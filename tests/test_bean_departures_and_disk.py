"""Tests pour les deux expériences indépendantes PLAN.md ligne 6 :

1. Départs aléatoires du tee de profondeur 1 (``solver.SolverParams.random_departures``) --
   remplace la grille fixe (``departure_angles`` x ``start_radii``) par des
   positions tirées, déterministe par ``(seed, nine)``, cercle complet,
   rayon dans l'intervalle fourni.
2. Disque d'exclusion clubhouse TOTAL (``geometry.ValidationRules.clubhouse_block_radius``) --
   aucune empreinte (cœur ET rough) ne peut intersecter le disque.

Les deux sont opt-in (défaut inchangé -> comportement byte-identique) : les
tests le vérifient explicitement.
"""

from __future__ import annotations

import math

from experiments.bean_paving.bean_bank import BeanTemplate
from experiments.bean_paving.bean_bank import _footprint as _bank_footprint
from experiments.bean_paving.geometry import PlacedBean, Transform, ValidationRules, validate
from experiments.bean_paving.solver import SearchState, SolverParams, _raw_transforms


def _straight_bean(name: str, par: int, length: float, width: float = 10.0,
                   margin: float = 0.0) -> BeanTemplate:
    """``margin`` > 0 donne une empreinte (rough) bufferisée plus large que le
    cœur (``core_footprint``, radius ``width / 2`` seul) -- nécessaire pour
    distinguer les deux dans les tests du disque d'exclusion total."""
    axis = ((0.0, 0.0), (length, 0.0))
    core = _bank_footprint(axis, width / 2.0)
    footprint = _bank_footprint(axis, width / 2.0 + margin)
    return BeanTemplate(name, par, length, axis, width, margin, footprint,
                        axis[0], axis[-1], 0.0, 0.0, allow_mirror=False, core_footprint=core)


def _placed(template: BeanTemplate, x: float, y: float, order: int, rotation: float = 0.0) -> PlacedBean:
    return PlacedBean(template, Transform(x, y, rotation, False), order)


# -- solver.py : départs aléatoires -----------------------------------------


def test_raw_transforms_default_stays_the_fixed_grid():
    # Défaut (``random_departures=False``) : comportement byte-identique à
    # avant ce paramètre -- grille fixe, pas de tirage.
    clubhouse = (150.0, 150.0)
    template = _straight_bean("t", 4, 10.0)
    state = SearchState((), (1, 0, 0), 0.0)
    params = SolverParams(start_radii=(24.0, 36.0), departure_angles=(0, 90), rotation_step_deg=360)
    transforms = list(_raw_transforms(template, state, clubhouse, params, seed=1))
    distances = {round(math.dist((t.x, t.y), clubhouse), 3) for t in transforms}
    assert distances == {24.0, 36.0}
    assert len(transforms) == 2 * 2 * 1  # radii x angles x rotations(1) x mirrors(1)


def test_random_departures_full_circle_and_radius_range():
    clubhouse = (150.0, 150.0)
    template = _straight_bean("t", 4, 10.0)
    state = SearchState((), (1, 0, 0), 0.0)
    params = SolverParams(random_departures=True, random_departure_count=200,
                          random_departure_radius=(44.0, 96.0), rotation_step_deg=360)
    transforms = list(_raw_transforms(template, state, clubhouse, params, seed=7))
    assert len(transforms) == 200  # count x rotations(1) x mirrors(1)
    angles = []
    for t in transforms:
        radius = math.dist((t.x, t.y), clubhouse)
        assert 44.0 <= radius <= 96.0
        angles.append(math.degrees(math.atan2(t.y - clubhouse[1], t.x - clubhouse[0])) % 360.0)
    # Cercle complet, pas restreint à un secteur : au moins un tirage dans
    # chacun des 4 quadrants sur 200 essais (déterministe pour ce seed/sel).
    quadrants = {int(angle // 90) for angle in angles}
    assert quadrants == {0, 1, 2, 3}


def test_random_departures_count_matches_requested_tee_position_count():
    # Nombre de positions de départ = ``random_departure_count`` (pas une
    # fonction de ``departure_angles``/``start_radii``, ignorés dans ce
    # mode) -- garantit un coût comparable à la grille qu'il remplace.
    clubhouse = (150.0, 150.0)
    template = _straight_bean("t", 4, 10.0)
    state = SearchState((), (1, 0, 0), 0.0)
    params = SolverParams(random_departures=True, random_departure_count=10,
                          random_departure_radius=(24.0, 48.0), rotation_step_deg=360)
    transforms = list(_raw_transforms(template, state, clubhouse, params, seed=3))
    tee_points = {(round(t.x, 6), round(t.y, 6)) for t in transforms}
    assert len(tee_points) <= 10  # au plus 10 positions distinctes tirées
    assert len(transforms) == 10


def test_random_departures_deterministic_per_seed_and_differ_across_seeds():
    clubhouse = (150.0, 150.0)
    template = _straight_bean("t", 4, 10.0)
    state = SearchState((), (1, 0, 0), 0.0)
    params = SolverParams(random_departures=True, random_departure_count=20,
                          random_departure_radius=(24.0, 48.0), rotation_step_deg=360)
    first = [(round(t.x, 4), round(t.y, 4)) for t in _raw_transforms(template, state, clubhouse, params, seed=5)]
    second = [(round(t.x, 4), round(t.y, 4)) for t in _raw_transforms(template, state, clubhouse, params, seed=5)]
    assert first == second  # même seed -> même tirage (reproductible)
    other_seed = [(round(t.x, 4), round(t.y, 4))
                  for t in _raw_transforms(template, state, clubhouse, params, seed=6)]
    assert first != other_seed  # seed différent -> tirage différent


def test_random_departures_differ_between_front_and_back_seed():
    # ``course_solver.solve_course`` dérive le seed du back par
    # ``seed ^ 0x9E3779B9`` : même seed de base, deux tirages différents.
    clubhouse = (150.0, 150.0)
    template = _straight_bean("t", 4, 10.0)
    state = SearchState((), (1, 0, 0), 0.0)
    params = SolverParams(random_departures=True, random_departure_count=20,
                          random_departure_radius=(24.0, 48.0), rotation_step_deg=360)
    front = [(round(t.x, 4), round(t.y, 4)) for t in _raw_transforms(template, state, clubhouse, params, seed=4)]
    back = [(round(t.x, 4), round(t.y, 4))
            for t in _raw_transforms(template, state, clubhouse, params, seed=4 ^ 0x9E3779B9)]
    assert front != back


# -- solver.py : SolverParams defaults inchangés -----------------------------


def test_solver_params_random_departures_defaults_are_inert():
    params = SolverParams()
    assert params.random_departures is False
    assert params.random_departure_count == 0
    assert params.random_departure_radius == (0.0, 0.0)


# -- geometry.py : disque d'exclusion clubhouse total ------------------------


def test_clubhouse_block_radius_default_is_none_and_inert():
    rules = ValidationRules(width=300.0, height=300.0)
    assert rules.clubhouse_block_radius is None
    # Un haricot qui passe en plein sur le clubhouse ne déclenche AUCUNE
    # violation ``clubhouse_block`` par défaut.
    bean = _placed(_straight_bean("b", 4, 10.0, width=4.0), 150.0, 150.0, 1)
    violations = validate((bean,), rules, check_links=False)
    assert all(problem.kind != "clubhouse_block" for problem in violations)


def test_clubhouse_block_radius_rejects_rough_intrusion():
    # Cœur hors du disque (gap 28 >= 25, pas de violation ``clubhouse_clear``
    # même si la règle était active), mais le ROUGH (buffer plus large,
    # ``margin=10``) entre dans le disque de 25 (gap 18 < 25) --
    # ``clubhouse_block_radius`` protège l'empreinte ENTIÈRE, contrairement à
    # ``clubhouse_clear_radius`` qui ne protège que le cœur.
    rules = ValidationRules(width=300.0, height=300.0, clubhouse_block_radius=25.0,
                            clubhouse_clear_radius=None, shared_rough=True)
    clubhouse = rules.clubhouse
    bean = _placed(_straight_bean("b", 4, 10.0, width=4.0, margin=10.0),
                   clubhouse[0] + 30.0, clubhouse[1], 1, rotation=90.0)
    violations = validate((bean,), rules, check_links=False)
    assert all(problem.kind != "clubhouse_clear" for problem in violations)
    assert any(problem.kind == "clubhouse_block" for problem in violations)


def test_clubhouse_block_radius_accepts_beans_fully_outside_the_disk():
    rules = ValidationRules(width=300.0, height=300.0, clubhouse_block_radius=25.0,
                            clubhouse_clear_radius=None)
    clubhouse = rules.clubhouse
    bean = _placed(_straight_bean("b", 4, 10.0, width=4.0),
                   clubhouse[0] + 60.0, clubhouse[1], 1, rotation=90.0)
    violations = validate((bean,), rules, check_links=False)
    assert all(problem.kind != "clubhouse_block" for problem in violations)


def test_clubhouse_block_radius_applies_without_shared_rough():
    # Contrairement à ``clubhouse_clear_radius`` (mode ``shared_rough``
    # uniquement), ``clubhouse_block_radius`` s'applique inconditionnellement.
    rules = ValidationRules(width=300.0, height=300.0, clubhouse_block_radius=25.0,
                            shared_rough=False)
    assert rules.shared_rough is False
    clubhouse = rules.clubhouse
    bean = _placed(_straight_bean("b", 4, 10.0, width=4.0), clubhouse[0], clubhouse[1], 1)
    violations = validate((bean,), rules, check_links=False)
    assert any(problem.kind == "clubhouse_block" for problem in violations)


# -- solver.py : cible de profondeur 9 tient compte du disque ----------------


def test_scaled_target_radius_depth9_widens_for_the_block_disk():
    from experiments.bean_paving.solver import _scaled_target_radius
    params = SolverParams(clubhouse_max=60.0)
    without_disk = ValidationRules(clubhouse_block_radius=None)
    with_disk = ValidationRules(clubhouse_block_radius=25.0)
    assert _scaled_target_radius(9, params, without_disk) == min(35.0, 60.0 * 0.75)
    assert _scaled_target_radius(9, params, with_disk) == max(min(35.0, 60.0 * 0.75), 25.0 + 15.0)
    assert _scaled_target_radius(9, params, with_disk) == 40.0


# -- solver.py : cible de profondeur 9 explicite (expérience "disque équitable") --


def test_solver_params_target_radius_depth9_min_default_is_none_and_inert():
    # Défaut ``None`` -> ``_scaled_target_radius`` retombe sur la formule
    # historique (``+15`` si ``rules.clubhouse_block_radius`` est renseigné) :
    # comportement byte-identique à avant ce paramètre.
    from experiments.bean_paving.solver import _scaled_target_radius
    params = SolverParams(clubhouse_max=60.0)
    assert params.target_radius_depth9_min is None
    with_disk = ValidationRules(clubhouse_block_radius=25.0)
    assert _scaled_target_radius(9, params, with_disk) == 40.0


def test_scaled_target_radius_depth9_min_overrides_the_plus15_formula():
    # Valeur explicite (ex. 50.0, expérience "disque équitable") : prend le
    # pas sur la formule ``+15`` (qui donnerait 40.0 ici) même avec le même
    # disque -- et s'applique aussi SANS disque actif (``rules.clubhouse_block_radius``
    # ``None``), contrairement à la formule qu'elle remplace.
    from experiments.bean_paving.solver import _scaled_target_radius
    params = SolverParams(clubhouse_max=80.0, target_radius_depth9_min=50.0)
    with_disk = ValidationRules(clubhouse_block_radius=25.0)
    without_disk = ValidationRules(clubhouse_block_radius=None)
    assert _scaled_target_radius(9, params, with_disk) == 50.0
    assert _scaled_target_radius(9, params, without_disk) == 50.0


def test_scaled_target_radius_depth9_min_still_bounded_by_clubhouse_max():
    # La cible reste un ``max(...)`` appliqué APRÈS le plafond
    # ``min(_target_radius(9), clubhouse_max * 0.75)`` -- une valeur
    # explicite plus petite que ce plafond ne l'abaisse pas.
    from experiments.bean_paving.solver import _scaled_target_radius
    params = SolverParams(clubhouse_max=200.0, target_radius_depth9_min=10.0)
    rules = ValidationRules(clubhouse_block_radius=25.0)
    assert _scaled_target_radius(9, params, rules) == min(35.0, 200.0 * 0.75)
