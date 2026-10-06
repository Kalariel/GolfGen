"""Expérience C1 « couloirs de départ réservés » (PLAN.md ligne 6) : départ
fixé de profondeur 1 (``SolverParams.fixed_start``), couloirs réservés
(``ValidationRules.reserved_corridors`` + couloir dynamique ``solver.
_own_start_corridor``/``corridor_from_own_start``) et divergence angulaire
tee1/tee10 (``SolverParams.start_angle_reference_deg``/
``start_angle_divergence_min_deg``). Chaque test isole une seule facette
(discipline PLAN.md, étape 2) : voir ``experiments/bean_paving/
run_exp_c1_corridors.py`` pour le contexte et le run seeds 1-5."""

from __future__ import annotations

from dataclasses import replace

from experiments.bean_paving.bean_bank import BeanBank, BeanTemplate, _footprint
from experiments.bean_paving.course_solver import _course_violations
from experiments.bean_paving.geometry import PlacedBean, Transform, ValidationRules, validate
from experiments.bean_paving.solver import (
    SearchState,
    SolverParams,
    _angular_distance_deg,
    _own_start_corridor,
    _placement_problems,
    _raw_transforms,
    _starts_divergent,
    _tee_angle_deg,
    expand_state,
)


def bean(name, axis=((0.0, 0.0), (60.0, 0.0)), width=10.0, margin=5.0, allow_mirror=True):
    axis = tuple(axis)
    return BeanTemplate(name, 4, 60.0, axis, width, margin,
                        _footprint(axis, width / 2 + margin), axis[0], axis[-1], 0.0, 0.0,
                        allow_mirror=allow_mirror)


def kinds(placed, rules, check_links=False, extra_corridors=()):
    return {item.kind for item in validate(placed, rules, check_links=check_links,
                                           extra_corridors=extra_corridors)}


# -- fixed_start ---------------------------------------------------------------


def test_fixed_start_default_is_none_and_byte_identical():
    assert SolverParams().fixed_start is None
    state = SearchState((), (0, 0, 0), 0.0)
    clubhouse = (200.0, 200.0)
    params = SolverParams()
    transforms = list(_raw_transforms(bean("x"), state, clubhouse, params, seed=1))
    expected = len(params.start_radii) * len(params.departure_angles) \
        * len(range(0, 360, params.rotation_step_deg)) * 2  # allow_mirror=True par défaut
    assert len(transforms) == expected


def test_fixed_start_yields_exactly_that_transform_plus_mirror_when_allowed():
    state = SearchState((), (0, 0, 0), 0.0)
    clubhouse = (200.0, 200.0)
    params = SolverParams(fixed_start=(123.0, 45.0, 67.0))
    mirrorable = bean("m", allow_mirror=True)
    transforms = list(_raw_transforms(mirrorable, state, clubhouse, params, seed=1))
    assert transforms == [Transform(123.0, 45.0, 67.0, False), Transform(123.0, 45.0, 67.0, True)]


def test_fixed_start_yields_a_single_transform_when_mirror_is_disallowed():
    state = SearchState((), (0, 0, 0), 0.0)
    clubhouse = (200.0, 200.0)
    params = SolverParams(fixed_start=(123.0, 45.0, 67.0))
    fixed = bean("f", allow_mirror=False)
    transforms = list(_raw_transforms(fixed, state, clubhouse, params, seed=1))
    assert transforms == [Transform(123.0, 45.0, 67.0, False)]


def test_fixed_start_ignores_start_radii_and_departure_angles():
    state = SearchState((), (0, 0, 0), 0.0)
    clubhouse = (200.0, 200.0)
    params = SolverParams(fixed_start=(999.0, -50.0, 10.0), start_radii=(24.0, 36.0),
                          departure_angles=(0, 90, 180, 270))
    transforms = list(_raw_transforms(bean("f", allow_mirror=False), state, clubhouse, params, seed=1))
    assert transforms == [Transform(999.0, -50.0, 10.0, False)]


# -- couloirs réservés statiques (ValidationRules.reserved_corridors) ----------


def test_reserved_corridors_default_is_empty_and_byte_identical():
    assert ValidationRules().reserved_corridors == ()
    rules = ValidationRules(width=200.0, height=200.0)
    blocker = PlacedBean(bean("blocker", ((0.0, 0.0), (40.0, 0.0)), width=10, margin=0), Transform(80, 80, 0), 2)
    assert "corridor_blocked" not in kinds((blocker,), rules)


def test_corridor_rejects_a_core_that_crosses_it():
    # Couloir clubhouse(100,100)->tee1(100,60) : segment vertical x=100,
    # y de 60 à 100. ``blocker`` (order 2, pas propriétaire) a son cœur
    # (rectangle local x[-5,45] y[-5,5], radius=5) transformé en (80,80) ->
    # x[75,125] y[75,85], ce qui traverse x=100 dans [60,100].
    rules = ValidationRules(width=200.0, height=200.0,
                            reserved_corridors=(((100.0, 100.0), (100.0, 60.0), 1),))
    blocker = PlacedBean(bean("blocker", ((0.0, 0.0), (40.0, 0.0)), width=10, margin=0), Transform(80, 80, 0), 2)
    assert "corridor_blocked" in kinds((blocker,), rules)


def test_corridor_owner_is_excluded_from_its_own_check():
    # Le trou 1 lui-même touche forcément ce couloir (son tee EST l'une des
    # deux extrémités) -- jamais une violation puisqu'il en est le
    # propriétaire (``owner_order``).
    rules = ValidationRules(width=200.0, height=200.0,
                            reserved_corridors=(((100.0, 100.0), (100.0, 60.0), 1),))
    owner = PlacedBean(bean("hole1", width=10, margin=5), Transform(100, 60, 0), 1)
    assert "corridor_blocked" not in kinds((owner,), rules)


def test_corridor_crossing_only_rough_is_accepted():
    # Même couloir, mais ``blocker`` ne touche plus que son ROUGH (pas son
    # cœur) -- le couloir ne porte que sur le cœur fairway.
    rules = ValidationRules(width=200.0, height=200.0,
                            reserved_corridors=(((100.0, 100.0), (100.0, 60.0), 1),))
    blocker = PlacedBean(bean("blocker", ((0.0, 0.0), (40.0, 0.0)), width=4, margin=8), Transform(105, 80, 0), 2)
    assert "corridor_blocked" not in kinds((blocker,), rules)


def test_validate_extra_corridors_argument_is_also_checked():
    rules = ValidationRules(width=200.0, height=200.0)
    blocker = PlacedBean(bean("blocker", ((0.0, 0.0), (40.0, 0.0)), width=10, margin=0), Transform(80, 80, 0), 2)
    assert "corridor_blocked" in kinds((blocker,), rules,
                                      extra_corridors=(((100.0, 100.0), (100.0, 60.0), 1),))


def test_validate_combines_rules_reserved_corridors_and_extra_corridors():
    rules = ValidationRules(width=200.0, height=200.0,
                            reserved_corridors=(((100.0, 100.0), (100.0, 60.0), 1),))
    blocker = PlacedBean(bean("blocker", ((0.0, 0.0), (40.0, 0.0)), width=10, margin=0), Transform(80, 80, 0), 2)
    # Deuxième couloir identique en géométrie mais propriétaire différent
    # (10, pas 1) : les deux s'appliquent, ``blocker`` n'est exclu d'aucun.
    violations = validate((blocker,), rules, extra_corridors=(((100.0, 100.0), (100.0, 60.0), 10),))
    assert sum(1 for v in violations if v.kind == "corridor_blocked") == 2


# -- couloir dynamique propre au nine (solver._own_start_corridor) -------------


def test_own_start_corridor_disabled_by_default():
    clubhouse = (200.0, 200.0)
    params = SolverParams()
    first = PlacedBean(bean("h1"), Transform(150.0, 200.0, 0), 1)
    state = SearchState((first,), (0, 0, 0), 0.0)
    assert _own_start_corridor(state, clubhouse, params) == ()


def test_own_start_corridor_empty_until_a_hole_is_placed():
    clubhouse = (200.0, 200.0)
    params = SolverParams(corridor_from_own_start=True)
    empty_state = SearchState((), (0, 1, 0), 0.0)
    assert _own_start_corridor(empty_state, clubhouse, params) == ()


def test_own_start_corridor_derives_clubhouse_to_the_first_placed_tee():
    clubhouse = (200.0, 200.0)
    params = SolverParams(corridor_from_own_start=True)
    first = PlacedBean(bean("h1"), Transform(150.0, 200.0, 0), 1)
    state = SearchState((first,), (0, 0, 0), 0.0)
    assert _own_start_corridor(state, clubhouse, params) == ((clubhouse, first.tee, 1),)


def test_placement_problems_rejects_a_candidate_crossing_the_own_start_corridor():
    rules = ValidationRules(width=400.0, height=400.0, shared_rough=True, fairway_gap=0.0,
                            clubhouse_clear_radius=None, edge_min=0.0)
    clubhouse = (200.0, 200.0)
    # hole1 : tee (160,200) -> green (200,200) -- couloir clubhouse->tee1 =
    # segment horizontal y=200, x dans [160, 200].
    hole1 = PlacedBean(bean("h1", ((0.0, 0.0), (40.0, 0.0)), width=4, margin=0), Transform(160.0, 200.0, 0.0), 1)
    state = SearchState((hole1,), (0, 1, 0), 0.0)
    corridors = _own_start_corridor(state, clubhouse, SolverParams(corridor_from_own_start=True))

    crossing = PlacedBean(bean("h2", ((0.0, 0.0), (0.0, 40.0)), width=4, margin=0), Transform(180.0, 180.0, 0.0), 2)
    problems = _placement_problems((hole1, crossing), (), rules, corridors)
    assert any(p.kind == "corridor_blocked" for p in problems)

    clear = PlacedBean(bean("h2b", ((0.0, 0.0), (0.0, 40.0)), width=4, margin=0), Transform(180.0, 260.0, 0.0), 2)
    clear_problems = _placement_problems((hole1, clear), (), rules, corridors)
    assert not any(p.kind == "corridor_blocked" for p in clear_problems)


# -- divergence angulaire tee1/tee10 -------------------------------------------


def test_start_angle_params_default_to_none_and_byte_identical():
    assert SolverParams().start_angle_reference_deg is None
    assert SolverParams().start_angle_divergence_min_deg is None


def test_angular_distance_deg_is_circular():
    assert _angular_distance_deg(0.0, 0.0) == 0.0
    assert _angular_distance_deg(0.0, 180.0) == 180.0
    assert _angular_distance_deg(10.0, 350.0) == 20.0
    assert _angular_distance_deg(359.0, 1.0) == 2.0


def test_starts_divergent_pure_function():
    clubhouse = (200.0, 200.0)
    near = PlacedBean(bean("near"), Transform(250.0, 200.0, 0), 1)  # angle 0
    far = PlacedBean(bean("far"), Transform(200.0, 250.0, 0), 1)  # angle 90
    assert _tee_angle_deg(near, clubhouse) == 0.0
    assert not _starts_divergent(near, clubhouse, reference_deg=0.0, min_divergence_deg=90.0)
    assert _starts_divergent(far, clubhouse, reference_deg=0.0, min_divergence_deg=90.0)


def test_expand_state_depth1_default_does_not_apply_divergence_filter():
    rules = ValidationRules(width=400.0, height=400.0, link_min=0.0, link_max=1000.0,
                            antiparallel_distance=0.0)
    clubhouse = (200.0, 200.0)
    state = SearchState((), (0, 1, 0), 0.0)
    bank = BeanBank(seed=1, templates=(bean("h", ((0.0, 0.0), (30.0, 0.0)), width=4, margin=0),))
    params = SolverParams(candidates_per_par=1, start_transforms_per_candidate=60,
                          rotation_step_deg=30, start_radii=(50.0,), departure_angles=(0, 90, 180, 270),
                          closure_lookahead=False)
    without_rule = expand_state(state, 1, bank, clubhouse, params, rules, seed=1)
    with_explicit_none = expand_state(state, 1, bank, clubhouse,
                                      replace(params, start_angle_reference_deg=None,
                                              start_angle_divergence_min_deg=None), rules, seed=1)
    assert len(without_rule.children) == len(with_explicit_none.children)
    assert without_rule.rejected == with_explicit_none.rejected


def test_expand_state_depth1_rejects_departures_near_the_reference_angle():
    rules = ValidationRules(width=400.0, height=400.0, link_min=0.0, link_max=1000.0,
                            antiparallel_distance=0.0)
    clubhouse = (200.0, 200.0)
    state = SearchState((), (0, 1, 0), 0.0)
    bank = BeanBank(seed=1, templates=(bean("h", ((0.0, 0.0), (30.0, 0.0)), width=4, margin=0),))
    params = SolverParams(candidates_per_par=1, start_transforms_per_candidate=60,
                          rotation_step_deg=30, start_radii=(50.0,), departure_angles=(0, 90, 180, 270),
                          closure_lookahead=False, start_angle_reference_deg=0.0,
                          start_angle_divergence_min_deg=90.0)
    result = expand_state(state, 1, bank, clubhouse, params, rules, seed=1)
    assert result.rejected.get("start_angle_divergence", 0) > 0
    assert len(result.children) > 0
    for child in result.children:
        angle = _tee_angle_deg(child.placed[-1], clubhouse)
        assert _angular_distance_deg(angle, 0.0) >= 90.0 - 1e-9


# -- validation indépendante (course_solver._course_violations) ---------------


def test_course_violations_reserved_corridors_default_is_byte_identical():
    rules = ValidationRules(width=400.0, height=400.0)
    clubhouse = (200.0, 200.0)
    front = (PlacedBean(bean("f", ((0.0, 0.0), (40.0, 0.0)), width=4, margin=0), Transform(170.0, 200.0, 0.0), 1),)
    without = _course_violations(front, (), rules, clubhouse, 50.0)
    with_empty = _course_violations(front, (), rules, clubhouse, 50.0, reserved_corridors=())
    assert without == with_empty


def test_course_violations_reserved_corridors_flags_a_blocked_corridor():
    rules = ValidationRules(width=400.0, height=400.0)
    clubhouse = (200.0, 200.0)
    front = (PlacedBean(bean("f", ((0.0, 0.0), (40.0, 0.0)), width=4, margin=0), Transform(170.0, 200.0, 0.0), 1),)
    blocker = PlacedBean(bean("blocker", ((0.0, 0.0), (0.0, 40.0)), width=4, margin=0), Transform(180.0, 180.0, 0.0), 2)
    violations = _course_violations(front, (blocker,), rules, clubhouse, 50.0,
                                    reserved_corridors=((clubhouse, (170.0, 200.0), 1),))
    assert "corridor_blocked" in violations
