# Benchmark parcours 18 trous — seeds 1 à 10 (400×400, rough partagé)

- Succès (18/18) : **5/10**
- Validation indépendante conforme : **5/10**
- Doublons exacts normalisés : **0**
- Quasi-doublons (similarité ≥ 85 %) : **0**
- Temps total (16 process) : **900.2s**

| Seed | Résultat | Front | Back | Temps | Essais | Empreinte | Pile max | Tee10→club | Green18→club | Groupe | Indép. |
|---:|:---:|:---:|:---:|---:|---:|---:|---:|---:|---:|---:|:---:|
| 1 | échec | 9/9 | 6/9 | 430.9s | 236898 | 35.1% | 2 | 80.0 | 175.9 | 80.0 | KO |
| 2 | OK | 9/9 | 9/9 | 784.1s | 298818 | 43.3% | 2 | 44.0 | 34.8 | 44.0/48.0 | OK |
| 3 | OK | 9/9 | 9/9 | 900.0s | 274608 | 46.1% | 3 | 96.0 | 35.3 | 96.0 | OK |
| 4 | échec | 9/9 | 7/9 | 618.3s | 257778 | 37.8% | 3 | 64.0 | 164.9 | 64.0 | KO |
| 5 | OK | 9/9 | 9/9 | 761.4s | 273042 | 43.9% | 2 | 96.0 | 60.1 | 96.0 | OK |
| 6 | échec | 9/9 | 6/9 | 402.6s | 225378 | 35.5% | 2 | 96.0 | 191.1 | 96.0 | KO |
| 7 | OK | 9/9 | 9/9 | 766.5s | 276354 | 44.6% | 3 | 96.0 | 68.6 | 96.0 | OK |
| 8 | échec | 9/9 | 7/9 | 620.6s | 265554 | 38.5% | 2 | 80.0 | 151.7 | 80.0 | KO |
| 9 | échec | 9/9 | 7/9 | 494.6s | 251154 | 38.4% | 3 | 80.0 | 165.8 | 80.0 | KO |
| 10 | OK | 9/9 | 9/9 | 785.4s | 264978 | 43.8% | 2 | 64.0 | 68.5 | 64.0 | OK |

## Pars par nine (ordre de jeu)

- seed 1 : front 3-4-4-3-5-3-4-4-4 / back 3-5-5-4-4-4
- seed 2 : front 3-4-4-4-3-4-5-4-3 / back 4-4-4-4-5-4-3-5-5
- seed 3 : front 3-4-4-3-5-4-4-4-3 / back 3-4-5-5-4-4-5-4-4
- seed 4 : front 3-4-4-4-4-3-3-5-4 / back 3-5-5-4-4-4-4
- seed 5 : front 3-4-4-5-3-3-4-4-4 / back 3-4-4-4-4-4-5-5-5
- seed 6 : front 3-4-4-4-3-3-5-4-4 / back 3-4-4-4-4-4
- seed 7 : front 3-4-4-3-5-3-4-4-4 / back 3-4-5-4-4-4-5-4-5
- seed 8 : front 3-4-4-4-3-4-4-5-3 / back 4-5-5-3-4-4-4
- seed 9 : front 3-4-4-5-4-3-4-4-3 / back 3-5-5-5-4-4-4
- seed 10 : front 3-4-4-4-3-4-5-4-3 / back 3-4-4-5-4-4-4-5-5

## Rejets cumulés

- `axis_crossing` : 1353166
- `bounds` : 706950
- `clubhouse_clear` : 83191
- `clubhouse_departure` : 17567
- `clubhouse_return` : 42464
- `fairway_gap` : 1904811
- `parallel_stack` : 117048

## Échecs — meilleur état et causes dominantes

- seed 1 : front 9/9, back 6/9 — causes dominantes : fairway_gap 166627, axis_crossing 117551, bounds 67528
- seed 4 : front 9/9, back 7/9 — causes dominantes : fairway_gap 187678, axis_crossing 132744, bounds 71323
- seed 6 : front 9/9, back 6/9 — causes dominantes : fairway_gap 158320, axis_crossing 108533, bounds 64672
- seed 8 : front 9/9, back 7/9 — causes dominantes : fairway_gap 191693, axis_crossing 138798, bounds 79870
- seed 9 : front 9/9, back 7/9 — causes dominantes : fairway_gap 180032, axis_crossing 129976, bounds 66196

## Back — 3 dernières profondeurs explorées (causes de rejet)

- seed 1 :
  - profondeur 5 : 19008 essais, 75 acceptés, 48 gardés — fairway_gap 17235, bounds 16147, axis_crossing 12751
  - profondeur 6 : 12816 essais, 35 acceptés, 19 gardés — fairway_gap 12737, axis_crossing 11056, bounds 5759
  - profondeur 7 : 5328 essais, 0 acceptés, 0 gardés — fairway_gap 5328, axis_crossing 4607, bounds 1495
- seed 2 :
  - profondeur 7 : 17712 essais, 272 acceptés, 72 gardés — fairway_gap 17414, axis_crossing 13428, bounds 3673
  - profondeur 8 : 15696 essais, 357 acceptés, 72 gardés — fairway_gap 15338, axis_crossing 13130, parallel_stack 565
  - profondeur 9 : 10368 essais, 496 acceptés, 72 gardés — fairway_gap 9360, axis_crossing 6247, clubhouse_clear 5308
- seed 3 :
  - profondeur 7 : 18432 essais, 249 acceptés, 72 gardés — fairway_gap 18183, axis_crossing 14755, parallel_stack 6651
  - profondeur 8 : 14256 essais, 615 acceptés, 72 gardés — fairway_gap 13613, axis_crossing 10935, parallel_stack 1571
  - profondeur 9 : 10368 essais, 225 acceptés, 72 gardés — fairway_gap 9718, axis_crossing 7308, clubhouse_clear 4939
- seed 4 :
  - profondeur 6 : 16848 essais, 64 acceptés, 59 gardés — fairway_gap 16571, axis_crossing 12562, bounds 6846
  - profondeur 7 : 13824 essais, 34 acceptés, 33 gardés — fairway_gap 13790, axis_crossing 11110, bounds 2584
  - profondeur 8 : 9360 essais, 0 acceptés, 0 gardés — fairway_gap 9360, axis_crossing 8296, parallel_stack 3893
- seed 5 :
  - profondeur 7 : 15552 essais, 98 acceptés, 72 gardés — fairway_gap 15454, axis_crossing 13140, bounds 4575
  - profondeur 8 : 11088 essais, 312 acceptés, 72 gardés — fairway_gap 10769, axis_crossing 7465, parallel_stack 671
  - profondeur 9 : 10368 essais, 3 acceptés, 3 gardés — fairway_gap 10332, axis_crossing 9306, clubhouse_clear 4895
- seed 6 :
  - profondeur 5 : 18000 essais, 33 acceptés, 26 gardés — bounds 15279, fairway_gap 14717, axis_crossing 10023
  - profondeur 6 : 6912 essais, 6 acceptés, 6 gardés — fairway_gap 6871, axis_crossing 5262, bounds 3282
  - profondeur 7 : 1584 essais, 0 acceptés, 0 gardés — fairway_gap 1584, axis_crossing 1331, parallel_stack 784
- seed 7 :
  - profondeur 7 : 16848 essais, 138 acceptés, 72 gardés — fairway_gap 16706, axis_crossing 12906, parallel_stack 5559
  - profondeur 8 : 14832 essais, 74 acceptés, 70 gardés — fairway_gap 14756, axis_crossing 12785, parallel_stack 939
  - profondeur 9 : 10080 essais, 5 acceptés, 5 gardés — fairway_gap 9907, axis_crossing 8127, clubhouse_clear 4200
- seed 8 :
  - profondeur 6 : 18144 essais, 378 acceptés, 72 gardés — fairway_gap 17335, axis_crossing 14041, bounds 7837
  - profondeur 7 : 17280 essais, 53 acceptés, 45 gardés — fairway_gap 17224, axis_crossing 14798, bounds 5753
  - profondeur 8 : 6624 essais, 0 acceptés, 0 gardés — fairway_gap 6624, axis_crossing 5285, parallel_stack 758
- seed 9 :
  - profondeur 6 : 13824 essais, 92 acceptés, 72 gardés — fairway_gap 13275, axis_crossing 9954, bounds 6328
  - profondeur 7 : 19296 essais, 1 acceptés, 1 gardés — fairway_gap 19295, axis_crossing 18166, bounds 2768
  - profondeur 8 : 144 essais, 0 acceptés, 0 gardés — fairway_gap 144, axis_crossing 132, parallel_stack 23
- seed 10 :
  - profondeur 7 : 12384 essais, 57 acceptés, 49 gardés — fairway_gap 12327, axis_crossing 10991, parallel_stack 1614
  - profondeur 8 : 7056 essais, 76 acceptés, 69 gardés — fairway_gap 6978, axis_crossing 5645, parallel_stack 381
  - profondeur 9 : 9936 essais, 4 acceptés, 4 gardés — fairway_gap 9636, axis_crossing 8897, clubhouse_clear 4054

## Observations

- Décision utilisateur : diversité stratifiée des départs du tee 10 par groupe de rayon (``solver.SolverParams.start_radius_groups=((44.0, 48.0), (64.0,), (80.0,), (96.0,))``, ``start_radius_depth2_min_survivors=9``, nouveaux opt-in, défauts () et 0 inchangés) par-dessus les distances back-far (back_clubhouse_max=100.0, back_start_radii=(44.0, 48.0, 64.0, 80.0, 96.0)) -- front inchangé, green 9 inchangé.
- Vérification préalable (script jetable, non committé) : sur les seeds 4 et 8, le beam de profondeur 1 du back-far (sans stratification) contenait déjà les deux rayons historiques (seed 4 : 9+38=47/72 en groupe {44,48} ; seed 8 : 2+2=4/72), mais ce groupe s'effondrait presque totalement à la profondeur 2 SANS garde-fou (seed 4 : 47 -> 4/72 ; seed 8 : 4 -> 0/72 -- lignage mort géométriquement pour cette seed, confirmé par un essai isolé : les 2 seuls candidats de profondeur 1 du groupe {44,48} produisent 0 enfant valide à la profondeur 2, rejet axis_crossing/fairway_gap systématique -- aucune sélection de beam ne peut ressusciter un lignage sans successeur valide). Avec stratification profondeur 1 (part égale 18/groupe) et garde-fou profondeur 2 (survivants minimum testés : 3, 6, 9) : seed 4 conserve EXACTEMENT ce minimum réservé du groupe {44,48} à la profondeur 2 (3, 6 ou 9 selon le réglage, au lieu de 4/72 sans garde-fou) -- le réglage retenu ici (9) a été choisi comme compromis léger (moitié de la part de la profondeur 1, 18/2) sans optimisation fine supplémentaire.
- Comparaison à la config B (``experiments/bean_paving/output/benchmark_course18_400_bounded_1_10/report.json``) : B obtient 5/10 complet, 5/10 validé indépendamment, temps total 2009.0s (16 process) ; ce run (back-div) obtient 5/10 complet, 5/10 validé indépendamment, temps total 900.2s (16 process). Temps par seed -- seed 1 : 655.6s (B) -> 430.9s (back-div); seed 2 : 614.2s (B) -> 784.1s (back-div); seed 3 : 682.0s (B) -> 900.0s (back-div); seed 4 : 2008.8s (B) -> 618.3s (back-div); seed 5 : 560.0s (B) -> 761.4s (back-div); seed 6 : 525.0s (B) -> 402.6s (back-div); seed 7 : 767.3s (B) -> 766.5s (back-div); seed 8 : 1174.2s (B) -> 620.6s (back-div); seed 9 : 700.2s (B) -> 494.6s (back-div); seed 10 : 765.3s (B) -> 785.4s (back-div).
- Composition vs B : seeds redevenues en échec [1, 4, 8] (18/18 en B), seeds nouvellement résolues [5, 7, 10] (échec en B).
- Comparaison à back-far (``experiments/bean_paving/output/benchmark_course18_400_backfar_1_10/report.json``) : back-far obtient 6/10 complet, 6/10 validé indépendamment, temps total 860.9s (16 process) ; ce run (back-div) obtient 5/10 complet, 5/10 validé indépendamment, temps total 900.2s (16 process). Seeds redevenues en échec vs back-far [1], seeds nouvellement résolues vs back-far —. Temps par seed -- seed 1 : 687.3s (back-far) -> 430.9s (back-div); seed 2 : 789.9s (back-far) -> 784.1s (back-div); seed 3 : 837.5s (back-far) -> 900.0s (back-div); seed 4 : 564.6s (back-far) -> 618.3s (back-div); seed 5 : 860.7s (back-far) -> 761.4s (back-div); seed 6 : 420.7s (back-far) -> 402.6s (back-div); seed 7 : 700.3s (back-far) -> 766.5s (back-div); seed 8 : 592.0s (back-far) -> 620.6s (back-div); seed 9 : 425.9s (back-far) -> 494.6s (back-div); seed 10 : 701.6s (back-far) -> 785.4s (back-div).
