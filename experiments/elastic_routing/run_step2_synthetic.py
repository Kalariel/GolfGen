"""Produit l'artefact manuel de la Porte 2, sans solveur."""

from __future__ import annotations

from collections import Counter
from dataclasses import asdict
import json
from pathlib import Path

from experiments.elastic_routing.geometry import ValidationRules, validate
from experiments.elastic_routing.render import render_svg
from experiments.elastic_routing.synthetic import build_synthetic_layout


OUTPUT_DIR = Path("experiments/elastic_routing/output/step2_synthetic")


def main() -> None:
    layout = build_synthetic_layout()
    final_rules = ValidationRules()
    permissive_rules = ValidationRules(
        link_max=500.0,
        max_parallel_stack=None,
        clubhouse_clear_radius=0.0,
        walkable_links=False,
    )
    violations = validate(layout, final_rules)
    permissive_violations = validate(layout, permissive_rules)
    counts = Counter(violation.kind for violation in violations)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUTPUT_DIR / "layout.json").write_text(layout.to_json(), encoding="utf-8")
    (OUTPUT_DIR / "layout.svg").write_text(
        render_svg(layout, final_rules, tuple(violations)),
        encoding="utf-8",
    )
    report = {
        "description": "layout manuel de diagnostic, pas une sortie du futur solveur",
        "final_rules_valid": not violations,
        "permissive_rules_valid": not permissive_violations,
        "violation_counts": dict(sorted(counts.items())),
        "violations": [asdict(violation) for violation in violations],
    }
    (OUTPUT_DIR / "report.json").write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    lines = [
        "# Étape 2 — layout synthétique",
        "",
        "Ce layout est dessiné à la main pour exercer l'oracle et le rendu ;",
        "il ne constitue pas une tentative de génération de parcours.",
        "",
        f"- Valide avec règles permissives : **{'oui' if not permissive_violations else 'non'}**",
        f"- Valide avec règles finales : **{'oui' if not violations else 'non'}**",
        f"- Violations finales : **{len(violations)}**",
        "",
        "| Type | Nombre |",
        "|---|---:|",
        *(f"| `{kind}` | {count} |" for kind, count in sorted(counts.items())),
        "",
    ]
    (OUTPUT_DIR / "REPORT.md").write_text("\n".join(lines), encoding="utf-8")
    print(f"step2_synthetic: permissif={not permissive_violations} "
          f"final={not violations} violations={len(violations)}")


if __name__ == "__main__":
    main()
