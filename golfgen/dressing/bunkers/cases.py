"""Construction des bunkers initiaux de chaque trou : les « cas » (round R3).

``course_cases(context, seed)`` = sélection (``selection.select_specs``,
coin extérieur des doglegs) puis ``build_cases`` : pour chaque trou, les
poses de sa sélection, dans l'ordre pots, haricots de green, haricot de
retombée, puis haricots de green de la famille remplacée
(``selection.is_replaced`` : construits en dernier, à la place de l'ancien
organique de green). Les essais rejetés par un contrôle restent posés et
visibles (``records``) ; aucune autre pose n'est choisie à leur place.

Contrat d'un cas (``BunkerCase``, dict ; la phase green et la phase
fairway le recopient avec ``{**case, "bunkers": ...}``) :

- ``spec`` : ``HoleSpec`` du trou ;
- ``hole`` : ``ElasticHole`` ; ``hd`` : ``HoleDressing`` du trou ;
- ``bunkers`` : ``Bunker`` posés, dans l'ordre de pose ; ``id`` =
  ``pot_<rôle>_<i>`` (rang dans la grappe) ou ``<famille>_<rôle>_<n>``
  (rang parmi les bunkers du trou), ``family`` (``pot``, ``haricot``),
  ``role`` (``green``, ``landing``), ``cells`` (cases de sable ``(k, 2)``,
  int) et ``outline`` (contour monde, ``None`` des pots), plus pour les
  haricots ``center``, ``tangent`` et les mesures de leur pose ;
- ``records`` : relevés de pose (``pot_groups.pot_row`` par rôle de pots,
  ``legality.pose_record`` complété pour les autres), avec ``source`` ;
- ``missing`` : rôles sélectionnés sans pose (``family``, ``role``,
  ``site`` éventuel, ``reason``) ;
- ``pairs`` : contacts et écarts entre bunkers du trou (``interactions``).

Production : contexte ``BunkerContext`` (taille et style quelconques,
``water`` éventuelle).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, TypedDict

import numpy as np

from golfgen.dressing.bunkers import placements, pot_groups
from golfgen.dressing.bunkers.beans import landing_placement
from golfgen.dressing.bunkers.legality import pose_record
from golfgen.dressing.bunkers.raster import cell_gap
from golfgen.dressing.bunkers.selection import OUTSIDE, HoleSpec, is_replaced, select_specs
from golfgen.dressing.bunkers.sites import candidates, corner_position

if TYPE_CHECKING:
    from golfgen.dressing.model import HoleDressing
    from golfgen.routing.model import ElasticHole

# Provenance des relevés (``records[*]["source"]``).
POT_SOURCE = "pot_groups.pot_row"
BEAN_GREEN_SOURCE = "placements.bean_green_outcomes"
LANDING_SOURCE = "placements.landing_pose(0)"


class Bunker(TypedDict, total=False):
    id: str
    family: str
    role: str
    cells: np.ndarray
    outline: np.ndarray | None
    center: np.ndarray
    tangent: np.ndarray


class BunkerCase(TypedDict):
    spec: HoleSpec
    hole: ElasticHole
    hd: HoleDressing
    bunkers: list[Bunker]
    records: list[dict]
    missing: list[dict]
    pairs: list[dict]


def interactions(bunkers: list[dict]) -> list[dict]:
    """Écart et cases partagées de chaque paire de bunkers (aucun seuil)."""
    rows = []
    for index, left in enumerate(bunkers):
        first = {tuple(cell) for cell in left["cells"]}
        for right in bunkers[index + 1:]:
            shared = first.intersection(map(tuple, right["cells"]))
            gap = cell_gap(left["cells"], right["cells"])
            rows.append({"first": left["id"], "second": right["id"],
                         "families": [left["family"], right["family"]],
                         "gap_blocks": round(gap, 4), "shared_sand_cells": len(shared),
                         "contact": gap == 0})
    return rows


def build_case(context, spec: HoleSpec, seed: int) -> BunkerCase:
    """Poses de la sélection ``spec`` d'un trou de ``context`` (``BunkerContext``)."""
    hole = context.holes[spec["order"]]
    hd = context.dressing[hole.order]
    limits, targets, water = context.limits, context.targets, context.water
    sites = (candidates(hole, style=context.style, green=hd.green, tees=hd.tees, seed=seed)
             if "haricot_green" in spec or "haricot_landing" in spec else [])
    bunkers, records, missing = [], [], []

    def add_position(family, role, label, position, *, source, **details):
        if position is None:
            missing.append({"family": family, "role": role, "site": label, "reason": "pose_unavailable"})
            return
        identity = f"{family}_{role}_{len(bunkers) + 1}"
        checked = pose_record({"id": identity, "family": family, "role": role}, label, position,
                              hole.order, limits, targets, water=water)
        checked.update(source=source, **details)
        records.append(checked)
        # Essai visible même rejeté : aucune autre pose ne le remplace.
        bunkers.append({"id": identity, "family": family, "role": role, **position})

    if "pots" in spec:
        roles = (spec["pots"],) if isinstance(spec["pots"], str) else spec["pots"]
        for role in roles:
            group = pot_groups.pot_row(context, hole, role, seed)
            records.append({"family": "pot", **group, "source": POT_SOURCE})
            if "cells" in group:
                for index, cells in enumerate(group["cells"]):
                    bunkers.append({"id": f"pot_{role}_{index + 1}", "family": "pot", "role": role,
                                    "cells": np.asarray(cells, dtype=int), "outline": None})
            else:
                missing.append({"family": "pot", "role": role, "reason": group.get("reason", group["status"])})
    def add_green_beans():
        reference = placements.green_reference(hole, hd, seed, sites, replaced=replaced)
        if reference is None:
            positions, absent = {}, {label: "no_legal_probe_reference" for label in spec["haricot_green"]}
        else:
            extra = [t.outline for t in targets if t.kind == "double_green" and hole.order in t.orders]
            positions, absent = placements.bean_green_outcomes(reference, hole, hd, limits, additional_greens=extra,
                                                               selected=spec["haricot_green"], water=water)
        for label in spec["haricot_green"]:
            if label not in positions:
                missing.append({"family": "haricot", "role": "green", "site": label,
                                "reason": absent.get(label, "pose_unavailable")})
            else:
                add_position("haricot", "green", label, positions[label], source=BEAN_GREEN_SOURCE)

    # Famille remplacée : haricots de green construits en dernier dans le trou.
    replaced = is_replaced(spec)
    if "haricot_green" in spec and not replaced:
        add_green_beans()
    if "haricot_landing" in spec:
        kind = spec["haricot_landing"]
        pool = [s for s in sites if s["role"] == "landing" and s["legal"] and corner_position(hole, s) == kind]
        site = pool[int(spec.get("landing_site_draw", 0.0) * len(pool))] if pool else None
        position = None
        if site is not None:
            drawn = landing_placement(seed, hole.order, hole.par, site)
            position = placements.landing_pose(hole, hd, drawn, water=water)
        absent = placements.outside_absence(context, hole, site, position) if kind == OUTSIDE else None
        if absent is not None:
            # Règle validée (2026-11-01) : pose extérieure illégale -> aucun
            # haricot de retombée ; ni repli intérieur, ni nouveau tirage.
            missing.append(absent)
        else:
            add_position("haricot", "landing", kind, position, source=LANDING_SOURCE, probe_site=site)
    if "haricot_green" in spec and replaced:
        add_green_beans()
    return {"spec": spec, "hole": hole, "hd": hd, "bunkers": bunkers,
            "records": records, "missing": missing, "pairs": interactions(bunkers)}


def build_cases(context, specs: list[HoleSpec], seed: int) -> list[BunkerCase]:
    """Un cas par sélection, dans l'ordre de ``specs``."""
    return [build_case(context, spec, seed) for spec in specs]


def course_cases(context, seed: int) -> list[BunkerCase]:
    """Sélection du parcours (coin extérieur des doglegs, trous vides par
    trou) puis construction."""
    return build_cases(context, select_specs(seed, list(context.holes.values())), seed)
