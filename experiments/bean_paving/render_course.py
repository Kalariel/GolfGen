"""Rendu du meilleur état coordonné front/back."""

from __future__ import annotations

import argparse
import math
from pathlib import Path

from experiments.bean_paving.course_solver import CourseSolveResult, solve_course
from experiments.bean_paving.geometry import ValidationRules, validate
from experiments.bean_paving.solver import SolverParams

PAR_COLORS = {3: "#58a6ff", 4: "#56d364", 5: "#f2cc60"}


def render_course_svg(result: CourseSolveResult, rules: ValidationRules | None = None, *,
                      theta_deg: float | None = None, band: float | None = None) -> str:
    """``rules`` ne sert qu'au rendu (mode ``shared_rough`` : distinction
    cœur/rough, surlignage des piles ``parallel_stack``) ; la recherche a
    déjà utilisé ses propres règles passées à ``solve_course``.

    ``theta_deg``/``band`` (facultatifs, repris de ``result.demarcation`` si
    omis) dessinent faiblement la droite de démarcation et sa bande de
    transition (EXPERIMENT_18_HALFPLANE.md, point B) — purement visuel,
    aucun effet sur la recherche déjà effectuée."""
    rules = rules or ValidationRules()
    if theta_deg is None and result.demarcation is not None:
        theta_deg = result.demarcation.get("theta_deg")
    if band is None and result.demarcation is not None:
        band = result.demarcation.get("band")
    size, pad = 800, 24
    map_width = result.front.clubhouse[0] * 2.0
    map_height = result.front.clubhouse[1] * 2.0
    scale = (size - 2 * pad) / max(map_width, map_height)
    point = lambda p: (pad + p[0] * scale, pad + p[1] * scale)
    footer_height = 100 if result.demarcation is not None else 80
    out = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{size}" height="{size + footer_height}">',
           '<rect width="100%" height="100%" fill="#0d1117"/>',
           f'<rect x="{pad}" y="{pad}" width="{map_width * scale}" height="{map_height * scale}" fill="#161b22" stroke="#8b949e"/>',
           '<style>text{font-family:monospace;fill:#c9d1d9}</style>']
    clubhouse_center = result.front.clubhouse
    clubhouse = point(clubhouse_center)
    if theta_deg is not None and band is not None:
        # Droite de démarcation (plein, faible opacité) + bande de transition
        # (pointillé, plus faible encore) : assez longues pour traverser la
        # carte dans tous les cas, le rectangle de fond les coupe au bord.
        rad = math.radians(theta_deg)
        ux, uy = math.cos(rad), math.sin(rad)
        reach = (map_width + map_height)
        half_band = (band / 2.0)
        nx, ny = -uy, ux  # normale (direction perpendiculaire à la droite)
        for offset, opacity, dash in ((0.0, 0.22, "0"), (half_band, 0.12, "4 6"), (-half_band, 0.12, "4 6")):
            cx, cy = clubhouse_center[0] + nx * offset, clubhouse_center[1] + ny * offset
            a = point((cx - ux * reach, cy - uy * reach))
            b = point((cx + ux * reach, cy + uy * reach))
            out.append(f'<line x1="{a[0]:.1f}" y1="{a[1]:.1f}" x2="{b[0]:.1f}" y2="{b[1]:.1f}" '
                       f'stroke="#f778ba" stroke-opacity="{opacity}" stroke-width="1.6" stroke-dasharray="{dash}"/>')
    out.append(f'<circle cx="{clubhouse[0]:.1f}" cy="{clubhouse[1]:.1f}" r="4" fill="#f0f6fc"/>')
    if rules.shared_rough and rules.clubhouse_clear_radius:
        radius_px = rules.clubhouse_clear_radius * scale
        out.append(f'<circle cx="{clubhouse[0]:.1f}" cy="{clubhouse[1]:.1f}" r="{radius_px:.1f}" '
                   f'fill="none" stroke="#f0f6fc" stroke-opacity="0.45" stroke-width="1.2" stroke-dasharray="3 3"/>')
    if rules.clubhouse_block_radius:
        # Disque d'exclusion TOTAL (expérience "disque 25", PLAN.md ligne 6) :
        # distinct du cercle ``clubhouse_clear_radius`` ci-dessus (cœur seul),
        # tracé en rouge pour le différencier visuellement.
        block_radius_px = rules.clubhouse_block_radius * scale
        out.append(f'<circle cx="{clubhouse[0]:.1f}" cy="{clubhouse[1]:.1f}" r="{block_radius_px:.1f}" '
                   f'fill="none" stroke="#ff2d7a" stroke-opacity="0.55" stroke-width="1.6" stroke-dasharray="2 4"/>')
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
    if result.demarcation is not None:
        d = result.demarcation
        out.append(f'<text x="{pad}" y="{size + 90}" font-size="11">demi-plan theta={d["theta_deg"]:.0f}° '
                   f'bande={d["band"]:.0f} · hors-camp={d["wrong_side_holes"]} · '
                   f'paires front-back collées={d["interleave_pairs"]}</text>')
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
    parser.add_argument("--clubhouse-clear-radius", type=float, default=10.0)
    parser.add_argument("--halfplane-weight", type=float, default=0.0)
    parser.add_argument("--halfplane-theta-deg", type=float, default=0.0)
    parser.add_argument("--halfplane-band", type=float, default=40.0)
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
        clubhouse_clear_radius=args.clubhouse_clear_radius,
    )
    result = solve_course(args.seed, front_params, back_params, rules,
                          halfplane_weight=args.halfplane_weight,
                          halfplane_theta_deg=args.halfplane_theta_deg,
                          halfplane_band=args.halfplane_band)
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
