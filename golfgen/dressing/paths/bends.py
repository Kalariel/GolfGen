"""Virages marqués d'une liaison (``bend_route``).

Sur le plus long tronçon PROPRE du tracé (morceau de segment hors des
intervalles partagés avec un autre chemin : ``own_pieces``), s'il fait au
moins ``BEND_MIN_LENGTH`` (35) blocs et ne touche pas l'eau : UN virage ;
deux en S si le tronçon dépasse ``BEND_S_MIN_LENGTH`` (60) blocs. Si le S
échoue (aucune paire ne passe), on retombe sur la règle d'un seul virage
(``BendReport.s_fallback``).

Un virage est une bosse en cosinus surélevé ``d · (1 + cos(π (s - at) /
h)) / 2`` sur ``|s - at| < h`` (sommet décalé de ``d`` ∈ ``BEND_OFFSET`` =
[3 ; 5] blocs, ``h = BEND_HALF_RATIO · d``), échantillonnée tous les
``BEND_STEP`` blocs, à au moins ``BEND_END_MARGIN`` des bouts du tronçon.
ANCRAGE (buisson ou bosquet du lot 5) : sur la perpendiculaire au sommet,
du côté intérieur, à ``min(d/2, d - w/2 - BEND_ANCHOR_CLEAR)`` de la droite
d'origine ; il doit tomber sur du rough libre (ni fairway, ni green, ni
boîte, ni bunker, ni parvis, ni eau, ni case de chemin). Un virage seul est
placé à une fraction tirée dans ``BEND_POSITION`` du tronçon ; une paire est
centrée sur le tronçon, vers 1/3 et 2/3, écartée d'au moins ``h1 + h2 +
BEND_GAP``, de côtés opposés.

Essais : pour chaque décalage (tiré, puis vers 3 : ``BEND_REDUCTIONS``), le
côté tiré puis l'autre (le second virage d'une paire : le côté opposé au
premier) ; sinon abandon. Chaque essai est revalidé (``bend_ok``) : tracé
(cases libres, plafond de surcoût du tronçon, aucune eau), trait du virage
hors des obstacles et de l'eau, cases nouvelles sans contact par une face
avec les chemins des autres liaisons (``others``), ancrage libre ; puis
``verify`` (``anchor_check``) sur les CASES FINALES de la liaison : pas plus
de défauts de connexité que la base, aucun ancrage déjà posé recouvert, ses
ancrages hors de ses cases, des ancrages et des cases des liaisons déjà
posées. Pour un S, ``verify`` ne juge que la paire complète. Avec
``FairwayRule.no_increase`` (volet c), un essai est aussi refusé si le trait
du tracé courbé a plus de cases de fairway que celui du tracé droit
(``fairway_cells`` ; ``BendReport.fairway_rejects``), y compris le premier
virage d'une paire en S, jugé seul avant le second.

Flux : ``golfgen.dressing.rng.bend_rng`` ; quatre tirages par liaison,
toujours dans cet ordre, qu'ils servent ou non : côté, décalage du 1er
virage, décalage du 2e, position d'un virage seul.

Portage fidèle de l'étude (« Virages marqués », ``_anchor_check``).
"""

from __future__ import annotations

from dataclasses import dataclass, field
import math
from typing import Callable, Sequence

import numpy as np

from golfgen.dressing.paths.blocks import band_cells, dilate4, link_blocks
from golfgen.dressing.paths.geometry import Cell, Point
from golfgen.dressing.paths.grid import Grid
from golfgen.dressing.paths.route import (Route, ceiling_of, fairway_cells, polyline_is_free,
                                          water_spans)
from golfgen.dressing.paths.scene import LinkEnds, Scene
from golfgen.dressing.rng import bend_rng

BEND_MIN_LENGTH = 35.0   # tronçon droit plus court : jamais de virage
BEND_S_MIN_LENGTH = 60.0  # tronçon droit plus long : deux virages en S
BEND_OFFSET = (3.0, 5.0)         # décalage latéral du sommet (blocs)
BEND_REDUCTIONS = (1.0, 0.5, 0.0)  # décalages essayés : 3 + poids × (tiré - 3)
BEND_HALF_RATIO = 2.0    # demi-longueur d'un virage = ratio × décalage
BEND_END_MARGIN = 3.0    # droite gardée à chaque bout du tronçon (blocs)
BEND_GAP = 4.0           # droite minimale entre deux virages (blocs)
BEND_POSITION = (0.4, 0.6)       # position d'un virage seul (fraction du tronçon)
BEND_ANCHOR_CLEAR = 1.0  # ancrage à au moins hw + ceci de l'axe du sommet (blocs)
BEND_STEP = 1.0          # pas des points d'un virage (blocs)

Verify = Callable[[list[Point], list["Bend"]], bool]


@dataclass(frozen=True)
class Bend:
    """Un virage sur le tronçon ``a–b`` : sommet à l'abscisse ``at`` (blocs
    depuis ``a``), décalé de ``offset`` blocs du côté ``side`` (+1 : normale
    ``(-uy, ux)``), sur ``± half`` blocs ; ``anchor`` : point d'ancrage."""
    at: float
    offset: float
    side: int
    half: float
    apex: Point
    anchor: Point

    @property
    def anchor_cell(self) -> Cell:
        return int(math.floor(self.anchor[0])), int(math.floor(self.anchor[1]))


@dataclass
class BendReport:
    """Bilan des virages d'une liaison : ``eligible`` (tronçon propre d'au
    moins ``BEND_MIN_LENGTH``), ``segment_length`` (celui qui reçoit les
    virages), ``requested``, ``placed``, ``reduced`` (posés à décalage
    réduit ; ``reduced_room`` : réduits faute de longueur seulement),
    ``abandoned``, ``skipped_water`` (tronçon sur l'eau), ``s_fallback`` (S
    demandé, aucune paire posée : règle d'un seul virage),
    ``verify_rejects`` (essais refusés sur les cases finales),
    ``fairway_rejects`` (essais refusés : fairway ajouté), ``bends``
    posés, ``span`` : morceau courbé (abscisses du tracé d'origine)."""
    eligible: bool = False
    segment_length: float = 0.0
    requested: int = 0
    placed: int = 0
    reduced: int = 0
    reduced_room: int = 0
    abandoned: int = 0
    skipped_water: bool = False
    s_fallback: bool = False
    verify_rejects: int = 0
    fairway_rejects: int = 0
    bends: list = field(default_factory=list)
    span: tuple[float, float] | None = None


def bend_profile(s: np.ndarray, bends: Sequence[Bend]) -> np.ndarray:
    """Décalage latéral à l'abscisse ``s`` : somme des bosses en cosinus
    surélevé (nulles, tangentes comprises, à leurs bords)."""
    out = np.zeros_like(s, dtype=float)
    for bend in bends:
        u = (s - bend.at) / bend.half
        inside = np.abs(u) < 1.0
        out[inside] += bend.side * bend.offset * (1.0 + np.cos(math.pi * u[inside])) / 2.0
    return out


def bend_points(a: Point, b: Point, bends: Sequence[Bend],
                step: float = BEND_STEP) -> tuple[list[Point], np.ndarray]:
    """Tronçon ``a–b`` avec ses virages (``a`` et ``b`` inchangés) et
    abscisse de chaque point."""
    pa, pb = np.asarray(a, dtype=float), np.asarray(b, dtype=float)
    length = float(np.hypot(*(pb - pa)))
    u = (pb - pa) / length
    normal = np.array([-u[1], u[0]])
    s = [0.0, length]
    for bend in bends:
        n = max(2, int(math.ceil(2.0 * bend.half / step)) + 1)
        s.extend(np.linspace(bend.at - bend.half, bend.at + bend.half, n))
        s.append(bend.at)                # le sommet est toujours un point
    s = np.unique(np.clip(np.asarray(s), 0.0, length))
    pts = pa + s[:, None] * u + bend_profile(s, bends)[:, None] * normal
    out = [tuple(map(float, p)) for p in pts]
    out[0], out[-1] = a, b
    return out, s


def make_bend(a: Point, b: Point, at: float, offset: float, side: int, hw: float) -> Bend:
    """Virage du tronçon ``a–b`` et son ancrage (côté intérieur)."""
    pa, pb = np.asarray(a, dtype=float), np.asarray(b, dtype=float)
    u = (pb - pa) / float(np.hypot(*(pb - pa)))
    normal = np.array([-u[1], u[0]]) * side
    foot = pa + u * at
    anchor = min(offset / 2.0, offset - hw - BEND_ANCHOR_CLEAR)
    return Bend(at, offset, side, BEND_HALF_RATIO * offset,
                tuple(map(float, foot + normal * offset)),
                tuple(map(float, foot + normal * max(anchor, 0.0))))


def anchor_is_free(scene: Scene, obstacles: np.ndarray, anchor: Point, path: np.ndarray) -> bool:
    """Ancrage sur du rough libre : case dans la carte, ni fairway, ni
    obstacle (green, boîte, bunker, parvis), ni eau, ni case de ``path``."""
    x, z = int(math.floor(anchor[0])), int(math.floor(anchor[1]))
    if not (0 <= x < scene.width and 0 <= z < scene.height):
        return False
    if obstacles[z, x] or scene.water[z, x] or scene.fairway[z, x]:
        return False
    return not bool(len(path)) or not ((path[:, 0] == x) & (path[:, 1] == z)).any()


def bend_ok(scene: Scene, grid: Grid, wet: bool, ceiling: float, obstacles: np.ndarray,
            a: Point, b: Point, placed: list[Bend], cand: Bend,
            others: np.ndarray | None = None) -> bool:
    """Tracé revalidé (cases libres, plafond du tronçon, aucune eau), puis
    cases : le trait du virage ne touche aucun obstacle ni l'eau, ses cases
    NOUVELLES (absentes du trait droit) ne touchent par une face aucune case
    ``others`` (chemins des autres liaisons) ; ancrage libre, hors des
    chemins ``others`` aussi."""
    pts, s = bend_points(a, b, [*placed, cand])
    if not polyline_is_free(grid, pts, allow_water=wet, ceiling=ceiling):
        return False
    if water_spans(scene, pts)[0] > 0:
        return False
    zone = [p for p, v in zip(pts, s) if cand.at - cand.half - 1.0 <= v <= cand.at + cand.half + 1.0]
    band = band_cells(zone, scene.path_width)
    inside = ((band[:, 0] >= 0) & (band[:, 0] < scene.width)
              & (band[:, 1] >= 0) & (band[:, 1] < scene.height))
    if not inside.all():
        return False
    if (obstacles[band[:, 1], band[:, 0]] | scene.water[band[:, 1], band[:, 0]]).any():
        return False
    if others is not None:
        pa, pb = np.asarray(a, dtype=float), np.asarray(b, dtype=float)
        u = (pb - pa) / float(np.hypot(*(pb - pa)))
        lo = max(cand.at - cand.half - 1.0, 0.0)
        hi = min(cand.at + cand.half + 1.0, float(np.hypot(*(pb - pa))))
        straight = {tuple(c) for c in band_cells([pa + u * lo, pa + u * hi], scene.path_width)}
        new = np.array([c for c in band.tolist() if tuple(c) not in straight], dtype=int)
        if len(new):
            near = dilate4(others)
            if near[new[:, 1], new[:, 0]].any():
                return False
        x, z = int(math.floor(cand.anchor[0])), int(math.floor(cand.anchor[1]))
        if 0 <= x < scene.width and 0 <= z < scene.height and others[z, x]:
            return False
    return anchor_is_free(scene, obstacles, cand.anchor, band)


def bend_count(length: float) -> int:
    """Virages demandés sur un tronçon propre de ``length`` blocs : 0 sous
    ``BEND_MIN_LENGTH``, 2 (en S) au-delà de ``BEND_S_MIN_LENGTH``, sinon 1."""
    if length < BEND_MIN_LENGTH:
        return 0
    return 2 if length > BEND_S_MIN_LENGTH else 1


def own_pieces(points: Sequence[Point], shared=()) -> list[tuple[int, float, float]]:
    """Morceaux de segments hors des intervalles d'abscisse ``shared`` :
    ``(segment, début, fin)``, abscisses depuis le début du segment."""
    out = []
    s = 0.0
    for k, (a, b) in enumerate(zip(points[:-1], points[1:])):
        seg = math.dist(a, b)
        cuts = sorted((max(lo - s, 0.0), min(hi - s, seg)) for lo, hi in shared
                      if hi > s + 1e-9 and lo < s + seg - 1e-9)
        u = 0.0
        for lo, hi in cuts:
            if lo - u > 1e-9:
                out.append((k, u, lo))
            u = max(u, hi)
        if seg - u > 1e-9:
            out.append((k, u, seg))
        s += seg
    return out


def bend_route(scene: Scene, route: Route, points: Sequence[Point], index: int,
               count: int | None, obstacles: np.ndarray, others: np.ndarray | None = None,
               verify: Verify | None = None, shared=()) -> tuple[list[Point], BendReport]:
    """Virages marqués de la liaison ``index`` sur le plus long tronçon
    propre d'au moins ``BEND_MIN_LENGTH`` du tracé ``points`` (voir le
    docstring du module) : ``count`` virages, ou la règle ``bend_count`` si
    ``None`` ; ``others`` : cases ``(h, w)`` des chemins des autres
    liaisons ; ``verify(points, bends) -> bool`` : contrôle du tracé complet
    (cases finales) ; ``shared`` : intervalles d'abscisse de ``points``
    partagés avec un autre chemin, jamais courbés. Rend le tracé courbé (ou
    inchangé) et le bilan."""
    report = BendReport()
    points = [tuple(map(float, p)) for p in points]
    rng = bend_rng(scene.seed, index)
    side0 = 1 if rng.random() < 0.5 else -1
    drawn = [float(rng.uniform(*BEND_OFFSET)), float(rng.uniform(*BEND_OFFSET))]
    where = float(rng.uniform(*BEND_POSITION))
    if route.grid is None or route.status == "trivial" or len(points) < 2:
        return points, report
    pieces = own_pieces(points, shared)
    if not pieces:
        return points, report
    k, u0, u1 = max(pieces, key=lambda p: (p[2] - p[1], -p[0]))
    length = u1 - u0
    if length < BEND_MIN_LENGTH:
        return points, report
    count = bend_count(length) if count is None else count
    report.eligible, report.segment_length, report.requested = True, round(length, 2), count
    seg = math.dist(points[k], points[k + 1])
    pa, pb = np.asarray(points[k]), np.asarray(points[k + 1])
    a = points[k] if u0 <= 1e-9 else tuple(map(float, pa + (pb - pa) * (u0 / seg)))
    b = points[k + 1] if u1 >= seg - 1e-9 else tuple(map(float, pa + (pb - pa) * (u1 / seg)))
    head = points[:k] if u0 <= 1e-9 else points[:k + 1]
    tail = points[k + 2:] if u1 >= seg - 1e-9 else points[k + 1:]
    if water_spans(scene, (a, b))[0] > 0:
        report.skipped_water = True
        return points, report
    grid, wet = route.grid, route.allow_water
    ceiling = ceiling_of(grid, ((a, b),), wet)
    hw = scene.path_width / 2.0
    fenced = scene.fairway_rule.no_increase
    base_fairway = fairway_cells(scene, points) if fenced else 0

    def ok(cand: Bend, before: list[Bend], *, full: bool = True) -> bool:
        # full=False : premier virage d'une paire, cases et tracé seulement ;
        # ``verify`` ne juge que le tracé complet (la paire entière)
        if not bend_ok(scene, grid, wet, ceiling, obstacles, a, b, before, cand, others):
            return False
        bends = [*before, cand]
        pts, _ = bend_points(a, b, bends)
        if fenced and fairway_cells(scene, head + pts + tail) > base_fairway:
            report.fairway_rejects += 1  # volet c) : le virage ajoute du fairway
            return False
        if verify is None or not full:
            return True
        if verify(head + pts + tail, bends):
            return True
        report.verify_rejects += 1
        return False

    levels = []                          # décalages essayés, du tiré au minimum
    for weight in BEND_REDUCTIONS:
        pair = tuple(BEND_OFFSET[0] + weight * (d - BEND_OFFSET[0]) for d in drawn)
        if not levels or max(abs(x - y) for x, y in zip(levels[-1], pair)) > 0.25:
            levels.append(pair)

    def one() -> tuple[list[Bend], int, int]:
        tried = False                    # un niveau a été essayé (pas seulement trop long)
        for r, (offset, _) in enumerate(levels):
            half = BEND_HALF_RATIO * offset
            if length < 2.0 * (half + BEND_END_MARGIN) - 1e-9:
                continue
            at = min(max(where * length, BEND_END_MARGIN + half), length - BEND_END_MARGIN - half)
            for side in (side0, -side0):
                cand = make_bend(a, b, at, offset, side, hw)
                if ok(cand, []):
                    return [cand], int(r > 0), int(r > 0 and not tried)
            tried = True
        return [], 0, 0

    def pair() -> tuple[list[Bend], int, int]:
        tried = False
        for r, (o1, o2) in enumerate(levels):
            h1, h2 = BEND_HALF_RATIO * o1, BEND_HALF_RATIO * o2
            spacing = max(length / 3.0, h1 + h2 + BEND_GAP)
            first = (length - (h1 + spacing + h2)) / 2.0 + h1   # paire centrée
            if first - h1 < BEND_END_MARGIN - 1e-9:
                continue
            for side in (side0, -side0):
                c1 = make_bend(a, b, first, o1, side, hw)
                if not ok(c1, [], full=False):
                    continue
                c2 = make_bend(a, b, first + spacing, o2, -side, hw)   # en S
                if ok(c2, [c1]):
                    return [c1, c2], 2 * int(r > 0), 2 * int(r > 0 and not tried)
            tried = True
        return [], 0, 0

    placed, report.reduced, report.reduced_room = pair() if count == 2 else one()
    if count == 2 and not placed:
        report.s_fallback = True         # S impossible : règle d'un seul virage
        placed, report.reduced, report.reduced_room = one()
    report.abandoned = count - len(placed)
    report.placed = len(placed)
    report.bends = placed
    if placed:
        s0 = sum(math.dist(p, q) for p, q in zip(points[:k], points[1:k + 1]))
        report.span = (s0 + u0, s0 + u1)
    if not placed:
        return points, report
    pts, _ = bend_points(a, b, placed)
    return head + pts + tail, report


def anchor_check(scene: Scene, link: LinkEnds, route: Route, obstacles: np.ndarray,
                 placed_anchors: set[Cell], placed_cells: np.ndarray,
                 base_defects: int) -> Verify:
    """``verify`` des virages d'une liaison (voir ``bend_route``) : sur les
    cases finales du tracé courbé, pas plus de défauts de connexité que la
    base (``base_defects``), aucun ancrage déjà posé recouvert, ses ancrages
    hors de ses cases, des ancrages (``placed_anchors``) et des cases
    (``placed_cells``, ``(h, w)``) des liaisons déjà posées."""
    def verify(points: list[Point], bends: list[Bend]) -> bool:
        blocks = link_blocks(scene, link, route, points, obstacles)
        if blocks.defects > base_defects:
            return False
        own = {(int(x), int(z)) for x, z in blocks.cells}
        if own & placed_anchors:
            return False                 # le virage recouvre un ancrage déjà posé
        for bend in bends:
            cell = bend.anchor_cell
            if cell in own or cell in placed_anchors or placed_cells[cell[1], cell[0]]:
                return False
        return True
    return verify
