"""Fixtures partagées pour les tests du golf course generator."""

import pytest
import numpy as np

from golfgen.config import CourseConfig
from golfgen.terrain import TerrainGenerator
from golfgen.paver import PavingGenerator
from golfgen.clubhouse import ClubhousePlacer


@pytest.fixture(scope="session")
def config():
    """Config par défaut (seed=42)."""
    return CourseConfig()


@pytest.fixture(scope="session")
def heightmap(config):
    """Heightmap générée avec seed 42 (cache session)."""
    gen = TerrainGenerator(config)
    return gen.generate()


@pytest.fixture(scope="session")
def paving_result(config, heightmap):
    """Résultat du paving avec seed 42 (owner, seeds, cell_sizes)."""
    paver = PavingGenerator(config, heightmap)
    return paver.pave()


@pytest.fixture(scope="session")
def clubhouse_result(config, heightmap, paving_result):
    """Résultat du placement clubhouse avec seed 42."""
    owner, seeds, cell_sizes = paving_result
    # Copier la heightmap car le placer la modifie in-place
    hm_copy = heightmap.copy()
    placer = ClubhousePlacer(config, hm_copy, owner, seeds, cell_sizes)
    result = placer.place()
    return result, placer
