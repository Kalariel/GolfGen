"""Tests pour la génération de squelettes de trous (étape 1 du pipeline)."""

import pytest

from golfgen.config import CourseConfig
from golfgen.hole_gen import HoleGenerator


class TestHoleGenDeterminism:
    """Même seed -> mêmes formes."""

    def test_same_seed_same_shapes(self):
        config = CourseConfig(seed=42)
        shapes_a = HoleGenerator(config).generate_all()
        shapes_b = HoleGenerator(config).generate_all()
        assert [s.waypoints for s in shapes_a] == [s.waypoints for s in shapes_b]

    def test_different_seed_different_shapes(self):
        shapes_a = HoleGenerator(CourseConfig(seed=42)).generate_all()
        shapes_b = HoleGenerator(CourseConfig(seed=43)).generate_all()
        assert [s.waypoints for s in shapes_a] != [s.waypoints for s in shapes_b]


class TestHoleGenShape:
    """Vérifie la cohérence géométrique de chaque squelette généré."""

    def test_count_matches_par_distribution(self, config):
        shapes = HoleGenerator(config).generate_all()
        assert len(shapes) == config.num_holes
        assert [s.par for s in shapes] == config.routing.par_distribution[:config.num_holes]

    def test_tee_at_origin(self, config):
        for shape in HoleGenerator(config).generate_all():
            assert shape.waypoints[0] == (0.0, 0.0)

    def test_length_within_configured_range(self, config):
        rc = config.routing
        ranges = {3: rc.par3_range, 4: rc.par4_range, 5: rc.par5_range}
        # La reconstruction/mise à l'échelle des waypoints peut légèrement
        # dépasser la cible (segments jitterés) — on tolère une petite marge.
        tolerance = 5
        for shape in HoleGenerator(config).generate_all():
            lo, hi = ranges[shape.par]
            assert lo - tolerance <= shape.length <= hi + tolerance

    def test_fairway_width_matches_par(self, config):
        rc = config.routing
        fw_map = {3: rc.fairway_width_par3, 4: rc.fairway_width_par4, 5: rc.fairway_width_par5}
        for shape in HoleGenerator(config).generate_all():
            assert shape.fairway_width == fw_map[shape.par]

    def test_green_radius_within_bounds(self, config):
        rc = config.routing
        for shape in HoleGenerator(config).generate_all():
            assert rc.green_radius_min <= shape.green_radius <= rc.green_radius_max

    def test_generate_one_standalone(self, config):
        shape = HoleGenerator(config).generate_one(par=4)
        assert shape.par == 4
        assert shape.waypoints[0] == (0.0, 0.0)
