"""Biais souple de demi-plan (``halfplane.py``) et sélecteur d'orientation
(``orientation_search.py``). EXPERIMENT_18_HALFPLANE.md, points B/C/D.
"""

from __future__ import annotations

from types import SimpleNamespace

from experiments.bean_paving import halfplane
from experiments.bean_paving.bean_bank import BeanTemplate, _footprint
from experiments.bean_paving.geometry import PlacedBean, Transform
from experiments.bean_paving.orientation_search import OrientationRun, pick_best

CLUBHOUSE = (50.0, 50.0)


def bean(name, axis, width=10.0, margin=5.0):
    axis = tuple(axis)
    return BeanTemplate(name, 4, 60.0, axis, width, margin,
                        _footprint(axis, width / 2 + margin), axis[0], axis[-1], 0.0, 0.0)


def placed_at(name, axis):
    return PlacedBean(bean(name, axis), Transform(0, 0), 1)


# -- projection / intrusion_depth / front_penalty ---------------------------

def test_projection_zero_at_clubhouse_and_positive_toward_theta():
    assert halfplane.projection(CLUBHOUSE, CLUBHOUSE, theta_deg=0.0) == 0.0
    assert halfplane.projection((70.0, 50.0), CLUBHOUSE, theta_deg=0.0) == 20.0
    assert halfplane.projection((30.0, 50.0), CLUBHOUSE, theta_deg=0.0) == -20.0


def test_intrusion_depth_zero_inside_band():
    # Bande de 40 -> demi-bande 20 : un point à 15 du clubhouse, dans la
    # direction theta, reste dans la bande.
    points = ((65.0, 50.0),)
    assert halfplane.intrusion_depth(points, CLUBHOUSE, theta_deg=0.0, band=40.0) == 0.0


def test_intrusion_depth_monotonic_beyond_band():
    shallow = ((70.0, 50.0),)   # projection 20 -> depth 0 (pile sur la bordure de bande)
    deep = ((90.0, 50.0),)      # projection 40 -> depth 20
    deeper = ((120.0, 50.0),)   # projection 70 -> depth 50
    d_shallow = halfplane.intrusion_depth(shallow, CLUBHOUSE, theta_deg=0.0, band=40.0)
    d_deep = halfplane.intrusion_depth(deep, CLUBHOUSE, theta_deg=0.0, band=40.0)
    d_deeper = halfplane.intrusion_depth(deeper, CLUBHOUSE, theta_deg=0.0, band=40.0)
    assert d_shallow == 0.0
    assert 0.0 < d_deep < d_deeper


def test_front_penalty_zero_when_weight_is_zero():
    bean_far = placed_at("a", ((100.0, 50.0), (160.0, 50.0)))  # franchement côté back
    assert halfplane.front_penalty(bean_far, CLUBHOUSE, theta_deg=0.0, band=40.0, weight=0.0) == 0.0


def test_front_penalty_zero_inside_band_positive_beyond():
    # Le capuchon semi-circulaire du rough dépasse le green de son rayon de
    # dégagement (10 ici) : green à x=55 -> pointe la plus avancée à x=65,
    # soit une projection de 15 < demi-bande 20 -> profondeur nulle.
    shallow = placed_at("a", ((20.0, 50.0), (55.0, 50.0)))
    deep = placed_at("b", ((80.0, 50.0), (140.0, 50.0)))     # bien au-delà de la bande
    assert halfplane.front_penalty(shallow, CLUBHOUSE, theta_deg=0.0, band=40.0, weight=1.0) == 0.0
    assert halfplane.front_penalty(deep, CLUBHOUSE, theta_deg=0.0, band=40.0, weight=1.0) > 0.0


# -- diagnostics (point D) ---------------------------------------------------

def test_wrong_side_count_tiny_synthetic_case():
    # Un front qui reste chez lui (x petit) et un autre qui déborde loin dans
    # le camp back (x grand, theta=0 -> back = x croissant) ; un back qui
    # reste chez lui et un autre qui retourne loin côté front.
    front = (
        placed_at("f1", ((10.0, 50.0), (30.0, 50.0))),   # centroïde x=20 : côté front, pas d'erreur
        placed_at("f2", ((80.0, 50.0), (120.0, 50.0))),  # centroïde x=100 : déborde chez le back
    )
    back = (
        placed_at("b1", ((90.0, 50.0), (130.0, 50.0))),  # centroïde x=110 : côté back, correct
        placed_at("b2", ((5.0, 50.0), (15.0, 50.0))),    # centroïde x=10 : déborde chez le front
    )
    assert halfplane.wrong_side_count(front, back, CLUBHOUSE, theta_deg=0.0, band=40.0) == 2


def test_interleave_pairs_counts_touching_roughs_only():
    front = (placed_at("f1", ((10.0, 50.0), (40.0, 50.0))),)
    back_touching = (placed_at("b1", ((10.0, 58.0), (40.0, 58.0))),)   # rough se touche (largeur 10+marge 5)
    back_far = (placed_at("b2", ((10.0, 200.0), (40.0, 200.0))),)       # bien séparé
    assert halfplane.interleave_pairs(front, back_touching) == 1
    assert halfplane.interleave_pairs(front, back_far) == 0


# -- sélecteur d'orientation (point C) --------------------------------------

def _fake_run(theta, complete, front_depth, back_depth, front_score, back_score=0.0):
    front = SimpleNamespace(state=SimpleNamespace(depth=front_depth, score=front_score))
    back = None if back_depth is None else SimpleNamespace(state=SimpleNamespace(depth=back_depth, score=back_score))
    result = SimpleNamespace(complete=complete, front=front, back=back)
    return OrientationRun(theta, result, elapsed_s=0.0)


def test_pick_best_prefers_validated_18_over_more_holes_or_better_score():
    validated = _fake_run(0.0, complete=True, front_depth=9, back_depth=9, front_score=50.0)
    almost_better_score = _fake_run(90.0, complete=False, front_depth=9, back_depth=9, front_score=1.0)
    assert pick_best([validated, almost_better_score]) is validated


def test_pick_best_prefers_more_holes_when_none_validated():
    fewer_holes = _fake_run(0.0, complete=False, front_depth=9, back_depth=7, front_score=1.0)
    more_holes = _fake_run(180.0, complete=False, front_depth=9, back_depth=8, front_score=1000.0)
    assert pick_best([fewer_holes, more_holes]) is more_holes


def test_pick_best_breaks_ties_by_score():
    worse_score = _fake_run(0.0, complete=False, front_depth=9, back_depth=7, front_score=50.0)
    better_score = _fake_run(270.0, complete=False, front_depth=9, back_depth=7, front_score=10.0)
    assert pick_best([worse_score, better_score]) is better_score
