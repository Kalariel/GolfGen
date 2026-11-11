"""Corpus des tests sur de vrais parcours : JSON produits par ``pipeline.py``,
mis en cache entre deux sessions de tests, et parcours fabriqués.

Options de ``pipeline.py`` (``extra`` d'``ensure_corpus`` et de
``corpus_json``) : par défaut ``--no-trees`` (``DEFAULT_EXTRA``), le JSON 3.3
des tests des chemins ; ``()`` : le 3.4 par défaut (arbres,
``tests/test_dressing_trees_frozen.py``) ; ``("--trees-debug",)`` : le 3.4 et
son détail (oracle des arbres, ``tests/test_dressing_trees_oracle.py``).

Seeds tirées au hasard (``SEEDS``, ``secrets.randbelow(10**6)``,
2026-11-06) puis figées : un test doit rester reproductible. Elles n'ont ni
green double, ni green ou départ insulaire, ni pont, et leur parvis est
toujours posé à 7 sans décalage : d'où les seeds CHOISIES (``CHOSEN``),
trouvées en balayant les seeds 1 à 130 en style ``links`` (et les
candidates en ``parkland``), chacune pour les cas qu'elle couvrait à la
constitution du corpus (2026-11-06, sous l'ancienne règle des ponts) :

- 50 links : pas de parvis (extrémités ponctuelles du clubhouse), 2 ponts
  dont un détour sec trop long (``long_dry``), tension refusée, fenêtre de
  60, emprunts au tronc ;
- 89 links : parvis décalé, pont avec ``long_dry``, tension refusée ;
- 1 links : green double ;
- 14 parkland : deux greens insulaires ;
- 46 links : deux départs insulaires, pont ;
- 109 links : parvis réduit (6) et décalé, fenêtre de 30.

Aucune des 130 seeds n'a de gué (``water_fringe``) : il est couvert par un
parcours fabriqué (``fabricated_variant``).

Rapides (par défaut) : ``FAST`` (50 et 89 en links) ; lents (``slow``,
``--run-slow``) : ``SLOW``, les 8 seeds × 2 styles et les autres choisies.

Cache : ``pipeline.py`` coûte ≈ 13 s par JSON (bunkers et arbres compris) ;
les JSON manquants sont produits en parallèle (un sous-processus chacun,
cache de relief sûr en écriture concurrente) dans un dossier du cache de
pytest donné par l'appelant (``.pytest_cache/d/golfgen-paths-corpus-<empreinte>``
pour les chemins, ``golfgen-trees-corpus-<empreinte>`` pour les arbres), puis
relus. Le nom de chaque fichier porte la seed, le style et les options
``extra`` (``corpus_path``) : deux jeux d'options ne partagent jamais un
fichier. L'empreinte (``CACHE_KEY``) est un hash du contenu de
``pipeline.py``, de ``default_config.json`` et de ``golfgen/`` : un pipeline
ou une configuration changés produisent un nouveau corpus.
``pytest --cache-clear`` le régénère aussi.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

import numpy as np

from golfgen.routing.sites import WaterMask

ROOT = Path(__file__).resolve().parent.parent
SEEDS = (112392, 145162, 371975, 421602, 422228, 461081, 479124, 746459)
STYLES = ("links", "parkland")
CHOSEN = ((50, "links"), (89, "links"), (1, "links"), (14, "parkland"), (46, "links"),
          (109, "links"))
FAST = ((50, "links"), (89, "links"))
SLOW = tuple((seed, style) for seed in SEEDS for style in STYLES) + tuple(
    course for course in CHOSEN if course not in FAST)
# parcours épinglés au JSON 3.3 (``tests/test_dressing_paths_frozen.py``) :
# ponts (86624, 57872 et 12501), quelques seeds dans les deux styles, green
# double (1), îles (14, 46) et parvis réduit (109)
FROZEN_FAST = FAST + ((12501, "parkland"),)
FROZEN = FROZEN_FAST + ((86624, "links"), (57872, "parkland"),
                        (112392, "links"), (112392, "parkland"),
                        (145162, "links"), (145162, "parkland"),
                        (1, "links"), (14, "parkland"), (46, "links"), (109, "links"))


def source_fingerprint() -> str:
    """Hash (12 caractères) du contenu de ``pipeline.py``, de
    ``default_config.json`` et des fichiers de ``golfgen/`` (hors
    ``__pycache__``), chemins compris."""
    digest = hashlib.sha256()
    files = [ROOT / "pipeline.py", ROOT / "default_config.json"] + sorted(
        p for p in (ROOT / "golfgen").rglob("*")
        if p.is_file() and "__pycache__" not in p.parts and p.suffix != ".pyc")
    for path in files:
        digest.update(str(path.relative_to(ROOT)).encode())
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()[:12]


CACHE_KEY = f"golfgen-paths-corpus-{source_fingerprint()}"


DEFAULT_EXTRA: tuple[str, ...] = ("--no-trees",)


def corpus_path(cache_dir: Path, seed: int, style: str,
                extra: tuple[str, ...] = DEFAULT_EXTRA) -> Path:
    """Fichier du JSON de ``(seed, style)`` produit avec les options
    ``extra`` : chacune s'ajoute au nom, telle quelle
    (``course_s50_links_--no-trees.json``)."""
    return cache_dir / f"course_s{seed}_{style}{''.join(f'_{option}' for option in extra)}.json"


def ensure_corpus(cache_dir: Path, courses, extra: tuple[str, ...] = DEFAULT_EXTRA) -> None:
    """Produit en parallèle les JSON des ``courses`` (``(seed, style)``)
    absents de ``cache_dir`` ; ``extra`` : options de ``pipeline.py`` (défaut
    ``--no-trees`` : le 3.3 du corpus des chemins ; ``()`` : le 3.4 par
    défaut, corpus des arbres), qui font partie du nom du fichier."""
    extra = tuple(extra)
    jobs = []
    for seed, style in courses:
        path = corpus_path(cache_dir, seed, style, extra)
        if path.exists():
            continue
        cmd = [sys.executable, str(ROOT / "pipeline.py"), "--seed", str(seed),
               "--style", style, *extra, "--output", str(path)]
        jobs.append((path, subprocess.Popen(cmd, cwd=ROOT, stdout=subprocess.DEVNULL,
                                            stderr=subprocess.PIPE, text=True)))
    failed = []
    for path, job in jobs:
        _, err = job.communicate()
        if job.returncode != 0 or not path.exists():
            failed.append(f"{path.name} : code {job.returncode}\n{err[-2000:]}")
    if failed:
        raise RuntimeError("corpus : pipeline en échec\n" + "\n".join(failed))


def corpus_json(cache_dir: Path, seed: int, style: str,
                extra: tuple[str, ...] = DEFAULT_EXTRA) -> dict:
    """JSON de la seed ``seed`` en style ``style`` produit avec les options
    ``extra`` (déjà produit par ``ensure_corpus``, mêmes options)."""
    return json.loads(corpus_path(cache_dir, seed, style, tuple(extra)).read_text(encoding="utf-8"))


# === Parcours fabriqués ===

FAB_WIDTH, FAB_HEIGHT = 60, 40


def _outline(x0, y0, x1, y1):
    return [{"x": x, "y": y} for x, y in ((x0, y0), (x1, y0), (x1, y1), (x0, y1))]


def _hole(order, green, tees, *, island=False, fairway=()):
    return {"id": order, "features": {
        "green": {"outline": _outline(*green), "island": island},
        "tees": [{"outline": _outline(*t)} for t in tees],
        "fairway": [{"outline": _outline(*f)} for f in fairway]}}


def fabricated_json(club=(30.0, 38.0, "S"), *, style: str = "links",
                    island_tee: bool = False) -> dict:
    """Petit JSON 3.2 fabriqué, 60 × 40 : 3 trous, green double 1/3, green
    2 insulaire, une boîte avancée (``tee 2/1``), un fairway, un bunker ;
    liaisons clubhouse → 1, 1 → 2, 2 → 3, 3 → clubhouse. ``island_tee`` :
    boîte ``tee 3/0`` insulaire."""
    data = {
        "metadata": {"style": style},
        "terrain": {"width": FAB_WIDTH, "height": FAB_HEIGHT},
        "routing": {
            "clubhouse": {"x": club[0], "y": club[1], "edge": club[2]},
            "green_pairs": [{"holes": [1, 3], "outline": _outline(10, 10, 18, 14)}],
            "holes": [_hole(1, (10, 10, 14, 14), [(5, 30, 7, 32)]),
                      _hole(2, (40, 10, 44, 14), [(20, 30, 22, 32), (24, 30, 26, 32)],
                            island=True, fairway=[(20, 20, 30, 28)]),
                      _hole(3, (14, 10, 18, 14), [(50, 30, 52, 32)])],
            "links": [{"from": "clubhouse", "to": 1}, {"from": 1, "to": 2},
                      {"from": 2, "to": 3}, {"from": 3, "to": "clubhouse"}]},
        "bunkers": {"items": [{"hole": 2, "id": "b0", "cells": [[35, 20], [36, 20]]}]},
    }
    if island_tee:
        data["routing"]["holes"][2]["features"]["tees"][0]["island"] = True
    return data


def fabricated_water() -> np.ndarray:
    """Eau brute de base : l'étang autour du green 2 (insulaire)."""
    water = np.zeros((FAB_HEIGHT, FAB_WIDTH), bool)
    water[8:18, 38:48] = True
    return water


# variante -> (clubhouse, eau ajoutée (rangées, colonnes), boîte 3/0 insulaire) ;
# « shifted » : la boîte 2/1 touche la marge du parvis nominal ; « reduced » :
# les boîtes 2/0 et 2/1 bloquent tous les décalages du parvis de 7 ; « point » :
# eau autour du clubhouse, pas de parvis ; « pond » : étang à traverser, bande
# y 20..23 sur x 0..54 (détour sec au-delà de x 55, plus de 3 × direct : pont) ;
# « ford » : la même avec un gué de 3 cases (x 18..20), trop étroit pour un
# chemin sec (frange dilatée de l'eau) ; « island_tee » : boîte 3/0 dans un étang
FABRICATED = {
    "nominal": ((30.0, 38.0, "S"), (), False),
    "shifted": ((29.0, 38.0, "S"), (), False),
    "reduced": ((24.0, 38.0, "S"), (), False),
    "point": ((30.0, 38.0, "S"), ((slice(33, 40), slice(22, 40)),), False),
    "pond": ((30.0, 38.0, "S"), ((slice(20, 24), slice(0, 55)),), False),
    "ford": ((30.0, 38.0, "S"), ((slice(20, 24), slice(0, 18)), (slice(20, 24), slice(21, 55))),
             False),
    "island_tee": ((30.0, 38.0, "S"), ((slice(27, 36), slice(47, 56)),), True),
}


def fabricated_variant(variant: str = "nominal",
                       style: str = "links") -> tuple[dict, SimpleNamespace]:
    """JSON fabriqué de la variante ``variant`` (``FABRICATED``) en style
    ``style`` et ce que doit rendre ``course_input_from_json`` à sa place :
    eau brute et relief plat."""
    club, extra, island_tee = FABRICATED[variant]
    water = fabricated_water()
    for rows, cols in extra:
        water[rows, cols] = True
    stub = SimpleNamespace(water=WaterMask(water=water),
                           relief=np.full((FAB_HEIGHT, FAB_WIDTH), 64.0))
    return fabricated_json(club, style=style, island_tee=island_tee), stub


def stub_course_input(monkeypatch, stub, *modules) -> None:
    """``course_input_from_json`` remplacé par ``stub`` dans ``modules``."""
    for module in modules:
        monkeypatch.setattr(module, "course_input_from_json", lambda data: stub)


# === Parcours fabriqué des virages ===

BENDS_WIDTH, BENDS_HEIGHT = 170, 100


def bend_reject_holes() -> list[dict]:
    """Trous 6 à 10 du parcours des virages (``bends_json``), en haut à
    droite (x 66 à 166, y 0 à 14) : 6 → 7 droite en y 6,2 (green 6 et boîte
    7 sous la droite, côté opposé à 8 → 9) ; 8 → 9 de (112,7 ; 9,6) à
    (72,7 ; 8,999) : le sommet pointu de la boîte 9 met le seul dernier
    échantillon dans l'anneau de 6 → 7 (plafond du tronçon : surcoût de
    l'anneau, sans le compter comme parcours d'anneau), ce qui laisse son
    virage approcher 6 → 7 ; green 10 et boîte 10 se touchent (liaisons
    triviales). Les greens, boîtes et cases inutilisés restent loin de
    tout chemin."""
    tee9 = [(72.7, 8.999), (72.2, 11.0), (70.2, 11.0), (70.7, 9.0)]
    hole9 = _hole(9, (156, 10, 160, 14), [])
    hole9["features"]["tees"] = [{"outline": [{"x": x, "y": y} for x, y in tee9]}]
    return [_hole(6, (66, 2.2, 70, 6.2), [(140, 2, 142, 4)]),
            _hole(7, (144, 2, 148, 6), [(110, 4.2, 112, 6.2)]),
            _hole(8, (112.7, 9.6, 116.7, 13.6), [(150, 10, 152, 12)]),
            hole9,
            _hole(10, (160, 0, 164, 4), [(164, 0, 166, 2)])]


def bends_json(*, style: str = "links") -> dict:
    """JSON 3.2 fabriqué, 170 × 100, pour les virages (seed 0 : tirages de
    ``bend_rng(0, k)`` fixes) : 10 trous, liaisons droites clubhouse → 1
    (≈ 44 blocs, un virage), 1 → 2 (≈ 71, un S), 2 → 3 (≈ 46, fairway des
    deux côtés : virage abandonné), 3 → 4 (≈ 46, fairway des deux côtés
    plus loin : décalage tiré 4,97 réduit), 4 → 5 (≈ 76, fairway sous le
    sommet du second virage du S : S impossible, repli sur un virage seul),
    5 → clubhouse (≈ 29, aucun virage) ; puis, en haut à droite, un essai
    refusé par ``verify`` (``bend_reject_holes``) : 6 → 7 (droite y 6,2,
    un virage vers le haut, ancrage posé), deux liaisons triviales 10 → 10
    (pour que 8 → 9 tire le flux de la liaison 9 : côté vers 6 → 7, décalage
    3,94), 8 → 9 (parallèle à 3 blocs, en sens inverse) : son premier essai,
    côté 6 → 7, passe ``bend_ok`` mais recouvre l'ancrage de 6 → 7, refusé
    par ``verify`` (``verify_rejects``), puis le virage part de l'autre
    côté (links seulement ; en parkland, la largeur 3 écarte le premier
    essai dès ``bend_ok``)."""
    def strip(x0, x1, y0, y1):
        return (x0, y0, x1, y1)

    return {
        "metadata": {"style": style},
        "terrain": {"width": BENDS_WIDTH, "height": BENDS_HEIGHT},
        "routing": {
            "clubhouse": {"x": 150.0, "y": 100.0, "edge": "S"},
            "holes": [
                _hole(1, (5, 70, 9, 74), [(100, 94, 102, 96)]),
                _hole(2, (10, 10, 14, 14), [(80, 71, 82, 73)],
                      fairway=[strip(16, 58, 7, 10), strip(16, 58, 14, 17)]),
                _hole(3, (70, 30, 74, 34), [(60, 11, 62, 13)],
                      fairway=[strip(76, 118, 20, 28), strip(76, 118, 35, 44)]),
                _hole(4, (10, 50, 14, 54), [(120, 31, 122, 33)],
                      fairway=[strip(60, 70, 46, 50), strip(60, 70, 54, 58)]),
                _hole(5, (135, 60, 139, 64), [(90, 51, 92, 53)]),
                *bend_reject_holes()],
            "links": [{"from": "clubhouse", "to": 1}, {"from": 1, "to": 2},
                      {"from": 2, "to": 3}, {"from": 3, "to": 4},
                      {"from": 4, "to": 5}, {"from": 5, "to": "clubhouse"},
                      # les deux 10 → 10 (triviales, rien de posé) ne servent
                      # qu'à décaler l'indice de 8 → 9 jusqu'à 9 : ses tirages
                      # viennent de bend_rng(0, 9) (seed 0, indice dans
                      # routing.links), qui donnent le côté vers 6 → 7 et le
                      # décalage 3,94 du refus par verify ; retirer, ajouter ou
                      # déplacer une liaison avant 8 → 9 change ce flux et casse
                      # le cas (verify_rejects)
                      {"from": 6, "to": 7}, {"from": 10, "to": 10},
                      {"from": 10, "to": 10}, {"from": 8, "to": 9}]},
        "bunkers": {"items": []},
    }


def bends_variant(style: str = "links") -> tuple[dict, SimpleNamespace]:
    """JSON des virages (``bends_json``) et ce que doit rendre
    ``course_input_from_json`` à sa place : sans eau, relief plat."""
    stub = SimpleNamespace(water=WaterMask(water=np.zeros((BENDS_HEIGHT, BENDS_WIDTH), bool)),
                           relief=np.full((BENDS_HEIGHT, BENDS_WIDTH), 64.0))
    return bends_json(style=style), stub


# === Parcours des chemins posés (R3) ===

def paths_cases() -> list:
    """Paramètres pytest des parcours de ``place_paths`` : fabriqués
    (``FABRICATED`` et ``bends_json``, deux styles) et seeds rapides, puis
    lentes (``slow``). Cas : ``("fab", variante, style)``, ``("bends",
    "bends", style)``, ``("seed", seed, style)``."""
    import pytest
    return ([pytest.param(("fab", v, st), id=f"fab-{v}-{st}") for v in FABRICATED for st in STYLES]
            + [pytest.param(("bends", "bends", st), id=f"bends-{st}") for st in STYLES]
            + [pytest.param(("seed", s, st), id=f"s{s}-{st}") for s, st in FAST]
            + [pytest.param(("seed", s, st), id=f"s{s}-{st}", marks=pytest.mark.slow)
               for s, st in SLOW])


def case_input(case, request) -> tuple[dict, SimpleNamespace | None]:
    """JSON d'un cas de ``paths_cases`` et, pour un parcours fabriqué, ce
    que doit rendre ``course_input_from_json`` (``None`` : seed réelle,
    relue dans le cache ``corpus_dir``)."""
    kind, key, style = case
    if kind == "fab":
        return fabricated_variant(key, style)
    if kind == "bends":
        return bends_variant(style)
    return corpus_json(request.getfixturevalue("corpus_dir"), key, style), None
