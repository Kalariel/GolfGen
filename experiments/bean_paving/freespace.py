"""Heuristique grossière d'espace libre — jamais un oracle géométrique.

Grille de cellules ~5 blocs construite à partir des empreintes déjà posées,
remplissage (flood-fill) depuis la cellule du clubhouse pour l'aire
accessible, et une mesure de largeur de corridor (transformée de distance +
chemin au goulot le plus large) entre le clubhouse et la frontière de chaque
nine (son dernier green). Ces signaux alimentent uniquement le score du beam
conjoint (`joint_solver.py`) : ils ne remplacent et n'exemptent jamais une
règle dure de `geometry.validate`.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
import heapq
import math
from typing import Iterable

from experiments.bean_paving.bean_bank import Point
from experiments.bean_paving.geometry import PlacedBean, ValidationRules, polygons_intersect

Cell = tuple[int, int]

CELL_SIZE = 5.0


@dataclass(frozen=True)
class FreespaceGrid:
    rules: ValidationRules
    cell_size: float
    cols: int
    rows: int
    occupied: frozenset[Cell]

    def cell_of(self, point: Point) -> Cell:
        return (int(point[0] // self.cell_size), int(point[1] // self.cell_size))

    def in_bounds(self, cell: Cell) -> bool:
        cx, cy = cell
        return 0 <= cx < self.cols and 0 <= cy < self.rows

    @property
    def total_cells(self) -> int:
        return self.cols * self.rows


def _cell_polygon(cx: int, cy: int, cell_size: float) -> tuple[Point, ...]:
    x0, y0 = cx * cell_size, cy * cell_size
    x1, y1 = x0 + cell_size, y0 + cell_size
    return ((x0, y0), (x1, y0), (x1, y1), (x0, y1))


def build_grid(placed: Iterable[PlacedBean], rules: ValidationRules | None = None,
               cell_size: float = CELL_SIZE) -> FreespaceGrid:
    """Marque occupée toute cellule touchant une empreinte posée.

    Ne scrute que la boîte englobante de chaque empreinte (pas la carte
    entière) pour rester bon marché quand on l'appelle sur des survivants de
    beam.
    """
    rules = rules or ValidationRules()
    cols = max(1, math.ceil(rules.width / cell_size))
    rows = max(1, math.ceil(rules.height / cell_size))
    occupied: set[Cell] = set()
    for bean in placed:
        footprint = bean.footprint
        min_x = max(0, int(min(p[0] for p in footprint) // cell_size))
        max_x = min(cols - 1, int(max(p[0] for p in footprint) // cell_size))
        min_y = max(0, int(min(p[1] for p in footprint) // cell_size))
        max_y = min(rows - 1, int(max(p[1] for p in footprint) // cell_size))
        for cx in range(min_x, max_x + 1):
            for cy in range(min_y, max_y + 1):
                if (cx, cy) in occupied:
                    continue
                if polygons_intersect(_cell_polygon(cx, cy, cell_size), footprint):
                    occupied.add((cx, cy))
    return FreespaceGrid(rules, cell_size, cols, rows, frozenset(occupied))


def reachable_area(grid: FreespaceGrid, start: Cell) -> frozenset[Cell]:
    """Flood-fill 4-connexe des cellules libres accessibles depuis ``start``."""
    if not grid.in_bounds(start) or start in grid.occupied:
        return frozenset()
    seen = {start}
    queue: deque[Cell] = deque([start])
    while queue:
        cx, cy = queue.popleft()
        for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            neighbor = (cx + dx, cy + dy)
            if (grid.in_bounds(neighbor) and neighbor not in grid.occupied
                    and neighbor not in seen):
                seen.add(neighbor)
                queue.append(neighbor)
    return frozenset(seen)


def clearance_map(grid: FreespaceGrid) -> dict[Cell, float]:
    """Distance (en cellules) à l'obstacle le plus proche, par propagation
    multi-source depuis toutes les cellules occupées (BFS à poids unitaire,
    équivalent à une transformée de distance sur grille entière)."""
    distances: dict[Cell, float] = {}
    queue: deque[Cell] = deque()
    for cx in range(grid.cols):
        for cy in range(grid.rows):
            if (cx, cy) in grid.occupied:
                distances[(cx, cy)] = 0.0
                queue.append((cx, cy))
    while queue:
        cx, cy = queue.popleft()
        d = distances[(cx, cy)]
        for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            neighbor = (cx + dx, cy + dy)
            if grid.in_bounds(neighbor) and neighbor not in distances:
                distances[neighbor] = d + 1.0
                queue.append(neighbor)
    sentinel = float(max(grid.cols, grid.rows))
    for cx in range(grid.cols):
        for cy in range(grid.rows):
            distances.setdefault((cx, cy), sentinel)
    return distances


def corridor_width(grid: FreespaceGrid, clearances: dict[Cell, float],
                    start: Cell, goal: Cell) -> float:
    """Largeur du corridor le plus large entre ``start`` et ``goal`` : le
    chemin qui maximise la clairance minimale traversée (« widest path »),
    via une variante de Dijkstra en max-min sur une grille 8-connexe.
    Retourne 0.0 si aucun chemin n'existe.
    """
    if not grid.in_bounds(start) or not grid.in_bounds(goal):
        return 0.0
    if start in grid.occupied or goal in grid.occupied:
        return 0.0
    best: dict[Cell, float] = {start: clearances.get(start, 0.0)}
    heap: list[tuple[float, Cell]] = [(-best[start], start)]
    visited: set[Cell] = set()
    while heap:
        neg_value, node = heapq.heappop(heap)
        value = -neg_value
        if node in visited:
            continue
        visited.add(node)
        if node == goal:
            return value
        cx, cy = node
        for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1),
                       (1, 1), (1, -1), (-1, 1), (-1, -1)):
            neighbor = (cx + dx, cy + dy)
            if (not grid.in_bounds(neighbor) or neighbor in grid.occupied
                    or neighbor in visited):
                continue
            candidate = min(value, clearances.get(neighbor, 0.0))
            if candidate > best.get(neighbor, -1.0):
                best[neighbor] = candidate
                heapq.heappush(heap, (-candidate, neighbor))
    return 0.0


@dataclass(frozen=True)
class FreespaceReport:
    reachable_cells: int
    total_free_cells: int
    corridor_widths: dict[str, float]  # blocs, par label de nine ("front"/"back")


def analyze(nines: dict[str, tuple[PlacedBean, ...]], clubhouse: Point,
            rules: ValidationRules | None = None, cell_size: float = CELL_SIZE) -> FreespaceReport:
    """Rapport d'espace libre pour un ensemble de nines déjà posés.

    ``nines`` associe un label (``"front"``, ``"back"``...) à ses haricots
    placés ; la grille d'occupation couvre toutes les empreintes fournies.
    """
    rules = rules or ValidationRules()
    all_placed = tuple(bean for beans in nines.values() for bean in beans)
    grid = build_grid(all_placed, rules, cell_size)
    clearances = clearance_map(grid)
    start = grid.cell_of(clubhouse)
    reachable = reachable_area(grid, start)
    total_free = grid.total_cells - len(grid.occupied)
    widths: dict[str, float] = {}
    for label, beans in nines.items():
        if not beans:
            continue
        goal = grid.cell_of(beans[-1].green)
        widths[label] = corridor_width(grid, clearances, start, goal) * cell_size
    return FreespaceReport(len(reachable), total_free, widths)


def freespace_penalty(report: FreespaceReport, *, min_corridor: float = 15.0,
                       weight: float = 1.0) -> float:
    """Pénalité croissante quand un corridor se resserre ou que l'aire
    accessible depuis le clubhouse se réduit par rapport à l'espace libre
    total. Un score, jamais un rejet : les contraintes dures restent dans
    ``geometry.validate``.
    """
    penalty = 0.0
    for width in report.corridor_widths.values():
        if width < min_corridor:
            penalty += (min_corridor - width) * weight
    if report.total_free_cells > 0:
        starved_ratio = 1.0 - report.reachable_cells / report.total_free_cells
        penalty += max(0.0, starved_ratio) * weight * 20.0
    return penalty
