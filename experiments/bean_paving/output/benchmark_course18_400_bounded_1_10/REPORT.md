# Benchmark parcours 18 trous — seeds 1 à 10 (400×400, rough partagé)

- Succès (18/18) : **5/10**
- Validation indépendante conforme : **5/10**
- Doublons exacts normalisés : **0**
- Quasi-doublons (similarité ≥ 85 %) : **0**
- Temps total (16 process) : **2009.0s**

| Seed | Résultat | Front | Back | Temps | Essais | Empreinte | Pile max | Indép. |
|---:|:---:|:---:|:---:|---:|---:|---:|---:|:---:|
| 1 | OK | 9/9 | 9/9 | 655.6s | 279666 | 43.3% | 2 | OK |
| 2 | OK | 9/9 | 9/9 | 614.2s | 295506 | 42.4% | 2 | OK |
| 3 | OK | 9/9 | 9/9 | 682.0s | 272736 | 44.4% | 3 | OK |
| 4 | OK | 9/9 | 9/9 | 2008.8s | 302706 | 42.2% | 3 | OK |
| 5 | échec | 9/9 | 8/9 | 560.0s | 287154 | 39.9% | 3 | KO |
| 6 | échec | 9/9 | 6/9 | 525.0s | 269154 | 35.8% | 2 | KO |
| 7 | échec | 9/9 | 8/9 | 767.3s | 275058 | 40.6% | 3 | KO |
| 8 | OK | 9/9 | 9/9 | 1174.2s | 271602 | 45.4% | 3 | OK |
| 9 | échec | 9/9 | 8/9 | 700.2s | 257346 | 38.9% | 3 | KO |
| 10 | échec | 9/9 | 6/9 | 765.3s | 273762 | 33.8% | 2 | KO |

## Pars par nine (ordre de jeu)

- seed 1 : front 3-4-4-3-5-3-4-4-4 / back 3-4-4-5-4-4-5-5-4
- seed 2 : front 3-4-4-4-3-4-5-4-3 / back 4-4-4-4-3-4-5-5-5
- seed 3 : front 3-4-4-3-5-4-4-4-3 / back 3-4-4-4-5-5-4-5-4
- seed 4 : front 3-4-4-4-4-3-3-5-4 / back 4-5-5-5-4-4-4-4-3
- seed 5 : front 3-4-4-5-3-3-4-4-4 / back 4-4-5-5-3-4-4-4
- seed 6 : front 3-4-4-4-3-3-5-4-4 / back 4-4-4-4-3-4
- seed 7 : front 3-4-4-3-5-3-4-4-4 / back 3-4-4-4-4-4-5-5
- seed 8 : front 3-4-4-4-3-4-4-5-3 / back 4-5-4-4-5-4-5-4-3
- seed 9 : front 3-4-4-5-4-3-4-4-3 / back 3-4-4-4-4-4-5-5
- seed 10 : front 3-4-4-4-3-4-5-4-3 / back 4-4-4-4-4-3

## Rejets cumulés

- `axis_crossing` : 1411425
- `bounds` : 764543
- `clubhouse_clear` : 78678
- `clubhouse_departure` : 15478
- `clubhouse_return` : 68620
- `fairway_gap` : 2000250
- `parallel_stack` : 111553

## Échecs — meilleur état et causes dominantes

- seed 5 : front 9/9, back 8/9 — causes dominantes : fairway_gap 203933, axis_crossing 143890, bounds 84046
- seed 6 : front 9/9, back 6/9 — causes dominantes : fairway_gap 194711, axis_crossing 136177, bounds 81624
- seed 7 : front 9/9, back 8/9 — causes dominantes : fairway_gap 196224, axis_crossing 139707, bounds 68572
- seed 9 : front 9/9, back 8/9 — causes dominantes : fairway_gap 184071, axis_crossing 133443, bounds 66251
- seed 10 : front 9/9, back 6/9 — causes dominantes : fairway_gap 195983, axis_crossing 136156, bounds 80382

## Back — 3 dernières profondeurs explorées (causes de rejet)

- seed 1 :
  - profondeur 7 : 15552 essais, 487 acceptés, 72 gardés — fairway_gap 15064, axis_crossing 10616, bounds 1496
  - profondeur 8 : 15552 essais, 132 acceptés, 72 gardés — fairway_gap 15417, axis_crossing 13218, parallel_stack 1370
  - profondeur 9 : 10368 essais, 6 acceptés, 5 gardés — fairway_gap 6331, axis_crossing 4882, clubhouse_return 4019
- seed 2 :
  - profondeur 7 : 18576 essais, 50 acceptés, 41 gardés — fairway_gap 18525, axis_crossing 15069, bounds 4762
  - profondeur 8 : 9936 essais, 170 acceptés, 72 gardés — fairway_gap 9752, axis_crossing 7545, bounds 598
  - profondeur 9 : 10368 essais, 2 acceptés, 2 gardés — fairway_gap 6091, axis_crossing 5654, clubhouse_return 4271
- seed 3 :
  - profondeur 7 : 14544 essais, 241 acceptés, 72 gardés — fairway_gap 14303, axis_crossing 10877, parallel_stack 1468
  - profondeur 8 : 13824 essais, 239 acceptés, 72 gardés — fairway_gap 13576, axis_crossing 10913, parallel_stack 1484
  - profondeur 9 : 10368 essais, 86 acceptés, 72 gardés — fairway_gap 5849, clubhouse_return 4258, axis_crossing 4234
- seed 4 :
  - profondeur 7 : 19008 essais, 117 acceptés, 72 gardés — fairway_gap 18842, axis_crossing 13733, bounds 5157
  - profondeur 8 : 16560 essais, 1876 acceptés, 72 gardés — fairway_gap 14673, axis_crossing 11292, parallel_stack 943
  - profondeur 9 : 10368 essais, 34 acceptés, 30 gardés — fairway_gap 7880, axis_crossing 6046, clubhouse_clear 3660
- seed 5 :
  - profondeur 7 : 20304 essais, 20 acceptés, 20 gardés — fairway_gap 20268, axis_crossing 16752, bounds 6917
  - profondeur 8 : 4320 essais, 39 acceptés, 28 gardés — fairway_gap 4281, axis_crossing 3706, parallel_stack 820
  - profondeur 9 : 4032 essais, 0 acceptés, 0 gardés — clubhouse_return 2080, fairway_gap 1949, axis_crossing 1685
- seed 6 :
  - profondeur 5 : 23472 essais, 383 acceptés, 72 gardés — bounds 19985, fairway_gap 18747, axis_crossing 12931
  - profondeur 6 : 19296 essais, 141 acceptés, 72 gardés — fairway_gap 18829, axis_crossing 13199, bounds 7950
  - profondeur 7 : 15264 essais, 0 acceptés, 0 gardés — fairway_gap 15264, axis_crossing 13184, bounds 5734
- seed 7 :
  - profondeur 7 : 15696 essais, 381 acceptés, 72 gardés — fairway_gap 15315, axis_crossing 11436, parallel_stack 3363
  - profondeur 8 : 14832 essais, 61 acceptés, 53 gardés — fairway_gap 14771, axis_crossing 13656, bounds 227
  - profondeur 9 : 7632 essais, 0 acceptés, 0 gardés — clubhouse_return 6567, fairway_gap 1065, axis_crossing 883
- seed 8 :
  - profondeur 7 : 20304 essais, 1312 acceptés, 72 gardés — fairway_gap 18920, axis_crossing 14133, bounds 6264
  - profondeur 8 : 16560 essais, 598 acceptés, 72 gardés — fairway_gap 15953, axis_crossing 11812, bounds 1070
  - profondeur 9 : 10368 essais, 20 acceptés, 10 gardés — fairway_gap 7894, axis_crossing 6959, clubhouse_clear 3683
- seed 9 :
  - profondeur 7 : 15264 essais, 39 acceptés, 37 gardés — fairway_gap 15225, axis_crossing 13815, bounds 1823
  - profondeur 8 : 5328 essais, 5 acceptés, 5 gardés — fairway_gap 5323, axis_crossing 4985, bounds 435
  - profondeur 9 : 720 essais, 0 acceptés, 0 gardés — clubhouse_return 657, fairway_gap 63, axis_crossing 57
- seed 10 :
  - profondeur 5 : 23328 essais, 763 acceptés, 72 gardés — bounds 18751, fairway_gap 18520, axis_crossing 11883
  - profondeur 6 : 22176 essais, 611 acceptés, 72 gardés — fairway_gap 21037, axis_crossing 14820, bounds 7686
  - profondeur 7 : 17856 essais, 0 acceptés, 0 gardés — fairway_gap 17856, axis_crossing 15737, bounds 5991

## Observations

- Déterminisme (seeds déjà résolues en B à 4 seeds, output/closure_ab_400/B) : seed 1 : identique (déterministe) — pars front/back antérieurs (3-4-4-3-5-3-4-4-4 / 3-4-4-5-4-4-5-5-4) vs ce run (3-4-4-3-5-3-4-4-4 / 3-4-4-5-4-4-5-5-4).
- Déterminisme (seeds déjà résolues en B à 4 seeds, output/closure_ab_400/B) : seed 2 : identique (déterministe) — pars front/back antérieurs (3-4-4-4-3-4-5-4-3 / 4-4-4-4-3-4-5-5-5) vs ce run (3-4-4-4-3-4-5-4-3 / 4-4-4-4-3-4-5-5-5).
- Déterminisme (seeds déjà résolues en B à 4 seeds, output/closure_ab_400/B) : seed 8 : identique (déterministe) — pars front/back antérieurs (3-4-4-4-3-4-4-5-3 / 4-5-4-4-5-4-5-4-3) vs ce run (3-4-4-4-3-4-4-5-3 / 4-5-4-4-5-4-5-4-3).
- Comparaison au benchmark séquentiel de référence (quota fixe 2/5/2, lookahead 9, 0/10 complet, 0/10 validé indépendamment, 6715.7s cumulées) : ce run (quota borné + lookahead 7) obtient 5/10 complet, 5/10 validé indépendamment, temps total 2009.0s sur 16 process (cumulé des temps par seed 8452.6s).
