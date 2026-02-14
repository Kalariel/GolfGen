"""Fixtures partagées pour les tests."""

import pytest

from golfgen.config import CourseConfig
from golfgen.terrain import TerrainGenerator


@pytest.fixture(scope="session")
def config():
    """Config par défaut (seed 42)."""
    return CourseConfig(seed=42)


@pytest.fixture(scope="session")
def heightmap(config):
    """Heightmap 350×350 générée avec seed 42 (~7s)."""
    return TerrainGenerator(config).generate()
