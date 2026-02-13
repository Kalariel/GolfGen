"""Routing procédural — placement des 18 trous par paving Voronoi.

Approche : découpage de la grille en cellules Voronoi pondérées par le par.
1. Placer 18 seeds (positions initiales) en séquence autour du clubhouse
2. Faire grandir les régions par flood-fill Dijkstra pondéré (priority queue)
3. Dans chaque cellule, placer tee et green aux extrémités
4. Construire les waypoints (ligne droite par 3, doglegs par 4/5)
5. Format JSON identique — le viewer ne change pas
"""

from __future__ import annotations

import heapq
import math
import random

import numpy as np

from .config import CourseConfig
from .utils import (
    distance, gradient_at, polyline_length, direction_label, snap_to_tile,
    slope_at,
)


class LayoutRouter:
    """Place les 18 trous sur le terrain par paving Voronoi."""

    def __init__(self, config: CourseConfig, heightmap: np.ndarray):
        self.config = config
        self.rc = config.routing
        self.heightmap = heightmap
        self.rng = random.Random(config.seed)
        self.h, self.w = heightmap.shape
        self.tile_size = self.rc.tile_size
        self.water_level = self.rc.water_level
        self.water_mask = heightmap < self.water_level

        # Grille de tiles
        self.tw = self.w // self.tile_size  # 70
        self.th = self.h // self.tile_size  # 70

        # Masque eau au niveau tile (une tile est eau si >50% de ses blocs sont eau)
        self.tile_water = np.zeros((self.th, self.tw), dtype=bool)
        for ty in range(self.th):
            for tx in range(self.tw):
                y0 = ty * self.tile_size
                x0 = tx * self.tile_size
                y1 = min(y0 + self.tile_size, self.h)
                x1 = min(x0 + self.tile_size, self.w)
                self.tile_water[ty, tx] = self.water_mask[y0:y1, x0:x1].mean() > 0.5

        # Pente moyenne par tile
        self.tile_slope = np.zeros((self.th, self.tw), dtype=np.float32)
        for ty in range(self.th):
            for tx in range(self.tw):
                cx = tx * self.tile_size + self.tile_size // 2
                cy = ty * self.tile_size + self.tile_size // 2
                cx = max(2, min(self.w - 3, cx))
                cy = max(2, min(self.h - 3, cy))
                self.tile_slope[ty, tx] = slope_at(heightmap, cx, cy)

    def route(self) -> tuple[dict, list[dict]]:
        """Route les 18 trous par paving Voronoi."""
        ch_x = self.config.clubhouse_x
        ch_y = self.config.clubhouse_y
        ch = {
            "x": ch_x, "y": ch_y,
            "width": self.config.features.clubhouse_width,
            "height": self.config.features.clubhouse_height,
        }

        pars = self.rc.par_distribution[:self.config.num_holes]

        # Phase 1 : Placer les seeds
        seeds = self._place_seeds(pars)

        # Phase 2 : Faire grandir les régions
        owner = self._grow_regions(seeds, pars)

        # Phase 3 : Placer tee et green dans chaque cellule
        placements = self._place_tee_green(owner, seeds, pars)

        # Phase 4 : Construire les trous (waypoints + JSON)
        holes = self._build_holes(placements, owner, pars)

        # Stats couverture
        land_tiles = int(np.sum(~self.tile_water))
        assigned = int(np.sum(owner >= 0))
        pct = assigned / land_tiles * 100 if land_tiles > 0 else 0
        print(f"  Couverture : {assigned}/{land_tiles} tiles terre ({pct:.1f}%)")

        return ch, holes

    # ===== Phase 1 : Placement des seeds =====

    def _place_seeds(self, pars: list[int]) -> list[tuple[int, int]]:
        """Place 18 seeds le long de deux boucles (ouest 1-9, est 10-18).

        Les seeds sont placées aux milieux des segments du parcours sur des
        chemins polygonaux prédéfinis. Ceci garantit que les cellules Voronoi
        sont allongées le long du parcours et que les trous consécutifs sont
        adjacents.
        """
        ch_x = self.config.clubhouse_x
        ch_y = self.config.clubhouse_y
        margin = 20

        # Boucle Ouest (trous 1-9)
        west_loop = [
            (ch_x - 10, ch_y + 5),
            (ch_x - 35, ch_y + 25),
            (ch_x - 85, ch_y + 15),
            (ch_x - 125, ch_y - 30),
            (ch_x - 130, ch_y - 85),
            (ch_x - 115, ch_y - 150),
            (ch_x - 75, ch_y - 200),
            (ch_x - 25, ch_y - 230),
            (ch_x + 15, ch_y - 210),
            (ch_x + 30, ch_y - 145),
            (ch_x + 10, ch_y - 75),
            (ch_x - 5, ch_y + 3),
        ]
        west_loop = [(max(margin, min(self.w - margin, x)),
                       max(margin, min(self.h - margin, y)))
                      for x, y in west_loop]

        # Boucle Est (trous 10-18)
        east_loop = [
            (ch_x + 30, ch_y + 3),
            (ch_x + 55, ch_y + 25),
            (ch_x + 100, ch_y + 15),
            (ch_x + 135, ch_y - 20),
            (ch_x + 140, ch_y - 75),
            (ch_x + 125, ch_y - 140),
            (ch_x + 90, ch_y - 195),
            (ch_x + 35, ch_y - 220),
            (ch_x - 5, ch_y - 185),
            (ch_x - 10, ch_y - 115),
            (ch_x + 5, ch_y - 45),
            (ch_x + 20, ch_y + 5),
        ]
        east_loop = [(max(margin, min(self.w - margin, x)),
                       max(margin, min(self.h - margin, y)))
                      for x, y in east_loop]

        west_seeds = self._seeds_along_loop(west_loop, pars[:9])
        east_seeds = self._seeds_along_loop(east_loop, pars[9:])

        return west_seeds + east_seeds

    def _seeds_along_loop(self, loop: list[tuple[float, float]],
                          pars: list[int]) -> list[tuple[int, int]]:
        """Place les seeds aux milieux des segments le long d'une boucle.

        Marche le long du chemin polygonal. Chaque trou occupe un segment
        proportionnel à son par. La seed est au milieu de ce segment.
        """
        n = len(pars)
        weights = [self._par_weight(p) for p in pars]
        total_weight = sum(weights)

        path_len = polyline_length(loop)

        # Position cumulée de chaque frontière trou (en distance le long du chemin)
        boundaries = [0.0]
        for w in weights:
            boundaries.append(boundaries[-1] + path_len * w / total_weight)

        # Milieu de chaque segment = position de la seed
        seeds = []
        for i in range(n):
            mid_dist = (boundaries[i] + boundaries[i + 1]) / 2.0
            px, py = self._point_at_distance(loop, mid_dist)
            # Convertir en coordonnées tile
            tx = max(0, min(self.tw - 1, int(px / self.tile_size)))
            ty = max(0, min(self.th - 1, int(py / self.tile_size)))
            # Éviter l'eau : chercher la tile terre la plus proche
            if self.tile_water[ty, tx]:
                tx, ty = self._nearest_land_tile(tx, ty)
            seeds.append((tx, ty))

        return seeds

    def _point_at_distance(self, path: list[tuple[float, float]],
                           target_dist: float) -> tuple[float, float]:
        """Retourne le point sur une polyligne à une distance donnée du début."""
        remaining = target_dist
        for i in range(len(path) - 1):
            seg_len = distance(path[i], path[i + 1])
            if seg_len < 1e-6:
                continue
            if remaining <= seg_len:
                t = remaining / seg_len
                return (path[i][0] + (path[i + 1][0] - path[i][0]) * t,
                        path[i][1] + (path[i + 1][1] - path[i][1]) * t)
            remaining -= seg_len
        return path[-1]

    def _nearest_land_tile(self, tx: int, ty: int) -> tuple[int, int]:
        """Trouve la tile terre la plus proche."""
        for r in range(1, max(self.tw, self.th)):
            for dy in range(-r, r + 1):
                for dx in range(-r, r + 1):
                    if abs(dx) != r and abs(dy) != r:
                        continue
                    nx, ny = tx + dx, ty + dy
                    if self._tile_valid(nx, ny) and not self.tile_water[ny, nx]:
                        return (nx, ny)
        return (tx, ty)

    def _tile_valid(self, tx: int, ty: int) -> bool:
        """Vérifie qu'une coordonnée tile est dans les limites."""
        return 0 <= tx < self.tw and 0 <= ty < self.th

    # ===== Phase 2 : Region growing (Dijkstra) =====

    def _grow_regions(self, seeds: list[tuple[int, int]],
                      pars: list[int]) -> np.ndarray:
        """Fait grandir les régions par Dijkstra pondéré."""
        owner = np.full((self.th, self.tw), -1, dtype=np.int16)

        # Marquer l'eau
        owner[self.tile_water] = -2

        # Marquer le clubhouse
        ch_tx = self.config.clubhouse_x // self.tile_size
        ch_ty = self.config.clubhouse_y // self.tile_size
        ch_hw = self.config.features.clubhouse_width // self.tile_size // 2 + 1
        ch_hh = self.config.features.clubhouse_height // self.tile_size // 2 + 1
        for dy in range(-ch_hh, ch_hh + 1):
            for dx in range(-ch_hw, ch_hw + 1):
                tx, ty = ch_tx + dx, ch_ty + dy
                if self._tile_valid(tx, ty):
                    owner[ty, tx] = -3

        # Surfaces cibles par trou
        land_tiles = int(np.sum(owner == -1))
        target_total = int(land_tiles * self.rc.target_coverage)

        weights = [self._par_weight(p) for p in pars]
        total_weight = sum(weights)
        targets = [int(target_total * w / total_weight) for w in weights]

        # Compteurs
        counts = [0] * len(pars)

        # Assigner les seeds
        for i, (tx, ty) in enumerate(seeds):
            if self._tile_valid(tx, ty) and owner[ty, tx] == -1:
                owner[ty, tx] = i
                counts[i] = 1

        # Priority queue : (cost, tx, ty, hole_id)
        pq: list[tuple[float, int, int, int]] = []

        slope_penalty = self.rc.growth_slope_penalty
        noise_factor = self.rc.growth_noise

        # Initialiser la queue avec les voisins des seeds
        for i, (sx, sy) in enumerate(seeds):
            for dx, dy in [(-1, 0), (1, 0), (0, -1), (0, 1)]:
                nx, ny = sx + dx, sy + dy
                if self._tile_valid(nx, ny) and owner[ny, nx] == -1:
                    dist = 1.0
                    slope_cost = self.tile_slope[ny, nx] * slope_penalty
                    noise = self.rng.random() * noise_factor
                    cost = dist + slope_cost + noise
                    heapq.heappush(pq, (cost, nx, ny, i))

        # Dijkstra
        while pq:
            cost, tx, ty, hole_id = heapq.heappop(pq)

            if owner[ty, tx] != -1:
                continue
            if counts[hole_id] >= targets[hole_id]:
                continue

            owner[ty, tx] = hole_id
            counts[hole_id] += 1

            # Ajouter les voisins
            for dx, dy in [(-1, 0), (1, 0), (0, -1), (0, 1)]:
                nx, ny = tx + dx, ty + dy
                if self._tile_valid(nx, ny) and owner[ny, nx] == -1:
                    dist = cost + 1.0
                    slope_cost = self.tile_slope[ny, nx] * slope_penalty
                    noise = self.rng.random() * noise_factor
                    new_cost = dist + slope_cost + noise
                    heapq.heappush(pq, (new_cost, nx, ny, hole_id))

        # Passe de comblement : tiles restantes → trou voisin le plus "affamé"
        self._fill_remaining(owner, counts, targets)

        return owner

    def _fill_remaining(self, owner: np.ndarray, counts: list[int],
                        targets: list[int]) -> None:
        """Assigne les tiles libres restantes au trou voisin le plus affamé."""
        changed = True
        while changed:
            changed = False
            for ty in range(self.th):
                for tx in range(self.tw):
                    if owner[ty, tx] != -1:
                        continue

                    # Trouver les trous voisins
                    neighbors: dict[int, float] = {}
                    for dx, dy in [(-1, 0), (1, 0), (0, -1), (0, 1)]:
                        nx, ny = tx + dx, ty + dy
                        if self._tile_valid(nx, ny) and owner[ny, nx] >= 0:
                            hid = int(owner[ny, nx])
                            # Score : plus affamé = meilleur
                            hunger = targets[hid] - counts[hid]
                            if hid not in neighbors or hunger > neighbors[hid]:
                                neighbors[hid] = hunger

                    if neighbors:
                        best_hid = max(neighbors, key=neighbors.get)
                        owner[ty, tx] = best_hid
                        counts[best_hid] += 1
                        changed = True

    # ===== Phase 3 : Placement tee/green =====

    def _place_tee_green(self, owner: np.ndarray, seeds: list[tuple[int, int]],
                         pars: list[int]
                         ) -> list[dict]:
        """Place tee et green dans chaque cellule Voronoi."""
        ch_x = self.config.clubhouse_x
        ch_y = self.config.clubhouse_y
        n = len(pars)

        placements = []

        for i in range(n):
            hole_num = i + 1
            par = pars[i]

            # Récupérer les tiles de cette cellule
            cell_tiles = list(zip(*np.where(owner == i)))  # [(ty, tx), ...]
            if not cell_tiles:
                # Fallback : utiliser le seed
                sx, sy = seeds[i]
                cx = float(sx * self.tile_size + self.tile_size // 2)
                cy = float(sy * self.tile_size + self.tile_size // 2)
                placements.append({"tee": (cx, cy), "green": (cx + 20, cy)})
                continue

            # Déterminer le point d'origine (green précédent ou clubhouse)
            if hole_num == 1 or hole_num == 10:
                origin = (ch_x, ch_y)
            elif i > 0:
                origin = placements[i - 1]["green"]
            else:
                origin = (ch_x, ch_y)

            # Tee : tile la plus proche de l'origine
            tee_tile = min(cell_tiles, key=lambda t: (
                (t[1] * self.tile_size + self.tile_size // 2 - origin[0]) ** 2 +
                (t[0] * self.tile_size + self.tile_size // 2 - origin[1]) ** 2
            ))
            tee_pos = (float(tee_tile[1] * self.tile_size + self.tile_size // 2),
                       float(tee_tile[0] * self.tile_size + self.tile_size // 2))

            # Green : dans la direction du trou suivant, à bonne distance du tee
            lo, hi = self._par_range(par)
            if par == 3:
                target_straight = (lo + hi) / 2  # ~60
            elif par == 4:
                target_straight = lo * 0.8  # ~88 (doglegs ajoutent ~25%)
            else:
                target_straight = lo * 0.75  # ~128 (doglegs ajoutent ~35%)

            # Direction cible : vers la seed suivante ou le clubhouse
            if hole_num == 9 or hole_num == 18:
                next_target = (float(ch_x), float(ch_y))
            elif i + 1 < n:
                ns = seeds[i + 1]
                next_target = (float(ns[0] * self.tile_size + self.tile_size // 2),
                               float(ns[1] * self.tile_size + self.tile_size // 2))
            else:
                next_target = (float(ch_x), float(ch_y))

            # Vecteur unitaire tee → next_target
            dx_next = next_target[0] - tee_pos[0]
            dy_next = next_target[1] - tee_pos[1]
            d_tn = math.sqrt(dx_next * dx_next + dy_next * dy_next)
            if d_tn > 0:
                ux, uy = dx_next / d_tn, dy_next / d_tn
            else:
                ux, uy = 1.0, 0.0

            best_green = None
            best_score = -1e9

            for ty, tx in cell_tiles:
                gx = float(tx * self.tile_size + self.tile_size // 2)
                gy = float(ty * self.tile_size + self.tile_size // 2)
                d = distance(tee_pos, (gx, gy))

                if d < self.tile_size * 2:
                    continue

                # Score gaussien : meilleur quand d proche de target_straight
                deviation = abs(d - target_straight) / max(target_straight, 1)
                dist_score = 100 * math.exp(-2 * deviation * deviation)
                if d < target_straight:
                    dist_score += d * 0.1

                # Bonus directionnel : projeter tee→green sur tee→next
                vgx = gx - tee_pos[0]
                vgy = gy - tee_pos[1]
                proj = vgx * ux + vgy * uy  # projection (positive = bonne dir)
                dir_score = proj * 0.5  # bonus proportionnel

                score = dist_score + dir_score - self.tile_slope[ty, tx] * 5
                if score > best_score:
                    best_score = score
                    best_green = (gx, gy)

            if best_green is None:
                # Fallback : tile la plus éloignée du tee
                far_tile = max(cell_tiles, key=lambda t: (
                    (t[1] * self.tile_size + self.tile_size // 2 - tee_pos[0]) ** 2 +
                    (t[0] * self.tile_size + self.tile_size // 2 - tee_pos[1]) ** 2
                ))
                best_green = (float(far_tile[1] * self.tile_size + self.tile_size // 2),
                              float(far_tile[0] * self.tile_size + self.tile_size // 2))

            # Validation eau
            tee_pos = self._ensure_on_land(tee_pos)
            best_green = self._ensure_on_land(best_green)

            placements.append({"tee": tee_pos, "green": best_green})

        # Post-traitement : corriger les transitions trop longues
        self._fix_continuity(placements, owner, pars, seeds)

        return placements

    def _fix_continuity(self, placements: list[dict], owner: np.ndarray,
                        pars: list[int], seeds: list[tuple[int, int]]) -> None:
        """Corrige les transitions green→tee trop longues (>80 blocs).

        Pour chaque paire problématique, ajuste le tee du trou N+1
        (le rapproche du green du trou N) puis re-place le green de N+1
        si la distance tee→green est devenue trop courte.
        """
        max_walk = 80
        n = len(pars)
        ch_x = float(self.config.clubhouse_x)
        ch_y = float(self.config.clubhouse_y)

        for i in range(n - 1):
            # Skip transitions inter-boucles (9→10)
            if i + 1 == 9:
                continue

            green_i = placements[i]["green"]
            tee_next = placements[i + 1]["tee"]
            d = distance(green_i, tee_next)

            if d <= max_walk:
                continue

            # Trouver une meilleure position pour le tee de i+1 :
            # tile de la cellule i+1 la plus proche du green i
            cell_tiles = list(zip(*np.where(owner == i + 1)))
            if not cell_tiles:
                continue

            new_tee_tile = min(cell_tiles, key=lambda t: (
                (t[1] * self.tile_size + self.tile_size // 2 - green_i[0]) ** 2 +
                (t[0] * self.tile_size + self.tile_size // 2 - green_i[1]) ** 2
            ))
            new_tee = (float(new_tee_tile[1] * self.tile_size + self.tile_size // 2),
                       float(new_tee_tile[0] * self.tile_size + self.tile_size // 2))
            new_tee = self._ensure_on_land(new_tee)
            placements[i + 1]["tee"] = new_tee

            # Vérifier que le green de i+1 est encore assez loin du nouveau tee
            green_next = placements[i + 1]["green"]
            d_tg = distance(new_tee, green_next)
            if d_tg < self.tile_size * 3:
                # Re-placer le green à l'opposé du nouveau tee
                far_tile = max(cell_tiles, key=lambda t: (
                    (t[1] * self.tile_size + self.tile_size // 2 - new_tee[0]) ** 2 +
                    (t[0] * self.tile_size + self.tile_size // 2 - new_tee[1]) ** 2
                ))
                new_green = (float(far_tile[1] * self.tile_size + self.tile_size // 2),
                             float(far_tile[0] * self.tile_size + self.tile_size // 2))
                placements[i + 1]["green"] = self._ensure_on_land(new_green)

    # ===== Phase 4 : Construction des trous =====

    def _build_holes(self, placements: list[dict], owner: np.ndarray,
                     pars: list[int]) -> list[dict]:
        """Construit les données JSON pour chaque trou."""
        holes = []

        for i, par in enumerate(pars):
            hole_id = i + 1
            tee_pos = placements[i]["tee"]
            green_pos = placements[i]["green"]

            fw_width = self._fairway_width(par)
            green_r = self.rng.randint(self.rc.green_radius_min,
                                       self.rc.green_radius_max)

            is_pivot = (par == 3)
            waypoints = self._build_waypoints(tee_pos, green_pos, par, is_pivot,
                                              owner, i)

            actual_blocks = round(polyline_length(waypoints))

            tee_elev = self._elevation_at(tee_pos)
            green_elev = self._elevation_at(green_pos)

            holes.append(self._format_hole(
                hole_id, par, actual_blocks, fw_width, green_r,
                waypoints, tee_elev, green_elev,
            ))

        return holes

    # --- Construction des waypoints ---

    def _build_waypoints(self, tee: tuple[float, float],
                         green: tuple[float, float],
                         par: int, is_pivot: bool,
                         owner: np.ndarray, hole_idx: int
                         ) -> list[tuple[float, float]]:
        """Par 3 : ligne droite. Par 4/5 : doglegs adaptés à la distance cible."""
        straight_dist = distance(tee, green)

        if is_pivot or par == 3:
            return [tee, green]

        lo, _ = self._par_range(par)
        target = lo  # viser le minimum du range

        if par == 4:
            num_bends = 1 if straight_dist >= lo * 0.8 else 2
        else:
            num_bends = 2 if straight_dist >= lo * 0.6 else 3

        return self._build_dogleg(tee, green, num_bends, target,
                                  owner=owner, hole_idx=hole_idx)

    def _build_dogleg(self, tee: tuple, green: tuple,
                      num_bends: int, target_dist: float,
                      owner: np.ndarray | None = None,
                      hole_idx: int = -1) -> list[tuple[float, float]]:
        """Construit un dogleg avec N virages, ajusté pour atteindre la distance cible."""
        clamp_margin = 10

        dx = green[0] - tee[0]
        dy = green[1] - tee[1]
        length = math.sqrt(dx * dx + dy * dy)
        if length < 1:
            return [tee, green]

        perp_x = -dy / length
        perp_y = dx / length

        # Positions t fixes pour chaque bend (avec jitter)
        t_values = []
        for k in range(num_bends):
            t = (k + 1) / (num_bends + 1) + self.rng.uniform(-0.08, 0.08)
            t_values.append(max(0.15, min(0.85, t)))

        # Terrain offsets aux positions des bends
        terrain_offsets = []
        for t in t_values:
            px = tee[0] + dx * t
            py = tee[1] + dy * t
            terrain_offsets.append(
                self._terrain_offset((px, py), (perp_x, perp_y)) * 6
            )

        # Signe alterné pour chaque bend
        signs = [1 if k % 2 == 0 else -1 for k in range(num_bends)]

        # Recherche binaire de l'offset optimal
        deficit = target_dist - length
        if deficit > 0:
            lo_off, hi_off = 5.0, 80.0
            for _ in range(15):
                mid_off = (lo_off + hi_off) / 2
                wp = self._make_waypoints(tee, green, dx, dy, perp_x, perp_y,
                                          t_values, signs, mid_off,
                                          terrain_offsets, clamp_margin)
                pl = polyline_length(wp)
                if pl < target_dist:
                    lo_off = mid_off
                else:
                    hi_off = mid_off
            best_offset = (lo_off + hi_off) / 2
        else:
            best_offset = self.rng.uniform(8, min(25, length * 0.15))

        waypoints = self._make_waypoints(tee, green, dx, dy, perp_x, perp_y,
                                         t_values, signs, best_offset,
                                         terrain_offsets, clamp_margin)
        return waypoints

    def _make_waypoints(self, tee, green, dx, dy, perp_x, perp_y,
                        t_values, signs, base_offset, terrain_offsets,
                        clamp_margin) -> list[tuple[float, float]]:
        """Génère les waypoints avec un offset donné."""
        waypoints = [tee]
        for k, t in enumerate(t_values):
            px = tee[0] + dx * t
            py = tee[1] + dy * t

            offset = signs[k] * base_offset + terrain_offsets[k]
            px += perp_x * offset
            py += perp_y * offset

            px = max(clamp_margin, min(self.w - clamp_margin, px))
            py = max(clamp_margin, min(self.h - clamp_margin, py))
            waypoints.append((px, py))

        waypoints.append(green)
        return waypoints

    def _constrain_to_cell(self, px: float, py: float,
                           owner: np.ndarray, hole_idx: int
                           ) -> tuple[float, float]:
        """Si le point est hors de la cellule, le ramener à l'intérieur."""
        tx = int(px / self.tile_size)
        ty = int(py / self.tile_size)
        if self._tile_valid(tx, ty) and owner[ty, tx] == hole_idx:
            return (px, py)

        # Chercher la tile la plus proche appartenant à cette cellule
        best_dist = float('inf')
        best_pos = (px, py)
        for r in range(1, 8):
            for dty in range(-r, r + 1):
                for dtx in range(-r, r + 1):
                    if abs(dtx) != r and abs(dty) != r:
                        continue
                    ntx, nty = tx + dtx, ty + dty
                    if self._tile_valid(ntx, nty) and owner[nty, ntx] == hole_idx:
                        cx = ntx * self.tile_size + self.tile_size // 2
                        cy = nty * self.tile_size + self.tile_size // 2
                        d = (cx - px) ** 2 + (cy - py) ** 2
                        if d < best_dist:
                            best_dist = d
                            best_pos = (float(cx), float(cy))
            if best_dist < float('inf'):
                break
        return best_pos

    # --- Validation eau ---

    def _is_on_land(self, pos: tuple[float, float]) -> bool:
        """Vérifie que la position n'est pas sur l'eau."""
        x, y = int(pos[0]), int(pos[1])
        half = self.tile_size // 2
        x0 = max(0, x - half)
        x1 = min(self.w, x + half + 1)
        y0 = max(0, y - half)
        y1 = min(self.h, y + half + 1)
        water_ratio = self.water_mask[y0:y1, x0:x1].mean()
        return water_ratio < 0.3

    def _ensure_on_land(self, pos: tuple[float, float]) -> tuple[float, float]:
        """Si la position est sur l'eau, cherche la tile terre la plus proche."""
        if self._is_on_land(pos):
            return pos

        best_pos = pos
        best_dist = float('inf')
        for dy in range(-3, 4):
            for dx in range(-3, 4):
                candidate = snap_to_tile(
                    pos[0] + dx * self.tile_size,
                    pos[1] + dy * self.tile_size,
                    self.tile_size,
                )
                if not (0 <= candidate[0] < self.w and 0 <= candidate[1] < self.h):
                    continue
                if self._is_on_land(candidate):
                    d = distance(pos, candidate)
                    if d < best_dist:
                        best_dist = d
                        best_pos = candidate
        return best_pos

    # --- Utilitaires ---

    def _par_weight(self, par: int) -> float:
        """Retourne le poids de surface pour un par donné."""
        if par == 3:
            return self.rc.par3_weight
        elif par == 5:
            return self.rc.par5_weight
        else:
            return self.rc.par4_weight

    def _terrain_offset(self, pos: tuple[float, float],
                        perp: tuple[float, float]) -> float:
        x, y = int(pos[0]), int(pos[1])
        if not (2 <= x < self.w - 2 and 2 <= y < self.h - 2):
            return 0.0
        dzdx, dzdy = gradient_at(self.heightmap, x, y)
        return -(dzdx * perp[0] + dzdy * perp[1])

    def _format_hole(self, hole_id: int, par: int, blocks: int,
                     fw_width: float, green_radius: int,
                     waypoints: list[tuple[float, float]],
                     tee_elev: float, green_elev: float) -> dict:
        tee = waypoints[0]
        green_pos = waypoints[-1]
        return {
            "id": hole_id, "par": par, "blocks": blocks,
            "tee": {"x": round(tee[0], 1), "y": round(tee[1], 1),
                    "elevation": round(tee_elev, 1)},
            "green": {"x": round(green_pos[0], 1), "y": round(green_pos[1], 1),
                      "radius": green_radius, "elevation": round(green_elev, 1)},
            "waypoints": [{"x": round(p[0], 1), "y": round(p[1], 1)}
                          for p in waypoints],
            "fairway_width": fw_width,
            "direction": direction_label(tee, green_pos),
        }

    def _par_range(self, par: int) -> tuple[int, int]:
        if par == 3:
            return self.rc.par3_range
        elif par == 5:
            return self.rc.par5_range
        else:
            return self.rc.par4_range

    def _fairway_width(self, par: int) -> int:
        if par == 3:
            return self.rc.fairway_width_par3
        elif par == 5:
            return self.rc.fairway_width_par5
        else:
            return self.rc.fairway_width_par4

    def _elevation_at(self, pos: tuple[float, float]) -> float:
        x = max(0, min(self.w - 1, int(pos[0])))
        y = max(0, min(self.h - 1, int(pos[1])))
        return float(self.heightmap[y, x])
