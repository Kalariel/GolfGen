from experiments.bean_paving.bean_bank import BeanBank, BeanTemplate, _footprint
from experiments.bean_paving.geometry import PlacedBean, Transform, ValidationRules
from experiments.bean_paving.joint_solver import (
    GLOBAL_PAR_QUOTA,
    _choose_side,
    _global_remaining,
    search_joint,
)
from experiments.bean_paving.solver import SearchState, SolverParams, _has_closing_move


def _straight_bean(name, par, length, width=10.0):
    axis = ((0.0, 0.0), (length, 0.0))
    return BeanTemplate(name, par, length, axis, width, 0.0, _footprint(axis, width / 2.0),
                        axis[0], axis[-1], 0.0, 0.0, allow_mirror=False)


def _placed(template, x, y, order, rotation=0.0):
    return PlacedBean(template, Transform(x, y, rotation, False), order)


def test_choose_side_picks_the_nine_with_fewer_holes():
    empty = SearchState((), (0, 0, 0), 0.0)
    one = SearchState((_placed(_straight_bean("a", 4, 10.0), 0, 0, 1),), (0, 0, 0), 0.0)
    assert _choose_side(empty, one) == "front"
    assert _choose_side(one, empty) == "back"


def test_choose_side_is_deterministic_on_ties():
    empty = SearchState((), (0, 0, 0), 0.0)
    same_depth = SearchState((_placed(_straight_bean("a", 4, 10.0), 0, 0, 1),), (0, 0, 0), 0.0)
    first = _choose_side(empty, empty)
    second = _choose_side(same_depth, same_depth)
    assert first == _choose_side(empty, empty)
    assert second == _choose_side(same_depth, same_depth)


def test_global_remaining_subtracts_both_nines_from_the_shared_quota():
    front = SearchState((_placed(_straight_bean("a", 4, 10.0), 0, 0, 1),
                        _placed(_straight_bean("b", 4, 10.0), 50, 0, 2)), (0, 0, 0), 0.0)
    back = SearchState((_placed(_straight_bean("c", 3, 10.0), 0, 100, 1),), (0, 0, 0), 0.0)
    remaining = _global_remaining(front, back)
    assert remaining == (GLOBAL_PAR_QUOTA[3] - 1, GLOBAL_PAR_QUOTA[4] - 2, GLOBAL_PAR_QUOTA[5])


def test_global_quota_accepts_a_skewed_split_between_the_two_nines():
    # 6 par-4 posés côté front, 2 côté back : total 8 <= 10, quota global non
    # dépassé malgré une répartition par-nine très asymétrique (2/5/2 n'est
    # pas imposé par trou).
    front = SearchState(tuple(_placed(_straight_bean(f"f{i}", 4, 10.0), i * 30, 0, i)
                              for i in range(6)), (0, 0, 0), 0.0)
    back = SearchState(tuple(_placed(_straight_bean(f"b{i}", 4, 10.0), i * 30, 200, i)
                             for i in range(2)), (0, 0, 0), 0.0)
    remaining = _global_remaining(front, back)
    assert remaining[1] == GLOBAL_PAR_QUOTA[4] - 8
    assert remaining[1] >= 0


def test_global_quota_is_exhausted_exactly_at_the_global_total():
    front = SearchState(tuple(_placed(_straight_bean(f"f{i}", 4, 10.0), i * 30, 0, i)
                              for i in range(10)), (0, 0, 0), 0.0)
    back = SearchState((), (0, 0, 0), 0.0)
    remaining = _global_remaining(front, back)
    assert remaining == (GLOBAL_PAR_QUOTA[3], 0, GLOBAL_PAR_QUOTA[5])


def test_closing_move_is_obstacle_aware_for_the_other_nine():
    rules = ValidationRules(width=300.0, height=300.0, link_min=0.0, link_max=1000.0,
                            antiparallel_distance=0.0)
    clubhouse = (150.0, 150.0)
    params = SolverParams(candidates_per_par=1, transforms_per_candidate=80, clubhouse_max=60.0)
    previous = _placed(_straight_bean("prev", 4, 40.0), 130.0, 150.0, 8)  # green = (170, 150)
    state = SearchState((previous,), (0, 1, 0), 0.0)

    close_template = _straight_bean("close", 4, 20.0)
    bank = BeanBank(seed=1, templates=(close_template,))

    # Sans obstacle : une fermeture doit exister (clubhouse proche, rien pour bloquer).
    assert _has_closing_move(state, bank, clubhouse, params, rules, seed=1)

    # Un obstacle qui couvre toute la zone atteignable depuis le green précédent
    # doit faire disparaître la fermeture — même logique que
    # `course_solver.py` (l'autre nine posé est un obstacle, pas une exemption).
    big_wall = BeanTemplate(
        "wall", 4, 1.0, ((160.0, 150.0), (161.0, 150.0)),
        1.0, 0.0, ((90.0, 70.0), (250.0, 70.0), (250.0, 230.0), (90.0, 230.0)),
        (160.0, 150.0), (161.0, 150.0), 0.0, 0.0, allow_mirror=False,
    )
    obstacles = (_placed(big_wall, 0.0, 0.0, 0),)
    assert not _has_closing_move(state, bank, clubhouse, params, rules, seed=1, obstacles=obstacles)


def test_toy_joint_run_is_deterministic_with_small_beam():
    rules = ValidationRules(width=120.0, height=120.0)
    params = SolverParams(beam_width=6, candidates_per_par=2, transforms_per_candidate=6,
                          start_transforms_per_candidate=10, closure_lookahead=False)
    first = search_joint(7, params, rules)
    second = search_joint(7, params, rules)
    assert first.to_json() == second.to_json()

    pars = ([bean["par"] for bean in first.to_dict()["front"]]
            + [bean["par"] for bean in first.to_dict()["back"]])
    counts = {par: pars.count(par) for par in (3, 4, 5)}
    assert all(counts[par] <= GLOBAL_PAR_QUOTA[par] for par in (3, 4, 5))
