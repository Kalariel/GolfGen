"""Orchestration du pipeline de génération de parcours (étapes 1 à 4).

1. Squelettes indépendants (golfgen/hole_gen.py)
2. Placement/packing sans ordre de jeu (golfgen/packing.py)
3. Séquençage : ordre de jeu + sens de chaque trou (golfgen/sequencing.py)
4. Assemblage final (ci-dessous) : ids, élévations, direction — au format
   attendu par golfgen/exporter.py.
"""

from __future__ import annotations

import random

import numpy as np

from golfgen.clubhouse import pick_clubhouse
from golfgen.config import CourseConfig
from golfgen.hole_gen import HoleGenerator
from golfgen.packing import Packer
from golfgen.sequencing import ordered_waypoints, sequence
from golfgen.terrain import TerrainGenerator
from golfgen.utils import direction_label, polyline_length


def build_course(config: CourseConfig,
                  heightmap: np.ndarray | None) -> tuple[list[dict], tuple[float, float]]:
    """Génère les n trous du parcours et retourne (holes, clubhouse_pos)."""
    # RNG séparé de celui de HoleGenerator (seedé indépendamment sur
    # config.seed) — deux flux déterministes indépendants plutôt que de
    # threader un seul RNG à travers toutes les étapes.
    rng = random.Random(config.seed + 1)

    clubhouse_pos, _sep_angle = pick_clubhouse(config, rng)
    shapes = HoleGenerator(config).generate_all()
    pieces = Packer(config, clubhouse_pos, rng).pack(shapes)
    order, flips = sequence(pieces, clubhouse_pos, config)

    holes = []
    for position, piece_idx in enumerate(order):
        piece = pieces[piece_idx]
        wps = ordered_waypoints(piece, flips[piece_idx])
        tee, green = wps[0], wps[-1]

        holes.append({
            "id": position + 1,
            "par": piece.shape.par,
            "blocks": int(polyline_length(wps)),
            "tee": {
                "x": round(tee[0], 1), "y": round(tee[1], 1),
                "elevation": TerrainGenerator.sample_elevation(heightmap, tee[0], tee[1]),
            },
            "green": {
                "x": round(green[0], 1), "y": round(green[1], 1),
                "radius": piece.shape.green_radius,
                "elevation": TerrainGenerator.sample_elevation(heightmap, green[0], green[1]),
            },
            "waypoints": [{"x": round(p[0], 1), "y": round(p[1], 1)} for p in wps],
            "fairway_width": piece.shape.fairway_width,
            "direction": direction_label(tee, green),
        })

    return holes, clubhouse_pos
