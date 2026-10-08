"""Étape M, R2 — contrôles en ligne sur un layout partiel.

``PartialLayout`` tient les trous déjà posés (des deux nines) et leurs
liaisons, et répond à une seule question : *ce trou candidat, avec sa ou ses
liaisons, introduit-il une violation finale ?* Les familles contrôlées sont
celles de ``geometry.validate`` qui dépendent d'un trou et de ses voisins
déjà posés : longueur/largeur, bords, clubhouse dégagé, croisement d'axes,
écart fairway (avec TOUS les trous posés), liaison hors plage, liaison
bloquée (dans les deux sens : nouvelle liaison vs fairways posés, liaisons
posées vs nouveau fairway) et pile parallèle consécutive.

Les prédicats sont ceux de l'oracle (mêmes fonctions, mêmes epsilons) : un
layout construit uniquement à partir de candidats acceptés ne peut donc pas
être rejeté par ``validate()`` sur ces familles. Seul un pré-filtre par boîtes
englobantes, conservatif, évite d'appeler les prédicats coûteux sur des
paires trop éloignées pour interagir.

Les quotas de pars (``par3_per_nine``, ``par5_per_nine``) et ``map_size``
sont garantis en amont par le tirage et la construction.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from golfgen.routing.geometry import (
    EPSILON,
    HoleGeometry,
    ValidationRules,
    _consecutive_parallel_series,
    _point_polygon_distance,
    _segment_crosses_polygon,
    _segments,
    build_hole_geometry,
    polygon_gap,
    segments_intersect,
)
from golfgen.routing.model import PAR_SPECS, ElasticHole


Point = tuple[float, float]
BBox = tuple[float, float, float, float]


def _bbox(points) -> BBox:
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    return (min(xs), min(ys), max(xs), max(ys))


def _bbox_apart(a: BBox, b: BBox, margin: float) -> bool:
    """Vrai si les boîtes sont séparées d'au moins ``margin`` sur un axe :
    alors la distance entre les contenus est ≥ ``margin``."""
    return (a[2] + margin < b[0] or b[2] + margin < a[0]
            or a[3] + margin < b[1] or b[3] + margin < a[1])


@dataclass(frozen=True, slots=True)
class PlannedLink:
    start: Point
    end: Point
    owners: tuple[int, ...]

    @property
    def length(self) -> float:
        return ((self.end[0] - self.start[0]) ** 2 + (self.end[1] - self.start[1]) ** 2) ** 0.5


@dataclass(frozen=True, slots=True)
class _Placed:
    hole: ElasticHole
    geometry: HoleGeometry
    core_box: BBox


@dataclass
class PartialLayout:
    """Trous et liaisons posés, avec empilement pour le retour arrière."""

    rules: ValidationRules
    clubhouse: Point
    holes: list[_Placed] = field(default_factory=list)
    links: list[tuple[PlannedLink, BBox]] = field(default_factory=list)
    _stack: list[tuple[int, int]] = field(default_factory=list)
    checks: int = 0

    def nine_holes(self, start_order: int) -> list[ElasticHole]:
        return [p.hole for p in self.holes if start_order <= p.hole.order < start_order + 9]

    def check(self, hole: ElasticHole, new_links: tuple[PlannedLink, ...],
              link_mins: tuple[float, ...] | None = None) -> str | None:
        """Première famille violée par ce candidat, ou ``None`` s'il est sain.

        ``link_mins`` permet d'exiger une liaison minimale plus stricte que
        ``rules.link_min`` (liaisons du clubhouse), jamais plus lâche.
        """
        self.checks += 1
        rules = self.rules
        spec = PAR_SPECS[hole.par]
        if not spec.accepts_length(hole.length):
            return "length"
        if not spec.accepts_width(hole.width):
            return "width"
        for index, link in enumerate(new_links):
            low = rules.link_min if link_mins is None else max(rules.link_min, link_mins[index])
            if not low - EPSILON <= link.length <= rules.link_max + EPSILON:
                return "link_distance"

        geometry = build_hole_geometry(hole)
        core = geometry.core
        if any(p[0] < rules.edge_min - EPSILON or p[0] > rules.width - rules.edge_min + EPSILON
               or p[1] < rules.edge_min - EPSILON or p[1] > rules.height - rules.edge_min + EPSILON
               for p in core):
            return "bounds"
        if (rules.clubhouse_clear_radius is not None
                and _point_polygon_distance(self.clubhouse, core)
                < rules.clubhouse_clear_radius - EPSILON):
            return "clubhouse_clear"

        box = _bbox(core)
        margin = rules.fairway_gap + 1.0
        for placed in self.holes:
            if _bbox_apart(box, placed.core_box, margin):
                continue
            other = placed.geometry
            if any(segments_intersect(a, b, c, d)
                   for a, b in _segments(geometry.axis)
                   for c, d in _segments(other.axis)):
                return "axis_crossing"
            if polygon_gap(core, other.core) < rules.fairway_gap - EPSILON:
                return "fairway_gap"

        if rules.walkable_links:
            for link in new_links:
                link_box = _bbox((link.start, link.end))
                for placed in self.holes:
                    if placed.hole.order in link.owners or _bbox_apart(link_box, placed.core_box, 1.0):
                        continue
                    if _segment_crosses_polygon(link.start, link.end, placed.geometry.core):
                        return "link_blocked"
            for link, link_box in self.links:
                if hole.order in link.owners or _bbox_apart(link_box, box, 1.0):
                    continue
                if _segment_crosses_polygon(link.start, link.end, core):
                    return "link_blocked"

        if rules.max_parallel_stack is not None:
            # toute fenêtre de max_parallel_stack + 1 trous consécutifs qui
            # contient le candidat et dont tous les trous sont posés (les
            # trous d'ancrage peuvent être posés avant leurs prédécesseurs)
            start_order = 1 if hole.order <= 9 else 10
            by_order = {h.order: h for h in self.nine_holes(start_order)}
            by_order[hole.order] = hole
            size = rules.max_parallel_stack + 1
            for first in range(hole.order - size + 1, hole.order + 1):
                orders = range(first, first + size)
                if not all(order in by_order for order in orders):
                    continue
                window = tuple(by_order[order] for order in orders)
                geometries = {h.order: (geometry if h is hole else build_hole_geometry(h))
                              for h in window}
                if _consecutive_parallel_series(window, geometries, rules):
                    return "parallel_stack"
        return None

    def push(self, hole: ElasticHole, new_links: tuple[PlannedLink, ...]) -> None:
        geometry = build_hole_geometry(hole)
        self.holes.append(_Placed(hole, geometry, _bbox(geometry.core)))
        for link in new_links:
            self.links.append((link, _bbox((link.start, link.end))))
        self._stack.append((1, len(new_links)))

    def pop(self) -> None:
        holes, links = self._stack.pop()
        del self.holes[len(self.holes) - holes:]
        if links:
            del self.links[len(self.links) - links:]


# ----------------------------------------------------------------------
# Pré-filtres vectorisés : conditions NÉCESSAIRES, jamais suffisantes
# ----------------------------------------------------------------------
#
# Un cœur ``buffered_axis(axis, r)`` (bouts plats prolongés de r, joints en
# onglet non écrêtés tant que la déflexion reste < ~88°, ce qui est le cas des
# doglegs ≤ 55°) contient la somme de Minkowski de l'axe et du disque de rayon
# r. D'où, pour deux trous de demi-largeurs r1, r2 :
#   écart des cœurs ≤ distance des axes − r1 − r2,
# et une liaison à moins de r d'un axe entre dans le cœur. Rejeter sur ces
# seuils (moins ``PREFILTER_SLACK``) ne rejette donc que des candidats que
# ``PartialLayout.check`` aurait aussi rejetés.

PREFILTER_SLACK = 1e-3


def point_segment_distances(points: np.ndarray, a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """Distances (n, m) des points (n, 2) aux segments a[m]→b[m]."""
    d = b - a                                          # (m, 2)
    length_sq = np.maximum((d * d).sum(axis=1), 1e-12)
    rel = points[:, None, :] - a[None, :, :]           # (n, m, 2)
    t = np.clip((rel * d[None]).sum(axis=2) / length_sq[None], 0.0, 1.0)
    proj = a[None] + t[..., None] * d[None]
    return np.hypot(*(points[:, None, :] - proj).transpose(2, 0, 1))


def _cross2(o: np.ndarray, a: np.ndarray, b: np.ndarray) -> np.ndarray:
    return (a[..., 0] - o[..., 0]) * (b[..., 1] - o[..., 1]) - (a[..., 1] - o[..., 1]) * (b[..., 0] - o[..., 0])


def segment_segment_distances(p0: np.ndarray, p1: np.ndarray,
                              q0: np.ndarray, q1: np.ndarray) -> np.ndarray:
    """Distances (n, m) entre segments p0[n]→p1[n] et q0[m]→q1[m]."""
    P0, P1 = p0[:, None, :], p1[:, None, :]
    Q0, Q1 = q0[None, :, :], q1[None, :, :]
    c1, c2 = _cross2(P0, P1, Q0), _cross2(P0, P1, Q1)
    c3, c4 = _cross2(Q0, Q1, P0), _cross2(Q0, Q1, P1)
    crossing = (c1 * c2 < 0) & (c3 * c4 < 0)
    best = np.minimum(
        np.minimum(point_segment_distances(p0, q0, q1), point_segment_distances(p1, q0, q1)),
        np.minimum(point_segment_distances(q0, p0, p1).T, point_segment_distances(q1, p0, p1).T),
    )
    return np.where(crossing, 0.0, best)


@dataclass(frozen=True, slots=True)
class Obstacles:
    """Axes et liaisons posés, sous forme de tableaux pour les pré-filtres."""

    axis_a: np.ndarray
    axis_b: np.ndarray
    axis_radius: np.ndarray
    axis_order: np.ndarray
    link_a: np.ndarray
    link_b: np.ndarray

    @classmethod
    def from_partial(cls, partial: PartialLayout) -> "Obstacles":
        a, b, r, o = [], [], [], []
        for placed in partial.holes:
            axis = placed.geometry.axis
            for start, end in zip(axis, axis[1:]):
                a.append(start)
                b.append(end)
                r.append(placed.hole.width / 2.0)
                o.append(placed.hole.order)
        la = [link.start for link, _ in partial.links]
        lb = [link.end for link, _ in partial.links]
        return cls(np.asarray(a, float).reshape(-1, 2), np.asarray(b, float).reshape(-1, 2),
                   np.asarray(r, float), np.asarray(o, int),
                   np.asarray(la, float).reshape(-1, 2), np.asarray(lb, float).reshape(-1, 2))

    def points_clear(self, points: np.ndarray, radius: float, gap: float) -> np.ndarray:
        """Points (tee/green d'un trou de demi-largeur ``radius``) compatibles
        avec l'écart fairway vis-à-vis de tous les axes posés."""
        if len(self.axis_a) == 0:
            return np.ones(len(points), dtype=bool)
        dist = point_segment_distances(points, self.axis_a, self.axis_b)
        return (dist >= radius + self.axis_radius[None] + gap - PREFILTER_SLACK).all(axis=1)

    def links_clear(self, start: np.ndarray, ends: np.ndarray, skip_order: int | None) -> np.ndarray:
        """Liaisons start→ends[i] qui n'entrent dans aucun cœur posé (hors
        trou propriétaire ``skip_order``)."""
        keep = self.axis_order != (skip_order if skip_order is not None else -1)
        if not keep.any():
            return np.ones(len(ends), dtype=bool)
        starts = np.repeat(start[None, :], len(ends), axis=0)
        dist = segment_segment_distances(starts, ends, self.axis_a[keep], self.axis_b[keep])
        return (dist >= self.axis_radius[keep][None] - PREFILTER_SLACK).all(axis=1)

    def chords_clear(self, tees: np.ndarray, greens: np.ndarray, radius: float,
                     gap: float) -> np.ndarray:
        """Trous droits tee[i]→green[i] compatibles avec les axes (écart) et
        les liaisons (non bloquées) posés."""
        ok = np.ones(len(tees), dtype=bool)
        if len(self.axis_a):
            dist = segment_segment_distances(tees, greens, self.axis_a, self.axis_b)
            ok &= (dist >= radius + self.axis_radius[None] + gap - PREFILTER_SLACK).all(axis=1)
        if len(self.link_a):
            dist = segment_segment_distances(tees, greens, self.link_a, self.link_b)
            ok &= (dist >= radius - PREFILTER_SLACK).all(axis=1)
        return ok
