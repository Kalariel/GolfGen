"""Spike : packer les 18 trous sans ordre, puis chercher deux chemins."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
import hashlib
import json
import math
import random

from experiments.bean_paving.bean_bank import BeanBank, BeanTemplate, GenerationParams, generate_bank
from experiments.bean_paving.geometry import PlacedBean, Transform, ValidationRules, validate

PACKING_PAR_ORDER = (5, 5, 5, 5, 4, 4, 4, 4, 4, 4, 4, 4, 4, 4, 3, 3, 3, 3)


@dataclass(frozen=True)
class PackingParams:
    beam_width: int = 42
    candidates_per_depth: int = 3
    transforms_per_candidate: int = 54


@dataclass(frozen=True)
class PackingState:
    placed: tuple[PlacedBean, ...]
    score: float


@dataclass(frozen=True)
class PackingResult:
    seed: int
    state: PackingState
    trials_by_depth: tuple[int, ...]
    accepted_by_depth: tuple[int, ...]
    rejection_counts: dict[str, int]
    rules: ValidationRules

    @property
    def complete(self) -> bool:
        return len(self.state.placed) == 18


@dataclass(frozen=True)
class RoutingResult:
    edges: tuple[tuple[int, int], ...]
    front: tuple[int, ...]
    back: tuple[int, ...]
    longest_path: tuple[int, ...]
    start_nodes: tuple[int, ...]
    return_nodes: tuple[int, ...]

    @property
    def complete(self) -> bool:
        return len(self.front) == len(self.back) == 9


@dataclass(frozen=True)
class PackThenRouteResult:
    packing: PackingResult
    routing: RoutingResult

    def to_dict(self) -> dict:
        return {
            "seed": self.packing.seed,
            "packing_complete": self.packing.complete,
            "packed_count": len(self.packing.state.placed),
            "routing_complete": self.routing.complete,
            "trials_by_depth": list(self.packing.trials_by_depth),
            "accepted_by_depth": list(self.packing.accepted_by_depth),
            "rejection_counts": self.packing.rejection_counts,
            "edge_count": len(self.routing.edges),
            "start_nodes": list(self.routing.start_nodes),
            "return_nodes": list(self.routing.return_nodes),
            "front": list(self.routing.front),
            "back": list(self.routing.back),
            "longest_path": list(self.routing.longest_path),
            "placed": [{
                "index": index,
                "id": bean.id,
                "par": bean.template.par,
                "tee": [round(value, 3) for value in bean.tee],
                "green": [round(value, 3) for value in bean.green],
                "transform": {
                    "x": round(bean.transform.x, 3),
                    "y": round(bean.transform.y, 3),
                    "rotation_deg": bean.transform.rotation_deg,
                    "mirrored": bean.transform.mirrored,
                },
            } for index, bean in enumerate(self.packing.state.placed)],
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2, sort_keys=True) + "\n"


def _rng(seed: int, state: PackingState, salt: str) -> random.Random:
    signature = ",".join(f"{b.id}:{b.transform.x:.0f}:{b.transform.y:.0f}:{b.transform.rotation_deg}"
                         for b in state.placed)
    digest = hashlib.sha256(f"{seed}|{salt}|{signature}".encode()).digest()
    return random.Random(int.from_bytes(digest[:8], "big"))


def _templates(bank: BeanBank, state: PackingState, par: int,
               params: PackingParams, seed: int) -> list[BeanTemplate]:
    used = {bean.id for bean in state.placed}
    available = [bean for bean in bank.templates if bean.par == par and bean.id not in used]
    rng = _rng(seed, state, f"templates-{par}")
    rng.shuffle(available)
    return available[:params.candidates_per_depth]


def _random_transforms(template: BeanTemplate, state: PackingState, rules: ValidationRules,
                       params: PackingParams, seed: int):
    rng = _rng(seed, state, template.id)
    yielded = set()
    attempts = params.transforms_per_candidate * 3
    for _ in range(attempts):
        rotation = rng.randrange(0, 360, 30)
        mirrored = rng.choice((False, True))
        origin = PlacedBean(template, Transform(0, 0, rotation, mirrored), len(state.placed) + 1)
        min_x = min(p[0] for p in origin.footprint)
        max_x = max(p[0] for p in origin.footprint)
        min_y = min(p[1] for p in origin.footprint)
        max_y = max(p[1] for p in origin.footprint)
        if max_x - min_x > rules.width or max_y - min_y > rules.height:
            continue
        x = rng.uniform(-min_x, rules.width - max_x)
        y = rng.uniform(-min_y, rules.height - max_y)
        key = (round(x / 4), round(y / 4), rotation, mirrored)
        if key in yielded:
            continue
        yielded.add(key)
        yield Transform(x, y, rotation, mirrored)
        if len(yielded) >= params.transforms_per_candidate:
            break


def _packing_score(placed: tuple[PlacedBean, ...], rules: ValidationRules) -> float:
    points = [point for bean in placed for point in bean.footprint]
    bbox = ((max(p[0] for p in points) - min(p[0] for p in points))
            * (max(p[1] for p in points) - min(p[1] for p in points)))
    # Un packing dense limite la fragmentation et laisse une grande zone libre.
    centers = [((min(p[0] for p in bean.footprint) + max(p[0] for p in bean.footprint)) / 2,
                (min(p[1] for p in bean.footprint) + max(p[1] for p in bean.footprint)) / 2)
               for bean in placed]
    center = (rules.width / 2, rules.height / 2)
    spread = sum(math.dist(point, center) for point in centers) / len(centers)
    return bbox * 0.0005 + spread * 0.025


def pack_unordered(seed: int, rules: ValidationRules | None = None,
                   params: PackingParams | None = None) -> PackingResult:
    rules = rules or ValidationRules()
    params = params or PackingParams()
    bank = generate_bank(seed, GenerationParams.eighteen())
    beam = [PackingState((), 0.0)]
    trials_by_depth, accepted_by_depth = [], []
    rejected: Counter = Counter()
    best = beam[0]

    for depth, par in enumerate(PACKING_PAR_ORDER, 1):
        children = []
        trials = accepted = 0
        for state in beam:
            for template in _templates(bank, state, par, params, seed):
                for transform in _random_transforms(template, state, rules, params, seed):
                    trials += 1
                    bean = PlacedBean(template, transform, depth)
                    candidate = (*state.placed, bean)
                    problems = validate(candidate, rules, check_links=False)
                    if problems:
                        for kind in {problem.kind for problem in problems}:
                            rejected[kind] += 1
                        continue
                    accepted += 1
                    children.append(PackingState(candidate, _packing_score(candidate, rules)))
        trials_by_depth.append(trials)
        accepted_by_depth.append(accepted)
        if not children:
            break
        children.sort(key=lambda item: item.score)
        # Plusieurs signatures spatiales grossières évitent les clones du beam.
        unique = {}
        for child in children:
            last = child.placed[-1]
            key = (tuple(sorted(bean.id for bean in child.placed)),
                   round(last.tee[0] / 15), round(last.tee[1] / 15),
                   round(last.transform.rotation_deg / 30))
            unique.setdefault(key, child)
        beam = list(unique.values())[:params.beam_width]
        best = beam[0]
    return PackingResult(seed, best, tuple(trials_by_depth), tuple(accepted_by_depth),
                         dict(sorted(rejected.items())), rules)


def route_packing(packing: PackingResult, link_min: float = 12.0,
                  link_max: float = 45.0, clubhouse_max: float = 50.0) -> RoutingResult:
    beans = packing.state.placed
    clubhouse = (packing.rules.width / 2, packing.rules.height / 2)
    edges = tuple((i, j) for i, first in enumerate(beans) for j, second in enumerate(beans)
                  if i != j and link_min <= math.dist(first.green, second.tee) <= link_max)
    adjacency = {i: [] for i in range(len(beans))}
    for first, second in edges:
        adjacency[first].append(second)
    starts = tuple(i for i, bean in enumerate(beans) if math.dist(bean.tee, clubhouse) <= clubhouse_max)
    returns = tuple(i for i, bean in enumerate(beans) if math.dist(bean.green, clubhouse) <= clubhouse_max)
    best: tuple[int, ...] = ()
    front_candidates = []

    def visit(path: tuple[int, ...], target: int, allowed: frozenset[int]):
        nonlocal best
        if len(path) > len(best):
            best = path
        if len(path) == target:
            if path[-1] in returns:
                yield path
            return
        for nxt in adjacency[path[-1]]:
            if nxt in allowed and nxt not in path:
                yield from visit((*path, nxt), target, allowed)

    all_nodes = frozenset(range(len(beans)))
    for start in starts:
        front_candidates.extend(visit((start,), 9, all_nodes))
    for front in front_candidates:
        remaining = all_nodes - set(front)
        for start in starts:
            if start not in remaining:
                continue
            for back in visit((start,), 9, remaining):
                if set(front) | set(back) == set(all_nodes):
                    return RoutingResult(edges, front, back, best, starts, returns)
    # Mesure aussi le plus long chemin sans contrainte clubhouse si aucun tee
    # n'est proche : cela distingue absence d'attache et graphe fragmenté.
    for start in range(len(beans)):
        tuple(visit((start,), len(beans), all_nodes))
    return RoutingResult(edges, (), (), best, starts, returns)


def run_pack_then_route(seed: int = 42, rules: ValidationRules | None = None,
                        params: PackingParams | None = None) -> PackThenRouteResult:
    packing = pack_unordered(seed, rules, params)
    routing = route_packing(packing) if packing.complete else RoutingResult((), (), (), (), (), ())
    return PackThenRouteResult(packing, routing)
