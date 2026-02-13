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
    # Masque de plaine centrale
    central_flat_radius: int = 45
    central_flat_transition: int = 25
    # Gradient nord-sud (terrain monte vers le nord)
    ns_gradient_strength: float = 0.15


@dataclass
class PavingConfig:
    """Paramètres du découpage Voronoi en cellules."""
    target_coverage: float = 0.92
    par3_weight: float = 1.0
    par4_weight: float = 1.5
    par5_weight: float = 2.0
    elongation: float = 1.8
    growth_slope_penalty: float = 2.0
    growth_noise: float = 0.3
    tile_size: int = 5
    water_level: float = 61.0


@dataclass
class RoutingConfig:
    """Paramètres de routing des trous."""
    par_distribution: list[int] = field(
        default_factory=lambda: [4, 3, 5, 4, 3, 4, 5, 3, 4,
                                  4, 5, 3, 4, 4, 5, 3, 4, 4]
    )
    par3_range: tuple[int, int] = (50, 70)
    par4_range: tuple[int, int] = (110, 150)
    par5_range: tuple[int, int] = (170, 195)
    fairway_width_par3: int = 9
    fairway_width_par4: int = 12
    fairway_width_par5: int = 13
    green_radius_min: int = 6
    green_radius_max: int = 10
    tee_width: int = 10
    tee_height: int = 6
    max_slope: float = 0.15
    collision_margin: int = 0
    max_retries: int = 3
    segment_length: int = 35


@dataclass
class HazardConfig:
    """Paramètres de placement des obstacles."""
    bunkers_per_green: tuple[int, int] = (1, 2)
    bunker_arc_min: float = 30.0
    bunker_arc_max: float = 60.0
    fairway_bunker_ratio: float = 0.66
    water_depth_threshold: float = -2.0
    ravine_gradient_threshold: float = 0.3


@dataclass
class VegetationConfig:
    """Paramètres de végétation."""
    border_forest_width: int = 50
    tree_cluster_density: float = 0.3
    dense_forest_min_area: int = 200


@dataclass
class FeatureConfig:
    """Paramètres des structures."""
    practice_range: bool = True
    putting_green: bool = True


@dataclass
class ClubhouseConfig:
    """Paramètres du clubhouse."""
    width: int = 45
    height: int = 35
    flat_radius_margin: int = 40
    flat_transition: int = 25
    practice_length: int = 70
    practice_width: int = 25
    putting_radius: int = 6


@dataclass
class CourseConfig:
    """Configuration complète du parcours."""
    width: int = 350
    height: int = 350
    seed: int = 42
    num_holes: int = 18
    total_par: int = 72
    scale_ratio: float = 3.0
    clubhouse_x: Optional[int] = None
    clubhouse_y: Optional[int] = None

    terrain: TerrainConfig = field(default_factory=TerrainConfig)
    paving: PavingConfig = field(default_factory=PavingConfig)
    routing: RoutingConfig = field(default_factory=RoutingConfig)
    hazards: HazardConfig = field(default_factory=HazardConfig)
    vegetation: VegetationConfig = field(default_factory=VegetationConfig)
    features: FeatureConfig = field(default_factory=FeatureConfig)
    clubhouse: ClubhouseConfig = field(default_factory=ClubhouseConfig)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_json(cls, path: str | Path) -> CourseConfig:
        """Charge la config depuis un fichier JSON."""
        with open(path, 'r') as f:
            data = json.load(f)

        config = cls()

        # Paramètres de premier niveau
        for key in ('width', 'height', 'seed', 'num_holes', 'total_par',
                     'scale_ratio', 'clubhouse_x', 'clubhouse_y'):
            if key in data:
                setattr(config, key, data[key])

        # Sous-configs
        sub_configs = {
            'terrain': (config.terrain, TerrainConfig),
            'paving': (config.paving, PavingConfig),
            'routing': (config.routing, RoutingConfig),
            'hazards': (config.hazards, HazardConfig),
            'vegetation': (config.vegetation, VegetationConfig),
            'features': (config.features, FeatureConfig),
            'clubhouse': (config.clubhouse, ClubhouseConfig),
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
