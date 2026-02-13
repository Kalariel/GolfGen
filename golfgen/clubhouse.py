"""Placement optimal du clubhouse a la jonction de 4 cellules."""

from __future__ import annotations

import numpy as np

from .config import CourseConfig


class ClubhousePlacer:
    """Place le clubhouse, le practice range et le putting green.

    Phase 1 : Trouver les quad junctions (>= 4 cellules distinctes).
    Phase 2 : Scorer les candidats (quad bonus, platitude, elevation, centralite).
    Phase 3 : Aplatir le terrain autour de la position choisie.
    Phase 4 : Placer le practice range et le putting green.
    Phase 5 : Mettre a jour la config.
    """

    def __init__(self, config: CourseConfig, heightmap: np.ndarray,
                 owner: np.ndarray, seeds: list[tuple[int, int]],
                 cell_sizes: list[int]):
        self.config = config
        self.heightmap = heightmap
        self.owner = owner
        self.seeds = seeds
        self.cell_sizes = cell_sizes
        self.ch = config.clubhouse
        self.tile_size = config.paving.tile_size

    def place(self) -> dict:
        """Retourne le dict clubhouse pour l'export JSON.
        Met a jour config.clubhouse_x/y et modifie heightmap in-place."""
        # Si position forcee dans la config
        if self.config.clubhouse_x is not None and self.config.clubhouse_y is not None:
            bx = self.config.clubhouse_x
            by = self.config.clubhouse_y
            adjacent = self._get_adjacent_cells(bx, by)
        else:
            bx, by, adjacent = self._find_best_position()

        elevation = float(self.heightmap[by, bx])

        # Phase 3 : Aplatir
        self._flatten_area(bx, by)

        # Phase 4 : Practice range et putting green
        practice = self._place_practice_range(bx, by)
        putting = self._place_putting_green(bx, by, practice["direction"])

        # Aplatir practice et putting
        self._flatten_rect(
            practice["x"], practice["y"],
            practice["width"], practice["height"],
            transition=10,
        )
        self._flatten_circle(
            putting["x"], putting["y"],
            putting["radius"] + 5,
            transition=8,
        )

        # Phase 5 : Mettre a jour la config
        self.config.clubhouse_x = bx
        self.config.clubhouse_y = by

        return {
            "x": bx,
            "y": by,
            "width": self.ch.width,
            "height": self.ch.height,
            "elevation": round(elevation, 1),
            "adjacent_cells": sorted(adjacent),
            "practice_range": practice,
            "putting_green": putting,
        }

    # ------------------------------------------------------------------
    # Phase 1 : Quad junctions
    # ------------------------------------------------------------------

    def _find_candidates(self) -> list[tuple[int, int, set[int]]]:
        """Trouve les positions avec >= 4 cellules distinctes sous le clubhouse."""
        th, tw = self.owner.shape
        ch_w_tiles = self.ch.width // self.tile_size
        ch_h_tiles = self.ch.height // self.tile_size
        hw = ch_w_tiles // 2
        hh = ch_h_tiles // 2

        candidates = []
        # Marge pour ne pas deborder
        margin = 2
        for ty in range(hh + margin, th - hh - margin):
            for tx in range(hw + margin, tw - hw - margin):
                window = self.owner[ty - hh:ty + hh + 1, tx - hw:tx + hw + 1]
                ids = set(int(v) for v in np.unique(window)) - {-1}
                if len(ids) >= 4:
                    candidates.append((tx, ty, ids))

        return candidates

    # ------------------------------------------------------------------
    # Phase 2 : Scoring
    # ------------------------------------------------------------------

    def _find_best_position(self) -> tuple[int, int, list[int]]:
        """Trouve la meilleure position pour le clubhouse."""
        candidates = self._find_candidates()

        if not candidates:
            # Fallback : centre de la grille
            th, tw = self.owner.shape
            tx, ty = tw // 2, th // 2
            bx = tx * self.tile_size + self.tile_size // 2
            by = ty * self.tile_size + self.tile_size // 2
            adjacent = self._get_adjacent_cells(bx, by)
            return bx, by, adjacent

        h, w = self.heightmap.shape
        center_tx = self.owner.shape[1] / 2.0
        center_ty = self.owner.shape[0] / 2.0
        max_dist = np.sqrt(center_tx**2 + center_ty**2)
        base_elev = self.config.terrain.base_elevation

        best_score = -1.0
        best_tx, best_ty = candidates[0][0], candidates[0][1]
        best_ids: set[int] = candidates[0][2]

        for tx, ty, ids in candidates:
            # Convertir en coordonnees bloc
            bx = tx * self.tile_size + self.tile_size // 2
            by = ty * self.tile_size + self.tile_size // 2

            # 1. Quad bonus (40pts si 4, 25pts si 5+)
            if len(ids) == 4:
                quad_score = 40.0
            else:
                quad_score = 25.0

            # 2. Platitude (30pts)
            hw_px = self.ch.width // 2
            hh_px = self.ch.height // 2
            y0 = max(0, by - hh_px)
            y1 = min(h, by + hh_px)
            x0 = max(0, bx - hw_px)
            x1 = min(w, bx + hw_px)
            patch = self.heightmap[y0:y1, x0:x1]
            flat_score = 30.0 * np.exp(-float(patch.std()) / 2.0)

            # 3. Elevation proche de base_elevation (20pts)
            elev_diff = abs(float(patch.mean()) - base_elev)
            elev_score = 20.0 * np.exp(-elev_diff / 5.0)

            # 4. Centralite (10pts)
            dist = np.sqrt((tx - center_tx)**2 + (ty - center_ty)**2)
            central_score = 10.0 * (1.0 - dist / max_dist)

            score = quad_score + flat_score + elev_score + central_score
            if score > best_score:
                best_score = score
                best_tx, best_ty = tx, ty
                best_ids = ids

        bx = best_tx * self.tile_size + self.tile_size // 2
        by = best_ty * self.tile_size + self.tile_size // 2
        return bx, by, sorted(best_ids)

    def _get_adjacent_cells(self, bx: int, by: int) -> list[int]:
        """Retourne les IDs des cellules sous le clubhouse."""
        tx = bx // self.tile_size
        ty = by // self.tile_size
        th, tw = self.owner.shape
        ch_w_tiles = self.ch.width // self.tile_size
        ch_h_tiles = self.ch.height // self.tile_size
        hw = ch_w_tiles // 2
        hh = ch_h_tiles // 2

        y0 = max(0, ty - hh)
        y1 = min(th, ty + hh + 1)
        x0 = max(0, tx - hw)
        x1 = min(tw, tx + hw + 1)
        window = self.owner[y0:y1, x0:x1]
        ids = set(int(v) for v in np.unique(window)) - {-1}
        return sorted(ids)

    # ------------------------------------------------------------------
    # Phase 3 : Aplatissement
    # ------------------------------------------------------------------

    def _flatten_area(self, cx: int, cy: int) -> None:
        """Aplatit le terrain autour du clubhouse."""
        radius = max(self.ch.width, self.ch.height) // 2 + self.ch.flat_radius_margin
        transition = self.ch.flat_transition

        h, w = self.heightmap.shape

        # Elevation cible = mediane locale clippee autour de base_elevation +/- 2
        hw_px = self.ch.width // 2
        hh_px = self.ch.height // 2
        y0 = max(0, cy - hh_px)
        y1 = min(h, cy + hh_px)
        x0 = max(0, cx - hw_px)
        x1 = min(w, cx + hw_px)
        patch = self.heightmap[y0:y1, x0:x1]
        base = self.config.terrain.base_elevation
        target_elev = float(np.clip(np.median(patch), base - 2, base + 2))

        yy, xx = np.mgrid[0:h, 0:w]
        dist = np.sqrt((xx - cx) ** 2 + (yy - cy) ** 2).astype(np.float32)

        # Facteur de melange : 1 = terrain original, 0 = plat
        blend = np.clip((dist - radius) / transition, 0.0, 1.0)

        self.heightmap[:] = self.heightmap * blend + target_elev * (1 - blend)

    def _flatten_rect(self, rx: int, ry: int, rw: int, rh: int,
                      transition: int = 10) -> None:
        """Aplatit une zone rectangulaire."""
        h, w = self.heightmap.shape
        cx = rx + rw // 2
        cy = ry + rh // 2
        radius = max(rw, rh) // 2 + 5
        base = self.config.terrain.base_elevation

        y0 = max(0, ry)
        y1 = min(h, ry + rh)
        x0 = max(0, rx)
        x1 = min(w, rx + rw)
        patch = self.heightmap[y0:y1, x0:x1]
        target_elev = float(np.clip(np.median(patch), base - 2, base + 2))

        yy, xx = np.mgrid[0:h, 0:w]
        dist = np.sqrt((xx - cx) ** 2 + (yy - cy) ** 2).astype(np.float32)
        blend = np.clip((dist - radius) / transition, 0.0, 1.0)
        self.heightmap[:] = self.heightmap * blend + target_elev * (1 - blend)

    def _flatten_circle(self, cx: int, cy: int, radius: int,
                        transition: int = 8) -> None:
        """Aplatit une zone circulaire."""
        h, w = self.heightmap.shape
        base = self.config.terrain.base_elevation

        y0 = max(0, cy - radius)
        y1 = min(h, cy + radius)
        x0 = max(0, cx - radius)
        x1 = min(w, cx + radius)
        patch = self.heightmap[y0:y1, x0:x1]
        target_elev = float(np.clip(np.median(patch), base - 2, base + 2))

        yy, xx = np.mgrid[0:h, 0:w]
        dist = np.sqrt((xx - cx) ** 2 + (yy - cy) ** 2).astype(np.float32)
        blend = np.clip((dist - radius) / transition, 0.0, 1.0)
        self.heightmap[:] = self.heightmap * blend + target_elev * (1 - blend)

    # ------------------------------------------------------------------
    # Phase 4 : Practice range et putting green
    # ------------------------------------------------------------------

    def _place_practice_range(self, ch_x: int, ch_y: int) -> dict:
        """Place le practice range dans la meilleure direction."""
        h, w = self.heightmap.shape
        pl = self.ch.practice_length
        pw = self.ch.practice_width
        ch_w = self.ch.width
        ch_h = self.ch.height

        # 4 directions possibles : N, S, E, O
        candidates = {
            "N": (ch_x - pw // 2, ch_y - ch_h // 2 - pl - 5, pw, pl),
            "S": (ch_x - pw // 2, ch_y + ch_h // 2 + 5, pw, pl),
            "E": (ch_x + ch_w // 2 + 5, ch_y - pw // 2, pl, pw),
            "W": (ch_x - ch_w // 2 - pl - 5, ch_y - pw // 2, pl, pw),
        }

        best_dir = None
        best_score = -999.0

        for direction, (rx, ry, rw, rh) in candidates.items():
            # Verifier les limites
            if rx < 0 or ry < 0 or rx + rw >= w or ry + rh >= h:
                continue

            # Verifier pas d'eau (water_level)
            patch = self.heightmap[ry:ry + rh, rx:rx + rw]
            water_level = self.config.paving.water_level
            water_ratio = float((patch < water_level).sum()) / max(patch.size, 1)
            if water_ratio > 0.1:
                continue

            # Score = platitude (std faible = bon)
            score = -float(patch.std())
            if score > best_score:
                best_score = score
                best_dir = direction

        if best_dir is None:
            # Fallback : Nord
            best_dir = "N"

        rx, ry, rw, rh = candidates[best_dir]
        # Clip aux limites
        rx = max(0, min(rx, w - rw - 1))
        ry = max(0, min(ry, h - rh - 1))

        return {
            "x": rx, "y": ry,
            "width": rw, "height": rh,
            "direction": best_dir,
        }

    def _place_putting_green(self, ch_x: int, ch_y: int,
                             practice_dir: str) -> dict:
        """Place le putting green cote oppose au practice."""
        r = self.ch.putting_radius
        ch_w = self.ch.width
        ch_h = self.ch.height
        h, w = self.heightmap.shape

        # Cote oppose au practice
        opposite = {"N": "S", "S": "N", "E": "W", "W": "E"}
        put_dir = opposite.get(practice_dir, "S")

        offsets = {
            "N": (0, -(ch_h // 2 + r + 5)),
            "S": (0, ch_h // 2 + r + 5),
            "E": (ch_w // 2 + r + 5, 0),
            "W": (-(ch_w // 2 + r + 5), 0),
        }

        dx, dy = offsets[put_dir]
        px = ch_x + dx
        py = ch_y + dy

        # Clip aux limites
        px = max(r + 1, min(px, w - r - 1))
        py = max(r + 1, min(py, h - r - 1))

        return {
            "x": px, "y": py,
            "radius": r,
        }
