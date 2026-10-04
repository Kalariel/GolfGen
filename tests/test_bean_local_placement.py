import pytest

from experiments.bean_paving.geometry import validate
from experiments.bean_paving.local_placement import place_local_chain


@pytest.mark.parametrize("seed", [1, 7, 42, 123])
def test_multiple_seeds_place_complete_valid_short_chains(seed):
    result = place_local_chain(seed, requested=4)
    assert result.complete, result.to_dict()
    assert not validate(result.placed)
    assert len({bean.id for bean in result.placed}) == 4
    assert result.attempts >= 4


def test_local_placement_is_deterministic():
    assert place_local_chain(42).to_json() == place_local_chain(42).to_json()


def test_rejection_causes_are_counted():
    result = place_local_chain(42)
    assert result.rejection_counts
    assert set(result.rejection_counts) <= {
        "bounds", "footprint_collision", "axis_crossing", "antiparallel", "link_distance"
    }
