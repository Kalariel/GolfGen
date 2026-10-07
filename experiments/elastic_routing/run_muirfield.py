"""Étape M, round R1 — premier visuel du routage Muirfield glouton.

Produit ``output/muirfield/r1/`` : un SVG (+ PNG) par seed, ``planche.png``
(3 par ligne) et ``report.json`` (violations par famille, longueurs par nine,
temps). Les violations sont tolérées et affichées : R1 n'est pas une porte
de validité.

    python -m experiments.elastic_routing.run_muirfield
"""

from __future__ import annotations

from collections import Counter
import json
from pathlib import Path
import subprocess
import time

from experiments.elastic_routing.muirfield import build_muirfield
from experiments.elastic_routing.render_readable import render_readable_svg
from experiments.elastic_routing.sites import WATER_LEVEL, load_terrain


OUT_DIR = Path(__file__).resolve().parent / "output" / "muirfield" / "r1"
SEEDS = (1, 2, 3, 4, 5, 6)


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    reports, pngs = [], []
    for seed in SEEDS:
        t0 = time.perf_counter()
        heightmap = load_terrain(seed)
        terrain_seconds = time.perf_counter() - t0
        result = build_muirfield(seed, heightmap)
        lengths = result.nine_lengths()
        kinds = dict(sorted(Counter(v.kind for v in result.violations).items()))
        side = "horaire" if result.direction > 0 else "anti-horaire"
        svg = render_readable_svg(
            result.layout, result.violations, heightmap=heightmap, water_level=WATER_LEVEL,
            rings=(result.outer_ring, result.inner_ring),
            title=f"Muirfield R1 · seed {seed} · clubhouse bord {result.clubhouse_edge} · front {side}",
            subtitle=(f"front par {lengths['front']['par']} · {lengths['front']['total']:.0f} blocs  |  "
                      f"back par {lengths['back']['par']} · {lengths['back']['total']:.0f} blocs  |  "
                      f"{result.elapsed_seconds * 1000:.0f} ms (hors relief)"),
        )
        svg_path = OUT_DIR / f"seed_{seed}.svg"
        png_path = OUT_DIR / f"seed_{seed}.png"
        svg_path.write_text(svg, encoding="utf-8")
        subprocess.run(["rsvg-convert", "-o", str(png_path), str(svg_path)], check=True)
        pngs.append(str(png_path))
        reports.append({
            "seed": seed,
            "clubhouse": [round(result.layout.clubhouse.x, 2), round(result.layout.clubhouse.y, 2)],
            "clubhouse_edge": result.clubhouse_edge,
            "front_direction": result.direction,
            "pars": {"front": [h.par for h in result.layout.front.holes],
                     "back": [h.par for h in result.layout.back.holes]},
            "nine_lengths": lengths,
            "hole_lengths": [round(h.length, 1) for h in result.layout.holes],
            "doglegs": sum(1 for h in result.layout.holes if h.doglegs),
            "violations_total": len(result.violations),
            "violations_by_kind": kinds,
            "violations": [{"kind": v.kind, "holes": list(v.holes), "detail": v.detail}
                           for v in result.violations],
            "fallbacks": [{"order": t.order, "fallback": t.fallback}
                          for t in result.traces if t.fallback],
            "target_distance_mean": round(sum(t.target_distance for t in result.traces) / 18, 1),
            "terrain_seconds_cached_or_built": round(terrain_seconds, 3),
            "elapsed_seconds": round(result.elapsed_seconds, 4),
            "timings": {k: round(v, 4) for k, v in result.timings.items()},
        })
        print(f"seed {seed}: {len(result.violations)} violation(s) {kinds} · front "
              f"{lengths['front']['total']:.0f} / back {lengths['back']['total']:.0f} blocs · "
              f"{result.elapsed_seconds * 1000:.0f} ms")
    subprocess.run(
        ["magick", "montage", *pngs, "-tile", "3x", "-geometry", "+6+6",
         "-background", "#0d1117", str(OUT_DIR / "planche.png")],
        check=True,
    )
    summary = {"round": "R1", "seeds": list(SEEDS), "reports": reports}
    (OUT_DIR / "report.json").write_text(json.dumps(summary, indent=2, sort_keys=True,
                                                    ensure_ascii=False) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
