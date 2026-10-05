# Essai 18 trous — exclusion clubhouse, biais de demi-plan, recherche d'orientation

Rappel d'unité : 1 bloc = 3 m (coordonnées Minecraft). Toutes les distances
ci-dessous sont en blocs.

**Portée de cet essai : 350×350, solveur séquentiel uniquement, seed 42.**
Aucune autre taille ni seed n'a été lancée (voir « Point de reprise »).

## Décision préalable : abandon du solveur conjoint

Retour utilisateur sur le rendu SVG du run `shared_rough` (`EXPERIMENT_18_ROUGH.md`) :
visuellement très correct, mais (1) le clubhouse tombait au milieu du
fairway du trou 9, un angle mort du validateur ; (2) le front s'étalait sur
toute la carte au lieu de laisser de la place pour le back. Décision
utilisateur du 2026-10-04, documentée dans `PLAN.md` : **le solveur conjoint
(`joint_solver.py`, `solve_course_joint`) est abandonné** — ses sorties sont
jugées trop symétriques (deux nines qui se répondent en miroir). Le code
reste dans le dépôt pour référence mais n'est plus lancé. Cette session ne
travaille que sur le solveur séquentiel (`solve_course`).

## Règles et mécanismes ajoutés

### A. Exclusion clubhouse (règle dure)

Nouveau champ `ValidationRules.clubhouse_clear_radius` (défaut 10 blocs,
`None` désactive). Actif uniquement en mode `shared_rough` (mode historique
inchangé, byte-identique — la vérification est dans la branche
`if rules.shared_rough:` de `validate`). Règle : aucun **cœur** de fairway
ne peut intersecter le disque de ce rayon autour du clubhouse ; le rough y
est autorisé (répond directement au problème (1) du retour utilisateur).
Position du clubhouse exposée par `ValidationRules.clubhouse` (propriété
calculée `(width/2, height/2)`, la même formule que `course_solver.py` et
`solver.py` calculent déjà séparément) : `validate` reste l'oracle unique,
aucun paramètre supplémentaire à faire circuler. Câblée exclusivement via
`geometry.validate`, donc héritée automatiquement par `solve_nine`,
`solve_course`, `solve_course_joint` et le regard de fermeture
(`_has_closing_move`) sans aucune modification de ces fonctions.

### B. Biais souple de demi-plan (score uniquement, jamais une règle dure)

Nouveau module `halfplane.py`. Une droite passant par le clubhouse à l'angle
`theta_deg` partage la carte en deux ; le camp "back" est celui vers lequel
pointe `unit_vector(theta_deg)`. Le **front** est pénalisé dans son score de
beam (`solver._state_score`, jamais dans `validate`) quand un trou empiète
dans le camp back ; le **back reste libre** (son propre `halfplane_weight`
reste à 0). Pour éviter l'effet "deux nines collées" signalé par
l'utilisateur sur un partage dur précédent, aucune pénalité ne s'applique
dans une bande de transition (`halfplane_band`, 40 blocs par défaut) de part
et d'autre de la droite ; au-delà, la pénalité grandit de façon lisse
(quadratique en profondeur d'intrusion). Profondeur mesurée sur
l'**empreinte complète** (tous les sommets du rough), pas un centroïde +
rayon : un centroïde sous-estimerait l'intrusion d'un haricot coudé ou
asymétrique, alors que le maximum de projection sur les sommets capture
exactement la pointe qui dépasse — ce que l'utilisateur veut éviter de voir
sur le rendu. Nouveaux champs `SolverParams.halfplane_weight/theta_deg/band`,
défaut `weight=0.0` (désactivé, comportement inchangé). `solve_course`
accepte des surcharges `halfplane_*` qui ne modifient que `front_params`.

### C. Recherche d'orientation

Nouveau script `orientation_search.py` : lance `solve_course` indépendamment
pour `theta ∈ {0°, 90°, 180°, 270°}`, en parallèle (processus, un par angle,
jusqu'à 16 cœurs disponibles). Chaque run est déterministe par
`(seed, theta)` et ne partage aucun état mutable avec les autres ; la
parallélisation ne change donc jamais le résultat, seulement le temps total
(vérifié : mêmes résultats en exécution séquentielle d'un run isolé pendant
le développement). Sélection du meilleur run (`pick_best`) : un 18/18 validé
d'abord, sinon le plus de trous posés, égalité tranchée par le score le plus
bas (convention du beam search : plus bas = meilleur).

### D. Diagnostic de démarcation (rapport uniquement, aucun effet sur la recherche)

Dans `halfplane.py` : `wrong_side_holes` (nombre de trous dont le centroïde
tee-green dépasse la bande du côté du camp de l'AUTRE nine) et
`interleave_pairs` (nombre de paires front/back dont les roughs se touchent
ou se chevauchent — proxy de l'effet visuel "deux nines collées"). Calculés
systématiquement dans `CourseSolveResult.demarcation`, qu'un biais ait été
appliqué ou non, et affichés sur chaque SVG.

## Choix du poids

Deux poids testés, comme prévu par le protocole (un poids, puis un second si
les 4 orientations échouent toutes au premier) :

- **`halfplane_weight = 0.01`** (premier essai). Rationale : à une
  profondeur d'intrusion de ~60 blocs (plausible vu la taille de carte), la
  pénalité vaut `0.01 × 60² = 36`, du même ordre de grandeur que les autres
  termes déjà réglés du score (`bbox_weight` ~36 pour une bbox typique,
  pénalité de bord jusqu'à ~5.6) : un simple départage, pas une force
  dominante.
- **`halfplane_weight = 0.1`** (second essai, les 4 orientations ayant
  échoué au premier poids — aucune n'atteint 18/18). Rationale : à la même
  profondeur de ~60 blocs, la pénalité vaut `0.1 × 60² = 360`, du même ordre
  que le saut de score ±80 qu'applique déjà le regard de fermeture
  (`_has_closing_move`) à la profondeur 8 — une vraie force de pilotage du
  beam, pas un simple bruit, pour tester sérieusement si séparer
  délibérément les deux nines peut combler l'écart vers 18/18.

Les sorties conservées dans `output/` sont celles du second poids (0.1),
retenu comme résultat final — voir conclusion.

## Résultat

Seed 42, 350×350, `shared_rough=True`, `clubhouse_clear_radius=10`,
`fairway_gap=5.0`, `edge_min=1.0`, `max_parallel_stack=3` (aucune autre
règle assouplie), `halfplane_band=40.0`, solveur séquentiel uniquement.

### Poids 0.01

| theta | front | back | total | temps | hors-camp | paires collées |
|---|---|---|---|---|---|---|
| 0° | 9/9 | 1/9 | 10/18 | 154.3 s | 2 | 1 |
| 90° | 9/9 | 1/9 | 10/18 | 162.0 s | 2 | 0 |
| 180° | 9/9 | 6/9 | 15/18 | 438.0 s | 0 | 0 |
| 270° | 9/9 | 7/9 | **16/18** | 438.0 s | 0 | 3 |

Meilleur : θ=270°, 16/18, aucun 18/18.

### Poids 0.1 (retenu, sorties dans `output/`)

| theta | front | back | total | temps | hors-camp | paires collées |
|---|---|---|---|---|---|---|
| 0° | 9/9 | 6/9 | 15/18 | 356.9 s | 0 | 1 |
| 90° | 9/9 | 7/9 | 16/18 | 443.7 s | 1 | 0 |
| 180° | 9/9 | 6/9 | 15/18 | 313.9 s | 0 | 1 |
| 270° | 9/9 | 7/9 | **16/18** | 378.5 s | 0 | 3 |

Meilleur (`pick_best`) : θ=270° (égalité de trous avec θ=90°, départagée par
le score). Aucun 18/18 non plus. Temps total de la recherche parallèle ≈ le
run le plus lent (443.7 s), les 4 processus tournant simultanément sur les
16 cœurs disponibles.

Aucun des deux poids n'atteint 18/18 à 350×350 avec le solveur séquentiel.

### Ce que le second poids a changé — et ce qu'il n'a pas changé

Le nombre d'essais du **front** est strictement identique (110 610, la même
valeur que le run sans biais d'`EXPERIMENT_18_ROUGH.md`) pour les 4 angles
**et pour les deux poids**. Ce nombre dépend de la largeur du beam (72,
restée pleine à chaque profondeur) et des templates/transformations
essayées par état, pas du score — il n'implique donc pas que le trajet final
du front soit identique partout, seulement que la structure de l'arbre
exploré ne s'est jamais effondrée. Dans les faits, le trajet final du front
n'a visiblement changé qu'aux angles où le biais était en tension avec le
secteur de départ déjà câblé en dur dans `solver.py`
(`departure_angles=(300, 330, 0, 30, 60)`, grossièrement est/nord-est) : aux
angles 180°/270°, le camp "front" favorisé coïncide à peu près avec ce
secteur déjà préféré, et le résultat ne change presque pas entre les deux
poids (15-16/18 dans les deux cas, `hors-camp=0` dès le poids faible). Aux
angles 0°/90°, le camp "front" favorisé s'oppose à ce secteur ; le poids
faible (0.01) ne suffit pas à le faire bouger (`hors-camp=2`, back écrasé à
1/9) alors que le poids fort (0.1) le fait nettement progresser
(`hors-camp` tombe à 0 ou 1, back remonte à 6-7/9). **Le poids fort rend donc
la recherche beaucoup plus robuste au choix d'angle** (écart max 15-16/18
contre 10-16/18 au poids faible) sans repousser le plafond déjà observé sans
aucun biais (16/18, `EXPERIMENT_18_ROUGH.md`).

### Causes de rejet (poids 0.1, agrégées sur toute la recherche)

| theta | côté | fairway_gap | axis_crossing | bounds | clubhouse_clear | parallel_stack |
|---|---|---|---|---|---|---|
| 0° | front | 48,1 % | 34,3 % | 10,1 % | 2,9 % | 2,7 % |
| 0° | back | 39,1 % | 28,7 % | 25,5 % | — | 6,1 % |
| 90° | front | 49,1 % | 35,2 % | 8,9 % | 3,0 % | 2,1 % |
| 90° | back | 41,6 % | 31,4 % | 23,7 % | — | 2,5 % |
| 180° | front | 49,0 % | 35,0 % | 8,8 % | 3,1 % | 2,2 % |
| 180° | back | 41,0 % | 30,5 % | 25,9 % | — | 1,8 % |
| 270° | front | 49,1 % | 34,6 % | 8,7 % | 3,1 % | 2,4 % |
| 270° | back | 39,0 % | 28,0 % | 27,3 % | — | 5,2 % |

`clubhouse_clear` (nouvelle règle, point A) ne rejette qu'environ 3 % des
essais côté front, stable sur les 4 angles — cohérent avec un rayon de 10
blocs très petit devant la carte (350×350) : elle ferme un angle mort
géométrique précis (le clubhouse au milieu d'un fairway) sans devenir une
contrainte dominante. `fairway_gap` et `axis_crossing` restent, comme dans
`EXPERIMENT_18_ROUGH.md`, les deux causes qui dominent largement (70-85 %
cumulées) partout, suivies de `bounds` ; le biais de demi-plan ne déplace pas
ce classement, il ne fait que changer *quels* états survivent le beam, pas
*pourquoi* un essai donné est rejeté.

Sorties : `output/seed42_halfplane_350_theta{0,90,180,270}_failed.{json,svg}`
(poids 0.1, retenu) et `output/seed42_halfplane_350_summary.json`. Chaque
SVG distingue front (plein) / back (tirets), cœur plein / rough translucide
(héréité de `shared_rough`), dessine le disque d'exclusion clubhouse (rayon
réel, pointillé), la droite de démarcation et sa bande de transition
(rose, très faible opacité), et affiche les statistiques de démarcation en
pied de page.

## Conclusion

Les trois mécanismes demandés (exclusion clubhouse dure, biais souple de
demi-plan, recherche multi-orientation parallèle) sont en place, testés
unitairement, et câblés exclusivement via `geometry.validate` /
`solver._state_score` — aucun raccourci, légataire ou mode legacy touché. Le
diagnostic de démarcation confirme objectivement que l'effet "deux nines
collées" signalé par l'utilisateur sur l'ancien partage dur **ne se
reproduit pas ici** : `hors-camp` tombe à 0 pour 3 des 4 angles au poids
retenu, et le nombre de paires front/back dont le rough se touche
(`paires collées`) reste faible (0 à 3 sur 9×9=81 paires possibles).

Mais le résultat géométrique brut **ne s'est pas amélioré** : le meilleur
run (θ=270°, 16/18) égale exactement le meilleur résultat déjà obtenu sans
aucun biais de demi-plan ni exclusion clubhouse
(`EXPERIMENT_18_ROUGH.md`, séquentiel 9+7=16/18). L'hypothèse du biais
souple — que forcer le front à rester dans "sa" moitié libérerait assez
d'espace pour que le back ferme son neuvième trou — **n'est pas confirmée**
à 350×350 avec les deux poids essayés : le plafond reste 16/18, porté par
`fairway_gap` et `axis_crossing`, deux contraintes dures que le biais de
score ne peut pas, par construction, assouplir. Le gain visible du poids
fort est la **robustesse au choix d'angle** (15-16/18 partout plutôt que
10-16/18), pas un dépassement du plafond.

L'exclusion clubhouse (point A), elle, répond concrètement au défaut visuel
signalé par l'utilisateur (clubhouse au milieu du fairway du trou 9) : elle
est maintenant une règle dure systématiquement vérifiée, pour un coût de
rejet marginal (~3 % des essais).

## Point de reprise

**Ce qui a été fait, honnêtement.** Seed 42, carte 350×350 uniquement,
solveur séquentiel uniquement (conjoint abandonné, voir plus haut). Deux
poids de biais de demi-plan essayés (0.01 puis 0.1, protocole respecté) sur
4 angles chacun, tous avec `clubhouse_clear_radius=10`,
`halfplane_band=40`, et sans toucher aux autres règles (`fairway_gap`,
`edge_min`, `max_parallel_stack=3` inchangés). Aucune autre seed, aucune
autre taille de carte (400/450 restent non lancées, question déjà ouverte
depuis `EXPERIMENT_18_ROUGH.md`).

Pour la reprendre :

1. Le plafond 16/18 à 350×350 semble tenir à `fairway_gap`/`axis_crossing`
   (70-85 % des rejets, stable depuis `EXPERIMENT_18_ROUGH.md` et inchangé
   par le biais de demi-plan) : une piste non essayée serait d'augmenter
   `halfplane_band` ou `halfplane_weight` encore davantage (au-delà de 0.1),
   ou de l'appliquer aussi, avec un poids plus faible, côté back (ce que le
   protocole de cette session excluait explicitement — back toujours libre).
2. 400/450 restent la piste la plus probable pour dépasser 16/18 (plus
   d'espace brut), toujours non lancée par discipline de session (périmètre
   explicitement limité à 350×350 cette fois encore).
3. Le solveur conjoint reste abandonné (décision utilisateur) : ne pas le
   relancer sans décision contraire explicite.
4. Conserver la seed témoin 42, le validateur indépendant (`geometry.validate`,
   maintenant avec l'exclusion clubhouse) et `golfgen/loop_router.py`
   inchangé.
