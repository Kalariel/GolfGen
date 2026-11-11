"""Repère local, cases de sable et topologie du raster (bunkers, round R1).

Un bunker est dessiné dans un repère LOCAL (``x`` le long de la tangente de
pose, ``y`` sur sa normale gauche), posé dans le monde par ``to_world``, puis
rastérisé en cases Minecraft : case ``(x, y)`` = carré ``[x, x + 1] × [y, y +
1]`` repéré par son coin bas-gauche entier (cases d'un haricot :
``beans.bean_cells``).
"""

from __future__ import annotations

import numpy as np

from golfgen.dressing.bunkers.errors import BunkerError

# Topologie exigée d'un bunker posé : un seul morceau de sable, aucune poche
# d'herbe fermée (``raster_topology``).
ONE_PIECE = {"sand_components": 1, "enclosed_grass_components": 0}


def to_local(points: np.ndarray, center, tangent) -> np.ndarray:
    """Points monde ``(k, 2)`` -> repère local (x le long de ``tangent``)."""
    tangent = np.asarray(tangent, dtype=float)
    normal = np.array((-tangent[1], tangent[0]))
    rel = np.asarray(points, dtype=float) - np.asarray(center, dtype=float)
    return np.column_stack((rel @ tangent, rel @ normal))


def to_world(local: np.ndarray, center, tangent) -> np.ndarray:
    """Contour local ``(k, 2)`` posé en ``center`` le long de ``tangent``."""
    tangent = np.asarray(tangent, dtype=float)
    normal = np.array((-tangent[1], tangent[0]))
    return np.asarray(center, dtype=float) + local[:, :1] * tangent + local[:, 1:] * normal


def components(cells) -> list[set[tuple[int, int]]]:
    """Composantes à quatre voisins : un contact diagonal ne suffit pas."""
    todo = {tuple(map(int, cell)) for cell in cells}
    result = []
    while todo:
        connected = {todo.pop()}
        queue = list(connected)
        while queue:
            x, y = queue.pop()
            for point in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)):
                if point in todo:
                    todo.remove(point)
                    connected.add(point)
                    queue.append(point)
        result.append(connected)
    return result


def raster_topology(cells: np.ndarray) -> dict:
    """Morceaux de sable et poches d'herbe fermées (4 voisins) des cases."""
    if not len(cells):
        return {"sand_components": 0, "enclosed_grass_components": 0}
    low, high = cells.min(axis=0) - 1, cells.max(axis=0) + 1
    sand = {tuple(c) for c in cells}
    grass = [(x, y) for x in range(low[0], high[0] + 1)
             for y in range(low[1], high[1] + 1) if (x, y) not in sand]
    outside = tuple(low)
    return {"sand_components": len(components(cells)),
            "enclosed_grass_components": sum(outside not in part for part in components(grass))}


def cell_gap(first: np.ndarray, second: np.ndarray) -> float:
    """Distance libre minimale entre carrés de sable (pas entre centres)."""
    delta = np.abs(first[:, None, :] - second[None, :, :])
    separation = np.maximum(delta - 1, 0)
    return float(np.linalg.norm(separation, axis=2).min())


def convex_hull(points: np.ndarray) -> np.ndarray:
    """Enveloppe convexe ``(h, 2)`` (sens trigonométrique, chaîne monotone)."""
    pts = sorted(set(map(tuple, np.asarray(points, dtype=float).tolist())))

    def chain(seq):
        out: list = []
        for p in seq:
            while len(out) >= 2 and ((out[-1][0] - out[-2][0]) * (p[1] - out[-2][1])
                                     - (out[-1][1] - out[-2][1]) * (p[0] - out[-2][0])) <= 0:
                out.pop()
            out.append(p)
        return out[:-1]

    return np.asarray(chain(pts) + chain(pts[::-1]), dtype=float)


def hull_depth(points: np.ndarray, hull: np.ndarray) -> np.ndarray:
    """Distance (blocs) de chaque point au bord de l'enveloppe ``hull``
    (minimum des distances signées aux arêtes, > 0 dedans). Lève
    ``BunkerError`` si l'enveloppe a moins de 3 sommets (pas d'intérieur)."""
    if len(hull) < 3:
        raise BunkerError(f"enveloppe convexe dégénérée ({len(hull)} sommet(s)) : "
                         "points confondus ou alignés")
    a, edge = hull, np.roll(hull, -1, axis=0) - hull
    rel = points[:, None, :] - a[None, :, :]
    cross = edge[None, :, 0] * rel[..., 1] - edge[None, :, 1] * rel[..., 0]
    return (cross / np.linalg.norm(edge, axis=1)[None, :]).min(axis=1)
