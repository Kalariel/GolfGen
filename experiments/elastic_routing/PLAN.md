# Spike `elastic_routing` — parcours global à trous déformables

## Décision

Le spike `bean_paving` reste une source d'oracles géométriques, de règles et
de diagnostics, mais son modèle de placement de formes rigides n'est plus la
direction proposée pour le générateur final.

Le nouveau spike combine :

1. un **squelette global** qui organise les deux nines et leurs liaisons ;
2. des **trous élastiques**, modifiables localement pendant l'optimisation ;
3. une validation finale stricte, indépendante de l'optimiseur ;
4. un budget de calcul court et explicite.

L'objectif n'est pas de rendre le beam search actuel plus large. Il est de
changer la représentation du problème pour qu'une impasse tardive puisse être
réparée par de petites déformations, sans reconstruire le parcours depuis le
premier trou.

## Pourquoi quitter le bean paving comme solveur principal

Dans `bean_paving`, un trou est une pièce préfabriquée. Une fois son gabarit
choisi, le solveur peut surtout le translater, le tourner ou le mirrorer. Il ne
peut pas reprendre quelques blocs à sa longueur, ouvrir un dogleg, déplacer un
green ou réduire légèrement sa largeur.

Cette rigidité transforme les derniers trous en problème combinatoire : une
solution presque correcte à 8/9 ne fournit aucune direction de réparation. Le
solveur essaie alors un grand nombre d'autres pièces et de placements complets.

La config C1 a confirmé la limite :

- seeds 1–5 : 5/5, mais 1054–2474 s par seed ;
- seed 7 : succès en 876,8 s ;
- seed 10 : succès en 942,5 s ;
- seed 6 : échec à 8/9 après trois candidats, 930,1 s ;
- seed 8 : échec à 8/9 après trois candidats, 1563,0 s ;
- seed 9 : troisième candidat interrompu, coût déjà prohibitif.

Le problème n'est donc pas seulement de trouver de meilleurs candidats de
tee 10. Le solveur manque de degrés de liberté continus et d'un mécanisme de
réparation globale.

## Hypothèse du spike

Un parcours 18 trous sans terrain contraignant doit pouvoir être produit de
manière fiable en 400×400 si :

- la topologie des deux nines est conçue globalement ;
- les liaisons piétonnes sont présentes dès la construction ;
- les formes des trous restent modifiables ;
- les contraintes sont introduites progressivement ;
- une impasse locale peut déplacer plusieurs trous voisins ;
- le calcul est arrêté rapidement lorsqu'une stratégie ne converge pas.

## Représentation

### Parcours

Le parcours contient deux séquences distinctes :

```text
clubhouse -> tee 1  -> trou 1  -> green 1  -> liaison -> ...
          -> tee 9  -> trou 9  -> green 9  -> clubhouse

clubhouse -> tee 10 -> trou 10 -> green 10 -> liaison -> ...
          -> tee 18 -> trou 18 -> green 18 -> clubhouse
```

Les liaisons ne sont plus dérivées après coup. Elles font partie du squelette
alterné `trou long / liaison courte` et influencent le placement global.

### Trou élastique

Un trou est défini par :

- un tee ;
- un green ;
- zéro, un ou deux points de contrôle de dogleg ;
- une classe de par ;
- une plage de longueur autorisée ;
- une largeur de fairway dans une plage autorisée ;
- une marge de rough ;
- un axe orienté tee -> green, reconstruit depuis ces points.

Il ne dépend pas d'un gabarit immuable tiré dans une banque.

Les micro-modifications autorisées sont notamment :

- déplacer le tee ou le green de quelques blocs ;
- déplacer un point de dogleg ;
- modifier l'angle d'un dogleg ;
- allonger ou raccourcir un ou plusieurs segments ;
- ajuster légèrement la largeur du fairway ;
- ajouter ou retirer un dogleg lorsque la classe de par l'autorise ;
- échanger les classes de par de deux trous si les longueurs restent valides
  et si le quota global est conservé.

## Solveur proposé

Le spike sépare la recherche en deux niveaux. Il ne manipule pas les polygones
finaux à pleine précision pendant toute la recherche.

### Niveau 1 — squelette global grossier

Sur une grille de 5 blocs environ :

- construire deux nines qui partent du clubhouse et y reviennent ;
- alterner corridors jouables longs et liaisons courtes ;
- réserver les ports du tee 1, du tee 10, du green 9 et du green 18 ;
- éviter les croisements topologiques ;
- maintenir une enveloppe grossière pour chaque futur fairway ;
- garder une asymétrie seedée afin d'éviter deux boucles artificiellement
  identiques.

Ce niveau cherche une topologie plausible, pas encore un dessin final.

### Niveau 2 — raffinement élastique

Convertir le squelette en axes continus, puis l'améliorer par recherche locale
à grand voisinage, avec recuit simulé ou mécanisme équivalent.

Une mutation agit sur un petit voisinage : un trou, une liaison, ou un groupe
de 2 à 5 trous contigus. Une réparation tardive du back peut ainsi déplacer les
trous 14–17 au lieu de rejouer les trous 10–18.

Exemples de mouvements :

- translation ou rotation locale ;
- déplacement d'un port partagé par un trou et sa liaison ;
- déformation d'un dogleg ;
- compression ou expansion répartie sur plusieurs trous ;
- échange de par entre deux positions ;
- reroutage d'une fenêtre de trous ;
- déplacement collectif d'un paquet parallèle.

Les vérifications et les scores doivent être recalculés localement autant que
possible. Les paires géométriquement éloignées ne doivent pas être retestées à
chaque mutation.

### Durcissement progressif

La recherche suit une logique d'« inflation » :

1. axes minces, longueurs et largeurs encore souples ;
2. suppression des croisements ;
3. augmentation progressive des largeurs et de l'écart entre fairways ;
4. resserrement des plages de longueur et de dogleg ;
5. application complète des contraintes clubhouse et liaisons ;
6. validation finale avec les dimensions réelles.

Une configuration presque correcte peut ainsi se réorganiser avant que les
fairways à largeur complète ne ferment tous les passages.

## Contraintes

### Contraintes finales dures

- carte 400×400 ;
- 18 trous complets ;
- distribution exacte 4 par 3 / 10 par 4 / 4 par 5 pour le premier spike ;
- chaque longueur dans la plage de sa classe de par ;
- tee, green et axe dans les limites ;
- aucun croisement d'axes non autorisé ;
- écart bord à bord entre fairways >= 5 blocs ;
- rough partagé autorisé ;
- au plus 3 fairways dans une pile parallèle ;
- aucun fairway à moins de 10 blocs du clubhouse ;
- tee 1 et tee 10 desservis depuis le clubhouse sans traverser un autre
  fairway ;
- green 9 et green 18 reliés au clubhouse sans traverser un autre fairway ;
- chaque green relié au tee suivant par une liaison praticable ;
- validation indépendante sans violation.

La répartition des par 5 entre les nines n'est pas fixée à 2/2. Chaque nine
reste dans une plage acceptable, initialement `[1, 3]`, pendant que le total
global reste exactement 4.

### Objectifs souples

- variété des caps et des doglegs ;
- éviter les longues séries parallèles ;
- objectif « voyage » (souple, à pondérer à l'étape 5, distinct de la
  violation dure `parallel_stack`) : une série de 3 trous consécutifs côte à
  côte est autorisée mais pénalisée, une simple paire consécutive côte à côte
  légèrement pénalisée ; favoriser une trajectoire de nine qui s'éloigne puis
  revient progressivement plutôt que des allers-retours sur place ; un
  voisinage avec un trou non consécutif (ex. le 5 et le 15) reste neutre,
  voire favorable ;
- limiter la distance totale des liaisons ;
- éviter les fairways inutilement proches du bord ;
- répartir l'occupation de la carte sans produire deux demi-cartes visibles ;
- favoriser des retours naturels du 9 et du 18 ;
- pénaliser les déformations extrêmes ;
- favoriser une distribution 2/2 des par 5 sans la rendre obligatoire ;
- éviter une symétrie excessive entre front et back.

Les objectifs souples ne peuvent jamais transformer une violation dure en
succès.

## Budget de calcul

Pour chaque seed :

- **cible** : première solution valide en moins de 60 s ;
- **garde-fou absolu** : arrêt à 120 s ;
- aucun élargissement automatique du budget ;
- un timeout est un échec explicite et produit quand même les diagnostics et
  le meilleur SVG partiel ;
- temps par phase et nombre d'évaluations consignés dans le rapport.

Pour préserver la reproductibilité, la recherche utilise une seed et un budget
déterministe d'évaluations. Le garde-fou mural de 120 s protège la session mais
ne remplace pas ce budget déterministe.

## Réutilisation de `bean_paving`

À conserver ou adapter :

- les primitives géométriques ;
- le calcul des axes, cœurs de fairway et empreintes ;
- `ValidationRules` et la validation indépendante ;
- les règles `shared_rough`, `fairway_gap`, limites et piles parallèles ;
- les contrôles clubhouse et liaisons praticables ;
- les diagnostics de violations ;
- le rendu SVG et les conventions de couleurs ;
- les tests unitaires des règles géométriques.

À ne pas reprendre comme moteur :

- la banque de formes fixes ;
- le placement séquentiel irréversible front puis back ;
- l'énumération massive de transformations rigides ;
- l'augmentation du beam comme principal levier de robustesse ;
- les profils radiaux fixes qui imposent des arcs similaires.

## Feuille de route et suivi

Le spike n'est pas développé en une seule passe. Chaque étape produit un
résultat isolé, relu et testable. La suivante ne commence qu'après validation
de sa sortie. Cette checklist est la source de vérité de l'avancement et doit
être mise à jour au fil du travail.

Règles de suivi :

- cocher une étape uniquement lorsque son livrable et ses vérifications sont
  terminés ;
- inscrire sous l'étape la date, le résultat et les chemins des artefacts ;
- relire le diff et exécuter les tests pertinents avant chaque porte ;
- ne lancer qu'une expérience à la fois ;
- regarder les SVG avant de choisir l'expérience suivante ;
- ne jamais augmenter silencieusement le budget de calcul ;
- arrêter et revenir au plan si une étape exige de modifier plusieurs familles
  de mécanismes à la fois.

### Étape 0 — décision et cadrage

- [x] Constater la limite de `bean_paving` comme solveur principal.
- [x] Choisir l'architecture « squelette global + trous élastiques ».
- [x] Rédiger le présent plan, les contraintes et les critères d'arrêt.
- [x] Relire et valider les choix encore ouverts avec l'utilisateur.

**Validation du 2026-10-06** : les six paramètres de départ proposés ont été
acceptés sans modification ; la Porte 0 est franchie.

**Porte 0 — franchie** : les paramètres de départ sont consignés dans
« Décisions validées avant implémentation ».

### Étape 1 — contrats et modèle de données

- [x] Définir les structures minimales `CourseLayout`, `NineLayout`,
  `ElasticHole`, `WalkingLink` et `ControlPoint`.
- [x] Encoder les plages validées de longueur, largeur et nombre de doglegs.
- [x] Garantir une sérialisation JSON déterministe.
- [x] Écrire les tests des transformations et invariants élémentaires.

**Résultat du 2026-10-06** : modèle immuable dans `model.py`, API publique
dans `__init__.py` et 12 tests dédiés dans
`tests/test_elastic_routing_model.py`. Les dimensions provisoires peuvent
sortir de leur plage pendant une future réparation, mais les incohérences
structurelles sont refusées immédiatement : ordre 1–18, deux nines de neuf
trous, liaisons explicites cohérentes, zéro segment nul, au plus deux doglegs
et quota global exact 4/10/4. La suite complète passe à **259/259** en
325,59 s.

**Livrable** : modèle instanciable et sérialisable, sans solveur.

**Porte 1 — franchie** : validation administrative consignée le 2026-10-06.

### Étape 2 — oracle indépendant et rendu

- [x] Adapter les primitives utiles de `bean_paving` sans importer son moteur
  de recherche.
- [x] Construire les fairways et roughs depuis les axes élastiques.
- [x] Valider limites, longueurs, croisements, écart entre fairways, clubhouse,
  quotas et liaisons.
- [x] Produire un SVG lisible montrant trous, liaisons, clubhouse, numéros et
  violations.
- [x] Tester chaque famille de violation avec de petits cas synthétiques.

**Résultat du 2026-10-06** : oracle indépendant dans `geometry.py`, rendu dans
`render.py` et layout manuel de diagnostic dans `synthetic.py`. Les 12 tests
ajoutés à cette étape couvrent la construction des empreintes, les paramètres
invalides, longueurs, largeurs, limites, croisements, écart entre fairways,
clubhouse, piles parallèles, quotas par nine et liaisons. Le sous-ensemble
géométrique élargi passe à **84/84** et la suite complète à **271/271** en
318,74 s.

Le runner `run_step2_synthetic.py` produit JSON, rapport et SVG dans
`output/step2_synthetic/`. Le layout est volontairement valide avec les règles
permissives et invalide avec les règles finales : 14 violations attendues
(4 distances de liaison, 6 liaisons bloquées et 4 piles parallèles). Le SVG a
été inspecté : trous, axes, empreintes, liaisons, clubhouse, numéros et
surbrillance rose des violations sont lisibles et cohérents avec le rapport.

**Livrable** : un layout écrit à la main peut être rendu et déclaré valide ou
invalide par un oracle qui ne dépend pas du futur optimiseur.

**Porte 2 — franchie** le 2026-10-06. Le SVG synthétique a été revu : axes,
empreintes, liaisons, numéros et violations lisibles, 14 violations
cohérentes avec le rapport. Il ne valide aucune qualité de génération (le
layout est artificiel). Mesure consignée : l'oracle complet coûte 11,46 ms
par validation (~87/s), donc 100 000 validations ≈ 19 min. Incompatible avec
la cible de 60 s : un score incrémental est obligatoire (voir « Décision
d'architecture avant l'étape 3 »).

### Décision d'architecture avant l'étape 3

**Décisions validées par l'utilisateur le 2026-10-06 (seconde série).**

#### a. Niveau 1 = contour d'un arbre aléatoire

Le niveau 1 ne « génère » plus une topologie par construction directe de
corridors ; il construit un arbre aléatoire puis en extrait le contour.
Algorithme officiel :

1. arbre enraciné au clubhouse, exactement deux sous-arbres racines (un par
   nine) ;
2. croissance alternée des deux sous-arbres, seedée, sans retour arrière ;
3. budget de longueur cible propre à chaque sous-arbre ;
4. halo interdisant tout contact entre arêtes/cellules non voisines dans
   l'arbre, y compris entre les deux sous-arbres racines (le pas de grille et
   le halo garantissent que le contour épaissi ne se touche pas lui-même) ;
5. nombre maximal de feuilles par sous-arbre (chaque feuille = une épingle ;
   chaque nine n'a que dix fenêtres de liaison pour absorber épingles et
   virages serrés) ; borne éventuelle sur les virages serrés ;
6. rejet complet, déterministe et peu coûteux de l'arbre si un budget ne peut
   être atteint (pas de retour arrière interne) ;
7. épaississement de l'arbre puis extraction de son contour (courbe simple
   par construction) ;
8. coupure du contour à ses deux passages au clubhouse → deux arcs
   clubhouse→clubhouse = front et back ;
9. DP de découpage sur chaque arc, inspirée de `_cut_nine()` de
   `golfgen/loop_router.py` (adaptation probable, pas réutilisation telle
   quelle) ;
10. validation par l'oracle indépendant.

Nuances :

- « sans impasse » vaut seulement au sens topologique : une branche peut
  épuiser son espace disponible, ce qui provoque un rejet complet bon marché
  de l'arbre ; ce n'est pas le problème combinatoire de `bean_paving` ;
- risque de parallélisme : chaque branche produit naturellement une paire
  aller/retour (acceptée) ; une interdiction locale de deux arêtes parallèles
  dans des cellules voisines doit suffire à limiter les piles à plus de
  quatre.

#### b. Place de `loop_router`

`loop_router` reste une baseline de temps et de validité, une source de
primitives et de la DP de découpage, et une éventuelle solution de secours
pour tester le pipeline. Il n'est PAS la graine de l'optimisation : sa
partition diagonale en triangles miroirs est structurelle, des mutations
locales ne la défont pas.

#### c. Score incrémental obligatoire

Conçu avant l'optimiseur, pas après. Cache : géométrie dérivée par trou,
pénalités par trou, matrice des pénalités par paire, pénalités par liaison,
agrégats par nine et globaux.

Chaîne d'évaluation :

1. boîtes englobantes élargies (en cache, pas d'index spatial complexe pour
   18 trous) ;
2. si proches, distance entre axes moins demi-largeurs (surrogate exact pour
   des capsules, mais l'oracle utilise des extrémités prolongées et des
   joints biseautés : une marge conservatrice est obligatoire) ;
3. oracle polygonal complet seulement périodiquement, pour les candidats
   prometteurs et la validation finale ; seul l'oracle polygonal décide du
   succès.

Le microbenchmark doit mesurer une mutation complète (géométrie + paires
touchées + score) et démontrer < ~0,6 ms, sinon 100 000 évaluations sont
incompatibles avec 60 s.

#### d. Score vectoriel

Composantes : topologie, croisements, écarts, longueurs, liaisons, clubhouse,
parallélisme, variété, déformation. Chaque phase d'inflation change
tolérances et poids sans toucher l'oracle ni le stockage incrémental. Léger
réchauffement de la température à chaque phase d'inflation. Pourcentages de
budget et températures fixés à l'étape 5 après mesures.

#### e. Définitions

- **pile parallèle** = série d'au moins quatre trous **consécutifs dans
  l'ordre de jeu**, à l'intérieur d'un même nine (la coupure 9→10, comme
  18→1, ne compte jamais), telle que chaque trou est `side_by_side` avec le
  suivant (angle ≤ 20°, recouvrement projeté > 40 blocs, roughs en contact)
  ET que tous les trous de la série sont alignés deux à deux (angle +
  recouvrement projeté, sans exigence de contact — ce second critère exclut
  l'éventail qui tourne progressivement : chaque voisin aligné, mais les
  extrémités ne le sont plus). Le critère est le *voyage* du joueur, pas la
  seule géométrie : deux trous côte à côte mais non consécutifs dans l'ordre
  de jeu (ex. le 5 et le 15) ne sont jamais une pile. Une violation par série
  maximale, diagnostics triés pour un résultat déterministe. Les cliques
  maximales du graphe `side_by_side` ont été essayées (étape 2b, première
  passe) puis abandonnées : `side_by_side` exige un contact de rough, or
  dans une vraie pile de bandes parallèles chaque trou ne touche que ses
  voisins immédiats — aucune clique de taille > 2 sans fairways superposés,
  donc la définition par clique ne détectait plus aucune vraie pile ;
- **liaison praticable** = segment droit de 12 à 45 blocs ne traversant le
  cœur d'aucun fairway non propriétaire ; 12–45 est la plage de validation
  finale, la construction tolère 12–60 avec resserrement progressif
  (décision 3) ; pas de chemin routé dans ce spike (viendra avec les
  obstacles réels).

### Étape 2b — oracle : piles par séries consécutives

Première passe (cliques maximales, voir historique ci-dessous) abandonnée :
`side_by_side` exige un contact de rough, or dans une vraie pile de bandes
parallèles chaque trou ne touche que ses voisins immédiats — aucune clique de
taille > 2 sans fairways superposés. Sur le layout synthétique, les vraies
piles 1-5 et 11-14 n'étaient plus détectées (décompte retombé à 0, faux
négatif). Nouvelle définition validée par l'utilisateur : le critère est le
*voyage* du joueur (série de trous consécutifs dans l'ordre de jeu), pas la
seule géométrie — voir « Décision d'architecture avant l'étape 3 », point e.

- [x] Remplacer les cliques maximales par un parcours linéaire de chaque nine
  détectant les séries de trous consécutifs dans l'ordre de jeu.
- [x] Tester : 4 trous consécutifs empilés déclenchent une violation ; 3 non.
- [x] Tester : 4 trous empilés mais non consécutifs dans l'ordre de jeu (y
  compris à cheval sur les deux nines) ne produisent aucune violation.
- [x] Tester : un éventail de trous consécutifs en contact qui tourne
  progressivement (chaque voisin aligné, les extrémités non) ne produit
  aucune violation.
- [x] Tester : deux séries fautives distinctes produisent deux diagnostics.
- [x] Tester : une série coupée au passage 9→10 ne fusionne pas.
- [x] Vérifier le cas synthétique de l'étape 2 : le décompte (4
  `parallel_stack`) reste cohérent, ou est explicitement actualisé.

**Porte 2b — franchie le 2026-10-07** : SVG revu par l'utilisateur, 4 séries
détectées (cohérent avec le décompte de 4 `parallel_stack` ci-dessous).

#### Paramètres validés le 2026-10-07 pour l'étape 3

- **Offset du contour** = 12 blocs (les fairways aller/retour d'une même
  branche sont alors à 24 blocs centre à centre, ≥ 18 + 5 requis) ; à
  réajuster si le rendu est moyen.
- **Halo** : deux parties de l'arbre non reliées localement doivent être à
  ≥ 2×12 + 23 = 47 blocs (≈ 10 cellules à pas 5), y compris entre les deux
  sous-arbres racines et près du clubhouse.
- **Longueur d'arbre visée par sous-arbre** ≈ 550–950 blocs (contour ≈ 2 ×
  arbre + caps ; nine ≈ 1220–2015 blocs avec liaisons de construction
  12–60) — plage à recalculer précisément dans le code depuis `PAR_SPECS`
  plutôt que figée en dur.
- Au plus 3 feuilles par sous-arbre ; branche menant à une feuille
  ≥ ~300 blocs (≈ 2 trous par côté).
- Grille à pas de 5 blocs, 8 voisins.
- Pas de `shapely` : le contour est le tour (d'Euler) de l'arbre décalé
  d'un côté, congés en arc, caps en demi-cercle, comme le ruban de
  `golfgen/loop_router.py`.
- Biais de croissance « voyage » : ~60 % du budget vers l'extérieur du
  clubhouse, puis vers le clubhouse ; asymétrie seedée par nine.

Ces paramètres corrigent les erreurs du tout premier brouillon (offset 9,
halo à 5 cellules, arbre visé 1300–1400 blocs), qui ne doivent pas
réapparaître dans le code ou la documentation.

**Porte 2b** : revue des tests et du nouveau décompte avant l'étape 3 — prête
pour validation (pas franchie, l'utilisateur valide).

**Résultat du 2026-10-06** : `_maximal_cliques` (Bron–Kerbosch) supprimé,
remplacé par `_consecutive_parallel_series` dans `geometry.py` — pour chaque
nine (front, back séparément, jamais fusionnés entre eux), parcours linéaire
des trous dans l'ordre de jeu ; une série de trous consécutifs est une
fenêtre maximale où (a) chaque trou est `_side_by_side` avec le suivant
(contact + alignement, inchangé) et (b) tous les trous de la fenêtre sont
alignés deux à deux (angle ≤ 20°, recouvrement projeté > 40 blocs, SANS
exigence de contact — critère extrait de `_side_by_side` dans le nouveau
helper `_aligned_overlap`, mêmes seuils). Justification de l'algorithme :
fermeture par préfixe retiré du prédicat de validité d'une fenêtre (si
`[start, end]` est valide, `[start+1, end]` l'est aussi, chaîne et paires
alignées étant un sous-ensemble de celles déjà vérifiées), donc la fenêtre
commençant à `start+1` est soit incluse dans celle commençant à `start`, soit
la prolonge strictement — jamais un cas intermédiaire. Cela permet de
calculer les séries réellement maximales en O(n²) par nine sans retour en
arrière. Une violation par série maximale de taille strictement supérieure à
`max_parallel_stack` (3), diagnostics triés par tuple de trous. Deux séries
maximales peuvent se chevaucher sans que l'une contienne l'autre (l'alignement
deux à deux peut casser au milieu d'une série plus longue) : c'est voulu,
chacune est alors un diagnostic distinct.

9 tests ajoutés/remplacés dans `tests/test_elastic_routing_geometry.py` : 4
consécutifs empilés → 1 violation ; 3 → 0 ; 4 empilés non consécutifs dans
l'ordre de jeu (2,4,6,8 et 2,5,12,15 à cheval sur les nines) → 0 ; éventail de
4 consécutifs en contact qui tourne (voisins à 15°, extrémités à 45°) → 0 ;
deux séries fautives distinctes (bandes séparées) → 2 diagnostics ; deux
séries maximales qui se chevauchent sans inclusion mutuelle (l'alignement
casse au milieu d'une bande de 6 trous chaînés, ex. 2 n'est plus aligné avec
6 mais 3 reste aligné avec 7) → 2 diagnostics `[2..5]` et `[3..7]` ; série de
6 rangées à cheval sur 9→10 (3 trous par nine, sous le seuil) → aucune
fusion, 0 violation ; décompte du layout synthétique explicitement actualisé
et vérifié. Les géométries de test utilisent un espacement de 20 blocs entre
rangées (comme le layout synthétique), pas 6 (superposition de fairways
irréaliste de la version précédente). 1 test de rendu `parallel_stack`
simplifié pour réutiliser directement le layout synthétique (qui couvre de
nouveau ce cas), sans réimporter de fixture entre modules de test. Suite
ciblée :
`pytest tests/test_elastic_routing_geometry.py tests/test_elastic_routing_model.py
tests/test_elastic_routing_render.py` → 33 passed.

Décompte du cas synthétique : **4** `parallel_stack` (violations totales 14,
comme avant l'introduction des cliques) : 1-2-3-4-5, 6-7-8-9, 10-11-12-13-14,
15-16-17-18. Les bornes diffèrent légèrement de l'estimation initiale du
point e (2-5/11-14 au lieu de 1-5/10-14) : les trous 1 et 10, qui ouvrent
chaque nine, se trouvent être alignés et en recouvrement projeté avec
l'ensemble de leur bande (pas seulement leur voisin immédiat), donc la série
maximale les inclut aussi — comportement correct au vu de la définition, pas
une anomalie.

**Historique (abandonné) — cliques maximales (2026-10-06, première passe)** :
`_connected_components` (union-find) avait été remplacé par `_maximal_cliques`
(Bron–Kerbosch avec pivot) sur le graphe `_side_by_side` inchangé. Décompte
obtenu sur le synthétique : 4 → 0 `parallel_stack`. Diagnostic : chaque nine
forme une chaîne de voisinages deux à deux (1-2, 2-3, 3-4, 4-5) mais aucun
triplet n'y est une clique (le trou 1 ne touche pas le trou 3, ni le 4, ni le
5) — la définition par clique exige un contact mutuel entre TOUS les trous de
la pile, incompatible avec une vraie pile de bandes parallèles où le contact
n'existe qu'entre voisins immédiats. D'où la redéfinition ci-dessus.

### Étape 3 — squelette global grossier (contour d'un arbre aléatoire)

- [x] Construire l'arbre enraciné au clubhouse à deux sous-arbres (un par
  nine), croissance alternée et seedée, sans retour arrière.
- [x] Appliquer le halo interdisant tout contact entre arêtes/cellules non
  voisines dans l'arbre, y compris entre les deux sous-arbres racines.
- [x] Appliquer le budget de longueur cible par sous-arbre et le nombre
  maximal de feuilles par sous-arbre (une feuille = une épingle).
- [x] Imposer une longueur minimale de branche (≥ ~2 trous portés par côté) :
  une branche trop courte force le contour à faire un aller-retour sur
  place, ce qui produit exactement les séries de trous consécutifs côte à
  côte (zigzags) que l'objectif « voyage » pénalise.
- [x] Rejeter complètement et de façon déterministe tout arbre qui ne peut
  atteindre son budget, sans retour arrière interne.
- [x] Épaissir l'arbre puis extraire son contour (courbe simple par
  construction).
- [x] Couper le contour à ses deux passages au clubhouse pour obtenir les
  deux arcs clubhouse→clubhouse (front et back).
- [ ] Appliquer la DP de découpage sur chaque arc, inspirée de `_cut_nine()`
  de `golfgen/loop_router.py`. Abandonné avec l'approche (Porte 3 refusée, voir plus bas) :
  le code existe dans `skeleton.py` (non branché depuis r2, à adapter aux
  arcs `front_contour`/`back_contour` de r3) mais n'est pas appelé par
  `build_skeleton`.
- [x] Rendre le squelette (arbre et contour, sans découpage) dans un SVG
  dédié.

**Résultat du 2026-10-07** : implémentation dans `experiments/elastic_routing/skeleton.py`,
runner `run_step3_skeleton.py` → `output/step3_skeleton/seed_<n>/` (`skeleton.svg`,
`report.json`, pas de `layout.json`/`layout.svg`/`REPORT.md` : pas de DP de
découpage ni de `CourseLayout` à ce stade, voir plus bas) pour les seeds 1 à
6, plus `tests/test_elastic_routing_skeleton.py` (suite ciblée
`elastic_routing` → 772/772). Trois versions successives, conservées côte à
côte pour comparaison dans `output/step3_skeleton/compare/` :

- **r1** (`r1_boustrophedon/`) : premier essai, méandre en boustrophédon
  (rangées perpendiculaires espacées d'au moins le halo), clubhouse fixé au
  centre de la carte. **Refusé à la Porte 3** : chaque nine devient un
  serpentin parallèle en S, les deux nines se font face autour du clubhouse
  central, la moitié de la carte reste vide.
- **r2** (`r2_offset12_1feuille/`) : remplace le boustrophédon par une
  marche aléatoire biaisée sur un réseau grossier (pas = halo arrondi au
  prochain entier pair, 8 voisins orthogonaux + diagonaux), clubhouse tiré
  par la seed. **Accepté sur le mécanisme, refusé sur le résultat** : une
  seule feuille par sous-arbre (jamais 2 ou 3), chaque nine reste un unique
  « doigt » replié, carte sous-occupée.
- **r3** (`r3_offset12/`, `r3_offset20/`) : version actuelle. 2 ou 3
  feuilles imposées par sous-arbre (jamais 1), budget de longueur par
  sous-arbre imposé (rejet si hors fenêtre), halo vérifié par PAIRE
  d'arêtes sans nœud commun sur l'arbre entier (pas de fenêtre « localement
  reliée » distincte). Contour = décalage de polyligne standard (jointure
  ronde de rayon `offset` côté convexe, intersection des deux segments
  décalés vérifiée dans les deux segments côté concave, sinon
  `ContourOffsetError` explicite) appliqué à un tour d'Euler UNIQUE couvrant
  les DEUX sous-arbres à la fois (`_combined_tour`), puis coupé PAR INDICE
  (`_split_combined_contour`) à ses deux passages au clubhouse pour produire
  les arcs `front_contour`/`back_contour` — pas deux contours indépendants
  décalés puis vérifiés séparément. Trois bugs corrigés en cours de route
  sur cette version, chacun invisible à l'inspection ou aux tests de la
  passe précédente : un cap mordu aux feuilles en bout d'arête diagonale ;
  un croisement front/back systématique près du clubhouse (deux contours
  décalés indépendamment, chacun refermé par son propre cap au clubhouse,
  les deux caps plantés à ~180° l'un de l'autre bulgant chacun vers le
  territoire de l'autre) ; des extrémités d'arc pendantes loin du clubhouse
  (le contour combiné bien formé, mais mal redécoupé en front/back — un
  groupe de points de coupure entier assigné à un seul arc au lieu des
  deux). `MAX_TREE_ATTEMPTS` porté de la cible « ≤ 50 » du plan à **1500**
  (pire cas mesuré empiriquement, pas une marge arbitraire). Longueur
  minimale d'une branche menant à une feuille ≈ 0,3 × (budget bas de la
  fenêtre de longueur − pas de grille), facteur 0,3 retenu après balayage
  empirique (0,2 à 0,45) sur les seeds 1–5. **Offset du contour** : 12 et 20
  blocs comparés côte à côte dans `compare/r3_offset12/` et
  `compare/r3_offset20/` — question ouverte, soumise à l'utilisateur.
- **r4** (`r4_regions_w2/`, `r4_regions_w3/`, `r4_regions_w4/`) : module
  `regions.py`, runner `run_step3_regions.py`, tests
  `tests/test_elastic_routing_regions.py` (seeds 1–30 × w_min 2/3/4).
  Objectif : supprimer l'« effet jumeau » de r3, où chaque branche devenait
  un aller-retour de deux traits parallèles. Ici chaque nine suit le BORD
  d'une RÉGION (tache de cellules) au lieu du contour d'un arbre. Grille de
  cellules de c blocs, clubhouse sur un coin tiré par la seed. Les deux
  régions grandissent en alternance, un bloc w_min×w_min entier par ajout,
  appuyé sur la région par un côté entier. Chaque région reste sans trou ni
  pincement, avec un couloir d'au moins une cellule entre front et back,
  sauf au clubhouse. Parcours = bord décalé vers l'intérieur de d = 9
  (`offset_closed_polyline`, extrait de `skeleton.py`), ouvert au coin
  clubhouse. La croissance s'arrête dès que le parcours entre dans la
  fenêtre 1220–2165. Valeur de c : 21 pour w_min 2 et 3 ; 19 pour w_min 4,
  car à c = 21 aucune seed n'aboutit (0/30 en 200 tirages). Tirages au pire
  sur les seeds 1–30 : 2 / 13 / 51, en moins de 0,1 s par seed. Ce qu'on
  voit sur les planches : aucun chevauchement, chaque nine part du
  clubhouse et y revient. Avec w3, l'aller et le retour ont des formes
  différentes ; c'est la meilleure variante. Avec w2, les lobes fins
  redonnent des jumeaux et les encoches donnent des peignes. Avec w4, le
  retour passe trop loin de l'aller : le parcours fait le tour d'un terrain
  vide. Dans tous les cas, l'esthétique reste celle d'une grille (angles
  droits arrondis, bord de carte longé) et les longueurs restent au bas de
  la fenêtre.

**Livrable** : un squelette 18 trous complet produit rapidement, même s'il ne
respecte pas encore les largeurs finales.

**Porte 3** : critères prévus — rejeter les deux anneaux, la symétrie
excessive, les liaisons incohérentes et toute pile de 4 trous ou plus avant
de poursuivre.

**Porte 3 — refusée, approche abandonnée (2026-10-07).** Que la forme soit
un arbre (r1–r3) ou une région (r4), un parcours qui « fait le tour d'une
forme » produit structurellement trois défauts :

- (a) un territoire par nine, donc deux demi-cartes ;
- (b) un rapport aller/retour fixé par l'épaisseur de la forme : des jumeaux
  si la forme est mince, un circuit autour d'un terrain vide si elle est
  large, des encoches en peigne entre les deux ;
- (c) un effet de grille.

Le code reste comme archive et comme source de primitives réutilisables :
`skeleton.py`, `regions.py`, le décalage de polyligne robuste
(`offset_closed_polyline`) et les tests d'invariants. Les planches de
`output/step3_skeleton/compare/` restent aussi.

### Nouvelle direction (2026-10-07)

**Constat de l'utilisateur** : l'aléatoire seul ne « fait pas vrai ». Un
vrai parcours est intentionnel : un architecte l'a conçu selon un patron.

**Principe retenu** : de l'aléatoire contraint par un patron d'architecte.

**Premier patron : Muirfield.** Deux boucles concentriques parcourues en sens
opposés : le front sur la boucle extérieure, le back sur la boucle
intérieure. Les deux boucles passent par le clubhouse.

**Inspiration** : le dépôt `addisonolmsted/procedural-golf-course-generator`
(Rust). Il n'a pas de licence : on en reprend seulement des idées, aucun
code.

- Sites candidats tirés du terrain, puis amincis.
- Cible de position douce : pour chaque trou, une fraction de la longueur
  cumulée le long d'une boucle.
- Construction trou par trou, avec un retour arrière borné et des relances
  bon marché (d'abord le plan de boucle, puis le clubhouse).
- Recuit qui ne garde que des états valides.

**Risque connu** : les derniers trous peuvent se retrouver bloqués (cf.
`bean_paving`). Parades : les relances, et une réparation élastique
(le score incrémental de l'étape 4 est déjà prêt).

**Piste future** : calibrer le recuit sur des statistiques de vrais
parcours tirées d'OpenStreetMap (`golf=hole`).

Le plan détaillé du round Muirfield sera rédigé et validé avant tout code.

### Étape M — routage Muirfield

#### Décisions validées par l'utilisateur (2026-10-07)

1. **Longueurs de trous réalistes** (1 bloc = 3 m). Les plages d'origine
   (décision 1 de « Décisions validées avant implémentation ») étaient
   30–60 % trop longues. Nouveau défaut de `PAR_SPECS` : par 3 45–70, par 4
   100–145, par 5 145–185 blocs ; largeurs inchangées (10–15, 11–17, 12–18).
   Solution retenue pour la compatibilité : les anciennes plages sont figées
   dans `LEGACY_PAR_SPECS` et épinglées explicitement par les seuls modules
   historiques de l'étape 3 (`skeleton.py`, `regions.py`, abandonnés) pour
   que leurs fenêtres de longueur et les résultats consignés plus haut
   restent reproductibles ; tout le reste (modèle, oracle `validate`,
   surrogate `incremental`, layout synthétique) suit le nouveau défaut. Deux
   tests construisaient à la main un par 3 de 80–90 blocs : ils ont été
   ramenés à 60.
2. **Patron Muirfield, clubhouse sur un BORD de carte** (bord et position le
   long du bord tirés par la seed) : front = boucle extérieure dans un sens,
   back = boucle intérieure en sens inverse, tous deux partant du clubhouse
   et y revenant. Le front part le long du bord d'un côté (trou 1) et revient
   le long du bord de l'autre côté (trou 9) ; le back sort du clubhouse vers
   l'intérieur ENTRE les trous 1 et 9 (secteur angulaire réservé au
   clubhouse) et y revient.
3. **Anneaux en carré arrondi** (superellipse, p ≈ 4–6) qui suivent la forme
   de la carte : cible extérieure pour le front, intérieure pour le back.
4. **Longueur d'un nine = conséquence**, pas une règle dure. La répartition
   des pars entre les deux nines est LIBRE (quota global 4/10/4, par 3 et
   par 5 par nine dans [1, 3]) et tirée par la seed comme le reste — aucun
   nine n'est imposé comme le plus court (correction de l'utilisateur sur une
   première formulation « combinaison la plus courte au back »). Recuit
   reporté au round R3. Relief mis en cache sur disque, hors git
   (`output/.cache/`, ajouté à `.gitignore`).

#### Découpage

- **R1 — visuel glouton** : sites, géométrie du patron, construction trou
  par trou sans retour arrière, rendu numéroté. Violations tolérées et
  affichées ; ce n'est pas une porte de validité.
- **R2 — zéro violation** : contrôles en ligne (collisions, écarts, liaisons
  bloquées) pendant la construction, retour arrière borné avec une borne de
  faisabilité de retour au clubhouse (le trou k doit laisser au trou 9/18
  une distance atteignable), relances bon marché (plan d'anneau, puis
  clubhouse).
- **R2b — anti-hélice** : forme du patron (reportée pour isoler l'effet de
  la carte rectangulaire testé en R2).
- **R3 — recuit** avec composantes souples (cibles, qualité des sites,
  variété de directions), en ne gardant que des états valides.

#### R1 — mécanisme (2026-10-07)

- `sites.py` : grille fine (pas 3, bruit seedé ±1.2), marge de bord 12, eau
  exclue (`WATER_LEVEL` = 60, ~1 % de la carte) ; score green = 0.6 ×
  planéité + 0.4 × proéminence modérée (gaussienne centrée +1 bloc), score
  tee = planéité ; si le relief est plat (écart p90–p10 de pente < 0.02),
  score aléatoire seedé ; amincissement glouton à 18 blocs (greens) et 12
  (tees). ~310 greens et ~665 tees par seed.
- `muirfield.py` : clubhouse à 6 blocs de son bord, à 30–70 % de sa
  longueur ; anneaux superellipse p = 5 centrés sur la carte, demi-côté 166
  (extérieur) et 88 (intérieur) ; secteur réservé ±9° autour de l'angle du
  clubhouse (aucun tee/green du front dedans) ; le back sort vers l'anneau
  intérieur à −18° côté trou 9 et revient à +18° côté trou 1. Pars tirés
  par la seed (répartition et ordre). Cible douce du green k = point du
  chemin clubhouse → anneau → clubhouse à la fraction de longueur nominale
  cumulée (milieu de plage + liaison 25). Glouton : tees à 12–45 du point
  courant (18–45 depuis le clubhouse), greens à longueur de par (droit, ou
  1 dogleg à 60 % de la corde, ≤ 55°, longueur visée `length_min` + 2),
  score = écart à la cible / 25 − 0.5 × (qualité tee + green) − 0.5 ×
  min(virage, 90°)/90° ; dernier green d'un nine pris parmi les sites à
  18–45 du clubhouse s'il en existe un atteignable. Largeur = `width_min`.
- `render_readable.py` : bandes de fairway par par, rough, flèche de sens,
  tee (carré), green (disque + drapeau), numéro dans un cercle derrière le
  tee, liaisons pointillées, anneaux en pointillés légers, relief en fond
  (cases de 8 blocs, eau en bleu), violations en rose.

#### R1 — résultat (2026-10-07)

`python -m experiments.elastic_routing.run_muirfield` →
`output/muirfield/r1/seed_<n>.svg|png`, `planche.png`, `report.json`.

| seed | bord | violations | familles | front par / blocs | back par / blocs | doglegs | ms |
|---|---|---|---|---|---|---|---|
| 1 | W | 14 | axis_crossing 2, fairway_gap 9, link_blocked 3 | 37 / 1363 | 35 / 1224 | 8 | 238 |
| 2 | S | 17 | axis_crossing 4, fairway_gap 9, link_blocked 4 | 38 / 1448 | 34 / 1224 | 5 | 220 |
| 3 | S | 16 | axis_crossing 3, fairway_gap 8, link_blocked 5 | 36 / 1431 | 36 / 1275 | 7 | 216 |
| 4 | W | 12 | axis_crossing 2, fairway_gap 7, link_blocked 2, link_distance 1 | 34 / 1299 | 38 / 1368 | 7 | 218 |
| 5 | E | 14 | axis_crossing 4, fairway_gap 7, link_blocked 2, link_distance 1 | 36 / 1438 | 36 / 1267 | 5 | 217 |
| 6 | W | 21 | axis_crossing 4, fairway_gap 11, link_blocked 6 | 37 / 1422 | 35 / 1268 | 5 | 213 |

Temps : ~0.22 s par seed relief en cache (sites 0.13 s, glouton 0.08 s,
oracle 0.01 s) ; le relief seul coûte 7 s par seed au premier passage.
Toutes les longueurs de trous sont dans les nouvelles `PAR_SPECS` ; quotas
de pars et bornes par nine respectés ; tees 1 et 10 à 18–45 du clubhouse.

Lecture de la planche : le patron se lit. Le front fait le tour du bord, le
back une boucle intérieure en sens inverse, numéros et sens de jeu
lisibles. Défauts visibles :
- **Nœud au clubhouse** : les trous 1, 9, 10 et 18 convergent dans le même
  petit secteur et s'y croisent ou se frôlent (seeds 1, 2, 6 surtout) — c'est
  la majorité des `axis_crossing`.
- **Retour au clubhouse** : sans retour arrière, le trou 9 ne trouve aucun
  green à liaison du clubhouse pour les seeds 4 (liaison 50) et 5 (67)
  → `link_distance` ; test `xfail` strict jusqu'à R2.
- **Back qui déborde** sur la bande du front (anneau intérieur trop petit
  pour ~1250 blocs de nine : les trous zigzaguent et touchent le front) →
  la plupart des `fairway_gap` et `link_blocked`.
- Le trou 1 n'a souvent qu'un ou deux tees candidats (secteur réservé +
  marge de bord) : choix contraint, pas de variété.
- Front plus long que le back dans 5 seeds sur 6 (+139 à +224 blocs ;
  seed 4 : −69), l'anneau extérieur étant plus long que le chemin du back.

Leçons pour R2 : contrôles d'écart et de croisement en ligne, borne de
retour au clubhouse dès le trou 6–7, demi-côté de l'anneau intérieur à
ajuster au nine attendu (ou p plus faible), et un couloir explicite pour
10/18 qui interdit au front d'y entrer par l'axe, pas seulement par les
sites.

#### Tableau des règles (étape M)

| règle | nature | où |
|---|---|---|
| longueur par par (`PAR_SPECS` : 45–70 / 100–145 / 145–185) | dure | oracle `length`, contrôle en ligne |
| largeur par par (10–15 / 11–17 / 12–18) | dure | oracle `width`, contrôle en ligne |
| quota global 4 par 3 / 10 par 4 / 4 par 5 | dure | `CourseLayout`, tirage |
| par 3 et par 5 par nine dans [1, 3], répartition entre nines tirée par la seed | dure | oracle `par3/5_per_nine`, tirage |
| **par d'un nine dans [34, 38]** (total 72, pas forcé à 36/36 — décision du 2026-10-08) | dure | `muirfield.nine_par_ok`, `draw_par_counts` |
| **jamais 3 par 5 consécutifs ni 3 par 3 consécutifs dans un nine** | dure | `muirfield.par_sequence_ok`, tirage |
| **éviter 2 par 5 consécutifs ; éviter qu'un nine commence par un par 3** | souple (tirage) | `muirfield.par_sequence_penalty` |
| liaisons 12–45 (18–45 depuis/vers le clubhouse) | dure | oracle `link_distance`, contrôle en ligne |
| liaison non bloquée par un fairway | dure | oracle `link_blocked`, contrôle en ligne |
| croisement d'axes, écart fairway ≥ 5 (tous trous, deux nines) | dure | oracle, contrôle en ligne |
| cœur ≥ 1 du bord, ≥ 10 du clubhouse | dure | oracle `bounds`, `clubhouse_clear` |
| pas de série de plus de 3 trous consécutifs en pile parallèle | dure | oracle `parallel_stack`, contrôle en ligne |
| 1/9 le long du bord de part et d'autre, 10/18 entre eux (cônes disjoints) | dure (construction) | `muirfield.anchor_bounds` |

La règle de séquence des pars n'est pas (encore) une famille de l'oracle :
elle est garantie par le tirage (`draw_pars` / `order_nine` : permutations
seedées, la première qui respecte la règle dure avec pénalité souple nulle,
sinon la moins pénalisée).

#### R2 — mécanisme (2026-10-08)

Une seule famille : la validité, plus deux paramètres simples (règle des
pars, carte rectangulaire). L'anti-hélice (forme du patron) est reportée à
R2b pour isoler l'effet de la carte rectangulaire.

- `partial_checks.py` : `PartialLayout.check(trou, liaisons)` rejette un
  candidat sur la première famille violée — longueur/largeur, liaison hors
  plage, bords, clubhouse dégagé, croisement d'axes et écart fairway avec
  TOUS les trous posés (des deux nines), liaison bloquée dans les deux sens,
  pile parallèle (toute fenêtre de 4 trous consécutifs posés contenant le
  candidat). Mêmes prédicats et epsilons que l'oracle (fonctions de
  `geometry.py`), pré-filtre par boîtes englobantes. Pré-filtres vectorisés
  (`Obstacles`) : conditions NÉCESSAIRES (un cœur contient la somme de
  Minkowski axe ⊕ disque de demi-largeur), testées par propriété.
- Secteur du clubhouse : repère local (normale entrante, tangente orientée
  vers le trou 1), cônes disjoints φ ≥ 58° (trou 1), φ ≤ −58° (trou 9),
  [−32°, −1°] (trou 10), [1°, 32°] (trou 18) ; tout l'axe d'un trou
  d'ancrage est dans son cône, donc 1/9/10/18 et leurs liaisons au
  clubhouse ne peuvent pas se croiser. Les sites du front sont exclus du
  couloir du back (|φ| < 45° jusqu'à l'anneau intérieur + 30).
- Recherche : DFS par nine dans l'ordre premier trou → DERNIER trou ancré
  (green à 18–45 du clubhouse, tee visé vers la cible du green 8) → trous 2
  à 8, le trou 8 devant finir à liaison du tee 9. Borne de faisabilité de
  retour pour les trous 6–7 (15–16) : green à moins de Σ(45 + longueur max)
  des trous restants + 45 du tee ancré. k = 3 enfants valides par niveau,
  au plus 150 candidats contrôlés par niveau, budgets 1500 contrôles et 300
  nœuds par nine et par tentative. Relances : 3 angles de départ × 3
  permutations de pars × 3 positions de clubhouse (27 tentatives au plus),
  aucune règle assouplie, `MuirfieldRoutingError` sinon.
- Ancrer le dernier trou AVANT les trous 2–8 a été décisif : sans ancrage
  (premier essai, DFS chronologique 1→9, greens espacés de 18, budget 3000
  contrôles), 7 cas sur 18 (400², 300×400, 350×400) échouaient après les 27
  tentatives, presque toujours dans le back, pour jusqu'à 61 s par seed ;
  avec ancrage (même espacement), 3 échecs avec des cônes 48°/[4°, 40°],
  puis 5 avec 58°/[1°, 32°] — cônes écartés parce qu'à 48°/40° le green 18
  et le tee 1 (tous deux à 18–45 du clubhouse) étaient trop proches pour
  l'écart fairway ; échecs dus au manque de sites dans les cônes (point
  suivant).
- **Écart au plan R1 (paramètre)** : espacement des greens 18 → 12. À 18,
  le cône d'ancrage (liaison 18–45, ~31° d'ouverture) ne contient que 0 à 2
  sites de green : 400²/s6, 300×400/s1, s3, s6 et 350×400/s1 échouaient sur
  toutes les relances (0 ou 1 green atteignable au trou 9 ou 18). À 12 :
  18/18 (400² compris, non publié en planche).
- Carte rectangulaire de bout en bout : relief `load_terrain(seed, w, h)`
  (cache par format), sites, anneaux superellipse à demi-axes (w/2 − 34,
  h/2 − 34) et intérieur −78, `ValidationRules(width, height)`, rendu.

#### R2 — résultat (2026-10-08)

`python -m experiments.elastic_routing.run_muirfield` →
`output/muirfield/r2_300x400/` et `output/muirfield/r2_350x400/` (svg/png
par seed, `planche.png`, `report.json`) ; `output/muirfield/r1/` conservé.

| format | seed | bord | violations | relances | front par / blocs | back par / blocs | doglegs | ms |
|---|---|---|---|---|---|---|---|---|
| 300x400 | 1 | S | 0 | 23 | 37 / 1337 | 35 / 1210 | 11 | 2035 |
| 300x400 | 2 | S | 0 | 3 | 38 / 1382 | 34 / 1159 | 10 | 3643 |
| 300x400 | 3 | S | 0 | 0 | 36 / 1248 | 36 / 1265 | 12 | 203 |
| 300x400 | 4 | W | 0 | 0 | 34 / 1178 | 38 / 1356 | 11 | 221 |
| 300x400 | 5 | E | 0 | 3 | 36 / 1226 | 36 / 1248 | 9 | 2478 |
| 300x400 | 6 | E | 0 | 12 | 37 / 1286 | 35 / 1220 | 13 | 8632 |
| 350x400 | 1 | S | 0 | 21 | 37 / 1334 | 35 / 1249 | 9 | 635 |
| 350x400 | 2 | S | 0 | 0 | 38 / 1275 | 34 / 1162 | 14 | 221 |
| 350x400 | 3 | S | 0 | 0 | 36 / 1333 | 36 / 1293 | 9 | 206 |
| 350x400 | 4 | W | 0 | 0 | 34 / 1272 | 38 / 1359 | 10 | 303 |
| 350x400 | 5 | W | 0 | 9 | 36 / 1259 | 36 / 1280 | 11 | 495 |
| 350x400 | 6 | W | 0 | 0 | 37 / 1332 | 35 / 1170 | 7 | 203 |

Zéro violation `validate()` sur les 12 cas. Objectif < 2 s/seed hors
relief **non atteint** pour 4 cas sur 12, tous en 300×400 (2.0, 2.5, 3.6 et
8.6 s) : chaque tentative dont le back échoue consomme son budget complet
(~0.3–1 s) ; budgets non relevés. Les 350×400 restent sous 0.7 s.

Lecture des planches :
- Le nœud au clubhouse a disparu : 1 et 9 longent le bord de part et
  d'autre, 10 et 18 plongent entre eux, aucun croisement.
- La forme reste une hélice : le back s'enroule vers le centre, et le
  rectangle ne la casse pas (l'anneau intérieur 300×400 fait 76 blocs de
  large, le back y zigzague) — c'est l'objet de R2b.
- Ce qui reste moche : grappes de trous quasi parallèles à l'écart minimal
  de 5 au centre et près du clubhouse (10/11/18), quelques longs par 5
  rectilignes le long du bord, liaisons parfois longues en diagonale.

#### Revue R1+R2 (2026-10-08) — corrections et points ouverts

- `build_muirfield` ne renvoie jamais un layout refusé par `validate()` : une
  tentative dont le layout a une violation est notée `echec_validate` et l'on
  passe au plan suivant, puis `MuirfieldRoutingError` (filet de sécurité ; il
  ne s'est jamais déclenché sur les 18 cas).
- Plages de liaison dérivées des `ValidationRules` (`link_bounds`) : entre
  trous `[link_min, link_max]`, clubhouse `[max(link_min, rayon dégagé +
  demi-fairway max + 2), link_max]` (18–45 par défaut).
- Cache du relief : clé = seed + taille + empreinte (version + hash de
  `TerrainConfig`).
- Artefacts : seuls `planche.png` et `report.json` sont versionnés pour
  r1/r2 ; les png/svg par seed (~180 Ko chacun) sont ignorés et régénérés
  par `run_muirfield` (ils restent dans l'historique des commits R1/R2).

**Questions ouvertes — FERMÉES le 2026-10-08 par l'utilisateur :**

1. **Par par nine** : pas forcé à 36/36, mais règle dure 34 ≤ par d'un nine
   ≤ 38 (total 72). Avec par 3 et par 5 par nine dans [1, 3], le par d'un
   nine vaut 36 + (par 5 − par 3), donc déjà dans [34, 38] ; la règle est
   désormais explicite (`nine_par_ok`, vérifiée au tirage, testée).
2. **Espacement des greens à 12** : validé.

Également décidé : les grappes de trous parallèles (ex. 16-17-18, seed 3)
restent telles quelles ; patron Muirfield inchangé.

#### Round A (2026-10-08) — formats paysage et robustesse

Aucun mécanisme ni budget modifié (1500 contrôles / 300 nœuds par nine,
27 tentatives au plus). Runner : `python -m
experiments.elastic_routing.run_muirfield --round ra` (paysage) et
`--round ra-30` (robustesse). Versionnés : `planche.png` + `report.json`.

**Paysage 400×300 et 400×350, seeds 1–6** (`output/muirfield/ra_400x300/`,
`output/muirfield/ra_400x350/`) : 12/12 réussis, 0 violation.

| format | relances (s1…s6) | médiane | p90 | max | > 2 s |
|---|---|---|---|---|---|
| 400×300 | 3, 24, 2, 2, 6, 18 | 0.71 s | 4.7 s | 7.6 s (s2) | s2 |
| 400×350 | 0, 3, 9, 0, 6, 9 | 0.27 s | 2.7 s | 4.8 s (s2) | s2 |

Lecture : même lecture que les portraits — front le long du bord, 1/9 et
10/18 sans croisement au clubhouse, back enroulé au centre (hélice). En
paysage, le back se range plutôt en faisceaux de trous parallèles
nord-sud ou est-ouest dans la bande centrale (400×300 s3 : 11/15/17/18
côte à côte). Le rendu laisse une bande vide sous la carte (cadre carré
800 px), purement cosmétique.

**Robustesse 300×400, seeds 1–30** (`output/muirfield/ra_300x400_30seeds/`,
planche 6×5 réduite des 25 réussites) : **25/30 réussis**, 0 violation sur
les réussites ; 322 relances au total ; temps hors relief médiane 2.0 s,
p90 8.5 s, max 20.2 s (s8, échec) ; 15 seeds au-dessus de 2 s.

Échecs explicites (`MuirfieldRoutingError`, 27 tentatives chacun) :

- **seeds 19 et 28 — front, clubhouse** : les trois positions de clubhouse
  tirées sont sur un bord COURT (N/S, 300 blocs) et le trou 1 est un par 5
  dans toutes les permutations. Le cône d'ancrage (φ ≥ 58°, axe à moins de
  32° du bord) n'offre pas 145–185 blocs entre le tee et le mur latéral :
  aucun candidat pour le trou 1 ou le trou 9 (échec en < 0.2 s).
- **seeds 8, 25, 27 — back** : budget de 1500 contrôles épuisé au trou
  17/18 dans la plupart des tentatives (le back n'arrive pas à rejoindre le
  tee 18 ancré dans l'anneau intérieur de 76 blocs de large), ou aucun
  candidat pour le trou 18 dans son cône (tentatives à ~13 nœuds). Seed 25
  a aussi 3 échecs du front.

Pistes (non appliquées, à valider) : interdire un par 5 aux trous 1/9 quand
le clubhouse est sur un bord court ou placer le clubhouse sur un bord long
en 300×400 ; anneau intérieur plus large en portrait étroit (R2b).

#### Round A2 (2026-10-08) — robustesse 300×400 : 30/30

Condition de l'utilisateur pour la suite (Muirfield inversé) : les 30 seeds
passent. Même famille (validité/faisabilité), AUCUNE règle assouplie, AUCUN
budget relevé (1500 contrôles / 300 nœuds par nine, k = 3, 150 candidats
par niveau, 27 tentatives), patron inchangé.

Causes trouvées et corrections :

1. **Front, seeds 19 et 28 — capacité des cônes.** Clubhouse sur un bord
   court (N/S, 300) et trou 1 par 5 dans toutes les permutations : aucun
   par 5 ne tient dans le cône φ ≥ 58° le long d'un bord court. Correction :
   avant toute construction, `anchor_fits` évalue pour chaque position de
   clubhouse les pars qui tiennent dans les cônes de 1, 9, 10, 18 (sites,
   cône, liaison au clubhouse, pré-filtres ; sans autre trou posé :
   condition nécessaire) ; la permutation des pars est tirée sous cette
   contrainte (`order_nine(first=, last=)`, identique au round A quand rien
   n'est exclu) ; un plan sans permutation admissible n'est pas tenté
   (`infaisable_ancrage`). Un bord court reste permis : 19 et 28 passent
   avec leur clubhouse de base, pars réordonnées.
2. **Back, seeds 8, 25, 27 — espace consommé avant les derniers trous.**
   Diagnostic (états les plus profonds rendus) : (a) les trous 11–16 se
   placent vers leurs cibles et occupent l'espace entre le green 16 et le
   tee 18 ancré : le trou 17 n'a plus aucun candidat (67 à 153 nœuds sur
   ~300 perdus en niveaux 17 vides) ou seulement des doglegs en collision ;
   l'ancienne borne de retour (distance en ligne droite) ne voyait rien ;
   (b) pour les clubhouses W/E de la seed 27, le trou 10 prenait l'emprise du
   18 (cônes adjacents) après que le front a occupé les abords du
   clubhouse. Corrections, toutes des conditions nécessaires :
   - ordre de construction : les quatre ancrages 1, 9, 10, 18 d'abord, avec
     anticipation (un ancrage qui ne laisse aucun candidat à un ancrage
     restant est écarté), puis 2–8, puis 11–17 en phase séparée (un échec
     du back ne fait pas remonter dans le front : la relance s'en charge) ;
   - borne de retour stricte pour l'antépénultième trou (7 / 16) : son green
     doit permettre un trou-pont (8 / 17) jusqu'au tee ancré (sites libres,
     longueur de par, liaisons non bloquées), revérifiée après sa pose ;
   - doglegs pré-filtrés comme les tirs droits (les deux coudes construits
     et testés contre axes et liaisons) : moins de contrôles gaspillés.
3. Nits de revue : `ValueError` inatteignable de `draw_par_counts` retirée
   (règle 34–38 garantie par construction, testée exhaustivement) ; test
   `width` au-dessus du max + cas valide ; statut `echec_ancrages` distinct.

**Mesure des temps** : chronomètre unique autour de `build_muirfield`
(sites + recherche + oracle, relief en cache exclu), identique pour succès
et échecs (`run_muirfield.py`) ; valeurs propres à la machine de mesure
(poste de dev), à comparer entre elles, pas en absolu.

Résultats (`--round ra2-30` → `output/muirfield/ra2_300x400_30seeds/`,
`--round ra2-check` → `output/muirfield/ra2_check_<w>x<h>/report.json`) :

| cas | réussis | violations | relances | médiane | p90 | max |
|---|---|---|---|---|---|---|
| 300×400 s1–30, round A | 25/30 | 0 | 322 | 2.0 s | 8.5 s | 20.2 s |
| **300×400 s1–30, A2** | **30/30** | 0 | 37 | 0.37 s | 3.5 s | 4.1 s |
| 350×400 s1–6, A2 | 6/6 | 0 | 18 | 0.38 s | 2.0 s | 2.2 s |
| 400×300 s1–6, A2 | 6/6 | 0 | 3 | 1.0 s | 2.9 s | 3.7 s |
| 400×350 s1–6, A2 | 6/6 | 0 | 0 | 0.35 s | 0.40 s | 0.41 s |

300×400 : 25 seeds sans relance ; relances restantes = 24 `echec_ancrages`
(seeds 1 et 29 : ancrages incompatibles entre eux à certaines positions de
clubhouse — la capacité est évaluée cône par cône, pas conjointement), 9
`infaisable_ancrage` (seed 30, gratuits) et 4 `echec_back`. 300×400 s1–6
reste à 0 violation (tests). Les layouts changent par rapport à R2/RA
(nouvel ordre de construction) ; les planches R2/RA versionnées restent
celles de leur round. Forme : toujours l'hélice et des faisceaux de trous
parallèles (hors périmètre A2).

#### Round B (2026-10-08) — patron explicite et Muirfield inversé

**Décision de l'utilisateur : le patron est un paramètre explicite**, au
même titre que la seed (futur site Minecraft : l'utilisateur choisit seed +
patron), PAS une variable tirée par la seed. Valeurs :

- `muirfield` : front = grand tour extérieur, back = boucle intérieure ;
- `muirfield_inverse` : front = boucle intérieure, back = grand tour
  extérieur (sens opposés, clubhouse sur un bord, mêmes cônes 1/9/10/18 mais
  rôles échangés : 10 et 18 longent le bord, 1 et 9 plongent entre eux) ;
- `random` : patron tiré de façon déterministe depuis la seed
  (`resolve_pattern`, flux `[seed, 23]` indépendant du routage) ;
  `build_course(seed, "random")` est identique à `build_course(seed, <patron
  résolu>)` (testé).

API : `build_course(seed, pattern, heightmap, width, height, rules)`
(`build_muirfield` reste un alias, patron `muirfield` par défaut) ; runner
`--pattern {muirfield, muirfield_inverse, random}` (+ `--round custom
--size LxH --seeds 1-6`). Pas de config JSON ajoutée : le spike n'en a pas
et le pipeline `golfgen/` n'utilise pas encore ce routage.

Mécanisme : aucune copie de code, les rôles extérieur/intérieur sont des
paramètres (`outer_start(pattern)`) : chemins cibles (`nine_paths`), repère
du clubhouse (côté = départ du nine extérieur), cônes (`anchor_bounds(order,
pattern)`), couloir réservé au nine intérieur, ordre de recherche (phase A :
ancrages puis milieu du nine EXTÉRIEUR ; phase B : milieu du nine
intérieur). Le patron `muirfield` donne exactement les mêmes parcours qu'en
A2 (37 relances, mêmes temps sur 300×400).

Nits de revue A2 traités : repère du clubhouse invariant par angle de départ
(note + test) ; `order_nine` contraint : repli par énumération EXHAUSTIVE des
permutations distinctes si les 200 tirages échouent (les 9
`infaisable_ancrage` de la seed 30 sont donc réellement infaisables) ;
statut par phase atteinte (`echec_ancrages` tant que les quatre ancrages
n'ont jamais été posés ensemble, puis `echec_<nine extérieur>`, puis
`echec_<nine intérieur>`) ; tests de `_bridge_reachable` et du pré-filtre des
doglegs (coude libre conservé et valide, coude bloqué écarté).

Résultats (`--round rb`, `rb-30`, `rb-check` →
`output/muirfield/rb_inverse_300x400/` [planche + report],
`rb_<patron>_300x400_30seeds/`, `rb_check_<patron>_<w>x<h>/`). Relances
séparées en **tentées** (une recherche lancée) et **gratuites** (plan écarté
par la capacité des cônes, aucune recherche) ; temps machine de dev,
chronomètre homogène succès/échec :

| patron | cas | réussis | violations | relances tentées | gratuites | médiane | p90 | max |
|---|---|---|---|---|---|---|---|---|
| muirfield | 300×400 s1–30 | 30/30 | 0 | 28 | 9 | 0.37 s | 3.5 s | 4.2 s |
| muirfield_inverse | 300×400 s1–30 | **30/30** | 0 | 23 | 9 | 0.38 s | 3.5 s | 17.7 s |
| muirfield | 350×400 s1–6 | 6/6 | 0 | 18 | 0 | 0.38 s | 2.0 s | 2.2 s |
| muirfield | 400×300 s1–6 | 6/6 | 0 | 3 | 0 | 1.0 s | 2.9 s | 3.7 s |
| muirfield | 400×350 s1–6 | 6/6 | 0 | 0 | 0 | 0.35 s | 0.41 s | 0.41 s |
| muirfield_inverse | 350×400 s1–6 | 6/6 | 0 | 18 | 0 | 0.36 s | 2.4 s | 2.7 s |
| muirfield_inverse | 400×300 s1–6 | 6/6 | 0 | 6 | 0 | 0.36 s | 7.6 s | 14.2 s |
| muirfield_inverse | 400×350 s1–6 | 6/6 | 0 | 0 | 0 | 0.34 s | 0.39 s | 0.40 s |

Inversé 300×400 : relances aux seeds 1, 2, 19, 23, 29, 30 — 12
`echec_ancrages`, 11 `echec_front` (milieu du nine intérieur, ici le front,
budget épuisé : ~4 s par tentative, d'où 13 s pour s19 et 17.7 s pour s23),
9 gratuites (s30). Aucune règle assouplie, aucun budget relevé.

Lecture de la planche inversée (300×400, s1–6) : le back fait bien le grand
tour le long du bord (10 et 18 longent le bord de part et d'autre du
clubhouse), le front sort entre eux (1 vers l'intérieur, 9 qui revient) et
reste au centre. Le front intérieur est valide mais peu lisible comme une
boucle : ses trous se regroupent en faisceaux et en zigzags au centre (s2,
s3), comme le back intérieur du Muirfield normal — l'hélice / le
remplissage du centre reste le défaut de forme commun aux deux patrons.

#### Round C (2026-10-08) — largeurs de fairway variables

Nits de revue B traités : empreinte de non-régression du patron `muirfield`
(seeds 1–3, 300×400 : plan, pars, longueurs, nombre de tentatives) en
`width_mode="min"` ; `outer_start` / `anchor_bounds` lèvent `ValueError`
pour un patron hors `PATTERNS` (`random` non résolu compris) ; test des
rôles sur les trous réels (distance moyenne au centre des sommets d'axe :
nine extérieur > nine intérieur, pour les deux patrons) ; `lru_cache` sur
`_distinct_orders`.

**C1 — variation ENTRE trous (fait).** Chaque ordre 1..18 tire une
fraction seedée (`hole_width_fractions`, flux `[seed, 31]`, une fois par
seed, indépendante des relances) ; la largeur du trou est le point
correspondant de la plage de SON par (`PAR_SPECS`), arrondi au demi-bloc
(`hole_width`). Utilisée partout où la largeur minimale l'était : trous
construits, rayons des pré-filtres, trou-pont, capacité des cônes. Rien
d'autre ne change (règles, budgets, patrons). `width_mode` : `variable`
(défaut) ou `min` (comportement A–B ; les rounds r2…rb du runner y sont
figés pour rester reproductibles). Runner : `--width-mode`, `--round rc`
(planche 6 seeds muirfield) et `--round rc-30` (30 seeds par patron).

| patron, 300×400 s1–30 | largeur | réussis | violations | relances tentées | gratuites | médiane | p90 | max |
|---|---|---|---|---|---|---|---|---|
| muirfield (round B) | min (moy. ≈ 11) | 30/30 | 0 | 28 | 9 | 0.37 s | 3.5 s | 4.2 s |
| muirfield (C1) | variable (moy. 13.9) | 30/30 | 0 | 108 | 9 | 2.3 s | 10.8 s | 17.1 s |
| muirfield_inverse (round B) | min | 30/30 | 0 | 23 | 9 | 0.38 s | 3.5 s | 17.7 s |
| muirfield_inverse (C1) | variable | 30/30 | 0 | 100 | 9 | 2.4 s | 12.0 s | 18.0 s |

Sorties : `output/muirfield/rc_muirfield_300x400/` (planche + report,
seeds 1–6) et `rc_<patron>_300x400_30seeds/report.json`. Les fairways plus
larges (+26 % en moyenne) consomment plus d'espace : la validité est
conservée (30/30 pour les deux patrons, aucune règle ni budget touché) mais
les relances quadruplent (`echec_ancrages` 63/54, `echec_back` 45 pour
muirfield, `echec_front` 46 pour l'inversé — le milieu du nine intérieur) et
les temps médians passent de ~0.4 s à ~2.3 s. Temps machine de dev,
chronomètre homogène.

Lecture de la planche (muirfield 300×400, seeds 1–6) : la variation se voit
— des par 5 larges à côté de par 3 étroits (s2 : trou 7 large, 18 étroit),
ce qui casse l'uniformité des bandes. La carte paraît plus pleine ; les
faisceaux de trous parallèles et l'hélice restent les défauts de forme.

**C2 — variation À L'INTÉRIEUR d'un trou : NON FAIT, plan ci-dessous.**
Le changement n'est pas contenu : il touche l'oracle (construction exacte
du cœur et du rough), les arguments de nécessité des pré-filtres, le
surrogate incrémental (et ses preuves de conservativité), le modèle et son
schéma, et le rendu. Conformément à la consigne, arrêt après C1.

Plan de C2 :

1. *Modèle* (`model.py`) : `ElasticHole.width_profile: tuple[float, ...] |
   None`, une largeur par sommet de l'axe (tee, doglegs, green) ; `width`
   reste le scalaire compatible (= max du profil, ou valeur unique si pas de
   profil). Validation : longueur du profil = nombre de sommets, chaque
   valeur dans la plage du par. `SCHEMA_VERSION` 1 → 2, lecture des
   documents v1 inchangée (profil absent).
2. *Oracle* (`geometry.py`) : `buffered_axis(axis, radii)` à rayon par
   sommet. Chaque segment devient un trapèze (côtés décalés de r_i et
   r_{i+1}, donc NON parallèles à l'axe) ; jointure = intersection des deux
   droites décalées voisines (onglet exact), avec la même limite d'onglet
   (0.72) qu'aujourd'hui ; bouts prolongés de r_0 / r_n. `rough` = rayon +
   `rough_margin`. Risque principal : l'onglet entre côtés convergents peut
   produire une auto-intersection pour un dogleg serré et un fort écart de
   rayons — borner la variation (ex. |r_i − r_{i+1}| ≤ 0.25 × longueur du
   segment) et ajouter un test de simplicité du polygone.
3. *Contrôles en ligne* (`partial_checks.py`) : inchangés sur le principe
   (mêmes prédicats sur le nouveau cœur). Pré-filtres `Obstacles` : la
   condition nécessaire « cœur ⊇ axe ⊕ disque » doit devenir « cœur ⊇ ∪
   segments ⊕ disque(rayon MIN du segment) » — à démontrer pour la
   construction trapézoïdale + onglet, sinon utiliser le rayon min (plus
   faible, toujours nécessaire).
4. *Surrogate incrémental* (`incremental.py`) : capsules par segment au
   rayon MAX du segment (conservateur), disque de dogleg au max des deux
   rayons × `MITER_FACTOR` ; garder le test « zéro faux négatif » sur seeds
   perturbées et mesurer le taux de faux positifs avant/après.
5. *Routage* (`muirfield.py`) : profil seedé par trou — par 3 : quasi
   constant, se resserrant vers le green ; par 4 : élargi dans la zone
   d'atterrissage du drive (≈ 55–65 % de la longueur), resserré à l'approche
   du green ; par 5 : deux zones larges (drive, second coup). Profil défini
   aux sommets : nécessite d'ajouter des sommets intermédiaires sur les
   tirs droits (axe à 3–4 sommets colinéaires), ce qui touche aussi les
   pré-filtres de candidats.
6. *Rendu* (`render_readable.py`) : remplacer la polyligne épaisse par le
   polygone du cœur (et du rough), puisque `stroke-width` est constant.
7. *Tests* : oracle à rayon variable (écart fairway qui passe avec un profil
   resserré et échoue avec le profil plein au même axe ; polygone simple ;
   largeur hors plage d'un sommet → `width`) ; surrogate zéro faux négatif ;
   pré-filtres nécessaires (propriété) ; 0 violation 30 seeds × 2 patrons ;
   lecture/écriture JSON v1 et v2.

### Étape 4 — trous élastiques et mutations locales

Note (2026-10-07) : cette étape reste valable (score incrémental), mais la
conversion des corridors dépendra du nouveau niveau 1 (voir « Nouvelle
direction »).

- [x] Implémenter le cache incrémental et la chaîne boîtes → distance d'axes
  → oracle.
- [x] Microbenchmark d'une mutation complète < ~0,6 ms.
- [ ] Convertir chaque corridor grossier en axe continu à 0–2 doglegs.
- [ ] Implémenter les mutations d'un trou : tee, green, dogleg, longueur,
  rotation et largeur.
- [ ] Implémenter les mutations de voisinage sur 2–5 trous contigus.
- [ ] Ajouter échange de pars et reroutage d'une fenêtre sans casser le quota
  global 4/10/4.
- [x] Recalculer seulement les contraintes touchées par une mutation.
- [ ] Tester la reproductibilité d'une séquence de mutations seedée.

**Résultat partiel du 2026-10-06** : travail avancé en parallèle de l'étape 3
(indépendant du squelette). Module `incremental.py` : évaluateur surrogate
par capsules — axes prolongés de `half_width` à chaque bout pour contenir les
extrémités plates de l'oracle, disques de rayon `half_width / 0.72` aux
sommets de dogleg pour contenir les onglets de joint clampés, marge
forfaitaire conservatrice de 1,0 bloc retranchée une fois sur l'estimation
finale. Zéro faux négatif vérifié par un test de propriété seedé sur 300
layouts perturbés. Taux de faux positifs mesurés : composante `ecarts`
~25 % (surtout aux sommets partagés entre trous consécutifs d'une boucle,
où les bouts arrondis comblent le creux concave entre deux trous plus que le
polygone biseauté réel), `clubhouse` ~4 %, `liaisons` ~5 %.

Microbenchmark (`output/bench_incremental/REPORT.md`) : k=1 (un trou)
0,1736 ms en moyenne, k=3 (trous contigus) 0,3749 ms, oracle polygonal
complet ~8,03 ms (échantillon réduit) — contre ~11,46 ms mesurés à l'étape 2
sur un layout différent. Verdict **GO** : cible ~0,6 ms atteinte pour k=1 et
k=3 (accélération ×46 et ×21 vs oracle).

Composantes `parallelisme`, `variete` et `deformation` du score vectoriel
restent à 0 : la règle des séries consécutives (étape 2b) n'est pas encore
branchée dans `incremental.py`, et l'objectif « voyage » reste à définir à
l'étape 5. Suite ciblée `elastic_routing` : 47 tests.

Le reste de l'étape 4 (conversion des corridors en axes continus, mutations
de trou et de voisinage, échange de pars, démonstration de réparation) attend
la sortie de l'étape 3 (squelette grossier), dont il a besoin comme entrée.
La **Porte 4 n'est pas franchie**.

**Livrable** : démonstration synthétique où une collision volontaire est
réparée sans reconstruire tout le parcours.

**Porte 4** : la réparation locale doit être visible dans les diagnostics et
dans un SVG avant de brancher l'optimisation complète.

### Étape 5 — optimisation et inflation progressive

- [ ] Implémenter le mécanisme validé de recherche locale.
- [ ] Définir le score par familles : topologie, collisions, longueurs,
  liaisons, clubhouse, variété et déformation.
- [ ] Introduire les contraintes selon les six phases d'inflation.
- [ ] Autoriser les grands voisinages quand une violation persiste.
- [ ] Conserver le meilleur état valide et le meilleur état partiel.
- [ ] Vérifier qu'aucune pénalité souple ne masque une violation dure.

**Livrable** : optimiseur capable d'améliorer un layout dégradé sur des cas
synthétiques mesurés.

**Porte 5** : revue des courbes de score et des états intermédiaires ; pas
encore de benchmark multi-seed.

### Étape 6 — budget, arrêt et observabilité

- [ ] Appliquer le budget déterministe validé de 100 000 évaluations.
- [ ] Ajouter la cible de 60 s et le garde-fou mural de 120 s.
- [ ] Produire un résultat explicite `success`, `invalid` ou `timeout`.
- [ ] Toujours sauvegarder le meilleur JSON et SVG partiel en cas d'échec.
- [ ] Rapporter le temps par phase, les évaluations, mutations acceptées et
  violations restantes.
- [ ] Tester le timeout avec un budget artificiellement minuscule.

**Livrable** : runner impossible à laisser dériver pendant plusieurs dizaines
de minutes sans résultat exploitable.

**Porte 6** : démonstration automatisée du timeout et vérification de ses
artefacts avant le premier vrai parcours.

### Étape 7 — première expérience 18 trous

- [ ] Choisir une unique seed de départ.
- [ ] Générer le squelette initial.
- [ ] Lancer le raffinement avec cible 60 s et arrêt 120 s.
- [ ] Exécuter la validation indépendante.
- [ ] Produire rapport, JSON et les trois SVG prévus.
- [ ] Relire le code, les diagnostics et les SVG.
- [ ] Consigner la décision : poursuivre, corriger le niveau 1, corriger le
  niveau 2 ou abandonner l'approche.

**Livrable** : première réponse factuelle à l'hypothèse du spike.

**Porte 7** : aucun second run avant avis utilisateur sur les SVG.

### Étape 8 — robustesse seeds 1–5

- [ ] Lancer les seeds une par une avec le même budget et la même config.
- [ ] Consigner succès, timeout, temps, évaluations et violations par seed.
- [ ] Examiner chaque SVG, y compris les meilleurs états partiels.
- [ ] Calculer taux de succès, médiane et pire temps.
- [ ] N'apporter qu'une modification isolée entre deux séries.

**Porte 8** : décider si la robustesse et le coût justifient les seeds 6–10.

### Étape 9 — robustesse seeds 6–10

- [ ] Lancer uniquement si la porte 8 est validée.
- [ ] Conserver exactement la config validée sur 1–5.
- [ ] Produire le bilan agrégé 1–10 et comparer aux limites de `bean_paving`.
- [ ] Décider si le spike devient la base du générateur de parcours.

### Étape 10 — terrain réel, hors spike initial

- [ ] Introduire une seule famille d'obstacles à la fois.
- [ ] Vérifier que les réparations élastiques absorbent les contraintes sans
  dépasser le budget.
- [ ] Revalider la qualité visuelle avant toute intégration Minecraft.

## Première expérience

Le premier essai reste volontairement étroit :

- une seule seed ;
- 400×400 ;
- aucun terrain, rivière, route, forêt ou habitation ;
- distribution exacte 4/10/4 ;
- deux nines complets avec toutes les liaisons ;
- maximum deux doglegs par trou ;
- budget cible 60 s, arrêt absolu 120 s ;
- SVG du squelette initial, du meilleur état intermédiaire et du résultat ;
- rapport détaillant temps, score par famille de contraintes, mutations
  acceptées, réparations locales et éventuelles violations finales.

### Critère de réussite

Le spike passe sa première porte seulement si la seed produit en moins de
120 s un parcours 18/18 validé indépendamment et visuellement crédible.

Une solution valide mais manifestement symétrique, composée de deux anneaux ou
présentant des liaisons absurdes ne suffit pas : le SVG est une partie du
critère d'acceptation.

### Critère d'arrêt

Après un premier prototype minimal :

- pas de relance de plusieurs dizaines de minutes ;
- pas d'augmentation du budget avant analyse du SVG et des diagnostics ;
- si la topologie globale échoue, corriger le niveau 1 ;
- si seule la géométrie finale échoue, corriger les mutations/réparations du
  niveau 2 ;
- ne modifier qu'une famille de mécanismes par expérience.

## Validation ultérieure

Après validation visuelle et technique de la première seed :

1. seeds 1–5, une par une ou avec un plafond global clairement annoncé ;
2. mesure du taux de succès, du temps médian et du pire temps ;
3. revue des SVG avant toute optimisation supplémentaire ;
4. seeds 6–10 seulement si l'étape précédente reste compatible avec le budget ;
5. introduction du terrain réel après robustesse sur carte vide.

## Hors périmètre initial

- détails de greens et de tees ;
- bunkers, eau, végétation et relief ;
- routes et bâtiments autres que le clubhouse ;
- optimisation esthétique fine ;
- génération Minecraft ;
- portefeuille de plusieurs solveurs lancé en parallèle ;
- assouplissement du par 72 pour masquer une faiblesse du placement.

## Décisions validées avant implémentation

Décisions approuvées le 2026-10-06 :

1. **Dimensions** : reprendre les plages de `bean_paving` — par 3 de 75 à
   110 blocs et largeur de 10 à 15 ; par 4 de 120 à 175 et largeur de 11 à
   17 ; par 5 de 175 à 235 et largeur de 12 à 18.
   *Remplacée le 2026-10-07* (étape M) : par 3 45–70, par 4 100–145,
   par 5 145–185 ; les anciennes plages restent dans `LEGACY_PAR_SPECS`.
2. **Grille** : pas de 5 blocs pour le squelette grossier.
3. **Liaisons** : plage assouplie de 12 à 60 blocs pendant la construction,
   resserrée progressivement à 12–45 pour la validation finale.
4. **Doglegs** : zéro ou un dogleg au niveau grossier ; un deuxième dogleg
   peut être introduit pendant le raffinement élastique.
5. **Budget** : 100 000 évaluations déterministes, cible de 60 s et arrêt mural
   absolu à 120 s. Un unique microbenchmark pourra calibrer le nombre
   d'évaluations avant la première expérience, sans relever les limites de
   temps.
6. **Raffinement** : recuit simulé avec mutations locales, complété
   périodiquement par une réparation à grand voisinage portant sur 2 à 5
   trous.

Voir aussi les décisions d'architecture complémentaires du 2026-10-06
(seconde série), section « Décision d'architecture avant l'étape 3 ».

Ces décisions ferment la Porte 0. Toute modification ultérieure doit être
consignée comme une nouvelle expérience, sans changer plusieurs paramètres à
la fois.
