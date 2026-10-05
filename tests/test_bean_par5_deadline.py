"""Tests pour EXP A (PLAN.md ligne 6, « deadline par5 ») : le mode quota
borné (``solver.SolverParams.bounded_quota``) force normalement par3 ET
par5 sur la fenêtre PARTAGÉE des emplacements restants, ce qui les pousse
souvent tout en fin de nine. ``par5_deadline`` (opt-in, défaut ``None``)
donne au par5 sa PROPRE fenêtre de forçage, plus courte, et interdit tout
par5 qui compléterait encore le minimum une fois le délai dépassé. Les
tests vérifient aussi que le défaut ne change rien."""

from collections import Counter

from experiments.bean_paving.bean_bank import BeanTemplate
from experiments.bean_paving.bean_bank import _footprint as _bank_footprint
from experiments.bean_paving.course_solver import solve_course
from experiments.bean_paving.geometry import PlacedBean, Transform
from experiments.bean_paving.solver import SearchState, SolverParams, _bounded_quota_filter, solve_nine


def _straight_bean(name: str, par: int, length: float, width: float = 10.0) -> BeanTemplate:
    axis = ((0.0, 0.0), (length, 0.0))
    return BeanTemplate(name, par, length, axis, width, 0.0, _bank_footprint(axis, width / 2.0),
                        axis[0], axis[-1], 0.0, 0.0, allow_mirror=False)


def _placed(template: BeanTemplate, x: float, y: float, order: int, rotation: float = 0.0) -> PlacedBean:
    return PlacedBean(template, Transform(x, y, rotation, False), order)


def _counts(placed: tuple) -> dict[int, int]:
    return dict(Counter(bean.template.par for bean in placed))


# -- défaut inchangé --------------------------------------------------------


def test_par5_deadline_default_is_none_and_byte_identical():
    assert SolverParams().par5_deadline is None
    params_implicit = SolverParams(beam_width=12, candidates_per_par=2, transforms_per_candidate=18,
                                   bounded_quota=True)
    params_explicit = SolverParams(beam_width=12, candidates_per_par=2, transforms_per_candidate=18,
                                   bounded_quota=True, par5_deadline=None)
    assert solve_nine(42, params_implicit).to_json() == solve_nine(42, params_explicit).to_json()


def test_bounded_quota_filter_without_deadline_is_unchanged():
    # Même scénario que l'ancien test « forces both classes when tight » :
    # sans deadline, le comportement partagé historique doit rester identique.
    template4 = _straight_bean("t4", 4, 10.0)
    placed = tuple(_placed(template4, i * 20.0, 0.0, i) for i in range(7))
    state = SearchState(placed, (0, 0, 0), 0.0)
    params = SolverParams()
    assert _bounded_quota_filter([3, 4, 5], state, 8, params, None) == [3, 5]


# -- forçage précoce du par5 -------------------------------------------------


def test_bounded_quota_filter_forces_par5_early_with_a_deadline():
    # Profondeur 6 (4 emplacements restants dont celui-ci), deadline=7 :
    # fenêtre du par5 = 7 - 6 + 1 = 2, besoin encore 1 -> pas encore forcé
    # (1 < 2), les 3 classes restent éligibles. À la profondeur 7, fenêtre
    # = 1, besoin 1 -> le par5 devient la SEULE classe éligible.
    params = SolverParams(par5_deadline=7)
    placed = ()
    state = SearchState(placed, (0, 0, 0), 0.0)
    assert _bounded_quota_filter([3, 4, 5], state, 6, params, None) == [3, 4, 5]
    assert _bounded_quota_filter([3, 4, 5], state, 7, params, None) == [5]


def test_bounded_quota_filter_forbids_a_minimum_filling_par5_past_the_deadline():
    # Minimum par5 toujours manquant à la profondeur 8 (deadline=7 déjà
    # dépassé) : le par5 doit disparaître de la liste éligible -- plus de
    # forçage possible, et il n'est pas encore au-dessus du minimum.
    params = SolverParams(par5_deadline=7)
    placed = ()
    state = SearchState(placed, (0, 0, 0), 0.0)
    eligible = _bounded_quota_filter([3, 4, 5], state, 8, params, None)
    assert 5 not in eligible


def test_bounded_quota_filter_allows_an_excess_par5_past_the_deadline():
    # Minimum par5 déjà atteint (1 posé) : au-delà du délai, un par5
    # EXCÉDENTAIRE reste permis tant que le plafond haut n'est pas atteint.
    template5 = _straight_bean("t5", 5, 10.0)
    placed = (_placed(template5, 0.0, 0.0, 0),)
    state = SearchState(placed, (0, 0, 0), 0.0)
    params = SolverParams(par5_deadline=7, par5_bounds=(1, 3))
    eligible = _bounded_quota_filter([3, 4, 5], state, 8, params, None)
    assert 5 in eligible


def test_bounded_quota_filter_deadline_does_not_change_par3_forcing():
    # Le par3 garde sa fenêtre partagée historique même quand ``par5_deadline``
    # est renseigné -- seul le par5 a une fenêtre propre.
    template4 = _straight_bean("t4", 4, 10.0)
    placed = tuple(_placed(template4, i * 20.0, 0.0, i) for i in range(8))
    state = SearchState(placed, (0, 0, 0), 0.0)
    params = SolverParams(par5_deadline=7)
    assert _bounded_quota_filter([3, 4, 5], state, 9, params, None) == [3]


def test_bounded_quota_filter_excludes_par5_but_does_not_yet_force_par3_past_the_deadline():
    # Même scénario que l'ancien test « forces both classes when tight »
    # (profondeur 8, 1 par3 ET 1 par5 encore nécessaires, 2 emplacements
    # restants), mais la deadline est déjà dépassée (7) : le garde-fou joint
    # ne se déclenche plus (``depth <= deadline`` faux), donc le par3 N'EST
    # PAS forcé à CE coup précis (1 besoin < 2 emplacements restants, comme
    # la fenêtre partagée historique l'aurait permis seul) -- mais le par5
    # est définitivement exclu (minimum manqué, plus de forçage possible).
    template4 = _straight_bean("t4", 4, 10.0)
    placed = tuple(_placed(template4, i * 20.0, 0.0, i) for i in range(7))
    state = SearchState(placed, (0, 0, 0), 0.0)
    params = SolverParams(par5_deadline=7)
    eligible = _bounded_quota_filter([3, 4, 5], state, 8, params, None)
    assert eligible == [3, 4]


def test_bounded_quota_filter_forces_both_when_jointly_tight_before_the_deadline():
    # Profondeur 5 (5 emplacements restants), deadline=7 : le par5 est
    # encore dans sa fenêtre (7 - 5 + 1 = 3 >= besoin 1, pas encore forcé
    # seul), mais le garde-fou joint (besoin total 2 >= 5 restants ? non,
    # 2 < 5) ne force rien non plus ici -- sert à vérifier l'absence de
    # faux positif avant que la fenêtre ne devienne tendue.
    template4 = _straight_bean("t4", 4, 10.0)
    placed = tuple(_placed(template4, i * 20.0, 0.0, i) for i in range(4))
    state = SearchState(placed, (0, 0, 0), 0.0)
    params = SolverParams(par5_deadline=7)
    eligible = _bounded_quota_filter([3, 4, 5], state, 5, params, None)
    assert eligible == [3, 4, 5]


# -- intégration solve_course ------------------------------------------------


_FRONT_PARAMS = SolverParams(beam_width=16, candidates_per_par=2, transforms_per_candidate=12,
                             departure_angles=(300, 330, 0, 30, 60), target_radius_scale=0.9,
                             bbox_weight=0.0004)
_BACK_PARAMS = SolverParams(beam_width=16, candidates_per_par=2, transforms_per_candidate=12,
                            departure_angles=tuple(range(0, 360, 30)), start_radii=(24.0, 36.0),
                            start_transforms_per_candidate=30)


def test_solve_course_default_leaves_par5_deadline_unset_on_both_nines():
    result = solve_course(1, front_params=_FRONT_PARAMS, back_params=_BACK_PARAMS, bounded_quota=True)
    assert result.front.params.par5_deadline is None
    assert result.back.params.par5_deadline is None


def test_solve_course_par5_deadline_is_plumbed_through_to_both_nines():
    result = solve_course(1, front_params=_FRONT_PARAMS, back_params=_BACK_PARAMS, bounded_quota=True,
                          par5_deadline=7)
    assert result.front.params.par5_deadline == 7
    assert result.back.params.par5_deadline == 7


def test_solve_course_par5_deadline_keeps_front_par5_within_the_deadline_when_complete():
    # Quand le front complète 9/9 sous la deadline, le MINIMUM de par5
    # (``par5_bounds[0]``) doit être atteint au plus tard au trou 7 (play
    # order 1-indexé) -- un par5 EXCÉDENTAIRE (au-delà du minimum) reste
    # permis aux trous 8-9, voir ``_bounded_quota_filter``.
    for seed in (1, 2, 3):
        result = solve_course(seed, front_params=_FRONT_PARAMS, back_params=_BACK_PARAMS,
                              bounded_quota=True, par5_deadline=7)
        if not result.front.complete:
            continue
        placed = result.front.state.placed
        par5_lo = result.front.params.par5_bounds[0]
        par5_count_by_7 = sum(1 for bean in placed[:7] if bean.template.par == 5)
        assert par5_count_by_7 >= par5_lo
        counts = _counts(placed)
        assert sum(counts.values()) == 9
