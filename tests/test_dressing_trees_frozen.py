"""Sortie de production des arbres figée : empreintes du JSON 3.4 écrit par
``pipeline.py`` au réglage par défaut, comme les empreintes des chemins
(``tests/test_dressing_paths_frozen.py``).

Corpus : 4 seeds × 2 styles (``TREES_FROZEN``), produit en parallèle par
``tests.paths_corpus.ensure_corpus`` sans option (le 3.4 par défaut) dans le
cache de pytest (``.pytest_cache/d/golfgen-trees-corpus-<empreinte>``, même
empreinte des sources que le corpus des chemins). Rapide : ``TREES_FROZEN_FAST`` ;
le reste avec ``--run-slow``.

Empreinte : sha256 du JSON réécrit à l'identique du fichier (``indent=2``,
``ensure_ascii=False``) normalisé par ``tests.frozen.normalize_frozen``
(horloge et version du paquet). Tout le JSON est couvert : un changement du
routage, de l'habillage, des bunkers, des chemins ou des arbres fait échouer
ces tests.
"""

import hashlib
import json

import pytest

from tests.frozen import normalize_frozen
from tests.paths_corpus import corpus_json, ensure_corpus, source_fingerprint

TREES_FROZEN_FAST = ((4, "links"),)
TREES_FROZEN = TREES_FROZEN_FAST + ((4, "parkland"), (28399, "parkland"), (28399, "links"),
                                    (85660, "parkland"), (85660, "links"), (50140, "parkland"),
                                    (50140, "links"))
CACHE_KEY = f"golfgen-trees-corpus-{source_fingerprint()}"

# Empreintes de la production au 2026-11-09 (lot 5, R6), parité avec l'étude
# (retirée au R7) vérifiée sur ses 10 seeds × 2 styles : tout changement de la sortie
# les fait échouer ; à mettre à jour seulement pour un changement voulu et
# validé.
FINGERPRINTS = {
    (4, "links"): "5012c44004200e0f590caa2e4a3a489e8379d3d81cf91720659597e9cc356c4c",
    (4, "parkland"): "992a85910c2c76c92b575474b59c860780fbdd297b0e01ab7d213a900cb408c7",
    (28399, "parkland"): "72bd2227eb054dea5ad2e613673fc230357733baf9806cdb1f26f8c90dc5a98b",
    (28399, "links"): "ae64fbbfdd4c34912a0b111d612e0af138be0a9a67722114b32bdb8eca18d324",
    (85660, "parkland"): "05feae91ba348fc9623888b733b172fe2d12c8d3c3b616c68d375bc100761c7f",
    (85660, "links"): "89f1f641242fd7ec9f50ae6a937be796f7007a55b8f9ed81ae5d5cd60914690c",
    (50140, "parkland"): "2f41b6f6758a62d8047a917ecb4cbf4d62edcbd274c0d6f8f3c221bd9391e37a",
    (50140, "links"): "b06b7765a643b07fb22741732a7178c57bc2e7a2c15443c945b6a8da5470a9bd",
}


@pytest.fixture(scope="module")
def trees_corpus_dir(request):
    path = request.config.cache.mkdir(CACHE_KEY)
    ensure_corpus(path, TREES_FROZEN if request.config.getoption("--run-slow") else TREES_FROZEN_FAST, extra=())
    return path


def _sha(data: dict) -> str:
    data = normalize_frozen(data)
    return hashlib.sha256(json.dumps(data, indent=2, ensure_ascii=False).encode("utf-8")).hexdigest()


@pytest.mark.parametrize(
    "seed, style",
    [pytest.param(*course, id=f"s{course[0]}-{course[1]}",
                  marks=() if course in TREES_FROZEN_FAST else pytest.mark.slow)
     for course in TREES_FROZEN])
def test_default_output_is_frozen(seed, style, trees_corpus_dir):
    data = corpus_json(trees_corpus_dir, seed, style, extra=())
    assert data["metadata"]["version"] == "3.4" and data["metadata"]["style"] == style
    assert data["trees"]["items"]
    assert _sha(data) == FINGERPRINTS[(seed, style)]


def test_every_frozen_course_has_a_fingerprint():
    assert set(TREES_FROZEN) == set(FINGERPRINTS)
