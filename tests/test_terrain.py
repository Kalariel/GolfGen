"""Tests de régression pour la génération de terrain (seed 42)."""

import numpy as np
import pytest

from pathlib import Path

from golfgen.config import CourseConfig, TerrainConfig
from golfgen import terrain as terrain_module
from golfgen.terrain import (
    TERRAIN_CACHE_DIR,
    TerrainGenerator,
    load_or_generate,
    terrain_cache_path,
    terrain_cache_tag,
)

REPO_ROOT = Path(__file__).resolve().parents[1]


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


class TestDefaultConfig:
    """``default_config.json`` (pipeline) et ``TerrainConfig()`` (runners) donnent le même relief."""

    def test_default_config_terrain_equals_terrain_config(self):
        config = CourseConfig.from_json(REPO_ROOT / "default_config.json")
        assert config.terrain == TerrainConfig()
        assert terrain_cache_tag(config.terrain) == terrain_cache_tag()


class TestTerrainCache:
    """Cache unique ``load_or_generate`` : clé, emplacement, égalité stricte."""

    def test_default_dir_is_absolute_under_repo_output_cache(self):
        assert TERRAIN_CACHE_DIR.is_absolute()
        assert TERRAIN_CACHE_DIR == REPO_ROOT / "output" / ".cache" / "terrain"

    def test_cache_key_tracks_terrain_config(self, tmp_path):
        assert terrain_cache_tag() == terrain_cache_tag(TerrainConfig())
        assert terrain_cache_tag() != terrain_cache_tag(TerrainConfig(octaves=5))
        base = CourseConfig(width=40, height=30, seed=9)
        other = CourseConfig(width=40, height=30, seed=9, terrain=TerrainConfig(octaves=5))
        assert terrain_cache_path(base, tmp_path) != terrain_cache_path(other, tmp_path)
        assert terrain_cache_path(base, tmp_path).name == f"terrain_s9_40x30_{terrain_cache_tag()}.npy"
        assert terrain_cache_path(base).parent == TERRAIN_CACHE_DIR

    @pytest.mark.parametrize("seed, width, height", [(42, 350, 350), (9, 40, 30), (3, 300, 400)])
    def test_identical_to_generator(self, tmp_path, seed, width, height):
        config = CourseConfig(width=width, height=height, seed=seed)
        reference = TerrainGenerator(CourseConfig(width=width, height=height, seed=seed)).generate()
        built = load_or_generate(config, tmp_path)
        cached = load_or_generate(config, tmp_path)
        for heightmap in (built, cached):
            assert heightmap.dtype == reference.dtype == np.float32
            assert np.array_equal(heightmap, reference)
        assert [p.name for p in tmp_path.iterdir()] == [terrain_cache_path(config).name]

    def test_cache_is_read_back(self, tmp_path, monkeypatch):
        config = CourseConfig(width=40, height=30, seed=9)
        first = load_or_generate(config, tmp_path)

        def fail(self):
            raise AssertionError("relief régénéré malgré le cache")

        monkeypatch.setattr(terrain_module.TerrainGenerator, "generate", fail)
        assert np.array_equal(load_or_generate(config, tmp_path), first)

    def test_failed_write_leaves_no_file(self, tmp_path, monkeypatch):
        config = CourseConfig(width=40, height=30, seed=9)

        def broken_save(*args, **kwargs):
            raise OSError("disque plein")

        monkeypatch.setattr(terrain_module.np, "save", broken_save)
        with pytest.raises(OSError):
            load_or_generate(config, tmp_path)
        assert list(tmp_path.iterdir()) == []
