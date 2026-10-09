# Format JSON 3.0 — parcours Muirfield

Référence du JSON produit par `golfgen.exporter.muirfield_to_dict(result,
heightmap, *, seed, seed_input=None)` et lu par le viewer (R6). Le format 2.0
(`JSONExporter`, routeur `loop_router`) reste en place jusqu'au R7 ; seul le
bloc `terrain` est commun aux deux formats.

`muirfield_to_dict` est pure (ni I/O, ni état global, ni aléa) : même entrée,
même dict. Le dict passe `json.dumps` sans encodeur (aucun type numpy).

## Conventions

- **Unité** : le bloc Minecraft (`block_m` = 3 m par bloc) pour toutes les
  coordonnées, longueurs et largeurs.
- **Repère** : origine en haut à gauche de la carte, `x` vers la droite
  (0..`width`), `y` vers le BAS (0..`height`), comme une image : la ligne `y`
  de la heightmap est la ligne `y` de la carte.
- **Flottants** arrondis à 2 décimales (coordonnées, longueurs, largeurs,
  côtés de carte, `elapsed_seconds`, totaux).
- Les objets ont des clés nommées (pas de tableaux nus) pour pouvoir recevoir
  des champs plus tard sans casser les lecteurs.
- Aucun `waypoints` : les liaisons sont des segments droits.

## `metadata`

| Champ | Type | Unité / valeurs |
|---|---|---|
| `version` | chaîne | `"3.0"` |
| `generator` | chaîne | `"golfgen <version du paquet>"` (`golfgen.__version__`, égal à `setup.py`) |
| `seed` | chaîne | entier signé tel que saisi, en décimal (`str(seed)`) ; voir plus bas |
| `seed_input` | chaîne ou `null` | texte d'origine saisi par l'utilisateur, sinon `null` |
| `pattern.requested` | chaîne | `"muirfield"`, `"muirfield_inverse"` ou `"random"` |
| `pattern.resolved` | chaîne | `"muirfield"` ou `"muirfield_inverse"` (patron effectif) |
| `orientation` | chaîne | `"landscape"` si `width > height`, `"portrait"` si `width < height`, `"square"` si égaux |
| `short_side`, `long_side` | nombre | blocs : `min` / `max` de (`width`, `height`) |
| `width`, `height` | nombre | blocs : dimensions de la carte |
| `block_m` | entier | mètres par bloc (3) |
| `stats` | objet | voir ci-dessous |

`stats` :

| Champ | Type | Unité |
|---|---|---|
| `front`, `back` | objet | `{holes_length, links_length, total, par}` du nine : longueurs en blocs (axes des trous, liaisons, somme), par du nine |
| `total` | nombre | blocs : longueur totale (trous + liaisons, 18 trous) |
| `par` | entier | par du parcours (72) |
| `elapsed_seconds` | nombre | secondes de construction du routage |
| `relaunches` | entier | relances (tentatives réelles − 1) |

## `terrain`

Identique au format 2.0 (même fonction `terrain_block`).

| Champ | Type | Unité |
|---|---|---|
| `width`, `height` | entier | pixels = blocs (colonnes, lignes) |
| `elevation.encoding` | chaîne | `"base64_uint8"` |
| `elevation.data` | chaîne | base64 de `width × height` octets, ligne par ligne (`y` puis `x`) ; 0..255 normalisé sur [min, max] (tout à 0 si le relief est plat) |
| `elevation.min_elevation`, `elevation.max_elevation` | nombre | altitude min / max (unités de la heightmap), 2 décimales |

Altitude d'un pixel : `min + octet / 255 × (max − min)`.

## `routing`

### `clubhouse`

`{x, y, edge}` : position en blocs ; `edge` ∈ `"N"`, `"E"`, `"S"`, `"W"` est le
bord de carte sur lequel il est posé (`N` = `y` petit, `W` = `x` petit).

### `direction`

| Champ | Valeurs |
|---|---|
| `outer_nine` | `"front"` (patron `muirfield`) ou `"back"` (`muirfield_inverse`) : nine qui fait le grand tour extérieur |
| `outer_turn` | `"clockwise"` ou `"counterclockwise"` : sens de rotation du nine extérieur autour du centre de carte, **tel qu'affiché** (y vers le bas) |
| `inner_nine` | l'autre nine (boucle intérieure) |
| `inner_turn` | toujours le sens inverse de `outer_turn` |

Dérivation : `Plan.direction` vaut `+1` ou `−1` (angle croissant ou décroissant
autour du centre dans le repère de la carte). Avec `y` vers le bas, `+1` est le
sens horaire à l'écran. Vérifié sur les trous réels (aire signée du polygone
clubhouse → tees/greens du nine, test `test_direction_matches_geometry`).

### `holes[]`

18 objets triés par `id` (1..18) :

| Champ | Type | Unité |
|---|---|---|
| `id` | entier | numéro du trou (ordre de jeu) |
| `nine` | chaîne | `"front"` (1–9) ou `"back"` (10–18) |
| `par` | entier | 3, 4 ou 5 |
| `length` | nombre | blocs : longueur de l'axe tee → doglegs → green |
| `width` | nombre | blocs : largeur TOTALE du fairway |
| `tee`, `green` | `{x, y}` | blocs |
| `doglegs` | liste de `{x, y}` | blocs : points de coude de l'axe, dans l'ordre (0 à 2) |

### `links[]`

20 liaisons à pied dans l'ordre de jeu : clubhouse → 1, 1 → 2, …, 9 →
clubhouse, clubhouse → 10, …, 18 → clubhouse.

| Champ | Type | Unité |
|---|---|---|
| `from`, `to` | entier ou `"clubhouse"` | numéro de trou, ou `"clubhouse"` ; une liaison part du green de `from` et arrive au tee de `to` |
| `length` | nombre | blocs : distance euclidienne (segment droit) |

## Exemple (seed 4, 400×300, `random`, tronqué)

```json
{
  "metadata": {
    "version": "3.0", "generator": "golfgen 0.0.2",
    "seed": "4", "seed_input": "4",
    "pattern": {"requested": "random", "resolved": "muirfield_inverse"},
    "orientation": "landscape", "short_side": 300.0, "long_side": 400.0,
    "width": 400.0, "height": 300.0, "block_m": 3,
    "stats": {
      "front": {"holes_length": 798.8, "links_length": 354.6, "total": 1153.39, "par": 34},
      "back": {"holes_length": 1049.84, "links_length": 309.55, "total": 1359.39, "par": 38},
      "total": 2512.78, "par": 72, "elapsed_seconds": 0.31, "relaunches": 0
    }
  },
  "terrain": {
    "width": 400, "height": 300,
    "elevation": {"encoding": "base64_uint8", "data": "o621u8DDx8nMz9LU…",
                  "min_elevation": 58.0, "max_elevation": 82.0}
  },
  "routing": {
    "clubhouse": {"x": 6.0, "y": 131.68, "edge": "W"},
    "direction": {"outer_nine": "back", "outer_turn": "clockwise",
                  "inner_nine": "front", "inner_turn": "counterclockwise"},
    "holes": [
      {"id": 1, "nine": "front", "par": 4, "length": 102.0, "width": 15.0,
       "tee": {"x": 44.23, "y": 137.06}, "green": {"x": 121.06, "y": 192.09},
       "doglegs": [{"x": 101.31, "y": 154.75}]}
    ],
    "links": [
      {"from": "clubhouse", "to": 1, "length": 38.61},
      {"from": 1, "to": 2, "length": 28.93}
    ]
  }
}
```

## Pourquoi la seed est une chaîne

La seed est un entier signé 64 bits (de −2^63 à 2^63 − 1). Un `Number`
JavaScript (double IEEE 754) n'est exact que jusqu'à 2^53 : `JSON.parse`
arrondirait silencieusement les grandes seeds, et le viewer afficherait ou
renverrait une seed qui ne reproduit pas le parcours. En chaîne décimale, elle
fait l'aller-retour exact. `seed` est l'entier tel que saisi (signe compris) ;
sa normalisation éventuelle (u64) relève du pipeline (R5), pas du format.
`seed_input` garde en plus le texte brut quand l'entrée n'était pas un entier.

Le pipeline (`pipeline.py`, `golfgen/seed.py`) le garantit : la saisie
(`--seed` ou `seed` du JSON de config) est lue comme Minecraft Java,
`Long.parseLong` si elle réussit, sinon `String.hashCode()` (entier signé
32 bits sur les unités UTF-16), ce qui donne toujours un entier de
[−2^63, 2^63 − 1] ; `seed_input` est alors le texte haché, et `null` dès que
`Long.parseLong` a réussi (même pour `"-007"` ou `"+5"`). Le routage reçoit
`seed & 0xFFFF_FFFF_FFFF_FFFF` (égal à `seed` si `seed ≥ 0`).

## Extension

- **Ajouts de champs = version mineure** (`3.1`, `3.2`, …) : un lecteur 3.x
  ignore les clés qu'il ne connaît pas, et aucun champ existant ne change de
  type, d'unité ou de sens. Retirer ou redéfinir un champ = `4.0`.
- **Une section par couche** pour le façonnage à venir : les formes s'ajoutent
  sur les objets existants (`holes[].green.outline`, `holes[].tee.outline`,
  `holes[].fairway`…) et chaque nouvelle couche indépendante arrive dans sa
  propre section de premier niveau ou de `routing` (`bunkers`, `trees`,
  `water`…), absente tant que l'étape correspondante n'est pas implémentée.
  Un lecteur teste la présence de la section au lieu de supposer une version.
- Mêmes conventions pour tout ajout : blocs, repère `y` vers le bas, flottants
  à 2 décimales, objets à clés nommées.
