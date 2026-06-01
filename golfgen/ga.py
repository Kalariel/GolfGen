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
        """Crée un individu pour un parcours de num_holes trous en deux nines distincts."""
        genes = []
        n = self.config.num_holes
        half = n // 2  # front nine / back nine

        for i in range(n):
            in_back_nine = i >= half

            if i == 0:
                # H1 : part depuis le clubhouse, angle presque nul
                angle_gene = 0.0 + self.rng.gauss(0, 0.001)
                dist_gene = 0.1 + self.rng.gauss(0, 0.001)
                dist_gene = max(0.08, min(0.12, dist_gene))
                rotation_gene = self.rng.gauss(0, 0.01)
                rotation_gene = max(-0.05, min(0.05, rotation_gene))

            elif i == half:
                # H(half+1) : début du back nine — secteur opposé au front nine
                angle_gene = 0.5 + self.rng.gauss(0, 0.02 + noise * 0.01)
                angle_gene = angle_gene % 1.0
                dist_gene = 0.15 + self.rng.gauss(0, 0.03)
                dist_gene = max(0.1, min(0.25, dist_gene))
                rotation_gene = self.rng.gauss(0, 0.02)
                rotation_gene = max(-0.1, min(0.1, rotation_gene))

            else:
                # Progression angulaire dans chaque nine (0..0.5 pour le front, 0.5..1 pour le back)
                progress = (i % half) / half
                base = (0.5 + progress * 0.5) if in_back_nine else (progress * 0.5)
                angle_gene = base + self.rng.gauss(0, 0.03 + noise * 0.02)
                angle_gene = angle_gene % 1.0
                dist_gene = 0.25 + self.rng.gauss(0, 0.04)
                dist_gene = max(0.15, min(0.35, dist_gene))
                rotation_gene = self.rng.gauss(0, 0.03)
                rotation_gene = max(-0.15, min(0.15, rotation_gene))

            shape_gene = self.rng.random()
            genes.extend([angle_gene, dist_gene, shape_gene, rotation_gene])

        return creator.Individual(array.array('d', genes))

    def tee_green_distance_score(self, holes):
        """Pénalise les grandes distances entre green(N) et tee(N+1)."""
        score = 0.0
        max_allowed_dist = {
            3: 20.0,  # Par 3
            4: 40.0,  # Par 4
            5: 60.0  # Par 5
        }
        for i in range(len(holes) - 1):
            # Handle both tuple and dict formats for green and tee
            if isinstance(holes[i]["green"], (tuple, list)):
                green = (holes[i]["green"][0], holes[i]["green"][1])
            else:
                green = (holes[i]["green"]["x"], holes[i]["green"]["y"])
                
            if isinstance(holes[i + 1]["tee"], (tuple, list)):
                next_tee = (holes[i + 1]["tee"][0], holes[i + 1]["tee"][1])
            else:
                next_tee = (holes[i + 1]["tee"]["x"], holes[i + 1]["tee"]["y"])
            
            dist = math.sqrt((green[0] - next_tee[0]) ** 2 + (green[1] - next_tee[1]) ** 2)
            par = holes[i + 1]["par"]
            if dist > max_allowed_dist.get(par, 50.0):
                score += (dist - max_allowed_dist.get(par, 50.0)) ** 2 * 2.0
        return score

    def compacity_score(self, holes):
        """Pénalise les trous éloignés du centroïde (version corrigée)."""
        centroid = self.calculate_centroid(holes)
        score = 0.0
        max_radius = 40.0  # Rayon maximal autorisé
        for hole in holes:
            # Handle both tuple and dict formats for tee and green
            if isinstance(hole["tee"], (tuple, list)):
                tee_x, tee_y = hole["tee"][0], hole["tee"][1]
                green_x, green_y = hole["green"][0], hole["green"][1]
            else:
                tee_x, tee_y = hole["tee"]["x"], hole["tee"]["y"]
                green_x, green_y = hole["green"]["x"], hole["green"]["y"]

            tee_dist = math.sqrt((tee_x - centroid[0]) ** 2 + (tee_y - centroid[1]) ** 2)
            green_dist = math.sqrt((green_x - centroid[0]) ** 2 + (green_y - centroid[1]) ** 2)
            if tee_dist > max_radius:
                score += (tee_dist - max_radius) ** 2 * 1.0
            if green_dist > max_radius:
                score += (green_dist - max_radius) ** 2 * 1.0
        return score * 2.0

    def calculate_centroid(self, holes):
        """Calcule le centroïde des trous (version universelle)."""
        tees = []
        greens = []
        for h in holes:
            # Cas 1: h["tee"] est un tuple (x, y)
            if isinstance(h["tee"], (tuple, list)):
                tees.append((h["tee"][0], h["tee"][1]))
                greens.append((h["green"][0], h["green"][1]))
            # Cas 2: h["tee"] est un dict {"x": ..., "y": ...}
            else:
                tees.append((h["tee"]["x"], h["tee"]["y"]))
                greens.append((h["green"]["x"], h["green"]["y"]))

        all_points = tees + greens
        if not all_points:  # Évite la division par zéro
            return 0, 0
        centroid_x = sum(p[0] for p in all_points) / len(all_points)
        centroid_y = sum(p[1] for p in all_points) / len(all_points)
        return centroid_x, centroid_y

    def _is_valid_individual(self, individual) -> bool:
        """Check if an individual produces a valid course (no out-of-bounds, no collisions)."""
        holes, penalties = self._build_course(individual)
        if holes is None:
            return False
        # Check if all waypoints are within bounds (hard check)
        margin = self.config.routing.grid_margin
        w, h = self.config.width, self.config.height
        for hole in holes:
            for wp in hole["waypoints"]:
                if wp[0] < margin or wp[0] > w - margin or wp[1] < margin or wp[1] > h - margin:
                    return False
        return True

    def run(self) -> List[Dict]:
        """Runs the evolutionary algorithm and returns the best course layout."""
        pop_size = 400
        n_gen = 250
        
        # Create population: half seeded, half with noise
        pop = []
        for i in range(pop_size):
            noise = (i / pop_size) * 0.5  # Gradually increasing noise
            ind = self._create_seeded_individual(noise)
            pop.append(ind)
        
        # Ensure at least one valid individual in the population
        valid_found = False
        for ind in pop:
            if self._is_valid_individual(ind):
                valid_found = True
                break
        
        if not valid_found:
            print("⚠️  No valid individual found in initial population. Regenerating first individual...")
            # Regenerate the first individual with minimal noise to ensure validity
            pop[0] = self._create_seeded_individual(noise=0.0)
        
        stats = tools.Statistics(lambda ind: ind.fitness.values)
        stats.register("min", np.min)
        stats.register("avg", np.mean)
        
        # Elitism
        hall_of_fame = tools.HallOfFame(1)
        
        print(f"Starting Evolution (Pop: {pop_size}, Gen: {n_gen})")
        
        # Track best fitness seen
        best_fitness_so_far = float('inf')
        generations_without_improvement = 0

        for gen in range(n_gen):
            # Evaluate population
            # Dans la boucle for gen in range(n_gen):
            pop, logbook = algorithms.eaSimple(
                pop, self.toolbox, cxpb=0.5, mutpb=0.2,
                ngen=1, stats=stats, halloffame=hall_of_fame, verbose=False
            )

            best_ind = tools.selBest(pop, k=1)[0]
            worst_ind = tools.selWorst(pop, k=1)[0]
            avg_score = sum(ind.fitness.values[0] for ind in pop) / len(pop)
            print(
                f"Gen {gen}: "
                f"Best={best_ind.fitness.values[0]:.1f}, "
                f"Worst={worst_ind.fitness.values[0]:.1f}, "
                f"Avg={avg_score:.1f}"
            )

            # Export debug files less frequently to avoid clutter (every 50 generations instead of 10)
            if gen % 50 == 0:
                best_holes = self._genome_to_course(best_ind)
                output_path = f"debug_gen_{gen}.json"  # Fichier JSON pour ton viewer
                with open(output_path, "w") as f:
                    import json
                    json.dump({
                        "holes": best_holes,
                        "centroid": self.calculate_centroid(best_holes),
                        "generation": gen,
                        "score": best_ind.fitness.values[0]
                    }, f, indent=2)
                print(f"[Gen {gen}] Exporté vers {output_path} (score: {best_ind.fitness.values[0]:.1f})")

            # Get best individual fitness
            best_fitness_this_gen = min(ind.fitness.values[0] / 10000 for ind in pop)
            # Check if fitness improved
            if best_fitness_this_gen < best_fitness_so_far:
                best_fitness_so_far = best_fitness_this_gen
                generations_without_improvement = 0
            else:
                generations_without_improvement += 1

        best_ind = hall_of_fame[0]
        print(f"Best Fitness: {best_ind.fitness.values[0]:.2f}")

        # Convert best individual to course format
        best_holes = self._genome_to_course(best_ind)

        # Phase de post-optimisation pour affiner la disposition
        print("🔧 Starting post-optimization phase...")
        optimized_holes = self.post_optimize_layout(best_holes)
        print("✅ Post-optimization completed!")

        return {
            "original": best_holes,
            "optimized": optimized_holes
        }

    def evaluate(self, individual):
        """Fitness function: calculates penalties for the entire course."""
        holes, penalties = self._build_course(individual)

        if holes is None:
            return (1e9,)

        # --- Calcul des pénalités individuelles ---
        overlap = self._calc_collision_penalties(holes)
        compacity = self.compacity_score(holes)
        tee_green = self.tee_green_distance_score(holes)
        consecutive = self.consecutive_holes_score(holes)
        natural_layout = self.natural_layout_score(holes)

        # --- Calcul des pénalités individuelles ---
        fairway_concentration = self.fairway_concentration_score(holes)

        par_dist = self._par_distribution_score(holes)
        hole_length = self._hole_length_score(holes)
        direction_variety = self._direction_variety_score(holes)
        return_ch = self._return_to_clubhouse_score(holes)
        ch_excl = self._clubhouse_exclusion_penalty(holes)

        # --- Score total ---
        total_score = (
                penalties +
                overlap * 1.0 +
                compacity * 2.0 +
                tee_green * 1.5 +
                consecutive * 0.5 +
                natural_layout * 1.2 +
                fairway_concentration * 3.0 +
                par_dist * 2.0 +
                hole_length * 1.5 +
                direction_variety * 1.0 +
                return_ch * 2.0 +
                ch_excl * 1.0
        )

        # --- DEBUG: Affichage des composantes (1% des évaluations) ---
        if random.random() < 0.01:
            print(
                f"[DEBUG] Score breakdown: "
                f"Total={total_score:.1f}, "
                f"Overlap={overlap:.1f}, "
                f"Compacity={compacity:.1f}, "
                f"TeeGreen={tee_green:.1f}, "
                f"Consecutive={consecutive:.1f}, "
                f"Natural={natural_layout:.1f}, "
                f"Conc={fairway_concentration:.1f}, "
                f"Par={par_dist:.1f}, "
                f"Len={hole_length:.1f}, "
                f"Dir={direction_variety:.1f}, "
                f"RetCH={return_ch:.1f}, "
                f"ChExcl={ch_excl:.1f}"
            )

        return (total_score,)

    def consecutive_holes_score(self, holes):
        """Pénalise les grandes distances entre trous consécutifs."""
        score = 0.0
        for i in range(len(holes) - 1):
            green = (holes[i]["green"][0], holes[i]["green"][1])
            next_tee = (holes[i + 1]["tee"][0], holes[i + 1]["tee"][1])
            dist = math.sqrt((green[0] - next_tee[0]) ** 2 + (green[1] - next_tee[1]) ** 2)
            if dist > 60:  # Seuil réduit pour compacité
                score += (dist - 60) ** 2 * 0.5
        return score

    def fairway_concentration_score(self, holes):
        """
        Encourage une concentration élevée des fairways pour maximiser l'utilisation de l'espace.
        Plus les fairways sont proches (sans se croiser), mieux c'est.
        """
        if len(holes) < 2:
            return 0.0

        score = 0.0
        all_segments = []

        # Collecter tous les segments de fairway avec leur largeur
        for hole in holes:
            waypoints = hole["waypoints"]
            width = hole["fairway_width"]
            for i in range(len(waypoints) - 1):
                p1 = waypoints[i]
                p2 = waypoints[i+1]
                if isinstance(p1, dict):
                    p1 = (p1["x"], p1["y"])
                    p2 = (p2["x"], p2["y"])
                all_segments.append((p1, p2, width))

        if not all_segments:
            return 0.0

        # 1. Calculer la surface totale couverte par les fairways
        total_fairway_area = 0.0
        for (p1, p2, width) in all_segments:
            segment_length = math.sqrt((p2[0]-p1[0])**2 + (p2[1]-p1[1])**2)
            total_fairway_area += segment_length * width

        # 2. Calculer la surface du bounding box
        min_x = min(min(p[0][0], p[1][0]) for p in all_segments)
        max_x = max(max(p[0][0], p[1][0]) for p in all_segments)
        min_y = min(min(p[0][1], p[1][1]) for p in all_segments)
        max_y = max(max(p[0][1], p[1][1]) for p in all_segments)

        bbox_area = (max_x - min_x) * (max_y - min_y)

        # Éviter la division par zéro
        if bbox_area < 10:
            bbox_area = 10

        # Ratio de couverture (0-1)
        coverage_ratio = total_fairway_area / bbox_area

        # 3. Calculer la proximité moyenne entre segments
        proximity_score = 0.0
        proximity_count = 0

        for i in range(len(all_segments)):
            p1a, p1b, w1 = all_segments[i]
            for j in range(i+1, len(all_segments)):
                p2a, p2b, w2 = all_segments[j]

                # Calculer la distance minimale entre les deux segments
                min_dist = min(
                    point_to_segment_dist(p1a[0], p1a[1], p2a[0], p2a[1], p2b[0], p2b[1]),
                    point_to_segment_dist(p1b[0], p1b[1], p2a[0], p2a[1], p2b[0], p2b[1]),
                    point_to_segment_dist(p2a[0], p2a[1], p1a[0], p1a[1], p1b[0], p1b[1]),
                    point_to_segment_dist(p2b[0], p2b[1], p1a[0], p1a[1], p1b[0], p1b[1])
                )

                # Distance normalisée par la largeur moyenne
                avg_width = (w1 + w2) / 2
                normalized_dist = min_dist / avg_width

                # Si les segments sont très proches (moins de 2.5x la largeur moyenne)
                if normalized_dist < 2.5:  # Seuil réduit pour plus de proximité
                    proximity_score += (2.5 - normalized_dist) * 1.5  # Bonus augmenté
                    proximity_count += 1
                elif normalized_dist < 3.5:  # Zone tampon
                    proximity_score += (3.5 - normalized_dist) * 0.5  # Bonus réduit
                    proximity_count += 1

        # Score de proximité moyen
        if proximity_count > 0:
            avg_proximity = proximity_score / proximity_count
        else:
            avg_proximity = 0.0

        # 4. Calculer le score final de concentration
        # Score basé sur la couverture (0-1, plus élevé = mieux)
        coverage_score = coverage_ratio * 100.0

        # Score basé sur la proximité (0-2.5, plus élevé = mieux)
        proximity_score = avg_proximity * 30.0  # Multiplicateur augmenté

        # Score combiné - nous voulons maximiser la concentration
        concentration_score = coverage_score + proximity_score

        # Inverser pour en faire une pénalité (plus la concentration est faible, plus la pénalité est élevée)
        # Avec les nouvelles contraintes renforcées, une bonne concentration devrait être > 120
        if concentration_score < 90.0:
            penalty = (90.0 - concentration_score) * 4.0  # Pénalité plus forte
        elif concentration_score < 110.0:
            penalty = (110.0 - concentration_score) * 2.0  # Pénalité modérée
        elif concentration_score < 130.0:
            penalty = (130.0 - concentration_score) * 0.5  # Pénalité légère
        else:
            penalty = 0.0  # Pas de pénalité pour les excellentes concentrations

        return penalty

    def natural_layout_score(self, holes):
        """Encourage une disposition en boucle plutôt qu'en ligne droite."""
        score = 0.0
        
        if len(holes) < 3:
            return 0.0
            
        # Calculer le centroïde
        centroid = self.calculate_centroid(holes)
        
        # Calculer les angles de chaque trou par rapport au centroïde
        angles = []
        for hole in holes:
            # Get tee position (handle both formats)
            if isinstance(hole["tee"], (tuple, list)):
                tee_x, tee_y = hole["tee"][0], hole["tee"][1]
            else:
                tee_x, tee_y = hole["tee"]["x"], hole["tee"]["y"]
            
            # Calculate angle from centroid
            dx = tee_x - centroid[0]
            dy = tee_y - centroid[1]
            angle = math.atan2(dy, dx)
            angles.append(angle)
        
        # Encourager une progression angulaire régulière (comme une horloge)
        for i in range(len(angles) - 1):
            angle_diff = abs(angles[i+1] - angles[i])
            # Normaliser la différence d'angle (chemin le plus court)
            angle_diff = min(angle_diff, 2*math.pi - angle_diff)
            ideal_angle_step = (2*math.pi) / len(holes)  # Espacement idéal
            score += abs(angle_diff - ideal_angle_step) * 10.0
        
        # Pénaliser si tous les trous sont dans un demi-cercle (disposition trop concentrée)
        angle_range = max(angles) - min(angles)
        angle_range = min(angle_range, 2*math.pi - angle_range)
        if angle_range < math.pi:  # Tous dans un demi-cercle
            score += (math.pi - angle_range) * 50.0
        
        # Encourager le dernier trou à être proche du premier (pour revenir au clubhouse)
        if len(holes) >= 2:
            # Angle entre le premier et le dernier trou
            angle_diff = abs(angles[-1] - angles[0])
            angle_diff = min(angle_diff, 2*math.pi - angle_diff)
            
            # Idéalement, le dernier trou devrait être à environ 30-60° du premier
            # pour permettre un retour naturel au clubhouse
            ideal_return_angle = math.pi / 3  # 60 degrés
            if angle_diff > ideal_return_angle:
                score += (angle_diff - ideal_return_angle) * 15.0
        
        return score

    def _par_distribution_score(self, holes: List[Dict]) -> float:
        """Pénalise si la distribution des pars s'écarte de la cible (4/10/4 pour 18 trous, scalé)."""
        n = len(holes)
        target = {3: round(n * 4 / 18), 4: round(n * 10 / 18), 5: round(n * 4 / 18)}
        counts = {3: 0, 4: 0, 5: 0}
        for hole in holes:
            par = hole["par"]
            if par in counts:
                counts[par] += 1
        penalty = 0.0
        for par, t in target.items():
            diff = counts[par] - t
            if diff < 0:
                penalty += (-diff) * 1000.0
            else:
                penalty += diff * 500.0
        return penalty

    def _hole_length_score(self, holes: List[Dict]) -> float:
        """Pénalise si la longueur des trous ne correspond pas à leur par."""
        target_ranges = {3: (25, 75), 4: (83, 133), 5: (150, 200)}
        penalty = 0.0
        for hole in holes:
            par = hole["par"]
            length = polyline_length(hole["waypoints"])
            lo, hi = target_ranges.get(par, (0, float("inf")))
            if length < lo:
                penalty += (lo - length) ** 2 * 10.0
            elif length > hi:
                penalty += (length - hi) ** 2 * 5.0
        return penalty

    def _direction_variety_score(self, holes: List[Dict]) -> float:
        """Pénalise si les trous pointent tous dans la même direction (variance circulaire faible)."""
        if len(holes) < 3:
            return 0.0
        angles = []
        for hole in holes:
            tee = hole["tee"]
            green = hole["green"]
            tx, ty = (tee[0], tee[1]) if isinstance(tee, (tuple, list)) else (tee["x"], tee["y"])
            gx, gy = (green[0], green[1]) if isinstance(green, (tuple, list)) else (green["x"], green["y"])
            angles.append(math.atan2(gy - ty, gx - tx))
        n = len(angles)
        R = abs(sum(complex(math.cos(a), math.sin(a)) for a in angles)) / n
        circular_variance = 1.0 - R  # 0 = tous identiques, 1 = max diversité
        threshold = 0.5
        if circular_variance < threshold:
            return (threshold - circular_variance) * 2000.0
        return 0.0

    def _return_to_clubhouse_score(self, holes: List[Dict]) -> float:
        """Pénalise si le green du dernier trou (et du 9e pour 18 trous) est trop loin/près du clubhouse."""
        if not holes:
            return 0.0

        def penalty_for_green(green):
            pos = (green[0], green[1]) if isinstance(green, (tuple, list)) else (green["x"], green["y"])
            dist = distance(pos, self.clubhouse_pos)
            if dist < 15.0:
                return (15.0 - dist) ** 2 * 200.0
            if dist > 50.0:
                return (dist - 50.0) ** 2 * 100.0
            return 0.0

        penalty = penalty_for_green(holes[-1]["green"])

        # Pour 18 trous : le green du trou 9 doit aussi retourner près du clubhouse
        if len(holes) >= 18:
            h9 = next((h for h in holes if h["id"] == 9), None)
            if h9:
                penalty += penalty_for_green(h9["green"])

        return penalty

    def _clubhouse_exclusion_penalty(self, holes: List[Dict]) -> float:
        """
        Zone d'exclusion autour du clubhouse : rectangle 30×20 blocs (hard) + buffer 5 blocs (soft).
        - Fairway segments : aucun ne doit traverser ni s'approcher de la zone.
        - Tees/greens : idem, sauf trou 1 (tee) et dernier trou (green) qui doivent rester proches.
        """
        cx, cy = self.clubhouse_pos
        hw, hh = 15.0, 10.0  # demi-extents du rectangle 30×20
        buffer = 5.0

        def dist_to_box(px, py) -> float:
            dx = max(abs(px - cx) - hw, 0.0)
            dy = max(abs(py - cy) - hh, 0.0)
            return math.sqrt(dx * dx + dy * dy)

        def segment_crosses_box(p1, p2) -> bool:
            if dist_to_box(p1[0], p1[1]) < 0.5 or dist_to_box(p2[0], p2[1]) < 0.5:
                return True
            bx1, by1, bx2, by2 = cx - hw, cy - hh, cx + hw, cy + hh
            edges = [
                ((bx1, by1), (bx2, by1)),
                ((bx2, by1), (bx2, by2)),
                ((bx2, by2), (bx1, by2)),
                ((bx1, by2), (bx1, by1)),
            ]
            return any(segments_intersect(p1, p2, ea, eb) for ea, eb in edges)

        def pos_xy(p):
            return (p[0], p[1]) if isinstance(p, (tuple, list)) else (p["x"], p["y"])

        penalty = 0.0
        n = len(holes)
        last_id = max(h["id"] for h in holes)
        # Greens exemptés : dernier trou + trou 9 (retour mi-parcours pour 18 trous)
        exempt_greens = {last_id}
        if n >= 18:
            exempt_greens.add(9)

        for hole in holes:
            hid = hole["id"]
            tx, ty = pos_xy(hole["tee"])
            gx, gy = pos_xy(hole["green"])

            # Tee : exempt trou 1
            if hid != 1:
                d = dist_to_box(tx, ty)
                if d < 0.5:
                    penalty += 500_000.0
                elif d < buffer:
                    penalty += (buffer - d) ** 2 * 500.0

            # Green : exempt dernier trou et trou 9 (mi-parcours)
            if hid not in exempt_greens:
                d = dist_to_box(gx, gy)
                if d < 0.5:
                    penalty += 500_000.0
                elif d < buffer:
                    penalty += (buffer - d) ** 2 * 500.0

            # Segments de fairway : tous les trous
            wps = hole["waypoints"]
            for i in range(len(wps) - 1):
                if segment_crosses_box(wps[i], wps[i + 1]):
                    penalty += 500_000.0

        return penalty

    def evaluate_holes(self, holes: List[Dict]) -> dict:
        """Évalue directement une liste de trous sans passer par le génome. Retourne un breakdown."""
        overlap = self._calc_collision_penalties(holes)
        compacity = self.compacity_score(holes)
        tee_green = self.tee_green_distance_score(holes)
        consecutive = self.consecutive_holes_score(holes)
        natural_layout = self.natural_layout_score(holes)
        fairway_concentration = self.fairway_concentration_score(holes)
        par_dist = self._par_distribution_score(holes)
        hole_length = self._hole_length_score(holes)
        direction_variety = self._direction_variety_score(holes)
        return_ch = self._return_to_clubhouse_score(holes)
        ch_excl = self._clubhouse_exclusion_penalty(holes)

        total = (
            overlap * 1.0
            + compacity * 2.0
            + tee_green * 1.5
            + consecutive * 0.5
            + natural_layout * 1.2
            + fairway_concentration * 3.0
            + par_dist * 2.0
            + hole_length * 1.5
            + direction_variety * 1.0
            + return_ch * 2.0
            + ch_excl * 1.0
        )
        return {
            "overlap": overlap,
            "compacity": compacity,
            "tee_green": tee_green,
            "consecutive": consecutive,
            "natural_layout": natural_layout,
            "fairway_concentration": fairway_concentration,
            "par_distribution": par_dist,
            "hole_length": hole_length,
            "direction_variety": direction_variety,
            "return_to_clubhouse": return_ch,
            "clubhouse_exclusion": ch_excl,
            "total": total,
        }

    def _calculate_dynamic_centroid(self, holes):
        """Calcule un centroïde dynamique basé sur les trous déjà placés."""
        if not holes:
            return self.clubhouse_pos

        # Calculer le centre actuel
        points = []
        for hole in holes:
            if isinstance(hole["tee"], (tuple, list)):
                points.append(hole["tee"])
                points.append(hole["green"])
            else:
                points.append((hole["tee"]["x"], hole["tee"]["y"]))
                points.append((hole["green"]["x"], hole["green"]["y"]))

        if not points:
            return self.clubhouse_pos

        avg_x = sum(p[0] for p in points) / len(points)
        avg_y = sum(p[1] for p in points) / len(points)

        # Pondérer vers le clubhouse pour garder une référence fixe
        clubhouse_weight = 0.3
        centroid_x = avg_x * (1 - clubhouse_weight) + self.clubhouse_pos[0] * clubhouse_weight
        centroid_y = avg_y * (1 - clubhouse_weight) + self.clubhouse_pos[1] * clubhouse_weight

        return (centroid_x, centroid_y)

    def _build_course(self, individual) -> Tuple[Optional[List[Dict]], float]:
        holes = []
        construction_penalty = 0.0
        w, h = self.config.width, self.config.height
        margin = self.config.routing.grid_margin
        n = self.config.num_holes
        pars = self.config.routing.par_distribution[:n]

        idx = 0
        for hole_id in range(1, n + 1):
            if idx + 3 >= len(individual): break  # Sécurité

            # Extraction des gènes
            g_angle = individual[idx] % 1.0
            g_dist = individual[idx + 1] % 1.0
            g_seed = individual[idx + 2]
            g_rotation = individual[idx + 3]
            idx += 4

            # Retour au clubhouse pour le 9ème trou
            return_to_start = (hole_id == 9)

            # --- Algorithme hybride : équilibre entre continuité et compacité ---
            # Calculer un centroïde dynamique basé sur les trous déjà placés
            center_point = self._calculate_dynamic_centroid(holes)

            # --- Décodage des paramètres pour placement hybride ---
            angle = g_angle * 2 * math.pi

            if hole_id == 1:
                # Premier trou : placement court depuis le clubhouse
                min_dist, max_dist = 8, 25  # Distance courte pour compacité
                dist = min_dist + g_dist * (max_dist - min_dist)
                
                # Position du tee depuis le clubhouse
                tee_pos = (
                    self.clubhouse_pos[0] + dist * math.cos(angle),
                    self.clubhouse_pos[1] + dist * math.sin(angle)
                )
                
                # Vérifier la distance au clubhouse
                dist_to_ch = distance(tee_pos, self.clubhouse_pos)
                if dist_to_ch > 25.0:
                    construction_penalty += (dist_to_ch - 25.0) * 10.0
                
                # Direction du trou : s'éloigner du clubhouse
                hole_direction = angle + math.pi
                
            else:
                # Trous suivants : approche hybride avec proximité renforcée entre G(N) et T(N+1)
                # 1. Calculer une position basée sur la continuité (depuis le green précédent)
                # Utiliser des distances plus courtes pour rapprocher G(N) et T(N+1)
                min_link, max_link = 10, 25  # Distance réduite depuis le green précédent
                link_dist = min_link + g_dist * (max_link - min_link)
                
                continuity_pos = (
                    prev_green[0] + link_dist * math.cos(angle),
                    prev_green[1] + link_dist * math.sin(angle)
                )
                
                # 2. Calculer une position basée sur l'attraction vers le centre
                # Garder une attraction modérée vers le centre pour la compacité globale
                min_radius, max_radius = 18, 35  # Distance depuis le centroïde
                radius = min_radius + (1.0 - g_dist) * (max_radius - min_radius)  # Inverser g_dist
                
                attraction_pos = (
                    center_point[0] + radius * math.cos(angle),
                    center_point[1] + radius * math.sin(angle)
                )
                
                # 3. Combiner les deux approches avec plus de poids sur la continuité
                blend_factor = 0.85  # Plus de poids sur la continuité pour rapprocher G(N) et T(N+1)
                tee_pos = (
                    continuity_pos[0] * blend_factor + attraction_pos[0] * (1 - blend_factor),
                    continuity_pos[1] * blend_factor + attraction_pos[1] * (1 - blend_factor)
                )
                
                # 4. Ajouter une variation latérale réduite pour éviter l'alignement parfait
                # mais sans trop éloigner les trous
                variation = g_rotation * 5.0  # Variation réduite: -2.5 à +2.5 unités
                tee_pos = (
                    tee_pos[0] + math.cos(angle + math.pi/2) * variation,
                    tee_pos[1] + math.sin(angle + math.pi/2) * variation
                )
                
                # 5. Direction du trou : principalement continuer dans la direction actuelle
                # avec très peu d'attraction radiale pour garder la continuité
                continuity_direction = angle
                radial_direction = math.atan2(tee_pos[1] - center_point[1], tee_pos[0] - center_point[0])
                hole_direction = continuity_direction * 0.95 + radial_direction * 0.05  # Presque toute continuité

            # Génération de la forme du trou
            # Utiliser self.rng pour garantir la reproductibilité
            temp_gen = HoleGenerator(self.config)
            temp_gen.rng = self.rng
            shape = temp_gen.generate_one(pars[hole_id - 1])

            # Rotation des waypoints
            rot_angle = g_rotation * math.pi  # -0.1π à 0.1π
            rotated_waypoints = self._rotate_waypoints(shape.waypoints, rot_angle)
            shape.waypoints = rotated_waypoints

            # Transformation des waypoints en coordonnées absolues
            # Utiliser la direction radiale plutôt que l'angle depuis le green précédent
            abs_wps = self._transform(shape.waypoints, tee_pos, hole_direction)

            # Clamp tee_pos and abs_wps to stay within bounds (soft clamping to avoid hard failures)
            tee_pos = (
                max(margin, min(tee_pos[0], w - margin)),
                max(margin, min(tee_pos[1], h - margin))
            )
            clamped_wps = []
            for wp in abs_wps:
                clamped_wps.append((
                    max(margin, min(wp[0], w - margin)),
                    max(margin, min(wp[1], h - margin))
                ))
            abs_wps = clamped_wps

            # Vérification des limites (pénalité résiduelle si trop proche des bords)
            bounds_pen = self._calc_bounds_penalty(abs_wps, margin)
            construction_penalty += bounds_pen

            # Ajout du trou à la liste
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
                shape = h.get("shape")
                safe_radius_green = (shape.green_radius if shape else self.config.routing.green_radius_max) + 2.0
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
            
            # Convert tee and green to dicts if they are tuples
            tee = hole["tee"]
            green = hole["green"]
            if isinstance(tee, (tuple, list)):
                tee = {"x": tee[0], "y": tee[1]}
            if isinstance(green, (tuple, list)):
                green = {"x": green[0], "y": green[1]}
            
            shape = hole["shape"]
            
            # Get elevations (mocking or real if map provided)
            tee_elev = self._elevation_at((tee["x"], tee["y"]))
            green_elev = self._elevation_at((green["x"], green["y"]))
            
            export_holes.append({
                "id": hole["id"],
                "par": hole["par"],
                "blocks": int(polyline_length(clamped_wps)),
                "tee": {"x": round(tee["x"], 1), "y": round(tee["y"], 1), "elevation": tee_elev},
                "green": {"x": round(green["x"], 1), "y": round(green["y"], 1), 
                          "radius": shape.green_radius, "elevation": green_elev},
                "waypoints": [{"x": round(p[0], 1), "y": round(p[1], 1)} for p in clamped_wps],
                "fairway_width": shape.fairway_width,
                "direction": direction_label((tee["x"], tee["y"]), (green["x"], green["y"])),
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

    def post_optimize_layout(self, holes):
        """
        Phase de post-optimisation pour ajuster les positions des tees et greens
        après l'exécution du GA. Améliore la continuité et la compacité locale.
        """
        if not holes or len(holes) < 2:
            return holes

        # Stocker les positions originales AVANT toute modification
        original_positions = []
        for hole in holes:
            original_tee = hole["tee"]
            original_green = hole["green"]
            
            # Convertir en tuples si ce sont des dicts
            if isinstance(original_tee, dict):
                orig_tee_pos = (original_tee["x"], original_tee["y"])
            else:
                orig_tee_pos = (original_tee[0], original_tee[1])
                
            if isinstance(original_green, dict):
                orig_green_pos = (original_green["x"], original_green["y"])
            else:
                orig_green_pos = (original_green[0], original_green[1])
                
            original_positions.append({
                "tee": orig_tee_pos,
                "green": orig_green_pos
            })

        # Convertir en format mutable si nécessaire
        optimized_holes = [hole.copy() for hole in holes]

        # Paramètres d'optimisation
        max_iterations = 30
        learning_rate = 0.15
        proximity_target = 18.0  # Distance cible entre G(N) et T(N+1)
        compacity_target = 32.0   # Distance cible moyenne au centroïde
        max_displacement = 10.0   # Distance maximale de déplacement par rapport à la position originale

        def limit_displacement(new_pos, original_pos, max_dist):
            """
            Limite le déplacement d'un point à une distance maximale par rapport à sa position originale.
            """
            orig_x, orig_y = original_pos
            new_x, new_y = new_pos
            
            # Calculer la distance actuelle par rapport à l'original
            current_dist = math.sqrt((new_x - orig_x)**2 + (new_y - orig_y)**2)
            
            # Si la distance dépasse le maximum autorisé, limiter le déplacement
            if current_dist > max_dist:
                # Calculer le vecteur de l'original vers la nouvelle position
                dx = new_x - orig_x
                dy = new_y - orig_y
                
                # Normaliser et appliquer la distance maximale
                scale = max_dist / current_dist
                limited_x = orig_x + dx * scale
                limited_y = orig_y + dy * scale
                
                return (limited_x, limited_y)
            
            return (new_x, new_y)

        # Debug: vérifier si les positions originales sont différentes des positions optimisées
        print(f"📊 Post-optimization: Storing {len(original_positions)} original positions")
        
        for iteration in range(max_iterations):
            # Calculer le centroïde actuel
            centroid = self.calculate_centroid(optimized_holes)

            # Phase 1: Optimiser la continuité (G(N) → T(N+1))
            for i in range(len(optimized_holes) - 1):
                green = optimized_holes[i]["green"]
                next_tee = optimized_holes[i+1]["tee"]

                # Convertir en tuples si ce sont des dicts
                if isinstance(green, dict):
                    gx, gy = green["x"], green["y"]
                    tx, ty = next_tee["x"], next_tee["y"]
                else:
                    gx, gy = green[0], green[1]
                    tx, ty = next_tee[0], next_tee[1]

                # Calculer la distance actuelle
                current_dist = math.sqrt((tx - gx)**2 + (ty - gy)**2)

                # Si trop éloignés, rapprocher le tee suivant
                if current_dist > proximity_target:
                    # Calculer le vecteur de déplacement
                    dx = gx - tx
                    dy = gy - ty
                    dist_to_reduce = current_dist - proximity_target

                    # Déplacer le tee vers le green (avec learning rate)
                    move_x = dx * (dist_to_reduce / current_dist) * learning_rate
                    move_y = dy * (dist_to_reduce / current_dist) * learning_rate

                    # Appliquer le déplacement
                    new_tee_x = tx + move_x
                    new_tee_y = ty + move_y

                    # Limiter le déplacement par rapport à la position originale
                    original_tee_pos = original_positions[i+1]["tee"]
                    limited_tee_x, limited_tee_y = limit_displacement(
                        (new_tee_x, new_tee_y), original_tee_pos, max_displacement
                    )

                    # Mettre à jour la position du tee
                    if isinstance(next_tee, dict):
                        optimized_holes[i+1]["tee"]["x"] = limited_tee_x
                        optimized_holes[i+1]["tee"]["y"] = limited_tee_y
                    else:
                        optimized_holes[i+1]["tee"] = (limited_tee_x, limited_tee_y)

                    # Also adjust the first waypoint to maintain fairway shape
                    if optimized_holes[i+1]["waypoints"]:
                        if isinstance(optimized_holes[i+1]["waypoints"][0], dict):
                            optimized_holes[i+1]["waypoints"][0]["x"] = limited_tee_x
                            optimized_holes[i+1]["waypoints"][0]["y"] = limited_tee_y
                        else:
                            wps = list(optimized_holes[i+1]["waypoints"])
                            wps[0] = (limited_tee_x, limited_tee_y)
                            optimized_holes[i+1]["waypoints"] = wps

            # Phase 2: Optimiser la compacité globale
            for i in range(len(optimized_holes)):
                tee = optimized_holes[i]["tee"]
                green = optimized_holes[i]["green"]

                # Convertir en tuples si ce sont des dicts
                if isinstance(tee, dict):
                    tx, ty = tee["x"], tee["y"]
                    gx, gy = green["x"], green["y"]
                else:
                    tx, ty = tee[0], tee[1]
                    gx, gy = green[0], green[1]

                # Calculer les distances au centroïde
                tee_dist = math.sqrt((tx - centroid[0])**2 + (ty - centroid[1])**2)
                green_dist = math.sqrt((gx - centroid[0])**2 + (gy - centroid[1])**2)

                # Si trop éloignés du centre, rapprocher légèrement
                if tee_dist > compacity_target:
                    # Déplacer vers le centroïde
                    dx = centroid[0] - tx
                    dy = centroid[1] - ty
                    move_factor = (tee_dist - compacity_target) / tee_dist * learning_rate * 0.5

                    new_tx = tx + dx * move_factor
                    new_ty = ty + dy * move_factor

                    # Limiter le déplacement par rapport à la position originale
                    original_tee_pos = original_positions[i]["tee"]
                    limited_tx, limited_ty = limit_displacement(
                        (new_tx, new_ty), original_tee_pos, max_displacement
                    )

                    if isinstance(tee, dict):
                        optimized_holes[i]["tee"]["x"] = limited_tx
                        optimized_holes[i]["tee"]["y"] = limited_ty
                    else:
                        optimized_holes[i]["tee"] = (limited_tx, limited_ty)

                    # Ajuster le premier waypoint
                    if optimized_holes[i]["waypoints"]:
                        if isinstance(optimized_holes[i]["waypoints"][0], dict):
                            optimized_holes[i]["waypoints"][0]["x"] = limited_tx
                            optimized_holes[i]["waypoints"][0]["y"] = limited_ty
                        else:
                            wps = list(optimized_holes[i]["waypoints"])
                            wps[0] = (limited_tx, limited_ty)
                            optimized_holes[i]["waypoints"] = wps

                if green_dist > compacity_target:
                    # Déplacer le green vers le centroïde
                    dx = centroid[0] - gx
                    dy = centroid[1] - gy
                    move_factor = (green_dist - compacity_target) / green_dist * learning_rate * 0.5

                    new_gx = gx + dx * move_factor
                    new_gy = gy + dy * move_factor

                    # Limiter le déplacement par rapport à la position originale
                    original_green_pos = original_positions[i]["green"]
                    limited_gx, limited_gy = limit_displacement(
                        (new_gx, new_gy), original_green_pos, max_displacement
                    )

                    if isinstance(green, dict):
                        optimized_holes[i]["green"]["x"] = limited_gx
                        optimized_holes[i]["green"]["y"] = limited_gy
                    else:
                        optimized_holes[i]["green"] = (limited_gx, limited_gy)

                    # Ajuster le dernier waypoint
                    if optimized_holes[i]["waypoints"]:
                        last_idx = len(optimized_holes[i]["waypoints"]) - 1
                        if isinstance(optimized_holes[i]["waypoints"][last_idx], dict):
                            optimized_holes[i]["waypoints"][last_idx]["x"] = limited_gx
                            optimized_holes[i]["waypoints"][last_idx]["y"] = limited_gy
                        else:
                            wps = list(optimized_holes[i]["waypoints"])
                            wps[last_idx] = (limited_gx, limited_gy)
                            optimized_holes[i]["waypoints"] = wps

            # Phase 3: Lisser les transitions entre trous consécutifs
            for i in range(len(optimized_holes) - 1):
                # Calculer les directions des trous consécutifs
                tee1 = optimized_holes[i]["tee"]
                green1 = optimized_holes[i]["green"]
                tee2 = optimized_holes[i+1]["tee"]
                green2 = optimized_holes[i+1]["green"]

                if isinstance(tee1, dict):
                    t1x, t1y = tee1["x"], tee1["y"]
                    g1x, g1y = green1["x"], green1["y"]
                    t2x, t2y = tee2["x"], tee2["y"]
                    g2x, g2y = green2["x"], green2["y"]
                else:
                    t1x, t1y = tee1[0], tee1[1]
                    g1x, g1y = green1[0], green1[1]
                    t2x, t2y = tee2[0], tee2[1]
                    g2x, g2y = green2[0], green2[1]

                # Calculer les angles des deux trous
                angle1 = math.atan2(g1y - t1y, g1x - t1x)
                angle2 = math.atan2(g2y - t2y, g2x - t2x)

                # Calculer la différence d'angle
                angle_diff = abs(angle1 - angle2)
                angle_diff = min(angle_diff, 2*math.pi - angle_diff)

                # Si les directions sont trop différentes, ajuster légèrement
                if angle_diff > math.pi / 3:  # Plus de 60 degrés de différence
                    # Ajuster la direction du deuxième trou pour réduire l'angle
                    adjustment = angle_diff - math.pi / 4  # Cible: ~45 degrés
                    if adjustment > 0:
                        # Calculer un nouvel angle pour le deuxième trou
                        new_angle = angle1 + (math.pi / 4) * (1 if angle2 > angle1 else -1)

                        # Calculer la nouvelle position du green
                        current_length = math.sqrt((g2x - t2x)**2 + (g2y - t2y)**2)
                        new_g2x = t2x + current_length * math.cos(new_angle)
                        new_g2y = t2y + current_length * math.sin(new_angle)

                        # Limiter le déplacement par rapport à la position originale
                        original_green_pos = original_positions[i+1]["green"]
                        limited_g2x, limited_g2y = limit_displacement(
                            (new_g2x, new_g2y), original_green_pos, max_displacement
                        )

                        # Appliquer l'ajustement
                        if isinstance(green2, dict):
                            optimized_holes[i+1]["green"]["x"] = limited_g2x
                            optimized_holes[i+1]["green"]["y"] = limited_g2y
                        else:
                            optimized_holes[i+1]["green"] = (limited_g2x, limited_g2y)

                        # Ajuster le dernier waypoint
                        if optimized_holes[i+1]["waypoints"]:
                            last_idx = len(optimized_holes[i+1]["waypoints"]) - 1
                            if isinstance(optimized_holes[i+1]["waypoints"][last_idx], dict):
                                optimized_holes[i+1]["waypoints"][last_idx]["x"] = limited_g2x
                                optimized_holes[i+1]["waypoints"][last_idx]["y"] = limited_g2y
                            else:
                                wps = list(optimized_holes[i+1]["waypoints"])
                                wps[last_idx] = (limited_g2x, limited_g2y)
                                optimized_holes[i+1]["waypoints"] = wps

        # Debug: vérifier si les positions ont été modifiées
        changes_detected = False
        for i, hole in enumerate(optimized_holes):
            orig_tee = original_positions[i]["tee"]
            orig_green = original_positions[i]["green"]
            
            opt_tee = hole["tee"]
            opt_green = hole["green"]
            
            # Convertir en tuples si ce sont des dicts
            if isinstance(opt_tee, dict):
                opt_tee_pos = (opt_tee["x"], opt_tee["y"])
            else:
                opt_tee_pos = (opt_tee[0], opt_tee[1])
                
            if isinstance(opt_green, dict):
                opt_green_pos = (opt_green["x"], opt_green["y"])
            else:
                opt_green_pos = (opt_green[0], opt_green[1])
            
            # Vérifier si les positions ont changé
            if (abs(opt_tee_pos[0] - orig_tee[0]) > 0.1 or 
                abs(opt_tee_pos[1] - orig_tee[1]) > 0.1 or
                abs(opt_green_pos[0] - orig_green[0]) > 0.1 or 
                abs(opt_green_pos[1] - orig_green[1]) > 0.1):
                changes_detected = True
                print("Hole " + str(i) + " modified")
                break
        
        if changes_detected:
            print("✅ Post-optimization: Positions have been modified")
            # Afficher un exemple de modifications
            if len(optimized_holes) > 0:
                i = 0  # Premier trou
                orig_tee = original_positions[i]["tee"]
                orig_green = original_positions[i]["green"]
                opt_tee = optimized_holes[i]["tee"]
                opt_green = optimized_holes[i]["green"]
                
                if isinstance(opt_tee, dict):
                    opt_tee_pos = (opt_tee["x"], opt_tee["y"])
                else:
                    opt_tee_pos = (opt_tee[0], opt_tee[1])
                    
                if isinstance(opt_green, dict):
                    opt_green_pos = (opt_green["x"], opt_green["y"])
                else:
                    opt_green_pos = (opt_green[0], opt_green[1])
                
                print(f"   Example (hole 1):")
                print(f"     Original - Tee: ({orig_tee[0]:.1f}, {orig_tee[1]:.1f}), Green: ({orig_green[0]:.1f}, {orig_green[1]:.1f})")
                print(f"     Optimized - Tee: ({opt_tee_pos[0]:.1f}, {opt_tee_pos[1]:.1f}), Green: ({opt_green_pos[0]:.1f}, {opt_green_pos[1]:.1f})")
        else:
            print("⚠️  Post-optimization: No significant position changes detected")
        
        return optimized_holes