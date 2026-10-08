"""Rendu SVG indépendant d'un ``CourseLayout`` et de ses violations."""

from __future__ import annotations

from html import escape

from golfgen.routing.geometry import (
    ValidationRules,
    Violation,
    build_hole_geometry,
    validate,
)
from golfgen.routing.model import CourseLayout


PAR_COLORS = {3: "#58a6ff", 4: "#56d364", 5: "#f2cc60"}


def render_svg(layout: CourseLayout, rules: ValidationRules | None = None,
               violations: tuple[Violation, ...] | None = None) -> str:
    rules = rules or ValidationRules(width=layout.width, height=layout.height)
    violations = tuple(validate(layout, rules) if violations is None else violations)
    violating_orders = {order for violation in violations for order in violation.holes}
    size, padding, footer = 800, 24, 92
    scale = (size - 2 * padding) / max(layout.width, layout.height)

    def point(value):
        return (padding + value[0] * scale, padding + value[1] * scale)

    out = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{size}" height="{size + footer}">',
        '<rect width="100%" height="100%" fill="#0d1117"/>',
        (f'<rect x="{padding}" y="{padding}" width="{layout.width * scale:.1f}" '
         f'height="{layout.height * scale:.1f}" fill="#161b22" stroke="#8b949e"/>'),
        '<style>text{font-family:monospace;fill:#c9d1d9}</style>',
    ]

    clubhouse = point((layout.clubhouse.x, layout.clubhouse.y))
    if rules.clubhouse_clear_radius:
        out.append(
            f'<circle cx="{clubhouse[0]:.1f}" cy="{clubhouse[1]:.1f}" '
            f'r="{rules.clubhouse_clear_radius * scale:.1f}" fill="none" '
            'stroke="#f0f6fc" stroke-opacity="0.45" stroke-dasharray="3 3"/>'
        )

    for link in layout.links:
        start = point((link.start.x, link.start.y))
        end = point((link.end.x, link.end.y))
        out.append(
            f'<line x1="{start[0]:.1f}" y1="{start[1]:.1f}" '
            f'x2="{end[0]:.1f}" y2="{end[1]:.1f}" stroke="#8b949e" '
            'stroke-width="1.2" stroke-dasharray="5 4"/>'
        )

    for hole in layout.holes:
        geometry = build_hole_geometry(hole)
        color = PAR_COLORS[hole.par]
        rough = " ".join(f"{point(value)[0]:.1f},{point(value)[1]:.1f}"
                          for value in geometry.rough)
        core = " ".join(f"{point(value)[0]:.1f},{point(value)[1]:.1f}"
                         for value in geometry.core)
        axis = " ".join(f"{point(value)[0]:.1f},{point(value)[1]:.1f}"
                         for value in geometry.axis)
        tee = point(geometry.axis[0])
        green = point(geometry.axis[-1])
        out.extend([
            (f'<polygon points="{rough}" fill="{color}" fill-opacity="0.12" '
             f'stroke="{color}" stroke-opacity="0.45" stroke-dasharray="5 3"/>'),
            (f'<polygon points="{core}" fill="{color}" fill-opacity="0.32" '
             f'stroke="{color}" stroke-width="1.3"/>'),
            (f'<polyline points="{axis}" fill="none" stroke="{color}" '
             'stroke-width="2.7"/>'),
            f'<circle cx="{tee[0]:.1f}" cy="{tee[1]:.1f}" r="3" fill="#f0f6fc"/>',
            (f'<circle cx="{green[0]:.1f}" cy="{green[1]:.1f}" r="4" '
             f'fill="{color}" stroke="#f0f6fc"/>'),
            (f'<text x="{tee[0] + 4:.1f}" y="{tee[1] - 4:.1f}" '
             f'font-size="10">H{hole.order}/p{hole.par}</text>'),
        ])
        if hole.order in violating_orders:
            out.append(
                f'<polygon points="{core}" fill="none" stroke="#ff2d7a" '
                'stroke-width="2.5"/>'
            )

    out.append(
        f'<circle cx="{clubhouse[0]:.1f}" cy="{clubhouse[1]:.1f}" '
        'r="5" fill="#f0f6fc" stroke="#8b949e"/>'
    )
    status = "VALIDE" if not violations else "INVALIDE"
    kinds = _count_by_first_appearance(violation.kind for violation in violations)
    summary = ", ".join(f"{kind}:{count}" for kind, count in kinds.items()) or "aucune"
    out.extend([
        (f'<text x="{padding}" y="{size + 30}" font-size="14">{status} · '
         f'seed {layout.seed} · violations {len(violations)}</text>'),
        (f'<text x="{padding}" y="{size + 52}" font-size="10">'
         f'{escape(summary)}</text>'),
        (f'<text x="{padding}" y="{size + 72}" font-size="10">'
         'bleu=par3 · vert=par4 · jaune=par5 · rose=trou en violation</text>'),
        "</svg>",
    ])
    return "\n".join(out) + "\n"


def _count_by_first_appearance(values) -> dict[str, int]:
    """Petit compteur ordonné par première apparition, suffisant au rendu."""
    counts: dict[str, int] = {}
    for value in values:
        counts[value] = counts.get(value, 0) + 1
    return counts
