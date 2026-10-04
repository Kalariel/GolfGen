"""Galerie SVG de cas synthétiques du validateur."""

from __future__ import annotations

from pathlib import Path

from experiments.bean_paving.bean_bank import BeanTemplate, _footprint
from experiments.bean_paving.geometry import PlacedBean, Transform, ValidationRules, validate


def _bean(name, axis, width=10.0, margin=5.0):
    axis = tuple(axis)
    return BeanTemplate(name, 4, 100.0, axis, width, margin,
                        _footprint(axis, width / 2 + margin), axis[0], axis[-1], 0.0, 0.0)


def render_gallery() -> str:
    cases = [
        ("valide", [PlacedBean(_bean("A", ((0, 0), (75, 0))), Transform(25, 35), 1),
                    PlacedBean(_bean("B", ((0, 0), (55, 20))), Transform(125, 35), 2)], True),
        ("collision", [PlacedBean(_bean("A", ((0, 0), (90, 0))), Transform(20, 45), 1),
                       PlacedBean(_bean("B", ((0, 0), (75, 0))), Transform(60, 52), 2)], False),
        ("croisement", [PlacedBean(_bean("A", ((0, 0), (90, 0))), Transform(20, 55), 1),
                        PlacedBean(_bean("B", ((0, 0), (70, 0))), Transform(65, 20, 90), 2)], False),
        ("antiparallèle", [PlacedBean(_bean("A", ((0, 0), (100, 0)), 4, 0), Transform(20, 40), 1),
                           PlacedBean(_bean("B", ((0, 0), (100, 0)), 4, 0), Transform(120, 62, 180), 2)], False),
        ("hors carte", [PlacedBean(_bean("A", ((0, 0), (90, 20))), Transform(-4, 18), 1)], False),
        ("liaison trop longue", [PlacedBean(_bean("A", ((0, 0), (60, 0))), Transform(20, 45), 1),
                                 PlacedBean(_bean("B", ((0, 0), (55, 0))), Transform(135, 45), 2)], True),
    ]
    panel_w, panel_h = 230, 145
    out = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{3 * panel_w}" height="{2 * panel_h}">',
           '<rect width="100%" height="100%" fill="#0d1117"/>',
           '<style>text{font-family:monospace;fill:#c9d1d9}.bad{fill:#ff7b72}</style>']
    rules = ValidationRules(width=200, height=110)
    for i, (title, beans, check_links) in enumerate(cases):
        ox, oy = (i % 3) * panel_w, (i // 3) * panel_h
        problems = validate(beans, rules, check_links=check_links)
        kinds = ", ".join(sorted({item.kind for item in problems})) or "aucune violation"
        out.extend([f'<text x="{ox + 12}" y="{oy + 20}" font-size="13">{title}</text>',
                    f'<text class="bad" x="{ox + 12}" y="{oy + 36}" font-size="9">{kinds}</text>',
                    f'<rect x="{ox + 12}" y="{oy + 45}" width="200" height="88" fill="#161b22" stroke="#30363d"/>'])
        for bean in beans:
            poly = " ".join(f"{ox + 12 + x:.1f},{oy + 45 + y * .8:.1f}" for x, y in bean.footprint)
            axis = " ".join(f"{ox + 12 + x:.1f},{oy + 45 + y * .8:.1f}" for x, y in bean.axis)
            out.append(f'<polygon points="{poly}" fill="#238636" fill-opacity=".3" stroke="#3fb950"/>')
            out.append(f'<polyline points="{axis}" fill="none" stroke="#f0f6fc" stroke-width="1.5"/>')
    out.append("</svg>")
    return "\n".join(out) + "\n"


if __name__ == "__main__":
    output = Path("experiments/bean_paving/output/geometry_violations.svg")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(render_gallery(), encoding="utf-8")
