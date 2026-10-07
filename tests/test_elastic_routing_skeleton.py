"""Tests de l'étape 3 : squelette global grossier (contour d'un arbre aléatoire).

Round correctif du 2026-10-07 (méandre en boustrophédon refusé à la Porte 3,
remplacé par une marche aléatoire biaisée sur un réseau grossier de nœuds —
voir PLAN.md et le rapport). Ce round ne couvre que l'arbre, son contour et
la coupure aux deux passages au clubhouse : pas de DP de découpage ni de
``CourseLayout`` testés ici.
"""

import math

import pytest

from experiments.elastic_routing import skeleton as sk
from experiments.elastic_routing.geometry import segment_distance
from experiments.elastic_routing.skeleton import (
    SkeletonGenerationError,
    build_skeleton,
    is_simple_polyline,
)


SEEDS = (1, 2, 3, 4, 5, 6)


def test_build_skeleton_is_deterministic_by_seed():
    first = build_skeleton(7)
    second = build_skeleton(7)
    assert first.clubhouse == second.clubhouse
    assert first.skeleton.front_leaves == second.skeleton.front_leaves
    assert first.skeleton.back_leaves == second.skeleton.back_leaves
    assert first.front_contour == second.front_contour
    assert first.back_contour == second.back_contour


@pytest.mark.parametrize("seed", SEEDS)
def test_contours_are_simple_closed_curves(seed):
    result = build_skeleton(seed)
    assert is_simple_polyline(list(result.front_contour))
    assert is_simple_polyline(list(result.back_contour))


@pytest.mark.parametrize("seed", SEEDS)
def test_two_subtrees_with_at_most_three_leaves_each(seed):
    result = build_skeleton(seed)
    skeleton = result.skeleton
    roots = skeleton.tree.children[result.clubhouse]
    assert len(roots) == 2
    assert skeleton.front_root != skeleton.back_root
    assert 1 <= len(skeleton.front_leaves) <= sk.MAX_LEAVES_PER_SUBTREE
    assert 1 <= len(skeleton.back_leaves) <= sk.MAX_LEAVES_PER_SUBTREE


@pytest.mark.parametrize("seed", SEEDS)
def test_halo_respected_for_every_pair_of_edges_without_shared_node(seed):
    """Toute paire d'arêtes sans nœud commun reste à >= HALO_MIN_DIST (distance segment-segment)."""
    result = build_skeleton(seed)
    edges = result.skeleton.tree.edges
    for i, (a, b) in enumerate(edges):
        world_a, world_b = sk.node_to_world(a), sk.node_to_world(b)
        for c, d in edges[i + 1:]:
            if a in (c, d) or b in (c, d):
                continue
            world_c, world_d = sk.node_to_world(c), sk.node_to_world(d)
            distance = segment_distance(world_a, world_b, world_c, world_d)
            assert distance >= sk.HALO_MIN_DIST - 1e-9, (a, b, c, d, distance)


@pytest.mark.parametrize("seed", SEEDS)
def test_branch_leading_to_a_leaf_is_at_least_min_length(seed):
    """Chaque branche menant à une feuille (depuis le clubhouse ou un nœud de fourche)

    atteint au moins ``MIN_LEAF_BRANCH_LENGTH``.
    """
    result = build_skeleton(seed)
    tree = result.skeleton.tree
    for leaf in (*result.skeleton.front_leaves, *result.skeleton.back_leaves):
        # distance depuis le clubhouse (longueur totale, pas seulement la fourche) :
        assert tree.arclen[leaf] - tree.arclen[result.clubhouse] >= sk.MIN_LEAF_BRANCH_LENGTH - 1e-9


def test_clubhouse_varies_with_seed():
    clubhouses = {build_skeleton(seed).clubhouse for seed in SEEDS}
    assert len(clubhouses) > 1


def test_rejection_is_bounded_and_explicit_for_an_impossible_budget(monkeypatch):
    """Une longueur minimale de branche hors de portée échoue vite, sans boucle infinie."""
    monkeypatch.setattr(sk, "MIN_LEAF_BRANCH_LENGTH", 1_000_000.0)
    monkeypatch.setattr(sk, "MAX_TREE_ATTEMPTS", 20)
    import time

    start = time.perf_counter()
    with pytest.raises(SkeletonGenerationError, match="20"):
        sk._build_tree(1)
    elapsed = time.perf_counter() - start
    assert elapsed < 5.0


@pytest.mark.parametrize("seed", SEEDS)
def test_skeleton_svg_renders(seed):
    from experiments.elastic_routing.skeleton import render_skeleton_svg

    result = build_skeleton(seed)
    svg = render_skeleton_svg(result)
    assert svg.startswith("<svg")
    assert f"seed {seed}" in svg


def test_nodes_stay_clear_of_the_map_edge_given_the_ribbon_offset_and_widest_fairway():
    """Marge requise (offset 12 + demi-largeur max 9 = 21) tenue par le réseau (24, 360)."""
    margin_needed = sk.RIBBON_OFFSET + max(spec.width_max for spec in sk.PAR_SPECS.values()) / 2.0
    assert sk.NODE_OFFSET >= margin_needed
    last_coord = sk.NODE_OFFSET + (sk.NODE_COUNT - 1) * sk.NODE_PITCH
    assert sk.MAP_SIZE - last_coord >= margin_needed
