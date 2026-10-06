"""Tests du surrogate incrémental de l'étape 4.

Conventions reprises de ``test_elastic_routing_geometry.py`` : ``PERMISSIVE``
désactive les contraintes non testées, ``_with_holes``/``_replace_hole``
reconstruisent un ``CourseLayout`` valide depuis des trous modifiés.
"""

from __future__ import annotations

from dataclasses import replace
import math
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


def test_surrogate_margin_can_over_report_a_near_threshold_fairway_gap():
    """Écart documenté : le surrogate traite chaque trou comme une capsule à
    bouts ronds bâtie sur un axe étendu de ``half_width`` à chaque bout (pour
    contenir le rectangle à bout plat de l'oracle), et retranche une marge
    forfaitaire (``conservative_margin``, 1.0 bloc par défaut) — plus, si le
    trou a un dogleg, une marge d'onglet (``half_width * (1/0.72 - 1)``) — de
    la distance axe-à-axe, pour ne jamais *manquer* un écart réel (joints
    biseautés et extrémités prolongées de ``geometry.buffered_axis``). Il
    peut donc signaler un écart fairway que l'oracle polygonal juge valide,
    tant que l'écart réel est à moins de cette marge du seuil : ce faux
    positif est résolu par l'oracle complet, périodiquement (PLAN.md,
    point c), pas par ce surrogate. Voir aussi le test de propriété
    ci-dessous pour une mesure du taux de faux positifs sur un échantillon.
    """
    layout = build_synthetic_layout()
    broken = _replace_hole(layout, 1, tee=ControlPoint(140.0, 200.0), green=ControlPoint(140.0, 290.0), width=10.0)
    broken = _replace_hole(broken, 10, tee=ControlPoint(155.3, 200.0), green=ControlPoint(155.3, 290.0), width=10.0)

    assert validate(broken, PERMISSIVE) == []  # l'oracle juge ce layout valide

    score = IncrementalEvaluator(broken, PERMISSIVE).score()
    assert score.ecarts > 0.0  # le surrogate, pessimiste par construction, le signale


# -- (a-bis) propriété seedée : zéro faux négatif, faux positifs mesurés ----

def _add_sharp_dogleg(hole, rng: random.Random):
    """Ajoute un dogleg à virage serré, pour stresser le joint en onglet."""
    tee, green = hole.tee, hole.green
    mx, my = (tee.x + green.x) / 2.0, (tee.y + green.y) / 2.0
    dx, dy = green.x - tee.x, green.y - tee.y
    length = math.hypot(dx, dy) or 1.0
    nx, ny = -dy / length, dx / length
    offset = rng.uniform(5.0, 20.0) * rng.choice((-1, 1))
    return replace(hole, doglegs=(ControlPoint(mx + nx * offset, my + ny * offset),))


def _nudge_hole(hole, rng: random.Random, spread: float = 10.0):
    dx1, dy1 = rng.uniform(-spread, spread), rng.uniform(-spread, spread)
    dx2, dy2 = rng.uniform(-spread, spread), rng.uniform(-spread, spread)
    return replace(hole,
                    tee=ControlPoint(hole.tee.x + dx1, hole.tee.y + dy1),
                    green=ControlPoint(hole.green.x + dx2, hole.green.y + dy2))


def _force_close_pair(layout: CourseLayout, rng: random.Random) -> CourseLayout:
    """Place un trou tout près (bout à bout) d'un autre : stresse les cas
    « près des extrémités » (axe étendu) et les écarts proches du seuil."""
    holes = {hole.order: hole for hole in layout.holes}
    anchor_order, moved_order = rng.sample(range(1, 19), 2)
    anchor = holes[anchor_order]
    gap = rng.uniform(-2.0, 10.0)
    angle = rng.uniform(0.0, 2 * math.pi)
    base = ControlPoint(anchor.tee.x + gap * math.cos(angle), anchor.tee.y + gap * math.sin(angle))
    direction = rng.uniform(0.0, 2 * math.pi)
    length = rng.uniform(80.0, 120.0)
    holes[moved_order] = replace(
        holes[moved_order], tee=base,
        green=ControlPoint(base.x + length * math.cos(direction), base.y + length * math.sin(direction)),
    )
    return _with_holes(layout, holes.values())


def _force_near_clubhouse(layout: CourseLayout, rng: random.Random) -> CourseLayout:
    holes = {hole.order: hole for hole in layout.holes}
    order = rng.choice(range(1, 19))
    distance = rng.uniform(0.0, 20.0)
    angle = rng.uniform(0.0, 2 * math.pi)
    tee = ControlPoint(layout.clubhouse.x + distance * math.cos(angle),
                        layout.clubhouse.y + distance * math.sin(angle))
    direction = rng.uniform(0.0, 2 * math.pi)
    length = rng.uniform(80.0, 120.0)
    green = ControlPoint(tee.x + length * math.cos(direction), tee.y + length * math.sin(direction))
    holes[order] = replace(holes[order], tee=tee, green=green)
    return _with_holes(layout, holes.values())


def _perturbed_layout(layout: CourseLayout, rng: random.Random) -> CourseLayout:
    mode = rng.random()
    if mode < 0.35:
        holes = {hole.order: hole for hole in layout.holes}
        for order in rng.sample(range(1, 19), rng.randint(1, 3)):
            hole = holes[order]
            if rng.random() < 0.5:
                hole = _add_sharp_dogleg(hole, rng)
            holes[order] = _nudge_hole(hole, rng)
        return _with_holes(layout, holes.values())
    if mode < 0.65:
        return _force_close_pair(layout, rng)
    return _force_near_clubhouse(layout, rng)


def test_surrogate_has_zero_false_negatives_on_seeded_perturbations():
    """Propriété (300 layouts perturbés seedés, dont des cas proches des
    extrémités et des doglegs à virage serré) : pour fairway_gap,
    clubhouse_clear et link_blocked, dès que l'oracle signale une violation,
    la composante surrogate correspondante est strictement positive — zéro
    faux négatif. Les faux positifs (surrogate > 0 sans violation oracle,
    attendus par construction pessimiste) sont comptés et rapportés, sans
    assertion stricte dessus.
    """
    rng = random.Random(777)
    rules = ValidationRules()
    mapping = (("fairway_gap", "ecarts"), ("clubhouse_clear", "clubhouse"), ("link_blocked", "liaisons"))
    false_positive_opportunities = {component: 0 for _, component in mapping}
    false_positives = {component: 0 for _, component in mapping}
    oracle_occurrences = {kind: 0 for kind, _ in mapping}

    for _ in range(300):
        layout = _perturbed_layout(build_synthetic_layout(), rng)
        kinds = {violation.kind for violation in validate(layout, rules)}
        score = IncrementalEvaluator(layout, rules).score()
        for kind, component in mapping:
            value = getattr(score, component)
            if kind in kinds:
                oracle_occurrences[kind] += 1
                assert value > 0.0, f"faux négatif : oracle={kind}, surrogate={component}=0"
            else:
                false_positive_opportunities[component] += 1
                if value > 0.0:
                    false_positives[component] += 1

    rates = {
        component: (false_positives[component] / false_positive_opportunities[component]
                    if false_positive_opportunities[component] else None)
        for _, component in mapping
    }
    print("occurrences oracle :", oracle_occurrences)
    print("taux de faux positifs (surrogate pessimiste, attendu) :", rates)


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
