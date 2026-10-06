"""Évaluateur incrémental (surrogate) pour les mutations locales de l'étape 4.

Ce module ne dépend que du modèle (``model.py``) et réutilise les primitives
publiques de l'oracle (``geometry.py``) par import ; il ne le modifie pas et
n'implémente pas la règle ``parallel_stack`` (réécrite ailleurs). La composante
``parallelisme`` du score reste donc à 0 — TODO : la brancher quand la
nouvelle implémentation de ``parallel_stack`` sera stabilisée dans
``geometry.py``. Les composantes ``variete`` et ``deformation`` sont des
objectifs souples pas encore définis par l'oracle (étape 5) : elles restent
à 0 elles aussi.

Approximations assumées (documentées, pas masquées) :

- chaque trou est traité comme une **capsule** (axe + demi-largeur), alors que
  l'oracle polygonal utilise des joints biseautés et des extrémités
  prolongées sur les virages (``geometry.buffered_axis``). Une marge
  conservatrice ``conservative_margin`` est retranchée de chaque distance
  estimée (écart fairway, clubhouse, blocage de liaison) pour que le
  surrogate ne *manque* jamais une violation réelle de l'oracle ; il peut en
  revanche signaler de faux positifs occasionnels près des seuils, résolus
  périodiquement par l'oracle complet (voir PLAN.md, point c) ;
- le rejet rapide par boîtes englobantes élargies (``_bbox_overlap``) peut, en
  théorie, laisser passer un recouvrement extrême si la marge conservatrice
  est insuffisante pour un virage très serré ; en pratique la marge par
  défaut couvre les cas du layout synthétique et des perturbations testées.

Mapping violation de l'oracle -> composante du score vectoriel (pas de nom
dédié "bounds"/"map_size" dans la liste imposée, donc rattaché à
``topologie`` comme contrainte structurelle de placement) :

- ``length``, ``width``                      -> ``longueurs``
- ``bounds``, ``map_size``, ``par{3,5}_per_nine`` -> ``topologie``
- ``axis_crossing``                          -> ``croisements``
- ``fairway_gap``                            -> ``ecarts``
- ``clubhouse_clear``                        -> ``clubhouse``
- ``link_distance``, ``link_blocked``        -> ``liaisons``
- ``parallel_stack``                         -> ``parallelisme`` (TODO, 0)
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, replace
import math
from typing import Iterable, Mapping

from experiments.elastic_routing.geometry import ValidationRules, segment_distance, segments_intersect
from experiments.elastic_routing.model import (
    PAR_SPECS,
    ControlPoint,
    CourseLayout,
    ElasticHole,
    NineLayout,
)


Point = tuple[float, float]

COMPONENT_NAMES = (
    "topologie",
    "croisements",
    "ecarts",
    "longueurs",
    "liaisons",
    "clubhouse",
    "parallelisme",
    "variete",
    "deformation",
)

LinkKey = tuple[int | None, int | None]


def _point(control: ControlPoint) -> Point:
    return (control.x, control.y)


def _point_segment_distance(point: Point, a: Point, b: Point) -> float:
    """Duplication locale (primitive privée de geometry.py, non importée)."""
    dx, dy = b[0] - a[0], b[1] - a[1]
    length_sq = dx * dx + dy * dy
    if length_sq <= 1e-12:
        return math.dist(point, a)
    ratio = ((point[0] - a[0]) * dx + (point[1] - a[1]) * dy) / length_sq
    ratio = max(0.0, min(1.0, ratio))
    return math.dist(point, (a[0] + ratio * dx, a[1] + ratio * dy))


def _bbox_overlap(first: tuple[float, float, float, float],
                   second: tuple[float, float, float, float]) -> bool:
    return (first[0] <= second[2] and second[0] <= first[2]
            and first[1] <= second[3] and second[1] <= first[3])


@dataclass(frozen=True, slots=True)
class ScoreVector:
    """Vecteur de score nommé ; les composantes non calculées valent 0."""

    topologie: float = 0.0
    croisements: float = 0.0
    ecarts: float = 0.0
    longueurs: float = 0.0
    liaisons: float = 0.0
    clubhouse: float = 0.0
    parallelisme: float = 0.0
    variete: float = 0.0
    deformation: float = 0.0

    def total(self) -> float:
        return math.fsum(getattr(self, name) for name in COMPONENT_NAMES)

    def as_dict(self) -> dict[str, float]:
        return {name: getattr(self, name) for name in COMPONENT_NAMES}


@dataclass(frozen=True, slots=True)
class _HoleCache:
    hole: ElasticHole
    axis: tuple[Point, ...]
    half_width: float
    bbox: tuple[float, float, float, float]
    gap_bbox: tuple[float, float, float, float]
    self_penalty: Mapping[str, float]


@dataclass(frozen=True, slots=True)
class _PairEntry:
    penalty: Mapping[str, float]


@dataclass(frozen=True, slots=True)
class _LinkEntry:
    start: Point
    end: Point
    owners: tuple[int, ...]
    distance_penalty: float
    block_penalty: Mapping[int, float]


def _nine_of(order: int) -> str:
    return "front" if 1 <= order <= 9 else "back"


def _adjacent_link_keys(order: int) -> tuple[LinkKey, LinkKey]:
    if 1 <= order <= 9:
        base = 1
    else:
        base = 10
    prev: LinkKey = (None, base) if order == base else (order - 1, order)
    nxt: LinkKey = (order, order + 1) if order < base + 8 else (base + 8, None)
    return prev, nxt


def _all_link_keys() -> tuple[LinkKey, ...]:
    keys: list[LinkKey] = []
    for base in (1, 10):
        keys.append((None, base))
        for order in range(base, base + 8):
            keys.append((order, order + 1))
        keys.append((base + 8, None))
    return tuple(keys)


def _owners_of(key: LinkKey) -> tuple[int, ...]:
    return tuple(order for order in key if order is not None)


class IncrementalEvaluator:
    """Cache et met à jour, par mutation locale, un score surrogate.

    Construit depuis un ``CourseLayout`` complet (18 trous). ``apply()``
    remplace un sous-ensemble de trous (identifiés par ``order``) et ne
    recalcule que : leur géométrie dérivée, leurs paires avec les 17 autres
    trous, et les liaisons touchées (directement possédées, ou dont le
    statut de blocage dépend d'un trou modifié). ``revert()`` annule la
    dernière mutation appliquée (pile à un seul niveau, suffisant pour un
    recuit qui teste puis annule un essai à la fois).
    """

    def __init__(self, layout: CourseLayout, rules: ValidationRules | None = None,
                 *, conservative_margin: float = 1.0) -> None:
        self._clubhouse = _point(layout.clubhouse)
        self._width = layout.width
        self._height = layout.height
        self._seed = layout.seed
        self._rules = rules if rules is not None else ValidationRules(width=layout.width, height=layout.height)
        self._conservative_margin = float(conservative_margin)
        self._all_orders: tuple[int, ...] = tuple(range(1, 19))
        self._all_link_keys: tuple[LinkKey, ...] = _all_link_keys()

        self._hole_cache: dict[int, _HoleCache] = {
            hole.order: self._build_hole_cache(hole) for hole in layout.holes
        }
        self._pair_cache: dict[tuple[int, int], _PairEntry] = {}
        for index, first in enumerate(self._all_orders):
            for second in self._all_orders[index + 1:]:
                self._pair_cache[(first, second)] = self._build_pair_entry(
                    self._hole_cache[first], self._hole_cache[second])
        self._link_cache: dict[LinkKey, _LinkEntry] = {
            key: self._build_link_entry(key) for key in self._all_link_keys
        }
        self._nine_par_penalty: dict[str, float] = {
            "front": self._compute_nine_par_penalty("front"),
            "back": self._compute_nine_par_penalty("back"),
        }
        self._totals: dict[str, float] = {}
        self._recompute_totals()
        self._last_undo: tuple | None = None

    # -- construction des entrées de cache -------------------------------

    def _build_hole_cache(self, hole: ElasticHole) -> _HoleCache:
        axis = tuple(_point(point) for point in hole.axis)
        half_width = hole.width / 2.0
        radius = half_width + self._conservative_margin
        xs = [point[0] for point in axis]
        ys = [point[1] for point in axis]
        bbox = (min(xs) - radius, min(ys) - radius, max(xs) + radius, max(ys) + radius)
        # bbox élargie en plus du seuil d'écart fairway : une paire ne peut
        # être rejetée avant calcul exact que si elle est hors de portée de
        # *toute* violation possible (pas seulement d'un contact), sinon le
        # rejet rapide masquerait des écarts fairway proches du seuil.
        gap_radius = radius + self._rules.fairway_gap
        gap_bbox = (min(xs) - gap_radius, min(ys) - gap_radius,
                    max(xs) + gap_radius, max(ys) + gap_radius)

        spec = PAR_SPECS[hole.par]
        length_penalty = max(0.0, spec.length_min - hole.length) + max(0.0, hole.length - spec.length_max)
        width_penalty = max(0.0, spec.width_min - hole.width) + max(0.0, hole.width - spec.width_max)
        bounds_penalty = self._bounds_penalty(axis, radius)
        clubhouse_penalty = 0.0
        if self._rules.clubhouse_clear_radius is not None:
            min_dist = min(_point_segment_distance(self._clubhouse, a, b)
                            for a, b in zip(axis, axis[1:]))
            estimate = min_dist - half_width - self._conservative_margin
            clubhouse_penalty = max(0.0, self._rules.clubhouse_clear_radius - estimate)

        self_penalty = {
            "longueurs": length_penalty + width_penalty,
            "topologie": bounds_penalty,
            "clubhouse": clubhouse_penalty,
        }
        return _HoleCache(hole=hole, axis=axis, half_width=half_width, bbox=bbox,
                          gap_bbox=gap_bbox, self_penalty=self_penalty)

    def _bounds_penalty(self, axis: tuple[Point, ...], radius: float) -> float:
        edge_min = self._rules.edge_min
        width, height = self._rules.width, self._rules.height
        penalty = 0.0
        for x, y in axis:
            penalty += max(0.0, (edge_min + radius) - x)
            penalty += max(0.0, x - (width - edge_min - radius))
            penalty += max(0.0, (edge_min + radius) - y)
            penalty += max(0.0, y - (height - edge_min - radius))
        return penalty

    def _build_pair_entry(self, first: _HoleCache, second: _HoleCache) -> _PairEntry:
        if not _bbox_overlap(first.gap_bbox, second.gap_bbox):
            return _PairEntry(penalty={"croisements": 0.0, "ecarts": 0.0})
        first_segments = tuple(zip(first.axis, first.axis[1:]))
        second_segments = tuple(zip(second.axis, second.axis[1:]))
        crossing = any(segments_intersect(a, b, c, d)
                       for a, b in first_segments for c, d in second_segments)
        axis_penalty = 1.0 if crossing else 0.0
        min_gap = min(segment_distance(a, b, c, d)
                      for a, b in first_segments for c, d in second_segments)
        estimate = min_gap - first.half_width - second.half_width - self._conservative_margin
        gap_penalty = max(0.0, self._rules.fairway_gap - estimate)
        return _PairEntry(penalty={"croisements": axis_penalty, "ecarts": gap_penalty})

    def _link_endpoints(self, key: LinkKey) -> tuple[Point, Point]:
        start = self._clubhouse if key[0] is None else self._hole_cache[key[0]].axis[-1]
        end = self._clubhouse if key[1] is None else self._hole_cache[key[1]].axis[0]
        return start, end

    def _block_penalty(self, start: Point, end: Point, cache: _HoleCache) -> float:
        threshold = cache.half_width + self._conservative_margin
        minx, maxx = min(start[0], end[0]), max(start[0], end[0])
        miny, maxy = min(start[1], end[1]), max(start[1], end[1])
        bx0, by0, bx1, by1 = cache.bbox
        if maxx < bx0 or minx > bx1 or maxy < by0 or miny > by1:
            return 0.0
        min_dist = min(segment_distance(start, end, a, b) for a, b in zip(cache.axis, cache.axis[1:]))
        return max(0.0, threshold - min_dist)

    def _build_link_entry(self, key: LinkKey) -> _LinkEntry:
        owners = _owners_of(key)
        start, end = self._link_endpoints(key)
        length = math.dist(start, end)
        distance_penalty = max(0.0, self._rules.link_min - length) + max(0.0, length - self._rules.link_max)
        block_penalty: dict[int, float] = {}
        if self._rules.walkable_links:
            for order in self._all_orders:
                if order in owners:
                    continue
                block_penalty[order] = self._block_penalty(start, end, self._hole_cache[order])
        return _LinkEntry(start=start, end=end, owners=owners,
                           distance_penalty=distance_penalty, block_penalty=block_penalty)

    def _compute_nine_par_penalty(self, nine: str) -> float:
        orders = range(1, 10) if nine == "front" else range(10, 19)
        counts = Counter(self._hole_cache[order].hole.par for order in orders)
        penalty = 0.0
        for par, bounds in ((3, self._rules.par3_per_nine), (5, self._rules.par5_per_nine)):
            lower, upper = bounds
            count = counts[par]
            penalty += max(0.0, lower - count) + max(0.0, count - upper)
        return float(penalty)

    def _recompute_totals(self) -> None:
        totals = {name: 0.0 for name in COMPONENT_NAMES}
        for cache in self._hole_cache.values():
            for name, value in cache.self_penalty.items():
                totals[name] += value
        for pair in self._pair_cache.values():
            for name, value in pair.penalty.items():
                totals[name] += value
        for link in self._link_cache.values():
            totals["liaisons"] += link.distance_penalty + math.fsum(link.block_penalty.values())
        for value in self._nine_par_penalty.values():
            totals["topologie"] += value
        self._totals = totals

    # -- API publique ------------------------------------------------------

    def score(self) -> ScoreVector:
        return ScoreVector(**self._totals)

    def to_layout(self) -> CourseLayout:
        """Reconstruit un ``CourseLayout`` valide depuis l'état courant."""
        clubhouse = ControlPoint(*self._clubhouse)
        front_holes = tuple(self._hole_cache[order].hole for order in range(1, 10))
        back_holes = tuple(self._hole_cache[order].hole for order in range(10, 19))
        return CourseLayout(
            seed=self._seed, width=self._width, height=self._height, clubhouse=clubhouse,
            front=NineLayout.from_holes(1, clubhouse, front_holes),
            back=NineLayout.from_holes(10, clubhouse, back_holes),
        )

    def _snapshot(self) -> tuple:
        return (
            dict(self._hole_cache),
            dict(self._pair_cache),
            dict(self._link_cache),
            dict(self._nine_par_penalty),
            dict(self._totals),
        )

    def apply(self, holes: ElasticHole | Iterable[ElasticHole]) -> None:
        """Remplace un ou plusieurs trous (par ``order``) et met à jour le cache.

        Ne recalcule que les trous fournis, leurs paires avec les 17 autres
        trous, et les liaisons touchées (possédées par un trou modifié, ou
        dont le statut de blocage dépend d'un trou modifié non propriétaire).
        """
        holes = (holes,) if isinstance(holes, ElasticHole) else tuple(holes)
        if not holes:
            raise ValueError("apply() nécessite au moins un trou")
        orders = [hole.order for hole in holes]
        if len(set(orders)) != len(orders):
            raise ValueError("apply() a reçu des ordres dupliqués")
        for hole in holes:
            if hole.order not in self._hole_cache:
                raise ValueError(f"trou inconnu : {hole.order}")

        self._last_undo = self._snapshot()

        changed = set(orders)
        for hole in holes:
            self._hole_cache[hole.order] = self._build_hole_cache(hole)

        for first in changed:
            for second in self._all_orders:
                if second == first:
                    continue
                key = (first, second) if first < second else (second, first)
                self._pair_cache[key] = self._build_pair_entry(
                    self._hole_cache[key[0]], self._hole_cache[key[1]])

        touched_links: set[LinkKey] = set()
        for order in changed:
            touched_links.update(_adjacent_link_keys(order))
        for key in touched_links:
            self._link_cache[key] = self._build_link_entry(key)

        if self._rules.walkable_links:
            for order in changed:
                for key in self._all_link_keys:
                    if key in touched_links or order in _owners_of(key):
                        continue
                    entry = self._link_cache[key]
                    new_block = dict(entry.block_penalty)
                    new_block[order] = self._block_penalty(entry.start, entry.end, self._hole_cache[order])
                    self._link_cache[key] = replace(entry, block_penalty=new_block)

        touched_nines = {_nine_of(order) for order in changed}
        for nine in touched_nines:
            self._nine_par_penalty[nine] = self._compute_nine_par_penalty(nine)

        self._recompute_totals()

    def revert(self) -> None:
        """Annule la dernière mutation appliquée (un seul niveau d'historique)."""
        if self._last_undo is None:
            raise RuntimeError("aucune mutation à annuler")
        (self._hole_cache, self._pair_cache, self._link_cache,
         self._nine_par_penalty, self._totals) = self._last_undo
        self._last_undo = None
