"""Export JSON du parcours de golf."""

from __future__ import annotations

import base64
import json
from pathlib import Path
from typing import Any

import numpy as np

from .config import CourseConfig


class JSONExporter:
    """Sérialise les données du parcours en JSON."""

    def __init__(self, config: CourseConfig):
        self.config = config
        self.data: dict[str, Any] = {
            "metadata": {
                "version": "2.0",
                "seed": config.seed,
                "config": {
                    "width": config.width,
                    "height": config.height,
                    "scale_ratio": config.scale_ratio,
                    "base_elevation": config.terrain.base_elevation,
                },
                "pipeline_stages": [],
            }
        }

    def add_terrain(self, heightmap: np.ndarray) -> None:
        """Ajoute la heightmap au JSON (encodée en base64 uint8)."""
        if "terrain" not in self.data["metadata"]["pipeline_stages"]:
            self.data["metadata"]["pipeline_stages"].append("terrain")

        h, w = heightmap.shape
        elev_min = float(heightmap.min())
        elev_max = float(heightmap.max())

        if elev_max - elev_min < 1e-10:
            uint8_data = np.zeros((h, w), dtype=np.uint8)
        else:
            normalized = (heightmap - elev_min) / (elev_max - elev_min)
            uint8_data = (normalized * 255).astype(np.uint8)

        encoded = base64.b64encode(uint8_data.tobytes()).decode('ascii')

        self.data["terrain"] = {
            "width": w,
            "height": h,
            "elevation": {
                "encoding": "base64_uint8",
                "data": encoded,
                "min_elevation": round(elev_min, 2),
                "max_elevation": round(elev_max, 2),
            }
        }

    def add_routing(self, holes: list[dict],
                    clubhouse_pos: tuple[float, float] | None = None) -> None:
        """Ajoute les données de routing (18 trous)."""
        if "routing" not in self.data["metadata"]["pipeline_stages"]:
            self.data["metadata"]["pipeline_stages"].append("routing")
        self.data["routing"] = {
            "holes": holes,
        }
        if clubhouse_pos is not None:
            self.data["routing"]["clubhouse"] = {
                "x": round(clubhouse_pos[0], 1),
                "y": round(clubhouse_pos[1], 1),
            }

    def export(self, path: str | Path) -> None:
        """Écrit le JSON sur disque."""
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(self.data, f, indent=2, ensure_ascii=False)
        print(f"Export: {path} ({path.stat().st_size / 1024:.1f} Ko)")
