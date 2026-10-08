# Calibration Muirfield — phase 2

Critère de lecture (ne filtre rien) : toutes les seeds réussies pour chaque patron et orientation, 0 violation, p90 ≤ 15 s et max ≤ 30 s, temps HORS relief. Relief : chargé ou construit (construit au 1er patron, en cache au 2e).

Total : 8 combinaisons, 240 seeds, routage 581 s, relief 634 s.

## Par taille et orientation (deux patrons poolés)

| petit | grand | orientation | W×H | réussites (m / inv) | violations | médiane s | p90 s | max s | relief moyen s | statut |
|---|---|---|---|---|---|---|---|---|---|---|
| 300 | 400 | portrait | 300×400 | 30 / 30 | 0 | 2.29 | 11.93 | 18.27 | 1.59 | OK |
| 300 | 400 | paysage | 400×300 | 30 / 30 | 0 | 0.99 | 10.26 | 29.04 | 2.39 | OK |
| 300 | 500 | portrait | 300×500 | 30 / 30 | 0 | 0.33 | 2.46 | 8.33 | 3.31 | OK |
| 300 | 500 | paysage | 500×300 | 30 / 29 | 0 | 0.32 | 1.94 | 4.85 | 3.27 | KO : muirfield_inverse : réussites 29/30 |

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
