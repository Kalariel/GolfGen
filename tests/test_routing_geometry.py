"""Règles de validation du cœur (``golfgen.routing.geometry``) sans layout du
spike ; les tests qui s'appuient sur ``synthetic`` restent dans
``test_elastic_routing_geometry.py``."""

import math

import pytest

from golfgen.routing.geometry import ValidationRules


def test_validation_rules_reject_non_finite_and_ambiguous_values():
    with pytest.raises(ValueError, match="fini"):
        ValidationRules(fairway_gap=math.nan)
    with pytest.raises(TypeError, match="max_parallel_stack"):
        ValidationRules(max_parallel_stack=True)
