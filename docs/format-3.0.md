# Format JSON 3.0 — parcours Muirfield (et extension 3.1 : habillage)

Référence du JSON produit par `golfgen.exporter.muirfield_to_dict(result,
heightmap, *, seed, seed_input=None, dressing=None)` et lu par le viewer
(`viewer/`, qui refuse tout `metadata.version` hors 3.x). Sans `dressing`, le
dict est du 3.0 ; avec, du 3.1 (section « Extension 3.1 » plus bas), que
`pipeline.py` écrit toujours.

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
| `version` | chaîne | `"3.0"` (`"3.1"` avec habillage) |
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

Relief encodé par `golfgen.exporter.terrain_block`, plus `water_level`.

| Champ | Type | Unité |
|---|---|---|
| `width`, `height` | entier | pixels = blocs (colonnes, lignes) |
| `elevation.encoding` | chaîne | `"base64_uint8"` |
| `elevation.data` | chaîne | base64 de `width × height` octets, ligne par ligne (`y` puis `x`) ; 0..255 normalisé sur [min, max] (tout à 0 si le relief est plat) |
| `elevation.min_elevation`, `elevation.max_elevation` | nombre | altitude min / max (unités de la heightmap), 2 décimales |
| `water_level` | nombre | niveau d'eau (mêmes unités que `min_elevation`/`max_elevation`) : un pixel d'altitude strictement inférieure est de l'eau, pour le routeur (`golfgen.routing.sites.WATER_LEVEL`), les planches PNG et le viewer ; peut être hors de [min, max] (aucune eau) |

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
    "version": "3.0", "generator": "golfgen 0.1.0",
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
                  "min_elevation": 58.0, "max_elevation": 82.0},
    "water_level": 60.0
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
(`--seed` ou `seed` du JSON de config) est lue comme Minecraft Java : blancs
de tête et de queue retirés (`String.trim()`, `" 42 "` vaut 42 ; vide après
trim → seed par défaut), puis `Long.parseLong` si elle réussit (chiffres du
plan de base Unicode seulement), sinon `String.hashCode()` du texte trimé
(entier signé 32 bits sur les unités UTF-16), ce qui donne toujours un entier
de [−2^63, 2^63 − 1] ; `seed_input` est alors le texte tel que saisi (non
trimé), et `null` dès que `Long.parseLong` a réussi (même pour `"-007"` ou
`"+5"`). Le routage reçoit
`seed & 0xFFFF_FFFF_FFFF_FFFF` (égal à `seed` si `seed ≥ 0`).

## Extension 3.1 : habillage

Ajout strictement additif (règle ci-dessous) : un lecteur 3.0 lit un 3.1 en
ignorant les nouvelles clés. Produit quand `muirfield_to_dict` reçoit
`dressing` (`golfgen.dressing.dress_course(result, *, seed, style)`), ce que
fait toujours `pipeline.py`.

| Champ | Type | Unité / valeurs |
|---|---|---|
| `metadata.version` | chaîne | `"3.1"` |
| `metadata.style` | chaîne | `"links"` ou `"parkland"` (`--style`, défaut `links`) |
| `routing.holes[].features` | objet | habillage du trou ; une clé par élément (aujourd'hui `green` ; `tees`, `double_green` à venir) |
| `features.green.outline` | liste de `{x, y}` | blocs : contour du green, 32 sommets, polygone simple fermé implicitement |
| `features.green.center` | `{x, y}` | blocs : centre de la forme (sur l'axe, reculé depuis le drapeau vers l'approche de `max(r, avant − width/2 + 0,5)`, `r` tiré dans 0–1,5 bloc et `avant` l'étendue de la forme devant son centre, puis suivi de la réduction éventuelle) |
| `features.green.area` | nombre | blocs² : aire du contour tel qu'exporté |

Invariants :

- **green ⊂ cœur** : le contour est inclus dans le cœur du trou,
  `buffered_axis(axe, width / 2)` (`golfgen.routing.geometry`) ; s'il en
  sortait, la forme est réduite par homothétie ×0,95 centrée sur le drapeau
  jusqu'à inclusion (contrôle fait sur les coordonnées arrondies).
- Le contour **contient le drapeau** (`holes[].green`).
- Aire signée positive dans le repère (x, y) (sens horaire à l'écran, `y`
  vers le bas). Aire visée : voir « Formes et tailles » ; une forme réduite
  est plus petite.
- **Le tracé ne dépend pas de l'habillage** : `routing` sans les clés
  `features` est identique octet pour octet au 3.0 de la même seed, quel que
  soit le style (aléa de l'habillage sur un flux séparé).
- Un lecteur teste la présence de `features` (et de chacune de ses clés)
  plutôt que la version.

### Formes et tailles des greens (3.1)

Le JSON ne porte que le contour : le type de green n'est pas exporté.
Constantes dans `golfgen/dressing/model.py` (`STYLE_SPECS`) et
`golfgen/dressing/green.py` ; chiffres mesurés sur 30 seeds × 2 formats
(400×300 et 300×400, patron `random`, 1080 trous par style ; détail dans
`tools/dressing/output/green_shapes/report.json`).

- **Types** : rond, allongé, haricot. Rond et allongé : ellipse dont le
  grand axe suit l'approche (dernier segment de l'axe, écart mesuré ≤ 15°),
  petit axe ≥ 5,5 blocs, déformée par l'harmonique 3 seule (links ≤ 12 %,
  parkland ≤ 6 %). Allongement : rond 1,0–1,3 ; allongé 1,45–1,9 en links,
  1,45–1,75 en parkland (mesuré ≥ 1,44).
- **Haricot : capsule courbée.** Stade de largeur `w` (bouts en
  demi-cercles) dont l'axe médian est un arc de cercle de flèche `s`, corde
  dans l'axe de l'approche, creux d'un côté tiré. `λ` = longueur dépliée /
  largeur, tiré dans 2,15–2,24 dans les deux styles ; `w` vient de l'aire
  visée (`aire = w·(λ − 1)·w + π·w²/4`), `λ` plafonné pour que `w` ≥ 5,5
  blocs : le **col** (largeur au droit du creux, perpendiculaire à
  l'approche) vaut `w`. Le **creux** (distance du contour à son enveloppe
  convexe) vaut la flèche `s`, tirée dans 1,5–2,0 blocs dans les deux
  styles. Harmonique 3 au poids ×0,5 (à ×1, elle refait des lobes) ; elle
  déplace le creux, recalé sur `s` par sécante (4 évaluations au plus,
  ±0,01 bloc ; mesuré 1,505–2,0, à l'arrondi des coordonnées près).
  Allongement mesuré (moment d'inertie) : links 1,53–1,96, médiane 1,74 ;
  parkland 1,53–1,88, médiane 1,70 (≤ 2,0 : au-delà, saucisse ; plus que
  l'ancienne encoche, inhérent à la capsule). Correspondance `λ` →
  allongement médian (haricots forcés, `λ` fixe, links / parkland) : 2,1 →
  1,67 / 1,63 ; 2,2 → 1,75 / 1,70 ; 2,3 → 1,85 / 1,80 ; 2,4 → 1,95 / 1,90.
  Le green **bascule** en allongé, sans tolérance, et la cause est comptée :
  creux inatteignable (arc intérieur inexistant ; cause légitime, au même
  titre que le col), recalage du creux non convergé, ou, une fois placé, col
  < 5,5 blocs ou creux rendu en blocs < 1 bloc.
- **Éligibilité** : un haricot exige un grand green, aire visée ≥ 84
  blocs² (links) ou 77 (parkland) ; seuils validés, conservés (la capsule
  tiendrait la bascule ≤ 5 % dès 74 et 72). Bascules mesurées sur les
  haricots tirés : links 3/370 (0,8 %, creux inatteignable), parkland 9/317
  (2,8 % : 8 creux inatteignables, 1 creux rastérisé).
- **Parts nettes visées** (après bascules) : links rond 0,30 / allongé 0,35 /
  haricot 0,35 ; parkland 0,30 / 0,40 / 0,30 (mesuré 0,288 / 0,372 / 0,340
  et 0,297 / 0,418 / 0,285). Tirage : haricot avec
  P_eff = part visée / (part d'éligibles × (1 − bascule)) parmi les
  éligibles (links 0,35 / (0,506 × 0,993) = 0,696 ; parkland 0,30 /
  (0,384 × 0,976) = 0,800) ; sinon rond avec la probabilité
  `round_given_plain` (0,463 et 0,433, calée pour que les bascules, comptées
  en allongés, ne fassent pas dériver la part des ronds), allongé sinon.
- **Tailles (provisoires)** : `ρ` = diamètre du disque de même aire / largeur
  `width` du cœur, dans links 0,68–0,85, parkland 0,62–0,76, à mi-chemin
  entre la longueur normalisée du trou et un tirage ; aire visée
  `π/4·(ρ·width)²` bornée à links 50–135 blocs², parkland 42–105. Retour aux
  plages fixes 60–95 / 50–75 si les bunkers ne passent pas.

## Extension

- **Ajouts de champs = version mineure** (`3.1`, `3.2`, …) : un lecteur 3.x
  ignore les clés qu'il ne connaît pas, et aucun champ existant ne change de
  type, d'unité ou de sens. Retirer ou redéfinir un champ = `4.0`.
- **Une section par couche** pour le façonnage à venir : les formes d'un trou
  s'ajoutent sous `holes[].features` (`green` en 3.1, puis `tees`,
  `double_green`…) et chaque nouvelle couche indépendante arrive dans sa
  propre section de premier niveau ou de `routing` (`bunkers`, `trees`,
  `water`…), absente tant que l'étape correspondante n'est pas implémentée.
  Un lecteur teste la présence de la section au lieu de supposer une version.
- Mêmes conventions pour tout ajout : blocs, repère `y` vers le bas, flottants
  à 2 décimales, objets à clés nommées.
