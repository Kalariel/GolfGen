"""Forme du green d'un trou (habillage, lot 1).

Trois types (``GREEN_KINDS``) : rond, allongé, haricot, tirés par
``pick_kind`` (haricot réservé aux aires visées ≥ ``StyleSpec.bean_min_area``,
probabilités calées sur les parts nettes ``StyleSpec.kind_weights``). Base : ellipse orientée selon le dernier segment de l'axe
(l'approche), grand axe dans le sens du jeu, d'allongement tiré dans la plage
du type (``StyleSpec.kind_aspects``) et de petit axe ≥ ``GREEN_MIN_WIDTH``
blocs ; déformée par l'harmonique 3 (``GREEN_HARMONICS`` ; écart radial
relatif ≤ ``StyleSpec.harmonic_amplitude`` ; pas d'harmonique 2, qui
pourrait annuler l'allongement ou faire tourner l'axe) ; échantillonnée en
``GREEN_VERTICES`` sommets, aire ramenée à l'aire visée.

Haricot : ellipse de base peu allongée (l'encoche l'allonge), dont le rayon
est diminué de ``d·w(θ)`` du côté tiré, ``w`` fenêtre en cosinus surélevé
de demi-largeur ``NOTCH_HALF_WIDTH`` centrée sur le petit axe : creux en arc,
pas en V. ``d`` est calé (fausse position, quelques évaluations) pour que le
CREUX du contour (distance maximale d'un sommet à l'enveloppe convexe,
``hull_depth``), aire recalée, vaille le creux tiré dans
``StyleSpec.bean_depth``. Le COL (largeur du contour au droit du sommet le
plus creux, perpendiculaire à l'approche, ``neck_width``) doit rester
≥ ``BEAN_MIN_NECK`` : sinon le haricot devient un allongé (même tirage
d'allongement, ramené dans la plage des allongés), compté par
``GreenShape.bean_fallback``.

Taille (R1c) : ``ρ = ρlo + (ρhi − ρlo)·(LENGTH_WEIGHT·q + (1 − LENGTH_WEIGHT)·u)``
(``q`` : longueur normalisée du trou, ``u`` : tirage de l'aire), aire visée
``clamp(π/4·(ρ·l)², Amin, Amax)`` avec ``l`` = ``hole.width`` (largeur du
cœur) et les bornes du style (``StyleSpec.green_rho``, ``green_area``).

Centre : reculé depuis le drapeau vers l'approche de
``max(r, avant − l/2 + RECESS_MARGIN)``, ``r`` tiré dans
``[0, GREEN_RECESS_MAX]`` et ``avant`` l'étendue de la forme devant son
centre (demi-grand axe) : la forme ne déborde pas le bout du cœur.

Ordre des tirages, figé (déterminisme), sur le flux propre au trou : aire
(``u``), type, allongement, creux, côté, recul, amplitude, poids
(``len(GREEN_HARMONICS)``), phases (idem). Creux et côté sont tirés pour
tous les types (ignorés hors haricot) : le nombre de tirages ne dépend pas
du type.

Contrainte dure : le polygone reste dans le CŒUR du trou
(``build_hole_geometry(hole).core``, demi-largeur ``width/2``). Tant qu'il
n'y est pas, homothétie ×``SHRINK_FACTOR`` centrée sur le DRAPEAU : le
drapeau, intérieur au polygone de départ, le reste à chaque pas, et la forme
converge vers lui, à ``width/2`` au moins du bord du cœur. Les coordonnées
sont arrondies à 2 décimales AVANT le contrôle d'inclusion.
"""

from __future__ import annotations

import math
from typing import NamedTuple

import numpy as np

from golfgen.routing.model import PAR_SPECS, ElasticHole
from golfgen.dressing.model import GREEN_KINDS, DressingError, GreenShape, StyleSpec


GREEN_VERTICES = 32
GREEN_HARMONICS = (3,)
GREEN_MIN_WIDTH = 5.5           # blocs : petit axe minimal de l'ellipse de base
BEAN_MIN_NECK = 5.5             # blocs : col minimal du haricot (sinon allongé)
NOTCH_HALF_WIDTH = math.radians(90.0)   # demi-largeur de la fenêtre de l'encoche
NOTCH_MAX_FRACTION = 0.9        # d ≤ 0,9 × rayon au centre de l'encoche
NOTCH_TOLERANCE = 0.01          # blocs : précision du calage du creux
NOTCH_MAX_EVALUATIONS = 16
GREEN_RECESS_MAX = 1.5          # blocs : recul tiré max du centre vers l'approche
RECESS_MARGIN = 0.5             # blocs : marge du recul adaptatif
AMPLITUDE_FLOOR = 0.4           # amplitude tirée dans [floor, 1] × max du style
LENGTH_WEIGHT = 0.5             # part de la longueur du trou dans ρ
SHRINK_FACTOR = 0.95
SHRINK_MAX_STEPS = 200          # garde-fou : 0,95^200 ≈ 4e-5
EPSILON = 1e-9

LENGTH_RANGE = (min(spec.length_min for spec in PAR_SPECS.values()),
                max(spec.length_max for spec in PAR_SPECS.values()))
_THETA = 2.0 * math.pi * np.arange(GREEN_VERTICES) / GREEN_VERTICES


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



def _convex_hull(points: np.ndarray) -> np.ndarray:
    """Enveloppe convexe (chaîne monotone), sens trigonométrique."""
    pts = sorted(map(tuple, points.tolist()))

    def half(seq):
        out: list = []
        for q in seq:
            while len(out) >= 2 and ((out[-1][0] - out[-2][0]) * (q[1] - out[-2][1])
                                     - (out[-1][1] - out[-2][1]) * (q[0] - out[-2][0])) <= 0:
                out.pop()
            out.append(q)
        return out
    lower, upper = half(pts), half(pts[::-1])
    return np.asarray(lower[:-1] + upper[:-1], dtype=float)


def _vertex_depths(points: np.ndarray) -> np.ndarray:
    """Distance ``(k,)`` de chaque sommet au bord de l'enveloppe convexe du
    polygone (0 pour un sommet de l'enveloppe)."""
    hull = _convex_hull(points)
    a, b = hull, np.roll(hull, -1, axis=0)
    edge = b - a
    length = np.linalg.norm(edge, axis=1)
    inside = ((edge[:, 0] * (points[:, 1:2] - a[:, 1])
               - edge[:, 1] * (points[:, 0:1] - a[:, 0])) / length)
    return np.maximum(inside.min(axis=1), 0.0)


def hull_depth(points: np.ndarray) -> float:
    """Creux du contour : distance maximale d'un sommet au bord de l'enveloppe
    convexe (0 pour un polygone convexe)."""
    return float(_vertex_depths(points).max())


def chord_length(points: np.ndarray, origin: np.ndarray, direction: np.ndarray) -> float:
    """Longueur de la traversée du polygone ``points`` par la droite passant
    par ``origin`` de direction unitaire ``direction`` (écart entre les
    intersections extrêmes avec les arêtes)."""
    a = points - origin
    b = np.roll(a, -1, axis=0)
    da = direction[0] * a[:, 1] - direction[1] * a[:, 0]
    db = direction[0] * b[:, 1] - direction[1] * b[:, 0]
    crossing = (da <= 0.0) != (db <= 0.0)
    if not crossing.any():
        return 0.0
    s = da[crossing] / (da[crossing] - db[crossing])
    hits = a[crossing] + s[:, None] * (b[crossing] - a[crossing])
    t = hits @ direction
    return float(t.max() - t.min())


def neck_width(points: np.ndarray, tangent: np.ndarray) -> float:
    """Col : longueur de la traversée du contour, perpendiculaire à l'approche
    ``tangent``, au droit du sommet le plus creux (par rapport à l'enveloppe
    convexe)."""
    deepest = points[int(np.argmax(_vertex_depths(points)))]
    return chord_length(points, deepest, np.array((-tangent[1], tangent[0])))


def _contour(radius: np.ndarray, area: float) -> np.ndarray:
    """Contour polaire (``radius`` aux angles ``_THETA``) ramené à ``area``."""
    out = np.column_stack((radius * np.cos(_THETA), radius * np.sin(_THETA)))
    return out * math.sqrt(area / shoelace(out))


def _base_radius(aspect: float, coefficients: np.ndarray, phases: np.ndarray) -> np.ndarray:
    """Rayon de l'ellipse d'allongement ``aspect`` (grand axe sur x), déformée
    par les harmoniques."""
    radius = aspect / np.sqrt(np.cos(_THETA) ** 2 + (aspect * np.sin(_THETA)) ** 2)
    harmonics = np.asarray(GREEN_HARMONICS, dtype=float)[:, None]
    return radius * (1.0 + (coefficients[:, None]
                            * np.cos(harmonics * _THETA + phases[:, None])).sum(axis=0))


def _bean(radius: np.ndarray, side: float, depth: float, area: float) -> np.ndarray | None:
    """Haricot : encoche ``radius − d·w(θ)`` du côté ``side`` (+1 : y > 0),
    ``d`` calé par fausse position (Illinois) pour que ``hull_depth`` du
    contour ramené à ``area`` vaille ``depth`` à ``NOTCH_TOLERANCE`` près ;
    ``None`` si ce creux demande plus de ``NOTCH_MAX_FRACTION`` du rayon."""
    gap = np.angle(np.exp(1j * (_THETA - side * math.pi / 2.0)))
    window = np.where(np.abs(gap) < NOTCH_HALF_WIDTH,
                      0.5 * (1.0 + np.cos(math.pi * gap / NOTCH_HALF_WIDTH)), 0.0)

    def build(d: float) -> tuple[np.ndarray, float]:
        shape = _contour(radius - d * window, area)
        return shape, hull_depth(shape) - depth

    lo, hi = 0.0, NOTCH_MAX_FRACTION * float(radius[int(np.argmax(window))])
    shape, f_lo = build(lo)
    if f_lo >= 0.0:
        return shape
    shape, f_hi = build(hi)
    if f_hi < 0.0:
        return None
    kept = 0
    for _ in range(NOTCH_MAX_EVALUATIONS):
        d = (lo * f_hi - hi * f_lo) / (f_hi - f_lo)
        shape, f = build(d)
        if abs(f) <= NOTCH_TOLERANCE:
            break
        if f < 0.0:
            lo, f_lo = d, f
            if kept == -1:
                f_hi *= 0.5
            kept = -1
        else:
            hi, f_hi = d, f
            if kept == 1:
                f_lo *= 0.5
            kept = 1
    return shape


class _Draws(NamedTuple):
    """Tirages d'un green, dans l'ordre documenté en tête de module."""

    kind: float                 # U(0, 1) : type (``pick_kind``)
    position: float             # U(0, 1) : position de l'allongement dans la plage du type
    depth: float                # creux du haricot, U(``StyleSpec.bean_depth``)
    side: float                 # côté de l'encoche, ±1
    recess: float               # recul tiré, U(0, ``GREEN_RECESS_MAX``)
    coefficients: np.ndarray    # amplitudes des harmoniques
    phases: np.ndarray          # phases des harmoniques


def _draw(rng: np.random.Generator, spec: StyleSpec) -> _Draws:
    """Tirages après l'aire, en nombre constant quel que soit le type."""
    kind = rng.uniform()
    position = rng.uniform()
    depth = rng.uniform(*spec.bean_depth)
    side = 1.0 if rng.uniform() < 0.5 else -1.0
    recess = rng.uniform(0.0, GREEN_RECESS_MAX)
    amplitude = spec.harmonic_amplitude * rng.uniform(AMPLITUDE_FLOOR, 1.0)
    weights = rng.uniform(0.0, 1.0, size=len(GREEN_HARMONICS))
    phases = rng.uniform(0.0, 2.0 * math.pi, size=len(GREEN_HARMONICS))
    coefficients = amplitude * weights / max(float(weights.sum()), EPSILON)
    return _Draws(kind, position, depth, side, recess, coefficients, phases)


def bean_eligible(area: float, spec: StyleSpec) -> bool:
    """Un haricot exige un grand green : aire visée ≥ ``StyleSpec.bean_min_area``."""
    return area >= spec.bean_min_area


def pick_kind(u: float, area: float, spec: StyleSpec) -> str:
    """Type du green pour le tirage ``u`` ∈ [0, 1) et l'aire visée ``area``.

    Éligible (``bean_eligible``) : haricot si ``u < p`` (``p`` =
    ``StyleSpec.bean_given_eligible``, qui compense les bascules), sinon
    ``u`` est ramené sur [0, 1) et départage rond et allongé. Non éligible :
    rond ou allongé. Dans les deux cas, rond si le tirage ramené est
    ``< StyleSpec.round_given_plain`` (calé pour les parts NETTES
    ``StyleSpec.kind_weights``, bascules comprises)."""
    p = spec.bean_given_eligible if bean_eligible(area, spec) else 0.0
    if u < p:
        return "bean"
    s = (u - p) / (1.0 - p) if p < 1.0 else 0.0
    return "round" if s < spec.round_given_plain else "elongated"


def _aspect(kind: str, position: float, area: float, spec: StyleSpec) -> float:
    """Allongement de l'ellipse de base : position ``position`` dans la plage
    du type, plafonné pour un petit axe ≥ ``GREEN_MIN_WIDTH``
    (π·a·b = aire, a = allongement·b)."""
    lo, hi = spec.kind_aspects[GREEN_KINDS.index(kind)]
    return min(lo + (hi - lo) * position, area / (math.pi * (GREEN_MIN_WIDTH / 2.0) ** 2))


def _shape(kind: str, area: float, draws: _Draws,
           spec: StyleSpec) -> tuple[np.ndarray, str, bool]:
    """Contour local ``(GREEN_VERTICES, 2)`` d'aire ``area`` (axe x = sens du
    jeu, centre à l'origine) du type ``kind``, type final et bascule
    haricot → allongé (filet : col < ``BEAN_MIN_NECK`` ou creux impossible)."""
    def base(name: str) -> np.ndarray:
        return _base_radius(_aspect(name, draws.position, area, spec),
                            draws.coefficients, draws.phases)

    if kind == "bean":
        local = _bean(base(kind), draws.side, draws.depth, area)
        if local is not None and neck_width(local, np.array((1.0, 0.0))) >= BEAN_MIN_NECK:
            return local, kind, False
        return _contour(base("elongated"), area), "elongated", True
    return _contour(base(kind), area), kind, False


def target_area(hole: ElasticHole, u: float, spec: StyleSpec) -> float:
    """Aire visée : ``clamp(π/4·(ρ·l)², Amin, Amax)``, ``l`` = largeur du
    cœur, ``ρ`` dans la plage du style à la position mélangeant la longueur
    normalisée du trou (poids ``LENGTH_WEIGHT``) et le tirage ``u``."""
    rho_lo, rho_hi = spec.green_rho
    span = LENGTH_RANGE[1] - LENGTH_RANGE[0]
    q = min(max((hole.length - LENGTH_RANGE[0]) / span, 0.0), 1.0)
    rho = rho_lo + (rho_hi - rho_lo) * (LENGTH_WEIGHT * q + (1.0 - LENGTH_WEIGHT) * u)
    lo, hi = spec.green_area
    return min(max(math.pi / 4.0 * (rho * hole.width) ** 2, lo), hi)


def green_shape(hole: ElasticHole, core, rng: np.random.Generator,
                spec: StyleSpec) -> GreenShape:
    """Green du trou, inclus dans ``core`` (polygone du cœur) et contenant le
    drapeau (``hole.green``). Lève ``DressingError`` si l'invariant ne peut
    être tenu (impossible si le drapeau est intérieur au cœur), ou si le
    segment final de l'axe est de longueur nulle
    (``ElasticHole`` refuse deux points égaux, pas deux points si proches
    que la norme s'annule en flottant)."""
    axis = hole.axis
    flag = np.array((axis[-1].x, axis[-1].y))
    before = np.array((axis[-2].x, axis[-2].y))
    tangent = flag - before
    norm = np.linalg.norm(tangent)
    if not norm > 0.0 or not math.isfinite(norm):
        raise DressingError(f"trou {hole.order} : segment final nul, direction d'approche "
                            "indéfinie")
    tangent /= norm
    normal = np.array((-tangent[1], tangent[0]))

    area = target_area(hole, rng.uniform(), spec)
    draws = _draw(rng, spec)
    local, kind, fallback = _shape(pick_kind(draws.kind, area, spec), area, draws, spec)
    recess = max(draws.recess, float(local[:, 0].max()) - hole.width / 2.0 + RECESS_MARGIN)
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
            raise DressingError(f"trou {hole.order} : green impossible à inclure dans le cœur")
        scale *= SHRINK_FACTOR
    if not points_in_polygon(flag_point, outline)[0]:
        raise DressingError(f"trou {hole.order} : le green ne contient pas le drapeau")

    shown_center = np.round(flag + scale * (center - flag), 2)
    return GreenShape(
        outline=tuple((float(x), float(y)) for x, y in outline),
        center=(float(shown_center[0]), float(shown_center[1])),
        area=round(abs(shoelace(outline)), 2),
        target_area=round(area, 2),
        scale=scale,
        shrink_steps=steps,
        kind=kind,
        bean_fallback=fallback,
    )
