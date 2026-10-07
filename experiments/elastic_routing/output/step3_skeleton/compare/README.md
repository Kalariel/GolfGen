# Comparaison des essais de l'étape 3 (squelette global)

Quatre variantes, chacune avec une planche `planche.png` (seeds côte à
côte, 3 par ligne) et les `skeleton.svg` individuels. Généré le
2026-10-07, round 3 (`rambo/elastic-step3-skeleton`, voir PLAN.md).

## Ce que chaque variante montre

- **`r1_boustrophedon/`** (seeds 1–3, commit `002b821`) — tout premier
  essai : méandre en boustrophédon, 1 épingle par nine. **Rejeté à la
  Porte 3** : chaque nine devient un serpentin parallèle en S, les deux
  nines se font face autour du clubhouse central, la moitié de la carte
  reste vide. Contient aussi `layout.svg` (avec les trous, tee/green) en
  plus de `skeleton.svg`.
- **`r2_offset12_1feuille/`** (seeds 1–6, commit `b3645ea`) — marche
  aléatoire sur réseau grossier (remplace le boustrophédon), mais encore
  1 seule épingle par nine. **Accepté sur le mécanisme, refusé sur le
  résultat** : chaque nine reste un unique « doigt » replié, la carte
  reste sous-occupée.
- **`r3_offset12/`** (seeds 1–6, round 3 actuel, offset 12 — identique au
  réseau de `r2`) — correction complète : contour refermé au clubhouse
  (le bug d'ouverture de la seed 2 du round précédent est corrigé), budget
  de sous-arbre imposé (rejet si en dessous du minimum), 2 ou 3 épingles
  par nine obligatoires, épingles et tiges poussées en alternance entre
  les deux nines. Identique à `experiments/elastic_routing/output/step3_skeleton/seed_1..6/skeleton.svg`
  (copie, voir note en bas).
- **`r3_offset20/`** (seeds 1–6, round 3 actuel, offset 20 — réseau à pas
  64 au lieu de 48) — même algorithme que `r3_offset12`, pour juger
  l'effet d'un ruban plus large (fairways/halo plus généreux, grille plus
  grossière : 6×6 nœuds au lieu de 8×8).

## Ce qu'il faut regarder

- **Épingles** : combien de « doigts » par nine (1 pour r1/r2, 2–3 pour
  r3) — plus d'épingles = plus de trous potentiels par zone, moins de
  risque de repli en zigzag.
- **Occupation de la carte** : r1/r2 laissent de grandes zones vides ;
  r3 (12 et 20) couvre la carte plus uniformément.
- **Emboîtement des deux nines** : dans r1, les deux nines sont deux
  blocs disjoints côte à côte (symétrie visible). Dans r3, front (bleu)
  et back (jaune) s'entrelacent davantage autour du clubhouse.
- **Effet de la position du clubhouse** (point blanc) : tirée par la
  seed depuis le round 2 (plus fixée au centre comme r1) — comparer
  comment la forme des deux nines s'adapte selon que le clubhouse tombe
  au centre, au bord ou dans un coin de la grille.
- **Effet de l'offset** (r3_offset12 vs r3_offset20) : ruban plus large,
  réseau plus grossier, mêmes règles — la silhouette reste lisible mais
  plus anguleuse (moins de nœuds disponibles).

## Tirages, temps et longueurs par seed (round 3, `MAX_TREE_ATTEMPTS=1500`)

### offset 12

| Seed | Tirages | Temps | Clubhouse | Feuilles front/back | Longueur front/back |
|---|---:|---:|---|---|---|
| 1 | 19  | 53 ms   | (4, 0) | 2/2 | 816 / 644 |
| 2 | 69  | 132 ms  | (5, 3) | 3/2 | 867 / 644 |
| 3 | 176 | 402 ms  | (3, 3) | 2/2 | 788 / 672 |
| 4 | 89  | 190 ms  | (3, 7) | 2/2 | 596 / 712 |
| 5 | 180 | 350 ms  | (3, 5) | 2/3 | 800 / 768 |
| 6 | 581 | 1140 ms | (2, 0) | 2/2 | 768 / 896 |

### offset 20

| Seed | Tirages | Temps | Clubhouse | Feuilles front/back | Longueur front/back |
|---|---:|---:|---|---|---|
| 1 | 103 | 112 ms | (2, 0) | 2/2 | 832 / 667 |
| 2 | 168 | 177 ms | (2, 4) | 2/2 | 832 / 704 |
| 3 | 187 | 200 ms | (3, 2) | 2/2 | 768 / 821 |
| 4 | 134 | 149 ms | (3, 2) | 2/3 | 554 / 693 |
| 5 | 102 | 115 ms | (3, 1) | 2/2 | 693 / 731 |
| 6 | 81  | 90 ms  | (3, 2) | 3/2 | 731 / 757 |

Aucun temps > 10 s. Le nombre de tirages dépasse régulièrement la cible
« ≤ 50 » du plan (voir PLAN.md, non modifié ce round, et le rapport de
livraison) : la combinaison budget imposé + 2-3 feuilles obligatoires est
nettement plus dure à satisfaire que le round précédent. `MAX_TREE_ATTEMPTS`
a été porté à 1500 plutôt que masqué ; le taux de rejet réel reste
toujours consigné (`attempts_used` dans chaque résultat).

## Note sur les doublons

`experiments/elastic_routing/output/step3_skeleton/seed_1..6/skeleton.svg`
(au niveau racine, produits par `run_step3_skeleton.py`) et
`compare/r3_offset12/seed_*_skeleton.svg` sont des copies identiques
(offset 12 par défaut) : le dossier `compare/` est autonome pour la revue,
le dossier racine reste la sortie "courante" du runner.
