"""Sites tactiques candidats des bunkers et position au coude (round R2).

Sonde (``candidates``) : par rôle, un ancrage dans l'axe (zones de retombée
du profil du fairway, flux ``fairway_rng`` ; garde de green à
``max(L - 10, 0,75 L)``), deux côtés à ``± largeur/2`` sur la normale ;
légal si une ellipse neutre (``RADIUS`` × 0,7 ``RADIUS``) tient dans la
bande de jeu (``geometry.rough``) à ``GREEN_GAP`` du green et ``TEE_GAP``
des départs. Aucun tirage de bunker, aucune sélection. Style : celui de
l'habillage (``FAIRWAY_STYLES``), jamais figé.
"""

from __future__ import annotations

import math

import numpy as np

from golfgen.dressing.bunkers.legality import GREEN_GAP, TEE_GAP
from golfgen.dressing.fairway import FAIRWAY_STYLES, Axis, landing_zones, profile_draws
from golfgen.dressing.green import polygon_inside
from golfgen.dressing.rng import fairway_rng
from golfgen.routing.geometry import build_hole_geometry, polygon_gap

RADIUS = 2.0   # ellipse de contrôle seulement, aucune forme de bunker


def footprint(center, tangent) -> np.ndarray:
    """Ellipse neutre de contrôle (16 sommets) le long de ``tangent``."""
    normal = np.array((-tangent[1], tangent[0]))
    angles = np.linspace(0.0, 2.0 * math.pi, 16, endpoint=False)
    return np.asarray(center) + (np.cos(angles)[:, None] * tangent * RADIUS
                                 + np.sin(angles)[:, None] * normal * (RADIUS * 0.7))


def candidates(hole, *, style: str, green, tees, seed: int) -> list[dict]:
    """Sites du trou, deux côtés par ancrage (``role``, ``side``, ``legal``,
    ``center``, ``tangent``, ``s_blocks``, écarts arrondis)."""
    axis = Axis.of(hole)
    geometry = build_hole_geometry(hole)
    zones = landing_zones(axis, hole.par, profile_draws(fairway_rng(seed, hole.order), FAIRWAY_STYLES[style]))
    anchors = [("landing", s) for s in zones]
    anchors.append(("green_guard", max(axis.length - 10.0, axis.length * 0.75)))
    rows = []
    obstacles = [green.outline, *(tee.outline for tee in tees)]
    for role, s in anchors:
        points, normals = axis.at(np.asarray([s]))
        for side in (-1, 1):
            center = points[0] + side * (hole.width / 2.0) * normals[0]
            tangent = axis.tangents[np.searchsorted(axis.starts, s, side="right") - 1]
            outline = footprint(center, tangent)
            legal_band = polygon_inside(outline, np.asarray(geometry.rough, dtype=float))
            gaps = [polygon_gap(tuple(map(tuple, outline)), tuple(obstacle)) for obstacle in obstacles]
            legal = legal_band and all(gap >= (GREEN_GAP if n == 0 else TEE_GAP) for n, gap in enumerate(gaps))
            rows.append({"role": role, "side": "left" if side > 0 else "right",
                         "legal": legal, "inside_play_band": legal_band,
                         "center": [round(float(v), 3) for v in center],
                         "tangent": [round(float(v), 6) for v in tangent],
                         "s_blocks": round(float(s), 2),
                         "green_gap_blocks": round(gaps[0], 2),
                         "tee_gap_blocks": round(min(gaps[1:], default=math.inf), 2)})
    return rows


def retained_site(sites: list[dict], role: str) -> dict | None:
    """Premier site du rôle légal à la sonde, ou ``None``."""
    return next((row for row in sites if row["role"] == role and row["legal"]), None)


def corner_position(hole, row: dict) -> str:
    """``inside`` / ``outside`` pour un site au coude d'un dogleg, sinon ``straight``."""
    axis = Axis.of(hole)
    for index, station in enumerate(axis.corners):
        if abs(row["s_blocks"] - station) > 0.02:
            continue
        before, after = axis.tangents[index:index + 2]
        turn = before[0] * after[1] - before[1] * after[0]
        inner = "left" if turn > 0 else "right"
        return "inside" if row["side"] == inner else "outside"
    return "straight"
