"""Oracle des arbres : vérificateur indépendant du code de placement, sur le
JSON 3.4 écrit par ``pipeline.py --trees-debug``.

L'oracle relit le JSON lui-même, sans ``golfgen.dressing.trees`` :
couronnes en boucles par rayon, table case → arbre pour la disjonction, eau
du relief, bunkers, chemins, parvis, carte, emprises des greens et départs
(aire découpée, Sutherland-Hodgman écrit ici), abords (3 blocs), corridor
``m = 5`` (lisière et remplissage), cœur ``m = 0`` (ancrages), bande de
lisière, couches (ordre de pose, ``grove`` sur les seuls ancrages) et
bosquets d'ancrage relus dans ``trees.debug.groves`` (tirage, motif,
portée, segment sans chemin). Couches stratégiques (retombée, green) :
rayon 3, ni abords ni corridor ici.

Oracle stratégique (``strategic_oracle``), porté de l'oracle de l'étude
stratégique du lot 5 (``tests/test_tools_dressing_trees_strategic.py``,
retiré au R7), sur la sortie en mémoire de ``place_strategic`` (qui porte
le trou de chaque arbre) : distance case-axe sur toutes les polylignes
(retombée 0,5, green 2,0), corridors ``m = 5`` des autres trous, passage
libre ≥ 6 sur coupes échantillonnées (coupes tournantes aux coudes), zone
à plateau / 2, formule ``d = max(h − e + 3 ; R_c + 0,5 ; 6 − h + R_c)``
(``e = 3``) retrouvée sur une grille d'abscisses, paires à ``zone ± 4`` du
même côté, arbre de green du côté sans bunker (côté tiré sinon), quota
``round(éligibles / 3)`` sur un ordre de visite retiré ici. Zones et
plateaux relus par ``landing_zones`` et le flux du fairway, comme l'étude.

Limite d'indépendance connue : le corridor ``m = 5`` (lisière, remplissage,
autres trous des couches stratégiques) et le cœur ``m = 0`` sont tracés
avec ``golfgen.routing.geometry.buffered_axis``, la fonction qu'emploie
aussi la production ; seul le test des cases (centre dans le polygone) est
écrit ici.

L'oracle doit échouer : mutations des données (arbre déplacé, doublé,
rayon faux…) puis du code de production (règle retirée par
``monkeypatch``, annulée à la fin du test).

Corpus : ``tests.paths_corpus.ensure_corpus`` avec ``--trees-debug``, dans le
cache des arbres (``golfgen-trees-corpus-<empreinte>``). Rapide :
``ORACLE_FAST`` ; les 10 seeds de l'étude du lot 5 × 2 styles avec
``--run-slow``.
"""

from __future__ import annotations

from collections import Counter
import copy
from dataclasses import replace
import math

import numpy as np
import pytest

from golfgen.dressing.fairway import FAIRWAY_STYLES, Axis, landing_zones, profile_draws
from golfgen.dressing.from_json import course_input_from_json
from golfgen.dressing.paths.scene import scene_from_json
from golfgen.dressing.rng import fairway_rng
from golfgen.dressing.trees import course as ct
from golfgen.dressing.trees import anchors as an
from golfgen.dressing.trees import fill as fl
from golfgen.dressing.trees import geometry as geo
from golfgen.dressing.trees import strategic as sg
from golfgen.dressing.trees import place_trees
from golfgen.dressing.water import AREA_NOISE
from golfgen.exporter import with_trees
from golfgen.routing.geometry import buffered_axis
from golfgen.terrain import relief_from_f32_block
from tests.paths_corpus import corpus_json, ensure_corpus, source_fingerprint

CACHE_KEY = f"golfgen-trees-corpus-{source_fingerprint()}"
EXTRA = ("--trees-debug",)
ORACLE_FAST = ((28399, "parkland"), (11675, "links"), (85660, "links"))
STUDY_SEEDS = (28399, 24055, 83916, 85660, 97579, 35483, 89144, 55435, 11675, 50140)
ORACLE_ALL = tuple(dict.fromkeys(ORACLE_FAST + tuple((s, st) for s in STUDY_SEEDS for st in ("parkland", "links"))))
MUTATION_COURSES = ORACLE_FAST[:2]

# définitions recopiées, pas importées
APRON, REACH, ALLOWED_RADII, STRATEGIC_RADIUS, CORRIDOR = 3, 8.0, {2, 3, 4}, 3, 5.0
EDGE = {"parkland": 12, "links": 0}
STREAM_LABEL, ANCHOR_LAYER = 0x54524532, 3
LAYER_ORDER = ("retombee", "green", "ancrage", "lisiere", "remplissage")
SEGMENT_STEP = 0.02
RULES = ("hors_carte", "eau", "bunkers", "chemins", "parvis", "emprise", "abords", "corridor", "coeur", "disjoint",
         "rayon", "couche", "lisiere", "ancrage", "portee", "segment", "tirage", "compteurs")

# oracle stratégique : définitions de l'étude, recopiées
LANDING_LAYER, GREEN_LAYER, USE_ORDER, USE_HOLE = 1, 2, 1, 2
ENCROACHMENT = 3.0          # e de la production
CROWN = STRATEGIC_RADIUS
R_C = math.hypot(3.5, 0.5)  # couronne réelle
AXIS_GAP, LANDING_AXIS_MARGIN = 2.0, 0.5    # blocs : green, retombée
PASSAGE = 6.0
TWIN_HALF = 4.0             # blocs : paire à zone ± 4
QUOTA = 3
SECTION_STEP, SECTION_REACH = 0.1, 18.0
SAMPLE_STEP, SAMPLE_SPAN, SAMPLE_TOLERANCE = 0.05, 25.0, 0.11
AXIS_SAMPLE, AXIS_TOLERANCE = 0.02, 0.02
SECTOR_LOW, SECTOR_HIGH = 45.0, 135.0
WEDGE_STEP = 2.0            # degrés entre deux coupes tournantes autour d'un coude
FORMULA_STEP, FORMULA_REACH = 0.05, 30.0
STRATEGIC_RULES = ("axe", "autres_corridors", "passage", "zone", "formule_d", "paire", "cote_retombee",
                   "cote_green", "quota")


# === Géométrie écrite ici ===

def _disc(r: int) -> list[tuple[int, int]]:
    return [(dx, dy) for dy in range(-r, r + 1) for dx in range(-r, r + 1) if dx * dx + dy * dy <= r * r]


def _polyline(hole) -> np.ndarray:
    return np.asarray([(p["x"], p["y"]) for p in [hole["tee"], *hole["doglegs"], hole["green"]]], dtype=float)


def _inside(points: np.ndarray, polygon) -> np.ndarray:
    poly = np.asarray(polygon, dtype=float)
    x, y = points[:, 0], points[:, 1]
    inside = np.zeros(len(points), dtype=bool)
    for (ax, ay), (bx, by) in zip(poly, np.roll(poly, -1, axis=0)):
        with np.errstate(divide="ignore", invalid="ignore"):
            inside ^= ((ay > y) != (by > y)) & (x < ax + (y - ay) * (bx - ax) / (by - ay))
    return inside


def _clip_area(polygon: np.ndarray, ix: int, iy: int) -> float:
    """Aire commune du polygone et de la case ``[ix, ix+1] × [iy, iy+1]``
    (Sutherland-Hodgman)."""
    def clip(points, inside, intersect):
        result = []
        for i, current in enumerate(points):
            previous = points[i - 1]
            if inside(current):
                if not inside(previous):
                    result.append(intersect(previous, current))
                result.append(current)
            elif inside(previous):
                result.append(intersect(previous, current))
        return result

    def at_x(c):
        return lambda p, q: (c, p[1] + (c - p[0]) * (q[1] - p[1]) / (q[0] - p[0]))

    def at_y(c):
        return lambda p, q: (p[0] + (c - p[1]) * (q[0] - p[0]) / (q[1] - p[1]), c)

    points = [tuple(p) for p in polygon.tolist()]
    for inside, intersect in ((lambda p: p[0] >= ix, at_x(ix)), (lambda p: p[0] <= ix + 1, at_x(ix + 1)),
                              (lambda p: p[1] >= iy, at_y(iy)), (lambda p: p[1] <= iy + 1, at_y(iy + 1))):
        points = clip(points, inside, intersect)
        if not points:
            return 0.0
    return abs(sum(a[0] * b[1] - b[0] * a[1] for a, b in zip(points, points[1:] + points[:1]))) / 2.0


def _surfaces(course):
    """Contours des greens (doubles compris) et des départs."""
    pairs = course["routing"].get("green_pairs") or []
    paired = {hole_id for pair in pairs for hole_id in pair["holes"]}
    for hole in course["routing"]["holes"]:
        if hole["id"] not in paired:
            yield np.asarray([(p["x"], p["y"]) for p in hole["features"]["green"]["outline"]], dtype=float)
        for tee in hole["features"]["tees"]:
            yield np.asarray([(p["x"], p["y"]) for p in tee["outline"]], dtype=float)
    for pair in pairs:
        yield np.asarray([(p["x"], p["y"]) for p in pair["outline"]], dtype=float)


def build_ground(course: dict) -> dict:
    """Terrain relu dans le JSON, sans le code de placement."""
    terrain = course["terrain"]
    width, height = terrain["width"], terrain["height"]
    relief = relief_from_f32_block(terrain["elevation_f32"], width, height)
    grids = {name: np.zeros((height, width), dtype=bool) for name in ("bunkers", "chemins", "parvis", "emprise", "abords")}
    for item in course["bunkers"]["items"]:
        for x, z in item["cells"]:
            grids["bunkers"][z, x] = True
    for x, z in course["paths"]["cells"]:
        grids["chemins"][z, x] = True
    for x, z in course["paths"].get("plaza", {}).get("cells", []):
        grids["parvis"][z, x] = True
    for polygon in _surfaces(course):
        for y in range(max(int(polygon[:, 1].min()) - 1, 0), min(int(polygon[:, 1].max()) + 2, height)):
            for x in range(max(int(polygon[:, 0].min()) - 1, 0), min(int(polygon[:, 0].max()) + 2, width)):
                if _clip_area(polygon, x, y) > AREA_NOISE:
                    grids["emprise"][y, x] = True
    for y, x in np.argwhere(grids["emprise"]).tolist():
        for dx, dy in _disc(APRON):
            if 0 <= x + dx < width and 0 <= y + dy < height:
                grids["abords"][y + dy, x + dx] = True
    ys, xs = np.mgrid[0:height, 0:width]
    centres = np.column_stack((xs.ravel() + 0.5, ys.ravel() + 0.5))
    corridor, core = np.zeros(len(centres), dtype=bool), np.zeros(len(centres), dtype=bool)
    for hole in course["routing"]["holes"]:
        axis = tuple(map(tuple, _polyline(hole)))
        corridor |= _inside(centres, buffered_axis(axis, hole["width"] / 2.0 + CORRIDOR))
        core |= _inside(centres, buffered_axis(axis, hole["width"] / 2.0))
    return {"width": width, "height": height, "seed": int(course["metadata"]["seed"]),
            "edge": EDGE[course["metadata"]["style"]],
            "water": ~(relief >= terrain["water_level"]), **grids,
            "corridor": corridor.reshape(height, width), "core": core.reshape(height, width),
            "anchors": [tuple(a) for a in course["paths"]["anchors"]]}


def _segment_hits_path(a, b, paths: np.ndarray) -> bool:
    steps = max(1, int(math.dist(a, b) / SEGMENT_STEP))
    for k in range(steps + 1):
        x = int(math.floor(a[0] + (b[0] - a[0]) * k / steps))
        y = int(math.floor(a[1] + (b[1] - a[1]) * k / steps))
        if 0 <= y < paths.shape[0] and 0 <= x < paths.shape[1] and paths[y, x]:
            return True
    return False


# === Oracle ===

def oracle(ground: dict, trees: dict) -> dict[str, int]:
    """Infractions par règle sur la section ``trees`` d'un JSON 3.4 (avec
    ``trees.debug``)."""
    width, height, edge = ground["width"], ground["height"], ground["edge"]
    found = {rule: 0 for rule in RULES}
    table: dict[tuple[int, int], tuple] = {}
    items = trees["items"]
    ranks = [LAYER_ORDER.index(item["layer"]) if item["layer"] in LAYER_ORDER else -1 for item in items]
    found["couche"] += sum(1 for rank in ranks if rank < 0) + sum(1 for a, b in zip(ranks, ranks[1:]) if b < a)
    for item in items:
        x, y, r, layer = item["x"], item["z"], item["radius"], item["layer"]
        strategic = layer in ("retombee", "green")
        if ("grove" in item) != (layer == "ancrage"):
            found["couche"] += 1
        if r not in ALLOWED_RADII or (strategic and r != STRATEGIC_RADIUS):
            found["rayon"] += 1
        if layer == "lisiere" and not (x < edge or y < edge or x >= width - edge or y >= height - edge):
            found["lisiere"] += 1
        for dx, dy in _disc(r):
            cx, cy = x + dx, y + dy
            if not (0 <= cx < width and 0 <= cy < height):
                found["hors_carte"] += 1
                continue
            if (cx, cy) in table:
                found["disjoint"] += 1
            table[(cx, cy)] = (x, y)
            for rule, grid in (("eau", ground["water"]), ("bunkers", ground["bunkers"]), ("chemins", ground["chemins"]),
                               ("parvis", ground["parvis"]), ("emprise", ground["emprise"])):
                found[rule] += int(grid[cy, cx])
            if not strategic:
                found["abords"] += int(ground["abords"][cy, cx])
            if layer in ("lisiere", "remplissage"):
                found["corridor"] += int(ground["corridor"][cy, cx])
            if layer == "ancrage":
                found["coeur"] += int(ground["core"][cy, cx])

    debug = trees["debug"]
    if debug["counts"] != {name: sum(1 for item in items if item["layer"] == name) for name in LAYER_ORDER}:
        found["compteurs"] += 1
    groves = debug["groves"]
    if [tuple(g["anchor"]) for g in groves] != ground["anchors"] or [g["index"] for g in groves] != list(range(len(groves))):
        found["ancrage"] += 1
    by_grove: dict[int, list] = {}
    for item in items:
        if item["layer"] == "ancrage":
            by_grove.setdefault(item.get("grove"), []).append([item["x"], item["z"], item["radius"]])
    if set(by_grove) - set(range(len(groves))):
        found["ancrage"] += 1
    for index, grove in enumerate(groves):
        expected = np.random.default_rng([ground["seed"], STREAM_LABEL, ANCHOR_LAYER, index]).integers(1, 4)
        if grove["target"] != int(expected):
            found["tirage"] += 1
        placed, motif, target = grove["trees"], grove["motif"], grove["target"]
        if (motif is None and len(placed) != target) or (motif == "partiel" and not 0 < len(placed) < target) \
                or (motif == "sans_place" and placed) or motif not in (None, "partiel", "sans_place") \
                or grove["placed"] != len(placed) or placed != by_grove.get(index, []):
            found["ancrage"] += 1
        ax, az = grove["anchor"]
        for x, y, _ in placed:
            if math.hypot(x - ax, y - az) > REACH:
                found["portee"] += 1
            if _segment_hits_path((ax + 0.5, az + 0.5), (x + 0.5, y + 0.5), ground["chemins"]):
                found["segment"] += 1
    return found


def violations(found: dict) -> dict:
    return {rule: count for rule, count in found.items() if count}


# === Oracle stratégique (porté de l'étude) ===

def _crown_of(tree) -> list[tuple[int, int]]:
    return [(tree[0] + dx, tree[1] + dy) for dx, dy in _disc(CROWN)]


def _unit(vector) -> np.ndarray:
    return vector / float(np.hypot(*vector))


def _axis_samples(points: np.ndarray) -> np.ndarray:
    """Points de la polyligne tous les ``AXIS_SAMPLE`` blocs au plus."""
    return np.concatenate([a + np.linspace(0.0, 1.0, int(math.dist(a, b) / AXIS_SAMPLE) + 2)[:, None] * (b - a)
                           for a, b in zip(points, points[1:])])


def _axis_distance(cells, samples: np.ndarray) -> float:
    """Distance la plus courte entre les cases ``cells`` et la polyligne échantillonnée."""
    corner = np.asarray(cells, dtype=float)
    qx = np.clip(samples[None, :, 0], corner[:, 0:1], corner[:, 0:1] + 1.0)
    qy = np.clip(samples[None, :, 1], corner[:, 1:2], corner[:, 1:2] + 1.0)
    return float(np.hypot(samples[None, :, 0] - qx, samples[None, :, 1] - qy).min())


def _nearest_side(cell, points: np.ndarray) -> int:
    """Côté (+1 gauche, -1 droite) du centre de ``cell`` par rapport au
    segment le plus proche de la polyligne."""
    px, py = cell[0] + 0.5, cell[1] + 0.5
    best, side = math.inf, 0
    for a, b in zip(points, points[1:]):
        length = float(np.hypot(*(b - a)))
        ux, uy = (b - a) / length
        t = max(0.0, min(length, (px - a[0]) * ux + (py - a[1]) * uy))
        distance = math.hypot(px - (a[0] + t * ux), py - (a[1] + t * uy))
        if distance < best:
            best = distance
            side = 1 if ux * (py - a[1]) - uy * (px - a[0]) > 0.0 else -1
    return side


def _flank(cell, flag, approach) -> tuple[int, float]:
    """Côté et angle (degrés, 0–180) du centre de ``cell`` depuis le drapeau."""
    vx, vy = cell[0] + 0.5 - flag[0], cell[1] + 0.5 - flag[1]
    angle = math.degrees(math.atan2(abs(approach[0] * vy - approach[1] * vx), approach[0] * vx + approach[1] * vy))
    return (1 if approach[0] * vy - approach[1] * vx > 0.0 else -1), angle


def _approach(hole) -> tuple[np.ndarray, np.ndarray]:
    polyline = _polyline(hole)
    return polyline[-1], _unit(polyline[-1] - polyline[-2])


def _bunker_flanks(course, order, flag, approach) -> set[int]:
    """Côtés portant une case ``role = green`` du green du trou ``order``
    (green double : bunkers des deux trous)."""
    group = {order}
    for pair in course["routing"].get("green_pairs") or []:
        if order in pair["holes"]:
            group |= set(pair["holes"])
    sides = set()
    for item in course["bunkers"]["items"]:
        if item["role"] == "green" and item["hole"] in group:
            for cell in item["cells"]:
                side, angle = _flank(cell, flag, approach)
                if SECTOR_LOW <= angle <= SECTOR_HIGH:
                    sides.add(side)
    return sides


def _fairway_pieces(hole) -> list[np.ndarray]:
    return [np.asarray([(p["x"], p["y"]) for p in piece["outline"]], dtype=float)
            for piece in hole["features"].get("fairway") or []]


def _sections(points: np.ndarray):
    """Abscisses ``0, SECTION_STEP, …`` : ``(point, normale)``, le segment
    suivant à un coude."""
    lengths = np.hypot(*np.diff(points, axis=0).T)
    starts = np.concatenate(([0.0], np.cumsum(lengths)))
    for k in range(int(math.ceil(starts[-1] / SECTION_STEP)) + 1):
        s = min(k * SECTION_STEP, starts[-1])
        segment = min(int(np.searchsorted(starts, s, side="right")) - 1, len(lengths) - 1)
        u = (points[segment + 1] - points[segment]) / lengths[segment]
        yield points[segment] + (s - starts[segment]) * u, np.array((-u[1], u[0]))


def _section_lines(points: np.ndarray):
    """Coupes perpendiculaires, plus, à chaque coude, des coupes tournantes
    qui balaient le secteur extérieur entre les normales des deux segments."""
    yield from _sections(points)
    for before, corner, after in zip(points, points[1:], points[2:]):
        u, v = _unit(corner - before), _unit(after - corner)
        first = math.atan2(u[0], -u[1])
        delta = (math.atan2(v[0], -v[1]) - first + math.pi) % (2.0 * math.pi) - math.pi
        count = max(int(math.ceil(abs(math.degrees(delta)) / WEDGE_STEP)), 1)
        for k in range(1, count):
            angle = first + delta * k / count
            yield corner, np.array((math.cos(angle), math.sin(angle)))


def _runs(flags: np.ndarray) -> list[tuple[int, int]]:
    """Intervalles ``[début, fin]`` (bornes incluses) des valeurs vraies."""
    edges = np.flatnonzero(np.diff(np.concatenate(([False], flags, [False])).astype(np.int8)))
    return [(int(edges[k]), int(edges[k + 1]) - 1) for k in range(0, len(edges), 2)]


def _passage_violations(points: np.ndarray, pieces, crown_cells: set, centres: np.ndarray) -> int:
    """Coupes dont le fairway, entamé par une couronne, garde moins de
    ``PASSAGE`` blocs libres : autour de l'axe s'il est sur le fairway, sinon
    plus long tronçon libre de chaque morceau entamé."""
    found = 0
    t = np.arange(-SAMPLE_SPAN, SAMPLE_SPAN + SAMPLE_STEP / 2.0, SAMPLE_STEP)
    centre = int(np.argmin(np.abs(t)))
    limit = PASSAGE - SAMPLE_TOLERANCE
    for point, normal in _section_lines(points):
        if not (((centres - point) ** 2).sum(axis=1) <= SECTION_REACH ** 2).any():
            continue
        samples = point + t[:, None] * normal
        on_fairway = np.zeros(len(t), dtype=bool)
        for piece in pieces:
            on_fairway |= _inside(samples, piece)
        if not on_fairway.any():
            continue
        blocked = np.zeros(len(t), dtype=bool)
        for k in np.flatnonzero(on_fairway):
            blocked[k] = (int(math.floor(samples[k, 0])), int(math.floor(samples[k, 1]))) in crown_cells
        if on_fairway[centre]:
            left, right = next((a, b) for a, b in _runs(on_fairway) if a <= centre <= b)
            if blocked[left:right + 1].any():
                free = next(((b - a) * SAMPLE_STEP for a, b in _runs(~blocked[left:right + 1])
                             if a <= centre - left <= b), 0.0)
                found += int(free < limit)
        else:
            for a, b in _runs(on_fairway):
                if blocked[a:b + 1].any():
                    longest = max(((d - c) * SAMPLE_STEP for c, d in _runs(~blocked[a:b + 1])), default=0.0)
                    found += int(longest < limit)
    return found


def _landing_targets(course) -> dict[int, tuple[float, float]]:
    """Zone (la plus proche de ``draws["drive"]``) et plateau par trou,
    recalculés depuis le JSON et le flux du fairway ; trous sans zone absents."""
    data = course_input_from_json(course)
    style = FAIRWAY_STYLES[course["metadata"]["style"]]
    targets = {}
    for hole in data.layout.holes:
        draws = profile_draws(fairway_rng(data.seed, hole.order), style)
        zones = landing_zones(Axis.of(hole), hole.par, draws)
        if zones:
            index = min(range(len(zones)), key=lambda k: abs(zones[k] - draws["drive"]))
            targets[hole.order] = (float(zones[index]), float(draws["plateau"][index]))
    return targets


def _first_crossing(polygon: np.ndarray, point, direction) -> float | None:
    """Première traversée du bord le long de la demi-droite, ou ``None``."""
    a, b = polygon, np.roll(polygon, -1, axis=0)
    edge_x, edge_y = b[:, 0] - a[:, 0], b[:, 1] - a[:, 1]
    to_x, to_y = a[:, 0] - point[0], a[:, 1] - point[1]
    denom = direction[0] * edge_y - direction[1] * edge_x
    with np.errstate(divide="ignore", invalid="ignore"):
        along = (to_x * edge_y - to_y * edge_x) / denom
        on_edge = (to_x * direction[1] - to_y * direction[0]) / denom
    hits = along[(denom != 0.0) & (on_edge >= 0.0) & (on_edge < 1.0) & (along > 1e-9)]
    return float(hits.min()) if len(hits) else None


def _at(points: np.ndarray, starts: np.ndarray, lengths: np.ndarray, s: float):
    segment = min(int(np.searchsorted(starts, s, side="right")) - 1, len(lengths) - 1)
    u = (points[segment + 1] - points[segment]) / lengths[segment]
    return points[segment] + (s - starts[segment]) * u, np.array((-u[1], u[0]))


def _expected_cells(points, pieces, s: float, e: float = ENCROACHMENT) -> list[tuple[int, int]]:
    """Cases d'un arbre de retombée à l'abscisse ``s`` selon la formule
    ``d = max(h - e + 3 ; R_c + 0,5 ; 6 - h + R_c)``, de chaque côté où ``h``
    est mesurable."""
    lengths = np.hypot(*np.diff(points, axis=0).T)
    starts = np.concatenate(([0.0], np.cumsum(lengths)[:-1]))
    point, normal = _at(points, starts, lengths, s)
    piece = next((p for p in pieces if _inside(point[None], p)[0]), None)
    if piece is None:
        return []
    cells = []
    for side in (1.0, -1.0):
        direction = normal * side
        half = _first_crossing(piece, point, direction)
        if half is not None:
            offset = max(half - e + CROWN, R_C + LANDING_AXIS_MARGIN, PASSAGE - half + R_C)
            target = point + offset * direction
            cells.append((int(math.floor(target[0])), int(math.floor(target[1]))))
    return cells


def _matching_stations(points, pieces, zone: float, tree, e: float = ENCROACHMENT) -> list[float]:
    """Abscisses (grille ``zone + k × FORMULA_STEP``) dont la formule redonne
    exactement la case ``tree``."""
    lengths = np.hypot(*np.diff(points, axis=0).T)
    starts = np.concatenate(([0.0], np.cumsum(lengths)[:-1]))
    length = float(lengths.sum())
    centre = np.array((tree[0] + 0.5, tree[1] + 0.5))
    matches = []
    for k in range(-int((zone + 1.0) / FORMULA_STEP), int((length - zone + 1.0) / FORMULA_STEP) + 1):
        s = zone + k * FORMULA_STEP
        if not 0.0 <= s <= length:
            continue
        point, _ = _at(points, starts, lengths, s)
        if float(np.hypot(*(point - centre))) > FORMULA_REACH:
            continue
        if tree in _expected_cells(points, pieces, s, e):
            matches.append(s)
    return matches


def _visit(seed: int, layer: int, eligible: list[int]) -> list[int]:
    """Ordre de visite d'une couche, retiré ici (flux « TRE2 »)."""
    return [int(o) for o in np.random.default_rng([seed, STREAM_LABEL, layer, USE_ORDER]).permutation(eligible)]


def _quota_violations(seed: int, layer: int, eligible: list[int], placed: list[int], skipped: int) -> int:
    """Trous posés (ordre de pose) dans l'ordre de visite rejoué, arrêt au
    quota ``round(éligibles / 3)`` ou à la fin de la liste."""
    quota = round(len(eligible) / QUOTA)
    visited = len(placed) + skipped
    seen = _visit(seed, layer, eligible)[:visited]
    ok = (len(placed) <= quota and visited <= len(eligible) and len(set(placed)) == len(placed)
          and placed == [order for order in seen if order in placed])
    ok = ok and ((len(placed) == quota and (visited == 0 or seen[-1] in placed))
                 or (len(placed) < quota and visited == len(eligible)))
    return int(not ok)


def strategic_view(placed) -> dict:
    """Vue d'un ``StrategicTrees`` : arbres par trou dans l'ordre de pose,
    trous sautés par couche."""
    view = {"retombee": {}, "green": {}}
    for key, layer in (("retombee", placed.landing), ("green", placed.green)):
        for tree in layer.trees:
            view[key].setdefault(tree.hole, []).append((tree.x, tree.z))
    view["skips"] = {"retombee": sum(placed.landing.skips.values()), "green": sum(placed.green.skips.values())}
    return view


def strategic_oracle(course: dict, view: dict, rules=None) -> dict[str, int]:
    """Infractions par règle des couches stratégiques ``view``
    (``strategic_view``), relues dans le JSON ``course``. ``rules`` : règles
    à contrôler (toutes si ``None``)."""
    selected = set(STRATEGIC_RULES if rules is None else rules)
    found = {rule: 0 for rule in selected}
    holes = {hole["id"]: hole for hole in course["routing"]["holes"]}
    seed = int(course["metadata"]["seed"])
    landing, green = view["retombee"], view["green"]
    trees = [(order, tuple(tree), LANDING_AXIS_MARGIN) for order, cells in landing.items() for tree in cells]
    trees += [(order, tuple(tree), AXIS_GAP) for order, cells in green.items() for tree in cells]

    if "axe" in selected:
        samples = {order: _axis_samples(_polyline(hole)) for order, hole in holes.items()}
        for _, tree, gap in trees:
            cells = _crown_of(tree)
            found["axe"] += sum(1 for line in samples.values() if _axis_distance(cells, line) < gap - AXIS_TOLERANCE)

    if "autres_corridors" in selected:
        polygons = {order: buffered_axis(tuple(map(tuple, _polyline(hole))), hole["width"] / 2.0 + CORRIDOR)
                    for order, hole in holes.items()}
        for order, tree, _ in trees:
            centres = np.asarray(_crown_of(tree), dtype=float) + 0.5
            found["autres_corridors"] += sum(int(np.count_nonzero(_inside(centres, polygon)))
                                             for other, polygon in polygons.items() if other != order)

    if "passage" in selected:
        for order, cells in landing.items():
            crowns = {cell for tree in [*cells, *green.get(order, [])] for cell in _crown_of(tuple(tree))}
            centres = np.asarray(cells, dtype=float) + 0.5
            found["passage"] += _passage_violations(_polyline(holes[order]), _fairway_pieces(holes[order]),
                                                    crowns, centres)

    if {"zone", "formule_d", "paire"} & selected and landing:
        targets = _landing_targets(course)
        for order, cells in landing.items():
            if order not in targets:
                found.update({rule: found[rule] + 1 for rule in ("zone", "formule_d") if rule in selected})
                continue
            points, pieces = _polyline(holes[order]), _fairway_pieces(holes[order])
            zone, plateau = targets[order]
            for tree in map(tuple, cells) if {"zone", "formule_d"} & selected else ():
                stations = _matching_stations(points, pieces, zone, tree)
                if "formule_d" in selected and not stations:
                    found["formule_d"] += 1
                if "zone" in selected and stations and min(abs(s - zone) for s in stations) > plateau / 2.0 + 1e-9:
                    found["zone"] += 1
            if "paire" in selected and len(cells) > 1:
                found["paire"] += int(len(cells) != 2
                                      or tuple(cells[0]) not in _expected_cells(points, pieces, zone - TWIN_HALF)
                                      or tuple(cells[1]) not in _expected_cells(points, pieces, zone + TWIN_HALF))

    if "cote_retombee" in selected:
        for order, cells in landing.items():
            found["cote_retombee"] += int(len({_nearest_side(tuple(tree), _polyline(holes[order]))
                                               for tree in cells}) > 1)

    if "cote_green" in selected:
        for order, cells in green.items():
            flag, approach = _approach(holes[order])
            flanks = _bunker_flanks(course, order, flag, approach)
            if len(flanks) == 1:
                expected = -next(iter(flanks))
            elif flanks:
                expected = 0        # bunkers des deux côtés : aucun arbre attendu
            else:
                rng = np.random.default_rng([seed, STREAM_LABEL, GREEN_LAYER, USE_HOLE, order])
                expected = 1 if rng.random() < 0.5 else -1
            for tree in cells:
                side, angle = _flank(tuple(tree), flag, approach)
                found["cote_green"] += int(side != expected or not SECTOR_LOW <= angle <= SECTOR_HIGH)

    if "quota" in selected:
        par45 = sorted(order for order, hole in holes.items() if hole["par"] in (4, 5))
        found["quota"] += sum(1 for order, cells in landing.items() if order not in par45 or not 1 <= len(cells) <= 2)
        found["quota"] += sum(1 for cells in green.values() if len(cells) != 1)
        found["quota"] += _quota_violations(seed, LANDING_LAYER, par45, list(landing), view["skips"]["retombee"])
        found["quota"] += _quota_violations(seed, GREEN_LAYER, sorted(holes), list(green), view["skips"]["green"])
    return found


# === Corpus ===

@pytest.fixture(scope="module")
def oracle_corpus_dir(request):
    path = request.config.cache.mkdir(CACHE_KEY)
    ensure_corpus(path, ORACLE_ALL if request.config.getoption("--run-slow") else ORACLE_FAST, extra=EXTRA)
    return path


def _replay(course: dict) -> dict:
    """Section ``trees`` rejouée depuis le JSON par la production."""
    base = {key: value for key, value in course.items() if key != "trees"}
    return with_trees(base, place_trees(base), debug=True)["trees"]


@pytest.mark.parametrize("seed, style", [pytest.param(*c, id=f"{c[1]}_{c[0]}",
                                                      marks=() if c in ORACLE_FAST else pytest.mark.slow)
                                         for c in ORACLE_ALL])
def test_real_output_has_no_violation(seed, style, oracle_corpus_dir):
    course = corpus_json(oracle_corpus_dir, seed, style, extra=EXTRA)
    assert course["metadata"]["version"] == "3.4" and course["trees"]["items"]
    assert violations(oracle(build_ground(course), course["trees"])) == {}


def _strategic_inputs(course: dict):
    """JSON sans arbres, modèle et interdits : les entrées de ``place_strategic``."""
    base = {key: value for key, value in course.items() if key != "trees"}
    return base, course_input_from_json(base), geo.forbidden_masks(base, scene_from_json(base))


def _json_strategic(course: dict) -> list[tuple]:
    return [(item["layer"], item["x"], item["z"]) for item in course["trees"]["items"]
            if item["layer"] in ("retombee", "green")]


@pytest.mark.parametrize("seed, style", [pytest.param(*c, id=f"{c[1]}_{c[0]}",
                                                      marks=() if c in ORACLE_FAST else pytest.mark.slow)
                                         for c in ORACLE_ALL])
def test_strategic_output_has_no_violation(seed, style, oracle_corpus_dir):
    """Sortie en mémoire de ``place_strategic`` (trou de chaque arbre), égale
    aux couches stratégiques du JSON, contrôlée par l'oracle de l'étude."""
    course = corpus_json(oracle_corpus_dir, seed, style, extra=EXTRA)
    placed = sg.place_strategic(*_strategic_inputs(course))
    assert [(t.layer, t.x, t.z) for t in placed.trees] == _json_strategic(course)
    assert placed.trees
    assert violations(strategic_oracle(course, strategic_view(placed))) == {}


@pytest.fixture(scope="module", params=MUTATION_COURSES, ids=lambda c: f"{c[1]}_{c[0]}")
def course(request, oracle_corpus_dir):
    return corpus_json(oracle_corpus_dir, *request.param, extra=EXTRA)


@pytest.fixture(scope="module")
def ground(course):
    return build_ground(course)


@pytest.fixture(scope="module")
def trees(course):
    return course["trees"]


def test_replay_from_the_json_gives_the_pipeline_trees(course, trees):
    assert _replay(course) == trees


def test_links_has_no_edge(course, trees):
    if course["metadata"]["style"] != "links":
        pytest.skip("parkland")
    assert not any(item["layer"] == "lisiere" for item in trees["items"])


@pytest.mark.parametrize("layer", ["remplissage", "lisiere"])
def test_placed_radii_are_near_50_37_12_with_a_tail_of_2(trees, layer):
    """Répartition POSÉE (tirage 30/50/20, queue de 2) : bornes larges, une seule seed."""
    radii = [item["radius"] for item in trees["items"] if item["layer"] == layer]
    if not radii:
        pytest.skip("couche vide (links : pas de lisière)")
    shares = {r: radii.count(r) / len(radii) for r in sorted(ALLOWED_RADII)}
    assert 0.38 <= shares[2] <= 0.62 and 0.25 <= shares[3] <= 0.50 and 0.04 <= shares[4] <= 0.22, shares
    start = max(i for i, r in enumerate(radii) if r >= 3) + 1
    assert 0.10 <= (len(radii) - start) / len(radii) <= 0.45


# --- Mutations des données : détectées, puis l'original reste propre ---

def _first_cell(mask: np.ndarray, margin: int = 0) -> tuple[int, int]:
    height, width = mask.shape
    for y, x in np.argwhere(mask).tolist():
        if margin <= x < width - margin and margin <= y < height - margin:
            return x, y
    pytest.skip("aucune case disponible")


def _index_in(trees: dict, *layers: str) -> int:
    for layer in layers:
        for index, item in enumerate(trees["items"]):
            if item["layer"] == layer:
                return index
    pytest.skip(f"aucun arbre de {layers}")


def _moved(trees: dict, index: int, cell: tuple[int, int]) -> dict:
    mutated = copy.deepcopy(trees)
    item = mutated["items"][index]
    if item["layer"] == "ancrage":
        grove = mutated["debug"]["groves"][item["grove"]]
        grove["trees"][grove["trees"].index([item["x"], item["z"], item["radius"]])][:2] = list(cell)
    item["x"], item["z"] = cell
    return mutated


@pytest.mark.parametrize("rule, grid", [("eau", "water"), ("bunkers", "bunkers"), ("chemins", "chemins"),
                                        ("parvis", "parvis"), ("emprise", "emprise"), ("abords", "abords"),
                                        ("corridor", "corridor")])
def test_oracle_catches_a_tree_on_forbidden_ground(ground, trees, rule, grid):
    if not ground[grid].any():
        pytest.skip(f"rien pour {rule}")
    mutated = _moved(trees, _index_in(trees, "remplissage", "lisiere"), _first_cell(ground[grid], 5))
    assert oracle(ground, mutated)[rule] > 0
    assert violations(oracle(ground, trees)) == {}


def test_oracle_catches_off_map_and_overlap_and_bad_radius(ground, trees):
    index = _index_in(trees, "remplissage", "lisiere")
    assert oracle(ground, _moved(trees, index, (0, 0)))["hors_carte"] > 0
    doubled = copy.deepcopy(trees)
    doubled["items"].append(dict(doubled["items"][index]))
    assert oracle(ground, doubled)["disjoint"] > 0
    wide = copy.deepcopy(trees)
    wide["items"][index]["radius"] = 5
    assert oracle(ground, wide)["rayon"] > 0
    small = copy.deepcopy(trees)
    small["items"][_index_in(trees, "retombee", "green")]["radius"] = 2
    assert oracle(ground, small)["rayon"] > 0


def test_oracle_catches_bad_layers_and_counters(ground, trees):
    unknown = copy.deepcopy(trees)
    unknown["items"][_index_in(trees, "remplissage")]["layer"] = "foret"
    assert oracle(ground, unknown)["couche"] > 0
    swapped = copy.deepcopy(trees)
    swapped["items"].insert(0, swapped["items"].pop(_index_in(trees, "remplissage")))
    assert oracle(ground, swapped)["couche"] > 0
    stray = copy.deepcopy(trees)
    stray["items"][_index_in(trees, "remplissage")]["grove"] = 0
    assert oracle(ground, stray)["couche"] > 0
    counted = copy.deepcopy(trees)
    counted["debug"]["counts"]["remplissage"] += 1
    assert oracle(ground, counted)["compteurs"] > 0


def test_oracle_catches_an_edge_tree_away_from_the_rim(ground, trees):
    centre = (ground["width"] // 2, ground["height"] // 2)
    mutated = copy.deepcopy(trees)
    index = _index_in(trees, "remplissage")
    mutated["items"][index]["layer"] = "lisiere"
    mutated["items"].append(mutated["items"].pop(index))
    mutated["items"][-1]["x"], mutated["items"][-1]["z"] = centre
    assert oracle(ground, mutated)["lisiere"] > 0


def test_oracle_catches_an_anchor_tree_in_the_core(ground, trees):
    mutated = _moved(trees, _index_in(trees, "ancrage"), _first_cell(ground["core"], 5))
    assert oracle(ground, mutated)["coeur"] > 0


def test_oracle_lets_an_anchor_tree_enter_the_corridor(ground, trees):
    """Exemption validée : pas de faux positif ``corridor`` pour un ancrage hors cœur."""
    mutated = _moved(trees, _index_in(trees, "ancrage"), _first_cell(ground["corridor"] & ~ground["core"], 5))
    assert oracle(ground, mutated)["corridor"] == 0


def test_oracle_catches_an_anchor_tree_too_far(ground, trees):
    index = _index_in(trees, "ancrage")
    item = trees["items"][index]
    assert oracle(ground, _moved(trees, index, (item["x"] + 20, item["z"])))["portee"] > 0


def test_oracle_catches_an_anchor_tree_behind_a_path(ground, trees):
    """Arbre d'ancrage reflété par une case de chemin proche de l'ancrage : le
    segment depuis l'ancrage traverse le centre de cette case, portée ≤ 8."""
    paths = np.argwhere(ground["chemins"])[:, ::-1]
    for item_index, item in enumerate(trees["items"]):
        if item["layer"] != "ancrage":
            continue
        ax, az = trees["debug"]["groves"][item["grove"]]["anchor"]
        for px, pz in paths.tolist():
            if 1.0 <= math.hypot(px - ax, pz - az) <= REACH / 2.0:
                found = oracle(ground, _moved(trees, item_index, (2 * px - ax, 2 * pz - az)))
                assert found["segment"] > 0 and found["portee"] == 0, found
                return
    pytest.skip("aucune case de chemin à portée d'un ancrage")


def test_oracle_catches_missing_grove_motif_and_draw(ground, trees):
    if not trees["debug"]["groves"]:
        pytest.skip("aucun ancrage")
    mutated = copy.deepcopy(trees)
    mutated["debug"]["groves"].pop()
    assert oracle(ground, mutated)["ancrage"] > 0
    mutated = copy.deepcopy(trees)
    grove = next((g for g in mutated["debug"]["groves"] if g["trees"]), None)
    if grove is None:
        pytest.skip("aucun arbre d'ancrage")
    grove["trees"], grove["placed"], grove["motif"] = [], 0, None
    assert oracle(ground, mutated)["ancrage"] > 0
    mutated = copy.deepcopy(trees)
    mutated["items"] = [item for item in mutated["items"] if item["layer"] != "ancrage"]
    mutated["debug"]["counts"]["ancrage"] = 0
    assert oracle(ground, mutated)["ancrage"] > 0
    mutated = copy.deepcopy(trees)
    mutated["debug"]["groves"][0]["target"] = 4
    assert oracle(ground, mutated)["tirage"] > 0
    assert violations(oracle(ground, trees)) == {}


# --- Mutations du code de production : détectées, puis restaurées ---

def test_mutation_without_crown_check_is_caught(course, ground, trees, monkeypatch):
    def unchecked(cells, solid, crowns, rng, *, radius=None, limit=None, shuffle=True, budget=None):
        """Couronne non testée contre ``solid`` ; la carte reste respectée."""
        height, width = solid.shape
        placed = []
        for k in (rng.permutation(len(cells)) if shuffle else range(len(cells)))[:limit]:
            x, y, r = int(cells[k, 0]), int(cells[k, 1]), fl.draw_radius(rng) if radius is None else radius
            if r <= x < width - r and r <= y < height - r:
                placed.append((x, y, r))
        return placed

    monkeypatch.setattr(ct, "greedy", unchecked)
    monkeypatch.setattr(an, "greedy", unchecked)
    assert oracle(ground, _replay(course))["disjoint"] > 0
    monkeypatch.undo()
    assert _replay(course) == trees


def test_mutation_without_corridor_is_caught(course, ground, monkeypatch):
    original = geo.corridors_mask

    def no_corridor(holes, margin, width, height):
        return np.zeros((height, width), dtype=bool) if margin == geo.CORRIDOR_MARGIN else original(holes, margin, width, height)

    monkeypatch.setattr(geo, "corridors_mask", no_corridor)
    assert oracle(ground, _replay(course))["corridor"] > 0


def test_mutation_without_fixed_forbidden_is_caught(course, ground, monkeypatch):
    original = ct.forbidden_masks

    def no_fixed(data, scene, margin=geo.CORRIDOR_MARGIN):
        masks = original(data, scene, margin)
        empty = np.zeros_like(masks.water)
        return replace(masks, water=empty, obstacles=empty, bunkers=empty, plaza=empty, paths=empty, aprons=empty)

    monkeypatch.setattr(ct, "forbidden_masks", no_fixed)
    found = oracle(ground, _replay(course))
    assert found["emprise"] + found["chemins"] + found["bunkers"] + found["eau"] > 0


def test_mutation_without_core_is_caught_on_links_85660(oracle_corpus_dir, monkeypatch):
    """Parcours choisi : le retrait du cœur y change les ancrages, l'oracle doit le voir."""
    course = corpus_json(oracle_corpus_dir, 85660, "links", extra=EXTRA)
    ground = build_ground(course)
    assert violations(oracle(ground, course["trees"])) == {}
    original = geo.corridors_mask

    def no_core(holes, margin, width, height):
        return np.zeros((height, width), dtype=bool) if margin == geo.CORE_MARGIN else original(holes, margin, width, height)

    monkeypatch.setattr(geo, "corridors_mask", no_core)
    assert oracle(ground, _replay(course))["coeur"] > 0
    monkeypatch.undo()
    assert _replay(course) == course["trees"]


def test_core_mask_really_blocks_anchors(course, ground, monkeypatch):
    """Câblage du masque de cœur, en complément de la mutation sur 85660 links :
    un cœur total ne laisse aucun bosquet."""
    if not ground["anchors"]:
        pytest.skip("aucun ancrage")
    original = geo.corridors_mask

    def full_core(holes, margin, width, height):
        return np.ones((height, width), dtype=bool) if margin == geo.CORE_MARGIN else original(holes, margin, width, height)

    monkeypatch.setattr(geo, "corridors_mask", full_core)
    replayed = _replay(course)
    assert {g["motif"] for g in replayed["debug"]["groves"]} == {"sans_place"}
    assert not any(item["layer"] == "ancrage" for item in replayed["items"])
    assert Counter(replayed["debug"]["skips"]["ancrage"]) == {"sans_place": len(ground["anchors"])}
    assert oracle(ground, replayed)["ancrage"] == 0


# --- Oracle stratégique : mutations des données ---

@pytest.fixture(scope="module")
def strategic_inputs(course):
    return _strategic_inputs(course)


@pytest.fixture(scope="module")
def strategic(strategic_inputs):
    return strategic_view(sg.place_strategic(*strategic_inputs))


def _first_landing(view: dict) -> int:
    if not view["retombee"]:
        pytest.skip("aucune retombée")
    return next(iter(view["retombee"]))


def _with(view: dict, **layers) -> dict:
    mutated = copy.deepcopy(view)
    mutated.update(layers)
    return mutated


def test_strategic_oracle_catches_a_tree_on_the_axis_or_in_another_corridor(course, strategic):
    order = _first_landing(strategic)
    holes = {hole["id"]: hole for hole in course["routing"]["holes"]}
    tee = holes[order]["tee"]
    mutated = _with(strategic, retombee={**strategic["retombee"], order: [(int(tee["x"]), int(tee["y"]))]})
    assert strategic_oracle(course, mutated, {"axe"})["axe"] > 0
    other = holes[next(o for o in holes if o != order)]["tee"]
    mutated = _with(strategic, retombee={**strategic["retombee"], order: [(int(other["x"]) + 1, int(other["y"]))]})
    assert strategic_oracle(course, mutated, {"autres_corridors"})["autres_corridors"] > 0


def test_strategic_oracle_catches_split_pairs_and_wrong_spacing(course, strategic):
    holes = {hole["id"]: hole for hole in course["routing"]["holes"]}
    order = _first_landing(strategic)
    points = _polyline(holes[order])
    a, b = points[0], points[1]
    ux, uy = _unit(b - a)
    middle = (a + b) / 2.0
    left = (int(middle[0] - uy * 10.0), int(middle[1] + ux * 10.0))
    right = (int(middle[0] + uy * 10.0), int(middle[1] - ux * 10.0))
    mutated = _with(strategic, retombee={**strategic["retombee"], order: [left, right]})
    assert strategic_oracle(course, mutated, {"cote_retombee"})["cote_retombee"] == 1
    assert strategic_oracle(course, mutated, {"paire"})["paire"] == 1
    tripled = _with(strategic, retombee={**strategic["retombee"], order: [*strategic["retombee"][order]] * 3})
    assert strategic_oracle(course, tripled, {"paire"})["paire"] == 1


def test_strategic_oracle_catches_a_green_tree_on_the_wrong_side(course, strategic):
    holes = {hole["id"]: hole for hole in course["routing"]["holes"]}
    for order, cells in strategic["green"].items():
        flag, approach = _approach(holes[order])
        cx, cy = cells[0][0] + 0.5 - flag[0], cells[0][1] + 0.5 - flag[1]
        across = cx * -approach[1] + cy * approach[0]
        mirrored = (int(math.floor(flag[0] + cx + 2.0 * across * approach[1])),
                    int(math.floor(flag[1] + cy - 2.0 * across * approach[0])))
        mutated = _with(strategic, green={**strategic["green"], order: [mirrored]})
        assert strategic_oracle(course, mutated, {"cote_green"})["cote_green"] == 1
        return
    pytest.skip("aucun arbre de green")


def test_strategic_oracle_catches_broken_quotas(course, strategic):
    skipped = _with(strategic, skips={**strategic["skips"], "green": strategic["skips"]["green"] + 1})
    assert strategic_oracle(course, skipped, {"quota"})["quota"] > 0
    if len(strategic["green"]) > 1:
        reordered = _with(strategic, green=dict(reversed(list(strategic["green"].items()))))
        assert strategic_oracle(course, reordered, {"quota"})["quota"] > 0
    assert strategic_oracle(course, strategic, {"quota"})["quota"] == 0


# --- Oracle stratégique : mutations du code de production ---

def _broken(course, strategic_inputs, rules, data=None):
    """Oracle sur la pose (mutée) de ``data`` (défaut : le JSON sans arbres),
    relue dans ce même JSON."""
    data = strategic_inputs[0] if data is None else data
    return strategic_oracle(data, strategic_view(sg.place_strategic(data, *strategic_inputs[1:])), rules)


def test_mutation_drop_axis_clearance_is_caught(course, strategic_inputs, monkeypatch):
    monkeypatch.setattr(sg, "landing_offset", lambda half, encroachment: 0.0)
    monkeypatch.setattr(sg, "LANDING_AXIS_MARGIN", -1.0)
    monkeypatch.setattr(sg, "sections_ok", lambda *args, **kwargs: True)
    assert _broken(course, strategic_inputs, {"axe"})["axe"] > 0


def test_mutation_ignored_other_corridors_is_caught(course, strategic_inputs):
    data, model, masks = strategic_inputs
    open_masks = replace(masks, others={order: np.zeros_like(mask) for order, mask in masks.others.items()})
    found = strategic_oracle(course, strategic_view(sg.place_strategic(data, model, open_masks)), {"autres_corridors"})
    assert found["autres_corridors"] > 0


def _narrowed(course: dict) -> dict:
    """Fairways réduits à une bande de demi-largeur 3 autour de l'axe."""
    narrow = copy.deepcopy(course)
    for hole in narrow["routing"]["holes"]:
        polygon = buffered_axis(tuple(map(tuple, _polyline(hole))), 3.0)
        hole["features"]["fairway"] = [{"outline": [{"x": x, "y": y} for x, y in polygon]}]
    return narrow


def test_mutation_ignored_passage_is_caught(course, strategic_inputs, monkeypatch):
    narrow = _narrowed(strategic_inputs[0])
    assert _broken(course, strategic_inputs, {"passage"}, narrow)["passage"] == 0
    monkeypatch.setattr(sg, "sections_ok", lambda *args, **kwargs: True)
    assert _broken(course, strategic_inputs, {"passage"}, narrow)["passage"] > 0


def test_mutation_ignored_plateau_is_caught(course, strategic_inputs, monkeypatch):
    original = sg.zone_for

    def inflated(hole, style, seed):
        target = original(hole, style, seed)
        return None if target is None else (target[0], target[1] * 100.0)

    monkeypatch.setattr(sg, "zone_for", inflated)
    monkeypatch.setattr(sg, "TRIAL_OFFSETS", (20.0, -20.0, 30.0, -30.0))
    monkeypatch.setattr(sg, "TWIN_PROBABILITY", 0.0)
    assert _broken(course, strategic_inputs, {"zone"})["zone"] > 0


def test_mutation_wrong_offset_formula_is_caught(course, strategic_inputs, monkeypatch):
    original = sg.landing_offset
    monkeypatch.setattr(sg, "landing_offset", lambda half, encroachment: original(half, encroachment) + 4.0)
    assert _broken(course, strategic_inputs, {"formule_d"})["formule_d"] > 0


def test_mutation_wrong_pair_spacing_is_caught(course, strategic_inputs, monkeypatch):
    monkeypatch.setattr(sg, "TWIN_PROBABILITY", 1.0)
    monkeypatch.setattr(sg, "TWIN_SPACING", 6.0)
    assert _broken(course, strategic_inputs, {"paire"})["paire"] > 0


def test_mutation_pair_across_the_axis_is_caught(course, strategic_inputs, monkeypatch):
    def crossed(view, zone, half, side, forbidden, encroachment):
        first = sg._try_landing_tree(view, zone - TWIN_HALF, side, forbidden, encroachment)
        second = sg._try_landing_tree(view, zone + TWIN_HALF, -side, forbidden, encroachment)
        return None if first is None or second is None else (first, second)

    monkeypatch.setattr(sg, "TWIN_PROBABILITY", 1.0)
    monkeypatch.setattr(sg, "_try_pair", crossed)
    assert _broken(course, strategic_inputs, {"cote_retombee"})["cote_retombee"] > 0


def test_mutation_ignored_flanks_is_caught(course, strategic_inputs, monkeypatch):
    original = sg.place_green
    monkeypatch.setattr(sg, "place_green", lambda view, bunkers, rng, forbidden, landing:
                        original(view, [], rng, forbidden, landing))
    assert _broken(course, strategic_inputs, {"cote_green"})["cote_green"] > 0


def test_mutation_wrong_quota_is_caught(course, strategic_inputs, monkeypatch):
    monkeypatch.setattr(sg, "QUOTA_DIVISOR", 2)
    assert _broken(course, strategic_inputs, {"quota"})["quota"] > 0
