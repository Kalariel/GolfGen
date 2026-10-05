"""Expérience « liens praticables » (PLAN.md ligne 6, décision utilisateur),
seeds 1 à 5, 400×400, base = config A de l'expérience deadline par5
(``output/exp_par5deadline_400_1_5``, ``par5_deadline=7`` sur les deux nines,
back-far : ``closing_lookahead_from=7``, ``clubhouse_max=100``,
``start_radii=(44, 48, 64, 80, 96)``) EXACTEMENT, plus deux changements :

1. Liens praticables (``geometry.ValidationRules.walkable_links=True``) :
   chaque liaison piétonne (segment droit clubhouse<->tee1, green_k->tee_{k+1}
   du même nine, green9->clubhouse, clubhouse->tee10, green18->clubhouse --
   9->10 exclue, le joueur repasse par le clubhouse) ne doit NI croiser NI
   toucher le cœur (fairway) d'AUCUN AUTRE trou que les deux qui la portent ;
   le rough reste traversable. Observation utilisateur sur les SVG de la
   deadline par5 : sur chaque seed, la marche du clubhouse au trou 1 ou 10
   traverse le fairway d'un AUTRE trou (seed 1 : 17+18, seed 2 : 18, seed 3 :
   9, seed 4 : 17+18, seed 5 : 18) -- des trous tardifs du retour se glissent
   entre le clubhouse et les départs précoces.

2. Longueur des liaisons green->tee next élargie de 12-45 à 12-80 blocs
   (``ValidationRules.link_max=80.0``) ; ``SolverParams.link_lengths`` étendu
   en conséquence pour que le solveur génère réellement des candidats de tee
   jusqu'à 80 (24, 32, 40 -- historique -- plus 55, 65, 80, un pas d'environ
   12-13 blocs entre valeurs successives, cohérent avec le pas existant
   24->32->40, sans explosion combinatoire : 3 rayons de liaison
   supplémentaires x 12 angles bruts avant troncature par
   ``transforms_per_candidate``, qui borne déjà le coût réel).

Les deux changements sont opt-in (``ValidationRules.walkable_links=False``
et ``SolverParams.link_lengths=(24, 32, 40)`` par défaut) : aucun appelant
existant n'est affecté.
"""

from __future__ import annotations

from collections import Counter
from concurrent.futures import ProcessPoolExecutor, as_completed
import json
import math
from pathlib import Path
import time

from experiments.bean_paving.benchmark_course import _largest_parallel_stack, _last_depths, _polygon_area
from experiments.bean_paving.course_solver import CourseSolveResult, _course_violations, solve_course
from experiments.bean_paving.geometry import ValidationRules
from experiments.bean_paving.render_course import render_course_svg
from experiments.bean_paving.solver import SolverParams

SEEDS = range(1, 6)
BASELINE_REPORT = Path("experiments/bean_paving/output/exp_par5deadline_400_1_5/report.json")
OUTPUT_DIR = Path("experiments/bean_paving/output/exp_walkable_links_400_1_5")

PAR5_DEADLINE = 7
LINK_MAX = 80.0
# Pas de ~12-13 blocs entre valeurs successives, cohérent avec le pas
# historique (24->32->40) ; 80 = la nouvelle borne haute exacte.
LINK_LENGTHS = (24.0, 32.0, 40.0, 55.0, 65.0, 80.0)


def _front_params() -> SolverParams:
    # Baseline par5-deadline (config A) : front inchangé hormis
    # ``par5_deadline`` (déjà dans la config A) et ``link_lengths`` (ce run).
    return SolverParams(beam_width=72, departure_angles=(300, 330, 0, 30, 60),
                        target_radius_scale=0.9, bbox_weight=0.0004,
                        par5_deadline=PAR5_DEADLINE, link_lengths=LINK_LENGTHS)


def _back_params() -> SolverParams:
    # Config "back-far" + deadline par5 (config A) + ``link_lengths`` élargi.
    return SolverParams(beam_width=72, candidates_per_par=4, transforms_per_candidate=36,
                        departure_angles=tuple(range(0, 360, 30)),
                        start_radii=(44.0, 48.0, 64.0, 80.0, 96.0),
                        start_transforms_per_candidate=144, clubhouse_max=100.0,
                        closing_lookahead_from=7, par5_deadline=PAR5_DEADLINE,
                        link_lengths=LINK_LENGTHS)


def _rules() -> ValidationRules:
    return ValidationRules(width=400.0, height=400.0, shared_rough=True, fairway_gap=5.0, edge_min=1.0,
                           max_parallel_stack=3, clubhouse_clear_radius=10.0,
                           link_max=LINK_MAX, walkable_links=True)


def _run_seed(seed: int):
    start = time.perf_counter()
    front_params, back_params, rules = _front_params(), _back_params(), _rules()
    result = solve_course(seed, front_params, back_params, rules, bounded_quota=True)
    return result, time.perf_counter() - start


def _link_lengths_used(front_placed, back_placed) -> list[float]:
    """Longueurs des liaisons green_k->tee_{k+1} RÉELLEMENT posées (chaque
    nine séparément, jamais la liaison clubhouse) -- ce que
    ``SolverParams.link_lengths``/``ValidationRules.link_max`` gouvernent."""
    lengths = []
    for nine in (front_placed, back_placed):
        lengths.extend(math.dist(previous.green, current.tee) for previous, current in zip(nine, nine[1:]))
    return lengths


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
        par3_bounds=par3_bounds, par5_bounds=par5_bounds,
    )
    independent_valid = (len(front_placed) == 9 and len(back_placed) == 9 and not independent_violations)

    tee1 = round(math.dist(front_placed[0].tee, clubhouse), 3) if front_placed else None
    green9 = round(math.dist(front_placed[-1].green, clubhouse), 3) if front_placed else None
    tee10 = round(math.dist(back_placed[0].tee, clubhouse), 3) if back_placed else None
    green18 = round(math.dist(back_placed[-1].green, clubhouse), 3) if back_placed else None

    front_par5_holes = [i + 1 for i, bean in enumerate(front_placed) if bean.template.par == 5]
    back_par5_holes = [i + 1 for i, bean in enumerate(back_placed) if bean.template.par == 5]

    link_lengths = _link_lengths_used(front_placed, back_placed)
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
        "footprint_ratio": round(footprint_ratio, 4),
        "largest_parallel_stack": _largest_parallel_stack(all_placed, rules),
        "rejection_counts": dict(sorted(rejection_counts.items())),
        "link_blocked_count": rejection_counts.get("link_blocked", 0),
        "link_lengths_max": round(max(link_lengths), 3) if link_lengths else None,
        "link_lengths_mean": round(sum(link_lengths) / len(link_lengths), 3) if link_lengths else None,
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


def _markdown(summaries: list[dict], total_seconds: float, baseline: dict[int, dict]) -> str:
    success_count = sum(item["success"] for item in summaries)
    independent_valid_count = sum(item["independent_valid"] for item in summaries)
    base_success = sum(1 for seed in SEEDS if baseline.get(seed, {}).get("success"))
    lines = [
        "# Expérience — liens praticables (seeds 1 à 5, 400×400)",
        "",
        f"- Succès (18/18) : **{success_count}/5** (baseline deadline par5 seeds 1-5 : **{base_success}/5**)",
        f"- Validation indépendante conforme : **{independent_valid_count}/5**",
        f"- Temps total (5 process en parallèle) : **{total_seconds:.1f}s**",
        "",
        "- Règle : chaque liaison piétonne (clubhouse<->tee1, green_k->tee_{k+1}, "
        "green9->clubhouse, clubhouse->tee10, green_k->tee_{k+1} (k=10..17), "
        "green18->clubhouse) ne doit ni croiser ni toucher le cœur fairway d'un "
        "AUTRE trou (rough autorisé). Longueur green->tee élargie de [12, 45] à "
        f"[12, {LINK_MAX:.0f}] blocs. Reste = config A (deadline par5, trou 7 max).",
        "",
        "| Seed | Résultat | Front | Back | Temps | Tee1→club | Green9→club | Tee10→club | "
        "Green18→club | Liaison max | Liaison moy. | link_blocked | Indép. | Base (par5-deadline) |",
        "|---:|:---:|:---:|:---:|---:|---:|---:|---:|---:|---:|---:|---:|:---:|:---:|",
    ]
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
        link_max = f"{item['link_lengths_max']:.1f}" if item["link_lengths_max"] is not None else "—"
        link_mean = f"{item['link_lengths_mean']:.1f}" if item["link_lengths_mean"] is not None else "—"
        lines.append(
            f"| {item['seed']} | {result} | {item['front_holes']}/9 | {item['back_holes']}/9 | "
            f"{item['seconds']:.1f}s | {tee1} | {green9} | {tee10} | {green18} | {link_max} | "
            f"{link_mean} | {item['link_blocked_count']} | {indep} | {base_text} |")

    lines.extend(["", "## Comparaison seed par seed à la baseline deadline par5 (5/5)", ""])
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
    baseline = _baseline_lookup()
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
    rules = _rules()
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
        "experiment": "walkable_links",
        "size": 400,
        "seeds_requested": list(SEEDS),
        "rules": {
            "shared_rough": rules.shared_rough,
            "fairway_gap": rules.fairway_gap,
            "edge_min": rules.edge_min,
            "max_parallel_stack": rules.max_parallel_stack,
            "clubhouse_clear_radius": rules.clubhouse_clear_radius,
            "link_max": rules.link_max,
            "walkable_links": rules.walkable_links,
        },
        "par5_deadline": PAR5_DEADLINE,
        "link_lengths": list(LINK_LENGTHS),
        "success_count": success_count,
        "independent_valid_count": independent_valid_count,
        "total_seconds": total_seconds,
        "seeds": summaries,
    }
    (OUTPUT_DIR / "report.json").write_text(json.dumps(report, indent=2, sort_keys=True) + "\n",
                                             encoding="utf-8")
    (OUTPUT_DIR / "REPORT.md").write_text(_markdown(summaries, total_seconds, baseline), encoding="utf-8")
    print(f"walkable_links: {success_count}/5 complet, {independent_valid_count}/5 validé "
          f"indépendamment (baseline deadline par5 seeds 1-5 : "
          f"{sum(1 for s in SEEDS if baseline.get(s, {}).get('success'))}/5)", flush=True)


if __name__ == "__main__":
    main()
