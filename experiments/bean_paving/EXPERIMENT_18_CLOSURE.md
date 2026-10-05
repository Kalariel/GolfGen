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
