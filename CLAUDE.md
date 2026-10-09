# CLAUDE.md

GolfGen : générateur procédural de parcours de golf 18 trous pour Minecraft
(1 bloc = 3 m) ; un pipeline Python produit un JSON qu'un viewer HTML/JS affiche.
État : `pipeline.py` (paquet `golfgen/`) route avec le routeur « Muirfield »
(cœur dans `golfgen/routing/`), l'habille (`golfgen/dressing/` : formes de greens,
style `links` ou `parkland`, sans effet sur le tracé) et écrit le JSON 3.1
(`docs/format-3.0.md`, section « Extension 3.1 » ; 3.0 = même JSON sans habillage),
que lit le viewer 3.x (`viewer/`) ; runner et rendus PNG dans `tools/muirfield/`,
planches des greens dans `tools/dressing/`.

## Commandes

Toujours le venv `.venv` (le python système n'a pas pytest).

```bash
.venv/bin/python -m pytest tests/ -v                 # tous les tests
.venv/bin/python -m pytest tests/test_routing_*.py   # cœur Muirfield seul
.venv/bin/python pipeline.py --seed 4                # -> output/course.json (3.1), ≈ 0,4 s
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
  - `/home/kalariel/Documents/Git/ObsidianVault/dev-kb/golfgen/session-2026-10-10-reprise.md` (statut et prompt de reprise)
