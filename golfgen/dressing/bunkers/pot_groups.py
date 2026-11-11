"""Grappes de pots d'un trou : pots de green et pots d'appel (round R3).

Pots de green (``green_group``) : site de garde retenu à la sonde, nombre
tiré selon la largeur réelle du fairway à l'approche (``approach_width``),
motif tiré et légal au contour (``draw_cluster``), grappe recentrée sur
l'axe avec recul commun (``centered_variants``), puis grappe raster la
moins étalée et la moins reculée (``voxelize_group``), tailles 8/5 mêlées.

Pots d'appel (``landing_group``, hors par 3) : ancre à la première zone de
retombée (``landing_anchor``), nombre voulu (2 ou 3) ; un duo décalé
(``fallback_duo``) s'il tient la règle du fairway, sinon un trio compact
tiré (``search_trio``).

``pot_row`` : relevé d'un rôle d'un trou (``status`` ``pose_found``,
``rejected``, ``missing``, ``not_applicable``), avec, pour les pots de
green rejetés, un recul commun borné sur la grille (``correct_green_group``).

Production : carte ``limits = (largeur, hauteur)`` (aucune taille figée),
``style`` de l'habillage pour les zones de retombée et la sonde des sites
(l'étude : ``"links"``) ; ``water`` (``WaterMask`` ou ``None``) passe aux
contrôles de légalité et écarte les essais mouillés des recherches
(``None`` : étude au bit près).
"""

from __future__ import annotations

import numpy as np

from golfgen.dressing.bunkers import pots
from golfgen.dressing.bunkers.beans import ROLE_IDS
from golfgen.dressing.bunkers.legality import (MIN_FAIRWAY_CELLS, ContourClearance, cells_dry,
                                               fairway_cell_counts, pot_group_legal, pot_measurements,
                                               prepared)
from golfgen.dressing.bunkers.raster import cell_gap
from golfgen.dressing.bunkers.sites import candidates, retained_site
from golfgen.dressing.fairway import FAIRWAY_STYLES, Axis, landing_zones, profile_draws
from golfgen.dressing.green import points_in_polygon
from golfgen.dressing.rng import RNG_LABEL, fairway_rng
from golfgen.routing.geometry import polygon_gap

# Grappes de green (contours lisses) : herbe entre pots, marge au green, essais.
POT_GAP = 3.0
GREEN_GAP = 1.0
MAX_TRIES = 80
APPROACH_BLOCKS = 12.0      # coupe du fairway avant le drapeau (largeur d'approche)
CUT_REACH = 40.0            # portée de la coupe de chaque côté de l'axe
# Recentrage : fractions du décalage latéral vers l'axe, ancre à 10 b du drapeau.
CENTER_BLOCKS = 10.0
LATERAL_FRACTIONS = (0.0, 0.5, 1.0)
CENTER_BACKS = np.arange(0.0, 12.5, 0.5)
# Grappe raster : étalement et recul bornés, coût = recul + SPREAD_COST × étalement.
MAX_CENTER_SPREAD = 1.4
SPREAD_COST = 8.0
VOXEL_BACKS = np.arange(0.0, 8.5, 0.5)
# Recul commun des pots de green rejetés : pas 0,25 b, au plus 8 b sur la grille.
CORRECTION_BACKS = np.arange(0.0, 8.01, 0.25)
MAX_CORRECTION = 8.0
# Trio d'appel : essais, tirage final parmi les meilleurs.
TRIO_TRIALS = 2500
TRIO_BEST = 12
DUO_AMPLITUDE = 2.0

CENTERING_ERROR = "recentrage impossible sans conflit avec le green ou la carte"
VOXEL_ERROR = "grappe voxel impossible dans le voisinage du site frontal"
NO_LANDING_ERROR = "trou sans zone de retombée"
DUO_ERROR = "duo de repli sous le seuil fairway"
GREEN_ERRORS = {CENTERING_ERROR: "centering_unavailable", VOXEL_ERROR: "voxel_group_unavailable"}
ROLES = ("green", "landing")


# --- largeur d'approche -----------------------------------------------------------------

def intervals(polygon: np.ndarray, origin: np.ndarray, normal: np.ndarray,
              reach: float = CUT_REACH) -> list[tuple[float, float]]:
    """Intervalles intérieurs au polygone le long d'une coupe de normale ``normal``."""
    a = np.asarray(polygon, dtype=float)
    edge = np.roll(a, -1, axis=0) - a
    delta = a - origin
    denom = normal[0] * edge[:, 1] - normal[1] * edge[:, 0]
    safe = np.where(np.abs(denom) < 1e-12, np.nan, denom)
    along = (delta[:, 0] * edge[:, 1] - delta[:, 1] * edge[:, 0]) / safe
    on_edge = (delta[:, 0] * normal[1] - delta[:, 1] * normal[0]) / safe
    hits = along[(on_edge >= 0.0) & (on_edge < 1.0) & (np.abs(along) < reach)]
    cuts = np.unique(np.concatenate(([-reach], np.round(hits, 9), [reach])))
    mid = (cuts[:-1] + cuts[1:]) / 2.0
    inside = points_in_polygon(origin + mid[:, None] * normal, a)
    return [(float(lo), float(hi)) for lo, hi, keep in zip(cuts[:-1], cuts[1:], inside)
            if keep and hi - lo > 1e-9]


def merge(interval_list: list[tuple[float, float]]) -> list[tuple[float, float]]:
    result = []
    for lo, hi in sorted(interval_list):
        if result and lo <= result[-1][1] + 1e-8:
            result[-1] = (result[-1][0], max(result[-1][1], hi))
        else:
            result.append((lo, hi))
    return result


def approach_width(hole, hd) -> float:
    """Largeur de fairway ``APPROACH_BLOCKS`` avant le drapeau, sans le rough."""
    axis = Axis.of(hole)
    point, normal = axis.at(np.array([axis.length - APPROACH_BLOCKS]))
    spans = merge([span for fairway in hd.fairway
                   for span in intervals(np.asarray(fairway.outline), point[0], normal[0])])
    return sum(hi - lo for lo, hi in spans)


# --- pots de green -------------------------------------------------------------------------

def draw_cluster(hole, hd, limits, style: str, seed: int, *, water=None) -> dict:
    """Nombre et motif seedés au site de garde ; ``missing`` si aucun site ou motif."""
    sites = candidates(hole, style=style, green=hd.green, tees=hd.tees, seed=seed)
    row = retained_site(sites, "green_guard")
    if row is None:
        return {"missing": "no_probe_site"}
    width = approach_width(hole, hd)
    rng = pots.cluster_rng(seed, hole.order)
    count = pots.draw_count(width, rng)
    tangent = Axis.of(hole).tangents[-1]
    anchor = np.asarray(row["center"], dtype=float)
    clearance = ContourClearance(hd, limits, green_gap=GREEN_GAP, water=water)
    for attempt in range(MAX_TRIES):
        motif_index = int(rng.integers(len(pots.MOTIFS[count])))
        shapes = pots.candidate_outlines(pots.MOTIFS[count][motif_index], anchor, tangent, rng)
        if clearance.legal(shapes, grass_gap=POT_GAP):
            gaps = [polygon_gap(tuple(map(tuple, left)), tuple(map(tuple, right)))
                    for index, left in enumerate(shapes) for right in shapes[index + 1:]]
            return {"count": count, "approach_width_blocks": round(width, 2),
                    "probabilities": [round(p, 3) for p in pots.count_probs(width)],
                    "site_side": row["side"], "anchor": row["center"],
                    "attempt": attempt + 1, "motif": motif_index,
                    "minimum_pot_gap_blocks": round(min(gaps), 2),
                    "shapes": shapes}
    return {"count": count, "approach_width_blocks": round(width, 2),
            "probabilities": [round(p, 3) for p in pots.count_probs(width)],
            "site_side": row["side"], "missing": "no_cluster_at_site"}


def centered_variants(hole, hd, limits, cluster: dict, *, water=None
                      ) -> tuple[float, float, list[tuple[np.ndarray, ...]]]:
    """(décalage latéral, recul commun, contours par fraction de recentrage) :
    plus petit recul légal pour toutes les fractions ; ``ValueError`` sinon."""
    axis = Axis.of(hole)
    tangent = axis.tangents[-1]
    normal = np.array((-tangent[1], tangent[0]))
    point, _ = axis.at(np.array([axis.length - CENTER_BLOCKS]))
    center = np.mean([shape.mean(axis=0) for shape in cluster["shapes"]], axis=0)
    lateral = float((center - point[0]) @ normal)
    clearance = ContourClearance(hd, limits, green_gap=GREEN_GAP, water=water)
    for backward in CENTER_BACKS:
        shifted = [tuple(shape - fraction * lateral * normal - backward * tangent
                         for shape in cluster["shapes"])
                   for fraction in LATERAL_FRACTIONS]
        if all(clearance.legal(shapes, grass_gap=POT_GAP) for shapes in shifted):
            return lateral, float(backward), shifted
    raise ValueError(CENTERING_ERROR)


def voxelize_group(hole, hd, limits, cluster: dict, *, water=None) -> dict:
    """Grappe raster du motif recentré : étalement et recul de moindre coût."""
    _, common_back, centered = centered_variants(hole, hd, limits, cluster, water=water)
    smooth_centers = np.asarray([shape.mean(axis=0) for shape in centered[-1]])
    tangent = Axis.of(hole).tangents[-1]
    choices = []
    green, squares = prepared(hd.green.outline), {}
    for scale in np.arange(1.0, MAX_CENTER_SPREAD + 0.01, 0.1):
        for back in VOXEL_BACKS:
            group = pots.group_at(smooth_centers, tangent, scale, back)
            if pot_group_legal(group, hd, limits, green=green, squares=squares, water=water):
                cost = float(back + SPREAD_COST * (scale - 1.0))
                choices.append((round(cost, 6), float(back), round(float(scale), 2), group))
    if not choices:
        raise ValueError(VOXEL_ERROR)
    _, back, scale, group = min(choices, key=lambda choice: choice[:3])
    gaps = [cell_gap(left, right) for index, left in enumerate(group) for right in group[index + 1:]]
    return {"pots": group, "center_spread_scale": scale,
            "extra_back_blocks": round(back, 2),
            "smooth_common_back_blocks": common_back,
            "minimum_grass_blocks": round(min(gaps), 2)}


def green_group(hole, hd, limits, style: str, seed: int, *, water=None) -> dict:
    """Pots de green du trou (``cells``, ``desired_count``) ou absence (``reason``)."""
    cluster = draw_cluster(hole, hd, limits, style, seed, water=water)
    if "missing" in cluster:
        return {"reason": cluster["missing"], "desired_count": cluster.get("count")}
    try:
        voxel = voxelize_group(hole, hd, limits, cluster, water=water)
    except ValueError as error:
        if str(error) not in GREEN_ERRORS:
            raise
        return {"reason": GREEN_ERRORS[str(error)], "desired_count": cluster["count"]}
    bases = tuple(cells[0] - pots.OFFSETS[0] for cells in voxel["pots"])
    sizes = pots.mixed_sizes(seed, hole.order, cluster["count"])
    return {"cells": tuple(pots.pot_cells(base, small=small) for base, small in zip(bases, sizes, strict=True)),
            "desired_count": cluster["count"]}


def correct_green_group(group, hole, limits, targets, *, water=None):
    """Recul commun borné, sur la grille entière ; ni motif ni taille modifiés.
    (cases, relevé, décalage) au premier recul sans échec, sinon ``None``."""
    tangent = Axis.of(hole).tangents[-1]
    seen = set()
    for back in CORRECTION_BACKS:
        offset = np.rint(-back * tangent).astype(int)
        key = tuple(offset)
        if key in seen or np.linalg.norm(offset) > MAX_CORRECTION:
            continue
        seen.add(key)
        shifted = tuple(p + offset for p in group)
        measured = pot_measurements(shifted, hole.order, limits, targets, water=water)
        if not measured["failures"]:
            return shifted, measured, offset
    return None


# --- pots d'appel --------------------------------------------------------------------------

def landing_anchor(hole, seed: int, style: str) -> dict:
    """Ancre à la première zone de retombée du fairway (``style``)."""
    axis = Axis.of(hole)
    zones = landing_zones(axis, hole.par, profile_draws(fairway_rng(seed, hole.order), FAIRWAY_STYLES[style]))
    if not zones:
        raise ValueError(NO_LANDING_ERROR)
    s = zones[0]
    center, normals = axis.at(np.array((s,)))
    segment = np.searchsorted(axis.starts, s, side="right") - 1
    return {"s_blocks": round(float(s), 3), "center": center[0],
            "normal": normals[0], "tangent": axis.tangents[segment],
            "landing_zone_count": len(zones)}


def trio_rng(seed: int, order: int) -> np.random.Generator:
    return np.random.default_rng([seed, RNG_LABEL, order, pots.TRIO_STREAM, ROLE_IDS["landing"]])


def search_trio(hole, hd, seed: int, style: str, trials: int = TRIO_TRIALS, *, water=None) -> dict | None:
    """Trio compact tiré autour de l'ancre : herbe ≥ ``MIN_GRASS``, au moins
    ``MIN_FAIRWAY_CELLS`` cases par pot dans le fairway ; choix seedé parmi
    les ``TRIO_BEST`` meilleurs scores. ``None`` si aucun essai ne passe."""
    anchor = landing_anchor(hole, seed, style)
    rng = trio_rng(seed, hole.order)
    choices = []
    for trial in range(trials):
        half_width = rng.uniform(2.4, 4.2)
        across = np.array((-half_width, rng.uniform(-1.4, 1.4), half_width))
        across -= across.mean()
        along = rng.uniform(-6.0, 6.0, size=3)
        along -= along.mean()
        if (np.ptp(along) < 5.0 or np.min(np.diff(np.sort(along))) < 0.7
                or abs(along[0] - 2 * along[1] + along[2]) < 2.0):
            continue
        shift = rng.uniform((-1.0, -1.5), (1.0, 1.5))
        cells = pots.raster_group(anchor, across, along, shift)
        gap = pots.minimum_gap(cells)
        if gap < pots.MIN_GRASS:
            continue
        fairway = fairway_cell_counts(cells, hd)
        if min(fairway) < MIN_FAIRWAY_CELLS:
            continue
        if water is not None and not cells_dry(np.vstack(cells), water):
            continue
        # Grappe compacte proche du centre ; plusieurs solutions gardées pour le tirage.
        score = (0.55 * np.ptp(across) + 0.45 * np.ptp(along)
                 + 0.4 * np.linalg.norm(shift) + 0.03 * (24 - sum(fairway)))
        choices.append((float(score), trial, cells, fairway, gap, across, along, shift))
    if not choices:
        return None
    choices.sort(key=lambda item: (item[0], item[1]))
    selected = choices[int(rng.integers(min(TRIO_BEST, len(choices))))]
    _, trial, cells, fairway, gap, across, along, shift = selected
    return {"cells": cells, "fairway_cells": fairway, "minimum_grass_blocks": gap,
            "across_offsets_blocks": np.round(across, 2).tolist(),
            "along_offsets_blocks": np.round(along, 2).tolist(),
            "site_shift_blocks": np.round(shift, 2).tolist(),
            "trial": trial, "valid_candidates": len(choices), "anchor": anchor}


def fallback_duo(hole, hd, seed: int, style: str, *, water=None) -> dict:
    """Duo décalé de ``DUO_AMPLITUDE`` ; ``ValueError`` (``DUO_ERROR``) sous
    la règle du fairway ou, ``water`` donnée, sur l'eau : comme un duo hors
    fairway, la recherche passe alors au trio."""
    anchor = landing_anchor(hole, seed, style)
    spacing = pots.shared_spacing(anchor, seed, hole.order, 2)
    along = pots.stagger_offsets(seed, hole.order, 2, DUO_AMPLITUDE)
    cells = pots.landing_group(anchor, 2, spacing, along)
    fairway = fairway_cell_counts(cells, hd)
    if min(fairway) < MIN_FAIRWAY_CELLS:
        raise ValueError(DUO_ERROR)
    if water is not None and not cells_dry(np.vstack(cells), water):
        raise ValueError(DUO_ERROR)
    return {"cells": cells, "fairway_cells": fairway,
            "minimum_grass_blocks": pots.minimum_gap(cells), "anchor": anchor,
            "spacing_blocks": spacing, "along_offsets_blocks": along.tolist()}


def landing_group(hole, hd, seed: int, style: str, *, water=None) -> dict:
    """Pots d'appel du trou : duo voulu s'il passe, sinon trio ; ou absence."""
    if hole.par == 3:
        return {"not_applicable": "par3"}
    try:
        landing_anchor(hole, seed, style)
    except ValueError as error:
        if str(error) != NO_LANDING_ERROR:
            raise
        return {"not_applicable": "no_landing_zone"}
    desired = pots.desired_count(seed, hole.order)
    if desired == 2:
        try:
            duo = fallback_duo(hole, hd, seed, style, water=water)
        except ValueError as error:
            if str(error) != DUO_ERROR:
                raise
        else:
            return {"cells": duo["cells"], "desired_count": desired, "duo_to_trio": False}
    trio = search_trio(hole, hd, seed, style, water=water)
    if trio is None:
        return {"reason": "no_validated_trio", "desired_count": desired}
    return {"cells": trio["cells"], "desired_count": desired, "duo_to_trio": desired == 2}


# --- relevé d'un rôle -----------------------------------------------------------------

def size_label(limits) -> str:
    """Taille ``"LxH"`` des relevés (comme l'étude)."""
    width, height = (int(v) for v in limits)
    return f"{width}x{height}"


def pot_row(context, hole, role: str, seed: int) -> dict:
    """Relevé des pots ``role`` (``"green"`` / ``"landing"``) du trou ``hole``
    dans ``context`` (``BunkerContext``) : mêmes clés que l'étude, cases
    en listes (``cells``) si une grappe est construite."""
    if role not in ROLES:
        raise ValueError("rôles pots green/landing attendus")
    hd, limits, water = context.dressing[hole.order], context.limits, context.water
    placed = (green_group(hole, hd, limits, context.style, seed, water=water) if role == "green"
              else landing_group(hole, hd, seed, context.style, water=water))
    row = {"seed": seed, "size": size_label(limits), "order": hole.order,
           "par": hole.par, "dogleg": bool(hole.doglegs), "role": role,
           **{k: v for k, v in placed.items() if k != "cells"}}
    if "not_applicable" in placed:
        row.update(status="not_applicable", reason=placed["not_applicable"])
        del row["not_applicable"]
    elif "reason" in placed:
        row["status"] = "missing"
    else:
        measured = pot_measurements(placed["cells"], hole.order, limits, context.targets,
                                    hd=hd if role == "landing" else None, water=water)
        if measured["failures"] and role == "green":
            row["before"] = {"cells": [p.tolist() for p in placed["cells"]], "measurements": measured}
            corrected = correct_green_group(placed["cells"], hole, limits, context.targets, water=water)
            if corrected is not None:
                cells, measured, offset = corrected
                placed["cells"] = cells
                row["adjustment"] = {"offset_blocks": offset.tolist(),
                                     "distance_blocks": round(float(np.linalg.norm(offset)), 4)}
        row.update(status="rejected" if measured["failures"] else "pose_found",
                   measurements=measured, cells=[p.tolist() for p in placed["cells"]])
    return row
