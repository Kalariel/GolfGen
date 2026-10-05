"""Config B (``output/benchmark_course18_400_bounded_1_10``) sur les seeds 1 à
10, 400×400, avec le plafond dur du BACK (``clubhouse_max``) relevé à DEUX
FOIS sa valeur par défaut (décision utilisateur, étape 1 d'une série) :
``back_clubhouse_max=100.0`` au lieu de ``50.0`` (1 bloc = 3 m, donc 300 m au
lieu de 150 m) -- le tee 10 (départ) et le green 18 (retour) peuvent
s'éloigner jusqu'à deux fois plus du clubhouse.

Le FRONT reste intégralement inchangé : ``clubhouse_max=50``, ``start_radii=
(24.0, 36.0)``, secteur de départ ``(300, 330, 0, 30, 60)`` -- le tee 1 doit
rester proche du clubhouse. Le green du trou 9 n'est pas non plus touché pour
l'instant (pas de ``front_clubhouse_max`` différent).

Pour que les départs plus lointains soient réellement essayés, les rayons de
départ du tee 10 sont étendus : ``back_start_radii=(44.0, 48.0, 64.0, 80.0,
96.0)`` au lieu du défaut ``(44.0, 48.0)`` (``solver._raw_transforms``, profondeur
1 du back). Coût : 5 rayons au lieu de 2 à la profondeur 1 (davantage de
candidats bruts), mais la largeur de beam reste celle de la config B (72) --
la sélection du beam absorbe le surcroît dès la profondeur 1, donc le coût des
profondeurs suivantes est inchangé.

Seul le PLAFOND DUR (``clubhouse_max``) bouge : la cible de score à la
profondeur 9 (``solver._scaled_target_radius``, ``min(35, 0.75 *
clubhouse_max)``) reste ``min(35, 75) == 35`` -- IDENTIQUE à la config B (0.75
* 100 = 75 > 35, le ``min`` ne change donc rien). Seule la limite de rejet
dur (``solver.expand_state`` / ``_has_closing_sequence``, profondeur 9 et
lookahead) et la validation indépendante (``course_solver._course_violations``,
``back_clubhouse_max`` désormais distinct de ``front_clubhouse_max``) se
relâchent.

Mêmes règles que la config B : ``bounded_quota=True`` (par3/par5 dans
``[1, 3]`` par nine, global ``4/10/4``), ``back_closing_lookahead_from=7``,
``shared_rough``, ``fairway_gap=5``, ``edge_min=1``, ``max_parallel_stack=3``,
``clubhouse_clear_radius=10``, poids demi-plan 0, ``beam_width=72`` front et
back.

Exécution : 10 process en parallèle (un par seed), temps réel mesuré par
process -- un message est affiché (``flush=True``) dès qu'un seed termine
(``benchmark_course.run_benchmark_course``), pour permettre un suivi externe
du run sans dépendre uniquement de la notification de fin de process."""

from __future__ import annotations

import json
from pathlib import Path

from experiments.bean_paving.benchmark_course import _markdown, run_benchmark_course
from experiments.bean_paving.geometry import ValidationRules

OUTPUT = Path("experiments/bean_paving/output/benchmark_course18_400_backfar_1_10")
CONFIG_B = Path("experiments/bean_paving/output/benchmark_course18_400_bounded_1_10/report.json")
REFERENCE = Path("experiments/bean_paving/output/benchmark_course18_400_1_10/report.json")

BACK_CLUBHOUSE_MAX = 100.0
BACK_START_RADII = (44.0, 48.0, 64.0, 80.0, 96.0)


def main() -> None:
    rules = ValidationRules(
        width=400.0, height=400.0, shared_rough=True, fairway_gap=5.0, edge_min=1.0,
        max_parallel_stack=3, clubhouse_clear_radius=10.0,
    )
    report = run_benchmark_course(
        OUTPUT, workers=16, rules=rules, halfplane_weight=0.0, seeds=range(1, 11),
        bounded_quota=True, back_closing_lookahead_from=7,
        back_clubhouse_max=BACK_CLUBHOUSE_MAX, back_start_radii=BACK_START_RADII,
    )

    observations = [
        f"Décision utilisateur (étape 1) : back_clubhouse_max={BACK_CLUBHOUSE_MAX} (défaut 50.0, "
        f"soit {BACK_CLUBHOUSE_MAX * 3:.0f} m au lieu de 150 m, 1 bloc = 3 m) + back_start_radii="
        f"{BACK_START_RADII} (défaut (44.0, 48.0)) -- front inchangé (clubhouse_max=50, "
        f"start_radii=(24.0, 36.0), secteur de départ inchangé), green 9 inchangé.",
    ]

    if CONFIG_B.exists():
        base = json.loads(CONFIG_B.read_text(encoding="utf-8"))
        base_times = {item["seed"]: item["seconds"] for item in base["seeds"]}
        this_times = {item["seed"]: item["seconds"] for item in report["seeds"]}
        delta_lines = []
        for seed in sorted(this_times):
            if seed in base_times:
                delta_lines.append(
                    f"seed {seed} : {base_times[seed]:.1f}s (B) -> {this_times[seed]:.1f}s (back far)")
        observations.append(
            f"Comparaison à la config B (``{CONFIG_B}``) : B obtient "
            f"{base['success_count']}/10 complet, {base['independent_valid_count']}/10 validé "
            f"indépendamment, temps total {base['total_seconds']:.1f}s (16 process) ; ce run "
            f"(back_clubhouse_max={BACK_CLUBHOUSE_MAX}, back_start_radii étendus) obtient "
            f"{report['success_count']}/10 complet, {report['independent_valid_count']}/10 validé "
            f"indépendamment, temps total {report['total_seconds']:.1f}s ({report['workers']} "
            f"process). Temps par seed -- {'; '.join(delta_lines)}.")

        base_success = {item["seed"] for item in base["seeds"] if item["success"]}
        this_success = {item["seed"] for item in report["seeds"] if item["success"]}
        newly_failed = sorted(base_success - this_success)
        newly_fixed = sorted(this_success - base_success)
        if newly_failed or newly_fixed:
            observations.append(
                f"Composition DIFFÉRENTE, pas un sur-ensemble strict de B : seeds redevenues en échec "
                f"{newly_failed or '—'} (18/18 en B), seeds nouvellement résolues {newly_fixed or '—'} "
                f"(échec en B). Cause probable (vérifiée sur les seeds 4 et 8, cf. JSON bruts des deux "
                f"runs) : ``solver._transform_rank`` classe les candidats du tee 10 par écart à la "
                f"cible d'expansion de profondeur 1 (``_scaled_target_radius(1, ...)`` = 110 * "
                f"target_radius_scale(1.0) * map_scale(400/350) ≈ 125.7 blocs pour le back) -- les "
                f"rayons étendus (64/80/96) sont OBJECTIVEMENT plus proches de cette cible que les "
                f"rayons historiques (44/48, écarts ~82/78 contre ~62/46/30), donc ils dominent "
                f"désormais le tri AVANT la coupe du beam (largeur 72, inchangée) à la profondeur 1. "
                f"Sur les seeds 4 et 8, ceci écarte du beam les départs à 44/48 qui portaient "
                f"auparavant la seule trajectoire gagnante (vérifié : seed 4 passe de tee10=44 "
                f"(succès en B) à tee10=96 (échec, bloqué profondeur 8) ; seed 8 de tee10=48 (succès) "
                f"à tee10=64 (échec, bloqué profondeur 8)) -- pas une régression géométrique du "
                f"plafond dur, une redistribution de la composition du beam dès la profondeur 1. Les "
                f"seeds 5, 7 et 10 (en échec en B, résolues ici) bénéficient symétriquement de la même "
                f"redistribution vers d'autres trajectoires. Le total 6/10 (vs 5/10) est donc un gain "
                f"agrégé, PAS une amélioration uniforme seed par seed.")
    else:
        observations.append("Config B introuvable, pas de comparaison de temps par seed possible.")

    if REFERENCE.exists():
        ref = json.loads(REFERENCE.read_text(encoding="utf-8"))
        observations.append(
            f"Comparaison au benchmark séquentiel de référence (quota fixe 2/5/2, lookahead 9, "
            f"clubhouse_max=50 symétrique, {ref['success_count']}/10 complet, "
            f"{ref['independent_valid_count']}/10 validé indépendamment, "
            f"{sum(item['seconds'] for item in ref['seeds']):.1f}s cumulées) : ce run obtient "
            f"{report['success_count']}/10 complet, {report['independent_valid_count']}/10 validé "
            f"indépendamment, temps total {report['total_seconds']:.1f}s sur {report['workers']} "
            f"process (cumulé des temps par seed "
            f"{sum(item['seconds'] for item in report['seeds']):.1f}s).")

    report["observations"] = observations
    OUTPUT.mkdir(parents=True, exist_ok=True)
    (OUTPUT / "report.json").write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (OUTPUT / "REPORT.md").write_text(_markdown(report, rules), encoding="utf-8")
    print(f"benchmark_course18_400_backfar_1_10: {report['success_count']}/10 complet, "
          f"{report['independent_valid_count']}/10 validé indépendamment, "
          f"temps total {report['total_seconds']:.1f}s", flush=True)


if __name__ == "__main__":
    main()
