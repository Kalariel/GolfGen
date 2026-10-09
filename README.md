# GolfGen

Générateur procédural de parcours de golf 18 trous pour Minecraft (1 bloc = 3 m).
Un pipeline Python (`pipeline.py`) produit le relief et le routage des 18 trous
avec le routeur « Muirfield », et les écrit dans un JSON au format 3.0
(`docs/format-3.0.md`) ; un viewer HTML/JS l'affiche sur un canvas interactif.

## Structure

```
golfgen/ + pipeline.py          pipeline : terrain OpenSimplex, routage Muirfield, export JSON 3.0
golfgen/routing/                routeur « Muirfield » : model, geometry, partial_checks, sites, muirfield
viewer/                         viewer 3.x (servi en http, charge output/course.json)
tools/muirfield/                runner de planches, rendu lisible, métriques de forme ; sorties dans output/
docs/format-3.0.md              contrat du JSON 3.0 (champs, unités, repère)
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

# Parcours complet (relief + 18 trous) -> output/course.json, format 3.0
.venv/bin/python pipeline.py --seed 4

# Tests
.venv/bin/python -m pytest tests/ -v
.venv/bin/python -m pytest tests/test_routing_*.py   # cœur Muirfield seul
```

La seed 4 sert d'exemple car elle est rapide avec les options par défaut
(400×300, patron `random`, tiré en `muirfield_inverse`) : ≈ 0,4 s avec le
relief en cache, ≈ 6 s au premier lancement (calcul du relief). La seed par
défaut de la config (42) marche aussi mais prend ≈ 19 s de routage.

### Options de `pipeline.py`

- `--seed TEXTE` : seed façon Minecraft Java. Blancs de tête et de queue
  retirés, puis entier signé 64 bits s'il se lit comme tel (`42`, `-7`),
  sinon texte haché par `String.hashCode` (`--seed golf`). Vide : seed de la
  config (42). Même seed, mêmes options : même parcours.
- `--pattern {muirfield,muirfield_inverse,random}` : patron du parcours
  (défaut `random`, tirage déterministe par seed).
- `--orientation {landscape,portrait}` : `landscape` = largeur sur le grand
  côté (défaut), `portrait` = l'inverse.
- `--short N` (300 à 350, défaut 300) et `--long N` (400 à 500, défaut 400) :
  petit et grand côté en blocs. `--width`/`--height` en sont des alias,
  exclusifs de `--orientation`/`--short`/`--long`.
- `--output CHEMIN` (défaut `output/course.json`), `--config FICHIER.json`,
  `--stage {terrain,holes}` (défaut `holes` ; `terrain` écrit le relief seul
  au format 2.0, que le viewer refuse).

Codes de sortie : `0` succès ; `2` paramètre invalide (rien n'est calculé) ;
`3` aucun parcours valide pour cette seed, ce patron et cette taille (rien
n'est écrit, essayer une autre seed).

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
autre fichier (2.0 compris). Affichage : relief, couloir de chaque trou (axe
tee → doglegs → green, largeur totale du fairway) coloré par par, numéro,
sens de jeu, tee, green, liaisons, clubhouse ; panneau seed, patron, taille,
sens des nines, stats par nine et tableaux des trous ; survol d'un trou :
numéro, nine, par, longueur et largeur (blocs et mètres).

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

- `pipeline.py` et le viewer passent par le routeur Muirfield et le format 3.0 ; le pipeline n'utilise plus `loop_router` (retiré au R7, avec le format 2.0).
- Défaut de forme connu : tracé en « hélice » sur certaines seeds.
- Planifié : largeur de fairway variable à l'intérieur d'un trou.
- Étapes du pipeline encore à créer : obstacles, végétation, ponts/ruisseaux.
