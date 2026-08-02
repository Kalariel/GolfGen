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
├── clubhouse.py            # pick_clubhouse — position du clubhouse (coin determine par seed)
├── hole_gen.py             # resolve_par_distribution — pars du parcours (patron corrige)
├── loop_router.py          # build_course_loop — routing par ruban serpentin + decoupage DP
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
├── test_terrain.py         # Tests de regression terrain (seed 42)
├── test_hole_gen.py        # Tests distribution des pars
└── test_loop_router.py     # Tests d'invariants du routing (croisements, liaisons, angles)

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
- **Clubhouse** : place automatiquement dans un coin (determine par seed, `clubhouse.py`), pas force au centre
- **Routing par ruban** (`loop_router.py`, remplace les anciens solveurs GA puis beam+rotules, retires) — « la courbe d'abord, les trous ensuite » :
  1. **Spine** : boustrophedon dans chaque triangle de la diagonale du coin clubhouse (repere (u, v) le long des deux murs), virages remplaces par des conges en arc (pas <= 22 deg)
  2. **Ruban** : contour offset (±SPINE_OFFSET) de la spine, cap en demi-cercle au bout — courbe simple par construction, donc zero croisement ; clairance, exclusion clubhouse et fenetre de longueur verifiees numeriquement, on retire le tirage sinon (quelques ms)
  3. **Decoupage** (programmation dynamique) : le ruban est tranche en stub clubhouse → trou 1 → liaison → ... → trou 9 → stub. Les regles d'angles sont appliquees ici : les epingles tombent sur les liaisons, jamais dans un trou
  4. **Assemblage** : ids, elevations, direction — format final pour l'exporter (dans `build_course_loop`)
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
| 2 | holes | `loop_router.py` (+ `hole_gen.py` pour les pars) | Rubans serpentins + decoupage DP (18 trous, ~0.2s) | OK |
| 3 | hazards | (a creer) | Bunkers, eau, iles, ravins — peut consommer les trous deja positionnes/orientes par `loop_router.py` | TODO |
| 4 | vegetation | (a creer) | Forets, arbres entre les trous | TODO |
| 5 | features | (a creer) | Ponts, ruisseaux | TODO |

## Config (dataclasses)

- `CourseConfig` : width=350, height=350, seed=42, num_holes=18
- `TerrainConfig` : octaves, persistence, scale, elevation_min/max, base_elevation, ns_gradient
- `RoutingConfig` : par_distribution (patron corrige automatiquement pour respecter total_par), ranges par3/4/5, fairway widths, green radius, tee_link_min/max, grid_margin, clubhouse_margin

## Invariants du routing actuel

- zero croisement et zero chevauchement de fairways : garantis par construction (courbe simple + clairance), pas par penalites
- `total_par` respecte exactement, sommes 36+36 par nine ; l'ORDRE des pars d'un nine est un patron prefere, permutable par le decoupage si le patron ne s'aligne pas sur le ruban
- toutes les liaisons jouables green→tee ont une corde euclidienne dans `[tee_link_min, tee_link_max]` ; 9→10 est exclue car le joueur repasse par le clubhouse ; l'ARC d'une liaison le long du ruban peut enjamber une epingle (jusqu'a LINK_ARC_MAX)
- regles d'angles dans un trou : aucun virage > MAX_CORNER_DEG (~100 deg), courbure nette cumulee (somme signee) <= MAX_NET_DEG — un trou ne se replie jamais sur lui-meme, les epingles vont aux liaisons
- marge de carte = demi-fairway (EDGE_MARGIN) : les fairways touchent la bordure, seule contrainte = rester dans le perimetre
- la fenetre de comptage des virages du decoupage est alignee EXACTEMENT sur le seuil de nettoyage des sommets (0.75) de `_sub_polyline` — les desaligner fait diverger la courbure nette exportee
- exports en 2 decimales : les segments d'arc font ~3 blocs, arrondir a 0.1 fausse les angles
