"""Rendu lisible d'un ``CourseLayout`` : bandes de fairway, trous numérotés.

Reprend le langage visuel du rendu « bandes + flèches » de ``regions.py``
(bandes épaisses, flèches de sens, clubhouse en losange) mais pour des trous
réels : bande par trou colorée par par, tee (carré blanc) et green (disque)
visibles, numéro du trou dans un cercle derrière le tee, liaisons en
pointillés, anneaux cibles en pointillés très légers, chemins cibles
non circulaires (``paths``, chemin à lobes du round R2b M2) en pointillés
orange discrets, trous et liaisons en
violation surlignés en rose. Relief en fond (niveaux de gris, eau en bleu).
"""

from __future__ import annotations

from html import escape
from collections.abc import Sequence

import numpy as np

from experiments.elastic_routing.geometry import Violation, build_hole_geometry
from experiments.elastic_routing.model import CourseLayout
from experiments.elastic_routing.regions import _point_and_tangent


Point = tuple[float, float]

PAR_COLORS = {3: "#58a6ff", 4: "#56d364", 5: "#f2cc60"}
VIOLATION_COLOR = "#ff2d7a"
PATH_COLOR = "#ffa657"          # chemin cible à lobes (pointillés)
RELIEF_CELL = 8                 # blocs par case de fond
LABEL_BACKOFF = 11.0            # le numéro est posé derrière le tee (blocs)


def _relief_rects(heightmap: np.ndarray, pt, scale: float, water_level: float | None) -> list[str]:
    h, w = heightmap.shape
    cell = RELIEF_CELL
    trimmed = heightmap[: h - h % cell, : w - w % cell].astype(np.float64)
    means = trimmed.reshape(h // cell, cell, w // cell, cell).mean(axis=(1, 3))
    low, high = float(heightmap.min()), float(heightmap.max())
    span = max(high - low, 1e-9)
    out = []
    size = cell * scale + 0.6
    for row in range(means.shape[0]):
        for col in range(means.shape[1]):
            value = means[row, col]
            x, y = pt((col * cell, row * cell))
            if water_level is not None and value < water_level:
                fill = "#1d4f73"
            else:
                level = int(26 + 44 * (value - low) / span)
                fill = f"#{level:02x}{level + 6:02x}{level:02x}"
            out.append(f'<rect x="{x:.1f}" y="{y:.1f}" width="{size:.1f}" height="{size:.1f}" fill="{fill}"/>')
    return out


def render_readable_svg(layout: CourseLayout, violations: Sequence[Violation] = (), *,
                        heightmap: np.ndarray | None = None,
                        water_level: float | None = None,
                        rings: Sequence[Sequence[Point]] = (),
                        paths: Sequence[Sequence[Point]] = (),
                        title: str = "", subtitle: str = "") -> str:
    size, padding, footer = 800, 24, 88
    scale = (size - 2 * padding) / max(layout.width, layout.height)

    def pt(value: Point) -> tuple[float, float]:
        return (padding + value[0] * scale, padding + value[1] * scale)

    def fmt(points) -> str:
        return " ".join(f"{pt(p)[0]:.1f},{pt(p)[1]:.1f}" for p in points)

    hole_kinds: dict[int, set[str]] = {}
    for violation in violations:
        for order in violation.holes:
            hole_kinds.setdefault(order, set()).add(violation.kind)
    bad_links = {(v.holes if len(v.holes) <= 1 else v.holes[:2])
                 for v in violations if v.kind == "link_distance"}

    out = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{size}" height="{size + footer}">',
        '<rect width="100%" height="100%" fill="#0d1117"/>',
        ('<style>text{font-family:monospace;fill:#f0f6fc}'
         '.num{font-weight:bold;fill:#0d1117}</style>'),
        (f'<rect x="{padding}" y="{padding}" width="{layout.width * scale:.1f}" '
         f'height="{layout.height * scale:.1f}" fill="#22341c"/>'),
    ]
    if heightmap is not None:
        out.extend(_relief_rects(heightmap, pt, scale, water_level))
    out.append(f'<rect x="{padding}" y="{padding}" width="{layout.width * scale:.1f}" '
               f'height="{layout.height * scale:.1f}" fill="none" stroke="#8b949e"/>')

    for ring in rings:
        out.append(f'<polyline points="{fmt(ring)}" fill="none" stroke="#f0f6fc" '
                   'stroke-opacity="0.22" stroke-width="1" stroke-dasharray="2 6"/>')
    for path in paths:
        out.append(f'<polyline points="{fmt(path)}" fill="none" stroke="{PATH_COLOR}" '
                   'stroke-opacity="0.6" stroke-width="1.3" stroke-dasharray="5 4"/>')

    for hole in layout.holes:
        color = PAR_COLORS[hole.par]
        axis = [(p.x, p.y) for p in hole.axis]
        rough_px = (hole.width + 2 * hole.rough_margin) * scale
        out.append(f'<polyline points="{fmt(axis)}" fill="none" stroke="{color}" stroke-opacity="0.16" '
                   f'stroke-width="{rough_px:.1f}" stroke-linejoin="round" stroke-linecap="round"/>')
    for hole in layout.holes:
        color = PAR_COLORS[hole.par]
        axis = [(p.x, p.y) for p in hole.axis]
        out.append(f'<polyline points="{fmt(axis)}" fill="none" stroke="{color}" stroke-opacity="0.8" '
                   f'stroke-width="{hole.width * scale:.1f}" stroke-linejoin="round" stroke-linecap="butt"/>')
        if hole.order in hole_kinds:
            core = build_hole_geometry(hole).core
            out.append(f'<polygon points="{fmt(core)}" fill="none" stroke="{VIOLATION_COLOR}" '
                       'stroke-width="2"/>')
        out.append(f'<polyline points="{fmt(axis)}" fill="none" stroke="#0d1117" stroke-opacity="0.5" '
                   'stroke-width="1"/>')
        length = hole.length
        (x, y), (tx, ty) = _point_and_tangent(axis, length * 0.5)
        nx, ny = -ty, tx
        tip = (x + tx * 5.0, y + ty * 5.0)
        left = (x - tx * 4.0 + nx * 4.0, y - ty * 4.0 + ny * 4.0)
        right = (x - tx * 4.0 - nx * 4.0, y - ty * 4.0 - ny * 4.0)
        out.append(f'<polygon points="{fmt((tip, left, right))}" fill="#0d1117" fill-opacity="0.75"/>')

    club = (layout.clubhouse.x, layout.clubhouse.y)
    for link in layout.links:
        owners = tuple(o for o in (link.from_hole_order, link.to_hole_order) if o is not None)
        bad = owners in bad_links
        stroke = VIOLATION_COLOR if bad else "#e6edf3"
        out.append(f'<polyline points="{fmt(((link.start.x, link.start.y), (link.end.x, link.end.y)))}" '
                   f'fill="none" stroke="{stroke}" stroke-opacity="{0.95 if bad else 0.7}" '
                   f'stroke-width="{2.2 if bad else 1.4}" stroke-dasharray="4 4"/>')

    for hole in layout.holes:
        color = PAR_COLORS[hole.par]
        tee, green = (hole.tee.x, hole.tee.y), (hole.green.x, hole.green.y)
        t = pt(tee)
        g = pt(green)
        out.append(f'<rect x="{t[0] - 4:.1f}" y="{t[1] - 4:.1f}" width="8" height="8" fill="#f0f6fc" '
                   'stroke="#0d1117" stroke-width="1"/>')
        out.append(f'<circle cx="{g[0]:.1f}" cy="{g[1]:.1f}" r="{4.5 * scale:.1f}" fill="#3dbd4e" '
                   'stroke="#f0f6fc" stroke-width="1.5"/>')
        out.append(f'<line x1="{g[0]:.1f}" y1="{g[1]:.1f}" x2="{g[0]:.1f}" y2="{g[1] - 13:.1f}" '
                   'stroke="#f0f6fc" stroke-width="1.2"/>')
        out.append(f'<polygon points="{g[0]:.1f},{g[1] - 13:.1f} {g[0] + 7:.1f},{g[1] - 10.5:.1f} '
                   f'{g[0]:.1f},{g[1] - 8:.1f}" fill="#e5534b"/>')
        _, (tx, ty) = _point_and_tangent([(p.x, p.y) for p in hole.axis], 0.0)
        label = pt((tee[0] - tx * LABEL_BACKOFF, tee[1] - ty * LABEL_BACKOFF))
        label = (min(max(label[0], padding + 10), size - padding - 10),
                 min(max(label[1], padding + 10), size - padding - 10))
        ring_color = VIOLATION_COLOR if hole.order in hole_kinds else "#0d1117"
        out.append(f'<circle cx="{label[0]:.1f}" cy="{label[1]:.1f}" r="10" fill="{color}" '
                   f'stroke="{ring_color}" stroke-width="2"/>')
        out.append(f'<text class="num" x="{label[0]:.1f}" y="{label[1] + 4.5:.1f}" font-size="12.5" '
                   f'text-anchor="middle">{hole.order}</text>')

    c = pt(club)
    out.append(f'<rect x="{c[0] - 10:.1f}" y="{c[1] - 10:.1f}" width="20" height="20" fill="#e5534b" '
               f'stroke="#f0f6fc" stroke-width="2.5" transform="rotate(45 {c[0]:.1f} {c[1]:.1f})"/>')
    out.append(f'<text x="{c[0]:.1f}" y="{c[1] + 4:.1f}" font-size="11" text-anchor="middle" '
               'font-weight="bold">CH</text>')

    counts: dict[str, int] = {}
    for violation in violations:
        counts[violation.kind] = counts.get(violation.kind, 0) + 1
    summary = ", ".join(f"{kind}:{count}" for kind, count in counts.items()) or "aucune"
    out.extend([
        f'<text x="{padding}" y="{size + 18}" font-size="14">{escape(title)}</text>',
        f'<text x="{padding}" y="{size + 38}" font-size="11">{escape(subtitle)}</text>',
        (f'<text x="{padding}" y="{size + 56}" font-size="11">violations {len(violations)} · '
         f'{escape(summary)}</text>'),
        (f'<text x="{padding}" y="{size + 76}" font-size="11">bleu=par3 · vert=par4 · jaune=par5 · '
         '□ tee · ● green · pointillés = liaisons · rose = violation</text>'),
        "</svg>",
    ])
    return "\n".join(out) + "\n"
