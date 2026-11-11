"""Pots (``golfgen.dressing.bunkers.pots``, round R1) : motifs, tailles mêlées
et géométrie des grappes. Tests repris de ceux de l'étude des bunkers (pots,
grappes et pots d'appel)."""

from __future__ import annotations

import numpy as np
import pytest

from golfgen.dressing.bunkers import pots
from golfgen.dressing.bunkers.raster import cell_gap

ANCHOR = {"center": np.array((120.3, 80.6)), "normal": np.array((-0.6, 0.8)),
          "tangent": np.array((0.8, 0.6))}


def test_exact_requested_patterns_and_grass_gap():
    assert pots.PATTERN == ("HSH", "SSS", "SSS", "HSH")
    assert pots.SMALL_PATTERN == ("HSH", "SSS", "HSH")
    assert len(pots.OFFSETS) == 8 and len(pots.SMALL_OFFSETS) == 5
    assert {tuple(c) for c in pots.SMALL_OFFSETS} <= {tuple(c) for c in pots.OFFSETS}
    assert cell_gap(pots.pot_cells((0, 0)), pots.pot_cells((6, 0))) == 3.0
    for count in (2, 3, 4):
        sizes = pots.mixed_sizes(1, 7, count)
        assert len(sizes) == count and any(sizes) and not all(sizes)
        assert sizes == pots.mixed_sizes(1, 7, count)
    with pytest.raises(ValueError):
        pots.mixed_sizes(1, 7, 1)


def test_count_probabilities_follow_the_approach_width():
    for width in (3.0, 5.0, 7.0, 9.0, 13.0):
        p2, p3, p4 = pots.count_probs(width)
        assert p2 + p3 + p4 == pytest.approx(1.0) and min(p2, p3, p4) >= 0.0
    assert pots.count_probs(7.0) == (0.0, 1.0, 0.0)
    assert pots.count_probs(3.0)[0] == 0.7 and pots.count_probs(13.0)[2] == 0.6


def test_candidate_cluster_keeps_the_motif_count_and_is_seeded():
    tangent = np.array((0.0, 1.0))
    for count, motifs in pots.MOTIFS.items():
        first = pots.candidate_outlines(motifs[0], ANCHOR["center"], tangent, pots.cluster_rng(1, 3))
        again = pots.candidate_outlines(motifs[0], ANCHOR["center"], tangent, pots.cluster_rng(1, 3))
        assert len(first) == count
        for a, b in zip(first, again):
            assert a.shape == (64, 2) and np.array_equal(a, b)


def test_group_at_spreads_and_backs_the_whole_cluster():
    smooth = np.array(((10.0, 10.0), (16.0, 12.0), (12.0, 17.0)))
    tangent = np.array((0.0, 1.0))
    group = pots.group_at(smooth, tangent, 1.0, 0.0)
    moved = pots.group_at(smooth, tangent, 1.0, 4.0)
    for a, b in zip(group, moved):
        assert np.array_equal(b, a - (0, 4))
    assert pots.minimum_gap(pots.group_at(smooth, tangent, 1.4, 0.0)) >= pots.minimum_gap(group)


@pytest.mark.parametrize("seed,order", ((1, 8), (1, 1), (3, 2)))
def test_duo_and_trio_keep_three_grass_blocks(seed, order):
    spacing = pots.shared_spacing(ANCHOR, seed, order, 2)
    for amplitude in pots.STAGGER_AMPLITUDES:
        offsets = pots.stagger_offsets(seed, order, 2, amplitude)
        assert offsets.sum() == 0.0
        duo = pots.landing_group(ANCHOR, 2, spacing, offsets)
        assert len(duo) == 2 and pots.minimum_gap(duo) >= pots.MIN_GRASS
    trio = pots.raster_group(ANCHOR, np.array((-4.0, 0.5, 4.0)), np.array((-3.0, 2.5, 0.5)))
    assert len(trio) == 3 and all(len(p) == 8 for p in trio)
    assert pots.desired_count(seed, order) in (2, 3)
    with pytest.raises(ValueError):
        pots.stagger_offsets(seed, order, 4, 1.0)
