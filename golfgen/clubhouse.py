"""Sélection de la position du clubhouse."""

from __future__ import annotations

import math
import random

from golfgen.config import CourseConfig


def pick_clubhouse(config: CourseConfig, rng: random.Random) -> tuple[tuple[float, float], float]:
    """Choisit un coin pour le clubhouse.

    Retourne (position, angle_separation) où l'angle separe les deux nines
    en secteurs angulaires depuis le coin (utilise par le placement/sequencage).
    """
    w, h = config.width, config.height
    margin = config.routing.clubhouse_margin
    corners = [
        ((margin, margin), math.pi / 4),                 # NO
        ((w - margin, margin), 3 * math.pi / 4),         # NE
        ((margin, h - margin), -math.pi / 4),            # SO
        ((w - margin, h - margin), -3 * math.pi / 4),    # SE
    ]
    idx = rng.randint(0, 3)
    return corners[idx]
