# Lessons Learned

## Paving

### Dijkstra isotrope > anisotrope pour cellules organiques
- Voronoi anisotrope (Dijkstra avec dx=1.8, dy=1.0) → toutes les cellules allongées N-S
- Voronoi distance directe → mêmes formes monotones
- BSP rectangulaire + bruit → frontières trop alignées
- **Solution** : Dijkstra isotrope 8-dir avec bruit pré-généré par tile + pénalité de pente

### Seeds : grille lâche + jitter + serpentin
- Grille 6×3, pad=4, jitter ±4 clippé dans la cellule de grille
- Ordre serpentin pour que les IDs soient géographiquement cohérents
- BFS fallback si la seed tombe dans l'eau

## Terrain

### OpenSimplex vectorisé
- `opensimplex.noise2array(xs, ys)` est ~2× plus rapide que la boucle Python
- `opensimplex.seed(n)` est au niveau module, pas `OpenSimplex(seed=n)` instance

### Aplatissement : pas dans le terrain, dans le clubhouse
- L'ancien `_apply_central_flat()` aplatissait à un point hardcodé (hors grille)
- Maintenant l'aplatissement se fait dans `ClubhousePlacer` après avoir trouvé la position optimale
- La heightmap est modifiée in-place

## Clubhouse

### Quad junctions pour placement optimal
- Scanner la grille owner avec une fenêtre de la taille du clubhouse en tiles
- Compter les cell IDs uniques (>= 4 cellules distinctes = bon candidat)
- Scoring multi-critère : quad bonus (40pts), platitude (30pts), élévation (20pts), centralité (10pts)

### numpy.int16 → JSON serialization
- `set(window.flat)` retourne des `numpy.int16`, pas des `int` Python
- `json.dumps()` ne sait pas sérialiser `numpy.int16`
- **Solution** : utiliser `int(v) for v in np.unique(window)` pour convertir en int natif

### Practice range : tester 4 directions
- N, S, E, O depuis le clubhouse
- Vérifier : pas hors limites, pas d'eau (< 10%), terrain le plus plat
- Putting green : côté opposé au practice

## Exporter

### Dédupliquation des pipeline_stages
- `add_terrain()` est appelé 2 fois (initial + après aplatissement clubhouse)
- Sans garde, "terrain" apparaît 2 fois dans pipeline_stages
- **Solution** : `if "terrain" not in stages` avant append

## Routing (tentative precedente — supprimee)

### Distances bord-a-bord > endpoints de diagonale
- La diagonale maximale (convex hull) ne donne que 2 points par cellule
- Deux cellules adjacentes peuvent avoir des endpoints de diagonale tres eloignes (>200 blocs)
- **Solution identifiee** : matrice de distances bord-a-bord entre toutes les paires de cellules
- Un tile est "de bord" si un voisin 4-dir appartient a une autre cellule

### L'enchainement des cellules ≠ le placement tee/green
- Meme avec un enchainement parfait (5 blocs entre cellules adjacentes), les transitions tee/green peuvent etre catastrophiques (>200 blocs)
- Cause : la diagonale oriente le tee/green sans tenir compte de la cellule precedente/suivante
- L'enchainement des cellules doit etre resolu AVANT le placement tee/green

### _fix_continuity cascade
- Deplacer un green pour corriger une transition casse la transition precedente
- Ne jamais corriger en cascadant des deplacements post-hoc
- **Lecon** : resoudre le probleme a la source (bon enchainement) plutot que patcher apres

### patch_owner modifie la geometrie des cellules
- `PavingGenerator.patch_owner()` cree la zone 18 (clubhouse) et reassigne des tiles
- Les diagnostics DOIVENT utiliser le owner patche pour etre coherents avec le pipeline
- Erreur courante : tester sans patch_owner et obtenir des resultats differents

## Tests

### Fixtures session-scoped pour performance
- La heightmap prend ~7s à générer → fixture `scope="session"` dans conftest.py
- Le paving et le clubhouse chaînent depuis la même heightmap
- Attention : le ClubhousePlacer modifie la heightmap in-place → copier avant dans la fixture

### Valeurs de référence fragiles
- Tout changement dans le terrain cascade vers le paving et le clubhouse
- Quand on retire `_apply_central_flat()`, TOUTES les valeurs de régression changent
- Workflow : recalculer avec un script Python, puis mettre à jour les tests
