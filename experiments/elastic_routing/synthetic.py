"""Layout manuel déterministe pour tester l'oracle et le rendu de l'étape 2."""

from __future__ import annotations

from experiments.elastic_routing.model import (
    PAR_SPECS,
    ControlPoint,
    CourseLayout,
    ElasticHole,
    NineLayout,
)


NINE_PARS = (3, 4, 4, 4, 4, 5, 5, 4, 3)


def _striped_nine(start_order: int, y_values: tuple[float, ...],
                  start_x: float, direction: int) -> tuple[ElasticHole, ...]:
    holes = []
    x = start_x
    for order, par, y in zip(range(start_order, start_order + 9), NINE_PARS, y_values):
        spec = PAR_SPECS[par]
        length = spec.length_min
        candidate = x + direction * length
        if not 15.0 <= candidate <= 385.0:
            direction *= -1
            candidate = x + direction * length
        holes.append(ElasticHole(
            order=order,
            par=par,
            tee=ControlPoint(x, y),
            green=ControlPoint(candidate, y),
            width=spec.width_min,
        ))
        x = candidate
        direction *= -1
    return tuple(holes)


def build_synthetic_layout(seed: int = 0) -> CourseLayout:
    """Deux bandes lisibles ; valides avec règles permissives, pas finales."""
    clubhouse = ControlPoint(200.0, 200.0)
    front_holes = _striped_nine(1, tuple(range(180, 0, -20)), 100.0, 1)
    back_holes = _striped_nine(10, tuple(range(220, 400, 20)), 300.0, -1)
    return CourseLayout(
        seed=seed,
        width=400.0,
        height=400.0,
        clubhouse=clubhouse,
        front=NineLayout.from_holes(1, clubhouse, front_holes),
        back=NineLayout.from_holes(10, clubhouse, back_holes),
    )
