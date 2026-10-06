"""Expérience A''' — back GUIDÉ vers 2 par5 exacts, SANS deadline back
(PLAN.md ligne 6, décision utilisateur), seeds 1 à 5, 400×400.

Contexte (``output/exp_a2_par5_split_fixed_400_1_5/REPORT.md``, config A'' :
``bounded_quota_back=False``, deadline ``par5_deadline=7`` posée uniquement
sur le front, ``par5_bounds=(2, 2)`` sur les deux nines) : **2/5** -- les
seeds 2, 3 ferment 18/18 (back par5 aux trous [4, 8] sur les deux, trou 8
légitime puisque le back n'a aucune deadline) ; les seeds 1, 4, 5 échouent
AVANT même d'atteindre une violation de quota, bloquées en cours de
recherche (``back_return``, back 7-8/9) -- la recherche du back n'étant PAS
guidée vers son quota ``(2, 2)`` (``bounded_quota_back=False``), elle peut
épuiser ou mal répartir ses par5 sans jamais être corrigée en cours de route,
contrairement au front qui, lui, est guidé.

EXP A''' -- UN SEUL changement par rapport à A'' : ``bounded_quota_back=True``
(le back est maintenant guidé EN COURS DE RECHERCHE vers exactement 2 par5,
via ``solver._bounded_quota_filter``, comme le front) mais garde
``back_params.par5_deadline=None`` (AUCUNE deadline de position sur le
back, contrairement à A' où le back avait aussi ``par5_deadline=7``) :
- ``front_params`` : ``par5_bounds=(2, 2)``, ``par5_deadline=7`` (inchangé) ;
- ``back_params`` : ``par5_bounds=(2, 2)``, ``par5_deadline=None`` (inchangé,
  ``_build_params`` de A'' ne pose jamais de deadline sur le back) ;
- ``solve_course(bounded_quota=True, bounded_quota_back=True)`` -- SEUL ce
  dernier argument diffère de A'' (``course_solver.py:325-332`` force alors
  aussi ``back_params.bounded_quota=True``, donc ``solver._bounded_quota_filter``
  s'exerce bien côté back, guidant chaque pas vers le quota exact ``(2, 2)``
  sans jamais imposer de fenêtre de position -- voir ``solver.py:833-834`` et
  ``course_solver.py`` docstring de ``bounded_quota_back``).

Réutilise STRICTEMENT le code de A'' (``run_exp_a2_par5_split``) : bases
front/back, règles, ``_build_params`` (déjà ``par5_bounds=(2, 2)`` symétrique
+ deadline front seule) et ``_seed_summary`` (déjà gated par nine sur
``bounded_quota``/``par5_deadline`` propres à chacun, donc directement
valable ici sans changement -- le ``back_bq_params.bounded_quota`` y est lu
dynamiquement depuis ``result.back.params``, qui refléte bien le forçage de
``bounded_quota_back``). Seuls ``_run_seed`` (nouvel argument
``bounded_quota_back=True``), le chemin de sortie et le rapport Markdown
(comparaison à trois configurations : A, A', A'' corrigée) sont propres à
ce script.

Exécution : seeds 1 à 5, EN PARALLÈLE (5 process), foreground, une ligne de
log par seed terminé (``flush=True``).
"""

from __future__ import annotations

from collections import Counter
from concurrent.futures import ProcessPoolExecutor, as_completed
import json
from pathlib import Path
import time

from experiments.bean_paving.course_solver import CourseSolveResult, solve_course
from experiments.bean_paving.geometry import ValidationRules
from experiments.bean_paving.render_course import render_course_svg
from experiments.bean_paving.run_exp_a2_par5_split import (
    PAR5_BOUNDS,
    PAR5_DEADLINE,
    _build_params,
    _report_lookup,
    _seed_summary,
)

SEEDS = range(1, 6)
# Comparaison : config A (deadline symétrique, par5 [1,3]), A' (deadline +
# bounds (2,2) symétriques, back guidé ET contraint en position) et A''
# corrigée (bounds (2,2), deadline front seule, back NON guidé).
CONFIG_A_REPORT = Path("experiments/bean_paving/output/exp_par5deadline_400_1_5/report.json")
CONFIG_A_PRIME_REPORT = Path("experiments/bean_paving/output/exp_par5_two_per_nine_400_1_5/report.json")
CONFIG_A_DOUBLE_PRIME_REPORT = Path(
    "experiments/bean_paving/output/exp_a2_par5_split_fixed_400_1_5/report.json")
OUTPUT_DIR = Path("experiments/bean_paving/output/exp_a3_back_guided_400_1_5")


def _run_seed(seed: int):
    start = time.perf_counter()
    front_params, back_params, rules = _build_params()
    # Seul changement par rapport à A'' : le back est désormais guidé vers
    # son quota (2, 2) pendant la recherche, sans deadline de position.
    result = solve_course(seed, front_params, back_params, rules, bounded_quota=True,
                          bounded_quota_back=True)
    return result, time.perf_counter() - start


def _markdown(summaries: list[dict], total_seconds: float, config_a: dict[int, dict],
             config_a_prime: dict[int, dict], config_a_double_prime: dict[int, dict]) -> str:
    success_count = sum(item["success"] for item in summaries)
    independent_valid_count = sum(item["independent_valid"] for item in summaries)
    a_success = sum(1 for seed in SEEDS if config_a.get(seed, {}).get("success"))
    a_prime_success = sum(1 for seed in SEEDS if config_a_prime.get(seed, {}).get("success"))
    a_double_prime_success = sum(1 for seed in SEEDS if config_a_double_prime.get(seed, {}).get("success"))
    lines = [
        "# Expérience A''' — back guidé (2 par5 exacts), sans deadline back (seeds 1 à 5, 400×400)",
        "",
        f"- Succès (18/18) : **{success_count}/5** (config A : **{a_success}/5** ; "
        f"config A' : **{a_prime_success}/5** ; config A'' corrigée : **{a_double_prime_success}/5**)",
        f"- Validation indépendante conforme : **{independent_valid_count}/5**",
        f"- Temps total (5 process) : **{total_seconds:.1f}s**",
        "",
        "- Changement vs A'' : ``solve_course(bounded_quota_back=True)`` (au lieu de ``False``) -- "
        "le back est désormais GUIDÉ en cours de recherche vers exactement 2 par5 "
        "(``solver._bounded_quota_filter``), mais garde ``back_params.par5_deadline=None`` "
        "(AUCUNE fenêtre de position imposée, contrairement à A' où le back avait aussi "
        "``par5_deadline=7``). ``front_params`` inchangé (bounds (2,2) + deadline trou 7).",
        "",
        "| Seed | Résultat | Front | Back | Temps | Par trou 9 | Par trou 18 | Indép. | "
        "Config A | Config A' | Config A'' |",
        "|---:|:---:|:---:|:---:|---:|---:|---:|:---:|:---:|:---:|:---:|",
    ]
    for item in summaries:
        a = config_a.get(item["seed"], {})
        a_prime = config_a_prime.get(item["seed"], {})
        a_double_prime = config_a_double_prime.get(item["seed"], {})
        a_text = f"{'OK' if a.get('success') else 'échec'} {a.get('seconds', 0):.1f}s" if a else "—"
        a_prime_text = (f"{'OK' if a_prime.get('success') else 'échec'} {a_prime.get('seconds', 0):.1f}s"
                        if a_prime else "—")
        a_double_prime_text = (
            f"{'OK' if a_double_prime.get('success') else 'échec'} {a_double_prime.get('seconds', 0):.1f}s"
            if a_double_prime else "—")
        result = "OK" if item["success"] else "échec"
        indep = "OK" if item["independent_valid"] else "KO"
        par9 = item["front_pars"][-1] if item["front_pars"] else "—"
        par18 = item["back_pars"][-1] if item["back_pars"] else "—"
        lines.append(
            f"| {item['seed']} | {result} | {item['front_holes']}/9 | {item['back_holes']}/9 | "
            f"{item['seconds']:.1f}s | {par9} | {par18} | {indep} | {a_text} | {a_prime_text} | "
            f"{a_double_prime_text} |")

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

    lines.extend(["", "## Comparaison seed par seed à A, A' et A''", ""])
    for item in summaries:
        a = config_a.get(item["seed"])
        a_prime = config_a_prime.get(item["seed"])
        a_double_prime = config_a_double_prime.get(item["seed"])
        a_text = (f"{'OK' if a['success'] else 'échec'}, back {a.get('back_par5_holes', '—')}"
                  if a else "absente")
        a_prime_text = (f"{'OK' if a_prime['success'] else 'échec'}, back {a_prime.get('back_par5_holes', '—')}"
                        if a_prime else "absente")
        a_double_prime_text = (
            f"{'OK' if a_double_prime['success'] else 'échec'}, "
            f"back {a_double_prime.get('back_par5_holes', '—')}" if a_double_prime else "absente")
        lines.append(
            f"- seed {item['seed']} : A''' {'OK' if item['success'] else 'échec'}, back par5 "
            f"{item['back_par5_holes'] or '—'} -- A : {a_text} -- A' : {a_prime_text} -- "
            f"A'' : {a_double_prime_text}")

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
    config_a_double_prime = _report_lookup(CONFIG_A_DOUBLE_PRIME_REPORT)
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
        "experiment": "a3_back_guided",
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
        "bounded_quota_back": True,
        "success_count": success_count,
        "independent_valid_count": independent_valid_count,
        "total_seconds": total_seconds,
        "seeds": summaries,
    }
    (OUTPUT_DIR / "report.json").write_text(json.dumps(report, indent=2, sort_keys=True) + "\n",
                                             encoding="utf-8")
    (OUTPUT_DIR / "REPORT.md").write_text(
        _markdown(summaries, total_seconds, config_a, config_a_prime, config_a_double_prime),
        encoding="utf-8")
    print(f"a3_back_guided: {success_count}/5 complet, {independent_valid_count}/5 validé "
          f"indépendamment (config A : "
          f"{sum(1 for s in SEEDS if config_a.get(s, {}).get('success'))}/5, "
          f"config A' : {sum(1 for s in SEEDS if config_a_prime.get(s, {}).get('success'))}/5, "
          f"config A'' : "
          f"{sum(1 for s in SEEDS if config_a_double_prime.get(s, {}).get('success'))}/5)", flush=True)


if __name__ == "__main__":
    main()
