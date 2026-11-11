"""Format JSON 3.0 (``muirfield_to_dict``, ``terrain_block``, ``relief_f32_block``)."""

from __future__ import annotations

import base64
import copy
import json
from pathlib import Path
import re
import zlib

import numpy as np
import pytest

import golfgen
from golfgen.exporter import muirfield_to_dict, terrain_block
from golfgen.routing import muirfield as mf
from golfgen.routing.sites import WATER_LEVEL, load_terrain
from golfgen.terrain import (RELIEF_F32_ENCODING, ReliefExportError, relief_f32_block,
                             relief_from_f32_block)


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


def _without_dressing_inputs(data):
    """``data`` sans les entrées de l'habillage, exportées en pleine
    précision (clubhouse x/y, trous width/rough_margin/tee/green/doglegs,
    relief float32)."""
    data = copy.deepcopy(data)
    del data["terrain"]["elevation"]["data"], data["terrain"]["elevation_f32"]
    routing = data["routing"]
    del routing["clubhouse"]["x"], routing["clubhouse"]["y"]
    for hole in routing["holes"]:
        for key in ("width", "rough_margin", "tee", "green", "doglegs"):
            del hole[key]
    return data


def test_floats_rounded_to_two_decimals(data):
    """Tout flottant hors entrées de l'habillage est arrondi à 2 décimales."""
    floats = list(_floats(_without_dressing_inputs(data)))
    assert len(floats) > 50
    for value in floats:
        assert value == round(value, 2)


def test_dressing_inputs_full_precision(built, data):
    """Entrées de l'habillage en pleine précision : égales au bit près au
    tracé, y compris après ``json.dumps``/``json.loads`` (ici, plusieurs ne
    tombent pas sur 2 décimales : l'arrondi en perdait)."""
    result, _ = built
    layout = result.layout
    back = json.loads(json.dumps(data))
    for exported in (data, back):
        routing = exported["routing"]
        assert (routing["clubhouse"]["x"], routing["clubhouse"]["y"]) == (
            layout.clubhouse.x, layout.clubhouse.y)
        by_order = {hole.order: hole for hole in layout.holes}
        for hole in routing["holes"]:
            source = by_order[hole["id"]]
            assert (hole["width"], hole["rough_margin"]) == (source.width, source.rough_margin)
            points = [hole["tee"], *hole["doglegs"], hole["green"]]
            assert [(p["x"], p["y"]) for p in points] == [(p.x, p.y) for p in source.axis]
    coords = [p.x for hole in layout.holes for p in hole.axis]
    assert sum(round(x, 2) != x for x in coords) > len(coords) // 2


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
    assert clubhouse == {"x": result.layout.clubhouse.x, "y": result.layout.clubhouse.y,
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
        assert list(hole) == ["id", "nine", "par", "length", "width", "rough_margin", "tee",
                              "green", "doglegs"]
        source = by_order[hole["id"]]
        assert hole["par"] == source.par
        assert hole["length"] == round(source.length, 2)
        assert hole["width"] == source.width
        assert hole["rough_margin"] == source.rough_margin
        assert hole["tee"] == {"x": source.tee.x, "y": source.tee.y}
        assert hole["green"] == {"x": source.green.x, "y": source.green.y}
        assert isinstance(hole["doglegs"], list)
        assert hole["doglegs"] == [{"x": p.x, "y": p.y} for p in source.doglegs]


def test_links(built, data):
    links = data["routing"]["links"]
    assert len(links) == 20
    for link in links:
        # extrémités non exportées : déduites des trous et du clubhouse
        assert list(link) == ["from", "to", "length"]
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
    for exported, source in zip(links, result.layout.links, strict=True):
        assert exported["length"] == round(source.length, 2)


def test_no_waypoints_anywhere(data):
    assert "waypoints" not in set(_keys(data))
    assert "waypoints" not in json.dumps(data)


# ----------------------------------------------------------------------
# Terrain : ``terrain_block`` (bloc 3.0 sans ``water_level``)
# ----------------------------------------------------------------------

def test_terrain_is_terrain_block(built, data):
    _, heightmap = built
    terrain = {k: v for k, v in data["terrain"].items()
               if k not in ("water_level", "elevation_f32")}
    assert terrain == terrain_block(heightmap)
    assert "water_level" not in terrain_block(heightmap)
    raw = base64.b64decode(data["terrain"]["elevation"]["data"])
    assert len(raw) == WIDTH * HEIGHT
    assert (data["terrain"]["width"], data["terrain"]["height"]) == (WIDTH, HEIGHT)


@pytest.mark.parametrize("kind", ["normal", "flat", "float32"])
def test_terrain_block_encoding(kind):
    """uint8 normalisé sur [min, max] (relief plat : zéros), ligne par ligne,
    min/max arrondis à 2 décimales."""
    rng = np.random.default_rng(7)
    heightmap = {
        "normal": lambda: rng.normal(50, 20, (120, 90)),
        "flat": lambda: np.full((10, 12), 3.0),
        "float32": lambda: rng.uniform(-5, 300, (64, 64)).astype(np.float32),
    }[kind]()
    h, w = heightmap.shape
    lo, hi = float(heightmap.min()), float(heightmap.max())
    if kind == "flat":
        expected = np.zeros((h, w), dtype=np.uint8)
    else:
        expected = ((heightmap - lo) / (hi - lo) * 255).astype(np.uint8)
    block = terrain_block(heightmap)
    assert (block["width"], block["height"]) == (w, h)
    elevation = block["elevation"]
    assert elevation["encoding"] == "base64_uint8"
    assert (elevation["min_elevation"], elevation["max_elevation"]) == (round(lo, 2), round(hi, 2))
    decoded = np.frombuffer(base64.b64decode(elevation["data"]), dtype=np.uint8)
    np.testing.assert_array_equal(decoded.reshape(h, w), expected)


def test_terrain_water_level(data):
    """Niveau d'eau du routeur (``sites.WATER_LEVEL``), en unités d'altitude :
    sous ce niveau le routeur et les planches PNG voient de l'eau."""
    water = data["terrain"]["water_level"]
    assert isinstance(water, float)
    assert water == WATER_LEVEL
    assert list(data["terrain"]) == ["width", "height", "elevation", "water_level",
                                     "elevation_f32"]


# ----------------------------------------------------------------------
# Relief sans perte : ``relief_f32_block`` (``terrain.elevation_f32``)
# ----------------------------------------------------------------------

def test_relief_f32_exported_without_loss(built, data):
    _, heightmap = built
    assert heightmap.dtype == np.float32
    block = json.loads(json.dumps(data))["terrain"]["elevation_f32"]
    assert block == relief_f32_block(heightmap)
    assert list(block) == ["encoding", "data"]
    assert block["encoding"] == RELIEF_F32_ENCODING == "zlib_base64_float32le_byteshuffle"
    # plans d'octets : les octets 0 de toutes les valeurs, puis les 1, 2 et 3
    raw = zlib.decompress(base64.b64decode(block["data"]))
    planes = np.frombuffer(raw, dtype=np.uint8).reshape(4, HEIGHT * WIDTH)
    natural = np.frombuffer(heightmap.astype("<f4").tobytes(), dtype=np.uint8)
    for k in range(4):
        np.testing.assert_array_equal(planes[k], natural[k::4])
    unshuffled = np.ascontiguousarray(planes.T).view("<f4").reshape(HEIGHT, WIDTH)
    np.testing.assert_array_equal(unshuffled, heightmap)
    relief = relief_from_f32_block(block, WIDTH, HEIGHT)
    assert relief.dtype == np.float32 and relief.shape == (HEIGHT, WIDTH)
    assert relief.tobytes() == heightmap.tobytes()          # au bit près
    assert relief.flags.writeable


@pytest.mark.parametrize("kind", ["float64_exact", "big_endian", "negative_zero",
                                  "extremes", "non_contiguous"])
def test_relief_f32_roundtrip(kind):
    rng = np.random.default_rng(3)
    relief = rng.uniform(-5, 300, (7, 9)).astype(np.float32)
    f32 = np.finfo(np.float32)
    extremes = relief.copy()
    extremes.flat[:6] = [np.inf, -np.inf, f32.max, f32.smallest_subnormal, -f32.tiny, -0.0]
    source = {"float64_exact": relief.astype(np.float64), "big_endian": relief.astype(">f4"),
              "negative_zero": np.where(relief > 100, np.float32(-0.0), relief),
              "extremes": extremes,
              "non_contiguous": np.asfortranarray(relief)}[kind]
    back = relief_from_f32_block(relief_f32_block(source), 9, 7)
    assert back.astype("<f4").tobytes() == source.astype("<f4").tobytes()
    assert back.flags.c_contiguous and back.flags.writeable


def test_relief_f32_unshuffled_stream_misread():
    # un flux float32 en ordre naturel (sans byte shuffle) n'est pas relu à
    # l'identique : le codage du bloc n'est pas interchangeable
    relief = np.random.default_rng(5).uniform(50, 90, (3, 4)).astype(np.float32)
    natural = _f32_block(zlib.compress(relief.astype("<f4").tobytes()))
    assert relief_from_f32_block(natural, 4, 3).tobytes() != relief.tobytes()


@pytest.mark.parametrize("relief", [np.full((3, 4), 0.1),            # float64 hors grille f32
                                    np.full((3, 4), np.nan, dtype=np.float32)])
def test_relief_f32_refuses_lossy(relief):
    with pytest.raises(ReliefExportError, match="float32") as info:
        relief_f32_block(relief)
    assert isinstance(info.value, ValueError)


def test_relief_f32_decode_errors():
    block = relief_f32_block(np.zeros((3, 4), dtype=np.float32))
    for encoding in ("base64_uint8", "zlib_base64_float32le"):   # dont l'ordre naturel
        with pytest.raises(ValueError, match="encodage"):
            relief_from_f32_block({**block, "encoding": encoding}, 4, 3)
    with pytest.raises(ValueError, match="octets"):
        relief_from_f32_block(block, 5, 3)


def _f32_block(raw: bytes) -> dict:
    return {"encoding": RELIEF_F32_ENCODING, "data": base64.b64encode(raw).decode("ascii")}


def test_relief_f32_decode_not_an_object():
    with pytest.raises(ValueError, match="objet attendu"):
        relief_from_f32_block(["zlib_base64_float32le", "eJw="], 4, 3)


def test_relief_f32_decode_bounded():
    # flux qui se décompresserait en 40 Mo : refusé sans tout décompresser
    bomb = _f32_block(zlib.compress(bytes(40_000_000), 9))
    with pytest.raises(ValueError, match="plus de 48 octets"):
        relief_from_f32_block(bomb, 4, 3)
    # un seul octet de trop suffit
    with pytest.raises(ValueError, match="plus de 48 octets"):
        relief_from_f32_block(_f32_block(zlib.compress(bytes(49))), 4, 3)


@pytest.mark.parametrize("tamper", ["trailing", "truncated"])
def test_relief_f32_decode_refuses_extra_or_missing_stream(tamper):
    stream = zlib.compress(np.zeros((3, 4), dtype="<f4").tobytes())
    # données après la fin du flux zlib, ou flux coupé avant sa somme de contrôle
    raw = stream + b"suite" if tamper == "trailing" else stream[:-4]
    with pytest.raises(ValueError, match="flux zlib incomplet ou suivi de données"):
        relief_from_f32_block(_f32_block(raw), 4, 3)


# ----------------------------------------------------------------------
# Extension 3.2 : bunkers (``with_bunkers``, clé de premier niveau)
# ----------------------------------------------------------------------

def _course_bunkers(cells_1=((10, 20), (11, 20), (10, 21))):
    from golfgen.dressing.bunkers import CourseBunkers, PlacedBunker
    from golfgen.dressing.bunkers.course import BUILT, IN_PLACE, UnplacedBunker, STAGE_FAIRWAY
    placed = (PlacedBunker("g1", 1, "pot", "green", np.array(cells_1), BUILT),
              PlacedBunker("l1", 3, "haricot", "landing", np.array([(5, 6), (6, 6)]), IN_PLACE))
    unplaced = (UnplacedBunker(4, "haricot", "landing", STAGE_FAIRWAY, ("18b",), ids=("l1",)),)
    return CourseBunkers(SEED, (5,), placed, unplaced)


@pytest.fixture(scope="module")
def dressed(data):
    from golfgen.dressing import dress_course_json
    from golfgen.exporter import with_dressing
    dressing = dress_course_json(data, "links")
    return with_dressing(data, dressing), dressing


def test_with_bunkers_roundtrip(data, dressed):
    from golfgen.dressing import course_input_from_json, dress_course_json
    from golfgen.exporter import with_bunkers, with_dressing
    plain, dressing = dressed
    before = copy.deepcopy(plain)
    out = with_bunkers(plain, _course_bunkers())
    assert plain == before                                   # entrée intacte
    assert out["metadata"]["version"] == "3.2"
    assert list(out) == ["metadata", "terrain", "routing", "bunkers"]
    assert {k: v for k, v in out.items() if k != "bunkers"} == {
        **plain, "metadata": {**plain["metadata"], "version": "3.2"}}
    assert out["bunkers"] == {
        "empty_rule": "per_hole", "empty_holes": [5],
        "items": [{"id": "g1", "hole": 1, "family": "pot", "role": "green", "status": "construction",
                   "cells": [[10, 20], [11, 20], [10, 21]]},
                  {"id": "l1", "hole": 3, "family": "haricot", "role": "landing", "status": "pose_en_place",
                   "cells": [[5, 6], [6, 6]]}]}                # non posés absents
    assert json.loads(json.dumps(out)) == out
    # lecteurs 3.x : le 3.2 se relit et se ré-habille ; ré-habiller retire
    # la clé bunkers (périmée) et revient au 3.1
    course_input_from_json(out)
    assert with_dressing(out, dress_course_json(out, "links")) == plain
    assert with_bunkers(out, _course_bunkers()) == out


@pytest.mark.parametrize("cells", [((-1, 0),), ((WIDTH, 0),), ((0, HEIGHT),)])
def test_with_bunkers_refuses_cells_off_map(dressed, cells):
    from golfgen.exporter import with_bunkers
    with pytest.raises(ValueError, match="hors de la carte"):
        with_bunkers(dressed[0], _course_bunkers(cells))


def test_with_bunkers_needs_dressing_and_course_bunkers(data, dressed):
    from golfgen.exporter import with_bunkers
    with pytest.raises(ValueError, match="habillage"):
        with_bunkers(data, _course_bunkers())
    with pytest.raises(TypeError):
        with_bunkers(dressed[0], {"items": []})
    unknown = copy.deepcopy(dressed[0])
    unknown["routing"]["holes"] = [h for h in unknown["routing"]["holes"] if h["id"] != 3]
    with pytest.raises(ValueError, match="trou 3 absent"):
        with_bunkers(unknown, _course_bunkers())


# ----------------------------------------------------------------------
# Extension 3.3 : chemins (``with_paths``, clé de premier niveau)
# ----------------------------------------------------------------------

def _course_paths(cells=((10, 20), (10, 21), (11, 21)), plaza=True):
    from golfgen.dressing.paths import CoursePaths, PlazaLayer
    layer = PlazaLayer(np.array([(2, 3), (2, 4), (3, 3), (3, 4)], dtype=np.int64), 2, (1, 0)) \
        if plaza else None
    return CoursePaths(width=2.0, cells=np.array(cells, dtype=np.int64),
                       bridge_cells=np.array([(10, 21)], dtype=np.int64), plaza=layer,
                       anchors=np.array([(12, 20)], dtype=np.int64))


def test_with_paths_roundtrip(dressed):
    from golfgen.dressing import dress_course_json
    from golfgen.exporter import PATHS_FORMAT_VERSION, with_bunkers, with_dressing, with_paths
    plain, _ = dressed
    v32 = with_bunkers(plain, _course_bunkers())
    before = copy.deepcopy(v32)
    out = with_paths(v32, _course_paths())
    assert v32 == before                                     # entrée intacte
    assert out["metadata"]["version"] == PATHS_FORMAT_VERSION == "3.3"
    assert list(out) == ["metadata", "terrain", "routing", "bunkers", "paths"]
    assert {k: v for k, v in out.items() if k != "paths"} == {
        **v32, "metadata": {**v32["metadata"], "version": "3.3"}}
    assert out["paths"] == {
        "width": 2.0, "cells": [[10, 20], [10, 21], [11, 21]], "bridge_cells": [[10, 21]],
        "plaza": {"cells": [[2, 3], [2, 4], [3, 3], [3, 4]], "size": 2,
                  "offset": {"along": 1, "inward": 0}},
        "anchors": [[12, 20]]}
    assert all(type(v) is int for c in out["paths"]["cells"] for v in c)
    assert json.loads(json.dumps(out)) == out
    assert with_paths(v32, _course_paths(plaza=False))["paths"]["plaza"] is None
    # ré-appliquer remplace la clé ; ré-habiller ou reposer les bunkers la
    # retire (chemins périmés) : retour au 3.1 et au 3.2
    assert with_paths(out, _course_paths()) == out
    assert with_bunkers(out, _course_bunkers()) == v32
    assert with_dressing(out, dress_course_json(out, "links")) == plain


@pytest.mark.parametrize("cells", [((-1, 0),), ((WIDTH, 0),), ((0, HEIGHT),)])
def test_with_paths_refuses_cells_off_map(dressed, cells):
    from golfgen.exporter import with_bunkers, with_paths
    with pytest.raises(ValueError, match="hors de la carte"):
        with_paths(with_bunkers(dressed[0], _course_bunkers()), _course_paths(cells))


def test_with_paths_needs_bunkers_course_paths_and_detail(dressed):
    from golfgen.exporter import with_bunkers, with_paths
    with pytest.raises(ValueError, match="sans bunkers"):
        with_paths(dressed[0], _course_paths())               # 3.1 : pas de chemins
    v32 = with_bunkers(dressed[0], _course_bunkers())
    with pytest.raises(TypeError):
        with_paths(v32, {"cells": []})
    with pytest.raises(ValueError, match="sans détail"):
        with_paths(v32, _course_paths(), debug=True)
