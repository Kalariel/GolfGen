# Benchmark parcours 18 trous — seeds 1 à 10 (400×400, rough partagé)

- Succès (18/18) : **0/10**
- Validation indépendante conforme : **0/10**
- Doublons exacts normalisés : **0**
- Quasi-doublons (similarité ≥ 85 %) : **0**

| Seed | Résultat | Front | Back | Temps | Essais | Empreinte | Pile max | Indép. |
|---:|:---:|:---:|:---:|---:|---:|---:|---:|:---:|
| 1 | échec | 9/9 | 7/9 | 528.8s | 255330 | 36.0% | 2 | KO |
| 2 | échec | 9/9 | 8/9 | 954.1s | 289026 | 39.7% | 2 | KO |
| 3 | échec | 9/9 | 8/9 | 660.5s | 267714 | 42.0% | 3 | KO |
| 4 | échec | 9/9 | 8/9 | 684.4s | 278226 | 40.3% | 3 | KO |
| 5 | échec | 9/9 | 7/9 | 583.5s | 265842 | 37.6% | 2 | KO |
| 6 | échec | 9/9 | 7/9 | 585.5s | 270882 | 38.7% | 3 | KO |
| 7 | échec | 9/9 | 8/9 | 573.7s | 256482 | 40.4% | 3 | KO |
| 8 | échec | 9/9 | 8/9 | 618.2s | 261954 | 42.2% | 2 | KO |
| 9 | échec | 9/9 | 8/9 | 679.1s | 286722 | 40.8% | 2 | KO |
| 10 | échec | 9/9 | 8/9 | 847.9s | 263682 | 40.0% | 2 | KO |

## Pars par nine (ordre de jeu)

- seed 1 : front 3-4-4-4-4-4-5-5-3 / back 3-4-4-4-3-4-4
- seed 2 : front 3-4-4-4-3-4-5-4-5 / back 4-4-3-3-4-4-4-5
- seed 3 : front 3-4-4-3-5-5-4-4-4 / back 3-5-4-5-3-4-4-4
- seed 4 : front 3-4-4-4-4-5-5-4-3 / back 4-5-3-4-3-4-4-4
- seed 5 : front 3-4-4-3-5-5-4-4-4 / back 4-5-4-4-4-3-4
- seed 6 : front 3-4-4-3-4-4-4-5-5 / back 4-4-4-4-3-4-3
- seed 7 : front 3-4-4-4-4-4-5-5-3 / back 3-4-4-4-3-4-4-5
- seed 8 : front 3-4-5-4-4-4-4-5-3 / back 3-4-5-4-4-4-4-3
- seed 9 : front 3-4-4-4-4-4-5-5-3 / back 4-4-3-3-5-4-4-4
- seed 10 : front 3-4-4-4-3-4-5-4-5 / back 3-5-4-3-4-4-4-4

## Rejets cumulés

- `axis_crossing` : 1358556
- `bounds` : 792612
- `clubhouse_clear` : 46574
- `clubhouse_departure` : 15246
- `clubhouse_return` : 38212
- `fairway_gap` : 1930605
- `parallel_stack` : 93412

## Échecs — meilleur état et causes dominantes

- seed 1 : front 9/9, back 7/9 — causes dominantes : fairway_gap 177754, axis_crossing 125671, bounds 78313
- seed 2 : front 9/9, back 8/9 — causes dominantes : fairway_gap 208841, axis_crossing 147715, bounds 82470
- seed 3 : front 9/9, back 8/9 — causes dominantes : fairway_gap 194311, axis_crossing 139641, bounds 74801
- seed 4 : front 9/9, back 8/9 — causes dominantes : fairway_gap 199214, axis_crossing 139567, bounds 82986
- seed 5 : front 9/9, back 7/9 — causes dominantes : fairway_gap 190843, axis_crossing 132515, bounds 81386
- seed 6 : front 9/9, back 7/9 — causes dominantes : fairway_gap 194242, axis_crossing 136367, bounds 82291
- seed 7 : front 9/9, back 8/9 — causes dominantes : fairway_gap 182932, axis_crossing 127110, bounds 75725
- seed 8 : front 9/9, back 8/9 — causes dominantes : fairway_gap 187338, axis_crossing 133072, bounds 77912
- seed 9 : front 9/9, back 8/9 — causes dominantes : fairway_gap 203011, axis_crossing 143211, bounds 79884
- seed 10 : front 9/9, back 8/9 — causes dominantes : fairway_gap 192119, axis_crossing 133687, bounds 76844

## Observations

- Aucune des dix seeds n'atteint 18/18 à 400×400 (shared_rough) : le front se ferme toujours à 9/9, mais le back plafonne systématiquement à 7 ou 8/9, jamais 9/9 — contrairement à la seed témoin 42 (hors de cet échantillon 1-10, voir EXPERIMENT_18_ROUGH.md section « Essai 400×400 », qui avait atteint 18/18).
- fairway_gap domine très largement les rejets cumulés (1 930 605 occurrences, ~45 % du total), suivi d'axis_crossing (~32 %) puis bounds (~18 %) — même hiérarchie de causes que le run seed 42 documenté dans EXPERIMENT_18_ROUGH.md.
- parallel_stack reste marginal (93 412 occurrences, ~2 %) et la pile côte-à-côte la plus grande observée (meilleur état de chaque seed) est de 2 ou 3, jamais en violation du seuil max_parallel_stack=3.
- Les parcours (meilleur état, souvent 16 ou 17/18 trous posés) occupent 36 à 42 % de la carte 400×400 en empreinte totale (rough inclus) — biais de pourtour déjà observé au benchmark du nine seul (biais visuel du score, non corrigé ici).
- Le premier trou du front est un par 3 sur les dix seeds, comme dans le benchmark du nine seul (output/benchmark_1_10/REPORT.md) : la préférence de départ par 4 reste dominée par la facilité géométrique.
- Temps très variable d'une seed à l'autre (529 s à 954 s, ~9 à 16 min) pour un nombre d'essais comparable (256k à 289k) : aucune cause chronométrée isolée dans ce benchmark, simple constat.
- Validation indépendante (geometry.validate sur front, back et front+back, plus contrôle départ/retour clubhouse, méthode identique à course_solver._course_violations) : conforme à 0/10, exactement comme le résultat complete=False du solveur — aucune divergence entre les deux vérifications.
