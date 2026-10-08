"""Étape M — routage Muirfield (R2 : construction valide par retour arrière borné).

Patron (comme le vrai Muirfield) : clubhouse sur un BORD de carte ; le front
fait une boucle extérieure dans un sens, le back une boucle intérieure en sens
inverse, tous deux partant du clubhouse et y revenant. Le front part le long
du bord d'un côté du clubhouse (trou 1) et revient le long du bord de l'autre
côté (trou 9) ; le back sort du clubhouse vers l'intérieur ENTRE les trous 1
et 9 et y revient.

Anneaux : superellipses (carré arrondi, exposant ``RING_P``) centrées sur la
carte et qui en suivent la forme (demi-axes différents si la carte est
rectangulaire) ; cible extérieure pour le front, intérieure pour le back.
Chaque green reçoit une cible DOUCE : le point du chemin de son nine
(clubhouse → anneau → clubhouse) à la fraction de longueur nominale cumulée.

Secteur réservé au clubhouse (repère local : normale entrante ``n`` et
tangente au bord orientée vers le côté du trou 1 ; ``φ`` = angle depuis ``n``,
positif côté trou 1) : chaque trou d'ancrage a tout son axe dans un cône
convexe issu du clubhouse, et ces quatre cônes sont disjoints —

    trou 9 : φ ≤ −58°   trou 10 : −32° ≤ φ ≤ −1°   trou 18 : 1° ≤ φ ≤ 32°   trou 1 : φ ≥ 58°

Deux polylignes contenues dans deux cônes convexes disjoints de même sommet
ne peuvent pas se croiser, liaisons au clubhouse comprises : 1, 9, 10 et 18
ne peuvent donc pas se croiser par construction. Les sites du front sont en
outre exclus du couloir du back (|φ| < 45°, jusqu'à l'anneau intérieur).

Construction (R2, réordonnée au round A2) : recherche en profondeur bornée.
Phase A : les quatre trous d'ancrage d'abord (1, 9, 10, 18 : premier trou
depuis le clubhouse, dernier trou ancré vers le clubhouse), avec
anticipation — un ancrage qui ne laisse plus de candidat à un ancrage restant
est écarté — puis les trous 2 à 8, qui doivent relier le green 1 au tee 9.
Phase B, une fois : les trous 11 à 17 entre le green 10 et le tee 18. À
chaque niveau, les couples (tee, green) faisables — tee à liaison du point
courant (plages dérivées des ``ValidationRules`` par ``link_bounds``),
longueur dans la plage du par (tir droit ou 1 dogleg ≤ 55°) — passent des
pré-filtres vectorisés (conditions nécessaires des contrôles, doglegs
compris), sont triés par score (distance à la cible − qualité des sites −
nouveauté de direction) puis contrôlés en ligne par ``partial_checks``
contre TOUS les trous posés ; au plus ``CHILDREN_PER_NODE`` enfants valides
par niveau, budgets ``CHECK_BUDGET_PER_NINE`` / ``NODE_BUDGET_PER_NINE`` par
nine. Bornes de retour : trous 6–7 (15–16) à distance atteignable du tee
ancré ; l'antépénultième green (7 / 16) doit encore permettre un trou-pont
(8 / 17) jusqu'à ce tee (sites libres, liaisons non bloquées), vérifié de
nouveau après sa pose. Avant toute construction, la capacité des cônes
d'ancrage (pars qui y tiennent à cette position de clubhouse) contraint la
permutation des pars ; un plan sans permutation admissible n'est pas tenté.
Relances bon marché (angle de départ, permutation des pars, position du
clubhouse) ; aucune règle n'est jamais assouplie : échec explicite sinon.
Au plus ``MAX_ATTEMPTS`` tentatives réelles : une variante dont l'échec est
déjà prouvé (même plan, ou même clubhouse et mêmes pars d'ancrage après une
recherche d'ancrages exhaustive) est sautée sans être comptée, et les
clubhouses 3, 4… prennent le relais une fois les trois premiers épuisés.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from functools import lru_cache
from itertools import permutations, product
import math
import time
from typing import Callable, Iterator

import numpy as np

from experiments.elastic_routing.geometry import ValidationRules, Violation, validate
from experiments.elastic_routing.model import (
    GLOBAL_PAR_QUOTA,
    PAR_SPECS,
    ControlPoint,
    CourseLayout,
    ElasticHole,
    NineLayout,
)
from experiments.elastic_routing.partial_checks import (
    PREFILTER_SLACK,
    Obstacles,
    PartialLayout,
    PlannedLink,
    segment_segment_distances,
)
from experiments.elastic_routing.sites import Sites, build_sites, load_terrain


Point = tuple[float, float]

MAP_WIDTH = 400.0
MAP_HEIGHT = 400.0
CLUBHOUSE_EDGE_INSET = 6.0          # clubhouse à 6 blocs à l'intérieur de son bord
CLUBHOUSE_ALONG = (0.3, 0.7)        # position le long du bord (fraction), tirée par la seed
RING_P = 5.0                        # exposant de superellipse (carré arrondi)
OUTER_INSET = 34.0                  # demi-axes anneau extérieur = demi-carte - 34
RING_GAP = 78.0                     # demi-axes anneau intérieur = extérieur - 78
RING_STEP_DEG = 0.5

# Angles de départ (degrés, autour du centre de carte) : (front, back).
# Index 0 = plan de base ; les suivants servent aux relances.
START_ANGLES = ((9.0, 18.0), (15.0, 26.0), (5.0, 12.0))
PAR_PERMUTATIONS = 3                # relances par permutation des pars
# Plafond de tentatives RÉELLES (entrées de ``attempts``, infaisables
# comprises) : 27 = 3 clubhouses × 3 permutations × 3 angles, valeur
# historique inchangée. Les doublons d'un échec prouvé sont sautés sans
# compter ; les positions de clubhouse 3, 4… complètent jusqu'au plafond.
MAX_ATTEMPTS = 27
# Garde-fou : chaque nouvelle position de clubhouse donne au moins une
# tentative réelle (aucune clé d'échec prouvé ne la couvre encore), donc
# MAX_ATTEMPTS positions suffisent toujours à atteindre le plafond.
MAX_CLUBHOUSE_POSITIONS = MAX_ATTEMPTS

# Secteur réservé au clubhouse (angles φ dans le repère local du clubhouse)
ANCHOR_FRONT_MIN_DEG = 58.0
ANCHOR_BACK_MIN_DEG = 1.0
ANCHOR_BACK_MAX_DEG = 32.0
CORRIDOR_HALF_DEG = 45.0
CORRIDOR_EXTRA = 30.0               # le couloir dépasse l'anneau intérieur de 30 blocs

CLUBHOUSE_LINK_MARGIN = 2.0        # liaison clubhouse ≥ rayon dégagé + max(width_min)/2 + 2
LINK_NOMINAL = 25.0                 # liaison nominale pour les fractions cibles
USED_POINT_CLEARANCE = 10.0         # un site trop près d'un tee/green déjà posé est consommé
DOGLEG_MAX_DEG = 55.0
DOGLEG_FRACTION = 0.6               # coude à 60 % de la corde
DOGLEG_LENGTH_SLACK = 2.0           # longueur visée = length_min + 2
DOGLEG_EDGE_MARGIN = 8.0
RETURN_BOUND_FROM = 5               # borne de retour pour les 6e et 7e trous (index 5, 6)

TARGET_SCALE = 25.0                 # 1 point de score = 25 blocs d'écart à la cible
QUALITY_WEIGHT = 0.5                # par site (tee, green)
NOVELTY_WEIGHT = 0.5                # bonus max pour un virage ≥ 90° vs le trou précédent

CHILDREN_PER_NODE = 3               # k meilleurs candidats valides explorés par niveau
EXAMINED_PER_NODE = 150             # candidats contrôlés au plus par niveau
CHECK_BUDGET_PER_NINE = 1500        # contrôles en ligne au plus par nine et par tentative
NODE_BUDGET_PER_NINE = 300          # nœuds de recherche au plus par nine et par tentative


WIDTH_MODES = ("variable", "min")
TARGET_MODES = ("uniform", "irregular")
TARGET_JITTER = 0.5                 # M1 : facteur de pas tiré dans [1 - a, 1 + a]
WIDTH_STEP = 0.5                    # largeurs arrondies au demi-bloc

# Round R2b M2 : chemin cible à lobes pour le SEUL nine intérieur. Paramètres
# déclarés avant les mesures, à ne pas ajuster après coup.
PATH_MODES = ("ring", "lobed")
LOBE_ORDERS = (2, 3)                # nombre de lobes m, tiré uniformément par seed
LOBE_OUT = 30.0                     # décalage radial max vers l'extérieur (blocs)
LOBE_IN = 20.0                      # décalage radial max vers l'intérieur (blocs)
LOBE_QUIET_DEG = 40.0               # aucun lobe à moins de 40° du clubhouse
LOBE_FULL_DEG = 80.0                # lobes pleins au-delà de 80° (smoothstep entre)
LOBE_MIN_RADIUS = 5.0               # rayon minimal du chemin à lobes (ValueError sinon)


def hole_width_fractions(seed: int) -> dict[int, float]:
    """Round C1 : position seedée de chaque trou (ordre 1..18) dans la plage
    de largeur de son par, tirée une fois par seed (indépendante des
    relances, qui peuvent changer le par d'un ordre)."""
    fractions = np.random.default_rng([seed, 31]).uniform(0.0, 1.0, size=18)
    return {order: float(fractions[order - 1]) for order in range(1, 19)}


def hole_width(par: int, fraction: float | None) -> float:
    """Largeur du trou : minimum du par (``fraction`` None, comportement des
    rounds A–B) ou point seedé de la plage [width_min, width_max]."""
    spec = PAR_SPECS[par]
    if fraction is None:
        return spec.width_min
    width = spec.width_min + fraction * (spec.width_max - spec.width_min)
    width = round(width / WIDTH_STEP) * WIDTH_STEP
    return float(min(max(width, spec.width_min), spec.width_max))


PATTERNS = ("muirfield", "muirfield_inverse")
PATTERN_CHOICES = (*PATTERNS, "random")


def resolve_pattern(seed: int, pattern: str) -> str:
    """Patron effectif. ``pattern`` est un paramètre explicite (au même titre
    que la seed) ; ``random`` le tire de façon déterministe à partir de la
    seed (flux indépendant de celui du routage)."""
    if pattern == "random":
        return PATTERNS[int(np.random.default_rng([seed, 23]).integers(len(PATTERNS)))]
    if pattern not in PATTERNS:
        raise ValueError(f"patron inconnu : {pattern!r} (attendu : {', '.join(PATTERN_CHOICES)})")
    return pattern


def outer_start(pattern: str) -> int:
    """Premier trou du nine qui fait le grand tour extérieur : le front (1)
    pour ``muirfield``, le back (10) pour ``muirfield_inverse``. Le patron
    doit être résolu (``random`` compris : passer par ``resolve_pattern``)."""
    if pattern not in PATTERNS:
        raise ValueError(f"patron non résolu ou inconnu : {pattern!r} (attendu : "
                         f"{', '.join(PATTERNS)} ; 'random' passe par resolve_pattern)")
    return 1 if pattern == "muirfield" else 10


def inner_start(pattern: str) -> int:
    return 10 if outer_start(pattern) == 1 else 1


def nine_start(order: int) -> int:
    return 1 if order <= 9 else 10


class MuirfieldRoutingError(RuntimeError):
    """Aucune relance n'a produit de parcours valide (aucune règle assouplie).

    ``skipped`` : variantes sautées car leur échec était déjà prouvé (hors
    de ``attempts``)."""

    def __init__(self, seed: int, attempts: list[dict], skipped: list[dict] | None = None):
        super().__init__(f"seed {seed} : échec après {len(attempts)} tentative(s)")
        self.seed = seed
        self.attempts = attempts
        self.skipped = list(skipped or ())


@dataclass(frozen=True, slots=True)
class Plan:
    edge: str
    clubhouse: Point
    direction: int
    front_pars: tuple[int, ...]
    back_pars: tuple[int, ...]
    outer_delta_deg: float
    inner_delta_deg: float
    clubhouse_index: int
    permutation_index: int
    angle_index: int
    pattern: str = "muirfield"


@dataclass(frozen=True, slots=True)
class MuirfieldResult:
    seed: int
    width: float
    height: float
    layout: CourseLayout
    violations: tuple[Violation, ...]
    plan: Plan
    outer_ring: tuple[Point, ...]
    inner_ring: tuple[Point, ...]
    front_path: tuple[Point, ...]
    back_path: tuple[Point, ...]
    attempts: tuple[dict, ...]
    elapsed_seconds: float
    timings: dict[str, float] = field(default_factory=dict)
    requested_pattern: str = "muirfield"
    width_mode: str = "variable"
    target_mode: str = "uniform"
    path_mode: str = "ring"
    # chemins ANNEAU des deux nines (repère des ancrages) ; égaux à
    # front_path / back_path en mode ``ring``
    front_ring_path: tuple[Point, ...] = ()
    back_ring_path: tuple[Point, ...] = ()
    lobes: tuple[int, float] | None = None     # (m, φ) en mode ``lobed``
    # variantes sautées (échec déjà prouvé), hors de ``attempts``
    skipped: tuple[dict, ...] = ()

    @property
    def pattern(self) -> str:
        return self.plan.pattern

    @property
    def clubhouse_edge(self) -> str:
        return self.plan.edge

    @property
    def direction(self) -> int:
        return self.plan.direction

    @property
    def relaunches(self) -> int:
        return len(self.attempts) - 1

    def nine_lengths(self) -> dict[str, dict[str, float]]:
        out = {}
        for name, nine in (("front", self.layout.front), ("back", self.layout.back)):
            holes = math.fsum(hole.length for hole in nine.holes)
            links = math.fsum(link.length for link in nine.links)
            out[name] = {"holes": round(holes, 1), "links": round(links, 1),
                         "total": round(holes + links, 1),
                         "par": sum(hole.par for hole in nine.holes)}
        return out


# ----------------------------------------------------------------------
# Géométrie du patron
# ----------------------------------------------------------------------

EDGES = ("N", "E", "S", "W")


def place_clubhouse(rng: np.random.Generator, width: float = MAP_WIDTH,
                    height: float = MAP_HEIGHT) -> tuple[str, Point]:
    edge = EDGES[int(rng.integers(4))]
    fraction = float(rng.uniform(*CLUBHOUSE_ALONG))
    inset = CLUBHOUSE_EDGE_INSET
    point = {"N": (fraction * width, inset), "S": (fraction * width, height - inset),
             "W": (inset, fraction * height), "E": (width - inset, fraction * height)}[edge]
    return edge, point


def superellipse_radius(theta, semi_x: float, semi_y: float, p: float = RING_P):
    c, s = np.abs(np.cos(theta)), np.abs(np.sin(theta))
    return ((c / semi_x) ** p + (s / semi_y) ** p) ** (-1.0 / p)


def ring_arc(theta_start: float, sweep: float, semi_x: float, semi_y: float,
             center: Point) -> list[Point]:
    steps = max(2, int(abs(math.degrees(sweep)) / RING_STEP_DEG) + 1)
    thetas = theta_start + np.linspace(0.0, sweep, steps)
    radii = superellipse_radius(thetas, semi_x, semi_y)
    return [(center[0] + r * math.cos(t), center[1] + r * math.sin(t))
            for r, t in zip(radii, thetas)]


def ring_semi_axes(width: float, height: float) -> tuple[tuple[float, float], tuple[float, float]]:
    outer = (width / 2 - OUTER_INSET, height / 2 - OUTER_INSET)
    inner = (outer[0] - RING_GAP, outer[1] - RING_GAP)
    if min(inner) <= 0.0:
        raise ValueError(f"carte {width:g}×{height:g} trop petite pour deux anneaux")
    return outer, inner


def _polyline_cumulative(path: list[Point]) -> np.ndarray:
    arr = np.asarray(path)
    steps = np.hypot(*np.diff(arr, axis=0).T)
    return np.concatenate([[0.0], np.cumsum(steps)])


def point_at(path: list[Point], cumulative: np.ndarray, distance: float) -> Point:
    distance = min(max(distance, 0.0), float(cumulative[-1]))
    index = int(np.searchsorted(cumulative, distance, side="right")) - 1
    index = min(max(index, 0), len(path) - 2)
    span = cumulative[index + 1] - cumulative[index]
    t = 0.0 if span <= 1e-12 else (distance - cumulative[index]) / span
    a, b = path[index], path[index + 1]
    return (a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t)


def nine_paths(clubhouse: Point, direction: int, width: float = MAP_WIDTH,
               height: float = MAP_HEIGHT, outer_delta_deg: float = START_ANGLES[0][0],
               inner_delta_deg: float = START_ANGLES[0][1], pattern: str = "muirfield"):
    """Anneaux complets (rendu) et chemins cibles des deux nines.

    Renvoie ``(anneau ext., anneau int., chemin du front, chemin du back)`` ;
    le nine extérieur (grand tour, sens ``direction``) est le front pour
    ``muirfield`` et le back pour ``muirfield_inverse`` ; l'autre nine fait
    la boucle intérieure en sens inverse."""
    center = (width / 2, height / 2)
    theta_ch = math.atan2(clubhouse[1] - center[1], clubhouse[0] - center[0])
    (ox, oy), (ix, iy) = ring_semi_axes(width, height)
    outer = ring_arc(0.0, 2 * math.pi, ox, oy, center)
    inner = ring_arc(0.0, 2 * math.pi, ix, iy, center)
    delta = math.radians(outer_delta_deg)
    delta_b = math.radians(inner_delta_deg)
    outer_path = [clubhouse, *ring_arc(theta_ch + direction * delta,
                                       direction * (2 * math.pi - 2 * delta), ox, oy, center),
                  clubhouse]
    inner_path = [clubhouse, *ring_arc(theta_ch - direction * delta_b,
                                       -direction * (2 * math.pi - 2 * delta_b), ix, iy, center),
                  clubhouse]
    if outer_start(pattern) == 1:
        return outer, inner, outer_path, inner_path
    return outer, inner, inner_path, outer_path


def lobe_parameters(seed: int) -> tuple[int, float]:
    """Round R2b M2 : (m, φ) du chemin intérieur à lobes, tirés une seule
    fois par seed sur le flux ``[seed, 41]`` (indépendants des relances et du
    patron) : m uniforme dans ``LOBE_ORDERS``, φ uniforme dans [0, 2π)."""
    rng = np.random.default_rng([seed, 41])
    order = LOBE_ORDERS[int(rng.integers(len(LOBE_ORDERS)))]
    return order, float(rng.uniform(0.0, 2.0 * math.pi))


def lobe_envelope(theta, theta_ch: float) -> np.ndarray:
    """Enveloppe g(θ) des lobes : 0 à moins de ``LOBE_QUIET_DEG`` du
    clubhouse (écart angulaire |Δ(θ, θ_ch)| autour du centre), 1 au-delà de
    ``LOBE_FULL_DEG``, smoothstep 3t² − 2t³ entre les deux."""
    delta = np.abs((np.asarray(theta, dtype=float) - theta_ch + math.pi) % (2 * math.pi) - math.pi)
    t = np.clip((np.degrees(delta) - LOBE_QUIET_DEG) / (LOBE_FULL_DEG - LOBE_QUIET_DEG), 0.0, 1.0)
    return t * t * (3.0 - 2.0 * t)


def lobe_offsets(theta, theta_ch: float, order: int, phase: float) -> np.ndarray:
    """Décalage radial off(θ) = g(θ)·L(c)·c, c = cos(mθ + φ), L = ``LOBE_OUT``
    si c > 0 (vers l'extérieur), ``LOBE_IN`` sinon (vers le centre)."""
    c = np.cos(order * np.asarray(theta, dtype=float) + phase)
    return lobe_envelope(theta, theta_ch) * np.where(c > 0.0, LOBE_OUT, LOBE_IN) * c


def lobed_arc(theta_start: float, sweep: float, semi_x: float, semi_y: float, center: Point,
              theta_ch: float, lobes: tuple[int, float], width: float, height: float
              ) -> list[Point]:
    """Arc de l'anneau (mêmes angles que ``ring_arc``) dont le rayon reçoit
    le décalage ``lobe_offsets`` le long du rayon issu du centre.

    ``ValueError`` si un rayon tombe sous ``LOBE_MIN_RADIUS`` ou si un point
    sort de la carte : jamais de rognage silencieux."""
    steps = max(2, int(abs(math.degrees(sweep)) / RING_STEP_DEG) + 1)
    thetas = theta_start + np.linspace(0.0, sweep, steps)
    radii = superellipse_radius(thetas, semi_x, semi_y) + lobe_offsets(thetas, theta_ch, *lobes)
    if float(radii.min()) < LOBE_MIN_RADIUS:
        raise ValueError(f"chemin à lobes : rayon {float(radii.min()):.1f} < {LOBE_MIN_RADIUS:g}")
    xs = center[0] + radii * np.cos(thetas)
    ys = center[1] + radii * np.sin(thetas)
    if xs.min() < 0.0 or ys.min() < 0.0 or xs.max() > width or ys.max() > height:
        raise ValueError(f"chemin à lobes hors de la carte {width:g}×{height:g}")
    return [(float(x), float(y)) for x, y in zip(xs, ys)]


def lobed_inner_path(clubhouse: Point, direction: int, width: float = MAP_WIDTH,
                     height: float = MAP_HEIGHT, inner_delta_deg: float = START_ANGLES[0][1],
                     lobes: tuple[int, float] = (LOBE_ORDERS[0], 0.0)) -> list[Point]:
    """Chemin cible à lobes du nine intérieur : même départ, même balayage et
    mêmes liaisons au clubhouse que le chemin intérieur de ``nine_paths`` ;
    seul le rayon change (l'anneau reste le repère des ancrages)."""
    center = (width / 2, height / 2)
    theta_ch = math.atan2(clubhouse[1] - center[1], clubhouse[0] - center[0])
    _, (ix, iy) = ring_semi_axes(width, height)
    delta_b = math.radians(inner_delta_deg)
    return [clubhouse, *lobed_arc(theta_ch - direction * delta_b,
                                  -direction * (2 * math.pi - 2 * delta_b), ix, iy, center,
                                  theta_ch, lobes, width, height),
            clubhouse]


def check_lobe_room(width: float, height: float) -> None:
    """Validation en amont du mode ``lobed`` : ``ValueError`` explicite si la
    carte ne laisse pas la place aux lobes, quels que soient le clubhouse,
    le sens, l'angle de départ et (m, φ).

    Pire cas, enveloppe pleine sur tout le tour : l'anneau intérieur moins
    ``LOBE_IN`` doit rester ≥ ``LOBE_MIN_RADIUS`` et l'anneau intérieur plus
    ``LOBE_OUT`` doit rester dans la carte. Condition suffisante : si elle
    passe, ``lobed_arc`` ne lève jamais sa ``ValueError`` (gardée en filet de
    sécurité) ; sans elle, un round custom sur une petite carte planterait
    en entier au lieu d'échouer seed par seed."""
    center = (width / 2, height / 2)
    _, (ix, iy) = ring_semi_axes(width, height)
    thetas = np.linspace(0.0, 2 * math.pi, int(360 / RING_STEP_DEG) + 1)
    radii = superellipse_radius(thetas, ix, iy)
    if float(radii.min()) - LOBE_IN < LOBE_MIN_RADIUS:
        raise ValueError(
            f"carte {width:g}×{height:g} trop petite pour le mode lobed : anneau intérieur "
            f"{ix:g}×{iy:g}, il faut un demi-axe ≥ LOBE_IN + LOBE_MIN_RADIUS = "
            f"{LOBE_IN + LOBE_MIN_RADIUS:g}")
    outer = radii + LOBE_OUT
    xs, ys = center[0] + outer * np.cos(thetas), center[1] + outer * np.sin(thetas)
    if xs.min() < 0.0 or ys.min() < 0.0 or xs.max() > width or ys.max() > height:
        raise ValueError(f"carte {width:g}×{height:g} trop petite pour le mode lobed : "
                         f"les lobes extérieurs (LOBE_OUT = {LOBE_OUT:g}) sortent de la carte")


@dataclass(frozen=True, slots=True)
class ClubhouseFrame:
    """Repère local : ``normal`` entrante, ``side`` = tangente vers le premier
    trou du nine extérieur (trou 1 pour ``muirfield``, 10 pour l'inversé)."""

    origin: Point
    normal: Point
    side: Point
    corridor_radius: float

    def phi_deg(self, points: np.ndarray) -> np.ndarray:
        rel = np.asarray(points, dtype=float).reshape(-1, 2) - np.asarray(self.origin)
        along_n = rel @ np.asarray(self.normal)
        along_s = rel @ np.asarray(self.side)
        return np.degrees(np.arctan2(along_s, along_n))

    def in_corridor(self, points: np.ndarray) -> np.ndarray:
        rel = np.asarray(points, dtype=float) - np.asarray(self.origin)
        return ((np.abs(self.phi_deg(points)) < CORRIDOR_HALF_DEG)
                & (np.hypot(rel[:, 0], rel[:, 1]) < self.corridor_radius))


def clubhouse_frame(edge: str, clubhouse: Point, outer_path: list[Point],
                    width: float, height: float) -> ClubhouseFrame:
    """Le côté ``side`` ne dépend que du signe de l'angle de départ du chemin
    extérieur : il est le même pour tous les ``START_ANGLES`` (tous < 90°),
    d'où un seul repère par position de clubhouse (vérifié par les tests)."""
    normal = {"N": (0.0, 1.0), "S": (0.0, -1.0), "W": (1.0, 0.0), "E": (-1.0, 0.0)}[edge]
    tangent = (-normal[1], normal[0])
    first = outer_path[1]
    sign = 1.0 if ((first[0] - clubhouse[0]) * tangent[0]
                   + (first[1] - clubhouse[1]) * tangent[1]) >= 0 else -1.0
    side = (tangent[0] * sign, tangent[1] * sign)
    center = (width / 2, height / 2)
    theta_ch = math.atan2(clubhouse[1] - center[1], clubhouse[0] - center[0])
    (_, _), (ix, iy) = ring_semi_axes(width, height)
    r_in = float(superellipse_radius(theta_ch, ix, iy))
    inner_point = (center[0] + r_in * math.cos(theta_ch), center[1] + r_in * math.sin(theta_ch))
    return ClubhouseFrame(clubhouse, normal, side,
                          math.dist(clubhouse, inner_point) + CORRIDOR_EXTRA)


def anchor_bounds(order: int, pattern: str = "muirfield") -> tuple[float, float] | None:
    """Cône (φ min, φ max) imposé à l'axe d'un trou d'ancrage, sinon None.

    Rôles : le nine extérieur part le long du bord côté ``side`` (φ ≥ 58°) et
    revient le long du bord de l'autre côté (φ ≤ −58°) ; le nine intérieur
    plonge entre eux, en sortant du côté du retour extérieur ([−32°, −1°]) et
    en revenant du côté du départ extérieur ([1°, 32°])."""
    outer, inner = outer_start(pattern), inner_start(pattern)
    return {
        outer: (ANCHOR_FRONT_MIN_DEG, 180.0),
        outer + 8: (-180.0, -ANCHOR_FRONT_MIN_DEG),
        inner: (-ANCHOR_BACK_MAX_DEG, -ANCHOR_BACK_MIN_DEG),
        inner + 8: (ANCHOR_BACK_MIN_DEG, ANCHOR_BACK_MAX_DEG),
    }.get(order)


# ----------------------------------------------------------------------
# Pars
# ----------------------------------------------------------------------

def par_sequence_ok(pars) -> bool:
    """Règle dure : jamais 3 par 5 ni 3 par 3 consécutifs dans un nine."""
    return not any(pars[i] == pars[i + 1] == pars[i + 2] and pars[i] in (3, 5)
                   for i in range(len(pars) - 2))


NINE_PAR_RANGE = (34, 38)            # règle dure : par d'un nine dans [34, 38] (total 72)


def nine_par_ok(pars) -> bool:
    """Règle dure : le par d'un nine reste dans ``NINE_PAR_RANGE``."""
    return NINE_PAR_RANGE[0] <= sum(pars) <= NINE_PAR_RANGE[1]


def par_sequence_penalty(pars) -> int:
    """Règle souple : éviter deux par 5 consécutifs et un nine qui commence
    par un par 3."""
    return (sum(1 for a, b in zip(pars, pars[1:]) if a == b == 5)
            + (1 if pars[0] == 3 else 0))


def draw_par_counts(rng: np.random.Generator) -> tuple[tuple[int, int], tuple[int, int]]:
    """(par 3, par 5) du front et du back : quota 4/10/4, chaque nombre par
    nine dans [1, 3], par de chaque nine dans [34, 38] ; répartition tirée
    par la seed (pas forcément 36/36)."""
    p3_front = int(rng.integers(1, 4))
    p5_front = int(rng.integers(1, 4))
    # par d'un nine = 36 + p5 - p3 ; avec p3, p5 dans [1, 3] (et le quota
    # 4/4), il est toujours dans [34, 38] : la règle est garantie par
    # construction et vérifiée exhaustivement par les tests.
    return ((p3_front, p5_front),
            (GLOBAL_PAR_QUOTA[3] - p3_front, GLOBAL_PAR_QUOTA[5] - p5_front))


@lru_cache(maxsize=None)
def _distinct_orders(p3: int, p5: int) -> tuple[tuple[int, ...], ...]:
    """Toutes les permutations distinctes d'un nine (≤ 1680), ordre lexicographique."""
    base = sorted([3] * p3 + [5] * p5 + [4] * (9 - p3 - p5))
    return tuple(sorted(set(permutations(base))))


def order_nine(p3: int, p5: int, rng: np.random.Generator, tries: int = 200,
               first: frozenset[int] | None = None,
               last: frozenset[int] | None = None) -> tuple[int, ...] | None:
    """Ordre seedé respectant la règle dure, pénalité souple minimale.

    D'abord ``tries`` permutations aléatoires seedées (comportement des
    rounds précédents) ; si aucune n'est admissible, énumération EXHAUSTIVE
    des permutations distinctes et choix seedé parmi les moins pénalisées :
    ``None`` signifie donc qu'aucun ordre admissible n'existe.

    ``first`` / ``last`` : pars admissibles pour le premier et le dernier trou
    (capacité des cônes d'ancrage)."""

    def admissible(pars) -> bool:
        return (par_sequence_ok(pars)
                and (first is None or pars[0] in first)
                and (last is None or pars[-1] in last))

    base = [3] * p3 + [5] * p5 + [4] * (9 - p3 - p5)
    best: tuple[int, int, tuple[int, ...]] | None = None
    for index in range(tries):
        pars = tuple(int(p) for p in rng.permutation(base))
        if not admissible(pars):
            continue
        penalty = par_sequence_penalty(pars)
        if penalty == 0:
            return pars
        if best is None or penalty < best[0]:
            best = (penalty, index, pars)
    if best is not None:
        return best[2]
    candidates = [pars for pars in _distinct_orders(p3, p5) if admissible(pars)]
    if not candidates:
        return None
    lowest = min(par_sequence_penalty(pars) for pars in candidates)
    pool = [pars for pars in candidates if par_sequence_penalty(pars) == lowest]
    return pool[int(rng.integers(len(pool)))]


def draw_pars(rng: np.random.Generator) -> tuple[tuple[int, ...], tuple[int, ...]]:
    (f3, f5), (b3, b5) = draw_par_counts(rng)
    return order_nine(f3, f5, rng), order_nine(b3, b5, rng)


def _nominal_length(par: int) -> float:
    spec = PAR_SPECS[par]
    return (spec.length_min + spec.length_max) / 2.0


def target_jitter_factors(seed: int) -> dict[int, np.ndarray]:
    """Round R2b M1 : facteurs de pas des cibles, tirés une fois par seed
    (flux ``[seed, 37]``, indépendants des relances et du patron) ; clé =
    premier ordre du nine (1 ou 10), 9 facteurs dans
    [1 - TARGET_JITTER, 1 + TARGET_JITTER]."""
    factors = np.random.default_rng([seed, 37]).uniform(
        1.0 - TARGET_JITTER, 1.0 + TARGET_JITTER, size=18)
    return {1: factors[:9], 10: factors[9:]}


def green_targets(path: list[Point], pars: tuple[int, ...],
                  factors: np.ndarray | None = None) -> list[Point]:
    """Cible douce de chaque green : fraction de longueur nominale cumulée.

    ``factors`` (mode ``irregular``) multiplie chaque pas nominal (liaison +
    trou), puis les pas sont renormalisés à leur somme nominale : la dernière
    cible et la liaison de retour ne bougent pas, les fractions restent
    strictement croissantes (facteurs > 0). ``None`` : pas réguliers."""
    cumulative = _polyline_cumulative(path)
    total = sum(LINK_NOMINAL + _nominal_length(par) for par in pars) + LINK_NOMINAL
    running, targets = 0.0, []
    if factors is None:
        for par in pars:
            running += LINK_NOMINAL + _nominal_length(par)
            targets.append(point_at(path, cumulative, running / total * cumulative[-1]))
        return targets
    factors = np.asarray(factors, dtype=float)
    if len(factors) != len(pars):
        raise ValueError(f"{len(factors)} facteurs pour {len(pars)} trous")
    nominal = np.array([LINK_NOMINAL + _nominal_length(par) for par in pars])
    steps = nominal * factors
    runnings = np.cumsum(steps) * (nominal.sum() / steps.sum())
    # dernière cible exacte : les longueurs nominales sont des multiples de
    # 0,5, la somme numpy est donc identique à l'octet à la somme Python
    runnings[-1] = nominal.sum()
    return [point_at(path, cumulative, float(r) / total * cumulative[-1]) for r in runnings]


@dataclass(frozen=True, slots=True)
class LinkBounds:
    """Plages de liaison dérivées des ``ValidationRules`` (jamais codées en dur) :
    ``minimum``–``maximum`` entre trous ; ``clubhouse_min``–``maximum`` pour
    les liaisons du clubhouse, assez longues pour que le cœur du trou reste
    hors du rayon dégagé."""

    minimum: float
    maximum: float
    clubhouse_min: float


def link_bounds(rules: ValidationRules) -> LinkBounds:
    half_width = max(spec.width_min for spec in PAR_SPECS.values()) / 2.0
    clear = rules.clubhouse_clear_radius or 0.0
    clubhouse_min = max(rules.link_min, clear + half_width + CLUBHOUSE_LINK_MARGIN)
    if clubhouse_min > rules.link_max:
        raise ValueError(f"liaison clubhouse ≥ {clubhouse_min:g} incompatible avec "
                         f"link_max = {rules.link_max:g}")
    return LinkBounds(rules.link_min, rules.link_max, clubhouse_min)


def return_reach(pars: tuple[int, ...], index: int, link_max: float) -> float:
    """Borne de faisabilité de retour : distance maximale entre le green du
    trou ``index`` et le tee (déjà ancré) du dernier trou du nine, encore
    rattrapable par les trous intermédiaires restants (liaisons et longueurs
    maximales mises bout à bout en ligne droite)."""
    last = len(pars) - 1
    return (math.fsum(link_max + PAR_SPECS[par].length_max for par in pars[index + 1:last])
            + link_max)


# ----------------------------------------------------------------------
# Recherche
# ----------------------------------------------------------------------

def _dogleg_table(samples: int = 4001) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Table (corde / longueur) → (décalage / longueur, déflexion en degrés)
    pour un coude à ``DOGLEG_FRACTION`` de la corde (invariant d'échelle)."""
    f = DOGLEG_FRACTION
    ratio = np.linspace(1e-3, 1.0, samples)
    lo, hi = np.zeros_like(ratio), np.ones_like(ratio)
    for _ in range(60):
        mid = (lo + hi) / 2
        too_long = np.hypot(f * ratio, mid) + np.hypot((1 - f) * ratio, mid) > 1.0
        hi = np.where(too_long, mid, hi)
        lo = np.where(too_long, lo, mid)
    h = (lo + hi) / 2
    deflection = np.degrees(np.arctan2(h, f * ratio) + np.arctan2(h, (1 - f) * ratio))
    return ratio, h, deflection


_DOGLEG_RATIO, _DOGLEG_H, _DOGLEG_DEFLECTION = _dogleg_table()


def _dogleg_offsets(chords: np.ndarray, length: float) -> tuple[np.ndarray, np.ndarray]:
    """Décalage latéral ``h`` du coude qui donne la longueur ``length`` à une
    corde donnée ; renvoie (h, déflexion en degrés). La longueur exacte du
    trou est revérifiée par ``PartialLayout.check``."""
    ratio = chords / length
    h = np.interp(ratio, _DOGLEG_RATIO, _DOGLEG_H) * length
    deflection = np.interp(ratio, _DOGLEG_RATIO, _DOGLEG_DEFLECTION, left=180.0, right=0.0)
    return h, deflection


@dataclass(frozen=True, slots=True)
class _Level:
    """Contraintes d'un niveau de la recherche (un trou)."""

    order: int
    index: int
    start: np.ndarray | None          # liaison entrante start → tee
    start_min: float
    start_owner: int | None           # trou précédent (propriétaire de la liaison)
    end: np.ndarray | None            # liaison sortante green → end
    end_min: float
    end_owner: int | None             # trou suivant (None : clubhouse)
    reach_point: np.ndarray | None    # borne de retour : green à ≤ reach de ce point
    reach: float
    heading: float | None
    target_green: np.ndarray | None
    target_tee: np.ndarray | None
    bridge_end: np.ndarray | None = None   # tee du dernier trou (ancré) à rejoindre
    bridge_par: int = 4                    # par du trou-pont (avant-dernier)
    bridge_owner: int | None = None        # ordre du dernier trou


_DOGLEG_MIN_RATIO = float(_DOGLEG_RATIO[_DOGLEG_DEFLECTION <= DOGLEG_MAX_DEG].min())


@dataclass
class _Search:
    """Contexte d'une tentative : sites, cadre clubhouse, layout partiel."""

    width: float
    height: float
    tees: Sites
    greens: Sites
    frame: ClubhouseFrame
    partial: PartialLayout
    outer_tee_ok: np.ndarray            # sites hors du couloir du nine intérieur
    outer_green_ok: np.ndarray
    links: LinkBounds
    nodes: int = 0
    rejections: Counter = field(default_factory=Counter)
    deepest: dict[int, int] = field(default_factory=dict)
    budget_used: tuple[dict[int, int], dict[int, int]] = field(default_factory=lambda: ({}, {}))
    pattern: str = "muirfield"
    width_fractions: dict[int, float] | None = None
    target_factors: dict[int, np.ndarray] | None = None
    anchors_done: bool = False
    outer_done: bool = False
    # une coupure (k enfants, candidats examinés ou budget) a eu lieu pendant
    # la pose des ancrages : un échec d'ancrage n'est alors PAS exhaustif
    anchor_truncated: bool = False

    @property
    def clubhouse(self) -> np.ndarray:
        return np.asarray(self.frame.origin)

    def _inside(self, point: np.ndarray, margin: float) -> bool:
        return bool(margin <= point[0] <= self.width - margin
                    and margin <= point[1] <= self.height - margin)

    def _in_anchor(self, order: int, points: np.ndarray) -> np.ndarray:
        bounds = anchor_bounds(order, self.pattern)
        if bounds is None:
            return np.ones(len(points), dtype=bool)
        phi = self.frame.phi_deg(points)
        return (phi >= bounds[0]) & (phi <= bounds[1])

    def width_for(self, order: int, par: int) -> float:
        return hole_width(par, None if self.width_fractions is None
                          else self.width_fractions[order])

    def is_outer(self, order: int) -> bool:
        return nine_start(order) == outer_start(self.pattern)

    def _available(self, points: np.ndarray, mask: np.ndarray, used: list[np.ndarray]) -> np.ndarray:
        ok = mask.copy()
        for point in used:
            ok &= np.hypot(points[:, 0] - point[0], points[:, 1] - point[1]) >= USED_POINT_CLEARANCE
        return ok

    def candidates(self, level: _Level, par: int, used: list[np.ndarray],
                   path_arr: np.ndarray) -> Iterator[ElasticHole]:
        """Trous candidats du niveau, par score croissant. Les pré-filtres
        vectorisés n'écartent que des candidats que ``check`` rejetterait."""
        spec = PAR_SPECS[par]
        order = level.order
        outer = self.is_outer(order)
        obstacles = Obstacles.from_partial(self.partial)
        width = self.width_for(order, par)
        radius, gap = width / 2.0, self.partial.rules.fairway_gap

        tee_ok = self._available(self.tees.points, self.outer_tee_ok if outer
                                 else np.ones(len(self.tees), dtype=bool), used)
        tee_ok &= self._in_anchor(order, self.tees.points)
        if level.start is not None:
            link = np.hypot(*(self.tees.points - level.start).T)
            tee_ok &= (link >= level.start_min) & (link <= self.links.maximum)
        tee_idx = np.flatnonzero(tee_ok)
        if len(tee_idx):
            pts = self.tees.points[tee_idx]
            keep = obstacles.points_clear(pts, radius, gap)
            if level.start is not None:
                keep &= obstacles.links_clear(level.start, pts, level.start_owner)
            tee_idx = tee_idx[keep]

        green_ok = self._available(self.greens.points, self.outer_green_ok if outer
                                   else np.ones(len(self.greens), dtype=bool), used)
        green_ok &= self._in_anchor(order, self.greens.points)
        if level.end is not None:
            link = np.hypot(*(self.greens.points - level.end).T)
            green_ok &= (link >= level.end_min) & (link <= self.links.maximum)
        if level.reach_point is not None:
            green_ok &= np.hypot(*(self.greens.points - level.reach_point).T) <= level.reach
        green_idx = np.flatnonzero(green_ok)
        if len(green_idx):
            pts = self.greens.points[green_idx]
            keep = obstacles.points_clear(pts, radius, gap)
            if level.end is not None:
                keep &= obstacles.links_clear(level.end, pts, level.end_owner)
            green_idx = green_idx[keep]
        if len(green_idx) and level.bridge_end is not None:
            green_idx = green_idx[self._bridge_reachable(self.greens.points[green_idx], level,
                                                         used, obstacles)]
        if len(tee_idx) == 0 or len(green_idx) == 0:
            return

        tee_pts, green_pts = self.tees.points[tee_idx], self.greens.points[green_idx]
        dx = green_pts[None, :, 0] - tee_pts[:, None, 0]
        dy = green_pts[None, :, 1] - tee_pts[:, None, 1]
        chords = np.hypot(dx, dy)
        straight = (chords >= spec.length_min) & (chords <= spec.length_max)
        h, deflection = _dogleg_offsets(chords, spec.length_min + DOGLEG_LENGTH_SLACK)
        dogleg = ((~straight) & (chords > 1.0) & (chords < spec.length_min)
                  & (deflection <= DOGLEG_MAX_DEG))
        rows, cols = np.nonzero(straight)
        if len(rows):
            clear = obstacles.chords_clear(tee_pts[rows], green_pts[cols], radius, gap)
            straight[rows[~clear], cols[~clear]] = False
        # doglegs : les deux coudes possibles (gauche/droite) sont construits
        # ici et pré-filtrés comme les tirs droits (carte, cône, axes, liaisons)
        side_ok: dict[tuple[int, int], list[np.ndarray]] = {}
        rows, cols = np.nonzero(dogleg)
        if len(rows):
            tees_d, greens_d = tee_pts[rows], green_pts[cols]
            chord = greens_d - tees_d
            norm = np.hypot(chord[:, 0], chord[:, 1])
            normal = np.column_stack([-chord[:, 1], chord[:, 0]]) / norm[:, None]
            offset = h[rows, cols][:, None] * normal
            corners = []
            for side in (1, -1):
                corner = tees_d + DOGLEG_FRACTION * chord + side * offset
                ok = ((corner[:, 0] >= DOGLEG_EDGE_MARGIN) & (corner[:, 0] <= self.width - DOGLEG_EDGE_MARGIN)
                      & (corner[:, 1] >= DOGLEG_EDGE_MARGIN) & (corner[:, 1] <= self.height - DOGLEG_EDGE_MARGIN)
                      & self._in_anchor(order, corner))
                ok &= obstacles.chords_clear(tees_d, corner, radius, gap)
                ok &= obstacles.chords_clear(corner, greens_d, radius, gap)
                corners.append((corner, ok))
            any_ok = corners[0][1] | corners[1][1]
            dogleg[rows[~any_ok], cols[~any_ok]] = False
            for k in np.flatnonzero(any_ok):
                side_ok[(int(rows[k]), int(cols[k]))] = [c[k] for c, ok in corners if ok[k]]
        feasible = straight | dogleg
        if not feasible.any():
            return

        score = -(QUALITY_WEIGHT * self.tees.scores[tee_idx][:, None]
                  + QUALITY_WEIGHT * self.greens.scores[green_idx][None, :])
        if level.target_green is not None:
            score = score + (np.hypot(*(green_pts - level.target_green).T) / TARGET_SCALE)[None, :]
        if level.target_tee is not None:
            score = score + (np.hypot(*(tee_pts - level.target_tee).T) / TARGET_SCALE)[:, None]
        if level.heading is not None:
            turn = np.abs((np.arctan2(dy, dx) - level.heading + np.pi) % (2 * np.pi) - np.pi)
            score = score - NOVELTY_WEIGHT * np.minimum(turn, np.pi / 2) / (np.pi / 2)
        flat = np.flatnonzero(feasible.ravel())
        flat = flat[np.argsort(score.ravel()[flat], kind="stable")]

        for item in flat:
            ti, gi = np.unravel_index(item, score.shape)
            tee, green = tee_pts[ti], green_pts[gi]
            tee_cp = ControlPoint(float(tee[0]), float(tee[1]))
            green_cp = ControlPoint(float(green[0]), float(green[1]))
            if straight[ti, gi]:
                yield ElasticHole(order=order, par=par, tee=tee_cp, green=green_cp,
                                  width=width)
                continue
            options = list(side_ok[(int(ti), int(gi))])
            options.sort(key=lambda p: float(np.min(np.hypot(*(path_arr - p).T))))
            for corner in options:
                yield ElasticHole(order=order, par=par, tee=tee_cp, green=green_cp,
                                  doglegs=(ControlPoint(float(corner[0]), float(corner[1])),),
                                  width=width)

    def _bridge_reachable(self, greens: np.ndarray, level: _Level, used: list[np.ndarray],
                          obstacles: Obstacles) -> np.ndarray:
        """Borne de retour stricte (antépénultième trou du nine) : un green
        n'est gardé que si un trou-pont du par ``level.bridge_par`` peut
        encore relier un tee à liaison de ce green au tee ancré du dernier
        trou, sur les sites libres et sans heurter ce qui est posé. Toutes les
        conditions sont nécessaires (pré-filtres), jamais suffisantes."""
        spec = PAR_SPECS[level.bridge_par]
        order = level.order + 1
        radius, gap = self.width_for(order, level.bridge_par) / 2.0, self.partial.rules.fairway_gap
        outer = self.is_outer(order)
        end = level.bridge_end
        lo, hi = self.links.minimum, self.links.maximum
        # greens du pont : à liaison du tee ancré, liaison non bloquée
        g_ok = self._available(self.greens.points, self.outer_green_ok if outer
                               else np.ones(len(self.greens), dtype=bool), used)
        d = np.hypot(*(self.greens.points - end).T)
        g_ok &= (d >= lo) & (d <= hi)
        g_idx = np.flatnonzero(g_ok)
        if len(g_idx):
            pts = self.greens.points[g_idx]
            g_idx = g_idx[obstacles.points_clear(pts, radius, gap)
                          & obstacles.links_clear(end, pts, level.bridge_owner)]
        if len(g_idx) == 0:
            return np.zeros(len(greens), dtype=bool)
        bridge_greens = self.greens.points[g_idx]
        # tees du pont : libres, avec au moins un green du pont à longueur de par
        t_ok = self._available(self.tees.points, self.outer_tee_ok if outer
                               else np.ones(len(self.tees), dtype=bool), used)
        t_idx = np.flatnonzero(t_ok)
        t_idx = t_idx[obstacles.points_clear(self.tees.points[t_idx], radius, gap)]
        if len(t_idx) == 0:
            return np.zeros(len(greens), dtype=bool)
        tees = self.tees.points[t_idx]
        chords = np.hypot(bridge_greens[None, :, 0] - tees[:, None, 0],
                          bridge_greens[None, :, 1] - tees[:, None, 1])
        straight = (chords >= spec.length_min) & (chords <= spec.length_max)
        rows, cols = np.nonzero(straight)
        if len(rows):
            clear = obstacles.chords_clear(tees[rows], bridge_greens[cols], radius, gap)
            straight[rows[~clear], cols[~clear]] = False
        bent = (chords >= _DOGLEG_MIN_RATIO * spec.length_min) & (chords < spec.length_min)
        tees = tees[(straight | bent).any(axis=1)]
        if len(tees) == 0:
            return np.zeros(len(greens), dtype=bool)
        # green candidat → tee du pont à liaison, liaison non bloquée
        link = np.hypot(greens[:, None, 0] - tees[None, :, 0], greens[:, None, 1] - tees[None, :, 1])
        pairs = np.argwhere((link >= lo) & (link <= hi))
        reachable = np.zeros(len(greens), dtype=bool)
        if len(pairs):
            starts, ends = greens[pairs[:, 0]], tees[pairs[:, 1]]
            if len(obstacles.axis_a):
                dist = segment_segment_distances(starts, ends, obstacles.axis_a, obstacles.axis_b)
                clear = (dist >= obstacles.axis_radius[None] - PREFILTER_SLACK).all(axis=1)
            else:
                clear = np.ones(len(pairs), dtype=bool)
            reachable[pairs[clear, 0]] = True
        return reachable

    def anchor_fits(self, order: int, par: int, path: list[Point]) -> bool:
        """Capacité du cône d'ancrage : existe-t-il, sur les sites et sans
        aucun autre trou posé, un trou de ce par dans le cône de ``order``,
        relié au clubhouse ? Condition nécessaire (les trous posés ne font
        que retirer des candidats)."""
        ch = self.clubhouse
        leaving = order in (1, 10)            # premier trou d'un nine (sinon dernier)
        level = _Level(order=order, index=0 if leaving else 8,
                       start=ch if leaving else None, start_min=self.links.clubhouse_min,
                       start_owner=None, end=None if leaving else ch,
                       end_min=self.links.clubhouse_min, end_owner=None, reach_point=None,
                       reach=math.inf, heading=None, target_green=None, target_tee=None)
        return next(iter(self.candidates(level, par, [], np.asarray(path))), None) is not None

    def route_course(self, front_pars: tuple[int, ...], back_pars: tuple[int, ...],
                     front_path: list[Point], back_path: list[Point]
                     ) -> tuple[list[ElasticHole], list[ElasticHole]] | None:
        """Recherche en profondeur bornée sur les deux nines à la fois.

        Phase A : les quatre trous d'ancrage d'abord — premier et dernier trou
        du nine extérieur, puis du nine intérieur — pour que leur emprise soit
        réservée avant que les trous intermédiaires ne consomment l'espace
        autour du clubhouse ; puis les trous intermédiaires du nine EXTÉRIEUR
        (2..8 pour ``muirfield``, 11..17 pour l'inversé). Phase B, une seule
        fois au bout de la phase A : les trous intermédiaires du nine
        intérieur. Un échec de la phase B termine la tentative (pas de retour
        dans le nine extérieur). Chaque nine garde son propre budget.
        """
        factors = self.target_factors or {}
        nines = {
            1: (front_pars, [np.asarray(t) for t in green_targets(front_path, front_pars,
                                                                 factors.get(1))],
                np.asarray(front_path)),
            10: (back_pars, [np.asarray(t) for t in green_targets(back_path, back_pars,
                                                                 factors.get(10))],
                 np.asarray(back_path)),
        }
        ch = self.clubhouse
        o, i_ = outer_start(self.pattern), inner_start(self.pattern)
        phase_a = [(o, 0), (o, 8), (i_, 0), (i_, 8), *((o, i) for i in range(1, 8))]
        phase_b = [(i_, i) for i in range(1, 8)]
        outcome = {"inner": False}
        placed: dict[int, ElasticHole] = {}
        checks = {1: 0, 10: 0}
        nodes = {1: 0, 10: 0}

        def exhausted(start: int) -> bool:
            return checks[start] >= CHECK_BUDGET_PER_NINE or nodes[start] >= NODE_BUDGET_PER_NINE

        def point(cp: ControlPoint) -> np.ndarray:
            return np.array([cp.x, cp.y])

        def level_for(start_order: int, index: int) -> _Level:
            pars, targets, _ = nines[start_order]
            last = len(pars) - 1
            order = start_order + index
            start = start_owner = end = end_owner = reach_point = heading = target_tee = None
            start_min = end_min = self.links.minimum
            reach = math.inf
            if index == 0:
                start, start_min = ch, self.links.clubhouse_min
            elif index != last:
                before = placed[order - 1]
                start, start_owner = point(before.green), order - 1
                tail = point(before.axis[-2])
                heading = math.atan2(start[1] - tail[1], start[0] - tail[0])
            if index == last:
                end, end_min = ch, self.links.clubhouse_min
                target_tee = targets[last - 1]
            elif index == last - 1:
                end, end_owner = point(placed[start_order + last].tee), order + 1
            elif index >= RETURN_BOUND_FROM:
                reach_point = point(placed[start_order + last].tee)
                reach = return_reach(pars, index, self.links.maximum)
            bridge = {}
            if index == last - 2:
                bridge = {"bridge_end": point(placed[start_order + last].tee),
                          "bridge_par": pars[last - 1], "bridge_owner": start_order + last}
            return _Level(order, index, start, start_min, start_owner, end, end_min, end_owner,
                          reach_point, reach, heading, targets[index], target_tee, **bridge)

        def links_for(level: _Level, hole: ElasticHole):
            links, mins = [], []
            if level.start is not None:
                owners = (level.order,) if level.start_owner is None else (level.start_owner, level.order)
                links.append(PlannedLink((float(level.start[0]), float(level.start[1])),
                                         (hole.tee.x, hole.tee.y), owners))
                mins.append(level.start_min)
            if level.end is not None:
                owners = (level.order,) if level.end_owner is None else (level.order, level.end_owner)
                links.append(PlannedLink((hole.green.x, hole.green.y),
                                         (float(level.end[0]), float(level.end[1])), owners))
                mins.append(level.end_min)
            return tuple(links), tuple(mins)

        def recurse(levels: list[tuple[int, int]], position: int, used: list[np.ndarray]) -> bool:
            if position == len(levels):
                if levels is phase_a:
                    # nine extérieur complet et ancrages du nine intérieur
                    # posés : ses trous intermédiaires sont cherchés UNE fois ;
                    # un échec termine la tentative (la relance s'en charge)
                    outcome["inner"] = recurse(phase_b, 0, used)
                return True
            start_order, index = levels[position]
            if exhausted(start_order):
                # anchors_done n'est levé qu'après ce contrôle : une coupure
                # à l'entrée de la position 4 laisse aussi les ancrages en échec
                if levels is phase_a and (position < 4 or not self.anchors_done):
                    self.anchor_truncated = True
                return False
            anchoring = levels is phase_a and position < 4
            nodes[start_order] += 1
            self.nodes += 1
            depth = position if levels is phase_a else len(phase_a) + position
            self.deepest[start_order] = max(self.deepest.get(start_order, 0), depth)
            if levels is phase_a and position >= 4:
                self.anchors_done = True      # les quatre ancrages ont été posés
            pars, _, path_arr = nines[start_order]
            level = level_for(start_order, index)
            explored = examined = 0
            candidates = self.candidates(level, pars[index], used, path_arr)
            for hole in candidates:
                if examined >= EXAMINED_PER_NODE or exhausted(start_order):
                    self.anchor_truncated |= anchoring
                    return False
                examined += 1
                links, mins = links_for(level, hole)
                checks[start_order] += 1
                kind = self.partial.check(hole, links, mins)
                if kind is not None:
                    self.rejections[kind] += 1
                    continue
                self.partial.push(hole, links)
                placed[hole.order] = hole
                new_used = used + [point(hole.tee), point(hole.green)]
                if levels is phase_a and position < 3 and not anchors_still_fit(position, new_used):
                    # anticipation : ce trou d'ancrage ne laisse plus aucun
                    # candidat à un ancrage restant (ex. 10 qui prend l'emprise
                    # du 18) — rejeté sans être compté comme enfant exploré
                    self.rejections["anchor_lookahead"] += 1
                    del placed[hole.order]
                    self.partial.pop()
                    continue
                if index == len(pars) - 3 and not bridge_still_fits(start_order, new_used):
                    # anticipation : le trou-pont (8 / 17) n'a plus aucun
                    # candidat une fois ce trou posé
                    self.rejections["bridge_lookahead"] += 1
                    del placed[hole.order]
                    self.partial.pop()
                    continue
                if recurse(levels, position + 1, new_used):
                    return True
                del placed[hole.order]
                self.partial.pop()
                explored += 1
                if explored >= CHILDREN_PER_NODE:
                    # coupure seulement s'il restait au moins un candidat
                    # (le générateur est sans effet de bord : rien n'est contrôlé)
                    if anchoring and next(candidates, None) is not None:
                        self.anchor_truncated = True
                    return False
            return False

        def anchors_still_fit(position: int, used: list[np.ndarray]) -> bool:
            """Chaque ancrage pas encore posé garde au moins un candidat
            (pré-filtres : condition nécessaire)."""
            for start_order, index in phase_a[position + 1:4]:
                pars, _, path_arr = nines[start_order]
                level = level_for(start_order, index)
                if next(iter(self.candidates(level, pars[index], used, path_arr)), None) is None:
                    return False
            return True

        def bridge_still_fits(start_order: int, used: list[np.ndarray]) -> bool:
            pars, _, path_arr = nines[start_order]
            index = len(pars) - 2
            level = level_for(start_order, index)
            return next(iter(self.candidates(level, pars[index], used, path_arr)), None) is not None

        self.budget_used = (checks, nodes)
        self.outer_done = recurse(phase_a, 0, [])
        if not self.outer_done or not outcome["inner"]:
            return None
        return ([placed[order] for order in range(1, 10)],
                [placed[order] for order in range(10, 19)])


AnchorCapacity = dict[int, frozenset[int]]


def iter_plans(seed: int, width: float = MAP_WIDTH, height: float = MAP_HEIGHT,
               capacity: Callable[[str, Point, int], AnchorCapacity] | None = None,
               pattern: str = "muirfield", clubhouses: int | None = None,
               ) -> Iterator[tuple[tuple[int, int, int], Plan | None]]:
    """Plan de base puis relances : angle de départ, permutation des pars,
    position du clubhouse (dans cet ordre d'imbrication).

    ``capacity(edge, clubhouse, direction)`` donne, pour chaque trou
    d'ancrage (1, 9, 10, 18), les pars qui tiennent dans son cône à cette
    position de clubhouse. Les permutations de pars sont tirées sous cette
    contrainte ; si aucune n'est possible, le plan est ``None`` (non tenté).
    Sans contrainte active, les plans sont identiques à ceux du round A.

    Positions de clubhouse 0, 1, 2… jusqu'à ``clubhouses`` (défaut
    ``MAX_CLUBHOUSE_POSITIONS``) ; l'appelant arrête l'itération quand son
    plafond de tentatives est atteint. Un clubhouse infaisable (``None``)
    ne produit qu'UNE entrée : ``order_nine`` ne renvoie ``None`` qu'après
    une énumération exhaustive qui ne dépend que des nombres de par 3 / par 5
    et de la capacité des cônes, ni de la permutation ni de l'angle."""
    rng = np.random.default_rng([seed, 7])
    base_edge, base_ch = place_clubhouse(rng, width, height)
    direction = 1 if rng.random() < 0.5 else -1
    (f3, f5), (b3, b5) = draw_par_counts(rng)
    base_pars = (order_nine(f3, f5, rng), order_nine(b3, b5, rng))
    limit = MAX_CLUBHOUSE_POSITIONS if clubhouses is None else clubhouses
    for ch_index in range(limit):
        if ch_index == 0:
            edge, ch = base_edge, base_ch
        else:
            edge, ch = place_clubhouse(np.random.default_rng([seed, 11, ch_index]), width, height)
        fits = (capacity(edge, ch, direction) if capacity is not None
                else {order: frozenset((3, 4, 5)) for order in (1, 9, 10, 18)})

        def admissible(pars) -> bool:
            front, back = pars
            return (front[0] in fits[1] and front[-1] in fits[9]
                    and back[0] in fits[10] and back[-1] in fits[18])

        for perm_index, angle_index in product(range(PAR_PERMUTATIONS), range(len(START_ANGLES))):
            if perm_index == 0 and admissible(base_pars):
                front_pars, back_pars = base_pars
            else:
                seed_tail = (13, perm_index) if perm_index else (17, ch_index)
                prng = np.random.default_rng([seed, *seed_tail])
                front_pars = order_nine(f3, f5, prng, first=fits[1], last=fits[9])
                back_pars = order_nine(b3, b5, prng, first=fits[10], last=fits[18])
            indices = (ch_index, perm_index, angle_index)
            if front_pars is None or back_pars is None:
                yield indices, None
                break                       # infaisable pour tout ce clubhouse
            outer_delta, inner_delta = START_ANGLES[angle_index]
            yield indices, Plan(edge, ch, direction, front_pars, back_pars, outer_delta,
                                inner_delta, ch_index, perm_index, angle_index, pattern)


def build_muirfield(seed: int, heightmap: np.ndarray | None = None, *,
                    width: float = MAP_WIDTH, height: float = MAP_HEIGHT,
                    rules: ValidationRules | None = None,
                    pattern: str = "muirfield", width_mode: str = "variable",
                    target_mode: str = "uniform", path_mode: str = "ring") -> MuirfieldResult:
    """Alias historique de ``build_course`` (patron ``muirfield`` par défaut)."""
    return build_course(seed, pattern, heightmap, width=width, height=height, rules=rules,
                        width_mode=width_mode, target_mode=target_mode, path_mode=path_mode)


def build_course(seed: int, pattern: str = "muirfield", heightmap: np.ndarray | None = None, *,
                 width: float = MAP_WIDTH, height: float = MAP_HEIGHT,
                 rules: ValidationRules | None = None,
                 width_mode: str = "variable",
                 target_mode: str = "uniform", path_mode: str = "ring") -> MuirfieldResult:
    """Parcours valide pour (seed, patron), ou ``MuirfieldRoutingError``.

    ``pattern`` est un paramètre explicite, au même titre que la seed :
    ``muirfield`` (front extérieur, back intérieur), ``muirfield_inverse``
    (front intérieur, back extérieur) ou ``random`` (patron tiré de façon
    déterministe à partir de la seed, cf. ``resolve_pattern``).

    ``width_mode`` : ``variable`` (round C1, défaut) — chaque trou tire sa
    largeur dans la plage de son par (``hole_width_fractions``) ; ``min`` —
    largeur minimale du par, comportement des rounds A–B.

    ``target_mode`` : ``uniform`` (défaut) — cibles des greens à pas
    nominal régulier le long de l'anneau ; ``irregular`` (round R2b M1) —
    chaque pas multiplié par un facteur seedé (``target_jitter_factors``),
    total conservé.

    ``path_mode`` : ``ring`` (défaut) — chemins cibles sur les anneaux ;
    ``lobed`` (round R2b M2) — le chemin cible du SEUL nine intérieur
    reçoit des lobes radiaux seedés (``lobe_parameters``,
    ``lobed_inner_path``) ; il sert aux cibles des greens et au départage
    des coudes. Anneaux, repère du clubhouse, couloir, cônes et capacité
    des ancrages restent calculés sur l'anneau. En mode ``lobed``, la taille
    de carte est validée en amont (``check_lobe_room``) : ``ValueError``
    immédiate si la carte est trop petite pour les lobes, avant tout calcul.

    Le résultat renvoyé a TOUJOURS zéro violation ``validate(layout, rules)`` ;
    les plages de liaison sont dérivées de ``rules`` (``link_bounds``)."""
    requested = pattern
    pattern = resolve_pattern(seed, pattern)
    if width_mode not in WIDTH_MODES:
        raise ValueError(f"width_mode inconnu : {width_mode!r} (attendu : {', '.join(WIDTH_MODES)})")
    fractions = hole_width_fractions(seed) if width_mode == "variable" else None
    if target_mode not in TARGET_MODES:
        raise ValueError(f"target_mode inconnu : {target_mode!r} "
                         f"(attendu : {', '.join(TARGET_MODES)})")
    target_factors = target_jitter_factors(seed) if target_mode == "irregular" else None
    if path_mode not in PATH_MODES:
        raise ValueError(f"path_mode inconnu : {path_mode!r} (attendu : {', '.join(PATH_MODES)})")
    if path_mode == "lobed":
        check_lobe_room(width, height)
    lobes = lobe_parameters(seed) if path_mode == "lobed" else None
    started = time.perf_counter()
    timings: dict[str, float] = {}
    if heightmap is None:
        heightmap = load_terrain(seed, int(width), int(height))
    if heightmap.shape != (int(height), int(width)):
        raise ValueError(f"relief {heightmap.shape}, carte attendue {int(height)}×{int(width)}")
    timings["terrain"] = time.perf_counter() - started
    rules = rules or ValidationRules(width=width, height=height)
    links = link_bounds(rules)

    t0 = time.perf_counter()
    green_sites = build_sites(heightmap, seed, "green")
    tee_sites = build_sites(heightmap, seed, "tee")
    timings["sites"] = time.perf_counter() - t0

    t0 = time.perf_counter()
    attempts: list[dict] = []
    def make_search(edge: str, clubhouse: Point, front_path: list[Point],
                    back_path: list[Point]) -> _Search:
        outer_path = front_path if outer_start(pattern) == 1 else back_path
        frame = clubhouse_frame(edge, clubhouse, outer_path, width, height)
        return _Search(
            width=width, height=height, tees=tee_sites, greens=green_sites, frame=frame,
            partial=PartialLayout(rules, clubhouse),
            outer_tee_ok=~frame.in_corridor(tee_sites.points),
            outer_green_ok=~frame.in_corridor(green_sites.points),
            links=links, pattern=pattern, width_fractions=fractions,
            target_factors=target_factors,
        )

    def capacity(edge: str, clubhouse: Point, direction: int) -> AnchorCapacity:
        _, _, front_path, back_path = nine_paths(clubhouse, direction, width, height,
                                                 pattern=pattern)
        probe = make_search(edge, clubhouse, front_path, back_path)
        return {order: frozenset(par for par in (3, 4, 5)
                                 if probe.anchor_fits(order, par,
                                                      front_path if order <= 9 else back_path))
                for order in (1, 9, 10, 18)}

    outer_name = "front" if outer_start(pattern) == 1 else "back"
    inner_name = "back" if outer_name == "front" else "front"
    # Clés d'échec PROUVÉ → indices de la tentative qui l'a prouvé :
    # - (clubhouse, pars des trous 1/9/10/18) : ``echec_ancrages`` sans
    #   aucune coupure pendant la pose des ancrages. L'angle ne change que
    #   l'ORDRE des candidats d'ancrage (cibles, départage des coudes), jamais
    #   leur ensemble ; la permutation n'en voit que ces quatre pars. Une
    #   recherche exhaustive échoue donc pour toute variante de même clé.
    # - (clubhouse, angle, pars complets) : plan strictement identique,
    #   recherche déterministe.
    proven_anchors: dict[tuple, tuple[int, int, int]] = {}
    tried_plans: dict[tuple, tuple[int, int, int]] = {}
    skipped: list[dict] = []

    def skip(plan: Plan, reason: str, key: dict, proof: tuple[int, int, int]) -> None:
        skipped.append({"clubhouse_index": plan.clubhouse_index,
                        "permutation_index": plan.permutation_index,
                        "angle_index": plan.angle_index, "reason": reason, "key": key,
                        "proven_by": list(proof)})

    for indices, plan in iter_plans(seed, width, height, capacity, pattern):
        if len(attempts) >= MAX_ATTEMPTS:      # garde-fou (l'arrêt normal est plus bas)
            break
        if plan is None:
            # une seule entrée par clubhouse infaisable (iter_plans passe au suivant)
            attempts.append({"clubhouse_index": indices[0], "permutation_index": indices[1],
                             "angle_index": indices[2], "status": "infaisable_ancrage",
                             "checks": 0, "nodes": 0})
            if len(attempts) >= MAX_ATTEMPTS:
                break
            continue
        anchor_pars = (plan.front_pars[0], plan.front_pars[-1],
                       plan.back_pars[0], plan.back_pars[-1])
        anchor_key = (plan.clubhouse_index, anchor_pars)
        plan_key = (plan.clubhouse_index, plan.angle_index, plan.front_pars, plan.back_pars)
        if anchor_key in proven_anchors:
            skip(plan, "echec_ancrages_prouve",
                 {"clubhouse_index": plan.clubhouse_index, "anchor_pars": list(anchor_pars)},
                 proven_anchors[anchor_key])
            continue
        if plan_key in tried_plans:
            skip(plan, "plan_identique",
                 {"clubhouse_index": plan.clubhouse_index, "angle_index": plan.angle_index,
                  "front_pars": list(plan.front_pars), "back_pars": list(plan.back_pars)},
                 tried_plans[plan_key])
            continue
        outer, inner, front_ring, back_ring = nine_paths(
            plan.clubhouse, plan.direction, width, height, plan.outer_delta_deg,
            plan.inner_delta_deg, pattern)
        front_path, back_path = front_ring, back_ring
        if lobes is not None:
            lobed = lobed_inner_path(plan.clubhouse, plan.direction, width, height,
                                     plan.inner_delta_deg, lobes)
            if outer_start(pattern) == 1:
                back_path = lobed
            else:
                front_path = lobed
        # repère du clubhouse : chemin extérieur (identique dans les deux modes)
        search = make_search(plan.edge, plan.clubhouse, front_ring, back_ring)
        routed = search.route_course(plan.front_pars, plan.back_pars, front_path, back_path)
        front, back = routed if routed is not None else (None, None)
        layout = violations = None
        if routed is not None:
            ch = ControlPoint(*plan.clubhouse)
            layout = CourseLayout(
                seed=seed, width=width, height=height, clubhouse=ch,
                front=NineLayout.from_holes(1, ch, tuple(front)),
                back=NineLayout.from_holes(10, ch, tuple(back)),
            )
            t1 = time.perf_counter()
            violations = tuple(validate(layout, rules))
            timings["validate"] = time.perf_counter() - t1
        if routed is None:
            # phase atteinte : ancrages (1/9/10/18), milieu du nine extérieur
            # (phase A), milieu du nine intérieur (phase B)
            status = ("echec_ancrages" if not search.anchors_done
                      else f"echec_{outer_name}" if not search.outer_done
                      else f"echec_{inner_name}")
        else:
            # filet de sécurité : un layout que l'oracle refuse n'est jamais
            # renvoyé, on passe au plan suivant
            status = "succes" if not violations else "echec_validate"
        attempts.append({
            "clubhouse_index": plan.clubhouse_index, "permutation_index": plan.permutation_index,
            "angle_index": plan.angle_index, "edge": plan.edge, "pattern": pattern,
            "status": status, "anchor_truncated": search.anchor_truncated,
            "checks": search.partial.checks, "nodes": search.nodes,
            "rejections": dict(sorted(search.rejections.items())),
            "deepest": dict(search.deepest),
            "violations": dict(sorted(Counter(v.kind for v in violations or ()).items())),
        })
        tried_plans[plan_key] = indices
        if status == "echec_ancrages" and not search.anchor_truncated:
            proven_anchors.setdefault(anchor_key, indices)
        if status != "succes":
            if len(attempts) >= MAX_ATTEMPTS:  # plafond de tentatives réelles atteint
                break
            continue
        timings["routing"] = time.perf_counter() - t0      # validations comprises
        return MuirfieldResult(
            seed=seed, width=width, height=height, layout=layout, violations=violations,
            plan=plan, outer_ring=tuple(outer), inner_ring=tuple(inner),
            front_path=tuple(front_path), back_path=tuple(back_path),
            attempts=tuple(attempts), elapsed_seconds=time.perf_counter() - started,
            timings=timings, requested_pattern=requested, width_mode=width_mode,
            target_mode=target_mode, path_mode=path_mode,
            front_ring_path=tuple(front_ring), back_ring_path=tuple(back_ring), lobes=lobes,
            skipped=tuple(skipped),
        )
    # plafond atteint, ou positions de clubhouse épuisées
    raise MuirfieldRoutingError(seed, attempts, skipped)
