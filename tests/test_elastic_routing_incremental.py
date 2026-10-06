"""Tests du surrogate incrémental de l'étape 4.

Conventions reprises de ``test_elastic_routing_geometry.py`` : ``PERMISSIVE``
désactive les contraintes non testées, ``_with_holes``/``_replace_hole``
reconstruisent un ``CourseLayout`` valide depuis des trous modifiés.
"""

from __future__ import annotations

from dataclasses import replace
import random

import pytest

from experiments.elastic_routing.geometry import ValidationRules, validate
from experiments.elastic_routing.incremental import COMPONENT_NAMES, IncrementalEvaluator
from experiments.elastic_routing.model import ControlPoint, CourseLayout, NineLayout, PAR_SPECS
from experiments.elastic_routing.synthetic import build_synthetic_layout


PERMISSIVE = ValidationRules(
    link_max=500.0,
    max_parallel_stack=None,
    clubhouse_clear_radius=0.0,
    walkable_links=False,
)

# Composantes jamais calculées par ce surrogate (parallel_stack réécrit
# ailleurs ; variete/deformation sont des objectifs souples pas encore
# définis par l'oracle). Toujours 0, vérifié une fois pour toutes.
NOT_YET_IMPLEMENTED = ("parallelisme", "variete", "deformation")


def _with_holes(layout: CourseLayout, holes) -> CourseLayout:
    holes = tuple(sorted(holes, key=lambda hole: hole.order))
    return CourseLayout(
        seed=layout.seed,
        width=layout.width,
        height=layout.height,
        clubhouse=layout.clubhouse,
        front=NineLayout.from_holes(1, layout.clubhouse, holes[:9]),
        back=NineLayout.from_holes(10, layout.clubhouse, holes[9:]),
    )


def _replace_hole(layout: CourseLayout, order: int, **changes) -> CourseLayout:
    holes = [replace(hole, **changes) if hole.order == order else hole for hole in layout.holes]
    return _with_holes(layout, holes)


# -- (a) cohérence surrogate / oracle ---------------------------------------

def test_permissive_layout_has_every_known_component_at_zero():
    layout = build_synthetic_layout()
    assert validate(layout, PERMISSIVE) == []

    score = IncrementalEvaluator(layout, PERMISSIVE).score()
    for name in COMPONENT_NAMES:
        assert getattr(score, name) == 0.0, name


def test_not_yet_implemented_components_are_always_zero():
    layout = build_synthetic_layout()
    score = IncrementalEvaluator(layout, ValidationRules()).score()
    for name in NOT_YET_IMPLEMENTED:
        assert getattr(score, name) == 0.0


def test_length_and_width_violations_raise_the_longueurs_component():
    layout = build_synthetic_layout()
    first = layout.holes[0]
    broken = _replace_hole(
        layout, 1,
        green=ControlPoint(first.tee.x + 10.0, first.tee.y),
        width=PAR_SPECS[3].width_min - 1.0,
    )
    assert {"length", "width"} <= {v.kind for v in validate(broken, PERMISSIVE)}

    score = IncrementalEvaluator(broken, PERMISSIVE).score()
    assert score.longueurs > 0.0
    for name in COMPONENT_NAMES:
        if name not in ("longueurs",):
            assert getattr(score, name) == 0.0, name


def test_bounds_violation_raises_the_topologie_component():
    layout = build_synthetic_layout()
    broken = _replace_hole(layout, 1, tee=ControlPoint(0.0, 20.0), green=ControlPoint(75.0, 20.0))
    assert "bounds" in {v.kind for v in validate(broken, PERMISSIVE)}

    score = IncrementalEvaluator(broken, PERMISSIVE).score()
    assert score.topologie > 0.0


def test_axis_crossing_and_fairway_gap_raise_croisements_and_ecarts():
    layout = build_synthetic_layout()
    broken = _replace_hole(layout, 10, tee=ControlPoint(140.0, 140.0), green=ControlPoint(140.0, 215.0))
    violations = validate(broken, PERMISSIVE)
    assert any(v.kind == "axis_crossing" and v.holes == (1, 10) for v in violations)
    assert any(v.kind == "fairway_gap" and v.holes == (1, 10) for v in violations)

    score = IncrementalEvaluator(broken, PERMISSIVE).score()
    assert score.croisements > 0.0
    assert score.ecarts > 0.0


def test_clubhouse_clearance_raises_the_clubhouse_component():
    layout = build_synthetic_layout()
    broken = _replace_hole(layout, 1, tee=ControlPoint(162.5, 200.0), green=ControlPoint(237.5, 200.0))
    rules = replace(PERMISSIVE, clubhouse_clear_radius=10.0)
    assert "clubhouse_clear" in {v.kind for v in validate(broken, rules)}

    score = IncrementalEvaluator(broken, rules).score()
    assert score.clubhouse > 0.0


def test_final_rules_link_distance_and_blocked_raise_the_liaisons_component():
    layout = build_synthetic_layout()
    violations = validate(layout, ValidationRules())
    assert sum(v.kind == "link_distance" for v in violations) > 0
    assert sum(v.kind == "link_blocked" for v in violations) > 0

    score = IncrementalEvaluator(layout, ValidationRules()).score()
    assert score.liaisons > 0.0
    for name in COMPONENT_NAMES:
        if name != "liaisons":
            assert getattr(score, name) == 0.0, name


def test_nine_par_bounds_violation_raises_the_topologie_component():
    layout = build_synthetic_layout()

    def reclassify(pars):
        holes = []
        for hole, par in zip(layout.holes, pars):
            direction = 1.0 if hole.green.x > hole.tee.x else -1.0
            holes.append(replace(
                hole, par=par,
                green=ControlPoint(hole.tee.x + direction * PAR_SPECS[par].length_min, hole.tee.y),
                width=PAR_SPECS[par].width_min,
            ))
        return _with_holes(layout, holes)

    par5_unbalanced = reclassify((3, 3, 4, 4, 4, 4, 4, 4, 4, 3, 3, 4, 4, 4, 5, 5, 5, 5))
    violations = validate(par5_unbalanced, PERMISSIVE)
    assert sum(v.kind == "par5_per_nine" for v in violations) == 2

    score = IncrementalEvaluator(par5_unbalanced, PERMISSIVE).score()
    assert score.topologie > 0.0


def test_conservative_margin_can_over_report_a_near_threshold_fairway_gap():
    """Écart documenté : le surrogate traite chaque trou comme une capsule et
    retranche une marge conservatrice (``conservative_margin``, 1.0 bloc par
    défaut) de la distance axe-à-axe pour ne jamais *manquer* un écart réel
    (joints biseautés de l'oracle, cf. ``geometry.buffered_axis``). Il peut
    donc signaler un écart fairway que l'oracle polygonal juge valide, tant
    que l'écart réel est à moins de ``conservative_margin`` du seuil : ce
    faux positif est résolu par l'oracle complet, périodiquement (PLAN.md,
    point c), pas par ce surrogate.
    """
    layout = build_synthetic_layout()
    broken = _replace_hole(layout, 1, tee=ControlPoint(140.0, 200.0), green=ControlPoint(140.0, 290.0), width=10.0)
    broken = _replace_hole(broken, 10, tee=ControlPoint(155.3, 200.0), green=ControlPoint(155.3, 290.0), width=10.0)

    assert validate(broken, PERMISSIVE) == []  # l'oracle juge ce layout valide

    score = IncrementalEvaluator(broken, PERMISSIVE).score()
    assert score.ecarts > 0.0  # le surrogate, pessimiste par construction, le signale


# -- (b) incrémental == recalcul complet ------------------------------------

def _random_hole_variant(hole, rng: random.Random):
    dx, dy = rng.uniform(-3.0, 3.0), rng.uniform(-3.0, 3.0)
    axis = "tee" if rng.random() < 0.5 else "green"
    point = getattr(hole, axis)
    return replace(hole, **{axis: ControlPoint(point.x + dx, point.y + dy)})


def test_incremental_matches_full_recompute_after_seeded_mutation_sequence_with_reverts():
    layout = build_synthetic_layout()
    evaluator = IncrementalEvaluator(layout, ValidationRules())
    rng = random.Random(1234)
    history: list = []

    for step in range(24):
        k = 3 if step % 5 == 0 else 1
        if k == 1:
            order = rng.randint(1, 18)
            orders = [order]
        else:
            start = rng.randint(1, 16)
            orders = [start, start + 1, start + 2]

        holes_by_order = {hole.order: hole for hole in evaluator.to_layout().holes}
        mutated = [_random_hole_variant(holes_by_order[order], rng) for order in orders]
        history.append(tuple(orders))

        evaluator.apply(mutated)
        fresh = IncrementalEvaluator(evaluator.to_layout(), ValidationRules())
        assert evaluator.score() == fresh.score()

        if step % 2 == 1:
            evaluator.revert()
            # après un revert, un recalcul complet depuis le layout courant
            # doit retomber sur le même score que l'évaluateur incrémental.
            fresh_after_revert = IncrementalEvaluator(evaluator.to_layout(), ValidationRules())
            assert evaluator.score() == fresh_after_revert.score()


def test_revert_without_prior_apply_raises():
    layout = build_synthetic_layout()
    evaluator = IncrementalEvaluator(layout)
    with pytest.raises(RuntimeError):
        evaluator.revert()


def test_apply_rejects_duplicate_orders():
    layout = build_synthetic_layout()
    evaluator = IncrementalEvaluator(layout)
    hole = layout.holes[0]
    with pytest.raises(ValueError):
        evaluator.apply((hole, hole))


# -- (c) déterminisme --------------------------------------------------------

def test_mutation_sequence_is_deterministic():
    def run():
        layout = build_synthetic_layout()
        evaluator = IncrementalEvaluator(layout, ValidationRules())
        rng = random.Random(42)
        totals = []
        for step in range(20):
            order = rng.randint(1, 18)
            holes_by_order = {hole.order: hole for hole in evaluator.to_layout().holes}
            mutated = _random_hole_variant(holes_by_order[order], rng)
            evaluator.apply(mutated)
            totals.append(evaluator.score().as_dict())
            if step % 3 == 0:
                evaluator.revert()
                totals.append(evaluator.score().as_dict())
        return totals

    assert run() == run()
