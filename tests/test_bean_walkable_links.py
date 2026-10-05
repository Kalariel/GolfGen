"""Règle « liens praticables » (``ValidationRules.walkable_links``) et
longueur de liaison green->tee élargie à 80 blocs (PLAN.md ligne 6).

Chaque test isole une seule facette (discipline PLAN.md, étape 2) : voir
``experiments/bean_paving/run_exp_walkable_links.py`` pour le contexte et le
run seeds 1-5.
"""

from __future__ import annotations

import math

import pytest

from experiments.bean_paving.bean_bank import BeanTemplate, _footprint
from experiments.bean_paving.geometry import PlacedBean, Transform, ValidationRules, validate
from experiments.bean_paving.solver import SearchState, SolverParams, _raw_transforms


def bean(name, axis=((0.0, 0.0), (60.0, 0.0)), width=10.0, margin=5.0):
    axis = tuple(axis)
    return BeanTemplate(name, 4, 60.0, axis, width, margin,
                        _footprint(axis, width / 2 + margin), axis[0], axis[-1], 0.0, 0.0)


def kinds(placed, rules, check_links=False):
    return {item.kind for item in validate(placed, rules, check_links=check_links)}


def test_defaults_are_byte_identical():
    rules = ValidationRules()
    assert rules.walkable_links is False
    assert rules.link_min == 12.0
    assert rules.link_max == 45.0
    assert SolverParams().link_lengths == (24.0, 32.0, 40.0)
    # Même géométrie que ``test_link_crossing_other_core_is_rejected`` :
    # sans l'opt-in, "link_blocked" n'apparaît jamais, même si la
    # géométrie (non testée ici) s'y prêterait.
    hole1 = PlacedBean(bean("hole1", width=10, margin=5), Transform(100, 60, 0), 1)
    blocker = PlacedBean(bean("blocker", ((0.0, 0.0), (40.0, 0.0)), width=10, margin=0), Transform(80, 80, 0), 2)
    assert "link_blocked" not in kinds([hole1, blocker], rules)


def test_link_crossing_other_core_is_rejected():
    # clubhouse = (100, 100) (carte 200x200) ; hole1 (order 1) a son tee en
    # (100, 60) -> liaison clubhouse->tee1 verticale x=100, y de 60 à 100.
    # ``blocker`` est un AUTRE trou (order 2, pas propriétaire de la
    # liaison) dont le cœur (rectangle local x[-5,45] y[-5,5], radius=5,
    # margin=0) recouvre x=100 y=80 une fois transformé -- la liaison le
    # traverse de part en part.
    rules = ValidationRules(width=200.0, height=200.0, walkable_links=True)
    hole1 = PlacedBean(bean("hole1", width=10, margin=5), Transform(100, 60, 0), 1)
    blocker = PlacedBean(bean("blocker", ((0.0, 0.0), (40.0, 0.0)), width=10, margin=0), Transform(80, 80, 0), 2)
    assert "link_blocked" in kinds([hole1, blocker], rules)


def test_link_crossing_only_rough_is_accepted():
    # Même liaison clubhouse->tee1 que ci-dessus. ``blocker`` est décalé
    # (width=4, margin=8) : son cœur (rectangle local x[-2,42] y[-2,2],
    # radius=2) transformé en (105, 80) donne x[103,147] -- la liaison
    # (x=100) ne le touche plus -- mais son ROUGH (radius=10, rectangle
    # local x[-10,50] y[-10,10] -> x[95,155] y[70,90]) le traverse encore :
    # le rough reste praticable, donc aucune violation.
    rules = ValidationRules(width=200.0, height=200.0, walkable_links=True)
    hole1 = PlacedBean(bean("hole1", width=10, margin=5), Transform(100, 60, 0), 1)
    blocker = PlacedBean(bean("blocker", ((0.0, 0.0), (40.0, 0.0)), width=4, margin=8), Transform(105, 80, 0), 2)
    assert "link_blocked" not in kinds([hole1, blocker], rules)


def test_new_hole_cutting_established_clubhouse_tee10_link_is_rejected():
    # Même géométrie de croisement que le premier test, mais la liaison
    # établie est clubhouse->tee10 (order 10, pas tee1) : un nouveau trou
    # (order 99, poitns quelconque hors 1/9/10/18) qui coupe cette liaison
    # doit être rejeté exactement comme pour tee1.
    rules = ValidationRules(width=200.0, height=200.0, walkable_links=True)
    tee10 = PlacedBean(bean("hole10", width=10, margin=5), Transform(100, 60, 0), 10)
    blocker = PlacedBean(bean("blocker", ((0.0, 0.0), (40.0, 0.0)), width=10, margin=0), Transform(80, 80, 0), 99)
    assert "link_blocked" in kinds([tee10, blocker], rules)


def test_own_two_holes_may_touch_their_shared_link_endpoint():
    # La liaison green1->tee2 touche forcément le cœur des DEUX trous
    # qu'elle relie à ses extrémités (le tee/green est sur leur propre
    # axe) -- ce n'est jamais une violation puisque ces deux trous sont
    # exclus du test (seuls les AUTRES trous comptent).
    rules = ValidationRules(width=200.0, height=200.0, walkable_links=True)
    first = PlacedBean(bean("a", ((0.0, 0.0), (40.0, 0.0))), Transform(20, 60, 0), 1)
    second = PlacedBean(bean("b", ((0.0, 0.0), (40.0, 0.0))), Transform(80, 60, 0), 2)
    assert "link_blocked" not in kinds([first, second], rules)


@pytest.mark.parametrize("link_max, distance, expected", [
    (45.0, 45.0, False), (45.0, 45.1, True),
    (80.0, 80.0, False), (80.0, 80.1, True),
])
def test_link_length_range_extended_to_80(link_max, distance, expected):
    rules = ValidationRules(link_max=link_max)
    first = bean("a", ((0.0, 0.0), (60.0, 0.0)), width=2, margin=0)
    second = bean("b", ((0.0, 0.0), (40.0, 0.0)), width=2, margin=0)
    placed = [PlacedBean(first, Transform(20, 40), 1),
              PlacedBean(second, Transform(80 + distance, 40), 2)]
    assert ("link_distance" in kinds(placed, rules, check_links=True)) is expected


def test_raw_transforms_generates_tee_candidates_up_to_80_when_configured():
    previous = PlacedBean(bean("prev"), Transform(0, 0, 0), 1)
    state = SearchState((previous,), (0, 0, 0), 0.0)
    params = SolverParams(link_lengths=(24.0, 32.0, 40.0, 55.0, 65.0, 80.0))
    distances = {round(math.dist(previous.green, (t.x, t.y)), 3)
                 for t in _raw_transforms(bean("next"), state, (999.0, 999.0), params)}
    assert 80.0 in distances
    assert max(distances) == pytest.approx(80.0)
