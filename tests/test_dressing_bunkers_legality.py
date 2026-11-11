"""Légalité des poses de bunkers (``golfgen.dressing.bunkers.legality``,
round R2) face à l'eau : poses, grappes de pots, sonde au site et contexte,
sur le parcours de production d'une graine du corpus (links 400×300 :
construction, phase green, phase fairway)."""

from __future__ import annotations

import numpy as np
import pytest

from golfgen.dressing.bunkers import cases as prod_cases
from golfgen.dressing.bunkers import fairway_phase, green_phase, legality
from golfgen.dressing.water import is_dry
from golfgen.routing.geometry import build_hole_geometry
from golfgen.routing.sites import WaterMask
from tests.bunker_corpus import corpus_context

SEED = 1


@pytest.fixture(scope="module")
def run():
    """Chemin de production de la graine ``SEED`` : construction, greens, fairway."""
    prod = corpus_context(SEED)
    built = prod_cases.course_cases(prod, SEED)
    _, after = green_phase.green_phase(built, prod, SEED)
    _, placed = fairway_phase.fairway_phase(built, after, prod)
    return {"prod": prod, "built": built, "after": after, "placed": placed}


def _wet(limits, cells) -> WaterMask:
    width, height = limits
    water = np.zeros((height, width), dtype=bool)
    for x, y in np.asarray(cells, dtype=int).reshape(-1, 2):
        water[y, x] = True
    return WaterMask(water=water)


def _legal_pose(run):
    """Première pose de haricot de green retenue : légale
    pour ``pose_record`` comme pour ``FlankAudit``."""
    prod = run["prod"]
    for case in run["after"]:
        for bunker in case["bunkers"]:
            if bunker.get("outline") is None or bunker["role"] != "green":
                continue
            failure, _, _ = legality.FlankAudit(prod, case["hole"].order).check(bunker)
            if failure is None:
                return case, bunker
    raise AssertionError("aucune pose légale")


def test_pose_on_water_is_rejected(run):
    prod = run["prod"]
    case, bunker = _legal_pose(run)
    order = case["hole"].order
    one_cell = bunker["cells"][len(bunker["cells"]) // 2]
    wet = _wet(prod.limits, [one_cell])
    dry = WaterMask.none(*prod.limits)
    reference = legality.pose_record({}, "s", bunker, order, prod.limits, prod.targets)
    assert reference["status"] == "pose_found"
    for water, rejected in ((None, False), (dry, False), (wet, True)):
        record = legality.pose_record({}, "s", bunker, order, prod.limits, prod.targets, water=water)
        if rejected:
            assert record["status"] == "missing"
            assert record["rejection_checks"] == [legality.WATER_FAILURE]
        else:
            assert record == reference
        wet_context = corpus_context(SEED, water=water)
        assert wet_context.audit(order).failures(bunker) == ([legality.WATER_FAILURE] if rejected else [])
        failure, _, _ = legality.FlankAudit(wet_context, order).check(bunker)
        assert failure == (legality.FlankAudit.AUDIT if rejected else None)
    # Contour seul sur l'eau (aucune case) : refusé aussi (sable dessiné au sec exigé).
    outline_cell = np.floor(bunker["outline"][0]).astype(int)
    if not {tuple(outline_cell)} & set(map(tuple, bunker["cells"].tolist())):
        record = legality.pose_record({}, "s", bunker, order, prod.limits, prod.targets,
                                      water=_wet(prod.limits, [outline_cell]))
        assert legality.WATER_FAILURE in record["rejection_checks"]
    # Sonde au site : haricot_checks refuse le contour mouillé.
    hd = case["hd"]
    rough = np.asarray(build_hole_geometry(case["hole"]).rough, dtype=float)
    assert not legality.haricot_checks(bunker["outline"], rough, hd.green, hd.tees, wet)["dry"]
    assert not legality.haricot_checks(bunker["outline"], rough, hd.green, hd.tees, wet)["legal"]


def test_pots_on_water_are_rejected(run):
    prod = run["prod"]
    for case in run["placed"]:
        group = tuple(np.asarray(b["cells"], dtype=int) for b in case["bunkers"]
                      if b["family"] == "pot" and b["role"] == "landing")
        if len(group) < 2:
            continue
        order, hd = case["hole"].order, case["hd"]
        base = legality.pot_measurements(group, order, prod.limits, prod.targets, hd=hd)
        wet = _wet(prod.limits, [group[-1][0]])
        assert legality.pot_measurements(group, order, prod.limits, prod.targets, hd=hd, water=None) == base
        measured = legality.pot_measurements(group, order, prod.limits, prod.targets, hd=hd, water=wet)
        assert measured["failures"] == [*base["failures"], legality.WATER_FAILURE]
        assert not legality.pot_group_legal(group, hd, prod.limits, water=wet)
        x, y = group[-1][0]
        shapes = (np.array(((x, y), (x + 1, y), (x + 1, y + 1), (x, y + 1)), dtype=float) + 0.25,)
        assert legality.ContourClearance(hd, prod.limits).legal(shapes)
        assert not legality.ContourClearance(hd, prod.limits, water=wet).legal(shapes)
        return
    pytest.skip("aucune grappe de pots d'appel posée")


def test_cells_dry_is_is_dry_of_each_square():
    rng = np.random.default_rng(7)
    water = WaterMask(water=rng.random((40, 50)) < 0.05)
    for _ in range(200):
        cells = rng.integers(-2, 52, size=(int(rng.integers(1, 6)), 2))
        squares = [np.array(((x, y), (x + 1, y), (x + 1, y + 1), (x, y + 1)), dtype=float) for x, y in cells]
        assert legality.cells_dry(cells, water) == all(is_dry(s, water, 0.0) for s in squares)
    assert legality.cells_dry(np.zeros((0, 2), dtype=int), water)
    assert legality.cells_dry(np.array(((3, 4),)), None)


def test_context_rejects_water_of_another_size():
    with pytest.raises(ValueError):
        corpus_context(SEED, water=WaterMask.none(10, 10))
