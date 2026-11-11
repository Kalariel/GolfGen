"""Bunkers d'un parcours entier (``golfgen.dressing.bunkers.place_bunkers``, round R5).

Résultat figé (empreinte de tout ``CourseBunkers``) sur des graines du
corpus et des parcours routés ; bunkers signalés synthétiques (flanc en
échec, pose mouillée) retirés du sable ; production : parcours routés
d'autres tailles, links et parkland, avec eau et règle des trous vides par
trou ; déterminisme et résultat figé ; haricots de green de la famille
remplacée (ex-organiques).
"""

from __future__ import annotations

from dataclasses import FrozenInstanceError
import hashlib
import inspect
import json
from types import SimpleNamespace

import numpy as np
import pytest

from golfgen.dressing import dress_course
from golfgen.dressing.bunkers import CourseBunkers, PlacedBunker, place_bunkers, place_bunkers_json
from golfgen.dressing.bunkers import cases as prod_cases
from golfgen.dressing.bunkers import course as bunkers_course
from golfgen.dressing.bunkers import access, green_phase
from golfgen.dressing.bunkers.legality import WATER_FAILURE, cells_dry, pose_record
from golfgen.dressing.bunkers.selection import EMPTY_RULE, is_replaced, select_specs
from golfgen.dressing.fairway import Axis
from golfgen.routing import muirfield as mf
from golfgen.routing.sites import WaterMask, load_terrain, water_mask
from tests.bunker_corpus import corpus_context, corpus_dressing


def fingerprint(out: CourseBunkers) -> str:
    """Empreinte de tout le résultat : graine, trous vides, sable posé (id,
    trou, famille, rôle, statut, cases), non posés (étape, raisons, ids,
    site, pose signalée)."""
    def pose(b):
        return None if b is None else [b.id, b.hole, b.family, b.role, b.status, b.cells.tolist()]
    payload = [out.seed, out.empty_rule, list(out.empty_holes), [pose(b) for b in out.bunkers],
               [[u.hole, u.family, u.role, u.stage, list(u.reasons), list(u.ids), u.site, pose(u.pose)]
                for u in out.unplaced]]
    return hashlib.sha256(json.dumps(payload, ensure_ascii=False).encode()).hexdigest()


# --- résultat figé ----------------------------------------------------------------------------

# Empreintes de la production au 2026-11-02, identiques à celles de l'ancienne
# option ``green_organics="haricot"`` (vérifié sur 9db06e7) :
# tout changement de comportement des bunkers les fait échouer ; à mettre à
# jour seulement pour un changement voulu et validé.
CORPUS_FINGERPRINTS = {3: "3c66341e5511bf88d066083d984d7d2bf3247300413e5e80937171ce94fe4fea",
                       7: "34e7b0ff65fd305957f4ed15e9c07a48cef3f37b00f362bbeef7a4e5519f89cd"}


@pytest.mark.parametrize("seed", sorted(CORPUS_FINGERPRINTS), ids=lambda s: f"graine{s}")
def test_corpus_result_is_frozen(seed):
    holes, dressing = corpus_dressing(seed)
    layout = SimpleNamespace(holes=holes, width=400, height=300)
    out = place_bunkers(layout, dressing, seed)
    assert fingerprint(out) == CORPUS_FINGERPRINTS[seed]
    assert {b.family for b in out.bunkers} <= {"pot", "haricot"}


def test_public_api_has_no_study_knobs():
    assert list(inspect.signature(place_bunkers).parameters) == ["layout", "dressing", "seed", "water"]
    assert list(inspect.signature(place_bunkers_json).parameters) == ["data", "dressing"]
    assert list(inspect.signature(prod_cases.course_cases).parameters) == ["context", "seed"]


# --- bunkers signalés : retirés du sable, raisons gardées (scénarios synthétiques) ----------

# Trou 12 de la graine 1 du corpus (haricot « devant » de la famille
# remplacée), carte rognée et deux murs de sable en travers du fairway : le
# flanc échoue (cf. ``test_flank_pose_fails_without_culprit_and_legal_pose``
# de la phase green). Eau : la pose construite du haricot est inondée.
FLAGGED_SEED, FLAGGED_ORDER, CROPPED, WALLS = 1, 12, (190, 300), (25.0, 30.0)


def _walled(cases):
    index = FLAGGED_ORDER - 1
    case = cases[index]
    hd = case["hd"]
    fairway = green_phase.fairway_cells(hd)
    station = (fairway + 0.5 - np.asarray(hd.green.center)) @ Axis.of(case["hole"]).tangents[-1]
    walls = [{"id": f"mur_{k + 1}", "family": "haricot", "role": "landing",
              "cells": fairway[(station >= -s - 2) & (station < -s)].astype(int), "outline": None}
             for k, s in enumerate(WALLS)]
    return [*cases[:index], {**case, "bunkers": [*case["bunkers"], *walls]}, *cases[index + 1:]]


def _failed_flank(cases, context, bunker_id):
    walled = _walled(cases)
    case = walled[FLAGGED_ORDER - 1]
    bunker = next(b for b in case["bunkers"] if b["id"] == bunker_id)
    row = green_phase.flank_pose(case, bunker, walled, context, seed=FLAGGED_SEED,
                                 shape=green_phase.haricot_shape(case, bunker, FLAGGED_SEED, context))
    assert row["status"] == green_phase.FAILED and row["position"] is None
    return row


@pytest.fixture(scope="module")
def flagged_setup():
    dry = corpus_context(FLAGGED_SEED, limits=CROPPED)
    cases = [green_phase.stripped(c) for c in prod_cases.course_cases(dry, FLAGGED_SEED)]
    case = cases[FLAGGED_ORDER - 1]
    (devant,) = green_phase.green_targets(case)
    grid = np.zeros(CROPPED[::-1], dtype=bool)
    grid[devant["cells"][:, 1], devant["cells"][:, 0]] = True
    water = WaterMask(grid)
    wet = corpus_context(FLAGGED_SEED, limits=CROPPED, water=water)
    # Pose construite gardée bien que refusée par l'eau (relevé refait avec l'eau).
    record = next(r for r in case["records"] if r.get("id") == devant["id"])
    rechecked = pose_record({k: devant[k] for k in ("id", "family", "role")}, record["site"], devant,
                            FLAGGED_ORDER, wet.limits, wet.targets, water=water)
    records = [rechecked if r is record else r for r in case["records"]]
    wet_cases = [*cases[:FLAGGED_ORDER - 1], {**case, "records": records}, *cases[FLAGGED_ORDER:]]
    return {"devant": devant, "water": water, "cases": cases, "wet_cases": wet_cases,
            "dry_row": _failed_flank(cases, dry, devant["id"]),
            "wet_row": _failed_flank(wet_cases, wet, devant["id"])}


def _legal_sand_only(out, water, flagged_id):
    assert all(b.status not in bunkers_course.FLAGGED_STATUSES for b in out.bunkers)
    assert flagged_id not in [b.id for b in out.of_hole(FLAGGED_ORDER)]
    for b in out.bunkers:
        assert cells_dry(b.cells, water), b
        assert (b.cells >= 0).all() and (b.cells + 1 <= CROPPED).all(), b
    (flagged,) = out.flagged()
    assert flagged.hole == FLAGGED_ORDER and flagged.ids == (flagged_id,) and flagged.pose.id == flagged_id
    return flagged


def test_failed_flank_is_unplaced_with_its_reasons(flagged_setup):
    """Sans eau : flanc en échec, pose de construction légale gardée hors du sable."""
    devant, row = flagged_setup["devant"], flagged_setup["dry_row"]
    out = bunkers_course.assemble(FLAGGED_SEED, flagged_setup["cases"], [row], [])
    flagged = _legal_sand_only(out, None, devant["id"])
    assert flagged.stage == bunkers_course.STAGE_GREEN and flagged.pose.status == bunkers_course.FLANK_FAILED
    assert flagged.reasons == tuple(row["reasons"]) and WATER_FAILURE not in flagged.reasons
    assert set(flagged.reasons) <= {green_phase.NO_LEGAL_POSE, green_phase.CONTACT_STOP, access.SAND_FAILURE}
    assert green_phase.NO_LEGAL_POSE in flagged.reasons
    assert np.array_equal(flagged.pose.cells, devant["cells"])
    assert out.summary()["flagged"] == {bunkers_course.FLANK_FAILED: 1}


def test_flagged_pose_without_reason_fails_loudly(flagged_setup):
    """Flanc en échec sans aucune raison (relevé incomplet) : erreur nommant le bunker."""
    devant, row = flagged_setup["devant"], {**flagged_setup["dry_row"], "reasons": {}}
    with pytest.raises(ValueError, match=f"trou {FLAGGED_ORDER}, bunker '{devant['id']}'.*sans aucune raison"):
        bunkers_course.assemble(FLAGGED_SEED, flagged_setup["cases"], [row], [])


def test_wet_flagged_bunkers_are_unplaced(flagged_setup):
    """Pose construite sur l'eau : refusée (construction) puis flanc en échec (green)."""
    devant, water, cases = flagged_setup["devant"], flagged_setup["water"], flagged_setup["wet_cases"]
    assert not cells_dry(devant["cells"], water)
    rejected = bunkers_course.assemble(FLAGGED_SEED, cases, [], [])
    flagged = _legal_sand_only(rejected, water, devant["id"])
    assert flagged.stage == bunkers_course.STAGE_CONSTRUCTION and flagged.pose.status == bunkers_course.REJECTED
    assert flagged.reasons == (WATER_FAILURE,)
    row = flagged_setup["wet_row"]
    failed = bunkers_course.assemble(FLAGGED_SEED, cases, [row], [])
    flagged = _legal_sand_only(failed, water, devant["id"])
    assert flagged.stage == bunkers_course.STAGE_GREEN and flagged.pose.status == bunkers_course.FLANK_FAILED
    assert flagged.reasons == (WATER_FAILURE, *row["reasons"])
    assert not cells_dry(flagged.pose.cells, water)


# --- production : autres tailles et styles, eau, trous vides par trou -----------------------

PRODUCTION = [(450, 330, 2, "parkland"), (300, 400, 4, "links")]


@pytest.fixture(scope="module", params=PRODUCTION, ids=lambda p: f"{p[0]}x{p[1]}-{p[3]}")
def produced(request):
    width, height, seed, style = request.param
    relief = load_terrain(seed, width, height)
    result = mf.build_course(seed, "random", relief, width=width, height=height)
    water = water_mask(relief)
    dressing = dress_course(result, seed=seed, style=style, relief=relief)
    return result.layout, dressing, seed, water, place_bunkers(result.layout, dressing, seed, water=water)


def test_production_course(produced):
    layout, dressing, seed, water, out = produced
    assert isinstance(out, CourseBunkers) and out.empty_rule == EMPTY_RULE == "per_hole" and out.seed == seed
    assert out.bunkers and {b.hole for b in out.bunkers} <= set(range(1, 19))
    assert [b.hole for b in out.bunkers] == sorted(b.hole for b in out.bunkers)
    limits = (int(layout.width), int(layout.height))
    for hole in range(1, 19):
        ids = [b.id for b in out.of_hole(hole)]
        assert len(ids) == len(set(ids))
        if hole in out.empty_holes:
            assert not ids
    for b in out.bunkers:
        assert b.cells.dtype == np.int64 and b.cells.ndim == 2 and b.cells.shape[1] == 2 and len(b.cells)
        assert (b.cells >= 0).all() and (b.cells + 1 <= limits).all(), b
        assert b.family in ("pot", "haricot") and b.role in ("green", "landing")
        assert b.status in bunkers_course.STATUSES and b.status not in bunkers_course.FLAGGED_STATUSES
        assert cells_dry(b.cells, water), b
    for u in out.unplaced:
        assert u.stage in bunkers_course.STAGES and u.reasons and all(isinstance(r, str) for r in u.reasons)
        if u.pose is not None:
            assert u.pose.status in bunkers_course.FLAGGED_STATUSES and u.ids == (u.pose.id,)
            assert u.stage == (bunkers_course.STAGE_GREEN if u.pose.status == bunkers_course.FLANK_FAILED
                               else bunkers_course.STAGE_CONSTRUCTION)


# Empreintes des parcours routés (même règle que ``CORPUS_FINGERPRINTS``).
PRODUCTION_FINGERPRINTS = {
    (450, 330, 2, "parkland"): "a16d19ae0a4fe5057c19eb88ccb3ea68e5bcf9aa7e48fb67a49512cef3b732bf",
    (300, 400, 4, "links"): "ccfc65081683bdc1a758c6848d49c7f2913a71896d198b699e016e1d01d90d38"}


def test_production_result_is_frozen(produced):
    layout, dressing, seed, water, out = produced
    key = (int(layout.width), int(layout.height), seed, dressing.style)
    assert fingerprint(out) == PRODUCTION_FINGERPRINTS[key]


def test_production_is_deterministic_and_frozen(produced):
    layout, dressing, seed, water, out = produced
    again = place_bunkers(layout, dressing, seed, water=water)
    assert again == out and again is not out
    bunker = out.bunkers[0]
    with pytest.raises(FrozenInstanceError):
        bunker.status = bunkers_course.BUILT
    with pytest.raises(ValueError):
        bunker.cells[0, 0] = -1
    with pytest.raises(ValueError):
        bunker.cells.setflags(write=True)
    with pytest.raises(TypeError):
        hash(out)
    with pytest.raises(TypeError):
        hash(bunker)
    flagged = PlacedBunker("x", 1, "pot", "green", [[0, 0]], bunkers_course.REJECTED)
    with pytest.raises(ValueError):
        CourseBunkers(seed, (), (flagged,), ())
    with pytest.raises(ValueError):
        PlacedBunker("x", 1, "pot", "green", [[0, 0]], "inconnu")
    shifted = PlacedBunker(bunker.id, bunker.hole, bunker.family, bunker.role, bunker.cells + 1, bunker.status)
    assert shifted != bunker


# --- famille remplacée : haricots de green sur flux dédiés ----------------------------------

def test_replaced_family_beans_in_course(produced):
    """Trous de la famille remplacée : chaque haricot de green tiré est posé
    ou non posé (avec ses raisons), aucun autre bunker de green ; ids des
    autres bunkers du trou avant eux (construits en dernier)."""
    layout, dressing, seed, water, out = produced
    specs = select_specs(seed, layout.holes)
    replaced = [s for s in specs if is_replaced(s)]
    assert replaced
    for spec in replaced:
        order = spec["order"]
        greens = [b for b in out.of_hole(order) if b.role == "green"]
        unplaced = [u for u in out.unplaced if u.hole == order and u.role == "green"]
        assert all(b.family == "haricot" for b in greens) and all(u.family == "haricot" for u in unplaced)
        assert len(greens) + len(unplaced) == len(spec["haricot_green"]), order
        assert all(u.reasons for u in unplaced)
        landing = [int(b.id.rsplit("_", 1)[1]) for b in out.of_hole(order) if b.role == "landing" and b.family != "pot"]
        ranks = [int(b.id.rsplit("_", 1)[1]) for b in greens]
        assert not landing or not ranks or max(landing) < min(ranks)
