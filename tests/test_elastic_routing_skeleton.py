"""Tests de l'étape 3 : squelette global grossier (contour d'un arbre aléatoire)."""

from collections import Counter

import pytest

from experiments.elastic_routing import skeleton as sk
from experiments.elastic_routing.skeleton import (
    SkeletonGenerationError,
    build_skeleton,
    is_simple_polyline,
)


SEEDS = (1, 2, 3)


def test_build_skeleton_is_deterministic_by_seed():
    first = build_skeleton(7)
    second = build_skeleton(7)
    assert first.layout.to_json() == second.layout.to_json()


@pytest.mark.parametrize("seed", SEEDS)
def test_contours_are_simple_closed_curves(seed):
    result = build_skeleton(seed)
    assert is_simple_polyline(list(result.front_contour))
    assert is_simple_polyline(list(result.back_contour))


@pytest.mark.parametrize("seed", SEEDS)
def test_two_subtrees_with_at_most_three_leaves_each(seed):
    result = build_skeleton(seed)
    skeleton = result.skeleton
    roots = skeleton.tree.children[sk.CLUBHOUSE_CELL]
    assert len(roots) == 2
    assert skeleton.front_root != skeleton.back_root
    assert 1 <= len(skeleton.front_leaves) <= sk.MAX_LEAVES_PER_SUBTREE
    assert 1 <= len(skeleton.back_leaves) <= sk.MAX_LEAVES_PER_SUBTREE


@pytest.mark.parametrize("seed", SEEDS)
def test_halo_respected_between_non_locally_connected_cells(seed):
    """Deux cellules de l'arbre non reliées localement restent à >= HALO_MIN_DIST.

    Vérifie l'invariant que ``_halo_ok`` impose pendant la croissance, sur
    l'arbre final complet (front + back + clubhouse), y compris entre les
    deux sous-arbres.
    """
    result = build_skeleton(seed)
    tree = result.skeleton.tree
    cells = list(tree.parent)
    near_hub = sk.HUB_RADIUS
    clubhouse_world = sk.cell_to_world(sk.CLUBHOUSE_CELL)
    violations = []
    for i, a in enumerate(cells):
        for b in cells[i + 1:]:
            if tree.is_locally_connected(a, b):
                continue
            world_a, world_b = sk.cell_to_world(a), sk.cell_to_world(b)
            import math

            if (math.dist(world_a, clubhouse_world) < near_hub
                    and math.dist(world_b, clubhouse_world) < near_hub):
                continue
            distance = math.dist(world_a, world_b)
            if distance < sk.HALO_MIN_DIST - 1e-6:
                violations.append((a, b, distance))
    assert violations == []


def test_rejection_is_bounded_and_explicit_for_an_impossible_budget(monkeypatch):
    """Une longueur minimale de branche hors de portée échoue vite, sans boucle infinie.

    Même en parcourant toute la carte, un sous-arbre ne peut pas atteindre
    une ``MIN_LEAF_BRANCH_LENGTH`` plus grande que la carte elle-même :
    chaque tirage échoue en « méandre tronqué trop court », et la boucle
    bornée de ``_build_tree`` lève explicitement après ``MAX_TREE_ATTEMPTS``.
    """
    monkeypatch.setattr(sk, "MIN_LEAF_BRANCH_LENGTH", 1_000_000.0)
    monkeypatch.setattr(sk, "MAX_TREE_ATTEMPTS", 20)
    import time

    start = time.perf_counter()
    with pytest.raises(SkeletonGenerationError, match="20"):
        sk._build_tree(1)
    elapsed = time.perf_counter() - start
    assert elapsed < 5.0


@pytest.mark.parametrize("seed", SEEDS)
def test_par_quota_two_par3_two_par5_five_par4_per_nine(seed):
    result = build_skeleton(seed)
    for nine in (result.layout.front, result.layout.back):
        counts = Counter(hole.par for hole in nine.holes)
        assert counts == {3: 2, 4: 5, 5: 2}


@pytest.mark.parametrize("seed", SEEDS)
def test_nine_plus_nine_holes_in_order(seed):
    result = build_skeleton(seed)
    assert tuple(hole.order for hole in result.layout.front.holes) == tuple(range(1, 10))
    assert tuple(hole.order for hole in result.layout.back.holes) == tuple(range(10, 19))


@pytest.mark.parametrize("seed", SEEDS)
def test_construction_links_within_12_60(seed):
    """Les liaisons jouables (entre deux trous) respectent [12, 60] à la construction.

    Les stubs clubhouse (``from_hole_order`` ou ``to_hole_order`` à ``None``)
    ne sont pas des liaisons jouables ; leur plage propre est [12, STUB_MAX]
    (voir PLAN.md et ``golfgen.loop_router``).
    """
    result = build_skeleton(seed)
    for link in result.layout.links:
        is_stub = link.from_hole_order is None or link.to_hole_order is None
        upper = sk.STUB_MAX if is_stub else sk.LINK_CONSTRUCTION_MAX
        assert sk.LINK_CONSTRUCTION_MIN - 0.5 <= link.length <= upper + 1e-6, (
            link.length, is_stub,
        )


@pytest.mark.parametrize("seed", SEEDS)
def test_skeleton_svg_and_layout_svg_render(seed):
    from experiments.elastic_routing.geometry import ValidationRules
    from experiments.elastic_routing.render import render_svg
    from experiments.elastic_routing.skeleton import render_skeleton_svg

    result = build_skeleton(seed)
    skeleton_svg = render_skeleton_svg(result)
    assert skeleton_svg.startswith("<svg")
    rules = ValidationRules(width=result.layout.width, height=result.layout.height, link_max=60.0)
    layout_svg = render_svg(result.layout, rules)
    assert layout_svg.startswith("<svg")
