"""Fairway B v1 (``golfgen.dressing.fairway``, lot 2 R2), à col marqué en
production (``profile_neck``, R2b), et profil en long (R3,
``golfgen.dressing.fairway_profile``), branchés à ``dress_course`` :
empreinte de la forme brute B v1 figée sur l'outil du R1 et empreinte de
production figée sur la colonne K de l'outil des cols (au bit près),
mécanique du col (zones et plateaux de v1, col plus bas, max de v1 aux
chevauchements, plancher de 6 blocs testé, cœurs étroits compris), îlots
d'un nœud de grille retirés et comptés (deux cas réels à la plage 12–35,
cas fabriqués ; un vrai second morceau lève toujours), inclusion dans le
cœur, une seule boucle et aucun recouvrement des boîtes,
du green ni du green double, du trou ou des autres (aucun green ni green
double d'un autre trou ne coupe un fairway), sur l'instantané 30x2
(1080 trous, deux styles) et les layouts des paires (écarts aux gardes à
une borne explicite près), déterminisme, flux
séparés (changer le fairway ou son profil ne bouge ni greens, ni départs, ni
paires ; le profil ne bouge pas les tirages de forme), sorties du lot 1
identiques au bit près à celles d'avant le branchement."""

from __future__ import annotations

import dataclasses
import hashlib
import json
import math
from collections import Counter
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from golfgen.dressing import RNG_LABEL, STYLE_SPECS, DressingError, FairwayShape, dress_course
from golfgen.dressing import course as course_module
from golfgen.dressing import fairway as fw
from golfgen.dressing import fairway_profile as fwp
from golfgen.dressing import fairway_water as fww
from golfgen.dressing import pairs as pairs_module
from golfgen.dressing.course import (FAIRWAY_STREAM, PROFILE_STREAM, fairway_profile_rng,
                                     fairway_rng, tee_rng)
from golfgen.dressing.pairs import polygon_gap_np
from golfgen.dressing.green import points_in_polygon, shoelace
from golfgen.dressing.offset import marching_squares, resample
from golfgen.dressing.pair_shape import is_simple
from golfgen.routing.geometry import build_hole_geometry
from golfgen.routing.model import ControlPoint, CourseLayout, ElasticHole
from golfgen.seed import seed_u64
from tests import fairway_fingerprint as ff

DATA = Path(__file__).resolve().parent / "data"
# Sorties du lot 1 (greens, départs, causes, paires, rejets) sur l'instantané
# 30x2 et les layouts complets des paires, relevées AVANT le branchement du
# fairway (88e670c + empreinte B v1) ; même calcul que ``_lot1_digest``.
# Lot 1 eau : les champs ``GreenShape.island`` et ``TeeBox.island`` (``None``
# sans eau) sont retirés du ``repr`` d'un green ou d'une boîte au sec
# (``green_repr``, ``tee_repr``) : la valeur d'avant ces champs reste la
# référence, au bit près.
LOT1_DIGEST = "811eb9d67896d70a0eca459ba56649fa8bbcf5b64c55e25fc152e85d70926852"
LOT1_CASES = 90


def _holes_only(holes):
    return SimpleNamespace(layout=SimpleNamespace(holes=holes))


def _lot1_cases():
    """``(étiquette, seed, résultat)`` : instantané 30x2 (seeds brutes),
    puis layouts complets des greens doubles (trois seeds chacun)."""
    cases = []
    snapshot = json.loads((DATA / "dressing_holes_30x2.json").read_text(encoding="utf-8"))
    for c in snapshot["courses"]:
        holes = tuple(ElasticHole.from_dict(h) for h in c["holes"])
        cases.append((f"{c['size']}/{c['seed']}", c["seed"], _holes_only(holes)))
    for name in ("green_pairs_layouts.json", "green_pair_r3f_layout.json"):
        for c in json.loads((DATA / name).read_text(encoding="utf-8"))["layouts"]:
            layout = CourseLayout.from_dict(c["layout"])
            for seed in (c["seed"], seed_u64(c["seed"]), 2 ** 64 - 1):
                cases.append((f"{name}/{c.get('round')}/{c.get('pattern')}/{c['seed']}/{seed}",
                              seed, SimpleNamespace(layout=layout)))
    return cases


@pytest.fixture(scope="module")
def dressed():
    """``[(étiquette, résultat, seed, style, habillage)]``, ordre de
    ``_lot1_cases`` puis des styles."""
    return [(label, result, seed, style, dress_course(result, seed=seed, style=style))
            for label, seed, result in _lot1_cases() for style in STYLE_SPECS]


def green_repr(green) -> str:
    """``repr`` du green sans le champ ``island`` s'il vaut ``None`` (lot 1
    eau) : celui d'avant ce champ ; un green insulaire garde le sien."""
    text = repr(green)
    if green.island is None:
        assert text.endswith(", island=None)")
        text = text[:-len(", island=None)")] + ")"
    return text


def tee_repr(box) -> str:
    """``repr`` de la boîte sans le champ ``island`` s'il vaut ``None`` (lot
    1 eau, boîte au sec) : celui d'avant ce champ ; une boîte remontée garde
    le sien."""
    text = repr(box)
    if box.island is None:
        assert text.endswith(", island=None)")
        text = text[:-len(", island=None)")] + ")"
    return text


def tees_repr(tees) -> str:
    """``repr`` du tuple de boîtes, chacune par ``tee_repr``."""
    items = [tee_repr(box) for box in tees]
    return "(" + ", ".join(items) + ("," if len(items) == 1 else "") + ")"


def _lot1_parts(dressing) -> list[str]:
    parts = [repr(dressing.green_pairs), repr(dressing.pair_rejections)]
    for order, hd in dressing.holes.items():
        parts += [repr(order), repr(hd.order), green_repr(hd.green), tees_repr(hd.tees),
                  repr(hd.tee_fallback_cause)]
    return parts


def _lot1_digest(dressed) -> str:
    digest = hashlib.sha256()
    for label, _, _, style, dressing in dressed:
        digest.update("\n".join([label, style] + _lot1_parts(dressing)).encode())
    return digest.hexdigest()


# --- mesures ------------------------------------------------------------------------------

def _point_edge_distances(points: np.ndarray, polygon: np.ndarray) -> np.ndarray:
    """Distance de chaque point au bord du polygone fermé."""
    a = polygon[None, :, :]
    ab = np.roll(polygon, -1, axis=0)[None, :, :] - a
    ap = points[:, None, :] - a
    t = np.clip((ap * ab).sum(axis=2) / np.maximum((ab * ab).sum(axis=2), 1e-12), 0.0, 1.0)
    return np.linalg.norm(ap - t[..., None] * ab, axis=2).min(axis=1)


def _crossings(first: np.ndarray, second: np.ndarray) -> int:
    """Nombre de croisements propres entre arêtes des deux polygones fermés."""
    a, b = first[:, None, :], np.roll(first, -1, axis=0)[:, None, :]
    c, d = second[None, :, :], np.roll(second, -1, axis=0)[None, :, :]

    def orient(p, q, r):
        return (q[..., 0] - p[..., 0]) * (r[..., 1] - p[..., 1]) \
            - (q[..., 1] - p[..., 1]) * (r[..., 0] - p[..., 0])
    o1, o2 = orient(a, b, c), orient(a, b, d)
    o3, o4 = orient(c, d, a), orient(c, d, b)
    return int(((o1 * o2 < 0) & (o3 * o4 < 0)).sum())


def core_check(outline: np.ndarray, core: np.ndarray) -> dict:
    """Inclusion du fairway dans le cœur, vérifiée (pas de clip) :
    sommets hors du cœur (et distance max au cœur), sommets du cœur dans le
    fairway, croisements d'arêtes ; marge = distance min au bord du cœur."""
    inside = points_in_polygon(outline, core)
    distances = _point_edge_distances(outline, core)
    core_inside = int(points_in_polygon(core, outline).sum())
    crossings = _crossings(outline, core)
    outside = int((~inside).sum())
    return {"ok": outside == 0 and core_inside == 0 and crossings == 0,
            "outside_vertices": outside, "core_vertices_inside": core_inside,
            "crossings": crossings,
            "max_outside": float(distances[~inside].max()) if outside else 0.0,
            "margin": float(distances[inside].min()) if inside.any() else 0.0}


def cut_width(axis: fw.Axis, outline: np.ndarray, s: float, reach: float) -> float | None:
    """Largeur du contour sur la perpendiculaire à l'axe en ``s`` (écart
    entre les intersections extrêmes à au plus ``reach`` de l'axe)."""
    (q,), (n,) = axis.at(np.array([s]))
    a = outline
    e = np.roll(outline, -1, axis=0) - a
    w = a - q
    denom = n[0] * e[:, 1] - n[1] * e[:, 0]
    safe = np.where(np.abs(denom) < 1e-12, np.nan, denom)
    t = (w[:, 0] * e[:, 1] - w[:, 1] * e[:, 0]) / safe
    u = (w[:, 0] * n[1] - w[:, 1] * n[0]) / safe
    hit = (u >= 0.0) & (u < 1.0) & (np.abs(t) <= reach)
    if hit.sum() < 2:
        return None
    return float(t[hit].max() - t[hit].min())


def test_core_check_detects_overflow():
    """``core_check`` signale un contour qui sort du cœur (sommets dehors,
    croisements) et accepte un contour intérieur avec sa marge."""
    core = np.array([(0.0, 0.0), (10.0, 0.0), (10.0, 10.0), (0.0, 10.0)])
    inner = np.array([(2.0, 2.0), (8.0, 2.0), (8.0, 8.0), (2.0, 8.0)])
    check = core_check(inner, core)
    assert check["ok"] and check["margin"] == pytest.approx(2.0)
    out = core_check(inner + (5.0, 0.0), core)
    assert not out["ok"] and out["outside_vertices"] == 2 and out["crossings"] == 2
    assert out["max_outside"] == pytest.approx(3.0)


# --- empreinte de B v1 -----------------------------------------------------------------

def _module_shape(hole, core, style, seed):
    build = fw.build_fairway(hole, core, fw.FAIRWAY_STYLES[style], fairway_rng(seed, hole.order))
    return build.outline, build.profile.zones, build.loops


def test_fingerprint_b_v1():
    """Le module redonne au bit près B v1 figée au R1."""
    got, ref = ff.fingerprint(_module_shape), ff.load()
    assert got["cases"] == ref["cases"]
    assert got["digest"] == ref["digest"]


def _production_shape(hole, core, style, seed):
    dressing, _ = ff.single_hole_dressing(hole, style, seed)
    (shape,) = dressing[hole.order].fairway
    profile = fw.profile_neck(hole, fw.Axis.of(hole), fw.FAIRWAY_STYLES[style],
                              fairway_rng(seed, hole.order), fw.cap_half(hole))
    return np.array(shape.outline), profile.zones, 1


def test_fingerprint_production():
    """``dress_course`` redonne, au bit près, l'empreinte de production
    (col marqué K) figée avant l'intégration (R2b)."""
    got, ref = ff.fingerprint(_production_shape), ff.load(ff.NECK_FINGERPRINT)
    assert got["cases"] == ref["cases"]
    assert got["digest"] == ref["digest"]


# --- col marqué (R2b) ------------------------------------------------------------------

def _ratios(style: str):
    """Style de production, et le même au col modéré de la planche (0,70)."""
    spec = fw.FAIRWAY_STYLES[style]
    return (spec, dataclasses.replace(spec, neck_ratio=0.70))


@pytest.mark.parametrize("style", sorted(STYLE_SPECS))
@pytest.mark.parametrize("name", sorted(ff.FABRICATED))
def test_profile_neck(name, style):
    """Mêmes tirages, zones et plateaux que v1, même plateau de zone, col
    plus bas (jamais sous ``neck_min`` avant bruit), largeur ≥
    ``width_floor`` après bruit, jamais au-dessus du plafond."""
    hole = ff.FABRICATED[name]
    axis, cap = fw.Axis.of(hole), fw.cap_half(hole)
    v1_rng = fairway_rng(5, hole.order)
    v1 = fw.profile_b(hole, axis, fw.FAIRWAY_STYLES[style], v1_rng, cap)
    for spec in _ratios(style):
        rng = fairway_rng(5, hole.order)
        neck = fw.profile_neck(hole, axis, spec, rng, cap)
        assert neck.zones == v1.zones and neck.plateaus == v1.plateaus
        assert np.array_equal(neck.s, v1.s)
        assert (neck.left + neck.right >= spec.width_floor).all()
        assert (np.maximum(neck.left, neck.right) <= cap).all()
        if not neck.zones:
            assert np.array_equal(neck.base, v1.base)
            continue
        # hors des zones et de leurs raccords : col jamais plus large que v1
        away = np.all([np.abs(neck.s - c) > p / 2.0 + spec.neck_ramp
                       for c, p in zip(neck.zones, neck.plateaus)], axis=0)
        assert (neck.base[away] <= v1.base[away] + 1e-9).all()
        halves = []
        for center in neck.zones:
            k = np.argmin(np.abs(neck.s - center))
            assert neck.base[k] == pytest.approx(v1.base[k])
            halves.append(neck.base[k])
        assert neck.base.min() >= min(spec.neck_min / 2.0, min(halves)) - 1e-9


def test_neck_half():
    spec = fw.FAIRWAY_STYLES["links"]
    moderate = dataclasses.replace(spec, neck_ratio=0.70)
    assert spec.neck_ratio == 0.55 and spec.neck_min == 6.5
    assert fw.neck_half([5.0, 6.0], moderate, 5.0) == pytest.approx(3.5)
    assert fw.neck_half([5.0, 6.0], spec, 5.0) == pytest.approx(spec.neck_min / 2.0)
    assert fw.neck_half([3.0], spec, 5.0) == pytest.approx(3.0)      # jamais au-dessus de la zone
    assert fw.neck_half([6.0], moderate, 4.0) == pytest.approx(4.0)  # ni du col de v1


# deux coudes à 22 blocs : le plateau de chaque zone est dans le raccord de l'autre
CLOSE_ZONES = ElasticHole(order=6, par=5, tee=ControlPoint(40.0, 10.0),
                          doglegs=(ControlPoint(60.0, 70.0), ControlPoint(58.0, 92.0)),
                          green=ControlPoint(40.0, 220.0), width=16.0)


@pytest.mark.parametrize("style", sorted(STYLE_SPECS))
def test_overlapping_zones_keep_their_plateau(style):
    """Zones dont les raccords se chevauchent : sur le plateau de chaque
    zone, demi-largeur avant bruit au moins celle de la zone (max de v1),
    jamais abaissée par la moyenne pondérée."""
    axis, cap = fw.Axis.of(CLOSE_ZONES), fw.cap_half(CLOSE_ZONES)
    for spec in _ratios(style):
        draws = fw.profile_draws(fairway_rng(5, CLOSE_ZONES.order), spec)
        neck = fw.profile_neck(CLOSE_ZONES, axis, spec, fairway_rng(5, CLOSE_ZONES.order), cap)
        assert len(neck.zones) >= 2
        crossed = False
        for k, (center, plateau) in enumerate(zip(neck.zones, neck.plateaus)):
            on = np.abs(neck.s - center) <= plateau / 2.0
            half = min(draws["landing"][k] / 2.0, cap - spec.noise_amp)
            assert (neck.base[on] >= half).all(), k
            crossed |= any((np.abs(neck.s[on] - c) < p / 2.0 + spec.neck_ramp).any()
                           for j, (c, p) in enumerate(zip(neck.zones, neck.plateaus)) if j != k)
        assert crossed


@pytest.mark.parametrize("style", sorted(STYLE_SPECS))
@pytest.mark.parametrize("width", [6.0, 7.0, 8.0, 9.0])
def test_width_floor_on_narrow_cores(width, style):
    """Cœurs plus étroits que le corpus (``plafond − noise_amp < 3``) :
    chaque côté reste ≥ ``width_floor / 2`` (largeur ≥ 6 blocs) tant que le
    plafond le permet (cœur ≥ 7) ; en deçà, chaque côté vaut le plafond
    (largeur = cœur − 1), comme le clip de v1 ; jamais au-dessus du plafond."""
    for name in ("par 4 droit", "par 3 étroit", "par 5, 2 coudes"):
        hole = dataclasses.replace(ff.FABRICATED[name], width=width)
        axis, cap = fw.Axis.of(hole), fw.cap_half(hole)
        for spec in _ratios(style):
            floor = min(spec.width_floor / 2.0, cap)
            neck = fw.profile_neck(hole, axis, spec, fairway_rng(5, hole.order), cap)
            sides = np.concatenate((neck.left, neck.right))
            assert sides.min() >= floor and sides.max() <= cap, (name, spec.neck_ratio)
            if cap < spec.width_floor / 2.0:
                assert (sides == cap).all(), (name, spec.neck_ratio)
    links = fw.FAIRWAY_STYLES["links"]
    assert fw.cap_half(hole) - links.noise_amp < links.width_floor / 2.0


def test_width_floor_corpus():
    """Instantané 30x2 (1080 trous), deux styles : plafond toujours au
    moins le plancher (cœurs ≥ 10), chaque côté de la forme de production
    dans ``[width_floor / 2, plafond]``, largeur ≥ 6 blocs avant le profil en
    long."""
    snapshot = json.loads((DATA / "dressing_holes_30x2.json").read_text(encoding="utf-8"))
    holes = 0
    for c in snapshot["courses"]:
        for raw in c["holes"]:
            hole = ElasticHole.from_dict(raw)
            axis, cap = fw.Axis.of(hole), fw.cap_half(hole)
            for style, spec in fw.FAIRWAY_STYLES.items():
                assert cap - spec.noise_amp >= spec.width_floor / 2.0
                neck = fw.profile_neck(hole, axis, spec, fairway_rng(c["seed"], hole.order), cap)
                sides = np.concatenate((neck.left, neck.right))
                assert sides.min() >= spec.width_floor / 2.0, (c["seed"], hole.order, style)
                assert sides.max() <= cap, (c["seed"], hole.order, style)
                holes += 1
    assert holes == 1080 * len(fw.FAIRWAY_STYLES)


def _profiled(hole, core, style, seed, dressing, **forced):
    hd = dressing[hole.order]
    return fwp.build_profiled_fairway(
        hole, core, fw.FAIRWAY_STYLES[style], fairway_rng(seed, hole.order),
        fairway_profile_rng(seed, hole.order), hd.tees, hd.green.outline,
        fwp.fairway_obstacles(dressing.holes, dressing.green_pairs), **forced)


def test_dress_course_fairway_is_build():
    """Échantillon de l'empreinte (par 3/4/5, avec et sans coude, cœurs
    étroits), deux styles : ``HoleDressing.fairway`` = un polygone, contour de
    ``build_profiled_fairway`` (non arrondi) d'une seule boucle, fermé (pas
    de sommet de fermeture répété, dernière arête au pas du contour), simple
    (aucun croisement d'arêtes), aire signée de ce contour > 0."""
    for seed in (5, 2 ** 64 - 1):
        for style in STYLE_SPECS:
            for label, hole in ff.sample_holes():
                core = build_hole_geometry(hole).core
                dressing = dress_course(_holes_only((hole,)), seed=seed, style=style)
                (shape,) = dressing[hole.order].fairway
                build = _profiled(hole, core, style, seed, dressing)
                outline = np.array(shape.outline)
                case = (label, style, seed)
                assert build.loops == 1, case
                assert np.array_equal(outline, build.outline), case
                assert shape.area == shoelace(outline) > 0.0, case
                steps = np.hypot(*np.diff(np.vstack((outline, outline[:1])), axis=0).T)
                assert len(outline) >= 8 and steps.min() > 0.0, case
                assert steps[-1] <= 1.5 * fw.OUTLINE_STEP, case
                assert is_simple(outline), case


def test_profile_keeps_shape_draws():
    """Ni le col marqué ni le profil en long ne consomment de tirage en plus
    dans le flux de forme : après ``build_profiled_fairway``, ``fairway_rng``
    est au même point qu'après la forme brute B v1 ``build_fairway`` (zones
    identiques), profil avant bruit de ``profile_neck`` ; forcer les choix ne
    change aucun tirage du flux du profil."""
    for label, hole in ff.sample_holes():
        core = build_hole_geometry(hole).core
        for style in STYLE_SPECS:
            spec = fw.FAIRWAY_STYLES[style]
            dressing = dress_course(_holes_only((hole,)), seed=5, style=style)
            hd = dressing[hole.order]
            raw_rng, rng, profile_rng = (fairway_rng(5, hole.order), fairway_rng(5, hole.order),
                                         fairway_profile_rng(5, hole.order))
            raw = fw.build_fairway(hole, core, spec, raw_rng)
            build = fwp.build_profiled_fairway(hole, core, spec, rng, profile_rng, hd.tees,
                                              hd.green.outline)
            assert raw_rng.random() == rng.random(), label
            assert raw.profile.zones == build.profile.zones, label
            neck = fw.profile_neck(hole, fw.Axis.of(hole), spec, fairway_rng(5, hole.order),
                                   fw.cap_half(hole))
            assert np.array_equal(np.interp(neck.s, build.profile.s, build.profile.base),
                                  neck.base), label
            plans = set()
            for carry in (None, True, False):
                for apron in (None, True, False):
                    plan = fwp.long_profile(fairway_profile_rng(5, hole.order), hole.par,
                                           fwp.PROFILE_STYLES[style], carry=carry, apron=apron)
                    plans.add((plan.carry_length, plan.apron_width, plan.apron_length))
            assert len(plans) == 1, label


def test_multi_loop_fairway_raises(monkeypatch):
    """Cas fabriqué : une ligne de niveau à deux boucles n'est jamais
    réduite en silence à la plus grande, ``DressingError`` nomme le trou ;
    dans ``dress_course``, la règle est celle de ``water_fairway`` (avant la
    coupure, ``fairway_outline``)."""
    _, hole = ff.sample_holes()[0]
    core = build_hole_geometry(hole).core
    hd = dress_course(_holes_only((hole,)), seed=5, style="links")[hole.order]
    args = (fairway_profile_rng(5, hole.order), hd.tees, hd.green.outline)
    real = fwp.build_profiled_fairway
    monkeypatch.setattr(fwp, "build_profiled_fairway",
                        lambda *args: dataclasses.replace(real(*args), loops=2))
    with pytest.raises(DressingError, match=rf"trou {hole.order} : fairway en 2 boucles"):
        fwp.fairway_shapes(hole, core, fw.FAIRWAY_STYLES["links"], fairway_rng(5, hole.order),
                          *args)
    real_outline = fww.fairway_outline
    monkeypatch.setattr(fww, "fairway_outline",
                        lambda field, grid: (real_outline(field, grid)[0], 2, 0))
    with pytest.raises(DressingError, match="fairway en 2 boucles"):
        dress_course(_holes_only((hole,)), seed=5, style="links")


def test_no_loop_fairway_raises(monkeypatch):
    """Cas fabriqué : une ligne de niveau sans boucle lève la même
    ``DressingError`` (et non la ``ValueError`` de ``max`` sur une liste
    vide)."""
    _, hole = ff.sample_holes()[0]
    core = build_hole_geometry(hole).core
    hd = dress_course(_holes_only((hole,)), seed=5, style="links")[hole.order]
    args = (fairway_profile_rng(5, hole.order), hd.tees, hd.green.outline)
    monkeypatch.setattr(fwp, "strip_field", lambda axis, profile, grid, cap: grid.blank())
    with pytest.raises(DressingError, match=rf"trou {hole.order} : fairway en 0 boucles"):
        fwp.fairway_shapes(hole, core, fw.FAIRWAY_STYLES["links"], fairway_rng(5, hole.order),
                          *args)
    with pytest.raises(DressingError, match="fairway en 0 boucles"):
        dress_course(_holes_only((hole,)), seed=5, style="links")


# --- îlots sous la résolution ---------------------------------------------------------

R3E_RANGE = (12.0, 35.0)        # PAIR_DISTANCE de R3a à R3e (fixture ``production``)
# Cas réels (plage 12–35, ``green_pairs_layouts.json``, links) : le bord du
# fairway rase en biais la garde du green double du trou lui-même ; un nœud
# reste sous 0, isolé par la selle de ``marching_squares``.
ISLAND_CASES = (("rc-30", "muirfield", 8, 2, 13), ("land-30", "muirfield_inverse", 26, 3, 7))


@pytest.mark.parametrize("round_, pattern, layout_seed, seed, order", ISLAND_CASES)
def test_real_islands_are_removed(round_, pattern, layout_seed, seed, order, monkeypatch):
    """Deux boucles, dont un îlot d'un nœud (aire < ``GRID_STEP``²) près du
    green double du trou : retiré, compté (``islands``), une boucle réelle ;
    contour = grande boucle rééchantillonnée, inchangée, celui de
    ``dress_course``."""
    monkeypatch.setattr(pairs_module, "PAIR_DISTANCE", R3E_RANGE)
    case = next(c for c in json.loads((DATA / "green_pairs_layouts.json").read_text(
        encoding="utf-8"))["layouts"]
        if (c["round"], c["pattern"], c["seed"]) == (round_, pattern, layout_seed))
    layout = CourseLayout.from_dict(case["layout"])
    dressing = dress_course(SimpleNamespace(layout=layout), seed=seed, style="links")
    assert any(order in (p.i, p.j) and p.outline for p in dressing.green_pairs)
    hole = next(h for h in layout.holes if h.order == order)
    core = np.asarray(build_hole_geometry(hole).core, dtype=float)
    hd = dressing[order]
    built = fwp.profiled_field(hole, core, fw.FAIRWAY_STYLES["links"], fairway_rng(seed, order),
                               fairway_profile_rng(seed, order), hd.tees, hd.green.outline,
                               fwp.fairway_obstacles(dressing.holes, dressing.green_pairs))
    loops = marching_squares(built.field, (built.grid.xs[0], built.grid.ys[0]), fw.GRID_STEP)
    islands = [loop for loop in loops if fw.is_island(loop, built.field, built.grid)]
    assert len(loops) == 2 and len(islands) == 1
    assert shoelace(islands[0]) < fw.GRID_STEP ** 2
    build = _profiled(hole, core, "links", seed, dressing)
    assert (build.loops, build.islands) == (1, 1)
    assert np.array_equal(build.outline, resample(max(loops, key=shoelace), fw.OUTLINE_STEP))
    assert np.array_equal(build.outline, np.array(hd.fairway[0].outline))


def _with_blob(monkeypatch, blob: str):
    """Ajoute au champ, après le contournement, une tache loin du fairway
    (fenêtre entièrement à ``BIG``) : ``"ilot"`` un nœud, ``"1x2"`` deux
    nœuds, ``"3x3"`` neuf ; ``"trou"`` : un nœud extérieur au milieu du
    fairway (``"trou0"`` : champ exactement 0, boucle dégénérée dont le
    cadre ne contient aucun nœud). Couronne d'un nœud à +0,5, nœuds de la
    tache à −0,5."""
    real = fwp.clear_obstacles

    def clear(field, grid, obstacles, order):
        bitten = real(field, grid, obstacles, order)
        if blob in ("trou", "trou0"):
            inside = np.argwhere(field < 0.0)
            iy, ix = next((y, x) for y, x in inside
                          if (field[y - 1:y + 2, x - 1:x + 2] < -0.25).all())
            field[iy, ix] = 0.5 if blob == "trou" else 0.0
            return bitten
        h, w = {"ilot": (1, 1), "1x2": (1, 2), "3x3": (3, 3)}[blob]
        far = field >= fw.BIG
        iy, ix = next((y, x) for y in range(1, far.shape[0] - h - 2)
                      for x in range(1, far.shape[1] - w - 2)
                      if far[y:y + h + 2, x:x + w + 2].all())
        field[iy:iy + h + 2, ix:ix + w + 2] = 0.5
        field[iy + 1:iy + h + 1, ix + 1:ix + w + 1] = -0.5
        return bitten

    monkeypatch.setattr(fwp, "clear_obstacles", clear)


def _sample_args(seed=5):
    _, hole = ff.sample_holes()[0]
    core = np.asarray(build_hole_geometry(hole).core, dtype=float)
    dressing = dress_course(_holes_only((hole,)), seed=seed, style="links")
    return hole, core, dressing


def test_fabricated_island_is_removed(monkeypatch):
    """Cas fabriqué : un nœud isolé sous 0, loin du fairway, est retiré et
    compté ; contour et polygone de ``fairway_shapes`` inchangés."""
    hole, core, dressing = _sample_args()
    before = _profiled(hole, core, "links", 5, dressing)
    assert (before.loops, before.islands) == (1, 0)
    _with_blob(monkeypatch, "ilot")
    after = _profiled(hole, core, "links", 5, dressing)
    assert (after.loops, after.islands) == (1, 1)
    assert np.array_equal(after.outline, before.outline)
    hd = dressing[hole.order]
    (shape,) = fwp.fairway_shapes(hole, core, fw.FAIRWAY_STYLES["links"],
                                  fairway_rng(5, hole.order), fairway_profile_rng(5, hole.order),
                                  hd.tees, hd.green.outline,
                                  fwp.fairway_obstacles(dressing.holes, dressing.green_pairs))
    assert shape == hd.fairway[0]


@pytest.mark.parametrize("blob", ["1x2", "3x3", "trou", "trou0"])
def test_real_second_piece_still_raises(blob, monkeypatch):
    """Cas fabriqués : un second morceau de plus d'un nœud (deux nœuds ;
    neuf, aire au-dessus de celle de tout îlot, 2 ``GRID_STEP``²) ou un trou
    d'un nœud dans le fairway, y compris à champ exactement 0 (boucle
    dégénérée, cadre sans nœud), n'est pas un îlot : deux boucles réelles,
    ``DressingError``."""
    hole, core, dressing = _sample_args()
    _with_blob(monkeypatch, blob)
    build = _profiled(hole, core, "links", 5, dressing)
    assert (build.loops, build.islands) == (2, 0)
    if blob == "3x3":
        built = fwp.profiled_field(
            hole, core, fw.FAIRWAY_STYLES["links"], fairway_rng(5, hole.order),
            fairway_profile_rng(5, hole.order), dressing[hole.order].tees,
            dressing[hole.order].green.outline)
        loops = marching_squares(built.field, (built.grid.xs[0], built.grid.ys[0]),
                                 fw.GRID_STEP)
        assert min(shoelace(loop) for loop in loops) > 2.0 * fw.GRID_STEP ** 2
    with pytest.raises(DressingError, match=rf"trou {hole.order} : fairway en 2 boucles"):
        dress_course(_holes_only((hole,)), seed=5, style="links")


def test_is_island_threshold():
    """Seuil lié à la résolution : un nœud intérieur entouré (``ISLAND_NODES``
    = 1), quelle que soit sa valeur ; pas deux, pas un nœud extérieur, pas
    une boucle dégénérée dont le cadre ne contient aucun nœud (champ
    exactement 0)."""
    assert fw.ISLAND_NODES == 1
    grid = fw.Grid(np.arange(7) * fw.GRID_STEP, np.arange(7) * fw.GRID_STEP)
    for depth in (-1e-6, -0.5, -1e6):
        field = grid.blank()
        field[2:5, 2:5] = 0.5
        field[3, 3] = depth
        (loop,) = marching_squares(field, (0.0, 0.0), fw.GRID_STEP)
        assert fw.is_island(loop, field, grid)
        assert shoelace(loop) < 2.0 * fw.GRID_STEP ** 2
        outline, loops, islands = fw.fairway_outline(field, grid)
        assert (outline.shape, loops, islands) == ((0, 2), 0, 1)
    field = grid.blank()
    field[2:5, 2:6] = 0.5
    field[3, 3:5] = -1e-6
    (loop,) = marching_squares(field, (0.0, 0.0), fw.GRID_STEP)
    assert not fw.is_island(loop, field, grid)
    field = np.full((7, 7), -0.5)
    field[3, 3] = 0.5
    field[0, :] = field[-1, :] = field[:, 0] = field[:, -1] = 0.5
    loops = marching_squares(field, (0.0, 0.0), fw.GRID_STEP)
    hole_loop = min(loops, key=shoelace)
    assert len(loops) == 2 and not fw.is_island(hole_loop, field, grid)
    field[3, 3] = 0.0
    loops = marching_squares(field, (0.0, 0.0), fw.GRID_STEP)
    hole_loop = min(loops, key=shoelace)
    assert len(loops) == 2 and np.ptp(hole_loop, axis=0).max() == 0.0
    assert not fw.is_island(hole_loop, field, grid)
    assert fw.fairway_outline(field, grid)[1:] == (2, 0)


# --- invariants sur le corpus ------------------------------------------------------------

# Écart garanti aux obstacles (garde ``margin`` R, distance d au bord du
# polygone, h = ``GRID_STEP``, c = pas du contour). Dans le champ, tout nœud
# intérieur (< 0) a d > R (``clear_obstacles`` : champ ≥ R − d). d est le
# minimum des distances d_e aux arêtes e, chacune convexe, de dérivée
# seconde ≤ 1 / d_e le long d'une droite.
# 1. Point P de la ligne de niveau sur une arête de grille AB (A intérieur) :
#    l'interpolation linéaire du champ s'y annule, donc celle de R − d_e
#    est ≤ 0 pour tout e ; la corde de d_e passe au plus h²/8 · max(1/d_e)
#    au-dessus de d_e, et d_e ≥ d(A) − h > R − h sur AB :
#    d(P) ≥ r1 = R − h² / (8 (R − h)).
# 2. Corde d'une case (≤ h√2) entre deux tels points, à r1 au moins de tout
#    point s du bord : d ≥ √(r1² − h²/2) =: r2 (corde d'un disque de centre s).
#    ``grid_gap_bound`` = R − r2 (ligne de niveau brute, déduite de h seul).
# 3. Contour de production : ``resample`` au pas ``OUTLINE_STEP``, sommets
#    sur la ligne brute, cordes ≤ c = 17/16 · OUTLINE_STEP (``max(8,
#    round(longueur / pas))`` sommets) : d ≥ √(r2² − c²/4).
#    ``outline_gap_bound`` = R − ce minimum.
# Obstacle hors de la fenêtre, ou nœud hors de la bande de la distance
# (±inf, plafond ``BIG``) : d > R + h, rien à borner.
# Valeurs (h = 0,5, pas 1) : ligne brute 0,132 (R = 1) / 0,053 (R = 2) ;
# contour 0,313 / 0,127. Le rééchantillonnage domine pour les greens.
GAP_TOLERANCE = 0.15
# ``GAP_TOLERANCE`` : plancher MESURÉ au R3 sur le contour de production
# (pire écart 0,872 pour une garde de 1, corpus de l'outil), plus serré que
# la borne garantie des greens (0,313) : gardé tel quel, non assoupli ; la
# borne garantie s'applique là où elle est plus serrée (départs, 0,127).


def grid_gap_bound(margin: float) -> float:
    """Déficit garanti de la ligne de niveau brute sous la garde ``margin``
    (étapes 1–2 ci-dessus, ``GRID_STEP`` seul)."""
    h = fw.GRID_STEP
    r1 = margin - h * h / (8.0 * (margin - h))
    return margin - math.sqrt(r1 * r1 - h * h / 2.0)


def outline_gap_bound(margin: float) -> float:
    """Déficit garanti du contour de production (étape 3 en plus)."""
    r2 = margin - grid_gap_bound(margin)
    c = 17.0 / 16.0 * fw.OUTLINE_STEP
    return margin - math.sqrt(r2 * r2 - c * c / 4.0)


def test_gap_bounds_values():
    assert grid_gap_bound(1.0) == pytest.approx(0.1317, abs=1e-4)
    assert grid_gap_bound(2.0) == pytest.approx(0.0527, abs=1e-4)
    assert outline_gap_bound(1.0) == pytest.approx(0.3132, abs=1e-4)
    assert outline_gap_bound(2.0) == pytest.approx(0.1265, abs=1e-4)
    assert fwp.GREEN_MARGIN == 1.0 and fwp.TEE_MARGIN == 2.0


def _near(outline: np.ndarray, obstacle) -> bool:
    """Préfiltre EXACT : cadre du contour hors du cadre de l'obstacle élargi
    de sa garde ⇒ écart > garde (rien à vérifier)."""
    lo, hi = outline.min(axis=0), outline.max(axis=0)
    return bool((lo <= obstacle.hi).all() and (hi >= obstacle.lo).all())


def _check_gaps(raw: np.ndarray, outline: np.ndarray, obstacles, order: int, case) -> Counter:
    """Écarts de la ligne brute et du contour à TOUS les obstacles du
    parcours (green, boîtes, green double du trou ; greens, boîtes et paires
    des autres trous, « voisin ») ; renvoie le compte vérifié par sorte."""
    seen = Counter()
    for obstacle in obstacles:
        if not _near(outline, obstacle) and not _near(raw, obstacle):
            continue
        kind = obstacle.kind if order in obstacle.owners else "voisin"
        margin = obstacle.margin
        assert polygon_gap_np(raw, obstacle.outline) >= margin - grid_gap_bound(margin), \
            (case, kind)
        tolerance = min(GAP_TOLERANCE, outline_gap_bound(margin))
        assert polygon_gap_np(outline, obstacle.outline) >= margin - tolerance, (case, kind)
        seen[kind] += 1
    return seen


# Trous de greens doubles du corpus des tests, par style (instantané 30x2 :
# aucun ; ``green_pair_r3f_layout.json`` : trois paires en links, une en
# parkland, seed 2**64 − 1) ; minimums fixes, cas parkland compris.
PAIRED_MIN = {"links": 6, "parkland": 2}


def test_core_check_corpus(dressed):
    """Instantané 30x2 (1080 trous) et layouts des paires, deux styles : un
    polygone, une seule boucle réelle (``fairway_outline``, comme en
    production), dans le cœur (``core_check`` : aucun dépassement, aucun
    croisement), aire positive ; aucun recouvrement des
    boîtes, du green ni du green double du trou, ni des greens, boîtes et
    paires des AUTRES trous, écarts au moins égaux aux gardes à la borne
    près (``_check_gaps``) ; trous de greens doubles au moins
    ``PAIRED_MIN`` par style ; tout carry tiré mais nul est signalé
    (``clamped``)."""
    holes = 0
    paired, pair_checked, seen = Counter(), Counter(), Counter()
    for label, result, seed, style, dressing in dressed:
        by_order = {h.order: h for h in result.layout.holes}
        obstacles = fwp.fairway_obstacles(dressing.holes, dressing.green_pairs)
        for order, hd in dressing.holes.items():
            hole = by_order[order]
            case = (label, style, order)
            core = np.asarray(build_hole_geometry(hole).core, dtype=float)
            assert len(hd.fairway) == 1 and isinstance(hd.fairway[0], FairwayShape)
            outline = np.array(hd.fairway[0].outline)
            built = fwp.profiled_field(
                hole, core, fw.FAIRWAY_STYLES[style], fairway_rng(seed, order),
                fairway_profile_rng(seed, order), hd.tees, hd.green.outline, obstacles)
            prod, loops, _ = fw.fairway_outline(built.field, built.grid)
            assert loops == 1, case
            assert np.array_equal(prod, outline), case
            raw = max((loop for loop in marching_squares(
                built.field, (built.grid.xs[0], built.grid.ys[0]), fw.GRID_STEP)
                if not fw.is_island(loop, built.field, built.grid)), key=shoelace)
            assert np.array_equal(resample(raw, fw.OUTLINE_STEP), outline), case
            assert hd.fairway[0].area > 0.0
            check = core_check(outline, core)
            assert check["ok"], (case, check)
            gaps = _check_gaps(raw, outline, obstacles, order, case)
            seen += gaps
            pair_checked[style] += gaps["paire"]
            if built.plan.carry and built.span.carry == 0.0:
                assert built.span.clamped, case
            paired[style] += any(order in (p.i, p.j) and p.outline for p in dressing.green_pairs)
            holes += 1
    assert holes == LOT1_CASES * 18 * len(STYLE_SPECS)
    for style in STYLE_SPECS:
        assert paired[style] >= PAIRED_MIN[style], (style, paired)
        assert pair_checked[style] >= PAIRED_MIN[style], (style, pair_checked)
    assert seen["green"] >= holes and seen["departs"] > 0, seen


def fairway_crossings(dressing) -> tuple[list, Counter]:
    """Fairways coupés par le green ou un green double d'un AUTRE trou
    (écart bord à bord nul, ``polygon_gap_np``) : ``[(trou, sorte, autre)]``,
    et le compte des couples vérifiés (cadres qui se touchent) par sorte."""
    crossed, checked = [], Counter()
    others = [("green", (o,), np.asarray(hd.green.outline, dtype=float))
              for o, hd in dressing.holes.items()]
    others += [("paire", (p.i, p.j), np.asarray(p.outline, dtype=float))
               for p in dressing.green_pairs if p.outline]
    for order, hd in dressing.holes.items():
        for shape in hd.fairway:
            outline = np.asarray(shape.outline, dtype=float)
            lo, hi = outline.min(axis=0), outline.max(axis=0)
            for kind, owners, polygon in others:
                if order in owners:
                    continue
                if (polygon.min(axis=0) > hi).any() or (polygon.max(axis=0) < lo).any():
                    continue
                checked[kind] += 1
                if polygon_gap_np(outline, polygon) <= 0.0:
                    crossed.append((order, kind, owners))
    return crossed, checked


def test_no_other_green_crosses_fairway(dressed):
    """Interdiction (décision utilisateur) : aucun green ni green double d'un
    autre trou ne coupe un fairway, instantané 30x2 et layouts des paires
    (plage de production) ; la fixture élargie 12–35 :
    ``tests/test_dressing_pair_shape.py``."""
    checked = Counter()
    for label, _, _, style, dressing in dressed:
        crossed, seen = fairway_crossings(dressing)
        assert crossed == [], (label, style, crossed)
        checked += seen
    assert checked["green"] > 0, checked        # aucune paire d'un autre trou à portée


def test_parkland_green_pair_is_cleared():
    """Cas parkland connu (``green_pair_r3f_layout.json``, seed 2**64 − 1) :
    un green double, que le fairway de chacun de ses deux trous contourne
    (« paire » mordue), écart à la borne près."""
    (case,) = json.loads((DATA / "green_pair_r3f_layout.json").read_text(encoding="utf-8")
                         )["layouts"]
    layout = CourseLayout.from_dict(case["layout"])
    seed = 2 ** 64 - 1
    dressing = dress_course(SimpleNamespace(layout=layout), seed=seed, style="parkland")
    (pair,) = dressing.green_pairs
    assert pair.outline
    obstacles = fwp.fairway_obstacles(dressing.holes, dressing.green_pairs)
    for order in (pair.i, pair.j):
        hole = next(h for h in layout.holes if h.order == order)
        build = _profiled(hole, build_hole_geometry(hole).core, "parkland", seed, dressing)
        assert "paire" in build.bitten, order
        assert np.array_equal(build.outline, np.array(dressing[order].fairway[0].outline))
        tolerance = min(GAP_TOLERANCE, outline_gap_bound(fwp.GREEN_MARGIN))
        assert polygon_gap_np(build.outline, pair.outline) >= fwp.GREEN_MARGIN - tolerance


def test_deterministic(dressed):
    for label, result, seed, style, dressing in dressed[::17]:
        assert dress_course(result, seed=seed, style=style) == dressing, label


# --- flux séparé et lot 1 inchangé ---------------------------------------------------------

def test_fairway_stream():
    assert FAIRWAY_STREAM == 3
    for seed in (0, 7, 2 ** 64 - 1):
        expected = np.random.default_rng([seed, RNG_LABEL, 4, 3]).random(4)
        assert np.array_equal(fairway_rng(seed, 4).random(4), expected)
        assert not np.array_equal(fairway_rng(seed, 4).random(4), tee_rng(seed, 4).random(4))


def test_profile_stream():
    """Flux du profil ``[seed, RNG_LABEL, order, 4]``, distinct de celui de
    la forme (3) et des départs (1)."""
    assert PROFILE_STREAM == 4
    for seed in (0, 7, 2 ** 64 - 1):
        expected = np.random.default_rng([seed, RNG_LABEL, 4, 4]).random(4)
        assert np.array_equal(fairway_profile_rng(seed, 4).random(4), expected)
        assert not np.array_equal(fairway_profile_rng(seed, 4).random(4),
                                  fairway_rng(seed, 4).random(4))
        assert not np.array_equal(fairway_profile_rng(seed, 4).random(4),
                                  tee_rng(seed, 4).random(4))


def test_changing_profile_stream_moves_only_the_profile(dressed, monkeypatch):
    """Autre flux du profil : lot 1 inchangé, forme brute (zones, profil
    avant bruit) inchangée, et au moins un fairway qui change."""
    sample = dressed[::23]
    with monkeypatch.context() as patch:
        patch.setattr(course_module, "fairway_profile_rng",
                      lambda seed, order: np.random.default_rng([seed, RNG_LABEL, order, 99]))
        moved = False
        for label, result, seed, style, dressing in sample:
            other = dress_course(result, seed=seed, style=style)
            assert _lot1_parts(other) == _lot1_parts(dressing), label
            moved |= any(other[o].fairway != hd.fairway for o, hd in dressing.holes.items())
    assert moved


def test_lot1_identical_to_before_fairway(dressed):
    """Greens, départs, causes, paires et rejets : au bit près ceux d'avant
    le branchement du fairway."""
    assert len(dressed) == LOT1_CASES * len(STYLE_SPECS)
    assert _lot1_digest(dressed) == LOT1_DIGEST


def test_changing_fairway_moves_nothing_else(dressed, monkeypatch):
    """Fairway retiré, ou styles de fairway échangés : greens, départs et
    paires inchangés ; le fairway, lui, change."""
    sample = [row for row in dressed if row[4].green_pairs or row[4].pair_rejections][:6]
    sample += dressed[::29]
    assert any(row[4].green_pairs for row in sample)
    swapped = {"links": fw.FAIRWAY_STYLES["parkland"], "parkland": fw.FAIRWAY_STYLES["links"]}
    for variant in ("sans", "échangé"):
        with monkeypatch.context() as patch:
            if variant == "sans":
                patch.setattr(course_module, "water_fairway",
                              lambda *args: fww.WaterFairway(
                                  shapes=(), removed=(), bitten=False, changed=False,
                                  drowned=False, islands=0, wet_area=0.0))
            else:
                patch.setattr(course_module, "FAIRWAY_STYLES", swapped)
            for label, result, seed, style, dressing in sample:
                other = dress_course(result, seed=seed, style=style)
                assert _lot1_parts(other) == _lot1_parts(dressing), (variant, label)
                assert any(other[o].fairway != hd.fairway for o, hd in dressing.holes.items())


def test_styles_cover_style_specs():
    assert set(fw.FAIRWAY_STYLES) == set(STYLE_SPECS) == set(fwp.PROFILE_STYLES)
    assert all(spec.name == name for name, spec in fw.FAIRWAY_STYLES.items())
    assert all(spec.name == name for name, spec in fwp.PROFILE_STYLES.items())


# --- profil en long : mécanique ----------------------------------------------------------

PAR4 = ff.FABRICATED["par 4 droit"]
PAR3 = ff.FABRICATED["par 3 étroit"]


def _plan(**kwargs):
    base = dict(carry=False, apron=False, carry_length=12.0, apron_width=6.5,
                apron_length=10.0, to_apron=False)
    return fwp.LongProfile(**{**base, **kwargs})


def test_span_rules():
    """Continu : bout à ``TEE_MARGIN`` devant la boîte la plus avancée ;
    carry : ``carry_length`` de plus ; par 3 jusqu'à l'avant-green :
    ``carry_length`` de fairway devant le green ; carry trop long réduit à
    ``MIN_FAIRWAY`` de fairway (signalé) ; carry tiré mais nul faute de
    place, ou par 3 dont le fairway gardé déborde sur les départs : nul et
    signalé lui aussi (``clamped`` dès que le carry est plus court que
    visé) ; fin à ``END_WRAP`` après le front du green, bornée par l'axe."""
    axis = fw.Axis.of(PAR4)
    span = fwp.fairway_span(axis, _plan(), 10.0, 120.0)
    assert (span.start, span.end, span.carry, span.clamped) == (
        10.0 + fwp.TEE_MARGIN, 120.0 + fwp.END_WRAP, 0.0, False)
    span = fwp.fairway_span(axis, _plan(carry=True), 10.0, 120.0)
    assert span.start == 10.0 + fwp.TEE_MARGIN + 12.0 and span.carry == 12.0
    assert not span.clamped
    span = fwp.fairway_span(axis, _plan(carry=True, to_apron=True), 10.0, 120.0)
    assert span.start == 120.0 - 12.0 and not span.clamped
    span = fwp.fairway_span(axis, _plan(carry=True, carry_length=200.0), 10.0, 120.0)
    assert span.clamped and span.end - span.start == pytest.approx(fwp.MIN_FAIRWAY)
    # carry tiré, mais départs à moins de MIN_FAIRWAY de la fin : carry nul, signalé
    span = fwp.fairway_span(axis, _plan(carry=True), 100.0, 105.0)
    assert (span.start, span.carry, span.clamped) == (100.0 + fwp.TEE_MARGIN, 0.0, True)
    # sans carry tiré, même étendue, rien à signaler
    assert not fwp.fairway_span(axis, _plan(), 100.0, 105.0).clamped
    # par 3 : 12 blocs gardés devant le green, mais départs à 10 du green : carry nul, signalé
    span = fwp.fairway_span(axis, _plan(carry=True, to_apron=True), 10.0, 20.0)
    assert (span.start, span.carry, span.clamped) == (10.0 + fwp.TEE_MARGIN, 0.0, True)
    span = fwp.fairway_span(axis, _plan(), 10.0, axis.length)
    assert span.end == axis.length


def test_par3_carry_option(monkeypatch):
    """Option ``PAR3_CARRY_TO_APRON`` : au par 3, longueur de fairway gardée
    (``par3_fairway``) ; désactivée, carry ordinaire du par 3 ; mêmes
    tirages dans les deux cas."""
    style = fwp.PROFILE_STYLES["parkland"]
    on = fwp.long_profile(np.random.default_rng(3), 3, style)
    monkeypatch.setattr(fwp, "PAR3_CARRY_TO_APRON", False)
    off = fwp.long_profile(np.random.default_rng(3), 3, style)
    assert on.to_apron and not off.to_apron
    assert style.par3_fairway[0] <= on.carry_length <= style.par3_fairway[1]
    assert style.carry[0][0] <= off.carry_length <= style.carry[0][1]
    assert (on.carry, on.apron, on.apron_width) == (off.carry, off.apron, off.apron_width)
    with pytest.raises(ValueError):
        fwp.long_profile(np.random.default_rng(3), 6, style)


@pytest.mark.parametrize("style", sorted(STYLE_SPECS))
@pytest.mark.parametrize("hole", [PAR4, PAR3], ids=["par 4", "par 3"])
def test_forced_ingredients(hole, style):
    """Carry forcé : fairway entièrement au-delà du carry ; avant-green
    forcé : fairway plus étroit devant le green, à la largeur tirée près
    (inchangé s'il est déjà plus étroit : l'avant-green n'élargit jamais)."""
    core = build_hole_geometry(hole).core
    dressing = dress_course(_holes_only((hole,)), seed=5, style=style)
    axis = fw.Axis.of(hole)
    plain = _profiled(hole, core, style, 5, dressing, carry=False, apron=False)
    carried = _profiled(hole, core, style, 5, dressing, carry=True, apron=False)
    apron = _profiled(hole, core, style, 5, dressing, carry=False, apron=True)
    along = (carried.outline - axis.points[0]) @ axis.tangents[0]
    assert carried.span.carry > 0.0
    assert along.min() >= carried.span.start - 0.5
    s = apron.span.green - apron.plan.apron_length / 2.0
    narrow = cut_width(axis, apron.outline, s, hole.width / 2.0)
    wide = cut_width(axis, plain.outline, s, hole.width / 2.0)
    base = 2.0 * float(np.interp(s, apron.profile.s, apron.profile.base))
    if apron.plan.apron_width < base:
        assert narrow < wide
        assert narrow == pytest.approx(apron.plan.apron_width, abs=1.0)
    else:
        # fairway déjà plus étroit que l'avant-green tiré (cœur étroit) : inchangé
        assert narrow == wide
