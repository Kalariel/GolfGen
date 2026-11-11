"""Grille d'une liaison, dilatation et A* multi-source, multi-cible.

Grille (``build_grid``) : cases dans la boîte englobante de ``start–end``
élargie de ``margin`` blocs (``WINDOW_MARGINS`` : 15, puis 30, puis 60 si
rien n'est trouvé). Cases interdites : obstacles dilatés d'une demi-largeur
plus ``CELL_PAD``, plus ``GREEN_MARGIN`` autour des greens et
``BUNKER_MARGIN`` autour des bunkers ; boîtes et parvis dilatés de la seule
demi-largeur. Les deux surfaces de la liaison sont des obstacles bruts,
sans dilatation : on ne les traverse pas. Relâchement : à moins de ``hw +
max(marges) + 1`` d'une extrémité (anneau autour d'une surface, disque
autour d'un point), seuls les obstacles bruts sont interdits. Une
extrémité ponctuelle (clubhouse sans parvis) a sa case libre.

``CELL_PAD`` (√2/2, du centre au coin d'une case) : la dilatation se mesure
du centre des cases, un échantillon dans une case libre est donc à au
moins hw + marge de l'obstacle.

FAIRWAY de la grille (``Grid.fairway``) : le fairway de la scène, ou, avec
``FairwayRule.full_width``, le fairway dilaté de la demi-largeur (cases dont
le centre est à moins de ``w/2`` d'une case de fairway : un axe qui y passe
a une case de son trait sur le fairway) ; son surcoût par bloc est
``Grid.rule.cost`` (``DEFAULT_COST`` par défaut, voir ``fairway_rule``).

A* 8-connexe (``astar``) : toutes les cases du BORD de la surface de départ
(cases de son empreinte dont une voisine en 4-connexité n'en est pas)
partent à coût nul ; la recherche s'arrête sur la première case du bord de
la surface d'arrivée atteinte. Coût d'un pas : longueur (1 ou √2) × (1 +
``rule.cost`` sur le fairway de la grille + ``Grid.bridge_cost`` sur l'eau,
si elle est traversable ; ``BridgeRule.cost``, ``GAIN_COST`` par défaut)
+ ``SLOPE_COST`` × dénivelé (blocs). Pas de diagonale
entre deux cases interdites. Heuristique : distance octile à la boîte
englobante des cases cibles, admissible et cohérente (un pas coûte au moins
sa longueur). Égalités du tas départagées par l'indice de case :
déterministe.

Tronc commun (``Network``) : les liaisons sont posées dans l'ordre de
``routing.links``, chacune sur le réseau des précédentes. AXE d'un chemin
posé : les cases traversées par son tracé (``supercover`` ; la première
liaison posée garde la case) ; un pas sur l'axe coûte ``TRUNK_FACTOR``
(0,5) × son coût ordinaire et l'heuristique est réduite d'autant : elle
reste admissible (un pas coûte alors au moins 0,5 × sa longueur). ANNEAU :
cases dont le centre est à moins de ``w + TRUNK_RING_MARGIN`` d'un tracé
posé, hors axe ; un pas y paie ``TRUNK_RING`` (+2 par bloc).

Portage fidèle de l'étude (« Base : grille, A* multi-source, contournement »
et ``Network``), sans les portes du parvis.
"""

from __future__ import annotations

from dataclasses import dataclass
import heapq
import math
from typing import Iterable

import numpy as np

from golfgen.dressing.paths.bridge_rule import GAIN_COST
from golfgen.dressing.paths.fairway_rule import FairwayRule
from golfgen.dressing.paths.geometry import (Cell, Point, boxes_meet, points_polygon_distance,
                                             polyline_distance, supercover)
from golfgen.dressing.paths.scene import LinkEnds, Scene

GREEN_MARGIN = 2.0       # blocs autour des greens
BUNKER_MARGIN = 2.0      # blocs autour des bunkers
WINDOW_MARGINS = (15, 30, 60)   # blocs autour de la boîte du segment
SLOPE_COST = 2.0         # surcoût par bloc de dénivelé
SQRT2 = math.sqrt(2.0)
CELL_PAD = SQRT2 / 2.0   # ajouté aux dilatations : centre de case → coin (blocs)
TRUNK_FACTOR = 0.5       # coût d'un pas sur l'axe d'un chemin déjà posé (× longueur)
TRUNK_RING = 2.0         # surcoût par bloc sur l'anneau d'un chemin posé, hors axe
TRUNK_RING_MARGIN = 1.0  # anneau : centres à moins de w + ceci de l'axe (blocs)
NEIGHBOURS = ((-1, 0, 1.0), (1, 0, 1.0), (0, -1, 1.0), (0, 1, 1.0),
              (-1, -1, SQRT2), (-1, 1, SQRT2), (1, -1, SQRT2), (1, 1, SQRT2))


@dataclass(frozen=True, eq=False)
class Grid:
    """Fenêtre ``[x0, x1) × [y0, y1)`` (cases) : interdit (surfaces de la
    liaison comprises), eau (dilatée), fairway et relief, indexés
    ``[y - y0, x - x0]`` ; ``own`` : cases des surfaces de la liaison (et
    ``own_polys`` leurs contours), ``other`` : interdit hors de ces
    surfaces, ``sources`` : cases de départ ``(r, c)``, ``goal`` : cases
    cibles ; ``trunk``, ``ring``, ``owner`` : axe, anneau et propriétaires
    des chemins déjà posés (``None`` sans réseau) ; ``rule`` : traitement
    du fairway (``fairway`` : celui de la règle, dilaté avec
    ``rule.full_width``) ; ``bridge_cost`` : surcoût par bloc sur l'eau
    traversable (``BridgeRule.cost``)."""
    x0: int
    y0: int
    forbidden: np.ndarray
    water: np.ndarray
    fairway: np.ndarray
    relief: np.ndarray
    own: np.ndarray | None = None
    sources: tuple[tuple[int, int], ...] = ()
    goal: np.ndarray | None = None
    other: np.ndarray | None = None      # interdit hors surfaces de la liaison
    own_polys: tuple[np.ndarray, ...] = ()
    trunk: np.ndarray | None = None      # axe des chemins déjà posés
    ring: np.ndarray | None = None       # anneau autour de leur bande, hors axe
    owner: np.ndarray | None = None      # liaison propriétaire de chaque case d'axe (-1)
    rule: FairwayRule = FairwayRule()    # traitement du fairway (surcoût, volets a–c)
    bridge_cost: float = GAIN_COST       # surcoût par bloc sur l'eau traversable (pont)

    @property
    def has_trunk(self) -> bool:
        return self.trunk is not None and bool(self.trunk.any())

    def cell(self, p: Point) -> tuple[int, int]:
        """Case ``(r, c)`` du point (bornée à la fenêtre)."""
        h, w = self.forbidden.shape
        return (min(max(int(math.floor(p[1])) - self.y0, 0), h - 1),
                min(max(int(math.floor(p[0])) - self.x0, 0), w - 1))

    def contains(self, p: Point) -> bool:
        h, w = self.forbidden.shape
        return (self.x0 <= p[0] < self.x0 + w) and (self.y0 <= p[1] < self.y0 + h)


def ring_reach(width: float) -> float:
    """Rayon de l'anneau du tronc commun : à moins de ``w + TRUNK_RING_MARGIN``
    de l'axe d'un chemin posé, la bande d'un chemin parallèle toucherait la
    sienne (deux demi-largeurs et une case)."""
    return width + TRUNK_RING_MARGIN


class Network:
    """Chemins déjà posés (tronc commun) sur toute la carte : ``owner``
    ``(h, w)`` : liaison propriétaire de chaque case d'AXE (cases traversées
    par son tracé, ``supercover`` ; la première posée garde la case, -1
    ailleurs), ``ring`` : cases dont le centre est à moins de
    ``ring_reach(w)`` d'un tracé posé, hors axe, et ``polylines`` : tracés
    posés, par indice de liaison."""

    def __init__(self, width: int, height: int, path_width: float):
        self.width, self.height, self.path_width = width, height, path_width
        self.owner = np.full((height, width), -1, dtype=np.int64)
        self.near = np.zeros((height, width), dtype=bool)
        self.polylines: dict[int, list[Point]] = {}

    @property
    def axis(self) -> np.ndarray:
        return self.owner >= 0

    @property
    def ring(self) -> np.ndarray:
        return self.near & ~self.axis

    def add(self, index: int, points: Iterable[Point]) -> None:
        """Pose le tracé ``points`` de la liaison ``index`` (ignoré s'il a
        moins de deux points)."""
        pts = [tuple(map(float, p)) for p in points]
        if len(pts) < 2:
            return
        self.polylines[index] = pts
        for x, z in supercover(pts):
            if 0 <= x < self.width and 0 <= z < self.height and self.owner[z, x] < 0:
                self.owner[z, x] = index
        reach = ring_reach(self.path_width)
        arr = np.asarray(pts, dtype=float)
        x0 = max(0, int(math.floor(arr[:, 0].min() - reach)) - 1)
        z0 = max(0, int(math.floor(arr[:, 1].min() - reach)) - 1)
        x1 = min(self.width, int(math.ceil(arr[:, 0].max() + reach)) + 2)
        z1 = min(self.height, int(math.ceil(arr[:, 1].max() + reach)) + 2)
        if x0 >= x1 or z0 >= z1:
            return
        xs, zs = np.meshgrid(np.arange(x0, x1), np.arange(z0, z1))
        cells = np.column_stack((xs.ravel(), zs.ravel()))
        dist, _ = polyline_distance(cells, pts)
        self.near[z0:z1, x0:x1] |= (dist < reach).reshape(xs.shape)


def dilate(mask: np.ndarray, radius: float) -> np.ndarray:
    """Cases dont le centre est à moins de ``radius`` d'une case marquée
    (distance centre → carré plein)."""
    if radius <= 0 or not mask.any():
        return mask.copy()
    out = mask.copy()
    reach = int(math.ceil(radius + 0.5))
    h, w = mask.shape
    for dy in range(-reach, reach + 1):
        for dx in range(-reach, reach + 1):
            if (dx, dy) == (0, 0):
                continue
            if math.hypot(max(abs(dx) - 0.5, 0.0), max(abs(dy) - 0.5, 0.0)) >= radius:
                continue
            src = mask[max(0, -dy):h - max(0, dy), max(0, -dx):w - max(0, dx)]
            out[max(0, dy):h - max(0, -dy), max(0, dx):w - max(0, -dx)] |= src
    return out


def border(mask: np.ndarray) -> np.ndarray:
    """Cases marquées dont une voisine (4-connexité) ne l'est pas."""
    padded = np.pad(mask, 1, constant_values=False)
    inner = (padded[:-2, 1:-1] & padded[2:, 1:-1] & padded[1:-1, :-2] & padded[1:-1, 2:])
    return mask & ~inner


def window(scene: Scene, link: LinkEnds, margin: float) -> tuple[int, int, int, int]:
    """Fenêtre ``(x0, y0, x1, y1)`` : boîte de ``start–end`` élargie de
    ``margin``, bornée à la carte."""
    xs, ys = (link.start[0], link.end[0]), (link.start[1], link.end[1])
    return (max(0, int(math.floor(min(xs) - margin))), max(0, int(math.floor(min(ys) - margin))),
            min(scene.width, int(math.ceil(max(xs) + margin)) + 1),
            min(scene.height, int(math.ceil(max(ys) + margin)) + 1))


def near_cells(point: Point, poly: np.ndarray | None, box: tuple[int, int, int, int],
               radius: float) -> np.ndarray:
    """Cases de ``box`` (``ex0, ey0, ex1, ey1``) dont le centre est à moins
    de ``radius`` du polygone plein ``poly`` (ou du point sans polygone)."""
    ex0, ey0, ex1, ey1 = box
    out = np.zeros((ey1 - ey0, ex1 - ex0), dtype=bool)
    if poly is None:
        lo = hi = np.asarray(point, dtype=float)
    else:
        lo, hi = poly.min(axis=0), poly.max(axis=0)
    x0, y0 = max(ex0, int(math.floor(lo[0] - radius))), max(ey0, int(math.floor(lo[1] - radius)))
    x1 = min(ex1, int(math.ceil(hi[0] + radius)) + 1)
    y1 = min(ey1, int(math.ceil(hi[1] + radius)) + 1)
    if x0 >= x1 or y0 >= y1:
        return out
    xs, ys = np.meshgrid(np.arange(x0, x1) + 0.5, np.arange(y0, y1) + 0.5)
    pts = np.column_stack((xs.ravel(), ys.ravel()))
    if poly is None:
        dist = np.hypot(pts[:, 0] - point[0], pts[:, 1] - point[1])
    else:
        dist = points_polygon_distance(pts, poly)
    out[y0 - ey0:y1 - ey0, x0 - ex0:x1 - ex0] = (dist < radius).reshape(xs.shape)
    return out


def build_grid(scene: Scene, link: LinkEnds, margin: float,
               network: Network | None = None) -> Grid:
    """Grille de ``link`` dans sa fenêtre de marge ``margin`` (voir le
    docstring du module) ; avec ``network``, axe, anneau et propriétaires
    des chemins déjà posés."""
    hw = scene.path_width / 2.0
    wx0, wy0, wx1, wy1 = window(scene, link, margin)
    clear = hw + CELL_PAD
    pad = int(math.ceil(clear + max(GREEN_MARGIN, BUNKER_MARGIN))) + 2
    ex0, ey0 = max(0, wx0 - pad), max(0, wy0 - pad)
    ex1, ey1 = min(scene.width, wx1 + pad), min(scene.height, wy1 + pad)
    shape = (ey1 - ey0, ex1 - ex0)
    layers = {"green": np.zeros(shape, bool), "bunker": np.zeros(shape, bool),
              "tee": np.zeros(shape, bool), "plaza": np.zeros(shape, bool)}
    src_own, dst_own = np.zeros(shape, bool), np.zeros(shape, bool)
    ext_box = (ex0, ey0, ex1, ey1)
    for obstacle in scene.obstacles:
        if not boxes_meet(ext_box, obstacle.bbox, 0.0):
            continue
        # l'étude saute ici les refs de ``link.exclude`` sans surface : en
        # production, ``exclude`` n'a que les refs des deux surfaces
        # (``scene_from_json``), la branche est retirée
        own = obstacle.ref in (link.src_ref, link.dst_ref)
        cells = obstacle.cells
        keep = ((cells[:, 0] >= ex0) & (cells[:, 0] < ex1)
                & (cells[:, 1] >= ey0) & (cells[:, 1] < ey1))
        cells = cells[keep]
        if own:
            target = src_own if obstacle.ref == link.src_ref else dst_own
        else:
            target = layers[obstacle.kind]
        target[cells[:, 1] - ey0, cells[:, 0] - ex0] = True
    raw = layers["green"] | layers["bunker"] | layers["tee"] | layers["plaza"]
    wide = (raw | dilate(layers["green"], clear + GREEN_MARGIN)
            | dilate(layers["bunker"], clear + BUNKER_MARGIN)
            | dilate(layers["tee"] | layers["plaza"], clear))
    water_raw = scene.water[ey0:ey1, ex0:ex1]
    water_wide = dilate(water_raw, clear)
    # relâchement autour des extrémités (anneau autour d'une surface, disque
    # autour d'un point) : seules les cases des obstacles bruts (et de l'eau
    # brute) y sont interdites. Rayon hw + 2 + 1 : 4 blocs en links
    # (largeur 2), 4,5 en parkland (largeur 3)
    relax = hw + max(GREEN_MARGIN, BUNKER_MARGIN) + 1.0
    near = (near_cells(link.start, link.src_poly, ext_box, relax)
            | near_cells(link.end, link.dst_poly, ext_box, relax))
    forbidden = np.where(near, raw, wide)
    water = np.where(near, water_raw, water_wide)
    for p, poly in ((link.start, link.src_poly), (link.end, link.dst_poly)):
        if poly is None:                 # extrémité ponctuelle : sa case est libre
            r = min(max(int(math.floor(p[1])) - ey0, 0), shape[0] - 1)
            c = min(max(int(math.floor(p[0])) - ex0, 0), shape[1] - 1)
            forbidden[r, c] = water[r, c] = False
    own = src_own | dst_own
    crop = (slice(wy0 - ey0, wy1 - ey0), slice(wx0 - ex0, wx1 - ex0))
    rule = scene.fairway_rule
    if rule.full_width:                  # volet a) : fairway sous tout le trait
        fairway = dilate(scene.fairway[ey0:ey1, ex0:ex1], hw)[crop]
    else:
        fairway = scene.fairway[wy0:wy1, wx0:wx1]
    grid = Grid(wx0, wy0, (forbidden | own)[crop], water[crop],
                fairway, scene.relief[wy0:wy1, wx0:wx1], own[crop])
    src_edge, dst_edge = border(src_own), border(dst_own)
    if link.src_poly is not None and src_own.any():
        sources = tuple((int(r), int(c)) for r, c in np.argwhere(src_edge[crop]))
    else:
        sources = (grid.cell(link.start),)
    if link.dst_poly is not None and dst_own.any():
        goal = dst_edge[crop]
    else:
        goal = np.zeros(grid.forbidden.shape, bool)
        goal[grid.cell(link.end)] = True
    trunk = ring = owner = None
    if network is not None and network.polylines:
        owner = network.owner[wy0:wy1, wx0:wx1].copy()
        trunk = owner >= 0
        ring = network.ring[wy0:wy1, wx0:wx1].copy()
    return Grid(grid.x0, grid.y0, grid.forbidden, grid.water, grid.fairway, grid.relief,
                grid.own, sources, goal, forbidden[crop], tuple(link.surfaces),
                trunk, ring, owner, rule, scene.bridge_rule.cost)


def is_cell(value) -> bool:
    """``value`` est une case ``(r, c)`` (et non une suite de cases)."""
    return (isinstance(value, tuple) and len(value) == 2
            and all(isinstance(v, (int, np.integer)) for v in value))


def shortest_path(grid: Grid, start: Cell | Iterable[Cell], goal: Cell | np.ndarray, *,
                  allow_water: bool, heuristic: bool = True) -> tuple[list[Cell], float] | None:
    """Plus court chemin de cases ``(r, c)`` d'une des cases ``start`` (une
    case ou une suite de cases, à coût nul) à une des cases ``goal`` (une
    case ou un masque), et son coût (voir le docstring du module) ; ``None``
    sans chemin dans la fenêtre. Sources et cibles peuvent être des cases
    des surfaces de la liaison (``grid.own``), interdites à la traversée.
    ``heuristic=False`` : Dijkstra (heuristique nulle), même coût que l'A*
    puisque son heuristique est admissible (contrôle des tests)."""
    blocked = grid.forbidden | (np.zeros_like(grid.water) if allow_water else grid.water)
    h, w = blocked.shape
    own = grid.own if grid.own is not None else np.zeros((h, w), bool)
    usable = ~(blocked & ~own)           # libres, ou dans une surface de la liaison
    if isinstance(goal, np.ndarray):
        goal_mask = goal.astype(bool) & usable
    else:
        goal_mask = np.zeros((h, w), bool)
        goal_mask[goal] = usable[goal]
    sources = [start] if is_cell(start) else list(start)
    sources = [s for s in sources if usable[s]]
    if not sources or not goal_mask.any():
        return None
    enter = ~blocked | goal_mask
    goal_flat = goal_mask.ravel()
    rows, cols = np.nonzero(goal_mask)
    gr0, gr1, gc0, gc1 = int(rows.min()), int(rows.max()), int(cols.min()), int(cols.max())
    # tronc commun : un pas sur l'axe d'un chemin posé coûte TRUNK_FACTOR ×
    # le coût ordinaire, l'heuristique est réduite d'autant (admissible)
    scale = (TRUNK_FACTOR if grid.has_trunk else 1.0) if heuristic else 0.0

    def estimate(r: int, c: int) -> float:
        # distance octile à la boîte des cibles : admissible (voir le module)
        ar, ac = max(gr0 - r, 0, r - gr1), max(gc0 - c, 0, c - gc1)
        return scale * (max(ar, ac) + (SQRT2 - 1.0) * min(ar, ac))

    extra = (1.0 + grid.rule.cost * grid.fairway
             + (grid.bridge_cost * grid.water if allow_water else 0.0))
    if grid.has_trunk:
        extra = (extra + TRUNK_RING * grid.ring) * np.where(grid.trunk, TRUNK_FACTOR, 1.0)
    relief = grid.relief
    g = np.full(h * w, np.inf)
    parent = np.full(h * w, -1, dtype=np.int64)
    closed = np.zeros(h * w, dtype=bool)
    heap = []
    for r, c in sources:
        s = r * w + c
        if g[s] > 0.0:
            g[s] = 0.0
            heapq.heappush(heap, (estimate(r, c), s))
    t = -1
    while heap:
        _, u = heapq.heappop(heap)
        if closed[u]:
            continue
        if goal_flat[u]:
            t = u
            break
        closed[u] = True
        r, c = divmod(u, w)
        for dr, dc, d in NEIGHBOURS:
            nr, nc = r + dr, c + dc
            if not (0 <= nr < h and 0 <= nc < w) or not enter[nr, nc]:
                continue
            if dr and dc and (blocked[r, nc] or blocked[nr, c]):
                continue
            v = nr * w + nc
            if closed[v]:
                continue
            cost = g[u] + d * extra[nr, nc] + SLOPE_COST * abs(relief[nr, nc] - relief[r, c])
            if cost < g[v]:
                g[v] = cost
                parent[v] = u
                heapq.heappush(heap, (cost + estimate(nr, nc), v))
    if t < 0:
        return None
    path = [t]
    while parent[path[-1]] >= 0:
        path.append(int(parent[path[-1]]))
    return [divmod(v, w) for v in reversed(path)], float(g[t])


def astar(grid: Grid, start: Cell | Iterable[Cell], goal: Cell | np.ndarray, *,
          allow_water: bool) -> list[Cell] | None:
    """Chemin de ``shortest_path`` (A*, heuristique octile), sans son coût."""
    found = shortest_path(grid, start, goal, allow_water=allow_water)
    return None if found is None else found[0]
