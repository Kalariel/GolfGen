"""Étape M : routage Muirfield (``muirfield.py``, ``partial_checks.py``, ``sites.py``).

R2 est une porte de validité : zéro violation de l'oracle final sur les
seeds 1–6 pour les deux formats de carte rectangulaires (300×400 et
350×400), par construction (contrôles en ligne, ancrages 1/9/10/18, retour
arrière borné, relances). Le relief est mis en cache sur disque
(``output/.cache``) : premier passage ~5 s par seed et par format.
"""

from __future__ import annotations

from collections import Counter
import dataclasses
import math
import re

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
    assert 1 <= len(attempts) <= mf.MAX_ATTEMPTS
    for attempt in attempts:
        assert attempt["checks"] <= 2 * mf.CHECK_BUDGET_PER_NINE
        assert attempt["nodes"] <= 2 * mf.NODE_BUDGET_PER_NINE
    assert attempts[-1]["status"] == "succes"
    assert all(a["status"] != "succes" for a in attempts[:-1])


def test_explicit_failure_without_relaxing_rules(monkeypatch):
    monkeypatch.setattr(mf, "NODE_BUDGET_PER_NINE", 3)
    with pytest.raises(mf.MuirfieldRoutingError) as info:
        mf.build_muirfield(2, width=350, height=400)
    # budget minuscule : chaque échec d'ancrage est coupé, donc rien n'est
    # sauté pour échec prouvé et le plafond de tentatives réelles est atteint
    assert len(info.value.attempts) == mf.MAX_ATTEMPTS == 27


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
    assert "#ffa657" not in svg
    lobed = mf.lobed_inner_path(result.plan.clubhouse, result.plan.direction, 300, 400,
                                result.plan.inner_delta_deg, mf.lobe_parameters(1))
    with_path = render_readable_svg(result.layout, result.violations,
                                    rings=(result.outer_ring, result.inner_ring),
                                    paths=(lobed,), title="t")
    assert with_path.count('stroke="#ffa657"') == 1


def test_readable_render_crops_the_canvas_to_a_landscape_map(results):
    """Portrait : canevas 800×(800 + pied), inchangé ; paysage : hauteur
    rognée à la carte, pas de bande vide sous la carte."""
    result = results[(300, 400, 1)]
    portrait = render_readable_svg(result.layout, result.violations, title="t")
    assert 'width="800" height="888"' in portrait.splitlines()[0]
    landscape = dataclasses.replace(result.layout, width=400.0, height=300.0)
    svg = render_readable_svg(landscape, (), title="t")
    assert 'width="800" height="700"' in svg.splitlines()[0]
    labels = [float(y) for y in re.findall(r'<circle cx="[\d.]+" cy="([\d.]+)" r="10"', svg)]
    assert len(labels) == 18 and max(labels) <= 612 - 24 - 10


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
    monkeypatch.setattr(mf, "MAX_ATTEMPTS", 3)
    with pytest.raises(mf.MuirfieldRoutingError) as info:
        mf.build_muirfield(3, width=350, height=400)
    assert len(info.value.attempts) == 3
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
    # une seule entrée par clubhouse infaisable, puis clubhouse suivant
    assert [indices for indices, _ in plans] == [(ch, 0, 0)
                                                 for ch in range(mf.MAX_CLUBHOUSE_POSITIONS)]
    assert all(plan is None for _, plan in plans)
    only_fours = {order: frozenset((4,)) for order in (1, 9, 10, 18)}
    plans = list(mf.iter_plans(5, 300, 400, capacity=lambda edge, ch, direction: only_fours,
                               clubhouses=3))
    assert len(plans) == 3 * mf.PAR_PERMUTATIONS * len(mf.START_ANGLES)
    for _, plan in plans:
        assert plan is not None
        assert (plan.front_pars[0], plan.front_pars[-1], plan.back_pars[0], plan.back_pars[-1]) == (4, 4, 4, 4)


@pytest.mark.parametrize("seed", (8, 19, 25, 27, 28))
def test_round_a_failures_now_route_cleanly(seed):
    """Échecs du round A (300×400) : clubhouse sur bord court + par 5 au
    trou 1 (19, 28), back bloqué vers 17/18 (8, 25, 27)."""
    result = mf.build_muirfield(seed, width=300, height=400)
    assert result.violations == ()
    assert validate(result.layout, ValidationRules(width=300, height=400)) == []


# -- round B : patron explicite, Muirfield inversé ---------------------------

from experiments.elastic_routing.sites import Sites


@pytest.fixture(scope="module")
def inverse_results():
    return {seed: mf.build_course(seed, "muirfield_inverse", width=300, height=400)
            for seed in SEEDS}


def test_pattern_is_an_explicit_parameter():
    assert mf.PATTERN_CHOICES == ("muirfield", "muirfield_inverse", "random")
    assert mf.resolve_pattern(4, "muirfield") == "muirfield"
    assert mf.resolve_pattern(4, "muirfield_inverse") == "muirfield_inverse"
    with pytest.raises(ValueError):
        mf.resolve_pattern(4, "spirale")
    drawn = [mf.resolve_pattern(seed, "random") for seed in range(1, 41)]
    assert drawn == [mf.resolve_pattern(seed, "random") for seed in range(1, 41)]
    assert set(drawn) == set(mf.PATTERNS)


def test_random_pattern_matches_the_explicit_one():
    seed = 3
    resolved = mf.resolve_pattern(seed, "random")
    by_random = mf.build_course(seed, "random", width=350, height=400)
    explicit = mf.build_course(seed, resolved, width=350, height=400)
    assert by_random.pattern == resolved and by_random.requested_pattern == "random"
    assert by_random.layout.to_json() == explicit.layout.to_json()


@pytest.mark.parametrize("seed", SEEDS)
def test_inverse_pattern_is_valid(inverse_results, seed):
    result = inverse_results[seed]
    assert result.pattern == "muirfield_inverse"
    assert result.violations == ()
    assert validate(result.layout, ValidationRules(width=300, height=400)) == []
    pars = [tuple(h.par for h in nine.holes) for nine in (result.layout.front, result.layout.back)]
    assert all(mf.par_sequence_ok(p) and mf.nine_par_ok(p) for p in pars)


@pytest.mark.parametrize("seed", SEEDS)
def test_inverse_roles_front_inside_back_outside(inverse_results, seed):
    """Front = boucle intérieure, back = grand tour extérieur, sens opposés ;
    10 et 18 longent le bord, 1 et 9 plongent entre eux."""
    result = inverse_results[seed]
    center = np.array([150.0, 200.0])
    front_r = np.hypot(*(np.asarray(result.front_path[1:-1]) - center).T)
    back_r = np.hypot(*(np.asarray(result.back_path[1:-1]) - center).T)
    assert front_r.max() < back_r.min()

    def signed_area(path):
        pts = np.asarray(path)
        return float(np.sum(pts[:-1, 0] * pts[1:, 1] - pts[1:, 0] * pts[:-1, 1]))

    assert signed_area(result.front_path) * signed_area(result.back_path) < 0.0
    plan = result.plan
    frame = mf.clubhouse_frame(plan.edge, plan.clubhouse, list(result.back_path), 300, 400)
    holes = {hole.order: hole for hole in result.layout.holes}
    for order in (1, 9, 10, 18):
        low, high = mf.anchor_bounds(order, "muirfield_inverse")
        phi = frame.phi_deg(np.array([(p.x, p.y) for p in holes[order].axis]))
        assert ((phi >= low) & (phi <= high)).all(), (order, phi)
    assert mf.anchor_bounds(10, "muirfield_inverse") == mf.anchor_bounds(1, "muirfield")
    assert mf.anchor_bounds(1, "muirfield_inverse") == mf.anchor_bounds(10, "muirfield")


def test_frame_side_is_the_same_for_every_start_angle():
    for edge, ch in (("S", (120.0, 394.0)), ("W", (6.0, 230.0)), ("N", (200.0, 6.0))):
        for direction in (1, -1):
            sides = set()
            for outer_delta, inner_delta in mf.START_ANGLES:
                _, _, front, _ = mf.nine_paths(ch, direction, 300, 400, outer_delta, inner_delta)
                sides.add(mf.clubhouse_frame(edge, ch, front, 300, 400).side)
            assert len(sides) == 1


def test_order_nine_exhaustive_fallback():
    exhaustive = mf.order_nine(3, 3, np.random.default_rng(1), tries=0,
                               first=frozenset((5,)), last=frozenset((3,)))
    assert exhaustive is not None and exhaustive[0] == 5 and exhaustive[-1] == 3
    assert mf.par_sequence_ok(exhaustive)
    assert exhaustive == mf.order_nine(3, 3, np.random.default_rng(1), tries=0,
                                       first=frozenset((5,)), last=frozenset((3,)))
    # un seul par 5 ne peut pas ouvrir ET fermer le nine : impossible, donc None
    assert mf.order_nine(2, 1, np.random.default_rng(1), first=frozenset((5,)),
                         last=frozenset((5,))) is None


@pytest.mark.parametrize("seed", SEEDS)
def test_attempt_statuses_are_classified(inverse_results, seed):
    known = {"succes", "echec_ancrages", "echec_front", "echec_back", "echec_validate",
             "infaisable_ancrage"}
    assert {a["status"] for a in inverse_results[seed].attempts} <= known


def _toy_search(tees, greens, holes=()):
    rules = ValidationRules(width=400, height=400)
    partial = PartialLayout(rules, (200.0, 394.0))
    for hole in holes:
        partial.push(hole, ())
    tees, greens = np.asarray(tees, float), np.asarray(greens, float)
    frame = mf.ClubhouseFrame((200.0, 394.0), (0.0, -1.0), (1.0, 0.0), 0.0)
    return mf._Search(
        width=400.0, height=400.0,
        tees=Sites("tee", tees, np.ones(len(tees)), False),
        greens=Sites("green", greens, np.ones(len(greens)), False),
        frame=frame, partial=partial,
        outer_tee_ok=np.ones(len(tees), dtype=bool), outer_green_ok=np.ones(len(greens), dtype=bool),
        links=mf.link_bounds(rules),
    )


def _bridge_level(end):
    return mf._Level(order=16, index=6, start=None, start_min=12.0, start_owner=None,
                     end=None, end_min=12.0, end_owner=None, reach_point=None, reach=math.inf,
                     heading=None, target_green=None, target_tee=None,
                     bridge_end=np.asarray(end, float), bridge_par=4, bridge_owner=18)


def test_bridge_reachable_keeps_a_green_that_can_still_reach_the_anchor():
    tee18 = (300.0, 300.0)
    tees = [(300.0, 150.0)]                                     # tee du trou-pont
    greens = [(300.0, 270.0), (300.0, 120.0), (100.0, 100.0)]   # green pont, candidats
    search = _toy_search(tees, greens)
    level = _bridge_level(tee18)
    candidates = np.asarray(greens[1:])
    obstacles = Obstacles.from_partial(search.partial)
    assert search._bridge_reachable(candidates, level, [], obstacles).tolist() == [True, False]
    # un trou posé en travers du trou-pont : plus de pont possible
    blocker = _hole(5, (250.0, 210.0), (350.0, 210.0))
    blocked = _toy_search(tees, greens, holes=(blocker,))
    assert blocked._bridge_reachable(candidates, level, [], Obstacles.from_partial(
        blocked.partial)).tolist() == [False, False]


def test_dogleg_prefilter_keeps_the_free_corner_only():
    level = mf._Level(order=12, index=3, start=None, start_min=12.0, start_owner=None,
                      end=None, end_min=12.0, end_owner=None, reach_point=None, reach=math.inf,
                      heading=None, target_green=None, target_tee=None)
    tee, green = (100.0, 200.0), (195.0, 200.0)                 # corde 95 < 100 : dogleg seul
    free = list(_toy_search([tee], [green]).candidates(level, 4, [], np.zeros((1, 2))))
    assert {hole.doglegs[0].y > 200.0 for hole in free} == {True, False}
    blocker = _hole(5, (120.0, 230.0), (220.0, 230.0))          # du côté y > 200 de la corde
    search = _toy_search([tee], [green], holes=(blocker,))
    kept = list(search.candidates(level, 4, [], np.zeros((1, 2))))
    assert len(kept) == 1 and kept[0].doglegs[0].y < 200.0
    assert search.partial.check(kept[0], ()) is None             # le coude gardé est valide


# -- round C : nits B et largeurs variables (C1) -------------------------------

# Empreinte (largeur minimale, 300×400) : patron muirfield au round B, plus
# muirfield_inverse seed 1 et le nombre de coudes par trou (R2b round 0).
# Revérifiée après le saut des échecs prouvés : aucune entrée modifiée (ni
# plan, ni pars, ni longueurs, ni nombre de tentatives).
MUIRFIELD_FINGERPRINT = {
    ("muirfield", 1): (
        ("N", 1, 2, 2), (3, 5, 4, 5, 4, 4, 4, 3, 5), (5, 3, 4, 4, 4, 4, 3, 4, 4),
        (49.18, 147.0, 102.86, 147.0, 103.2, 141.97, 133.2, 47.0, 147.0,
         147.0, 62.9, 102.0, 103.87, 102.45, 106.26, 45.63, 102.0, 100.62), 18,
        (0, 1, 0, 1, 0, 0, 0, 1, 1, 1, 0, 1, 0, 0, 0, 0, 1, 0)),
    ("muirfield", 2): (
        ("S", 0, 0, 0), (4, 4, 5, 3, 5, 4, 4, 4, 5), (4, 3, 4, 3, 3, 4, 4, 5, 4),
        (101.62, 104.71, 147.0, 57.94, 152.63, 114.92, 101.02, 102.0, 147.0,
         102.0, 47.0, 102.0, 66.22, 69.43, 102.0, 102.0, 145.1, 102.0), 1,
        (0, 0, 1, 0, 0, 0, 0, 1, 1, 1, 1, 1, 0, 0, 1, 1, 0, 1)),
    ("muirfield", 3): (
        ("S", 0, 0, 0), (4, 3, 5, 3, 5, 3, 5, 4, 4), (4, 4, 4, 3, 5, 4, 4, 4, 4),
        (102.0, 50.49, 147.0, 47.0, 147.0, 56.63, 173.76, 104.58, 102.0,
         102.0, 102.0, 102.0, 45.98, 147.0, 102.0, 102.0, 110.39, 102.0), 1,
        (1, 0, 1, 1, 1, 0, 0, 0, 1, 1, 1, 1, 0, 1, 1, 1, 0, 1)),
    ("muirfield_inverse", 1): (
        ("W", 0, 1, 0), (4, 5, 4, 4, 5, 4, 3, 5, 3), (4, 4, 3, 3, 4, 4, 5, 4, 4),
        (102.0, 147.0, 102.0, 104.31, 147.0, 102.0, 47.0, 147.0, 57.82,
         100.73, 102.0, 55.77, 54.38, 100.06, 102.0, 147.0, 109.83, 110.67), 4,
        (1, 1, 1, 0, 1, 1, 1, 1, 0, 0, 1, 0, 0, 0, 1, 1, 0, 0)),
}


@pytest.mark.parametrize("pattern,seed", sorted(MUIRFIELD_FINGERPRINT))
def test_muirfield_fingerprint_is_stable_in_min_width_mode(pattern, seed):
    result = mf.build_course(seed, pattern, width=300, height=400, width_mode="min")
    plan = result.plan
    got = ((plan.edge, plan.clubhouse_index, plan.permutation_index, plan.angle_index),
           plan.front_pars, plan.back_pars,
           tuple(round(h.length, 2) for h in result.layout.holes), len(result.attempts),
           tuple(len(h.doglegs) for h in result.layout.holes))
    assert got == MUIRFIELD_FINGERPRINT[(pattern, seed)]


def test_unresolved_or_unknown_pattern_raises():
    for bad in ("random", "spirale"):
        with pytest.raises(ValueError):
            mf.outer_start(bad)
        with pytest.raises(ValueError):
            mf.anchor_bounds(1, bad)
    with pytest.raises(ValueError):
        mf.build_course(1, "spirale", width=300, height=400)
    with pytest.raises(ValueError):
        mf.build_course(1, "muirfield", width=300, height=400, width_mode="large")


def test_distinct_orders_is_cached():
    first = mf._distinct_orders(3, 3)
    assert mf._distinct_orders(3, 3) is first
    assert len(first) == 1680 and len(set(first)) == 1680


def _mean_center_distance(nine, center):
    points = np.array([(p.x, p.y) for hole in nine.holes for p in hole.axis])
    return float(np.hypot(*(points - center).T).mean())


@pytest.mark.parametrize("seed", SEEDS)
def test_roles_on_actual_holes(results, inverse_results, seed):
    """Les trous eux-mêmes (pas seulement les chemins cibles) : le nine
    extérieur est en moyenne plus loin du centre de la carte que l'autre."""
    center = np.array([150.0, 200.0])
    normal = results[(300, 400, seed)].layout
    inverse = inverse_results[seed].layout
    assert _mean_center_distance(normal.front, center) > _mean_center_distance(normal.back, center)
    assert _mean_center_distance(inverse.back, center) > _mean_center_distance(inverse.front, center)


def test_hole_widths_are_seeded_within_par_range():
    fractions = mf.hole_width_fractions(7)
    assert fractions == mf.hole_width_fractions(7) != mf.hole_width_fractions(8)
    for par, spec in PAR_SPECS.items():
        assert mf.hole_width(par, None) == spec.width_min
        assert mf.hole_width(par, 0.0) == spec.width_min
        assert mf.hole_width(par, 1.0) == spec.width_max
        for fraction in fractions.values():
            width = mf.hole_width(par, fraction)
            assert spec.width_min <= width <= spec.width_max and (width * 2).is_integer()


@pytest.mark.parametrize("seed", SEEDS)
def test_variable_widths_are_used_and_valid(results, seed):
    result = results[(300, 400, seed)]
    assert result.width_mode == "variable"
    fractions = mf.hole_width_fractions(seed)
    widths = [hole.width for hole in result.layout.holes]
    assert widths == [mf.hole_width(h.par, fractions[h.order]) for h in result.layout.holes]
    assert len(set(widths)) > 3
    assert result.violations == ()


# -- round R2b M1 : cibles irrégulières ------------------------------------------

M1_PARS = (4, 3, 5, 4, 4, 3, 4, 5, 4)
M1_PATH = [(0.0, 0.0), (400.0, 0.0), (400.0, 300.0), (0.0, 300.0)]   # 1 100 blocs


def _legacy_green_targets(path, pars):
    """Calcul d'avant M1 (pas réguliers), recopié tel quel."""
    cumulative = mf._polyline_cumulative(path)
    total = sum(mf.LINK_NOMINAL + mf._nominal_length(par) for par in pars) + mf.LINK_NOMINAL
    running, targets = 0.0, []
    for par in pars:
        running += mf.LINK_NOMINAL + mf._nominal_length(par)
        targets.append(mf.point_at(path, cumulative, running / total * cumulative[-1]))
    return targets


def _along(path, targets):
    """Abscisse curviligne de chaque cible (chemin en U sans retour)."""
    cumulative = mf._polyline_cumulative(path)
    out = []
    for x, y in targets:
        for i, (a, b) in enumerate(zip(path, path[1:])):
            if (min(a[0], b[0]) - 1e-9 <= x <= max(a[0], b[0]) + 1e-9
                    and min(a[1], b[1]) - 1e-9 <= y <= max(a[1], b[1]) + 1e-9):
                out.append(cumulative[i] + math.hypot(x - a[0], y - a[1]))
                break
    return out


def test_uniform_targets_match_the_legacy_computation():
    legacy = _legacy_green_targets(M1_PATH, M1_PARS)
    assert mf.green_targets(M1_PATH, M1_PARS) == legacy
    assert mf.green_targets(M1_PATH, M1_PARS, None) == legacy


def test_irregular_factors_are_seeded_within_jitter():
    a, b = mf.target_jitter_factors(5), mf.target_jitter_factors(6)
    assert set(a) == {1, 10} and all(len(v) == 9 for v in a.values())
    for start in (1, 10):
        assert np.array_equal(a[start], mf.target_jitter_factors(5)[start])
        assert not np.array_equal(a[start], b[start])
        assert np.all(a[start] >= 1.0 - mf.TARGET_JITTER)
        assert np.all(a[start] <= 1.0 + mf.TARGET_JITTER)
    assert not np.array_equal(a[1], a[10])


def test_irregular_targets_are_deterministic_and_seed_dependent():
    def targets(seed):
        return mf.green_targets(M1_PATH, M1_PARS, mf.target_jitter_factors(seed)[1])
    assert targets(3) == targets(3)
    assert targets(3) != targets(4)
    assert targets(3) != mf.green_targets(M1_PATH, M1_PARS)


@pytest.mark.parametrize("seed", range(1, 21))
def test_irregular_targets_are_strictly_increasing_and_keep_the_total(seed):
    uniform = mf.green_targets(M1_PATH, M1_PARS)
    nominal = np.array([mf.LINK_NOMINAL + mf._nominal_length(par) for par in M1_PARS])
    total = nominal.sum() + mf.LINK_NOMINAL
    to_path = mf._polyline_cumulative(M1_PATH)[-1] / total      # blocs nominaux → chemin
    for start in (1, 10):
        factors = mf.target_jitter_factors(seed)[start]
        irregular = mf.green_targets(M1_PATH, M1_PARS, factors)
        along = _along(M1_PATH, irregular)
        assert len(along) == 9 and all(b > a for a, b in zip(along, along[1:]))
        assert along[0] > 0.0
        assert irregular[-1] == uniform[-1]            # dernière cible et retour inchangés
        # chaque pas reste dans [1 - a, 1 + a] × nominal × renormalisation
        renorm = nominal.sum() / (nominal * factors).sum()
        steps = np.diff([0.0, *along])
        low = (1.0 - mf.TARGET_JITTER) * nominal * renorm * to_path
        high = (1.0 + mf.TARGET_JITTER) * nominal * renorm * to_path
        assert np.all(steps >= low - 1e-9) and np.all(steps <= high + 1e-9)


def test_green_targets_reject_a_factor_count_mismatch():
    with pytest.raises(ValueError, match="facteurs"):
        mf.green_targets(M1_PATH, M1_PARS, np.ones(len(M1_PARS) + 1))


@pytest.mark.parametrize("factor", (1.0 - mf.TARGET_JITTER, 1.0 + mf.TARGET_JITTER))
def test_constant_factors_give_the_uniform_targets(factor):
    irregular = mf.green_targets(M1_PATH, M1_PARS, np.full(9, factor))
    assert irregular == pytest.approx(mf.green_targets(M1_PATH, M1_PARS))


def test_unknown_target_mode_raises():
    with pytest.raises(ValueError, match="target_mode"):
        mf.build_course(1, "muirfield", width=300, height=400, target_mode="chaos")
    with pytest.raises(ValueError, match="target_mode"):
        mf.build_muirfield(1, width=300, height=400, target_mode="chaos")


def test_irregular_mode_is_valid_and_reported():
    result = mf.build_course(1, "muirfield", width=300, height=400, width_mode="min",
                             target_mode="irregular")
    assert result.target_mode == "irregular"
    assert result.violations == ()
    uniform = mf.build_course(1, "muirfield", width=300, height=400, width_mode="min")
    assert uniform.target_mode == "uniform"
    assert result.layout.to_json() != uniform.layout.to_json()


# -- round R2b M2 : chemin intérieur à lobes ---------------------------------------

def test_lobe_parameters_are_seeded_once_per_seed():
    draws = {seed: mf.lobe_parameters(seed) for seed in range(1, 41)}
    assert mf.lobe_parameters(5) == draws[5]
    assert {m for m, _ in draws.values()} == set(mf.LOBE_ORDERS)
    assert all(0.0 <= phase < 2 * math.pi for _, phase in draws.values())
    assert len({phase for _, phase in draws.values()}) == len(draws)


def test_lobe_envelope_is_quiet_near_the_clubhouse_and_full_beyond():
    theta_ch = 1.0
    degrees = np.array([0.0, 20.0, -40.0, 60.0, -80.0, 120.0, 180.0])
    g = mf.lobe_envelope(theta_ch + np.radians(degrees), theta_ch)
    assert g == pytest.approx([0.0, 0.0, 0.0, 0.5, 1.0, 1.0, 1.0])
    ramp = mf.lobe_envelope(theta_ch + np.radians(np.linspace(40.0, 80.0, 41)), theta_ch)
    assert np.all(np.diff(ramp) > 0.0)


def test_lobe_envelope_wraps_around_theta_ch_near_pi():
    """θ_ch ≈ ±π : l'écart angulaire est pris modulo 2π, pas en brut."""
    eps = 1e-3
    assert mf.lobe_envelope(-math.pi + eps, math.pi) == pytest.approx(0.0)
    assert mf.lobe_envelope(math.pi - eps, -math.pi) == pytest.approx(0.0)
    assert mf.lobe_envelope(-math.pi + eps + math.radians(90.0), math.pi) == pytest.approx(1.0)


def test_lobe_offsets_stay_within_the_declared_amplitudes():
    theta = np.linspace(-math.pi, math.pi, 2001)
    for order in mf.LOBE_ORDERS:
        off = mf.lobe_offsets(theta, math.pi, order, 0.7)
        assert off.max() <= mf.LOBE_OUT and off.min() >= -mf.LOBE_IN
        assert off.max() > 0.9 * mf.LOBE_OUT and off.min() < -0.9 * mf.LOBE_IN


@pytest.mark.parametrize("seed", range(1, 13))
def test_lobed_inner_path_follows_the_ring_radially(seed):
    """Même départ, mêmes angles que l'anneau intérieur ; écart radial =
    lobe_offsets ; nul près du clubhouse ; dans la carte."""
    width, height = 300.0, 400.0
    center = (width / 2, height / 2)
    edge, ch = mf.place_clubhouse(np.random.default_rng(seed), width, height)
    direction = 1 if seed % 2 else -1
    lobes = mf.lobe_parameters(seed)
    _, _, _, ring = mf.nine_paths(ch, direction, width, height, inner_delta_deg=18.0)
    lobed = mf.lobed_inner_path(ch, direction, width, height, 18.0, lobes)
    assert len(lobed) == len(ring) and lobed[0] == lobed[-1] == ch
    ring_arr, lobed_arr = np.asarray(ring[1:-1]), np.asarray(lobed[1:-1])
    theta = np.arctan2(*(ring_arr - center)[:, ::-1].T)
    assert np.allclose(np.arctan2(*(lobed_arr - center)[:, ::-1].T), theta)
    theta_ch = math.atan2(ch[1] - center[1], ch[0] - center[0])
    radial = np.hypot(*(lobed_arr - center).T) - np.hypot(*(ring_arr - center).T)
    assert np.allclose(radial, mf.lobe_offsets(theta, theta_ch, *lobes))
    assert np.allclose(lobed_arr[:3], ring_arr[:3]) and np.allclose(lobed_arr[-3:], ring_arr[-3:])
    assert np.abs(radial).max() > 10.0
    assert lobed_arr.min() >= 0.0 and lobed_arr[:, 0].max() <= width
    assert lobed_arr[:, 1].max() <= height


def test_lobed_path_without_amplitude_is_the_ring_path(monkeypatch):
    monkeypatch.setattr(mf, "LOBE_OUT", 0.0)
    monkeypatch.setattr(mf, "LOBE_IN", 0.0)
    ch = (90.0, 6.0)
    _, _, _, ring = mf.nine_paths(ch, 1, 300, 400, inner_delta_deg=26.0)
    lobed = mf.lobed_inner_path(ch, 1, 300, 400, 26.0, (3, 1.0))
    assert np.allclose(lobed, ring)


def test_lobed_path_refuses_to_leave_the_map_or_collapse(monkeypatch):
    ch = (90.0, 6.0)
    monkeypatch.setattr(mf, "LOBE_OUT", 200.0)
    with pytest.raises(ValueError, match="hors de la carte"):
        mf.lobed_inner_path(ch, 1, 300, 400, 18.0, (2, 0.0))
    monkeypatch.setattr(mf, "LOBE_OUT", 30.0)
    monkeypatch.setattr(mf, "LOBE_IN", 100.0)
    with pytest.raises(ValueError, match="rayon"):
        mf.lobed_inner_path(ch, 1, 300, 400, 18.0, (2, 0.0))


@pytest.mark.parametrize("size", [(250, 400), (400, 250), (270, 270)])
def test_lobed_mode_rejects_a_map_too_small_for_the_lobes_upfront(size, monkeypatch):
    """Carte où l'anneau existe mais où LOBE_IN écraserait le chemin : erreur
    explicite dès l'entrée de build_course, avant relief et routage."""
    width, height = size
    mf.ring_semi_axes(width, height)                      # le mode ring reste possible
    def forbidden(*args, **kwargs):
        raise AssertionError("relief chargé malgré une carte trop petite")
    monkeypatch.setattr(mf, "load_terrain", forbidden)
    with pytest.raises(ValueError, match="trop petite pour le mode lobed"):
        mf.build_course(1, "muirfield", width=width, height=height, path_mode="lobed")


@pytest.mark.parametrize("size", [(300, 400), (400, 300), (350, 400), (400, 400)])
def test_lobe_room_accepts_the_measured_formats(size):
    mf.check_lobe_room(*size)


def test_lobe_room_rejects_lobes_leaving_the_map(monkeypatch):
    monkeypatch.setattr(mf, "LOBE_OUT", 200.0)
    with pytest.raises(ValueError, match="sortent de la carte"):
        mf.check_lobe_room(300, 400)


def test_unknown_path_mode_raises():
    with pytest.raises(ValueError, match="path_mode"):
        mf.build_course(1, "muirfield", width=300, height=400, path_mode="spirale")
    with pytest.raises(ValueError, match="path_mode"):
        mf.build_muirfield(1, width=300, height=400, path_mode="spirale")


def test_ring_mode_draws_no_lobes(monkeypatch):
    def forbidden(seed):
        raise AssertionError("tirage de lobes en mode ring")
    monkeypatch.setattr(mf, "lobe_parameters", forbidden)
    result = mf.build_course(1, "muirfield", width=300, height=400, width_mode="min")
    assert result.path_mode == "ring" and result.lobes is None
    assert result.front_path == result.front_ring_path
    assert result.back_path == result.back_ring_path


@pytest.mark.parametrize("pattern", mf.PATTERNS)
def test_lobed_mode_only_bends_the_inner_nine(pattern, monkeypatch):
    ring = mf.build_course(1, pattern, width=300, height=400, width_mode="min")
    received: list[tuple] = []
    original = mf.green_targets

    def recording(path, pars, factors=None):
        received.append(tuple(path))
        return original(path, pars, factors)

    monkeypatch.setattr(mf, "green_targets", recording)
    lobed = mf.build_course(1, pattern, width=300, height=400, width_mode="min",
                            path_mode="lobed")
    # tentative retenue = deux derniers appels (front puis back) : les cibles
    # du nine intérieur sont calculées sur le chemin à lobes, celles du nine
    # extérieur sur l'anneau
    assert received[-2:] == [lobed.front_path, lobed.back_path]
    assert lobed.path_mode == "lobed" and lobed.lobes == mf.lobe_parameters(1)
    assert lobed.violations == ()
    assert (lobed.outer_ring, lobed.inner_ring) == (ring.outer_ring, ring.inner_ring)
    inner = "back_path" if mf.outer_start(pattern) == 1 else "front_path"
    outer = "front_path" if inner == "back_path" else "back_path"
    assert getattr(lobed, outer) == getattr(lobed, outer.replace("path", "ring_path"))
    assert getattr(lobed, inner) != getattr(lobed, inner.replace("path", "ring_path"))
    plan = lobed.plan
    _, _, front_ring, back_ring = mf.nine_paths(plan.clubhouse, plan.direction, 300, 400,
                                                plan.outer_delta_deg, plan.inner_delta_deg,
                                                pattern)
    assert (lobed.front_ring_path, lobed.back_ring_path) == (tuple(front_ring), tuple(back_ring))


# -- tentatives sans doublon (échecs prouvés sautés) ---------------------------

def _outcome(pattern: str, seed: int, width: int, height: int):
    """(attempts, skipped, plan ou None) d'un build_course."""
    try:
        result = mf.build_course(seed, pattern, width=width, height=height)
    except mf.MuirfieldRoutingError as error:
        return tuple(error.attempts), tuple(error.skipped), None
    return result.attempts, result.skipped, result.plan


@pytest.fixture(scope="module")
def dedup_cases():
    # inverse 17 (300×400) : échecs d'ancrage SANS coupure au clubhouse 0 ;
    # inverse 20 (400×300) : échecs d'ancrage coupés (k enfants) aux clubhouses
    # 0 et 2, clubhouse 1 infaisable
    return {key: _outcome(*key) for key in (("muirfield_inverse", 17, 300, 400),
                                            ("muirfield_inverse", 20, 400, 300))}


def _key(entry: dict) -> tuple[int, int, int]:
    return entry["clubhouse_index"], entry["permutation_index"], entry["angle_index"]


def test_attempt_keys_are_unique_and_capped(results, dedup_cases):
    outcomes = [(r.attempts, r.skipped) for r in results.values()]
    outcomes += [(attempts, skipped) for attempts, skipped, _ in dedup_cases.values()]
    for attempts, skipped in outcomes:
        keys = [_key(a) for a in attempts]
        assert len(keys) == len(set(keys))
        assert len(attempts) <= mf.MAX_ATTEMPTS
        skipped_keys = [_key(s) for s in skipped]
        assert len(skipped_keys) == len(set(skipped_keys))
        assert not set(keys) & set(skipped_keys)        # sautées : hors de attempts


def test_dedup_is_deterministic(dedup_cases):
    key = ("muirfield_inverse", 17, 300, 400)
    assert _outcome(*key) == dedup_cases[key]


def test_only_exhaustive_anchor_failures_are_skipped(dedup_cases):
    attempts, skipped, plan = dedup_cases[("muirfield_inverse", 17, 300, 400)]
    by_key = {_key(a): a for a in attempts}
    assert plan is not None and skipped
    for entry in skipped:
        assert entry["reason"] == "echec_ancrages_prouve"
        proof = by_key[tuple(entry["proven_by"])]
        assert proof["status"] == "echec_ancrages" and proof["anchor_truncated"] is False
        assert proof["clubhouse_index"] == entry["clubhouse_index"]
        assert entry["key"]["clubhouse_index"] == entry["clubhouse_index"]
    # angles 1 et 2 du clubhouse 0 sautés pour chaque permutation
    assert {_key(s) for s in skipped} == {(0, p, a) for p in range(3) for a in (1, 2)}


def test_truncated_anchor_failures_are_not_skipped(dedup_cases):
    attempts, skipped, plan = dedup_cases[("muirfield_inverse", 20, 400, 300)]
    for ch in (0, 2):
        entries = [a for a in attempts if a["clubhouse_index"] == ch]
        assert len(entries) == 9                         # toutes les variantes tentées
        assert all(a["status"] == "echec_ancrages" and a["anchor_truncated"] for a in entries)
    assert not [s for s in skipped if s["clubhouse_index"] in (0, 2)]
    # au-delà des clubhouses 0-2 : la position 3 prend le relais
    assert plan is not None and plan.clubhouse_index == 3


@pytest.mark.parametrize("children", (mf.CHILDREN_PER_NODE, 10 ** 6))
def test_truncation_is_flagged_and_prevents_skips(monkeypatch, children):
    """Cas construit (muirfield 19, 400×300, clubhouse 0, permutations 0 et
    1 seules — la permutation 2 réussit) : avec k = 3
    la pose du trou 1 est coupée (plus de 3 enfants), rien n'est sauté ;
    avec k levé DANS CE TEST, la même recherche devient exhaustive et les
    angles 1 et 2 sont sautés."""
    real = mf.iter_plans
    monkeypatch.setattr(mf, "iter_plans", lambda *args, **kwargs: (
        item for item in real(*args, **{**kwargs, "clubhouses": 1}) if item[0][1] < 2))
    monkeypatch.setattr(mf, "CHILDREN_PER_NODE", children)
    attempts, skipped, plan = _outcome("muirfield", 19, 400, 300)
    assert plan is None and {a["status"] for a in attempts} == {"echec_ancrages"}
    truncated = children == 3
    assert all(a["anchor_truncated"] is truncated for a in attempts)
    if truncated:
        assert skipped == () and len(attempts) == 6
    else:
        assert {_key(a)[2] for a in attempts} == {0}
        assert {_key(s)[2] for s in skipped} == {1, 2}
        assert {s["reason"] for s in skipped} == {"echec_ancrages_prouve"}
        assert len(attempts) + len(skipped) == 6


def test_infeasible_clubhouse_yields_a_single_attempt(dedup_cases):
    attempts, _, _ = dedup_cases[("muirfield_inverse", 20, 400, 300)]
    infeasible = [a for a in attempts if a["status"] == "infaisable_ancrage"]
    assert [_key(a) for a in infeasible] == [(1, 0, 0)]
    assert all(a["clubhouse_index"] != 1 for a in attempts if a["status"] != "infaisable_ancrage")


def test_identical_plan_is_skipped(monkeypatch):
    real = mf.iter_plans

    def twice(*args, **kwargs):
        indices, plan = next(iter(real(*args, **kwargs)))
        yield indices, plan
        yield (indices[0], indices[1] + 1, indices[2]), dataclasses.replace(
            plan, permutation_index=indices[1] + 1)

    monkeypatch.setattr(mf, "iter_plans", twice)
    monkeypatch.setattr(mf, "validate",
                        lambda layout, rules: [Violation("length", (1,), "injectée")])
    with pytest.raises(mf.MuirfieldRoutingError) as info:
        mf.build_muirfield(3, width=350, height=400)
    assert [a["status"] for a in info.value.attempts] == ["echec_validate"]
    assert [(s["reason"], s["proven_by"]) for s in info.value.skipped] == [
        ("plan_identique", list(_key(info.value.attempts[0])))]


def test_clubhouse_positions_beyond_the_first_three_follow_the_seeded_stream():
    plans = list(mf.iter_plans(5, 300, 400, clubhouses=5))
    assert [p.clubhouse_index for _, p in plans] == [ch for ch in range(5) for _ in range(9)]
    for _, plan in plans[27:]:
        rng = np.random.default_rng([5, 11, plan.clubhouse_index])
        assert (plan.edge, plan.clubhouse) == mf.place_clubhouse(rng, 300, 400)


def _forced_attempt(monkeypatch, pattern, seed, width, height, target):
    """Une variante relancée seule (aucun saut possible)."""
    real = mf.iter_plans

    def only(*args, **kwargs):
        for indices, plan in real(*args, **kwargs):
            if indices == target:
                yield indices, plan
                return

    monkeypatch.setattr(mf, "iter_plans", only)
    attempts, _, _ = _outcome(pattern, seed, width, height)
    monkeypatch.undo()
    return attempts[0]


@pytest.mark.parametrize("perm", range(3))
def test_exhaustive_anchor_failure_is_angle_invariant(monkeypatch, perm):
    """Preuve empirique de l'hypothèse sur un vrai cas sans coupure (inverse
    17, 300×400, clubhouse 0) : les trois angles relancés de force donnent
    le même échec, compteurs compris."""
    forced = [_forced_attempt(monkeypatch, "muirfield_inverse", 17, 300, 400, (0, perm, angle))
              for angle in range(3)]
    assert all(a["status"] == "echec_ancrages" and not a["anchor_truncated"] for a in forced)
    summary = {(a["checks"], a["nodes"], tuple(a["rejections"].items()),
                tuple(a["deepest"].items())) for a in forced}
    assert len(summary) == 1


def test_exhaustive_anchor_failure_is_angle_invariant_on_a_deeper_tree(monkeypatch):
    """Même invariant sur un arbre d'ancrages plus profond (muirfield 19,
    400×300, 94 nœuds) : k est levé DANS CE TEST SEULEMENT pour que la
    recherche des ancrages soit exhaustive (aucun budget de production
    modifié)."""
    forced = []
    for angle in range(3):
        monkeypatch.setattr(mf, "CHILDREN_PER_NODE", 10 ** 6)
        forced.append(_forced_attempt(monkeypatch, "muirfield", 19, 400, 300, (0, 0, angle)))
    assert all(a["status"] == "echec_ancrages" and not a["anchor_truncated"] for a in forced)
    assert len({(a["checks"], a["nodes"], tuple(a["rejections"].items())) for a in forced}) == 1
    assert forced[0]["nodes"] > 50
