"""Benchmark config B (EXPERIMENT_18_CLOSURE.md, section « Reprise — A/B ») sur
les seeds 1 à 10, 400×400 : quota borné par nine (``bounded_quota=True``, par3
et par5 dans ``[1, 3]`` par nine, global ``4/10/4``), fermeture anticipée du
back isolée (``back_closing_lookahead_from=7``), mêmes règles que
``benchmark_course18_400_1_10`` (``shared_rough``, ``fairway_gap=5``,
``edge_min=1``, ``max_parallel_stack=3``, ``clubhouse_clear_radius=10``,
``beam_width=72`` front et back, poids demi-plan 0). Aucun réglage ajusté par
rapport à ``run_closure_ab.py`` config B — seul l'échantillon change (10 seeds
au lieu de 4).

Les seeds 2, 8 et 1 ont déjà été résolues en B (4 seeds) dans
``output/closure_ab_400/B`` : ce run les refait, dans ce nouveau cadre à 10
seeds et 16 process, pour vérifier la reproductibilité (déterminisme) du
solveur avant de les comparer au benchmark séquentiel de référence à 0/10
(``output/benchmark_course18_400_1_10``)."""

from __future__ import annotations

import json
from pathlib import Path

from experiments.bean_paving.benchmark_course import _markdown, run_benchmark_course
from experiments.bean_paving.geometry import ValidationRules

OUTPUT = Path("experiments/bean_paving/output/benchmark_course18_400_bounded_1_10")
REFERENCE = Path("experiments/bean_paving/output/benchmark_course18_400_1_10/report.json")
PRIOR_B = Path("experiments/bean_paving/output/closure_ab_400/B")
PRIOR_SEEDS = (1, 2, 8)


def _prior_pars(seed: int) -> tuple[list[int], list[int]] | None:
    path = PRIOR_B / f"seed{seed}_success.json"
    if not path.exists():
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    front = [bean["par"] for bean in data["front"]["placed"]]
    back = [bean["par"] for bean in data["back"]["placed"]]
    return front, back


def _determinism_observations(report: dict) -> list[str]:
    by_seed = {item["seed"]: item for item in report["seeds"]}
    lines = []
    for seed in PRIOR_SEEDS:
        prior = _prior_pars(seed)
        current = by_seed.get(seed)
        if prior is None or current is None:
            lines.append(f"seed {seed} : pas de résultat antérieur ou courant à comparer.")
            continue
        prior_front, prior_back = prior
        same = (current["front_pars"] == prior_front and current["back_pars"] == prior_back
               and current["success"])
        verdict = "identique (déterministe)" if same else "DIVERGENT"
        lines.append(
            f"seed {seed} : {verdict} — pars front/back antérieurs "
            f"({'-'.join(map(str, prior_front))} / {'-'.join(map(str, prior_back))}) vs "
            f"ce run ({'-'.join(map(str, current['front_pars']))} / "
            f"{'-'.join(map(str, current['back_pars']))}).")
    return lines


def main() -> None:
    rules = ValidationRules(
        width=400.0, height=400.0, shared_rough=True, fairway_gap=5.0, edge_min=1.0,
        max_parallel_stack=3, clubhouse_clear_radius=10.0,
    )
    report = run_benchmark_course(
        OUTPUT, workers=16, rules=rules, halfplane_weight=0.0, seeds=range(1, 11),
        bounded_quota=True, back_closing_lookahead_from=7,
    )

    observations = []
    observations.extend(
        f"Déterminisme (seeds déjà résolues en B à 4 seeds, output/closure_ab_400/B) : {line}"
        for line in _determinism_observations(report))

    if REFERENCE.exists():
        ref = json.loads(REFERENCE.read_text(encoding="utf-8"))
        observations.append(
            f"Comparaison au benchmark séquentiel de référence (quota fixe 2/5/2, "
            f"lookahead 9, {ref['success_count']}/10 complet, "
            f"{ref['independent_valid_count']}/10 validé indépendamment, "
            f"{sum(item['seconds'] for item in ref['seeds']):.1f}s cumulées) : "
            f"ce run (quota borné + lookahead 7) obtient {report['success_count']}/10 complet, "
            f"{report['independent_valid_count']}/10 validé indépendamment, "
            f"temps total {report['total_seconds']:.1f}s sur {report['workers']} process "
            f"(cumulé des temps par seed {sum(item['seconds'] for item in report['seeds']):.1f}s).")
    else:
        observations.append("Benchmark de référence introuvable, pas de comparaison possible.")

    report["observations"] = observations
    OUTPUT.mkdir(parents=True, exist_ok=True)
    (OUTPUT / "report.json").write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (OUTPUT / "REPORT.md").write_text(_markdown(report, rules), encoding="utf-8")
    print(f"benchmark_course18_400_bounded_1_10: {report['success_count']}/10 complet, "
          f"{report['independent_valid_count']}/10 validé indépendamment, "
          f"temps total {report['total_seconds']:.1f}s")


if __name__ == "__main__":
    main()
