"""Fixtures partagées pour les tests, et marqueur ``slow``.

Tests lents (``@pytest.mark.slow`` : corpus complet des tests des
chemins) : SAUTÉS par défaut, ``pytest tests/`` ne lance que le
sous-ensemble rapide. Pour les lancer :

    .venv/bin/python -m pytest tests/ --run-slow            # tout
    .venv/bin/python -m pytest tests/ --run-slow -m slow    # les lents seuls
"""

import pytest

from golfgen.config import CourseConfig
from golfgen.terrain import TerrainGenerator
from tests.paths_corpus import CACHE_KEY, FAST, FROZEN, FROZEN_FAST, SLOW, ensure_corpus


def pytest_addoption(parser):
    parser.addoption("--run-slow", action="store_true", default=False,
                     help="lance aussi les tests marqués slow (sautés par défaut)")


def pytest_configure(config):
    config.addinivalue_line("markers", "slow: test lent, sauté sans --run-slow")


def pytest_collection_modifyitems(config, items):
    if config.getoption("--run-slow"):
        return
    skip = pytest.mark.skip(reason="lent : --run-slow pour le lancer")
    for item in items:
        if item.get_closest_marker("slow") is not None:
            item.add_marker(skip)


@pytest.fixture(scope="session")
def config():
    """Config de référence des tests de relief : seed 42, 350×350."""
    return CourseConfig(seed=42, width=350, height=350)


@pytest.fixture(scope="session")
def heightmap(config):
    """Heightmap 350×350 générée avec seed 42 (~7s)."""
    return TerrainGenerator(config).generate()


@pytest.fixture(scope="session")
def corpus_dir(request):
    """Cache du corpus réel des chemins (``tests/paths_corpus.py``) : les
    JSON rapides, et les lents avec ``--run-slow``."""
    path = request.config.cache.mkdir(CACHE_KEY)
    run_slow = request.config.getoption("--run-slow")
    ensure_corpus(path, tuple(dict.fromkeys(FAST + FROZEN_FAST + (SLOW + FROZEN if run_slow else ()))))
    return path
