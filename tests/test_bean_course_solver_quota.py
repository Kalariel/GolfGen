"""Tests de régression pour le correctif ``bounded_quota_back`` (revue de
code, 2026-10-05) : ``course_solver.solve_course`` ne mettait
``SolverParams.bounded_quota=True`` que côté FRONT -- ``back_params`` était
passé inchangé à ``solve_nine``, donc ``solver._bounded_quota_filter`` (et le
forçage ``par5_bounds``/``par5_deadline`` qu'il porte) n'était jamais exercé
côté BACK. Voir ``course_solver.solve_course`` docstring (paramètre
``bounded_quota_back``) et ``course_solver._course_violations`` (paramètre
``par5_deadline``)."""

from __future__ import annotations

from dataclasses import replace
from unittest.mock import patch
import inspect

import pytest

from experiments.bean_paving import course_solver as cs
from experiments.bean_paving.bean_bank import GenerationParams, generate_bank
from experiments.bean_paving.geometry import PlacedBean, Transform, ValidationRules
from experiments.bean_paving.solver import SearchState, SolveResult, SolverParams, solve_nine


def _fake_solve_nine_factory(captured):
    def fake(seed, params, rules, *, bank, par_quota, **kwargs):
        order_offset = kwargs.get("order_offset", 0)
        label = "back" if order_offset else "front"
        captured[label] = params
        state = SearchState((), (0, 0, 0), 0.0)
        return SolveResult(seed, (rules.width / 2.0, rules.height / 2.0), state, True, (), params)
    return fake


def test_default_bounded_quota_back_is_false():
    """Comportement byte-identique : le nouveau paramètre ne change rien tant
    qu'il n'est pas explicitement activé (même si ``bounded_quota`` du front
    l'est -- c'est exactement le bug corrigé)."""
    assert inspect.signature(cs.solve_course).parameters["bounded_quota_back"].default is False
    captured: dict = {}
    with patch.object(cs, "solve_nine", side_effect=_fake_solve_nine_factory(captured)):
        cs.solve_course(1, bounded_quota=True)
    assert captured["front"].bounded_quota is True
    assert captured["back"].bounded_quota is False


def test_bounded_quota_back_without_bounded_quota_raises():
    """Garde-fou (revue de code) : ``bounded_quota_back=True`` sans
    ``bounded_quota=True`` est un piège -- ``back_quota`` (ligne ~307 de
    ``course_solver.solve_course``) ne bascule sur
    ``_global_remaining_from_front`` que si ``bounded_quota`` (ou
    ``free_quota``) est vrai ; sinon le back recevrait le quota générique
    ``PAR_QUOTAS`` alors que ``solver._bounded_quota_filter`` serait quand
    même actif côté back. Doit lever ``ValueError`` avant tout calcul."""
    with pytest.raises(ValueError):
        cs.solve_course(1, bounded_quota_back=True)


def test_bounded_quota_back_propagates_flag_to_back_params():
    """Le correctif : ``bounded_quota_back=True`` force aussi
    ``back_params.bounded_quota=True``, sans toucher au front."""
    captured: dict = {}
    with patch.object(cs, "solve_nine", side_effect=_fake_solve_nine_factory(captured)):
        cs.solve_course(1, bounded_quota=True, bounded_quota_back=True)
    assert captured["front"].bounded_quota is True
    assert captured["back"].bounded_quota is True


def test_back_nine_respects_bounds_and_deadline_when_filter_active():
    """Preuve au niveau ``solver.solve_nine`` (ce que le back exécute une
    fois ``bounded_quota_back=True``) : bornes ``(2, 2)`` + deadline 7 ->
    exactement 2 par5, tous deux au plus tard au trou 7."""
    params = replace(SolverParams(beam_width=16), bounded_quota=True,
                     par5_bounds=(2, 2), par5_deadline=7)
    result = solve_nine(1, params, ValidationRules(), par_quota={3: 2, 4: 5, 5: 2})
    assert result.complete
    pars = [bean.template.par for bean in result.state.placed]
    par5_holes = [i + 1 for i, par in enumerate(pars) if par == 5]
    assert pars.count(5) == 2
    assert all(hole <= 7 for hole in par5_holes)


def _placed_nine(bank, pars, spacing=200.0, order_offset=0):
    beans = []
    for i, par in enumerate(pars):
        template = next(t for t in bank.templates if t.par == par)
        beans.append(PlacedBean(template, Transform(i * spacing, 0.0), order_offset + i + 1))
    return tuple(beans)


def test_course_violations_flags_late_par5_deadline():
    """``par5_bounds=(2, 2)``, ``par5_deadline=7`` : un back dont le 2e par5
    tombe au trou 8 (comme les seeds 2/3 du run A' invalide) doit être
    signalé par la validation indépendante -- c'est exactement le trou sur
    lequel ``_bounded_quota_filter`` aurait dû forcer le back s'il avait été
    actif (bug corrigé par ``bounded_quota_back``)."""
    bank = generate_bank(1, GenerationParams.eighteen())
    back = _placed_nine(bank, [4, 4, 4, 4, 4, 4, 5, 5, 4], order_offset=9)
    rules = ValidationRules(width=4000.0, height=4000.0)
    clubhouse = (2000.0, 2000.0)
    violations = cs._course_violations((), back, rules, clubhouse, 4000.0,
                                       par5_bounds=(2, 2), par5_deadline=7)
    assert "back_par5_deadline" in violations


def test_course_violations_does_not_flag_on_time_par5():
    """Même bornes/deadline, mais les deux par5 tombent aux trous 5 et 7
    (<= deadline) : pas de violation de deadline."""
    bank = generate_bank(1, GenerationParams.eighteen())
    back = _placed_nine(bank, [4, 4, 4, 4, 5, 4, 5, 4, 4], order_offset=9)
    rules = ValidationRules(width=4000.0, height=4000.0)
    clubhouse = (2000.0, 2000.0)
    violations = cs._course_violations((), back, rules, clubhouse, 4000.0,
                                       par5_bounds=(2, 2), par5_deadline=7)
    assert "back_par5_deadline" not in violations


def test_course_violations_deadline_disabled_by_default():
    """``par5_deadline=None`` (défaut) : comportement byte-identique, aucune
    nouvelle clé de violation possible même avec un par5 tardif."""
    bank = generate_bank(1, GenerationParams.eighteen())
    back = _placed_nine(bank, [4, 4, 4, 4, 4, 4, 5, 5, 4], order_offset=9)
    rules = ValidationRules(width=4000.0, height=4000.0)
    clubhouse = (2000.0, 2000.0)
    violations = cs._course_violations((), back, rules, clubhouse, 4000.0,
                                       par5_bounds=(2, 2))
    assert not any(v.endswith("par5_deadline") for v in violations)
