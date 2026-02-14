"""Placement des 18 trous sur la grille terrain."""

from __future__ import annotations

import math
import random

import numpy as np

from golfgen.config import CourseConfig
from golfgen.hole_gen import HoleGenerator, HoleShape
from golfgen.utils import (
    distance, direction_label, point_to_segment_dist, polyline_length,
    segments_intersect,
)

class CoursePlacer:
    """Place les trous sur la grille 350×350 avec enchaînement."""

    def __init__(self, config: CourseConfig, heightmap: np.ndarray):
        self.config = config
        self.heightmap = heightmap
        self.rc = config.routing
        self.rng = random.Random(config.seed + 1000)
        self.placed_segments: list[tuple] = []  # [(p1, p2, fairway_width), ...]
        self.placed_points: list[tuple] = []  # tees + greens déjà placés

    def _pick_clubhouse(self) -> tuple[tuple, float]:
        """Choisit un coin pour le clubhouse basé sur la seed.

        Retourne (position, angle_séparation) où l'angle sépare
        les deux nines en secteurs angulaires depuis le coin.
        """
        w, h = self.config.width, self.config.height
        margin = 45
        corners = [
            ((margin, margin),         math.pi / 4),       # NO — diag vers SE
            ((w - margin, margin),     3 * math.pi / 4),   # NE — diag vers SO
            ((margin, h - margin),    -math.pi / 4),       # SO — diag vers NE
            ((w - margin, h - margin), -3 * math.pi / 4),  # SE — diag vers NO
        ]
        idx = self.rng.randint(0, 3)
        pos, sep_angle = corners[idx]
        print(f"     Clubhouse: coin {['NO','NE','SO','SE'][idx]} ({pos[0]:.0f}, {pos[1]:.0f})")
        return pos, sep_angle

    def place(self, hole_gen: HoleGenerator) -> list[dict]:
        """Place les 18 trous et retourne la liste pour l'export.

        Pour chaque trou, génère plusieurs formes candidates et garde
        la meilleure combo forme×angle×position.
        """
        w, h = self.config.width, self.config.height
        start, self.sep_angle = self._pick_clubhouse()
        self.clubhouse_pos = start
        pars = self.rc.par_distribution[:self.config.num_holes]
        n_shape_candidates = 4

        holes = []
        placed_wps: list[list[tuple]] = []
        placed_shapes: list[HoleShape] = []
        prev_green = start

        for idx, par in enumerate(pars):
            hole_id = idx + 1

            if hole_id == 10:
                prev_green = start
            return_to_start = (hole_id == 9 or hole_id == 18)

            # Générer plusieurs formes et garder le meilleur placement
            best = None
            best_shape = None
            best_score = float("inf")
            for _ in range(n_shape_candidates):
                shape = hole_gen.generate_one(par)
                result = self._find_placement(
                    shape, prev_green, hole_id,
                    return_to_start=return_to_start,
                )
                if result is not None:
                    abs_wps, angle, score = result
                    if score < best_score:
                        best_score = score
                        best = (abs_wps, angle)
                        best_shape = shape

            if best is None:
                shape = hole_gen.generate_one(par)
                print(f"  WARN: trou {hole_id} — placement forcé")
                best = self._force_placement(shape, prev_green)
                best_shape = shape

            abs_wps, angle = best
            shape = best_shape

            for i in range(len(abs_wps) - 1):
                self.placed_segments.append(
                    (abs_wps[i], abs_wps[i + 1], shape.fairway_width)
                )

            placed_wps.append(abs_wps)
            placed_shapes.append(shape)
            self.placed_points.append(abs_wps[0])
            self.placed_points.append(abs_wps[-1])
            prev_green = abs_wps[-1]

            hole = self._make_hole_dict(hole_id, shape, abs_wps)
            holes.append(hole)

        # Post-traitement
        holes = self._postprocess(holes, placed_wps, placed_shapes)

        return holes

    def _find_placement(self, shape: HoleShape, tee_near: tuple,
                        hole_id: int, return_to_start: bool = False,
                        ) -> tuple | None:
        """Essaie plusieurs angles, retourne (abs_waypoints, angle, score) ou None."""
        w, h = self.config.width, self.config.height
        margin = self.rc.grid_margin
        center = self.clubhouse_pos
        link_dist = self.rc.tee_link_distance

        # 72 directions espacées de 5°
        angles = [i * math.pi / 36 for i in range(72)]
        self.rng.shuffle(angles)

        # Pour les trous de retour, ajouter des angles pointant vers le centre
        if return_to_start:
            angle_to_center = math.atan2(
                center[1] - tee_near[1], center[0] - tee_near[0])
            # Ajouter 8 angles proches de la direction vers le centre
            for delta in [-0.3, -0.2, -0.1, 0, 0.1, 0.2, 0.3, 0.15]:
                angles.insert(0, angle_to_center + delta)

        best = None
        best_score = float("inf")

        min_link = 12  # distance min green→tee
        max_link = link_dist  # distance max

        # RNG séparé pour les offsets de tee (ne perturbe pas le RNG principal)
        if return_to_start:
            cur_min, cur_max = 8, 15
        else:
            cur_min, cur_max = min_link, link_dist
        tee_tries = 8
        tee_rng = random.Random(self.config.seed + 2000 + hole_id)

        for angle in angles:
          for _try in range(tee_tries):
            offset_angle = tee_rng.uniform(0, 2 * math.pi)
            offset_dist = tee_rng.uniform(cur_min, cur_max)
            tee_offset_x = offset_dist * math.cos(offset_angle)
            tee_offset_y = offset_dist * math.sin(offset_angle)
            tee_pos = (tee_near[0] + tee_offset_x, tee_near[1] + tee_offset_y)

            abs_wps = self._transform(shape.waypoints, tee_pos, angle)

            if not self._in_bounds(abs_wps, margin):
                continue

            # --- Scoring ---
            overlap, has_crossing = self._overlap_score(abs_wps, shape.fairway_width)

            # Retour au clubhouse (trous 9, 18)
            # Le green doit s'arrêter juste avant le CH (~20 blocs)
            return_penalty = 0.0
            if return_to_start:
                d = distance(abs_wps[-1], center)
                target_dist = 20  # pas sur le CH, juste avant
                return_penalty = (d - target_dist) ** 2 * 10

            # Distance tee → green précédent
            tee_dist = distance(abs_wps[0], tee_near)

            # Trous 1 et 10 : tee proche du clubhouse
            center_penalty = 0.0
            if hole_id in (1, 10):
                center_penalty = distance(abs_wps[0], center) ** 2 * 0.3

            # Protection clubhouse : segments ne passent pas sur le CH
            # Exempt pour les trous de retour (9, 18) qui y reviennent
            clubhouse_penalty = 0.0
            if not return_to_start:
                ch_exclusion = 25
                for i in range(len(abs_wps) - 1):
                    d = point_to_segment_dist(
                        center[0], center[1],
                        abs_wps[i][0], abs_wps[i][1],
                        abs_wps[i+1][0], abs_wps[i+1][1])
                    if d < ch_exclusion:
                        clubhouse_penalty += (ch_exclusion - d) ** 2 * 100

            # Convergence pré-retour : greens 7-8 et 16-17 proches du CH
            # Le green doit être à distance ≈ longueur du trou suivant
            # pour que le trou de retour puisse viser le CH
            converge_penalty = 0.0
            if hole_id in (7, 8, 16, 17):
                d_green = distance(abs_wps[-1], center)
                # Trous 7 et 16 : green à ~180 blocs (loin mais en approche)
                if hole_id in (7, 16) and d_green > 180:
                    converge_penalty = (d_green - 180) ** 2 * 2
                # Trous 8 et 17 : green à distance ≈ longueur du trou suivant
                # Trop proche = le retour dépasse le CH
                # Trop loin = le retour ne peut pas atteindre le CH
                if hole_id in (8, 17):
                    # Longueur typique du trou de retour (par 4)
                    target = 110
                    converge_penalty += (d_green - target) ** 2 * 8

            # Territoire : secteurs angulaires depuis le clubhouse
            # Exempt pour les trous de retour qui doivent traverser
            territory_penalty = 0.0
            cx, cy = center
            sep = self.sep_angle
            if not return_to_start:
                for wp in abs_wps:
                    wp_angle = math.atan2(wp[1] - cy, wp[0] - cx)
                    rel = wp_angle - sep
                    if rel > math.pi: rel -= 2 * math.pi
                    if rel < -math.pi: rel += 2 * math.pi
                    if hole_id <= 9 and rel < 0:
                        territory_penalty += rel ** 2 * 300
                    elif hole_id > 9 and rel > 0:
                        territory_penalty += rel ** 2 * 300

            # Pour les trous de retour, l'overlap pèse moins
            # car ils doivent traverser des zones déjà occupées
            if return_to_start:
                overlap *= 0.1

            score = (overlap + return_penalty + tee_dist
                     + center_penalty + clubhouse_penalty
                     + territory_penalty + converge_penalty)

            # Croisement = plancher (sauf trous de retour 9/18)
            if has_crossing and not return_to_start:
                score += 1_000_000

            if score < best_score:
                best_score = score
                best = (abs_wps, angle, score)


        return best

    def _force_placement(self, shape: HoleShape, tee_near: tuple,
                         ) -> tuple:
        """Placement de secours : prend le premier angle qui rentre dans la grille."""
        margin = self.rc.grid_margin
        for angle_deg in range(0, 360, 15):
            angle = math.radians(angle_deg)
            abs_wps = self._transform(shape.waypoints, tee_near, angle)
            if self._in_bounds(abs_wps, margin):
                return (abs_wps, angle)

        abs_wps = self._transform(shape.waypoints, tee_near, 0)
        return (abs_wps, 0)

    def _transform(self, local_wps: list[tuple], tee_pos: tuple,
                   angle: float) -> list[tuple]:
        """Rotation + translation des waypoints locaux → coordonnées absolues."""
        cos_a = math.cos(angle)
        sin_a = math.sin(angle)
        result = []
        for lx, ly in local_wps:
            rx = lx * cos_a - ly * sin_a
            ry = lx * sin_a + ly * cos_a
            result.append((tee_pos[0] + rx, tee_pos[1] + ry))
        return result

    def _in_bounds(self, abs_wps: list[tuple], margin: int) -> bool:
        """Vérifie que tous les waypoints sont dans la grille avec marge."""
        w, h = self.config.width, self.config.height
        for x, y in abs_wps:
            if x < margin or x > w - margin or y < margin or y > h - margin:
                return False
        return True

    def _overlap_score(self, abs_wps: list[tuple], fw: int) -> tuple[float, bool]:
        """Score de chevauchement avec les trous déjà placés.

        Retourne (score, has_crossing) pour permettre un traitement
        multiplicatif des croisements dans le scoring global.
        """
        score = 0.0
        has_crossing = False

        for i in range(len(abs_wps) - 1):
            p1, p2 = abs_wps[i], abs_wps[i + 1]
            for seg_p1, seg_p2, seg_fw in self.placed_segments:
                mid_new = ((p1[0] + p2[0]) / 2, (p1[1] + p2[1]) / 2)
                mid_old = ((seg_p1[0] + seg_p2[0]) / 2, (seg_p1[1] + seg_p2[1]) / 2)

                if distance(mid_new, mid_old) > 100:
                    continue

                # Croisement réel
                if segments_intersect(p1, p2, seg_p1, seg_p2):
                    has_crossing = True

                # Distance minimale entre les deux segments
                d = min(
                    point_to_segment_dist(p1[0], p1[1], seg_p1[0], seg_p1[1], seg_p2[0], seg_p2[1]),
                    point_to_segment_dist(p2[0], p2[1], seg_p1[0], seg_p1[1], seg_p2[0], seg_p2[1]),
                    point_to_segment_dist(seg_p1[0], seg_p1[1], p1[0], p1[1], p2[0], p2[1]),
                    point_to_segment_dist(seg_p2[0], seg_p2[1], p1[0], p1[1], p2[0], p2[1]),
                )

                threshold = (fw + seg_fw) / 2 + 5
                if d < threshold:
                    score += (threshold - d) ** 2

        # Pénalité si un segment du nouveau trou passe sur un tee/green existant
        for i in range(len(abs_wps) - 1):
            p1, p2 = abs_wps[i], abs_wps[i + 1]
            for pt in self.placed_points:
                d = point_to_segment_dist(pt[0], pt[1], p1[0], p1[1], p2[0], p2[1])
                if d < fw / 2 + 3:
                    score += (fw / 2 + 3 - d) ** 2 * 500

        # Pénalité si un tee/green du nouveau trou est sur un segment existant
        for wp in (abs_wps[0], abs_wps[-1]):
            for seg_p1, seg_p2, seg_fw in self.placed_segments:
                d = point_to_segment_dist(wp[0], wp[1], seg_p1[0], seg_p1[1], seg_p2[0], seg_p2[1])
                if d < seg_fw / 2 + 3:
                    score += (seg_fw / 2 + 3 - d) ** 2 * 500

        return score, has_crossing

    # --- Post-traitement ---

    def _postprocess(self, holes: list[dict], placed_wps: list[list[tuple]],
                     shapes: list[HoleShape]) -> list[dict]:
        """Corrections post-placement (placeholder pour futures passes)."""
        return holes

    # --- Utilitaires ---

    def _make_hole_dict(self, hole_id: int, shape: HoleShape,
                        abs_wps: list[tuple]) -> dict:
        """Construit le dict d'un trou pour l'export."""
        tee = abs_wps[0]
        green = abs_wps[-1]

        tee_elev = self._elevation_at(tee)
        green_elev = self._elevation_at(green)

        waypoints = [{"x": round(p[0], 1), "y": round(p[1], 1)} for p in abs_wps]
        blocks = int(polyline_length(abs_wps))

        return {
            "id": hole_id,
            "par": shape.par,
            "blocks": blocks,
            "tee": {"x": round(tee[0], 1), "y": round(tee[1], 1),
                    "elevation": tee_elev},
            "green": {"x": round(green[0], 1), "y": round(green[1], 1),
                      "radius": shape.green_radius, "elevation": green_elev},
            "waypoints": waypoints,
            "fairway_width": shape.fairway_width,
            "direction": direction_label(tee, green),
        }

    def _elevation_at(self, pos: tuple) -> float:
        """Élévation du terrain à une position."""
        x = max(0, min(int(pos[0]), self.heightmap.shape[1] - 1))
        y = max(0, min(int(pos[1]), self.heightmap.shape[0] - 1))
        return float(self.heightmap[y, x])
