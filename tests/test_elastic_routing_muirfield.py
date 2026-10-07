"""Étape M, round R1 : routage Muirfield glouton (``muirfield.py``, ``sites.py``).

R1 n'est pas une porte de validité : les violations de l'oracle sont
tolérées. Ces tests verrouillent la structure du patron (clubhouse au bord,
quotas de pars, départs/retours au clubhouse, longueurs réalistes) et le
déterminisme. Le relief est mis en cache sur disque (``output/.cache``) :
premier passage ~7 s par seed, ensuite instantané.
"""

from __future__ import annotations

from collections import Counter
import math

import numpy as np
import pytest

from experiments.elastic_routing.model import GLOBAL_PAR_QUOTA, PAR_SPECS
from experiments.elastic_routing import muirfield as mf
from experiments.elastic_routing.render_readable import render_readable_svg
from experiments.elastic_routing.sites import (
    GREEN_SPACING,
    TEE_SPACING,
    WATER_LEVEL,
    build_sites,
    load_terrain,
    min_pairwise_distance,
)


SEEDS = (1, 2, 3, 4, 5, 6)
# R1 glouton sans retour arrière : pour ces seeds le trou 9 ne trouve aucun
# green à distance de liaison du clubhouse (borne de faisabilité : R2).
RETURN_FAILS_R1 = {4, 5}


@pytest.fixture(scope="module")
def results():
    return {seed: mf.build_muirfield(seed) for seed in SEEDS}


def test_build_is_deterministic(results):
    again = mf.build_muirfield(3)
    assert again.layout.to_json() == results[3].layout.to_json()
    assert again.violations == results[3].violations


@pytest.mark.parametrize("seed", SEEDS)
def test_eighteen_holes_and_par_quotas(results, seed):
    layout = results[seed].layout
    assert [hole.order for hole in layout.holes] == list(range(1, 19))
    assert Counter(hole.par for hole in layout.holes) == Counter(GLOBAL_PAR_QUOTA)
    for nine in (layout.front, layout.back):
        counts = Counter(hole.par for hole in nine.holes)
        assert 1 <= counts[3] <= 3
        assert 1 <= counts[5] <= 3


def test_par_split_between_nines_is_not_fixed():
    """La répartition des pars entre nines est tirée par la seed : aucun nine
    n'est systématiquement le plus court."""
    shorter = set()
    for seed in range(1, 40):
        front, back = mf.draw_pars(np.random.default_rng([seed, 7]))
        if sum(front) != sum(back):
            shorter.add("front" if sum(front) < sum(back) else "back")
    assert shorter == {"front", "back"}


@pytest.mark.parametrize("seed", SEEDS)
def test_clubhouse_on_a_map_edge(results, seed):
    result = results[seed]
    ch = result.layout.clubhouse
    edge_distance = min(ch.x, ch.y, result.layout.width - ch.x, result.layout.height - ch.y)
    assert edge_distance <= mf.CLUBHOUSE_EDGE_INSET + 1e-9


@pytest.mark.parametrize("seed", SEEDS)
def test_nines_loop_in_opposite_directions(results, seed):
    """Front sur l'anneau extérieur dans un sens, back sur l'intérieur en sens
    inverse : aires signées opposées des chemins cibles."""
    def signed_area(path):
        pts = np.asarray(path)
        return 0.5 * float(np.sum(pts[:-1, 0] * pts[1:, 1] - pts[1:, 0] * pts[:-1, 1]))

    result = results[seed]
    assert signed_area(result.front_path) * signed_area(result.back_path) < 0.0
    center = np.array([200.0, 200.0])
    outer = np.hypot(*(np.asarray(result.outer_ring) - center).T)
    inner = np.hypot(*(np.asarray(result.inner_ring) - center).T)
    assert inner.max() < outer.min()


@pytest.mark.parametrize("seed", SEEDS)
def test_first_tees_leave_from_the_clubhouse(results, seed):
    layout = results[seed].layout
    ch = (layout.clubhouse.x, layout.clubhouse.y)
    for nine in (layout.front, layout.back):
        tee = nine.holes[0].tee
        assert mf.CLUBHOUSE_LINK_MIN <= math.dist(ch, (tee.x, tee.y)) <= mf.LINK_MAX


@pytest.mark.parametrize("seed", [
    pytest.param(seed, marks=pytest.mark.xfail(
        strict=True, reason="R1 sans retour arrière : retour au clubhouse borné en R2"))
    if seed in RETURN_FAILS_R1 else seed
    for seed in SEEDS
])
def test_last_greens_return_near_the_clubhouse(results, seed):
    layout = results[seed].layout
    ch = (layout.clubhouse.x, layout.clubhouse.y)
    for nine in (layout.front, layout.back):
        green = nine.holes[-1].green
        assert math.dist(ch, (green.x, green.y)) <= mf.LINK_MAX


@pytest.mark.parametrize("seed", SEEDS)
def test_hole_lengths_within_realistic_par_specs(results, seed):
    for hole in results[seed].layout.holes:
        assert PAR_SPECS[hole.par].accepts_length(hole.length), (hole.order, hole.length)
        assert len(hole.doglegs) <= 1


@pytest.mark.parametrize("seed", SEEDS)
def test_front_sites_avoid_the_clubhouse_sector(results, seed):
    result = results[seed]
    ch = (result.layout.clubhouse.x, result.layout.clubhouse.y)
    points = np.array([(p.x, p.y) for hole in result.layout.front.holes
                       for p in (hole.tee, hole.green)])
    assert not mf.in_front_sector(points, ch).any()


@pytest.mark.parametrize("seed", (1, 4))
def test_sites_are_spaced_dry_and_deterministic(seed):
    heightmap = load_terrain(seed)
    for kind, spacing in (("green", GREEN_SPACING), ("tee", TEE_SPACING)):
        sites = build_sites(heightmap, seed, kind)
        assert len(sites) > 100
        assert min_pairwise_distance(sites.points) >= spacing - 1e-9
        ix, iy = sites.points[:, 0].astype(int), sites.points[:, 1].astype(int)
        assert (heightmap[iy, ix] >= WATER_LEVEL).all()
        assert ((sites.scores >= 0.0) & (sites.scores <= 1.0)).all()
        again = build_sites(heightmap, seed, kind)
        assert np.array_equal(again.points, sites.points)


def test_flat_relief_falls_back_to_seeded_random_scores():
    flat = np.full((400, 400), 70.0, dtype=np.float32)
    first = build_sites(flat, 5, "green")
    assert first.random_scores
    assert np.array_equal(first.points, build_sites(flat, 5, "green").points)
    assert not np.array_equal(first.points, build_sites(flat, 6, "green").points)


def test_readable_render_numbers_every_hole(results):
    result = results[1]
    svg = render_readable_svg(result.layout, result.violations,
                              rings=(result.outer_ring, result.inner_ring), title="t")
    assert svg.startswith("<svg") and svg.rstrip().endswith("</svg>")
    for order in range(1, 19):
        assert f'text-anchor="middle">{order}</text>' in svg
