"""Régression : ``_has_closing_moves`` ne doit jamais se fier à un
``SearchState.remaining`` périmé (voir revue de code sur l'incrément A)."""

from experiments.bean_paving.bean_bank import BeanTemplate, _footprint
from experiments.bean_paving.geometry import PlacedBean, Transform, ValidationRules
from experiments.bean_paving.joint_solver import (
    JointState,
    _has_closing_moves,
    _quota_pressure_penalty,
    _select_penalized_beam,
)
from experiments.bean_paving.solver import SearchState, SolverParams


def _template(name, par):
    axis = ((0.0, 0.0), (60.0, 0.0))
    return BeanTemplate(name, par, 60.0, axis, 10.0, 5.0, axis, axis[0], axis[-1], 0.0, 0.0)


def _placed(pars, order_offset=0):
    return tuple(
        PlacedBean(_template(f"b{order_offset}-{i}", par), Transform(0.0, 0.0), order_offset + i)
        for i, par in enumerate(pars)
    )


def test_complete_when_stored_remaining_is_stale():
    # Comptes réels : front 2x par3 + 5x par4 + 2x par5 = 9, back idem = 9 ;
    # total 4/10/4, exactement le quota global. Mais le ``remaining`` stocké
    # sur chaque côté est un instantané périmé (jamais remis à jour depuis
    # la dernière extension de CE côté) et ne reflète pas ce total.
    front_pars = [3, 3, 4, 4, 4, 4, 4, 5, 5]
    back_pars = [3, 3, 4, 4, 4, 4, 4, 5, 5]
    front = SearchState(_placed(front_pars, 0), (0, 1, 0), 0.0)
    back = SearchState(_placed(back_pars, 9), (0, 0, 0), 0.0)

    assert _has_closing_moves(front, back) is True


def test_incomplete_when_global_quota_not_actually_met():
    # Les deux côtés sont à profondeur 9, mais le total réel des pars posés
    # ne correspond pas au quota global (un par5 de trop, un par3 manquant).
    front_pars = [4, 4, 4, 4, 4, 4, 4, 5, 5]
    back_pars = [3, 3, 4, 4, 4, 4, 4, 5, 5]
    front = SearchState(_placed(front_pars, 0), (0, 0, 0), 0.0)
    back = SearchState(_placed(back_pars, 9), (0, 0, 0), 0.0)

    assert _has_closing_moves(front, back) is False


def test_incomplete_when_depths_not_both_nine():
    front = SearchState(_placed([3, 3, 4, 4, 4, 4, 4, 5, 5], 0), (0, 0, 0), 0.0)
    back = SearchState(_placed([3, 3, 4, 4, 4, 4], 9), (1, 4, 2), 0.0)

    assert _has_closing_moves(front, back) is False


def _wall_bean(name, axis, width):
    return BeanTemplate(name, 4, 10.0, axis, width, 0.0, _footprint(axis, width / 2.0),
                        axis[0], axis[-1], 0.0, 0.0, allow_mirror=False)


def _goal_bean(name, green, par=4):
    axis = ((green[0] - 10.0, green[1]), green)
    return BeanTemplate(name, par, 10.0, axis, 10.0, 0.0, _footprint(axis, 5.0),
                        axis[0], axis[-1], 0.0, 0.0, allow_mirror=False)


def test_freespace_penalty_changes_which_joint_state_survives_the_beam():
    """Incrément B' : la pénalité d'espace libre doit influencer la survie
    au beam, pas seulement le score rapporté en sortie (bug de câblage
    décrit dans EXPERIMENT_18_JOINT.md). Cas construit : deux états de même
    profondeur (même case du round-robin), l'un avec un meilleur score brut
    mais un corridor pincé jusqu'à son green, l'autre avec un score brut
    moins bon mais un corridor ouvert."""
    rules = ValidationRules(width=120.0, height=120.0)
    clubhouse = (10.0, 60.0)

    # État A : score brut 0.0 (meilleur), mais deux murs qui laissent un
    # étroit goulot (8 blocs) entre le clubhouse et son green — même
    # géométrie que test_bean_freespace.test_corridor_width_is_smaller_*.
    north = _wall_bean("north", ((60.0, 0.0), (60.0, 56.0)), 4.0)
    south = _wall_bean("south", ((60.0, 64.0), (60.0, 120.0)), 4.0)
    goal_a = _goal_bean("goal-a", (110.0, 60.0))
    front_a = SearchState((
        PlacedBean(north, Transform(0.0, 0.0), 0),
        PlacedBean(south, Transform(0.0, 0.0), 1),
        PlacedBean(goal_a, Transform(0.0, 0.0), 2),
    ), (0, 0, 0), 0.0)
    state_a = JointState(front_a, SearchState((), (0, 0, 0), 0.0), 0.0)

    # État B : score brut 1.0 (moins bon), mais deux haricots minuscules
    # loin de l'axe clubhouse -> green, qui ne pincent rien.
    filler1 = _wall_bean("filler1", ((5.0, 5.0), (5.0, 6.0)), 1.0)
    filler2 = _wall_bean("filler2", ((5.0, 8.0), (5.0, 9.0)), 1.0)
    goal_b = _goal_bean("goal-b", (110.0, 60.0))
    front_b = SearchState((
        PlacedBean(filler1, Transform(0.0, 0.0), 0),
        PlacedBean(filler2, Transform(0.0, 0.0), 1),
        PlacedBean(goal_b, Transform(0.0, 0.0), 2),
    ), (0, 0, 0), 1.0)
    state_b = JointState(front_b, SearchState((), (0, 0, 0), 0.0), 1.0)

    assert state_a.front.depth == state_b.front.depth  # même case (front.depth, back.depth)

    off = SolverParams(beam_width=1, freespace_weight=0.0, freespace_pool_width=10)
    selected_off = _select_penalized_beam([state_a, state_b], clubhouse, rules, off)
    assert selected_off[0].front.placed[-1].id == "goal-a"  # meilleur score brut gagne

    on = SolverParams(beam_width=1, freespace_weight=4.0, freespace_pool_width=10)
    selected_on = _select_penalized_beam([state_a, state_b], clubhouse, rules, on)
    assert selected_on[0].front.placed[-1].id == "goal-b"  # le corridor pincé fait perdre A


def test_quota_pressure_penalty_is_zero_when_disabled():
    front = SearchState(_placed([3, 3, 3], 0), (0, 0, 0), 0.0)
    back = SearchState((), (0, 0, 0), 0.0)
    assert _quota_pressure_penalty(front, back, 0.0) == 0.0


def test_quota_pressure_penalty_is_zero_with_no_holes_placed():
    empty = SearchState((), (0, 0, 0), 0.0)
    assert _quota_pressure_penalty(empty, empty, 1.0) == 0.0


def test_quota_pressure_penalty_increases_when_par3_outpaces_its_expected_share():
    # Profondeur totale 4 ; part attendue par3 à cette profondeur = 4/18*4
    # ~ 0.89 trou. Poser 3 par3 dépasse largement cette part ; poser 0
    # par3/par5 (tout en par4) ne la dépasse jamais (la pénalité ne
    # sanctionne qu'un dépassement, jamais un retard).
    back_empty = SearchState((), (0, 0, 0), 0.0)
    front_over = SearchState(_placed([3, 3, 3, 4], 0), (0, 0, 0), 0.0)
    front_on_track = SearchState(_placed([4, 4, 4, 4], 0), (0, 0, 0), 0.0)

    over_penalty = _quota_pressure_penalty(front_over, back_empty, 1.0)
    on_track_penalty = _quota_pressure_penalty(front_on_track, back_empty, 1.0)

    assert over_penalty > on_track_penalty
    assert on_track_penalty == 0.0
