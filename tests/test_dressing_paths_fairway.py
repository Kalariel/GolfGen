"""Règle du fairway des chemins (``golfgen.dressing.paths.fairway_rule``) :
défaut = la correction à surcoût 2, puis chacun des
trois volets de la correction sur des scènes synthétiques : a) surcoût sur toute la largeur (fairway dilaté de la
demi-largeur, ``rule.cost`` par bloc), b) ligne droite seulement hors du
fairway, c) tension et virages sans case de fairway de plus."""

from __future__ import annotations

from dataclasses import replace

import numpy as np
import pytest

from golfgen.dressing.paths import FairwayRule, geometry, scene as pscene
from golfgen.dressing.paths.bends import bend_route
from golfgen.dressing.paths.fairway_rule import DEFAULT_COST
from golfgen.dressing.paths.grid import build_grid, dilate, shortest_path
from golfgen.dressing.paths.route import (fairway_cells, nearest_on, reproject_ends, route_link,
                                          tighten)
from golfgen.dressing.paths.scene import Obstacle, Scene, obstacle_mask


def _surface(kind, ref, x0, y0, x1, y1):
    xs, ys = np.meshgrid(np.arange(x0, x1), np.arange(y0, y1))
    poly = np.array([(x0, y0), (x1, y0), (x1, y1), (x0, y1)], dtype=float)
    return Obstacle(kind, ref, np.column_stack((xs.ravel(), ys.ravel())), poly)


def _rule(cost=0.5, full_width=False, dry_straight=False, no_increase=False):
    """Volets choisis un à un (aucun par défaut, surcoût du centre à 0,5)."""
    return FairwayRule(cost, full_width, dry_straight, no_increase)


NO_VOLET = _rule()


def _scene(fairway, green_box, tee_box, rule=NO_VOLET, path_width=2.0):
    h, w = fairway.shape
    green = _surface("green", "green 1", *green_box)
    tee = _surface("tee", "tee 2/0", *tee_box)
    start, end = geometry.closest_points(green.polygon, tee.polygon)
    link = pscene.LinkEnds(0, 1, 2, start, end, frozenset({green.ref, tee.ref}),
                           green.ref, tee.ref, green.polygon, tee.polygon)
    sc = Scene(width=w, height=h, path_width=path_width, relief=np.full((h, w), 64.0),
               water=np.zeros((h, w), bool), fairway=fairway, obstacles=(green, tee),
               links=(link,), seed=7, fairway_rule=rule)
    return sc, link


def _band(h=60, w=80, rows=(25, 30)):
    fairway = np.zeros((h, w), bool)
    fairway[rows[0]:rows[1], :] = True
    return fairway


def test_default_rule_is_the_correction_at_cost_2():
    assert FairwayRule() == FairwayRule.corrected(2.0) == FairwayRule(2.0, True, True, True)
    assert DEFAULT_COST == 2.0
    assert pscene.Scene.__dataclass_fields__["fairway_rule"].default == FairwayRule()


@pytest.mark.parametrize("cost", [-0.5, -1e-9, float("nan")])
def test_negative_cost_is_refused(cost):
    """Surcoût négatif : l'heuristique octile de l'A* ne serait plus
    admissible ; 0 reste permis."""
    with pytest.raises(ValueError):
        FairwayRule(cost)
    assert FairwayRule(0.0).cost == 0.0


# === a) surcoût sur toute la largeur ===

def test_full_width_dilates_the_fairway_by_the_half_width():
    """Links (largeur 2) : une case de plus de chaque côté de la bande ;
    l'A* paie ``rule.cost`` par bloc sur ce fairway dilaté."""
    fairway = _band()
    plain, link = _scene(np.zeros_like(fairway), (30, 5, 35, 10), (31, 50, 34, 53))
    costs = {}
    for name, rule in (("none", None), ("default", NO_VOLET),
                       ("wide", _rule(2.0, full_width=True))):
        sc = plain if rule is None else replace(plain, fairway=fairway, fairway_rule=rule)
        grid = build_grid(sc, link, 15)
        if name == "wide":
            rows = np.flatnonzero(grid.fairway.any(axis=1)) + grid.y0
            assert (rows.min(), rows.max()) == (24, 30)          # 25..29 dilaté d'une case
            sub = sc.fairway[grid.y0:grid.y0 + grid.fairway.shape[0],
                             grid.x0:grid.x0 + grid.fairway.shape[1]]
            assert np.array_equal(grid.fairway, dilate(sub, 1.0))
        cells, cost = shortest_path(grid, grid.sources, grid.goal, allow_water=False)
        costs[name] = cost
    # traversée droite : 5 rangées × 0,5 par défaut, 7 rangées × 2 avec la largeur
    assert np.isclose(costs["default"] - costs["none"], 5 * 0.5)
    assert np.isclose(costs["wide"] - costs["none"], 7 * 2.0)


def test_full_width_keeps_the_band_off_a_fairway_it_can_skirt():
    """Fairway le long de la ligne directe (rangées 7 à 19, ligne en y = 20),
    de la place à côté : le surcoût du centre seul laisse le trait (rangées
    19 et 20) mordre le fairway, la largeur entière l'en écarte."""
    fairway = np.zeros((40, 80), bool)
    fairway[7:20, 18:62] = True                  # rangées 7..19, la ligne est en y = 20
    touched = {}
    for name, rule in (("default", _rule(4.0)), ("wide", _rule(4.0, True))):
        sc, link = _scene(fairway, (5, 17, 10, 25), (70, 20, 74, 21), rule)
        assert link.start[1] == link.end[1] == 20.0
        grid = build_grid(sc, link, 15)
        cells, _ = shortest_path(grid, grid.sources, grid.goal, allow_water=False)
        centres = [(c + grid.x0 + 0.5, r + grid.y0 + 0.5) for r, c in cells[1:-1]]
        touched[name] = fairway_cells(sc, centres)
    assert touched["default"] > 0 and touched["wide"] == 0


def test_full_width_parkland_width_3():
    """Parkland (largeur 3, demi-largeur 1,5) : même dilatation d'une case
    (une case à deux rangées a son centre à 1,5 de la bande, exclue), un
    trait de 3 sur une case voisine de la bande la touche ; le défaut écarte
    le trait d'un fairway contournable, sans volets il le laisse mordre."""
    fairway = _band()
    sc, link = _scene(fairway, (30, 5, 35, 10), (31, 50, 34, 53), FairwayRule(), path_width=3.0)
    grid = build_grid(sc, link, 15)
    rows = np.flatnonzero(grid.fairway.any(axis=1)) + grid.y0
    assert (rows.min(), rows.max()) == (24, 30)
    sub = sc.fairway[grid.y0:grid.y0 + grid.fairway.shape[0],
                     grid.x0:grid.x0 + grid.fairway.shape[1]]
    assert np.array_equal(grid.fairway, dilate(sub, 1.5))
    assert fairway_cells(sc, ((10.5, 23.5), (60.5, 23.5))) == 0
    assert fairway_cells(sc, ((10.5, 24.5), (60.5, 24.5))) > 0
    skirt = np.zeros((40, 80), bool)
    skirt[7:20, 18:62] = True
    touched = {}
    for name, rule in (("sans volets", NO_VOLET), ("default", FairwayRule())):
        sc, link = _scene(skirt, (5, 17, 10, 25), (70, 20, 74, 21), rule, path_width=3.0)
        route = route_link(sc, link)
        touched[name] = fairway_cells(sc, route.points)
        if name == "default":
            assert route.length < 1.05 * link.direct
    assert touched["sans volets"] > 0 and touched["default"] == 0


# === b) ligne droite hors du fairway ===

def test_straight_line_is_refused_when_its_band_touches_the_fairway():
    fairway = np.zeros((60, 80), bool)
    fairway[18:24, 34:40] = True                 # sur la ligne directe, contournable
    default, link = _scene(fairway, (5, 17, 10, 25), (70, 20, 74, 21))
    route = route_link(default, link)
    assert route.status == "straight" and len(route.points) == 2
    assert fairway_cells(default, route.points) > 0
    strict = replace(default, fairway_rule=_rule(dry_straight=True))
    route = route_link(strict, link)
    assert route.points != (link.start, link.end)
    fixed = replace(default, fairway_rule=FairwayRule.corrected(2.0))
    route = route_link(fixed, link)
    assert fairway_cells(fixed, route.points) == 0
    assert route.length < 1.5 * link.direct


def test_straight_line_off_the_fairway_is_unchanged():
    fairway = np.zeros((60, 80), bool)
    fairway[40:50, 30:50] = True                 # loin de la ligne directe
    default, link = _scene(fairway, (5, 17, 10, 25), (70, 20, 74, 21))
    fixed = replace(default, fairway_rule=FairwayRule.corrected(4.0))
    a, b = route_link(default, link), route_link(fixed, link)
    assert a.status == b.status == "straight" and a.points == b.points


def test_fairway_against_an_endpoint():
    """Fairway collé au départ (contre sa face vers le green) : la ligne
    droite, qui le touche, est refusée par le défaut ; contournable, l'A*
    l'évite ; sur toute la hauteur (inévitable), l'A* retrouve la droite
    (``slide``), sans plus de fairway qu'elle."""
    for rows, avoidable in ((slice(14, 28), True), (slice(None), False)):
        fairway = np.zeros((60, 80), bool)
        fairway[rows, 34:40] = True              # cases x 34..39, le départ commence en x = 40
        loose, link = _scene(fairway, (5, 17, 10, 25), (40, 18, 44, 22))
        straight = (link.start, link.end)
        assert fairway_cells(loose, straight) > 0
        old = route_link(loose, link)
        assert old.status == "straight" and not old.slide and old.points == straight
        sc = replace(loose, fairway_rule=FairwayRule())
        route = route_link(sc, link)
        if avoidable:
            assert route.status == "detour" and fairway_cells(sc, route.points) == 0
            assert route.length < 1.3 * link.direct
        else:
            assert route.status == "straight" and route.slide and len(route.points) == 2
            assert fairway_cells(sc, route.points) <= fairway_cells(sc, straight)


# === c) tension et virages sans fairway de plus ===

def test_tension_keeps_a_forced_crossing_at_its_shortest():
    """Bande de fairway sur toute la largeur, extrémités en diagonale : l'A*
    la traverse au plus court ; sans le volet c, la tension (plafond du
    tronçon) coupe en diagonale à travers le fairway et ajoute des cases,
    avec lui le trait tendu n'en a pas plus que le brut, et chaque
    raccourci n'en a pas plus que le tronçon remplacé."""
    fairway = _band(rows=(25, 35))
    wide, link = _scene(fairway, (5, 3, 10, 8), (66, 52, 70, 56),
                        _rule(4.0, full_width=True, dry_straight=True))
    loose = route_link(wide, link)
    assert fairway_cells(wide, loose.points) > fairway_cells(wide, loose.raw)
    fenced = replace(wide, fairway_rule=FairwayRule.corrected(4.0))
    route = route_link(fenced, link)
    assert fairway_cells(fenced, route.points) <= fairway_cells(fenced, route.raw)
    assert fairway_cells(fenced, route.points) < fairway_cells(wide, loose.points)
    raw = list(route.raw)
    tight = tighten(route.grid, raw, allow_water=False, scene=fenced)
    idx = [raw.index(p) for p in tight]
    for i, j in zip(idx[:-1], idx[1:]):
        assert fairway_cells(fenced, (raw[i], raw[j])) <= fairway_cells(fenced, raw[i:j + 1])


def test_bend_is_refused_when_it_adds_fairway():
    """Liaison droite de 52 blocs entre deux fairways : le virage tiré
    pose son trait sur le fairway ; le volet c le refuse
    (``fairway_rejects``, un décalage réduit peut passer), le trait n'a
    aucune case de fairway."""
    fairway = np.zeros((40, 80), bool)
    fairway[:16, 15:60] = True
    fairway[23:, 15:60] = True
    results = {}
    for name, rule in (("default", NO_VOLET), ("fenced", _rule(no_increase=True))):
        sc, link = _scene(fairway, (5, 17, 10, 25), (62, 19, 66, 20), rule)
        route = route_link(sc, link)
        assert link.start[1] == link.end[1] == 19.0
        assert route.status == "straight"
        points, report = bend_route(sc, route, route.points, 0, 1, obstacle_mask(sc))
        results[name] = (fairway_cells(sc, route.points), fairway_cells(sc, points), report)
    base, bent, report = results["default"]
    assert report.placed == 1 and bent > base
    base, bent, report = results["fenced"]
    assert report.fairway_rejects > 0 and bent == base == 0


def test_reproject_ends_keeps_the_end_when_it_adds_fairway():
    """Bout reprojeté vers son nouveau voisin : le coin du green, plus près,
    ferait passer le segment sur le fairway (11 cases contre 4) ; avec le
    volet c, l'ancien bout est gardé (au lieu de laisser la tension entière
    être refusée plus loin), sans lui il est remplacé. Surcoût nul : seul
    le compte de cases juge (le plafond ne bloque pas)."""
    fairway = np.zeros((60, 80), bool)
    fairway[23:28, 23:27] = True                 # sur la diagonale du coin (20, 20)
    sc, link = _scene(fairway, (10, 10, 20, 20), (60, 50, 64, 53),
                      _rule(0.0, no_increase=True))
    grid = build_grid(sc, link, 30)
    old, nxt = (20.0, 12.0), (30.0, 30.0)
    cand = nearest_on(link.src_poly, nxt)
    assert cand == (20.0, 20.0)
    assert fairway_cells(sc, (cand, nxt)) > fairway_cells(sc, (old, nxt)) > 0
    points = [old, nxt, link.end]
    kept = reproject_ends(link, grid, points, allow_water=False, ends=(True, False), scene=sc)
    assert kept == points
    moved = reproject_ends(link, grid, points, allow_water=False, ends=(True, False))
    assert moved[0] == cand and moved[1:] == points[1:]
    loose = replace(sc, fairway_rule=_rule(0.0))
    grid = build_grid(loose, link, 30)
    assert reproject_ends(link, grid, points, allow_water=False, ends=(True, False),
                          scene=loose)[0] == cand
