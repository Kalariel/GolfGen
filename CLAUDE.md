# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Projet

Generateur procedural et visualiseur interactif d'un parcours de golf 18 trous pour Minecraft. Deux composants :
1. **Pipeline Python** (`golfgen/`) — genere un parcours proceduralement (terrain Perlin, placement 18 trous, obstacles, vegetation)
2. **Viewer HTML/JS** (`viewer/`) — affiche le JSON produit par le pipeline sur un canvas interactif

## Lancer le projet

```bash
# Installer les dependances Python
pip install -r requirements.txt

# Generer terrain seul
python pipeline.py --stage terrain

# Generer terrain + placement 18 trous (pipeline complet actuel)
python pipeline.py --stage holes

# Options
python pipeline.py --seed 123 --stage holes --output output/v2.json

# Tests
python -m pytest tests/ -v
```

Le viewer se lance en ouvrant `viewer/index.html` dans un navigateur. Il charge automatiquement `output/course.json` ou permet de charger un JSON manuellement.

## Architecture

```
golfgen/                    # Bibliotheque Python
├── config.py               # Dataclasses CourseConfig, TerrainConfig, RoutingConfig
├── terrain.py              # TerrainGenerator — OpenSimplex multi-octave (vectorise)
├── hole_gen.py             # HoleGenerator — formes parametriques en coords locales
├── placer.py               # CoursePlacer — placement 18 trous avec scoring multi-critere
├── exporter.py             # JSONExporter — serialisation JSON, heightmap base64
└── utils.py                # Math, gradient, geometrie (distance, segments_intersect, etc.)

pipeline.py                 # CLI principal (orchestre les 2 etapes)
default_config.json         # Config par defaut (surchargeable)

viewer/
├── index.html              # Page unique
├── style.css               # CSS (theme sombre, Silkscreen/IBM Plex Mono)
└── viewer.js               # Moteur de rendu Canvas (consomme le JSON)

tests/
├── conftest.py             # Fixtures partagees (config, heightmap)
└── test_terrain.py         # Tests de regression terrain (seed 42, 18 tests)

output/
└── course.json             # Fichier genere par le pipeline
```

## Contrat JSON (Python → Viewer)

Le JSON contient des couches optionnelles : `terrain`, `routing`. Le viewer affiche ce qui est present.

- **Heightmap** : encodee en base64 uint8 normalise [0-255] → reconverti en elevation [min, max]
- **Routing** : `holes[]` avec `tee`, `green`, `waypoints` (objets `{x, y}`), `fairway_width`, `par`, `blocks`
- **Routing.clubhouse** : `{x, y}` — position du clubhouse (coin determine par la seed)
- **Blocks** : distance reelle calculee depuis les waypoints (polyline_length)

## Concepts cles

- **Systeme de coordonnees** : blocs Minecraft. 1 bloc = 3 metres.
- **Terrain** : OpenSimplex 6 octaves, grille 350×350, elevation [58, 82], gradient N-S
- **Clubhouse** : place automatiquement dans un coin (determine par seed), avec separation angulaire front/back nine
- **Hole generation** : formes parametriques en coords locales (tee=(0,0), axe Y+), avec waypoints, fairway_width, green_radius
- **Placement** : greedy sequentiel, 72 angles × 8 tee offsets × 4 formes = ~2304 candidats/trou, scoring multi-critere
- **Scoring** : overlap, return_penalty (G9/G18 → ~20 blocs du CH), territory (secteurs angulaires), convergence (H7-8/H16-17), clubhouse protection, anti-crossing (+1M)
- **Palette** : constante `C` dans viewer.js (rough=#2e5420, fairway=#6aad45, green=#3dbd4e, tee=#4ecf5f, sand=#e8d68a, water=#3b8bba)

## Conventions

- Python : dataclasses, type hints, numpy vectorise quand possible
- JS : vanilla, pas de framework, canvas 2D
- Polices : Google Fonts `Silkscreen` (titres) et `IBM Plex Mono` (contenu)
- Interface : francais
- Config : JSON (pas de YAML/TOML)

## Pipeline (2 etapes actives + futures)

| # | Etape | Module | Description | Status |
|---|-------|--------|-------------|--------|
| 1 | terrain | `terrain.py` | OpenSimplex heightmap 350×350 (~7s) | OK |
| 2 | holes | `hole_gen.py` + `placer.py` | Generation + placement 18 trous | OK |
| 3 | hazards | (a creer) | Bunkers, eau, iles, ravins | TODO |
| 4 | vegetation | (a creer) | Forets, arbres entre les trous | TODO |
| 5 | features | (a creer) | Ponts, ruisseaux | TODO |

## Config (dataclasses)

- `CourseConfig` : width=350, height=350, seed=42, num_holes=18
- `TerrainConfig` : octaves, persistence, scale, elevation_min/max, base_elevation, ns_gradient
- `RoutingConfig` : par_distribution, ranges par3/4/5, fairway widths, green radius, tee_link_distance, grid_margin
