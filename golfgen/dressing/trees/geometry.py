"""Géométrie des arbres : axes, masques de cases, couronnes, interdits.

Portage des fonctions pures des études du lot 5, retirées au R7 (aucun
import de ``tools`` ici). Grilles ``(h, w)`` indexées ``[y, x]``, cases
``(ix, iy)``, en blocs.

Couronne de rayon ``r`` : cases dont le centre est à au plus ``r`` de la case
centrale (``CROWN_DISCS`` : tables précalculées pour ``CROWN_RADII`` ; tout
autre rayon, pour des abords réglables, est calculé à la demande). Corridor
d'un trou à la marge ``m`` : ``buffered_axis(axe, width / 2 + m)``, ``m = 5``
est la bande de jeu, ``m = 0`` le cœur.

Interdits (``ForbiddenMasks``) :

- ``base`` : obstacles (greens, boîtes, bunkers, parvis), eau effective et
  cases de chemin, sans abords : ce que lisent les couches stratégiques ;
- ``fixed`` : ``base`` et abords des greens et boîtes à ``APRON`` blocs : ce
  que lisent les ancrages, la lisière et le remplissage ;
- ``corridor``, ``core``, ``others`` : corridors à part, chaque couche les
  combine à sa façon. La marge réglable (``margin``) ne porte que sur
  ``corridor``, le corridor de la lisière et du remplissage ; ``others``, lu
  par les couches stratégiques, reste à ``CORRIDOR_MARGIN`` quelle que soit
  ``margin``.

Hors de la carte : interdit, par ``crown_fits`` (masque) et ``crown_on_map``
(une case) ; une couronne reste entière sur la carte.
"""

from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Any, Iterable, Mapping, Sequence

import numpy as np

from golfgen.dressing.paths.geometry import Point
from golfgen.dressing.paths.scene import Scene, obstacle_mask
from golfgen.dressing.trees.errors import TreeError
from golfgen.routing.geometry import buffered_axis

CROWN_RADII: tuple[int, ...] = (2, 3, 4)    # blocs : rayons des couronnes
CROWN_RADIUS = 3            # blocs : couronne des arbres stratégiques
APRON = 3                   # blocs autour des départs et greens
CORRIDOR_MARGIN = 5.0       # blocs au-delà du cœur : la bande de jeu
CORE_MARGIN = 0.0           # blocs : le cœur du trou

Tree = tuple[int, int, int]     # case x, case y, rayon


def _disc(radius: int) -> np.ndarray:
    """Décalages ``(k, 2)`` ``(dx, dy)`` du disque, en lecture seule, ligne
    par ligne (``dy`` puis ``dx`` croissants)."""
    offsets = np.asarray([(dx, dy) for dy in range(-radius, radius + 1)
                          for dx in range(-radius, radius + 1)
                          if dx * dx + dy * dy <= radius * radius], dtype=np.int64)
    offsets.setflags(write=False)
    return offsets


CROWN_DISCS: dict[int, np.ndarray] = {radius: _disc(radius) for radius in CROWN_RADII}


def _offsets(radius: int) -> np.ndarray:
    """Décalages du disque : la table pour les rayons de couronne, calculés
    à la demande pour tout autre rayon (abords réglables)."""
    return CROWN_DISCS[radius] if radius in CROWN_DISCS else _disc(radius)


# === Axes et polygones ===

def axis_of(hole: Mapping[str, Any]) -> tuple[Point, ...]:
    """Axe exporté du trou : départ, doglegs, green."""
    return tuple((p["x"], p["y"]) for p in [hole["tee"], *hole.get("doglegs", []), hole["green"]])


def polygon_mask(polygon, width: int, height: int) -> np.ndarray:
    """Cases (centres ``x + 0,5``, ``y + 0,5``) dans le polygone (pair-impair),
    grille hauteur × largeur."""
    poly = np.asarray(polygon, dtype=float)
    mask = np.zeros((height, width), dtype=bool)
    x0 = max(0, int(math.floor(poly[:, 0].min())))
    x1 = min(width, int(math.ceil(poly[:, 0].max())) + 1)
    y0 = max(0, int(math.floor(poly[:, 1].min())))
    y1 = min(height, int(math.ceil(poly[:, 1].max())) + 1)
    if x0 >= x1 or y0 >= y1:
        return mask
    xs, ys = np.meshgrid(np.arange(x0, x1) + 0.5, np.arange(y0, y1) + 0.5)
    inside = np.zeros(xs.shape, dtype=bool)
    for (ax, ay), (bx, by) in zip(poly, np.roll(poly, -1, axis=0)):
        crosses = (ay > ys) != (by > ys)
        with np.errstate(divide="ignore", invalid="ignore"):
            xi = ax + (ys - ay) * (bx - ax) / (by - ay)
        inside ^= crosses & (xs < xi)
    mask[y0:y1, x0:x1] = inside
    return mask


def corridor_polygon(hole: Mapping[str, Any], margin: float) -> tuple[Point, ...]:
    """Corridor du trou à la marge ``margin`` (blocs)."""
    return buffered_axis(axis_of(hole), hole["width"] / 2.0 + margin)


def corridors_mask(holes: Sequence[Mapping[str, Any]], margin: float, width: int, height: int) -> np.ndarray:
    """Union des corridors de ``holes`` à la marge ``margin``."""
    mask = np.zeros((height, width), dtype=bool)
    for hole in holes:
        mask |= polygon_mask(corridor_polygon(hole, margin), width, height)
    return mask


def other_corridors(holes: Sequence[Mapping[str, Any]], margin: float, width: int,
                    height: int) -> dict[int, np.ndarray]:
    """Par trou : union des corridors à la marge ``margin`` des AUTRES trous."""
    counts = np.zeros((height, width), dtype=np.int32)
    masks = {}
    for hole in holes:
        mask = polygon_mask(corridor_polygon(hole, margin), width, height)
        masks[hole["id"]] = mask
        counts += mask
    return {order: (counts - mask) > 0 for order, mask in masks.items()}


# === Couronnes ===

def dilate_disc(mask: np.ndarray, radius: int) -> np.ndarray:
    """``mask`` dilaté par le disque de ``radius`` (même forme)."""
    height, width = mask.shape
    out = np.zeros_like(mask, dtype=bool)
    for dx, dy in _offsets(radius).tolist():
        out[max(dy, 0):height + min(dy, 0), max(dx, 0):width + min(dx, 0)] |= \
            mask[max(-dy, 0):height + min(-dy, 0), max(-dx, 0):width + min(-dx, 0)]
    return out


def crown_fits(forbidden: np.ndarray, radius: int = CROWN_RADIUS) -> np.ndarray:
    """Cases où le centre d'un arbre est légal : aucune case de sa couronne
    n'est interdite ni hors de la carte."""
    padded = np.pad(forbidden, radius, constant_values=True)
    return ~dilate_disc(padded, radius)[radius:-radius, radius:-radius]


def crown_on_map(x: int, y: int, radius: int, width: int, height: int) -> bool:
    """La couronne de centre ``(x, y)`` tient-elle entière sur la carte ?"""
    return radius <= x < width - radius and radius <= y < height - radius


def crown_cells(cell: Sequence[int], radius: int = CROWN_RADIUS) -> np.ndarray:
    """Cases ``(k, 2)`` de la couronne de centre ``cell``."""
    return _offsets(radius) + np.asarray(cell, dtype=np.int64)


def crown_mask(trees: Iterable[Tree], width: int, height: int) -> np.ndarray:
    """Masque ``(h, w)`` des couronnes de ``trees`` ``(x, y, rayon)``, sur la
    carte."""
    mask = np.zeros((height, width), dtype=bool)
    for x, y, radius in trees:
        cells = crown_cells((x, y), radius)
        keep = ((cells[:, 0] >= 0) & (cells[:, 0] < width) & (cells[:, 1] >= 0) & (cells[:, 1] < height))
        mask[cells[keep, 1], cells[keep, 0]] = True
    return mask


# === Interdits ===

def kind_mask(scene: Scene, *kinds: str) -> np.ndarray:
    """``(h, w)`` : cases des obstacles de la scène des genres ``kinds``
    (``green``, ``tee``, ``bunker``, ``plaza``), sur la carte."""
    mask = np.zeros((scene.height, scene.width), dtype=bool)
    for obstacle in scene.obstacles:
        if obstacle.kind in kinds:
            cells = obstacle.cells
            keep = ((cells[:, 0] >= 0) & (cells[:, 0] < scene.width)
                    & (cells[:, 1] >= 0) & (cells[:, 1] < scene.height))
            mask[cells[keep, 1], cells[keep, 0]] = True
    return mask


def paths_mask(data: Mapping[str, Any], width: int, height: int) -> np.ndarray:
    """``(h, w)`` : cases exportées des chemins (``paths.cells``).
    ``TreeError`` si le JSON n'a pas de chemins : les arbres les exigent."""
    cells = (data.get("paths") or {}).get("cells")
    if cells is None:
        raise TreeError("JSON sans paths.cells : la pose des arbres exige les chemins")
    mask = np.zeros((height, width), dtype=bool)
    paths = np.asarray(cells, dtype=np.int64).reshape(-1, 2)
    mask[paths[:, 1], paths[:, 0]] = True
    return mask


def aprons_mask(scene: Scene, apron: int = APRON) -> np.ndarray:
    """``(h, w)`` : emprises des greens et départs dilatées de ``apron`` blocs."""
    return dilate_disc(kind_mask(scene, "green", "tee"), apron)


@dataclass(frozen=True, eq=False)
class ForbiddenMasks:
    """Interdits d'un parcours, grilles ``(h, w)`` (voir le docstring du
    module). ``obstacles`` réunit greens, boîtes, bunkers et parvis ;
    ``bunkers`` et ``plaza`` en sont des parties ; ``corridor`` : à la marge
    demandée (lisière et remplissage) ; ``others`` : par trou, les corridors
    des autres trous, toujours à ``CORRIDOR_MARGIN``."""
    water: np.ndarray
    obstacles: np.ndarray
    bunkers: np.ndarray
    plaza: np.ndarray
    paths: np.ndarray
    aprons: np.ndarray
    corridor: np.ndarray
    core: np.ndarray
    others: dict[int, np.ndarray]

    @property
    def base(self) -> np.ndarray:
        """Obstacles, eau effective et chemins."""
        return self.obstacles | self.water | self.paths

    @property
    def fixed(self) -> np.ndarray:
        """``base`` et abords des départs et greens."""
        return self.base | self.aprons


def forbidden_masks(data: Mapping[str, Any], scene: Scene,
                    margin: float = CORRIDOR_MARGIN) -> ForbiddenMasks:
    """Interdits d'un JSON 3.3 et de sa scène. ``margin`` ne règle que
    ``corridor`` (lisière et remplissage) : ``others`` reste à
    ``CORRIDOR_MARGIN`` et ``core`` à ``CORE_MARGIN``."""
    holes, width, height = data["routing"]["holes"], scene.width, scene.height
    return ForbiddenMasks(water=scene.water.copy(), obstacles=obstacle_mask(scene),
                          bunkers=kind_mask(scene, "bunker"), plaza=kind_mask(scene, "plaza"),
                          paths=paths_mask(data, width, height), aprons=aprons_mask(scene),
                          corridor=corridors_mask(holes, margin, width, height),
                          core=corridors_mask(holes, CORE_MARGIN, width, height),
                          others=other_corridors(holes, CORRIDOR_MARGIN, width, height))
