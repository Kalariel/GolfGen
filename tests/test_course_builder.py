"""Tests bout-en-bout pour l'assemblage final du parcours (étape 4)."""

import pytest

from golfgen.config import CourseConfig
from golfgen.course_builder import build_course

REQUIRED_HOLE_KEYS = {"id", "par", "blocks", "tee", "green", "waypoints", "fairway_width", "direction"}
COMPASS_LABELS = {"E", "NE", "N", "NO", "O", "SO", "S", "SE"}


@pytest.fixture(scope="module")
def small_config():
    config = CourseConfig(seed=42, num_holes=6)
    config.routing.par_distribution = [4, 3, 5, 4, 3, 4]
    return config


@pytest.fixture(scope="module")
def built(small_config):
    return build_course(small_config, heightmap=None)


class TestCourseBuilderShape:
    def test_hole_count(self, built):
        holes, _ = built
        assert len(holes) == 6

    def test_ids_are_sequential(self, built):
        holes, _ = built
        assert [h["id"] for h in holes] == list(range(1, 7))

    def test_required_keys_present(self, built):
        holes, _ = built
        for h in holes:
            assert REQUIRED_HOLE_KEYS.issubset(h.keys())
            assert {"x", "y", "elevation"}.issubset(h["tee"].keys())
            assert {"x", "y", "radius", "elevation"}.issubset(h["green"].keys())
            assert all({"x", "y"}.issubset(wp.keys()) for wp in h["waypoints"])

    def test_direction_is_valid_compass_label(self, built):
        holes, _ = built
        for h in holes:
            assert h["direction"] in COMPASS_LABELS

    def test_elevation_defaults_without_heightmap(self, built):
        holes, _ = built
        for h in holes:
            assert h["tee"]["elevation"] == 64.0
            assert h["green"]["elevation"] == 64.0

    def test_par_matches_configured_distribution(self, built, small_config):
        holes, _ = built
        assert sorted(h["par"] for h in holes) == sorted(small_config.routing.par_distribution)


class TestCourseBuilderDeterminism:
    def test_same_seed_same_result(self, small_config):
        holes_a, clubhouse_a = build_course(small_config, heightmap=None)
        holes_b, clubhouse_b = build_course(small_config, heightmap=None)
        assert holes_a == holes_b
        assert clubhouse_a == clubhouse_b
