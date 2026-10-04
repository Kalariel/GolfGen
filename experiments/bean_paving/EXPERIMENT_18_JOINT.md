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
