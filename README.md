# GolfGen

Générateur procédural de parcours de golf 18 trous pour Minecraft (1 bloc = 3 m).
Un pipeline Python produit le terrain et le routage des trous dans un JSON, qu'un
viewer HTML/JS affiche sur un canvas interactif.

## Structure

```
golfgen/ + pipeline.py          pipeline : terrain OpenSimplex, routage loop_router (ruban serpentin)
viewer/                         viewer : ouvrir viewer/index.html (charge output/course.json)
experiments/elastic_routing/    spike actuel : routeur par patron d'architecte « Muirfield »
experiments/bean_paving/        spike archivé
tests/                          tests pytest (pipeline + spikes)
```

Détail de l'architecture, du contrat JSON et des invariants : `CLAUDE.md`.

## Démarrage rapide

```bash
# Installation (ou utiliser le venv existant .venv)
python -m venv .venv
.venv/bin/pip install -r requirements.txt

# Pipeline (sortie par défaut : output/course.json)
.venv/bin/python pipeline.py --stage terrain      # terrain seul
.venv/bin/python pipeline.py --stage holes        # terrain + 18 trous
.venv/bin/python pipeline.py --seed 123 --stage holes --output output/v2.json

# Tests
.venv/bin/python -m pytest tests/ -v
.venv/bin/python -m pytest tests/ -v -k elastic   # spike elastic_routing seul
```

Puis ouvrir `viewer/index.html` dans un navigateur.

## Routeur Muirfield (spike)

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
.venv/bin/python -m experiments.elastic_routing.run_muirfield \
    --round custom --pattern muirfield_inverse --size 300x400 --seeds 1-6
.venv/bin/python -m experiments.elastic_routing.run_muirfield --round rc-30   # 30 seeds par patron
```

Options : `--round` (r2, ra, ra-30, ra2-30, ra2-check, rb, rb-30, rb-check, rc,
rc-30, custom), `--pattern`, `--width-mode {variable,min}`, `--size LxH`,
`--seeds 1-6|3,7`. Sorties : `experiments/elastic_routing/output/muirfield/<round>_…/`
(SVG/PNG par seed, `planche.png`, `report.json`). Détail : section « Étape M » de
`experiments/elastic_routing/PLAN.md`.

## État et prochaines étapes

- Le routeur Muirfield est un spike : pas encore branché sur `pipeline.py` ni sur le viewer.
- Défaut de forme connu : tracé en « hélice » sur certaines seeds.
- Planifié : largeur de fairway variable à l'intérieur d'un trou.
- Étapes du pipeline encore à créer : obstacles, végétation, ponts/ruisseaux.
