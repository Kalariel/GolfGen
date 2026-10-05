"""Lanceur dédié pour l'essai A/B EXPERIMENT_18_CLOSURE.md (quota fixe +
fermeture anticipée isolée vs quota borné par nine + fermeture anticipée),
``PLAN.md`` ligne 6.

Deux configurations, mêmes règles que ``benchmark_course18_400_1_10``
(400x400, séquentiel, ``shared_rough``, ``fairway_gap=5``, ``edge_min=1``,
``max_parallel_stack=3``, ``clubhouse_clear_radius=10``, poids demi-plan 0),
seeds 2, 8, 9, 1 (les 4 bloquées à 7-8/9 dans le benchmark) :

A) Quota fixe par nine ``2/5/2`` (``free_quota=False``, défaut historique),
   fermeture anticipée du back isolée (``back_closing_lookahead_from=7``,
   jamais testée seule avant ce run -- EXPERIMENT_18_CLOSURE.md, point de
   reprise).
B) Quota borné par nine (``bounded_quota=True``, nouveau, opt-in) : chaque
   nine doit finir avec un compte de par3 et de par5 dans ``[1, 3]``, le
   par4 complétant librement jusqu'à 9 ; total global exact ``4/10/4``.
   Même fermeture anticipée isolée (``back_closing_lookahead_from=7``).

Les 8 runs (2 configs x 4 seeds) tournent en parallèle, un process chacun
(``ProcessPoolExecutor``, 8 workers), temps mesuré en wall-clock réel par
run (``time.perf_counter``), pas une extrapolation."""

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
CONFIGS = ("A", "B")


def _run(config: str, seed: int):
    start = time.perf_counter()
    if config == "A":
        result = solve_course(seed, rules=RULES, free_quota=False,
                              back_closing_lookahead_from=BACK_CLOSING_LOOKAHEAD_FROM)
    else:
        result = solve_course(seed, rules=RULES, bounded_quota=True,
                              back_closing_lookahead_from=BACK_CLOSING_LOOKAHEAD_FROM)
    elapsed = time.perf_counter() - start
    return config, seed, result, elapsed


def _last_depths(diagnostics, count: int = 3) -> list[dict]:
    out = []
    for item in diagnostics[-count:]:
        out.append({
            "depth": item.depth,
            "trials": item.trials,
            "accepted": item.accepted,
            "kept": item.kept,
            "dead_ends": item.dead_ends,
            "rejection_counts": dict(sorted(item.rejection_counts.items(), key=lambda kv: -kv[1])),
            "lookahead_calls": item.lookahead_calls,
            "lookahead_pruned": item.lookahead_pruned,
        })
    return out


def _lookahead_totals(diagnostics) -> dict:
    calls = sum(item.lookahead_calls for item in diagnostics)
    pruned = sum(item.lookahead_pruned for item in diagnostics)
    return {"calls": calls, "pruned": pruned}


def _summarize(config: str, seed: int, result: CourseSolveResult, elapsed: float) -> dict:
    front_placed = result.front.state.placed
    back_placed = () if result.back is None else result.back.state.placed
    clubhouse = RULES.clubhouse
    clubhouse_max = SolverParams().clubhouse_max
    independent_violations = _course_violations(front_placed, back_placed, RULES, clubhouse, clubhouse_max)
    independent_valid = (len(front_placed) == 9 and len(back_placed) == 9 and not independent_violations)
    back_diag = () if result.back is None else result.back.diagnostics
    return {
        "config": config,
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
        "back_last_depths": _last_depths(back_diag),
        "back_lookahead": _lookahead_totals(back_diag),
    }


def main() -> None:
    base = Path("experiments/bean_paving/output/closure_ab_400")
    for config in CONFIGS:
        (base / config).mkdir(parents=True, exist_ok=True)

    jobs = [(config, seed) for config in CONFIGS for seed in SEEDS]
    summaries: dict[str, list[dict]] = {config: [] for config in CONFIGS}
    with ProcessPoolExecutor(max_workers=len(jobs)) as executor:
        futures = {executor.submit(_run, config, seed): (config, seed) for config, seed in jobs}
        for future in as_completed(futures):
            config, seed, result, elapsed = future.result()
            tag = "success" if result.complete else "failed"
            out_dir = base / config
            (out_dir / f"seed{seed}_{tag}.json").write_text(result.to_json(), encoding="utf-8")
            (out_dir / f"seed{seed}_{tag}.svg").write_text(render_course_svg(result, RULES), encoding="utf-8")
            summary = _summarize(config, seed, result, elapsed)
            summaries[config].append(summary)
            print(f"[{config}] seed {seed}: {'OK' if result.complete else 'echec'} "
                  f"front={summary['front_holes']}/9 back={summary['back_holes']}/9 "
                  f"temps={elapsed:.1f}s", flush=True)

    for config in CONFIGS:
        summaries[config].sort(key=lambda item: SEEDS.index(item["seed"]))

    report = {
        "seeds_tried": list(SEEDS),
        "back_closing_lookahead_from": BACK_CLOSING_LOOKAHEAD_FROM,
        "configs": {
            config: {
                "success_count": sum(1 for item in summaries[config] if item["complete"]),
                "summaries": summaries[config],
            }
            for config in CONFIGS
        },
    }
    (base / "summary.json").write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    for config in CONFIGS:
        print(f"closure_ab_400[{config}]: {report['configs'][config]['success_count']}/{len(SEEDS)} complet")


if __name__ == "__main__":
    main()
