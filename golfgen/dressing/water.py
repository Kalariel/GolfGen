"""Eau du relief vue par l'habillage : surfaces et écarts d'un polygone aux
cellules d'eau, à la VRAIE berge (``golfgen.routing.sites.WaterMask`` :
relief < ``WATER_LEVEL``, sans l'élargissement de ``DRY_RADIUS`` du masque
sec du routeur).

Une cellule d'eau ``(ix, iy)`` est le carré fermé ``[ix, ix + 1] × [iy,
iy + 1]`` (indexation des sites, ``grid_indices``). Un polygone (green,
boîte de départ, green double) est AU SEC à la marge ``m`` si :

- ``m = 0`` : son aire commune avec l'eau est nulle (``water_area`` ≤
  ``AREA_NOISE``, bruit flottant du découpage d'un bord posé exactement sur
  un bord de cellule ; un contact par un bord ou un coin est admis) ;
- ``m > 0`` : son écart bord à bord à toute cellule d'eau est ≥ ``m``
  (``water_gap`` ; 0 s'il la touche ou la recouvre).

Contrôles exacts (découpage de Sutherland–Hodgman par le carré, distances
sommet ↔ carré et coin ↔ arête), précédés d'un préfiltre exact : sans
cellule d'eau dans la boîte englobante élargie de ``m``, le polygone est au
sec sans calcul. ``water = None`` : carte sans eau connue, tout est au sec.

Marges retenues (décision utilisateur, lot 1 eau : 0 bloc) :
``GREEN_WATER_MARGIN`` et ``TEE_WATER_MARGIN`` pour les greens et les
boîtes de départ, ``PAIR_WATER_MARGIN`` pour les greens doubles.

Green insulaire (``GreenShape.island``, ``golfgen.dressing.green``) : ses
cellules remontées sont les cellules d'eau qui partagent une aire non nulle
(> ``AREA_NOISE``) avec son contour (``raised_cells``), remontées à
l'altitude minimale de sa partie émergée (cellules sèches qu'il recouvre de
même, ``island_of``) ; bord franc, sans talus. Boîte de départ remontée
(``TeeBox.island``, ``golfgen.dressing.tees``) : même règle
(``tee_island_of``) ; entièrement immergée, à un bloc au-dessus de l'eau
(``WATER_LEVEL + SUBMERGED_TEE_LIFT``). Rien n'est stocké : la remontée se déduit du contour et
du relief.

``effective_water`` rend l'eau EFFECTIVE d'UN trou : eau réelle moins les
cellules remontées de SES éléments (green insulaire, boîtes remontées),
seule eau que lisent les étapes en aval (départs, contrôles ; à venir :
coupure du fairway au R4, bunkers). Les cellules remontées par un trou
restent de l'eau pour les autres (une bande remontée hors du contour d'un
green ou d'une boîte n'est pas du sec pour un autre trou), et aucune boîte
ne se remonte sur une cellule déjà remontée (``dry_tee_boxes``, argument
``raised``). Les greens doubles restent contrôlés sur l'eau RÉELLE (pas
d'insulaire pour eux).
"""

from __future__ import annotations

from collections.abc import Iterable
import math

import numpy as np

from golfgen.dressing.model import GreenIsland, TeeIsland
from golfgen.routing.sites import WATER_LEVEL, WaterMask


# Marges à la berge, en blocs (lot 1 eau, retenues par l'utilisateur) : 0,
# aucune aire commune avec l'eau (contact par un bord admis). 1 bloc (une
# rangée de berge entre la surface tondue et l'eau), mesuré au premier relevé,
# n'a pas été retenu.
GREEN_WATER_MARGIN = 0.0
TEE_WATER_MARGIN = 0.0
PAIR_WATER_MARGIN = 0.0
# blocs² : aire commune en dessous de laquelle un polygone est au sec à la
# marge 0 (bruit flottant du découpage, pas une tolérance de la règle)
AREA_NOISE = 1e-9
# blocs : remontée d'une boîte de départ entièrement immergée au-dessus du
# niveau d'eau (décision utilisateur, lot 1 eau : un bloc au-dessus de l'eau,
# pas à fleur d'eau)
SUBMERGED_TEE_LIFT = 1.0


def _clip_area(polygon: list[tuple[float, float]], ix: int, iy: int) -> float:
    """Aire de ``polygon`` (simple) ∩ carré ``[ix, ix+1] × [iy, iy+1]``
    (Sutherland–Hodgman : le carré est convexe, le polygone quelconque ;
    l'aire du résultat est exacte, aux arrondis près)."""
    out = polygon
    for axis, bound, keep_above in ((0, ix, True), (0, ix + 1, False),
                                    (1, iy, True), (1, iy + 1, False)):
        if not out:
            return 0.0
        clipped = []
        previous = out[-1]
        prev_in = (previous[axis] >= bound) if keep_above else (previous[axis] <= bound)
        for current in out:
            cur_in = (current[axis] >= bound) if keep_above else (current[axis] <= bound)
            if cur_in != prev_in:
                t = (bound - previous[axis]) / (current[axis] - previous[axis])
                point = (previous[0] + t * (current[0] - previous[0]),
                         previous[1] + t * (current[1] - previous[1]))
                clipped.append(point)
            if cur_in:
                clipped.append(current)
            previous, prev_in = current, cur_in
        out = clipped
    if len(out) < 3:
        return 0.0
    total = 0.0
    for (x0, y0), (x1, y1) in zip(out, out[1:] + out[:1]):
        total += x0 * y1 - x1 * y0
    return abs(total) / 2.0


def _cells(outline: np.ndarray, water: WaterMask, reach: float) -> np.ndarray:
    lo, hi = outline.min(axis=0), outline.max(axis=0)
    return water.cells_near(lo[0] - reach, lo[1] - reach, hi[0] + reach, hi[1] + reach)


def water_area(outline, water: WaterMask | None) -> float:
    """Aire commune (blocs²) du polygone ``outline`` et de l'eau."""
    if water is None:
        return 0.0
    polygon = np.asarray(outline, dtype=float)
    cells = _cells(polygon, water, 0.0)
    if not len(cells):
        return 0.0
    points = [tuple(p) for p in polygon.tolist()]
    return float(sum(_clip_area(points, int(ix), int(iy)) for ix, iy in cells))


def _point_box_distance(points: np.ndarray, cells: np.ndarray) -> np.ndarray:
    """Distances ``(k, c)`` des points aux carrés des cellules."""
    px, py = points[:, 0][:, None], points[:, 1][:, None]
    x0, y0 = cells[:, 0][None, :].astype(float), cells[:, 1][None, :].astype(float)
    dx = np.maximum(np.maximum(x0 - px, px - (x0 + 1.0)), 0.0)
    dy = np.maximum(np.maximum(y0 - py, py - (y0 + 1.0)), 0.0)
    return np.hypot(dx, dy)


def _point_edge_distance(points: np.ndarray, polygon: np.ndarray) -> np.ndarray:
    a = polygon
    ab = np.concatenate((polygon[1:], polygon[:1])) - a
    ap = points[:, None, :] - a[None, :, :]
    length2 = np.maximum((ab * ab).sum(axis=1), 1e-300)
    t = np.clip((ap * ab[None]).sum(axis=2) / length2, 0.0, 1.0)
    return np.hypot(ap[..., 0] - t * ab[:, 0], ap[..., 1] - t * ab[:, 1])


def water_gap(outline, water: WaterMask | None, reach: float) -> float:
    """Écart bord à bord du polygone ``outline`` à l'eau la plus proche,
    parmi les cellules dont le carré est à ≤ ``reach`` de sa boîte
    englobante en x et en y (portée carrée) ; ``inf`` s'il n'y en a aucune, 0 si le polygone touche ou
    recouvre une cellule d'eau. Sans aire commune, deux polygones disjoints
    (ou qui se touchent) sont à la distance minimale atteinte en un sommet de
    l'un : sommets du polygone ↔ carrés, coins des carrés ↔ arêtes."""
    if water is None:
        return math.inf
    polygon = np.asarray(outline, dtype=float)
    cells = _cells(polygon, water, reach)
    if not len(cells):
        return math.inf
    if water_area(polygon, water) > AREA_NOISE:
        return 0.0
    corners = np.concatenate([cells + offset for offset in ((0, 0), (1, 0), (1, 1), (0, 1))])
    return float(min(_point_box_distance(polygon, cells).min(),
                     _point_edge_distance(corners.astype(float), polygon).min()))


def _centers_inside(cells: np.ndarray, polygon: np.ndarray) -> np.ndarray:
    """Masque ``(k,)`` des cellules dont le centre est intérieur au polygone
    (tracé de rayon vectorisé ; sert d'ORDRE d'examen dans ``_wet``, pas de
    critère : un centre sur le bord peut tomber d'un côté ou de l'autre)."""
    a, b = polygon, np.roll(polygon, -1, axis=0)
    px, py = cells[:, 0][:, None] + 0.5, cells[:, 1][:, None] + 0.5
    straddle = (a[:, 1] > py) != (b[:, 1] > py)
    dy = np.where(straddle, b[:, 1] - a[:, 1], 1.0)
    x_cross = (b[:, 0] - a[:, 0]) * (py - a[:, 1]) / dy + a[:, 0]
    return ((straddle & (px < x_cross)).sum(axis=1) % 2) == 1


def _wet(outline, water: WaterMask) -> bool:
    """``water_area(outline, water) > AREA_NOISE``, au bit près, avec rejet
    rapide EXACT : les aires par cellule sont ≥ 0 et une somme flottante de
    termes ≥ 0 n'est jamais inférieure à l'un d'eux, donc une seule cellule
    d'aire > ``AREA_NOISE`` suffit à conclure. Sont examinées d'abord les
    cellules d'eau qui contiennent un sommet du polygone (elles rencontrent
    sa boîte englobante, donc font partie des cellules de ``water_area``),
    puis celles dont le centre est dans le polygone ; sinon toutes, dans
    l'ordre de ``water_area``, puis la somme dans ce même ordre (cas de
    plusieurs miettes sous ``AREA_NOISE``)."""
    polygon = np.asarray(outline, dtype=float)
    points = [tuple(p) for p in polygon.tolist()]
    grid = water.water
    height, width = grid.shape
    tried = set()
    for x, y in points:
        ix, iy = math.floor(x), math.floor(y)
        if (ix, iy) in tried or not (0 <= ix < width and 0 <= iy < height):
            continue
        tried.add((ix, iy))
        if grid[iy, ix] and _clip_area(points, ix, iy) > AREA_NOISE:
            return True
    cells = _cells(polygon, water, 0.0)
    if not len(cells):
        return False
    areas: dict[int, float] = {}
    for k in np.flatnonzero(_centers_inside(cells, polygon)).tolist():
        areas[k] = _clip_area(points, int(cells[k, 0]), int(cells[k, 1]))
        if areas[k] > AREA_NOISE:
            return True
    for k in range(len(cells)):
        if k not in areas:
            areas[k] = _clip_area(points, int(cells[k, 0]), int(cells[k, 1]))
            if areas[k] > AREA_NOISE:
                return True
    return float(sum(areas[k] for k in range(len(cells)))) > AREA_NOISE


def is_dry(outline, water: WaterMask | None, margin: float) -> bool:
    """Le polygone ``outline`` est-il au sec à la marge ``margin`` (blocs,
    ≥ 0 ; règle en tête de module) ? À la marge 0 : ``water_area`` ≤
    ``AREA_NOISE``, calculé par ``_wet`` (rejet rapide exact)."""
    if water is None:
        return True
    if margin > 0.0:
        return water_gap(outline, water, margin) >= margin
    return not _wet(outline, water)


def water_overlap(outline, water: WaterMask | None) -> tuple[np.ndarray, np.ndarray]:
    """Cellules d'eau ``(k, 2)`` (colonnes ix, iy) qui partagent une aire
    > ``AREA_NOISE`` avec le polygone ``outline``, et ces aires ``(k,)``
    (blocs²), dans l'ordre de ``WaterMask.cells_near``."""
    empty = np.zeros((0, 2), dtype=np.int64), np.zeros(0)
    if water is None:
        return empty
    polygon = np.asarray(outline, dtype=float)
    cells = _cells(polygon, water, 0.0)
    if not len(cells):
        return empty
    points = [tuple(p) for p in polygon.tolist()]
    areas = np.array([_clip_area(points, int(ix), int(iy)) for ix, iy in cells])
    keep = areas > AREA_NOISE
    return cells[keep], areas[keep]


def raised_cells(outline, water: WaterMask | None) -> np.ndarray:
    """Cellules remontées ``(k, 2)`` d'un green insulaire de contour
    ``outline`` : cellules d'eau réelle qu'il recouvre (aire commune >
    ``AREA_NOISE``)."""
    return water_overlap(outline, water)[0]


def footprint_cells(outline, width: int, height: int) -> np.ndarray:
    """Cellules ``(k, 2)`` de la carte ``width × height`` qui partagent une
    aire > ``AREA_NOISE`` avec le polygone ``outline`` (eau ou non)."""
    everything = WaterMask(water=np.ones((int(height), int(width)), dtype=bool))
    return water_overlap(outline, everything)[0]


def _emerged(outline, relief: np.ndarray, water: WaterMask) -> tuple[np.ndarray, int]:
    """Cellules sèches ``(k, 2)`` recouvertes par ``outline`` (aire commune
    > ``AREA_NOISE``) et nombre de cellules d'eau recouvertes."""
    footprint = footprint_cells(outline, water.width, water.height)
    wet = water.water[footprint[:, 1], footprint[:, 0]]
    return footprint[~wet], int(wet.sum())


def island_of(outline, relief: np.ndarray, water: WaterMask) -> GreenIsland:
    """Remontée du green insulaire de contour ``outline`` sur le relief
    ``relief`` (indexé ``[y, x]``) d'eau ``water`` (``water_mask(relief)``) :
    altitude minimale de la partie émergée (cellules sèches que le contour
    recouvre, aire commune > ``AREA_NOISE``), aire remontée = nombre de
    cellules remontées (``raised_cells``, blocs²). Lève ``ValueError`` si le
    green ne recouvre aucune cellule sèche (impossible : le drapeau routé,
    intérieur au green, est au sec du routeur) ou aucune cellule d'eau."""
    emerged, wet = _emerged(outline, relief, water)
    if not len(emerged) or not wet:
        raise ValueError("green insulaire sans partie émergée ou sans eau")
    height = float(np.min(relief[emerged[:, 1], emerged[:, 0]]))
    return GreenIsland(height=height, raised_area=float(wet))


def tee_island_of(outline, relief: np.ndarray, water: WaterMask) -> TeeIsland:
    """Remontée de la boîte de départ de contour ``outline`` (même règle que
    ``island_of``) ; entièrement immergée (aucune cellule sèche recouverte),
    elle remonte à un bloc au-dessus de l'eau, ``WATER_LEVEL +
    SUBMERGED_TEE_LIFT``, ``submerged`` vrai. ``water`` : eau vue par
    la boîte (eau effective de son trou) ; lève ``ValueError`` si la boîte
    ne recouvre aucune cellule d'eau."""
    emerged, wet = _emerged(outline, relief, water)
    if not wet:
        raise ValueError("boîte remontée sans eau")
    if not len(emerged):
        return TeeIsland(height=float(WATER_LEVEL + SUBMERGED_TEE_LIFT), raised_area=float(wet), submerged=True)
    height = float(np.min(relief[emerged[:, 1], emerged[:, 0]]))
    return TeeIsland(height=height, raised_area=float(wet))


def raised_mask(water: WaterMask | None, features: Iterable) -> np.ndarray | None:
    """Masque ``(h, w)`` des cellules remontées par les éléments ``features``
    (greens et boîtes de départ : ``outline`` et ``island``, ``None`` au
    sec) : leurs cellules d'eau réelle recouvertes (``raised_cells``) ;
    ``None`` sans eau connue."""
    if water is None:
        return None
    grid = np.zeros_like(water.water)
    for feature in features:
        if feature.island is not None:
            cells = raised_cells(feature.outline, water)
            grid[cells[:, 1], cells[:, 0]] = True
    return grid


def effective_water(water: WaterMask | None, features: Iterable) -> WaterMask | None:
    """Eau EFFECTIVE d'un trou : eau réelle ``water`` moins les cellules
    remontées (``raised_cells``) de ses éléments ``features`` remontés
    (green insulaire ``GreenShape.island``, boîtes remontées
    ``TeeBox.island``) ; ``water`` lui-même s'il n'y en a aucun, ``None``
    sans eau connue. Seule source de l'eau vue en aval des greens.
    ``features`` : les éléments du SEUL trou concerné ; les cellules
    remontées par un autre trou restent de l'eau pour lui."""
    if water is None:
        return None
    grid = None
    for feature in features:
        if feature.island is None:
            continue
        cells = raised_cells(feature.outline, water)
        if grid is None:
            grid = np.array(water.water)
        grid[cells[:, 1], cells[:, 0]] = False
    return water if grid is None else WaterMask(water=grid)
