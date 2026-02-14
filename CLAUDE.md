# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Projet

Générateur procédural et visualiseur interactif d'un parcours de golf 18 trous pour Minecraft. Deux composants :
1. **Pipeline Python** (`golfgen/`) — génère un parcours procéduralement (terrain Perlin, paving, clubhouse, routing, obstacles, végétation)
2. **Viewer HTML/JS** (`viewer/`) — affiche le JSON produit par le pipeline sur un canvas interactif
3. **Fichiers de référence** (`course_overview.html`, `hole1_map.html`) — anciens viewers statiques, conservés comme référence visuelle

## Lancer le projet

```bash
# Installer les dépendances Python
pip install -r requirements.txt

# Générer un parcours (terrain seul)
python pipeline.py --stage terrain

# Générer terrain + paving
python pipeline.py --stage paving

# Terrain + paving + clubhouse
python pipeline.py --stage clubhouse

# Pipeline complet (quand toutes les étapes seront implémentées)
python pipeline.py --stage features

# Options
python pipeline.py --seed 123 --stage clubhouse --output output/v2.json

# Tests
python -m pytest tests/ -v
```

Le viewer se lance en ouvrant `viewer/index.html` dans un navigateur. Il charge automatiquement `output/course.json` ou permet de charger un JSON manuellement.

## Architecture

```
golfgen/                    # Bibliothèque Python
├── config.py               # Dataclasses CourseConfig, TerrainConfig, PavingConfig, ClubhouseConfig...
├── terrain.py              # TerrainGenerator — OpenSimplex multi-octave (vectorisé)
├── paver.py                # PavingGenerator — Dijkstra isotrope 8-dir, cellules organiques
├── clubhouse.py            # ClubhousePlacer — placement optimal à la jonction de 4 cellules
├── router.py               # LayoutRouter — boucle polygonale, par 3 comme pivots (à refaire)
├── refiner.py              # TerrainRefiner — lissage post-routing (TODO)
├── hazards.py              # HazardPlacer — bunkers, eau, ravins (TODO)
├── vegetation.py           # VegetationPainter — forêts, arbres (TODO)
├── features.py             # FeatureGenerator — ponts, ruisseaux (TODO)
├── exporter.py             # JSONExporter — sérialisation JSON, heightmap base64
└── utils.py                # Math, gradient, géométrie

pipeline.py                 # CLI principal (orchestre les 7 étapes)
default_config.json         # Config par défaut (surchargeable)

viewer/
├── index.html              # Page unique
├── style.css               # CSS (thème sombre, Silkscreen/IBM Plex Mono)
└── viewer.js               # Moteur de rendu Canvas (consomme le JSON)

tests/
├── conftest.py             # Fixtures partagées (config, heightmap, paving_result, clubhouse_result)
├── test_terrain.py         # Tests de régression terrain (seed 42)
├── test_paving.py          # Tests de régression paving (seed 42)
├── test_clubhouse.py       # Tests du clubhouse (position, aplatissement, practice, putting)
└── test_routing.py         # (à écrire — supprimé, routing à refaire de zéro)

output/
└── course.json             # Fichier généré par le pipeline
```

## Contrat JSON (Python → Viewer)

Le JSON contient des couches optionnelles : `terrain`, `paving`, `clubhouse`, `routing`, `hazards`, `vegetation`, `features`. Le viewer affiche ce qui est présent.

- **Heightmap** : encodée en base64 uint8 normalisé [0-255] → reconverti en élévation [min, max]
- **Paving** : `owner` grid en base64 int16, `cells[]` avec id, par, seed_tx/ty, tile_count
- **Clubhouse** : `x`, `y`, `width`, `height`, `elevation`, `adjacent_cells`, `practice_range`, `putting_green`
- **Routing** : `holes[]` avec `tee`, `green`, `waypoints` (objets `{x, y}`), `fairway_width`, `par`, `blocks`
- **Blocks** : distance réelle calculée depuis les waypoints (polyline_length)

## Concepts clés

- **Système de coordonnées** : blocs Minecraft. 1 bloc = 3 mètres.
- **Terrain** : OpenSimplex 6 octaves, grille 350×350, élévation [58, 82], gradient N-S
- **Paving** : Dijkstra isotrope 8-dir avec bruit + pente. 18 cellules organiques. Seeds sur grille 6×3 avec jitter.
- **Clubhouse** : placé automatiquement à la jonction de >= 4 cellules paving. Scoring multi-critère (quad bonus, platitude, élévation, centralité). Aplatit le terrain in-place. Practice range + putting green adjacents.
- **Routing** : (à refaire) boucles polygonales autour du clubhouse. Les par 3 servent de pivots.
- **Palette** : constante `C` dans viewer.js (rough=#2e5420, fairway=#6aad45, green=#3dbd4e, tee=#4ecf5f, sand=#e8d68a, water=#3b8bba)

## Conventions

- Python : dataclasses, type hints, numpy vectorisé quand possible
- JS : vanilla, pas de framework, canvas 2D
- Polices : Google Fonts `Silkscreen` (titres) et `IBM Plex Mono` (contenu)
- Interface : français
- Config : JSON (pas de YAML/TOML)

## Pipeline (7 étapes)

| # | Étape | Module | Description | Status |
|---|-------|--------|-------------|--------|
| 1 | terrain | `terrain.py` | OpenSimplex heightmap 350×350 (~7s) | OK |
| 2 | paving | `paver.py` | Découpage Dijkstra en 18 cellules organiques | OK |
| 3 | clubhouse | `clubhouse.py` | Placement optimal + aplatissement + practice/putting | OK |
| 4 | routing | `router.py` | Placement 18 trous (à écrire de zéro) | TODO |
| 5 | hazards | `hazards.py` | Bunkers, eau, ravins | TODO |
| 6 | vegetation | `vegetation.py` | Forêts, arbres | TODO |
| 7 | features | `features.py` | Ponts, ruisseaux | TODO |

## Config (dataclasses)

- `CourseConfig` : width=350, height=350, seed=42, clubhouse_x/y=None (auto-détecté)
- `TerrainConfig` : octaves, persistence, scale, elevation_min/max, base_elevation, ns_gradient
- `PavingConfig` : target_coverage, weights par3/4/5, tile_size=5, water_level=61
- `ClubhouseConfig` : width=45, height=35, flat_radius_margin=40, flat_transition=25, practice_length=70, practice_width=25, putting_radius=6
- `RoutingConfig` : par_distribution, ranges par3/4/5, fairway widths, green radius, etc.

## Fichiers de référence (anciens)

- `course_overview.html` — Vue d'ensemble 18 trous hardcodée (880×780 coords, SCALE=1.15)
- `hole1_map.html` — Vue détaillée Trou 1 bloc par bloc (50×130 blocs)
