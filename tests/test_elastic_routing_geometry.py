from collections import Counter
from dataclasses import replace
import math

import pytest

from experiments.elastic_routing.geometry import (
    ValidationRules,
    build_hole_geometry,
    validate,
)
from experiments.elastic_routing.model import (
    PAR_SPECS,
    ControlPoint,
    CourseLayout,
    NineLayout,
)
from experiments.elastic_routing.synthetic import build_synthetic_layout


PERMISSIVE = ValidationRules(
    link_max=500.0,
    max_parallel_stack=None,
    clubhouse_clear_radius=0.0,
    walkable_links=False,
)


def _with_holes(layout, holes):
    holes = tuple(sorted(holes, key=lambda hole: hole.order))
    return CourseLayout(
        seed=layout.seed,
        width=layout.width,
        height=layout.height,
        clubhouse=layout.clubhouse,
        front=NineLayout.from_holes(1, layout.clubhouse, holes[:9]),
        back=NineLayout.from_holes(10, layout.clubhouse, holes[9:]),
    )


def _replace_hole(layout, order, **changes):
    holes = [replace(hole, **changes) if hole.order == order else hole
             for hole in layout.holes]
    return _with_holes(layout, holes)


def _kinds(layout, rules=PERMISSIVE):
    return {violation.kind for violation in validate(layout, rules)}


def test_synthetic_layout_is_valid_under_explicitly_permissive_rules():
    assert validate(build_synthetic_layout(), PERMISSIVE) == []


def test_validation_rules_reject_non_finite_and_ambiguous_values():
    with pytest.raises(ValueError, match="fini"):
        ValidationRules(fairway_gap=math.nan)
    with pytest.raises(TypeError, match="max_parallel_stack"):
        ValidationRules(max_parallel_stack=True)


def test_geometry_builds_core_and_larger_rough_from_elastic_axis():
    hole = build_synthetic_layout().holes[0]
    geometry = build_hole_geometry(hole)

    assert geometry.axis[0] == (hole.tee.x, hole.tee.y)
    assert geometry.axis[-1] == (hole.green.x, hole.green.y)
    assert len(geometry.core) == len(geometry.rough) == 2 * len(hole.axis)
    assert min(point[1] for point in geometry.rough) < min(point[1] for point in geometry.core)
    assert max(point[1] for point in geometry.rough) > max(point[1] for point in geometry.core)


def test_validator_reports_length_and_width_ranges():
    layout = build_synthetic_layout()
    first = layout.holes[0]
    broken = _replace_hole(
        layout,
        1,
        green=ControlPoint(first.tee.x + 10.0, first.tee.y),
        width=PAR_SPECS[3].width_min - 1.0,
    )

    assert {"length", "width"} <= _kinds(broken)


def test_validator_reports_core_outside_map():
    layout = build_synthetic_layout()
    broken = _replace_hole(
        layout,
        1,
        tee=ControlPoint(0.0, 20.0),
        green=ControlPoint(75.0, 20.0),
    )

    assert "bounds" in _kinds(broken)


def test_validator_reports_axis_crossing_and_fairway_gap():
    layout = build_synthetic_layout()
    broken = _replace_hole(
        layout,
        10,
        tee=ControlPoint(140.0, 140.0),
        green=ControlPoint(140.0, 215.0),
    )
    violations = validate(broken, PERMISSIVE)

    assert any(item.kind == "axis_crossing" and item.holes == (1, 10)
               for item in violations)
    assert any(item.kind == "fairway_gap" and item.holes == (1, 10)
               for item in violations)


def test_validator_reports_clubhouse_clearance():
    layout = build_synthetic_layout()
    broken = _replace_hole(
        layout,
        1,
        tee=ControlPoint(162.5, 200.0),
        green=ControlPoint(237.5, 200.0),
    )
    rules = replace(PERMISSIVE, clubhouse_clear_radius=10.0)

    assert "clubhouse_clear" in _kinds(broken, rules)


def test_final_rules_report_link_distance_blocking_and_parallel_stacks():
    violations = validate(build_synthetic_layout(), ValidationRules())
    counts = Counter(item.kind for item in violations)

    assert counts["link_distance"] > 0
    assert counts["link_blocked"] > 0
    assert counts["parallel_stack"] > 0


def test_validator_reports_per_nine_par_bounds_while_global_quota_stays_exact():
    layout = build_synthetic_layout()

    def reclassify(pars):
        holes = []
        for hole, par in zip(layout.holes, pars):
            direction = 1.0 if hole.green.x > hole.tee.x else -1.0
            holes.append(replace(
                hole,
                par=par,
                green=ControlPoint(hole.tee.x + direction * PAR_SPECS[par].length_min,
                                   hole.tee.y),
                width=PAR_SPECS[par].width_min,
            ))
        return _with_holes(layout, holes)

    par5_unbalanced = reclassify(
        (3, 3, 4, 4, 4, 4, 4, 4, 4, 3, 3, 4, 4, 4, 5, 5, 5, 5)
    )
    par3_unbalanced = reclassify(
        (4, 4, 4, 4, 4, 4, 4, 5, 5, 3, 3, 3, 3, 4, 4, 4, 5, 5)
    )

    assert sum(item.kind == "par5_per_nine"
               for item in validate(par5_unbalanced, PERMISSIVE)) == 2
    assert sum(item.kind == "par3_per_nine"
               for item in validate(par3_unbalanced, PERMISSIVE)) == 2


def test_validator_reports_rule_and_layout_map_size_mismatch():
    rules = replace(PERMISSIVE, width=399.0)
    assert "map_size" in _kinds(build_synthetic_layout(), rules)
