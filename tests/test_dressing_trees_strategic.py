"""Arbres stratégiques (``golfgen.dressing.trees.strategic``) : constantes
validées, géométrie du module, zones de retombée face au vrai pipeline,
mémoire de la pose, sur de vrais parcours. Invariants de la sortie : oracle
indépendant (``tests/test_dressing_trees_oracle.py``)."""

from __future__ import annotations

from dataclasses import replace
import importlib.util
import json
import math
from pathlib import Path
import subprocess
import sys

import numpy as np
import pytest

import golfgen.dressing.bunkers  # noqa: F401 (importé d'avance : ``sites`` lierait sinon l'espion de ``landing_zones``)
from golfgen.dressing import fairway, fairway_profile, fairway_water
from golfgen.dressing.from_json import course_input_from_json
from golfgen.dressing.paths.scene import scene_from_json
from golfgen.dressing.trees import TreeError
from golfgen.dressing.trees import geometry as geo
from golfgen.dressing.trees import strategic as sg

ROOT = Path(__file__).resolve().parents[1]
COURSES = ((28399, "parkland"), (85660, "parkland"), (50140, "parkland"), (28399, "links"), (4, "links"))
SPY_COURSES = ((28399, "parkland"), (50140, "parkland"), (4, "links"))
R_C = math.hypot(3.5, 0.5)  # couronne réelle


@pytest.fixture(scope="module", params=COURSES, ids=lambda c: f"{c[1]}_{c[0]}")
def course_data(request, tmp_path_factory):
    seed, style = request.param
    path = tmp_path_factory.mktemp("trees_strategic") / "course.json"
    subprocess.run([sys.executable, str(ROOT / "pipeline.py"), "--seed", str(seed), "--style", style,
                    "--output", str(path)], check=True, cwd=ROOT, stdout=subprocess.DEVNULL)
    return json.loads(path.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def scene(course_data):
    return scene_from_json(course_data)


@pytest.fixture(scope="module")
def course(course_data):
    return course_input_from_json(course_data)


@pytest.fixture(scope="module")
def masks(course_data, scene):
    return geo.forbidden_masks(course_data, scene)


@pytest.fixture(scope="module")
def placed(course_data, course, masks):
    return sg.place_strategic(course_data, course, masks)


# === Constantes et géométrie du module ===

def test_defaults_are_the_validated_ones():
    assert (sg.ENCROACHMENT, sg.CROWN_RADIUS) == (3.0, 3)
    assert (sg.LANDING_AXIS_MARGIN, sg.AXIS_CLEARANCE, sg.PASSAGE_MIN, sg.TWIN_SPACING, sg.TWIN_PROBABILITY,
            sg.TRIAL_OFFSETS, sg.SECTOR_CENTER, sg.SECTOR_HALF, sg.GREEN_EDGE_GAP, sg.GREEN_TRIAL_ANGLES,
            sg.QUOTA_DIVISOR, sg.SECTION_STEP, sg.SECTION_SCAN) == \
        (0.5, 2.0, 6.0, 8.0, 0.5, (0.0, 4.0, -4.0, 8.0, -8.0), 90.0, 45.0, 1.0,
         (0.0, 15.0, -15.0, 30.0, -30.0), 3, 0.1, 18.0)


def test_crown_reach_is_the_measured_354():
    farthest = max(math.hypot(abs(dx) + 0.5, abs(dy) + 0.5) for dx, dy in geo.CROWN_DISCS[sg.CROWN_RADIUS].tolist())
    assert farthest == pytest.approx(sg.CROWN_REACH)
    assert farthest == pytest.approx(3.5355, abs=1e-3)


@pytest.mark.parametrize("half, e, expected", [
    (8.0, 1.5, 9.5),                    # empiètement seul
    (5.52, 4.5, R_C + 0.5),             # marge de couronne à l'axe, seule à dominer
    (3.0, 1.5, 6.0 - 3.0 + R_C),        # passage libre
])
def test_landing_offset_formula(half, e, expected):
    assert sg.landing_offset(half, e) == pytest.approx(expected)


def test_ray_exit_and_contains_on_a_square():
    square = np.array([(0.0, 0.0), (10.0, 0.0), (10.0, 10.0), (0.0, 10.0)])
    assert sg.contains(square, (5.0, 5.0)) and not sg.contains(square, (11.0, 5.0))
    assert sg.ray_exit(square, (5.0, 5.0), (1.0, 0.0)) == pytest.approx(5.0)
    assert sg.fairway_half_width([square], (20.0, 5.0), (1.0, 0.0)) is None


def test_segment_square_distance_cases():
    assert sg.segment_square_distance(2, 2, (0.0, 2.5), (5.0, 2.5)) == 0.0      # traverse
    assert sg.segment_square_distance(2, 2, (0.0, 5.0), (5.0, 5.0)) == pytest.approx(2.0)
    assert sg.segment_square_distance(2, 2, (6.0, 3.0), (9.0, 3.0)) == pytest.approx(3.0)
    assert sg.segment_square_distance(2, 2, (5.0, 6.0), (5.0, 6.0)) == pytest.approx(math.hypot(2.0, 3.0))


def test_section_free_counts_the_crown_cut():
    square = np.array([(-10.0, -10.0), (10.0, -10.0), (10.0, 10.0), (-10.0, 10.0)])
    crowns = np.array([[4, -1]])     # case [4, 5] × [-1, 0], sur la coupe y = 0 à son bord
    free, cut = sg.section_free((0.0, -0.5), (1.0, 0.0), [square], crowns)
    assert cut and free == pytest.approx(14.0)
    free, cut = sg.section_free((0.0, 5.5), (1.0, 0.0), [square], crowns)
    assert not cut and free == pytest.approx(20.0)
    assert sg.section_free((50.0, 0.0), (1.0, 0.0), [square], crowns) is None


def test_quota_rounds_a_third():
    assert [round(n / sg.QUOTA_DIVISOR) for n in (0, 14, 15, 16, 17, 18)] == [0, 5, 5, 5, 6, 6]


def test_sector_side_limits():
    points = np.array([(0.0, 0.0), (10.0, 0.0)])
    view = sg.HoleView(1, 4, None, points, (), np.empty((0, 2)), points[-1], np.array((1.0, 0.0)))
    # case dont le centre est à gauche (+y) et à droite (-y) du drapeau, à 90°
    assert sg.sector_side(view, (9, 5)) == 1
    assert sg.sector_side(view, (9, -7)) == -1
    # devant et derrière : hors secteur
    assert sg.sector_side(view, (20, 0)) == 0
    assert sg.sector_side(view, (0, 0)) == 0


# === Vrais parcours ===

def test_trees_are_landing_then_green(placed):
    assert placed.trees == placed.landing.trees + placed.green.trees


def test_is_deterministic(course_data, course, masks, placed):
    assert sg.place_strategic(course_data, course, masks) == placed


def test_a_diverging_zone_is_a_bug(course_data, course, monkeypatch):
    style = course_data["metadata"].get("style") or "links"
    hole = next(hole for hole in course.layout.holes if hole.par in (4, 5))
    real = sg.landing_zones
    monkeypatch.setattr(sg, "landing_zones", lambda *args: [z + 1.0 for z in real(*args)] + [1.0])
    with pytest.raises(TreeError, match="zone de retombée"):
        sg.zone_for(hole, style, int(course.seed))


def test_a_full_map_skips_every_hole_without_error(course_data, course, masks):
    full = replace(masks, water=np.ones_like(masks.water))
    result = sg.place_strategic(course_data, course, full)
    eligible = sum(1 for hole in course.layout.holes if hole.par in (4, 5))
    assert result.trees == ()
    assert sum(result.landing.skips.values()) == eligible
    assert sum(result.green.skips.values()) == 18


@pytest.mark.parametrize("data", [{}, {"bunkers": None}, {"bunkers": {}}], ids=str)
def test_bunkers_are_required(data):
    with pytest.raises(TreeError, match="bunkers.items"):
        sg.green_bunker_cells({"routing": {}, **data}, [1])


# === Zones : le rejeu face au vrai pipeline ===

def _load_pipeline(monkeypatch):
    spec = importlib.util.spec_from_file_location("golfgen_pipeline_under_test", ROOT / "pipeline.py")
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, spec.name, module)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize("seed, style", SPY_COURSES, ids=lambda v: str(v))
def test_replay_uses_the_zones_of_the_real_pipeline(seed, style, tmp_path, monkeypatch):
    output = tmp_path / "course.json"
    real_field, real_zones = fairway_profile.profiled_field, fairway.landing_zones
    current: dict[str, int] = {}

    def spy_field(hole, *args, **kwargs):
        current["order"] = hole.order
        try:
            return real_field(hole, *args, **kwargs)
        finally:
            del current["order"]     # les bunkers rejouent aussi ``landing_zones`` : hors du fairway, ignorés

    def zones_spy(into: dict[int, list]):
        def spy(axis, par, draws):
            zones = real_zones(axis, par, draws)
            if "order" in current:
                into.setdefault(current["order"], []).append(
                    (tuple(zones), tuple(float(v) for v in draws["plateau"][:len(zones)]), float(draws["drive"])))
            return zones
        return spy

    built: dict[int, list] = {}
    pipeline = _load_pipeline(monkeypatch)
    with monkeypatch.context() as patch:
        patch.setattr(fairway, "landing_zones", zones_spy(built))
        patch.setattr(fairway_profile, "profiled_field", spy_field)
        patch.setattr(fairway_water, "profiled_field", spy_field)
        assert pipeline.main(["--seed", str(seed), "--style", style, "--output", str(output)]) == 0

    course = course_input_from_json(json.loads(output.read_text(encoding="utf-8")))
    assert sorted(built) == list(range(1, 19))
    used: dict[int, list] = {}
    monkeypatch.setattr(sg, "landing_zones", zones_spy(used))
    for hole in course.layout.holes:
        current["order"] = hole.order
        target = sg.zone_for(hole, style, int(course.seed))
        assert len(set(built[hole.order])) == 1, hole.order
        assert used[hole.order] == [built[hole.order][0]], hole.order
        zones, plateaus, drive = built[hole.order][0]
        if zones:
            index = min(range(len(zones)), key=lambda k: abs(zones[k] - drive))
            assert target == (zones[index], plateaus[index]), hole.order
        else:
            assert target is None, hole.order


# === Mémoire de la pose ===

def test_mark_fills_the_whole_crown():
    forbidden = np.zeros((20, 20), dtype=bool)
    sg._mark(forbidden, [(10, 9)])
    assert np.array_equal(forbidden, geo.crown_mask([(10, 9, sg.CROWN_RADIUS)], 20, 20))


def test_placed_crowns_stay_forbidden_for_the_next_holes(course_data, course, masks, monkeypatch):
    real_landing, real_green = sg.place_landing, sg.place_green
    placed: list[tuple[int, int]] = []
    checks: list[int] = []

    def check(forbidden):
        for cell in placed:
            crown = sg.crown_cells(cell)
            assert forbidden[crown[:, 1], crown[:, 0]].all(), cell
            checks.append(1)

    def spy_landing(view, zone, plateau, rng, forbidden, encroachment):
        check(forbidden)
        out = real_landing(view, zone, plateau, rng, forbidden, encroachment)
        placed.extend(out[0])
        return out

    def spy_green(view, bunkers, rng, forbidden, landing):
        check(forbidden)
        out = real_green(view, bunkers, rng, forbidden, landing)
        if out[0] is not None:
            placed.append(out[0])
        return out

    monkeypatch.setattr(sg, "place_landing", spy_landing)
    monkeypatch.setattr(sg, "place_green", spy_green)
    sg.place_strategic(course_data, course, masks)
    assert checks


def test_green_layer_receives_the_landing_trees(course_data, course, masks, placed, monkeypatch):
    real = sg.place_green
    seen: dict[int, tuple] = {}

    def spy(view, bunkers, rng, forbidden, landing):
        seen[view.order] = tuple(landing)
        return real(view, bunkers, rng, forbidden, landing)

    monkeypatch.setattr(sg, "place_green", spy)
    sg.place_strategic(course_data, course, masks)
    by_hole: dict[int, list] = {}
    for tree in placed.landing.trees:
        by_hole.setdefault(tree.hole, []).append((tree.x, tree.z))
    for order, landing in seen.items():
        assert list(landing) == by_hole.get(order, []), order


def test_green_tree_checks_the_passage_with_the_landing_trees(course_data, course, masks, monkeypatch):
    views = sg.hole_views(course_data, course.layout)
    found = next((view, side, angle, forbidden, cell)
                 for view in views.values() if view.fairway
                 for forbidden in [masks.base | masks.others[view.order]]
                 for side in (1, -1) for angle in sg.GREEN_TRIAL_ANGLES
                 for cell in [sg._try_green_tree(view, side, angle, forbidden, ())] if cell is not None)
    view, side, angle, forbidden, cell = found
    landing = [(cell[0] + 9, cell[1])]
    calls: list[list] = []
    monkeypatch.setattr(sg, "sections_ok", lambda _view, trees: calls.append(list(trees)) or False)
    assert sg._try_green_tree(view, side, angle, forbidden, landing) is None
    assert calls == [[*landing, cell]]
    monkeypatch.setattr(sg, "sections_ok", lambda _view, trees: True)
    assert sg._try_green_tree(view, side, angle, forbidden, landing) == cell
