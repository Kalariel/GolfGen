"""Coupure du fairway au-dessus de l'eau (lot 2 R4), branchée à
``dress_course`` (R4c) avec ``FAIRWAY_WATER_CUT`` : bande de 2 blocs, aire
minimale de 5 blocs², validées par l'utilisateur sur les planches (R4b).

Décisions utilisateur : un segment droit peut franchir l'eau (carry ; seul un
coude dans l'eau est interdit, garanti par le routage) ; le fairway s'arrête à
``WaterCut.band`` blocs de la berge (bande de rough entre fairway et eau) ;
les fragments plus petits que ``WaterCut.min_area`` sont supprimés, comptés
avec leur cause, jamais en silence ; le fairway peut donc compter plusieurs
morceaux, ou aucun (cas explicite : ``WaterFairway.empty``).

Eau : l'eau EFFECTIVE du trou (``golfgen.dressing.water.effective_water`` :
eau réelle du relief, ``WaterMask``, à la vraie berge, sans élargissement,
moins les cellules remontées du green insulaire et des boîtes remontées du
trou), consommée telle quelle : aucune copie du critère ici. Cellule
``(i, j)`` = carré fermé ``[i, i+1] × [j, j+1]`` en blocs (indexation de
``WaterMask``) ; la distance est mesurée au BORD de ce carré, c'est-à-dire
à la berge : une bande de ``b`` blocs laisse ``b`` blocs de rough entre le
fairway et l'eau. Hors de la carte, la cellule du bord la plus proche
(bornage) ; sans effet pour un nœud dans la carte, la cellule du bord étant
plus proche que sa copie virtuelle.

Mécanisme, comme le contournement des greens (``fairway_profile
.clear_obstacles``) : dans le champ, avant la ligne de niveau, ``champ ←
max(champ, band − d)``, ``d`` = distance EXACTE du nœud de grille au bord
de la cellule mouillée la plus proche (``wet_distance``, calcul séparable
borné à ``band + 2 GRID_STEP``, au-delà ``inf`` : sans effet). Le ``max``
ne fait que retirer de la surface : chaque morceau obtenu est inclus dans le
fairway sans eau, donc dans le cœur.

Règle des boucles :

- AVANT la coupure, le fairway sans eau doit avoir exactement une boucle
  réelle (îlots d'un nœud ``fairway.is_island`` retirés et comptés), sinon
  ``DressingError`` : règle de production inchangée ;
- APRÈS la coupure, chaque boucle extérieure est un morceau (les îlots d'un
  nœud sont retirés et comptés comme avant) ; un morceau d'aire < ``min_area``
  est retiré et rapporté (``RemovedPiece``, cause ``"eau"``) ;
- une boucle intérieure à une autre (eau entièrement entourée de fairway :
  le polygone simple ``FairwayShape`` ne sait pas la porter) lève
  ``DressingError`` : rapportée, jamais bouchée en silence ;
- dès que la coupure modifie le champ (``changed``), le contour est
  recalculé par la ligne de niveau du champ coupé, même si aucun nœud
  intérieur ne devient extérieur : relever un nœud extérieur, ou un nœud
  intérieur sans changer son signe, sur une arête que la ligne traverse
  déplace la ligne ; ``bitten`` (un nœud intérieur rendu extérieur) n'est
  qu'un indicateur ;
- sans eau (``water = None``) ou sans eau à portée (champ inchangé), le
  résultat est celui de production au bit près
  (``fairway_profile.fairway_shapes``).

Aléa : AUCUN tirage. La coupure est déterministe (champ et masque) ; la bande
et l'aire minimale sont des constantes de style, pas des tirages : les flux
``fairway_rng`` (3) et ``fairway_profile_rng`` (4) ne bougent pas, aucun flux
nouveau n'est nécessaire.
"""

from __future__ import annotations

from dataclasses import dataclass
import math

import numpy as np

from golfgen.dressing.fairway import (BIG, GRID_STEP, OUTLINE_STEP, FairwayStyle, Grid,
                                      RawProfile, fairway_outline, is_island, profile_neck)
from golfgen.dressing.fairway_profile import profiled_field
from golfgen.dressing.green import points_in_polygon, shoelace
# ``RemovedPiece`` est défini dans ``model`` (champ ``HoleDressing.fairway_removed``,
# sans import circulaire) et réexporté ici
from golfgen.dressing.model import DressingError, FairwayShape, RemovedPiece
from golfgen.dressing.offset import marching_squares, resample
from golfgen.routing.model import ElasticHole
from golfgen.routing.sites import WaterMask


WATER_CAUSE = "eau"
PAD = 2.0 * GRID_STEP           # blocs : distance exacte au-delà de la bande (ligne de niveau)


@dataclass(frozen=True, slots=True)
class WaterCut:
    """Paramètres de la coupure : ``band`` blocs de rough au moins entre
    fairway et cellule mouillée (> 0) ; ``min_area`` blocs² : fragment plus
    petit supprimé (0 : aucun filtre). Production : ``FAIRWAY_WATER_CUT``."""

    band: float
    min_area: float = 0.0

    def __post_init__(self) -> None:
        if not (math.isfinite(self.band) and self.band > 0.0):
            raise ValueError(f"bande d'eau invalide : {self.band!r} (attendu > 0)")
        if not (math.isfinite(self.min_area) and self.min_area >= 0.0):
            raise ValueError(f"aire minimale invalide : {self.min_area!r} (attendu ≥ 0)")


# Coupure de production (``dress_course``, R4c) : bande de 2 blocs de rough
# entre fairway et eau, fragments de moins de 5 blocs² retirés (cause
# ``"eau"``). Valeurs validées par l'utilisateur sur les planches (colonne
# 4, R4b) ; mêmes dans les deux styles.
FAIRWAY_WATER_CUT = WaterCut(band=2.0, min_area=5.0)


@dataclass(frozen=True)
class WaterFairway:
    """Fairway coupé d'un trou. ``shapes`` : morceaux gardés (aire
    décroissante, coordonnées NON arrondies), éventuellement aucun ;
    ``removed`` : fragments retirés (aire < ``min_area``), avec leur cause ;
    ``bitten`` : l'eau a retiré au moins un nœud du fairway (indicateur) ;
    ``changed`` : la coupure a modifié le champ, contour recalculé (sinon
    contour de production au bit près) ; ``drowned`` : aucune boucle après
    la coupure (fairway entièrement à moins de ``band`` de l'eau) ;
    ``islands`` : îlots d'un nœud retirés (avant coupure si le champ est
    inchangé, après sinon) ; ``wet_area`` : aire du fairway sans coupure
    sur des cellules mouillées (blocs², nœuds × ``GRID_STEP``²)."""

    shapes: tuple[FairwayShape, ...]
    removed: tuple[RemovedPiece, ...]
    bitten: bool
    changed: bool
    drowned: bool
    islands: int
    wet_area: float

    @property
    def empty(self) -> bool:
        """Aucun morceau gardé : noyé, ou tous les fragments retirés."""
        return not self.shapes

    @property
    def empty_cause(self) -> str | None:
        """``None`` si un morceau reste ; sinon ``"eau : noyé"`` ou ``"eau :
        fragments trop petits"``."""
        if self.shapes:
            return None
        return f"{WATER_CAUSE} : noyé" if self.drowned else f"{WATER_CAUSE} : fragments trop petits"


def wet_cells(water: WaterMask | np.ndarray) -> np.ndarray:
    """Tableau booléen ``(h, w)`` des cellules mouillées (indexé ``[y, x]``)
    d'un ``WaterMask`` (eau effective) ou d'un tableau déjà booléen."""
    if isinstance(water, WaterMask):
        return water.water
    wet = np.asarray(water)
    if wet.dtype != bool or wet.ndim != 2:
        raise ValueError("masque mouillé attendu : WaterMask ou tableau booléen 2D (h, w)")
    return wet


def wet_distance(grid: Grid, water: WaterMask | np.ndarray, reach: float) -> np.ndarray | None:
    """Distance (blocs) de chaque nœud de ``grid`` (``(ny, nx)``) au BORD de
    la cellule mouillée la plus proche (``wet_cells(water)``, carré fermé
    ``[i, i+1] × [j, j+1]`` : distance à la berge) ; exacte jusqu'à
    ``reach``, ``inf`` au-delà ; 0 dans une cellule mouillée ou sur son
    bord. ``None`` si aucune cellule mouillée n'est à portée de la grille.
    Calcul séparable : par colonne de nœuds, carré du plus proche écart en x
    pour chaque ligne de cellules, puis minimum en y."""
    wet_map = wet_cells(water)
    height, width = wet_map.shape
    k = int(math.ceil(reach)) + 1
    x0, x1 = int(math.floor(grid.xs[0])) - k, int(math.floor(grid.xs[-1])) + k
    y0, y1 = int(math.floor(grid.ys[0])) - k, int(math.floor(grid.ys[-1])) + k
    # cellules virtuelles x0..x1, y0..y1 ; hors carte : cellule du bord (bornage)
    ci = np.clip(np.arange(x0, x1 + 1), 0, width - 1)
    cj = np.clip(np.arange(y0, y1 + 1), 0, height - 1)
    wet = wet_map[np.ix_(cj, ci)]
    if not wet.any():
        return None
    # passe 1 : g[j, ix] = min sur i mouillé, |i − x| ≤ k, de dx², dx = écart au carré [i, i+1]
    fx = np.floor(grid.xs).astype(int)
    g = np.full((wet.shape[0], len(grid.xs)), np.inf)
    for off in range(-k, k + 1):
        i = fx + off
        dx = np.maximum(np.maximum(i - grid.xs, grid.xs - (i + 1)), 0.0)
        np.minimum(g, np.where(wet[:, i - x0], dx * dx, np.inf), out=g)
    # passe 2 : D[iy, ix] = min sur j, |j − y| ≤ k, de g[j, ix] + dy²
    fy = np.floor(grid.ys).astype(int)
    d2 = np.full((len(grid.ys), len(grid.xs)), np.inf)
    for off in range(-k, k + 1):
        j = fy + off
        dy = np.maximum(np.maximum(j - grid.ys, grid.ys - (j + 1)), 0.0)
        np.minimum(d2, g[j - y0, :] + (dy * dy)[:, None], out=d2)
    distance = np.sqrt(d2)
    distance[distance > reach] = np.inf
    return distance


def cut_water(field: np.ndarray, grid: Grid, water: WaterMask | np.ndarray,
              band: float) -> tuple[bool, bool, int]:
    """Coupure dans le champ, avant la ligne de niveau : ``field ← max(field,
    band − d)`` (``d`` : ``wet_distance`` à la berge de ``water``, exacte
    jusqu'à ``band + PAD``). Renvoie ``(bitten, changed, wet_nodes)`` : un
    nœud intérieur rendu extérieur (indicateur) ; au moins un nœud du champ
    relevé (la ligne de niveau peut bouger : contour à recalculer) ; nombre
    de nœuds intérieurs AVANT coupure posés dans une cellule mouillée (ou
    sur son bord).

    Précision de la bande : exacte (à l'arrondi flottant près) le long d'une
    berge droite, ``d`` étant affine sur chaque case hors de l'eau. Près
    d'un coin SAILLANT de l'eau (cellule isolée, angle d'un étang), ``d`` est
    la distance à un point, convexe : la ligne de niveau, interpolée
    linéairement entre nœuds, coupe l'arc de rayon ``band`` par des cordes
    d'au plus ``GRID_STEP·√2`` et entre dans la bande d'au plus ≈
    ``GRID_STEP²/(4·band)`` (flèche d'une corde ; ≈ 0,06 bloc en bande 1,
    0,03 en bande 2 ; mesuré : sommets à 0,957 et 1,974, carré d'eau 2×2 sur
    le bord du par 5 droit des tests) ; puis ``resample`` (pas
    ``OUTLINE_STEP``) garde les sommets sur cette ligne, mais les côtés du
    polygone, cordes d'environ ``OUTLINE_STEP``, y ajoutent ≈
    ``OUTLINE_STEP²/(8·band)`` (mesuré : côtés à 0,850 en bande 1 et 1,917
    en bande 2). Mécanisme inchangé : écart rapporté, pas corrigé."""
    distance = wet_distance(grid, water, band + PAD)
    if distance is None:
        return False, False, 0
    inside = field < 0.0
    wet_nodes = int((inside & (distance == 0.0)).sum())
    clear = np.minimum(band - distance, BIG)
    bitten = bool((inside & (clear >= 0.0)).any())
    changed = bool((clear > field).any())
    np.maximum(field, clear, out=field)
    return bitten, changed, wet_nodes


def _nested(loops: list[np.ndarray]) -> list[bool]:
    """Boucle intérieure à une autre (boucles de niveau disjointes : un
    sommet suffit)."""
    return [any(j != i and bool(points_in_polygon(loop[:1], other)[0])
                for j, other in enumerate(loops)) for i, loop in enumerate(loops)]


def water_pieces(field: np.ndarray, grid: Grid,
                 order: int) -> tuple[list[np.ndarray], int]:
    """Boucles extérieures de la ligne de niveau 0 de ``field`` (îlots d'un
    nœud retirés), rééchantillonnées au pas ``OUTLINE_STEP``, aire
    décroissante ; et nombre d'îlots retirés. ``DressingError`` si une
    boucle réelle est intérieure à une autre (eau entourée de fairway)."""
    loops = marching_squares(field, (grid.xs[0], grid.ys[0]), GRID_STEP)
    real = [loop for loop in loops if not is_island(loop, field, grid)]
    islands = len(loops) - len(real)
    if any(_nested(real)):
        raise DressingError(f"trou {order} : eau entourée de fairway (boucle intérieure), "
                            "non représentable par un polygone simple")
    pieces = sorted((resample(loop, OUTLINE_STEP) for loop in real), key=shoelace,
                    reverse=True)
    return pieces, islands


def water_fairway(hole: ElasticHole, core, style: FairwayStyle, rng: np.random.Generator,
                  profile_rng: np.random.Generator, tees, green_outline, obstacles,
                  water: WaterMask | None, cut: WaterCut, *,
                  raw_profile: RawProfile = profile_neck) -> WaterFairway:
    """Fairway de production (``fairway_profile.profiled_field`` : forme
    brute, profil en long, contournement, mêmes flux ``rng`` /
    ``profile_rng``) coupé au-dessus de l'eau ``water`` selon ``cut``.
    ``water`` : eau EFFECTIVE du trou (``water.effective_water(eau réelle,
    (green, *boîtes))``) ; ``None`` : pas d'eau connue, aucune coupure.
    ``DressingError`` si le fairway SANS eau n'a pas exactement une boucle
    réelle (règle de production inchangée) ou si l'eau est entourée de
    fairway (``water_pieces``). Champ modifié par la coupure (``changed``,
    même sans nœud retiré) : contour recalculé par ``water_pieces`` ; champ
    inchangé : ``shapes`` = celui de ``fairway_profile.fairway_shapes``, au
    bit près."""
    built = profiled_field(hole, core, style, rng, profile_rng, tees, green_outline,
                           obstacles, raw_profile=raw_profile)
    field = built.field
    outline, loops, islands = fairway_outline(field, built.grid)
    if loops != 1:
        raise DressingError(f"trou {hole.order} : fairway en {loops} boucles "
                            f"(une seule attendue, style {style.name})")
    bitten, changed, wet_nodes = ((False, False, 0) if water is None
                                  else cut_water(field, built.grid, water, cut.band))
    wet_area = wet_nodes * GRID_STEP * GRID_STEP
    if not changed:
        shape = FairwayShape(outline=tuple((x, y) for x, y in outline.tolist()),
                             area=float(shoelace(outline)))
        return WaterFairway((shape,), (), False, False, False, islands, wet_area)
    pieces, islands = water_pieces(field, built.grid, hole.order)
    kept, removed = [], []
    for piece in pieces:
        area = float(shoelace(piece))
        if area < cut.min_area:
            removed.append(RemovedPiece(area, WATER_CAUSE))
        else:
            kept.append(FairwayShape(outline=tuple((x, y) for x, y in piece.tolist()),
                                     area=area))
    return WaterFairway(tuple(kept), tuple(removed), bitten, True, not pieces, islands,
                        wet_area)
