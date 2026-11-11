"""Chemins (``golfgen.dressing.paths``) : parvis, scène, A*, route, flux des
virages (R1, R2), et invariants des chemins posés par ``place_paths`` (R3) :
4-connexité de chaque liaison et de l'union (réparée de ses contacts par un
coin seul), aucune case sur un obstacle ni
sur l'eau hors pont, contact aux deux bouts, ancrages en rough libre hors de
tout chemin, couche triée, déterminisme."""

from __future__ import annotations

from dataclasses import replace
import math
from types import SimpleNamespace

import numpy as np
import pytest

from golfgen.dressing import rng
from golfgen.dressing.bunkers import beans, green_phase, pots, selection
from golfgen.dressing.paths import BridgeRule, PathError, geometry, grid as pgrid, plaza as pplaza
from golfgen.dressing.paths import blocks as pblocks, course as pcourse
from golfgen.dressing.paths import route as proute, scene as pscene
from golfgen.dressing.paths.bends import bend_route
from golfgen.dressing.paths.course import place_paths, repair_union_corners
from golfgen.dressing.paths.grid import Grid, Network, astar, build_grid, shortest_path
from golfgen.dressing.paths.route import route_link, route_network
from golfgen.dressing.paths.plaza import PLAZA_CLEAR, PLAZA_SIZE, place_plaza, plaza_at, plaza_hits
from golfgen.dressing.paths.scene import PLAZA_REF, Obstacle, Scene, obstacle_mask, scene_from_json
from golfgen.routing.sites import WaterMask
from tests.paths_corpus import (FAB_HEIGHT, FAB_WIDTH, bends_variant, case_input,
                                 fabricated_json, fabricated_variant, fabricated_water,
                                 paths_cases, stub_course_input)


def cells(kind, ref, x0, y0, x1, y1):
    xs, ys = np.meshgrid(np.arange(x0, x1), np.arange(y0, y1))
    return Obstacle(kind, ref, np.column_stack((xs.ravel(), ys.ravel())))


def _club(x, y, edge):
    return {"x": x, "y": y, "edge": edge}


DRY = np.zeros((60, 80), bool)


# === Parvis ===

def test_plaza_sits_inside_in_front_of_the_clubhouse():
    for edge, club, inside in (("S", (30.0, 56.0), lambda p: p.z0 + p.size == 56),
                               ("N", (30.0, 4.0), lambda p: p.z0 == 4),
                               ("W", (4.0, 30.0), lambda p: p.x0 == 4),
                               ("E", (76.0, 30.0), lambda p: p.x0 + p.size == 76)):
        plaza, report = place_plaza(_club(*club, edge), 80, 60, [], DRY)
        assert plaza.size == PLAZA_SIZE and inside(plaza) and report["placed"]
        assert report["conflicts"] == [] and not report["shifted"] and not report["reduced"]
        lo, hi = plaza.polygon.min(axis=0), plaza.polygon.max(axis=0)
        along = 0 if edge in "NS" else 1
        assert lo[along] <= club[along] <= hi[along]                  # centré sur le clubhouse
        assert len(plaza.cells) == PLAZA_SIZE ** 2 and plaza.shift == (0, 0)
    assert pplaza.clubhouse_edge({"x": 30.0, "y": 57.0}, 80, 60) == "S"


def test_plaza_shifts_along_the_edge_first():
    tee = cells("tee", "tee 1/0", 24, 50, 28, 53)                     # mord sur le coin gauche
    plaza, report = place_plaza(_club(30.0, 56.0, "S"), 80, 60, [tee], DRY)
    assert report["conflicts"] == ["tee 1/0"] and report["shifted"] and not report["reduced"]
    assert report["shift"]["inward"] == 0 and report["shift"]["along"] > 0
    assert plaza.size == PLAZA_SIZE and plaza.x0 >= 28 + PLAZA_CLEAR
    assert plaza_hits(plaza, 80, 60, [tee], DRY) == []


def test_plaza_moves_inward_when_the_edge_row_is_taken():
    row = cells("bunker", "bunker 1/r", 18, 55, 43, 56)
    plaza, report = place_plaza(_club(30.0, 56.0, "S"), 80, 60, [row], DRY)
    assert report["conflicts"] == ["bunker 1/r"] and report["shifted"] and not report["reduced"]
    assert report["shift"] == {"along": 0, "inward": 2}
    assert plaza.z0 + plaza.size == 54 and plaza.size == PLAZA_SIZE


def test_plaza_keeps_one_clear_cell_even_by_a_corner():
    nominal = plaza_at((30.0, 56.0), "S", PLAZA_SIZE, 0, 0)
    corner = cells("tee", "tee 2/0", nominal.x0 - 1, nominal.z0 - 1, nominal.x0, nominal.z0)
    assert plaza_hits(nominal, 80, 60, [corner], DRY) == ["tee 2/0"]
    far = cells("tee", "tee 2/0", nominal.x0 - 2, nominal.z0 - 2, nominal.x0 - 1, nominal.z0 - 1)
    assert plaza_hits(nominal, 80, 60, [far], DRY) == []


def test_plaza_shrinks_between_walls_then_gives_up():
    club = _club(30.0, 56.0, "S")
    walls = [cells("tee", "tee 1/0", 20, 40, 27, 56), cells("tee", "tee 10/0", 34, 40, 41, 56)]
    plaza, report = place_plaza(club, 80, 60, walls, DRY)
    assert report["reduced"] and plaza.size <= 34 - 27 - 2 * PLAZA_CLEAR
    assert plaza.x0 >= 27 + PLAZA_CLEAR and plaza.x0 + plaza.size <= 34 - PLAZA_CLEAR
    assert report["size"] == plaza.size < PLAZA_SIZE
    plaza, report = place_plaza(club, 80, 60, [], np.ones((60, 80), bool))
    assert plaza is None and not report["placed"] and report["conflicts"] == ["eau"]
    assert report["tried"] == len(pplaza.PLAZA_SIZES) * len(pplaza.plaza_shifts())


def test_plaza_off_the_map_is_shifted_and_may_touch_the_map_edge():
    out = plaza_at((2.0, 56.0), "S", PLAZA_SIZE, 0, 0)
    assert out.x0 < 0 and plaza_hits(out, 80, 60, [], DRY) is None
    plaza, report = place_plaza(_club(2.0, 56.0, "S"), 80, 60, [], DRY)
    assert report["conflicts"] == ["hors carte"] and report["shifted"]
    assert report["shift"]["along"] > 0 and report["shift"]["inward"] == 0
    assert plaza.x0 == 0 and plaza.size == PLAZA_SIZE                # collé au bord ouest
    # coin de la carte : hors carte des deux côtés, glissé le long du bord seulement
    plaza, report = place_plaza(_club(77.5, 3.0, "N"), 80, 60, [], DRY)
    assert report["conflicts"] == ["hors carte"] and plaza.x0 + plaza.size == 80
    assert plaza.z0 == 3
    # clubhouse sur la dernière rangée : le parvis touche le bord sud de la carte
    plaza, report = place_plaza(_club(30.0, 60.0, "S"), 80, 60, [], DRY)
    assert plaza.z0 + plaza.size == 60 and not report["shifted"]


# === Scène ===

def fabricated_course(monkeypatch, *, club=(30.0, 38.0, "S"), water=None):
    """Petit JSON 3.2 fabriqué (``tests.paths_corpus.fabricated_json`` : 3
    trous, green double 1/3, green 2 insulaire) et ``course_input_from_json``
    remplacé : eau brute (par défaut l'étang autour du green 2) et relief
    plat."""
    stub = SimpleNamespace(water=WaterMask(water=fabricated_water() if water is None else water),
                           relief=np.full((FAB_HEIGHT, FAB_WIDTH), 64.0))
    stub_course_input(monkeypatch, stub, pscene)
    return fabricated_json(club)


def test_scene_from_json_obstacles_ends_and_effective_water(monkeypatch):
    sc = scene_from_json(fabricated_course(monkeypatch))
    assert {"green_pair 1/3", "green 2", "tee 1/0", "tee 2/0", "tee 2/1", "tee 3/0",
            "bunker 2/b0", PLAZA_REF} == {o.ref for o in sc.obstacles}
    assert sc.path_width == pscene.PATH_WIDTH["links"] and sc.style == "links"
    by_ends = {(l.src, l.dst): l for l in sc.links}
    assert by_ends[(1, 2)].exclude == {"green_pair 1/3", "tee 2/0"}
    assert by_ends[(1, 2)].src_ref == "green_pair 1/3" and by_ends[(1, 2)].dst_ref == "tee 2/0"
    sx, sy = by_ends[(1, 2)].start
    assert 10 <= sx <= 18 and math.isclose(sy, 14.0)
    ex, ey = by_ends[(1, 2)].end
    assert 20 <= ex <= 22 and math.isclose(ey, 30.0)
    # parvis : surface d'extrémité de toutes les liaisons du clubhouse, sur tout son bord
    assert sc.plaza is not None and sc.plaza_report["placed"]
    for key in (("clubhouse", 1), (3, "clubhouse")):
        link = by_ends[key]
        assert PLAZA_REF in (link.src_ref, link.dst_ref) and PLAZA_REF in link.exclude
        poly = link.src_poly if link.src_ref == PLAZA_REF else link.dst_poly
        assert np.array_equal(poly, sc.plaza.polygon)
    # eau effective : cases sous le green insulaire remontées, reste de l'étang gardé
    assert not sc.water[10:14, 40:44].any()
    assert sc.water[8, 38] and sc.water[16, 46]
    assert sc.fairway[24, 25] and not sc.fairway[24, 35]
    mask = obstacle_mask(sc)
    assert mask[sc.plaza.z0, sc.plaza.x0] and mask[20, 35] and not mask[24, 25]


def test_scene_without_plaza_keeps_the_clubhouse_point(monkeypatch):
    water = np.zeros((40, 60), bool)
    water[30:, :] = True                                       # pas de place pour le parvis
    sc = scene_from_json(fabricated_course(monkeypatch, club=(2.0, 38.0, "S"), water=water))
    assert sc.plaza is None and not sc.plaza_report["placed"]
    assert PLAZA_REF not in {o.ref for o in sc.obstacles}
    by_ends = {(l.src, l.dst): l for l in sc.links}
    assert by_ends[("clubhouse", 1)].start == (2.0, 38.0)
    assert by_ends[("clubhouse", 1)].src_poly is None
    assert by_ends[("clubhouse", 1)].exclude == {"tee 1/0"}
    assert by_ends[(3, "clubhouse")].end == (2.0, 38.0)
    grid = build_grid(sc, by_ends[("clubhouse", 1)], 15)
    r, c = grid.sources[0]
    assert len(grid.sources) == 1 and not grid.forbidden[r, c]   # case du point libre


# === Grille et A* ===

def _scene(width=80, height=60, *, obstacles=(), water=None, path_width=2.0):
    shape = (height, width)
    return Scene(width=width, height=height, path_width=path_width,
                 relief=np.full(shape, 64.0),
                 water=np.zeros(shape, bool) if water is None else water,
                 fairway=np.zeros(shape, bool), obstacles=tuple(obstacles))


def _random_grid(rng, h=28, w=36) -> Grid:
    forbidden = rng.random((h, w)) < 0.12
    forbidden[:, 0] = forbidden[:, -1] = False
    water = (rng.random((h, w)) < 0.08) & ~forbidden
    fairway = rng.random((h, w)) < 0.3
    relief = rng.integers(60, 64, size=(h, w)).astype(float)
    # axe : deux tracés posés (supercover), anneau autour, hors axe
    net = Network(w, h, 2.0)
    for k in range(2):
        pts = [tuple(rng.uniform([0, 0], [w, h])) for _ in range(int(rng.integers(2, 5)))]
        net.add(k, pts)
    forbidden &= ~net.axis
    goal = np.zeros((h, w), bool)
    goal[rng.integers(0, h, 4), -1] = True
    sources = tuple((int(r), 0) for r in rng.integers(0, h, 3))
    return Grid(0, 0, forbidden, water, fairway, relief, None, sources, goal,
                trunk=net.axis, ring=net.ring, owner=net.owner)


def test_astar_with_trunk_equals_dijkstra_on_random_grids():
    """Remarque de la revue : l'A* avec axe de tronc (heuristique ×0,5)
    rend le coût optimal de Dijkstra ; une heuristique non réduite le
    manquerait sur ces grilles."""
    rng = np.random.default_rng(4)
    checked = 0
    for _ in range(80):
        grid = _random_grid(rng)
        assert grid.has_trunk
        for allow_water in (False, True):
            fast = shortest_path(grid, grid.sources, grid.goal, allow_water=allow_water)
            exact = shortest_path(grid, grid.sources, grid.goal, allow_water=allow_water,
                                  heuristic=False)
            assert (fast is None) == (exact is None)
            if fast is not None:
                assert math.isclose(fast[1], exact[1], rel_tol=1e-12, abs_tol=1e-9)
                checked += 1
    assert checked >= 100


def test_trunk_axis_halves_the_step_cost():
    grid = Grid(0, 0, np.zeros((3, 10), bool), np.zeros((3, 10), bool),
                np.zeros((3, 10), bool), np.zeros((3, 10)), None, ((1, 0),),
                trunk=np.zeros((3, 10), bool), ring=np.zeros((3, 10), bool))
    goal = np.zeros((3, 10), bool)
    goal[1, 9] = True
    plain = shortest_path(grid, grid.sources, goal, allow_water=False)
    assert plain[1] == 9.0 and not grid.has_trunk
    trunk = np.zeros((3, 10), bool)
    trunk[1, :] = True
    on_axis = Grid(0, 0, grid.forbidden, grid.water, grid.fairway, grid.relief, None,
                   grid.sources, goal, trunk=trunk, ring=np.zeros((3, 10), bool))
    assert shortest_path(on_axis, on_axis.sources, goal, allow_water=False)[1] == 4.5
    assert astar(on_axis, on_axis.sources, goal, allow_water=False) == [(1, c) for c in range(10)]


def test_astar_multi_source_and_no_corner_cutting():
    sc = _scene(obstacles=[cells("bunker", "bunker 1/a", 30, 30, 31, 31),
                           cells("bunker", "bunker 1/b", 31, 31, 32, 32)])
    link = pscene.LinkEnds(0, 1, 2, (20.5, 20.5), (40.5, 40.5))
    grid = build_grid(sc, link, 15)
    path = astar(grid, grid.sources, grid.goal, allow_water=False)
    assert path[0] == grid.cell(link.start) and path[-1] == grid.cell(link.end)
    for (r, c), (nr, nc) in zip(path[:-1], path[1:]):
        assert max(abs(nr - r), abs(nc - c)) == 1
        assert not grid.forbidden[nr, nc]
        if nr != r and nc != c:
            assert not (grid.forbidden[r, nc] or grid.forbidden[nr, c])
    # multi-source : la source la plus proche de la cible part
    goal = np.zeros(grid.forbidden.shape, bool)
    goal[5, 40] = True
    far, near = (5, 2), (5, 30)
    assert astar(grid, (far, near), goal, allow_water=False)[0] == near
    assert shortest_path(grid, near, goal, allow_water=False)[1] == 10.0


def test_network_axis_keeps_the_first_owner_and_ring_excludes_the_axis():
    net = Network(30, 20, 2.0)
    net.add(0, [(2.5, 10.5), (27.5, 10.5)])
    net.add(1, [(15.5, 2.5), (15.5, 17.5)])
    net.add(2, [(4.0, 4.0)])                                   # un seul point : ignoré
    assert net.owner[10, 15] == 0 and net.owner[5, 15] == 1 and 2 not in net.polylines
    assert not (net.ring & net.axis).any()
    reach = pgrid.ring_reach(2.0)
    assert net.ring[10 + int(reach) - 1, 5] and not net.ring[10 + int(reach) + 1, 5]


# === Route ===

def _surface(kind, ref, x0, y0, x1, y1):
    poly = np.array([(x0, y0), (x1, y0), (x1, y1), (x0, y1)], dtype=float)
    return Obstacle(kind, ref, cells(kind, ref, x0, y0, x1, y1).cells, poly)


def _link(index, src, dst, src_obs, dst_obs):
    start, end = geometry.closest_points(src_obs.polygon, dst_obs.polygon)
    return pscene.LinkEnds(index, src, dst, start, end, frozenset({src_obs.ref, dst_obs.ref}),
                           src_obs.ref, dst_obs.ref, src_obs.polygon, dst_obs.polygon)


def _fabricated_scene(monkeypatch, variant):
    data, stub = fabricated_variant(variant)
    stub_course_input(monkeypatch, stub, pscene)
    return scene_from_json(data)


def test_route_link_without_any_route_raises_path_error():
    """Boîte d'arrivée cernée de bunkers : aucune route, même avec l'eau
    traversable et la fenêtre de 60 : un bogue, ``PathError`` explicite."""
    green = _surface("green", "green 1", 10, 10, 14, 14)
    tee = _surface("tee", "tee 2/0", 40, 30, 42, 32)
    ring = [cells("bunker", f"bunker 2/{k}", *box) for k, box in enumerate(
        ((38, 28, 44, 29), (38, 33, 44, 34), (38, 29, 39, 33), (43, 29, 44, 33)))]
    sc = Scene(width=80, height=60, path_width=2.0, relief=np.full((60, 80), 64.0),
               water=np.zeros((60, 80), bool), fairway=np.zeros((60, 80), bool),
               obstacles=(green, tee, *ring), seed=1234)
    link = _link(7, 1, 2, green, tee)
    with pytest.raises(PathError, match=r"liaison 7 \(1 → 2\), seed 1234"):
        route_link(sc, link)
    with pytest.raises(PathError):
        route_network(Scene(**{**sc.__dict__, "links": (link,)}))


def test_route_link_bridges_when_the_water_cuts_the_map():
    """Bande d'eau sur toute la largeur : pas de détour sec, un pont ;
    ``bridge_spans`` sur l'eau effective, pas d'eau hors du pont."""
    water = np.zeros((60, 80), bool)
    water[24:30, :] = True
    green = _surface("green", "green 1", 30, 10, 34, 14)
    tee = _surface("tee", "tee 2/0", 31, 44, 33, 46)
    sc = Scene(width=80, height=60, path_width=2.0, relief=np.full((60, 80), 64.0),
               water=water, fairway=np.zeros((60, 80), bool), obstacles=(green, tee))
    route = route_link(sc, _link(0, 1, 2, green, tee))
    assert route.status == "bridge" and route.bridge and route.allow_water
    assert route.dry_length is None and not route.long_dry and not route.water_fringe
    assert route.bridge_length >= 6.0 and route.bridge_spans
    length, spans = proute.water_spans(sc, route.points)
    assert (length, spans) == (route.bridge_length, route.bridge_spans)
    for span in route.bridge_spans:
        for x, y in span:
            assert water[int(math.floor(y)), int(math.floor(x))]


def test_route_link_bridges_over_a_long_dry_detour_and_fords_a_narrow_gap(monkeypatch):
    """Parcours fabriqué : étang à traverser (détour sec plus long que 3 ×
    la distance directe : pont, ``long_dry``), puis le même avec un gué de 3
    cases, trop étroit pour un chemin sec mais hors de l'eau effective
    (``water_fringe``)."""
    sc = _fabricated_scene(monkeypatch, "pond")
    link = sc.links[1]                                         # 1 → 2, à travers l'étang
    route = route_link(sc, link)
    assert route.status == "bridge" and route.long_dry and route.bridge_spans
    assert route.dry_length > 3.0 * link.direct
    assert route.length < route.dry_length
    sc = _fabricated_scene(monkeypatch, "ford")
    route = route_link(sc, sc.links[1])
    assert route.status == "detour" and route.water_fringe and route.allow_water
    assert route.long_dry and route.bridge_length == 0.0 and route.bridge_spans == ()
    assert proute.water_spans(sc, route.points)[0] == 0.0


def test_tension_is_refused_when_it_adds_water(monkeypatch):
    """Green insulaire → boîte 3/0 : la tension couperait sur l'eau (plafond
    d'un pont), elle est refusée et le chemin brut gardé."""
    sc = _fabricated_scene(monkeypatch, "nominal")
    link = sc.links[2]                                         # 2 → 3, depuis l'île
    route = route_link(sc, link)
    assert route.status == "bridge" and route.tension_refused
    assert route.points == route.raw
    tight = proute.tighten(route.grid, list(route.raw), allow_water=True)
    tight = proute.reproject_ends(link, route.grid, tight, allow_water=True)
    assert proute.water_spans(sc, tight)[0] > proute.water_spans(sc, route.raw)[0]
    points, refused = proute.tension(sc, link, route.grid, list(route.raw), allow_water=True)
    assert refused and points == list(route.raw)


def test_trunk_borrow_follows_the_laid_path_exactly(monkeypatch):
    """Règle par défaut : 3 → clubhouse emprunte le tracé de 1 → 2 (posé
    avant) puis, à l'arrivée, celui de 0 ; le morceau emprunté à 1 → 2 est
    exactement le morceau du tracé posé, rattaché à son bout sur le green
    double. Sans réseau, pas d'emprunt."""
    sc = _fabricated_scene(monkeypatch, "nominal")
    routes, network = route_network(sc)
    assert list(network.polylines) == [l.index for l, r in zip(sc.links, routes)
                                       if r.status != "trivial"]
    route = routes[3]
    assert len(route.borrows) == len(route.shared) == 2
    assert route.borrows[1]["from"] == 0 and route.borrows[1]["snapped_end"]
    borrow = route.borrows[0]
    assert borrow["from"] == 1 and borrow["snapped_start"]
    owner = network.polylines[1]
    pts = list(route.points)
    cum = np.concatenate(([0.0], np.cumsum([math.dist(a, b) for a, b in zip(pts[:-1], pts[1:])])))
    lo, hi = route.shared[0]
    piece = [p for p, s in zip(pts, cum) if lo - 1e-6 <= s <= hi + 1e-6]
    assert len(piece) >= 2 and piece[0] == owner[0]            # bout du tracé posé
    assert piece[:-1] == owner[:len(piece) - 1]                # sommets du tracé posé
    dist, along = geometry.polyline_distance(np.asarray([piece[-1]]) - 0.5, owner)
    assert dist[0] < 1e-9                                      # coupé sur le tracé posé
    assert math.isclose(along[0], borrow["owner_interval"][1], abs_tol=1e-3)
    assert math.isclose(hi - lo, borrow["length"], abs_tol=1e-2)
    alone = route_link(sc, sc.links[3])
    assert alone.borrows == () and alone.shared == ()


def test_trivial_link_is_not_laid():
    green = _surface("green", "green 1", 10, 10, 14, 14)
    tee = _surface("tee", "tee 2/0", 14.5, 10, 16, 12)
    sc = Scene(width=40, height=30, path_width=2.0, relief=np.full((30, 40), 64.0),
               water=np.zeros((30, 40), bool), fairway=np.zeros((30, 40), bool),
               obstacles=(green, tee))
    link = _link(0, 1, 2, green, tee)
    routes, network = route_network(Scene(**{**sc.__dict__, "links": (link,)}))
    assert routes[0].status == "trivial" and network.polylines == {}


# === 4-connexité de l'union (préparé pour R3) ===

_N4 = ((1, 0), (-1, 0), (0, 1), (0, -1))
_N8 = _N4 + ((1, 1), (1, -1), (-1, 1), (-1, -1))


def _pieces(cell_set: set, steps) -> int:
    seen, count = set(), 0
    for start in cell_set:
        if start in seen:
            continue
        count += 1
        stack = [start]
        seen.add(start)
        while stack:
            x, z = stack.pop()
            for dx, dz in steps:
                n = (x + dx, z + dz)
                if n in cell_set and n not in seen:
                    seen.add(n)
                    stack.append(n)
    return count


def union_four_connectivity(cells_by_link) -> dict:
    """Défauts de 4-connexité des cases d'un réseau de chemins (une liste de
    cases ``(x, z)`` par liaison) : liaisons en plusieurs morceaux, contacts
    par un coin seul dans l'union (``(x, z)`` et ``(x+1, z±1)`` sans case
    commune), et morceaux de l'union qui ne tiennent que par un coin
    (morceaux 4-connexes moins morceaux 8-connexes). Calcul indépendant de
    la production (ensembles Python)."""
    union: set = set()
    split = 0
    for link_cells in cells_by_link:
        own = {(int(x), int(z)) for x, z in link_cells}
        if own and _pieces(own, _N4) > 1:
            split += 1
        union |= own
    corner = sum(1 for x, z in union for dz in (1, -1)
                 if (x + 1, z + dz) in union and (x + 1, z) not in union and (x, z + dz) not in union)
    return {"split_links": split, "corner_only": corner,
            "corner_joined": _pieces(union, _N4) - _pieces(union, _N8)}


def test_union_four_connectivity_check():
    band = [(x, z) for x in range(10) for z in (5, 6)]
    branch = [(x, z) for x in (4, 5) for z in range(6, 15)]
    assert union_four_connectivity([band, branch]) == {"split_links": 0, "corner_only": 0,
                                                       "corner_joined": 0}
    # deux bandes qui ne se touchent que par un coin
    diag = [(10, 7), (11, 7), (11, 8), (12, 8)]
    defects = union_four_connectivity([band, diag])
    assert defects["corner_only"] == 1 and defects["corner_joined"] == 1
    # une liaison en deux morceaux, recollée par une autre : comptée quand même
    defects = union_four_connectivity([band[:6] + band[-4:], band])
    assert defects["split_links"] == 1 and defects["corner_joined"] == 0
    # escalier en diagonale pure : chaque marche ne tient que par un coin
    stairs = [(k, k) for k in range(5)]
    defects = union_four_connectivity([stairs])
    assert defects == {"split_links": 1, "corner_only": 4, "corner_joined": 4}


# === Chemins posés (``place_paths``) : invariants de production ===

@pytest.fixture(scope="module", params=paths_cases())
def placed(request):
    """``place_paths`` d'un parcours (``tests/paths_corpus.py``), deux fois."""
    data, stub = case_input(request.param, request)
    with pytest.MonkeyPatch.context() as mp:
        if stub is not None:
            stub_course_input(mp, stub, pscene)
        first, second = place_paths(data), place_paths(data)
    return SimpleNamespace(case=request.param, paths=first, again=second)


def test_each_link_and_the_union_are_four_connected(placed):
    """Chaque liaison d'un seul morceau 4-connexe, et l'union exportée
    (réparée) sans contact par un coin seul (calcul indépendant :
    ``union_four_connectivity``) ; l'union brute y est entière, aucun
    contact laissé sans case libre."""
    paths = placed.paths
    links = paths.debug.links
    for lp in links:
        if lp.status == "trivial":       # liaison triviale : pas posée, aucune case
            assert not len(lp.cells), lp.index
            continue
        assert lp.blocks.components == 1 and lp.blocks.corner_only == 0, lp.index
    assert union_four_connectivity([lp.cells.tolist() for lp in links])["split_links"] == 0
    union = paths.cells.tolist()
    defects = union_four_connectivity([union])
    assert (defects["corner_only"], defects["corner_joined"]) == (0, 0)
    assert paths.debug.union_defects == ()
    raw = {tuple(c) for c in paths.debug.raw_cells.tolist()}
    added = {tuple(c) for c in paths.debug.union_added.tolist()}
    assert raw == {tuple(c) for lp in links for c in lp.cells.tolist()}
    assert not raw & added and {tuple(c) for c in union} == raw | added


def test_union_corner_contact_between_two_links_is_bridged():
    """Deux liaisons qui ne se touchent que par un coin : la case de raccord
    libre la plus proche des deux tracés est ajoutée (départage
    lexicographique à égalité) ; une case interdite (obstacle, eau hors
    pont, ancrage) ne l'est jamais ; sans case libre, le contact reste,
    signalé."""
    a = np.array([[x, 5] for x in range(0, 6)] + [[x, 6] for x in range(0, 6)])
    b = np.array([[x, 7] for x in range(6, 12)] + [[x, 8] for x in range(6, 12)])
    union = np.unique(np.concatenate((a, b)), axis=0)
    traces = [[(0.0, 6.0), (6.0, 6.0)], [(6.0, 8.0), (12.0, 8.0)]]
    free = np.zeros((20, 20), bool)
    # contact (5, 6) / (6, 7) : raccords (6, 6) et (5, 7), à égale distance
    # des deux tracés : (5, 7) l'emporte (x plus petit)
    out, added, defects = repair_union_corners(union, [a, b], traces, free)
    assert added.tolist() == [[5, 7]] and defects == ()
    assert union_four_connectivity([out.tolist()])["corner_only"] == 0
    assert out.dtype == np.int64 and out.tolist() == sorted(map(list, {*map(tuple, union.tolist()),
                                                                       (5, 7)}))
    # tracé de b décalé vers le haut : (6, 6) devient la plus proche
    out, added, _ = repair_union_corners(union, [a, b], [traces[0], [(5.0, 7.0), (12.0, 7.0)]],
                                         free)
    assert added.tolist() == [[6, 6]]
    # (5, 7) interdite (obstacle, eau hors pont ou ancrage) : l'autre
    blocked = free.copy()
    blocked[7, 5] = True
    _, added, defects = repair_union_corners(union, [a, b], traces, blocked)
    assert added.tolist() == [[6, 6]] and defects == ()
    # les deux interdites : le défaut reste, signalé
    blocked[6, 6] = True
    out, added, defects = repair_union_corners(union, [a, b], traces, blocked)
    assert len(added) == 0 and defects == (((5, 6), (6, 7)),)
    assert np.array_equal(out, union)


def test_union_corner_repair_water_only_from_the_contact_links_bridges():
    """Eau sous les deux cases de raccord : interdite, sauf là où le pont
    d'une liaison propriétaire de l'une des deux cases du contact la permet ;
    le pont d'une autre liaison (ici c, loin du contact) ne compte pas."""
    a = np.array([[x, 5] for x in range(0, 6)] + [[x, 6] for x in range(0, 6)])
    b = np.array([[x, 7] for x in range(6, 12)] + [[x, 8] for x in range(6, 12)])
    c = np.array([[x, 15] for x in range(0, 4)])
    union = np.unique(np.concatenate((a, b, c)), axis=0)
    traces = [[(0.0, 6.0), (6.0, 6.0)], [(6.0, 8.0), (12.0, 8.0)], [(0.0, 15.5), (4.0, 15.5)]]
    free = np.zeros((20, 20), bool)
    water = np.zeros((20, 20), bool)
    water[7, 5] = water[6, 6] = True
    on_contact = np.zeros((20, 20), bool)
    on_contact[7, 5] = on_contact[6, 6] = True
    # pont de c seulement : le contact a/b reste
    _, added, defects = repair_union_corners(union, [a, b, c], traces, free,
                                             water=water, link_water=[None, None, on_contact])
    assert len(added) == 0 and defects == (((5, 6), (6, 7)),)
    # pont de b sur (6, 6) seulement : seule case permise, prise
    own = np.zeros((20, 20), bool)
    own[6, 6] = True
    _, added, defects = repair_union_corners(union, [a, b, c], traces, free,
                                             water=water, link_water=[None, own, on_contact])
    assert added.tolist() == [[6, 6]] and defects == ()
    # sans ``water`` : comportement d'avant (seul ``forbidden`` compte)
    _, added, _ = repair_union_corners(union, [a, b, c], traces, free)
    assert added.tolist() == [[5, 7]]


def test_paths_avoid_obstacles_and_water_except_bridges(placed):
    """Aucune case sur un green, une boîte, un bunker, le parvis ou l'eau, hors
    cases de pont (sur l'eau, d'une liaison qui est un pont)."""
    paths = placed.paths
    scene = paths.debug.scene
    obstacles = obstacle_mask(scene)
    cells = paths.cells
    assert len(cells) and not obstacles[cells[:, 1], cells[:, 0]].any()
    wet = scene.water[cells[:, 1], cells[:, 0]]
    assert np.array_equal(paths.bridge_cells, cells[wet])
    for lp in paths.debug.links:
        own_wet = scene.water[lp.cells[:, 1], lp.cells[:, 0]]
        assert not own_wet.any() or lp.route.bridge, lp.index
        assert np.array_equal(lp.bridge_cells, lp.cells[own_wet])
    if paths.plaza is not None:
        plaza = {tuple(c) for c in paths.plaza.cells.tolist()}
        assert len(plaza) == paths.plaza.size ** 2
        assert not plaza & {tuple(c) for c in cells.tolist()}


@pytest.fixture(scope="module", params=paths_cases())
def placed_gain(request):
    """``place_paths`` d'un parcours avec la règle du gain (25 %)."""
    data, stub = case_input(request.param, request)
    with pytest.MonkeyPatch.context() as mp:
        if stub is not None:
            stub_course_input(mp, stub, pscene)
        return place_paths(data, bridge_rule=BridgeRule.gained(0.25))


def test_gain_rule_invariants(placed_gain):
    """Règle du gain : chaque liaison d'un seul morceau (calcul indépendant
    de la conversion), union sans contact par un coin, aucune case sur un
    obstacle, eau seulement sous les liaisons en pont."""
    paths = placed_gain
    links = paths.debug.links
    for lp in links:
        if lp.status != "trivial":
            assert lp.blocks.components == 1 and lp.blocks.corner_only == 0, lp.index
            assert lp.blocks.severed == 0 and lp.contacts_missing == 0, lp.index
    assert union_four_connectivity([lp.cells.tolist() for lp in links])["split_links"] == 0
    assert paths.debug.union_defects == ()
    scene = paths.debug.scene
    assert not obstacle_mask(scene)[paths.cells[:, 1], paths.cells[:, 0]].any()
    owned = {tuple(c) for lp in links if lp.route.bridge for c in lp.cells.tolist()}
    owned |= {tuple(c) for c in paths.debug.union_added.tolist()}
    assert {tuple(c) for c in paths.bridge_cells.tolist()} <= owned


def test_each_link_touches_both_of_its_ends(placed):
    """Contact par une face aux deux bouts : green ou boîte, et parvis (le
    clubhouse sans parvis est un point, sans contact à vérifier) ; une
    liaison triviale (bouts à moins d'un bloc) n'est pas posée."""
    scene = placed.paths.debug.scene
    for lp in placed.paths.debug.links:
        if lp.status == "trivial":
            continue
        assert lp.contacts_missing == 0, lp.index
        for ref in (lp.link.src_ref, lp.link.dst_ref):
            if ref is not None:
                surface = next(o.cells for o in scene.obstacles if o.ref == ref)
                assert pblocks.touches(lp.cells, surface), (lp.index, ref)


def test_anchors_sit_on_free_rough_off_every_path(placed):
    paths = placed.paths
    scene = paths.debug.scene
    obstacles = obstacle_mask(scene)
    union = {tuple(c) for c in paths.cells.tolist()}
    anchors = [tuple(c) for c in paths.anchors.tolist()]
    assert len(set(anchors)) == len(anchors) == sum(lp.bends.placed for lp in paths.debug.links)
    assert sorted(anchors) == sorted(c for lp in paths.debug.links for c in lp.anchor_cells)
    for x, z in anchors:
        assert 0 <= x < scene.width and 0 <= z < scene.height
        assert not (obstacles[z, x] or scene.water[z, x] or scene.fairway[z, x]), (x, z)
        assert (x, z) not in union


def test_layer_cells_are_sorted_unique_integer_pairs(placed):
    paths = placed.paths
    for arr in (paths.cells, paths.bridge_cells, paths.anchors,
                *(() if paths.plaza is None else (paths.plaza.cells,))):
        assert arr.dtype == np.int64 and arr.ndim == 2 and arr.shape[1] == 2
        rows = [tuple(c) for c in arr.tolist()]
        assert rows == sorted(set(rows))                     # x puis z, sans doublon
    assert paths.width == pscene.PATH_WIDTH[paths.debug.scene.style]


def test_place_paths_is_deterministic(placed):
    a, b = placed.paths, placed.again
    assert a.width == b.width
    for name in ("cells", "bridge_cells", "anchors"):
        assert np.array_equal(getattr(a, name), getattr(b, name)), name
    assert (a.plaza is None) == (b.plaza is None)
    if a.plaza is not None:
        assert np.array_equal(a.plaza.cells, b.plaza.cells)
        assert (a.plaza.size, a.plaza.shift) == (b.plaza.size, b.plaza.shift)
    for x, y in zip(a.debug.links, b.debug.links):
        assert x.points == y.points and np.array_equal(x.cells, y.cells)
        assert x.anchors == y.anchors


def test_place_paths_raises_path_error_when_a_link_has_no_route(monkeypatch):
    """Une liaison sans route est un bogue : ``PathError`` remonte de
    ``place_paths``, rien de silencieux."""
    data, stub = fabricated_variant("nominal")
    stub_course_input(monkeypatch, stub, pscene)
    monkeypatch.setattr(proute, "search", lambda *args, **kwargs: None)
    monkeypatch.setattr(proute, "line_is_free", lambda *args, **kwargs: False)
    with pytest.raises(PathError):
        place_paths(data)


@pytest.mark.parametrize("fault", ["severed", "contact"])
def test_a_cut_link_is_a_path_error_naming_the_link(monkeypatch, fault):
    """Avec les corrections, une liaison coupée (tracé en morceaux, ou
    surface non touchée) lève ``PathError`` au lieu d'être exportée ; le
    message nomme la liaison."""
    data, stub = fabricated_variant("nominal")
    stub_course_input(monkeypatch, stub, pscene)
    target = next(lp.index for lp in place_paths(data).debug.links if lp.status != "trivial")
    if fault == "severed":
        real = pcourse.link_blocks
        monkeypatch.setattr(pcourse, "link_blocks", lambda scene, link, *args: replace(
            real(scene, link, *args), severed=int(link.index == target)))
    else:
        monkeypatch.setattr(pcourse, "contacts_missing",
                            lambda scene, link, cells: int(link.index == target))
    with pytest.raises(PathError, match=rf"liaison {target} \(.+ → .+\) coupée"):
        place_paths(data)
    with pytest.raises(PathError, match="coupée"):
        place_paths(data, bridge_rule=BridgeRule.gained(0.15))


def test_bend_on_a_long_free_straight_and_none_on_shared_pieces():
    """Un tronçon propre de 45 blocs reçoit un virage (ancrage côté intérieur,
    entre la droite et le sommet) ; partagé en entier, aucun."""
    data, stub = bends_variant()
    with pytest.MonkeyPatch.context() as mp:
        stub_course_input(mp, stub, pscene)
        paths = place_paths(data)
    lp = paths.debug.links[0]
    assert lp.bends.placed == 1 and lp.bends.segment_length == 45.0
    bend = lp.bends.bends[0]
    y = lp.link.start[1]
    assert bend.anchor[0] == bend.apex[0]                      # même perpendiculaire
    assert 0.0 < (bend.anchor[1] - y) / (bend.apex[1] - y) < 1.0   # entre la droite et le sommet
    scene = paths.debug.scene
    route = lp.route
    _, report = bend_route(scene, route, route.points, 0, None, obstacle_mask(scene),
                           shared=((0.0, route.length),))
    assert not report.eligible and not report.bends


# === Flux des virages ===

def test_bend_stream_is_dedicated_and_reserved_streams_stay_free():
    taken = {rng.TEE_STREAM, rng.PAIR_STREAM, rng.FAIRWAY_STREAM, rng.PROFILE_STREAM,
             rng.EMPTY_HOLE_STREAM, rng.REPLACED_GREEN_STREAM, beans.BUNKER_STREAM,
             pots.CLUSTER_STREAM, pots.MIX_STREAM, pots.STAGGER_STREAM, pots.TRIO_STREAM,
             pots.COUNT_STREAM, green_phase.HARICOT_FLANK_STREAM, selection.SELECTION_STREAM,
             *rng.RETIRED_STREAMS}
    assert rng.BENDS_STREAM == 0x56495247 and rng.BENDS_STREAM.to_bytes(4, "big") == b"VIRG"
    assert rng.RESERVED_STREAMS == (0x43484D4E,)
    assert rng.RESERVED_STREAMS[0].to_bytes(4, "big") == b"CHMN"
    assert rng.BENDS_STREAM not in taken | set(rng.RESERVED_STREAMS)
    assert not set(rng.RESERVED_STREAMS) & (taken | {rng.BENDS_STREAM})
    a = rng.bend_rng(5, 0).random(4)
    assert np.array_equal(a, np.random.default_rng(
        [5, rng.RNG_LABEL, rng.COURSE_ORDER, rng.BENDS_STREAM, 1]).random(4))
    assert np.array_equal(a, rng.bend_rng(5, 0).random(4))
    assert not np.array_equal(a, rng.bend_rng(5, 1).random(4))
    assert not np.array_equal(a, rng.bend_rng(6, 0).random(4))


def test_bend_stream_is_frozen():
    assert rng.BENDS_STREAM == 0x56495247 and rng.RESERVED_STREAMS == (0x43484D4E,)
    for seed, index in ((0, 0), (4, 3), (2**63 - 1, 19)):
        expected = np.random.default_rng(
            [seed, rng.RNG_LABEL, rng.COURSE_ORDER, rng.BENDS_STREAM, index + 1])
        assert np.array_equal(rng.bend_rng(seed, index).random(4), expected.random(4))


def test_path_error_is_not_a_value_error():
    assert not issubclass(PathError, ValueError) and issubclass(PathError, Exception)
