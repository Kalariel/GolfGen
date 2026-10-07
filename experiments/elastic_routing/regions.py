"""Étape 3, r4 — squelette par RÉGIONS : chaque nine = bord d'une tache de cellules.

Remplace (à titre de comparaison, sans toucher ``skeleton.py``) le contour
d'un ARBRE de r3, dont chaque branche devenait un aller-retour à 2·offset
blocs (« effet jumeau »). Ici chaque nine longe le bord d'une RÉGION : la
largeur de la tache sépare l'aller du retour et leur donne des formes
différentes.

Mécanisme :

1. grille de ``GRID_N``×``GRID_N`` cellules de ``CELL`` blocs ; clubhouse
   sur un COIN de cellule (sommet de la grille) tiré par la seed ;
2. deux régions (front, back) amorcées chacune par un bloc
   ``w_min``×``w_min`` dont un coin est le clubhouse, dans deux quadrants
   opposés (elles ne se touchent qu'en ce point) ; croissance ALTERNÉE,
   un bloc ``w_min``×``w_min`` ENTIER par ajout. Un bloc est candidat
   s'il ne recouvre rien, s'appuie sur la région par un côté ENTIER
   (``w_min`` cellules adjacentes toutes dans la région : tout goulot fait
   donc ≥ ``w_min`` cellules), et n'est pas 8-adjacent à l'autre région
   (couloir ≥ 1 cellule partout sauf au clubhouse). Après ajout, la
   région doit rester sans trou (complément 4-connexe jusqu'au bord) et
   sans pincement diagonal (bord = un seul polygone simple) — vérifié à
   chaque ajout, candidat écarté sinon ;
3. biais de croissance seedé par nine : une « tête » avance selon un cap
   qui tourne (rayon de courbure seedé, signe seedé), avec une part
   d'ajouts uniformes qui épaississent irrégulièrement (lobes allongés,
   côtés non parallèles) et de rares bifurcations ;
4. parcours = bord de la région décalé VERS L'INTÉRIEUR de ``INSET`` blocs
   (``offset_closed_polyline`` de ``skeleton.py`` : jointure ronde aux
   coins rentrants, intersection vérifiée aux coins saillants), ouvert au
   clubhouse (coin saillant de la région) : part du clubhouse, longe le
   bord, y revient ;
5. budget : la croissance d'une région s'arrête dès que son parcours entre
   dans la fenêtre d'un nine (``nine_length_window``) ; tirage entier
   rejeté sinon (impasse, décalage invalide, dégagement < 23), au plus
   ``MAX_REGION_ATTEMPTS`` tirages, puis ``RegionGenerationError``.

Choix de ``CELL`` = 21 et ``INSET`` = 9 (voir ``check_parameters``) :
``INSET`` ≥ 9 (demi-fairway max) pour que le parcours reste dans la carte
même quand la région touche le bord ; contrainte la plus dure (a) pour
``w_min`` = 2 : 2·c − 2·9 ≥ 23 ⇒ c ≥ 20,5 ⇒ 21 (19 cellules = 399 blocs,
marge 0,5). ``w_min`` = 4 fait exception (``CELL_BY_W_MIN`` : c = 19,
régions de 76 blocs), c = 21 y étant infaisable dans une carte de 400.

Pas de dépendance à ``shapely`` ni ``scipy``. Toutes les longueurs sont en
blocs.
"""

from __future__ import annotations

import math
import random
import time
from collections import Counter
from dataclasses import dataclass

import numpy as np

from experiments.elastic_routing.geometry import segments_intersect
from experiments.elastic_routing.model import PAR_SPECS
from experiments.elastic_routing.skeleton import (
    LINK_CONSTRUCTION_MAX,
    LINK_CONSTRUCTION_MIN,
    MAP_SIZE,
    NINE_PAR_PATTERN,
    ContourOffsetError,
    _polyline_length,
    _sub_polyline,
    is_simple_polyline,
    offset_closed_polyline,
)


Point = tuple[float, float]
Cell = tuple[int, int]

CELL = 21.0
INSET = 9.0
FAIRWAY_GAP = 23.0                 # largeur max de fairway (18) + écart (5)
HALF_FAIRWAY_MAX = max(spec.width_max for spec in PAR_SPECS.values()) / 2.0
OPENING_HALF_GAP = 8.0             # arc retiré de part et d'autre du coin clubhouse
CLEARANCE_ARC_EXEMPT = 60.0        # portions voisines le long de l'arc : exemptées
SAMPLE_STEP = 3.0
ENDPOINT_MAX_DIST = 30.0           # extrémités d'un nine : à moins de 30 blocs du clubhouse
MAX_REGION_ATTEMPTS = 200
W_MIN_CHOICES = (2, 3, 4)
# c par w_min : 21 pour w_min 2 et 3 ; 19 pour w_min 4, car à c = 21 des
# régions de >= 84 blocs ne trouvent pas assez de périmètre dans la carte
# (mesuré : 0/30 seeds en 200 tirages, toutes en impasse) ; à c = 19
# (76 blocs) : 30/30, pire cas 51 tirages.
CELL_BY_W_MIN = {2: CELL, 3: CELL, 4: 19.0}

ALONG_GAIN = 3.0                   # préférence de la tête pour avancer (par bloc)
PERP_GAIN = 2.0                    # pénalité d'écart latéral à la tête (par bloc)


class RegionGenerationError(RuntimeError):
    """Aucun tirage valide en ``max_attempts`` : rejet borné et explicite."""

    def __init__(self, message: str, attempts: int, reasons: dict[str, int]):
        super().__init__(message)
        self.attempts = attempts
        self.reasons = reasons


class _Reject(Exception):
    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


def grid_size(cell: float = CELL) -> int:
    return int(MAP_SIZE // cell)


def grid_origin(cell: float = CELL) -> float:
    return (MAP_SIZE - grid_size(cell) * cell) / 2.0


def nine_length_window() -> tuple[float, float]:
    """Fenêtre de longueur d'un nine : 9 trous (``NINE_PAR_PATTERN``) + 8 liaisons
    + 2 stubs, comptés comme 10 tronçons de construction 12–60 (comme
    ``skeleton.make_config``)."""
    low = sum(PAR_SPECS[par].length_min for par in NINE_PAR_PATTERN) + 10 * LINK_CONSTRUCTION_MIN
    high = sum(PAR_SPECS[par].length_max for par in NINE_PAR_PATTERN) + 10 * LINK_CONSTRUCTION_MAX
    return (float(low), float(high))


def check_parameters(w_min: int, cell: float = CELL, inset: float = INSET) -> None:
    """Contraintes géométriques (a), (b), (c) du plan r4, plus la validité du décalage."""
    margin = grid_origin(cell)
    checks = {
        "(a) goulot: w_min*c - 2d >= 23": w_min * cell - 2.0 * inset >= FAIRWAY_GAP,
        "(b) couloir: c + 2d >= 23": cell + 2.0 * inset >= FAIRWAY_GAP,
        "(b') clubhouse: 2*sqrt(2)*d >= 23": 2.0 * math.sqrt(2.0) * inset >= FAIRWAY_GAP,
        "(c) carte: d + marge >= demi-fairway": inset + margin >= HALF_FAIRWAY_MAX,
        "decalage: c >= d (arete a un seul coin saillant)": cell >= inset,
        "grille: 2*w_min <= N": 2 * w_min <= grid_size(cell),
    }
    failed = [name for name, ok in checks.items() if not ok]
    if failed:
        raise ValueError(f"parametres invalides (w_min={w_min}, c={cell}, d={inset}) : {failed}")


# ----------------------------------------------------------------------
# Opérations sur la grille (masques numpy [i, j], i = colonne x, j = ligne y)
# ----------------------------------------------------------------------

def _integral(mask: np.ndarray) -> np.ndarray:
    n0, n1 = mask.shape
    table = np.zeros((n0 + 1, n1 + 1), dtype=np.int64)
    table[1:, 1:] = mask.astype(np.int64).cumsum(0).cumsum(1)
    return table


def _rect_sum(table: np.ndarray, i0, j0, wi: int, wj: int):
    return table[i0 + wi, j0 + wj] - table[i0, j0 + wj] - table[i0 + wi, j0] + table[i0, j0]


def _dilate8(mask: np.ndarray) -> np.ndarray:
    padded = np.pad(mask, 1)
    out = np.zeros_like(mask)
    n0, n1 = mask.shape
    for di in (0, 1, 2):
        for dj in (0, 1, 2):
            out |= padded[di:di + n0, dj:dj + n1]
    return out


def _candidates(region: np.ndarray, other: np.ndarray, w: int) -> np.ndarray:
    """Coins (i, j) des blocs w×w libres, hors halo 8-voisin de ``other``,
    appuyés sur ``region`` par un côté entier."""
    n = region.shape[0]
    free = ~(region | _dilate8(other))
    sf, sr = _integral(free), _integral(region)
    m = n - w + 1
    ii, jj = np.meshgrid(np.arange(m), np.arange(m), indexing="ij")
    fits = _rect_sum(sf, ii, jj, w, w) == w * w
    attached = np.zeros_like(fits)
    attached |= (ii >= 1) & (_rect_sum(sr, np.maximum(ii - 1, 0), jj, 1, w) == w)
    attached |= (ii + w <= n - 1) & (_rect_sum(sr, np.minimum(ii + w, n - 1), jj, 1, w) == w)
    attached |= (jj >= 1) & (_rect_sum(sr, ii, np.maximum(jj - 1, 0), w, 1) == w)
    attached |= (jj + w <= n - 1) & (_rect_sum(sr, ii, np.minimum(jj + w, n - 1), w, 1) == w)
    return np.argwhere(fits & attached)


def has_pinch(mask: np.ndarray) -> bool:
    """Deux cellules de la région qui ne se touchent que par un coin (bord non simple)."""
    p = np.pad(mask, 1)
    a, b, c, d = p[:-1, :-1], p[1:, :-1], p[:-1, 1:], p[1:, 1:]
    return bool(np.any((a & d & ~b & ~c) | (b & c & ~a & ~d)))


def has_hole(mask: np.ndarray) -> bool:
    """Vrai si le complément (bord de carte compris) n'est pas 4-connexe."""
    comp = ~np.pad(mask, 1)
    reached = np.zeros_like(comp)
    reached[0, :] = reached[-1, :] = reached[:, 0] = reached[:, -1] = True
    reached &= comp
    while True:
        grown = reached.copy()
        grown[1:, :] |= reached[:-1, :]
        grown[:-1, :] |= reached[1:, :]
        grown[:, 1:] |= reached[:, :-1]
        grown[:, :-1] |= reached[:, 1:]
        grown &= comp
        if np.array_equal(grown, reached):
            break
        reached = grown
    return bool(np.any(comp & ~reached))


def is_4_connected(mask: np.ndarray) -> bool:
    cells = np.argwhere(mask)
    if len(cells) == 0:
        return False
    seen = {tuple(cells[0])}
    stack = [tuple(cells[0])]
    n0, n1 = mask.shape
    while stack:
        i, j = stack.pop()
        for di, dj in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            a, b = i + di, j + dj
            if 0 <= a < n0 and 0 <= b < n1 and mask[a, b] and (a, b) not in seen:
                seen.add((a, b))
                stack.append((a, b))
    return len(seen) == len(cells)


def _length_estimate(mask: np.ndarray, cell: float, inset: float) -> float:
    """Longueur du parcours ouvert déduite du masque (bord rectilinéaire) :
    périmètre − 2d par coin saillant + (π/2)d par coin rentrant − ouverture."""
    p = np.pad(mask, 1).astype(np.int64)
    edges = int(np.sum(p[1:, :] != p[:-1, :]) + np.sum(p[:, 1:] != p[:, :-1]))
    s = p[:-1, :-1] + p[1:, :-1] + p[:-1, 1:] + p[1:, 1:]
    convex, reflex = int(np.sum(s == 1)), int(np.sum(s == 3))
    return edges * cell - 2.0 * inset * convex + 0.5 * math.pi * inset * reflex - 2.0 * OPENING_HALF_GAP


def trace_boundary(mask: np.ndarray, start: tuple[int, int]) -> list[tuple[int, int]]:
    """Bord de la région (sommets de grille, intérieur À GAUCHE pour la normale
    (-vy, vx)), points colinéaires retirés, commençant au sommet ``start``."""
    n0, n1 = mask.shape

    def inside(i: int, j: int) -> bool:
        return 0 <= i < n0 and 0 <= j < n1 and bool(mask[i, j])

    edges: dict[tuple[int, int], tuple[int, int]] = {}

    def add(a: tuple[int, int], b: tuple[int, int]) -> None:
        if a in edges:
            raise _Reject("bord_non_simple")
        edges[a] = b

    for i, j in np.argwhere(mask):
        i, j = int(i), int(j)
        if not inside(i, j - 1):
            add((i, j), (i + 1, j))
        if not inside(i + 1, j):
            add((i + 1, j), (i + 1, j + 1))
        if not inside(i, j + 1):
            add((i + 1, j + 1), (i, j + 1))
        if not inside(i - 1, j):
            add((i, j + 1), (i, j))
    if start not in edges:
        raise _Reject("clubhouse_hors_bord")
    loop = [start]
    current = edges.pop(start)
    while current != start:
        loop.append(current)
        current = edges.pop(current)
    if edges:
        raise _Reject("bord_multiple")
    corners = []
    m = len(loop)
    for k in range(m):
        a, b, c = loop[k - 1], loop[k], loop[(k + 1) % m]
        if (b[0] - a[0], b[1] - a[1]) != (c[0] - b[0], c[1] - b[1]):
            corners.append(b)
    if corners[0] != start:
        raise _Reject("clubhouse_pas_un_coin")
    return corners


# ----------------------------------------------------------------------
# Parcours (bord décalé vers l'intérieur, ouvert au clubhouse)
# ----------------------------------------------------------------------

def _to_world(vertex: tuple[float, float], cell: float) -> Point:
    origin = grid_origin(cell)
    return (origin + vertex[0] * cell, origin + vertex[1] * cell)


def _region_path(mask: np.ndarray, clubhouse_vertex: tuple[int, int], cell: float, inset: float):
    """(polygone de bord monde, boucle décalée fermée commençant au coin clubhouse,
    parcours ouvert, longueur du parcours)."""
    corners = trace_boundary(mask, clubhouse_vertex)
    polygon = [_to_world(v, cell) for v in corners]
    try:
        contour, source = offset_closed_polyline(polygon, inset, return_source_index=True)
    except ContourOffsetError as error:
        raise _Reject("decalage") from error
    at_club = [k for k, src in enumerate(source) if src == 0]
    if len(at_club) != 1:
        raise _Reject("coin_clubhouse")
    k = at_club[0]
    loop = contour[k:] + contour[:k]
    closed = loop + [loop[0]]
    total = _polyline_length(closed)
    path = _sub_polyline(closed, OPENING_HALF_GAP, total - OPENING_HALF_GAP)
    return polygon, loop, path, _polyline_length(path)


def resample_closed(loop: list[Point], step: float = SAMPLE_STEP) -> tuple[np.ndarray, np.ndarray, float]:
    """Points tous les ``step`` blocs le long d'une boucle fermée, leurs abscisses
    curvilignes et la longueur totale."""
    pts = np.asarray(list(loop) + [loop[0]], dtype=float)
    seg = np.hypot(*(pts[1:] - pts[:-1]).T)
    cum = np.concatenate(([0.0], np.cumsum(seg)))
    total = float(cum[-1])
    s = np.arange(0.0, total, step)
    xs = np.interp(s, cum, pts[:, 0])
    ys = np.interp(s, cum, pts[:, 1])
    return np.stack([xs, ys], axis=1), s, total


def loop_self_clearance(loop: list[Point], exempt_arc: float = CLEARANCE_ARC_EXEMPT,
                        step: float = SAMPLE_STEP) -> float:
    """Distance min entre points de la boucle séparés de plus de ``exempt_arc``
    blocs le long de l'arc (distance d'arc cyclique)."""
    pts, s, total = resample_closed(loop, step)
    diff = pts[:, None, :] - pts[None, :, :]
    dist = np.hypot(diff[..., 0], diff[..., 1])
    arc = np.abs(s[:, None] - s[None, :])
    arc = np.minimum(arc, total - arc)
    far = arc > exempt_arc
    return float(dist[far].min()) if np.any(far) else math.inf


def polylines_min_distance(a: list[Point], b: list[Point], step: float = SAMPLE_STEP) -> float:
    pa, _, _ = resample_closed(a, step)
    pb, _, _ = resample_closed(b, step)
    diff = pa[:, None, :] - pb[None, :, :]
    return float(np.hypot(diff[..., 0], diff[..., 1]).min())


def polylines_cross(a: list[Point], b: list[Point]) -> bool:
    """Intersection exacte entre deux polylignes ouvertes (préfiltre par boîtes)."""
    sa = [(a[k], a[k + 1]) for k in range(len(a) - 1)]
    sb = [(b[k], b[k + 1]) for k in range(len(b) - 1)]
    box_b = np.array([[min(p[0], q[0]), min(p[1], q[1]), max(p[0], q[0]), max(p[1], q[1])] for p, q in sb])
    for p, q in sa:
        x0, y0, x1, y1 = min(p[0], q[0]), min(p[1], q[1]), max(p[0], q[0]), max(p[1], q[1])
        near = np.nonzero((box_b[:, 0] <= x1) & (box_b[:, 2] >= x0) & (box_b[:, 1] <= y1) & (box_b[:, 3] >= y0))[0]
        for k in near:
            if segments_intersect(p, q, *sb[k]):
                return True
    return False


# ----------------------------------------------------------------------
# Croissance
# ----------------------------------------------------------------------

@dataclass(frozen=True)
class NineBias:
    heading_deg: float      # cap initial de la tête (s'éloigner du clubhouse)
    curve_radius: float     # rayon de courbure signé du cap (blocs)
    fatten_prob: float      # part des ajouts uniformes (épaississement irrégulier)
    branch_prob: float      # part des bifurcations (nouvelle tête sur le bord)


@dataclass
class _Growth:
    mask: np.ndarray
    head: np.ndarray        # centre de la tête, en unités de cellule
    theta: float
    bias: NineBias
    done: bool = False
    polygon: list[Point] | None = None
    loop: list[Point] | None = None
    path: list[Point] | None = None
    length: float = 0.0
    blocks: int = 1


def _draw_bias(rng: random.Random, quadrant: tuple[int, int]) -> NineBias:
    base = math.degrees(math.atan2(quadrant[1], quadrant[0]))
    return NineBias(
        heading_deg=base + rng.uniform(-45.0, 45.0),
        curve_radius=rng.uniform(120.0, 280.0) * rng.choice((-1.0, 1.0)),
        fatten_prob=rng.uniform(0.15, 0.40),
        branch_prob=rng.uniform(0.0, 0.12),
    )


def _grow_one(rng: random.Random, state: _Growth, other: np.ndarray, w: int, cell: float) -> None:
    cands = _candidates(state.mask, other, w)
    if len(cands) == 0:
        raise _Reject("impasse")
    centers = cands.astype(float) + w / 2.0
    roll = rng.random()
    tip_mode = roll >= state.bias.fatten_prob
    if tip_mode and roll < state.bias.fatten_prob + state.bias.branch_prob:
        cells = np.argwhere(state.mask & ~_erode4(state.mask))
        pick = cells[rng.randrange(len(cells))].astype(float) + 0.5
        centroid = np.argwhere(state.mask).mean(axis=0) + 0.5
        state.head = pick
        state.theta = math.atan2(pick[1] - centroid[1], pick[0] - centroid[0]) + rng.gauss(0.0, 0.3)
    if tip_mode:
        u = np.array([math.cos(state.theta), math.sin(state.theta)])
        rel = centers - state.head
        along = (rel @ u) / w
        perp = np.abs(rel[:, 0] * u[1] - rel[:, 1] * u[0]) / w
        logits = ALONG_GAIN * along - PERP_GAIN * perp
        weights = np.exp(logits - logits.max())
    else:
        along = np.zeros(len(cands))
        weights = np.ones(len(cands))
    weights = weights.tolist()
    total = math.fsum(weights)
    for _ in range(len(cands)):
        if total <= 0.0:
            break
        target = rng.random() * total
        acc, chosen = 0.0, len(weights) - 1
        for k, weight in enumerate(weights):
            acc += weight
            if weight > 0.0 and acc >= target:
                chosen = k
                break
        i, j = int(cands[chosen][0]), int(cands[chosen][1])
        trial = state.mask.copy()
        trial[i:i + w, j:j + w] = True
        if has_pinch(trial) or has_hole(trial):
            total -= weights[chosen]
            weights[chosen] = 0.0
            continue
        state.mask = trial
        state.blocks += 1
        if tip_mode:
            state.head = centers[chosen]
            state.theta += (w * cell) / state.bias.curve_radius + rng.gauss(0.0, math.radians(10.0))
            if along[chosen] < 0.25:  # tête bloquée : on tourne franchement
                state.theta += rng.choice((-1.0, 1.0)) * math.radians(rng.uniform(30.0, 70.0))
        return
    raise _Reject("impasse")


def _erode4(mask: np.ndarray) -> np.ndarray:
    p = np.pad(mask, 1)
    return mask & p[:-2, 1:-1] & p[2:, 1:-1] & p[1:-1, :-2] & p[1:-1, 2:]


@dataclass(frozen=True)
class RegionsResult:
    seed: int
    w_min: int
    cell: float
    inset: float
    clubhouse_vertex: tuple[int, int]
    clubhouse: Point
    front_cells: frozenset[Cell]
    back_cells: frozenset[Cell]
    front_polygon: tuple[Point, ...]
    back_polygon: tuple[Point, ...]
    front_loop: tuple[Point, ...]
    back_loop: tuple[Point, ...]
    front_path: tuple[Point, ...]
    back_path: tuple[Point, ...]
    front_length: float
    back_length: float
    length_window: tuple[float, float]
    front_bias: NineBias
    back_bias: NineBias
    front_blocks: int
    back_blocks: int
    attempts_used: int
    rejection_reasons: dict[str, int]
    elapsed_seconds: float

    def mask(self, cells: frozenset[Cell]) -> np.ndarray:
        n = grid_size(self.cell)
        out = np.zeros((n, n), dtype=bool)
        for i, j in cells:
            out[i, j] = True
        return out


def _attempt(rng: random.Random, w: int, window: tuple[float, float], cell: float, inset: float):
    n = grid_size(cell)
    px, py = rng.randint(w, n - w), rng.randint(w, n - w)
    sx, sy = rng.choice(((1, 1), (-1, -1), (1, -1), (-1, 1)))

    def seed_state(qx: int, qy: int) -> _Growth:
        mask = np.zeros((n, n), dtype=bool)
        i0 = px if qx > 0 else px - w
        j0 = py if qy > 0 else py - w
        mask[i0:i0 + w, j0:j0 + w] = True
        bias = _draw_bias(rng, (qx, qy))
        return _Growth(mask=mask, head=np.array([i0 + w / 2.0, j0 + w / 2.0]),
                       theta=math.radians(bias.heading_deg), bias=bias)

    states = [seed_state(sx, sy), seed_state(-sx, -sy)]
    low, high = window
    for _ in range(n * n):
        if all(state.done for state in states):
            break
        for idx in (0, 1):
            state = states[idx]
            if state.done:
                continue
            _grow_one(rng, state, states[1 - idx].mask, w, cell)
            if _length_estimate(state.mask, cell, inset) < low - 1.0:
                continue
            polygon, loop, path, length = _region_path(state.mask, (px, py), cell, inset)
            if length < low:
                continue
            if length > high:
                raise _Reject("trop_long")
            if not is_simple_polyline(loop):
                raise _Reject("non_simple")
            if loop_self_clearance(loop) < FAIRWAY_GAP:
                raise _Reject("degagement")
            state.polygon, state.loop, state.path, state.length = polygon, loop, path, length
            state.done = True
    if not all(state.done for state in states):
        raise _Reject("borne_pas")
    front, back = states
    if polylines_cross(front.path, back.path):
        raise _Reject("croisement")
    if polylines_min_distance(front.loop, back.loop) < FAIRWAY_GAP:
        raise _Reject("degagement_front_back")
    clubhouse = _to_world((px, py), cell)
    for state in states:
        if max(math.dist(state.path[0], clubhouse), math.dist(state.path[-1], clubhouse)) > ENDPOINT_MAX_DIST:
            raise _Reject("extremite")
    return (px, py), clubhouse, front, back


def _cells(mask: np.ndarray) -> frozenset[Cell]:
    return frozenset((int(i), int(j)) for i, j in np.argwhere(mask))


def build_regions(seed: int, w_min: int, *, cell: float | None = None, inset: float = INSET,
                  length_window: tuple[float, float] | None = None,
                  max_attempts: int = MAX_REGION_ATTEMPTS) -> RegionsResult:
    """Construit les deux régions et leurs parcours ; ``RegionGenerationError``
    après ``max_attempts`` tirages rejetés (aucune boucle non bornée)."""
    if cell is None:
        cell = CELL_BY_W_MIN[w_min]
    check_parameters(w_min, cell, inset)
    window = length_window if length_window is not None else nine_length_window()
    start = time.perf_counter()
    reasons: Counter[str] = Counter()
    for attempt in range(1, max_attempts + 1):
        rng = random.Random(seed * 1_000_000 + w_min * 10_000 + attempt)
        try:
            vertex, clubhouse, front, back = _attempt(rng, w_min, window, cell, inset)
        except _Reject as reject:
            reasons[reject.reason] += 1
            continue
        return RegionsResult(
            seed=seed, w_min=w_min, cell=cell, inset=inset,
            clubhouse_vertex=vertex, clubhouse=clubhouse,
            front_cells=_cells(front.mask), back_cells=_cells(back.mask),
            front_polygon=tuple(front.polygon), back_polygon=tuple(back.polygon),
            front_loop=tuple(front.loop), back_loop=tuple(back.loop),
            front_path=tuple(front.path), back_path=tuple(back.path),
            front_length=front.length, back_length=back.length,
            length_window=window, front_bias=front.bias, back_bias=back.bias,
            front_blocks=front.blocks, back_blocks=back.blocks,
            attempts_used=attempt, rejection_reasons=dict(sorted(reasons.items())),
            elapsed_seconds=time.perf_counter() - start,
        )
    raise RegionGenerationError(
        f"aucun tirage valide en {max_attempts} (seed={seed}, w_min={w_min}, "
        f"fenetre={window}) : {dict(sorted(reasons.items()))}",
        attempts=max_attempts, reasons=dict(sorted(reasons.items())),
    )


# ----------------------------------------------------------------------
# Rendu SVG lisible : bandes de fairway, flèches de sens de jeu, clubhouse
# ----------------------------------------------------------------------

BAND_WIDTH = 14.0          # fairway moyen
ARROW_SPACING = 60.0
FRONT_TINT, BACK_TINT = "#58a6ff", "#f2cc60"


def _point_and_tangent(path: list[Point], arclength: float) -> tuple[Point, Point]:
    travelled = 0.0
    for a, b in zip(path, path[1:]):
        step = math.dist(a, b)
        if step > 1e-9 and travelled + step >= arclength:
            t = (arclength - travelled) / step
            return ((a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t),
                    ((b[0] - a[0]) / step, (b[1] - a[1]) / step))
        travelled += step
    a, b = path[-2], path[-1]
    step = max(math.dist(a, b), 1e-9)
    return b, ((b[0] - a[0]) / step, (b[1] - a[1]) / step)


def render_regions_svg(result: RegionsResult, show_regions: bool = True) -> str:
    size, padding, footer = 800, 24, 64
    scale = (size - 2 * padding) / MAP_SIZE

    def pt(value: Point) -> tuple[float, float]:
        return (padding + value[0] * scale, padding + value[1] * scale)

    def fmt(points) -> str:
        return " ".join(f"{pt(p)[0]:.1f},{pt(p)[1]:.1f}" for p in points)

    out = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{size}" height="{size + footer}">',
        '<rect width="100%" height="100%" fill="#0d1117"/>',
        (f'<rect x="{padding}" y="{padding}" width="{MAP_SIZE * scale:.1f}" '
         f'height="{MAP_SIZE * scale:.1f}" fill="#22341c" stroke="#8b949e"/>'),
        ('<style>text{font-family:monospace;fill:#f0f6fc;paint-order:stroke;'
         'stroke:#0d1117;stroke-width:3px;font-weight:bold}</style>'),
    ]
    if show_regions:
        for polygon, tint in ((result.front_polygon, FRONT_TINT), (result.back_polygon, BACK_TINT)):
            out.append(f'<polygon points="{fmt(polygon)}" fill="{tint}" fill-opacity="0.10" stroke="none"/>')

    band = BAND_WIDTH * scale
    for path, tint in ((result.front_path, FRONT_TINT), (result.back_path, BACK_TINT)):
        out.append(f'<polyline points="{fmt(path)}" fill="none" stroke="{tint}" stroke-width="{band + 4:.1f}" '
                   'stroke-linejoin="round" stroke-linecap="butt"/>')
        out.append(f'<polyline points="{fmt(path)}" fill="none" stroke="#6aad45" stroke-width="{band:.1f}" '
                   'stroke-linejoin="round" stroke-linecap="butt"/>')

    for path in (result.front_path, result.back_path):
        length = _polyline_length(list(path))
        s = ARROW_SPACING / 2.0
        while s < length - 10.0:
            (x, y), (tx, ty) = _point_and_tangent(list(path), s)
            nx, ny = -ty, tx
            tip = (x + tx * 5.0, y + ty * 5.0)
            left = (x - tx * 4.0 + nx * 4.0, y - ty * 4.0 + ny * 4.0)
            right = (x - tx * 4.0 - nx * 4.0, y - ty * 4.0 - ny * 4.0)
            out.append(f'<polygon points="{fmt((tip, left, right))}" fill="#173d10"/>')
            s += ARROW_SPACING

    labels = (
        (result.front_path, 0, "départ 1", FRONT_TINT),
        (result.front_path, -1, "retour 9", FRONT_TINT),
        (result.back_path, 0, "départ 10", BACK_TINT),
        (result.back_path, -1, "retour 18", BACK_TINT),
    )
    club = result.clubhouse
    for path, end, text, tint in labels:
        anchor = path[end]
        p = pt(anchor)
        out.append(f'<circle cx="{p[0]:.1f}" cy="{p[1]:.1f}" r="5" fill="{tint}" stroke="#0d1117" stroke-width="1.5"/>')
        # étiquette repoussée loin du clubhouse, dans le prolongement du bout de parcours
        length = _polyline_length(list(path))
        probe, _ = _point_and_tangent(list(path), 34.0 if end == 0 else length - 34.0)
        away = (probe[0] - club[0], probe[1] - club[1])
        norm = max(math.hypot(*away), 1e-9)
        pos = (probe[0] + away[0] / norm * 12.0, probe[1] + away[1] / norm * 12.0)
        q = pt(pos)
        anchor_kind = "start" if away[0] >= 0 else "end"
        text_px = 9.2 * len(text)  # monospace 15 px, pour garder l'étiquette dans la carte
        if anchor_kind == "start" and q[0] + text_px > size - padding:
            anchor_kind = "end"
        elif anchor_kind == "end" and q[0] - text_px < padding:
            anchor_kind = "start"
        q = (q[0], min(max(q[1], padding + 12.0), size - padding - 8.0))
        out.append(f'<text x="{q[0]:.1f}" y="{q[1] + 5:.1f}" font-size="15" text-anchor="{anchor_kind}" '
                   f'style="fill:{tint}">{text}</text>')

    c = pt(club)
    out.append(f'<rect x="{c[0] - 10:.1f}" y="{c[1] - 10:.1f}" width="20" height="20" fill="#e5534b" '
               'stroke="#f0f6fc" stroke-width="2.5" transform="rotate(45 '
               f'{c[0]:.1f} {c[1]:.1f})"/>')
    out.append(f'<text x="{c[0]:.1f}" y="{c[1] + 5:.1f}" font-size="11" text-anchor="middle">CH</text>')

    low, high = result.length_window
    out.extend([
        (f'<text x="{padding}" y="{size + 22}" font-size="14">seed {result.seed} · w_min {result.w_min} · '
         f'c {result.cell:g} · d {result.inset:g} · {result.attempts_used} tirage(s) · '
         f'{result.elapsed_seconds * 1000:.0f} ms</text>'),
        (f'<text x="{padding}" y="{size + 46}" font-size="13">front (bleu) {result.front_length:.0f} · '
         f'back (jaune) {result.back_length:.0f} blocs · fenêtre {low:.0f}–{high:.0f} · '
         f'bande = fairway {BAND_WIDTH:g}</text>'),
        "</svg>",
    ])
    return "\n".join(out) + "\n"
