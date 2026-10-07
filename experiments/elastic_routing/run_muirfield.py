"""Étape M — planches du routage Muirfield.

R2 : construction valide (contrôles en ligne, ancrages 1/9/10/18, retour
arrière borné, relances). Pour chaque format de carte, produit
``output/muirfield/r2_<w>x<h>/`` : un SVG (+ PNG) par seed, ``planche.png``
(3 par ligne) et ``report.json`` (violations par famille, longueurs par
nine, relances, temps). Les sorties R1 (``output/muirfield/r1/``) sont
conservées telles quelles pour comparaison (commit 9ff957a).

    python -m experiments.elastic_routing.run_muirfield
"""

from __future__ import annotations

from collections import Counter
import json
from pathlib import Path
import subprocess
import time

from experiments.elastic_routing.muirfield import MuirfieldRoutingError, build_muirfield
from experiments.elastic_routing.render_readable import render_readable_svg
from experiments.elastic_routing.sites import WATER_LEVEL, load_terrain


OUTPUT_ROOT = Path(__file__).resolve().parent / "output" / "muirfield"
SEEDS = (1, 2, 3, 4, 5, 6)
FORMATS = ((300, 400), (350, 400))


def _run_format(width: int, height: int) -> dict:
    out_dir = OUTPUT_ROOT / f"r2_{width}x{height}"
    out_dir.mkdir(parents=True, exist_ok=True)
    reports, pngs = [], []
    for seed in SEEDS:
        t0 = time.perf_counter()
        heightmap = load_terrain(seed, width, height)
        terrain_seconds = time.perf_counter() - t0
        try:
            result = build_muirfield(seed, heightmap, width=width, height=height)
        except MuirfieldRoutingError as error:
            reports.append({"seed": seed, "status": "echec", "attempts": error.attempts})
            print(f"{width}x{height} seed {seed}: ECHEC après {len(error.attempts)} tentative(s)")
            continue
        lengths = result.nine_lengths()
        kinds = dict(sorted(Counter(v.kind for v in result.violations).items()))
        side = "horaire" if result.direction > 0 else "anti-horaire"
        svg = render_readable_svg(
            result.layout, result.violations, heightmap=heightmap, water_level=WATER_LEVEL,
            rings=(result.outer_ring, result.inner_ring),
            title=(f"Muirfield R2 · {width}×{height} · seed {seed} · clubhouse bord "
                   f"{result.clubhouse_edge} · front {side}"),
            subtitle=(f"front par {lengths['front']['par']} · {lengths['front']['total']:.0f} blocs  |  "
                      f"back par {lengths['back']['par']} · {lengths['back']['total']:.0f} blocs  |  "
                      f"{result.relaunches} relance(s) · {result.elapsed_seconds * 1000:.0f} ms"),
        )
        svg_path = out_dir / f"seed_{seed}.svg"
        png_path = out_dir / f"seed_{seed}.png"
        svg_path.write_text(svg, encoding="utf-8")
        subprocess.run(["rsvg-convert", "-o", str(png_path), str(svg_path)], check=True)
        pngs.append(str(png_path))
        plan = result.plan
        reports.append({
            "seed": seed,
            "status": "succes",
            "clubhouse": [round(result.layout.clubhouse.x, 2), round(result.layout.clubhouse.y, 2)],
            "clubhouse_edge": plan.edge,
            "front_direction": plan.direction,
            "plan": {"clubhouse_index": plan.clubhouse_index,
                     "permutation_index": plan.permutation_index,
                     "angle_index": plan.angle_index},
            "pars": {"front": list(plan.front_pars), "back": list(plan.back_pars)},
            "nine_lengths": lengths,
            "hole_lengths": [round(h.length, 1) for h in result.layout.holes],
            "doglegs": sum(1 for h in result.layout.holes if h.doglegs),
            "violations_total": len(result.violations),
            "violations_by_kind": kinds,
            "relaunches": result.relaunches,
            "attempts": list(result.attempts),
            "terrain_seconds_cached_or_built": round(terrain_seconds, 3),
            "elapsed_seconds": round(result.elapsed_seconds, 4),
            "timings": {k: round(v, 4) for k, v in result.timings.items()},
        })
        print(f"{width}x{height} seed {seed}: {len(result.violations)} violation(s) {kinds} · "
              f"{result.relaunches} relance(s) · front {lengths['front']['total']:.0f} / back "
              f"{lengths['back']['total']:.0f} blocs · {result.elapsed_seconds * 1000:.0f} ms")
    if pngs:
        subprocess.run(
            ["magick", "montage", *pngs, "-tile", "3x", "-geometry", "+6+6",
             "-background", "#0d1117", str(out_dir / "planche.png")],
            check=True,
        )
    summary = {"round": "R2", "width": width, "height": height, "seeds": list(SEEDS),
               "reports": reports}
    (out_dir / "report.json").write_text(json.dumps(summary, indent=2, sort_keys=True,
                                                    ensure_ascii=False) + "\n", encoding="utf-8")
    return summary


def main() -> None:
    for width, height in FORMATS:
        _run_format(width, height)


if __name__ == "__main__":
    main()
