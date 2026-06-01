🎯 Partie 1 : Améliorer la fonction de fitness
Problème actuel

Ta fonction de fitness actuelle est trop générique et ne capture pas les contraintes spécifiques d’un parcours de golf. Elle pénalise des choses comme :

    Les croisements de fairways (✅ bon)
    La compacité (✅ bon, mais mal équilibré)
    La distance entre green(N) et tee(N+1) (✅ bon)

Mais elle ignore :

    L’équilibre des pars (ex: 4× par 3, 10× par 4, 4× par 5 pour 18 trous).
    La variété des directions (éviter que tous les trous aillent dans la même direction).
    Le dénivelé (un bon parcours a des montées/descentes variées).
    La difficulté progressive (les trous doivent varier en difficulté).
    L’esthétique (ex: éviter les angles trop aigus, les fairways trop courts/longs).
    Le réalisme (ex: un par 3 ne doit pas faire 200 blocs, un par 5 ne doit pas faire 50 blocs).

📊 Benchmark contre Pebble Beach (ou autre parcours réel)
Pourquoi ?

    Valider objectivement si ta fonction de fitness produit des résultats "bons".
    Calibrer les poids des différentes pénalités.
    Identifier les critères manquants.

Comment ?

    Créer un fichier JSON manuel avec les coordonnées des trous de Pebble Beach (ou un autre parcours célèbre).
        Exemple : Pebble Beach Hole 1 → Tee: (x1, y1), Green: (x2, y2), Par: 4, etc.
        Outils :
            Utiliser Google Earth pour mesurer les distances et angles.
            Ou trouver des données existantes (ex: Golf Course GIS Data).

    Calculer son score avec ta fonction de fitness actuelle.
        Problème attendu : Le score sera très mauvais (car ta fonction pénalise des choses qui n’ont pas de sens pour un vrai parcours).
        Exemple :

        # Dans ga.py, ajouter une méthode :
        def calculate_fitness_for_manual_course(self, manual_holes: List[Dict]) -> float:
            """Calcule le score d'un parcours manuel (ex: Pebble Beach) avec la fonction de fitness actuelle."""
            # Convertir manual_holes au format attendu par _calc_collision_penalties, etc.
            # Retourner le score total.
            pass

    Comparer avec les résultats du GA.
        Si le GA produit des parcours avec un score pire que Pebble Beach → La fonction de fitness est mal calibrée.
        Si le GA produit des parcours avec un score similaire mais visuellement mauvais → La fonction de fitness manque de critères.

💡 Critères manquants dans la fitness (à ajouter)

Voici une liste de critères spécifiques au golf que tu pourrais ajouter, classés par importance :
Catégorie	Critère	Description	Poids suggéré	Comment implémenter
🏌️ Équilibre des pars	Distribution des pars	4× par 3, 10× par 4, 4× par 5 pour 18 trous	⭐⭐⭐⭐	Pénaliser si trop de trous ont le même par.
📏 Longueur des trous	Longueur par type	Par 3: 90-150m, Par 4: 250-400m, Par 5: 450-600m	⭐⭐⭐⭐	Pénaliser si un trou est trop court/long pour son par.
🔄 Variété des directions	Éviter les alignements	Les trous ne doivent pas tous aller dans la même direction.	⭐⭐⭐	Calculer l’écart-type des angles des trous.
⛰️ Dénivelé	Utilisation du terrain	Un bon parcours utilise les pentes naturelles.	⭐⭐⭐	Pénaliser si tee et green sont à la même altitude.
🎯 Difficulté progressive	Front nine vs Back nine	Le back nine (trous 10-18) doit être légèrement plus difficile.	⭐⭐	Comparer la longueur moyenne des deux nines.
🚫 Éviter les angles aigus	Fairway shape	Les waypoints ne doivent pas former des angles < 30°.	⭐⭐	Vérifier les angles entre segments consécutifs.
🌳 Obstacles naturels	Bunkers, eau, arbres	Les trous doivent éviter les zones "dangereuses".	⭐⭐	(À implémenter plus tard avec hazards.py).
🏠 Retour au clubhouse	Fin du parcours	Le green du trou 18 doit être proche du clubhouse.	⭐⭐⭐	Pénaliser si la distance > 50 blocs.
🔄 Boucle naturelle	Flow du parcours	Les trous doivent former une boucle (pas une ligne).	⭐⭐⭐	Utiliser un score de "circularité" (ex: distance entre tee(1) et green(18)).
📉 Variété des fairways	Largeur des fairways	Les fairways ne doivent pas tous avoir la même largeur.	⭐	Calculer l’écart-type des largeurs.
📈 Nouvelle fonction de fitness proposée

Voici une version améliorée de ta fonction evaluate, avec les nouveaux critères :

def evaluate(self, individual):
    """Fitness function: calculates penalties for the entire course."""
    holes, construction_penalty = self._build_course(individual)
    if holes is None:
        return (1e9,)

    # --- 1. Critères de base (déjà présents) ---
    overlap = self._calc_collision_penalties(holes)  # ✅ Croisements de fairways
    compacity = self.compacity_score(holes)  # ✅ Compacité globale
    tee_green_distance = self.tee_green_distance_score(holes)  # ✅ Continuité
    consecutive = self.consecutive_holes_score(holes)  # ✅ Distance entre trous consécutifs
    natural_layout = self.natural_layout_score(holes)  # ✅ Disposition en boucle
    fairway_concentration = self.fairway_concentration_score(holes)  # ✅ Concentration des fairways

    # --- 2. NOUVEAUX CRITÈRES SPÉCIFIQUES AU GOLF ---
    # 2.1. Équilibre des pars (4× par 3, 10× par 4, 4× par 5 pour 18 trous)
    par_distribution_penalty = self._par_distribution_score(holes)

    # 2.2. Longueur des trous adaptée au par
    length_penalty = self._hole_length_score(holes)

    # 2.3. Variété des directions (éviter les alignements)
    direction_variety_penalty = self._direction_variety_score(holes)

    # 2.4. Dénivelé (utilisation du terrain)
    elevation_penalty = self._elevation_score(holes)

    # 2.5. Difficulté progressive (back nine > front nine)
    difficulty_progression_penalty = self._difficulty_progression_score(holes)

    # 2.6. Retour au clubhouse (trou 18 proche du clubhouse)
    return_to_clubhouse_penalty = self._return_to_clubhouse_score(holes)

    # --- 3. SCORE TOTAL (poids à ajuster) ---
    total_score = (
        construction_penalty * 1.0 +
        overlap * 2.0 +  # ✅ Très important : éviter les croisements
        compacity * 1.5 +  # ✅ Important : compacité globale
        tee_green_distance * 1.5 +  # ✅ Important : continuité
        consecutive * 0.5 +  # ✅ Moyen : distance entre trous consécutifs
        natural_layout * 1.0 +  # ✅ Moyen : disposition en boucle
        fairway_concentration * 2.0 +  # ✅ Important : concentration des fairways
        # NOUVEAUX CRITÈRES
        par_distribution_penalty * 3.0 +  # ⭐⭐⭐⭐ Très important : équilibre des pars
        length_penalty * 2.5 +  # ⭐⭐⭐⭐ Très important : longueur adaptée au par
        direction_variety_penalty * 1.5 +  # ⭐⭐⭐ Important : variété des directions
        elevation_penalty * 1.0 +  # ⭐⭐ Moyen : dénivelé
        difficulty_progression_penalty * 1.0 +  # ⭐⭐ Moyen : difficulté progressive
        return_to_clubhouse_penalty * 2.0  # ⭐⭐⭐ Important : retour au clubhouse
    )

    return (total_score,)

🔧 Implémentation des nouveaux critères

Voici comment implémenter chaque nouveau critère :
1. _par_distribution_score(holes)

def _par_distribution_score(self, holes: List[Dict]) -> float:
    """Pénalise si la distribution des pars n'est pas équilibrée (4× par 3, 10× par 4, 4× par 5)."""
    par_counts = {3: 0, 4: 0, 5: 0}
    for hole in holes:
        par = hole["par"]
        if par in par_counts:
            par_counts[par] += 1

    # Cibles pour 18 trous
    target = {3: 4, 4: 10, 5: 4}
    penalty = 0.0
    for par, count in par_counts.items():
        if count < target[par]:
            penalty += (target[par] - count) * 1000.0  # Pénalité forte si manque de trous d'un par
        elif count > target[par]:
            penalty += (count - target[par]) * 500.0  # Pénalité modérée si trop de trous d'un par
    return penalty

2. _hole_length_score(holes)

def _hole_length_score(self, holes: List[Dict]) -> float:
    """Pénalise si la longueur des trous n'est pas adaptée à leur par."""
    # Longueurs cibles en blocs (1 bloc = 3m)
    target_lengths = {
        3: (30, 50),   # Par 3: 90-150m
        4: (83, 133),  # Par 4: 250-400m
        5: (150, 200)  # Par 5: 450-600m
    }
    penalty = 0.0
    for hole in holes:
        par = hole["par"]
        length = hole["blocks"]  # Longueur en blocs
        min_len, max_len = target_lengths.get(par, (0, float('inf')))
        if length < min_len:
            penalty += (min_len - length) ** 2 * 10.0
        elif length > max_len:
            penalty += (length - max_len) ** 2 * 5.0
    return penalty

3. _direction_variety_score(holes)

def _direction_variety_score(self, holes: List[Dict]) -> float:
    """Pénalise si tous les trous vont dans la même direction."""
    if len(holes) < 2:
        return 0.0

    # Calculer l'angle de chaque trou (tee → green)
    angles = []
    for hole in holes:
        tee = hole["tee"]
        green = hole["green"]
        if isinstance(tee, dict):
            dx = green["x"] - tee["x"]
            dy = green["y"] - tee["y"]
        else:
            dx = green[0] - tee[0]
            dy = green[1] - tee[1]
        angle = math.atan2(dy, dx)
        angles.append(angle)

    # Calculer l'écart-type des angles (plus il est faible, moins il y a de variété)
    mean_angle = sum(angles) / len(angles)
    variance = sum((a - mean_angle) ** 2 for a in angles) / len(angles)
    std_dev = math.sqrt(variance)

    # Pénaliser si l'écart-type est trop faible (tous les trous dans la même direction)
    if std_dev < math.pi / 6:  # < 30° d'écart
        penalty = (math.pi / 6 - std_dev) * 1000.0
    else:
        penalty = 0.0
    return penalty

4. _elevation_score(holes)

def _elevation_score(self, holes: List[Dict]) -> float:
    """Pénalise si les trous n'utilisent pas le dénivelé du terrain."""
    if self.heightmap is None:
        return 0.0  # Pas de heightmap, pas de pénalité

    penalty = 0.0
    for hole in holes:
        tee = hole["tee"]
        green = hole["green"]
        if isinstance(tee, dict):
            tee_elev = self._elevation_at((tee["x"], tee["y"]))
            green_elev = self._elevation_at((green["x"], green["y"]))
        else:
            tee_elev = self._elevation_at(tee)
            green_elev = self._elevation_at(green)

        # Pénaliser si la différence d'élévation est trop faible (trou plat)
        elev_diff = abs(tee_elev - green_elev)
        if elev_diff < 2.0:  # Moins de 2 blocs de dénivelé
            penalty += (2.0 - elev_diff) * 50.0
        # Bonus si dénivelé important (trou intéressant)
        elif elev_diff > 10.0:
            penalty -= (elev_diff - 10.0) * 5.0  # Récompense
    return max(0, penalty)  # Ne pas retourner de score négatif

5. _difficulty_progression_score(holes)

def _difficulty_progression_score(self, holes: List[Dict]) -> float:
    """Pénalise si le back nine (trous 10-18) n'est pas plus difficile que le front nine (1-9)."""
    if len(holes) < 18:
        return 0.0  # Pas assez de trous

    front_nine = holes[:9]
    back_nine = holes[9:]

    # Calculer la longueur moyenne des deux nines
    front_avg_length = sum(h["blocks"] for h in front_nine) / len(front_nine)
    back_avg_length = sum(h["blocks"] for h in back_nine) / len(back_nine)

    # Le back nine doit être au moins 10% plus long que le front nine
    if back_avg_length < front_avg_length * 1.1:
        penalty = (front_avg_length * 1.1 - back_avg_length) * 10.0
    else:
        penalty = 0.0
    return penalty

6. _return_to_clubhouse_score(holes)

def _return_to_clubhouse_score(self, holes: List[Dict]) -> float:
    """Pénalise si le green du trou 18 est trop loin du clubhouse."""
    if not holes or len(holes) < 18:
        return 0.0

    last_green = holes[-1]["green"]
    if isinstance(last_green, dict):
        last_green_pos = (last_green["x"], last_green["y"])
    else:
        last_green_pos = last_green

    dist_to_ch = distance(last_green_pos, self.clubhouse_pos)
    # Zone cible : 20-50 blocs du clubhouse
    if dist_to_ch < 20:
        penalty = (20 - dist_to_ch) * 20.0
    elif dist_to_ch > 50:
        penalty = (dist_to_ch - 50) * 10.0
    else:
        penalty = 0.0
    return penalty

🧬 Partie 2 : Améliorer la représentation génétique
Problème actuel

Ta représentation génétique actuelle utilise 4 gènes par trou :

    angle (direction du trou)
    dist (distance depuis le point de référence)
    shape_seed (forme du trou)
    rotation (rotation de la forme)

Problèmes identifiés :

    Trop peu de gènes → Manque de flexibilité :
        Impossible de contrôler indépendamment :
            La longueur du fairway.
            Le nombre de waypoints (courbes).
            La largeur du fairway.
            La position du green par rapport au tee.
        Résultat : Tous les trous ressemblent trop à des lignes droites avec une légère courbe.

    Gènes mal adaptés :
        dist est utilisé pour deux choses différentes :
            La distance depuis le clubhouse (trou 1).
            La distance depuis le green précédent (trous 2-9).
        shape_seed ne contrôle pas assez la forme du trou (ex: dogleg gauche/droite, S-curve).

    Pas de contrôle sur les pars :
        Le par est déterminé après coup par HoleGenerator, mais il devrait être un gène pour permettre au GA de choisir le type de trou.

💡 Nouvelle représentation génétique proposée

Voici une nouvelle structure de génome plus riche et plus adaptée au golf :
Gène	Type	Description	Plage	Impact
par	Entier (3, 4, 5)	Par du trou (3, 4 ou 5)	{3, 4, 5}	✅ Contrôle le type de trou
tee_x	Float	Position X du tee (relative au point de référence)	[0, 1]	✅ Position précise
tee_y	Float	Position Y du tee (relative au point de référence)	[0, 1]	✅ Position précise
green_x	Float	Position X du green (relative au tee)	[0, 1]	✅ Contrôle la longueur et direction
green_y	Float	Position Y du green (relative au tee)	[0, 1]	✅ Contrôle la longueur et direction
fairway_width	Float	Largeur du fairway	[5, 20]	✅ Variété des fairways
num_waypoints	Entier	Nombre de waypoints (courbes)	{2, 3, 4, 5}	✅ Complexité du trou
waypoint_1_x	Float	Position X du waypoint 1 (relative au tee)	[0, 1]	✅ Forme du fairway
waypoint_1_y	Float	Position Y du waypoint 1 (relative au tee)	[0, 1]	✅ Forme du fairway
waypoint_2_x	Float	Position X du waypoint 2 (si num_waypoints >= 3)	[0, 1]	✅ Forme du fairway
waypoint_2_y	Float	Position Y du waypoint 2 (si num_waypoints >= 3)	[0, 1]	✅ Forme du fairway
dogleg_direction	Entier	Direction du dogleg (-1: gauche, 0: droit, 1: droite)	{-1, 0, 1}	✅ Forme spécifique

Exemple de génome pour 9 trous :

[par_1, tee_x_1, tee_y_1, green_x_1, green_y_1, fairway_width_1, num_waypoints_1, wp1_x_1, wp1_y_1, wp2_x_1, wp2_y_1, dogleg_1,
 par_2, tee_x_2, tee_y_2, ...]

→ ~10-15 gènes par trou (selon num_waypoints).
⚠️ Avantages et inconvénients
Aspect	Ancienne représentation	Nouvelle représentation
Nombre de gènes	4 × 9 = 36	10-15 × 9 = 90-135
Flexibilité	❌ Faible (tous les trous similaires)	✅ Élevée (contrôle fin)
Complexité	✅ Simple	❌ Plus complexe
Temps de calcul	✅ Rapide	❌ Plus lent (plus de gènes à évaluer)
Qualité des résultats	❌ Moyenne	✅ Excellente
🔧 Comment implémenter la nouvelle représentation ?
Étape 1 : Modifier creator.Individual

# Ancienne version :
creator.create("Individual", array.array, typecode='d', fitness=creator.FitnessMin)

# Nouvelle version (avec un nombre variable de gènes) :
# On peut utiliser une liste Python au lieu de array.array pour plus de flexibilité.
creator.create("Individual", list, fitness=creator.FitnessMin)

Étape 2 : Modifier _create_seeded_individual

def _create_seeded_individual(self, noise: float = 0.0) -> creator.Individual:
    """Crée un individu avec une représentation génétique riche."""
    genes = []
    n = 9  # 9 trous

    # Distribution des pars (4× par 3, 10× par 4, 4× par 5 pour 18 trous)
    # Pour 9 trous : 2× par 3, 5× par 4, 2× par 5
    par_distribution = [4, 4, 4, 4, 4, 3, 3, 5, 5]  # Exemple pour 9 trous

    for i in range(n):
        par = par_distribution[i]

        # Position du tee (relative au point de référence : clubhouse ou green précédent)
        tee_x = self.rng.uniform(0.1, 0.9)  # Éviter les bords
        tee_y = self.rng.uniform(0.1, 0.9)

        # Position du green (relative au tee)
        # Pour un par 3 : distance courte (0.1-0.3)
        # Pour un par 4 : distance moyenne (0.3-0.6)
        # Pour un par 5 : distance longue (0.6-0.9)
        if par == 3:
            green_dist = self.rng.uniform(0.1, 0.3)
        elif par == 4:
            green_dist = self.rng.uniform(0.3, 0.6)
        else:  # par 5
            green_dist = self.rng.uniform(0.6, 0.9)

        green_angle = self.rng.uniform(0, 2 * math.pi)
        green_x = tee_x + green_dist * math.cos(green_angle)
        green_y = tee_y + green_dist * math.sin(green_angle)

        # Largeur du fairway (5-20 blocs)
        fairway_width = self.rng.uniform(5, 20)

        # Nombre de waypoints (2-5)
        num_waypoints = self.rng.randint(2, 5)

        # Waypoints (positions relatives au tee)
        waypoints = []
        for j in range(num_waypoints - 2):  # -2 car tee et green sont déjà inclus
            wp_x = self.rng.uniform(0, 1)
            wp_y = self.rng.uniform(0, 1)
            waypoints.extend([wp_x, wp_y])

        # Direction du dogleg (-1: gauche, 0: droit, 1: droite)
        dogleg_direction = self.rng.choice([-1, 0, 1])

        # Ajouter les gènes pour ce trou
        genes.extend([
            par, tee_x, tee_y, green_x, green_y,
            fairway_width, num_waypoints, *waypoints,
            dogleg_direction
        ])

    return creator.Individual(genes)

Étape 3 : Modifier _build_course

def _build_course(self, individual) -> Tuple[Optional[List[Dict]], float]:
    holes = []
    construction_penalty = 0.0
    w, h = self.config.width, self.config.height
    margin = self.config.routing.grid_margin

    idx = 0
    prev_green = self.clubhouse_pos  # Point de référence initial = clubhouse

    for hole_id in range(1, 10):  # 1 à 9
        if idx >= len(individual):
            break  # Sécurité

        # Lire les gènes pour ce trou
        par = int(individual[idx])
        tee_x_rel = individual[idx + 1]
        tee_y_rel = individual[idx + 2]
        green_x_rel = individual[idx + 3]
        green_y_rel = individual[idx + 4]
        fairway_width = individual[idx + 5]
        num_waypoints = int(individual[idx + 6])
        waypoints_rel = individual[idx + 7 : idx + 7 + 2 * (num_waypoints - 2)]
        dogleg_direction = int(individual[idx + 7 + 2 * (num_waypoints - 2)])
        idx += 7 + 2 * (num_waypoints - 2) + 1

        # Calculer la position absolue du tee (relative au point de référence)
        ref_x, ref_y = prev_green
        tee_x_abs = ref_x + (w - 2 * margin) * (tee_x_rel - 0.5) * 2  # [margin, w - margin]
        tee_y_abs = ref_y + (h - 2 * margin) * (tee_y_rel - 0.5) * 2
        tee_pos = (max(margin, min(tee_x_abs, w - margin)), max(margin, min(tee_y_abs, h - margin)))

        # Calculer la position absolue du green (relative au tee)
        green_x_abs = tee_pos[0] + (w - 2 * margin) * (green_x_rel - 0.5) * 2
        green_y_abs = tee_pos[1] + (h - 2 * margin) * (green_y_rel - 0.5) * 2
        green_pos = (max(margin, min(green_x_abs, w - margin)), max(margin, min(green_y_abs, h - margin)))

        # Calculer les waypoints absolus
        waypoints_abs = [tee_pos]
        for j in range(0, len(waypoints_rel), 2):
            wp_x_rel = waypoints_rel[j]
            wp_y_rel = waypoints_rel[j + 1]
            wp_x_abs = tee_pos[0] + (w - 2 * margin) * (wp_x_rel - 0.5) * 2
            wp_y_abs = tee_pos[1] + (h - 2 * margin) * (wp_y_rel - 0.5) * 2
            waypoints_abs.append((max(margin, min(wp_x_abs, w - margin)), max(margin, min(wp_y_abs, h - margin))))
        waypoints_abs.append(green_pos)

        # Appliquer le dogleg si nécessaire
        if dogleg_direction != 0:
            waypoints_abs = self._apply_dogleg(waypoints_abs, dogleg_direction, fairway_width)

        # Générer la forme du trou (utiliser HoleGenerator ou créer manuellement)
        shape = self._create_hole_shape(
            par=par,
            waypoints=waypoints_abs,
            fairway_width=fairway_width,
            green_radius=self.config.routing.green_radius
        )

        # Ajouter le trou
        hole_data = {
            "id": hole_id,
            "par": par,
            "shape": shape,
            "waypoints": waypoints_abs,
            "tee": tee_pos,
            "green": green_pos,
            "fairway_width": fairway_width
        }
        holes.append(hole_data)
        prev_green = green_pos

    return holes, construction_penalty

📌 Résumé des prochaines étapes

Voici un plan d’action pour améliorer ton GA, classées par priorité :
Étape	Action	Impact	Complexité	Fichiers à modifier
1	Implémenter les nouveaux critères de fitness (par distribution, longueur, variété des directions, etc.)	⭐⭐⭐⭐⭐	⭐⭐	golfgen/ga.py
2	Benchmark contre Pebble Beach (calculer son score avec la nouvelle fitness)	⭐⭐⭐⭐	⭐	tests/, golfgen/ga.py
3	Ajuster les poids de la fitness en fonction des résultats du benchmark	⭐⭐⭐	⭐	golfgen/ga.py
4	Implémenter la nouvelle représentation génétique (plus de gènes, plus de contrôle)	⭐⭐⭐⭐	⭐⭐⭐	golfgen/ga.py
5	Tester avec 18 trous (au lieu de 9)	⭐⭐⭐	⭐⭐	golfgen/ga.py, pipeline.py
6	Optimiser les performances (parallélisation, spatial hashing)	⭐⭐	⭐⭐⭐	golfgen/ga.py