"""Arbres, base du paquet (``golfgen.dressing.trees``) : disques, couronnes,
dilatation, flux, corridors et interdits, contre des références écrites ici
(ou les masques de polygones de ``tools/dressing/rough_plate.py``), sur de
vrais parcours."""

from __future__ import annotations

import ast
import json
from pathlib import Path
import subprocess
import sys

import numpy as np
import pytest

from golfgen.dressing import rng as dressing_rng
from golfgen.dressing.bunkers.selection import SELECTION_STREAM
from golfgen.dressing.paths.scene import obstacle_mask, scene_from_json
from golfgen.dressing.trees import TreeError
from golfgen.dressing.trees import geometry as geo
from golfgen.routing.geometry import buffered_axis
from tools.dressing import rough_plate as rp

ROOT = Path(__file__).resolve().parents[1]
COURSES = ((28399, "parkland"), (85660, "parkland"), (28399, "links"))
MARGINS = (0.0, 3.0, 5.0, 8.0, 12.0)


def _disc(r: int) -> list[tuple[int, int]]:
    """Décalages du disque, ligne par ligne (``dy`` puis ``dx`` croissants)."""
    return [(dx, dy) for dy in range(-r, r + 1) for dx in range(-r, r + 1) if dx * dx + dy * dy <= r * r]


def _dilate(mask: np.ndarray, radius: int) -> np.ndarray:
    """Dilatation sur une copie bordée de ``radius`` cases vides : chaque case
    reçoit les cases du disque autour d'elle."""
    height, width = mask.shape
    padded = np.pad(mask, radius, constant_values=False)
    out = np.zeros_like(mask, dtype=bool)
    for dx, dy in _disc(radius):
        out |= padded[radius - dy:radius - dy + height, radius - dx:radius - dx + width]
    return out


def _corridor(hole, margin: float, width: int, height: int) -> np.ndarray:
    axis = tuple((p["x"], p["y"]) for p in [hole["tee"], *hole["doglegs"], hole["green"]])
    return rp.polygon_mask(buffered_axis(axis, hole["width"] / 2.0 + margin), width, height)


@pytest.fixture(scope="module", params=COURSES, ids=lambda c: f"{c[1]}_{c[0]}")
def course(request, tmp_path_factory):
    seed, style = request.param
    path = tmp_path_factory.mktemp("trees_geometry") / "course.json"
    subprocess.run([sys.executable, str(ROOT / "pipeline.py"), "--seed", str(seed), "--style", style,
                    "--output", str(path)], check=True, cwd=ROOT, stdout=subprocess.DEVNULL)
    return json.loads(path.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def scene(course):
    return scene_from_json(course)


@pytest.fixture(scope="module")
def masks(course, scene):
    return geo.forbidden_masks(course, scene)


# === Fonctions pures ===

@pytest.mark.parametrize("radius", geo.CROWN_RADII)
def test_discs_are_row_major_and_read_only(radius):
    assert [tuple(offset) for offset in geo.CROWN_DISCS[radius].tolist()] == _disc(radius)
    assert not geo.CROWN_DISCS[radius].flags.writeable


@pytest.mark.parametrize("radius", geo.CROWN_RADII)
def test_crown_cells_are_the_disc_around_the_cell(radius):
    assert geo.crown_cells((40, 17), radius).tolist() == [[40 + dx, 17 + dy] for dx, dy in _disc(radius)]


def test_constants_are_the_validated_ones():
    assert (geo.CROWN_RADIUS, geo.APRON, geo.CORRIDOR_MARGIN, geo.CORE_MARGIN) == (3, 3, 5.0, 0.0)
    assert geo.CROWN_RADII == (2, 3, 4)


@pytest.mark.parametrize("radius", geo.CROWN_RADII)
def test_crown_on_map_matches_the_crown_cells(radius):
    width, height = 12, 11
    for y in range(-2, height + 2):
        for x in range(-2, width + 2):
            cells = geo.crown_cells((x, y), radius)
            inside = ((cells[:, 0] >= 0) & (cells[:, 0] < width) & (cells[:, 1] >= 0) & (cells[:, 1] < height)).all()
            assert geo.crown_on_map(x, y, radius, width, height) == bool(inside)


@pytest.mark.parametrize("radius", geo.CROWN_RADII)
def test_crown_fits_on_an_empty_map_is_crown_on_map(radius):
    fits = geo.crown_fits(np.zeros((11, 12), dtype=bool), radius)
    for y in range(11):
        for x in range(12):
            assert fits[y, x] == geo.crown_on_map(x, y, radius, 12, 11)


def test_crown_mask_clips_to_the_map():
    mask = geo.crown_mask([(0, 0, 2)], 8, 8)
    assert mask[0, 0] and mask[2, 0] and mask[0, 2] and not mask[-1, 0] and not mask[0, -1]


@pytest.mark.parametrize("data", [{}, {"paths": None}, {"paths": {}}], ids=str)
def test_paths_mask_requires_the_paths(data):
    with pytest.raises(TreeError, match="paths.cells"):
        geo.paths_mask(data, 8, 8)


@pytest.mark.parametrize("radius", (1, 5))
def test_dilation_handles_any_radius(radius):
    mask = np.zeros((16, 16), dtype=bool)
    mask[8, 8] = mask[0, 15] = True
    assert np.array_equal(geo.dilate_disc(mask, radius), _dilate(mask, radius))
    assert radius not in geo.CROWN_DISCS


def test_tree_error_is_not_a_value_error():
    assert issubclass(TreeError, Exception) and not issubclass(TreeError, ValueError)


# === Flux ===

@pytest.mark.parametrize("words", [(1, 1), (1, 2, 7), (2, 1), (2, 2, 18), (3, 0), (3, 5), (4,), (5,), (6,)],
                         ids=str)
def test_tree_rng_is_its_own_stream(words):
    seed = 28399
    expected = np.random.default_rng([seed, 0x54524532, *words]).random(16)
    assert np.array_equal(dressing_rng.tree_rng(seed, *words).random(16), expected)


def test_tree_stream_constants_are_the_validated_ones():
    assert dressing_rng.TREES_STREAM == 0x54524532
    assert (dressing_rng.TREE_LANDING_LAYER, dressing_rng.TREE_GREEN_LAYER, dressing_rng.TREE_ANCHOR_LAYER,
            dressing_rng.TREE_EDGE_LAYER, dressing_rng.TREE_FILL_LAYER, dressing_rng.TREE_NOISE_LAYER) == \
        (1, 2, 3, 4, 5, 6)
    assert (dressing_rng.TREE_USE_ORDER, dressing_rng.TREE_USE_HOLE) == (1, 2)


def test_tree_stream_is_apart_from_the_others():
    taken = {dressing_rng.RNG_LABEL, SELECTION_STREAM, dressing_rng.EMPTY_HOLE_STREAM,
             dressing_rng.REPLACED_GREEN_STREAM, dressing_rng.BENDS_STREAM,
             *dressing_rng.RETIRED_STREAMS, *dressing_rng.RESERVED_STREAMS}
    assert dressing_rng.TREES_STREAM not in taken


def test_production_never_imports_tools():
    for path in (ROOT / "golfgen" / "dressing" / "trees").glob("*.py"):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            names = ([alias.name for alias in node.names] if isinstance(node, ast.Import)
                     else [node.module or ""] if isinstance(node, ast.ImportFrom) else [])
            assert not any(name.split(".")[0] == "tools" for name in names), path.name


# === Vrais parcours ===

def test_axes_and_polygon_masks_match_the_plate_tool(course, scene):
    for hole in course["routing"]["holes"]:
        assert geo.axis_of(hole) == rp.axis_of(hole)
        polygon = geo.corridor_polygon(hole, geo.CORRIDOR_MARGIN)
        assert polygon == buffered_axis(geo.axis_of(hole), hole["width"] / 2.0 + geo.CORRIDOR_MARGIN)
        assert np.array_equal(geo.polygon_mask(polygon, scene.width, scene.height),
                              rp.polygon_mask(polygon, scene.width, scene.height))


@pytest.mark.parametrize("margin", MARGINS, ids=lambda m: f"m{m:g}")
def test_corridors_are_the_union_of_the_holes(course, scene, margin):
    holes = course["routing"]["holes"]
    expected = np.zeros((scene.height, scene.width), dtype=bool)
    for hole in holes:
        expected |= _corridor(hole, margin, scene.width, scene.height)
    assert np.array_equal(geo.corridors_mask(holes, margin, scene.width, scene.height), expected)


def test_bundle_corridors_are_at_their_margins(course, scene, masks):
    holes = course["routing"]["holes"]
    assert np.array_equal(masks.corridor, geo.corridors_mask(holes, 5.0, scene.width, scene.height))
    assert np.array_equal(masks.core, geo.corridors_mask(holes, 0.0, scene.width, scene.height))
    assert masks.corridor.sum() > masks.core.sum() > 0


def _others(course, scene) -> dict[int, np.ndarray]:
    holes = course["routing"]["holes"]
    own = {hole["id"]: _corridor(hole, 5.0, scene.width, scene.height) for hole in holes}
    return {order: np.logical_or.reduce([mask for other, mask in own.items() if other != order]) for order in own}


def test_other_corridors_leave_out_the_hole_itself(course, scene, masks):
    expected = _others(course, scene)
    assert sorted(masks.others) == sorted(expected) and len(expected) == 18
    for order, mask in expected.items():
        assert np.array_equal(masks.others[order], mask), order


def test_margin_only_moves_the_corridor(course, scene, masks):
    holes = course["routing"]["holes"]
    wider = geo.forbidden_masks(course, scene, margin=12.0)
    assert np.array_equal(wider.corridor, geo.corridors_mask(holes, 12.0, scene.width, scene.height))
    assert not np.array_equal(wider.corridor, masks.corridor)
    assert np.array_equal(wider.core, masks.core)
    assert sorted(wider.others) == sorted(masks.others)
    for order, mask in masks.others.items():
        assert np.array_equal(wider.others[order], mask), order


def test_custom_apron_matches_the_dilation(scene):
    obstacles = geo.kind_mask(scene, "green", "tee")
    assert np.array_equal(geo.aprons_mask(scene, apron=5), _dilate(obstacles, 5))


def test_fixed_and_base_are_the_validated_unions(course, scene, masks):
    paths = np.zeros_like(masks.base)
    for x, z in course["paths"]["cells"]:
        paths[z, x] = True
    base = obstacle_mask(scene) | scene.water | paths
    assert np.array_equal(masks.base, base)
    assert np.array_equal(masks.fixed, base | _dilate(geo.kind_mask(scene, "green", "tee"), geo.APRON))


def test_aprons_are_what_separates_fixed_from_base(course, scene, masks):
    obstacles = np.zeros_like(masks.base)
    for obstacle in scene.obstacles:
        if obstacle.kind in ("green", "tee"):
            cells = obstacle.cells
            keep = ((cells[:, 0] >= 0) & (cells[:, 0] < scene.width)
                    & (cells[:, 1] >= 0) & (cells[:, 1] < scene.height))
            obstacles[cells[keep, 1], cells[keep, 0]] = True
    assert np.array_equal(masks.aprons, _dilate(obstacles, geo.APRON))
    assert (masks.aprons & ~masks.base).any()


def test_parts_of_the_masks_read_the_json(course, scene, masks):
    assert np.array_equal(masks.obstacles, obstacle_mask(scene))
    assert np.array_equal(masks.water, scene.water)
    bunkers = np.zeros_like(masks.base)
    for item in course["bunkers"]["items"]:
        cells = np.asarray(item["cells"], dtype=np.int64).reshape(-1, 2)
        bunkers[cells[:, 1], cells[:, 0]] = True
    assert np.array_equal(masks.bunkers, bunkers) and bunkers.any()
    plaza = np.zeros_like(masks.base)
    if scene.plaza is not None:
        plaza[scene.plaza.cells[:, 1], scene.plaza.cells[:, 0]] = True
    assert np.array_equal(masks.plaza, plaza) and (masks.plaza & ~masks.obstacles).sum() == 0
    paths = np.zeros_like(masks.base)
    for x, z in course["paths"]["cells"]:
        paths[z, x] = True
    assert np.array_equal(masks.paths, paths) and paths.any()


@pytest.mark.parametrize("radius", geo.CROWN_RADII)
def test_crown_fits_and_dilation_on_a_real_course(masks, radius):
    forbidden = masks.fixed | masks.corridor
    assert np.array_equal(geo.dilate_disc(forbidden, radius), _dilate(forbidden, radius))
    padded = _dilate(np.pad(forbidden, radius, constant_values=True), radius)[radius:-radius, radius:-radius]
    assert np.array_equal(geo.crown_fits(forbidden, radius), ~padded)


def test_crown_mask_marks_every_crown_cell(masks, scene):
    legal = np.argwhere(geo.crown_fits(masks.fixed | masks.corridor, 3))[:, ::-1][::37]
    assert len(legal) > 0
    trees = [(int(x), int(y), r) for (x, y), r in zip(legal.tolist(), [2, 3] * len(legal))]
    expected = np.zeros((scene.height, scene.width), dtype=bool)
    for x, y, r in trees:
        for dx, dy in _disc(r):
            expected[y + dy, x + dx] = True
    assert np.array_equal(geo.crown_mask(trees, scene.width, scene.height), expected)
