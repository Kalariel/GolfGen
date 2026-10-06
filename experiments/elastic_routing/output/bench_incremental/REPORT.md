# Microbenchmark du cache incrémental (étape 4)

Layout : synthétique 18 trous. Règles : `ValidationRules()` (finales). Seed : 20261006. Budget cible : < 0.6 ms / mutation (100 000 évaluations en 60 s).

Chaque mutation mesurée = `apply()` (géométrie + paires k×17 + liaisons touchées) + `score()`, avec `revert()` un coup sur deux (inclus dans le temps mesuré).

| Scénario | n | moyenne (ms) | médiane (ms) | p95 (ms) | max (ms) |
|---|---:|---:|---:|---:|---:|
| k=1 (un trou) | 20000 | 0.1748 | 0.1743 | 0.1911 | 0.4064 |
| k=3 (trous contigus) | 8000 | 0.3793 | 0.3789 | 0.4105 | 0.5003 |
| oracle `validate()` complet | 30 | 9.8673 | 9.8539 | 9.9938 | 10.0679 |

**Verdict go/no-go** : GO — cible ~0.6 ms atteinte pour k=1 et k=3 (accélération vs oracle : k=1 ×56, k=3 ×26).

Notes :

- le recalcul complet du score surrogate (`score()`) agrège tous les caches (18 trous, 153 paires, 20 liaisons) à chaque appel ; seule la **géométrie** touchée par la mutation est recalculée, pas l'agrégation finale (O(fixe), négligeable pour 18 trous) ;
- k=3 coûte environ le double de k=1 (plus de paires et de liaisons touchées), pas 3×, car les paires communes aux 3 trous changés ne sont recalculées qu'une fois chacune ;
- comparaison à l'oracle sur un échantillon réduit (30 appels) car ~11 ms/appel rendrait un grand échantillon coûteux pour un résultat déjà stable ;
- le budget 100 000/60 s porte sur le coût **moyen** d'une évaluation (soit 0,6 ms) : un `max` ponctuel de k=3 proche ou légèrement au-dessus (GC, jitter de l'interpréteur) n'invalide pas le go/no-go tant que la moyenne et le p95 restent nettement en dessous, ce qui est le cas ici.
