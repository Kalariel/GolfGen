"""Étape 3 — squelette global grossier (contour d'un arbre aléatoire).

Ne constitue pas encore l'étape 4 (trous élastiques/mutations) : seuls le
squelette grossier et son découpage DP sont produits ici, avec les
violations de l'oracle laissées visibles (attendu à ce stade, voir PLAN.md).
"""

from __future__ import annotations

from collections import Counter
import json
from pathlib import Path

from experiments.elastic_routing.geometry import ValidationRules, validate
from experiments.elastic_routing.render import render_svg
from experiments.elastic_routing.skeleton import (
    SkeletonGenerationError,
    build_skeleton,
    render_skeleton_svg,
)


OUTPUT_DIR = Path("experiments/elastic_routing/output/step3_skeleton")
SEEDS = (1, 2, 3)
SLOW_SECONDS = 10.0  # au-dela, le temps de generation doit etre signale


def _run_seed(seed: int) -> dict:
    seed_dir = OUTPUT_DIR / f"seed_{seed}"
    seed_dir.mkdir(parents=True, exist_ok=True)

    try:
        result = build_skeleton(seed)
    except SkeletonGenerationError as error:
        report = {
            "seed": seed,
            "status": "echec",
            "error": str(error),
        }
        (seed_dir / "REPORT.md").write_text(
            f"# Étape 3 — seed {seed}\n\nÉchec : {error}\n", encoding="utf-8",
        )
        (seed_dir / "report.json").write_text(
            json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8",
        )
        print(f"seed {seed}: ECHEC — {error}")
        return report

    construction_rules = ValidationRules(
        width=result.layout.width, height=result.layout.height, link_max=60.0,
    )
    final_rules = ValidationRules(width=result.layout.width, height=result.layout.height)
    construction_violations = validate(result.layout, construction_rules)
    final_violations = validate(result.layout, final_rules)
    construction_counts = Counter(v.kind for v in construction_violations)
    final_counts = Counter(v.kind for v in final_violations)

    (seed_dir / "layout.json").write_text(result.layout.to_json(), encoding="utf-8")
    (seed_dir / "skeleton.svg").write_text(render_skeleton_svg(result), encoding="utf-8")
    (seed_dir / "layout.svg").write_text(
        render_svg(result.layout, final_rules, tuple(final_violations)), encoding="utf-8",
    )

    report = {
        "seed": seed,
        "status": "succes",
        "elapsed_seconds": result.elapsed_seconds,
        "slow": result.elapsed_seconds > SLOW_SECONDS,
        "front_leaves": len(result.skeleton.front_leaves),
        "back_leaves": len(result.skeleton.back_leaves),
        "front_tree_length": result.skeleton.front_length,
        "back_tree_length": result.skeleton.back_length,
        "front_contour_length": sum(
            ((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2) ** 0.5
            for a, b in zip(result.front_contour, result.front_contour[1:])
        ),
        "back_contour_length": sum(
            ((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2) ** 0.5
            for a, b in zip(result.back_contour, result.back_contour[1:])
        ),
        "construction_violation_counts": dict(sorted(construction_counts.items())),
        "final_violation_counts": dict(sorted(final_counts.items())),
        "construction_violations_total": len(construction_violations),
        "final_violations_total": len(final_violations),
    }
    (seed_dir / "report.json").write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8",
    )
    lines = [
        f"# Étape 3 — squelette seed {seed}",
        "",
        f"- Temps de génération : **{result.elapsed_seconds:.3f} s**"
        + (" (> 10 s, à signaler)" if report["slow"] else ""),
        f"- Feuilles front / back : **{report['front_leaves']}** / **{report['back_leaves']}**",
        f"- Longueur d'arbre front / back : **{result.skeleton.front_length:.1f}** / "
        f"**{result.skeleton.back_length:.1f}** blocs",
        f"- Violations construction (liaisons 12–60) : **{report['construction_violations_total']}**",
        f"- Violations finales (liaisons 12–45) : **{report['final_violations_total']}**",
        "",
        "| Type (règles finales) | Nombre |",
        "|---|---:|",
        *(f"| `{kind}` | {count} |" for kind, count in sorted(final_counts.items())),
        "",
    ]
    (seed_dir / "REPORT.md").write_text("\n".join(lines), encoding="utf-8")
    print(
        f"seed {seed}: succes en {result.elapsed_seconds:.3f}s, "
        f"violations finales={len(final_violations)}, "
        f"feuilles front/back={report['front_leaves']}/{report['back_leaves']}"
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
