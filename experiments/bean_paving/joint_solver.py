"""Recherche conjointe front/back — alternance au lieu d'un enchaînement.

``solve_nine`` traite le résultat d'un nine comme un obstacle figé pour le
second, ce qui monopolise trop d'espace topologique (voir
``EXPERIMENT_18.md``). Ce module fait grandir les deux nines côte à côte sur
la même carte : à chaque pas, un seul des deux haricots avance (pas de
produit cartésien), choisi par le nombre de trous déjà posés, et chaque
candidat est validé en tenant compte de l'autre nine déjà posé — jamais
d'exemption à une règle dure de ``geometry.validate``.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
import json
import math

from experiments.bean_paving import freespace
from experiments.bean_paving.bean_bank import BeanBank, GenerationParams, generate_bank
from experiments.bean_paving.geometry import PlacedBean, ValidationRules, validate
from experiments.bean_paving.solver import (
    SearchState,
    SolverParams,
    expand_state,
)

# Quota global des 18 trous (voir PLAN.md, étape 6) ; la répartition par nine
# est libre, seul le total par classe est une contrainte dure.
GLOBAL_PAR_QUOTA = {3: 4, 4: 10, 5: 4}
_BACK_SEED_SALT = 0x9E3779B9


@dataclass(frozen=True)
class JointState:
    front: SearchState
    back: SearchState
    score: float

    @property
    def depth(self) -> int:
        return self.front.depth + self.back.depth


@dataclass(frozen=True)
class SideDiagnostics:
    parents: int
    trials: int
    accepted: int
    rejection_counts: dict[str, int]


@dataclass(frozen=True)
class JointDepthDiagnostics:
    global_step: int
    front: SideDiagnostics
    back: SideDiagnostics
    kept: int
    dead_ends: int


@dataclass(frozen=True)
class JointSolveResult:
    seed: int
    clubhouse: tuple[float, float]
    state: JointState
    complete: bool
    diagnostics: tuple[JointDepthDiagnostics, ...]
    params: SolverParams
    violations: tuple[str, ...]

    @property
    def total_trials(self) -> int:
        return sum(item.front.trials + item.back.trials for item in self.diagnostics)

    def to_dict(self) -> dict:
        def _side(state: SearchState) -> list[dict]:
            return [{
                "order": bean.order,
                "id": bean.id,
                "par": bean.template.par,
                "tee": [round(value, 4) for value in bean.tee],
                "green": [round(value, 4) for value in bean.green],
            } for bean in state.placed]

        return {
            "seed": self.seed,
            "complete": self.complete,
            "violations": list(self.violations),
            "clubhouse": [round(value, 4) for value in self.clubhouse],
            "score": round(self.state.score, 5),
            "total_trials": self.total_trials,
            "front": _side(self.state.front),
            "back": _side(self.state.back),
            "diagnostics": [{
                "global_step": item.global_step,
                "kept": item.kept,
                "dead_ends": item.dead_ends,
                "front": {
                    "parents": item.front.parents, "trials": item.front.trials,
                    "accepted": item.front.accepted,
                    "rejection_counts": dict(sorted(item.front.rejection_counts.items())),
                },
                "back": {
                    "parents": item.back.parents, "trials": item.back.trials,
                    "accepted": item.back.accepted,
                    "rejection_counts": dict(sorted(item.back.rejection_counts.items())),
                },
            } for item in self.diagnostics],
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2, sort_keys=True) + "\n"


def _global_remaining(front: SearchState, back: SearchState) -> tuple[int, int, int]:
    """Quota global restant, dérivé des haricots déjà posés des deux côtés —
    pas un compteur mutable séparé, pour que ``JointState`` reste
    ``(front, back, score)``."""
    used = Counter(bean.template.par for bean in (*front.placed, *back.placed))
    return tuple(GLOBAL_PAR_QUOTA[par] - used[par] for par in (3, 4, 5))


def _choose_side(front: SearchState, back: SearchState) -> str:
    """Fait grandir le nine qui a le moins de trous ; en cas d'égalité,
    ``front`` quand la profondeur totale est paire, sinon ``back``. À
    profondeurs égales la somme est toujours paire (2 * depth) : la branche
    ``back`` ne sert qu'à documenter la règle si ``depth`` cessait un jour
    d'être un simple compteur de trous posés.
    """
    if front.depth != back.depth:
        return "front" if front.depth < back.depth else "back"
    return "front" if (front.depth + back.depth) % 2 == 0 else "back"


def _side_view(state: SearchState, global_remaining: tuple[int, int, int]) -> SearchState:
    """Vue d'un état de nine avec le quota global substitué à son propre
    quota (qui n'existe pas en mode conjoint)."""
    return SearchState(state.placed, global_remaining, state.score)


def _joint_state_key(state: JointState) -> tuple:
    def side_key(side: SearchState):
        if not side.placed:
            return ((), None)
        last = side.placed[-1]
        return (tuple(sorted(bean.id for bean in side.placed)),
                (round(last.green[0] / 8), round(last.green[1] / 8),
                 round(last.transform.rotation_deg / 30)))

    return (side_key(state.front), side_key(state.back))


def _select_joint_beam(states: list[JointState], width: int) -> list[JointState]:
    """Round-robin par répartition (front.depth, back.depth), comme
    ``solver._select_beam`` round-robine par quota restant."""
    unique: dict[tuple, JointState] = {}
    for state in sorted(states, key=lambda item: item.score):
        unique.setdefault(_joint_state_key(state), state)
    buckets: dict[tuple[int, int], list[JointState]] = {}
    for state in unique.values():
        buckets.setdefault((state.front.depth, state.back.depth), []).append(state)
    for values in buckets.values():
        values.sort(key=lambda item: item.score)

    selected: list[JointState] = []
    while len(selected) < width and buckets:
        for key in sorted(list(buckets)):
            values = buckets[key]
            if values:
                selected.append(values.pop(0))
                if len(selected) == width:
                    break
            if not values:
                del buckets[key]
    return selected


def _with_freespace_penalty(state: JointState, clubhouse: tuple[float, float],
                            rules: ValidationRules) -> JointState:
    """N'évalue l'espace libre que sur les survivants du beam (lazy), car
    c'est une heuristique de score, pas une règle dure."""
    nines = {"front": state.front.placed, "back": state.back.placed}
    report = freespace.analyze(nines, clubhouse, rules)
    penalty = freespace.freespace_penalty(report)
    return JointState(state.front, state.back, state.score + penalty)


def _has_closing_moves(front: SearchState, back: SearchState) -> bool:
    """``front.remaining``/``back.remaining`` sont des instantanés figés au
    dernier moment où CE côté a été étendu (voir ``_side_view``) ; quand
    l'autre côté termine en dernier, ils sont périmés. Le quota réellement
    consommé ne peut se lire qu'en recomptant les haricots posés des DEUX
    côtés à cet instant, jamais via un ``.remaining`` stocké."""
    return (front.depth == 9 and back.depth == 9
            and _global_remaining(front, back) == (0, 0, 0))


def _joint_violations(front: tuple[PlacedBean, ...], back: tuple[PlacedBean, ...],
                      rules: ValidationRules, clubhouse: tuple[float, float],
                      clubhouse_max: float) -> list[str]:
    """Filet de sécurité final : les règles dures sont déjà vérifiées à
    chaque pas (candidat contre l'autre nine déjà posé), ceci ne fait que
    recontrôler l'ensemble complet avec le même oracle indépendant."""
    violations = [problem.kind for problem in validate((*front, *back), rules, check_links=False)]
    violations.extend(problem.kind for problem in validate(front, rules))
    violations.extend(problem.kind for problem in validate(back, rules))
    if len({bean.id for bean in (*front, *back)}) != len(front) + len(back):
        violations.append("duplicate_template")
    pars = [bean.template.par for bean in (*front, *back)]
    if len(pars) == 18 and {par: pars.count(par) for par in (3, 4, 5)} != GLOBAL_PAR_QUOTA:
        violations.append("par_quotas")
    for label, nine in (("front", front), ("back", back)):
        if not nine:
            violations.append(f"{label}_empty")
            continue
        if math.dist(nine[0].tee, clubhouse) > clubhouse_max:
            violations.append(f"{label}_start")
        if math.dist(nine[-1].green, clubhouse) > clubhouse_max:
            violations.append(f"{label}_return")
    return violations


def search_joint(seed: int, params: SolverParams | None = None,
                 rules: ValidationRules | None = None, *,
                 bank: BeanBank | None = None) -> JointSolveResult:
    params = params or SolverParams(beam_width=56)
    rules = rules or ValidationRules()
    clubhouse = (rules.width / 2.0, rules.height / 2.0)
    bank = bank or generate_bank(seed, GenerationParams.eighteen())
    front_seed, back_seed = seed, seed ^ _BACK_SEED_SALT

    empty = SearchState((), (GLOBAL_PAR_QUOTA[3], GLOBAL_PAR_QUOTA[4], GLOBAL_PAR_QUOTA[5]), 0.0)
    beam = [JointState(empty, empty, 0.0)]
    diagnostics: list[JointDepthDiagnostics] = []
    best = beam[0]

    for global_step in range(1, 19):
        next_states: list[JointState] = []
        front_rejected: Counter = Counter()
        back_rejected: Counter = Counter()
        front_trials = front_accepted = front_parents = 0
        back_trials = back_accepted = back_parents = 0
        dead_ends = 0

        for state in beam:
            side = _choose_side(state.front, state.back)
            if side == "front":
                own, other, own_seed, order_offset = state.front, state.back, front_seed, 0
            else:
                own, other, own_seed, order_offset = state.back, state.front, back_seed, 9

            global_remaining = _global_remaining(state.front, state.back)
            view = _side_view(own, global_remaining)
            target_depth = own.depth + 1
            blocked_ids = frozenset(bean.id for bean in other.placed)
            result = expand_state(view, target_depth, bank, clubhouse, params, rules, own_seed,
                                  obstacles=other.placed, blocked_ids=blocked_ids,
                                  order_offset=order_offset,
                                  par_quota=dict(zip((3, 4, 5), global_remaining)))

            if side == "front":
                front_trials += result.trials
                front_accepted += result.accepted
                front_rejected.update(result.rejected)
                front_parents += 1
            else:
                back_trials += result.trials
                back_accepted += result.accepted
                back_rejected.update(result.rejected)
                back_parents += 1
            if result.accepted == 0:
                dead_ends += 1

            for child in result.children:
                new_front, new_back = (child, other) if side == "front" else (other, child)
                next_states.append(JointState(new_front, new_back, new_front.score + new_back.score))

        if not next_states:
            diagnostics.append(JointDepthDiagnostics(
                global_step,
                SideDiagnostics(front_parents, front_trials, front_accepted, dict(front_rejected)),
                SideDiagnostics(back_parents, back_trials, back_accepted, dict(back_rejected)),
                0, dead_ends))
            break

        beam = _select_joint_beam(next_states, params.beam_width)
        beam = [_with_freespace_penalty(state, clubhouse, rules) for state in beam]
        beam.sort(key=lambda item: item.score)
        best = beam[0]
        diagnostics.append(JointDepthDiagnostics(
            global_step,
            SideDiagnostics(front_parents, front_trials, front_accepted, dict(front_rejected)),
            SideDiagnostics(back_parents, back_trials, back_accepted, dict(back_rejected)),
            len(beam), dead_ends))

    complete = _has_closing_moves(best.front, best.back)
    violations = _joint_violations(best.front.placed, best.back.placed, rules, clubhouse,
                                   params.clubhouse_max)
    complete = complete and not violations
    return JointSolveResult(seed, clubhouse, best, complete, tuple(diagnostics), params,
                            tuple(violations))
