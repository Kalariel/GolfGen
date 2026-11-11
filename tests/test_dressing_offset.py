"""Dilatation arrondie et fermeture (``golfgen.dressing.offset``, round R3f) :
distance signée sur grille (exacte dans la bande, identique à la grille
entière), marching squares, dilatation d'un carré, fermeture des angles
rentrants. Tests repris de l'outil des planches R3e, d'où le mécanisme a
été sorti."""

from __future__ import annotations

import math

import numpy as np
import pytest

from golfgen.dressing import offset as off
from golfgen.dressing.green import points_in_polygon, shoelace

SQUARE = np.array(((0.0, 0.0), (10.0, 0.0), (10.0, 10.0), (0.0, 10.0)))
ELL = np.array(((0.0, 0.0), (10.0, 0.0), (10.0, 4.0), (4.0, 4.0), (4.0, 10.0), (0.0, 10.0)))


def test_grid_signed_distance_is_exact_and_signed():
    xs = np.array((-2.0, 5.0, 12.0))
    ys = np.array((5.0, 13.0))
    values = off.grid_signed_distance(xs, ys, SQUARE)
    assert values[0].tolist() == pytest.approx([2.0, -5.0, 2.0])
    assert values[1].tolist() == pytest.approx([math.hypot(2.0, 3.0), 3.0, math.hypot(2.0, 3.0)])


def test_band_keeps_exact_values_near_the_boundary_and_signs_beyond():
    """Dans la bande : valeurs identiques au bit près à la grille entière ;
    au-delà : ``±inf`` selon l'intérieur."""
    rng = np.random.default_rng(5)
    angles = np.sort(rng.uniform(0.0, 2.0 * math.pi, 40))
    radii = rng.uniform(6.0, 12.0, 40)
    polygon = np.column_stack((20 + radii * np.cos(angles), 20 + radii * np.sin(angles)))
    xs = ys = 0.15 * np.arange(270)
    full = off.grid_signed_distance(xs, ys, polygon)
    band = 2.0
    banded = off.grid_signed_distance(xs, ys, polygon, band)
    near = np.abs(full) <= band
    assert near.sum() > 1000 and (~near).sum() > 1000
    assert np.array_equal(banded[near], full[near])
    assert np.array_equal(np.sign(banded[~near]), np.sign(full[~near]))
    assert np.isinf(banded[~near]).all()


def test_inside_test_matches_points_in_polygon():
    xs = ys = 0.37 * np.arange(-3, 32)
    values = off.grid_signed_distance(xs, ys, ELL, band=1.0)
    gx, gy = np.meshgrid(xs, ys)
    inside = points_in_polygon(np.column_stack((gx.ravel(), gy.ravel())), ELL).reshape(gx.shape)
    on_edge = np.abs(off.grid_signed_distance(xs, ys, ELL)) < 1e-12
    assert np.array_equal((values < 0)[~on_edge], inside[~on_edge])


def test_marching_squares_closes_a_circle():
    step, radius = 0.1, 3.0
    xs = ys = step * np.arange(81)
    gx, gy = np.meshgrid(xs, ys)
    values = np.hypot(gx - 4.0, gy - 4.0) - radius
    loops = off.marching_squares(values, (0.0, 0.0), step)
    assert len(loops) == 1 and shoelace(loops[0]) > 0
    assert shoelace(loops[0]) == pytest.approx(math.pi * radius ** 2, rel=2e-3)


def test_offset_of_a_square_is_its_rounded_buffer():
    shape, loops = off.offset_closing(SQUARE, 1.5, closing=0.0)
    assert loops == 1
    expected = 100.0 + 4 * 10.0 * 1.5 + math.pi * 1.5 ** 2
    assert shoelace(shape) == pytest.approx(expected, rel=2e-3)
    # fermeture sans effet sur un convexe
    closed, _ = off.offset_closing(SQUARE, 1.5, closing=3.0)
    assert shoelace(closed) == pytest.approx(expected, rel=3e-3)


def test_closing_rounds_reentrant_corners():
    plain, _ = off.offset_closing(ELL, 1.5, closing=0.0)
    closed, loops = off.offset_closing(ELL, 1.5, closing=3.0)
    assert loops == 1 and shoelace(closed) > shoelace(plain) + 1.0


def test_resample_keeps_a_constant_step():
    loop = off.resample(SQUARE, 0.5)
    steps = np.hypot(*(loop - np.roll(loop, -1, axis=0)).T)
    assert len(loop) == 80 and steps == pytest.approx(0.5)
