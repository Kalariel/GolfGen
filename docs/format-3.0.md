# Format JSON 3.0 — parcours Muirfield (extensions 3.1 : habillage, 3.2 : bunkers, 3.3 : chemins, 3.4 : arbres)

Référence du JSON produit par `golfgen.exporter.muirfield_to_dict(result,
heightmap, *, seed, seed_input=None, dressing=None)` et lu par le viewer
(`viewer/`, qui refuse tout `metadata.version` hors 3.x). Sans `dressing`, le
dict est du 3.0 ; avec, du 3.1 (section « Extension 3.1 » plus bas), que
`pipeline.py` écrit avec `--no-bunkers` ; par défaut, il y ajoute les bunkers
(3.2, section « Extension 3.2 », seul avec `--no-paths`), les chemins
(3.3, section « Extension 3.3 », seul avec `--no-trees`) puis les arbres
(3.4, section « Extension 3.4 »). Le 3.0 suffit à habiller le parcours sans le
re-router (section « Habiller depuis le JSON ») : c'est ainsi que
`pipeline.py` produit le 3.1.

`muirfield_to_dict` est pure (ni I/O, ni état global, ni aléa) : même entrée,
même dict. Le dict passe `json.dumps` sans encodeur (aucun type numpy).

## Conventions

- **Unité** : le bloc Minecraft (`block_m` = 3 m par bloc) pour toutes les
  coordonnées, longueurs et largeurs.
- **Repère** : origine en haut à gauche de la carte, `x` vers la droite
  (0..`width`), `y` vers le BAS (0..`height`), comme une image : la ligne `y`
  de la heightmap est la ligne `y` de la carte.
- **Flottants** arrondis à 2 décimales (coordonnées, longueurs, largeurs,
  côtés de carte, `elapsed_seconds`, totaux), **sauf les entrées de
  l'habillage**, en pleine précision (le `repr` du flottant, relu au bit
  près) : `routing.clubhouse` `x`/`y`, `holes[].width`, `rough_margin`,
  `tee`, `green`, `doglegs`. Les sorties de
  l'habillage (contours, centres, aires) restent arrondies.
- Les objets ont des clés nommées (pas de tableaux nus) pour pouvoir recevoir
  des champs plus tard sans casser les lecteurs.
- Aucun `waypoints` : les liaisons sont des segments droits.

## `metadata`

| Champ | Type | Unité / valeurs |
|---|---|---|
| `version` | chaîne | `"3.0"` (`"3.1"` avec habillage, `"3.2"` avec bunkers, `"3.3"` avec chemins, `"3.4"` avec arbres) |
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

Relief encodé par `golfgen.exporter.terrain_block`, plus `water_level`, plus
le relief sans perte `elevation_f32` (`golfgen.terrain.relief_f32_block`).

| Champ | Type | Unité |
|---|---|---|
| `width`, `height` | entier | pixels = blocs (colonnes, lignes) |
| `elevation.encoding` | chaîne | `"base64_uint8"` |
| `elevation.data` | chaîne | base64 de `width × height` octets, ligne par ligne (`y` puis `x`) ; 0..255 normalisé sur [min, max] (tout à 0 si le relief est plat) |
| `elevation.min_elevation`, `elevation.max_elevation` | nombre | altitude min / max (unités de la heightmap), 2 décimales |
| `water_level` | nombre | niveau d'eau (mêmes unités que `min_elevation`/`max_elevation`) : un pixel d'altitude strictement inférieure est de l'eau, pour le routeur (`golfgen.routing.sites.WATER_LEVEL`), les planches PNG et le viewer ; peut être hors de [min, max] (aucune eau) |
| `elevation_f32.encoding` | chaîne | `"zlib_base64_float32le_byteshuffle"` (seul codage accepté ; l'ordre naturel `"zlib_base64_float32le"` est refusé) |
| `elevation_f32.data` | chaîne | base64 d'un flux zlib (RFC 1950 : en-tête zlib et somme Adler-32, pas du deflate brut ; côté JS `DecompressionStream("deflate")`, et non `"deflate-raw"`) de `width × height` float32 petit-boutistes (`<f4`), ligne par ligne (`y` puis `x`), octets regroupés par plan (*byte shuffle*) : les `n = width × height` octets 0 des valeurs (octet 0 = octet de poids faible), puis leurs octets 1, 2 et 3 ; la valeur `i` se relit en `octets[i], octets[n+i], octets[2n+i], octets[3n+i]`. Le relief exact du routage, au bit près (entrée de l'habillage : masque sec, eau, relief) |

Altitude d'un pixel : `min + octet / 255 × (max − min)` (uint8, aperçu du
viewer, gardé pour la compatibilité) ; exacte : `elevation_f32`. Surcoût
mesuré en 400×300 (seed 21, `muirfield_inverse`) : `data` fait ≈ 354 Ko
(469 Ko de float32), contre 156 Ko pour le uint8 ; le JSON 3.1 fait
≈ 600 Ko. Sans le byte shuffle, zlib ne retirait que ≈ 20 % (bruit des
mantisses mêlé aux octets de poids fort, presque constants) : `data` ≈ 509 Ko,
JSON ≈ 756 Ko. Un delta entre cellules voisines avant le shuffle, sans perte
lui aussi, ne gagnerait que ≈ 3,5 % de plus : non retenu.

## `routing`

### `clubhouse`

`{x, y, edge}` : position en blocs (pleine précision) ; `edge` ∈ `"N"`, `"E"`, `"S"`, `"W"` est le
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
| `width` | nombre | blocs : largeur TOTALE du fairway (pleine précision) ; cœur du trou = `buffered_axis(axe, width / 2)` |
| `rough_margin` | nombre | blocs : marge de rough de part et d'autre du cœur (`golfgen.routing.model.ElasticHole`) |
| `tee`, `green` | `{x, y}` | blocs (pleine précision) |
| `doglegs` | liste de `{x, y}` | blocs (pleine précision) : points de coude de l'axe, dans l'ordre (0 à 2) |

### `links[]`

20 liaisons à pied dans l'ordre de jeu : clubhouse → 1, 1 → 2, …, 9 →
clubhouse, clubhouse → 10, …, 18 → clubhouse.

| Champ | Type | Unité |
|---|---|---|
| `from`, `to` | entier ou `"clubhouse"` | numéro de trou, ou `"clubhouse"` ; une liaison part du green de `from` et arrive au tee de `to` |
| `length` | nombre | blocs : distance euclidienne (segment droit) |

Les extrémités d'une liaison ne sont pas exportées : elles se déduisent
exactement des trous et du clubhouse (green de `from` ou `routing.clubhouse`,
tee de `to` ou `routing.clubhouse`, en pleine précision).

## Exemple (seed 4, 400×300, `random`, tronqué)

```json
{
  "metadata": {
    "version": "3.0", "generator": "golfgen 0.2.0",
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
    "water_level": 60.0,
    "elevation_f32": {"encoding": "zlib_base64_float32le_byteshuffle",
                      "data": "eJwA/z8AwBscvhTwdBGK…"}
  },
  "routing": {
    "clubhouse": {"x": 6.0, "y": 131.68486690454253, "edge": "W"},
    "direction": {"outer_nine": "back", "outer_turn": "clockwise",
                  "inner_nine": "front", "inner_turn": "counterclockwise"},
    "holes": [
      {"id": 1, "nine": "front", "par": 4, "length": 102.0, "width": 15.0,
       "rough_margin": 5.0,
       "tee": {"x": 44.23233860363279, "y": 137.06072917624857},
       "green": {"x": 121.05552954062037, "y": 192.0946873678776},
       "doglegs": [{"x": 101.30984261121921, "y": 154.74885438825405}]}
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
`dressing` (`golfgen.dressing.dress_course(result, *, seed, style)`), ou par
`golfgen.exporter.with_dressing(data, dressing)` sur un dict 3.0 (ce que
fait toujours `pipeline.py`, avec `dress_course_json`) ; les deux donnent le
même dict.

| Champ | Type | Unité / valeurs |
|---|---|---|
| `metadata.version` | chaîne | `"3.1"` |
| `metadata.style` | chaîne | `"links"` ou `"parkland"` (`--style`, défaut `links`) |
| `routing.holes[].features` | objet | habillage du trou ; une clé par élément (aujourd'hui `green`, `tees` et `fairway`) |
| `features.green.outline` | liste de `{x, y}` | blocs : contour du green, 32 sommets, polygone simple fermé implicitement |
| `features.green.center` | `{x, y}` | blocs : centre de la forme (sur l'axe, reculé depuis le drapeau vers l'approche de `max(r, avant − width/2 + 0,5)`, `r` tiré dans 0–1,5 bloc et `avant` l'étendue de la forme devant son centre, puis suivi de la réduction éventuelle) |
| `features.green.area` | nombre | blocs² : aire du contour tel qu'exporté |
| `features.green.island` | objet, **optionnel** | green insulaire (lot 1 eau : parkland, ou links en dernier recours) ; absent pour un green au sec. Les cellules du relief sous `terrain.water_level` qui partagent une aire non nulle avec `outline` sont remontées à `height`, bord franc, sans talus ; le relief exporté (`terrain`) n'est PAS modifié : la remontée se déduit du contour et du relief |
| `features.green.island.height` | nombre | altitude de la remontée : minimum du relief sur la partie émergée du green (cellules sèches qu'il recouvre), 2 décimales |
| `features.green.island.raised_area` | nombre | blocs² : nombre de cellules remontées |
| `features.tees` | liste d'objets | boîtes de départ, 1 à 3, **de l'arrière vers l'avant** ; même forme d'objet que `features.green` |
| `features.tees[].outline` | liste de `{x, y}` | blocs : rectangle de 4 blocs dans le sens du jeu × 3 en travers, 4 sommets, fermé implicitement |
| `features.tees[].center` | `{x, y}` | blocs : centre de la boîte, sur l'axe du trou ; `tees[0].center` = `holes[].tee` arrondi à 2 décimales ; repli pour l'eau (lot 1) : boîte avancée décalée en travers de l'axe, boîte arrière glissée d'au plus 1 bloc dans l'axe (sinon remontée sur place, `island`) |
| `features.tees[].area` | nombre | blocs² : aire du contour tel qu'exporté (12 à l'arrondi des sommets près) |
| `features.tees[].island` | objet, **optionnel** | boîte remontée (lot 1 eau : dernier repli d'une boîte sur l'eau, après le glissement dans l'axe et le décalage en travers ; aucune boîte n'est retirée) ; absent pour une boîte au sec. Même règle que `features.green.island` : les cellules du relief sous `terrain.water_level` qui partagent une aire non nulle avec `outline` sont remontées à `height`, bord franc ; le relief exporté n'est PAS modifié |
| `features.tees[].island.height` | nombre | altitude de la remontée : minimum du relief sur la partie émergée de la boîte ; boîte entièrement immergée : `terrain.water_level` + 1, un bloc au-dessus de l'eau (`golfgen.dressing.water.SUBMERGED_TEE_LIFT`) ; 2 décimales |
| `features.tees[].island.raised_area` | nombre | blocs² : nombre de cellules remontées |
| `features.tees[].island.submerged` | booléen | `true` si la boîte était entièrement immergée (aucune partie émergée) |
| `features.fairway` | liste d'objets | morceaux du fairway, **morceau principal d'abord, puis par aire décroissante** ; **toujours présente** en 3.1 depuis le R5 ; `[]` = fairway entièrement vidé par l'eau ; voir « Surfaces (3.1) » |
| `features.fairway[].outline` | liste de `{x, y}` | blocs : contour du morceau, polygone **strictement simple** (ni croisement, ni contact, ni sommets confondus), sans trou, fermé implicitement ; sommets arrondis à 2 décimales, nombre de sommets variable ; pas de `center` |
| `features.fairway[].area` | nombre | blocs² : aire du contour du modèle avant arrondi (le contour n'est arrondi qu'à l'export) : peut différer de quelques centièmes de l'aire du contour exporté (≤ 0,08 mesuré, seed 4), contrairement à `features.green.area` et `features.tees[].area`, dont le contour est déjà arrondi dans le modèle |
| `routing.green_pairs` | liste d'objets | greens doubles du parcours, triés par `holes` ; **toujours présente** en 3.1 (liste vide sans green double) ; voir « Greens doubles (3.1) » |
| `green_pairs[].holes` | `[i, j]` | numéros des deux trous qui partagent le green, `i < j` |
| `green_pairs[].outline` | liste de `{x, y}` | blocs : contour du green double, polygone simple fermé implicitement (environ 150 à 250 sommets, espacés d'≈ 0,5 bloc) |
| `green_pairs[].area` | nombre | blocs² : aire du contour tel qu'exporté |

Invariants :

- **green ⊂ cœur** : le contour est inclus dans le cœur du trou,
  `buffered_axis(axe, width / 2)` (`golfgen.routing.geometry`) ; s'il en
  sortait, la forme est réduite par homothétie ×0,95 centrée sur le drapeau
  jusqu'à inclusion (contrôle fait sur les coordonnées arrondies).
- Le contour **contient le drapeau** (`holes[].green`).
- **Eau** (lot 1) : aucun green ni aucune boîte de départ ne partage d'aire
  avec l'eau EFFECTIVE de son trou (cellules sous `terrain.water_level`,
  moins les cellules remontées du green insulaire et des boîtes remontées
  de CE trou ; une cellule remontée par un trou reste de l'eau pour les
  autres, et aucune boîte ne se remonte sur une cellule déjà remontée) ; un
  green links tiré sur l'eau est décalé à l'opposé de l'eau (drapeau à au
  moins 1 bloc du bord ; une forme réduite de plus de 30 % de l'aire visée
  n'est pas retenue), sinon insulaire, un green parkland devient
  insulaire ; une boîte de départ sur l'eau glisse dans l'axe, puis se
  décale en travers, puis est remontée (jamais retirée) ; un green double
  ne touche pas l'eau et ne contient aucun green insulaire.
- Aire signée positive dans le repère (x, y) (sens horaire à l'écran, `y`
  vers le bas). Aire visée : voir « Formes et tailles » ; une forme réduite
  est plus petite.
- **Le tracé ne dépend pas de l'habillage** : `routing` sans les clés
  `features` et `green_pairs` est identique octet pour octet au 3.0 de la
  même seed, quel que soit le style (aléa de l'habillage sur un flux séparé).
- Un lecteur teste la présence de `features` (et de chacune de ses clés)
  plutôt que la version : un 3.1 produit avant les départs n'a pas de clé
  `tees`, ce qui se lit « départs non habillés », pas « aucun départ ». De
  même, un 3.1 produit avant les greens doubles n'a pas de clé
  `routing.green_pairs` (« greens doubles non calculés ») ; une liste vide
  se lit « aucun green double ». Un 3.1 produit avant le R5 n'a pas de clé
  `features.fairway` (« fairway non exporté ») ; `[]` se lit « fairway
  vidé par l'eau ».

### Surfaces (3.1)

- **Le rough est la surface par défaut** : toute terre ferme qui n'est
  couverte par aucun élément exporté (fairway, green, départs) ; l'eau
  (cellules sous `terrain.water_level`, hors remontées) reste de l'eau.
  Aucune géométrie de rough n'est exportée. Les éléments des lots futurs
  (bunkers, arbres, hors-limites) seront des clés à part, posées sur ce
  fond.
- **Bande de jeu** d'un trou = cœur (`width`) + `rough_margin` de part et
  d'autre de l'axe : `buffered_axis(axe, width / 2 + rough_margin)`
  (`golfgen.routing.geometry`), bouts prolongés du rayon dans l'axe, coudes
  en onglet (décalage au coude limité à 1/0,72 ≈ 1,39 rayon). Elle se
  déduit des champs 3.0 et n'est pas exportée : c'est une zone de placement
  interne au générateur, pas une surface.

### Greens doubles (3.1)

Deux trous proches peuvent partager un **green double** (sélection et forme :
`golfgen/dressing/pairs.py`, `golfgen/dressing/pair_shape.py`). La paire est
portée par le parcours, dans `routing.green_pairs`, pas par les trous : les
**greens individuels restent dans `features.green` de chaque trou**,
inchangés (même contour, même drapeau), et le contour de la paire les
**contient tous les deux**, drapeaux compris (enveloppe des deux greens
pincée au milieu à la largeur du plus petit green, puis élargie d'environ
1,5 bloc et arrondie : la forme déborde les deux greens, et sa partie la
plus étroite entre eux est au moins aussi large que le plus petit green).
Un lecteur qui ignore `green_pairs` affiche donc deux
greens séparés, ce qui reste correct.

- Contour : mêmes conventions que `features.green.outline` (blocs, 2
  décimales, aire signée positive dans le repère (x, y), sens horaire à
  l'écran) ; sommets consécutifs confondus par l'arrondi retirés.
- `area` : aire du contour exporté (comme `features.green.area`).
- Un trou appartient à une paire au plus ; aucun champ interne (distance
  entre greens, largeur du col, empreinte, candidates rejetées) n'est
  exporté.

```json
"routing": {
  "holes": [ … ],
  "green_pairs": [
    {"holes": [2, 8],
     "outline": [{"x": 136.6, "y": 151.41}, {"x": 136.98, "y": 152.15}, …],
     "area": 225.84}
  ],
  "links": [ … ]
}
```

(seed 4, 400×300, style `links` : 129 sommets ; greens des trous 2 et 8 :
58,82 et 68,83 blocs².)

### Départs (3.1)

Constantes dans `golfgen/dressing/tees.py`. Le style n'intervient pas ; le
JSON ne porte ni le rang, ni le sens, ni la cause d'une bascule.

- **Boîtes** : rectangles de **4×3 blocs** (4 dans le sens du jeu, 3 en
  travers), toutes de même taille, centrées sur l'axe, alignées sur le
  premier segment de l'axe (tee → premier coude, ou green sans coude).
- **Ordre** : `tees[0]` est la boîte arrière, centrée exactement sur le tee
  routé (`holes[].tee`) ; les suivantes avancent le long du premier segment,
  la dernière étant la plus avancée. Écart bord à bord ≥ 2 blocs entre
  boîtes consécutives (≥ 6 blocs entre centres).
- **Nombre, 1 à 3** : par 3 de longueur < 55 blocs : 1, plus long : 2 ;
  par 4 : 2 ou 3 à 50/50 ; par 5 : 3. Moins de boîtes (bascule, 3 → 2 →
  1) si le plafond d'étalement `Emax = min(20, L/4, seg1 − 10)` (`L` :
  longueur de l'axe ; `seg1` : premier segment, terme pris avec coude
  seulement) est sous le minimum requis (12 blocs à 3 boîtes, 10 à 2).
- **Étalement** (centre arrière → centre le plus avancé) : tiré dans
  10–`Emax` blocs à 2 boîtes, 12–`Emax` à 3 ; boîte du milieu entre 35 et
  65 % de l'étalement, à 6 blocs au moins de chaque voisine.
- **Contraintes** : chaque boîte est dans le cœur du trou et à un écart
  strictement positif du contour du green (pas même un contact par un bord).

### Formes et tailles des greens (3.1)

Le JSON ne porte que le contour : le type de green n'est pas exporté.
Constantes dans `golfgen/dressing/model.py` (`STYLE_SPECS`) et
`golfgen/dressing/green.py` ; chiffres mesurés sur 30 seeds × 2 formats
(400×300 et 300×400, patron `random`, 1080 trous par style ; contrôlés par
`tests/test_dressing_kinds.py`).

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
  creux inatteignable (arc intérieur inexistant pour la flèche visée, dès la
  première évaluation), calage (échec du recalage du creux : non convergé,
  ou sécante qui pousse la flèche hors du domaine de la capsule), ou, une
  fois placé, col < 5,5 blocs ou creux rendu en blocs < 1 bloc. Le creux
  rendu est exigé de tout haricot placé, réduit compris (règle plus stricte
  que nécessaire : aucun haricot réduit ne bascule ainsi aujourd'hui).
- **Éligibilité** : un haricot exige un grand green, aire visée ≥ 84
  blocs² (links) ou 77 (parkland) ; seuils validés, conservés (la capsule
  tiendrait la bascule ≤ 5 % dès 74 et 72). Bascules mesurées sur les
  haricots tirés : links 3/370 (0,8 % : 3 calages), parkland 9/317 (2,8 % :
  5 creux inatteignables, 3 calages, 1 creux rendu) ; ce sont un
  sous-ensemble des bascules des haricots forcés sur tous les éligibles, base
  du calage de P_eff ci-dessous : links 4/547 (0,7 % : 3 calages, 1 creux
  rendu), parkland 10/415 (2,4 % : 5 creux inatteignables, 4 calages, 1
  creux rendu). Le calage est une cause réelle (0,5–1,0 % des haricots) : un
  bornage de la flèche dans le domaine de la capsule pourrait le réduire
  (piste future ; il changerait les formes et obligerait à recalibrer).
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

## Extension 3.2 : bunkers

Ajout strictement additif : le 3.1 plus une clé de **premier niveau**
`bunkers` (dernière clé), et `metadata.version` `"3.2"` ; tout le reste est
identique au 3.1 de la même seed et du même style (`pipeline.py
--no-bunkers` écrit ce 3.1, sans la clé). Produit par
`golfgen.exporter.with_bunkers(data, bunkers)` sur le 3.1, avec
`golfgen.dressing.bunkers.place_bunkers_json(data, dressing)`, qui lit un
JSON 3.x quelconque (le pipeline lui passe le 3.0 du routage ; tracé, seed
et eau relus dans le JSON, comme l'habillage : rejouable sans re-router).
`with_dressing` sur un 3.2 retire la clé (bunkers calculés sur l'ancien
habillage) et rend un 3.1.

| Champ | Type | Unité / valeurs |
|---|---|---|
| `bunkers.empty_rule` | chaîne | règle des trous vides, toujours `"per_hole"` (1 chance sur 50 par trou ; seule règle, champ gardé pour la compatibilité) |
| `bunkers.empty_holes` | liste d'entiers | trous laissés sans bunker par cette règle, croissants |
| `bunkers.items` | liste d'objets | bunkers posés (sable légal seulement), trous croissants |
| `items[].id` | chaîne | identifiant, unique **dans son trou** (`(hole, id)` est unique) |
| `items[].hole` | entier | numéro du trou (`holes[].id`) |
| `items[].family` | chaîne | `"pot"` ou `"haricot"` (plus d'`"organique"` depuis le 2026-11-02 : les haricots de green les remplacent ; un lecteur peut garder l'ancienne valeur pour des fichiers antérieurs) |
| `items[].role` | chaîne | `"green"` (autour du green) ou `"landing"` (zone de retombée) |
| `items[].status` | chaîne | origine de la pose : `"construction"`, `"flanc"`, `"flanc_sans_fautifs"`, `"pose_en_place"`, `"recule"` |
| `items[].cells` | liste de `[x, z]` | cases de sable, entiers ; la case `[x, z]` couvre `[x, x+1] × [z, z+1]` en blocs, `z` étant le `y` du repère (vers le bas) ; `0 ≤ x < terrain.width`, `0 ≤ z < terrain.height` |

Invariants : aucune case sur l'eau — l'eau BRUTE de la carte
(`golfgen.routing.sites.WaterMask` : cellules du relief exact
`terrain.elevation_f32` sous `terrain.water_level`, sans élargissement), pas
l'eau effective par trou qui coupe le fairway (eau brute moins les
cellules remontées d'un green insulaire ou d'une boîte de départ) : une
cellule remontée reste de l'eau pour les bunkers ; contrôlé à la pose
(`place_bunkers`), pas revérifié par `with_bunkers` ;
aucun trou de `empty_holes` n'a de bunker. Les bunkers sélectionnés mais non
posés (refusés, sans pose légale) ne sont pas exportés : la console du
pipeline les compte, par étape et raison. Le sable se dessine sur le rough
(surface par défaut, « Surfaces (3.1) ») ; un lecteur teste la présence de
`bunkers` plutôt que la version.

## Extension 3.3 : chemins

Ajout strictement additif : le 3.2 plus une clé de **premier niveau** `paths`
(dernière clé), et `metadata.version` `"3.3"` ; tout le reste est identique,
à l'octet près, au 3.2 de la même seed et du même style (`pipeline.py
--no-paths` écrit ce 3.2, sans la clé). Versions en escalier : 3.1 sans
bunkers, 3.2 avec bunkers, 3.3 avec bunkers et chemins (`--no-bunkers`
implique `--no-paths` : pas de chemins sans bunkers, qui en sont des
obstacles). Produit par `golfgen.exporter.with_paths(data, paths)` sur le
3.2, avec `golfgen.dressing.paths.place_paths(data)`, qui ne lit que ce JSON
3.2 (scène, eau et relief relus comme l'habillage ; style dans
`metadata.style`) : rejouable sans re-router. `with_dressing` et
`with_bunkers` sur un 3.3 retirent la clé (chemins posés autour de l'ancien
habillage ou des anciens bunkers).

Couche à plat, en cases entières (même convention que `bunkers` : la case
`[x, z]` couvre `[x, x+1] × [z, z+1]`, `z` = `y` du repère ; listes triées par
`x` puis `z`, sans doublon, dans la carte) :

| Champ | Type | Unité / valeurs |
|---|---|---|
| `paths.width` | nombre | blocs : largeur nominale du chemin, `2.0` (`links`) ou `3.0` (`parkland`) |
| `paths.cells` | liste de `[x, z]` | union des cases de chemin de toutes les liaisons, **ponts compris** ; une case partagée (tronc commun) n'y est qu'une fois |
| `paths.bridge_cells` | liste de `[x, z]` | cases de pont : le sous-ensemble de `cells` sur l'eau effective (déjà dans `cells`, à dessiner par-dessus) ; vide sans pont |
| `paths.plaza` | objet ou `null` | parvis du clubhouse (`null` s'il n'a pas pu être posé : le clubhouse est alors un point) |
| `plaza.cells` | liste de `[x, z]` | `size × size` cases du parvis, **hors de** `cells` (le parvis est une surface à part, un obstacle pour les chemins, qui viennent le toucher par une face) |
| `plaza.size` | entier | côté du parvis (blocs : 7 au nominal, réduit jusqu'à 3) |
| `plaza.offset` | `{along, inward}` | entiers, blocs : décalage par rapport à la position nominale, le long du bord du clubhouse et vers l'intérieur de la carte |
| `paths.anchors` | liste de `[x, z]` | case d'ancrage de chaque virage marqué : rough libre (ni fairway, ni green, ni boîte, ni bunker, ni parvis, ni eau), hors de toute case de chemin ; réservée au futur lot arbres (buisson ou bosquet du côté intérieur du virage) |

Invariants : `cells` est 4-connexe liaison par liaison et l'union n'a aucun
contact par un coin seul (deux liaisons qui ne se touchaient que par un coin
reçoivent une case de raccord libre, la plus proche des deux tracés ; un contact
sans case libre resterait, signalé dans `debug.union_defects`) ; aucune
case de `cells` sur un green, une boîte, un bunker ou le parvis, ni sur l'eau
hors de `bridge_cells` ; chaque liaison posée touche ses deux bouts par une face.

Détail (`pipeline.py --paths-debug` seulement, `with_paths(..., debug=True)`) :
une sous-clé `paths.debug` (dernière), pour la mise au point et le viewer, sans
garantie de stabilité :

| Champ | Type | Unité / valeurs |
|---|---|---|
| `debug.links` | liste d'objets | une par liaison de `routing.links`, même ordre |
| `links[].from`, `links[].to` | entier ou `"clubhouse"` | comme `routing.links` |
| `links[].status` | chaîne | statut de la route : `"straight"`, `"detour"`, `"bridge"` ou `"trivial"` (surfaces qui se touchent : rien de posé) |
| `links[].bridge` | booléen | la liaison est un pont |
| `links[].points` | liste de `{x, y}` | tracé final (virages compris), blocs, 2 décimales |
| `links[].cells` | liste de `[x, z]` | cases de la liaison (avant raccord de l'union) |
| `debug.union_added` | liste de `[x, z]` | cases de raccord ajoutées à l'union |
| `debug.union_defects` | liste de paires de `[x, z]` | contacts par un coin restés sans case libre (vide attendu) |

Exemple (seed 4, `links`, tronqué) :

```json
"paths": {
  "width": 2.0,
  "cells": [[8, 125], [8, 126], [8, 127], "… 954 cases"],
  "bridge_cells": [],
  "plaza": {"cells": [[6, 128], [6, 129], "… 49 cases"], "size": 7,
            "offset": {"along": 0, "inward": 0}},
  "anchors": [[328, 25]]
}
```

Un lecteur teste la présence de `paths` plutôt que la version.

## Extension 3.4 : arbres

Ajout strictement additif : le 3.3 plus une clé de **premier niveau** `trees`
(dernière clé), et `metadata.version` `"3.4"` ; tout le reste est identique, à
l'octet près, au 3.3 de la même seed et du même style (`pipeline.py --no-trees`
écrit ce 3.3, sans la clé). Versions en escalier : pas d'arbres sans chemins
(`--no-paths` et `--no-bunkers` impliquent `--no-trees`). Produit par
`golfgen.exporter.with_trees(data, trees)` sur le 3.3, avec
`golfgen.dressing.trees.place_trees(data, margin=5.0, scene=None)`, qui ne lit
que ce JSON 3.3 : rejouable sans re-router. `with_dressing`, `with_bunkers` et
`with_paths` sur un 3.4 retirent la clé (arbres posés autour des anciennes
surfaces).

Couche à plat, en blocs, sans hauteur, dans l'ordre de pose (retombée, green,
ancrages, lisière, remplissage) :

| Champ | Type | Unité / valeurs |
|---|---|---|
| `trees.items` | liste d'objets | un par arbre |
| `items[].x`, `items[].z` | entiers | case du centre de l'arbre (même convention que `bunkers` : `z` = `y` du repère) |
| `items[].radius` | entier | rayon de couronne (2, 3 ou 4 blocs : cases dont le centre est à au plus ce rayon de la case centrale) |
| `items[].layer` | chaîne | `"retombee"`, `"green"`, `"ancrage"`, `"lisiere"` ou `"remplissage"` |
| `items[].grove` | entier | **ancrages seuls** : indice de l'ancrage dans `paths.anchors` |

Invariants : chaque couronne est entière sur la carte, hors de l'eau effective,
des greens, boîtes, bunkers, parvis et chemins, et ne chevauche aucune autre
couronne. Les ancrages peuvent entrer dans le corridor, jamais dans le cœur
du trou. `--tree-margin` (0 à 12, défaut 5) ne règle que le corridor de lisière
et de remplissage : couches stratégiques et ancrages n'en dépendent pas.

Détail (`pipeline.py --trees-debug` seulement, `with_trees(..., debug=True)`) :
une sous-clé `trees.debug` (dernière), pour la mise au point, sans garantie de
stabilité :

| Champ | Type | Unité / valeurs |
|---|---|---|
| `debug.counts` | objet | arbres posés par couche |
| `debug.skips` | objet | par couche, défauts par motif (`sans_zone`, `hors_plateau`, `impossible`, `deux_flancs`, `partiel`, `sans_place`) |
| `debug.groves` | liste d'objets | un par ancrage de `paths.anchors`, même ordre : `index`, `anchor` (`[x, z]`), `placed`, `target`, `trees` (`[[x, z, rayon], ...]`), `motif` (`null` si complet) |

Un trou sauté ou un ancrage incomplet n'est jamais une erreur : il est compté.

Exemple (seed 4, `links`, tronqué) :

```json
"trees": {
  "items": [{"x": 243, "z": 91, "radius": 3, "layer": "retombee"},
            {"x": 329, "z": 27, "radius": 3, "layer": "ancrage", "grove": 0},
            {"x": 233, "z": 15, "radius": 2, "layer": "remplissage"},
            "… 110 arbres"]
}
```

Un lecteur teste la présence de `trees` plutôt que la version.

## Habiller depuis le JSON (étape 2)

`golfgen.dressing.dress_course_json(data, style)` habille le parcours décrit
par un dict 3.x (`json.load` du fichier) **sans re-router** : même
`CourseDressing`, au bit près, que `dress_course` sur le résultat du routage
(testé sur 10 parcours, deux styles, green double compris). Le 3.1 s'en
déduit par `with_dressing(data, dressing)` ; un 3.1 se ré-habille de même
(habillage présent ignoré puis remplacé, autre style possible).

- Lu : `metadata.seed` (seed u64 de l'habillage : `seed & 0xFFFF_FFFF_FFFF_FFFF`),
  `metadata.width`/`height` (= `terrain.width`/`height`), `routing.clubhouse`,
  `holes[]` (`id`, `nine`, `par`, `width`, `rough_margin`, `tee`, `green`,
  `doglegs`), `links[]` (`from`, `to`), `terrain.water_level`
  et `terrain.elevation_f32`. Les longueurs, statistiques et le uint8 ne
  servent pas.
- Reconstruit (`course_input_from_json` → `CourseInput`) : le `CourseLayout`
  (liaisons déduites des trous et du clubhouse par `NineLayout.from_holes`,
  leurs `from`/`to` vérifiés contre l'ordre de jeu ; mêmes contrôles qu'au
  routage : quotas de par…), le relief float32 et son masque sec par
  `golfgen.routing.sites.dry_mask` lui-même (critère unique du routeur ; pas
  encore lu par l'habillage).
- Refusé (`CourseJsonError`, sous-classe de `ValueError`, message nommant
  les champs) : version hors 3.x ; export antérieur à ces champs (3.0 ou 3.1
  arrondis à 2 décimales, sans `rough_margin` ni `elevation_f32`) —
  l'habiller donnerait des formes légèrement différentes, en silence (mesuré sur 10 layouts × 2 styles : les `features` exportées
  des 360 trous changent, sommets déplacés jusqu'à 0,014 bloc) ; tracé
  incohérent (dont des `from`/`to` hors de l'ordre de jeu) ; `water_level`
  différent de celui du routeur ; relief ou seed illisibles (dont un
  `elevation_f32` qui n'est pas un objet, d'un autre codage que
  `"zlib_base64_float32le_byteshuffle"`, ou dont le flux zlib dépasse ou
  n'atteint pas `4·width·height` octets) ; taille de carte incohérente
  (côtés non entiers, booléens ou nuls) ; `terrain`, `routing` ou `metadata`
  qui ne sont pas des objets.

## Extension

- **Ajouts de champs = version mineure** (`3.1`, `3.2`, …) : un lecteur 3.x
  ignore les clés qu'il ne connaît pas, et aucun champ existant ne change de
  type, d'unité ou de sens. Retirer ou redéfinir un champ = `4.0`.
- **Une section par couche** pour le façonnage à venir : les formes d'un trou
  s'ajoutent sous `holes[].features` (`green`, `tees` et `fairway` en 3.1) ; une forme
  partagée par plusieurs trous va dans `routing` (`green_pairs` en 3.1), et
  chaque nouvelle couche indépendante arrive dans sa
  propre section de premier niveau ou de `routing` (`bunkers`, `trees`,
  `water`…), absente tant que l'étape correspondante n'est pas implémentée.
  Un lecteur teste la présence de la section au lieu de supposer une version.
- Mêmes conventions pour tout ajout : blocs, repère `y` vers le bas, flottants
  à 2 décimales (sauf entrée d'une étape ultérieure, en pleine précision),
  objets à clés nommées.
