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

from golfgen.routing.geometry import ValidationRules, validate
from experiments.elastic_routing.incremental import COMPONENT_NAMES, IncrementalEvaluator
from golfgen.routing.model import ControlPoint, CourseLayout, ElasticHole, NineLayout, PAR_SPECS
from experiments.elastic_routing.synthetic import NINE_PARS, build_synthetic_layout


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
    broken = _replace_hole(layout, 1, tee=ControlPoint(140.0, 200.0), green=ControlPoint(140.0, 260.0), width=10.0)
    broken = _replace_hole(broken, 10, tee=ControlPoint(155.3, 200.0), green=ControlPoint(155.3, 260.0), width=10.0)

    assert validate(broken, PERMISSIVE) == []  # l'oracle juge ce layout valide

    score = IncrementalEvaluator(broken, PERMISSIVE).score()
    assert score.ecarts > 0.0  # le surrogate, pessimiste par construction, le signale


# -- (a-bis) propriété seedée : zéro faux négatif, faux positifs mesurés ----

def _layout_scale(layout: CourseLayout) -> float:
    """Longueur de trou moyenne du layout : unité de perturbation relative,
    pour que les mêmes fonctions de perturbation restent proportionnées sur
    le layout synthétique (trous ~75-235) et sur la boucle compacte de
    ``_clean_liaisons_layout`` (trous ~25) — sans quoi des décalages
    absolus calibrés sur le premier écrasent la géométrie du second et
    gonflent artificiellement le taux de faux positifs mesuré."""
    return sum(hole.length for hole in layout.holes) / len(layout.holes)


def _add_sharp_dogleg(hole, rng: random.Random, scale: float):
    """Ajoute un dogleg à virage serré, pour stresser le joint en onglet."""
    tee, green = hole.tee, hole.green
    mx, my = (tee.x + green.x) / 2.0, (tee.y + green.y) / 2.0
    dx, dy = green.x - tee.x, green.y - tee.y
    length = math.hypot(dx, dy) or 1.0
    nx, ny = -dy / length, dx / length
    offset = rng.uniform(0.04 * scale, 0.16 * scale) * rng.choice((-1, 1))
    return replace(hole, doglegs=(ControlPoint(mx + nx * offset, my + ny * offset),))


def _nudge_hole(hole, rng: random.Random, scale: float):
    spread = 0.08 * scale
    dx1, dy1 = rng.uniform(-spread, spread), rng.uniform(-spread, spread)
    dx2, dy2 = rng.uniform(-spread, spread), rng.uniform(-spread, spread)
    return replace(hole,
                    tee=ControlPoint(hole.tee.x + dx1, hole.tee.y + dy1),
                    green=ControlPoint(hole.green.x + dx2, hole.green.y + dy2))


def _force_close_pair(layout: CourseLayout, rng: random.Random, scale: float) -> CourseLayout:
    """Place un trou tout près (bout à bout) d'un autre : stresse les cas
    « près des extrémités » (axe étendu) et les écarts proches du seuil.
    Le jeu (``gap``) teste la proximité du seuil fairway_gap (indépendant de
    l'échelle du layout, même largeurs de trou des deux côtés) ; la longueur
    du trou déplacé est, elle, relative à ``scale`` pour ne pas déborder sur
    tout le reste d'un petit layout."""
    holes = {hole.order: hole for hole in layout.holes}
    anchor_order, moved_order = rng.sample(range(1, 19), 2)
    anchor = holes[anchor_order]
    gap = rng.uniform(-2.0, 10.0)
    angle = rng.uniform(0.0, 2 * math.pi)
    base = ControlPoint(anchor.tee.x + gap * math.cos(angle), anchor.tee.y + gap * math.sin(angle))
    direction = rng.uniform(0.0, 2 * math.pi)
    length = rng.uniform(0.6 * scale, 1.0 * scale)
    holes[moved_order] = replace(
        holes[moved_order], tee=base,
        green=ControlPoint(base.x + length * math.cos(direction), base.y + length * math.sin(direction)),
    )
    return _with_holes(layout, holes.values())


def _force_near_clubhouse(layout: CourseLayout, rng: random.Random, scale: float) -> CourseLayout:
    holes = {hole.order: hole for hole in layout.holes}
    order = rng.choice(range(1, 19))
    distance = rng.uniform(0.0, 20.0)
    angle = rng.uniform(0.0, 2 * math.pi)
    tee = ControlPoint(layout.clubhouse.x + distance * math.cos(angle),
                        layout.clubhouse.y + distance * math.sin(angle))
    direction = rng.uniform(0.0, 2 * math.pi)
    length = rng.uniform(0.6 * scale, 1.0 * scale)
    green = ControlPoint(tee.x + length * math.cos(direction), tee.y + length * math.sin(direction))
    holes[order] = replace(holes[order], tee=tee, green=green)
    return _with_holes(layout, holes.values())


def _loop_nine(start_order: int, center, radius: float, rotation: float, gap: float):
    """Neuf trous disposés en boucle (ennéagone) : chaque trou occupe une
    arête, un petit jeu ``gap`` de chaque côté du sommet laisse place à la
    liaison. Le sommet d'indice 0 (partagé par le premier tee et le dernier
    green) sert de point d'ancrage pour le clubhouse."""
    vertices = [
        (center[0] + radius * math.cos(rotation + 2 * math.pi * i / 9),
         center[1] + radius * math.sin(rotation + 2 * math.pi * i / 9))
        for i in range(10)
    ]
    holes = []
    for index, (order, par) in enumerate(zip(range(start_order, start_order + 9), NINE_PARS)):
        start, end = vertices[index], vertices[index + 1]
        dx, dy = end[0] - start[0], end[1] - start[1]
        edge_length = math.hypot(dx, dy)
        ux, uy = dx / edge_length, dy / edge_length
        tee = ControlPoint(start[0] + ux * gap, start[1] + uy * gap)
        green = ControlPoint(end[0] - ux * gap, end[1] - uy * gap)
        holes.append(ElasticHole(order=order, par=par, tee=tee, green=green,
                                 width=PAR_SPECS[par].width_min))
    return tuple(holes)


def _clean_liaisons_layout() -> CourseLayout:
    """Parcours fixe (hors classe des longueurs, non testée ici) où toutes
    les liaisons sont praticables : deux boucles à 9 trous tangentes en un
    seul point (cercles de même rayon, centres diamétralement opposés par
    rapport à ce point => tangence externe, aucun autre recouvrement),
    décalées d'un petit ``d`` pour que les deux trous du seuil (front/back)
    gardent un écart fairway correct. Sert à mesurer le taux de faux
    positifs de la composante ``liaisons`` sur une base où l'oracle ne
    signale ni ``link_distance`` ni ``link_blocked`` (contrairement au
    layout synthétique, qui les viole déjà near clubhouse).

    ``gap`` choisi assez grand (20, pas le minimum qui tient dans
    ``[12, 45]``) pour que l'estimation surrogate du sommet partagé entre
    deux trous consécutifs (capsules à bouts ronds qui comblent le creux
    concave du virage plus que le polygone réel — cf. docstring de module)
    reste, elle aussi, au-dessus du seuil fairway_gap à l'état non perturbé
    (vérifié : pénalité ``ecarts`` surrogate nulle partout avant
    perturbation). Avec un ``gap`` trop petit (15), ce même calcul
    surrogate franchissait déjà le seuil sans perturbation — un faux positif
    *systématique*, pas une mesure utile du taux de faux positifs."""
    radius, gap, offset, shift = 80.0, 20.0, 20.0, 1000.0
    front = _loop_nine(1, (radius + offset, 0.0), radius, math.pi, gap)
    back = _loop_nine(10, (-(radius + offset), 0.0), radius, 0.0, gap)

    def shifted(hole):
        return replace(hole, tee=ControlPoint(hole.tee.x + shift, hole.tee.y + shift),
                       green=ControlPoint(hole.green.x + shift, hole.green.y + shift))

    clubhouse = ControlPoint(shift, shift)
    return CourseLayout(
        seed=0, width=3000.0, height=3000.0, clubhouse=clubhouse,
        front=NineLayout.from_holes(1, clubhouse, tuple(shifted(h) for h in front)),
        back=NineLayout.from_holes(10, clubhouse, tuple(shifted(h) for h in back)),
    )


def _perturbed_layout(layout: CourseLayout, rng: random.Random) -> CourseLayout:
    scale = _layout_scale(layout)
    mode = rng.random()
    if mode < 0.35:
        holes = {hole.order: hole for hole in layout.holes}
        for order in rng.sample(range(1, 19), rng.randint(1, 3)):
            hole = holes[order]
            if rng.random() < 0.5:
                hole = _add_sharp_dogleg(hole, rng, scale)
            holes[order] = _nudge_hole(hole, rng, scale)
        return _with_holes(layout, holes.values())
    if mode < 0.65:
        return _force_close_pair(layout, rng, scale)
    return _force_near_clubhouse(layout, rng, scale)


def test_surrogate_has_zero_false_negatives_on_seeded_perturbations():
    """Propriété (300 layouts perturbés seedés, dont des cas proches des
    extrémités et des doglegs à virage serré) : pour fairway_gap,
    clubhouse_clear et link_blocked, dès que l'oracle signale une violation,
    la composante surrogate correspondante est strictement positive — zéro
    faux négatif. Les faux positifs (surrogate > 0 sans violation oracle,
    attendus par construction pessimiste) sont comptés et rapportés, sans
    assertion stricte dessus.

    Deux layouts de base alternés : le layout synthétique (qui viole déjà
    ``link_distance``/``link_blocked`` près du clubhouse, donc mesure bien le
    zéro faux négatif de ``liaisons``) et ``_clean_liaisons_layout`` (dont
    aucune liaison n'est violée avant perturbation, donc mesure aussi le taux
    de faux positifs de ``liaisons`` — jamais testé sinon, le layout
    synthétique seul violant ``link_blocked`` dans 100% des échantillons).

    Le taux de faux positifs ``ecarts`` est rapporté globalement ET par
    layout de base (``-s`` pour le voir) : il est nettement plus élevé sur
    ``_clean_liaisons_layout`` que sur le synthétique, pour une raison
    géométrique comprise et documentée dans ``incremental.py`` (capsules
    voisines à un sommet d'angle partagé, pas un bug ni un faux négatif —
    voir le docstring de module, section « Source de faux positifs
    distincte »).
    """
    rng = random.Random(777)
    bases = (build_synthetic_layout, _clean_liaisons_layout)
    mapping = (("fairway_gap", "ecarts"), ("clubhouse_clear", "clubhouse"), ("link_blocked", "liaisons"))

    def _empty_stats():
        return {
            "fpo": {component: 0 for _, component in mapping},
            "fp": {component: 0 for _, component in mapping},
            "occ": {kind: 0 for kind, _ in mapping},
        }

    overall = _empty_stats()
    per_base = {base.__name__: _empty_stats() for base in bases}

    for _ in range(300):
        base_fn = bases[rng.randrange(len(bases))]
        layout = _perturbed_layout(base_fn(), rng)
        rules = ValidationRules(width=layout.width, height=layout.height)
        kinds = {violation.kind for violation in validate(layout, rules)}
        score = IncrementalEvaluator(layout, rules).score()
        for stats in (overall, per_base[base_fn.__name__]):
            for kind, component in mapping:
                value = getattr(score, component)
                if kind in kinds:
                    stats["occ"][kind] += 1
                    assert value > 0.0, f"faux négatif : oracle={kind}, surrogate={component}=0"
                else:
                    stats["fpo"][component] += 1
                    if value > 0.0:
                        stats["fp"][component] += 1

    def _rates(stats):
        return {
            component: (stats["fp"][component] / stats["fpo"][component] if stats["fpo"][component] else None)
            for _, component in mapping
        }

    print("occurrences oracle (global) :", overall["occ"])
    print("taux de faux positifs (global, surrogate pessimiste, attendu) :", _rates(overall))
    for name, stats in per_base.items():
        print(f"  dont {name} : occurrences={stats['occ']} taux_fp={_rates(stats)}")


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
