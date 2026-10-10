"""Types de greens (rond, allongé, haricot) sur 30 seeds × 2 formats.

Les 1080 trous viennent d'un instantané du routeur (``tests/data/
dressing_holes_30x2.json`` : seeds 1–30, 400x300 et 300x400, patron random),
pour ne pas router 60 parcours (≈ 3 min) à chaque passe ; c'est l'échantillon
de calibration de ``STYLE_SPECS`` (seuil d'éligibilité, P_eff, rapport
rond / allongé). ``tests/test_dressing.py`` vérifie que l'instantané est
identique au routeur actuel sur ses 9 parcours. Régénération :

    .venv/bin/python -m tests.test_dressing_kinds
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from golfgen.dressing import GREEN_KINDS, STYLE_SPECS, dress_course
from golfgen.dressing.green import BEAN_MIN_NECK
from golfgen.routing.model import ElasticHole
from tools.dressing import green_shapes as gs

SNAPSHOT = Path(__file__).resolve().parent / "data" / "dressing_holes_30x2.json"
SEEDS = range(1, 31)

# Parts nettes : écart toléré à la part visée, en points. 3 points = seuil
# d'arrêt fixé pour la calibration ; l'écart-type d'échantillonnage du tirage
# du type sur 1080 trous est ≈ 1,4–1,5 point (√(p(1−p)/1080)).
SHARE_TOLERANCE = 0.03
AXIS_MAX_DEGREES = 15.0         # grand axe d'inertie / approche (allongé, haricot)
ELONGATED_MIN = 1.4             # allongement mesuré minimal d'un allongé
RASTER_WIDTH_MIN = 5.0          # blocs, traversée par le centre ⟂ approche
NECK_ROUNDING = 0.01            # blocs : col contrôlé avant l'arrondi à 2 décimales
# Haricots dont l'encoche (creux vectoriel 1,54 et 1,71) tombe en marche
# d'escalier au rastérisé (creux rastérisé 0) : connus et rapportés, toute
# nouvelle occurrence fait échouer le test.
KNOWN_UNREADABLE = {"links": ["300x400/22#11"], "parkland": ["400x300/7#7"]}


def load_snapshot() -> list[tuple[str, int, tuple[ElasticHole, ...]]]:
    data = json.loads(SNAPSHOT.read_text(encoding="utf-8"))
    return [(c["size"], c["seed"], tuple(ElasticHole.from_dict(h) for h in c["holes"]))
            for c in data["courses"]]


@pytest.fixture(scope="module")
def rows_by_style():
    out = {}
    for style in STYLE_SPECS:
        rows = []
        for size, seed, holes in load_snapshot():
            result = SimpleNamespace(layout=SimpleNamespace(holes=holes))
            dressing = dress_course(result, seed=seed, style=style)
            rows.extend(gs.green_rows(result, dressing, case=f"{size}/{seed}"))
        out[style] = rows
    return out


@pytest.fixture(scope="module")
def summary(rows_by_style):
    return gs.summarize([row for rows in rows_by_style.values() for row in rows])


def test_snapshot_size():
    courses = load_snapshot()
    assert sorted((size, seed) for size, seed, _ in courses) == sorted(
        (size, seed) for size in gs.SIZES for seed in SEEDS)
    assert all(len(holes) == 18 for _, _, holes in courses)


@pytest.mark.parametrize("style", sorted(STYLE_SPECS))
def test_net_kind_shares(summary, style):
    kinds = summary[style]["kinds"]
    for i, kind in enumerate(GREEN_KINDS):
        target = STYLE_SPECS[style].kind_weights[i]
        assert abs(kinds[kind]["share"] - target) <= SHARE_TOLERANCE, (kind, kinds[kind])
    print(f"\n{style} : " + ", ".join(f"{k} {v['share']:.3f}" for k, v in kinds.items()))


@pytest.mark.parametrize("style", sorted(STYLE_SPECS))
def test_fallbacks_at_most_5_percent(summary, style):
    fallbacks = summary[style]["fallbacks"]
    assert fallbacks["drawn_beans"] > 0
    assert fallbacks["count"] <= 0.05 * fallbacks["drawn_beans"], fallbacks


@pytest.mark.parametrize("style", sorted(STYLE_SPECS))
def test_no_bean_below_threshold(rows_by_style, style):
    threshold = STYLE_SPECS[style].bean_min_area
    beans = [r for r in rows_by_style[style] if r["kind"] == "bean"]
    assert beans and all(r["target_area"] >= threshold for r in beans)
    # les bascules ne viennent que de haricots tirés, donc éligibles
    assert all(r["target_area"] >= threshold for r in rows_by_style[style] if r["fallback"])


@pytest.mark.parametrize("style", sorted(STYLE_SPECS))
def test_axis_follows_approach(rows_by_style, style):
    for row in rows_by_style[style]:
        if row["kind"] != "round":
            assert row["axis_deviation"] <= AXIS_MAX_DEGREES, row


@pytest.mark.parametrize("style", sorted(STYLE_SPECS))
def test_elongated_are_elongated(rows_by_style, style):
    elongated = [r for r in rows_by_style[style] if r["kind"] == "elongated"]
    assert elongated and min(r["elongation"] for r in elongated) >= ELONGATED_MIN


@pytest.mark.parametrize("style", sorted(STYLE_SPECS))
def test_bean_notch_readable_and_neck(rows_by_style, style):
    beans = [r for r in rows_by_style[style] if r["kind"] == "bean"]
    unreadable = sorted(r["case"] for r in beans if r["concavity"] < 1.0)
    assert unreadable == KNOWN_UNREADABLE[style]
    assert min(r["neck"] for r in beans) >= BEAN_MIN_NECK - NECK_ROUNDING


@pytest.mark.parametrize("style", sorted(STYLE_SPECS))
def test_raster_width(rows_by_style, style):
    assert min(r["raster_width"] for r in rows_by_style[style]) >= RASTER_WIDTH_MIN


@pytest.mark.parametrize("style", sorted(STYLE_SPECS))
def test_reduction_criterion(summary, style):
    data = summary[style]
    assert data["reduction_criterion"]["ok"], (data["reduced_pct"], data["max_shrink_steps"])
    assert data["reduced_pct"] <= gs.REDUCED_MAX_PCT
    assert data["max_shrink_steps"] <= gs.REDUCED_MAX_STEPS


def _regenerate() -> None:
    courses = []
    for size, (width, height) in gs.SIZES.items():
        for seed in SEEDS:
            _, result = gs.route(seed, width, height)
            holes = sorted(result.layout.holes, key=lambda h: h.order)
            courses.append({"size": size, "seed": seed,
                            "holes": [hole.to_dict() for hole in holes]})
            print(size, seed, flush=True)
    SNAPSHOT.parent.mkdir(parents=True, exist_ok=True)
    lines = ",\n".join(json.dumps(c, sort_keys=True) for c in courses)
    SNAPSHOT.write_text('{"courses": [\n' + lines + "\n]}\n", encoding="utf-8")


if __name__ == "__main__":
    _regenerate()
