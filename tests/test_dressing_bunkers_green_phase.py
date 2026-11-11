"""Phase green des bunkers (``golfgen.dressing.bunkers.green_phase``, round R4).

Sur des graines du corpus (links 400×300, sans eau) : bunkers de fairway
retirés, cibles (haricots « devant », côté tiré ou opposé au haricot côté,
flux du côté propre à la famille remplacée), poses de flanc, reculs le long
de l'axe ; statuts rares sur des scénarios synthétiques (option a′, échec).
Puis un parcours routé d'une autre taille, en parkland, avec eau.
"""

from __future__ import annotations

import numpy as np
import pytest

from golfgen.dressing import dress_course
from golfgen.dressing.bunkers import cases as prod_cases
from golfgen.dressing.bunkers import access, green_phase
from golfgen.dressing.bunkers.context import BunkerContext
from golfgen.dressing.bunkers.legality import cells_dry
from golfgen.dressing.bunkers.selection import is_replaced
from golfgen.dressing.fairway import Axis
from golfgen.dressing.rng import RNG_LABEL
from golfgen.routing import muirfield as mf
from golfgen.routing.sites import load_terrain, water_mask
from tests.bunker_corpus import corpus_context

# Graines du corpus : 1 un seul haricot « devant » (famille remplacée), 3 et 5
# haricots « devant » des deux familles, côté tiré et opposé au haricot côté.
SEEDS = (1, 3, 5)


@pytest.fixture(scope="module", params=SEEDS, ids=lambda s: f"graine{s}")
def corpus_run(request):
    seed = request.param
    context = corpus_context(seed)
    cases = prod_cases.course_cases(context, seed)
    rows, after = green_phase.green_phase(cases, context, seed)
    return seed, context, cases, rows, after


def test_stripped_and_targets(corpus_run):
    seed, context, cases, rows, after = corpus_run
    targets, replaced = [], set()
    for case in cases:
        stripped = green_phase.stripped(case)
        assert [b["id"] for b in stripped["bunkers"]] == [b["id"] for b in case["bunkers"] if b["role"] != "landing"]
        assert stripped["records"] is case["records"]
        found = green_phase.green_targets(stripped)
        assert all(b["family"] == "haricot" and b["role"] == "green" and green_phase.is_devant(case, b)
                   for b in found)
        for bunker in found:
            targets.append((case["hole"].order, bunker["id"]))
            shape = green_phase.haricot_shape(case, bunker, seed, context)
            expected = green_phase.REPLACED_FLANK_STREAM if is_replaced(case["spec"]) else \
                green_phase.HARICOT_FLANK_STREAM
            assert shape["side_stream"] == expected
            side = green_phase.cote_side(case)
            if side is None:
                assert shape["side"] is None and shape["side_rule"] == green_phase.DRAWN
            else:
                assert shape["side"] != side and shape["side_rule"] == green_phase.OPPOSITE
            if is_replaced(case["spec"]):
                replaced.add(case["hole"].order)
    assert [(r["hole_order"], r["id"]) for r in rows] == targets and targets and replaced
    for order in (1, 9, 18):
        for stream in (green_phase.HARICOT_FLANK_STREAM, green_phase.REPLACED_FLANK_STREAM):
            words = stream if isinstance(stream, tuple) else (stream,)
            draw = np.random.default_rng([seed, RNG_LABEL, order, *words]).random()
            assert green_phase.side_draw(seed, order, stream) == ("droite" if draw < 0.5 else "gauche")


def test_flank_rows(corpus_run):
    seed, context, cases, rows, after = corpus_run
    by_order = {c["hole"].order: c for c in after}
    for row in rows:
        assert row["family"] == "haricot" and row["theta_tried"] == len(row["trials"]) >= 1
        if row["status"] == green_phase.FAILED:
            assert row["position"] is None and row["reasons"]
            continue
        assert row["status"] in green_phase.POSED and row["topology_pass"] and row["access_pass"]
        assert row["theta_deg"] in green_phase.THETAS_DEG and row["concave_toward_green"]
        (bunker,) = [b for b in by_order[row["hole_order"]]["bunkers"] if b["id"] == row["id"]]
        assert np.array_equal(bunker["cells"], row["position"]["cells"])
        record = next(r for r in by_order[row["hole_order"]]["records"] if r.get("id") == row["id"])
        assert record["source"] == green_phase.SOURCE and record["drawn_site"] == green_phase.SITE


def test_offsets_and_translated(corpus_run):
    seed, context, cases, rows, after = corpus_run
    seen = 0
    for case in cases:
        for bunker in case["bunkers"][:2]:
            steps = green_phase.offsets(case["hole"], bunker["cells"], 12)
            ks = [k for k, _ in steps]
            assert ks[0] == 0 and not steps[0][1].any() and ks == sorted(set(ks)) and ks[-1] <= 12
            assert len({tuple(o) for _, o in steps}) == len(steps)
            assert [k for k, _ in green_phase.offsets(case["hole"], bunker["cells"], 4)] == [k for k in ks if k <= 4]
            for _, offset in steps:
                moved = green_phase.translated(bunker, offset)
                assert np.array_equal(moved["cells"], np.asarray(bunker["cells"]) + offset)
                for key in ("outline", "center"):
                    if bunker.get(key) is not None:
                        np.testing.assert_allclose(moved[key], np.asarray(bunker[key], dtype=float) + offset)
                seen += 1
    assert seen


# --- statuts rares : option a′, échec, aucune pose légale (scénarios synthétiques) ----------

# Trou 12 de la graine 1 (haricot « devant » de la famille remplacée, côté
# opposé au haricot côté, « droite ») ; murs de sable posés en travers de tout
# son fairway, à ces stations (blocs avant le centre du green, épaisseur 2),
# et carte rognée (``BunkerContext.limits``).
SYNTHETIC_SEED, SYNTHETIC_ORDER = 1, 12
ONE_WALL, TWO_WALLS = (25.0,), (25.0, 30.0)
CROPPED = (190, 300)


def _walled(cases, stations):
    """Copie du parcours, murs ``mur_<k>`` (haricots de fairway) ajoutés au trou."""
    index = SYNTHETIC_ORDER - 1
    case = cases[index]
    hd = case["hd"]
    fairway = green_phase.fairway_cells(hd)
    station = (fairway + 0.5 - np.asarray(hd.green.center)) @ Axis.of(case["hole"]).tangents[-1]
    walls = [{"id": f"mur_{k + 1}", "family": "haricot", "role": "landing",
              "cells": fairway[(station >= -s - 2) & (station < -s)].astype(int), "outline": None}
             for k, s in enumerate(stations)]
    return [*cases[:index], {**case, "bunkers": [*case["bunkers"], *walls]}, *cases[index + 1:]]


def _flank(stations, cropped=None):
    context = corpus_context(SYNTHETIC_SEED, limits=cropped)
    cases = _walled([green_phase.stripped(c) for c in prod_cases.course_cases(context, SYNTHETIC_SEED)], stations)
    case = cases[SYNTHETIC_ORDER - 1]
    (bunker,) = green_phase.green_targets(case)
    assert is_replaced(case["spec"]) and green_phase.devant_side(case) == "droite"
    return green_phase.flank_pose(case, bunker, cases, context, seed=SYNTHETIC_SEED,
                                  shape=green_phase.haricot_shape(case, bunker, SYNTHETIC_SEED, context))


def test_flank_pose_ignores_blocking_culprit():
    """Un mur seul bloque le green : coupable retiré du contrôle d'accès (option a′)."""
    row = _flank(ONE_WALL)
    assert row["green_preblocked"] and row["status"] == green_phase.POSED_IGNORING
    assert [c["id"] for c in row["access_ignored_culprits"]] == ["mur_1"]
    assert row["position"] is not None


def test_flank_pose_fails_without_culprit_and_legal_pose():
    """Deux murs : aucun coupable seul, chaque θ échoue (accès, contact, ou
    aucune pose légale de 0 à 40 blocs sur la carte rognée) : échec."""
    row = _flank(TWO_WALLS, CROPPED)
    assert row["green_preblocked"] and not row["access_ignored_culprits"]
    assert row["status"] == green_phase.FAILED and row["position"] is None
    statuses = {t["status"] for t in row["trials"]}
    assert statuses == {green_phase.NO_LEGAL_POSE, green_phase.CONTACT_STOP, access.FAIL}
    assert row["reasons"][green_phase.NO_LEGAL_POSE] and row["theta_tried"] == len(green_phase.THETAS_DEG)


# --- production : autre taille, parkland, eau, trous vides par trou ------------------------

def test_green_phase_runs_on_parkland_with_water():
    width, height, seed = 450, 330, 2
    relief = load_terrain(seed, width, height)
    result = mf.build_course(seed, "random", relief, width=width, height=height)
    water = water_mask(relief)
    dressing = dress_course(result, seed=seed, style="parkland", relief=relief)
    context = BunkerContext.of(result.layout, dressing, water=water)
    cases = prod_cases.course_cases(context, seed)
    rows, after = green_phase.green_phase(cases, context, seed)
    assert [c["hole"].order for c in after] == list(range(1, 19))
    targets = [b["id"] for c in cases for b in green_phase.green_targets(green_phase.stripped(c))]
    assert [r["id"] for r in rows] == targets and rows
    assert {r["status"] for r in rows} <= {*green_phase.POSED, green_phase.FAILED}
    posed = {(r["hole_order"], r["id"]) for r in rows if r["status"] in green_phase.POSED}
    assert posed
    for case, original in zip(after, cases):
        assert all(b["role"] == "green" for b in case["bunkers"])
        assert [b["id"] for b in case["bunkers"]] == [b["id"] for b in original["bunkers"] if b["role"] == "green"]
        if original["spec"]["empty_selected"]:
            assert not case["bunkers"]
        for bunker in case["bunkers"]:
            if (case["hole"].order, bunker["id"]) in posed:
                cells = bunker["cells"]
                assert (cells >= 0).all() and (cells + 1 <= context.limits).all()
                assert cells_dry(cells, water), bunker["id"]
                record = next(r for r in case["records"] if r.get("id") == bunker["id"])
                assert record["source"] == green_phase.SOURCE and record["status"] == "pose_found"
    again, _ = green_phase.green_phase(cases, context, seed)
    assert [(r["id"], r["status"], r.get("theta_deg"), r.get("offset_blocks")) for r in again] == \
        [(r["id"], r["status"], r.get("theta_deg"), r.get("offset_blocks")) for r in rows]
