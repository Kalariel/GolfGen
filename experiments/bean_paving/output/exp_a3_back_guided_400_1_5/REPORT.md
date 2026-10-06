# Expérience A''' — back guidé (2 par5 exacts), sans deadline back (seeds 1 à 5, 400×400)

- Succès (18/18) : **2/5** (config A : **5/5** ; config A' : **2/5** ; config A'' corrigée : **2/5**)
- Validation indépendante conforme : **2/5**
- Temps total (5 process) : **808.8s**

- Changement vs A'' : ``solve_course(bounded_quota_back=True)`` (au lieu de ``False``) -- le back est désormais GUIDÉ en cours de recherche vers exactement 2 par5 (``solver._bounded_quota_filter``), mais garde ``back_params.par5_deadline=None`` (AUCUNE fenêtre de position imposée, contrairement à A' où le back avait aussi ``par5_deadline=7``). ``front_params`` inchangé (bounds (2,2) + deadline trou 7).

| Seed | Résultat | Front | Back | Temps | Par trou 9 | Par trou 18 | Indép. | Config A | Config A' | Config A'' |
|---:|:---:|:---:|:---:|---:|---:|---:|:---:|:---:|:---:|:---:|
| 1 | échec | 9/9 | 7/9 | 309.9s | 3 | 4 | KO | OK 519.9s | échec 309.4s | échec 312.7s |
| 2 | OK | 9/9 | 9/9 | 603.5s | 4 | 4 | OK | OK 802.6s | OK 500.2s | OK 602.2s |
| 3 | OK | 9/9 | 9/9 | 808.7s | 3 | 4 | OK | OK 824.7s | OK 442.3s | OK 827.9s |
| 4 | échec | 9/9 | 7/9 | 327.0s | 3 | 4 | KO | OK 568.2s | échec 312.1s | échec 327.7s |
| 5 | échec | 9/9 | 8/9 | 439.6s | 4 | 5 | KO | OK 793.1s | échec 312.9s | échec 445.5s |

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

## Comparaison seed par seed à A, A' et A''

- seed 1 : A''' échec, back par5 [2, 3] -- A : OK, back [2, 5, 8] -- A' : échec, back [2, 3] -- A'' : échec, back [2, 3]
- seed 2 : A''' OK, back par5 [4, 8] -- A : OK, back [5, 6, 7] -- A' : OK, back [3, 4] -- A'' : OK, back [4, 8]
- seed 3 : A''' OK, back par5 [4, 8] -- A : OK, back [5, 7, 8] -- A' : OK, back [4, 7] -- A'' : OK, back [4, 8]
- seed 4 : A''' échec, back par5 [2] -- A : OK, back [2, 6, 8] -- A' : échec, back [2, 4] -- A'' : échec, back [2]
- seed 5 : A''' échec, back par5 [8] -- A : OK, back [7, 8, 9] -- A' : échec, back [6] -- A'' : échec, back [8]

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
  - profondeur 6 : 12528 essais, 6 acceptés, 5 gardés — fairway_gap 12495, axis_crossing 10923, bounds 6100
  - profondeur 7 : 720 essais, 2 acceptés, 2 gardés — fairway_gap 718, axis_crossing 483, bounds 211
  - profondeur 8 : 288 essais, 0 acceptés, 0 gardés — fairway_gap 288, axis_crossing 235, parallel_stack 47
- seed 2 :
  - profondeur 7 : 15552 essais, 153 acceptés, 72 gardés — fairway_gap 15399, axis_crossing 11903, parallel_stack 6308
  - profondeur 8 : 15552 essais, 479 acceptés, 72 gardés — fairway_gap 15064, axis_crossing 12152, parallel_stack 2552
  - profondeur 9 : 10368 essais, 193 acceptés, 72 gardés — fairway_gap 9873, axis_crossing 7542, clubhouse_clear 5087
- seed 3 :
  - profondeur 7 : 17568 essais, 136 acceptés, 72 gardés — fairway_gap 17432, axis_crossing 13105, bounds 5090
  - profondeur 8 : 15552 essais, 462 acceptés, 72 gardés — fairway_gap 15040, axis_crossing 11371, parallel_stack 2790
  - profondeur 9 : 10368 essais, 34 acceptés, 31 gardés — fairway_gap 10201, axis_crossing 8541, clubhouse_clear 5122
- seed 4 :
  - profondeur 6 : 9936 essais, 29 acceptés, 21 gardés — fairway_gap 9592, axis_crossing 7106, bounds 4545
  - profondeur 7 : 4464 essais, 15 acceptés, 14 gardés — fairway_gap 4449, axis_crossing 3164, bounds 617
  - profondeur 8 : 2448 essais, 0 acceptés, 0 gardés — fairway_gap 2448, axis_crossing 2285, parallel_stack 1194
- seed 5 :
  - profondeur 7 : 19440 essais, 150 acceptés, 72 gardés — fairway_gap 19290, axis_crossing 15695, bounds 4355
  - profondeur 8 : 14112 essais, 10 acceptés, 10 gardés — fairway_gap 14102, axis_crossing 12908, parallel_stack 2423
  - profondeur 9 : 1440 essais, 0 acceptés, 0 gardés — fairway_gap 1402, axis_crossing 1222, clubhouse_clear 675

## Échecs — causes dominantes

- seed 1 : front 9/9, back 7/9 — causes dominantes : fairway_gap 144590, axis_crossing 101126, bounds 59621
- seed 4 : front 9/9, back 7/9 — causes dominantes : fairway_gap 141944, axis_crossing 98850, bounds 54732
- seed 5 : front 9/9, back 8/9 — causes dominantes : fairway_gap 183010, axis_crossing 130889, bounds 67755
