"""Format JSON 3.0 (``muirfield_to_dict``) et non-régression du format 2.0."""

from __future__ import annotations

import base64
import copy
import json
from pathlib import Path
import re

import numpy as np
import pytest

import golfgen
from golfgen.config import CourseConfig
from golfgen.exporter import JSONExporter, muirfield_to_dict, terrain_block
from golfgen.routing import muirfield as mf
from golfgen.routing.sites import load_terrain


# seed 4 en 400×300 : « random » résolu en muirfield_inverse, sans relance,
# Plan.direction = +1 (sens horaire)
SEED, WIDTH, HEIGHT = 4, 400, 300
# seed 42 en 400×300, patron muirfield : Plan.direction = −1 (sens antihoraire),
# pour couvrir les deux branches de ``direction``
SEED_CCW = 42


@pytest.fixture(scope="module")
def built():
    heightmap = load_terrain(SEED, WIDTH, HEIGHT)
    result = mf.build_course(SEED, "random", heightmap, width=WIDTH, height=HEIGHT)
    return result, heightmap


@pytest.fixture(scope="module")
def data(built):
    result, heightmap = built
    return muirfield_to_dict(result, heightmap, seed=SEED, seed_input="4")


@pytest.fixture(scope="module")
def built_ccw():
    heightmap = load_terrain(SEED_CCW, WIDTH, HEIGHT)
    result = mf.build_course(SEED_CCW, "muirfield", heightmap, width=WIDTH, height=HEIGHT)
    return result, heightmap


@pytest.fixture(scope="module", params=["inverse_cw", "muirfield_ccw"])
def case(request, built, data, built_ccw):
    """Les deux branches de ``direction`` : (résultat, dict, patron, sens attendu)."""
    if request.param == "inverse_cw":
        return built[0], data, "muirfield_inverse", "clockwise"
    result, heightmap = built_ccw
    return (result, muirfield_to_dict(result, heightmap, seed=SEED_CCW), "muirfield",
            "counterclockwise")


def _keys(node):
    if isinstance(node, dict):
        for key, value in node.items():
            yield key
            yield from _keys(value)
    elif isinstance(node, list):
        for item in node:
            yield from _keys(item)


def _floats(node):
    if isinstance(node, dict):
        for value in node.values():
            yield from _floats(value)
    elif isinstance(node, list):
        for item in node:
            yield from _floats(item)
    elif isinstance(node, float):
        yield node


# ----------------------------------------------------------------------
# Structure 3.0
# ----------------------------------------------------------------------

def test_top_level_structure(data):
    assert list(data) == ["metadata", "terrain", "routing"]
    meta = data["metadata"]
    assert set(meta) == {"version", "generator", "seed", "seed_input", "pattern",
                         "orientation", "short_side", "long_side", "width", "height",
                         "block_m", "stats"}
    assert meta["version"] == "3.0"
    assert meta["generator"] == f"golfgen {golfgen.__version__}"
    assert meta["block_m"] == 3
    assert (meta["width"], meta["height"]) == (400.0, 300.0)
    assert meta["orientation"] == "landscape"
    assert (meta["short_side"], meta["long_side"]) == (300.0, 400.0)
    assert set(data["routing"]) == {"clubhouse", "direction", "holes", "links"}


def test_json_serialisable_without_custom_encoder(data):
    text = json.dumps(data)
    assert json.loads(text) == data


def test_floats_rounded_to_two_decimals(data):
    data = copy.deepcopy(data)
    del data["terrain"]["elevation"]["data"]
    for value in _floats(data):
        assert value == round(value, 2)


def test_deterministic(built, data):
    result, heightmap = built
    again = muirfield_to_dict(result, heightmap, seed=SEED, seed_input="4")
    assert again == data
    assert json.dumps(again) == json.dumps(data)


def test_version_matches_setup_py():
    setup = (Path(__file__).resolve().parents[1] / "setup.py").read_text(encoding="utf-8")
    assert re.search(r'version="([^"]+)"', setup).group(1) == golfgen.__version__


# ----------------------------------------------------------------------
# Seed
# ----------------------------------------------------------------------

@pytest.mark.parametrize("seed", [0, -1, -2**63, 2**63 - 1])
def test_seed_exported_as_exact_string(built, seed):
    result, heightmap = built
    data = muirfield_to_dict(result, heightmap, seed=seed)
    assert data["metadata"]["seed"] == str(seed)
    assert int(json.loads(json.dumps(data))["metadata"]["seed"]) == seed


def test_seed_input_present_and_null(built):
    result, heightmap = built
    with_input = muirfield_to_dict(result, heightmap, seed=-7, seed_input="  -007 ")
    assert with_input["metadata"]["seed_input"] == "  -007 "
    without = muirfield_to_dict(result, heightmap, seed=-7)
    assert without["metadata"]["seed_input"] is None
    assert '"seed_input": null' in json.dumps(without)


@pytest.mark.parametrize("seed", [True, 1.0, "4"])
def test_seed_must_be_int(built, seed):
    result, heightmap = built
    with pytest.raises(TypeError):
        muirfield_to_dict(result, heightmap, seed=seed)


def test_heightmap_shape_must_match(built):
    result, heightmap = built
    with pytest.raises(ValueError):
        muirfield_to_dict(result, heightmap.T, seed=SEED)


# ----------------------------------------------------------------------
# Patron, stats, routing
# ----------------------------------------------------------------------

def test_pattern_requested_vs_resolved(built, data):
    result, _ = built
    assert data["metadata"]["pattern"] == {"requested": "random",
                                           "resolved": mf.resolve_pattern(SEED, "random")}
    assert data["metadata"]["pattern"]["resolved"] == result.pattern == "muirfield_inverse"


def test_stats(built, data):
    result, _ = built
    stats = data["metadata"]["stats"]
    legacy = result.nine_lengths()
    for nine in ("front", "back"):
        assert set(stats[nine]) == {"holes_length", "links_length", "total", "par"}
        assert stats[nine]["par"] == legacy[nine]["par"]
        assert stats[nine]["holes_length"] == pytest.approx(legacy[nine]["holes"], abs=0.06)
        assert stats[nine]["links_length"] == pytest.approx(legacy[nine]["links"], abs=0.06)
        assert stats[nine]["total"] == pytest.approx(legacy[nine]["total"], abs=0.06)
    assert stats["par"] == stats["front"]["par"] + stats["back"]["par"] == 72
    assert stats["total"] == pytest.approx(stats["front"]["total"] + stats["back"]["total"],
                                           abs=0.011)
    hole_sum = sum(hole["length"] for hole in data["routing"]["holes"])
    assert stats["front"]["holes_length"] + stats["back"]["holes_length"] == pytest.approx(
        hole_sum, abs=0.1)
    assert stats["elapsed_seconds"] == round(result.elapsed_seconds, 2)
    assert stats["relaunches"] == result.relaunches


def test_clubhouse(built, data):
    result, _ = built
    clubhouse = data["routing"]["clubhouse"]
    assert clubhouse == {"x": round(result.layout.clubhouse.x, 2),
                         "y": round(result.layout.clubhouse.y, 2),
                         "edge": result.clubhouse_edge}
    assert clubhouse["edge"] in ("N", "E", "S", "W")


def _signed_area(points):
    return sum(a[0] * b[1] - b[0] * a[1] for a, b in zip(points, points[1:] + points[:1])) / 2


def test_direction_matches_geometry(case):
    result, data, pattern, outer_turn = case
    assert result.pattern == data["metadata"]["pattern"]["resolved"] == pattern
    direction = data["routing"]["direction"]
    outer = "front" if pattern == "muirfield" else "back"
    assert direction["outer_nine"] == outer
    assert direction["inner_nine"] == ("back" if outer == "front" else "front")
    assert direction["outer_turn"] == outer_turn
    assert {direction["outer_turn"], direction["inner_turn"]} == {"clockwise",
                                                                   "counterclockwise"}
    # Repère y vers le bas : aire signée positive = sens horaire à l'écran.
    clubhouse = data["routing"]["clubhouse"]
    for nine in ("front", "back"):
        points = [(clubhouse["x"], clubhouse["y"])]
        for hole in (h for h in data["routing"]["holes"] if h["nine"] == nine):
            points += [(hole["tee"]["x"], hole["tee"]["y"]),
                       (hole["green"]["x"], hole["green"]["y"])]
        turn = "clockwise" if _signed_area(points) > 0 else "counterclockwise"
        key = "outer_turn" if direction["outer_nine"] == nine else "inner_turn"
        assert direction[key] == turn
    assert direction["outer_turn"] == {1: "clockwise", -1: "counterclockwise"}[result.direction]


def test_holes(built, data):
    result, _ = built
    holes = data["routing"]["holes"]
    assert [hole["id"] for hole in holes] == list(range(1, 19))
    assert [hole["nine"] for hole in holes] == ["front"] * 9 + ["back"] * 9
    by_order = {hole.order: hole for hole in result.layout.holes}
    for hole in holes:
        assert set(hole) == {"id", "nine", "par", "length", "width", "tee", "green", "doglegs"}
        source = by_order[hole["id"]]
        assert hole["par"] == source.par
        assert hole["length"] == round(source.length, 2)
        assert hole["width"] == round(source.width, 2)
        assert hole["tee"] == {"x": round(source.tee.x, 2), "y": round(source.tee.y, 2)}
        assert hole["green"] == {"x": round(source.green.x, 2), "y": round(source.green.y, 2)}
        assert isinstance(hole["doglegs"], list)
        assert len(hole["doglegs"]) == len(source.doglegs)
        for point in hole["doglegs"]:
            assert set(point) == {"x", "y"}


def test_links(built, data):
    links = data["routing"]["links"]
    assert len(links) == 20
    for link in links:
        assert set(link) == {"from", "to", "length"}
        assert link["length"] > 0
    ends = [(link["from"], link["to"]) for link in links]
    assert ends[0] == ("clubhouse", 1)
    assert ends[9] == (9, "clubhouse")
    assert ends[10] == ("clubhouse", 10)
    assert ends[19] == (18, "clubhouse")
    assert sum("clubhouse" in end for end in ends) == 4
    inner = [end for end in ends if "clubhouse" not in end]
    assert inner == [(i, i + 1) for i in range(1, 18) if i != 9]
    result, _ = built
    for exported, source in zip(links, result.layout.links):
        assert exported["length"] == round(source.length, 2)


def test_no_waypoints_anywhere(data):
    assert "waypoints" not in set(_keys(data))
    assert "waypoints" not in json.dumps(data)


# ----------------------------------------------------------------------
# Terrain : bloc commun 2.0 / 3.0
# ----------------------------------------------------------------------

def test_terrain_identical_to_v2_helper(built, data):
    _, heightmap = built
    assert data["terrain"] == terrain_block(heightmap)
    exporter = JSONExporter(CourseConfig(seed=SEED, width=WIDTH, height=HEIGHT))
    exporter.add_terrain(heightmap)
    assert exporter.data["terrain"] == data["terrain"]
    raw = base64.b64decode(data["terrain"]["elevation"]["data"])
    assert len(raw) == WIDTH * HEIGHT
    assert (data["terrain"]["width"], data["terrain"]["height"]) == (WIDTH, HEIGHT)


# ----------------------------------------------------------------------
# Non-régression 2.0 : copie de l'implémentation d'avant la factorisation
# ----------------------------------------------------------------------

def _legacy_terrain(heightmap: np.ndarray) -> dict:
    h, w = heightmap.shape
    elev_min = float(heightmap.min())
    elev_max = float(heightmap.max())
    if elev_max - elev_min < 1e-10:
        uint8_data = np.zeros((h, w), dtype=np.uint8)
    else:
        normalized = (heightmap - elev_min) / (elev_max - elev_min)
        uint8_data = (normalized * 255).astype(np.uint8)
    encoded = base64.b64encode(uint8_data.tobytes()).decode('ascii')
    return {
        "width": w,
        "height": h,
        "elevation": {
            "encoding": "base64_uint8",
            "data": encoded,
            "min_elevation": round(elev_min, 2),
            "max_elevation": round(elev_max, 2),
        }
    }


def _legacy_export(config: CourseConfig, heightmap: np.ndarray) -> str:
    data = {
        "metadata": {
            "version": "2.0",
            "seed": config.seed,
            "config": {
                "width": config.width,
                "height": config.height,
                "scale_ratio": config.scale_ratio,
                "base_elevation": config.terrain.base_elevation,
            },
            "pipeline_stages": ["terrain", "routing"],
        },
        "terrain": _legacy_terrain(heightmap),
        "routing": {"holes": [{"tee": {"x": 1.0, "y": 2.0}}],
                    "clubhouse": {"x": 3.1, "y": 2.7}},
    }
    return json.dumps(data, indent=2, ensure_ascii=False)


@pytest.mark.parametrize("kind", ["normal", "flat", "float32"])
def test_v2_export_unchanged(tmp_path, kind):
    rng = np.random.default_rng(7)
    heightmap = {
        "normal": lambda: rng.normal(50, 20, (120, 90)),
        "flat": lambda: np.full((10, 12), 3.0),
        "float32": lambda: rng.uniform(-5, 300, (64, 64)).astype(np.float32),
    }[kind]()
    config = CourseConfig(seed=42)
    exporter = JSONExporter(config)
    exporter.add_terrain(heightmap)
    exporter.add_routing([{"tee": {"x": 1.0, "y": 2.0}}], clubhouse_pos=(3.14159, 2.71828))
    path = tmp_path / "course.json"
    exporter.export(path)
    assert path.read_text(encoding="utf-8") == _legacy_export(config, heightmap)
