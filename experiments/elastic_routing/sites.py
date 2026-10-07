"""Étape M — sites candidats de greens et de tees tirés du relief.

Un *site* est un point du terrain jugé apte à recevoir un green (planéité +
proéminence modérée) ou un tee (planéité seule). Les sites sont obtenus en
trois temps :

1. grille fine (pas ``GRID_STEP``) décalée d'un bruit seedé, eau exclue ;
2. score de relief normalisé dans [0, 1] — ou score aléatoire seedé si le
   relief est trop plat pour départager les candidats ;
3. amincissement glouton par score décroissant : un candidat n'est retenu que
   s'il est à au moins ``spacing`` blocs de tous les sites déjà retenus
   (~18 entre greens, ~12 entre tees).

Le relief (7 s par seed en 400×400) est mis en cache sur disque, hors git.
"""

from __future__ import annotations

from dataclasses import dataclass
import math
from pathlib import Path

import numpy as np

from golfgen.config import CourseConfig
from golfgen.terrain import TerrainGenerator


CACHE_DIR = Path(__file__).resolve().parent / "output" / ".cache"

WATER_LEVEL = 60.0             # sous ce niveau : eau (~1 % de la carte, seeds 1–3)
GRID_STEP = 3.0                # pas de la grille fine de candidats
GRID_JITTER = 1.2              # amplitude du bruit seedé sur la grille
EDGE_MARGIN = 12.0             # un site reste à distance du bord (cœur dans la carte)
GREEN_SPACING = 18.0
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


def load_terrain(seed: int, width: int = 400, height: int = 400,
                 cache_dir: Path | None = CACHE_DIR) -> np.ndarray:
    """Relief de ``TerrainGenerator`` pour la seed, mis en cache en ``.npy``."""
    path = None
    if cache_dir is not None:
        path = Path(cache_dir) / f"terrain_s{seed}_{width}x{height}.npy"
        if path.exists():
            return np.load(path)
    heightmap = TerrainGenerator(CourseConfig(width=width, height=height, seed=seed)).generate()
    if path is not None:
        path.parent.mkdir(parents=True, exist_ok=True)
        np.save(path, heightmap)
    return heightmap


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
    dry = _box_min(heightmap, 2) >= WATER_LEVEL

    points = _candidate_grid(heightmap, rng)
    ix = np.clip(points[:, 0].astype(int), 0, heightmap.shape[1] - 1)
    iy = np.clip(points[:, 1].astype(int), 0, heightmap.shape[0] - 1)
    keep = dry[iy, ix]
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
