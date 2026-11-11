"""Pots : motifs de cases, tailles mêlées et géométrie des grappes (round R1).

Pot = motif fixe de cases autour d'une base entière : grand (8 cases,
``PATTERN``) ou petit (5 cases, ``SMALL_PATTERN``) ; au moins
``MIN_GRASS`` blocs d'herbe entre deux pots (``cell_gap``).

Pots de green : nombre 2/3/4 tiré selon la largeur d'approche
(``count_probs``, flux ``[seed, RNG_LABEL, order, CLUSTER_STREAM, rôle]``),
motif tourné/miroir/bruité (``candidate_outlines``, contours lisses
``pot_outline``), grappe raster rigide (``group_at`` : étalement et recul),
tailles mêlées (``mixed_sizes``, flux ``MIX_STREAM``).

Pots d'appel : nombre 2 ou 3 (``desired_count``, flux ``COUNT_STREAM``),
duo en ligne décalée (``stagger_offsets``, ``landing_group``,
``shared_spacing``) ou trio à trois centres libres (``raster_group``).

Cette géométrie est pure : sites, ancres, choix légal et contrôles
(carte, marges, fairway) relèvent des rounds suivants.
"""

from __future__ import annotations

import math

import numpy as np

from golfgen.dressing.rng import RNG_LABEL
from golfgen.dressing.bunkers.beans import ROLE_IDS
from golfgen.dressing.bunkers.errors import BunkerError
from golfgen.dressing.bunkers.raster import cell_gap

PATTERN = ("HSH", "SSS", "SSS", "HSH")
SMALL_PATTERN = ("HSH", "SSS", "HSH")
# Coin bas-gauche des cases autour de la base entière ; lignes de haut en bas.
OFFSETS = np.array([(x, y) for y, row in zip((-2, -1, 0, 1), PATTERN)
                    for x, char in zip((-1, 0, 1), row) if char == "S"], dtype=int)
SMALL_OFFSETS = np.array([(x, y) for y, row in zip((-1, 0, 1), SMALL_PATTERN)
                          for x, char in zip((-1, 0, 1), row) if char == "S"], dtype=int)
MIN_GRASS = 3.0
# Flux des pots, tous ``[seed, RNG_LABEL, order, STREAM, rôle, ...]``.
CLUSTER_STREAM = 7   # nombre et motif des pots de green
MIX_STREAM = 8       # tailles des pots de green
STAGGER_STREAM = 9   # décalage du duo d'appel
TRIO_STREAM = 11     # trio d'appel
COUNT_STREAM = 12    # nombre de pots d'appel
# Motifs non collinéaires (travers, profondeur) autour de l'ancre du rôle.
MOTIFS = {
    2: (((-3.5, -1.0), (3.0, 1.0)),
        ((-2.5, -2.0), (3.5, 2.0))),
    3: (((-4.0, -2.0), (2.0, -3.0), (3.0, 3.0)),
        ((-4.5, 0.0), (0.0, -3.5), (4.0, 2.5)),
        ((-3.0, -3.0), (3.5, -1.5), (0.0, 3.5))),
    4: (((-4.0, -3.0), (2.5, -3.5), (-3.0, 3.0), (4.0, 2.0)),
        ((-5.0, -1.5), (0.0, -4.0), (5.0, -1.0), (1.0, 4.0)),
        ((-4.0, -3.0), (3.0, -2.5), (-2.0, 3.5), (4.5, 3.0))),
}
# Duo d'appel : espacements latéraux essayés et amplitudes de décalage partagées.
SPACING_TRIALS = np.arange(6.0, 12.01, 0.5)
STAGGER_AMPLITUDES = (0.0, 2.0, 4.0)
LANDING_TWO_WEIGHT = 0.40


def pot_cells(base: np.ndarray, small: bool = False) -> np.ndarray:
    """Cases d'un pot (8, ou 5 si ``small``) autour de la base entière."""
    return (SMALL_OFFSETS if small else OFFSETS) + np.asarray(base, dtype=int)


def minimum_gap(cells: tuple[np.ndarray, ...]) -> float:
    """Plus petit écart d'herbe entre deux pots de la grappe."""
    return min(cell_gap(left, right)
               for i, left in enumerate(cells) for right in cells[i + 1:])


def mixed_sizes(seed: int, order: int, count: int) -> tuple[bool, ...]:
    """True = petit pot (5 cases) ; au moins un pot de chaque taille."""
    if count < 2:
        raise ValueError("un mix exige au moins deux pots")
    rng = np.random.default_rng([seed, RNG_LABEL, order, MIX_STREAM,
                                 ROLE_IDS["green_guard"], count])
    large_count = int(rng.integers(1, count))
    large_indices = set(int(i) for i in rng.choice(count, size=large_count,
                                                   replace=False))
    return tuple(index not in large_indices for index in range(count))


def pot_outline(center, tangent) -> np.ndarray:
    """Contour lisse ``(64, 2)`` d'un pot, pour placer la grappe avant le raster."""
    angle = np.linspace(0.0, 2.0 * math.pi, 64, endpoint=False)
    along, across, wobble, waves = (1.45, 1.45, 0.03, 3)
    scale = 1.0 + wobble * np.cos(waves * angle + 0.4) + 0.035 * np.cos(5.0 * angle - 0.7)
    normal = np.array((-tangent[1], tangent[0]))
    return np.asarray(center) + scale[:, None] * (
        np.cos(angle)[:, None] * tangent * along
        + np.sin(angle)[:, None] * normal * across)


def cluster_rng(seed: int, order: int) -> np.random.Generator:
    """Flux du nombre et des motifs des pots de green."""
    return np.random.default_rng([seed, RNG_LABEL, order, CLUSTER_STREAM,
                                  ROLE_IDS["green_guard"]])


def count_probs(width: float) -> tuple[float, float, float]:
    """Probabilités de 2, 3, 4 pots selon la largeur d'approche (blocs)."""
    p2 = float(np.clip((7.0 - width) / 2.0, 0.0, 0.7))
    p4 = float(np.clip((width - 7.0) / 4.0, 0.0, 0.6))
    return p2, 1.0 - p2 - p4, p4


def draw_count(width: float, rng: np.random.Generator) -> int:
    return int(rng.choice((2, 3, 4), p=count_probs(width)))


def candidate_outlines(motif, anchor: np.ndarray, tangent: np.ndarray,
                       rng: np.random.Generator) -> tuple[np.ndarray, ...]:
    """Contours d'une grappe : motif centré, miroir, rotation ±25°, bruit et décalage tirés."""
    local = np.asarray(motif, dtype=float)
    local = local - local.mean(axis=0)
    if rng.integers(2):
        local[:, 0] *= -1.0
    theta = math.radians(float(rng.uniform(-25.0, 25.0)))
    rotation = np.array(((math.cos(theta), -math.sin(theta)),
                         (math.sin(theta), math.cos(theta))))
    local = local @ rotation.T
    local += rng.uniform(-0.6, 0.6, size=local.shape)
    local += np.array((rng.uniform(-1.0, 1.0), rng.uniform(-1.5, 0.2)))
    normal = np.array((-tangent[1], tangent[0]))
    centers = anchor + local[:, 0, None] * normal + local[:, 1, None] * tangent
    return tuple(pot_outline(center, tangent) for center in centers)


def group_at(smooth_centers: np.ndarray, tangent: np.ndarray,
             scale: float, back: float) -> tuple[np.ndarray, ...]:
    """Grappe raster : centres étalés de ``scale`` autour de leur moyenne, reculés de ``back``."""
    mean = smooth_centers.mean(axis=0)
    centers = mean + scale * (smooth_centers - mean) - back * tangent
    bases = np.rint(centers - np.array((0.5, 0.0))).astype(int)
    return tuple(pot_cells(base) for base in bases)


def desired_count(seed: int, order: int) -> int:
    """Nombre de pots d'appel voulu (2 ou 3), flux propre."""
    rng = np.random.default_rng([seed, RNG_LABEL, order, COUNT_STREAM,
                                 ROLE_IDS["landing"]])
    return 2 if rng.random() < LANDING_TWO_WEIGHT else 3


def stagger_offsets(seed: int, order: int, count: int, amplitude: float) -> np.ndarray:
    """Décalages le long du jeu, centrés et seedés."""
    if count not in (2, 3):
        raise ValueError("deux ou trois pots uniquement")
    if amplitude < 0:
        raise ValueError("décalage négatif")
    rng = np.random.default_rng([seed, RNG_LABEL, order, STAGGER_STREAM,
                                 ROLE_IDS["landing"], count])
    sign = 1 if rng.integers(2) else -1
    profile = np.array((-0.5, 0.5) if count == 2 else (-0.5, 1.0, -0.5))
    return sign * amplitude * profile


def landing_group(anchor: dict, count: int, spacing: float,
                  along_offsets: np.ndarray | None = None) -> tuple[np.ndarray, ...]:
    """Pots en ligne sur la normale de l'ancre (``center``, ``normal``, ``tangent``)."""
    if count not in (2, 3):
        raise ValueError("deux ou trois pots uniquement")
    positions = (np.arange(count, dtype=float) - (count - 1) / 2.0) * spacing
    centers = anchor["center"] + positions[:, None] * anchor["normal"]
    if along_offsets is not None:
        offsets = np.asarray(along_offsets, dtype=float)
        if offsets.shape != (count,):
            raise ValueError("un décalage longitudinal par pot attendu")
        centers += offsets[:, None] * anchor["tangent"]
    bases = np.rint(centers - np.array((0.5, -0.5))).astype(int)
    return tuple(pot_cells(base) for base in bases)


def shared_spacing(anchor: dict, seed: int, order: int, count: int) -> float:
    """Plus petit espacement qui garde ``MIN_GRASS`` pour toutes les amplitudes."""
    for spacing in SPACING_TRIALS:
        valid = True
        for amplitude in STAGGER_AMPLITUDES:
            offsets = stagger_offsets(seed, order, count, amplitude)
            cells = landing_group(anchor, count, float(spacing), offsets)
            if any(cell_gap(left, right) < MIN_GRASS
                   for i, left in enumerate(cells) for right in cells[i + 1:]):
                valid = False
                break
        if valid:
            return float(spacing)
    raise BunkerError("écart de trois blocs d'herbe introuvable")


def raster_group(anchor: dict, across: np.ndarray, along: np.ndarray,
                 shift: np.ndarray | None = None) -> tuple[np.ndarray, ...]:
    """Trio : trois centres locaux (travers, long) décalés de ``shift``, puis cases."""
    if across.shape != (3,) or along.shape != (3,):
        raise ValueError("trois positions attendues")
    shift = np.zeros(2) if shift is None else np.asarray(shift, dtype=float)
    centers = (anchor["center"] + (across + shift[0])[:, None] * anchor["normal"]
               + (along + shift[1])[:, None] * anchor["tangent"])
    bases = np.rint(centers - np.array((0.5, -0.5))).astype(int)
    return tuple(pot_cells(base) for base in bases)
