"""Utilitaires mathématiques et géométriques."""

from __future__ import annotations

import math

import numpy as np


def snap_to_tile(x: float, y: float, tile_size: int = 5) -> tuple[float, float]:
    """Aligne une position au centre de la tile la plus proche."""
    tx = int(x / tile_size)
    ty = int(y / tile_size)
    return (tx * tile_size + tile_size / 2, ty * tile_size + tile_size / 2)


def gradient_at(heightmap: np.ndarray, x: int, y: int) -> tuple[float, float]:
    """Calcule le gradient local (dz/dx, dz/dy) à une position donnée."""
    h, w = heightmap.shape
    x = max(1, min(w - 2, x))
    y = max(1, min(h - 2, y))

    dzdx = (float(heightmap[y, x + 1]) - float(heightmap[y, x - 1])) / 2.0
    dzdy = (float(heightmap[y + 1, x]) - float(heightmap[y - 1, x])) / 2.0
    return dzdx, dzdy


def slope_at(heightmap: np.ndarray, x: int, y: int) -> float:
    """Retourne la pente (magnitude du gradient) à une position."""
    dzdx, dzdy = gradient_at(heightmap, x, y)
    return math.sqrt(dzdx * dzdx + dzdy * dzdy)


def distance(p1: tuple[float, float], p2: tuple[float, float]) -> float:
    """Distance euclidienne entre deux points 2D."""
    return math.sqrt((p2[0] - p1[0]) ** 2 + (p2[1] - p1[1]) ** 2)


def angle_between(p1: tuple[float, float], p2: tuple[float, float]) -> float:
    """Angle en radians de p1 vers p2."""
    return math.atan2(p2[1] - p1[1], p2[0] - p1[0])


def point_on_circle(center: tuple[float, float], radius: float,
                     angle: float) -> tuple[float, float]:
    """Point sur un cercle à un angle donné."""
    return (center[0] + radius * math.cos(angle),
            center[1] + radius * math.sin(angle))


def point_to_segment_dist(px: float, py: float,
                           ax: float, ay: float,
                           bx: float, by: float) -> float:
    """Distance d'un point à un segment de droite."""
    dx = bx - ax
    dy = by - ay
    len2 = dx * dx + dy * dy
    if len2 < 1e-10:
        return math.sqrt((px - ax) ** 2 + (py - ay) ** 2)
    t = max(0, min(1, ((px - ax) * dx + (py - ay) * dy) / len2))
    proj_x = ax + t * dx
    proj_y = ay + t * dy
    return math.sqrt((px - proj_x) ** 2 + (py - proj_y) ** 2)


def polyline_length(points: list[tuple[float, float]]) -> float:
    """Longueur totale d'une polyligne."""
    total = 0.0
    for i in range(len(points) - 1):
        total += distance(points[i], points[i + 1])
    return total


def direction_label(tee: tuple[float, float],
                     green: tuple[float, float]) -> str:
    """Label de direction (N, NE, E, etc.) du tee vers le green."""
    dx = green[0] - tee[0]
    dy = -(green[1] - tee[1])  # Y inversé (haut = nord)
    angle = math.atan2(dy, dx) * 180 / math.pi
    dirs = ['E', 'NE', 'N', 'NO', 'O', 'SO', 'S', 'SE']
    idx = round(((angle + 360) % 360) / 45) % 8
    return dirs[idx]


def segments_intersect(a1: tuple, a2: tuple, b1: tuple, b2: tuple) -> bool:
    """True si les segments a1-a2 et b1-b2 se croisent (test CCW)."""
    def ccw(p, q, r):
        return (q[0] - p[0]) * (r[1] - p[1]) - (q[1] - p[1]) * (r[0] - p[0])

    d1 = ccw(b1, b2, a1)
    d2 = ccw(b1, b2, a2)
    d3 = ccw(a1, a2, b1)
    d4 = ccw(a1, a2, b2)

    if ((d1 > 0 and d2 < 0) or (d1 < 0 and d2 > 0)) and \
       ((d3 > 0 and d4 < 0) or (d3 < 0 and d4 > 0)):
        return True
    return False


def convex_hull_2d(points: list[tuple[float, float]]) -> list[tuple[float, float]]:
    """Enveloppe convexe 2D (Andrew's monotone chain). O(n log n)."""
    pts = sorted(set(points))
    if len(pts) <= 2:
        return pts

    def cross(o, a, b):
        return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])

    lower = []
    for p in pts:
        while len(lower) >= 2 and cross(lower[-2], lower[-1], p) <= 0:
            lower.pop()
        lower.append(p)

    upper = []
    for p in reversed(pts):
        while len(upper) >= 2 and cross(upper[-2], upper[-1], p) <= 0:
            upper.pop()
        upper.append(p)

    return lower[:-1] + upper[:-1]


def gaussian_kernel_2d(size: int, sigma: float) -> np.ndarray:
    """Crée un noyau gaussien 2D normalisé."""
    x = np.arange(size) - size // 2
    kernel_1d = np.exp(-0.5 * (x / sigma) ** 2)
    kernel_2d = np.outer(kernel_1d, kernel_1d)
    return kernel_2d / kernel_2d.sum()
