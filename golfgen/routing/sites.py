"""Étape M — sites candidats de greens et de tees tirés du relief.

Un *site* est un point du terrain jugé apte à recevoir un green (planéité +
proéminence modérée) ou un tee (planéité seule). Les sites sont obtenus en
trois temps :

1. grille fine (pas ``GRID_STEP``) décalée d'un bruit seedé, eau exclue
   (``DryMask``, seule définition du « sec » du routeur) ;
2. score de relief normalisé dans [0, 1] — ou score aléatoire seedé si le
   relief est trop plat pour départager les candidats ;
3. amincissement glouton par score décroissant : un candidat n'est retenu que
   s'il est à au moins ``spacing`` blocs de tous les sites déjà retenus
   (12 entre greens — 18 en R1 —, 12 entre tees).

Le relief (7 s par seed en 400×400) est mis en cache sur disque, hors git, par
le cache unique ``golfgen.terrain.load_or_generate``.
"""

from __future__ import annotations

from dataclasses import dataclass
import math

import numpy as np

from golfgen.config import CourseConfig, TerrainConfig
from golfgen.terrain import load_or_generate


WATER_LEVEL = 60.0             # sous ce niveau : eau (~1 % de la carte, seeds 1–3)
GRID_STEP = 3.0                # pas de la grille fine de candidats
GRID_JITTER = 1.2              # amplitude du bruit seedé sur la grille
EDGE_MARGIN = 12.0             # un site reste à distance du bord (cœur dans la carte)
# 18 en R1 ; ramené à 12 en R2 : à 18, le cône d'ancrage du clubhouse
# (liaison 18–45, ~30° d'ouverture) ne contient que 0 à 2 sites de green et
# 3 cas sur 12 (seeds × formats rectangulaires) échouaient sur le trou 9/18.
GREEN_SPACING = 12.0
TEE_SPACING = 12.0
PLANARITY_RADIUS = 4           # fenêtre (2r+1)² de pente moyenne
PROMINENCE_RADIUS = 20         # fenêtre (2r+1)² du relief moyen environnant
PROMINENCE_TARGET = 1.0        # proéminence idéale d'un green (blocs au-dessus)
PROMINENCE_SIGMA = 1.5
GREEN_PLANARITY_WEIGHT = 0.6
FLAT_SLOPE_SPREAD = 0.02       # écart p90-p10 de pente sous lequel le relief est « plat »


@dataclass(frozen=True, slots=True)
class Sites:
    """Sites retenus d'un type, triés par score décroissant."""

    kind: str
    points: np.ndarray         # (n, 2) float64, colonnes x, y
    scores: np.ndarray         # (n,) dans [0, 1]
    random_scores: bool        # True si le relief était trop plat

    def __len__(self) -> int:
        return len(self.points)


def grid_indices(points: np.ndarray, width: int, height: int) -> tuple[np.ndarray, np.ndarray]:
    """Cellules ``(ix, iy)`` du relief sous ``points`` (colonnes x, y) :
    coordonnées tronquées vers zéro puis bornées à la carte."""
    ix = np.clip(points[:, 0].astype(int), 0, width - 1)
    iy = np.clip(points[:, 1].astype(int), 0, height - 1)
    return ix, iy


@dataclass(frozen=True, slots=True)
class DryMask:
    """Cellules « sèches » du relief : le minimum du relief dans une boîte de
    rayon 2 autour de la cellule est ≥ ``WATER_LEVEL``.

    Seule source de vérité du critère sec : les sites de tee et de green
    (``build_sites``) et le décompte des coudes mouillés du runner l'utilisent.
    """

    dry: np.ndarray            # (h, w) bool, indexé [y, x]

    @property
    def width(self) -> int:
        return int(self.dry.shape[1])

    @property
    def height(self) -> int:
        return int(self.dry.shape[0])

    def is_dry(self, points) -> np.ndarray:
        """``(n,)`` bool : chaque point ``(x, y)`` tombe-t-il sur une cellule
        sèche ? Même indexation (tronquée, bornée) que les sites."""
        points = np.asarray(points, dtype=np.float64).reshape(-1, 2)
        ix, iy = grid_indices(points, self.width, self.height)
        return self.dry[iy, ix]

    @classmethod
    def all_dry(cls, width: int, height: int) -> DryMask:
        """Masque entièrement sec (tests)."""
        return cls(dry=np.ones((int(height), int(width)), dtype=bool))


def dry_mask(heightmap: np.ndarray) -> DryMask:
    """``DryMask`` du relief ``heightmap`` (indexé ``[y, x]``)."""
    return DryMask(dry=_box_min(heightmap.astype(np.float64), 2) >= WATER_LEVEL)


def load_terrain(seed: int, width: int = 400, height: int = 400,
                 terrain: TerrainConfig | None = None) -> np.ndarray:
    """Relief de la seed pour la ``TerrainConfig`` donnée (défaut : ``TerrainConfig()``).

    Délègue au cache unique ``golfgen.terrain.load_or_generate``."""
    config = CourseConfig(width=width, height=height, seed=seed,
                          terrain=terrain if terrain is not None else TerrainConfig())
    return load_or_generate(config)


def _box_mean(values: np.ndarray, radius: int) -> np.ndarray:
    """Moyenne glissante (2r+1)² par table de sommes, bords répliqués."""
    padded = np.pad(values.astype(np.float64), radius, mode="edge")
    table = np.pad(padded.cumsum(0).cumsum(1), ((1, 0), (1, 0)))
    size = 2 * radius + 1
    total = (table[size:, size:] - table[:-size, size:]
             - table[size:, :-size] + table[:-size, :-size])
    return total / (size * size)


def _box_min(values: np.ndarray, radius: int) -> np.ndarray:
    padded = np.pad(values, radius, mode="edge")
    h, w = values.shape
    result = np.full(values.shape, np.inf)
    for dy in range(2 * radius + 1):
        for dx in range(2 * radius + 1):
            result = np.minimum(result, padded[dy:dy + h, dx:dx + w])
    return result


def _candidate_grid(heightmap: np.ndarray, rng: np.random.Generator) -> np.ndarray:
    h, w = heightmap.shape
    xs = np.arange(EDGE_MARGIN, w - EDGE_MARGIN + 1e-9, GRID_STEP)
    ys = np.arange(EDGE_MARGIN, h - EDGE_MARGIN + 1e-9, GRID_STEP)
    gx, gy = np.meshgrid(xs, ys)
    points = np.column_stack([gx.ravel(), gy.ravel()])
    points += rng.uniform(-GRID_JITTER, GRID_JITTER, size=points.shape)
    points[:, 0] = np.clip(points[:, 0], EDGE_MARGIN, w - EDGE_MARGIN)
    points[:, 1] = np.clip(points[:, 1], EDGE_MARGIN, h - EDGE_MARGIN)
    return points


def _thin(points: np.ndarray, scores: np.ndarray, spacing: float) -> np.ndarray:
    """Indices retenus par amincissement glouton (score décroissant, stable)."""
    order = np.argsort(-scores, kind="stable")
    buckets: dict[tuple[int, int], list[int]] = {}
    kept: list[int] = []
    limit = spacing * spacing
    for index in order:
        x, y = points[index]
        cx, cy = int(x // spacing), int(y // spacing)
        clear = True
        for bx in (cx - 1, cx, cx + 1):
            for by in (cy - 1, cy, cy + 1):
                for other in buckets.get((bx, by), ()):
                    ox, oy = points[other]
                    if (ox - x) ** 2 + (oy - y) ** 2 < limit:
                        clear = False
                        break
                if not clear:
                    break
            if not clear:
                break
        if clear:
            kept.append(int(index))
            buckets.setdefault((cx, cy), []).append(int(index))
    return np.asarray(kept, dtype=np.int64)


def _normalize(values: np.ndarray) -> np.ndarray:
    low, high = float(values.min()), float(values.max())
    if high - low < 1e-12:
        return np.zeros_like(values)
    return (values - low) / (high - low)


def build_sites(heightmap: np.ndarray, seed: int, kind: str) -> Sites:
    """Sites ``kind`` (``"green"`` ou ``"tee"``) pour ce relief et cette seed."""
    if kind not in ("green", "tee"):
        raise ValueError("kind doit valoir 'green' ou 'tee'")
    rng = np.random.default_rng([seed, 0 if kind == "green" else 1])
    heightmap = heightmap.astype(np.float64)
    gy, gx = np.gradient(heightmap)
    slope = _box_mean(np.hypot(gx, gy), PLANARITY_RADIUS)
    prominence = heightmap - _box_mean(heightmap, PROMINENCE_RADIUS)
    mask = dry_mask(heightmap)

    points = _candidate_grid(heightmap, rng)
    ix, iy = grid_indices(points, mask.width, mask.height)
    keep = mask.dry[iy, ix]
    points, ix, iy = points[keep], ix[keep], iy[keep]

    local_slope = slope[iy, ix]
    spread = float(np.percentile(local_slope, 90) - np.percentile(local_slope, 10))
    random_scores = spread < FLAT_SLOPE_SPREAD
    if random_scores:
        scores = rng.uniform(0.0, 1.0, size=len(points))
    else:
        planarity = 1.0 - _normalize(local_slope)
        if kind == "tee":
            scores = planarity
        else:
            bump = np.exp(-0.5 * ((prominence[iy, ix] - PROMINENCE_TARGET) / PROMINENCE_SIGMA) ** 2)
            scores = (GREEN_PLANARITY_WEIGHT * planarity
                      + (1.0 - GREEN_PLANARITY_WEIGHT) * bump)
    # bruit seedé minuscule : départage les égalités sans changer le classement
    scores = scores + rng.uniform(0.0, 1e-6, size=len(scores))
    kept = _thin(points, scores, GREEN_SPACING if kind == "green" else TEE_SPACING)
    return Sites(kind=kind, points=points[kept], scores=np.clip(scores[kept], 0.0, 1.0),
                 random_scores=random_scores)


def min_pairwise_distance(points: np.ndarray) -> float:
    """Utilitaire de test : plus petite distance entre deux sites."""
    if len(points) < 2:
        return math.inf
    diff = points[:, None, :] - points[None, :, :]
    dist = np.hypot(diff[..., 0], diff[..., 1])
    np.fill_diagonal(dist, np.inf)
    return float(dist.min())
