"""Benchmark reproductible des seeds 1 à 10 du parcours 18 trous
(``course_solver.solve_course``), paramétré par taille de carte et règles.

Mirroré sur ``benchmark.py`` (le benchmark du nine) mais pour deux nines
coordonnés : complétude front/back, validation indépendante des 18 trous
(mêmes appels que ``course_solver._course_violations``), pile côte-à-côte la
plus grande et occupation de la carte complète. Ne modifie pas
``benchmark.py`` ni son comportement.
"""

from __future__ import annotations

import argparse
from collections import Counter
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import replace
import json
import math
from pathlib import Path
import time

from experiments.bean_paving.benchmark import _angle_bin, _similarity
from experiments.bean_paving.course_solver import CourseSolveResult, _course_violations, solve_course
from experiments.bean_paving.geometry import PlacedBean, ValidationRules, validate
from experiments.bean_paving.render_course import render_course_svg
from experiments.bean_paving.solver import SolverParams, _arrival_angle_deg, _radius_group_index


def _polygon_area(points) -> float:
    return abs(sum(a[0] * b[1] - b[0] * a[1]
                   for a, b in zip(points, (*points[1:], points[0]))) / 2.0)


def _fingerprint_beans(beans: tuple[PlacedBean, ...]) -> tuple:
    """Même signature que ``benchmark._fingerprint``, mais sur une liste de
    trous déjà posés (ici les 18 trous front+back) plutôt que sur un
    ``SolveResult`` de nine isolé."""
    if not beans:
        return ()
    raw_angles = [_angle_bin(bean.tee, bean.green) for bean in beans]
    origin = raw_angles[0]
    relative = tuple((value - origin) % 12 for value in raw_angles)
    mirrored = tuple((-value) % 12 for value in relative)
    angles = min(relative, mirrored)
    lengths = tuple(round(math.dist(bean.tee, bean.green) / 10.0) for bean in beans)
    pars = tuple(bean.template.par for bean in beans)
    links = tuple(round(math.dist(a.green, b.tee) / 8.0) for a, b in zip(beans, beans[1:]))
    return pars, angles, lengths, links


def _largest_parallel_stack(beans: tuple[PlacedBean, ...], rules: ValidationRules) -> int | None:
    """Taille de la plus grande composante connexe de la relation côte-à-côte
    (``parallel_stack``), recalculée sans filtrage par seuil — même méthode
    que EXPERIMENT_18_ROUGH.md, section « Essai 400×400 » : on ne réutilise
    que l'oracle public ``validate`` (pas les fonctions privées de
    ``geometry.py``), en balayant ``max_parallel_stack`` jusqu'à ce qu'aucune
    violation ``parallel_stack`` ne subsiste."""
    if not rules.shared_rough or len(beans) < 2:
        return 0 if beans else None
    for threshold in range(1, len(beans) + 1):
        trial_rules = replace(rules, max_parallel_stack=threshold)
        if not any(problem.kind == "parallel_stack"
                   for problem in validate(beans, trial_rules, check_links=False)):
            return threshold
    # Inatteignable : une composante connexe ne peut jamais excéder
    # ``len(beans)``, donc le seuil ``threshold == len(beans)`` ne laisse
    # jamais subsister de violation ``parallel_stack`` — la boucle retourne
    # toujours au plus tard à cette itération (revue de code : ancien
    # ``return len(beans)`` après la boucle, jamais exécuté, couverture
    # 0 % confirmée sur toute la suite de tests).
    raise AssertionError("unreachable: threshold == len(beans) always clears parallel_stack")


def _last_depths(diagnostics, count: int = 3) -> list[dict]:
    """Causes de rejet des ``count`` dernières profondeurs explorées, même
    format que ``run_closure_ab.py._last_depths`` (EXPERIMENT_18_CLOSURE.md)."""
    out = []
    for item in diagnostics[-count:]:
        out.append({
            "depth": item.depth,
            "trials": item.trials,
            "accepted": item.accepted,
            "kept": item.kept,
            "dead_ends": item.dead_ends,
            "rejection_counts": dict(sorted(item.rejection_counts.items(), key=lambda kv: -kv[1])),
            "lookahead_calls": item.lookahead_calls,
            "lookahead_pruned": item.lookahead_pruned,
        })
    return out


def _run_seed(seed: int, rules: ValidationRules, halfplane_weight: float, *,
             free_quota: bool = False, bounded_quota: bool = False,
             par3_bounds: tuple[int, int] | None = None,
             par5_bounds: tuple[int, int] | None = None,
             back_closing_lookahead_from: int | None = None,
             back_clubhouse_max: float | None = None,
             back_start_radii: tuple[float, ...] | None = None,
             back_start_radius_groups: tuple[tuple[float, ...], ...] | None = None,
             back_start_radius_depth2_min_survivors: int | None = None,
             par5_deadline: int | None = None,
             arrival_max_angle_deg: float | None = None):
    start = time.perf_counter()
    front_params = None
    if bounded_quota and (par3_bounds is not None or par5_bounds is not None):
        # Mêmes valeurs par défaut que le front construit par ``solve_course``
        # (course_solver.solve_course), seules les bornes par3/par5 changent --
        # EXPERIMENT_18_CLOSURE.md, section « Reprise — A/B ».
        front_params = SolverParams(
            beam_width=72,
            departure_angles=(300, 330, 0, 30, 60),
            target_radius_scale=0.9,
            bbox_weight=0.0004,
            par3_bounds=par3_bounds or (1, 3),
            par5_bounds=par5_bounds or (1, 3),
        )
    result = solve_course(seed, front_params, None, rules, halfplane_weight=halfplane_weight,
                          free_quota=free_quota, bounded_quota=bounded_quota,
                          back_closing_lookahead_from=back_closing_lookahead_from,
                          back_clubhouse_max=back_clubhouse_max,
                          back_start_radii=back_start_radii,
                          back_start_radius_groups=back_start_radius_groups,
                          back_start_radius_depth2_min_survivors=back_start_radius_depth2_min_survivors,
                          par5_deadline=par5_deadline,
                          arrival_max_angle_deg=arrival_max_angle_deg)
    return result, time.perf_counter() - start


def _seed_summary(result: CourseSolveResult, elapsed: float, rules: ValidationRules) -> dict:
    front_placed = result.front.state.placed
    back_placed = () if result.back is None else result.back.state.placed
    all_placed = front_placed + back_placed

    clubhouse = rules.clubhouse
    # Plafond RÉEL utilisé par chaque nine (``result.*.params.clubhouse_max``),
    # jamais un défaut partagé câblé en dur : si le back a reçu un plafond
    # différent (décision utilisateur, ``solve_course(back_clubhouse_max=
    # ...)``), la validation indépendante le reflète. Défaut inchangé
    # (``SolverParams().clubhouse_max``, 50.0) quand le back est absent.
    front_clubhouse_max = result.front.params.clubhouse_max
    back_clubhouse_max = (SolverParams().clubhouse_max if result.back is None
                          else result.back.params.clubhouse_max)
    # Seuils d'arrivée radiale / bornes par3-par5 RÉELLEMENT utilisés par le
    # front (``None`` si l'expérience correspondante n'est pas active -- voir
    # ``SolverParams.arrival_max_angle_deg``/``par3_bounds``/``par5_bounds``),
    # jamais une valeur câblée en dur : la validation indépendante reflète
    # exactement ce que le solveur a réellement appliqué.
    arrival_max_angle_deg = result.front.params.arrival_max_angle_deg
    bounded_quota = result.front.params.bounded_quota
    independent_violations = _course_violations(
        front_placed, back_placed, rules, clubhouse, front_clubhouse_max, back_clubhouse_max,
        arrival_max_angle_deg=arrival_max_angle_deg,
        par3_bounds=result.front.params.par3_bounds if bounded_quota else None,
        par5_bounds=result.front.params.par5_bounds if bounded_quota else None,
    )
    independent_valid = (len(front_placed) == 9 and len(back_placed) == 9
                         and not independent_violations)
    back_start_distance = (round(math.dist(back_placed[0].tee, clubhouse), 3)
                           if back_placed else None)
    back_return_distance = (round(math.dist(back_placed[-1].green, clubhouse), 3)
                            if back_placed else None)
    front_start_distance = (round(math.dist(front_placed[0].tee, clubhouse), 3)
                            if front_placed else None)
    front_return_distance = (round(math.dist(front_placed[-1].green, clubhouse), 3)
                             if front_placed else None)
    # Angle d'arrivée (degrés) du trou de clôture de chaque nine -- toujours
    # calculé pour le rapport (diagnostic), même quand la règle est inactive
    # (``arrival_max_angle_deg is None``) : ``None`` seulement si l'axe du
    # dernier haricot est dégénéré (voir ``solver._arrival_angle_deg``) ou si
    # la nine est vide.
    front_arrival_angle_deg = (round(_arrival_angle_deg(front_placed[-1], clubhouse), 3)
                               if front_placed else None)
    back_arrival_angle_deg = (round(_arrival_angle_deg(back_placed[-1], clubhouse), 3)
                              if back_placed else None)
    # Trous (1-indexés, ordre de jeu) où un par5 a été posé -- diagnostic
    # direct de la deadline par5 (PLAN.md ligne 6) : doit tomber dans
    # ``[1, par5_deadline]`` quand l'expérience est active.
    front_par5_holes = [i + 1 for i, bean in enumerate(front_placed) if bean.template.par == 5]
    back_par5_holes = [i + 1 for i, bean in enumerate(back_placed) if bean.template.par == 5]
    # Groupe de rayon de départ dont est issu le back final (lignage du
    # premier haricot, même regroupement que ``solver.SolverParams.
    # start_radius_groups`` -- diagnostic PLAN.md ligne 6). ``None`` si le
    # back n'a pas défini de groupes (comportement historique) ou n'a posé
    # aucun trou.
    back_start_groups = (None if result.back is None else result.back.params.start_radius_groups)
    back_start_group = (None if not back_start_groups or not back_placed
                        else list(back_start_groups[_radius_group_index(back_start_distance,
                                                                         back_start_groups)]))

    footprint_ratio = (sum(_polygon_area(bean.footprint) for bean in all_placed)
                       / (rules.width * rules.height)) if all_placed else 0.0

    rejection_counts: Counter = Counter()
    for nine in (result.front, result.back):
        if nine is None:
            continue
        for depth in nine.diagnostics:
            rejection_counts.update(depth.rejection_counts)

    front_trials = result.front.total_trials
    back_trials = 0 if result.back is None else result.back.total_trials

    return {
        "seed": result.seed,
        "success": result.complete,
        "independent_valid": independent_valid,
        "independent_violations": independent_violations,
        "seconds": round(elapsed, 3),
        "trials": front_trials + back_trials,
        "front_trials": front_trials,
        "back_trials": back_trials,
        "front_holes": len(front_placed),
        "back_holes": len(back_placed),
        "front_pars": [bean.template.par for bean in front_placed],
        "back_pars": [bean.template.par for bean in back_placed],
        "footprint_ratio": round(footprint_ratio, 4),
        "largest_parallel_stack": _largest_parallel_stack(all_placed, rules),
        "rejection_counts": dict(sorted(rejection_counts.items())),
        "back_last_depths": () if result.back is None else _last_depths(result.back.diagnostics),
        "front_clubhouse_max": front_clubhouse_max,
        "back_clubhouse_max": back_clubhouse_max,
        "back_start_distance": back_start_distance,
        "back_return_distance": back_return_distance,
        "back_start_group": back_start_group,
        "front_start_distance": front_start_distance,
        "front_return_distance": front_return_distance,
        "front_arrival_angle_deg": front_arrival_angle_deg,
        "back_arrival_angle_deg": back_arrival_angle_deg,
        "front_par5_holes": front_par5_holes,
        "back_par5_holes": back_par5_holes,
        "par5_deadline": result.front.params.par5_deadline,
        "arrival_max_angle_deg": arrival_max_angle_deg,
    }


def _markdown(report: dict, rules: ValidationRules) -> str:
    size = int(rules.width)
    lines = [
        f"# Benchmark parcours 18 trous — seeds 1 à 10 ({size}×{size}, rough partagé)",
        "",
        f"- Succès (18/18) : **{report['success_count']}/10**",
        f"- Validation indépendante conforme : **{report['independent_valid_count']}/10**",
        f"- Doublons exacts normalisés : **{len(report['exact_duplicates'])}**",
        f"- Quasi-doublons (similarité ≥ 85 %) : **{len(report['near_duplicates'])}**",
        f"- Temps total ({report.get('workers', 16)} process) : **{report.get('total_seconds', 0):.1f}s**",
        "",
        "| Seed | Résultat | Front | Back | Temps | Essais | Empreinte | Pile max | Tee10→club | "
        "Green18→club | Groupe | Indép. |",
        "|---:|:---:|:---:|:---:|---:|---:|---:|---:|---:|---:|---:|:---:|",
    ]
    for item in report["seeds"]:
        result = "OK" if item["success"] else "échec"
        indep = "OK" if item["independent_valid"] else "KO"
        tee10 = item.get("back_start_distance")
        green18 = item.get("back_return_distance")
        tee10_text = f"{tee10:.1f}" if tee10 is not None else "—"
        green18_text = f"{green18:.1f}" if green18 is not None else "—"
        group = item.get("back_start_group")
        group_text = "/".join(str(value) for value in group) if group else "—"
        lines.append(
            f"| {item['seed']} | {result} | {item['front_holes']}/9 | {item['back_holes']}/9 | "
            f"{item['seconds']:.1f}s | {item['trials']} | {item['footprint_ratio']:.1%} | "
            f"{item['largest_parallel_stack']} | {tee10_text} | {green18_text} | {group_text} | {indep} |")
    lines.extend(["", "## Pars par nine (ordre de jeu)", ""])
    for item in report["seeds"]:
        front = "-".join(map(str, item["front_pars"])) or "—"
        back = "-".join(map(str, item["back_pars"])) or "—"
        lines.append(f"- seed {item['seed']} : front {front} / back {back}")
    lines.extend(["", "## Rejets cumulés", ""])
    for kind, count in report["rejection_counts"].items():
        lines.append(f"- `{kind}` : {count}")
    if report["near_duplicates"]:
        lines.extend(["", "## Quasi-doublons", ""])
        for pair in report["near_duplicates"]:
            lines.append(f"- seeds {pair['seeds'][0]} et {pair['seeds'][1]} : {pair['similarity']:.1%}")
    failures = [item for item in report["seeds"] if not item["success"]]
    if failures:
        lines.extend(["", "## Échecs — meilleur état et causes dominantes", ""])
        for item in failures:
            dominant = sorted(item["rejection_counts"].items(), key=lambda kv: -kv[1])[:3]
            dominant_text = ", ".join(f"{kind} {count}" for kind, count in dominant) or "—"
            lines.append(f"- seed {item['seed']} : front {item['front_holes']}/9, "
                         f"back {item['back_holes']}/9 — causes dominantes : {dominant_text}")
    solver_config = report.get("solver_config", {})
    if solver_config.get("par5_deadline") is not None:
        lines.extend(["", f"## Deadline par5 (trou {solver_config['par5_deadline']} max)", ""])
        for item in report["seeds"]:
            front_holes = item.get("front_par5_holes") or []
            back_holes = item.get("back_par5_holes") or []
            lines.append(
                f"- seed {item['seed']} : front par5 aux trous {front_holes or '—'} / "
                f"back par5 aux trous {back_holes or '—'}")
    if solver_config.get("arrival_max_angle_deg") is not None:
        max_angle = solver_config["arrival_max_angle_deg"]
        lines.extend(["", f"## Arrivée radiale (seuil {max_angle:.0f}°)", ""])
        for item in report["seeds"]:
            front_angle = item.get("front_arrival_angle_deg")
            back_angle = item.get("back_arrival_angle_deg")
            front_text = f"{front_angle:.1f}°" if front_angle is not None else "—"
            back_text = f"{back_angle:.1f}°" if back_angle is not None else "—"
            front_par = item["front_pars"][-1] if item["front_pars"] else "—"
            back_par = item["back_pars"][-1] if item["back_pars"] else "—"
            lines.append(
                f"- seed {item['seed']} : trou 9 (par {front_par}) arrive à {front_text} / "
                f"trou 18 (par {back_par}) arrive à {back_text}")
    lines.extend(["", "## Back — 3 dernières profondeurs explorées (causes de rejet)", ""])
    for item in report["seeds"]:
        lines.append(f"- seed {item['seed']} :")
        for depth_info in item.get("back_last_depths", ()):
            dominant = list(depth_info["rejection_counts"].items())[:3]
            dominant_text = ", ".join(f"{kind} {count}" for kind, count in dominant) or "—"
            lines.append(
                f"  - profondeur {depth_info['depth']} : {depth_info['trials']} essais, "
                f"{depth_info['accepted']} acceptés, {depth_info['kept']} gardés — {dominant_text}")
    lines.extend(["", "## Observations", ""])
    for observation in report.get("observations", []):
        lines.append(f"- {observation}")
    lines.append("")
    return "\n".join(lines)


def _finalize_report(output: Path, rules: ValidationRules,
                     completed: dict[int, tuple[CourseSolveResult, float]],
                     total_seconds: float, workers: int, solver_config: dict,
                     observations: list[str] | None = None) -> dict:
    """Assemble le rapport final (JSON/SVG par seed, doublons, agrégats) à
    partir d'un ``completed`` déjà résolu -- factorisé hors de
    ``run_benchmark_course`` pour qu'un appelant qui pilote lui-même le pool
    de process (ex. deux expériences partageant les mêmes 10 workers,
    PLAN.md ligne 6) puisse construire ``completed`` à sa façon puis
    réutiliser EXACTEMENT la même logique d'agrégation et le même format de
    rapport."""
    output.mkdir(parents=True, exist_ok=True)
    summaries = []
    fingerprints = {}
    rejection_counts: Counter = Counter()
    size_label = int(rules.width)
    for seed in sorted(completed):
        result, elapsed = completed[seed]
        summary = _seed_summary(result, elapsed, rules)
        summaries.append(summary)
        rejection_counts.update(summary["rejection_counts"])
        suffix = f"course18_{size_label}" + ("" if result.complete else "_failed")
        (output / f"seed{seed}_{suffix}.json").write_text(result.to_json(), encoding="utf-8")
        (output / f"seed{seed}_{suffix}.svg").write_text(render_course_svg(result, rules), encoding="utf-8")
        if result.complete:
            fingerprints[seed] = _fingerprint_beans(result.placed)

    exact, near = [], []
    fp_seeds = sorted(fingerprints)
    for index, first in enumerate(fp_seeds):
        for second in fp_seeds[index + 1:]:
            similarity = _similarity(fingerprints[first], fingerprints[second])
            if fingerprints[first] == fingerprints[second]:
                exact.append([first, second])
            elif similarity >= 0.85:
                near.append({"seeds": [first, second], "similarity": round(similarity, 4)})

    success_count = sum(item["success"] for item in summaries)
    independent_valid_count = sum(item["independent_valid"] for item in summaries)
    report = {
        "size": size_label,
        "rules": {
            "shared_rough": rules.shared_rough,
            "fairway_gap": rules.fairway_gap,
            "edge_min": rules.edge_min,
            "max_parallel_stack": rules.max_parallel_stack,
            "clubhouse_clear_radius": rules.clubhouse_clear_radius,
        },
        "solver_config": solver_config,
        "workers": workers,
        "total_seconds": round(total_seconds, 3),
        "success_count": success_count,
        "independent_valid_count": independent_valid_count,
        "exact_duplicates": exact,
        "near_duplicates": near,
        "rejection_counts": dict(sorted(rejection_counts.items())),
        "seeds": summaries,
        "observations": observations or [],
    }
    (output / "report.json").write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (output / "REPORT.md").write_text(_markdown(report, rules), encoding="utf-8")
    return report


def run_benchmark_course(output: Path, workers: int = 16, rules: ValidationRules | None = None,
                         halfplane_weight: float = 0.0, seeds: range = range(1, 11), *,
                         free_quota: bool = False, bounded_quota: bool = False,
                         par3_bounds: tuple[int, int] | None = None,
                         par5_bounds: tuple[int, int] | None = None,
                         back_closing_lookahead_from: int | None = None,
                         back_clubhouse_max: float | None = None,
                         back_start_radii: tuple[float, ...] | None = None,
                         back_start_radius_groups: tuple[tuple[float, ...], ...] | None = None,
                         back_start_radius_depth2_min_survivors: int | None = None,
                         par5_deadline: int | None = None,
                         arrival_max_angle_deg: float | None = None,
                         observations: list[str] | None = None) -> dict:
    rules = rules or ValidationRules(
        shared_rough=True, fairway_gap=5.0, edge_min=1.0,
        max_parallel_stack=3, clubhouse_clear_radius=10.0,
    )
    output.mkdir(parents=True, exist_ok=True)
    total_start = time.perf_counter()
    completed: dict[int, tuple[CourseSolveResult, float]] = {}
    if workers <= 1:
        for seed in seeds:
            result, elapsed = _run_seed(seed, rules, halfplane_weight, free_quota=free_quota,
                                        bounded_quota=bounded_quota, par3_bounds=par3_bounds,
                                        par5_bounds=par5_bounds,
                                        back_closing_lookahead_from=back_closing_lookahead_from,
                                        back_clubhouse_max=back_clubhouse_max,
                                        back_start_radii=back_start_radii,
                                        back_start_radius_groups=back_start_radius_groups,
                                        back_start_radius_depth2_min_survivors=
                                        back_start_radius_depth2_min_survivors,
                                        par5_deadline=par5_deadline,
                                        arrival_max_angle_deg=arrival_max_angle_deg)
            completed[result.seed] = (result, elapsed)
            print(f"seed {result.seed}: {'OK' if result.complete else 'échec'} "
                  f"front={result.front.state.depth}/9 "
                  f"back={0 if result.back is None else result.back.state.depth}/9 "
                  f"temps={elapsed:.1f}s", flush=True)
    else:
        with ProcessPoolExecutor(max_workers=workers) as executor:
            futures = {executor.submit(_run_seed, seed, rules, halfplane_weight,
                                       free_quota=free_quota, bounded_quota=bounded_quota,
                                       par3_bounds=par3_bounds, par5_bounds=par5_bounds,
                                       back_closing_lookahead_from=back_closing_lookahead_from,
                                       back_clubhouse_max=back_clubhouse_max,
                                       back_start_radii=back_start_radii,
                                       back_start_radius_groups=back_start_radius_groups,
                                       back_start_radius_depth2_min_survivors=
                                       back_start_radius_depth2_min_survivors,
                                       par5_deadline=par5_deadline,
                                       arrival_max_angle_deg=arrival_max_angle_deg): seed
                      for seed in seeds}
            for future in as_completed(futures):
                result, elapsed = future.result()
                completed[result.seed] = (result, elapsed)
                print(f"seed {result.seed}: {'OK' if result.complete else 'échec'} "
                      f"front={result.front.state.depth}/9 "
                      f"back={0 if result.back is None else result.back.state.depth}/9 "
                      f"temps={elapsed:.1f}s", flush=True)

    total_seconds = time.perf_counter() - total_start
    solver_config = {
        "free_quota": free_quota,
        "bounded_quota": bounded_quota,
        "par3_bounds": list(par3_bounds) if par3_bounds else None,
        "par5_bounds": list(par5_bounds) if par5_bounds else None,
        "back_closing_lookahead_from": back_closing_lookahead_from,
        "back_clubhouse_max": back_clubhouse_max,
        "back_start_radii": list(back_start_radii) if back_start_radii else None,
        "back_start_radius_groups": ([list(group) for group in back_start_radius_groups]
                                     if back_start_radius_groups else None),
        "back_start_radius_depth2_min_survivors": back_start_radius_depth2_min_survivors,
        "par5_deadline": par5_deadline,
        "arrival_max_angle_deg": arrival_max_angle_deg,
    }
    return _finalize_report(output, rules, completed, total_seconds, workers, solver_config, observations)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--workers", type=int, default=16)
    parser.add_argument("--size", type=float, default=400.0)
    parser.add_argument("--fairway-gap", type=float, default=5.0)
    parser.add_argument("--edge-min", type=float, default=1.0)
    parser.add_argument("--max-parallel-stack", type=int, default=3)
    parser.add_argument("--clubhouse-clear-radius", type=float, default=10.0)
    parser.add_argument("--halfplane-weight", type=float, default=0.0)
    parser.add_argument("--bounded-quota", action="store_true",
                        help="Quota borné par nine (EXPERIMENT_18_CLOSURE.md, défaut désactivé)")
    parser.add_argument("--par3-bounds", type=int, nargs=2, default=None, metavar=("MIN", "MAX"))
    parser.add_argument("--par5-bounds", type=int, nargs=2, default=None, metavar=("MIN", "MAX"))
    parser.add_argument("--back-closing-lookahead-from", type=int, default=None,
                        help="Fermeture anticipée du back (défaut: comportement historique, 9)")
    parser.add_argument("--back-clubhouse-max", type=float, default=None,
                        help="Plafond dur départ/retour du back (défaut: comportement historique, 50.0)")
    parser.add_argument("--back-start-radii", type=float, nargs="+", default=None,
                        help="Rayons de départ du tee 10 (défaut: comportement historique, 44 48)")
    parser.add_argument("--output", type=Path,
                        default=Path("experiments/bean_paving/output/benchmark_course18_400_1_10"))
    args = parser.parse_args()
    rules = ValidationRules(
        width=args.size, height=args.size, shared_rough=True,
        fairway_gap=args.fairway_gap, edge_min=args.edge_min,
        max_parallel_stack=args.max_parallel_stack,
        clubhouse_clear_radius=args.clubhouse_clear_radius,
    )
    report = run_benchmark_course(
        args.output, args.workers, rules, args.halfplane_weight,
        bounded_quota=args.bounded_quota,
        par3_bounds=tuple(args.par3_bounds) if args.par3_bounds else None,
        par5_bounds=tuple(args.par5_bounds) if args.par5_bounds else None,
        back_closing_lookahead_from=args.back_closing_lookahead_from,
        back_clubhouse_max=args.back_clubhouse_max,
        back_start_radii=tuple(args.back_start_radii) if args.back_start_radii else None,
    )
    print(f"benchmark course18: {report['success_count']}/10 complet, "
          f"{report['independent_valid_count']}/10 validé indépendamment")


if __name__ == "__main__":
    main()
