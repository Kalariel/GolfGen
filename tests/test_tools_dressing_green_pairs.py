"""Mesure des greens doubles (``tools.dressing.green_pairs``) sur le layout
synthétique de l'oracle (deux bandes de trous rectilignes)."""

from __future__ import annotations

import math

from tools.dressing import green_pairs as gp
from tests.test_routing_geometry import build_synthetic_layout


def test_convex_hull_drops_interior_and_collinear_points():
    hull = gp.convex_hull([(0, 0), (2, 0), (1, 0), (2, 2), (0, 2), (1, 1)])
    assert sorted(hull) == [(0.0, 0.0), (0.0, 2.0), (2.0, 0.0), (2.0, 2.0)]


def test_disk_polygon_contains_the_disk():
    polygon = gp.disk((10.0, 10.0), 5.0, 16)
    assert len(polygon) == 16
    assert all(math.dist(p, (10.0, 10.0)) >= 5.0 for p in polygon)
    # apothème du polygone circonscrit = rayon
    mid = ((polygon[0][0] + polygon[1][0]) / 2, (polygon[0][1] + polygon[1][1]) / 2)
    assert math.isclose(math.dist(mid, (10.0, 10.0)), 5.0)


def test_eligible_pairs_exclude_consecutive_and_9_18():
    pairs = {(i, j) for i, j, _ in gp.eligible_pairs(build_synthetic_layout())}
    assert len(pairs) == 18 * 17 // 2 - 17 - 1
    assert (9, 18) not in pairs and (9, 10) not in pairs and (4, 5) not in pairs
    assert (1, 18) in pairs and (1, 3) in pairs


def test_core_check_rejects_a_hull_over_another_fairway():
    layout = build_synthetic_layout()
    # greens 1 (y=180) et 3 (y=140) encadrent le trou 2 (y=160)
    checks = gp.pair_checks(layout, 1, 3)
    assert checks["coeur"][0] is False
    assert set(checks) == set(gp.CONTROLS)


def test_select_pairs_is_greedy_sorted_and_keeps_a_gap_between_pairs():
    hulls = {(1, 3): gp.convex_hull(gp.disk((0, 0)) + gp.disk((20, 0))),
             (2, 5): gp.convex_hull(gp.disk((0, 3)) + gp.disk((20, 3))),     # chevauche
             (4, 7): gp.convex_hull(gp.disk((0, 100)) + gp.disk((25, 100))),
             (6, 8): gp.convex_hull(gp.disk((0, 200)) + gp.disk((26, 200)))}
    valid = [{"i": 6, "j": 8, "d": 26.0}, {"i": 2, "j": 5, "d": 20.0},
             {"i": 4, "j": 7, "d": 25.0}, {"i": 1, "j": 3, "d": 20.0}]
    chosen, blocked = gp.select_pairs(valid, hulls)
    assert [(p["i"], p["j"]) for p in chosen] == [(1, 3), (4, 7)]
    assert blocked == 1


def test_loop_relation_follows_the_outer_nine():
    assert gp.loop_relation(2, 7, outer_first=1) == "exterieure"
    assert gp.loop_relation(2, 7, outer_first=10) == "interieure"
    assert gp.loop_relation(3, 12, outer_first=1) == "croisee"


def test_histogram_bins_by_five_up_to_sixty():
    bins = gp.histogram([0.0, 4.9, 12.0, 59.9, 60.0, 300.0])
    assert list(bins)[:2] == ["00-05", "05-10"] and bins["00-05"] == 2
    assert bins["10-15"] == 1 and bins["55-60"] == 1 and bins["60+"] == 2


def test_evaluate_layout_reports_every_range():
    result = gp.evaluate_layout(build_synthetic_layout(), outer_first=1)
    assert set(result["ranges"]) == set(gp.RANGES)
    assert len(result["nn_any"]) == 18
    for data in result["ranges"].values():
        assert data["valid"] <= data["candidates"]
        assert len(data["selected"]) <= gp.MAX_PAIRS


def test_render_overlays_are_optional_and_drawn():
    from tools.muirfield.render_readable import render_readable_svg
    layout = build_synthetic_layout()
    plain = render_readable_svg(layout, (), title="t")
    hull = gp.pair_hull(layout, 1, 3)
    svg = render_readable_svg(layout, (), title="t", overlays=[(hull, "#ff7b00")])
    assert 'fill="#ff7b00" fill-opacity="0.35"' in svg and "#ff7b00" not in plain
    assert len(svg.splitlines()) == len(plain.splitlines()) + 1
