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
