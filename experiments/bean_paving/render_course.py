"""Rendu du meilleur état coordonné front/back."""

from __future__ import annotations

import argparse
from pathlib import Path

from experiments.bean_paving.course_solver import CourseSolveResult, solve_course
from experiments.bean_paving.geometry import ValidationRules, validate
from experiments.bean_paving.solver import SolverParams

PAR_COLORS = {3: "#58a6ff", 4: "#56d364", 5: "#f2cc60"}


def render_course_svg(result: CourseSolveResult, rules: ValidationRules | None = None) -> str:
    """``rules`` ne sert qu'au rendu (mode ``shared_rough`` : distinction
    cœur/rough, surlignage des piles ``parallel_stack``) ; la recherche a
    déjà utilisé ses propres règles passées à ``solve_course``."""
    rules = rules or ValidationRules()
    size, pad = 800, 24
    map_width = result.front.clubhouse[0] * 2.0
    map_height = result.front.clubhouse[1] * 2.0
    scale = (size - 2 * pad) / max(map_width, map_height)
    point = lambda p: (pad + p[0] * scale, pad + p[1] * scale)
    out = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{size}" height="{size + 80}">',
           '<rect width="100%" height="100%" fill="#0d1117"/>',
           f'<rect x="{pad}" y="{pad}" width="{map_width * scale}" height="{map_height * scale}" fill="#161b22" stroke="#8b949e"/>',
           '<style>text{font-family:monospace;fill:#c9d1d9}</style>']
    clubhouse = point(result.front.clubhouse)
    out.append(f'<circle cx="{clubhouse[0]:.1f}" cy="{clubhouse[1]:.1f}" r="10" fill="#f0f6fc"/>')
    nines = [("F", result.front.state.placed, 1.0, "0")]
    if result.back is not None:
        nines.append(("B", result.back.state.placed, 0.72, "6 3"))

    stacked_ids: set[str] = set()
    if rules.shared_rough:
        all_placed = result.front.state.placed + (() if result.back is None else result.back.state.placed)
        for problem in validate(all_placed, rules, check_links=False):
            if problem.kind == "parallel_stack":
                stacked_ids.update(problem.beans)

    for label, beans, opacity, dash in nines:
        for previous, current in zip(beans, beans[1:]):
            a, b = point(previous.green), point(current.tee)
            out.append(f'<line x1="{a[0]:.1f}" y1="{a[1]:.1f}" x2="{b[0]:.1f}" y2="{b[1]:.1f}" stroke="#8b949e" stroke-dasharray="5 4"/>')
        for bean in beans:
            color = PAR_COLORS[bean.template.par]
            rough = " ".join(f"{point(p)[0]:.1f},{point(p)[1]:.1f}" for p in bean.footprint)
            axis = " ".join(f"{point(p)[0]:.1f},{point(p)[1]:.1f}" for p in bean.axis)
            tee, green = point(bean.tee), point(bean.green)
            out.extend([
                f'<polygon points="{rough}" fill="{color}" fill-opacity="{.12 * opacity:.2f}" stroke="{color}" stroke-opacity="{.5 * opacity:.2f}" stroke-dasharray="{dash}"/>',
            ])
            if rules.shared_rough:
                core = " ".join(f"{point(p)[0]:.1f},{point(p)[1]:.1f}" for p in bean.core)
                out.append(f'<polygon points="{core}" fill="{color}" fill-opacity="{.32 * opacity:.2f}" stroke="{color}" stroke-opacity="{opacity}" stroke-width="1.4" stroke-dasharray="{dash}"/>')
                if bean.id in stacked_ids:
                    out.append(f'<polygon points="{core}" fill="none" stroke="#ff2d7a" stroke-opacity="{opacity}" stroke-width="2.4"/>')
            out.extend([
                f'<polyline points="{axis}" fill="none" stroke="{color}" stroke-opacity="{opacity}" stroke-width="2.7"/>',
                f'<circle cx="{tee[0]:.1f}" cy="{tee[1]:.1f}" r="3" fill="#f0f6fc"/>',
                f'<circle cx="{green[0]:.1f}" cy="{green[1]:.1f}" r="4" fill="{color}" stroke="#f0f6fc"/>',
                f'<text x="{tee[0] + 4:.1f}" y="{tee[1] - 4:.1f}" font-size="10">{label}{bean.order}/p{bean.template.par}</text>',
            ])
    back_depth = 0 if result.back is None else result.back.state.depth
    status = "SUCCÈS" if result.complete else "ÉCHEC"
    out.append(f'<text x="{pad}" y="{size + 30}" font-size="14">{status} · seed {result.seed} · front {result.front.state.depth}/9 · back {back_depth}/9</text>')
    out.append(f'<text x="{pad}" y="{size + 52}" font-size="11">violations {list(result.violations)}</text>')
    if rules.shared_rough:
        out.append(f'<text x="{pad}" y="{size + 70}" font-size="11">rough partagé : cœur plein, rough translucide, pile &gt; {rules.max_parallel_stack} en rose · F=plein, B=tirets</text>')
    out.append("</svg>")
    return "\n".join(out) + "\n"


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--size", type=float, default=350.0)
    parser.add_argument("--quick", action="store_true")
    parser.add_argument("--shared-rough", action="store_true")
    parser.add_argument("--fairway-gap", type=float, default=5.0)
    parser.add_argument("--edge-min", type=float, default=1.0)
    parser.add_argument("--max-parallel-stack", type=int, default=3)
    parser.add_argument("--no-stack-limit", action="store_true")
    parser.add_argument("--label", type=str, default="")
    parser.add_argument("--output", type=Path, default=Path("experiments/bean_paving/output"))
    args = parser.parse_args()
    front_params = back_params = None
    if args.quick:
        front_params = SolverParams(
            beam_width=48, departure_angles=(300, 330, 0, 30, 60),
            target_radius_scale=0.9, bbox_weight=0.0004, closure_lookahead=False,
        )
        back_params = SolverParams(
            beam_width=36, candidates_per_par=3, transforms_per_candidate=24,
            departure_angles=tuple(range(0, 360, 30)), start_radii=(44.0, 48.0),
            start_transforms_per_candidate=96, closure_lookahead=False,
        )
    rules = ValidationRules(
        width=args.size, height=args.size, shared_rough=args.shared_rough,
        fairway_gap=args.fairway_gap, edge_min=args.edge_min,
        max_parallel_stack=None if args.no_stack_limit else args.max_parallel_stack,
    )
    result = solve_course(args.seed, front_params, back_params, rules)
    size_label = int(args.size)
    suffix = f"course18_{size_label}"
    if args.label:
        suffix += f"_{args.label}"
    suffix += "" if result.complete else "_failed"
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / f"seed{args.seed}_{suffix}.json").write_text(result.to_json(), encoding="utf-8")
    (args.output / f"seed{args.seed}_{suffix}.svg").write_text(render_course_svg(result, rules), encoding="utf-8")
    back_depth = 0 if result.back is None else result.back.state.depth
    print(f"seed={args.seed} complete={result.complete} front={result.front.state.depth} back={back_depth}")
