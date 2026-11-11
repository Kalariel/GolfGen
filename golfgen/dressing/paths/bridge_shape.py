"""Forme ``bends`` des ponts (« virages doux », ``BridgeRule.shape``) :
portage de la colonne ``virages doux`` de la planche des formes de pont
(``tools/dressing/paths_bridge_plate.py``, branche ``rambo/paths-bridge-shapes``).

Virages comptés sur TOUTE la liaison : 3, sinon 2, sinon 1
(``BRIDGE_BEND_COUNTS``), répartis sur les tronçons PROPRES
(``bends.own_pieces`` : hors des intervalles empruntés au tronc ou
empruntés par d'autres) du tracé du pont qui passent sur l'eau effective ;
une bosse tient dans un tronçon (``needed`` : bosses de 4 × le décalage
minimal, écarts ``BEND_GAP``, marges ``BEND_END_MARGIN`` ; 18 blocs pour
1, 34 pour 2, 50 pour 3, sur la somme des tronçons mouillés). Les
bosses sont celles des virages marqués de production (``bends`` : cosinus
surélevé, décalage ``BRIDGE_BEND_OFFSETS`` de 3 à 5 blocs, demi-longueur
``BEND_HALF_RATIO`` × décalage, pente maximale π/4 soit ≈ 38°), côtés
alternés, SANS ancrage, sommet (sa case) sur l'eau effective ; entre deux
sommets le tracé peut passer sur une île (« sauter d'îlot en îlot »).

Placement : candidats ``(position, décalage, côté)`` au pas
``BRIDGE_BEND_STEP`` (0,5 bloc) le long de chaque tronçon, abscisses
reportées sur toute la liaison ; un candidat est gardé
si son sommet est sur l'eau, sa bosse libre sur la grille de la route (eau
traversable, plafond de surcoût du tronçon : ``route.polyline_is_free``),
son trait dans la carte et hors des obstacles, et, avec
``FairwayRule.no_increase``, sans case de fairway de plus que le trait
droit qu'elle remplace. Score d'un candidat : longueur de tracé sur l'eau
gagnée par sa bosse ; les bosses ne se recouvrant pas, le score d'un
placement est la somme : le meilleur (le plus de tracé sur l'eau, comme
l'étude) est trouvé par programmation dynamique sur les candidats triés
(fin croissante, écart ``BEND_GAP``, côtés alternés), égalités départagées
par l'ordre des candidats (fin, début, côté, décalage) ; écart et côtés
alternés valent d'un tronçon à l'autre : DÉTERMINISTE, sans
tirage (aucun flux RNG). Écart avec l'étude : recherche exhaustive au même
pas, mais sur les candidats valides un par un plutôt que sur les produits
de décalages (même optimum, la somme étant exacte) ; tracé de l'étude : la
ligne droite forcée ``start–end``, ici les tronçons du tracé du pont.

Contrôle final sur toute la liaison (``blocks.link_blocks``) : pas plus de
cases rognées hors des bouts ni de défauts de 4-connexité que le pont
droit, pas plus de fairway sous le trait (``no_increase``) ; sinon le pont
droit est gardé (``Route.bridge_notes``). Les intervalles empruntés
(``Route.shared``) sont reportés sur les abscisses du tracé courbé.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
import math
from typing import Sequence

import numpy as np

from golfgen.dressing.paths.bends import (BEND_END_MARGIN, BEND_GAP, BEND_HALF_RATIO, Bend,
                                          bend_points, make_bend, own_pieces)
from golfgen.dressing.paths.blocks import link_blocks
from golfgen.dressing.paths.geometry import Point, band_cells, polyline_length
from golfgen.dressing.paths.route import (Route, ceiling_of, fairway_cells, polyline_is_free,
                                          water_spans)
from golfgen.dressing.paths.scene import LinkEnds, Scene, obstacle_mask

BRIDGE_BEND_OFFSETS = (3.0, 3.25, 3.5, 3.75, 4.0, 4.5, 5.0)   # décalages essayés (blocs)
BRIDGE_BEND_STEP = 0.5          # pas des positions essayées (blocs)
BRIDGE_BEND_COUNTS = (3, 2, 1)  # virages demandés sur la liaison, du plus au moins


@dataclass(frozen=True)
class Candidate:
    """Un virage possible : bosse sur ``[start, end]`` (abscisses depuis le
    début du tronçon ``piece`` dans ``candidates``, de la liaison dans
    ``place``), ``gain`` : tracé gagné sur l'eau."""
    bend: Bend
    start: float
    end: float
    gain: float
    piece: int = 0


def needed(count: int) -> float:
    """Longueur minimale d'un tronçon pour ``count`` virages au décalage
    minimal (bosses, écarts, marges)."""
    return (count * 2.0 * BEND_HALF_RATIO * BRIDGE_BEND_OFFSETS[0]
            + (count - 1) * BEND_GAP + 2.0 * BEND_END_MARGIN)


def candidates(scene: Scene, route: Route, obstacles: np.ndarray, a: Point, b: Point,
               ceiling: float) -> list[Candidate]:
    """Virages valides un par un sur le tronçon ``a–b`` (voir le docstring
    du module), dans l'ordre (décalage, position, côté)."""
    length = math.dist(a, b)
    hw = scene.path_width / 2.0
    fenced = scene.fairway_rule.no_increase
    out = []
    for offset in BRIDGE_BEND_OFFSETS:
        half = BEND_HALF_RATIO * offset
        room = length - 2.0 * (BEND_END_MARGIN + half)
        if room < -1e-9:
            continue
        for i in range(int(math.floor(room / BRIDGE_BEND_STEP + 1e-9)) + 1):
            at = BEND_END_MARGIN + half + i * BRIDGE_BEND_STEP
            for side in (1, -1):
                bend = make_bend(a, b, at, offset, side, hw)
                x, z = int(math.floor(bend.apex[0])), int(math.floor(bend.apex[1]))
                if not (0 <= x < scene.width and 0 <= z < scene.height) or not scene.water[z, x]:
                    continue
                pts, s = bend_points(a, b, [bend])
                zone = [p for p, v in zip(pts, s) if at - half - 1e-9 <= v <= at + half + 1e-9]
                if not polyline_is_free(route.grid, zone, allow_water=True, ceiling=ceiling):
                    continue
                band = band_cells(zone, scene.path_width)
                if not ((band[:, 0] >= 0) & (band[:, 0] < scene.width)
                        & (band[:, 1] >= 0) & (band[:, 1] < scene.height)).all():
                    continue
                if obstacles[band[:, 1], band[:, 0]].any():
                    continue
                chord = (zone[0], zone[-1])
                # le trait de la bosse sert aussi au fairway (tout dans la carte) ;
                # sans fairway dessous, inutile de compter celui de la corde
                if fenced:
                    fairway = int(scene.fairway[band[:, 1], band[:, 0]].sum())
                    if fairway and fairway > fairway_cells(scene, chord):
                        continue
                gain = water_spans(scene, zone)[0] - water_spans(scene, chord)[0]
                out.append(Candidate(bend, at - half, at + half, round(gain, 6)))
    return out


def select(cands: Sequence[Candidate], count: int) -> list[Candidate]:
    """Meilleurs ``count`` virages (somme des gains maximale), espacés d'au
    moins ``BEND_GAP``, côtés alternés ; ``[]`` s'il n'y en a pas assez.
    Égalités : le premier dans l'ordre (fin, début, côté, décalage)."""
    order = sorted(cands, key=lambda c: (c.end, c.start, c.bend.side, c.bend.offset))
    n = len(order)
    if n < count:
        return []
    ends = {s: [c.end for c in order if c.bend.side == s] for s in (1, -1)}
    index = {s: [j for j, c in enumerate(order) if c.bend.side == s] for s in (1, -1)}
    best = [c.gain for c in order]       # placement de 1 virage finissant par j
    back: list[list[int]] = [[-1] * n]
    for _ in range(count - 1):
        # meilleur préfixe (dans l'ordre des fins) de chaque côté
        prefix = {}
        for s in (1, -1):
            vals, args, top, arg = [], [], -math.inf, -1
            for j in index[s]:
                if best[j] > top + 1e-12:
                    top, arg = best[j], j
                vals.append(top)
                args.append(arg)
            prefix[s] = (vals, args)
        new, link = [-math.inf] * n, [-1] * n
        for j, c in enumerate(order):
            s = -c.bend.side
            k = int(np.searchsorted(ends[s], c.start - BEND_GAP + 1e-9, side="right"))
            vals, args = prefix[s]
            if k and vals[k - 1] > -math.inf:
                new[j], link[j] = vals[k - 1] + c.gain, args[k - 1]
        best = new
        back.append(link)
    j = max(range(n), key=lambda j: (best[j], -j))
    if best[j] == -math.inf:
        return []
    out = [j]
    for link in reversed(back[1:]):
        out.append(link[out[-1]])
    return [order[j] for j in reversed(out)]


def place(scene: Scene, route: Route, obstacles: np.ndarray,
          pieces: Sequence[tuple[float, Point, Point]]) -> tuple[list[list[Bend]], str]:
    """Virages doux de la liaison (3, sinon 2, sinon 1) sur ses tronçons
    mouillés ``pieces`` (``(abscisse du début sur la liaison, a, b)``) ;
    virages de chaque tronçon et bilan."""
    total = sum(math.dist(a, b) for _, a, b in pieces)
    ceilings = [ceiling_of(route.grid, ((a, b),), True) for _, a, b in pieces]
    cands = None
    why = []
    for count in BRIDGE_BEND_COUNTS:
        if total < needed(count) - 1e-9:
            why.append(f"{count} : tronçons mouillés de {total:.1f} < {needed(count):.0f}")
            continue
        if cands is None:
            cands = [replace(c, start=s0 + c.start, end=s0 + c.end, piece=i)
                     for i, ((s0, a, b), ceiling) in enumerate(zip(pieces, ceilings))
                     for c in candidates(scene, route, obstacles, a, b, ceiling)]
        chosen = select(cands, count)
        per = [[c.bend for c in chosen if c.piece == i] for i in range(len(pieces))]
        if chosen and all(not bends or polyline_is_free(
                route.grid, bend_points(a, b, bends)[0], allow_water=True, ceiling=ceiling)
                for bends, (_, a, b), ceiling in zip(per, pieces, ceilings)):
            return per, f"{count} virage{'s' if count > 1 else ''}"
        why.append(f"{count} : aucun placement")
    return [[] for _ in pieces], "aucun virage (" + " ; ".join(why) + ")"


def bend_bridge(scene: Scene, link: LinkEnds, route: Route) -> Route:
    """Pont ``route`` avec ses virages doux (voir le docstring du module) ;
    la route d'origine (avec son bilan) si aucun virage n'est posé ou si le
    contrôle final échoue."""
    points = [tuple(map(float, p)) for p in route.points]
    obstacles = obstacle_mask(scene)
    notes: list[str] = []
    bent: dict[int, list] = {}           # segment -> [(u0, u1, a, b, virages)]
    starts = np.concatenate(([0.0], np.cumsum([math.dist(p, q)
                                               for p, q in zip(points[:-1], points[1:])])))
    wet = []                             # (segment, u0, u1, a, b) des tronçons mouillés
    for k, u0, u1 in own_pieces(points, route.shared):
        pa, pb = np.asarray(points[k]), np.asarray(points[k + 1])
        seg = math.dist(points[k], points[k + 1])
        a = tuple(map(float, pa + (pb - pa) * (u0 / seg)))
        b = tuple(map(float, pa + (pb - pa) * (u1 / seg)))
        if water_spans(scene, (a, b))[0] > 0:
            wet.append((k, u0, u1, a, b))
    if wet:
        per, note = place(scene, route, obstacles,
                          [(float(starts[k]) + u0, a, b) for k, u0, u1, a, b in wet])
        notes.append(note)
        for (k, u0, u1, a, b), bends in zip(wet, per):
            if bends:
                bent.setdefault(k, []).append((u0, u1, a, b, bends))
    if not bent:
        return replace(route, bridge_notes=tuple(notes))
    out: list[Point] = [points[0]]
    shifts = []                          # (abscisse de fin d'origine, allongement)
    s0 = 0.0
    all_bends = []
    for k in range(len(points) - 1):
        for u0, u1, a, b, bends in bent.get(k, ()):
            pts, _ = bend_points(a, b, bends)
            if math.dist(out[-1], pts[0]) > 1e-9:
                out.append(pts[0])
            out.extend(pts[1:])
            shifts.append((s0 + u1, polyline_length(pts) - (u1 - u0)))
            all_bends.extend(bends)
        if math.dist(out[-1], points[k + 1]) > 1e-9:
            out.append(points[k + 1])
        s0 += math.dist(points[k], points[k + 1])

    def moved(s: float) -> float:
        return round(s + sum(d for end, d in shifts if end <= s + 1e-9), 6)

    bridge_length, spans = water_spans(scene, out)
    shaped = replace(route, points=tuple(out), length=polyline_length(out),
                     bridge_length=bridge_length, bridge_spans=spans,
                     shared=tuple((moved(lo), moved(hi)) for lo, hi in route.shared),
                     bridge_bends=tuple(all_bends), bridge_notes=tuple(notes))
    before = link_blocks(scene, link, route, points, obstacles)
    after = link_blocks(scene, link, shaped, out, obstacles)
    if after.trimmed - after.trimmed_ends > before.trimmed - before.trimmed_ends \
            or after.defects > before.defects:
        return replace(route, bridge_notes=tuple(notes) + ("refusé : cases rognées ou défauts",))
    if scene.fairway_rule.no_increase and fairway_cells(scene, out) > fairway_cells(scene, points):
        return replace(route, bridge_notes=tuple(notes) + ("refusé : fairway ajouté",))
    return shaped
