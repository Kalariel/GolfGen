"""Export JSON du parcours de golf."""

from __future__ import annotations

import base64
import json
from pathlib import Path
from typing import Any, Optional

import numpy as np

from .config import CourseConfig


class JSONExporter:
    """Sérialise les données du parcours en JSON."""

    def __init__(self, config: CourseConfig):
        self.config = config
        self.data: dict[str, Any] = {
            "metadata": {
                "version": "1.0",
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

        # Normaliser en uint8 [0, 255]
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

    def add_paving(self, owner: np.ndarray, seeds: list[tuple[int, int]],
                    pars: list[int]) -> None:
        """Ajoute les données de paving (cellules Voronoi)."""
        self.data["metadata"]["pipeline_stages"].append("paving")
        tile_size = self.config.paving.tile_size
        th, tw = owner.shape

        # Encoder owner en base64 int16
        owner_int16 = owner.astype(np.int16)
        encoded = base64.b64encode(owner_int16.tobytes()).decode('ascii')

        cells = []
        for i, ((sx, sy), par) in enumerate(zip(seeds, pars)):
            tile_count = int((owner == i).sum())
            cells.append({
                "id": i,
                "par": par,
                "seed_tx": sx,
                "seed_ty": sy,
                "tile_count": tile_count,
            })

        self.data["paving"] = {
            "tile_size": tile_size,
            "grid_width": tw,
            "grid_height": th,
            "owner": {
                "encoding": "base64_int16",
                "data": encoded,
            },
            "cells": cells,
        }

    def add_clubhouse(self, clubhouse_data: dict) -> None:
        """Ajoute les données du clubhouse."""
        self.data["metadata"]["pipeline_stages"].append("clubhouse")
        self.data["clubhouse"] = clubhouse_data

    def add_routing(self, holes: list[dict]) -> None:
        """Ajoute les données de routing."""
        self.data["metadata"]["pipeline_stages"].append("routing")
        self.data["routing"] = {
            "holes": holes,
        }

    def add_hazards(self, bunkers: list[dict], water_bodies: list[dict],
                     ravines: list[dict]) -> None:
        """Ajoute les obstacles."""
        self.data["metadata"]["pipeline_stages"].append("hazards")
        self.data["hazards"] = {
            "bunkers": bunkers,
            "water_bodies": water_bodies,
            "ravines": ravines,
        }

    def add_vegetation(self, tree_clusters: list[dict],
                        dense_forests: list[dict]) -> None:
        """Ajoute la végétation."""
        self.data["metadata"]["pipeline_stages"].append("vegetation")
        self.data["vegetation"] = {
            "tree_clusters": tree_clusters,
            "dense_forests": dense_forests,
        }

    def add_features(self, features: dict) -> None:
        """Ajoute les structures (ponts, ruisseaux, etc.)."""
        self.data["metadata"]["pipeline_stages"].append("features")
        self.data["features"] = features

    def export(self, path: str | Path) -> None:
        """Écrit le JSON sur disque."""
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(self.data, f, indent=2, ensure_ascii=False)
        print(f"Export: {path} ({path.stat().st_size / 1024:.1f} Ko)")
