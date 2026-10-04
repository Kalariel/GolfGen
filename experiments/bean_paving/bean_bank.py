"""Contrats et génération déterministe d'une banque de haricots abstraits.

Le modèle volontairement minimal conserve la sémantique utile au futur
paveur : un axe orienté tee -> green, une largeur et une marge. L'empreinte
SVG/JSON est le contour de cet axe épaissi de ``largeur / 2 + marge``.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
import json
import math
import random
from typing import Iterable

Point = tuple[float, float]


@dataclass(frozen=True)
class ClassParams:
    count: int
    length_range: tuple[float, float]
    width_range: tuple[float, float]
    turn_choices: tuple[int, ...]
    max_turn_deg: float


@dataclass(frozen=True)
class GenerationParams:
    """Réglages de la banque d'un nine, indépendants de la carte."""

    margin: float = 5.0
    par3: ClassParams = ClassParams(4, (75.0, 110.0), (10.0, 15.0), (0, 0, 1), 24.0)
    par4: ClassParams = ClassParams(10, (120.0, 175.0), (11.0, 17.0), (0, 1, 1, 2), 31.0)
    par5: ClassParams = ClassParams(4, (175.0, 235.0), (12.0, 18.0), (1, 1, 2), 36.0)

    def for_par(self, par: int) -> ClassParams:
        return {3: self.par3, 4: self.par4, 5: self.par5}[par]


@dataclass(frozen=True)
class BeanTemplate:
    id: str
    par: int
    target_length: float
    axis: tuple[Point, ...]
    width: float
    margin: float
    footprint: tuple[Point, ...]
    tee: Point
    green: Point
    tee_heading_deg: float
    green_heading_deg: float
    allow_mirror: bool = True

    @property
    def clearance_radius(self) -> float:
        return self.width / 2.0 + self.margin

    def to_dict(self) -> dict:
        data = asdict(self)
        for key in ("axis", "footprint"):
            data[key] = _round_points(data[key])
        for key in ("tee", "green"):
            data[key] = _round_point(data[key])
        for key in ("target_length", "width", "margin", "tee_heading_deg", "green_heading_deg"):
            data[key] = round(data[key], 4)
        return data


@dataclass(frozen=True)
class BeanBank:
    seed: int
    templates: tuple[BeanTemplate, ...]

    def to_dict(self) -> dict:
        return {"seed": self.seed, "templates": [bean.to_dict() for bean in self.templates]}

    def to_json(self, *, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent, sort_keys=True) + "\n"


def _round_points(points: Iterable[Point]) -> list[list[float]]:
    return [[round(float(x), 4), round(float(y), 4)] for x, y in points]


def _round_point(point: Point) -> list[float]:
    return [round(float(point[0]), 4), round(float(point[1]), 4)]


def _heading(a: Point, b: Point) -> float:
    return math.degrees(math.atan2(b[1] - a[1], b[0] - a[0]))


def _normal(a: Point, b: Point) -> Point:
    dx, dy = b[0] - a[0], b[1] - a[1]
    length = math.hypot(dx, dy)
    return -dy / length, dx / length


def _unit(a: Point, b: Point) -> Point:
    dx, dy = b[0] - a[0], b[1] - a[1]
    length = math.hypot(dx, dy)
    return dx / length, dy / length


def _footprint(axis: tuple[Point, ...], radius: float) -> tuple[Point, ...]:
    """Contour simple à joints biseautés autour d'un axe peu courbé."""
    normals = [_normal(a, b) for a, b in zip(axis, axis[1:])]

    def vertex_offset(index: int) -> Point:
        if index == 0:
            return normals[0]
        if index == len(axis) - 1:
            return normals[-1]
        nx = normals[index - 1][0] + normals[index][0]
        ny = normals[index - 1][1] + normals[index][1]
        norm = math.hypot(nx, ny)
        if norm < 1e-8:
            return normals[index]
        nx, ny = nx / norm, ny / norm
        # Corrige la contraction de la bissectrice sans produire d'onglet long.
        dot = max(0.72, nx * normals[index][0] + ny * normals[index][1])
        return nx / dot, ny / dot

    offsets = [vertex_offset(i) for i in range(len(axis))]
    left = [(p[0] + radius * n[0], p[1] + radius * n[1]) for p, n in zip(axis, offsets)]
    right = [(p[0] - radius * n[0], p[1] - radius * n[1]) for p, n in zip(axis, offsets)]
    start_tangent = _unit(axis[0], axis[1])
    end_tangent = _unit(axis[-2], axis[-1])
    for side in (left, right):
        side[0] = (side[0][0] - radius * start_tangent[0],
                   side[0][1] - radius * start_tangent[1])
        side[-1] = (side[-1][0] + radius * end_tangent[0],
                    side[-1][1] + radius * end_tangent[1])
    return tuple(left + list(reversed(right)))


def _axis_for(rng: random.Random, length: float, turns: int, max_turn_deg: float) -> tuple[Point, ...]:
    """Construit un axe local dont la longueur cumulée vaut ``length``."""
    segment_count = turns + 1
    if segment_count == 1:
        return ((0.0, 0.0), (length, 0.0))

    raw = [rng.uniform(0.82, 1.18) for _ in range(segment_count)]
    lengths = [length * value / sum(raw) for value in raw]
    headings = [0.0]
    previous_sign = rng.choice((-1.0, 1.0))
    for _ in range(turns):
        # Alterner souvent le signe produit des S, le répéter produit un dogleg
        # prolongé. Les amplitudes restent lisibles et sans repli.
        if rng.random() < 0.62:
            previous_sign *= -1.0
        delta = previous_sign * rng.uniform(12.0, max_turn_deg)
        headings.append(max(-52.0, min(52.0, headings[-1] + delta)))

    points: list[Point] = [(0.0, 0.0)]
    for segment_length, heading in zip(lengths, headings):
        angle = math.radians(heading)
        points.append((points[-1][0] + segment_length * math.cos(angle),
                       points[-1][1] + segment_length * math.sin(angle)))
    return tuple(points)


def generate_bank(seed: int, params: GenerationParams | None = None) -> BeanBank:
    """Génère les 18 candidats d'un nine, de façon stable pour une seed."""
    params = params or GenerationParams()
    rng = random.Random(seed)
    templates: list[BeanTemplate] = []

    for par in (3, 4, 5):
        spec = params.for_par(par)
        for index in range(1, spec.count + 1):
            length = rng.uniform(*spec.length_range)
            width = rng.uniform(*spec.width_range)
            turns = rng.choice(spec.turn_choices)
            axis = _axis_for(rng, length, turns, spec.max_turn_deg)
            templates.append(BeanTemplate(
                id=f"s{seed}-p{par}-{index:02d}",
                par=par,
                target_length=length,
                axis=axis,
                width=width,
                margin=params.margin,
                footprint=_footprint(axis, width / 2.0 + params.margin),
                tee=axis[0],
                green=axis[-1],
                tee_heading_deg=_heading(axis[0], axis[1]),
                green_heading_deg=_heading(axis[-2], axis[-1]),
            ))

    # L'ordre de banque ne doit pas révéler artificiellement la classe.
    rng.shuffle(templates)
    return BeanBank(seed=seed, templates=tuple(templates))
