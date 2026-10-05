# Benchmark parcours 18 trous — seeds 1 à 10 (400×400, rough partagé)

- Succès (18/18) : **6/10**
- Validation indépendante conforme : **6/10**
- Doublons exacts normalisés : **0**
- Quasi-doublons (similarité ≥ 85 %) : **0**
- Temps total (16 process) : **860.9s**

| Seed | Résultat | Front | Back | Temps | Essais | Empreinte | Pile max | Tee10→club | Green18→club | Indép. |
|---:|:---:|:---:|:---:|---:|---:|---:|---:|---:|---:|:---:|
| 1 | OK | 9/9 | 9/9 | 687.3s | 262098 | 43.6% | 2 | 96.0 | 35.0 | OK |
| 2 | OK | 9/9 | 9/9 | 789.9s | 300402 | 43.3% | 2 | 44.0 | 34.8 | OK |
| 3 | OK | 9/9 | 9/9 | 837.5s | 275760 | 45.2% | 3 | 80.0 | 29.1 | OK |
| 4 | échec | 9/9 | 7/9 | 564.6s | 247122 | 37.8% | 2 | 96.0 | 150.0 | KO |
| 5 | OK | 9/9 | 9/9 | 860.7s | 272610 | 41.8% | 2 | 96.0 | 35.9 | OK |
| 6 | échec | 9/9 | 6/9 | 420.7s | 233586 | 35.5% | 2 | 80.0 | 183.4 | KO |
| 7 | OK | 9/9 | 9/9 | 700.3s | 264690 | 45.4% | 3 | 80.0 | 35.5 | OK |
| 8 | échec | 9/9 | 7/9 | 592.0s | 251874 | 39.2% | 3 | 64.0 | 159.9 | KO |
| 9 | échec | 9/9 | 7/9 | 425.9s | 238482 | 38.4% | 3 | 80.0 | 165.8 | KO |
| 10 | OK | 9/9 | 9/9 | 701.6s | 254754 | 44.4% | 3 | 64.0 | 73.2 | OK |

## Pars par nine (ordre de jeu)

- seed 1 : front 3-4-4-3-5-3-4-4-4 / back 3-5-4-4-5-4-4-5-4
- seed 2 : front 3-4-4-4-3-4-5-4-3 / back 4-4-4-4-5-4-3-5-5
- seed 3 : front 3-4-4-3-5-4-4-4-3 / back 3-5-4-5-4-4-5-4-4
- seed 4 : front 3-4-4-4-4-3-3-5-4 / back 3-5-5-4-4-4-4
- seed 5 : front 3-4-4-5-3-3-4-4-4 / back 3-4-4-4-4-4-5-5-5
- seed 6 : front 3-4-4-4-3-3-5-4-4 / back 3-4-4-4-4-4
- seed 7 : front 3-4-4-3-5-3-4-4-4 / back 3-4-4-5-5-4-5-4-4
- seed 8 : front 3-4-4-4-3-4-4-5-3 / back 4-5-5-5-3-4-4
- seed 9 : front 3-4-4-5-4-3-4-4-3 / back 3-5-5-5-4-4-4
- seed 10 : front 3-4-4-4-3-4-5-4-3 / back 3-4-4-4-4-4-5-5-5

## Rejets cumulés

- `axis_crossing` : 1325542
- `bounds` : 716722
- `clubhouse_clear` : 82403
- `clubhouse_departure` : 16724
- `clubhouse_return` : 42480
- `fairway_gap` : 1876472
- `parallel_stack` : 103755

## Échecs — meilleur état et causes dominantes

- seed 4 : front 9/9, back 7/9 — causes dominantes : fairway_gap 176363, axis_crossing 123100, bounds 72142
- seed 6 : front 9/9, back 6/9 — causes dominantes : fairway_gap 166226, axis_crossing 114126, bounds 68240
- seed 8 : front 9/9, back 7/9 — causes dominantes : fairway_gap 177591, axis_crossing 126672, bounds 79490
- seed 9 : front 9/9, back 7/9 — causes dominantes : fairway_gap 167223, axis_crossing 118323, bounds 63953

## Back — 3 dernières profondeurs explorées (causes de rejet)

- seed 1 :
  - profondeur 7 : 17712 essais, 11 acceptés, 11 gardés — axis_crossing 13147, bounds 4888, fairway_gap 17700
  - profondeur 8 : 3168 essais, 24 acceptés, 24 gardés — axis_crossing 2726, clubhouse_clear 11, fairway_gap 3142
  - profondeur 9 : 3456 essais, 17 acceptés, 15 gardés — axis_crossing 2408, clubhouse_clear 1838, fairway_gap 3362
- seed 2 :
  - profondeur 7 : 16848 essais, 354 acceptés, 72 gardés — axis_crossing 12287, bounds 3914, fairway_gap 16463
  - profondeur 8 : 15696 essais, 366 acceptés, 72 gardés — axis_crossing 13110, bounds 600, clubhouse_clear 30
  - profondeur 9 : 10368 essais, 496 acceptés, 72 gardés — axis_crossing 6235, clubhouse_clear 5312, fairway_gap 9360
- seed 3 :
  - profondeur 7 : 19728 essais, 283 acceptés, 72 gardés — axis_crossing 15919, bounds 4158, fairway_gap 19445
  - profondeur 8 : 13824 essais, 225 acceptés, 72 gardés — axis_crossing 11240, bounds 337, clubhouse_clear 165
  - profondeur 9 : 10368 essais, 13 acceptés, 13 gardés — axis_crossing 8963, clubhouse_clear 4647, clubhouse_return 263
- seed 4 :
  - profondeur 6 : 18000 essais, 49 acceptés, 47 gardés — axis_crossing 12899, bounds 7650, fairway_gap 17527
  - profondeur 7 : 10512 essais, 1 acceptés, 1 gardés — axis_crossing 8720, bounds 2559, fairway_gap 10510
  - profondeur 8 : 288 essais, 0 acceptés, 0 gardés — axis_crossing 255, fairway_gap 288, parallel_stack 57
- seed 5 :
  - profondeur 7 : 15408 essais, 92 acceptés, 72 gardés — axis_crossing 12467, bounds 5186, fairway_gap 15316
  - profondeur 8 : 10800 essais, 351 acceptés, 72 gardés — axis_crossing 7303, bounds 264, clubhouse_clear 88
  - profondeur 9 : 10368 essais, 50 acceptés, 39 gardés — axis_crossing 8791, clubhouse_clear 4923, clubhouse_return 52
- seed 6 :
  - profondeur 5 : 17568 essais, 50 acceptés, 41 gardés — axis_crossing 9715, bounds 14617, fairway_gap 14867
  - profondeur 6 : 11232 essais, 20 acceptés, 19 gardés — axis_crossing 8029, bounds 5208, fairway_gap 11107
  - profondeur 7 : 5328 essais, 0 acceptés, 0 gardés — axis_crossing 4471, bounds 2363, fairway_gap 5328
- seed 7 :
  - profondeur 7 : 18720 essais, 34 acceptés, 28 gardés — axis_crossing 14810, bounds 2249, fairway_gap 18685
  - profondeur 8 : 5184 essais, 95 acceptés, 72 gardés — axis_crossing 4154, bounds 214, clubhouse_clear 41
  - profondeur 9 : 10368 essais, 10 acceptés, 9 gardés — axis_crossing 8528, clubhouse_clear 4526, clubhouse_return 133
- seed 8 :
  - profondeur 6 : 18720 essais, 152 acceptés, 72 gardés — axis_crossing 13500, bounds 7496, fairway_gap 18014
  - profondeur 7 : 13248 essais, 11 acceptés, 11 gardés — axis_crossing 11159, bounds 4944, fairway_gap 13236
  - profondeur 8 : 1584 essais, 0 acceptés, 0 gardés — axis_crossing 1383, fairway_gap 1584, parallel_stack 758
- seed 9 :
  - profondeur 6 : 10512 essais, 49 acceptés, 47 gardés — axis_crossing 7954, bounds 4675, fairway_gap 10200
  - profondeur 7 : 9936 essais, 1 acceptés, 1 gardés — axis_crossing 9122, bounds 1570, fairway_gap 9935
  - profondeur 8 : 144 essais, 0 acceptés, 0 gardés — axis_crossing 132, bounds 15, fairway_gap 144
- seed 10 :
  - profondeur 7 : 10800 essais, 28 acceptés, 27 gardés — axis_crossing 9844, bounds 1732, fairway_gap 10772
  - profondeur 8 : 3888 essais, 37 acceptés, 30 gardés — axis_crossing 3252, bounds 99, clubhouse_clear 154
  - profondeur 9 : 4320 essais, 2 acceptés, 2 gardés — axis_crossing 3931, clubhouse_clear 1762, clubhouse_return 172

## Observations

- Décision utilisateur (étape 1) : back_clubhouse_max=100.0 (défaut 50.0, soit 300 m au lieu de 150 m, 1 bloc = 3 m) + back_start_radii=(44.0, 48.0, 64.0, 80.0, 96.0) (défaut (44.0, 48.0)) -- front inchangé (clubhouse_max=50, start_radii=(24.0, 36.0), secteur de départ inchangé), green 9 inchangé.
- Comparaison à la config B (``experiments/bean_paving/output/benchmark_course18_400_bounded_1_10/report.json``) : B obtient 5/10 complet, 5/10 validé indépendamment, temps total 2009.0s (16 process) ; ce run (back_clubhouse_max=100.0, back_start_radii étendus) obtient 6/10 complet, 6/10 validé indépendamment, temps total 860.9s (16 process). Temps par seed -- seed 1 : 655.6s (B) -> 687.3s (back far); seed 2 : 614.2s (B) -> 789.9s (back far); seed 3 : 682.0s (B) -> 837.5s (back far); seed 4 : 2008.8s (B) -> 564.6s (back far); seed 5 : 560.0s (B) -> 860.7s (back far); seed 6 : 525.0s (B) -> 420.7s (back far); seed 7 : 767.3s (B) -> 700.3s (back far); seed 8 : 1174.2s (B) -> 592.0s (back far); seed 9 : 700.2s (B) -> 425.9s (back far); seed 10 : 765.3s (B) -> 701.6s (back far).
- Composition DIFFÉRENTE, pas un sur-ensemble strict de B : seeds redevenues en échec [4, 8] (18/18 en B), seeds nouvellement résolues [5, 7, 10] (échec en B). Cause probable (vérifiée sur les seeds 4 et 8, cf. JSON bruts des deux runs) : ``solver._transform_rank`` classe les candidats du tee 10 par écart à la cible d'expansion de profondeur 1 (``_scaled_target_radius(1, ...)`` = 110 * target_radius_scale(1.0) * map_scale(400/350) ≈ 125.7 blocs pour le back) -- les rayons étendus (64/80/96) sont OBJECTIVEMENT plus proches de cette cible que les rayons historiques (44/48, écarts ~82/78 contre ~62/46/30), donc ils dominent désormais le tri AVANT la coupe du beam (largeur 72, inchangée) à la profondeur 1. Sur les seeds 4 et 8, ceci écarte du beam les départs à 44/48 qui portaient auparavant la seule trajectoire gagnante (vérifié : seed 4 passe de tee10=44 (succès en B) à tee10=96 (échec, bloqué profondeur 8) ; seed 8 de tee10=48 (succès) à tee10=64 (échec, bloqué profondeur 8)) -- pas une régression géométrique du plafond dur, une redistribution de la composition du beam dès la profondeur 1. Les seeds 5, 7 et 10 (en échec en B, résolues ici) bénéficient symétriquement de la même redistribution vers d'autres trajectoires. Le total 6/10 (vs 5/10) est donc un gain agrégé, PAS une amélioration uniforme seed par seed.
- Comparaison au benchmark séquentiel de référence (quota fixe 2/5/2, lookahead 9, clubhouse_max=50 symétrique, 0/10 complet, 0/10 validé indépendamment, 6715.7s cumulées) : ce run obtient 6/10 complet, 6/10 validé indépendamment, temps total 860.9s sur 16 process (cumulé des temps par seed 6580.3s).
