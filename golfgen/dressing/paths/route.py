"""Route d'une liaison et pose du réseau dans l'ordre de ``routing.links``.

``route_link`` (dans cet ordre) :

1. TRIVIALE : extrémités à moins de ``TRIVIAL_GAP`` (1 bloc), pas de
   recherche, rien de posé sur le réseau, seulement si les empreintes des
   surfaces se touchent par une face ou se chevauchent
   (``scene.surfaces_meet``), sinon routage normal.
2. LIGNE DROITE libre : le segment ``start–end`` (points les plus proches
   des deux surfaces) sur des cases libres et sèches de la grille de
   première marge, et, avec un tronc posé, sans toucher son anneau
   (``straight``) ; avec ``FairwayRule.dry_straight``, son trait ne touche
   aucune case de fairway (``fairway_cells``).
3. Recherche SÈCHE (``search``) : A* dans la plus petite fenêtre
   (``WINDOW_MARGINS`` : 15, puis 30, puis 60) qui a un chemin, emprunts au
   tronc commun (``trunk_pieces``), puis tension (``tension_pieces``).

Règle du gain (défaut, ``BridgeRule.gain``, voir ``bridge_rule``) : routes
sèche et mouillée (eau traversable au surcoût ``BridgeRule.cost``, défaut
``GAIN_COST``), la mouillée prise si et seulement si
``(sec − mouillé) / sec ≥ gain`` (longueurs des tracés tendus), ou s'il n'y a
pas de route sèche ; ``long_dry`` : la route sèche a perdu. La route mouillée
prise est un PONT si le tracé passe sur l'eau effective (``bridge``,
``bridge_spans`` : tronçons sur l'eau ; forme ``BridgeRule.shape``,
``bends`` : virages doux posés par ``bridge_shape.bend_bridge``), sinon un
détour qui n'en touche que la frange dilatée (``detour`` avec
``water_fringe`` : un gué étroit, la demi-largeur n'y est pas respectée face
à l'eau). Sinon la route sèche (``detour`` ; ``straight`` avec ``slide`` si
elle s'est réduite à un seul segment depuis un autre point du bord).

Aucun chemin : ``PathError`` (une liaison sans chemin est un BOGUE : par
construction, le routeur pose des liaisons de 12 à 45 blocs sans couper
d'autre fairway, l'habillage garde un accès de 2 blocs au green et les ponts
sont permis). Écart avec l'étude : elle rend un statut ``failed`` compté
dans son rapport, la production lève.

Tension (``tighten``) : de chaque point, le plus loin atteignable en ligne
droite sur des cases libres sans surcoût supérieur au maximum du tronçon
remplacé (le « plafond »), ni plus longtemps sur l'anneau du tronc
(``TRUNK_RING_SLACK`` près) ; puis bouts reprojetés sur leur contour vers
leur nouveau voisin et revalidés (``reproject_ends``). Elle est REFUSÉE si
elle passe plus longtemps sur l'eau effective que le chemin brut
(``water_spans``) : le brut (centres des cases) est gardé et
``tension_refused`` le signale (sur un gué, le plafond de la frange vaut le
surcoût d'un pont : la tension pouvait changer un gué sec en pont). Avec
``FairwayRule.no_increase``, de même pour le fairway : un raccourci n'a pas
plus de cases de fairway sous son trait que le tronçon remplacé, un bout
reprojeté n'en ajoute pas au segment qu'il remplace (sinon l'ancien est
gardé), et la tension est refusée si le trait tendu en a plus que le brut
(``fairway_cells``).

Tests de ligne (``line_is_free``) : échantillons tous les ``SAMPLE_STEP``
blocs ; dans les cases des deux surfaces de la liaison, le test est exact :
un échantillon y bloque s'il est à l'intérieur du contour à plus de
``OWN_EDGE`` (un tracé peut longer le contour, pas y entrer).

Tronc commun (``route_network``) : les liaisons sont posées dans l'ordre de
``routing.links``, chacune sur le ``Network`` des précédentes (coût réduit
sur l'axe, anneau pénalisé : voir ``grid``). EMPRUNT (``trunk_pieces``) :
une suite d'au moins ``TRUNK_MIN_RUN`` cases d'axe d'une même liaison est
remplacée par le morceau EXACT de son tracé entre les projetés de la
première et de la dernière case (le tronc garde un seul tracé), prolongé
jusqu'au bout du tracé emprunté s'il est à moins de ``TRUNK_END_REACH`` et
posé sur la surface de la liaison (le parvis est un point de rattachement du
tronc) ; un emprunt dont le tracé n'est pas libre sur la grille de la
liaison est refusé (``snaps_refused``). Seuls les morceaux propres sont
tendus ; ``shared`` : intervalles d'abscisse empruntés, ``borrows`` : un
bilan par emprunt.

Portage fidèle de l'étude (``route_link`` et ses aides, pose dans l'ordre
des liaisons), sans les portes du parvis : bouts projetés sur le contour de la surface (``src_poly``,
``dst_poly``), pas de repli « sans porte » (``gate_dropped``).
"""

from __future__ import annotations

from dataclasses import dataclass, field
import math
from typing import Any, Sequence

import numpy as np

from golfgen.dressing.paths.errors import PathError
from golfgen.dressing.paths.geometry import (Point, band_cells, edges, points_in_polygon,
                                             points_polygon_distance, polyline_distance,
                                             polyline_length, project, sample_segment)
from golfgen.dressing.paths.grid import (TRUNK_RING, WINDOW_MARGINS, Grid, Network, astar,
                                         build_grid)
from golfgen.dressing.paths.scene import LinkEnds, Scene, surfaces_meet

TRIVIAL_GAP = 1.0        # extrémités plus proches : liaison triviale (blocs)
OWN_EDGE = 0.05          # profondeur tolérée sous le contour d'une surface (blocs)
TRUNK_RING_SLACK = 0.5   # tension : anneau traversé au plus ceci de plus que le brut (blocs)
TRUNK_MIN_RUN = 3        # cases d'axe consécutives au moins pour un emprunt
TRUNK_END_REACH = 2.0    # emprunt prolongé jusqu'au bout du tracé emprunté à moins de ceci

Piece = tuple[bool, list[Point]]        # (emprunté, points)
Span = tuple[Point, ...]


@dataclass(frozen=True)
class Route:
    """Route d'une liaison. ``status`` : ``straight`` (ligne droite libre ;
    ``slide`` : depuis un autre point du bord), ``detour``, ``bridge`` ou
    ``trivial`` ; ``points`` : tracé (blocs), ``length`` : sa longueur ;
    ``bridge_length`` et ``bridge_spans`` : longueur et tronçons sur l'eau
    effective (pont) ; ``window_margin`` : marge de la fenêtre retenue ;
    ``dry_length`` : meilleur détour sec (``None`` si aucun ou non cherché) ;
    ``long_dry`` : route sèche trouvée mais route mouillée prise (gain) ;
    ``water_fringe`` : détour avec l'eau traversable qui n'en touche que la
    frange dilatée ; ``raw`` : chemin avant tension ; ``grid`` : grille de la
    recherche retenue, ``allow_water`` : eau traversable sur cette grille ;
    ``tension_refused`` : tension refusée (eau) ; ``shared`` : intervalles
    d'abscisse de ``points`` empruntés à un chemin déjà posé, ``borrows`` :
    un bilan par emprunt (liaison empruntée ``from``, ``length``,
    ``owner_interval`` sur son tracé, bouts prolongés), ``snaps_refused`` :
    emprunts refusés (tracé emprunté pas libre sur la grille) ;
    ``bridge_bends`` : virages doux posés sur l'eau (``bends.Bend``, forme
    ``bends`` de ``BridgeRule``), ``bridge_notes`` : bilan de la forme
    (nombre de virages posés, ou pourquoi aucun) ; ``wet_length`` : longueur
    du tracé mouillé tendu comparée par la règle du gain (``None`` sans
    recherche mouillée)."""
    status: str
    points: tuple[Point, ...]
    length: float | None
    bridge_length: float = 0.0
    bridge_spans: tuple[Span, ...] = ()
    window_margin: int | None = None
    dry_length: float | None = None
    long_dry: bool = False
    water_fringe: bool = False
    slide: bool = False
    raw: tuple[Point, ...] = ()
    grid: Grid | None = field(default=None, compare=False, repr=False)
    allow_water: bool = False
    tension_refused: bool = False
    shared: tuple[tuple[float, float], ...] = ()
    borrows: tuple[dict, ...] = ()
    snaps_refused: int = 0
    bridge_bends: tuple = ()
    bridge_notes: tuple[str, ...] = ()
    wet_length: float | None = None

    @property
    def bridge(self) -> bool:
        return self.status == "bridge"


@dataclass(frozen=True)
class Found:
    """Chemin trouvé par ``search`` : tendu (ou brut si la tension a été
    refusée), brut, grille et marge ; ``shared``, ``borrows``,
    ``snaps_refused`` : voir ``Route``."""
    points: list[Point]
    raw: list[Point]
    grid: Grid
    margin: int
    tension_refused: bool = False
    shared: tuple[tuple[float, float], ...] = ()
    borrows: tuple[dict, ...] = ()
    snaps_refused: int = 0

    def route_fields(self) -> dict:
        return {"raw": tuple(self.raw), "grid": self.grid,
                "tension_refused": self.tension_refused, "shared": self.shared,
                "borrows": self.borrows, "snaps_refused": self.snaps_refused}


# === Lignes brisées ===

def subpolyline(points: Sequence[Point], s0: float, s1: float) -> list[Point]:
    """Morceau de la ligne brisée ``points`` entre les abscisses ``s0`` et
    ``s1`` (dans ce sens : renversé si ``s0 > s1``), sommets intermédiaires
    compris."""
    pts = np.asarray(points, dtype=float)
    seg = np.hypot(*(pts[1:] - pts[:-1]).T)
    cum = np.concatenate(([0.0], np.cumsum(seg)))
    lo, hi = sorted((s0, s1))

    def at(s: float) -> Point:
        if s >= cum[-1] - 1e-9:
            return float(pts[-1][0]), float(pts[-1][1])
        k = int(np.clip(np.searchsorted(cum, s, side="right") - 1, 0, len(seg) - 1))
        t = 0.0 if seg[k] == 0 else (s - cum[k]) / seg[k]
        p = pts[k] + (pts[k + 1] - pts[k]) * min(max(t, 0.0), 1.0)
        return float(p[0]), float(p[1])

    out = [at(lo)]
    for k in range(1, len(pts) - 1):
        if lo + 1e-9 < cum[k] < hi - 1e-9:
            out.append((float(pts[k][0]), float(pts[k][1])))
    out.append(at(hi))
    return out[::-1] if s0 > s1 else out


def project_on(points: Sequence[Point], p: Point) -> float:
    """Abscisse curviligne du projeté de ``p`` sur la ligne brisée."""
    return float(polyline_distance(np.asarray([p], dtype=float) - 0.5, points)[1][0])


def nearest_on(poly: np.ndarray, p: Point) -> Point:
    """Point du contour fermé ``poly`` le plus proche de ``p``."""
    proj, dist = project(np.asarray([p], dtype=float), *edges(poly))
    e = int(np.argmin(dist[0]))
    return float(proj[0, e, 0]), float(proj[0, e, 1])


def spans(pts: np.ndarray, flags: np.ndarray) -> tuple[tuple[Point, Point], ...]:
    """Tronçons consécutifs ``(p0, p1)`` des échantillons marqués."""
    out = []
    k = 0
    while k < len(flags):
        if not flags[k]:
            k += 1
            continue
        j = k
        while j + 1 < len(flags) and flags[j + 1]:
            j += 1
        out.append((tuple(map(float, pts[k])), tuple(map(float, pts[min(j, len(pts) - 1)]))))
        k = j + 1
    return tuple(out)


def water_spans(scene: Scene, points: Sequence[Point]) -> tuple[float, tuple[Span, ...]]:
    """Longueur (arrondie au centième) et tronçons du tracé sur l'eau
    effective, échantillons tous les ``SAMPLE_STEP`` blocs."""
    total, out = 0.0, []
    for a, b in zip(points[:-1], points[1:]):
        pts = sample_segment(a, b)
        ix = np.clip(np.floor(pts[:, 0]).astype(int), 0, scene.width - 1)
        iy = np.clip(np.floor(pts[:, 1]).astype(int), 0, scene.height - 1)
        wet = scene.water[iy, ix]
        total += float(wet[1:].sum()) * math.dist(a, b) / (len(pts) - 1)
        out.extend(spans(pts, wet))
    return round(total, 2), tuple(out)


# === Tests de ligne sur la grille ===

def line_samples(grid: Grid, a: Point, b: Point) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Échantillons du segment ``a–b`` et leurs cases ``(rows, cols)`` dans
    la fenêtre (bornées)."""
    pts = sample_segment(a, b)
    h, w = grid.forbidden.shape
    rows = np.clip(np.floor(pts[:, 1]).astype(int) - grid.y0, 0, h - 1)
    cols = np.clip(np.floor(pts[:, 0]).astype(int) - grid.x0, 0, w - 1)
    return pts, rows, cols


def inside_own(grid: Grid, pts: np.ndarray) -> np.ndarray:
    """Échantillons à l'intérieur d'une surface de la liaison, à plus de
    ``OWN_EDGE`` de son contour (un point du contour n'y est pas)."""
    out = np.zeros(len(pts), dtype=bool)
    for poly in grid.own_polys:
        inside = points_in_polygon(pts, poly)
        if inside.any():
            _, dist = project(pts[inside], *edges(poly))
            out[np.flatnonzero(inside)[dist.min(axis=1) > OWN_EDGE]] = True
    return out


def surcharge(grid: Grid, rows: np.ndarray, cols: np.ndarray, allow_water: bool) -> np.ndarray:
    """Surcoût par bloc des cases : fairway, anneau du tronc, eau (pont)."""
    extra = grid.rule.cost * grid.fairway[rows, cols]
    if grid.ring is not None:
        extra = extra + TRUNK_RING * grid.ring[rows, cols]
    return extra + (grid.bridge_cost * grid.water[rows, cols] if allow_water else 0.0)


def ceiling_of(grid: Grid, segments, allow_water: bool) -> float:
    """Plafond : surcoût maximal des cases des segments ``(a, b)``."""
    return max(float(surcharge(grid, *line_samples(grid, a, b)[1:], allow_water).max())
               for a, b in segments)


def ring_length(grid: Grid, points: Sequence[Point]) -> float:
    """Longueur (blocs) de la ligne brisée sur l'anneau des chemins posés."""
    if grid.ring is None:
        return 0.0
    total = 0.0
    for a, b in zip(points[:-1], points[1:]):
        pts, rows, cols = line_samples(grid, a, b)
        mid = grid.ring[rows, cols][1:] & grid.ring[rows, cols][:-1]
        total += float(mid.sum()) * math.dist(a, b) / max(len(pts) - 1, 1)
    return total


def fairway_cells(scene: Scene, points: Sequence[Point]) -> int:
    """Cases de fairway de la scène sous le trait (``band_cells``, largeur
    du chemin) de la ligne brisée, avant tout découpage."""
    pts = np.asarray(points, dtype=float).reshape(-1, 2)
    reach = scene.path_width / 2.0 + 1.0
    x0, y0 = (max(0, int(math.floor(v - reach))) for v in pts.min(axis=0))
    x1 = min(scene.width, int(math.ceil(pts[:, 0].max() + reach)) + 1)
    y1 = min(scene.height, int(math.ceil(pts[:, 1].max() + reach)) + 1)
    if x0 >= x1 or y0 >= y1 or not scene.fairway[y0:y1, x0:x1].any():
        return 0                         # aucun fairway dans la boîte du trait
    band = band_cells(pts, scene.path_width)
    inside = ((band[:, 0] >= 0) & (band[:, 0] < scene.width)
              & (band[:, 1] >= 0) & (band[:, 1] < scene.height))
    band = band[inside]
    return int(scene.fairway[band[:, 1], band[:, 0]].sum())


def line_is_free(grid: Grid, a: Point, b: Point, *, allow_water: bool = False,
                 ceiling: float | None = None) -> bool:
    """Segment ``a–b`` sur des cases libres (et sèches sans ``allow_water``)
    et sans surcoût supérieur à ``ceiling`` s'il est donné. Dans les cases
    des surfaces de la liaison, le test est exact (``inside_own``)."""
    if not (grid.contains(a) and grid.contains(b)):
        return False
    pts, rows, cols = line_samples(grid, a, b)
    if grid.own is None or grid.other is None:
        own = np.zeros(len(pts), dtype=bool)
        forbidden = grid.forbidden[rows, cols]
    else:
        own = grid.own[rows, cols]
        forbidden = grid.other[rows, cols]
    if forbidden.any():
        return False
    if own.any() and inside_own(grid, pts[own]).any():
        return False
    if not allow_water and (grid.water[rows, cols] & ~own).any():
        return False
    if ceiling is not None and surcharge(grid, rows, cols, allow_water).max() > ceiling + 1e-9:
        return False
    return True


def polyline_is_free(grid: Grid, points: Sequence[Point], *, allow_water: bool = False,
                     ceiling: float | None = None) -> bool:
    """``line_is_free`` sur chaque segment de la ligne brisée."""
    return all(line_is_free(grid, a, b, allow_water=allow_water, ceiling=ceiling)
               for a, b in zip(points[:-1], points[1:]))


# === Tension ===

def point_costs(grid: Grid, points: Sequence[Point], allow_water: bool) -> list[float]:
    """Surcoût de la case de chaque point."""
    cells = [grid.cell(p) for p in points]
    return [float(surcharge(grid, np.array([r]), np.array([c]), allow_water)[0])
            for r, c in cells]


def tighten(grid: Grid, points: list[Point], *, allow_water: bool,
            scene: Scene | None = None) -> list[Point]:
    """Raccourcis gloutons (voir le docstring du module) : arrêt au premier
    échec, pour chaque point. Avec ``scene`` et ``grid.rule.no_increase`` :
    un raccourci n'a pas plus de cases de fairway sous son trait que le
    tronçon qu'il remplace (``fairway_cells``)."""
    if len(points) <= 2:
        return list(points)
    cost = point_costs(grid, points, allow_water)
    ringed = grid.ring is not None and bool(grid.ring.any())
    if ringed:
        cum = np.concatenate(([0.0], np.cumsum([ring_length(grid, (a, b))
                                                for a, b in zip(points[:-1], points[1:])])))
    # raccourci : sans case de fairway dans la fenêtre de la grille, le volet
    # c) n'a rien à compter (évite ``fairway_cells`` pour chaque raccourci
    # candidat)
    fenced = scene is not None and grid.rule.no_increase and bool(grid.fairway.any())
    out = [points[0]]
    i = 0
    while i < len(points) - 1:
        best = i + 1
        ceiling = max(cost[i], cost[i + 1])
        for j in range(i + 2, len(points)):
            ceiling = max(ceiling, cost[j])
            if not line_is_free(grid, points[i], points[j], allow_water=allow_water,
                                ceiling=ceiling):
                break
            if ringed and ring_length(grid, (points[i], points[j])) > \
                    cum[j] - cum[i] + TRUNK_RING_SLACK:
                break
            if fenced:                   # volet c) : le raccourci ajoute du fairway ?
                added = fairway_cells(scene, (points[i], points[j]))
                if added and added > fairway_cells(scene, points[i:j + 1]):
                    break
            best = j
        out.append(points[best])
        i = best
    return out


def reproject_ends(link: LinkEnds, grid: Grid, points: Sequence[Point], *, allow_water: bool,
                   ends: tuple[bool, bool] = (True, True),
                   scene: Scene | None = None) -> list[Point]:
    """Après la tension, départ et arrivée reprojetés sur leurs contours vers
    leur nouveau voisin (``points[1]``, ``points[-2]``), chacun revalidé
    (cases libres, plafond du segment remplacé ; avec ``scene`` et
    ``grid.rule.no_increase`` : pas plus de cases de fairway sous le trait du
    segment que sous celui qu'il remplace), sinon gardé. ``ends`` : bouts
    concernés (pas un bout pris sur un tracé emprunté)."""
    out = list(points)
    if len(out) < 2:
        return out
    fenced = scene is not None and grid.rule.no_increase and bool(grid.fairway.any())
    for poly, end, nxt, flag in ((link.src_poly, 0, 1, ends[0]),
                                 (link.dst_poly, -1, -2, ends[1])):
        if poly is None or not flag:
            continue
        cand = nearest_on(poly, out[nxt])
        if cand == out[end]:
            continue
        ceiling = ceiling_of(grid, ((out[end], out[nxt]),), allow_water)
        if not line_is_free(grid, cand, out[nxt], allow_water=allow_water, ceiling=ceiling):
            continue
        if fenced and fairway_cells(scene, (cand, out[nxt])) > \
                fairway_cells(scene, (out[end], out[nxt])):
            continue                     # volet c) : le bout reprojeté ajoute du fairway
        out[end] = cand
    return out


def flatten(pieces: list[Piece]) -> tuple[list[Point], tuple[tuple[float, float], ...]]:
    """Points de la ligne brisée des morceaux (jonctions comptées une fois)
    et intervalles d'abscisse des morceaux empruntés."""
    out: list[Point] = []
    marks = []
    for borrowed, pts in pieces:
        if out and math.dist(out[-1], pts[0]) < 1e-9:
            i0 = len(out) - 1
            out.extend(pts[1:])
        else:
            i0 = len(out)
            out.extend(pts)
        marks.append((borrowed, i0, len(out) - 1))
    cum = np.concatenate(([0.0], np.cumsum([math.dist(a, b) for a, b in zip(out[:-1], out[1:])])))
    shared = tuple((round(float(cum[i0]), 6), round(float(cum[i1]), 6))
                   for borrowed, i0, i1 in marks if borrowed)
    return out, shared


def tension_pieces(scene: Scene, link: LinkEnds, grid: Grid, pieces: list[Piece], *,
                   allow_water: bool):
    """Tension morceau par morceau : seuls les morceaux propres à la liaison
    sont tendus, les morceaux empruntés restent le tracé emprunté ; un bout
    n'est reprojeté que s'il est sur un morceau propre. Refusée si elle
    allonge le trajet sur l'eau effective, ou, avec ``rule.no_increase``, si
    elle ajoute des cases de fairway au trait. Rend les points, le brut, les
    intervalles empruntés et la tension refusée."""
    tight: list[Piece] = []
    for n, (borrowed, pts) in enumerate(pieces):
        if borrowed:
            tight.append((True, pts))
            continue
        out = tighten(grid, pts, allow_water=allow_water, scene=scene)
        out = reproject_ends(link, grid, out, allow_water=allow_water,
                             ends=(n == 0, n == len(pieces) - 1), scene=scene)
        tight.append((False, out))
    raw, raw_shared = flatten(pieces)
    points, shared = flatten(tight)
    if water_spans(scene, points)[0] <= water_spans(scene, raw)[0] and \
            (not grid.rule.no_increase
             or fairway_cells(scene, points) <= fairway_cells(scene, raw)):
        return points, raw, shared, False
    return list(raw), raw, raw_shared, True


def tension(scene: Scene, link: LinkEnds, grid: Grid, raw: list[Point], *,
            allow_water: bool) -> tuple[list[Point], bool]:
    """Tension d'un chemin d'un seul morceau propre ; ``True`` : refusée
    (voir ``tension_pieces``)."""
    points, _, _, refused = tension_pieces(scene, link, grid, [(False, list(raw))],
                                           allow_water=allow_water)
    return points, refused


# === Emprunts au tronc commun ===

def cells_to_points(link: LinkEnds, grid: Grid, cells) -> list[Point]:
    """Points du chemin de cases : centres des cases hors surfaces, et aux
    bouts les points des contours les plus proches (ou les points fixes)."""
    inner = [(c + grid.x0 + 0.5, r + grid.y0 + 0.5) for r, c in cells[1:-1]]
    if not inner:
        return [link.start, link.end]
    start = link.start if link.src_poly is None else nearest_on(link.src_poly, inner[0])
    end = link.end if link.dst_poly is None else nearest_on(link.dst_poly, inner[-1])
    return [start, *inner, end]


def snap_end(poly: Sequence[Point], total: float, s: float,
             surface: np.ndarray | None) -> tuple[float, bool]:
    """Abscisse ``s`` sur le tracé emprunté ``poly`` portée à son bout le
    plus proche s'il est à moins de ``TRUNK_END_REACH`` et posé sur le
    contour ``surface`` de la liaison : un tronc qui part du parvis en part
    pour toutes les liaisons qui l'empruntent."""
    if surface is None:
        return s, False
    for s_end, p in ((0.0, poly[0]), (total, poly[-1])):
        if abs(s - s_end) <= TRUNK_END_REACH and \
                points_polygon_distance(np.asarray([p], dtype=float), surface)[0] < 1e-6:
            return s_end, True
    return s, False


def trunk_pieces(link: LinkEnds, grid: Grid, cells, network: Network | None, *,
                 allow_water: bool) -> tuple[list[Piece], list[dict], int]:
    """Chemin de cases en morceaux (voir « Emprunt » dans le docstring du
    module) ; le reste garde les centres des cases. Rend les morceaux, un
    bilan par emprunt et le nombre d'emprunts refusés. Sans emprunt : les
    points de ``cells_to_points``, en un seul morceau."""
    inner = list(cells[1:-1])
    if not inner:
        return [(False, [link.start, link.end])], [], 0

    def centre(rc) -> Point:
        return (rc[1] + grid.x0 + 0.5, rc[0] + grid.y0 + 0.5)

    runs = []
    if network is not None and grid.owner is not None:
        owners = [int(grid.owner[r, c]) for r, c in inner]
        i = 0
        while i < len(owners):
            k = i
            while k + 1 < len(owners) and owners[k + 1] == owners[i]:
                k += 1
            if owners[i] >= 0 and k - i + 1 >= TRUNK_MIN_RUN:
                runs.append((i, k, owners[i]))
            i = k + 1
    accepted, borrows, refused = [], [], 0
    for i0, i1, j in runs:
        poly = network.polylines[j]
        total = polyline_length(poly)
        s0 = project_on(poly, centre(inner[i0]))
        s1 = project_on(poly, centre(inner[i1]))
        snap0 = snap1 = False
        if i0 == 0 and link.src_poly is not None:
            s0, snap0 = snap_end(poly, total, s0, link.src_poly)
        if i1 == len(inner) - 1 and link.dst_poly is not None:
            s1, snap1 = snap_end(poly, total, s1, link.dst_poly)
        if abs(s1 - s0) < 1.0:
            continue
        sub = subpolyline(poly, s0, s1)
        if not polyline_is_free(grid, sub, allow_water=allow_water):
            refused += 1
            continue
        accepted.append((i0, i1, sub, snap0, snap1))
        borrows.append({"from": j, "length": round(abs(s1 - s0), 2),
                        "owner_interval": (round(min(s0, s1), 3), round(max(s0, s1), 3)),
                        "snapped_start": snap0, "snapped_end": snap1})
    seq: list[tuple[str, Any]] = []
    pos = 0
    for i0, i1, sub, snap0, snap1 in accepted:
        seq.append(("own", [centre(c) for c in inner[pos:i0]]))
        seq.append(("shared", (sub, snap0, snap1)))
        pos = i1 + 1
    seq.append(("own", [centre(c) for c in inner[pos:]]))
    pieces: list[Piece] = []
    for n, (kind, item) in enumerate(seq):
        if kind == "shared":
            pieces.append((True, list(item[0])))
            continue
        pts = list(item)
        if n == 0:
            if not pts and len(seq) > 1 and seq[1][1][1]:
                continue                 # départ pris sur le bout du tracé emprunté
            nxt = pts[0] if pts else seq[1][1][0][0]
            head = link.start if link.src_poly is None else nearest_on(link.src_poly, nxt)
        else:
            head = seq[n - 1][1][0][-1]
        if n == len(seq) - 1:
            if not pts and n > 0 and seq[n - 1][1][2]:
                continue                 # arrivée prise sur le bout du tracé emprunté
            prev = pts[-1] if pts else head
            tail = link.end if link.dst_poly is None else nearest_on(link.dst_poly, prev)
        else:
            tail = seq[n + 1][1][0][0]
        piece = [head, *pts, tail]
        if len(piece) == 2 and math.dist(head, tail) < 1e-9:
            continue
        pieces.append((False, piece))
    return pieces, borrows, refused


# === Route ===

def search(scene: Scene, link: LinkEnds, *, allow_water: bool,
           margins: Sequence[int] = WINDOW_MARGINS,
           network: Network | None = None) -> Found | None:
    """A* dans la plus petite fenêtre (marges ``margins``) qui a un chemin,
    emprunts au tronc commun puis tension ; ``None`` sans chemin."""
    for margin in margins:
        grid = build_grid(scene, link, margin, network)
        cells = astar(grid, grid.sources, grid.goal, allow_water=allow_water)
        if cells is None:
            continue
        pieces, borrows, refused = trunk_pieces(link, grid, cells, network,
                                                allow_water=allow_water)
        points, raw, shared, tension_refused = tension_pieces(
            scene, link, grid, pieces, allow_water=allow_water)
        return Found(points, raw, grid, margin, tension_refused, shared, tuple(borrows), refused)
    return None


def route_link(scene: Scene, link: LinkEnds, margins: Sequence[int] = WINDOW_MARGINS,
               network: Network | None = None) -> Route:
    """Route de ``link`` (voir le docstring du module) sur le réseau
    ``network`` des liaisons déjà posées ; ``PathError`` sans chemin."""
    direct = link.direct
    rule = scene.bridge_rule
    if direct <= TRIVIAL_GAP and surfaces_meet(scene, link):
        return Route("trivial", (link.start, link.end), direct)
    grid = build_grid(scene, link, margins[0], network)
    if line_is_free(grid, link.start, link.end) and \
            (not grid.has_trunk or ring_length(grid, (link.start, link.end)) == 0.0) and \
            (not scene.fairway_rule.dry_straight
             or fairway_cells(scene, (link.start, link.end)) == 0):
        return Route("straight", (link.start, link.end), direct, window_margin=margins[0],
                     raw=(link.start, link.end), grid=grid)
    dry = search(scene, link, allow_water=False, margins=margins, network=network)
    dry_length = polyline_length(dry.points) if dry else None

    # sans eau dans la fenêtre de la route sèche (ni dans les plus
    # petites, qu'elle contient), la recherche mouillée rendrait la même
    wet = None
    if dry is None or dry.grid.water.any():
        wet = search(scene, link, allow_water=True, margins=margins, network=network)
    take = bool(wet) and (dry_length is None or (dry_length - polyline_length(wet.points))
                          >= rule.gain * dry_length - 1e-9)
    long_dry = take and dry_length is not None
    gained = {} if not wet else {"wet_length": polyline_length(wet.points)}
    if take:
        wet_length = polyline_length(wet.points)
        bridge_length, wet_spans = water_spans(scene, wet.points)
        if bridge_length > 0:
            route = Route("bridge", tuple(wet.points), wet_length, bridge_length, wet_spans,
                          wet.margin, dry_length, long_dry, allow_water=True,
                          **gained, **wet.route_fields())
            if rule.shape == "straight":
                return route
            # import local : ``bridge_shape`` dépend de ``blocks`` et
            # ``bends``, qui dépendent de ce module
            from golfgen.dressing.paths.bridge_shape import bend_bridge
            return bend_bridge(scene, link, route)
        # frange de l'eau seulement (gué étroit) : un détour, pas un pont
        return Route("detour", tuple(wet.points), wet_length, window_margin=wet.margin,
                     dry_length=dry_length, long_dry=long_dry, water_fringe=True,
                     allow_water=True, **gained, **wet.route_fields())
    if dry:
        slide = len(dry.points) == 2
        return Route("straight" if slide else "detour", tuple(dry.points), dry_length,
                     window_margin=dry.margin, dry_length=dry_length, slide=slide,
                     long_dry=False, **gained, **dry.route_fields())
    raise PathError(f"chemins : aucune route pour la liaison {link.index} "
                    f"({link.src} → {link.dst}), seed {scene.seed}, fenêtres {tuple(margins)}, "
                    f"eau traversable comprise : bogue (aucune liaison n'est impossible "
                    f"par construction)")


def route_network(scene: Scene) -> tuple[tuple[Route, ...], Network]:
    """Toutes les liaisons de ``scene.links`` routées dans l'ordre de
    ``routing.links``, chacune sur le réseau des précédentes (tronc commun) ;
    une liaison triviale n'est pas posée. Rend les routes et le réseau."""
    network = Network(scene.width, scene.height, scene.path_width)
    routes = []
    for link in scene.links:
        route = route_link(scene, link, network=network)
        if route.status != "trivial":
            network.add(link.index, route.points)
        routes.append(route)
    return tuple(routes), network
