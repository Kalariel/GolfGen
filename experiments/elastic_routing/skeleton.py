"""Étape 3 — squelette global grossier : contour d'un arbre aléatoire.

Round correctif du 2026-10-07 (3e passe). Historique :

- 1re passe : méandre en boustrophédon — refusé à la Porte 3 (deux
  serpentins en S face à face, carte sous-occupée).
- 2e passe : marche aléatoire biaisée sur réseau grossier, 1 feuille par
  sous-arbre — accepté sur le mécanisme, mais refusé de nouveau : un bug de
  fermeture du contour (voir ``build_contour``), un budget d'arbre non
  imposé et une ramification toujours à 1 feuille (carte sous-occupée).

Cette passe corrige les deux bugs, impose 2 ou 3 feuilles par sous-arbre,
fait pousser les branches en alternance (pas seulement les troncs) et rend
le décalage du contour (``offset``) configurable. Toujours sans DP de
découpage ni ``CourseLayout`` (ce code, déjà validé, reste plus bas dans ce
fichier, non appelé par ``build_skeleton``).

Algorithme :

1. réseau grossier de nœuds, pas = halo arrondi (``make_config``), 8
   voisins (orthogonaux + diagonaux), marge de bord vérifiée contre
   l'offset et la plus grande demi-largeur de fairway ;
2. clubhouse = un nœud du réseau tiré par la seed ; racine de l'arbre,
   exactement deux sous-arbres (front, back) ;
3. croissance ALTERNÉE au niveau de l'ARÊTE (tronc puis branches, front et
   back entrelacés) par marche aléatoire biaisée « voyage » (s'éloigner du
   clubhouse, puis y revenir) ; budget de longueur par sous-arbre dérivé de
   ``PAR_SPECS`` (et de l'offset, via les caps) et IMPOSÉ (rejet si sous le
   minimum) ; 2 ou 3 feuilles par sous-arbre (jamais 1), chaque branche
   menant à une feuille d'au moins ``min_leaf_branch_length`` blocs (valeur
   recalculée depuis le budget, voir ``make_config``) ;
4. halo GÉNÉRAL : toute paire d'arêtes de l'arbre sans nœud commun doit
   être à distance segment-segment >= ``halo_min_dist`` ;
5. rejet complet et borné (``MAX_TREE_ATTEMPTS`` tirages dérivés de la
   seed, zéro boucle non bornée) si un budget ou la ramification ne peuvent
   être atteints ;
6. contour = tour COMBINÉ (à la manière d'un tour d'Euler) des DEUX
   sous-arbres à la fois, FERMÉ, via le clubhouse commun
   (``_combined_tour_with_owners`` : clubhouse -> front -> clubhouse ->
   back -> clubhouse, un seul cycle, PAS deux tours indépendants chacun
   refermé par un cap au clubhouse — round précédent, bug : les deux caps
   se recoupaient systématiquement, les tiges front/back étant plantées à
   ~180° l'une de l'autre) ; décalage de polyligne standard sommet par
   sommet sur ce tour combiné, SANS lissage préalable de la ligne centrale
   — côté convexe, jointure ronde (arc de rayon ``offset``, pas <= 22°) ;
   côté concave, intersection des deux segments décalés adjacents (sinon
   ``ContourOffsetError``, violation de halo explicite). Une feuille est un
   demi-tour exact, toujours classé côté convexe : la jointure ronde y
   produit directement un cap en demi-cercle, sans cas particulier — le
   clubhouse n'en est PLUS un cas depuis le tour combiné (prev/nxt y sont
   toujours deux nœuds différents, les racines des deux sous-arbres). Le
   contour combiné simple (vérifié en un seul passage, garantissant à la
   fois qu'aucun arc ne se recoupe lui-même ET que les deux arcs ne se
   recoupent pas l'un l'autre) est ensuite redécoupé en deux ARCS OUVERTS
   ``front_contour``/``back_contour`` d'après le tag d'origine de chaque
   point.

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
# Constantes globales (indépendantes de l'offset)
# ----------------------------------------------------------------------

MAP_SIZE = 400.0
HALO_MARGIN = 23.0
MAX_LEAVES_PER_SUBTREE = 3
MAX_ARC_STEP_DEG = 22.0
BRANCH_JITTER = 60.0              # marge de longueur au-dessus du minimum pour une branche

# Mesuré sur les seeds 1-20 (offset 12) : la combinaison 2-3 feuilles +
# fenêtre de budget stricte + contour fermé simple est nettement plus dure
# à satisfaire que le round précédent (1 feuille, pas de budget imposé) --
# certaines seeds (ex. 17) n'aboutissent qu'après plusieurs centaines de
# tirages (pire cas observé : 614). 50 (la cible demandée) ne suffit pas ;
# plutôt que de masquer le problème, ``build_skeleton`` consigne toujours le
# taux de rejet réel (``attempts_used``) dans son résultat et le rapport du
# runner. Borne portée à 1500 (comme le round 2), qui reste < 1,3 s par seed
# mesuré -- un ordre de grandeur sous la cible de 60 s.
MAX_TREE_ATTEMPTS = 1500

NEIGHBOR_DELTAS: tuple[Node, ...] = (
    (-1, -1), (-1, 0), (-1, 1), (0, -1), (0, 1), (1, -1), (1, 0), (1, 1),
)

NINE_PAR_PATTERN = (3, 4, 4, 4, 4, 5, 5, 4, 3)  # 2 par3, 2 par5, 5 par4 (comme synthetic.py)

# Liaisons de construction (DP de découpage, non utilisée par ce round) :
# conservées ici pour que les bornes de contour par nine restent identiques
# à l'étape 3 initiale, sans dépendre d'une DP appelée.
LINK_CONSTRUCTION_MIN = 12.0
LINK_CONSTRUCTION_MAX = 60.0

RIBBON_OFFSET = 12.0  # offset par defaut (round 2), conserve pour compatibilite du module DP


class SkeletonGenerationError(RuntimeError):
    """Levee quand aucun arbre valide n'a ete trouve en MAX_TREE_ATTEMPTS tirages."""


class ContourOffsetError(SkeletonGenerationError):
    """Jointure concave du contour hors des deux segments decales adjacents.

    Signale une violation de halo (deux parties de l'arbre trop proches l'une
    de l'autre pour que le decalage standard reste valide a ce sommet) :
    volontairement explicite, jamais masquee par un clampage silencieux.
    Capturee par la boucle de rejet de ``_build_tree`` comme n'importe quel
    autre tirage invalide.
    """


# ----------------------------------------------------------------------
# Configuration dépendant de l'offset (décalage du contour)
# ----------------------------------------------------------------------

@dataclass(frozen=True)
class SkeletonConfig:
    offset: float
    halo_min_dist: float
    node_pitch: float
    node_count: int
    node_margin: float          # = position du premier noeud = marge de bord reelle
    min_leaf_branch_length: float
    subtree_length_range: tuple[float, float]


def _node_pitch(halo: float) -> float:
    """Plus petit entier PAIR strictement supérieur à ``halo`` (marge de sécurité)."""
    pitch = math.floor(halo) + 1
    if pitch % 2:
        pitch += 1
    return float(pitch)


def make_config(offset: float = RIBBON_OFFSET, avg_leaves: float = 2.5) -> SkeletonConfig:
    """Dérive tous les paramètres géométriques d'un offset de contour.

    - halo = 2·offset + 23 (inchangé) ; pas du réseau = halo arrondi au
      prochain entier pair (offset 12 -> halo 47 -> pas 48 ; offset 20 ->
      halo 63 -> pas 64, conforme aux exemples donnés).
    - marge de bord nécessaire = offset + demi-largeur de fairway max (par
      5, 18/2=9) ; les nœuds sont placés symétriquement, en gardant au
      moins cette marge ET au moins un demi-pas, des deux côtés de la
      carte.
    - budget d'arbre par sous-arbre = (longueur de contour visée par nine
      d'après ``PAR_SPECS`` moins les caps aux feuilles) / 2. Chaque
      feuille ajoute un cap d'arc ≈ π·offset ; ``avg_leaves`` (2,5, le
      milieu de la plage imposée 2-3) sert d'estimation représentative
      avant que le nombre réel de feuilles ne soit tiré.
    - longueur minimale d'une branche menant à une feuille : la plus
      grande valeur telle que le budget le plus bas de la plage puisse
      encore financer AU MOINS 2 feuilles, même avec le pire tirage de
      jitter (``BRANCH_JITTER``) sur chaque branche : si ce n'était pas
      garanti, 2-3 feuilles deviendraient parfois infaisables et
      ``_choose_leaf_plan`` n'aurait plus aucun plan valide à proposer.
    """
    halo = 2.0 * offset + HALO_MARGIN
    pitch = _node_pitch(halo)
    half_fairway_max = max(spec.width_max for spec in PAR_SPECS.values()) / 2.0
    margin_needed = offset + half_fairway_max
    node_margin = max(margin_needed, pitch / 2.0)
    node_count = 1
    while node_margin + node_count * pitch <= MAP_SIZE - margin_needed:
        node_count += 1

    contour_low = sum(PAR_SPECS[par].length_min for par in NINE_PAR_PATTERN) + 10 * LINK_CONSTRUCTION_MIN
    contour_high = sum(PAR_SPECS[par].length_max for par in NINE_PAR_PATTERN) + 10 * LINK_CONSTRUCTION_MAX
    caps = avg_leaves * math.pi * offset
    low = (contour_low - caps) / 2.0
    high = (contour_high - caps) / 2.0

    # Facteur 0,3 (pas 0,5) retenu empiriquement, pas seulement arithmetique :
    # meme une fois le budget correctement partage entre 2-3 feuilles, une
    # feuille peut encore se tronquer tres court quand le clubhouse tombe
    # pres d'un bord/coin de la grille grossiere (8x8 ou 6x6 selon l'offset :
    # un coin n'a que 3 voisins sur 8, dont 1 deja pris par le clubhouse et
    # souvent 1 par une autre feuille -- observe : une feuille a 0 arete
    # plantee, voir l'historique Git de ce round). Balayage empirique de ce
    # facteur sur les seeds 1-5 (voir le rapport) : 0,45 -> 3/5 seeds
    # aboutissent en <= 50 tirages, 0,35 -> 4/5, 0,3 -> 5/5 (et encore 5/5 a
    # 0,25-0,2, sans gain supplementaire) ; 0,3 est le plus grand facteur
    # (donc la plus grande longueur minimale, la plus proche de l'intention
    # initiale ~300 blocs) qui reste fiable.
    min_leaf = 0.3 * (low - pitch)
    min_leaf = max(min_leaf, 2.0 * pitch)  # jamais sous ~2 aretes, garde-fou de bon sens

    return SkeletonConfig(
        offset=offset, halo_min_dist=halo, node_pitch=pitch,
        node_count=node_count, node_margin=node_margin, min_leaf_branch_length=min_leaf,
        subtree_length_range=(low, high),
    )


DEFAULT_CONFIG = make_config(RIBBON_OFFSET)


# ----------------------------------------------------------------------
# Réseau de nœuds
# ----------------------------------------------------------------------

def node_to_world(config: SkeletonConfig, node: Node) -> Point:
    return (config.node_margin + node[0] * config.node_pitch, config.node_margin + node[1] * config.node_pitch)


def _in_grid(config: SkeletonConfig, node: Node) -> bool:
    return 0 <= node[0] < config.node_count and 0 <= node[1] < config.node_count


def _edge_length(config: SkeletonConfig, delta: Node) -> float:
    return config.node_pitch * math.hypot(delta[0], delta[1])


def _wrap_pi(angle: float) -> float:
    return (angle + math.pi) % (2.0 * math.pi) - math.pi


def all_nodes(config: SkeletonConfig) -> list[Node]:
    return [(x, y) for x in range(config.node_count) for y in range(config.node_count)]


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

    def add(self, config: SkeletonConfig, node: Node, parent_node: Node) -> None:
        edge = _edge_length(config, (node[0] - parent_node[0], node[1] - parent_node[1]))
        self.parent[node] = parent_node
        self.arclen[node] = self.arclen[parent_node] + edge
        self.children.setdefault(parent_node, []).append(node)
        self.children.setdefault(node, [])
        self.edges.append((parent_node, node))


def _halo_ok(config: SkeletonConfig, u: Node, v: Node, tree: TreeState) -> bool:
    """Halo général : toute arête existante sans nœud commun avec (u, v)

    doit être à distance segment-segment >= ``halo_min_dist``. Couvre à la
    fois les diagonales qui frôlent un nœud voisin et les diagonales qui se
    croisent, sans fenêtre « localement reliée » distincte.
    """
    world_u, world_v = node_to_world(config, u), node_to_world(config, v)
    for a, b in tree.edges:
        if a == u or a == v or b == u or b == v:
            continue
        if segment_distance(world_u, world_v, node_to_world(config, a), node_to_world(config, b)) < config.halo_min_dist:
            return False
    return True


# ----------------------------------------------------------------------
# Croissance : marche aléatoire biaisée « voyage » sur le réseau de nœuds
# ----------------------------------------------------------------------

def _walk_steps(config: SkeletonConfig, rng: random.Random, tree: TreeState, occupied: set[Node],
                start_node: Node, target_length: float, fallback_angle: float, clubhouse_world: Point,
                fixed_outward: bool = False):
    """Générateur : fait croître l'arbre depuis ``start_node``, une arête à la fois.

    Biais « voyage » : score = alignement avec le vecteur clubhouse->nœud
    courant (s'éloigne) tant que < 60% du budget, puis avec le vecteur
    nœud courant->clubhouse (revient) au-delà. ``fallback_angle`` lève
    l'ambiguïté au tout premier pas (ce vecteur est alors nul) et assure
    l'asymétrie seedée entre les deux sous-arbres.

    Tronque (s'arrête, sans retour arrière) dès qu'aucun nœud voisin n'est
    libre et conforme au halo — jamais d'exception ici, l'appelant décide
    si la longueur obtenue est suffisante.
    """
    current = start_node
    grown = 0.0
    last_delta: Node | None = None
    yield grown, [current]
    while grown < target_length:
        current_world = node_to_world(config, current)
        returning = grown >= 0.6 * target_length
        if returning:
            ref_vec = (clubhouse_world[0] - current_world[0], clubhouse_world[1] - current_world[1])
            ref_norm = math.hypot(*ref_vec)
            ref_unit = (ref_vec[0] / ref_norm, ref_vec[1] / ref_norm) if ref_norm > 1e-9 else (
                math.cos(fallback_angle), math.sin(fallback_angle)
            )
        elif fixed_outward:
            # Direction fixe (feuille d'un eventail) : contrairement au vecteur
            # clubhouse->courant utilise par la tige, ce biais reste identique
            # tout au long de la phase de depart meme si le noeud de depart
            # (le point de fourche) est deja a une certaine distance du
            # clubhouse -- sinon deux feuilles parties du meme point de
            # fourche suivent quasiment le meme vecteur position-relative et
            # se bloquent mutuellement par halo des les premiers pas (constate
            # : 2e feuille tronquee a 2 aretes sur l'historique Git de ce
            # round).
            ref_unit = (math.cos(fallback_angle), math.sin(fallback_angle))
        else:
            ref_vec = (current_world[0] - clubhouse_world[0], current_world[1] - clubhouse_world[1])
            ref_norm = math.hypot(*ref_vec)
            ref_unit = (ref_vec[0] / ref_norm, ref_vec[1] / ref_norm) if ref_norm > 1e-9 else (
                math.cos(fallback_angle), math.sin(fallback_angle)
            )

        candidates = []
        for delta in NEIGHBOR_DELTAS:
            if last_delta is not None and delta == (-last_delta[0], -last_delta[1]):
                continue  # jamais de retour arriere strict sur le pas precedent
            candidate = (current[0] + delta[0], current[1] + delta[1])
            if not _in_grid(config, candidate) or candidate in occupied:
                continue
            if not _halo_ok(config, current, candidate, tree):
                continue
            edge_len = _edge_length(config, delta)
            candidate_world = node_to_world(config, candidate)
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

        tree.add(config, chosen, current)
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


# ----------------------------------------------------------------------
# Construction d'un sous-arbre complet (tronc + branches), pas à pas
# ----------------------------------------------------------------------

def _choose_leaf_plan(rng: random.Random, target_length: float, min_leaf: float,
                      stem_estimate: float) -> tuple[int, list[float]]:
    """2 ou 3 feuilles (jamais 1) : voir ``make_config`` pour la garantie de faisabilité.

    Le budget restant après la tige (``stem_estimate``, environ un pas de
    grille, voir ``_grow_subtree_steps``) est réparti entre les feuilles
    avec une légère variation aléatoire, chacune plafonnée au minimum à
    ``min_leaf``. Cette répartition n'a pas besoin d'être exacte : la
    longueur totale réellement atteinte (après troncature éventuelle de
    chaque branche) est vérifiée a posteriori contre la fenêtre de budget.
    """
    remaining = max(min_leaf, target_length - stem_estimate)
    max_leaves = 2
    if remaining >= 3.0 * min_leaf:
        max_leaves = 3
    num_leaves = rng.randint(2, max_leaves)
    shares = [rng.uniform(0.8, 1.2) for _ in range(num_leaves)]
    total_share = sum(shares)
    targets = [max(min_leaf, remaining * share / total_share) for share in shares]
    return num_leaves, targets


def _grow_subtree_steps(config: SkeletonConfig, rng: random.Random, tree: TreeState,
                        occupied: set[Node], clubhouse: Node, root: Node,
                        target_length: float, min_leaf: float, clubhouse_world: Point, result: dict):
    """Générateur : fait pousser 2 ou 3 feuilles en éventail depuis ``root``.

    ``root`` (la tige, une arête depuis le clubhouse) est déjà plantée par
    l'appelant (``_plant_opposed_stems``), de façon à être aussi opposée
    que possible à la tige de l'AUTRE sous-arbre. Round précédent (bug) :
    la branche secondaire cherchait un point sur le TRONC DÉJÀ COMPLET,
    dans une fenêtre ``[pas, longueur_tronc - min_leaf]`` — souvent
    introuvable, le tronc étant lui-même tronqué (halo) bien avant sa
    cible. Ici, chaque feuille pousse indépendamment depuis ``root``, avec
    son propre budget — aucune recherche de point de greffe après coup.

    Pour que l'appelant puisse entrelacer les feuilles avec celles de
    l'AUTRE sous-arbre, ce générateur est consommé une arête à la fois. Le
    résultat final est déposé dans ``result`` (``ok``, ``root``, ``leaves``,
    ``total``) une fois le générateur épuisé.
    """
    num_leaves, targets = _choose_leaf_plan(rng, target_length, min_leaf, config.node_pitch)
    result["num_leaves_planned"] = num_leaves
    fork_point = root
    leaves = []
    # Angles de depart repartis autour d'un eventail FACE A LA TIGE (pas
    # autour du cercle complet) : deux feuilles tirees au hasard peuvent
    # demarrer dans des directions proches, et la premiere bloque alors
    # tres vite la seconde par halo (constate : 2e feuille tronquee a ~100
    # blocs sur un budget de 460, voir l'historique Git de ce round). Fixer
    # l'eventail dans le prolongement de la tige (la direction
    # clubhouse->point de fourche), plutot qu'un tirage a 360 degres,
    # evite en plus qu'une feuille reparte vers le clubhouse ou le
    # territoire de l'autre sous-arbre des le depart.
    stem_angle = math.atan2(fork_point[1] - clubhouse[1], fork_point[0] - clubhouse[0])
    fan_span = math.radians(170.0)
    base_angle = stem_angle - fan_span / 2.0 + rng.uniform(-0.1, 0.1)
    fan_step = fan_span / max(1, len(targets) - 1) if len(targets) > 1 else 0.0
    for index, leaf_target in enumerate(targets):
        fan_angle = base_angle + index * fan_step + rng.uniform(-0.15, 0.15)
        leaf_state = (0.0, [fork_point])
        for leaf_state in _walk_steps(config, rng, tree, occupied, fork_point, leaf_target,
                                      fan_angle, clubhouse_world, fixed_outward=True):
            yield
        leaf_grown, leaf_path = leaf_state
        if leaf_grown < min_leaf:
            result["ok"] = False
            return
        leaves.append(leaf_path[-1])
    if len(leaves) < 2 or len(leaves) > MAX_LEAVES_PER_SUBTREE:
        result["ok"] = False
        return
    total = tree.arclen[root] + _subtree_total_length(tree, root)
    result.update(ok=True, root=root, leaves=leaves, total=total)


def _plant_opposed_stems(config: SkeletonConfig, tree: TreeState, occupied: set[Node],
                         clubhouse: Node, front_angle: float, back_angle: float) -> tuple[Node, Node] | None:
    """Plante les deux premières arêtes (tiges), en forçant front et back à des

    directions aussi opposées que possible l'une de l'autre — pas seulement
    chacune alignée indépendamment sur son propre angle : deux tiges tirées
    indépendamment peuvent atterrir sur des nœuds adjacents (à peine plus
    que le halo l'un de l'autre), et toute la ramification suivante se
    bloque alors par halo dès les premiers pas (constaté, voir l'historique
    Git de ce round : une feuille à 0 arête plantée). ``None`` si le
    clubhouse n'a aucun voisin libre (bord de grille très contraint).
    """
    clubhouse_world = node_to_world(config, clubhouse)

    def ranked(angle: float) -> list[tuple[float, Node, Point]]:
        ref = (math.cos(angle), math.sin(angle))
        options = []
        for delta in NEIGHBOR_DELTAS:
            candidate = (clubhouse[0] + delta[0], clubhouse[1] + delta[1])
            if not _in_grid(config, candidate) or candidate in occupied:
                continue
            edge_len = _edge_length(config, delta)
            candidate_world = node_to_world(config, candidate)
            direction = ((candidate_world[0] - clubhouse_world[0]) / edge_len,
                        (candidate_world[1] - clubhouse_world[1]) / edge_len)
            score = direction[0] * ref[0] + direction[1] * ref[1]
            options.append((score, candidate, direction))
        options.sort(key=lambda item: -item[0])
        return options

    front_options = ranked(front_angle)
    if not front_options:
        return None
    front_node, front_dir = front_options[0][1], front_options[0][2]
    tree.add(config, front_node, clubhouse)
    occupied.add(front_node)

    back_options = [option for option in ranked(back_angle) if option[1] != front_node]
    if not back_options:
        return None
    # Parmi les candidats valides pour back_angle, prefere le plus OPPOSE a
    # front_dir (produit scalaire le plus negatif), pas seulement le mieux
    # aligne sur back_angle individuellement.
    back_options.sort(key=lambda item: item[2][0] * front_dir[0] + item[2][1] * front_dir[1])
    back_node = back_options[0][1]
    tree.add(config, back_node, clubhouse)
    occupied.add(back_node)
    return front_node, back_node


def _grow_both_alternating(config: SkeletonConfig, rng: random.Random, tree: TreeState,
                           occupied: set[Node], clubhouse: Node, front_angle: float, back_angle: float,
                           front_target: float, back_target: float, min_leaf: float,
                           clubhouse_world: Point) -> tuple[dict, dict]:
    """Plante les deux tiges (opposées), puis entrelace la croissance des feuilles.

    Les deux sous-arbres partagent le même état (``tree``, ``occupied``) :
    chaque arête ajoutée par l'un est immédiatement visible du halo de
    l'autre. Les feuilles (pas seulement les tiges) sont entrelacées ici.
    """
    front_result: dict = {}
    back_result: dict = {}
    stems = _plant_opposed_stems(config, tree, occupied, clubhouse, front_angle, back_angle)
    if stems is None:
        return front_result, back_result  # ni l'un ni l'autre "ok" (cle absente) : tirage retire
    front_root, back_root = stems
    gen_front = _grow_subtree_steps(config, rng, tree, occupied, clubhouse, front_root,
                                    front_target, min_leaf, clubhouse_world, front_result)
    gen_back = _grow_subtree_steps(config, rng, tree, occupied, clubhouse, back_root,
                                   back_target, min_leaf, clubhouse_world, back_result)
    front_done = back_done = False
    while not (front_done and back_done):
        if not front_done:
            try:
                next(gen_front)
            except StopIteration:
                front_done = True
        if not back_done:
            try:
                next(gen_back)
            except StopIteration:
                back_done = True
    return front_result, back_result


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


def _build_tree(seed: int, config: SkeletonConfig = DEFAULT_CONFIG) -> tuple[_BuildOutcome, int]:
    """Boucle de rejet bornée (``MAX_TREE_ATTEMPTS``).

    Un tirage n'est accepté que si les deux sous-arbres : atteignent 2 ou 3
    feuilles, respectent la longueur minimale de branche, tombent dans leur
    fenêtre de budget (``config.subtree_length_range``, avec une tolérance
    haute d'un pas de grille pour le dernier pas qui peut dépasser
    légèrement la cible) ET produisent, une fois DÉCALÉ COMME UN TOUT
    (``_combined_tour_with_owners`` + ``build_contour``, pas deux contours
    indépendants), un contour combiné fermé et simple — un échec à
    n'importe laquelle de ces étapes retire le tirage entier (pas de retour
    arrière interne).
    """
    low, high = config.subtree_length_range
    for attempt in range(MAX_TREE_ATTEMPTS):
        rng = random.Random(f"elastic_routing_skeleton:{config.offset}:{seed}:{attempt}")
        clubhouse = rng.choice(all_nodes(config))
        clubhouse_world = node_to_world(config, clubhouse)
        tree = TreeState()
        tree.add_root(clubhouse)
        occupied = {clubhouse}

        front_angle = rng.uniform(0.0, 2.0 * math.pi)
        back_angle = front_angle + math.pi + rng.uniform(-0.6, 0.6)
        front_target = rng.uniform(low, high)
        back_target = rng.uniform(low, high)

        front_result, back_result = _grow_both_alternating(
            config, rng, tree, occupied, clubhouse, front_angle, back_angle,
            front_target, back_target, config.min_leaf_branch_length, clubhouse_world,
        )
        if not front_result.get("ok") or not back_result.get("ok"):
            continue
        front_total, back_total = front_result["total"], back_result["total"]
        if not (low <= front_total <= high + config.node_pitch):
            continue
        if not (low <= back_total <= high + config.node_pitch):
            continue

        front_root, back_root = front_result["root"], back_result["root"]
        combined_nodes, combined_owners = _combined_tour_with_owners(
            tree, clubhouse, front_root, back_root, config,
        )
        try:
            combined_contour, point_owners = build_contour(config, combined_nodes, owners=combined_owners)
        except ContourOffsetError:
            # Violation de halo locale au decalage (jointure concave hors
            # segment) : rejet du tirage, comme tout autre echec geometrique
            # de cette boucle -- pas une exception qui doit remonter a l'appelant.
            continue
        # Un seul contour COMBINE (les deux sous-arbres, via le clubhouse
        # commun) verifie ici : garantit a la fois qu'aucun des deux arcs ne
        # se recoupe lui-meme ET qu'ils ne se recoupent pas l'un l'autre
        # (round precedent, bug : deux contours independants, chacun simple
        # sur lui-meme, mais se recoupant l'un l'autre pres du clubhouse --
        # is_simple_polyline(front)/is_simple_polyline(back) ne pouvait pas
        # le detecter).
        if not is_simple_polyline(combined_contour):
            continue
        front_contour = [p for p, owner in zip(combined_contour, point_owners) if owner == "front"]
        back_contour = [p for p, owner in zip(combined_contour, point_owners) if owner == "back"]

        skeleton = Skeleton(clubhouse, tree, front_root, back_root, tuple(front_result["leaves"]),
                            tuple(back_result["leaves"]), front_total, back_total)
        return _BuildOutcome(skeleton, front_contour, back_contour), attempt + 1
    raise SkeletonGenerationError(
        f"aucun arbre valide apres {MAX_TREE_ATTEMPTS} tirages derives (seed={seed}, offset={config.offset})"
    )


# ----------------------------------------------------------------------
# Tour (à la manière d'un tour d'Euler) et contour décalé — FERMÉ
# ----------------------------------------------------------------------

def _angle_between(a: Point, b: Point) -> float:
    return math.atan2(b[1] - a[1], b[0] - a[0])


def _tour_nodes(config: SkeletonConfig, node: Node, parent: Node | None, tree: TreeState) -> list[Node]:
    kids = [c for c in tree.children.get(node, ()) if c != parent]
    if not kids:
        return [node]
    node_world = node_to_world(config, node)
    if parent is not None:
        ref = _angle_between(node_world, node_to_world(config, parent))
    else:
        ref = 0.0
    # Ordre de visite des enfants a une fourche : doit etre coherent avec le
    # sens du decalage (a gauche du sens de marche, cf. build_contour) pour
    # que le contour ne se recoupe pas en X au point de fourche (constate :
    # ordre croissant -> figure en huit, voir l'historique Git de ce round).
    # L'ordre decroissant (horaire depuis la reference) est le bon sens.
    kids_sorted = sorted(
        kids,
        key=lambda k: -((_angle_between(node_world, node_to_world(config, k)) - ref) % (2.0 * math.pi)),
    )
    sequence = [node]
    for kid in kids_sorted:
        sequence.append(kid)
        sub = _tour_nodes(config, kid, node, tree)
        sequence.extend(sub[1:])
        sequence.append(node)
    return sequence


def _full_tour(root_child: Node, tree: TreeState, clubhouse: Node,
              config: SkeletonConfig = DEFAULT_CONFIG) -> list[Node]:
    """Tour clubhouse -> ... -> clubhouse pour le sous-arbre débutant à ``root_child``."""
    return [clubhouse] + _tour_nodes(config, root_child, clubhouse, tree) + [clubhouse]


def _combined_tour_with_owners(tree: TreeState, clubhouse: Node, front_root: Node,
                               back_root: Node, config: SkeletonConfig) -> tuple[list[Node], list[str]]:
    """Tour COMBINÉ clubhouse -> (front) -> clubhouse -> (back) -> clubhouse.

    Un seul tour cyclique pour les DEUX sous-arbres, au lieu de deux tours
    indépendants chacun refermé par un cap au clubhouse (round précédent,
    bug) : au clubhouse, ``prev`` (dernier nœud du sous-arbre précédent) et
    ``nxt`` (racine du sous-arbre suivant) sont alors deux nœuds DIFFÉRENTS
    — jamais un demi-tour — donc ``build_contour`` n'y crée plus jamais de
    cap indépendant par sous-arbre. Le round précédent décalait chaque
    sous-arbre séparément avec son propre cap au clubhouse ; les deux caps
    (chacun bulgant vers le sous-arbre opposé, les deux tiges étant plantées
    à ~180° l'une de l'autre par construction, voir ``_plant_opposed_stems``)
    se recoupaient systématiquement près du clubhouse — constaté sur
    100/100 tirages (seeds 1-50 x offsets 12/20), pas un cas rare.

    Retourne les nœuds (CYCLE FERMÉ, ``nodes[0] == nodes[-1]``, même
    convention que ``_full_tour``) et un tag parallèle ``'front'``/``'back'``
    par nœud (même longueur), utilisé par l'appelant pour redécouper le
    contour combiné décalé en ``front_contour``/``back_contour`` après coup.
    """
    front_seq = _tour_nodes(config, front_root, clubhouse, tree)
    back_seq = _tour_nodes(config, back_root, clubhouse, tree)
    nodes = [clubhouse] + front_seq + [clubhouse] + back_seq + [clubhouse]
    owners = (["front"] * (1 + len(front_seq))
              + ["back"] * (1 + len(back_seq))
              + ["front"])  # dernier element (duplicata de fermeture) : trim par build_contour
    return nodes, owners


def _point_to_segment_distance(point: Point, a: Point, b: Point) -> float:
    dx, dy = b[0] - a[0], b[1] - a[1]
    length_sq = dx * dx + dy * dy
    if length_sq <= 1e-12:
        return math.dist(point, a)
    ratio = max(0.0, min(1.0, ((point[0] - a[0]) * dx + (point[1] - a[1]) * dy) / length_sq))
    return math.dist(point, (a[0] + ratio * dx, a[1] + ratio * dy))


def _simplify_tour_points(points: list[Point], epsilon: float = 6.0,
                          tags: list | None = None):
    """Douglas-Peucker itératif : fusionne les points quasi colinéaires.

    Les deux extrémités (identiques : le clubhouse) sont toujours
    conservées. Implémentation itérative (pas de récursion).

    Si ``tags`` est fourni (même longueur que ``points``), retourne aussi
    la liste des tags conservés avec le même masque de filtrage :
    ``(points, tags)``. Sinon, retourne seulement la liste de points
    (comportement historique).
    """
    n = len(points)
    if n < 3:
        return (list(points), list(tags)) if tags is not None else list(points)
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
    kept_points = [point for point, kept in zip(points, keep) if kept]
    if tags is not None:
        kept_tags = [tag for tag, kept in zip(tags, keep) if kept]
        return kept_points, kept_tags
    return kept_points


CONCAVE_JOIN_EPS = 1e-6  # tolerance sur le parametre [0, 1] d'un segment decale


def build_contour(config: SkeletonConfig, tour_nodes: list[Node], owners: list | None = None):
    """Décale le tour (FERMÉ) d'un côté courant (la main gauche du sens de marche).

    Décalage de polyligne standard, sommet par sommet, SANS lissage
    préalable de la ligne centrale (abandonné : devenu inutile une fois le
    décalage traité correctement à chaque sommet, voir plus bas — un
    lissage préalable risquait lui-même de recouper les segments
    adjacents). À chaque sommet du tour :

    - côté CONVEXE (le tour tourne à droite dans le sens de la marche, pour
      un décalage à gauche) : jointure ronde, arc de rayon ``offset`` centré
      sur le sommet, pas angulaire <= ``MAX_ARC_STEP_DEG`` ;
    - côté CONCAVE (le tour tourne à gauche) : intersection des deux
      segments adjacents décalés. Le paramètre de l'intersection est vérifié
      dans les DEUX segments (pas seulement sur les droites infinies) ;
      hors de ces bornes, ``ContourOffsetError`` est levée explicitement
      (violation de halo : deux parties de l'arbre trop proches pour ce
      sommet), jamais masquée par un clampage silencieux.

    Une feuille est un demi-tour EXACT (le nœud suivant et le nœud précédent
    du tour sont le MÊME nœud, traversé dans les deux sens) : ``v1`` et
    ``v2`` y sont alors des vecteurs exactement opposés, donc le signe du
    virage calculé par ``atan2`` sur un produit vectoriel nul n'est qu'un
    artefact de convention flottante, PAS une classification convexe/concave
    valide (classer par signe seul y envoie à tort côté concave, avec des
    segments décalés strictement parallèles — échec systématique, voir
    historique Git). Ce cas est donc détecté par égalité EXACTE de point
    (``prev == nxt``), pas par un seuil d'angle, et toujours traité côté
    convexe : la jointure ronde y produit alors directement un cap en
    demi-cercle, sans cas particulier. Le clubhouse n'est PLUS un cas de ce
    genre : quand ``tour_nodes`` est le tour COMBINÉ des deux sous-arbres
    (``_combined_tour_with_owners``), le clubhouse y est un sommet ORDINAIRE
    à deux arêtes distinctes (prev = dernier nœud du sous-arbre précédent,
    nxt = racine du sous-arbre suivant, deux nœuds différents) — jamais un
    demi-tour. Round précédent (bug) : chaque sous-arbre était décalé
    indépendamment, avec son propre cap au clubhouse ; les deux caps, l'un
    bulgant vers l'autre sous-arbre (tiges front/back à ~180° l'une de
    l'autre par construction), se recoupaient systématiquement près du
    clubhouse (constaté sur 100/100 tirages seeds 1-50 x offsets 12/20, pas
    seulement un cas rare — voir historique Git).

    Si ``owners`` est fourni (même longueur que ``tour_nodes``, un tag par
    sommet source, typiquement ``'front'``/``'back'``), retourne aussi la
    liste des propriétaires du contour généré (un tag par point émis, celui
    du sommet source) : ``(contour, point_owners)``. Sinon, retourne
    seulement la liste de points (comportement historique).

    Boucle cyclique (modulo) : le contour retourné est un polygone fermé
    (pas de point de fermeture dupliqué, le dernier segment revient au
    premier point).
    """
    raw = [node_to_world(config, n) for n in tour_nodes]
    if owners is not None:
        assert len(owners) == len(tour_nodes)
        simplified_points, simplified_owners = _simplify_tour_points(raw, tags=owners)
        base = simplified_points[:-1]
        base_owners = simplified_owners[:-1]
    else:
        base = _simplify_tour_points(raw)[:-1]
        base_owners = None
    m = len(base)
    if m < 2:
        return ([], []) if owners is not None else []
    radius = config.offset

    contour: list[Point] = []
    contour_owners: list = []
    for i in range(m):
        _emitted_before = len(contour)
        prev, here, nxt = base[i - 1], base[i], base[(i + 1) % m]
        d1, d2 = math.dist(prev, here), math.dist(here, nxt)
        if d1 < 1e-9 or d2 < 1e-9:
            continue
        v1 = ((here[0] - prev[0]) / d1, (here[1] - prev[1]) / d1)
        v2 = ((nxt[0] - here[0]) / d2, (nxt[1] - here[1]) / d2)
        n1 = (-v1[1], v1[0])
        n2 = (-v2[1], v2[0])
        turn = math.atan2(v1[0] * v2[1] - v1[1] * v2[0], v1[0] * v2[0] + v1[1] * v2[1])
        turn_deg = math.degrees(turn)

        if abs(turn_deg) < 1e-9:
            # Colineaire (ne devrait plus guere survenir apres simplification).
            contour.append((here[0] + radius * n2[0], here[1] + radius * n2[1]))
            if base_owners is not None:
                contour_owners.extend([base_owners[i]] * (len(contour) - _emitted_before))
            continue

        # Cap (feuille, jamais le clubhouse depuis que ``tour_nodes`` est le
        # tour COMBINÉ des deux sous-arbres) : demi-tour EXACT, prev et nxt
        # sont le MEME noeud (traverse dans les deux sens) -- detecte par
        # egalite exacte de point, pas par un seuil d'angle (voir docstring).
        # Toujours traite cote convexe, la jointure ronde produit alors
        # directement un cap en demi-cercle.
        if prev == nxt or turn < 0.0:
            # Cote convexe.
            contour.append((here[0] + radius * n1[0], here[1] + radius * n1[1]))
            contour.extend(_corner_arc(here, n1, n2, radius))
            if base_owners is not None:
                contour_owners.extend([base_owners[i]] * (len(contour) - _emitted_before))
            continue

        # Cote concave : intersection des deux segments adjacents decales
        # (translation du segment reel le long de sa propre normale).
        a1 = (prev[0] + radius * n1[0], prev[1] + radius * n1[1])
        a2 = (here[0] + radius * n1[0], here[1] + radius * n1[1])
        b1 = (here[0] + radius * n2[0], here[1] + radius * n2[1])
        b2 = (nxt[0] + radius * n2[0], nxt[1] + radius * n2[1])
        da = (a2[0] - a1[0], a2[1] - a1[1])
        db = (b2[0] - b1[0], b2[1] - b1[1])
        denom = da[0] * db[1] - da[1] * db[0]
        if abs(denom) < 1e-9:
            raise ContourOffsetError(
                f"segments decales paralleles au sommet {here} (virage {turn_deg:.1f} deg)"
            )
        diff = (b1[0] - a1[0], b1[1] - a1[1])
        t = (diff[0] * db[1] - diff[1] * db[0]) / denom
        s = (diff[0] * da[1] - diff[1] * da[0]) / denom
        if not (-CONCAVE_JOIN_EPS <= t <= 1.0 + CONCAVE_JOIN_EPS
                and -CONCAVE_JOIN_EPS <= s <= 1.0 + CONCAVE_JOIN_EPS):
            raise ContourOffsetError(
                f"intersection hors segment au sommet {here} (t={t:.3f}, s={s:.3f}, "
                f"virage {turn_deg:.1f} deg)"
            )
        contour.append((a1[0] + t * da[0], a1[1] + t * da[1]))
        if base_owners is not None:
            contour_owners.extend([base_owners[i]] * (len(contour) - _emitted_before))
    if owners is not None:
        return contour, contour_owners
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
    """Vérifie numériquement qu'un contour FERMÉ (cycle, pas de point dupliqué)

    ne se croise pas lui-même. Deux segments qui partagent un sommet
    (y compris le dernier et le premier, via le bouclage) sont exemptés.
    """
    n = len(points)
    if n < 3:
        return True
    segments = [(points[i], points[(i + 1) % n]) for i in range(n)]
    for i in range(n):
        for j in range(i + 1, n):
            if j == i + 1 or (i == 0 and j == n - 1):
                continue  # segments adjacents (sommet partagé, via le bouclage)
            if segments_intersect(*segments[i], *segments[j]):
                return False
    return True


# ----------------------------------------------------------------------
# Orchestration
# ----------------------------------------------------------------------

@dataclass(frozen=True)
class SkeletonResult:
    seed: int
    offset: float
    clubhouse: Node
    skeleton: Skeleton
    front_contour: tuple[Point, ...]
    back_contour: tuple[Point, ...]
    elapsed_seconds: float
    attempts_used: int
    config: SkeletonConfig


def build_skeleton(seed: int, offset: float = RIBBON_OFFSET) -> SkeletonResult:
    config = make_config(offset)
    start = time.perf_counter()
    outcome, attempts_used = _build_tree(seed, config)
    elapsed = time.perf_counter() - start
    return SkeletonResult(
        seed=seed,
        offset=offset,
        clubhouse=outcome.skeleton.clubhouse,
        skeleton=outcome.skeleton,
        front_contour=tuple(outcome.front_contour),
        back_contour=tuple(outcome.back_contour),
        elapsed_seconds=elapsed,
        attempts_used=attempts_used,
        config=config,
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
    config = result.config
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

    for node in all_nodes(config):
        p = point(node_to_world(config, node))
        out.append(f'<circle cx="{p[0]:.1f}" cy="{p[1]:.1f}" r="1.0" fill="#3b4049"/>')

    for root, color in ((skeleton.front_root, "#58a6ff"), (skeleton.back_root, "#f2cc60")):
        for node in _subtree_nodes(skeleton.tree, root):
            p = point(node_to_world(config, node))
            out.append(f'<circle cx="{p[0]:.1f}" cy="{p[1]:.1f}" r="2.6" fill="{color}" fill-opacity="0.85"/>')
    for a, b in skeleton.tree.edges:
        pa, pb = point(node_to_world(config, a)), point(node_to_world(config, b))
        out.append(f'<line x1="{pa[0]:.1f}" y1="{pa[1]:.1f}" x2="{pb[0]:.1f}" y2="{pb[1]:.1f}" '
                   'stroke="#8b949e" stroke-width="1.0" stroke-opacity="0.6"/>')

    # polyline (PAS polygon) : front_contour/back_contour sont désormais des
    # ARCS OUVERTS clubhouse -> clubhouse (deux arcs d'un unique contour
    # combiné, coupés aux deux passages au clubhouse), pas deux boucles
    # indépendantes — fermer chacun en polygon dessinerait une corde parasite
    # entre ses deux extrémités, qui ne sont pas censées se relier directement
    # l'une à l'autre (chacune se raccorde à l'extrémité de l'AUTRE arc).
    for contour, color in ((result.front_contour, "#58a6ff"), (result.back_contour, "#f2cc60")):
        path = " ".join(f"{point(p)[0]:.1f},{point(p)[1]:.1f}" for p in contour)
        out.append(f'<polyline points="{path}" fill="none" stroke="{color}" stroke-width="1.4" stroke-opacity="0.9"/>')

    clubhouse = point(node_to_world(config, result.clubhouse))
    out.append(
        f'<circle cx="{clubhouse[0]:.1f}" cy="{clubhouse[1]:.1f}" r="6" fill="#f0f6fc" stroke="#8b949e"/>'
    )
    out.extend([
        (f'<text x="{padding}" y="{size + 24}" font-size="14">seed {result.seed} · offset '
         f'{result.offset:g} · clubhouse {result.clubhouse} · {result.attempts_used} tirage(s) · '
         f'{result.elapsed_seconds * 1000:.0f} ms</text>'),
        (f'<text x="{padding}" y="{size + 44}" font-size="12">bleu=front '
         f'({len(skeleton.front_leaves)} feuilles, {skeleton.front_length:.0f} blocs) · jaune=back '
         f'({len(skeleton.back_leaves)} feuilles, {skeleton.back_length:.0f} blocs) · '
         'blanc=clubhouse</text>'),
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
