"""Plages de longueur par par : validées (cœur ``golfgen.routing.model``) et
historiques (``LEGACY_PAR_SPECS``, figées dans le spike ``skeleton``)."""

import pytest

from experiments.elastic_routing.skeleton import LEGACY_PAR_SPECS
from golfgen.routing.model import PAR_SPECS, HoleClassSpec


def test_validated_specs_match_decisions():
    assert {
        par: (spec.length_min, spec.length_max, spec.width_min, spec.width_max,
              spec.coarse_max_doglegs, spec.final_max_doglegs)
        for par, spec in PAR_SPECS.items()
    } == {
        3: (45.0, 70.0, 10.0, 15.0, 1, 2),
        4: (100.0, 145.0, 11.0, 17.0, 1, 2),
        5: (145.0, 185.0, 12.0, 18.0, 1, 2),
    }
    assert {par: (spec.length_min, spec.length_max) for par, spec in LEGACY_PAR_SPECS.items()} == {
        3: (75.0, 110.0), 4: (120.0, 175.0), 5: (175.0, 235.0),
    }

    with pytest.raises(TypeError, match="doglegs"):
        HoleClassSpec(3, 75, 110, 10, 15, coarse_max_doglegs=1.5)
