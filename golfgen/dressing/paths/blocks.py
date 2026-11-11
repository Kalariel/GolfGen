"""Conversion en blocs d'un tracé de liaison : cases ``[x, z]`` (z = y de la
carte).

Règle : TRAIT ÉPAIS À COMPTE FIXE PAR COLONNE (``band_cells``, défini dans
``geometry`` : la route compte aussi les cases de fairway du trait). Pour chaque
segment, sur son axe majeur (x si ``|dx| >= |dy|``), chaque colonne dont le
centre est dans l'étendue du segment reçoit ``N = round(w / cos θ)`` cases
consécutives (θ : angle à l'axe majeur, ``w`` : largeur du chemin, 2 en
links, 3 en parkland), celles dont le centre est dans ``[m - N/2, m + N/2[``
autour du point ``m`` du tracé ; à chaque sommet s'ajoutent les cases dont
le centre est à moins de ``w/2`` (raccord des segments). Les deux bords sont
deux droites discrètes parallèles : la largeur ne dépend pas du décalage du
tracé par rapport à la grille, et avec ``N ≥ 2`` et ``|pente| ≤ 1`` deux
colonnes voisines se recouvrent d'au moins une case (4-connexité).

Puis (``path_blocks``) : bouts prolongés de ``BLOCK_EXTEND`` blocs dans leur
surface (green, boîte ou parvis) et cases ``blocked`` retirées (greens,
toutes les boîtes, bunkers, parvis, eau effective sauf sur un pont) : le
chemin vient au contact du bord sans y entrer. Sur un pont, l'eau est
permise dans les cases du trait des tronçons sur l'eau de la route
(``Route.bridge_spans``), prolongés de ``BRIDGE_BANK`` largeurs dans chaque
rive, et sous TOUT le trait du
tracé de la liaison (``bridge_water``) : une flaque sous le bord du trait,
centre au sec, n'est plus découpée (passerelle pincée à un bloc). Contrôle
du pincement : ``water_cuts`` (cases du trait découpées par l'eau, loin
des bouts : 0 attendu sur un pont). Réparations, qui n'ajoutent jamais de case
interdite : encoches et trous comblés (case libre à au moins 3 voisines,
puis régions entièrement cernées), épines retirées (feuille qui dépasse
d'une demi-largeur), contacts par un coin seul complétés de la case commune
libre la plus proche du tracé, morceaux recollés par la couverture
4-connexe du tracé, morceaux de ``BLOCK_ISOLATED_MAX`` cases au plus
retirés (avec les corrections des ponts : tous les morceaux sauf le plus
grand de ceux qui portent le tracé ; l'eau du trait d'un pont limitée à celle reliée
à la traversée, une case du trait découpée par l'eau en chemin rendue de
l'autre côté du trait, et une case due au seul prolongement d'un bout gardée
seulement si, au-delà du bout, elle mène à sa surface : ``past_the_surface``).
Contrôles (``Blocks``) : ``components`` (1), ``corner_only`` (0),
``obstacle_cells`` (0, par construction) ; contact des bouts (``touches``).

Portage fidèle de l'étude (« Conversion en blocs »), sans la mesure de
largeur de son rapport (``measure_width``).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

import numpy as np

from golfgen.dressing.paths.geometry import (SAMPLE_STEP, Cell, Point, band_cells,
                                             points_in_polygon, polyline_distance, project,
                                             supercover)
from golfgen.dressing.paths.route import Route
from golfgen.dressing.paths.scene import LinkEnds, Scene

BLOCK_EXTEND = 1.5       # bouts prolongés dans leur surface avant découpage (blocs)
BLOCK_END_ZONE = 4.0     # cases découpées à moins de ce rayon d'un bout : « aux bouts »
BLOCK_ISOLATED_MAX = 2   # morceau détaché de cette taille au plus : retiré
BRIDGE_BANK = 1.0        # eau d'un pont : tronçon prolongé de ceci × largeur par rive

N4 = ((1, 0), (-1, 0), (0, 1), (0, -1))


def extend(points: Sequence[Point], start: bool, end: bool, by: float | None = None) -> list[Point]:
    """Bouts prolongés de ``by`` blocs (``BLOCK_EXTEND`` par défaut) dans le
    prolongement du premier et du dernier segment."""
    by = BLOCK_EXTEND if by is None else by
    pts = [tuple(map(float, p)) for p in points]
    if len(pts) < 2:
        return pts
    for flag, end_i, nxt in ((start, 0, 1), (end, -1, -2)):
        if not flag:
            continue
        a, b = np.asarray(pts[end_i]), np.asarray(pts[nxt])
        d = a - b
        length = float(np.hypot(*d))
        if length == 0.0:
            continue
        p = tuple(map(float, a + d / length * by))
        if end_i == 0:
            pts.insert(0, p)
        else:
            pts.append(p)
    return pts


def past_the_surface(cells: np.ndarray, end: Point, previous: Point,
                     surface: np.ndarray) -> np.ndarray:
    """``(k,)`` bool : cases (``(k, 2)`` x, z) dues au prolongement du bout
    ``end`` (arrivée depuis ``previous``) qui passent au-delà de ce bout sans
    mener à sa surface : centre devant le plan du bout, et polygone pas
    atteint à moins de ``BLOCK_EXTEND`` droit devant lui. Un bout posé sur un
    coin saillant d'une boîte tournée prolonge sinon le trait de part et
    d'autre du coin, et le chemin en fait le tour (crochet) ; les cases
    derrière le plan du bout (épaule du trait, contact du bout) et celles
    qui comblent le coin entre la fin du trait et un bord droit restent."""
    d = np.asarray(end, dtype=float) - np.asarray(previous, dtype=float)
    d = d / float(np.hypot(*d))
    steps = np.linspace(0.0, BLOCK_EXTEND, int(np.ceil(BLOCK_EXTEND / SAMPLE_STEP)) + 1)
    centre = cells.astype(float) + 0.5
    ahead = (centre - np.asarray(end, dtype=float)) @ d > 0.0
    reached = np.zeros(len(cells), dtype=bool)
    for t in steps:
        reached |= points_in_polygon(centre + t * d, surface)
    return ahead & ~reached


def components(mask: np.ndarray) -> list[list[Cell]]:
    """Composantes 4-connexes ``(r, c)`` du masque, de la plus grande à la
    plus petite."""
    seen = np.zeros_like(mask)
    h, w = mask.shape
    comps = []
    for r0, c0 in zip(*np.nonzero(mask)):
        if seen[r0, c0]:
            continue
        seen[r0, c0] = True
        stack, comp = [(int(r0), int(c0))], []
        while stack:
            r, c = stack.pop()
            comp.append((r, c))
            for dr, dc in N4:
                nr, nc = r + dr, c + dc
                if 0 <= nr < h and 0 <= nc < w and mask[nr, nc] and not seen[nr, nc]:
                    seen[nr, nc] = True
                    stack.append((nr, nc))
        comps.append(comp)
    return sorted(comps, key=len, reverse=True)


def n4_count(mask: np.ndarray) -> np.ndarray:
    """Nombre de voisines (par une face) de chaque case dans le masque."""
    p = np.pad(mask, 1).astype(np.int8)
    return p[:-2, 1:-1] + p[2:, 1:-1] + p[1:-1, :-2] + p[1:-1, 2:]


def corner_only(mask: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Contacts par un coin seul : ``(r, c)`` et ``(r+1, c+1)`` sans voisine
    commune (``d1``), ``(r, c+1)`` et ``(r+1, c)`` sans voisine commune
    (``d2``) ; masques ``(h-1, w-1)``."""
    a, b, c, d = mask[:-1, :-1], mask[:-1, 1:], mask[1:, :-1], mask[1:, 1:]
    return a & d & ~b & ~c, b & c & ~a & ~d


def dilate4(mask: np.ndarray) -> np.ndarray:
    """Masque et ses voisines par une face."""
    p = np.pad(mask, 1)
    return mask | p[:-2, 1:-1] | p[2:, 1:-1] | p[1:-1, :-2] | p[1:-1, 2:]


@dataclass(frozen=True)
class Blocks:
    """Cases d'un tracé (``cells`` ``(k, 2)``, x et z, triées par x puis z)
    et bilan de la conversion : ``trimmed`` cases du trait retirées parce
    qu'elles tombaient sur un obstacle (dont ``trimmed_ends`` à moins de
    ``BLOCK_END_ZONE`` d'un bout), ``filled`` trous et encoches comblés,
    ``corners_added`` cases ajoutées contre un contact par un coin,
    ``linked`` cases du tracé ajoutées pour recoller des morceaux,
    ``dropped`` cases de morceaux détachés retirées, ``spurs`` épines
    retirées, ``compensated`` cases rendues (et restées) contre une case du
    trait découpée par l'eau en chemin, ``severed`` morceaux portant le
    tracé retirés (tracé coupé) ; contrôles finaux : ``components`` (1 attendu),
    ``corner_only`` (0 attendu), ``obstacle_cells`` (0 attendu)."""
    cells: np.ndarray
    trimmed: int = 0
    trimmed_ends: int = 0
    filled: int = 0
    corners_added: int = 0
    linked: int = 0
    dropped: int = 0
    components: int = 0
    corner_only: int = 0
    obstacle_cells: int = 0
    spurs: int = 0
    compensated: int = 0
    severed: int = 0

    @property
    def defects(self) -> int:
        """Défauts de 4-connexité : morceaux en trop (retirés s'ils portaient
        le tracé compris) et contacts par un coin."""
        return max(self.components - 1, 0) + self.corner_only + self.severed


def path_blocks(points: Sequence[Point], width: float, blocked: np.ndarray, *,
                extend_ends: tuple[bool, bool] = (False, False),
                single_piece: bool = False, compensate: np.ndarray | None = None,
                compensate_free: np.ndarray | None = None,
                surfaces: tuple[np.ndarray | None, np.ndarray | None] | None = None) -> Blocks:
    """Cases du tracé ``points`` (voir le docstring du module) : trait
    épais à compte fixe (bouts prolongés de ``BLOCK_EXTEND`` si
    ``extend_ends``), cases ``blocked`` (``(h, w)`` indexé ``[z, x]``)
    retirées, puis réparations, qui n'ajoutent jamais de case ``blocked``.
    ``single_piece`` (corrections des ponts) : un seul morceau 4-connexe
    reste, le plus grand de ceux qui portent le tracé (``supercover`` de
    ``points``, sans les prolongements) ; un autre morceau qui porte le
    tracé est compté dans ``severed``, donc dans ``defects`` (sinon : seuls
    les morceaux de ``BLOCK_ISOLATED_MAX`` cases au plus sont retirés).
    ``compensate`` (``(h, w)``, corrections des ponts : eau interdite
    à la liaison) : chaque case du trait qu'il découpe à au moins
    ``BLOCK_END_ZONE`` des bouts est rendue de l'autre côté du trait, dans
    une case libre et ``compensate_free`` (``(h, w)``) ; rien si un obstacle
    est en travers du trait. ``surfaces`` (contours du départ et de
    l'arrivée, corrections des ponts) : les cases dues au seul prolongement
    d'un bout qui ne mènent pas à sa surface sont retirées
    (``past_the_surface``)."""
    h, w = blocked.shape
    pts = [tuple(map(float, p)) for p in points]
    band = band_cells(extend(pts, *extend_ends), width)
    if not len(band):
        return Blocks(np.zeros((0, 2), dtype=int))
    pad = 3
    x0, z0 = int(band[:, 0].min()) - pad, int(band[:, 1].min()) - pad
    x1, z1 = int(band[:, 0].max()) + pad + 1, int(band[:, 1].max()) + pad + 1
    stop = np.ones((z1 - z0, x1 - x0), dtype=bool)          # hors carte : interdit
    sx0, sz0, sx1, sz1 = max(x0, 0), max(z0, 0), min(x1, w), min(z1, h)
    if sx0 < sx1 and sz0 < sz1:
        stop[sz0 - z0:sz1 - z0, sx0 - x0:sx1 - x0] = blocked[sz0:sz1, sx0:sx1]
    path = np.zeros_like(stop)
    path[band[:, 1] - z0, band[:, 0] - x0] = True
    cut = path & stop
    trimmed = int(cut.sum())
    trimmed_ends = 0
    if trimmed and len(pts) >= 2:
        rc = np.argwhere(cut)
        cut_cells = np.column_stack((rc[:, 1] + x0, rc[:, 0] + z0))
        ends = np.asarray([pts[0], pts[-1]], dtype=float)
        dist = np.hypot(cut_cells[:, None, 0] + 0.5 - ends[None, :, 0],
                        cut_cells[:, None, 1] + 0.5 - ends[None, :, 1]).min(axis=1)
        trimmed_ends = int((dist < BLOCK_END_ZONE).sum())
    path &= ~stop
    retracted = np.zeros_like(path)
    base = np.zeros_like(path)
    if surfaces is not None and len(pts) >= 2:
        own = band_cells(pts, width)
        base[own[:, 1] - z0, own[:, 0] - x0] = True
        for flag, surface, end, nxt in ((extend_ends[0], surfaces[0], 0, 1),
                                        (extend_ends[1], surfaces[1], -1, -2)):
            if not flag or surface is None or pts[end] == pts[nxt]:
                continue
            tip = extend([pts[nxt], pts[end]], False, True)[-1]
            cand = band_cells([pts[end], tip], width)
            cand = cand[path[cand[:, 1] - z0, cand[:, 0] - x0]
                        & ~base[cand[:, 1] - z0, cand[:, 0] - x0]]
            if len(cand):
                gone = cand[past_the_surface(cand, pts[end], pts[nxt], surface)]
                path[gone[:, 1] - z0, gone[:, 0] - x0] = False
                retracted[gone[:, 1] - z0, gone[:, 0] - x0] = True

    def near_line(rc: np.ndarray) -> np.ndarray:
        return polyline_distance(np.column_stack((rc[:, 1] + x0, rc[:, 0] + z0)), pts)[0]

    # trous et encoches : case libre à au moins 3 voisines du chemin, puis
    # régions hors chemin entièrement cernées par le chemin
    filled = 0
    while True:
        add = ~path & ~stop & (n4_count(path) >= 3)
        if not add.any():
            break
        filled += int(add.sum())
        path |= add
    reach = np.zeros_like(path)
    reach[0, :] = reach[-1, :] = reach[:, 0] = reach[:, -1] = True
    reach &= ~path
    while True:
        p = np.pad(reach, 1)
        grown = (reach | p[:-2, 1:-1] | p[2:, 1:-1] | p[1:-1, :-2] | p[1:-1, 2:]) & ~path
        if (grown == reach).all():
            break
        reach = grown
    holes = ~path & ~reach & ~stop
    filled += int(holes.sum())
    path |= holes
    # épines : case à une seule voisine qui dépasse du trait (centre à au
    # moins une demi-largeur du tracé), une passe ; une feuille retirée ne
    # coupe jamais le chemin ; une case du trait non prolongé, voisine d'une
    # case retirée du prolongement, n'est pas une épine (épaule du trait)
    leaf = path & (n4_count(path) == 1) & ~(base & (n4_count(retracted) > 0))
    spurs = 0
    if leaf.any():
        rc = np.argwhere(leaf)
        out = rc[near_line(rc) >= width / 2.0 - 1e-9]
        path[out[:, 0], out[:, 1]] = False
        spurs = len(out)

    def add_one(pair: np.ndarray) -> bool:
        free = [k for k in range(2) if not stop[pair[k, 0], pair[k, 1]]]
        if not free or path[pair[:, 0], pair[:, 1]].any():
            return False
        k = min(free, key=lambda k: near_line(pair[k:k + 1])[0])
        path[pair[k, 0], pair[k, 1]] = True
        return True

    def fix_corners() -> None:
        while True:
            d1, d2 = corner_only(path)
            if not (d1.any() or d2.any()):
                return
            progress = False
            for (r, c) in np.argwhere(d1):
                progress |= add_one(np.array([(r, c + 1), (r + 1, c)]))
            for (r, c) in np.argwhere(d2):
                progress |= add_one(np.array([(r, c), (r + 1, c + 1)]))
            if not progress:
                return

    # après les épines : une case rendue seule serait une feuille
    added = np.zeros_like(path)
    if compensate is not None and trimmed and len(pts) >= 2:
        wet = np.zeros_like(stop)
        wet[sz0 - z0:sz1 - z0, sx0 - x0:sx1 - x0] = compensate[sz0:sz1, sx0:sx1]
        landing = ~stop
        if compensate_free is not None:
            free = np.zeros_like(stop)
            free[sz0 - z0:sz1 - z0, sx0 - x0:sx1 - x0] = compensate_free[sz0:sz1, sx0:sx1]
            landing &= free
        rc = np.argwhere(cut & wet)
        xz = np.column_stack((rc[:, 1] + x0, rc[:, 0] + z0))
        ends = np.asarray([pts[0], pts[-1]], dtype=float)
        inner = np.hypot(xz[:, None, 0] + 0.5 - ends[None, :, 0],
                         xz[:, None, 1] + 0.5 - ends[None, :, 1]).min(axis=1) >= BLOCK_END_ZONE
        if inner.any():
            line = np.asarray(pts, dtype=float)
            centre = xz[inner].astype(float) + 0.5
            proj, dist = project(centre, line[:-1], line[1:])
            near = proj[np.arange(len(centre)), np.argmin(dist, axis=1)]
            across = cut | path
            for (r, c), to in zip(rc[inner], near - centre):
                if not to.any():
                    continue
                step = ((0, int(np.sign(to[0]))) if abs(to[0]) >= abs(to[1])
                        else (int(np.sign(to[1])), 0))
                nr, nc = r + step[0], c + step[1]
                # en travers du trait, jusqu'à la première case hors du trait ;
                # un obstacle découpé en travers : rien à rendre
                while 0 <= nr < path.shape[0] and 0 <= nc < path.shape[1] and across[nr, nc] \
                        and not (cut[nr, nc] and not wet[nr, nc]):
                    nr, nc = nr + step[0], nc + step[1]
                if 0 <= nr < path.shape[0] and 0 <= nc < path.shape[1] \
                        and not across[nr, nc] and landing[nr, nc]:
                    path[nr, nc] = across[nr, nc] = added[nr, nc] = True
    before = int(path.sum())
    fix_corners()
    corners_added = int(path.sum()) - before
    comps = components(path)
    linked = dropped = severed = 0
    if len(comps) > 1:
        for cx, cz in supercover(pts):
            r, c = cz - z0, cx - x0
            if 0 <= r < path.shape[0] and 0 <= c < path.shape[1] and not stop[r, c] \
                    and not path[r, c]:
                path[r, c] = True
                linked += 1
        before = int(path.sum())
        fix_corners()
        corners_added += int(path.sum()) - before
        comps = components(path)
    if len(comps) > 1:
        trace = set()
        if single_piece:                 # le morceau du tracé d'abord (tri stable)
            trace = {(cz - z0, cx - x0) for cx, cz in supercover(pts)}
            comps.sort(key=lambda comp: trace.isdisjoint(comp))
        for comp in comps[1:]:
            if len(comp) <= BLOCK_ISOLATED_MAX or single_piece:
                rr, cc = np.array(comp).T
                path[rr, cc] = False
                dropped += len(comp)
                severed += single_piece and not trace.isdisjoint(comp)
        comps = components(path)
    d1, d2 = corner_only(path)
    rc = np.argwhere(path)
    cells = np.column_stack((rc[:, 1] + x0, rc[:, 0] + z0)).astype(int)
    order = np.lexsort((cells[:, 1], cells[:, 0]))
    return Blocks(cells[order], trimmed, trimmed_ends, filled, corners_added, linked, dropped,
                  len(comps), int(d1.sum() + d2.sum()), int((path & stop).sum()), spurs,
                  int((added & path).sum()), severed)


def surface_cells(scene: Scene, ref: str | None) -> np.ndarray | None:
    """Cases de l'obstacle ``ref`` (``None`` : extrémité ponctuelle)."""
    if ref is None:
        return None
    return next((o.cells for o in scene.obstacles if o.ref == ref), None)


def touches(cells: np.ndarray, surface: np.ndarray | None) -> bool:
    """Une case du chemin touche par une face une case de la surface."""
    if not len(cells) or surface is None or not len(surface):
        return False
    path = {(int(x), int(z)) for x, z in cells}
    return any((int(x) + dx, int(z) + dz) in path for x, z in surface for dx, dz in N4)


def bridge_water(scene: Scene, route: Route, points: Sequence[Point] | None = None,
                 ends: tuple[bool, bool] = (True, True)) -> np.ndarray:
    """``(h, w)`` : eau permise aux cases d'une liaison, celles du trait
    (``band_cells``, largeur du chemin) de chaque tronçon sur l'eau de la
    route (``route.bridge_spans``), prolongé de ``BRIDGE_BANK`` largeurs
    dans chaque rive (une rive oblique laisserait sinon une case d'eau du
    trait hors des colonnes du tronçon) ;
    plus toutes les cases du trait du tracé ``points`` (défaut : celui de la
    route), bouts prolongés de ``BLOCK_EXTEND`` comme dans ``path_blocks`` ;
    vide hors pont. Les virages marqués ne touchent jamais l'eau : ces
    tronçons restent ceux du tracé courbé. Le
    trait de ``points`` n'est prolongé qu'aux bouts ``ends`` (ceux qui ont
    une surface), et seule son eau RELIÉE (8-connexité, dans l'eau du
    trait) à l'eau des tronçons est permise : une autre mare frôlée par le
    bord du trait reste interdite."""
    allowed = np.zeros((scene.height, scene.width), dtype=bool)
    if not route.bridge:
        return allowed
    bands = [band_cells(extend(span, True, True, BRIDGE_BANK * scene.path_width),
                        scene.path_width) for span in route.bridge_spans]
    pts = route.points if points is None else points
    full = band_cells(extend(pts, *ends), scene.path_width)
    for band in bands:
        allowed |= _mask(scene, band)
    wet = _mask(scene, full) & scene.water
    zz, xx = np.nonzero(wet | allowed)
    if len(zz):
        # eau du trait reliée (8-connexité) à celle des tronçons, dans
        # la boîte des cases concernées
        box = (slice(zz.min(), zz.max() + 1), slice(xx.min(), xx.max() + 1))
        wet, grown = wet[box], (allowed & scene.water)[box]
        while True:
            p = np.pad(grown, 1)
            more = grown.copy()
            for dz in (-1, 0, 1):
                for dx in (-1, 0, 1):
                    more |= p[1 + dz:p.shape[0] - 1 + dz, 1 + dx:p.shape[1] - 1 + dx]
            more &= wet | grown
            if (more == grown).all():
                break
            grown = more
        allowed[box] |= grown
    return allowed


def _mask(scene: Scene, band: np.ndarray) -> np.ndarray:
    """``(h, w)`` : cases ``band`` dans la carte."""
    out = np.zeros((scene.height, scene.width), dtype=bool)
    keep = ((band[:, 0] >= 0) & (band[:, 0] < scene.width)
            & (band[:, 1] >= 0) & (band[:, 1] < scene.height))
    out[band[keep, 1], band[keep, 0]] = True
    return out


def water_cuts(scene: Scene, link: LinkEnds, route: Route,
               points: Sequence[Point]) -> tuple[int, int]:
    """Cases du trait du tracé ``points`` (bouts prolongés comme dans
    ``link_blocks``) découpées par l'eau (eau effective hors
    ``bridge_water``) : en tout, et à au moins ``BLOCK_END_ZONE`` des deux
    bouts (« en chemin » : chemin pincé ; 0 attendu sur un pont)."""
    pts = [tuple(map(float, p)) for p in points]
    if len(pts) < 2:
        return 0, 0
    ends = link_ends(link)
    band = band_cells(extend(pts, *ends), scene.path_width)
    keep = ((band[:, 0] >= 0) & (band[:, 0] < scene.width)
            & (band[:, 1] >= 0) & (band[:, 1] < scene.height))
    band = band[keep]
    cut = scene.water[band[:, 1], band[:, 0]] \
        & ~bridge_water(scene, route, pts, ends)[band[:, 1], band[:, 0]]
    cells = band[cut]
    if not len(cells):
        return 0, 0
    ends = np.asarray([pts[0], pts[-1]], dtype=float)
    dist = np.hypot(cells[:, None, 0] + 0.5 - ends[None, :, 0],
                    cells[:, None, 1] + 0.5 - ends[None, :, 1]).min(axis=1)
    return len(cells), int((dist >= BLOCK_END_ZONE).sum())


def link_blocks(scene: Scene, link: LinkEnds, route: Route, points: Sequence[Point],
                obstacles: np.ndarray) -> Blocks:
    """Cases du tracé ``points`` de la liaison : eau interdite, sauf sur un
    pont dans les cases de ``bridge_water`` (trait de ses tronçons sur
    l'eau, et tout le trait de ``points``) ;
    bouts prolongés dans leurs surfaces (green, boîte ou parvis, pas le
    clubhouse ponctuel) pour venir au contact de leur bord. ``obstacles`` :
    ``scene.obstacle_mask``. Une liaison triviale
    n'a aucune case (ses surfaces se touchent : ``scene.surfaces_meet``)."""
    if route.status == "trivial":
        return Blocks(np.zeros((0, 2), dtype=int))
    ends = link_ends(link)
    forbidden = scene.water & ~bridge_water(scene, route, points, ends)
    return path_blocks(points, scene.path_width, obstacles | forbidden, extend_ends=ends,
                       single_piece=True, compensate=forbidden,
                       compensate_free=~scene.fairway,
                       surfaces=(link.src_poly, link.dst_poly))


def link_ends(link: LinkEnds) -> tuple[bool, bool]:
    """Bouts de la liaison qui ont une surface (prolongés dans les blocs)."""
    return link.src_poly is not None, link.dst_poly is not None


def contacts_missing(scene: Scene, link: LinkEnds, cells: np.ndarray) -> int:
    """Bouts de surface (pas le clubhouse ponctuel) que les cases ne touchent
    pas par une face (0 attendu)."""
    return [touches(cells, surface_cells(scene, ref))
            for ref in (link.src_ref, link.dst_ref) if ref is not None].count(False)
