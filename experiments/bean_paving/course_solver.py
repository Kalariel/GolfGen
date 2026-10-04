"""Coordination de deux recherches de nine sur une même carte 350x350."""

from __future__ import annotations

from dataclasses import dataclass, replace
import json
import math

from experiments.bean_paving import halfplane
from experiments.bean_paving.bean_bank import GenerationParams, generate_bank
from experiments.bean_paving.geometry import PlacedBean, ValidationRules, validate
from experiments.bean_paving.joint_solver import JointSolveResult, search_joint
from experiments.bean_paving.solver import SolveResult, SolverParams, solve_nine


@dataclass(frozen=True)
class CourseSolveResult:
    seed: int
    front: SolveResult
    back: SolveResult | None
    complete: bool
    violations: tuple[str, ...]
    # Diagnostic de démarcation (rapport uniquement, EXPERIMENT_18_HALFPLANE.md
    # point D) : jamais utilisé par la recherche. Calculé avec le
    # ``theta``/``band`` effectifs de ``front.params`` même si le poids de
    # pénalité est à 0 (le partage géométrique existe indépendamment du biais).
    demarcation: dict | None = None

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
            "demarcation": self.demarcation,
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
                 rules: ValidationRules | None = None, *,
                 halfplane_weight: float | None = None,
                 halfplane_theta_deg: float | None = None,
                 halfplane_band: float | None = None) -> CourseSolveResult:
    """``halfplane_*`` : surcharge le biais souple de demi-plan
    (``halfplane.py``, EXPERIMENT_18_HALFPLANE.md) côté front uniquement, sans
    toucher au reste de ``front_params`` — ``None`` (défaut) ne change rien,
    comportement identique à avant ce paramètre. Le back reste libre
    (``back_params`` n'est jamais modifié ici)."""
    rules = rules or ValidationRules()
    front_params = front_params or SolverParams(
        beam_width=72,
        departure_angles=(300, 330, 0, 30, 60),
        target_radius_scale=0.9,
        bbox_weight=0.0004,
    )
    if halfplane_weight is not None or halfplane_theta_deg is not None or halfplane_band is not None:
        front_params = replace(
            front_params,
            halfplane_weight=front_params.halfplane_weight if halfplane_weight is None else halfplane_weight,
            halfplane_theta_deg=(front_params.halfplane_theta_deg if halfplane_theta_deg is None
                                 else halfplane_theta_deg),
            halfplane_band=front_params.halfplane_band if halfplane_band is None else halfplane_band,
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
    demarcation = {
        "theta_deg": front_params.halfplane_theta_deg,
        "band": front_params.halfplane_band,
        "wrong_side_holes": halfplane.wrong_side_count(
            front.state.placed, back.state.placed, clubhouse,
            front_params.halfplane_theta_deg, front_params.halfplane_band),
        "interleave_pairs": halfplane.interleave_pairs(front.state.placed, back.state.placed),
    }
    return CourseSolveResult(seed, front, back, complete, tuple(violations), demarcation)


def solve_course_joint(seed: int, params: SolverParams | None = None,
                       rules: ValidationRules | None = None) -> JointSolveResult:
    """Variante conjointe : les deux nines avancent en alternance sur la même
    carte au lieu de l'enchaînement front-puis-back de ``solve_course``.
    Motivation détaillée dans ``EXPERIMENT_18.md`` (le front, résolu seul,
    monopolise trop d'espace topologique pour le back). Ne remplace pas
    ``solve_course`` : les deux restent disponibles.
    """
    rules = rules or ValidationRules()
    params = params or SolverParams(beam_width=56)
    bank = generate_bank(seed, GenerationParams.eighteen())
    return search_joint(seed, params, rules, bank=bank)
