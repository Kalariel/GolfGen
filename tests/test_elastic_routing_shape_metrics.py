"""Métriques de forme (``shape_metrics.py``) sur des cas synthétiques."""

from __future__ import annotations

import json
import math

import pytest

from golfgen.routing.model import ControlPoint, CourseLayout, ElasticHole, NineLayout
from golfgen.routing import muirfield as mf
from experiments.elastic_routing.run_muirfield import (
    _nine_shape_stats,
    _planche_title,
    _shape_stats,
)
from experiments.elastic_routing.shape_metrics import (
    CV_MIN_PROGRESS,
    angular_step_cv,
    convex_hull,
    direction_entropy,
    forward_mean,
    heading_turns,
    hull_ratio,
    nearest_segment,
    nominal_nine_length,
    obliquity_abs,
    obliquity_signed,
    oriented_angular_steps,
    path_to_nine_length,
    path_tangent,
    polygon_area,
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
    angles = [0.0, 0.5, 1.0, 0.5, 1.0, 1.5, 2.0]   # un pas à rebours de même amplitude
    greens = [_polar(100.0, a) for a in angles]
    steps = oriented_angular_steps(greens, CENTRE)
    assert steps == pytest.approx([0.5, 0.5, -0.5, 0.5, 0.5, 0.5])
    assert angular_step_cv(greens, CENTRE) > 1.0   # |Δθ| aurait donné CV = 0


def test_cv_is_undefined_without_net_progress():
    greens = [_polar(100.0, a) for a in (0.0, 0.5, 0.0)]
    assert angular_step_cv(greens, CENTRE) is None
    assert angular_step_cv(greens[:1], CENTRE) is None


def test_cv_needs_a_minimal_net_progress():
    # pas réguliers mais quart de tour à peine entamé : pas de CV
    short = [_polar(100.0, a) for a in (0.0, 0.2, 0.4, 0.6, 0.8, 1.0, 1.2, 1.4)]
    assert abs(sum(oriented_angular_steps(short, CENTRE))) < CV_MIN_PROGRESS
    assert angular_step_cv(short, CENTRE) is None
    longer = short + [_polar(100.0, 1.6)]                    # 1,6 rad > π/2
    assert angular_step_cv(longer, CENTRE) == pytest.approx(0.0, abs=1e-9)
    # forte dispersion mais progression nette faible : toujours None
    zigzag = [_polar(100.0, a) for a in (0.0, 1.0, 0.1, 1.1, 0.2, 1.2)]
    assert angular_step_cv(zigzag, CENTRE) is None


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
    angles = [start + 0.4 * i for i in range(6)]             # traverse ±π
    greens = [_polar(100.0, a) for a in angles]
    assert oriented_angular_steps(greens, CENTRE) == pytest.approx([0.4] * 5)
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
    base = {"angular_step_cv", "direction_entropy", "radial_alignment_R"}
    assert set(metrics["course"]) == base
    for scope in metrics.values():
        assert set(scope) == (base if scope is metrics["course"] else base | {"heading_turns"})
        assert scope["angular_step_cv"] == pytest.approx(0.0, abs=1e-4)
        assert scope["radial_alignment_R"] == pytest.approx(1.0)
    # 18 orientations distinctes modulo 180° : les 12 cases sont touchées, mais
    # inégalement (6 cases à 2 trous, 6 à 1) → entropie < 1
    uneven = -(6 * (2 / 18) * math.log(2 / 18) + 6 * (1 / 18) * math.log(1 / 18)) / math.log(12)
    assert metrics["course"]["direction_entropy"] == pytest.approx(uneven, abs=1e-4)
    assert metrics["course"]["direction_entropy"] > metrics["front"]["direction_entropy"]
    assert json.loads(json.dumps(metrics, allow_nan=False)) == metrics


# -- projeteur sur le chemin ---------------------------------------------------

SQUARE = [(0.0, 0.0), (100.0, 0.0), (100.0, 100.0), (0.0, 100.0), (0.0, 0.0)]


@pytest.mark.parametrize("point,index", (
    ((50.0, -5.0), 0), ((50.0, 10.0), 0), ((95.0, 50.0), 1), ((50.0, 140.0), 2),
    ((-30.0, 60.0), 3), ((300.0, 50.0), 1),
))
def test_nearest_segment(point, index):
    assert nearest_segment(SQUARE, point) == index


def test_nearest_segment_clamps_to_the_ends_and_breaks_ties_on_the_first():
    path = [(0.0, 0.0), (10.0, 0.0), (20.0, 0.0)]
    assert nearest_segment(path, (-50.0, 3.0)) == 0
    assert nearest_segment(path, (70.0, 3.0)) == 1
    assert nearest_segment(path, (10.0, 5.0)) == 0            # sommet partagé
    assert nearest_segment(SQUARE, (50.0, 50.0)) == 0         # équidistant des 4 côtés


def test_nearest_segment_skips_degenerate_segments():
    path = [(0.0, 0.0), (0.0, 0.0), (10.0, 0.0), (10.0, 0.0), (10.0, 10.0)]
    assert nearest_segment(path, (0.0, 0.0)) == 1
    assert nearest_segment(path, (10.0, 0.0)) == 1
    assert nearest_segment(path, (12.0, 8.0)) == 3
    with pytest.raises(ValueError):
        nearest_segment([(1.0, 1.0), (1.0, 1.0)], (0.0, 0.0))
    with pytest.raises(ValueError):
        nearest_segment([(1.0, 1.0)], (0.0, 0.0))


def test_path_tangent_follows_the_path_direction():
    assert path_tangent(SQUARE, (50.0, -5.0)) == pytest.approx(0.0)
    assert path_tangent(SQUARE, (105.0, 50.0)) == pytest.approx(math.pi / 2)
    assert path_tangent(SQUARE[::-1], (50.0, -5.0)) == pytest.approx(math.pi)


# -- obliquité signée -----------------------------------------------------------

def _circle(radius: float = 100.0, count: int = 720):
    """Chemin circulaire parcouru dans le sens θ croissant."""
    return [_polar(radius, 2.0 * math.pi * k / count) for k in range(count + 1)]


def _tilted(theta: float, tilt: float, radius: float = 100.0, half: float = 30.0):
    """Trou centré sur le cercle en ``theta``, tourné de ``tilt`` depuis la tangente."""
    mx, my = _polar(radius, theta)
    heading = theta + math.pi / 2 + tilt                    # tangente dans le sens θ croissant
    ux, uy = math.cos(heading), math.sin(heading)
    return (mx - half * ux, my - half * uy), (mx + half * ux, my + half * uy)


def _tilted_nine(tilts):
    holes = [_tilted(0.3 + i * 2.0 * math.pi / 9, tilt) for i, tilt in enumerate(tilts)]
    return [h[0] for h in holes], [h[1] for h in holes]


def test_tangent_holes_have_zero_obliquity():
    tees, greens = _tilted_nine([0.0] * 9)
    assert obliquity_signed(tees, greens, _circle()) == pytest.approx(0.0, abs=1e-2)
    assert obliquity_abs(tees, greens, _circle()) == pytest.approx(0.0, abs=1e-2)
    # joués à rebours : sin(π) ≈ 0 aussi
    assert obliquity_signed(greens, tees, _circle()) == pytest.approx(0.0, abs=1e-2)


@pytest.mark.parametrize("tilt,expected", ((math.pi / 6, 0.5), (-math.pi / 6, -0.5)))
def test_uniformly_tilted_holes(tilt, expected):
    tees, greens = _tilted_nine([tilt] * 9)
    assert obliquity_signed(tees, greens, _circle()) == pytest.approx(expected, abs=1e-2)
    assert obliquity_abs(tees, greens, _circle()) == pytest.approx(0.5, abs=1e-2)


def test_mirror_tilts_cancel_in_the_signed_obliquity():
    tilts = [math.pi / 6, -math.pi / 6] * 4 + [0.0]
    tees, greens = _tilted_nine(tilts[:8])
    assert obliquity_signed(tees, greens, _circle()) == pytest.approx(0.0, abs=1e-2)
    assert obliquity_abs(tees, greens, _circle()) == pytest.approx(0.5, abs=1e-2)


def test_windmill_blades_have_a_one_sided_obliquity():
    tees, greens = _blades(twist=0.4)
    path = _circle(radius=105.0)
    signed = obliquity_signed(tees, greens, path)
    assert abs(signed) > 0.5
    assert obliquity_abs(tees, greens, path) == pytest.approx(abs(signed))
    # le même moulinet sur un chemin parcouru en sens inverse change de signe
    assert obliquity_signed(tees, greens, path[::-1]) == pytest.approx(-signed)


def test_obliquity_is_reported_per_nine_only_when_paths_are_given():
    layout = _windmill_course()
    bare = shape_metrics(layout)
    assert all("obliquity_signed" not in scope for scope in bare.values())
    path = _circle(radius=105.0)
    metrics = shape_metrics(layout, front_path=path, back_path=path)
    for nine in ("front", "back"):
        assert abs(metrics[nine]["obliquity_signed"]) == pytest.approx(
            metrics[nine]["obliquity_abs"], abs=1e-4)
        assert metrics[nine]["obliquity_abs"] > 0.5
    assert set(metrics["course"]) == set(bare["course"])
    assert json.loads(json.dumps(metrics, allow_nan=False)) == metrics


# -- métriques par nine (R2b) ------------------------------------------------

def _square(side: float, origin=(0.0, 0.0)):
    x, y = origin
    return [(x, y), (x + side, y), (x + side, y + side), (x, y + side)]


def test_heading_turns_counts_absolute_turns_between_successive_chords():
    straight_tees = [(i * 100.0, 0.0) for i in range(9)]
    straight_greens = [(i * 100.0 + 80.0, 0.0) for i in range(9)]
    assert heading_turns(straight_tees, straight_greens) == 0.0
    # tour régulier : 8 virages de 40° = 320° ; même valeur dans l'autre sens
    tees, greens = _blades(twist=0.0)
    tangent_tees = [_polar(100.0, i * 2 * math.pi / 9) for i in range(9)]
    tangent_greens = [_polar(100.0, (i + 0.5) * 2 * math.pi / 9) for i in range(9)]
    assert heading_turns(tangent_tees, tangent_greens) == pytest.approx(320.0 / 360.0)
    assert heading_turns(tangent_tees[::-1], tangent_greens[::-1]) == pytest.approx(320.0 / 360.0)
    assert heading_turns(tees, greens) == pytest.approx(320.0 / 360.0)
    # zigzag à ±90° : 8 virages de 90° = 2 tours, sans aucune progression nette
    zig_tees = [(0.0, 0.0)] * 9
    zig_greens = [(100.0, 0.0) if i % 2 == 0 else (0.0, 100.0) for i in range(9)]
    assert heading_turns(zig_tees, zig_greens) == pytest.approx(2.0)
    # hélice : deux tours en 9 trous → 8 virages de 80°
    helix_tees = [_polar(100.0, i * 4 * math.pi / 9) for i in range(9)]
    helix_greens = [_polar(100.0, (i + 0.5) * 4 * math.pi / 9) for i in range(9)]
    assert heading_turns(helix_tees, helix_greens) == pytest.approx(8 * 80.0 / 360.0)
    assert heading_turns(tees[:1], greens[:1]) == 0.0


def test_hull_ratio_compares_the_convex_hull_to_the_outer_ring():
    ring = _square(200.0)
    assert polygon_area(ring) == pytest.approx(40_000.0)
    assert polygon_area([*ring, ring[0]]) == pytest.approx(40_000.0)   # fermé ou non
    tees = [(50.0, 50.0), (150.0, 150.0), (100.0, 100.0)]              # point intérieur ignoré
    greens = [(150.0, 50.0), (50.0, 150.0), (60.0, 60.0)]
    assert len(convex_hull([*tees, *greens])) == 4
    assert hull_ratio(tees, greens, ring) == pytest.approx(0.25)
    assert hull_ratio([(0.0, 0.0), (10.0, 10.0)], [(5.0, 5.0), (20.0, 20.0)], ring) == 0.0
    circle = _circle(radius=100.0, count=720)
    assert polygon_area(circle) == pytest.approx(math.pi * 100.0 ** 2, rel=1e-4)
    with pytest.raises(ValueError):
        hull_ratio(tees, greens, [(0.0, 0.0), (1.0, 1.0)])


def test_path_to_nine_length_uses_the_nominal_nine_length():
    pars = (4,) * 9
    nominal = nominal_nine_length(pars)
    assert nominal == pytest.approx(9 * 122.5 + 10 * mf.LINK_NOMINAL)
    # même total que celui que green_targets répartit le long du chemin
    assert nominal == pytest.approx(sum(mf.LINK_NOMINAL + mf._nominal_length(p) for p in pars)
                                    + mf.LINK_NOMINAL)
    path = [(0.0, 0.0), (nominal / 2, 0.0), (nominal / 2, nominal / 2)]
    assert path_to_nine_length(path, pars) == pytest.approx(1.0)
    assert path_to_nine_length(path[:2], pars) == pytest.approx(0.5)


def test_forward_mean_flags_holes_played_backwards():
    path = [(0.0, 0.0), (1000.0, 0.0)]
    tees = [(100.0 * i, 5.0) for i in range(4)]
    forward = [(t[0] + 80.0, 5.0) for t in tees]
    backward = [(t[0] - 80.0, 5.0) for t in tees]
    across = [(t[0], 85.0) for t in tees]
    assert forward_mean(tees, forward, path) == pytest.approx(1.0)
    assert forward_mean(tees, backward, path) == pytest.approx(-1.0)
    assert forward_mean(tees, across, path) == pytest.approx(0.0, abs=1e-12)
    # obliquity_abs ne voit pas la différence : à rebours compte pour 0
    assert obliquity_abs(tees, backward, path) == pytest.approx(0.0, abs=1e-12)
    assert obliquity_abs(tees, forward, path) == pytest.approx(0.0, abs=1e-12)
    assert forward_mean([], [], path) == 0.0


# -- agrégation du runner --------------------------------------------------------

def test_shape_stats_skip_failures_and_missing_values():
    def ok(cv, entropy, r):
        return {"status": "succes", "shape": {"course": {
            "angular_step_cv": cv, "direction_entropy": entropy, "radial_alignment_R": r}}}
    reports = [ok(0.2, 0.5, 0.9), {"status": "echec", "seed": 4},
               ok(None, 0.7, 0.1), ok(0.6, 0.6, 0.5), ok(0.4, 0.8, None)]
    stats = _shape_stats(reports)
    assert stats["angular_step_cv"] == {"median": 0.4, "min": 0.2, "max": 0.6}
    assert stats["direction_entropy"] == {"median": 0.65, "min": 0.5, "max": 0.8}
    assert stats["radial_alignment_R"] == {"median": 0.5, "min": 0.1, "max": 0.9}
    assert _shape_stats([{"status": "echec"}, ok(None, 0.3, 0.3)])["angular_step_cv"] is None


def test_planche_title_lists_pattern_round_format_seed_and_outer_nine():
    from types import SimpleNamespace
    result = SimpleNamespace(pattern="muirfield", clubhouse_edge="N")
    assert _planche_title(result, "rc", 300, 400, 3, "front", "horaire") == (
        "muirfield RC · 300×400 · seed 3 · bord N · front extérieur horaire")
    inverse = SimpleNamespace(pattern="muirfield_inverse", clubhouse_edge="E")
    assert _planche_title(inverse, "land", 400, 300, 5, "back", "anti-horaire") == (
        "muirfield_inverse LAND · 400×300 · seed 5 · bord E · back extérieur anti-horaire")


def test_nine_shape_stats_split_outer_and_inner_nines():
    def ok(outer, front_turns, back_turns):
        return {"status": "succes", "outer_nine": outer,
                "shape": {"front": {"heading_turns": front_turns},
                          "back": {"heading_turns": back_turns}}}
    reports = [ok("front", 1.0, 2.0), ok("back", 3.0, 1.2), {"status": "echec"},
               ok("front", 1.1, 2.2)]
    stats = _nine_shape_stats(reports)
    assert stats["outer"]["heading_turns"] == {"median": 1.1, "min": 1.0, "max": 1.2}
    assert stats["inner"]["heading_turns"] == {"median": 2.2, "min": 2.0, "max": 3.0}
    assert stats["outer"]["hull_ratio"] is None


# -- métriques figées sur un vrai parcours -------------------------------------

# muirfield seed 1, 300×400, width_mode="min"
REAL_COURSE_SHAPE = {
    "front": {"angular_step_cv": 0.2681, "direction_entropy": 0.6749, "radial_alignment_R": 0.488,
              "obliquity_signed": -0.0213, "obliquity_abs": 0.2614,
              "heading_turns": 1.1867, "hull_ratio": 1.14, "forward_mean": 0.8809,
              "path_to_nine_length": 0.78},
    "back": {"angular_step_cv": 0.3325, "direction_entropy": 0.6983, "radial_alignment_R": 0.2601,
             "obliquity_signed": -0.0573, "obliquity_abs": 0.3451,
             "heading_turns": 1.8648, "hull_ratio": 0.4784, "forward_mean": 0.4435,
             "path_to_nine_length": 0.523},
    "course": {"angular_step_cv": 0.3164, "direction_entropy": 0.7739,
               "radial_alignment_R": 0.1139},
}


def test_shape_metrics_on_a_real_course_are_frozen():
    result = mf.build_course(1, "muirfield", width=300, height=400, width_mode="min")
    metrics = shape_metrics(result.layout, front_path=result.front_path,
                            back_path=result.back_path, outer_ring=result.outer_ring)
    assert metrics == REAL_COURSE_SHAPE
