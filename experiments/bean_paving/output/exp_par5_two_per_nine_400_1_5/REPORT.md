# Expérience A' — 2 par5 par nine (bornes (2,2), deadline trou 7, seeds 1 à 5, 400×400)

**Correctif préalable (revue de code, 2026-10-05) :** le PREMIER run de cette
expérience (``bounded_quota=True`` seul, sans ``bounded_quota_back``) était
INVALIDE -- ``course_solver.solve_course`` ne mettait
``SolverParams.bounded_quota=True`` que côté FRONT (``front_params``) ;
``back_params`` était transmis inchangé à ``solver.solve_nine``, donc
``solver._bounded_quota_filter`` (et le forçage ``par5_bounds``/
``par5_deadline`` qu'il porte) n'était JAMAIS exercé côté BACK, quel que soit
``bounded_quota``. Preuve : dans ce premier run, les 2 seules seeds réussies
(2 et 3) avaient leur back par5 aux trous **[4, 8]** et **[4, 8]** -- le trou 8
dépasse la deadline 7 annoncée, qui n'avait donc jamais été appliquée au back.
Chiffres (invalides) du premier run, pour mémoire : **2/5** (seeds 2, 3 OK ;
1, 4, 5 en échec), 2/5 validé indépendamment, 828.7s. Corrigé par le nouveau
paramètre opt-in ``solve_course(bounded_quota_back=True)`` (voir
``course_solver.py``, tests dans ``experiments/bean_paving/
test_course_solver.py``) et par un contrôle indépendant supplémentaire
(``_course_violations(par5_deadline=...)``, qui aurait dû signaler ce
premier run mais n'était pas non plus branché). Le run ci-dessous est le
RUN CORRIGÉ (``bounded_quota_back=True``, validation indépendante avec
``par5_deadline=7``) -- les fichiers du premier run ont été remplacés.

**Résultat du run corrigé, en bref :** toujours **2/5** (mêmes seeds réussies,
2 et 3), un score IDENTIQUE au premier run mais pour une raison désormais
correcte -- le back est maintenant RÉELLEMENT contraint : sur les 5 seeds,
back par5 aux trous ``[2,3]``, ``[3,4]``, ``[4,7]``, ``[2,4]``, ``[6]``
(seed 5 incomplète, 6/9) -- plus aucun trou 8 ou 9, la deadline 7 est
désormais respectée partout où le back a pu placer ses 2 par5. Les 3 échecs
(1, 4, 5) restent bloqués aux mêmes profondeurs (6-7/9) par les mêmes causes
géométriques indépendantes du quota (``fairway_gap``, ``axis_crossing``,
``bounds``) -- la deadline n'est donc PAS la cause des échecs, qui étaient
déjà présents (sous une forme non valide) dans le premier run.

- Succès (18/18) : **2/5** (config A -- deadline seule, par5 [1,3] -- seeds 1-5 : **5/5**)
- Validation indépendante conforme : **2/5**
- Temps total (5 process) : **500.2s**

- Changement vs config A : ``par5_bounds=(2, 2)`` sur les deux nines (au lieu de ``(1, 3)`` par défaut) -- le minimum = maximum = 2, donc le filtre de forçage ``solver._bounded_quota_filter`` (générique en ``lo``/``hi``, AUCUN changement de code) force la pose des DEUX par5 de chaque nine au plus tard au trou **7**. ``par3_bounds`` ``(1, 3)`` et le quota global 4/10/4 restent inchangés (2 + 2 = 4 par5 au total). Reste = config A à l'identique.

| Seed | Résultat | Front | Back | Temps | Tee1→club | Green9→club | Tee10→club | Green18→club | Par trou 9 | Par trou 18 | Indép. | Config A |
|---:|:---:|:---:|:---:|---:|---:|---:|---:|---:|---:|---:|:---:|:---:|
| 1 | échec | 9/9 | 7/9 | 309.4s | 36.0 | 22.3 | 96.0 | 153.0 | 3 | 4 | KO | OK 519.9s |
| 2 | OK | 9/9 | 9/9 | 500.2s | 36.0 | 24.6 | 96.0 | 29.2 | 4 | 4 | OK | OK 802.6s |
| 3 | OK | 9/9 | 9/9 | 442.3s | 24.0 | 26.0 | 64.0 | 35.2 | 3 | 4 | OK | OK 824.7s |
| 4 | échec | 9/9 | 7/9 | 312.1s | 36.0 | 25.2 | 80.0 | 152.9 | 3 | 4 | KO | OK 568.2s |
| 5 | échec | 9/9 | 6/9 | 312.9s | 36.0 | 39.4 | 96.0 | 169.8 | 4 | 5 | KO | OK 793.1s |

## Comparaison seed par seed à la config A

- seed 1 : échec (DIFFÉRENT de la config A OK), temps 309.4s vs 519.9s (config A), delta -210.5s. Par5 config A : front [5] / back [2, 5, 8] -- A' : front [5, 7] / back [2, 3].
- seed 2 : OK (identique de la config A OK), temps 500.2s vs 802.6s (config A), delta -302.4s. Par5 config A : front [7] / back [5, 6, 7] -- A' : front [3, 6] / back [3, 4].
- seed 3 : OK (identique de la config A OK), temps 442.3s vs 824.7s (config A), delta -382.4s. Par5 config A : front [5] / back [5, 7, 8] -- A' : front [3, 5] / back [4, 7].
- seed 4 : échec (DIFFÉRENT de la config A OK), temps 312.1s vs 568.2s (config A), delta -256.0s. Par5 config A : front [3] / back [2, 6, 8] -- A' : front [5, 7] / back [2, 4].
- seed 5 : échec (DIFFÉRENT de la config A OK), temps 312.9s vs 793.1s (config A), delta -480.2s. Par5 config A : front [4] / back [7, 8, 9] -- A' : front [4, 7] / back [6].

## Pars par nine (ordre de jeu) -- trous 9 et 18 en gras

- seed 1 : front 3-4-4-3-5-4-5-4-**3** / back 3-5-5-4-4-4-**4**
- seed 2 : front 3-4-5-3-3-5-4-4-**4** / back 3-4-5-5-4-4-4-4-**4**
- seed 3 : front 3-4-5-4-5-4-4-3-**3** / back 3-4-4-5-4-4-5-4-**4**
- seed 4 : front 3-4-4-4-5-4-5-3-**3** / back 3-5-4-5-4-4-**4**
- seed 5 : front 3-4-4-5-3-3-5-4-**4** / back 3-4-4-4-4-**5**

## Par5 — trous de pose (play order, 1-indexé)

- seed 1 : front par5 aux trous [5, 7] / back par5 aux trous [2, 3]
- seed 2 : front par5 aux trous [3, 6] / back par5 aux trous [3, 4]
- seed 3 : front par5 aux trous [3, 5] / back par5 aux trous [4, 7]
- seed 4 : front par5 aux trous [5, 7] / back par5 aux trous [2, 4]
- seed 5 : front par5 aux trous [4, 7] / back par5 aux trous [6]

## Rejets cumulés

- `axis_crossing` : 544091
- `bounds` : 296875
- `clubhouse_clear` : 42283
- `clubhouse_departure` : 8440
- `clubhouse_return` : 1171
- `fairway_gap` : 776335
- `parallel_stack` : 62470

## Back — 3 dernières profondeurs explorées (causes de rejet)

- seed 1 :
  - profondeur 6 : 12096 essais, 6 acceptés, 5 gardés — fairway_gap 12064, axis_crossing 10539, bounds 5886
  - profondeur 7 : 720 essais, 2 acceptés, 2 gardés — fairway_gap 718, axis_crossing 483, bounds 211
  - profondeur 8 : 288 essais, 0 acceptés, 0 gardés — fairway_gap 288, axis_crossing 235, parallel_stack 47
- seed 2 :
  - profondeur 7 : 10368 essais, 102 acceptés, 72 gardés — fairway_gap 10266, axis_crossing 7975, parallel_stack 4187
  - profondeur 8 : 10368 essais, 412 acceptés, 72 gardés — fairway_gap 9926, axis_crossing 7749, parallel_stack 2475
  - profondeur 9 : 10368 essais, 337 acceptés, 72 gardés — fairway_gap 9770, axis_crossing 6869, clubhouse_clear 5256
- seed 3 :
  - profondeur 7 : 10368 essais, 51 acceptés, 45 gardés — fairway_gap 10317, axis_crossing 8041, bounds 2544
  - profondeur 8 : 6480 essais, 53 acceptés, 50 gardés — fairway_gap 6420, axis_crossing 5050, parallel_stack 1772
  - profondeur 9 : 7200 essais, 8 acceptés, 8 gardés — fairway_gap 7172, axis_crossing 5492, clubhouse_clear 4097
- seed 4 :
  - profondeur 6 : 9360 essais, 27 acceptés, 20 gardés — fairway_gap 9037, axis_crossing 6650, bounds 4246
  - profondeur 7 : 2880 essais, 11 acceptés, 11 gardés — fairway_gap 2869, axis_crossing 2154, bounds 315
  - profondeur 8 : 1584 essais, 0 acceptés, 0 gardés — fairway_gap 1584, axis_crossing 1455, parallel_stack 736
- seed 5 :
  - profondeur 5 : 17280 essais, 157 acceptés, 72 gardés — bounds 15678, fairway_gap 12771, axis_crossing 8251
  - profondeur 6 : 13824 essais, 36 acceptés, 34 gardés — fairway_gap 13519, axis_crossing 10243, bounds 6413
  - profondeur 7 : 4896 essais, 0 acceptés, 0 gardés — fairway_gap 4896, axis_crossing 4338, parallel_stack 1359

## Échecs — causes dominantes

- seed 1 : front 9/9, back 7/9 — causes dominantes : fairway_gap 144159, axis_crossing 100742, bounds 59407
- seed 4 : front 9/9, back 7/9 — causes dominantes : fairway_gap 138945, axis_crossing 96554, bounds 54116
- seed 5 : front 9/9, back 6/9 — causes dominantes : fairway_gap 150089, axis_crossing 103711, bounds 62360
