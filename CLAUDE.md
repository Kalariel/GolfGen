# CLAUDE.md

## Projet

**GolfGen** — Editeur interactif de parcours de golf pour Minecraft. Application web pure (HTML/JS/CSS), deployable sur GitHub Pages. L'utilisateur genere un terrain procedural puis dessine les trous directement sur le canvas.

## Lancer le projet

Ouvrir `index.html` dans un navigateur. Aucune dependance locale — simplex-noise est integre inline dans `terrain.js`. Google Fonts charge via CDN.

## Architecture

```
index.html      # Page unique, scripts classiques (pas ES modules)
style.css       # Theme sombre (Silkscreen + IBM Plex Mono)
app.js          # Rendu canvas principal + Hole Editor overlay (rendering/events)
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
5. **Vue pixel** : toggle "Vue pixel" → rendu bloc-par-bloc 350x350 avec zones inter-trous resolues par priorite
6. **Facilities** : clubhouse, putting green, practice (drag pour rectangle)
7. **Hole Editor** : overlay plein ecran — bunkers, eau, arbres, cart path par trou
   - Dessin point-par-point ou freehand → lissage Chaikin automatique a la validation
   - Rendu bloc-par-bloc par trou (cache offscreen, 1px = 1 bloc Minecraft)
8. **Block map globale** : 350x350 Uint8Array, zones resolues tous trous confondus, debounce 300ms
9. **Export JSON** : inclut `block_map` (base64_uint8, zones indexees)
10. **Import JSON** : facilities importees AVANT les trous (bug fix ordre critique)
11. **Autosave** : localStorage (seed + trous + features + facilities)
12. **Escape** : annule l'action locale la plus proche (poly en cours → feature type → ferme HE → annule dessin → deselectionne)

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

### Block map exportee
```json
"block_map": {
  "width": 350, "height": 350,
  "zones": ["rough","semi_rough","fairway","cart_path","tree","water","bunker","green_fringe","green","tee"],
  "encoding": "base64_uint8",
  "data": "..."
}
```

## Deux systemes de camera

| | Canvas principal | Hole Editor |
|---|---|---|
| Zoom | `camZoom` | `heCamZoom` |
| Pan | `camPanX/Y` | `heCamPanX/Y` |
| World→Screen | `toCanvas(wx,wy)` | `toHeCanvas(wx,wy)` |
| Screen→World | `toWorld(sx,sy)` | `fromHeCanvas(sx,sy)` |

## Fonctions cles utils.js

- `polylineLength`, `autoPar`, `autoFairwayWidth`, `directionLabel`
- `pointToSegDist`, `pointInPolygon` (ray casting)
- `simplifyRDP` (Ramer-Douglas-Peucker)
- `smoothChaikin(points, iterations, closed)` — lissage coin-coupant

## Fonctions cles editor.js

- `getHoles()`, `getSelectedHoleId()`, `getEditorMode()`
- `getHoleZoneAt(h, bx, by)` — zone d'un bloc pour un trou (priorite tee→green→bunker→eau→arbre→cart_path→fairway→semi_rough→rough)
- `getHoleBBox(h)` — bounding box etendue pour culling
- `getGlobalZoneAt(bx, by, holes, bboxes)` — zone globale tous trous confondus (merge par priorite)
- `ZONE_PRIORITY` — objet de priorite par zone
- Callbacks : `editorSetOnChange`, `editorSetDrawCallback`, `heSetDrawCallback`

## Fonctions cles app.js

- `draw()` — canvas principal : mode pixel ou vectoriel selon `show.pixel`
- `drawRouting(overlayOnly=false)` — si overlayOnly : skip fairway/green/tee/features, garde glow+flag+numero+handles
- `drawPixelMap()` — affiche `mainPixelCache` (350x350) mise a l'echelle
- `buildCourseBlockMap()` — construit `courseBlockMap` (Uint8Array) + `mainPixelCache` (canvas colore)
- `scheduleBlockMapRebuild()` — debounce 300ms, appele par `onEditorChange`
- `buildHoleBlockCache(h)` — cache offscreen pour le Hole Editor (1px=1bloc, bounding box du trou)
- `drawHoleEditor()` — fond pixel + trous adjacents vecteur + overlay waypoints/flag + poly/freehand en cours + grille
- `openHoleEditor(holeId)` / `closeHoleEditor()` — gestion overlay + camera + events
- `onKeyDown` — gestion Escape avec priorites contextuelles

## Pattern callbacks (editor.js → app.js)

- `editorSetOnChange(fn)` → `onEditorChange()` : sync routing + autosave + scheduleBlockMapRebuild + invalidation heBlockCache si HE ouvert
- `editorSetDrawCallback(fn)` → `draw()` canvas principal
- `heSetDrawCallback(fn)` → `drawHoleEditor()` canvas overlay

## Invalidation des caches

- `heBlockCache` (Hole Editor) : null dans `openHoleEditor`, `heDeleteFeature`, `onEditorChange` (si HE ouvert)
- `mainPixelCache` / `courseBlockMap` : null dans `buildCourseBlockMap` si 0 trous ; reconstruit via debounce

## Pieges connus

- **Import JSON** : toujours importer `facilities` AVANT `holes` dans `loadCourseData`. `importHoles` appelle `_onChangeCallback` → `syncRouting` → ecrase `courseData.routing` (meme reference que le JSON parse). Les facilities du JSON sont alors perdues.
- **Scripts non-ES modules** : pas de `import/export`, pas besoin de `window.fn = fn`. Toutes les fonctions definies avec `function` sont globales.
- **Simplex noise** : integre inline dans `terrain.js`, pas de CDN.
- **addEventListener dedup** : utiliser des fonctions nommees pour pouvoir appeler `removeEventListener`. Le flag `alreadyOpen` evite de re-enregistrer les listeners du HE quand on navigue entre trous.

## Conventions

- JS : scripts classiques vanilla, fonctions globales, pas de framework
- CSS : variables CSS, theme sombre
- Interface : francais
- Palette : objet `C` dans app.js (rough, fairway, green, tee, sand, water, etc.)
- Separation etat/rendu : `editor.js` = etat pur, `app.js` = rendu + events
