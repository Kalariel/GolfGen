# Expérience — liens praticables (seeds 1 à 5, 400×400)

- Succès (18/18) : **1/5** (baseline deadline par5 seeds 1-5 : **5/5**)
- Validation indépendante conforme : **1/5**
- Temps total (5 process en parallèle) : **2005.3s**

- Règle : chaque liaison piétonne (clubhouse<->tee1, green_k->tee_{k+1}, green9->clubhouse, clubhouse->tee10, green_k->tee_{k+1} (k=10..17), green18->clubhouse) ne doit ni croiser ni toucher le cœur fairway d'un AUTRE trou (rough autorisé). Longueur green->tee élargie de [12, 45] à [12, 80] blocs. Reste = config A (deadline par5, trou 7 max).

| Seed | Résultat | Front | Back | Temps | Tee1→club | Green9→club | Tee10→club | Green18→club | Liaison max | Liaison moy. | link_blocked | Indép. | Base (par5-deadline) |
|---:|:---:|:---:|:---:|---:|---:|---:|---:|---:|---:|---:|---:|:---:|:---:|
| 1 | échec | 9/9 | 8/9 | 772.4s | 36.0 | 25.3 | 44.0 | 122.7 | 80.0 | 49.5 | 68811 | KO | OK 519.9s |
| 2 | échec | 9/9 | 6/9 | 469.2s | 36.0 | 19.2 | 80.0 | 180.3 | 65.0 | 49.2 | 63058 | KO | OK 802.6s |
| 3 | échec | 9/9 | 8/9 | 953.8s | 36.0 | 21.7 | 44.0 | 126.9 | 80.0 | 51.5 | 93487 | KO | OK 824.7s |
| 4 | échec | 9/9 | 8/9 | 1216.9s | 36.0 | 19.1 | 96.0 | 126.4 | 80.0 | 44.3 | 103022 | KO | OK 568.2s |
| 5 | OK | 9/9 | 9/9 | 2005.2s | 36.0 | 20.4 | 44.0 | 21.1 | 80.0 | 51.0 | 97468 | OK | OK 793.1s |

## Comparaison seed par seed à la baseline deadline par5 (5/5)

- seed 1 : échec (DIFFÉRENT de la baseline OK), temps 772.4s vs 519.9s (baseline), delta +252.5s.
- seed 2 : échec (DIFFÉRENT de la baseline OK), temps 469.2s vs 802.6s (baseline), delta -333.4s.
- seed 3 : échec (DIFFÉRENT de la baseline OK), temps 953.8s vs 824.7s (baseline), delta +129.1s.
- seed 4 : échec (DIFFÉRENT de la baseline OK), temps 1216.9s vs 568.2s (baseline), delta +648.7s.
- seed 5 : OK (identique de la baseline OK), temps 2005.2s vs 793.1s (baseline), delta +1212.1s.

## Pars par nine (ordre de jeu) -- trous 9 et 18 en gras

- seed 1 : front 3-4-3-3-5-4-4-4-**4** / back 3-4-4-4-4-5-4-**5**
- seed 2 : front 3-4-4-5-3-3-4-4-**4** / back 3-5-4-4-5-**5**
- seed 3 : front 3-4-4-4-4-4-5-3-**3** / back 3-4-4-4-4-5-4-**5**
- seed 4 : front 3-4-4-4-5-4-4-3-**3** / back 3-5-4-5-4-4-4-**4**
- seed 5 : front 3-4-5-4-3-4-4-3-**4** / back 4-5-4-4-5-5-4-4-**3**

## Par5 — trous de pose (play order, 1-indexé)

- seed 1 : front par5 aux trous [5] / back par5 aux trous [6, 8]
- seed 2 : front par5 aux trous [4] / back par5 aux trous [2, 5, 6]
- seed 3 : front par5 aux trous [7] / back par5 aux trous [6, 8]
- seed 4 : front par5 aux trous [5] / back par5 aux trous [2, 4]
- seed 5 : front par5 aux trous [3] / back par5 aux trous [2, 5, 6]

## Rejets cumulés

- `axis_crossing` : 677366
- `bounds` : 401710
- `clubhouse_clear` : 72664
- `clubhouse_departure` : 8446
- `clubhouse_return` : 6520
- `fairway_gap` : 900769
- `link_blocked` : 425846
- `parallel_stack` : 31986

## Back — 3 dernières profondeurs explorées (causes de rejet)

- seed 1 :
  - profondeur 7 : 12096 essais, 30 acceptés, 25 gardés — fairway_gap 12052, axis_crossing 10979, link_blocked 8677
  - profondeur 8 : 4176 essais, 7 acceptés, 7 gardés — fairway_gap 4167, axis_crossing 3477, link_blocked 2999
  - profondeur 9 : 1008 essais, 0 acceptés, 0 gardés — fairway_gap 1008, link_blocked 938, axis_crossing 932
- seed 2 :
  - profondeur 5 : 18288 essais, 19 acceptés, 18 gardés — bounds 15609, fairway_gap 14898, axis_crossing 10356
  - profondeur 6 : 5040 essais, 2 acceptés, 2 gardés — fairway_gap 4998, axis_crossing 4095, link_blocked 3377
  - profondeur 7 : 288 essais, 0 acceptés, 0 gardés — fairway_gap 288, axis_crossing 252, link_blocked 213
- seed 3 :
  - profondeur 7 : 8496 essais, 98 acceptés, 72 gardés — fairway_gap 8311, axis_crossing 6635, link_blocked 5552
  - profondeur 8 : 13392 essais, 65 acceptés, 60 gardés — fairway_gap 13315, axis_crossing 11709, link_blocked 9791
  - profondeur 9 : 8640 essais, 0 acceptés, 0 gardés — fairway_gap 8636, link_blocked 8506, axis_crossing 8385
- seed 4 :
  - profondeur 7 : 16128 essais, 107 acceptés, 72 gardés — fairway_gap 15957, axis_crossing 13842, link_blocked 8955
  - profondeur 8 : 14832 essais, 169 acceptés, 72 gardés — fairway_gap 14139, link_blocked 11353, axis_crossing 11039
  - profondeur 9 : 10368 essais, 0 acceptés, 0 gardés — fairway_gap 10368, link_blocked 10204, axis_crossing 9932
- seed 5 :
  - profondeur 7 : 19152 essais, 381 acceptés, 72 gardés — fairway_gap 18386, axis_crossing 14305, link_blocked 11321
  - profondeur 8 : 15408 essais, 553 acceptés, 72 gardés — fairway_gap 14820, axis_crossing 12111, link_blocked 8126
  - profondeur 9 : 10368 essais, 109 acceptés, 72 gardés — fairway_gap 9979, link_blocked 9167, axis_crossing 7709

## Échecs — causes dominantes

- seed 1 : front 9/9, back 8/9 — causes dominantes : fairway_gap 155354, axis_crossing 115847, bounds 76482
- seed 2 : front 9/9, back 6/9 — causes dominantes : fairway_gap 146713, axis_crossing 108534, bounds 70313
- seed 3 : front 9/9, back 8/9 — causes dominantes : fairway_gap 191763, axis_crossing 145948, link_blocked 93487
- seed 4 : front 9/9, back 8/9 — causes dominantes : fairway_gap 199398, axis_crossing 153053, link_blocked 103022
