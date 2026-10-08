"""Étape M : routage Muirfield (``muirfield.py``, ``partial_checks.py``, ``sites.py``).

R2 est une porte de validité : zéro violation de l'oracle final sur les
seeds 1–6 pour les deux formats de carte rectangulaires (300×400 et
350×400), par construction (contrôles en ligne, ancrages 1/9/10/18, retour
arrière borné, relances). Le relief est mis en cache sur disque
(``output/.cache``) : premier passage ~5 s par seed et par format.
"""

from __future__ import annotations

from collections import Counter
import math

import numpy as np
import pytest

from experiments.elastic_routing import muirfield as mf
from experiments.elastic_routing.geometry import ValidationRules, Violation, validate
from experiments.elastic_routing.model import GLOBAL_PAR_QUOTA, PAR_SPECS, ControlPoint, ElasticHole
from experiments.elastic_routing.partial_checks import Obstacles, PartialLayout, PlannedLink
from experiments.elastic_routing.render_readable import render_readable_svg
from experiments.elastic_routing import sites as sites_module
from experiments.elastic_routing.sites import (
    GREEN_SPACING,
    TEE_SPACING,
    WATER_LEVEL,
    build_sites,
    load_terrain,
    min_pairwise_distance,
)


SEEDS = (1, 2, 3, 4, 5, 6)
FORMATS = ((300, 400), (350, 400))
CASES = [(w, h, seed) for w, h in FORMATS for seed in SEEDS]


@pytest.fixture(scope="module")
def results():
    return {(w, h, seed): mf.build_muirfield(seed, width=w, height=h) for w, h, seed in CASES}


@pytest.mark.parametrize("case", CASES, ids=lambda c: f"{c[0]}x{c[1]}-s{c[2]}")
def test_zero_final_violations(results, case):
    result = results[case]
    assert result.violations == ()
    w, h, _ = case
    assert validate(result.layout, ValidationRules(width=w, height=h)) == []


def test_build_is_deterministic(results):
    again = mf.build_muirfield(3, width=350, height=400)
    assert again.layout.to_json() == results[(350, 400, 3)].layout.to_json()
    assert again.attempts == results[(350, 400, 3)].attempts


@pytest.mark.parametrize("case", CASES, ids=lambda c: f"{c[0]}x{c[1]}-s{c[2]}")
def test_search_budgets_are_bounded(results, case):
    attempts = results[case].attempts
    max_attempts = mf.CLUBHOUSE_POSITIONS * mf.PAR_PERMUTATIONS * len(mf.START_ANGLES)
    assert 1 <= len(attempts) <= max_attempts
    for attempt in attempts:
        assert attempt["checks"] <= 2 * mf.CHECK_BUDGET_PER_NINE
        assert attempt["nodes"] <= 2 * mf.NODE_BUDGET_PER_NINE
    assert attempts[-1]["status"] == "succes"
    assert all(a["status"] != "succes" for a in attempts[:-1])


def test_explicit_failure_without_relaxing_rules(monkeypatch):
    monkeypatch.setattr(mf, "NODE_BUDGET_PER_NINE", 3)
    with pytest.raises(mf.MuirfieldRoutingError) as info:
        mf.build_muirfield(2, width=350, height=400)
    assert len(info.value.attempts) == (mf.CLUBHOUSE_POSITIONS * mf.PAR_PERMUTATIONS
                                        * len(mf.START_ANGLES))


@pytest.mark.parametrize("case", CASES, ids=lambda c: f"{c[0]}x{c[1]}-s{c[2]}")
def test_eighteen_holes_and_par_quotas(results, case):
    layout = results[case].layout
    assert [hole.order for hole in layout.holes] == list(range(1, 19))
    assert Counter(hole.par for hole in layout.holes) == Counter(GLOBAL_PAR_QUOTA)
    for nine in (layout.front, layout.back):
        pars = tuple(hole.par for hole in nine.holes)
        assert 1 <= pars.count(3) <= 3
        assert 1 <= pars.count(5) <= 3
        assert mf.par_sequence_ok(pars)
        assert mf.nine_par_ok(pars)


def test_par_sequence_rules():
    assert not mf.par_sequence_ok((4, 5, 5, 5, 4, 3, 4, 4, 3))
    assert not mf.par_sequence_ok((4, 3, 3, 3, 4, 5, 4, 4, 5))
    assert mf.par_sequence_ok((4, 5, 5, 4, 3, 3, 4, 5, 4))
    assert mf.par_sequence_penalty((3, 4, 5, 5, 4, 4, 4, 3, 4)) == 2
    for seed in range(1, 201):
        front, back = mf.draw_pars(np.random.default_rng([seed, 7]))
        for pars in (front, back):
            assert mf.par_sequence_ok(pars)            # dure
            assert mf.par_sequence_penalty(pars) == 0  # souple, toujours satisfaisable ici
        assert Counter(front + back) == Counter(GLOBAL_PAR_QUOTA)


def test_par_split_between_nines_is_not_fixed():
    """La répartition des pars entre nines est tirée par la seed : aucun nine
    n'est systématiquement le plus court."""
    shorter = set()
    for seed in range(1, 40):
        front, back = mf.draw_pars(np.random.default_rng([seed, 7]))
        if sum(front) != sum(back):
            shorter.add("front" if sum(front) < sum(back) else "back")
    assert shorter == {"front", "back"}


@pytest.mark.parametrize("case", CASES, ids=lambda c: f"{c[0]}x{c[1]}-s{c[2]}")
def test_clubhouse_on_a_map_edge(results, case):
    layout = results[case].layout
    ch = layout.clubhouse
    assert (layout.width, layout.height) == case[:2]
    edge_distance = min(ch.x, ch.y, layout.width - ch.x, layout.height - ch.y)
    assert edge_distance <= mf.CLUBHOUSE_EDGE_INSET + 1e-9


@pytest.mark.parametrize("case", CASES, ids=lambda c: f"{c[0]}x{c[1]}-s{c[2]}")
def test_rings_follow_the_rectangular_map(results, case):
    result = results[case]
    w, h, _ = case
    outer = np.asarray(result.outer_ring)
    inner = np.asarray(result.inner_ring)
    assert np.ptp(outer[:, 0]) == pytest.approx(w - 2 * mf.OUTER_INSET, abs=0.5)
    assert np.ptp(outer[:, 1]) == pytest.approx(h - 2 * mf.OUTER_INSET, abs=0.5)
    assert np.ptp(inner[:, 0]) < np.ptp(outer[:, 0]) and np.ptp(inner[:, 1]) < np.ptp(outer[:, 1])

    def signed_area(path):
        pts = np.asarray(path)
        return 0.5 * float(np.sum(pts[:-1, 0] * pts[1:, 1] - pts[1:, 0] * pts[:-1, 1]))

    assert signed_area(result.front_path) * signed_area(result.back_path) < 0.0


@pytest.mark.parametrize("case", CASES, ids=lambda c: f"{c[0]}x{c[1]}-s{c[2]}")
def test_anchor_holes_leave_and_return_near_the_clubhouse(results, case):
    result = results[case]
    layout = result.layout
    ch = (layout.clubhouse.x, layout.clubhouse.y)
    bounds = mf.link_bounds(ValidationRules(width=layout.width, height=layout.height))
    for nine in (layout.front, layout.back):
        tee, green = nine.holes[0].tee, nine.holes[-1].green
        assert bounds.clubhouse_min <= math.dist(ch, (tee.x, tee.y)) <= bounds.maximum
        assert bounds.clubhouse_min <= math.dist(ch, (green.x, green.y)) <= bounds.maximum


@pytest.mark.parametrize("case", CASES, ids=lambda c: f"{c[0]}x{c[1]}-s{c[2]}")
def test_anchor_holes_sit_in_disjoint_clubhouse_cones(results, case):
    """1 et 9 de part et d'autre le long du bord, 10 et 18 entre eux : cônes
    convexes disjoints issus du clubhouse, donc aucun croisement possible."""
    result = results[case]
    w, h, _ = case
    plan = result.plan
    frame = mf.clubhouse_frame(plan.edge, plan.clubhouse, list(result.front_path), w, h)
    holes = {hole.order: hole for hole in result.layout.holes}
    for order in (1, 9, 10, 18):
        low, high = mf.anchor_bounds(order)
        phi = frame.phi_deg(np.array([(p.x, p.y) for p in holes[order].axis]))
        assert ((phi >= low) & (phi <= high)).all(), (order, phi)
    assert mf.anchor_bounds(10)[1] < 0 < mf.anchor_bounds(18)[0]
    assert mf.anchor_bounds(9)[1] < mf.anchor_bounds(10)[0]
    assert mf.anchor_bounds(18)[1] < mf.anchor_bounds(1)[0]


@pytest.mark.parametrize("case", CASES, ids=lambda c: f"{c[0]}x{c[1]}-s{c[2]}")
def test_hole_lengths_within_realistic_par_specs(results, case):
    for hole in results[case].layout.holes:
        assert PAR_SPECS[hole.par].accepts_length(hole.length), (hole.order, hole.length)
        assert len(hole.doglegs) <= 1


def test_prefilters_only_reject_what_the_checks_reject(results):
    """Les pré-filtres vectorisés sont des conditions nécessaires : tout
    candidat qu'ils écartent est aussi rejeté par ``PartialLayout.check``."""
    layout = results[(350, 400, 3)].layout
    partial = PartialLayout(ValidationRules(width=350, height=400),
                            (layout.clubhouse.x, layout.clubhouse.y))
    for hole in layout.front.holes:
        partial.push(hole, ())
    for link in layout.front.links:
        owners = tuple(o for o in (link.from_hole_order, link.to_hole_order) if o is not None)
        partial.links.append((PlannedLink((link.start.x, link.start.y), (link.end.x, link.end.y),
                                          owners), (min(link.start.x, link.end.x),
                                                    min(link.start.y, link.end.y),
                                                    max(link.start.x, link.end.x),
                                                    max(link.start.y, link.end.y))))
    obstacles = Obstacles.from_partial(partial)
    rng = np.random.default_rng(0)
    rejected = 0
    for _ in range(400):
        tee = rng.uniform(20, 330, size=2)
        angle = rng.uniform(0, 2 * math.pi)
        green = tee + 120.0 * np.array([math.cos(angle), math.sin(angle)])
        if not (5 < green[0] < 345 and 5 < green[1] < 395):
            continue
        hole = ElasticHole(order=12, par=4, tee=ControlPoint(*map(float, tee)),
                           green=ControlPoint(*map(float, green)), width=11.0)
        clear = (obstacles.points_clear(np.array([tee, green]), 5.5, 5.0).all()
                 and obstacles.chords_clear(tee[None], green[None], 5.5, 5.0)[0])
        if not clear:
            rejected += 1
            assert partial.check(hole, ()) is not None
    assert rejected > 50


@pytest.mark.parametrize("seed", (1, 4))
def test_sites_are_spaced_dry_and_deterministic(seed):
    heightmap = load_terrain(seed, 350, 400)
    assert heightmap.shape == (400, 350)
    for kind, spacing in (("green", GREEN_SPACING), ("tee", TEE_SPACING)):
        sites = build_sites(heightmap, seed, kind)
        assert len(sites) > 100
        assert min_pairwise_distance(sites.points) >= spacing - 1e-9
        ix, iy = sites.points[:, 0].astype(int), sites.points[:, 1].astype(int)
        assert (heightmap[iy, ix] >= WATER_LEVEL).all()
        assert ((sites.scores >= 0.0) & (sites.scores <= 1.0)).all()
        assert (sites.points[:, 0] <= 350).all()
        again = build_sites(heightmap, seed, kind)
        assert np.array_equal(again.points, sites.points)


def test_flat_relief_falls_back_to_seeded_random_scores():
    flat = np.full((400, 400), 70.0, dtype=np.float32)
    first = build_sites(flat, 5, "green")
    assert first.random_scores
    assert np.array_equal(first.points, build_sites(flat, 5, "green").points)
    assert not np.array_equal(first.points, build_sites(flat, 6, "green").points)


def test_readable_render_numbers_every_hole(results):
    result = results[(300, 400, 1)]
    svg = render_readable_svg(result.layout, result.violations,
                              rings=(result.outer_ring, result.inner_ring), title="t")
    assert svg.startswith("<svg") and svg.rstrip().endswith("</svg>")
    for order in range(1, 19):
        assert f'text-anchor="middle">{order}</text>' in svg


# ----------------------------------------------------------------------
# Revue R1+R2
# ----------------------------------------------------------------------

def test_default_square_map_is_valid():
    result = mf.build_muirfield(1)
    assert (result.width, result.height) == (400.0, 400.0)
    assert result.violations == ()
    assert validate(result.layout) == []


def test_layout_rejected_by_the_oracle_is_never_returned(monkeypatch):
    real = mf.validate
    calls = []

    def first_call_fails(layout, rules):
        calls.append(1)
        if len(calls) == 1:
            return [Violation("fairway_gap", (1, 2), "injectée")]
        return real(layout, rules)

    monkeypatch.setattr(mf, "validate", first_call_fails)
    result = mf.build_muirfield(3, width=350, height=400)
    assert result.attempts[0]["status"] == "echec_validate"
    assert result.attempts[-1]["status"] == "succes"
    assert result.violations == ()

    monkeypatch.setattr(mf, "validate",
                        lambda layout, rules: [Violation("length", (1,), "injectée")])
    monkeypatch.setattr(mf, "CLUBHOUSE_POSITIONS", 1)
    monkeypatch.setattr(mf, "PAR_PERMUTATIONS", 1)
    with pytest.raises(mf.MuirfieldRoutingError) as info:
        mf.build_muirfield(3, width=350, height=400)
    assert {a["status"] for a in info.value.attempts} == {"echec_validate"}


def test_link_bounds_are_derived_from_rules():
    default = mf.link_bounds(ValidationRules())
    assert (default.minimum, default.maximum, default.clubhouse_min) == (12.0, 45.0, 18.0)
    custom = mf.link_bounds(ValidationRules(link_min=15.0, link_max=40.0, clubhouse_clear_radius=25.0))
    assert (custom.minimum, custom.maximum, custom.clubhouse_min) == (15.0, 40.0, 33.0)
    with pytest.raises(ValueError):
        mf.link_bounds(ValidationRules(link_max=30.0, clubhouse_clear_radius=25.0))


def test_custom_link_rules_are_honoured():
    rules = ValidationRules(width=350, height=400, link_min=14.0, link_max=40.0)
    result = mf.build_muirfield(3, width=350, height=400, rules=rules)
    assert validate(result.layout, rules) == []
    assert all(14.0 - 1e-9 <= link.length <= 40.0 + 1e-9 for link in result.layout.links)


def test_terrain_cache_key_tracks_terrain_config(tmp_path):
    from golfgen.config import TerrainConfig
    assert sites_module.terrain_cache_tag() == sites_module.terrain_cache_tag(TerrainConfig())
    assert sites_module.terrain_cache_tag() != sites_module.terrain_cache_tag(TerrainConfig(octaves=5))
    small = sites_module.load_terrain(9, 40, 30, cache_dir=tmp_path)
    files = list(tmp_path.iterdir())
    assert len(files) == 1 and sites_module.terrain_cache_tag() in files[0].name
    assert np.array_equal(sites_module.load_terrain(9, 40, 30, cache_dir=tmp_path), small)


# -- PartialLayout.check : un cas minimal rejeté par famille ---------------

RULES = ValidationRules(width=400.0, height=400.0)
CLUBHOUSE = (200.0, 395.0)


def _hole(order, tee, green, par=4, width=11.0):
    return ElasticHole(order=order, par=par, tee=ControlPoint(*tee), green=ControlPoint(*green),
                       width=width)


def _partial(*holes, links=()):
    partial = PartialLayout(RULES, CLUBHOUSE)
    for hole in holes:
        partial.push(hole, ())
    for link in links:
        partial.push(_hole(17, (380.0, 20.0), (380.0, 120.0)), (link,))
    return partial


H1 = _hole(1, (100.0, 200.0), (200.0, 200.0))


def test_check_accepts_a_clean_candidate():
    assert _partial(H1).check(_hole(12, (100.0, 300.0), (200.0, 300.0)), ()) is None


def test_check_rejects_length():
    assert _partial().check(_hole(12, (100.0, 300.0), (200.0, 300.0), par=3), ()) == "length"


def test_check_rejects_bounds():
    assert _partial().check(_hole(12, (0.5, 100.0), (0.5, 200.0)), ()) == "bounds"


def test_check_rejects_clubhouse_clear():
    assert _partial().check(_hole(12, (150.0, 388.0), (250.0, 388.0)), ()) == "clubhouse_clear"


def test_check_rejects_axis_crossing():
    assert _partial(H1).check(_hole(12, (150.0, 150.0), (150.0, 250.0)), ()) == "axis_crossing"


def test_check_rejects_fairway_gap():
    assert _partial(H1).check(_hole(12, (100.0, 214.0), (200.0, 214.0)), ()) == "fairway_gap"


def test_check_rejects_new_link_crossing_a_placed_fairway():
    candidate = _hole(12, (140.0, 222.0), (140.0, 322.0))
    link = PlannedLink((140.0, 178.0), (140.0, 222.0), (11, 12))
    assert _partial(H1).check(candidate, ()) is None
    assert _partial(H1).check(candidate, (link,)) == "link_blocked"


def test_check_rejects_placed_link_crossing_the_new_fairway():
    placed_link = PlannedLink((150.0, 280.0), (150.0, 320.0), (16, 17))
    candidate = _hole(12, (100.0, 300.0), (200.0, 300.0))
    assert _partial().check(candidate, ()) is None
    assert _partial(links=(placed_link,)).check(candidate, ()) == "link_blocked"


def test_check_rejects_parallel_stack():
    stack = [_hole(order, (100.0, y), (200.0, y)) for order, y in ((1, 100.0), (2, 116.0), (3, 132.0))]
    fourth = _hole(4, (100.0, 148.0), (200.0, 148.0))
    assert _partial(*stack[:2]).check(stack[2], ()) is None
    assert _partial(*stack).check(fourth, ()) == "parallel_stack"
    # même pile, mais le trou 4 est déjà posé (ancrage) et le 3 arrive en dernier
    assert _partial(stack[0], stack[1], fourth).check(stack[2], ()) == "parallel_stack"


# -- round A ---------------------------------------------------------------

def test_nine_par_stays_within_34_38():
    assert mf.NINE_PAR_RANGE == (34, 38)
    assert not mf.nine_par_ok((3, 3, 3, 3, 4, 4, 4, 4, 4))     # 32
    assert not mf.nine_par_ok((5, 5, 5, 5, 4, 4, 4, 4, 3))     # 39
    assert mf.nine_par_ok((3, 3, 4, 4, 4, 4, 4, 4, 4))         # 34
    assert mf.nine_par_ok((5, 5, 4, 4, 4, 4, 4, 4, 4))         # 38
    seen = set()
    for seed in range(1, 301):
        front, back = mf.draw_pars(np.random.default_rng([seed, 7]))
        assert mf.nine_par_ok(front) and mf.nine_par_ok(back)
        assert sum(front) + sum(back) == 72
        seen.add(sum(front))
    assert seen == {34, 35, 36, 37, 38}   # pas forcé à 36/36


def test_check_rejects_width():
    assert _partial().check(_hole(12, (100.0, 300.0), (200.0, 300.0), width=9.0), ()) == "width"


def test_check_rejects_link_distance():
    candidate = _hole(12, (100.0, 300.0), (200.0, 300.0))
    too_long = PlannedLink((100.0, 250.0), (100.0, 300.0), (11, 12))     # 50 > 45
    too_short = PlannedLink((100.0, 290.0), (100.0, 300.0), (11, 12))    # 10 < 12
    ok = PlannedLink((100.0, 270.0), (100.0, 300.0), (11, 12))           # 30
    assert _partial().check(candidate, (ok,)) is None
    assert _partial().check(candidate, (too_long,)) == "link_distance"
    assert _partial().check(candidate, (too_short,)) == "link_distance"
    # minimum plus strict exigé pour une liaison du clubhouse
    assert _partial().check(candidate, (ok,), (35.0,)) == "link_distance"


# -- round A2 : robustesse 300×400 -------------------------------------------

def test_check_rejects_width_above_max_and_accepts_valid_width():
    assert _partial().check(_hole(12, (100.0, 300.0), (200.0, 300.0), width=18.0), ()) == "width"
    assert _partial().check(_hole(12, (100.0, 300.0), (200.0, 300.0), width=14.0), ()) is None


def test_order_nine_respects_anchor_capacity():
    rng = np.random.default_rng(3)
    free = mf.order_nine(2, 3, np.random.default_rng(3))
    assert mf.order_nine(2, 3, rng, first=frozenset((3, 4, 5)), last=frozenset((3, 4, 5))) == free
    constrained = mf.order_nine(2, 3, np.random.default_rng(3), first=frozenset((4,)),
                                last=frozenset((3, 4)))
    assert constrained[0] == 4 and constrained[-1] in (3, 4)
    assert mf.par_sequence_ok(constrained)
    assert mf.order_nine(2, 3, np.random.default_rng(3), first=frozenset(),
                         last=frozenset((4,))) is None


def test_plan_not_tried_when_no_permutation_fits_the_cones():
    nothing = {order: frozenset() for order in (1, 9, 10, 18)}
    plans = list(mf.iter_plans(5, 300, 400, capacity=lambda edge, ch, direction: nothing))
    assert len(plans) == mf.CLUBHOUSE_POSITIONS * mf.PAR_PERMUTATIONS * len(mf.START_ANGLES)
    assert all(plan is None for _, plan in plans)
    only_fours = {order: frozenset((4,)) for order in (1, 9, 10, 18)}
    for _, plan in mf.iter_plans(5, 300, 400, capacity=lambda edge, ch, direction: only_fours):
        assert plan is not None
        assert (plan.front_pars[0], plan.front_pars[-1], plan.back_pars[0], plan.back_pars[-1]) == (4, 4, 4, 4)


@pytest.mark.parametrize("seed", (8, 19, 25, 27, 28))
def test_round_a_failures_now_route_cleanly(seed):
    """Échecs du round A (300×400) : clubhouse sur bord court + par 5 au
    trou 1 (19, 28), back bloqué vers 17/18 (8, 25, 27)."""
    result = mf.build_muirfield(seed, width=300, height=400)
    assert result.violations == ()
    assert validate(result.layout, ValidationRules(width=300, height=400)) == []
