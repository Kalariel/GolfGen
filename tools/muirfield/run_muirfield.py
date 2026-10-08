"""Planches et rapports du routage Muirfield.

Rounds disponibles (``--round``), sorties sous ``tools/muirfield/output/`` :

- ``rc`` (défaut) : planche 6 seeds en 300×400 pour un patron (``--pattern``,
  défaut muirfield) → ``rc_<patron>_300x400/`` ;
- ``rc-30`` : robustesse 300×400 sur les seeds 1–30, pour chaque patron (ou
  celui de ``--pattern``), sans planche → ``rc_<patron>_300x400_30seeds/`` ;
- ``land`` / ``land-30`` : format paysage 400×300, pour chaque patron —
  planche 6 seeds → ``land_<patron>_400x300/`` ; 30 seeds sans planche →
  ``land_<patron>_400x300_30seeds/`` ;
- ``custom`` : ``--pattern``, ``--size LxH``, ``--seeds 1-6`` →
  ``custom_<patron>_<w>x<h>/``.
- ``calib`` : calibration des tailles (phase 1). Grille petit côté ×
  grand côté (petit < grand) × orientation (portrait W=petit, paysage
  W=grand) × patron (muirfield, muirfield_inverse) × seeds 1–6, sans planche
  ni rendu → ``calib_phase1/<patron>_<w>x<h>/report.json``, puis
  ``calib_phase1/summary.json`` et ``summary.md`` reconstruits à partir de
  TOUS les report.json présents (les morceaux se fusionnent seuls). Filtres
  pour découper la grille : ``--calib-short 240,260``, ``--calib-long 400``,
  ``--calib-orientation portrait``. Une ``ValueError`` levée pour la taille
  (géométrie trop petite) y est enregistrée en ``taille_invalide`` au lieu
  d'interrompre le round ; les autres rounds ne capturent rien de plus.

Le patron (``--pattern`` : muirfield, muirfield_inverse, random) est un
paramètre explicite au même titre que la seed. ``--width-mode`` choisit les
largeurs de fairway (``variable`` par défaut, ``min`` pour les reproduire à
la largeur minimale).

Chaque dossier contient un SVG (+ PNG) par seed, ``planche.png`` (sauf
rounds 30 seeds) et ``report.json`` (violations par famille, longueurs par
nine, relances, métriques de forme, temps). Seuls ``planche.png`` et
``report.json`` sont versionnés ; les png/svg par seed sont régénérés
localement (``.gitignore``).

Les temps sont mesurés sur la machine qui exécute le runner (dépendants du
matériel) : chronomètre unique autour de ``build_course``, succès comme
échecs, relief en cache exclu.

    .venv/bin/python -m tools.muirfield.run_muirfield --round rc-30
"""

from __future__ import annotations

from collections import Counter
import argparse
import json
from pathlib import Path
import subprocess
import time
from typing import NamedTuple

from golfgen.routing.muirfield import (
    PATTERN_CHOICES,
    PATTERNS,
    MuirfieldRoutingError,
    build_course,
    outer_start,
)
from tools.muirfield.render_readable import render_readable_svg
from tools.muirfield.shape_metrics import shape_metrics
from golfgen.routing.sites import WATER_LEVEL, load_terrain


OUTPUT_ROOT = Path(__file__).resolve().parent / "output"
SEEDS = (1, 2, 3, 4, 5, 6)
ROBUSTNESS_SEEDS = tuple(range(1, 31))

CALIB_DIR = "calib_phase1"
CALIB_SHORT = (240, 260, 280, 300, 325, 350)
CALIB_LONG = (400, 450, 500)
CALIB_ORIENTATIONS = ("portrait", "paysage")
CALIB_PATTERNS = ("muirfield", "muirfield_inverse")
# critère de lecture d'une taille « OK » (affiché, ne filtre rien)
CALIB_OK_P90_SECONDS = 10.0
CALIB_OK_MAX_SECONDS = 30.0


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


NINE_SHAPE_METRICS = ("angular_step_cv", "direction_entropy", "radial_alignment_R",
                      "heading_turns", "hull_ratio", "path_to_nine_length", "forward_mean",
                      "obliquity_signed", "obliquity_abs")


def _nine_shape_stats(reports: list[dict]) -> dict:
    """Médiane, min et max des métriques par nine sur les succès, séparées
    en nine EXTÉRIEUR (``outer_nine`` du rapport) et nine INTÉRIEUR."""
    stats: dict[str, dict] = {"outer": {}, "inner": {}}
    for role in stats:
        for metric in NINE_SHAPE_METRICS:
            values = []
            for r in reports:
                if r["status"] != "succes":
                    continue
                nine = r["outer_nine"] if role == "outer" else (
                    "back" if r["outer_nine"] == "front" else "front")
                value = r["shape"][nine].get(metric)
                if value is not None:
                    values.append(value)
            stats[role][metric] = ({"median": round(_percentile(values, 0.5), 4),
                                    "min": min(values), "max": max(values)} if values else None)
    return stats


def _size_error_report(seed: int, stage: str, error: ValueError, elapsed: float) -> dict:
    """Entrée de rapport d'une seed dont la taille est refusée (round calib)."""
    return {"seed": seed, "status": "taille_invalide", "stage": stage,
            "error_type": type(error).__name__, "message": str(error),
            "elapsed_seconds": round(elapsed, 4), "relaunches": 0, "attempts": [],
            "skipped": []}


def _planche_title(result, label: str, width: int, height: int, seed: int,
                   outer_nine: str, side: str) -> str:
    """Titre de vignette : patron, round, format, seed, bord du clubhouse,
    nine extérieur et son sens."""
    return (f"{result.pattern} {label.upper()} · {width}×{height} · seed {seed} · bord "
            f"{result.clubhouse_edge} · {outer_nine} extérieur {side}")


def _run_format(width: int, height: int, *, seeds: tuple[int, ...] = SEEDS,
                label: str = "custom", out_name: str | None = None, planche: bool = True,
                pattern: str = "muirfield", width_mode: str = "variable",
                render: bool = True, size_errors: bool = False,
                extra: dict | None = None) -> dict:
    """Route ``seeds`` sur une taille et écrit ``report.json``.

    ``render=False`` saute SVG/PNG (et donc la planche). ``size_errors=True``
    (round ``calib`` seulement) enregistre une ``ValueError`` de relief ou de
    routage en statut ``taille_invalide`` au lieu de la laisser remonter ;
    toute autre exception remonte. ``extra`` est fusionné dans le rapport.
    """
    out_dir = OUTPUT_ROOT / (out_name or f"{label}_{width}x{height}")
    out_dir.mkdir(parents=True, exist_ok=True)
    reports, pngs = [], []
    caught = (ValueError,) if size_errors else ()
    for seed in seeds:
        t0 = time.perf_counter()
        try:
            heightmap = load_terrain(seed, width, height)
        except caught as error:
            reports.append(_size_error_report(seed, "relief", error, time.perf_counter() - t0))
            print(f"{width}x{height} seed {seed}: TAILLE INVALIDE (relief) {error}")
            continue
        terrain_seconds = time.perf_counter() - t0
        # mesure homogène succès/échec : même chronomètre autour de
        # build_course (sites + recherche + oracle, relief en cache exclu)
        t1 = time.perf_counter()
        try:
            result = build_course(seed, pattern, heightmap, width=width, height=height,
                                  width_mode=width_mode)
            elapsed = time.perf_counter() - t1
        except MuirfieldRoutingError as error:
            elapsed = time.perf_counter() - t1
            stages = dict(sorted(Counter(a["status"] for a in error.attempts).items()))
            reports.append({"seed": seed, "status": "echec", "elapsed_seconds": round(elapsed, 4),
                            "relaunches": len(error.attempts), "failure_stages": stages,
                            "attempts": error.attempts, "skipped": error.skipped,
                            "terrain_seconds_cached_or_built": round(terrain_seconds, 3)})
            print(f"{width}x{height} seed {seed}: ECHEC après {len(error.attempts)} tentative(s) "
                  f"{stages} · {len(error.skipped)} variante(s) sautée(s) · "
                  f"{elapsed * 1000:.0f} ms")
            continue
        except caught as error:
            elapsed = time.perf_counter() - t1
            report = _size_error_report(seed, "routage", error, elapsed)
            report["terrain_seconds_cached_or_built"] = round(terrain_seconds, 3)
            reports.append(report)
            print(f"{width}x{height} seed {seed}: TAILLE INVALIDE (routage) {error}")
            continue
        lengths = result.nine_lengths()
        kinds = dict(sorted(Counter(v.kind for v in result.violations).items()))
        # ``direction`` est le sens du nine EXTÉRIEUR (front pour muirfield,
        # back pour muirfield_inverse) ; le nine intérieur tourne en sens inverse
        side = "horaire" if result.direction > 0 else "anti-horaire"
        outer_nine = "front" if outer_start(result.pattern) == 1 else "back"
        if render:
            svg = render_readable_svg(
                result.layout, result.violations, heightmap=heightmap, water_level=WATER_LEVEL,
                rings=(result.outer_ring, result.inner_ring),
                title=_planche_title(result, label, width, height, seed, outer_nine, side),
                subtitle=(f"front par {lengths['front']['par']} · "
                          f"{lengths['front']['total']:.0f} blocs  |  "
                          f"back par {lengths['back']['par']} · "
                          f"{lengths['back']['total']:.0f} blocs  |  "
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
                                   back_path=result.back_path,
                                   outer_ring=result.outer_ring),
            "hole_widths": [h.width for h in result.layout.holes],
            "violations_total": len(result.violations),
            "violations_by_kind": kinds,
            "relaunches": result.relaunches,
            "attempts": list(result.attempts),
            # variantes sautées (échec déjà prouvé), hors de ``attempts``
            "skipped": list(result.skipped),
            "terrain_seconds_cached_or_built": round(terrain_seconds, 3),
            "elapsed_seconds": round(elapsed, 4),
            "timings": {k: round(v, 4) for k, v in result.timings.items()},
        })
        print(f"{width}x{height} seed {seed}: {len(result.violations)} violation(s) {kinds} · "
              f"{result.relaunches} relance(s) · front {lengths['front']['total']:.0f} / back "
              f"{lengths['back']['total']:.0f} blocs · {elapsed * 1000:.0f} ms")
    if pngs and planche:
        subprocess.run(
            ["magick", "montage", *pngs, "-tile", "3x", "-geometry", "+6+6",
             "-background", "#0d1117", str(out_dir / "planche.png")],
            check=True,
        )
    times = [r["elapsed_seconds"] for r in reports]
    succeeded = [r for r in reports if r["status"] == "succes"]
    summary = {
        "round": label.upper(), "pattern": pattern, "width_mode": width_mode,
        "width": width, "height": height,
        "seeds": list(seeds),
        "stats": {
            "successes": len(succeeded),
            "failures": [r["seed"] for r in reports if r["status"] != "succes"],
            "violations_total": sum(r.get("violations_total", 0) for r in succeeded),
            "relaunches_total": sum(r["relaunches"] for r in reports),
            "attempts_mean": (round(sum(len(r["attempts"]) for r in reports) / len(reports), 3)
                              if reports else None),
            "skipped_total": sum(len(r["skipped"]) for r in reports),
            "seconds_median": round(_percentile(times, 0.5), 3),
            "seconds_p90": round(_percentile(times, 0.9), 3),
            "seconds_max": round(max(times), 3) if times else None,
            "seeds_over_2s": [r["seed"] for r in reports if r["elapsed_seconds"] > 2.0],
            "shape_course": _shape_stats(reports),
            "shape_nines": _nine_shape_stats(reports),
        },
        "reports": reports,
    }
    if extra:
        summary.update(extra)
    print(f"{width}x{height}: {summary['stats']}")
    (out_dir / "report.json").write_text(json.dumps(summary, indent=2, sort_keys=True,
                                                    ensure_ascii=False) + "\n", encoding="utf-8")
    return summary


# --- calibration des tailles (round ``calib``) ------------------------------

class CalibSize(NamedTuple):
    short: int
    long: int
    orientation: str        # portrait : W=petit, H=grand ; paysage : l'inverse
    width: int
    height: int


def calib_grid(shorts=CALIB_SHORT, longs=CALIB_LONG,
               orientations=CALIB_ORIENTATIONS) -> list[CalibSize]:
    """Tailles de la grille : couples petit < grand, dans chaque orientation."""
    sizes = []
    for short in shorts:
        for long in longs:
            if not short < long:
                continue
            for orientation in orientations:
                if orientation == "portrait":
                    sizes.append(CalibSize(short, long, orientation, short, long))
                elif orientation == "paysage":
                    sizes.append(CalibSize(short, long, orientation, long, short))
                else:
                    raise ValueError(f"orientation inconnue : {orientation!r}")
    return sizes


def calib_out_name(pattern: str, width: int, height: int) -> str:
    return f"{CALIB_DIR}/{pattern}_{width}x{height}"


def run_calib(sizes: list[CalibSize], *, patterns=CALIB_PATTERNS, seeds=SEEDS,
              width_mode: str = "variable") -> dict:
    """Route chaque (taille, patron) séquentiellement, puis reconstruit la
    synthèse à partir de tous les report.json présents."""
    for size in sizes:
        for pattern in patterns:
            _run_format(size.width, size.height, seeds=seeds, label="calib",
                        out_name=calib_out_name(pattern, size.width, size.height),
                        planche=False, render=False, size_errors=True,
                        pattern=pattern, width_mode=width_mode,
                        extra={"calib": {"short": size.short, "long": size.long,
                                         "orientation": size.orientation}})
    return write_calib_summary()


def _calib_stats(reports: list[dict]) -> dict:
    """Statistiques d'un groupe de seeds (un patron, ou les deux poolés).

    Temps HORS relief sur les seeds routées (succès et échecs) ; une seed
    ``taille_invalide`` n'a pas de temps de routage significatif.
    """
    succeeded = [r for r in reports if r["status"] == "succes"]
    routed = [r for r in reports if r["status"] != "taille_invalide"]
    times = [r["elapsed_seconds"] for r in routed]
    terrain = [r["terrain_seconds_cached_or_built"] for r in reports
               if "terrain_seconds_cached_or_built" in r]
    stages: Counter = Counter()
    for r in reports:
        stages.update(r.get("failure_stages", {}))
    messages = sorted({r["message"] for r in reports if r["status"] == "taille_invalide"})
    return {
        "seeds": len(reports),
        "successes": len(succeeded),
        "violations_total": sum(r.get("violations_total", 0) for r in succeeded),
        "statuses": dict(sorted(Counter(r["status"] for r in reports).items())),
        "failed_seeds": sorted(r["seed"] for r in reports if r["status"] != "succes"),
        "failure_stages": dict(sorted(stages.items())),
        "size_error_messages": messages,
        "seconds_median": round(_percentile(times, 0.5), 3) if times else None,
        "seconds_p90": round(_percentile(times, 0.9), 3) if times else None,
        "seconds_max": round(max(times), 3) if times else None,
        "terrain_seconds_mean": round(sum(terrain) / len(terrain), 3) if terrain else None,
        "terrain_seconds_max": round(max(terrain), 3) if terrain else None,
    }


def _calib_verdict(stats: dict) -> list[str]:
    """Raisons de KO selon le critère de lecture (liste vide : OK)."""
    reasons = []
    if stats["statuses"].get("taille_invalide"):
        reasons.append("taille_invalide")
    if stats["successes"] < stats["seeds"]:
        reasons.append(f"réussites {stats['successes']}/{stats['seeds']}")
    if stats["violations_total"]:
        reasons.append(f"violations {stats['violations_total']}")
    if stats["seconds_p90"] is not None and stats["seconds_p90"] > CALIB_OK_P90_SECONDS:
        reasons.append(f"p90 {stats['seconds_p90']:.1f} s")
    if stats["seconds_max"] is not None and stats["seconds_max"] > CALIB_OK_MAX_SECONDS:
        reasons.append(f"max {stats['seconds_max']:.1f} s")
    return reasons


def build_calib_summary(reports: list[dict]) -> dict:
    """Synthèse : une ligne par (petit, grand, orientation, patron), plus une
    ligne agrégée par (petit, grand, orientation), patrons poolés. Le verdict
    agrégé est OK si chaque patron présent est OK ET que les deux sont là."""
    order = {name: i for i, name in enumerate(CALIB_ORIENTATIONS)}

    def key(report):
        c = report["calib"]
        return (c["short"], c["long"], order.get(c["orientation"], 99), report["pattern"])

    rows, groups = [], {}
    for report in sorted(reports, key=key):
        c = report["calib"]
        stats = _calib_stats(report["reports"])
        reasons = _calib_verdict(stats)
        row = {"short": c["short"], "long": c["long"], "orientation": c["orientation"],
               "pattern": report["pattern"], "width": report["width"],
               "height": report["height"], "width_mode": report["width_mode"],
               **stats, "ok": not reasons, "ko_reasons": reasons}
        rows.append(row)
        groups.setdefault((c["short"], c["long"], c["orientation"]), []).append((row, report))
    aggregated = []
    for (short, long, orientation), members in groups.items():
        pooled = [r for _, report in members for r in report["reports"]]
        stats = _calib_stats(pooled)
        patterns = sorted(row["pattern"] for row, _ in members)
        reasons = [f"{row['pattern']} : {reason}" for row, _ in members
                   for reason in row["ko_reasons"]]
        missing = [p for p in CALIB_PATTERNS if p not in patterns]
        reasons += [f"{p} : non mesuré" for p in missing]
        first = members[0][0]
        aggregated.append({"short": short, "long": long, "orientation": orientation,
                           "width": first["width"], "height": first["height"],
                           "patterns": patterns,
                           "successes_by_pattern": {row["pattern"]: row["successes"]
                                                    for row, _ in members},
                           **stats, "ok": not reasons, "ko_reasons": reasons})
    all_seeds = [r for report in reports for r in report["reports"]]
    return {
        "phase": 1,
        "criterion": {"successes": "toutes les seeds, chaque patron et orientation",
                      "violations": 0, "seconds_p90_max": CALIB_OK_P90_SECONDS,
                      "seconds_max_max": CALIB_OK_MAX_SECONDS,
                      "note": "critère de lecture, temps HORS relief ; ne filtre rien"},
        "grid": {"short": list(CALIB_SHORT), "long": list(CALIB_LONG),
                 "orientations": list(CALIB_ORIENTATIONS), "patterns": list(CALIB_PATTERNS)},
        "totals": {"reports": len(reports), "seeds_run": len(all_seeds),
                   "routing_seconds": round(sum(r["elapsed_seconds"] for r in all_seeds), 1),
                   "terrain_seconds": round(sum(r.get("terrain_seconds_cached_or_built", 0.0)
                                                for r in all_seeds), 1)},
        "rows": rows,
        "aggregated": aggregated,
    }


def _fmt_seconds(value) -> str:
    return "—" if value is None else f"{value:.2f}"


def calib_summary_markdown(summary: dict) -> str:
    """Rendu lisible de la synthèse (tableaux markdown)."""
    totals = summary["totals"]
    lines = [
        "# Calibration Muirfield — phase 1",
        "",
        f"Critère de lecture (ne filtre rien) : toutes les seeds réussies pour chaque patron "
        f"et orientation, 0 violation, p90 ≤ {CALIB_OK_P90_SECONDS:g} s et max ≤ "
        f"{CALIB_OK_MAX_SECONDS:g} s, temps HORS relief. Relief : chargé ou construit "
        f"(construit au 1er patron, en cache au 2e).",
        "",
        f"Total : {totals['reports']} combinaisons, {totals['seeds_run']} seeds, routage "
        f"{totals['routing_seconds']:.0f} s, relief {totals['terrain_seconds']:.0f} s.",
        "",
        "## Par taille et orientation (deux patrons poolés)",
        "",
        "| petit | grand | orientation | W×H | réussites (m / inv) | violations | médiane s "
        "| p90 s | max s | relief moyen s | statut |",
        "|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for a in summary["aggregated"]:
        by = a["successes_by_pattern"]
        succ = " / ".join(str(by.get(p, "—")) for p in CALIB_PATTERNS)
        status = "OK" if a["ok"] else "KO : " + " ; ".join(a["ko_reasons"])
        lines.append(f"| {a['short']} | {a['long']} | {a['orientation']} | "
                     f"{a['width']}×{a['height']} | {succ} | {a['violations_total']} | "
                     f"{_fmt_seconds(a['seconds_median'])} | {_fmt_seconds(a['seconds_p90'])} | "
                     f"{_fmt_seconds(a['seconds_max'])} | "
                     f"{_fmt_seconds(a['terrain_seconds_mean'])} | {status} |")
    lines += [
        "",
        "## Par patron",
        "",
        "| petit | grand | orientation | patron | réussites | violations | médiane s | p90 s "
        "| max s | relief moyen s | échecs |",
        "|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for r in summary["rows"]:
        failures = ", ".join(f"{k} {v}" for k, v in r["statuses"].items() if k != "succes")
        if r["failure_stages"]:
            failures += " (" + ", ".join(f"{k} {v}" for k, v in r["failure_stages"].items()) + ")"
        if r["size_error_messages"]:
            failures += " — " + " ; ".join(r["size_error_messages"])
        lines.append(f"| {r['short']} | {r['long']} | {r['orientation']} | {r['pattern']} | "
                     f"{r['successes']}/{r['seeds']} | {r['violations_total']} | "
                     f"{_fmt_seconds(r['seconds_median'])} | {_fmt_seconds(r['seconds_p90'])} | "
                     f"{_fmt_seconds(r['seconds_max'])} | "
                     f"{_fmt_seconds(r['terrain_seconds_mean'])} | {failures or '—'} |")
    return "\n".join(lines) + "\n"


def write_calib_summary() -> dict:
    """Relit tous les ``calib_phase1/*/report.json`` (fusion des morceaux) et
    écrit ``summary.json`` et ``summary.md``."""
    root = OUTPUT_ROOT / CALIB_DIR
    reports = [json.loads(path.read_text(encoding="utf-8"))
               for path in sorted(root.glob("*/report.json"))]
    summary = build_calib_summary(reports)
    root.mkdir(parents=True, exist_ok=True)
    (root / "summary.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False) + "\n",
                                       encoding="utf-8")
    (root / "summary.md").write_text(calib_summary_markdown(summary), encoding="utf-8")
    return summary


def _int_list(text: str | None) -> tuple[int, ...] | None:
    return None if text is None else tuple(int(v) for v in text.split(","))


def _parse_seeds(text: str) -> tuple[int, ...]:
    if "-" in text:
        low, high = (int(v) for v in text.split("-"))
        return tuple(range(low, high + 1))
    return tuple(int(v) for v in text.split(","))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--round", choices=("rc", "rc-30", "land", "land-30", "custom", "calib"),
                        default="rc")
    parser.add_argument("--pattern", choices=PATTERN_CHOICES, default=None,
                        help="patron explicite (défaut : muirfield ; rc-30/land/land-30 : tous)")
    parser.add_argument("--width-mode", choices=("variable", "min"), default="variable",
                        help="largeurs de fairway (défaut : variable ; min : largeur minimale)")
    parser.add_argument("--size", default="300x400", help="format LxH (round custom)")
    parser.add_argument("--seeds", default="1-6", help="ex. 1-6 ou 3,7 (rounds custom, calib)")
    parser.add_argument("--calib-short", default=None,
                        help="calib : petits côtés à lancer, ex. 240,260 (défaut : toute la grille)")
    parser.add_argument("--calib-long", default=None,
                        help="calib : grands côtés à lancer, ex. 400,450 (défaut : toute la grille)")
    parser.add_argument("--calib-orientation", choices=CALIB_ORIENTATIONS, default=None,
                        help="calib : une seule orientation (défaut : les deux)")
    parser.add_argument("--calib-summary-only", action="store_true",
                        help="calib : reconstruire la synthèse sans rien relancer")
    args = parser.parse_args()
    patterns = (args.pattern,) if args.pattern else PATTERNS
    if args.round == "rc":
        pattern = args.pattern or "muirfield"
        _run_format(300, 400, label="rc", out_name=f"rc_{pattern}_300x400", pattern=pattern,
                    width_mode=args.width_mode)
    elif args.round == "rc-30":
        for pattern in patterns:
            _run_format(300, 400, seeds=ROBUSTNESS_SEEDS, label="rc", planche=False,
                        out_name=f"rc_{pattern}_300x400_30seeds", pattern=pattern,
                        width_mode=args.width_mode)
    elif args.round in ("land", "land-30"):
        robust = args.round == "land-30"
        for pattern in patterns:
            suffix = "_30seeds" if robust else ""
            _run_format(400, 300, seeds=ROBUSTNESS_SEEDS if robust else SEEDS, label="land",
                        out_name=f"land_{pattern}_400x300{suffix}", planche=not robust,
                        pattern=pattern, width_mode=args.width_mode)
    elif args.round == "calib":
        if args.calib_summary_only:
            summary = write_calib_summary()
        else:
            for name, values, grid in (("--calib-short", _int_list(args.calib_short), CALIB_SHORT),
                                       ("--calib-long", _int_list(args.calib_long), CALIB_LONG)):
                if values and not set(values) <= set(grid):
                    parser.error(f"{name} hors grille {grid} : {values}")
            sizes = calib_grid(_int_list(args.calib_short) or CALIB_SHORT,
                               _int_list(args.calib_long) or CALIB_LONG,
                               (args.calib_orientation,) if args.calib_orientation
                               else CALIB_ORIENTATIONS)
            summary = run_calib(sizes, patterns=(args.pattern,) if args.pattern else CALIB_PATTERNS,
                                seeds=_parse_seeds(args.seeds), width_mode=args.width_mode)
        print(f"calib : {summary['totals']}")
    else:
        width, height = (int(v) for v in args.size.lower().split("x"))
        seeds = _parse_seeds(args.seeds)
        pattern = args.pattern or "muirfield"
        _run_format(width, height, seeds=seeds, label="custom", pattern=pattern,
                    out_name=f"custom_{pattern}_{width}x{height}", width_mode=args.width_mode)


if __name__ == "__main__":
    main()
