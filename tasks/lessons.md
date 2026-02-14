# Lessons Learned

## Terrain

### OpenSimplex vectorise
- `opensimplex.noise2array(xs, ys)` est ~2x plus rapide que la boucle Python
- `opensimplex.seed(n)` est au niveau module, pas `OpenSimplex(seed=n)` instance

## Placement des trous (CoursePlacer)

### Scoring : hierarchie des poids
- Les contraintes se combattent facilement. Garder un scoring simple avec peu de termes.
- Les contraintes essentielles : overlap, return, territory, convergence, clubhouse protection, crossing
- Les contraintes secondaires (eau, coverage, direction, clustering) ont ete retirees car elles cascadaient des conflits
- On les remettra une par une lors du raffinement

### Convergence pre-retour : cibler la bonne distance
- Si G8 est trop proche du CH (50 blocs), un par 4 de 120 blocs depasse le CH
- Si G8 est trop loin (200 blocs), le par 4 ne peut pas atteindre le CH
- Solution : convergence avec target = ~110 blocs (longueur typique du trou de retour)
- Penalite (d - target)^2 pour centrer sur la distance ideale

### Retour au clubhouse : ne pas viser le CH directement
- Le green de retour ne doit pas atterrir SUR le clubhouse
- Utiliser (d - 20)^2 au lieu de d^2 pour cibler ~20 blocs avant le CH
- Exempter les trous de retour de : territory, crossing penalty, overlap (x0.1)

### Anti-croisement : poids massif
- Le return_penalty peut atteindre ~70k (d^2 * 3). Le crossing a besoin d'etre >> ca
- Solution : +1_000_000 plancher pour les croisements (sauf trous retour exempts)

### Tees sur fairways : verification bidirectionnelle
- Verifier que les segments du nouveau trou ne passent pas sur des tees/greens existants
- ET que les tees/greens du nouveau trou ne sont pas sur des segments existants
- Poids 500 pour cette penalite (fort car visuellement genant)

### RNG : separer les flux
- Les offsets de tee (8 essais par angle) perturbent le RNG principal
- Solution : `tee_rng = random.Random(seed + 2000 + hole_id)` separe par trou
- Le RNG principal ne change pas quand on ajuste tee_tries

### Multi-shape : generer au moment de placer
- Generer les formes avant le placement empeche l'adaptation
- Solution : `hole_gen.generate_one(par)` appele 4 fois par trou dans la boucle de placement
- On garde la meilleure combo forme x angle x position

## Tests

### Fixtures session-scoped pour performance
- La heightmap prend ~7s a generer → fixture `scope="session"` dans conftest.py
- Workflow : recalculer avec un script Python si on change le terrain, puis mettre a jour les tests

## Architecture

### Approche "trous d'abord" vs paving
- L'ancienne approche (Voronoi paving → routing dans les cellules) imposait des formes artificielles
- La nouvelle approche genere les trous librement puis les place sur le terrain
- Beaucoup plus flexible et donne des resultats plus naturels
