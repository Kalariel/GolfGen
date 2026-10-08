"""Métriques de forme (``shape_metrics.py``) sur des cas synthétiques."""

from __future__ import annotations

import json
import math

import pytest

from experiments.elastic_routing.model import ControlPoint, CourseLayout, ElasticHole, NineLayout
from experiments.elastic_routing.shape_metrics import (
    angular_step_cv,
    direction_entropy,
    oriented_angular_steps,
    radial_alignment_R,
    shape_metrics,
)


CENTRE = (200.0, 200.0)
PARS = (3, 4, 4, 4, 4, 4, 5, 5, 3) * 2


def _polar(radius: float, angle: float, centre=CENTRE) -> tuple[float, float]:
    return (centre[0] + radius * math.cos(angle), centre[1] + radius * math.sin(angle))


def _blades(count: int = 9, *, start: float = 0.0, step: float | None = None,
            twist: float = 0.4, sign: float = 1.0):
    """Moulinet parfait : pale i = tee au rayon 60, green au rayon 150, tournée de ``twist``."""
    step = 2.0 * math.pi / count if step is None else step
    tees, greens = [], []
    for i in range(count):
        theta = start + sign * i * step
        tees.append(_polar(60.0, theta))
        greens.append(_polar(150.0, theta + twist))
    return tees, greens


# -- pale parfaite / pas régulier ----------------------------------------------

@pytest.mark.parametrize("sign", (1.0, -1.0))
@pytest.mark.parametrize("twist", (0.0, 0.4, -0.7))
def test_perfect_windmill_has_zero_cv_and_unit_r(sign, twist):
    tees, greens = _blades(twist=twist, sign=sign)
    assert angular_step_cv(greens, CENTRE) == pytest.approx(0.0, abs=1e-9)
    assert radial_alignment_R(tees, greens, CENTRE) == pytest.approx(1.0)


def test_steps_are_oriented_by_the_dominant_direction():
    _, greens = _blades(sign=-1.0)                 # boucle anti-horaire (repère image)
    steps = oriented_angular_steps(greens, CENTRE)
    assert steps == pytest.approx([2.0 * math.pi / 9] * 8)


def test_backtracking_step_raises_cv():
    angles = [0.0, 0.5, 1.0, 0.5, 1.0, 1.5]        # un pas à rebours de même amplitude
    greens = [_polar(100.0, a) for a in angles]
    steps = oriented_angular_steps(greens, CENTRE)
    assert steps == pytest.approx([0.5, 0.5, -0.5, 0.5, 0.5])
    assert angular_step_cv(greens, CENTRE) > 1.0   # |Δθ| aurait donné CV = 0


def test_cv_is_undefined_without_net_progress():
    greens = [_polar(100.0, a) for a in (0.0, 0.5, 0.0)]
    assert angular_step_cv(greens, CENTRE) is None
    assert angular_step_cv(greens[:1], CENTRE) is None


def _oblique(theta: float, alpha: float):
    """Trou centré au rayon 100 sur l'angle ``theta``, d'obliquité ``alpha`` sur le rayon."""
    mx, my = _polar(100.0, theta)
    ux, uy = math.cos(theta + alpha), math.sin(theta + alpha)
    return (mx - 30.0 * ux, my - 30.0 * uy), (mx + 30.0 * ux, my + 30.0 * uy)


@pytest.mark.parametrize("alpha", (math.pi / 4, math.pi / 3, 0.2))
def test_mirror_windmills_cancel_in_r(alpha):
    holes = [_oblique(i * 2.0 * math.pi / 9, alpha) for i in range(9)]
    holes += [_oblique((i + 0.5) * 2.0 * math.pi / 9, -alpha) for i in range(9)]
    tees, greens = zip(*holes)
    # obliquités opposées (moulinets miroirs) : 2α et −2α → R = |cos 2α|
    assert radial_alignment_R(tees, greens, CENTRE) == pytest.approx(abs(math.cos(2.0 * alpha)))
    assert radial_alignment_R(tees[:9], greens[:9], CENTRE) == pytest.approx(1.0)


def test_r_ignores_play_direction():
    tees, greens = _blades(twist=0.4)
    swapped = radial_alignment_R(tees[:4] + greens[4:], greens[:4] + tees[4:], CENTRE)
    assert swapped == pytest.approx(1.0)


# -- entropie des directions -----------------------------------------------------

def test_identical_directions_have_zero_entropy():
    tees = [(10.0 * i, 5.0 * i) for i in range(9)]
    greens = [(x + 100.0, y + 20.0) for x, y in tees]
    assert direction_entropy(tees, greens) == 0.0


def test_opposite_directions_share_a_bin():
    tees = [(0.0, 0.0)] * 6
    greens = [(100.0, 30.0), (-100.0, -30.0)] * 3
    assert direction_entropy(tees, greens) == 0.0


def test_varied_directions_have_high_entropy():
    angles = [(k + 0.5) * math.pi / 12 for k in range(12)]   # une direction par case
    tees = [(0.0, 0.0)] * 12
    greens = [(100.0 * math.cos(a), 100.0 * math.sin(a)) for a in angles]
    assert direction_entropy(tees, greens) == pytest.approx(1.0)
    nine_tees, nine_greens = _blades(twist=0.4)               # 9 orientations distinctes
    assert direction_entropy(nine_tees, nine_greens) == pytest.approx(math.log(9) / math.log(12))


# -- wrap angulaire --------------------------------------------------------------

@pytest.mark.parametrize("start", (math.pi - 0.3, -math.pi + 0.1, 3.0))
def test_steps_unwrap_across_pi(start):
    angles = [start + 0.2 * i for i in range(6)]             # traverse ±π
    greens = [_polar(100.0, a) for a in angles]
    assert oriented_angular_steps(greens, CENTRE) == pytest.approx([0.2] * 5)
    assert angular_step_cv(greens, CENTRE) == pytest.approx(0.0, abs=1e-9)


def test_r_unwraps_obliquity_across_pi():
    # même obliquité, rayons de part et d'autre de l'angle ±π
    tees, greens = _blades(count=5, start=math.pi - 0.2, step=0.1, twist=0.5)
    assert radial_alignment_R(tees, greens, CENTRE) == pytest.approx(1.0)


# -- synthèse sur un CourseLayout ------------------------------------------------

def _windmill_course() -> CourseLayout:
    clubhouse = ControlPoint(200.0, 395.0)
    holes = []
    for nine, start in ((0, 0.0), (1, math.pi / 18)):
        tees, greens = _blades(start=start, twist=0.4)
        for i, (tee, green) in enumerate(zip(tees, greens)):
            order = 9 * nine + i + 1
            holes.append(ElasticHole(order=order, par=PARS[order - 1],
                                     tee=ControlPoint(*tee), green=ControlPoint(*green)))
    return CourseLayout(seed=1, width=400.0, height=400.0, clubhouse=clubhouse,
                        front=NineLayout.from_holes(1, clubhouse, tuple(holes[:9])),
                        back=NineLayout.from_holes(10, clubhouse, tuple(holes[9:])))


def test_shape_metrics_summary_is_serialisable():
    metrics = shape_metrics(_windmill_course())
    assert set(metrics) == {"front", "back", "course"}
    for scope in metrics.values():
        assert set(scope) == {"angular_step_cv", "direction_entropy", "radial_alignment_R"}
        assert scope["angular_step_cv"] == pytest.approx(0.0, abs=1e-4)
        assert scope["radial_alignment_R"] == pytest.approx(1.0)
    # 18 orientations distinctes modulo 180° → 12 cases toutes touchées
    assert metrics["course"]["direction_entropy"] > metrics["front"]["direction_entropy"]
    assert json.loads(json.dumps(metrics, allow_nan=False)) == metrics


def test_shape_metrics_is_deterministic():
    layout = _windmill_course()
    assert shape_metrics(layout) == shape_metrics(layout)
