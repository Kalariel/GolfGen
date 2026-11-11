"""Phase fairway des bunkers (``golfgen.dressing.bunkers.fairway_phase``, round R5).

Valeurs adoptées (recul max 12 b, règle des 18 b, contrôle d'accès), sans
réglage ; sur des graines du corpus (links 400×300, sans eau), enchaînée
sur la phase green : relevés par unité et parcours final. Graine 6 : grappe
de pots et haricot droit reculés ; graine 7 : grappe reculée et grappe non
posée (18 b). Puis les refus explicites.
"""

from __future__ import annotations

import inspect

import numpy as np
import pytest

from golfgen.dressing.bunkers import cases as prod_cases
from golfgen.dressing.bunkers import fairway_phase, green_phase
from tests.bunker_corpus import corpus_context

SEEDS = (6, 7)
# Unités non posées attendues (raison) par graine.
NOT_PLACED = {6: set(), 7: {("grappe_pots", "18b")}}


@pytest.fixture(scope="module", params=SEEDS, ids=lambda s: f"graine{s}")
def phases(request):
    seed = request.param
    context = corpus_context(seed)
    cases = prod_cases.course_cases(context, seed)
    _, after = green_phase.green_phase(cases, context, seed)
    rows, final = fairway_phase.fairway_phase(cases, after, context)
    return seed, context, cases, after, rows, final


def test_adopted_values_without_knobs():
    assert fairway_phase.ADOPTED_MAX_SLIDE_BLOCKS == 12
    assert fairway_phase.MIN_GREEN_DISTANCE_BLOCKS == 18.0
    assert list(inspect.signature(fairway_phase.fairway_phase).parameters) == ["built", "green_after", "context"]


def test_fairway_phase_rows_and_final(phases):
    seed, context, cases, after, rows, final = phases
    units = [(c["hole"].order, u["kind"], u["ids"]) for c in cases for u in fairway_phase.landing_units(c)]
    assert [(r["hole_order"], r["kind"], r["ids"]) for r in rows] == units and rows
    statuses = {(r["kind"], r["status"]) for r in rows}
    assert (fairway_phase.POTS, fairway_phase.SLID) in statuses
    assert (seed != 6) or (fairway_phase.STRAIGHT, fairway_phase.SLID) in statuses
    assert {(r["kind"], r["reason"]) for r in rows if r["status"] == fairway_phase.NOT_PLACED} == NOT_PLACED[seed]
    for row in rows:
        assert row["max_slide_blocks"] == fairway_phase.ADOPTED_MAX_SLIDE_BLOCKS
        assert row["slides"] == (row["kind"] in fairway_phase.SLIDING_KINDS)
        assert all(0 <= t["slide_blocks"] <= fairway_phase.ADOPTED_MAX_SLIDE_BLOCKS for t in row["trials"])
        if row["status"] == fairway_phase.NOT_PLACED:
            assert row["reason"] in (fairway_phase.REASON_DISTANCE, fairway_phase.REASON_ACCESS,
                                     fairway_phase.REASON_OTHER)
            assert all(t["failures"] for t in row["trials"])
        else:
            # Première position sans aucun échec, translation déjà essayée sautée.
            assert row["status"] in fairway_phase.PLACED and not row["trials"][-1]["failures"]
            assert all(t["failures"] for t in row["trials"][:-1])
            assert (row["slide_blocks"] == 0) == (row["status"] == fairway_phase.IN_PLACE)
    # Dogleg extérieur : contrôle en place seulement.
    assert all(len(r["trials"]) == 1 for r in rows if r["kind"] == fairway_phase.DOGLEG)
    placed = {(r["hole_order"], i) for r in rows if r["status"] in fairway_phase.PLACED for i in r["ids"]}
    dropped = {(r["hole_order"], i) for r in rows if r["status"] == fairway_phase.NOT_PLACED for i in r["ids"]}
    for case, green_case in zip(final, after, strict=True):
        order = case["hole"].order
        ids = [b["id"] for b in case["bunkers"]]
        assert len(ids) == len(set(ids))
        landing = {(order, b["id"]) for b in case["bunkers"] if b["role"] == "landing"}
        assert landing <= placed and not landing & dropped
        greens = [(b["id"], np.asarray(b["cells"]).tolist()) for b in case["bunkers"] if b["role"] == "green"]
        assert greens == [(b["id"], np.asarray(b["cells"]).tolist()) for b in green_case["bunkers"]]
    again, _ = fairway_phase.fairway_phase(cases, after, context)
    assert [(r["ids"], r["status"], r["slide_blocks"]) for r in again] == \
        [(r["ids"], r["status"], r["slide_blocks"]) for r in rows]


def test_refusals(phases):
    seed, context, cases, after, rows, final = phases
    case = next(c for c in cases if c["spec"].get("haricot_landing"))
    with pytest.raises(ValueError):
        fairway_phase.landing_units({**case, "spec": {**case["spec"], "haricot_landing": "inside"}})
