"""Placement glouton de petites chaînes, sans recherche globale."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
import json
import math
import random

from experiments.bean_paving.bean_bank import BeanBank, BeanTemplate, generate_bank
from experiments.bean_paving.geometry import PlacedBean, Transform, ValidationRules, validate


@dataclass(frozen=True)
class LocalPlacementResult:
    seed: int
    requested: int
    clubhouse: tuple[float, float]
    placed: tuple[PlacedBean, ...]
    attempts: int
    rejection_counts: dict[str, int]

    @property
    def complete(self) -> bool:
        return len(self.placed) == self.requested

    def to_dict(self) -> dict:
        return {
            "seed": self.seed,
            "requested": self.requested,
            "complete": self.complete,
            "clubhouse": [round(value, 3) for value in self.clubhouse],
            "attempts": self.attempts,
            "rejection_counts": dict(sorted(self.rejection_counts.items())),
            "placed": [{
                "order": bean.order,
                "id": bean.id,
                "par": bean.template.par,
                "transform": {
                    "x": round(bean.transform.x, 4),
                    "y": round(bean.transform.y, 4),
                    "rotation_deg": round(bean.transform.rotation_deg, 4),
                    "mirrored": bean.transform.mirrored,
                },
            } for bean in self.placed],
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2, sort_keys=True) + "\n"


def _record(counter: Counter, problems) -> None:
    for kind in {problem.kind for problem in problems}:
        counter[kind] += 1


def _first_placements(bank: BeanBank, clubhouse: tuple[float, float], rng: random.Random):
    candidates = list(bank.templates)
    rng.shuffle(candidates)
    rotations = list(range(0, 360, 30))
    rng.shuffle(rotations)
    for template in candidates:
        for rotation in rotations:
            mirrors = [False, True] if template.allow_mirror else [False]
            rng.shuffle(mirrors)
            for mirrored in mirrors:
                yield template, Transform(clubhouse[0], clubhouse[1], rotation, mirrored)


def _next_placements(template: BeanTemplate, previous: PlacedBean, rng: random.Random):
    link_lengths = [24.0, 32.0, 40.0]
    link_angles = list(range(0, 360, 30))
    rotations = list(range(0, 360, 30))
    rng.shuffle(link_lengths)
    rng.shuffle(link_angles)
    rng.shuffle(rotations)
    mirrors = [False, True] if template.allow_mirror else [False]
    rng.shuffle(mirrors)
    for link_length in link_lengths:
        for link_angle in link_angles:
            radians = math.radians(link_angle)
            tee = (previous.green[0] + link_length * math.cos(radians),
                   previous.green[1] + link_length * math.sin(radians))
            for rotation in rotations:
                for mirrored in mirrors:
                    yield Transform(tee[0], tee[1], rotation, mirrored)


def place_local_chain(seed: int, requested: int = 4,
                      rules: ValidationRules | None = None) -> LocalPlacementResult:
    """Place jusqu'à ``requested`` haricots, sans backtracking."""
    rules = rules or ValidationRules()
    bank = generate_bank(seed)
    rng = random.Random(seed ^ 0xBEE5)
    clubhouse = (rules.width / 2.0, rules.height / 2.0)
    placed: list[PlacedBean] = []
    rejected: Counter = Counter()
    attempts = 0

    for template, transform in _first_placements(bank, clubhouse, rng):
        attempts += 1
        trial = PlacedBean(template, transform, 1)
        problems = validate([trial], rules)
        if not problems:
            placed.append(trial)
            break
        _record(rejected, problems)

    while placed and len(placed) < requested:
        candidates = [bean for bean in bank.templates if bean.id not in {item.id for item in placed}]
        rng.shuffle(candidates)
        accepted = False
        for template in candidates:
            for transform in _next_placements(template, placed[-1], rng):
                attempts += 1
                trial = PlacedBean(template, transform, len(placed) + 1)
                problems = validate([*placed, trial], rules)
                if not problems:
                    placed.append(trial)
                    accepted = True
                    break
                _record(rejected, problems)
            if accepted:
                break
        if not accepted:
            break

    return LocalPlacementResult(seed, requested, clubhouse, tuple(placed), attempts, dict(rejected))
