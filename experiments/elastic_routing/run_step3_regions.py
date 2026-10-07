"""Étape 3, r4 — squelette par régions : rendu comparatif w_min = 2, 3, 4.

Produit, pour chaque variante, ``output/step3_skeleton/compare/r4_regions_w<w>/`` :
un SVG (+ PNG) par seed, ``planche.png`` (3 par ligne) et ``report.json``.
Pas de découpage en trous ni de ``CourseLayout`` dans ce round.

``w_min`` = 4 utilise ``c`` = 19 (et non 21) : à ``c`` = 21 les régions
font ≥ 84 blocs de large et aucun tirage n'aboutit (0/30 seeds en 200
tirages, toutes en impasse : deux régions aussi larges ne trouvent pas
assez de périmètre dans une carte de 400). Voir le README de ``compare/``.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

from experiments.elastic_routing.regions import (
    CELL_BY_W_MIN,
    INSET,
    RegionGenerationError,
    build_regions,
    render_regions_svg,
)


COMPARE_DIR = Path("experiments/elastic_routing/output/step3_skeleton/compare")
SEEDS = (1, 2, 3, 4, 5, 6)
VARIANTS = tuple(sorted(CELL_BY_W_MIN.items()))


def _run_variant(w_min: int, cell: float) -> dict:
    out_dir = COMPARE_DIR / f"r4_regions_w{w_min}"
    out_dir.mkdir(parents=True, exist_ok=True)
    reports, pngs = [], []
    for seed in SEEDS:
        try:
            result = build_regions(seed, w_min, cell=cell)
        except RegionGenerationError as error:
            reports.append({"seed": seed, "status": "echec", "error": str(error), "reasons": error.reasons})
            print(f"w{w_min} seed {seed}: ECHEC — {error}")
            continue
        svg = out_dir / f"seed_{seed}_regions.svg"
        png = out_dir / f"seed_{seed}_regions.png"
        svg.write_text(render_regions_svg(result), encoding="utf-8")
        subprocess.run(["rsvg-convert", "-o", str(png), str(svg)], check=True)
        pngs.append(str(png))
        reports.append({
            "seed": seed,
            "status": "succes",
            "cell": result.cell,
            "inset": result.inset,
            "clubhouse_vertex": list(result.clubhouse_vertex),
            "front_length": round(result.front_length, 1),
            "back_length": round(result.back_length, 1),
            "front_blocks": result.front_blocks,
            "back_blocks": result.back_blocks,
            "attempts_used": result.attempts_used,
            "rejection_reasons": result.rejection_reasons,
            "elapsed_seconds": round(result.elapsed_seconds, 4),
        })
        print(f"w{w_min} seed {seed}: {result.attempts_used} tirage(s), "
              f"{result.elapsed_seconds * 1000:.0f} ms, front/back "
              f"{result.front_length:.0f}/{result.back_length:.0f}")
    if pngs:
        subprocess.run(
            ["magick", "montage", *pngs, "-tile", "3x", "-geometry", "+6+6",
             "-background", "#0d1117", str(out_dir / "planche.png")],
            check=True,
        )
    summary = {"w_min": w_min, "cell": cell, "inset": INSET, "seeds": list(SEEDS), "reports": reports}
    (out_dir / "report.json").write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return summary


def main() -> None:
    for w_min, cell in VARIANTS:
        _run_variant(w_min, cell)


if __name__ == "__main__":
    main()
