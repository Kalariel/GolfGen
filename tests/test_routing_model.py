import json
import math

import pytest

from golfgen.routing.model import (
    PAR_SPECS,
    ControlPoint,
    CourseLayout,
    ElasticHole,
    HoleClassSpec,
    NineLayout,
    WalkingLink,
)


PARS = (3, 4, 4, 4, 4, 4, 5, 5, 3) * 2


def hole(order, par, *, doglegs=(), width=None):
    spec = PAR_SPECS[par]
    tee = ControlPoint(20.0 + order * 3.0, 30.0 + order * 2.0)
    green = ControlPoint(tee.x + spec.length_min, tee.y)
    return ElasticHole(
        order=order,
        par=par,
        tee=tee,
        green=green,
        doglegs=doglegs,
        width=spec.width_min if width is None else width,
    )


def course(seed=7):
    clubhouse = ControlPoint(200.0, 200.0)
    holes = tuple(hole(order, par) for order, par in enumerate(PARS, start=1))
    return CourseLayout(
        seed=seed,
        width=400.0,
        height=400.0,
        clubhouse=clubhouse,
        front=NineLayout.from_holes(1, clubhouse, holes[:9]),
        back=NineLayout.from_holes(10, clubhouse, holes[9:]),
    )


@pytest.mark.parametrize("value", [math.nan, math.inf, -math.inf])
def test_control_point_rejects_non_finite_coordinates(value):
    with pytest.raises(ValueError, match="fini"):
        ControlPoint(value, 0.0)


def test_elastic_hole_exposes_axis_length_and_final_dimension_status():
    item = ElasticHole(
        order=1,
        par=3,
        tee=ControlPoint(0.0, 0.0),
        doglegs=(ControlPoint(18.0, 24.0),),
        green=ControlPoint(48.0, 24.0),
        width=10.0,
    )

    assert item.axis == (item.tee, *item.doglegs, item.green)
    assert item.length == 60.0
    assert item.dimensions_are_final is True

    # Une dimension provisoire hors plage reste représentable pour permettre
    # l'inflation et les réparations des étapes suivantes.
    provisional = hole(1, 3, width=9.0)
    assert provisional.dimensions_are_final is False


def test_elastic_hole_rejects_more_than_two_doglegs_and_zero_segments():
    with pytest.raises(ValueError, match="plus de deux"):
        hole(1, 4, doglegs=(ControlPoint(1, 1), ControlPoint(2, 2), ControlPoint(3, 3)))

    with pytest.raises(ValueError, match="segment nul"):
        ElasticHole(1, 3, ControlPoint(0, 0), ControlPoint(75, 0),
                    doglegs=(ControlPoint(0, 0),), width=10)

    with pytest.raises(TypeError, match="order"):
        ElasticHole(None, 3, ControlPoint(0, 0), ControlPoint(75, 0), width=10)

    with pytest.raises(ValueError, match="par"):
        ElasticHole(1, 3.0, ControlPoint(0, 0), ControlPoint(75, 0), width=10)


def test_walking_link_rejects_invalid_ownership():
    start = ControlPoint(0, 0)
    end = ControlPoint(1, 0)

    with pytest.raises(ValueError, match="au moins un trou"):
        WalkingLink(start, end, None, None)
    with pytest.raises(ValueError, match="lui-même"):
        WalkingLink(start, end, 1, 1)


def test_nine_builder_creates_explicit_ordered_walking_links():
    clubhouse = ControlPoint(200.0, 200.0)
    holes = tuple(hole(order, par) for order, par in enumerate(PARS[:9], start=1))
    nine = NineLayout.from_holes(1, clubhouse, holes)

    assert len(nine.links) == 10
    assert (nine.links[0].from_hole_order, nine.links[0].to_hole_order) == (None, 1)
    assert nine.links[0].start == clubhouse
    assert nine.links[0].end == holes[0].tee
    assert (nine.links[5].from_hole_order, nine.links[5].to_hole_order) == (5, 6)
    assert nine.links[5].start == holes[4].green
    assert nine.links[5].end == holes[5].tee
    assert (nine.links[-1].from_hole_order, nine.links[-1].to_hole_order) == (9, None)
    assert nine.links[-1].end == clubhouse


def test_nine_rejects_a_link_that_does_not_match_its_holes():
    valid = course().front
    broken = list(valid.links)
    broken[1] = WalkingLink(valid.holes[0].green, valid.holes[2].tee, 1, 2)

    with pytest.raises(ValueError, match="liaisons internes"):
        NineLayout(1, valid.holes, tuple(broken))

    with pytest.raises(TypeError, match="start_order"):
        NineLayout(True, valid.holes, valid.links)


def test_course_requires_exact_orders_clubhouse_returns_and_global_quota():
    valid = course()
    assert len(valid.holes) == 18
    assert [item.order for item in valid.holes] == list(range(1, 19))

    wrong_pars = list(PARS)
    wrong_pars[0] = 4
    wrong_holes = tuple(hole(order, par) for order, par in enumerate(wrong_pars, start=1))
    with pytest.raises(ValueError, match="quota global"):
        CourseLayout(
            seed=7,
            width=400,
            height=400,
            clubhouse=valid.clubhouse,
            front=NineLayout.from_holes(1, valid.clubhouse, wrong_holes[:9]),
            back=NineLayout.from_holes(10, valid.clubhouse, wrong_holes[9:]),
        )

    shifted_clubhouse = ControlPoint(201.0, 200.0)
    with pytest.raises(ValueError, match="partir du clubhouse"):
        CourseLayout(7, 400, 400, shifted_clubhouse, valid.front, valid.back)


def test_course_json_is_deterministic_and_round_trips():
    layout = course()

    assert layout.to_json() == layout.to_json()
    assert CourseLayout.from_json(layout.to_json()) == layout
    assert json.loads(layout.to_json())["schema_version"] == 1


def test_course_rejects_unknown_json_schema():
    data = course().to_dict()
    data["schema_version"] = 2

    with pytest.raises(ValueError, match="schema_version"):
        CourseLayout.from_dict(data)


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

    with pytest.raises(TypeError, match="doglegs"):
        HoleClassSpec(3, 75, 110, 10, 15, coarse_max_doglegs=1.5)
