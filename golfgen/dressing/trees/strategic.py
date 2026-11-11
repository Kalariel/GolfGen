"""Arbres stratégiques : couches retombée puis green, avant tout remplissage.

Portage de ``strategic_layers`` (étude stratégique du lot 5, retirée au R7),
remplissage vide, empiètement ``ENCROACHMENT`` ; aucune mesure ni rapport.
Couronnes de rayon ``CROWN_RADIUS``.

Retombée (par 4 et 5) : zone de réception la plus proche de ``draws["drive"]``
(même rejeu du flux du fairway que ``bunkers.sites.candidates``, contrôlé
contre un ``profile_neck`` rejoué, voir ``zone_for``). ``h`` = demi-largeur du fairway sur la normale ;
centre à ``landing_offset(h, e)`` de l'axe. Paire tirée : deux arbres à
``zone ± TWIN_SPACING / 2``, même côté, côté tiré puis l'autre, dans le plateau ;
sinon arbre unique, essais ``TRIAL_OFFSETS``, côté tiré puis l'autre, dans le
plateau (y compris un arbre décentré après une paire ratée). Passage libre
``PASSAGE_MIN`` sur les coupes entamées.

Green (tous les trous) : secteurs ``SECTOR_CENTER`` ± ``SECTOR_HALF`` degrés de
part et d'autre de l'axe d'approche ; arbre du côté sans bunker de green, côté
tiré sans aucun bunker, trou sauté si les deux côtés en ont. Couche posée après
la retombée, en évitant ses arbres.

Commun : quota ``round(éligibles / QUOTA_DIVISOR)`` par couche, trous visités
dans un ordre tiré (``tree_rng``) ; couronne interdite sur ``ForbiddenMasks.base``
(sans abords), les corridors ``others`` des autres trous, les couronnes déjà
posées, hors de la carte. Un trou sauté n'est jamais une erreur : il est
compté par motif dans ``StrategicLayer.skips``.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
import math
from typing import Any, Mapping, Sequence

import numpy as np

from golfgen.dressing.fairway import (FAIRWAY_STYLES, Axis, cap_half, landing_zones, profile_draws,
                                      profile_neck)
from golfgen.dressing.from_json import CourseInput
from golfgen.dressing.paths.geometry import outline_polygon
from golfgen.dressing.rng import (TREE_GREEN_LAYER, TREE_LANDING_LAYER, TREE_USE_HOLE, TREE_USE_ORDER,
                                  fairway_rng, tree_rng)
from golfgen.dressing.trees.errors import TreeError
from golfgen.dressing.trees.geometry import CROWN_RADIUS, ForbiddenMasks, crown_cells, crown_on_map

# Portée réelle d'une couronne : coin de case le plus loin du centre de l'arbre.
CROWN_REACH = math.hypot(CROWN_RADIUS + 0.5, 0.5)

ENCROACHMENT = 3.0          # blocs : empiètement sur le fairway
LANDING_AXIS_MARGIN = 0.5   # blocs : bord de couronne d'un arbre de retombée au plus près de l'axe
AXIS_CLEARANCE = 2.0        # blocs : bord de couronne d'un arbre de green au plus près de l'axe
PASSAGE_MIN = 6.0           # blocs libres dans une coupe entamée
TRIAL_OFFSETS = (0.0, 4.0, -4.0, 8.0, -8.0)     # blocs le long de l'axe (retombée)
TWIN_SPACING = 8.0          # blocs entre les deux arbres d'une retombée
TWIN_PROBABILITY = 0.5      # chance de tirer deux arbres

SECTOR_CENTER = 90.0        # degrés depuis l'axe d'approche
SECTOR_HALF = 45.0          # degrés
GREEN_EDGE_GAP = 1.0        # blocs entre le contour du green et le bord de couronne
GREEN_TRIAL_ANGLES = (0.0, 15.0, -15.0, 30.0, -30.0)     # degrés autour du flanc

QUOTA_DIVISOR = 3
SECTION_STEP = 0.1          # blocs entre deux coupes transversales
SECTION_SCAN = 18.0         # blocs : coupes retenues autour d'un arbre

LANDING_KEY, GREEN_KEY = "retombee", "green"

Cell = tuple[int, int]


@dataclass(frozen=True, slots=True)
class StrategicTree:
    """Un arbre stratégique : case ``(x, z)``, rayon, couche
    (``LANDING_KEY`` ou ``GREEN_KEY``) et trou."""
    x: int
    z: int
    radius: int
    layer: str
    hole: int


@dataclass(frozen=True)
class StrategicLayer:
    """Une couche : arbres dans l'ordre de pose, trous sautés par motif."""
    name: str
    trees: tuple[StrategicTree, ...]
    skips: Mapping[str, int]


@dataclass(frozen=True)
class StrategicTrees:
    """Les deux couches stratégiques d'un parcours."""
    landing: StrategicLayer
    green: StrategicLayer

    @property
    def trees(self) -> tuple[StrategicTree, ...]:
        """Retombée puis green, dans l'ordre de pose."""
        return self.landing.trees + self.green.trees


@dataclass(frozen=True, eq=False)
class HoleView:
    """Ce que lit la couche d'un trou : modèle, axe, morceaux de fairway,
    contour du green (double le cas échéant), drapeau et unité de l'axe
    d'approche."""
    order: int
    par: int
    axis: Axis
    points: np.ndarray
    fairway: tuple[np.ndarray, ...]
    green: np.ndarray
    flag: np.ndarray
    approach: np.ndarray


# === Géométrie ===

def contains(polygon: np.ndarray, point) -> bool:
    """Pair-impair : ``point`` est-il dans ``polygon`` ?"""
    x, y = float(point[0]), float(point[1])
    ax, ay = polygon[:, 0], polygon[:, 1]
    bx, by = np.roll(ax, -1), np.roll(ay, -1)
    with np.errstate(divide="ignore", invalid="ignore"):
        hits = ((ay > y) != (by > y)) & (x < ax + (y - ay) * (bx - ax) / (by - ay))
    return bool(np.count_nonzero(hits) % 2)


def ray_exit(polygon: np.ndarray, origin, direction) -> float | None:
    """Première traversée de ``polygon`` sur la demi-droite, ``None`` sinon."""
    a, e = polygon, np.roll(polygon, -1, axis=0) - polygon
    wx, wy = a[:, 0] - float(origin[0]), a[:, 1] - float(origin[1])
    dx, dy = float(direction[0]), float(direction[1])
    denom = dx * e[:, 1] - dy * e[:, 0]
    with np.errstate(divide="ignore", invalid="ignore"):
        t = (wx * e[:, 1] - wy * e[:, 0]) / denom
        u = (wx * dy - wy * dx) / denom
    valid = (denom != 0.0) & (u >= 0.0) & (u < 1.0) & (t > 1e-9)
    return float(t[valid].min()) if valid.any() else None


def fairway_half_width(pieces: Sequence[np.ndarray], point, direction) -> float | None:
    """Distance de ``point`` au bord du morceau de fairway qui le contient,
    dans ``direction`` ; ``None`` si ``point`` est hors de tout morceau."""
    for piece in pieces:
        if contains(piece, point):
            return ray_exit(piece, point, direction)
    return None


def segment_square_distance(ix: int, iy: int, a, b) -> float:
    """Distance entre la case ``[ix, ix+1] × [iy, iy+1]`` et le segment ``ab``."""
    ax, ay, bx, by = float(a[0]), float(a[1]), float(b[0]), float(b[1])
    low, high = 0.0, 1.0                    # Liang-Barsky : traversée de la case
    for p, q in ((-(bx - ax), ax - ix), (bx - ax, ix + 1 - ax),
                 (-(by - ay), ay - iy), (by - ay, iy + 1 - ay)):
        if p == 0.0:
            if q < 0.0:
                low, high = 1.0, 0.0
        elif p < 0.0:
            low = max(low, q / p)
        else:
            high = min(high, q / p)
    if low <= high:
        return 0.0
    dx, dy = bx - ax, by - ay
    length2 = dx * dx + dy * dy
    corners = ((ix, iy), (ix + 1, iy), (ix + 1, iy + 1), (ix, iy + 1))

    def to_segment(px: float, py: float) -> float:
        t = 0.0 if length2 == 0.0 else max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / length2))
        return math.hypot(px - (ax + t * dx), py - (ay + t * dy))

    def to_square(px: float, py: float) -> float:
        qx, qy = min(max(px, ix), ix + 1), min(max(py, iy), iy + 1)
        return math.hypot(px - qx, py - qy)

    return min(min(to_segment(cx, cy) for cx, cy in corners), to_square(ax, ay), to_square(bx, by))


def crown_axis_gap(cell: Sequence[int], points: np.ndarray) -> float:
    """Distance minimale entre la couronne et la polyligne ``points``."""
    return min(segment_square_distance(int(x), int(y), a, b)
               for x, y in crown_cells(cell).tolist()
               for a, b in zip(points, points[1:]))


def section_free(point, normal, pieces: Sequence[np.ndarray], crowns: np.ndarray) -> tuple[float, bool] | None:
    """Passage de la coupe en ``point`` le long de ``normal`` : longueur libre
    du fairway autour du point moins les couronnes, et si une couronne
    l'entame. ``None`` si ``point`` est hors du fairway."""
    px, py = float(point[0]), float(point[1])
    nx, ny = float(normal[0]), float(normal[1])
    forward = fairway_half_width(pieces, (px, py), (nx, ny))
    backward = fairway_half_width(pieces, (px, py), (-nx, -ny))
    if forward is None or backward is None:
        return None
    low, high = -backward, forward
    start_low, start_high = low, high
    for ix, iy in crowns.tolist():
        t0, t1 = -math.inf, math.inf
        for origin, slope, lo, hi in ((px, nx, ix, ix + 1), (py, ny, iy, iy + 1)):
            if slope == 0.0:
                if origin < lo or origin > hi:
                    t0, t1 = 1.0, 0.0
            else:
                near, far = sorted(((lo - origin) / slope, (hi - origin) / slope))
                t0, t1 = max(t0, near), min(t1, far)
        if t0 >= t1:
            continue
        if t0 <= 0.0 <= t1:
            return 0.0, True
        if t1 < 0.0:
            low = max(low, t1)
        else:
            high = min(high, t0)
    return high - low, (low > start_low or high < start_high)


def min_section_free(view: HoleView, trees: Sequence[Cell]) -> float | None:
    """Plus petit passage libre des coupes entamées par ``trees`` (axe sur le
    fairway, perpendiculaires à l'axe) ; ``None`` si aucune n'est entamée."""
    if not trees or not view.fairway:
        return None
    stations = np.arange(0.0, view.axis.length + SECTION_STEP, SECTION_STEP)
    points, normals = view.axis.at(stations)
    centres = np.asarray(trees, dtype=float) + 0.5
    near = (((points[:, None] - centres[None]) ** 2).sum(axis=2) <= SECTION_SCAN ** 2).any(axis=1)
    crowns = np.concatenate([crown_cells(tree) for tree in trees])
    smallest = None
    for point, normal in zip(points[near], normals[near]):
        section = section_free(point, normal, view.fairway, crowns)
        if section is not None and section[1]:
            smallest = section[0] if smallest is None else min(smallest, section[0])
    return smallest


def sections_ok(view: HoleView, trees: Sequence[Cell], minimum: float = PASSAGE_MIN) -> bool:
    """Chaque coupe de ``min_section_free`` garde au moins ``minimum`` blocs libres."""
    smallest = min_section_free(view, trees)
    return smallest is None or smallest >= minimum


def fits(mask: np.ndarray, cell: Sequence[int]) -> bool:
    """Couronne entière sur la carte et hors de ``mask``."""
    height, width = mask.shape
    if not crown_on_map(cell[0], cell[1], CROWN_RADIUS, width, height):
        return False
    cells = crown_cells(cell)
    return not mask[cells[:, 1], cells[:, 0]].any()


def landing_offset(half: float, encroachment: float) -> float:
    """Distance centre-axe d'un arbre de retombée : empiètement, couronne hors
    de l'axe (marge ``LANDING_AXIS_MARGIN``), passage libre ≥ ``PASSAGE_MIN``."""
    return max(half - encroachment + CROWN_RADIUS, CROWN_REACH + LANDING_AXIS_MARGIN,
               PASSAGE_MIN - half + CROWN_REACH)


def sector_side(view: HoleView, cell: Cell) -> int:
    """Côté du secteur (+1, -1) du centre de ``cell``, 0 hors des secteurs."""
    vx, vy = cell[0] + 0.5 - view.flag[0], cell[1] + 0.5 - view.flag[1]
    if vx == 0.0 and vy == 0.0:
        return 0
    ux, uy = float(view.approach[0]), float(view.approach[1])
    angle = math.degrees(math.atan2(abs(ux * vy - uy * vx), ux * vx + uy * vy))
    if abs(angle - SECTOR_CENTER) > SECTOR_HALF:
        return 0
    return 1 if (-uy * vx + ux * vy) > 0.0 else -1


# === Parcours ===

def hole_views(data: Mapping[str, Any], layout) -> dict[int, HoleView]:
    """Vues des 18 trous : modèle reconstruit du JSON, fairway lu dans ``features``."""
    pairs = {}
    for pair in data["routing"].get("green_pairs") or []:
        for hole_id in pair["holes"]:
            pairs[hole_id] = outline_polygon(pair["outline"])
    views = {}
    exported = {hole["id"]: hole for hole in data["routing"]["holes"]}
    for hole in layout.holes:
        features = exported[hole.order]["features"]
        points = np.asarray([(p.x, p.y) for p in hole.axis], dtype=float)
        delta = points[-1] - points[-2]
        views[hole.order] = HoleView(
            order=hole.order, par=hole.par, axis=Axis.of(hole), points=points,
            fairway=tuple(outline_polygon(piece["outline"]) for piece in features.get("fairway") or []),
            green=pairs.get(hole.order, outline_polygon(features["green"]["outline"])),
            flag=points[-1], approach=delta / float(np.hypot(*delta)))
    return views


def green_bunker_cells(data: Mapping[str, Any], hole_ids: Sequence[int]) -> dict[int, list[Cell]]:
    """Cases ``role = green`` par trou ; un green double réunit les bunkers
    de ses deux trous."""
    groups = {i: {i} for i in hole_ids}
    for pair in data["routing"].get("green_pairs") or []:
        i, j = pair["holes"]
        groups[i] = groups[j] = {i, j}
    cells: dict[int, list[Cell]] = {i: [] for i in hole_ids}
    items = (data.get("bunkers") or {}).get("items")
    if items is None:
        raise TreeError("JSON sans bunkers.items : la pose des arbres exige les bunkers")
    for item in items:
        if item["role"] != "green":
            continue
        for member in groups[item["hole"]]:
            cells[member].extend((int(x), int(z)) for x, z in item["cells"])
    return cells


def zone_for(hole, style: str, seed: int) -> tuple[float, float] | None:
    """Zone de retombée retenue (la plus proche de ``draws["drive"]``) et
    longueur de son plateau, ``(zone, plateau)`` ; ``None`` sans zone. Mêmes
    appels que ``bunkers.sites.candidates``. Garde : ``TreeError`` si ce rejeu
    diverge de ``Profile.zones`` ou ``Profile.plateaus`` de ``profile_neck``,
    la forme brute de production, rejouée ici sur un flux neuf. Elle détecte
    un décalage du flux ou de la loi entre ces deux chemins, elle ne lit pas
    le fairway effectivement construit par l'habillage : cette concordance-là
    est vérifiée par les tests, en espionnant le vrai pipeline."""
    fairway_style = FAIRWAY_STYLES[style]
    axis = Axis.of(hole)
    draws = profile_draws(fairway_rng(seed, hole.order), fairway_style)
    zones = landing_zones(axis, hole.par, draws)
    profile = profile_neck(hole, axis, fairway_style, fairway_rng(seed, hole.order), cap_half(hole))
    if tuple(zones) != profile.zones or tuple(float(v) for v in draws["plateau"][:len(zones)]) != profile.plateaus:
        raise TreeError(f"trou {hole.order} : zone de retombée divergente du profil du fairway "
                        f"({zones} ; {list(profile.zones)})")
    if not zones:
        return None
    index = min(range(len(zones)), key=lambda k: abs(zones[k] - draws["drive"]))
    return zones[index], float(draws["plateau"][index])


# === Pose ===

def _try_landing_tree(view: HoleView, station: float, side: int, forbidden: np.ndarray,
                      encroachment: float) -> Cell | None:
    """Arbre de retombée à ``station``, côté ``side``, ou ``None``."""
    points, normals = view.axis.at(np.asarray([station]))
    point, normal = points[0], normals[0] * side
    half = fairway_half_width(view.fairway, point, normal)
    if half is None:
        return None
    offset = landing_offset(half, encroachment)
    cell = tuple(int(v) for v in np.floor(point + offset * normal))
    if not fits(forbidden, cell) or crown_axis_gap(cell, view.points) < LANDING_AXIS_MARGIN:
        return None
    return cell


def _try_pair(view: HoleView, zone: float, half: float, side: int, forbidden: np.ndarray,
              encroachment: float) -> tuple[Cell, Cell] | None:
    """Paire à ``zone ± TWIN_SPACING / 2`` du côté ``side``, ou ``None``."""
    step = TWIN_SPACING / 2.0
    if step > half:
        return None
    stations = (zone - step, zone + step)
    if not 0.0 <= stations[0] or stations[1] > view.axis.length:
        return None
    first = _try_landing_tree(view, stations[0], side, forbidden, encroachment)
    if first is None:
        return None
    solid = forbidden.copy()
    cells = crown_cells(first)
    solid[cells[:, 1], cells[:, 0]] = True
    second = _try_landing_tree(view, stations[1], side, solid, encroachment)
    if second is None or not sections_ok(view, [first, second]):
        return None
    return first, second


def place_landing(view: HoleView, zone: float, plateau: float, rng: np.random.Generator,
                  forbidden: np.ndarray, encroachment: float = ENCROACHMENT) -> tuple[tuple[Cell, ...], bool]:
    """Arbres de retombée d'un trou : ``(cases ou (), au moins un essai n'a
    été écarté que par le plateau)``. Paire d'abord si tirée, puis arbre
    unique."""
    half = plateau / 2.0
    first = 1 if rng.random() < 0.5 else -1
    want_two = rng.random() < TWIN_PROBABILITY
    if want_two:
        for side in (first, -first):
            pair = _try_pair(view, zone, half, side, forbidden, encroachment)
            if pair is not None:
                return pair, False
    beyond_plateau = False
    for side in (first, -first):
        for delta in TRIAL_OFFSETS:
            station = zone + delta
            if not 0.0 <= station <= view.axis.length:
                continue
            tree = _try_landing_tree(view, station, side, forbidden, encroachment)
            if tree is None or not sections_ok(view, [tree]):
                continue
            if abs(station - zone) > half:
                beyond_plateau = True
                continue
            return (tree,), False
    return (), beyond_plateau


def _try_green_tree(view: HoleView, side: int, angle: float, forbidden: np.ndarray,
                    landing: Sequence[Cell]) -> Cell | None:
    """Arbre de green de ``side`` à ``angle`` degrés du flanc, ou ``None``."""
    ux, uy = float(view.approach[0]), float(view.approach[1])
    radians = math.radians(angle)
    side_x, side_y = -uy * side, ux * side
    direction = (side_x * math.cos(radians) + ux * math.sin(radians),
                 side_y * math.cos(radians) + uy * math.sin(radians))
    edge = ray_exit(view.green, view.flag, direction)
    if edge is None:
        return None
    reach = edge + GREEN_EDGE_GAP + CROWN_REACH
    cell = (int(math.floor(view.flag[0] + direction[0] * reach)),
            int(math.floor(view.flag[1] + direction[1] * reach)))
    if sector_side(view, cell) != side or not fits(forbidden, cell):
        return None
    if crown_axis_gap(cell, view.points) < AXIS_CLEARANCE:
        return None
    if landing and not sections_ok(view, [*landing, cell]):
        return None
    return cell


def place_green(view: HoleView, bunkers: Sequence[Cell], rng: np.random.Generator,
                forbidden: np.ndarray, landing: Sequence[Cell]) -> tuple[Cell | None, str]:
    """Arbre de green d'un trou : ``(case, "")`` ou ``(None, motif)``. Côté
    tiré d'office, pour que l'ordre des sauts ne décale aucun tirage."""
    drawn = 1 if rng.random() < 0.5 else -1
    sides = {sector_side(view, cell) for cell in bunkers} - {0}
    if sides == {1, -1}:
        return None, "deux_flancs"
    side = -sides.pop() if sides else drawn
    for angle in GREEN_TRIAL_ANGLES:
        tree = _try_green_tree(view, side, angle, forbidden, landing)
        if tree is not None:
            return tree, ""
    return None, "impossible"


def _mark(forbidden: np.ndarray, trees: Sequence[Cell]) -> None:
    for tree in trees:
        cells = crown_cells(tree)
        forbidden[cells[:, 1], cells[:, 0]] = True


def _tree(cell: Cell, layer: str, hole: int) -> StrategicTree:
    return StrategicTree(cell[0], cell[1], CROWN_RADIUS, layer, hole)


def place_strategic(data: Mapping[str, Any], course: CourseInput, masks: ForbiddenMasks,
                    encroachment: float = ENCROACHMENT) -> StrategicTrees:
    """Couches retombée puis green d'un JSON 3.3 et des interdits ``masks``
    (voir le docstring du module)."""
    seed = int(course.seed)
    style = data["metadata"].get("style") or "links"
    views = hole_views(data, course.layout)
    models = {hole.order: hole for hole in course.layout.holes}
    forbidden = masks.base

    # --- couche retombée ---
    eligible = sorted(order for order, view in views.items() if view.par in (4, 5))
    quota = round(len(eligible) / QUOTA_DIVISOR)
    order_rng = tree_rng(seed, TREE_LANDING_LAYER, TREE_USE_ORDER)
    visit = [int(o) for o in order_rng.permutation(eligible)] if eligible else []
    landing_trees: list[StrategicTree] = []
    landing_of: dict[int, tuple[Cell, ...]] = {}
    skips: Counter = Counter()
    for order in visit:
        if len(landing_of) >= quota:
            break
        target = zone_for(models[order], style, seed)
        if target is None:
            skips["sans_zone"] += 1
            continue
        rng = tree_rng(seed, TREE_LANDING_LAYER, TREE_USE_HOLE, order)
        placed, beyond_plateau = place_landing(views[order], *target, rng,
                                               forbidden | masks.others[order], encroachment)
        if not placed:
            skips["hors_plateau" if beyond_plateau else "impossible"] += 1
            continue
        landing_of[order] = placed
        landing_trees.extend(_tree(cell, LANDING_KEY, order) for cell in placed)
        _mark(forbidden, placed)
    landing = StrategicLayer(LANDING_KEY, tuple(landing_trees), dict(sorted(skips.items())))

    # --- couche green, en évitant les arbres de retombée ---
    eligible = sorted(views)
    quota = round(len(eligible) / QUOTA_DIVISOR)
    visit = [int(o) for o in tree_rng(seed, TREE_GREEN_LAYER, TREE_USE_ORDER).permutation(eligible)]
    bunkers = green_bunker_cells(data, eligible)
    green_trees: list[StrategicTree] = []
    skips = Counter()
    for order in visit:
        if len(green_trees) >= quota:
            break
        rng = tree_rng(seed, TREE_GREEN_LAYER, TREE_USE_HOLE, order)
        cell, motif = place_green(views[order], bunkers[order], rng, forbidden | masks.others[order],
                                  landing_of.get(order, ()))
        if cell is None:
            skips[motif] += 1
            continue
        green_trees.append(_tree(cell, GREEN_KEY, order))
        _mark(forbidden, [cell])
    green = StrategicLayer(GREEN_KEY, tuple(green_trees), dict(sorted(skips.items())))
    return StrategicTrees(landing, green)
