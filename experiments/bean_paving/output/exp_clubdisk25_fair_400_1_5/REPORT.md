# Expérience — disque d'exclusion clubhouse 25 blocs, anneau de départ élargi "équitable" (seeds 1 à 5, 400×400)

- Succès (18/18) : **1/5** (baseline back-far seeds 1-5 : **4/5** ; disque 25 étroit (EXP2) : **0/5**)
- Validation indépendante conforme : **1/5**
- Temps total (5 process en parallèle) : **1223.3s**

- Disque : rayon **25.0** autour du clubhouse, empreinte entière (cœur ET rough) interdite dedans -- même règle que l'expérience "disque 25" étroite. Différence : front `start_radii`=(45.0, 55.0, 65.0) (étroit : (40.0, 48.0)), secteur de départ inchangé ; front `clubhouse_max`=80.0 (étroit : 60.0) ; cible de score de profondeur 9 fixée EXPLICITEMENT (`solver.SolverParams.target_radius_depth9_min`) à **50.0** pour LES DEUX nines (étroit : formule `max(cible, 25+15)=40`, implicite). Back inchangé (baseline back-far : `clubhouse_max`=100, `start_radii`=(44, 48, 64, 80, 96), `closing_lookahead_from`=7). Départs sur grille FIXE (pas de tirage aléatoire).

| Seed | Résultat | Front | Back | Temps | Tee1→club | Green9→club | Tee10→club | Green18→club | Pile max | Indép. | Back-far | Disque étroit (EXP2) |
|---:|:---:|:---:|:---:|---:|---:|---:|---:|---:|---:|:---:|:---:|:---:|
| 1 | échec | 9/9 | 8/9 | 957.2s | 65.0 | 52.4 | 96.0 | 122.1 | 3 | KO | OK 687.3s | échec 883.4s |
| 2 | échec | 9/9 | 8/9 | 976.9s | 65.0 | 45.5 | 64.0 | 123.7 | 3 | KO | OK 789.9s | échec 866.9s |
| 3 | OK | 9/9 | 9/9 | 1037.7s | 55.0 | 60.7 | 96.0 | 42.4 | 3 | OK | OK 837.5s | échec 1157.5s |
| 4 | échec | 9/9 | 7/9 | 774.9s | 55.0 | 47.3 | 96.0 | 161.6 | 2 | KO | échec 564.6s | échec 1092.8s |
| 5 | échec | 9/9 | 8/9 | 1223.2s | 55.0 | 45.7 | 44.0 | 128.2 | 3 | KO | OK 860.7s | échec 1209.1s |

## Comparaison seed par seed

- seed 1 : échec, vs back-far (DIFFÉRENT, OK 687.3s, delta +269.9s), vs disque étroit (identique, échec 883.4s, delta +73.8s).
- seed 2 : échec, vs back-far (DIFFÉRENT, OK 789.9s, delta +187.0s), vs disque étroit (identique, échec 866.9s, delta +109.9s).
- seed 3 : OK, vs back-far (identique, OK 837.5s, delta +200.1s), vs disque étroit (DIFFÉRENT, échec 1157.5s, delta -119.9s).
- seed 4 : échec, vs back-far (identique, échec 564.6s, delta +210.3s), vs disque étroit (identique, échec 1092.8s, delta -317.9s).
- seed 5 : échec, vs back-far (DIFFÉRENT, OK 860.7s, delta +362.5s), vs disque étroit (identique, échec 1209.1s, delta +14.2s).

## Pars par nine (ordre de jeu)

- seed 1 : front 3-4-4-3-4-4-3-4-5 / back 3-4-4-4-4-4-5-5
- seed 2 : front 3-4-4-3-4-4-3-5-4 / back 4-5-5-3-4-4-4-4
- seed 3 : front 3-4-4-4-4-3-4-3-5 / back 3-5-5-5-4-4-4-4-4
- seed 4 : front 3-4-4-3-4-3-4-4-5 / back 3-5-5-4-4-4-4
- seed 5 : front 3-4-4-3-3-4-4-4-5 / back 4-4-4-3-4-5-5-4

## Rejets cumulés

- `axis_crossing` : 699090
- `bounds` : 372363
- `clubhouse_block` : 89948
- `clubhouse_clear` : 50812
- `clubhouse_departure` : 8612
- `clubhouse_return` : 4897
- `fairway_gap` : 988725
- `parallel_stack` : 65245
- dont `clubhouse_block` (disque 25.0) : **89948** rejets cumulés sur les 5 seeds

## Front — 3 dernières profondeurs explorées (causes de rejet)

- seed 1 :
  - profondeur 7 : 15660 essais, 3731 acceptés, 72 gardés — fairway_gap 11657, axis_crossing 8380, parallel_stack 2077
  - profondeur 8 : 15660 essais, 3087 acceptés, 72 gardés — fairway_gap 12132, axis_crossing 8099, parallel_stack 2102
  - profondeur 9 : 12960 essais, 138 acceptés, 72 gardés — clubhouse_block 11561, fairway_gap 9291, clubhouse_clear 6958
- seed 2 :
  - profondeur 7 : 15660 essais, 4082 acceptés, 72 gardés — fairway_gap 11236, axis_crossing 8711, bounds 1153
  - profondeur 8 : 15660 essais, 1909 acceptés, 72 gardés — fairway_gap 13543, axis_crossing 9933, parallel_stack 1589
  - profondeur 9 : 12960 essais, 187 acceptés, 72 gardés — clubhouse_block 11835, fairway_gap 9174, axis_crossing 6879
- seed 3 :
  - profondeur 7 : 15660 essais, 3587 acceptés, 72 gardés — fairway_gap 11790, axis_crossing 8469, parallel_stack 1155
  - profondeur 8 : 15660 essais, 2773 acceptés, 72 gardés — fairway_gap 12338, axis_crossing 7931, clubhouse_block 1417
  - profondeur 9 : 12960 essais, 115 acceptés, 72 gardés — clubhouse_block 10247, fairway_gap 7565, clubhouse_clear 6198
- seed 4 :
  - profondeur 7 : 15660 essais, 5481 acceptés, 72 gardés — fairway_gap 9841, axis_crossing 6976, bounds 945
  - profondeur 8 : 15660 essais, 1320 acceptés, 72 gardés — fairway_gap 14060, axis_crossing 10214, clubhouse_block 702
  - profondeur 9 : 12960 essais, 142 acceptés, 72 gardés — clubhouse_block 11719, fairway_gap 9178, clubhouse_clear 7153
- seed 5 :
  - profondeur 7 : 15660 essais, 4914 acceptés, 72 gardés — fairway_gap 10344, axis_crossing 7136, bounds 1311
  - profondeur 8 : 15660 essais, 1473 acceptés, 72 gardés — fairway_gap 13958, axis_crossing 9841, clubhouse_block 638
  - profondeur 9 : 12960 essais, 144 acceptés, 72 gardés — clubhouse_block 11631, fairway_gap 8995, clubhouse_clear 7079

## Back — 3 dernières profondeurs explorées (causes de rejet)

- seed 1 :
  - profondeur 7 : 16416 essais, 18 acceptés, 17 gardés — fairway_gap 16398, axis_crossing 13395, bounds 5568
  - profondeur 8 : 2448 essais, 18 acceptés, 10 gardés — fairway_gap 2422, axis_crossing 1748, parallel_stack 815
  - profondeur 9 : 1440 essais, 0 acceptés, 0 gardés — fairway_gap 1440, axis_crossing 1440, clubhouse_block 1140
- seed 2 :
  - profondeur 7 : 19152 essais, 675 acceptés, 72 gardés — fairway_gap 18341, axis_crossing 15147, bounds 4866
  - profondeur 8 : 16560 essais, 76 acceptés, 55 gardés — fairway_gap 16471, axis_crossing 14111, parallel_stack 1301
  - profondeur 9 : 7920 essais, 0 acceptés, 0 gardés — fairway_gap 7899, axis_crossing 7753, clubhouse_block 7037
- seed 3 :
  - profondeur 7 : 17280 essais, 524 acceptés, 72 gardés — fairway_gap 16507, axis_crossing 12540, bounds 3659
  - profondeur 8 : 13824 essais, 154 acceptés, 72 gardés — fairway_gap 13669, axis_crossing 10772, parallel_stack 1473
  - profondeur 9 : 10368 essais, 1 acceptés, 1 gardés — fairway_gap 9954, clubhouse_block 9041, axis_crossing 8187
- seed 4 :
  - profondeur 6 : 18144 essais, 120 acceptés, 72 gardés — fairway_gap 17467, axis_crossing 12213, bounds 7869
  - profondeur 7 : 15696 essais, 55 acceptés, 46 gardés — fairway_gap 15640, axis_crossing 12975, bounds 3778
  - profondeur 8 : 12672 essais, 0 acceptés, 0 gardés — fairway_gap 12672, axis_crossing 11767, parallel_stack 1141
- seed 5 :
  - profondeur 7 : 19152 essais, 496 acceptés, 72 gardés — fairway_gap 18531, axis_crossing 12675, bounds 2982
  - profondeur 8 : 16560 essais, 179 acceptés, 72 gardés — fairway_gap 16371, axis_crossing 13546, parallel_stack 1203
  - profondeur 9 : 10368 essais, 0 acceptés, 0 gardés — fairway_gap 10263, axis_crossing 9923, clubhouse_block 9402

## Échecs — causes dominantes

- seed 1 : front 9/9, back 8/9 — causes dominantes : fairway_gap 174119, axis_crossing 120175, bounds 71179
- seed 2 : front 9/9, back 8/9 — causes dominantes : fairway_gap 214962, axis_crossing 154175, bounds 80955
- seed 4 : front 9/9, back 7/9 — causes dominantes : fairway_gap 184894, axis_crossing 131378, bounds 72610
- seed 5 : front 9/9, back 8/9 — causes dominantes : fairway_gap 219401, axis_crossing 154968, bounds 81010
