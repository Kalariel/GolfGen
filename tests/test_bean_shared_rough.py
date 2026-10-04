"""Jeu de règles "rough partagé" (``ValidationRules.shared_rough``).

Chaque test isole une seule règle pour qu'elle ait au moins un cas qui
échouerait sans elle (discipline PLAN.md, étape 2). Voir
EXPERIMENT_18_ROUGH.md pour le contexte et les runs seed 42.
"""

from __future__ import annotations

import pytest

from experiments.bean_paving.bean_bank import BeanTemplate, _footprint
from experiments.bean_paving.geometry import PlacedBean, Transform, ValidationRules, validate


def bean(name, axis=((0.0, 0.0), (60.0, 0.0)), width=10.0, margin=5.0):
    axis = tuple(axis)
    return BeanTemplate(name, 4, 60.0, axis, width, margin,
                        _footprint(axis, width / 2 + margin), axis[0], axis[-1], 0.0, 0.0)


def thin(name, axis=((0.0, 0.0), (100.0, 0.0))):
    # margin=0 : rough == cœur, isole la règle antiparallèle/parallel_stack
    # de l'écart fairway.
    return bean(name, axis, width=4.0, margin=0.0)


def kinds(placed, rules, check_links=False):
    return {item.kind for item in validate(placed, rules, check_links=check_links)}


def test_default_is_legacy_behavior():
    """``shared_rough`` est désactivé par défaut : comportement inchangé."""
    assert ValidationRules().shared_rough is False
    placed = [PlacedBean(bean("a"), Transform(20, 50), 1),
              PlacedBean(bean("b"), Transform(20, 70), 2)]
    assert "footprint_collision" in kinds(placed, ValidationRules())
    assert "fairway_gap" not in kinds(placed, ValidationRules())


def test_rough_overlap_is_accepted_when_fairway_gap_holds():
    rules = ValidationRules(shared_rough=True)
    placed = [PlacedBean(bean("a"), Transform(20, 50), 1),
              PlacedBean(bean("b"), Transform(20, 66), 2)]  # D=16 : rough overlap, core gap 6
    assert not kinds(placed, rules)


def test_fairway_gap_below_minimum_is_rejected():
    rules = ValidationRules(shared_rough=True)
    placed = [PlacedBean(bean("a"), Transform(20, 50), 1),
              PlacedBean(bean("b"), Transform(20, 63), 2)]  # D=13 : core gap 3 < 5
    assert "fairway_gap" in kinds(placed, rules)
    assert "footprint_collision" not in kinds(placed, rules)  # la règle n'existe plus en mode partagé


def test_core_one_block_from_edge_with_rough_outside_is_accepted():
    rules = ValidationRules(width=200, height=110, shared_rough=True)
    # tee en x=6 : cœur (rayon 5) commence à x=1, rough (rayon 10) à x=-4.
    placed = [PlacedBean(bean("a"), Transform(6, 50), 1)]
    assert not kinds(placed, rules)


def test_core_touching_edge_is_rejected():
    rules = ValidationRules(width=200, height=110, shared_rough=True)
    # tee en x=5.5 : cœur commence à x=0.5, à moins de edge_min=1 du bord.
    placed = [PlacedBean(bean("a"), Transform(5.5, 50), 1)]
    assert "bounds" in kinds(placed, rules)


def test_side_by_side_antiparallel_accepted_in_shared_mode():
    placed = [PlacedBean(thin("a"), Transform(20, 50), 1),
              PlacedBean(thin("b"), Transform(120, 72, 180), 2)]
    assert not kinds(placed, ValidationRules(shared_rough=True))


def test_side_by_side_antiparallel_still_rejected_in_legacy_mode():
    placed = [PlacedBean(thin("a"), Transform(20, 50), 1),
              PlacedBean(thin("b"), Transform(120, 72, 180), 2)]
    assert "antiparallel" in kinds(placed, ValidationRules())


def _stack(n: int, orders: list[int], gap: float = 16.0) -> list[PlacedBean]:
    beans = []
    y = 50.0
    for i in range(n):
        beans.append(PlacedBean(bean(f"b{i}"), Transform(20, y, 0), orders[i]))
        y += gap
    return beans


def test_parallel_stack_of_three_is_accepted():
    rules = ValidationRules(shared_rough=True)
    # ordre de jeu non consécutif : la composante ne dépend que des id.
    placed = _stack(3, [1, 7, 4])
    assert not kinds(placed, rules)


def test_parallel_stack_of_four_is_rejected_with_non_consecutive_order():
    rules = ValidationRules(shared_rough=True)
    placed = _stack(4, [1, 7, 4, 2])
    violations = validate(placed, rules, check_links=False)
    kinds_found = {item.kind for item in violations}
    assert "parallel_stack" in kinds_found
    stack_violation = next(item for item in violations if item.kind == "parallel_stack")
    assert set(stack_violation.beans) == {"b0", "b1", "b2", "b3"}


def test_parallel_stack_disabled_when_max_is_none():
    rules = ValidationRules(shared_rough=True, max_parallel_stack=None)
    placed = _stack(4, [1, 7, 4, 2])
    assert "parallel_stack" not in kinds(placed, rules)


@pytest.mark.parametrize("n,expect_rejected", [(3, False), (4, True)])
def test_parallel_stack_threshold_is_exclusive_on_size(n, expect_rejected):
    rules = ValidationRules(shared_rough=True)
    placed = _stack(n, list(range(1, n + 1)))
    assert ("parallel_stack" in kinds(placed, rules)) is expect_rejected


# -- Exclusion clubhouse (EXPERIMENT_18_HALFPLANE.md, point A) --------------
# Carte 100x100 : clubhouse = (50, 50) (``ValidationRules.clubhouse``).

def test_clubhouse_exclusion_rejects_core_intrusion():
    rules = ValidationRules(width=100, height=100, shared_rough=True)
    # Axe horizontal passant exactement par le clubhouse : le cœur (demi-
    # largeur 5) couvre largement le disque d'exclusion (rayon 10 par défaut).
    placed = [PlacedBean(bean("a", axis=((20.0, 50.0), (80.0, 50.0)), width=10.0, margin=5.0),
                         Transform(0, 0), 1)]
    assert "clubhouse_clear" in kinds(placed, rules)


def test_clubhouse_exclusion_accepts_rough_only_intrusion():
    rules = ValidationRules(width=100, height=100, shared_rough=True)
    # Axe à 17 blocs du clubhouse : écart cœur = 17 - 5 = 12 >= 10 (accepté),
    # écart rough = 17 - 10 = 7 < 10 (le rough, lui, intrude le disque).
    placed = [PlacedBean(bean("a", axis=((20.0, 67.0), (80.0, 67.0)), width=10.0, margin=5.0),
                         Transform(0, 0), 1)]
    assert "clubhouse_clear" not in kinds(placed, rules)


def test_clubhouse_exclusion_disabled_in_legacy_mode():
    """Mode historique (``shared_rough=False``) : comportement inchangé,
    aucune nouvelle violation même quand le cœur couvre le clubhouse."""
    rules = ValidationRules(width=100, height=100, shared_rough=False)
    placed = [PlacedBean(bean("a", axis=((20.0, 50.0), (80.0, 50.0)), width=10.0, margin=5.0),
                         Transform(0, 0), 1)]
    assert "clubhouse_clear" not in kinds(placed, rules)


def test_clubhouse_exclusion_disabled_when_radius_is_none():
    rules = ValidationRules(width=100, height=100, shared_rough=True, clubhouse_clear_radius=None)
    placed = [PlacedBean(bean("a", axis=((20.0, 50.0), (80.0, 50.0)), width=10.0, margin=5.0),
                         Transform(0, 0), 1)]
    assert "clubhouse_clear" not in kinds(placed, rules)
