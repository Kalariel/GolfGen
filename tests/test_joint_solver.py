"""Régression : ``_has_closing_moves`` ne doit jamais se fier à un
``SearchState.remaining`` périmé (voir revue de code sur l'incrément A)."""

from experiments.bean_paving.bean_bank import BeanTemplate
from experiments.bean_paving.geometry import PlacedBean, Transform
from experiments.bean_paving.joint_solver import _has_closing_moves
from experiments.bean_paving.solver import SearchState


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
