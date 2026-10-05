# Expérience 2 — disque d'exclusion clubhouse total 25 blocs (seeds 1 à 5, 400×400)

- Succès (18/18) : **0/5** (baseline back-far seeds 1-5 : **4/5**)
- Validation indépendante conforme : **0/5**
- Temps total (10 process, 2 expériences en parallèle) : **1209.2s**

- Disque : rayon **25.0** autour du clubhouse, empreinte entière (cœur ET rough) interdite dedans. Conséquences : front start_radii=(40.0, 48.0) (défaut (24.0, 36.0)), front clubhouse_max=60.0 (défaut 50.0), cible profondeur 9 élargie à max(cible actuelle, 25.0 + 15) pour les deux nines. Back inchangé (baseline back-far).

| Seed | Résultat | Front | Back | Temps | Tee1→club | Green9→club | Tee10→club | Green18→club | Pile max | Indép. | Base (back-far) |
|---:|:---:|:---:|:---:|---:|---:|---:|---:|---:|---:|:---:|:---:|
| 1 | échec | 9/9 | 8/9 | 883.4s | 40.0 | 56.2 | 80.0 | 119.4 | 3 | KO | OK 687.3s |
| 2 | échec | 9/9 | 6/9 | 866.9s | 40.0 | 40.6 | 80.0 | 182.8 | 2 | KO | OK 789.9s |
| 3 | échec | 9/9 | 8/9 | 1157.5s | 48.0 | 55.3 | 64.0 | 128.3 | 2 | KO | OK 837.5s |
| 4 | échec | 9/9 | 8/9 | 1092.8s | 48.0 | 40.7 | 96.0 | 113.1 | 3 | KO | échec 564.6s |
| 5 | échec | 9/9 | 8/9 | 1209.1s | 48.0 | 44.1 | 44.0 | 124.5 | 3 | KO | OK 860.7s |

## Comparaison seed par seed à la baseline back-far

- seed 1 : échec (DIFFÉRENT de la baseline OK), temps 883.4s vs 687.3s (baseline), delta +196.1s.
- seed 2 : échec (DIFFÉRENT de la baseline OK), temps 866.9s vs 789.9s (baseline), delta +77.1s.
- seed 3 : échec (DIFFÉRENT de la baseline OK), temps 1157.5s vs 837.5s (baseline), delta +320.0s.
- seed 4 : échec (identique de la baseline échec), temps 1092.8s vs 564.6s (baseline), delta +528.2s.
- seed 5 : échec (DIFFÉRENT de la baseline OK), temps 1209.1s vs 860.7s (baseline), delta +348.4s.

## Pars par nine (ordre de jeu)

- seed 1 : front 3-4-4-3-4-3-4-4-5 / back 3-5-4-4-4-4-5-4
- seed 2 : front 3-4-4-4-3-3-5-4-4 / back 3-4-4-4-4-4
- seed 3 : front 3-4-4-4-3-4-4-3-5 / back 3-4-5-5-4-4-4-4
- seed 4 : front 3-4-4-3-4-3-4-5-4 / back 3-4-5-4-5-4-4-4
- seed 5 : front 3-4-4-4-4-3-3-5-4 / back 4-5-4-5-4-3-4-4

## Rejets cumulés

- `axis_crossing` : 670039
- `bounds` : 363389
- `clubhouse_block` : 73848
- `clubhouse_clear` : 42111
- `clubhouse_departure` : 8458
- `clubhouse_return` : 13098
- `fairway_gap` : 949445
- `parallel_stack` : 71987
- dont `clubhouse_block` (disque 25.0) : **73848** rejets cumulés sur les 5 seeds (nouvelle règle)

## Back — 3 dernières profondeurs explorées (causes de rejet)

- seed 1 :
  - profondeur 7 : 14256 essais, 182 acceptés, 72 gardés — fairway_gap 14073, axis_crossing 10761, parallel_stack 3369
  - profondeur 8 : 14256 essais, 12 acceptés, 10 gardés — fairway_gap 14239, axis_crossing 12341, parallel_stack 5381
  - profondeur 9 : 1440 essais, 0 acceptés, 0 gardés — fairway_gap 1440, axis_crossing 1401, clubhouse_block 1134
- seed 2 :
  - profondeur 5 : 17856 essais, 264 acceptés, 72 gardés — bounds 15619, fairway_gap 13827, axis_crossing 9406
  - profondeur 6 : 18144 essais, 290 acceptés, 72 gardés — fairway_gap 16966, axis_crossing 11781, bounds 7843
  - profondeur 7 : 15552 essais, 0 acceptés, 0 gardés — fairway_gap 15552, axis_crossing 13202, bounds 3262
- seed 3 :
  - profondeur 7 : 15552 essais, 410 acceptés, 72 gardés — fairway_gap 15008, axis_crossing 11490, bounds 3408
  - profondeur 8 : 13824 essais, 47 acceptés, 44 gardés — fairway_gap 13776, axis_crossing 11141, parallel_stack 926
  - profondeur 9 : 6336 essais, 0 acceptés, 0 gardés — fairway_gap 6277, clubhouse_block 6026, axis_crossing 5963
- seed 4 :
  - profondeur 7 : 18576 essais, 7 acceptés, 6 gardés — fairway_gap 18565, axis_crossing 14328, bounds 5291
  - profondeur 8 : 1584 essais, 6 acceptés, 6 gardés — fairway_gap 1577, axis_crossing 1313, parallel_stack 236
  - profondeur 9 : 864 essais, 0 acceptés, 0 gardés — fairway_gap 804, clubhouse_block 741, axis_crossing 597
- seed 5 :
  - profondeur 7 : 19008 essais, 193 acceptés, 72 gardés — fairway_gap 18813, axis_crossing 13873, bounds 5749
  - profondeur 8 : 17424 essais, 226 acceptés, 72 gardés — fairway_gap 17186, axis_crossing 13860, parallel_stack 4320
  - profondeur 9 : 10368 essais, 0 acceptés, 0 gardés — fairway_gap 10303, axis_crossing 9513, clubhouse_block 9444

## Échecs — causes dominantes

- seed 1 : front 9/9, back 8/9 — causes dominantes : fairway_gap 187413, axis_crossing 134124, bounds 72242
- seed 2 : front 9/9, back 6/9 — causes dominantes : fairway_gap 173630, axis_crossing 122452, bounds 70628
- seed 3 : front 9/9, back 8/9 — causes dominantes : fairway_gap 189339, axis_crossing 134569, bounds 69470
- seed 4 : front 9/9, back 8/9 — causes dominantes : fairway_gap 177184, axis_crossing 122541, bounds 70343
- seed 5 : front 9/9, back 8/9 — causes dominantes : fairway_gap 221879, axis_crossing 156353, bounds 80706
