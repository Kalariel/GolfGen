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
    # Quota borné par nine (EXPERIMENT_18_CLOSURE.md, opt-in, défaut ``False``
    # -> comportement byte-identique). Quand activé (``bounded_quota=True``),
    # ``expand_state`` applique ``_bounded_quota_filter`` : chaque nine doit
    # finir avec un compte de par3 et de par5 dans ces bornes ; le par4
    # complète librement jusqu'à 9. Les bornes sont des paramètres, pas des
    # constantes câblées.
    bounded_quota: bool = False
    par3_bounds: tuple[int, int] = (1, 3)
    par5_bounds: tuple[int, int] = (1, 3)
    # Diversité stratifiée des départs du tee 10 par groupe de rayon
    # (PLAN.md, décision utilisateur, étape suivant ``back_start_radii``
    # étendus) : opt-in, défaut ``()`` -> comportement byte-identique (tout
    # le code existant qui ne passe pas ce paramètre n'est pas affecté).
    # Diagnostic ayant motivé ce paramètre (``experiments/bean_paving/
    # output/benchmark_course18_400_backfar_1_10/REPORT.md``) : à la
    # profondeur 1, ``_transform_rank`` classe les rayons étendus (64/80/96)
    # plus près de la cible d'expansion que les rayons historiques (44/48),
    # qui se retrouvent minoritaires AVANT la coupe de troncature par
    # candidat (``start_transforms_per_candidate``) et avant la sélection du
    # beam -- sur certaines seeds (4, 8) la seule trajectoire gagnante
    # partait justement d'un rayon historique. Chaque groupe (ex. ``((44.0,
    # 48.0), (64.0,), (80.0,), (96.0,))``) reçoit une part égale à CES DEUX
    # endroits (``_stratified_truncate``, ``_select_beam_stratified`` à la
    # profondeur 1) ; le reliquat (division non entière, groupe sous-peuplé)
    # est comblé par rang global, jamais perdu.
    start_radius_groups: tuple[tuple[float, ...], ...] = ()
    # Garde-fou LÉGER (pas une répartition stricte) à la profondeur 2 :
    # réserve au moins ``start_radius_depth2_min_survivors`` places par
    # groupe (même lignage que la profondeur 1, ``placed[0]``) avant de
    # combler le reliquat par rang global -- motivé par un diagnostic
    # chiffré (script jetable, voir le rapport) montrant que la diversité de
    # la profondeur 1 s'effondre quasi totalement dès la profondeur 2 sans
    # cette garde (ex. seed 4 : groupe {44,48} passe de 47/72 à 4/72 une
    # profondeur plus tard). Défaut ``0`` -> désactivé, comportement
    # byte-identique ; sans effet si ``start_radius_groups`` est vide.
    start_radius_depth2_min_survivors: int = 0
    # Départs aléatoires du tee de profondeur 1 (opt-in, décision utilisateur
    # PLAN.md ligne 6, expérience "départs aléatoires") : remplace la grille
    # fixe (``departure_angles`` x ``start_radii``) de ``_raw_transforms`` par
    # des positions tirées, angle uniforme sur tout le cercle ``[0, 360)`` et
    # rayon uniforme dans ``random_departure_radius`` -- ``departure_angles``
    # et ``start_radii`` sont alors ignorés pour le tirage des positions
    # (mais restent lus ailleurs, ex. valeur par défaut d'autres chemins).
    # Tirage déterministe par ``(seed, nine)`` via ``_rng_for`` (profondeur 1
    # -> ``state.placed`` vide, donc seule la paire (seed, salt) détermine le
    # tirage -- le ``seed`` du back diffère déjà du front, voir
    # ``course_solver.solve_course``). Défaut ``False`` -> comportement
    # byte-identique (grille fixe, comme avant ce paramètre).
    random_departures: bool = False
    # Nombre de positions de départ tirées à la profondeur 1 quand
    # ``random_departures`` est actif -- fixé par l'appelant pour garder un
    # coût comparable à la grille qu'il remplace (ex. 10 = 2 rayons x 5
    # angles pour le front par défaut, 60 = 5 rayons x 12 angles pour le
    # back étendu). Ignoré si ``random_departures`` est faux.
    random_departure_count: int = 0
    # Intervalle ``(r_min, r_max)`` du rayon de départ tiré uniformément
    # quand ``random_departures`` est actif. Ignoré sinon.
    random_departure_radius: tuple[float, float] = (0.0, 0.0)
    # Cible de score EXPLICITE pour la profondeur 9 (opt-in, décision
    # utilisateur PLAN.md ligne 6, expérience "disque 25 équitable") :
    # remplace la formule ``max(cible actuelle, rules.clubhouse_block_radius
    # + 15)`` de ``_scaled_target_radius`` par une valeur posée directement
    # par l'appelant -- utile quand la marge fixe de 15 blocs au-dessus du
    # disque ne suffit pas (ex. ``clubhouse_block_radius=25`` -> 40, trop
    # proche de la frontière réelle de l'anneau jouable). ``None`` (défaut)
    # retombe sur le comportement historique (formule ``+15`` si
    # ``rules.clubhouse_block_radius`` est renseigné, sinon la cible
    # d'origine) -- comportement byte-identique.
    target_radius_depth9_min: float | None = None


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
    # Fermeture anticipée (EXPERIMENT_18_CLOSURE.md) : combien de fois
    # ``_has_closing_sequence`` a été appelée à cette profondeur, et combien
    # de fois elle a renvoyé ``False`` (pénalité +80, le candidat est
    # défavorisé pour la sélection du beam -- une "coupe" souple, pas un
    # retrait dur). Toujours (0, 0) quand ``closure_lookahead`` ne se
    # déclenche pas à cette profondeur (comportement historique inchangé).
    lookahead_calls: int = 0
    lookahead_pruned: int = 0


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
                "bounded_quota": self.params.bounded_quota,
                "par3_bounds": list(self.params.par3_bounds),
                "par5_bounds": list(self.params.par5_bounds),
                "halfplane_weight": self.params.halfplane_weight,
                "halfplane_theta_deg": self.params.halfplane_theta_deg,
                "halfplane_band": self.params.halfplane_band,
                "start_radius_groups": [list(group) for group in self.params.start_radius_groups],
                "start_radius_depth2_min_survivors": self.params.start_radius_depth2_min_survivors,
                "random_departures": self.params.random_departures,
                "random_departure_count": self.params.random_departure_count,
                "random_departure_radius": list(self.params.random_departure_radius),
                "target_radius_depth9_min": self.params.target_radius_depth9_min,
            },
            "diagnostics": [{
                "depth": item.depth,
                "parents": item.parents,
                "trials": item.trials,
                "accepted": item.accepted,
                "kept": item.kept,
                "dead_ends": item.dead_ends,
                "rejection_counts": dict(sorted(item.rejection_counts.items())),
                "lookahead_calls": item.lookahead_calls,
                "lookahead_pruned": item.lookahead_pruned,
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


def _bounded_quota_filter(pars: list[int], state: SearchState, depth: int,
                          params: SolverParams,
                          global_quota: dict[int, int] | None) -> list[int]:
    """Filtre additionnel pour le mode quota borné par nine (opt-in,
    ``params.bounded_quota``, EXPERIMENT_18_CLOSURE.md). ``pars`` est déjà
    restreint aux classes dont la capacité haute (``state.remaining``) n'est
    pas épuisée.

    1. Forçage : si une classe bornée (par3/par5) ne peut plus atteindre son
       minimum ``lo`` avec les emplacements restants (CE coup inclus), elle
       devient la SEULE classe éligible -- sinon ce nine pourrait finir avec
       un compte sous le minimum (ex. 0 par3) sans jamais violer la règle 2,
       qui ne protège que l'AUTRE nine.
    2. Plafond solidaire : une classe bornée n'est éligible que si, après
       l'avoir prise, le quota global restant (``global_quota`` moins ce que
       CE nine a RÉELLEMENT posé, jamais un compteur périmé) laisse encore à
       l'autre nine au moins son propre minimum ``lo``.
    """
    bounds = {3: params.par3_bounds, 5: params.par5_bounds}
    counts = Counter(bean.template.par for bean in state.placed)
    slots_from_now = 10 - depth  # emplacements restants, CE coup inclus

    # Forçage sur le besoin TOTAL (somme des deux classes bornées), pas
    # classe par classe isolément : sinon deux besoins qui deviennent
    # tendus au même moment (ex. profondeur 8, 2 emplacements restants, 1
    # par3 ET 1 par5 encore nécessaires) ne seraient forcés qu'à la toute
    # dernière profondeur, trop tard pour satisfaire les deux à la fois.
    needs = {par: max(0, lo - counts[par]) for par, (lo, _hi) in bounds.items()}
    if sum(needs.values()) >= slots_from_now:
        forced = [par for par, need in needs.items() if need > 0]
        return [par for par in pars if par in forced]

    eligible = []
    for par in pars:
        if par in bounds:
            lo, hi = bounds[par]
            if counts[par] + 1 > hi:
                continue
            if global_quota is not None and global_quota[par] - (counts[par] + 1) < lo:
                continue
        eligible.append(par)
    return eligible


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
        target = min(_target_radius(depth), params.clubhouse_max * 0.75)
        # Disque d'exclusion clubhouse total (opt-in, ``rules.clubhouse_block_radius``
        # -- décision utilisateur PLAN.md ligne 6, expérience "disque 25") :
        # la cible de score du dernier trou doit rester nettement hors du
        # disque (marge de 15 blocs), sinon le score pousserait le retour
        # DANS une zone que ``geometry.validate`` rejette de toute façon --
        # ``None`` (défaut) ne change rien.
        if params.target_radius_depth9_min is not None:
            # Cible explicite (opt-in) : prend le pas sur la formule
            # ``+15`` ci-dessous -- voir la docstring du paramètre.
            target = max(target, params.target_radius_depth9_min)
        elif rules.clubhouse_block_radius is not None:
            target = max(target, rules.clubhouse_block_radius + 15.0)
        return target
    map_scale = min(rules.width, rules.height) / 350.0
    return _target_radius(depth) * params.target_radius_scale * map_scale


def _raw_transforms(template: BeanTemplate, state: SearchState,
                    clubhouse: tuple[float, float], params: SolverParams, seed: int = 0):
    rotations = range(0, 360, params.rotation_step_deg)
    mirrors = (False, True) if template.allow_mirror else (False,)
    if not state.placed:
        if params.random_departures:
            # Positions tirées (opt-in, ``SolverParams.random_departures``) :
            # angle uniforme sur tout le cercle, rayon uniforme dans
            # ``random_departure_radius``, tirage déterministe par
            # ``(seed, nine)`` -- ``state.placed`` est vide à cette
            # profondeur, donc ``_rng_for`` ne dépend que de ``seed`` et du
            # sel ci-dessous (pas d'un lignage déjà posé).
            rng = _rng_for(seed, state, "random-departures")
            r_min, r_max = params.random_departure_radius
            tees = []
            for _ in range(params.random_departure_count):
                angle = rng.uniform(0.0, 360.0)
                radius = rng.uniform(r_min, r_max)
                rad = math.radians(angle)
                tees.append((clubhouse[0] + radius * math.cos(rad),
                            clubhouse[1] + radius * math.sin(rad)))
        else:
            # Le tee 1 reste proche du clubhouse, mais libère son centre pour le retour.
            tees = []
            for radius in params.start_radii:
                for angle in params.departure_angles:
                    rad = math.radians(angle)
                    tees.append((clubhouse[0] + radius * math.cos(rad),
                                clubhouse[1] + radius * math.sin(rad)))
        for tee in tees:
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


def _radius_group_index(radius: float, groups: tuple[tuple[float, ...], ...]) -> int:
    """Groupe le plus proche de ``radius`` parmi ``groups`` (tolérance au
    bruit flottant du aller-retour polaire -> cartésien -> distance, jamais
    une égalité exacte garantie) -- toujours un résultat, même si ``radius``
    ne correspond à AUCUNE valeur de ``groups`` (plus proche par défaut)."""
    return min(range(len(groups)),
               key=lambda idx: min(abs(radius - value) for value in groups[idx]))


def _stratified_truncate(transforms: list[Transform], limit: int,
                         groups: tuple[tuple[float, ...], ...],
                         clubhouse: tuple[float, float]) -> list[Transform]:
    """Troncature (a) de ``_transforms`` à la profondeur 1 : répartit
    ``limit`` en part égale par groupe de rayon de départ (``groups``) au
    lieu de garder bêtement les ``limit`` premiers du tri global (qui
    favorise structurellement les rayons les plus proches de la cible
    d'expansion, cf. ``SolverParams.start_radius_groups``). ``transforms``
    est déjà trié par ``_transform_rank`` : l'ordre relatif à l'intérieur
    de chaque groupe est préservé. Le reliquat (part non entière, groupe
    sous-peuplé) est comblé par rang global, jamais perdu -- la taille du
    résultat ne dépasse jamais ``limit`` et n'est inférieure que si
    ``transforms`` lui-même en a moins."""
    share = max(1, limit // len(groups))
    grouped: list[list[Transform]] = [[] for _ in groups]
    for transform in transforms:
        radius = math.dist((transform.x, transform.y), clubhouse)
        grouped[_radius_group_index(radius, groups)].append(transform)

    selected: list[Transform] = []
    taken: set[int] = set()
    for bucket in grouped:
        for transform in bucket[:share]:
            selected.append(transform)
            taken.add(id(transform))
    if len(selected) < limit:
        for transform in transforms:
            if len(selected) >= limit:
                break
            if id(transform) in taken:
                continue
            selected.append(transform)
            taken.add(id(transform))
    return selected[:limit]


def _transforms(template: BeanTemplate, state: SearchState,
                clubhouse: tuple[float, float], params: SolverParams, seed: int,
                rules: ValidationRules):
    depth = state.depth + 1
    transforms = list(_raw_transforms(template, state, clubhouse, params, seed))
    rng = _rng_for(seed, state, f"transforms-{template.id}")
    rng.shuffle(transforms)  # départage déterministe des rangs égaux
    transforms.sort(key=lambda item: _transform_rank(template, item, depth, clubhouse, params, rules))
    if not state.placed:
        limit = params.start_transforms_per_candidate
        if params.start_radius_groups:
            return _stratified_truncate(transforms, limit, params.start_radius_groups, clubhouse)
        return transforms[:limit]
    return transforms[:params.transforms_per_candidate]


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


def _lineage_start_radius(state: SearchState, clubhouse: tuple[float, float]) -> float:
    """Rayon de départ (profondeur 1) du lignage de ``state`` -- le premier
    haricot posé ne change plus une fois le tee 10 choisi, donc ce rayon
    reste valable à n'importe quelle profondeur ultérieure."""
    first = state.placed[0].transform
    return math.dist((first.x, first.y), clubhouse)


def _select_beam_stratified(states: Iterable[SearchState], width: int, share: int,
                            groups: tuple[tuple[float, ...], ...],
                            clubhouse: tuple[float, float]) -> list[SearchState]:
    """Sélection du beam (b), stratifiée par groupe de rayon de départ
    (lignage, ``_lineage_start_radius``) : chaque groupe reçoit AU MOINS
    ``share`` places (sélectionnées via ``_select_beam`` à l'intérieur du
    groupe, donc la diversité de quotas par3/5 existante est préservée à
    l'intérieur de chaque groupe), le reliquat (``width - sum(shares)``, ou
    un groupe sous-peuplé) est comblé par rang global parmi les états
    restants -- jamais perdu, jamais plus de ``width`` au total. Utilisée à
    la profondeur 1 (``share = width // len(groups)``, répartition stricte,
    ``SolverParams.start_radius_groups``) et, en option, à la profondeur 2
    (``share`` plus petit, garde-fou léger,
    ``SolverParams.start_radius_depth2_min_survivors`` -- voir le
    diagnostic chiffré dans le rapport motivant ce second point
    d'intervention)."""
    grouped: list[list[SearchState]] = [[] for _ in groups]
    for state in states:
        grouped[_radius_group_index(_lineage_start_radius(state, clubhouse), groups)].append(state)

    selected: list[SearchState] = []
    selected_keys: set[tuple] = set()
    for bucket in grouped:
        for state in _select_beam(bucket, share):
            key = _state_key(state)
            if key in selected_keys:
                continue
            selected_keys.add(key)
            selected.append(state)
            if len(selected) == width:
                return selected

    if len(selected) < width:
        remaining_pool = [state for state in states if _state_key(state) not in selected_keys]
        for state in _select_beam(remaining_pool, width - len(selected)):
            key = _state_key(state)
            if key in selected_keys:
                continue
            selected_keys.add(key)
            selected.append(state)
    return selected[:width]


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
    lookahead_calls: int = 0
    lookahead_pruned: int = 0


def expand_state(state: SearchState, target_depth: int, bank: BeanBank,
                 clubhouse: tuple[float, float], params: SolverParams,
                 rules: ValidationRules, seed: int, *,
                 obstacles: tuple[PlacedBean, ...] = (),
                 blocked_ids: frozenset[str] = frozenset(), order_offset: int = 0,
                 par_quota: dict[int, int] = PAR_QUOTAS,
                 global_quota: dict[int, int] | None = None) -> ExpansionResult:
    """Développe un seul état d'une profondeur : candidats, transformations,
    validation, score. Corps extrait de la boucle de ``solve_nine`` pour être
    réutilisé par le paveur conjoint (``joint_solver.py``), qui développe les
    deux nines côte à côte sur la même carte.

    ``obstacles`` et ``blocked_ids`` portent l'autre nine déjà posé (même
    motif que ``course_solver.py``). ``par_quota`` ne fait qu'ordonner les
    classes essayées en premier (l'éligibilité reste pilotée par
    ``state.remaining``) : un compteur partagé peut ainsi remplacer le
    module-level ``PAR_QUOTAS`` sans toucher à cette fonction.

    ``global_quota`` : budget global fixe (ex. ``joint_solver.GLOBAL_PAR_QUOTA``)
    utilisé UNIQUEMENT par ``_bounded_quota_filter`` quand
    ``params.bounded_quota`` est vrai (EXPERIMENT_18_CLOSURE.md) ; ``None``
    (défaut) ne change rien.
    """
    children: list[SearchState] = []
    rejected: Counter = Counter()
    trials = accepted = 0
    lookahead_calls = lookahead_pruned = 0
    remaining = _remaining_dict(state.remaining)
    pars = [par for par in _par_order(par_quota) if remaining[par] > 0]
    if params.bounded_quota:
        pars = _bounded_quota_filter(pars, state, target_depth, params, global_quota)
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
                    lookahead_calls += 1
                    if not closure:
                        lookahead_pruned += 1
                    child = SearchState(candidate, remaining_after,
                                        child.score - 80.0 if closure else child.score + 80.0)
                children.append(child)
                accepted += 1
    return ExpansionResult(tuple(children), trials, accepted, rejected, lookahead_calls, lookahead_pruned)


def solve_nine(seed: int, params: SolverParams | None = None,
               rules: ValidationRules | None = None, *, bank: BeanBank | None = None,
               obstacles: tuple[PlacedBean, ...] = (),
               blocked_ids: frozenset[str] = frozenset(), order_offset: int = 0,
               par_quota: dict[int, int] | None = None,
               require_full_quota: bool = True,
               global_quota: dict[int, int] | None = None) -> SolveResult:
    """``global_quota`` : transmis tel quel à ``expand_state`` (voir sa
    docstring) ; sans effet si ``params.bounded_quota`` est faux (défaut).

    ``require_full_quota`` (défaut ``True``, inchangé) : la complétude
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
        lookahead_calls = lookahead_pruned = 0
        parent_count = len(beam)
        for state in beam:
            result = expand_state(state, target_depth, bank, clubhouse, params, rules, seed,
                                  obstacles=obstacles, blocked_ids=blocked_ids,
                                  order_offset=order_offset, par_quota=quota,
                                  global_quota=global_quota)
            trials += result.trials
            accepted += result.accepted
            rejected.update(result.rejected)
            next_states.extend(result.children)
            lookahead_calls += result.lookahead_calls
            lookahead_pruned += result.lookahead_pruned
            if result.accepted == 0:
                dead_ends += 1

        if not next_states:
            diagnostics.append(DepthDiagnostics(target_depth, parent_count, trials, accepted, 0,
                                                dead_ends, dict(rejected), lookahead_calls, lookahead_pruned))
            break
        if params.start_radius_groups and target_depth == 1:
            # (b) sélection stratifiée du beam à la profondeur 1 -- part
            # égale par groupe, reliquat par rang global (voir
            # ``_select_beam_stratified`` et ``SolverParams.start_radius_groups``).
            share = max(1, params.beam_width // len(params.start_radius_groups))
            beam = _select_beam_stratified(next_states, params.beam_width, share,
                                           params.start_radius_groups, clubhouse)
        elif (params.start_radius_groups and target_depth == 2
              and params.start_radius_depth2_min_survivors > 0):
            # Garde-fou léger à la profondeur 2 (voir
            # ``SolverParams.start_radius_depth2_min_survivors`` -- motivé
            # par un diagnostic chiffré montrant l'effondrement de la
            # diversité de la profondeur 1 une profondeur plus tard).
            beam = _select_beam_stratified(next_states, params.beam_width,
                                           params.start_radius_depth2_min_survivors,
                                           params.start_radius_groups, clubhouse)
        else:
            beam = _select_beam(next_states, params.beam_width)
        best = beam[0]
        diagnostics.append(DepthDiagnostics(target_depth, parent_count, trials, accepted, len(beam),
                                            dead_ends, dict(rejected), lookahead_calls, lookahead_pruned))
        if target_depth == 9:
            break

    quota_ok = best.remaining == (0, 0, 0) if require_full_quota else True
    complete = best.depth == 9 and quota_ok \
        and math.dist(best.placed[-1].green, clubhouse) <= params.clubhouse_max
    return SolveResult(seed, clubhouse, best, complete, tuple(diagnostics), params)
