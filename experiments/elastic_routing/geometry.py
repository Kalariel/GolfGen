"""Oracle géométrique indépendant pour les parcours élastiques.

Le module dépend uniquement du modèle de données. Il ne connaît ni squelette,
ni mutation, ni optimiseur : une recherche future ne peut donc pas déclarer
elle-même son résultat valide.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
import math

from experiments.elastic_routing.model import CourseLayout, ElasticHole, PAR_SPECS


Point = tuple[float, float]
EPSILON = 1e-7


def _finite(value: float, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"{field} doit être un nombre")
    result = float(value)
    if not math.isfinite(result):
        raise ValueError(f"{field} doit être fini")
    return result


@dataclass(frozen=True, slots=True)
class ValidationRules:
    width: float = 400.0
    height: float = 400.0
    link_min: float = 12.0
    link_max: float = 45.0
    fairway_gap: float = 5.0
    edge_min: float = 1.0
    clubhouse_clear_radius: float | None = 10.0
    max_parallel_stack: int | None = 3
    parallel_stack_angle_deg: float = 20.0
    parallel_stack_overlap: float = 40.0
    walkable_links: bool = True
    par3_per_nine: tuple[int, int] = (1, 3)
    par5_per_nine: tuple[int, int] = (1, 3)

    def __post_init__(self) -> None:
        numeric_fields = (
            "width", "height", "link_min", "link_max", "fairway_gap",
            "edge_min", "parallel_stack_angle_deg", "parallel_stack_overlap",
        )
        for field in numeric_fields:
            object.__setattr__(self, field, _finite(getattr(self, field), field))
        if self.clubhouse_clear_radius is not None:
            object.__setattr__(
                self,
                "clubhouse_clear_radius",
                _finite(self.clubhouse_clear_radius, "clubhouse_clear_radius"),
            )
        if self.width <= 0.0 or self.height <= 0.0:
            raise ValueError("les dimensions de carte doivent être positives")
        if not 0.0 <= self.link_min <= self.link_max:
            raise ValueError("plage de liaison invalide")
        if self.fairway_gap < 0.0 or self.edge_min < 0.0:
            raise ValueError("les marges géométriques doivent être positives")
        if self.clubhouse_clear_radius is not None and self.clubhouse_clear_radius < 0.0:
            raise ValueError("clubhouse_clear_radius doit être positif ou nul")
        if self.max_parallel_stack is not None:
            if isinstance(self.max_parallel_stack, bool) or not isinstance(self.max_parallel_stack, int):
                raise TypeError("max_parallel_stack doit être un entier ou None")
            if self.max_parallel_stack < 1:
                raise ValueError("max_parallel_stack doit être positif")
        if not isinstance(self.walkable_links, bool):
            raise TypeError("walkable_links doit être un booléen")
        for minimum, maximum in (self.par3_per_nine, self.par5_per_nine):
            if (isinstance(minimum, bool) or not isinstance(minimum, int)
                    or isinstance(maximum, bool) or not isinstance(maximum, int)):
                raise TypeError("les bornes de pars doivent être des entiers")
            if not 0 <= minimum <= maximum <= 9:
                raise ValueError("bornes de pars par nine invalides")


@dataclass(frozen=True, slots=True)
class HoleGeometry:
    order: int
    axis: tuple[Point, ...]
    core: tuple[Point, ...]
    rough: tuple[Point, ...]


@dataclass(frozen=True, slots=True)
class Violation:
    kind: str
    holes: tuple[int, ...]
    detail: str


def _point(point) -> Point:
    return (point.x, point.y)


def _normal(a: Point, b: Point) -> Point:
    dx, dy = b[0] - a[0], b[1] - a[1]
    length = math.hypot(dx, dy)
    return (-dy / length, dx / length)


def _unit(a: Point, b: Point) -> Point:
    dx, dy = b[0] - a[0], b[1] - a[1]
    length = math.hypot(dx, dy)
    return (dx / length, dy / length)


def buffered_axis(axis: tuple[Point, ...], radius: float) -> tuple[Point, ...]:
    """Contour simple à joints biseautés autour d'un axe ouvert."""
    if radius <= 0.0:
        raise ValueError("radius doit être strictement positif")
    if len(axis) < 2:
        raise ValueError("un axe doit contenir au moins deux points")
    normals = [_normal(a, b) for a, b in zip(axis, axis[1:])]

    def vertex_offset(index: int) -> Point:
        if index == 0:
            return normals[0]
        if index == len(axis) - 1:
            return normals[-1]
        nx = normals[index - 1][0] + normals[index][0]
        ny = normals[index - 1][1] + normals[index][1]
        norm = math.hypot(nx, ny)
        if norm < EPSILON:
            return normals[index]
        nx, ny = nx / norm, ny / norm
        dot = max(0.72, nx * normals[index][0] + ny * normals[index][1])
        return (nx / dot, ny / dot)

    offsets = [vertex_offset(index) for index in range(len(axis))]
    left = [(point[0] + radius * normal[0], point[1] + radius * normal[1])
            for point, normal in zip(axis, offsets)]
    right = [(point[0] - radius * normal[0], point[1] - radius * normal[1])
             for point, normal in zip(axis, offsets)]
    start_tangent = _unit(axis[0], axis[1])
    end_tangent = _unit(axis[-2], axis[-1])
    for side in (left, right):
        side[0] = (side[0][0] - radius * start_tangent[0],
                   side[0][1] - radius * start_tangent[1])
        side[-1] = (side[-1][0] + radius * end_tangent[0],
                    side[-1][1] + radius * end_tangent[1])
    return tuple(left + list(reversed(right)))


def build_hole_geometry(hole: ElasticHole) -> HoleGeometry:
    axis = tuple(_point(point) for point in hole.axis)
    return HoleGeometry(
        order=hole.order,
        axis=axis,
        core=buffered_axis(axis, hole.width / 2.0),
        rough=buffered_axis(axis, hole.width / 2.0 + hole.rough_margin),
    )


def _cross(a: Point, b: Point, c: Point) -> float:
    return (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])


def _on_segment(point: Point, a: Point, b: Point) -> bool:
    return (abs(_cross(a, b, point)) <= EPSILON
            and min(a[0], b[0]) - EPSILON <= point[0] <= max(a[0], b[0]) + EPSILON
            and min(a[1], b[1]) - EPSILON <= point[1] <= max(a[1], b[1]) + EPSILON)


def segments_intersect(a: Point, b: Point, c: Point, d: Point) -> bool:
    """Intersection fermée : un contact compte comme une intersection."""
    c1, c2 = _cross(a, b, c), _cross(a, b, d)
    c3, c4 = _cross(c, d, a), _cross(c, d, b)
    if ((c1 > EPSILON and c2 < -EPSILON) or (c1 < -EPSILON and c2 > EPSILON)) \
            and ((c3 > EPSILON and c4 < -EPSILON) or (c3 < -EPSILON and c4 > EPSILON)):
        return True
    return ((abs(c1) <= EPSILON and _on_segment(c, a, b))
            or (abs(c2) <= EPSILON and _on_segment(d, a, b))
            or (abs(c3) <= EPSILON and _on_segment(a, c, d))
            or (abs(c4) <= EPSILON and _on_segment(b, c, d)))


def _segments(points: tuple[Point, ...], *, closed: bool = False):
    yield from zip(points, points[1:])
    if closed and len(points) > 2:
        yield points[-1], points[0]


def _point_in_polygon(point: Point, polygon: tuple[Point, ...]) -> bool:
    inside = False
    previous = polygon[-1]
    for current in polygon:
        if _on_segment(point, previous, current):
            return True
        if (current[1] > point[1]) != (previous[1] > point[1]):
            x_cross = ((previous[0] - current[0]) * (point[1] - current[1])
                       / (previous[1] - current[1]) + current[0])
            if point[0] < x_cross:
                inside = not inside
        previous = current
    return inside


def _point_segment_distance(point: Point, a: Point, b: Point) -> float:
    dx, dy = b[0] - a[0], b[1] - a[1]
    length_sq = dx * dx + dy * dy
    if length_sq <= EPSILON:
        return math.dist(point, a)
    ratio = ((point[0] - a[0]) * dx + (point[1] - a[1]) * dy) / length_sq
    ratio = max(0.0, min(1.0, ratio))
    return math.dist(point, (a[0] + ratio * dx, a[1] + ratio * dy))


def segment_distance(a: Point, b: Point, c: Point, d: Point) -> float:
    if segments_intersect(a, b, c, d):
        return 0.0
    return min(
        _point_segment_distance(a, c, d),
        _point_segment_distance(b, c, d),
        _point_segment_distance(c, a, b),
        _point_segment_distance(d, a, b),
    )


def polygon_gap(first: tuple[Point, ...], second: tuple[Point, ...]) -> float:
    best = min(segment_distance(a, b, c, d)
               for a, b in _segments(first, closed=True)
               for c, d in _segments(second, closed=True))
    if best > EPSILON and (_point_in_polygon(first[0], second)
                           or _point_in_polygon(second[0], first)):
        return 0.0
    return best


def _point_polygon_distance(point: Point, polygon: tuple[Point, ...]) -> float:
    if _point_in_polygon(point, polygon):
        return 0.0
    return min(_point_segment_distance(point, a, b)
               for a, b in _segments(polygon, closed=True))


def _projected_overlap(a: Point, b: Point, c: Point, d: Point) -> float:
    ux, uy = b[0] - a[0], b[1] - a[1]
    length = math.hypot(ux, uy)
    unit = (ux / length, uy / length)
    first = sorted((a[0] * unit[0] + a[1] * unit[1],
                    b[0] * unit[0] + b[1] * unit[1]))
    second = sorted((c[0] * unit[0] + c[1] * unit[1],
                     d[0] * unit[0] + d[1] * unit[1]))
    return min(first[1], second[1]) - max(first[0], second[0])


def _aligned(a: Point, b: Point, c: Point, d: Point, angle_deg: float) -> bool:
    ux, uy = b[0] - a[0], b[1] - a[1]
    vx, vy = d[0] - c[0], d[1] - c[1]
    lengths = math.hypot(ux, uy) * math.hypot(vx, vy)
    if lengths <= EPSILON:
        return False
    return abs((ux * vx + uy * vy) / lengths) >= math.cos(math.radians(angle_deg)) - EPSILON


def _aligned_overlap(first: HoleGeometry, second: HoleGeometry,
                     rules: ValidationRules) -> bool:
    """Angle ≤ seuil et recouvrement projeté > seuil, sans exigence de contact.

    Utilisé à la fois par `_side_by_side` (avec contact) et par la détection
    de piles parallèles pour vérifier l'alignement deux à deux d'une série
    entière, y compris entre trous non voisins qui ne se touchent pas.
    """
    return any(
        _aligned(a, b, c, d, rules.parallel_stack_angle_deg)
        and _projected_overlap(a, b, c, d) > rules.parallel_stack_overlap
        for a, b in _segments(first.axis)
        for c, d in _segments(second.axis)
    )


def _side_by_side(first: HoleGeometry, second: HoleGeometry,
                  rules: ValidationRules) -> bool:
    return (_aligned_overlap(first, second, rules)
            and polygon_gap(first.rough, second.rough) <= EPSILON)


def _consecutive_parallel_series(nine_holes: tuple[ElasticHole, ...],
                                 geometries: dict[int, HoleGeometry],
                                 rules: ValidationRules) -> list[Violation]:
    """Séries maximales de trous consécutifs en pile parallèle, dans un nine.

    Une série = trous consécutifs dans l'ordre de jeu, chacun `_side_by_side`
    (contact + alignement) avec le suivant, ET tous les trous de la série
    alignés deux à deux (alignement seul, sans exigence de contact) — ce
    second critère exclut l'éventail qui tourne progressivement (chaque
    voisin aligné, mais les extrémités ne le sont plus). Une violation par
    série maximale strictement plus longue que `max_parallel_stack`.
    """
    count = len(nine_holes)
    geoms = [geometries[hole.order] for hole in nine_holes]
    chain_edge = [_side_by_side(geoms[index], geoms[index + 1], rules)
                  for index in range(count - 1)]
    alignment_cache: dict[tuple[int, int], bool] = {}

    def aligned(i: int, j: int) -> bool:
        key = (i, j)
        if key not in alignment_cache:
            alignment_cache[key] = _aligned_overlap(geoms[i], geoms[j], rules)
        return alignment_cache[key]

    # Fenêtre maximale commençant à chaque indice : extension gloutonne tant
    # que le trou suivant reste chaîné (contact) et aligné avec tous les
    # trous déjà inclus. Ces fenêtres sont croissantes avec l'indice de
    # départ (retirer le premier trou ne peut qu'assouplir les contraintes),
    # donc une fenêtre n'est maximale (non incluse dans la précédente) que
    # si sa fin dépasse strictement celle de la fenêtre précédente.
    ends: list[int] = []
    for start in range(count):
        end = start
        while (end + 1 < count and chain_edge[end]
               and all(aligned(previous, end + 1) for previous in range(start, end + 1))):
            end += 1
        ends.append(end)

    violations: list[Violation] = []
    for start, end in enumerate(ends):
        if start > 0 and end <= ends[start - 1]:
            continue
        size = end - start + 1
        if size > rules.max_parallel_stack:
            orders = tuple(nine_holes[index].order for index in range(start, end + 1))
            violations.append(Violation(
                "parallel_stack", orders,
                f"pile de {size} trous consécutifs > {rules.max_parallel_stack}",
            ))
    return violations


def _segment_crosses_polygon(start: Point, end: Point, polygon: tuple[Point, ...]) -> bool:
    if any(segments_intersect(start, end, a, b)
           for a, b in _segments(polygon, closed=True)):
        return True
    return _point_in_polygon(start, polygon) or _point_in_polygon(end, polygon)


def _validate_nine_pars(layout: CourseLayout, rules: ValidationRules) -> list[Violation]:
    violations = []
    for name, nine in (("front", layout.front), ("back", layout.back)):
        counts = Counter(hole.par for hole in nine.holes)
        for par, bounds in ((3, rules.par3_per_nine), (5, rules.par5_per_nine)):
            if not bounds[0] <= counts[par] <= bounds[1]:
                violations.append(Violation(
                    f"par{par}_per_nine",
                    tuple(hole.order for hole in nine.holes if hole.par == par),
                    f"{name}: {counts[par]} par {par}, attendu dans [{bounds[0]}, {bounds[1]}]",
                ))
    return violations


def validate(layout: CourseLayout, rules: ValidationRules | None = None) -> list[Violation]:
    """Retourne toutes les violations finales, dans un ordre déterministe."""
    rules = rules or ValidationRules(width=layout.width, height=layout.height)
    geometries = {hole.order: build_hole_geometry(hole) for hole in layout.holes}
    violations: list[Violation] = []

    if abs(layout.width - rules.width) > EPSILON or abs(layout.height - rules.height) > EPSILON:
        violations.append(Violation(
            "map_size", (),
            f"layout {layout.width:g}x{layout.height:g}, règles {rules.width:g}x{rules.height:g}",
        ))

    clubhouse = _point(layout.clubhouse)
    for hole in layout.holes:
        geometry = geometries[hole.order]
        spec = PAR_SPECS[hole.par]
        if not spec.accepts_length(hole.length):
            violations.append(Violation(
                "length", (hole.order,),
                f"longueur {hole.length:.2f}, attendue dans [{spec.length_min:.2f}, {spec.length_max:.2f}]",
            ))
        if not spec.accepts_width(hole.width):
            violations.append(Violation(
                "width", (hole.order,),
                f"largeur {hole.width:.2f}, attendue dans [{spec.width_min:.2f}, {spec.width_max:.2f}]",
            ))
        if any(point[0] < rules.edge_min - EPSILON
               or point[0] > rules.width - rules.edge_min + EPSILON
               or point[1] < rules.edge_min - EPSILON
               or point[1] > rules.height - rules.edge_min + EPSILON
               for point in geometry.core):
            violations.append(Violation(
                "bounds", (hole.order,),
                f"cœur à moins de {rules.edge_min:.2f} bloc du bord",
            ))
        if rules.clubhouse_clear_radius is not None:
            distance = _point_polygon_distance(clubhouse, geometry.core)
            if distance < rules.clubhouse_clear_radius - EPSILON:
                violations.append(Violation(
                    "clubhouse_clear", (hole.order,),
                    f"cœur à {distance:.2f} blocs du clubhouse, minimum {rules.clubhouse_clear_radius:.2f}",
                ))

    for index, first in enumerate(layout.holes):
        first_geometry = geometries[first.order]
        for second in layout.holes[index + 1:]:
            second_geometry = geometries[second.order]
            pair = (first.order, second.order)
            if any(segments_intersect(a, b, c, d)
                   for a, b in _segments(first_geometry.axis)
                   for c, d in _segments(second_geometry.axis)):
                violations.append(Violation("axis_crossing", pair, "axes en intersection"))
            gap = polygon_gap(first_geometry.core, second_geometry.core)
            if gap < rules.fairway_gap - EPSILON:
                violations.append(Violation(
                    "fairway_gap", pair,
                    f"écart fairway {gap:.2f}, minimum {rules.fairway_gap:.2f}",
                ))

    if rules.max_parallel_stack is not None:
        for nine in (layout.front, layout.back):
            violations.extend(_consecutive_parallel_series(nine.holes, geometries, rules))

    violations.extend(_validate_nine_pars(layout, rules))

    for link in layout.links:
        owners = tuple(order for order in (link.from_hole_order, link.to_hole_order)
                       if order is not None)
        if not rules.link_min - EPSILON <= link.length <= rules.link_max + EPSILON:
            violations.append(Violation(
                "link_distance", owners,
                f"liaison {link.length:.2f}, attendue dans [{rules.link_min:.2f}, {rules.link_max:.2f}]",
            ))
        if rules.walkable_links:
            start, end = _point(link.start), _point(link.end)
            owner_set = set(owners)
            for hole in layout.holes:
                if hole.order in owner_set:
                    continue
                if _segment_crosses_polygon(start, end, geometries[hole.order].core):
                    violations.append(Violation(
                        "link_blocked", tuple(sorted((*owners, hole.order))),
                        f"liaison {owners} traverse le fairway du trou {hole.order}",
                    ))

    return violations
