"""Produit le JSON et la planche SVG d'une banque témoin."""

from __future__ import annotations

import argparse
from html import escape
from pathlib import Path

from experiments.bean_paving.bean_bank import BeanBank, generate_bank


COLORS = {3: "#58a6ff", 4: "#56d364", 5: "#f2cc60"}


def render_bank_svg(bank: BeanBank) -> str:
    cell_w, cell_h = 280, 190
    padding = 22
    width, height = 3 * cell_w, 6 * cell_h
    elements = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
        '<rect width="100%" height="100%" fill="#0d1117"/>',
        '<style>text{font-family:monospace;fill:#c9d1d9}.meta{fill:#8b949e;font-size:11px}</style>',
    ]
    for i, bean in enumerate(bank.templates):
        col, row = i % 3, i // 3
        ox, oy = col * cell_w + padding, row * cell_h + 48
        xs = [p[0] for p in bean.footprint]
        ys = [p[1] for p in bean.footprint]
        scale = min((cell_w - 2 * padding) / max(1.0, max(xs) - min(xs)),
                    (cell_h - 70) / max(1.0, max(ys) - min(ys)))
        tx = ox - min(xs) * scale
        ty = oy + (cell_h - 82) / 2 - (min(ys) + max(ys)) * scale / 2

        def points(values):
            return " ".join(f"{tx + x * scale:.1f},{ty + y * scale:.1f}" for x, y in values)

        color = COLORS[bean.par]
        elements.extend([
            f'<text x="{col * cell_w + padding}" y="{row * cell_h + 22}" font-size="13">{escape(bean.id)}</text>',
            f'<text class="meta" x="{col * cell_w + padding}" y="{row * cell_h + 38}">par {bean.par} · {bean.target_length:.0f} blocs · {len(bean.axis) - 2} virage(s)</text>',
            f'<polygon points="{points(bean.footprint)}" fill="{color}" fill-opacity="0.22" stroke="{color}" stroke-width="1.2"/>',
            f'<polyline points="{points(bean.axis)}" fill="none" stroke="{color}" stroke-width="2.2"/>',
            f'<circle cx="{tx + bean.tee[0] * scale:.1f}" cy="{ty + bean.tee[1] * scale:.1f}" r="4" fill="#f0f6fc"/>',
            f'<circle cx="{tx + bean.green[0] * scale:.1f}" cy="{ty + bean.green[1] * scale:.1f}" r="5" fill="{color}" stroke="#f0f6fc"/>',
        ])
    elements.append("</svg>")
    return "\n".join(elements) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--output", type=Path, default=Path("experiments/bean_paving/output"))
    args = parser.parse_args()
    bank = generate_bank(args.seed)
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / f"seed{args.seed}_bank.json").write_text(bank.to_json(), encoding="utf-8")
    (args.output / f"seed{args.seed}_bank.svg").write_text(render_bank_svg(bank), encoding="utf-8")


if __name__ == "__main__":
    main()
