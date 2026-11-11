"""Accès au green : passage de 2 blocs sur le fairway sans sable (round R2).

Contrôle discret : un carré ``width`` × ``width`` (2 par défaut) se déplace
à quatre voisins (pas de diagonale) sur les cases de fairway (centre dans
l'union des morceaux) hors sable, d'une bande d'entrée à une bande de
sortie d'un bloc dans l'axe final (``Axis.tangents[-1]``, origine centre du
green). Extrémités fixées sans sable : si le fairway seul ne relie pas
l'entrée à la sortie, l'échec n'est pas imputé au sable.

Domaine du trou (``hole_domain``) : cases de fairway entre 4 blocs derrière
la case de sable la plus arrière de TOUS les bunkers du trou et le bord
avant du green ; trou sans bunker : fairway entier. Bande vide (début au-delà
du bord avant) : ``non_applicable`` ; trou sans fairway : ``no_fairway``.

Règle validée (utilisateur, 2026-10-31) : le sable des pots de green (famille
``pot``, rôle ``green``, ``ACCESS_EXEMPT``) n'est pas un obstacle ; masque
d'obstacles construit en un seul endroit (``sand_of``). Le domaine, lui,
compte tous les bunkers du trou.

Un bunker est un dict ``id``, ``family`` (``pot``, ``haricot``),
``role`` (``green``, ``landing``), ``cells`` ; un trou du
parcours (``cases``) un dict ``hole`` (``ElasticHole``), ``hd``
(``HoleDressing``), ``bunkers`` et, pour les étiquettes, ``spec``.
"""

from __future__ import annotations

from collections import deque

import numpy as np

from golfgen.dressing.bunkers.errors import BunkerError
from golfgen.dressing.fairway import Axis
from golfgen.dressing.green import points_in_polygon

NEIGHBORS = ((1, 0), (-1, 0), (0, 1), (0, -1))
ACCESS_WIDTH = 2
# Recul (blocs) de l'entrée derrière la case de sable la plus arrière du trou.
DOMAIN_BACK_BLOCKS = 4.0
# (famille, rôle) dont le sable n'est pas un obstacle du passage.
ACCESS_EXEMPT = frozenset({("pot", "green")})
PASS, FAIL = "pass", "fail"
NON_APPLICABLE, NO_FAIRWAY_STATUS = "non_applicable", "no_fairway"
SAND_FAILURE = "sand_blocks_access"
EMPTY_BAND = "empty_approach_band"
NO_FAIRWAY = "no_fairway_pieces"
SQUARE = np.array(((0, 0), (1, 0), (1, 1), (0, 1)))


def footprint(anchor, width: int) -> set[tuple[int, int]]:
    x, y = anchor
    return {(x + i, y + j) for i in range(width) for j in range(width)}


def anchors(cells, width: int) -> set[tuple[int, int]]:
    """Carrés complets ``width`` × ``width`` contenus dans les cases ``cells``."""
    return {p for p in cells if footprint(p, width) <= cells}


def corridor(fairway_cells, sand_cells, forward, origin, *, width: int = ACCESS_WIDTH) -> dict:
    """Passage du carré de l'entrée à la sortie, hors sable (``pass``,
    ``baseline_pass``, ``reason``, chemin)."""
    fair = {tuple(map(int, p)) for p in np.asarray(fairway_cells, dtype=int).reshape(-1, 2)}
    sand = {tuple(map(int, p)) for p in np.asarray(sand_cells, dtype=int).reshape(-1, 2)}
    baseline = anchors(fair, width)
    if not baseline:
        return {"width_blocks": width, "baseline_pass": False, "pass": False,
                "reason": "no_fairway_footprint", "path_anchors": [], "path_cells": []}
    origin, forward = np.asarray(origin), np.asarray(forward)
    stations = {p: float((np.asarray(p) + width / 2 - origin) @ forward) for p in baseline}
    low, high = min(stations.values()), max(stations.values())
    source = {p for p, s in stations.items() if s <= low + 1.0}
    target = {p for p, s in stations.items() if s >= high - 1.0}

    def find_path(allowed):
        queue = deque(sorted(source & allowed))
        previous = {p: None for p in queue}
        while queue:
            point = queue.popleft()
            if point in target:
                path = []
                while point is not None:
                    path.append(point)
                    point = previous[point]
                return list(reversed(path))
            x, y = point
            for dx, dy in NEIGHBORS:
                other = x + dx, y + dy
                if other in allowed and other not in previous:
                    previous[other] = point
                    queue.append(other)
        return []

    baseline_pass = bool(find_path(baseline))
    free = {p for p in baseline if not footprint(p, width).intersection(sand)}
    path = find_path(free)
    cells = sorted(set().union(*(footprint(p, width) for p in path))) if path else []
    return {"width_blocks": width, "baseline_pass": baseline_pass, "pass": bool(path),
            "reason": "pass" if path else SAND_FAILURE if baseline_pass else "baseline_fairway_disconnected",
            "terminal_stations_blocks": [low, high],
            "path_anchors": [list(p) for p in path], "path_cells": [list(p) for p in cells]}


def fairway_domain(hole, hd, positions: list[dict]) -> tuple[np.ndarray, dict]:
    """Cases de fairway de la bande d'approche : de ``DOMAIN_BACK_BLOCKS``
    derrière la plus arrière des cases de ``positions`` au bord avant du green."""
    forward = Axis.of(hole).tangents[-1]
    origin = np.asarray(hd.green.center)
    corners = np.vstack([p["cells"][:, None, :] + SQUARE for p in positions]).reshape(-1, 2)
    start = float(((corners - origin) @ forward).min() - DOMAIN_BACK_BLOCKS)
    end = float(((np.asarray(hd.green.outline) - origin) @ forward).min())
    outlines = [np.asarray(f.outline) for f in hd.fairway]
    vertices = np.vstack(outlines)
    lo, hi = np.floor(vertices.min(axis=0)).astype(int), np.ceil(vertices.max(axis=0)).astype(int)
    x, y = np.meshgrid(np.arange(lo[0], hi[0]), np.arange(lo[1], hi[1]), indexing="ij")
    cells = np.column_stack((x.ravel(), y.ravel()))
    centers = cells + 0.5
    station = (centers - origin) @ forward
    mask = (station >= start) & (station <= end)
    inside = np.zeros(len(cells), dtype=bool)
    for outline in outlines:
        inside |= points_in_polygon(centers, outline)
    return cells[mask & inside], {"origin": origin.tolist(), "forward": forward.tolist(),
                                  "start_station_blocks": start, "front_green_station_blocks": end}


def whole_fairway_positions(hd) -> list[dict]:
    if not hd.fairway:
        raise BunkerError("trou sans morceau de fairway")
    vertices = np.vstack([np.asarray(f.outline) for f in hd.fairway])
    return [{"cells": np.floor(vertices).astype(int)}]


def hole_domain(hole, hd, bunkers: list[dict]) -> tuple[np.ndarray, dict]:
    """Domaine d'accès du trou : tous ses bunkers, sinon fairway entier."""
    positions = ([{"cells": np.asarray(b["cells"], dtype=int)} for b in bunkers]
                 or whole_fairway_positions(hd))
    return fairway_domain(hole, hd, positions)


def empty_band(dimensions: dict) -> bool:
    """Bande d'approche vide : début au-delà du bord avant du green."""
    return dimensions["start_station_blocks"] > dimensions["front_green_station_blocks"]


def domain_cells(hole, hd, bunkers: list[dict]) -> set[tuple[int, int]]:
    """Cases du domaine contrôlé (vide : sans fairway ou bande vide)."""
    if not hd.fairway:
        return set()
    domain, dimensions = hole_domain(hole, hd, bunkers)
    if empty_band(dimensions):
        return set()
    return {tuple(map(int, p)) for p in np.asarray(domain, dtype=int).reshape(-1, 2)}


def blocks_access(bunker: dict) -> bool:
    """Le sable de ce bunker est-il un obstacle du passage ?"""
    return (bunker["family"], bunker["role"]) not in ACCESS_EXEMPT


def _cells_of(bunkers: list[dict], skip: int | None, keep) -> np.ndarray:
    chosen = [np.asarray(b["cells"], dtype=int).reshape(-1, 2) for i, b in enumerate(bunkers)
              if i != skip and keep(b)]
    return np.vstack(chosen) if chosen else np.zeros((0, 2), dtype=int)


def sand_of(bunkers: list[dict], skip: int | None = None) -> np.ndarray:
    """Masque d'obstacles du contrôle : sable des bunkers obstacles (``blocks_access``)."""
    return _cells_of(bunkers, skip, blocks_access)


def access_status(hole, hd, bunkers: list[dict], sand: np.ndarray) -> dict:
    """Décision d'accès du trou (domaine de ses ``bunkers``) sous le sable ``sand``."""
    if not hd.fairway:
        return {"status": NO_FAIRWAY_STATUS, "pass": None, "reason": NO_FAIRWAY}
    domain, dimensions = hole_domain(hole, hd, bunkers)
    if empty_band(dimensions):
        return {"status": NON_APPLICABLE, "pass": None, "reason": EMPTY_BAND}
    result = corridor(domain, sand, Axis.of(hole).tangents[-1], np.asarray(hd.green.center))
    return {"status": PASS if result["pass"] else FAIL, "pass": result["pass"], "reason": result["reason"]}


# --- coupables d'un blocage (option a′ de la pose de flanc) -----------------------

def variant(spec: dict, bunker: dict) -> str | None:
    """Variante de pose lue dans la spec : seul le haricot de retombée
    extérieur existe sur le chemin validé (corrections réservées à g1 non portées)."""
    if bunker["family"] == "haricot" and bunker["role"] == "landing" and spec.get("haricot_landing") == "outside":
        return "dogleg_extérieur"
    return None


def label(row: dict) -> str:
    text = f"{row['family']}/{row['role']}"
    return f"{text}/{row['variant']}" if row["variant"] else text


def course_bunkers(cases: list[dict]) -> list[dict]:
    """Bunkers du parcours, trou par trou : identité, variante et cases."""
    return [{"hole_order": case["hole"].order, "id": b["id"], "family": b["family"], "role": b["role"],
             "variant": variant(case.get("spec", {}), b),
             "cells": np.asarray(b["cells"], dtype=int).reshape(-1, 2)}
            for case in cases for b in case["bunkers"]]


def attribute(domain, bunkers: list[dict], forward, origin) -> dict:
    """Contrôle, puis, si le sable bloque, retrait d'un seul bunker obstacle
    du domaine à la fois : coupables = ceux dont le retrait rétablit le passage."""
    result = corridor(domain, sand_of(bunkers), forward, origin)
    inside = {tuple(map(int, p)) for p in np.asarray(domain, dtype=int).reshape(-1, 2)}
    candidates = [i for i, b in enumerate(bunkers)
                  if blocks_access(b) and inside.intersection(map(tuple, b["cells"].tolist()))]
    row = {"status": PASS if result["pass"] else FAIL,
           "pass": result["pass"], "reason": result["reason"], "baseline_pass": result["baseline_pass"],
           "candidates": [{"hole_order": bunkers[i]["hole_order"], "id": bunkers[i]["id"]} for i in candidates],
           "culprits": [], "attribution": None}
    if result["pass"]:
        return row
    if result["reason"] != SAND_FAILURE:
        row["attribution"] = "fairway_sans_sable"
        return row
    for i in candidates:
        if corridor(domain, sand_of(bunkers, skip=i), forward, origin)["pass"]:
            b = bunkers[i]
            row["culprits"].append({"hole_order": b["hole_order"], "id": b["id"], "family": b["family"],
                                    "role": b["role"], "variant": b["variant"], "label": label(b)})
    row["attribution"] = "bunker_seul" if row["culprits"] else "combinaison"
    return row


def checked_row(domain, dimensions: dict, bunkers: list[dict], forward, origin) -> dict:
    """Bande vide : non applicable, sans contrôle ; sinon contrôle et attribution."""
    if empty_band(dimensions):
        return {"status": NON_APPLICABLE, "pass": None, "reason": EMPTY_BAND, "baseline_pass": None,
                "candidates": [], "culprits": [], "attribution": None}
    return attribute(domain, bunkers, forward, origin)


def access_without(cases: list[dict], order: int, bunker_id: str) -> dict:
    """Accès du green du trou ``order`` sans le bunker ``bunker_id`` (domaine
    recalculé sans lui), sable de tous les autres bunkers du parcours ;
    décision et coupables (``checked_row``)."""
    course = [{**c, "bunkers": [b for b in c["bunkers"] if b["id"] != bunker_id]}
              if c["hole"].order == order else c for c in cases]
    stripped = next(c for c in course if c["hole"].order == order)
    hd = stripped["hd"]
    if not hd.fairway:
        return {"status": NO_FAIRWAY_STATUS, "reason": NO_FAIRWAY, "attribution": None, "culprits": []}
    domain, dimensions = hole_domain(stripped["hole"], hd, stripped["bunkers"])
    checked = checked_row(domain, dimensions, course_bunkers(course),
                          Axis.of(stripped["hole"]).tangents[-1], np.asarray(hd.green.center))
    return {"status": checked["status"], "reason": checked["reason"], "attribution": checked["attribution"],
            "culprits": [{k: c[k] for k in ("hole_order", "id", "label")} for c in checked["culprits"]]}
