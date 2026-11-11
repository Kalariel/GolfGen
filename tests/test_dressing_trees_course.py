"""Arbres d'un parcours (``golfgen.dressing.trees.place_trees``) : constantes
validées, pose gloutonne, rayons, lisière, bruit, ancrages, marge, et
quelques parcours réels. Invariants de la sortie : oracle indépendant
(``tests/test_dressing_trees_oracle.py``) ; sortie figée :
``tests/test_dressing_trees_frozen.py``."""

from __future__ import annotations

from itertools import count
import json
import math
from pathlib import Path
import subprocess
import sys

import numpy as np
import opensimplex
import pytest

from golfgen.dressing.paths.scene import scene_from_json
from golfgen.dressing.rng import TREE_ANCHOR_LAYER, tree_rng
from golfgen.dressing.trees import TreeError, place_trees
from golfgen.dressing.trees import anchors as an
from golfgen.dressing.trees import course as ct
from golfgen.dressing.trees import fill as fl
from golfgen.dressing.trees import geometry as geo

ROOT = Path(__file__).resolve().parents[1]
QUICK = ((28399, "parkland"), (85660, "links"))


def _generate(seed: int, style: str, tmp_path_factory) -> dict:
    path = tmp_path_factory.mktemp("trees_course") / "course.json"
    subprocess.run([sys.executable, str(ROOT / "pipeline.py"), "--seed", str(seed), "--style", style,
                    "--output", str(path)], check=True, cwd=ROOT, stdout=subprocess.DEVNULL)
    return json.loads(path.read_text(encoding="utf-8"))


@pytest.fixture(scope="module", params=QUICK, ids=lambda c: f"{c[1]}_{c[0]}")
def quick_data(request, tmp_path_factory):
    return _generate(*request.param, tmp_path_factory)


def _disc(r: int) -> list[tuple[int, int]]:
    return [(dx, dy) for dy in range(-r, r + 1) for dx in range(-r, r + 1) if dx * dx + dy * dy <= r * r]


# === Constantes validées (lot 5) ===

def test_constants_are_the_validated_ones():
    assert (ct.PRESETS["parkland"].cover, ct.PRESETS["parkland"].edge) == (0.65, 12)
    assert (ct.PRESETS["links"].cover, ct.PRESETS["links"].edge) == (0.05, 0)
    assert (fl.RADIUS_WEIGHTS, fl.PLANTABLE_RADIUS, fl.NOISE_WAVELENGTH, fl.NOISE_SEED_SPAN) == \
        ((0.3, 0.5, 0.2), 2, 40.0, 2 ** 31)
    assert (an.ANCHOR_REACH, an.ANCHOR_TREES, an.ANCHOR_FALLBACK) == (8.0, (1, 3), 2)


# === Pose gloutonne, rayons, lisière, bruit ===

def test_greedy_rejects_and_marks():
    solid = np.zeros((20, 20), dtype=bool)
    crowns = np.zeros_like(solid)
    cells = np.array([(10, 10), (11, 10), (1, 1)], dtype=np.int64)
    placed = fl.greedy(cells, solid, crowns, np.random.default_rng(0), radius=3, shuffle=False)
    assert placed == [(10, 10, 3)]      # (11, 10) chevauche, (1, 1) sort de la carte
    assert crowns[10, 10] and solid[13, 10] and not crowns[14, 10]


def test_radius_draws_follow_the_weights():
    rng = np.random.default_rng(1)
    draws = [fl.draw_radius(rng) for _ in range(40000)]
    for radius, weight in zip(geo.CROWN_RADII, fl.RADIUS_WEIGHTS):
        assert abs(draws.count(radius) / len(draws) - weight) < 0.01


def test_radius_is_held_until_it_fits(monkeypatch):
    draws = iter([4, 2, 3, 2, 2, 2])
    monkeypatch.setattr(fl, "draw_radius", lambda rng: next(draws, 2))
    solid = np.zeros((60, 60), dtype=bool)
    cells = np.array([(2, 2), (30, 30), (45, 45), (10, 40), (40, 10), (15, 15)], dtype=np.int64)
    placed = fl.greedy(cells, solid, np.zeros_like(solid), np.random.default_rng(0), shuffle=False)
    assert [t[2] for t in placed] == [4, 2, 3, 2, 2, 2]     # le 4 refusé en (2, 2) attend (30, 30)


def _fits(occupied: set, cell, r: int, size: int) -> bool:
    x, y = cell
    return r <= x < size - r and r <= y < size - r and not any((x + dx, y + dy) in occupied for dx, dy in _disc(r))


def test_tail_is_only_radius_2_because_3_no_longer_fits():
    """Rejeu indépendant : au début de la queue, plus aucun candidat n'accepte un 3."""
    size = 70
    solid = np.zeros((size, size), dtype=bool)
    cells = np.argwhere(np.ones((size, size), dtype=bool))[:, ::-1]
    placed = fl.greedy(cells, solid, np.zeros_like(solid), np.random.default_rng(3))
    radii = [t[2] for t in placed]
    start = max(i for i, r in enumerate(radii) if r >= 3) + 1
    assert 0 < start < len(radii) and set(radii[start:]) == {2}
    occupied = {(x + dx, y + dy) for x, y, r in placed[:start] for dx, dy in _disc(r)}
    assert not any(_fits(occupied, (int(x), int(y)), 3, size) for x, y in cells.tolist())


def test_edge_band_is_the_rim_and_empty_without_edge():
    band = fl.edge_band(40, 30, 12)
    assert band[11, 20] and band[20, 39] and not band[12, 20]
    assert not fl.edge_band(40, 30, 0).any()


def test_noise_field_is_deterministic_per_seed():
    field = fl.noise_field(28399, 60, 45)
    assert field.shape == (45, 60)
    assert np.array_equal(field, fl.noise_field(28399, 60, 45))
    assert not np.array_equal(field, fl.noise_field(28400, 60, 45))


@pytest.mark.parametrize("cover", (0.05, 0.25, 0.65))
def test_forest_zone_is_a_quantile_insensitive_to_amplitude(cover):
    noise = np.random.default_rng(2).random((60, 60))
    plantable = noise < 0.8
    zone = fl.forest_zone(noise, plantable, cover)
    assert np.count_nonzero(zone) == pytest.approx(cover * np.count_nonzero(plantable), abs=2)
    assert not zone[~plantable].any()
    assert np.array_equal(fl.forest_zone(noise * 37.0 + 5.0, plantable, cover), zone)
    assert not fl.forest_zone(noise, np.zeros_like(plantable), cover).any()


# === Ancrages ===

def test_anchor_candidates_skip_cells_behind_a_path():
    paths = np.array([(12, y) for y in range(0, 21)], dtype=np.int64)
    cells = an.anchor_candidates(10, 10, paths, (21, 21))
    assert (10, 10) == tuple(cells[0])
    assert all(x < 12 for x, _ in cells.tolist())
    assert all(math.hypot(x - 10, y - 10) <= an.ANCHOR_REACH for x, y in cells.tolist())


def test_anchor_falls_back_to_the_smallest_crown(monkeypatch):
    data = {"paths": {"cells": [], "anchors": [[10, 10]]}}
    solid = np.ones((21, 21), dtype=bool)
    solid[8:13, 8:13] = False       # un carré 5 x 5 : seule la couronne de repli tient
    monkeypatch.setattr(an, "draw_radius", lambda rng: 4)
    grove = an.plant_anchors(data, solid, np.zeros_like(solid), 5)[0]
    assert grove.trees[0] == (10, 10, an.ANCHOR_FALLBACK)


@pytest.mark.parametrize("data", [{}, {"paths": None}, {"paths": {"cells": []}}], ids=str)
def test_anchors_are_required(data):
    with pytest.raises(TreeError, match="paths.anchors"):
        an.plant_anchors(data, np.zeros((8, 8), dtype=bool), np.zeros((8, 8), dtype=bool), 1)


# === Ancrages synthétiques : motifs absents des seeds rapides ===

def _plant_one(solid: np.ndarray, seed: int):
    data = {"paths": {"cells": [], "anchors": [[15, 15]]}}
    groves = an.plant_anchors(data, solid.copy(), np.zeros_like(solid), seed)
    assert [(g.index, g.anchor) for g in groves] == [(0, (15, 15))]
    return groves[0]


def test_anchor_without_room_is_sans_place():
    grove = _plant_one(np.ones((30, 30), dtype=bool), 1)
    assert grove.motif == "sans_place" and grove.trees == () and grove.target >= 1


def test_anchor_with_room_for_one_is_partiel():
    seed = next(s for s in count(1) if int(tree_rng(s, TREE_ANCHOR_LAYER, 0).integers(1, 4)) >= 2)
    solid = np.ones((30, 30), dtype=bool)
    free = geo.crown_cells((15, 15), 2)
    solid[free[:, 1], free[:, 0]] = False
    grove = _plant_one(solid, seed)
    assert grove.motif == "partiel" and grove.trees == ((15, 15, 2),) and grove.target >= 2


def test_anchor_with_free_ground_is_complete():
    grove = _plant_one(np.zeros((30, 30), dtype=bool), 1)
    assert grove.motif is None and len(grove.trees) == grove.target


# === Marge ===

@pytest.mark.parametrize("margin", (-3.0, 12.5, float("nan"), float("inf"), True, "5", None), ids=str)
def test_invalid_margin_is_rejected(margin):
    with pytest.raises(ValueError, match="marge des arbres invalide"):
        place_trees({}, margin=margin)


@pytest.mark.parametrize("margin", (0.0, 12.0))
def test_margin_bounds_are_accepted(quick_data, margin):
    assert place_trees(quick_data, margin=margin).items


def test_zero_margin_keeps_edge_and_fill_off_the_core(quick_data):
    scene = scene_from_json(quick_data)
    trees = place_trees(quick_data, margin=0.0, scene=scene)
    core = geo.corridors_mask(quick_data["routing"]["holes"], geo.CORE_MARGIN, scene.width, scene.height)
    crowns = geo.crown_mask([(t.x, t.z, t.radius) for t in trees.layer("lisiere") + trees.layer("remplissage")],
                            scene.width, scene.height)
    assert crowns.any() and not (crowns & core).any()


# === Parcours réels, sous-ensemble rapide ===

def test_is_deterministic(quick_data):
    assert place_trees(quick_data) == place_trees(quick_data)


def test_given_scene_gives_the_same_trees(quick_data):
    assert place_trees(quick_data, scene=scene_from_json(quick_data)) == place_trees(quick_data)


def test_margin_only_moves_edge_and_fill(quick_data):
    default, wider = place_trees(quick_data), place_trees(quick_data, margin=12.0)
    for layer in ("retombee", "green", "ancrage"):
        assert wider.layer(layer) == default.layer(layer), layer
    assert wider.layer("lisiere") + wider.layer("remplissage") != default.layer("lisiere") + default.layer("remplissage")


def test_noise_leaves_the_global_seed_alone(quick_data):
    before = opensimplex.get_seed()
    try:
        opensimplex.seed(424242)
        probe = opensimplex.noise2(0.3, 0.7)
        place_trees(quick_data)
        assert opensimplex.get_seed() == 424242
        assert opensimplex.noise2(0.3, 0.7) == probe
    finally:
        opensimplex.seed(before)


def test_anchor_trees_alone_carry_a_grove(quick_data):
    trees = place_trees(quick_data)
    assert all((item.grove is not None) == (item.layer == "ancrage") for item in trees.items)
    assert set(trees.counts) == set(ct.LAYERS) == set(trees.skips)
