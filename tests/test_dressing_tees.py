"""Boîtes de départ (``golfgen.dressing.tees``) sur l'instantané du routeur
``tests/data/dressing_holes_30x2.json`` (1080 trous, seeds brutes 1–30 comme
``tests/test_dressing_kinds.py``) et sur des trous synthétiques."""

from __future__ import annotations

import math
from types import SimpleNamespace

import numpy as np
import pytest

from golfgen.dressing import RNG_LABEL, STYLE_SPECS, DressingError, dress_course
from golfgen.dressing import tees as tees_module
from golfgen.dressing.course import TEE_STREAM, tee_rng
from golfgen.dressing.green import green_shape, polygon_inside, shoelace
from golfgen.dressing.tees import (TEE_BOX_LENGTH, TEE_BOX_WIDTH, TEE_FALLBACK_CAUSES,
                                   TEE_MIN_GAP, TEE_MIN_SPACING, TEE_SPREAD_MIN_2,
                                   TEE_SPREAD_MIN_3, settled_count, spread_cap, tee_boxes)
from golfgen.routing.geometry import _point_in_polygon, build_hole_geometry, polygon_gap
from golfgen.routing.model import ControlPoint, ElasticHole
from tests.test_dressing_kinds import load_snapshot

# Règles validées (R2b), réécrites ici sans passer par le module testé.
S, F, M = 55.0, 0.25, 10.0
SPREAD_MAX = 20.0
MIDDLE = (0.35, 0.65)
FALLBACK_MAX_SHARE = 0.05
# Écart bord à bord mesuré sur les contours arrondis à 2 décimales
# (déplacement ≤ 0,005·√2 par sommet) : seule tolérance, due à cet arrondi.
OUTLINE_ROUNDING = 0.01
EPS = 1e-9


def _dress(holes, seed, style="links"):
    return dress_course(SimpleNamespace(layout=SimpleNamespace(holes=holes)),
                        seed=seed, style=style)


@pytest.fixture(scope="module")
def dressed():
    return [(size, seed, holes, _dress(holes, seed)) for size, seed, holes in load_snapshot()]


def _items(dressed):
    for size, seed, holes, dressing in dressed:
        for hole in holes:
            yield f"{size}/{seed}#{hole.order}", seed, hole, dressing[hole.order]


def _seg1(hole):
    a, b = hole.axis[0], hole.axis[1]
    return math.dist((a.x, a.y), (b.x, b.y))


def _emax(hole):
    terms = [SPREAD_MAX, F * hole.length]
    if hole.doglegs:
        terms.append(_seg1(hole) - M)
    return min(terms)


def _dir(hole):
    a, b = hole.axis[0], hole.axis[1]
    d = np.array((b.x - a.x, b.y - a.y))
    return d / np.linalg.norm(d)


def test_constants_are_consistent():
    assert TEE_MIN_SPACING == TEE_BOX_LENGTH + TEE_MIN_GAP == 6.0
    assert TEE_SPREAD_MIN_3 == 2 * TEE_MIN_SPACING
    assert TEE_SPREAD_MIN_2 == 10.0 and (TEE_BOX_LENGTH, TEE_BOX_WIDTH) == (4.0, 3.0)
    assert TEE_STREAM != 0          # [.., 0] confondu avec le flux du green


def test_boxes_inside_core(dressed):
    for case, _, hole, hd in _items(dressed):
        core = build_hole_geometry(hole).core
        for box in hd.tees:
            assert polygon_inside(np.asarray(box.outline), np.asarray(core)), case
            assert all(_point_in_polygon(p, core) for p in box.outline), case


def test_box_shape(dressed):
    for case, _, hole, hd in _items(dressed):
        u = _dir(hole)
        for box in hd.tees:
            outline = np.asarray(box.outline)
            assert len(outline) == 4 and shoelace(outline) > 0.0, case   # sens des greens
            # aire : arrondi des sommets, au plus périmètre × 0,005·√2 ≈ 0,1
            # (écart mesuré jusqu'à 0,06 sur l'instantané : 0,03 ne suffit pas)
            assert box.area == pytest.approx(TEE_BOX_LENGTH * TEE_BOX_WIDTH, abs=0.1), case
            # l'aire exportée est celle du contour arrondi, arrondie à 2 décimales
            assert box.area == pytest.approx(abs(shoelace(outline)), abs=0.005 + EPS), case
            edges = np.roll(outline, -1, axis=0) - outline
            lengths = np.linalg.norm(edges, axis=1)
            along = np.abs(edges @ u) / lengths
            for length, cos in zip(lengths, along):
                expected = TEE_BOX_LENGTH if cos > 0.5 else TEE_BOX_WIDTH
                assert length == pytest.approx(expected, abs=OUTLINE_ROUNDING * 2), case
            assert np.allclose(outline.mean(axis=0), box.center, atol=OUTLINE_ROUNDING), case
            assert np.allclose(box.heading, u), case


def test_order_back_to_front_and_back_box_on_tee(dressed):
    for case, _, hole, hd in _items(dressed):
        tees = hd.tees
        assert tees and [box.rank for box in tees] == list(range(len(tees))), case
        assert tees[0].center == (hole.tee.x, hole.tee.y), case
        tee = np.array(tees[0].center)
        distances = [float(np.dot(np.array(box.center) - tee, _dir(hole))) for box in tees]
        assert distances == sorted(distances) and distances[0] == 0.0, case


def test_boxes_on_first_segment_and_on_axis(dressed):
    for case, _, hole, hd in _items(dressed):
        u, tee, seg1 = _dir(hole), np.array((hole.tee.x, hole.tee.y)), _seg1(hole)
        normal = np.array((-u[1], u[0]))
        for box in hd.tees:
            offset = np.array(box.center) - tee
            assert -EPS <= float(offset @ u) <= seg1, case
            assert abs(float(offset @ normal)) <= 1e-6, case     # centré sur l'axe


def test_no_overlap_and_min_gap(dressed):
    for case, _, hole, hd in _items(dressed):
        for back, front in zip(hd.tees, hd.tees[1:]):
            assert math.dist(back.center, front.center) - TEE_BOX_LENGTH >= TEE_MIN_GAP - EPS, case
            assert polygon_gap(back.outline, front.outline) >= TEE_MIN_GAP - OUTLINE_ROUNDING, case


def test_boxes_do_not_touch_green(dressed):
    for case, _, hole, hd in _items(dressed):
        for box in hd.tees:
            assert polygon_gap(box.outline, hd.green.outline) > 0.0, case


def _expected_count(hole, seed):
    if hole.par == 3:
        drawn = 1 if hole.length < S else 2
    elif hole.par == 4:
        drawn = 3 if tee_rng(seed, hole.order).uniform() < 0.5 else 2
    else:
        drawn = 3
    emax = _emax(hole)
    count = drawn
    if count == 3 and emax < 12.0:
        count = 2 if emax >= 10.0 else 1
    if count == 2 and emax < 10.0:
        count = 1
    return drawn, count


def test_box_count_rule(dressed):
    for case, seed, hole, hd in _items(dressed):
        drawn, count = _expected_count(hole, seed)
        assert len(hd.tees) == count, case
        if count < drawn:
            by_length = F * hole.length
            by_segment = _seg1(hole) - M if hole.doglegs else math.inf
            cause = "segment_court" if by_segment < by_length else "trou_court"
            assert hd.tee_fallback_cause == cause, case
        else:
            assert hd.tee_fallback_cause is None, case


def test_tee_rng_stream_replay(dressed):
    """Rejoue le flux des départs ``default_rng([seed, RNG_LABEL, order, 1])``
    dans l'ordre figé : nombre (par 4 seulement), ``E`` (2 boîtes ou plus,
    après bascule), ``d`` du milieu (3 boîtes). Le nombre de boîtes est celui
    produit (les bascules sont vérifiées par ``test_box_count_rule``) : seuls
    les tirages sont rejoués ici."""
    checked = {1: 0, 2: 0, 3: 0}
    for case, seed, hole, hd in _items(dressed):
        rng = np.random.default_rng([seed, RNG_LABEL, hole.order, 1])
        if hole.par == 4:
            rng.uniform()  # tirage du nombre, consommé même s'il bascule
        count = len(hd.tees)
        checked[count] += 1
        if count == 1:
            continue
        spread = rng.uniform(12.0 if count == 3 else 10.0, _emax(hole))
        assert math.dist(hd.tees[0].center, hd.tees[-1].center) == pytest.approx(
            spread, abs=1e-9), case
        if count == 3:
            middle = rng.uniform(max(6.0, MIDDLE[0] * spread),
                                 min(spread - 6.0, MIDDLE[1] * spread))
            assert math.dist(hd.tees[0].center, hd.tees[1].center) == pytest.approx(
                middle, abs=1e-9), case
    assert checked[2] and checked[3], checked


def test_spread_and_middle_bounds(dressed):
    for case, _, hole, hd in _items(dressed):
        tees, emax = hd.tees, _emax(hole)
        if len(tees) < 2:
            continue
        spread = math.dist(tees[0].center, tees[-1].center)
        lo = 12.0 if len(tees) == 3 else 10.0
        assert lo - EPS <= spread <= emax + EPS, case
        if len(tees) == 3:
            d = math.dist(tees[0].center, tees[1].center)
            assert (max(6.0, MIDDLE[0] * spread) - EPS <= d
                    <= min(spread - 6.0, MIDDLE[1] * spread) + EPS), case


def test_fallbacks_at_most_5_percent(dressed):
    holes = [hd for _, _, _, hd in _items(dressed)]
    fallbacks = [hd for hd in holes if hd.tee_fallback_cause is not None]
    assert all(hd.tee_fallback_cause in TEE_FALLBACK_CAUSES for hd in fallbacks)
    assert len(fallbacks) <= FALLBACK_MAX_SHARE * len(holes), len(fallbacks)


def test_deterministic_and_seed_dependent(dressed):
    for size, seed, holes, dressing in dressed[:6]:
        again = _dress(holes, seed)
        assert all(again[o].tees == dressing[o].tees for o in dressing.holes)
        other = _dress(holes, seed + 1000)
        assert any(other[o].tees != dressing[o].tees for o in dressing.holes), (size, seed)


def test_tees_do_not_depend_on_style(dressed):
    for _, seed, holes, dressing in dressed[:10]:
        parkland = _dress(holes, seed, "parkland")
        for order in dressing.holes:
            assert parkland[order].tees == dressing[order].tees
            assert parkland[order].tee_fallback_cause == dressing[order].tee_fallback_cause


@pytest.mark.parametrize("style", sorted(STYLE_SPECS))
def test_greens_unchanged(dressed, style):
    """Green identique au bit près à celui de l'ancien flux unique
    ``[seed, RNG_LABEL, order]`` (avant les départs)."""
    spec = STYLE_SPECS[style]
    for size, seed, holes, dressing in dressed:
        current = dressing if style == "links" else _dress(holes, seed, style)
        for hole in holes:
            core = build_hole_geometry(hole).core
            old = green_shape(hole, core, np.random.default_rng([seed, RNG_LABEL, hole.order]),
                              spec)
            assert current[hole.order].green == old, (size, seed, hole.order)


# --- trous synthétiques : bascules et contraintes dures ---------------------------

def _hole(par, points, width=12.0):
    tee, *doglegs, green = (ControlPoint(x, y) for x, y in points)
    return ElasticHole(order=1, par=par, tee=tee, green=green, doglegs=tuple(doglegs),
                       width=width)


def _far_green():
    return ((1e4, 1e4), (1e4 + 1, 1e4), (1e4 + 1, 1e4 + 1))


@pytest.mark.parametrize("par, points, count, cause", [
    # coude, seg1 = 20 : Emax = 10 → 3 → 2 boîtes
    (5, [(0, 0), (20, 0), (20, 150)], 2, "segment_court"),
    # coude, seg1 = 15 : Emax = 5 → 1 boîte
    (5, [(0, 0), (15, 0), (15, 150)], 1, "segment_court"),
    # sans coude, L = 44 : F·L = 11 → 3 → 2 boîtes
    (5, [(0, 0), (44, 0)], 2, "trou_court"),
    # sans coude, L = 36 : F·L = 9 → 1 boîte
    (5, [(0, 0), (36, 0)], 1, "trou_court"),
    # coude, seg1 = 30 mais L = 40 : F·L = 10 < seg1 − M = 20 → trou court
    (5, [(0, 0), (30, 0), (30, 10)], 2, "trou_court"),
    # sans coude, par 3 de 60 blocs : 2 boîtes, pas de bascule
    (3, [(0, 0), (60, 0)], 2, None),
    # coude au premier segment long (seg1 = 25 ≥ 22) : 3 boîtes
    (5, [(0, 0), (25, 0), (25, 150)], 3, None),
])
def test_fallbacks_on_synthetic_holes(par, points, count, cause):
    hole = _hole(par, points)
    core = build_hole_geometry(hole).core
    tees, got = tee_boxes(hole, core, _far_green(), np.random.default_rng(3))
    assert (len(tees), got) == (count, cause)
    assert tees[0].center == (0.0, 0.0)


def test_settled_count():
    assert settled_count(3, 20.0, "trou_court") == (3, None)
    assert settled_count(3, 11.9, "trou_court") == (2, "trou_court")
    assert settled_count(3, 9.9, "segment_court") == (1, "segment_court")
    assert settled_count(2, 10.0, "trou_court") == (2, None)
    assert settled_count(2, 9.99, "trou_court") == (1, "trou_court")
    assert settled_count(1, 0.0, "trou_court") == (1, None)


def test_spread_cap_ignores_segment_without_dogleg():
    straight = _hole(4, [(0, 0), (100, 0)])
    assert spread_cap(straight) == (20.0, "trou_court")
    bent = _hole(4, [(0, 0), (25, 0), (25, 80)])
    assert spread_cap(bent) == (15.0, "segment_court")


def test_box_outside_core_raises():
    hole = _hole(3, [(0, 0), (60, 0)], width=2.0)       # cœur de 2 blocs < 3
    core = build_hole_geometry(hole).core
    with pytest.raises(DressingError, match="hors du cœur"):
        tee_boxes(hole, core, _far_green(), np.random.default_rng(0))


# boîte arrière d'un par 3 de 60 blocs (tee en (0, 0), axe +x) :
# [−2, 2] × [−1,5, 1,5]
@pytest.mark.parametrize("green", [
    ((-3.0, -3.0), (3.0, -3.0), (3.0, 3.0), (-3.0, 3.0)),       # recouvre la boîte
    ((-6.0, -3.0), (-2.0, -3.0), (-2.0, 3.0), (-6.0, 3.0)),     # bord commun seul
    ((-1.0, 1.5), (1.0, 1.5), (0.0, 4.0)),                      # bord sur le côté
    ((-5.0, -4.0), (-2.0, -1.5), (-4.0, 2.0)),                  # coin seul
    ((-0.5, -0.5), (0.5, -0.5), (0.0, 0.5)),                    # dans la boîte
], ids=["recouvre", "bord", "cote", "coin", "dedans"])
def test_box_on_green_raises(green):
    hole = _hole(3, [(0, 0), (60, 0)])
    core = build_hole_geometry(hole).core
    with pytest.raises(DressingError, match="sur le green"):
        tee_boxes(hole, core, green, np.random.default_rng(0))


def test_box_near_green_is_accepted():
    """Écart strictement positif, même petit : pas d'erreur."""
    hole = _hole(3, [(0, 0), (60, 0)])
    core = build_hole_geometry(hole).core
    green = ((-6.0, -3.0), (-2.01, -3.0), (-2.01, 3.0), (-6.0, 3.0))
    tees, _ = tee_boxes(hole, core, green, np.random.default_rng(0))
    assert tees[0].center == (0.0, 0.0)


def test_gap_matches_polygon_gap(dressed):
    """``_gap`` (vectorisé) rend l'écart de ``polygon_gap`` (routage) entre
    chaque boîte et son green, et des boîtes déplacées vers le green."""
    for case, _, hole, hd in list(_items(dressed))[::7]:
        green = np.asarray(hd.green.outline)
        for box in hd.tees:
            outline = np.asarray(box.outline)
            towards = np.asarray(hd.green.center) - np.asarray(box.center)
            for k in (0.0, 0.5, 0.9, 1.0):
                moved = outline + k * towards
                expected = polygon_gap(tuple(map(tuple, moved)), hd.green.outline)
                got = tees_module._gap(moved, green)
                assert got == pytest.approx(expected, abs=1e-9), (case, k)


@pytest.mark.parametrize("p, q, meets", [
    ((-5.0, 0.0), (5.0, 0.0), True),        # traverse
    ((-5.0, 3.0), (5.0, 3.0), False),       # au-dessus, parallèle
    ((-5.0, 1.0), (5.0, 1.0), True),        # sur le bord (rectangle fermé)
    ((0.0, -5.0), (0.0, 5.0), True),        # vertical
    ((3.0, -5.0), (3.0, 5.0), False),       # vertical, à droite
    ((-5.0, -5.0), (-1.5, 0.0), False),     # s'arrête avant
    ((0.5, 0.5), (0.6, 0.6), True),         # intérieur
])
def test_segment_meets_rectangle(p, q, meets):
    assert tees_module._segment_meets_rectangle(p, q, -1.0, 2.0, 1.0) is meets


def test_fast_core_check_is_sound(dressed):
    """``_rectangle_in_core`` (condition suffisante) n'accepte que des
    rectangles que ``polygon_inside`` accepte aussi, sur les cœurs réels."""
    accepted = rejected = 0
    for case, _, hole, _ in list(_items(dressed))[::9]:
        core = build_hole_geometry(hole).core
        tx, ty = hole.tee.x, hole.tee.y
        hx, hy = _dir(hole)
        local = [((x - tx) * hx + (y - ty) * hy, (y - ty) * hx - (x - tx) * hy)
                 for x, y in core]
        # rectangles à 0,2 bloc au moins du bord du cœur (un rectangle posé
        # sur le bord est ambigu en flottant pour l'un et l'autre contrôle)
        r = hole.width / 2
        for back, front, half in ((-2.0, 22.0, 1.5), (-2.0, 60.0, 1.5),
                                  (-r - 0.2, 2.0, 1.5), (-r + 0.2, 2.0, 1.5),
                                  (-2.0, 2.0, r - 0.2), (-2.0, 2.0, r + 0.2)):
            fast = tees_module._rectangle_in_core(local, back, front, half)
            rect = np.array(tees_module._rectangle(tx, ty, hx, hy, back, front, half))
            if fast:
                accepted += 1
                assert polygon_inside(rect, np.asarray(core)), case
            else:
                rejected += 1
    assert accepted and rejected
