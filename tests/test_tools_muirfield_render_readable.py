"""Rendu lisible du spike (``render_readable.py``) sur un parcours Muirfield."""

from __future__ import annotations

import dataclasses
import re

import pytest

from tools.muirfield.render_readable import render_readable_svg
from golfgen.routing import muirfield as mf


@pytest.fixture(scope="module")
def results():
    return {(300, 400, 1): mf.build_muirfield(1, width=300, height=400)}


def test_readable_render_numbers_every_hole(results):
    result = results[(300, 400, 1)]
    svg = render_readable_svg(result.layout, result.violations,
                              rings=(result.outer_ring, result.inner_ring), title="t")
    assert svg.startswith("<svg") and svg.rstrip().endswith("</svg>")
    for order in range(1, 19):
        assert f'text-anchor="middle">{order}</text>' in svg


def test_readable_render_crops_the_canvas_to_a_landscape_map(results):
    """Portrait : canevas 800×(800 + pied), inchangé ; paysage : hauteur
    rognée à la carte, pas de bande vide sous la carte."""
    result = results[(300, 400, 1)]
    portrait = render_readable_svg(result.layout, result.violations, title="t")
    assert 'width="800" height="888"' in portrait.splitlines()[0]
    landscape = dataclasses.replace(result.layout, width=400.0, height=300.0)
    svg = render_readable_svg(landscape, (), title="t")
    assert 'width="800" height="700"' in svg.splitlines()[0]
    labels = [float(y) for y in re.findall(r'<circle cx="[\d.]+" cy="([\d.]+)" r="10"', svg)]
    assert len(labels) == 18 and max(labels) <= 612 - 24 - 10
