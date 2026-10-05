# Expérience A — deadline par5 (trou 7 max, seeds 1 à 5, 400×400)

- Succès (18/18) : **5/5** (baseline back-far seeds 1-5 : **4/5**)
- Validation indépendante conforme : **5/5**
- Temps total (10 process, 2 expériences en parallèle) : **954.3s**

- Deadline : le minimum de par5 (``par5_bounds[0]``, 1 par défaut) doit être atteint au plus tard au trou **7** sur les deux nines ; au-delà, seul un par5 EXCÉDENTAIRE (au-dessus du minimum) reste permis. Reste = baseline back-far.

| Seed | Résultat | Front | Back | Temps | Tee1→club | Green9→club | Tee10→club | Green18→club | Angle trou 9 | Angle trou 18 | Indép. | Base (back-far) |
|---:|:---:|:---:|:---:|---:|---:|---:|---:|---:|---:|---:|:---:|:---:|
| 1 | OK | 9/9 | 9/9 | 519.9s | 36.0 | 23.0 | 96.0 | 35.0 | 8.1° | 7.8° | OK | OK 687.3s |
| 2 | OK | 9/9 | 9/9 | 802.6s | 36.0 | 21.2 | 64.0 | 35.1 | 20.8° | 11.8° | OK | OK 789.9s |
| 3 | OK | 9/9 | 9/9 | 824.7s | 36.0 | 29.0 | 96.0 | 35.6 | 9.2° | 21.8° | OK | OK 837.5s |
| 4 | OK | 9/9 | 9/9 | 568.2s | 36.0 | 28.6 | 96.0 | 30.2 | 34.3° | 22.0° | OK | échec 564.6s |
| 5 | OK | 9/9 | 9/9 | 793.1s | 36.0 | 20.4 | 96.0 | 35.9 | 0.1° | 31.4° | OK | OK 860.7s |

## Comparaison seed par seed à la baseline back-far

- seed 1 : OK (identique de la baseline OK), temps 519.9s vs 687.3s (baseline), delta -167.3s.
- seed 2 : OK (identique de la baseline OK), temps 802.6s vs 789.9s (baseline), delta +12.7s.
- seed 3 : OK (identique de la baseline OK), temps 824.7s vs 837.5s (baseline), delta -12.9s.
- seed 4 : OK (DIFFÉRENT de la baseline échec), temps 568.2s vs 564.6s (baseline), delta +3.6s.
- seed 5 : OK (identique de la baseline OK), temps 793.1s vs 860.7s (baseline), delta -67.6s.

## Pars par nine (ordre de jeu) -- trous 9 et 18 en gras

- seed 1 : front 3-4-4-3-5-3-4-4-**4** / back 3-5-4-4-5-4-4-5-**4**
- seed 2 : front 3-4-4-4-3-4-5-4-**3** / back 4-4-4-4-5-5-5-3-**4**
- seed 3 : front 3-4-4-3-5-4-4-3-**4** / back 3-4-4-4-5-4-5-5-**4**
- seed 4 : front 3-4-5-3-4-3-4-4-**4** / back 3-5-4-4-4-5-4-5-**4**
- seed 5 : front 3-4-4-5-3-3-4-4-**4** / back 3-4-4-4-4-4-5-5-**5**

## Par5 — trous de pose (play order, 1-indexé)

- seed 1 : front par5 aux trous [5] / back par5 aux trous [2, 5, 8]
- seed 2 : front par5 aux trous [7] / back par5 aux trous [5, 6, 7]
- seed 3 : front par5 aux trous [5] / back par5 aux trous [5, 7, 8]
- seed 4 : front par5 aux trous [3] / back par5 aux trous [2, 6, 8]
- seed 5 : front par5 aux trous [4] / back par5 aux trous [7, 8, 9]

## Rejets cumulés

- `axis_crossing` : 704159
- `bounds` : 371822
- `clubhouse_clear` : 55683
- `clubhouse_departure` : 8478
- `clubhouse_return` : 18323
- `fairway_gap` : 996038
- `parallel_stack` : 62903

## Back — 3 dernières profondeurs explorées (causes de rejet)

- seed 1 :
  - profondeur 7 : 17712 essais, 11 acceptés, 11 gardés — fairway_gap 17700, axis_crossing 13147, bounds 4888
  - profondeur 8 : 3168 essais, 24 acceptés, 24 gardés — fairway_gap 3142, axis_crossing 2726, parallel_stack 343
  - profondeur 9 : 3456 essais, 17 acceptés, 15 gardés — fairway_gap 3362, axis_crossing 2408, clubhouse_clear 1838
- seed 2 :
  - profondeur 7 : 19008 essais, 776 acceptés, 72 gardés — fairway_gap 18201, axis_crossing 13442, bounds 4541
  - profondeur 8 : 16560 essais, 238 acceptés, 72 gardés — fairway_gap 16313, axis_crossing 13133, parallel_stack 2801
  - profondeur 9 : 10368 essais, 204 acceptés, 72 gardés — fairway_gap 9931, axis_crossing 7021, clubhouse_clear 4976
- seed 3 :
  - profondeur 7 : 17136 essais, 600 acceptés, 72 gardés — fairway_gap 16525, axis_crossing 11725, bounds 3940
  - profondeur 8 : 13824 essais, 351 acceptés, 72 gardés — fairway_gap 13420, axis_crossing 10497, parallel_stack 2306
  - profondeur 9 : 10368 essais, 131 acceptés, 72 gardés — fairway_gap 10086, axis_crossing 8275, clubhouse_clear 5118
- seed 4 :
  - profondeur 7 : 15984 essais, 8 acceptés, 8 gardés — fairway_gap 15921, axis_crossing 12287, bounds 5041
  - profondeur 8 : 1728 essais, 20 acceptés, 19 gardés — fairway_gap 1708, axis_crossing 1559, parallel_stack 240
  - profondeur 9 : 2736 essais, 27 acceptés, 26 gardés — fairway_gap 2667, axis_crossing 1938, clubhouse_clear 1446
- seed 5 :
  - profondeur 7 : 15408 essais, 92 acceptés, 72 gardés — fairway_gap 15316, axis_crossing 12467, bounds 5186
  - profondeur 8 : 10800 essais, 351 acceptés, 72 gardés — fairway_gap 10449, axis_crossing 7303, parallel_stack 279
  - profondeur 9 : 10368 essais, 50 acceptés, 39 gardés — fairway_gap 10205, axis_crossing 8791, clubhouse_clear 4923
