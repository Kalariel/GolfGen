"""Distance des bunkers de fairway aux bunkers de green (round R2).

Règle des 18 b (décision B2 de l'utilisateur, 2026-11-01) : un bunker de
fairway (rôle ``landing``) est refusé si son sable est STRICTEMENT à moins
de ``MIN_GREEN_DISTANCE_BLOCKS`` (plus petite distance entre centres de
cases) d'un bunker de green devant ou sur le côté du green du même trou ;
les bunkers de green derrière le green ne comptent pas.

Site d'un bunker de green (``green_site``) : pots selon leur position dans
l'axe final (``axis_site`` : devant si tout le bunker est avant le bord
avant du green ; derrière si le centre moyen des cases est au-delà du
centre du green d'au moins son décalage latéral, cône à 45° ; côté
sinon) ; haricots : site tiré de leur enregistrement de pose
(``drawn_site``, sinon ``site``).
"""

from __future__ import annotations

import numpy as np

from golfgen.dressing.fairway import Axis

MIN_GREEN_DISTANCE_BLOCKS = 18.0
FRONT, SIDE, BEHIND = "devant", "côté", "derrière"
FRONT_SIDE_SITES = (FRONT, SIDE, "côté actuel")
CORNERS = np.array(((0, 0), (1, 0), (1, 1), (0, 1)))


def axis_site(gap: float, station: float, lateral: float) -> str:
    """Site dans l'axe final : devant, derrière ou côté."""
    if gap >= 0:
        return FRONT
    return BEHIND if station >= abs(lateral) else SIDE


def green_front(hole, hd) -> float:
    """Station (axe final, origine centre du green) du bord avant du green."""
    forward = Axis.of(hole).tangents[-1]
    return float(((np.asarray(hd.green.outline) - np.asarray(hd.green.center)) @ forward).min())


def axis_geometry(cells, hole, hd, front: float, tangent=None) -> dict:
    """Écart au bord avant du green dans l'axe, profondeur, station et
    décalage latéral moyens (origine centre du green), site dans l'axe."""
    forward = Axis.of(hole).tangents[-1]
    across = np.array((-forward[1], forward[0]))
    origin = np.asarray(hd.green.center)
    cells = np.asarray(cells, dtype=int).reshape(-1, 2)
    corners = (cells[:, None, :] + CORNERS).reshape(-1, 2)
    station = (corners - origin) @ forward
    lateral = (corners - origin) @ across
    gap = float(front - station.max())
    mean_station = float(((cells + 0.5 - origin) @ forward).mean())
    mean_lateral = float(((cells + 0.5 - origin) @ across).mean())
    out = {"gap_to_green_front_blocks": round(gap, 3),
           "depth_along_axis_blocks": round(float(station.max() - station.min()), 3),
           "station_from_green_center_blocks": round(mean_station, 3),
           "lateral_offset_blocks": round(mean_lateral, 3),
           "lateral_span_blocks": [round(float(lateral.min()), 3), round(float(lateral.max()), 3)],
           "axis_site": axis_site(gap, mean_station, mean_lateral)}
    if tangent is not None:
        t = np.asarray(tangent, dtype=float)
        out["orientation_deg"] = round(float(np.degrees(np.arctan2(t @ across, t @ forward))), 2)
    return out


def green_site(hole, hd, bunker: dict, records: list[dict]) -> str | None:
    """Site d'un bunker de green (``None`` pour un autre rôle)."""
    if bunker["role"] != "green":
        return None
    if bunker["family"] == "pot":
        return axis_geometry(bunker["cells"], hole, hd, green_front(hole, hd))["axis_site"]
    record = next((r for r in records if r.get("id") == bunker["id"]), None)
    if record is None:
        raise ValueError(f"t{hole.order} {bunker['id']} : enregistrement de pose absent")
    return record.get("drawn_site") or record["site"]


def front_side_greens(hole, hd, bunkers: list[dict], records: list[dict]) -> list[dict]:
    """Bunkers de green devant ou sur les côtés du green (derrière exclu), avec leur ``site``."""
    out = []
    for b in bunkers:
        site = green_site(hole, hd, b, records)
        if site is None or site == BEHIND:
            continue
        if site not in FRONT_SIDE_SITES:
            raise ValueError(f"t{hole.order} {b['id']} : site inconnu {site!r}")
        out.append({**b, "site": site})
    return out


def sand_distance(a, b) -> float:
    """Plus petite distance euclidienne entre centres de cases de sable (blocs)."""
    a = np.asarray(a, dtype=float).reshape(-1, 2)
    b = np.asarray(b, dtype=float).reshape(-1, 2)
    if not len(a) or not len(b):
        raise ValueError("bunker sans case de sable")
    return float(np.sqrt(((a[:, None, :] - b[None, :, :]) ** 2).sum(axis=-1).min()))


def nearest(cells, greens: list[dict]) -> dict | None:
    """Bunker de green le plus proche (relevé, distance arrondie au millième)."""
    rows = [{"hole_order": g["hole_order"], "id": g["id"], "family": g["family"], "site": g["site"],
             "distance_blocks": round(sand_distance(cells, g["cells"]), 3)} for g in greens]
    return min(rows, key=lambda r: (r["distance_blocks"], r["hole_order"], r["id"]), default=None)


def too_close(cells, greens: list[dict], min_distance: float = MIN_GREEN_DISTANCE_BLOCKS) -> bool:
    """Règle des 18 b sur la distance exacte : strictement sous ``min_distance``."""
    return any(sand_distance(cells, g["cells"]) < min_distance for g in greens)
