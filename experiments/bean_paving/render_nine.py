"""Rendu du meilleur état du solveur, succès comme échec."""

from __future__ import annotations

import argparse
from pathlib import Path

from experiments.bean_paving.solver import SolveResult, SolverParams, solve_nine

COLORS = {3: "#58a6ff", 4: "#56d364", 5: "#f2cc60"}


def render_nine_svg(result: SolveResult) -> str:
    size, pad = 760, 24
    scale = (size - 2 * pad) / 350.0
    point = lambda p: (pad + p[0] * scale, pad + p[1] * scale)
    out = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{size}" height="{size + 80}">',
           '<rect width="100%" height="100%" fill="#0d1117"/>',
           f'<rect x="{pad}" y="{pad}" width="{350 * scale}" height="{350 * scale}" fill="#161b22" stroke="#8b949e"/>',
           '<style>text{font-family:monospace;fill:#c9d1d9}</style>']
    clubhouse = point(result.clubhouse)
    out.extend([f'<circle cx="{clubhouse[0]:.1f}" cy="{clubhouse[1]:.1f}" r="10" fill="#f0f6fc"/>',
                f'<circle cx="{clubhouse[0]:.1f}" cy="{clubhouse[1]:.1f}" r="{result.params.clubhouse_max * scale:.1f}" fill="none" stroke="#8b949e" stroke-dasharray="4 5"/>'])
    for previous, current in zip(result.state.placed, result.state.placed[1:]):
        a, b = point(previous.green), point(current.tee)
        out.append(f'<line x1="{a[0]:.1f}" y1="{a[1]:.1f}" x2="{b[0]:.1f}" y2="{b[1]:.1f}" stroke="#8b949e" stroke-width="2" stroke-dasharray="5 4"/>')
    for bean in result.state.placed:
        color = COLORS[bean.template.par]
        polygon = " ".join(f"{point(p)[0]:.1f},{point(p)[1]:.1f}" for p in bean.footprint)
        axis = " ".join(f"{point(p)[0]:.1f},{point(p)[1]:.1f}" for p in bean.axis)
        tee, green = point(bean.tee), point(bean.green)
        out.extend([
            f'<polygon points="{polygon}" fill="{color}" fill-opacity=".22" stroke="{color}" stroke-width="1.3"/>',
            f'<polyline points="{axis}" fill="none" stroke="{color}" stroke-width="3"/>',
            f'<circle cx="{tee[0]:.1f}" cy="{tee[1]:.1f}" r="3.5" fill="#f0f6fc"/>',
            f'<circle cx="{green[0]:.1f}" cy="{green[1]:.1f}" r="4.5" fill="{color}" stroke="#f0f6fc"/>',
            f'<text x="{tee[0] + 5:.1f}" y="{tee[1] - 5:.1f}" font-size="12">{bean.order}/p{bean.template.par}</text>',
        ])
    status = "SUCCÈS" if result.complete else "ÉCHEC"
    pars = "-".join(str(bean.template.par) for bean in result.state.placed)
    out.append(f'<text x="{pad}" y="{size + 30}" font-size="14">{status} · seed {result.seed} · profondeur {result.state.depth}/9 · pars {pars}</text>')
    out.append(f'<text x="{pad}" y="{size + 52}" font-size="11">{result.total_trials} essais · score {result.state.score:.2f}</text>')
    out.append("</svg>")
    return "\n".join(out) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--beam", type=int, default=48)
    parser.add_argument("--output", type=Path, default=Path("experiments/bean_paving/output"))
    args = parser.parse_args()
    result = solve_nine(args.seed, SolverParams(beam_width=args.beam))
    args.output.mkdir(parents=True, exist_ok=True)
    suffix = "nine" if result.complete else "nine_failed"
    (args.output / f"seed{args.seed}_{suffix}.json").write_text(result.to_json(), encoding="utf-8")
    (args.output / f"seed{args.seed}_{suffix}.svg").write_text(render_nine_svg(result), encoding="utf-8")
    print(f"seed={args.seed} complete={result.complete} depth={result.state.depth} trials={result.total_trials}")


if __name__ == "__main__":
    main()
