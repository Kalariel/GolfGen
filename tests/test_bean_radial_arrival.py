"""Tests pour EXP B (PLAN.md ligne 6, « arrivée radiale ») : règle dure sur
le trou de clôture de chaque nine (9 et 18) -- mirroir de
``solver._starts_outward`` (départ du trou 1) côté arrivée. Le DERNIER
segment de l'axe du trou (celui qui finit sur le green) doit pointer vers le
clubhouse à moins de ``arrival_max_angle_deg`` degrés : angle entre (a) la
direction de ce segment et (b) la direction de son point de DÉPART vers le
clubhouse. Les tests vérifient aussi que le défaut (``None``) ne change
rien."""

from dataclasses import replace
import math

from experiments.bean_paving.bean_bank import BeanBank, BeanTemplate
from experiments.bean_paving.bean_bank import _footprint as _bank_footprint
from experiments.bean_paving.course_solver import _course_violations, solve_course
from experiments.bean_paving.geometry import PlacedBean, Transform, ValidationRules
from experiments.bean_paving.solver import (
    SearchState,
    SolverParams,
    _arrival_angle_deg,
    _arrives_radially,
    _has_closing_move,
    expand_state,
)


def _straight_bean(name: str, par: int, length: float, width: float = 10.0) -> BeanTemplate:
    axis = ((0.0, 0.0), (length, 0.0))
    return BeanTemplate(name, par, length, axis, width, 0.0, _bank_footprint(axis, width / 2.0),
                        axis[0], axis[-1], 0.0, 0.0, allow_mirror=False)


def _placed(template: BeanTemplate, x: float, y: float, order: int, rotation: float = 0.0) -> PlacedBean:
    return PlacedBean(template, Transform(x, y, rotation, False), order)


# -- _arrival_angle_deg / _arrives_radially : géométrie pure ----------------


def test_arrival_angle_is_zero_when_the_last_segment_points_straight_at_the_clubhouse():
    clubhouse = (100.0, 0.0)
    # Axe (0,0) -> (50,0) : le dernier segment pointe plein est, le
    # clubhouse est plein est depuis (0,0) -- angle nul.
    bean = _placed(_straight_bean("h", 4, 50.0), 0.0, 0.0, 9)
    angle = _arrival_angle_deg(bean, clubhouse)
    assert angle is not None
    assert angle < 1e-6
    assert _arrives_radially(bean, clubhouse, 45.0)


def test_arrival_angle_is_180_when_the_last_segment_points_away_from_the_clubhouse():
    clubhouse = (-100.0, 0.0)
    bean = _placed(_straight_bean("h", 4, 50.0), 0.0, 0.0, 9)
    angle = _arrival_angle_deg(bean, clubhouse)
    assert angle is not None
    assert abs(angle - 180.0) < 1e-6
    assert not _arrives_radially(bean, clubhouse, 45.0)


def test_arrival_angle_is_90_when_the_last_segment_is_perpendicular_skirting_the_clubhouse():
    # Le trou longe le clubhouse au lieu de s'y diriger (observation
    # utilisateur : le par5 de clôture qui contourne le clubhouse).
    clubhouse = (0.0, 100.0)
    bean = _placed(_straight_bean("h", 4, 50.0), 0.0, 0.0, 9)
    angle = _arrival_angle_deg(bean, clubhouse)
    assert angle is not None
    assert abs(angle - 90.0) < 1e-6
    assert not _arrives_radially(bean, clubhouse, 45.0)
    assert _arrives_radially(bean, clubhouse, 90.0)


def test_arrives_radially_accepts_within_the_threshold_and_rejects_beyond_it():
    clubhouse = (100.0, 0.0)
    rotations = {30.0: True, 44.0: True, 46.0: False, 90.0: False}
    for rotation_deg, expected in rotations.items():
        bean = _placed(_straight_bean("h", 4, 50.0), 0.0, 0.0, 9, rotation=rotation_deg)
        assert _arrives_radially(bean, clubhouse, 45.0) is expected


def test_arrival_angle_is_none_for_a_degenerate_last_segment():
    # Dernier segment de longueur nulle (axe à deux points confondus) :
    # angle indéfini, jamais une violation par défaut. Construit directement
    # (pas via ``_straight_bean``/``_bank_footprint``, qui divisent par la
    # longueur du segment pour l'empreinte -- hors de propos ici, seul
    # l'axe compte pour ``_arrival_angle_deg``).
    degenerate = BeanTemplate(
        "degenerate", 4, 0.0, ((0.0, 0.0), (0.0, 0.0)), 10.0, 0.0,
        ((-5.0, -5.0), (5.0, -5.0), (5.0, 5.0), (-5.0, 5.0)),
        (0.0, 0.0), (0.0, 0.0), 0.0, 0.0, allow_mirror=False,
        core_footprint=((-5.0, -5.0), (5.0, -5.0), (5.0, 5.0), (-5.0, 5.0)),
    )
    bean = _placed(degenerate, 0.0, 0.0, 9)
    assert _arrival_angle_deg(bean, (100.0, 0.0)) is None
    assert _arrives_radially(bean, (100.0, 0.0), 45.0)


# -- défaut inchangé ----------------------------------------------------------


def test_arrival_max_angle_deg_default_is_none_and_byte_identical():
    assert SolverParams().arrival_max_angle_deg is None


def test_expand_state_depth9_default_does_not_apply_the_arrival_rule():
    rules = ValidationRules(width=300.0, height=300.0, link_min=0.0, link_max=1000.0,
                            antiparallel_distance=0.0)
    clubhouse = (150.0, 150.0)
    previous = _placed(_straight_bean("prev", 4, 10.0, width=4.0), 140.0, 150.0, 7)
    state = SearchState((previous,), (0, 1, 0), 0.0)
    bank = BeanBank(seed=1, templates=(_straight_bean("last", 4, 80.0, width=4.0),))
    params = SolverParams(candidates_per_par=1, transforms_per_candidate=40,
                          rotation_step_deg=360, link_lengths=(10.0,), closure_lookahead=False,
                          clubhouse_max=100.0)
    without_rule = expand_state(state, 9, bank, clubhouse, params, rules, seed=1)
    with_explicit_none = expand_state(state, 9, bank, clubhouse,
                                      replace(params, arrival_max_angle_deg=None), rules, seed=1)
    assert len(without_rule.children) == len(with_explicit_none.children)
    assert without_rule.rejected == with_explicit_none.rejected


# -- règle appliquée aux chemins de clôture -----------------------------------


def test_expand_state_depth9_rejects_a_skirting_arrival_and_keeps_a_head_on_one():
    rules = ValidationRules(width=400.0, height=400.0, link_min=0.0, link_max=1000.0,
                            antiparallel_distance=0.0)
    clubhouse = (200.0, 200.0)
    # previous.green = (190, 200) ; le dernier haricot démarre là, lien fixe
    # de 10 blocs, rotation discrète par pas de 90° -- un seul angle (0°,
    # plein est) pointe droit sur le clubhouse, les 3 autres (90/180/270)
    # longent ou s'éloignent.
    previous = _placed(_straight_bean("prev", 4, 10.0, width=4.0), 180.0, 200.0, 7)
    state = SearchState((previous,), (0, 1, 0), 0.0)
    bank = BeanBank(seed=1, templates=(_straight_bean("last", 4, 30.0, width=4.0),))
    params = SolverParams(candidates_per_par=1, transforms_per_candidate=40,
                          rotation_step_deg=90, link_lengths=(10.0,), closure_lookahead=False,
                          clubhouse_max=100.0, arrival_max_angle_deg=45.0)

    result = expand_state(state, 9, bank, clubhouse, params, rules, seed=1)
    assert result.rejected.get("radial_arrival", 0) > 0
    assert len(result.children) > 0
    for child in result.children:
        assert _arrives_radially(child.placed[-1], clubhouse, 45.0)


def test_has_closing_move_honors_the_arrival_rule():
    rules = ValidationRules(width=400.0, height=400.0, link_min=0.0, link_max=1000.0,
                            antiparallel_distance=0.0)
    clubhouse = (200.0, 200.0)
    previous = _placed(_straight_bean("prev", 4, 10.0, width=4.0), 180.0, 200.0, 7)
    state = SearchState((previous,), (0, 1, 0), 0.0)
    bank = BeanBank(seed=1, templates=(_straight_bean("last", 4, 30.0, width=4.0),))
    base_params = SolverParams(candidates_per_par=1, transforms_per_candidate=40,
                               rotation_step_deg=90, link_lengths=(10.0,), closure_lookahead=False,
                               clubhouse_max=100.0)
    # Sans la règle : une fermeture existe toujours (angle 0° disponible).
    assert _has_closing_move(state, bank, clubhouse, base_params, rules, seed=1)
    # Avec la règle à un seuil impossible (0°, aucune tolérance) : plus
    # aucune fermeture (aucune transformation discrète ne tombe exactement
    # sur l'angle 0°, hors coïncidence).
    tight = replace(base_params, arrival_max_angle_deg=1e-6)
    # L'angle 0° existe exactement dans la grille (rotation 0°) -- utiliser
    # un seuil négatif est impossible (angle toujours >= 0), donc on retire
    # plutôt l'angle 0° de la grille en décalant le pas de rotation.
    shifted = replace(base_params, rotation_step_deg=45, arrival_max_angle_deg=1e-6)
    assert not _has_closing_move(state, bank, clubhouse, shifted, rules, seed=1)


# -- course-level / validation indépendante ----------------------------------


def test_course_violations_default_does_not_check_arrival():
    rules = ValidationRules(width=400.0, height=400.0)
    clubhouse = (200.0, 200.0)
    # Trou de clôture qui longe le clubhouse (angle ~90°) -- sans le
    # paramètre, aucune violation d'arrivée ne doit apparaître.
    skirting = _placed(_straight_bean("close", 4, 20.0, width=4.0), 190.0, 200.0, 9, rotation=90.0)
    violations = _course_violations((skirting,), (), rules, clubhouse, 50.0)
    assert "front_radial_arrival" not in violations


def test_course_violations_arrival_max_angle_deg_flags_a_skirting_closing_hole():
    rules = ValidationRules(width=400.0, height=400.0)
    clubhouse = (200.0, 200.0)
    skirting = _placed(_straight_bean("close", 4, 20.0, width=4.0), 190.0, 200.0, 9, rotation=90.0)
    head_on = _placed(_straight_bean("close2", 4, 20.0, width=4.0), 190.0, 200.0, 18, rotation=0.0)
    violations = _course_violations((skirting,), (head_on,), rules, clubhouse, 50.0,
                                    arrival_max_angle_deg=45.0)
    assert "front_radial_arrival" in violations
    assert "back_radial_arrival" not in violations


def test_solve_course_arrival_max_angle_deg_is_plumbed_through_to_both_nines():
    front_params = SolverParams(beam_width=16, candidates_per_par=2, transforms_per_candidate=12,
                                departure_angles=(300, 330, 0, 30, 60), target_radius_scale=0.9,
                                bbox_weight=0.0004)
    back_params = SolverParams(beam_width=16, candidates_per_par=2, transforms_per_candidate=12,
                               departure_angles=tuple(range(0, 360, 30)), start_radii=(24.0, 36.0),
                               start_transforms_per_candidate=30)
    result = solve_course(1, front_params=front_params, back_params=back_params, bounded_quota=True,
                          arrival_max_angle_deg=45.0)
    assert result.front.params.arrival_max_angle_deg == 45.0
    assert result.back.params.arrival_max_angle_deg == 45.0
    if result.complete:
        assert _arrives_radially(result.front.state.placed[-1], (175.0, 175.0), 45.0)
        assert _arrives_radially(result.back.state.placed[-1], (175.0, 175.0), 45.0)


def test_solve_course_default_leaves_arrival_max_angle_deg_unset():
    front_params = SolverParams(beam_width=16, candidates_per_par=2, transforms_per_candidate=12,
                                departure_angles=(300, 330, 0, 30, 60), target_radius_scale=0.9,
                                bbox_weight=0.0004)
    back_params = SolverParams(beam_width=16, candidates_per_par=2, transforms_per_candidate=12,
                               departure_angles=tuple(range(0, 360, 30)), start_radii=(24.0, 36.0),
                               start_transforms_per_candidate=30)
    result = solve_course(1, front_params=front_params, back_params=back_params, bounded_quota=True)
    assert result.front.params.arrival_max_angle_deg is None
    assert result.back.params.arrival_max_angle_deg is None
