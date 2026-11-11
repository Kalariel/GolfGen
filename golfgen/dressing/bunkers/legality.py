"""Légalité d'une pose de bunker : carte, marges, voisins, contacts, eau (round R2).

Une pose (``position``) est un dict ``center``, ``tangent``, ``outline``
(contour monde, absent des pots) et ``cells`` (cases de sable ``(k, 2)``,
coin bas-gauche). Les surfaces du parcours sont des cibles ``Target``
(``course_targets`` : green, départs, morceaux de fairway de chaque trou,
greens doubles), la carte est ``limits = (largeur, hauteur)`` en blocs.

Contrôles (mêmes seuils, mêmes epsilon, mêmes libellés d'échec que l'étude) :

- ``pose_record`` / ``pose_measurements`` (haricots) : contour
  et cases dans la carte ; marge ≥ ``GREEN_GAP`` au green (et green double)
  du trou et ≥ ``TEE_GAP`` à ses départs, au contour (``polygon_gap``) ET
  aux carrés de sable (``raster_gap``) ; aucun carré sur une surface d'un
  autre trou (``neighbor_contact``) ; marge d'un bloc aux greens et départs
  des autres trous (``neighbor_green_tee_margin``) ;
- ``PoseAudit`` : mêmes décisions par seuils, sans distances de rapport
  (balayages des poses de flanc) ;
- ``pot_measurements`` (grappes de pots) : carte, herbe entre pots ≥
  ``MIN_GRASS``, marges green/départs aux carrés, voisins ; avec ``hd`` :
  au moins ``MIN_FAIRWAY_CELLS`` cases sur 8 dans le fairway par pot ;
- ``ContactIndex`` : contact arête/coin avec un bunker déjà posé ;
- ``ContourClearance``, ``pot_group_legal`` : contrôles de construction des
  grappes de pots de green ;
- ``haricot_checks`` : règles de la sonde des sites sur le contour réel ;
- ``FlankAudit`` : suite des contrôles d'une pose de flanc (glissement).

Eau (production) : ``water`` (``golfgen.routing.sites.WaterMask``) refuse
une pose dont le sable est sur l'eau, échec ``WATER_FAILURE`` ajouté en
dernier ; contour : ``golfgen.dressing.water.is_dry`` à la marge 0 ; cases :
``cells_dry`` (une case est mouillée si elle EST une cellule d'eau, ce qui
équivaut à ``is_dry`` sur son carré à la marge 0). ``water=None`` : aucun
contrôle d'eau, résultat de l'étude au bit près.
"""

from __future__ import annotations

from dataclasses import dataclass
import math

import numpy as np

from golfgen.dressing.bunkers.beans import bean_cells
from golfgen.dressing.bunkers.errors import BunkerError
from golfgen.dressing.bunkers.pots import MIN_GRASS
from golfgen.dressing.bunkers.raster import ONE_PIECE, cell_gap, raster_topology, to_world
from golfgen.dressing.green import points_in_polygon, polygon_inside
from golfgen.dressing.water import is_dry
from golfgen.routing import geometry
from golfgen.routing.geometry import build_hole_geometry, polygon_gap

# Marges (blocs) au green et aux départs du trou (sonde des sites et poses).
GREEN_GAP = 1.0
TEE_GAP = 1.0
# Pots d'appel : au moins 4 cases sur 8 dans le fairway (au plus la moitié en rough).
MIN_FAIRWAY_CELLS = 4
# Échec ajouté quand ``water`` est donné et que du sable est sur l'eau.
WATER_FAILURE = "water"
# Statut d'une pose légale (relevés de pose, grappes de pots, phase green).
POSE_FOUND = "pose_found"


@dataclass(frozen=True)
class Target:
    """Surface du parcours vue par les contrôles : ``orders`` (trous
    propriétaires, deux pour un green double), ``kind`` (``green``,
    ``tee_<i>``, ``fairway_<i>``, ``double_green``), contour monde."""

    orders: tuple[int, ...]
    kind: str
    outline: tuple[tuple[float, float], ...]


def _points(outline) -> tuple[tuple[float, float], ...]:
    return tuple((float(x), float(y)) for x, y in outline)


def course_targets(dressing) -> tuple[Target, ...]:
    """Cibles du parcours habillé (``CourseDressing``), dans l'ordre de l'étude :
    par trou green, départs, fairway ; puis greens doubles dessinés."""
    targets = []
    for order, hd in dressing.holes.items():
        features = [("green", hd.green.outline)]
        features.extend((f"tee_{i}", t.outline) for i, t in enumerate(hd.tees))
        features.extend((f"fairway_{i}", f.outline) for i, f in enumerate(hd.fairway))
        targets.extend(Target((order,), name, _points(outline)) for name, outline in features)
    for pair in dressing.green_pairs:
        if pair.outline:
            targets.append(Target((pair.i, pair.j), "double_green", _points(pair.outline)))
    return tuple(targets)


def _in_limits(points, limits) -> bool:
    return bool(((points >= 0) & (points < tuple(limits))).all())


# --- eau ----------------------------------------------------------------------

def cells_dry(cells, water) -> bool:
    """Aucune case de sable n'est une cellule d'eau (``water=None`` : vrai)."""
    if water is None:
        return True
    cells = np.asarray(cells, dtype=int).reshape(-1, 2)
    if not len(cells):
        return True
    low, high = cells.min(axis=0), cells.max(axis=0) + 1
    wet = water.cells_near(float(low[0]), float(low[1]), float(high[0]), float(high[1]))
    if not len(wet):
        return True
    return not {tuple(c) for c in wet.tolist()}.intersection(map(tuple, cells.tolist()))


def pose_dry(position: dict, water) -> bool:
    """Sable de la pose au sec : cases, et contour s'il existe (``is_dry``, marge 0)."""
    if water is None:
        return True
    outline = position.get("outline")
    return cells_dry(position["cells"], water) and (outline is None or is_dry(outline, water, 0.0))


# --- seuils préparés -------------------------------------------------------------

def prepared(points) -> dict:
    p = np.asarray(points, dtype=float)
    following = np.roll(p, -1, axis=0)
    return {"poly": tuple(map(tuple, p.tolist())), "p": p,
            "next": following, "low": p.min(axis=0), "high": p.max(axis=0),
            "edge_low": np.minimum(p, following), "edge_high": np.maximum(p, following)}


def box_safe(low, high, target, margin) -> bool:
    delta = np.maximum(np.maximum(target["low"] - high, low - target["high"]), 0)
    distance = float(np.linalg.norm(delta))
    return distance > 2 * geometry.EPSILON if margin == 0 else distance >= margin + 2 * geometry.EPSILON


def gap_safe(first: dict, second: dict, margin: float) -> bool:
    """Écart contour/contour ≥ ``margin`` (> 0 à marge 0), mêmes primitives
    scalaires et epsilon que ``polygon_gap``, cas d'inclusion compris."""
    if box_safe(first["low"], first["high"], second, margin):
        return True
    contained = (geometry.point_in_polygon(first["poly"][0], second["poly"])
                 or geometry.point_in_polygon(second["poly"][0], first["poly"]))
    if margin and contained:
        return False
    delta = np.maximum(np.maximum(second["edge_low"][None, :, :] - first["edge_high"][:, None, :],
                                  first["edge_low"][:, None, :] - second["edge_high"][None, :, :]), 0)
    reach = margin + 2 * geometry.EPSILON
    pairs = np.argwhere((delta * delta).sum(axis=2) <= reach * reach)
    near_positive = False
    for i, j in pairs:
        value = geometry.segment_distance(first["poly"][i], first["poly"][(i + 1) % len(first["poly"])],
                                          second["poly"][j], second["poly"][(j + 1) % len(second["poly"])])
        if (value == 0 if margin == 0 else value < margin):
            return False
        near_positive |= value <= geometry.EPSILON
    return (not contained or near_positive) if margin == 0 else True


def raster_safe(cells, low, high, target, margin, squares) -> bool:
    """Écart carrés de sable/contour ≥ ``margin`` ; ``squares`` : cache des carrés préparés."""
    if box_safe(low, high, target, margin):
        return True
    separation = np.maximum(np.maximum(target["low"] - (cells + 1), cells - target["high"]), 0)
    bounds = np.linalg.norm(separation, axis=1)
    for i in np.argsort(bounds):
        safe = (bounds[i] > 2 * geometry.EPSILON if margin == 0
                else bounds[i] >= margin + 2 * geometry.EPSILON)
        if safe:
            break
        key = tuple(map(int, cells[i]))
        if key not in squares:
            x, z = key
            squares[key] = prepared(((x, z), (x + 1, z), (x + 1, z + 1), (x, z + 1)))
        if not gap_safe(squares[key], target, margin):
            return False
    return True


def raster_gap(cells: np.ndarray, polygon) -> float:
    """Distance carrés de sable/polygone, filtrée par leurs boîtes englobantes."""
    if not len(cells):
        raise ValueError("empreinte raster vide")
    polygon = _points(polygon)
    p = np.asarray(polygon)
    separation = np.maximum(np.maximum(p.min(axis=0) - (cells + 1), cells - p.max(axis=0)), 0)
    bounds = np.linalg.norm(separation, axis=1)
    best = float("inf")
    for index in np.argsort(bounds):
        if bounds[index] >= best:
            break
        x, y = map(float, cells[index])
        square = ((x, y), (x + 1, y), (x + 1, y + 1), (x, y + 1))
        best = min(best, polygon_gap(square, polygon))
    return best


class PoseAudit:
    """Mêmes motifs de rejet que ``pose_record``, par seuils seulement (sans
    distances de rapport) ; cibles préparées partagées (``polygons``)."""

    def __init__(self, targets, order: int, limits, *, polygons=None, water=None):
        self.limits = np.array(tuple(int(v) for v in limits))
        self.water = water
        self.squares = {}
        self.own = {"green": [], "tee": []}
        self.neighbors = []
        for index, target in enumerate(targets):
            polygon = prepared(target.outline) if polygons is None else polygons[index]
            if order in target.orders:
                if target.kind.startswith(("green", "double_green")):
                    self.own["green"].append(polygon)
                elif target.kind.startswith("tee"):
                    self.own["tee"].append(polygon)
            else:
                self.neighbors.append((polygon, 0. if target.kind.startswith("fairway") else 1.))

    def failures(self, position: dict) -> list[str]:
        cells, outline = position["cells"], position["outline"]
        contour = prepared(outline)
        low, high = cells.min(axis=0), cells.max(axis=0) + 1
        failures = []
        for label, targets in self.own.items():
            margin = GREEN_GAP if label == "green" else TEE_GAP
            if not all(gap_safe(contour, target, margin) for target in targets):
                failures.append(f"{label}_contour_margin")
            if not all(raster_safe(cells, low, high, target, margin, self.squares) for target in targets):
                failures.append(f"{label}_raster_margin")
        if not ((outline >= 0).all() and (outline < self.limits).all()
                and (cells >= 0).all() and (cells + 1 <= self.limits).all()):
            failures.append("map")
        contact, margin_failure = False, False
        for target, margin in self.neighbors:
            if margin:
                safe = raster_safe(cells, low, high, target, margin, self.squares)
                margin_failure |= not safe
                if safe:
                    continue
            contact |= not raster_safe(cells, low, high, target, 0., self.squares)
        if contact:
            failures.append("neighbor_contact")
        if margin_failure:
            failures.append("neighbor_green_tee_margin")
        if not pose_dry(position, self.water):
            failures.append(WATER_FAILURE)
        return failures

    def record(self, identity, site, position):
        failures = self.failures(position)
        row = {**identity, "site": site, "status": "missing" if failures else "pose_found"}
        if failures:
            row.update(reason="geometry_constraints", rejection_checks=failures)
        return row


class ContactIndex:
    """Contacts exacts des carrés (arête et coin compris) avec des bunkers
    déjà posés ``others`` = ``[(ordre du trou, bunker), ...]``."""

    def __init__(self, others):
        self.others = [(order, bunker["id"]) for order, bunker in others]
        self.blocked = {}
        for index, (_, bunker) in enumerate(others):
            for x, z in bunker["cells"]:
                for dx in (-1, 0, 1):
                    for dz in (-1, 0, 1):
                        self.blocked.setdefault((int(x) + dx, int(z) + dz), set()).add(index)

    def contacts(self, cells) -> list[dict]:
        indices = set()
        for cell in cells:
            indices.update(self.blocked.get(tuple(cell), ()))
        return [{"order": self.others[i][0], "bunker": self.others[i][1]} for i in sorted(indices)]


class ContourClearance:
    """Contours lisses d'une grappe de pots : carte, marges au green et aux
    départs du trou, herbe entre pots ; ``water`` : contours au sec."""

    def __init__(self, hd, limits, *, green_gap=1., tee_gap=1., water=None):
        self.limits = np.array(tuple(int(v) for v in limits))
        self.water = water
        self.targets = [(prepared(hd.green.outline), green_gap),
                        *((prepared(t.outline), tee_gap) for t in hd.tees)]

    def legal(self, shapes, *, grass_gap=3.) -> bool:
        outlines = []
        for shape in shapes:
            if not ((shape >= 0).all() and (shape < self.limits).all()):
                return False
            outline = prepared(shape)
            if not all(gap_safe(outline, target, margin) for target, margin in self.targets):
                return False
            if not is_dry(shape, self.water, 0.0):
                return False
            outlines.append(outline)
        return all(gap_safe(left, right, grass_gap)
                   for i, left in enumerate(outlines) for right in outlines[i + 1:])


def pot_group_legal(pots: tuple[np.ndarray, ...], hd, limits, *, green=None, squares=None,
                    water=None) -> bool:
    """Grappe raster de pots de green : carte, marge ``GREEN_GAP`` au green
    (carrés), herbe ≥ ``MIN_GRASS`` entre pots ; ``water`` : cases au sec."""
    width, height = (int(v) for v in limits)
    for cells in pots:
        if (cells[:, 0].min() < 0 or cells[:, 0].max() + 1 > width
                or cells[:, 1].min() < 0 or cells[:, 1].max() + 1 > height):
            return False
        if green is None:
            green = prepared(hd.green.outline)
        if squares is None:
            squares = {}
        if not raster_safe(cells, cells.min(axis=0), cells.max(axis=0) + 1, green, GREEN_GAP, squares):
            return False
        if not cells_dry(cells, water):
            return False
    return all(cell_gap(left, right) >= MIN_GRASS
               for index, left in enumerate(pots) for right in pots[index + 1:])


# --- relevés exacts --------------------------------------------------------------

def _neighbor_rows(cells, order: int, targets) -> tuple[list[dict], list[dict]]:
    """Contacts (écart 0 à toute surface d'un autre trou) et marges d'un bloc
    manquées aux greens/départs des autres trous."""
    low, high = cells.min(axis=0), (cells + 1).max(axis=0)
    contacts, margins = [], []
    for target in targets:
        if order in target.orders:
            continue
        p = np.asarray(target.outline)
        clearance = 0.0 if target.kind.startswith("fairway") else 1.0
        if (p.max(axis=0) < low - clearance).any() or (p.min(axis=0) > high + clearance).any():
            continue
        gap = raster_gap(cells, target.outline)
        identity = {"orders": list(target.orders), "kind": target.kind}
        if gap == 0:
            contacts.append(identity)
        if clearance and gap < clearance:
            margins.append({**identity, "gap_blocks": round(gap, 4)})
    return contacts, margins


def pose_measurements(position: dict, order: int, limits, targets) -> dict:
    """Distances et décisions d'une pose à contour (décisions non arrondies)."""
    outline = _points(position["outline"])
    cells = position["cells"]
    width, height = (int(v) for v in limits)
    result = {"center": [round(float(v), 4) for v in position["center"]],
              "sand_cells": len(cells),
              "contour_in_map": _in_limits(position["outline"], (width, height)),
              "raster_in_map": bool(((cells >= 0) & (cells + 1 <= (width, height))).all())}
    for label, kinds in (("green", ("green", "double_green")), ("tee", ("tee",))):
        own = [t for t in targets if order in t.orders and any(t.kind.startswith(kind) for kind in kinds)]
        contour = min((polygon_gap(outline, t.outline) for t in own), default=None)
        raster = min((raster_gap(cells, t.outline) for t in own), default=None)
        threshold = GREEN_GAP if label == "green" else TEE_GAP
        result[f"{label}_contour_gap_blocks"] = None if contour is None else round(contour, 4)
        result[f"{label}_raster_gap_blocks"] = None if raster is None else round(raster, 4)
        result[f"{label}_contour_margin_pass"] = contour is None or contour >= threshold
        result[f"{label}_raster_margin_pass"] = raster is None or raster >= threshold
    contacts, margins = _neighbor_rows(cells, order, targets)
    result["neighbor_raster_contacts"] = contacts
    result["neighbor_green_tee_margin_failures"] = margins
    return result


def pose_record(identity: dict, site: str, position: dict, order: int, limits, targets, *,
                water=None) -> dict:
    """Enregistrement de pose : ``pose_found``, ou ``missing`` avec les
    contrôles en échec (``rejection_checks``). Empreinte sans sable :
    ``BunkerError`` (contour tiré trop mince pour couvrir un centre de case,
    échec dépendant de la seed) ; les aides de mesure (``raster_gap``,
    ``distance.sand_distance``) gardent ``ValueError`` (bogue de l'appelant)."""
    if not len(position["cells"]):
        raise BunkerError("empreinte raster vide")
    measured = pose_measurements(position, order, limits, targets)
    failures = []
    for kind in ("green", "tee"):
        if not measured[f"{kind}_contour_margin_pass"]:
            failures.append(f"{kind}_contour_margin")
        if not measured[f"{kind}_raster_margin_pass"]:
            failures.append(f"{kind}_raster_margin")
    if not measured["contour_in_map"] or not measured["raster_in_map"]:
        failures.append("map")
    if measured["neighbor_raster_contacts"]:
        failures.append("neighbor_contact")
    if measured["neighbor_green_tee_margin_failures"]:
        failures.append("neighbor_green_tee_margin")
    if not pose_dry(position, water):
        failures.append(WATER_FAILURE)
    row = {**identity, "site": site, "status": "missing" if failures else POSE_FOUND,
           "measurements": measured}
    if failures:
        row.update(reason="geometry_constraints", rejection_checks=failures)
    return row


def fairway_cell_counts(group_cells: tuple[np.ndarray, ...], hd) -> tuple[int, ...]:
    """Nombre de cases de chaque pot dont le centre est dans le fairway."""
    fairways = tuple(np.asarray(fairway.outline) for fairway in hd.fairway)
    counts = []
    for cells in group_cells:
        centers = cells + 0.5
        inside = np.zeros(len(cells), dtype=bool)
        for fairway in fairways:
            inside |= points_in_polygon(centers, fairway)
        counts.append(int(np.count_nonzero(inside)))
    return tuple(counts)


def pot_measurements(group, order: int, limits, targets, *, hd=None, water=None) -> dict:
    """Relevé et échecs (``failures``) d'une grappe de pots ; ``hd`` : règle
    du fairway des pots d'appel. Décisions sur les distances exactes."""
    cells = np.vstack(group)
    width, height = (int(v) for v in limits)
    failures = []
    in_map = bool(((cells >= 0) & (cells + 1 <= (width, height))).all())
    if not in_map:
        failures.append("map")
    gap = min(cell_gap(left, right) for index, left in enumerate(group) for right in group[index + 1:])
    if gap < MIN_GRASS:
        failures.append("pot_grass_gap")
    result = {"sand_cells_per_pot": [len(p) for p in group], "raster_in_map": in_map,
              "minimum_grass_blocks": round(gap, 4)}
    for name in ("green", "tee"):
        own = [t for t in targets if order in t.orders and (
            t.kind.startswith(name) or name == "green" and t.kind == "double_green")]
        distance = min((raster_gap(cells, t.outline) for t in own), default=None)
        result[f"minimum_{name}_gap_blocks"] = None if distance is None else round(distance, 4)
        if distance is not None and distance < 1.0:
            failures.append(f"{name}_margin")
    contacts, margins = _neighbor_rows(cells, order, targets)
    if contacts:
        failures.append("neighbor_contact")
    if margins:
        failures.append("neighbor_green_tee_margin")
    result.update(neighbor_contacts=contacts, neighbor_margin_failures=margins)
    if hd is not None:
        fairway = fairway_cell_counts(group, hd)
        result["fairway_cells_per_pot"] = list(fairway)
        if any(len(p) != 8 or count < MIN_FAIRWAY_CELLS for p, count in zip(group, fairway, strict=True)):
            failures.append("fairway_half_per_pot")
    if not cells_dry(cells, water):
        failures.append(WATER_FAILURE)
    result["failures"] = failures
    return result


# --- haricot au site ---------------------------------------------------------------

def haricot_checks(outline: np.ndarray, rough: np.ndarray, green, tees, water=None) -> dict:
    """Règles de la sonde des sites appliquées au contour monde réel du
    haricot (bande de jeu, marges green/départs), plus le sec à la marge 0."""
    inside = polygon_inside(outline, rough)
    poly = tuple(map(tuple, outline))
    green_gap = polygon_gap(poly, tuple(map(tuple, green.outline)))
    tee_gap = min((polygon_gap(poly, tuple(map(tuple, tee.outline))) for tee in tees), default=math.inf)
    dry = is_dry(outline, water, 0.0)
    return {"inside_play_band": inside, "green_gap_blocks": round(green_gap, 2),
            "tee_gap_blocks": round(tee_gap, 2), "dry": dry,
            "legal": inside and dry and green_gap >= GREEN_GAP and tee_gap >= TEE_GAP}


def edge_distance(points: np.ndarray, polygon: np.ndarray) -> np.ndarray:
    """Distance de chaque point aux segments du contour (blocs)."""
    points = np.asarray(points, dtype=float)
    polygon = np.asarray(polygon, dtype=float)
    a, b = polygon, np.roll(polygon, -1, axis=0)
    ab = b - a
    rel = points[:, None, :] - a[None, :, :]
    t = np.clip(np.einsum("pij,ij->pi", rel, ab) / np.einsum("ij,ij->i", ab, ab), 0.0, 1.0)
    closest = a[None, :, :] + t[:, :, None] * ab[None, :, :]
    return np.linalg.norm(points[:, None, :] - closest, axis=2).min(axis=1)


def fairway_metrics(cells: np.ndarray, center: np.ndarray, fairways) -> dict:
    """Morsure raster du fairway et position signée du centre (relevé)."""
    points = cells + 0.5
    inside = np.zeros(len(points), dtype=bool)
    center_inside = False
    nearest_center = math.inf
    depth = 0.0
    for fairway in fairways:
        polygon = np.asarray(fairway.outline, dtype=float)
        mask = points_in_polygon(points, polygon)
        inside |= mask
        center_inside |= bool(points_in_polygon(center[None, :], polygon)[0])
        nearest_center = min(nearest_center, float(edge_distance(center[None, :], polygon)[0]))
        if mask.any():
            depth = max(depth, float(edge_distance(points[mask], polygon).max()))
    count = int(inside.sum())
    return {"sand_cells": int(len(cells)), "fairway_cells": count,
            "fairway_fraction": round(count / len(cells), 3) if len(cells) else 0.0,
            "bite_depth_blocks": round(depth, 2),
            "center_to_fairway_blocks": round(-nearest_center if center_inside else nearest_center, 2)}


def shifted_pose(hole, hd, placement, offset: float, *, water=None) -> dict:
    """Haricot de retombée posé au site décalé de ``offset`` vers l'extérieur
    (``placement`` = ``beans.landing_placement``) : pose, contrôles de la
    sonde (``haricot_checks``), écart au bord de la bande, morsure du fairway."""
    row, bean, local, tangent, outward, length = placement
    center = np.asarray(row["center"], dtype=float) + offset * outward
    outline = to_world(local, center, tangent)
    cells = bean_cells(bean, center, tangent, outline=local)
    rough = np.asarray(build_hole_geometry(hole).rough, dtype=float)
    checks = haricot_checks(outline, rough, hd.green, hd.tees, water)
    rough_gap = (min(float(edge_distance(outline, rough).min()), float(edge_distance(rough, outline).min()))
                 if checks["inside_play_band"] else 0.0)
    return {"offset_blocks": offset, "length_blocks": round(length, 2),
            "center": center, "outline": outline, "cells": cells, "checks": checks,
            "rough_edge_gap_blocks": round(rough_gap, 2),
            "fairway": fairway_metrics(cells, center, hd.fairway)}


# --- pose de flanc -------------------------------------------------------------------

class FlankAudit:
    """Contrôles d'une pose de flanc d'un bunker de green du trou ``order``,
    dans l'ordre de l'étude (le contact, qui arrête le glissement, est à
    part : ``ContactIndex``) : aucune inclusion mutuelle avec le green, le
    green double ou les départs du trou ; marges du contour ; un seul
    morceau de sable sans poche d'herbe ; ``PoseAudit`` ; ``pose_record``."""

    INCLUSION, CONTOUR, TOPOLOGY, AUDIT, RECORD = (
        "inclusion", "own_contour_margin", "topology", "audit", "pose_record")

    def __init__(self, context, order: int):
        self.order, self.context = order, context
        self.own = [t for t in context.targets if order in t.orders and not t.kind.startswith("fairway")]
        self.own_prepared = [(prepared(t.outline), TEE_GAP if t.kind.startswith("tee") else GREEN_GAP)
                             for t in self.own]

    def check(self, position: dict) -> tuple[str | None, dict | None, dict | None]:
        """(échec ou ``None``, enregistrement de pose, topologie) de ``position``."""
        outline, cells = position["outline"], position["cells"]
        if any(points_in_polygon(outline, np.asarray(t.outline)).any()
               or points_in_polygon(np.asarray(t.outline), outline).any() for t in self.own):
            return self.INCLUSION, None, None
        contour = prepared(outline)
        if not all(gap_safe(contour, target, margin) for target, margin in self.own_prepared):
            return self.CONTOUR, None, None
        topology = raster_topology(cells) if len(cells) else None
        if topology != ONE_PIECE:
            return self.TOPOLOGY, None, topology
        if self.context.audit(self.order).failures(position):
            return self.AUDIT, None, topology
        record = pose_record({}, "flanc", position, self.order, self.context.limits, self.context.targets,
                             water=self.context.water)
        if record["status"] != "pose_found":
            return self.RECORD, record, topology
        return None, record, topology
