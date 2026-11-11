"""Habillage du parcours routé (greens, départs, fairway, sélection des greens
doubles), en mémoire (``dress_course``) ou depuis le seul JSON du routage
(``dress_course_json``).

Dépend du tracé (``golfgen.routing``), jamais l'inverse : l'habillage lit le
parcours et ne le modifie pas.
"""

from golfgen.dressing.course import dress_course
from golfgen.dressing.rng import RNG_LABEL
from golfgen.dressing.from_json import (CourseInput, CourseJsonError, course_input_from_json,
                                        dress_course_json)
from golfgen.dressing.model import (GREEN_KINDS, STYLE_SPECS, CourseDressing, DressingError,
                                    FairwayShape, GreenIsland, GreenPair, GreenShape,
                                    HoleDressing, PairRejection, StyleSpec, TeeBox, TeeIsland,
                                    WaterFix)
from golfgen.dressing.water import effective_water

__all__ = ["GREEN_KINDS", "RNG_LABEL", "STYLE_SPECS", "CourseDressing", "CourseInput",
           "CourseJsonError", "DressingError", "FairwayShape", "GreenIsland", "GreenPair",
           "GreenShape", "HoleDressing", "PairRejection", "StyleSpec", "TeeBox", "TeeIsland",
           "WaterFix",
           "course_input_from_json", "dress_course", "dress_course_json", "effective_water"]
