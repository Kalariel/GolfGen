"""Recherche d'orientation du biais de demi-plan (EXPERIMENT_18_HALFPLANE.md,
point C).

Lance ``solve_course`` indépendamment pour plusieurs angles ``theta`` (une
droite de démarcation différente par angle), en parallèle (processus) pour
tenir le budget : chaque run est déterministe par ``(seed, theta)`` et ne
partage aucun état mutable avec les autres, donc la parallélisation ne
change jamais le résultat — seulement le temps total. Sélectionne ensuite le
meilleur run : un 18/18 validé d'abord, sinon le plus de trous posés, égalité
tranchée par le score (plus bas = meilleur, convention du beam search de
``solver.py``).
"""

from __future__ import annotations

import argparse
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass
import json
from pathlib import Path
import time

from experiments.bean_paving.course_solver import CourseSolveResult, solve_course
from experiments.bean_paving.geometry import ValidationRules
from experiments.bean_paving.render_course import render_course_svg
from experiments.bean_paving.solver import SolverParams

DEFAULT_THETAS: tuple[float, ...] = (0.0, 90.0, 180.0, 270.0)


@dataclass(frozen=True)
class OrientationRun:
    theta_deg: float
    result: CourseSolveResult
    elapsed_s: float

    @property
    def holes_placed(self) -> int:
        back_depth = 0 if self.result.back is None else self.result.back.state.depth
        return self.result.front.state.depth + back_depth

    @property
    def total_score(self) -> float:
        back_score = 0.0 if self.result.back is None else self.result.back.state.score
        return self.result.front.state.score + back_score


def _sort_key(run: OrientationRun) -> tuple[int, int, float]:
    """0 d'abord pour un run validé 18/18 (``complete``) ; puis le plus de
    trous posés (négatif pour trier par ordre croissant) ; puis le score le
    plus bas en dernier recours."""
    return (0 if run.result.complete else 1, -run.holes_placed, run.total_score)


def pick_best(runs: list[OrientationRun]) -> OrientationRun:
    if not runs:
        raise ValueError("aucun run à comparer")
    return min(runs, key=_sort_key)


def _run_one(seed: int, theta_deg: float, halfplane_weight: float, halfplane_band: float,
            rules: ValidationRules, front_params: SolverParams | None,
            back_params: SolverParams | None) -> OrientationRun:
    start = time.monotonic()
    result = solve_course(seed, front_params, back_params, rules,
                          halfplane_weight=halfplane_weight,
                          halfplane_theta_deg=theta_deg,
                          halfplane_band=halfplane_band)
    return OrientationRun(theta_deg, result, time.monotonic() - start)


def search_orientations(seed: int, *, thetas: tuple[float, ...] = DEFAULT_THETAS,
                        halfplane_weight: float, halfplane_band: float = 40.0,
                        rules: ValidationRules | None = None,
                        front_params: SolverParams | None = None,
                        back_params: SolverParams | None = None,
                        max_workers: int | None = None) -> list[OrientationRun]:
    rules = rules or ValidationRules()
    runs: list[OrientationRun] = []
    with ProcessPoolExecutor(max_workers=max_workers or len(thetas)) as pool:
        futures = [
            pool.submit(_run_one, seed, theta, halfplane_weight, halfplane_band,
                       rules, front_params, back_params)
            for theta in thetas
        ]
        for future in futures:
            runs.append(future.result())
    return sorted(runs, key=lambda run: run.theta_deg)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--size", type=float, default=350.0)
    parser.add_argument("--halfplane-weight", type=float, required=True)
    parser.add_argument("--halfplane-band", type=float, default=40.0)
    parser.add_argument("--clubhouse-clear-radius", type=float, default=10.0)
    parser.add_argument("--fairway-gap", type=float, default=5.0)
    parser.add_argument("--edge-min", type=float, default=1.0)
    parser.add_argument("--max-parallel-stack", type=int, default=3)
    parser.add_argument("--output", type=Path, default=Path("experiments/bean_paving/output"))
    args = parser.parse_args()

    rules = ValidationRules(
        width=args.size, height=args.size, shared_rough=True,
        fairway_gap=args.fairway_gap, edge_min=args.edge_min,
        max_parallel_stack=args.max_parallel_stack,
        clubhouse_clear_radius=args.clubhouse_clear_radius,
    )
    runs = search_orientations(args.seed, halfplane_weight=args.halfplane_weight,
                               halfplane_band=args.halfplane_band, rules=rules)

    args.output.mkdir(parents=True, exist_ok=True)
    size_label = int(args.size)
    summary = []
    for run in runs:
        theta_label = int(run.theta_deg)
        status = "success" if run.result.complete else "failed"
        stem = f"seed{args.seed}_halfplane_{size_label}_theta{theta_label}_{status}"
        (args.output / f"{stem}.json").write_text(run.result.to_json(), encoding="utf-8")
        (args.output / f"{stem}.svg").write_text(render_course_svg(run.result, rules), encoding="utf-8")
        back_depth = 0 if run.result.back is None else run.result.back.state.depth
        print(f"theta={run.theta_deg:.0f} complete={run.result.complete} "
             f"front={run.result.front.state.depth} back={back_depth} "
             f"trials_front={run.result.front.total_trials} "
             f"trials_back={0 if run.result.back is None else run.result.back.total_trials} "
             f"elapsed={run.elapsed_s:.1f}s demarcation={run.result.demarcation}")
        summary.append({
            "theta_deg": run.theta_deg, "complete": run.result.complete,
            "front_depth": run.result.front.state.depth, "back_depth": back_depth,
            "elapsed_s": run.elapsed_s, "demarcation": run.result.demarcation,
        })

    best = pick_best(runs)
    print(f"MEILLEUR theta={best.theta_deg:.0f} complete={best.result.complete} "
         f"holes={best.holes_placed}/18 score={best.total_score:.3f}")
    (args.output / f"seed{args.seed}_halfplane_{size_label}_summary.json").write_text(
        json.dumps({"best_theta_deg": best.theta_deg, "runs": summary}, indent=2, sort_keys=True) + "\n",
        encoding="utf-8")
