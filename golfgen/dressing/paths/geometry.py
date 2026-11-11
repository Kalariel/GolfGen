"""Géométrie des chemins : polygones, distances, échantillonnage.

Portage fidèle de l'étude (« Géométrie » et les aides de la conversion en
blocs dont dépend le tronc commun) : mêmes formules, même ordre des
opérations flottantes (la sortie en dépend). Repère : points ``(x, y)`` en blocs, ``y`` = ``z`` de Minecraft ;
case ``(ix, iy)`` = carré ``[ix, ix + 1] × [iy, iy + 1]``.
"""

from __future__ import annotations

import math
from typing import Any, Iterable, Mapping, Sequence

import numpy as np

Point = tuple[float, float]
Cell = tuple[int, int]

SAMPLE_STEP = 0.25       # pas d'échantillonnage des segments (blocs)
SUPERCOVER_STEP = 0.05   # pas d'échantillonnage des cases traversées (blocs)


def edges(poly: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Arêtes ``(a, b)`` du polygone fermé ``poly`` ; un point seul donne une
    arête dégénérée."""
    return poly, np.roll(poly, -1, axis=0)


def project(points: np.ndarray, a: np.ndarray, b: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Projetés ``(k, e, 2)`` des ``points`` sur les segments ``a[e]–b[e]``
    et distances ``(k, e)``."""
    ab = b - a
    denom = np.einsum("ij,ij->i", ab, ab)
    ap = points[:, None, :] - a[None, :, :]
    with np.errstate(divide="ignore", invalid="ignore"):
        t = np.where(denom > 0, np.einsum("kij,ij->ki", ap, ab) / denom, 0.0)
    t = np.clip(t, 0.0, 1.0)
    proj = a[None, :, :] + t[..., None] * ab[None, :, :]
    return proj, np.hypot(*(points[:, None, :] - proj).transpose(2, 0, 1))


def points_in_polygon(points: np.ndarray, poly: np.ndarray) -> np.ndarray:
    """``(k,)`` bool : points dans le polygone (pair-impair). Pas celui de
    ``golfgen.dressing.green`` : l'ordre de ses opérations flottantes diffère
    (la sortie en dépend), et un polygone de moins de 3 sommets ne
    contient rien."""
    inside = np.zeros(len(points), dtype=bool)
    if len(poly) < 3:
        return inside
    x, y = points[:, 0], points[:, 1]
    for (ax, ay), (bx, by) in zip(poly, np.roll(poly, -1, axis=0)):
        crosses = (ay > y) != (by > y)
        with np.errstate(divide="ignore", invalid="ignore"):
            xi = ax + (y - ay) * (bx - ax) / (by - ay)
        inside ^= crosses & (x < xi)
    return inside


def points_polygon_distance(points: np.ndarray, poly: np.ndarray) -> np.ndarray:
    """Distance ``(k,)`` des points au polygone plein (0 à l'intérieur)."""
    _, dist = project(points, *edges(poly))
    out = dist.min(axis=1)
    out[points_in_polygon(points, poly)] = 0.0
    return out


def points_cells_distance(points: np.ndarray, cells: np.ndarray) -> np.ndarray:
    """Distance ``(k,)`` des points à la plus proche des cases pleines
    ``cells`` (``(n, 2)`` ix, iy ; la case couvre ``[ix, ix+1] × [iy, iy+1]``)."""
    if not len(cells):
        return np.full(len(points), np.inf)
    centre = cells.astype(float) + 0.5
    dx = np.maximum(np.abs(points[:, None, 0] - centre[None, :, 0]) - 0.5, 0.0)
    dy = np.maximum(np.abs(points[:, None, 1] - centre[None, :, 1]) - 0.5, 0.0)
    return np.hypot(dx, dy).min(axis=1)


def closest_points(first: np.ndarray, second: np.ndarray) -> tuple[Point, Point]:
    """Points les plus proches entre les contours ``first`` et ``second``
    (polygones fermés, ou un point seul ``(1, 2)``)."""
    best = (math.inf, None, None)
    for src, dst, flip in ((first, second, False), (second, first, True)):
        proj, dist = project(src, *edges(dst))
        k, e = np.unravel_index(int(np.argmin(dist)), dist.shape)
        if dist[k, e] < best[0]:
            p, q = tuple(map(float, src[k])), tuple(map(float, proj[k, e]))
            best = (float(dist[k, e]), *((q, p) if flip else (p, q)))
    return best[1], best[2]


def sample_segment(start: Point, end: Point, step: float = SAMPLE_STEP) -> np.ndarray:
    """Points du segment ``start–end`` espacés d'au plus ``step`` (bouts
    compris, au moins deux)."""
    length = math.dist(start, end)
    n = max(2, int(math.ceil(length / step)) + 1)
    t = np.linspace(0.0, 1.0, n)[:, None]
    return np.asarray(start, dtype=float) * (1 - t) + np.asarray(end, dtype=float) * t


def polyline_length(points) -> float:
    """Longueur (blocs) de la ligne brisée."""
    pts = np.asarray(points, dtype=float)
    return float(np.hypot(*np.diff(pts, axis=0).T).sum()) if len(pts) > 1 else 0.0


def polyline_distance(cells: np.ndarray, points) -> tuple[np.ndarray, np.ndarray]:
    """Distance des centres de ``cells`` à la ligne brisée et abscisse
    curviligne de leur projeté."""
    pts = np.asarray(points, dtype=float).reshape(-1, 2)
    centre = cells.astype(float) + 0.5
    if len(pts) < 2:
        return np.hypot(*(centre - pts[0]).T), np.zeros(len(cells))
    a, b = pts[:-1], pts[1:]
    proj, dist = project(centre, a, b)
    e = np.argmin(dist, axis=1)
    k = np.arange(len(cells))
    seg = np.hypot(*(b - a).T)
    s0 = np.concatenate(([0.0], np.cumsum(seg)[:-1]))
    along = s0[e] + np.hypot(*(proj[k, e] - a[e]).T)
    return dist[k, e], along


def supercover(points: Iterable[Point], step: float = SUPERCOVER_STEP) -> list[Cell]:
    """Cases traversées par la ligne brisée, en 4-connexité (un passage par
    un coin ajoute la case ``(x2, z1)``)."""
    points = list(points)
    out: list[Cell] = []
    for a, b in zip(points[:-1], points[1:]):
        for x, y in sample_segment(a, b, step):
            c = (int(math.floor(x)), int(math.floor(y)))
            if out and c == out[-1]:
                continue
            if out and c[0] != out[-1][0] and c[1] != out[-1][1]:
                out.append((c[0], out[-1][1]))
            out.append(c)
    return out


def boxes_meet(a, b, pad: float) -> bool:
    """Boîtes ``(x0, y0, x1, y1)`` qui se touchent à ``pad`` près."""
    return not (a[2] + pad < b[0] or b[2] + pad < a[0] or a[3] + pad < b[1] or b[3] + pad < a[1])


def half_up(x: float) -> int:
    """Arrondi au plus proche, moitiés vers le haut."""
    return int(math.floor(x + 0.5))


def band_cells(points: Sequence[Point], width: float) -> np.ndarray:
    """Cases ``(k, 2)`` (x, z) du trait épais de largeur ``width`` sur la
    ligne brisée ``points``, avant tout découpage (voir le docstring du
    module de ``blocks``), triées par x puis z (``np.unique``)."""
    pts = np.asarray(points, dtype=float).reshape(-1, 2)
    hw = width / 2.0
    out = []
    for a, b in zip(pts[:-1], pts[1:]):
        d = b - a
        length = float(np.hypot(*d))
        if length == 0.0:
            continue
        major = 0 if abs(d[0]) >= abs(d[1]) else 1
        minor = 1 - major
        n = max(1, half_up(width * length / abs(d[major])))
        lo, hi = sorted((float(a[major]), float(b[major])))
        i = np.arange(math.ceil(lo - 0.5), math.floor(hi - 0.5) + 1)
        if not len(i):
            continue
        m = a[minor] + (i + 0.5 - a[major]) * d[minor] / d[major]
        j0 = np.ceil(m - n / 2.0 - 0.5 - 1e-9).astype(int)
        jj = (j0[:, None] + np.arange(n)[None, :]).ravel()
        ii = np.repeat(i, n)
        out.append(np.column_stack((ii, jj) if major == 0 else (jj, ii)))
    reach = int(math.ceil(hw)) + 1
    off = np.arange(-reach, reach + 1)
    ox, oy = np.meshgrid(off, off)
    if len(pts):                         # disque de chaque sommet (vectorisé : appel fréquent)
        cx = np.floor(pts[:, 0])[:, None, None] + ox
        cy = np.floor(pts[:, 1])[:, None, None] + oy
        near = np.hypot(cx + 0.5 - pts[:, 0, None, None],
                        cy + 0.5 - pts[:, 1, None, None]) < hw
        out.append(np.column_stack((cx[near], cy[near])).astype(int))
    if not out:
        return np.zeros((0, 2), dtype=int)
    return np.unique(np.concatenate(out).astype(int), axis=0)


def outline_polygon(outline: Iterable[Mapping[str, Any]]) -> np.ndarray:
    """Contour JSON ``[{"x", "y"}, ...]`` -> ``(k, 2)`` float."""
    return np.array([(p["x"], p["y"]) for p in outline], dtype=float)


def center_mask(poly: np.ndarray, width: int, height: int) -> np.ndarray:
    """``(height, width)`` : cases dont le centre est dans le polygone."""
    mask = np.zeros((height, width), dtype=bool)
    x0, y0 = (max(0, int(math.floor(v))) for v in poly.min(axis=0))
    x1 = min(width, int(math.ceil(poly[:, 0].max())) + 1)
    y1 = min(height, int(math.ceil(poly[:, 1].max())) + 1)
    if x0 >= x1 or y0 >= y1:
        return mask
    xs, ys = np.meshgrid(np.arange(x0, x1) + 0.5, np.arange(y0, y1) + 0.5)
    pts = np.column_stack((xs.ravel(), ys.ravel()))
    mask[y0:y1, x0:x1] = points_in_polygon(pts, poly).reshape(xs.shape)
    return mask
