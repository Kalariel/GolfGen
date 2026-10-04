"""CLI et SVG du spike packing puis routing."""

from __future__ import annotations

import argparse
from pathlib import Path

from experiments.bean_paving.geometry import ValidationRules
from experiments.bean_paving.pack_then_route import run_pack_then_route

COLORS = {3: "#58a6ff", 4: "#56d364", 5: "#f2cc60"}


def render_svg(result) -> str:
    packing, routing = result.packing, result.routing
    size, pad = 800, 24
    scale = (size - 2 * pad) / max(packing.rules.width, packing.rules.height)
    point = lambda p: (pad + p[0] * scale, pad + p[1] * scale)
    out = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{size}" height="{size + 80}">',
           '<rect width="100%" height="100%" fill="#0d1117"/>',
           f'<rect x="{pad}" y="{pad}" width="{packing.rules.width * scale}" height="{packing.rules.height * scale}" fill="#161b22" stroke="#8b949e"/>',
           '<style>text{font-family:monospace;fill:#c9d1d9}</style>']
    clubhouse = point((packing.rules.width / 2, packing.rules.height / 2))
    out.append(f'<circle cx="{clubhouse[0]:.1f}" cy="{clubhouse[1]:.1f}" r="9" fill="#f0f6fc"/>')
    for first, second in routing.edges:
        a = point(packing.state.placed[first].green)
        b = point(packing.state.placed[second].tee)
        out.append(f'<line x1="{a[0]:.1f}" y1="{a[1]:.1f}" x2="{b[0]:.1f}" y2="{b[1]:.1f}" stroke="#d29922" stroke-opacity=".45" stroke-dasharray="4 4"/>')
    path_nodes = set(routing.longest_path)
    for index, bean in enumerate(packing.state.placed):
        color = COLORS[bean.template.par]
        polygon = " ".join(f"{point(p)[0]:.1f},{point(p)[1]:.1f}" for p in bean.footprint)
        axis = " ".join(f"{point(p)[0]:.1f},{point(p)[1]:.1f}" for p in bean.axis)
        tee = point(bean.tee)
        emphasis = 1.0 if index in path_nodes else 0.55
        out.extend([
            f'<polygon points="{polygon}" fill="{color}" fill-opacity="{.18 * emphasis:.2f}" stroke="{color}" stroke-opacity="{emphasis}"/>',
            f'<polyline points="{axis}" fill="none" stroke="{color}" stroke-opacity="{emphasis}" stroke-width="2.5"/>',
            f'<text x="{tee[0] + 4:.1f}" y="{tee[1] - 4:.1f}" font-size="10">{index}/p{bean.template.par}</text>',
        ])
    out.append(f'<text x="{pad}" y="{size + 30}" font-size="14">packing {len(packing.state.placed)}/18 · arêtes {len(routing.edges)} · plus long chemin {len(routing.longest_path)}</text>')
    out.append(f'<text x="{pad}" y="{size + 52}" font-size="11">départs clubhouse {list(routing.start_nodes)} · retours {list(routing.return_nodes)}</text>')
    out.append("</svg>")
    return "\n".join(out) + "\n"


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--size", type=float, default=350.0)
    parser.add_argument("--output", type=Path, default=Path("experiments/bean_paving/output"))
    args = parser.parse_args()
    result = run_pack_then_route(args.seed, ValidationRules(width=args.size, height=args.size))
    args.output.mkdir(parents=True, exist_ok=True)
    size_label = int(args.size)
    (args.output / f"seed{args.seed}_pack_then_route_{size_label}.json").write_text(result.to_json(), encoding="utf-8")
    (args.output / f"seed{args.seed}_pack_then_route_{size_label}.svg").write_text(render_svg(result), encoding="utf-8")
    print(f"packing={len(result.packing.state.placed)}/18 edges={len(result.routing.edges)} "
          f"longest={len(result.routing.longest_path)} routed={result.routing.complete}")
