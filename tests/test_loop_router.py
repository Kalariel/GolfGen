"""Tests d'invariants du routing par ruban (loop_router).

Les garanties structurelles sont vérifiées sur les trous exportés, pas sur les
détails internes du ruban : ce sont elles que le viewer et les étapes futures
(hazards, végétation) consomment.
"""

import math

import pytest

from golfgen.config import CourseConfig
from golfgen.loop_router import MAX_CORNER_DEG, STUB_MAX, build_course_loop

SEEDS = [1, 7, 42, 123]


def _points(hole):
    return [(w["x"], w["y"]) for w in hole["waypoints"]]


def _segments(holes):
    for hole in holes:
        pts = _points(hole)
        for a, b in zip(pts, pts[1:]):
            yield hole["id"], a, b, hole["fairway_width"]


def _segments_intersect(p1, p2, p3, p4):
    def ccw(a, b, c):
        return (c[1] - a[1]) * (b[0] - a[0]) - (b[1] - a[1]) * (c[0] - a[0])
    d1, d2 = ccw(p3, p4, p1), ccw(p3, p4, p2)
    d3, d4 = ccw(p1, p2, p3), ccw(p1, p2, p4)
    return ((d1 > 0) != (d2 > 0)) and ((d3 > 0) != (d4 > 0))


def _point_seg_dist(p, a, b):
    dx, dy = b[0] - a[0], b[1] - a[1]
    n2 = dx * dx + dy * dy
    t = 0.0 if n2 == 0 else max(0.0, min(1.0, ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / n2))
    return math.hypot(p[0] - (a[0] + t * dx), p[1] - (a[1] + t * dy))


@pytest.fixture(scope="module", params=SEEDS)
def course(request):
    config = CourseConfig(seed=request.param, width=350, height=350)
    holes, clubhouse_pos = build_course_loop(config, heightmap=None)
    return config, holes, clubhouse_pos


class TestStructure:

    def test_count_ids_and_par(self, course):
        config, holes, _ = course
        assert len(holes) == config.num_holes
        assert [h["id"] for h in holes] == list(range(1, config.num_holes + 1))
        assert sum(h["par"] for h in holes) == config.total_par
        mid = config.num_holes // 2
        assert sum(h["par"] for h in holes[:mid]) \
            == sum(h["par"] for h in holes[mid:]) == config.total_par // 2

    def test_hole_lengths_match_par_ranges(self, course):
        config, holes, _ = course
        rc = config.routing
        ranges = {3: rc.par3_range, 4: rc.par4_range, 5: rc.par5_range}
        for hole in holes:
            lo, hi = ranges[hole["par"]]
            # blocks est tronqué à l'entier, la coupe est discrétisée
            assert lo - 4 <= hole["blocks"] <= hi + 4

    def test_within_map(self, course):
        config, holes, _ = course
        for hole in holes:
            for x, y in _points(hole):
                assert 0 <= x <= config.width
                assert 0 <= y <= config.height


class TestLiaisons:

    def test_playable_links_within_bounds(self, course):
        config, holes, _ = course
        rc = config.routing
        mid = config.num_holes // 2
        for prev, nxt in zip(holes, holes[1:]):
            if prev["id"] == mid:  # 9->10 repasse par le clubhouse
                continue
            link = math.dist(
                (prev["green"]["x"], prev["green"]["y"]),
                (nxt["tee"]["x"], nxt["tee"]["y"]),
            )
            assert rc.tee_link_min - 1e-6 <= link <= rc.tee_link_max + 1e-6

    def test_nines_start_and_end_near_clubhouse(self, course):
        config, holes, clubhouse_pos = course
        mid = config.num_holes // 2
        walk_max = STUB_MAX + 60.0  # stub le long du ruban + traversée esplanade
        for hole, endpoint in ((holes[0], "tee"), (holes[mid - 1], "green"),
                               (holes[mid], "tee"), (holes[-1], "green")):
            point = (hole[endpoint]["x"], hole[endpoint]["y"])
            assert math.dist(point, clubhouse_pos) <= walk_max


class TestGeometrie:

    def test_no_crossings_between_holes(self, course):
        _, holes, _ = course
        segs = list(_segments(holes))
        for i, (ha, a1, a2, _) in enumerate(segs):
            for hb, b1, b2, _ in segs[i + 1:]:
                if ha == hb:
                    continue
                assert not _segments_intersect(a1, a2, b1, b2), f"trous {ha}x{hb}"

    def test_no_fairway_overlap(self, course):
        _, holes, _ = course
        segs = list(_segments(holes))
        for i, (ha, a1, a2, wa) in enumerate(segs):
            for hb, b1, b2, wb in segs[i + 1:]:
                if ha == hb:
                    continue
                d = min(
                    _point_seg_dist(a1, b1, b2), _point_seg_dist(a2, b1, b2),
                    _point_seg_dist(b1, a1, a2), _point_seg_dist(b2, a1, a2),
                )
                assert d >= (wa + wb) / 2, f"trous {ha}x{hb}: {d:.1f}"


class TestAngles:
    """Règles métier : pas de virage dur ni de repli dans un trou."""

    def test_corner_and_net_curvature_bounds(self, course):
        _, holes, _ = course
        for hole in holes:
            pts = _points(hole)
            net = 0.0
            for i in range(1, len(pts) - 1):
                v1 = (pts[i][0] - pts[i - 1][0], pts[i][1] - pts[i - 1][1])
                v2 = (pts[i + 1][0] - pts[i][0], pts[i + 1][1] - pts[i][1])
                angle = math.degrees(math.atan2(
                    v1[0] * v2[1] - v1[1] * v2[0], v1[0] * v2[0] + v1[1] * v2[1]
                ))
                assert abs(angle) <= MAX_CORNER_DEG + 1.0, \
                    f"trou {hole['id']}: virage {angle:.0f}"
                net += angle
            assert abs(net) <= 100.0, f"trou {hole['id']}: net {net:.0f}"


class TestDeterminisme:

    def test_same_seed_same_course(self):
        config = CourseConfig(seed=42, width=350, height=350)
        holes_a, _ = build_course_loop(config, heightmap=None)
        holes_b, _ = build_course_loop(config, heightmap=None)
        assert [h["waypoints"] for h in holes_a] == [h["waypoints"] for h in holes_b]
