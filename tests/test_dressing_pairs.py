"""Greens doubles, sélection (``golfgen.dressing.pairs``, rounds R3a, R3c et
R3f ; forme et oracle : ``tests/test_dressing_pair_shape.py``).

Layouts complets : instantané ``tests/data/green_pairs_layouts.json``
(9 layouts du cache de la mesure des greens doubles : rounds rc-30 et
land-30, patrons muirfield et muirfield_inverse ; choisis, à la plage R3a–R3e
[12, 35], pour couvrir 0, 1, 2 et 3 paires valides, un rejet par contrôle
``coeur`` et un blocage par écart entre paires). ``before_r3a_sha256`` :
empreintes des greens et départs habillés calculées avec le code d'avant
R3a (commit ``before_r3a_commit``), même calcul que ``_digest``.

R3f : ``PAIR_DISTANCE`` = [12, 20] ne laisse aucune candidate sur
l'instantané. La mécanique de sélection (glouton, écarts, plafond, tirage,
traces) ne dépend pas de la plage : ses tests sur l'instantané tournent à
la plage R3a–R3e (fixture ``r3e_range``, ``PAIR_DISTANCE`` remplacée), avec
les formes R3f. La plage de production est testée sur le seul layout réel
du corpus qui a une paire à [12, 20] (``tests/data/green_pair_r3f_layout.json``,
land-30 muirfield seed 1 : 10/17 en links)."""

from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from golfgen.dressing import RNG_LABEL, STYLE_SPECS, GreenPair, dress_course
from golfgen.dressing import course as course_module
from golfgen.dressing import pairs as pairs_module
from golfgen.dressing.course import (COURSE_ORDER, PAIR_STREAM, TEE_STREAM, green_rng, pair_rng,
                                     tee_rng)
from golfgen.dressing.model import PairRejection
from golfgen.dressing.pair_shape import GreensOverlapError, PairShapeError
from golfgen.dressing.pairs import (CONTROLS, ORACLE_CHECKS, PAIR_REJECTION_CAUSES, PAIR_RULES,
                                    candidate_pairs, footprint, greedy_select, pair_checks,
                                    pair_selection, select_green_pairs, shape_and_check,
                                    valid_pairs)
from golfgen.routing.geometry import build_hole_geometry, polygon_gap, segment_crosses_polygon
from golfgen.routing.model import ControlPoint, CourseLayout, ElasticHole
from tests.test_dressing_fairway import green_repr, tees_repr
from tests.test_routing_geometry import build_synthetic_layout

SNAPSHOT = Path(__file__).resolve().parent / "data" / "green_pairs_layouts.json"
R3F_LAYOUT = Path(__file__).resolve().parent / "data" / "green_pair_r3f_layout.json"
# Seeds d'habillage de l'empreinte (en plus de la seed du routage) : u64
# d'un mot, de deux mots, maximale.
DIGEST_SEEDS = (1, 2 ** 32 + 7, 2 ** 64 - 1)

# Règles validées (R3a ; plage R3f), réécrites ici sans passer par le module testé.
RANGE = (12.0, 20.0)
R3E_RANGE = (12.0, 35.0)        # plage de R3a à R3e (instantané)
GAP = 5.0
MAX_PAIRS = {"links": 2, "parkland": 1}
PARKLAND_P = 0.25
EPS = 1e-7


@pytest.fixture(scope="module")
def snapshot():
    data = json.loads(SNAPSHOT.read_text(encoding="utf-8"))
    cases = [(f"{c['round']}_{c['pattern']}_{c['seed']}", c["seed"],
              CourseLayout.from_dict(c["layout"])) for c in data["layouts"]]
    return cases, data["before_r3a_sha256"]


@pytest.fixture
def r3e_range(monkeypatch):
    """Plage R3a–R3e [12, 35] pour les tests de mécanique sur l'instantané."""
    monkeypatch.setattr(pairs_module, "PAIR_DISTANCE", R3E_RANGE)
    return R3E_RANGE


@pytest.fixture(scope="module")
def r3f_case():
    """Layout réel à paire de production (land-30 muirfield seed 1)."""
    case = json.loads(R3F_LAYOUT.read_text(encoding="utf-8"))["layouts"][0]
    return case["seed"], CourseLayout.from_dict(case["layout"])


def _dress(layout, seed, style="links"):
    return dress_course(SimpleNamespace(layout=layout), seed=seed, style=style)


def _cores(layout):
    return {h.order: build_hole_geometry(h).core for h in layout.holes}


def _outlines(dressing):
    return {order: hd.green.outline for order, hd in dressing.holes.items()}


def _valid(layout, seed=1, style="links"):
    return valid_pairs(layout, _dress(layout, seed, style).holes, _cores(layout))


def _shaper(layout, dressing):
    """Rappel de forme de la production (``shape_and_check``) pour ``greedy_select``."""
    cores = _cores(layout)
    return lambda pair, done: shape_and_check(layout, dressing.holes, cores, pair, done)[0]


def _bare(pair):
    """Paire sans sa forme (comparaison avec les valides de la sélection)."""
    return GreenPair(i=pair.i, j=pair.j, distance=pair.distance, footprint=pair.footprint)


def _digest(dressing) -> str:
    # lot 1 eau : champs ``island`` retirés du ``repr`` d'un green ou d'une
    # boîte au sec (``green_repr``, ``tees_repr``, qui vérifient qu'ils
    # valent ``None``), référence d'avant ces champs inchangée ; même texte
    # que ``repr([(o, green, tees, cause), ...])``
    text = "[" + ", ".join(
        f"({o!r}, {green_repr(hd.green)}, {tees_repr(hd.tees)}, {hd.tee_fallback_cause!r})"
        for o, hd in sorted(dressing.holes.items())) + "]"
    return hashlib.sha256(text.encode()).hexdigest()


# --- candidates -----------------------------------------------------------------

def _greens(positions):
    """Trous réduits à ``order`` et ``green`` (seuls lus par
    ``candidate_pairs``) ; trous absents de ``positions`` : très loin."""
    return [SimpleNamespace(order=o, green=ControlPoint(*positions.get(o, (1e4 * o, 1e4))))
            for o in range(1, 19)]


def test_candidates_exclude_consecutive_and_9_18():
    # 9/10, 9/18, 10/18 à 14 blocs (triangle) ; 1/3, 3/5 et 4/5 à 20 blocs ;
    # 4/5 consécutifs
    holes = _greens({9: (0, 0), 10: (14, 0), 18: (7, 7 * math.sqrt(3)), 1: (580, 0),
                     3: (600, 0), 5: (620, 0), 4: (640, 0)})
    pairs = {(i, j) for i, j, _ in candidate_pairs(holes)}
    assert (9, 10) not in pairs and (9, 18) not in pairs and (4, 5) not in pairs
    assert {(1, 3), (3, 5), (10, 18)} <= pairs
    holes = _greens({1: (0, 0), 18: (20, 0)})
    assert [(i, j) for i, j, _ in candidate_pairs(holes)] == [(1, 18)]


@pytest.mark.parametrize("d, kept", [(11.99, False), (12.0, True), (17.0, True),
                                     (20.0, True), (20.01, False), (23.0, False)])
def test_candidates_distance_range(d, kept):
    pairs = candidate_pairs(_greens({2: (0, 0), 7: (d, 0)}))
    assert [(i, j) for i, j, _ in pairs] == ([(2, 7)] if kept else [])
    if kept:
        assert pairs[0][2] == pytest.approx(d)


def test_candidates_range_is_read_at_call_time(monkeypatch):
    """``bounds=None`` : ``PAIR_DISTANCE`` lue à l'appel (plage R3a–R3e
    possible dans les tests) ; plage explicite prioritaire."""
    holes = _greens({2: (0, 0), 7: (30.0, 0)})
    assert candidate_pairs(holes) == []
    assert [(i, j) for i, j, _ in candidate_pairs(holes, R3E_RANGE)] == [(2, 7)]
    monkeypatch.setattr(pairs_module, "PAIR_DISTANCE", R3E_RANGE)
    assert [(i, j) for i, j, _ in candidate_pairs(holes)] == [(2, 7)]


def test_rule_constants():
    assert pairs_module.PAIR_DISTANCE == RANGE
    assert (pairs_module.CORE_GAP, pairs_module.TEE_GAP, pairs_module.CLUBHOUSE_MIN,
            pairs_module.PAIR_GAP) == (5.0, 5.0, 10.0, GAP)
    assert pairs_module.EXCLUDED_PAIRS == {(9, 18)}
    assert set(PAIR_RULES) == set(STYLE_SPECS)
    assert {s: r.max_pairs for s, r in PAIR_RULES.items()} == MAX_PAIRS
    assert PAIR_RULES["links"].probability is None
    assert PAIR_RULES["parkland"].probability == PARKLAND_P


# --- empreinte et contrôles ------------------------------------------------------

def test_footprint_is_hull_of_the_dressed_outlines(snapshot):
    cases, _ = snapshot
    for case, seed, layout in cases:
        dressing = _dress(layout, seed)
        for pair in _valid(layout, seed)[0]:
            hull = pair.footprint
            assert pair.distance == pytest.approx(math.dist(
                (layout.holes[pair.i - 1].green.x, layout.holes[pair.i - 1].green.y),
                (layout.holes[pair.j - 1].green.x, layout.holes[pair.j - 1].green.y)))
            points = np.asarray(dressing[pair.i].green.outline + dressing[pair.j].green.outline)
            vertices = {tuple(p) for p in points.tolist()}
            assert set(hull) <= vertices, case
            # convexe, sens trigonométrique, contient tous les sommets
            h = np.asarray(hull)
            edge = np.roll(h, -1, axis=0) - h
            side = (edge[:, None, 0] * (points[None, :, 1] - h[:, None, 1])
                    - edge[:, None, 1] * (points[None, :, 0] - h[:, None, 0]))
            assert (side >= -1e-9).all(), case


def test_core_check_rejects_a_footprint_over_another_fairway():
    layout = build_synthetic_layout()
    # greens 1 (y=180) et 3 (y=140) encadrent le trou 2 (y=160)
    hull = footprint(_disk((100.0, 180.0)), _disk((100.0, 140.0)))
    checks = pair_checks(layout, 1, 3, hull, _cores(layout), ())
    assert checks["coeur"][0] is False
    assert tuple(checks) == CONTROLS


def _disk(center, radius=5.0, n=16):
    return tuple((center[0] + radius * math.cos(2 * math.pi * k / n),
                  center[1] + radius * math.sin(2 * math.pi * k / n)) for k in range(n))


@pytest.mark.parametrize("dx, crosses", [(5e-9, True), (1e-3, False)])
def test_link_prefilter_keeps_contact_within_epsilon(dx, crosses):
    """Le préfiltre des liaisons ne saute pas une liaison dont la boîte est à
    moins de ``EPSILON`` de celle de l'empreinte : ``segments_intersect``
    compte ce contact comme une traversée."""
    hull = ((0.0, 0.0), (10.0, 0.0), (10.0, 10.0), (0.0, 10.0))
    start, end = (10.0 + dx, 5.0), (20.0, 5.0)
    assert segment_crosses_polygon(start, end, hull) is crosses
    link = SimpleNamespace(from_hole_order=5, to_hole_order=6,
                           start=ControlPoint(*start), end=ControlPoint(*end))
    layout = SimpleNamespace(holes=(), links=(link,), clubhouse=ControlPoint(200.0, 200.0),
                             width=400.0, height=400.0)
    assert pair_checks(layout, 1, 3, hull, {}, ())["liaisons"] == (
        (False, [[5, 6]]) if crosses else (True, []))


def test_tee_check_uses_the_dressed_tee_box_outlines():
    """R3c : le contrôle ``tees`` porte sur les contours des boîtes de départ
    habillées, pas sur le point ``hole.tee`` : une boîte à 4 blocs de
    l'empreinte la rejette, à 5 blocs elle passe."""
    hull = ((0.0, 0.0), (10.0, 0.0), (10.0, 10.0), (0.0, 10.0))
    layout = SimpleNamespace(holes=(), links=(), clubhouse=ControlPoint(200.0, 200.0),
                             width=400.0, height=400.0)
    for gap, expected in ((4.0, (False, pytest.approx(4.0))), (4.999, (False, pytest.approx(4.999))),
                          (5.0, (True, math.inf))):      # ≥ 5 : écarté par le préfiltre exact
        box = ((10.0 + gap, 4.0), (14.0 + gap, 4.0), (14.0 + gap, 6.0), (10.0 + gap, 6.0))
        assert pair_checks(layout, 1, 3, hull, {}, (box,))["tees"] == expected
    assert pair_checks(layout, 1, 3, hull, {}, ())["tees"] == (True, math.inf)


def test_greedy_select_skips_pairs_rejected_by_the_shape():
    """Une valide dont la forme est rejetée est écartée (ni retenue ni
    comptée bloquée) : la suivante est examinée."""
    valid = [_pair(1, 3, 20.0, 0, 0), _pair(4, 7, 21.0, 0, 100), _pair(5, 8, 22.0, 0, 200)]
    chosen, blocked = greedy_select(valid, 2, shape=lambda p, done: None if p.i == 1 else p)
    assert [(p.i, p.j) for p in chosen] == [(4, 7), (5, 8)] and blocked == 0


def test_core_check_prefilter_matches_exact_gap(snapshot):
    """Le préfiltre par boîtes englobantes de ``pair_checks`` donne le même
    verdict ``coeur`` que l'écart exact à tous les autres cœurs."""
    cases, _ = snapshot
    checked = 0
    for case, seed, layout in cases:
        dressing, cores = _dress(layout, seed), _cores(layout)
        outlines = _outlines(dressing)
        for i, j, _ in candidate_pairs(layout.holes, (0.0, 80.0)):
            hull = footprint(outlines[i], outlines[j])
            exact = min(polygon_gap(hull, core) for o, core in cores.items() if o not in (i, j))
            assert pair_checks(layout, i, j, hull, cores, ())["coeur"][0] == \
                (exact >= 5.0 - EPS), case
            checked += 1
    assert checked >= 40


def test_vectorized_gap_matches_routing_polygon_gap(snapshot):
    cases, _ = snapshot
    rng = np.random.default_rng(0)
    checked = zero = 0
    for case, seed, layout in cases:
        dressing, cores = _dress(layout, seed), _cores(layout)
        outlines = _outlines(dressing)
        for i, j, _ in candidate_pairs(layout.holes, (0.0, 80.0)):
            hull = footprint(outlines[i], outlines[j])
            for core in cores.values():
                expected = polygon_gap(hull, core)
                assert pairs_module.polygon_gap_np(hull, core) == pytest.approx(
                    expected, abs=1e-9), case
                checked += 1
                zero += expected == 0.0
    # polygones aléatoires : contenance, croisement, disjonction
    for _ in range(300):
        a = tuple(map(tuple, _disk(tuple(rng.uniform(0, 30, 2)), rng.uniform(2, 10), 7)))
        b = tuple(map(tuple, _disk(tuple(rng.uniform(0, 30, 2)), rng.uniform(2, 10), 5)))
        assert pairs_module.polygon_gap_np(a, b) == pytest.approx(polygon_gap(a, b), abs=1e-9)
    assert checked > 500 and zero > 0


def test_snapshot_covers_rejections_and_three_valid_pairs(snapshot, r3e_range):
    cases, _ = snapshot
    counts, rejected = set(), 0
    for _, seed, layout in cases:
        valid, checks = _valid(layout, seed)
        counts.add(len(valid))
        rejected += sum(1 for c in checks.values() if not c["coeur"][0])
    assert {0, 1, 2, 3} <= counts and rejected >= 2


# --- sélection ----------------------------------------------------------------

def _pair(i, j, d, x, y, length=20.0):
    return GreenPair(i=i, j=j, distance=d,
                     footprint=((x, y), (x + length, y), (x + length, y + 4), (x, y + 4)))


def test_greedy_select_is_sorted_and_keeps_a_gap_between_pairs():
    valid = [_pair(6, 8, 26.0, 0, 200), _pair(2, 5, 20.0, 0, 3),     # 2/5 chevauche 1/3
             _pair(4, 7, 25.0, 0, 100), _pair(1, 3, 20.0, 0, 0)]
    chosen, blocked = greedy_select(valid, 2)
    assert [(p.i, p.j) for p in chosen] == [(1, 3), (4, 7)] and blocked == 1
    chosen, _ = greedy_select(valid, 1)
    assert [(p.i, p.j) for p in chosen] == [(1, 3)]
    # écart de 4,99 blocs : refusé ; 5 blocs : retenu
    near = [_pair(1, 3, 20.0, 0, 0), _pair(4, 7, 21.0, 0, 8.99)]
    assert len(greedy_select(near, 2)[0]) == 1
    far = [_pair(1, 3, 20.0, 0, 0), _pair(4, 7, 21.0, 0, 9.0)]
    assert len(greedy_select(far, 2)[0]) == 2


def test_selection_rules_on_snapshot(snapshot, r3e_range):
    """Paires retenues : valides, triées (d, i, j), plafond du style, ≥ 5
    blocs entre empreintes ; en links, le glouton sur les valides."""
    cases, _ = snapshot
    capped = 0
    for case, seed, layout in cases:
        for style in STYLE_SPECS:
            dressing = _dress(layout, seed, style)
            valid, _ = _valid(layout, seed, style)
            pairs = dressing.green_pairs
            assert len(pairs) <= MAX_PAIRS[style], case
            assert all(_bare(p) in valid for p in pairs), case
            assert list(pairs) == sorted(pairs, key=lambda p: (p.distance, p.i, p.j))
            for a in range(len(pairs)):
                for b in range(a + 1, len(pairs)):
                    assert polygon_gap(pairs[a].footprint, pairs[b].footprint) >= GAP - EPS
            for p in pairs:
                assert p.j != p.i + 1 and (p.i, p.j) != (9, 18)
                assert R3E_RANGE[0] - EPS <= p.distance <= R3E_RANGE[1] + EPS
            if style == "links":
                assert list(pairs) == greedy_select(valid, 2,
                                                    shape=_shaper(layout, dressing))[0], case
                capped += len(valid) > 2 and len(pairs) == 2
    assert capped >= 2


def test_production_range_on_the_real_pair_layout(snapshot, r3f_case):
    """Plage de production [12, 20] : sur le layout réel R3f, la seule
    candidate (10, 17), d ≈ 17,7, est valide et retenue en links (aucun
    rejet) ; l'instantané n'a aucune candidate."""
    seed, layout = r3f_case
    assert [(i, j) for i, j, _ in candidate_pairs(layout.holes)] == [(10, 17)]
    dressing = _dress(layout, seed)
    assert [(p.i, p.j) for p in dressing.green_pairs] == [(10, 17)]
    assert dressing.green_pairs[0].distance == pytest.approx(17.68, abs=0.01)
    assert dressing.pair_rejections == ()
    assert [_bare(p) for p in dressing.green_pairs] == _valid(layout, seed)[0]
    cases, _ = snapshot
    assert all(candidate_pairs(lay.holes) == [] for _, _, lay in cases)


def test_parkland_draw_on_the_real_pair_layout(r3f_case):
    """Parkland sur le layout réel R3f, plage de production : un tirage du
    flux du parcours par seed d'habillage ; paire formée ssi < 0,25 (et
    forme valide), sinon rejet ``tirage``."""
    _, layout = r3f_case
    formed = drawn = 0
    for seed in range(40):
        dressing = _dress(layout, seed, "parkland")
        valid_now = valid_pairs(layout, dressing.holes, _cores(layout))[0]
        if not valid_now:
            assert dressing.green_pairs == ()
            continue
        drawn += 1
        draw = np.random.default_rng([seed, RNG_LABEL, 0, 2]).random()
        expected = (tuple(greedy_select(valid_now, 1, shape=_shaper(layout, dressing))[0])
                    if draw < PARKLAND_P else ())
        assert dressing.green_pairs == expected, seed
        if draw >= PARKLAND_P:
            assert {r.cause for r in dressing.pair_rejections if (r.i, r.j) == (10, 17)} \
                == {"tirage"}
        formed += bool(expected)
    assert drawn >= 20 and 0 < formed < drawn, (formed, drawn)


# --- traçabilité des rejets (R3c retouches) ------------------------------------------

def test_greedy_select_traces_each_rejection():
    """Une ``PairRejection`` par valide non retenue, dans l'ordre du glouton :
    écart entre empreintes, rejet rendu par la forme, plafond ; les paires
    retenues sont celles du glouton sans trace."""
    valid = [_pair(6, 8, 26.0, 0, 200), _pair(2, 5, 20.0, 0, 3),     # 2/5 chevauche 1/3
             _pair(4, 7, 25.0, 0, 100), _pair(1, 3, 20.0, 0, 0), _pair(9, 11, 27.0, 0, 300)]
    shape = lambda p, done: PairRejection(p.i, p.j, "oracle", ("col",)) if p.i == 4 else p  # noqa: E731
    rejections = []
    chosen, blocked = greedy_select(valid, 2, shape=shape, rejections=rejections)
    assert [(p.i, p.j) for p in chosen] == [(1, 3), (6, 8)] and blocked == 1
    assert rejections == [PairRejection(2, 5, "ecart_empreintes"),
                          PairRejection(4, 7, "oracle", ("col",)), PairRejection(9, 11, "plafond")]
    assert greedy_select(valid, 2, shape=shape) == (chosen, blocked)


def test_rejections_trace_every_candidate_on_snapshot(snapshot, r3e_range):
    """Toute candidate est retenue ou écartée avec une cause stable ;
    ``empreinte`` porte les contrôles en échec ; la trace ne change pas la
    sélection et est déterministe."""
    cases, _ = snapshot
    causes = set()
    for case, seed, layout in cases:
        for style in STYLE_SPECS:
            dressing = _dress(layout, seed, style)
            rejections = dressing.pair_rejections
            ids = [(p.i, p.j) for p in dressing.green_pairs] + [(r.i, r.j) for r in rejections]
            assert sorted(ids) == sorted((i, j) for i, j, _ in candidate_pairs(layout.holes)), case
            _, checks = _valid(layout, seed, style)
            for r in rejections:
                assert r.cause in PAIR_REJECTION_CAUSES, case
                if r.cause == "empreinte":
                    assert r.checks == tuple(c for c in CONTROLS if not checks[(r.i, r.j)][c][0])
                    assert r.checks
                elif r.cause == "oracle":
                    assert r.checks and set(r.checks) <= set(ORACLE_CHECKS)
                else:
                    assert r.checks == ()
                causes.add(r.cause)
            again = pair_selection(layout, dressing.holes, _cores(layout), style, pair_rng(seed))
            assert again == (dressing.green_pairs, rejections), case
            assert select_green_pairs(layout, dressing.holes, _cores(layout), style,
                                      pair_rng(seed)) == dressing.green_pairs
    assert {"empreinte", "ecart_empreintes", "plafond", "tirage"} <= causes


def test_rejection_label():
    assert PairRejection(1, 3, "construction").label == "construction"
    assert PairRejection(1, 3, "oracle", ("col", "tees")).label == "oracle:col,tees"


def _two_valid_links_case(snapshot):
    """Premier layout de l'instantané où le glouton links retient deux paires."""
    cases, _ = snapshot
    for case, seed, layout in cases:
        dressing = _dress(layout, seed)
        if len(dressing.green_pairs) == 2:
            return case, seed, layout, dressing
    raise AssertionError("aucun layout à deux paires")


@pytest.mark.parametrize("error, cause", [(PairShapeError, "construction"),
                                          (GreensOverlapError, "chevauchement")])
def test_construction_failure_moves_to_the_next_pair(snapshot, r3e_range, monkeypatch, error, cause):
    """Une construction qui lève (``PairShapeError``) écarte la paire avec sa
    cause, sans planter : le glouton examine la valide suivante."""
    case, seed, layout, before = _two_valid_links_case(snapshot)
    first = before.green_pairs[0]
    real = pairs_module.build_pair

    def failing(pair, *args):
        if (pair.i, pair.j) == (first.i, first.j):
            raise error("échec simulé")
        return real(pair, *args)
    monkeypatch.setattr(pairs_module, "build_pair", failing)
    after = _dress(layout, seed)
    assert PairRejection(first.i, first.j, cause) in after.pair_rejections
    valid, _ = _valid(layout, seed)
    rest = [p for p in valid if (p.i, p.j) != (first.i, first.j)]
    assert list(after.green_pairs) == greedy_select(rest, 2, shape=_shaper(layout, after))[0]
    assert (first.i, first.j) not in {(p.i, p.j) for p in after.green_pairs}
    assert after.green_pairs[0] == before.green_pairs[1], case


# --- flux du parcours (k = 2) ------------------------------------------------------

@pytest.mark.parametrize("seed", [0, 1, 4, 2 ** 32 - 1, 2 ** 32, 2 ** 32 + 7, 2 ** 64 - 1])
def test_pair_stream_never_collides_with_hole_streams(seed):
    """``[seed, RNG_LABEL, 0, 2]`` ≠ ``[seed, RNG_LABEL, order]`` et
    ``[seed, RNG_LABEL, order, 1]`` pour tout ``order`` (1–18) : états
    initiaux distincts de ``SeedSequence``."""
    assert (COURSE_ORDER, PAIR_STREAM, TEE_STREAM) == (0, 2, 1)

    def state(rng):
        return rng.bit_generator.seed_seq.generate_state(8).tolist()

    pair = state(pair_rng(seed))
    assert pair == state(np.random.default_rng([seed, RNG_LABEL, 0, 2]))
    holes = [state(green_rng(seed, o)) for o in range(1, 19)]
    holes += [state(tee_rng(seed, o)) for o in range(1, 19)]
    assert pair not in holes
    assert len({tuple(s) for s in holes}) == 36


def test_hole_orders_never_reach_the_course_order():
    """Le flux du parcours emploie l'ordre 0 : aucun trou ne le porte."""
    for order in (COURSE_ORDER, 19):
        with pytest.raises(ValueError):
            ElasticHole(order=order, par=4, tee=ControlPoint(0, 0), green=ControlPoint(0, 100),
                        width=12.0)


def test_parkland_draw_replays_the_course_stream(snapshot, r3e_range):
    """Parkland : un tirage ``default_rng([seed, RNG_LABEL, 0, 2]).random()``
    par parcours ; paire formée (la première du glouton) ssi < 0,25."""
    cases, _ = snapshot
    formed = drawn = 0
    for case, routing_seed, layout in cases:
        valid, _ = _valid(layout, routing_seed, "parkland")
        if not valid:
            continue
        for seed in range(40):
            dressing = _dress(layout, seed, "parkland")
            # les greens parkland dépendent de la seed : valides recalculées
            valid_now = valid_pairs(layout, dressing.holes, _cores(layout))[0]
            if not valid_now:
                assert dressing.green_pairs == ()
                continue
            drawn += 1
            draw = np.random.default_rng([seed, RNG_LABEL, 0, 2]).random()
            expected = (tuple(greedy_select(valid_now, 1, shape=_shaper(layout, dressing))[0])
                        if draw < PARKLAND_P else ())
            assert dressing.green_pairs == expected, (case, seed)
            formed += bool(expected)
    assert drawn >= 200 and 0 < formed < drawn, (formed, drawn)
    # le tirage ne dépend que de la seed (40 seeds ci-dessus, partagées entre
    # layouts) : sa fréquence se mesure sur des seeds distinctes
    draws = [np.random.default_rng([s, RNG_LABEL, 0, 2]).random() for s in range(2000)]
    assert 0.22 < np.mean(np.asarray(draws) < PARKLAND_P) < 0.28


class _SpyRng:
    def __init__(self):
        self.calls = 0

    def random(self):
        self.calls += 1
        return 0.0


def test_parkland_consumes_no_draw_without_valid_pair(snapshot, r3e_range, monkeypatch):
    cases, _ = snapshot
    seen = {"none": 0, "some": 0}
    for case, seed, layout in cases:
        valid, _ = _valid(layout, seed, "parkland")
        spy = _SpyRng()
        monkeypatch.setattr(course_module, "pair_rng", lambda s, spy=spy: spy)
        dressing = _dress(layout, seed, "parkland")
        assert spy.calls == (1 if valid else 0), case
        assert len(dressing.green_pairs) == (1 if valid else 0), case
        seen["some" if valid else "none"] += 1
        spy = _SpyRng()
        monkeypatch.setattr(course_module, "pair_rng", lambda s, spy=spy: spy)
        _dress(layout, seed, "links")
        assert spy.calls == 0, case
    assert seen["none"] and seen["some"]


def test_select_green_pairs_without_candidate_leaves_rng_untouched():
    holes = _greens({})
    layout = SimpleNamespace(holes=holes, links=(), clubhouse=ControlPoint(0, 0),
                             width=400.0, height=400.0)
    rng = np.random.default_rng(3)
    before = rng.bit_generator.state
    assert select_green_pairs(layout, {}, {}, "parkland", rng) == ()
    assert rng.bit_generator.state == before


def test_deterministic_and_seed_dependent_parkland(snapshot, r3e_range):
    cases, _ = snapshot
    for case, seed, layout in cases:
        for style in STYLE_SPECS:
            assert _dress(layout, seed, style).green_pairs == _dress(layout, seed, style).green_pairs
    with_valid = [(s, lay) for _, s, lay in cases if _valid(lay, s, "parkland")[0]]
    outcomes = {bool(_dress(lay, seed, "parkland").green_pairs)
                for _, lay in with_valid for seed in range(20)}
    assert outcomes == {True, False}


# --- greens et départs inchangés ------------------------------------------------------

def test_greens_and_tees_identical_to_before_r3a(snapshot):
    cases, expected = snapshot
    for case, seed, layout in cases:
        for style in STYLE_SPECS:
            for dress_seed in (seed,) + DIGEST_SEEDS:
                key = f"{case}/{style}/{dress_seed}"
                assert _digest(_dress(layout, dress_seed, style)) == expected[key], key
    assert len(expected) == len(cases) * len(STYLE_SPECS) * (1 + len(DIGEST_SEEDS))


def test_holes_only_layout_gets_no_pairs(snapshot):
    """Un ``layout`` réduit à ``holes`` (instantanés) : mêmes greens et
    départs, aucune paire (contrôles impossibles sans liaisons ni
    clubhouse)."""
    cases, _ = snapshot
    for case, seed, layout in cases[:3]:
        full = _dress(layout, seed)
        partial = _dress(SimpleNamespace(holes=layout.holes), seed)
        assert partial.green_pairs == ()
        assert dict(partial.holes) == dict(full.holes), case
