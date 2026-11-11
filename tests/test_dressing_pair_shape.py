"""Greens doubles, forme et oracle (``golfgen.dressing.pair_shape``,
``golfgen.dressing.pairs.check_green_pairs``, rounds R3c et R3f).

Forme pincée (base de la forme R3f, ``pinched_shape``) : cas construits
(disques, haricots, greens décalés) comparés à une référence par
appartenance de points (enveloppe pincée ∪ greens, calculée ici sans le
module), au col R3c ``max(5,5 ; 0,6 × W)`` (``r3c_w`` : la machinerie de
croisements et ses non-régressions sont testées comme en R3c). Forme de
production R3f (``pair_outline`` : pincée au col ``W`` puis dilatée et
fermée) : greens et drapeaux dedans, dilatation, col ≥ ``W``. Puis chaque
contrôle de l'oracle R3f est mis en échec sur une configuration construite.
Production : paires de ``dress_course`` sur le layout réel R3f (plage de
production) et sur l'instantané de ``tests/test_dressing_pairs.py`` (plage
R3a–R3e [12, 35], pour le nombre de paires)."""

from __future__ import annotations

import json
import math
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from golfgen.dressing import STYLE_SPECS, dress_course
from golfgen.dressing import pair_shape as ps
from golfgen.dressing import pairs as pairs_module
from golfgen.dressing.green import _convex_hull, points_in_polygon, shoelace
from golfgen.dressing.model import GreenPair, GreenShape, HoleDressing, PairRejection, TeeBox
from golfgen.dressing.pairs import (ORACLE_CHECKS, PAIR_GAP, check_green_pairs, footprint,
                                    oracle_failures, shape_and_check, shape_or_reject)
from golfgen.routing.geometry import build_hole_geometry
from golfgen.routing.model import ControlPoint, CourseLayout

SNAPSHOT = Path(__file__).resolve().parent / "data" / "green_pairs_layouts.json"
R3F_LAYOUT = Path(__file__).resolve().parent / "data" / "green_pair_r3f_layout.json"
R3E_RANGE = (12.0, 35.0)        # PAIR_DISTANCE de R3a à R3e
R3C_RATIO = 0.6                 # col R3c : max(NECK_FLOOR, 0,6 × W)
NECK_TOLERANCE = 0.05           # col réel de la forme pincée à 5 % de w (R3b/R3c)


def smaller_width(gi, gj) -> float:
    return min(ps.min_width(gi), ps.min_width(gj))


def r3c_w(gi, gj) -> float:
    """Col de la forme pincée R3c (strictement sous ``W`` sur les cas)."""
    return max(ps.NECK_FLOOR, R3C_RATIO * smaller_width(gi, gj))


def overshoot(shape, hull) -> float:
    """Plus grand dépassement (blocs, ≤ 0 si ``shape`` ⊆ ``hull``) d'un sommet
    de ``shape`` hors de l'enveloppe convexe ``hull``."""
    shape, hull = np.asarray(shape, dtype=float), np.asarray(hull, dtype=float)
    if shoelace(hull) < 0:
        hull = hull[::-1]
    edge = np.roll(hull, -1, axis=0) - hull
    rel = shape[:, None, :] - hull[None, :, :]
    outward = (rel[..., 1] * edge[None, :, 0] - rel[..., 0] * edge[None, :, 1]) \
        / np.hypot(edge[:, 0], edge[:, 1])[None, :]
    return float(-outward.min(axis=1).min())

def disk(cx: float, cy: float, r: float, n: int = 32) -> np.ndarray:
    t = 2.0 * math.pi * np.arange(n) / n
    return np.column_stack((cx + r * np.cos(t), cy + r * np.sin(t)))


def dented(cx: float, cy: float, r: float, toward: float, depth: float = 2.0,
           n: int = 32) -> np.ndarray:
    """Disque creusé (haricot grossier) : creux de ``depth`` blocs centré sur
    la direction ``toward`` (radians)."""
    t = 2.0 * math.pi * np.arange(n) / n
    gap = np.abs((t - toward + math.pi) % (2 * math.pi) - math.pi)
    radius = r - depth * np.clip(1.0 - gap / 0.8, 0.0, 1.0)
    return np.column_stack((cx + radius * np.cos(t), cy + radius * np.sin(t)))


def ellipse(cx, cy, a, b, angle=0.0, n=32):
    t = 2.0 * math.pi * np.arange(n) / n
    x, y = a * np.cos(t), b * np.sin(t)
    c, s = math.cos(angle), math.sin(angle)
    return np.column_stack((cx + c * x - s * y, cy + s * x + c * y))


def reference_inside(points, gi, gj, ci, cj, w):
    """Appartenance à l'enveloppe pincée ∪ greens, sans le module : un point
    ``(s, t)`` est dans l'enveloppe pincée ssi ``(s, t / f(s))`` est dans
    l'enveloppe convexe."""
    ci, cj = np.asarray(ci, float), np.asarray(cj, float)
    d = float(np.linalg.norm(cj - ci))
    u = (cj - ci) / d
    n = np.array((-u[1], u[0]))
    m = 0.5 * (ci + cj)
    hull = _convex_hull(np.concatenate((gi, gj)))
    s = (points - m) @ u
    t = (points - m) @ n
    probe = m + np.outer(np.linspace(-50, 50, 20001), n)
    inside = points_in_polygon(probe, hull)
    w0 = inside.sum() * (100.0 / 20000)
    depth = 1.0 - min(w / w0, 1.0)
    f = np.where(np.abs(s) < d / 2, 1.0 - depth * np.cos(math.pi * s / d) ** 2, 1.0)
    unpinched = m + s[:, None] * u + (t / f)[:, None] * n
    return (points_in_polygon(unpinched, hull) | points_in_polygon(points, gi)
            | points_in_polygon(points, gj))


CASES = {
    "disques egaux": (disk(0, 0, 5), disk(20, 0, 5)),
    "grand-petit": (disk(0, 0, 8), disk(22, 3, 3.6)),
    "petit-grand": (disk(0, 0, 3.6), disk(18, -4, 8)),
    "proches": (disk(0, 0, 5), disk(12.5, 0, 4.5)),
    "haricot vers le partenaire": (dented(0, 0, 6, 0.0), disk(24, 0, 5)),
    "haricot de travers": (dented(0, 0, 6, 1.2, 2.5), dented(26, 5, 5.5, 2.5, 2.0)),
    "ellipses": (ellipse(0, 0, 7, 4, 0.9), ellipse(25, -6, 6, 3.8, -0.4)),
}


@pytest.mark.parametrize("name", CASES)
def test_shape_contains_greens_inside_hull_with_neck_w(name):
    gi, gj = (np.round(g, 2) for g in CASES[name])
    ci, cj = tuple(gi.mean(axis=0)), tuple(gj.mean(axis=0))
    w = r3c_w(gi, gj)
    assert w < smaller_width(gi, gj)
    shape = ps.pinched_shape(gi, gj, ci, cj, w)
    assert shoelace(shape) > 0.0                                   # sens trigonométrique
    assert ps.contains_outline(shape, gi) and ps.contains_outline(shape, gj)
    assert overshoot(shape, footprint(gi, gj)) <= 1e-6
    assert ps.is_simple(shape)
    neck, chord = ps.neck_measure(shape, gi, gj, ci, cj)
    assert chord is not None and abs(neck - w) <= NECK_TOLERANCE * w, (neck, w)
    assert shoelace(shape) < shoelace(np.asarray(footprint(gi, gj)))
    # même région que la référence par appartenance (points à > 0,05 bloc du bord)
    lo, hi = shape.min(axis=0) - 1.0, shape.max(axis=0) + 1.0
    xs, ys = np.meshgrid(np.arange(lo[0], hi[0], 0.137), np.arange(lo[1], hi[1], 0.137))
    points = np.column_stack((xs.ravel(), ys.ravel()))
    far = ps._edge_distances(points, shape) > 0.05
    expected = reference_inside(points[far], gi, gj, ci, cj, w)
    assert (points_in_polygon(points[far], shape) == expected).all(), name


def test_pinch_gives_exactly_w_at_the_middle():
    gi, gj = disk(0, 0, 5), disk(20, 0, 5)
    w = r3c_w(gi, gj)
    shape = ps.pinched_shape(gi, gj, (0.0, 0.0), (20.0, 0.0), w)
    neck, (a, b) = ps.neck_measure(shape, gi, gj, (0.0, 0.0), (20.0, 0.0))
    assert neck == pytest.approx(w, abs=1e-6)
    assert a[0] == pytest.approx(10.0, abs=0.05) and b[0] == pytest.approx(10.0, abs=0.05)


def test_neck_target_ratio_and_floor():
    """R3f : ``w = max(5,5 ; 1,0 × W)`` ; plus de rejet ``w ≥ W`` : sous le
    plancher, la paire se construit au col 5,5 (le col réel est vérifié par
    l'oracle, ≥ ``W``)."""
    assert (ps.NECK_RATIO, ps.NECK_FLOOR, ps.DILATION, ps.CLOSING) == (1.0, 5.5, 1.5, 3.0)
    w, smaller = ps.neck_target(disk(0, 0, 6), disk(20, 0, 4))
    assert smaller == pytest.approx(8.0 * math.cos(math.pi / 32))
    assert w == smaller
    small = _green(disk(20, 0, 2.5), (20.0, 0.0))
    big = _green(disk(0, 0, 6), (0.0, 0.0))
    w, smaller = ps.neck_target(big.outline, small.outline)
    assert smaller < w == ps.NECK_FLOOR
    pair = GreenPair(i=1, j=3, distance=20.0, footprint=footprint(big.outline, small.outline))
    shaped = ps.build_pair(pair, big, small)
    assert shaped.neck_width == ps.NECK_FLOOR and len(shaped.outline) > 8


def test_overlapping_greens_are_refused():
    with pytest.raises(ps.PairShapeError):
        ps.pinched_shape(disk(0, 0, 5), disk(8, 0, 5), (0.0, 0.0), (8.0, 0.0), 5.5)


def test_neck_measure_uses_the_component_on_the_axis():
    """Un lobe séparé du col par du vide ne compte pas dans la coupe
    (``chord_length`` donnerait l'étendue extrême)."""
    # col de 2 (|t| ≤ 1) de x = 4 à 16, lobe isolé au-dessus (t de 3 à 5) de x = 8 à 12
    shape = np.array(((-2, -3), (4, -3), (4, -1), (16, -1), (16, -3), (22, -3), (22, 3),
                      (16, 3), (16, 1), (12, 1), (12, 5), (8, 5), (8, 3.0), (11, 3.0),
                      (11, 1), (4, 1), (4, 3), (-2, 3)), dtype=float)
    gi = np.array(((-1, -2), (3, -2), (3, 2), (-1, 2)), dtype=float)
    gj = gi + (18.0, 0.0)
    neck, _ = ps.neck_measure(shape, gi, gj, (1.0, 0.0), (19.0, 0.0))
    assert neck == pytest.approx(2.0)


def test_neck_is_not_measurable_when_the_axis_leaves_the_shape():
    """Une coupe entre les greens sans bord d'un côté de l'axe (l'axe sort
    de la forme par une encoche) : col ``inf``, sans extrémités, même si les
    autres coupes sont finies ; l'oracle ``col`` échoue sur cette forme."""
    # haltère : col |t| ≤ 2 de x = 4 à 16, encoche par le bas jusqu'à t = 1
    # entre x = 9 et 11 (l'axe t = 0 y sort de la forme)
    shape = np.array(((-2, -3), (4, -3), (4, -2), (9, -2), (9, 1), (11, 1), (11, -2),
                      (16, -2), (16, -3), (22, -3), (22, 3), (16, 3), (16, 2), (4, 2),
                      (4, 3), (-2, 3)), dtype=float)
    gi = np.array(((-1, -2), (3, -2), (3, 2), (-1, 2)), dtype=float)
    gj = gi + (18.0, 0.0)
    assert ps.is_simple(shape)
    assert ps.neck_measure(shape, gi, gj, (1.0, 0.0), (19.0, 0.0)) == (math.inf, None)
    whole = shape[[0, 1, 2, 7, 8, 9, 10, 11, 12, 13, 14, 15]]          # sans encoche
    neck, ends = ps.neck_measure(whole, gi, gj, (1.0, 0.0), (19.0, 0.0))
    assert neck == pytest.approx(4.0) and ends is not None


def test_oracle_col_fails_when_the_axis_leaves_the_shape():
    """Configuration de base, forme rectangulaire contenant les deux greens
    avec une encoche par le bas qui coupe l'axe des centres (y = 50) entre
    eux : ``inclusion`` passe, ``col`` échoue (col ``inf``)."""
    layout, holes, cores, pair = _config()
    notched = ((44.0, 43.0), (61.0, 43.0), (61.0, 51.0), (63.0, 51.0), (63.0, 43.0),
               (81.0, 43.0), (81.0, 57.0), (44.0, 57.0))
    assert ps.is_simple(notched)
    report = check_green_pairs(layout, holes, (_replace(pair, outline=notched),), cores)[(1, 3)]
    ok, (neck, _) = report["col"]
    assert report["inclusion"][0] and not ok and math.isinf(neck)


def test_construction_is_deterministic():
    gi, gj = CASES["haricot de travers"]
    first = ps.pinched_shape(gi, gj, tuple(gi.mean(0)), tuple(gj.mean(0)), 5.5)
    again = ps.pinched_shape(gi.copy(), gj.copy(), tuple(gi.mean(0)), tuple(gj.mean(0)), 5.5)
    assert first.tobytes() == again.tobytes()
    w, _ = ps.neck_target(gi, gj)
    first = ps.pair_outline(gi, gj, tuple(gi.mean(0)), tuple(gj.mean(0)), w)
    again = ps.pair_outline(gi.copy(), gj.copy(), tuple(gi.mean(0)), tuple(gj.mean(0)), w)
    assert first.tobytes() == again.tobytes()


# --- forme de production R3f (variante A) --------------------------------------------

@pytest.mark.parametrize("name", CASES)
def test_production_shape_dilates_the_pinched_base(name):
    """``pair_outline`` : sens trigonométrique, simple, greens et drapeaux
    dedans ; la forme de départ (pincée au col ``W``, ou l'enveloppe) est à
    ``DILATION`` au moins du bord (au pas de grille près) ; la forme dépasse
    l'empreinte d'environ ``DILATION`` ; col réel ≥ ``W`` (proche de ``W`` +
    2 × ``DILATION``) ; contour rééchantillonné au pas
    ``RESAMPLE_STEP``."""
    gi, gj = (np.round(g, 2) for g in CASES[name])
    ci, cj = tuple(gi.mean(axis=0)), tuple(gj.mean(axis=0))
    w, smaller = ps.neck_target(gi, gj)
    shape = ps.pair_outline(gi, gj, ci, cj, w)
    assert shoelace(shape) > 0.0 and ps.is_simple(shape)
    assert ps.contains_outline(shape, gi) and ps.contains_outline(shape, gj)
    assert points_in_polygon(np.array((ci, cj)), shape).all()
    base = ps.base_shape(ps.clean_outline(gi), ps.clean_outline(gj), ci, cj, w)
    dense = ps._densify(base, 0.2)
    assert points_in_polygon(dense, shape).all()
    # flèche du rééchantillonnage (pas 0,5 sur un arc de rayon 1,5) ≈ 0,02
    assert ps._edge_distances(dense, shape).min() >= ps.DILATION - 0.05
    assert overshoot(shape, footprint(gi, gj)) == pytest.approx(ps.DILATION, abs=0.05)
    neck, _ = ps.neck_measure(shape, gi, gj, ci, cj)
    assert neck >= smaller and neck > w + ps.DILATION, (neck, w)
    steps = np.hypot(*(shape - np.roll(shape, -1, axis=0)).T)
    assert steps.max() <= 1.2 * ps.RESAMPLE_STEP


def test_base_is_the_hull_when_the_neck_reaches_the_middle_chord():
    """``w ≥ W0`` (corde de l'enveloppe au milieu des centres) : pas de
    pincement, la forme de départ est l'enveloppe ; juste en dessous, la
    forme pincée (plus petite)."""
    gi, gj = ps.clean_outline(disk(0, 0, 5)), ps.clean_outline(disk(20, 0, 5))
    hull = _convex_hull(np.concatenate((gi, gj)))
    w0 = ps.mid_chord(hull, (0.0, 0.0), (20.0, 0.0))
    assert w0 == pytest.approx(10.0)
    assert np.array_equal(ps.base_shape(gi, gj, (0.0, 0.0), (20.0, 0.0), w0), hull)
    pinched = ps.base_shape(gi, gj, (0.0, 0.0), (20.0, 0.0), w0 - 1.0)
    assert shoelace(pinched) < shoelace(hull)


def test_overlapping_greens_are_refused_by_the_production_shape():
    with pytest.raises(ps.GreensOverlapError):
        ps.pair_outline(disk(0, 0, 5), disk(8, 0, 5), (0.0, 0.0), (8.0, 0.0), 20.0)


def test_smoothing_in_several_loops_is_a_construction_failure(monkeypatch):
    gi, gj = disk(0, 0, 5), disk(20, 0, 5)
    real = ps.offset_closing
    monkeypatch.setattr(ps, "offset_closing", lambda *a: (real(*a)[0], 2))
    with pytest.raises(ps.PairShapeError, match="2 boucles"):
        ps.pair_outline(gi, gj, (0.0, 0.0), (20.0, 0.0), 9.0)


# --- oracle sur une configuration construite ---------------------------------------

def _green(outline, center) -> GreenShape:
    outline = tuple(map(tuple, np.round(np.asarray(outline, dtype=float), 2).tolist()))
    return GreenShape(outline=outline, center=center, area=shoelace(np.asarray(outline)),
                      target_area=0.0)


def _tee(x, y) -> TeeBox:
    outline = ((x, y), (x + 4, y), (x + 4, y + 2), (x, y + 2))
    return TeeBox(outline=outline, center=(x + 2, y + 1), area=8.0, rank=0, heading=(1.0, 0.0))


def _square(x0, y0, x1, y1):
    return ((x0, y0), (x1, y0), (x1, y1), (x0, y1))


def _config(**change):
    """Paire (1, 3) : greens disques en (50, 50) r 5 et (75, 50) r 4,5 ;
    trou 5 loin ; ``change`` remplace un élément (cœur ou départs du trou 5,
    liaisons, clubhouse, taille de carte)."""
    greens = {1: _green(disk(50, 50, 5), (50.0, 50.0)), 3: _green(disk(75, 50, 4.5), (75.0, 50.0)),
              5: _green(disk(200, 200, 5), (200.0, 200.0))}
    tees = {1: (_tee(50, 150),), 3: (_tee(75, 150),), 5: change.get("tees", (_tee(200, 250),))}
    holes = {o: HoleDressing(order=o, green=g, tees=tees[o]) for o, g in greens.items()}
    cores = {1: _square(40, 40, 60, 60), 3: _square(65, 40, 85, 60),
             5: change.get("core", _square(190, 190, 210, 210))}
    link = lambda a, b, p, q: SimpleNamespace(from_hole_order=a, to_hole_order=b,  # noqa: E731
                                              start=ControlPoint(*p), end=ControlPoint(*q))
    links = (link(1, 2, (50, 50), (50, 150)), link(3, 4, (75, 50), (75, 150)),
             *change.get("links", ()))
    layout = SimpleNamespace(links=links, clubhouse=ControlPoint(*change.get("clubhouse", (250, 250))),
                             width=change.get("width", 300.0), height=300.0)
    pair = GreenPair(i=1, j=3, distance=25.0,
                     footprint=footprint(greens[1].outline, greens[3].outline))
    shaped, cause = shape_and_check(layout, holes, {} if change.get("no_cores") else cores, pair)
    assert cause is None or change, cause
    shaped = shaped or ps.build_pair(pair, greens[1], greens[3])
    return layout, holes, cores, shaped


def _failed(layout, holes, cores, pairs):
    return {name for _, _, name in oracle_failures(check_green_pairs(layout, holes, pairs, cores))}


def test_oracle_passes_on_the_base_configuration():
    layout, holes, cores, pair = _config()
    report = check_green_pairs(layout, holes, (pair,), cores)
    assert tuple(report[(1, 3)]) == ORACLE_CHECKS
    assert oracle_failures(report) == []
    neck, smaller = report[(1, 3)]["col"][1]
    assert pair.neck_width == pytest.approx(smaller) and neck >= smaller


def _replace(pair, **fields):
    data = {k: getattr(pair, k) for k in ("i", "j", "distance", "footprint", "outline",
                                          "neck_width")}
    data.update(fields)
    return GreenPair(**data)


def _scaled(outline, factor):
    shape = np.asarray(outline, dtype=float)
    centre = shape.mean(axis=0)
    return tuple(map(tuple, (centre + factor * (shape - centre)).tolist()))


@pytest.mark.parametrize("check, change", [
    ("coeur", {"core": _square(45, 58, 55, 62)}),                 # 3 blocs au-dessus du green 1
    ("tees", {"tees": (_tee(48, 58),)}),
    ("clubhouse", {"clubhouse": (50, 63)}),
    ("carte", {"width": 78.0}),
    ("liaison_autre", {"links": (SimpleNamespace(
        from_hole_order=5, to_hole_order=6, start=ControlPoint(62, 30),
        end=ControlPoint(62, 70)),)}),
    ("liaison_partenaire", {"links": ()}),
])
def test_oracle_rejects_each_distance_and_link_failure(check, change):
    layout, holes, cores, pair = _config(**change)
    if check == "liaison_partenaire":
        # la liaison 1 → 2 part dans la forme (permis) mais traverse le green 3
        links = (SimpleNamespace(from_hole_order=1, to_hole_order=2, start=ControlPoint(52, 50),
                                 end=ControlPoint(90, 52)),) + layout.links[1:]
        layout = SimpleNamespace(**{**vars(layout), "links": links})
    assert _failed(layout, holes, cores, (pair,)) == {check}


def test_partner_link_may_start_inside_the_shared_shape():
    layout, holes, cores, pair = _config()
    links = (SimpleNamespace(from_hole_order=1, to_hole_order=2, start=ControlPoint(50, 50),
                             end=ControlPoint(62, 80)),) + layout.links[1:]
    layout = SimpleNamespace(**{**vars(layout), "links": links})
    assert _failed(layout, holes, cores, (pair,)) == set()


def _r3c_outline(holes):
    """Forme pincée R3c (col 0,6 × W, sans dilatation) de la paire (1, 3)."""
    g1, g3 = holes[1].green, holes[3].green
    shape = ps.pinched_shape(g1.outline, g3.outline, g1.center, g3.center,
                             r3c_w(g1.outline, g3.outline))
    return tuple(map(tuple, shape.tolist()))


def test_oracle_rejects_a_neck_narrower_than_the_smaller_green():
    """Contrôle ``col`` (R3f) : col réel ≥ ``W``. La forme pincée R3c (col
    0,6 × W) contient les greens mais échoue sur ``col`` seul."""
    layout, holes, cores, pair = _config()
    pinched = _replace(pair, outline=_r3c_outline(holes))
    report = check_green_pairs(layout, holes, (pinched,), cores)
    ok, (neck, smaller) = report[(1, 3)]["col"]
    assert not ok and neck == pytest.approx(R3C_RATIO * smaller, rel=NECK_TOLERANCE)
    assert _failed(layout, holes, cores, (pinched,)) == {"col"}


def test_oracle_col_uses_the_greens_of_the_holes():
    """``W`` recalculé des greens des trous (le plus petit des deux) : deux
    greens plus larges que le col réel de la forme font échouer ``col``."""
    layout, holes, cores, pair = _config()
    wide = {1: _green(disk(50, 50, 6.5), (50.0, 50.0)), 3: _green(disk(75, 50, 7.0), (75.0, 50.0))}
    holes = {o: HoleDressing(order=o, green=wide.get(o, hd.green), tees=hd.tees)
             for o, hd in holes.items()}
    ok, (neck, smaller) = check_green_pairs(layout, holes, (pair,), cores)[(1, 3)]["col"]
    assert not ok and neck < smaller == pytest.approx(ps.min_width(wide[1].outline))


def test_oracle_rejects_a_pin_outside_the_shape():
    """``inclusion`` couvre les drapeaux : un drapeau (``GreenShape.center``)
    hors de la forme la fait échouer, même greens dedans."""
    layout, holes, cores, pair = _config()
    g3 = holes[3].green
    stray = GreenShape(outline=g3.outline, center=(75.0, 64.0), area=g3.area, target_area=0.0)
    holes = {**holes, 3: HoleDressing(order=3, green=stray, tees=holes[3].tees)}
    assert not points_in_polygon(np.array([stray.center]), np.asarray(pair.outline))[0]
    assert "inclusion" in _failed(layout, holes, cores, (pair,))


def test_oracle_rejects_a_shape_missing_a_green():
    layout, holes, cores, pair = _config()
    shape = np.asarray(pair.outline)
    clipped = tuple(map(tuple, shape[shape[:, 0] > 47.0].tolist()))   # coupe le green 1
    assert "inclusion" in _failed(layout, holes, cores, (_replace(pair, outline=clipped),))


def test_oracle_rejects_a_self_crossing_outline():
    layout, holes, cores, pair = _config()
    shape = list(pair.outline)
    k = len(shape) // 4
    shape[k], shape[3 * k] = shape[3 * k], shape[k]
    assert "simple" in _failed(layout, holes, cores, (_replace(pair, outline=tuple(shape)),))


def test_oracle_rejects_two_pairs_closer_than_the_pair_gap():
    layout, holes, cores, pair = _config(no_cores=True)
    offset = -14.0                     # sous la paire (liaisons vers le haut) : écart ≈ 4 < 5
    moved = {7: holes[1], 9: holes[3]}
    for order, hd in moved.items():
        g = hd.green
        green = _green(np.asarray(g.outline) + (0.0, offset), (g.center[0], g.center[1] + offset))
        holes[order] = HoleDressing(order=order, green=green, tees=())
    other = GreenPair(i=7, j=9, distance=25.0,
                      footprint=footprint(holes[7].green.outline, holes[9].green.outline))
    other = ps.build_pair(other, holes[7].green, holes[9].green)
    report = check_green_pairs(layout, holes, (pair, other), {})
    assert {(i, j, n) for i, j, n in oracle_failures(report)} == {
        (1, 3, "ecart_paires"), (7, 9, "ecart_paires")}
    assert report[(1, 3)]["ecart_paires"][1] < PAIR_GAP


def test_shape_and_check_reports_rejection_causes():
    layout, holes, cores, pair = _config(clubhouse=(50, 63))
    bare = GreenPair(i=1, j=3, distance=25.0, footprint=pair.footprint)
    assert shape_and_check(layout, holes, cores, bare) == (None, "oracle:clubhouse")
    # R3f : plus de cause « col_cible » ; un green sous le plancher (W < 5,5)
    # se construit au col 5,5 et passe l'oracle (col réel ≥ W)
    layout, holes, cores, _ = _config()
    small = _green(disk(75, 50, 2.6), (75.0, 50.0))
    holes = {**holes, 3: HoleDressing(order=3, green=small, tees=())}
    shaped, cause = shape_and_check(layout, holes, cores, bare)
    assert cause is None and shaped.neck_width == ps.NECK_FLOOR


# --- géométrie dégénérée et contours d'entrée (R3c retouches) ------------------------

def test_degenerate_geometry_is_a_rejection_with_its_cause():
    """Centres confondus (construction impossible) et greens qui se
    chevauchent : rejet avec la bonne cause, pas d'exception."""
    layout, holes, cores, pair = _config()
    bare = GreenPair(i=1, j=3, distance=25.0, footprint=pair.footprint)
    g3 = holes[3].green
    same_center = GreenShape(outline=g3.outline, center=holes[1].green.center, area=g3.area,
                             target_area=0.0)
    merged = {**holes, 3: HoleDressing(order=3, green=same_center, tees=holes[3].tees)}
    assert shape_or_reject(layout, merged, cores, bare) == (
        None, PairRejection(1, 3, "construction"))
    assert shape_and_check(layout, merged, cores, bare) == (None, "construction")
    overlapping = _green(disk(57, 50, 4.5), (57.0, 50.0))
    merged = {**holes, 3: HoleDressing(order=3, green=overlapping, tees=holes[3].tees)}
    assert shape_or_reject(layout, merged, cores, bare) == (
        None, PairRejection(1, 3, "chevauchement"))


@pytest.mark.parametrize("outline", [((0.0, 0.0), (0.0, 0.0), (0.0, 0.0)),
                                     ((0.0, 0.0), (1.0, 1.0), (0.0, 0.0)),
                                     ((0.0, 0.0), (1.0, 1.0), (2.0, 2.0), (0.0, 0.0))])
def test_degenerate_outline_raises_a_pair_shape_error(outline):
    with pytest.raises(ps.PairShapeError):
        ps.pinched_shape(outline, disk(20, 0, 5), (0.0, 0.0), (20.0, 0.0), 5.5)


@pytest.mark.parametrize("value", [math.nan, math.inf, -math.inf])
@pytest.mark.parametrize("where", [0, 5, -1])
def test_non_finite_outline_is_refused_not_dropped(value, where):
    """Un sommet NaN ou infini est refusé (``PairShapeError``), pas écarté
    sans bruit par le dédoublonnage ; dans la sélection : rejet
    ``construction``."""
    bad = disk(0, 0, 5)
    bad[where] = (value, 0.0)
    with pytest.raises(ps.PairShapeError, match="non fini"):
        ps.clean_outline(bad)
    with pytest.raises(ps.PairShapeError, match="non fini"):
        ps.pinched_shape(disk(20, 0, 5), bad, (20.0, 0.0), (0.0, 0.0), 5.5)
    layout, holes, cores, pair = _config()
    bare = GreenPair(i=1, j=3, distance=25.0, footprint=pair.footprint)
    g3 = holes[3].green
    broken = GreenShape(outline=tuple(map(tuple, (bad + g3.center).tolist())), center=g3.center,
                        area=g3.area, target_area=0.0)
    merged = {**holes, 3: HoleDressing(order=3, green=broken, tees=holes[3].tees)}
    assert shape_or_reject(layout, merged, cores, bare) == (
        None, PairRejection(1, 3, "construction"))


def _with_duplicates(points, how, offset=0.0):
    """Contour avec doublons (copies décalées de ``offset`` : quasi-doublons) :
    point de fermeture, chaque sommet, ou quelques sommets (un triplé). Les
    copies précèdent leur original, sauf la fermeture (après le dernier)."""
    points = np.asarray(points, dtype=float)
    if how == "fermeture":
        return np.vstack((points, points[:1] + offset))
    if how == "tous":
        out = np.repeat(points, 2, axis=0)
        out[::2] += offset
        return out
    return np.insert(points, [3, 3, 11], points[[3, 3, 11]] + offset, axis=0)


@pytest.mark.parametrize("how", ["fermeture", "tous", "isoles"])
@pytest.mark.parametrize("name", CASES)
def test_duplicate_vertices_do_not_change_the_shape(name, how):
    """Sommets consécutifs identiques ou quasi identiques (1e-12 bloc) et
    point de fermeture dupliqué : même forme, au bit près, qu'avec le
    contour propre (entrées nettoyées)."""
    gi, gj = (np.round(g, 2) for g in CASES[name])
    ci, cj = tuple(gi.mean(axis=0)), tuple(gj.mean(axis=0))
    w = r3c_w(gi, gj)
    clean = ps.pinched_shape(gi, gj, ci, cj, w)
    for offset in (0.0, 1e-12):
        dup = ps.pinched_shape(_with_duplicates(gi, how, offset), _with_duplicates(gj, how, offset),
                               ci, cj, w)
        assert np.array_equal(clean, dup), offset
    if how == "isoles":                 # forme de production : mêmes entrées nettoyées
        w, _ = ps.neck_target(gi, gj)
        clean = ps.pair_outline(gi, gj, ci, cj, w)
        dup = ps.pair_outline(_with_duplicates(gi, how), _with_duplicates(gj, how), ci, cj, w)
        assert np.array_equal(clean, dup)


# Scénario de la relecture R3c : greens à coordonnées entières (sommets
# consécutifs dupliqués dans le green i), axe des centres horizontal au bruit
# flottant près (cj = 16·(cos π, sin π)). Le green i dépassait de 0,84 bloc de
# la forme : un échantillon du flanc pincé (s = −5) tombe EXACTEMENT sur
# l'arête verticale x = −3 du green i, et l'abscisse s = −5 y figurait deux
# fois (échantillon régulier et sommet d'enveloppe à 1 ulp près : segment de
# flanc de ~1e-15). Avec le bruit de 2e-15 du repère, le croisement n'était
# compté sur aucun segment. Corrigé (R3c retouches) : abscisses à ON_TOL
# près fusionnées (``_samples``) et prédicats d'orientation partagés entre
# segments voisins (``_crossings``).
CASE_232_I = ((2, 6), (1, 6), (1, 6), (0, 6), (-1, 5), (-2, 5), (-3, 4), (-3, 2), (-4, 1),
              (-4, 0), (-4, -1), (-4, -2), (-4, -4), (-4, -5), (-3, -5), (-3, -6), (-2, -6),
              (-1, -6), (-1, -6), (0, -6), (1, -5), (2, -5), (3, -4), (3, -2), (4, -1), (4, 0),
              (4, 1), (4, 2), (4, 4), (4, 5), (3, 5), (3, 6))
CASE_232_J = ((-11, 0), (-11, 1), (-11, 2), (-12, 3), (-12, 4), (-13, 4), (-14, 5), (-15, 5),
              (-16, 5), (-17, 5), (-18, 5), (-19, 4), (-20, 4), (-20, 3), (-21, 2), (-21, 1),
              (-21, 0), (-21, -1), (-21, -2), (-20, -3), (-20, -4), (-19, -4), (-18, -5),
              (-17, -5), (-16, -5), (-15, -5), (-14, -5), (-13, -4), (-12, -4), (-12, -3),
              (-11, -2), (-11, -1))
CASE_232_CENTERS = ((0.0, 0.0), (16.0 * math.cos(math.pi), 16.0 * math.sin(math.pi)))


def _case_232():
    gi, gj = (np.asarray(g, dtype=float) for g in (CASE_232_I, CASE_232_J))
    w = r3c_w(gi, gj)                   # col du scénario de la relecture R3c
    assert w < smaller_width(gi, gj)
    return gi, gj, w


def _case_232_holes(gi, gj):
    greens = {1: GreenShape(outline=tuple(map(tuple, gi.tolist())), center=CASE_232_CENTERS[0],
                            area=shoelace(gi), target_area=0.0),
              3: GreenShape(outline=tuple(map(tuple, gj.tolist())), center=CASE_232_CENTERS[1],
                            area=shoelace(gj), target_area=0.0)}
    return {o: HoleDressing(order=o, green=g) for o, g in greens.items()}


def test_review_case_with_duplicates_passes_the_oracle():
    """Non-régression : la forme du scénario de la relecture contient les
    deux greens ; l'oracle ne la rejette que sur ``carte`` (scénario en
    coordonnées négatives, hors carte), plus sur ``inclusion``."""
    gi, gj, _ = _case_232()
    layout = SimpleNamespace(links=(), clubhouse=ControlPoint(500.0, 500.0), width=1000.0,
                             height=1000.0)
    pair = GreenPair(i=1, j=3, distance=16.0, footprint=footprint(gi, gj))
    holes = _case_232_holes(gi, gj)
    assert shape_or_reject(layout, holes, {}, pair) == (
        None, PairRejection(1, 3, "oracle", ("carte",)))
    shaped = ps.build_pair(pair, holes[1].green, holes[3].green)
    assert ps.contains_outline(shaped.outline, gi) and ps.contains_outline(shaped.outline, gj)


def test_review_case_with_duplicates_contains_both_greens():
    gi, gj, w = _case_232()
    shape = ps.pinched_shape(gi, gj, *CASE_232_CENTERS, w)
    assert ps.contains_outline(shape, gi) and ps.contains_outline(shape, gj)


def test_review_case_with_a_green_vertex_on_the_flank(monkeypatch):
    """Variante « sur un sommet » : un sommet est ajouté au green i (sur
    l'arête x = −3, sans changer sa région ni l'enveloppe) exactement au
    point du flanc qui y était posé ; le flanc passe alors par un sommet du
    green, au bruit du repère près. La forme contient toujours les deux
    greens."""
    gi, gj, w = _case_232()
    flanks = []
    side_path = ps._side_path
    monkeypatch.setattr(ps, "_side_path",
                        lambda flank, greens: flanks.append(flank) or side_path(flank, greens))
    ps.pinched_shape(gi, gj, *CASE_232_CENTERS, w)
    m, rot, _ = ps._frame(*CASE_232_CENTERS)
    on_edge = [p for p in m + flanks[0] @ rot if abs(p[0] + 3.0) < 1e-12 and -6.0 < p[1] < -5.0]
    assert len(on_edge) == 1
    k = CASE_232_I.index((-3, -5)) + 1
    gv = np.insert(gi, k, on_edge[0], axis=0)
    assert np.array_equal(_convex_hull(gv), _convex_hull(gi))
    shape = ps.pinched_shape(gv, gj, *CASE_232_CENTERS, w)
    assert ps.contains_outline(shape, gv) and ps.contains_outline(shape, gj)


def _ring_hits(flank, ring):
    """Croisements de ``_crossings`` triés le long du flanc :
    ``(position, entre)``."""
    fpos, _, _, enters = ps._crossings(np.asarray(flank, float), np.asarray(ring, float))
    return sorted(zip(fpos.tolist(), enters.tolist()))


def _enters(hits):
    return [enter for _, enter in hits]


def _net(hits):
    """``entre`` le long du flanc, chaque groupe de croisements confondus
    (positions à ``ON_TOL`` près : sommet du flanc sur un coin de
    l'anneau, ordre indéterminé) réduit à son effet net, entrée, sortie ou
    rien."""
    groups = []
    for position, enter in hits:
        if not groups or position - groups[-1][0] > ps.ON_TOL:
            groups.append((position, []))
        groups[-1][1].append(enter)
    net = []
    for _, group in groups:
        balance = group.count(True) - group.count(False)
        assert abs(balance) <= 1, group
        net.extend([balance > 0] if balance else [])
    return net


@pytest.mark.parametrize("flank, expected", [
    (((-1, 0.5), (0, 0.5), (1, 0.5)), [True]),              # sommet du flanc sur une arête
    (((-1, -1), (0, 0), (1, 1)), [True]),                    # sommet du flanc sur un sommet
    (((-1, -1), (0.5, 0.5), (1, 3)), [True, False]),         # passe par un sommet, ressort
    (((-1, 0), (0, 0), (0.5, 1.5)), [True]),                 # le long d'une arête puis entre
])
def test_crossings_on_a_vertex_or_an_edge_are_counted_once(flank, expected):
    square = ((0, 0), (0, 2), (2, 2), (2, 0))                # horaire : intérieur à droite
    assert _enters(_ring_hits(flank, square)) == expected


@pytest.mark.parametrize("flank", [((-1, 1), (0, 0), (1, -1)),    # touche un coin, dehors
                                   ((-1, 0), (0, 0), (3, 0)),     # longe une arête
                                   ((-1, 1), (0, 1), (-1, 2))])   # touche une arête, repart
def test_touching_the_boundary_is_never_an_odd_crossing(flank):
    hits = _net(_ring_hits(flank, ((0, 0), (0, 2), (2, 2), (2, 0))))
    assert len(hits) % 2 == 0 and hits[::2] == [True] * (len(hits) // 2)


GRID_RING = ((0, 0), (0, 4), (2, 4), (2, 2), (4, 2), (4, 4), (6, 4), (6, 0))


def _grid_flanks(rng, count):
    """Flancs aux sommets intérieurs sur la grille entière de ``GRID_RING``
    (sur ses arêtes, ses sommets, colinéaires à ses arêtes), extrémités
    hors grille ; sans segment nul."""
    for _ in range(count):
        inner = rng.integers(-1, 8, size=(rng.integers(1, 6), 2)).astype(float)
        start, end = rng.uniform(-1, 7, size=(2, 2)) + 0.1234567
        flank = np.vstack((start, inner, end))
        if np.all(np.hypot(*np.diff(flank, axis=0).T) > 0.0):
            yield flank


def _assert_alternate(flank, ring, inside):
    """Le long du flanc, entrées et sorties alternent, la première est
    cohérente avec la position du départ, leur nombre (parité) avec celle
    de l'arrivée."""
    hits = _net(_ring_hits(flank, ring))
    expected = [not inside[0] if n % 2 == 0 else inside[0] for n in range(len(hits))]
    assert hits == expected, flank
    assert (len(hits) % 2 == 1) == (inside[0] != inside[1]), flank


def test_crossings_alternate_on_degenerate_integer_grids():
    """Flancs et anneaux sur une grille entière (sommets du flanc sur des
    arêtes et des sommets de l'anneau, segments colinéaires : égalités
    exactes). Un sommet du flanc sur un coin de l'anneau peut donner
    plusieurs croisements au même point (ordre indéterminé ; ``_side_path``
    rejette les croisements confondus) : réduits à leur effet net."""
    ring = np.array(GRID_RING, float)
    for flank in _grid_flanks(np.random.default_rng(7), 400):
        inside = points_in_polygon(flank[[0, -1]], ring).tolist()
        _assert_alternate(flank, ring, inside)


def test_crossings_alternate_on_rotated_integer_grids():
    """Même grille tournée d'un angle quelconque (et translatée) : les
    égalités exactes deviennent du bruit d'arrondi (~1e-15), segments
    presque colinéaires disjoints ou chevauchants compris. Signes
    d'orientation exacts : aucune erreur de parité ni d'alternance."""
    rng = np.random.default_rng(11)
    ring0 = np.array(GRID_RING, float)
    for index, flank in enumerate(_grid_flanks(rng, 1000)):
        angle = rng.uniform(0.0, 2.0 * math.pi)
        rot = np.array(((math.cos(angle), -math.sin(angle)), (math.sin(angle), math.cos(angle))))
        offset = rng.uniform(-500.0, 500.0, 2) if index % 2 else np.zeros(2)
        inside = points_in_polygon(flank[[0, -1]], ring0).tolist()
        _assert_alternate(flank @ rot.T + offset, ring0 @ rot.T + offset, inside)


def test_collinear_disjoint_rotated_segments_do_not_cross():
    """Cas de relecture : segment du flanc ``(4, −1) → (4, 0)`` colinéaire à
    l'arête ``(4, 2) → (4, 4)`` (index 4) mais disjoint, le tout tourné de
    ~3,2143 rad : aucun croisement avec cette arête, mêmes croisements
    qu'avant rotation."""
    flank = np.array(((3.8076205998910915, 5.60960834956756), (-1, -1), (4, -1), (4, 0),
                      (1.679128467486113, 2.5770445195499816)), float)
    ring = np.array(GRID_RING, float)
    angle = 3.214319950205114
    rot = np.array(((math.cos(angle), -math.sin(angle)), (math.sin(angle), math.cos(angle))))
    straight, turned = _ring_hits(flank, ring), _ring_hits(flank @ rot.T, ring @ rot.T)
    ring_positions = ps._crossings(flank @ rot.T, ring @ rot.T)[1]
    assert not np.any((ring_positions >= 4.0) & (ring_positions <= 5.0)), ring_positions
    assert _net(turned) == _net(straight)


@pytest.mark.parametrize("scale", [1e200, 1e300, 1e-170, 1e-300])
def test_orientation_signs_survive_huge_and_tiny_coordinates(scale):
    """Orientations dont le produit flottant déborde (~1e400) ou
    sous-dépasse (~1e-340) : signe pris sur le rationnel exact (pas de
    ``OverflowError``, pas de faux zéro), zéro seulement si exact ; mêmes
    croisements qu'à l'échelle 1, positions dans [0, 1]."""
    p = np.array(((0.0, 1.0), (0.0, -1.0), (1.0, 0.0), (0.5, 0.0)))
    a, b = np.array((-1.0, 0.0)), np.array((1.0, 0.0))
    signs = np.sign(ps._orientations(p, a, b))
    with np.errstate(over="ignore", under="ignore"):
        scaled = ps._orientations(p * scale, a * scale, b * scale)
    assert np.isfinite(scaled).all()
    assert np.array_equal(np.sign(scaled), signs) and signs.tolist() == [1, -1, 0, 0]
    square = np.array(((0, 0), (0, 2), (2, 2), (2, 0)), float)
    flank = np.array(((-1, 0.5), (0.7, 0.5), (1, 3)), float)
    with np.errstate(over="ignore", under="ignore"):
        fpos, rpos, _, enters = ps._crossings(flank * scale, square * scale)
    reference = _ring_hits(flank, square)
    assert sorted(zip(np.floor(fpos).tolist(), enters.tolist())) == \
        [(math.floor(f), e) for f, e in reference]
    assert np.all((fpos % 1 >= 0) & (rpos >= 0) & (rpos < 4))


def test_signed_float_keeps_the_sign_of_the_rational():
    from fractions import Fraction
    assert ps._signed_float(Fraction(10) ** 400) == np.finfo(float).max
    assert ps._signed_float(-Fraction(10) ** 400) == -np.finfo(float).max
    assert ps._signed_float(Fraction(1, 10 ** 400)) == math.ulp(0.0)
    assert ps._signed_float(-Fraction(1, 10 ** 400)) == -math.ulp(0.0)
    assert ps._signed_float(Fraction(0)) == 0.0
    assert ps._signed_float(Fraction(3, 4)) == 0.75


# --- production --------------------------------------------------------------------

def _production_cases(path):
    out = []
    for case in json.loads(path.read_text(encoding="utf-8"))["layouts"]:
        layout = CourseLayout.from_dict(case["layout"])
        cores = {h.order: build_hole_geometry(h).core for h in layout.holes}
        for style in STYLE_SPECS:
            for seed in (case["seed"], 1, 2, 3):
                dressing = dress_course(SimpleNamespace(layout=layout), seed=seed, style=style)
                again = dress_course(SimpleNamespace(layout=layout), seed=seed, style=style)
                out.append((layout, cores, seed, dressing, again))
    return out


@pytest.fixture(scope="module")
def production():
    """Habillages de production : layout réel R3f (plage de production, la
    paire 10/17) et instantané à la plage R3a–R3e (formes R3f, plus de
    paires) ; chacun habillé deux fois (déterminisme)."""
    out = _production_cases(R3F_LAYOUT)
    assert any(d.green_pairs for _, _, _, d, _ in out)
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(pairs_module, "PAIR_DISTANCE", R3E_RANGE)
        out += _production_cases(SNAPSHOT)
    return out


def test_production_pairs_pass_the_oracle(production):
    shaped = 0
    for layout, cores, _, dressing, _ in production:
        pairs = dressing.green_pairs
        for p in pairs:
            assert len(p.outline) >= 3 and p.neck_width is not None
            shaped += 1
        assert oracle_failures(check_green_pairs(layout, dressing.holes, pairs, cores)) == []
    assert shaped >= 20


def test_production_fairways_cross_no_other_green(production):
    """Interdiction (décision utilisateur), plage élargie 12–35 et layout
    R3f : aucun green ni green double d'un autre trou ne coupe un fairway
    (``tests.test_dressing_fairway.fairway_crossings``)."""
    from collections import Counter

    from tests.test_dressing_fairway import fairway_crossings
    checked = Counter()
    for _, _, seed, dressing, _ in production:
        crossed, seen = fairway_crossings(dressing)
        assert crossed == [], (seed, dressing.style, crossed)
        checked += seen
    assert checked["green"] > 0 and checked["paire"] > 0, checked


def test_production_shapes_are_deterministic(production):
    for _, _, _, dressing, again in production:
        assert again.green_pairs == dressing.green_pairs
        assert [p.outline for p in again.green_pairs] == [p.outline for p in dressing.green_pairs]


def test_production_pairs_export_as_valid_polygons(production):
    """Export 3.1 (``routing.green_pairs``) des paires de production : contour
    arrondi à 2 décimales, même sens que les greens (aire signée positive),
    polygone simple contenant les centres des deux greens, aire proche de
    celle du contour non arrondi."""
    from golfgen.exporter import _green_pairs_v31
    exported = 0
    for _, _, _, dressing, _ in production:
        entries = _green_pairs_v31(dressing)
        assert [e["holes"] for e in entries] == sorted([p.i, p.j] for p in dressing.green_pairs)
        for entry in entries:
            pair = next(p for p in dressing.green_pairs if [p.i, p.j] == entry["holes"])
            outline = np.array([[q["x"], q["y"]] for q in entry["outline"]], dtype=float)
            assert np.array_equal(outline, np.round(outline, 2))
            assert shoelace(outline) > 0 and ps.is_simple(outline)
            assert entry["area"] == round(shoelace(outline), 2)
            assert abs(entry["area"] - shoelace(np.asarray(pair.outline))) < 0.1
            centres = np.array([dressing[o].green.center for o in entry["holes"]])
            assert points_in_polygon(centres, outline).all()
            exported += 1
    assert exported >= 20
