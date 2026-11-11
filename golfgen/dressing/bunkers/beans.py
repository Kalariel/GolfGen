"""Haricots : deux disques fondus, tirage seedé, orientation et miroir (round R1).

Haricot (``Bean``) en blocs, repère local (x le long de l'axe, y en travers,
côté ``+y`` = côté du creux profond) : disque 1 (``r1``, gros lobe) en
``(+d/2, 0)``, disque 2 (``r2``) en ``(-d/2, -bend)`` ; champ = minimum lisse
des deux distances signées, ``k`` creux côté ``+y``, ``k`` doux côté ``-y``
(raccord ``K_RAMP``, excédent au-delà de ``K_GENTLE_CAP`` pondéré par
l'angle) ; ``mirror`` : symétrie ``y -> -y``. Contour : zéro du champ sur
``N_RAYS`` rayons issus de ``star_center`` (marche puis dichotomie), refus
explicite (``BeanRefused``) si la forme n'est pas étoilée.

Tirage (``draw_bean``) : forme sans taille ``BeanShape`` uniforme dans
``SHAPE_RANGES`` (k doux dans le mélange validé ``K_GENTLE_MIXTURE``),
miroir à pile ou face, longueur uniforme dans la plage du rôle et du par
(``HARICOT_LENGTHS``) ; flux ``[seed, RNG_LABEL, order, BUNKER_STREAM, rôle,
catégorie]`` (``bunker_rng``). Orientation à la pose (``orient_haricot``) :
creux profond vers l'axe ; garde de green : miroir imposé par le côté du
site ; retombée : miroir tiré, demi-tour s'il diffère.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
import math
from types import MappingProxyType

import numpy as np

from golfgen.dressing.rng import RNG_LABEL
from golfgen.dressing.bunkers.errors import BunkerError
from golfgen.dressing.bunkers.raster import convex_hull, hull_depth, to_local, to_world

N_RAYS = 256                    # sommets du contour (rayons de l'étoile)
MARCH_STEP = 0.1                # pas de la marche grossière (blocs)
BISECTIONS = 20
K_RAMP = 0.75                   # demi-largeur (blocs) du raccord k_creux / k_plein
K_GENTLE_CAP = 3.2              # k plein au-delà duquel l'excédent passe par l'angle
GENTLE_EXCESS_SIN = (0.2, 0.8)  # sinus de l'angle à l'axe : excédent nul -> plein
REFUSED_CENTRE = "centre hors du haricot"
REFUSED_STAR = "non étoilée"
R1_REF = 1.82                   # r1 du haricot unité (blocs)
K_GENTLE_MAX = 4.0
# k doux validé : 65 % « cacahuète », 35 % « rein » (nom, poids, bornes).
K_GENTLE_MIXTURE = (("cacahuète", 0.65, (2.5, 3.0)), ("rein", 0.35, (3.8, K_GENTLE_MAX)))
SHAPE_RANGES = MappingProxyType({   # bornes des tirages uniformes (ordre de tirage fixe)
    "q": (0.65, 0.80),          # rapport des lobes r2/r1
    "e": (2.00, 2.15),          # allongement d/r1
    "k_deep": (1.8, 2.3),       # k côté creux profond (blocs à r1 = 1,82)
    "k_gentle": (2.5, K_GENTLE_MAX),
    "bend": (0.10, 0.35),       # cambrure
})
PARAM_KEYS = tuple(SHAPE_RANGES)
FAMILY_LENGTH_RANGE = (8.0, 16.0)
# Longueur (blocs) par (rôle, par).
HARICOT_LENGTHS = {("green_guard", 3): (8.0, 10.0),
                   ("green_guard", 4): (10.0, 12.0), ("green_guard", 5): (10.0, 12.0),
                   ("landing", 4): (12.0, 16.0), ("landing", 5): (12.0, 16.0)}
# Flux des bunkers : [seed, RNG_LABEL, order, BUNKER_STREAM, rôle, catégorie].
BUNKER_STREAM = 5
ROLE_IDS = {"green_guard": 1, "landing": 2}
CATEGORY_IDS = {"haricot": 1}
# Écart (blocs) sous lequel les deux côtés du creux sont jugés indiscernables.
CONCAVE_MIN_GAP = 0.05


class BeanRefused(ValueError):
    """Refus de ``bean_outline`` ; ``code`` : ``REFUSED_CENTRE`` ou ``REFUSED_STAR``."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class Bean:
    """Haricot à deux disques, en blocs ; ``scale`` multiplie tout."""

    r1: float
    r2: float
    d: float
    k_hollow: float
    k_full: float
    bend: float = 0.0
    scale: float = 1.0
    mirror: bool = False

    def scaled(self) -> tuple[float, float, float, float, float, float]:
        s = self.scale
        return (self.r1 * s, self.r2 * s, self.d * s, self.k_hollow * s, self.k_full * s,
                self.bend * s)


@dataclass(frozen=True)
class BeanShape:
    """Forme sans taille (rapports à ``r1 = R1_REF``) et miroir."""

    q: float
    e: float
    k_deep: float
    k_gentle: float
    bend: float
    mirror: bool = False

    def unit_bean(self) -> Bean:
        return Bean(r1=R1_REF, r2=self.q * R1_REF, d=self.e * R1_REF, k_hollow=self.k_deep,
                    k_full=self.k_gentle, bend=self.bend, mirror=self.mirror)

    def bean(self, length: float) -> Bean:
        """Haricot de longueur ``length`` (emprise en x local) ; seule ``scale`` change."""
        unit = self.unit_bean()
        return replace(unit, scale=length / float(np.ptp(bean_outline(unit)[:, 0])))


@dataclass(frozen=True)
class BeanDraw:
    """Un tirage : forme et longueur cible (blocs)."""

    shape: BeanShape
    length: float

    def bean(self) -> Bean:
        return self.shape.bean(self.length)


# --- champ des deux disques -------------------------------------------------

def smooth_min(a: np.ndarray, b: np.ndarray, k: np.ndarray) -> np.ndarray:
    """Minimum lisse polynomial (``k`` > 0) : comblement maximal ``k/4`` à ``a = b``."""
    h = np.clip(0.5 + 0.5 * (b - a) / k, 0.0, 1.0)
    return b + (a - b) * h - k * h * (1.0 - h)


def _local_xy(bean: Bean, points: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    x, y = points[..., 0], points[..., 1]
    return x, (-y if bean.mirror else y)


def axis_side(bean: Bean, points: np.ndarray) -> np.ndarray:
    """Distance signée des points locaux à la droite des centres, > 0 côté creux."""
    _, _, d, _, _, bend = bean.scaled()
    x, y = _local_xy(bean, points)
    return (d * y - bend * x + bend * d / 2.0) / math.hypot(d, bend)


def _smoothstep(t: np.ndarray) -> np.ndarray:
    t = np.clip(t, 0.0, 1.0)
    return t * t * (3.0 - 2.0 * t)


def star_center(bean: Bean) -> np.ndarray:
    """Point du segment des centres à égale distance des deux cercles."""
    r1, r2, d, _, _, bend = bean.scaled()
    c1, c2 = np.array((d / 2.0, 0.0)), np.array((-d / 2.0, -bend))
    length = float(np.linalg.norm(c1 - c2))
    center = c2 + (c1 - c2) * (length - r1 + r2) / (2.0 * length)
    return center * np.array((1.0, -1.0)) if bean.mirror else center


def _sin_from_axis(bean: Bean, points: np.ndarray) -> np.ndarray:
    rel = points - star_center(bean)
    return axis_side(bean, points) / np.maximum(np.hypot(rel[..., 0], rel[..., 1]), 1e-12)


def field(bean: Bean, points: np.ndarray) -> np.ndarray:
    """Champ (blocs, < 0 dedans) aux points locaux ``(..., 2)``."""
    r1, r2, d, k_hollow, k_full, bend = bean.scaled()
    x, y = _local_xy(bean, points)
    d1 = np.hypot(x - d / 2.0, y) - r1
    d2 = np.hypot(x + d / 2.0, y + bend) - r2
    side = axis_side(bean, points)
    ramp = _smoothstep((K_RAMP * bean.scale - side) / (2.0 * K_RAMP * bean.scale))
    k_ramped = min(k_full, K_GENTLE_CAP * bean.scale)
    k = k_hollow + (k_ramped - k_hollow) * ramp
    if k_full > k_ramped:
        lo, hi = GENTLE_EXCESS_SIN
        k = k + (k_full - k_ramped) * _smoothstep((-_sin_from_axis(bean, points) - lo) / (hi - lo))
    return smooth_min(d1, d2, k)


def bean_outline(bean: Bean) -> np.ndarray:
    """Contour local ``(N_RAYS, 2)`` (sens trigonométrique) ; ``BeanRefused`` si
    le centre de l'étoile est hors du haricot ou si un rayon n'a pas exactement
    un changement de signe."""
    r1, r2, d, k_hollow, k_full, bend = bean.scaled()
    center = star_center(bean)
    at_center = float(field(bean, center[None, :])[0])
    if at_center >= 0.0:
        raise BeanRefused(REFUSED_CENTRE, f"centre de l'étoile hors du haricot (champ "
                                          f"{at_center:+.3f} ≥ 0) : {bean}")
    angle = np.linspace(0.0, 2.0 * math.pi, N_RAYS, endpoint=False)
    direction = np.column_stack((np.cos(angle), np.sin(angle)))
    reach = d + abs(bend) + max(r1, r2) + max(k_hollow, k_full) / 4.0 + MARCH_STEP
    ts = np.arange(0.0, reach + MARCH_STEP, MARCH_STEP)
    values = field(bean, center + direction[:, None, :] * ts[None, :, None])
    outside = values >= 0.0
    changes = np.count_nonzero(outside[:, 1:] != outside[:, :-1], axis=1)
    if (changes != 1).any():
        bad = np.flatnonzero(changes != 1)
        raise BeanRefused(REFUSED_STAR, f"forme non étoilée : {len(bad)} rayon(s) sur {N_RAYS} "
                          f"avec {sorted(set(changes[bad].tolist()))} changement(s) de signe "
                          f"au lieu de 1 : {bean}")
    first = np.argmax(outside, axis=1)
    low, high = ts[first - 1], ts[first]
    for _ in range(BISECTIONS):
        mid = 0.5 * (low + high)
        inside = field(bean, center + direction * mid[:, None]) < 0.0
        low = np.where(inside, mid, low)
        high = np.where(inside, high, mid)
    return center + direction * (0.5 * (low + high))[:, None]


def bean_cells(bean: Bean, center=(0.0, 0.0), tangent=(1.0, 0.0),
               outline: np.ndarray | None = None) -> np.ndarray:
    """Cases ``(k, 2)`` du haricot posé en ``center`` le long de ``tangent`` :
    centre de case dans le champ < 0 ; ``outline`` (contour local) ne fixe
    que la boîte parcourue."""
    local = bean_outline(bean) if outline is None else outline
    world = to_world(local, center, tangent)
    lo = np.floor(world.min(axis=0)).astype(int)
    hi = np.ceil(world.max(axis=0)).astype(int)
    xs, ys = np.meshgrid(np.arange(lo[0], hi[0]), np.arange(lo[1], hi[1]), indexing="ij")
    cells = np.column_stack((xs.ravel(), ys.ravel()))
    return cells[field(bean, to_local(cells + 0.5, center, tangent)) < 0.0]


# --- tirage -----------------------------------------------------------------

def mixture_value(rng: np.random.Generator, mixture=K_GENTLE_MIXTURE) -> float:
    """Composante par un uniforme sur [0, 1), puis valeur uniforme dans ses bornes."""
    weights = np.array([weight for _, weight, _ in mixture], dtype=float)
    if abs(weights.sum() - 1.0) > 1e-9:
        raise ValueError(f"poids du mélange de somme {weights.sum()} ≠ 1 : {mixture}")
    pick = float(rng.uniform())
    index = min(int(np.searchsorted(np.cumsum(weights), pick, side="right")), len(mixture) - 1)
    return float(rng.uniform(*mixture[index][2]))


def sample_bean(rng: np.random.Generator, length_range=FAMILY_LENGTH_RANGE,
                ranges=None, mixture=None) -> BeanDraw:
    """Tirage sans contrôle : paramètres dans l'ordre ``PARAM_KEYS`` (k doux
    dans ``mixture`` s'il est donné), miroir, puis longueur."""
    ranges = SHAPE_RANGES if ranges is None else ranges
    values = {key: (mixture_value(rng, mixture) if key == "k_gentle" and mixture is not None
                    else float(rng.uniform(*ranges[key]))) for key in PARAM_KEYS}
    mirror = bool(rng.integers(2))
    return BeanDraw(BeanShape(**values, mirror=mirror), float(rng.uniform(*length_range)))


def draw_bean(rng: np.random.Generator, length_range=FAMILY_LENGTH_RANGE,
              ranges=None, mixture=None) -> BeanDraw:
    """``sample_bean`` contrôlé par ``bean_outline`` : lève au lieu de retirer."""
    draw = sample_bean(rng, length_range, ranges, mixture)
    try:
        bean_outline(draw.shape.unit_bean())
    except BeanRefused as error:
        raise BunkerError(f"tirage refusé {draw.shape} : {error}") from error
    return draw


def bunker_rng(seed: int, order: int, role: str, category: str) -> np.random.Generator:
    """Flux des bunkers du trou ``order`` : rôle puis catégorie."""
    return np.random.default_rng([seed, RNG_LABEL, order, BUNKER_STREAM,
                                  ROLE_IDS[role], CATEGORY_IDS[category]])


def haricot_length_range(role: str, par: int) -> tuple[float, float]:
    try:
        return HARICOT_LENGTHS[(role, par)]
    except KeyError:
        raise ValueError(f"pas de longueur de haricot pour le rôle {role!r} au par {par}") from None


def orient_haricot(draw: BeanDraw, row: dict) -> tuple[BeanShape, np.ndarray]:
    """Forme (miroir final) et tangente de pose au site ``row`` (``side``,
    ``tangent``, ``role``) : creux profond vers l'axe ; garde de green :
    miroir imposé ; retombée : miroir tiré, demi-tour (``-t``) s'il diffère."""
    tangent = np.asarray(row["tangent"], dtype=float)
    forward_mirror = row["side"] == "left"
    if row["role"] == "green_guard":
        return replace(draw.shape, mirror=forward_mirror), tangent
    if draw.shape.mirror == forward_mirror:
        return draw.shape, tangent
    return draw.shape, -tangent


def landing_placement(seed: int, order: int, par: int, row: dict):
    """Haricot de retombée au site ``row`` :
    (site, haricot, contour local, tangente, normale extérieure, longueur).

    Tirage toujours sur le flux et la plage du rôle ``"landing"``, quel que
    soit ``row["role"]`` (comme l'étude) ; l'orientation lit ``row``."""
    draw = draw_bean(bunker_rng(seed, order, "landing", "haricot"),
                     haricot_length_range("landing", par), mixture=K_GENTLE_MIXTURE)
    shape, tangent = orient_haricot(draw, row)
    bean, length = shape.bean(draw.length), draw.length
    base_tangent = np.asarray(row["tangent"])
    normal = np.array((-base_tangent[1], base_tangent[0]))
    outward = normal if row["side"] == "left" else -normal
    return row, bean, bean_outline(bean), tangent, outward, length


def concave_side(local) -> dict:
    """Côté y local du creux : plus grand écart contour -> enveloppe convexe."""
    local = np.asarray(local, dtype=float)
    depth = np.maximum(hull_depth(local, convex_hull(local)), 0.0)
    plus = float(depth[local[:, 1] > 0].max(initial=0.0))
    minus = float(depth[local[:, 1] < 0].max(initial=0.0))
    return {"sign": 1 if plus >= minus else -1, "max_hull_gap_plus_y": round(plus, 4),
            "max_hull_gap_minus_y": round(minus, 4), "determined": abs(plus - minus) >= CONCAVE_MIN_GAP}
