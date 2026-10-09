"""Habillage (``golfgen.dressing``) : formes de greens sur des parcours réels,
déterminisme, indépendance vis-à-vis du tracé, export 3.1."""

from __future__ import annotations

from collections import Counter
import json
import math
from pathlib import Path
import time

import numpy as np
import pytest

from golfgen import config as config_module
from golfgen.dressing import (RNG_LABEL, STYLE_SPECS, CourseDressing, DressingError,
                              dress_course)
from golfgen.dressing.green import (GREEN_VERTICES, green_shape, points_in_polygon,
                                    polygon_inside, shoelace)
from golfgen.exporter import muirfield_to_dict
from golfgen.routing import muirfield as mf
from golfgen.routing.model import ControlPoint, ElasticHole
from golfgen.routing.geometry import (ValidationRules, _point_in_polygon, _segments,
                                      build_hole_geometry, segments_intersect, validate)
from golfgen.routing.sites import dry_mask, load_terrain

REPO_ROOT = Path(__file__).resolve().parents[1]

# 9 parcours réels (162 trous) : paysage seeds 1–6, portrait seeds 1–3, patron random
CASES = [(400, 300, seed) for seed in range(1, 7)] + [(300, 400, seed) for seed in range(1, 4)]
AREA_TOLERANCE = 0.5            # blocs² : arrondi des sommets à 2 décimales


@pytest.fixture(scope="module")
def courses():
    out = {}
    for width, height, seed in CASES:
        heightmap = load_terrain(seed, width, height)
        result = mf.build_course(seed, "random", heightmap, width=width, height=height)
        out[(width, height, seed)] = (heightmap, result)
    return out


@pytest.fixture(scope="module", params=sorted(STYLE_SPECS))
def dressed(request, courses):
    style = request.param
    return style, {case: dress_course(result, seed=case[2], style=style)
                   for case, (_, result) in courses.items()}


def _is_simple(polygon) -> bool:
    edges = list(_segments(polygon, closed=True))
    n = len(edges)
    for i in range(n):
        for j in range(i + 1, n):
            if j == i + 1 or (i == 0 and j == n - 1):
                continue
            if segments_intersect(*edges[i], *edges[j]):
                return False
    return True


def test_styles_match_config():
    assert tuple(STYLE_SPECS) == config_module.STYLES


def test_rng_label_unused_by_router():
    sources = "".join((REPO_ROOT / "golfgen" / "routing" / name).read_text(encoding="utf-8")
                      for name in ("muirfield.py", "sites.py"))
    assert str(RNG_LABEL) not in sources
    assert hex(RNG_LABEL).lower() not in sources.lower()


def test_green_properties_on_real_holes(courses, dressed):
    style, dressings = dressed
    lo, hi = STYLE_SPECS[style].green_area
    reduced = Counter()
    for case, (_, result) in courses.items():
        dressing = dressings[case]
        assert isinstance(dressing, CourseDressing) and dressing.style == style
        assert list(dressing.holes) == list(range(1, 19))
        for hole in result.layout.holes:
            green = dressing[hole.order].green
            outline = green.outline
            core = build_hole_geometry(hole).core
            flag = (hole.green.x, hole.green.y)
            assert len(outline) == GREEN_VERTICES
            assert all(round(v, 2) == v for point in outline for v in point)
            assert all(round(v, 2) == v for v in green.center)
            assert _is_simple(outline), (case, hole.order)
            signed = shoelace(np.asarray(outline))
            assert signed > 0
            assert green.area == round(signed, 2)
            # contient le drapeau, inclus dans le cœur (oracle de geometry)
            assert _point_in_polygon(flag, outline), (case, hole.order)
            assert all(_point_in_polygon(p, core) for p in outline), (case, hole.order)
            assert not any(segments_intersect(a, b, c, d)
                           for a, b in _segments(outline, closed=True)
                           for c, d in _segments(core, closed=True)), (case, hole.order)
            assert lo <= green.target_area <= hi
            if green.reduced:
                reduced[hole.par] += 1
                assert green.scale < 1.0 and green.area < green.target_area
            else:
                assert green.scale == 1.0
                assert lo - AREA_TOLERANCE <= green.area <= hi + AREA_TOLERANCE
                assert abs(green.area - green.target_area) <= AREA_TOLERANCE
    print(f"\n{style} : greens réduits par par {dict(reduced)}")


def test_area_grows_with_hole_length(courses, dressed):
    style, dressings = dressed
    means = {}
    for par in (3, 4, 5):
        targets = [dressings[case][hole.order].green.target_area
                   for case, (_, result) in courses.items()
                   for hole in result.layout.holes if hole.par == par]
        means[par] = sum(targets) / len(targets)
    assert means[3] < means[4] < means[5]


def test_deterministic_and_seed_dependent(courses):
    _, result = courses[(400, 300, 4)]
    first = dress_course(result, seed=4, style="links")
    again = dress_course(result, seed=4, style="links")
    other = dress_course(result, seed=5, style="links")
    assert dict(first.holes) == dict(again.holes)
    assert first[1].green.outline != other[1].green.outline


def test_dressing_leaves_routing_untouched(courses):
    for (width, height, seed), (heightmap, result) in courses.items():
        before = result.layout.to_dict()
        for style in STYLE_SPECS:
            dress_course(result, seed=seed, style=style)
        assert result.layout.to_dict() == before
        rules = ValidationRules(width=width, height=height)
        assert validate(result.layout, rules, dry=dry_mask(heightmap)) == []


def test_dressing_time_order_of_magnitude(courses):
    # 50 ms est la CIBLE (≈ 6 ms mesurés au repos, cf. report.json), pas le
    # seuil du test : les mesures tournent sur un PC de bureau chargé. Le
    # garde-fou ne vise qu'une régression d'ordre de grandeur.
    _, result = courses[(400, 300, 4)]
    best = math.inf
    for _ in range(5):
        t0 = time.perf_counter()
        dress_course(result, seed=4, style="links")
        best = min(best, time.perf_counter() - t0)
    print(f"\nhabillage seed 4 : {best * 1000:.1f} ms")
    assert best <= 0.250


@pytest.mark.parametrize("style", sorted(STYLE_SPECS))
def test_narrow_synthetic_hole_forces_shrink(style):
    # trou rectiligne de 120 blocs, cœur de 4 blocs de large : l'aire visée
    # (≥ 60 blocs²) ne tient pas, la forme est réduite vers le drapeau
    hole = ElasticHole(order=1, par=3, tee=ControlPoint(0.0, 0.0),
                       green=ControlPoint(120.0, 0.0), width=4.0)
    core = np.asarray(build_hole_geometry(hole).core, dtype=float)
    green = green_shape(hole, core, np.random.default_rng(7), STYLE_SPECS[style])
    outline = np.asarray(green.outline)
    assert green.shrink_steps > 0 and green.reduced
    assert 0.0 < green.scale < 1.0 and green.area < green.target_area
    assert polygon_inside(outline, core)
    assert all(_point_in_polygon(point, [tuple(p) for p in core]) for point in green.outline)
    assert points_in_polygon(np.array([[120.0, 0.0]]), outline)[0]
    assert len(green.outline) == GREEN_VERTICES and _is_simple(green.outline)


def test_null_final_segment_raises():
    # ElasticHole refuse deux points ÉGAUX ; des points distincts mais si
    # proches que la norme s'annule en flottant passent : erreur explicite
    with pytest.raises(ValueError, match="segment nul"):
        ElasticHole(order=1, par=3, tee=ControlPoint(0.0, 0.0), green=ControlPoint(0.0, 0.0))
    hole = ElasticHole(order=1, par=3, tee=ControlPoint(0.0, 0.0),
                       green=ControlPoint(1e-200, 0.0))
    core = np.array([(-10.0, -10.0), (10.0, -10.0), (10.0, 10.0), (-10.0, 10.0)])
    with pytest.raises(DressingError, match="segment final nul"):
        green_shape(hole, core, np.random.default_rng(0), STYLE_SPECS["links"])


def test_shrink_without_convergence_raises_dressing_error():
    # Drapeau HORS du cœur : l'homothétie centrée sur lui ne converge jamais
    hole = ElasticHole(order=2, par=3, tee=ControlPoint(0.0, 0.0),
                       green=ControlPoint(120.0, 0.0))
    core = np.array([(-10.0, -10.0), (10.0, -10.0), (10.0, 10.0), (-10.0, 10.0)])
    with pytest.raises(DressingError, match="green impossible"):
        green_shape(hole, core, np.random.default_rng(0), STYLE_SPECS["links"])


@pytest.mark.parametrize("kwargs, error", [
    ({"seed": 4, "style": "desert"}, ValueError),
    ({"seed": -1, "style": "links"}, ValueError),
    ({"seed": 2 ** 64, "style": "links"}, ValueError),
    ({"seed": 4.0, "style": "links"}, TypeError),
    ({"seed": True, "style": "links"}, TypeError),
])
def test_bad_arguments(courses, kwargs, error):
    _, result = courses[(400, 300, 4)]
    with pytest.raises(error):
        dress_course(result, **kwargs)


# ----------------------------------------------------------------------
# Export 3.1
# ----------------------------------------------------------------------

def _plain_types(node) -> bool:
    if isinstance(node, dict):
        return all(type(k) is str and _plain_types(v) for k, v in node.items())
    if isinstance(node, list):
        return all(_plain_types(v) for v in node)
    return node is None or type(node) in (str, int, float, bool)


def _strip_features(routing: dict) -> dict:
    routing = json.loads(json.dumps(routing))
    for hole in routing["holes"]:
        hole.pop("features", None)
    return routing


def test_export_v31(courses):
    heightmap, result = courses[(400, 300, 4)]
    plain = muirfield_to_dict(result, heightmap, seed=4)
    assert plain["metadata"]["version"] == "3.0" and "style" not in plain["metadata"]
    assert all("features" not in hole for hole in plain["routing"]["holes"])
    for style in STYLE_SPECS:
        dressing = dress_course(result, seed=4, style=style)
        data = muirfield_to_dict(result, heightmap, seed=4, dressing=dressing)
        meta = data["metadata"]
        assert (meta["version"], meta["style"]) == ("3.1", style)
        assert _plain_types(data)
        json.dumps(data)
        for hole in data["routing"]["holes"]:
            green = hole["features"]["green"]
            shape = dressing[hole["id"]].green
            assert set(hole["features"]) == {"green"}
            assert set(green) == {"outline", "center", "area"}
            assert green["outline"] == [{"x": x, "y": y} for x, y in shape.outline]
            assert green["center"] == {"x": shape.center[0], "y": shape.center[1]}
            assert green["area"] == shape.area
        # tracé identique octet pour octet, habillage retiré ; métadonnées
        # identiques hors version et style
        assert json.dumps(_strip_features(data["routing"])) == json.dumps(plain["routing"])
        stripped = {k: v for k, v in meta.items() if k not in ("version", "style")}
        assert stripped == {k: v for k, v in plain["metadata"].items() if k != "version"}
        assert data["terrain"] == plain["terrain"]


def test_export_rejects_mismatched_dressing(courses):
    heightmap, result = courses[(400, 300, 4)]
    dressing = dress_course(result, seed=4, style="links")
    partial = CourseDressing(style="links",
                             holes={k: v for k, v in dressing.holes.items() if k != 18})
    with pytest.raises(ValueError):
        muirfield_to_dict(result, heightmap, seed=4, dressing=partial)
    with pytest.raises(TypeError):
        muirfield_to_dict(result, heightmap, seed=4, dressing=dict(dressing.holes))


@pytest.mark.parametrize("style", ["desert", "Links", None])
def test_export_rejects_unknown_style(courses, style):
    heightmap, result = courses[(400, 300, 4)]
    dressing = dress_course(result, seed=4, style="links")
    forged = CourseDressing(style=style, holes=dressing.holes)
    with pytest.raises(ValueError, match="style d'habillage inconnu"):
        muirfield_to_dict(result, heightmap, seed=4, dressing=forged)
