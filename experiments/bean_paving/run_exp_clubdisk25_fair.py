"""Expérience "disque équitable" (PLAN.md ligne 6, décision utilisateur) :
reprend EXACTEMENT la baseline "back-far" (``output/benchmark_course18_400_backfar_1_10``,
config B + ``back_clubhouse_max=100`` + ``back_start_radii=(44,48,64,80,96)`` +
``back_closing_lookahead_from=7`` -- sur les seeds 1-5 : **4/5**, seed 4 en
échec), départs sur la grille FIXE (pas de tirage aléatoire -- contrairement
à ``run_exp_departures_and_disk.py``, EXP1), plus :

- ``geometry.ValidationRules.clubhouse_block_radius=25.0`` -- disque
  d'exclusion clubhouse TOTAL (cœur ET rough), comme l'expérience 2 "disque
  25" précédente (``output/exp_clubdisk25_400_1_5``, résultat **0/5**).

Différence avec cette expérience 2 (le constat qui motive cette variante
"équitable") : l'ancienne combinaison front ``start_radii=(40, 48)`` +
``clubhouse_max=60`` + cible de profondeur 9 = ``max(cible, 25+15)=40``
laissait un anneau jouable trop étroit -- une empreinte s'étend sur 10 à 14
blocs autour d'un tee/green (demi-largeur + 5 de rough), donc un point
d'ancrage (tee ou green) doit rester à AU MOINS 35-39 blocs du clubhouse
pour que son empreinte entière reste hors du disque de 25 ; à 40-48, la
marge restante (1 à 13 blocs) était trop fine pour que la recherche referme
systématiquement sur le trou 9/18. Cette variante élargit donc l'anneau :

- front ``start_radii`` : ``(45.0, 55.0, 65.0)`` (secteur de départ
  ``departure_angles`` inchangé, ``(300, 330, 0, 30, 60)``) ;
- front ``clubhouse_max`` : ``80.0`` (plafond dur départ trou 1 / retour
  trou 9, au lieu de ``60.0`` dans l'expérience "disque 25" étroite) ;
- cible de score de profondeur 9 (``solver.SolverParams.target_radius_depth9_min``,
  nouveau paramètre EXPLICITE -- voir sa docstring -- qui prend le pas sur la
  formule ``max(cible actuelle, rules.clubhouse_block_radius + 15) = 40``
  utilisée par l'expérience "disque 25" étroite) : ``50.0`` pour LES DEUX
  nines, front et back.
- back : INCHANGÉ (baseline back-far -- ``clubhouse_max=100``,
  ``start_radii=(44, 48, 64, 80, 96)``, ``closing_lookahead_from=7``), tous
  ses rayons de départ (>= 44) sont déjà hors du disque de 25 par
  construction.

Exécution : 5 seeds (1 à 5), EN PARALLÈLE (5 process), foreground, une ligne
de log par seed terminé (``flush=True``), pas de notification de fin
différée. Temps réel mesuré par seed (``time.perf_counter``, dans le
process du seed, donc insensible à l'attente des autres).
"""

from __future__ import annotations

from collections import Counter
from concurrent.futures import ProcessPoolExecutor, as_completed
import json
import math
from pathlib import Path
import time

from experiments.bean_paving.benchmark_course import _last_depths, _largest_parallel_stack, _polygon_area
from experiments.bean_paving.course_solver import CourseSolveResult, _course_violations, solve_course
from experiments.bean_paving.geometry import ValidationRules
from experiments.bean_paving.render_course import render_course_svg
from experiments.bean_paving.solver import SolverParams

SEEDS = range(1, 6)
BACKFAR_BASELINE_REPORT = Path("experiments/bean_paving/output/benchmark_course18_400_backfar_1_10/report.json")
NARROW_DISK_REPORT = Path("experiments/bean_paving/output/exp_clubdisk25_400_1_5/report.json")
OUTPUT_DIR = Path("experiments/bean_paving/output/exp_clubdisk25_fair_400_1_5")

CLUBHOUSE_BLOCK_RADIUS = 25.0
FRONT_START_RADII = (45.0, 55.0, 65.0)
FRONT_CLUBHOUSE_MAX = 80.0
TARGET_RADIUS_DEPTH9_MIN = 50.0


def _front_params() -> SolverParams:
    return SolverParams(beam_width=72, departure_angles=(300, 330, 0, 30, 60),
                        target_radius_scale=0.9, bbox_weight=0.0004,
                        start_radii=FRONT_START_RADII, clubhouse_max=FRONT_CLUBHOUSE_MAX,
                        target_radius_depth9_min=TARGET_RADIUS_DEPTH9_MIN)


def _back_params() -> SolverParams:
    # Config "back-far" inchangée (output/benchmark_course18_400_backfar_1_10),
    # seule la cible explicite de profondeur 9 est ajoutée (sans effet sur le
    # plafond dur ``clubhouse_max=100``, ni sur les rayons de départ, déjà
    # tous >= 44 > 25).
    return SolverParams(beam_width=72, candidates_per_par=4, transforms_per_candidate=36,
                        departure_angles=tuple(range(0, 360, 30)), start_radii=(44.0, 48.0, 64.0, 80.0, 96.0),
                        start_transforms_per_candidate=144, clubhouse_max=100.0,
                        closing_lookahead_from=7, target_radius_depth9_min=TARGET_RADIUS_DEPTH9_MIN)


def _rules() -> ValidationRules:
    return ValidationRules(width=400.0, height=400.0, shared_rough=True, fairway_gap=5.0, edge_min=1.0,
                           max_parallel_stack=3, clubhouse_clear_radius=10.0,
                           clubhouse_block_radius=CLUBHOUSE_BLOCK_RADIUS)


def _run_seed(seed: int):
    start = time.perf_counter()
    result = solve_course(seed, _front_params(), _back_params(), _rules(), bounded_quota=True)
    return result, time.perf_counter() - start


def _seed_summary(result: CourseSolveResult, elapsed: float, rules: ValidationRules) -> dict:
    front_placed = result.front.state.placed
    back_placed = () if result.back is None else result.back.state.placed
    all_placed = front_placed + back_placed
    clubhouse = rules.clubhouse
    front_clubhouse_max = result.front.params.clubhouse_max
    back_clubhouse_max = (SolverParams().clubhouse_max if result.back is None
                          else result.back.params.clubhouse_max)
    independent_violations = _course_violations(front_placed, back_placed, rules, clubhouse,
                                                front_clubhouse_max, back_clubhouse_max)
    independent_valid = (len(front_placed) == 9 and len(back_placed) == 9 and not independent_violations)

    tee1 = round(math.dist(front_placed[0].tee, clubhouse), 3) if front_placed else None
    green9 = round(math.dist(front_placed[-1].green, clubhouse), 3) if front_placed else None
    tee10 = round(math.dist(back_placed[0].tee, clubhouse), 3) if back_placed else None
    green18 = round(math.dist(back_placed[-1].green, clubhouse), 3) if back_placed else None

    footprint_ratio = (sum(_polygon_area(bean.footprint) for bean in all_placed)
                       / (rules.width * rules.height)) if all_placed else 0.0

    rejection_counts: Counter = Counter()
    for nine in (result.front, result.back):
        if nine is None:
            continue
        for depth in nine.diagnostics:
            rejection_counts.update(depth.rejection_counts)

    disk_rejections = rejection_counts.get("clubhouse_block", 0)
    disk_violations_independent = sum(1 for kind in independent_violations if kind == "clubhouse_block")

    return {
        "seed": result.seed,
        "success": result.complete,
        "independent_valid": independent_valid,
        "independent_violations": independent_violations,
        "seconds": round(elapsed, 3),
        "front_holes": len(front_placed),
        "back_holes": len(back_placed),
        "front_pars": [bean.template.par for bean in front_placed],
        "back_pars": [bean.template.par for bean in back_placed],
        "footprint_ratio": round(footprint_ratio, 4),
        "largest_parallel_stack": _largest_parallel_stack(all_placed, rules),
        "rejection_counts": dict(sorted(rejection_counts.items())),
        "clubhouse_block_rejections": disk_rejections,
        "clubhouse_block_independent_violations": disk_violations_independent,
        "front_last_depths": _last_depths(result.front.diagnostics),
        "back_last_depths": () if result.back is None else _last_depths(result.back.diagnostics),
        "front_clubhouse_max": front_clubhouse_max,
        "back_clubhouse_max": back_clubhouse_max,
        "tee1_distance": tee1,
        "green9_distance": green9,
        "back_start_distance": tee10,
        "back_return_distance": green18,
    }


def _report_lookup(path: Path) -> dict[int, dict]:
    if not path.exists():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    key = "seeds"
    return {item["seed"]: item for item in data[key] if item["seed"] in SEEDS}


def _markdown(summaries: list[dict], rules: ValidationRules, total_seconds: float,
             backfar: dict[int, dict], narrow_disk: dict[int, dict]) -> str:
    success_count = sum(item["success"] for item in summaries)
    independent_valid_count = sum(item["independent_valid"] for item in summaries)
    backfar_success = sum(1 for seed in SEEDS if backfar.get(seed, {}).get("success"))
    narrow_success = sum(1 for seed in SEEDS if narrow_disk.get(seed, {}).get("success"))
    lines = [
        "# Expérience — disque d'exclusion clubhouse 25 blocs, anneau de départ élargi \"équitable\" "
        "(seeds 1 à 5, 400×400)",
        "",
        f"- Succès (18/18) : **{success_count}/5** "
        f"(baseline back-far seeds 1-5 : **{backfar_success}/5** ; disque 25 étroit (EXP2) : "
        f"**{narrow_success}/5**)",
        f"- Validation indépendante conforme : **{independent_valid_count}/5**",
        f"- Temps total (5 process en parallèle) : **{total_seconds:.1f}s**",
        "",
        f"- Disque : rayon **{CLUBHOUSE_BLOCK_RADIUS}** autour du clubhouse, empreinte entière "
        "(cœur ET rough) interdite dedans -- même règle que l'expérience \"disque 25\" étroite. "
        f"Différence : front `start_radii`={FRONT_START_RADII} (étroit : (40.0, 48.0)), secteur de "
        "départ inchangé ; front `clubhouse_max`="
        f"{FRONT_CLUBHOUSE_MAX} (étroit : 60.0) ; cible de score de profondeur 9 fixée EXPLICITEMENT "
        f"(`solver.SolverParams.target_radius_depth9_min`) à **{TARGET_RADIUS_DEPTH9_MIN}** pour LES "
        "DEUX nines (étroit : formule `max(cible, 25+15)=40`, implicite). Back inchangé "
        "(baseline back-far : `clubhouse_max`=100, `start_radii`=(44, 48, 64, 80, 96), "
        "`closing_lookahead_from`=7). Départs sur grille FIXE (pas de tirage aléatoire).",
        "",
        "| Seed | Résultat | Front | Back | Temps | Tee1→club | Green9→club | Tee10→club | "
        "Green18→club | Pile max | Indép. | Back-far | Disque étroit (EXP2) |",
        "|---:|:---:|:---:|:---:|---:|---:|---:|---:|---:|---:|:---:|:---:|:---:|",
    ]
    for item in summaries:
        backfar_item = backfar.get(item["seed"], {})
        narrow_item = narrow_disk.get(item["seed"], {})
        backfar_text = (f"{'OK' if backfar_item.get('success') else 'échec'} {backfar_item.get('seconds', 0):.1f}s"
                       if backfar_item else "—")
        narrow_text = (f"{'OK' if narrow_item.get('success') else 'échec'} {narrow_item.get('seconds', 0):.1f}s"
                      if narrow_item else "—")
        result = "OK" if item["success"] else "échec"
        indep = "OK" if item["independent_valid"] else "KO"
        tee1 = f"{item['tee1_distance']:.1f}" if item["tee1_distance"] is not None else "—"
        green9 = f"{item['green9_distance']:.1f}" if item["green9_distance"] is not None else "—"
        tee10 = f"{item['back_start_distance']:.1f}" if item["back_start_distance"] is not None else "—"
        green18 = f"{item['back_return_distance']:.1f}" if item["back_return_distance"] is not None else "—"
        lines.append(
            f"| {item['seed']} | {result} | {item['front_holes']}/9 | {item['back_holes']}/9 | "
            f"{item['seconds']:.1f}s | {tee1} | {green9} | {tee10} | {green18} | "
            f"{item['largest_parallel_stack']} | {indep} | {backfar_text} | {narrow_text} |")

    lines.extend(["", "## Comparaison seed par seed", ""])
    for item in summaries:
        backfar_item = backfar.get(item["seed"])
        narrow_item = narrow_disk.get(item["seed"])
        parts = [f"seed {item['seed']} : {'OK' if item['success'] else 'échec'}"]
        if backfar_item is not None:
            same = item["success"] == backfar_item["success"]
            delta = item["seconds"] - backfar_item["seconds"]
            parts.append(f"vs back-far ({'identique' if same else 'DIFFÉRENT'}, "
                        f"{'OK' if backfar_item['success'] else 'échec'} {backfar_item['seconds']:.1f}s, "
                        f"delta {delta:+.1f}s)")
        if narrow_item is not None:
            same = item["success"] == narrow_item["success"]
            delta = item["seconds"] - narrow_item["seconds"]
            parts.append(f"vs disque étroit ({'identique' if same else 'DIFFÉRENT'}, "
                        f"{'OK' if narrow_item['success'] else 'échec'} {narrow_item['seconds']:.1f}s, "
                        f"delta {delta:+.1f}s)")
        lines.append("- " + ", ".join(parts) + ".")

    lines.extend(["", "## Pars par nine (ordre de jeu)", ""])
    for item in summaries:
        front = "-".join(map(str, item["front_pars"])) or "—"
        back = "-".join(map(str, item["back_pars"])) or "—"
        lines.append(f"- seed {item['seed']} : front {front} / back {back}")

    lines.extend(["", "## Rejets cumulés", ""])
    all_rejections: Counter = Counter()
    for item in summaries:
        all_rejections.update(item["rejection_counts"])
    for kind, count in sorted(all_rejections.items()):
        lines.append(f"- `{kind}` : {count}")
    total_disk = sum(item["clubhouse_block_rejections"] for item in summaries)
    lines.append(f"- dont `clubhouse_block` (disque {CLUBHOUSE_BLOCK_RADIUS}) : **{total_disk}** "
                "rejets cumulés sur les 5 seeds")

    lines.extend(["", "## Front — 3 dernières profondeurs explorées (causes de rejet)", ""])
    for item in summaries:
        lines.append(f"- seed {item['seed']} :")
        for depth_info in item.get("front_last_depths", ()):
            dominant = list(depth_info["rejection_counts"].items())[:3]
            dominant_text = ", ".join(f"{kind} {count}" for kind, count in dominant) or "—"
            lines.append(
                f"  - profondeur {depth_info['depth']} : {depth_info['trials']} essais, "
                f"{depth_info['accepted']} acceptés, {depth_info['kept']} gardés — {dominant_text}")

    lines.extend(["", "## Back — 3 dernières profondeurs explorées (causes de rejet)", ""])
    for item in summaries:
        lines.append(f"- seed {item['seed']} :")
        for depth_info in item.get("back_last_depths", ()):
            dominant = list(depth_info["rejection_counts"].items())[:3]
            dominant_text = ", ".join(f"{kind} {count}" for kind, count in dominant) or "—"
            lines.append(
                f"  - profondeur {depth_info['depth']} : {depth_info['trials']} essais, "
                f"{depth_info['accepted']} acceptés, {depth_info['kept']} gardés — {dominant_text}")

    failures = [item for item in summaries if not item["success"]]
    if failures:
        lines.extend(["", "## Échecs — causes dominantes", ""])
        for item in failures:
            dominant = sorted(item["rejection_counts"].items(), key=lambda kv: -kv[1])[:3]
            dominant_text = ", ".join(f"{kind} {count}" for kind, count in dominant) or "—"
            lines.append(f"- seed {item['seed']} : front {item['front_holes']}/9, "
                         f"back {item['back_holes']}/9 — causes dominantes : {dominant_text}")
    lines.append("")
    return "\n".join(lines)


def main() -> None:
    backfar = _report_lookup(BACKFAR_BASELINE_REPORT)
    narrow_disk = _report_lookup(NARROW_DISK_REPORT)
    rules = _rules()
    total_start = time.perf_counter()
    completed: dict[int, tuple[CourseSolveResult, float]] = {}

    with ProcessPoolExecutor(max_workers=5) as executor:
        futures = {executor.submit(_run_seed, seed): seed for seed in SEEDS}
        for future in as_completed(futures):
            result, elapsed = future.result()
            completed[result.seed] = (result, elapsed)
            back_depth = 0 if result.back is None else result.back.state.depth
            print(f"[clubdisk25-fair] seed {result.seed}: {'OK' if result.complete else 'échec'} "
                  f"front={result.front.state.depth}/9 back={back_depth}/9 temps={elapsed:.1f}s "
                  f"({len(completed)}/{len(SEEDS)} terminés)", flush=True)

    total_seconds = round(time.perf_counter() - total_start, 3)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    summaries = []
    for seed in sorted(completed):
        result, elapsed = completed[seed]
        summary = _seed_summary(result, elapsed, rules)
        summaries.append(summary)
        suffix = "course18_400" + ("" if result.complete else "_failed")
        (OUTPUT_DIR / f"seed{seed}_{suffix}.json").write_text(result.to_json(), encoding="utf-8")
        (OUTPUT_DIR / f"seed{seed}_{suffix}.svg").write_text(render_course_svg(result, rules), encoding="utf-8")

    success_count = sum(item["success"] for item in summaries)
    independent_valid_count = sum(item["independent_valid"] for item in summaries)
    report = {
        "experiment": "clubdisk25_fair",
        "size": 400,
        "seeds_requested": list(SEEDS),
        "rules": {
            "shared_rough": rules.shared_rough,
            "fairway_gap": rules.fairway_gap,
            "edge_min": rules.edge_min,
            "max_parallel_stack": rules.max_parallel_stack,
            "clubhouse_clear_radius": rules.clubhouse_clear_radius,
            "clubhouse_block_radius": rules.clubhouse_block_radius,
        },
        "front_start_radii": list(FRONT_START_RADII),
        "front_clubhouse_max": FRONT_CLUBHOUSE_MAX,
        "target_radius_depth9_min": TARGET_RADIUS_DEPTH9_MIN,
        "success_count": success_count,
        "independent_valid_count": independent_valid_count,
        "total_seconds": total_seconds,
        "seeds": summaries,
    }
    (OUTPUT_DIR / "report.json").write_text(json.dumps(report, indent=2, sort_keys=True) + "\n",
                                            encoding="utf-8")
    (OUTPUT_DIR / "REPORT.md").write_text(
        _markdown(summaries, rules, total_seconds, backfar, narrow_disk), encoding="utf-8")
    print(f"clubdisk25-fair: {success_count}/5 complet, {independent_valid_count}/5 validé "
          f"indépendamment (back-far seeds 1-5 : "
          f"{sum(1 for s in SEEDS if backfar.get(s, {}).get('success'))}/5 ; disque étroit : "
          f"{sum(1 for s in SEEDS if narrow_disk.get(s, {}).get('success'))}/5)", flush=True)


if __name__ == "__main__":
    main()
