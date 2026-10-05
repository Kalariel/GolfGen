# Expérience B — arrivée radiale (seuil 45°, seeds 1 à 5, 400×400)

- Succès (18/18) : **4/5** (baseline back-far seeds 1-5 : **4/5**)
- Validation indépendante conforme : **4/5**
- Temps total (10 process, 2 expériences en parallèle) : **954.3s**

- Seuil : le dernier segment de l'axe des trous 9 et 18 doit pointer vers le clubhouse à moins de **45°** (angle entre ce segment et la direction de son point de départ vers le clubhouse -- mirroir du départ du trou 1). Reste = baseline back-far.

| Seed | Résultat | Front | Back | Temps | Tee1→club | Green9→club | Tee10→club | Green18→club | Angle trou 9 | Angle trou 18 | Indép. | Base (back-far) |
|---:|:---:|:---:|:---:|---:|---:|---:|---:|---:|---:|---:|:---:|:---:|
| 1 | OK | 9/9 | 9/9 | 527.5s | 36.0 | 23.0 | 96.0 | 35.0 | 8.1° | 7.8° | OK | OK 687.3s |
| 2 | OK | 9/9 | 9/9 | 903.7s | 36.0 | 18.9 | 44.0 | 34.4 | 11.3° | 31.3° | OK | OK 789.9s |
| 3 | OK | 9/9 | 9/9 | 911.0s | 36.0 | 19.2 | 80.0 | 29.1 | 12.0° | 20.1° | OK | OK 837.5s |
| 4 | échec | 9/9 | 7/9 | 664.8s | 36.0 | 27.9 | 96.0 | 150.0 | 8.6° | 123.9° | KO | échec 564.6s |
| 5 | OK | 9/9 | 9/9 | 954.2s | 36.0 | 20.4 | 96.0 | 35.9 | 0.1° | 31.4° | OK | OK 860.7s |

## Comparaison seed par seed à la baseline back-far

- seed 1 : OK (identique de la baseline OK), temps 527.5s vs 687.3s (baseline), delta -159.8s.
- seed 2 : OK (identique de la baseline OK), temps 903.7s vs 789.9s (baseline), delta +113.8s.
- seed 3 : OK (identique de la baseline OK), temps 911.0s vs 837.5s (baseline), delta +73.4s.
- seed 4 : échec (identique de la baseline échec), temps 664.8s vs 564.6s (baseline), delta +100.2s.
- seed 5 : OK (identique de la baseline OK), temps 954.2s vs 860.7s (baseline), delta +93.6s.

## Pars par nine (ordre de jeu) -- trous 9 et 18 en gras

- seed 1 : front 3-4-4-3-5-3-4-4-**4** / back 3-5-4-4-5-4-4-5-**4**
- seed 2 : front 3-4-4-4-3-4-5-4-**3** / back 4-4-4-4-5-5-3-5-**4**
- seed 3 : front 3-4-4-3-5-4-4-4-**3** / back 3-5-4-5-4-4-5-4-**4**
- seed 4 : front 3-4-4-4-4-3-3-5-**4** / back 3-5-5-4-4-4-**4**
- seed 5 : front 3-4-4-5-3-3-4-4-**4** / back 3-4-4-4-4-4-5-5-**5**

## Par5 — trous de pose (play order, 1-indexé)

- seed 1 : front par5 aux trous [5] / back par5 aux trous [2, 5, 8]
- seed 2 : front par5 aux trous [7] / back par5 aux trous [5, 6, 8]
- seed 3 : front par5 aux trous [5] / back par5 aux trous [2, 4, 7]
- seed 4 : front par5 aux trous [8] / back par5 aux trous [2, 3]
- seed 5 : front par5 aux trous [4] / back par5 aux trous [7, 8, 9]

## Rejets cumulés

- `axis_crossing` : 695293
- `bounds` : 371737
- `clubhouse_clear` : 45591
- `clubhouse_departure` : 8366
- `clubhouse_return` : 20063
- `fairway_gap` : 984451
- `parallel_stack` : 54337
- `radial_arrival` : 5073

## Back — 3 dernières profondeurs explorées (causes de rejet)

- seed 1 :
  - profondeur 7 : 17712 essais, 11 acceptés, 11 gardés — fairway_gap 17700, axis_crossing 13147, bounds 4888
  - profondeur 8 : 3168 essais, 24 acceptés, 24 gardés — fairway_gap 3142, axis_crossing 2726, parallel_stack 343
  - profondeur 9 : 3456 essais, 17 acceptés, 15 gardés — fairway_gap 3203, axis_crossing 2277, clubhouse_clear 1805
- seed 2 :
  - profondeur 7 : 16848 essais, 354 acceptés, 72 gardés — fairway_gap 16463, axis_crossing 12287, bounds 3914
  - profondeur 8 : 15696 essais, 222 acceptés, 72 gardés — fairway_gap 15471, axis_crossing 13288, bounds 585
  - profondeur 9 : 10368 essais, 468 acceptés, 72 gardés — fairway_gap 8878, axis_crossing 5967, clubhouse_clear 5217
- seed 3 :
  - profondeur 7 : 19728 essais, 283 acceptés, 72 gardés — fairway_gap 19445, axis_crossing 15919, bounds 4158
  - profondeur 8 : 13824 essais, 225 acceptés, 72 gardés — fairway_gap 13597, axis_crossing 11240, parallel_stack 705
  - profondeur 9 : 10368 essais, 11 acceptés, 11 gardés — fairway_gap 7864, axis_crossing 6892, clubhouse_clear 4335
- seed 4 :
  - profondeur 6 : 18000 essais, 49 acceptés, 47 gardés — fairway_gap 17527, axis_crossing 12899, bounds 7650
  - profondeur 7 : 10512 essais, 1 acceptés, 1 gardés — fairway_gap 10510, axis_crossing 8720, bounds 2559
  - profondeur 8 : 288 essais, 0 acceptés, 0 gardés — fairway_gap 288, axis_crossing 255, parallel_stack 57
- seed 5 :
  - profondeur 7 : 15408 essais, 92 acceptés, 72 gardés — fairway_gap 15316, axis_crossing 12467, bounds 5186
  - profondeur 8 : 10800 essais, 351 acceptés, 72 gardés — fairway_gap 10449, axis_crossing 7303, parallel_stack 279
  - profondeur 9 : 10368 essais, 42 acceptés, 31 gardés — fairway_gap 9361, axis_crossing 8089, clubhouse_clear 4827

## Échecs — causes dominantes

- seed 4 : front 9/9, back 7/9 — causes dominantes : fairway_gap 176214, axis_crossing 122996, bounds 72142
