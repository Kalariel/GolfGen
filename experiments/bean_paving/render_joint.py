"""Rendu + diagnostics texte du meilleur état d'une recherche conjointe
front/back (``joint_solver.search_joint``). Mirroir de ``render_course.py``,
adapté à ``JointSolveResult`` (une seule paire de ``SearchState`` partagée,
pas deux ``SolveResult`` indépendants)."""

from __future__ import annotations

import argparse
import time
from pathlib import Path

from experiments.bean_paving.course_solver import solve_course_joint
from experiments.bean_paving.geometry import ValidationRules
from experiments.bean_paving.joint_solver import JointSolveResult
from experiments.bean_paving.solver import SolverParams

PAR_COLORS = {3: "#58a6ff", 4: "#56d364", 5: "#f2cc60"}


def render_joint_svg(result: JointSolveResult) -> str:
    size, pad = 800, 24
    map_width = result.clubhouse[0] * 2.0
    map_height = result.clubhouse[1] * 2.0
    scale = (size - 2 * pad) / max(map_width, map_height)
    point = lambda p: (pad + p[0] * scale, pad + p[1] * scale)
    out = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{size}" height="{size + 80}">',
           '<rect width="100%" height="100%" fill="#0d1117"/>',
           f'<rect x="{pad}" y="{pad}" width="{map_width * scale}" height="{map_height * scale}" fill="#161b22" stroke="#8b949e"/>',
           '<style>text{font-family:monospace;fill:#c9d1d9}</style>']
    clubhouse = point(result.clubhouse)
    out.append(f'<circle cx="{clubhouse[0]:.1f}" cy="{clubhouse[1]:.1f}" r="10" fill="#f0f6fc"/>')
    nines = [("F", result.state.front.placed, 1.0), ("B", result.state.back.placed, 0.72)]
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
    status = "SUCCÈS" if result.complete else "ÉCHEC"
    out.append(f'<text x="{pad}" y="{size + 30}" font-size="14">{status} · seed {result.seed} · front {result.state.front.depth}/9 · back {result.state.back.depth}/9</text>')
    out.append(f'<text x="{pad}" y="{size + 52}" font-size="11">violations {list(result.violations)}</text>')
    out.append("</svg>")
    return "\n".join(out) + "\n"


def print_diagnostics(result: JointSolveResult, elapsed: float) -> None:
    print(f"seed={result.seed} complete={result.complete} "
          f"front={result.state.front.depth}/9 back={result.state.back.depth}/9 "
          f"trials={result.total_trials} time={elapsed:.1f}s")
    if result.violations:
        print(f"violations: {list(result.violations)}")
    last_step = result.diagnostics[-1].global_step if result.diagnostics else 0
    died = last_step < 18 and (not result.diagnostics or result.diagnostics[-1].kept == 0)
    print(f"beam died at global_step={last_step}" if died else f"beam reached global_step={last_step} (loop end)")
    # Sous l'alternance stricte (depth le plus petit d'abord, égalité -> front),
    # le trou 1 du front est toujours au global_step=1 et celui du back au
    # global_step=2 : seul ce côté avance tant que l'autre n'a pas bougé.
    first_front = result.diagnostics[0].front if result.diagnostics else None
    first_back = result.diagnostics[1].back if len(result.diagnostics) > 1 else None
    if first_front:
        print(f"  first hole FRONT (clubhouse departure): trials={first_front.trials} "
              f"accepted={first_front.accepted} rejected={dict(sorted(first_front.rejection_counts.items()))}")
    if first_back:
        print(f"  first hole BACK (clubhouse departure): trials={first_back.trials} "
              f"accepted={first_back.accepted} rejected={dict(sorted(first_back.rejection_counts.items()))}")
    for item in result.diagnostics:
        for label, side in (("front", item.front), ("back", item.back)):
            if side.parents == 0:
                continue
            print(f"  step={item.global_step:2d} {label:5s} parents={side.parents:3d} "
                  f"trials={side.trials:4d} accepted={side.accepted:3d} "
                  f"rejected={dict(sorted(side.rejection_counts.items()))}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--size", type=float, default=350.0)
    parser.add_argument("--beam-width", type=int, default=56)
    parser.add_argument("--freespace-weight", type=float, default=1.0)
    parser.add_argument("--freespace-min-corridor", type=float, default=15.0)
    parser.add_argument("--freespace-pool-width", type=int, default=240)
    parser.add_argument("--quota-pressure-weight", type=float, default=0.0)
    parser.add_argument("--label", type=str, default="")
    parser.add_argument("--output", type=Path, default=Path("experiments/bean_paving/output"))
    args = parser.parse_args()

    params = SolverParams(
        beam_width=args.beam_width,
        freespace_weight=args.freespace_weight,
        freespace_min_corridor=args.freespace_min_corridor,
        freespace_pool_width=args.freespace_pool_width,
        quota_pressure_weight=args.quota_pressure_weight,
    )
    rules = ValidationRules(width=args.size, height=args.size)

    start = time.perf_counter()
    result = solve_course_joint(args.seed, params, rules)
    elapsed = time.perf_counter() - start

    print_diagnostics(result, elapsed)

    size_label = int(args.size)
    suffix = f"joint_{size_label}" + (f"_{args.label}" if args.label else "")
    suffix += "" if result.complete else "_failed"
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / f"seed{args.seed}_{suffix}.json").write_text(result.to_json(), encoding="utf-8")
    (args.output / f"seed{args.seed}_{suffix}.svg").write_text(render_joint_svg(result), encoding="utf-8")
