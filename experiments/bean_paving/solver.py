"""Beam search borné pour paver un nine de haricots abstraits."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
import hashlib
import json
import math
import random
from typing import Iterable

from experiments.bean_paving import halfplane
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
    departure_angles: tuple[int, ...] = tuple(range(0, 360, 30))
    start_radii: tuple[float, ...] = (24.0, 36.0)
    start_transforms_per_candidate: int = 60
    target_radius_scale: float = 1.0
    bbox_weight: float = 0.00018
    closure_lookahead: bool = True
    # Pénalité d'espace libre (``freespace.py``) : seule la recherche conjointe
    # (``joint_solver.py``) l'utilise, sur un pool borné de candidats évalué
    # AVANT la sélection du beam (voir ``joint_solver._select_penalized_beam``
    # et EXPERIMENT_18_JOINT.md, incrément B' — avant B' elle n'influençait
    # que le score rapporté du meilleur état, jamais la survie au beam).
    # Défauts alignés sur ceux de ``freespace.freespace_penalty``.
    freespace_weight: float = 1.0
    freespace_min_corridor: float = 15.0
    # Taille du pool de candidats bruts (triés par score non pénalisé) sur
    # lequel la pénalité d'espace libre et la pression de quota sont
    # évaluées avant sélection — borne le coût de ``freespace.analyze``
    # (recherche conjointe uniquement).
    freespace_pool_width: int = 240
    # Pénalité de pression de quota (recherche conjointe uniquement) :
    # hypothèse testée, pas un fait acquis (EXPERIMENT_18_JOINT.md, B').
    # Désactivée par défaut pour ne rien changer tant qu'elle n'est pas
    # explicitement activée.
    quota_pressure_weight: float = 0.0
    # Biais souple de demi-plan (score uniquement, EXPERIMENT_18_HALFPLANE.md,
    # ``halfplane.py``) : désactivé par défaut (poids 0) pour ne rien changer
    # au comportement existant. Côté front, pénalise l'intrusion dans le camp
    # "back" (direction ``halfplane_theta_deg``) au-delà de la bande de
    # transition ``halfplane_band`` ; le back reste libre tant que son propre
    # ``halfplane_weight`` reste à 0.
    halfplane_weight: float = 0.0
    halfplane_theta_deg: float = 0.0
    halfplane_band: float = 40.0
    # Fermeture anticipée (EXPERIMENT_18_CLOSURE.md) : généralise l'ancien
    # regard d'un coup (toujours déclenché à la profondeur 8, cas particulier
    # ``closing_lookahead_from=9``) à des profondeurs plus précoces. Le
    # déclenchement couvre les profondeurs ``[closing_lookahead_from - 1, 8]``
    # ; ``9`` (défaut) donne exactement l'ancien comportement (profondeur 8
    # seule). Sans effet si ``closure_lookahead`` est ``False``.
    closing_lookahead_from: int = 9
    # Largeur réduite des pas INTERMÉDIAIRES de la fermeture anticipée
    # (``steps_remaining > 1``) — une sonde de plausibilité bon marché, pas
    # une énumération exhaustive. Le dernier pas (celui qui referme vraiment
    # sur le clubhouse) utilise toujours la largeur normale
    # (``candidates_per_par``/``transforms_per_candidate``), donc ces deux
    # valeurs ne changent rien quand ``closing_lookahead_from`` reste à 9.
    lookahead_candidates_per_par: int = 1
    lookahead_transforms_per_candidate: int = 4


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
                "departure_angles": list(self.params.departure_angles),
                "start_radii": list(self.params.start_radii),
                "start_transforms_per_candidate": self.params.start_transforms_per_candidate,
                "target_radius_scale": self.params.target_radius_scale,
                "bbox_weight": self.params.bbox_weight,
                "closure_lookahead": self.params.closure_lookahead,
                "closing_lookahead_from": self.params.closing_lookahead_from,
                "lookahead_candidates_per_par": self.params.lookahead_candidates_per_par,
                "lookahead_transforms_per_candidate": self.params.lookahead_transforms_per_candidate,
                "halfplane_weight": self.params.halfplane_weight,
                "halfplane_theta_deg": self.params.halfplane_theta_deg,
                "halfplane_band": self.params.halfplane_band,
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


def _par_order(par_quota: dict[int, int]) -> tuple[int, int, int]:
    """Classe le plus demandé d'abord ; égalité tranchée par la valeur du par.

    Reproduit l'ordre historiquement câblé ``(4, 3, 5)`` pour le quota par
    défaut ``PAR_QUOTAS``, mais dérive de ``par_quota`` pour qu'un compteur
    partagé (recherche conjointe) réordonne correctement les classes.
    """
    return tuple(sorted((3, 4, 5), key=lambda par: (-par_quota.get(par, 0), par)))


def _consume(values: tuple[int, int, int], par: int) -> tuple[int, int, int]:
    result = list(values)
    result[(3, 4, 5).index(par)] -= 1
    return tuple(result)


def _candidate_templates(bank: BeanBank, state: SearchState, par: int,
                         params: SolverParams, seed: int,
                         blocked_ids: frozenset[str] = frozenset()) -> list[BeanTemplate]:
    used = {bean.id for bean in state.placed} | set(blocked_ids)
    available = [bean for bean in bank.templates if bean.par == par and bean.id not in used]
    rng = _rng_for(seed, state, f"templates-{par}")
    rng.shuffle(available)
    return available[:params.candidates_per_par]


def _target_radius(depth: int) -> float:
    # Expansion pendant les quatre premiers trous, puis préparation du retour.
    return (0.0, 110.0, 150.0, 175.0, 185.0, 180.0, 160.0, 140.0, 110.0, 35.0)[depth]


def _scaled_target_radius(depth: int, params: SolverParams, rules: ValidationRules) -> float:
    # Le retour reste lié à clubhouse_max ; les phases d'expansion utilisent
    # réellement l'espace supplémentaire d'une carte plus grande.
    if depth == 9:
        return min(_target_radius(depth), params.clubhouse_max * 0.75)
    map_scale = min(rules.width, rules.height) / 350.0
    return _target_radius(depth) * params.target_radius_scale * map_scale


def _raw_transforms(template: BeanTemplate, state: SearchState,
                    clubhouse: tuple[float, float], params: SolverParams):
    rotations = range(0, 360, params.rotation_step_deg)
    mirrors = (False, True) if template.allow_mirror else (False,)
    if not state.placed:
        # Le tee 1 reste proche du clubhouse, mais libère son centre pour le retour.
        for radius in params.start_radii:
            for angle in params.departure_angles:
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
                    clubhouse: tuple[float, float], params: SolverParams,
                    rules: ValidationRules) -> float:
    trial = PlacedBean(template, transform, depth)
    radius = math.dist(trial.green, clubhouse)
    rank = abs(radius - _scaled_target_radius(depth, params, rules))
    # Les derniers trous privilégient franchement une direction de retour.
    if depth >= 7:
        rank += radius * (depth - 6) * 0.35
    return rank


def _transforms(template: BeanTemplate, state: SearchState,
                clubhouse: tuple[float, float], params: SolverParams, seed: int,
                rules: ValidationRules):
    depth = state.depth + 1
    transforms = list(_raw_transforms(template, state, clubhouse, params))
    rng = _rng_for(seed, state, f"transforms-{template.id}")
    rng.shuffle(transforms)  # départage déterministe des rangs égaux
    transforms.sort(key=lambda item: _transform_rank(template, item, depth, clubhouse, params, rules))
    limit = params.start_transforms_per_candidate if not state.placed else params.transforms_per_candidate
    return transforms[:limit]


def _state_score(placed: tuple[PlacedBean, ...], clubhouse: tuple[float, float],
                 params: SolverParams, rules: ValidationRules) -> float:
    depth = len(placed)
    points = [point for bean in placed for point in bean.footprint]
    min_x, max_x = min(p[0] for p in points), max(p[0] for p in points)
    min_y, max_y = min(p[1] for p in points), max(p[1] for p in points)
    bbox_area = (max_x - min_x) * (max_y - min_y)
    radius = math.dist(placed[-1].green, clubhouse)
    score = (abs(radius - _scaled_target_radius(depth, params, rules)) * 0.11
             + bbox_area * params.bbox_weight)

    # Diversité de caps globaux, sans forcer neuf directions toutes différentes.
    bins = []
    for bean in placed:
        dx, dy = bean.green[0] - bean.tee[0], bean.green[1] - bean.tee[1]
        bins.append(round(math.degrees(math.atan2(dy, dx)) / 30.0) % 12)
    score += (len(bins) - len(set(bins))) * 1.7

    # Évite de coller durablement les bordures : réserve utile aux trous suivants.
    edge_clearance = min(min_x, min_y, rules.width - max_x, rules.height - max_y)
    if edge_clearance < 16.0:
        score += (16.0 - edge_clearance) * 0.35
    score += FIRST_PAR_PENALTY[placed[0].template.par]

    if params.halfplane_weight > 0.0:
        score += sum(halfplane.front_penalty(bean, clubhouse, params.halfplane_theta_deg,
                                              params.halfplane_band, params.halfplane_weight)
                     for bean in placed)
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


def _has_closing_sequence(state: SearchState, bank: BeanBank, clubhouse: tuple[float, float],
                          params: SolverParams, rules: ValidationRules, seed: int,
                          obstacles: tuple[PlacedBean, ...] = (),
                          blocked_ids: frozenset[str] = frozenset(), order_offset: int = 0,
                          par_quota: dict[int, int] = PAR_QUOTAS, *,
                          steps_remaining: int = 1) -> bool:
    """Généralise l'ancien regard d'un coup (``steps_remaining=1``, voir
    ``_has_closing_move``) à plusieurs coups : cherche une séquence valide
    d'EXACTEMENT ``steps_remaining`` trous qui referme sur le clubhouse,
    retour vrai dès la première trouvée (pas la meilleure).

    Chaque pas, y compris les intermédiaires, passe par
    ``_placement_problems`` -> ``geometry.validate`` (même oracle que le
    reste du solveur, aucun raccourci parallèle). ``obstacles`` porte déjà
    les haricots de l'autre nine (même motif que ``course_solver.py``) : la
    fermeture reste consciente de l'occupation conjointe.

    Coût : le dernier pas (celui qui referme réellement, ``steps_remaining
    == 1``) utilise la largeur normale (``candidates_per_par`` /
    ``transforms_per_candidate``) — c'est exactement l'ancien comportement.
    Les pas intermédiaires utilisent une largeur réduite
    (``lookahead_candidates_per_par`` / ``lookahead_transforms_per_candidate``,
    1×4 par défaut) : une sonde de plausibilité bon marché (« un chemin
    existe-t-il », pas « quel est le meilleur »), pas une énumération
    exhaustive. Le pire cas est donc borné par
    (3 pars x largeur réduite) ^ (steps_remaining - 1) x
    (3 pars x largeur normale) au dernier pas, avec retour anticipé dès la
    première séquence valide trouvée.
    """
    target_depth = state.depth + 1
    final_step = steps_remaining <= 1
    cand_n, trans_n = ((params.candidates_per_par, params.transforms_per_candidate) if final_step
                       else (params.lookahead_candidates_per_par, params.lookahead_transforms_per_candidate))
    remaining = _remaining_dict(state.remaining)
    pars = [par for par in _par_order(par_quota) if remaining[par] > 0]
    for par in pars:
        for template in _candidate_templates(bank, state, par, params, seed, blocked_ids)[:cand_n]:
            for transform in _transforms(template, state, clubhouse, params, seed, rules)[:trans_n]:
                placed = PlacedBean(template, transform, order_offset + target_depth)
                if final_step and math.dist(placed.green, clubhouse) > params.clubhouse_max:
                    continue
                candidate = (*state.placed, placed)
                if _placement_problems(candidate, obstacles, rules):
                    continue
                if final_step:
                    return True
                child = SearchState(candidate, _consume(state.remaining, par), 0.0)
                if _has_closing_sequence(child, bank, clubhouse, params, rules, seed,
                                         obstacles, blocked_ids, order_offset, par_quota,
                                         steps_remaining=steps_remaining - 1):
                    return True
    return False


def _has_closing_move(state: SearchState, bank: BeanBank, clubhouse: tuple[float, float],
                      params: SolverParams, rules: ValidationRules, seed: int,
                      obstacles: tuple[PlacedBean, ...] = (),
                      blocked_ids: frozenset[str] = frozenset(), order_offset: int = 0,
                      par_quota: dict[int, int] = PAR_QUOTAS) -> bool:
    """Alias conservé pour compatibilité (tests, docs) : regard exact d'un
    coup, cas particulier de ``_has_closing_sequence`` à ``steps_remaining=1``
    — comportement et coût strictement inchangés."""
    return _has_closing_sequence(state, bank, clubhouse, params, rules, seed,
                                 obstacles, blocked_ids, order_offset, par_quota,
                                 steps_remaining=1)


def _placement_problems(candidate: tuple[PlacedBean, ...], obstacles: tuple[PlacedBean, ...],
                        rules: ValidationRules):
    problems = validate(candidate, rules)
    if obstacles:
        problems.extend(validate((*obstacles, *candidate), rules, check_links=False))
    return problems


@dataclass(frozen=True)
class ExpansionResult:
    """Sortie pure de ``expand_state`` : les enfants d'un seul parent."""
    children: tuple[SearchState, ...]
    trials: int
    accepted: int
    rejected: Counter


def expand_state(state: SearchState, target_depth: int, bank: BeanBank,
                 clubhouse: tuple[float, float], params: SolverParams,
                 rules: ValidationRules, seed: int, *,
                 obstacles: tuple[PlacedBean, ...] = (),
                 blocked_ids: frozenset[str] = frozenset(), order_offset: int = 0,
                 par_quota: dict[int, int] = PAR_QUOTAS) -> ExpansionResult:
    """Développe un seul état d'une profondeur : candidats, transformations,
    validation, score. Corps extrait de la boucle de ``solve_nine`` pour être
    réutilisé par le paveur conjoint (``joint_solver.py``), qui développe les
    deux nines côte à côte sur la même carte.

    ``obstacles`` et ``blocked_ids`` portent l'autre nine déjà posé (même
    motif que ``course_solver.py``). ``par_quota`` ne fait qu'ordonner les
    classes essayées en premier (l'éligibilité reste pilotée par
    ``state.remaining``) : un compteur partagé peut ainsi remplacer le
    module-level ``PAR_QUOTAS`` sans toucher à cette fonction.
    """
    children: list[SearchState] = []
    rejected: Counter = Counter()
    trials = accepted = 0
    remaining = _remaining_dict(state.remaining)
    pars = [par for par in _par_order(par_quota) if remaining[par] > 0]
    for par in pars:
        for template in _candidate_templates(bank, state, par, params, seed, blocked_ids):
            for transform in _transforms(template, state, clubhouse, params, seed, rules):
                trials += 1
                placed = PlacedBean(template, transform, order_offset + target_depth)
                candidate = (*state.placed, placed)
                if target_depth == 1 and not _starts_outward(placed, clubhouse):
                    rejected["clubhouse_departure"] += 1
                    continue
                problems = _placement_problems(candidate, obstacles, rules)
                if target_depth == 9 and math.dist(placed.green, clubhouse) > params.clubhouse_max:
                    rejected["clubhouse_return"] += 1
                    continue
                if problems:
                    for kind in {problem.kind for problem in problems}:
                        rejected[kind] += 1
                    continue
                remaining_after = _consume(state.remaining, par)
                child = SearchState(candidate, remaining_after,
                                    _state_score(candidate, clubhouse, params, rules))
                # Déclenche sur [closing_lookahead_from - 1, 8] : le défaut
                # (9) borne à {8}, exactement l'ancien comportement (regard
                # d'un coup uniquement à la profondeur 8).
                lookahead_start = max(1, min(8, params.closing_lookahead_from - 1))
                if params.closure_lookahead and lookahead_start <= target_depth <= 8:
                    steps_remaining = 9 - target_depth
                    closure = _has_closing_sequence(child, bank, clubhouse, params, rules, seed,
                                                    obstacles, blocked_ids, order_offset, par_quota,
                                                    steps_remaining=steps_remaining)
                    child = SearchState(candidate, remaining_after,
                                        child.score - 80.0 if closure else child.score + 80.0)
                children.append(child)
                accepted += 1
    return ExpansionResult(tuple(children), trials, accepted, rejected)


def solve_nine(seed: int, params: SolverParams | None = None,
               rules: ValidationRules | None = None, *, bank: BeanBank | None = None,
               obstacles: tuple[PlacedBean, ...] = (),
               blocked_ids: frozenset[str] = frozenset(), order_offset: int = 0,
               par_quota: dict[int, int] | None = None,
               require_full_quota: bool = True) -> SolveResult:
    """``require_full_quota`` (défaut ``True``, inchangé) : la complétude
    exige que ``remaining`` tombe exactement à ``(0, 0, 0)`` à la profondeur
    9 — vrai par construction dès que la somme du quota de départ est 9
    (``PAR_QUOTAS`` ou tout quota par-nine qui somme à 9), puisqu'aucune
    classe ne peut descendre sous 0 (``expand_state`` ne propose que les
    classes dont ``remaining[par] > 0``). Mettre ``False`` (voir
    ``course_solver.solve_course(free_quota=True)``) quand ``par_quota``
    porte le budget GLOBAL (18 trous, ex. ``4/10/4``) plutôt que le budget
    du seul nine : neuf trous n'épuisent alors jamais ce quota, donc exiger
    ``(0, 0, 0)`` serait toujours faux même pour un nine par ailleurs
    parfaitement valide."""
    params = params or SolverParams()
    rules = rules or ValidationRules()
    clubhouse = (rules.width / 2.0, rules.height / 2.0)
    bank = bank or generate_bank(seed)
    quota = dict(par_quota) if par_quota is not None else dict(PAR_QUOTAS)
    beam = [SearchState((), (quota[3], quota[4], quota[5]), 0.0)]
    diagnostics: list[DepthDiagnostics] = []
    best = beam[0]

    for target_depth in range(1, 10):
        next_states: list[SearchState] = []
        rejected: Counter = Counter()
        trials = accepted = dead_ends = 0
        parent_count = len(beam)
        for state in beam:
            result = expand_state(state, target_depth, bank, clubhouse, params, rules, seed,
                                  obstacles=obstacles, blocked_ids=blocked_ids,
                                  order_offset=order_offset, par_quota=quota)
            trials += result.trials
            accepted += result.accepted
            rejected.update(result.rejected)
            next_states.extend(result.children)
            if result.accepted == 0:
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

    quota_ok = best.remaining == (0, 0, 0) if require_full_quota else True
    complete = best.depth == 9 and quota_ok \
        and math.dist(best.placed[-1].green, clubhouse) <= params.clubhouse_max
    return SolveResult(seed, clubhouse, best, complete, tuple(diagnostics), params)
