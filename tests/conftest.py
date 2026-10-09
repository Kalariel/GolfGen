"""Fixtures partagées pour les tests."""

import pytest

from golfgen.config import CourseConfig
from golfgen.terrain import TerrainGenerator


@pytest.fixture(scope="session")
def config():
    """Config de référence des tests de relief : seed 42, 350×350."""
    return CourseConfig(seed=42, width=350, height=350)


@pytest.fixture(scope="session")
def heightmap(config):
    """Heightmap 350×350 générée avec seed 42 (~7s)."""
    return TerrainGenerator(config).generate()
