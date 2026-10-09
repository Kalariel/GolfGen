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
  ``--calib-orientation portrait``. Une taille refusée par la géométrie du
  cœur (``ring_semi_axes`` : carte trop petite pour deux anneaux), validée
  AVANT ``build_course``, y est enregistrée en ``taille_invalide`` au lieu
  d'interrompre le round ; toute autre exception (``ValueError`` comprise)
  remonte, et les autres rounds ne capturent rien de plus.
- ``calib2`` : calibration des tailles (phase 2), même mécanique sur les
  4 coins et le centre du rectangle retenu (petit 300–350 × grand 400–500),
  2 orientations × 2 patrons × seeds 1–30 → ``calib_phase2/``. Critère de
  lecture révisé par l'utilisateur : p90 ≤ 15 s, max ≤ 30 s. Mêmes filtres
  ``--calib-*`` (restreints aux couples de la phase 2).

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
from typing import Iterable, NamedTuple

from golfgen.routing.muirfield import (
    PATTERN_CHOICES,
    PATTERNS,
    MuirfieldRoutingError,
    build_course,
    outer_start,
    ring_semi_axes,
)
from tools.muirfield.render_readable import render_readable_svg
from tools.muirfield.shape_metrics import shape_metrics
from golfgen.routing.sites import WATER_LEVEL, DryMask, dry_mask, load_terrain


OUTPUT_ROOT = Path(__file__).resolve().parent / "output"
SEEDS = (1, 2, 3, 4, 5, 6)
ROBUSTNESS_SEEDS = tuple(range(1, 31))

CALIB_DIR = "calib_phase1"
CALIB_SHORT = (240, 260, 280, 300, 325, 350)
CALIB_LONG = (400, 450, 500)
CALIB_ORIENTATIONS = ("portrait", "paysage")
CALIB_PATTERNS = ("muirfield", "muirfield_inverse")
# critère de lecture d'une taille « OK » en phase 1 (affiché, ne filtre rien)
CALIB_OK_P90_SECONDS = 10.0
CALIB_OK_MAX_SECONDS = 30.0

CALIB2_DIR = "calib_phase2"
# 4 coins et centre du rectangle retenu après la phase 1 (petit, grand)
CALIB2_COUPLES = ((300, 400), (300, 500), (350, 400), (350, 500), (325, 450))
# critère révisé explicitement par l'utilisateur après la phase 1
CALIB2_OK_P90_SECONDS = 15.0
CALIB2_OK_MAX_SECONDS = 30.0


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


def wet_doglegs(layout, mask: DryMask) -> list[dict]:
    """Coudes de dogleg posés sur une cellule mouillée au sens de ``DryMask``
    (même critère que les sites de tee et de green) : ``[{"hole", "x", "y"}]``
    dans l'ordre des trous puis des coudes. Instrumentation seule : le
    routeur ne contrôle pas encore l'eau sous les coudes."""
    found = []
    for hole in layout.holes:
        if not hole.doglegs:
            continue
        dry = mask.is_dry([(p.x, p.y) for p in hole.doglegs])
        found.extend({"hole": hole.order, "x": round(p.x, 2), "y": round(p.y, 2)}
                     for p, ok in zip(hole.doglegs, dry) if not ok)
    return found


def _size_error(width: int, height: int) -> ValueError | None:
    """Refus de taille par la règle du cœur (``ring_semi_axes``), ou ``None``.

    Seul point de capture d'une ``ValueError`` dans les rounds ``calib*`` :
    l'appel ne fait que la géométrie des anneaux, donc l'erreur ne peut venir
    que de la taille de carte."""
    try:
        ring_semi_axes(width, height)
    except ValueError as error:
        return error
    return None


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
    (rounds ``calib*`` seulement) valide la taille AVANT relief et routage
    avec la règle du cœur (``ring_semi_axes``) et enregistre un refus en
    statut ``taille_invalide`` ; rien n'est capturé autour de ``load_terrain``
    ni de ``build_course``, donc toute autre exception — y compris une
    ``ValueError`` d'invariant, qui trahit un bug — remonte. ``extra`` est
    fusionné dans le rapport.
    """
    out_dir = OUTPUT_ROOT / (out_name or f"{label}_{width}x{height}")
    out_dir.mkdir(parents=True, exist_ok=True)
    reports, pngs = [], []
    for seed in seeds:
        if size_errors:
            t0 = time.perf_counter()
            size_error = _size_error(width, height)
            if size_error is not None:
                reports.append(_size_error_report(seed, "routage", size_error,
                                                  time.perf_counter() - t0))
                print(f"{width}x{height} seed {seed}: TAILLE INVALIDE (routage) {size_error}")
                continue
        t0 = time.perf_counter()
        heightmap = load_terrain(seed, width, height)
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
        wet = wet_doglegs(result.layout, dry_mask(heightmap))
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
            # coudes mouillés (critère DryMask des sites), détail trou + coordonnées
            "wet_doglegs": len(wet),
            "wet_dogleg_details": wet,
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
              f"{len(wet)} coude(s) mouillé(s) · "
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
            "wet_doglegs_total": sum(r["wet_doglegs"] for r in succeeded),
            "wet_dogleg_seeds": [r["seed"] for r in succeeded if r["wet_doglegs"]],
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


# --- calibration des tailles (rounds ``calib`` et ``calib2``) ---------------

class CalibPhase(NamedTuple):
    """Paramètres d'une phase de calibration : grille, dossier, critère.

    Critère de lecture (affiché, ne filtre rien) : ``ok_p90_seconds`` et
    ``ok_max_seconds``, temps de routage HORS relief. Le max de 30 s de la
    phase 1 (``CALIB_OK_MAX_SECONDS``, à côté d'un p90 de 10 s) est VOULU :
    il borne la pire seed acceptable, pas le temps typique, et ne doit pas
    être resserré sans décision explicite.

    ``seeds`` est l'ensemble attendu : une taille dont un patron n'a pas
    exactement ces seeds sort en KO (« seeds incomplètes », « seeds hors
    phase »). ``width_mode`` est le mode de largeurs unique de la phase :
    ``run_calib`` refuse d'en lancer un autre (la CLI le refuse aussi, même
    avec ``--calib-summary-only``) et la synthèse rejette tout rapport mesuré
    dans un autre mode.
    """
    number: int
    directory: str
    couples: tuple[tuple[int, int], ...]     # (petit, grand), petit < grand
    seeds: tuple[int, ...]
    ok_p90_seconds: float
    ok_max_seconds: float
    width_mode: str = "variable"


CALIB_PHASE1 = CalibPhase(1, CALIB_DIR,
                          tuple((s, l) for s in CALIB_SHORT for l in CALIB_LONG if s < l),
                          SEEDS, CALIB_OK_P90_SECONDS, CALIB_OK_MAX_SECONDS)
CALIB_PHASE2 = CalibPhase(2, CALIB2_DIR, CALIB2_COUPLES, ROBUSTNESS_SEEDS,
                          CALIB2_OK_P90_SECONDS, CALIB2_OK_MAX_SECONDS)


class CalibSize(NamedTuple):
    short: int
    long: int
    orientation: str        # portrait : W=petit, H=grand ; paysage : l'inverse
    width: int
    height: int


def calib_grid(shorts=CALIB_SHORT, longs=CALIB_LONG,
               orientations=CALIB_ORIENTATIONS) -> list[CalibSize]:
    """Tailles de la grille : couples petit < grand, dans chaque orientation."""
    return calib_sizes([(s, l) for s in shorts for l in longs if s < l], orientations)


def calib_sizes(couples, orientations=CALIB_ORIENTATIONS) -> list[CalibSize]:
    """Tailles d'une liste de couples (petit, grand), dans chaque orientation."""
    sizes = []
    for short, long in couples:
        for orientation in orientations:
            if orientation == "portrait":
                sizes.append(CalibSize(short, long, orientation, short, long))
            elif orientation == "paysage":
                sizes.append(CalibSize(short, long, orientation, long, short))
            else:
                raise ValueError(f"orientation inconnue : {orientation!r}")
    return sizes


def calib_out_name(pattern: str, width: int, height: int,
                   phase: CalibPhase = CALIB_PHASE1) -> str:
    return f"{phase.directory}/{pattern}_{width}x{height}"


def run_calib(sizes: list[CalibSize], *, patterns=CALIB_PATTERNS, seeds=SEEDS,
              width_mode: str = "variable", phase: CalibPhase = CALIB_PHASE1) -> dict:
    """Route chaque (taille, patron) séquentiellement, puis reconstruit la
    synthèse à partir de tous les report.json présents.

    ``width_mode`` doit être celui de la phase : un autre mode mélangerait
    silencieusement deux mesures dans le même dossier (refus avant tout
    routage)."""
    if width_mode != phase.width_mode:
        raise ValueError(f"width_mode {width_mode!r} : la phase {phase.number} est calibrée en "
                         f"{phase.width_mode!r}")
    for size in sizes:
        for pattern in patterns:
            label = "calib" if phase.number == 1 else f"calib{phase.number}"
            _run_format(size.width, size.height, seeds=seeds, label=label,
                        out_name=calib_out_name(pattern, size.width, size.height, phase),
                        planche=False, render=False, size_errors=True,
                        pattern=pattern, width_mode=width_mode,
                        extra={"calib": {"short": size.short, "long": size.long,
                                         "orientation": size.orientation}})
    return write_calib_summary(phase)


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


def _calib_verdict(stats: dict, seeds: Iterable[int],
                   phase: CalibPhase = CALIB_PHASE1) -> list[str]:
    """Raisons de KO selon le critère de lecture de la phase (liste vide : OK).

    ``seeds`` : seeds présentes dans le rapport. La complétude compare
    l'ENSEMBLE à celui de la phase (``--seeds 7-12`` en phase 1 compte bien
    six seeds, mais pas les bonnes)."""
    reasons = []
    present, expected = set(seeds), set(phase.seeds)
    if not expected <= present:
        reasons.append(f"seeds incomplètes {len(present & expected)}/{len(expected)}")
    if present - expected:
        reasons.append(f"seeds hors phase {sorted(present - expected)}")
    if stats["statuses"].get("taille_invalide"):
        reasons.append("taille_invalide")
    if stats["successes"] < stats["seeds"]:
        reasons.append(f"réussites {stats['successes']}/{stats['seeds']}")
    if stats["violations_total"]:
        reasons.append(f"violations {stats['violations_total']}")
    if stats["seconds_p90"] is not None and stats["seconds_p90"] > phase.ok_p90_seconds:
        reasons.append(f"p90 {stats['seconds_p90']:.1f} s")
    if stats["seconds_max"] is not None and stats["seconds_max"] > phase.ok_max_seconds:
        reasons.append(f"max {stats['seconds_max']:.1f} s")
    return reasons


def build_calib_summary(reports: list[dict], phase: CalibPhase = CALIB_PHASE1) -> dict:
    """Synthèse : une ligne par (petit, grand, orientation, patron), plus une
    ligne agrégée par (petit, grand, orientation), patrons poolés. Le verdict
    agrégé est OK si chaque patron présent est OK ET que les deux sont là.

    Tous les rapports doivent avoir le ``width_mode`` de la phase : sinon
    ``ValueError`` (deux modes ne se poolent pas en silence)."""
    mixed = sorted(f"{r['pattern']}_{r['width']}x{r['height']} ({r['width_mode']})"
                   for r in reports if r["width_mode"] != phase.width_mode)
    if mixed:
        raise ValueError(f"rapports hors width_mode {phase.width_mode!r} de la phase "
                         f"{phase.number} : {', '.join(mixed)}")
    order = {name: i for i, name in enumerate(CALIB_ORIENTATIONS)}

    def key(report):
        c = report["calib"]
        return (c["short"], c["long"], order.get(c["orientation"], 99), report["pattern"])

    rows, groups = [], {}
    for report in sorted(reports, key=key):
        c = report["calib"]
        stats = _calib_stats(report["reports"])
        reasons = _calib_verdict(stats, (r["seed"] for r in report["reports"]), phase)
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
    if phase.number == 1:
        grid = {"short": list(CALIB_SHORT), "long": list(CALIB_LONG)}
    else:
        grid = {"couples": [list(c) for c in phase.couples],
                "seeds": [phase.seeds[0], phase.seeds[-1]]}
    return {
        "phase": phase.number,
        "criterion": {"successes": "toutes les seeds, chaque patron et orientation",
                      "violations": 0, "seconds_p90_max": phase.ok_p90_seconds,
                      "seconds_max_max": phase.ok_max_seconds,
                      "note": "critère de lecture, temps HORS relief ; ne filtre rien"},
        "grid": {**grid, "orientations": list(CALIB_ORIENTATIONS),
                 "patterns": list(CALIB_PATTERNS)},
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
    criterion = summary["criterion"]
    lines = [
        f"# Calibration Muirfield — phase {summary['phase']}",
        "",
        f"Critère de lecture (ne filtre rien) : toutes les seeds réussies pour chaque patron "
        f"et orientation, 0 violation, p90 ≤ {criterion['seconds_p90_max']:g} s et max ≤ "
        f"{criterion['seconds_max_max']:g} s, temps HORS relief. Relief : chargé ou construit "
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


def write_calib_summary(phase: CalibPhase = CALIB_PHASE1) -> dict:
    """Relit tous les ``<dossier de la phase>/*/report.json`` (fusion des
    morceaux) et écrit ``summary.json`` et ``summary.md``."""
    root = OUTPUT_ROOT / phase.directory
    reports = [json.loads(path.read_text(encoding="utf-8"))
               for path in sorted(root.glob("*/report.json"))]
    summary = build_calib_summary(reports, phase)
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
    parser.add_argument("--round", choices=("rc", "rc-30", "land", "land-30", "custom", "calib",
                                            "calib2"),
                        default="rc")
    parser.add_argument("--pattern", choices=PATTERN_CHOICES, default=None,
                        help="patron explicite (défaut : muirfield ; rc-30/land/land-30 : tous)")
    parser.add_argument("--width-mode", choices=("variable", "min"), default="variable",
                        help="largeurs de fairway (défaut : variable ; min : largeur minimale)")
    parser.add_argument("--size", default="300x400", help="format LxH (round custom)")
    parser.add_argument("--seeds", default=None,
                        help="ex. 1-6 ou 3,7 (rounds custom et calib : défaut 1-6 ; calib2 : 1-30)")
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
    elif args.round in ("calib", "calib2"):
        phase = CALIB_PHASE1 if args.round == "calib" else CALIB_PHASE2
        if args.width_mode != phase.width_mode:
            parser.error(f"--width-mode {args.width_mode} : la phase {phase.number} est "
                         f"calibrée en {phase.width_mode}")
        if args.calib_summary_only:
            summary = write_calib_summary(phase)
        else:
            shorts = sorted({s for s, _ in phase.couples})
            longs = sorted({l for _, l in phase.couples})
            wanted_short, wanted_long = _int_list(args.calib_short), _int_list(args.calib_long)
            for name, values, grid in (("--calib-short", wanted_short, shorts),
                                       ("--calib-long", wanted_long, longs)):
                if values and not set(values) <= set(grid):
                    parser.error(f"{name} hors grille {grid} : {values}")
            couples = [(s, l) for s, l in phase.couples
                       if (not wanted_short or s in wanted_short)
                       and (not wanted_long or l in wanted_long)]
            sizes = calib_sizes(couples, (args.calib_orientation,) if args.calib_orientation
                                else CALIB_ORIENTATIONS)
            seeds = _parse_seeds(args.seeds) if args.seeds else phase.seeds
            summary = run_calib(sizes, patterns=(args.pattern,) if args.pattern else CALIB_PATTERNS,
                                seeds=seeds, width_mode=args.width_mode, phase=phase)
        print(f"{args.round} : {summary['totals']}")
    else:
        width, height = (int(v) for v in args.size.lower().split("x"))
        seeds = _parse_seeds(args.seeds or "1-6")
        pattern = args.pattern or "muirfield"
        _run_format(width, height, seeds=seeds, label="custom", pattern=pattern,
                    out_name=f"custom_{pattern}_{width}x{height}", width_mode=args.width_mode)


if __name__ == "__main__":
    main()
