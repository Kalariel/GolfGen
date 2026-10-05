# Prototype `bean_paving` — plan de travail

## Décision et hypothèse

Les spikes précédents ont montré que construire une route globale puis la
découper, ou imposer des paires de trous en doigts, produit soit trop peu de
solutions, soit des formes artificielles. Ce prototype sépare complètement :

1. la création d'une banque de trous potentiels ;
2. leur sélection et leur placement spatial dans l'ordre de jeu.

Avant d'investir dans un vrai générateur de trous, chaque candidat est une
forme abstraite appelée **haricot**. Un haricot n'est pas un blob libre : il
conserve les informations dont le futur paveur aura besoin.

```text
haricot = empreinte + axe central + port tee + port green + classe de par
```

L'objectif du spike est de répondre à une seule question :

> peut-on sélectionner et placer une suite de formes variées en 350x350,
> sans collision ni croisement de fairways, tout en revenant au clubhouse ?

## Base de travail

- Branche : `spike/bean-paving`.
- Worktree : `.worktrees/bean-paving/`.
- Base locale : commit `2fa8242` de la branche `ga`, qui contient
  `loop_router`.
- Le worktree principal et ses modifications ne sont pas touchés.
- Les anciens spikes restent archivés dans leurs branches respectives.
- Le fetch GitHub n'est pas disponible dans l'environnement courant faute de
  clé SSH ; aucun merge distant implicite ne sera effectué.

## Périmètre du premier prototype

- Première cible : **un nine** en 350x350.
- Banque : 18 haricots, soit le double du besoin final du nine :
  - 4 courts, classe par 3 ;
  - 10 moyens, classe par 4 ;
  - 4 longs, classe par 5.
- Sélection finale : exactement 2 par 3, 5 par 4 et 2 par 5.
- La banque de 36 candidats et le parcours de 18 trous ne commencent qu'après
  validation du nine.
- Aucun terrain, bunker, végétation ou détail de green dans ce spike.
- Une seed doit reproduire exactement la banque, la recherche et le résultat.

## Contrat minimal d'un haricot

Chaque forme est définie dans un repère local, tee à l'origine :

- identifiant stable dans la banque ;
- classe 3, 4 ou 5 ;
- longueur cible cohérente avec la classe ;
- axe central orienté du tee vers le green ;
- zéro, un ou deux changements de direction simplifiés ;
- largeur effective ;
- empreinte incluant la forme et une marge extérieure de 5 blocs ;
- port tee, port green et cap local à chaque extrémité ;
- transformations autorisées : rotation et éventuellement miroir.

L'empreinte représente déjà la largeur du futur fairway. Pour une largeur de
12 et une marge de 5, elle s'étend par exemple de 11 blocs de chaque côté de
l'axe. Deux empreintes disjointes assurent alors une séparation d'environ
22 blocs entre axes.

## Règles du paving

Contraintes dures :

- tous les haricots restent dans les limites 350x350 ;
- aucune superposition d'empreintes ;
- aucun croisement entre axes centraux de trous ;
- liaison green -> tee comprise entre 12 et 45 blocs ;
- tee 1 et green 9 à 50 blocs maximum du clubhouse ;
- quotas de pars exacts ;
- aucun long aller-retour presque parallèle ;
- aucun candidat déclaré réussi avec une violation.

Les liaisons ne sont pas des fairways : elles peuvent croiser une empreinte ou
une autre liaison.

La règle anti-parallélisme sera paramétrée et testée séparément. Point de
départ proposé : deux segments non adjacents sont interdits si leur angle est
à moins de 15 degrés de l'antiparallèle, leur distance est inférieure à 30
blocs et leur projection commune dépasse 40 blocs. Ces valeurs sont
provisoires et devront être confirmées visuellement.

## Sélection des pars

Les probabilités sont des préférences, jamais des substituts aux quotas.

- Les quotas restants sont des contraintes dures.
- Le poids du prochain par dépend de sa préférence de position, du quota
  restant, des emplacements restants et des pars déjà posés.
- Pour le trou 1, le prototype pourra commencer avec les poids indicatifs
  par 4 = 90 %, par 3 = 8 %, par 5 = 2 %.
- Ces chiffres restent configurables et ne seront pas optimisés avant que le
  paving géométrique fonctionne.

## Stratégie de recherche cible

Le paveur ne sera pas purement glouton. Un état de recherche contient :

- les haricots placés et leurs transformations ;
- le prochain green à relier ;
- les candidats déjà consommés ;
- les quotas de pars restants ;
- l'occupation spatiale ;
- un score et les statistiques de rejet.

Pour chaque profondeur :

1. choisir plusieurs classes de par encore compatibles avec les quotas ;
2. choisir plusieurs haricots inutilisés ;
3. essayer rotations, miroir et positions de tee dans l'anneau de liaison ;
4. rejeter immédiatement les contraintes dures ;
5. noter compacité, diversité des directions, espace restant et capacité de
   retour clubhouse ;
6. conserver les meilleurs états dans un beam borné ;
7. revenir en arrière si aucun état ne peut continuer.

Un SVG du meilleur état doit être produit même en cas d'échec.

## Étapes autonomes

### Étape 1 — Contrats abstraits et génération de banque

Créer les types minimaux :

- `BeanTemplate` : géométrie locale, ports et empreinte ;
- `BeanBank` : candidats déterministes d'une seed ;
- paramètres de génération par classe ;
- sérialisation JSON de diagnostic.

Générer une banque de nine de 18 candidats avec les quotas `4/10/4`. Les
formes peuvent être construites par un axe polygonal épaissi ; aucun détail
golfique supplémentaire.

**Terminé lorsque :** les 18 identifiants sont uniques, les classes et plages
de dimensions sont correctes, la même seed produit exactement le même JSON et
plusieurs seeds donnent des banques différentes.

**Livrable visuel :** planche SVG des 18 haricots de la seed témoin.

**Point de reprise :** partir uniquement des contrats sérialisés ; ne pas
commencer le placement spatial dans cette étape.

### Étape 2 — Transformations et validateur géométrique

Implémenter indépendamment du paveur :

- translation, rotation discrète et miroir ;
- limites de carte ;
- collision d'empreintes ;
- intersection exacte des axes ;
- règle anti-parallélisme ;
- distance entre ports green et tee.

Tester des cas synthétiques positifs et négatifs, notamment les formes qui se
touchent presque, se croisent ou effectuent un aller-retour parallèle.

**Terminé lorsque :** chaque règle possède au moins un test qui échoue sans
elle et le validateur ne dépend d'aucune décision du futur solveur.

**Livrable visuel :** petite galerie SVG des violations géométriques.

**Point de reprise :** conserver le validateur comme oracle indépendant ; ne
pas ajouter d'exemption pour faire passer un résultat du solveur.

### Étape 3 — Placement séquentiel local

Placer sans recherche globale :

- le premier haricot près du clubhouse ;
- un deuxième à une liaison valide ;
- une courte chaîne de trois ou quatre candidats ;
- rotations et miroirs déterministes pour une seed.

Les liaisons peuvent traverser les empreintes. Seuls les axes et empreintes des
trous participent aux contraintes spatiales.

**Terminé lorsque :** plusieurs petites chaînes passent le validateur et les
causes d'échec sont comptabilisées.

**Livrable visuel :** SVG d'une chaîne locale avec ports et empreintes.

**Point de reprise :** la chaîne n'a pas encore à revenir au clubhouse ; ne
pas masquer une collision pour l'allonger.

### Étape 4 — Paveur beam/backtracking d'un nine

Construire le solveur borné :

- quotas `2/5/2` exacts ;
- sélection pondérée des pars ;
- candidats inutilisés seulement ;
- beam configurable ;
- backtracking ;
- score de compacité, variété, espace libre et retour possible ;
- diagnostics par profondeur et cause de rejet.

La capacité de retour ne doit pas être vérifiée seulement au trou 9. Le score
doit pénaliser progressivement les états dont le green courant ne laisse plus
de route plausible vers le clubhouse.

**Terminé lorsque :** au moins une seed produit neuf haricots valides en
350x350 avec retour clubhouse, sans intervention manuelle.

**Livrable visuel :** SVG du témoin valide et SVG du meilleur état d'un échec.

**Point de reprise :** conserver la seed témoin, les paramètres de beam et le
nombre d'états explorés.

### Étape 5 — Benchmark seeds 1 à 10

Mesurer sur 350x350 :

- succès et temps par seed ;
- états développés et retours arrière ;
- profondeur maximale des échecs ;
- causes de rejet ;
- distribution des pars dans l'ordre ;
- occupation de carte ;
- diversité des orientations ;
- doublons exacts ou quasi-doublons ;
- conformité visuelle de la règle anti-parallélisme.

Seuils de décision :

- 8 à 10 succès : paving abstrait validé ;
- 5 à 7 succès : prometteur, ajuster le solveur ;
- moins de 5 succès : revoir le paving avant tout générateur de trous ;
- toute violation dure : résultat invalide.

**Terminé lorsque :** un rapport reproductible permet une décision explicite.

**Point de reprise :** commencer par la conclusion et les seeds en échec.

### Étape 6 — Banque de 36 et parcours de 18 trous

Seulement après validation du nine :

- banque `8/20/8` ;
- sélection finale `4/10/4` ;
- construction de deux nines ;
- départs et retours clubhouse distincts ;
- occupation commune de la même carte.

Tester d'abord deux recherches de nine coordonnées avant une recherche globale
de profondeur 18.

**Terminé lorsque :** au moins un parcours abstrait de 18 trous passe le même
validateur indépendant.

**Livrable visuel :** SVG complet avec front/back différenciés.

### Étape 7 — Remplacement progressif par de vrais trous

Si et seulement si le paving abstrait est validé :

1. remplacer l'axe abstrait par une géométrie de trou compatible ;
2. conserver exactement les mêmes ports et empreintes ;
3. ajouter longueurs golfiques, doglegs, largeurs et greens ;
4. comparer les taux de réussite avant/après substitution.

Cette étape doit réutiliser le paveur et son validateur, pas créer un nouveau
routeur parallèle.

**Terminé lorsque :** la substitution ne casse ni déterminisme ni contraintes
spatiales et produit un parcours visualisable dans le viewer.

## Discipline de travail

1. Une session ne commence qu'une seule étape.
2. Aucune étape suivante ne démarre avant les critères de fin de l'étape
   courante.
3. Chaque étape se termine par tests, visuel, résultat et point de reprise.
4. Un échec est enregistré avec son meilleur état et ses causes ; il ne doit
   pas être transformé en succès par une exemption implicite.
5. Les paramètres expérimentaux restent dans `experiments/bean_paving/`.
6. `golfgen/loop_router.py` reste inchangé pendant le spike.
7. Aucun benchmark multi-seeds n'est lancé avant l'étape 5.
8. Décision utilisateur 2026-10-04 : le solveur conjoint (`joint_solver.py`,
   `solve_course_joint`) est **abandonné** — ses sorties visuelles jugées
   trop symétriques (deux nines qui se répondent en miroir plutôt que des
   formes variées). Le code reste dans le dépôt pour référence, mais n'est
   plus lancé dans aucune session suivante ; seul le solveur séquentiel
   (`solve_course`) reste actif.
9. Décision utilisateur 2026-10-05 : le mode lobe (`lobe.py`,
   `lobe_search.py`, `EXPERIMENT_18_LOBES.md`) est **abandonné** — sur les 4
   tirages testés à 350×350 (`shared_rough`), le back reste bloqué à 0/9
   dans les 4 cas, avant et après le seul ajustement permis. Développé sur la
   branche `rambo/lobe-targets`, jamais fusionnée dans `spike/bean-paving` ;
   le mode radial (anneaux par profondeur) reste le seul actif.

## Avancement

| Étape | État | Résultat / reprise |
|---|---|---|
| 1. Contrats et banque de 18 | Terminé | Seed témoin 42, 4 tests, JSON et planche SVG reproductibles |
| 2. Transformations et validateur | Terminé | 13 cas géométriques, galerie SVG ; oracle sans dépendance au solveur |
| 3. Placement local | Terminé | Chaînes 4/4 valides sur seeds 1, 7, 42, 123 ; seed 42 en 340 essais |
| 4. Paveur d'un nine | Terminé | Seed 42 valide, beam 48, 68 850 essais, 5 fermetures ; échec intermédiaire conservé |
| 5. Benchmark 1..10 | Terminé | 10/10, 0 violation dure, 0 doublon exact ; biais pourtour et départ par 3 consignés |
| 6. Banque de 36 et 18 trous | Partiel | 350 (règles d'origine) : séquentiel 9+1, conjoint ≤9/18 ; 500 : 18/18. Variante `shared_rough` (350 seulement) : séquentiel 16/18 (front 9+back 7), conjoint 11/18 (front 6+back 5). **Solveur conjoint abandonné le 2026-10-04** (décision utilisateur : sorties trop symétriques visuellement) — non relancé depuis. Suite (exclusion clubhouse dure + biais souple de demi-plan + recherche d'orientation, séquentiel uniquement) : toujours 16/18 au mieux à 350×350, voir `EXPERIMENT_18_HALFPLANE.md`. **Mode lobe abandonné le 2026-10-05** (décision utilisateur, 4 tirages à 350×350, back bloqué à 0/9 sur les 4 ; branche `rambo/lobe-targets` non fusionnée). **400×400, séquentiel, `shared_rough` + exclusion clubhouse (mêmes paramètres de beam que le run 350) : 18/18 (seed 42, un seul tirage)** — voir `EXPERIMENT_18_ROUGH.md`, section « Essai 400×400 » ; taille de carte et exclusion clubhouse confondues dans ce résultat, pas de benchmark multi-seed. **Benchmark seeds 1 à 10, mêmes paramètres (400×400, `shared_rough`, `fairway_gap=5`, `edge_min=1`, `max_parallel_stack=3`, `clubhouse_clear_radius=10`, poids demi-plan 0, 10 recherches en parallèle sur 16 cœurs) : 0/10 — le front se ferme toujours à 9/9 mais le back plafonne systématiquement à 7-8/9, jamais 9/9 ; `fairway_gap` puis `axis_crossing` puis `bounds` dominent les rejets, `parallel_stack` reste marginal (~2 %), pile maximale observée 2-3 ; validation indépendante (`geometry.validate` + contrôle clubhouse, méthode `course_solver._course_violations`) confirme 0/10 sans divergence avec le solveur** — la seed 42 (18/18) n'appartient pas à cet échantillon 1-10 et reste un cas isolé non représentatif ; voir `experiments/bean_paving/output/benchmark_course18_400_1_10/REPORT.md`. **Quota global libre (`solve_course(free_quota=True)`) + fermeture anticipée du back (`closing_lookahead_from=7`), seeds 2/8/9 (bloquées 8/9) et 1 (bloquée 7/9) : 0/4, net recul** — le front, libre sur le quota global 4/10/4, épuise systématiquement (4 seeds sur 4) l'intégralité du par3 et n'en laisse aucun au back, qui meurt alors à la profondeur 1 (`clubhouse_departure`, 100 % des essais) au lieu de 7-8/9 comme dans le benchmark ; la fermeture anticipée n'a donc jamais pu être exercée. Variante `closing_lookahead_from=6` testée (seule, comme prévu) : résultat identique (0/4), confirmant que la cause est le quota libre, pas la profondeur de la fermeture anticipée. **Reprise : A) quota fixe `2/5/2` + fermeture anticipée isolée (`lookahead=7`, sans quota libre) sur les mêmes 4 seeds : 0/4, back identique trou pour trou au benchmark (8,8,8,7) — la fermeture anticipée est bien exercée (336 à 2956 appels/seed) mais renvoie `False` 100 % du temps, elle détecte le blocage géométrique sans le lever tant que le quota par-nine reste fixe. B) quota BORNÉ par nine (`solve_course(bounded_quota=True)`, nouveau opt-in, défaut inchangé) : chaque nine doit finir avec par3 ET par5 dans `[1, 3]` (bornes paramétrables), par4 libre jusqu'à 9, total global `4/10/4` exact — le front ne peut prendre une classe que si le reste global après coup laisse encore à l'autre nine son propre minimum (recalculé à chaque pas, jamais un compteur périmé) ; même fermeture anticipée `lookahead=7` : **3/4** — seeds 2, 8, 1 ferment à 18/18 (validation indépendante conforme), seule la seed 9 reste bloquée à 8/9 (`clubhouse_return` dominant en fin de nine, même quota que les succès — blocage géométrique propre à cette seed, pas une carence de quota). Premier résultat de la série à dépasser le plafond historique 7-8/9.** Voir `experiments/bean_paving/EXPERIMENT_18_CLOSURE.md`, section « Reprise — A/B quota fixe vs quota borné ». **Config B étendue aux seeds 1 à 10 (`bounded_quota=True`, `back_closing_lookahead_from=7`, mêmes règles 400×400, 10 recherches en parallèle sur 16 cœurs, temps réel mesuré par seed dans chaque process) : 5/10 complet, 5/10 validé indépendamment (seeds 1, 2, 3, 4, 8), contre 0/10 pour le benchmark séquentiel de référence (quota fixe `2/5/2`, lookahead 9) — les 3 seeds déjà résolues en B sur l'échantillon à 4 seeds (1, 2, 8) reproduisent EXACTEMENT les mêmes pars front/back (déterminisme confirmé). Échecs (5, 6, 7, 9, 10) toujours bloqués en fin de nine (profondeur 7-9), causes dominantes identiques (`fairway_gap`, `axis_crossing`, `bounds`, puis `clubhouse_return` à la profondeur 9) ; temps par seed très variable (525s à 2009s), temps total du run 2009s (le plus lent, seed 4, domine car les 10 seeds tournent en parallèle sur 16 cœurs). Le quota borné améliore nettement le taux de succès (0/10 → 5/10) mais ne généralise pas le 3/4 observé sur l'échantillon restreint. Voir `experiments/bean_paving/output/benchmark_course18_400_bounded_1_10/REPORT.md`. |
| 7. Substitution par vrais trous | À faire | — |
