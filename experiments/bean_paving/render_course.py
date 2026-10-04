"""Rendu du meilleur état coordonné front/back."""

from __future__ import annotations

import argparse
from pathlib import Path

from experiments.bean_paving.course_solver import CourseSolveResult, solve_course

PAR_COLORS = {3: "#58a6ff", 4: "#56d364", 5: "#f2cc60"}


def render_course_svg(result: CourseSolveResult) -> str:
    size, pad = 800, 24
    scale = (size - 2 * pad) / 350.0
    point = lambda p: (pad + p[0] * scale, pad + p[1] * scale)
    out = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{size}" height="{size + 80}">',
           '<rect width="100%" height="100%" fill="#0d1117"/>',
           f'<rect x="{pad}" y="{pad}" width="{350 * scale}" height="{350 * scale}" fill="#161b22" stroke="#8b949e"/>',
           '<style>text{font-family:monospace;fill:#c9d1d9}</style>']
    clubhouse = point(result.front.clubhouse)
    out.append(f'<circle cx="{clubhouse[0]:.1f}" cy="{clubhouse[1]:.1f}" r="10" fill="#f0f6fc"/>')
    nines = [("F", result.front.state.placed, 1.0)]
    if result.back is not None:
        nines.append(("B", result.back.state.placed, 0.72))
    for label, beans, opacity in nines:
        for previous, current in zip(beans, beans[1:]):
            a, b = point(previous.green), point(current.tee)
            out.append(f'<line x1="{a[0]:.1f}" y1="{a[1]:.1f}" x2="{b[0]:.1f}" y2="{b[1]:.1f}" stroke="#8b949e" stroke-dasharray="5 4"/>')
        for bean in beans:
            color = PAR_COLORS[bean.template.par]
            polygon = " ".join(f"{point(p)[0]:.1f},{point(p)[1]:.1f}" for p in bean.footprint)
            axis = " ".join(f"{point(p)[0]:.1f},{point(p)[1]:.1f}" for p in bean.axis)
            tee, green = point(bean.tee), point(bean.green)
            out.extend([
                f'<polygon points="{polygon}" fill="{color}" fill-opacity="{.18 * opacity:.2f}" stroke="{color}" stroke-opacity="{opacity}"/>',
                f'<polyline points="{axis}" fill="none" stroke="{color}" stroke-opacity="{opacity}" stroke-width="2.7"/>',
                f'<circle cx="{tee[0]:.1f}" cy="{tee[1]:.1f}" r="3" fill="#f0f6fc"/>',
                f'<circle cx="{green[0]:.1f}" cy="{green[1]:.1f}" r="4" fill="{color}" stroke="#f0f6fc"/>',
                f'<text x="{tee[0] + 4:.1f}" y="{tee[1] - 4:.1f}" font-size="10">{label}{bean.order}/p{bean.template.par}</text>',
            ])
    back_depth = 0 if result.back is None else result.back.state.depth
    status = "SUCCÈS" if result.complete else "ÉCHEC"
    out.append(f'<text x="{pad}" y="{size + 30}" font-size="14">{status} · seed {result.seed} · front {result.front.state.depth}/9 · back {back_depth}/9</text>')
    out.append(f'<text x="{pad}" y="{size + 52}" font-size="11">violations {list(result.violations)}</text>')
    out.append("</svg>")
    return "\n".join(out) + "\n"


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--output", type=Path, default=Path("experiments/bean_paving/output"))
    args = parser.parse_args()
    result = solve_course(args.seed)
    suffix = "course18" if result.complete else "course18_failed"
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / f"seed{args.seed}_{suffix}.json").write_text(result.to_json(), encoding="utf-8")
    (args.output / f"seed{args.seed}_{suffix}.svg").write_text(render_course_svg(result), encoding="utf-8")
    back_depth = 0 if result.back is None else result.back.state.depth
    print(f"seed={args.seed} complete={result.complete} front={result.front.state.depth} back={back_depth}")
