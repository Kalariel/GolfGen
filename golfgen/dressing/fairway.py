"""Fairway d'un trou : forme brute de PRODUCTION « B v1 à col marqué »
(``profile_neck``, lot 2 R2b, variante K des planches des cols validée par
l'utilisateur, deux styles), et forme brute « B v1 » (lot 2 R2,
``profile_b`` / ``build_fairway``), gardée telle quelle : historique,
référence des planches et empreinte ``tests/data/fairway_b_v1_fingerprint.json``.

B v1 (largeurs en blocs, 1 bloc = 3 m) : demi-largeur ``h(s)`` le long de
l'abscisse curviligne ``s`` de l'axe = demi-col (``neck``, plage de
``FairwayStyle``) partout, relevée en zones de réception aux coudes (par 4
et 5) et, sur les segments droits, aux distances de drive typiques
(``DRIVE`` ; par 5 : lay-up à ``LAYUP`` blocs du drapeau) ; plateau
``ZONE_PLATEAU`` puis raccords en cosinus sur ``ZONE_RAMP`` ; par 3 : col
constant. Profil plafonné à ``plafond − noise_amp``, puis bruit de valeurs
1D (nœuds tous les ``λ`` blocs, raccords cosinus) indépendant à gauche et à
droite, amplitude ``noise_amp`` (±1,5 bloc en links, ±0,5 en parkland),
ramené à 0 sur ``NOISE_TAPER`` blocs aux deux bouts ; plancher
``HALF_MIN``. Plafond : ``hole.width / 2 − CORE_INSET``.

Col marqué (``profile_neck``, constantes PROVISOIRES de ``FairwayStyle`` :
``neck_ratio``, ``neck_min``, ``neck_ramp``, ``width_floor``) : mêmes
tirages que B v1 dans le même ordre (``profile_draws``, puis un bruit par
côté), mêmes zones (``landing_zones``), même plateau de zone (``min(landing
/ 2, plafond − noise_amp)`` par côté). Col UNIQUE par trou : ``neck_ratio``
× la zone la plus étroite, jamais sous ``neck_min`` ni au-dessus de cette
zone ou du col de v1. Raccord zone ↔ col en cosinus sur ``neck_ramp``
blocs ; zones voisines combinées (``1 − Π(1 − poids)``, montée moyenne
pondérée), et, là où deux raccords se chevauchent, au moins le max de v1
(``col + max(poids × montée)``) : le plateau d'une zone n'est jamais abaissé
par sa voisine. Plancher avant bruit ``width_floor / 2`` par côté, ou le
plafond s'il est plus bas (cœur < 7 blocs : largeur = cœur − 1, comme le
clip de v1 ; aucun cœur du corpus, tous ≥ 10). Bruit de v1 (mêmes nœuds,
mêmes octaves) ATTÉNUÉ là où le profil est étroit : facteur ``clip((h −
width_floor / 2) / noise_amp, 0, 1)``, d'où chaque côté ≥ ``width_floor /
2`` après bruit, sans clip (testé). Par 3 et trous sans zone : col de v1,
seul le plancher s'applique.

Formes BRUTES (``build_fairway`` : B v1) : fairway CONTINU du tee routé
(``hole.tee``) au drapeau (``hole.green``), bouts arrondis.

Profil en long (R3 : étendue, carry, avant-green) et contournement des
obstacles : ``golfgen.dressing.fairway_profile``, appliqués par-dessus la
forme brute de production (``build_profiled_fairway``, branché à
``dress_course``) ; empreinte de production
``tests/data/fairway_neck_k_fingerprint.json``.

Contour : champ ``min`` sur les segments de l'axe de ``d(p, q) − h_côté(s)``
(``q`` = projeté de ``p`` sur le segment) sur une grille locale (cadre du
cœur + ``GRID_PAD``, pas ``GRID_STEP``), ligne de niveau 0 par
``golfgen.dressing.offset.marching_squares`` (plus grande boucle retenue,
nombre de boucles rapporté ; ``fairway_profile.fairway_shapes`` lève
``DressingError`` s'il n'y en a pas exactement une, aucune comprise, jamais
de boucle écartée en silence), rééchantillonnée au pas ``OUTLINE_STEP``.
En production (``fairway_outline``), seuls les îlots sont retirés, et
comptés : boucle qui n'entoure qu'un nœud de grille intérieur
(``ISLAND_NODES``), sous la résolution ``GRID_STEP`` (cas réel : bord du
fairway qui rase en biais la garde du green double du trou, selle de
``marching_squares``) ; toute autre boucle surnuméraire lève toujours.
L'inclusion dans le cœur n'est pas clippée : elle découle du plafond et est
vérifiée par les tests (``core_check`` de ``tests/test_dressing_fairway.py``,
corpus 30x2).

Aléa : flux ``golfgen.dressing.rng.fairway_rng`` (``[seed, RNG_LABEL,
order, FAIRWAY_STREAM]``, ``FAIRWAY_STREAM`` = 3), tirages toujours faits
dans le même ordre (``profile_draws`` puis un bruit par côté), les mêmes
pour les deux formes. La forme B v1 est identique au bit près à la colonne B
de l'outil du R1 (empreinte ``tests/data/fairway_b_v1_fingerprint.json``).
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
import math
from types import MappingProxyType
from typing import TYPE_CHECKING

import numpy as np

from golfgen.dressing.green import shoelace
from golfgen.dressing.offset import marching_squares, resample
from golfgen.routing.model import ElasticHole

if TYPE_CHECKING:
    from golfgen.dressing.fairway_profile import LongProfile, Span


# --- constantes PROVISOIRES (B v1, R1 ; à recaler aux R3–R4) -----------------------

CORE_INSET = 0.5                # blocs : plafond de demi-largeur = width/2 − CORE_INSET
HALF_MIN = 3.0                  # blocs : plancher de demi-largeur
DRIVE = (75.0, 88.0)            # blocs depuis le tee (225–265 m), par 4 et 5
LAYUP = (35.0, 50.0)            # blocs avant le drapeau (105–150 m) : lay-up du par 5
ZONE_SEPARATION = 30.0          # blocs : zone de drive omise si un coude est plus près
GREEN_CLEAR = 20.0              # blocs : pas de zone de réception plus près du drapeau
ZONE_PLATEAU = (10.0, 16.0)     # blocs : longueur du plateau d'une zone
ZONE_RAMP = 10.0                # blocs : raccord cosinus de part et d'autre
NOISE_TAPER = 8.0               # blocs : bruit ramené à 0 aux deux bouts
PROFILE_STEP = 0.5              # blocs : table du profil en long
MAX_ZONES = 4                   # tirages de zones toujours faits (flux stable)

GRID_STEP = 0.5                 # blocs : grille locale du champ
GRID_PAD = 2.0                  # blocs autour du cadre du cœur
OUTLINE_STEP = 1.0              # blocs : pas du contour final
ISLAND_NODES = 1                # nœuds de grille : une boucle qui n'entoure pas plus
                                # de nœuds intérieurs est un îlot, sous la résolution
                                # (``fairway_outline``)
BIG = 1e9


@dataclass(frozen=True, slots=True)
class FairwayStyle:
    """Plages et constantes PROVISOIRES d'un style (largeurs en blocs) :
    B v1 (``landing`` à ``noise_octaves``), puis col marqué (R2b,
    ``profile_neck``) ; ``name`` = clé de ``FAIRWAY_STYLES`` (et de
    ``STYLE_SPECS``)."""

    name: str
    landing: tuple[float, float]            # largeur en zone de réception
    neck: tuple[float, float]               # largeur entre zones (col de v1)
    noise_amp: float                        # amplitude du bruit par bord
    noise_octaves: tuple[tuple[float, float], ...]   # (λ blocs, poids)
    neck_ratio: float                       # col marqué = ratio × zone la plus étroite
    neck_min: float                         # col marqué avant bruit jamais plus étroit
    neck_ramp: float                        # raccord cosinus zone ↔ col (v1 : ZONE_RAMP)
    width_floor: float                      # largeur min (2 × plancher par côté)


# Col marqué (R2b), mêmes valeurs PROVISOIRES dans les deux styles (décision
# utilisateur : colonne K, 0,55 × zone) : col ≥ 6,5 blocs (19,5 m) avant
# bruit, raccord sur 15 blocs, largeur ≥ 6 blocs (18 m, ≈ min de B v1).
FAIRWAY_STYLES: Mapping[str, FairwayStyle] = MappingProxyType({
    # links : larges, bords irréguliers (36–45 m en réception, 27–33 m au col de v1)
    "links": FairwayStyle("links", landing=(12.0, 15.0), neck=(9.0, 11.0), noise_amp=1.5,
                          noise_octaves=((24.0, 1.0), (9.0, 0.45)), neck_ratio=0.55,
                          neck_min=6.5, neck_ramp=15.0, width_floor=6.0),
    # parkland : plus étroits, bords nets (31–39 m en réception, 25–30 m au col de v1)
    "parkland": FairwayStyle("parkland", landing=(10.5, 13.0), neck=(8.5, 10.0),
                             noise_amp=0.5, noise_octaves=((40.0, 1.0),), neck_ratio=0.55,
                             neck_min=6.5, neck_ramp=15.0, width_floor=6.0),
})


# --- axe -------------------------------------------------------------------------

@dataclass(frozen=True)
class Axis:
    """Axe du trou (tee, coudes, drapeau) et son abscisse curviligne."""

    points: np.ndarray          # (n, 2)
    starts: np.ndarray          # (n−1,) abscisse curviligne au début de chaque segment
    lengths: np.ndarray         # (n−1,)
    tangents: np.ndarray        # (n−1, 2) unitaires

    @classmethod
    def of(cls, hole: ElasticHole) -> Axis:
        points = np.array([(p.x, p.y) for p in hole.axis], dtype=float)
        delta = np.diff(points, axis=0)
        lengths = np.hypot(delta[:, 0], delta[:, 1])
        starts = np.concatenate(([0.0], np.cumsum(lengths)[:-1]))
        return cls(points, starts, lengths, delta / lengths[:, None])

    @property
    def length(self) -> float:
        return float(self.starts[-1] + self.lengths[-1])

    @property
    def corners(self) -> np.ndarray:
        return self.starts[1:]

    def at(self, s: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        """Points et normales (gauche) de l'axe aux abscisses ``s``."""
        s = np.clip(np.asarray(s, dtype=float), 0.0, self.length)
        index = np.clip(np.searchsorted(self.starts, s, side="right") - 1,
                        0, len(self.lengths) - 1)
        u = self.tangents[index]
        points = self.points[index] + (s - self.starts[index])[:, None] * u
        return points, np.column_stack((-u[:, 1], u[:, 0]))


def cap_half(hole: ElasticHole) -> float:
    """Plafond de demi-largeur : ``width / 2 − CORE_INSET``."""
    return hole.width / 2.0 - CORE_INSET


# --- profil en long ----------------------------------------------------------------

@dataclass(frozen=True)
class Profile:
    s: np.ndarray               # table des abscisses
    left: np.ndarray            # demi-largeur à gauche de l'axe
    right: np.ndarray           # demi-largeur à droite de l'axe
    zones: tuple[float, ...]    # centres des zones de réception
    plateaus: tuple[float, ...] = ()  # longueur du plateau de chaque zone
    base: np.ndarray | None = None    # demi-largeur avant bruit (B v1 ; avant-green, R3)


def _smoothstep(x: np.ndarray) -> np.ndarray:
    x = np.clip(x, 0.0, 1.0)
    return x * x * (3.0 - 2.0 * x)


def _end_taper(s: np.ndarray, length: float, span: float) -> np.ndarray:
    """0 aux deux bouts, 1 au-delà de ``span`` (smoothstep)."""
    return _smoothstep(np.minimum(s, length - s) / span)


def _zone_weight(s: np.ndarray, center: float, plateau: float) -> np.ndarray:
    """1 sur le plateau, raccord cosinus sur ``ZONE_RAMP``, 0 au-delà."""
    x = (np.abs(s - center) - plateau / 2.0) / ZONE_RAMP
    return np.where(x <= 0.0, 1.0, np.where(x >= 1.0, 0.0, 0.5 * (1.0 + np.cos(np.pi * x))))


def landing_zones(axis: Axis, par: int, draws: dict) -> list[float]:
    """Centres des zones de réception : coudes (par 4 et 5), puis distance
    de drive si aucun coude n'est à moins de ``ZONE_SEPARATION`` ; zone de
    lay-up au par 5 (``LAYUP`` avant le drapeau), aux mêmes conditions ;
    rien à moins de ``GREEN_CLEAR`` du drapeau ; au plus ``MAX_ZONES``."""
    if par == 3:
        return []
    limit = axis.length - GREEN_CLEAR
    zones = [float(c) for c in axis.corners if c <= limit]
    targets = [draws["drive"]] + ([axis.length - draws["layup"]] if par == 5 else [])
    for target in targets:
        if target <= limit and all(abs(target - z) >= ZONE_SEPARATION for z in zones):
            zones.append(target)
    return sorted(zones)[:MAX_ZONES]


def profile_draws(rng: np.random.Generator, style: FairwayStyle) -> dict:
    """Tirages du profil, toujours tous et dans le même ordre (flux stable)."""
    return {"neck": rng.uniform(*style.neck), "drive": rng.uniform(*DRIVE),
            "layup": rng.uniform(*LAYUP),
            "landing": rng.uniform(*style.landing, size=MAX_ZONES),
            "plateau": rng.uniform(*ZONE_PLATEAU, size=MAX_ZONES)}


def profile_a(hole: ElasticHole, axis: Axis, style: FairwayStyle,
              rng: np.random.Generator, cap: float) -> Profile:
    """Largeur par tronçons seule (col + zones de réception), plafonnée à
    ``cap`` ; symétrique. Base de ``profile_b``."""
    draws = profile_draws(rng, style)
    zones = landing_zones(axis, hole.par, draws)
    s = np.linspace(0.0, axis.length, int(math.ceil(axis.length / PROFILE_STEP)) + 1)
    neck = draws["neck"] / 2.0
    boost = np.zeros_like(s)
    for k, center in enumerate(zones):
        rise = max(draws["landing"][k] / 2.0 - neck, 0.0)
        boost = np.maximum(boost, rise * _zone_weight(s, center, draws["plateau"][k]))
    half = np.minimum(neck + boost, cap)
    plateaus = tuple(float(v) for v in draws["plateau"][:len(zones)])
    return Profile(s, half, half.copy(), tuple(zones), plateaus)


def value_noise(rng: np.random.Generator, s: np.ndarray, octaves) -> np.ndarray:
    """Bruit de valeurs 1D dans [−1, 1] : nœuds uniformes tous les ``λ``,
    phase tirée, raccords cosinus ; octaves pondérées puis normalisées."""
    total = np.zeros_like(s)
    for wavelength, weight in octaves:
        x = s / wavelength + rng.uniform(0.0, 1.0)
        knots = rng.uniform(-1.0, 1.0, size=int(math.ceil(x[-1])) + 2)
        i = np.floor(x).astype(int)
        w = 0.5 * (1.0 - np.cos(np.pi * (x - i)))
        total += weight * (knots[i] * (1.0 - w) + knots[i + 1] * w)
    return total / sum(weight for _, weight in octaves)


def profile_b(hole: ElasticHole, axis: Axis, style: FairwayStyle,
              rng: np.random.Generator, cap: float) -> Profile:
    """B v1 : ``profile_a`` plafonné à ``cap − noise_amp``, plus un bruit
    par côté (gauche puis droite), ramené à 0 aux bouts, dans
    ``[HALF_MIN, cap]``."""
    base = profile_a(hole, axis, style, rng, cap - style.noise_amp)
    taper = _end_taper(base.s, axis.length, NOISE_TAPER)
    sides = [np.clip(base.left + style.noise_amp * taper
                     * value_noise(rng, base.s, style.noise_octaves), HALF_MIN, cap)
             for _ in range(2)]
    return Profile(base.s, sides[0], sides[1], base.zones, base.plateaus, base.left)


def _ramp_weight(s: np.ndarray, center: float, plateau: float, ramp: float) -> np.ndarray:
    """1 sur le plateau, raccord cosinus sur ``ramp``, 0 au-delà."""
    x = (np.abs(s - center) - plateau / 2.0) / ramp
    return np.where(x <= 0.0, 1.0, np.where(x >= 1.0, 0.0, 0.5 * (1.0 + np.cos(np.pi * x))))


def neck_half(zone_halves, style: FairwayStyle, v1_neck: float) -> float:
    """Demi-col marqué : ``neck_ratio`` × la zone la plus étroite, au moins
    ``neck_min / 2``, jamais au-dessus de cette zone ni du demi-col de v1
    ``v1_neck`` (le col ne fait que descendre)."""
    narrowest = min(zone_halves)
    return min(max(style.neck_ratio * narrowest, style.neck_min / 2.0), narrowest, v1_neck)


def profile_neck(hole: ElasticHole, axis: Axis, style: FairwayStyle,
                 rng: np.random.Generator, cap: float) -> Profile:
    """Forme de production, B v1 à col marqué (docstring du module) : mêmes
    tirages que ``profile_b``, dans le même ordre, aucun de plus ; ``base``
    = demi-largeur avant bruit (symétrique), chaque côté dans
    ``[min(width_floor / 2, cap), cap]``."""
    upper = cap - style.noise_amp
    draws = profile_draws(rng, style)
    zones = landing_zones(axis, hole.par, draws)
    s = np.linspace(0.0, axis.length, int(math.ceil(axis.length / PROFILE_STEP)) + 1)
    plateaus = tuple(float(v) for v in draws["plateau"][:len(zones)])
    if zones:
        halves = [min(draws["landing"][k] / 2.0, upper) for k in range(len(zones))]
        neck = neck_half(halves, style, min(draws["neck"] / 2.0, upper))
        weights = np.array([_ramp_weight(s, c, p, style.neck_ramp)
                            for c, p in zip(zones, plateaus)])
        rises = weights * (np.array(halves) - neck)[:, None]
        total = weights.sum(axis=0)
        rise = np.divide(rises.sum(axis=0), total, out=np.zeros_like(s), where=total > 0.0)
        half = neck + (1.0 - np.prod(1.0 - weights, axis=0)) * rise
        # zones qui se chevauchent : la moyenne pondérée abaisserait le plateau
        # d'une zone sous le sien ; max de v1 (jamais moins que chaque zone)
        overlap = (weights > 0.0).sum(axis=0) >= 2
        half = np.where(overlap, np.maximum(half, neck + rises.max(axis=0)), half)
    else:
        half = np.full_like(s, min(draws["neck"] / 2.0, upper))
    # plancher avant bruit : width_floor / 2, ou le plafond s'il est plus bas
    # (cœur < 7 blocs) ; sans effet si upper ≥ width_floor / 2 (cœurs ≥ 10
    # en links, ≥ 8 en parkland : tout le corpus)
    floor = style.width_floor / 2.0
    half = np.maximum(half, min(floor, cap))
    taper = _end_taper(s, axis.length, NOISE_TAPER)
    if style.noise_amp > 0.0:
        damp = np.clip((half - floor) / style.noise_amp, 0.0, 1.0)
    else:
        damp = np.zeros_like(s)
    sides = [half + style.noise_amp * taper * damp
             * value_noise(rng, s, style.noise_octaves) for _ in range(2)]
    return Profile(s, sides[0], sides[1], tuple(zones), plateaus, half)


# Forme brute d'un trou : ``(trou, axe, style, flux, plafond) -> Profile``
# (``profile_neck`` en production, ``profile_b`` pour B v1).
RawProfile = Callable[[ElasticHole, Axis, FairwayStyle, np.random.Generator, float], Profile]


# --- grille locale et contour --------------------------------------------------------

@dataclass(frozen=True)
class Grid:
    xs: np.ndarray
    ys: np.ndarray

    @classmethod
    def around(cls, polygon) -> Grid:
        polygon = np.asarray(polygon, dtype=float)
        lo, hi = polygon.min(axis=0) - GRID_PAD, polygon.max(axis=0) + GRID_PAD
        nx, ny = (np.ceil((hi - lo) / GRID_STEP).astype(int) + 1).tolist()
        return cls(lo[0] + GRID_STEP * np.arange(nx), lo[1] + GRID_STEP * np.arange(ny))

    def window(self, lo, hi) -> tuple[slice, slice]:
        x0 = max(int(math.floor((lo[0] - self.xs[0]) / GRID_STEP)), 1)
        y0 = max(int(math.floor((lo[1] - self.ys[0]) / GRID_STEP)), 1)
        x1 = min(int(math.ceil((hi[0] - self.xs[0]) / GRID_STEP)) + 1, len(self.xs) - 1)
        y1 = min(int(math.ceil((hi[1] - self.ys[0]) / GRID_STEP)) + 1, len(self.ys) - 1)
        return slice(y0, y1), slice(x0, x1)

    def blank(self) -> np.ndarray:
        # bords à +BIG : lignes de niveau toujours fermées (marching_squares)
        return np.full((len(self.ys), len(self.xs)), BIG)


def strip_field(axis: Axis, profile: Profile, grid: Grid, cap: float) -> np.ndarray:
    """``min`` sur les segments de ``d(p, q) − h_côté(s)``, ``q`` = projeté
    de ``p`` sur le segment (abscisse ``s``), côté jugé par rapport à l'axe ;
    chaque segment ne met à jour que son cadre élargi de ``cap + 3 pas``
    (au-delà, la valeur est > 0 : lignes de niveau inchangées)."""
    field = grid.blank()
    band = cap + 3.0 * GRID_STEP
    for a, u, s0, length in zip(axis.points, axis.tangents, axis.starts, axis.lengths):
        b = a + length * u
        rows, cols = grid.window(np.minimum(a, b) - band, np.maximum(a, b) + band)
        px = (grid.xs[cols] - a[0])[None, :]
        py = (grid.ys[rows] - a[1])[:, None]
        t = np.clip(px * u[0] + py * u[1], 0.0, length)
        s = s0 + t
        d = np.hypot(px - t * u[0], py - t * u[1])
        left = u[0] * py - u[1] * px > 0.0
        h = np.where(left, np.interp(s, profile.s, profile.left),
                     np.interp(s, profile.s, profile.right))
        window = field[rows, cols]
        np.minimum(window, d - h, out=window)
    return field


def is_island(loop: np.ndarray, field: np.ndarray, grid: Grid) -> bool:
    """Boucle qui n'entoure qu'``ISLAND_NODES`` nœud de grille, intérieur
    (champ < 0) : un seul échantillon sous 0, isolé de ses voisins (selle de
    ``marching_squares`` tranchée par la moyenne des coins), sans surface à
    la résolution ``GRID_STEP`` (aire < 2 ``GRID_STEP``²). Les sommets
    d'une boucle sont sur les arêtes de grille, au plus à un pas du nœud
    entouré : les nœuds strictement dans son cadre sont ceux qu'elle
    entoure. Un trou d'un nœud (champ > 0) n'est pas un îlot ; une boucle
    dégénérée dont le cadre ne contient aucun nœud (trou d'un nœud à champ
    exactement 0 : sommets confondus sur le nœud) non plus."""
    lo, hi = loop.min(axis=0), loop.max(axis=0)
    cols = np.nonzero((grid.xs > lo[0]) & (grid.xs < hi[0]))[0]
    rows = np.nonzero((grid.ys > lo[1]) & (grid.ys < hi[1]))[0]
    return (0 < len(rows) * len(cols) <= ISLAND_NODES
            and bool((field[np.ix_(rows, cols)] < 0.0).all()))


def fairway_outline(field: np.ndarray, grid: Grid) -> tuple[np.ndarray, int, int]:
    """Contour du fairway de production : plus grande boucle de la ligne de
    niveau 0, îlots (``is_island``) retirés EXPLICITEMENT et comptés,
    rééchantillonnée au pas ``OUTLINE_STEP`` ; renvoie ``(contour, boucles
    réelles, îlots retirés)``. Les boucles réelles restent toutes comptées
    (l'appelant lève s'il n'y en a pas exactement une) ; sans boucle réelle,
    contour vide ``(0, 2)``."""
    loops = marching_squares(field, (grid.xs[0], grid.ys[0]), GRID_STEP)
    real = [loop for loop in loops if not is_island(loop, field, grid)]
    islands = len(loops) - len(real)
    if not real:
        return np.empty((0, 2)), 0, islands
    return resample(max(real, key=shoelace), OUTLINE_STEP), len(real), islands


def level_outline(field: np.ndarray, grid: Grid) -> tuple[np.ndarray, int]:
    """Plus grande boucle (aire signée) de la ligne de niveau 0, et nombre de
    boucles ; sans boucle, contour vide ``(0, 2)`` et 0 (l'appelant lève)."""
    loops = marching_squares(field, (grid.xs[0], grid.ys[0]), GRID_STEP)
    if not loops:
        return np.empty((0, 2)), 0
    return max(loops, key=shoelace), len(loops)


# --- fairway d'un trou -----------------------------------------------------------------

@dataclass(frozen=True)
class FairwayBuild:
    """Construction interne : contour (non arrondi, ``OUTLINE_STEP``),
    nombre de boucles de la ligne de niveau (1 attendu) et profil ; avec le
    profil en long (R3, ``golfgen.dressing.fairway_profile``) : choix tirés,
    étendue, obstacles qui ont mordu, et îlots retirés (``fairway_outline`` :
    ``loops`` ne compte alors que les boucles réelles ; B v1, ``build_fairway``,
    ne retire rien)."""

    outline: np.ndarray
    loops: int
    profile: Profile
    plan: LongProfile | None = None
    span: Span | None = None
    bitten: tuple[str, ...] = ()
    islands: int = 0


def _outline(field: np.ndarray, grid: Grid) -> tuple[np.ndarray, int]:
    outline, loops = level_outline(field, grid)
    return (resample(outline, OUTLINE_STEP) if loops else outline), loops


def build_fairway(hole: ElasticHole, core, style: FairwayStyle,
                  rng: np.random.Generator) -> FairwayBuild:
    """Forme BRUTE B v1 (historique, référence ; la production passe par
    ``profile_neck``) du trou ``hole`` (cœur ``core`` : cadre de la grille),
    continue du tee au drapeau, tirages pris dans ``rng`` (``fairway_rng`` du
    trou) ; empreinte ``tests/data/fairway_b_v1_fingerprint.json``."""
    axis = Axis.of(hole)
    cap = cap_half(hole)
    grid = Grid.around(core)
    profile = profile_b(hole, axis, style, rng, cap)
    outline, loops = _outline(strip_field(axis, profile, grid, cap), grid)
    return FairwayBuild(outline, loops, profile)
