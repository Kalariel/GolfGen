"""Tests pour le placement (packing) des squelettes de trous (étape 2)."""

import random

import pytest

from golfgen.clubhouse import pick_clubhouse
from golfgen.config import CourseConfig
from golfgen.hole_gen import HoleGenerator
from golfgen.packing import Packer, score_placement
from golfgen.utils import distance

# Le packing est un problème de recherche (candidats aléatoires + réparation
# locale) — quelques dizaines de secondes par seed. On ne teste ici que 2
# seeds (validé manuellement sur davantage pendant le développement) pour
# garder la suite de tests rapide.
SEEDS = [42, 1]


def _pack(seed: int):
    config = CourseConfig(seed=seed)
    rng = random.Random(config.seed + 1)
    clubhouse_pos, _ = pick_clubhouse(config, rng)
    shapes = HoleGenerator(config).generate_all()
    pieces = Packer(config, clubhouse_pos, rng).pack(shapes)
    return config, clubhouse_pos, pieces


@pytest.fixture(scope="module", params=SEEDS)
def packed(request):
    return _pack(request.param)


class TestPackingFeasibility:
    """Un packing valide ne doit avoir aucune violation dure."""

    def test_no_hard_violations(self, packed):
        config, clubhouse_pos, pieces = packed
        hard, _ = score_placement(pieces, config, clubhouse_pos)
        assert hard == 0

    def test_all_pieces_placed(self, packed):
        _, _, pieces = packed
        assert len(pieces) == 18
        assert all(p is not None for p in pieces)

    def test_within_bounds(self, packed):
        config, _, pieces = packed
        margin = config.routing.grid_margin
        for piece in pieces:
            for x, y in piece.waypoints_ab:
                assert margin - 1e-6 <= x <= config.width - margin + 1e-6
                assert margin - 1e-6 <= y <= config.height - margin + 1e-6


class TestPackingAnchors:
    """4 trous (destinés à devenir 1/9/10/18 au séquençage) sont désignés
    ancres et placés près du clubhouse, séparément des 14 intérieurs."""

    def test_exactly_four_anchors(self, packed):
        _, _, pieces = packed
        assert sum(1 for p in pieces if p.is_anchor) == 4

    def test_anchors_closer_to_clubhouse_than_interior_median(self, packed):
        _, clubhouse_pos, pieces = packed
        anchor_dists = sorted(distance(p.anchor, clubhouse_pos) for p in pieces if p.is_anchor)
        interior_dists = sorted(distance(p.anchor, clubhouse_pos) for p in pieces if not p.is_anchor)
        interior_median = interior_dists[len(interior_dists) // 2]
        assert max(anchor_dists) < interior_median


class TestPackingDeterminism:
    """Même seed -> même placement (position ET rotation)."""

    def test_same_seed_same_result(self):
        _, _, pieces_a = _pack(42)
        _, _, pieces_b = _pack(42)
        assert [p.anchor for p in pieces_a] == [p.anchor for p in pieces_b]
        assert [p.rotation for p in pieces_a] == [p.rotation for p in pieces_b]
