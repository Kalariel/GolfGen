"""Forme du green d'un trou (habillage, lot 1).

Trois types (``GREEN_KINDS``) : rond, allongé, haricot, tirés par
``pick_kind`` (haricot réservé aux aires visées ≥ ``StyleSpec.bean_min_area``,
probabilités calées sur les parts nettes ``StyleSpec.kind_weights``).
Rond et allongé : ellipse orientée selon le dernier segment de l'axe
(l'approche), grand axe dans le sens du jeu, d'allongement tiré dans la plage
du type (``StyleSpec.kind_aspects``) et de petit axe ≥ ``GREEN_MIN_WIDTH``
blocs ; déformée par l'harmonique 3 (``GREEN_HARMONICS`` ; écart radial
relatif ≤ ``StyleSpec.harmonic_amplitude`` ; pas d'harmonique 2, qui
pourrait annuler l'allongement ou faire tourner l'axe) ; échantillonnée en
``GREEN_VERTICES`` sommets, aire ramenée à l'aire visée.

Haricot : capsule courbée (``_capsule``), stade de largeur ``w`` (bouts en
demi-cercles de rayon ``w/2``) dont l'axe médian est un arc de cercle de
longueur ``L`` et de flèche ``s`` ; la corde suit l'approche, le creux est
du côté tiré. ``λ = (L + w)/w`` (longueur dépliée sur largeur) est tiré dans
``StyleSpec.kind_aspects`` (plage du haricot), plafonné pour ``w ≥
BEAN_MIN_NECK`` ; ``w`` vient de l'aire visée par la formule fermée
``aire = w·L + π·w²/4`` : le col vaut ``w`` par construction. La flèche ``s``
est le creux tiré dans ``StyleSpec.bean_depth`` (ramené à
``BEAN_DEPTH_TOLERANCE`` des bornes) : sur le polygone, dont le dos, les
points de tangence de l'enveloppe sur les bouts et le fond du creux sont des
sommets, le CREUX (distance maximale d'un sommet à l'enveloppe convexe,
``hull_depth``) vaut exactement ``s``. Harmonique 3 au poids
``BEAN_HARMONIC_WEIGHT`` (× coefficients tirés ; à 1, elle refait des lobes),
en écart radial autour du centre, aire ramenée à l'aire visée ; elle déplace
le creux : s'il s'écarte de plus de ``BEAN_DEPTH_TOLERANCE`` du creux visé,
la flèche est recalée par sécante (``BEAN_MAX_EVALUATIONS`` évaluations au
plus, première comprise). Règle, sans tolérance : le haricot devient un
allongé (même tirage d'allongement, ramené dans la plage des allongés, placé
à son tour), compté par ``GreenShape.fallback_cause`` (``FALLBACK_CAUSES``),
si son creux visé est inatteignable (arc intérieur de rayon ``R − w/2`` ≤ 0
dès la première évaluation : ``creux_inatteignable``) ou si le recalage
échoue (``calage`` : pas de convergence, ou sécante qui pousse la flèche hors
du domaine de la capsule ; un bornage de la flèche pourrait le réduire), ou
si, une fois placé (contour final arrondi, réduit le cas échéant : règle plus
stricte que celle des tests, qui n'exigent le creux rastérisé que des
haricots non réduits), son COL (largeur du contour au droit du
sommet le plus creux, perpendiculaire à l'approche, ``neck_width``) est
< ``BEAN_MIN_NECK`` (``col``) ou son creux rastérisé (``raster_concavity``)
est < 1 bloc (``creux_raster``).

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

Eau (lot 1 eau, décision utilisateur) : ``dry_green_shape`` garde le green
hors de l'eau réelle du relief (``golfgen.dressing.water``), sans tirage
supplémentaire, selon le style (``StyleSpec.water_green``) : green décalé à
l'opposé de l'eau en links (``shifted_greens``, avec rotation puis paliers
d'aire de ``green_candidates`` si le décalage seul ne suffit pas), green
insulaire en parkland et en dernier recours links (``GreenShape.island``) ;
``green_shape`` est le green sans eau connue, inchangé.
"""

from __future__ import annotations

import dataclasses
import itertools
import math
from typing import NamedTuple

import numpy as np

from golfgen.routing.model import PAR_SPECS, ElasticHole
from golfgen.routing.sites import WaterMask
from golfgen.dressing.model import GREEN_KINDS, DressingError, GreenShape, StyleSpec, WaterFix
from golfgen.dressing.water import GREEN_WATER_MARGIN, is_dry, island_of, water_overlap


GREEN_VERTICES = 32
GREEN_HARMONICS = (3,)
GREEN_MIN_WIDTH = 5.5           # blocs : petit axe minimal de l'ellipse de base
BEAN_MIN_NECK = 5.5             # blocs : col minimal du haricot (sinon allongé)
BEAN_HARMONIC_WEIGHT = 0.5      # poids de l'harmonique 3 du haricot (× coefficients tirés)
BEAN_DEPTH_TOLERANCE = 0.01     # blocs : précision du recalage du creux
BEAN_MAX_EVALUATIONS = 4        # évaluations du creux au plus (sécante)
GREEN_RECESS_MAX = 1.5          # blocs : recul tiré max du centre vers l'approche
RECESS_MARGIN = 0.5             # blocs : marge du recul adaptatif
AMPLITUDE_FLOOR = 0.4           # amplitude tirée dans [floor, 1] × max du style
LENGTH_WEIGHT = 0.5             # part de la longueur du trou dans ρ
SHRINK_FACTOR = 0.95
SHRINK_MAX_STEPS = 200          # garde-fou : 0,95^200 ≈ 4e-5
EPSILON = 1e-9
# Causes de bascule haricot → allongé (``GreenShape.fallback_cause``), dans
# l'ordre où elles sont testées : palier d'aire du repli pour l'eau sous
# ``bean_min_area`` (``eau``, ``dry_green_shape``), construction de la
# capsule (``_bean``), puis haricot placé (``bean_defect``).
FALLBACK_CAUSES = ("eau", "creux_inatteignable", "calage", "col", "creux_raster")
# Repli pour l'eau (lot 1 eau, links, ``dry_green_shape``) : rotations
# essayées (degrés, dans l'ordre), paliers d'aire jusqu'au bas de la plage du
# style, tolérance d'axe (grand axe d'inertie ↔ approche) des allongés et des
# haricots, celle des tests depuis R1 (``tests/test_dressing_kinds.py``).
GREEN_AXIS_TOLERANCE = 15.0
GREEN_WATER_ROTATIONS = (5.0, -5.0, 10.0, -10.0, 15.0, -15.0)
GREEN_WATER_AREA_STEPS = 4
# Règle des 30 % (décision utilisateur, lot 1 eau) : une candidate du repli
# dont l'aire est inférieure à (1 − GREEN_WATER_MAX_REDUCTION) × l'aire de la
# forme tirée (avant le repli : seule la perte due à l'eau compte, pas la
# réduction au cœur) n'est pas retenue (ni telle quelle, ni décalée) ; si
# rien d'autre n'est au sec, le green devient insulaire en dernier recours.
GREEN_WATER_MAX_REDUCTION = 0.30
# Green décalé (lot 1 eau, style ``"shift"``, ``shifted_greens``) : drapeau
# routé à au moins ``GREEN_FLAG_EDGE`` blocs du bord (PROVISOIRE), pas et
# angles d'écart à la direction opposée à l'eau (degrés, dans l'ordre).
GREEN_FLAG_EDGE = 1.0
GREEN_SHIFT_STEP = 0.25
GREEN_SHIFT_ANGLES = (0.0, 15.0, -15.0, 30.0, -30.0, 45.0, -45.0, 60.0, -60.0)

LENGTH_RANGE = (min(spec.length_min for spec in PAR_SPECS.values()),
                max(spec.length_max for spec in PAR_SPECS.values()))
_THETA = 2.0 * math.pi * np.arange(GREEN_VERTICES) / GREEN_VERTICES


def _following(points: np.ndarray) -> np.ndarray:
    """Sommet suivant de chaque sommet (``np.roll(points, -1, axis=0)``, sans
    son surcoût sur de petits tableaux)."""
    return np.concatenate((points[1:], points[:1]))


def shoelace(points: np.ndarray) -> float:
    """Aire signée d'un polygone ``(k, 2)`` (positive si sens trigonométrique
    dans le repère (x, y))."""
    x, y = points[:, 0], points[:, 1]
    return 0.5 * float(np.dot(x, _following(y)) - np.dot(_following(x), y))


def points_in_polygon(points: np.ndarray, polygon: np.ndarray) -> np.ndarray:
    """Masque booléen ``(k,)`` : points strictement intérieurs (tracé de rayon,
    vectorisé ; un point sur le bord peut tomber d'un côté ou de l'autre)."""
    a = polygon
    b = _following(polygon)
    px = points[:, 0][:, None]
    py = points[:, 1][:, None]
    straddle = (a[:, 1] > py) != (b[:, 1] > py)
    dy = np.where(straddle, b[:, 1] - a[:, 1], 1.0)
    x_cross = (b[:, 0] - a[:, 0]) * (py - a[:, 1]) / dy + a[:, 0]
    crossings = straddle & (px < x_cross)
    return (crossings.sum(axis=1) % 2) == 1


def cross(a: np.ndarray, b: np.ndarray, c: np.ndarray) -> np.ndarray:
    """Produit vectoriel ``(b - a) × (c - a)`` (composante z), vectorisé sur
    les axes de tête ; son signe dit de quel côté de ``ab`` tombe ``c``."""
    return ((b[..., 0] - a[..., 0]) * (c[..., 1] - a[..., 1])
            - (b[..., 1] - a[..., 1]) * (c[..., 0] - a[..., 0]))


def edges_cross(first: np.ndarray, second: np.ndarray) -> bool:
    """Vrai si une arête de ``first`` coupe proprement une arête de ``second``
    (polygones fermés ``(k, 2)`` et ``(m, 2)``)."""
    a = first[:, None, :]
    b = _following(first)[:, None, :]
    c = second[None, :, :]
    d = _following(second)[None, :, :]
    c1, c2 = cross(a, b, c), cross(a, b, d)
    c3, c4 = cross(c, d, a), cross(c, d, b)
    split_cd = ((c1 > EPSILON) & (c2 < -EPSILON)) | ((c1 < -EPSILON) & (c2 > EPSILON))
    split_ab = ((c3 > EPSILON) & (c4 < -EPSILON)) | ((c3 < -EPSILON) & (c4 > EPSILON))
    return bool(np.any(split_cd & split_ab))


def polygon_inside(inner: np.ndarray, outer: np.ndarray) -> bool:
    """``inner`` ⊂ ``outer`` : tous les sommets intérieurs et aucune arête
    croisée (suffisant pour un cœur non convexe, à joints biseautés)."""
    return bool(points_in_polygon(inner, outer).all()) and not edges_cross(inner, outer)



def _convex_hull(points: np.ndarray) -> np.ndarray:
    """Enveloppe convexe (chaîne monotone), sens trigonométrique, sans
    doublons ni points alignés."""
    pts = sorted(set(map(tuple, points.tolist())))
    if len(pts) < 3:
        return np.asarray(pts, dtype=float)

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
    a, b = hull, _following(hull)
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
    b = _following(a)
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


def rasterize(outline) -> np.ndarray:
    """Cases ``(k, 2)`` (coin bas-gauche entier) du green rendu en blocs : une
    case est verte si son centre est dans le polygone (``points_in_polygon``)."""
    polygon = np.asarray(outline, dtype=float)
    lo = np.floor(polygon.min(axis=0)).astype(int)
    hi = np.ceil(polygon.max(axis=0)).astype(int)
    xs, ys = np.meshgrid(np.arange(lo[0], hi[0]), np.arange(lo[1], hi[1]), indexing="ij")
    cells = np.column_stack((xs.ravel(), ys.ravel()))
    return cells[points_in_polygon(cells + 0.5, polygon)]


def raster_concavity(cells: np.ndarray) -> float:
    """Creux rastérisé (blocs) : 1 + distance maximale au bord de l'enveloppe
    convexe des centres verts d'un centre de case NON verte situé dans cette
    enveloppe (bord compris) ; 0 si aucun (forme rastérisée « convexe » :
    aucune case manquante entre deux cases vertes). Une rangée de cases
    manquante entre deux cornes vaut 1."""
    if len(cells) < 3:
        return 0.0
    lo = cells.min(axis=0)
    green = np.zeros(tuple(cells.max(axis=0) - lo + 1), dtype=bool)
    green[cells[:, 0] - lo[0], cells[:, 1] - lo[1]] = True
    # enveloppe des seules cases extrêmes de chaque colonne (mêmes sommets)
    columns = np.flatnonzero(green.any(axis=1))
    first = green[columns].argmax(axis=1)
    last = green.shape[1] - 1 - green[columns, ::-1].argmax(axis=1)
    extremes = np.column_stack((np.concatenate((columns, columns)),
                                np.concatenate((first, last)))) + lo
    hull = _convex_hull(extremes.astype(float) + 0.5)
    if len(hull) < 3:
        return 0.0
    missing = (np.argwhere(~green) + lo).astype(float)
    if not len(missing):
        return 0.0
    centers = missing + 0.5
    a, b = hull, _following(hull)
    edge = b - a
    length = np.linalg.norm(edge, axis=1)
    # distance signée intérieure à chaque arête (enveloppe trigonométrique)
    inside = ((edge[:, 0] * (centers[:, 1:2] - a[:, 1]) - edge[:, 1] * (centers[:, 0:1] - a[:, 0]))
              / length)
    depth = inside.min(axis=1)
    depth = depth[depth >= -1e-9]
    return round(1.0 + float(depth.max()), 2) if len(depth) else 0.0


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


def _capsule_alpha(ratio: float) -> float | None:
    """Demi-angle ``α`` de l'arc médian de flèche ``s`` et de longueur ``L``
    (``ratio = s/L = (1 − cos α)/(2α)``), par Newton depuis ``α ≈ 4·ratio``
    (petits angles) ; ``None`` au-delà du maximum de ``(1 − cos α)/(2α)``
    (≈ 0,362 pour α ≈ 2,33 rad)."""
    if not 0.0 < ratio < 0.36:
        return None
    a = 4.0 * ratio
    for _ in range(40):
        f = (1.0 - math.cos(a)) / (2.0 * a) - ratio
        df = (a * math.sin(a) - (1.0 - math.cos(a))) / (2.0 * a * a)
        step = f / df
        a = min(max(a - step, 1e-6), 2.3)
        if abs(step) < 1e-12:
            return a
    return None


def _capsule(w: float, length: float, sagitta: float) -> np.ndarray | None:
    """Capsule courbée : stade de largeur ``w`` (bouts en demi-cercles de
    rayon w/2), arc médian de longueur ``length`` et de flèche ``sagitta``,
    corde sur x, creux du côté y < 0, centré sur le milieu de sa boîte
    (x = 0, y = s/2 au-dessus de la corde). ``GREEN_VERTICES`` sommets sur le
    bord exact, sens trigonométrique, par abscisse curviligne uniforme sur
    deux tronçons par moitié : sommet du dos → point de tangence de
    l'enveloppe sur le bout (point le plus bas du bout) → fond du creux ; ces
    trois points sont des sommets, donc le creux du polygone par rapport à
    son enveloppe vaut exactement ``sagitta`` (forme = arc ⊕ disque de rayon
    w/2, enveloppe = segment circulaire ⊕ disque : bord bas de l'enveloppe à
    w/2 sous la corde, fond du creux à s − w/2 au-dessus). ``None`` si l'arc
    intérieur (rayon R − w/2) n'existe pas."""
    alpha = _capsule_alpha(sagitta / length)
    if alpha is None:
        return None
    radius = length / (2.0 * alpha)
    h = w / 2.0
    if radius <= h:
        return None
    outer, cap = (radius + h) * alpha, math.pi * h
    first = outer + h * (math.pi - alpha)
    second = h * alpha + (radius - h) * alpha
    half = GREEN_VERTICES // 2
    n_first = min(max(round(half * first / (first + second)), 1), half - 1)
    t = np.concatenate((first * np.arange(n_first) / n_first,
                        first + second * np.arange(half - n_first + 1) / (half - n_first)))
    x = np.empty_like(t)
    y = np.empty_like(t)
    on_outer = t <= outer
    phi = t[on_outer] / (radius + h)
    x[on_outer] = (radius + h) * np.sin(phi)
    y[on_outer] = sagitta - radius + (radius + h) * np.cos(phi)
    on_cap = (~on_outer) & (t <= outer + cap)
    psi = alpha + (t[on_cap] - outer) / h
    x[on_cap] = radius * math.sin(alpha) + h * np.sin(psi)
    y[on_cap] = h * np.cos(psi)
    on_inner = t > outer + cap
    phi = alpha - (t[on_inner] - outer - cap) / (radius - h)
    x[on_inner] = (radius - h) * np.sin(phi)
    y[on_inner] = sagitta - radius + (radius - h) * np.cos(phi)
    right = np.column_stack((x, y - sagitta / 2.0))           # dos → fond du creux
    left = right[-2:0:-1] * np.array((-1.0, 1.0))
    return np.vstack((right, left))[::-1]                      # sens trigonométrique


def _bean(draws: "_Draws", length: float, area: float,
          depth_range: tuple[float, float]) -> tuple[np.ndarray | None, str | None]:
    """Haricot : capsule courbée (``_capsule``) d'allongement déplié
    ``length`` (λ), ``w`` depuis l'aire visée (``aire = w·L + π·w²/4``,
    ``L = (λ − 1)·w``), flèche = creux visé (``draws.depth`` ramené à
    ``BEAN_DEPTH_TOLERANCE`` des bornes de ``depth_range`` : creux final dans
    ``depth_range``), creux du côté ``draws.side`` (+1 : y > 0) ; harmonique 3
    au poids ``BEAN_HARMONIC_WEIGHT`` en écart radial autour du centre, puis
    aire ramenée à ``area``. Si le creux mesuré (``hull_depth``) s'écarte de
    plus de ``BEAN_DEPTH_TOLERANCE`` du creux visé, la flèche est recalée par
    sécante (pente 1 au premier pas : sans harmonique, creux = flèche).

    Renvoie ``(contour, None)``, ou ``(None, cause)`` si le haricot bascule :
    ``"creux_inatteignable"`` (arc intérieur inexistant pour la flèche visée,
    dès la première évaluation), ``"calage"`` (échec du recalage : pas de
    convergence en ``BEAN_MAX_EVALUATIONS`` évaluations, ou sécante qui pousse
    la flèche hors du domaine de la capsule)."""
    target = min(max(draws.depth, depth_range[0] + BEAN_DEPTH_TOLERANCE),
                 depth_range[1] - BEAN_DEPTH_TOLERANCE)
    w = math.sqrt(area / (length - 1.0 + math.pi / 4.0))
    harmonics = np.asarray(GREEN_HARMONICS, dtype=float)[:, None]
    coefficients = BEAN_HARMONIC_WEIGHT * draws.coefficients

    def build(sagitta: float) -> tuple[np.ndarray | None, float]:
        base = _capsule(w, (length - 1.0) * w, sagitta)
        if base is None:
            return None, 0.0
        if draws.side > 0.0:                                   # creux côté y > 0
            base = (base * np.array((1.0, -1.0)))[::-1]
        theta = np.arctan2(base[:, 1], base[:, 0])
        factor = 1.0 + (coefficients[:, None]
                        * np.cos(harmonics * theta + draws.phases[:, None])).sum(axis=0)
        shape = base * factor[:, None]
        shape = shape * math.sqrt(area / shoelace(shape))
        return shape, hull_depth(shape) - target

    previous = None
    sagitta = target
    for _ in range(BEAN_MAX_EVALUATIONS):
        shape, f = build(sagitta)
        if shape is None:                   # hors domaine : visé ou recalé
            return None, "creux_inatteignable" if previous is None else "calage"
        if abs(f) <= BEAN_DEPTH_TOLERANCE:
            return shape, None
        slope = 1.0
        if previous is not None:
            if f == previous[1]:
                break
            slope = (f - previous[1]) / (sagitta - previous[0])
        previous = (sagitta, f)
        sagitta -= f / slope
        if not sagitta > 0.0:
            break
    return None, "calage"


def bean_defect(outline: np.ndarray, tangent: np.ndarray) -> str | None:
    """Défaut du haricot placé (contour final ``outline``, approche
    ``tangent``) qui le fait basculer : ``"col"`` si ``neck_width`` <
    ``BEAN_MIN_NECK``, ``"creux_raster"`` si le creux rastérisé
    (``raster_concavity``) est < 1 bloc ; ``None`` sinon."""
    if neck_width(outline, tangent) < BEAN_MIN_NECK:
        return "col"
    if raster_concavity(rasterize(outline)) < 1.0:
        return "creux_raster"
    return None


class _Draws(NamedTuple):
    """Tirages d'un green, dans l'ordre documenté en tête de module."""

    kind: float                 # U(0, 1) : type (``pick_kind``)
    position: float             # U(0, 1) : position de l'allongement dans la plage du type
    depth: float                # creux du haricot, U(``StyleSpec.bean_depth``)
    side: float                 # côté du creux du haricot, ±1
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
    """Allongement tiré : position ``position`` dans la plage du type
    (``StyleSpec.kind_aspects``). Rond, allongé : allongement de l'ellipse de
    base, plafonné pour un petit axe ≥ ``GREEN_MIN_WIDTH`` (π·a·b = aire,
    a = allongement·b). Haricot : λ de la capsule (longueur dépliée sur
    largeur), plafonné pour ``w ≥ BEAN_MIN_NECK`` (aire = w²·(λ − 1 + π/4))."""
    lo, hi = spec.kind_aspects[GREEN_KINDS.index(kind)]
    if kind == "bean":
        cap = area / BEAN_MIN_NECK ** 2 + 1.0 - math.pi / 4.0
    else:
        cap = area / (math.pi * (GREEN_MIN_WIDTH / 2.0) ** 2)
    return min(lo + (hi - lo) * position, cap)


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


def inertia(outline) -> tuple[float, np.ndarray]:
    """Allongement mesuré (√(λ₁/λ₂) des moments d'inertie du polygone, = a/b
    pour une ellipse) et direction unitaire du grand axe d'inertie."""
    p = np.asarray(outline, dtype=float)
    p = p - p.mean(axis=0)
    x, y = p[:, 0], p[:, 1]
    x1, y1 = np.roll(x, -1), np.roll(y, -1)
    cross = x * y1 - x1 * y
    area = cross.sum() / 2.0
    cx = ((x + x1) * cross).sum() / (6.0 * area)
    cy = ((y + y1) * cross).sum() / (6.0 * area)
    sxx = (cross * (x * x + x * x1 + x1 * x1)).sum() / (12.0 * area) - cx * cx
    syy = (cross * (y * y + y * y1 + y1 * y1)).sum() / (12.0 * area) - cy * cy
    sxy = (cross * (2 * x * y + x * y1 + x1 * y + 2 * x1 * y1)).sum() / (24.0 * area) - cx * cy
    values, vectors = np.linalg.eigh(np.array([[sxx, sxy], [sxy, syy]]))
    return float(math.sqrt(values[1] / values[0])), vectors[:, 1]


def axis_deviation(outline, tangent: np.ndarray) -> float:
    """Angle (degrés, 0–90) entre le grand axe d'inertie et l'approche."""
    _, major = inertia(outline)
    return math.degrees(math.acos(min(1.0, abs(float(np.dot(major, tangent))))))


def water_area_steps(area: float, spec: StyleSpec) -> tuple[float, ...]:
    """Paliers d'aire visée du repli pour l'eau (``dry_green_shape``) :
    ``GREEN_WATER_AREA_STEPS`` paliers réguliers de ``area`` (exclue) au bas
    de la plage du style (``StyleSpec.green_area[0]``, inclus) ; aucun si
    l'aire visée y est déjà."""
    floor = spec.green_area[0]
    if not area > floor:
        return ()
    n = GREEN_WATER_AREA_STEPS
    return tuple(area + (floor - area) * k / n for k in range(1, n + 1))


def green_shape(hole: ElasticHole, core, rng: np.random.Generator,
                spec: StyleSpec) -> GreenShape:
    """Green du trou sans eau connue (``dry_green_shape`` sans masque)."""
    return dry_green_shape(hole, core, rng, spec, None)[0]


def green_candidates(hole: ElasticHole, core, rng: np.random.Generator, spec: StyleSpec):
    """``(forme tirée, candidates)`` : green tiré du trou, inclus dans
    ``core`` (polygone du cœur) et contenant le drapeau (``hole.green``), et
    itérateur paresseux des formes de repli pour l'eau ``(GreenShape,
    WaterFix)`` dans l'ordre de la règle (``dry_green_shape`` retient la
    première au sec). Lève ``DressingError`` si l'invariant ne peut être
    tenu pour la forme tirée (impossible si le drapeau est intérieur au
    cœur), ou si le segment final de l'axe est de longueur nulle
    (``ElasticHole`` refuse deux points égaux, pas deux points si proches
    que la norme s'annule en flottant) ; une candidate qui ne le tient pas
    est sautée.

    Repli pour l'eau (lot 1 eau, links, chaque candidate essayée telle
    quelle puis décalée par ``dry_green_shape``), déterministe, SANS tirage
    supplémentaire (mêmes tirages, déjà faits) : la forme tirée qui déborde
    est d'abord tournée autour de son centre (``GREEN_WATER_ROTATIONS``,
    dans la tolérance d'axe ``GREEN_AXIS_TOLERANCE`` : un allongé ou un
    haricot dont le grand axe d'inertie s'écarterait de plus de 15° de
    l'approche est écarté), puis reconstruite à des aires visées
    décroissantes (``water_area_steps``, jusqu'au bas de la plage du style),
    chaque palier essayé sans rotation puis avec les mêmes rotations ; la
    première forme au sec est retenue. Cascade des types : le type tiré est
    gardé (pas de nouveau ``pick_kind`` : rond et allongé ne s'échangent
    jamais) ; un haricot dont le palier passe sous ``bean_min_area`` devient
    allongé (cause ``"eau"``), et un haricot reconstruit qui bascule
    (``_bean``, ``bean_defect``) devient allongé avec sa cause, comme hors
    eau. Aucune forme tronquée : si rien n'est au sec, le green tiré devient
    insulaire (``dry_green_shape``)."""
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
    core_array = np.asarray(core, dtype=float)
    drawn_kind = pick_kind(draws.kind, area, spec)

    def build(target: float, angle: float) -> GreenShape:
        """Green d'aire visée ``target``, forme tournée de ``angle`` degrés
        autour de son centre (0 : forme tirée, au bit près)."""

        def base(name: str) -> np.ndarray:
            return _base_radius(_aspect(name, draws.position, target, spec),
                                draws.coefficients, draws.phases)

        def place(local: np.ndarray) -> tuple[np.ndarray, np.ndarray, float, int]:
            if angle != 0.0:
                c, s = math.cos(math.radians(angle)), math.sin(math.radians(angle))
                local = local @ np.array(((c, s), (-s, c)))
            recess = max(draws.recess, float(local[:, 0].max()) - hole.width / 2.0
                         + RECESS_MARGIN)
            center = flag - recess * tangent
            world = center + local[:, :1] * tangent + local[:, 1:] * normal
            scale, steps = 1.0, 0
            while True:
                outline = np.round(flag + scale * (world - flag), 2)
                if polygon_inside(outline, core_array):
                    break
                steps += 1
                if steps > SHRINK_MAX_STEPS:
                    raise DressingError(f"trou {hole.order} : green impossible à inclure "
                                        "dans le cœur")
                scale *= SHRINK_FACTOR
            if not points_in_polygon(flag[None, :], outline)[0]:
                raise DressingError(f"trou {hole.order} : le green ne contient pas le drapeau")
            return outline, np.round(flag + scale * (center - flag), 2), scale, steps

        kind, cause = drawn_kind, None
        if kind == "bean" and not bean_eligible(target, spec):
            kind, cause = "elongated", "eau"
        if kind == "bean":
            local, cause = _bean(draws, _aspect(kind, draws.position, target, spec), target,
                                 spec.bean_depth)
            if cause is None:
                outline, shown_center, scale, steps = place(local)
                cause = bean_defect(outline, tangent)
            if cause is not None:
                kind = "elongated"
        if kind != "bean":
            outline, shown_center, scale, steps = place(_contour(base(kind), target))

        return GreenShape(
            outline=tuple((float(x), float(y)) for x, y in outline),
            center=(float(shown_center[0]), float(shown_center[1])),
            area=round(abs(shoelace(outline)), 2),
            target_area=round(target, 2),
            scale=scale,
            shrink_steps=steps,
            kind=kind,
            fallback_cause=cause,
        )

    def candidates():
        for step, target in enumerate((area,) + water_area_steps(area, spec)):
            for angle in ((0.0,) if step else ()) + GREEN_WATER_ROTATIONS:
                try:
                    shape = build(target, angle)
                except DressingError:
                    continue
                if (shape.kind != "round"
                        and axis_deviation(shape.outline, tangent) > GREEN_AXIS_TOLERANCE):
                    continue
                yield shape, WaterFix(
                    green_rotation=angle, green_steps=step, green_target=round(area, 2),
                    green_kind=drawn_kind if shape.kind != drawn_kind else None)

    return build(area, 0.0), candidates()


def flag_edge_distance(outline, flag) -> float:
    """Distance (blocs) du drapeau ``flag`` au bord du polygone ``outline``
    (``-inf`` s'il n'y est pas strictement intérieur)."""
    polygon = np.asarray(outline, dtype=float)
    point = np.asarray(flag, dtype=float)
    if not points_in_polygon(point[None, :], polygon)[0]:
        return -math.inf
    a, b = polygon, _following(polygon)
    ab, ap = b - a, point - a
    t = np.clip((ap * ab).sum(axis=1) / np.maximum((ab * ab).sum(axis=1), 1e-300), 0.0, 1.0)
    return float(np.hypot(ap[:, 0] - t * ab[:, 0], ap[:, 1] - t * ab[:, 1]).min())


def _centroid(points: np.ndarray) -> np.ndarray:
    """Centre de gravité de l'aire du polygone ``points``."""
    x, y = points[:, 0], points[:, 1]
    x1, y1 = _following(x), _following(y)
    c = x * y1 - x1 * y
    return np.array(((x + x1) @ c, (y + y1) @ c)) / (3.0 * c.sum())


def shifted_greens(drawn: GreenShape, hole: ElasticHole, core, water: WaterMask | None):
    """Greens décalés (lot 1 eau, style ``"shift"``) : translations de
    ``drawn`` (forme, taille et type gardés), à l'opposé de l'eau qu'il
    recouvre, dans l'ordre de la règle, ``(GreenShape, (dx, dy))``.

    Direction de base ``u`` : du centre de gravité de la partie mouillée
    (centres des cellules d'eau recouvertes pondérés par l'aire commune,
    ``water_overlap``) vers celui du green ; tournée de
    ``GREEN_SHIFT_ANGLES`` (dans cet ordre) si le cœur ou le drapeau
    l'exigent. Pas de ``GREEN_SHIFT_STEP`` blocs, du plus court au plus
    long (à longueur égale, dans l'ordre des angles), jusqu'à l'étendue du
    green autour du drapeau. Une candidate (sommets arrondis à 2 décimales)
    est retenue si elle reste dans le cœur, contient le drapeau routé à au
    moins ``GREEN_FLAG_EDGE`` du bord, au sec à ``GREEN_WATER_MARGIN``
    (contrôle examiné en premier, le plus sélectif) et, pour un haricot,
    sans défaut (``bean_defect``)."""
    outline = np.asarray(drawn.outline, dtype=float)
    axis = hole.axis
    flag = np.array((axis[-1].x, axis[-1].y))
    tangent = flag - np.array((axis[-2].x, axis[-2].y))
    tangent /= np.linalg.norm(tangent)
    cells, areas = water_overlap(outline, water)
    if not len(cells):
        return
    wet = (cells + 0.5).T @ areas / areas.sum()
    away = _centroid(outline) - wet
    norm = float(np.linalg.norm(away))
    away = away / norm if norm > EPSILON else -tangent
    core_array = np.asarray(core, dtype=float)
    reach = float(np.linalg.norm(outline - flag, axis=1).max())
    center = np.asarray(drawn.center, dtype=float)
    for k in range(1, int(reach / GREEN_SHIFT_STEP) + 1):
        length = k * GREEN_SHIFT_STEP
        for angle in GREEN_SHIFT_ANGLES:
            c, s_ = math.cos(math.radians(angle)), math.sin(math.radians(angle))
            shift = length * np.array((c * away[0] - s_ * away[1], s_ * away[0] + c * away[1]))
            moved = np.round(outline + shift, 2)
            # eau d'abord : contrôle le plus sélectif (rejet rapide exact de
            # ``is_dry``) ; conjonction de prédicats purs, ordre sans effet
            # sur le résultat
            if not is_dry(moved, water, GREEN_WATER_MARGIN):
                continue
            if flag_edge_distance(moved, flag) < GREEN_FLAG_EDGE:
                continue
            if not polygon_inside(moved, core_array):
                continue
            if drawn.kind == "bean" and bean_defect(moved, tangent) is not None:
                continue
            shown = np.round(center + shift, 2)
            yield GreenShape(
                outline=tuple((float(x), float(y)) for x, y in moved),
                center=(float(shown[0]), float(shown[1])),
                area=round(abs(shoelace(moved)), 2),
                target_area=drawn.target_area, scale=drawn.scale,
                shrink_steps=drawn.shrink_steps, kind=drawn.kind,
                fallback_cause=drawn.fallback_cause), (round(float(shift[0]), 4),
                                                       round(float(shift[1]), 4))


def dry_green_shape(hole: ElasticHole, core, rng: np.random.Generator, spec: StyleSpec,
                    water: WaterMask | None, relief: np.ndarray | None = None
                    ) -> tuple[GreenShape, WaterFix | None]:
    """Green du trou, inclus dans ``core`` (polygone du cœur) et contenant le
    drapeau (``hole.green``), au sec de l'eau RÉELLE ``water``
    (``golfgen.dressing.water`` ; ``None`` : pas d'eau connue) à
    ``GREEN_WATER_MARGIN``, ou insulaire ; et repli appliqué (``WaterFix``,
    ``None`` si la forme tirée est au sec, renvoyée telle quelle).

    Repli (lot 1 eau, décision utilisateur), déterministe, SANS tirage
    supplémentaire, selon ``spec.water_green`` :

    - ``"island"`` (parkland) : forme tirée inchangée (ni rotation, ni
      réduction, ni décalage), rendue insulaire (``GreenShape.island``,
      ``golfgen.dressing.water.island_of`` sur ``relief``) ;
    - ``"shift"`` (links) : forme tirée décalée à l'opposé de l'eau
      (``shifted_greens`` : même forme, même taille), première candidate au
      sec ; à défaut, chaque candidate de rotation puis de palier d'aire de
      ``green_candidates``, dans leur ordre, telle quelle puis décalée ; en
      dernier recours, insulaire comme en parkland
      (``WaterFix.green_island_fallback``). Toute candidate retenue, telle
      quelle ou décalée, contient le drapeau routé à au moins
      ``GREEN_FLAG_EDGE`` du bord ; une candidate (forme tirée comprise)
      d'aire inférieure à ``(1 − GREEN_WATER_MAX_REDUCTION)`` × l'aire de la
      forme tirée (avant le repli : seule la perte due à l'eau compte) n'est
      pas retenue, ni telle quelle ni décalée (règle des 30 %, le décalage
      garde l'aire). Rotation et paliers sont gardés
      parce que le décalage seul ne suffit pas : sur le relevé du lot 1
      eau (120 parcours), 9 greens links
      mouillés sur 23 ne se décalent pas au sec ; tournés ou réduits puis
      décalés, 7 de ces 9 le sont, 2 restent insulaires (4 avec la rotation
      seule, sans réduction).

    ``relief`` (indexé ``[y, x]``, ``water`` = ``water_mask(relief)``) n'est
    lu que pour un green insulaire : ``ValueError`` s'il manque alors. Lève
    ``DressingError`` comme ``green_candidates``."""
    drawn, candidates = green_candidates(hole, core, rng, spec)
    if is_dry(drawn.outline, water, GREEN_WATER_MARGIN):
        return drawn, None
    fallback = False
    if spec.water_green == "shift":
        touched = WaterFix(green_target=drawn.target_area)
        flag = (hole.axis[-1].x, hole.axis[-1].y)
        smallest = (1.0 - GREEN_WATER_MAX_REDUCTION) * drawn.area
        for base, fix in itertools.chain(((drawn, touched),), candidates):
            if base.area < smallest:
                continue
            if (base is not drawn and is_dry(base.outline, water, GREEN_WATER_MARGIN)
                    and flag_edge_distance(base.outline, flag) >= GREEN_FLAG_EDGE):
                return base, fix
            for shape, shift in shifted_greens(base, hole, core, water):
                if is_dry(shape.outline, water, GREEN_WATER_MARGIN):
                    return shape, dataclasses.replace(fix, green_shift=shift)
        fallback = True
    elif spec.water_green != "island":
        raise ValueError(f"repli de green inconnu : {spec.water_green!r}")
    if relief is None:
        raise ValueError(f"trou {hole.order} : green insulaire, relief requis")
    island = island_of(drawn.outline, relief, water)
    return (dataclasses.replace(drawn, island=island),
            WaterFix(green_target=drawn.target_area, green_island=True,
                     green_island_fallback=fallback))
