"""Coordination de deux recherches de nine sur une même carte 350x350."""

from __future__ import annotations

from dataclasses import dataclass
import json
import math

from experiments.bean_paving.bean_bank import GenerationParams, generate_bank
from experiments.bean_paving.geometry import PlacedBean, ValidationRules, validate
from experiments.bean_paving.solver import SolveResult, SolverParams, solve_nine


@dataclass(frozen=True)
class CourseSolveResult:
    seed: int
    front: SolveResult
    back: SolveResult | None
    complete: bool
    violations: tuple[str, ...]

    @property
    def placed(self) -> tuple[PlacedBean, ...]:
        return self.front.state.placed + (() if self.back is None else self.back.state.placed)

    def to_dict(self) -> dict:
        return {
            "seed": self.seed,
            "complete": self.complete,
            "violations": list(self.violations),
            "front": self.front.to_dict(),
            "back": None if self.back is None else self.back.to_dict(),
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2, sort_keys=True) + "\n"


def _course_violations(front: tuple[PlacedBean, ...], back: tuple[PlacedBean, ...],
                       rules: ValidationRules, clubhouse: tuple[float, float],
                       clubhouse_max: float) -> list[str]:
    violations = [problem.kind for problem in validate((*front, *back), rules, check_links=False)]
    violations.extend(problem.kind for problem in validate(front, rules))
    violations.extend(problem.kind for problem in validate(back, rules))
    if len({bean.id for bean in (*front, *back)}) != len(front) + len(back):
        violations.append("duplicate_template")
    for label, nine in (("front", front), ("back", back)):
        if not nine:
            violations.append(f"{label}_empty")
            continue
        if math.dist(nine[0].tee, clubhouse) > clubhouse_max:
            violations.append(f"{label}_start")
        if math.dist(nine[-1].green, clubhouse) > clubhouse_max:
            violations.append(f"{label}_return")
    if front and back:
        if math.dist(front[0].tee, back[0].tee) < 18.0:
            violations.append("starts_not_distinct")
        if math.dist(front[-1].green, back[-1].green) < 18.0:
            violations.append("returns_not_distinct")
    pars = [bean.template.par for bean in (*front, *back)]
    if len(pars) == 18 and {par: pars.count(par) for par in (3, 4, 5)} != {3: 4, 4: 10, 5: 4}:
        violations.append("par_quotas")
    return violations


def solve_course(seed: int, front_params: SolverParams | None = None,
                 back_params: SolverParams | None = None,
                 rules: ValidationRules | None = None) -> CourseSolveResult:
    rules = rules or ValidationRules()
    front_params = front_params or SolverParams(
        beam_width=72,
        departure_angles=(300, 330, 0, 30, 60),
        target_radius_scale=0.9,
        bbox_weight=0.0004,
    )
    back_params = back_params or SolverParams(
        beam_width=72,
        candidates_per_par=4,
        transforms_per_candidate=36,
        departure_angles=tuple(range(0, 360, 30)),
        start_radii=(44.0, 48.0),
        start_transforms_per_candidate=144,
    )
    bank = generate_bank(seed, GenerationParams.eighteen())
    front = solve_nine(seed, front_params, rules, bank=bank)
    if not front.complete:
        return CourseSolveResult(seed, front, None, False, ("front_incomplete",))

    used = frozenset(bean.id for bean in front.state.placed)
    back = solve_nine(seed ^ 0x9E3779B9, back_params, rules, bank=bank,
                      obstacles=front.state.placed, blocked_ids=used, order_offset=9)
    clubhouse = (rules.width / 2.0, rules.height / 2.0)
    violations = _course_violations(front.state.placed, back.state.placed, rules, clubhouse,
                                     back_params.clubhouse_max)
    if not back.complete:
        violations.append("back_incomplete")
    complete = front.complete and back.complete and not violations
    return CourseSolveResult(seed, front, back, complete, tuple(violations))
