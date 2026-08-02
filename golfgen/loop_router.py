"""Routing par ruban : une boucle serpentine par nine, découpée en trous.

Approche « la courbe d'abord, les trous ensuite » : chaque nine est une courbe
fermée simple qui part des abords du clubhouse, serpente dans son triangle (la
carte est coupée en deux par la diagonale du coin clubhouse) et y revient. La
courbe est le contour offset d'une « spine » boustrophédon ; les trous sont des
tronçons consécutifs de ce ruban, séparés par les liaisons green→tee.

Garanties par construction (aucun solveur, aucune réparation) :
- pas d'auto-intersection ni de croisement entre nines ;
- liaisons green→tee exactes et ordre de jeu gratuit (l'ordre sur la courbe) ;
- chaque nine part du clubhouse et y revient ;
- aucun angle > MAX_CORNER_DEG a l'intérieur d'un trou, courbure nette par trou
  bornée par MAX_NET_DEG : les virages en épingle tombent sur les liaisons
  (un trou de golf ne se replie pas sur lui-même) — c'est le découpage par
  programmation dynamique qui place les coupes en conséquence.

Seules vérifications numériques : clairance entre segments non adjacents et
exclusion clubhouse ; un tirage coûte quelques millisecondes, on retire.
"""

from __future__ import annotations

import math
import random
from bisect import bisect_left, bisect_right

import numpy as np

from golfgen.clubhouse import pick_clubhouse
from golfgen.config import CourseConfig
from golfgen.hole_gen import resolve_par_distribution
from golfgen.terrain import TerrainGenerator
from golfgen.utils import direction_label, distance, point_to_segment_dist, polyline_length

LOOP_ATTEMPTS = 300          # tirages de boucle max par nine
CLEARANCE_REQUIRED = 18.0    # distance min entre segments non adjacents
HUB_RADIUS = 40.0            # rayon autour du clubhouse exempté de clairance
EDGE_MARGIN = 7.0            # demi-fairway max : le fairway touche la bordure
# La boucle d'un nine est le contour offset d'une spine boustrophédon.
# Espacements par construction : 2×SPINE_OFFSET entre l'aller et le retour
# d'une même rangée, pitch − 2×SPINE_OFFSET entre rangées voisines. Le pitch
# est large : le budget de longueur (fixé par les pars) doit couvrir la carte.
SPINE_OFFSET = 15.0
ROW_PITCH = (64.0, 78.0)     # espacement vertical entre rangées de la spine
DIAG_GAP = 14.0              # demi-écart de part et d'autre de la diagonale
ROW_JITTER = 5.0             # amplitude des doglegs sur une rangée
FILLET_RADIUS = 32.0         # rayon des congés aux virages de la spine
MAX_ARC_STEP_DEG = 22.0      # granularité angulaire des congés et du cap
# Règles d'angles à l'intérieur d'un trou (les virages plus durs vont aux
# liaisons) : bornes par virage et sur la courbure nette cumulée.
MAX_CORNER_DEG = 100.0
MAX_NET_DEG = 92.0
CUT_STEP = 3.0               # discrétisation du découpage (blocs)
# Les stubs clubhouse (marche vers le tee 1 / depuis le green 9) ne sont pas
# des liaisons jouables : plus longs, ils absorbent la quantification des
# fenêtres de validité du découpage.
STUB_MAX = 90.0
# Une liaison green→tee se marche à vol d'oiseau : son ARC le long du ruban
# peut enjamber toute une épingle, seule sa corde euclidienne doit rester
# dans [tee_link_min, tee_link_max].
LINK_ARC_MAX = 150.0
# Nombre de permutations des pars d'un nine essayées quand l'ordre configuré
# ne s'aligne pas sur les rangées du ruban.
PAR_ORDER_SHUFFLES = 14


# ----------------------------------------------------------------------
# Géométrie de la boucle
# ----------------------------------------------------------------------

def _radius_cap(clubhouse: tuple[float, float], theta: float,
                config: CourseConfig) -> float:
    """Distance max depuis le clubhouse le long de theta restant en carte."""
    x, y = clubhouse
    cos_t, sin_t = math.cos(theta), math.sin(theta)
    cap = float("inf")
    if cos_t > 1e-9:
        cap = min(cap, (config.width - EDGE_MARGIN - x) / cos_t)
    elif cos_t < -1e-9:
        cap = min(cap, (EDGE_MARGIN - x) / cos_t)
    if sin_t > 1e-9:
        cap = min(cap, (config.height - EDGE_MARGIN - y) / sin_t)
    elif sin_t < -1e-9:
        cap = min(cap, (EDGE_MARGIN - y) / sin_t)
    return max(cap, 0.0)


def _spine_points(rng: random.Random, u_cap: float, v_cap: float, v_floor: float,
                  max_length: float) -> list[tuple[float, float]]:
    """Spine boustrophédon du triangle {v <= u - DIAG_GAP} du repère coin.

    (u, v) sont les coordonnées le long des deux murs du coin, origine au
    clubhouse (les valeurs négatives couvrent la bande entre le clubhouse et
    les murs). La spine part de l'esplanade clubhouse et serpente en rangées
    parallèles à l'axe u jusqu'à épuisement du triangle ou du budget.
    """
    offset = SPINE_OFFSET
    points: list[tuple[float, float]] = []
    v = rng.uniform(v_floor, v_floor + 8.0)
    going_right = True
    # Le départ laisse passer les brins de l'AUTRE boucle (qui longent leur
    # mur dans le repère miroir) : le coin reste une esplanade clubhouse.
    points.append((rng.uniform(38.0, 48.0), v))

    def left_margin(row_v: float) -> float:
        # ROW_JITTER compte : les doglegs ne doivent pas entamer la marge
        # diagonale partagée avec l'autre nine.
        return max(row_v + DIAG_GAP + offset + ROW_JITTER
                   + rng.uniform(0.0, 10.0), 18.0)

    while True:
        pitch = rng.uniform(*ROW_PITCH)
        u_right = u_cap - offset - rng.uniform(0.0, 5.0)
        # Le virage gauche est une verticale à 90° : elle doit respecter la
        # marge diagonale de la rangée SUPERIEURE qu'elle rejoint (la rangée
        # basse s'arrête donc un peu plus tôt — le connecteur reste carré,
        # aucun virage de spine ne dépasse 90°).
        u_left = left_margin(v + pitch)
        # Une rangée doit au moins loger les deux tangentes de ses congés
        # (le rayon effectif s'adapte si la rangée est courte).
        if u_right - u_left < 2.0 * FILLET_RADIUS:
            break
        start_u = points[-1][0]
        end_u = u_right if going_right else u_left
        # Doglegs : points intermédiaires avec jitter vertical.
        # Pas de dogleg sur les rangées courtes : une tige raccourcie
        # écraserait le rayon du congé voisin et pincerait le contour.
        n_mid = int(abs(end_u - start_u) / 130.0)
        for i in range(1, n_mid + 1):
            mid_u = start_u + (end_u - start_u) * i / (n_mid + 1)
            points.append((mid_u, v + rng.uniform(-ROW_JITTER, ROW_JITTER)))
        points.append((end_u, v))

        if v + pitch > v_cap - offset:
            break
        v += pitch
        points.append((end_u, v))
        going_right = not going_right
        if polyline_length(points) > max_length:
            break

    if polyline_length(points) > max_length:
        return _sub_polyline(points, 0.0, max_length)
    return points


def _round_corners(points: list[tuple[float, float]],
                   radius: float = FILLET_RADIUS) -> list[tuple[float, float]]:
    """Remplace chaque virage marqué de la spine par un congé en arc.

    Le virage devient une suite de petits pas d'au plus MAX_ARC_STEP_DEG :
    aucun virage individuel ne dépasse la borne par-virage des trous, et le
    découpage peut trancher n'importe où dans l'arc. Le rayon effectif reste
    supérieur à SPINE_OFFSET, donc le contour intérieur ne se replie jamais.
    """
    result = [points[0]]
    for i in range(1, len(points) - 1):
        prev, here, nxt = points[i - 1], points[i], points[i + 1]
        d1, d2 = distance(prev, here), distance(here, nxt)
        v1 = ((here[0] - prev[0]) / d1, (here[1] - prev[1]) / d1)
        v2 = ((nxt[0] - here[0]) / d2, (nxt[1] - here[1]) / d2)
        turn = math.atan2(v1[0] * v2[1] - v1[1] * v2[0],
                          v1[0] * v2[0] + v1[1] * v2[1])
        if abs(math.degrees(turn)) < 25.0:
            result.append(here)
            continue
        half_tan = math.tan(abs(turn) / 2.0)
        tangent = min(radius * half_tan, 0.42 * d1, 0.42 * d2)
        r_eff = tangent / half_tan
        p_in = (here[0] - v1[0] * tangent, here[1] - v1[1] * tangent)
        side = 1.0 if turn > 0 else -1.0
        center = (p_in[0] - v1[1] * r_eff * side,
                  p_in[1] + v1[0] * r_eff * side)
        phi = math.atan2(p_in[1] - center[1], p_in[0] - center[0])
        n_sub = max(2, int(math.ceil(abs(math.degrees(turn)) / MAX_ARC_STEP_DEG)))
        for j in range(n_sub + 1):
            angle = phi + turn * j / n_sub
            result.append((center[0] + r_eff * math.cos(angle),
                           center[1] + r_eff * math.sin(angle)))
    result.append(points[-1])
    return result


def _despike(points: list[tuple[float, float]]) -> list[tuple[float, float]]:
    """Supprime les replis résiduels d'un contour offset (virages > 130°)."""
    pts = list(points)
    changed = True
    while changed and len(pts) > 3:
        changed = False
        for i in range(1, len(pts) - 1):
            d1 = distance(pts[i - 1], pts[i])
            d2 = distance(pts[i], pts[i + 1])
            if d1 < 1e-9 or d2 < 1e-9:
                del pts[i]
                changed = True
                break
            dot = ((pts[i][0] - pts[i - 1][0]) * (pts[i + 1][0] - pts[i][0])
                   + (pts[i][1] - pts[i - 1][1]) * (pts[i + 1][1] - pts[i][1]))
            if dot / (d1 * d2) < math.cos(math.radians(130.0)):
                del pts[i]
                changed = True
                break
    return pts


def _offset_polyline(points: list[tuple[float, float]],
                     offset: float) -> list[tuple[float, float]]:
    """Décale une polyligne simple d'``offset`` (signé), joints en onglet."""
    normals = []
    for a, b in zip(points, points[1:]):
        dx, dy = b[0] - a[0], b[1] - a[1]
        norm = math.hypot(dx, dy)
        normals.append((-dy / norm, dx / norm))

    result = [(points[0][0] + offset * normals[0][0],
               points[0][1] + offset * normals[0][1])]
    for i in range(1, len(points) - 1):
        n_prev, n_next = normals[i - 1], normals[i]
        d_prev = (points[i][0] - points[i - 1][0], points[i][1] - points[i - 1][1])
        d_next = (points[i + 1][0] - points[i][0], points[i + 1][1] - points[i][1])
        a1 = (points[i - 1][0] + offset * n_prev[0], points[i - 1][1] + offset * n_prev[1])
        a2 = (points[i][0] + offset * n_next[0], points[i][1] + offset * n_next[1])
        cross = d_prev[0] * d_next[1] - d_prev[1] * d_next[0]
        if abs(cross) < 1e-9:
            result.append(a2)
            continue
        # Intersection des deux bords décalés (joint en onglet).
        t = ((a2[0] - a1[0]) * d_next[1] - (a2[1] - a1[1]) * d_next[0]) / cross
        result.append((a1[0] + d_prev[0] * t, a1[1] + d_prev[1] * t))
    result.append((points[-1][0] + offset * normals[-1][0],
                   points[-1][1] + offset * normals[-1][1]))
    return result


def _loop_points(rng: random.Random, clubhouse: tuple[float, float],
                 frame: tuple[tuple[float, float], tuple[float, float]],
                 config: CourseConfig,
                 max_total: float) -> list[tuple[float, float]]:
    """Une boucle = contour offset de la spine chanfreinée, du hub au hub.

    ``frame`` = (e1, e2), directions unitaires des deux murs du coin ; les
    rangées sont parallèles à e1. Échanger e1/e2 produit le nine miroir de
    l'autre côté de la diagonale.
    """
    e1, e2 = frame
    u_cap = _radius_cap(clubhouse, math.atan2(e1[1], e1[0]), config)
    v_cap = _radius_cap(clubhouse, math.atan2(e2[1], e2[0]), config)
    # Bande murale comprise : la première rangée descend jusqu'à ce que le
    # brin retour du ruban touche presque le mur derrière le clubhouse.
    v_floor = -_radius_cap(clubhouse, math.atan2(-e2[1], -e2[0]), config) \
        + SPINE_OFFSET
    max_spine = (max_total - 4.0 * SPINE_OFFSET) / 2.0
    spine_uv = _round_corners(_spine_points(rng, u_cap, v_cap, v_floor, max_spine))

    side_a = _despike(_offset_polyline(spine_uv, SPINE_OFFSET))
    side_b = _despike(_offset_polyline(spine_uv, -SPINE_OFFSET))

    # Cap en demi-cercle au bout du ruban (le hub reste ouvert) : des pas de
    # ~30 degrés que le découpage traite comme n'importe quel virage.
    end = spine_uv[-1]
    before = spine_uv[-2]
    d_end = distance(before, end)
    direction = ((end[0] - before[0]) / d_end, (end[1] - before[1]) / d_end)
    normal = (-direction[1], direction[0])
    cap = []
    for j in range(1, 6):
        angle = math.pi * j / 6.0
        cap.append((
            end[0] + SPINE_OFFSET * (normal[0] * math.cos(angle)
                                     + direction[0] * math.sin(angle)),
            end[1] + SPINE_OFFSET * (normal[1] * math.cos(angle)
                                     + direction[1] * math.sin(angle)),
        ))
    loop_uv = side_a + cap + list(reversed(side_b))

    return [
        (clubhouse[0] + u * e1[0] + v * e2[0],
         clubhouse[1] + u * e1[1] + v * e2[1])
        for u, v in loop_uv
    ]


# ----------------------------------------------------------------------
# Vérifications numériques
# ----------------------------------------------------------------------

def _min_clearance(points: list[tuple[float, float]],
                   other_segments: list[tuple[tuple[float, float], tuple[float, float]]],
                   clubhouse: tuple[float, float]) -> float:
    """Clairance min entre segments non adjacents, hors zone clubhouse."""
    segments = list(zip(points, points[1:]))

    def near_hub(seg):
        return (distance(seg[0], clubhouse) < HUB_RADIUS
                or distance(seg[1], clubhouse) < HUB_RADIUS)

    def seg_dist(a, b):
        (a1, a2), (b1, b2) = a, b
        return min(
            point_to_segment_dist(a1[0], a1[1], b1[0], b1[1], b2[0], b2[1]),
            point_to_segment_dist(a2[0], a2[1], b1[0], b1[1], b2[0], b2[1]),
            point_to_segment_dist(b1[0], b1[1], a1[0], a1[1], a2[0], a2[1]),
            point_to_segment_dist(b2[0], b2[1], a1[0], a1[1], a2[0], a2[1]),
        )

    # Deux segments proches LE LONG de la courbe appartiennent au même virage
    # (chanfreins compris) : le pincement intérieur d'une épingle est normal
    # pour un ruban — ces zones accueillent des liaisons, pas des fairways.
    # Seuls les rapprochements entre portions éloignées sur la courbe comptent.
    arc_positions = [0.0]
    for a, b in zip(points, points[1:]):
        arc_positions.append(arc_positions[-1] + distance(a, b))
    same_turn_arc = 5.0 * SPINE_OFFSET

    clearance = float("inf")
    for i, seg_a in enumerate(segments):
        for j in range(i + 2, len(segments)):
            seg_b = segments[j]
            if arc_positions[j] - arc_positions[i + 1] < same_turn_arc:
                continue
            if near_hub(seg_a) and near_hub(seg_b):
                continue
            clearance = min(clearance, seg_dist(seg_a, seg_b))
    for seg_a in segments:
        for seg_b in other_segments:
            if near_hub(seg_a) and near_hub(seg_b):
                continue
            clearance = min(clearance, seg_dist(seg_a, seg_b))
    return clearance


def _clubhouse_clear(points: list[tuple[float, float]],
                     clubhouse: tuple[float, float]) -> bool:
    """Aucun point du ruban dans la zone clubhouse (boîte 15x10 + fairway)."""
    half_w, half_h = 15.0 + 9.0, 10.0 + 9.0
    cx, cy = clubhouse
    total = polyline_length(points)
    steps = max(2, int(total / 6.0))
    for i in range(steps + 1):
        x, y = _point_at(points, total * i / steps)
        if abs(x - cx) < half_w and abs(y - cy) < half_h:
            return False
    return True


# ----------------------------------------------------------------------
# Découpage du ruban en trous
# ----------------------------------------------------------------------

def _hole_length_range(par: int, config: CourseConfig) -> tuple[int, int]:
    rc = config.routing
    return {3: rc.par3_range, 4: rc.par4_range, 5: rc.par5_range}[par]


def _point_at(points: list[tuple[float, float]], arclength: float) -> tuple[float, float]:
    travelled = 0.0
    for a, b in zip(points, points[1:]):
        step = distance(a, b)
        if travelled + step >= arclength - 1e-9:
            t = 0.0 if step < 1e-9 else (arclength - travelled) / step
            return (a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t)
        travelled += step
    return points[-1]


def _sub_polyline(points: list[tuple[float, float]], start: float,
                  end: float) -> list[tuple[float, float]]:
    """Tronçon [start, end] en arclength : extrémités interpolées + sommets."""
    result = [_point_at(points, start)]
    travelled = 0.0
    for a, b in zip(points, points[1:]):
        step = distance(a, b)
        if start + 0.75 < travelled + step and travelled + step < end - 0.75:
            if travelled + step > start:
                result.append(b)
        travelled += step
    result.append(_point_at(points, end))
    return result


def _sample_coords(points: list[tuple[float, float]],
                   step: float, count: int) -> list[tuple[float, float]]:
    """Positions xy tous les ``step`` blocs le long du ruban (marche unique)."""
    coords = []
    seg_idx, travelled = 0, 0.0
    for k in range(count):
        target = k * step
        while seg_idx < len(points) - 2 and \
                travelled + distance(points[seg_idx], points[seg_idx + 1]) < target:
            travelled += distance(points[seg_idx], points[seg_idx + 1])
            seg_idx += 1
        a, b = points[seg_idx], points[seg_idx + 1]
        seg_len = distance(a, b)
        t = 0.0 if seg_len < 1e-9 else min(1.0, (target - travelled) / seg_len)
        coords.append((a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t))
    return coords


def _corners(points: list[tuple[float, float]]) -> list[tuple[float, float]]:
    """(arclength, angle signé en degrés) de chaque virage du ruban."""
    out = []
    travelled = 0.0
    for i in range(1, len(points) - 1):
        travelled += distance(points[i - 1], points[i])
        d1 = distance(points[i - 1], points[i])
        d2 = distance(points[i], points[i + 1])
        if d1 < 1e-9 or d2 < 1e-9:
            continue
        v1 = ((points[i][0] - points[i - 1][0]) / d1,
              (points[i][1] - points[i - 1][1]) / d1)
        v2 = ((points[i + 1][0] - points[i][0]) / d2,
              (points[i + 1][1] - points[i][1]) / d2)
        angle = math.degrees(math.atan2(
            v1[0] * v2[1] - v1[1] * v2[0], v1[0] * v2[0] + v1[1] * v2[1]
        ))
        if abs(angle) > 0.5:
            out.append((travelled, angle))
    return out


def _cut_nine(rng: random.Random, points: list[tuple[float, float]],
              pars: list[int], config: CourseConfig) -> list[dict] | None:
    """Découpe le ruban en trous par programmation dynamique.

    Positions discrétisées au pas CUT_STEP. Un trou n'est valide que si tous
    ses virages intérieurs respectent MAX_CORNER_DEG et que leur somme signée
    reste sous MAX_NET_DEG : les épingles du serpentin tombent d'office sur
    les liaisons. None si aucun découpage n'existe pour ce ruban.
    """
    rc = config.routing
    total = polyline_length(points)
    n_pos = int(total / CUT_STEP)
    coords = _sample_coords(points, CUT_STEP, n_pos)
    corner_list = _corners(points)
    corner_s = [s for s, _ in corner_list]

    def hole_ok(start: float, end: float) -> bool:
        # Fenetre alignee EXACTEMENT sur le seuil de nettoyage des sommets
        # de _sub_polyline : un virage plus pres de la coupe est efface de
        # l'export (sa direction n'est pas realisee), il ne compte donc pas ;
        # au-dela il est pleinement exporte et compte.
        lo = bisect_right(corner_s, start + 0.75)
        hi = bisect_left(corner_s, end - 0.75)
        net = 0.0
        for k in range(lo, hi):
            angle = corner_list[k][1]
            if abs(angle) > MAX_CORNER_DEG:
                return False
            net += angle
        return abs(net) <= MAX_NET_DEG

    link_indices = range(int(math.ceil(rc.tee_link_min / CUT_STEP)),
                         int(LINK_ARC_MAX / CUT_STEP) + 1)
    stub_indices = range(int(math.ceil(rc.tee_link_min / CUT_STEP)),
                         int(STUB_MAX / CUT_STEP) + 1)
    valid_holes: dict[tuple[int, int], list[int]] = {}

    def greens_for(tee_idx: int, par: int) -> list[int]:
        key = (tee_idx, par)
        if key not in valid_holes:
            lo, hi = _hole_length_range(par, config)
            result = []
            for length_idx in range(int(math.ceil(lo / CUT_STEP)),
                                    int(hi / CUT_STEP) + 1):
                green_idx = tee_idx + length_idx
                if green_idx >= n_pos:
                    break
                if hole_ok(tee_idx * CUT_STEP, green_idx * CUT_STEP):
                    result.append(green_idx)
            valid_holes[key] = result
        return valid_holes[key]

    def solve(order: list[int]) -> list[dict] | None:
        # parent[k][green] = (green_precedent, tee) — un seul parent suffit.
        parent: list[dict[int, tuple[int | None, int]]] = [{} for _ in order]
        for tee_idx in stub_indices:  # stub clubhouse -> tee du trou 1
            for green_idx in greens_for(tee_idx, order[0]):
                parent[0].setdefault(green_idx, (None, tee_idx))

        for k in range(1, len(order)):
            for green_prev, _ in parent[k - 1].items():
                for link_idx in link_indices:
                    tee_idx = green_prev + link_idx
                    if tee_idx >= n_pos:
                        continue
                    # La liaison est jouée à vol d'oiseau : c'est la corde qui
                    # doit rester dans les bornes, l'arc pouvant enjamber une
                    # épingle entière.
                    chord = distance(coords[green_prev], coords[tee_idx])
                    # +0.35 : l'arrondi des coordonnees exportees ne doit pas
                    # faire retomber la corde sous le minimum.
                    if not rc.tee_link_min + 0.35 <= chord <= rc.tee_link_max:
                        continue
                    for green_idx in greens_for(tee_idx, order[k]):
                        parent[k].setdefault(green_idx, (green_prev, tee_idx))

        finals = [
            green_idx for green_idx in parent[-1]
            if rc.tee_link_min <= total - green_idx * CUT_STEP <= STUB_MAX
        ]
        if not finals:
            return None

        holes_rev = []
        green_idx = rng.choice(finals)
        for k in range(len(order) - 1, -1, -1):
            green_prev, tee_idx = parent[k][green_idx]
            holes_rev.append({
                "par": order[k],
                "waypoints": _sub_polyline(points, tee_idx * CUT_STEP,
                                           green_idx * CUT_STEP),
            })
            green_idx = green_prev
        return list(reversed(holes_rev))

    # L'ordre configuré est un patron préféré, pas un invariant : seules les
    # sommes par nine sont garanties (resolve_par_distribution). Si le patron
    # ne s'aligne pas sur les rangées du ruban, on permute les pars du nine —
    # le cache des fenêtres est partagé, chaque ordre supplémentaire est
    # quasi gratuit.
    holes = solve(list(pars))
    if holes is not None:
        return holes
    for _ in range(PAR_ORDER_SHUFFLES):
        shuffled = list(pars)
        rng.shuffle(shuffled)
        holes = solve(shuffled)
        if holes is not None:
            return holes
    return None


# ----------------------------------------------------------------------
# Assemblage
# ----------------------------------------------------------------------

def _build_nine(rng: random.Random, clubhouse: tuple[float, float],
                frame: tuple[tuple[float, float], tuple[float, float]],
                pars: list[int], config: CourseConfig,
                other_segments: list) -> tuple[list[dict], list[tuple[float, float]]] | None:
    """Tire des boucles jusqu'à en trouver une claire et découpable."""
    rc = config.routing
    length_low = (sum(_hole_length_range(p, config)[0] for p in pars)
                  + (len(pars) + 1) * rc.tee_link_min)
    length_high = (sum(_hole_length_range(p, config)[1] for p in pars)
                   + (len(pars) + 1) * rc.tee_link_max)
    for _ in range(LOOP_ATTEMPTS):
        # L'arc des liaisons pouvant enjamber les épingles, le ruban peut être
        # plus long que la somme des bornes hautes : marge de 250 blocs.
        points = _loop_points(rng, clubhouse, frame, config,
                              max_total=length_high + 250.0)
        # Le découpage perd ~150 blocs en friction de phase (les trous se
        # calent sur les rangées) : un ruban trop juste ne se découpe jamais.
        if polyline_length(points) < length_low + 170.0:
            continue
        if not _clubhouse_clear(points, clubhouse):
            continue
        clearance = _min_clearance(points, other_segments, clubhouse)
        if clearance < CLEARANCE_REQUIRED:
            continue
        holes = _cut_nine(rng, points, pars, config)
        if holes is None:
            continue
        return holes, points
    return None


def build_course_loop(config: CourseConfig,
                      heightmap: np.ndarray | None) -> tuple[list[dict], tuple[float, float]]:
    """Génère les trous par découpage de deux boucles serpentines.

    Même contrat que ``course_builder.build_course`` : (holes, clubhouse_pos).
    """
    rng = random.Random(config.seed + 1)
    clubhouse_pos, sep_angle = pick_clubhouse(config, rng)

    pars = resolve_par_distribution(config)
    mid = len(pars) // 2
    quadrant = math.pi / 4
    wall1 = sep_angle - quadrant
    wall2 = sep_angle + quadrant
    e1 = (math.cos(wall1), math.sin(wall1))
    e2 = (math.cos(wall2), math.sin(wall2))

    # Le back doit rester clair du front déjà posé : si aucune boucle back ne
    # convient, on retire aussi le front plutôt que d'insister contre lui.
    for _ in range(12):
        front_result = _build_nine(
            rng, clubhouse_pos, (e1, e2), pars[:mid], config, other_segments=[]
        )
        if front_result is None:
            continue
        front, front_points = front_result
        back_result = _build_nine(
            rng, clubhouse_pos, (e2, e1), pars[mid:], config,
            other_segments=list(zip(front_points, front_points[1:])),
        )
        if back_result is not None:
            back, _ = back_result
            break
    else:
        raise RuntimeError("aucune paire de boucles valide")

    rc = config.routing
    holes = []
    for position, hole in enumerate(front + back):
        waypoints = hole["waypoints"]
        tee, green = waypoints[0], waypoints[-1]
        par = hole["par"]
        fairway_width = {3: rc.fairway_width_par3, 4: rc.fairway_width_par4,
                         5: rc.fairway_width_par5}[par]
        holes.append({
            "id": position + 1,
            "par": par,
            "blocks": int(polyline_length(waypoints)),
            "tee": {
                "x": round(tee[0], 2), "y": round(tee[1], 2),
                "elevation": TerrainGenerator.sample_elevation(heightmap, tee[0], tee[1]),
            },
            "green": {
                "x": round(green[0], 2), "y": round(green[1], 2),
                "radius": rng.randint(rc.green_radius_min, rc.green_radius_max),
                "elevation": TerrainGenerator.sample_elevation(heightmap, green[0], green[1]),
            },
            "waypoints": [{"x": round(p[0], 2), "y": round(p[1], 2)} for p in waypoints],
            "fairway_width": fairway_width,
            "direction": direction_label(tee, green),
        })
    return holes, clubhouse_pos
