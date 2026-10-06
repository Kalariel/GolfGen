# Expérience C1 — couloirs de départ réservés (seeds 1 à 5, 400×400)

- Succès (18/18) : **5/5** (config A : **5/5** ; liens praticables généralisés : **1/5**)
- Validation indépendante conforme (quotas + couloirs) : **5/5**
- Temps total (5 process) : **2473.8s**

- Tee 10 fixé avant le front (``solver.SolverParams.fixed_start``), candidats tirés des rayons **(44.0, 48.0, 64.0)** (pas 80/96), au plus **3** essayés par seed, classés par ``solver._transform_rank``. Divergence angulaire tee1/tee10 (vue depuis le clubhouse) >= **90°** imposée au front. Couloirs réservés clubhouse<->tee1 et clubhouse<->tee10 (largeur nulle, propriétaire exclu) vérifiés à chaque candidat de placement des deux nines ET en validation finale indépendante.

| Seed | Résultat | Front | Back | Temps | Essais | Candidat retenu (rayon, angle) | Angle tee1 | Angle tee10 | Divergence | Couloirs | Indép. | Config A | Liens praticables |
|---:|:---:|:---:|:---:|---:|---:|:---:|---:|---:|---:|:---:|:---:|:---:|:---:|
| 1 | OK | 9/9 | 9/9 | 1054.4s | 2 | #1 (44, 270°) | 30° | 270° | 120° | OK | OK | OK 519.9s | échec 772.4s |
| 2 | OK | 9/9 | 9/9 | 2024.4s | 1 | #0 (44, 120°) | 330° | 120° | 150° | OK | OK | OK 802.6s | échec 469.2s |
| 3 | OK | 9/9 | 9/9 | 1592.8s | 2 | #1 (44, 240°) | 0° | 240° | 120° | OK | OK | OK 824.7s | échec 953.8s |
| 4 | OK | 9/9 | 9/9 | 2473.8s | 2 | #1 (44, 330°) | 60° | 330° | 90° | OK | OK | OK 568.2s | échec 1216.9s |
| 5 | OK | 9/9 | 9/9 | 1498.6s | 2 | #1 (44, 150°) | 300° | 150° | 150° | OK | OK | OK 793.1s | OK 2005.2s |

## Candidats de tee 10 essayés par seed

- seed 1 :
  - candidat 0 : tee10=(244.0, 200.0), cap 330°, rayon 44.0, angle 0.0° -- front échec, back —
  - candidat 1 : tee10=(200.0, 156.0), cap 240°, rayon 44.0, angle 270.0° -- front OK, back OK
- seed 2 :
  - candidat 0 : tee10=(178.0, 238.1), cap 150°, rayon 44.0, angle 120.0° -- front OK, back OK
- seed 3 :
  - candidat 0 : tee10=(222.0, 238.1), cap 30°, rayon 44.0, angle 60.0° -- front OK, back échec
  - candidat 1 : tee10=(178.0, 161.9), cap 270°, rayon 44.0, angle 240.0° -- front OK, back OK
- seed 4 :
  - candidat 0 : tee10=(222.0, 238.1), cap 90°, rayon 44.0, angle 60.0° -- front OK, back échec
  - candidat 1 : tee10=(238.1, 178.0), cap 0°, rayon 44.0, angle 330.0° -- front OK, back OK
- seed 5 :
  - candidat 0 : tee10=(244.0, 200.0), cap 330°, rayon 44.0, angle 0.0° -- front échec, back —
  - candidat 1 : tee10=(161.9, 222.0), cap 120°, rayon 44.0, angle 150.0° -- front OK, back OK

## Pars par nine (ordre de jeu) -- trous 9 et 18 en gras

- seed 1 : front 3-4-4-3-3-4-5-4-**4** / back 5-5-5-4-3-4-4-4-**4**
- seed 2 : front 3-4-4-4-5-4-3-3-**4** / back 4-5-5-3-4-4-5-4-**4**
- seed 3 : front 3-4-4-3-5-4-4-4-**3** / back 4-5-4-3-5-5-4-4-**4**
- seed 4 : front 3-4-4-3-3-5-4-4-**4** / back 4-5-4-3-4-5-5-4-**4**
- seed 5 : front 3-4-4-5-3-3-4-4-**4** / back 4-5-4-3-4-4-4-5-**5**

## Par5 — trous de pose (play order, 1-indexé)

- seed 1 : front par5 aux trous [7] / back par5 aux trous [1, 2, 3]
- seed 2 : front par5 aux trous [5] / back par5 aux trous [2, 3, 7]
- seed 3 : front par5 aux trous [5] / back par5 aux trous [2, 5, 6]
- seed 4 : front par5 aux trous [6] / back par5 aux trous [2, 6, 7]
- seed 5 : front par5 aux trous [4] / back par5 aux trous [2, 8, 9]

## Rejets cumulés (tous candidats confondus)

- `axis_crossing` : 711298
- `bounds` : 385521
- `clubhouse_clear` : 62273
- `clubhouse_departure` : 1944
- `clubhouse_return` : 17661
- `corridor_blocked` : 75947
- `fairway_gap` : 1007390
- `parallel_stack` : 66534
- `start_angle_divergence` : 283

## Back — 3 dernières profondeurs explorées (meilleure tentative, causes de rejet)

- seed 1 :
  - profondeur 7 : 13248 essais, 348 acceptés, 72 gardés — fairway_gap 12896, axis_crossing 11235, bounds 3890
  - profondeur 8 : 10368 essais, 403 acceptés, 72 gardés — fairway_gap 9816, axis_crossing 5990, parallel_stack 2780
  - profondeur 9 : 10368 essais, 260 acceptés, 72 gardés — fairway_gap 9688, axis_crossing 6779, corridor_blocked 6177
- seed 2 :
  - profondeur 7 : 19872 essais, 1858 acceptés, 72 gardés — fairway_gap 17962, axis_crossing 12896, bounds 3184
  - profondeur 8 : 16560 essais, 1596 acceptés, 72 gardés — fairway_gap 14952, axis_crossing 12331, parallel_stack 1102
  - profondeur 9 : 10368 essais, 795 acceptés, 72 gardés — fairway_gap 8876, corridor_blocked 6853, axis_crossing 5508
- seed 3 :
  - profondeur 7 : 17280 essais, 921 acceptés, 72 gardés — fairway_gap 16330, axis_crossing 13565, bounds 4921
  - profondeur 8 : 13824 essais, 146 acceptés, 72 gardés — fairway_gap 13672, axis_crossing 11656, parallel_stack 551
  - profondeur 9 : 10368 essais, 15 acceptés, 8 gardés — fairway_gap 10286, axis_crossing 8039, corridor_blocked 7356
- seed 4 :
  - profondeur 7 : 18432 essais, 1043 acceptés, 72 gardés — fairway_gap 17329, axis_crossing 11590, bounds 4409
  - profondeur 8 : 16560 essais, 1502 acceptés, 72 gardés — fairway_gap 15033, axis_crossing 11729, bounds 549
  - profondeur 9 : 10368 essais, 409 acceptés, 72 gardés — fairway_gap 9658, axis_crossing 6816, corridor_blocked 5508
- seed 5 :
  - profondeur 7 : 20160 essais, 603 acceptés, 72 gardés — fairway_gap 19541, axis_crossing 15721, bounds 6469
  - profondeur 8 : 15264 essais, 893 acceptés, 72 gardés — fairway_gap 14331, axis_crossing 11403, bounds 1135
  - profondeur 9 : 10368 essais, 854 acceptés, 72 gardés — fairway_gap 9060, corridor_blocked 6133, axis_crossing 5453
