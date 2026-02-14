"""Génération de formes de trous individuels en coordonnées locales."""

from __future__ import annotations

import math
import random
from dataclasses import dataclass

from golfgen.config import CourseConfig


@dataclass
class HoleShape:
    """Forme d'un trou en coordonnées locales (tee à l'origine, axe Y+)."""
    par: int
    length: int               # distance polyline en blocs
    waypoints: list[tuple]    # [(x, y), ...] — tee=(0,0)
    fairway_width: int
    green_radius: int


class HoleGenerator:
    """Génère les formes des 18 trous paramétriquement."""

    def __init__(self, config: CourseConfig):
        self.config = config
        self.rc = config.routing
        self.rng = random.Random(config.seed)

    def generate_all(self) -> list[HoleShape]:
        """Génère les 18 formes de trous."""
        pars = self.rc.par_distribution[:self.config.num_holes]
        return [self._generate_hole(par) for par in pars]

    def generate_one(self, par: int) -> HoleShape:
        """Génère une forme de trou pour un par donné."""
        return self._generate_hole(par)

    def _generate_hole(self, par: int) -> HoleShape:
        """Génère un trou paramétrique."""
        rc = self.rc

        # Longueur cible
        ranges = {3: rc.par3_range, 4: rc.par4_range, 5: rc.par5_range}
        lo, hi = ranges[par]
        target_length = self.rng.randint(lo, hi)

        # Largeur fairway
        fw_map = {3: rc.fairway_width_par3, 4: rc.fairway_width_par4,
                  5: rc.fairway_width_par5}
        fairway_width = fw_map[par]

        # Green radius
        green_radius = self.rng.randint(rc.green_radius_min, rc.green_radius_max)

        # Nombre de segments
        if par == 3:
            n_segments = self.rng.randint(1, 2)
        elif par == 4:
            n_segments = self.rng.randint(3, 4)
        else:
            n_segments = self.rng.randint(4, 6)

        # Construire les waypoints
        waypoints = self._build_waypoints(target_length, n_segments, par)

        # Calculer la longueur réelle
        length = 0
        for i in range(len(waypoints) - 1):
            dx = waypoints[i + 1][0] - waypoints[i][0]
            dy = waypoints[i + 1][1] - waypoints[i][1]
            length += math.sqrt(dx * dx + dy * dy)

        return HoleShape(
            par=par,
            length=int(length),
            waypoints=waypoints,
            fairway_width=fairway_width,
            green_radius=green_radius,
        )

    def _build_waypoints(self, target_length: int, n_segments: int,
                         par: int) -> list[tuple]:
        """Construit une polyligne organique du tee au green.

        Le tee est à (0, 0). La direction principale est Y+ (vers le haut).
        Les segments avancent principalement en Y avec des déviations latérales
        pour créer des doglegs naturels.
        """
        seg_len = target_length / n_segments
        points = [(0.0, 0.0)]

        # Déviation latérale max selon le par
        max_lateral = {3: 5, 4: 15, 5: 25}[par]

        # Direction cumulative (commence droit vers Y+)
        cum_x = 0.0
        cum_y = 0.0

        for i in range(n_segments):
            # Déviation latérale (plus forte au milieu du trou)
            progress = (i + 1) / n_segments
            mid_factor = 1.0 - abs(progress - 0.5) * 2  # max au milieu
            lateral = self.rng.uniform(-max_lateral, max_lateral) * mid_factor

            # Avancée principale (Y+) avec légère variation
            advance = seg_len * self.rng.uniform(0.85, 1.15)

            cum_x += lateral
            cum_y += advance
            points.append((cum_x, cum_y))

        # Ajuster la longueur totale pour matcher la cible
        actual_len = sum(
            math.sqrt((points[i + 1][0] - points[i][0]) ** 2 +
                       (points[i + 1][1] - points[i][1]) ** 2)
            for i in range(len(points) - 1)
        )
        if actual_len > 0:
            scale = target_length / actual_len
            points = [(p[0] * scale, p[1] * scale) for p in points]
            # Garder le tee à l'origine
            points[0] = (0.0, 0.0)

        return points
