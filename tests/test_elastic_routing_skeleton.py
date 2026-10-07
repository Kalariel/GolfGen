"""Tests de l'étape 3 : squelette global grossier (contour d'un arbre aléatoire).

3e round correctif du 2026-10-07 (voir PLAN.md et le rapport) : contour
fermé (bug d'ouverture corrigé), budget de sous-arbre imposé, 2-3 feuilles
obligatoires, offset configurable. Toujours sans DP de découpage ni
``CourseLayout`` testés ici.

4e round correctif (même date) : les deux sous-arbres sont désormais
décalés comme un tour COMBINÉ (un seul passage par ``build_contour``, pas
deux contours indépendants chacun refermé par un cap au clubhouse) — voir
``_combined_tour``. Round précédent (bug) : les deux caps, plantés à ~180°
l'un de l'autre par construction, se recoupaient systématiquement près du
clubhouse (100/100 tirages, seeds 1-50 x offsets 12/20) ; chaque contour
était individuellement simple (``is_simple_polyline``), donc le test ne le
détectait pas.

5e round correctif (même date) : la 1re version du tour combiné répartissait
chaque point du contour décalé à UN SEUL des deux arcs via un tag
``'front'``/``'back'`` par sommet source. Bug : au sommet du clubhouse où la
jointure est CONVEXE (un arc de plusieurs points, pas un point unique), tout
l'arc était assigné à un seul côté — l'autre arc n'avait alors plus son
point de retour au clubhouse et se refermait n'importe où au milieu de la
carte (bouts pendants, seed 1 offset 20 à ~48 blocs du clubhouse au lieu de
~offset). Remplacé par un découpage par INDICE (``_split_combined_contour``,
``build_contour(..., return_source_index=True)``) : chaque groupe de points
produit aux deux occurrences du clubhouse est inclus EN ENTIER dans les DEUX
arcs (ils partagent ces deux groupes à leurs extrémités, ce ne sont pas deux
boucles indépendantes mais deux portions d'un même contour fermé coupé à ses
deux passages au clubhouse — la coupure prévue par le plan initial).
"""

import math
from functools import lru_cache

import pytest

from experiments.elastic_routing import skeleton as sk
from experiments.elastic_routing.geometry import segment_distance, segments_intersect
from experiments.elastic_routing.skeleton import (
    SkeletonGenerationError,
    build_skeleton,
    is_simple_polyline,
)


SEEDS_SMALL = (1, 2, 3, 4, 5, 6)
SEEDS_20 = tuple(range(1, 21))
SEEDS_50 = tuple(range(1, 51))
OFFSETS = (12.0, 20.0)


@lru_cache(maxsize=None)
def _cached_build(seed, offset):
    """Partagé entre les tests seeds 1-50 x offsets 12/20 (évite de regénérer
    le même squelette plusieurs fois pour des invariants indépendants)."""
    return build_skeleton(seed, offset=offset)


def _recompute_combined(result):
    """Reconstruit le contour COMBINÉ (front + back, un seul passage) et les
    indices de coupure, à partir de ``result`` seul (pas d'accès à l'état
    interne de ``_build_tree`` : seulement ``skeleton``/``config``, exposés
    publiquement sur ``SkeletonResult``). Fonction pure, même résultat que
    celui produit par ``_build_tree`` pour ce tirage (mêmes arguments).
    """
    skeleton = result.skeleton
    config = result.config
    nodes, mid_index = sk._combined_tour(
        skeleton.tree, result.clubhouse, skeleton.front_root, skeleton.back_root, config,
    )
    combined, source_index = sk.build_contour(config, nodes, return_source_index=True)
    return combined, source_index, mid_index


def _cut_boundaries(source_index, mid_index):
    """Les deux groupes de points partagés (un par passage au clubhouse) :

    ``(end0, start_mid, end_mid)`` tels que ``combined[0:end0]`` est le
    premier groupe (sommet d'index 0) et ``combined[start_mid:end_mid]`` le
    second (sommet d'index ``mid_index``). Voir ``_split_combined_contour``.
    """
    end0 = next(k for k, v in enumerate(source_index) if v != 0)
    start_mid = next(k for k, v in enumerate(source_index) if v == mid_index)
    end_mid = next((k for k in range(start_mid, len(source_index)) if source_index[k] != mid_index),
                   len(source_index))
    return end0, start_mid, end_mid


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
    """Le tour brut (nœuds) de chaque sous-arbre part du clubhouse et y revient ;

    le contour COMBINÉ décalé (``_combined_tour`` + ``build_contour``, un
    seul passage) est fermé et simple. Vérifié ici sur les seeds 1 à 20.

    Round précédent (bug, corrigé) : le contour n'était jamais refermé au
    clubhouse (fente visible dans le SVG). Round d'avant celui-ci (bug,
    corrigé) : front_contour et back_contour étaient décalés et vérifiés
    INDÉPENDAMMENT (chacun individuellement simple), ce qui ne détectait pas
    qu'ils se recoupaient l'un l'autre près du clubhouse (100/100 tirages) —
    remplacé par une vérification du contour combiné unique. NE PAS tester
    ``front_contour + back_contour`` avec ``is_simple_polyline`` : les deux
    arcs partagent leurs deux groupes de points de coupure (voir
    ``test_arcs_reconstruct_the_combined_contour``), donc leur simple
    concaténation contient des segments dupliqués que
    ``is_simple_polyline`` signale à tort comme un croisement.
    """
    result = build_skeleton(seed)
    skeleton = result.skeleton
    front_tour = sk._full_tour(skeleton.front_root, skeleton.tree, result.clubhouse, result.config)
    back_tour = sk._full_tour(skeleton.back_root, skeleton.tree, result.clubhouse, result.config)
    assert front_tour[0] == result.clubhouse and front_tour[-1] == result.clubhouse
    assert back_tour[0] == result.clubhouse and back_tour[-1] == result.clubhouse
    combined, _, _ = _recompute_combined(result)
    assert is_simple_polyline(combined)


def _all_tree_edges_world(tree, config):
    """Toutes les arêtes de l'arbre (les deux sous-arbres), en coordonnées monde."""
    return [
        (sk.node_to_world(config, a), sk.node_to_world(config, b))
        for a, b in tree.edges
    ]


@pytest.mark.parametrize("seed", SEEDS_20)
@pytest.mark.parametrize("offset", OFFSETS)
def test_contour_stays_at_offset_distance_from_its_tree_everywhere(seed, offset):
    """Invariant géométrique remplaçant l'ancien test de convexité locale de cap.

    Un décalage de polyligne standard (jointure ronde convexe, intersection
    concave vérifiée dans les deux segments) place CHAQUE point du contour à
    une distance EXACTE de ``offset`` de l'arbre ENTIER (les deux
    sous-arbres : depuis le tour combiné, un point près du clubhouse peut
    être à distance ``offset`` de l'arête de l'AUTRE sous-arbre, voir
    ``_combined_tour_with_owners``) : les jointures rondes sont des arcs de
    rayon ``offset`` centrés sur un sommet de l'arbre, et les intersections
    concaves ne sont acceptées (sinon ``ContourOffsetError``) que si elles
    tombent dans les deux segments décalés, c'est-à-dire dans la zone de
    projection perpendiculaire valide des deux arêtes réelles adjacentes
    (donc aussi à distance ``offset`` exacte). Pas de pointe (distance >
    offset + tolérance) ni de morsure (distance < offset - tolérance) nulle
    part sur le contour. Remplace l'ancien test ad hoc sur la forme du cap
    d'une feuille (6a61a3d), qui masquait le même symptôme (pointes, caps
    mordus) sans vérifier directement la distance à l'arbre.
    """
    result = _cached_build(seed, offset)
    config = result.config
    tolerance = 1e-6
    edges = _all_tree_edges_world(result.skeleton.tree, config)
    for contour in (result.front_contour, result.back_contour):
        for point in contour:
            distance = min(sk._point_to_segment_distance(point, a, b) for a, b in edges)
            assert offset - tolerance <= distance <= offset + tolerance, (
                seed, offset, point, distance,
            )


@pytest.mark.parametrize("seed", SEEDS_50)
@pytest.mark.parametrize("offset", OFFSETS)
def test_tree_has_no_duplicate_or_cross_subtree_node(seed, offset):
    """(a) L'arbre est un arbre : pas de nœud dupliqué, pas de nœud partagé

    entre les deux sous-arbres (hormis le clubhouse, qui n'appartient à
    aucun des deux au sens de ``_subtree_nodes``, lequel part de la racine
    du sous-arbre, pas du clubhouse). Seeds 1-50 x offsets 12/20, demandé
    après la régression du cap qui se recoupait près du clubhouse (pour
    écarter l'hypothèse d'un nœud partagé entre sous-arbres).
    """
    result = _cached_build(seed, offset)
    tree = result.skeleton.tree
    front_nodes = set(sk._subtree_nodes(tree, result.skeleton.front_root))
    back_nodes = set(sk._subtree_nodes(tree, result.skeleton.back_root))
    assert len(front_nodes) == len(sk._subtree_nodes(tree, result.skeleton.front_root))
    assert len(back_nodes) == len(sk._subtree_nodes(tree, result.skeleton.back_root))
    assert not (front_nodes & back_nodes), (seed, offset, front_nodes & back_nodes)
    assert result.clubhouse not in front_nodes and result.clubhouse not in back_nodes
    assert len(tree.parent) == len(front_nodes) + len(back_nodes) + 1


@pytest.mark.parametrize("seed", SEEDS_50)
@pytest.mark.parametrize("offset", OFFSETS)
def test_no_pair_of_tree_edges_crosses(seed, offset):
    """(b) Aucune paire d'arêtes de l'arbre (même entre les deux sous-arbres)

    ne se croise, hormis les paires qui partagent un nœud (adjacentes dans
    l'arbre, exemptées du halo par construction). Seeds 1-50 x offsets
    12/20.
    """
    result = _cached_build(seed, offset)
    tree = result.skeleton.tree
    config = result.config
    edges = tree.edges
    world = [(sk.node_to_world(config, a), sk.node_to_world(config, b)) for a, b in edges]
    for i in range(len(edges)):
        a, b = edges[i]
        for j in range(i + 1, len(edges)):
            c, d = edges[j]
            if a in (c, d) or b in (c, d):
                continue  # arêtes réellement adjacentes dans l'arbre (nœud partagé)
            assert not segments_intersect(*world[i], *world[j]), (seed, offset, edges[i], edges[j])


@pytest.mark.parametrize("seed", SEEDS_50)
@pytest.mark.parametrize("offset", OFFSETS)
def test_combined_contour_is_simple(seed, offset):
    """(c), 1/2 : le contour COMPLET (combiné, un seul passage par

    ``build_contour``) est fermé et simple — garantit à la fois qu'aucun des
    deux arcs ne se recoupe lui-même ET qu'ils ne se recoupent pas l'un
    l'autre (sauf à leurs deux groupes de points de coupure communs, qui ne
    comptent pas comme un croisement : ce sont les mêmes points, pas deux
    segments distincts qui se recoupent). Seeds 1-50 x offsets 12/20.
    """
    result = _cached_build(seed, offset)
    combined, _, _ = _recompute_combined(result)
    assert is_simple_polyline(combined)


@pytest.mark.parametrize("seed", SEEDS_50)
@pytest.mark.parametrize("offset", OFFSETS)
def test_front_and_back_only_meet_at_shared_cut_points(seed, offset):
    """(c), 2/2 : en dehors de leurs deux groupes de points de coupure

    COMMUNS (partagés tels quels par les deux arcs, voir
    ``_split_combined_contour``), front_contour et back_contour ne se
    touchent ni ne se croisent nulle part. Reproduit directement la
    régression rapportée : seed 6, offset 20 montrait un croisement en X
    entre une diagonale front (bleu) et une diagonale back (jaune) près du
    clubhouse — les deux contours étaient chacun individuellement simples,
    ce test-ci ne l'était pas. Seeds 1-50 x offsets 12/20 : la régression
    était systématique (100/100 avant correction), pas un cas isolé.
    """
    result = _cached_build(seed, offset)
    combined, source_index, mid_index = _recompute_combined(result)
    end0, start_mid, end_mid = _cut_boundaries(source_index, mid_index)
    front = combined[0:end_mid]
    back = combined[start_mid:] + combined[0:end0]
    # Portions STRICTEMENT internes à chaque sous-arbre (hors des deux
    # groupes de coupure partagés, inclus aux deux extrémités de chaque arc).
    front_pure = front[end0:start_mid]
    back_pure = back[(end_mid - start_mid):(len(combined) - start_mid)]
    for i in range(len(front_pure) - 1):
        for j in range(len(back_pure) - 1):
            assert not segments_intersect(
                front_pure[i], front_pure[i + 1], back_pure[j], back_pure[j + 1],
            ), (seed, offset, front_pure[i], front_pure[i + 1], back_pure[j], back_pure[j + 1])


@pytest.mark.parametrize("seed", SEEDS_50)
@pytest.mark.parametrize("offset", OFFSETS)
def test_arcs_reconstruct_the_combined_contour(seed, offset):
    """front ∪ back = contour complet : la somme des longueurs des deux arcs

    OUVERTS (``front_contour``, ``back_contour``) égale la longueur du
    contour combiné FERMÉ, plus deux fois la longueur de chacun des deux
    groupes de points de coupure (chaque groupe est parcouru une fois par
    CHAQUE arc, voir ``_split_combined_contour``). Seeds 1-50 x offsets
    12/20.
    """
    result = _cached_build(seed, offset)
    combined, source_index, mid_index = _recompute_combined(result)
    end0, start_mid, end_mid = _cut_boundaries(source_index, mid_index)
    front_len = sk._polyline_length(list(result.front_contour))
    back_len = sk._polyline_length(list(result.back_contour))
    combined_closed_len = sk._polyline_length(combined) + math.dist(combined[-1], combined[0])
    cluster0_len = sk._polyline_length(combined[0:end0])
    cluster_mid_len = sk._polyline_length(combined[start_mid:end_mid])
    assert abs((front_len + back_len)
               - (combined_closed_len + cluster0_len + cluster_mid_len)) < 1e-6, (seed, offset)


@pytest.mark.parametrize("seed", SEEDS_50)
@pytest.mark.parametrize("offset", OFFSETS)
def test_arc_endpoints_stay_near_the_clubhouse(seed, offset):
    """Les deux extrémités de chaque arc sont à distance <= offset*sqrt(2) + eps

    du clubhouse : reproduit directement la régression rapportée (bouts
    pendants loin du clubhouse, ex. seed 1 offset 20 à ~48 blocs au lieu de
    ~20-28). sqrt(2) couvre le pire cas d'une jointure à 90° exacte (grille à
    8 voisins). Seeds 1-50 x offsets 12/20.
    """
    result = _cached_build(seed, offset)
    clubhouse_world = sk.node_to_world(result.config, result.clubhouse)
    bound = offset * math.sqrt(2.0) + 1e-6
    for contour in (result.front_contour, result.back_contour):
        for point in (contour[0], contour[-1]):
            distance = math.dist(point, clubhouse_world)
            assert distance <= bound, (seed, offset, point, distance, bound)


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
