"""Expérience A'' — 2 par5 PAR NINE mais deadline FRONT SEULE (PLAN.md
ligne 6, décision utilisateur), seeds 1 à 5, 400×400.

Contexte : config A (``par5_deadline=7`` symétrique, ``par5_bounds`` par
défaut ``[1, 3]``) donne 5/5 mais le front pose systématiquement le MINIMUM
(1 par5), forçant le back à en poser 3 (ex. seed 5 : back par5 aux trous 7,
8, 9). Config A' (``par5_bounds=(2, 2)`` symétrique + deadline 7 symétrique
+ ``bounded_quota_back=True``, filtre de forçage RÉELLEMENT actif côté back
après le correctif de bug) régresse à 2/5 -- contraindre le BACK à poser ses
2 par5 au plus tard au trou 7 lui retire la flexibilité nécessaire pour
absorber ses propres contraintes de fermeture.

EXP A'' -- seul le FRONT reçoit la deadline, le quota ``(2, 2)`` étant posé
sur les deux nines pour que le partage 2/2 soit respecté globalement (quota
global 4/10/4 inchangé) :
- ``front_params`` : ``par5_bounds=(2, 2)``, ``par5_deadline=7`` (les DEUX
  par5 du front posés au plus tard au trou 7 -- avec ``lo == hi == 2``, la
  fenêtre de ``solver._bounded_quota_filter`` couvre alors la totalité des
  par5 du nine, pas seulement le premier requis, voir
  ``course_solver.py:112-116``) ;
- ``back_params`` : ``par5_bounds=(2, 2)``, ``par5_deadline=None`` (PAS de
  deadline posée sur le back) ;
- ``solve_course(bounded_quota=True, bounded_quota_back=False)`` -- comme la
  config A originale, SEUL le front a ``SolverParams.bounded_quota`` forcé à
  ``True`` (``course_solver.py:306-307``) ; le back ne passe donc jamais par
  ``solver._bounded_quota_filter`` (``solver.py:833-834``, gardée par
  ``params.bounded_quota``), quelle que soit la valeur de
  ``back_params.par5_deadline`` -- il reçoit seulement le quota GLOBAL
  restant après le front (``_global_remaining_from_front``,
  ``course_solver.py:128-134``, 2 par5 si le front en a bien posé 2) et le
  consomme librement, sans contrainte de POSITION.
- ``solve_course`` n'est PAS appelé avec son propre paramètre
  ``par5_deadline=...`` (qui écraserait symétriquement les deux nines,
  ``course_solver.py:296-298``) -- la deadline est posée directement sur
  ``front_params`` via ``dataclasses.replace``, comme dans
  ``run_exp_par5_two_per_nine.py``.

PIÈGE DE LECTURE vérifié en code (ne change rien à cette expérience, mais à
documenter) : la validation indépendante finale de ``solve_course``
(``course_solver.py:325-332``) appelle ``_course_violations`` avec UN SEUL
jeu ``par5_bounds``/``par5_deadline`` -- toujours celui de ``front_params``,
jamais celui de ``back_params`` -- appliqué aux DEUX nines par la boucle
``for label, nine, ... in (("front", ...), ("back", ...))``
(``course_solver.py:93-116``). Résultat : ``back_params.par5_deadline=None``
n'a donc AUCUN effet observable sur ``result.complete`` -- la deadline 7 du
front est, de fait, également vérifiée sur le back au moment du bilan final,
même si (contrairement à A') la RECHERCHE du back n'a jamais été guidée vers
cette contrainte pendant l'expansion (``bounded_quota_back=False``). Cette
expérience teste donc en pratique : « même exigence finale 2 par5 ≤ trou 7
sur les deux nines qu'A', mais recherche du back non guidée » -- un résultat
différent d'A' mesurerait l'effet du GUIDAGE de recherche, pas de la règle
elle-même.

Reste STRICTEMENT identique à la config A (back-far + deadline par5) : front
= ``_front_base()`` (beam 72, départs fixes à 5 angles), back =
``_back_base()`` (candidates_per_par=4, transforms_per_candidate=36, grille
de départs 0-330 par pas de 30°, start_radii (44,48,64,80,96),
clubhouse_max=100, closing_lookahead_from=7) ; règles ``shared_rough=True``,
``fairway_gap=5``, ``edge_min=1``, ``max_parallel_stack=3``,
``clubhouse_clear_radius=10`` ; ``par3_bounds`` INCHANGÉ ``(1, 3)`` ; PAS
d'arrivée radiale, PAS de règle « walkable-links » (expériences
indépendantes, PLAN.md ligne 6).

Exécution : seeds 1 à 5, EN PARALLÈLE (5 process), foreground, une ligne de
log par seed terminé (``flush=True``).
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
from experiments.bean_paving.solver import SolverParams, _arrival_angle_deg

SEEDS = range(1, 6)
# Comparaison : config A (deadline par5 seule, par5_bounds par défaut [1,3])
# et config A' (deadline par5 + bounds (2,2) symétriques sur les deux nines).
CONFIG_A_REPORT = Path("experiments/bean_paving/output/exp_par5deadline_400_1_5/report.json")
CONFIG_A_PRIME_REPORT = Path("experiments/bean_paving/output/exp_par5_two_per_nine_400_1_5/report.json")
OUTPUT_DIR = Path("experiments/bean_paving/output/exp_a2_par5_split_400_1_5")

PAR5_DEADLINE = 7
PAR5_BOUNDS = (2, 2)


def _front_base() -> SolverParams:
    # Baseline back-far : front inchangé.
    return SolverParams(beam_width=72, departure_angles=(300, 330, 0, 30, 60),
                        target_radius_scale=0.9, bbox_weight=0.0004)


def _back_base() -> SolverParams:
    # Config "back-far" (output/benchmark_course18_400_backfar_1_10) :
    # clubhouse_max relevé à 100, rayons de départ étendus, fermeture
    # anticipée dès la profondeur 7 -- posés ici directement (pas via les
    # surcharges de ``solve_course``) pour garder un seul point de vérité,
    # même motif que ``run_exp_par5deadline_and_radialarrival.py``.
    return SolverParams(beam_width=72, candidates_per_par=4, transforms_per_candidate=36,
                        departure_angles=tuple(range(0, 360, 30)), start_radii=(44.0, 48.0, 64.0, 80.0, 96.0),
                        start_transforms_per_candidate=144, clubhouse_max=100.0,
                        closing_lookahead_from=7)


def _rules() -> ValidationRules:
    return ValidationRules(width=400.0, height=400.0, shared_rough=True, fairway_gap=5.0, edge_min=1.0,
                           max_parallel_stack=3, clubhouse_clear_radius=10.0)


def _build_params() -> tuple[SolverParams, SolverParams, ValidationRules]:
    # Deadline posée UNIQUEMENT sur le front -- le back garde
    # par5_deadline=None (défaut de SolverParams), voir le piège de lecture
    # documenté en tête de module (sans effet sur result.complete, mais sans
    # effet non plus sur le GUIDAGE de la recherche du back, contrairement à
    # A' où bounded_quota_back=True force aussi back_params.bounded_quota).
    front = replace(_front_base(), par5_deadline=PAR5_DEADLINE, par5_bounds=PAR5_BOUNDS)
    back = replace(_back_base(), par5_bounds=PAR5_BOUNDS)
    return front, back, _rules()


def _run_seed(seed: int):
    start = time.perf_counter()
    front_params, back_params, rules = _build_params()
    result = solve_course(seed, front_params, back_params, rules, bounded_quota=True,
                          bounded_quota_back=False)
    return result, time.perf_counter() - start


def _seed_summary(result: CourseSolveResult, elapsed: float, rules: ValidationRules) -> dict:
    front_placed = result.front.state.placed
    back_placed = () if result.back is None else result.back.state.placed
    all_placed = front_placed + back_placed
    clubhouse = rules.clubhouse
    front_clubhouse_max = result.front.params.clubhouse_max
    back_clubhouse_max = (SolverParams().clubhouse_max if result.back is None
                          else result.back.params.clubhouse_max)
    par3_bounds = result.front.params.par3_bounds
    par5_bounds = result.front.params.par5_bounds
    independent_violations = _course_violations(
        front_placed, back_placed, rules, clubhouse, front_clubhouse_max, back_clubhouse_max,
        par3_bounds=par3_bounds, par5_bounds=par5_bounds, par5_deadline=PAR5_DEADLINE,
    )
    independent_valid = (len(front_placed) == 9 and len(back_placed) == 9 and not independent_violations)

    tee1 = round(math.dist(front_placed[0].tee, clubhouse), 3) if front_placed else None
    green9 = round(math.dist(front_placed[-1].green, clubhouse), 3) if front_placed else None
    tee10 = round(math.dist(back_placed[0].tee, clubhouse), 3) if back_placed else None
    green18 = round(math.dist(back_placed[-1].green, clubhouse), 3) if back_placed else None

    front_angle = round(_arrival_angle_deg(front_placed[-1], clubhouse), 3) if front_placed else None
    back_angle = round(_arrival_angle_deg(back_placed[-1], clubhouse), 3) if back_placed else None
    front_par5_holes = [i + 1 for i, bean in enumerate(front_placed) if bean.template.par == 5]
    back_par5_holes = [i + 1 for i, bean in enumerate(back_placed) if bean.template.par == 5]

    footprint_ratio = (sum(_polygon_area(bean.footprint) for bean in all_placed)
                       / (rules.width * rules.height)) if all_placed else 0.0

    rejection_counts: Counter = Counter()
    for nine in (result.front, result.back):
        if nine is None:
            continue
        for depth in nine.diagnostics:
            rejection_counts.update(depth.rejection_counts)

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
        "front_par5_holes": front_par5_holes,
        "back_par5_holes": back_par5_holes,
        "front_arrival_angle_deg": front_angle,
        "back_arrival_angle_deg": back_angle,
        "footprint_ratio": round(footprint_ratio, 4),
        "largest_parallel_stack": _largest_parallel_stack(all_placed, rules),
        "rejection_counts": dict(sorted(rejection_counts.items())),
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
    return {item["seed"]: item for item in data["seeds"] if item["seed"] in SEEDS}


def _markdown(summaries: list[dict], rules: ValidationRules, total_seconds: float,
             config_a: dict[int, dict], config_a_prime: dict[int, dict]) -> str:
    success_count = sum(item["success"] for item in summaries)
    independent_valid_count = sum(item["independent_valid"] for item in summaries)
    a_success = sum(1 for seed in SEEDS if config_a.get(seed, {}).get("success"))
    a_prime_success = sum(1 for seed in SEEDS if config_a_prime.get(seed, {}).get("success"))
    lines = [
        "# Expérience A'' — 2 par5 par nine, deadline trou 7 FRONT SEULE (seeds 1 à 5, 400×400)",
        "",
        f"- Succès (18/18) : **{success_count}/5** (config A -- deadline symétrique, par5 [1,3] -- "
        f"seeds 1-5 : **{a_success}/5** ; config A' -- deadline + bounds (2,2) symétriques -- "
        f"seeds 1-5 : **{a_prime_success}/5**)",
        f"- Validation indépendante conforme : **{independent_valid_count}/5**",
        f"- Temps total (5 process) : **{total_seconds:.1f}s**",
        "",
        "- Changement vs A' : ``par5_deadline=7`` posé UNIQUEMENT sur ``front_params`` "
        "(``back_params.par5_deadline=None``) et ``solve_course(bounded_quota_back=False)`` -- "
        "le back ne passe plus par ``solver._bounded_quota_filter`` (comme la config A d'origine), "
        "``par5_bounds=(2, 2)`` reste posé sur les DEUX nines pour que le partage global 2+2=4 "
        "soit respecté. ``par3_bounds`` ``(1, 3)`` et le quota global 4/10/4 inchangés.",
        "",
        "- RAPPEL (voir docstring du module) : la validation finale de ``solve_course`` "
        "(``course_solver.py:325-332``) réutilise TOUJOURS ``front_params.par5_bounds``/"
        "``par5_deadline`` pour contrôler le BACK aussi -- ``back_params.par5_deadline=None`` est "
        "donc sans effet sur ``result.complete`` ; seule la RECHERCHE du back (non guidée ici, "
        "contrairement à A') peut différer.",
        "",
        "| Seed | Résultat | Front | Back | Temps | Tee1→club | Green9→club | Tee10→club | "
        "Green18→club | Par trou 9 | Par trou 18 | Indép. | Config A | Config A' |",
        "|---:|:---:|:---:|:---:|---:|---:|---:|---:|---:|---:|---:|:---:|:---:|:---:|",
    ]
    for item in summaries:
        a = config_a.get(item["seed"], {})
        a_prime = config_a_prime.get(item["seed"], {})
        a_text = f"{'OK' if a.get('success') else 'échec'} {a.get('seconds', 0):.1f}s" if a else "—"
        a_prime_text = (f"{'OK' if a_prime.get('success') else 'échec'} {a_prime.get('seconds', 0):.1f}s"
                        if a_prime else "—")
        result = "OK" if item["success"] else "échec"
        indep = "OK" if item["independent_valid"] else "KO"
        tee1 = f"{item['tee1_distance']:.1f}" if item["tee1_distance"] is not None else "—"
        green9 = f"{item['green9_distance']:.1f}" if item["green9_distance"] is not None else "—"
        tee10 = f"{item['back_start_distance']:.1f}" if item["back_start_distance"] is not None else "—"
        green18 = f"{item['back_return_distance']:.1f}" if item["back_return_distance"] is not None else "—"
        par9 = item["front_pars"][-1] if item["front_pars"] else "—"
        par18 = item["back_pars"][-1] if item["back_pars"] else "—"
        lines.append(
            f"| {item['seed']} | {result} | {item['front_holes']}/9 | {item['back_holes']}/9 | "
            f"{item['seconds']:.1f}s | {tee1} | {green9} | {tee10} | {green18} | {par9} | {par18} | "
            f"{indep} | {a_text} | {a_prime_text} |")

    lines.extend(["", "## Comparaison seed par seed à A et A'", ""])
    for item in summaries:
        a = config_a.get(item["seed"])
        a_prime = config_a_prime.get(item["seed"])
        a_text = (f"{'OK' if a['success'] else 'échec'}, par5 front {a.get('front_par5_holes', '—')} "
                  f"/ back {a.get('back_par5_holes', '—')}" if a else "absente")
        a_prime_text = (f"{'OK' if a_prime['success'] else 'échec'}, par5 front "
                        f"{a_prime.get('front_par5_holes', '—')} / back {a_prime.get('back_par5_holes', '—')}"
                        if a_prime else "absente")
        lines.append(
            f"- seed {item['seed']} : A'' {'OK' if item['success'] else 'échec'}, par5 front "
            f"{item['front_par5_holes'] or '—'} / back {item['back_par5_holes'] or '—'} -- "
            f"A : {a_text} -- A' : {a_prime_text}")

    lines.extend(["", "## Pars par nine (ordre de jeu) -- trous 9 et 18 en gras", ""])
    for item in summaries:
        front_pars = item["front_pars"]
        back_pars = item["back_pars"]
        front = "-".join(f"**{p}**" if i == len(front_pars) - 1 else str(p)
                         for i, p in enumerate(front_pars)) or "—"
        back = "-".join(f"**{p}**" if i == len(back_pars) - 1 else str(p)
                        for i, p in enumerate(back_pars)) or "—"
        lines.append(f"- seed {item['seed']} : front {front} / back {back}")

    lines.extend(["", "## Par5 — trous de pose (play order, 1-indexé)", ""])
    for item in summaries:
        front_holes = item["front_par5_holes"] or "—"
        back_holes = item["back_par5_holes"] or "—"
        lines.append(f"- seed {item['seed']} : front par5 aux trous {front_holes} / "
                     f"back par5 aux trous {back_holes}")

    lines.extend(["", "## Rejets cumulés", ""])
    all_rejections: Counter = Counter()
    for item in summaries:
        all_rejections.update(item["rejection_counts"])
    for kind, count in sorted(all_rejections.items()):
        lines.append(f"- `{kind}` : {count}")

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
    config_a = _report_lookup(CONFIG_A_REPORT)
    config_a_prime = _report_lookup(CONFIG_A_PRIME_REPORT)
    total_start = time.perf_counter()
    completed: dict[int, tuple[CourseSolveResult, float]] = {}

    with ProcessPoolExecutor(max_workers=5) as executor:
        futures = {executor.submit(_run_seed, seed): seed for seed in SEEDS}
        for future in as_completed(futures):
            result, elapsed = future.result()
            completed[result.seed] = (result, elapsed)
            back_depth = 0 if result.back is None else result.back.state.depth
            print(f"seed {result.seed}: {'OK' if result.complete else 'échec'} "
                  f"front={result.front.state.depth}/9 back={back_depth}/9 temps={elapsed:.1f}s "
                  f"({len(completed)}/{len(SEEDS)} terminés)", flush=True)

    total_seconds = round(time.perf_counter() - total_start, 3)

    _, _, rules = _build_params()
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    summaries = []
    for seed in sorted(completed):
        result, elapsed = completed[seed]
        summary = _seed_summary(result, elapsed, rules)
        summaries.append(summary)
        suffix = "course18_400" + ("" if result.complete else "_failed")
        (OUTPUT_DIR / f"seed{seed}_{suffix}.json").write_text(result.to_json(), encoding="utf-8")
        (OUTPUT_DIR / f"seed{seed}_{suffix}.svg").write_text(render_course_svg(result, rules),
                                                              encoding="utf-8")
    success_count = sum(item["success"] for item in summaries)
    independent_valid_count = sum(item["independent_valid"] for item in summaries)
    report = {
        "experiment": "a2_par5_split",
        "size": 400,
        "seeds_requested": list(SEEDS),
        "rules": {
            "shared_rough": rules.shared_rough,
            "fairway_gap": rules.fairway_gap,
            "edge_min": rules.edge_min,
            "max_parallel_stack": rules.max_parallel_stack,
            "clubhouse_clear_radius": rules.clubhouse_clear_radius,
        },
        "front_par5_deadline": PAR5_DEADLINE,
        "back_par5_deadline": None,
        "par5_bounds": list(PAR5_BOUNDS),
        "success_count": success_count,
        "independent_valid_count": independent_valid_count,
        "total_seconds": total_seconds,
        "seeds": summaries,
    }
    (OUTPUT_DIR / "report.json").write_text(json.dumps(report, indent=2, sort_keys=True) + "\n",
                                             encoding="utf-8")
    (OUTPUT_DIR / "REPORT.md").write_text(
        _markdown(summaries, rules, total_seconds, config_a, config_a_prime), encoding="utf-8")
    print(f"a2_par5_split: {success_count}/5 complet, {independent_valid_count}/5 validé "
          f"indépendamment (config A seeds 1-5 : "
          f"{sum(1 for s in SEEDS if config_a.get(s, {}).get('success'))}/5, "
          f"config A' : {sum(1 for s in SEEDS if config_a_prime.get(s, {}).get('success'))}/5)", flush=True)


if __name__ == "__main__":
    main()
