"""Habillage depuis le seul JSON du routage (``golfgen.dressing.from_json``) :
équivalence au bit près avec l'habillage en mémoire, masque sec reconstruit,
refus des JSON non habillables (exports antérieurs arrondis, incohérences)."""

from __future__ import annotations

import copy
import json

import numpy as np
import pytest

from golfgen.dressing import (STYLE_SPECS, CourseInput, CourseJsonError, DressingError,
                              course_input_from_json, dress_course, dress_course_json)
from golfgen.exporter import muirfield_to_dict, with_dressing
from golfgen.routing import muirfield as mf
from golfgen.routing.sites import dry_mask, load_terrain
from golfgen.seed import seed_u64

# Même échantillon que ``tests/test_dressing.py`` (9 parcours réels, patron
# random : muirfield et muirfield_inverse) ; (400, 300, 1) porte le seul green
# double du corpus (trous 10/17, links). Plus une seed négative, pour la
# conversion ``metadata.seed`` (signée) → seed u64 de l'habillage, et
# (400, 300, 7) : green du trou 5 sur l'eau (décalé en links, insulaire en
# parkland, lot 1 eau).
CASES = ([(400, 300, seed) for seed in range(1, 7)] + [(300, 400, seed) for seed in range(1, 4)]
         + [(400, 300, -3), (400, 300, 7)])
WET_GREEN_CASE = (400, 300, 7, 5)
PAIR_CASE = (400, 300, 1)


@pytest.fixture(scope="module")
def courses():
    out = {}
    for width, height, seed in CASES:
        heightmap = load_terrain(seed_u64(seed), width, height)
        result = mf.build_course(seed_u64(seed), "random", heightmap, width=width, height=height)
        # JSON relu depuis le texte, comme le lirait le « bouton 2 »
        data = json.loads(json.dumps(muirfield_to_dict(result, heightmap, seed=seed)))
        out[(width, height, seed)] = (heightmap, result, data)
    return out


@pytest.fixture
def data4(courses):
    return copy.deepcopy(courses[(400, 300, 4)][2])


# ----------------------------------------------------------------------
# Équivalence au bit près
# ----------------------------------------------------------------------

@pytest.mark.parametrize("style", sorted(STYLE_SPECS))
def test_same_dressing_as_in_memory(courses, style):
    pairs = 0
    for case, (heightmap, result, data) in courses.items():
        expected = dress_course(result, seed=seed_u64(case[2]), style=style, relief=heightmap)
        got = dress_course_json(data, style)
        # égalité des dataclasses : chaque flottant de chaque contour, centre,
        # aire, paire et rejet de paire, au bit près
        assert got == expected, case
        assert got.pair_rejections == expected.pair_rejections
        pairs += len(got.green_pairs)
        # et le JSON 3.1 qui en sort, texte compris
        direct = muirfield_to_dict(result, heightmap, seed=case[2], dressing=expected)
        assert json.dumps(with_dressing(data, got)) == json.dumps(direct)
    fix = dress_course_json(courses[WET_GREEN_CASE[:3]][2], style)[WET_GREEN_CASE[3]].water_fix
    assert fix.green_shift is not None if style == "links" else fix.green_island
    if style == "links":
        assert pairs >= 1
        assert [(p.i, p.j) for p in dress_course_json(courses[PAIR_CASE][2],
                                                       "links").green_pairs] == [(10, 17)]


def test_layout_relief_and_dry_mask_rebuilt(courses):
    wet = 0
    for case, (heightmap, result, data) in courses.items():
        course = course_input_from_json(data)
        assert isinstance(course, CourseInput)
        assert course.seed == seed_u64(case[2]) == result.layout.seed
        assert course.layout == result.layout                  # tous les flottants
        assert course.relief.dtype == np.float32
        assert course.relief.tobytes() == heightmap.tobytes()
        # même fonction que le routeur (``build_course`` : ``dry_mask(heightmap)``)
        np.testing.assert_array_equal(course.dry.dry, dry_mask(heightmap).dry)
        course.dry.require_size(result.width, result.height)
        wet += int((~course.dry.dry).sum())
    assert wet > 0                    # l'échantillon contient de l'eau


def test_redress_dressed_json(courses):
    """Un 3.1 se ré-habille (bouton 2 relancé, autre style) : seules ses
    entrées comptent, l'habillage déjà présent est ignoré puis remplacé."""
    _, result, data = courses[PAIR_CASE]
    links = with_dressing(data, dress_course_json(data, "links"))
    assert links["routing"]["green_pairs"]
    assert with_dressing(links, dress_course_json(links, "links")) == links
    parkland = with_dressing(links, dress_course_json(links, "parkland"))
    assert parkland == with_dressing(data, dress_course_json(data, "parkland"))
    assert parkland["metadata"]["style"] == "parkland"
    assert list(parkland["metadata"]).index("style") == list(parkland["metadata"]).index(
        "pattern") + 1


def test_with_dressing_keeps_input(data4):
    before = json.dumps(data4)
    dressed = with_dressing(data4, dress_course_json(data4, "links"))
    assert json.dumps(data4) == before
    assert dressed["metadata"]["version"] == "3.1"
    assert list(dressed["routing"]) == ["clubhouse", "direction", "holes", "green_pairs",
                                        "links"]


# ----------------------------------------------------------------------
# Refus
# ----------------------------------------------------------------------

def _legacy(data):
    """Le même parcours tel qu'exporté avant le lot 2 R0 (3.0/3.1 arrondi)."""
    data = copy.deepcopy(data)
    del data["terrain"]["elevation_f32"]
    for hole in data["routing"]["holes"]:
        del hole["rough_margin"]
        for point in (hole["tee"], hole["green"], *hole["doglegs"]):
            point.update(x=round(point["x"], 2), y=round(point["y"], 2))
    return data


@pytest.mark.parametrize("version", ["3.0", "3.1"])
def test_legacy_json_refused(data4, version):
    legacy = _legacy(data4)
    legacy["metadata"]["version"] = version
    with pytest.raises(CourseJsonError, match=f"JSON {version} sans les entrées de "
                                              "l'habillage") as info:
        dress_course_json(legacy, "links")
    message = str(info.value)
    for field in ("terrain.elevation_f32", "routing.holes[].rough_margin"):
        assert field in message
    assert "routing.links[]" not in message
    assert isinstance(info.value, ValueError) and not isinstance(info.value, DressingError)


def test_single_missing_field_refused(data4):
    del data4["routing"]["holes"][5]["rough_margin"]
    with pytest.raises(CourseJsonError, match=r"\(routing\.holes\[\]\.rough_margin\)"):
        dress_course_json(data4, "links")


@pytest.mark.parametrize("version", [None, "2.0", "4.0", 3.1])
def test_version_refused(data4, version):
    data4["metadata"]["version"] = version
    with pytest.raises(CourseJsonError, match="version"):
        course_input_from_json(data4)


def test_not_an_object_refused():
    with pytest.raises(CourseJsonError, match="objet"):
        course_input_from_json([])


def test_links_rebuilt_from_holes(data4):
    """Liaisons sans extrémités dans le JSON : déduites des trous et du
    clubhouse. Un tee déplacé sous la tolérance des longueurs emporte ses
    liaisons ; déplacé au-delà, il contredit les ``length`` exportées
    (que ``with_dressing`` recopierait, périmées) : refusé."""
    assert all(list(link) == ["from", "to", "length"] for link in data4["routing"]["links"])
    moved = copy.deepcopy(data4)
    moved["routing"]["holes"][3]["tee"]["x"] += 1e-9
    layout = course_input_from_json(moved).layout
    tee = layout.holes[3].tee
    assert tee.x == moved["routing"]["holes"][3]["tee"]["x"]
    assert layout.links[3].end == tee
    assert layout.links[0].start == layout.links[9].end == layout.clubhouse
    assert layout.links[10].start == layout.links[19].end == layout.clubhouse
    hole_id = data4["routing"]["holes"][3]["id"]
    data4["routing"]["holes"][3]["tee"]["x"] += 5.0
    with pytest.raises(CourseJsonError, match=f"incohérent : trou {hole_id}, longueur "
                                              "exportée"):
        course_input_from_json(data4)


@pytest.mark.parametrize("section, index", [("holes", 6), ("links", 13)])
def test_stale_length_refused(data4, section, index):
    data4["routing"][section][index]["length"] += 0.02
    where = (f"trou {data4['routing']['holes'][index]['id']}" if section == "holes"
             else f"liaison {index} ")
    with pytest.raises(CourseJsonError, match=f"incohérent : {where}"):
        course_input_from_json(data4)


@pytest.mark.parametrize("section", ["holes", "links"])
@pytest.mark.parametrize("value", [None, "1.5", True, float("nan")])
def test_bad_length_refused(data4, section, value):
    data4["routing"][section][2]["length"] = value
    with pytest.raises(CourseJsonError, match="longueur exportée"):
        course_input_from_json(data4)


def test_length_within_tolerance_accepted(data4):
    data4["routing"]["holes"][0]["length"] += 0.004
    data4["routing"]["links"][0]["length"] -= 0.004
    course_input_from_json(data4)


@pytest.mark.parametrize("section", ["holes", "links"])
@pytest.mark.parametrize("value", [None, "trou", 4, ["id"]])
def test_item_not_an_object_refused(data4, section, value):
    data4["routing"][section][7] = value
    with pytest.raises(CourseJsonError, match=rf"routing\.{section}\[7\] doit être un objet"):
        course_input_from_json(data4)


@pytest.mark.parametrize("section", ["holes", "links"])
@pytest.mark.parametrize("value", [None, {}, "trous", 18])
def test_section_not_a_list_refused(data4, section, value):
    data4["routing"][section] = value
    with pytest.raises(CourseJsonError, match=rf"routing\.{section} doit être une liste") as info:
        course_input_from_json(data4)
    assert "export antérieur" not in str(info.value)


@pytest.mark.parametrize("index, field, value", [
    (3, "to", 5),                        # 3 → 5 au lieu de 3 → 4
    (0, "from", 1),                      # départ du trou 1 au lieu du clubhouse
    (9, "to", 10),                       # 9 → 10 au lieu de 9 → clubhouse
    (12, "from", "clubhouse"),
])
def test_link_order_mismatch_refused(data4, index, field, value):
    data4["routing"]["links"][index][field] = value
    with pytest.raises(CourseJsonError, match=f"incohérent : liaison {index} "):
        course_input_from_json(data4)


def test_links_swapped_refused(data4):
    links = data4["routing"]["links"]
    links[1], links[2] = links[2], links[1]
    with pytest.raises(CourseJsonError, match="liaison 1 2 → 3, attendue 1 → 2"):
        course_input_from_json(data4)


def test_inconsistent_layout_refused(data4):
    # trou passé dans l'autre nine : contrôles de ``NineLayout``
    data4["routing"]["holes"][3]["nine"] = "back"
    with pytest.raises(CourseJsonError, match="incohérent"):
        course_input_from_json(data4)


def test_missing_hole_refused(data4):
    data4["routing"]["holes"].pop()
    with pytest.raises(CourseJsonError, match="incohérent"):
        course_input_from_json(data4)


@pytest.mark.parametrize("mode", ["append", "replace"])
def test_duplicate_hole_id_refused(data4, mode):
    # un id en double écrasait l'entrée précédente dans le dict des trous :
    # 19 entrées dont un doublon passaient le contrôle des 18 trous
    holes = data4["routing"]["holes"]
    twin = copy.deepcopy(holes[4])
    if mode == "append":
        holes.append(twin)
    else:
        holes[5] = twin
    with pytest.raises(CourseJsonError, match=f"incohérent : trou {twin['id']} en double"):
        course_input_from_json(data4)


def test_water_level_mismatch_refused(data4):
    data4["terrain"]["water_level"] = 61.0
    with pytest.raises(CourseJsonError, match="niveau d'eau"):
        course_input_from_json(data4)


def test_map_size_mismatch_refused(data4):
    data4["metadata"]["width"] = 401.0
    with pytest.raises(CourseJsonError, match="taille de carte"):
        course_input_from_json(data4)


@pytest.mark.parametrize("side", [True, 0, -400, 400.0, "400", None])
def test_map_size_not_positive_int_refused(data4, side):
    # booléen (True == 1 pour ``isinstance(…, int)``), nul, négatif, non entier
    data4["terrain"]["width"] = side
    if not isinstance(side, (str, type(None))):
        data4["metadata"]["width"] = float(side)
    with pytest.raises(CourseJsonError, match="taille de carte"):
        course_input_from_json(data4)


@pytest.mark.parametrize("key", ["terrain", "routing", "metadata"])
@pytest.mark.parametrize("value", [None, [], "objet", 3])
def test_section_not_an_object_refused(data4, key, value):
    data4[key] = value
    with pytest.raises(CourseJsonError, match="objet"):
        course_input_from_json(data4)


@pytest.mark.parametrize("value", [None, [], "eJw=", 3])
def test_relief_block_not_an_object_refused(data4, value):
    data4["terrain"]["elevation_f32"] = value
    with pytest.raises(CourseJsonError, match="relief illisible.*objet"):
        course_input_from_json(data4)


def test_oversized_relief_refused(data4):
    import base64
    import zlib
    data4["terrain"]["elevation_f32"]["data"] = base64.b64encode(
        zlib.compress(bytes(4 * 400 * 300 + 1))).decode("ascii")
    with pytest.raises(CourseJsonError, match="seed ou relief illisible.*plus de"):
        course_input_from_json(data4)


@pytest.mark.parametrize("corrupt", ["encoding", "unshuffled", "data", "seed"])
def test_unreadable_relief_or_seed_refused(data4, corrupt):
    if corrupt == "encoding":
        data4["terrain"]["elevation_f32"]["encoding"] = "base64_uint8"
    elif corrupt == "unshuffled":
        # float32 en ordre naturel, sans byte shuffle : codage refusé
        data4["terrain"]["elevation_f32"]["encoding"] = "zlib_base64_float32le"
    elif corrupt == "data":
        data4["terrain"]["elevation_f32"]["data"] = data4["terrain"]["elevation"]["data"]
    else:
        data4["metadata"]["seed"] = "quatre"
    with pytest.raises(CourseJsonError, match="seed ou relief illisible"):
        course_input_from_json(data4)


def test_unknown_style_refused(data4):
    with pytest.raises(ValueError, match="style inconnu"):
        dress_course_json(data4, "desert")
