"""Lot 2 R4 : coupure du fairway au-dessus de l'eau
(``golfgen.dressing.fairway_water``), branchée à ``dress_course`` (R4c,
``FAIRWAY_WATER_CUT`` : bande 2, aire minimale 5 blocs²). L'eau est l'eau
EFFECTIVE du trou
(``golfgen.dressing.water.effective_water``), distance mesurée à la berge
(bord de la cellule mouillée).

Cas synthétiques sur un par 5 droit de l'instantané (400x300/1 trou 2,
fairway de x ≈ 77 à 199, y ≈ 251–263) : distance au bord exacte (contre un
calcul brut), bande respectée (bandes 1 et 2, y compris eau juste au-delà
du bord sans nœud retiré : contour recalculé), fairway coupé en deux,
fragment trop petit retiré et compté (cause « eau »), fairway noyé ou vidé
explicite (aussi de bout en bout dans ``dress_course`` : noyé, fragments
trop petits, cause ``None`` dès qu'un morceau reste), eau entourée de
fairway → ``DressingError``, règle d'une seule
boucle avant la coupure, sans eau (``None``, masque vide, eau hors de
portée, hors de la fenêtre de calcul ou dedans) : ``fairway_shapes`` au bit
près. Corpus de l'instantané 30x2 (reliefs ``load_terrain``, eau effective
de chaque trou, ``dress_course`` avec le relief habillé une fois pour tout
le module) : en bande 1, aire minimale 0, tout trou dont la coupure ne
modifie pas le champ garde le fairway sans eau au bit près, seule erreur
l'eau entourée relevée (``ENCLOSED_BAND_1``) ; le fairway de
``dress_course`` est celui de ``water_fairway`` à la coupure de production
(bande 2, 5 blocs²) sur l'eau effective du trou, retirés de cause « eau », cause du vide si et
seulement si fairway vide, aucune erreur ; empreinte « fairway avec eau »
(``tests/data/fairway_water_fingerprint.json``) ; le cas d'eau entourée en
bande 1 s'ouvre en bande 2 (un morceau simple).
"""

from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import pytest

from golfgen.dressing import STYLE_SPECS, DressingError, dress_course, effective_water
from golfgen.dressing import fairway as fw
from golfgen.dressing import fairway_profile as fwp
from golfgen.dressing import fairway_water as fww
from golfgen.dressing.course import fairway_profile_rng, fairway_rng
from golfgen.dressing.fairway_water import (FAIRWAY_WATER_CUT, WATER_CAUSE, RemovedPiece,
                                            WaterCut, cut_water, water_fairway, wet_distance)
from golfgen.dressing.pair_shape import is_simple
from golfgen.dressing.water import footprint_cells
from golfgen.exporter import _features_v31, _strictly_simple
from golfgen.routing.geometry import build_hole_geometry
from golfgen.routing.sites import WATER_LEVEL, WaterMask, water_mask
from tests import fairway_fingerprint as ff

SEED = 5
STYLE = "links"
MAP = (300, 400)                 # (h, w) de 400x300
STRIPE = (130, 133)              # colonnes d'eau x ∈ [130, 133] : coupe le fairway en travers
# Contour à au moins ``band`` de la berge, à l'arrondi près : la ligne de
# niveau interpole linéairement le champ sur chaque arête, champ ≥ band − d
# aux deux nœuds, et d (distance à une bande ou un demi-plan d'eau) est
# affine sur toute case hors de l'eau ; le rééchantillonnage reste sur la
# ligne brisée. Seule l'erreur d'arrondi flottant reste : 1e-6. Vrai pour
# une berge DROITE seulement : près d'un coin saillant de l'eau, d n'est plus
# affine (distance à un point) et la ligne interpolée entre nœuds entre dans
# la bande d'au plus ≈ GRID_STEP²/(4·band) (sommets), les côtés du contour
# rééchantillonné d'environ OUTLINE_STEP²/(8·band) de plus
# (``cut_water`` ; ``test_band_square_corner``).
EPS = 1e-6
# Carré d'eau 2×2 (x0, y0) mordant le bord du par 5 droit, position la plus
# défavorable relevée pour chaque bande (coins saillants) ; sommets du
# contour à au moins band − corner_vertex(band), borne documentée
# GRID_STEP²/(4·band) de ``cut_water`` (mesuré 0,957 et 1,974) ; côtés
# du polygone (points des segments) à au moins band − corner_side(band)
# (mesuré 0,850 et 1,917).
SQUARE_CORNER = [(1.0, (154, 260)), (2.0, (152, 258))]


def corner_vertex(band: float) -> float:
    """Entrée maximale attendue des sommets dans la bande près d'un coin
    saillant (``cut_water``) : ``GRID_STEP²/(4·band)``."""
    return fw.GRID_STEP ** 2 / (4.0 * band)


def corner_side(band: float) -> float:
    """Entrée maximale attendue des côtés dans la bande près d'un coin :
    flèche des cordes de la grille (``GRID_STEP·√2``) et du
    rééchantillonnage (``OUTLINE_STEP``) sur un arc de rayon ``band``."""
    return (2.0 * fw.GRID_STEP ** 2 + fw.OUTLINE_STEP ** 2) / (8.0 * band)
# Eau sur les lignes y ≥ y0 juste au-delà du bord du fairway (y max ≈ 263,12) :
# aucun nœud intérieur ne devient extérieur, mais des nœuds de part et
# d'autre de la ligne sont relevés : la berge de production y serait à
# 0,876 (bande 1) et 1,876 (bande 2) blocs.
EDGE_WATER = [(1.0, 264), (2.0, 265)]
# Corpus, bande 1, aire minimale 0 (mécanisme, pas la coupure de
# production) : seule eau entourée de fairway relevée (links, 300x400 seed
# 28, trou 8) ; la règle n'est pas assouplie, le cas est rapporté. En bande
# 2 (``FAIRWAY_WATER_CUT``), l'encoche d'environ 4,5 blocs s'ouvre sur le
# bord est : un seul morceau simple (``ENCLOSED_BAND_2_AREA``).
ENCLOSED_BAND_1 = {("links", "300x400", 28, 8)}
ENCLOSED_BAND_2_AREA = 548.2     # blocs², à 0,05 près


@pytest.fixture(scope="module")
def straight():
    """Par 5 droit 400x300/1 trou 2, habillé seul (links, seed 5) : trou,
    cœur, habillage du trou, obstacles."""
    hole = next(h for label, h in ff.sample_holes() if label.startswith("400x300/1#2 "))
    core = build_hole_geometry(hole).core
    dressing = dress_course(SimpleNamespace(layout=SimpleNamespace(holes=(hole,))), seed=SEED,
                            style=STYLE)
    return (hole, core, dressing[hole.order],
            fwp.fairway_obstacles(dressing.holes, dressing.green_pairs))


def _cut(straight, water, band, min_area=0.0):
    hole, core, hd, obstacles = straight
    return water_fairway(hole, core, fw.FAIRWAY_STYLES[STYLE], fairway_rng(SEED, hole.order),
                         fairway_profile_rng(SEED, hole.order), hd.tees, hd.green.outline,
                         obstacles, water, WaterCut(band, min_area))


def _field(straight):
    hole, core, hd, obstacles = straight
    return fwp.profiled_field(hole, core, fw.FAIRWAY_STYLES[STYLE],
                              fairway_rng(SEED, hole.order), fairway_profile_rng(SEED, hole.order),
                              hd.tees, hd.green.outline, obstacles)


def _stripe() -> WaterMask:
    wet = np.zeros(MAP, dtype=bool)
    wet[:, STRIPE[0]:STRIPE[1]] = True
    return WaterMask(water=wet)


def _stripe_distance(x: np.ndarray) -> np.ndarray:
    """Distance à la berge de la bande d'eau ``[130, 133] × tout y``."""
    return np.maximum(np.maximum(STRIPE[0] - x, x - STRIPE[1]), 0.0)


# --- distance à la berge ---------------------------------------------------------------

def test_wet_distance_is_shore_distance():
    """``wet_distance`` = distance au BORD (carré fermé) de la cellule
    mouillée la plus proche, exacte jusqu'à ``reach`` (calcul brut), ``inf``
    au-delà ; même résultat pour ``WaterMask`` et tableau booléen ; un nœud
    à 1 bloc du bord d'une cellule est à 1, pas à 1,5 (centre)."""
    rng = np.random.default_rng(7)
    wet = rng.random((24, 30)) < 0.04
    grid = fw.Grid(xs=3.0 + 0.5 * np.arange(40), ys=2.5 + 0.5 * np.arange(36))
    reach = 3.0
    got = wet_distance(grid, WaterMask(water=wet), reach)
    assert np.array_equal(got, wet_distance(grid, wet, reach))
    iy, ix = np.nonzero(wet)
    px, py = grid.xs[None, :, None], grid.ys[:, None, None]
    dx = np.maximum(np.maximum(ix - px, px - (ix + 1)), 0.0)
    dy = np.maximum(np.maximum(iy - py, py - (iy + 1)), 0.0)
    brute = np.sqrt(dx * dx + dy * dy).min(axis=2)
    near = brute <= reach
    assert near.any() and (~near).any()
    assert np.allclose(got[near], brute[near], rtol=0.0, atol=1e-12)
    assert np.isinf(got[~near]).all()
    single = np.zeros((10, 10), dtype=bool)
    single[5, 5] = True
    point = fw.Grid(xs=np.array([4.0, 5.5, 7.0]), ys=np.array([5.5]))
    assert wet_distance(point, single, 3.0).tolist() == [[1.0, 0.0, 1.0]]
    assert wet_distance(point, np.zeros((10, 10), dtype=bool), 3.0) is None
    with pytest.raises(ValueError):
        wet_distance(point, single.astype(int), 3.0)


@pytest.mark.parametrize("band", [1.0, 2.0])
def test_band_respected(straight, band):
    """Aucun nœud intérieur après la coupure à moins de ``band`` de la
    berge (distance analytique à la bande d'eau) ; sommets du contour à au
    moins ``band`` (à l'arrondi ``EPS`` près, voir ``EPS``)."""
    built = _field(straight)
    field = built.field.copy()
    bitten, changed, wet_nodes = cut_water(field, built.grid, _stripe(), band)
    assert bitten and changed and wet_nodes > 0
    inside = field < 0.0
    distance = np.broadcast_to(_stripe_distance(built.grid.xs)[None, :], field.shape)
    assert inside.any()
    assert distance[inside].min() >= band
    assert (field[~(built.field < 0.0)] >= 0.0).all()          # rien n'est ajouté
    result = _cut(straight, _stripe(), band)
    for shape in result.shapes:
        outline = np.array(shape.outline)
        assert _stripe_distance(outline[:, 0]).min() >= band - EPS


@pytest.mark.parametrize("band, y0", EDGE_WATER)
def test_band_respected_edge_water(straight, band, y0):
    """Eau juste au-delà du bord (lignes y ≥ y0), aucun nœud intérieur
    rendu extérieur (``bitten`` faux) : le champ est pourtant modifié
    (``changed``), le contour est recalculé et respecte la bande ; celui de
    production ne la respecte pas."""
    hd = straight[2]
    wet = np.zeros(MAP, dtype=bool)
    wet[y0:, :] = True
    production = np.array(hd.fairway[0].outline)
    assert y0 - production[:, 1].max() < band - 0.1
    result = _cut(straight, WaterMask(water=wet), band)
    assert not result.bitten and result.changed
    assert not result.drowned and result.removed == () and len(result.shapes) == 1
    outline = np.array(result.shapes[0].outline)
    assert (y0 - outline[:, 1]).min() >= band - EPS


def _square_distance(points: np.ndarray, x0: int, y0: int, size: int) -> np.ndarray:
    """Distance des points au carré d'eau ``[x0, x0 + size] × [y0, y0 + size]``."""
    dx = np.maximum(np.maximum(x0 - points[:, 0], points[:, 0] - (x0 + size)), 0.0)
    dy = np.maximum(np.maximum(y0 - points[:, 1], points[:, 1] - (y0 + size)), 0.0)
    return np.hypot(dx, dy)


@pytest.mark.parametrize("band, corner", SQUARE_CORNER)
def test_band_square_corner(straight, band, corner):
    """Carré d'eau 2×2 mordant le bord : la bande n'est exacte que le long
    d'une berge droite ; près des coins saillants, sommets à au moins
    ``band − corner_vertex(band)`` et côtés du polygone à au moins ``band −
    corner_side(band)`` (voir ``cut_water``) ; la bande mord vraiment (contour
    à moins de ``band + 0,25`` du carré)."""
    x0, y0 = corner
    wet = np.zeros(MAP, dtype=bool)
    wet[y0:y0 + 2, x0:x0 + 2] = True
    result = _cut(straight, WaterMask(water=wet), band)
    assert result.bitten and result.changed and len(result.shapes) == 1
    outline = np.array(result.shapes[0].outline)
    vertices = _square_distance(outline, x0, y0, 2)
    t = np.linspace(0.0, 1.0, 41)[:, None, None]
    sides = (outline[None] * (1.0 - t) + np.roll(outline, -1, axis=0)[None] * t).reshape(-1, 2)
    sides = _square_distance(sides, x0, y0, 2)
    assert vertices.min() >= band - corner_vertex(band)
    assert sides.min() >= band - corner_side(band)
    assert sides.min() < band + 0.25


# --- morceaux -------------------------------------------------------------------------

def test_cut_in_two(straight):
    """Bande d'eau en travers : deux morceaux, aire décroissante, un de
    chaque côté, aucun retiré, aire totale inférieure à celle sans eau."""
    hd = straight[2]
    result = _cut(straight, _stripe(), 1.0)
    assert result.bitten and not result.drowned and not result.empty
    assert result.empty_cause is None and result.removed == ()
    assert len(result.shapes) == 2
    big, small = result.shapes
    assert big.area >= small.area > 0.0
    sides = sorted(np.array(s.outline)[:, 0].max() < STRIPE[0] for s in result.shapes)
    assert sides == [False, True]
    assert all(np.array(s.outline)[:, 0].min() > STRIPE[1] or np.array(s.outline)[:, 0].max()
               < STRIPE[0] for s in result.shapes)
    assert big.area + small.area < hd.fairway[0].area
    assert result.wet_area > 0.0


def test_small_fragment_removed(straight):
    """Fragment d'aire < ``min_area`` retiré et compté (cause « eau ») ; le
    morceau gardé est inchangé ; tous retirés : vide explicite
    (« fragments trop petits »)."""
    free = _cut(straight, _stripe(), 1.0)
    big, small = free.shapes
    cut = _cut(straight, _stripe(), 1.0, min_area=(big.area + small.area) / 2.0)
    assert cut.shapes == (big,)
    assert cut.removed == (RemovedPiece(small.area, WATER_CAUSE),)
    gone = _cut(straight, _stripe(), 1.0, min_area=big.area + 1.0)
    assert gone.empty and not gone.drowned
    assert gone.empty_cause == f"{WATER_CAUSE} : fragments trop petits"
    assert gone.removed == (RemovedPiece(big.area, WATER_CAUSE),
                            RemovedPiece(small.area, WATER_CAUSE))


def test_drowned(straight):
    """Fairway entièrement sous l'eau : aucun morceau, noyé, vide explicite."""
    result = _cut(straight, WaterMask(water=np.ones(MAP, dtype=bool)), 1.0)
    assert result.bitten and result.drowned and result.empty
    assert result.shapes == () and result.removed == ()
    assert result.empty_cause == f"{WATER_CAUSE} : noyé"


def test_enclosed_water_raises(straight):
    """Une cellule d'eau au cœur du fairway (nœud le plus intérieur) :
    boucle intérieure, ``DressingError``, jamais bouchée en silence."""
    built = _field(straight)
    iy, ix = np.unravel_index(np.argmin(built.field), built.field.shape)
    assert built.field[iy, ix] < -4.0
    wet = np.zeros(MAP, dtype=bool)
    wet[int(built.grid.ys[iy]), int(built.grid.xs[ix])] = True
    with pytest.raises(DressingError, match=rf"trou {straight[0].order} : eau entourée"):
        _cut(straight, WaterMask(water=wet), 1.0)


def test_single_loop_rule_before_cut(straight, monkeypatch):
    """Règle de production inchangée AVANT la coupure : un fairway sans eau
    à deux boucles lève ``DressingError``, même sans eau."""
    real = fww.fairway_outline
    monkeypatch.setattr(fww, "fairway_outline",
                        lambda field, grid: (real(field, grid)[0], 2, 0))
    with pytest.raises(DressingError, match=rf"trou {straight[0].order} : fairway en 2 boucles"):
        _cut(straight, None, 1.0)


def test_water_cut_params():
    with pytest.raises(ValueError):
        WaterCut(0.0)
    with pytest.raises(ValueError):
        WaterCut(1.0, -1.0)


# --- vide de bout en bout (dress_course) ---------------------------------------------------

# Îlots secs (x0, y0, côté) dans le fairway du par 5 droit (y ≈ 251–263),
# carte entièrement en eau sauf eux et l'emprise du green et des boîtes :
# côté 6 → morceau de ≈ 2 × 2 blocs après la bande 2 (< 5 b², retiré) ;
# côté 10 → ≈ 6 × 6 (gardé).
DRY_PATCHES = {
    "noyé": ((), 0, 0, f"{WATER_CAUSE} : noyé"),
    "fragment": (((130, 254, 6),), 0, 1, f"{WATER_CAUSE} : fragments trop petits"),
    "un morceau": (((130, 254, 10),), 1, 0, None),
    "deux morceaux": (((130, 254, 10), (170, 254, 10)), 2, 0, None),
}


@pytest.mark.parametrize("name", list(DRY_PATCHES))
def test_dress_course_empty_cause(straight, name):
    """Cas fabriqués, de bout en bout dans ``dress_course`` avec un relief :
    eau partout sauf l'emprise du green et des boîtes (au sec, aucun repli :
    ``water_fix`` vide, green et boîtes inchangés) et des îlots secs dans le
    fairway. Sans îlot : fairway ``()``, cause « eau : noyé » ; îlot trop
    petit après la bande : fairway ``()``, fragment retiré (cause « eau »),
    cause « eau : fragments trop petits » ; un ou deux morceaux gardés :
    cause ``None``."""
    patches, kept, removed, cause = DRY_PATCHES[name]
    hole, _, plain, _ = straight
    dry = np.zeros(MAP, dtype=bool)
    for outline in [plain.green.outline] + [box.outline for box in plain.tees]:
        cells = footprint_cells(outline, MAP[1], MAP[0])
        dry[cells[:, 1], cells[:, 0]] = True
    for x0, y0, side in patches:
        dry[y0:y0 + side, x0:x0 + side] = True
    relief = np.where(dry, WATER_LEVEL + 5.0, WATER_LEVEL - 5.0)
    hd = dress_course(SimpleNamespace(layout=SimpleNamespace(holes=(hole,))), seed=SEED,
                      style=STYLE, relief=relief)[hole.order]
    assert hd.water_fix is None
    assert (hd.green, hd.tees) == (plain.green, plain.tees)
    assert len(hd.fairway) == kept and len(hd.fairway_removed) == removed
    assert all(p.cause == WATER_CAUSE and p.area < FAIRWAY_WATER_CUT.min_area
               for p in hd.fairway_removed)
    assert all(shape.area >= FAIRWAY_WATER_CUT.min_area for shape in hd.fairway)
    assert hd.fairway_empty_cause == cause
    assert (hd.fairway_empty_cause is None) == (hd.fairway != ())


# --- sans eau qui morde : production au bit près ----------------------------------------

def test_no_water_is_production(straight):
    """``water = None``, masque sans eau, eau hors de la fenêtre de calcul
    (coin de la carte : ``wet_distance`` renvoie ``None``), eau dans la
    fenêtre mais au-delà de la portée ``band + PAD`` (distance ``inf``
    partout) : ``fairway_shapes`` de production au bit près, champ
    inchangé, rien de mordu."""
    hd = straight[2]
    grid = _field(straight).grid
    far = np.zeros(MAP, dtype=bool)
    far[:20, :20] = True
    for band in (1.0, 2.0):
        reach = band + fww.PAD
        k = int(np.ceil(reach)) + 1
        # dernière ligne de cellules de la fenêtre, au-dessus de la grille :
        # distance au nœud le plus proche dans (k − 1, k], donc > reach
        row = int(np.floor(grid.ys[-1])) + k
        assert row < MAP[0]
        window = np.zeros(MAP, dtype=bool)
        window[row, int(grid.xs[len(grid.xs) // 2])] = True
        assert wet_distance(grid, far, reach) is None
        beyond = wet_distance(grid, window, reach)
        assert beyond is not None and np.isinf(beyond).all()
        for water in (None, WaterMask.none(MAP[1], MAP[0]), WaterMask(water=far),
                      WaterMask(water=window)):
            result = _cut(straight, water, band, min_area=1e6)
            assert result.shapes == hd.fairway
            assert not result.bitten and not result.changed
            assert not result.drowned and result.removed == ()
            assert result.wet_area == 0.0


@pytest.fixture(scope="module")
def relief_corpus():
    """Instantané 30x2 habillé AVEC le relief (``dress_course``, coupure de
    production), une seule fois pour le module : ``[(taille, seed, style,
    trous, eau réelle, habillage, obstacles)]`` ; aucune ``DressingError``
    (pas d'eau entourée en bande 2)."""
    rows = []
    for label, style, holes, relief, dressing in ff.water_dressings():
        size, seed = label.split("/")
        rows.append((size, int(seed), style, holes, water_mask(relief), dressing,
                     fwp.fairway_obstacles(dressing.holes, dressing.green_pairs)))
    return rows


def _corpus_cut(row, hole, water, cut):
    size, seed, style, holes, _, dressing, obstacles = row
    hd = dressing[hole.order]
    return water_fairway(hole, build_hole_geometry(hole).core, fw.FAIRWAY_STYLES[style],
                         fairway_rng(seed, hole.order), fairway_profile_rng(seed, hole.order),
                         hd.tees, hd.green.outline, obstacles, water, cut)


def test_corpus_unbitten_is_production(relief_corpus):
    """Instantané 30x2 (60 parcours, deux styles), relief ``load_terrain``,
    eau effective de chaque trou, bande 1, aire minimale 0 : tout trou dont
    la coupure ne modifie pas le champ garde le fairway sans eau
    (``fairway_profile.fairway_shapes``) au bit près ; seule erreur, l'eau
    entourée de fairway relevée (``ENCLOSED_BAND_1``)."""
    changed = dict.fromkeys(STYLE_SPECS, 0)
    unbitten = dict.fromkeys(STYLE_SPECS, 0)
    enclosed = set()
    for row in relief_corpus:
        size, seed, style, holes, water, dressing, obstacles = row
        for hole in holes:
            hd = dressing[hole.order]
            try:
                result = _corpus_cut(row, hole, effective_water(water, (hd.green, *hd.tees)),
                                     WaterCut(1.0))
            except DressingError as exc:
                assert "eau entourée de fairway" in str(exc)
                enclosed.add((style, size, seed, hole.order))
                continue
            if result.changed:
                changed[style] += 1
                continue
            unbitten[style] += 1
            free = fwp.fairway_shapes(hole, build_hole_geometry(hole).core,
                                      fw.FAIRWAY_STYLES[style], fairway_rng(seed, hole.order),
                                      fairway_profile_rng(seed, hole.order), hd.tees,
                                      hd.green.outline, obstacles)
            assert result.shapes == free, (size, seed, hole.order, style)
    assert enclosed == ENCLOSED_BAND_1
    assert all(n > 0 for n in changed.values())
    assert all(n > 1000 for n in unbitten.values())


def test_production_cut_values():
    """Coupure de production validée sur planches (R4b) : bande 2, 5 blocs²."""
    assert FAIRWAY_WATER_CUT == WaterCut(2.0, 5.0)


def test_corpus_dress_course_is_water_fairway(relief_corpus):
    """Instantané 30x2, deux styles : le fairway de ``dress_course`` avec
    le relief (morceaux, retirés, cause du vide) est, trou par trou, celui
    de ``water_fairway`` à la coupure ``FAIRWAY_WATER_CUT`` sur l'eau
    effective du trou ; morceaux par aire décroissante ; retirés de cause
    « eau », d'aire < aire minimale ; cause du vide renseignée si et
    seulement si le fairway est vide ; l'eau coupe vraiment (trous à
    plusieurs morceaux, fragments retirés)."""
    cut = FAIRWAY_WATER_CUT
    multi = removed = 0
    for row in relief_corpus:
        size, seed, style, holes, water, dressing, obstacles = row
        for hole in holes:
            hd = dressing[hole.order]
            column = _corpus_cut(row, hole, effective_water(water, (hd.green, *hd.tees)), cut)
            key = (size, seed, hole.order, style)
            assert hd.fairway == column.shapes, key
            assert hd.fairway_removed == column.removed, key
            assert hd.fairway_empty_cause == column.empty_cause, key
            areas = [shape.area for shape in hd.fairway]
            assert areas == sorted(areas, reverse=True), key
            assert all(p.cause == WATER_CAUSE and p.area < cut.min_area
                       for p in hd.fairway_removed), key
            assert (hd.fairway_empty_cause is not None) == (hd.fairway == ()), key
            multi += len(hd.fairway) > 1
            removed += len(hd.fairway_removed)
    assert multi > 0 and removed > 0


def test_water_fingerprint(relief_corpus):
    """Empreinte « fairway avec eau » (``tests/fairway_fingerprint.py``,
    ``WATER_FINGERPRINT``) : fairway coupé de ``dress_course`` avec le
    relief, instantané 30x2, deux styles, au bit près."""
    got = ff.water_fingerprint((f"{size}/{seed}", style, dressing)
                               for size, seed, style, _, _, dressing, _ in relief_corpus)
    ref = ff.load(ff.WATER_FINGERPRINT)
    assert got["cases"] == ref["cases"]
    assert got["digest"] == ref["digest"]


def test_enclosed_band_1_opens_at_band_2(relief_corpus):
    """Le cas d'eau entourée en bande 1 (``ENCLOSED_BAND_1`` : links,
    300x400 seed 28, trou 8) lève toujours en bande 1 (mécanisme) ; avec la
    coupure de production (bande 2, 5 blocs²), l'encoche d'environ 4,5
    blocs s'ouvre sur le bord est : exactement un morceau, polygone simple,
    rien de retiré, aucune erreur, aire ≈ ``ENCLOSED_BAND_2_AREA`` ; c'est
    le fairway de ``dress_course``."""
    ((style, size, seed, order),) = ENCLOSED_BAND_1
    row = next(r for r in relief_corpus if (r[2], r[0], r[1]) == (style, size, seed))
    hole = next(h for h in row[3] if h.order == order)
    hd = row[5][order]
    water = effective_water(row[4], (hd.green, *hd.tees))
    with pytest.raises(DressingError, match=rf"trou {order} : eau entourée de fairway"):
        _corpus_cut(row, hole, water, WaterCut(1.0))
    result = _corpus_cut(row, hole, water, FAIRWAY_WATER_CUT)
    assert result.changed and result.removed == () and result.empty_cause is None
    (shape,) = result.shapes
    assert is_simple(np.array(shape.outline))
    assert shape.area == pytest.approx(ENCLOSED_BAND_2_AREA, abs=0.05)
    assert hd.fairway == result.shapes and hd.fairway_removed == ()


def test_corpus_fairway_export(relief_corpus):
    """``features.fairway`` (R5a) sur tout l'instantané 30x2 habillé avec le
    relief, deux styles : clé toujours présente, morceaux dans l'ordre du
    modèle (aire décroissante), contours arrondis à 2 décimales strictement
    simples (aucune ``ValueError`` de l'export), aire arrondie ; au moins un
    trou à plusieurs morceaux (l'ordre est exercé)."""
    multi = 0
    for _, _, _, _, _, dressing, _ in relief_corpus:
        for hd in dressing.holes.values():
            pieces = _features_v31(hd)["fairway"]
            assert isinstance(pieces, list) and len(pieces) == len(hd.fairway)
            for item, shape in zip(pieces, hd.fairway):
                assert list(item) == ["outline", "area"]
                assert item["outline"] == [{"x": round(x, 2), "y": round(y, 2)}
                                           for x, y in shape.outline]
                assert item["area"] == round(shape.area, 2)
                outline = np.array([(q["x"], q["y"]) for q in item["outline"]])
                assert _strictly_simple(outline) and is_simple(outline)
            areas = [item["area"] for item in pieces]
            assert areas == sorted(areas, reverse=True)
            multi += len(pieces) > 1
    assert multi > 0
