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

**Porte 1 — prête pour validation** : aucun rendu ni algorithme ne commence
avant revue de ce modèle et de ses tests.

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

**Porte 2 — prête pour validation** : revue du SVG synthétique et des tests
avant toute génération. L'étape 3 ne commence pas avant validation utilisateur.

### Étape 3 — squelette global grossier

- [ ] Représenter sur grille les deux séquences alternées trou/liaison.
- [ ] Réserver les quatre ports clubhouse : tee 1, green 9, tee 10, green 18.
- [ ] Générer une topologie complète de 18 trous sans chercher encore les
  formes finales.
- [ ] Empêcher les croisements topologiques grossiers.
- [ ] Introduire une asymétrie seedée et reproductible entre les deux nines.
- [ ] Rendre le squelette initial dans un SVG dédié.

**Livrable** : un squelette 18 trous complet produit rapidement, même s'il ne
respecte pas encore les largeurs finales.

**Porte 3** : inspection visuelle obligatoire. Rejeter les deux anneaux, la
symétrie excessive et les liaisons incohérentes avant de poursuivre.

### Étape 4 — trous élastiques et mutations locales

- [ ] Convertir chaque corridor grossier en axe continu à 0–2 doglegs.
- [ ] Implémenter les mutations d'un trou : tee, green, dogleg, longueur,
  rotation et largeur.
- [ ] Implémenter les mutations de voisinage sur 2–5 trous contigus.
- [ ] Ajouter échange de pars et reroutage d'une fenêtre sans casser le quota
  global 4/10/4.
- [ ] Recalculer seulement les contraintes touchées par une mutation.
- [ ] Tester la reproductibilité d'une séquence de mutations seedée.

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

Ces décisions ferment la Porte 0. Toute modification ultérieure doit être
consignée comme une nouvelle expérience, sans changer plusieurs paramètres à
la fois.
