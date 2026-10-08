# Calibration Muirfield — phase 2

Critère de lecture (ne filtre rien) : toutes les seeds réussies pour chaque patron et orientation, 0 violation, p90 ≤ 15 s et max ≤ 30 s, temps HORS relief. Relief : chargé ou construit (construit au 1er patron, en cache au 2e).

Total : 20 combinaisons, 600 seeds, routage 944 s, relief 1834 s.

## Par taille et orientation (deux patrons poolés)

| petit | grand | orientation | W×H | réussites (m / inv) | violations | médiane s | p90 s | max s | relief moyen s | statut |
|---|---|---|---|---|---|---|---|---|---|---|
| 300 | 400 | portrait | 300×400 | 30 / 30 | 0 | 2.29 | 11.93 | 18.27 | 1.59 | OK |
| 300 | 400 | paysage | 400×300 | 30 / 30 | 0 | 0.99 | 10.26 | 29.04 | 2.39 | OK |
| 300 | 500 | portrait | 300×500 | 30 / 30 | 0 | 0.33 | 2.46 | 8.33 | 3.31 | OK |
| 300 | 500 | paysage | 500×300 | 30 / 29 | 0 | 0.32 | 1.94 | 4.85 | 3.27 | KO : muirfield_inverse : réussites 29/30 |
| 325 | 450 | portrait | 325×450 | 30 / 30 | 0 | 0.34 | 1.61 | 10.47 | 3.26 | OK |
| 325 | 450 | paysage | 450×325 | 29 / 30 | 0 | 0.34 | 2.48 | 15.14 | 3.28 | KO : muirfield : réussites 29/30 |
| 350 | 400 | portrait | 350×400 | 30 / 29 | 0 | 0.33 | 2.96 | 5.72 | 2.47 | KO : muirfield_inverse : réussites 29/30 |
| 350 | 400 | paysage | 400×350 | 30 / 30 | 0 | 0.40 | 3.46 | 10.44 | 3.07 | OK |
| 350 | 500 | portrait | 350×500 | 30 / 30 | 0 | 0.37 | 2.85 | 5.04 | 4.02 | OK |
| 350 | 500 | paysage | 500×350 | 30 / 30 | 0 | 0.36 | 2.12 | 3.76 | 3.90 | OK |

## Par patron

| petit | grand | orientation | patron | réussites | violations | médiane s | p90 s | max s | relief moyen s | échecs |
|---|---|---|---|---|---|---|---|---|---|---|
| 300 | 400 | portrait | muirfield | 30/30 | 0 | 2.29 | 10.94 | 17.10 | 3.18 | — |
| 300 | 400 | portrait | muirfield_inverse | 30/30 | 0 | 2.40 | 12.02 | 18.27 | 0.00 | — |
| 300 | 400 | paysage | muirfield | 30/30 | 0 | 1.02 | 10.26 | 14.90 | 4.78 | — |
| 300 | 400 | paysage | muirfield_inverse | 30/30 | 0 | 0.99 | 9.91 | 29.04 | 0.00 | — |
| 300 | 500 | portrait | muirfield | 30/30 | 0 | 0.35 | 2.26 | 5.40 | 6.63 | — |
| 300 | 500 | portrait | muirfield_inverse | 30/30 | 0 | 0.32 | 2.60 | 8.33 | 0.00 | — |
| 300 | 500 | paysage | muirfield | 30/30 | 0 | 0.31 | 1.67 | 3.50 | 6.54 | — |
| 300 | 500 | paysage | muirfield_inverse | 29/30 | 0 | 0.32 | 2.28 | 4.85 | 0.00 | echec 1 (echec_ancrages 27) |
| 325 | 450 | portrait | muirfield | 30/30 | 0 | 0.33 | 1.41 | 6.06 | 6.52 | — |
| 325 | 450 | portrait | muirfield_inverse | 30/30 | 0 | 0.34 | 2.86 | 10.47 | 0.00 | — |
| 325 | 450 | paysage | muirfield | 29/30 | 0 | 0.34 | 3.09 | 15.14 | 6.56 | echec 1 (echec_ancrages 26, infaisable_ancrage 1) |
| 325 | 450 | paysage | muirfield_inverse | 30/30 | 0 | 0.34 | 1.95 | 5.35 | 0.00 | — |
| 350 | 400 | portrait | muirfield | 30/30 | 0 | 0.37 | 2.34 | 5.72 | 4.95 | — |
| 350 | 400 | portrait | muirfield_inverse | 29/30 | 0 | 0.32 | 3.93 | 4.68 | 0.00 | echec 1 (echec_ancrages 27) |
| 350 | 400 | paysage | muirfield | 30/30 | 0 | 0.37 | 3.46 | 9.49 | 6.13 | — |
| 350 | 400 | paysage | muirfield_inverse | 30/30 | 0 | 0.42 | 2.66 | 10.44 | 0.00 | — |
| 350 | 500 | portrait | muirfield | 30/30 | 0 | 0.36 | 2.81 | 3.94 | 8.04 | — |
| 350 | 500 | portrait | muirfield_inverse | 30/30 | 0 | 0.37 | 2.95 | 5.04 | 0.00 | — |
| 350 | 500 | paysage | muirfield | 30/30 | 0 | 0.36 | 2.34 | 3.76 | 7.80 | — |
| 350 | 500 | paysage | muirfield_inverse | 30/30 | 0 | 0.36 | 2.06 | 2.80 | 0.00 | — |
