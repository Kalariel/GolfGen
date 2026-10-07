"""Étape M, round R1 — routage Muirfield glouton (premier visuel).

Patron (comme le vrai Muirfield) : clubhouse sur un BORD de carte ; le front
fait une boucle extérieure dans un sens, le back une boucle intérieure en sens
inverse, tous deux partant du clubhouse et y revenant. Le front part le long
du bord d'un côté du clubhouse (trou 1) et revient le long du bord de l'autre
côté (trou 9) ; le back sort du clubhouse vers l'intérieur ENTRE les trous 1
et 9 (secteur angulaire réservé au clubhouse) et y revient.

Les anneaux sont des superellipses (carré arrondi, exposant ``RING_P``)
centrées sur la carte : cible extérieure pour le front, intérieure pour le
back. Chaque green reçoit une cible DOUCE : le point du chemin de son nine
(clubhouse → anneau → clubhouse) à la fraction de longueur cumulée nominale
de ce green dans le nine.

Construction GLOUTONNE trou par trou, sans retour arrière (R1) : depuis le
point courant (clubhouse ou green précédent), on choisit un tee à distance de
liaison 12–45 puis un green dont la longueur tombe dans la plage du par (tir
droit, ou 1 dogleg ≤ 55°). Score = distance à la cible + qualité des sites +
nouveauté de direction. Le dernier green d'un nine est choisi à distance de
liaison du clubhouse. Aucun contrôle de collision en ligne : ``validate()``
(règles finales) est appliqué à la fin et les violations sont seulement
rapportées — R1 n'est pas une porte de validité.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import math
import time

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
from experiments.elastic_routing.sites import Sites, build_sites, load_terrain


Point = tuple[float, float]

MAP_SIZE = 400.0
CLUBHOUSE_EDGE_INSET = 6.0          # clubhouse à 6 blocs à l'intérieur de son bord
CLUBHOUSE_ALONG = (0.3, 0.7)        # position le long du bord (fraction), tirée par la seed
RING_P = 5.0                        # exposant de superellipse (carré arrondi)
OUTER_INSET = 34.0                  # demi-côté anneau extérieur = 200 - 34
INNER_INSET = 112.0                 # demi-côté anneau intérieur = 200 - 112
FRONT_SECTOR_HALF_DEG = 9.0         # secteur réservé au clubhouse (front exclu)
BACK_SPOKE_HALF_DEG = 18.0          # sortie / retour du back sur l'anneau intérieur
RING_STEP_DEG = 0.5

LINK_MIN, LINK_MAX = 12.0, 45.0
CLUBHOUSE_LINK_MIN = 18.0           # > rayon dégagé (10) + demi-fairway
LINK_NOMINAL = 25.0                 # liaison nominale pour les fractions cibles
USED_POINT_CLEARANCE = 10.0         # un site trop près d'un tee/green déjà posé est consommé
DOGLEG_MAX_DEG = 55.0
DOGLEG_FRACTION = 0.6               # coude à 60 % de la corde
DOGLEG_LENGTH_SLACK = 2.0           # longueur visée = length_min + 2
DOGLEG_EDGE_MARGIN = 8.0

TARGET_SCALE = 25.0                 # 1 point de score = 25 blocs d'écart à la cible
QUALITY_WEIGHT = 0.5                # par site (tee, green)
NOVELTY_WEIGHT = 0.5                # bonus max pour un virage ≥ 90° vs le trou précédent


@dataclass(frozen=True, slots=True)
class HoleTrace:
    """Diagnostic d'un choix glouton."""

    order: int
    par: int
    target: Point
    tee_candidates: int
    green_candidates: int
    dogleg: bool
    target_distance: float
    fallback: str | None = None


@dataclass(frozen=True, slots=True)
class MuirfieldResult:
    seed: int
    layout: CourseLayout
    violations: tuple[Violation, ...]
    clubhouse_edge: str
    direction: int
    outer_ring: tuple[Point, ...]
    inner_ring: tuple[Point, ...]
    front_path: tuple[Point, ...]
    back_path: tuple[Point, ...]
    traces: tuple[HoleTrace, ...]
    elapsed_seconds: float
    timings: dict[str, float] = field(default_factory=dict)

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


def place_clubhouse(rng: np.random.Generator, size: float = MAP_SIZE) -> tuple[str, Point]:
    edge = EDGES[int(rng.integers(4))]
    along = float(rng.uniform(*CLUBHOUSE_ALONG)) * size
    inset = CLUBHOUSE_EDGE_INSET
    point = {"N": (along, inset), "S": (along, size - inset),
             "W": (inset, along), "E": (size - inset, along)}[edge]
    return edge, point


def superellipse_radius(theta: np.ndarray | float, semi_axis: float, p: float = RING_P):
    c, s = np.abs(np.cos(theta)), np.abs(np.sin(theta))
    return semi_axis * (c ** p + s ** p) ** (-1.0 / p)


def ring_arc(theta_start: float, sweep: float, semi_axis: float,
             center: Point = (MAP_SIZE / 2, MAP_SIZE / 2)) -> list[Point]:
    steps = max(2, int(abs(math.degrees(sweep)) / RING_STEP_DEG) + 1)
    thetas = theta_start + np.linspace(0.0, sweep, steps)
    radii = superellipse_radius(thetas, semi_axis)
    return [(center[0] + r * math.cos(t), center[1] + r * math.sin(t))
            for r, t in zip(radii, thetas)]


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


def nine_paths(clubhouse: Point, direction: int,
               size: float = MAP_SIZE) -> tuple[list[Point], list[Point], list[Point], list[Point]]:
    """Anneaux complets (pour le rendu) et chemins cibles des deux nines."""
    center = (size / 2, size / 2)
    theta_ch = math.atan2(clubhouse[1] - center[1], clubhouse[0] - center[0])
    outer_semi, inner_semi = size / 2 - OUTER_INSET, size / 2 - INNER_INSET
    outer = ring_arc(0.0, 2 * math.pi, outer_semi, center)
    inner = ring_arc(0.0, 2 * math.pi, inner_semi, center)
    delta = math.radians(FRONT_SECTOR_HALF_DEG)
    delta_b = math.radians(BACK_SPOKE_HALF_DEG)
    front = [clubhouse, *ring_arc(theta_ch + direction * delta,
                                  direction * (2 * math.pi - 2 * delta), outer_semi, center), clubhouse]
    back = [clubhouse, *ring_arc(theta_ch - direction * delta_b,
                                 -direction * (2 * math.pi - 2 * delta_b), inner_semi, center), clubhouse]
    return outer, inner, front, back


def in_front_sector(points: np.ndarray, clubhouse: Point, size: float = MAP_SIZE) -> np.ndarray:
    """Masque des points dans le secteur angulaire réservé au clubhouse."""
    center = np.array([size / 2, size / 2])
    theta_ch = math.atan2(clubhouse[1] - center[1], clubhouse[0] - center[0])
    angles = np.arctan2(points[:, 1] - center[1], points[:, 0] - center[0])
    diff = np.abs((angles - theta_ch + np.pi) % (2 * np.pi) - np.pi)
    return diff < math.radians(FRONT_SECTOR_HALF_DEG)


# ----------------------------------------------------------------------
# Pars
# ----------------------------------------------------------------------

def draw_pars(rng: np.random.Generator) -> tuple[tuple[int, ...], tuple[int, ...]]:
    """Quota global 4/10/4, par 3 et par 5 par nine dans [1, 3] ; répartition
    entre nines et ordre dans chaque nine tirés par la seed (aucun nine n'est
    favorisé)."""
    p3_front = int(rng.integers(1, 4))
    p5_front = int(rng.integers(1, 4))
    nines = []
    for p3, p5 in ((p3_front, p5_front),
                   (GLOBAL_PAR_QUOTA[3] - p3_front, GLOBAL_PAR_QUOTA[5] - p5_front)):
        pars = [3] * p3 + [5] * p5 + [4] * (9 - p3 - p5)
        nines.append(tuple(int(p) for p in rng.permutation(pars)))
    return nines[0], nines[1]


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


# ----------------------------------------------------------------------
# Glouton
# ----------------------------------------------------------------------

def _dogleg_offsets(chords: np.ndarray, length: float) -> tuple[np.ndarray, np.ndarray]:
    """Décalage latéral ``h`` du coude (à ``DOGLEG_FRACTION`` de la corde) qui
    donne la longueur ``length`` ; renvoie (h, déflexion en degrés)."""
    f = DOGLEG_FRACTION
    lo = np.zeros_like(chords)
    hi = np.full_like(chords, length)
    for _ in range(50):
        mid = (lo + hi) / 2
        total = np.hypot(f * chords, mid) + np.hypot((1 - f) * chords, mid)
        too_long = total > length
        hi = np.where(too_long, mid, hi)
        lo = np.where(too_long, lo, mid)
    h = (lo + hi) / 2
    with np.errstate(divide="ignore", invalid="ignore"):
        deflection = np.degrees(np.arctan2(h, f * chords) + np.arctan2(h, (1 - f) * chords))
    return h, deflection


def _dogleg_point(tee: np.ndarray, green: np.ndarray, h: float, side: int) -> np.ndarray:
    chord = green - tee
    norm = np.hypot(*chord)
    normal = np.array([-chord[1], chord[0]]) / norm
    return tee + DOGLEG_FRACTION * chord + side * h * normal


def _inside(point: np.ndarray, margin: float, size: float = MAP_SIZE) -> bool:
    return bool(margin <= point[0] <= size - margin and margin <= point[1] <= size - margin)


def _distance_to_path(point: np.ndarray, path: np.ndarray) -> float:
    return float(np.min(np.hypot(path[:, 0] - point[0], path[:, 1] - point[1])))


@dataclass
class _SitePool:
    sites: Sites
    available: np.ndarray

    def candidates(self) -> np.ndarray:
        return np.flatnonzero(self.available)

    def consume_near(self, point: np.ndarray, radius: float) -> None:
        dist = np.hypot(*(self.sites.points - point).T)
        self.available &= dist >= radius


def _route_nine(start_order: int, pars: tuple[int, ...], clubhouse: Point,
                path: list[Point], tees: _SitePool, greens: _SitePool,
                previous_heading: float | None,
                exclude_sector: bool) -> tuple[list[ElasticHole], list[HoleTrace]]:
    ch = np.asarray(clubhouse)
    path_arr = np.asarray(path)
    targets = green_targets(path, pars)
    holes: list[ElasticHole] = []
    traces: list[HoleTrace] = []
    current = ch
    heading = previous_heading
    tee_sector = in_front_sector(tees.sites.points, clubhouse) if exclude_sector else None
    green_sector = in_front_sector(greens.sites.points, clubhouse) if exclude_sector else None

    for index, par in enumerate(pars):
        order = start_order + index
        spec = PAR_SPECS[par]
        target = np.asarray(targets[index])
        last = index == len(pars) - 1
        fallback = None

        # -- tees à distance de liaison du point courant
        tee_idx = tees.candidates()
        if tee_sector is not None:
            tee_idx = tee_idx[~tee_sector[tee_idx]]
        tee_pts = tees.sites.points[tee_idx]
        link = np.hypot(*(tee_pts - current).T)
        link_min = CLUBHOUSE_LINK_MIN if index == 0 else LINK_MIN
        ok = (link >= link_min) & (link <= LINK_MAX)
        if not ok.any():
            fallback = "tee: aucun site à distance de liaison, plus proche retenu"
            ok = link >= link_min
            ok &= link <= link[ok].min() + 1e-9
        tee_idx, tee_pts = tee_idx[ok], tee_pts[ok]

        # -- greens accessibles depuis chaque tee ; pour le dernier trou du
        # nine, d'abord les seuls greens à distance de liaison du clubhouse
        all_greens = greens.candidates()
        if green_sector is not None:
            all_greens = all_greens[~green_sector[all_greens]]
        green_sets = [all_greens]
        if last:
            back_link = np.hypot(*(greens.sites.points[all_greens] - ch).T)
            near = (back_link >= CLUBHOUSE_LINK_MIN) & (back_link <= LINK_MAX)
            green_sets.insert(0, all_greens[near])
        for attempt, green_idx in enumerate(green_sets):
            green_pts = greens.sites.points[green_idx]
            chords = np.hypot(green_pts[None, :, 0] - tee_pts[:, None, 0],
                              green_pts[None, :, 1] - tee_pts[:, None, 1])
            straight = (chords >= spec.length_min) & (chords <= spec.length_max)
            h, deflection = _dogleg_offsets(chords, spec.length_min + DOGLEG_LENGTH_SLACK)
            dogleg = ((~straight) & (chords > 1.0) & (chords < spec.length_min)
                      & (deflection <= DOGLEG_MAX_DEG))
            feasible = straight | dogleg
            if feasible.any():
                if attempt > 0:
                    fallback = (fallback or "") + " green: aucun site à liaison du clubhouse atteignable"
                break
        else:
            raise RuntimeError(f"trou {order} : aucun couple tee/green de longueur par {par}")

        target_term = np.hypot(*(green_pts - target).T) / TARGET_SCALE
        quality = (QUALITY_WEIGHT * tees.sites.scores[tee_idx][:, None]
                   + QUALITY_WEIGHT * greens.sites.scores[green_idx][None, :])
        score = target_term[None, :] - quality
        if heading is not None:
            dx = green_pts[None, :, 0] - tee_pts[:, None, 0]
            dy = green_pts[None, :, 1] - tee_pts[:, None, 1]
            turn = np.abs((np.arctan2(dy, dx) - heading + np.pi) % (2 * np.pi) - np.pi)
            score = score - NOVELTY_WEIGHT * np.minimum(turn, np.pi / 2) / (np.pi / 2)
        score = np.where(feasible, score, np.inf)

        # meilleur couple dont le coude (si dogleg) peut rester dans la carte
        doglegs: tuple[ControlPoint, ...] = ()
        for flat in np.argsort(score, axis=None, kind="stable"):
            if not np.isfinite(score.flat[flat]):
                raise RuntimeError(f"trou {order} : aucun dogleg dans la carte")
            ti, gi = np.unravel_index(flat, score.shape)
            tee, green = tee_pts[ti], green_pts[gi]
            if straight[ti, gi]:
                break
            options = [_dogleg_point(tee, green, float(h[ti, gi]), side) for side in (1, -1)]
            options = [p for p in options if _inside(p, DOGLEG_EDGE_MARGIN)]
            if options:
                corner = min(options, key=lambda p: _distance_to_path(p, path_arr))
                doglegs = (ControlPoint(float(corner[0]), float(corner[1])),)
                break

        hole = ElasticHole(
            order=order, par=par,
            tee=ControlPoint(float(tee[0]), float(tee[1])),
            green=ControlPoint(float(green[0]), float(green[1])),
            doglegs=doglegs, width=spec.width_min,
        )
        holes.append(hole)
        traces.append(HoleTrace(
            order=order, par=par, target=(float(target[0]), float(target[1])),
            tee_candidates=int(len(tee_idx)), green_candidates=int(feasible[ti].sum()),
            dogleg=bool(doglegs), target_distance=float(np.hypot(*(green - target))),
            fallback=fallback.strip() if fallback else None,
        ))
        for point in (tee, green):
            tees.consume_near(point, USED_POINT_CLEARANCE)
            greens.consume_near(point, USED_POINT_CLEARANCE)
        last_from = np.array([hole.axis[-2].x, hole.axis[-2].y])
        heading = math.atan2(green[1] - last_from[1], green[0] - last_from[0])
        current = green
    return holes, traces


def build_muirfield(seed: int, heightmap: np.ndarray | None = None,
                    rules: ValidationRules | None = None) -> MuirfieldResult:
    """Parcours Muirfield glouton pour la seed (R1, violations tolérées)."""
    started = time.perf_counter()
    timings: dict[str, float] = {}
    if heightmap is None:
        heightmap = load_terrain(seed, int(MAP_SIZE), int(MAP_SIZE))
    timings["terrain"] = time.perf_counter() - started

    t0 = time.perf_counter()
    green_sites = build_sites(heightmap, seed, "green")
    tee_sites = build_sites(heightmap, seed, "tee")
    timings["sites"] = time.perf_counter() - t0

    t0 = time.perf_counter()
    rng = np.random.default_rng([seed, 7])
    edge, clubhouse = place_clubhouse(rng)
    direction = 1 if rng.random() < 0.5 else -1
    front_pars, back_pars = draw_pars(rng)
    outer, inner, front_path, back_path = nine_paths(clubhouse, direction)

    tees = _SitePool(tee_sites, np.ones(len(tee_sites), dtype=bool))
    greens = _SitePool(green_sites, np.ones(len(green_sites), dtype=bool))
    front_holes, front_traces = _route_nine(1, front_pars, clubhouse, front_path, tees, greens,
                                            None, exclude_sector=True)
    back_holes, back_traces = _route_nine(10, back_pars, clubhouse, back_path, tees, greens,
                                          None, exclude_sector=False)
    timings["routing"] = time.perf_counter() - t0

    ch = ControlPoint(*clubhouse)
    layout = CourseLayout(
        seed=seed, width=MAP_SIZE, height=MAP_SIZE, clubhouse=ch,
        front=NineLayout.from_holes(1, ch, tuple(front_holes)),
        back=NineLayout.from_holes(10, ch, tuple(back_holes)),
    )
    t0 = time.perf_counter()
    violations = tuple(validate(layout, rules or ValidationRules(width=MAP_SIZE, height=MAP_SIZE)))
    timings["validate"] = time.perf_counter() - t0
    return MuirfieldResult(
        seed=seed, layout=layout, violations=violations, clubhouse_edge=edge,
        direction=direction, outer_ring=tuple(outer), inner_ring=tuple(inner),
        front_path=tuple(front_path), back_path=tuple(back_path),
        traces=tuple(front_traces + back_traces),
        elapsed_seconds=time.perf_counter() - started, timings=timings,
    )
