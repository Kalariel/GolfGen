import json
import math

from experiments.bean_paving.bean_bank import GenerationParams, generate_bank


def _polyline_length(points):
    return sum(math.dist(a, b) for a, b in zip(points, points[1:]))


def test_bank_has_unique_ids_and_expected_classes():
    bank = generate_bank(42)
    ids = [bean.id for bean in bank.templates]
    assert len(ids) == len(set(ids)) == 18
    assert {par: sum(bean.par == par for bean in bank.templates) for par in (3, 4, 5)} == {3: 4, 4: 10, 5: 4}


def test_dimensions_and_contract_match_generation_ranges():
    params = GenerationParams()
    for bean in generate_bank(42, params).templates:
        spec = params.for_par(bean.par)
        assert spec.length_range[0] <= bean.target_length <= spec.length_range[1]
        assert spec.width_range[0] <= bean.width <= spec.width_range[1]
        assert math.isclose(_polyline_length(bean.axis), bean.target_length, rel_tol=1e-9)
        assert bean.tee == bean.axis[0]
        assert bean.green == bean.axis[-1]
        assert len(bean.footprint) == 2 * len(bean.axis)
        assert len(bean.axis) - 2 in spec.turn_choices


def test_same_seed_has_byte_identical_json():
    assert generate_bank(7).to_json() == generate_bank(7).to_json()
    json.loads(generate_bank(7).to_json())


def test_different_seeds_produce_different_banks():
    assert generate_bank(7).to_json() != generate_bank(8).to_json()
