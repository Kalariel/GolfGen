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

Construction (R2) : pour chaque nine, recherche en profondeur trou par trou,
dans l'ordre premier trou, DERNIER trou (ancré : green à liaison du
clubhouse), puis trous 2 à 8 qui doivent relier le premier green au tee du
dernier trou. À chaque niveau, les couples (tee, green) faisables — tee à 12–45 du point
courant (18–45 depuis le clubhouse), longueur dans la plage du par (tir
droit ou 1 dogleg ≤ 55°) — sont triés par score (distance à la cible −
qualité des sites − nouveauté de direction) puis passés aux contrôles en
ligne de ``partial_checks`` contre TOUS les trous déjà posés ; au plus
``CHILDREN_PER_NODE`` enfants valides sont explorés par niveau, dans la
limite de ``CHECK_BUDGET_PER_NINE`` contrôles et ``NODE_BUDGET_PER_NINE``
nœuds. Pour les trous 6–8 (15–17), une borne de faisabilité de retour élimine
les greens d'où le tee du dernier trou (ancré, donc le clubhouse) n'est plus
atteignable avec les trous restants ; le trou 8 (17) doit finir à liaison de
ce tee, le trou 9 (18) à liaison du clubhouse. Des pré-filtres vectorisés
(conditions nécessaires des contrôles) écartent d'abord les candidats
évidemment en collision. En cas d'échec : relances bon
marché (angle de départ, puis permutation des pars, puis position du
clubhouse). Aucune règle n'est jamais assouplie : échec explicite sinon.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from itertools import product
import math
import time
from typing import Iterator

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
from experiments.elastic_routing.partial_checks import Obstacles, PartialLayout, PlannedLink
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
CLUBHOUSE_POSITIONS = 3             # relances par position de clubhouse

# Secteur réservé au clubhouse (angles φ dans le repère local du clubhouse)
ANCHOR_FRONT_MIN_DEG = 58.0
ANCHOR_BACK_MIN_DEG = 1.0
ANCHOR_BACK_MAX_DEG = 32.0
CORRIDOR_HALF_DEG = 45.0
CORRIDOR_EXTRA = 30.0               # le couloir dépasse l'anneau intérieur de 30 blocs

LINK_MIN, LINK_MAX = 12.0, 45.0
CLUBHOUSE_LINK_MIN = 18.0           # > rayon dégagé (10) + demi-fairway
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


class MuirfieldRoutingError(RuntimeError):
    """Aucune relance n'a produit de parcours valide (aucune règle assouplie)."""

    def __init__(self, seed: int, attempts: list[dict]):
        super().__init__(f"seed {seed} : échec après {len(attempts)} tentative(s)")
        self.seed = seed
        self.attempts = attempts


@dataclass(frozen=True, slots=True)
class Plan:
    edge: str
    clubhouse: Point
    direction: int
    front_pars: tuple[int, ...]
    back_pars: tuple[int, ...]
    front_delta_deg: float
    back_delta_deg: float
    clubhouse_index: int
    permutation_index: int
    angle_index: int


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
               height: float = MAP_HEIGHT, front_delta_deg: float = START_ANGLES[0][0],
               back_delta_deg: float = START_ANGLES[0][1]):
    """Anneaux complets (rendu) et chemins cibles des deux nines."""
    center = (width / 2, height / 2)
    theta_ch = math.atan2(clubhouse[1] - center[1], clubhouse[0] - center[0])
    (ox, oy), (ix, iy) = ring_semi_axes(width, height)
    outer = ring_arc(0.0, 2 * math.pi, ox, oy, center)
    inner = ring_arc(0.0, 2 * math.pi, ix, iy, center)
    delta = math.radians(front_delta_deg)
    delta_b = math.radians(back_delta_deg)
    front = [clubhouse, *ring_arc(theta_ch + direction * delta,
                                  direction * (2 * math.pi - 2 * delta), ox, oy, center), clubhouse]
    back = [clubhouse, *ring_arc(theta_ch - direction * delta_b,
                                 -direction * (2 * math.pi - 2 * delta_b), ix, iy, center), clubhouse]
    return outer, inner, front, back


@dataclass(frozen=True, slots=True)
class ClubhouseFrame:
    """Repère local : ``normal`` entrante, ``side`` = tangente vers le trou 1."""

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


def clubhouse_frame(edge: str, clubhouse: Point, front_path: list[Point],
                    width: float, height: float) -> ClubhouseFrame:
    normal = {"N": (0.0, 1.0), "S": (0.0, -1.0), "W": (1.0, 0.0), "E": (-1.0, 0.0)}[edge]
    tangent = (-normal[1], normal[0])
    first = front_path[1]
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


def anchor_bounds(order: int) -> tuple[float, float] | None:
    """Cône (φ min, φ max) imposé à l'axe d'un trou d'ancrage, sinon None."""
    return {
        1: (ANCHOR_FRONT_MIN_DEG, 180.0),
        9: (-180.0, -ANCHOR_FRONT_MIN_DEG),
        10: (-ANCHOR_BACK_MAX_DEG, -ANCHOR_BACK_MIN_DEG),
        18: (ANCHOR_BACK_MIN_DEG, ANCHOR_BACK_MAX_DEG),
    }.get(order)


# ----------------------------------------------------------------------
# Pars
# ----------------------------------------------------------------------

def par_sequence_ok(pars) -> bool:
    """Règle dure : jamais 3 par 5 ni 3 par 3 consécutifs dans un nine."""
    return not any(pars[i] == pars[i + 1] == pars[i + 2] and pars[i] in (3, 5)
                   for i in range(len(pars) - 2))


def par_sequence_penalty(pars) -> int:
    """Règle souple : éviter deux par 5 consécutifs et un nine qui commence
    par un par 3."""
    return (sum(1 for a, b in zip(pars, pars[1:]) if a == b == 5)
            + (1 if pars[0] == 3 else 0))


def draw_par_counts(rng: np.random.Generator) -> tuple[tuple[int, int], tuple[int, int]]:
    """(par 3, par 5) du front et du back : quota 4/10/4, chaque nombre par
    nine dans [1, 3] ; répartition tirée par la seed."""
    p3_front = int(rng.integers(1, 4))
    p5_front = int(rng.integers(1, 4))
    return ((p3_front, p5_front),
            (GLOBAL_PAR_QUOTA[3] - p3_front, GLOBAL_PAR_QUOTA[5] - p5_front))


def order_nine(p3: int, p5: int, rng: np.random.Generator, tries: int = 200) -> tuple[int, ...]:
    """Ordre seedé respectant la règle dure, pénalité souple minimale."""
    base = [3] * p3 + [5] * p5 + [4] * (9 - p3 - p5)
    best: tuple[int, int, tuple[int, ...]] | None = None
    for index in range(tries):
        pars = tuple(int(p) for p in rng.permutation(base))
        if not par_sequence_ok(pars):
            continue
        penalty = par_sequence_penalty(pars)
        if penalty == 0:
            return pars
        if best is None or penalty < best[0]:
            best = (penalty, index, pars)
    if best is None:
        raise ValueError("aucun ordre de pars ne respecte la règle de séquence")
    return best[2]


def draw_pars(rng: np.random.Generator) -> tuple[tuple[int, ...], tuple[int, ...]]:
    (f3, f5), (b3, b5) = draw_par_counts(rng)
    return order_nine(f3, f5, rng), order_nine(b3, b5, rng)


def _nominal_length(par: int) -> float:
    spec = PAR_SPECS[par]
    return (spec.length_min + spec.length_max) / 2.0


def green_targets(path: list[Point], pars: tuple[int, ...]) -> list[Point]:
    """Cible douce de chaque green : fraction de longueur nominale cumulée."""
    cumulative = _polyline_cumulative(path)
    total = sum(LINK_NOMINAL + _nominal_length(par) for par in pars) + LINK_NOMINAL
    running, targets = 0.0, []
    for par in pars:
        running += LINK_NOMINAL + _nominal_length(par)
        targets.append(point_at(path, cumulative, running / total * cumulative[-1]))
    return targets


def return_reach(pars: tuple[int, ...], index: int) -> float:
    """Borne de faisabilité de retour : distance maximale entre le green du
    trou ``index`` et le tee (déjà ancré) du dernier trou du nine, encore
    rattrapable par les trous intermédiaires restants (liaisons et longueurs
    maximales mises bout à bout en ligne droite)."""
    last = len(pars) - 1
    return (math.fsum(LINK_MAX + PAR_SPECS[par].length_max for par in pars[index + 1:last])
            + LINK_MAX)


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


def _dogleg_point(tee: np.ndarray, green: np.ndarray, h: float, side: int) -> np.ndarray:
    chord = green - tee
    norm = np.hypot(*chord)
    normal = np.array([-chord[1], chord[0]]) / norm
    return tee + DOGLEG_FRACTION * chord + side * h * normal


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


@dataclass
class _Search:
    """Contexte d'une tentative : sites, cadre clubhouse, layout partiel."""

    width: float
    height: float
    tees: Sites
    greens: Sites
    frame: ClubhouseFrame
    partial: PartialLayout
    front_tee_ok: np.ndarray
    front_green_ok: np.ndarray
    checks_limit: int = 0
    nodes_limit: int = 0
    nodes: int = 0
    rejections: Counter = field(default_factory=Counter)
    deepest: dict[int, int] = field(default_factory=dict)

    @property
    def clubhouse(self) -> np.ndarray:
        return np.asarray(self.frame.origin)

    @property
    def exhausted(self) -> bool:
        return self.partial.checks >= self.checks_limit or self.nodes >= self.nodes_limit

    def _inside(self, point: np.ndarray, margin: float) -> bool:
        return bool(margin <= point[0] <= self.width - margin
                    and margin <= point[1] <= self.height - margin)

    def _in_anchor(self, order: int, points: np.ndarray) -> np.ndarray:
        bounds = anchor_bounds(order)
        if bounds is None:
            return np.ones(len(points), dtype=bool)
        phi = self.frame.phi_deg(points)
        return (phi >= bounds[0]) & (phi <= bounds[1])

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
        front = order <= 9
        obstacles = Obstacles.from_partial(self.partial)
        radius, gap = spec.width_min / 2.0, self.partial.rules.fairway_gap

        tee_ok = self._available(self.tees.points, self.front_tee_ok if front
                                 else np.ones(len(self.tees), dtype=bool), used)
        tee_ok &= self._in_anchor(order, self.tees.points)
        if level.start is not None:
            link = np.hypot(*(self.tees.points - level.start).T)
            tee_ok &= (link >= level.start_min) & (link <= LINK_MAX)
        tee_idx = np.flatnonzero(tee_ok)
        if len(tee_idx):
            pts = self.tees.points[tee_idx]
            keep = obstacles.points_clear(pts, radius, gap)
            if level.start is not None:
                keep &= obstacles.links_clear(level.start, pts, level.start_owner)
            tee_idx = tee_idx[keep]

        green_ok = self._available(self.greens.points, self.front_green_ok if front
                                   else np.ones(len(self.greens), dtype=bool), used)
        green_ok &= self._in_anchor(order, self.greens.points)
        if level.end is not None:
            link = np.hypot(*(self.greens.points - level.end).T)
            green_ok &= (link >= level.end_min) & (link <= LINK_MAX)
        if level.reach_point is not None:
            green_ok &= np.hypot(*(self.greens.points - level.reach_point).T) <= level.reach
        green_idx = np.flatnonzero(green_ok)
        if len(green_idx):
            pts = self.greens.points[green_idx]
            keep = obstacles.points_clear(pts, radius, gap)
            if level.end is not None:
                keep &= obstacles.links_clear(level.end, pts, level.end_owner)
            green_idx = green_idx[keep]
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
                                  width=spec.width_min)
                continue
            options = [_dogleg_point(tee, green, float(h[ti, gi]), side) for side in (1, -1)]
            options = [p for p in options
                       if self._inside(p, DOGLEG_EDGE_MARGIN) and self._in_anchor(order, p[None, :])[0]]
            options.sort(key=lambda p: float(np.min(np.hypot(*(path_arr - p).T))))
            for corner in options:
                yield ElasticHole(order=order, par=par, tee=tee_cp, green=green_cp,
                                  doglegs=(ControlPoint(float(corner[0]), float(corner[1])),),
                                  width=spec.width_min)

    def route_nine(self, start_order: int, pars: tuple[int, ...],
                   path: list[Point]) -> list[ElasticHole] | None:
        """Recherche en profondeur bornée ; laisse les trous posés si succès.

        Ordre des niveaux : premier trou (depuis le clubhouse), puis le
        DERNIER trou ancré (retour au clubhouse), puis les trous 2..8 qui
        doivent relier le premier green au tee du dernier trou.
        """
        targets = [np.asarray(t) for t in green_targets(path, pars)]
        path_arr = np.asarray(path)
        ch = self.clubhouse
        last = len(pars) - 1
        levels_order = [0, last, *range(1, last)]
        placed: dict[int, ElasticHole] = {}
        self.checks_limit = self.partial.checks + CHECK_BUDGET_PER_NINE
        self.nodes_limit = self.nodes + NODE_BUDGET_PER_NINE

        def point(cp: ControlPoint) -> np.ndarray:
            return np.array([cp.x, cp.y])

        def level_for(index: int) -> _Level:
            order = start_order + index
            start = start_owner = end = end_owner = reach_point = heading = target_tee = None
            start_min = end_min = LINK_MIN
            reach = math.inf
            if index == 0:
                start, start_min = ch, CLUBHOUSE_LINK_MIN
            elif index != last:
                before = placed[index - 1]
                start, start_owner = point(before.green), order - 1
                tail = point(before.axis[-2])
                heading = math.atan2(start[1] - tail[1], start[0] - tail[0])
            if index == last:
                end, end_min = ch, CLUBHOUSE_LINK_MIN
                target_tee = targets[last - 1]
            elif index == last - 1:
                end, end_owner = point(placed[last].tee), order + 1
            elif index >= RETURN_BOUND_FROM:
                reach_point = point(placed[last].tee)
                reach = return_reach(pars, index)
            return _Level(order, index, start, start_min, start_owner, end, end_min, end_owner,
                          reach_point, reach, heading, targets[index], target_tee)

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

        def recurse(position: int, used: list[np.ndarray]) -> bool:
            if position == len(levels_order):
                return True
            if self.exhausted:
                return False
            self.nodes += 1
            self.deepest[start_order] = max(self.deepest.get(start_order, 0), position)
            index = levels_order[position]
            level = level_for(index)
            explored = examined = 0
            for hole in self.candidates(level, pars[index], used, path_arr):
                if examined >= EXAMINED_PER_NODE or self.exhausted:
                    return False
                examined += 1
                links, mins = links_for(level, hole)
                kind = self.partial.check(hole, links, mins)
                if kind is not None:
                    self.rejections[kind] += 1
                    continue
                self.partial.push(hole, links)
                placed[index] = hole
                if recurse(position + 1, used + [point(hole.tee), point(hole.green)]):
                    return True
                del placed[index]
                self.partial.pop()
                explored += 1
                if explored >= CHILDREN_PER_NODE:
                    return False
            return False

        if not recurse(0, []):
            return None
        return [placed[index] for index in range(len(pars))]


def iter_plans(seed: int, width: float = MAP_WIDTH, height: float = MAP_HEIGHT) -> Iterator[Plan]:
    """Plan de base puis relances : angle de départ, permutation des pars,
    position du clubhouse (dans cet ordre d'imbrication)."""
    rng = np.random.default_rng([seed, 7])
    base_edge, base_ch = place_clubhouse(rng, width, height)
    direction = 1 if rng.random() < 0.5 else -1
    (f3, f5), (b3, b5) = draw_par_counts(rng)
    base_pars = (order_nine(f3, f5, rng), order_nine(b3, b5, rng))
    for ch_index, perm_index, angle_index in product(range(CLUBHOUSE_POSITIONS),
                                                     range(PAR_PERMUTATIONS),
                                                     range(len(START_ANGLES))):
        if ch_index == 0:
            edge, ch = base_edge, base_ch
        else:
            edge, ch = place_clubhouse(np.random.default_rng([seed, 11, ch_index]), width, height)
        if perm_index == 0:
            front_pars, back_pars = base_pars
        else:
            prng = np.random.default_rng([seed, 13, perm_index])
            front_pars, back_pars = order_nine(f3, f5, prng), order_nine(b3, b5, prng)
        front_delta, back_delta = START_ANGLES[angle_index]
        yield Plan(edge, ch, direction, front_pars, back_pars, front_delta, back_delta,
                   ch_index, perm_index, angle_index)


def build_muirfield(seed: int, heightmap: np.ndarray | None = None, *,
                    width: float = MAP_WIDTH, height: float = MAP_HEIGHT,
                    rules: ValidationRules | None = None) -> MuirfieldResult:
    """Parcours Muirfield valide pour la seed, ou ``MuirfieldRoutingError``."""
    started = time.perf_counter()
    timings: dict[str, float] = {}
    if heightmap is None:
        heightmap = load_terrain(seed, int(width), int(height))
    if heightmap.shape != (int(height), int(width)):
        raise ValueError(f"relief {heightmap.shape}, carte attendue {int(height)}×{int(width)}")
    timings["terrain"] = time.perf_counter() - started
    rules = rules or ValidationRules(width=width, height=height)

    t0 = time.perf_counter()
    green_sites = build_sites(heightmap, seed, "green")
    tee_sites = build_sites(heightmap, seed, "tee")
    timings["sites"] = time.perf_counter() - t0

    t0 = time.perf_counter()
    attempts: list[dict] = []
    for plan in iter_plans(seed, width, height):
        outer, inner, front_path, back_path = nine_paths(
            plan.clubhouse, plan.direction, width, height, plan.front_delta_deg, plan.back_delta_deg)
        frame = clubhouse_frame(plan.edge, plan.clubhouse, front_path, width, height)
        search = _Search(
            width=width, height=height, tees=tee_sites, greens=green_sites, frame=frame,
            partial=PartialLayout(rules, plan.clubhouse),
            front_tee_ok=~frame.in_corridor(tee_sites.points),
            front_green_ok=~frame.in_corridor(green_sites.points),
        )
        front = search.route_nine(1, plan.front_pars, front_path)
        back = search.route_nine(10, plan.back_pars, back_path) if front is not None else None
        attempts.append({
            "clubhouse_index": plan.clubhouse_index, "permutation_index": plan.permutation_index,
            "angle_index": plan.angle_index, "edge": plan.edge,
            "status": "succes" if back is not None else ("echec_back" if front is not None
                                                          else "echec_front"),
            "checks": search.partial.checks, "nodes": search.nodes,
            "rejections": dict(sorted(search.rejections.items())),
            "deepest": dict(search.deepest),
        })
        if back is None:
            continue
        timings["routing"] = time.perf_counter() - t0
        ch = ControlPoint(*plan.clubhouse)
        layout = CourseLayout(
            seed=seed, width=width, height=height, clubhouse=ch,
            front=NineLayout.from_holes(1, ch, tuple(front)),
            back=NineLayout.from_holes(10, ch, tuple(back)),
        )
        t1 = time.perf_counter()
        violations = tuple(validate(layout, rules))
        timings["validate"] = time.perf_counter() - t1
        return MuirfieldResult(
            seed=seed, width=width, height=height, layout=layout, violations=violations,
            plan=plan, outer_ring=tuple(outer), inner_ring=tuple(inner),
            front_path=tuple(front_path), back_path=tuple(back_path),
            attempts=tuple(attempts), elapsed_seconds=time.perf_counter() - started,
            timings=timings,
        )
    raise MuirfieldRoutingError(seed, attempts)
