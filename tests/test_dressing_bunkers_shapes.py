"""Formes des bunkers (``golfgen.dressing.bunkers``, round R1) : raster et
haricots. Tests repris de l'étude des bunkers sur les seules fonctions
portées."""

from __future__ import annotations

from dataclasses import replace

import numpy as np
import pytest

from golfgen.dressing.bunkers import BunkerError, beans, distance, legality, raster
from golfgen.dressing.green import points_in_polygon
from golfgen.routing.geometry import EPSILON, segments_intersect

# Tirages de référence de l'étude (planches).
REFERENCE_DRAWS = ((1, 1), (1, 8), (24, 8))
GRID = tuple((dx, dy) for dx in (0.0, 0.25, 0.5, 0.75) for dy in (0.0, 0.25, 0.5, 0.75))


def _simple(vertices: np.ndarray) -> bool:
    """Arêtes non voisines sans intersection."""
    following = np.roll(vertices, -1, axis=0)
    if (np.linalg.norm(following - vertices, axis=1) <= EPSILON).any():
        return False
    low, high = np.minimum(vertices, following), np.maximum(vertices, following)
    boxes = ((high[:, None, :] + EPSILON >= low[None, :, :]).all(axis=2)
             & (high[None, :, :] + EPSILON >= low[:, None, :]).all(axis=2))
    candidates = np.triu(boxes, k=2)
    candidates[0, -1] = False
    points, ends = vertices.tolist(), following.tolist()
    return not any(segments_intersect(points[i], ends[i], points[j], ends[j])
                   for i, j in zip(*np.nonzero(candidates), strict=True))


# --- raster -----------------------------------------------------------------

def test_diagonal_sand_contact_does_not_count_as_connected():
    assert raster.raster_topology(np.array(((0, 0), (1, 1))))["sand_components"] == 2


def test_closed_grass_pocket_is_detected_and_open_notch_is_not():
    ring = np.array([(x, y) for x in range(3) for y in range(3) if (x, y) != (1, 1)])
    assert raster.raster_topology(ring)["enclosed_grass_components"] == 1
    opened = ring[~np.all(ring == (1, 2), axis=1)]
    assert raster.raster_topology(opened)["enclosed_grass_components"] == 0


def test_local_frame_round_trips():
    local = np.array(((1.0, 2.0), (-3.5, 0.25)))
    tangent = np.array((0.6, -0.8))
    world = raster.to_world(local, (10.0, 5.0), tangent)
    np.testing.assert_allclose(raster.to_local(world, (10.0, 5.0), tangent), local, atol=1e-12)


def test_hull_depth_refuses_a_degenerate_hull():
    # Échec attendu dépendant de la seed : BunkerError, pas une ValueError
    # (que le pipeline laisserait remonter comme un bogue)
    assert not issubclass(BunkerError, ValueError)
    points = np.array(((0.0, 0.0), (1.0, 1.0), (2.0, 2.0)))
    with pytest.raises(BunkerError, match="dégénérée"):
        raster.hull_depth(points, raster.convex_hull(points))


def test_refused_bean_draw_raises_bunker_error():
    # Site réel converti (beans.draw_bean, sans monkeypatch) : un tirage refusé
    # par bean_outline est un échec attendu, BunkerError et pas ValueError
    refused = (0.60, 2.3, 1.7, 2.5, 0.10)
    ranges = {key: (value, value) for key, value in zip(beans.PARAM_KEYS, refused)}
    with pytest.raises(BunkerError, match="tirage refusé") as caught:
        beans.draw_bean(np.random.default_rng(0), ranges=ranges)
    assert not isinstance(caught.value, ValueError)


def test_empty_footprint_is_expected_at_pose_but_a_bug_in_helpers():
    # Aides de mesure : ValueError (bogue de l'appelant) ; pose_record, où
    # l'empreinte vient du contour tiré : BunkerError
    empty = np.zeros((0, 2), dtype=int)
    square = ((0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0))
    with pytest.raises(ValueError, match="empreinte raster vide"):
        legality.raster_gap(empty, square)
    with pytest.raises(ValueError, match="sans case de sable"):
        distance.sand_distance(empty, [(0, 0)])
    position = {"center": (0.5, 0.5), "outline": square, "cells": empty}
    with pytest.raises(BunkerError, match="empreinte raster vide"):
        legality.pose_record({}, "s", position, 1, (10, 10), ())

# --- haricots ---------------------------------------------------------------

def _drawn(seed: int, order: int, role: str = "landing", par: int = 4) -> beans.BeanDraw:
    return beans.draw_bean(beans.bunker_rng(seed, order, role, "haricot"),
                           beans.haricot_length_range(role, par), mixture=beans.K_GENTLE_MIXTURE)


@pytest.mark.parametrize("seed,order", REFERENCE_DRAWS)
def test_bean_outline_lies_on_the_field_zero_and_is_simple(seed, order):
    bean = _drawn(seed, order).bean()
    outline = beans.bean_outline(bean)
    assert outline.shape == (beans.N_RAYS, 2)
    assert np.abs(beans.field(bean, outline)).max() < 1e-4
    assert _simple(outline)
    np.testing.assert_array_equal(outline, beans.bean_outline(bean))


@pytest.mark.parametrize("seed,order", REFERENCE_DRAWS)
def test_bean_length_hits_its_draw(seed, order):
    draw = _drawn(seed, order)
    assert np.ptp(beans.bean_outline(draw.bean())[:, 0]) == pytest.approx(draw.length, abs=1e-3)
    assert 12.0 <= draw.length <= 16.0


@pytest.mark.parametrize("seed,order", REFERENCE_DRAWS)
def test_bean_raster_is_one_piece_and_matches_the_outline(seed, order):
    bean = _drawn(seed, order).bean()
    local = beans.bean_outline(bean)
    for angle in (0.0, 35.0, 120.0):
        tangent = np.array((np.cos(np.radians(angle)), np.sin(np.radians(angle))))
        for offset in GRID[::5]:
            cells = beans.bean_cells(bean, offset, tangent, outline=local)
            assert raster.raster_topology(cells) == raster.ONE_PIECE
            world = raster.to_world(local, offset, tangent)
            inside = points_in_polygon(cells + 0.5, world)
            assert inside.mean() > 0.97


def test_mirror_is_the_reflection_across_the_local_axis():
    bean = _drawn(1, 1).bean()
    plain, mirrored = replace(bean, mirror=False), replace(bean, mirror=True)
    points = np.random.default_rng(3).uniform(-6.0, 6.0, (200, 2))
    np.testing.assert_allclose(beans.field(mirrored, points), beans.field(plain, points * (1.0, -1.0)))
    assert beans.concave_side(beans.bean_outline(plain))["sign"] == 1
    assert beans.concave_side(beans.bean_outline(mirrored))["sign"] == -1


def test_draws_are_deterministic_and_respect_the_ranges():
    for seed in (1, 2, 3):
        for order in range(1, 19):
            draw = _drawn(seed, order)
            assert draw == _drawn(seed, order)
            for key in ("q", "e", "k_deep", "bend"):
                low, high = beans.SHAPE_RANGES[key]
                assert low <= getattr(draw.shape, key) <= high
            assert beans.K_GENTLE_MIXTURE[0][2][0] <= draw.shape.k_gentle <= beans.K_GENTLE_MAX
            assert any(lo <= draw.shape.k_gentle <= hi for _, _, (lo, hi) in beans.K_GENTLE_MIXTURE)


def test_streams_are_per_hole_role_then_category():
    first = beans.bunker_rng(1, 4, "landing", "haricot").uniform()
    assert first == beans.bunker_rng(1, 4, "landing", "haricot").uniform()
    assert first != beans.bunker_rng(1, 4, "green_guard", "haricot").uniform()
    assert first != beans.bunker_rng(1, 5, "landing", "haricot").uniform()
    with pytest.raises(ValueError):
        beans.haricot_length_range("landing", 3)


def test_orientation_puts_the_deep_notch_toward_the_axis():
    draw = _drawn(2, 3)
    tangent = np.array((1.0, 0.0))
    for side, mirror in (("left", True), ("right", False)):
        shape, posed = beans.orient_haricot(draw, {"role": "green_guard", "side": side, "tangent": tangent})
        assert shape.mirror is mirror and np.array_equal(posed, tangent)
        shape, posed = beans.orient_haricot(draw, {"role": "landing", "side": side, "tangent": tangent})
        assert shape == draw.shape
        assert np.array_equal(posed, tangent if draw.shape.mirror == mirror else -tangent)


def test_centre_outside_the_bean_raises():
    bean = beans.Bean(r1=1.0, r2=1.0, d=8.0, k_hollow=0.1, k_full=0.1)
    with pytest.raises(beans.BeanRefused) as error:
        beans.bean_outline(bean)
    assert error.value.code == beans.REFUSED_CENTRE
