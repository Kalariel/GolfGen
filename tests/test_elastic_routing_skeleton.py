"""Tests de l'étape 3 : squelette global grossier (contour d'un arbre aléatoire).

3e round correctif du 2026-10-07 (voir PLAN.md et le rapport) : contour
fermé (bug d'ouverture corrigé), budget de sous-arbre imposé, 2-3 feuilles
obligatoires, offset configurable. Toujours sans DP de découpage ni
``CourseLayout`` testés ici.
"""

import pytest

from experiments.elastic_routing import skeleton as sk
from experiments.elastic_routing.geometry import segment_distance
from experiments.elastic_routing.skeleton import (
    SkeletonGenerationError,
    build_skeleton,
    is_simple_polyline,
)


SEEDS_SMALL = (1, 2, 3, 4, 5, 6)
SEEDS_20 = tuple(range(1, 21))


def test_build_skeleton_is_deterministic_by_seed():
    first = build_skeleton(7)
    second = build_skeleton(7)
    assert first.clubhouse == second.clubhouse
    assert first.skeleton.front_leaves == second.skeleton.front_leaves
    assert first.skeleton.back_leaves == second.skeleton.back_leaves
    assert first.front_contour == second.front_contour
    assert first.back_contour == second.back_contour


@pytest.mark.parametrize("seed", SEEDS_20)
def test_contour_is_closed_simple_clubhouse_to_clubhouse(seed):
    """Chaque arc coupé part du clubhouse et y revient ; le contour fermé est simple.

    Bug du round précédent : le contour n'était jamais refermé au
    clubhouse (deux extrémités indépendantes, visible comme une fente dans
    le SVG de la seed 2). Vérifié ici sur les seeds 1 à 20.
    """
    result = build_skeleton(seed)
    skeleton = result.skeleton
    front_tour = sk._full_tour(skeleton.front_root, skeleton.tree, result.clubhouse, result.config)
    back_tour = sk._full_tour(skeleton.back_root, skeleton.tree, result.clubhouse, result.config)
    assert front_tour[0] == result.clubhouse and front_tour[-1] == result.clubhouse
    assert back_tour[0] == result.clubhouse and back_tour[-1] == result.clubhouse
    assert is_simple_polyline(list(result.front_contour))
    assert is_simple_polyline(list(result.back_contour))


def _subtree_edges_world(tree, root, config):
    """Arêtes (en coordonnées monde) du sous-arbre enraciné à ``root``.

    Inclut l'arête de rattachement au clubhouse : ``root`` lui-même fait
    partie de ``_subtree_nodes(tree, root)``, donc l'arête ``(clubhouse,
    root)`` (parent=clubhouse, enfant=root) est couverte.
    """
    nodes = set(sk._subtree_nodes(tree, root))
    return [
        (sk.node_to_world(config, a), sk.node_to_world(config, b))
        for a, b in tree.edges
        if b in nodes
    ]


@pytest.mark.parametrize("seed", SEEDS_20)
@pytest.mark.parametrize("offset", (12.0, 20.0))
def test_contour_stays_at_offset_distance_from_its_tree_everywhere(seed, offset):
    """Invariant géométrique remplaçant l'ancien test de convexité locale de cap.

    Un décalage de polyligne standard (jointure ronde convexe, intersection
    concave vérifiée dans les deux segments) place CHAQUE point du contour à
    une distance EXACTE de ``offset`` de l'arbre dont il est issu : les
    jointures rondes sont des arcs de rayon ``offset`` centrés sur un sommet
    de l'arbre, et les intersections concaves ne sont acceptées (sinon
    ``ContourOffsetError``) que si elles tombent dans les deux segments
    décalés, c'est-à-dire dans la zone de projection perpendiculaire valide
    des deux arêtes réelles adjacentes (donc aussi à distance ``offset``
    exacte). Pas de pointe (distance > offset + tolérance) ni de morsure
    (distance < offset - tolérance) nulle part sur le contour. Remplace
    l'ancien test ad hoc sur la forme du cap d'une feuille (6a61a3d), qui
    masquait le même symptôme (pointes, caps mordus) sans vérifier
    directement la distance à l'arbre.
    """
    result = build_skeleton(seed, offset=offset)
    skeleton = result.skeleton
    config = result.config
    tolerance = 1e-6
    for contour, root in (
        (result.front_contour, skeleton.front_root),
        (result.back_contour, skeleton.back_root),
    ):
        edges = _subtree_edges_world(skeleton.tree, root, config)
        for point in contour:
            distance = min(sk._point_to_segment_distance(point, a, b) for a, b in edges)
            assert offset - tolerance <= distance <= offset + tolerance, (
                seed, offset, point, distance,
            )


@pytest.mark.parametrize("seed", SEEDS_20)
def test_each_subtree_within_its_budget_window(seed):
    """Le budget de longueur par sous-arbre est IMPOSÉ, pas seulement visé.

    Bug du round précédent : les seeds 3 et 4 produisaient un sous-arbre
    (336 blocs) bien sous le minimum (~550) ; le tirage aurait dû être
    rejeté plutôt qu'accepté. Vérifié ici sur les seeds 1 à 20.
    """
    result = build_skeleton(seed)
    low, high = result.config.subtree_length_range
    tolerance = result.config.node_pitch
    assert low - 1e-6 <= result.skeleton.front_length <= high + tolerance + 1e-6
    assert low - 1e-6 <= result.skeleton.back_length <= high + tolerance + 1e-6


@pytest.mark.parametrize("seed", SEEDS_20)
def test_two_subtrees_with_two_or_three_leaves_never_one(seed):
    result = build_skeleton(seed)
    skeleton = result.skeleton
    roots = skeleton.tree.children[result.clubhouse]
    assert len(roots) == 2
    assert skeleton.front_root != skeleton.back_root
    assert 2 <= len(skeleton.front_leaves) <= sk.MAX_LEAVES_PER_SUBTREE
    assert 2 <= len(skeleton.back_leaves) <= sk.MAX_LEAVES_PER_SUBTREE


@pytest.mark.parametrize("seed", SEEDS_SMALL)
def test_halo_respected_for_every_pair_of_edges_without_shared_node(seed):
    """Toute paire d'arêtes sans nœud commun reste à >= halo_min_dist (distance segment-segment)."""
    result = build_skeleton(seed)
    config = result.config
    edges = result.skeleton.tree.edges
    for i, (a, b) in enumerate(edges):
        world_a, world_b = sk.node_to_world(config, a), sk.node_to_world(config, b)
        for c, d in edges[i + 1:]:
            if a in (c, d) or b in (c, d):
                continue
            world_c, world_d = sk.node_to_world(config, c), sk.node_to_world(config, d)
            distance = segment_distance(world_a, world_b, world_c, world_d)
            assert distance >= config.halo_min_dist - 1e-9, (a, b, c, d, distance)


@pytest.mark.parametrize("seed", SEEDS_SMALL)
def test_branch_leading_to_a_leaf_is_at_least_min_length(seed):
    result = build_skeleton(seed)
    tree = result.skeleton.tree
    min_leaf = result.config.min_leaf_branch_length
    for leaf in (*result.skeleton.front_leaves, *result.skeleton.back_leaves):
        # Longueur de la branche = depuis le point de fourche (le premier
        # noeud apres le clubhouse), pas depuis le clubhouse lui-meme (voir
        # _grow_subtree_steps : la tige elle-meme n'est pas une "branche").
        fork_point = (result.skeleton.front_root if leaf in result.skeleton.front_leaves
                     else result.skeleton.back_root)
        assert tree.arclen[leaf] - tree.arclen[fork_point] >= min_leaf - 1e-9


def test_clubhouse_varies_with_seed():
    clubhouses = {build_skeleton(seed).clubhouse for seed in SEEDS_SMALL}
    assert len(clubhouses) > 1


def test_rejection_is_bounded_and_explicit_for_an_impossible_budget(monkeypatch):
    """Une fenêtre de budget hors de portée échoue explicitement, sans boucle infinie."""
    import dataclasses

    base = sk.make_config(12.0)
    impossible = dataclasses.replace(base, subtree_length_range=(1_000_000.0, 1_000_001.0))
    monkeypatch.setattr(sk, "MAX_TREE_ATTEMPTS", 20)
    import time

    start = time.perf_counter()
    with pytest.raises(SkeletonGenerationError, match="20"):
        sk._build_tree(1, impossible)
    elapsed = time.perf_counter() - start
    assert elapsed < 5.0


@pytest.mark.parametrize("offset", (12.0, 20.0))
def test_offset_configurable_grid_and_halo(offset):
    config = sk.make_config(offset)
    assert config.halo_min_dist == 2.0 * offset + sk.HALO_MARGIN
    assert config.node_pitch >= config.halo_min_dist
    half_fairway_max = max(spec.width_max for spec in sk.PAR_SPECS.values()) / 2.0
    margin_needed = offset + half_fairway_max
    assert config.node_margin >= margin_needed
    last_coord = config.node_margin + (config.node_count - 1) * config.node_pitch
    assert sk.MAP_SIZE - last_coord >= margin_needed


def test_offset_12_matches_round2_grid():
    config = sk.make_config(12.0)
    assert (config.node_pitch, config.node_count, config.node_margin) == (48.0, 8, 24.0)


def test_offset_20_grid():
    config = sk.make_config(20.0)
    assert config.node_pitch == 64.0
    assert config.halo_min_dist == 63.0


@pytest.mark.parametrize("seed", SEEDS_SMALL)
def test_skeleton_svg_renders(seed):
    from experiments.elastic_routing.skeleton import render_skeleton_svg

    result = build_skeleton(seed)
    svg = render_skeleton_svg(result)
    assert svg.startswith("<svg")
    assert f"seed {seed}" in svg
