"""Habillage d'un parcours routé : point d'entrée ``dress_course``."""

from __future__ import annotations

from types import MappingProxyType

import numpy as np

from golfgen.dressing.green import green_shape
from golfgen.dressing.model import STYLE_SPECS, CourseDressing, HoleDressing
from golfgen.routing.geometry import build_hole_geometry


# Étiquette du flux aléatoire de l'habillage : ``[seed, RNG_LABEL, order]``.
# Le routeur n'emploie que des suites de un ou deux éléments après la seed
# (sites : 0/1 ; muirfield : 7, 11, 13, 17, 23, 31) : flux disjoint, donc
# changer l'habillage ou le style ne change jamais le tracé.
RNG_LABEL = 0xD7E5


def dress_course(result, *, seed: int, style: str) -> CourseDressing:
    """Habillage du parcours ``result`` (``MuirfieldResult``, ou tout objet
    portant ``layout: CourseLayout``) pour le ``style`` donné.

    Fonction pure : ni I/O, ni état global ; aléa tiré d'un flux propre à
    chaque trou, ``np.random.default_rng([seed, RNG_LABEL, order])``.
    ``seed`` est la seed u64 donnée au routage (``golfgen.seed.seed_u64``).
    Ne lit que le tracé, ne le modifie pas."""
    if isinstance(seed, bool) or not isinstance(seed, int):
        raise TypeError("seed doit être un entier")
    if not 0 <= seed < 2 ** 64:
        raise ValueError("seed attendue sous forme u64 (0 ≤ seed < 2^64)")
    if style not in STYLE_SPECS:
        raise ValueError(f"style inconnu : {style!r} (attendu : {', '.join(STYLE_SPECS)})")
    spec = STYLE_SPECS[style]
    holes = {}
    for hole in sorted(result.layout.holes, key=lambda h: h.order):
        rng = np.random.default_rng([seed, RNG_LABEL, hole.order])
        core = build_hole_geometry(hole).core
        holes[hole.order] = HoleDressing(order=hole.order,
                                         green=green_shape(hole, core, rng, spec))
    return CourseDressing(style=style, holes=MappingProxyType(holes))
