"""Bosquets d'ancrage des virages de chemin.

Portage de ``plant_anchors`` (étude du lot 5, retirée au R7). Chaque
ancrage de ``paths.anchors`` reçoit de 1 à 3 arbres (flux propre à son indice),
sur la case légale la plus proche à ``ANCHOR_REACH`` au plus, segment depuis
l'ancrage sans case de chemin ; rayon tiré, puis repli à ``ANCHOR_FALLBACK``.
Les couronnes peuvent entrer dans le corridor, jamais dans le cœur ``m = 0``
(interdits fournis par l'appelant). Un ancrage incomplet n'est jamais une
erreur : son motif est relevé (``partiel``, ``sans_place``).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

import numpy as np

from golfgen.dressing.rng import TREE_ANCHOR_LAYER, tree_rng
from golfgen.dressing.trees.errors import TreeError
from golfgen.dressing.trees.fill import draw_radius, greedy
from golfgen.dressing.trees.geometry import Tree
from golfgen.dressing.trees.strategic import segment_square_distance

ANCHOR_REACH = 8.0                  # blocs entre ancrage et centre d'arbre
ANCHOR_TREES = (1, 3)               # arbres d'un bosquet, bornes incluses
ANCHOR_FALLBACK = 2                 # blocs


@dataclass(frozen=True)
class AnchorGrove:
    """Bosquet d'un ancrage : indice dans ``paths.anchors``, case de
    l'ancrage, nombre d'arbres visé, arbres posés et motif (``None`` si
    complet, sinon ``partiel`` ou ``sans_place``)."""
    index: int
    anchor: tuple[int, int]
    target: int
    trees: tuple[Tree, ...]
    motif: str | None


def anchor_candidates(ax: int, az: int, paths: np.ndarray, shape: tuple[int, int]) -> np.ndarray:
    """Cases à ``ANCHOR_REACH`` au plus, segment depuis l'ancrage sans case de
    chemin, de la plus proche à la plus lointaine (égalités : y puis x)."""
    reach = int(ANCHOR_REACH)
    near = paths[np.abs(paths - (ax, az)).max(axis=1) <= reach + 1].tolist()
    found = [((x - ax) ** 2 + (y - az) ** 2, y, x)
             for y in range(max(az - reach, 0), min(az + reach, shape[0] - 1) + 1)
             for x in range(max(ax - reach, 0), min(ax + reach, shape[1] - 1) + 1)
             if (x - ax) ** 2 + (y - az) ** 2 <= ANCHOR_REACH ** 2
             and not any(segment_square_distance(px, pz, (ax + 0.5, az + 0.5), (x + 0.5, y + 0.5)) == 0.0
                         for px, pz in near)]
    return np.asarray([(x, y) for _, y, x in sorted(found)], dtype=np.int64).reshape(-1, 2)


def plant_anchors(data: Mapping[str, Any], solid: np.ndarray, crowns: np.ndarray, seed: int) -> tuple[AnchorGrove, ...]:
    """Bosquet de chaque ancrage, flux propre à l'index. Marque ``solid`` et
    ``crowns``. ``TreeError`` si le JSON n'a pas de ``paths.anchors``."""
    anchors = (data.get("paths") or {}).get("anchors")
    if anchors is None:
        raise TreeError("JSON sans paths.anchors : la pose des arbres exige les chemins")
    paths = np.asarray(data["paths"]["cells"], dtype=np.int64).reshape(-1, 2)
    groves = []
    for index, (ax, az) in enumerate(anchors):
        rng = tree_rng(seed, TREE_ANCHOR_LAYER, index)
        target = int(rng.integers(ANCHOR_TREES[0], ANCHOR_TREES[1] + 1))
        near = anchor_candidates(int(ax), int(az), paths, solid.shape)
        trees: list[Tree] = []
        for _ in range(target):
            for radius in dict.fromkeys((draw_radius(rng), ANCHOR_FALLBACK)):
                got = greedy(near, solid, crowns, rng, radius=radius, limit=1, shuffle=False)
                if got:
                    trees += got
                    break
        motif = None if len(trees) == target else "partiel" if trees else "sans_place"
        groves.append(AnchorGrove(index, (int(ax), int(az)), target, tuple(trees), motif))
    return tuple(groves)
