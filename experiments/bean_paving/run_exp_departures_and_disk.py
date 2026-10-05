"""Deux expériences INDÉPENDANTES (PLAN.md ligne 6, décision utilisateur),
seeds 1 à 5, 400×400, même baseline commune "back-far"
(``output/benchmark_course18_400_backfar_1_10``, config B + back_clubhouse_max=100
+ back_start_radii=(44,48,64,80,96) : sur les seeds 1-5, baseline = 4/5
complet, seed 4 en échec).

EXP 1 -- DÉPARTS ALÉATOIRES (``solver.SolverParams.random_departures``) :
remplace la grille fixe (``departure_angles`` x ``start_radii``) du tee de
profondeur 1 par des positions tirées, cercle COMPLET ``[0, 360)`` et rayon
uniforme dans un intervalle, pour les DEUX nines. Nombre de positions = taille
de la grille qu'il remplace (coût comparable) : front 10 (= 2 rayons x 5
angles du secteur baseline), rayon ``[24, 48]`` (``front.clubhouse_max``
reste 50) ; back 60 (= 5 rayons x 12 angles), rayon ``[44, 96]``
(``back.clubhouse_max`` reste 100). Tirage déterministe par ``(seed, nine)``
(``solver._rng_for``, le seed du back diffère déjà du front via
``seed ^ 0x9E3779B9``, ``course_solver.solve_course``). Tout le reste =
baseline back-far à l'identique.

EXP 2 -- DISQUE D'EXCLUSION CLUBHOUSE TOTAL
(``geometry.ValidationRules.clubhouse_block_radius=25.0``) : aucune empreinte
(cœur FAIRWAY et ROUGH) d'aucun trou ne peut intersecter un disque de 25
blocs autour du clubhouse -- règle dure nouvelle, appliquée inconditionnellement
dans ``geometry.validate`` (donc dans tous les chemins du solveur, y compris
``_has_closing_sequence``/fermeture anticipée, sans changement séparé côté
``solver.py`` pour la DÉTECTION). Départs restent sur la grille fixe (PAS de
tirage aléatoire ici -- les deux expériences sont indépendantes). Conséquences
nécessaires, documentées ici et nulle part ailleurs :
  - front ``start_radii`` : ``(24.0, 36.0)`` -> ``(40.0, 48.0)`` -- 24 et 36
    sont trop proches (resp. dans et à la limite du disque de 25) pour que le
    rough du tee 1 reste dehors.
  - front ``clubhouse_max`` : ``50.0`` -> ``60.0`` -- marge d'anneau pour que
    le trou 1 (départ désormais à 40-48) et le retour du trou 9 restent
    both jouables sans resserrer la recherche autour du plafond dur.
  - front ET back, cible de score de profondeur 9
    (``solver._scaled_target_radius``) : élargie à
    ``max(cible actuelle, 25 + 15) = 40`` par le code déjà commité
    (lit ``rules.clubhouse_block_radius`` directement, aucun paramètre
    supplémentaire à passer ici) -- oriente la recherche vers un retour
    nettement hors du disque plutôt que juste à sa frontière.
  - back ``start_radii``/``clubhouse_max`` : INCHANGÉS (baseline back-far,
    tous les rayons >= 44 > 25, déjà hors du disque par construction).

Exécution : les DEUX expériences, 5 seeds chacune (10 jobs), EN PARALLÈLE
(10 process sur 16 cœurs disponibles) -- foreground, une ligne de log par
seed terminé (``flush=True``), pas de notification de fin différée.
"""

from __future__ import annotations

from collections import Counter
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import replace
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
BASELINE_REPORT = Path("experiments/bean_paving/output/benchmark_course18_400_backfar_1_10/report.json")

EXPERIMENTS = {
    "departures": Path("experiments/bean_paving/output/exp_departures_400_1_5"),
    "clubdisk25": Path("experiments/bean_paving/output/exp_clubdisk25_400_1_5"),
}

FRONT_DEPARTURE_COUNT = 10  # = 2 rayons x 5 angles du secteur baseline
FRONT_DEPARTURE_RADIUS = (24.0, 48.0)
BACK_DEPARTURE_COUNT = 60  # = 5 rayons x 12 angles (grille back-far)
BACK_DEPARTURE_RADIUS = (44.0, 96.0)
CLUBHOUSE_BLOCK_RADIUS = 25.0
EXP2_FRONT_START_RADII = (40.0, 48.0)
EXP2_FRONT_CLUBHOUSE_MAX = 60.0


def _front_base() -> SolverParams:
    return SolverParams(beam_width=72, departure_angles=(300, 330, 0, 30, 60),
                        target_radius_scale=0.9, bbox_weight=0.0004)


def _back_base() -> SolverParams:
    # Config "back-far" (output/benchmark_course18_400_backfar_1_10) :
    # clubhouse_max relevé à 100, rayons de départ étendus, fermeture
    # anticipée dès la profondeur 7 -- posés ici directement (pas via les
    # surcharges de ``solve_course``) pour garder un seul point de vérité.
    return SolverParams(beam_width=72, candidates_per_par=4, transforms_per_candidate=36,
                        departure_angles=tuple(range(0, 360, 30)), start_radii=(44.0, 48.0, 64.0, 80.0, 96.0),
                        start_transforms_per_candidate=144, clubhouse_max=100.0,
                        closing_lookahead_from=7)


def _build_params(experiment: str) -> tuple[SolverParams, SolverParams, ValidationRules]:
    front = _front_base()
    back = _back_base()
    rules_kwargs = dict(width=400.0, height=400.0, shared_rough=True, fairway_gap=5.0, edge_min=1.0,
                        max_parallel_stack=3, clubhouse_clear_radius=10.0)
    if experiment == "departures":
        front = replace(front, random_departures=True, random_departure_count=FRONT_DEPARTURE_COUNT,
                        random_departure_radius=FRONT_DEPARTURE_RADIUS)
        back = replace(back, random_departures=True, random_departure_count=BACK_DEPARTURE_COUNT,
                       random_departure_radius=BACK_DEPARTURE_RADIUS)
        rules = ValidationRules(**rules_kwargs)
    elif experiment == "clubdisk25":
        front = replace(front, start_radii=EXP2_FRONT_START_RADII, clubhouse_max=EXP2_FRONT_CLUBHOUSE_MAX)
        rules = ValidationRules(**rules_kwargs, clubhouse_block_radius=CLUBHOUSE_BLOCK_RADIUS)
    else:
        raise ValueError(experiment)
    return front, back, rules


def _run_seed(experiment: str, seed: int):
    start = time.perf_counter()
    front_params, back_params, rules = _build_params(experiment)
    result = solve_course(seed, front_params, back_params, rules, bounded_quota=True)
    return experiment, result, time.perf_counter() - start


def _seed_summary(experiment: str, result: CourseSolveResult, elapsed: float, rules: ValidationRules) -> dict:
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
        "experiment": experiment,
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
        "back_last_depths": () if result.back is None else _last_depths(result.back.diagnostics),
        "front_clubhouse_max": front_clubhouse_max,
        "back_clubhouse_max": back_clubhouse_max,
        "tee1_distance": tee1,
        "green9_distance": green9,
        "back_start_distance": tee10,
        "back_return_distance": green18,
    }


def _baseline_lookup() -> dict[int, dict]:
    if not BASELINE_REPORT.exists():
        return {}
    data = json.loads(BASELINE_REPORT.read_text(encoding="utf-8"))
    return {item["seed"]: item for item in data["seeds"] if item["seed"] in SEEDS}


def _markdown(experiment: str, summaries: list[dict], rules: ValidationRules, total_seconds: float,
             baseline: dict[int, dict]) -> str:
    title = {
        "departures": "Expérience 1 — départs aléatoires du tee (seeds 1 à 5, 400×400)",
        "clubdisk25": "Expérience 2 — disque d'exclusion clubhouse total 25 blocs (seeds 1 à 5, 400×400)",
    }[experiment]
    success_count = sum(item["success"] for item in summaries)
    independent_valid_count = sum(item["independent_valid"] for item in summaries)
    base_success = sum(1 for seed in SEEDS if baseline.get(seed, {}).get("success"))
    lines = [
        f"# {title}",
        "",
        f"- Succès (18/18) : **{success_count}/5** (baseline back-far seeds 1-5 : **{base_success}/5**)",
        f"- Validation indépendante conforme : **{independent_valid_count}/5**",
        f"- Temps total (10 process, 2 expériences en parallèle) : **{total_seconds:.1f}s**",
        "",
    ]
    if experiment == "departures":
        lines.extend([
            f"- Tirage : front {FRONT_DEPARTURE_COUNT} positions, rayon {FRONT_DEPARTURE_RADIUS}, "
            f"cercle complet ; back {BACK_DEPARTURE_COUNT} positions, rayon {BACK_DEPARTURE_RADIUS}, "
            f"cercle complet. Déterministe par (seed, nine).",
            "",
        ])
    else:
        lines.extend([
            f"- Disque : rayon **{CLUBHOUSE_BLOCK_RADIUS}** autour du clubhouse, empreinte entière "
            "(cœur ET rough) interdite dedans. Conséquences : front start_radii="
            f"{EXP2_FRONT_START_RADII} (défaut (24.0, 36.0)), front clubhouse_max="
            f"{EXP2_FRONT_CLUBHOUSE_MAX} (défaut 50.0), cible profondeur 9 élargie à "
            f"max(cible actuelle, {CLUBHOUSE_BLOCK_RADIUS} + 15) pour les deux nines. "
            "Back inchangé (baseline back-far).",
            "",
        ])
    lines.extend([
        "| Seed | Résultat | Front | Back | Temps | Tee1→club | Green9→club | Tee10→club | "
        "Green18→club | Pile max | Indép. | Base (back-far) |",
        "|---:|:---:|:---:|:---:|---:|---:|---:|---:|---:|---:|:---:|:---:|",
    ])
    for item in summaries:
        base = baseline.get(item["seed"], {})
        base_text = (f"{'OK' if base.get('success') else 'échec'} {base.get('seconds', 0):.1f}s"
                    if base else "—")
        result = "OK" if item["success"] else "échec"
        indep = "OK" if item["independent_valid"] else "KO"
        tee1 = f"{item['tee1_distance']:.1f}" if item["tee1_distance"] is not None else "—"
        green9 = f"{item['green9_distance']:.1f}" if item["green9_distance"] is not None else "—"
        tee10 = f"{item['back_start_distance']:.1f}" if item["back_start_distance"] is not None else "—"
        green18 = f"{item['back_return_distance']:.1f}" if item["back_return_distance"] is not None else "—"
        lines.append(
            f"| {item['seed']} | {result} | {item['front_holes']}/9 | {item['back_holes']}/9 | "
            f"{item['seconds']:.1f}s | {tee1} | {green9} | {tee10} | {green18} | "
            f"{item['largest_parallel_stack']} | {indep} | {base_text} |")

    lines.extend(["", "## Comparaison seed par seed à la baseline back-far", ""])
    for item in summaries:
        base = baseline.get(item["seed"])
        if base is None:
            lines.append(f"- seed {item['seed']} : baseline absente, pas de comparaison.")
            continue
        delta_t = item["seconds"] - base["seconds"]
        same_success = item["success"] == base["success"]
        lines.append(
            f"- seed {item['seed']} : {'OK' if item['success'] else 'échec'} "
            f"({'identique' if same_success else 'DIFFÉRENT'} de la baseline "
            f"{'OK' if base['success'] else 'échec'}), temps {item['seconds']:.1f}s vs "
            f"{base['seconds']:.1f}s (baseline), delta {delta_t:+.1f}s.")

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
    if experiment == "clubdisk25":
        total_disk = sum(item["clubhouse_block_rejections"] for item in summaries)
        lines.append(f"- dont `clubhouse_block` (disque {CLUBHOUSE_BLOCK_RADIUS}) : **{total_disk}** "
                     "rejets cumulés sur les 5 seeds (nouvelle règle)")

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
    baseline = _baseline_lookup()
    jobs = [(experiment, seed) for experiment in EXPERIMENTS for seed in SEEDS]
    total_start = time.perf_counter()
    completed: dict[str, dict[int, tuple[CourseSolveResult, float]]] = {name: {} for name in EXPERIMENTS}
    rules_by_experiment: dict[str, ValidationRules] = {}

    with ProcessPoolExecutor(max_workers=10) as executor:
        futures = {executor.submit(_run_seed, experiment, seed): (experiment, seed) for experiment, seed in jobs}
        for future in as_completed(futures):
            experiment, result, elapsed = future.result()
            completed[experiment][result.seed] = (result, elapsed)
            back_depth = 0 if result.back is None else result.back.state.depth
            print(f"[{experiment}] seed {result.seed}: {'OK' if result.complete else 'échec'} "
                  f"front={result.front.state.depth}/9 back={back_depth}/9 temps={elapsed:.1f}s "
                  f"({sum(len(v) for v in completed.values())}/{len(jobs)} terminés)", flush=True)

    total_seconds = round(time.perf_counter() - total_start, 3)

    for experiment, output_dir in EXPERIMENTS.items():
        _, _, rules = _build_params(experiment)
        rules_by_experiment[experiment] = rules
        output_dir.mkdir(parents=True, exist_ok=True)
        summaries = []
        for seed in sorted(completed[experiment]):
            result, elapsed = completed[experiment][seed]
            summary = _seed_summary(experiment, result, elapsed, rules)
            summaries.append(summary)
            suffix = "course18_400" + ("" if result.complete else "_failed")
            (output_dir / f"seed{seed}_{suffix}.json").write_text(result.to_json(), encoding="utf-8")
            (output_dir / f"seed{seed}_{suffix}.svg").write_text(render_course_svg(result, rules),
                                                                  encoding="utf-8")
        success_count = sum(item["success"] for item in summaries)
        independent_valid_count = sum(item["independent_valid"] for item in summaries)
        report = {
            "experiment": experiment,
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
            "success_count": success_count,
            "independent_valid_count": independent_valid_count,
            "total_seconds_both_experiments": total_seconds,
            "seeds": summaries,
        }
        (output_dir / "report.json").write_text(json.dumps(report, indent=2, sort_keys=True) + "\n",
                                                 encoding="utf-8")
        (output_dir / "REPORT.md").write_text(
            _markdown(experiment, summaries, rules, total_seconds, baseline), encoding="utf-8")
        print(f"{experiment}: {success_count}/5 complet, {independent_valid_count}/5 validé "
              f"indépendamment (baseline back-far seeds 1-5 : "
              f"{sum(1 for s in SEEDS if baseline.get(s, {}).get('success'))}/5)", flush=True)


if __name__ == "__main__":
    main()
