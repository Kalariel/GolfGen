# Todo - Générateur procédural de parcours de golf

## Phase 1 : Fondation + Terrain [TERMINEE]
- [x] Arborescence (`golfgen/`, `viewer/`, `output/`)
- [x] `requirements.txt` (numpy, opensimplex)
- [x] `golfgen/config.py` — dataclasses
- [x] `golfgen/terrain.py` — génération heightmap (vectorisé ~7s)
- [x] `golfgen/exporter.py` — export JSON terrain
- [x] `pipeline.py` — CLI minimal `--stage terrain`
- [x] `viewer/` — HTML+CSS+JS affiche la heightmap
- [x] `tests/test_terrain.py` — tests de régression (50 tests)

## Phase 2 : Paving Voronoi [TERMINEE]
- [x] `golfgen/paver.py` — Dijkstra isotrope 8-dir, 18 cellules organiques
- [x] `golfgen/config.py` — PavingConfig (tile_size=5, water_level=61, weights)
- [x] `pipeline.py` — étape paving insérée
- [x] `golfgen/exporter.py` — add_paving() (owner base64 int16 + cells)
- [x] `viewer/viewer.js` — layer debug paving (HSL + contours + labels)
- [x] `tests/test_paving.py` — tests de régression

## Phase 3 : Clubhouse [TERMINEE]
- [x] `golfgen/config.py` — ClubhouseConfig, clubhouse_x/y Optional
- [x] `golfgen/terrain.py` — retiré _apply_central_flat() de generate()
- [x] `golfgen/clubhouse.py` — ClubhousePlacer (quad junctions, scoring, aplatissement, practice, putting)
- [x] `golfgen/exporter.py` — add_clubhouse(), add_routing() sans clubhouse param
- [x] `pipeline.py` — 7 étapes, clubhouse entre paving et routing
- [x] `default_config.json` — section clubhouse, retiré clubhouse_x/y hardcodés
- [x] `viewer/viewer.js` — rendu practice range + putting green depuis courseData.clubhouse
- [x] `tests/test_clubhouse.py` — 11 tests (position, adjacence, aplatissement, practice, putting, déterminisme, régression)
- [x] Tests de régression terrain et paving mis à jour (50 tests passent)

## Phase 4 : Routing (PROCHAINE)
- [ ] Refaire `golfgen/router.py` de zéro pour consommer le paving + clubhouse
- [ ] Placement tee/green dans chaque cellule assignée
- [ ] Waypoints + doglegs terrain-aware
- [ ] Boucles : trous 1-9 et 10-18 partant/revenant au clubhouse
- [ ] Tests de régression routing

## Phase 5 : Raffinement + Obstacles
- [ ] `golfgen/refiner.py` — lissage terrain sous les fairways
- [ ] `golfgen/hazards.py` — bunkers, eau, ravins
- [ ] Rendu bunkers et eau dans viewer.js

## Phase 6 : Végétation + Features
- [ ] `golfgen/vegetation.py` — forêts, arbres entre les trous
- [ ] `golfgen/features.py` — ponts, ruisseaux
- [ ] Rendu complet dans viewer.js

## Phase 7 : Polish
- [ ] Config JSON complète
- [ ] Mode vue détaillée par trou
- [ ] Test multi-seeds (1, 42, 100, 999, 12345)
- [ ] Mise à jour CLAUDE.md finale
