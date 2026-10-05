"""Lanceur dédié pour le benchmark EXPERIMENT_18_CLOSURE.md (fermeture
anticipée du back + quota global libre, voir ``PLAN.md`` ligne 6).

Reprend ``course_solver.solve_course`` avec ``free_quota=True`` et
``back_closing_lookahead_from`` surchargé, sur un sous-ensemble de seeds
choisi pour ce diagnostic (``benchmark_course18_400_1_10`` : 2, 8, 9 bloqués
à 8/9, 1 bloqué à 7/9). Un process par seed (``ProcessPoolExecutor``), temps
mesuré en wall-clock réel par seed (``time.perf_counter``), pas une
extrapolation.

Sorties, par seed : ``seed{N}_{success|failed}.json`` (``SolveResult``
complet front+back), ``seed{N}_{success|failed}.svg`` (même rendu que
``benchmark_course.py``) ; plus ``summary.json`` agrégé (tous les champs
requis : complétude, trous par nine, pars, essais, temps, causes de rejet
des 3 dernières profondeurs du back, validation indépendante geometry.validate
+ clubhouse)."""

from __future__ import annotations

from concurrent.futures import ProcessPoolExecutor, as_completed
import json
from pathlib import Path
import time

from experiments.bean_paving.course_solver import CourseSolveResult, _course_violations, solve_course
from experiments.bean_paving.geometry import ValidationRules
from experiments.bean_paving.render_course import render_course_svg
from experiments.bean_paving.solver import SolverParams

RULES = ValidationRules(
    width=400.0, height=400.0, shared_rough=True, fairway_gap=5.0, edge_min=1.0,
    max_parallel_stack=3, clubhouse_clear_radius=10.0,
)
SEEDS = (2, 8, 9, 1)
BACK_CLOSING_LOOKAHEAD_FROM = 7


def _run_seed(seed: int, back_closing_lookahead_from: int):
    start = time.perf_counter()
    result = solve_course(seed, rules=RULES, free_quota=True,
                          back_closing_lookahead_from=back_closing_lookahead_from)
    elapsed = time.perf_counter() - start
    return seed, result, elapsed


def _last_depths(result: CourseSolveResult, count: int = 3) -> list[dict]:
    if result.back is None:
        return []
    out = []
    for item in result.back.diagnostics[-count:]:
        out.append({
            "depth": item.depth,
            "trials": item.trials,
            "accepted": item.accepted,
            "kept": item.kept,
            "dead_ends": item.dead_ends,
            "rejection_counts": dict(sorted(item.rejection_counts.items(), key=lambda kv: -kv[1])),
        })
    return out


def _summarize(seed: int, result: CourseSolveResult, elapsed: float) -> dict:
    front_placed = result.front.state.placed
    back_placed = () if result.back is None else result.back.state.placed
    clubhouse = RULES.clubhouse
    clubhouse_max = SolverParams().clubhouse_max
    independent_violations = _course_violations(front_placed, back_placed, RULES, clubhouse, clubhouse_max)
    independent_valid = (len(front_placed) == 9 and len(back_placed) == 9 and not independent_violations)
    return {
        "seed": seed,
        "complete": result.complete,
        "independent_valid": independent_valid,
        "independent_violations": independent_violations,
        "seconds": round(elapsed, 3),
        "front_holes": len(front_placed),
        "back_holes": len(back_placed),
        "front_pars": [bean.template.par for bean in front_placed],
        "back_pars": [bean.template.par for bean in back_placed],
        "front_trials": result.front.total_trials,
        "back_trials": 0 if result.back is None else result.back.total_trials,
        "back_last_depths": _last_depths(result),
    }


def main() -> None:
    output = Path("experiments/bean_paving/output/back_closure_400")
    output.mkdir(parents=True, exist_ok=True)
    summaries = []
    with ProcessPoolExecutor(max_workers=len(SEEDS)) as executor:
        futures = {executor.submit(_run_seed, seed, BACK_CLOSING_LOOKAHEAD_FROM): seed for seed in SEEDS}
        for future in as_completed(futures):
            seed, result, elapsed = future.result()
            tag = "success" if result.complete else "failed"
            (output / f"seed{seed}_{tag}.json").write_text(result.to_json(), encoding="utf-8")
            (output / f"seed{seed}_{tag}.svg").write_text(render_course_svg(result, RULES), encoding="utf-8")
            summary = _summarize(seed, result, elapsed)
            summaries.append(summary)
            print(f"seed {seed}: {'OK' if result.complete else 'échec'} "
                  f"front={summary['front_holes']}/9 back={summary['back_holes']}/9 "
                  f"temps={elapsed:.1f}s", flush=True)

    summaries.sort(key=lambda item: SEEDS.index(item["seed"]))
    report = {
        "seeds_tried": list(SEEDS),
        "back_closing_lookahead_from": BACK_CLOSING_LOOKAHEAD_FROM,
        "free_quota": True,
        "success_count": sum(1 for item in summaries if item["complete"]),
        "summaries": summaries,
    }
    (output / "summary.json").write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"back_closure_400: {report['success_count']}/{len(SEEDS)} complet")


if __name__ == "__main__":
    main()
