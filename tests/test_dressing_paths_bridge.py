"""Règle des ponts des chemins (``BridgeRule``) : défaut = règle du gain à
25 %, avec les corrections ; la règle du gain ; le surcoût (forme du tracé
mouillé) ; la forme
``bends`` (virages doux, comptés sur toute la liaison) ; les corrections (un
seul morceau, eau reliée à la traversée, bouts avec surface, largeur rendue
côté sec) ; invariants d'un parcours fabriqué posé avec les virages doux."""

from __future__ import annotations

from dataclasses import replace
import math

import numpy as np
import pytest

from golfgen.dressing import rng
from golfgen.dressing.paths import BridgeRule, PathError, geometry, scene as pscene
from golfgen.dressing.paths import blocks as pblocks, bridge_rule as pbridge, course as pcourse
from golfgen.dressing.paths.bends import BEND_END_MARGIN, BEND_GAP, BEND_HALF_RATIO, make_bend
from golfgen.dressing.paths.blocks import bridge_water, link_blocks, path_blocks, water_cuts
from golfgen.dressing.paths.bridge_shape import Candidate, bend_bridge, needed, select
from golfgen.dressing.paths.course import place_paths
from golfgen.dressing.paths.geometry import polyline_length
from golfgen.dressing.paths.grid import build_grid, shortest_path
from golfgen.dressing.paths.route import Route, route_link, water_spans
from golfgen.dressing.paths.scene import Obstacle, Scene, obstacle_mask
from tests.paths_corpus import fabricated_variant, stub_course_input


def _surface(kind, ref, x0, y0, x1, y1):
    xs, ys = np.meshgrid(np.arange(x0, x1), np.arange(y0, y1))
    poly = np.array([(x0, y0), (x1, y0), (x1, y1), (x0, y1)], dtype=float)
    return Obstacle(kind, ref, np.column_stack((xs.ravel(), ys.ravel())), poly)


# règle par défaut, pont droit (sans virages doux)
_STRAIGHT = BridgeRule.gained(pbridge.DEFAULT_GAIN, shape="straight")


def _scene(water, green_box, tee_box, rule=BridgeRule()):
    h, w = water.shape
    green = _surface("green", "green 1", *green_box)
    tee = _surface("tee", "tee 2/0", *tee_box)
    start, end = geometry.closest_points(green.polygon, tee.polygon)
    link = pscene.LinkEnds(0, 1, 2, start, end, frozenset({green.ref, tee.ref}),
                           green.ref, tee.ref, green.polygon, tee.polygon)
    sc = Scene(width=w, height=h, path_width=2.0, relief=np.full((h, w), 64.0), water=water,
               fairway=np.zeros((h, w), bool), obstacles=(green, tee), links=(link,), seed=7,
               bridge_rule=rule)
    return sc, link


def _pond():
    """Étang au milieu, contournable à l'est et à l'ouest : détour sec
    entre 1,5 et 3 × la distance directe."""
    water = np.zeros((70, 100), bool)
    water[26:34, 22:78] = True
    return water, (46, 10, 54, 14), (48, 46, 52, 48)


def _lake(rows=(12, 58)):
    """Lac sur toute la largeur : pas de détour sec, un pont droit et long."""
    water = np.zeros((70, 60), bool)
    water[rows[0]:rows[1], :] = True
    return water, (26, 2, 34, 6), (28, 63, 32, 66)


# === Règle ===

def test_default_rule_is_the_gain_rule_at_25_percent_with_the_fixes():
    rule = BridgeRule()
    assert rule == BridgeRule.gained(0.25)
    assert (rule.cost, rule.shape, rule.gain) == (0.25, "bends", 0.25)
    assert rule.cost == pbridge.GAIN_COST and rule.gain == pbridge.DEFAULT_GAIN
    assert pscene.Scene.__dataclass_fields__["bridge_rule"].default == BridgeRule()


@pytest.mark.parametrize("kwargs", [{"cost": -0.1}, {"shape": "zigzag"},
                                    {"gain": 0.0}, {"gain": 1.0}])
def test_rule_rejects_bad_parameters(kwargs):
    with pytest.raises(ValueError):
        BridgeRule(**kwargs)


def test_grid_and_astar_use_the_rule_cost():
    """Le surcoût de la règle passe à la grille et au coût d'un pas sur
    l'eau de l'A*."""
    water, green, tee = _lake()
    for cost in (4.0, 1.0, 0.0):
        sc, link = _scene(water, green, tee, BridgeRule(cost=cost))
        grid = build_grid(sc, link, 15)
        assert grid.bridge_cost == cost
        r, c = 30 - grid.y0, 30 - grid.x0
        cells, total = shortest_path(grid, (r, c), (r + 3, c), allow_water=True)
        assert cells == [(r + k, c) for k in range(4)]
        assert total == pytest.approx(3 * (1.0 + cost))


def test_cost_shapes_the_wet_route():
    """Règle du gain (gain de 5 %) : un pont moins cher est plus court et
    passe plus longtemps sur l'eau."""
    water, green, tee = _pond()
    sc, link = _scene(water, green, tee)
    dear = route_link(replace(sc, bridge_rule=BridgeRule(cost=4.0, shape="straight", gain=0.05)), link)
    cheap = route_link(replace(sc, bridge_rule=BridgeRule(cost=0.5, shape="straight", gain=0.05)), link)
    assert dear.bridge and cheap.bridge
    assert cheap.length <= dear.length and cheap.bridge_length >= dear.bridge_length


# === Forme ``bends`` ===

def _max_angle(points, a, b) -> float:
    u = np.subtract(b, a) / math.dist(a, b)
    out = 0.0
    for p, q in zip(points[:-1], points[1:]):
        v = np.subtract(q, p)
        n = float(np.hypot(*v))
        if n > 1e-9:
            out = max(out, math.degrees(math.acos(min(1.0, abs(float(v @ u)) / n))))
    return out


@pytest.mark.parametrize("rows, count", [((8, 62), 3), ((14, 56), 3)])
def test_bends_on_a_long_crossing(rows, count):
    """Traversée droite d'au moins 50 blocs : 3 virages doux, sommets sur
    l'eau, côtés alternés, écart ``BEND_GAP``, pente ≤ 38,2°, sans
    ancrage ; déterministe."""
    water, green, tee = _lake(rows)
    sc, link = _scene(water, green, tee, _STRAIGHT)
    straight = route_link(sc, link)
    assert straight.bridge and len(straight.points) == 2 and not straight.bridge_bends
    length = math.dist(*straight.points)
    assert length >= needed(3)
    bent_sc = replace(sc, bridge_rule=BridgeRule())
    route = route_link(bent_sc, link)
    assert route == route_link(bent_sc, link)
    bends = route.bridge_bends
    assert len(bends) == count and route.bridge_notes == (f"{count} virages",)
    assert all(water[int(math.floor(b.apex[1])), int(math.floor(b.apex[0]))] for b in bends)
    assert [b.side for b in bends] == [bends[0].side * (-1) ** i for i in range(count)]
    assert all(3.0 <= b.offset <= 5.0 and b.half == BEND_HALF_RATIO * b.offset for b in bends)
    for b0, b1 in zip(bends[:-1], bends[1:]):
        assert (b1.at - b1.half) - (b0.at + b0.half) >= BEND_GAP - 1e-9
    assert bends[0].at - bends[0].half >= BEND_END_MARGIN - 1e-9
    assert bends[-1].at + bends[-1].half <= length - BEND_END_MARGIN + 1e-9
    assert _max_angle(route.points, *straight.points) <= 38.2
    assert route.points[0] == straight.points[0] and route.points[-1] == straight.points[-1]
    assert route.length == pytest.approx(polyline_length(route.points))
    assert route.length > straight.length
    assert (route.bridge_length, route.bridge_spans) == water_spans(sc, route.points)
    assert route.bridge_length > straight.bridge_length


def test_bend_count_follows_the_room_on_the_whole_link():
    """Entre 34 et 50 blocs : 2 virages ; entre 18 et 34 : 1 ; sous 18 :
    aucun, pont droit gardé et bilan explicite."""
    assert (needed(3), needed(2), needed(1)) == (50.0, 34.0, 18.0)
    water = np.zeros((60, 60), bool)
    water[8:44, :] = True
    sc, link = _scene(water, (26, 0, 34, 3), (28, 50, 32, 52))
    straight = route_link(replace(sc, bridge_rule=_STRAIGHT), link)
    assert needed(2) <= straight.length < needed(3)
    route = route_link(sc, link)
    assert len(route.bridge_bends) == 2
    assert route.bridge_notes == ("2 virages",)
    water, green, tee = _lake((20, 40))
    sc, link = _scene(water, (26, 14, 34, 18), (28, 44, 32, 46))
    route = route_link(sc, link)
    assert 18.0 <= link.direct < 34.0
    assert route.bridge and len(route.bridge_bends) == 1 and route.bridge_notes == ("1 virage",)
    water, green, tee = _lake((24, 36))
    sc, link = _scene(water, (26, 20, 34, 24), (28, 36, 32, 38))
    route = route_link(sc, link)
    assert link.direct < 18.0
    assert route.bridge and not route.bridge_bends and len(route.points) == 2
    assert route.bridge_notes[0].startswith("aucun virage (3 : tronçons mouillés de")


def test_select_maximises_the_water_gain_with_gaps_and_alternate_sides():
    """Programmation dynamique : somme des gains maximale, écart et côtés
    alternés respectés, égalités départagées par l'ordre."""
    a, b = (0.0, 0.0), (60.0, 0.0)

    def c(at, side, gain, offset=3.0):
        bend = make_bend(a, b, at, offset, side, 1.0)
        return Candidate(bend, at - bend.half, at + bend.half, gain)

    cands = [c(10, 1, 1.0), c(12, -1, 5.0), c(26, 1, 2.0), c(28, -1, 9.0), c(44, -1, 3.0),
             c(44, 1, 1.0)]
    # bosses de ±6 : (12, -1) puis (26, 1) trop proches (20 < 18 + 4)
    out = select(cands, 3)
    assert [(x.bend.at, x.bend.side) for x in out] == [(10, 1), (28, -1), (44, 1)]
    two = select(cands, 2)               # 10 à égalité : la première fin l'emporte
    assert [(x.bend.at, x.bend.side) for x in two] == [(10, 1), (28, -1)]
    assert sum(x.gain for x in two) == max(
        x.gain + y.gain for x in cands for y in cands
        if x.end + BEND_GAP <= y.start + 1e-9 and x.bend.side == -y.bend.side)
    assert select(cands[:2], 3) == []


def test_bends_keep_shared_intervals_on_their_piece():
    """Un intervalle emprunté (tronc) n'est jamais courbé et suit les
    abscisses du tracé courbé."""
    water, green, tee = _lake((8, 62))
    sc, link = _scene(water, green, tee)
    straight = route_link(replace(sc, bridge_rule=_STRAIGHT), link)
    total = straight.length
    shared = replace(straight, shared=((0.0, 4.0), (total - 6.0, total)))
    bent = bend_bridge(sc, link, shared)
    assert bent.bridge_bends
    lo, hi = bent.shared[1]
    assert bent.shared[0] == (0.0, 4.0)
    assert hi == pytest.approx(bent.length, abs=1e-5) and hi - lo == pytest.approx(6.0)
    piece = total - 10.0                 # tronçon propre : de 4 à total - 6
    for bend in bent.bridge_bends:       # abscisses depuis le début du tronçon
        assert bend.at - bend.half >= BEND_END_MARGIN - 1e-9
        assert bend.at + bend.half <= piece - BEND_END_MARGIN + 1e-9


def test_bends_use_no_random_stream():
    """Forme sans tirage : aucun flux, ni ``BENDS_STREAM`` ni un réservé."""
    import golfgen.dressing.paths.bridge_shape as shape
    assert not hasattr(shape, "np_random") and "rng" not in vars(shape)
    assert rng.BENDS_STREAM == 0x56495247 and 0x43484D4E in rng.RESERVED_STREAMS


# === Pincement ===

def _pinch_scene(rule, water=None):
    if water is None:
        water = np.zeros((60, 64), bool)
        water[24:30, :] = True           # le pont
        water[40, 31] = True             # autre mare sous le bord du trait, centre au sec
    sc, link = _scene(water, (28, 6, 36, 10), (30, 52, 34, 54), rule)
    points = ((32.0, 10.0), (32.0, 52.0))
    length, spans = water_spans(sc, points)
    route = Route("bridge", points, 42.0, length, spans, allow_water=True)
    return sc, link, route


def test_a_bridge_is_full_width_over_water_connected_to_the_crossing():
    """Eau reliée à la traversée sous le bord du trait, centre au sec, loin
    des bouts : gardée sous le trait (pas de passerelle pincée d'un bloc) ;
    jamais d'eau permise hors pont."""
    water = np.zeros((60, 64), bool)
    water[24:30, :] = True               # la traversée
    water[30:37, 31] = True              # rive oblique sous le bord du trait
    sc, link, route = _pinch_scene(BridgeRule(), water)
    cells = {tuple(c) for c in link_blocks(sc, link, route, route.points,
                                           obstacle_mask(sc)).cells.tolist()}
    assert (31, 35) in cells and (32, 35) in cells
    assert water_cuts(sc, link, route, route.points) == (0, 0)
    for z in range(14, 48):              # trait complet, deux cases par rang
        assert {(31, z), (32, z)} <= cells
    detour = replace(route, status="detour")
    assert not bridge_water(sc, detour).any()


def test_a_second_pond_under_the_band_edge_is_not_a_bridge():
    """Une autre mare frôlée par le bord du trait n'est pas posée en cases
    d'eau ; la largeur est rendue de l'autre côté du trait."""
    sc, link, route = _pinch_scene(BridgeRule())
    assert sc.water[40, 31]
    allowed = bridge_water(sc, route, route.points)
    assert allowed[26, 31] and not allowed[40, 31]
    blocks = link_blocks(sc, link, route, route.points, obstacle_mask(sc))
    cells = {tuple(c) for c in blocks.cells.tolist()}
    assert (31, 40) not in cells and {(32, 40), (33, 40)} <= cells
    assert blocks.compensated == 1 and blocks.components == 1 and blocks.corner_only == 0
    assert water_cuts(sc, link, route, route.points) == (1, 1)


def test_ford_pinch_keeps_width_on_the_dry_side_without_water_cells():
    """Gué étroit (``water_fringe``) dont le trait mord l'eau : largeur
    rendue côté sec, aucune case d'eau, route gardée (pas de long détour)."""
    sc, link, route = _ford_scene()
    points = route.points
    blocks = link_blocks(sc, link, route, points, obstacle_mask(sc))
    cells = {tuple(c) for c in blocks.cells.tolist()}
    for z in range(24, 30):
        assert {(31, z), (32, z)} <= cells and (30, z) not in cells
    assert blocks.compensated == 6 and blocks.components == 1
    assert not sc.water[blocks.cells[:, 1], blocks.cells[:, 0]].any()


def _ford_scene():
    water = np.zeros((60, 64), bool)
    water[24:30, :31] = True
    water[24:30, 35:] = True             # gué x 31..34
    sc, link = _scene(water, (28, 6, 36, 10), (30, 52, 34, 54))
    points = ((31.5, 10.0), (31.5, 52.0))   # trait x 30 et 31 : x 30 dans l'eau
    return sc, link, Route("detour", points, 42.0, water_fringe=True, allow_water=True)


def test_width_is_not_given_back_on_the_fairway():
    """La case rendue côté sec n'est jamais posée sur le fairway."""
    sc, link, route = _ford_scene()
    fairway = np.zeros_like(sc.fairway)
    fairway[24:27, 32] = True            # moitié du gué : x 32 en fairway
    sc = replace(sc, fairway=fairway)
    blocks = link_blocks(sc, link, route, route.points, obstacle_mask(sc))
    cells = {tuple(c) for c in blocks.cells.tolist()}
    assert blocks.compensated == 3
    for z in range(24, 27):
        assert (32, z) not in cells
    for z in range(27, 30):
        assert (32, z) in cells
    assert not fairway[blocks.cells[:, 1], blocks.cells[:, 0]].any()


def test_width_is_not_given_back_beyond_an_obstacle():
    """Obstacle en travers du trait : rien au-delà, ``compensated`` nul."""
    water = np.zeros((40, 40), bool)
    water[20, 30] = True
    blocked = water.copy()
    blocked[20, 32] = True               # trait x 30..32 : bunker au bord opposé
    blocks = path_blocks(((31.5, 5.0), (31.5, 35.0)), 3.0, blocked, compensate=water)
    assert blocks.compensated == 0
    assert (33, 20) not in {tuple(c) for c in blocks.cells.tolist()}


# === Un seul morceau ===

def test_a_cut_trace_leaves_exactly_one_piece_and_counts_as_a_defect():
    """Tracé coupé en deux morceaux qui le portent : le plus grand reste,
    l'autre est compté (``severed``, ``defects``) ; ``compensated`` ne compte
    que les cases restées (celles rendues ici étaient isolées)."""
    water = np.zeros((40, 40), bool)
    water[20, 30:32] = True              # toute la largeur du trait
    blocked = water.copy()
    for x in (29, 32):                   # cases rendues sans raccord possible
        blocked[19, x] = blocked[21, x] = True
    points = ((31.0, 5.0), (31.0, 35.0))
    blocks = path_blocks(points, 2.0, blocked, single_piece=True, compensate=water)
    assert blocks.components == 1 and blocks.severed == 1 and blocks.defects == 1
    assert blocks.compensated == 0
    assert blocks.cells[:, 1].max() < 20
    old = path_blocks(points, 2.0, blocked)
    assert old.components == 2 and old.severed == 0 and old.defects == 1

def test_a_link_keeps_only_the_piece_on_its_trace():
    """Morceau détaché de plus de ``BLOCK_ISOLATED_MAX`` cases (prolongement
    d'un bout qui contourne un coin) : retiré, quelle que soit sa taille."""
    from golfgen.dressing.paths.blocks import BLOCK_ISOLATED_MAX
    blocked = np.zeros((30, 40), bool)
    blocked[9:12, 10:20] = True          # coupe le prolongement du trait
    points = ((15.0, 25.0), (15.0, 14.0))
    kwargs = {"extend_ends": (False, True)}
    # prolongement long pour isoler 3 cases et plus au-delà de l'obstacle
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(pblocks, "BLOCK_EXTEND", 7.0)
        old = path_blocks(points, 2.0, blocked, **kwargs)
        new = path_blocks(points, 2.0, blocked, **kwargs, single_piece=True)
    assert old.components == 2 and new.components == 1
    assert len(old.cells) - len(new.cells) == new.dropped > BLOCK_ISOLATED_MAX
    assert not (new.cells[:, 1] < 9).any()


# === Prolongement des bouts ===

def test_bridge_water_extends_only_ends_with_a_surface():
    """Bout ponctuel (clubhouse sans parvis) : le trait du pont n'est pas
    prolongé au-delà. Eau reliée à la traversée sous le bord du trait,
    jusqu'au-delà du bout."""
    water = np.zeros((60, 64), bool)
    water[14:26, :] = True
    water[14:33, 31] = True
    points = ((32.0, 30.0), (32.0, 10.0))
    sc, link, _ = _pinch_scene(BridgeRule(), water)
    length, spans = water_spans(sc, points)
    route = Route("bridge", points, 20.0, length, spans, allow_water=True)
    # la 1re extrémité est ponctuelle : rien au-delà de z = 30
    allowed = bridge_water(sc, route, points, (False, True))
    assert not allowed[31, 31] and allowed[28, 31]


# === Règle du gain ===

def test_gain_rule_compares_the_tensioned_lengths():
    """Pont pris si et seulement si (sec − mouillé) / sec atteint le gain
    (tracés tendus, avant les virages) ; même règle quelle que soit la
    distance directe."""
    water, green, tee = _pond()
    sc, link = _scene(water, green, tee, BridgeRule.gained(0.05))
    route = route_link(sc, link)
    assert route.bridge and route.dry_length is not None and route.wet_length is not None
    gain = (route.dry_length - route.wet_length) / route.dry_length
    assert route.long_dry and gain > 0.05
    assert route.wet_length <= route.length      # les virages n'entrent pas dans le gain
    at = BridgeRule.gained(gain - 1e-6)
    above = BridgeRule.gained(min(gain + 0.01, 0.99))
    assert route_link(replace(sc, bridge_rule=at), link).bridge
    kept = route_link(replace(sc, bridge_rule=above), link)
    assert not kept.bridge and not kept.long_dry and kept.length == route.dry_length
    assert kept.wet_length == route.wet_length


def test_gain_rule_crosses_at_low_water_cost():
    """Surcoût ``GAIN_COST`` : la route mouillée traverse (droite), elle ne
    longe pas la rive."""
    assert pbridge.GAIN_COST == 0.25
    water, green, tee = _pond()
    sc, link = _scene(water, green, tee, _STRAIGHT)
    route = route_link(sc, link)
    assert route.bridge and len(route.points) == 2


def test_gain_rule_takes_water_when_there_is_no_dry_route():
    water, green, tee = _lake()
    sc, link = _scene(water, green, tee, BridgeRule.gained(0.9))
    route = route_link(sc, link)
    assert route.bridge and route.dry_length is None


# === Crochet au coin d'une boîte ===

_ARRIVAL = ((352.82, 153.52), (348.25, 156.79))
_ROTATED_BOX = np.array([(347.3, 161.7), (345.56, 158.1), (348.25, 156.79), (350.0, 160.39)])
_BOX_ROWS = {156: (347, 349), 157: (345, 349), 158: (345, 350), 159: (345, 350), 160: (346, 350),
             161: (346, 349)}
# arrivées réelles sur le coin saillant d'une boîte tournée : (tracé, contour, lignes de la
# boîte, largeur, cases du crochet)
_CORNER_ARRIVALS = {
    "large-3": (_ARRIVAL, _ROTATED_BOX, _BOX_ROWS, 3.0, {(346, 156), (346, 155)}),
    "large-2": (((371.71, 163.99), (384.73, 149.05)),
                np.array([(384.73, 149.05), (382.19, 145.96), (384.5, 144.05), (387.04, 147.14)]),
                {144: (383, 386), 145: (382, 387), 146: (382, 387), 147: (383, 388),
                 148: (383, 386), 149: (384, 385)}, 2.0, {(386, 148), (386, 149)}),
}


def test_extension_cells_past_the_surface():
    """Au-delà du bout, une case due au seul prolongement doit atteindre la
    surface droit devant ; derrière le plan du bout, elle reste (épaule du
    trait) ; sur un bord droit, la case qui comble le coin reste."""
    end, prev = _ARRIVAL[1], _ARRIVAL[0]
    assert pblocks.past_the_surface(np.array([[346, 156]]), end, prev, _ROTATED_BOX).all()
    assert not pblocks.past_the_surface(np.array([[348, 155]]), end, prev, _ROTATED_BOX).any()
    wall = np.array([(10.0, 0.0), (20.0, 0.0), (20.0, 20.0), (10.0, 20.0)])
    assert not pblocks.past_the_surface(np.array([[9, 11], [9, 9]]), (10.0, 10.0), (0.0, 4.0),
                                        wall).any()


@pytest.mark.parametrize("name", sorted(_CORNER_ARRIVALS))
@pytest.mark.parametrize("arrival", [True, False], ids=["arrivee", "depart"])
def test_a_corner_arrival_does_not_hook_around_the_box(name, arrival):
    """Bout sur le coin saillant d'une boîte tournée, à l'arrivée comme au
    départ, en largeur 2 et 3 : avec ``surfaces``, plus de crochet de l'autre
    côté du coin (ni la case du prolongement, ni sa réparation de contact
    par un coin), contact gardé."""
    points, box, rows, width, hook = _CORNER_ARRIVALS[name]
    ends = (False, True)
    surfaces = (None, box)
    if not arrival:
        points, ends, surfaces = points[::-1], ends[::-1], surfaces[::-1]
    blocked = np.zeros((170, 400), bool)
    for z, (x0, x1) in rows.items():
        blocked[z, x0:x1] = True
    old = path_blocks(points, width, blocked, extend_ends=ends)
    hooked = {tuple(c) for c in old.cells.tolist()}
    assert hook <= hooked
    fixed = path_blocks(points, width, blocked, extend_ends=ends, surfaces=surfaces)
    cells = {tuple(c) for c in fixed.cells.tolist()}
    assert not cells & hook
    assert cells <= hooked and fixed.components == 1 and fixed.corner_only == 0
    tee = np.array(sorted((x, z) for z, (x0, x1) in rows.items() for x in range(x0, x1)))
    assert pblocks.touches(fixed.cells, tee)


def test_a_shoulder_left_by_the_extension_is_not_a_spur():
    """Trait à 45° (N = 3, case extérieure à 1,06 du tracé) sur le coin d'une
    boîte tournée : l'épaule que le retrait du prolongement laisse en
    feuille reste, elle n'est pas une épine."""
    end = np.array([35.0, 35.5])
    th = math.radians(45.0)
    prev = end - np.array([math.cos(th), -math.sin(th)]) * 20.0
    box = np.array([(0.0, 0.0), (6.0, 0.0), (6.0, 6.0), (0.0, 6.0)])
    box = box @ np.array([(math.cos(th), math.sin(th)), (-math.sin(th), math.cos(th))])
    box = box - box[3] + end
    blocked = geometry.center_mask(box, 70, 70)
    blocks = path_blocks((tuple(prev), tuple(end)), 2.0, blocked, extend_ends=(False, True),
                         surfaces=(None, box))
    assert (34, 34) in {tuple(c) for c in blocks.cells.tolist()}
    assert blocks.spurs == 0


# === Liaisons triviales et union coupée ===

def _box(ref, kind, x0, z0, x1, z1):
    """Surface : contour ``(x0, z0)``–``(x1, z1)``, flottants permis ;
    empreinte des cases dont le centre est dans le contour."""
    poly = np.array([(x0, z0), (x1, z0), (x1, z1), (x0, z1)], dtype=float)
    return _footprint(ref, kind, poly)


def _diamond(ref, kind, cx, cz, radius):
    """Boîte tournée à 45° (sommets sur les axes)."""
    poly = np.array([(cx - radius, cz), (cx, cz - radius), (cx + radius, cz), (cx, cz + radius)],
                    dtype=float)
    return _footprint(ref, kind, poly)


def _footprint(ref, kind, poly):
    mask = geometry.center_mask(poly, 40, 30)
    cells = np.argwhere(mask)[:, ::-1]
    return Obstacle(kind, ref, cells, poly)


def _laid(monkeypatch, first, second, rule, *, water=None, extra=(), point=None):
    """``place_paths`` d'une seule liaison ``first`` → ``second`` (``point`` :
    départ sans surface au lieu de ``first``)."""
    if point is None:
        start, end = geometry.closest_points(first.polygon, second.polygon)
        ends = (first.ref, second.ref, first.polygon, second.polygon)
        obstacles = (first, second)
    else:
        start, end = point, tuple(geometry.closest_points(
            np.array([point], dtype=float), second.polygon)[1])
        ends = (None, second.ref, None, second.polygon)
        obstacles = (second,)
    link = pscene.LinkEnds(0, 1, 2, start, end, frozenset(r for r in ends[:2] if r), *ends)
    sc = Scene(width=40, height=30, path_width=2.0, relief=np.full((30, 40), 64.0),
               water=np.zeros((30, 40), bool) if water is None else water,
               fairway=np.zeros((30, 40), bool), obstacles=(*obstacles, *extra), links=(link,),
               seed=7, bridge_rule=rule)
    monkeypatch.setattr(pcourse, "scene_from_json", lambda *args: sc)
    return place_paths({}, bridge_rule=rule)


def _assert_touches_both(lp, *surfaces):
    assert len(lp.cells) and lp.contacts_missing == 0
    for obstacle in surfaces:
        assert pblocks.touches(lp.cells, obstacle.cells)


@pytest.mark.parametrize("first, second", [
    (("green 1", "green", 10, 10, 14, 14), ("tee 2/0", "tee", 14, 10, 18, 14)),
    (("green 1", "green", 10, 15.5, 5), ("tee 2/0", "tee", 20, 15.5, 5)),
], ids=["face", "tournees"])
def test_trivial_link_between_surfaces_sharing_a_face_is_not_laid(monkeypatch, first, second):
    make = _box if len(first) == 6 else _diamond
    paths = _laid(monkeypatch, make(*first), make(*second), BridgeRule())
    lp = paths.debug.links[0]
    assert lp.status == "trivial" and not len(lp.cells) and not len(paths.cells)
    assert lp.contacts_missing == 0


@pytest.mark.parametrize("first, second", [
    (("green 1", "green", 8, 8, 10.9, 10.9), ("tee 2/0", "tee", 11.1, 11.1, 14, 14)),
    (("green 1", "green", 10, 10, 14, 14), ("tee 2/0", "tee", 15, 10, 19, 14)),
    (("green 1", "green", 10, 15.5, 5), ("tee 2/0", "tee", 21, 15.5, 5)),
], ids=["coin-seul", "colonne-libre", "tournees-ecartees"])
def test_close_surfaces_not_sharing_a_face_are_routed(monkeypatch, first, second):
    """À moins d'un bloc, sans face commune : routage normal, liaison tracée
    (coin seul : (11, 10) et (10, 11) libres ; colonne libre à 1,0)."""
    make = _box if len(first) == 6 else _diamond
    green, tee = make(*first), make(*second)
    assert not pscene.surfaces_meet(
        Scene(width=40, height=30, path_width=2.0, relief=np.full((30, 40), 64.0),
              water=np.zeros((30, 40), bool), fairway=np.zeros((30, 40), bool),
              obstacles=(green, tee)),
        pscene.LinkEnds(0, 1, 2, (0.0, 0.0), (1.0, 0.0), frozenset({green.ref, tee.ref}),
                        green.ref, tee.ref, green.polygon, tee.polygon))
    lp = _laid(monkeypatch, green, tee, BridgeRule()).debug.links[0]
    assert lp.status != "trivial"
    _assert_touches_both(lp, green, tee)


def test_end_without_a_surface_is_never_trivial(monkeypatch):
    """Bout sans surface (clubhouse sans parvis) à moins d'un bloc : routé."""
    tee = _box("tee 2/0", "tee", 15, 10, 19, 14)
    lp = _laid(monkeypatch, None, tee, BridgeRule(), point=(14.5, 12.0)).debug.links[0]
    assert lp.status != "trivial"
    _assert_touches_both(lp, tee)


def test_close_surfaces_with_a_water_column_are_crossed_by_a_bridge(monkeypatch):
    """Colonne d'eau à 1,0, traversable par construction : pont, pas d'erreur."""
    water = np.zeros((30, 40), bool)
    water[:, 14] = True
    green, tee = _box("green 1", "green", 10, 10, 14, 14), _box("tee 2/0", "tee", 15, 10, 19, 14)
    lp = _laid(monkeypatch, green, tee, BridgeRule(), water=water).debug.links[0]
    assert lp.route.bridge
    _assert_touches_both(lp, green, tee)


def test_close_surfaces_behind_an_impassable_column_are_a_path_error(monkeypatch):
    """Colonne infranchissable (obstacle sur toute la hauteur) : aucune route."""
    green, tee = _box("green 1", "green", 10, 10, 14, 14), _box("tee 2/0", "tee", 15, 10, 19, 14)
    wall = _box("bunker", "bunker", 14, 0, 15, 30)
    with pytest.raises(PathError, match=r"liaison 0 \(1 → 2\)"):
        _laid(monkeypatch, green, tee, BridgeRule(), extra=(wall,))


def test_union_left_with_a_corner_contact_is_a_path_error(monkeypatch):
    data, stub = fabricated_variant("nominal")
    stub_course_input(monkeypatch, stub, pscene)
    real = pcourse.repair_union_corners

    def defective(*args, **kwargs):
        union, added, _ = real(*args, **kwargs)
        return union, added, (((1, 1), (2, 2)),)

    monkeypatch.setattr(pcourse, "repair_union_corners", defective)
    with pytest.raises(PathError, match="union coupée"):
        place_paths(data)


# === Parcours fabriqué posé avec les virages doux ===

@pytest.mark.parametrize("rule", [BridgeRule.gained(0.15), BridgeRule()])
def test_fabricated_course_invariants_with_bends(monkeypatch, rule):
    """4-connexité, aucune case sur un green, une boîte, un bunker ou le
    parvis, eau seulement sous les liaisons en pont (et exportée dans
    ``bridge_cells``), aucun pont pincé par l'eau en chemin, ancrages hors de
    l'eau, déterministe."""
    data, stub = fabricated_variant("pond")
    stub_course_input(monkeypatch, stub, pscene)
    paths = place_paths(data, bridge_rule=rule)
    again = place_paths(data, bridge_rule=rule)
    assert np.array_equal(paths.cells, again.cells)
    scene = paths.debug.scene
    obstacles = obstacle_mask(scene)
    assert not obstacles[paths.cells[:, 1], paths.cells[:, 0]].any()
    wet = scene.water[paths.cells[:, 1], paths.cells[:, 0]]
    assert np.array_equal(paths.bridge_cells, paths.cells[wet])
    owned = {tuple(c) for lp in paths.debug.links if lp.route.bridge for c in lp.cells.tolist()}
    owned |= {tuple(c) for c in paths.debug.union_added.tolist()}
    assert {tuple(c) for c in paths.bridge_cells.tolist()} <= owned
    assert any(lp.route.bridge for lp in paths.debug.links)
    for lp in paths.debug.links:
        if lp.status == "trivial":
            continue
        assert lp.blocks.components == 1 and lp.blocks.corner_only == 0, lp.index
        if lp.route.bridge:
            assert lp.water_cuts == 0, lp.index
    if len(paths.anchors):
        assert not scene.water[paths.anchors[:, 1], paths.anchors[:, 0]].any()
    assert paths.debug.union_defects == ()
