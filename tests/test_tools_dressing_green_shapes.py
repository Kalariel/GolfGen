"""Planches et statistiques des greens (``tools.dressing.green_shapes``) sur le
layout synthétique de l'oracle."""

from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import pytest

from golfgen.dressing import STYLE_SPECS, dress_course
from golfgen.dressing.green import shoelace
from tests.test_routing_geometry import build_synthetic_layout
from tools.dressing import green_shapes as gs
from tools.muirfield.render_readable import render_readable_svg


@pytest.fixture(scope="module")
def layout():
    return build_synthetic_layout()


def test_tile_svg_renders_blocks_and_labels(layout):
    dressing = dress_course(SimpleNamespace(layout=layout), seed=4, style="links")
    for hole in layout.holes:
        green = dressing[hole.order].green
        svg = gs.tile_svg(hole, dressing, label="links")
        assert svg.startswith("<svg") and svg.rstrip().endswith("</svg>")
        assert svg.count("<polygon") == 3          # cœur, contour du green, fanion
        assert svg.count('class="cell"') == len(gs.rasterize(green.outline)) > 0
        assert gs.GREEN_FILL in svg and "<polyline" in svg
        assert f"#{hole.order} par {hole.par}" in svg
        assert f"{gs.KIND_LABELS[green.kind]}" in svg and "allong. " in svg
        assert f"A {green.area:.0f} bl²" in svg
        assert ("col " in svg) == (green.kind == "bean")
        assert ("réduit ×" in svg) == green.reduced


def test_raster_outline_and_concavity():
    square = np.array([(x, y) for x in range(3) for y in range(3)])
    (ring,) = gs.raster_outline(square)
    assert sorted(ring) == [(0.0, 0.0), (0.0, 3.0), (3.0, 0.0), (3.0, 3.0)]
    assert gs.raster_concavity(square) == 0.0
    # C : rangée du milieu ouverte sur deux cases -> creux rastérisé ≥ 1
    c_shape = np.array([c for c in square.tolist() + [[3, 0], [3, 2]] if c not in ([1, 1], [2, 1])])
    (ring,) = gs.raster_outline(c_shape)
    assert len(ring) == 8 and gs.raster_concavity(c_shape) >= 1.0
    # aire du contour = nombre de cases
    assert abs(shoelace(np.asarray(ring))) == len(c_shape)


def _row(**values):
    row = {"style": "links", "case": "x#1", "par": 3, "area": 70.0, "target_area": 70.0,
           "reduced": False, "shrink_steps": 0, "width": 14.0, "kind": "round",
           "fallback": False, "elongation": 1.1, "axis_deviation": 0.0, "raster_area": 70,
           "concavity": 0.0, "raster_width": 8.0, "neck": None, "margin": 2.0, "rho": 0.68}
    row.update(values)
    return row


def test_summarize_counts_kinds_fallbacks_and_reductions():
    rows = [
        _row(par=3, area=60.0, reduced=True, shrink_steps=2, width=10.0),
        _row(par=3),
        _row(par=4, area=90.0, target_area=90.0, kind="bean", neck=6.2, concavity=1.5,
             elongation=1.7),
        _row(par=4, area=95.0, target_area=95.0, kind="elongated", fallback=True,
             elongation=1.6),
    ]
    summary = gs.summarize(rows, {"links": [0.006, 0.008]})["links"]
    assert (summary["greens"], summary["reduced"], summary["max_shrink_steps"]) == (4, 1, 2)
    assert summary["by_par"]["3"]["reduced_pct"] == 50.0
    assert summary["by_par"]["3"]["reduced_widths"] == [10.0]
    assert summary["by_par"]["4"]["area"]["median"] == 92.5
    assert {k: v["greens"] for k, v in summary["kinds"].items()} == {
        "round": 2, "elongated": 1, "bean": 1}
    assert summary["kinds"]["bean"]["target"] == 0.35
    assert summary["fallbacks"]["count"] == 1 and summary["fallbacks"]["pct"] == 50.0
    eligibility = summary["eligibility"]
    assert eligibility["bean_min_area"] == STYLE_SPECS["links"].bean_min_area
    assert eligibility["eligible"] == 2 and eligibility["beans_below_threshold"] == 0
    assert summary["beans"]["readable"] == 1 and summary["beans"]["neck_min"] == 6.2
    assert summary["reduction_criterion"]["ok"] is False      # 25 % réduits
    assert summary["dressing_ms"]["median"] == 7.0
    assert summary["raster_area_diff"]["max_abs"] == 25.0      # 70 cases pour 95 bl²


def test_summarize_keys_on_dressed_layout(layout):
    result = SimpleNamespace(layout=layout)
    rows = [row for style in STYLE_SPECS
            for row in gs.green_rows(result, dress_course(result, seed=4, style=style),
                                     case="synthetique")]
    summary = gs.summarize(rows)
    assert set(summary) == set(STYLE_SPECS)
    for data in summary.values():
        assert {"kinds", "fallbacks", "eligibility", "elongation", "axis_deviation_max",
                "beans", "area", "area_by_kind", "by_par", "rho", "margin_min",
                "raster_width_min", "raster_area_diff", "reduced", "reduced_pct",
                "max_shrink_steps", "reduction_criterion"} <= set(data)
        assert sum(v["greens"] for v in data["kinds"].values()) == data["greens"] == 18
        assert data["margin_min"] > 0.0


def test_render_readable_green_disks_option(layout):
    with_disks = render_readable_svg(layout, ())
    without = render_readable_svg(layout, (), green_disks=False)
    assert with_disks.count('fill="#3dbd4e"') == 18
    assert 'fill="#3dbd4e"' not in without
    assert without.count('fill="#e5534b"/>') == with_disks.count('fill="#e5534b"/>')
    assert "● green" in with_disks and "green habillé" not in with_disks
    assert "● green" not in without and "▱ green habillé · • drapeau" in without
