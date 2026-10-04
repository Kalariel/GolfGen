# Benchmark bean paving — seeds 1 à 10

- Succès : **10/10**
- Décision : **paving abstrait validé**
- Violations dures : **0**
- Doublons exacts normalisés : **0**
- Quasi-doublons (similarité ≥ 85 %) : **2**

| Seed | Résultat | Temps | Essais | Prof. | Pars | Empreinte | BBox | Caps |
|---:|:---:|---:|---:|---:|:---|---:|---:|---:|
| 1 | OK | 38.0s | 63990 | 9 | 3-4-3-4-5-4-4-5-4 | 30.9% | 80.6% | 8 |
| 2 | OK | 24.5s | 55890 | 9 | 3-3-4-5-5-4-4-4-4 | 28.5% | 80.2% | 7 |
| 3 | OK | 63.4s | 71190 | 9 | 3-4-4-4-5-3-4-5-4 | 31.1% | 87.2% | 8 |
| 4 | OK | 51.4s | 70380 | 9 | 3-4-3-5-4-4-4-5-4 | 29.8% | 87.3% | 9 |
| 5 | OK | 66.8s | 69030 | 9 | 3-4-3-4-5-4-4-5-4 | 29.7% | 84.7% | 9 |
| 6 | OK | 55.9s | 64350 | 9 | 3-4-5-5-4-4-3-4-4 | 29.5% | 81.0% | 8 |
| 7 | OK | 58.2s | 71100 | 9 | 3-4-4-4-3-5-4-5-4 | 28.2% | 74.6% | 7 |
| 8 | OK | 67.1s | 68940 | 9 | 3-4-3-5-5-4-4-4-4 | 29.6% | 84.5% | 9 |
| 9 | OK | 50.7s | 68490 | 9 | 3-4-3-5-4-5-4-4-4 | 30.5% | 83.3% | 8 |
| 10 | OK | 54.9s | 66420 | 9 | 3-4-4-5-3-4-4-5-4 | 26.5% | 81.3% | 8 |

## Rejets cumulés

- `antiparallel` : 95859
- `axis_crossing` : 283265
- `bounds` : 308505
- `clubhouse_departure` : 1888
- `clubhouse_return` : 16156
- `footprint_collision` : 532671

## Quasi-doublons

- seeds 4 et 8 : 85.7%
- seeds 5 et 8 : 88.6%

## Observations

- Les contraintes dures et le retour clubhouse sont respectés sur les dix seeds.
- Les parcours occupent surtout le pourtour de la carte (biais visuel du score actuel).
- Les dix séquences commencent par un par 3 : la préférence de départ par 4 est dominée par la facilité géométrique.
- Le temps moyen est d'environ 53 secondes par seed avec ce prototype Python non optimisé.
