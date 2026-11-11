"""R3 : sélection et construction des bunkers de chaque trou.

Sélection (trous vides par trou, famille du green, famille remplacée servie
par des haricots de green sur flux dédiés, choix retirés) sur les trous figés
du corpus (``tests/data/dressing_holes_30x2.json``) ; construction sur ses
parcours habillés (eau, ordre de construction) ; puis la production :
contexte d'un layout réel en parkland, tailles et styles quelconques, eau."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from golfgen.dressing import dress_course
from golfgen.dressing.bunkers import cases as prod_cases
from golfgen.dressing.bunkers import green_phase, pot_groups, pots, selection
from golfgen.dressing.bunkers.context import BunkerContext
from golfgen.dressing.bunkers.legality import cells_dry
from golfgen.dressing.rng import (EMPTY_HOLE_STREAM, REPLACED_GREEN_SITES, REPLACED_GREEN_STREAM,
                                  RETIRED_STREAMS, RNG_LABEL, empty_hole_rng)
from golfgen.routing import muirfield as mf
from golfgen.routing.model import CourseLayout
from golfgen.routing.sites import WaterMask, load_terrain, water_mask
from tests.bunker_corpus import corpus_context, corpus_holes

R3F_LAYOUT = Path(__file__).resolve().parent / "data" / "green_pair_r3f_layout.json"
PARKLAND_PAIR_SEED = 3   # habillage parkland du layout R3f : paire (10, 17) tirée
CORPUS_SEEDS = range(1, 31)


# --- sélection ---------------------------------------------------------------------------

def test_select_specs_shape_and_refusals():
    """Clés par famille, coin extérieur des doglegs, aucune clé d'organique ;
    18 trous distincts exigés ; aucun réglage d'étude (règle des trous vides,
    coin des doglegs)."""
    families = set()
    for seed in CORPUS_SEEDS:
        holes = corpus_holes(seed)
        specs = selection.select_specs(seed, holes)
        assert [s["order"] for s in specs] == list(range(1, 19))
        by_order = {h.order: h for h in holes}
        for spec in specs:
            hole = by_order[spec["order"]]
            base = ["key", "title", "order", "empty_selected"]
            if spec["empty_selected"]:
                assert list(spec) == base
                continue
            family = spec["green_family"]
            families.add(family)
            landing = [] if hole.par == 3 else ["haricot_landing", "landing_site_draw"]
            expected = {"pot": ["pots"], "haricot": ["haricot_green", *(["pots"] if hole.par != 3 else [])],
                        selection.REPLACED_FAMILY: [*landing, "haricot_green"]}[family]
            assert list(spec) == [*base, "green_family", *expected], spec
            if "haricot_landing" in spec:
                assert spec["haricot_landing"] == (selection.OUTSIDE if hole.doglegs else selection.STRAIGHT)
                assert 0.0 <= spec["landing_site_draw"] < 1.0
    assert families == {"pot", "haricot", selection.REPLACED_FAMILY}
    assert selection.GREEN_FAMILIES == ("pot", "haricot", selection.REPLACED_FAMILY, selection.REPLACED_FAMILY)
    assert selection.DOGLEG_LANDING == selection.OUTSIDE == "outside"
    assert not {selection.FAMILY_CHOICE, selection.BEAN_SITES_CHOICE,
                selection.LANDING_SITE_CHOICE} & set(selection.RETIRED_CHOICES)
    with pytest.raises(ValueError):
        selection.select_specs(1, holes[:17])
    with pytest.raises(TypeError):
        selection.select_specs(1, holes, empty_rule="per_hole")
    with pytest.raises(TypeError):
        selection.select_specs(1, holes, dogleg_landing="outside")


def test_per_hole_empty_rule_is_seeded_and_shifts_no_stream(monkeypatch):
    """Un tirage par trou sur le flux dédié, même résultat à chaque appel ;
    les trous non vides gardent exactement leur sélection quand aucun trou
    n'est vide (``empty_holes`` forcé à l'ensemble vide) : aucun autre flux
    consommé ni décalé."""
    assert selection.EMPTY_RULE == "per_hole" and selection.EMPTY_PROBABILITY == 1 / 50
    assert EMPTY_HOLE_STREAM == 0x56494445
    runs = []
    for seed in CORPUS_SEEDS:
        holes = corpus_holes(seed)
        specs = selection.select_specs(seed, holes)
        assert specs == selection.select_specs(seed, holes)
        expected = {h.order for h in holes
                    if np.random.default_rng([seed, RNG_LABEL, h.order, EMPTY_HOLE_STREAM]).random() < 1 / 50}
        assert {s["order"] for s in specs if s["empty_selected"]} == expected
        runs.append((seed, holes, specs))
    monkeypatch.setattr(selection, "empty_holes", lambda *args, **kwargs: set())
    seen = emptied = 0
    for seed, holes, specs in runs:
        full = selection.select_specs(seed, holes)
        assert not any(s["empty_selected"] for s in full)
        for prod, filled in zip(specs, full, strict=True):
            if prod["empty_selected"]:
                assert list(prod) == ["key", "title", "order", "empty_selected"]
                emptied += 1
                continue
            assert prod == filled
            seen += 1
    assert seen > 400 and emptied


def test_per_hole_empty_rate_is_two_percent():
    """1 trou sur 50 en moyenne, chaque trou indépendamment : ni minimum ni
    plafond par parcours."""
    holes = [SimpleNamespace(order=order) for order in range(1, 19)]
    counts = np.array([len(selection.empty_holes(seed, holes)) for seed in range(5000)])
    rate = counts.sum() / (18 * len(counts))
    assert abs(rate - 0.02) < 0.0025, rate          # ±2,4 écarts-types (≈ 0,001)
    assert (counts == 0).mean() == pytest.approx(0.98 ** 18, abs=0.02)
    assert counts.max() >= 3                        # aucun plafond
    assert selection.empty_holes(7, holes) == selection.empty_holes(7, holes)
    assert selection.empty_holes(7, holes) == {h.order for h in holes if empty_hole_rng(7, h.order).random() < 0.02}


def test_replaced_family_beans_on_dedicated_stream():
    """Famille remplacée (ex-organique, tirage de la famille gardé) : nombre et
    sites des haricots de green tirés sur le flux dédié ``[seed, RNG_LABEL,
    order, REPLACED_GREEN_STREAM, 1]``, même loi que la famille haricot (1 ou
    2 sites, ordre de ``BEAN_SITES``) ; flux de la famille et des haricots
    ordinaires inchangés ; identifiants retirés jamais réemployés."""
    assert REPLACED_GREEN_STREAM == 0x4F524748 and REPLACED_GREEN_SITES == 1
    assert RETIRED_STREAMS == (0x0B6A, 0x464C4B31)
    live = (EMPTY_HOLE_STREAM, green_phase.HARICOT_FLANK_STREAM, REPLACED_GREEN_STREAM)
    assert not set(live) & set(RETIRED_STREAMS) and len(set(live)) == len(live)
    counts = {1: 0, 2: 0}
    for seed in CORPUS_SEEDS:
        for spec in selection.select_specs(seed, corpus_holes(seed)):
            if spec["empty_selected"]:
                continue
            order = spec["order"]
            index = int(np.random.default_rng([seed, selection.SELECTION_STREAM, order, selection.FAMILY_CHOICE])
                        .integers(4))
            assert spec["green_family"] == ("pot", "haricot", selection.REPLACED_FAMILY,
                                            selection.REPLACED_FAMILY)[index]
            if spec["green_family"] == "haricot":
                draw = np.random.default_rng([seed, selection.SELECTION_STREAM, order, selection.BEAN_SITES_CHOICE])
            elif selection.is_replaced(spec):
                draw = np.random.default_rng([seed, RNG_LABEL, order, REPLACED_GREEN_STREAM, 1])
            else:
                continue
            count = int(draw.integers(1, 3))
            indices = sorted(draw.choice(3, count, replace=False).tolist())
            assert spec["haricot_green"] == tuple(selection.BEAN_SITES[i] for i in indices)
            if selection.is_replaced(spec):
                assert spec["haricot_green"] == selection.replaced_green_beans(seed, order)
                counts[count] += 1
    assert min(counts.values()) > 0.3 * sum(counts.values())
    # Côté du flanc d'un haricot « devant » de la famille remplacée : flux dédié à deux mots.
    for order in (1, 9, 18):
        rng = np.random.default_rng([4, RNG_LABEL, order, REPLACED_GREEN_STREAM, 3])
        assert green_phase.side_draw(4, order, green_phase.REPLACED_FLANK_STREAM) == \
            ("droite" if rng.random() < 0.5 else "gauche")


# --- cas du parcours (construction) --------------------------------------------------------

# Graines du corpus : 1 référence, 6 trou sans zone de retombée, 8 haricot
# extérieur illégal, 24 duo d'appel passé en trio.
CASE_SEEDS = (1, 6, 8, 24)


@pytest.mark.parametrize("seed", CASE_SEEDS)
def test_course_cases_build_order_and_ids(seed):
    """Ordre de construction : pots, haricots de green, haricot de retombée,
    puis haricots de la famille remplacée (en dernier) ; ids
    ``<famille>_<rôle>_<rang>`` ; chaque rôle sélectionné posé ou manquant."""
    cases = prod_cases.course_cases(corpus_context(seed), seed)
    assert [c["hole"].order for c in cases] == list(range(1, 19))
    replaced = 0
    for case in cases:
        spec, bunkers = case["spec"], case["bunkers"]
        assert not any(b["family"] not in ("pot", "haricot") for b in bunkers)
        for rank, bunker in enumerate(bunkers, start=1):
            if bunker["family"] != "pot":
                assert bunker["id"] == f"{bunker['family']}_{bunker['role']}_{rank}"
        greens = [b for b in bunkers if b["family"] == "haricot" and b["role"] == "green"]
        missing = [m for m in case["missing"] if m["family"] == "haricot" and m["role"] == "green"]
        assert len(greens) + len(missing) == len(spec.get("haricot_green", ()))
        if selection.is_replaced(spec):
            replaced += 1
            assert bunkers[len(bunkers) - len(greens):] == greens
            assert not any(b["family"] == "pot" for b in bunkers)
        records = {r["id"]: r for r in case["records"] if r.get("family") != "pot"}
        for bunker in greens:
            assert records[bunker["id"]]["source"] == prod_cases.BEAN_GREEN_SOURCE
    assert replaced


def _ids_and_cells(cases):
    return [[(b["id"], b["cells"].tolist()) for b in c["bunkers"]] for c in cases]


def test_dry_water_mask_leaves_cases_unchanged():
    """Eau donnée mais absente : les essais au sec ne consomment aucun tirage
    de plus, mêmes poses (ids et cases) que ``water=None``."""
    dry = prod_cases.course_cases(corpus_context(1, water=WaterMask.none(400, 300)), 1)
    assert _ids_and_cells(prod_cases.course_cases(corpus_context(1), 1)) == _ids_and_cells(dry)


def _wet(width, height, cells):
    water = np.zeros((height, width), dtype=bool)
    cells = np.vstack(cells)
    water[cells[:, 1], cells[:, 0]] = True
    return WaterMask(water=water)


# Graine 1 du corpus, trou 7 : duo d'appel voulu et passé au sec.
WET_SEED, WET_ORDER = 1, 7


def test_wet_landing_duo_and_trio_are_skipped():
    """Duo d'appel mouillé : ``DUO_ERROR`` comme un duo hors fairway, la
    recherche passe au trio ; trio mouillé : l'essai est écarté."""
    context = corpus_context(WET_SEED)
    width, height = context.limits
    hole, hd = context.holes[WET_ORDER], context.dressing[WET_ORDER]
    assert hole.par != 3 and pots.desired_count(WET_SEED, WET_ORDER) == 2
    duo = pot_groups.fallback_duo(hole, hd, WET_SEED, "links")
    assert pot_groups.landing_group(hole, hd, WET_SEED, "links")["duo_to_trio"] is False
    water = _wet(width, height, duo["cells"])
    with pytest.raises(ValueError, match=pot_groups.DUO_ERROR):
        pot_groups.fallback_duo(hole, hd, WET_SEED, "links", water=water)
    placed = pot_groups.landing_group(hole, hd, WET_SEED, "links", water=water)
    assert placed["duo_to_trio"] is True and cells_dry(np.vstack(placed["cells"]), water)
    trio = pot_groups.search_trio(hole, hd, WET_SEED, "links")
    water = _wet(width, height, trio["cells"])
    wet_trio = pot_groups.search_trio(hole, hd, WET_SEED, "links", water=water)
    assert not cells_dry(np.vstack(trio["cells"]), water)
    assert wet_trio is not None and cells_dry(np.vstack(wet_trio["cells"]), water)
    assert wet_trio["valid_candidates"] < trio["valid_candidates"]


# --- production : contexte, tailles, styles, eau -------------------------------------------

def test_context_of_real_parkland_layout_with_double_green():
    """``BunkerContext.of`` sur le layout réel R3f habillé en parkland
    (paire (10, 17) tirée) : carte en blocs entiers, sans troncature."""
    case = json.loads(R3F_LAYOUT.read_text(encoding="utf-8"))["layouts"][0]
    layout = CourseLayout.from_dict(case["layout"])
    dressing = dress_course(SimpleNamespace(layout=layout), seed=PARKLAND_PAIR_SEED, style="parkland")
    assert [(p.i, p.j) for p in dressing.green_pairs] == [(10, 17)]
    context = BunkerContext.of(layout, dressing)
    assert context.style == "parkland"
    assert context.limits == (400, 300) and all(type(v) is int for v in context.limits)
    assert context.limits == (layout.width, layout.height)
    assert [t.orders for t in context.targets if t.kind == "double_green"] == [(10, 17)]
    cases = prod_cases.course_cases(context, PARKLAND_PAIR_SEED)
    assert [c["hole"].order for c in cases] == list(range(1, 19))
    for width, height in ((400.5, 300), (400, 299.9), (0, 300), (True, 300), ("400", 300), (400, "abc")):
        with pytest.raises(ValueError):
            BunkerContext(layout.holes, dressing, width, height)


# Tailles dans les bornes du générateur (petit côté 300–350, grand 400–500),
# deux orientations ; graines routées par le patron « random ».
SMOKE_COURSES = ((450, 330, 2), (350, 500, 5), (500, 300, 4))


@pytest.fixture(scope="module", params=SMOKE_COURSES, ids=lambda c: f"{c[0]}x{c[1]}")
def routed(request):
    width, height, seed = request.param
    relief = load_terrain(seed, width, height)
    return seed, relief, mf.build_course(seed, "random", relief, width=width, height=height)


@pytest.mark.parametrize("style", ("links", "parkland"))
def test_cases_run_on_any_size_and_style(routed, style):
    seed, relief, result = routed
    water = water_mask(relief)
    dressing = dress_course(result, seed=seed, style=style, relief=relief)
    context = BunkerContext.of(result.layout, dressing, water=water)
    cases = prod_cases.course_cases(context, seed)
    assert [c["hole"].order for c in cases] == list(range(1, 19))
    width, height = context.limits
    empty = [c for c in cases if c["spec"]["empty_selected"]]
    assert {c["hole"].order for c in empty} == selection.empty_holes(seed, context.holes.values())
    assert all(not c["bunkers"] and not c["records"] for c in empty)
    assert sum(len(c["bunkers"]) for c in cases) > 0
    for case in cases:
        ids = [b["id"] for b in case["bunkers"]]
        assert len(ids) == len(set(ids))
        found = {r["id"] for r in case["records"] if r["family"] != "pot" and r["status"] == "pose_found"}
        found_pots = {r["role"] for r in case["records"] if r["family"] == "pot" and r["status"] == "pose_found"}
        for bunker in case["bunkers"]:
            cells = bunker["cells"]
            assert cells.dtype.kind == "i" and cells.shape[1:] == (2,) and len(cells)
            if bunker["id"] in found or (bunker["family"] == "pot" and bunker["role"] in found_pots):
                # Pose retenue : dans la carte et au sec.
                assert (cells >= 0).all() and (cells + 1 <= (width, height)).all()
                assert cells_dry(cells, water), bunker["id"]
        assert len(case["pairs"]) == len(ids) * (len(ids) - 1) // 2
