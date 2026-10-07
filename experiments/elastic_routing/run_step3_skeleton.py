"""Étape 3 — squelette global grossier (arbre aléatoire sur réseau grossier).

Round correctif du 2026-10-07 : ne produit QUE l'arbre, son contour et la
coupure aux deux passages au clubhouse (``skeleton.svg``). Pas de DP de
découpage ni de ``CourseLayout`` dans ce round (voir PLAN.md et le rapport
de correction) — ``layout.json``/``layout.svg`` du round précédent sont
périmés et supprimés par ce runner.
"""

from __future__ import annotations

import json
from pathlib import Path

from experiments.elastic_routing.skeleton import (
    SkeletonGenerationError,
    build_skeleton,
    render_skeleton_svg,
)


OUTPUT_DIR = Path("experiments/elastic_routing/output/step3_skeleton")
SEEDS = (1, 2, 3, 4, 5, 6)
SLOW_SECONDS = 10.0  # au-dela, le temps de generation doit etre signale

# Fichiers du round precedent (DP + CourseLayout), perimes par ce round court.
STALE_FILES = ("layout.json", "layout.svg", "report.json", "REPORT.md")


def _run_seed(seed: int) -> dict:
    seed_dir = OUTPUT_DIR / f"seed_{seed}"
    seed_dir.mkdir(parents=True, exist_ok=True)
    for name in STALE_FILES:
        stale = seed_dir / name
        if stale.exists():
            stale.unlink()

    try:
        result = build_skeleton(seed)
    except SkeletonGenerationError as error:
        report = {"seed": seed, "status": "echec", "error": str(error)}
        (seed_dir / "report.json").write_text(
            json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8",
        )
        print(f"seed {seed}: ECHEC — {error}")
        return report

    (seed_dir / "skeleton.svg").write_text(render_skeleton_svg(result), encoding="utf-8")

    report = {
        "seed": seed,
        "status": "succes",
        "elapsed_seconds": result.elapsed_seconds,
        "slow": result.elapsed_seconds > SLOW_SECONDS,
        "attempts_used": result.attempts_used,
        "rejection_rate": (result.attempts_used - 1) / result.attempts_used,
        "clubhouse": list(result.clubhouse),
        "front_leaves": len(result.skeleton.front_leaves),
        "back_leaves": len(result.skeleton.back_leaves),
        "front_tree_length": result.skeleton.front_length,
        "back_tree_length": result.skeleton.back_length,
    }
    (seed_dir / "report.json").write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8",
    )
    print(
        f"seed {seed}: succes en {result.elapsed_seconds:.3f}s, "
        f"tirages={result.attempts_used}, clubhouse={result.clubhouse}, "
        f"feuilles front/back={report['front_leaves']}/{report['back_leaves']}, "
        f"longueurs front/back={result.skeleton.front_length:.1f}/{result.skeleton.back_length:.1f}"
    )
    return report


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    reports = [_run_seed(seed) for seed in SEEDS]
    summary = {
        "seeds": SEEDS,
        "successes": sum(1 for r in reports if r["status"] == "succes"),
        "reports": reports,
    }
    (OUTPUT_DIR / "SUMMARY.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8",
    )


if __name__ == "__main__":
    main()
