"""Étape 3 — squelette global grossier : contour d'un arbre aléatoire.

Algorithme (voir PLAN.md, « Décision d'architecture avant l'étape 3 ») :

1. un arbre unique, enraciné au clubhouse, avec exactement deux sous-arbres
   (front, back) ; croissance alternée au sens où les deux sous-arbres sont
   tirés depuis le même état global (occupation, halo), seedés, sans retour
   arrière (aucune cellule n'est jamais revisitée) ;
2. budget de longueur cible par sous-arbre, halo entre parties non reliées
   localement, au plus trois feuilles par sous-arbre, branche menant à une
   feuille d'au moins ``MIN_LEAF_BRANCH_LENGTH`` blocs ;
3. rejet complet et borné (``MAX_TREE_ATTEMPTS`` tirages dérivés de la seed,
   zéro boucle non bornée) si un budget ne peut être atteint ;
4. le contour est le tour (à la manière d'un tour d'Euler) de l'arbre,
   décalé de ``RIBBON_OFFSET`` sur un seul côté courant (jamais ré-offsetté
   dans l'autre sens comme un ruban à deux brins indépendants : chaque arête
   de l'arbre est traversée deux fois par le tour, une fois dans chaque
   sens, ce qui produit naturellement les deux rives) ; congés en arc
   centrés sur chaque sommet du tour, cap en demi-cercle aux feuilles (cas
   particulier d'un virage à 180°) ;
5. DP de découpage par nine, adaptée de ``golfgen.loop_router._cut_nine``.

Pas de dépendance à ``shapely``. Toutes les longueurs sont en blocs.
"""

from __future__ import annotations

import math
import random
import time
from bisect import bisect_left, bisect_right
from dataclasses import dataclass, field

from experiments.elastic_routing.geometry import segments_intersect
from experiments.elastic_routing.model import (
    PAR_SPECS,
    ControlPoint,
    CourseLayout,
    ElasticHole,
    NineLayout,
)


Point = tuple[float, float]
Cell = tuple[int, int]


# ----------------------------------------------------------------------
# Constantes (voir PLAN.md, paramètres validés le 2026-10-07)
# ----------------------------------------------------------------------

GRID_PITCH = 5.0
GRID_CELLS = 80
MAP_SIZE = GRID_CELLS * GRID_PITCH  # 400.0
CLUBHOUSE_CELL: Cell = (GRID_CELLS // 2, GRID_CELLS // 2)  # centre, pas impose par le modele

RIBBON_OFFSET = 12.0
HALO_MARGIN = 23.0
HALO_MIN_DIST = 2.0 * RIBBON_OFFSET + HALO_MARGIN  # 47.0 blocs (~10 cellules)
# Exemption de halo pres du clubhouse (cf. near_hub/HUB_RADIUS de
# loop_router, qui vaut ~2.2x sa propre CLEARANCE_REQUIRED) : le tronc quitte
# le clubhouse en ligne a peu pres droite puis tourne vite dans la premiere
# rangee, repassant parfois juste a cote de son propre depart avant d'etre
# "localement relie" au sens strict (LOCAL_WINDOW_BLOCKS) -- sans cette
# marge, cette zone immediate produit des faux positifs de halo.
HUB_RADIUS = 2.2 * HALO_MIN_DIST
# Fenetre "localement reliee" le long de l'arbre. A un virage a 90 degres
# (nos rangees en boustrophedon n'en font pas d'autres), deux points a une
# distance d'arc a et b du coin (a+b = LOCAL_WINDOW_BLOCKS) sont separes
# d'au moins sqrt(a^2+b^2), minimal (pire cas a=b=W/2) a W/sqrt(2). Pour
# garantir ce minimum >= HALO_MIN_DIST il faut W >= HALO_MIN_DIST*sqrt(2)
# (~66.5) ; marge prise a *1.5 pour couvrir aussi les coudes de branche
# (angle de fourche moins favorable que 90 degres).
LOCAL_WINDOW_BLOCKS = 1.5 * HALO_MIN_DIST

MIN_LEAF_BRANCH_LENGTH = 300.0
MAX_LEAVES_PER_SUBTREE = 3
MAX_ARC_STEP_DEG = 22.0
# Le clubhouse est au centre de la carte (choix de ce module, cf. docstring
# de build_skeleton) : chaque sous-arbre dispose d'environ moitie moins de
# place qu'avec un clubhouse de coin (comme loop_router), donc une plus
# grande fraction des tirages est rejetee (ligne hors carte, collision ou
# decoupage DP impossible). Mesure empirique (apres troncature du meandre
# au contact, cf. _grow_boustrophedon) : ~50% des sous-arbres seuls
# reussissent, mais certaines seeds precises exigent plusieurs centaines de
# tirages avant qu'un COUPLE front/back + decoupage DP passe. "ex. <= 50" du
# plan est donc porte a 1500 (verifie < 2 s par seed sur les seeds 1-10,
# largement sous la cible de 60 s) ; reste une borne fixe, deterministe,
# sans boucle non bornee.
MAX_TREE_ATTEMPTS = 1500

# Le squelette est un meandre en boustrophedon (comme la spine de
# loop_router), rasterise sur la grille : chaque rangee est perpendiculaire
# a la precedente a ROW_PITCH (>= HALO_MIN_DIST) pres, ce qui satisfait le
# halo entre rangees PAR CONSTRUCTION plutot que par rejet reactif d'une
# marche aleatoire (qui se bloque trop souvent au contact du halo, cf.
# tentative initiale documentee dans le rapport).
EDGE_MARGIN = 10.0
ROW_PITCH = HALO_MIN_DIST + 6.0
ROW_JITTER = 4.0

NEIGHBOR_DELTAS: tuple[Cell, ...] = (
    (-1, -1), (-1, 0), (-1, 1), (0, -1), (0, 1), (1, -1), (1, 0), (1, 1),
)

CUT_STEP = 3.0
LINK_CONSTRUCTION_MIN = 12.0
LINK_CONSTRUCTION_MAX = 60.0
STUB_MAX = 90.0
LINK_ARC_MAX = 150.0
MAX_CORNER_DEG = 100.0
MAX_NET_DEG = 92.0
SUB_POLYLINE_EPS = 0.75       # aligne sur _sub_polyline/_cut_nine de loop_router
DOGLEG_MIN_DEVIATION = 3.0    # en dessous, le trou est declare droit (0 dogleg)
PAR_ORDER_SHUFFLES = 14

NINE_PAR_PATTERN = (3, 4, 4, 4, 4, 5, 5, 4, 3)  # 2 par3, 2 par5, 5 par4 (comme synthetic.py)


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
# Grille
# ----------------------------------------------------------------------

def cell_to_world(cell: Cell) -> Point:
    return (cell[0] * GRID_PITCH, cell[1] * GRID_PITCH)


def _edge_length(delta: Cell) -> float:
    return GRID_PITCH * math.hypot(delta[0], delta[1])


def _wrap_pi(angle: float) -> float:
    return (angle + math.pi) % (2.0 * math.pi) - math.pi


# ----------------------------------------------------------------------
# État global de l'arbre (un seul arbre, deux sous-arbres sous le clubhouse)
# ----------------------------------------------------------------------

@dataclass
class TreeState:
    parent: dict[Cell, Cell | None] = field(default_factory=dict)
    arclen: dict[Cell, float] = field(default_factory=dict)
    children: dict[Cell, list[Cell]] = field(default_factory=dict)
    buckets: dict[Cell, set[Cell]] = field(default_factory=dict)  # index spatial grossier

    def __post_init__(self) -> None:
        self.parent[CLUBHOUSE_CELL] = None
        self.arclen[CLUBHOUSE_CELL] = 0.0
        self._bucket_add(CLUBHOUSE_CELL)

    def _bucket_key(self, cell: Cell) -> Cell:
        size = max(1, int(round(HALO_MIN_DIST / GRID_PITCH)))
        return (cell[0] // size, cell[1] // size)

    def _bucket_add(self, cell: Cell) -> None:
        self.buckets.setdefault(self._bucket_key(cell), set()).add(cell)

    def nearby(self, cell: Cell) -> list[Cell]:
        bx, by = self._bucket_key(cell)
        result: list[Cell] = []
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                result.extend(self.buckets.get((bx + dx, by + dy), ()))
        return result

    def add(self, cell: Cell, parent_cell: Cell) -> None:
        edge = _edge_length((cell[0] - parent_cell[0], cell[1] - parent_cell[1]))
        self.parent[cell] = parent_cell
        self.arclen[cell] = self.arclen[parent_cell] + edge
        self.children.setdefault(parent_cell, []).append(cell)
        self.children.setdefault(cell, [])
        self._bucket_add(cell)

    def is_locally_connected(self, a: Cell, b: Cell, limit: float = LOCAL_WINDOW_BLOCKS) -> bool:
        """Distance le long de l'arbre entre ``a`` et ``b`` <= ``limit`` ?

        Marche bornee (par ``limit``) depuis chaque extremite ; ne calcule
        jamais la distance exacte au-dela du seuil (complexite independante
        de la taille de l'arbre).
        """
        if a == b:
            return True
        anc_a = self._bounded_ancestors(a, limit)
        anc_b = self._bounded_ancestors(b, limit)
        common = anc_a.keys() & anc_b.keys()
        if not common:
            return False
        return min(anc_a[c] + anc_b[c] for c in common) <= limit

    def _bounded_ancestors(self, start: Cell, limit: float) -> dict[Cell, float]:
        out = {start: 0.0}
        cur, dist = start, 0.0
        while True:
            parent_cell = self.parent.get(cur)
            if parent_cell is None:
                break
            edge = self.arclen[cur] - self.arclen[parent_cell]
            dist += edge
            if dist > limit:
                break
            out[parent_cell] = dist
            cur = parent_cell
        return out


def _halo_ok(candidate_cell: Cell, candidate_world: Point, parent_cell: Cell,
            candidate_arclen: float, tree: TreeState) -> bool:
    clubhouse_world = cell_to_world(CLUBHOUSE_CELL)
    candidate_near_hub = math.dist(candidate_world, clubhouse_world) < HUB_RADIUS
    for other in tree.nearby(candidate_cell):
        if other == parent_cell:
            continue
        other_world = cell_to_world(other)
        if math.dist(candidate_world, other_world) >= HALO_MIN_DIST:
            continue
        if candidate_near_hub and math.dist(other_world, clubhouse_world) < HUB_RADIUS:
            continue
        # Connexion locale le long de l'arbre : on simule l'ajout du candidat
        # en l'ajoutant temporairement (retire juste apres).
        tree.parent[candidate_cell] = parent_cell
        tree.arclen[candidate_cell] = candidate_arclen
        try:
            local = tree.is_locally_connected(candidate_cell, other)
        finally:
            del tree.parent[candidate_cell]
            del tree.arclen[candidate_cell]
        if local:
            continue
        return False
    return True


# ----------------------------------------------------------------------
# Croissance d'une chaîne : méandre en boustrophédon rasterisé sur la grille
# ----------------------------------------------------------------------

def _rect_cap(origin: Point, theta: float) -> float:
    """Distance max depuis ``origin`` le long de ``theta`` restant en carte."""
    x, y = origin
    cos_t, sin_t = math.cos(theta), math.sin(theta)
    cap = float("inf")
    if cos_t > 1e-9:
        cap = min(cap, (MAP_SIZE - EDGE_MARGIN - x) / cos_t)
    elif cos_t < -1e-9:
        cap = min(cap, (EDGE_MARGIN - x) / cos_t)
    if sin_t > 1e-9:
        cap = min(cap, (MAP_SIZE - EDGE_MARGIN - y) / sin_t)
    elif sin_t < -1e-9:
        cap = min(cap, (EDGE_MARGIN - y) / sin_t)
    return max(cap, 0.0)


def _in_map(point: Point) -> bool:
    return (EDGE_MARGIN <= point[0] <= MAP_SIZE - EDGE_MARGIN
            and EDGE_MARGIN <= point[1] <= MAP_SIZE - EDGE_MARGIN)


def _boustrophedon_waypoints_signed(rng: random.Random, origin_world: Point, theta: float,
                                    target_length: float, sign: float,
                                    max_rows: int = 40) -> list[Point]:
    """Rangées perpendiculaires à ``theta`` (un seul côté, ``sign`` fixe), espacées de ``ROW_PITCH``.

    Le halo entre rangées voisines est satisfait par construction (le pas
    perpendiculaire est toujours >= ``HALO_MIN_DIST``), au lieu d'être testé
    et rejeté après coup sur une marche aléatoire (essai initial abandonné,
    voir le rapport de l'étape 3).
    """
    e1 = (math.cos(theta), math.sin(theta))
    perp = (-e1[1], e1[0])
    e2 = (sign * perp[0], sign * perp[1])

    points = [origin_world]
    pos = (origin_world[0] + 1.0 * ROW_PITCH * e2[0], origin_world[1] + 1.0 * ROW_PITCH * e2[1])
    if _in_map(pos):
        points.append(pos)
    else:
        pos = origin_world

    direction = 1
    row_margin = ROW_PITCH * 0.5  # marge pour que le connecteur reste en carte
    for _ in range(max_rows):
        row_theta = math.atan2(e1[1], e1[0]) if direction > 0 else math.atan2(-e1[1], -e1[0])
        u_cap = max(0.0, _rect_cap(pos, row_theta) - row_margin - rng.uniform(0.0, ROW_JITTER))
        end = (pos[0] + direction * u_cap * e1[0], pos[1] + direction * u_cap * e1[1])
        points.append(end)
        if _polyline_length(points) >= target_length:
            break
        # Connecteur perpendiculaire vers la rangée suivante : même u, v +
        # pitch (comme loop_router._spine_points), jamais une diagonale qui
        # pourrait recroiser une rangée déjà posée.
        next_pos = (end[0] + ROW_PITCH * e2[0], end[1] + ROW_PITCH * e2[1])
        if not _in_map(next_pos):
            break
        points.append(next_pos)
        pos = next_pos
        direction *= -1
    return points


def _boustrophedon_waypoints(rng: random.Random, origin_world: Point, theta: float,
                             target_length: float, max_rows: int = 40) -> list[Point]:
    """Essaie les deux côtés perpendiculaires à ``theta`` et garde le plus long.

    Le clubhouse est au centre de la carte (pas de coin disponible comme
    dans loop_router) : un seul côté perpendiculaire choisi par une
    heuristique de distance au bord (essai initial abandonné, voir le
    rapport de l'étape 3) se heurtait trop souvent au bord après une seule
    rangée, pour un angle ``theta`` donné. Construire les deux côtés et
    garder le résultat le plus long reste déterministe (même ``rng``
    consommé dans le même ordre pour les deux essais) et borné (``max_rows``
    de chaque côté), et augmente nettement le rendement du tirage global.
    """
    rng_a = random.Random(rng.random())
    rng_b = random.Random(rng.random())
    candidate_a = _boustrophedon_waypoints_signed(rng_a, origin_world, theta, target_length, 1.0, max_rows)
    candidate_b = _boustrophedon_waypoints_signed(rng_b, origin_world, theta, target_length, -1.0, max_rows)
    if _polyline_length(candidate_a) >= _polyline_length(candidate_b):
        return candidate_a
    return candidate_b


def _snap_cell(point: Point) -> Cell:
    cx = max(0, min(GRID_CELLS - 1, round(point[0] / GRID_PITCH)))
    cy = max(0, min(GRID_CELLS - 1, round(point[1] / GRID_PITCH)))
    return (cx, cy)


def _bresenham(a: Cell, b: Cell) -> list[Cell]:
    """Ligne numérique 8-connexe de ``a`` à ``b`` (DDA par interpolation entière).

    Préféré à une marche gloutonne « plus proche voisin du but » : cette
    dernière zigzague sur les segments à pente faible (elle alterne entre
    deux colonnes pour corriger l'erreur), ce qui allonge artificiellement
    l'arclength locale et déclenche de faux positifs du halo contre elle
    même (essai initial abandonné, voir le rapport de l'étape 3).
    """
    x0, y0 = a
    x1, y1 = b
    dx, dy = x1 - x0, y1 - y0
    steps = max(abs(dx), abs(dy))
    if steps == 0:
        return [a]
    return [(round(x0 + dx * i / steps), round(y0 + dy * i / steps)) for i in range(steps + 1)]


def _rasterize_from(start_cell: Cell, waypoints: list[Point]) -> list[Cell]:
    """Chemine cellule par cellule de ``start_cell`` vers chaque waypoint (ligne droite)."""
    cells = [start_cell]
    current_cell = start_cell
    for target_world in waypoints[1:]:
        target_cell = _snap_cell(target_world)
        segment = _bresenham(current_cell, target_cell)
        cells.extend(segment[1:])
        current_cell = target_cell
    return cells


def _grow_boustrophedon(rng: random.Random, tree: TreeState, start_cell: Cell,
                        theta: float, target_length: float) -> tuple[float, list[Cell]]:
    """Fait croître l'arbre depuis ``start_cell`` (déjà présent dans ``tree``).

    Tronque (n'ajoute rien de plus, sans retour arrière) dès que la
    rasterisation entrerait en collision avec l'arbre existant ou le halo —
    plutôt que de jeter tout le progrès déjà fait (essai initial abandonné :
    annuler systématiquement tout le sous-arbre dès la première rangée en
    défaut, souvent après plusieurs rangées valides, faisait chuter le
    rendement du tirage sous 15 %, voir le rapport de l'étape 3). Lève
    ``_SubtreeStuck`` seulement si la longueur obtenue reste sous
    ``MIN_LEAF_BRANCH_LENGTH``.
    """
    origin_world = cell_to_world(start_cell)
    waypoints = _boustrophedon_waypoints(rng, origin_world, theta, target_length)

    raw_cells = _rasterize_from(start_cell, waypoints)
    cells = [raw_cells[0]]
    for cell in raw_cells[1:]:
        if cell != cells[-1]:
            cells.append(cell)

    current = start_cell
    total = 0.0
    out_cells = [start_cell]
    for cell in cells[1:]:
        if cell in tree.parent:
            break  # collision avec une cellule existante : on s'arrete ici
        edge_len = _edge_length((cell[0] - current[0], cell[1] - current[1]))
        candidate_arclen = tree.arclen[current] + edge_len
        if not _halo_ok(cell, cell_to_world(cell), current, candidate_arclen, tree):
            break  # halo viole : on s'arrete ici, pas de retour arriere
        tree.add(cell, current)
        total += edge_len
        current = cell
        out_cells.append(cell)
    if total < MIN_LEAF_BRANCH_LENGTH:
        raise _SubtreeStuck(
            f"meandre tronque trop court ({total:.1f} < {MIN_LEAF_BRANCH_LENGTH})"
        )
    return total, out_cells


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


def _grow_subtree(rng: random.Random, tree: TreeState, start_angle: float,
                  target_length: float, clubhouse_world: Point) -> list[Cell]:
    """Construit un sous-arbre complet (tronc en boustrophédon + branches).

    Lève ``_SubtreeStuck`` si le budget minimal (une seule feuille d'au
    moins ``MIN_LEAF_BRANCH_LENGTH``) n'est pas atteignable ; le tirage
    entier est alors abandonné (``MAX_TREE_ATTEMPTS``, pas de retour
    arrière interne). Retourne la liste des feuilles (cellules) du
    sous-arbre.
    """
    del clubhouse_world  # le pivot de chaque rangee est deja l'origine du tronc/branche
    num_leaves, trunk_target, branch_targets = _choose_leaf_plan(rng, target_length)
    trunk_grown, trunk_cells = _grow_boustrophedon(rng, tree, CLUBHOUSE_CELL, start_angle, trunk_target)
    if trunk_grown < MIN_LEAF_BRANCH_LENGTH:
        raise _SubtreeStuck(f"tronc trop court ({trunk_grown:.1f} < {MIN_LEAF_BRANCH_LENGTH})")

    leaves = [trunk_cells[-1]]

    for branch_target in branch_targets:
        branch_point = _pick_branch_point(rng, tree, trunk_cells, branch_target)
        if branch_point is None:
            continue  # reduit silencieusement le nombre de feuilles (<=3 reste respecte)
        fan_angle = start_angle + rng.choice([-1.0, 1.0]) * rng.uniform(math.pi / 3, 2 * math.pi / 3)
        branch_grown, branch_cells = _grow_boustrophedon(rng, tree, branch_point, fan_angle, branch_target)
        if branch_grown < MIN_LEAF_BRANCH_LENGTH:
            raise _SubtreeStuck(f"branche trop courte ({branch_grown:.1f})")
        leaves.append(branch_cells[-1])

    if len(leaves) > MAX_LEAVES_PER_SUBTREE:
        raise _SubtreeStuck("trop de feuilles")
    return leaves


class _SubtreeStuck(RuntimeError):
    """Signal interne : ce tirage de sous-arbre echoue, on retire l'arbre entier."""


def _pick_branch_point(rng: random.Random, tree: TreeState, trunk_nodes: list[Cell],
                       branch_target: float) -> Cell | None:
    trunk_total = tree.arclen[trunk_nodes[-1]] - tree.arclen[trunk_nodes[0]]
    candidates = [
        node for node in trunk_nodes
        if HUB_RADIUS <= tree.arclen[node] - tree.arclen[trunk_nodes[0]] <= trunk_total - MIN_LEAF_BRANCH_LENGTH
    ]
    if not candidates:
        return None
    return rng.choice(candidates)


# ----------------------------------------------------------------------
# Arbre complet (deux sous-arbres)
# ----------------------------------------------------------------------

@dataclass(frozen=True)
class Skeleton:
    tree: TreeState
    front_root: Cell
    back_root: Cell
    front_leaves: tuple[Cell, ...]
    back_leaves: tuple[Cell, ...]
    front_length: float
    back_length: float


@dataclass(frozen=True)
class _SkeletonAttempt:
    skeleton: Skeleton
    front_contour: list[Point]
    back_contour: list[Point]
    layout: CourseLayout


def _build_tree(seed: int) -> _SkeletonAttempt:
    """Boucle de rejet bornée (``MAX_TREE_ATTEMPTS``) sur le pipeline complet.

    Un tirage n'est accepté que si l'arbre atteint son budget, son contour
    est simple ET la DP de découpage trouve un decoupage pour les deux
    nines — un échec à n'importe laquelle de ces étapes retire l'arbre
    entier (pas de retour arrière interne, pas de boucle non bornée : au
    plus ``MAX_TREE_ATTEMPTS`` tirages dérivés de la seed).
    """
    clubhouse_world = cell_to_world(CLUBHOUSE_CELL)
    clubhouse = ControlPoint(*clubhouse_world)
    for attempt in range(MAX_TREE_ATTEMPTS):
        rng = random.Random(f"elastic_routing_skeleton:{seed}:{attempt}")
        tree = TreeState()
        front_angle = rng.uniform(0.0, 2.0 * math.pi)
        back_angle = front_angle + math.pi + rng.uniform(-0.6, 0.6)
        front_target = rng.uniform(*SUBTREE_LENGTH_RANGE)
        back_target = rng.uniform(*SUBTREE_LENGTH_RANGE)
        try:
            front_leaves = _grow_subtree(rng, tree, front_angle, front_target, clubhouse_world)
            back_leaves = _grow_subtree(rng, tree, back_angle, back_target, clubhouse_world)
        except _SubtreeStuck:
            continue
        roots = tree.children[CLUBHOUSE_CELL]
        if len(roots) != 2:
            continue
        front_root, back_root = roots
        # Le halo et le lissage visent a garantir un contour simple ; on le
        # verifie numeriquement (comme loop_router verifie sa clairance) et
        # on retire l'arbre entier si ca echoue malgre tout, plutot que de
        # produire un contour qui se recoupe.
        front_contour = build_contour(_full_tour(front_root, tree))
        back_contour = build_contour(_full_tour(back_root, tree))
        if not is_simple_polyline(front_contour) or not is_simple_polyline(back_contour):
            continue
        front = _build_nine_layout(rng, 1, clubhouse, front_contour)
        back = _build_nine_layout(rng, 10, clubhouse, back_contour)
        if front is None or back is None:
            continue
        try:
            layout = CourseLayout(
                seed=seed, width=MAP_SIZE, height=MAP_SIZE, clubhouse=clubhouse, front=front, back=back,
            )
        except (TypeError, ValueError):
            continue  # quota/structure incoherente issue de la DP : tirage retire
        front_total = _subtree_total_length(tree, front_root)
        back_total = _subtree_total_length(tree, back_root)
        skeleton = Skeleton(tree, front_root, back_root, tuple(front_leaves), tuple(back_leaves),
                            front_total, back_total)
        return _SkeletonAttempt(skeleton, front_contour, back_contour, layout)
    raise SkeletonGenerationError(
        f"aucun arbre valide apres {MAX_TREE_ATTEMPTS} tirages derives (seed={seed})"
    )


def _subtree_total_length(tree: TreeState, root: Cell) -> float:
    total = 0.0
    stack = [root]
    while stack:
        node = stack.pop()
        for child in tree.children.get(node, ()):
            total += tree.arclen[child] - tree.arclen[node]
            stack.append(child)
    return total


# ----------------------------------------------------------------------
# Tour (à la manière d'un tour d'Euler) et contour décalé
# ----------------------------------------------------------------------

def _angle_between(a: Point, b: Point) -> float:
    return math.atan2(b[1] - a[1], b[0] - a[0])


def _tour_nodes(node: Cell, parent: Cell | None, tree: TreeState) -> list[Cell]:
    kids = [c for c in tree.children.get(node, ()) if c != parent]
    if not kids:
        return [node]
    node_world = cell_to_world(node)
    if parent is not None:
        ref = _angle_between(node_world, cell_to_world(parent))
    else:
        ref = 0.0
    kids_sorted = sorted(
        kids,
        key=lambda k: (_angle_between(node_world, cell_to_world(k)) - ref) % (2.0 * math.pi),
    )
    sequence = [node]
    for kid in kids_sorted:
        sequence.append(kid)
        sub = _tour_nodes(kid, node, tree)
        sequence.extend(sub[1:])
        sequence.append(node)
    return sequence


def _full_tour(root_child: Cell, tree: TreeState) -> list[Cell]:
    """Tour clubhouse -> ... -> clubhouse pour le sous-arbre débutant à ``root_child``."""
    return [CLUBHOUSE_CELL] + _tour_nodes(root_child, CLUBHOUSE_CELL, tree) + [CLUBHOUSE_CELL]


def _point_to_segment_distance(point: Point, a: Point, b: Point) -> float:
    dx, dy = b[0] - a[0], b[1] - a[1]
    length_sq = dx * dx + dy * dy
    if length_sq <= 1e-12:
        return math.dist(point, a)
    ratio = max(0.0, min(1.0, ((point[0] - a[0]) * dx + (point[1] - a[1]) * dy) / length_sq))
    return math.dist(point, (a[0] + ratio * dx, a[1] + ratio * dy))


def _simplify_tour_points(points: list[Point], epsilon: float = 1.5 * GRID_PITCH) -> list[Point]:
    """Douglas-Peucker itératif : lisse le bruit de rasterisation en escalier.

    Chaque rangée du méandre est rasterisée cellule par cellule (pas de 5 ou
    7.07 blocs) : une pente peu alignée sur les 8 directions produit un
    escalier dont chaque marche change de direction de ±45°, un angle trop
    grand pour être filtré par un simple seuil local sur le virage (essai
    initial abandonné, voir le rapport de l'étape 3). Toutes les marches
    restent à moins de ``epsilon`` de la corde idéale ; Douglas-Peucker les
    fusionne sans toucher les vrais virages (feuilles, nœuds de branche).
    Implémentation itérative (pas de récursion : jusqu'à ~1500 points).
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

    Un décalage uniforme (toujours à gauche du sens de marche) d'une ligne
    brisée NON lissée se recoupe lui-même du côté concave d'un virage dur :
    les deux segments adjacents, décalés sans être raccourcis, se croisent
    à une distance ``radius*tan(virage/2)`` du sommet, souvent bien avant le
    rayon de décalage lui-même (essai initial abandonné, voir le rapport de
    l'étape 3). Lisser la LIGNE CENTRALE d'abord (comme la spine de
    loop_router, ici avec un rayon >= au décalage du ruban) rend ensuite le
    décalage par arc centré sur chaque sommet sûr, car aucun virage résiduel
    ne dépasse ``MAX_ARC_STEP_DEG``. Les quasi demi-tours (feuilles) sont
    volontairement non modifiés ici : la formule en tangente diverge à 180°,
    et ``build_contour`` leur applique directement l'arc centré exact (cap
    en demi-cercle), qui n'a pas ce problème de côté concave.
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


def build_contour(tour_cells: list[Cell], radius: float = RIBBON_OFFSET) -> list[Point]:
    """Décale le tour d'un côté courant (la main gauche du sens de marche).

    Après le lissage de la ligne centrale (``_round_centerline_corners``,
    qui porte le « congé en arc »), le décalage proprement dit utilise
    l'intersection des deux bords décalés à chaque sommet (onglet, porté de
    ``golfgen.loop_router._offset_polyline``) : un arc centré séparément sur
    CHAQUE sommet (essai initial abandonné, voir le rapport de l'étape 3) ne
    raccourcit jamais les segments adjacents, qui se recoupent alors du
    côté concave d'un virage, à une distance ``radius*tan(virage/2)`` du
    sommet — un défaut qui s'aggrave en subdivisant (la somme des tangentes
    de petits angles dépasse la tangente de l'angle total). L'onglet n'a
    ce problème que pour un demi-tour (tangente infinie) : les sommets
    marqués comme virage de feuille (quasi 180°, non lissés plus haut)
    reçoivent donc directement le cap en demi-cercle centré sur le sommet.
    """
    points = _round_centerline_corners(_simplify_tour_points([cell_to_world(c) for c in tour_cells]))
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
# Découpage DP (adapté de golfgen.loop_router._cut_nine)
# ----------------------------------------------------------------------

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
# Assemblage en ElasticHole / NineLayout / CourseLayout
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
    """``None`` si la DP ne trouve aucun découpage (contour trop court/trop dur) :

    le tirage d'arbre est alors abandonné comme les autres rejets bornés de
    ``_build_tree``, pas une erreur fatale isolée.
    """
    cut = cut_nine(rng, contour, list(NINE_PAR_PATTERN))
    if cut is None:
        return None
    holes = tuple(
        _hole_from_cut(order, hole["par"], hole["waypoints"])
        for order, hole in enumerate(cut, start=start_order)
    )
    return NineLayout.from_holes(start_order, clubhouse, holes)


# ----------------------------------------------------------------------
# Orchestration
# ----------------------------------------------------------------------

@dataclass(frozen=True)
class SkeletonResult:
    layout: CourseLayout
    skeleton: Skeleton
    front_contour: tuple[Point, ...]
    back_contour: tuple[Point, ...]
    front_simple: bool
    back_simple: bool
    elapsed_seconds: float


def build_skeleton(seed: int) -> SkeletonResult:
    start = time.perf_counter()
    attempt = _build_tree(seed)
    elapsed = time.perf_counter() - start
    return SkeletonResult(
        layout=attempt.layout,
        skeleton=attempt.skeleton,
        front_contour=tuple(attempt.front_contour),
        back_contour=tuple(attempt.back_contour),
        front_simple=True,
        back_simple=True,
        elapsed_seconds=elapsed,
    )


# ----------------------------------------------------------------------
# Rendu SVG du squelette (arbre + contour + coupures), avant tout layout
# ----------------------------------------------------------------------

def _subtree_cells(tree: TreeState, root: Cell) -> list[Cell]:
    cells = [root]
    stack = [root]
    while stack:
        node = stack.pop()
        for child in tree.children.get(node, ()):
            cells.append(child)
            stack.append(child)
    return cells


def render_skeleton_svg(result: SkeletonResult) -> str:
    """SVG de diagnostic : cellules de l'arbre par nine, contour, coupures, clubhouse."""
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

    for root, color in ((skeleton.front_root, "#58a6ff"), (skeleton.back_root, "#f2cc60")):
        for cell in _subtree_cells(skeleton.tree, root):
            p = point(cell_to_world(cell))
            out.append(f'<circle cx="{p[0]:.1f}" cy="{p[1]:.1f}" r="1.4" fill="{color}" fill-opacity="0.75"/>')

    for contour, color in ((result.front_contour, "#58a6ff"), (result.back_contour, "#f2cc60")):
        path = " ".join(f"{point(p)[0]:.1f},{point(p)[1]:.1f}" for p in contour)
        out.append(f'<polygon points="{path}" fill="none" stroke="{color}" stroke-width="1.4" stroke-opacity="0.9"/>')

    for hole in result.layout.holes:
        tee, green = point((hole.tee.x, hole.tee.y)), point((hole.green.x, hole.green.y))
        out.append(f'<circle cx="{tee[0]:.1f}" cy="{tee[1]:.1f}" r="3" fill="#f0f6fc"/>')
        out.append(f'<circle cx="{green[0]:.1f}" cy="{green[1]:.1f}" r="3" fill="#ff2d7a"/>')

    clubhouse = point((result.layout.clubhouse.x, result.layout.clubhouse.y))
    out.append(
        f'<circle cx="{clubhouse[0]:.1f}" cy="{clubhouse[1]:.1f}" r="6" fill="#f0f6fc" stroke="#8b949e"/>'
    )
    out.extend([
        (f'<text x="{padding}" y="{size + 24}" font-size="14">seed {result.layout.seed} · '
         f'{result.elapsed_seconds * 1000:.0f} ms · bleu=front · jaune=back · blanc=tee · '
         'rose=green</text>'),
        "</svg>",
    ])
    return "\n".join(out) + "\n"
