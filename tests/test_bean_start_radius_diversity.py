"""Tests pour la diversité stratifiée des départs du tee 10 par groupe de
rayon (PLAN.md ligne 6, décision utilisateur suivant ``back_start_radii``
étendus) : ``solver.SolverParams.start_radius_groups`` /
``start_radius_depth2_min_survivors``, opt-in (défauts ``()`` / ``0``), aux
deux endroits où la diversité de la profondeur 1 se faisait écraser (a. la
troncature des transformations brutes par candidat, b. la sélection du
beam) -- plus le garde-fou léger optionnel de la profondeur 2."""

from collections import Counter
import math

from experiments.bean_paving.bean_bank import BeanTemplate
from experiments.bean_paving.bean_bank import _footprint as _bank_footprint
from experiments.bean_paving.course_solver import solve_course
from experiments.bean_paving.geometry import PlacedBean, Transform
from experiments.bean_paving.solver import (
    SearchState, SolverParams, _radius_group_index, _select_beam_stratified, _stratified_truncate,
)

GROUPS = ((44.0, 48.0), (64.0,), (80.0,), (96.0,))
CLUBHOUSE = (0.0, 0.0)


def _straight_bean(name: str, par: int = 4, length: float = 10.0) -> BeanTemplate:
    axis = ((0.0, 0.0), (length, 0.0))
    return BeanTemplate(name, par, length, axis, 10.0, 0.0, _bank_footprint(axis, 5.0),
                        axis[0], axis[-1], 0.0, 0.0, allow_mirror=False)


def _transform_at(radius: float, angle_deg: float) -> Transform:
    rad = math.radians(angle_deg)
    return Transform(CLUBHOUSE[0] + radius * math.cos(rad), CLUBHOUSE[1] + radius * math.sin(rad))


def _state_at(radius: float, angle_deg: float, score: float, name: str) -> SearchState:
    bean = PlacedBean(_straight_bean(name), _transform_at(radius, angle_deg), 10)
    return SearchState((bean,), (2, 5, 2), score)


def _group_of(point: tuple) -> int:
    return _radius_group_index(math.dist(point, CLUBHOUSE), GROUPS)


# -- SolverParams : défauts inchangés ---------------------------------------


def test_solver_params_defaults_disable_stratification():
    params = SolverParams()
    assert params.start_radius_groups == ()
    assert params.start_radius_depth2_min_survivors == 0


# -- _radius_group_index -----------------------------------------------------


def test_radius_group_index_matches_the_nearest_group():
    assert _radius_group_index(44.0, GROUPS) == 0
    assert _radius_group_index(48.0, GROUPS) == 0
    assert _radius_group_index(64.0, GROUPS) == 1
    assert _radius_group_index(80.0, GROUPS) == 2
    assert _radius_group_index(96.3, GROUPS) == 3  # bruit flottant toléré


# -- _stratified_truncate : troncature (a) -----------------------------------


def test_stratified_truncate_keeps_every_group_represented():
    transforms = [_transform_at(radius, angle)
                 for radius in (44.0, 48.0, 64.0, 80.0, 96.0)
                 for angle in range(0, 360, 36)]  # 10 par rayon, largement > la part
    limit = 8
    result = _stratified_truncate(transforms, limit, GROUPS, CLUBHOUSE)
    assert len(result) == limit
    present = {_group_of((t.x, t.y)) for t in result}
    assert present == {0, 1, 2, 3}
    counts = Counter(_group_of((t.x, t.y)) for t in result)
    # part égale (limit // 4 == 2) pour chaque groupe, offre abondante partout.
    assert counts == {0: 2, 1: 2, 2: 2, 3: 2}


def test_stratified_truncate_fills_leftover_from_the_remaining_pool():
    # Groupe 0 n'a qu'UN seul candidat (moins que sa part de 2) : le
    # reliquat doit être comblé par les autres groupes, jamais perdu, et le
    # candidat unique du groupe sous-peuplé doit être conservé.
    transforms = [_transform_at(44.0, 0.0)]
    transforms += [_transform_at(radius, angle)
                   for radius in (64.0, 80.0, 96.0)
                   for angle in range(0, 360, 36)]
    limit = 8
    result = _stratified_truncate(transforms, limit, GROUPS, CLUBHOUSE)
    assert len(result) == limit
    counts = Counter(_group_of((t.x, t.y)) for t in result)
    assert counts[0] == 1  # le seul candidat disponible, jamais écarté
    assert sum(counts.values()) == limit


def test_stratified_truncate_never_exceeds_the_limit_when_pool_is_small():
    transforms = [_transform_at(44.0, 0.0), _transform_at(64.0, 0.0)]
    result = _stratified_truncate(transforms, 8, GROUPS, CLUBHOUSE)
    assert len(result) == 2  # jamais plus que ce qui existe réellement


# -- _select_beam_stratified : sélection du beam (b) -------------------------


def test_select_beam_stratified_keeps_every_group_represented():
    states = []
    for idx, radius in enumerate((44.0, 64.0, 80.0, 96.0)):
        for i in range(10):
            states.append(_state_at(radius, i * 36, float(idx * 100 + i), f"g{idx}-{i}"))
    width, share = 8, 2
    beam = _select_beam_stratified(states, width, share, GROUPS, CLUBHOUSE)
    assert len(beam) == width
    counts = Counter(_group_of((s.placed[0].transform.x, s.placed[0].transform.y)) for s in beam)
    assert counts == {0: 2, 1: 2, 2: 2, 3: 2}


def test_select_beam_stratified_fills_leftover_by_global_rank_when_a_group_is_thin():
    # Groupe 0 n'a qu'UN état (bien pire score que tout le reste) : il doit
    # quand même survivre (sa part de 2 n'a qu'un candidat, jamais inventé).
    # Chaque AUTRE groupe reçoit d'abord sa propre part (2, les meilleurs en
    # interne) ; SEUL le reliquat au-delà de la somme des parts (1 place
    # ici, 8 - (1+2+2+2)) va au meilleur score global parmi ce qui reste
    # (score 12, le meilleur des laissés-pour-compte du groupe 1).
    states = [_state_at(44.0, 0.0, score=999.0, name="thin")]
    for idx, radius in enumerate((64.0, 80.0, 96.0), start=1):
        for i in range(5):
            states.append(_state_at(radius, i * 36, float(idx * 10 + i), f"g{idx}-{i}"))
    width, share = 8, 2
    beam = _select_beam_stratified(states, width, share, GROUPS, CLUBHOUSE)
    assert len(beam) == width
    counts = Counter(_group_of((s.placed[0].transform.x, s.placed[0].transform.y)) for s in beam)
    assert counts == {0: 1, 1: 3, 2: 2, 3: 2}
    assert sorted(s.score for s in beam) == [10.0, 11.0, 12.0, 20.0, 21.0, 30.0, 31.0, 999.0]


# -- course_solver.solve_course : plomberie, ne touche que le back ----------


_FRONT_PARAMS = SolverParams(beam_width=16, candidates_per_par=2, transforms_per_candidate=12,
                             departure_angles=(300, 330, 0, 30, 60), target_radius_scale=0.9,
                             bbox_weight=0.0004)
_BACK_PARAMS = SolverParams(beam_width=8, candidates_per_par=1, transforms_per_candidate=6,
                            departure_angles=tuple(range(0, 360, 30)), start_radii=(24.0, 36.0),
                            start_transforms_per_candidate=10)


def test_solve_course_defaults_leave_start_radius_groups_disabled():
    result = solve_course(1, front_params=_FRONT_PARAMS, back_params=_BACK_PARAMS, bounded_quota=True)
    assert result.back.params.start_radius_groups == ()
    assert result.back.params.start_radius_depth2_min_survivors == 0


def test_solve_course_start_radius_groups_are_plumbed_through_the_back_only():
    result = solve_course(1, front_params=_FRONT_PARAMS, back_params=_BACK_PARAMS, bounded_quota=True,
                          back_start_radius_groups=GROUPS,
                          back_start_radius_depth2_min_survivors=9)
    assert result.front.params.start_radius_groups == ()
    assert result.front.params.start_radius_depth2_min_survivors == 0
    assert result.back.params.start_radius_groups == GROUPS
    assert result.back.params.start_radius_depth2_min_survivors == 9
