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
  par nine obligatoires, épingles et tiges poussées en alternance entre les
  deux nines. Décalage du contour (`build_contour`) remplacé le 2026-10-07
  par un décalage de polyligne standard (jointure ronde côté convexe par
  arc centré sur le sommet, intersection vérifiée des deux segments
  décalés côté concave, sinon rejet explicite) : élimine les pointes en
  onglet et les caps mordus qui subsistaient aux virages diagonaux serrés
  près d'une feuille avec les deux approches précédentes (lissage de la
  ligne centrale avec ou sans exception pour le sommet voisin d'une
  feuille). **2e passe, même jour** : front et back sont désormais décalés
  comme un seul tour COMBINÉ (`_combined_tour`), pas deux contours
  indépendants chacun refermé par un cap au clubhouse — les deux caps
  (plantés à ~180° l'un de l'autre par construction) se recoupaient
  systématiquement près du clubhouse (100/100 tirages, seeds 1-50 x offsets
  12/20, voir le rapport de livraison). **3e passe, même jour** : la 2e
  passe assignait chaque groupe de points de coupure à UN SEUL des deux
  arcs (tag `'front'`/`'back'` par sommet) — quand la jointure au clubhouse
  est convexe (plusieurs points, pas un seul), l'arc qui ne récupérait pas
  ce groupe perdait son point de retour au clubhouse et se refermait en
  plein milieu de la carte (bout pendant, ex. seed 1 offset 20 à ~48 blocs
  du clubhouse). Corrigé par découpage par INDICE
  (`_split_combined_contour`) : les deux groupes de coupure sont désormais
  inclus EN ENTIER dans les DEUX arcs, qui les partagent à leurs
  extrémités. `front_contour`/`back_contour` sont des ARCS OUVERTS (pas
  deux boucles fermées indépendantes), rendus en `<polyline>`, qui se
  rejoignent maintenant exactement au clubhouse (plus de bout pendant ni
  d'espace visuel artificiel). Identique à
  `experiments/elastic_routing/output/step3_skeleton/seed_1..6/skeleton.svg`
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
| 1 | 8  | 16 ms | (6, 3) | 3/2 | 760 / 608 |
| 2 | 48 | 82 ms | (4, 5) | 3/2 | 712 / 616 |
| 3 | 1  | 17 ms | (5, 4) | 2/3 | 808 / 788 |
| 4 | 24 | 54 ms | (3, 0) | 2/2 | 619 / 568 |
| 5 | 50 | 90 ms | (2, 5) | 2/3 | 644 / 780 |
| 6 | 26 | 42 ms | (2, 6) | 2/2 | 704 / 839 |

### offset 20

| Seed | Tirages | Temps | Clubhouse | Feuilles front/back | Longueur front/back |
|---|---:|---:|---|---|---|
| 1 | 91 | 91 ms | (4, 4) | 2/2 | 731 / 576 |
| 2 | 15 | 21 ms | (1, 2) | 2/2 | 629 / 667 |
| 3 | 2  | 6 ms  | (1, 4) | 2/2 | 539 / 704 |
| 4 | 29 | 31 ms | (5, 2) | 2/2 | 923 / 576 |
| 5 | 23 | 26 ms | (2, 3) | 2/2 | 640 / 795 |
| 6 | 32 | 32 ms | (2, 3) | 2/3 | 720 / 826 |

Aucun temps > 10 s. Le nombre de tirages dépasse régulièrement la cible
« ≤ 50 » du plan (voir PLAN.md, non modifié ce round, et le rapport de
livraison) : la combinaison budget imposé + 2-3 feuilles obligatoires est
nettement plus dure à satisfaire que le round précédent. `MAX_TREE_ATTEMPTS`
a été porté à 1500 plutôt que masqué ; le taux de rejet réel reste
toujours consigné (`attempts_used` dans chaque résultat).

**Régénération du 2026-10-07, 2e passe (tour combiné front+back, voir plus
bas)** : seeds 1, 3, 5, 6 identiques (mêmes tirages, clubhouse, longueurs)
aux deux offsets. Seed 2 (offset 12) et seeds 2, 4 (offset 20) changent à
nouveau : la condition de rejet dépend de la forme du contour COMBINÉ
désormais (un seul passage pour les deux sous-arbres, voir plus bas), donc
un tirage accepté ou rejeté à un numéro de tirage donné peut différer de la
1re passe (qui vérifiait chaque sous-arbre indépendamment). Seed 2 revient
coïncidemment aux valeurs d'avant la 1re passe (48 tirages, (4, 5) /
712-616 en offset 12 ; 15 tirages, (1, 2) / 629-667 en offset 20) ; seed 4
(offset 20) prend des valeurs inédites (29 tirages, (5, 2) / 923-576) :
rien à en déduire sur le mécanisme de croissance de l'arbre lui-même
(inchangé), seulement sur quel tirage franchit le test de contour en
premier.

## Note sur les doublons

`experiments/elastic_routing/output/step3_skeleton/seed_1..6/skeleton.svg`
(au niveau racine, produits par `run_step3_skeleton.py`) et
`compare/r3_offset12/seed_*_skeleton.svg` sont des copies identiques
(offset 12 par défaut) : le dossier `compare/` est autonome pour la revue,
le dossier racine reste la sortie "courante" du runner.

## r4 — squelette par RÉGIONS (`r4_regions_w2/`, `r4_regions_w3/`, `r4_regions_w4/`)

Module `experiments/elastic_routing/regions.py`, runner
`run_step3_regions.py`, tests `tests/test_elastic_routing_regions.py`.
`skeleton.py` (r3) inchangé, sauf la factorisation de
`offset_closed_polyline`, sans changement de comportement. Pas de découpage
en trous ni de `CourseLayout`.

Idée : chaque nine longe le BORD d'une région (tache de cellules) au lieu du
contour d'un arbre. La largeur de la tache sépare l'aller du retour, et
ceux-ci n'ont plus la même forme (fin de l'« effet jumeau » de r3, où
chaque branche devenait deux traits parallèles à 24 blocs).

### Paramètres

- **d = 9** (décalage vers l'intérieur) : c'est le minimum pour que le
  parcours garde un demi-fairway (9) de marge quand la région touche le
  bord de la carte.
- **c = 21** pour w_min 2 et 3 : c'est la contrainte (a) la plus dure, avec
  w_min = 2 : 2c − 18 ≥ 23 ⇒ c ≥ 20,5. Grille 19×19 (399 blocs, marge 0,5).
  (b) couloir : c + 2d = 39 ≥ 23 ; au clubhouse : 2√2·d = 25,5 ≥ 23.
- **c = 19 pour w_min = 4** (grille 21×21) : avec c = 21, une région fait au
  moins 84 blocs de large et aucun tirage n'aboutit (0/30 seeds en 200
  tirages, tous en impasse : deux régions aussi larges ne trouvent pas
  1220 blocs de bord chacune dans une carte de 400). Avec c = 19 (76 blocs),
  30/30 seeds aboutissent. **Les trois variantes n'ont donc pas toutes le
  même c.**
- Largeur minimale de région (w_min·c) : 42 / 63 / 76 blocs. Écart minimal
  entre l'aller et le retour (axe à axe) : 24 / 45 / 58 blocs.
- Fenêtre d'un nine, calculée depuis `PAR_SPECS` (9 trous + 10 tronçons de
  12 à 60) : **1220–2165 blocs**. La croissance s'arrête dès que le parcours
  entre dans la fenêtre, donc toutes les longueurs tombent entre 1225 et 1336.

### Tirages et temps (seeds 1–6, borne 200)

| w_min (c) | tirages s1..s6 | temps s1..s6 (ms) | longueurs front/back |
|---|---|---|---|
| 2 (21) | 1 1 1 1 1 1 | 54 31 30 31 33 28 | 1225–1301 |
| 3 (21) | 3 2 1 4 1 1 | 38 26 25 45 23 24 | 1225–1309 |
| 4 (19) | 10 18 13 4 6 3 | 63 92 98 37 42 39 | 1249–1336 |

Sur les seeds 1–30 (tests), le pire cas est de 2 tirages pour w2, 13 pour
w3 et 51 pour w4. Le détail par seed et les motifs de rejet sont dans
`report.json`.

### Ce qu'il faut regarder

- La bande verte (14 blocs, fairway moyen) montre le parcours. Le bord bleu
  correspond au front (trous 1–9), le bord jaune au back (trous 10–18). Les
  flèches, tous les 60 blocs, donnent le sens de jeu. Les étiquettes
  « départ 1 / retour 9 / départ 10 / retour 18 » sont au losange rouge
  (clubhouse). Le remplissage pâle montre la région, comme échafaudage.
- **Aller et retour** : avec w3 et w4, les deux côtés d'un même lobe ont des
  formes différentes. Avec w2, les lobes fins (42 blocs) redonnent par
  endroits deux bandes parallèles proches, donc encore un effet jumeau.
- **Encoches** : une encoche d'une cellule entre deux lobes de la même
  région produit deux bandes parallèles à 39 blocs. C'est un nouvel effet
  jumeau, côté extérieur (par exemple w3 seed 4 et w4 seeds 4/5, en peigne).
- **Esthétique en grille** : tous les virages sont des angles droits
  arrondis, et le parcours longe souvent le bord de la carte.
- **Occupation** : les nines restent au bas de la fenêtre de longueur, et une
  partie de la carte reste vide, surtout avec w2.
