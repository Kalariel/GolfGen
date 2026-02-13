"""Tests de régression pour la génération de terrain (seed 42)."""

import numpy as np
import pytest

from golfgen.config import CourseConfig
from golfgen.terrain import TerrainGenerator


class TestTerrainShape:
    """Vérifie les dimensions et le type de la heightmap."""

    def test_shape(self, heightmap):
        assert heightmap.shape == (350, 350)

    def test_dtype(self, heightmap):
        assert heightmap.dtype == np.float32


class TestTerrainElevation:
    """Vérifie les bornes et statistiques d'élévation."""

    def test_min_elevation(self, heightmap):
        assert heightmap.min() == pytest.approx(58.0, abs=0.01)

    def test_max_elevation(self, heightmap):
        assert heightmap.max() == pytest.approx(82.0, abs=0.01)

    def test_mean_elevation(self, heightmap):
        assert heightmap.mean() == pytest.approx(69.217, abs=0.1)

    def test_std_elevation(self, heightmap):
        assert heightmap.std() == pytest.approx(4.512, abs=0.1)


class TestTerrainDeterminism:
    """Vérifie que la même seed produit la même heightmap."""

    def test_same_seed_same_result(self):
        config = CourseConfig(seed=42)
        hm1 = TerrainGenerator(config).generate()
        hm2 = TerrainGenerator(config).generate()
        np.testing.assert_array_equal(hm1, hm2)

    def test_different_seed_different_result(self):
        hm1 = TerrainGenerator(CourseConfig(seed=42)).generate()
        hm2 = TerrainGenerator(CourseConfig(seed=99)).generate()
        assert not np.array_equal(hm1, hm2)


class TestTerrainRegression:
    """Valeurs de référence exactes pour détecter les régressions (seed 42)."""

    def test_pixel_origin(self, heightmap):
        assert heightmap[0, 0] == pytest.approx(72.181, abs=0.01)

    def test_pixel_center(self, heightmap):
        assert heightmap[175, 175] == pytest.approx(64.761, abs=0.01)

    def test_pixel_corner(self, heightmap):
        assert heightmap[349, 349] == pytest.approx(67.426, abs=0.01)

    def test_pixel_arbitrary(self, heightmap):
        assert heightmap[100, 200] == pytest.approx(71.482, abs=0.01)

    def test_checksum(self, heightmap):
        assert heightmap.sum() == pytest.approx(8479102.0, rel=1e-4)


class TestTerrainNoCentralFlat:
    """Vérifie que le terrain n'a pas d'aplatissement central (fait par l'étape clubhouse)."""

    def test_no_artificial_flat_zone(self, heightmap):
        # Sans aplatissement, le centre doit avoir un std > 1
        # (le terrain est naturellement vallonné)
        center = heightmap[150:200, 150:200]
        assert center.std() > 1.0, "Le terrain semble aplati alors qu'il ne devrait pas l'être"


class TestTerrainWaterMask:
    """Vérifie le masque d'eau."""

    def test_water_mask_dtype(self, heightmap):
        mask = TerrainGenerator.water_mask(heightmap, 61.0)
        assert mask.dtype == np.bool_

    def test_water_mask_shape(self, heightmap):
        mask = TerrainGenerator.water_mask(heightmap, 61.0)
        assert mask.shape == heightmap.shape

    def test_water_below_threshold(self, heightmap):
        mask = TerrainGenerator.water_mask(heightmap, 61.0)
        assert heightmap[mask].max() < 61.0

    def test_land_above_threshold(self, heightmap):
        mask = TerrainGenerator.water_mask(heightmap, 61.0)
        assert heightmap[~mask].min() >= 61.0
