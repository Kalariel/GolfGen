"""Configuration dataclasses pour la génération de parcours de golf."""

from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Optional


@dataclass
class TerrainConfig:
    """Paramètres de génération du terrain."""
    octaves: int = 6
    persistence: float = 0.5
    scale: float = 120.0
    elevation_min: int = 58
    elevation_max: int = 82
    base_elevation: int = 64
    central_flat_radius: int = 45
    central_flat_transition: int = 25
    ns_gradient_strength: float = 0.15


@dataclass
class RoutingConfig:
    """Paramètres de génération et placement des trous."""
    par_distribution: list[int] = field(
        default_factory=lambda: [4, 3, 5, 4, 3, 4, 5, 3, 4,
                                  4, 5, 3, 4, 4, 5, 3, 4, 4]
    )
    # Distances cible (en blocs, 1 bloc = 3m)
    par3_range: tuple[int, int] = (50, 70)
    par4_range: tuple[int, int] = (110, 150)
    par5_range: tuple[int, int] = (170, 195)
    # Largeurs de fairway
    fairway_width_par3: int = 9
    fairway_width_par4: int = 12
    fairway_width_par5: int = 13
    # Green
    green_radius_min: int = 6
    green_radius_max: int = 10
    # Placement
    tee_link_distance: int = 20  # distance max green→tee suivant
    grid_margin: int = 15        # marge min des bords de la carte
    segment_length: int = 35     # longueur des segments waypoints


@dataclass
class CourseConfig:
    """Configuration complète du parcours."""
    width: int = 350
    height: int = 350
    seed: int = 42
    num_holes: int = 18
    total_par: int = 72
    scale_ratio: float = 3.0

    terrain: TerrainConfig = field(default_factory=TerrainConfig)
    routing: RoutingConfig = field(default_factory=RoutingConfig)
    method: str = "ga"

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_json(cls, path: str | Path) -> CourseConfig:
        """Charge la config depuis un fichier JSON."""
        with open(path, 'r') as f:
            data = json.load(f)

        config = cls()

        for key in ('width', 'height', 'seed', 'num_holes', 'total_par',
                     'scale_ratio'):
            if key in data:
                setattr(config, key, data[key])

        sub_configs = {
            'terrain': (config.terrain, TerrainConfig),
            'routing': (config.routing, RoutingConfig),
        }
        for section, (obj, _cls) in sub_configs.items():
            if section in data:
                for k, v in data[section].items():
                    if hasattr(obj, k):
                        setattr(obj, k, v)

        return config

    def save_json(self, path: str | Path) -> None:
        """Sauvegarde la config en JSON."""
        with open(path, 'w') as f:
            json.dump(self.to_dict(), f, indent=2)
