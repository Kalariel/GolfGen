"""Planches et statistiques des greens (``tools.dressing.green_shapes``) sur le
layout synthétique de l'oracle."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from golfgen.dressing import dress_course
from tests.test_routing_geometry import build_synthetic_layout
from tools.dressing import green_shapes as gs
from tools.muirfield.render_readable import render_readable_svg


@pytest.fixture(scope="module")
def layout():
    return build_synthetic_layout()


def test_tile_svg_shows_core_axis_green_and_flag(layout):
    dressing = dress_course(SimpleNamespace(layout=layout), seed=4, style="links")
    hole = layout.holes[0]
    svg = gs.tile_svg(hole, dressing, label="links")
    assert svg.startswith("<svg") and svg.rstrip().endswith("</svg>")
    assert svg.count("<polygon") == 3          # cœur, green, fanion
    assert gs.GREEN_FILL in svg and "<polyline" in svg
    assert f"#{hole.order} par {hole.par}" in svg


def test_summarize_counts_reductions_per_par():
    rows = [
        {"style": "links", "par": 3, "area": 60.0, "target_area": 70.0, "reduced": True,
         "shrink_steps": 2, "width": 10.0},
        {"style": "links", "par": 3, "area": 70.0, "target_area": 70.0, "reduced": False,
         "shrink_steps": 0, "width": 14.0},
        {"style": "links", "par": 4, "area": 80.0, "target_area": 80.0, "reduced": False,
         "shrink_steps": 0, "width": 15.0},
    ]
    summary = gs.summarize(rows)["links"]
    assert (summary["greens"], summary["reduced"]) == (3, 1)
    assert summary["by_par"]["3"]["reduced_pct"] == 50.0
    assert summary["by_par"]["3"]["reduced_widths"] == [10.0]
    assert summary["by_par"]["4"]["area"]["median"] == 80.0


def test_render_readable_green_disks_option(layout):
    with_disks = render_readable_svg(layout, ())
    without = render_readable_svg(layout, (), green_disks=False)
    assert with_disks.count('fill="#3dbd4e"') == 18
    assert 'fill="#3dbd4e"' not in without
    assert without.count('fill="#e5534b"/>') == with_disks.count('fill="#e5534b"/>')
