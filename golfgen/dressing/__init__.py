"""Habillage du parcours routé (greens ; tees et greens doubles à venir).

Dépend du tracé (``golfgen.routing``), jamais l'inverse : l'habillage lit le
parcours et ne le modifie pas.
"""

from golfgen.dressing.course import RNG_LABEL, dress_course
from golfgen.dressing.model import (GREEN_KINDS, STYLE_SPECS, CourseDressing, DressingError,
                                    GreenShape, HoleDressing, StyleSpec)

__all__ = ["GREEN_KINDS", "RNG_LABEL", "STYLE_SPECS", "CourseDressing", "DressingError",
           "GreenShape", "HoleDressing", "StyleSpec", "dress_course"]
