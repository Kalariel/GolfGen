"""Paving — decoupe la grille en 18 cellules organiques par region growing isotrope."""

from __future__ import annotations

import heapq

import numpy as np

from .config import CourseConfig

# 8 directions (cardinales + diagonales) avec couts euclidiens
DIRS_8 = [
    (-1, 0, 1.0), (1, 0, 1.0), (0, -1, 1.0), (0, 1, 1.0),
    (-1, -1, 1.414), (-1, 1, 1.414), (1, -1, 1.414), (1, 1, 1.414),
]


class PavingGenerator:
    """Decoupe le terrain en cellules organiques via Dijkstra isotrope.

    Phase 1 : placement des seeds sur grille lache + jitter.
    Phase 2 : region growing (Dijkstra 8-dir) avec bruit + pente.
    Phase 3 : comblement des tiles restantes.
    Phase 4 : nettoyage des tiles isolees (filtre majoritaire).
    """

    def __init__(self, config: CourseConfig, heightmap: np.ndarray):
        self.cfg = config
        self.pav = config.paving
        self.heightmap = heightmap
        self.rng = np.random.default_rng(config.seed)

        self.tile_size = self.pav.tile_size
        self.th = config.height // self.tile_size  # 70
        self.tw = config.width // self.tile_size   # 70

        self.pars = config.routing.par_distribution[:config.num_holes]
        self.n_holes = len(self.pars)
        self.weights = self._compute_weights()

    # ------------------------------------------------------------------
    # Public
    # ------------------------------------------------------------------

    def pave(self) -> tuple[np.ndarray, list[tuple[int, int]], list[int]]:
        """Retourne (owner[th, tw], seeds[(tx,ty),...], cell_sizes)."""
        tile_elev = self._build_tile_elevation()
        land_mask = tile_elev >= self.pav.water_level
        land_count = int(land_mask.sum())

        seeds = self._place_seeds(land_mask)
        owner = self._region_growing(seeds, tile_elev, land_mask, land_count)
        owner = self._fill_remaining(owner, land_mask)
        owner = self._cleanup(owner)

        cell_sizes = [int((owner == i).sum()) for i in range(self.n_holes)]

        filled = int((owner >= 0).sum())
        print(f"     Paving: {self.n_holes} cellules, "
              f"{filled}/{land_count} tiles terre "
              f"({filled / max(land_count, 1) * 100:.0f}%)")

        return owner, seeds, cell_sizes

    # ------------------------------------------------------------------
    # Phase 1 : Placement des seeds
    # ------------------------------------------------------------------

    def _place_seeds(self, land_mask: np.ndarray) -> list[tuple[int, int]]:
        """Place 18 seeds en grille lache 6x3 avec jitter, ordre serpentin."""
        cols = 6
        rows = 3
        pad = 4
        inner_tw = self.tw - 2 * pad
        inner_th = self.th - 2 * pad
        dx = inner_tw / cols
        dy = inner_th / rows
        cell_margin = 2

        grid_positions: list[tuple[float, float, int, int]] = []
        for c in range(cols):
            col_positions = []
            for r in range(rows):
                tx = pad + dx * (c + 0.5)
                ty = pad + dy * (r + 0.5)
                col_positions.append((tx, ty, c, r))
            if c % 2 == 1:
                col_positions.reverse()
            grid_positions.extend(col_positions)

        seeds: list[tuple[int, int]] = []
        for i in range(self.n_holes):
            base_tx, base_ty, col, row = grid_positions[i]
            x_min = int(pad + dx * col) + cell_margin
            x_max = int(pad + dx * (col + 1)) - 1 - cell_margin
            y_min = int(pad + dy * row) + cell_margin
            y_max = int(pad + dy * (row + 1)) - 1 - cell_margin
            jx = self.rng.integers(-4, 5)
            jy = self.rng.integers(-4, 5)
            tx = int(np.clip(base_tx + jx, x_min, x_max))
            ty = int(np.clip(base_ty + jy, y_min, y_max))

            if not land_mask[ty, tx]:
                tx, ty = self._find_nearest_land(tx, ty, land_mask)

            seeds.append((tx, ty))

        return seeds

    def _find_nearest_land(self, tx: int, ty: int,
                           land_mask: np.ndarray) -> tuple[int, int]:
        """BFS pour trouver la tile terre la plus proche."""
        visited = set()
        queue = [(tx, ty)]
        visited.add((tx, ty))
        while queue:
            cx, cy = queue.pop(0)
            if 0 <= cy < self.th and 0 <= cx < self.tw and land_mask[cy, cx]:
                return cx, cy
            for ddx, ddy, _ in DIRS_8[:4]:
                nx, ny = cx + ddx, cy + ddy
                if (nx, ny) not in visited and 0 <= nx < self.tw and 0 <= ny < self.th:
                    visited.add((nx, ny))
                    queue.append((nx, ny))
        return tx, ty

    # ------------------------------------------------------------------
    # Phase 2 : Region growing (Dijkstra isotrope)
    # ------------------------------------------------------------------

    def _region_growing(self, seeds: list[tuple[int, int]],
                        tile_elev: np.ndarray, land_mask: np.ndarray,
                        land_count: int) -> np.ndarray:
        """Croissance isotrope avec bruit + pente pour des frontieres organiques."""
        owner = np.full((self.th, self.tw), -1, dtype=np.int16)
        cost = np.full((self.th, self.tw), np.inf, dtype=np.float64)

        # Taille cible par trou
        total_weight = sum(self.weights)
        target_sizes = [
            int(land_count * self.pav.target_coverage * w / total_weight)
            for w in self.weights
        ]
        current_sizes = [0] * self.n_holes

        slope = self._compute_tile_slope(tile_elev)

        # Bruit pre-genere par tile (evite les appels rng dans la boucle)
        noise_field = self.rng.uniform(0, self.pav.growth_noise,
                                       (self.th, self.tw))

        heap: list[tuple[float, int, int, int]] = []

        for i, (sx, sy) in enumerate(seeds):
            owner[sy, sx] = i
            cost[sy, sx] = 0.0
            current_sizes[i] = 1
            for ddx, ddy, base_cost in DIRS_8:
                nx, ny = sx + ddx, sy + ddy
                if 0 <= nx < self.tw and 0 <= ny < self.th:
                    c = base_cost + noise_field[ny, nx] + slope[ny, nx] * self.pav.growth_slope_penalty
                    heapq.heappush(heap, (c, nx, ny, i))

        while heap:
            c, tx, ty, hole_id = heapq.heappop(heap)

            if owner[ty, tx] >= 0:
                continue
            if not land_mask[ty, tx]:
                continue
            if current_sizes[hole_id] >= target_sizes[hole_id]:
                continue

            owner[ty, tx] = hole_id
            cost[ty, tx] = c
            current_sizes[hole_id] += 1

            for ddx, ddy, base_cost in DIRS_8:
                nx, ny = tx + ddx, ty + ddy
                if 0 <= nx < self.tw and 0 <= ny < self.th and owner[ny, nx] < 0:
                    nc = c + base_cost + noise_field[ny, nx] + slope[ny, nx] * self.pav.growth_slope_penalty
                    if nc < cost[ny, nx]:
                        cost[ny, nx] = nc
                        heapq.heappush(heap, (nc, nx, ny, hole_id))

        return owner

    # ------------------------------------------------------------------
    # Phase 3 : Comblement
    # ------------------------------------------------------------------

    def _fill_remaining(self, owner: np.ndarray,
                        land_mask: np.ndarray) -> np.ndarray:
        """Assigne les tiles restantes au voisin le plus sous-rempli."""
        # Taille cible pour le ratio de remplissage
        land_count = int(land_mask.sum())
        total_weight = sum(self.weights)
        target_sizes = [
            max(1, int(land_count * self.pav.target_coverage * w / total_weight))
            for w in self.weights
        ]

        changed = True
        while changed:
            changed = False
            free = (owner < 0) & land_mask
            ys, xs = np.where(free)

            for y, x in zip(ys, xs):
                neighbors: dict[int, int] = {}
                for ddx, ddy, _ in DIRS_8:
                    nx, ny = x + ddx, y + ddy
                    if 0 <= nx < self.tw and 0 <= ny < self.th:
                        n = int(owner[ny, nx])
                        if n >= 0:
                            neighbors[n] = neighbors.get(n, 0) + 1

                if neighbors:
                    sizes = {n: int((owner == n).sum()) for n in neighbors}
                    best = min(neighbors,
                               key=lambda n: sizes[n] / target_sizes[n])
                    owner[y, x] = best
                    changed = True

        return owner

    # ------------------------------------------------------------------
    # Phase 4 : Nettoyage (filtre majoritaire)
    # ------------------------------------------------------------------

    def _cleanup(self, owner: np.ndarray) -> np.ndarray:
        """Absorbe les tiles isolees (5+ voisins sur 8 d'une meme autre zone)."""
        result = owner.copy()
        min_size = 50

        for _ in range(3):
            sizes = {i: int((result == i).sum()) for i in range(self.n_holes)}
            changed = False
            for ty in range(self.th):
                for tx in range(self.tw):
                    cell = result[ty, tx]
                    if cell < 0:
                        continue

                    counts: dict[int, int] = {}
                    for dy in (-1, 0, 1):
                        for dx in (-1, 0, 1):
                            if dy == 0 and dx == 0:
                                continue
                            ny, nx = ty + dy, tx + dx
                            if 0 <= ny < self.th and 0 <= nx < self.tw:
                                n = result[ny, nx]
                                if n >= 0 and n != cell:
                                    counts[n] = counts.get(n, 0) + 1

                    if not counts:
                        continue

                    best_zone = max(counts, key=counts.get)
                    if counts[best_zone] >= 5 and sizes.get(cell, 0) > min_size:
                        result[ty, tx] = best_zone
                        sizes[cell] -= 1
                        sizes[best_zone] = sizes.get(best_zone, 0) + 1
                        changed = True

            if not changed:
                break

        return result

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _compute_weights(self) -> list[float]:
        weight_map = {
            3: self.pav.par3_weight,
            4: self.pav.par4_weight,
            5: self.pav.par5_weight,
        }
        return [weight_map.get(p, 1.5) for p in self.pars]

    def _build_tile_elevation(self) -> np.ndarray:
        ts = self.tile_size
        cropped = self.heightmap[:self.th * ts, :self.tw * ts]
        reshaped = cropped.reshape(self.th, ts, self.tw, ts)
        return reshaped.mean(axis=(1, 3))

    def _compute_tile_slope(self, tile_elev: np.ndarray) -> np.ndarray:
        gy, gx = np.gradient(tile_elev)
        return np.sqrt(gx ** 2 + gy ** 2)
