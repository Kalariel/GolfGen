"""Transformations et oracle géométrique indépendant du paveur."""

from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Iterable

from experiments.bean_paving.bean_bank import BeanTemplate, Point

EPSILON = 1e-7


@dataclass(frozen=True)
class Transform:
    x: float
    y: float
    rotation_deg: float = 0.0
    mirrored: bool = False

    def point(self, point: Point) -> Point:
        px, py = point
        if self.mirrored:
            py = -py
        angle = math.radians(self.rotation_deg)
        cos_a, sin_a = math.cos(angle), math.sin(angle)
        return (self.x + px * cos_a - py * sin_a,
                self.y + px * sin_a + py * cos_a)


@dataclass(frozen=True)
class PlacedBean:
    template: BeanTemplate
    transform: Transform
    order: int

    @property
    def id(self) -> str:
        return self.template.id

    @property
    def axis(self) -> tuple[Point, ...]:
        return tuple(self.transform.point(point) for point in self.template.axis)

    @property
    def footprint(self) -> tuple[Point, ...]:
        return tuple(self.transform.point(point) for point in self.template.footprint)

    @property
    def tee(self) -> Point:
        return self.transform.point(self.template.tee)

    @property
    def green(self) -> Point:
        return self.transform.point(self.template.green)


@dataclass(frozen=True)
class ValidationRules:
    width: float = 350.0
    height: float = 350.0
    link_min: float = 12.0
    link_max: float = 45.0
    antiparallel_angle_deg: float = 15.0
    antiparallel_distance: float = 30.0
    antiparallel_overlap: float = 40.0


@dataclass(frozen=True)
class Violation:
    kind: str
    beans: tuple[str, ...]
    detail: str


def _cross(a: Point, b: Point, c: Point) -> float:
    return (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])


def _on_segment(point: Point, a: Point, b: Point) -> bool:
    return (abs(_cross(a, b, point)) <= EPSILON
            and min(a[0], b[0]) - EPSILON <= point[0] <= max(a[0], b[0]) + EPSILON
            and min(a[1], b[1]) - EPSILON <= point[1] <= max(a[1], b[1]) + EPSILON)


def segments_intersect(a: Point, b: Point, c: Point, d: Point) -> bool:
    """Intersection fermée : un simple contact compte comme une collision."""
    c1, c2, c3, c4 = _cross(a, b, c), _cross(a, b, d), _cross(c, d, a), _cross(c, d, b)
    if ((c1 > EPSILON and c2 < -EPSILON) or (c1 < -EPSILON and c2 > EPSILON)) \
            and ((c3 > EPSILON and c4 < -EPSILON) or (c3 < -EPSILON and c4 > EPSILON)):
        return True
    return ((abs(c1) <= EPSILON and _on_segment(c, a, b))
            or (abs(c2) <= EPSILON and _on_segment(d, a, b))
            or (abs(c3) <= EPSILON and _on_segment(a, c, d))
            or (abs(c4) <= EPSILON and _on_segment(b, c, d)))


def _point_in_polygon(point: Point, polygon: tuple[Point, ...]) -> bool:
    inside = False
    j = len(polygon) - 1
    for i, pi in enumerate(polygon):
        pj = polygon[j]
        if _on_segment(point, pj, pi):
            return True
        if (pi[1] > point[1]) != (pj[1] > point[1]):
            x_cross = (pj[0] - pi[0]) * (point[1] - pi[1]) / (pj[1] - pi[1]) + pi[0]
            if point[0] < x_cross:
                inside = not inside
        j = i
    return inside


def polygons_intersect(first: tuple[Point, ...], second: tuple[Point, ...]) -> bool:
    for a, b in _segments(first, closed=True):
        for c, d in _segments(second, closed=True):
            if segments_intersect(a, b, c, d):
                return True
    return _point_in_polygon(first[0], second) or _point_in_polygon(second[0], first)


def _segments(points: tuple[Point, ...], *, closed: bool = False):
    for a, b in zip(points, points[1:]):
        yield a, b
    if closed and len(points) > 2:
        yield points[-1], points[0]


def _point_segment_distance(point: Point, a: Point, b: Point) -> float:
    dx, dy = b[0] - a[0], b[1] - a[1]
    length_sq = dx * dx + dy * dy
    if length_sq <= EPSILON:
        return math.dist(point, a)
    t = max(0.0, min(1.0, ((point[0] - a[0]) * dx + (point[1] - a[1]) * dy) / length_sq))
    return math.dist(point, (a[0] + t * dx, a[1] + t * dy))


def segment_distance(a: Point, b: Point, c: Point, d: Point) -> float:
    if segments_intersect(a, b, c, d):
        return 0.0
    return min(_point_segment_distance(a, c, d), _point_segment_distance(b, c, d),
               _point_segment_distance(c, a, b), _point_segment_distance(d, a, b))


def _antiparallel(a: Point, b: Point, c: Point, d: Point, rules: ValidationRules) -> bool:
    ux, uy = b[0] - a[0], b[1] - a[1]
    vx, vy = d[0] - c[0], d[1] - c[1]
    len_u, len_v = math.hypot(ux, uy), math.hypot(vx, vy)
    if len_u <= EPSILON or len_v <= EPSILON:
        return False
    dot = (ux * vx + uy * vy) / (len_u * len_v)
    if dot > -math.cos(math.radians(rules.antiparallel_angle_deg)):
        return False
    if segment_distance(a, b, c, d) >= rules.antiparallel_distance:
        return False
    unit = (ux / len_u, uy / len_u)
    first = sorted((a[0] * unit[0] + a[1] * unit[1], b[0] * unit[0] + b[1] * unit[1]))
    second = sorted((c[0] * unit[0] + c[1] * unit[1], d[0] * unit[0] + d[1] * unit[1]))
    overlap = min(first[1], second[1]) - max(first[0], second[0])
    return overlap > rules.antiparallel_overlap


def validate(beans: Iterable[PlacedBean], rules: ValidationRules | None = None,
             *, check_links: bool = True) -> list[Violation]:
    """Retourne toutes les violations, sans réparer ni assouplir le résultat."""
    rules = rules or ValidationRules()
    ordered = sorted(beans, key=lambda bean: bean.order)
    violations: list[Violation] = []

    for bean in ordered:
        outside = [p for p in bean.footprint
                   if p[0] < -EPSILON or p[0] > rules.width + EPSILON
                   or p[1] < -EPSILON or p[1] > rules.height + EPSILON]
        if outside:
            violations.append(Violation("bounds", (bean.id,), f"{len(outside)} sommet(s) hors carte"))

    for index, first in enumerate(ordered):
        for second in ordered[index + 1:]:
            pair = (first.id, second.id)
            if polygons_intersect(first.footprint, second.footprint):
                violations.append(Violation("footprint_collision", pair, "empreintes en contact"))
            crosses = any(segments_intersect(a, b, c, d)
                          for a, b in _segments(first.axis)
                          for c, d in _segments(second.axis))
            if crosses:
                violations.append(Violation("axis_crossing", pair, "axes en intersection"))
            parallel = any(_antiparallel(a, b, c, d, rules)
                           for a, b in _segments(first.axis)
                           for c, d in _segments(second.axis))
            if parallel:
                violations.append(Violation("antiparallel", pair, "retour parallèle long et proche"))

    if check_links:
        for previous, current in zip(ordered, ordered[1:]):
            link = math.dist(previous.green, current.tee)
            if link < rules.link_min - EPSILON or link > rules.link_max + EPSILON:
                violations.append(Violation(
                    "link_distance", (previous.id, current.id),
                    f"liaison {link:.2f}, attendue dans [{rules.link_min:.2f}, {rules.link_max:.2f}]",
                ))
    return violations
