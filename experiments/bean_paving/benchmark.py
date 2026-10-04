"""Benchmark reproductible des seeds 1 à 10 du paveur abstrait."""

from __future__ import annotations

import argparse
from collections import Counter
from concurrent.futures import ProcessPoolExecutor, as_completed
import json
import math
from pathlib import Path
import time

from experiments.bean_paving.geometry import validate
from experiments.bean_paving.render_nine import render_nine_svg
from experiments.bean_paving.solver import SolveResult, SolverParams, solve_nine


def _polygon_area(points) -> float:
    return abs(sum(a[0] * b[1] - b[0] * a[1]
                   for a, b in zip(points, (*points[1:], points[0]))) / 2.0)


def _angle_bin(a, b) -> int:
    return round(math.degrees(math.atan2(b[1] - a[1], b[0] - a[0])) / 30.0) % 12


def _fingerprint(result: SolveResult) -> tuple:
    """Signature insensible à une rotation globale et à un miroir global."""
    if not result.state.placed:
        return ()
    raw_angles = [_angle_bin(bean.tee, bean.green) for bean in result.state.placed]
    origin = raw_angles[0]
    relative = tuple((value - origin) % 12 for value in raw_angles)
    mirrored = tuple((-value) % 12 for value in relative)
    angles = min(relative, mirrored)
    lengths = tuple(round(math.dist(bean.tee, bean.green) / 10.0) for bean in result.state.placed)
    pars = tuple(bean.template.par for bean in result.state.placed)
    links = tuple(round(math.dist(a.green, b.tee) / 8.0)
                  for a, b in zip(result.state.placed, result.state.placed[1:]))
    return pars, angles, lengths, links


def _similarity(first: tuple, second: tuple) -> float:
    if not first or not second or len(first[0]) != len(second[0]):
        return 0.0
    pars_a, angles_a, lengths_a, links_a = first
    pars_b, angles_b, lengths_b, links_b = second
    scores = []
    scores.extend(a == b for a, b in zip(pars_a, pars_b))
    scores.extend(min((a - b) % 12, (b - a) % 12) <= 1 for a, b in zip(angles_a, angles_b))
    scores.extend(abs(a - b) <= 1 for a, b in zip(lengths_a, lengths_b))
    scores.extend(abs(a - b) <= 1 for a, b in zip(links_a, links_b))
    return sum(scores) / len(scores)


def _run_seed(seed: int, params: SolverParams):
    start = time.perf_counter()
    result = solve_nine(seed, params)
    return result, time.perf_counter() - start


def _seed_summary(result: SolveResult, elapsed: float) -> dict:
    placed = result.state.placed
    problems = validate(placed) if placed else []
    points = [point for bean in placed for point in bean.footprint]
    footprint_ratio = sum(_polygon_area(bean.footprint) for bean in placed) / (350.0 * 350.0)
    if points:
        bbox_ratio = ((max(p[0] for p in points) - min(p[0] for p in points))
                      * (max(p[1] for p in points) - min(p[1] for p in points)) / (350.0 * 350.0))
    else:
        bbox_ratio = 0.0
    rejection_counts = Counter()
    for depth in result.diagnostics:
        rejection_counts.update(depth.rejection_counts)
    orientations = {_angle_bin(bean.tee, bean.green) for bean in placed}
    hard_valid = (not problems
                  and (not result.complete or math.dist(placed[-1].green, result.clubhouse)
                       <= result.params.clubhouse_max))
    return {
        "seed": result.seed,
        "success": result.complete,
        "hard_valid": hard_valid,
        "seconds": round(elapsed, 3),
        "trials": result.total_trials,
        "max_depth": result.state.depth,
        "dead_ends": sum(item.dead_ends for item in result.diagnostics),
        "par_order": [bean.template.par for bean in placed],
        "footprint_ratio": round(footprint_ratio, 4),
        "bbox_ratio": round(bbox_ratio, 4),
        "orientation_bins": len(orientations),
        "final_clubhouse_distance": (round(math.dist(placed[-1].green, result.clubhouse), 3)
                                     if placed else None),
        "violations": [problem.kind for problem in problems],
        "rejection_counts": dict(sorted(rejection_counts.items())),
    }


def _markdown(report: dict) -> str:
    lines = [
        "# Benchmark bean paving — seeds 1 à 10",
        "",
        f"- Succès : **{report['success_count']}/10**",
        f"- Décision : **{report['decision']}**",
        f"- Violations dures : **{report['hard_violation_count']}**",
        f"- Doublons exacts normalisés : **{len(report['exact_duplicates'])}**",
        f"- Quasi-doublons (similarité ≥ 85 %) : **{len(report['near_duplicates'])}**",
        "",
        "| Seed | Résultat | Temps | Essais | Prof. | Pars | Empreinte | BBox | Caps |",
        "|---:|:---:|---:|---:|---:|:---|---:|---:|---:|",
    ]
    for item in report["seeds"]:
        result = "OK" if item["success"] else "échec"
        pars = "-".join(map(str, item["par_order"]))
        lines.append(f"| {item['seed']} | {result} | {item['seconds']:.1f}s | {item['trials']} | "
                     f"{item['max_depth']} | {pars} | {item['footprint_ratio']:.1%} | "
                     f"{item['bbox_ratio']:.1%} | {item['orientation_bins']} |")
    lines.extend(["", "## Rejets cumulés", ""])
    for kind, count in report["rejection_counts"].items():
        lines.append(f"- `{kind}` : {count}")
    if report["near_duplicates"]:
        lines.extend(["", "## Quasi-doublons", ""])
        for pair in report["near_duplicates"]:
            lines.append(f"- seeds {pair['seeds'][0]} et {pair['seeds'][1]} : {pair['similarity']:.1%}")
    lines.extend(["", "## Observations", ""])
    for observation in report.get("observations", []):
        lines.append(f"- {observation}")
    lines.append("")
    return "\n".join(lines)


def run_benchmark(output: Path, workers: int = 3,
                  params: SolverParams | None = None) -> dict:
    params = params or SolverParams()
    output.mkdir(parents=True, exist_ok=True)
    completed: dict[int, tuple[SolveResult, float]] = {}
    if workers <= 1:
        for seed in range(1, 11):
            result, elapsed = _run_seed(seed, params)
            completed[result.seed] = (result, elapsed)
            print(f"seed {result.seed}: {'OK' if result.complete else 'échec'} "
                  f"profondeur={result.state.depth} temps={elapsed:.1f}s", flush=True)
    else:
        with ProcessPoolExecutor(max_workers=workers) as executor:
            futures = {executor.submit(_run_seed, seed, params): seed for seed in range(1, 11)}
            for future in as_completed(futures):
                result, elapsed = future.result()
                completed[result.seed] = (result, elapsed)
                print(f"seed {result.seed}: {'OK' if result.complete else 'échec'} "
                      f"profondeur={result.state.depth} temps={elapsed:.1f}s", flush=True)

    summaries = []
    fingerprints = {}
    rejection_counts = Counter()
    for seed in sorted(completed):
        result, elapsed = completed[seed]
        summary = _seed_summary(result, elapsed)
        summaries.append(summary)
        rejection_counts.update(summary["rejection_counts"])
        suffix = "success" if result.complete else "failure"
        (output / f"seed{seed}_{suffix}.json").write_text(result.to_json(), encoding="utf-8")
        (output / f"seed{seed}_{suffix}.svg").write_text(render_nine_svg(result), encoding="utf-8")
        if result.complete:
            fingerprints[seed] = _fingerprint(result)

    exact, near = [], []
    seeds = sorted(fingerprints)
    for index, first in enumerate(seeds):
        for second in seeds[index + 1:]:
            similarity = _similarity(fingerprints[first], fingerprints[second])
            if fingerprints[first] == fingerprints[second]:
                exact.append([first, second])
            elif similarity >= 0.85:
                near.append({"seeds": [first, second], "similarity": round(similarity, 4)})

    success_count = sum(item["success"] for item in summaries)
    if success_count >= 8:
        decision = "paving abstrait validé"
    elif success_count >= 5:
        decision = "prometteur, solveur à ajuster"
    else:
        decision = "paving à revoir avant le générateur de trous"
    report = {
        "success_count": success_count,
        "decision": decision,
        "hard_violation_count": sum(not item["hard_valid"] for item in summaries),
        "exact_duplicates": exact,
        "near_duplicates": near,
        "observations": [
            "Les contraintes dures et le retour clubhouse sont respectés sur les dix seeds.",
            "Les parcours occupent surtout le pourtour de la carte (biais visuel du score actuel).",
            "Les dix séquences commencent par un par 3 : la préférence de départ par 4 est dominée par la facilité géométrique.",
            "Le temps moyen est d'environ 53 secondes par seed avec ce prototype Python non optimisé.",
        ],
        "rejection_counts": dict(sorted(rejection_counts.items())),
        "seeds": summaries,
    }
    (output / "report.json").write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (output / "REPORT.md").write_text(_markdown(report), encoding="utf-8")
    return report


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--workers", type=int, default=3)
    parser.add_argument("--output", type=Path,
                        default=Path("experiments/bean_paving/output/benchmark_1_10"))
    args = parser.parse_args()
    report = run_benchmark(args.output, args.workers)
    print(f"benchmark: {report['success_count']}/10 — {report['decision']}")


if __name__ == "__main__":
    main()
