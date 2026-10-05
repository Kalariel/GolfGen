"""Tests pour la décision utilisateur « back deux fois plus loin du
clubhouse » (étape 1 d'une série) : plafond dur (``clubhouse_max``) distinct
par nine et rayons de départ du tee 10 étendus (``start_radii``). Les deux
changements sont opt-in (nouveaux paramètres de ``course_solver.solve_course``) :
les tests vérifient aussi que les défauts ne changent rien."""

from dataclasses import replace
import math

from experiments.bean_paving.bean_bank import BeanBank, BeanTemplate
from experiments.bean_paving.bean_bank import _footprint as _bank_footprint
from experiments.bean_paving.course_solver import _course_violations, solve_course
from experiments.bean_paving.geometry import PlacedBean, Transform, ValidationRules
from experiments.bean_paving.solver import SearchState, SolverParams, _has_closing_move, _raw_transforms, expand_state


def _straight_bean(name: str, par: int, length: float, width: float = 10.0) -> BeanTemplate:
    axis = ((0.0, 0.0), (length, 0.0))
    return BeanTemplate(name, par, length, axis, width, 0.0, _bank_footprint(axis, width / 2.0),
                        axis[0], axis[-1], 0.0, 0.0, allow_mirror=False)


def _placed(template: BeanTemplate, x: float, y: float, order: int, rotation: float = 0.0) -> PlacedBean:
    return PlacedBean(template, Transform(x, y, rotation, False), order)


# -- course_solver._course_violations : plafond distinct front/back --------


def test_course_violations_single_positional_arg_keeps_historical_behavior():
    # Tout appelant existant (run_back_closure.py, run_closure_ab.py,
    # l'ancien appel de benchmark_course.py) ne passe qu'UN SEUL plafond
    # positionnel : le back doit en hériter exactement comme avant l'ajout
    # de ce paramètre (``back_clubhouse_max`` par défaut ``None``).
    rules = ValidationRules(width=400.0, height=400.0)
    clubhouse = (200.0, 200.0)
    far = _placed(_straight_bean("far", 4, 1.0), 280.0, 200.0, 10)
    violations = _course_violations((), (far,), rules, clubhouse, 50.0)
    assert "back_start" in violations
    assert "back_return" in violations


def test_course_violations_back_clubhouse_max_relaxes_only_the_back():
    rules = ValidationRules(width=400.0, height=400.0)
    clubhouse = (200.0, 200.0)
    front_far = _placed(_straight_bean("f", 4, 1.0), 280.0, 200.0, 1)
    back_far = _placed(_straight_bean("b", 4, 1.0), 280.0, 200.0, 10)
    violations = _course_violations((front_far,), (back_far,), rules, clubhouse, 50.0, 100.0)
    # Front reste bridé à son propre plafond (50) : 80 > 50, violation.
    assert "front_start" in violations
    assert "front_return" in violations
    # Back profite du plafond relevé (100) : 80/81 <= 100, aucune violation.
    assert "back_start" not in violations
    assert "back_return" not in violations


# -- solver.py : plafond dur et départs honorent params.clubhouse_max/start_radii --


def test_raw_transforms_departure_tries_every_start_radius_including_the_extended_ones():
    clubhouse = (150.0, 150.0)
    template = _straight_bean("t", 4, 10.0)
    state = SearchState((), (1, 0, 0), 0.0)
    params = SolverParams(start_radii=(44.0, 48.0, 64.0, 80.0, 96.0), departure_angles=(0,),
                          rotation_step_deg=360)
    transforms = list(_raw_transforms(template, state, clubhouse, params))
    distances = {round(math.dist((t.x, t.y), clubhouse), 3) for t in transforms}
    assert distances == {44.0, 48.0, 64.0, 80.0, 96.0}


def test_expand_state_depth9_honors_a_relaxed_clubhouse_max():
    rules = ValidationRules(width=300.0, height=300.0, link_min=0.0, link_max=1000.0,
                            antiparallel_distance=0.0)
    clubhouse = (150.0, 150.0)
    previous = _placed(_straight_bean("prev", 4, 10.0, width=4.0), 140.0, 150.0, 7)  # green = clubhouse
    state = SearchState((previous,), (0, 1, 0), 0.0)
    bank = BeanBank(seed=1, templates=(_straight_bean("last", 4, 80.0, width=4.0),))
    # link_length=10 (gap réel, pas une coïncidence exacte tee==green
    # précédent) : le green du dernier haricot tombe entre 70 et 90 du
    # clubhouse selon l'angle de départ (12 angles fixes de ``_raw_transforms``
    # pour un état non vide), toujours > 50 et toujours <= 100.
    base_params = SolverParams(candidates_per_par=1, transforms_per_candidate=40,
                               rotation_step_deg=360, link_lengths=(10.0,), closure_lookahead=False)

    tight = expand_state(state, 9, bank, clubhouse, replace(base_params, clubhouse_max=50.0),
                         rules, seed=1)
    assert tight.rejected.get("clubhouse_return", 0) > 0
    assert len(tight.children) == 0

    relaxed = expand_state(state, 9, bank, clubhouse, replace(base_params, clubhouse_max=100.0),
                           rules, seed=1)
    assert len(relaxed.children) > 0
    for child in relaxed.children:
        distance = math.dist(child.placed[-1].green, clubhouse)
        assert 50.0 < distance <= 100.0


def test_has_closing_move_honors_a_relaxed_clubhouse_max():
    # Même géométrie que ci-dessus, mais via le regard d'un coup
    # (``_has_closing_move``, alias ``steps_remaining=1``) -- le chemin
    # empruntée par la fermeture anticipée à la profondeur 8.
    rules = ValidationRules(width=300.0, height=300.0, link_min=0.0, link_max=1000.0,
                            antiparallel_distance=0.0)
    clubhouse = (150.0, 150.0)
    previous = _placed(_straight_bean("prev", 4, 10.0, width=4.0), 140.0, 150.0, 7)
    state = SearchState((previous,), (0, 1, 0), 0.0)
    bank = BeanBank(seed=1, templates=(_straight_bean("last", 4, 80.0, width=4.0),))
    base_params = SolverParams(candidates_per_par=1, transforms_per_candidate=40,
                               rotation_step_deg=360, link_lengths=(10.0,), closure_lookahead=False)

    assert not _has_closing_move(state, bank, clubhouse, replace(base_params, clubhouse_max=50.0),
                                 rules, seed=1)
    assert _has_closing_move(state, bank, clubhouse, replace(base_params, clubhouse_max=100.0),
                             rules, seed=1)


# -- course_solver.solve_course : plomberie des deux nouvelles surcharges --


_FRONT_PARAMS = SolverParams(beam_width=16, candidates_per_par=2, transforms_per_candidate=12,
                             departure_angles=(300, 330, 0, 30, 60), target_radius_scale=0.9,
                             bbox_weight=0.0004)
_BACK_PARAMS = SolverParams(beam_width=8, candidates_per_par=1, transforms_per_candidate=6,
                            departure_angles=tuple(range(0, 360, 30)), start_radii=(24.0, 36.0),
                            start_transforms_per_candidate=10)


def test_solve_course_defaults_are_unchanged_without_the_new_overrides():
    result = solve_course(1, front_params=_FRONT_PARAMS, back_params=_BACK_PARAMS, bounded_quota=True)
    assert result.front.params.clubhouse_max == 50.0
    assert result.back.params.clubhouse_max == 50.0
    assert result.back.params.start_radii == (24.0, 36.0)


def test_solve_course_back_clubhouse_max_and_start_radii_are_plumbed_through():
    result = solve_course(1, front_params=_FRONT_PARAMS, back_params=_BACK_PARAMS, bounded_quota=True,
                          back_clubhouse_max=100.0, back_start_radii=(44.0, 48.0, 64.0, 80.0, 96.0))
    # Le front n'est JAMAIS touché par ces deux surcharges.
    assert result.front.params.clubhouse_max == 50.0
    assert result.front.params.start_radii == SolverParams().start_radii
    assert result.back.params.clubhouse_max == 100.0
    assert result.back.params.start_radii == (44.0, 48.0, 64.0, 80.0, 96.0)
