"""Forme du green d'un trou (habillage, lot 1).

Ellipse orientée selon le dernier segment de l'axe (l'approche), grand axe
dans le sens du jeu, déformée par les harmoniques 2 à 4 (écart radial relatif
≤ ``StyleSpec.harmonic_amplitude``), échantillonnée en ``GREEN_VERTICES``
sommets. Le centre est reculé de 0 à ``GREEN_RECESS_MAX`` bloc depuis le
drapeau vers l'approche. L'aire visée est tirée dans la plage du style,
modulée par la longueur du trou (donc par le par : plages de longueur
disjointes).

Contrainte dure : le polygone reste dans le CŒUR du trou
(``build_hole_geometry(hole).core``, demi-largeur ``width/2``). Tant qu'il
n'y est pas, homothétie ×``SHRINK_FACTOR`` centrée sur le DRAPEAU : le
drapeau, intérieur au polygone de départ, le reste à chaque pas, et la forme
converge vers lui, à ``width/2`` au moins du bord du cœur. Les coordonnées
sont arrondies à 2 décimales AVANT le contrôle d'inclusion.
"""

from __future__ import annotations

import math

import numpy as np

from golfgen.routing.model import PAR_SPECS, ElasticHole
from golfgen.dressing.model import GreenShape, StyleSpec


GREEN_VERTICES = 32
GREEN_HARMONICS = (2, 3, 4)
GREEN_RECESS_MAX = 1.5          # blocs : recul max du centre vers l'approche
GREEN_ASPECT = (1.0, 1.35)      # rapport grand axe (approche) / petit axe
AMPLITUDE_FLOOR = 0.4           # amplitude tirée dans [floor, 1] × max du style
LENGTH_WEIGHT = 0.5             # part de la longueur du trou dans l'aire visée
SHRINK_FACTOR = 0.95
SHRINK_MAX_STEPS = 200          # garde-fou : 0,95^200 ≈ 4e-5
EPSILON = 1e-9

LENGTH_RANGE = (min(spec.length_min for spec in PAR_SPECS.values()),
                max(spec.length_max for spec in PAR_SPECS.values()))


def shoelace(points: np.ndarray) -> float:
    """Aire signée d'un polygone ``(k, 2)`` (positive si sens trigonométrique
    dans le repère (x, y))."""
    x, y = points[:, 0], points[:, 1]
    return 0.5 * float(np.dot(x, np.roll(y, -1)) - np.dot(np.roll(x, -1), y))


def points_in_polygon(points: np.ndarray, polygon: np.ndarray) -> np.ndarray:
    """Masque booléen ``(k,)`` : points strictement intérieurs (tracé de rayon,
    vectorisé ; un point sur le bord peut tomber d'un côté ou de l'autre)."""
    a = polygon
    b = np.roll(polygon, -1, axis=0)
    px = points[:, 0][:, None]
    py = points[:, 1][:, None]
    straddle = (a[:, 1] > py) != (b[:, 1] > py)
    dy = np.where(straddle, b[:, 1] - a[:, 1], 1.0)
    x_cross = (b[:, 0] - a[:, 0]) * (py - a[:, 1]) / dy + a[:, 0]
    crossings = straddle & (px < x_cross)
    return (crossings.sum(axis=1) % 2) == 1


def _cross(a: np.ndarray, b: np.ndarray, c: np.ndarray) -> np.ndarray:
    return ((b[..., 0] - a[..., 0]) * (c[..., 1] - a[..., 1])
            - (b[..., 1] - a[..., 1]) * (c[..., 0] - a[..., 0]))


def edges_cross(first: np.ndarray, second: np.ndarray) -> bool:
    """Vrai si une arête de ``first`` coupe proprement une arête de ``second``
    (polygones fermés ``(k, 2)`` et ``(m, 2)``)."""
    a = first[:, None, :]
    b = np.roll(first, -1, axis=0)[:, None, :]
    c = second[None, :, :]
    d = np.roll(second, -1, axis=0)[None, :, :]
    c1, c2 = _cross(a, b, c), _cross(a, b, d)
    c3, c4 = _cross(c, d, a), _cross(c, d, b)
    split_cd = ((c1 > EPSILON) & (c2 < -EPSILON)) | ((c1 < -EPSILON) & (c2 > EPSILON))
    split_ab = ((c3 > EPSILON) & (c4 < -EPSILON)) | ((c3 < -EPSILON) & (c4 > EPSILON))
    return bool(np.any(split_cd & split_ab))


def polygon_inside(inner: np.ndarray, outer: np.ndarray) -> bool:
    """``inner`` ⊂ ``outer`` : tous les sommets intérieurs et aucune arête
    croisée (suffisant pour un cœur non convexe, à joints biseautés)."""
    return bool(points_in_polygon(inner, outer).all()) and not edges_cross(inner, outer)


def _unit_shape(rng: np.random.Generator, spec: StyleSpec) -> tuple[np.ndarray, float]:
    """Contour local ``(GREEN_VERTICES, 2)`` d'aire 1 (axe x = sens du jeu) et
    recul du centre. Ordre des tirages figé (déterminisme)."""
    aspect = rng.uniform(*GREEN_ASPECT)
    recess = rng.uniform(0.0, GREEN_RECESS_MAX)
    amplitude = spec.harmonic_amplitude * rng.uniform(AMPLITUDE_FLOOR, 1.0)
    weights = rng.uniform(0.0, 1.0, size=len(GREEN_HARMONICS))
    phases = rng.uniform(0.0, 2.0 * math.pi, size=len(GREEN_HARMONICS))
    coefficients = amplitude * weights / max(float(weights.sum()), EPSILON)

    theta = 2.0 * math.pi * np.arange(GREEN_VERTICES) / GREEN_VERTICES
    a, b = aspect, 1.0
    radius = a * b / np.sqrt((b * np.cos(theta)) ** 2 + (a * np.sin(theta)) ** 2)
    harmonics = np.asarray(GREEN_HARMONICS, dtype=float)[:, None]
    radius = radius * (1.0 + (coefficients[:, None]
                              * np.cos(harmonics * theta + phases[:, None])).sum(axis=0))
    local = np.column_stack((radius * np.cos(theta), radius * np.sin(theta)))
    return local / math.sqrt(shoelace(local)), recess


def target_area(hole: ElasticHole, u: float, spec: StyleSpec) -> float:
    """Aire visée : plage du style, position = mélange de la longueur
    normalisée du trou (poids ``LENGTH_WEIGHT``) et d'un tirage ``u``."""
    lo, hi = spec.green_area
    span = LENGTH_RANGE[1] - LENGTH_RANGE[0]
    q = min(max((hole.length - LENGTH_RANGE[0]) / span, 0.0), 1.0)
    return lo + (hi - lo) * (LENGTH_WEIGHT * q + (1.0 - LENGTH_WEIGHT) * u)


def green_shape(hole: ElasticHole, core, rng: np.random.Generator,
                spec: StyleSpec) -> GreenShape:
    """Green du trou, inclus dans ``core`` (polygone du cœur) et contenant le
    drapeau (``hole.green``). Lève ``RuntimeError`` si l'invariant ne peut
    être tenu (impossible si le drapeau est intérieur au cœur), et
    ``ValueError`` si le segment final de l'axe est de longueur nulle
    (``ElasticHole`` refuse deux points égaux, pas deux points si proches
    que la norme s'annule en flottant)."""
    axis = hole.axis
    flag = np.array((axis[-1].x, axis[-1].y))
    before = np.array((axis[-2].x, axis[-2].y))
    tangent = flag - before
    norm = np.linalg.norm(tangent)
    if not norm > 0.0 or not math.isfinite(norm):
        raise ValueError(f"trou {hole.order} : segment final nul, direction d'approche "
                         "indéfinie")
    tangent /= norm
    normal = np.array((-tangent[1], tangent[0]))

    area = target_area(hole, rng.uniform(), spec)
    local, recess = _unit_shape(rng, spec)
    local = local * math.sqrt(area)
    center = flag - recess * tangent
    world = center + local[:, :1] * tangent + local[:, 1:] * normal

    core_array = np.asarray(core, dtype=float)
    flag_point = flag[None, :]
    scale, steps = 1.0, 0
    while True:
        outline = np.round(flag + scale * (world - flag), 2)
        if polygon_inside(outline, core_array):
            break
        steps += 1
        if steps > SHRINK_MAX_STEPS:
            raise RuntimeError(f"trou {hole.order} : green impossible à inclure dans le cœur")
        scale *= SHRINK_FACTOR
    if not points_in_polygon(flag_point, outline)[0]:
        raise RuntimeError(f"trou {hole.order} : le green ne contient pas le drapeau")

    shown_center = np.round(flag + scale * (center - flag), 2)
    return GreenShape(
        outline=tuple((float(x), float(y)) for x, y in outline),
        center=(float(shown_center[0]), float(shown_center[1])),
        area=round(abs(shoelace(outline)), 2),
        target_area=round(area, 2),
        scale=scale,
        shrink_steps=steps,
    )
