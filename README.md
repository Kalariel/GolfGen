# GolfGen

Générateur procédural de parcours de golf 18 trous pour Minecraft (1 bloc = 3 m).
Un pipeline Python (`pipeline.py`) produit le relief et le routage des 18 trous
avec le routeur « Muirfield », les habille (fairways, formes de greens, 1 à 3 boîtes de départ par trou, bunkers, chemins, arbres), et les écrit
dans un JSON au format 3.4 (`docs/format-3.0.md` ; 3.3 avec `--no-trees`, 3.2 avec `--no-paths`, 3.1 avec `--no-bunkers`) ; un viewer HTML/JS l'affiche sur un canvas interactif.

## Structure

```
golfgen/ + pipeline.py          pipeline : terrain OpenSimplex, routage Muirfield, habillage, bunkers, chemins, arbres, export JSON 3.4
golfgen/routing/                routeur « Muirfield » : model, geometry, partial_checks, sites, muirfield
golfgen/dressing/               habillage post-routage (fairways, greens, départs), sans effet sur le tracé ;
                                bunkers/ (clé bunkers), paths/ (chemins, clé paths) et trees/ (arbres, clé trees)
viewer/                         viewer 3.x (servi en http, charge output/course.json)
tools/muirfield/                runner de planches, rendu lisible, métriques de forme ; sorties dans output/
tools/dressing/                 rough_plate.py : planches rendues par le viewer (trous, seeds) ; sorties dans output/
docs/format-3.0.md              contrat du JSON 3.0 et de ses extensions 3.1, 3.2, 3.3 et 3.4 (champs, unités, repère)
docs/muirfield-spike.md         historique du spike Muirfield (chemins historiques)
docs/calibration-tailles.md     calibration des tailles de terrain (R3, R3b) et pistes ouvertes
tests/                          tests pytest (pipeline, cœur test_routing_*, outils test_tools_*)
```

Détail de l'architecture, du contrat JSON et des invariants : note vault
`/home/kalariel/Documents/Git/ObsidianVault/dev-kb/golfgen/_overview.md`, section
« Pipeline golfgen : contrat JSON et invariants ». Spike : `docs/muirfield-spike.md` (chemins historiques ; le code des spikes
abandonnés est récupérable via les tags git `archive/*`).

## Démarrage rapide

```bash
# Installation (ou utiliser le venv existant .venv)
python -m venv .venv
.venv/bin/pip install -r requirements.txt

# Parcours complet (relief + 18 trous + habillage + bunkers + chemins + arbres) -> output/course.json, format 3.4
.venv/bin/python pipeline.py --seed 4
.venv/bin/python pipeline.py --seed 4 --no-trees     # sans arbres : format 3.3
.venv/bin/python pipeline.py --seed 4 --no-paths     # sans chemins ni arbres : format 3.2
.venv/bin/python pipeline.py --seed 4 --no-bunkers   # sans bunkers, chemins ni arbres : format 3.1, ≈ 0,4 s

# Tests
.venv/bin/python -m pytest tests/ -v                 # tests rapides (les « slow » sont exclus)
.venv/bin/python -m pytest tests/ -v --run-slow      # tous les tests
.venv/bin/python -m pytest tests/test_routing_*.py   # cœur Muirfield seul
```

La seed 4 sert d'exemple car elle est rapide avec les options par défaut
(400×300, patron `random`, tiré en `muirfield_inverse`) : ≈ 10 s avec le
relief en cache, dont ≈ 7,4 s de bunkers, ≈ 0,2 s de chemins et ≈ 1,5 s
d'arbres (≈ 0,4 s avec `--no-bunkers`), plus
≈ 6 s au premier lancement (calcul du relief). La seed par
défaut de la config (42) marche aussi mais prend ≈ 19 s de routage.

### Options de `pipeline.py`

- `--seed TEXTE` : seed façon Minecraft Java. Blancs de tête et de queue
  retirés, puis entier signé 64 bits s'il se lit comme tel (`42`, `-7`),
  sinon texte haché par `String.hashCode` (`--seed golf`). Vide : seed de la
  config (42). Même seed, mêmes options : même parcours.
- `--pattern {muirfield,muirfield_inverse,random}` : patron du parcours
  (défaut `random`, tirage déterministe par seed).
- `--style {links,parkland}` : style d'habillage (défaut `links`) ; ne change
  jamais le tracé, seulement les formes (greens, fairways).
- `--no-bunkers` : saute l'étape des bunkers (actifs par défaut) et donc celles
  des chemins et des arbres (versions en escalier) ; le JSON est alors le 3.1,
  sans clés `bunkers`, `paths` ni `trees`.
- `--no-paths` : saute l'étape des chemins (actifs par défaut) et donc celle des
  arbres ; le JSON est alors le 3.2 d'avant (identique hors `metadata.generator`
  et `stats.elapsed_seconds`), sans clés `paths` ni `trees`.
- `--no-trees` : saute l'étape des arbres (actifs par défaut) ; le JSON est
  alors le 3.3 d'avant (identique hors `metadata.generator` et
  `stats.elapsed_seconds`), sans clé `trees`.
- `--tree-margin M` (0 à 12, défaut 5) : marge en blocs du corridor de lisière
  et de remplissage ; ni les arbres stratégiques ni les ancrages n'en dépendent.
  Refusée avec `--no-trees`, `--no-paths` ou `--no-bunkers`.
- `--trees-debug` : ajoute compteurs et bosquets dans `trees.debug` ; refusé
  avec `--no-trees`, `--no-paths` ou `--no-bunkers`.
- `--paths-debug` : ajoute le détail des chemins par liaison (tracé, statut,
  pont, cases) dans `paths.debug` ; refusé avec `--no-paths` ou `--no-bunkers`.
- `--orientation {landscape,portrait}` : `landscape` = largeur sur le grand
  côté (défaut), `portrait` = l'inverse.
- `--short N` (300 à 350, défaut 300) et `--long N` (400 à 500, défaut 400) :
  petit et grand côté en blocs. `--width`/`--height` en sont des alias,
  exclusifs de `--orientation`/`--short`/`--long`.
- `--output CHEMIN` (défaut `output/course.json`), `--config FICHIER.json`
  (défaut `default_config.json` s'il existe dans le répertoire courant ; une
  section `routing` d'une ancienne config est ignorée, avec un avertissement).

Le pipeline fait toujours le relief, le parcours puis l'habillage, puis les
bunkers (sauf `--no-bunkers`), les chemins (sauf `--no-paths` ou
`--no-bunkers`) et les arbres (sauf `--no-trees`, `--no-paths` ou
`--no-bunkers`), et écrit le JSON 3.4 (3.3 sans arbres, 3.2 sans chemins, 3.1
sans bunkers).
Les bunkers non posés ne sont signalés que dans la console.

Codes de sortie : `0` succès ; `2` paramètre invalide (rien n'est calculé) ;
`3` aucun parcours valide pour cette seed, ce patron et cette taille (rien
n'est écrit, essayer une autre seed) ; même code pour un tracé des chemins
impossible (`PathError` : une liaison sans route ou coupée, un bogue par
construction, signalé comme tel ; `--no-paths` pour s'en passer) ou pour un
invariant cassé dans la pose des arbres (`TreeError` : un bogue, signalé comme
tel ; `--no-trees` pour s'en passer).

### Viewer

Le viewer lit le JSON par `fetch` : il doit être servi en http depuis la
racine du dépôt (ouvrir `viewer/index.html` en `file://` ne charge rien).

```bash
.venv/bin/python -m http.server 8000      # depuis la racine du dépôt
# puis ouvrir http://localhost:8000/viewer/
```

Il charge `output/course.json` au démarrage ; un autre fichier se charge par
le bouton « Choisir un JSON... » ou par l'URL
`http://localhost:8000/viewer/?json=../chemin/vers/parcours.json`. Il n'accepte
que le format 3.x (`metadata.version`) et affiche un message clair pour tout
autre fichier.

Affichage : relief, rough (surface par défaut de toute la terre ferme),
fairways, greens et boîtes de départ habillés, bunkers (3.2), chemins en
cases (3.3 : terre battue, ponts en bois, parvis plus foncé ; boutons
« Chemins » et, masqués par défaut, « Ancrages » pour les repères des
virages), arbres en cercles de rayon réel (3.4 : bouton « Arbres » présent
seulement avec la clé `trees`, une couleur par couche avec « Debug »), numéro, tee, green, clubhouse, liaisons (tirets, masquées quand le
fichier a des chemins ; bouton « Liaisons »). Panneau : seed, patron, taille,
sens des nines, stats par nine, tableaux des trous. Survol d'un trou : numéro,
nine, par, longueur et largeur (blocs et mètres), aire du green, départs,
morceaux et aire du fairway. Option « Debug » : couloir de chaque trou (axe
tee → doglegs → green, largeur totale du fairway) coloré par par, axe, sens de
jeu, contour de la bande de jeu (cœur + marge de rough). Un fichier sans
`features.fairway` (3.0, 3.1 d'avant le R5) s'affiche en couloirs.

## Routeur Muirfield

Le cœur vit dans `golfgen/routing/` (`muirfield.build_course`) ; le runner, le
rendu lisible et les métriques de forme sont dans `tools/muirfield/`.

- Patron explicite, au même titre que la seed : `muirfield`, `muirfield_inverse`,
  ou `random` (choix déterministe par seed).
- Clubhouse sur un bord de carte ; front = boucle extérieure, back = boucle
  intérieure en sens inverse (`muirfield_inverse` : l'inverse).
- Règles dures garanties : zéro croisement, écart de 5 blocs entre fairways,
  liaisons 12–45 blocs (18–45 depuis/vers le clubhouse), quota de pars 4/10/4, par d'un nine 34–38, jamais 3 par 5
  ni 3 par 3 consécutifs, pas de série de ≥ 4 trous consécutifs côte à côte.
- Longueurs de trous réalistes ; cartes rectangulaires (ex. 300×400) ;
  30/30 seeds réussies, médiane ≈ 2 s par seed (jusqu'à ~18 s en largeurs variables).

```bash
# Runner (nécessite rsvg-convert et ImageMagick `magick` pour les planches)
.venv/bin/python -m tools.muirfield.run_muirfield \
    --round custom --pattern muirfield_inverse --size 300x400 --seeds 1-6
.venv/bin/python -m tools.muirfield.run_muirfield --round rc-30   # 30 seeds par patron
```

Options : `--round` (rc, rc-30, land, land-30, custom), `--pattern`,
`--width-mode {variable,min}`, `--size LxH`, `--seeds 1-6|3,7`. Sorties :
`tools/muirfield/output/<round>_<patron>_<w>x<h>[_30seeds]/` (SVG/PNG par seed,
`planche.png`, `report.json`). Le relief (pipeline et runner) est mis en cache dans
`output/.cache/terrain/`. Détail : section « Étape M » de `docs/muirfield-spike.md`
(les chemins de modules qui y sont cités sont historiques).

## État et prochaines étapes

- Chaîne unique : seed → relief → routeur Muirfield → habillage → bunkers → chemins → arbres → JSON 3.4 → viewer
  (le viewer affiche les chemins de la clé `paths`, détectée par présence).
- Fairways (habillage) : B v1 avec col, profil en long (carry, avant-green), style
  `links`/`parkland`, coupés au-dessus de l'eau (bande de 2 blocs, fragments < 5 b²
  retirés, plusieurs morceaux possibles), exportés dans `features.fairway` ; le rough est
  la surface par défaut (rien n'est exporté pour lui).
- Défaut de forme connu : tracé en « hélice » sur certaines seeds.
- Planifié : largeur de fairway variable à l'intérieur d'un trou.
- Étape du pipeline encore à créer : ruisseaux (bunkers, arbres et ponts des
  chemins sont livrés).
