"""Génération de terrain par Perlin noise (OpenSimplex)."""

from __future__ import annotations

import numpy as np
import opensimplex

from .config import CourseConfig


class TerrainGenerator:
    """Génère une heightmap via OpenSimplex multi-octave."""

    def __init__(self, config: CourseConfig):
        self.config = config
        self.tc = config.terrain
        self.rng = np.random.default_rng(config.seed)

    def generate(self) -> np.ndarray:
        """Génère la heightmap (float32, valeurs en élévation Minecraft).

        Returns:
            np.ndarray de shape (height, width) avec des valeurs dans
            [elevation_min, elevation_max].
        """
        w, h = self.config.width, self.config.height
        raw = self._multi_octave_noise(w, h)
        raw = self._apply_ns_gradient(raw, h)
        # _apply_central_flat retiré — fait par l'étape clubhouse
        heightmap = self._normalize(raw)
        return heightmap

    def _multi_octave_noise(self, w: int, h: int) -> np.ndarray:
        """Bruit OpenSimplex multi-octave (vectorisé)."""
        opensimplex.seed(self.config.seed)

        # Coordonnées de la grille
        xs = np.arange(w, dtype=np.float64)
        ys = np.arange(h, dtype=np.float64)

        result = np.zeros((h, w), dtype=np.float64)
        amplitude = 1.0
        frequency = 1.0
        max_amplitude = 0.0

        for _ in range(self.tc.octaves):
            scaled_x = xs * frequency / self.tc.scale
            scaled_y = ys * frequency / self.tc.scale
            noise = opensimplex.noise2array(scaled_x, scaled_y)
            result += noise * amplitude
            max_amplitude += amplitude
            amplitude *= self.tc.persistence
            frequency *= 2.0

        result /= max_amplitude
        return result

    def _apply_ns_gradient(self, raw: np.ndarray, h: int) -> np.ndarray:
        """Ajoute un léger gradient nord-sud (plus haut au nord = y=0)."""
        gradient = np.linspace(self.tc.ns_gradient_strength, -self.tc.ns_gradient_strength, h)
        raw += gradient[:, np.newaxis]
        return raw

    def _apply_central_flat(self, raw: np.ndarray, w: int, h: int) -> np.ndarray:
        """Aplatit la zone centrale (clubhouse) vers base_elevation."""
        cx = self.config.clubhouse_x
        cy = self.config.clubhouse_y
        radius = self.tc.central_flat_radius
        transition = self.tc.central_flat_transition

        # Valeur cible pour la zone centrale (0 dans l'espace brut = base_elevation)
        target = 0.0

        yy, xx = np.mgrid[0:h, 0:w]
        dist = np.sqrt((xx - cx) ** 2 + (yy - cy) ** 2)

        # Facteur de mélange : 1 au centre, 0 au-delà de radius + transition
        blend = np.clip((dist - radius) / transition, 0.0, 1.0)

        raw = raw * blend + target * (1 - blend)
        return raw

    @staticmethod
    def water_mask(heightmap: np.ndarray, water_level: float) -> np.ndarray:
        """Retourne un masque booleen : True = eau (elevation < water_level)."""
        return heightmap < water_level

    def _normalize(self, raw: np.ndarray) -> np.ndarray:
        """Normalise dans [elevation_min, elevation_max]."""
        lo, hi = raw.min(), raw.max()
        if hi - lo < 1e-10:
            return np.full_like(raw, self.tc.base_elevation, dtype=np.float32)

        normalized = (raw - lo) / (hi - lo)
        elev_range = self.tc.elevation_max - self.tc.elevation_min
        heightmap = (normalized * elev_range + self.tc.elevation_min).astype(np.float32)
        return heightmap
