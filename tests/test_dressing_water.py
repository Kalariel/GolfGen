"""Lot 1 eau : greens, boîtes de départ et greens doubles hors de l'eau RÉELLE
du relief (``golfgen.dressing.water``, masque brut
``golfgen.routing.sites.water_mask``), règle retenue par l'utilisateur
(marge 0 bloc) : green links décalé à l'opposé de l'eau (insulaire en
dernier recours, et quand la seule candidate au sec est réduite de plus de
30 %), green parkland insulaire, boîtes avancées déplacées dans l'axe puis
décalées en travers puis remontées, boîte arrière glissée d'au plus 1 bloc
puis remontée, aucune boîte retirée, paires refusées sur l'eau réelle.

Géométrie exacte (aire commune, écart, cellules remontées, eau effective),
habillage sans eau inchangé au bit près, repli déterministe sans tirage
supplémentaire, et sur le corpus de l'instantané 30x2 (60 parcours, deux
styles, reliefs ``load_terrain``) : plus rien sur l'eau effective, seuls les
trous repliés changent (et le fairway coupé par l'eau, lot 2 R4),
drapeau des greens repliés à ≥ 1 bloc du bord,
green dans le cœur, insulaire à forme intacte et à la bonne altitude,
boîtes remontées à la bonne altitude, nombre de boîtes par par respecté ;
l'eau effective est celle de chaque trou (une bande remontée par un trou
reste de l'eau pour les autres).
"""

from __future__ import annotations

import dataclasses
import json
import math
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from golfgen.dressing import STYLE_SPECS, GreenIsland, TeeIsland, dress_course, effective_water
from golfgen.dressing import course as course_module
from golfgen.dressing import green as green_module
from golfgen.dressing import fairway as fw
from golfgen.dressing.course import (fairway_profile_rng, fairway_rng, green_rng, pair_rng,
                                     tee_rng)
from golfgen.dressing.fairway_profile import fairway_obstacles
from golfgen.dressing.fairway_water import FAIRWAY_WATER_CUT, water_fairway
from golfgen.dressing.green import (GREEN_FLAG_EDGE, GREEN_WATER_MAX_REDUCTION,
                                    dry_green_shape, flag_edge_distance, green_shape,
                                    polygon_inside)
from golfgen.dressing.pairs import PAIR_REJECTION_CAUSES, REJECT_WATER, pair_selection
from golfgen.dressing.tees import TEE_BACK_SLIDE_MAX, dry_tee_boxes, tee_boxes
from golfgen.dressing.water import (AREA_NOISE, SUBMERGED_TEE_LIFT, footprint_cells,
                                    island_of, is_dry, raised_cells, raised_mask,
                                    tee_island_of, water_area, water_gap)
from golfgen.exporter import _features_v31
from golfgen.routing.geometry import build_hole_geometry
from golfgen.routing.model import CourseLayout, ElasticHole
from golfgen.routing.sites import WATER_LEVEL, WaterMask, load_terrain, water_mask

DATA = Path(__file__).resolve().parent / "data"
# Parcours réels de l'instantané (taille, seed) : 400x300/26 (green du trou 14
# décalé en links ; boîte arrière du trou 16 glissée),
# 300x400/28 (boîte avancée du trou 15 décalée en travers).
REAL = ((400, 300, 26), (300, 400, 28))
BACK_SLID = (400, 300, 26, 16)
# Green links du trou 4 de 400x300/14 : sans la règle des 30 %, réduit
# au sec (≈ 70 blocs² pour ≈ 129 tirés) ; avec la règle, insulaire.
RULE_30 = (400, 300, 14, 4)
# Green links du trou 5 de 400x300/28 : réduit de ≈ 27 % de la forme tirée
# (deux paliers d'aire) puis décalé, retenu par la règle des 30 %.
RULE_30_KEPT = (400, 300, 28, 5)
# 400x300/20, trou 2 : les deux boîtes avancées remontées (eau partout dans
# leurs bornes d'étalement et en travers), entièrement immergées.
RAISED = (400, 300, 20, 2)
PAR_RULE = {3: (1, 2), 4: (2, 3), 5: (3,)}


def _snapshot():
    data = json.loads((DATA / "dressing_holes_30x2.json").read_text(encoding="utf-8"))
    return {(*map(int, c["size"].split("x")), c["seed"]):
            tuple(ElasticHole.from_dict(h) for h in c["holes"]) for c in data["courses"]}


@pytest.fixture(scope="module")
def snapshot():
    return _snapshot()


def _result(holes):
    return SimpleNamespace(layout=SimpleNamespace(holes=holes))


@pytest.fixture(scope="module")
def corpus(snapshot):
    """``[(cas, style, relief, trous, sans eau, avec relief)]`` sur tout
    l'instantané."""
    out = []
    for case, holes in snapshot.items():
        width, height, seed = case
        relief = load_terrain(seed, width, height)
        for style in STYLE_SPECS:
            out.append((case, style, relief, {h.order: h for h in holes},
                        dress_course(_result(holes), seed=seed, style=style),
                        dress_course(_result(holes), seed=seed, style=style, relief=relief)))
    return out


# --- géométrie -------------------------------------------------------------------------

def _single_cell():
    water = np.zeros((20, 20), dtype=bool)
    water[10, 10] = True                    # carré [10, 11] × [10, 11]
    return WaterMask(water=water)


def test_water_area_and_gap_are_exact():
    water = _single_cell()
    half = [(9.5, 9.0), (10.5, 9.0), (10.5, 12.0), (9.5, 12.0)]
    assert water_area(half, water) == pytest.approx(0.5)
    assert water_gap(half, water, 1.0) == 0.0
    touching = [(8.0, 10.0), (10.0, 10.0), (10.0, 11.0), (8.0, 11.0)]
    assert water_area(touching, water) == 0.0
    assert water_gap(touching, water, 1.0) == 0.0
    assert is_dry(touching, water, 0.0) and not is_dry(touching, water, 1.0)
    away = [(7.0, 10.0), (9.5, 10.0), (9.5, 11.0), (7.0, 11.0)]
    assert water_gap(away, water, 1.0) == pytest.approx(0.5)
    diagonal = [(8.0, 8.0), (9.0, 8.0), (9.0, 9.0), (8.0, 9.0)]
    assert water_gap(diagonal, water, 2.0) == pytest.approx(math.sqrt(2.0))
    assert water_gap(diagonal, water, 0.5) == math.inf      # hors de portée (en x et en y)
    around = [(5.0, 5.0), (15.0, 5.0), (15.0, 15.0), (5.0, 15.0)]
    assert water_area(around, water) == pytest.approx(1.0)
    assert is_dry(around, None, 1.0) and water_area(around, None) == 0.0


def test_water_area_of_a_concave_polygon():
    water = WaterMask(water=np.ones((10, 10), dtype=bool))
    notch = [(1.0, 1.0), (5.0, 1.0), (5.0, 5.0), (3.0, 2.5), (1.0, 5.0)]
    shoelace = 0.5 * abs(sum(x0 * y1 - x1 * y0 for (x0, y0), (x1, y1)
                             in zip(notch, notch[1:] + notch[:1])))
    assert water_area(notch, water) == pytest.approx(shoelace)


def test_fast_wet_test_matches_water_area():
    """Rejet rapide exact de ``is_dry`` (marge 0, ``water._wet``) : même
    verdict que ``water_area ≤ AREA_NOISE`` sur des polygones tirés sur une
    eau tirée, contacts par un bord et miettes comprises."""
    rng = np.random.default_rng(5)
    water = WaterMask(water=rng.uniform(size=(40, 40)) < 0.15)
    theta = 2.0 * np.pi * np.arange(12) / 12
    seen = {True: 0, False: 0}
    for _ in range(600):
        cx, cy = rng.uniform(2.0, 38.0, size=2)
        radius = rng.uniform(0.2, 3.0) * (1.0 + 0.3 * np.sin(3.0 * theta + rng.uniform(0, 6)))
        outline = np.round(np.column_stack((cx + radius * np.cos(theta),
                                            cy + radius * np.sin(theta))), 2)
        if rng.uniform() < 0.3:             # boîte posée sur la grille : contacts par un bord
            x0, y0 = int(cx), int(cy)
            outline = np.array([(x0, y0), (x0 + 1.0, y0), (x0 + 1.0, y0 + 1.0), (x0, y0 + 1.0)])
        expected = water_area(outline, water) <= AREA_NOISE
        assert is_dry(outline, water, 0.0) == expected
        seen[expected] += 1
    assert min(seen.values()) > 50


def test_island_raised_cells_and_effective_water():
    """Relief fabriqué : green à cheval sur deux cellules d'eau. Remontées :
    les cellules d'eau qu'il recouvre (pas celle qu'il touche d'un bord),
    à l'altitude minimale de sa partie émergée ; eau effective = eau
    réelle moins ces cellules, rien d'autre."""
    relief = np.full((20, 20), 70.0, dtype=np.float32)
    relief[10, 10] = relief[10, 11] = 50.0      # eau recouverte
    relief[10, 13] = 40.0                       # eau touchée d'un bord seulement
    relief[12, 12] = 50.0                       # eau ailleurs
    relief[9, 10] = 61.5                        # partie émergée la plus basse
    water = water_mask(relief)
    outline = [(9.5, 9.0), (13.0, 9.0), (13.0, 10.5), (9.5, 10.5)]
    raised = {tuple(c) for c in raised_cells(outline, water).tolist()}
    assert raised == {(10, 10), (11, 10)}
    footprint = {tuple(c) for c in footprint_cells(outline, 20, 20).tolist()}
    assert raised < footprint and (13, 10) not in footprint
    island = island_of(outline, relief, water)
    assert island == GreenIsland(height=61.5, raised_area=2.0)
    green = SimpleNamespace(outline=tuple(outline), island=island)
    seen = effective_water(water, (green,))
    expected = np.array(water.water)
    expected[10, 10] = expected[10, 11] = False
    assert np.array_equal(seen.water, expected)
    assert is_dry(outline, seen, 0.0) and not is_dry(outline, water, 0.0)
    # même eau qu'un relief où les cellules remontées le sont à ``height``
    lifted = np.array(relief)
    lifted[10, 10] = lifted[10, 11] = island.height
    assert np.array_equal(water_mask(lifted).water, seen.water)
    assert effective_water(water, (SimpleNamespace(outline=tuple(outline), island=None),)) \
        is water
    assert effective_water(None, (green,)) is None


# --- sans eau : inchangé au bit près ------------------------------------------------------

def test_without_water_nothing_changes(snapshot):
    holes = snapshot[REAL[0]]
    dry = np.full((300, 400), WATER_LEVEL + 10.0, dtype=np.float32)
    for style in STYLE_SPECS:
        plain = dress_course(_result(holes), seed=26, style=style)
        assert dress_course(_result(holes), seed=26, style=style, relief=dry) == plain
        assert all(hd.water_fix is None and hd.green.island is None
                   for hd in plain.holes.values())


def test_no_new_draws_and_deterministic(snapshot):
    """Le repli ne consomme aucun tirage de plus : état des flux identique à
    celui de l'habillage sans eau ; deux appels donnent le même résultat."""
    width, height, seed = REAL[0]
    relief = load_terrain(seed, width, height)
    water = water_mask(relief)
    for hole in snapshot[REAL[0]]:
        core = build_hole_geometry(hole).core
        for style, spec in STYLE_SPECS.items():
            plain_rng, wet_rng = green_rng(seed, hole.order), green_rng(seed, hole.order)
            green_shape(hole, core, plain_rng, spec)
            green, fix = dry_green_shape(hole, core, wet_rng, spec, water, relief)
            assert plain_rng.bit_generator.state == wet_rng.bit_generator.state
            assert dry_green_shape(hole, core, green_rng(seed, hole.order), spec,
                                   water, relief) == (green, fix)
            plain_rng, wet_rng = tee_rng(seed, hole.order), tee_rng(seed, hole.order)
            seen = effective_water(water, (green,))
            tee_boxes(hole, core, green.outline, plain_rng)
            got = dry_tee_boxes(hole, core, green.outline, wet_rng, seen, relief)
            assert plain_rng.bit_generator.state == wet_rng.bit_generator.state
            assert dry_tee_boxes(hole, core, green.outline, tee_rng(seed, hole.order),
                                 seen, relief) == got
    for case in REAL:
        holes = snapshot[case]
        relief = load_terrain(case[2], case[0], case[1])
        for style in STYLE_SPECS:
            first = dress_course(_result(holes), seed=case[2], style=style, relief=relief)
            assert dress_course(_result(holes), seed=case[2], style=style,
                                relief=relief) == first


# --- corpus de l'instantané -------------------------------------------------------------

def test_corpus_nothing_on_effective_water(corpus):
    """Ni green ni boîte de départ sur l'eau EFFECTIVE de son trou (eau
    réelle moins son green insulaire et ses boîtes remontées), sur les 60
    parcours de l'instantané, deux styles ; un green non insulaire et une
    boîte non remontée sont au sec de l'eau réelle moins le seul green
    insulaire de leur trou ; aucun élément ne recouvre une cellule remontée
    par un AUTRE trou, aucune cellule n'est remontée deux fois."""
    for case, style, relief, _, _, wet in corpus:
        water = water_mask(relief)
        owners = np.zeros(water.water.shape, dtype=np.int64)
        for order, hd in wet.holes.items():
            seen = effective_water(water, (hd.green, *hd.tees))
            assert is_dry(hd.green.outline, seen, 0.0), (case, style, order)
            if hd.green.island is None:
                assert is_dry(hd.green.outline, water, 0.0), (case, style, order)
            under_green = effective_water(water, (hd.green,))
            for box in hd.tees:
                assert is_dry(box.outline, seen, 0.0), (case, style, order, box.rank)
                if box.island is None:
                    assert is_dry(box.outline, under_green, 0.0), (case, style, order)
            mask = raised_mask(water, (hd.green, *hd.tees))
            assert not (owners[mask] != 0).any(), (case, style, order)
            owners[mask] = order
        for order, hd in wet.holes.items():
            others = WaterMask(water=(owners != 0) & (owners != order))
            for outline in [hd.green.outline] + [box.outline for box in hd.tees]:
                assert is_dry(outline, others, 0.0), (case, style, order)


def test_corpus_only_fixed_holes_change(corpus):
    """Un trou sans repli (``water_fix is None``) est identique au bit près
    à l'habillage sans eau : green, départs, cause ; fairway aussi, sauf
    coupure sur l'eau (lot 2 R4, ``FAIRWAY_WATER_CUT``) : alors le même
    fairway SANS eau (``water_fairway``, ``water = None``) est celui de
    l'habillage sans eau, au bit près ; les replis sont là où le green ou
    une boîte touchait l'eau."""
    fixed = cut = 0
    for case, style, relief, holes, plain, wet in corpus:
        water = water_mask(relief)
        obstacles = fairway_obstacles(wet.holes, wet.green_pairs)
        for order, hd in wet.holes.items():
            old = plain[order]
            if hd.water_fix is None:
                assert old.fairway_removed == () and old.fairway_empty_cause is None
                if (hd.fairway, hd.fairway_removed, hd.fairway_empty_cause) != (old.fairway,
                                                                                (), None):
                    cut += 1
                    seed, hole = case[2], holes[order]
                    uncut = water_fairway(hole, build_hole_geometry(hole).core,
                                          fw.FAIRWAY_STYLES[style], fairway_rng(seed, order),
                                          fairway_profile_rng(seed, order), hd.tees,
                                          hd.green.outline, obstacles, None, FAIRWAY_WATER_CUT)
                    assert uncut.shapes == old.fairway, (case, style, order)
                    hd = dataclasses.replace(hd, fairway=old.fairway, fairway_removed=(),
                                             fairway_empty_cause=None)
                assert hd == old, (case, style, order)
                continue
            fixed += 1
            fix = hd.water_fix
            assert fix.green_changed == (not is_dry(old.green.outline, water, 0.0))
            if not fix.green_changed:
                assert hd.green == old.green
            if not fix.tees_changed:
                assert (hd.tees, hd.tee_fallback_cause) == (old.tees, old.tee_fallback_cause)
    assert fixed and cut


def test_corpus_shifted_greens(corpus):
    """Green replié sans être insulaire (links seulement : décalé, ou tourné
    ou réduit, décalé ou non) : dans le cœur, drapeau routé dedans à au moins
    ``GREEN_FLAG_EDGE`` du bord, aire ≥ (1 − ``GREEN_WATER_MAX_REDUCTION``)
    × l'aire de la forme tirée ; décalé seul, il garde forme, taille et type
    (translation du green tiré, aux arrondis près)."""
    shifted = 0
    for case, style, relief, holes, plain, wet in corpus:
        for order, hd in wet.holes.items():
            fix = hd.water_fix
            if fix is None or not fix.green_changed or fix.green_island:
                continue
            assert style == "links" and STYLE_SPECS[style].water_green == "shift"
            hole = holes[order]
            core = np.asarray(build_hole_geometry(hole).core)
            assert polygon_inside(np.asarray(hd.green.outline), core)
            assert flag_edge_distance(hd.green.outline,
                                      (hole.green.x, hole.green.y)) >= GREEN_FLAG_EDGE
            assert hd.green.area >= (1.0 - GREEN_WATER_MAX_REDUCTION) * plain[order].green.area
            assert hd.green.island is None
            if fix.green_shift is None:
                continue
            shifted += 1
            old = plain[order].green
            if fix.green_rotation == 0.0 and fix.green_steps == 0:
                moved = np.asarray(old.outline) + np.asarray(fix.green_shift)
                assert np.abs(np.asarray(hd.green.outline) - moved).max() <= 0.0051
                assert hd.green.kind == old.kind
                assert abs(hd.green.area - old.area) <= 0.1
    assert shifted >= 10


def test_corpus_island_greens(corpus):
    """Green insulaire (parkland ; links en dernier recours, absent de
    l'instantané) : forme tirée intacte (green sans eau au bit près, hors
    ``island``), cellules remontées = cellules d'eau qu'il recouvre,
    ``height`` = minimum du relief de la partie émergée, ≥ ``WATER_LEVEL`` ;
    le relief n'est pas modifié."""
    islands = 0
    for case, style, relief, holes, plain, wet in corpus:
        before = relief.copy()
        water = water_mask(relief)
        for order, hd in wet.holes.items():
            island = hd.green.island
            if island is None:
                continue
            islands += 1
            assert style == "parkland" or hd.water_fix.green_island_fallback
            assert hd.water_fix.green_island
            assert dataclasses.replace(hd.green, island=None) == plain[order].green
            footprint = footprint_cells(hd.green.outline, water.width, water.height)
            wet_cells = water.water[footprint[:, 1], footprint[:, 0]]
            raised = raised_cells(hd.green.outline, water)
            assert np.array_equal(footprint[wet_cells], raised)
            emerged = footprint[~wet_cells]
            assert len(emerged) and len(raised) == island.raised_area
            assert island.height == float(relief[emerged[:, 1], emerged[:, 0]].min())
            assert island.height >= WATER_LEVEL
        assert np.array_equal(relief, before)
    assert islands >= 5


def test_corpus_tees(corpus):
    """Boîtes : aucune retirée (même nombre et même cause de bascule que sans
    eau, nombre par par de la règle) ; remontées (``TeeBox.island``) au rang
    noté, cellules remontées = cellules d'eau de son trou qu'elle touche, à
    l'altitude minimale de sa partie émergée, ou à ``WATER_LEVEL +
    SUBMERGED_TEE_LIFT`` (un bloc au-dessus de l'eau) si elle est entièrement
    immergée (compté à part) ; décalées en travers
    perpendiculairement à l'axe, même sens ; boîte arrière inchangée sauf
    glissement d'au plus ``TEE_BACK_SLIDE_MAX`` dans l'axe (un seul cas
    réel)."""
    slid, lateral, raised = set(), 0, set()
    for case, style, relief, holes, plain, wet in corpus:
        water = water_mask(relief)
        for order, hd in wet.holes.items():
            old, fix = plain[order], hd.water_fix
            assert len(hd.tees) == len(old.tees), (case, style, order)
            assert hd.tee_fallback_cause == old.tee_fallback_cause
            if hd.tee_fallback_cause is None:
                assert len(hd.tees) in PAR_RULE[holes[order].par], (case, style, order)
            ranks = tuple(box.rank for box in hd.tees if box.island is not None)
            assert ranks == (() if fix is None else fix.tees_raised)
            seen = effective_water(water, (hd.green,))
            for box in hd.tees:
                if box.island is None:
                    continue
                raised.add((*case, order, box.rank))
                assert box.island == tee_island_of(box.outline, relief, seen)
                footprint = footprint_cells(box.outline, water.width, water.height)
                wet_cells = seen.water[footprint[:, 1], footprint[:, 0]]
                assert box.island.raised_area == wet_cells.sum() > 0
                assert box.island.submerged == (box.rank in fix.tees_submerged)
                if box.island.submerged:
                    assert wet_cells.all()
                    assert box.island.height == WATER_LEVEL + SUBMERGED_TEE_LIFT == 61.0
                else:
                    emerged = footprint[~wet_cells]
                    assert box.island.height == float(
                        relief[emerged[:, 1], emerged[:, 0]].min()) >= WATER_LEVEL
            if fix is not None and fix.back_slide:
                slid.add((*case, order))
                assert 0.0 < abs(fix.back_slide) <= TEE_BACK_SLIDE_MAX
                (bx, by), (ox, oy) = hd.tees[0].center, old.tees[0].center
                hx, hy = old.tees[0].heading
                assert (bx - ox) * hx + (by - oy) * hy == pytest.approx(fix.back_slide)
                assert (bx - ox) * hy - (by - oy) * hx == pytest.approx(0.0, abs=1e-9)
            else:
                assert dataclasses.replace(hd.tees[0], island=None) == old.tees[0]
            if fix is not None and fix.tees_shifted:
                lateral += 1
                hole = holes[order]
                for box in hd.tees[1:]:
                    assert box.heading == old.tees[0].heading
                tx, ty = hole.tee.x, hole.tee.y
                hx, hy = hd.tees[0].heading
                off = [abs((b.center[0] - tx) * hy - (b.center[1] - ty) * hx) for b in hd.tees]
                assert max(off) > 0.0
    assert slid == {BACK_SLID}
    assert lateral >= 2
    assert (*RAISED, 1) in raised and (*RAISED, 2) in raised


# --- dernier recours links, paires, export ---------------------------------------------

def test_links_last_resort_island(snapshot, monkeypatch):
    """Si rien ne se décale au sec (décalage, rotation et paliers neutralisés),
    le green links devient insulaire, compté à part
    (``green_island_fallback``)."""
    width, height, seed = REAL[0]
    relief = load_terrain(seed, width, height)
    monkeypatch.setattr(green_module, "shifted_greens", lambda *args: iter(()))
    monkeypatch.setattr(green_module, "GREEN_WATER_ROTATIONS", ())
    monkeypatch.setattr(green_module, "GREEN_WATER_AREA_STEPS", 0)
    wet = dress_course(_result(snapshot[REAL[0]]), seed=seed, style="links", relief=relief)
    plain = dress_course(_result(snapshot[REAL[0]]), seed=seed, style="links")
    hd = wet[14]
    assert hd.water_fix.green_island and hd.water_fix.green_island_fallback
    assert dataclasses.replace(hd.green, island=None) == plain[14].green


def test_pair_touching_water_is_rejected_with_cause_eau():
    """Paire de production (land-30 muirfield seed 1, 10/17) : une cellule
    d'eau fabriquée sous le col (loin des deux greens) la fait refuser, cause
    ``eau`` ; greens et départs inchangés."""
    assert REJECT_WATER == "eau" and REJECT_WATER in PAIR_REJECTION_CAUSES
    case = json.loads((DATA / "green_pair_r3f_layout.json").read_text(encoding="utf-8"))
    case = case["layouts"][0]
    seed, layout = case["seed"], CourseLayout.from_dict(case["layout"])
    result = SimpleNamespace(layout=layout)
    plain = dress_course(result, seed=seed, style="links")
    (pair,) = plain.green_pairs
    gi, gj = plain[pair.i].green, plain[pair.j].green
    middle = ((gi.center[0] + gj.center[0]) / 2.0, (gi.center[1] + gj.center[1]) / 2.0)
    relief = np.full((int(layout.height), int(layout.width)), WATER_LEVEL + 10.0,
                     dtype=np.float32)
    relief[int(middle[1]), int(middle[0])] = WATER_LEVEL - 5.0
    water = water_mask(relief)
    assert water_area(pair.outline, water) > 0.0
    assert is_dry(gi.outline, water, 0.0) and is_dry(gj.outline, water, 0.0)
    wet = dress_course(result, seed=seed, style="links", relief=relief)
    assert (pair.i, pair.j) not in {(p.i, p.j) for p in wet.green_pairs}
    assert [(r.i, r.j, r.cause) for r in wet.pair_rejections if r.cause == "eau"] == [
        (pair.i, pair.j, "eau")]
    for order, hd in wet.holes.items():
        assert (hd.green, hd.tees) == (plain[order].green, plain[order].tees)


def test_pair_with_an_island_green_is_rejected():
    """Pas d'insulaire pour un green double : une paire dont un green est
    insulaire est refusée, cause ``eau``, même sans eau sous sa forme."""
    case = json.loads((DATA / "green_pair_r3f_layout.json").read_text(encoding="utf-8"))
    case = case["layouts"][0]
    seed, layout = case["seed"], CourseLayout.from_dict(case["layout"])
    plain = dress_course(SimpleNamespace(layout=layout), seed=seed, style="links")
    (pair,) = plain.green_pairs
    holes = dict(plain.holes)
    holes[pair.i] = dataclasses.replace(holes[pair.i], green=dataclasses.replace(
        holes[pair.i].green, island=GreenIsland(height=61.0, raised_area=3.0)))
    cores = {h.order: build_hole_geometry(h).core for h in layout.holes}
    pairs, rejections = pair_selection(layout, holes, cores, "links", pair_rng(seed), None)
    assert (pair.i, pair.j) not in {(p.i, p.j) for p in pairs}
    assert (pair.i, pair.j, "eau") in {(r.i, r.j, r.cause) for r in rejections}


def test_island_exported_in_features(corpus):
    """JSON 3.1 : ``features.green.island`` (hauteur et aire remontée,
    2 décimales) pour un green insulaire, absent sinon."""
    seen = {True: 0, False: 0}
    for *_, wet in corpus[:20]:
        for hd in wet.holes.values():
            green = _features_v31(hd)["green"]
            island = hd.green.island
            seen[island is not None] += 1
            if island is None:
                assert "island" not in green
            else:
                assert green["island"] == {"height": round(island.height, 2),
                                           "raised_area": round(island.raised_area, 2)}
    assert seen[True] and seen[False]


# --- boîtes remontées, eau d'un trou, règle des 30 % ---------------------------------------

def _two_box_hole(snapshot):
    """Premier par 4 à deux boîtes tirées de l'instantané 400x300/26, sans
    eau : ``(trou, cœur, green, boîtes, seed)``."""
    for hole in snapshot[REAL[0]]:
        core = build_hole_geometry(hole).core
        green = green_shape(hole, core, green_rng(26, hole.order), STYLE_SPECS["links"])
        tees, cause = tee_boxes(hole, core, green.outline, tee_rng(26, hole.order))
        if hole.par == 4 and len(tees) == 2 and cause is None:
            return hole, core, green, tees
    raise AssertionError("aucun par 4 à deux boîtes")


def _band_relief(hole, shape, along, checker=False):
    """Relief 300 × 400 au sec (70 + ix/1000), eau (50) sur les cellules dont
    le centre se projette dans ``along`` (blocs depuis le tee, le long du
    premier segment), en travers sur toute la carte ; ``checker`` : une
    cellule sur deux seulement (damier) ; partie émergée la plus basse
    imposée à 61,25 sous la boîte avancée tirée."""
    relief = np.fromfunction(lambda iy, ix: 70.0 + ix / 1000.0, shape).astype(np.float32)
    a, b = hole.axis[0], hole.axis[1]
    n = math.hypot(b.x - a.x, b.y - a.y)
    hx, hy = (b.x - a.x) / n, (b.y - a.y) / n
    iy, ix = np.indices(shape)
    d = (ix + 0.5 - a.x) * hx + (iy + 0.5 - a.y) * hy
    wet = (d >= along[0]) & (d <= along[1])
    if checker:
        wet &= (ix + iy) % 2 == 0
    relief[wet] = 50.0
    return relief


def test_advanced_box_raised_partly_emerged(snapshot):
    """Eau en damier sur toute la plage d'étalement et en travers : aucune
    position au sec, la boîte avancée est remontée à sa position tirée
    (aucune retirée), cellules d'eau touchées remontées à l'altitude
    minimale de sa partie émergée ; boîte arrière intacte."""
    hole, core, green, plain = _two_box_hole(snapshot)
    relief = _band_relief(hole, (300, 400), (6.0, 30.0), checker=True)
    front = plain[1]
    footprint = footprint_cells(front.outline, 400, 300)
    water = water_mask(relief)
    dry_cells = footprint[~water.water[footprint[:, 1], footprint[:, 0]]]
    relief[dry_cells[0, 1], dry_cells[0, 0]] = 61.25
    water = water_mask(relief)
    tees, cause, fix = dry_tee_boxes(hole, core, green.outline, tee_rng(26, hole.order),
                                     water, relief)
    assert cause is None and len(tees) == 2
    assert tees[0] == dataclasses.replace(plain[0])
    assert dataclasses.replace(tees[1], island=None) == front
    assert fix.tees_raised == (1,) and fix.tees_submerged == ()
    assert (fix.tees_moved, fix.tees_shifted, fix.back_slide) == ((), (), 0.0)
    wet_cells = water.water[footprint[:, 1], footprint[:, 0]]
    assert tees[1].island == TeeIsland(height=61.25, raised_area=float(wet_cells.sum()))
    seen = effective_water(water, tees)
    assert all(is_dry(box.outline, seen, 0.0) for box in tees)
    with pytest.raises(ValueError):
        dry_tee_boxes(hole, core, green.outline, tee_rng(26, hole.order), water)


def test_boxes_fully_submerged_and_back_box_raised(snapshot):
    """Eau pleine de l'arrière du tee à la plage d'étalement : la boîte
    arrière ne glisse pas au sec, elle est remontée sur le tee routé ; les
    deux boîtes, entièrement immergées, remontent à un bloc au-dessus de
    l'eau, ``WATER_LEVEL + SUBMERGED_TEE_LIFT`` (``submerged``, compté à
    part)."""
    hole, core, green, plain = _two_box_hole(snapshot)
    relief = _band_relief(hole, (300, 400), (-8.0, 30.0))
    water = water_mask(relief)
    tees, cause, fix = dry_tee_boxes(hole, core, green.outline, tee_rng(26, hole.order),
                                     water, relief)
    assert cause is None and len(tees) == 2
    assert [dataclasses.replace(box, island=None) for box in tees] == list(plain)
    assert fix.tees_raised == (0, 1) and fix.tees_submerged == (0, 1)
    assert fix.back_slide == 0.0 and tees[0].center == (hole.tee.x, hole.tee.y)
    for box in tees:
        assert box.island == TeeIsland(height=WATER_LEVEL + SUBMERGED_TEE_LIFT,
                                       raised_area=box.island.raised_area, submerged=True)
        assert box.island.height == 61.0
        assert box.island.raised_area == len(footprint_cells(box.outline, 400, 300))


def test_box_never_raised_on_cells_raised_by_another_hole(snapshot):
    """Cellules remontées par un AUTRE trou (``raised``) : de l'eau pour la
    boîte (au sec par ailleurs, elle ne s'y pose pas sans se replier), et
    jamais remontées une seconde fois (la boîte se remonte ailleurs)."""
    hole, core, green, plain = _two_box_hole(snapshot)
    front = plain[1]
    # (1) la bande d'un autre trou sous la boîte tirée, rien d'autre : la
    # boîte se replie comme sur l'eau
    relief = np.full((300, 400), 70.0, dtype=np.float32)
    band = footprint_cells(front.outline, 400, 300)
    relief[band[:, 1], band[:, 0]] = 50.0
    water = water_mask(relief)
    other = np.array(water.water)                 # remontées par un autre trou
    tees, _, fix = dry_tee_boxes(hole, core, green.outline, tee_rng(26, hole.order),
                                 water, relief, other)
    assert tees[1].island is None and fix.tees_moved == (1,)
    assert is_dry(tees[1].outline, water, 0.0)
    # (2) eau en damier partout : la boîte se remonte, mais pas sur la bande
    relief = _band_relief(hole, (300, 400), (6.0, 30.0), checker=True)
    water = water_mask(relief)
    other = np.zeros_like(water.water)
    other[band[:, 1], band[:, 0]] = water.water[band[:, 1], band[:, 0]]
    free, _, free_fix = dry_tee_boxes(hole, core, green.outline, tee_rng(26, hole.order),
                                      water, relief)
    tees, _, fix = dry_tee_boxes(hole, core, green.outline, tee_rng(26, hole.order),
                                 water, relief, other)
    assert free_fix.tees_raised == fix.tees_raised == (1,)
    assert dataclasses.replace(free[1], island=None) == front
    assert tees[1].outline != front.outline
    assert is_dry(tees[1].outline, WaterMask(water=other), 0.0)


def test_other_holes_see_a_raised_band_as_water(snapshot, monkeypatch):
    """Production (``dress_course``) : chaque trou pose ses boîtes sur SON
    eau effective. En parkland sur 400x300/14, les greens des trous 4 et 15
    sont insulaires : chacun de ces trous voit l'eau réelle moins SES
    cellules remontées, tous les autres trous l'eau réelle, bandes remontées
    comprises ; ``raised`` contient les cellules des deux greens pour tous
    les trous."""
    width, height, seed = 400, 300, 14
    relief = load_terrain(seed, width, height)
    water = water_mask(relief)
    seen = {}
    real = course_module.dry_tee_boxes

    def spy(hole, core, outline, rng, water_arg, relief_arg, raised):
        seen[hole.order] = (water_arg, raised)
        return real(hole, core, outline, rng, water_arg, relief_arg, raised)

    monkeypatch.setattr(course_module, "dry_tee_boxes", spy)
    wet = dress_course(_result(snapshot[(width, height, seed)]), seed=seed, style="parkland",
                       relief=relief)
    owners = [order for order, hd in wet.holes.items() if hd.green.island is not None]
    assert owners == [4, 15] and len(seen) == 18
    for owner in owners:
        band = raised_cells(wet[owner].green.outline, water)
        assert len(band)
        for order, (water_arg, raised) in seen.items():
            assert raised[band[:, 1], band[:, 0]].all()
            cells = water_arg.water[band[:, 1], band[:, 0]]
            assert cells.all() if order != owner else not cells.any()
            assert np.array_equal(water_arg.water,
                                  effective_water(water, (wet[order].green,)).water)


def test_rule_30_percent(snapshot, monkeypatch):
    """Règle des 30 % : le green links du trou 4 de 400x300/14, sans la
    règle, est retenu réduit de plus de 30 % de l'aire de la forme tirée ;
    avec elle, il devient insulaire en dernier recours, forme tirée intacte."""
    width, height, seed, order = RULE_30
    relief = load_terrain(seed, width, height)
    holes = snapshot[(width, height, seed)]
    ruled = dress_course(_result(holes), seed=seed, style="links", relief=relief)[order]
    monkeypatch.setattr(green_module, "GREEN_WATER_MAX_REDUCTION", 1.0)
    free = dress_course(_result(holes), seed=seed, style="links", relief=relief)[order]
    plain = dress_course(_result(holes), seed=seed, style="links")[order]
    assert free.green.island is None and free.water_fix.green_steps > 0
    assert free.green.area < (1.0 - GREEN_WATER_MAX_REDUCTION) * plain.green.area
    assert ruled.water_fix.green_island and ruled.water_fix.green_island_fallback
    assert dataclasses.replace(ruled.green, island=None) == plain.green


def test_rule_30_percent_keeps_smaller_reduction(snapshot, monkeypatch):
    """Règle des 30 % : le green links du trou 5 de 400x300/28, réduit de
    30 % ou moins de l'aire de la forme tirée, est retenu (réduit puis
    décalé), sans passer en insulaire, comme sans la règle."""
    width, height, seed, order = RULE_30_KEPT
    relief = load_terrain(seed, width, height)
    holes = snapshot[(width, height, seed)]
    ruled = dress_course(_result(holes), seed=seed, style="links", relief=relief)[order]
    plain = dress_course(_result(holes), seed=seed, style="links")[order]
    fix = ruled.water_fix
    assert ruled.green.island is None and not fix.green_island
    assert fix.green_steps > 0 and fix.green_shift is not None
    assert ((1.0 - GREEN_WATER_MAX_REDUCTION) * plain.green.area <= ruled.green.area
            < plain.green.area)
    monkeypatch.setattr(green_module, "GREEN_WATER_MAX_REDUCTION", 1.0)
    free = dress_course(_result(holes), seed=seed, style="links", relief=relief)[order]
    assert (free.green, free.water_fix) == (ruled.green, fix)


def test_raised_box_exported_in_features(snapshot):
    """JSON 3.1 : ``features.tees[].island`` (hauteur, aire remontée,
    ``submerged``) pour une boîte remontée, absent sinon."""
    width, height, seed, order = RAISED
    relief = load_terrain(seed, width, height)
    wet = dress_course(_result(snapshot[(width, height, seed)]), seed=seed, style="links",
                       relief=relief)
    for hd in wet.holes.values():
        for item, box in zip(_features_v31(hd)["tees"], hd.tees):
            if box.island is None:
                assert "island" not in item
            else:
                assert item["island"] == {"height": round(box.island.height, 2),
                                          "raised_area": round(box.island.raised_area, 2),
                                          "submerged": box.island.submerged}
    assert [box.rank for box in wet[order].tees if box.island is not None] == [1, 2]
