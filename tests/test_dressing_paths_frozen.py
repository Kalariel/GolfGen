"""Sortie de production des chemins figée : empreintes du JSON 3.3 écrit par
``pipeline.py --no-trees`` (corpus ``tests/paths_corpus.py``,
``FROZEN``), comme les empreintes des bunkers
(``tests/test_dressing_bunkers_course.py``).

Empreinte : sha256 du JSON réécrit à l'identique du fichier (``indent=2``,
``ensure_ascii=False``) normalisé par ``tests.frozen.normalize_frozen``
(horloge et version du paquet). Tout le JSON est couvert : un changement du
routage, de l'habillage ou des bunkers fait aussi échouer ces tests.
"""

import hashlib
import json

import pytest

from tests.frozen import normalize_frozen
from tests.paths_corpus import FROZEN, FROZEN_FAST, corpus_json

# Empreintes de la production au 2026-11-08 (f208092), relevées avant le
# retrait de l'étude et des variantes ``legacy`` : tout changement de la
# sortie les fait échouer ; à mettre à jour seulement pour un changement
# voulu et validé.
FINGERPRINTS = {
    (50, "links"): "e4492aed628c89d01d0907591b6d5a185c67952b2296501b89576d5537e1654a",
    (89, "links"): "b837328667bcf6b28d13e3000a0d9a9c546a2c372f4da8ea2aa4f0686ef04df5",
    (12501, "parkland"): "ea137806b0e55cab2f8423fb4234b25cacecc3468eb2322b0d5537d1163ab7e1",
    (86624, "links"): "dfe074534ec24bda02235082fb573d5b29c4330e8805b2eea3b1fbecc3112c88",
    (57872, "parkland"): "17a78b09b366fa04fbaff909771b023137c8e6d2caef7bc431a5bfbf4b098adb",
    (112392, "links"): "3e8f040929b9d886b13aeb9a8cdb815e5ba1cfdcb00f362c893b6dbda75dba4b",
    (112392, "parkland"): "1da2ce3966acff63cf438d97a8e9123b5fef793671fe4ac8a96ccfe56b64a4fd",
    (145162, "links"): "8554966fe669370248966e70bf588c3ce80d3550bd4ed17fe3336ba60192b4ff",
    (145162, "parkland"): "afa71f15c01726ac34940ffb87f63e584a4e5923b0bc809f1f32c71be6ffad16",
    (1, "links"): "6d72f7cf064783c96d656875d71ebaa58d73f4c1238a366a6186faa8a0f8c304",
    (14, "parkland"): "cd52c36cffa0023c486fb17fa59846ecc5147a096853173af63e43822abd1113",
    (46, "links"): "1d58b56a02d06448fbe8d4462e63cbc632573167df562db3f54ef631c7d9308c",
    (109, "links"): "9d8f9569ff29460b4651f0e35057812a81d4b34c6f93cb122b60a32f9a0f250a",
}
WITH_BRIDGES = {(50, "links"), (89, "links"), (12501, "parkland"), (86624, "links"),
                (57872, "parkland"), (46, "links")}


def _sha(data: dict) -> str:
    data = normalize_frozen(data)
    return hashlib.sha256(json.dumps(data, indent=2, ensure_ascii=False).encode("utf-8")).hexdigest()


@pytest.mark.parametrize(
    "seed, style",
    [pytest.param(*course, id=f"s{course[0]}-{course[1]}",
                  marks=() if course in FROZEN_FAST else pytest.mark.slow)
     for course in FROZEN])
def test_default_output_is_frozen(seed, style, corpus_dir):
    data = corpus_json(corpus_dir, seed, style)
    assert data["metadata"]["version"] == "3.3" and data["metadata"]["style"] == style
    assert _sha(data) == FINGERPRINTS[(seed, style)]
    assert bool(data["paths"]["bridge_cells"]) == ((seed, style) in WITH_BRIDGES)


def test_every_frozen_course_has_a_fingerprint():
    assert set(FROZEN) == set(FINGERPRINTS)
