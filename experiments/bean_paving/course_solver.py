"""Coordination de deux recherches de nine sur une même carte 350x350."""

from __future__ import annotations

from dataclasses import dataclass, replace
import json
import math

from collections import Counter

from experiments.bean_paving import halfplane
from experiments.bean_paving.bean_bank import GenerationParams, generate_bank
from experiments.bean_paving.geometry import PlacedBean, ValidationRules, validate
from experiments.bean_paving.joint_solver import GLOBAL_PAR_QUOTA, JointSolveResult, search_joint
from experiments.bean_paving.solver import PAR_QUOTAS, SolveResult, SolverParams, _arrives_radially, solve_nine


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


_UNSET = object()


def _course_violations(front: tuple[PlacedBean, ...], back: tuple[PlacedBean, ...],
                       rules: ValidationRules, clubhouse: tuple[float, float],
                       front_clubhouse_max: float,
                       back_clubhouse_max: float | None = None, *,
                       arrival_max_angle_deg: float | None = None,
                       par3_bounds: tuple[int, int] | None = None,
                       par5_bounds: tuple[int, int] | None = None,
                       par5_deadline: int | None = None,
                       back_par3_bounds: tuple[int, int] | None = _UNSET,
                       back_par5_bounds: tuple[int, int] | None = _UNSET,
                       back_par5_deadline: int | None = _UNSET,
                       reserved_corridors: tuple[tuple[tuple[float, float], tuple[float, float], int], ...]
                       = ()) -> list[str]:
    """``back_clubhouse_max`` (défaut ``None``) : plafond dur départ/retour du
    BACK si différent de celui du front (décision utilisateur, tee 10 /
    green 18 autorisés plus loin -- voir ``solve_course(back_clubhouse_max=
    ...)``). ``None`` retombe sur ``front_clubhouse_max`` pour les deux
    nines : tout appelant existant qui ne précise qu'un seul argument
    positionnel garde un comportement strictement inchangé.

    ``arrival_max_angle_deg`` (opt-in, décision utilisateur PLAN.md ligne 6,
    expérience « arrivée radiale ») : vérifie indépendamment, pour chaque
    nine non vide, que son trou de clôture (dernier élément) arrive sur le
    clubhouse à moins de cet angle (``solver._arrives_radially``, mirroir de
    ``solver._starts_outward``) -- ``None`` (défaut) désactive la
    vérification, comportement byte-identique.

    ``par3_bounds`` / ``par5_bounds`` (opt-in, défaut ``None`` ->
    vérification désactivée, byte-identique) : vérifie indépendamment, pour
    chaque nine non vide, que son propre compte de par3/par5 tombe dans ces
    bornes (``solver.SolverParams.par3_bounds``/``par5_bounds``, mode
    ``bounded_quota``) -- distinct de ``par_quotas`` ci-dessous, qui ne
    porte que sur le total GLOBAL des 18 trous.

    ``par5_deadline`` (opt-in, défaut ``None`` -> vérification désactivée,
    byte-identique) : vérifie indépendamment, pour chaque nine non vide, que
    son ``par5_bounds[0]``-ième par5 (ordre de jeu, 1-indexé ; ``par5_bounds``
    non fourni -> ``1``, même défaut que ``solver.SolverParams.par5_bounds``)
    tombe au plus tard au trou ``par5_deadline`` -- mirroir indépendant du
    forçage de ``solver._bounded_quota_filter``. Quand ``par5_bounds`` est
    ``(n, n)`` (borne basse = borne haute), ce point est aussi le DERNIER
    par5 du nine (il y en a exactement ``n``), donc la vérification couvre
    alors TOUS les par5 du nine, pas seulement le premier requis.

    ``back_par3_bounds`` / ``back_par5_bounds`` / ``back_par5_deadline``
    (opt-in, défaut sentinelle ``_UNSET`` -> retombe sur ``par3_bounds`` /
    ``par5_bounds`` / ``par5_deadline`` ci-dessus pour le BACK AUSSI, donc
    byte-identique pour tout appelant existant qui ne précise que les
    paramètres partagés) : BUG DE LECTURE corrigé ici (revue de code,
    2026-10-06, EXP A'' invalidée -- seeds 2/3 placées 18/18 mais rejetées
    sur ``back_par5_deadline``) -- avant ce correctif, le BACK était
    TOUJOURS contrôlé avec les bornes/deadline du FRONT (``par3_bounds``/
    ``par5_bounds``/``par5_deadline`` ci-dessus), jamais les siennes propres,
    alors que ``solver._bounded_quota_filter`` (le mécanisme qui les force
    RÉELLEMENT pendant la recherche) lit bien ``back_params.par3_bounds``/
    ``par5_bounds``/``par5_deadline`` quand ``back_params.bounded_quota`` est
    vrai (``bounded_quota_back=True``, voir ``solve_course`` docstring) :
    front et back peuvent légitimement avoir des bornes/deadline DIFFÉRENTES
    (ex. EXP A'' : deadline posée sur le front seul, ``back_params.
    par5_deadline=None``) et la validation doit refléter CE QUE CHAQUE NINE
    A RÉELLEMENT REÇU, pas celui de l'autre. Passer explicitement ``None``
    (plutôt que de laisser la sentinelle) désactive la vérification
    correspondante pour le BACK SEUL, indépendamment du FRONT -- c'est ce que
    fait ``solve_course`` ci-dessous.

    ``reserved_corridors`` (opt-in, défaut ``()`` -> comportement
    byte-identique, décision utilisateur PLAN.md ligne 6, expérience C1
    « couloirs de départ réservés ») : couloirs STATIQUES supplémentaires
    (``(point_a, point_b, owner_order)``, voir ``geometry.ValidationRules.
    reserved_corridors``) vérifiés ici en plus de ceux déjà portés par
    ``rules`` -- utile pour la validation indépendante d'une config C1, où
    les deux couloirs (clubhouse->tee1, clubhouse->tee10) sont déjà
    entièrement connus une fois les deux nines complets.

    Note sur les configs A et A' (``run_exp_par5deadline_and_radialarrival.py``,
    ``run_exp_par5_two_per_nine.py``) : correctif sans effet observable chez
    elles. En A, ``solve_course(par5_deadline=7)`` pose la MÊME deadline sur
    ``front_params`` ET ``back_params`` (symétrique, voir docstring de
    ``solve_course``) et ``par3_bounds``/``par5_bounds`` ne sont jamais
    surchargés séparément par nine -- back et front partagent donc déjà les
    mêmes valeurs AVANT ce correctif, qui ne fait que les lire à la bonne
    source. En A', ``par5_bounds=(2, 2)`` et ``par5_deadline=7`` sont posés
    identiquement sur ``front_params`` ET ``back_params`` par l'appelant
    (``run_exp_par5_two_per_nine.py``) -- même raison. Seule EXP A''
    (``front_params.par5_deadline=7``, ``back_params.par5_deadline=None``,
    valeurs désormais ASYMÉTRIQUES) révèle la différence."""
    back_max = front_clubhouse_max if back_clubhouse_max is None else back_clubhouse_max
    if back_par3_bounds is _UNSET:
        back_par3_bounds = par3_bounds
    if back_par5_bounds is _UNSET:
        back_par5_bounds = par5_bounds
    if back_par5_deadline is _UNSET:
        back_par5_deadline = par5_deadline
    if reserved_corridors:
        rules = replace(rules, reserved_corridors=tuple(rules.reserved_corridors) + tuple(reserved_corridors))
    violations = [problem.kind for problem in validate((*front, *back), rules, check_links=False)]
    violations.extend(problem.kind for problem in validate(front, rules))
    violations.extend(problem.kind for problem in validate(back, rules))
    if len({bean.id for bean in (*front, *back)}) != len(front) + len(back):
        violations.append("duplicate_template")
    nine_specs = (
        ("front", front, front_clubhouse_max, par3_bounds, par5_bounds, par5_deadline),
        ("back", back, back_max, back_par3_bounds, back_par5_bounds, back_par5_deadline),
    )
    for label, nine, clubhouse_max, nine_par3_bounds, nine_par5_bounds, nine_par5_deadline in nine_specs:
        if not nine:
            violations.append(f"{label}_empty")
            continue
        if math.dist(nine[0].tee, clubhouse) > clubhouse_max:
            violations.append(f"{label}_start")
        if math.dist(nine[-1].green, clubhouse) > clubhouse_max:
            violations.append(f"{label}_return")
        if (arrival_max_angle_deg is not None
                and not _arrives_radially(nine[-1], clubhouse, arrival_max_angle_deg)):
            violations.append(f"{label}_radial_arrival")
        if nine_par3_bounds is not None or nine_par5_bounds is not None:
            counts = Counter(bean.template.par for bean in nine)
            lo3, hi3 = nine_par3_bounds or (0, 9)
            lo5, hi5 = nine_par5_bounds or (0, 9)
            if not (lo3 <= counts.get(3, 0) <= hi3):
                violations.append(f"{label}_par3_bounds")
            if not (lo5 <= counts.get(5, 0) <= hi5):
                violations.append(f"{label}_par5_bounds")
        if nine_par5_deadline is not None:
            lo5 = (nine_par5_bounds or (1, 9))[0]
            par5_positions = [i + 1 for i, bean in enumerate(nine) if bean.template.par == 5]
            if len(par5_positions) >= lo5 and par5_positions[lo5 - 1] > nine_par5_deadline:
                violations.append(f"{label}_par5_deadline")
    if front and back:
        if math.dist(front[0].tee, back[0].tee) < 18.0:
            violations.append("starts_not_distinct")
        if math.dist(front[-1].green, back[-1].green) < 18.0:
            violations.append("returns_not_distinct")
    pars = [bean.template.par for bean in (*front, *back)]
    if len(pars) == 18 and {par: pars.count(par) for par in (3, 4, 5)} != {3: 4, 4: 10, 5: 4}:
        violations.append("par_quotas")
    return violations


def _global_remaining_from_front(front_placed: tuple[PlacedBean, ...]) -> dict[int, int]:
    """Quota global restant pour le back, recalculé depuis les haricots
    RÉELLEMENT posés par le front (jamais un ``.remaining`` stocké —
    périmé dès que le front a consommé le quota dans un ordre quelconque,
    même bug que documenté dans ``joint_solver._has_closing_moves``)."""
    used = Counter(bean.template.par for bean in front_placed)
    return {par: GLOBAL_PAR_QUOTA[par] - used[par] for par in (3, 4, 5)}


def _bounded_front_quota(params: SolverParams) -> dict[int, int]:
    """Capacité haute de départ du front en mode quota borné
    (EXPERIMENT_18_CLOSURE.md) : les bornes de ``params.par3_bounds`` /
    ``par5_bounds`` plafonnent par3/par5, le par4 complète librement
    jusqu'à 9 (aucun plafond propre autre que les 9 trous du nine)."""
    return {3: params.par3_bounds[1], 4: 9, 5: params.par5_bounds[1]}


def solve_course(seed: int, front_params: SolverParams | None = None,
                 back_params: SolverParams | None = None,
                 rules: ValidationRules | None = None, *,
                 halfplane_weight: float | None = None,
                 halfplane_theta_deg: float | None = None,
                 halfplane_band: float | None = None,
                 free_quota: bool = False,
                 bounded_quota: bool = False,
                 bounded_quota_back: bool = False,
                 back_closing_lookahead_from: int | None = None,
                 back_clubhouse_max: float | None = None,
                 back_start_radii: tuple[float, ...] | None = None,
                 back_start_radius_groups: tuple[tuple[float, ...], ...] | None = None,
                 back_start_radius_depth2_min_survivors: int | None = None,
                 par5_deadline: int | None = None,
                 arrival_max_angle_deg: float | None = None) -> CourseSolveResult:
    """``halfplane_*`` : surcharge le biais souple de demi-plan
    (``halfplane.py``, EXPERIMENT_18_HALFPLANE.md) côté front uniquement, sans
    toucher au reste de ``front_params`` — ``None`` (défaut) ne change rien,
    comportement identique à avant ce paramètre. Le back reste libre
    (``back_params`` n'est jamais modifié ici).

    ``free_quota`` (défaut ``False``, inchangé, EXPERIMENT_18_CLOSURE.md) :
    seul le quota GLOBAL 18 trous (``4/10/4``) est imposé. Le front pioche
    librement dans ce budget (son propre quota par-nine ``2/5/2`` n'est plus
    vérifié) ; le back reçoit exactement ce qu'il reste, recalculé depuis les
    haricots RÉELLEMENT posés par le front (``_global_remaining_from_front``,
    jamais un compteur périmé). La banque ``8/20/8`` (36 candidats) offre
    toujours au moins ``GLOBAL_PAR_QUOTA[par]`` candidats par classe — plus
    que ce que front+back peuvent consommer ensemble (``GLOBAL_PAR_QUOTA``
    lui-même) — donc le back garde toujours au moins un candidat inutilisé
    disponible par classe qu'il lui reste à poser.

    ``bounded_quota`` (défaut ``False``, inchangé, incompatible avec
    ``free_quota`` — EXPERIMENT_18_CLOSURE.md) : chaque nine doit finir avec
    un compte de par3 et de par5 dans ``front_params.par3_bounds`` /
    ``par5_bounds`` (``[1, 3]`` par défaut), le par4 complétant librement
    jusqu'à 9 ; le total global reste exactement ``4/10/4``. Le front
    (``solver._bounded_quota_filter``, activé via
    ``SolverParams.bounded_quota``) n'a le droit de prendre une classe
    bornée que si le quota global restant APRÈS (recalculé depuis les
    haricots réellement posés, jamais un compteur périmé) laisse encore au
    back au moins son propre minimum ; le back reçoit ensuite exactement ce
    qui reste (même mécanisme que ``free_quota``, via
    ``_global_remaining_from_front``), ce qui tombe toujours dans ses
    propres bornes puisque ``GLOBAL_PAR_QUOTA[3] == GLOBAL_PAR_QUOTA[5] ==
    4 == min + max`` des bornes par défaut.

    ``bounded_quota_back`` (opt-in, défaut ``False`` -> comportement
    byte-identique, PRÉ-EXISTANT BUG corrigé ici, EXIGE ``bounded_quota=True``
    sinon ``ValueError`` -- voir le garde-fou juste avant la génération de la
    banque : sans ``bounded_quota``, ``back_quota`` (ligne ~307) resterait
    ``PAR_QUOTAS`` générique alors que ``back_params.bounded_quota`` serait
    quand même forcé à ``True`` ci-dessous, un piège silencieux) : seul ``front_params``
    recevait ``bounded_quota=True`` ci-dessous -- ``back_params`` restait
    inchangé et passé tel quel à ``solve_nine``, donc
    ``solver._bounded_quota_filter`` (et le forçage ``par5_bounds``/
    ``par5_deadline`` qu'il porte) n'était JAMAIS exercé côté BACK, quel que
    soit ``bounded_quota``. Quand ``bounded_quota_back`` est vrai, ce
    paramètre force aussi ``back_params.bounded_quota=True`` : le back doit
    alors finir avec son propre compte de par3/par5 dans SES bornes
    (``back_params.par3_bounds``/``par5_bounds``, déjà plombées par
    l'appelant ou par ``par5_deadline`` ci-dessous) via le même mécanisme de
    forçage que le front. Aucun ``global_quota`` n'est transmis au back (reste
    ``None``, défaut de ``solve_nine``) : le back est le DERNIER nine, il n'y
    a plus de nine suivant dont protéger le minimum (le « plafond solidaire »
    de ``_bounded_quota_filter`` ne s'applique qu'entre deux nines successifs)
    -- ses propres bornes ``lo``/``hi`` et son quota exact
    (``_global_remaining_from_front``, déjà le ``par_quota`` transmis plus
    bas) suffisent à le contraindre correctement, y compris quand
    ``lo == hi`` (ex. ``(2, 2)``, voir les tests).

    ``back_closing_lookahead_from`` : surcharge ``back_params.closing_lookahead_from``
    (fermeture anticipée, ``solver._has_closing_sequence``) sans toucher au
    reste de ``back_params`` — ``None`` (défaut) ne change rien.

    ``back_clubhouse_max`` / ``back_start_radii`` (décision utilisateur) :
    surchargent respectivement ``back_params.clubhouse_max`` (plafond dur
    départ trou 10 / retour trou 18) et ``back_params.start_radii`` (rayons
    de départ essayés au tee 10, voir ``solver._raw_transforms``) sans
    toucher au reste de ``back_params`` ni au front — ``None`` (défaut) ne
    change rien. Le plafond du front (``front_params.clubhouse_max``) et le
    sien propre (``start_radii``) restent inchangés dans tous les cas : ces
    deux surcharges ne touchent QUE le back.

    ``back_start_radius_groups`` / ``back_start_radius_depth2_min_survivors``
    (décision utilisateur, PLAN.md ligne 6) : surchargent respectivement
    ``back_params.start_radius_groups`` et
    ``back_params.start_radius_depth2_min_survivors`` (diversité stratifiée
    des départs du tee 10 par groupe de rayon, voir
    ``solver.SolverParams.start_radius_groups``) — ``None`` (défaut) ne
    change rien ; comme les deux surcharges précédentes, ne touchent QUE le
    back.

    ``par5_deadline`` (décision utilisateur, PLAN.md ligne 6, expérience
    « deadline par5 ») : surcharge ``SolverParams.par5_deadline`` sur LES
    DEUX nines (contrairement aux surcharges ``back_*`` ci-dessus, cette
    règle doit s'appliquer symétriquement au front ET au back) — ``None``
    (défaut) ne change rien, sans effet si ``bounded_quota`` est faux.

    ``arrival_max_angle_deg`` (décision utilisateur, PLAN.md ligne 6,
    expérience « arrivée radiale ») : surcharge ``SolverParams.
    arrival_max_angle_deg`` sur LES DEUX nines (même raison que
    ``par5_deadline`` : le trou de clôture du front, 9, et celui du back,
    18, doivent tous les deux respecter la règle) ET le même seuil est
    transmis à ``_course_violations`` ci-dessous pour la validation
    indépendante — ``None`` (défaut) ne change rien."""
    if free_quota and bounded_quota:
        raise ValueError("free_quota et bounded_quota sont mutuellement exclusifs")
    if bounded_quota_back and not bounded_quota:
        raise ValueError(
            "bounded_quota_back=True sans bounded_quota=True est un piège : "
            "back_quota (ligne ~307) ne bascule sur _global_remaining_from_front "
            "que si bounded_quota (ou free_quota) est vrai, sinon le back reçoit "
            "le quota générique PAR_QUOTAS alors que solver._bounded_quota_filter "
            "est quand même actif côté back -- activez aussi bounded_quota=True."
        )
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
    if back_closing_lookahead_from is not None:
        back_params = replace(back_params, closing_lookahead_from=back_closing_lookahead_from)
    if back_clubhouse_max is not None:
        back_params = replace(back_params, clubhouse_max=back_clubhouse_max)
    if back_start_radii is not None:
        back_params = replace(back_params, start_radii=back_start_radii)
    if back_start_radius_groups is not None:
        back_params = replace(back_params, start_radius_groups=back_start_radius_groups)
    if back_start_radius_depth2_min_survivors is not None:
        back_params = replace(back_params,
                              start_radius_depth2_min_survivors=back_start_radius_depth2_min_survivors)
    if par5_deadline is not None:
        front_params = replace(front_params, par5_deadline=par5_deadline)
        back_params = replace(back_params, par5_deadline=par5_deadline)
    if arrival_max_angle_deg is not None:
        front_params = replace(front_params, arrival_max_angle_deg=arrival_max_angle_deg)
        back_params = replace(back_params, arrival_max_angle_deg=arrival_max_angle_deg)
    if bounded_quota_back:
        back_params = replace(back_params, bounded_quota=True)
    bank = generate_bank(seed, GenerationParams.eighteen())

    if bounded_quota:
        front_params = replace(front_params, bounded_quota=True)
        front_quota = _bounded_front_quota(front_params)
        front = solve_nine(seed, front_params, rules, bank=bank, par_quota=front_quota,
                           require_full_quota=False, global_quota=GLOBAL_PAR_QUOTA)
    else:
        front_quota = dict(GLOBAL_PAR_QUOTA) if free_quota else dict(PAR_QUOTAS)
        front = solve_nine(seed, front_params, rules, bank=bank, par_quota=front_quota,
                           require_full_quota=not free_quota)
    if not front.complete:
        return CourseSolveResult(seed, front, None, False, ("front_incomplete",))

    used = frozenset(bean.id for bean in front.state.placed)
    back_quota = (_global_remaining_from_front(front.state.placed) if (free_quota or bounded_quota)
                 else dict(PAR_QUOTAS))
    back = solve_nine(seed ^ 0x9E3779B9, back_params, rules, bank=bank,
                      obstacles=front.state.placed, blocked_ids=used, order_offset=9,
                      par_quota=back_quota)
    clubhouse = (rules.width / 2.0, rules.height / 2.0)
    violations = _course_violations(
        front.state.placed, back.state.placed, rules, clubhouse,
        front_params.clubhouse_max, back_params.clubhouse_max,
        arrival_max_angle_deg=front_params.arrival_max_angle_deg,
        # BUG corrigé ici (voir _course_violations docstring, back_par3_bounds
        # / back_par5_bounds / back_par5_deadline) : chaque nine est désormais
        # contrôlé avec SES PROPRES par3_bounds/par5_bounds/par5_deadline
        # (``front_params``/``back_params``), pas toujours ceux du front --
        # le gate ``if <params>.bounded_quota`` est appliqué indépendamment
        # par nine (``bounded_quota`` local == ``front_params.bounded_quota``
        # après le forçage ci-dessus ; ``back_params.bounded_quota`` n'est
        # vrai que si ``bounded_quota_back=True``), ``par5_deadline`` reste
        # non gated (comme avant) car indépendant du mode quota borné.
        par3_bounds=front_params.par3_bounds if bounded_quota else None,
        par5_bounds=front_params.par5_bounds if bounded_quota else None,
        par5_deadline=front_params.par5_deadline,
        back_par3_bounds=back_params.par3_bounds if back_params.bounded_quota else None,
        back_par5_bounds=back_params.par5_bounds if back_params.bounded_quota else None,
        back_par5_deadline=back_params.par5_deadline,
    )
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
