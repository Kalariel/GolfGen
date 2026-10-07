"""Étape 3, r4 — squelette par régions (``experiments/elastic_routing/regions.py``).

Seeds 1–30 × w_min 2/3/4. Les vérifications géométriques (dégagement,
croisements, appartenance à la région) sont réimplémentées ici sans passer
par les helpers de validation du module, pour ne pas tester le code par
lui-même.
"""

from __future__ import annotations

import math
from functools import lru_cache

import numpy as np
import pytest

from experiments.elastic_routing.geometry import segments_intersect
from experiments.elastic_routing.model import PAR_SPECS
from experiments.elastic_routing.regions import (
    CELL_BY_W_MIN,
    ENDPOINT_MAX_DIST,
    FAIRWAY_GAP,
    HALF_FAIRWAY_MAX,
    RegionGenerationError,
    RegionsResult,
    build_regions,
    check_parameters,
    has_hole,
    has_pinch,
    is_4_connected,
    nine_length_window,
    render_regions_svg,
)
from experiments.elastic_routing.skeleton import MAP_SIZE, NINE_PAR_PATTERN, is_simple_polyline


SEEDS = range(1, 31)
W_MINS = (2, 3, 4)
CASES = [(seed, w) for w in W_MINS for seed in SEEDS]
ARC_EXEMPT = 60.0
STEP = 3.0


@lru_cache(maxsize=None)
def _built(seed: int, w_min: int) -> RegionsResult:
    return build_regions(seed, w_min)


def _resample(points, step: float, closed: bool):
    pts = list(points) + ([points[0]] if closed else [])
    out, arcs, travelled = [pts[0]], [0.0], 0.0
    next_s = step
    for a, b in zip(pts, pts[1:]):
        seg = math.dist(a, b)
        while seg > 1e-12 and next_s <= travelled + seg:
            t = (next_s - travelled) / seg
            out.append((a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t))
            arcs.append(next_s)
            next_s += step
        travelled += seg
    return np.array(out), np.array(arcs), travelled


def _min_far_distance(points, closed: bool) -> float:
    pts, s, total = _resample(points, STEP, closed)
    dist = np.hypot(pts[:, None, 0] - pts[None, :, 0], pts[:, None, 1] - pts[None, :, 1])
    arc = np.abs(s[:, None] - s[None, :])
    if closed:
        arc = np.minimum(arc, total - arc)
    return float(dist[arc > ARC_EXEMPT].min())


def _mask(result: RegionsResult, cells) -> np.ndarray:
    return result.mask(cells)


def _inside(point, polygon) -> bool:
    x, y = point
    inside = False
    for (x1, y1), (x2, y2) in zip(polygon, polygon[1:] + polygon[:1]):
        if (y1 > y) != (y2 > y):
            if x < x1 + (y - y1) * (x2 - x1) / (y2 - y1):
                inside = not inside
    return inside


def _dist_to_polygon(point, polygon) -> float:
    best = math.inf
    for a, b in zip(polygon, polygon[1:] + polygon[:1]):
        dx, dy = b[0] - a[0], b[1] - a[1]
        t = max(0.0, min(1.0, ((point[0] - a[0]) * dx + (point[1] - a[1]) * dy) / (dx * dx + dy * dy)))
        best = min(best, math.dist(point, (a[0] + t * dx, a[1] + t * dy)))
    return best


# ----------------------------------------------------------------------
# Paramètres et budget
# ----------------------------------------------------------------------

def test_length_window_derived_from_par_specs():
    low = sum(PAR_SPECS[p].length_min for p in NINE_PAR_PATTERN) + 10 * 12
    high = sum(PAR_SPECS[p].length_max for p in NINE_PAR_PATTERN) + 10 * 60
    assert nine_length_window() == (low, high) == (1220.0, 2165.0)


@pytest.mark.parametrize("w_min", W_MINS)
def test_chosen_parameters_satisfy_constraints(w_min):
    cell = CELL_BY_W_MIN[w_min]
    check_parameters(w_min, cell)
    assert w_min * cell - 2 * 9.0 >= FAIRWAY_GAP


def test_invalid_parameters_are_rejected():
    with pytest.raises(ValueError):
        check_parameters(2, cell=19.0)  # 2*19 - 18 = 20 < 23


def test_impossible_budget_is_rejected_explicitly_and_bounded():
    with pytest.raises(RegionGenerationError) as info:
        build_regions(1, 2, length_window=(5000.0, 6000.0), max_attempts=5)
    assert info.value.attempts == 5
    assert sum(info.value.reasons.values()) == 5


# ----------------------------------------------------------------------
# Invariants par seed × w_min
# ----------------------------------------------------------------------

@pytest.mark.parametrize("seed,w_min", CASES)
def test_deterministic(seed, w_min):
    first, second = _built(seed, w_min), build_regions(seed, w_min)
    assert first.front_cells == second.front_cells and first.back_cells == second.back_cells
    assert first.front_path == second.front_path and first.back_path == second.back_path
    assert first.attempts_used == second.attempts_used


@pytest.mark.parametrize("seed,w_min", CASES)
def test_regions_simply_connected_wide_and_separated(seed, w_min):
    result = _built(seed, w_min)
    front, back = _mask(result, result.front_cells), _mask(result, result.back_cells)
    for region in (front, back):
        assert is_4_connected(region)
        assert not has_hole(region)
        assert not has_pinch(region)
        # union de blocs w×w entiers : chaque cellule appartient à un bloc w×w de la région
        n = region.shape[0]
        covered = np.zeros_like(region)
        for i in range(n - w_min + 1):
            for j in range(n - w_min + 1):
                if region[i:i + w_min, j:j + w_min].all():
                    covered[i:i + w_min, j:j + w_min] = True
        assert np.array_equal(covered, region)
    assert not np.any(front & back)
    px, py = result.clubhouse_vertex
    junction = {(px - 1, py - 1), (px, py), (px - 1, py), (px, py - 1)}
    contacts = set()
    for i, j in result.front_cells:
        for di in (-1, 0, 1):
            for dj in (-1, 0, 1):
                if (i + di, j + dj) in result.back_cells:
                    contacts.add(((i, j), (i + di, j + dj)))
    # couloir >= 1 cellule partout, sauf le contact diagonal au coin clubhouse
    assert len(contacts) == 1
    (a, b), = contacts
    assert a in junction and b in junction and abs(a[0] - b[0]) == 1 and abs(a[1] - b[1]) == 1


@pytest.mark.parametrize("seed,w_min", CASES)
def test_paths_closed_simple_inside_and_clear(seed, w_min):
    result = _built(seed, w_min)
    low, high = result.length_window
    for path, loop, polygon, length in (
        (result.front_path, result.front_loop, result.front_polygon, result.front_length),
        (result.back_path, result.back_loop, result.back_polygon, result.back_length),
    ):
        assert is_simple_polyline(list(loop))
        assert low <= length <= high
        assert length == pytest.approx(sum(math.dist(a, b) for a, b in zip(path, path[1:])))
        # fermé à l'ouverture clubhouse près, et extrémités au clubhouse
        assert math.dist(path[0], path[-1]) < 2 * ENDPOINT_MAX_DIST
        for end in (path[0], path[-1]):
            assert math.dist(end, result.clubhouse) <= ENDPOINT_MAX_DIST
        # dans sa région, à ~d du bord, et dans la carte avec la marge d'un demi-fairway
        for point in path:
            assert _inside(point, list(polygon))
            assert _dist_to_polygon(point, list(polygon)) >= result.inset - 0.05
            assert HALF_FAIRWAY_MAX <= point[0] <= MAP_SIZE - HALF_FAIRWAY_MAX
            assert HALF_FAIRWAY_MAX <= point[1] <= MAP_SIZE - HALF_FAIRWAY_MAX
        # portions non voisines le long de l'arc (> 60 blocs) : >= 23 blocs
        assert _min_far_distance(list(path), closed=True) >= FAIRWAY_GAP


@pytest.mark.parametrize("seed,w_min", CASES)
def test_front_and_back_never_cross_nor_touch(seed, w_min):
    result = _built(seed, w_min)
    front, back = result.front_path, result.back_path
    for a, b in zip(front, front[1:]):
        for c, d in zip(back, back[1:]):
            assert not segments_intersect(a, b, c, d)
    pf, _, _ = _resample(list(front), STEP, closed=False)
    pb, _, _ = _resample(list(back), STEP, closed=False)
    dist = np.hypot(pf[:, None, 0] - pb[None, :, 0], pf[:, None, 1] - pb[None, :, 1])
    assert float(dist.min()) >= FAIRWAY_GAP


@pytest.mark.parametrize("seed,w_min", CASES)
def test_attempts_within_target(seed, w_min):
    assert _built(seed, w_min).attempts_used <= 200


def test_render_marks_start_and_return_of_each_nine():
    svg = render_regions_svg(_built(1, 3))
    for label in ("départ 1", "retour 9", "départ 10", "retour 18", ">CH<"):
        assert label in svg
    assert "<polyline" in svg and render_regions_svg(_built(1, 3), show_regions=False).count("<polygon") < svg.count("<polygon")
