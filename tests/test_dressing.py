"""Habillage (``golfgen.dressing``) : formes de greens sur des parcours réels,
déterminisme, indépendance vis-à-vis du tracé, export 3.1."""

from __future__ import annotations

from collections import Counter
import dataclasses
import json
import math
from pathlib import Path
import time

import numpy as np
import pytest

from golfgen import config as config_module
from golfgen.dressing import (RNG_LABEL, STYLE_SPECS, CourseDressing, DressingError,
                              dress_course, dress_course_json)
from golfgen.dressing import green as green_module
from golfgen.dressing import pairs as pairs_module
from golfgen.dressing.green import (BEAN_DEPTH_TOLERANCE, BEAN_MAX_EVALUATIONS, BEAN_MIN_NECK,
                                    GREEN_VERTICES, _aspect, _bean, _capsule, _capsule_alpha,
                                    _Draws, green_shape, hull_depth, neck_width, pick_kind,
                                    points_in_polygon, polygon_inside, shoelace, target_area)
from golfgen.dressing.model import FairwayShape, HoleDressing
from golfgen.exporter import _features_v31, _strictly_simple, muirfield_to_dict, with_dressing
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


# R3f : seul parcours réel du corpus des outils (120 layouts) avec un green
# double à PAIR_DISTANCE [12, 20] ; c'est 400×300 seed 1 (patron random
# résolu en muirfield, ``pipeline.py --seed 1``) : paire (10, 17) en links ;
# en parkland, tirage négatif pour la seed 1.
PAIR_CASE = (400, 300, 1)
R3E_RANGE = (12.0, 35.0)        # PAIR_DISTANCE de R3a à R3e


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


def test_snapshot_matches_router(courses):
    # l'instantané de tests/test_dressing_kinds.py est le routeur actuel
    from tests.test_dressing_kinds import load_snapshot
    snapshot = {((400, 300) if size == "400x300" else (300, 400)) + (seed,): holes
                for size, seed, holes in load_snapshot()}
    for case, (_, result) in courses.items():
        holes = tuple(sorted(result.layout.holes, key=lambda h: h.order))
        assert snapshot[case] == holes, case


def test_real_courses_get_green_pairs_in_links(courses):
    """Chemin réel (``build_course`` → ``dress_course``) : le repli « layout
    réduit à ``holes`` » de ``dress_course`` ne doit pas avaler les greens
    doubles. R3f (``PAIR_DISTANCE`` [12, 20]) : sur les 9 parcours, seul
    400×300 seed 1 en a une, (10, 17), en links (constat R3a, à [12, 35] :
    4 sur 9)."""
    with_pairs = {case: [(p.i, p.j) for p in pairs]
                  for case, (_, result) in courses.items()
                  if (pairs := dress_course(result, seed=case[2], style="links").green_pairs)}
    assert with_pairs == {PAIR_CASE: [(10, 17)]}


def _straight_hole(width: float, length: float = 300.0) -> ElasticHole:
    return ElasticHole(order=1, par=4, tee=ControlPoint(0.0, 0.0),
                       green=ControlPoint(length, 0.0), width=width)


@pytest.mark.parametrize("style", sorted(STYLE_SPECS))
def test_area_grows_with_core_width_at_equal_draws(style):
    spec = STYLE_SPECS[style]
    lo, hi = spec.green_area
    widths = [8.0 + 0.5 * i for i in range(25)]
    for u in (0.0, 0.3, 0.7, 1.0):
        targets = [target_area(_straight_hole(w), u, spec) for w in widths]
        assert all(a <= b for a, b in zip(targets, targets[1:]))
        assert all(a < b for a, b in zip(targets, targets[1:]) if lo < b and a < hi)
    # même flux aléatoire (mêmes tirages) : aire du green croissante avec l
    areas = []
    for width in widths:
        hole = _straight_hole(width)
        core = np.asarray(build_hole_geometry(hole).core, dtype=float)
        green = green_shape(hole, core, np.random.default_rng(11), spec)
        if not green.reduced:
            areas.append(green.area)
    assert len(areas) >= 20
    assert all(a <= b + AREA_TOLERANCE for a, b in zip(areas, areas[1:]))
    assert areas[-1] > areas[0]


@pytest.mark.parametrize("style", sorted(STYLE_SPECS))
def test_target_area_bounds(style):
    spec = STYLE_SPECS[style]
    lo, hi = spec.green_area
    assert target_area(_straight_hole(2.0), 1.0, spec) == lo
    assert target_area(_straight_hole(60.0), 0.0, spec) == hi
    for width in (5.0, 10.0, 15.0, 20.0, 30.0):
        for u in (0.0, 0.5, 1.0):
            assert lo <= target_area(_straight_hole(width), u, spec) <= hi


@pytest.mark.parametrize("style", sorted(STYLE_SPECS))
def test_pick_kind_eligibility(style):
    spec = STYLE_SPECS[style]
    big, small = spec.bean_min_area, spec.bean_min_area - 0.01
    grid = [i / 1000 for i in range(1000)]
    assert all(pick_kind(u, small, spec) != "bean" for u in grid)
    beans = sum(pick_kind(u, big, spec) == "bean" for u in grid)
    assert abs(beans / 1000 - spec.bean_given_eligible) <= 0.002
    for area in (small, big):
        plain = [pick_kind(u, area, spec) for u in grid]
        plain = [k for k in plain if k != "bean"]
        share = plain.count("round") / len(plain)
        assert abs(share - spec.round_given_plain) <= 0.005


@pytest.mark.parametrize("w", (7.0, 8.0))
@pytest.mark.parametrize("length", (2.15, 2.24))
@pytest.mark.parametrize("sagitta", (1.5, 1.75, 2.0))
def test_capsule_depth_neck_and_round_ends(w, length, sagitta):
    """Capsule courbée nue : creux = flèche, col = w, et chaque sommet à w/2
    de l'arc médian (bords parallèles, bouts en demi-cercles)."""
    arc = (length - 1.0) * w
    polygon = _capsule(w, arc, sagitta)
    assert polygon is not None and len(polygon) == GREEN_VERTICES
    assert shoelace(polygon) > 0.0 and _is_simple([tuple(p) for p in polygon])
    assert abs(hull_depth(polygon) - sagitta) <= 1e-9
    assert abs(neck_width(polygon, np.array((1.0, 0.0))) - w) <= 1e-9
    alpha = _capsule_alpha(sagitta / arc)
    radius = arc / (2.0 * alpha)
    center = np.array((0.0, sagitta / 2.0 - radius))
    rel = polygon - center
    angle = np.arctan2(rel[:, 0], rel[:, 1])
    ends = center + radius * np.array([(-math.sin(alpha), math.cos(alpha)),
                                       (math.sin(alpha), math.cos(alpha))])
    on_arc = np.abs(np.linalg.norm(rel, axis=1) - radius)
    to_ends = np.linalg.norm(polygon[:, None, :] - ends[None, :, :], axis=2).min(axis=1)
    distance = np.where(np.abs(angle) <= alpha, on_arc, to_ends)
    assert np.allclose(distance, w / 2.0, atol=1e-9)


def test_capsule_without_inner_arc_is_none():
    # flèche trop forte pour la longueur (w = 5,5, λ = 2,15, creux 2) : rayon
    # de l'arc médian ≤ w/2, creux inatteignable
    assert _capsule(5.5, 1.15 * 5.5, 2.0) is None


@pytest.mark.parametrize("style", sorted(STYLE_SPECS))
def test_bean_length_keeps_neck(style):
    # λ plafonné : w = √(aire / (λ − 1 + π/4)) ≥ BEAN_MIN_NECK, même petit
    spec = STYLE_SPECS[style]
    for area in (40.0, 60.0, spec.bean_min_area, spec.green_area[1]):
        for position in (0.0, 0.5, 1.0):
            length = _aspect("bean", position, area, spec)
            assert length <= spec.kind_aspects[2][1]
            assert math.sqrt(area / (length - 1.0 + math.pi / 4.0)) >= BEAN_MIN_NECK - 1e-9


@pytest.mark.parametrize("style", sorted(STYLE_SPECS))
def test_bean_depth_recalibrated_within_four_evaluations(style, monkeypatch):
    """Avec l'harmonique, creux recalé à ``BEAN_DEPTH_TOLERANCE`` du creux
    visé en ``BEAN_MAX_EVALUATIONS`` évaluations au plus."""
    spec = STYLE_SPECS[style]
    calls = []

    def counted(*args):
        calls.append(args)
        return _capsule(*args)

    monkeypatch.setattr(green_module, "_capsule", counted)
    rng = np.random.default_rng(11)
    for _ in range(40):
        depth = rng.uniform(*spec.bean_depth)
        draws = _Draws(kind=0.0, position=rng.uniform(), depth=depth,
                       side=1.0 if rng.uniform() < 0.5 else -1.0, recess=0.0,
                       coefficients=np.array([spec.harmonic_amplitude]),
                       phases=rng.uniform(0.0, 2.0 * math.pi, size=1))
        area = rng.uniform(spec.bean_min_area, spec.green_area[1])
        calls.clear()
        shape, cause = _bean(draws, _aspect("bean", draws.position, area, spec), area,
                             spec.bean_depth)
        assert 1 <= len(calls) <= BEAN_MAX_EVALUATIONS
        assert cause is None, cause
        target = min(max(depth, spec.bean_depth[0] + BEAN_DEPTH_TOLERANCE),
                     spec.bean_depth[1] - BEAN_DEPTH_TOLERANCE)
        assert abs(hull_depth(shape) - target) <= BEAN_DEPTH_TOLERANCE
        assert abs(shoelace(shape) - area) <= 1e-6


@pytest.mark.parametrize("failing_call, cause", [(1, "creux_inatteignable"), (2, "calage")])
def test_bean_fallback_cause_by_evaluation(failing_call, cause, monkeypatch):
    """Capsule hors domaine : ``creux_inatteignable`` si c'est la flèche
    visée (première évaluation), ``calage`` si c'est la flèche recalée."""
    spec = STYLE_SPECS["links"]
    calls = []

    def failing(*args):
        calls.append(args)
        return None if len(calls) == failing_call else _capsule(*args)

    monkeypatch.setattr(green_module, "_capsule", failing)
    # creux mesuré 0,5 au-dessus du visé (1,75) : recalage, flèche 1,25 > 0
    monkeypatch.setattr(green_module, "hull_depth", lambda shape: 2.25)
    draws = _Draws(kind=0.0, position=0.5, depth=1.75, side=1.0, recess=0.0,
                   coefficients=np.zeros(1), phases=np.zeros(1))
    area = spec.green_area[1]
    shape, got = _bean(draws, _aspect("bean", 0.5, area, spec), area, spec.bean_depth)
    assert shape is None and got == cause
    assert len(calls) == failing_call


def test_dressing_time_order_of_magnitude(courses):
    # 10 ms médian par parcours est la CIBLE (mesurée sur 60 parcours dans
    # report.json), pas le seuil du test : les mesures tournent sur un PC de
    # bureau chargé. Le garde-fou (10× la cible) vise une régression d'ordre
    # de grandeur.
    _, result = courses[(400, 300, 4)]
    best = math.inf
    for _ in range(5):
        t0 = time.perf_counter()
        dress_course(result, seed=4, style="links")
        best = min(best, time.perf_counter() - t0)
    print(f"\nhabillage seed 4 : {best * 1000:.1f} ms")
    assert best <= 0.100


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
    routing.pop("green_pairs", None)
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
            assert list(hole["features"]) == ["green", "tees", "fairway"]
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


def test_export_v31_tees(courses):
    """``features.tees`` : liste de 1 à 3 boîtes ``{outline, center, area}``,
    de l'arrière (centrée sur le tee routé) vers l'avant, fidèle à
    ``HoleDressing.tees`` ; le JSON 3.0 n'en porte pas trace."""
    heightmap, result = courses[(400, 300, 4)]
    plain = muirfield_to_dict(result, heightmap, seed=4)
    assert all("features" not in hole for hole in plain["routing"]["holes"])
    for style in STYLE_SPECS:
        dressing = dress_course(result, seed=4, style=style)
        data = muirfield_to_dict(result, heightmap, seed=4, dressing=dressing)
        for hole in data["routing"]["holes"]:
            tees = hole["features"]["tees"]
            boxes = dressing[hole["id"]].tees
            assert isinstance(tees, list) and 1 <= len(tees) == len(boxes) <= 3
            for item, box in zip(tees, boxes):
                assert set(item) == {"outline", "center", "area"}
                assert len(item["outline"]) == 4
                assert item["outline"] == [{"x": x, "y": y} for x, y in box.outline]
                assert item["center"] == {"x": round(box.center[0], 2),
                                          "y": round(box.center[1], 2)}
                assert item["area"] == box.area
            # ordre : de l'arrière vers l'avant, le long du sens du jeu
            # (centre arrondi comme toute sortie d'habillage ; tee routé
            # exporté en pleine précision, entrée de l'habillage)
            assert tees[0]["center"] == {k: round(v, 2) for k, v in hole["tee"].items()}
            tee = np.array([hole["tee"]["x"], hole["tee"]["y"]])
            first = hole["doglegs"][0] if hole["doglegs"] else hole["green"]
            heading = np.array([first["x"], first["y"]]) - tee
            along = [float(np.dot([t["center"]["x"], t["center"]["y"]] - tee, heading))
                     for t in tees]
            assert along == sorted(along) and len(set(along)) == len(along)


def _fairway_pieces_match(pieces, shapes) -> None:
    """``features.fairway`` fidèle à ``HoleDressing.fairway`` : même ordre,
    contours arrondis à 2 décimales, aire arrondie, pas de ``center`` ;
    contour exporté strictement simple ; morceaux par aire décroissante."""
    assert isinstance(pieces, list) and len(pieces) == len(shapes)
    for item, shape in zip(pieces, shapes):
        assert list(item) == ["outline", "area"]
        assert item["outline"] == [{"x": round(x, 2), "y": round(y, 2)} for x, y in shape.outline]
        assert item["area"] == round(shape.area, 2)
        outline = _xy_array(item["outline"])
        assert _strictly_simple(outline) and _is_simple([tuple(q) for q in outline])
    areas = [item["area"] for item in pieces]
    assert areas == sorted(areas, reverse=True)


def test_export_v31_fairway(courses):
    """``features.fairway`` (R5a) : toujours présent en 3.1, après ``tees`` ;
    un morceau par trou sans relief (aucune coupure), fidèle au modèle ;
    absent du 3.0."""
    for case in CASES:
        heightmap, result = courses[case]
        plain = muirfield_to_dict(result, heightmap, seed=case[2])
        assert all("features" not in hole for hole in plain["routing"]["holes"])
        for style in STYLE_SPECS:
            dressing = dress_course(result, seed=case[2], style=style)
            data = muirfield_to_dict(result, heightmap, seed=case[2], dressing=dressing)
            for hole in data["routing"]["holes"]:
                assert list(hole["features"]) == ["green", "tees", "fairway"]
                assert len(hole["features"]["fairway"]) == 1
                _fairway_pieces_match(hole["features"]["fairway"], dressing[hole["id"]].fairway)


def test_export_v31_fairway_additive(courses):
    """Ajout additif (R5a), sur l'habillage du pipeline (``dress_course_json``,
    coupure par l'eau du relief) : la partie 3.0 est identique octet pour
    octet, et ``green``/``tees`` sont ceux d'un habillage sans fairway."""
    heightmap, result = courses[(400, 300, 4)]
    plain = muirfield_to_dict(result, heightmap, seed=4)
    for style in STYLE_SPECS:
        dressing = dress_course_json(plain, style)
        data = with_dressing(plain, dressing)
        assert json.dumps(_strip_features(data["routing"])) == json.dumps(plain["routing"])
        assert data["terrain"] == plain["terrain"]
        bare = dataclasses.replace(dressing, holes={
            order: dataclasses.replace(hd, fairway=()) for order, hd in dressing.holes.items()})
        without = with_dressing(plain, bare)
        for hole, other in zip(data["routing"]["holes"], without["routing"]["holes"]):
            assert other["features"]["fairway"] == []
            assert json.dumps({k: v for k, v in hole["features"].items() if k != "fairway"}) \
                == json.dumps({k: v for k, v in other["features"].items() if k != "fairway"})
            _fairway_pieces_match(hole["features"]["fairway"], dressing[hole["id"]].fairway)
        assert json.dumps({**data, "routing": _strip_features(data["routing"])}) \
            == json.dumps({**without, "routing": _strip_features(without["routing"])})


NOT_SIMPLE_FAIRWAYS = [
    ((0.0, 0.0), (10.0, 0.0), (10.0, 0.001), (10.0, 10.0), (0.0, 10.0)),   # confondus à l'arrondi
    ((0.0, 0.0), (10.0, 10.0), (10.0, 0.0), (0.0, 10.0)),                   # nœud papillon
    ((0.0, 0.0), (0.001, 0.0), (0.0, 0.002)),                               # dégénéré à l'arrondi
]


@pytest.mark.parametrize("outline", NOT_SIMPLE_FAIRWAYS)
def test_export_v31_fairway_not_simple_raises(courses, outline):
    """Contour de fairway non strictement simple après l'arrondi : erreur
    explicite nommant le trou, jamais corrigé."""
    hd = dress_course(courses[(400, 300, 4)][1], seed=4, style="links")[7]
    bad = dataclasses.replace(hd, fairway=(*hd.fairway, FairwayShape(outline, 1.0)))
    with pytest.raises(ValueError, match="trou 7 : contour de fairway non simple"):
        _features_v31(bad)


@pytest.mark.parametrize("outline", NOT_SIMPLE_FAIRWAYS)
def test_export_v31_fairway_not_simple_raises_from_with_dressing(courses, outline):
    """Même erreur par le point d'entrée ``with_dressing`` (étape 2 du
    pipeline) : la ``ValueError`` nommant le trou remonte telle quelle."""
    heightmap, result = courses[(400, 300, 4)]
    plain = muirfield_to_dict(result, heightmap, seed=4)
    dressing = dress_course(result, seed=4, style="links")
    hd = dressing[7]
    bad = dataclasses.replace(hd, fairway=(*hd.fairway, FairwayShape(outline, 1.0)))
    forged = dataclasses.replace(dressing, holes={**dressing.holes, 7: bad})
    with pytest.raises(ValueError, match="trou 7 : contour de fairway non simple"):
        with_dressing(plain, forged)


def test_export_v31_fairway_empty(courses):
    """Fairway vide (``()``, vidé par l'eau) : clé présente, ``[]`` ; défaut
    de ``HoleDressing`` compris."""
    hd = dress_course(courses[(400, 300, 4)][1], seed=4, style="links")[3]
    for empty in (dataclasses.replace(hd, fairway=()),
                  HoleDressing(order=3, green=hd.green, tees=hd.tees)):
        assert list(_features_v31(empty)) == ["green", "tees", "fairway"]
        assert _features_v31(empty)["fairway"] == []


def _xy_array(points) -> np.ndarray:
    return np.array([[p["x"], p["y"]] for p in points], dtype=float)


def _assert_green_pairs(data, dressing):
    """``routing.green_pairs`` fidèle à ``dressing.green_pairs`` : triés par
    ``(i, j)``, contour arrondi à 2 décimales (sommets confondus par
    l'arrondi retirés), même sens que les greens, aire du contour exporté,
    polygone simple contenant les centres des deux greens."""
    pairs = data["routing"]["green_pairs"]
    expected = sorted(dressing.green_pairs, key=lambda p: (p.i, p.j))
    assert [entry["holes"] for entry in pairs] == [[p.i, p.j] for p in expected]
    holes = {hole["id"]: hole for hole in data["routing"]["holes"]}
    for entry, pair in zip(pairs, expected):
        assert set(entry) == {"holes", "outline", "area"}
        rounded = [(round(x, 2), round(y, 2)) for x, y in pair.outline]
        rounded = [p for k, p in enumerate(rounded) if p != rounded[k - 1]]
        assert [(p["x"], p["y"]) for p in entry["outline"]] == rounded
        outline = _xy_array(entry["outline"])
        assert shoelace(outline) > 0                    # comme features.green.outline
        assert entry["area"] == round(abs(shoelace(outline)), 2)
        assert abs(entry["area"] - abs(shoelace(np.asarray(pair.outline)))) < AREA_TOLERANCE
        assert _is_simple([tuple(p) for p in outline])
        for order in entry["holes"]:
            green = holes[order]["features"]["green"]
            assert shoelace(_xy_array(green["outline"])) > 0
            centre = np.array([[green["center"]["x"], green["center"]["y"]]])
            assert points_in_polygon(centre, outline)[0]
            # greens individuels inchangés par la paire
            assert green["outline"] == [{"x": x, "y": y}
                                        for x, y in dressing[order].green.outline]


def test_export_v31_green_pairs(courses):
    """``routing.green_pairs`` : toujours présent en 3.1 (liste vide sans
    green double), absent du 3.0 ; seed 1 : la paire (10, 17) en links,
    aucune en parkland (tirage négatif) ; seed 3 : aucune paire."""
    for case, expected in ((PAIR_CASE, {"links": [[10, 17]], "parkland": []}),
                           ((400, 300, 3), {"links": [], "parkland": []})):
        (heightmap, result), seed = courses[case], case[2]
        plain = muirfield_to_dict(result, heightmap, seed=seed)
        assert "green_pairs" not in plain["routing"]
        for style in STYLE_SPECS:
            dressing = dress_course(result, seed=seed, style=style)
            data = muirfield_to_dict(result, heightmap, seed=seed, dressing=dressing)
            assert list(data["routing"]) == ["clubhouse", "direction", "holes", "green_pairs",
                                              "links"]
            assert [p["holes"] for p in data["routing"]["green_pairs"]] == expected[style]
            _assert_green_pairs(data, dressing)
            for value in _floats_of(data["routing"]["green_pairs"]):
                assert value == round(value, 2)


def _floats_of(node):
    if isinstance(node, dict):
        node = list(node.values())
    if isinstance(node, list):
        for item in node:
            yield from _floats_of(item)
    elif isinstance(node, float):
        yield node


def test_export_v31_green_pairs_sorted_by_holes(monkeypatch):
    """300×400 seed 7 en links, à la plage R3a–R3e [12, 35] (aucun parcours
    réel n'a deux paires à [12, 20]) : deux paires, (15, 17) avant (14, 16)
    dans l'ordre de sélection (distance), exportées triées par trous ; formes
    R3f."""
    monkeypatch.setattr(pairs_module, "PAIR_DISTANCE", R3E_RANGE)
    heightmap = load_terrain(7, 300, 400)
    result = mf.build_course(7, "random", heightmap, width=300, height=400)
    dressing = dress_course(result, seed=7, style="links")
    assert [(p.i, p.j) for p in dressing.green_pairs] == [(15, 17), (14, 16)]
    data = muirfield_to_dict(result, heightmap, seed=7, dressing=dressing)
    assert [p["holes"] for p in data["routing"]["green_pairs"]] == [[14, 16], [15, 17]]
    _assert_green_pairs(data, dressing)


def test_export_v31_green_pairs_skip_shapeless_and_check_holes(courses):
    heightmap, result = courses[PAIR_CASE]
    seed = PAIR_CASE[2]
    dressing = dress_course(result, seed=seed, style="links")
    real = dressing.green_pairs[0]
    shapeless = dataclasses.replace(real, i=1, j=3, outline=(), neck_width=None)
    forged = dataclasses.replace(dressing, green_pairs=dressing.green_pairs + (shapeless,))
    data = muirfield_to_dict(result, heightmap, seed=seed, dressing=forged)
    assert [p["holes"] for p in data["routing"]["green_pairs"]] == [[10, 17]]
    stray = dataclasses.replace(dressing, green_pairs=(dataclasses.replace(real, j=19),))
    with pytest.raises(ValueError, match="green double"):
        muirfield_to_dict(result, heightmap, seed=seed, dressing=stray)


@pytest.mark.parametrize("outline", [
    ((0.0, 0.0), (0.001, 0.002), (10.0, 0.0)),                  # 2 sommets après arrondi
    ((0.0, 0.0), (4.0, 4.0), (4.0, 0.0), (0.0, 4.0)),           # nœud papillon
    ((0.0, 0.0), (5.0, 0.0), (5.0, 5.0), (2.5, 0.001), (0.0, 5.0)),  # pincé à l'arrondi
])
def test_export_v31_green_pairs_refuse_degenerate_rounded_outline(courses, outline):
    heightmap, result = courses[PAIR_CASE]
    seed = PAIR_CASE[2]
    dressing = dress_course(result, seed=seed, style="links")
    bad = dataclasses.replace(dressing.green_pairs[0], outline=outline)
    forged = dataclasses.replace(dressing, green_pairs=(bad,))
    with pytest.raises(ValueError, match="dégénéré"):
        muirfield_to_dict(result, heightmap, seed=seed, dressing=forged)


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
