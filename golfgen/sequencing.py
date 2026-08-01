"""Séquençage (étape 3) : ordre de jeu 1..n + sens (tee/green) de chaque trou.

Les squelettes sont déjà placés (golfgen/packing.py) — leurs deux extrémités
sont fixes dans le monde. Retourner un trou est donc gratuit : aucun champ
directionnel n'existe encore sur HoleShape (pas de bunker, pas de tee
multiple), donc "retourner" un trou, c'est juste échanger les labels
tee/green et inverser l'ordre de la liste de waypoints — pas de recalcul
géométrique.
"""

from __future__ import annotations

import math

from golfgen.config import CourseConfig
from golfgen.packing import PlacedPiece
from golfgen.utils import distance

TEE1_WEIGHT = 3.0
TURN_WEIGHT = 3.0
FINISH_WEIGHT = 3.0
PAR_BALANCE_WEIGHT = 0.05

MAX_LOCAL_SEARCH_PASSES = 50


def _tee(piece: PlacedPiece, flipped: bool) -> tuple[float, float]:
    return piece.endpoint_b if flipped else piece.endpoint_a


def _green(piece: PlacedPiece, flipped: bool) -> tuple[float, float]:
    return piece.endpoint_a if flipped else piece.endpoint_b


def ordered_waypoints(piece: PlacedPiece, flipped: bool) -> list[tuple[float, float]]:
    """Liste des waypoints dans l'ordre de jeu (tee -> green)."""
    return list(reversed(piece.waypoints_ab)) if flipped else piece.waypoints_ab


def tour_cost(order: list[int], flips: list[bool], pieces: list[PlacedPiece],
              clubhouse_pos: tuple[float, float], config: CourseConfig) -> float:
    """Coût d'une tournée : transitions green->tee + ancrages clubhouse (1er
    tee, tour du 9e green, dernier green) + équilibre des pars front/back."""
    n = len(order)
    total = 0.0
    for i in range(n - 1):
        a, b = pieces[order[i]], pieces[order[i + 1]]
        total += distance(_green(a, flips[order[i]]), _tee(b, flips[order[i + 1]]))

    first = pieces[order[0]]
    total += TEE1_WEIGHT * distance(_tee(first, flips[order[0]]), clubhouse_pos)

    if n >= 4 and n % 2 == 0:
        turn_idx = n // 2 - 1
        turn_piece = pieces[order[turn_idx]]
        total += TURN_WEIGHT * distance(_green(turn_piece, flips[order[turn_idx]]), clubhouse_pos)

    last = pieces[order[-1]]
    total += FINISH_WEIGHT * distance(_green(last, flips[order[-1]]), clubhouse_pos)

    mid = n // 2
    front_par = sum(pieces[order[i]].shape.par for i in range(mid))
    back_par = sum(pieces[order[i]].shape.par for i in range(mid, n))
    total += PAR_BALANCE_WEIGHT * (front_par - back_par) ** 2

    return total


def nearest_neighbor_construct(pieces: list[PlacedPiece],
                                clubhouse_pos: tuple[float, float]) -> tuple[list[int], list[bool]]:
    """Construction gloutonne : démarre par le (trou, sens) le plus proche du
    clubhouse, puis enchaîne toujours le (trou restant, sens) le plus proche
    du green courant."""
    n = len(pieces)
    flips = [False] * n

    best_start, best_dist = None, float("inf")
    for i in range(n):
        for flip in (False, True):
            d = distance(_tee(pieces[i], flip), clubhouse_pos)
            if d < best_dist:
                best_dist, best_start = d, (i, flip)

    start_i, start_flip = best_start
    order = [start_i]
    flips[start_i] = start_flip
    remaining = set(range(n)) - {start_i}
    current_green = _green(pieces[start_i], start_flip)

    while remaining:
        best_next, best_dist = None, float("inf")
        for i in remaining:
            for flip in (False, True):
                d = distance(current_green, _tee(pieces[i], flip))
                if d < best_dist:
                    best_dist, best_next = d, (i, flip)
        i, flip = best_next
        order.append(i)
        flips[i] = flip
        remaining.remove(i)
        current_green = _green(pieces[i], flip)

    return order, flips


def _two_opt_move(order: list[int], flips: list[bool], i: int, j: int) -> tuple[list[int], list[bool]]:
    """Renverse le sous-chemin order[i+1..j] ; parcourir un trou à l'envers
    échange son tee et son green, donc son bit de sens s'inverse aussi."""
    new_order = order[:i + 1] + list(reversed(order[i + 1:j + 1])) + order[j + 1:]
    new_flips = list(flips)
    for k in order[i + 1:j + 1]:
        new_flips[k] = not flips[k]
    return new_order, new_flips


def local_search(order: list[int], flips: list[bool], pieces: list[PlacedPiece],
                  clubhouse_pos: tuple[float, float], config: CourseConfig,
                  max_passes: int = MAX_LOCAL_SEARCH_PASSES) -> tuple[list[int], list[bool]]:
    """Passes 2-opt + Or-opt + flip isolé, premier-amélioration, jusqu'à
    convergence. n est petit (<=18) donc un recalcul complet du coût à
    chaque candidat reste trivial — pas de bookkeeping incrémental."""
    order = list(order)
    flips = list(flips)
    n = len(order)
    best_cost = tour_cost(order, flips, pieces, clubhouse_pos, config)

    for _ in range(max_passes):
        improved = False

        for i in range(n - 1):
            for j in range(i + 1, n):
                cand_order, cand_flips = _two_opt_move(order, flips, i, j)
                cost = tour_cost(cand_order, cand_flips, pieces, clubhouse_pos, config)
                if cost < best_cost - 1e-9:
                    order, flips, best_cost = cand_order, cand_flips, cost
                    improved = True

        for block_len in (1, 2, 3):
            for start in range(n - block_len + 1):
                block = order[start:start + block_len]
                rest = order[:start] + order[start + block_len:]
                for insert_at in range(len(rest) + 1):
                    if insert_at == start:
                        continue
                    cand_order = rest[:insert_at] + block + rest[insert_at:]
                    cost = tour_cost(cand_order, flips, pieces, clubhouse_pos, config)
                    if cost < best_cost - 1e-9:
                        order, best_cost = cand_order, cost
                        improved = True

        for idx in range(n):
            cand_flips = list(flips)
            cand_flips[idx] = not cand_flips[idx]
            cost = tour_cost(order, cand_flips, pieces, clubhouse_pos, config)
            if cost < best_cost - 1e-9:
                flips, best_cost = cand_flips, cost
                improved = True

        if not improved:
            break

    return order, flips


def _open_chain_cost(order: list[int], flips: dict[int, bool], pieces: list[PlacedPiece],
                      start_point: tuple[float, float], end_point: tuple[float, float]) -> float:
    """Coût d'un chemin ouvert entre deux points fixes (pas des trous) —
    utilisé pour ordonner les pièces intérieures entre deux ancres."""
    if not order:
        return distance(start_point, end_point)
    total = distance(start_point, _tee(pieces[order[0]], flips[order[0]]))
    for i in range(len(order) - 1):
        a, b = pieces[order[i]], pieces[order[i + 1]]
        total += distance(_green(a, flips[order[i]]), _tee(b, flips[order[i + 1]]))
    total += distance(_green(pieces[order[-1]], flips[order[-1]]), end_point)
    return total


def _nn_open_chain(indices: list[int], start_point: tuple[float, float],
                    pieces: list[PlacedPiece]) -> tuple[list[int], dict[int, bool]]:
    remaining = set(indices)
    order: list[int] = []
    flips: dict[int, bool] = {}
    current = start_point
    while remaining:
        best_i, best_flip, best_d = None, None, float("inf")
        for i in remaining:
            for flip in (False, True):
                d = distance(current, _tee(pieces[i], flip))
                if d < best_d:
                    best_d, best_i, best_flip = d, i, flip
        order.append(best_i)
        flips[best_i] = best_flip
        remaining.remove(best_i)
        current = _green(pieces[best_i], best_flip)
    return order, flips


def _solve_open_chain(indices: list[int], start_point: tuple[float, float],
                       end_point: tuple[float, float], pieces: list[PlacedPiece],
                       max_passes: int = MAX_LOCAL_SEARCH_PASSES) -> tuple[list[int], dict[int, bool]]:
    """Ordonne un sous-ensemble de pièces intérieures le long d'un chemin
    ouvert dont les deux extrémités sont fixes (les bouts éloignés des deux
    ancres qui l'encadrent) — mêmes mouvements (2-opt/Or-opt/flip) que
    `local_search`, mais sur un sous-ensemble et un coût sans termes clubhouse."""
    if not indices:
        return [], {}

    order, flips = _nn_open_chain(indices, start_point, pieces)
    n = len(order)
    best_cost = _open_chain_cost(order, flips, pieces, start_point, end_point)

    for _ in range(max_passes):
        improved = False

        for i in range(n - 1):
            for j in range(i + 1, n):
                seg = order[i:j + 1]
                cand_order = order[:i] + list(reversed(seg)) + order[j + 1:]
                cand_flips = dict(flips)
                for k in seg:
                    cand_flips[k] = not flips[k]
                cost = _open_chain_cost(cand_order, cand_flips, pieces, start_point, end_point)
                if cost < best_cost - 1e-9:
                    order, flips, best_cost = cand_order, cand_flips, cost
                    improved = True

        for block_len in (1, 2, 3):
            for start in range(n - block_len + 1):
                block = order[start:start + block_len]
                rest = order[:start] + order[start + block_len:]
                for insert_at in range(len(rest) + 1):
                    if insert_at == start:
                        continue
                    cand_order = rest[:insert_at] + block + rest[insert_at:]
                    cost = _open_chain_cost(cand_order, flips, pieces, start_point, end_point)
                    if cost < best_cost - 1e-9:
                        order, best_cost = cand_order, cost
                        improved = True

        for idx in order:
            cand_flips = dict(flips)
            cand_flips[idx] = not flips[idx]
            cost = _open_chain_cost(order, cand_flips, pieces, start_point, end_point)
            if cost < best_cost - 1e-9:
                flips, best_cost = cand_flips, cost
                improved = True

        if not improved:
            break

    return order, flips


def _anchor_angle(piece: PlacedPiece, clubhouse_pos: tuple[float, float]) -> float:
    ax, ay = piece.anchor
    return math.atan2(ay - clubhouse_pos[1], ax - clubhouse_pos[0])


def _sequence_with_anchors(pieces: list[PlacedPiece], clubhouse_pos: tuple[float, float],
                            config: CourseConfig,
                            anchor_indices: list[int],
                            interior_indices: list[int]) -> tuple[list[int], list[bool]]:
    """Ordre + sens quand 4 ancres (1, 9, 10, 18) sont désignées au packing.

    Seules les pièces intérieures sont optimisées par TSP (2 chaînes de 7,
    une par nine) ; les 4 ancres occupent des positions fixes, déjà orientées
    radialement au packing. Une ancre a été placée avec son ancre (le tee
    local) près du clubhouse par construction — donc `endpoint_a` est
    toujours le bout proche du clubhouse : flip=False -> ce bout sert de
    tee (rôle "départ" : trou 1 ou 10), flip=True -> il sert de green (rôle
    "retour" : trou 9 ou 18).
    """
    n = len(pieces)
    anchors = sorted(anchor_indices, key=lambda i: _anchor_angle(pieces[i], clubhouse_pos))
    interior = sorted(interior_indices, key=lambda i: _anchor_angle(pieces[i], clubhouse_pos))
    front_anchors, back_anchors = anchors[:2], anchors[2:4]
    mid = len(interior) // 2
    front_interior, back_interior = interior[:mid], interior[mid:]

    best_order, best_flips, best_cost = None, None, float("inf")
    for start_f, finish_f in ((front_anchors[0], front_anchors[1]), (front_anchors[1], front_anchors[0])):
        for start_b, finish_b in ((back_anchors[0], back_anchors[1]), (back_anchors[1], back_anchors[0])):
            flips: list[bool] = [False] * n
            flips[start_f], flips[finish_f] = False, True
            flips[start_b], flips[finish_b] = False, True

            front_start_pt = _green(pieces[start_f], False)
            front_end_pt = _tee(pieces[finish_f], True)
            front_order, front_flips = _solve_open_chain(front_interior, front_start_pt, front_end_pt, pieces)

            back_start_pt = _green(pieces[start_b], False)
            back_end_pt = _tee(pieces[finish_b], True)
            back_order, back_flips = _solve_open_chain(back_interior, back_start_pt, back_end_pt, pieces)

            for idx, f in front_flips.items():
                flips[idx] = f
            for idx, f in back_flips.items():
                flips[idx] = f

            order = [start_f, *front_order, finish_f, start_b, *back_order, finish_b]
            cost = tour_cost(order, flips, pieces, clubhouse_pos, config)
            if cost < best_cost:
                best_order, best_flips, best_cost = order, flips, cost

    assert best_order is not None
    return best_order, best_flips


def sequence(pieces: list[PlacedPiece], clubhouse_pos: tuple[float, float],
             config: CourseConfig) -> tuple[list[int], list[bool]]:
    """Détermine l'ordre de jeu et le sens de chaque trou placé.

    Si 4 ancres ont été désignées au packing (le cas normal, num_holes>=4),
    seules les 14 pièces intérieures sont optimisées par TSP, encadrées par
    les 4 ancres à positions fixes (voir `_sequence_with_anchors`). Sinon
    (petites configs de test), repli sur le TSP entièrement libre.
    """
    anchor_indices = [i for i, p in enumerate(pieces) if p.is_anchor]
    interior_indices = [i for i, p in enumerate(pieces) if not p.is_anchor]

    if len(anchor_indices) >= 4:
        return _sequence_with_anchors(pieces, clubhouse_pos, config, anchor_indices[:4],
                                       interior_indices + anchor_indices[4:])

    order, flips = nearest_neighbor_construct(pieces, clubhouse_pos)
    return local_search(order, flips, pieces, clubhouse_pos, config)
