"""Genetic Algorithm for Golf Course Generation using DEAP."""
from __future__ import annotations

print("🚀 Starting ga.py... (debug)")

import math
import random
import array
from typing import List, Tuple, Dict, Optional

import numpy as np
from deap import base, creator, tools, algorithms

from golfgen.config import CourseConfig
from golfgen.hole_gen import HoleGenerator, HoleShape
from golfgen.utils import distance, point_to_segment_dist, segments_intersect, direction_label, polyline_length

# --- DEAP Setup ---
# Minimize fitness (penalties)
creator.create("FitnessMin", base.Fitness, weights=(-1.0,))
# Individual is a list of floats: [angle_1, dist_1, shape_seed_1, ..., angle_18, dist_18, shape_seed_18]
creator.create("Individual", array.array, typecode='d', fitness=creator.FitnessMin)

class GeneticOptimizer:
    """Optimizes course layout using Evolutionary Strategy."""

    def __init__(self, config: CourseConfig, heightmap: np.ndarray):
        self.config = config
        self.heightmap = heightmap
        self.hole_gen = HoleGenerator(config)
        self.toolbox = base.Toolbox()
        self.rng = random.Random(config.seed)
        
        # Determine clubhouse position (same logic as placer for now)
        self.clubhouse_pos, self.sep_angle = self._pick_clubhouse()
        
        self._setup_deap()

    def _pick_clubhouse(self) -> Tuple[Tuple[float, float], float]:
        """Chooses clubhouse position based on seed.
        
        Positions are ~30% from each edge, giving holes room to spread
        in all directions without being crammed against walls.
        """
        w, h = self.config.width, self.config.height
        offset = int(w * 0.30)  # ~105 for a 350 grid
        positions = [
            ((offset, offset),         math.pi / 4),       # NO quadrant
            ((w - offset, offset),     3 * math.pi / 4),   # NE quadrant
            ((offset, h - offset),    -math.pi / 4),       # SO quadrant
            ((w - offset, h - offset), -3 * math.pi / 4),  # SE quadrant
        ]
        idx = self.rng.randint(0, 3)
        return positions[idx]

    def _rotate_waypoints(self, waypoints: list[tuple], angle: float) -> list[tuple]:
        """Rotates a list of waypoints around the origin by a given angle."""
        cos_a = math.cos(angle)
        sin_a = math.sin(angle)
        result = []
        for x, y in waypoints:
            rx = x * cos_a - y * sin_a
            ry = x * sin_a + y * cos_a
            result.append((rx, ry))
        return result

    def _setup_deap(self):
        """Configures DEAP toolbox."""
        # Operators
        self.toolbox.register("evaluate", self.evaluate)
        self.toolbox.register("mate", tools.cxTwoPoint)
        self.toolbox.register("mutate", tools.mutGaussian, mu=0.0, sigma=0.15, indpb=0.15)
        self.toolbox.register("select", tools.selTournament, tournsize=3)

    def _create_seeded_individual(self, noise: float = 0.0) -> creator.Individual:
        """Creates an individual with a loop layout pattern.
        
        Each nine follows an out-and-back loop from the clubhouse.
        The angle gene controls direction from the previous green to the next tee.
        We seed angles to create a smooth progressive turn (loop shape).
        """
        n = self.config.num_holes
        genes = []
        
        for i in range(n):
            nine_idx = i % 9  # Position within the current nine (0-8)
            nine_num = i // 9  # Which nine (0 = front, 1 = back)

            # Create a loop: progressive turn through 360 degrees over 9 holes
            # Each hole turns ~40 degrees (360/9) to form a complete loop
            base_sector = (nine_idx / 9.0)  # 0..0.89 of the circle

            # Offset front vs back nine so they don't overlap
            if nine_num == 0:
                angle_gene = base_sector  # Front nine: 0..0.89
            else:
                angle_gene = (base_sector + 0.5) % 1.0  # Back nine: offset by half circle

            # Add controlled noise
            angle_gene += self.rng.gauss(0, 0.01 + noise * 0.03)
            angle_gene = angle_gene % 1.0

            # Distance: shorter for return holes (6-9), longer for outgoing (1-5)
            if nine_idx < 5:
                dist_gene = 0.4 + self.rng.gauss(0, 0.03 + noise * 0.05)
            else:
                dist_gene = 0.3 + self.rng.gauss(0, 0.03 + noise * 0.05)
            dist_gene = max(0.05, min(0.95, dist_gene))

            # Shape seed: random
            shape_gene = self.rng.random()

            # Rotation gene: small random angle (0 to 0.5 radians) to define hole orientation
            rotation_gene = self.rng.gauss(0, 0.05)  # Small random rotation
            rotation_gene = max(-0.5, min(0.5, rotation_gene))  # Clamp to [-0.5, 0.5]

            genes.extend([angle_gene, dist_gene, shape_gene, rotation_gene])
        
        return creator.Individual(array.array('d', genes))

    def run(self) -> List[Dict]:
        """Runs the evolutionary algorithm and returns the best course layout."""
        pop_size = 300
        n_gen = 120
        consecutive_no_improvement = 10  # Stop if no improvement for 10 generations
        
        # Create population: half seeded, half with noise
        pop = []
        for i in range(pop_size):
            noise = (i / pop_size) * 0.5  # Gradually increasing noise
            ind = self._create_seeded_individual(noise)
            pop.append(ind)
        
        stats = tools.Statistics(lambda ind: ind.fitness.values)
        stats.register("min", np.min)
        stats.register("avg", np.mean)
        
        # Elitism
        hall_of_fame = tools.HallOfFame(1)
        
        print(f"Starting Evolution (Pop: {pop_size}, Gen: {n_gen})")
        
        # Track best fitness seen
        best_fitness_so_far = float('inf')
        generations_without_improvement = 0
        
        # Run standard GA with early stopping
        for gen in range(n_gen):
            # Evaluate population
            pop, logbook = algorithms.eaSimple(
                pop, self.toolbox, cxpb=0.5, mutpb=0.2,
                ngen=1,  # Only one generation at a time for monitoring
                stats=stats, halloffame=hall_of_fame, verbose=False
            )

            # Get best individual fitness
            best_fitness_this_gen = min(ind.fitness.values[0] / 10000 for ind in pop)
            print(f"Best fitness this gen: {best_fitness_this_gen} (type: {type(best_fitness_this_gen)})")
            # Check if fitness improved
            if best_fitness_this_gen < best_fitness_so_far:
                best_fitness_so_far = best_fitness_this_gen
                generations_without_improvement = 0
            else:
                generations_without_improvement += 1

            # Check for early stopping


        best_ind = hall_of_fame[0]
        print(f"Best Fitness: {best_ind.fitness.values[0]:.2f}")

        # Convert best individual to course format
        return self._genome_to_course(best_ind)

    def evaluate(self, individual) -> Tuple[float]:
        """Fitness function: calculates penalties for the entire course."""
        holes, penalties = self._build_course(individual)
        
        # If construction failed critically (e.g. out of bounds), return high penalty
        if holes is None:
            return (1e9,)
            
        score = penalties
        
        # --- Constraints & Penalties ---
        # 1. Overlaps/Crossings
        overlap_score = self._calc_collision_penalties(holes)
        score += overlap_score
        
        # 2. Return to clubhouse (Hole 9 & 18) -- Handled in _build_course
        # 3. Bounds -- Handled in _build_course
        
        return (score,)

    def _build_course(self, individual) -> Tuple[Optional[List[Dict]], float]:
        """Constructs course from genome. Returns (holes_list, construction_penalty)."""
        holes = []
        construction_penalty = 0.0
        
        prev_green = self.clubhouse_pos
        w, h = self.config.width, self.config.height
        margin = self.config.routing.grid_margin
        
        pars = self.config.routing.par_distribution[:self.config.num_holes]
        
        idx = 0
        for hole_id in range(1, self.config.num_holes + 1):
            if idx + 2 >= len(individual): break

            # Extract genes
            # Use raw float values to derive parameters
            # Genes are [0, 1] usually (initialized by random), but mutation can push them out
            # So we wrap them or clamp them

            g_angle = individual[idx] % 1.0  # 0..1 -> 0..2pi
            g_dist = individual[idx + 1] % 1.0  # 0..1 -> min_link..max_link
            g_seed = individual[idx + 2]  # float -> int seed
            g_rotation = individual[idx + 3]  # 0..1 -> -0.5 to 0.5

            idx += 4
            
            # Return to start logic
            return_to_start = (hole_id == 9 or hole_id == 18)
            if hole_id == 10:
                prev_green = self.clubhouse_pos # Reset for back nine
            
            # --- Decode Parameters ---
            angle = g_angle * 2 * math.pi
            
            # Distance prev green -> tee
            min_link, max_link = 10, self.config.routing.tee_link_distance
            dist = min_link + g_dist * (max_link - min_link)
            
            tee_pos = (
                prev_green[0] + dist * math.cos(angle),
                prev_green[1] + dist * math.sin(angle)
            )

            # Generate Shape
            shape_rng = random.Random(int(g_seed * 10000))
            temp_gen = HoleGenerator(self.config)
            temp_gen.rng = shape_rng
            shape = temp_gen.generate_one(pars[hole_id - 1])  # Use correct par

            # Apply rotation to the hole (e.g., rotate the waypoints)
            # Use the rotation gene to rotate the hole orientation
            rot_angle = g_rotation * math.pi  # Convert to radians (0 to π)
            rotated_waypoints = self._rotate_waypoints(shape.waypoints, rot_angle)
            shape.waypoints = rotated_waypoints
            
            # Rotate/Translate Waypoints
            # We need a hole orientation. 
            # Let's say gene 0 (angle) also dictates the general direction of the hole?
            # Or we add a 4th gene for hole rotation?
            # Let's use the tee->tee angle for now, or just add 4th gene.
            # Actually, `angle` defined tee position relative to prev green.
            # We need another angle for the hole direction.
            # Let's say:
            # Gene 1: Angle from prev green to Tee
            # Gene 2: Distance from prev green to Tee
            # Gene 3: Hole Rotation (relative to Tee approach or absolute)
            # Gene 4: Shape Seed
            
            # Wait, I only allocated 3 genes. Let's use 3 for now.
            # Angle usually implies direction away from previous.
            # Let's try to align hole with the move from prev_green.
            # hole_dir = angle

            # Coordinate Transform
            abs_wps = self._transform(shape.waypoints, tee_pos, angle) # simple: hole goes in `angle` direction
            
            # --- Bounds Check ---
            # Soft penalty for gradient descent
            bounds_pen = self._calc_bounds_penalty(abs_wps, margin)
            construction_penalty += bounds_pen
            # Hard "strike" if significantly OOB (optional, keeping soft is better for flow)

            # --- Return to Clubhouse Check (Holes 9 & 18) ---
            if return_to_start:
                # Green should be close to clubhouse
                dist_to_ch = distance(abs_wps[-1], self.clubhouse_pos)
                target_dist = 25.0 # Aim to finish within 25 blocks
                if dist_to_ch > target_dist:
                    # Quadratic penalty for distance
                    construction_penalty += (dist_to_ch - target_dist) ** 2 * 500.0
            else:
                # --- Anti-Early-Return: non-9/18 holes should NOT be near clubhouse ---
                dist_to_ch = distance(abs_wps[-1], self.clubhouse_pos)
                min_dist_from_ch = 50.0  # Must be at least 50 blocks away from CH
                if dist_to_ch < min_dist_from_ch:
                    construction_penalty += (min_dist_from_ch - dist_to_ch) ** 2 * 200.0
            
            # Add to list (even if OOB, to allow evolution to pull it back)
            hole_data = {
                "id": hole_id,
                "par": shape.par,
                "shape": shape,
                "waypoints": abs_wps,
                "tee": tee_pos,
                "green": abs_wps[-1],
                "fairway_width": shape.fairway_width
            }
            holes.append(hole_data)
            
            prev_green = abs_wps[-1]

        # Additional Check: End near clubhouse for 9/18
        # We can calculate this penalty in evaluate() but might as well add here if critical
        
        if len(holes) < self.config.num_holes:
             construction_penalty += 999999 # Should not happen unless gene count mismatch
            
        return holes, construction_penalty

    def _calc_collision_penalties(self, holes: List[Dict]) -> float:
        """Calculates penalties for crossings and placements on other fairways."""
        penalty = 0.0
        segments = [] # (p1, p2, width, hole_id)
        
        # Collect all segments
        for h in holes:
            w = h["fairway_width"]
            wps = h["waypoints"]
            # Store segments with hole ID to avoid self-intersection checks if needed
            # (though normally we want to avoid self-intersection too, but adjacent segments touch)
            for i in range(len(wps)-1):
                segments.append((wps[i], wps[i+1], w, h["id"]))
                
        # 1. Segment-Segment Intersection (Crossing Fairways)
        # O(N^2) - N is small (~72)
        for i in range(len(segments)):
            p1a, p1b, w1, hid1 = segments[i]
            for j in range(i + 1, len(segments)):
                p2a, p2b, w2, hid2 = segments[j]
                
                # Skip adjacent segments of same hole (they touch at endpoints)
                if hid1 == hid2 and abs(j - i) == 1: continue
                # Skip if same segment (shouldn't happen with i+1)

                # Fast check
                if distance(p1a, p2a) > 200: continue 
                
                # Intersection Check
                if segments_intersect(p1a, p1b, p2a, p2b):
                    # STRICT Penalty for crossing
                    penalty += 500_000.0 
                    
                # Proximity Check (keep fairways apart)
                d = min(
                    point_to_segment_dist(p1a[0], p1a[1], p2a[0], p2a[1], p2b[0], p2b[1]),
                    point_to_segment_dist(p1b[0], p1b[1], p2a[0], p2a[1], p2b[0], p2b[1]),
                    point_to_segment_dist(p2a[0], p2a[1], p1a[0], p1a[1], p1b[0], p1b[1]),
                    point_to_segment_dist(p2b[0], p2b[1], p1a[0], p1a[1], p1b[0], p1b[1]),
                )
                
                safe_dist = (w1 + w2) / 2 + 5.0 # Buffer
                if d < safe_dist:
                    # Penalize entering the buffer zone
                    penalty += (safe_dist - d) ** 2 * 50.0

        # 2. Tee/Green Placement on Other Fairways
        # Check every Tee and Green against every segment of OTHER holes
        
        for h in holes:
            tee = h["tee"]
            green = h["green"]
            hid = h["id"]
            
            # Check against all segments
            for seg in segments:
                p1, p2, width, seg_hid = seg
                if seg_hid == hid: continue # Don't check against own hole components
                
                # Check Tee
                d_tee = point_to_segment_dist(tee[0], tee[1], p1[0], p1[1], p2[0], p2[1])
                safe_radius_tee = 5.0 # Tee buffer
                if d_tee < (width / 2 + safe_radius_tee):
                    penalty += 50_000.0 # High penalty for Tee on Fairway
                    
                # Check Green
                d_green = point_to_segment_dist(green[0], green[1], p1[0], p1[1], p2[0], p2[1])
                safe_radius_green = h["shape"].green_radius + 2.0
                if d_green < (width / 2 + safe_radius_green):
                    penalty += 50_000.0 # High penalty for Green on Fairway
            
        return penalty

    def _genome_to_course(self, individual) -> List[Dict]:
        """Converts the optimized genome to the final list of dicts."""
        holes, _ = self._build_course(individual)
        
            # Final formatting similar to placer.py export
        export_holes = []
        w, height = self.config.width, self.config.height
        margin = self.config.routing.grid_margin

        for hole in holes:
            abs_wps = hole["waypoints"]
            # Clamp waypoints to be strictly in bounds
            clamped_wps = []
            for x, y in abs_wps:
                cx = max(margin, min(x, w - margin))
                cy = max(margin, min(y, height - margin))
                clamped_wps.append((cx, cy))
            
            # Update Tee/Green based on clamped values
            hole["tee"] = clamped_wps[0]
            hole["green"] = clamped_wps[-1]
            tee = hole["tee"]
            green = hole["green"]
            
            shape = hole["shape"]
            
            # Get elevations (mocking or real if map provided)
            tee_elev = self._elevation_at(tee)
            green_elev = self._elevation_at(green)
            
            export_holes.append({
                "id": hole["id"],
                "par": hole["par"],
                "blocks": int(polyline_length(clamped_wps)),
                "tee": {"x": round(tee[0], 1), "y": round(tee[1], 1), "elevation": tee_elev},
                "green": {"x": round(green[0], 1), "y": round(green[1], 1), 
                          "radius": shape.green_radius, "elevation": green_elev},
                "waypoints": [{"x": round(p[0], 1), "y": round(p[1], 1)} for p in clamped_wps],
                "fairway_width": shape.fairway_width,
                "direction": direction_label(tee, green),
            })
            
        return export_holes

    def _transform(self, local_wps: list[tuple], tee_pos: tuple, angle: float) -> list[tuple]:
        """Rotates and translates waypoints."""
        cos_a = math.cos(angle)
        sin_a = math.sin(angle)
        result = []
        for lx, ly in local_wps:
            rx = lx * cos_a - ly * sin_a
            ry = lx * sin_a + ly * cos_a
            result.append((tee_pos[0] + rx, tee_pos[1] + ry))
        return result

    def _calc_bounds_penalty(self, abs_wps: list[tuple], margin: int) -> float:
        """Calculates soft penalty magnitude for OOB points."""
        w, h = self.config.width, self.config.height
        penalty = 0.0
        for x, y in abs_wps:
            dx = max(0, margin - x, x - (w - margin))
            dy = max(0, margin - y, y - (h - margin))
            if dx > 0 or dy > 0:
                # Quadratic penalty to discourage being far out
                # Base penalty high enough to dominate overlaps (50k)
                penalty += (dx**2 + dy**2) * 100.0 + 100_000.0
        return penalty

    def _in_bounds(self, abs_wps: list[tuple], margin: int) -> bool:
        """Boolean check for hard validity."""
        w, h = self.config.width, self.config.height
        for x, y in abs_wps:
            if x < margin or x > w - margin or y < margin or y > h - margin:
                return False
        return True

    def _elevation_at(self, pos: tuple) -> float:
        if self.heightmap is None: return 64.0
        x = max(0, min(int(pos[0]), self.heightmap.shape[1] - 1))
        y = max(0, min(int(pos[1]), self.heightmap.shape[0] - 1))
        return float(self.heightmap[y, x])

print("✅ ga.py finished successfully!")