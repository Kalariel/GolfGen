# CLAUDE.md

GolfGen : générateur procédural de parcours de golf 18 trous pour Minecraft
(1 bloc = 3 m) ; un pipeline Python produit un JSON qu'un viewer HTML/JS affiche.
État : `pipeline.py` (paquet `golfgen/`) route avec le routeur « Muirfield »
(cœur dans `golfgen/routing/`), l'habille (`golfgen/dressing/` : formes de greens
et 1 à 3 boîtes de départ par trou, style `links` ou `parkland`, sans effet sur le
tracé ; fairway B v1 avec col, profil en long — carry, avant-green — et style
`links`/`parkland`, coupé au-dessus de l'eau — bande de 2 blocs, fragments < 5 b²
retirés, plusieurs morceaux possibles —, exporté dans `features.fairway`), pose
les bunkers (`golfgen/dressing/bunkers/`, clé `bunkers`), trace les chemins
(`golfgen/dressing/paths/`, clé `paths` : cases de l'union, ponts, parvis,
ancrages des virages), plante les arbres (`golfgen/dressing/trees/`, clé
`trees` : retombée, green, ancrages, lisière, remplissage) et écrit le JSON 3.4
(`docs/format-3.0.md`, sections « Extension 3.1 » à « Extension 3.4 » ; 3.3 =
même JSON sans arbres, 3.2 = sans chemins ni arbres, 3.1 = sans bunkers, chemins
ni arbres, 3.0 = sans habillage),
que lit le viewer 3.x (`viewer/` : rough partout par défaut, fairways, greens,
départs, bunkers, chemins en cases — ponts, parvis ; ancrages en option ;
liaisons droites masquées par défaut avec des chemins — ; arbres en cercles,
bouton « Arbres » si la clé existe, par couche sous Debug ; ancien couloir et
bande de jeu en option Debug) ; runner et rendus PNG
dans `tools/muirfield/`, planches rendues par le viewer (trous choisis ou
parcours entiers sur plusieurs seeds) dans `tools/dressing/rough_plate.py`.

## Commandes

Toujours le venv `.venv` (le python système n'a pas pytest).

```bash
.venv/bin/python -m pytest tests/ -v                 # tests rapides (marqueur slow exclu)
.venv/bin/python -m pytest tests/ -v --run-slow      # tous les tests, slow compris
.venv/bin/python -m pytest tests/test_routing_*.py   # cœur Muirfield seul
.venv/bin/python pipeline.py --seed 4                # -> output/course.json (3.4), ≈ 10 s (bunkers, arbres)
.venv/bin/python pipeline.py --seed 4 --no-trees     # sans arbres : 3.3 d'avant, hors generator et elapsed_seconds
.venv/bin/python pipeline.py --seed 4 --tree-margin 8   # marge du corridor de lisière et remplissage (0 à 12, défaut 5)
.venv/bin/python pipeline.py --seed 4 --trees-debug  # 3.4 + compteurs et bosquets (trees.debug)
.venv/bin/python pipeline.py --seed 4 --no-paths     # sans chemins ni arbres : 3.2 d'avant, hors generator et elapsed_seconds
.venv/bin/python pipeline.py --seed 4 --paths-debug  # 3.4 + détail par liaison (paths.debug)
.venv/bin/python pipeline.py --seed 4 --no-bunkers   # sans bunkers, chemins ni arbres : 3.1, ≈ 0,4 s
.venv/bin/python pipeline.py --seed 4 --style parkland  # style d'habillage (défaut links)
.venv/bin/python -m http.server 8000                 # viewer : http://localhost:8000/viewer/
.venv/bin/python -m tools.muirfield.run_muirfield \
    --round custom --pattern muirfield_inverse --size 300x400 --seeds 1-6
```

Options : `pipeline.py --help`, `.venv/bin/python -m tools.muirfield.run_muirfield --help`.

## Conventions

- Python : dataclasses, type hints, numpy vectorisé quand possible.
- JS : vanilla, pas de framework, canvas 2D.
- Interface en français ; config en JSON (pas de YAML/TOML).
- Polices : Google Fonts `Silkscreen` (titres) et `IBM Plex Mono` (contenu).

## Règles de travail (spike)

- Plan validé par l'utilisateur avant d'écrire du code.
- Ne jamais assouplir une règle ni relever un budget en silence.
- Regarder soi-même les planches PNG produites, pas seulement les chiffres.
- Si un mécanisme validé ne marche pas : s'arrêter et rapporter, ne pas improviser.

## Où lire

- `README.md` : vue d'ensemble, structure, démarrage.
- `docs/muirfield-spike.md`, section « Étape M » : historique du spike, règles,
  résultats (chemins historiques ; code abandonné sous les tags git `archive/*`).
- Vault Obsidian :
  - `/home/kalariel/Documents/Git/ObsidianVault/dev-kb/golfgen/_overview.md`
  - `/home/kalariel/Documents/Git/ObsidianVault/dev-kb/golfgen/elastic-routing-muirfield.md` (historique et décisions)
  - `/home/kalariel/Documents/Git/ObsidianVault/dev-kb/golfgen/session-2026-10-16-reprise.md` (statut et prompt de reprise)
