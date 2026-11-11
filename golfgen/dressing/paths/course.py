"""Chemins d'un parcours : ``place_paths`` (API publique) et la couche à plat
``CoursePaths`` destinée à l'export.

``place_paths`` enchaîne : scène (``scene_from_json``, parvis posé) → réseau (liaisons
routées dans l'ordre de ``routing.links``, chacune sur le tronc des
précédentes : ``route_network``) → cases de la base de chaque liaison
(``link_blocks``) → intervalles partagés de chaque liaison (ses emprunts au
tronc et les morceaux de son tracé que d'autres lui ont empruntés) →
virages, liaison par liaison dans l'ordre, contre les cases des autres
liaisons (déjà courbées avant elle, base après) et les ancrages déjà posés
(``bend_route``, ``anchor_check``) → cases finales du tracé courbé →
union des cases, puis réparation des contacts par un coin seul DANS
L'UNION (``repair_union_corners``).

Réparation de l'union (règle de 4-connexité appliquée au réseau) : chaque
liaison est réparée seule (``path_blocks``), mais deux liaisons peuvent ne
se toucher que par un coin (cas de ``s112392-parkland`` : 9 → clubhouse et
clubhouse → 10, (10, 157) et (11, 158), juste au-dessus du parvis). Pour
chaque contact par un coin seul de l'union, on ajoute une des deux cases de
raccord : interdites les cases des obstacles (greens, boîtes, bunkers,
parvis), des ancrages et de l'eau, sauf l'eau permise aux liaisons qui
possèdent l'une des deux cases du contact (``bridge_water`` du tracé final
de celles qui sont des ponts : le raccord d'un contact ne s'appuie jamais sur l'eau d'un
autre pont) ; parmi les libres, la plus proche des deux
tracés (somme des distances de son centre au tracé final de chacune des
deux cases du contact : pour une case de plusieurs liaisons, le plus
proche), départage lexicographique ``(x, z)``. Passes répétées tant
qu'une case est ajoutée ; un contact sans case libre reste, signalé dans
``PathsDebug.union_defects``. L'union BRUTE (avant réparation) est dans
``PathsDebug.raw_cells``, les cases ajoutées dans
``PathsDebug.union_added`` ; la sortie (``CoursePaths.cells``) est
l'union réparée.

Couche à plat (``CoursePaths``) : cases entières ``[x, z]`` (z = y de la
carte), tableaux ``(k, 2)`` ``int64`` triés par x puis par z (ordre
lexicographique de ``[x, z]``, celui de ``np.unique(..., axis=0)``), sans
doublon :

- ``width`` : largeur nominale du chemin (blocs : 2 en links, 3 en
  parkland) ;
- ``cells`` : union des cases de toutes les liaisons (troncs fusionnés : une
  case partagée n'y est qu'une fois), réparée de ses contacts par un coin
  seul (voir plus haut). Les cases de pont
  Y SONT : ``bridge_cells`` en est le sous-ensemble sur l'eau effective (une
  liaison qui n'est pas un pont n'a jamais de case sur l'eau). Le parvis n'y
  est jamais (c'est un obstacle de la conversion en blocs) ;
- ``bridge_cells`` : cases de chemin sur l'eau effective (ponts) ;
- ``plaza`` : parvis du clubhouse (cases, côté, décalage), ``None`` s'il
  n'a pas pu être posé ;
- ``anchors`` : case de l'ancrage de chaque virage posé (rough libre, hors
  de tout chemin).

Le détail par liaison (tracés, statut, cases, ancrages, pont, emprunts,
bilan des virages) n'est que dans ``CoursePaths.debug`` (``PathsDebug``),
hors de la couche exportée. Une liaison sans route lève ``PathError`` ; de
même, une liaison coupée (``Blocks.severed``) ou
qui ne touche pas une de ses surfaces (``contacts_missing`` ; une liaison
triviale, entre surfaces qui se touchent par une face, n'a pas de contact à
tenir), et une union avec un contact par un coin resté sans case libre
(``union_defects``) : rien n'est exporté.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping

import numpy as np

from golfgen.dressing.paths.bends import BendReport, anchor_check, bend_route
from golfgen.dressing.paths.blocks import (Blocks, bridge_water, contacts_missing, corner_only,
                                           link_blocks, link_ends, water_cuts)
from golfgen.dressing.paths.bridge_rule import BridgeRule
from golfgen.dressing.paths.errors import PathError
from golfgen.dressing.paths.fairway_rule import FairwayRule
from golfgen.dressing.paths.geometry import Cell, Point, polyline_distance
from golfgen.dressing.paths.grid import Network
from golfgen.dressing.paths.route import Route, route_network
from golfgen.dressing.paths.scene import LinkEnds, Scene, obstacle_mask, scene_from_json


def _sorted_cells(cells) -> np.ndarray:
    """Cases ``(k, 2)`` ``int64`` uniques, triées par x puis z."""
    arr = np.asarray(cells, dtype=np.int64).reshape(-1, 2)
    return np.unique(arr, axis=0) if len(arr) else arr


@dataclass(frozen=True, eq=False)
class PlazaLayer:
    """Parvis exporté : ``cells`` (``size`` × ``size`` cases, triées par x
    puis z), ``shift`` (le long du bord, vers l'intérieur ; blocs) par
    rapport à la position nominale."""
    cells: np.ndarray
    size: int
    shift: tuple[int, int]


@dataclass(frozen=True, eq=False)
class LinkPaths:
    """Détail d'une liaison (debug, non exporté) : ``points`` tracé final
    (courbé), ``route`` (tracé de base, statut, pont, emprunts ``borrows``,
    ``shared``), ``shared`` intervalles d'abscisse de la base partagés avec
    d'autres chemins (jamais courbés), ``blocks`` conversion du tracé final
    (``cells`` : ses cases), ``bridge_cells`` ses cases sur l'eau,
    ``bends`` bilan des virages, ``anchors`` points et ``anchor_cells``
    cases d'ancrage, ``contacts_missing`` bouts de surface non touchés (0
    attendu), ``water_cuts`` cases du trait découpées par l'eau à au moins
    ``BLOCK_END_ZONE`` des bouts (chemin pincé en chemin, 0 attendu sur un
    pont) et ``water_cuts_total`` en tout (``blocks.water_cuts``)."""
    link: LinkEnds
    route: Route
    points: tuple[Point, ...]
    shared: tuple[tuple[float, float], ...]
    blocks: Blocks
    bridge_cells: np.ndarray
    bends: BendReport
    anchors: tuple[Point, ...]
    anchor_cells: tuple[Cell, ...]
    contacts_missing: int
    water_cuts: int = 0
    water_cuts_total: int = 0

    @property
    def index(self) -> int:
        return self.link.index

    @property
    def status(self) -> str:
        return self.route.status

    @property
    def cells(self) -> np.ndarray:
        return self.blocks.cells


@dataclass(frozen=True, eq=False)
class PathsDebug:
    """Structure de debug : scène, réseau (tronc), cases de base et détail
    de chaque liaison, dans l'ordre de ``routing.links`` ; ``raw_cells``
    union brute des cases des liaisons, ``union_added``
    cases ajoutées par la réparation des contacts par un coin seul de
    l'union (triées), ``union_defects`` contacts restés sans case libre
    (paires de cases ``((x, z), (x', z'))``, 0 attendu)."""
    scene: Scene
    network: Network
    base_blocks: tuple[Blocks, ...]
    links: tuple[LinkPaths, ...]
    raw_cells: np.ndarray = field(default_factory=lambda: np.zeros((0, 2), dtype=np.int64))
    union_added: np.ndarray = field(default_factory=lambda: np.zeros((0, 2), dtype=np.int64))
    union_defects: tuple[tuple[Cell, Cell], ...] = ()


@dataclass(frozen=True, eq=False)
class CoursePaths:
    """Couche à plat des chemins d'un parcours (voir le docstring du
    module) ; ``debug`` : détail par liaison, non exporté."""
    width: float
    cells: np.ndarray
    bridge_cells: np.ndarray
    plaza: PlazaLayer | None
    anchors: np.ndarray
    debug: PathsDebug | None = field(default=None, repr=False)


def link_shared(routes: tuple[Route, ...]) -> list[tuple[tuple[float, float], ...]]:
    """Intervalles partagés de chaque liaison, triés : ses emprunts
    (``route.shared``) et les morceaux de son tracé que d'autres lui ont
    empruntés (``owner_interval`` de leurs ``borrows``)."""
    shared = [list(route.shared) for route in routes]
    for route in routes:
        for b in route.borrows:
            shared[b["from"]].append(tuple(b["owner_interval"]))
    return [tuple(sorted(s)) for s in shared]


def repair_union_corners(union: np.ndarray, link_cells, traces, forbidden: np.ndarray,
                         water: np.ndarray | None = None, link_water=None
                         ) -> tuple[np.ndarray, np.ndarray, tuple[tuple[Cell, Cell], ...]]:
    """Réparation des contacts par un coin seul de l'union ``union`` (voir
    le docstring du module) : ``link_cells`` cases de chaque liaison,
    ``traces`` tracé final de chacune (même ordre), ``forbidden`` ``(h, w)``
    cases interdites. ``water`` ``(h, w)`` (optionnel) : eau, interdite
    elle aussi sauf là où ``link_water[k]`` (``(h, w)`` ou ``None``, même
    ordre que ``link_cells``) la permet à une liaison ``k`` propriétaire de
    l'une des deux cases du contact. Rend l'union réparée (triée), les cases
    ajoutées (triées) et les contacts restés sans case libre."""
    h, w = forbidden.shape
    mask = np.zeros((h, w), dtype=bool)
    if len(union):
        mask[union[:, 1], union[:, 0]] = True
    owners: dict[Cell, list[int]] = {}
    for k, cells in enumerate(link_cells):
        for x, z in cells.tolist():
            owners.setdefault((x, z), []).append(k)
    added: list[Cell] = []

    def near(cell: Cell, of: Cell) -> float:
        # distance du centre de ``cell`` au plus proche des tracés de ``of``
        # (une case ajoutée n'a pas de liaison : ses deux voisines du contact)
        links = owners.get(of, ())
        arr = np.asarray([cell], dtype=np.int64)
        return min(float(polyline_distance(arr, traces[k])[0][0]) for k in links) \
            if links else 0.0

    def dry_or_bridged(cell: Cell, a: Cell, b: Cell) -> bool:
        # eau : permise seulement par le pont d'une liaison de ``a`` ou ``b``
        x, z = cell
        if water is None or not water[z, x]:
            return True
        return any(link_water[k] is not None and link_water[k][z, x]
                   for k in {*owners.get(a, ()), *owners.get(b, ())})

    def contacts() -> list[tuple[Cell, Cell, tuple[Cell, Cell]]]:
        # (case, case) du contact et ses deux cases de raccord, ordre de
        # ``corner_only`` : diagonale d1 puis d2, (z, x) croissants
        d1, d2 = corner_only(mask)
        out = []
        for z, x in np.argwhere(d1).tolist():
            out.append(((x, z), (x + 1, z + 1), ((x + 1, z), (x, z + 1))))
        for z, x in np.argwhere(d2).tolist():
            out.append(((x + 1, z), (x, z + 1), ((x, z), (x + 1, z + 1))))
        return out

    while True:
        progress = False
        for a, b, pair in contacts():
            if mask[pair[0][1], pair[0][0]] or mask[pair[1][1], pair[1][0]] \
                    or not (mask[a[1], a[0]] and mask[b[1], b[0]]):
                continue                 # déjà raccordé par une case de cette passe
            free = [c for c in pair if not forbidden[c[1], c[0]] and dry_or_bridged(c, a, b)]
            if not free:
                continue
            best = min(free, key=lambda c: (near(c, a) + near(c, b), c))
            mask[best[1], best[0]] = True
            added.append(best)
            for k in {*owners.get(a, ()), *owners.get(b, ())}:
                owners.setdefault(best, []).append(k)
            progress = True
        if not progress:
            break
    defects = tuple((a, b) for a, b, _ in contacts())
    rc = np.argwhere(mask)
    out = _sorted_cells(np.column_stack((rc[:, 1], rc[:, 0])))
    return out, _sorted_cells(added), defects


def place_paths(data: Mapping[str, Any], *,
                fairway_rule: FairwayRule = FairwayRule(),
                bridge_rule: BridgeRule = BridgeRule()) -> CoursePaths:
    """Chemins du parcours du JSON 3.2 ``data`` (style lu dans
    ``metadata.style``, défaut ``links`` ; largeur ``scene.PATH_WIDTH``) :
    voir le docstring du module ; ``fairway_rule`` : traitement du fairway
    (``fairway_rule`` ; défaut : la correction, surcoût 2) ; ``bridge_rule``
    : règle des ponts (``bridge_rule`` ; défaut : règle du gain à 25 %,
    virages doux, avec les corrections ; ``BridgeRule.gained(G)`` : autre
    gain). ``PathError`` si une liaison n'a aucune route ou si elle est
    coupée (bogue)."""
    scene = scene_from_json(data, fairway_rule, bridge_rule)
    obstacles = obstacle_mask(scene)
    routes, network = route_network(scene)
    base = [link_blocks(scene, link, route, route.points, obstacles)
            for link, route in zip(scene.links, routes)]
    shared = link_shared(routes)
    cells = [b.cells for b in base]
    anchors: set[Cell] = set()
    links = []
    for k, link in enumerate(scene.links):
        route = routes[k]
        others = np.zeros((scene.height, scene.width), dtype=bool)
        placed = np.zeros_like(others)
        for j, c in enumerate(cells):
            if j != k and len(c):
                others[c[:, 1], c[:, 0]] = True
                if j < k:
                    placed[c[:, 1], c[:, 0]] = True
        verify = anchor_check(scene, link, route, obstacles, anchors, placed, base[k].defects)
        points, report = bend_route(scene, route, route.points, link.index, None, obstacles,
                                    others, verify, shared[k])
        # sans virage posé, le tracé est celui de la base : mêmes cases
        blocks = link_blocks(scene, link, route, points, obstacles) if report.placed else base[k]
        cells[k] = blocks.cells
        own_anchors = tuple(b.anchor_cell for b in report.bends)
        missing = contacts_missing(scene, link, blocks.cells)
        if route.status == "trivial":
            missing = 0                  # surfaces qui se touchent : rien à poser (``route_link``)
        if blocks.severed or missing:
            raise PathError(f"chemins : liaison {link.index} ({link.src} → {link.dst}) coupée, "
                            f"seed {scene.seed} : {blocks.severed} morceau(x) du tracé retiré(s), "
                            f"{missing} bout(s) de surface non touché(s) : bogue (une liaison "
                            f"coupée n'est jamais exportée)")
        cuts_total, cuts_inner = water_cuts(scene, link, route, points)
        anchors.update(own_anchors)
        wet = (scene.water[blocks.cells[:, 1], blocks.cells[:, 0]] if len(blocks.cells)
               else np.zeros(0, dtype=bool))
        links.append(LinkPaths(
            link=link, route=route, points=tuple(points), shared=shared[k], blocks=blocks,
            bridge_cells=_sorted_cells(blocks.cells[wet]), bends=report,
            anchors=tuple(b.anchor for b in report.bends), anchor_cells=own_anchors,
            contacts_missing=missing,
            water_cuts=cuts_inner, water_cuts_total=cuts_total))
    raw = _sorted_cells(np.concatenate(cells) if cells else ())
    # réparation de l'union : obstacles (parvis compris) et ancrages
    # interdits ; eau interdite hors du pont des liaisons du contact
    forbidden = obstacles.copy()
    for x, z in anchors:
        forbidden[z, x] = True
    link_water = [bridge_water(scene, lp.route, lp.points, link_ends(lp.link))
                  if lp.route.bridge else None
                  for lp in links]
    union, added, defects = repair_union_corners(raw, [lp.cells for lp in links],
                                                 [lp.points for lp in links], forbidden,
                                                 water=scene.water, link_water=link_water)
    if defects:
        raise PathError(f"chemins : union coupée, seed {scene.seed} : {len(defects)} contact(s) "
                        f"par un coin seul sans case libre, dont {defects[0][0]} – "
                        f"{defects[0][1]} : bogue (une union coupée n'est jamais exportée)")
    on_water = (scene.water[union[:, 1], union[:, 0]] if len(union)
                else np.zeros(0, dtype=bool))
    plaza = None
    if scene.plaza is not None:
        plaza = PlazaLayer(_sorted_cells(scene.plaza.cells), scene.plaza.size,
                           tuple(scene.plaza.shift))
    return CoursePaths(width=scene.path_width, cells=union, bridge_cells=union[on_water],
                       plaza=plaza, anchors=_sorted_cells(sorted(anchors)),
                       debug=PathsDebug(scene, network, tuple(base), tuple(links), raw, added,
                                        defects))
