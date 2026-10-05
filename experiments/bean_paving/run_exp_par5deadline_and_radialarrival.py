"""Deux expériences INDÉPENDANTES (PLAN.md ligne 6, décision utilisateur),
seeds 1 à 5, 400×400, même baseline commune « back-far »
(``output/benchmark_course18_400_backfar_1_10``, config B + back_clubhouse_max=100
+ back_start_radii=(44,48,64,80,96) : sur les seeds 1-5, baseline = 4/5
complet, seed 4 en échec).

Observation utilisateur sur les SVG de la baseline : avec le quota borné
(``bounded_quota=True``, par3/par5 dans ``[1, 3]`` par nine), le solveur
repousse systématiquement le par5 obligatoire (préfère les par3/par4 plus
faciles), ce qui le force sur les TOUT DERNIERS trous (le filtre
``solver._bounded_quota_filter`` ne force qu'en toute fin de fenêtre
partagée) ; le trou 9 (et le dernier trou du back en échec) est alors très
souvent un par5 qui contourne le clubhouse pour s'y refermer -- tous les
échecs observés portent sur ce DERNIER par5 à placer.

EXP A -- DEADLINE PAR5 (``solver.SolverParams.par5_deadline=7``) : le
MINIMUM de par5 de chaque nine doit être posé au plus tard au trou 7 (les
trous 8-9/17-18 restent libres : par3, par4, ou un par5 EXCÉDENTAIRE si le
quota le permet). Implémenté dans ``_bounded_quota_filter`` (fenêtre de
forçage propre au par5, distincte de la fenêtre partagée du par3) --
``SolverParams.par5_deadline`` plumbé symétriquement sur les deux nines via
``solve_course(par5_deadline=7)``.

EXP B -- ARRIVÉE RADIALE (``solver.SolverParams.arrival_max_angle_deg=45.0``) :
règle dure sur le trou de clôture de chaque nine (9 et 18) -- mirroir de
``solver._starts_outward`` (départ du trou 1) côté arrivée. Le DERNIER
segment de l'axe du trou (celui qui finit sur le green) doit pointer vers
le clubhouse à moins de 45° : angle entre (a) la direction de ce segment et
(b) la direction de son point de DÉPART vers le clubhouse
(``solver._arrival_angle_deg`` -- 0° = arrivée « de face », en continuant
vers le clubhouse ; 90-180° = le trou longe/s'éloigne du clubhouse au lieu
de s'y diriger). Appliqué dans ``expand_state`` (profondeur 9),
``_has_closing_sequence``/``_has_closing_move`` (dernier pas de la
fermeture anticipée), et ``course_solver._course_violations`` (contrôle
niveau parcours ET validation indépendante, même fonction) --
``SolverParams.arrival_max_angle_deg`` plumbé symétriquement sur les deux
nines via ``solve_course(arrival_max_angle_deg=45.0)``.

Les deux expériences sont strictement INDÉPENDANTES : chacune ne change
que son propre paramètre, tout le reste = baseline back-far à l'identique.

Exécution : les DEUX expériences, 5 seeds chacune (10 jobs), EN PARALLÈLE
(10 process sur 16 cœurs disponibles) -- foreground, une ligne de log par
seed terminé (``flush=True``), pas de notification de fin différée.
"""

from __future__ import annotations

from collections import Counter
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import replace
import json
import math
from pathlib import Path
import time

from experiments.bean_paving.benchmark_course import _last_depths, _largest_parallel_stack, _polygon_area
from experiments.bean_paving.course_solver import CourseSolveResult, _course_violations, solve_course
from experiments.bean_paving.geometry import ValidationRules
from experiments.bean_paving.render_course import render_course_svg
from experiments.bean_paving.solver import SolverParams, _arrival_angle_deg

SEEDS = range(1, 6)
BASELINE_REPORT = Path("experiments/bean_paving/output/benchmark_course18_400_backfar_1_10/report.json")

EXPERIMENTS = {
    "par5deadline": Path("experiments/bean_paving/output/exp_par5deadline_400_1_5"),
    "radialarrival": Path("experiments/bean_paving/output/exp_radialarrival_400_1_5"),
}

PAR5_DEADLINE = 7
ARRIVAL_MAX_ANGLE_DEG = 45.0


def _front_base() -> SolverParams:
    # Baseline back-far : front inchangé.
    return SolverParams(beam_width=72, departure_angles=(300, 330, 0, 30, 60),
                        target_radius_scale=0.9, bbox_weight=0.0004)


def _back_base() -> SolverParams:
    # Config "back-far" (output/benchmark_course18_400_backfar_1_10) :
    # clubhouse_max relevé à 100, rayons de départ étendus, fermeture
    # anticipée dès la profondeur 7 -- posés ici directement (pas via les
    # surcharges de ``solve_course``) pour garder un seul point de vérité,
    # même motif que ``run_exp_departures_and_disk.py``.
    return SolverParams(beam_width=72, candidates_per_par=4, transforms_per_candidate=36,
                        departure_angles=tuple(range(0, 360, 30)), start_radii=(44.0, 48.0, 64.0, 80.0, 96.0),
                        start_transforms_per_candidate=144, clubhouse_max=100.0,
                        closing_lookahead_from=7)


def _rules() -> ValidationRules:
    return ValidationRules(width=400.0, height=400.0, shared_rough=True, fairway_gap=5.0, edge_min=1.0,
                           max_parallel_stack=3, clubhouse_clear_radius=10.0)


def _build_params(experiment: str) -> tuple[SolverParams, SolverParams, ValidationRules]:
    front = _front_base()
    back = _back_base()
    if experiment == "par5deadline":
        front = replace(front, par5_deadline=PAR5_DEADLINE)
        back = replace(back, par5_deadline=PAR5_DEADLINE)
    elif experiment == "radialarrival":
        front = replace(front, arrival_max_angle_deg=ARRIVAL_MAX_ANGLE_DEG)
        back = replace(back, arrival_max_angle_deg=ARRIVAL_MAX_ANGLE_DEG)
    else:
        raise ValueError(experiment)
    return front, back, _rules()


def _run_seed(experiment: str, seed: int):
    start = time.perf_counter()
    front_params, back_params, rules = _build_params(experiment)
    result = solve_course(seed, front_params, back_params, rules, bounded_quota=True)
    return experiment, result, time.perf_counter() - start


def _seed_summary(experiment: str, result: CourseSolveResult, elapsed: float, rules: ValidationRules) -> dict:
    front_placed = result.front.state.placed
    back_placed = () if result.back is None else result.back.state.placed
    all_placed = front_placed + back_placed
    clubhouse = rules.clubhouse
    front_clubhouse_max = result.front.params.clubhouse_max
    back_clubhouse_max = (SolverParams().clubhouse_max if result.back is None
                          else result.back.params.clubhouse_max)
    arrival_max_angle_deg = result.front.params.arrival_max_angle_deg
    par3_bounds = result.front.params.par3_bounds
    par5_bounds = result.front.params.par5_bounds
    independent_violations = _course_violations(
        front_placed, back_placed, rules, clubhouse, front_clubhouse_max, back_clubhouse_max,
        arrival_max_angle_deg=arrival_max_angle_deg, par3_bounds=par3_bounds, par5_bounds=par5_bounds,
    )
    independent_valid = (len(front_placed) == 9 and len(back_placed) == 9 and not independent_violations)

    tee1 = round(math.dist(front_placed[0].tee, clubhouse), 3) if front_placed else None
    green9 = round(math.dist(front_placed[-1].green, clubhouse), 3) if front_placed else None
    tee10 = round(math.dist(back_placed[0].tee, clubhouse), 3) if back_placed else None
    green18 = round(math.dist(back_placed[-1].green, clubhouse), 3) if back_placed else None

    front_angle = round(_arrival_angle_deg(front_placed[-1], clubhouse), 3) if front_placed else None
    back_angle = round(_arrival_angle_deg(back_placed[-1], clubhouse), 3) if back_placed else None
    front_par5_holes = [i + 1 for i, bean in enumerate(front_placed) if bean.template.par == 5]
    back_par5_holes = [i + 1 for i, bean in enumerate(back_placed) if bean.template.par == 5]

    footprint_ratio = (sum(_polygon_area(bean.footprint) for bean in all_placed)
                       / (rules.width * rules.height)) if all_placed else 0.0

    rejection_counts: Counter = Counter()
    for nine in (result.front, result.back):
        if nine is None:
            continue
        for depth in nine.diagnostics:
            rejection_counts.update(depth.rejection_counts)

    return {
        "experiment": experiment,
        "seed": result.seed,
        "success": result.complete,
        "independent_valid": independent_valid,
        "independent_violations": independent_violations,
        "seconds": round(elapsed, 3),
        "front_holes": len(front_placed),
        "back_holes": len(back_placed),
        "front_pars": [bean.template.par for bean in front_placed],
        "back_pars": [bean.template.par for bean in back_placed],
        "front_par5_holes": front_par5_holes,
        "back_par5_holes": back_par5_holes,
        "front_arrival_angle_deg": front_angle,
        "back_arrival_angle_deg": back_angle,
        "footprint_ratio": round(footprint_ratio, 4),
        "largest_parallel_stack": _largest_parallel_stack(all_placed, rules),
        "rejection_counts": dict(sorted(rejection_counts.items())),
        "back_last_depths": () if result.back is None else _last_depths(result.back.diagnostics),
        "front_clubhouse_max": front_clubhouse_max,
        "back_clubhouse_max": back_clubhouse_max,
        "tee1_distance": tee1,
        "green9_distance": green9,
        "back_start_distance": tee10,
        "back_return_distance": green18,
    }


def _baseline_lookup() -> dict[int, dict]:
    if not BASELINE_REPORT.exists():
        return {}
    data = json.loads(BASELINE_REPORT.read_text(encoding="utf-8"))
    return {item["seed"]: item for item in data["seeds"] if item["seed"] in SEEDS}


def _markdown(experiment: str, summaries: list[dict], rules: ValidationRules, total_seconds: float,
             baseline: dict[int, dict]) -> str:
    title = {
        "par5deadline": "Expérience A — deadline par5 (trou 7 max, seeds 1 à 5, 400×400)",
        "radialarrival": "Expérience B — arrivée radiale (seuil 45°, seeds 1 à 5, 400×400)",
    }[experiment]
    success_count = sum(item["success"] for item in summaries)
    independent_valid_count = sum(item["independent_valid"] for item in summaries)
    base_success = sum(1 for seed in SEEDS if baseline.get(seed, {}).get("success"))
    lines = [
        f"# {title}",
        "",
        f"- Succès (18/18) : **{success_count}/5** (baseline back-far seeds 1-5 : **{base_success}/5**)",
        f"- Validation indépendante conforme : **{independent_valid_count}/5**",
        f"- Temps total (10 process, 2 expériences en parallèle) : **{total_seconds:.1f}s**",
        "",
    ]
    if experiment == "par5deadline":
        lines.extend([
            f"- Deadline : le minimum de par5 (``par5_bounds[0]``, 1 par défaut) doit être atteint "
            f"au plus tard au trou **{PAR5_DEADLINE}** sur les deux nines ; au-delà, seul un par5 "
            "EXCÉDENTAIRE (au-dessus du minimum) reste permis. Reste = baseline back-far.",
            "",
        ])
    else:
        lines.extend([
            f"- Seuil : le dernier segment de l'axe des trous 9 et 18 doit pointer vers le clubhouse "
            f"à moins de **{ARRIVAL_MAX_ANGLE_DEG:.0f}°** (angle entre ce segment et la direction de "
            "son point de départ vers le clubhouse -- mirroir du départ du trou 1). Reste = baseline "
            "back-far.",
            "",
        ])
    lines.extend([
        "| Seed | Résultat | Front | Back | Temps | Tee1→club | Green9→club | Tee10→club | "
        "Green18→club | Angle trou 9 | Angle trou 18 | Indép. | Base (back-far) |",
        "|---:|:---:|:---:|:---:|---:|---:|---:|---:|---:|---:|---:|:---:|:---:|",
    ])
    for item in summaries:
        base = baseline.get(item["seed"], {})
        base_text = (f"{'OK' if base.get('success') else 'échec'} {base.get('seconds', 0):.1f}s"
                    if base else "—")
        result = "OK" if item["success"] else "échec"
        indep = "OK" if item["independent_valid"] else "KO"
        tee1 = f"{item['tee1_distance']:.1f}" if item["tee1_distance"] is not None else "—"
        green9 = f"{item['green9_distance']:.1f}" if item["green9_distance"] is not None else "—"
        tee10 = f"{item['back_start_distance']:.1f}" if item["back_start_distance"] is not None else "—"
        green18 = f"{item['back_return_distance']:.1f}" if item["back_return_distance"] is not None else "—"
        angle9 = (f"{item['front_arrival_angle_deg']:.1f}°"
                 if item["front_arrival_angle_deg"] is not None else "—")
        angle18 = (f"{item['back_arrival_angle_deg']:.1f}°"
                  if item["back_arrival_angle_deg"] is not None else "—")
        lines.append(
            f"| {item['seed']} | {result} | {item['front_holes']}/9 | {item['back_holes']}/9 | "
            f"{item['seconds']:.1f}s | {tee1} | {green9} | {tee10} | {green18} | {angle9} | {angle18} | "
            f"{indep} | {base_text} |")

    lines.extend(["", "## Comparaison seed par seed à la baseline back-far", ""])
    for item in summaries:
        base = baseline.get(item["seed"])
        if base is None:
            lines.append(f"- seed {item['seed']} : baseline absente, pas de comparaison.")
            continue
        delta_t = item["seconds"] - base["seconds"]
        same_success = item["success"] == base["success"]
        lines.append(
            f"- seed {item['seed']} : {'OK' if item['success'] else 'échec'} "
            f"({'identique' if same_success else 'DIFFÉRENT'} de la baseline "
            f"{'OK' if base['success'] else 'échec'}), temps {item['seconds']:.1f}s vs "
            f"{base['seconds']:.1f}s (baseline), delta {delta_t:+.1f}s.")

    lines.extend(["", "## Pars par nine (ordre de jeu) -- trous 9 et 18 en gras", ""])
    for item in summaries:
        front_pars = item["front_pars"]
        back_pars = item["back_pars"]
        front = "-".join(f"**{p}**" if i == len(front_pars) - 1 else str(p)
                         for i, p in enumerate(front_pars)) or "—"
        back = "-".join(f"**{p}**" if i == len(back_pars) - 1 else str(p)
                        for i, p in enumerate(back_pars)) or "—"
        lines.append(f"- seed {item['seed']} : front {front} / back {back}")

    lines.extend(["", "## Par5 — trous de pose (play order, 1-indexé)", ""])
    for item in summaries:
        front_holes = item["front_par5_holes"] or "—"
        back_holes = item["back_par5_holes"] or "—"
        lines.append(f"- seed {item['seed']} : front par5 aux trous {front_holes} / "
                     f"back par5 aux trous {back_holes}")

    lines.extend(["", "## Rejets cumulés", ""])
    all_rejections: Counter = Counter()
    for item in summaries:
        all_rejections.update(item["rejection_counts"])
    for kind, count in sorted(all_rejections.items()):
        lines.append(f"- `{kind}` : {count}")

    lines.extend(["", "## Back — 3 dernières profondeurs explorées (causes de rejet)", ""])
    for item in summaries:
        lines.append(f"- seed {item['seed']} :")
        for depth_info in item.get("back_last_depths", ()):
            dominant = list(depth_info["rejection_counts"].items())[:3]
            dominant_text = ", ".join(f"{kind} {count}" for kind, count in dominant) or "—"
            lines.append(
                f"  - profondeur {depth_info['depth']} : {depth_info['trials']} essais, "
                f"{depth_info['accepted']} acceptés, {depth_info['kept']} gardés — {dominant_text}")

    failures = [item for item in summaries if not item["success"]]
    if failures:
        lines.extend(["", "## Échecs — causes dominantes", ""])
        for item in failures:
            dominant = sorted(item["rejection_counts"].items(), key=lambda kv: -kv[1])[:3]
            dominant_text = ", ".join(f"{kind} {count}" for kind, count in dominant) or "—"
            lines.append(f"- seed {item['seed']} : front {item['front_holes']}/9, "
                         f"back {item['back_holes']}/9 — causes dominantes : {dominant_text}")
    lines.append("")
    return "\n".join(lines)


def main() -> None:
    baseline = _baseline_lookup()
    jobs = [(experiment, seed) for experiment in EXPERIMENTS for seed in SEEDS]
    total_start = time.perf_counter()
    completed: dict[str, dict[int, tuple[CourseSolveResult, float]]] = {name: {} for name in EXPERIMENTS}

    with ProcessPoolExecutor(max_workers=10) as executor:
        futures = {executor.submit(_run_seed, experiment, seed): (experiment, seed) for experiment, seed in jobs}
        for future in as_completed(futures):
            experiment, result, elapsed = future.result()
            completed[experiment][result.seed] = (result, elapsed)
            back_depth = 0 if result.back is None else result.back.state.depth
            print(f"[{experiment}] seed {result.seed}: {'OK' if result.complete else 'échec'} "
                  f"front={result.front.state.depth}/9 back={back_depth}/9 temps={elapsed:.1f}s "
                  f"({sum(len(v) for v in completed.values())}/{len(jobs)} terminés)", flush=True)

    total_seconds = round(time.perf_counter() - total_start, 3)

    for experiment, output_dir in EXPERIMENTS.items():
        _, _, rules = _build_params(experiment)
        output_dir.mkdir(parents=True, exist_ok=True)
        summaries = []
        for seed in sorted(completed[experiment]):
            result, elapsed = completed[experiment][seed]
            summary = _seed_summary(experiment, result, elapsed, rules)
            summaries.append(summary)
            suffix = "course18_400" + ("" if result.complete else "_failed")
            (output_dir / f"seed{seed}_{suffix}.json").write_text(result.to_json(), encoding="utf-8")
            (output_dir / f"seed{seed}_{suffix}.svg").write_text(render_course_svg(result, rules),
                                                                  encoding="utf-8")
        success_count = sum(item["success"] for item in summaries)
        independent_valid_count = sum(item["independent_valid"] for item in summaries)
        report = {
            "experiment": experiment,
            "size": 400,
            "seeds_requested": list(SEEDS),
            "rules": {
                "shared_rough": rules.shared_rough,
                "fairway_gap": rules.fairway_gap,
                "edge_min": rules.edge_min,
                "max_parallel_stack": rules.max_parallel_stack,
                "clubhouse_clear_radius": rules.clubhouse_clear_radius,
            },
            "par5_deadline": PAR5_DEADLINE if experiment == "par5deadline" else None,
            "arrival_max_angle_deg": ARRIVAL_MAX_ANGLE_DEG if experiment == "radialarrival" else None,
            "success_count": success_count,
            "independent_valid_count": independent_valid_count,
            "total_seconds_both_experiments": total_seconds,
            "seeds": summaries,
        }
        (output_dir / "report.json").write_text(json.dumps(report, indent=2, sort_keys=True) + "\n",
                                                 encoding="utf-8")
        (output_dir / "REPORT.md").write_text(
            _markdown(experiment, summaries, rules, total_seconds, baseline), encoding="utf-8")
        print(f"{experiment}: {success_count}/5 complet, {independent_valid_count}/5 validé "
              f"indépendamment (baseline back-far seeds 1-5 : "
              f"{sum(1 for s in SEEDS if baseline.get(s, {}).get('success'))}/5)", flush=True)


if __name__ == "__main__":
    main()
