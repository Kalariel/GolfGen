# Expérience 1 — départs aléatoires du tee (seeds 1 à 5, 400×400)

- Succès (18/18) : **4/5** (baseline back-far seeds 1-5 : **4/5**)
- Validation indépendante conforme : **4/5**
- Temps total (10 process, 2 expériences en parallèle) : **1209.2s**

- Tirage : front 10 positions, rayon (24.0, 48.0), cercle complet ; back 60 positions, rayon (44.0, 96.0), cercle complet. Déterministe par (seed, nine).

| Seed | Résultat | Front | Back | Temps | Tee1→club | Green9→club | Tee10→club | Green18→club | Pile max | Indép. | Base (back-far) |
|---:|:---:|:---:|:---:|---:|---:|---:|---:|---:|---:|:---:|:---:|
| 1 | OK | 9/9 | 9/9 | 1102.0s | 38.0 | 27.2 | 84.0 | 35.2 | 3 | OK | OK 687.3s |
| 2 | OK | 9/9 | 9/9 | 1036.5s | 35.6 | 25.8 | 45.2 | 34.7 | 2 | OK | OK 789.9s |
| 3 | OK | 9/9 | 9/9 | 785.0s | 29.8 | 23.0 | 87.3 | 32.2 | 3 | OK | OK 837.5s |
| 4 | échec | 9/9 | 8/9 | 611.0s | 33.3 | 25.8 | 81.0 | 126.0 | 3 | KO | échec 564.6s |
| 5 | OK | 9/9 | 9/9 | 1143.8s | 30.6 | 22.6 | 52.6 | 32.4 | 3 | OK | OK 860.7s |

## Comparaison seed par seed à la baseline back-far

- seed 1 : OK (identique de la baseline OK), temps 1102.0s vs 687.3s (baseline), delta +414.7s.
- seed 2 : OK (identique de la baseline OK), temps 1036.5s vs 789.9s (baseline), delta +246.6s.
- seed 3 : OK (identique de la baseline OK), temps 785.0s vs 837.5s (baseline), delta -52.6s.
- seed 4 : échec (identique de la baseline échec), temps 611.0s vs 564.6s (baseline), delta +46.4s.
- seed 5 : OK (identique de la baseline OK), temps 1143.8s vs 860.7s (baseline), delta +283.1s.

## Pars par nine (ordre de jeu)

- seed 1 : front 3-4-4-4-4-4-3-5-3 / back 3-4-4-5-4-4-5-5-4
- seed 2 : front 3-4-4-3-4-4-5-4-3 / back 4-4-4-4-5-5-3-5-4
- seed 3 : front 3-4-5-3-3-4-4-4-4 / back 3-4-4-5-4-4-5-4-5
- seed 4 : front 3-4-4-3-4-4-3-5-4 / back 3-5-4-5-4-4-4-4
- seed 5 : front 4-4-4-3-3-5-4-4-3 / back 4-5-5-4-4-4-4-5-3

## Rejets cumulés

- `axis_crossing` : 718332
- `bounds` : 375617
- `clubhouse_clear` : 50138
- `clubhouse_departure` : 8274
- `clubhouse_return` : 19391
- `fairway_gap` : 1024557
- `parallel_stack` : 68939

## Back — 3 dernières profondeurs explorées (causes de rejet)

- seed 1 :
  - profondeur 7 : 19728 essais, 467 acceptés, 72 gardés — fairway_gap 19261, axis_crossing 14822, bounds 4993
  - profondeur 8 : 15552 essais, 450 acceptés, 72 gardés — fairway_gap 15065, axis_crossing 12177, parallel_stack 3049
  - profondeur 9 : 10368 essais, 114 acceptés, 72 gardés — fairway_gap 10189, axis_crossing 8135, clubhouse_clear 5214
- seed 2 :
  - profondeur 7 : 18432 essais, 546 acceptés, 72 gardés — fairway_gap 17877, axis_crossing 12895, bounds 3214
  - profondeur 8 : 16992 essais, 676 acceptés, 72 gardés — fairway_gap 16316, axis_crossing 13311, bounds 601
  - profondeur 9 : 10368 essais, 139 acceptés, 72 gardés — fairway_gap 9989, axis_crossing 6961, clubhouse_clear 4995
- seed 3 :
  - profondeur 7 : 14688 essais, 64 acceptés, 41 gardés — fairway_gap 14624, axis_crossing 12063, bounds 1933
  - profondeur 8 : 6336 essais, 94 acceptés, 72 gardés — fairway_gap 6242, axis_crossing 4883, parallel_stack 397
  - profondeur 9 : 10368 essais, 88 acceptés, 70 gardés — fairway_gap 10128, axis_crossing 8453, clubhouse_clear 4992
- seed 4 :
  - profondeur 7 : 15696 essais, 27 acceptés, 22 gardés — fairway_gap 15649, axis_crossing 12168, parallel_stack 3728
  - profondeur 8 : 5760 essais, 15 acceptés, 15 gardés — fairway_gap 5744, axis_crossing 5249, parallel_stack 2233
  - profondeur 9 : 2160 essais, 0 acceptés, 0 gardés — fairway_gap 2160, axis_crossing 1872, clubhouse_clear 1090
- seed 5 :
  - profondeur 7 : 19152 essais, 768 acceptés, 72 gardés — fairway_gap 18030, axis_crossing 12302, bounds 3822
  - profondeur 8 : 16560 essais, 436 acceptés, 72 gardés — fairway_gap 16000, axis_crossing 11805, parallel_stack 2506
  - profondeur 9 : 10368 essais, 87 acceptés, 38 gardés — fairway_gap 10138, axis_crossing 8034, clubhouse_clear 4687

## Échecs — causes dominantes

- seed 4 : front 9/9, back 8/9 — causes dominantes : fairway_gap 186926, axis_crossing 131000, bounds 70605
