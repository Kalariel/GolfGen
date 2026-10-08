# CLAUDE.md

GolfGen : générateur procédural de parcours de golf 18 trous pour Minecraft
(1 bloc = 3 m) ; un pipeline Python produit un JSON qu'un viewer HTML/JS affiche.
État : pipeline `golfgen/` + `pipeline.py` avec le routeur `loop_router` ; routeur
« Muirfield » : cœur dans `golfgen/routing/`, runner et rendus dans
`tools/muirfield/` ; pas encore branché au pipeline ni au viewer.

## Commandes

Toujours le venv `.venv` (le python système n'a pas pytest).

```bash
.venv/bin/python -m pytest tests/ -v                 # tous les tests
.venv/bin/python -m pytest tests/test_routing_*.py   # cœur Muirfield seul
.venv/bin/python pipeline.py --stage holes --seed 42 --output output/course.json
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
  - `/home/kalariel/Documents/Git/ObsidianVault/dev-kb/golfgen/session-2026-10-08-reprise.md` (statut et prompt de reprise)
