"""Dilatation arrondie et fermeture d'un polygone (greens doubles, round R3f).

Mécanisme des planches R3e (variante A, retenue par l'utilisateur), repris
sans changer le résultat : sur une grille de pas ``GRID_STEP`` (blocs), distance signée
EXACTE au contour (négative dedans), ligne de niveau extraite par marching
squares (interpolation linéaire sur les arêtes de la grille).

``offset_closing(P, r, c)`` = ``fermeture(P, c) ⊕ disque(r)`` : dilatation de
``r + c`` (ligne de niveau ``+ (r + c)``), contour extérieur rééchantillonné
au pas ``LEVEL_RESAMPLE``, puis érosion de ``c`` (ligne de niveau ``− c``).
Les angles saillants sont arrondis au rayon ``r`` au moins, les rentrants
au rayon ``c`` au moins ; le résultat contient ``P`` dilaté de ``r``.

Coût (budget d'habillage) : la distance n'est calculée exactement que dans
une bande de ``|niveau| + 2 × pas`` autour du contour (chaque arête met à
jour la fenêtre de grille de sa boîte élargie de la bande) ; hors de la
bande, ``±inf`` selon l'intérieur. Les cases traversées par la ligne de
niveau n'ont que des nœuds dans la bande (deux nœuds d'une case sont à
moins de ``pas × √2`` l'un de l'autre), et un nœud de la bande a pour
distance le minimum sur un ensemble d'arêtes qui contient la plus proche :
lignes de niveau identiques, au bit près, à celles de la grille entière.
"""

from __future__ import annotations

from collections import defaultdict
import math

import numpy as np

from golfgen.dressing.green import _following, shoelace


GRID_STEP = 0.15                # blocs : pas de la grille de distance
LEVEL_RESAMPLE = 0.3            # blocs : pas du contour intermédiaire (après dilatation)


def grid_signed_distance(xs: np.ndarray, ys: np.ndarray, polygon,
                         band: float = math.inf) -> np.ndarray:
    """Distance signée (négative dedans) des nœuds de la grille ``(ys × xs)``
    (abscisses et ordonnées régulières, croissantes) au bord du polygone
    fermé : minimum des distances aux arêtes, EXACT pour tout nœud à moins
    de ``band`` du bord ; au-delà, ``−inf`` dedans et ``+inf`` dehors.
    Intérieur par balayage de lignes (parité des croisements à gauche du
    nœud)."""
    polygon = np.asarray(polygon, dtype=float)
    xs, ys = np.asarray(xs, dtype=float), np.asarray(ys, dtype=float)
    a, b = polygon, _following(polygon)
    best = np.full((len(ys), len(xs)), np.inf)
    if math.isinf(band):
        windows = [(0, len(ys), 0, len(xs))] * len(a)
    else:
        lo, hi = np.minimum(a, b) - band, np.maximum(a, b) + band
        dx = xs[1] - xs[0] if len(xs) > 1 else 1.0
        dy = ys[1] - ys[0] if len(ys) > 1 else 1.0
        ix0 = np.clip(np.floor((lo[:, 0] - xs[0]) / dx).astype(int) - 1, 0, len(xs))
        ix1 = np.clip(np.ceil((hi[:, 0] - xs[0]) / dx).astype(int) + 2, 0, len(xs))
        iy0 = np.clip(np.floor((lo[:, 1] - ys[0]) / dy).astype(int) - 1, 0, len(ys))
        iy1 = np.clip(np.ceil((hi[:, 1] - ys[0]) / dy).astype(int) + 2, 0, len(ys))
        windows = list(zip(iy0.tolist(), iy1.tolist(), ix0.tolist(), ix1.tolist()))
    for ((ax, ay), (bx, by)), (y0, y1, x0, x1) in zip(zip(a.tolist(), b.tolist()), windows):
        if y0 >= y1 or x0 >= x1:
            continue
        ex, ey = bx - ax, by - ay
        length2 = max(ex * ex + ey * ey, 1e-300)
        px, py = (xs[x0:x1] - ax)[None, :], (ys[y0:y1] - ay)[:, None]
        t = np.clip((px * ex + py * ey) / length2, 0.0, 1.0)
        window = best[y0:y1, x0:x1]
        np.minimum(window, np.hypot(px - t * ex, py - t * ey), out=window)
    if not math.isinf(band):
        best[best > band] = np.inf
    return np.where(_inside_grid(xs, ys, a, b), -best, best)


def _inside_grid(xs: np.ndarray, ys: np.ndarray, a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """Nœuds intérieurs : nombre impair de croisements des arêtes ``a → b``
    avec la ligne du nœud, à son abscisse ou à sa gauche."""
    straddle = (a[None, :, 1] > ys[:, None]) != (b[None, :, 1] > ys[:, None])   # (ny, m)
    dy = np.where(straddle, (b[:, 1] - a[:, 1])[None, :], 1.0)
    x_cross = a[None, :, 0] + (ys[:, None] - a[None, :, 1]) * (b[None, :, 0] - a[None, :, 0]) / dy
    rows, cols = np.nonzero(straddle)
    if not len(rows):
        return np.zeros((len(ys), len(xs)), dtype=bool)
    values = x_cross[rows, cols]
    counts = np.bincount(rows, minlength=len(ys))
    rank = np.arange(len(rows)) - np.repeat(np.cumsum(counts) - counts, counts)
    padded = np.full((len(ys), int(counts.max())), np.inf)
    padded[rows, rank] = values
    return (padded[:, :, None] <= xs[None, None, :]).sum(axis=1) % 2 == 1


def marching_squares(values: np.ndarray, origin, step: float) -> list[np.ndarray]:
    """Lignes de niveau 0 de ``values`` (``(ny, nx)``, valeur en ``origin +
    (ix, iy)·step``), intérieur = ``values < 0`` ; bords de la grille
    supposés extérieurs (lignes fermées). Cases selle : tranchées par la
    valeur au centre (moyenne des quatre coins). Boucles en sens
    trigonométrique."""
    inside = values < 0.0
    hcross = inside[:, :-1] != inside[:, 1:]        # arête (iy, ix)–(iy, ix+1)
    vcross = inside[:-1, :] != inside[1:, :]        # arête (iy, ix)–(iy+1, ix)
    bl, br = inside[:-1, :-1], inside[:-1, 1:]
    tl, tr = inside[1:, :-1], inside[1:, 1:]
    mixed = ~((bl == br) & (br == tl) & (tl == tr))
    adjacency: dict[tuple, list] = defaultdict(list)

    def link(a, b):
        adjacency[a].append(b)
        adjacency[b].append(a)

    for iy, ix in zip(*(v.tolist() for v in np.nonzero(mixed))):
        edges = {"b": ("h", iy, ix), "t": ("h", iy + 1, ix),
                 "l": ("v", iy, ix), "r": ("v", iy, ix + 1)}
        crossed = [k for k in "brtl"
                   if (hcross[edges[k][1], edges[k][2]] if edges[k][0] == "h"
                       else vcross[edges[k][1], edges[k][2]])]
        if len(crossed) == 2:
            link(edges[crossed[0]], edges[crossed[1]])
            continue
        centre = values[iy:iy + 2, ix:ix + 2].mean() < 0.0
        for state, (e1, e2) in ((bl[iy, ix], "bl"), (br[iy, ix], "br"),
                                (tr[iy, ix], "rt"), (tl[iy, ix], "tl")):
            if bool(state) != bool(centre):
                link(edges[e1], edges[e2])

    def point(key):
        kind, iy, ix = key
        a = values[iy, ix]
        b = values[iy, ix + 1] if kind == "h" else values[iy + 1, ix]
        t = a / (a - b)
        dx, dy = (t, 0.0) if kind == "h" else (0.0, t)
        return (origin[0] + (ix + dx) * step, origin[1] + (iy + dy) * step)

    loops, seen = [], set()
    for start in adjacency:
        if start in seen:
            continue
        keys, prev, cur = [start], None, start
        seen.add(start)
        while True:
            nbrs = adjacency[cur]
            if len(nbrs) != 2:
                raise ValueError(f"marching squares : degré {len(nbrs)} en {cur}")
            nxt = nbrs[0] if nbrs[0] != prev else nbrs[1]
            if nxt == start:
                break
            seen.add(nxt)
            keys.append(nxt)
            prev, cur = cur, nxt
        loop = np.array([point(k) for k in keys])
        loops.append(loop[::-1].copy() if shoelace(loop) < 0 else loop)
    return loops


def resample(loop: np.ndarray, step: float) -> np.ndarray:
    """Contour fermé rééchantillonné à pas d'arc constant (≈ ``step``, 8
    sommets au moins)."""
    closed = np.concatenate((loop, loop[:1]))
    seg = np.hypot(*np.diff(closed, axis=0).T)
    arc = np.concatenate(([0.0], np.cumsum(seg)))
    count = max(8, int(round(arc[-1] / step)))
    s = np.linspace(0.0, arc[-1], count, endpoint=False)
    return np.column_stack((np.interp(s, arc, closed[:, 0]), np.interp(s, arc, closed[:, 1])))


def _level_loops(polygon: np.ndarray, pad: float, offset: float, step: float):
    """Boucles de ``{distance signée ≤ offset}`` sur une grille couvrant le
    polygone élargi de ``pad`` (distance exacte dans la bande utile)."""
    lo = polygon.min(axis=0) - pad
    hi = polygon.max(axis=0) + pad
    nx, ny = (np.ceil((hi - lo) / step).astype(int) + 1).tolist()
    xs, ys = step * np.arange(nx), step * np.arange(ny)      # repère local (origine lo)
    values = grid_signed_distance(xs, ys, polygon - lo, abs(offset) + 2.0 * step) - offset
    return marching_squares(values, lo, step)


def offset_closing(polygon, dilation: float, closing: float = 0.0,
                   step: float = GRID_STEP) -> tuple[np.ndarray, int]:
    """``fermeture(polygon, closing) ⊕ disque(dilation)`` (= dilatation de
    ``dilation + closing`` puis érosion de ``closing``) : contour extérieur
    (plus grande boucle, sens trigonométrique) et nombre de boucles de la
    dernière extraction (1 attendu). ``polygon`` : sens trigonométrique,
    sans sommets consécutifs confondus."""
    polygon = np.asarray(polygon, dtype=float)
    outer = dilation + closing
    loops = _level_loops(polygon, outer + 3 * step, outer, step)
    shape = max(loops, key=shoelace)
    if closing > 0.0:
        loops = _level_loops(resample(shape, LEVEL_RESAMPLE), 3 * step, -closing, step)
        shape = max(loops, key=shoelace)
    return shape, len(loops)
