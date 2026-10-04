import math

from experiments.bean_paving.geometry import validate
from experiments.bean_paving.solver import PAR_QUOTAS, SolverParams, solve_nine


def test_seed_42_builds_a_valid_closed_nine():
    result = solve_nine(42)
    assert result.complete, result.to_dict()
    assert len(result.state.placed) == 9
    assert {par: sum(bean.template.par == par for bean in result.state.placed)
            for par in (3, 4, 5)} == PAR_QUOTAS
    assert len({bean.id for bean in result.state.placed}) == 9
    assert math.dist(result.state.placed[0].tee, result.clubhouse) <= result.params.clubhouse_max
    assert math.dist(result.state.placed[-1].green, result.clubhouse) <= result.params.clubhouse_max
    assert not validate(result.state.placed)


def test_solver_is_deterministic_with_small_beam():
    params = SolverParams(beam_width=12, candidates_per_par=2, transforms_per_candidate=18)
    assert solve_nine(42, params).to_json() == solve_nine(42, params).to_json()
