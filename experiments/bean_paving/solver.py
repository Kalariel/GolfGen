"""Beam search borné pour paver un nine de haricots abstraits."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
import hashlib
import json
import math
import random
from typing import Iterable

from experiments.bean_paving.bean_bank import BeanBank, BeanTemplate, generate_bank
from experiments.bean_paving.geometry import PlacedBean, Transform, ValidationRules, validate

PAR_QUOTAS = {3: 2, 4: 5, 5: 2}
FIRST_PAR_PENALTY = {4: 0.0, 3: 2.4, 5: 3.8}


@dataclass(frozen=True)
class SolverParams:
    beam_width: int = 48
    candidates_per_par: int = 3
    transforms_per_candidate: int = 30
    rotation_step_deg: int = 30
    link_lengths: tuple[float, ...] = (24.0, 32.0, 40.0)
    clubhouse_max: float = 50.0


@dataclass(frozen=True)
class SearchState:
    placed: tuple[PlacedBean, ...]
    remaining: tuple[int, int, int]  # pars 3, 4, 5
    score: float

    @property
    def depth(self) -> int:
        return len(self.placed)


@dataclass(frozen=True)
class DepthDiagnostics:
    depth: int
    parents: int
    trials: int
    accepted: int
    kept: int
    dead_ends: int
    rejection_counts: dict[str, int]


@dataclass(frozen=True)
class SolveResult:
    seed: int
    clubhouse: tuple[float, float]
    state: SearchState
    complete: bool
    diagnostics: tuple[DepthDiagnostics, ...]
    params: SolverParams

    @property
    def total_trials(self) -> int:
        return sum(item.trials for item in self.diagnostics)

    def to_dict(self) -> dict:
        return {
            "seed": self.seed,
            "complete": self.complete,
            "clubhouse": [round(value, 4) for value in self.clubhouse],
            "score": round(self.state.score, 5),
            "total_trials": self.total_trials,
            "params": {
                "beam_width": self.params.beam_width,
                "candidates_per_par": self.params.candidates_per_par,
                "transforms_per_candidate": self.params.transforms_per_candidate,
                "rotation_step_deg": self.params.rotation_step_deg,
                "link_lengths": list(self.params.link_lengths),
                "clubhouse_max": self.params.clubhouse_max,
            },
            "diagnostics": [{
                "depth": item.depth,
                "parents": item.parents,
                "trials": item.trials,
                "accepted": item.accepted,
                "kept": item.kept,
                "dead_ends": item.dead_ends,
                "rejection_counts": dict(sorted(item.rejection_counts.items())),
            } for item in self.diagnostics],
            "placed": [{
                "order": bean.order,
                "id": bean.id,
                "par": bean.template.par,
                "tee": [round(value, 4) for value in bean.tee],
                "green": [round(value, 4) for value in bean.green],
                "transform": {
                    "x": round(bean.transform.x, 4),
                    "y": round(bean.transform.y, 4),
                    "rotation_deg": round(bean.transform.rotation_deg, 4),
                    "mirrored": bean.transform.mirrored,
                },
            } for bean in self.state.placed],
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2, sort_keys=True) + "\n"


def _rng_for(seed: int, state: SearchState, salt: str) -> random.Random:
    signature = ",".join(bean.id for bean in state.placed)
    if state.placed:
        signature += f"@{state.placed[-1].green[0]:.2f},{state.placed[-1].green[1]:.2f}"
    digest = hashlib.sha256(f"{seed}|{salt}|{signature}".encode()).digest()
    return random.Random(int.from_bytes(digest[:8], "big"))


def _remaining_dict(values: tuple[int, int, int]) -> dict[int, int]:
    return dict(zip((3, 4, 5), values))


def _consume(values: tuple[int, int, int], par: int) -> tuple[int, int, int]:
    result = list(values)
    result[(3, 4, 5).index(par)] -= 1
    return tuple(result)


def _candidate_templates(bank: BeanBank, state: SearchState, par: int,
                         params: SolverParams, seed: int) -> list[BeanTemplate]:
    used = {bean.id for bean in state.placed}
    available = [bean for bean in bank.templates if bean.par == par and bean.id not in used]
    rng = _rng_for(seed, state, f"templates-{par}")
    rng.shuffle(available)
    return available[:params.candidates_per_par]


def _target_radius(depth: int) -> float:
    # Expansion pendant les quatre premiers trous, puis préparation du retour.
    return (0.0, 110.0, 150.0, 175.0, 185.0, 180.0, 160.0, 140.0, 110.0, 35.0)[depth]


def _raw_transforms(template: BeanTemplate, state: SearchState,
                    clubhouse: tuple[float, float], params: SolverParams):
    rotations = range(0, 360, params.rotation_step_deg)
    mirrors = (False, True) if template.allow_mirror else (False,)
    if not state.placed:
        # Le tee 1 reste proche du clubhouse, mais libère son centre pour le retour.
        for radius in (24.0, 36.0):
            for angle in range(0, 360, 30):
                rad = math.radians(angle)
                tee = (clubhouse[0] + radius * math.cos(rad),
                       clubhouse[1] + radius * math.sin(rad))
                for rotation in rotations:
                    for mirrored in mirrors:
                        yield Transform(tee[0], tee[1], rotation, mirrored)
        return

    previous = state.placed[-1]
    for link_length in params.link_lengths:
        for angle in range(0, 360, 30):
            rad = math.radians(angle)
            tee = (previous.green[0] + link_length * math.cos(rad),
                   previous.green[1] + link_length * math.sin(rad))
            for rotation in rotations:
                for mirrored in mirrors:
                    yield Transform(tee[0], tee[1], rotation, mirrored)


def _transform_rank(template: BeanTemplate, transform: Transform, depth: int,
                    clubhouse: tuple[float, float]) -> float:
    trial = PlacedBean(template, transform, depth)
    radius = math.dist(trial.green, clubhouse)
    rank = abs(radius - _target_radius(depth))
    # Les derniers trous privilégient franchement une direction de retour.
    if depth >= 7:
        rank += radius * (depth - 6) * 0.35
    return rank


def _transforms(template: BeanTemplate, state: SearchState,
                clubhouse: tuple[float, float], params: SolverParams, seed: int):
    depth = state.depth + 1
    transforms = list(_raw_transforms(template, state, clubhouse, params))
    rng = _rng_for(seed, state, f"transforms-{template.id}")
    rng.shuffle(transforms)  # départage déterministe des rangs égaux
    transforms.sort(key=lambda item: _transform_rank(template, item, depth, clubhouse))
    return transforms[:params.transforms_per_candidate]


def _state_score(placed: tuple[PlacedBean, ...], clubhouse: tuple[float, float]) -> float:
    depth = len(placed)
    points = [point for bean in placed for point in bean.footprint]
    min_x, max_x = min(p[0] for p in points), max(p[0] for p in points)
    min_y, max_y = min(p[1] for p in points), max(p[1] for p in points)
    bbox_area = (max_x - min_x) * (max_y - min_y)
    radius = math.dist(placed[-1].green, clubhouse)
    score = abs(radius - _target_radius(depth)) * 0.11 + bbox_area * 0.00018

    # Diversité de caps globaux, sans forcer neuf directions toutes différentes.
    bins = []
    for bean in placed:
        dx, dy = bean.green[0] - bean.tee[0], bean.green[1] - bean.tee[1]
        bins.append(round(math.degrees(math.atan2(dy, dx)) / 30.0) % 12)
    score += (len(bins) - len(set(bins))) * 1.7

    # Évite de coller durablement les bordures : réserve utile aux trous suivants.
    edge_clearance = min(min_x, min_y, 350.0 - max_x, 350.0 - max_y)
    if edge_clearance < 16.0:
        score += (16.0 - edge_clearance) * 0.35
    score += FIRST_PAR_PENALTY[placed[0].template.par]
    return score


def _state_key(state: SearchState) -> tuple:
    last = state.placed[-1]
    # Déduplique seulement les fins pratiquement identiques avec la même banque consommée.
    return (tuple(sorted(bean.id for bean in state.placed)),
            round(last.green[0] / 8), round(last.green[1] / 8),
            round(last.transform.rotation_deg / 30), state.remaining)


def _select_beam(states: Iterable[SearchState], width: int) -> list[SearchState]:
    """Conserve plusieurs profils de quotas au lieu d'un seul ordre de pars."""
    unique: dict[tuple, SearchState] = {}
    for state in sorted(states, key=lambda item: item.score):
        unique.setdefault(_state_key(state), state)
    buckets: dict[tuple[int, int, int], list[SearchState]] = {}
    for state in unique.values():
        buckets.setdefault(state.remaining, []).append(state)
    for values in buckets.values():
        values.sort(key=lambda item: item.score)

    selected: list[SearchState] = []
    # Round-robin : chaque composition encore vivante reçoit la même chance.
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


def _starts_outward(bean: PlacedBean, clubhouse: tuple[float, float]) -> bool:
    """Le trou 1 doit s'éloigner du clubhouse, pas le traverser."""
    tee_vector = (bean.tee[0] - clubhouse[0], bean.tee[1] - clubhouse[1])
    hole_vector = (bean.green[0] - bean.tee[0], bean.green[1] - bean.tee[1])
    return tee_vector[0] * hole_vector[0] + tee_vector[1] * hole_vector[1] > 0.0


def _has_closing_move(state: SearchState, bank: BeanBank, clubhouse: tuple[float, float],
                      params: SolverParams, rules: ValidationRules, seed: int) -> bool:
    """Regard exact d'un coup : un état à 8 doit avoir une fermeture réelle."""
    remaining = _remaining_dict(state.remaining)
    pars = [par for par in (4, 3, 5) if remaining[par] > 0]
    for par in pars:
        for template in _candidate_templates(bank, state, par, params, seed):
            for transform in _transforms(template, state, clubhouse, params, seed):
                placed = PlacedBean(template, transform, 9)
                if math.dist(placed.green, clubhouse) > params.clubhouse_max:
                    continue
                if not validate((*state.placed, placed), rules):
                    return True
    return False


def solve_nine(seed: int, params: SolverParams | None = None,
               rules: ValidationRules | None = None) -> SolveResult:
    params = params or SolverParams()
    rules = rules or ValidationRules()
    clubhouse = (rules.width / 2.0, rules.height / 2.0)
    bank = generate_bank(seed)
    beam = [SearchState((), (PAR_QUOTAS[3], PAR_QUOTAS[4], PAR_QUOTAS[5]), 0.0)]
    diagnostics: list[DepthDiagnostics] = []
    best = beam[0]

    for target_depth in range(1, 10):
        next_states: list[SearchState] = []
        rejected: Counter = Counter()
        trials = accepted = dead_ends = 0
        parent_count = len(beam)
        for state in beam:
            parent_children = 0
            remaining = _remaining_dict(state.remaining)
            pars = [par for par in (4, 3, 5) if remaining[par] > 0]
            for par in pars:
                for template in _candidate_templates(bank, state, par, params, seed):
                    for transform in _transforms(template, state, clubhouse, params, seed):
                        trials += 1
                        placed = PlacedBean(template, transform, target_depth)
                        candidate = (*state.placed, placed)
                        if target_depth == 1 and not _starts_outward(placed, clubhouse):
                            rejected["clubhouse_departure"] += 1
                            continue
                        problems = validate(candidate, rules)
                        if target_depth == 9 and math.dist(placed.green, clubhouse) > params.clubhouse_max:
                            rejected["clubhouse_return"] += 1
                            continue
                        if problems:
                            for kind in {problem.kind for problem in problems}:
                                rejected[kind] += 1
                            continue
                        remaining_after = _consume(state.remaining, par)
                        child = SearchState(candidate, remaining_after,
                                            _state_score(candidate, clubhouse))
                        if target_depth == 8:
                            closure = _has_closing_move(child, bank, clubhouse, params, rules, seed)
                            child = SearchState(candidate, remaining_after,
                                                child.score - 80.0 if closure else child.score + 80.0)
                        next_states.append(child)
                        accepted += 1
                        parent_children += 1
            if parent_children == 0:
                dead_ends += 1

        if not next_states:
            diagnostics.append(DepthDiagnostics(target_depth, parent_count, trials, accepted, 0,
                                                dead_ends, dict(rejected)))
            break
        beam = _select_beam(next_states, params.beam_width)
        best = beam[0]
        diagnostics.append(DepthDiagnostics(target_depth, parent_count, trials, accepted, len(beam),
                                            dead_ends, dict(rejected)))
        if target_depth == 9:
            break

    complete = best.depth == 9 and best.remaining == (0, 0, 0) \
        and math.dist(best.placed[-1].green, clubhouse) <= params.clubhouse_max
    return SolveResult(seed, clubhouse, best, complete, tuple(diagnostics), params)
