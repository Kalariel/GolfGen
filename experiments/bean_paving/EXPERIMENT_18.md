# Essai 18 trous coordonné — arrêt expérimental

## Résultat

La banque de 36 formes est fonctionnelle (`8/20/8`), mais deux recherches de
nine successives ne pavent pas encore 18 trous sur la même carte 350x350.

Meilleur résultat reproductible, seed 42 :

- front nine : **9/9**, valide, 110 610 transformations testées ;
- back nine : **1/9**, puis aucune continuation valide ;
- deuxième trou du back : 432 essais, 0 accepté ;
- causes dominantes : 432 collisions d'empreinte, 368 croisements d'axes et
  77 retours antiparallèles (un essai peut compter plusieurs causes) ;
- rectangle englobant des extrémités du front : environ 60 % de la carte.

Le SVG `output/seed42_course18_failed.svg` conserve le meilleur état.

## Variantes essayées

1. Front avec le score du nine, départs back dans le secteur opposé : le back
   ne place aucun trou à 24–36 blocs du clubhouse.
2. Départs back repoussés à 44–48 blocs : aucun premier trou avec
   l'échantillonnage initial.
3. Cercle de départ complet et 144 transformations par candidat au premier
   coup : le back atteint 1/9 puis bloque.
4. Front fortement compacté (`radius_scale=0.82`, `bbox_weight=0.00075`) : le
   front lui-même bloque à 8/9.
5. Compromis final (`radius_scale=0.9`, `bbox_weight=0.0004`, beam 72) : front
   9/9, back 1/9, sans progression au deuxième trou.

Aucune règle géométrique n'a été assouplie pendant ces essais.

## Conclusion

Le nine abstrait est validé, mais la stratégie « résoudre un nine complet,
puis traiter son résultat comme obstacle immuable » monopolise trop d'espace
topologique. La surface brute n'est pas le seul problème : le premier nine
découpe l'espace restant en poches incapables de recevoir une forme longue.

Ce résultat ne justifie pas encore d'abandonner le paving. Il indique que
l'étape 6 demande une coordination plus précoce, par exemple :

- construire les deux nines en alternance ;
- réserver explicitement deux corridors de retour clubhouse ;
- scorer l'espace libre par sa composante connexe et sa largeur, pas seulement
  par un rectangle englobant ;
- ou effectuer une recherche conjointe par paires de profondeurs, sans aller
  directement à un DFS global de profondeur 18.

## Point de reprise

Reprendre dans `course_solver.py`. Conserver la banque 36, le validateur et le
solveur de nine. Remplacer l'enchaînement front-puis-back par une coordination
alternée ; ne pas augmenter simplement le beam et ne pas lancer l'étape 7 tant
qu'un parcours abstrait de 18 trous n'est pas valide.
