# CLAUDE.md

## Projet

**GolfGen** — Editeur interactif de parcours de golf pour Minecraft. Application web pure (HTML/JS/CSS), deployable sur GitHub Pages. L'utilisateur genere un terrain procedural puis dessine les trous directement sur le canvas.

## Lancer le projet

Ouvrir `index.html` dans un navigateur. Aucune dependance locale — simplex-noise est integre inline dans `terrain.js`. Google Fonts charge via CDN.

## Architecture

```
index.html      # Page unique, scripts classiques (pas ES modules)
style.css       # Theme sombre (Silkscreen + IBM Plex Mono)
app.js          # Rendu canvas principal + Hole Editor overlay + Vue Loupe (rendering/events)
terrain.js      # Generation terrain OpenSimplex multi-octave (inline, pas de CDN)
editor.js       # Tout l'etat : trous, facilities, hole editor (he*), zones globales
utils.js        # Utilitaires math/geometrie
CLAUDE.md
.claude/commands/   # Skills personnalises : sync-docs, check-globals
```

Ordre de chargement : `utils.js` → `terrain.js` → `editor.js` → `app.js`

## Fonctionnalites

1. **Generation terrain** : OpenSimplex 6 octaves, gradient N-S, seed configurable, grille 350x350
2. **Dessin de trous** : clic gauche = waypoints, double-clic = finir, freehand (glisser)
3. **Calculs auto** : par (longueur), largeur fairway, direction
4. **Rendu vectoriel** : terrain colore, fairways, greens, tees, drapeaux, numeros, grille
5. **Vue pixel** : toggle "Vue pixel" → rendu bloc-par-bloc 350x350 + legende zones dans la sidebar
6. **Facilities** : clubhouse, putting green, practice (drag pour rectangle, resize 8 poignees, DnD reorder trous)
7. **Hole Editor** : overlay plein ecran — bunkers, eau, arbres, cart path par trou
   - Dessin point-par-point ou freehand → lissage Chaikin automatique a la validation
   - Rendu bloc-par-bloc par trou (cache offscreen, 1px = 1 bloc Minecraft)
8. **Block map globale** : 350x350 Uint8Array, zones resolues tous trous confondus, debounce 300ms
9. **Arbres de decor global** : generation clusterisee (biomes 40x40, grille 4x4, distance min 3 blocs) dans rough/semi_rough uniquement ; pixel central marron `#6b3a1f` ; slider de densite ; persistance autosave + export JSON (`decor_trees`)
10. **Vue loupe** : affiche 50x50 blocs du courseBlockMap, navigation fleches/WASD/drag, etiquettes coords Minecraft, legende
11. **Export JSON** : inclut `block_map` (base64_uint8, zones indexees) + `decor_trees` [{x,y}]
12. **Import JSON** : facilities importees AVANT les trous (bug fix ordre critique)
13. **Autosave** : localStorage (seed + trous + features + facilities + decorTrees)
14. **Escape** : annule l'action locale la plus proche (loupe → poly HE → feature type → ferme HE → toggle draw → deselectionne)

## Modele de donnees

### Trou
```js
h = {
  id, par, blocks, direction, fairwayWidth, greenRadius,
  points: [{x, y}],   // waypoints
  features: {
    bunkers:       [{ id, points: [{x,y}] }],  // polygone lisse Chaikin (min 3 pts)
    water_hazards: [{ id, points: [{x,y}] }],  // polygone lisse Chaikin (min 3 pts)
    trees:         [{ id, x, y }],             // points individuels
    cart_path:     { points: [{x,y}] } | null, // polyligne lisse Chaikin (min 2 pts)
  }
}
```

### Facility
```js
f = { id, type: 'clubhouse'|'putting_green'|'practice', x, y, w, h }
```

### Block map exportee
```json
"block_map": {
  "width": 350, "height": 350,
  "zones": ["rough","semi_rough","fairway","cart_path","tree","water","bunker","green_fringe","green","tee"],
  "encoding": "base64_uint8",
  "data": "..."
},
"decor_trees": [{"x": 12, "y": 34}, ...]
```

## Deux systemes de camera

| | Canvas principal | Hole Editor |
|---|---|---|
| Zoom | `camZoom` | `heCamZoom` |
| Pan | `camPanX/Y` | `heCamPanX/Y` |
| World→Screen | `toCanvas(wx,wy)` | `toHeCanvas(wx,wy)` |
| Screen→World | `toWorld(sx,sy)` | `fromHeCanvas(sx,sy)` |

## Fonctions cles utils.js

- `polylineLength(points)`, `autoPar(blocks)`, `autoFairwayWidth(par)`, `directionLabel(from, to)`
- `pointToSegDist(px, py, ax, ay, bx, by)`, `pointInPolygon(px, py, points)` (ray casting)
- `simplifyRDP(points, epsilon)` (Ramer-Douglas-Peucker)
- `smoothChaikin(points, iterations, closed)` — lissage coin-coupant

## Fonctions cles terrain.js

- `mulberry32(seed)` — PRNG seeded (retourne fonction `rng()` → float [0,1))
- `createNoise2D(rng)` — ferme OpenSimplex 2D
- `generateTerrain(config)` → `{ heightmap: Uint8Array, width, height, minElevation, maxElevation }`

## Fonctions cles editor.js

- `getHoles()`, `getSelectedHoleId()`, `getEditorMode()`, `getCurrentHole()`
- `getFacilities()`, `getFacilityMode()`, `getSelectedFacilityId()`
- `getHeEditingHoleId()`, `getHeFeatureType()`, `getHeCurrentPoly()`
- `getHoleZoneAt(h, bx, by)` — zone d'un bloc (priorite tee→green→bunker→eau→arbre→cart_path→fairway→semi_rough→rough)
- `getGlobalZoneAt(bx, by, holes, bboxes)` — zone globale tous trous (merge par priorite)
- `getHoleBBox(h)` — bounding box etendue pour culling
- `ZONE_PRIORITY = {rough:0, semi_rough:1, fairway:2, cart_path:3, tree:4, water:5, bunker:6, green_fringe:7, green:8, tee:9}`
- `importHoles(routingHoles)`, `importFacilities(arr)`, `buildRoutingData()`
- Callbacks : `editorSetOnChange(fn)`, `editorSetDrawCallback(fn)`, `heSetDrawCallback(fn)`

## Fonctions cles app.js

- `draw()` — canvas principal : mode pixel ou vectoriel selon `show.pixel`
- `drawRouting(overlayOnly=false)` — si overlayOnly : skip fairway/green/tee/features, garde glow+flag+numero+handles
- `drawPixelMap()` — affiche `mainPixelCache` (350x350) mise a l'echelle
- `buildCourseBlockMap()` — construit `courseBlockMap` (Uint8Array) + `mainPixelCache` + integre `globalDecorTrees`
- `scheduleBlockMapRebuild()` — debounce 300ms, appele par `onEditorChange`
- `generateDecorTrees()` — algo clusterise, lit slider `#tree-density-input`, necessite `courseBlockMap` existant
- `clearDecorTrees()` — vide `globalDecorTrees` + rebuild
- `buildHoleBlockCache(h)` — cache offscreen pour le Hole Editor (1px=1bloc, bounding box du trou)
- `drawHoleEditor()` — fond pixel + trous adjacents vecteur + overlay waypoints/flag + poly/freehand en cours + grille
- `openHoleEditor(holeId)` / `closeHoleEditor()` — gestion overlay + camera + events
- `buildZoneLegend(container)` — peuple un container DOM avec swatches + labels (utilise par loupe ET vue pixel)
- `buildLoupeLegend()`, `buildPixelLegend()` — wrappers de `buildZoneLegend`
- `onKeyDown` — gestion Escape avec priorites contextuelles

## Constantes app.js

```js
ZONE_INDEX = ['rough','semi_rough','fairway','cart_path','tree','water','bunker','green_fringe','green','tee']
ZONE_TO_IDX = { rough:0, semi_rough:1, ... }  // inverse de ZONE_INDEX

HE_ZONE_COLORS = {
  tee:'#4ecf5f', green:'#3dbd4e', green_fringe:'#4db84a',
  fairway:'#6aad45', semi_rough:'#4a8632', rough:'#2e5420', rough_alt:'#263f1a',
  bunker:'#e8d68a', water:'#3b8bba',
  tree:'#6b3a1f',        // marron tronc — utilise pour rendu pixel, loupe et decor trees
  cart_path:'#a08b6e',
}
```

## Pattern callbacks (editor.js → app.js)

- `editorSetOnChange(fn)` → `onEditorChange()` : sync routing + autosave + scheduleBlockMapRebuild + invalidation heBlockCache si HE ouvert
- `editorSetDrawCallback(fn)` → `draw()` canvas principal
- `heSetDrawCallback(fn)` → `drawHoleEditor()` canvas overlay

## Invalidation des caches

- `heBlockCache` (Hole Editor) : null dans `openHoleEditor`, `heDeleteFeature`, `onEditorChange` (si HE ouvert)
- `mainPixelCache` / `courseBlockMap` : null dans `buildCourseBlockMap` si 0 trous ; reconstruit via debounce
- `terrainCache` : reconstruit dans `buildTerrainCache()` (appele si toggle water ou nouveau terrain)

## Pieges connus

- **Import JSON** : toujours importer `facilities` AVANT `holes` dans `loadCourseData`. `importHoles` appelle `_onChangeCallback` → `syncRouting` → ecrase `courseData.routing` (meme reference que le JSON parse). Les facilities du JSON sont alors perdues.
- **Arbres decor** : `generateDecorTrees()` necessite `courseBlockMap` deja construit (au moins 1 trou dessiné). Retour early sinon.
- **Scripts non-ES modules** : pas de `import/export`, pas besoin de `window.fn = fn`. Toutes les fonctions definies avec `function` sont globales.
- **Simplex noise** : integre inline dans `terrain.js`, pas de CDN.
- **addEventListener dedup** : fonctions nommees obligatoires pour `removeEventListener`. Flag `alreadyOpen` evite de re-enregistrer les listeners du HE quand on navigue entre trous.
- **heBlockCache** : invalider dans `openHoleEditor`, `heDeleteFeature`, et `onEditorChange` (si HE ouvert).

## Conventions

- JS : scripts classiques vanilla, fonctions globales, pas de framework
- CSS : variables CSS, theme sombre
- Interface : francais
- Palette rendu vectoriel : objet `C` dans app.js ; rendu pixel : `HE_ZONE_COLORS`
- Separation etat/rendu : `editor.js` = etat pur, `app.js` = rendu + events
