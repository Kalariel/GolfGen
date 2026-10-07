"""Étape 3 — squelette global grossier : contour d'un arbre aléatoire.

Round correctif du 2026-10-07 (Porte 3 refusée à l'inspection visuelle du
premier essai : le méandre en boustrophédon produisait deux serpentins en S
qui se font face autour du clubhouse, la moitié de la carte vide — voir
PLAN.md). Ce round ne couvre QUE la génération de l'arbre, son contour et la
coupure aux deux passages au clubhouse (pas de DP de découpage ni de
``CourseLayout`` ici ; ces briques, déjà validées, restent plus bas dans ce
fichier mais ne sont plus appelées par ``build_skeleton``).

Algorithme révisé :

1. réseau grossier de nœuds, pas ``NODE_PITCH`` (>= halo), 8 voisins
   (orthogonaux + diagonaux) ;
2. clubhouse = un nœud du réseau tiré par la seed (pas fixé au centre) ;
   racine de l'arbre, exactement deux sous-arbres (front, back) ;
3. croissance ALTERNÉE (une arête front, une arête back, ...) par marche
   aléatoire biaisée « voyage » (s'éloigner du clubhouse, puis y revenir),
   budget de longueur par sous-arbre dérivé de ``PAR_SPECS``, au plus trois
   feuilles par sous-arbre, branche menant à une feuille d'au moins
   ``MIN_LEAF_BRANCH_LENGTH`` blocs ;
4. halo GÉNÉRAL : toute paire d'arêtes de l'arbre sans nœud commun doit
   être à distance segment-segment >= ``HALO_MIN_DIST`` (remplace la
   fenêtre « localement reliée » du premier essai, qui ne couvrait pas
   toutes les géométries) ;
5. rejet complet et borné (``MAX_TREE_ATTEMPTS`` tirages dérivés de la
   seed, zéro boucle non bornée) si un budget ne peut être atteint ;
6. contour = tour (à la manière d'un tour d'Euler) de l'arbre, ligne
   centrale lissée en congés d'arc (pas <= 22°) puis décalée par
   intersection des bords (onglet) ; cap en demi-cercle aux feuilles. La
   coupure aux deux passages au clubhouse est déjà le résultat : front et
   back sont deux arcs clubhouse -> clubhouse indépendants.

Pas de dépendance à ``shapely``. Toutes les longueurs sont en blocs.
"""

from __future__ import annotations

import math
import random
import time
from bisect import bisect_left, bisect_right
from dataclasses import dataclass, field

from experiments.elastic_routing.geometry import segment_distance, segments_intersect
from experiments.elastic_routing.model import (
    PAR_SPECS,
    ControlPoint,
    ElasticHole,
    NineLayout,
)


Point = tuple[float, float]
Node = tuple[int, int]


# ----------------------------------------------------------------------
# Constantes
# ----------------------------------------------------------------------

# Réseau grossier : 8x8 nœuds à pas 48 (>= halo 47), premier/dernier nœud à
# 24/360 sur une carte de 400. Marge requise jusqu'au bord : offset du
# contour (12) + demi-largeur de fairway max (par 5, 18/2 = 9) = 21 ; marge
# réelle 24 (et 400-360=40) >= 21, donc le contour + la plus grosse moitié
# de fairway restent toujours en carte.
MAP_SIZE = 400.0
NODE_PITCH = 48.0
NODE_COUNT = 8
NODE_OFFSET = 24.0

RIBBON_OFFSET = 12.0
HALO_MARGIN = 23.0
HALO_MIN_DIST = 2.0 * RIBBON_OFFSET + HALO_MARGIN  # 47.0 blocs

# ~6 arêtes orthogonales (6*48=288, arrondi à 300 pour rester cohérent avec
# le budget de longueur, lui aussi en blocs et non en nombre d'arêtes).
MIN_LEAF_BRANCH_LENGTH = 300.0
MAX_LEAVES_PER_SUBTREE = 3
MAX_ARC_STEP_DEG = 22.0

# Rendement mesuré après le passage au réseau grossier (pas 48) et au halo
# général (distance segment-segment, exemption uniquement sur nœud commun) :
# nettement meilleur qu'au pas 5 (voir historique plus bas). Reste borné et
# petit comme demandé ; ``build_skeleton`` consigne le taux de rejet réel.
MAX_TREE_ATTEMPTS = 50

NEIGHBOR_DELTAS: tuple[Node, ...] = (
    (-1, -1), (-1, 0), (-1, 1), (0, -1), (0, 1), (1, -1), (1, 0), (1, 1),
)

NINE_PAR_PATTERN = (3, 4, 4, 4, 4, 5, 5, 4, 3)  # 2 par3, 2 par5, 5 par4 (comme synthetic.py)

# Liaisons de construction (DP de découpage, non utilisée par ce round) :
# conservées ici pour que _subtree_length_range reste identique à l'étape 3
# initiale (même calcul, mêmes bornes), sans dépendre d'une DP appelée.
LINK_CONSTRUCTION_MIN = 12.0
LINK_CONSTRUCTION_MAX = 60.0


def _subtree_length_range() -> tuple[float, float]:
    """Plage de longueur d'arbre par sous-arbre, dérivée de ``PAR_SPECS``.

    Un nine = 9 trous + 10 liaisons de construction. Borne basse : pars les
    plus courts (2 par3, 5 par4, 2 par5 comme ``NINE_PAR_PATTERN``) + 10
    liaisons au minimum de construction. Borne haute : symetrique au
    maximum. L'arbre (avant offset) vise environ la moitie du contour
    (aller + retour), caps negliges.
    """
    low = sum(PAR_SPECS[par].length_min for par in NINE_PAR_PATTERN) + 10 * LINK_CONSTRUCTION_MIN
    high = sum(PAR_SPECS[par].length_max for par in NINE_PAR_PATTERN) + 10 * LINK_CONSTRUCTION_MAX
    return (low / 2.0, high / 2.0)


SUBTREE_LENGTH_RANGE = _subtree_length_range()


class SkeletonGenerationError(RuntimeError):
    """Levee quand aucun arbre valide n'a ete trouve en MAX_TREE_ATTEMPTS tirages."""


# ----------------------------------------------------------------------
# Réseau de nœuds
# ----------------------------------------------------------------------

def node_to_world(node: Node) -> Point:
    return (NODE_OFFSET + node[0] * NODE_PITCH, NODE_OFFSET + node[1] * NODE_PITCH)


def _in_grid(node: Node) -> bool:
    return 0 <= node[0] < NODE_COUNT and 0 <= node[1] < NODE_COUNT


def _edge_length(delta: Node) -> float:
    return NODE_PITCH * math.hypot(delta[0], delta[1])


def _wrap_pi(angle: float) -> float:
    return (angle + math.pi) % (2.0 * math.pi) - math.pi


def all_nodes() -> list[Node]:
    return [(x, y) for x in range(NODE_COUNT) for y in range(NODE_COUNT)]


# ----------------------------------------------------------------------
# État global de l'arbre (un seul arbre, deux sous-arbres sous le clubhouse)
# ----------------------------------------------------------------------

@dataclass
class TreeState:
    parent: dict[Node, Node | None] = field(default_factory=dict)
    arclen: dict[Node, float] = field(default_factory=dict)
    children: dict[Node, list[Node]] = field(default_factory=dict)
    edges: list[tuple[Node, Node]] = field(default_factory=list)

    def add_root(self, root: Node) -> None:
        self.parent[root] = None
        self.arclen[root] = 0.0
        self.children.setdefault(root, [])

    def add(self, node: Node, parent_node: Node) -> None:
        edge = _edge_length((node[0] - parent_node[0], node[1] - parent_node[1]))
        self.parent[node] = parent_node
        self.arclen[node] = self.arclen[parent_node] + edge
        self.children.setdefault(parent_node, []).append(node)
        self.children.setdefault(node, [])
        self.edges.append((parent_node, node))


def _halo_ok(u: Node, v: Node, tree: TreeState) -> bool:
    """Halo général : toute arête existante sans nœud commun avec (u, v)

    doit être à distance segment-segment >= ``HALO_MIN_DIST``. Couvre à la
    fois les diagonales qui frôlent un nœud voisin et les diagonales qui se
    croisent, sans fenêtre « localement reliée » distincte (remplace
    l'approche du premier essai de l'étape 3, qui se limitait aux parties
    non reliées le long de l'arbre et ne suffisait pas en général).
    """
    world_u, world_v = node_to_world(u), node_to_world(v)
    for a, b in tree.edges:
        if a == u or a == v or b == u or b == v:
            continue
        if segment_distance(world_u, world_v, node_to_world(a), node_to_world(b)) < HALO_MIN_DIST:
            return False
    return True


# ----------------------------------------------------------------------
# Croissance : marche aléatoire biaisée « voyage » sur le réseau de nœuds
# ----------------------------------------------------------------------

def _walk_steps(rng: random.Random, tree: TreeState, occupied: set[Node], start_node: Node,
                target_length: float, fallback_angle: float, clubhouse_world: Point):
    """Générateur : fait croître l'arbre depuis ``start_node``, une arête à la fois.

    Biais « voyage » : score = alignement avec le vecteur clubhouse->nœud
    courant (s'éloigne) tant que < 60% du budget, puis avec le vecteur
    nœud courant->clubhouse (revient) au-delà. Au tout premier pas, ce
    vecteur est nul (le nœud courant EST le clubhouse pour le tronc) :
    ``fallback_angle`` (différent pour front et back, seedé) lève
    l'ambiguïté et assure l'asymétrie entre les deux sous-arbres.

    Tronque (s'arrête, sans retour arrière) dès qu'aucun nœud voisin n'est
    libre et conforme au halo — jamais d'exception ici, l'appelant décide
    si la longueur obtenue est suffisante.
    """
    current = start_node
    grown = 0.0
    last_delta: Node | None = None
    yield grown, [current]
    while grown < target_length:
        current_world = node_to_world(current)
        ref_vec = (current_world[0] - clubhouse_world[0], current_world[1] - clubhouse_world[1])
        if grown >= 0.6 * target_length:
            ref_vec = (-ref_vec[0], -ref_vec[1])
        ref_norm = math.hypot(*ref_vec)
        ref_unit = (ref_vec[0] / ref_norm, ref_vec[1] / ref_norm) if ref_norm > 1e-9 else (
            math.cos(fallback_angle), math.sin(fallback_angle)
        )

        candidates = []
        for delta in NEIGHBOR_DELTAS:
            if last_delta is not None and delta == (-last_delta[0], -last_delta[1]):
                continue  # jamais de retour arriere strict sur le pas precedent
            candidate = (current[0] + delta[0], current[1] + delta[1])
            if not _in_grid(candidate) or candidate in occupied:
                continue
            if not _halo_ok(current, candidate, tree):
                continue
            edge_len = _edge_length(delta)
            candidate_world = node_to_world(candidate)
            direction = ((candidate_world[0] - current_world[0]) / edge_len,
                        (candidate_world[1] - current_world[1]) / edge_len)
            score = direction[0] * ref_unit[0] + direction[1] * ref_unit[1]
            candidates.append((score, candidate, edge_len, delta))

        if not candidates:
            return  # troncature : pas de retour arriere, on garde l'acquis

        candidates.sort(key=lambda item: -item[0])
        if len(candidates) > 1 and rng.random() < 0.4:
            _, chosen, edge_len, delta = candidates[rng.randrange(1, len(candidates))]
        else:
            _, chosen, edge_len, delta = candidates[0]

        tree.add(chosen, current)
        occupied.add(chosen)
        grown += edge_len
        current = chosen
        last_delta = delta
        yield grown, _path_from(tree, start_node, current)


def _path_from(tree: TreeState, start: Node, end: Node) -> list[Node]:
    path = [end]
    cur = end
    while cur != start:
        cur = tree.parent[cur]
        path.append(cur)
    path.reverse()
    return path


def _grow_alternating(rng: random.Random, tree: TreeState, occupied: set[Node],
                      front_start: Node, back_start: Node, front_target: float,
                      back_target: float, front_angle: float, back_angle: float,
                      clubhouse_world: Point) -> tuple[tuple[float, list[Node]], tuple[float, list[Node]]]:
    """Fait croître les deux troncs en alternance, une arête à la fois.

    Les deux sous-arbres partagent le même état (``tree``, ``occupied``) :
    chaque arête ajoutée par l'un est immédiatement visible du halo de
    l'autre, ce qui évite qu'un sous-arbre occupe toute la carte avant que
    l'autre ne commence (défaut du premier essai, rejeté à la Porte 3).
    """
    gen_front = _walk_steps(rng, tree, occupied, front_start, front_target, front_angle, clubhouse_world)
    gen_back = _walk_steps(rng, tree, occupied, back_start, back_target, back_angle, clubhouse_world)
    front_state = next(gen_front)
    back_state = next(gen_back)
    front_done = back_done = False
    while not (front_done and back_done):
        if not front_done:
            try:
                front_state = next(gen_front)
            except StopIteration:
                front_done = True
        if not back_done:
            try:
                back_state = next(gen_back)
            except StopIteration:
                back_done = True
    return front_state, back_state


# ----------------------------------------------------------------------
# Construction d'un sous-arbre complet (tronc + branches eventuelles)
# ----------------------------------------------------------------------

def _choose_leaf_plan(rng: random.Random, target_length: float) -> tuple[int, float, list[float]]:
    max_leaves = 1
    if target_length >= 2 * MIN_LEAF_BRANCH_LENGTH + 150.0:
        max_leaves = 2
    if target_length >= 3 * MIN_LEAF_BRANCH_LENGTH + 200.0:
        max_leaves = 3
    num_leaves = rng.randint(1, max_leaves)
    num_branches = num_leaves - 1
    if num_branches == 0:
        return 1, target_length, []
    branch_targets = [MIN_LEAF_BRANCH_LENGTH + rng.uniform(0.0, 60.0) for _ in range(num_branches)]
    trunk_target = target_length - sum(branch_targets)
    if trunk_target < MIN_LEAF_BRANCH_LENGTH:
        trunk_target = MIN_LEAF_BRANCH_LENGTH
        branch_targets = [MIN_LEAF_BRANCH_LENGTH] * num_branches
    return num_leaves, trunk_target, branch_targets


class _SubtreeStuck(RuntimeError):
    """Signal interne : ce tirage de sous-arbre echoue, on retire l'arbre entier."""


def _pick_branch_point(rng: random.Random, tree: TreeState, trunk_nodes: list[Node],
                       branch_target: float) -> Node | None:
    trunk_total = tree.arclen[trunk_nodes[-1]] - tree.arclen[trunk_nodes[0]]
    candidates = [
        node for node in trunk_nodes
        if NODE_PITCH <= tree.arclen[node] - tree.arclen[trunk_nodes[0]] <= trunk_total - MIN_LEAF_BRANCH_LENGTH
    ]
    if not candidates:
        return None
    return rng.choice(candidates)


def _grow_branch(rng: random.Random, tree: TreeState, occupied: set[Node], start_node: Node,
                 branch_target: float, fan_angle: float, clubhouse_world: Point) -> tuple[float, list[Node]]:
    grown, path = 0.0, [start_node]
    for grown, path in _walk_steps(rng, tree, occupied, start_node, branch_target, fan_angle, clubhouse_world):
        pass
    return grown, path


# ----------------------------------------------------------------------
# Arbre complet (deux sous-arbres), avec rejet borné
# ----------------------------------------------------------------------

@dataclass(frozen=True)
class Skeleton:
    clubhouse: Node
    tree: TreeState
    front_root: Node
    back_root: Node
    front_leaves: tuple[Node, ...]
    back_leaves: tuple[Node, ...]
    front_length: float
    back_length: float


def _subtree_total_length(tree: TreeState, root: Node) -> float:
    total = 0.0
    stack = [root]
    while stack:
        node = stack.pop()
        for child in tree.children.get(node, ()):
            total += tree.arclen[child] - tree.arclen[node]
            stack.append(child)
    return total


@dataclass(frozen=True)
class _BuildOutcome:
    skeleton: Skeleton
    front_contour: list[Point]
    back_contour: list[Point]


def _build_tree(seed: int) -> tuple[_BuildOutcome, int]:
    """Boucle de rejet bornée (``MAX_TREE_ATTEMPTS``).

    Un tirage n'est accepté que si les deux sous-arbres atteignent leur
    budget minimal, ont au plus 3 feuilles chacun ET leurs deux contours
    sont simples — un échec à n'importe laquelle de ces étapes retire le
    tirage entier (pas de retour arrière interne). Retourne le résultat et
    le nombre de tentatives consommées (pour rapporter le taux de rejet).
    """
    for attempt in range(MAX_TREE_ATTEMPTS):
        rng = random.Random(f"elastic_routing_skeleton:{seed}:{attempt}")
        clubhouse = rng.choice(all_nodes())
        clubhouse_world = node_to_world(clubhouse)
        tree = TreeState()
        tree.add_root(clubhouse)
        occupied = {clubhouse}

        front_angle = rng.uniform(0.0, 2.0 * math.pi)
        back_angle = front_angle + math.pi + rng.uniform(-0.6, 0.6)
        front_target_total = rng.uniform(*SUBTREE_LENGTH_RANGE)
        back_target_total = rng.uniform(*SUBTREE_LENGTH_RANGE)
        front_leaves_n, front_trunk_target, front_branch_targets = _choose_leaf_plan(rng, front_target_total)
        back_leaves_n, back_trunk_target, back_branch_targets = _choose_leaf_plan(rng, back_target_total)

        (front_grown, front_trunk_path), (back_grown, back_trunk_path) = _grow_alternating(
            rng, tree, occupied, clubhouse, clubhouse, front_trunk_target, back_trunk_target,
            front_angle, back_angle, clubhouse_world,
        )
        roots = tree.children[clubhouse]
        if len(roots) != 2:
            continue  # l'un des deux troncs n'a pas pu planter sa toute premiere arete
        front_root, back_root = roots
        if front_trunk_path[-1] == clubhouse or back_trunk_path[-1] == clubhouse:
            continue

        try:
            if front_grown < MIN_LEAF_BRANCH_LENGTH or back_grown < MIN_LEAF_BRANCH_LENGTH:
                raise _SubtreeStuck("tronc trop court")
            front_leaves = [front_trunk_path[-1]]
            for branch_target in front_branch_targets:
                branch_point = _pick_branch_point(rng, tree, front_trunk_path, branch_target)
                if branch_point is None:
                    continue
                fan_angle = rng.uniform(0.0, 2.0 * math.pi)
                branch_grown, branch_path = _grow_branch(rng, tree, occupied, branch_point,
                                                         branch_target, fan_angle, clubhouse_world)
                if branch_grown < MIN_LEAF_BRANCH_LENGTH:
                    raise _SubtreeStuck("branche front trop courte")
                front_leaves.append(branch_path[-1])
            if len(front_leaves) > MAX_LEAVES_PER_SUBTREE:
                raise _SubtreeStuck("trop de feuilles front")

            back_leaves = [back_trunk_path[-1]]
            for branch_target in back_branch_targets:
                branch_point = _pick_branch_point(rng, tree, back_trunk_path, branch_target)
                if branch_point is None:
                    continue
                fan_angle = rng.uniform(0.0, 2.0 * math.pi)
                branch_grown, branch_path = _grow_branch(rng, tree, occupied, branch_point,
                                                         branch_target, fan_angle, clubhouse_world)
                if branch_grown < MIN_LEAF_BRANCH_LENGTH:
                    raise _SubtreeStuck("branche back trop courte")
                back_leaves.append(branch_path[-1])
            if len(back_leaves) > MAX_LEAVES_PER_SUBTREE:
                raise _SubtreeStuck("trop de feuilles back")
        except _SubtreeStuck:
            continue

        front_contour = build_contour(_full_tour(front_root, tree, clubhouse))
        back_contour = build_contour(_full_tour(back_root, tree, clubhouse))
        if not is_simple_polyline(front_contour) or not is_simple_polyline(back_contour):
            continue

        # arclen[root] = longueur clubhouse->root (premiere arete du sous-arbre) :
        # a additionner pour que front_length/back_length mesurent bien la
        # longueur totale depuis le clubhouse (coherent avec MIN_LEAF_BRANCH_LENGTH,
        # verifie plus haut sur front_grown/back_grown, qui incluent cette arete).
        front_total = tree.arclen[front_root] + _subtree_total_length(tree, front_root)
        back_total = tree.arclen[back_root] + _subtree_total_length(tree, back_root)
        skeleton = Skeleton(clubhouse, tree, front_root, back_root, tuple(front_leaves),
                            tuple(back_leaves), front_total, back_total)
        return _BuildOutcome(skeleton, front_contour, back_contour), attempt + 1
    raise SkeletonGenerationError(
        f"aucun arbre valide apres {MAX_TREE_ATTEMPTS} tirages derives (seed={seed})"
    )


# ----------------------------------------------------------------------
# Tour (à la manière d'un tour d'Euler) et contour décalé — inchangé
# ----------------------------------------------------------------------

def _angle_between(a: Point, b: Point) -> float:
    return math.atan2(b[1] - a[1], b[0] - a[0])


def _tour_nodes(node: Node, parent: Node | None, tree: TreeState) -> list[Node]:
    kids = [c for c in tree.children.get(node, ()) if c != parent]
    if not kids:
        return [node]
    node_world = node_to_world(node)
    if parent is not None:
        ref = _angle_between(node_world, node_to_world(parent))
    else:
        ref = 0.0
    kids_sorted = sorted(
        kids,
        key=lambda k: (_angle_between(node_world, node_to_world(k)) - ref) % (2.0 * math.pi),
    )
    sequence = [node]
    for kid in kids_sorted:
        sequence.append(kid)
        sub = _tour_nodes(kid, node, tree)
        sequence.extend(sub[1:])
        sequence.append(node)
    return sequence


def _full_tour(root_child: Node, tree: TreeState, clubhouse: Node) -> list[Node]:
    """Tour clubhouse -> ... -> clubhouse pour le sous-arbre débutant à ``root_child``."""
    return [clubhouse] + _tour_nodes(root_child, clubhouse, tree) + [clubhouse]


def _point_to_segment_distance(point: Point, a: Point, b: Point) -> float:
    dx, dy = b[0] - a[0], b[1] - a[1]
    length_sq = dx * dx + dy * dy
    if length_sq <= 1e-12:
        return math.dist(point, a)
    ratio = max(0.0, min(1.0, ((point[0] - a[0]) * dx + (point[1] - a[1]) * dy) / length_sq))
    return math.dist(point, (a[0] + ratio * dx, a[1] + ratio * dy))


def _simplify_tour_points(points: list[Point], epsilon: float = 6.0) -> list[Point]:
    """Douglas-Peucker itératif : fusionne les points quasi colinéaires.

    Implémentation itérative (pas de récursion).
    """
    n = len(points)
    if n < 3:
        return list(points)
    keep = [False] * n
    keep[0] = keep[-1] = True
    stack = [(0, n - 1)]
    while stack:
        start, end = stack.pop()
        if end <= start + 1:
            continue
        a, b = points[start], points[end]
        max_dist, split = 0.0, None
        for i in range(start + 1, end):
            d = _point_to_segment_distance(points[i], a, b)
            if d > max_dist:
                max_dist, split = d, i
        if split is not None and max_dist > epsilon:
            keep[split] = True
            stack.append((start, split))
            stack.append((split, end))
    return [point for point, kept in zip(points, keep) if kept]


CENTERLINE_FILLET_RADIUS = 2.0 * RIBBON_OFFSET
CENTERLINE_LEAF_SKIP_DEG = 150.0  # au-dela, le virage est un demi-tour (feuille), traite a part


def _round_centerline_corners(points: list[Point], radius: float = CENTERLINE_FILLET_RADIUS,
                              skip_above_deg: float = CENTERLINE_LEAF_SKIP_DEG) -> list[Point]:
    """Remplace chaque virage marqué par un congé en arc (porté de loop_router._round_corners).

    Lisser la LIGNE CENTRALE d'abord (rayon >= au décalage du ruban) rend
    ensuite le décalage par onglet/arc centré sûr : aucun virage résiduel
    ne dépasse ``MAX_ARC_STEP_DEG``. Les quasi demi-tours (feuilles) sont
    volontairement non modifiés ici : la formule en tangente diverge à
    180°, et ``build_contour`` leur applique directement l'arc centré exact
    (cap en demi-cercle).
    """
    result = [points[0]]
    for i in range(1, len(points) - 1):
        prev, here, nxt = points[i - 1], points[i], points[i + 1]
        d1, d2 = math.dist(prev, here), math.dist(here, nxt)
        if d1 < 1e-9 or d2 < 1e-9:
            continue
        v1 = ((here[0] - prev[0]) / d1, (here[1] - prev[1]) / d1)
        v2 = ((nxt[0] - here[0]) / d2, (nxt[1] - here[1]) / d2)
        turn = math.atan2(v1[0] * v2[1] - v1[1] * v2[0], v1[0] * v2[0] + v1[1] * v2[1])
        turn_deg = math.degrees(turn)
        if abs(turn_deg) < 25.0 or abs(turn_deg) >= skip_above_deg:
            result.append(here)
            continue
        half_tan = math.tan(abs(turn) / 2.0)
        tangent = min(radius * half_tan, 0.42 * d1, 0.42 * d2)
        r_eff = tangent / half_tan
        p_in = (here[0] - v1[0] * tangent, here[1] - v1[1] * tangent)
        side = 1.0 if turn > 0 else -1.0
        center = (p_in[0] - v1[1] * r_eff * side, p_in[1] + v1[0] * r_eff * side)
        phi = math.atan2(p_in[1] - center[1], p_in[0] - center[0])
        n_sub = max(2, int(math.ceil(abs(turn_deg) / MAX_ARC_STEP_DEG)))
        for j in range(n_sub + 1):
            angle = phi + turn * j / n_sub
            result.append((center[0] + r_eff * math.cos(angle), center[1] + r_eff * math.sin(angle)))
    result.append(points[-1])
    return result


def build_contour(tour_nodes: list[Node], radius: float = RIBBON_OFFSET) -> list[Point]:
    """Décale le tour d'un côté courant (la main gauche du sens de marche).

    Après le lissage de la ligne centrale (``_round_centerline_corners``,
    qui porte le « congé en arc »), le décalage proprement dit utilise
    l'intersection des deux bords décalés à chaque sommet (onglet, porté de
    ``golfgen.loop_router._offset_polyline``), sauf au cap (demi-tour en
    feuille) qui reçoit un arc centré exact sur le sommet.
    """
    points = _round_centerline_corners(_simplify_tour_points([node_to_world(n) for n in tour_nodes]))
    n = len(points)
    if n < 2:
        return []
    normals = []
    for a, b in zip(points, points[1:]):
        d = (b[0] - a[0], b[1] - a[1])
        norm = math.hypot(*d)
        normals.append((-d[1] / norm, d[0] / norm))

    contour: list[Point] = [
        (points[0][0] + radius * normals[0][0], points[0][1] + radius * normals[0][1]),
    ]
    for i in range(1, n - 1):
        prev, here, nxt = points[i - 1], points[i], points[i + 1]
        n_prev, n_next = normals[i - 1], normals[i]
        if abs(n_next[0] - n_prev[0]) < 1e-9 and abs(n_next[1] - n_prev[1]) < 1e-9:
            contour.append((here[0] + radius * n_next[0], here[1] + radius * n_next[1]))
            continue
        turn = _wrap_pi(math.atan2(n_next[1], n_next[0]) - math.atan2(n_prev[1], n_prev[0]))
        if abs(math.degrees(turn)) >= CENTERLINE_LEAF_SKIP_DEG:
            # Demi-tour (feuille) : cap en demi-cercle centré sur le sommet,
            # seul cas où l'onglet (tangente) diverge.
            contour.append((here[0] + radius * n_prev[0], here[1] + radius * n_prev[1]))
            contour.extend(_corner_arc(here, n_prev, n_next, radius))
            continue
        d_prev = (here[0] - prev[0], here[1] - prev[1])
        d_next = (nxt[0] - here[0], nxt[1] - here[1])
        a1 = (prev[0] + radius * n_prev[0], prev[1] + radius * n_prev[1])
        a2 = (here[0] + radius * n_next[0], here[1] + radius * n_next[1])
        cross = d_prev[0] * d_next[1] - d_prev[1] * d_next[0]
        if abs(cross) < 1e-9:
            contour.append(a2)
            continue
        t = ((a2[0] - a1[0]) * d_next[1] - (a2[1] - a1[1]) * d_next[0]) / cross
        contour.append((a1[0] + d_prev[0] * t, a1[1] + d_prev[1] * t))
    contour.append((points[-1][0] + radius * normals[-1][0], points[-1][1] + radius * normals[-1][1]))
    return contour


def _corner_arc(center: Point, normal_in: Point, normal_out: Point, radius: float) -> list[Point]:
    angle_in = math.atan2(normal_in[1], normal_in[0])
    angle_out = math.atan2(normal_out[1], normal_out[0])
    turn = _wrap_pi(angle_out - angle_in)
    if abs(turn) < 1e-9:
        return []
    steps = max(1, int(math.ceil(abs(math.degrees(turn)) / MAX_ARC_STEP_DEG)))
    out = []
    for step in range(1, steps + 1):
        angle = angle_in + turn * step / steps
        out.append((center[0] + radius * math.cos(angle), center[1] + radius * math.sin(angle)))
    return out


def is_simple_polyline(points: list[Point]) -> bool:
    """Vérifie numériquement que la polyligne (ouverte) ne se croise pas elle-même."""
    segments = list(zip(points, points[1:]))
    n = len(segments)
    for i in range(n):
        for j in range(i + 2, n):
            if i == 0 and j == n - 1:
                continue  # extremites communes au depart/retour clubhouse, attendu
            if segments_intersect(*segments[i], *segments[j]):
                return False
    return True


# ----------------------------------------------------------------------
# Orchestration
# ----------------------------------------------------------------------

@dataclass(frozen=True)
class SkeletonResult:
    seed: int
    clubhouse: Node
    skeleton: Skeleton
    front_contour: tuple[Point, ...]
    back_contour: tuple[Point, ...]
    elapsed_seconds: float
    attempts_used: int


def build_skeleton(seed: int) -> SkeletonResult:
    start = time.perf_counter()
    outcome, attempts_used = _build_tree(seed)
    elapsed = time.perf_counter() - start
    return SkeletonResult(
        seed=seed,
        clubhouse=outcome.skeleton.clubhouse,
        skeleton=outcome.skeleton,
        front_contour=tuple(outcome.front_contour),
        back_contour=tuple(outcome.back_contour),
        elapsed_seconds=elapsed,
        attempts_used=attempts_used,
    )


# ----------------------------------------------------------------------
# Rendu SVG du squelette (réseau, arbre, contour, clubhouse)
# ----------------------------------------------------------------------

def _subtree_nodes(tree: TreeState, root: Node) -> list[Node]:
    nodes = [root]
    stack = [root]
    while stack:
        node = stack.pop()
        for child in tree.children.get(node, ()):
            nodes.append(child)
            stack.append(child)
    return nodes


def render_skeleton_svg(result: SkeletonResult) -> str:
    """SVG de diagnostic : réseau de nœuds, arbre par nine, contour, clubhouse."""
    skeleton = result.skeleton
    size, padding, footer = 800, 24, 60
    scale = (size - 2 * padding) / MAP_SIZE

    def point(value: Point) -> Point:
        return (padding + value[0] * scale, padding + value[1] * scale)

    out = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{size}" height="{size + footer}">',
        '<rect width="100%" height="100%" fill="#0d1117"/>',
        (f'<rect x="{padding}" y="{padding}" width="{MAP_SIZE * scale:.1f}" '
         f'height="{MAP_SIZE * scale:.1f}" fill="#161b22" stroke="#8b949e"/>'),
        '<style>text{font-family:monospace;fill:#c9d1d9}</style>',
    ]

    for node in all_nodes():
        p = point(node_to_world(node))
        out.append(f'<circle cx="{p[0]:.1f}" cy="{p[1]:.1f}" r="1.0" fill="#3b4049"/>')

    for root, color in ((skeleton.front_root, "#58a6ff"), (skeleton.back_root, "#f2cc60")):
        for node in _subtree_nodes(skeleton.tree, root):
            p = point(node_to_world(node))
            out.append(f'<circle cx="{p[0]:.1f}" cy="{p[1]:.1f}" r="2.6" fill="{color}" fill-opacity="0.85"/>')
    for a, b in skeleton.tree.edges:
        pa, pb = point(node_to_world(a)), point(node_to_world(b))
        out.append(f'<line x1="{pa[0]:.1f}" y1="{pa[1]:.1f}" x2="{pb[0]:.1f}" y2="{pb[1]:.1f}" '
                   'stroke="#8b949e" stroke-width="1.0" stroke-opacity="0.6"/>')

    for contour, color in ((result.front_contour, "#58a6ff"), (result.back_contour, "#f2cc60")):
        path = " ".join(f"{point(p)[0]:.1f},{point(p)[1]:.1f}" for p in contour)
        out.append(f'<polygon points="{path}" fill="none" stroke="{color}" stroke-width="1.4" stroke-opacity="0.9"/>')

    clubhouse = point(node_to_world(result.clubhouse))
    out.append(
        f'<circle cx="{clubhouse[0]:.1f}" cy="{clubhouse[1]:.1f}" r="6" fill="#f0f6fc" stroke="#8b949e"/>'
    )
    out.extend([
        (f'<text x="{padding}" y="{size + 24}" font-size="14">seed {result.seed} · '
         f'clubhouse {result.clubhouse} · {result.attempts_used} tirage(s) · '
         f'{result.elapsed_seconds * 1000:.0f} ms</text>'),
        (f'<text x="{padding}" y="{size + 44}" font-size="12">bleu=front '
         f'({len(skeleton.front_leaves)} feuille(s)) · jaune=back '
         f'({len(skeleton.back_leaves)} feuille(s)) · blanc=clubhouse</text>'),
        "</svg>",
    ])
    return "\n".join(out) + "\n"


# ----------------------------------------------------------------------
# Découpage DP (adapté de golfgen.loop_router._cut_nine) — NON appelé par
# build_skeleton dans ce round (voir docstring du module) ; conservé pour
# le prochain round, une fois la Porte 3 franchie sur le squelette seul.
# ----------------------------------------------------------------------

CUT_STEP = 3.0
STUB_MAX = 90.0
LINK_ARC_MAX = 150.0
MAX_CORNER_DEG = 100.0
MAX_NET_DEG = 92.0
SUB_POLYLINE_EPS = 0.75       # aligne sur _sub_polyline/_cut_nine de loop_router
DOGLEG_MIN_DEVIATION = 3.0    # en dessous, le trou est declare droit (0 dogleg)
PAR_ORDER_SHUFFLES = 14


def _polyline_length(points: list[Point]) -> float:
    return math.fsum(math.dist(a, b) for a, b in zip(points, points[1:]))


def _point_at(points: list[Point], arclength: float) -> Point:
    travelled = 0.0
    for a, b in zip(points, points[1:]):
        step = math.dist(a, b)
        if travelled + step >= arclength - 1e-9:
            t = 0.0 if step < 1e-9 else (arclength - travelled) / step
            return (a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t)
        travelled += step
    return points[-1]


def _sub_polyline(points: list[Point], start: float, end: float) -> list[Point]:
    result = [_point_at(points, start)]
    travelled = 0.0
    for a, b in zip(points, points[1:]):
        step = math.dist(a, b)
        if start + SUB_POLYLINE_EPS < travelled + step < end - SUB_POLYLINE_EPS:
            if travelled + step > start:
                result.append(b)
        travelled += step
    result.append(_point_at(points, end))
    return result


def _sample_coords(points: list[Point], step: float, count: int) -> list[Point]:
    coords = []
    seg_idx, travelled = 0, 0.0
    for k in range(count):
        target = k * step
        while seg_idx < len(points) - 2 and \
                travelled + math.dist(points[seg_idx], points[seg_idx + 1]) < target:
            travelled += math.dist(points[seg_idx], points[seg_idx + 1])
            seg_idx += 1
        a, b = points[seg_idx], points[seg_idx + 1]
        seg_len = math.dist(a, b)
        t = 0.0 if seg_len < 1e-9 else min(1.0, (target - travelled) / seg_len)
        coords.append((a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t))
    return coords


def _corners(points: list[Point]) -> list[tuple[float, float]]:
    out = []
    travelled = 0.0
    for i in range(1, len(points) - 1):
        travelled += math.dist(points[i - 1], points[i])
        d1 = math.dist(points[i - 1], points[i])
        d2 = math.dist(points[i], points[i + 1])
        if d1 < 1e-9 or d2 < 1e-9:
            continue
        v1 = ((points[i][0] - points[i - 1][0]) / d1, (points[i][1] - points[i - 1][1]) / d1)
        v2 = ((points[i + 1][0] - points[i][0]) / d2, (points[i + 1][1] - points[i][1]) / d2)
        angle = math.degrees(math.atan2(v1[0] * v2[1] - v1[1] * v2[0], v1[0] * v2[0] + v1[1] * v2[1]))
        if abs(angle) > 0.5:
            out.append((travelled, angle))
    return out


def _hole_length_range(par: int) -> tuple[float, float]:
    spec = PAR_SPECS[par]
    return spec.length_min, spec.length_max


def cut_nine(rng: random.Random, points: list[Point], pars: list[int]) -> list[dict] | None:
    """Découpe le contour d'un nine en 9 trous, adapté de ``_cut_nine``."""
    total = _polyline_length(points)
    n_pos = int(total / CUT_STEP)
    if n_pos < 10:
        return None
    coords = _sample_coords(points, CUT_STEP, n_pos)
    corner_list = _corners(points)
    corner_s = [s for s, _ in corner_list]

    def hole_ok(start: float, end: float) -> bool:
        lo = bisect_right(corner_s, start + SUB_POLYLINE_EPS)
        hi = bisect_left(corner_s, end - SUB_POLYLINE_EPS)
        net = 0.0
        for k in range(lo, hi):
            angle = corner_list[k][1]
            if abs(angle) > MAX_CORNER_DEG:
                return False
            net += angle
        return abs(net) <= MAX_NET_DEG

    link_indices = range(int(math.ceil(LINK_CONSTRUCTION_MIN / CUT_STEP)),
                         int(LINK_ARC_MAX / CUT_STEP) + 1)
    stub_indices = range(int(math.ceil(LINK_CONSTRUCTION_MIN / CUT_STEP)),
                         int(STUB_MAX / CUT_STEP) + 1)
    valid_holes: dict[tuple[int, int], list[int]] = {}

    def greens_for(tee_idx: int, par: int) -> list[int]:
        key = (tee_idx, par)
        if key not in valid_holes:
            lo, hi = _hole_length_range(par)
            result = []
            for length_idx in range(int(math.ceil(lo / CUT_STEP)), int(hi / CUT_STEP) + 1):
                green_idx = tee_idx + length_idx
                if green_idx >= n_pos:
                    break
                if hole_ok(tee_idx * CUT_STEP, green_idx * CUT_STEP):
                    result.append(green_idx)
            valid_holes[key] = result
        return valid_holes[key]

    def solve(order: list[int]) -> list[dict] | None:
        parent: list[dict[int, tuple[int | None, int]]] = [{} for _ in order]
        for tee_idx in stub_indices:
            for green_idx in greens_for(tee_idx, order[0]):
                parent[0].setdefault(green_idx, (None, tee_idx))
        for k in range(1, len(order)):
            for green_prev in parent[k - 1]:
                for link_idx in link_indices:
                    tee_idx = green_prev + link_idx
                    if tee_idx >= n_pos:
                        continue
                    chord = math.dist(coords[green_prev], coords[tee_idx])
                    if not LINK_CONSTRUCTION_MIN + 0.35 <= chord <= LINK_CONSTRUCTION_MAX:
                        continue
                    for green_idx in greens_for(tee_idx, order[k]):
                        parent[k].setdefault(green_idx, (green_prev, tee_idx))
        finals = [
            green_idx for green_idx in parent[-1]
            if LINK_CONSTRUCTION_MIN <= total - green_idx * CUT_STEP <= STUB_MAX
        ]
        if not finals:
            return None
        holes_rev = []
        green_idx = rng.choice(finals)
        for k in range(len(order) - 1, -1, -1):
            green_prev, tee_idx = parent[k][green_idx]
            holes_rev.append({
                "par": order[k],
                "waypoints": _sub_polyline(points, tee_idx * CUT_STEP, green_idx * CUT_STEP),
            })
            green_idx = green_prev
        return list(reversed(holes_rev))

    holes = solve(list(pars))
    if holes is not None:
        return holes
    for _ in range(PAR_ORDER_SHUFFLES):
        shuffled = list(pars)
        rng.shuffle(shuffled)
        holes = solve(shuffled)
        if holes is not None:
            return holes
    return None


# ----------------------------------------------------------------------
# Assemblage en ElasticHole / NineLayout — idem, non appelé ce round
# ----------------------------------------------------------------------

def _best_single_dogleg(waypoints: list[Point]) -> Point | None:
    """Point unique approximant au mieux la sous-polyligne (hors tee/green)."""
    if len(waypoints) <= 2:
        return None
    tee, green = waypoints[0], waypoints[-1]
    base_len = math.dist(tee, green)
    best_point, best_dev = None, DOGLEG_MIN_DEVIATION
    if base_len > 1e-9:
        ux, uy = (green[0] - tee[0]) / base_len, (green[1] - tee[1]) / base_len
        for point in waypoints[1:-1]:
            dev = abs((point[0] - tee[0]) * uy - (point[1] - tee[1]) * ux)
            if dev > best_dev:
                best_dev, best_point = dev, point
    return best_point


def _hole_from_cut(order: int, par: int, waypoints: list[Point]) -> ElasticHole:
    tee, green = waypoints[0], waypoints[-1]
    dogleg = _best_single_dogleg(waypoints)
    doglegs = () if dogleg is None else (ControlPoint(dogleg[0], dogleg[1]),)
    return ElasticHole(
        order=order,
        par=par,
        tee=ControlPoint(tee[0], tee[1]),
        green=ControlPoint(green[0], green[1]),
        doglegs=doglegs,
        width=PAR_SPECS[par].width_min,
    )


def _build_nine_layout(rng: random.Random, start_order: int, clubhouse: ControlPoint,
                       contour: list[Point]) -> NineLayout | None:
    """``None`` si la DP ne trouve aucun découpage (contour trop court/trop dur)."""
    cut = cut_nine(rng, contour, list(NINE_PAR_PATTERN))
    if cut is None:
        return None
    holes = tuple(
        _hole_from_cut(order, hole["par"], hole["waypoints"])
        for order, hole in enumerate(cut, start=start_order)
    )
    return NineLayout.from_holes(start_order, clubhouse, holes)
