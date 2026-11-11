"""Scène des chemins : obstacles, extrémités des liaisons, eau effective.

Réseau minimal (``routing.links``, 20 liaisons) : green N → départ N+1, et
clubhouse → départ 1, green 9 → clubhouse, clubhouse → départ 10, green 18 →
clubhouse. Surfaces d'extrémité : le green de départ
(``features.green.outline``, ou le contour du green double
``routing.green_pairs`` qui le contient) et la boîte de départ ARRIÈRE du
trou suivant (``features.tees[0]``) ; côté clubhouse, le parvis s'il est
posé (``plaza``), sinon le point ``routing.clubhouse``. ``LinkEnds.start``
et ``end`` sont les deux points les plus proches entre ces surfaces. Les
boîtes avancées ne sont pas desservies (elles restent des obstacles).

Obstacles : greens (et greens doubles, qui remplacent leurs deux greens),
boîtes de départ, bunkers (``bunkers.items[].cells``), parvis, et eau
EFFECTIVE : eau brute (``course_input_from_json`` → ``WaterMask``) moins les
cellules remontées des greens et boîtes insulaires (``raised_cells``).
Greens et boîtes : cases qui partagent une aire avec le contour
(``footprint_cells``).

Portage fidèle de l'étude (``scene_from_json`` avec parvis, sans sorties
réparties).
"""

from __future__ import annotations

from dataclasses import dataclass, field
import math
from typing import Any, Mapping

import numpy as np

from golfgen.dressing.from_json import course_input_from_json
from golfgen.dressing.paths.bridge_rule import BridgeRule
from golfgen.dressing.paths.fairway_rule import FairwayRule
from golfgen.dressing.paths.geometry import Point, center_mask, closest_points, outline_polygon
from golfgen.dressing.paths.plaza import PLAZA_REF, Plaza, place_plaza
from golfgen.dressing.water import footprint_cells, raised_cells

PATH_WIDTH = {"links": 2.0, "parkland": 3.0}   # blocs, selon ``metadata.style``


@dataclass(frozen=True, eq=False)
class Obstacle:
    """Obstacle : ``kind`` (``green``, ``tee``, ``bunker``, ``plaza``), ``ref``
    lisible et unique, cases ``(k, 2)`` (ix, iy) et contour (greens, boîtes,
    parvis)."""
    kind: str
    ref: str
    cells: np.ndarray
    polygon: np.ndarray | None = None

    @property
    def bbox(self) -> tuple[float, float, float, float]:
        if self.polygon is not None:
            lo, hi = self.polygon.min(axis=0), self.polygon.max(axis=0)
        else:
            lo, hi = self.cells.min(axis=0).astype(float), self.cells.max(axis=0) + 1.0
        return float(lo[0]), float(lo[1]), float(hi[0]), float(hi[1])


@dataclass(frozen=True)
class LinkEnds:
    """Liaison du réseau : points les plus proches des deux extrémités
    (blocs), refs exemptées (``exclude`` : surface de départ et boîte
    d'arrivée) et surfaces d'extrémité (ref et contour ; ``None`` :
    extrémité ponctuelle, clubhouse sans parvis)."""
    index: int
    src: int | str
    dst: int | str
    start: Point
    end: Point
    exclude: frozenset[str] = frozenset()
    src_ref: str | None = None
    dst_ref: str | None = None
    src_poly: np.ndarray | None = field(default=None, compare=False, repr=False)
    dst_poly: np.ndarray | None = field(default=None, compare=False, repr=False)

    @property
    def surfaces(self) -> list[np.ndarray]:
        return [p for p in (self.src_poly, self.dst_poly) if p is not None]

    @property
    def direct(self) -> float:
        return math.dist(self.start, self.end)


@dataclass(frozen=True, eq=False)
class Scene:
    """Ce que lit le tracé : grilles ``(h, w)`` indexées ``[y, x]``."""
    width: int
    height: int
    path_width: float
    relief: np.ndarray        # float, blocs
    water: np.ndarray         # bool, eau effective
    fairway: np.ndarray       # bool, centre de case dans un morceau de fairway
    obstacles: tuple[Obstacle, ...]
    links: tuple[LinkEnds, ...] = ()
    style: str = "links"
    seed: int = 0             # seed u64 du parcours (virages)
    plaza: Plaza | None = None            # parvis posé, ``None`` sans parvis
    plaza_report: dict | None = None      # bilan de la pose (même sans parvis posé)
    fairway_rule: FairwayRule = FairwayRule()   # traitement du fairway (défaut : la correction)
    bridge_rule: BridgeRule = BridgeRule()      # règle des ponts (défaut : gain 25 %)


def surfaces_meet(scene: Scene, link: LinkEnds) -> bool:
    """Les empreintes des deux surfaces de la liaison se chevauchent ou se
    touchent par une face (un contact par un coin seul ne compte pas) ;
    ``False`` si un bout n'a pas de surface."""
    def footprint(ref: str | None) -> set[tuple[int, int]]:
        cells = next((o.cells for o in scene.obstacles if o.ref == ref), None)
        return set() if ref is None or cells is None else {(int(x), int(z)) for x, z in cells}

    first, second = footprint(link.src_ref), footprint(link.dst_ref)
    return any((x + dx, z + dz) in second
               for x, z in first for dx, dz in ((0, 0), (1, 0), (-1, 0), (0, 1), (0, -1)))


def scene_from_json(data: Mapping[str, Any], fairway_rule: FairwayRule = FairwayRule(),
                    bridge_rule: BridgeRule = BridgeRule()) -> Scene:
    """Scène d'un JSON 3.2 (voir le docstring du module), parvis du clubhouse
    posé (``place_plaza``) et extrémité de ses liaisons ; ``fairway_rule`` :
    traitement du fairway par les chemins (``fairway_rule``) ; ``bridge_rule``
    : règle des ponts (``bridge_rule``)."""
    course = course_input_from_json(data)
    routing = data["routing"]
    width, height = int(data["terrain"]["width"]), int(data["terrain"]["height"])
    style = data["metadata"].get("style") or "links"
    holes = {hole["id"]: hole for hole in routing["holes"]}
    obstacles: list[Obstacle] = []
    surface: dict[int, tuple[str, np.ndarray]] = {}     # green de départ de chaque trou
    for pair in routing.get("green_pairs") or []:
        i, j = pair["holes"]
        poly = outline_polygon(pair["outline"])
        ref = f"green_pair {i}/{j}"
        obstacles.append(Obstacle("green", ref, footprint_cells(poly, width, height), poly))
        surface[i] = surface[j] = (ref, poly)
    for order in sorted(holes):
        features = holes[order].get("features") or {}
        if order not in surface:
            poly = outline_polygon(features["green"]["outline"])
            ref = f"green {order}"
            obstacles.append(Obstacle("green", ref, footprint_cells(poly, width, height), poly))
            surface[order] = (ref, poly)
        for k, tee in enumerate(features.get("tees") or []):
            poly = outline_polygon(tee["outline"])
            obstacles.append(Obstacle("tee", f"tee {order}/{k}",
                                      footprint_cells(poly, width, height), poly))
    for item in (data.get("bunkers") or {}).get("items") or []:
        obstacles.append(Obstacle("bunker", f"bunker {item['hole']}/{item['id']}",
                                  np.asarray(item["cells"], dtype=np.int64).reshape(-1, 2)))

    water = np.array(course.water.water)
    fairway = np.zeros((height, width), dtype=bool)
    for hole in holes.values():
        features = hole.get("features") or {}
        for feature in [features.get("green"), *(features.get("tees") or [])]:
            if feature and feature.get("island"):
                cells = raised_cells(outline_polygon(feature["outline"]), course.water)
                water[cells[:, 1], cells[:, 0]] = False
        for piece in features.get("fairway") or []:
            fairway |= center_mask(outline_polygon(piece["outline"]), width, height)

    club = routing["clubhouse"]
    club_pt = np.array([[club["x"], club["y"]]], dtype=float)
    placed, plaza_report = place_plaza(club, width, height, obstacles, water)
    if placed is not None:
        obstacles.append(Obstacle("plaza", PLAZA_REF, placed.cells, placed.polygon))
    links = []
    for index, link in enumerate(routing["links"]):
        src, dst = link["from"], link["to"]
        src_ref = src_poly = dst_ref = dst_poly = None
        if src == "clubhouse":
            if placed is not None:
                src_ref, src_poly = PLAZA_REF, placed.polygon
        else:
            src_ref, src_poly = surface[src]
        if dst == "clubhouse":
            if placed is not None:
                dst_ref, dst_poly = PLAZA_REF, placed.polygon
        else:
            dst_ref = f"tee {dst}/0"
            dst_poly = outline_polygon(holes[dst]["features"]["tees"][0]["outline"])
        a = club_pt if src_poly is None else src_poly
        b = club_pt if dst_poly is None else dst_poly
        start, end = closest_points(a, b)
        exclude = frozenset(r for r in (src_ref, dst_ref) if r is not None)
        links.append(LinkEnds(index, src, dst, start, end, exclude,
                              src_ref, dst_ref, src_poly, dst_poly))
    return Scene(width=width, height=height, path_width=PATH_WIDTH[style],
                 relief=np.asarray(course.relief, dtype=float), water=water,
                 fairway=fairway, obstacles=tuple(obstacles), links=tuple(links), style=style,
                 seed=int(getattr(course, "seed", 0)), plaza=placed, plaza_report=plaza_report,
                 fairway_rule=fairway_rule, bridge_rule=bridge_rule)


def obstacle_mask(scene: Scene) -> np.ndarray:
    """``(h, w)`` : cases des greens (et greens doubles), de toutes les
    boîtes de départ, des bunkers et du parvis ; l'eau effective est à
    part."""
    mask = np.zeros((scene.height, scene.width), dtype=bool)
    for obstacle in scene.obstacles:
        cells = obstacle.cells
        keep = ((cells[:, 0] >= 0) & (cells[:, 0] < scene.width)
                & (cells[:, 1] >= 0) & (cells[:, 1] < scene.height))
        mask[cells[keep, 1], cells[keep, 0]] = True
    return mask
