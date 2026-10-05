from experiments.bean_paving.bean_bank import BeanTemplate
from experiments.bean_paving.bean_bank import _footprint as _bank_footprint
from experiments.bean_paving.benchmark import _similarity
from experiments.bean_paving.benchmark_course import (
    _fingerprint_beans,
    _largest_parallel_stack,
    _polygon_area,
    _seed_summary,
)
from experiments.bean_paving.course_solver import CourseSolveResult
from experiments.bean_paving.geometry import PlacedBean, Transform, ValidationRules
from experiments.bean_paving.solver import DepthDiagnostics, SearchState, SolveResult, SolverParams


def _bean(bean_id: str, order: int, x: float, par: int = 4) -> PlacedBean:
    """Trou abstrait rectiligne, axe vertical de longueur 60, posé à
    l'abscisse ``x`` — assez pour tester les règles ``shared_rough`` sans
    lancer de recherche."""
    axis = ((0.0, 0.0), (0.0, 60.0))
    width, margin = 10.0, 2.0
    template = BeanTemplate(
        id=bean_id, par=par, target_length=60.0,
        axis=axis, width=width, margin=margin,
        footprint=_bank_footprint(axis, width / 2.0 + margin),
        tee=(0.0, 0.0), green=(0.0, 60.0),
        tee_heading_deg=90.0, green_heading_deg=90.0,
    )
    return PlacedBean(template=template, transform=Transform(x=x, y=0.0), order=order)


def test_polygon_area_square():
    assert _polygon_area(((0, 0), (10, 0), (10, 10), (0, 10))) == 100.0


def test_fingerprint_beans_is_rotation_and_mirror_invariant():
    beans = (_bean("a", 1, 0.0), _bean("b", 2, 30.0))
    forward = _fingerprint_beans(beans)
    assert _similarity(forward, forward) == 1.0
    assert _fingerprint_beans(()) == ()


def test_largest_parallel_stack_counts_side_by_side_component():
    rules = ValidationRules(width=400.0, height=400.0, shared_rough=True)
    # a et b : axes parallèles, 12 blocs d'écart, se chevauchent sur toute
    # la longueur -> une seule pile de 2. c : isolé loin, hors de la pile.
    beans = (_bean("a", 1, 0.0), _bean("b", 2, 12.0), _bean("c", 3, 300.0))
    assert _largest_parallel_stack(beans, rules) == 2


def test_largest_parallel_stack_disabled_without_shared_rough():
    rules = ValidationRules(width=400.0, height=400.0, shared_rough=False)
    beans = (_bean("a", 1, 0.0), _bean("b", 2, 12.0))
    assert _largest_parallel_stack(beans, rules) == 0
    assert _largest_parallel_stack((), rules) is None


def test_largest_parallel_stack_resolves_within_the_loop_up_to_the_full_component():
    # Revue de code : l'ancien ``return len(beans)`` après la boucle était
    # mort (seuil == len(beans) ne peut jamais laisser subsister de
    # violation ``parallel_stack``, voir benchmark_course._largest_parallel_stack).
    # Ce test vérifie que la boucle elle-même résout correctement une pile
    # complète (4 fairways côte à côte) SANS dépendre de ce filet mort.
    rules = ValidationRules(width=400.0, height=400.0, shared_rough=True)
    beans = tuple(_bean(f"s{i}", i, i * 12.0) for i in range(4))
    assert _largest_parallel_stack(beans, rules) == 4


def test_seed_summary_reports_incomplete_back_as_invalid():
    rules = ValidationRules(width=400.0, height=400.0, shared_rough=True)
    front_beans = tuple(_bean(f"front{i}", i + 1, i * 50.0, par=4) for i in range(9))
    front_state = SearchState(placed=front_beans, remaining=(0, 0, 0), score=0.0)
    front_diag = (DepthDiagnostics(depth=1, parents=1, trials=10, accepted=5, kept=5,
                                   dead_ends=0, rejection_counts={"bounds": 3}),)
    front = SolveResult(seed=7, clubhouse=(200.0, 200.0), state=front_state,
                        complete=True, diagnostics=front_diag, params=SolverParams())

    back_state = SearchState(placed=(), remaining=(2, 5, 2), score=0.0)
    back_diag = (DepthDiagnostics(depth=1, parents=1, trials=20, accepted=0, kept=0,
                                  dead_ends=1, rejection_counts={"axis_crossing": 7}),)
    back = SolveResult(seed=7 ^ 0x9E3779B9, clubhouse=(200.0, 200.0), state=back_state,
                       complete=False, diagnostics=back_diag, params=SolverParams())

    result = CourseSolveResult(seed=7, front=front, back=back, complete=False,
                               violations=("back_incomplete",))
    summary = _seed_summary(result, elapsed=1.5, rules=rules)

    assert summary["success"] is False
    assert summary["independent_valid"] is False
    assert summary["front_holes"] == 9
    assert summary["back_holes"] == 0
    assert summary["trials"] == 30
    assert summary["rejection_counts"] == {"axis_crossing": 7, "bounds": 3}


def _far_bean(bean_id: str, order: int, distance: float, par: int = 4) -> PlacedBean:
    """Trou abstrait minuscule dont le tee est exactement à ``distance`` du
    clubhouse ``(200, 200)`` (``rules.clubhouse`` pour ``width=height=400``),
    le long de +x — pour tester les plafonds ``clubhouse_max`` par nine sans
    lancer de recherche."""
    axis = ((0.0, 0.0), (1.0, 0.0))
    width, margin = 10.0, 2.0
    template = BeanTemplate(
        id=bean_id, par=par, target_length=1.0, axis=axis, width=width, margin=margin,
        footprint=_bank_footprint(axis, width / 2.0 + margin), tee=(0.0, 0.0), green=(1.0, 0.0),
        tee_heading_deg=0.0, green_heading_deg=0.0,
    )
    return PlacedBean(template=template, transform=Transform(x=200.0 + distance, y=200.0), order=order)


def test_seed_summary_uses_each_nines_own_clubhouse_max_for_independent_validation():
    # Décision utilisateur (étape 1) : le back peut avoir un plafond
    # (``clubhouse_max``) distinct du front. ``_seed_summary`` doit lire le
    # plafond RÉELLEMENT utilisé par chaque nine (``result.*.params``),
    # jamais un défaut partagé câblé en dur.
    rules = ValidationRules(width=400.0, height=400.0, shared_rough=True)
    front_state = SearchState(placed=(), remaining=(0, 0, 0), score=0.0)
    front = SolveResult(seed=7, clubhouse=(200.0, 200.0), state=front_state,
                        complete=True, diagnostics=(), params=SolverParams(clubhouse_max=50.0))

    # Tee 10 et green 18 à ~79-80 du clubhouse : > plafond front (50),
    # <= plafond back relevé (100).
    back_beans = (_far_bean("back_tee", 10, 79.0), _far_bean("back_green", 18, 80.0))
    back_state = SearchState(placed=back_beans, remaining=(0, 0, 0), score=0.0)
    back = SolveResult(seed=7 ^ 0x9E3779B9, clubhouse=(200.0, 200.0), state=back_state,
                       complete=True, diagnostics=(), params=SolverParams(clubhouse_max=100.0))

    result = CourseSolveResult(seed=7, front=front, back=back, complete=True, violations=())
    summary = _seed_summary(result, elapsed=0.1, rules=rules)

    assert summary["front_clubhouse_max"] == 50.0
    assert summary["back_clubhouse_max"] == 100.0
    assert summary["back_start_distance"] == 79.0
    assert summary["back_return_distance"] == 81.0  # tee du 2e haricot (x=1) + distance 80
    assert "back_start" not in summary["independent_violations"]
    assert "back_return" not in summary["independent_violations"]

    # Même géométrie, mais plafond back laissé au défaut historique (50) :
    # la même distance devient une violation, preuve que le plafond relevé
    # est bien ce qui change le résultat, pas autre chose.
    back_default = SolveResult(seed=back.seed, clubhouse=back.clubhouse, state=back_state,
                               complete=True, diagnostics=(), params=SolverParams())
    result_default = CourseSolveResult(seed=7, front=front, back=back_default,
                                       complete=True, violations=())
    summary_default = _seed_summary(result_default, elapsed=0.1, rules=rules)
    assert summary_default["back_clubhouse_max"] == 50.0
    assert "back_start" in summary_default["independent_violations"]
    assert "back_return" in summary_default["independent_violations"]
