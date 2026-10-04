# Essai 18 trous — solveur conjoint front/back (incrément B)

## Résultat

Le solveur conjoint (`joint_solver.search_joint`, incrément A) fait grandir
front et back en alternance sur la même carte 350×350, avec quota global
`4/10/4` et pénalité d'espace libre (`freespace.py`) sur les survivants du
beam. Aucune des trois variantes essayées n'atteint 18/18 ; aucune ne dépasse
le meilleur état déjà obtenu par le solveur séquentiel (`EXPERIMENT_18.md`,
front 9/back 1 = 10 trous au total).

| Run | beam | freespace (weight / min_corridor) | front | back | total | trials | temps | mort à |
|---|---|---|---|---|---|---|---|---|
| 1 (défaut) | 56 | 1.0 / 15.0 | 5/9 | 4/9 | 9 | 101 430 | 54,5 s | step 10 (back, 0 accepté) |
| 2 (beam large) | 100 | 1.0 / 15.0 | 4/9 | 4/9 | 8 | 198 540 | 126,0 s | step 9 (front, 0 accepté) |
| 3 (pénalité forte) | 56 | 4.0 / 25.0 | 5/9 | 4/9 | 9 | 101 430 | 54,9 s | step 10 (back, 0 accepté) |

Le run 3 reproduit **exactement** les mêmes comptes de trials/acceptés/rejetés
que le run 1 à chaque profondeur, et place les mêmes haricots aux mêmes
positions (seul le champ `score` diffère dans le JSON, de la valeur de la
pénalité ajoutée). Voir « Conclusion » : ce n'est pas une coïncidence, c'est
un bug de câblage qui rend la pénalité inerte sur la trajectoire de
recherche.

Premier trou de chaque nine (congestion départ clubhouse), identique sur les
trois runs car indépendant des leviers testés :

- **front** (`global_step=1`) : 540 essais, 172 acceptés, 368 rejets
  `clubhouse_departure` (le tee doit s'éloigner du clubhouse) ;
- **back** (`global_step=2`) : 30 240 essais (run1/3) ou 54 000 (run2), ~20 %
  acceptés, dominés par `clubhouse_departure` (20 160 / 36 000) puis
  `footprint_collision` (déjà le front posé bloque une partie du cercle de
  départ du back) et `axis_crossing`.

Causes dominantes par profondeur (run 1, représentatif des trois) :
`footprint_collision` et `axis_crossing` dominent dès la profondeur 2–4,
puis `bounds` (hors-carte) devient la cause majoritaire ou co-majoritaire à
partir de la profondeur 5 jusqu'à la mort du beam, avec `antiparallel` en
hausse constante. Le taux d'acceptation s'effondre sous 1 % dès la
profondeur 7 (35/10 080, puis 39/6 300, 8/3 510, 0/360).

JSON + SVG de l'état final de chacun des trois runs dans `output/` :
`seed42_joint_350_run1_failed.{json,svg}`,
`seed42_joint_350_run2_failed.{json,svg}`,
`seed42_joint_350_run3_failed.{json,svg}`.

## Variantes essayées

1. **Run 1 — défaut (`beam_width=56`)** : reproduit le smoke test non réglé
   (front 5/9, back 4/9, 54 s, mort au step 10). Choisi comme témoin pour
   mesurer l'effet des deux leviers suivants.
2. **Run 2 — beam élargi (`beam_width=100`)** : motivé par l'effondrement du
   nombre de parents du run 1 en fin de partie (56 → 35 → 39 → 4 aux steps
   7–10) alors que le taux d'acceptation chute sous 1 % — hypothèse qu'un
   beam plus large préserverait plus de profils de quota rares jusqu'à la
   profondeur critique. Résultat : **pire**, pas meilleur (front 4/9, back
   4/9, mort un step plus tôt) pour 2,3× le temps de calcul. Les causes de
   rejet dominantes (`bounds`, `footprint_collision`) restent dans les mêmes
   proportions qu'au run 1 — élargir le beam ajoute de la diversité de
   trajectoires mais ne change rien à la saturation géométrique sous-jacente.
3. **Run 3 — pénalité d'espace libre renforcée (`freespace_weight=4.0`,
   `freespace_min_corridor=25.0`)** : motivé par l'hypothèse que la pénalité
   d'espace libre, en se déclenchant plus tôt (corridor jugé insuffisant dès
   25 blocs au lieu de 15) et plus fort, pourrait pousser le beam à
   préserver de la place avant la profondeur 5 où `bounds` explose. Résultat
   : **strictement identique** au run 1 à chaque étape (mêmes trials, mêmes
   acceptés, mêmes rejets, mêmes haricots placés) — la pénalité n'a eu
   aucun effet mesurable sur la trajectoire de recherche. Diagnostic exact
   ci-dessous.

Aucune règle géométrique dure n'a été modifiée ni assouplie ; la carte reste
350×350 sur les trois runs.

## Conclusion

Aucun 18/18, et le total de trous posés (9, run 1/3) est même **inférieur**
au meilleur résultat séquentiel déjà enregistré (front 9 + back 1 = 10,
`EXPERIMENT_18.md`) : l'alternance rééquilibre front/back (5 et 4 au lieu de
9 et 1) mais ne les fait pas progresser plus loin ensemble. Deux causes
distinctes, toutes deux avérées par les diagnostics :

**1. Bug de câblage de la pénalité d'espace libre (cause immédiate du run 3).**
Dans `search_joint` (`joint_solver.py`), la pénalité est appliquée *après*
la sélection du beam et *après* la construction des états suivants :

```
beam = _select_joint_beam(next_states, params.beam_width)       # tri par score NON pénalisé
beam = [_with_freespace_penalty(state, ...) for state in beam]  # pénalité ajoutée ICI
```
(`joint_solver.py:288-289`)

`_with_freespace_penalty` ne modifie que le champ `score` du `JointState`
englobant ; il ne touche jamais `state.front.score` ni `state.back.score`
(`joint_solver.py:179-187`). Or l'étape suivante lit exclusivement ces scores
par-côté : `view = _side_view(own, global_remaining)` reprend `own.score`
tel quel (`joint_solver.py:255`), et chaque enfant reçoit
`new_front.score + new_back.score` — toujours les scores par-côté, jamais le
score pénalisé du parent (`joint_solver.py:277`). La pénalité ne survit donc
que pour le tri final `beam.sort(...)` qui désigne `best` pour l'affichage/le
JSON de CE tour ; elle est invisible pour `_select_joint_beam` au tour
suivant, qui retrie depuis `next_states` reconstruit à partir des scores
par-côté non pénalisés. Résultat : changer `freespace_weight` ou
`freespace_min_corridor` ne peut jamais changer quel état survit dans le
beam — seule la valeur numérique `score` rapportée en sortie change. Les
deux champs ajoutés à `SolverParams` (`freespace_weight`,
`freespace_min_corridor`, défauts inchangés) sont donc fonctionnellement
inertes en l'état.

**2. Saturation géométrique de la surface 350×350, confirmée indépendamment du
levier beam (run 2).** Même avec 100 parents conservés à chaque profondeur
(contre 56), les causes de rejet dominantes à partir de la profondeur 5 sont
`bounds` (hors des 350×350) et `footprint_collision`, dans des proportions
quasi identiques au run 1 — élargir la recherche ne révèle aucune poche de
solutions supplémentaires, il explore juste plus de trajectoires qui finissent
dans le même mur. Ceci confirme, en mode conjoint, le diagnostic déjà posé en
mode séquentiel (`REPORT_SURFACE_AND_PACKING.md`) : 350×350 ne contient
structurellement pas assez de surface libre pour dix-huit haricots sous les
règles dures actuelles (empreintes, croisements, antiparallélisme, liaisons
12–45) ; 500×500 y parvient (18/18).

**3. Épuisement de quota comme facteur amplificateur (run 1/3 spécifiquement).**
Au moment où le beam meurt (profondeur totale 9), le quota global `4/10/4`
est déjà exactement épuisé pour les pars 3 et 5 (4/4 et 4/4 consommés à
parts égales entre front et back) ; seul le par 4 reste disponible (9/10).
`_select_joint_beam` fait un round-robin **par profil de quota restant**, pas
pondéré par la taille du quota global — un profil « par3 posé » et un profil
« par4 posé » reçoivent la même part du beam à profondeur 1, alors que le
quota final favorise 10 fois plus les par4. Les par3/par5, plus courts/longs
et donc parfois plus faciles à caser dans un espace contraint, survivent
ainsi de façon disproportionnée tôt, et épuisent leur quota avant que le par4
majoritaire n'ait eu sa part de la recherche. Au step 10 (dernière tentative,
back), les 360 essais sont tous en par4 (seule classe restante) et tous
rejetés — la perte de diversité de formes (plus de filler court ni long
disponible) se combine à la saturation géométrique du point 2.

## Point de reprise

Avant tout nouveau réglage de la pénalité d'espace libre : corriger le
câblage dans `search_joint` pour que la pénalité influence réellement la
sélection du beam au tour suivant (par exemple, propager `state.score`
pénalisé dans `front.score`/`back.score` avant de reconstruire
`next_states`, ou appliquer la pénalité avant `_select_joint_beam` plutôt
qu'après). Tant que ce n'est pas fait, tout réglage de
`freespace_weight`/`freespace_min_corridor` est un essai sans effet garanti
par construction — ne pas le refaire tel quel.

Ne pas relancer de benchmark multi-seeds sur ce solveur avant 18/18 (discipline
§7). Deux pistes restent ouvertes, dans l'ordre :

1. corriger le bug de câblage ci-dessus puis réévaluer si la pénalité change
   la trajectoire seed 42 (sans présumer du résultat) ;
2. revisiter le round-robin de `_select_joint_beam` pour qu'il pondère les
   profils de quota restant par leur poids global (`4/10/4`), au lieu d'une
   parité stricte entre profils, afin de ne pas épuiser par3/par5 avant que
   par4 ait eu sa chance — cohérent avec la piste « packing connecté sans
   ordre fixé » déjà proposée dans `REPORT_SURFACE_AND_PACKING.md`.

Conserver la seed témoin 42, la carte 350×350, la banque `8/20/8` et le
validateur indépendant. `golfgen/loop_router.py` reste inchangé.

## Incrément B' — câblage réel de la pénalité + hypothèse de pression de quota

### Ce qui a été corrigé (vérifié, pas supposé)

`_select_joint_beam` est maintenant appelé sur un pool borné (`next_states`
triés par score brut, tronqués à `SolverParams.freespace_pool_width`,
défaut 240) **avant** que la pénalité d'espace libre soit calculée et
ajoutée au score de chaque candidat du pool (`joint_solver._select_penalized_beam`,
qui remplace l'appel direct à `_select_joint_beam` dans `search_joint`).
Comme `freespace.analyze` est recalculé à chaque tour à partir des
empreintes réellement posées (`state.front.placed`/`state.back.placed`),
il n'est plus nécessaire de propager un score pénalisé dans
`front.score`/`back.score` pour que l'effet survive au tour suivant : la
pénalité est simplement réévaluée depuis zéro à chaque tour, sur le pool
de CE tour.

Preuve directe, pas seulement un rerun global : `tests/test_bean_joint_solver.py::
test_freespace_penalty_changes_which_joint_state_survives_the_beam`
construit deux `JointState` de même profondeur (même case du round-robin),
l'un avec un meilleur score brut mais un corridor pincé à 8 blocs jusqu'à
son green, l'autre avec un score brut moins bon mais un corridor ouvert.
Avec `freespace_weight=0.0`, `_select_penalized_beam` retient le meilleur
score brut ; avec `freespace_weight=4.0`, il retient l'autre — la pénalité
change bien le survivant du beam, pas seulement le score affiché.

### Hypothèse de pression de quota (point de reprise n°2, testée — pas confirmée)

Un terme optionnel `_quota_pressure_penalty(front, back, weight)` pénalise
le dépassement (jamais le retard) de la part attendue de par3/par5 à la
profondeur totale courante, par rapport au quota global `4/10/4`.
Désactivé par défaut (`quota_pressure_weight=0.0`, résultat toujours 0.0
sans même inspecter les haricots posés — voir
`test_quota_pressure_penalty_is_zero_when_disabled`). Testé isolément
(`test_quota_pressure_penalty_increases_when_par3_outpaces_its_expected_share`)
et en intégration dans `_select_penalized_beam`.

**Correction au diagnostic du point 3 de l'incrément B** : la relecture
affirmait que `_select_joint_beam` « fait un round-robin par profil de
quota restant ». C'est inexact — il bucket par `(front.depth, back.depth)`,
jamais par quota. Et en pratique, les diagnostics ci-dessous (comme ceux de
B) montrent qu'à CHAQUE `global_step`, la totalité du beam choisit le même
côté (`front` ou `back` a toujours `parents=0` sur l'autre ligne) : tous les
survivants partagent systématiquement la même paire de profondeurs, donc il
n'existe qu'un seul bucket actif par tour. Le round-robin de
`_select_joint_beam` ne fait donc, en l'état actuel, strictement rien de
plus qu'un tri par score — il ne protège aucun profil de quota rare. Le
biais par3/par5 observé n'est donc pas un artefact du round-robin, mais une
conséquence du score (`_state_score`, `_transform_rank`) qui favorise des
formes correspondant mieux à l'espace restant, pas de la sélection de beam
elle-même.

**Les chiffres, pour trancher « est-ce que par3/par5 s'épuisent vraiment
tôt » :** au moment de la mort du beam de R4 (profondeur totale 9, comme
B run1/3) : par3 4/4 (**100 %** du quota global), par5 4/4 (**100 %**),
par4 1/10 (**10 %**) — alors que par4 représente 55,6 % du quota final.
Pour R5/R6 (mort à profondeur totale 8) : par3 4/4 (100 %), par5 3/4
(75 %), par4 1/10 (10 %). Le déséquilibre est réel et mesuré, pas supposé.

### Runs (seed 42, 350×350, beam 56)

| Run | freespace (weight / min_corridor / pool) | quota_pressure | front | back | total | trials | temps | mort à |
|---|---|---|---|---|---|---|---|---|
| 4 | 1.0 / 15.0 / 240 (câblé pour de vrai) | 0.0 (off) | 5/9 | 4/9 | 9 | 103 770 | 77,2 s | step 10 |
| 5 | 0.0 (off) | 3.0 | 4/9 | 4/9 | 8 | 98 910 | 63,8 s | step 9 |
| 6 | 1.0 / 15.0 / 240 | 3.0 | 4/9 | 4/9 | 8 | 98 910 | 65,3 s | step 9 |

Choix des poids : `freespace_weight=1.0`/`min_corridor=15.0` = défauts déjà
en place avant B' (aucune raison de les changer pour isoler l'effet du
câblage). `freespace_pool_width=240` ≈ 4× le beam, pour rester nettement
au-dessus des quelques centaines d'acceptés typiques par tour (voir trials
B) sans évaluer `freespace.analyze` sur des milliers de candidats à chaque
profondeur. `quota_pressure_weight=3.0` : même ordre de grandeur que
`FIRST_PAR_PENALTY` (2.4–3.8, `solver.py`), le seul autre terme de score
connu à cette échelle ; à profondeur 9 un dépassement de 2 trous (4 posés
contre ~2 attendus) donne une pénalité de 6.0, comparable aux autres termes
sans les dominer outrageusement.

**R4 (câblage seul) : même résultat que B run1/3** (front 5/9, back 4/9,
9 trous, mêmes pars `3-3-5-5-4` / `3-3-5-5`). Le temps monte de 54,5 s à
77,2 s (coût de `freespace.analyze` sur le pool de 240, à chaque tour), mais
la trajectoire ne change pas : au poids par défaut, le signal d'espace libre
ne suffit pas à déplacer le classement parmi les survivants retenus — les
causes dominantes de rejet restent `bounds`/`footprint_collision`/
`axis_crossing` (contraintes dures, invisibles à toute pénalité de score).
Le câblage est maintenant réel et vérifié (test ci-dessus) — mais pas
suffisant : une vérification instrumentée menée en relecture de code (run
complet seed 42/350, ~80 s) montre que la pénalité est non nulle sur
~100 % des candidats du pool à chaque tour (valeurs 15–44), mais que son
**étalement** à une profondeur donnée est quasi nul (0,0000–0,0062), contre
0,05–12 pour l'étalement du score brut à la même profondeur. La pénalité
se comporte donc comme un **décalage quasi constant** ajouté à tous les
candidats du pool, qui ne change jamais leur classement relatif — ce n'est
pas que « la saturation géométrique domine le signal de score » (affirmation
non étayée par ces chiffres, retirée ici), c'est que le signal lui-même ne
discrimine pas les candidats de même profondeur. Cause probable : la grille
`CELL_SIZE=5` de `freespace.py` est trop grossière pour distinguer des
frères de même profondeur qui diffèrent de quelques blocs. Un seul poids de
pénalité a été testé avec le câblage réel (`freespace_weight=1.0`, R4/R6) ;
relancer avec un poids plus fort n'a aucune raison de changer ce diagnostic,
puisque multiplier un décalage quasi constant par un facteur reste un
décalage quasi constant — **le solveur conjoint guidé par freespace n'a
donc pas encore été testé de façon significative** : le levier à actionner
est la résolution/sensibilité de la métrique (grille plus fine, ou une
mesure de capacité de poche plutôt qu'une distance au bord), pas le poids.

**R5 (pression de quota seule) et R6 (les deux) : pire que R4,
pas mieux.** Les deux s'arrêtent un tour plus tôt (step 9 au lieu de 10),
avec un total de 8 trous au lieu de 9. Le détail : `par5` chute de 4/4 à
3/4 (la pénalité décourage bien un par5 de plus en fin de partie), mais
ceci ne libère **aucune** place supplémentaire pour par4 (toujours 1/10
dans les trois runs) — le nombre d'acceptés au step 7/8/9 s'effondre plus
vite (step8 : 3 acceptés contre 49 en R4 ; step9 : 0 parent survivant vs 49
parents en R4). L'hypothèse du point 3 de B (« les par3/par5 volent de la
diversité de recherche aux par4 ») est donc **réfutée** par ce test : à
poids 3.0, pénaliser l'usage précoce de par3/par5 ne fait pas émerger de
par4 supplémentaire, parce que le facteur limitant n'est pas la part du
beam allouée aux profils de quota (il n'y a qu'un seul bucket actif par
tour, voir plus haut) mais la difficulté géométrique réelle de caser un
par4 dans l'espace restant — moins de bonnes solutions par3/par5
conservées ne compense pas par davantage de bonnes solutions par4, elle
réduit juste le pool de survivants valides.

R6 reproduit exactement les mêmes haricots que R5 (le score affiché diffère
seulement de la contribution freespace, qui ne change donc rien à la
décision une fois la pression de quota active) — cohérent avec R4 montrant
déjà que le poids freespace par défaut ne suffit pas à déplacer un
classement dominé par d'autres facteurs.

JSON + SVG : `output/seed42_joint_350_run4_failed.{json,svg}`,
`output/seed42_joint_350_run5_failed.{json,svg}`,
`output/seed42_joint_350_run6_failed.{json,svg}`.

### Verdict

Aucun des trois runs n'atteint 18/18, ni même le meilleur résultat conjoint
déjà connu (9 trous, B run1/3) — R5/R6 sont strictement en dessous (8).
Le câblage de la pénalité d'espace libre est désormais réel (prouvé par
test unitaire), mais à son poids par défaut il ne change pas l'issue sur
cette seed. Ce n'est pas la preuve que « la saturation géométrique domine
le signal de score » (affirmation retirée, voir R4 ci-dessus) : la mesure
instrumentée montre que la pénalité freespace n'a quasiment aucun pouvoir
discriminant entre candidats de même profondeur (grille `CELL_SIZE=5` trop
grossière), donc elle ne pouvait pas déplacer le classement — qu'il y ait
ou non saturation géométrique par ailleurs. Un seul poids a été essayé avec
le câblage réel ; le solveur conjoint guidé par freespace reste donc
**effectivement non testé**, et le restera tant que la métrique ne
discrimine pas. L'hypothèse de pression de quota, elle, est bien testée et
réfutée sur ce cas : forcer le par4 plus tôt en pénalisant par3/par5 ne
fait qu'épuiser plus vite le pool de survivants valides, sans produire de
par4 supplémentaire.

Trois incréments indépendants (B : beam élargi, câblage buggé ; B' :
câblage réel, pression de quota) n'ont déplacé le mur que de ± 1 trou
autour de 8-9/18, jamais au-delà — mais aucun n'a encore testé un signal
d'espace libre réellement discriminant. Pour contexte (pas comme preuve) :
un haricot occupe 26 à 31 % de la carte 350×350 en empreinte
(`output/benchmark_1_10/REPORT.md`), donc dix-huit trous représentent
environ 60 % d'occupation de surface sous les règles dures actuelles
(aucune superposition, aucun croisement d'axes, antiparallélisme, liaisons
12–45) ; les 350 tentatives plafonnent toutes autour de 8-9/18 alors que
500×500 en séquentiel a réussi 18/18 (`REPORT_SURFACE_AND_PACKING.md`).
Ceci rend plausible une contrainte de densité réelle, sans la démontrer
tant que la métrique freespace reste non discriminante.

**Point de reprise.** La décision suivante porte sur la taille de carte :
si 350×350 est une exigence réelle du spike, les leviers restants sont une
métrique freespace plus fine (grille plus petite que `CELL_SIZE=5`, ou une
mesure de capacité de poche plutôt qu'une distance au bord) ou le packing
connecté sans ordre de jeu fixé déjà proposé dans
`REPORT_SURFACE_AND_PACKING.md`. Si 500×500 (ou une taille intermédiaire)
est acceptable, l'étape 6 est déjà satisfaite par le run 500×500 (18/18) et
la prochaine étape est le benchmark seeds 1..10 à cette taille. Conformément
à la discipline (§7), aucun benchmark multi-seeds n'est lancé sur le
solveur conjoint ordonné en 350×350 avant cette décision.
