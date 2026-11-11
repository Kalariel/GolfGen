"""Poses initiales des haricots d'un trou (round R3).

- ``green_reference`` : haricot de green tiré et orienté au site de garde
  retenu à la sonde ;
- ``bean_green_outcomes`` : ce haricot sur trois sites indépendants
  (``BEAN_SITES``) : côté actuel (repoussé latéralement jusqu'aux marges
  raster), devant et derrière (premier écart légal sur l'axe final, en
  travers de l'axe ; derrière incliné de ``REAR_PAR5_TILT_DEG`` sur les
  par 5) ; aucune pose de repli ;
- ``landing_pose`` : haricot de retombée au site tiré, sans décalage ;
  ``outside_absence`` : absence explicite d'un haricot extérieur illégal.

Production : carte ``limits`` (aucune taille figée) ; ``water`` écarte
les essais mouillés des recherches et passe aux contrôles (``None`` :
étude au bit près).
"""

from __future__ import annotations

import numpy as np

from golfgen.dressing.bunkers.beans import (K_GENTLE_MIXTURE, bean_cells, bean_outline, bunker_rng,
                                            draw_bean, haricot_length_range, orient_haricot)
from golfgen.dressing.bunkers.legality import GREEN_GAP, TEE_GAP, pose_dry, pose_record, raster_gap, shifted_pose
from golfgen.dressing.bunkers.raster import to_world
from golfgen.dressing.bunkers.sites import retained_site
from golfgen.dressing.fairway import Axis
from golfgen.dressing.green import points_in_polygon
from golfgen.dressing.rng import REPLACED_GREEN_SHAPE, replaced_green_rng
from golfgen.routing.geometry import build_hole_geometry, polygon_gap

SIDE, FRONT, REAR = BEAN_SITES = ("côté actuel", "devant", "derrière")
REAR_PAR5_TILT_DEG = 25
SEARCH_STEPS = np.arange(0.0, 40.01, 0.25)     # écarts essayés (blocs)
SEARCH_EXHAUSTED = "search_exhausted_0_to_40_blocks"
OUTSIDE_ABSENT = "absent_exterieur_illegal"


def _gap(first, second) -> float:
    return polygon_gap(tuple((float(x), float(y)) for x, y in first),
                       tuple((float(x), float(y)) for x, y in second))


# --- haricots de green --------------------------------------------------------------------

def green_reference(hole, hd, seed: int, sites: list[dict], *, replaced: bool = False) -> dict | None:
    """Haricot de garde du trou au site retenu (``bean``, ``center``,
    ``tangent``), ou ``None`` sans site légal à la sonde. ``replaced`` :
    haricots de la famille remplacée, même loi tirée sur le flux dédié
    ``replaced_green_rng(..., REPLACED_GREEN_SHAPE)``."""
    row = retained_site(sites, "green_guard")
    if row is None:
        return None
    rng = (replaced_green_rng(seed, hole.order, REPLACED_GREEN_SHAPE) if replaced
           else bunker_rng(seed, hole.order, "green_guard", "haricot"))
    draw = draw_bean(rng, haricot_length_range("green_guard", hole.par), mixture=K_GENTLE_MIXTURE)
    shape, tangent = orient_haricot(draw, row)
    return {"bean": shape.bean(draw.length), "center": np.asarray(row["center"]), "tangent": tangent}


def _make_position(baseline: dict, center: np.ndarray, tangent: np.ndarray, hd, limits, rough, *,
                   local: np.ndarray, raster_margins: bool = True, additional_greens=(),
                   water=None) -> dict | None:
    outline = to_world(local, center, tangent)
    width, height = (int(v) for v in limits)
    if (outline[:, 0].min() < 0 or outline[:, 0].max() >= width
            or outline[:, 1].min() < 0 or outline[:, 1].max() >= height):
        return None
    # Une inclusion de sommet prouve un écart nul ; les croisements sans
    # sommet intérieur passent encore par polygon_gap.
    greens = (hd.green.outline, *additional_greens)
    for green in greens:
        green_outline = np.asarray(green)
        if (points_in_polygon(outline, green_outline).any()
                or points_in_polygon(green_outline, outline).any()):
            return None
    green_gap = min(_gap(outline, green) for green in greens)
    tee_gap = min((_gap(outline, tee.outline) for tee in hd.tees), default=float("inf"))
    if green_gap < GREEN_GAP or tee_gap < TEE_GAP:
        return None
    cells = bean_cells(baseline["bean"], center, tangent, outline=local)
    if not len(cells):
        return None
    if not ((cells >= 0) & (cells + 1 <= (width, height))).all():
        return None
    raster_green_gap = min(raster_gap(cells, green) for green in greens)
    if raster_margins and raster_green_gap < GREEN_GAP:
        return None
    raster_tee_gap = min((raster_gap(cells, tee.outline) for tee in hd.tees), default=float("inf"))
    if raster_margins and raster_tee_gap < TEE_GAP:
        return None
    if not pose_dry({"outline": outline, "cells": cells}, water):
        return None
    inside = points_in_polygon(cells + 0.5, rough)
    return {"center": center, "tangent": tangent, "outline": outline, "cells": cells,
            "green_gap_blocks": round(green_gap, 2), "tee_gap_blocks": round(tee_gap, 2),
            "raster_green_gap_blocks": round(raster_green_gap, 4),
            "raster_tee_gap_blocks": round(raster_tee_gap, 4),
            "raster_cells_in_rough_band_pct": round(100.0 * float(inside.mean()), 1)}


def bean_green_outcomes(baseline: dict, hole, hd, limits, *, additional_greens=(), selected=None,
                        water=None) -> tuple[dict, dict]:
    """(poses par site, raisons d'absence par site) des sites ``selected``
    (défaut : les trois) ; ``additional_greens`` : contours des greens
    doubles du trou."""
    requested = set(BEAN_SITES if selected is None else selected)
    if not requested <= set(BEAN_SITES):
        raise ValueError("sites de haricot green inconnus")
    rough = np.asarray(build_hole_geometry(hole).rough, dtype=float)
    local = bean_outline(baseline["bean"])
    common = {"local": local, "additional_greens": additional_greens, "water": water}
    lateral = None
    if SIDE in requested:
        lateral = _make_position(baseline, baseline["center"], baseline["tangent"], hd, limits, rough,
                                 raster_margins=False, **common)
    forward = Axis.of(hole).tangents[-1]
    green_center = np.asarray(hd.green.center, dtype=float)
    across = np.array((-forward[1], forward[0]))
    # Seule une pose latérale admissible au contour est repoussée jusqu'aux
    # marges raster ; une pose absente n'est pas remplacée.
    if lateral is not None:
        sign = 1 if np.dot(baseline["center"] - green_center, across) > 0 else -1
        for offset in SEARCH_STEPS:
            adjusted = _make_position(baseline, baseline["center"] + sign * offset * across,
                                      baseline["tangent"], hd, limits, rough, **common)
            if adjusted is not None:
                adjusted["margin_offset_blocks"] = float(offset)
                lateral = adjusted
                break
        else:
            lateral = None
    result = {} if lateral is None else {SIDE: lateral}
    missing = {SIDE: "lateral_pose_rejected"} if lateral is None and SIDE in requested else {}
    for label, sign in ((FRONT, -1), (REAR, 1)):
        if label not in requested:
            continue
        tangent = across
        if label == REAR and hole.par == 5:
            theta = np.deg2rad(REAR_PAR5_TILT_DEG)
            tangent = np.cos(theta) * across + np.sin(theta) * forward
        for distance in SEARCH_STEPS:
            candidate = _make_position(baseline, green_center + sign * distance * forward, tangent, hd,
                                       limits, rough, **common)
            if candidate is not None:
                candidate["offset_from_green_center_blocks"] = float(distance)
                result[label] = candidate
                break
        else:
            missing[label] = SEARCH_EXHAUSTED
    return result, missing


# --- haricot de retombée ------------------------------------------------------------------

def landing_pose(hole, hd, placement, *, water=None) -> dict:
    """Haricot de retombée posé au site (``placement`` = ``beans.landing_placement``)."""
    return shifted_pose(hole, hd, placement, 0.0, water=water)


def outside_absence(context, hole, site: dict | None, position: dict | None) -> dict | None:
    """Absence explicite du haricot de retombée extérieur (aucun site, ou
    pose illégale au relevé), sinon ``None``."""
    base = {"family": "haricot", "role": "landing", "site": "outside", "status": OUTSIDE_ABSENT}
    if site is None:
        return {**base, "reason": "no_legal_outside_probe_site"}
    checked = pose_record({"id": "haricot_landing_outside", "family": "haricot", "role": "landing"},
                          "outside", position, hole.order, context.limits, context.targets, water=context.water)
    if checked["status"] == "pose_found":
        return None
    return {**base, "reason": "outside_pose_illegal", "rejection_checks": checked["rejection_checks"],
            "probe_site": site, "measurements": checked["measurements"],
            "center": [round(float(v), 4) for v in position["center"]]}
