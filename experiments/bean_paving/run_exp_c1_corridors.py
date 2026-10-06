"""Expérience C1 — couloirs de départ réservés (PLAN.md ligne 6, décision
utilisateur), seeds 1 à 5, 400×400, construite sur la config A (``run_exp_
par5deadline_and_radialarrival.py``, variante ``par5deadline`` -- **5/5**).

Défaut observé sur A : la liaison piétonne clubhouse->tee1 ou clubhouse->
tee10 traverse le fairway d'un AUTRE trou sur chaque seed (17+18 aux seeds
1, 2, 4, 5 ; trou 9 à la seed 3) — constat visuel repris de l'expérience
« liens praticables » (``run_exp_walkable_links.py``, règle générale sur
TOUTES les liaisons piétonnes, **1/5** seulement, net recul).

C1 attaque directement les DEUX seules liaisons concernées (clubhouse<->
tee1, clubhouse<->tee10 -- pas green->tee) par construction plutôt que par
rejet généralisé :

1. Tee 10 FIXÉ avant le front (``solver.SolverParams.fixed_start``) :
   candidats de départ tirés de la grille de profondeur 1 du back (rayons
   **44/48/64** SEULEMENT, PAS 80/96 -- décision utilisateur, 96 jugé trop
   loin, cause probable de l'entrelacement observé sur A), classés par
   ``solver._transform_rank`` (``_tee10_candidates`` ci-dessous). Au plus
   ``TEE10_CANDIDATE_COUNT`` candidats essayés par seed, dans l'ordre de
   classement.
2. Pour chaque candidat : le FRONT tourne librement (comme A) mais son
   trou 1 doit avoir une position angulaire (vue depuis le clubhouse, PAS
   le cap du trou) à au moins 90° de celle du tee 10 déjà choisi
   (``SolverParams.start_angle_reference_deg``/``start_angle_divergence_
   min_deg``) ; puis le BACK tourne avec ``fixed_start`` posé sur ce
   candidat. Un échec (front OU back) passe au candidat suivant ; les 3
   échouent -> échec de la seed (AUCUN repli vers la config A).
3. Couloirs réservés (``geometry.ValidationRules.reserved_corridors`` +
   couloir dynamique ``solver.SolverParams.corridor_from_own_start``) :
   segments à largeur nulle clubhouse->tee10 (connu dès le départ) et
   clubhouse->tee1 (connu dès que le trou 1 est posé) -- aucun cœur fairway
   ne peut les croiser, SAUF celui du trou qui les porte (``owner_order``
   1 ou 10). Vérifié à CHAQUE candidat de placement (``solver.
   _placement_problems``, donc fermeture anticipée incluse) sur les DEUX
   nines, et à nouveau en validation finale indépendante
   (``course_solver._course_violations(reserved_corridors=...)``).

Tout le reste = config A à l'identique (carte 400, ``shared_rough``, zone
clubhouse 10, ``back_clubhouse_max=100`` pour le back, ``par5_deadline=7``
symétrique, ``bounded_quota`` 4/10/4 avec bornes (2,2) implicites via
``par5_bounds``/``par3_bounds`` de A -- voir ``_build_params("par5deadline")``,
réutilisée par IMPORT, pas recopiée).

Exécution : seeds 1 à 5, EN PARALLÈLE (5 process), FOREGROUND, une ligne de
log par CANDIDAT essayé et par seed terminé (``flush=True``)."""

from __future__ import annotations

from collections import Counter
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import replace
import json
import math
from pathlib import Path
import time

from experiments.bean_paving.bean_bank import GenerationParams, generate_bank
from experiments.bean_paving.benchmark_course import _last_depths, _largest_parallel_stack, _polygon_area
from experiments.bean_paving.course_solver import (
    CourseSolveResult,
    _bounded_front_quota,
    _course_violations,
    _global_remaining_from_front,
)
from experiments.bean_paving.joint_solver import GLOBAL_PAR_QUOTA
from experiments.bean_paving.render_course import render_course_svg
from experiments.bean_paving.run_exp_par5deadline_and_radialarrival import _build_params
from experiments.bean_paving.solver import (
    SearchState,
    SolveResult,
    _angular_distance_deg,
    _arrival_angle_deg,
    _raw_transforms,
    _rng_for,
    _transform_rank,
    solve_nine,
)

SEEDS = range(1, 6)
OUTPUT_DIR = Path("experiments/bean_paving/output/exp_c1_corridors_400_1_5")
CONFIG_A_REPORT = Path("experiments/bean_paving/output/exp_par5deadline_400_1_5/report.json")
WALKABLE_LINKS_REPORT = Path("experiments/bean_paving/output/exp_walkable_links_400_1_5/report.json")

TEE10_RADII = (44.0, 48.0, 64.0)
TEE10_CANDIDATE_COUNT = 3
START_ANGLE_DIVERGENCE_MIN_DEG = 90.0
# Marge de sécurité (degrés) entre le cap candidat et la direction purement
# radiale (clubhouse->tee) -- voir ``_tee10_candidates``. ``bean_bank.
# _axis_for`` borne la direction CUMULÉE de chaque segment d'un haricot à
# ``[-52, 52]`` degrés de son cap local 0° (``headings.append(max(-52.0,
# min(52.0, ...)))``), donc le vecteur tee->green RÉSULTANT (combinaison
# convexe de segments tous dans ce cône) ne dévie JAMAIS de plus de 52° du
# cap posé, quel que soit le gabarit (mirroir inclus, cône symétrique) --
# un cap à moins de ``90 - 52 = 38°`` de la direction radiale garantit donc
# ``solver._starts_outward`` pour TOUS les gabarits réels de la banque, pas
# seulement un gabarit de référence. Marge choisie à 35° (< 38°, tolérance
# flottante).
MAX_TEE10_HEADING_DEVIATION_DEG = 35.0


def _angle_deg(point: tuple[float, float], clubhouse: tuple[float, float]) -> float:
    return math.degrees(math.atan2(point[1] - clubhouse[1], point[0] - clubhouse[0])) % 360.0


def _tee10_candidates(bank, clubhouse: tuple[float, float], back_base, rules, seed: int,
                      k: int = TEE10_CANDIDATE_COUNT) -> list[tuple[float, float, float]]:
    """Candidats de départ du tee 10 : grille de profondeur 1 du back
    (``solver._raw_transforms``, rayons ``TEE10_RADII`` seulement, pas les
    rayons étendus 80/96 de ``back_base``), classés par ``solver.
    _transform_rank`` (même oracle que la recherche réelle, voir
    ``solver.py:488-497``). ``_raw_transforms`` ignore le gabarit à la
    profondeur 1 (seul ``allow_mirror`` compte) ; ``_transform_rank`` en a
    besoin pour le point green -- un gabarit par4 de référence (le plus
    représentatif des 3 classes) sert de base de classement commune, le
    gabarit RÉELLEMENT posé au trou 10 restant libre d'être tout autre
    pendant la recherche. Déduplique par (x, y, rotation) -- un départ
    identique en position/cap ne compte qu'une fois, le miroir étant résolu
    séparément par ``fixed_start`` au moment de la recherche réelle.

    Filtré par ``MAX_TEE10_HEADING_DEVIATION_DEG`` AVANT le classement --
    sans ce filtre, ``_transform_rank`` seul (qui ne juge que la distance au
    clubhouse, pas la direction) peut retenir, pour le gabarit de référence,
    un cap qui satisfait ``solver._starts_outward`` de justesse (marge trop
    fine) mais que la PLUPART des gabarits RÉELS de la banque, une fois
    ``fixed_start`` posé, rejettent (``clubhouse_departure``) -- observé
    empiriquement (16/24 essais rejetés sur un cap filtré seulement par
    ``_starts_outward`` du gabarit de référence). Le filtre angulaire
    (cap à moins de ``MAX_TEE10_HEADING_DEVIATION_DEG`` de la direction
    radiale clubhouse->tee) est, lui, INDÉPENDANT du gabarit -- voir sa
    docstring pour la preuve géométrique (borne ``bean_bank._axis_for``)."""
    reference = next(template for template in bank.templates if template.par == 4)
    ranking_params = replace(back_base, start_radii=TEE10_RADII)
    state = SearchState((), (0, 0, 0), 0.0)
    raw = []
    for transform in _raw_transforms(reference, state, clubhouse, ranking_params, seed):
        position_angle = _angle_deg((transform.x, transform.y), clubhouse)
        if _angular_distance_deg(transform.rotation_deg, position_angle) <= MAX_TEE10_HEADING_DEVIATION_DEG:
            raw.append(transform)
    rng = _rng_for(seed, state, "tee10-candidates")
    rng.shuffle(raw)
    raw.sort(key=lambda transform: _transform_rank(reference, transform, 1, clubhouse, ranking_params, rules))
    seen: set[tuple[float, float, float]] = set()
    candidates: list[tuple[float, float, float]] = []
    for transform in raw:
        key = (round(transform.x, 3), round(transform.y, 3), round(transform.rotation_deg, 3))
        if key in seen:
            continue
        seen.add(key)
        candidates.append((transform.x, transform.y, transform.rotation_deg))
        if len(candidates) >= k:
            break
    return candidates


def _depth_score(front: SolveResult, back: SolveResult | None) -> int:
    return front.state.depth * 10 + (0 if back is None else back.state.depth)


def _attempt(seed: int, tee10: tuple[float, float, float], front_base, back_base, rules, bank,
            clubhouse: tuple[float, float]) -> tuple[SolveResult, SolveResult | None]:
    """Une tentative complète (front puis back) pour UN candidat de tee 10 --
    voir le docstring du module pour la séquence exacte."""
    cx, cy, heading = tee10
    angle10 = _angle_deg((cx, cy), clubhouse)

    front_params = replace(front_base, bounded_quota=True, corridor_from_own_start=True,
                           start_angle_reference_deg=angle10,
                           start_angle_divergence_min_deg=START_ANGLE_DIVERGENCE_MIN_DEG)
    front_rules = replace(rules, reserved_corridors=((clubhouse, (cx, cy), 10),))
    front_quota = _bounded_front_quota(front_params)
    front = solve_nine(seed, front_params, front_rules, bank=bank, par_quota=front_quota,
                       require_full_quota=False, global_quota=GLOBAL_PAR_QUOTA)
    if not front.complete:
        return front, None

    tee1 = front.state.placed[0].tee
    # ``back_params.bounded_quota`` reste à son défaut (``False``, comme
    # dans la config A -- ``run_exp_par5deadline_and_radialarrival`` appelle
    # ``solve_course(bounded_quota=True)`` SANS ``bounded_quota_back=True``,
    # donc ``solver._bounded_quota_filter`` n'a jamais guidé le back, même
    # dans A) : seul ``fixed_start`` change ici par rapport à A.
    back_params = replace(back_base, fixed_start=(cx, cy, heading))
    back_rules = replace(rules, reserved_corridors=((clubhouse, tee1, 1), (clubhouse, (cx, cy), 10)))
    used = frozenset(bean.id for bean in front.state.placed)
    back_quota = _global_remaining_from_front(front.state.placed)
    back = solve_nine(seed ^ 0x9E3779B9, back_params, back_rules, bank=bank,
                      obstacles=front.state.placed, blocked_ids=used, order_offset=9,
                      par_quota=back_quota)
    return front, back


def _run_seed(seed: int):
    start = time.perf_counter()
    front_base, back_base, rules = _build_params("par5deadline")  # config A, par import
    clubhouse = rules.clubhouse
    bank = generate_bank(seed, GenerationParams.eighteen())
    candidates = _tee10_candidates(bank, clubhouse, back_base, rules, seed)

    chosen_index = None
    best_front = best_back = None
    best_index = None
    best_score = -1
    attempts: list[dict] = []
    for index, tee10 in enumerate(candidates):
        front, back = _attempt(seed, tee10, front_base, back_base, rules, bank, clubhouse)
        attempts.append({
            "index": index,
            "tee10_x": round(tee10[0], 3), "tee10_y": round(tee10[1], 3),
            "tee10_heading_deg": round(tee10[2], 3),
            "tee10_radius": round(math.dist((tee10[0], tee10[1]), clubhouse), 3),
            "tee10_angle_deg": round(_angle_deg((tee10[0], tee10[1]), clubhouse), 3),
            "front_complete": front.complete,
            "back_complete": None if back is None else back.complete,
        })
        print(f"seed {seed} candidat {index} tee10=({tee10[0]:.1f},{tee10[1]:.1f},{tee10[2]:.0f}°): "
              f"front={'OK' if front.complete else 'échec'} "
              f"back={'—' if back is None else ('OK' if back.complete else 'échec')}", flush=True)
        if front.complete and back is not None and back.complete:
            chosen_index = best_index = index
            best_front, best_back = front, back
            break
        score = _depth_score(front, back)
        if score > best_score:
            best_score = score
            best_front, best_back = front, back
            best_index = index

    front, back = best_front, best_back
    tee1 = front.state.placed[0].tee if front.state.placed else None
    angle1 = None if tee1 is None else round(_angle_deg(tee1, clubhouse), 3)

    if chosen_index is not None:
        cx, cy, _ = candidates[chosen_index]
        corridors = ((clubhouse, tee1, 1), (clubhouse, (cx, cy), 10))
        violations = _course_violations(
            front.state.placed, back.state.placed, rules, clubhouse,
            front_base.clubhouse_max, back_base.clubhouse_max,
            par3_bounds=front_base.par3_bounds, par5_bounds=front_base.par5_bounds,
            par5_deadline=front_base.par5_deadline,
            # back_params.bounded_quota reste False (voir _attempt) -- comme
            # dans la config A, seules les bornes du FRONT sont vérifiées ;
            # la deadline par5, elle, n'est pas gated par bounded_quota dans
            # ``solve_course`` et s'applique donc aux deux nines.
            back_par3_bounds=None, back_par5_bounds=None,
            back_par5_deadline=back_base.par5_deadline,
            reserved_corridors=corridors,
        )
        complete = front.complete and back.complete and not violations
    else:
        violations = ["front_incomplete" if not front.complete else "back_incomplete"]
        complete = False

    result = CourseSolveResult(seed, front, back, complete, tuple(violations))
    elapsed = time.perf_counter() - start
    return result, elapsed, candidates, chosen_index, best_index, attempts, angle1


def _seed_summary(result: CourseSolveResult, elapsed: float, candidates: list[tuple[float, float, float]],
                  chosen_index: int | None, attempts: list[dict], angle1: float | None,
                  rules) -> dict:
    front_placed = result.front.state.placed
    back_placed = () if result.back is None else result.back.state.placed
    all_placed = front_placed + back_placed
    clubhouse = rules.clubhouse

    independent_valid = (len(front_placed) == 9 and len(back_placed) == 9
                         and not any(kind == "corridor_blocked" for kind in result.violations)
                         and result.complete)

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

    chosen = attempts[chosen_index] if chosen_index is not None else None

    return {
        "seed": result.seed,
        "success": result.complete,
        "independent_valid": independent_valid,
        "violations": list(result.violations),
        "corridor_blocked": any(kind == "corridor_blocked" for kind in result.violations),
        "seconds": round(elapsed, 3),
        "attempts_tried": len(attempts),
        "attempts": attempts,
        "chosen_candidate": chosen,
        "front_holes": len(front_placed),
        "back_holes": len(back_placed),
        "front_pars": [bean.template.par for bean in front_placed],
        "back_pars": [bean.template.par for bean in back_placed],
        "front_par5_holes": front_par5_holes,
        "back_par5_holes": back_par5_holes,
        "front_arrival_angle_deg": front_angle,
        "back_arrival_angle_deg": back_angle,
        "tee1_angle_deg": angle1,
        "tee10_angle_deg": None if chosen is None else chosen["tee10_angle_deg"],
        "angle_divergence_deg": (None if angle1 is None or chosen is None else
                                 round(min(abs(angle1 - chosen["tee10_angle_deg"]) % 360.0,
                                          360.0 - abs(angle1 - chosen["tee10_angle_deg"]) % 360.0), 3)),
        "footprint_ratio": round(footprint_ratio, 4),
        "largest_parallel_stack": _largest_parallel_stack(all_placed, rules),
        "rejection_counts": dict(sorted(rejection_counts.items())),
        "back_last_depths": () if result.back is None else _last_depths(result.back.diagnostics),
    }


def _report_lookup(path: Path) -> dict[int, dict]:
    if not path.exists():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    return {item["seed"]: item for item in data["seeds"] if item["seed"] in SEEDS}


def _overlay_corridors_svg(svg: str, clubhouse: tuple[float, float], tee1: tuple[float, float] | None,
                           tee10: tuple[float, float] | None) -> str:
    """Surligne (rouge vif, plein) les deux couloirs réservés par-dessus la
    liaison piétonne déjà tracée par ``render_course_svg`` (blanc pointillé,
    commune à TOUTES les liaisons) -- même formule de projection (``size,
    pad=800,24``) recopiée ici plutôt que modifiée dans ``render_course.py``,
    pour ne rien changer au rendu partagé par les autres expériences."""
    size, pad = 800, 24
    map_width = clubhouse[0] * 2.0
    map_height = clubhouse[1] * 2.0
    scale = (size - 2 * pad) / max(map_width, map_height)
    point = lambda p: (pad + p[0] * scale, pad + p[1] * scale)
    lines = []
    for label, tee in (("tee1", tee1), ("tee10", tee10)):
        if tee is None:
            continue
        a, b = point(clubhouse), point(tee)
        lines.append(f'<line x1="{a[0]:.1f}" y1="{a[1]:.1f}" x2="{b[0]:.1f}" y2="{b[1]:.1f}" '
                     f'stroke="#ff2d7a" stroke-opacity="0.85" stroke-width="2.2"/>')
        lines.append(f'<text x="{(a[0] + b[0]) / 2 + 4:.1f}" y="{(a[1] + b[1]) / 2 - 4:.1f}" '
                     f'font-size="10" fill="#ff2d7a">couloir {label}</text>')
    return svg.replace("</svg>", "".join(lines) + "</svg>")


def _markdown(summaries: list[dict], total_seconds: float, config_a: dict[int, dict],
             walkable_links: dict[int, dict]) -> str:
    success_count = sum(item["success"] for item in summaries)
    independent_valid_count = sum(item["independent_valid"] for item in summaries)
    a_success = sum(1 for seed in SEEDS if config_a.get(seed, {}).get("success"))
    wl_success = sum(1 for seed in SEEDS if walkable_links.get(seed, {}).get("success"))
    lines = [
        "# Expérience C1 — couloirs de départ réservés (seeds 1 à 5, 400×400)",
        "",
        f"- Succès (18/18) : **{success_count}/5** (config A : **{a_success}/5** ; "
        f"liens praticables généralisés : **{wl_success}/5**)",
        f"- Validation indépendante conforme (quotas + couloirs) : **{independent_valid_count}/5**",
        f"- Temps total (5 process) : **{total_seconds:.1f}s**",
        "",
        f"- Tee 10 fixé avant le front (``solver.SolverParams.fixed_start``), candidats tirés des "
        f"rayons **{TEE10_RADII}** (pas 80/96), au plus **{TEE10_CANDIDATE_COUNT}** essayés par seed, "
        f"classés par ``solver._transform_rank``. Divergence angulaire tee1/tee10 (vue depuis le "
        f"clubhouse) >= **{START_ANGLE_DIVERGENCE_MIN_DEG:.0f}°** imposée au front. Couloirs réservés "
        "clubhouse<->tee1 et clubhouse<->tee10 (largeur nulle, propriétaire exclu) vérifiés à chaque "
        "candidat de placement des deux nines ET en validation finale indépendante.",
        "",
        "| Seed | Résultat | Front | Back | Temps | Essais | Candidat retenu (rayon, angle) | "
        "Angle tee1 | Angle tee10 | Divergence | Couloirs | Indép. | Config A | Liens praticables |",
        "|---:|:---:|:---:|:---:|---:|---:|:---:|---:|---:|---:|:---:|:---:|:---:|:---:|",
    ]
    for item in summaries:
        a = config_a.get(item["seed"], {})
        wl = walkable_links.get(item["seed"], {})
        a_text = f"{'OK' if a.get('success') else 'échec'} {a.get('seconds', 0):.1f}s" if a else "—"
        wl_text = f"{'OK' if wl.get('success') else 'échec'} {wl.get('seconds', 0):.1f}s" if wl else "—"
        result = "OK" if item["success"] else "échec"
        indep = "OK" if item["independent_valid"] else "KO"
        corridors_status = "KO" if item["corridor_blocked"] else "OK"
        chosen = item["chosen_candidate"]
        candidate_text = ("—" if chosen is None
                          else f"#{chosen['index']} ({chosen['tee10_radius']:.0f}, "
                               f"{chosen['tee10_angle_deg']:.0f}°)")
        angle1 = f"{item['tee1_angle_deg']:.0f}°" if item["tee1_angle_deg"] is not None else "—"
        angle10 = f"{item['tee10_angle_deg']:.0f}°" if item["tee10_angle_deg"] is not None else "—"
        divergence = (f"{item['angle_divergence_deg']:.0f}°" if item["angle_divergence_deg"] is not None
                     else "—")
        lines.append(
            f"| {item['seed']} | {result} | {item['front_holes']}/9 | {item['back_holes']}/9 | "
            f"{item['seconds']:.1f}s | {item['attempts_tried']} | {candidate_text} | {angle1} | "
            f"{angle10} | {divergence} | {corridors_status} | {indep} | {a_text} | {wl_text} |")

    lines.extend(["", "## Candidats de tee 10 essayés par seed", ""])
    for item in summaries:
        lines.append(f"- seed {item['seed']} :")
        for attempt in item["attempts"]:
            back_status = "—" if attempt["back_complete"] is None else ("OK" if attempt["back_complete"] else "échec")
            lines.append(
                f"  - candidat {attempt['index']} : tee10=({attempt['tee10_x']:.1f}, "
                f"{attempt['tee10_y']:.1f}), cap {attempt['tee10_heading_deg']:.0f}°, rayon "
                f"{attempt['tee10_radius']:.1f}, angle {attempt['tee10_angle_deg']:.1f}° -- front "
                f"{'OK' if attempt['front_complete'] else 'échec'}, back {back_status}")

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

    lines.extend(["", "## Rejets cumulés (tous candidats confondus)", ""])
    all_rejections: Counter = Counter()
    for item in summaries:
        all_rejections.update(item["rejection_counts"])
    for kind, count in sorted(all_rejections.items()):
        lines.append(f"- `{kind}` : {count}")

    lines.extend(["", "## Back — 3 dernières profondeurs explorées (meilleure tentative, causes de rejet)", ""])
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
        lines.extend(["", "## Échecs — causes dominantes (meilleure tentative)", ""])
        for item in failures:
            dominant = sorted(item["rejection_counts"].items(), key=lambda kv: -kv[1])[:3]
            dominant_text = ", ".join(f"{kind} {count}" for kind, count in dominant) or "—"
            lines.append(f"- seed {item['seed']} : front {item['front_holes']}/9, "
                         f"back {item['back_holes']}/9, {item['attempts_tried']} candidats essayés — "
                         f"causes dominantes : {dominant_text}")
    lines.append("")
    return "\n".join(lines)


def main() -> None:
    config_a = _report_lookup(CONFIG_A_REPORT)
    walkable_links = _report_lookup(WALKABLE_LINKS_REPORT)
    total_start = time.perf_counter()
    completed: dict[int, tuple] = {}

    with ProcessPoolExecutor(max_workers=5) as executor:
        futures = {executor.submit(_run_seed, seed): seed for seed in SEEDS}
        for future in as_completed(futures):
            result, elapsed, candidates, chosen_index, best_index, attempts, angle1 = future.result()
            completed[result.seed] = (result, elapsed, candidates, chosen_index, best_index, attempts, angle1)
            back_depth = 0 if result.back is None else result.back.state.depth
            print(f"seed {result.seed}: {'OK' if result.complete else 'échec'} "
                  f"front={result.front.state.depth}/9 back={back_depth}/9 "
                  f"candidats={len(attempts)} temps={elapsed:.1f}s "
                  f"({len(completed)}/{len(SEEDS)} terminés)", flush=True)

    total_seconds = round(time.perf_counter() - total_start, 3)

    _, _, rules = _build_params("par5deadline")
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    summaries = []
    for seed in sorted(completed):
        result, elapsed, candidates, chosen_index, best_index, attempts, angle1 = completed[seed]
        summary = _seed_summary(result, elapsed, candidates, chosen_index, attempts, angle1, rules)
        summaries.append(summary)
        suffix = "course18_400" + ("" if result.complete else "_failed")
        (OUTPUT_DIR / f"seed{seed}_{suffix}.json").write_text(result.to_json(), encoding="utf-8")
        svg = render_course_svg(result, rules)
        tee1 = result.front.state.placed[0].tee if result.front.state.placed else None
        # Sur échec total, aucun trou 10 n'est posé (``result.back`` reste
        # ``None`` ou incomplet) : on surligne quand même le couloir sur la
        # position du MEILLEUR candidat essayé (``best_index``), à titre
        # diagnostique (PLAN.md discipline : « un échec est enregistré avec
        # son meilleur état »).
        tee10 = (result.back.state.placed[0].tee if result.back is not None and result.back.state.placed
                else (None if best_index is None else candidates[best_index][:2]))
        svg = _overlay_corridors_svg(svg, rules.clubhouse, tee1, tee10)
        (OUTPUT_DIR / f"seed{seed}_{suffix}.svg").write_text(svg, encoding="utf-8")

    success_count = sum(item["success"] for item in summaries)
    independent_valid_count = sum(item["independent_valid"] for item in summaries)
    report = {
        "experiment": "c1_corridors",
        "size": 400,
        "seeds_requested": list(SEEDS),
        "tee10_radii": list(TEE10_RADII),
        "tee10_candidate_count": TEE10_CANDIDATE_COUNT,
        "start_angle_divergence_min_deg": START_ANGLE_DIVERGENCE_MIN_DEG,
        "rules": {
            "shared_rough": rules.shared_rough,
            "fairway_gap": rules.fairway_gap,
            "edge_min": rules.edge_min,
            "max_parallel_stack": rules.max_parallel_stack,
            "clubhouse_clear_radius": rules.clubhouse_clear_radius,
        },
        "success_count": success_count,
        "independent_valid_count": independent_valid_count,
        "config_a_success_count": sum(1 for s in SEEDS if config_a.get(s, {}).get("success")),
        "walkable_links_success_count": sum(1 for s in SEEDS if walkable_links.get(s, {}).get("success")),
        "total_seconds": total_seconds,
        "seeds": summaries,
    }
    (OUTPUT_DIR / "report.json").write_text(json.dumps(report, indent=2, sort_keys=True) + "\n",
                                            encoding="utf-8")
    (OUTPUT_DIR / "REPORT.md").write_text(_markdown(summaries, total_seconds, config_a, walkable_links),
                                          encoding="utf-8")
    print(f"c1_corridors: {success_count}/5 complet, {independent_valid_count}/5 validé "
          f"indépendamment (config A : {report['config_a_success_count']}/5, "
          f"liens praticables : {report['walkable_links_success_count']}/5)", flush=True)


if __name__ == "__main__":
    main()
