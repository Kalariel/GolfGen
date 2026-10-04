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

    @property
    def core(self) -> tuple[Point, ...]:
        """Empreinte du fairway seul (axe bufferisé à ``width / 2``, sans la
        marge de rough) — utilisée uniquement par les règles ``shared_rough``."""
        return tuple(self.transform.point(point) for point in self.template.core_footprint)


@dataclass(frozen=True)
class ValidationRules:
    width: float = 350.0
    height: float = 350.0
    link_min: float = 12.0
    link_max: float = 45.0
    antiparallel_angle_deg: float = 15.0
    antiparallel_distance: float = 30.0
    antiparallel_overlap: float = 40.0
    # Jeu de règles "rough partagé" (désactivé par défaut : comportement et
    # tests existants inchangés). Voir EXPERIMENT_18_ROUGH.md.
    shared_rough: bool = False
    # Écart bord-à-bord minimal entre fairways (cœurs bufferisés de
    # ``fairway_gap / 2`` chacun) : deux fairways ne peuvent jamais se
    # toucher ni se chevaucher, même si leurs roughs se superposent.
    fairway_gap: float = 5.0
    # Le cœur (fairway) doit rester à au moins ``edge_min`` blocs du bord de
    # la carte ; le rough peut sortir de la carte le long du bord.
    edge_min: float = 1.0
    # Deux trous sont "côte à côte" si une paire de segments d'axes est
    # parallèle OU antiparallèle à ``parallel_stack_angle_deg`` près, que
    # leurs roughs se touchent/chevauchent, et que le recouvrement projeté
    # dépasse ``parallel_stack_overlap`` blocs.
    parallel_stack_angle_deg: float = 20.0
    parallel_stack_overlap: float = 40.0
    # Taille maximale d'une composante connexe de la relation "côte à côte",
    # calculée sur TOUS les trous posés, indépendamment de l'ordre de jeu.
    # ``None`` désactive entièrement la règle.
    max_parallel_stack: int | None = 3


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


def polygon_gap(first: tuple[Point, ...], second: tuple[Point, ...]) -> float:
    """Écart bord-à-bord entre deux polygones ; 0.0 s'ils se touchent ou se
    chevauchent. Un seul passage sur les paires de segments (chaque
    ``segment_distance`` détecte déjà le contact), complété par un test de
    confinement bon marché pour le cas "un polygone entièrement dans
    l'autre, aucun bord ne se touche"."""
    best = min(segment_distance(a, b, c, d)
               for a, b in _segments(first, closed=True)
               for c, d in _segments(second, closed=True))
    if best > EPSILON and (_point_in_polygon(first[0], second) or _point_in_polygon(second[0], first)):
        return 0.0
    return best


def _axis_distance(first: tuple[Point, ...], second: tuple[Point, ...]) -> float:
    """Distance exacte (pas un minorant) entre deux axes ouverts — quelques
    segments seulement, donc bon marché même appelée à chaque paire."""
    return min(segment_distance(a, b, c, d)
               for a, b in _segments(first) for c, d in _segments(second))


def _buffered_axis_lower_bound(axis_distance: float, radius_first: float, radius_second: float) -> float:
    """Minorant sûr de l'écart entre deux empreintes bufferisées (rayon
    constant autour de leurs axes) : jamais supérieur à l'écart réel, donc
    un filtre valide pour écarter sans calcul de polygone les paires
    manifestement trop éloignées. Beaucoup plus serré qu'une boîte
    englobante pour des formes longues et étroites tournées dans tous les
    sens (le cas des haricots)."""
    return axis_distance - radius_first - radius_second


def _projected_overlap(a: Point, b: Point, c: Point, d: Point) -> float:
    """Recouvrement de ``c, d`` projeté sur la direction unitaire de ``a, b``."""
    ux, uy = b[0] - a[0], b[1] - a[1]
    len_u = math.hypot(ux, uy)
    if len_u <= EPSILON:
        return 0.0
    unit = (ux / len_u, uy / len_u)
    first = sorted((a[0] * unit[0] + a[1] * unit[1], b[0] * unit[0] + b[1] * unit[1]))
    second = sorted((c[0] * unit[0] + c[1] * unit[1], d[0] * unit[0] + d[1] * unit[1]))
    return min(first[1], second[1]) - max(first[0], second[0])


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
    return _projected_overlap(a, b, c, d) > rules.antiparallel_overlap


def _parallel_or_antiparallel(a: Point, b: Point, c: Point, d: Point, angle_deg: float) -> bool:
    """Vrai si les deux segments sont alignés (même sens ou opposé) à
    ``angle_deg`` près de 0° ou 180°."""
    ux, uy = b[0] - a[0], b[1] - a[1]
    vx, vy = d[0] - c[0], d[1] - c[1]
    len_u, len_v = math.hypot(ux, uy), math.hypot(vx, vy)
    if len_u <= EPSILON or len_v <= EPSILON:
        return False
    dot = (ux * vx + uy * vy) / (len_u * len_v)
    return abs(dot) >= math.cos(math.radians(angle_deg)) - EPSILON


def _side_by_side(first: PlacedBean, second: PlacedBean, rules: ValidationRules) -> bool:
    """Deux trous sont "côte à côte" (règle ``parallel_stack``) si leurs
    roughs se touchent/chevauchent et qu'une paire de segments d'axes est
    alignée avec un recouvrement projeté suffisant.

    L'alignement d'axes (quelques segments) est vérifié avant l'intersection
    de polygones (O(sommets²)) : la plupart des paires de trous ne sont pas
    alignées, ce qui évite l'étape coûteuse pour elles.
    """
    aligned = any(_parallel_or_antiparallel(a, b, c, d, rules.parallel_stack_angle_deg)
                  and _projected_overlap(a, b, c, d) > rules.parallel_stack_overlap
                  for a, b in _segments(first.axis)
                  for c, d in _segments(second.axis))
    if not aligned:
        return False
    return polygons_intersect(first.footprint, second.footprint)


def _connected_components(ids: Iterable[str], pairs: Iterable[tuple[str, str]]) -> list[list[str]]:
    """Composantes connexes de la relation "côte à côte", sur l'ensemble des
    identifiants fournis (indépendant de l'ordre de jeu)."""
    parent = {bean_id: bean_id for bean_id in ids}

    def find(x: str) -> str:
        while parent[x] != x:
            x = parent[x]
        return x

    for a, b in pairs:
        root_a, root_b = find(a), find(b)
        if root_a != root_b:
            parent[root_a] = root_b

    groups: dict[str, list[str]] = {}
    for bean_id in parent:
        groups.setdefault(find(bean_id), []).append(bean_id)
    return list(groups.values())


def validate(beans: Iterable[PlacedBean], rules: ValidationRules | None = None,
             *, check_links: bool = True) -> list[Violation]:
    """Retourne toutes les violations, sans réparer ni assouplir le résultat."""
    rules = rules or ValidationRules()
    ordered = sorted(beans, key=lambda bean: bean.order)
    violations: list[Violation] = []

    for bean in ordered:
        if rules.shared_rough:
            # Le rough peut sortir de la carte le long du bord ; seul le
            # cœur (fairway) doit rester à ``edge_min`` blocs du bord.
            outside = [p for p in bean.core
                       if p[0] < rules.edge_min - EPSILON or p[0] > rules.width - rules.edge_min + EPSILON
                       or p[1] < rules.edge_min - EPSILON or p[1] > rules.height - rules.edge_min + EPSILON]
            if outside:
                violations.append(Violation(
                    "bounds", (bean.id,),
                    f"{len(outside)} sommet(s) du cœur à moins de {rules.edge_min:.2f} bloc du bord"))
        else:
            outside = [p for p in bean.footprint
                       if p[0] < -EPSILON or p[0] > rules.width + EPSILON
                       or p[1] < -EPSILON or p[1] > rules.height + EPSILON]
            if outside:
                violations.append(Violation("bounds", (bean.id,), f"{len(outside)} sommet(s) hors carte"))

    side_by_side_pairs: list[tuple[str, str]] = []

    for index, first in enumerate(ordered):
        for second in ordered[index + 1:]:
            pair = (first.id, second.id)
            # Distance axe-à-axe (quelques segments) une seule fois par
            # paire : sert de minorant bon marché pour les trois filtres
            # géométriques ci-dessous, nettement plus serré qu'une boîte
            # englobante pour des formes longues tournées dans tous les sens.
            axis_distance = _axis_distance(first.axis, second.axis)
            core_lower_bound = _buffered_axis_lower_bound(
                axis_distance, first.template.width / 2.0, second.template.width / 2.0)
            clearance = first.template.clearance_radius + second.template.clearance_radius

            if rules.shared_rough:
                # Le rough peut chevaucher un autre trou ; seul l'écart
                # entre fairways (cœurs) est une contrainte dure.
                if (core_lower_bound < rules.fairway_gap - EPSILON
                        and polygon_gap(first.core, second.core) < rules.fairway_gap - EPSILON):
                    violations.append(Violation("fairway_gap", pair,
                                                f"écart fairway < {rules.fairway_gap:.2f} blocs"))
            elif (axis_distance - clearance <= EPSILON
                  and polygons_intersect(first.footprint, second.footprint)):
                violations.append(Violation("footprint_collision", pair, "empreintes en contact"))

            crosses = any(segments_intersect(a, b, c, d)
                          for a, b in _segments(first.axis)
                          for c, d in _segments(second.axis))
            if crosses:
                violations.append(Violation("axis_crossing", pair, "axes en intersection"))

            if rules.shared_rough:
                if (axis_distance - clearance <= EPSILON
                        and _side_by_side(first, second, rules)):
                    side_by_side_pairs.append(pair)
            else:
                parallel = any(_antiparallel(a, b, c, d, rules)
                               for a, b in _segments(first.axis)
                               for c, d in _segments(second.axis))
                if parallel:
                    violations.append(Violation("antiparallel", pair, "retour parallèle long et proche"))

    if rules.shared_rough and rules.max_parallel_stack is not None:
        components = _connected_components((bean.id for bean in ordered), side_by_side_pairs)
        for component in components:
            if len(component) > rules.max_parallel_stack:
                violations.append(Violation(
                    "parallel_stack", tuple(sorted(component)),
                    f"pile de {len(component)} trous côte à côte > {rules.max_parallel_stack}"))

    if check_links:
        for previous, current in zip(ordered, ordered[1:]):
            link = math.dist(previous.green, current.tee)
            if link < rules.link_min - EPSILON or link > rules.link_max + EPSILON:
                violations.append(Violation(
                    "link_distance", (previous.id, current.id),
                    f"liaison {link:.2f}, attendue dans [{rules.link_min:.2f}, {rules.link_max:.2f}]",
                ))
    return violations
