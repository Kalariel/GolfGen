"""Tests rapides pour EXPERIMENT_18_CLOSURE.md : quota global libre
(``course_solver.solve_course(free_quota=True)``) et fermeture anticipée
(``solver._has_closing_sequence`` / ``closing_lookahead_from``). Les deux
changements sont opt-in : les tests vérifient aussi que les défauts ne
changent rien."""

from experiments.bean_paving.bean_bank import BeanBank, BeanTemplate
from experiments.bean_paving.bean_bank import _footprint as _bank_footprint
from experiments.bean_paving.course_solver import _global_remaining_from_front
from experiments.bean_paving.geometry import PlacedBean, Transform, ValidationRules
from experiments.bean_paving.joint_solver import GLOBAL_PAR_QUOTA
from experiments.bean_paving.solver import (
    PAR_QUOTAS,
    SearchState,
    SolverParams,
    _has_closing_move,
    _has_closing_sequence,
    solve_nine,
)


def _straight_bean(name: str, par: int, length: float, width: float = 10.0) -> BeanTemplate:
    axis = ((0.0, 0.0), (length, 0.0))
    return BeanTemplate(name, par, length, axis, width, 0.0, _bank_footprint(axis, width / 2.0),
                        axis[0], axis[-1], 0.0, 0.0, allow_mirror=False)


def _placed(template: BeanTemplate, x: float, y: float, order: int, rotation: float = 0.0) -> PlacedBean:
    return PlacedBean(template, Transform(x, y, rotation, False), order)


def test_global_remaining_from_front_mirrors_the_global_quota():
    # Front a posé 4 par3 et 5 par4 (quota global libre entièrement consommé
    # sur ces deux classes) : il ne reste au back que du par4 et du par5,
    # jamais plus que le budget global, jamais négatif.
    front_placed = tuple(_placed(_straight_bean(f"f{i}", 3 if i < 4 else 4, 10.0), i * 30, 0, i)
                         for i in range(9))
    remaining = _global_remaining_from_front(front_placed)
    assert remaining == {3: 0, 4: GLOBAL_PAR_QUOTA[4] - 5, 5: GLOBAL_PAR_QUOTA[5]}
    assert sum(remaining.values()) == 9  # toujours les 9 trous du back, par construction


def test_global_remaining_from_front_sums_to_nine_regardless_of_split():
    # Peu importe la répartition par le front (tant qu'elle reste <= quota
    # global par classe), le reste pour le back somme toujours à 9 : front a
    # consommé exactement 9 trous sur les 18 du quota global.
    front_placed = tuple(_placed(_straight_bean(f"f{i}", 4, 10.0), i * 30, 0, i) for i in range(9))
    remaining = _global_remaining_from_front(front_placed)
    assert sum(remaining.values()) == 9
    assert remaining[4] == GLOBAL_PAR_QUOTA[4] - 9
    assert all(value >= 0 for value in remaining.values())


def test_require_full_quota_false_lets_a_nine_complete_without_exhausting_the_global_budget():
    # Avec le quota global (4/10/4, somme 18) passé à un seul nine (9 trous),
    # ``require_full_quota=True`` (comportement historique) ne peut jamais
    # être satisfait ; ``False`` permet la complétude dès 9 trous valides.
    result = solve_nine(42, par_quota=dict(GLOBAL_PAR_QUOTA), require_full_quota=False)
    assert len(result.state.placed) == 9
    assert result.complete
    assert sum(result.state.remaining) == sum(GLOBAL_PAR_QUOTA.values()) - 9


def test_require_full_quota_default_is_unchanged():
    # Défaut (True) : comportement historique, identique à avant ce paramètre.
    default_result = solve_nine(42)
    explicit_result = solve_nine(42, require_full_quota=True)
    assert default_result.to_json() == explicit_result.to_json()


def test_has_closing_sequence_default_matches_has_closing_move():
    rules = ValidationRules(width=300.0, height=300.0, link_min=0.0, link_max=1000.0,
                            antiparallel_distance=0.0)
    clubhouse = (150.0, 150.0)
    params = SolverParams(candidates_per_par=1, transforms_per_candidate=80, clubhouse_max=60.0)
    previous = _placed(_straight_bean("prev", 4, 40.0), 130.0, 150.0, 8)
    state = SearchState((previous,), (0, 1, 0), 0.0)
    bank = BeanBank(seed=1, templates=(_straight_bean("close", 4, 20.0),))
    assert _has_closing_move(state, bank, clubhouse, params, rules, seed=1) == \
        _has_closing_sequence(state, bank, clubhouse, params, rules, seed=1, steps_remaining=1)


def test_has_closing_sequence_prunes_a_constructed_dead_end_two_steps_out():
    """État à 2 coups de la fermeture, mais un mur bloque TOUT green
    atteignable depuis la position courante : aucune séquence de 2 trous ne
    peut passer ``geometry.validate``, donc ``steps_remaining=2`` doit
    renvoyer ``False`` — c'est exactement ce que ``closing_lookahead_from``
    doit permettre de détecter plus tôt qu'avant (avant : seul
    ``steps_remaining=1``, donc seulement visible à la profondeur 8).

    Liaisons et empreintes volontairement étroites (``width=4``, liaison
    fixe de 20) pour que le green précédent, déjà posé SUR le clubhouse,
    reste bien à l'intérieur de ``clubhouse_max`` après 2 coups quelle que
    soit la direction choisie, sans collision de gabarit — la séquence
    positive ne dépend donc pas du classement par distance
    (``_transform_rank``), seulement de la géométrie dure (``validate``),
    vérifié ci-dessous sur les 20 premières transformations candidates."""
    rules = ValidationRules(width=300.0, height=300.0, link_min=0.0, link_max=1000.0,
                            antiparallel_distance=0.0)
    clubhouse = (150.0, 150.0)
    params = SolverParams(candidates_per_par=1, transforms_per_candidate=60, clubhouse_max=60.0,
                          link_lengths=(20.0,),
                          lookahead_candidates_per_par=1, lookahead_transforms_per_candidate=20)
    previous = _placed(_straight_bean("prev", 4, 10.0, width=4.0), 140.0, 150.0, 7)  # green = clubhouse
    state = SearchState((previous,), (0, 2, 0), 0.0)
    # Deux gabarits distincts : le premier coup consomme l'un des deux
    # (``_candidate_templates`` exclut déjà posé), il en faut un second pour
    # que le DERNIER coup ait encore un candidat disponible.
    bank = BeanBank(seed=1, templates=(_straight_bean("mid1", 4, 15.0, width=4.0),
                                       _straight_bean("mid2", 4, 15.0, width=4.0)))

    # Sans obstacle : une séquence de 2 trous vers le clubhouse doit exister.
    assert _has_closing_sequence(state, bank, clubhouse, params, rules, seed=1, steps_remaining=2)

    # Un mur qui couvre toute la zone atteignable depuis le green précédent
    # fait disparaître TOUTE séquence, pas seulement le dernier coup — même
    # logique obstacle-aware que ``_has_closing_move``. Axe ET largeur du
    # mur dimensionnés pour couvrir réellement son empreinte (évite de
    # fausser le minorant bon marché axe-à-axe de ``geometry.validate``, qui
    # suppose l'empreinte ~ axe bufferisé par la largeur déclarée).
    big_wall = BeanTemplate(
        "wall", 4, 200.0, ((50.0, 150.0), (250.0, 150.0)),
        200.0, 0.0, ((50.0, 50.0), (250.0, 50.0), (250.0, 250.0), (50.0, 250.0)),
        (50.0, 150.0), (250.0, 150.0), 0.0, 0.0, allow_mirror=False,
    )
    obstacles = (_placed(big_wall, 0.0, 0.0, 0),)
    assert not _has_closing_sequence(state, bank, clubhouse, params, rules, seed=1,
                                     obstacles=obstacles, steps_remaining=2)


def test_closing_lookahead_from_default_does_not_change_expand_state_trigger():
    # closing_lookahead_from=9 (défaut) ne doit déclencher qu'à la profondeur
    # 8, comme avant ce paramètre : vérifié indirectement par la
    # déterminisme bit-à-bit d'un petit run avec et sans préciser le défaut.
    params_implicit = SolverParams(beam_width=12, candidates_per_par=2, transforms_per_candidate=18)
    params_explicit = SolverParams(beam_width=12, candidates_per_par=2, transforms_per_candidate=18,
                                   closing_lookahead_from=9)
    assert solve_nine(42, params_implicit).to_json() == solve_nine(42, params_explicit).to_json()
