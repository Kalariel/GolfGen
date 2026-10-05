# Essai 18 trous — quota global libre + fermeture anticipée du back

Rappel d'unité : 1 bloc = 3 m. Toutes les distances sont en blocs.

**Point de départ.** `experiments/bean_paving/output/benchmark_course18_400_1_10/REPORT.md` :
séquentiel, 400×400, `shared_rough=True`, `fairway_gap=5`, `edge_min=1`,
`max_parallel_stack=3`, `clubhouse_clear_radius=10`, poids demi-plan 0 — **0/10**.
Le front ferme toujours à 9/9. Le back plafonne à **8/9** sur les seeds 2, 8, 9
(rejeté à la profondeur 9, `clubhouse_clear`/`clubhouse_return` mêlés à la
géométrie dure) et à **7/9** sur la seed 1 (bloqué à la profondeur 8, uniquement
`fairway_gap`/`axis_crossing`/`bounds`, aucune cause liée au clubhouse).

Deux changements opt-in (paramètres par défaut inchangés, comportement
byte-identique sans eux) :

1. **Quota global libre** (`course_solver.solve_course(free_quota=True)`) :
   seul le quota 18 trous (`joint_solver.GLOBAL_PAR_QUOTA`, 4/10/4) est
   imposé. Le front reçoit ce budget entier (`solver.solve_nine(...,
   par_quota=GLOBAL_PAR_QUOTA, require_full_quota=False)`) au lieu du
   quota par-nine fixe `2/5/2` ; `require_full_quota=False` relâche
   uniquement le test de complétude (`remaining == (0, 0, 0)` devient
   inapplicable puisque le front ne consomme que 9 des 18 places du budget).
   Le back reçoit EXACTEMENT ce qu'il reste, recalculé depuis les haricots
   réellement posés par le front — jamais un compteur périmé, même principe
   que `joint_solver._global_remaining` (bug documenté dans
   `_has_closing_moves`) — via la nouvelle fonction
   `course_solver._global_remaining_from_front`.
2. **Fermeture anticipée plus précoce** (`SolverParams.closing_lookahead_from`,
   défaut `9` = comportement historique, déclenché seulement à la profondeur
   8). `solver._has_closing_move` est généralisé en
   `solver._has_closing_sequence(state, ..., steps_remaining=N)` : cherche
   une séquence d'EXACTEMENT `N` trous qui referme sur le clubhouse, chaque
   pas passant par `_placement_problems` → `geometry.validate` (aucun
   raccourci géométrique parallèle, même oracle que le reste du solveur).
   `_has_closing_move` devient un alias (`steps_remaining=1`), donc
   strictement inchangé. Coût : le DERNIER pas (celui qui referme vraiment)
   garde la largeur normale (`candidates_per_par`/`transforms_per_candidate`) ;
   les pas intermédiaires utilisent une largeur réduite
   (`lookahead_candidates_per_par=1`, `lookahead_transforms_per_candidate=4`
   par défaut) — une sonde de plausibilité bon marché (« un chemin existe-t-il »,
   pas « quel est le meilleur »), avec retour dès la première séquence
   trouvée. Pire cas borné par (3 pars × largeur réduite)^(N-1) × (3 pars ×
   largeur normale), jamais une énumération exhaustive à pleine largeur.

## Paramètres du run

`back_closure_400` (seeds 2, 8, 9, 1 — les 4 bloquées à 7-8/9 dans le
benchmark) : mêmes règles que le benchmark (400×400, `shared_rough`,
`fairway_gap=5`, `edge_min=1`, `max_parallel_stack=3`,
`clubhouse_clear_radius=10`), `free_quota=True`,
`back_closing_lookahead_from=7` (seule surcharge de `back_params` ; aucune
autre largeur de beam, de candidats ou de transformations n'a changé —
`beam_width=72` côté front et côté back comme avant). Un process par seed
(`ProcessPoolExecutor`, 4 workers), temps mesuré en wall-clock réel par
seed.

## Résultat

**0/4 — aucune des 4 seeds ne ferme, et toutes échouent bien plus tôt que
dans le benchmark de référence.**

| Seed | Benchmark (référence) | Ce run (`free_quota` + lookahead 7) | Temps | Essais front / back |
|---:|:---:|:---:|---:|---:|
| 2 | 8/9 (bloqué profondeur 9) | **0/9** (bloqué profondeur 1) | 166.2s | 146 250 / 1 152 |
| 8 | 8/9 (bloqué profondeur 9) | **0/9** (bloqué profondeur 1) | 178.3s | 146 250 / 1 152 |
| 9 | 8/9 (bloqué profondeur 9) | **0/9** (bloqué profondeur 1) | 198.1s | 146 250 / 1 152 |
| 1 | 7/9 (bloqué profondeur 8) | **0/9** (bloqué profondeur 1) | 219.4s | 146 250 / 1 152 |

Front toujours 9/9 (comme avant), mais le back meurt systématiquement au
**premier trou**, pas au 8ᵉ ou 9ᵉ comme dans le benchmark. Le quota global
libre a donc rendu les choses **nettement pires**, pas meilleures, sur
l'échantillon testé.

### Cause — pas une coïncidence, un biais structurel reproductible

Pars posés par le front (libre sur le quota global 4/10/4) :

| Seed | Pars front (ordre de jeu) | Par3 utilisés | Par4 utilisés | Par5 utilisés |
|---:|---|---:|---:|---:|
| 2 | 3-4-4-4-3-3-4-3-4 | **4** | 5 | 0 |
| 8 | 3-4-4-4-3-3-3-4-4 | **4** | 5 | 0 |
| 9 | 3-4-4-3-4-3-4-4-3 | **4** | 5 | 0 |
| 1 | 3-4-4-3-3-4-3-4-4 | **4** | 5 | 0 |

**Sur les 4 seeds, sans exception, le front consomme l'intégralité du quota
global de par3 (4/4) et aucun par5.** Le back reçoit donc un quota
`{3: 0, 4: 5, 5: 4}` — zéro par3, quatre par5 (les trous les plus longs,
donc les plus difficiles à caser). C'est cohérent avec le score de
`solver._state_score` : un par3 court contribue moins à la boîte englobante
(`bbox_weight`) et s'insère plus facilement dans un espace contraint, donc
il survit souvent mieux au beam quand aucun quota dur ne le limite à 2 —
l'effet est systématique, pas une variance d'échantillonnage.

Avec ce quota, la profondeur 1 du back (trou d'ouverture, un seul état
parent, aucun rattrapage possible si cet état meurt) ne peut tirer que des
par4/par5 — seulement `candidates_per_par=4` gabarits par classe parmi ceux
restants dans la banque, tirage pseudo-aléatoire scellé par la seed. Sur les
4 seeds testées, les candidats ainsi tirés échouent **tous** le test
`clubhouse_departure` (`solver._starts_outward`, géométrie pure — le trou
doit s'éloigner du clubhouse) :

| Seed | Profondeur 1 — essais | acceptés | cause |
|---:|---:|---:|---|
| 2, 8, 9, 1 | 1 152 | **0** | `clubhouse_departure` : 1 152 (100 %) |

Les 1 152 essais (= 2 classes × 4 gabarits × 144 transformations de départ)
échouent tous la même règle géométrique, sans aucune autre cause mêlée —
confirmé par `back_last_depths` dans
`output/back_closure_400/summary.json`. Le retrait complet du par3 réduit
la diversité directionnelle disponible à la profondeur 1 juste assez pour
qu'aucun des 8 gabarits tirés (4 par4 + 4 par5) ne pointe vers l'extérieur
pour AUCUNE des 144 transformations de départ retenues par le classement de
rang (`_transform_rank`) — un effet de bord du `candidates_per_par=4` fixe
combiné à la disparition d'une classe entière, jamais testé avant ce run
puisque le quota par-nine `2/5/2` garantissait toujours au moins 2 par3
disponibles au back.

### La fermeture anticipée n'a jamais été exercée

Le second changement (`closing_lookahead_from`) ne se déclenche qu'à partir
de la profondeur `closing_lookahead_from - 1` (6 avec le paramètre `7` de ce
run). Le back meurt à la profondeur 1, bien avant — **le code de fermeture
anticipée n'a jamais été appelé dans ce run**, sur aucune des 4 seeds. Ce
run ne mesure donc QUE l'effet du quota global libre, pas celui de la
fermeture anticipée : les deux changements sont demandés ensemble par le
plan, mais le premier bloque le second avant qu'il ait une chance de jouer
un rôle.

## Variante testée (unique, comme prévu si le résultat est ambigu)

Résultat non ambigu en soi (0/4, cause claire et identique sur les 4
seeds), mais comme le run ne permettait de juger ni `closing_lookahead_from`
ni la fermeture anticipée, la variante `closing_lookahead_from=6` (au lieu
de 7) a été lancée pour vérifier qu'elle ne change rien — ce qui était
attendu puisque le back ne dépend pas de `back_closing_lookahead_from` tant
qu'il meurt avant la profondeur 5.

| Seed | `lookahead_from=7` | `lookahead_from=6` |
|---:|:---:|:---:|
| 2 | 0/9 (profondeur 1) | 0/9 (profondeur 1) |
| 8 | 0/9 (profondeur 1) | 0/9 (profondeur 1) |
| 9 | 0/9 (profondeur 1) | 0/9 (profondeur 1) |
| 1 | 0/9 (profondeur 1) | 0/9 (profondeur 1) |

Résultat identique au bloc (`front_pars` identiques, le front ne dépend pas
de `back_closing_lookahead_from`) : confirmé, sans surprise, que la
variante n'apporte rien tant que le quota global libre tue le back avant la
profondeur 5. Sorties : `output/back_closure_400_variant_from6/summary.json`
(non conservé en JSON/SVG complet par seed, seul le résumé a été produit
pour cette variante de confirmation).

## Validation indépendante

`independent_valid` (même oracle que `course_solver._course_violations` :
`geometry.validate` sur front, back et front+back, plus contrôle
départ/retour clubhouse) : **False sur les 4 seeds**, cohérent avec
`back_holes=0` — aucun parcours à 18/18 n'a été produit, donc rien à valider
positivement ; le contrôle sert ici seulement à confirmer qu'aucun faux
succès ne s'est glissé dans `complete`.

## Conclusion

**0/4, net recul par rapport au benchmark (qui donnait 7-8/9 sur ces 4
seeds).** Le quota global libre, tel que spécifié (le front pioche
librement dans le budget 18 trous sans aucune réserve par classe), produit
un biais systématique et reproductible : le front épuise entièrement le
par3 sur les 4 seeds testées, ce qui prive le back de sa classe la plus
facile à ouvrir et fait mourir sa toute première profondeur — un échec plus
sévère et plus précoce que le blocage observé à 7-8/9 dans le benchmark de
référence. La fermeture anticipée (deuxième changement demandé) n'a jamais
pu être exercée dans ces conditions, puisque le back ne dépasse jamais la
profondeur 1.

Cette session s'arrête ici, comme convenu (un paramétrage + une variante).
**Aucune autre variante n'a été tentée** (par exemple limiter le front à au
plus 3 par3, ou élargir `candidates_per_par` à la profondeur 1 du back) —
ce sont des pistes de reprise, pas des correctifs appliqués dans cette
session, pour rester dans le périmètre convenu.

## Point de reprise

- Le quota global libre, dans sa forme actuelle, N'EST PAS une amélioration
  nette : il a besoin d'une garde-fou (ex. empêcher le front d'épuiser
  entièrement une classe, ou réserver un minimum par classe au back) avant
  d'être réévalué.
- La fermeture anticipée (`closing_lookahead_from`,
  `solver._has_closing_sequence`) reste non testée en conditions réelles de
  blocage à la profondeur 8 — elle a seulement été vérifiée unitairement
  (`tests/test_bean_back_closure.py`). Un prochain run devrait l'isoler
  (`free_quota=False`, quota par-nine `2/5/2` inchangé, seul
  `closing_lookahead_from` activé) pour mesurer son effet propre sur les
  seeds 2, 8, 9 (bloquées profondeur 9) et 1 (bloquée profondeur 8), sans le
  confondre avec le quota global.
- Code conservé pour la suite : `course_solver.solve_course(free_quota=...,
  back_closing_lookahead_from=...)`, `course_solver._global_remaining_from_front`,
  `solver.SolverParams.closing_lookahead_from` /
  `lookahead_candidates_per_par` / `lookahead_transforms_per_candidate`,
  `solver._has_closing_sequence` (généralisation de `_has_closing_move`,
  conservé comme alias `steps_remaining=1`).
- Sorties : `output/back_closure_400/seed{2,8,9,1}_failed.{json,svg}` +
  `summary.json` ; variante : `output/back_closure_400_variant_from6/summary.json`.

## Reprise — A/B quota fixe vs quota borné, fermeture anticipée isolée

Reprend les deux pistes laissées ouvertes ci-dessus, sur les mêmes 4 seeds
(2, 8, 9, 1) et les mêmes règles (400×400, `shared_rough`, `fairway_gap=5`,
`edge_min=1`, `max_parallel_stack=3`, `clubhouse_clear_radius=10`, poids
demi-plan 0, `beam_width=72` front et back inchangé) :

**A) Quota fixe `2/5/2` (`free_quota=False`, défaut historique) + fermeture
anticipée isolée (`back_closing_lookahead_from=7`)** — cette fois sans le
quota global libre, pour mesurer l'effet PROPRE de la fermeture anticipée
sur le vrai plateau à 7-8/9 (pas le cas dégénéré profondeur-1 du run
précédent).

**B) Quota borné par nine (`solve_course(bounded_quota=True)`, nouveau,
opt-in — défaut `False`, comportement byte-identique sans lui)** : chaque
nine doit finir avec un compte de par3 ET de par5 dans `[1, 3]`
(`SolverParams.par3_bounds` / `par5_bounds`, des paramètres, pas des
constantes câblées) ; le par4 complète librement jusqu'à 9. Implémentation
(`solver._bounded_quota_filter`, appelée depuis `expand_state` uniquement
côté front) :

1. **Forçage** : si le besoin TOTAL restant (somme des manques par3 + par5
   par rapport à leur minimum) égale ou dépasse les emplacements restants,
   SEULES les classes encore sous leur minimum deviennent éligibles (le
   par4 est exclu de ce coup). Le forçage porte sur la somme des deux
   classes, pas sur chacune isolément — sinon deux besoins qui deviennent
   tendus au même coup (ex. profondeur 8, 2 emplacements restants, 1 par3 ET
   1 par5 encore nécessaires) ne seraient forcés qu'à la toute dernière
   profondeur, trop tard pour satisfaire les deux à la fois.
2. **Plafond solidaire** : une classe bornée n'est éligible que si, après
   l'avoir prise, le quota global restant (`joint_solver.GLOBAL_PAR_QUOTA`
   moins ce que CE nine a RÉELLEMENT posé, jamais un compteur périmé —
   `course_solver._bounded_front_quota` / `_global_remaining_from_front`)
   laisse encore à l'AUTRE nine au moins son propre minimum.

Le back reçoit ensuite exactement le quota global restant (même mécanisme
que `free_quota`, via `_global_remaining_from_front`), qui tombe
automatiquement dans ses propres bornes `[1, 3]` puisque
`GLOBAL_PAR_QUOTA[3] == GLOBAL_PAR_QUOTA[5] == 4 == min + max` des bornes
par défaut — si le front reste dans ses bornes, le reste pour le back y
reste aussi, par construction arithmétique, pas par une vérification
séparée côté back. Même fermeture anticipée isolée
(`back_closing_lookahead_from=7`) que la config A.

Compteur ajouté (`solver.DepthDiagnostics.lookahead_calls` /
`lookahead_pruned`, nouveaux champs à défaut `0`, aucun autre champ modifié)
pour mesurer si la fermeture anticipée est réellement exercée : incrémentés
dans `expand_state` à chaque appel de `_has_closing_sequence`, `pruned`
quand l'appel renvoie `False` (le candidat reçoit la pénalité +80, un
rejet souple qui le défavorise à la sélection du beam, pas un retrait dur).

### Résultat

**A : 0/4 (identique au benchmark de référence sur ces 4 seeds). B : 3/4 —
seeds 2, 8, 1 ferment à 18/18, validées indépendamment ; seule la seed 9
reste bloquée à 8/9.**

| Seed | Benchmark (réf.) | A (quota fixe + lookahead 7) | B (quota borné + lookahead 7) |
|---:|:---:|:---:|:---:|
| 2 | 8/9 (profondeur 9) | 8/9 (profondeur 9), 905.3s | **9/9 (18/18)**, 605.5s |
| 8 | 8/9 (profondeur 9) | 8/9 (profondeur 9), 582.4s | **9/9 (18/18)**, 958.7s |
| 9 | 8/9 (profondeur 9) | 8/9 (profondeur 9), 545.7s | 8/9 (profondeur 8), 535.0s |
| 1 | 7/9 (profondeur 8) | 7/9 (profondeur 8), 445.2s | **9/9 (18/18)**, 693.3s |

Validation indépendante (`geometry.validate` front+back+conjoint, contrôle
départ/retour clubhouse, `course_solver._course_violations`) : **conforme
sur les 3 succès B (seeds 2, 8, 1)**, aucune divergence avec `complete` du
solveur ; sans objet sur A et sur B/seed 9 (pas de 18/18 à valider).

### A — la fermeture anticipée isolée reproduit EXACTEMENT le plafond du benchmark

Sur les 4 seeds, `back_holes` de A est identique, trou pour trou, au
benchmark de référence (8, 8, 8, 7) — avec le même nombre de pars par
classe au back (quota fixe `2/5/2` inchangé). La fermeture anticipée est
bien exercée cette fois (contrairement au run précédent où elle ne
s'activait jamais, le back mourant à la profondeur 1) :

| Seed | Appels lookahead (back) | Renvoient `False` (pénalisés) | Taux |
|---:|---:|---:|---:|
| 2 | 2956 | 2956 | 100 % |
| 8 | 2486 | 2486 | 100 % |
| 9 | 791 | 791 | 100 % |
| 1 | 336 | 336 | 100 % |

**100 % des appels renvoient `False` sur les 4 seeds — la fermeture
anticipée n'a JAMAIS trouvé de séquence valide vers le clubhouse depuis les
états explorés aux profondeurs 6-8.** Ce n'est pas un bug : avec le quota
fixe `2/5/2`, les classes de haricots disponibles pour les 2-3 derniers
trous sont déjà déterminées (2 par3, 5 par4, 2 par5 au total, consommés
dans un ordre que le beam a figé plus tôt) ; si la géométrie bloque
réellement toute fermeture depuis ces états (mêmes causes dominantes que le
benchmark : `axis_crossing`, `bounds`, `fairway_gap` aux profondeurs 6-7,
puis `axis_crossing`/`clubhouse_clear`/`clubhouse_return` à la profondeur
9 pour les seeds 2/8/9 ; uniquement `axis_crossing`/`fairway_gap`/
`parallel_stack` à la profondeur 8 pour la seed 1, confirmant la
description déjà posée dans ce document), la sonde de plausibilité ne peut
que le confirmer plus tôt — elle ne crée pas de nouvelles options. La
pénalité +80 réordonne la sélection du beam parmi des candidats tous
également condamnés, elle ne change pas l'issue. **Conclusion A :
isolée du quota global libre, la fermeture anticipée ne résout pas le
plafond à 7-8/9 — elle le détecte, mais ne peut pas le contourner tant que
le quota par-nine fixe limite les classes disponibles en fin de nine.**

### B — le quota borné lève le plafond sur 3 seeds sur 4

Le front se stabilise systématiquement sur la même composition `par3=3,
par4=5, par5=1` (plafond haut de `par3_bounds`, plancher bas de
`par5_bounds`) sur les 4 seeds, laissant au back un quota global restant
`{3: 1, 4: 5, 5: 3}` — vérifié identique sur les 4 seeds, succès comme
échec. Contrairement au run précédent (quota global libre SANS garde-fou,
où le front épuisait le par3 à 4/4 et en laissait 0 au back), le back garde
ici toujours au moins 1 par3 pour ouvrir — exactement le garde-fou suggéré
au point de reprise ci-dessus.

Sur les 3 succès (seeds 2, 8, 1), le beam atteint la profondeur 9 avec
quelques états acceptés (2, 20, 6 respectivement) là où A n'en a jamais
aucun — la diversité supplémentaire apportée par le par5 restant au back
(3 au lieu de 2) et par l'ordre différent des classes (le quota borné
réordonne `_par_order` différemment du `2/5/2` fixe) suffit, sur ces 3
seeds, à ouvrir des chemins de fermeture que le quota fixe fermait
systématiquement.

La seed 9 (échec, 8/9) a la MÊME composition de quota back `{3: 1, 4: 5,
5: 3}` que les 3 succès — l'échec n'est donc pas une carence de quota mais
un blocage géométrique propre à cette seed (profondeur 8 : seulement 5
états acceptés sur 5328 essais, causes `axis_crossing`/`bounds` ; profondeur
9 : 0 accepté sur 720 essais, cause dominante `clubhouse_return` (657/720,
91 %) — la seed se rapproche du clubhouse mais ne rentre jamais dans
`clubhouse_max`, contrairement aux 3 autres qui mêlaient davantage
`axis_crossing`/`clubhouse_clear`).

Fermeture anticipée en B (comme en A, exercée des centaines à quelques
milliers de fois) :

| Seed | Appels | Pruned (`False`) | Trouvées (`True`) |
|---:|---:|---:|---:|
| 2 | 1373 | 1371 | 2 |
| 8 | 2586 | 2580 | 6 |
| 9 | 209 | 209 | 0 |
| 1 | 691 | 685 | 6 |

Sur les 3 succès, quelques appels (2 à 6) renvoient enfin `True` — la
fermeture anticipée a donc, ici, un effet réel et mesurable (pas seulement
une pénalité qui ne change jamais rien comme en A), même si elle reste
l'exception (0,1-0,9 % des appels) plutôt que la règle : l'essentiel du
travail de déblocage vient du quota borné, la fermeture anticipée confirme
et accélère la détection des quelques chemins qui existent.

### Comparaison au benchmark et au run précédent

| | Benchmark (2/5/2, lookahead 9) | Quota global libre (lookahead 7) | A (2/5/2, lookahead 7) | B (borné, lookahead 7) |
|---|:---:|:---:|:---:|:---:|
| Score /4 (seeds 2,8,9,1) | 0/4 | 0/4 | 0/4 | **3/4** |
| Meilleur résultat | 8/9 | 0/9 (profondeur 1) | 8/9 (identique) | **9/9 ×3** |
| Cause dominante | géométrie fin de nine | par3 épuisé par le front | géométrie fin de nine (identique) | géométrie fin de nine (1 seed résiduelle) |
| Lookahead exercé | non mesuré | jamais (mort avant profondeur 5) | oui, 100 % pruned | oui, 0,1-0,9 % trouvées |

### Conclusion

Le quota borné par nine (`bounded_quota=True`) est, sur cet échantillon de
4 seeds, la première variante de cette série à dépasser le plafond
historique de 7-8/9 — **3 seeds sur 4 ferment à 18/18**, validées
indépendamment, contre 0/10 au benchmark et 0/4 aux deux tentatives
précédentes (quota global libre, puis fermeture anticipée isolée avec
quota fixe). La fermeture anticipée seule (config A), isolée du quota,
confirme la conclusion du run précédent : elle détecte bien le blocage
(exercée des centaines à quelques milliers de fois par seed) mais ne le
lève pas tant que le quota par-nine fixe limite les classes disponibles en
fin de nine — le levier qui fonctionne est le garde-fou de quota, pas la
profondeur de la sonde de fermeture.

Reste un échec sur quatre (seed 9, B) : blocage géométrique
(`clubhouse_return` dominant à la profondeur 9) avec une composition de
quota pourtant identique aux 3 succès — pas un problème de garde-fou
supplémentaire à ajouter, un cas à reprendre avec d'autres leviers (plus de
largeur de beam, d'autres bornes `par3_bounds`/`par5_bounds`, ou une
fermeture anticipée moins restrictive en largeur réduite) si cette piste
est poursuivie.

Code ajouté pour cette reprise : `solver.SolverParams.bounded_quota` /
`par3_bounds` / `par5_bounds` (opt-in, défaut `False` / `(1, 3)` / `(1, 3)`,
comportement byte-identique sans eux), `solver._bounded_quota_filter`,
`solver.expand_state(global_quota=...)`, `solver.solve_nine(global_quota=...)`,
`course_solver.solve_course(bounded_quota=...)`,
`course_solver._bounded_front_quota`, `solver.DepthDiagnostics.lookahead_calls`
/ `lookahead_pruned` (nouveaux champs, défaut `0`). Tests rapides :
`tests/test_bean_back_closure.py` (forçage, plafond, quota global, défauts
inchangés, front jamais sous le minimum du back). Sorties :
`output/closure_ab_400/{A,B}/seed{2,8,9,1}_{success,failed}.{json,svg}` +
`output/closure_ab_400/summary.json`.
