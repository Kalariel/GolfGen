from collections import Counter
from dataclasses import replace
import math

import pytest

from experiments.elastic_routing.geometry import (
    ValidationRules,
    build_hole_geometry,
    validate,
)
from experiments.elastic_routing.model import (
    PAR_SPECS,
    ControlPoint,
    CourseLayout,
    NineLayout,
)
from experiments.elastic_routing.synthetic import build_synthetic_layout


PERMISSIVE = ValidationRules(
    link_max=500.0,
    max_parallel_stack=None,
    clubhouse_clear_radius=0.0,
    walkable_links=False,
)


def _with_holes(layout, holes):
    holes = tuple(sorted(holes, key=lambda hole: hole.order))
    return CourseLayout(
        seed=layout.seed,
        width=layout.width,
        height=layout.height,
        clubhouse=layout.clubhouse,
        front=NineLayout.from_holes(1, layout.clubhouse, holes[:9]),
        back=NineLayout.from_holes(10, layout.clubhouse, holes[9:]),
    )


def _replace_hole(layout, order, **changes):
    holes = [replace(hole, **changes) if hole.order == order else hole
             for hole in layout.holes]
    return _with_holes(layout, holes)


def _kinds(layout, rules=PERMISSIVE):
    return {violation.kind for violation in validate(layout, rules)}


def test_synthetic_layout_is_valid_under_explicitly_permissive_rules():
    assert validate(build_synthetic_layout(), PERMISSIVE) == []


def test_validation_rules_reject_non_finite_and_ambiguous_values():
    with pytest.raises(ValueError, match="fini"):
        ValidationRules(fairway_gap=math.nan)
    with pytest.raises(TypeError, match="max_parallel_stack"):
        ValidationRules(max_parallel_stack=True)


def test_geometry_builds_core_and_larger_rough_from_elastic_axis():
    hole = build_synthetic_layout().holes[0]
    geometry = build_hole_geometry(hole)

    assert geometry.axis[0] == (hole.tee.x, hole.tee.y)
    assert geometry.axis[-1] == (hole.green.x, hole.green.y)
    assert len(geometry.core) == len(geometry.rough) == 2 * len(hole.axis)
    assert min(point[1] for point in geometry.rough) < min(point[1] for point in geometry.core)
    assert max(point[1] for point in geometry.rough) > max(point[1] for point in geometry.core)


def test_validator_reports_length_and_width_ranges():
    layout = build_synthetic_layout()
    first = layout.holes[0]
    broken = _replace_hole(
        layout,
        1,
        green=ControlPoint(first.tee.x + 10.0, first.tee.y),
        width=PAR_SPECS[3].width_min - 1.0,
    )

    assert {"length", "width"} <= _kinds(broken)


def test_validator_reports_core_outside_map():
    layout = build_synthetic_layout()
    broken = _replace_hole(
        layout,
        1,
        tee=ControlPoint(0.0, 20.0),
        green=ControlPoint(75.0, 20.0),
    )

    assert "bounds" in _kinds(broken)


def test_validator_reports_axis_crossing_and_fairway_gap():
    layout = build_synthetic_layout()
    broken = _replace_hole(
        layout,
        10,
        tee=ControlPoint(140.0, 140.0),
        green=ControlPoint(140.0, 215.0),
    )
    violations = validate(broken, PERMISSIVE)

    assert any(item.kind == "axis_crossing" and item.holes == (1, 10)
               for item in violations)
    assert any(item.kind == "fairway_gap" and item.holes == (1, 10)
               for item in violations)


def test_validator_reports_clubhouse_clearance():
    layout = build_synthetic_layout()
    broken = _replace_hole(
        layout,
        1,
        tee=ControlPoint(162.5, 200.0),
        green=ControlPoint(237.5, 200.0),
    )
    rules = replace(PERMISSIVE, clubhouse_clear_radius=10.0)

    assert "clubhouse_clear" in _kinds(broken, rules)


def test_final_rules_report_link_distance_and_blocking():
    violations = validate(build_synthetic_layout(), ValidationRules())
    counts = Counter(item.kind for item in violations)

    assert counts["link_distance"] > 0
    assert counts["link_blocked"] > 0


def test_synthetic_layout_has_no_parallel_stack_under_clique_detection():
    # Avant l'étape 2b, `_connected_components` comptait 4 violations
    # `parallel_stack` sur ce layout : chaque nine forme deux chaînes de trous
    # voisins qui se touchent deux à deux (1-2-3-4-5 et 6-7-8-9 côté front,
    # pareil côté back), union-find les fusionnait en une seule « pile » par
    # chaîne. Mais aucun triplet de cette chaîne n'est une clique (le trou 1
    # ne touche pas le trou 3, etc.) : ce n'est pas une pile parallèle au sens
    # de la définition (clique maximale), seulement une suite de voisinages.
    # Avec Bron–Kerbosch, les cliques maximales de ce graphe sont toutes des
    # arêtes isolées (taille 2), sous le seuil `max_parallel_stack=3` : 0
    # violation `parallel_stack`, et non plus 4.
    violations = validate(build_synthetic_layout(), ValidationRules())
    counts = Counter(item.kind for item in violations)

    assert counts["parallel_stack"] == 0


def _stack(layout, orders, y_values, x_start=50.0, length=90.0):
    for order, y in zip(orders, y_values):
        layout = _replace_hole(
            layout, order,
            tee=ControlPoint(x_start, y), green=ControlPoint(x_start + length, y),
            width=12.0, rough_margin=5.0,
        )
    return layout


def test_true_clique_of_four_holes_triggers_one_parallel_stack_violation():
    # 4 trous parallèles, alignés, qui se recouvrent tous deux à deux (écart
    # 6 blocs, rayon de rough 11 : même les deux trous les plus éloignés se
    # touchent) : une vraie clique de taille 4, hors carte pour l'isoler de
    # tout le reste du layout.
    layout = _stack(build_synthetic_layout(), (2, 3, 4, 5),
                     (-100.0, -94.0, -88.0, -82.0))
    violations = [v for v in validate(layout, ValidationRules()) if v.kind == "parallel_stack"]

    assert len(violations) == 1
    assert violations[0].holes == (2, 3, 4, 5)


def test_true_clique_of_exactly_max_size_triggers_no_violation():
    # Frontière : une vraie clique de taille exactement égale à
    # max_parallel_stack (3) ne doit déclencher aucune violation, seule une
    # taille strictement supérieure au seuil (len(clique) > max) compte.
    layout = _stack(build_synthetic_layout(), (2, 3, 4),
                     (-100.0, -94.0, -88.0))
    violations = [v for v in validate(layout, ValidationRules()) if v.kind == "parallel_stack"]

    assert violations == []


def test_chain_without_pairwise_parallelism_triggers_no_parallel_stack():
    # A-B, B-C, C-D se touchent (écart 15, rayon 11 : 15-22<0) mais A-C, B-D,
    # A-D ne se touchent pas (écart >= 30, 30-22>0) : chaîne sans triangle,
    # aucune clique de taille > 3.
    layout = _stack(build_synthetic_layout(), (2, 3, 4, 5),
                     (-300.0, -285.0, -270.0, -255.0))
    violations = [v for v in validate(layout, ValidationRules()) if v.kind == "parallel_stack"]

    assert violations == []


def test_two_distinct_faulty_cliques_produce_two_diagnostics():
    layout = _stack(build_synthetic_layout(), (2, 3, 4, 5),
                     (-100.0, -94.0, -88.0, -82.0))
    layout = _stack(layout, (6, 7, 8, 9),
                     (-500.0, -494.0, -488.0, -482.0))
    violations = [v for v in validate(layout, ValidationRules()) if v.kind == "parallel_stack"]

    assert sorted(v.holes for v in violations) == [(2, 3, 4, 5), (6, 7, 8, 9)]


def test_validator_reports_per_nine_par_bounds_while_global_quota_stays_exact():
    layout = build_synthetic_layout()

    def reclassify(pars):
        holes = []
        for hole, par in zip(layout.holes, pars):
            direction = 1.0 if hole.green.x > hole.tee.x else -1.0
            holes.append(replace(
                hole,
                par=par,
                green=ControlPoint(hole.tee.x + direction * PAR_SPECS[par].length_min,
                                   hole.tee.y),
                width=PAR_SPECS[par].width_min,
            ))
        return _with_holes(layout, holes)

    par5_unbalanced = reclassify(
        (3, 3, 4, 4, 4, 4, 4, 4, 4, 3, 3, 4, 4, 4, 5, 5, 5, 5)
    )
    par3_unbalanced = reclassify(
        (4, 4, 4, 4, 4, 4, 4, 5, 5, 3, 3, 3, 3, 4, 4, 4, 5, 5)
    )

    assert sum(item.kind == "par5_per_nine"
               for item in validate(par5_unbalanced, PERMISSIVE)) == 2
    assert sum(item.kind == "par3_per_nine"
               for item in validate(par3_unbalanced, PERMISSIVE)) == 2


def test_validator_reports_rule_and_layout_map_size_mismatch():
    rules = replace(PERMISSIVE, width=399.0)
    assert "map_size" in _kinds(build_synthetic_layout(), rules)
