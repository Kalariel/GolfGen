"""Rendu SVG d'une chaîne locale."""

from __future__ import annotations

import argparse
from pathlib import Path

from experiments.bean_paving.local_placement import LocalPlacementResult, place_local_chain

COLORS = {3: "#58a6ff", 4: "#56d364", 5: "#f2cc60"}


def render_local_svg(result: LocalPlacementResult) -> str:
    size, pad = 700, 20
    scale = (size - 2 * pad) / 350.0
    point = lambda p: (pad + p[0] * scale, pad + p[1] * scale)
    out = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{size}" height="{size + 55}">',
           '<rect width="100%" height="100%" fill="#0d1117"/>',
           f'<rect x="{pad}" y="{pad}" width="{350 * scale}" height="{350 * scale}" fill="#161b22" stroke="#8b949e"/>',
           '<style>text{font-family:monospace;fill:#c9d1d9}</style>']
    clubhouse = point(result.clubhouse)
    out.append(f'<circle cx="{clubhouse[0]:.1f}" cy="{clubhouse[1]:.1f}" r="7" fill="#f0f6fc"/>')
    for previous, current in zip(result.placed, result.placed[1:]):
        a, b = point(previous.green), point(current.tee)
        out.append(f'<line x1="{a[0]:.1f}" y1="{a[1]:.1f}" x2="{b[0]:.1f}" y2="{b[1]:.1f}" stroke="#8b949e" stroke-width="2" stroke-dasharray="6 5"/>')
    for bean in result.placed:
        color = COLORS[bean.template.par]
        polygon = " ".join(f"{point(p)[0]:.1f},{point(p)[1]:.1f}" for p in bean.footprint)
        axis = " ".join(f"{point(p)[0]:.1f},{point(p)[1]:.1f}" for p in bean.axis)
        tee, green = point(bean.tee), point(bean.green)
        out.extend([
            f'<polygon points="{polygon}" fill="{color}" fill-opacity=".24" stroke="{color}" stroke-width="1.5"/>',
            f'<polyline points="{axis}" fill="none" stroke="{color}" stroke-width="3"/>',
            f'<circle cx="{tee[0]:.1f}" cy="{tee[1]:.1f}" r="4" fill="#f0f6fc"/>',
            f'<circle cx="{green[0]:.1f}" cy="{green[1]:.1f}" r="5" fill="{color}" stroke="#f0f6fc"/>',
            f'<text x="{tee[0] + 6:.1f}" y="{tee[1] - 6:.1f}" font-size="13">{bean.order} · p{bean.template.par}</text>',
        ])
    summary = f"seed {result.seed} · {len(result.placed)}/{result.requested} placés · {result.attempts} essais · rejets {result.rejection_counts}"
    out.append(f'<text x="{pad}" y="{size + 35}" font-size="12">{summary}</text>')
    out.append("</svg>")
    return "\n".join(out) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--count", type=int, default=4)
    parser.add_argument("--output", type=Path, default=Path("experiments/bean_paving/output"))
    args = parser.parse_args()
    result = place_local_chain(args.seed, args.count)
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / f"seed{args.seed}_local.json").write_text(result.to_json(), encoding="utf-8")
    (args.output / f"seed{args.seed}_local.svg").write_text(render_local_svg(result), encoding="utf-8")


if __name__ == "__main__":
    main()
