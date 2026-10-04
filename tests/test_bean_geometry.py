import math

import pytest

from experiments.bean_paving.bean_bank import BeanTemplate, _footprint
from experiments.bean_paving.geometry import PlacedBean, Transform, ValidationRules, validate


def bean(name, axis=((0.0, 0.0), (60.0, 0.0)), width=10.0, margin=5.0):
    axis = tuple(axis)
    return BeanTemplate(name, 4, 60.0, axis, width, margin,
                        _footprint(axis, width / 2 + margin), axis[0], axis[-1], 0.0, 0.0)


def kinds(placed, rules=ValidationRules(), check_links=False):
    return {item.kind for item in validate(placed, rules, check_links=check_links)}


def test_rotation_translation_and_mirror():
    shape = bean("turn", ((0.0, 0.0), (20.0, 0.0), (30.0, 10.0)))
    placed = PlacedBean(shape, Transform(100.0, 50.0, 90.0, True), 1)
    assert placed.tee == pytest.approx((100.0, 50.0))
    assert placed.axis[1] == pytest.approx((100.0, 70.0))
    assert placed.green == pytest.approx((110.0, 80.0))


def test_valid_separated_pair():
    placed = [PlacedBean(bean("a"), Transform(20, 30), 1),
              PlacedBean(bean("b"), Transform(100, 60, 20), 2)]
    assert not kinds(placed)


def test_bounds_violation():
    assert "bounds" in kinds([PlacedBean(bean("a"), Transform(4, 20), 1)])


def test_footprints_that_touch_are_a_collision():
    placed = [PlacedBean(bean("a"), Transform(20, 50), 1),
              PlacedBean(bean("b"), Transform(20, 70), 2)]
    assert "footprint_collision" in kinds(placed)


def test_near_footprints_do_not_collide():
    placed = [PlacedBean(bean("a"), Transform(20, 50), 1),
              PlacedBean(bean("b"), Transform(20, 70.01), 2)]
    assert "footprint_collision" not in kinds(placed)


def test_axis_crossing_is_reported_exactly():
    placed = [PlacedBean(bean("a", ((0, 0), (80, 0))), Transform(30, 60), 1),
              PlacedBean(bean("b", ((0, 0), (80, 0))), Transform(70, 20, 90), 2)]
    assert "axis_crossing" in kinds(placed)


def test_long_close_antiparallel_run_is_rejected_without_collision():
    thin = lambda name: bean(name, ((0, 0), (100, 0)), width=4, margin=0)
    placed = [PlacedBean(thin("a"), Transform(20, 50), 1),
              PlacedBean(thin("b"), Transform(120, 72, 180), 2)]
    found = kinds(placed)
    assert "footprint_collision" not in found
    assert "antiparallel" in found


@pytest.mark.parametrize("offset", [31.0, 45.0])
def test_antiparallel_rule_allows_distant_or_short_overlap(offset):
    thin = lambda name: bean(name, ((0, 0), (100, 0)), width=4, margin=0)
    second_x = 75 if offset == 45 else 120
    placed = [PlacedBean(thin("a"), Transform(20, 50), 1),
              PlacedBean(thin("b"), Transform(second_x, 50 + offset, 180), 2)]
    assert "antiparallel" not in kinds(placed)


@pytest.mark.parametrize("distance, expected", [(12.0, False), (45.0, False), (11.9, True), (45.1, True)])
def test_link_distance_bounds(distance, expected):
    first = bean("a", ((0, 0), (60, 0)), width=2, margin=0)
    second = bean("b", ((0, 0), (40, 0)), width=2, margin=0)
    placed = [PlacedBean(first, Transform(20, 40), 1),
              PlacedBean(second, Transform(80 + distance, 40), 2)]
    assert ("link_distance" in kinds(placed, check_links=True)) is expected
