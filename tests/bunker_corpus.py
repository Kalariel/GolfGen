"""Corpus des tests de bunkers : parcours figés de ``tests/data/dressing_holes_30x2.json``
(graines 1–30, links 400×300 ou 300×400), habillés et mis en contexte par le
seul code de production (``dress_course``, ``BunkerContext``), sans eau
par défaut."""

from __future__ import annotations

from functools import lru_cache
import json
from pathlib import Path
from types import SimpleNamespace

from golfgen.dressing import dress_course
from golfgen.dressing.bunkers.context import BunkerContext
from golfgen.routing.model import ElasticHole

SNAPSHOT = Path(__file__).resolve().parent / "data" / "dressing_holes_30x2.json"
SIZE = (400, 300)


@lru_cache(maxsize=1)
def _courses() -> dict:
    data = json.loads(SNAPSHOT.read_text(encoding="utf-8"))
    return {(c["seed"], c["size"]): c for c in data["courses"]}


def corpus_holes(seed: int, size: tuple[int, int] = SIZE) -> list[ElasticHole]:
    """Trous figés de la graine ``seed`` (``ElasticHole``, ordre du fichier)."""
    course = _courses()[(seed, "x".join(map(str, size)))]
    return [ElasticHole.from_dict(h) for h in course["holes"]]


@lru_cache(maxsize=8)
def corpus_dressing(seed: int, style: str = "links", size: tuple[int, int] = SIZE):
    """Habillage ``style`` des trous figés (seed du parcours)."""
    holes = tuple(corpus_holes(seed, size))
    return holes, dress_course(SimpleNamespace(layout=SimpleNamespace(holes=holes)), seed=seed, style=style)


def corpus_context(seed: int, *, water=None, limits: tuple[int, int] | None = None,
                   style: str = "links", size: tuple[int, int] = SIZE) -> BunkerContext:
    """``BunkerContext`` de la graine ``seed`` (carte ``limits``, défaut ``size``)."""
    holes, dressing = corpus_dressing(seed, style, size)
    width, height = limits or size
    return BunkerContext(holes, dressing, width, height, water=water)
