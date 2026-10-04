# Rapport — surface 500×500 et packing avant routing

## Questions testées

1. Le blocage du deuxième nine en 350×350 vient-il surtout de la densité ?
2. Peut-on placer les 18 trous sans ordre, puis trouver deux chemins de neuf ?

Seed témoin : 42. Les longueurs, largeurs, marges, croisements, règle
antiparallèle et liaisons 12–45 restent inchangés.

## 1. Solveur séquentiel en 500×500

**Résultat : succès 18/18, aucune violation dure.**

- front : 9/9, 75 150 transformations ;
- back : 9/9, 41 400 transformations ;
- temps : 3 min 33 s avec beam réduit ;
- lookahead de fermeture désactivé pour ce run rapide, mais retour clubhouse
  vérifié comme contrainte dure au neuvième trou de chaque nine ;
- pars du front : `4-4-4-4-5-3-5-4-3` ;
- pars du back : `4-3-3-5-4-4-4-5-4`.

Le passage de 350 à 500 double presque exactement la surface disponible et
résout le blocage topologique observé précédemment. En revanche, le nombre
d'états valides augmente fortement : le prototype Python devient plus lent.

Visuel : [`output/seed42_course18_500.svg`](output/seed42_course18_500.svg).

## 2. Packing aveugle puis recherche des chemins

Le second prototype sélectionne bien `4/10/4` dans la banque `8/20/8`, place
les formes de la plus longue à la plus courte sans regarder les ports, puis :

1. crée une arête dirigée lorsque green A → tee B mesure 12 à 45 blocs ;
2. cherche deux chemins disjoints de neuf trous ;
3. n'impose aucun par théorique par nine.

### Carte 350×350

**Résultat : packing bloqué à 12/18.**

- 70 956 transformations ;
- 1 min 23 s ;
- aucune exemption géométrique ;
- le routing n'est pas lancé sur un packing incomplet.

Le packing aveugle perd le guide spatial que fournissaient les liaisons et se
fige dans une configuration dense avant les six dernières formes.

Visuel : [`output/seed42_pack_then_route.svg`](output/seed42_pack_then_route.svg).

### Contrôle 500×500

**Résultat : packing 18/18, routing impossible.**

- 115 830 transformations ;
- 5 min 18 s ;
- seulement **3 arêtes** green → tee compatibles ;
- plus long chemin : **2 trous** ;
- un seul tee à moins de 50 blocs du clubhouse ;
- aucun green à moins de 50 blocs du clubhouse.

Le contrôle isole les deux phénomènes : 500 résout la densité du packing, mais
un packing totalement aveugle ne crée presque jamais les ports nécessaires à
un parcours.

Visuel :
[`output/seed42_pack_then_route_500.svg`](output/seed42_pack_then_route_500.svg).

## Conclusion

- **500×500 valide l'approche actuelle pour 18 trous.**
- **Packing d'abord, routing ensuite n'est pas viable sous forme totalement
  découplée.**
- La souplesse sur le par du front et du back reste une bonne idée : le futur
  solveur ne devrait pas imposer deux distributions `2/5/2`.

La piste suivante est un **packing connecté sans ordre fixé** :

- ne pas décider que le prochain trou placé sera le prochain trou joué ;
- maintenir néanmoins plusieurs prédécesseurs/successeurs possibles par port ;
- réserver au moins deux tees et deux greens proches du clubhouse ;
- scorer la taille de la composante connexe du graphe ;
- chercher les deux chemins seulement après le packing ;
- laisser les pars de chaque nine émerger, avec seulement le total `4/10/4`.

Ce modèle hybride conserve l'intérêt de la proposition — liberté spatiale et
distribution naturelle des pars — tout en évitant le graphe presque vide du
packing aveugle.
