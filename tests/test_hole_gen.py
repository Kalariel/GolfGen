"""Tests de la distribution des pars (patron corrigé automatiquement)."""

import pytest

from golfgen.config import CourseConfig
from golfgen.hole_gen import resolve_par_distribution


class TestResolveParDistribution:

    def test_configured_pattern_kept_when_valid(self, config):
        pars = resolve_par_distribution(config)
        assert pars == config.routing.par_distribution[:config.num_holes]

    def test_total_par_is_enforced(self):
        config = CourseConfig(seed=42, total_par=72)
        # Ancien patron fautif (par 71) : le resolveur doit le corriger.
        config.routing.par_distribution = [
            4, 3, 5, 4, 3, 4, 5, 3, 4,
            4, 5, 3, 4, 4, 5, 3, 4, 4,
        ]
        pars = resolve_par_distribution(config)
        assert len(pars) == 18
        assert sum(pars) == 72
        assert sum(pars[:9]) == sum(pars[9:]) == 36

    def test_impossible_total_par_fails_fast(self):
        config = CourseConfig(num_holes=18, total_par=100)
        with pytest.raises(ValueError, match="impossible"):
            resolve_par_distribution(config)

    def test_deterministic(self):
        assert resolve_par_distribution(CourseConfig(seed=1)) \
            == resolve_par_distribution(CourseConfig(seed=1))
