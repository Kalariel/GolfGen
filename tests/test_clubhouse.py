"""Tests pour le placement du clubhouse (seed 42)."""

import numpy as np
import pytest

from golfgen.config import CourseConfig
from golfgen.terrain import TerrainGenerator
from golfgen.paver import PavingGenerator
from golfgen.clubhouse import ClubhousePlacer


class TestClubhousePosition:
    """Vérifie que le clubhouse est correctement positionné."""

    def test_position_within_grid(self, clubhouse_result):
        result, _ = clubhouse_result
        assert 0 < result["x"] < 350
        assert 0 < result["y"] < 350

    def test_four_adjacent_cells(self, clubhouse_result):
        result, _ = clubhouse_result
        assert len(result["adjacent_cells"]) >= 4


class TestClubhouseFlattening:
    """Vérifie que le terrain est aplati autour du clubhouse."""

    def test_terrain_flattened(self, clubhouse_result):
        result, placer = clubhouse_result
        cx, cy = result["x"], result["y"]
        w, h = result["width"], result["height"]
        hw, hh = w // 2, h // 2
        patch = placer.heightmap[cy - hh:cy + hh, cx - hw:cx + hw]
        assert patch.std() < 1.0, f"Zone clubhouse pas assez plate (std={patch.std():.2f})"


class TestPracticeRange:
    """Vérifie le placement du practice range."""

    def test_practice_range_within_grid(self, clubhouse_result):
        result, _ = clubhouse_result
        pr = result["practice_range"]
        assert pr["x"] >= 0
        assert pr["y"] >= 0
        assert pr["x"] + pr["width"] <= 350
        assert pr["y"] + pr["height"] <= 350

    def test_practice_range_no_water(self, clubhouse_result):
        result, placer = clubhouse_result
        pr = result["practice_range"]
        patch = placer.heightmap[pr["y"]:pr["y"] + pr["height"],
                                 pr["x"]:pr["x"] + pr["width"]]
        water_level = placer.config.paving.water_level
        water_ratio = float((patch < water_level).sum()) / max(patch.size, 1)
        assert water_ratio <= 0.1, f"Trop d'eau sous le practice ({water_ratio:.0%})"

    def test_practice_range_direction(self, clubhouse_result):
        result, _ = clubhouse_result
        assert result["practice_range"]["direction"] in ("N", "S", "E", "W")


class TestPuttingGreen:
    """Vérifie le placement du putting green."""

    def test_putting_green_within_grid(self, clubhouse_result):
        result, _ = clubhouse_result
        pg = result["putting_green"]
        r = pg["radius"]
        assert pg["x"] - r >= 0
        assert pg["y"] - r >= 0
        assert pg["x"] + r <= 350
        assert pg["y"] + r <= 350

    def test_putting_green_radius(self, clubhouse_result):
        result, _ = clubhouse_result
        assert result["putting_green"]["radius"] == 6


class TestClubhouseDeterminism:
    """Vérifie la reproductibilité."""

    def test_determinism(self):
        config1 = CourseConfig()
        hm1 = TerrainGenerator(config1).generate()
        owner1, seeds1, sizes1 = PavingGenerator(config1, hm1).pave()
        placer1 = ClubhousePlacer(config1, hm1, owner1, seeds1, sizes1)
        r1 = placer1.place()

        config2 = CourseConfig()
        hm2 = TerrainGenerator(config2).generate()
        owner2, seeds2, sizes2 = PavingGenerator(config2, hm2).pave()
        placer2 = ClubhousePlacer(config2, hm2, owner2, seeds2, sizes2)
        r2 = placer2.place()

        assert r1["x"] == r2["x"]
        assert r1["y"] == r2["y"]
        assert r1["adjacent_cells"] == r2["adjacent_cells"]


class TestClubhouseRegression:
    """Valeurs de référence exactes pour seed 42."""

    def test_regression_position(self, clubhouse_result):
        result, _ = clubhouse_result
        assert result["x"] == 247
        assert result["y"] == 117

    def test_regression_adjacent_cells(self, clubhouse_result):
        result, _ = clubhouse_result
        assert result["adjacent_cells"] == [11, 12, 13, 16]
