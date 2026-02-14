# Todo - Generateur procedural de parcours de golf

## Phase 1 : Terrain [TERMINEE]
- [x] Arborescence (`golfgen/`, `viewer/`, `output/`)
- [x] `golfgen/config.py` — dataclasses
- [x] `golfgen/terrain.py` — generation heightmap (vectorise ~7s)
- [x] `golfgen/exporter.py` — export JSON terrain
- [x] `pipeline.py` — CLI minimal `--stage terrain`
- [x] `viewer/` — HTML+CSS+JS affiche la heightmap
- [x] `tests/test_terrain.py` — tests de regression (18 tests)

## Phase 2 : Placement des 18 trous [TERMINEE]
- [x] `golfgen/hole_gen.py` — HoleGenerator + HoleShape (formes parametriques)
- [x] `golfgen/placer.py` — CoursePlacer (placement greedy avec scoring)
- [x] `pipeline.py` — etape `holes` (terrain + placement)
- [x] `golfgen/exporter.py` — add_routing avec clubhouse_pos
- [x] Clubhouse dans un coin (determine par seed)
- [x] Separation territoriale front/back nine (secteurs angulaires)
- [x] Retour au clubhouse (G9/G18 a ~20 blocs du CH)
- [x] Convergence pre-retour (H7-8/H16-17 a ~110 blocs du CH)
- [x] Anti-croisement (+1M, exempt trous retour)
- [x] Protection clubhouse (rayon 25 blocs, exempt retour)
- [x] Multi-shape candidats (4 formes × 72 angles × 8 tee offsets)
- [x] Anti-chevauchement tee/green sur fairways existants

## Phase 3 : Raffinement du parcours (PROCHAINE)
- [ ] Verification visuelle multi-seeds
- [ ] Lissage terrain sous les fairways
- [ ] Bunkers, eau, iles, ravins
- [ ] Rendu obstacles dans viewer.js

## Phase 4 : Vegetation + Features
- [ ] Forets, arbres entre les trous
- [ ] Ponts, ruisseaux
- [ ] Rendu complet dans viewer.js

## Phase 5 : Polish
- [ ] Mode vue detaillee par trou
- [ ] Test multi-seeds automatise
