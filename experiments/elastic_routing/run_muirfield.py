"""Étape M — planches du routage Muirfield.

Rounds disponibles (``--round``) :

- ``r2`` (défaut) : 300×400 et 350×400, seeds 1–6 → ``r2_<w>x<h>/`` ;
- ``ra`` : formats paysage 400×300 et 400×350, seeds 1–6 → ``ra_<w>x<h>/`` ;
- ``ra-30`` : robustesse 300×400 sur les seeds 1–30 →
  ``ra_300x400_30seeds/`` (taux de réussite, relances, temps médian/p90/max,
  planche 6×5 réduite) ;
- ``ra2-30`` : idem après le round A2 → ``ra2_300x400_30seeds/`` ;
- ``ra2-check`` : non-régression A2 sur 350×400, 400×300, 400×350 (seeds
  1–6) → ``ra2_check_<w>x<h>/report.json`` (pas de planche) ;
- ``rb`` : patron ``muirfield_inverse`` en 300×400, seeds 1–6 →
  ``rb_inverse_300x400/`` ;
- ``rb-30`` / ``rb-check`` : robustesse 30 seeds (300×400) et non-régression
  (350×400, 400×300, 400×350, seeds 1–6) pour chaque patron (ou celui de
  ``--pattern``) → ``rb_<patron>_300x400_30seeds/``, ``rb_check_<patron>_<w>x<h>/`` ;
- ``rc`` / ``rc-30`` : largeurs variables (C1, ``--width-mode``) — planche
  6 seeds muirfield 300×400 → ``rc_<patron>_300x400/`` ; 30 seeds par
  patron → ``rc_<patron>_300x400_30seeds/`` ;
- ``r2b1`` / ``r2b1-30`` : cibles irrégulières (R2b M1, ``target_mode``) —
  planches 6 seeds 300×400 pour chaque patron et chaque mode (uniform,
  irregular) → ``r2b1_<patron>_<mode>_300x400/`` ; 30 seeds en mode
  irregular par patron, sans planche (base uniform : rc-30) →
  ``r2b1_<patron>_irregular_300x400_30seeds/`` ;
- ``custom`` : ``--pattern``, ``--size LxH``, ``--seeds 1-6`` →
  ``custom_<patron>_<w>x<h>/``.

Le patron (``--pattern`` : muirfield, muirfield_inverse, random) est un
paramètre explicite au même titre que la seed.

Les temps sont mesurés sur la machine qui exécute le runner (dépendants du
matériel) : chronomètre unique autour de ``build_course``, succès comme
échecs, relief en cache exclu.

Seuls ``planche.png`` et ``report.json`` sont versionnés ; les png/svg par
seed sont régénérés localement (``.gitignore``).

R2 : construction valide (contrôles en ligne, ancrages 1/9/10/18, retour
arrière borné, relances). Pour chaque format de carte, produit
``output/muirfield/r2_<w>x<h>/`` : un SVG (+ PNG) par seed, ``planche.png``
(3 par ligne) et ``report.json`` (violations par famille, longueurs par
nine, relances, temps). Les sorties R1 (``output/muirfield/r1/``) sont
conservées telles quelles pour comparaison (commit 9ff957a).

    .venv/bin/python -m experiments.elastic_routing.run_muirfield
"""

from __future__ import annotations

from collections import Counter
import argparse
import json
from pathlib import Path
import subprocess
import time

from experiments.elastic_routing.muirfield import (
    PATTERN_CHOICES,
    PATTERNS,
    TARGET_MODES,
    MuirfieldRoutingError,
    build_course,
    outer_start,
)
from experiments.elastic_routing.render_readable import render_readable_svg
from experiments.elastic_routing.shape_metrics import shape_metrics
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


def _shape_stats(reports: list[dict]) -> dict:
    """Médiane, min et max des métriques de forme « course » sur les succès."""
    stats = {}
    for metric in ("angular_step_cv", "direction_entropy", "radial_alignment_R"):
        values = [r["shape"]["course"][metric] for r in reports
                  if r["status"] == "succes" and r["shape"]["course"][metric] is not None]
        stats[metric] = ({"median": round(_percentile(values, 0.5), 4),
                          "min": min(values), "max": max(values)} if values else None)
    return stats


# Rounds r2…rb : largeur minimale (``width_mode="min"``, défaut ici, pour
# rester reproductibles) ; rc et custom passent ``--width-mode`` (défaut
# variable).
def _run_format(width: int, height: int, *, seeds: tuple[int, ...] = SEEDS,
                label: str = "r2", out_name: str | None = None, tile: str = "3x",
                thumb: str | None = None, planche: bool = True,
                pattern: str = "muirfield", width_mode: str = "min",
                target_mode: str = "uniform") -> dict:
    out_dir = OUTPUT_ROOT / (out_name or f"{label}_{width}x{height}")
    out_dir.mkdir(parents=True, exist_ok=True)
    reports, pngs = [], []
    for seed in seeds:
        t0 = time.perf_counter()
        heightmap = load_terrain(seed, width, height)
        terrain_seconds = time.perf_counter() - t0
        # mesure homogène succès/échec : même chronomètre autour de
        # build_course (sites + recherche + oracle, relief en cache exclu)
        t1 = time.perf_counter()
        try:
            result = build_course(seed, pattern, heightmap, width=width, height=height,
                                  width_mode=width_mode, target_mode=target_mode)
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
        # ``direction`` est le sens du nine EXTÉRIEUR (front pour muirfield,
        # back pour muirfield_inverse) ; le nine intérieur tourne en sens inverse
        side = "horaire" if result.direction > 0 else "anti-horaire"
        outer_nine = "front" if outer_start(result.pattern) == 1 else "back"
        svg = render_readable_svg(
            result.layout, result.violations, heightmap=heightmap, water_level=WATER_LEVEL,
            rings=(result.outer_ring, result.inner_ring),
            title=(f"{result.pattern} {label.upper()} · {width}×{height} · seed {seed} · bord "
                   f"{result.clubhouse_edge} · {outer_nine} extérieur {side} · cibles "
                   f"{result.target_mode}"),
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
            "pattern": result.pattern,
            "outer_nine": outer_nine,
            "outer_direction": plan.direction,
            "plan": {"clubhouse_index": plan.clubhouse_index,
                     "permutation_index": plan.permutation_index,
                     "angle_index": plan.angle_index},
            "pars": {"front": list(plan.front_pars), "back": list(plan.back_pars)},
            "nine_lengths": lengths,
            "hole_lengths": [round(h.length, 1) for h in result.layout.holes],
            "doglegs": sum(1 for h in result.layout.holes if h.doglegs),
            "shape": shape_metrics(result.layout, front_path=result.front_path,
                                   back_path=result.back_path),
            "hole_widths": [h.width for h in result.layout.holes],
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
        "round": label.upper(), "pattern": pattern, "width_mode": width_mode,
        "target_mode": target_mode,
        "width": width, "height": height,
        "seeds": list(seeds),
        "stats": {
            "successes": len(succeeded),
            "failures": [r["seed"] for r in reports if r["status"] != "succes"],
            "violations_total": sum(r.get("violations_total", 0) for r in succeeded),
            "relaunches_total": sum(r["relaunches"] for r in reports),
            "seconds_median": round(_percentile(times, 0.5), 3),
            "seconds_p90": round(_percentile(times, 0.9), 3),
            "seconds_max": round(max(times), 3) if times else None,
            "seeds_over_2s": [r["seed"] for r in reports if r["elapsed_seconds"] > 2.0],
            "shape_course": _shape_stats(reports),
        },
        "reports": reports,
    }
    print(f"{width}x{height}: {summary['stats']}")
    (out_dir / "report.json").write_text(json.dumps(summary, indent=2, sort_keys=True,
                                                    ensure_ascii=False) + "\n", encoding="utf-8")
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--round", choices=("r2", "ra", "ra-30", "ra2-30", "ra2-check",
                                            "rb", "rb-30", "rb-check", "rc", "rc-30", "r2b1",
                                            "r2b1-30", "custom"),
                        default="r2")
    parser.add_argument("--pattern", choices=PATTERN_CHOICES, default=None,
                        help="patron explicite (défaut : muirfield ; rb-30/rb-check : les deux)")
    parser.add_argument("--width-mode", choices=("variable", "min"), default="variable",
                        help="largeurs de fairway (C1 : variable ; rounds A–B : min)")
    parser.add_argument("--size", default="300x400", help="format LxH (round custom)")
    parser.add_argument("--seeds", default="1-6", help="ex. 1-6 ou 3,7 (round custom)")
    args = parser.parse_args()
    patterns = (args.pattern,) if args.pattern else PATTERNS
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
    elif args.round == "ra2-check":
        for width, height in ((350, 400), *LANDSCAPE_FORMATS):
            _run_format(width, height, label="ra2", out_name=f"ra2_check_{width}x{height}",
                        planche=False)
    elif args.round == "rb":
        _run_format(300, 400, label="rb", out_name="rb_inverse_300x400",
                    pattern=args.pattern or "muirfield_inverse", width_mode="min")
    elif args.round == "rc":
        pattern = args.pattern or "muirfield"
        _run_format(300, 400, label="rc", out_name=f"rc_{pattern}_300x400", pattern=pattern,
                    width_mode=args.width_mode)
    elif args.round == "rc-30":
        for pattern in patterns:
            _run_format(300, 400, seeds=ROBUSTNESS_SEEDS, label="rc", planche=False,
                        out_name=f"rc_{pattern}_300x400_30seeds", pattern=pattern,
                        width_mode=args.width_mode)
    elif args.round == "r2b1":
        for pattern in patterns:
            for mode in TARGET_MODES:
                _run_format(300, 400, label="r2b1", out_name=f"r2b1_{pattern}_{mode}_300x400",
                            pattern=pattern, width_mode=args.width_mode, target_mode=mode)
    elif args.round == "r2b1-30":
        for pattern in patterns:
            _run_format(300, 400, seeds=ROBUSTNESS_SEEDS, label="r2b1", planche=False,
                        out_name=f"r2b1_{pattern}_irregular_300x400_30seeds", pattern=pattern,
                        width_mode=args.width_mode, target_mode="irregular")
    elif args.round == "rb-30":
        for pattern in patterns:
            _run_format(300, 400, seeds=ROBUSTNESS_SEEDS, label="rb",
                        out_name=f"rb_{pattern}_300x400_30seeds", planche=False, pattern=pattern,
                        width_mode="min")
    elif args.round == "rb-check":
        for pattern in patterns:
            for width, height in ((350, 400), *LANDSCAPE_FORMATS):
                _run_format(width, height, label="rb", planche=False, pattern=pattern,
                            out_name=f"rb_check_{pattern}_{width}x{height}", width_mode="min")
    else:
        width, height = (int(v) for v in args.size.lower().split("x"))
        if "-" in args.seeds:
            low, high = (int(v) for v in args.seeds.split("-"))
            seeds = tuple(range(low, high + 1))
        else:
            seeds = tuple(int(v) for v in args.seeds.split(","))
        pattern = args.pattern or "muirfield"
        _run_format(width, height, seeds=seeds, label="custom", pattern=pattern,
                    out_name=f"custom_{pattern}_{width}x{height}", width_mode=args.width_mode)


if __name__ == "__main__":
    main()
