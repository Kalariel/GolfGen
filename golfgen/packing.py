"""Placement (packing) des squelettes de trous — sans notion d'ordre de jeu.

Chaque squelette (HoleShape) reçoit une ancre (x, y) et une rotation,
indépendamment des autres — contrairement à l'ancien GA, il n'y a aucune
chaîne "position du trou i = decalage depuis le green du trou i-1".
L'ordre de jeu et le sens (tee/green) de chaque trou sont decides plus tard,
à l'étape de séquençage (golfgen/sequencing.py).
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass

from golfgen.config import CourseConfig
from golfgen.hole_gen import HoleShape
from golfgen.utils import distance, point_to_segment_dist, rotate_translate, segments_intersect

N_ROTATION_STEPS = 72
CANDIDATES_PER_PIECE = 200
MAX_GLOBAL_RETRIES = 5
REPAIR_ROUNDS = 3
# Seulement 4 ancres à placer (contre 14 intérieures) : leur donner plus de
# candidats compense le fait qu'elles sont confinées à une bande de rayon
# étroite près du clubhouse (plus dur d'y trouver un arrangement sans
# collision entre les 4).
ANCHOR_CANDIDATES_PER_PIECE = 400

# Une carte a une clubhouse pres d'un coin (pas forcement centree) : depuis
# un coin, seul le quadrant "vers l'interieur de la carte" (~90 degres,
# centre sur la diagonale vers le centre) offre assez de place — au-dela,
# on sort de la carte en quelques dizaines de blocs. On y repartit les 18
# secteurs, avec un peu de marge de part et d'autre.
SECTOR_SPAN_FRACTION = 0.30
SECTOR_JITTER_FACTOR = 0.9

# 4 trous ont une vraie raison de pointer vers/depuis le clubhouse (1, 9, 10,
# 18 — determines au sequencage, golfgen/sequencing.py). Ils sont places pres
# du clubhouse (bande de rayon resserree) avec une rotation recompensee pour
# suivre le secteur ; les 14 autres ("interieurs") ont une rotation libre et
# sont recompenses pour former un nuage connecte (voir _connectivity_soft).
N_ANCHORS = 4
ANCHOR_RADIUS_BAND_FRACTION = 0.4
CONNECTIVITY_TARGET_DIST = 45.0


@dataclass
class PlacedPiece:
    """Un squelette de trou place dans le monde (position/rotation fixees)."""
    shape: HoleShape
    anchor: tuple[float, float]
    rotation: float
    endpoint_a: tuple[float, float]
    endpoint_b: tuple[float, float]
    waypoints_ab: list[tuple[float, float]]
    sector_index: int
    is_anchor: bool = False


# ----------------------------------------------------------------------
# Scoring (hard = infaisable, soft = qualite) — agnostique a l'ordre de jeu
# ----------------------------------------------------------------------

def _collect_segments(pieces: list[PlacedPiece]) -> list[tuple[tuple, tuple, float, int]]:
    segments = []
    for pid, piece in enumerate(pieces):
        wps = piece.waypoints_ab
        width = piece.shape.fairway_width
        for i in range(len(wps) - 1):
            segments.append((wps[i], wps[i + 1], width, pid))
    return segments


def _collision_hard_and_soft(segments: list[tuple]) -> tuple[int, float]:
    """Croisement de fairway (hard) + chevauchement de corridor (hard,
    plus strict qu'un simple croisement de centerline) + buffer (soft)."""
    hard = 0
    soft = 0.0
    for i in range(len(segments)):
        p1a, p1b, w1, pid1 = segments[i]
        for j in range(i + 1, len(segments)):
            p2a, p2b, w2, pid2 = segments[j]
            if pid1 == pid2 and abs(j - i) == 1:
                continue  # segments adjacents du meme trou, se touchent par construction
            if distance(p1a, p2a) > 200:
                continue

            if segments_intersect(p1a, p1b, p2a, p2b):
                hard += 1

            d = min(
                point_to_segment_dist(p1a[0], p1a[1], p2a[0], p2a[1], p2b[0], p2b[1]),
                point_to_segment_dist(p1b[0], p1b[1], p2a[0], p2a[1], p2b[0], p2b[1]),
                point_to_segment_dist(p2a[0], p2a[1], p1a[0], p1a[1], p1b[0], p1b[1]),
                point_to_segment_dist(p2b[0], p2b[1], p1a[0], p1a[1], p1b[0], p1b[1]),
            )
            overlap_threshold = (w1 + w2) / 2
            if d < overlap_threshold:
                hard += 1  # chevauchement reel de corridor, pas juste un croisement de ligne
            safe_dist = overlap_threshold + 5.0
            if d < safe_dist:
                soft += (safe_dist - d) ** 2 * 50.0
    return hard, soft


def _tee_green_hard(pieces: list[PlacedPiece], segments: list[tuple]) -> int:
    """Un tee/green ne doit pas tomber sur le fairway d'un AUTRE trou."""
    hard = 0
    for pid, piece in enumerate(pieces):
        tee = piece.endpoint_a
        green = piece.endpoint_b
        green_radius = piece.shape.green_radius + 2.0
        for p1, p2, width, seg_pid in segments:
            if seg_pid == pid:
                continue
            d_tee = point_to_segment_dist(tee[0], tee[1], p1[0], p1[1], p2[0], p2[1])
            if d_tee < (width / 2 + 5.0):
                hard += 1
            d_green = point_to_segment_dist(green[0], green[1], p1[0], p1[1], p2[0], p2[1])
            if d_green < (width / 2 + green_radius):
                hard += 1
    return hard


def _bounds_hard_and_soft(pieces: list[PlacedPiece], margin: int, w: int, h: int) -> tuple[int, float]:
    hard = 0
    soft = 0.0
    for piece in pieces:
        for x, y in piece.waypoints_ab:
            dx = max(0.0, margin - x, x - (w - margin))
            dy = max(0.0, margin - y, y - (h - margin))
            if dx > 0 or dy > 0:
                hard += 1
                soft += (dx ** 2 + dy ** 2) * 10.0
    return hard, soft


def _clubhouse_hard_and_soft(pieces: list[PlacedPiece],
                              clubhouse_pos: tuple[float, float]) -> tuple[int, float]:
    """Zone d'exclusion autour du clubhouse — aucune exemption : à ce stade
    aucun trou n'a encore d'id (le 9/18 n'existe pas avant le séquençage)."""
    cx, cy = clubhouse_pos
    hw, hh = 15.0, 10.0
    buffer = 5.0

    def dist_to_box(px, py):
        dx = max(abs(px - cx) - hw, 0.0)
        dy = max(abs(py - cy) - hh, 0.0)
        return math.sqrt(dx * dx + dy * dy)

    def segment_crosses_box(p1, p2):
        if dist_to_box(p1[0], p1[1]) < 0.5 or dist_to_box(p2[0], p2[1]) < 0.5:
            return True
        bx1, by1, bx2, by2 = cx - hw, cy - hh, cx + hw, cy + hh
        edges = [
            ((bx1, by1), (bx2, by1)),
            ((bx2, by1), (bx2, by2)),
            ((bx2, by2), (bx1, by2)),
            ((bx1, by2), (bx1, by1)),
        ]
        return any(segments_intersect(p1, p2, ea, eb) for ea, eb in edges)

    hard = 0
    soft = 0.0
    for piece in pieces:
        for pt in (piece.endpoint_a, piece.endpoint_b):
            d = dist_to_box(pt[0], pt[1])
            if d < 0.5:
                hard += 1
            elif d < buffer:
                soft += (buffer - d) ** 2 * 500.0
        wps = piece.waypoints_ab
        for i in range(len(wps) - 1):
            if segment_crosses_box(wps[i], wps[i + 1]):
                hard += 1
    return hard, soft


def _angle_diff(a: float, b: float) -> float:
    d = a - b
    while d > math.pi:
        d -= 2 * math.pi
    while d < -math.pi:
        d += 2 * math.pi
    return d


def _center_angle(config: CourseConfig, clubhouse_pos: tuple[float, float]) -> float:
    """Direction du clubhouse vers le centre de la carte."""
    return math.atan2(config.height / 2 - clubhouse_pos[1],
                       config.width / 2 - clubhouse_pos[0])


def _half_sector(config: CourseConfig) -> float:
    span = 2 * math.pi * SECTOR_SPAN_FRACTION
    return span / (2 * config.num_holes)


def _sector_center(config: CourseConfig, clubhouse_pos: tuple[float, float],
                    sector_index: int) -> float:
    """Centre angulaire du secteur, sur l'arc tourné vers l'intérieur de la
    carte (pas les 360° complets — un coin n'ouvre que sur une partie)."""
    n = config.num_holes
    span = 2 * math.pi * SECTOR_SPAN_FRACTION
    offset = (sector_index + 0.5) / n * span - span / 2
    return _center_angle(config, clubhouse_pos) + offset


def _territory_soft(pieces: list[PlacedPiece], config: CourseConfig,
                     clubhouse_pos: tuple[float, float]) -> float:
    """Pénalise une ANCRE dont le tee s'éloigne trop de son secteur assigné.

    Mesuré sur `piece.anchor` (le tee), pas le centroïde de toute la pièce —
    sinon la pénalité varie avec la rotation et force accidentellement
    toutes les pièces à pointer radialement (voir contexte du plan)."""
    soft = 0.0
    half_sector = _half_sector(config)
    for piece in pieces:
        if not piece.is_anchor:
            continue
        sector_center = _sector_center(config, clubhouse_pos, piece.sector_index)
        ax, ay = piece.anchor
        angle = math.atan2(ay - clubhouse_pos[1], ax - clubhouse_pos[0])
        excess = max(0.0, abs(_angle_diff(angle, sector_center)) - half_sector)
        soft += excess ** 2 * 300.0
    return soft


def _bearing_soft(pieces: list[PlacedPiece], config: CourseConfig,
                   clubhouse_pos: tuple[float, float]) -> float:
    """Uniquement pour les ANCRES : pénalise si le trou ne pointe pas
    radialement (vers/depuis le clubhouse) le long de son secteur — c'est
    volontaire ici, contrairement à l'ancien biais accidentel."""
    soft = 0.0
    for piece in pieces:
        if not piece.is_anchor:
            continue
        sector_center = _sector_center(config, clubhouse_pos, piece.sector_index)
        fx, fy = piece.endpoint_b  # bout eloigne de l'ancre (endpoint_a == anchor)
        bearing = math.atan2(fy - clubhouse_pos[1], fx - clubhouse_pos[0])
        dev = abs(_angle_diff(bearing, sector_center))
        soft += dev ** 2 * 150.0
    return soft


def _connectivity_soft(pieces: list[PlacedPiece]) -> float:
    """Uniquement pour les pièces INTERIEURES : encourage un nuage connecté
    (au moins une extrémité à portée raisonnable d'une pièce déjà placée)
    pour que le séquençage puisse enchaîner sans grand saut."""
    soft = 0.0
    for i, piece in enumerate(pieces):
        if piece.is_anchor:
            continue
        others = pieces[:i] + pieces[i + 1:]
        if not others:
            continue
        cand_pts = (piece.endpoint_a, piece.endpoint_b)
        other_pts = [pt for p in others for pt in (p.endpoint_a, p.endpoint_b)]
        d_min = min(distance(cp, op) for cp in cand_pts for op in other_pts)
        if d_min > CONNECTIVITY_TARGET_DIST:
            soft += (d_min - CONNECTIVITY_TARGET_DIST) ** 2 * 3.0
    return soft


def _radius_bounds(config: CourseConfig) -> tuple[float, float]:
    margin = config.routing.grid_margin
    diag = math.hypot(config.width, config.height)
    lo = margin + 25.0
    hi = max(lo + 1.0, 0.55 * diag)
    return lo, hi


def _anchor_radius_bounds(config: CourseConfig) -> tuple[float, float]:
    radius_lo, radius_hi = _radius_bounds(config)
    return radius_lo, radius_lo + ANCHOR_RADIUS_BAND_FRACTION * (radius_hi - radius_lo)


def _radial_band_soft(pieces: list[PlacedPiece], clubhouse_pos: tuple[float, float],
                       radius_lo: float, radius_hi: float,
                       anchor_radius_hi: float) -> float:
    """Pénalise un trou trop proche ou trop loin du clubhouse (rayonnement,
    pas centrage) — mesuré sur `piece.anchor`, pas le centroïde (même
    raison que `_territory_soft`). Les ancres ont leur propre bande, plus
    resserrée près du clubhouse."""
    soft = 0.0
    for piece in pieces:
        d = distance(piece.anchor, clubhouse_pos)
        hi = anchor_radius_hi if piece.is_anchor else radius_hi
        if d > hi:
            soft += (d - hi) ** 2 * 2.0
        elif d < radius_lo:
            soft += (radius_lo - d) ** 2 * 2.0
    return soft


def score_placement(pieces: list[PlacedPiece], config: CourseConfig,
                     clubhouse_pos: tuple[float, float]) -> tuple[int, float]:
    """Score (hard_count, soft_penalty) d'un placement complet.

    Agnostique à l'ordre de jeu — aucun id de trou n'intervient ici.
    """
    rc = config.routing
    segments = _collect_segments(pieces)
    coll_hard, coll_soft = _collision_hard_and_soft(segments)
    tg_hard = _tee_green_hard(pieces, segments)
    b_hard, b_soft = _bounds_hard_and_soft(pieces, rc.grid_margin, config.width, config.height)
    ch_hard, ch_soft = _clubhouse_hard_and_soft(pieces, clubhouse_pos)
    radius_lo, radius_hi = _radius_bounds(config)
    _, anchor_radius_hi = _anchor_radius_bounds(config)

    hard = coll_hard + tg_hard + b_hard + ch_hard
    soft = (
        coll_soft + b_soft + ch_soft
        + _territory_soft(pieces, config, clubhouse_pos)
        + _bearing_soft(pieces, config, clubhouse_pos)
        + _connectivity_soft(pieces)
        + _radial_band_soft(pieces, clubhouse_pos, radius_lo, radius_hi, anchor_radius_hi)
    )
    return hard, soft


# ----------------------------------------------------------------------
# Placement glouton randomisé
# ----------------------------------------------------------------------

class Packer:
    """Place les squelettes de trous sur la carte (position + rotation).

    Approche gloutonne randomisée (pas un GA) : le problème est bien
    conditionné une fois qu'il n'y a plus de chaîne de dépendance entre
    trous — chaque pièce est indépendante, un échantillonnage suffisant de
    candidats trouve une solution sans avoir besoin d'une population/GA.
    """

    def __init__(self, config: CourseConfig, clubhouse_pos: tuple[float, float],
                 rng: random.Random):
        self.config = config
        self.clubhouse_pos = clubhouse_pos
        self.rng = rng

    def pack(self, shapes: list[HoleShape]) -> list[PlacedPiece]:
        best_pieces: list[PlacedPiece] | None = None
        best_score = (float("inf"), float("inf"))
        for _ in range(MAX_GLOBAL_RETRIES):
            pieces = self._pack_once(shapes)
            pieces = self._repair(pieces)
            score = score_placement(pieces, self.config, self.clubhouse_pos)
            if score < best_score:
                best_score, best_pieces = score, pieces
            if score[0] == 0:
                return pieces
        hard, soft = best_score
        if hard > 0:
            print(f"WARN: packing — {hard} violation(s) dure(s) restante(s) apres "
                  f"{MAX_GLOBAL_RETRIES} tentatives (soft={soft:.1f}).")
        assert best_pieces is not None
        return best_pieces

    def _repair(self, pieces: list[PlacedPiece]) -> list[PlacedPiece]:
        """Recherche locale : re-tire chaque pièce (les autres fixées) si ça
        améliore le score global — nettoie les violations résiduelles sans
        repartir d'un pack complet."""
        pieces = list(pieces)
        n = len(pieces)
        for _ in range(REPAIR_ROUNDS):
            current = score_placement(pieces, self.config, self.clubhouse_pos)
            if current[0] == 0:
                break
            order = list(range(n))
            self.rng.shuffle(order)
            improved = False
            for i in order:
                others = pieces[:i] + pieces[i + 1:]
                candidate = self._best_candidate(pieces[i].shape, pieces[i].sector_index,
                                                  pieces[i].is_anchor, others)
                trial = others + [candidate]
                trial_score = score_placement(trial, self.config, self.clubhouse_pos)
                if trial_score < current:
                    pieces[i] = candidate
                    current = trial_score
                    improved = True
            if not improved:
                break
        return pieces

    def _pack_once(self, shapes: list[HoleShape]) -> list[PlacedPiece]:
        n = len(shapes)
        sector_of = list(range(n))
        self.rng.shuffle(sector_of)  # decouple du par et de l'ordre de traitement
        anchor_set = set(self.rng.sample(range(n), min(N_ANCHORS, n)))
        process_order = sorted(range(n), key=lambda i: -shapes[i].length)  # plus gros d'abord

        placed: list[PlacedPiece | None] = [None] * n
        for i in process_order:
            already = [p for p in placed if p is not None]
            placed[i] = self._best_candidate(shapes[i], sector_of[i], i in anchor_set, already)
        return placed  # type: ignore[return-value]

    def _best_candidate(self, shape: HoleShape, sector_index: int, is_anchor: bool,
                         already: list[PlacedPiece]) -> PlacedPiece:
        sector_center = _sector_center(self.config, self.clubhouse_pos, sector_index)
        best: PlacedPiece | None = None
        best_score = (float("inf"), float("inf"))
        n_candidates = ANCHOR_CANDIDATES_PER_PIECE if is_anchor else CANDIDATES_PER_PIECE
        for _ in range(n_candidates):
            candidate = self._sample_candidate(shape, sector_index, sector_center, is_anchor)
            score = score_placement(already + [candidate], self.config, self.clubhouse_pos)
            if score < best_score:
                best_score, best = score, candidate
        assert best is not None
        return best

    def _sample_candidate(self, shape: HoleShape, sector_index: int,
                           sector_center: float, is_anchor: bool) -> PlacedPiece:
        radius_lo, radius_hi = _radius_bounds(self.config)
        if is_anchor:
            _, radius_hi = _anchor_radius_bounds(self.config)
        radius = self.rng.uniform(radius_lo, radius_hi)
        jitter = SECTOR_JITTER_FACTOR * _half_sector(self.config)
        angle = sector_center + self.rng.uniform(-jitter, jitter)
        anchor = (
            self.clubhouse_pos[0] + radius * math.cos(angle),
            self.clubhouse_pos[1] + radius * math.sin(angle),
        )
        rotation = self.rng.randrange(N_ROTATION_STEPS) * (2 * math.pi / N_ROTATION_STEPS)
        waypoints_ab = rotate_translate(shape.waypoints, anchor, rotation)
        return PlacedPiece(
            shape=shape,
            anchor=anchor,
            rotation=rotation,
            endpoint_a=waypoints_ab[0],
            endpoint_b=waypoints_ab[-1],
            waypoints_ab=waypoints_ab,
            sector_index=sector_index,
            is_anchor=is_anchor,
        )
