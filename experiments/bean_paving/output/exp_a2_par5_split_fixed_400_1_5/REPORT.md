# Expérience A'' — 2 par5 par nine, deadline trou 7 FRONT SEULE (seeds 1 à 5, 400×400)

- Succès (18/18) : **2/5** (config A -- deadline symétrique, par5 [1,3] -- seeds 1-5 : **5/5** ; config A' -- deadline + bounds (2,2) symétriques -- seeds 1-5 : **2/5**)
- Validation indépendante conforme : **2/5**
- Temps total (5 process) : **828.0s**

- Changement vs A' : ``par5_deadline=7`` posé UNIQUEMENT sur ``front_params`` (``back_params.par5_deadline=None``) et ``solve_course(bounded_quota_back=False)`` -- le back ne passe plus par ``solver._bounded_quota_filter`` (comme la config A d'origine), ``par5_bounds=(2, 2)`` reste posé sur les DEUX nines pour que le partage global 2+2=4 soit respecté. ``par3_bounds`` ``(1, 3)`` et le quota global 4/10/4 inchangés.

- RAPPEL (voir docstring du module) : un bug corrigé le 2026-10-06 faisait réutiliser TOUJOURS ``front_params.par5_bounds``/``par5_deadline`` pour contrôler le BACK aussi, rendant ``back_params.par5_deadline=None`` sans effet sur ``result.complete`` -- le premier run de cette expérience (``output/exp_a2_par5_split_400_1_5/``) a été produit avec ce bug et est INVALIDÉ. Depuis le correctif, ``back_params.par5_deadline=None`` désactive bien la vérification côté back ; seule la RECHERCHE du back (non guidée ici, contrairement à A') peut différer.

| Seed | Résultat | Front | Back | Temps | Tee1→club | Green9→club | Tee10→club | Green18→club | Par trou 9 | Par trou 18 | Indép. | Config A | Config A' |
|---:|:---:|:---:|:---:|---:|---:|---:|---:|---:|---:|---:|:---:|:---:|:---:|
| 1 | échec | 9/9 | 7/9 | 312.7s | 36.0 | 22.3 | 96.0 | 153.0 | 3 | 4 | KO | OK 519.9s | échec 309.4s |
| 2 | OK | 9/9 | 9/9 | 602.2s | 36.0 | 24.6 | 96.0 | 32.8 | 4 | 4 | OK | OK 802.6s | OK 500.2s |
| 3 | OK | 9/9 | 9/9 | 827.9s | 24.0 | 26.0 | 64.0 | 26.7 | 3 | 4 | OK | OK 824.7s | OK 442.3s |
| 4 | échec | 9/9 | 7/9 | 327.7s | 36.0 | 25.2 | 96.0 | 152.7 | 3 | 4 | KO | OK 568.2s | échec 312.1s |
| 5 | échec | 9/9 | 8/9 | 445.5s | 36.0 | 39.4 | 96.0 | 118.7 | 4 | 5 | KO | OK 793.1s | échec 312.9s |

## Comparaison seed par seed à A et A'

- seed 1 : A'' échec, par5 front [5, 7] / back [2, 3] -- A : OK, par5 front [5] / back [2, 5, 8] -- A' : échec, par5 front [5, 7] / back [2, 3]
- seed 2 : A'' OK, par5 front [3, 6] / back [4, 8] -- A : OK, par5 front [7] / back [5, 6, 7] -- A' : OK, par5 front [3, 6] / back [3, 4]
- seed 3 : A'' OK, par5 front [3, 5] / back [4, 8] -- A : OK, par5 front [5] / back [5, 7, 8] -- A' : OK, par5 front [3, 5] / back [4, 7]
- seed 4 : A'' échec, par5 front [5, 7] / back [2] -- A : OK, par5 front [3] / back [2, 6, 8] -- A' : échec, par5 front [5, 7] / back [2, 4]
- seed 5 : A'' échec, par5 front [4, 7] / back [8] -- A : OK, par5 front [4] / back [7, 8, 9] -- A' : échec, par5 front [4, 7] / back [6]

## Pars par nine (ordre de jeu) -- trous 9 et 18 en gras

- seed 1 : front 3-4-4-3-5-4-5-4-**3** / back 3-5-5-4-4-4-**4**
- seed 2 : front 3-4-5-3-3-5-4-4-**4** / back 3-4-4-5-4-4-4-5-**4**
- seed 3 : front 3-4-5-4-5-4-4-3-**3** / back 3-4-4-5-4-4-4-5-**4**
- seed 4 : front 3-4-4-4-5-4-5-3-**3** / back 3-5-4-4-4-4-**4**
- seed 5 : front 3-4-4-5-3-3-5-4-**4** / back 3-4-4-4-4-4-4-**5**

## Par5 — trous de pose (play order, 1-indexé)

- seed 1 : front par5 aux trous [5, 7] / back par5 aux trous [2, 3]
- seed 2 : front par5 aux trous [3, 6] / back par5 aux trous [4, 8]
- seed 3 : front par5 aux trous [3, 5] / back par5 aux trous [4, 8]
- seed 4 : front par5 aux trous [5, 7] / back par5 aux trous [2]
- seed 5 : front par5 aux trous [4, 7] / back par5 aux trous [8]

## Rejets cumulés

- `axis_crossing` : 599285
- `bounds` : 307864
- `clubhouse_clear` : 44032
- `clubhouse_departure` : 8440
- `clubhouse_return` : 1313
- `fairway_gap` : 844559
- `parallel_stack` : 73621

## Back — 3 dernières profondeurs explorées (causes de rejet)

- seed 1 :
  - profondeur 6 : 12528 essais, 6 acceptés, 5 gardés — axis_crossing 10923, bounds 6100, fairway_gap 12495
  - profondeur 7 : 720 essais, 2 acceptés, 2 gardés — axis_crossing 483, bounds 211, fairway_gap 718
  - profondeur 8 : 288 essais, 0 acceptés, 0 gardés — axis_crossing 235, fairway_gap 288, parallel_stack 47
- seed 2 :
  - profondeur 7 : 15552 essais, 153 acceptés, 72 gardés — axis_crossing 11903, bounds 2349, fairway_gap 15399
  - profondeur 8 : 15552 essais, 479 acceptés, 72 gardés — axis_crossing 12152, bounds 161, clubhouse_clear 8
  - profondeur 9 : 10368 essais, 193 acceptés, 72 gardés — axis_crossing 7542, clubhouse_clear 5087, fairway_gap 9873
- seed 3 :
  - profondeur 7 : 17568 essais, 136 acceptés, 72 gardés — axis_crossing 13105, bounds 5090, fairway_gap 17432
  - profondeur 8 : 15552 essais, 462 acceptés, 72 gardés — axis_crossing 11371, bounds 118, clubhouse_clear 125
  - profondeur 9 : 10368 essais, 34 acceptés, 31 gardés — axis_crossing 8541, clubhouse_clear 5122, clubhouse_return 106
- seed 4 :
  - profondeur 6 : 9936 essais, 29 acceptés, 21 gardés — axis_crossing 7106, bounds 4545, fairway_gap 9592
  - profondeur 7 : 4464 essais, 15 acceptés, 14 gardés — axis_crossing 3164, bounds 617, fairway_gap 4449
  - profondeur 8 : 2448 essais, 0 acceptés, 0 gardés — axis_crossing 2285, bounds 102, fairway_gap 2448
- seed 5 :
  - profondeur 7 : 19440 essais, 150 acceptés, 72 gardés — axis_crossing 15695, bounds 4355, fairway_gap 19290
  - profondeur 8 : 14112 essais, 10 acceptés, 10 gardés — axis_crossing 12908, bounds 495, clubhouse_clear 85
  - profondeur 9 : 1440 essais, 0 acceptés, 0 gardés — axis_crossing 1222, clubhouse_clear 675, clubhouse_return 36

## Échecs — causes dominantes

- seed 1 : front 9/9, back 7/9 — causes dominantes : fairway_gap 144590, axis_crossing 101126, bounds 59621
- seed 4 : front 9/9, back 7/9 — causes dominantes : fairway_gap 141944, axis_crossing 98850, bounds 54732
- seed 5 : front 9/9, back 8/9 — causes dominantes : fairway_gap 183010, axis_crossing 130889, bounds 67755
