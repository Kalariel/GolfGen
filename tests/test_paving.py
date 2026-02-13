"""Tests de régression pour le paving (seed 42)."""

import numpy as np
import pytest

from golfgen.config import CourseConfig
from golfgen.paver import PavingGenerator
from golfgen.terrain import TerrainGenerator


class TestPavingOutput:
    """Vérifie la forme et le type des sorties."""

    def test_owner_shape(self, paving_result):
        owner, _, _ = paving_result
        assert owner.shape == (70, 70)

    def test_owner_dtype(self, paving_result):
        owner, _, _ = paving_result
        assert owner.dtype == np.int16

    def test_seeds_count(self, paving_result):
        _, seeds, _ = paving_result
        assert len(seeds) == 18

    def test_cell_sizes_count(self, paving_result):
        _, _, cell_sizes = paving_result
        assert len(cell_sizes) == 18


class TestPavingCells:
    """Vérifie que les 18 cellules sont présentes et non-vides."""

    def test_all_cells_present(self, paving_result):
        owner, _, _ = paving_result
        unique = set(np.unique(owner))
        for i in range(18):
            assert i in unique, f"Cellule {i} absente"

    def test_no_empty_cell(self, paving_result):
        _, _, cell_sizes = paving_result
        for i, size in enumerate(cell_sizes):
            assert size > 0, f"Cellule {i} vide (taille=0)"

    def test_min_cell_size(self, paving_result):
        """Chaque cellule doit faire au moins 50 tiles (seuil du cleanup)."""
        _, _, cell_sizes = paving_result
        for i, size in enumerate(cell_sizes):
            assert size >= 50, f"Cellule {i} trop petite ({size} tiles)"

    def test_owner_range(self, paving_result):
        owner, _, _ = paving_result
        assert owner.min() >= -1
        assert owner.max() == 17


class TestPavingCoverage:
    """Vérifie la couverture des tiles terre."""

    def test_coverage_above_85_percent(self, config, heightmap, paving_result):
        owner, _, _ = paving_result
        tile_size = config.paving.tile_size
        th = config.height // tile_size
        tw = config.width // tile_size

        # Recalcul du land_mask
        cropped = heightmap[:th * tile_size, :tw * tile_size]
        tile_elev = cropped.reshape(th, tile_size, tw, tile_size).mean(axis=(1, 3))
        land_mask = tile_elev >= config.paving.water_level
        land_count = int(land_mask.sum())

        filled = int((owner >= 0).sum())
        coverage = filled / land_count
        assert coverage >= 0.85, f"Couverture trop faible: {coverage:.1%}"

    def test_water_tiles_unassigned(self, config, heightmap, paving_result):
        """Les tiles sous le water_level ne doivent pas être assignées."""
        owner, _, _ = paving_result
        tile_size = config.paving.tile_size
        th = config.height // tile_size
        tw = config.width // tile_size

        cropped = heightmap[:th * tile_size, :tw * tile_size]
        tile_elev = cropped.reshape(th, tile_size, tw, tile_size).mean(axis=(1, 3))
        water_mask = tile_elev < config.paving.water_level

        # Toutes les tiles d'eau doivent avoir owner == -1
        assert np.all(owner[water_mask] == -1), "Des tiles d'eau sont assignées"


class TestPavingSeedPlacement:
    """Vérifie le placement des seeds."""

    def test_seeds_within_bounds(self, config, paving_result):
        _, seeds, _ = paving_result
        tw = config.width // config.paving.tile_size
        th = config.height // config.paving.tile_size
        for i, (sx, sy) in enumerate(seeds):
            assert 0 <= sx < tw, f"Seed {i} hors limites X: {sx}"
            assert 0 <= sy < th, f"Seed {i} hors limites Y: {sy}"

    def test_seeds_on_land(self, config, heightmap, paving_result):
        """Les seeds doivent être sur la terre ferme."""
        _, seeds, _ = paving_result
        tile_size = config.paving.tile_size
        th = config.height // tile_size
        tw = config.width // tile_size

        cropped = heightmap[:th * tile_size, :tw * tile_size]
        tile_elev = cropped.reshape(th, tile_size, tw, tile_size).mean(axis=(1, 3))
        land_mask = tile_elev >= config.paving.water_level

        for i, (sx, sy) in enumerate(seeds):
            assert land_mask[sy, sx], f"Seed {i} ({sx},{sy}) dans l'eau"

    def test_seeds_unique(self, paving_result):
        _, seeds, _ = paving_result
        assert len(set(seeds)) == len(seeds), "Seeds dupliquées"


class TestPavingDeterminism:
    """Vérifie la reproductibilité avec la même seed."""

    def test_same_seed_same_owner(self, config, heightmap):
        paver1 = PavingGenerator(config, heightmap)
        owner1, seeds1, sizes1 = paver1.pave()

        paver2 = PavingGenerator(config, heightmap)
        owner2, seeds2, sizes2 = paver2.pave()

        np.testing.assert_array_equal(owner1, owner2)
        assert seeds1 == seeds2
        assert sizes1 == sizes2

    def test_different_seed_different_result(self, heightmap):
        config1 = CourseConfig(seed=42)
        config2 = CourseConfig(seed=99)
        # Besoin de heightmaps différentes aussi
        hm1 = TerrainGenerator(config1).generate()
        hm2 = TerrainGenerator(config2).generate()

        owner1, _, _ = PavingGenerator(config1, hm1).pave()
        owner2, _, _ = PavingGenerator(config2, hm2).pave()
        assert not np.array_equal(owner1, owner2)


class TestPavingRegression:
    """Valeurs de référence exactes pour détecter les régressions (seed 42)."""

    def test_seeds_exact(self, paving_result):
        _, seeds, _ = paving_result
        expected = [
            (6, 16), (10, 34), (8, 58), (16, 57), (16, 31), (19, 18),
            (31, 16), (31, 38), (29, 52), (42, 55), (40, 34), (37, 18),
            (52, 15), (49, 38), (50, 54), (60, 53), (57, 35), (63, 10),
        ]
        assert seeds == expected

    def test_cell_sizes_exact(self, paving_result):
        _, _, cell_sizes = paving_result
        expected = [306, 245, 364, 270, 168, 322, 432, 169, 266,
                    268, 139, 182, 299, 196, 362, 196, 330, 279]
        assert cell_sizes == expected

    def test_owner_checksum(self, paving_result):
        owner, _, _ = paving_result
        assert int(owner.sum()) == 39832

    def test_land_count(self, paving_result):
        owner, _, _ = paving_result
        assert int((owner >= 0).sum()) == 4793

    def test_water_count(self, paving_result):
        owner, _, _ = paving_result
        assert int((owner < 0).sum()) == 107


class TestPavingWeighting:
    """Vérifie que le poids par par est respecté (par 5 > par 4 > par 3)."""

    def test_par5_larger_than_par3(self, config, paving_result):
        _, _, cell_sizes = paving_result
        pars = config.routing.par_distribution[:config.num_holes]

        par3_sizes = [s for p, s in zip(pars, cell_sizes) if p == 3]
        par5_sizes = [s for p, s in zip(pars, cell_sizes) if p == 5]

        avg_par3 = sum(par3_sizes) / len(par3_sizes)
        avg_par5 = sum(par5_sizes) / len(par5_sizes)

        assert avg_par5 > avg_par3, (
            f"Par 5 moyen ({avg_par5:.0f}) devrait être > par 3 moyen ({avg_par3:.0f})"
        )
