from experiments.bean_paving.bean_bank import BeanTemplate, _footprint
from experiments.bean_paving.freespace import (
    build_grid, clearance_map, corridor_width, freespace_penalty, reachable_area, analyze,
)
from experiments.bean_paving.geometry import PlacedBean, Transform, ValidationRules


def _wall_bean(name, axis, width):
    return BeanTemplate(name, 4, 10.0, axis, width, 0.0, _footprint(axis, width / 2.0),
                        axis[0], axis[-1], 0.0, 0.0, allow_mirror=False)


def _rules(size=100.0):
    return ValidationRules(width=size, height=size)


def test_flood_fill_reaches_whole_open_map_without_obstacles():
    rules = _rules(100.0)
    grid = build_grid((), rules, cell_size=5.0)
    start = grid.cell_of((50.0, 50.0))
    reachable = reachable_area(grid, start)
    assert len(reachable) == grid.cols * grid.rows


def test_flood_fill_does_not_cross_a_closed_wall_ring():
    rules = _rules(100.0)
    # Anneau fermé de segments formant un mur autour du clubhouse (cellule
    # centrale isolée du reste de la carte).
    ring_points = [(40.0, 40.0), (60.0, 40.0), (60.0, 60.0), (40.0, 60.0), (40.0, 40.0)]
    walls = []
    for index, (a, b) in enumerate(zip(ring_points, ring_points[1:])):
        walls.append(PlacedBean(_wall_bean(f"wall{index}", (a, b), 6.0), Transform(0.0, 0.0), index))
    grid = build_grid(walls, rules, cell_size=5.0)
    start = grid.cell_of((50.0, 50.0))
    reachable = reachable_area(grid, start)
    outside_cell = grid.cell_of((5.0, 5.0))
    assert outside_cell not in reachable
    assert len(reachable) < grid.cols * grid.rows


def test_corridor_width_is_smaller_in_a_pinched_passage_than_in_open_space():
    rules = _rules(120.0)
    open_grid = build_grid((), rules, cell_size=5.0)
    open_clearances = clearance_map(open_grid)
    open_width = corridor_width(open_grid, open_clearances,
                                open_grid.cell_of((10.0, 60.0)), open_grid.cell_of((110.0, 60.0)))

    # Deux murs qui se referment presque, laissant un étroit goulot au centre.
    north = _wall_bean("north", ((60.0, 0.0), (60.0, 56.0)), 4.0)
    south = _wall_bean("south", ((60.0, 64.0), (60.0, 120.0)), 4.0)
    pinched = (PlacedBean(north, Transform(0.0, 0.0), 0), PlacedBean(south, Transform(0.0, 0.0), 1))
    pinched_grid = build_grid(pinched, rules, cell_size=5.0)
    pinched_clearances = clearance_map(pinched_grid)
    pinched_width = corridor_width(pinched_grid, pinched_clearances,
                                   pinched_grid.cell_of((10.0, 60.0)), pinched_grid.cell_of((110.0, 60.0)))

    assert pinched_width < open_width


def test_corridor_width_is_zero_when_no_path_exists():
    rules = _rules(100.0)
    wall = _wall_bean("wall", ((50.0, 0.0), (50.0, 100.0)), 6.0)
    grid = build_grid((PlacedBean(wall, Transform(0.0, 0.0), 0),), rules, cell_size=5.0)
    clearances = clearance_map(grid)
    width = corridor_width(grid, clearances, grid.cell_of((10.0, 50.0)), grid.cell_of((90.0, 50.0)))
    assert width == 0.0


def test_freespace_penalty_increases_when_corridor_narrows():
    report_open = analyze(
        {"front": (PlacedBean(_wall_bean("f", ((10.0, 10.0), (30.0, 10.0)), 10.0),
                              Transform(0.0, 0.0), 0),)},
        clubhouse=(50.0, 50.0), rules=_rules(100.0),
    )
    narrow_widths = {"front": 2.0}
    wide_widths = {"front": 40.0}
    narrow = report_open.__class__(report_open.reachable_cells, report_open.total_free_cells, narrow_widths)
    wide = report_open.__class__(report_open.reachable_cells, report_open.total_free_cells, wide_widths)
    assert freespace_penalty(narrow) > freespace_penalty(wide)
