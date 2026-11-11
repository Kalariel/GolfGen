"""Types de greens (rond, allongé, haricot) sur 30 seeds × 2 formats.

Les 1080 trous viennent d'un instantané du routeur (``tests/data/
dressing_holes_30x2.json`` : seeds 1–30, 400x300 et 300x400, patron random),
pour ne pas router 60 parcours (≈ 3 min) à chaque passe ; c'est l'échantillon
de calibration de ``STYLE_SPECS`` (seuil d'éligibilité, P_eff, rapport
rond / allongé). ``tests/test_dressing.py`` vérifie que l'instantané est
identique au routeur actuel sur ses 9 parcours. Mesures par green
(``green_row``) et synthèse par style (``summarize``) : ici, sur les
fonctions de ``golfgen.dressing.green``. Régénération :

    .venv/bin/python -m tests.test_dressing_kinds
"""

from __future__ import annotations

import json
import math
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from golfgen.dressing import GREEN_KINDS, STYLE_SPECS, dress_course
from golfgen.dressing.green import (BEAN_MIN_NECK, FALLBACK_CAUSES, axis_deviation, hull_depth,
                                    inertia, neck_width, raster_concavity, rasterize)
from golfgen.routing.model import ElasticHole

SNAPSHOT = Path(__file__).resolve().parent / "data" / "dressing_holes_30x2.json"
SEEDS = range(1, 31)
SIZES = {"400x300": (400, 300), "300x400": (300, 400)}

# Parts nettes : écart toléré à la part visée, en points. 3 points = seuil
# d'arrêt fixé pour la calibration ; l'écart-type d'échantillonnage du tirage
# du type sur 1080 trous est ≈ 1,4–1,5 point (√(p(1−p)/1080)).
SHARE_TOLERANCE = 0.03
AXIS_MAX_DEGREES = 15.0         # grand axe d'inertie / approche (allongé, haricot)
ELONGATED_MIN = 1.4             # allongement mesuré minimal d'un allongé
BEAN_MAX_ELONGATION = 2.0       # allongement mesuré maximal d'un haricot (au-delà : saucisse)
RASTER_WIDTH_MIN = 5.0          # blocs, traversée par le centre ⟂ approche
# Creux vectoriel d'un haricot non réduit : calé dans ``bean_depth`` sur le
# contour local, puis mesuré ici sur le contour placé, dont les coordonnées
# sont arrondies à 2 décimales (déplacement ≤ 0,005·√2 par sommet) : seule
# tolérance, due à cet arrondi.
HULL_DEPTH_ROUNDING = 0.01
REDUCED_MAX_PCT = 5.0           # critère : ≤ 5 % de greens réduits par style
REDUCED_MAX_STEPS = 3           # critère : ≤ 3 pas ×0,95
RASTER_SPAN = 30.0              # blocs : longueur maximale d'une traversée


def approach_tangent(hole: ElasticHole) -> np.ndarray:
    """Direction unitaire de l'approche (dernier segment de l'axe)."""
    tangent = np.array((hole.axis[-1].x - hole.axis[-2].x, hole.axis[-1].y - hole.axis[-2].y))
    return tangent / np.linalg.norm(tangent)


def raster_width(cells: np.ndarray, center, tangent: np.ndarray, step: float = 0.05) -> float:
    """Largeur rastérisée (blocs) : longueur, dans l'union des cases vertes,
    de la traversée continue par le centre de la forme, perpendiculaire à
    l'approche."""
    green = {tuple(c) for c in cells.tolist()}
    normal = np.array((-tangent[1], tangent[0]))
    total = 0.0
    for sign in (1.0, -1.0):
        t = 0.0 if sign > 0 else step
        while t < RASTER_SPAN:
            p = np.asarray(center, dtype=float) + sign * t * normal
            if (int(math.floor(p[0])), int(math.floor(p[1]))) not in green:
                break
            t += step
        total += t
    return round(total, 2)


def green_row(hole: ElasticHole, green, style: str) -> dict:
    """Mesures d'un green : type, bascule et sa cause, aire visée,
    réduction, allongement et écart de l'axe d'inertie à l'approche,
    concavité et largeur rastérisées, col et creux vectoriel (haricot,
    sinon ``None``)."""
    cells = rasterize(green.outline)
    tangent = approach_tangent(hole)
    elongation, _ = inertia(green.outline)
    outline = np.asarray(green.outline, dtype=float)
    bean = green.kind == "bean"
    neck = neck_width(outline, tangent) if bean else None
    return {
        "style": style, "order": hole.order, "kind": green.kind,
        "target_area": green.target_area, "reduced": green.reduced,
        "shrink_steps": green.shrink_steps, "fallback": green.bean_fallback,
        "fallback_cause": green.fallback_cause,
        "hull_depth": round(hull_depth(outline), 3) if bean else None,
        "elongation": round(elongation, 3),
        "axis_deviation": round(axis_deviation(green.outline, tangent), 2),
        "concavity": raster_concavity(cells),
        "raster_width": raster_width(cells, green.center, tangent),
        "neck": None if neck is None else round(neck, 3),
    }


def summarize(rows: list[dict]) -> dict:
    """Synthèse par style : parts nettes des types, bascules (sur les
    haricots tirés), greens réduits et pas de réduction maximal."""
    out = {}
    for style in sorted({row["style"] for row in rows}):
        items = [row for row in rows if row["style"] == style]
        n = len(items)
        by_kind = {kind: [r for r in items if r["kind"] == kind] for kind in GREEN_KINDS}
        fallbacks = sum(r["fallback"] for r in items)
        reduced = sum(r["reduced"] for r in items)
        max_steps = max((r["shrink_steps"] for r in items), default=0)
        out[style] = {
            "kinds": {kind: {"greens": len(group), "share": round(len(group) / n, 3)}
                      for kind, group in by_kind.items()},
            "fallbacks": {"count": fallbacks, "drawn_beans": len(by_kind["bean"]) + fallbacks},
            "reduced_pct": round(100.0 * reduced / n, 1),
            "max_shrink_steps": max_steps,
        }
    return out


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
            rows.extend(green_row(hole, dressing[hole.order].green, style)
                        for hole in sorted(holes, key=lambda h: h.order))
        out[style] = rows
    return out


@pytest.fixture(scope="module")
def summary(rows_by_style):
    return summarize([row for rows in rows_by_style.values() for row in rows])


def test_snapshot_size():
    courses = load_snapshot()
    assert sorted((size, seed) for size, seed, _ in courses) == sorted(
        (size, seed) for size in SIZES for seed in SEEDS)
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
def test_beans_are_not_sausages(rows_by_style, style):
    beans = [r for r in rows_by_style[style] if r["kind"] == "bean"]
    assert beans and max(r["elongation"] for r in beans) <= BEAN_MAX_ELONGATION


@pytest.mark.parametrize("style", sorted(STYLE_SPECS))
def test_bean_neck_and_raster_notch(rows_by_style, style):
    """Règle, sans exception : col ≥ ``BEAN_MIN_NECK`` pour tout haricot,
    creux rastérisé ≥ 1 bloc pour tout haricot non réduit (le générateur
    fait basculer en allongé tout haricot placé qui ne les tient pas)."""
    beans = [r for r in rows_by_style[style] if r["kind"] == "bean"]
    assert beans and min(r["neck"] for r in beans) >= BEAN_MIN_NECK
    assert all(r["concavity"] >= 1.0 for r in beans if not r["reduced"])


@pytest.mark.parametrize("style", sorted(STYLE_SPECS))
def test_bean_hull_depth_in_range(rows_by_style, style):
    lo, hi = STYLE_SPECS[style].bean_depth
    beans = [r for r in rows_by_style[style] if r["kind"] == "bean" and not r["reduced"]]
    assert beans
    for row in beans:
        assert lo - HULL_DEPTH_ROUNDING <= row["hull_depth"] <= hi + HULL_DEPTH_ROUNDING, row


@pytest.mark.parametrize("style", sorted(STYLE_SPECS))
def test_fallbacks_have_a_cause(rows_by_style, style):
    for row in rows_by_style[style]:
        assert (row["fallback_cause"] is not None) == row["fallback"], row
        if row["fallback"]:
            assert row["kind"] == "elongated" and row["fallback_cause"] in FALLBACK_CAUSES, row


@pytest.mark.parametrize("style", sorted(STYLE_SPECS))
def test_raster_width(rows_by_style, style):
    assert min(r["raster_width"] for r in rows_by_style[style]) >= RASTER_WIDTH_MIN


@pytest.mark.parametrize("style", sorted(STYLE_SPECS))
def test_reduction_criterion(summary, style):
    data = summary[style]
    assert data["reduced_pct"] <= REDUCED_MAX_PCT, data
    assert data["max_shrink_steps"] <= REDUCED_MAX_STEPS, data


def _regenerate() -> None:
    from golfgen.routing.muirfield import build_course
    from golfgen.routing.sites import load_terrain
    courses = []
    for size, (width, height) in SIZES.items():
        for seed in SEEDS:
            heightmap = load_terrain(seed, width, height)
            result = build_course(seed, "random", heightmap, width=width, height=height)
            holes = sorted(result.layout.holes, key=lambda h: h.order)
            courses.append({"size": size, "seed": seed,
                            "holes": [hole.to_dict() for hole in holes]})
            print(size, seed, flush=True)
    SNAPSHOT.parent.mkdir(parents=True, exist_ok=True)
    lines = ",\n".join(json.dumps(c, sort_keys=True) for c in courses)
    SNAPSHOT.write_text('{"courses": [\n' + lines + "\n]}\n", encoding="utf-8")


if __name__ == "__main__":
    _regenerate()
