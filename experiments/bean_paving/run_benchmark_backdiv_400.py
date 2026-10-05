"""Config B (``output/benchmark_course18_400_bounded_1_10``) étendue aux
distances du BACK « back-far » (``output/benchmark_course18_400_backfar_1_10``,
``back_clubhouse_max=100.0``, ``back_start_radii=(44.0, 48.0, 64.0, 80.0,
96.0)``), plus la DIVERSITÉ STRATIFIÉE des départs du tee 10 par groupe de
rayon (décision utilisateur, PLAN.md ligne 6, nouveaux opt-in de
``solver.SolverParams`` / ``course_solver.solve_course`` -- défauts
inchangés) :

- ``back_start_radius_groups=((44.0, 48.0), (64.0,), (80.0,), (96.0,))`` --
  4 groupes, les rayons historiques (44/48) fusionnés en UN SEUL groupe.
- Chaque groupe reçoit une part ÉGALE (``beam_width // 4 == 18``) aux DEUX
  endroits où le diagnostic (``output/benchmark_course18_400_backfar_1_10/
  REPORT.md``) a identifié que la diversité se faisait écraser dès la
  profondeur 1 : (a) la troncature des transformations brutes par candidat
  (``solver._stratified_truncate``, ``start_transforms_per_candidate=144``) et
  (b) la sélection du beam (``solver._select_beam_stratified``, largeur 72
  inchangée). Le reliquat (division non entière, groupe sous-peuplé) est
  comblé par rang global, jamais perdu.
- ``back_start_radius_depth2_min_survivors=9`` -- garde-fou LÉGER (moitié de
  la part de la profondeur 1) à la profondeur 2 SEULEMENT : un diagnostic
  chiffré préalable (script jetable, seeds 4 et 8, voir les observations
  ci-dessous) a montré que, sans ce garde-fou, la diversité de la
  profondeur 1 s'effondre quasi totalement UNE profondeur plus tard (ex.
  seed 4 : groupe {44,48} passe de 47/72 à 4/72) -- aucune stratification de
  la troncature n'est nécessaire à cette profondeur : les transformations
  n'y dépendent plus de ``start_radii`` (``solver._raw_transforms``, branche
  ``state.placed`` non vide), seule la sélection du beam est concernée.

Même config B par ailleurs (``bounded_quota=True``, par3/par5 dans
``[1, 3]``, ``back_closing_lookahead_from=7``, ``shared_rough``,
``fairway_gap=5``, ``edge_min=1``, ``max_parallel_stack=3``,
``clubhouse_clear_radius=10``, poids demi-plan 0, ``beam_width=72`` front et
back). Front intégralement inchangé.

Exécution : 10 process en parallèle (un par seed), temps réel mesuré par
process -- un message est affiché (``flush=True``) dès qu'un seed termine
(``benchmark_course.run_benchmark_course``) pour permettre un suivi externe
du run sans dépendre uniquement de la notification de fin de process."""

from __future__ import annotations

import json
from pathlib import Path

from experiments.bean_paving.benchmark_course import _markdown, run_benchmark_course
from experiments.bean_paving.geometry import ValidationRules

OUTPUT = Path("experiments/bean_paving/output/benchmark_course18_400_backdiv_1_10")
CONFIG_B = Path("experiments/bean_paving/output/benchmark_course18_400_bounded_1_10/report.json")
BACK_FAR = Path("experiments/bean_paving/output/benchmark_course18_400_backfar_1_10/report.json")

BACK_CLUBHOUSE_MAX = 100.0
BACK_START_RADII = (44.0, 48.0, 64.0, 80.0, 96.0)
BACK_START_RADIUS_GROUPS = ((44.0, 48.0), (64.0,), (80.0,), (96.0,))
BACK_START_RADIUS_DEPTH2_MIN_SURVIVORS = 9


def main() -> None:
    rules = ValidationRules(
        width=400.0, height=400.0, shared_rough=True, fairway_gap=5.0, edge_min=1.0,
        max_parallel_stack=3, clubhouse_clear_radius=10.0,
    )
    report = run_benchmark_course(
        OUTPUT, workers=16, rules=rules, halfplane_weight=0.0, seeds=range(1, 11),
        bounded_quota=True, back_closing_lookahead_from=7,
        back_clubhouse_max=BACK_CLUBHOUSE_MAX, back_start_radii=BACK_START_RADII,
        back_start_radius_groups=BACK_START_RADIUS_GROUPS,
        back_start_radius_depth2_min_survivors=BACK_START_RADIUS_DEPTH2_MIN_SURVIVORS,
    )

    observations = [
        f"Décision utilisateur : diversité stratifiée des départs du tee 10 par groupe de rayon "
        f"(``solver.SolverParams.start_radius_groups={BACK_START_RADIUS_GROUPS}``, "
        f"``start_radius_depth2_min_survivors={BACK_START_RADIUS_DEPTH2_MIN_SURVIVORS}``, nouveaux "
        f"opt-in, défauts () et 0 inchangés) par-dessus les distances back-far "
        f"(back_clubhouse_max={BACK_CLUBHOUSE_MAX}, back_start_radii={BACK_START_RADII}) -- front "
        f"inchangé, green 9 inchangé.",
        "Vérification préalable (script jetable, non committé) : sur les seeds 4 et 8, le beam de "
        "profondeur 1 du back-far (sans stratification) contenait déjà les deux rayons historiques "
        "(seed 4 : 9+38=47/72 en groupe {44,48} ; seed 8 : 2+2=4/72), mais ce groupe s'effondrait "
        "presque totalement à la profondeur 2 SANS garde-fou (seed 4 : 47 -> 4/72 ; seed 8 : 4 -> 0/72 "
        "-- lignage mort géométriquement pour cette seed, confirmé par un essai isolé : les 2 seuls "
        "candidats de profondeur 1 du groupe {44,48} produisent 0 enfant valide à la profondeur 2, "
        "rejet axis_crossing/fairway_gap systématique -- aucune sélection de beam ne peut ressusciter "
        "un lignage sans successeur valide). Avec stratification profondeur 1 (part égale 18/groupe) "
        "et garde-fou profondeur 2 (survivants minimum testés : 3, 6, 9) : seed 4 conserve EXACTEMENT "
        "ce minimum réservé du groupe {44,48} à la profondeur 2 (3, 6 ou 9 selon le réglage, au lieu "
        "de 4/72 sans garde-fou) -- le réglage retenu ici (9) a été choisi comme compromis léger "
        "(moitié de la part de la profondeur 1, 18/2) sans optimisation fine supplémentaire.",
    ]

    if CONFIG_B.exists():
        base = json.loads(CONFIG_B.read_text(encoding="utf-8"))
        base_times = {item["seed"]: item["seconds"] for item in base["seeds"]}
        this_times = {item["seed"]: item["seconds"] for item in report["seeds"]}
        delta_lines = [f"seed {seed} : {base_times[seed]:.1f}s (B) -> {this_times[seed]:.1f}s (back-div)"
                       for seed in sorted(this_times) if seed in base_times]
        observations.append(
            f"Comparaison à la config B (``{CONFIG_B}``) : B obtient {base['success_count']}/10 "
            f"complet, {base['independent_valid_count']}/10 validé indépendamment, temps total "
            f"{base['total_seconds']:.1f}s (16 process) ; ce run (back-div) obtient "
            f"{report['success_count']}/10 complet, {report['independent_valid_count']}/10 validé "
            f"indépendamment, temps total {report['total_seconds']:.1f}s ({report['workers']} "
            f"process). Temps par seed -- {'; '.join(delta_lines)}.")
        base_success = {item["seed"] for item in base["seeds"] if item["success"]}
        this_success = {item["seed"] for item in report["seeds"] if item["success"]}
        observations.append(
            f"Composition vs B : seeds redevenues en échec {sorted(base_success - this_success) or '—'} "
            f"(18/18 en B), seeds nouvellement résolues {sorted(this_success - base_success) or '—'} "
            f"(échec en B).")
    else:
        observations.append("Config B introuvable, pas de comparaison de temps par seed possible.")

    if BACK_FAR.exists():
        far = json.loads(BACK_FAR.read_text(encoding="utf-8"))
        far_times = {item["seed"]: item["seconds"] for item in far["seeds"]}
        this_times = {item["seed"]: item["seconds"] for item in report["seeds"]}
        delta_lines = [f"seed {seed} : {far_times[seed]:.1f}s (back-far) -> {this_times[seed]:.1f}s (back-div)"
                       for seed in sorted(this_times) if seed in far_times]
        far_success = {item["seed"] for item in far["seeds"] if item["success"]}
        this_success = {item["seed"] for item in report["seeds"] if item["success"]}
        observations.append(
            f"Comparaison à back-far (``{BACK_FAR}``) : back-far obtient {far['success_count']}/10 "
            f"complet, {far['independent_valid_count']}/10 validé indépendamment, temps total "
            f"{far['total_seconds']:.1f}s (16 process) ; ce run (back-div) obtient "
            f"{report['success_count']}/10 complet, {report['independent_valid_count']}/10 validé "
            f"indépendamment, temps total {report['total_seconds']:.1f}s ({report['workers']} "
            f"process). Seeds redevenues en échec vs back-far "
            f"{sorted(far_success - this_success) or '—'}, seeds nouvellement résolues vs back-far "
            f"{sorted(this_success - far_success) or '—'}. Temps par seed -- {'; '.join(delta_lines)}.")

    report["observations"] = observations
    OUTPUT.mkdir(parents=True, exist_ok=True)
    (OUTPUT / "report.json").write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (OUTPUT / "REPORT.md").write_text(_markdown(report, rules), encoding="utf-8")
    print(f"benchmark_course18_400_backdiv_1_10: {report['success_count']}/10 complet, "
          f"{report['independent_valid_count']}/10 validé indépendamment, "
          f"temps total {report['total_seconds']:.1f}s", flush=True)


if __name__ == "__main__":
    main()
