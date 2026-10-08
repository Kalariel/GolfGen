from collections import Counter
from dataclasses import replace
import math

from golfgen.routing.geometry import (
    ValidationRules,
    build_hole_geometry,
    validate,
)
from golfgen.routing.model import (
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


def test_synthetic_layout_parallel_stack_matches_expected_consecutive_series():
    # Étape 2b (cliques maximales) comptait 0 `parallel_stack` sur ce layout :
    # chaque nine forme deux chaînes de voisinages deux à deux qui ne sont
    # jamais des cliques (le trou 1 ne touche pas le trou 3, etc.), donc la
    # définition par clique ne détectait aucune pile réelle. La nouvelle
    # définition (série de trous CONSÉCUTIFS dans l'ordre de jeu, chacun
    # `_side_by_side` avec le suivant, tous alignés deux à deux) retrouve bien
    # les 4 vraies piles de bandes parallèles du layout synthétique :
    # 1-2-3-4-5, 6-7-8-9, 10-11-12-13-14 et 15-16-17-18 (4 violations, comme
    # avant l'étape 2b). Les bornes diffèrent légèrement de l'estimation du
    # plan (2-5/11-14 au lieu de 1-5/10-14) : les trous 1 et 10, qui ouvrent
    # chaque nine, se trouvent être alignés et en recouvrement projeté avec
    # TOUS les trous de leur bande (pas seulement leur voisin immédiat), donc
    # la série maximale les inclut aussi.
    violations = [v for v in validate(build_synthetic_layout(), ValidationRules())
                  if v.kind == "parallel_stack"]

    assert sorted(v.holes for v in violations) == [
        (1, 2, 3, 4, 5), (6, 7, 8, 9), (10, 11, 12, 13, 14), (15, 16, 17, 18),
    ]


def _row(layout, orders, y_values, *, x_start=50.0, length=90.0,
         width=11.0, rough_margin=5.0):
    """Place des trous réalistes en bande horizontale (sans fairways
    superposés) : largeur et marge de rough comparables au layout
    synthétique, espacement entre rangées de 20 blocs (pas 6, irréaliste)."""
    for order, y in zip(orders, y_values):
        layout = _replace_hole(
            layout, order,
            tee=ControlPoint(x_start, y), green=ControlPoint(x_start + length, y),
            width=width, rough_margin=rough_margin,
        )
    return layout


def _fan(layout, orders, *, cx=0.0, cy=-300.0, step=10.0, angle_step_deg=15.0,
          length=90.0, width=11.0, rough_margin=5.0):
    """Éventail réaliste : chaque trou tourne de `angle_step_deg` par rapport
    au précédent et reste en contact avec lui (bande qui longe une courbe),
    mais les extrémités de la série finissent par dépasser le seuil
    d'angle (20°) entre elles."""
    theta = 0.0
    for order in orders:
        rad = math.radians(theta)
        dx, dy = math.cos(rad), math.sin(rad)
        tee = ControlPoint(cx - dx * length / 2.0, cy - dy * length / 2.0)
        green = ControlPoint(cx + dx * length / 2.0, cy + dy * length / 2.0)
        layout = _replace_hole(layout, order, tee=tee, green=green,
                                width=width, rough_margin=rough_margin)
        px, py = -math.sin(rad), math.cos(rad)
        cx += px * step
        cy += py * step
        theta += angle_step_deg
    return layout


def _sliding_row(layout, orders, x_values, *, y_start=-100.0, y_step=-20.0,
                  length=90.0, width=11.0, rough_margin=5.0):
    """Bande réaliste où chaque trou glisse en x par rapport au précédent
    (recouvrement projeté décroissant avec l'écart d'indice), pour casser
    l'alignement deux à deux entre des trous éloignés dans la série tout en
    gardant chaque voisin immédiat `_side_by_side` (même angle horizontal,
    contact par rangées espacées de 20 blocs)."""
    for index, (order, x) in enumerate(zip(orders, x_values)):
        y = y_start + y_step * index
        layout = _replace_hole(
            layout, order,
            tee=ControlPoint(x, y), green=ControlPoint(x + length, y),
            width=width, rough_margin=rough_margin,
        )
    return layout


def _parallel_stack_touching(layout, orders):
    """Violations `parallel_stack` impliquant au moins un des `orders`.

    Le layout synthétique porte déjà ses propres piles ailleurs (voir le
    test de décompte ci-dessus) ; les tests ci-dessous ne modifient que
    quelques trous et doivent ignorer ce bruit de fond sans rapport.
    """
    orders = set(orders)
    violations = validate(layout, ValidationRules())
    return [v for v in violations if v.kind == "parallel_stack" and set(v.holes) & orders]


def test_four_consecutive_holes_stacked_trigger_one_violation():
    # Vraie pile de 4 trous consécutifs (2-3-4-5), bande réaliste.
    layout = _row(build_synthetic_layout(), (2, 3, 4, 5),
                  (-100.0, -80.0, -60.0, -40.0))
    violations = _parallel_stack_touching(layout, (2, 3, 4, 5))

    assert len(violations) == 1
    assert violations[0].holes == (2, 3, 4, 5)


def test_three_consecutive_holes_stacked_trigger_no_violation():
    # Frontière : une série de taille exactement `max_parallel_stack` (3) ne
    # déclenche aucune violation, seule une taille strictement supérieure
    # compte.
    layout = _row(build_synthetic_layout(), (2, 3, 4),
                  (-100.0, -80.0, -60.0))

    assert _parallel_stack_touching(layout, (2, 3, 4)) == []


def test_four_stacked_holes_non_consecutive_order_trigger_no_violation():
    # Trous 2, 4, 6, 8 empilés côte à côte, mais 3, 5, 7 (laissés à leur
    # position d'origine) rompent la consécutivité dans l'ordre de jeu : la
    # série ne peut jamais s'étendre au-delà d'un trou isolé.
    layout = _row(build_synthetic_layout(), (2, 4, 6, 8),
                  (-100.0, -80.0, -60.0, -40.0))

    assert _parallel_stack_touching(layout, (2, 4, 6, 8)) == []


def test_four_stacked_holes_across_nines_non_consecutive_trigger_no_violation():
    # Trous 2, 5 (front) et 12, 15 (back) empilés côte à côte : ni
    # consécutifs dans leur nine, ni dans le même nine pour certains d'entre
    # eux, donc aucune série.
    layout = _row(build_synthetic_layout(), (2, 5, 12, 15),
                  (-100.0, -80.0, -60.0, -40.0))

    assert _parallel_stack_touching(layout, (2, 5, 12, 15)) == []


def test_rotating_fan_of_four_consecutive_holes_triggers_no_violation():
    # Éventail de 4 trous consécutifs (2-3-4-5), chaque voisin aligné à 15°
    # (`_side_by_side` vrai pour chaque paire adjacente), mais les extrémités
    # (2 et 4, 2 et 5, 3 et 5) dépassent 20° : la série entière n'est pas
    # alignée deux à deux, donc aucune pile parallèle n'est détectée malgré
    # la chaîne de contacts.
    layout = _fan(build_synthetic_layout(), (2, 3, 4, 5))

    assert _parallel_stack_touching(layout, (2, 3, 4, 5)) == []


def test_two_distinct_consecutive_series_produce_two_diagnostics():
    layout = _row(build_synthetic_layout(), (2, 3, 4, 5),
                  (-100.0, -80.0, -60.0, -40.0))
    layout = _row(layout, (6, 7, 8, 9),
                  (-500.0, -480.0, -460.0, -440.0))
    violations = _parallel_stack_touching(layout, (2, 3, 4, 5, 6, 7, 8, 9))

    assert sorted(v.holes for v in violations) == [(2, 3, 4, 5), (6, 7, 8, 9)]


def test_overlapping_maximal_series_both_reported():
    # 6 trous consécutifs (2 à 7) tous chaînés par contact (chaque voisin
    # `_side_by_side`), mais l'alignement deux à deux casse au milieu : le
    # trou 2 n'est plus aligné avec le trou 6 (recouvrement projeté 37 <= 40)
    # alors que le trou 3 reste aligné avec le trou 7 (recouvrement 70 > 40).
    # Deux séries maximales se chevauchent donc sans que l'une contienne
    # l'autre : [2..5] (le 2 ne peut pas s'étendre plus loin) et [3..7] (le 3
    # s'étend plus loin une fois le 2 écarté). Les deux sont des diagnostics
    # distincts, c'est voulu : chaque série maximale est signalée séparément,
    # même si elles partagent des trous (3, 4, 5).
    layout = _sliding_row(build_synthetic_layout(), (2, 3, 4, 5, 6, 7),
                          (0.0, 35.0, 41.0, 47.0, 53.0, 55.0))
    violations = _parallel_stack_touching(layout, (2, 3, 4, 5, 6, 7))

    assert sorted(v.holes for v in violations) == [(2, 3, 4, 5), (3, 4, 5, 6, 7)]


def test_series_does_not_merge_across_nine_boundary():
    # 7, 8, 9 (fin du front) et 10, 11, 12 (début du back) forment une seule
    # bande continue de 6 rangées : si la coupure 9→10 n'était pas respectée,
    # ce serait une pile de 6 trous (violation). Chaque nine ne porte que 3
    # de ces trous (taille au seuil, pas de violation), et la frontière de
    # nine empêche toute fusion.
    layout = _row(build_synthetic_layout(), (7, 8, 9, 10, 11, 12),
                  (-100.0, -80.0, -60.0, -40.0, -20.0, 0.0))

    assert _parallel_stack_touching(layout, (7, 8, 9, 10, 11, 12)) == []


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
