"""Tests pour le séquençage (étape 3) : ordre de jeu + sens de chaque trou."""

import math
import random

import pytest

from golfgen.clubhouse import pick_clubhouse
from golfgen.config import CourseConfig
from golfgen.hole_gen import HoleGenerator, HoleShape
from golfgen.packing import PlacedPiece, Packer
from golfgen.sequencing import (
    _nn_open_chain, _open_chain_cost, _solve_open_chain,
    local_search, nearest_neighbor_construct, ordered_waypoints, sequence, tour_cost,
)
from golfgen.utils import distance


def _synthetic_piece(par: int, a: tuple, b: tuple, sector_index: int = 0,
                      is_anchor: bool = False) -> PlacedPiece:
    shape = HoleShape(par=par, length=int(distance(a, b)),
                       waypoints=[(0.0, 0.0), (distance(a, b), 0.0)],
                       fairway_width=10, green_radius=8)
    return PlacedPiece(shape=shape, anchor=a, rotation=0.0, endpoint_a=a, endpoint_b=b,
                        waypoints_ab=[a, b], sector_index=sector_index, is_anchor=is_anchor)


@pytest.fixture
def synthetic_pieces():
    """6 trous disposés grossièrement en cercle autour du clubhouse (100, 100)."""
    pieces = []
    for i in range(6):
        angle = i * math.pi / 3
        a = (100 + 60 * math.cos(angle), 100 + 60 * math.sin(angle))
        b = (100 + 120 * math.cos(angle), 100 + 120 * math.sin(angle))
        pieces.append(_synthetic_piece(par=4, a=a, b=b, sector_index=i))
    return pieces


class TestSequencingValidity:
    def test_nearest_neighbor_is_valid_permutation(self, synthetic_pieces):
        order, flips = nearest_neighbor_construct(synthetic_pieces, (100, 100))
        assert sorted(order) == list(range(len(synthetic_pieces)))
        assert len(flips) == len(synthetic_pieces)
        assert all(isinstance(f, bool) for f in flips)

    def test_local_search_is_valid_permutation(self, synthetic_pieces):
        config = CourseConfig(seed=42, num_holes=6)
        order, flips = sequence(synthetic_pieces, (100, 100), config)
        assert sorted(order) == list(range(len(synthetic_pieces)))
        assert len(flips) == len(synthetic_pieces)


class TestSequencingImprovement:
    def test_local_search_never_worsens_cost(self, synthetic_pieces):
        config = CourseConfig(seed=42, num_holes=6)
        clubhouse = (100.0, 100.0)
        order0, flips0 = nearest_neighbor_construct(synthetic_pieces, clubhouse)
        cost0 = tour_cost(order0, flips0, synthetic_pieces, clubhouse, config)
        order1, flips1 = local_search(order0, flips0, synthetic_pieces, clubhouse, config)
        cost1 = tour_cost(order1, flips1, synthetic_pieces, clubhouse, config)
        assert cost1 <= cost0 + 1e-9


class TestDirectionFlipIsFree:
    """Un retournement ne doit changer que l'ordre/les labels, jamais une coordonnée."""

    def test_flip_does_not_recompute_geometry(self, synthetic_pieces):
        piece = synthetic_pieces[0]
        original_points = set(piece.waypoints_ab)
        flipped_wps = ordered_waypoints(piece, flipped=True)
        normal_wps = ordered_waypoints(piece, flipped=False)
        assert set(flipped_wps) == set(normal_wps) == original_points
        assert flipped_wps == list(reversed(normal_wps))


@pytest.fixture
def synthetic_pieces_with_anchors():
    """4 ancres près du clubhouse (100, 100) + 4 pièces intérieures plus
    loin — de quoi exercer `_sequence_with_anchors`/`_solve_open_chain`."""
    clubhouse = (100.0, 100.0)
    pieces = []
    for angle in (0.1, 0.4, 0.7, 1.0):
        near = (clubhouse[0] + 20 * math.cos(angle), clubhouse[1] + 20 * math.sin(angle))
        far = (clubhouse[0] + 150 * math.cos(angle), clubhouse[1] + 150 * math.sin(angle))
        pieces.append(_synthetic_piece(par=4, a=near, b=far, is_anchor=True))
    for angle in (0.2, 0.5, 0.8, 0.95):
        a = (clubhouse[0] + 100 * math.cos(angle), clubhouse[1] + 100 * math.sin(angle))
        b = (clubhouse[0] + 140 * math.cos(angle + 0.05), clubhouse[1] + 140 * math.sin(angle + 0.05))
        pieces.append(_synthetic_piece(par=4, a=a, b=b, is_anchor=False))
    return pieces, clubhouse


class TestSequencingWithAnchors:
    """Quand 4 ancres existent, elles occupent des positions fixes
    (0, n/2-1, n/2, n-1) et seules les intérieures sont réordonnées."""

    def test_sequence_fixes_anchors_at_expected_slots(self, synthetic_pieces_with_anchors):
        pieces, clubhouse = synthetic_pieces_with_anchors
        config = CourseConfig(seed=42, num_holes=8)
        order, flips = sequence(pieces, clubhouse, config)
        n = len(order)
        assert sorted(order) == list(range(n))
        assert len(flips) == n
        for pos in (0, n // 2 - 1, n // 2, n - 1):
            assert pieces[order[pos]].is_anchor

    def test_solve_open_chain_valid_permutation(self, synthetic_pieces_with_anchors):
        pieces, clubhouse = synthetic_pieces_with_anchors
        interior = [i for i, p in enumerate(pieces) if not p.is_anchor]
        order, flips = _solve_open_chain(interior, clubhouse, clubhouse, pieces)
        assert sorted(order) == sorted(interior)
        assert set(flips.keys()) == set(interior)

    def test_solve_open_chain_never_worsens_cost(self, synthetic_pieces_with_anchors):
        pieces, clubhouse = synthetic_pieces_with_anchors
        interior = [i for i, p in enumerate(pieces) if not p.is_anchor]
        nn_order, nn_flips = _nn_open_chain(interior, clubhouse, pieces)
        nn_cost = _open_chain_cost(nn_order, nn_flips, pieces, clubhouse, clubhouse)
        order, flips = _solve_open_chain(interior, clubhouse, clubhouse, pieces)
        cost = _open_chain_cost(order, flips, pieces, clubhouse, clubhouse)
        assert cost <= nn_cost + 1e-9


class TestSequencingIntegration:
    """Bout-en-bout sur un petit parcours réel (peu de trous pour la vitesse)."""

    @pytest.mark.parametrize("seed", [42, 1])
    def test_sequence_valid_on_packed_course(self, seed):
        config = CourseConfig(seed=seed, num_holes=6)
        config.routing.par_distribution = [4, 3, 5, 4, 3, 4]
        rng = random.Random(config.seed + 1)
        clubhouse_pos, _ = pick_clubhouse(config, rng)
        shapes = HoleGenerator(config).generate_all()
        pieces = Packer(config, clubhouse_pos, rng).pack(shapes)
        order, flips = sequence(pieces, clubhouse_pos, config)
        assert sorted(order) == list(range(6))
        assert len(flips) == 6
