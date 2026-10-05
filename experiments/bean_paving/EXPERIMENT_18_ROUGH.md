# Essai 18 trous — jeu de règles « rough partagé »

Rappel d'unité : 1 bloc = 3 m (coordonnées Minecraft). Toutes les distances
ci-dessous sont en blocs.

**Portée de cet essai : 350×350 uniquement.** Contrairement au plan initial
(qui prévoyait d'essayer 400 puis 450 si 350 échouait), le périmètre a été
restreint en cours de session à la seule carte 350×350, sur demande
explicite ; 400 et 450 n'ont pas été lancés. Voir « Point de reprise ».

## Règles

Nouveau jeu de règles, activé par `ValidationRules.shared_rough: bool = False`
(désactivé par défaut : comportement et tests existants inchangés). But :
distinguer le **cœur** (fairway, axe bufferisé à `width / 2`) du **rough**
(marge de 5 blocs autour, comme avant). Quand `shared_rough=True` :

1. **Cœur vs rough.** Le rough peut chevaucher le rough d'un autre trou. Les
   cœurs, eux, doivent garder un écart bord-à-bord ≥ `fairway_gap` (5.0
   blocs par défaut) : nouvelle violation `fairway_gap`, qui remplace
   `footprint_collision` dans ce mode. Conséquence directe : un tee ou un
   green ne peut jamais tomber dans le fairway d'un autre trou.
2. **Bord de carte.** Le rough peut sortir de la carte le long du bord ; seul
   le cœur doit rester à `edge_min` blocs du bord (1.0 bloc par défaut).
   Remplace le test `bounds` sur l'empreinte complète.
3. **Antiparallèle.** La règle historique (angle < 15°, distance < 30,
   recouvrement > 40) ne s'applique plus en mode `shared_rough` : deux trous
   aller-retour côte à côte sont autorisés tant que `fairway_gap` est
   respecté.
4. **Pile côte-à-côte (`parallel_stack`), nouvelle règle.** Deux trous sont
   « côte à côte » si une paire de segments d'axes est parallèle OU
   antiparallèle à `parallel_stack_angle_deg` (20°) près, que leurs roughs se
   touchent/chevauchent, et que le recouvrement projeté dépasse
   `parallel_stack_overlap` (40 blocs). Une **pile** est une composante
   connexe de cette relation sur TOUS les trous posés, indépendamment de
   l'ordre de jeu. Violation si une composante dépasse `max_parallel_stack`
   (3 par défaut ; `None` désactive la règle).
5. **Croisement d'axes, clubhouse, banque de haricots** : inchangés.

Tous les paramètres (`fairway_gap`, `edge_min`, `parallel_stack_angle_deg`,
`parallel_stack_overlap`, `max_parallel_stack`) restent dans
`experiments/bean_paving/geometry.py` (`ValidationRules`), comme le reste du
spike.

**Câblage solveur.** `solve_nine`, `solve_course` et `solve_course_joint`
consomment ces règles exclusivement via `geometry.validate` (aucun
contournement ajouté) : vérifié en relisant chaque appel de
`_placement_problems` (`solver.py`) et les filets de sécurité finaux
(`_course_violations`, `_joint_violations`). Un seul raccourci existant a dû
être traité pour rester cohérent : la grille d'occupation heuristique de
`freespace.py` (utilisée uniquement pour le score du beam conjoint, jamais
pour une règle dure) marquait les cellules occupées à partir de l'empreinte
complète (rough) ; en mode `shared_rough`, le rough pouvant légitimement se
chevaucher, elle utilise maintenant le cœur (`freespace.build_grid`). Un
heuristique de score resté inchangé : `solver._state_score` calcule encore
sa boîte englobante et sa marge de bord à partir de l'empreinte complète
(rough), donc un peu pessimiste en mode `shared_rough` près des bords — pas
une règle dure, simple biais de score non corrigé dans cette session.

**Performance.** La première implémentation de `fairway_gap` (calcul de
distance polygone-à-polygone exact sur chaque paire) ralentissait `validate`
d'environ 3× par rapport au mode historique, au point qu'une recherche
`--quick` qui prenait 40 s en legacy ne terminait pas en 120 s. Deux
correctifs, sans changer aucune règle : (1) le cœur était recalculé à chaque
accès (`@property` non mise en cache) — stocké une fois à la génération,
comme `footprint` ; (2) un minorant bon marché (distance entre axes, quelques
segments, moins un rayon de part et d'autre) écarte sans calcul de polygone
les paires manifestement hors de portée d'une violation, pour les trois
règles `fairway_gap`/`footprint_collision`/`parallel_stack`. Résultat :
`validate` en mode `shared_rough` coûte environ le même temps que le mode
historique (mesuré, pas estimé — voir tests de non-régression).

## Résultat

Seed 42, 350×350, `shared_rough=True`, aucune autre règle assouplie.

| Run | complet ? | front | back | total | trials | temps |
|---|---|---|---|---|---|---|
| séquentiel (`solve_course`, params par défaut) | non | 9/9 | 7/9 | **16/18** | 235 314 | 346 s (5 min 46) |
| conjoint (`solve_course_joint`, beam 56) | non | 6/9 | 5/9 | **11/18** | 126 360 | 111 s (1 min 51) |

Aucun des deux n'atteint 18/18 à 350×350. Le séquentiel progresse nettement
par rapport au jeu de règles d'origine (9+1=10 trous dans
`EXPERIMENT_18.md`) : **16 trous au lieu de 10**, le back avance jusqu'à 7/9
au lieu de bloquer dès le 2ᵉ trou. Le conjoint, en revanche, reste proche de
son plafond déjà observé (`EXPERIMENT_18_JOINT.md` : 8-9/18) avec 11/18.

Pars posés (ordre de jeu) :

- séquentiel front (9/9) : 3-4-5-5-3-4-4-4-4
- séquentiel back (7/9, bloqué) : 3-4-4-3-4-4-4
- conjoint front (6/9, bloqué) : 3-3-4-4-5-4
- conjoint back (5/9, bloqué) : 3-3-5-5-4

Pile côte-à-côte la plus grande dans le meilleur état de chaque run (toutes
règles dures déjà respectées, donc ≤ `max_parallel_stack=3`) :

- séquentiel (16 trous posés) : **3** (une pile de 3 trous côte à côte,
  aucune violation puisque le seuil est 3)
- conjoint (11 trous posés) : **2**

**La règle `parallel_stack` n'est pas une cause dominante de rejet** dans
ces deux runs — condition posée pour justifier une variante
`max_parallel_stack=None` (point c des instructions). Causes agrégées sur
toute la recherche :

Séquentiel, front (9/9 posés, 110 610 essais) :

| cause | occurrences | part |
|---|---|---|
| fairway_gap | 74 158 | 50,8 % |
| axis_crossing | 52 738 | 36,2 % |
| bounds | 13 122 | 9,0 % |
| parallel_stack | 2 999 | 2,1 % |
| clubhouse_return | 2 387 | 1,6 % |
| clubhouse_departure | 420 | 0,3 % |

Séquentiel, back (7/9, bloqué à la profondeur 8, 124 704 essais) :

| cause | occurrences | part |
|---|---|---|
| fairway_gap | 103 570 | 41,0 % |
| axis_crossing | 78 393 | 31,0 % |
| bounds | 65 627 | 26,0 % |
| parallel_stack | 3 524 | 1,4 % |
| clubhouse_departure | 1 390 | 0,6 % |

Conjoint (126 360 essais, mort au `global_step=12`, cumul front+back) :

| cause | occurrences | part |
|---|---|---|
| fairway_gap | 70 742 | 37,6 % |
| axis_crossing | 53 710 | 28,5 % |
| bounds | 42 701 | 22,7 % |
| clubhouse_departure | 20 528 | 10,9 % |
| parallel_stack | 528 | 0,3 % |

Dans les deux runs, `fairway_gap` et `axis_crossing` dominent largement
(70-90 % des rejets combinés), suivis de `bounds` ; `parallel_stack` reste
sous 2,1 % partout. **Condition (c) non remplie : aucune variante
`max_parallel_stack=None` n'a donc été lancée** — la relaxer n'aurait eu
qu'un effet marginal mesurable sur ces runs précis, et le faire sans cause
dominante serait sorti du périmètre convenu (« no other rule relaxed »).

Détail par profondeur — séquentiel, front :

| profondeur | parents | essais | acceptés | morts | causes dominantes |
|---|---|---|---|---|---|
| 1 | 1 | 540 | 120 | 0 | clubhouse_departure 420 |
| 2 | 72 | 19 440 | 8 460 | 0 | fairway_gap 10 980, axis_crossing 7 596 |
| 3 | 72 | 17 280 | 6 679 | 0 | fairway_gap 9 880, axis_crossing 6 856 |
| 4 | 72 | 15 480 | 3 807 | 0 | fairway_gap 10 223, axis_crossing 6 648 |
| 5 | 72 | 14 040 | 2 541 | 3 | fairway_gap 10 432, axis_crossing 7 447 |
| 6 | 72 | 14 040 | 2 018 | 13 | fairway_gap 11 074, axis_crossing 8 680 |
| 7 | 72 | 12 960 | 3 427 | 1 | fairway_gap 9 318, axis_crossing 7 011 |
| 8 | 72 | 10 350 | 1 537 | 3 | fairway_gap 8 809, axis_crossing 6 055 |
| 9 | 72 | 6 480 | 651 | 4 | fairway_gap 3 442, axis_crossing 2 445, clubhouse_return 2 387 |

Détail par profondeur — séquentiel, back (bloqué, 0 survivant à la
profondeur 8) :

| profondeur | parents | essais | acceptés | morts | causes dominantes |
|---|---|---|---|---|---|
| 1 | 1 | 1 728 | 26 | 0 | clubhouse_departure 1 390 |
| 2 | 12 | 5 184 | 928 | 0 | fairway_gap 4 256, axis_crossing 3 445 |
| 3 | 72 | 27 648 | 1 765 | 1 | fairway_gap 23 623, axis_crossing 18 907, bounds 13 641 |
| 4 | 72 | 24 768 | 828 | 20 | axis_crossing 11 249, fairway_gap 17 320, bounds 20 212 |
| 5 | 72 | 22 464 | 727 | 20 | axis_crossing 11 312, fairway_gap 16 267, bounds 17 956 |
| 6 | 72 | 22 464 | 437 | 21 | fairway_gap 21 349, axis_crossing 15 018, bounds 7 891 |
| 7 | 72 | 19 872 | 5 | 68 | fairway_gap 19 867, axis_crossing 17 628, bounds 5 925 |
| 8 | 4 | 576 | 0 | 4 | fairway_gap 576, axis_crossing 576 |

Détail par pas — conjoint (alternance front/back, mort au `global_step=12`) :

| pas | côté | parents | essais | acceptés | causes dominantes |
|---|---|---|---|---|---|
| 1 | front | 1 | 540 | 172 | clubhouse_departure 368 |
| 2 | back | 56 | 30 240 | 7 446 | clubhouse_departure 20 160, fairway_gap 2 634 |
| 3 | front | 56 | 15 120 | 6 223 | fairway_gap 8 897, axis_crossing 6 939 |
| 4 | back | 56 | 15 120 | 4 906 | fairway_gap 10 214, axis_crossing 8 369 |
| 5 | front | 56 | 10 080 | 1 556 | fairway_gap 6 344, bounds 5 062, axis_crossing 4 584 |
| 6 | back | 56 | 10 080 | 1 304 | fairway_gap 6 959, bounds 4 445, axis_crossing 5 378 |
| 7 | front | 56 | 10 080 | 374 | bounds 7 634, fairway_gap 7 088, axis_crossing 4 967 |
| 8 | back | 56 | 10 080 | 268 | bounds 8 071, fairway_gap 7 461, axis_crossing 5 562 |
| 9 | front | 56 | 9 000 | 237 | bounds 7 188, fairway_gap 6 464, axis_crossing 4 485, parallel_stack 270 |
| 10 | back | 56 | 8 640 | 70 | fairway_gap 7 456, bounds 7 010, axis_crossing 5 770, parallel_stack 167 |
| 11 | front | 50 | 7 200 | 1 | fairway_gap 7 045, axis_crossing 5 933, bounds 3 206, parallel_stack 91 |
| 12 | back | 1 | 180 | 0 | fairway_gap 180, axis_crossing 155, bounds 85 |

Sorties : `output/seed42_rough_350_seq_failed.{json,svg}`,
`output/seed42_rough_350_joint_failed.{json,svg}`. Chaque SVG distingue le
cœur (plein) du rough (translucide, même teinte), le front (trait continu)
du back (tirets), et surlignerait en rose tout trou appartenant à une pile
`parallel_stack` en violation — aucune pile en violation dans ces deux
résultats, donc le surlignage n'apparaît pas. Galerie de violations étendue
dans `render_violations.render_shared_rough_gallery`
(`output/geometry_violations_shared_rough.svg`) : un cas par règle
(chevauchement de rough accepté, écart fairway refusé, cœur à la limite du
bord accepté/refusé, paire antiparallèle côte-à-côte acceptée, pile de 4
refusée).

## Variantes

Une seule variante était prévue au-delà de (a) séquentiel/conjoint à 350 :
(c) `max_parallel_stack=None` si la pile était une cause dominante de rejet.
Comme détaillé ci-dessus, `parallel_stack` reste sous 2,1 % des rejets dans
les deux runs (c) **n'a pas été déclenchée** — ni testée, pour rester dans
le périmètre explicitement validé (« no other rule relaxed » sauf
condition remplie). Aucune autre variante (tailles 400/450, poids de
recherche, etc.) n'a été lancée : voir « Point de reprise ».

## Conclusion

Le jeu de règles `shared_rough` change nettement le paysage de recherche à
350×350 sans assouplir aucune contrainte dure de collision : en séparant le
fairway (contrainte stricte, `fairway_gap`) du rough (chevauchable), le
séquentiel passe de 10 à **16/18** trous posés, et le conjoint progresse
aussi (8-9 → **11/18**) bien qu'il reste nettement derrière le séquentiel,
comme avant ce changement de règles. Les causes de rejet dominantes se sont
déplacées : `footprint_collision` (bloquant dans l'ancien jeu de règles) a
disparu, remplacé par `fairway_gap` (bloquant à son tour, mais sur une
enveloppe deux fois plus étroite) comme première ou deuxième cause partout,
`axis_crossing` restant la seule contrainte totalement inchangée et toujours
très présente (28-36 % des rejets). `bounds` (désormais calculé sur le
cœur, pas l'empreinte complète) a reculé en proportion relative mais reste
significatif en fin de recherche (jusqu'à 26 % côté back séquentiel,
profondeurs 3 à 6) — le mode `shared_rough` assouplit le bord pour le rough,
pas pour le fairway, donc l'effet n'est pas aussi fort qu'espéré sur une
carte où le rough débordait déjà peu.

La règle `parallel_stack`, elle, s'est révélée **non limitante** sur cette
seed à cette taille : elle ne rejette qu'une poignée de trajectoires (sous
2,1 %) même quand plusieurs trous se retrouvent effectivement côte à côte
(pile de taille 3 observée dans le meilleur état séquentiel, sans
violation). Rien n'indique qu'elle bride la recherche plus que les règles
dures historiques (fairway, croisement, bord).

Aucun des deux solveurs n'atteint 18/18 à 350×350 avec `shared_rough`. Le
séquentiel s'en approche sensiblement plus que dans n'importe quel essai
précédent à cette taille (16/18, contre 10/18 avant ce changement de
règles), ce qui suggère que la séparation fairway/rough libère une vraie
marge de manœuvre géométrique — mais cette session n'a pas testé si cette
marge suffit à atteindre 18/18, à 350 ou à une taille plus grande.

## Point de reprise

**Ce qui a été fait, honnêtement.** Seules les tailles 350×350 ont été
testées (séquentiel et conjoint), avec les paramètres par défaut des deux
solveurs (`solve_course`, `solve_course_joint`) et `shared_rough=True`,
tous les autres paramètres `ValidationRules`/`SolverParams` à leur valeur
par défaut. Aucune variante de poids de recherche, de beam, ni de taille de
carte 400/450 n'a été essayée : le plan initial prévoyait d'escalader vers
400 puis 450 si 350 échouait, mais la portée de cette session a été
explicitement restreinte à 350×350 en cours de route, sur demande de
l'utilisateur. **La décision 400/450 reste donc entièrement ouverte** et
n'a pas été prise par cette session, ni dans un sens ni dans l'autre.

Pour la reprendre :

1. Relancer `render_course.py --shared-rough` et `render_joint.py
   --shared-rough` directement à 400 puis 450 (`--size 400`, `--size 450`),
   seed 42, avant d'envisager tout réglage de poids — c'est l'étape prévue
   par le plan initial, non encore exécutée.
2. Si 350 doit rester la cible, les leviers suivants n'ont pas été essayés :
   régler `fairway_gap`/`edge_min` eux-mêmes (actuellement aux valeurs
   proposées, 5.0/1.0, jamais variées) ; ou reprendre le diagnostic déjà
   posé dans `EXPERIMENT_18_JOINT.md` sur le conjoint (pénalité d'espace
   libre non discriminante, `freespace.py` à grille `CELL_SIZE=5` trop
   grossière) — ce diagnostic n'a pas été réévalué avec `shared_rough`
   activé (la grille utilise maintenant le cœur, voir « Règles », mais sa
   résolution n'a pas changé).
3. Ne pas relancer de benchmark multi-seeds (discipline §7) avant un 18/18
   validé indépendamment, à quelque taille que ce soit.

Conserver la seed témoin 42, la banque `8/20/8`, le validateur indépendant
(`geometry.validate`) et `golfgen/loop_router.py` inchangé.

## Essai 400×400

**Portée : un seul lancement, séquentiel uniquement (`solve_course`), seed
42, 400×400, `shared_rough=True`, mêmes paramètres de beam que le run
séquentiel 350 ci-dessus (`SolverParams` par défaut des deux nines, aucun
réglage).** Deux différences assumées par rapport au run 350 : la taille de
carte et `clubhouse_clear_radius=10` (règle ajoutée après ce run 350 dans
une session ultérieure, voir `EXPERIMENT_18_HALFPLANE.md` point A — absente
de la comptabilisation des causes de rejet du run 350 ci-dessus). Les deux
facteurs sont donc confondus dans ce résultat : rien ici ne permet de dire
lequel des deux explique le gain, seulement que leur combinaison suffit.

Commande : `render_course.py --seed 42 --size 400 --shared-rough
--fairway-gap 5 --edge-min 1 --max-parallel-stack 3
--clubhouse-clear-radius 10 --halfplane-weight 0`.

### Résultat

| Run | complet ? | front | back | total | trials | temps |
|---|---|---|---|---|---|---|
| séquentiel, 400×400 | **oui** | 9/9 | 9/9 | **18/18** | 292 482 | ~7 min (estimé, non chronométré précisément — lancé en tâche de fond ; extrapolé du débit mesuré à 350, ≈680 essais/s) |

Contre 16/18 (front 9/9, back 7/9) à 350×350 avec les mêmes règles et les
mêmes paramètres de recherche : le passage à 400×400 (+ exclusion
clubhouse) fait franchir le plafond observé à 350, le back allant cette
fois jusqu'au bout au lieu de se bloquer à la profondeur 8.

Pars posés (ordre de jeu) :

- front (9/9) : 3-4-4-4-3-4-5-4-5
- back (9/9) : 4-4-4-5-4-4-3-5-3

**Validation indépendante sur les 18 trous.** Les beans ont été reconstruits
depuis le JSON exporté (banque + id + transform) et revalidés avec
`geometry.validate`, exactement comme `course_solver._course_violations` le
fait : `validate(front, rules)`, `validate(back, rules)` (liaisons
intra-nine comprises) et `validate(front + back, rules, check_links=False)`
(contraintes croisées, sans le lien 9→10 qui traverse le clubhouse) —
**les trois appels renvoient une liste vide**, donc aucune règle dure n'est
violée sur l'ensemble des 18 trous, confirmé indépendamment du run.

**Pile côte-à-côte la plus grande.** Recalculée directement (composantes
connexes de la relation côte-à-côte, sans filtrage par seuil) sur les 18
trous posés : tailles de composantes `[3, 2, 2, 2, 1×9]` — la plus grande
pile est de **3**, exactement au seuil `max_parallel_stack=3`, donc jamais
en violation. Même taille de pile maximale qu'à 350×350.

**Causes de rejet, agrégées sur toute la recherche (front + back, 292 482
essais, décompte brut des causes — un essai peut échouer plusieurs règles à
la fois, donc la somme des causes dépasse le nombre d'essais, comme dans le
run 350 ci-dessus) :**

| cause | occurrences | part |
|---|---|---|
| fairway_gap | 207 390 | 45,3 % |
| axis_crossing | 151 373 | 33,0 % |
| bounds | 77 582 | 16,9 % |
| parallel_stack | 7 578 | 1,7 % |
| clubhouse_clear | 6 513 | 1,4 % |
| clubhouse_return | 6 219 | 1,4 % |
| clubhouse_departure | 1 414 | 0,3 % |

Même hiérarchie qu'à 350×350 (`fairway_gap` puis `axis_crossing` puis
`bounds` dominent largement, `parallel_stack` reste marginal) ; la seule
nouveauté est `clubhouse_clear` (règle inexistante au moment du run 350),
qui reste elle aussi marginale (1,4 %).

Détail par profondeur — back (9/9, complet cette fois, à comparer avec le
blocage à la profondeur 8 du run 350) :

| profondeur | parents | essais | acceptés | morts | causes dominantes |
|---|---|---|---|---|---|
| 1 | 1 | 1 728 | 151 | 0 | clubhouse_departure 1 054, fairway_gap 523, axis_crossing 323 |
| 2 | 72 | 31 104 | 9 196 | 0 | fairway_gap 21 908, axis_crossing 16 327, parallel_stack 149 |
| 3 | 72 | 28 944 | 5 014 | 0 | fairway_gap 18 209, axis_crossing 12 553, bounds 12 834 |
| 4 | 72 | 25 920 | 1 177 | 2 | bounds 21 657, fairway_gap 15 176, axis_crossing 9 900 |
| 5 | 72 | 23 472 | 664 | 20 | bounds 18 940, fairway_gap 15 912, axis_crossing 10 986 |
| 6 | 72 | 22 896 | 1 338 | 26 | fairway_gap 20 790, axis_crossing 15 172, bounds 7 029 |
| 7 | 72 | 20 736 | 234 | 37 | fairway_gap 20 486, axis_crossing 15 572, bounds 6 151 |
| 8 | 72 | 16 704 | 333 | 29 | fairway_gap 16 335, axis_crossing 13 722, bounds 225 |
| 9 | 72 | 10 368 | 8 | 70 | clubhouse_return 4 084, clubhouse_clear 3 200, fairway_gap 6 276 |

À la profondeur 8, le run 350 ne gardait plus aucun survivant (0 accepté,
68 morts) ; ici 333 acceptés sur 72 parents, et la profondeur 9 réussit à
en garder 4 jusqu'à la fermeture (`kept=4`, voir diagnostics JSON) au lieu
de mourir.

### Interprétation

`solver._scaled_target_radius` multiplie le profil d'anneau fixe par
`map_scale = min(width, height) / 350`, donc à 400×400 ce facteur est
`400/350 ≈ 1,14` : les anneaux cibles des profondeurs d'expansion (2 à 8)
sont environ 14 % plus larges qu'à 350, ce qui donne mécaniquement plus de
surface disponible pour que `fairway_gap`/`axis_crossing` (les deux causes
dominantes, inchangées en proportion relative) finissent par laisser passer
suffisamment d'états pour fermer le parcours — exactement le goulot qui
tuait le back à la profondeur 8 à 350×350. Cela confirme, sur cette seed et
ce jeu de paramètres précis, l'hypothèse ouverte à la fin du run 350
(« cette session n'a pas testé si cette marge suffit à atteindre 18/18 »).

### Limites honnêtes

- **Un seul tirage** (seed 42) : aucun benchmark multi-seed n'a été lancé,
  conformément à la discipline §7 du `PLAN.md` (pas de benchmark avant un
  18/18 validé indépendamment — c'est fait ici, mais pour une seule seed).
- **Deux facteurs confondus** : taille de carte et `clubhouse_clear_radius`
  changent en même temps par rapport au run 350 ; ce résultat ne dit pas si
  400×400 seul (sans l'exclusion clubhouse) aurait suffi, ni l'inverse.
- Aucun réglage de poids, de beam ni de `fairway_gap`/`edge_min` n'a été
  essayé à 400×400 : les paramètres sont strictement ceux du run 350
  séquentiel, seule la carte change (plus la règle clubhouse déjà en place
  depuis la session précédente).
- Le temps de recherche n'a pas été chronométré avec un minuteur explicite
  (exécution en tâche de fond) ; la valeur ci-dessus est une extrapolation,
  pas une mesure directe.
