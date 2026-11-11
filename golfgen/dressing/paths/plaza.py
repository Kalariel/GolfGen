"""Parvis du clubhouse, sans portes.

Un carré de ``PLAZA_SIZE`` (7) blocs devant le clubhouse, côté intérieur de
la carte (le clubhouse est sur un bord, ``routing.clubhouse.edge`` ; à
défaut, le bord le plus proche) : son côté extérieur passe par le
clubhouse, il est centré sur lui le long du bord. Il ne doit chevaucher ni
green, ni boîte de départ, ni bunker, ni eau effective, et en reste à
``PLAZA_CLEAR`` case au moins (pas même un contact par une face ou un coin :
sinon une liaison vers une boîte collée deviendrait triviale et le parvis se
fondrait dans la boîte). Un parvis collé au bord de la carte est accepté.
En cas de conflit, il est d'abord DÉCALÉ (le long du bord de
``±PLAZA_MAX_SHIFT`` blocs et vers l'intérieur d'au plus autant, le plus
petit décalage d'abord), puis RÉDUIT (``PLAZA_SIZES``, jusqu'à 3) ; sinon
pas de parvis et les liaisons du clubhouse gardent son point.

Le parvis posé est la surface d'extrémité commune des liaisons du clubhouse
(départ ou arrivée glissants sur TOUT son bord, comme un green : les sorties
réparties de l'étude, r5, ne sont pas portées) et un obstacle pour les
autres liaisons. Portage fidèle de l'étude (r4).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Mapping

import numpy as np

from golfgen.dressing.paths.geometry import Point, half_up

PLAZA_SIZE = 7           # côté nominal du parvis (blocs)
PLAZA_SIZES = (7, 6, 5, 4, 3)    # côtés essayés, du nominal au minimum
PLAZA_MAX_SHIFT = 4      # décalage maximal, le long du bord et vers l'intérieur (blocs)
PLAZA_CLEAR = 1          # cases libres au moins entre le parvis et un obstacle
PLAZA_REF = "parvis"
EDGE_NORMALS = {"N": (0, 1), "S": (0, -1), "W": (1, 0), "E": (-1, 0)}   # vers l'intérieur


@dataclass(frozen=True)
class Plaza:
    """Parvis du clubhouse : cases ``[x0, x0 + size) × [z0, z0 + size)``,
    bord ``edge`` du clubhouse, décalage ``shift`` (le long du bord, vers
    l'intérieur ; blocs) par rapport à la position nominale."""
    x0: int
    z0: int
    size: int
    edge: str
    shift: tuple[int, int] = (0, 0)

    @property
    def polygon(self) -> np.ndarray:
        x0, z0, x1, z1 = self.x0, self.z0, self.x0 + self.size, self.z0 + self.size
        return np.array([(x0, z0), (x1, z0), (x1, z1), (x0, z1)], dtype=float)

    @property
    def cells(self) -> np.ndarray:
        xs, zs = np.meshgrid(np.arange(self.x0, self.x0 + self.size),
                             np.arange(self.z0, self.z0 + self.size))
        return np.column_stack((xs.ravel(), zs.ravel())).astype(np.int64)


def clubhouse_edge(club: Mapping[str, Any], width: int, height: int) -> str:
    """Bord du clubhouse : ``club["edge"]`` s'il est donné, sinon le plus
    proche."""
    if club.get("edge") in EDGE_NORMALS:
        return club["edge"]
    x, y = float(club["x"]), float(club["y"])
    return min((("N", y), ("S", height - y), ("W", x), ("E", width - x)), key=lambda e: e[1])[0]


def plaza_at(club: Point, edge: str, size: int, along: int, inward: int) -> Plaza:
    """Parvis de côté ``size`` devant ``club``, décalé de ``along`` le long du
    bord et de ``inward`` vers l'intérieur."""
    nx, nz = EDGE_NORMALS[edge]
    tx, tz = abs(nz), abs(nx)
    cx = club[0] + nx * (size / 2.0 + inward) + tx * along
    cz = club[1] + nz * (size / 2.0 + inward) + tz * along
    return Plaza(half_up(cx - size / 2.0), half_up(cz - size / 2.0), size, edge, (along, inward))


def plaza_hits(plaza: Plaza, width: int, height: int, obstacles: Iterable,
               water: np.ndarray) -> list[str] | None:
    """Obstacles (refs, ``"eau"``) sur le parvis ou à moins de
    ``PLAZA_CLEAR`` case (8-voisinage) ; ``None`` s'il sort de la carte."""
    if plaza.x0 < 0 or plaza.z0 < 0 or plaza.x0 + plaza.size > width \
            or plaza.z0 + plaza.size > height:
        return None
    lo_x, lo_z = plaza.x0 - PLAZA_CLEAR, plaza.z0 - PLAZA_CLEAR
    hi_x, hi_z = plaza.x0 + plaza.size + PLAZA_CLEAR, plaza.z0 + plaza.size + PLAZA_CLEAR
    hits = []
    for obstacle in obstacles:
        c = obstacle.cells
        if ((c[:, 0] >= lo_x) & (c[:, 0] < hi_x) & (c[:, 1] >= lo_z) & (c[:, 1] < hi_z)).any():
            hits.append(obstacle.ref)
    if water[max(lo_z, 0):hi_z, max(lo_x, 0):hi_x].any():
        hits.append("eau")
    return hits


def plaza_shifts() -> list[tuple[int, int]]:
    """Décalages ``(along, inward)`` essayés, du plus petit au plus grand
    (somme, puis vers l'intérieur, puis le long du bord, puis négatif
    d'abord)."""
    return sorted(((along, inward) for along in range(-PLAZA_MAX_SHIFT, PLAZA_MAX_SHIFT + 1)
                   for inward in range(PLAZA_MAX_SHIFT + 1)),
                  key=lambda p: (abs(p[0]) + p[1], p[1], abs(p[0]), p[0]))


def place_plaza(club: Mapping[str, Any], width: int, height: int, obstacles,
                water: np.ndarray) -> tuple[Plaza | None, dict]:
    """Parvis devant le clubhouse (voir le docstring du module) et bilan :
    côté, décalage, obstacles en conflit à la position nominale, essais."""
    edge = clubhouse_edge(club, width, height)
    point = (float(club["x"]), float(club["y"]))
    nominal = plaza_hits(plaza_at(point, edge, PLAZA_SIZE, 0, 0), width, height,
                         obstacles, water)
    shifts = plaza_shifts()
    report = {"edge": edge, "nominal_size": PLAZA_SIZE,
              "conflicts": ["hors carte"] if nominal is None else nominal}
    tried = 0
    for size in PLAZA_SIZES:
        for along, inward in shifts:
            tried += 1
            plaza = plaza_at(point, edge, size, along, inward)
            if plaza_hits(plaza, width, height, obstacles, water) == []:
                report.update(placed=True, size=size, shift={"along": along, "inward": inward},
                              shifted=(along, inward) != (0, 0), reduced=size < PLAZA_SIZE,
                              x0=plaza.x0, z0=plaza.z0, tried=tried)
                return plaza, report
    report.update(placed=False, size=0, shift=None, shifted=False, reduced=False, tried=tried)
    return None, report
