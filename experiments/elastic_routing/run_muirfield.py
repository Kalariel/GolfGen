"""Étape M — planches du routage Muirfield.

Rounds disponibles (``--round``) :

- ``r2`` (défaut) : 300×400 et 350×400, seeds 1–6 → ``r2_<w>x<h>/`` ;
- ``ra`` : formats paysage 400×300 et 400×350, seeds 1–6 → ``ra_<w>x<h>/`` ;
- ``ra-30`` : robustesse 300×400 sur les seeds 1–30 →
  ``ra_300x400_30seeds/`` (taux de réussite, relances, temps médian/p90/max,
  planche 6×5 réduite) ;
- ``ra2-30`` : idem après le round A2 → ``ra2_300x400_30seeds/`` ;
- ``ra2-check`` : non-régression A2 sur 350×400, 400×300, 400×350 (seeds
  1–6) → ``ra2_check_<w>x<h>/report.json`` (pas de planche).

Les temps sont mesurés sur la machine qui exécute le runner (dépendants du
matériel) : chronomètre unique autour de ``build_muirfield``, succès comme
échecs, relief en cache exclu.

Seuls ``planche.png`` et ``report.json`` sont versionnés ; les png/svg par
seed sont régénérés localement (``.gitignore``).

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
import argparse
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
LANDSCAPE_FORMATS = ((400, 300), (400, 350))
ROBUSTNESS_SEEDS = tuple(range(1, 31))


def _percentile(values: list[float], q: float) -> float:
    ordered = sorted(values)
    if not ordered:
        return float("nan")
    rank = q * (len(ordered) - 1)
    low = int(rank)
    high = min(low + 1, len(ordered) - 1)
    return ordered[low] + (ordered[high] - ordered[low]) * (rank - low)


def _run_format(width: int, height: int, *, seeds: tuple[int, ...] = SEEDS,
                label: str = "r2", out_name: str | None = None, tile: str = "3x",
                thumb: str | None = None, planche: bool = True) -> dict:
    out_dir = OUTPUT_ROOT / (out_name or f"{label}_{width}x{height}")
    out_dir.mkdir(parents=True, exist_ok=True)
    reports, pngs = [], []
    for seed in seeds:
        t0 = time.perf_counter()
        heightmap = load_terrain(seed, width, height)
        terrain_seconds = time.perf_counter() - t0
        # mesure homogène succès/échec : même chronomètre autour de
        # build_muirfield (sites + recherche + oracle, relief en cache exclu)
        t1 = time.perf_counter()
        try:
            result = build_muirfield(seed, heightmap, width=width, height=height)
            elapsed = time.perf_counter() - t1
        except MuirfieldRoutingError as error:
            elapsed = time.perf_counter() - t1
            stages = dict(sorted(Counter(a["status"] for a in error.attempts).items()))
            reports.append({"seed": seed, "status": "echec", "elapsed_seconds": round(elapsed, 4),
                            "relaunches": len(error.attempts), "failure_stages": stages,
                            "attempts": error.attempts})
            print(f"{width}x{height} seed {seed}: ECHEC après {len(error.attempts)} tentative(s) "
                  f"{stages} · {elapsed * 1000:.0f} ms")
            continue
        lengths = result.nine_lengths()
        kinds = dict(sorted(Counter(v.kind for v in result.violations).items()))
        side = "horaire" if result.direction > 0 else "anti-horaire"
        svg = render_readable_svg(
            result.layout, result.violations, heightmap=heightmap, water_level=WATER_LEVEL,
            rings=(result.outer_ring, result.inner_ring),
            title=(f"Muirfield {label.upper()} · {width}×{height} · seed {seed} · clubhouse bord "
                   f"{result.clubhouse_edge} · front {side}"),
            subtitle=(f"front par {lengths['front']['par']} · {lengths['front']['total']:.0f} blocs  |  "
                      f"back par {lengths['back']['par']} · {lengths['back']['total']:.0f} blocs  |  "
                      f"{result.relaunches} relance(s) · {elapsed * 1000:.0f} ms"),
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
            "elapsed_seconds": round(elapsed, 4),
            "timings": {k: round(v, 4) for k, v in result.timings.items()},
        })
        print(f"{width}x{height} seed {seed}: {len(result.violations)} violation(s) {kinds} · "
              f"{result.relaunches} relance(s) · front {lengths['front']['total']:.0f} / back "
              f"{lengths['back']['total']:.0f} blocs · {elapsed * 1000:.0f} ms")
    if pngs and planche:
        geometry = f"{thumb}+3+3" if thumb else "+6+6"
        # vignettes réduites en palette 8 bits : la planche des 30 seeds reste < 1 Mo
        target = f"PNG8:{out_dir / 'planche.png'}" if thumb else str(out_dir / "planche.png")
        subprocess.run(
            ["magick", "montage", *pngs, "-tile", tile, "-geometry", geometry,
             "-background", "#0d1117", target],
            check=True,
        )
    times = [r["elapsed_seconds"] for r in reports]
    succeeded = [r for r in reports if r["status"] == "succes"]
    summary = {
        "round": label.upper(), "width": width, "height": height, "seeds": list(seeds),
        "stats": {
            "successes": len(succeeded),
            "failures": [r["seed"] for r in reports if r["status"] != "succes"],
            "violations_total": sum(r.get("violations_total", 0) for r in succeeded),
            "relaunches_total": sum(r["relaunches"] for r in reports),
            "seconds_median": round(_percentile(times, 0.5), 3),
            "seconds_p90": round(_percentile(times, 0.9), 3),
            "seconds_max": round(max(times), 3) if times else None,
            "seeds_over_2s": [r["seed"] for r in reports if r["elapsed_seconds"] > 2.0],
        },
        "reports": reports,
    }
    print(f"{width}x{height}: {summary['stats']}")
    (out_dir / "report.json").write_text(json.dumps(summary, indent=2, sort_keys=True,
                                                    ensure_ascii=False) + "\n", encoding="utf-8")
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--round", choices=("r2", "ra", "ra-30", "ra2-30", "ra2-check"),
                        default="r2")
    args = parser.parse_args()
    if args.round == "r2":
        for width, height in FORMATS:
            _run_format(width, height, label="r2")
    elif args.round == "ra":
        for width, height in LANDSCAPE_FORMATS:
            _run_format(width, height, label="ra")
    elif args.round == "ra-30":
        _run_format(300, 400, seeds=ROBUSTNESS_SEEDS, label="ra",
                    out_name="ra_300x400_30seeds", tile="6x", thumb="340x")
    elif args.round == "ra2-30":
        _run_format(300, 400, seeds=ROBUSTNESS_SEEDS, label="ra2",
                    out_name="ra2_300x400_30seeds", tile="6x", thumb="340x")
    else:
        for width, height in ((350, 400), *LANDSCAPE_FORMATS):
            _run_format(width, height, label="ra2", out_name=f"ra2_check_{width}x{height}",
                        planche=False)


if __name__ == "__main__":
    main()
