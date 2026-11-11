"""Export JSON du parcours de golf."""

from __future__ import annotations

import base64
import copy
import json
import math
import os
from pathlib import Path
from typing import TYPE_CHECKING, Any
import uuid

import numpy as np

from . import __version__
from .dressing.green import _following, edges_cross, shoelace
from .dressing.model import STYLE_SPECS, CourseDressing, GreenPair, HoleDressing
from .routing.model import ElasticHole, NineLayout, WalkingLink
from .routing.muirfield import MuirfieldResult, outer_start
from .routing.sites import WATER_LEVEL
from .terrain import relief_f32_block

if TYPE_CHECKING:  # import paresseux : l'exporteur ne charge ni bunkers, ni chemins, ni arbres
    from .dressing.bunkers import CourseBunkers
    from .dressing.paths import CoursePaths
    from .dressing.trees import CourseTrees


def terrain_block(heightmap: np.ndarray) -> dict[str, Any]:
    """Bloc ``terrain`` du format 3.0 (sans ``water_level``) : heightmap encodée
    en base64 uint8 (normalisée sur [min, max]), min/max arrondis à 2 décimales."""
    h, w = heightmap.shape
    elev_min = float(heightmap.min())
    elev_max = float(heightmap.max())

    if elev_max - elev_min < 1e-10:
        uint8_data = np.zeros((h, w), dtype=np.uint8)
    else:
        normalized = (heightmap - elev_min) / (elev_max - elev_min)
        uint8_data = (normalized * 255).astype(np.uint8)

    encoded = base64.b64encode(uint8_data.tobytes()).decode('ascii')

    return {
        "width": w,
        "height": h,
        "elevation": {
            "encoding": "base64_uint8",
            "data": encoded,
            "min_elevation": round(elev_min, 2),
            "max_elevation": round(elev_max, 2),
        }
    }


FORMAT_VERSION = "3.0"
DRESSED_FORMAT_VERSION = "3.1"  # 3.0 + habillage (metadata.style, holes[].features,
                                #                  routing.green_pairs)
BUNKERS_FORMAT_VERSION = "3.2"  # 3.1 + bunkers (clé de premier niveau ``bunkers``)
PATHS_FORMAT_VERSION = "3.3"    # 3.2 + chemins (clé de premier niveau ``paths``)
TREES_FORMAT_VERSION = "3.4"    # 3.3 + arbres (clé de premier niveau ``trees``)
BLOCK_M = 3                     # 1 bloc Minecraft = 3 m (model.py)
# Sens de rotation du nine extérieur selon ``Plan.direction`` : +1 = angle
# croissant autour du centre de carte ; repère carte en y vers le bas (rendus
# SVG et viewer), donc sens horaire à l'écran.
TURNS = {1: "clockwise", -1: "counterclockwise"}


def _r2(value: float) -> float:
    return round(float(value), 2)


def _exact(point) -> dict[str, float]:
    """Point d'ENTRÉE de l'habillage (tee, green, coude, clubhouse, extrémité
    de liaison) : pleine précision, non arrondi. ``json`` écrit le ``repr``
    d'un flottant, relu au bit près : l'habillage depuis le JSON est celui
    du parcours en mémoire."""
    return {"x": float(point.x), "y": float(point.y)}


def _xy(point: tuple[float, float]) -> dict[str, float]:
    return {"x": _r2(point[0]), "y": _r2(point[1])}


def _shape_v31(shape) -> dict[str, Any]:
    """Contour, centre et aire d'une forme d'habillage (green ou départ)."""
    return {
        "outline": [_xy(p) for p in shape.outline],
        "center": _xy(shape.center),
        "area": _r2(shape.area),
    }


def _features_v31(dressing: HoleDressing) -> dict[str, Any]:
    """``features`` d'un trou 3.1 : green, départs (de l'arrière vers
    l'avant) et fairway (R5 : ``features.fairway``, toujours présent, liste
    de morceaux ``{outline, area}`` dans l'ordre de ``HoleDressing.fairway``
    — le principal d'abord, puis par aire décroissante —, ``[]`` si l'eau
    l'a vidé ; contours arrondis comme le green, sans ``center`` ; un
    contour qui n'est plus strictement simple après l'arrondi lève
    ``ValueError`` nommant le trou, jamais corrigé). Type du green, rang,
    sens, causes de bascule, repli pour l'eau, fragments retirés et cause
    d'un fairway vide restent internes, sauf la remontée d'un green
    insulaire ou d'une boîte remontée (``features.green.island``,
    ``features.tees[].island``, absentes au sec)."""
    green = _shape_v31(dressing.green)
    if dressing.green.island is not None:
        green["island"] = {"height": _r2(dressing.green.island.height),
                           "raised_area": _r2(dressing.green.island.raised_area)}
    tees = []
    for box in dressing.tees:
        item = _shape_v31(box)
        if box.island is not None:
            item["island"] = {"height": _r2(box.island.height),
                              "raised_area": _r2(box.island.raised_area),
                              "submerged": bool(box.island.submerged)}
        tees.append(item)
    fairway = [_fairway_piece_v31(piece, dressing.order) for piece in dressing.fairway]
    return {"green": green, "tees": tees, "fairway": fairway}


def _fairway_piece_v31(piece, order: int) -> dict[str, Any]:
    """Morceau de fairway 3.1 : contour arrondi à 2 décimales (``_xy``) et
    aire (``_r2``), sans ``center``. Contrairement au green et aux départs,
    dont le contour est déjà arrondi dans le modèle, le contour du fairway
    n'est arrondi qu'ici : ``area`` est l'aire du contour du modèle avant
    arrondi (``piece.area``) et peut différer de l'aire du contour exporté
    (jusqu'à ≈ 0,08 bloc² mesuré) ; ``routing.green_pairs`` donne, lui,
    l'aire du contour arrondi. Contour arrondi de
    moins de 3 sommets, ou non strictement simple (croisement, contact ou
    sommets confondus par l'arrondi) : ``ValueError`` nommant le trou ;
    aucune correction."""
    outline = [_xy(p) for p in piece.outline]
    array = np.array([(p["x"], p["y"]) for p in outline], dtype=float)
    if len(outline) < 3 or not _strictly_simple(array):
        raise ValueError(f"trou {order} : contour de fairway non simple à l'arrondi")
    return {"outline": outline, "area": _r2(piece.area)}


def _strictly_simple(points: np.ndarray, tol: float = 1e-9) -> bool:
    """Polygone fermé sans croisement propre d'arêtes NI contact : aucun
    sommet posé (à ``tol`` près) sur une arête non adjacente, sommets
    répétés compris."""
    if edges_cross(points, points):
        return False
    a, b = points, _following(points)
    q = b - a                                               # arêtes (n, 2)
    rel = points[:, None, :] - a[None, :, :]                # sommet v − début de e
    length2 = np.maximum((q * q).sum(axis=1), 1e-300)
    t = (rel * q[None]).sum(axis=2) / length2
    gap = np.abs(rel[..., 0] * q[None, :, 1] - rel[..., 1] * q[None, :, 0]) / np.sqrt(length2)
    n = len(points)
    own = np.arange(n)
    adjacent = (own[:, None] == own[None, :]) | (own[:, None] == (own[None, :] + 1) % n)
    touch = (gap <= tol) & (t >= -tol) & (t <= 1.0 + tol) & ~adjacent
    return not bool(touch.any())


def _pair_outline(outline) -> list[tuple[float, float]]:
    """Contour d'un green double pour l'export : arrondi à 2 décimales,
    sommets consécutifs confondus par l'arrondi retirés (fermeture
    comprise), même sens que les contours de greens (aire signée positive
    dans le repère (x, y) de la carte : sens horaire à l'écran). Contour
    arrondi de moins de 3 sommets, ou non simple (croisement ou contact) :
    ``ValueError``."""
    points = [(_r2(x), _r2(y)) for x, y in outline]
    points = [p for k, p in enumerate(points) if p != points[k - 1]]
    array = np.asarray(points, dtype=float)
    if len(points) < 3 or not _strictly_simple(array):
        raise ValueError("contour de green double dégénéré à l'arrondi")
    if shoelace(array) < 0:
        points.reverse()
    return points


def _green_pairs_v31(dressing: CourseDressing) -> list[dict[str, Any]]:
    """``routing.green_pairs`` (3.1) : greens doubles triés par ``(i, j)``,
    trous, contour arrondi et aire du contour arrondi (calculée comme celle
    des greens : ``|shoelace|``, 2 décimales). Paire sans forme (``outline``
    vide : jamais retenue par ``dress_course``) ignorée ; distance, col,
    empreinte et rejets restent internes."""
    out = []
    for pair in sorted(dressing.green_pairs, key=lambda p: (p.i, p.j)):
        if not pair.outline:
            continue
        if pair.i not in dressing.holes or pair.j not in dressing.holes or pair.i >= pair.j:
            raise ValueError(f"green double ({pair.i}, {pair.j}) hors des trous du parcours")
        outline = _pair_outline(pair.outline)
        out.append({
            "holes": [pair.i, pair.j],
            "outline": [{"x": x, "y": y} for x, y in outline],
            "area": _r2(abs(shoelace(np.asarray(outline, dtype=float)))),
        })
    return out


def _hole_v3(hole: ElasticHole, nine: str) -> dict[str, Any]:
    """Trou 3.0 ; ``width``, ``rough_margin``, ``tee``, ``green`` et
    ``doglegs`` (entrées de l'habillage) en pleine précision, ``length``
    (statistique) arrondie."""
    return {
        "id": hole.order,
        "nine": nine,
        "par": hole.par,
        "length": _r2(hole.length),
        "width": float(hole.width),
        "rough_margin": float(hole.rough_margin),
        "tee": _exact(hole.tee),
        "green": _exact(hole.green),
        "doglegs": [_exact(p) for p in hole.doglegs],
    }


def _link_v3(link: WalkingLink) -> dict[str, Any]:
    """Liaison 3.0 : ``from``/``to`` (ses extrémités, green de ``from`` et
    tee de ``to`` ou clubhouse, se déduisent des trous : pas exportées en
    double), ``length`` (statistique) arrondie."""
    def end(order: int | None) -> int | str:
        return "clubhouse" if order is None else order
    return {
        "from": end(link.from_hole_order),
        "to": end(link.to_hole_order),
        "length": _r2(link.length),
    }


def _nine_stats(nine: NineLayout) -> tuple[dict[str, Any], float, int]:
    holes = math.fsum(hole.length for hole in nine.holes)
    links = math.fsum(link.length for link in nine.links)
    par = sum(hole.par for hole in nine.holes)
    stats = {"holes_length": _r2(holes), "links_length": _r2(links),
             "total": _r2(holes + links), "par": par}
    return stats, holes + links, par


def muirfield_to_dict(result: MuirfieldResult, heightmap: np.ndarray, *, seed: int,
                      seed_input: str | None = None,
                      dressing: CourseDressing | None = None) -> dict[str, Any]:
    """Parcours Muirfield au format JSON 3.0 (référence : ``docs/format-3.0.md``),
    ou 3.1 si ``dressing`` est donné : ``with_dressing`` appliqué au 3.0
    (``metadata.style``, ``holes[].features`` et ``routing.green_pairs``,
    toujours présent, liste vide sans green double, en plus ; le reste est
    identique, octet pour octet).

    Fonction pure : ni I/O, ni état global, ni aléa. ``seed`` est l'entier
    signé 64 bits tel que saisi (exporté en chaîne, exact au-delà de 2^53),
    PAS sa forme u64 donnée au routage ; ce doit être un ``int`` Python
    (``int(seed)`` à l'appel : un ``np.int64`` est refusé) ; ``seed_input`` le
    texte d'origine, ou None. Unités : blocs (1 bloc = 3 m). Flottants
    arrondis à 2 décimales, SAUF les entrées de l'habillage, en pleine
    précision : ``holes[].width``, ``rough_margin``, ``tee``, ``green``,
    ``doglegs``, ``clubhouse`` (x, y) ; relief
    float32 sans perte dans ``terrain.elevation_f32`` (``heightmap`` doit
    donc être exactement représentable en float32). Le JSON suffit ainsi à
    habiller à nouveau le parcours (``golfgen.dressing.dress_course_json``).
    Le résultat passe ``json.dumps`` tel quel."""
    if isinstance(seed, bool) or not isinstance(seed, int):
        raise TypeError("seed doit être un entier")
    if seed_input is not None and not isinstance(seed_input, str):
        raise TypeError("seed_input doit être une chaîne ou None")
    if dressing is not None:
        _check_dressing(dressing, [hole.order for hole in result.layout.holes])
    width, height = float(result.width), float(result.height)
    if heightmap.shape != (int(height), int(width)):
        raise ValueError(f"relief {heightmap.shape}, carte attendue {int(height)}×{int(width)}")

    layout = result.layout
    if width > height:
        orientation = "landscape"
    elif width < height:
        orientation = "portrait"
    else:
        orientation = "square"

    front, front_total, front_par = _nine_stats(layout.front)
    back, back_total, back_par = _nine_stats(layout.back)
    outer = "front" if outer_start(result.pattern) == 1 else "back"
    direction = TURNS[result.direction]
    opposite = TURNS[-result.direction]

    holes = [_hole_v3(hole, name)
             for name, nine in (("front", layout.front), ("back", layout.back))
             for hole in nine.holes]
    holes.sort(key=lambda hole: hole["id"])

    metadata: dict[str, Any] = {
        "version": FORMAT_VERSION,
        "generator": f"golfgen {__version__}",
        "seed": str(seed),
        "seed_input": seed_input,
        "pattern": {"requested": result.requested_pattern, "resolved": result.pattern},
        "orientation": orientation,
        "short_side": _r2(min(width, height)),
        "long_side": _r2(max(width, height)),
        "width": _r2(width),
        "height": _r2(height),
        "block_m": BLOCK_M,
        "stats": {
            "front": front,
            "back": back,
            "total": _r2(front_total + back_total),
            "par": front_par + back_par,
            "elapsed_seconds": _r2(result.elapsed_seconds),
            "relaunches": result.relaunches,
        },
    }

    routing: dict[str, Any] = {
        "clubhouse": {**_exact(layout.clubhouse), "edge": result.clubhouse_edge},
        "direction": {
            "outer_nine": outer,
            "outer_turn": direction,
            "inner_nine": "back" if outer == "front" else "front",
            "inner_turn": opposite,
        },
        "holes": holes,
        "links": [_link_v3(link) for link in layout.links],
    }

    data = {
        "metadata": metadata,
        "terrain": {**terrain_block(heightmap), "water_level": _r2(WATER_LEVEL),
                    "elevation_f32": relief_f32_block(heightmap)},
        "routing": routing,
    }
    return data if dressing is None else with_dressing(data, dressing)


def _check_dressing(dressing: CourseDressing, orders) -> None:
    if not isinstance(dressing, CourseDressing):
        raise TypeError("dressing doit être un CourseDressing ou None")
    if not isinstance(dressing.style, str) or dressing.style not in STYLE_SPECS:
        raise ValueError(f"style d'habillage inconnu : {dressing.style!r} "
                         f"(attendu : {', '.join(STYLE_SPECS)})")
    if sorted(dressing.holes) != sorted(orders):
        raise ValueError("l'habillage ne couvre pas exactement les trous du parcours")


def with_dressing(data: dict[str, Any], dressing: CourseDressing) -> dict[str, Any]:
    """JSON 3.1 : le dict 3.0 ``data`` (``muirfield_to_dict`` sans
    habillage) plus ``dressing`` — ``metadata.version`` "3.1",
    ``metadata.style`` (après ``pattern``), ``holes[].features`` (dernière
    clé de chaque trou : ``green``, ``tees``, ``fairway``) et
    ``routing.green_pairs`` (avant ``links``) ; tout le reste est repris
    tel quel, sauf les clés ``bunkers`` (3.2), ``paths`` (3.3) et ``trees``
    (3.4) : calculées sur l'ancien habillage, elles sont retirées
    (``with_bunkers``, ``with_paths`` et ``with_trees`` les recalculent). Étape 2 du
    pipeline : n'a besoin que du JSON de l'étape 1,
    pas du résultat du routage. ``data`` n'est pas modifié (le résultat ne
    partage que des chaînes et nombres avec lui)."""
    _check_dressing(dressing, [hole["id"] for hole in data["routing"]["holes"]])
    data = {key: value for key, value in copy.deepcopy(data).items()
            if key not in ("bunkers", "paths", "trees")}
    metadata: dict[str, Any] = {}
    for key, value in data["metadata"].items():
        if key == "style":
            continue
        metadata[key] = DRESSED_FORMAT_VERSION if key == "version" else value
        if key == "pattern":
            metadata["style"] = dressing.style
    routing: dict[str, Any] = {}
    for key, value in data["routing"].items():
        if key == "green_pairs":
            continue
        if key == "holes":
            for hole in value:
                hole["features"] = _features_v31(dressing[hole["id"]])
        if key == "links":
            routing["green_pairs"] = _green_pairs_v31(dressing)
        routing[key] = value
    return {**data, "metadata": metadata, "routing": routing}


def _bunker_v32(bunker) -> dict[str, Any]:
    """Bunker posé 3.2 : cases de sable ``[[x, z], ...]`` entières (la case
    ``(x, z)`` couvre ``[x, x + 1] × [z, z + 1]`` ; ``z`` = ``y`` du JSON)."""
    return {"id": bunker.id, "hole": int(bunker.hole), "family": bunker.family,
            "role": bunker.role, "status": bunker.status,
            "cells": [[int(x), int(z)] for x, z in bunker.cells.tolist()]}


def with_bunkers(data: dict[str, Any], bunkers: CourseBunkers) -> dict[str, Any]:
    """JSON 3.2 : le dict 3.1 ``data`` (``with_dressing``) plus la clé de
    premier niveau ``bunkers`` (dernière clé) — ``empty_rule``,
    ``empty_holes`` et ``items`` (sable légal de ``CourseBunkers.bunkers``,
    dans son ordre) — et ``metadata.version`` "3.2" ; tout le reste est
    repris tel quel, sauf les clés ``paths`` (3.3) et ``trees`` (3.4) : posés
    autour des anciens bunkers, chemins et arbres sont retirés (``with_paths``
    et ``with_trees`` les recalculent). Les bunkers non posés (``unplaced``) ne sont pas
    exportés. ``ValueError`` si ``data`` n'est pas habillé, si un bunker
    nomme un trou absent ou si une case sort de la carte. ``data`` n'est
    pas modifié.

    L'invariant « aucune case sur l'eau » est garanti par ``place_bunkers``
    (contrôle de légalité sur le ``WaterMask`` brut) et n'est PAS revérifié
    ici : seuls le trou et les bornes de la carte le sont."""
    from .dressing.bunkers import CourseBunkers  # paresseux (cf. en-tête)
    if not isinstance(bunkers, CourseBunkers):
        raise TypeError("bunkers doit être un CourseBunkers")
    holes = data["routing"]["holes"]
    if any("features" not in hole for hole in holes):
        raise ValueError("bunkers sans habillage : appliquer with_dressing d'abord")
    orders = {hole["id"] for hole in holes}
    width, height = data["terrain"]["width"], data["terrain"]["height"]
    for bunker in bunkers.bunkers:
        if bunker.hole not in orders:
            raise ValueError(f"bunker {bunker.id!r} : trou {bunker.hole} absent du parcours")
        cells = bunker.cells
        if len(cells) and ((cells < 0).any() or (cells[:, 0] >= width).any()
                           or (cells[:, 1] >= height).any()):
            raise ValueError(f"trou {bunker.hole}, bunker {bunker.id!r} : case hors de la carte")
    data = copy.deepcopy(data)
    data.pop("bunkers", None)
    data.pop("paths", None)
    data.pop("trees", None)
    data["metadata"]["version"] = BUNKERS_FORMAT_VERSION
    data["bunkers"] = {"empty_rule": bunkers.empty_rule,
                       "empty_holes": [int(order) for order in bunkers.empty_holes],
                       "items": [_bunker_v32(bunker) for bunker in bunkers.bunkers]}
    return data


def _cells_v33(cells: np.ndarray) -> list[list[int]]:
    """Cases ``(k, 2)`` en ``[[x, z], ...]`` d'entiers Python."""
    return np.asarray(cells, dtype=np.int64).reshape(-1, 2).tolist()


def _paths_debug_v33(paths: CoursePaths) -> dict[str, Any]:
    """Détail des chemins (``--paths-debug``) : par liaison, dans l'ordre
    de ``routing.links``, ``from``, ``to``, ``status`` (statut de la route :
    ``straight``, ``detour``, ``bridge``, ``trivial``), ``bridge``,
    ``points`` (tracé final, virages compris, ``{x, y}`` à 2 décimales) et
    ``cells`` (ses cases) ; puis ``union_added`` (cases de raccord ajoutées
    à l'union contre les contacts par un coin seul) et ``union_defects``
    (contacts restés sans case libre : paires de cases, vide attendu)."""
    debug = paths.debug
    links = [{"from": lp.link.src, "to": lp.link.dst, "status": lp.status,
              "bridge": bool(lp.route.bridge),
              "points": [{"x": _r2(x), "y": _r2(y)} for x, y in lp.points],
              "cells": _cells_v33(lp.cells)} for lp in debug.links]
    return {"links": links, "union_added": _cells_v33(debug.union_added),
            "union_defects": [[list(map(int, a)), list(map(int, b))]
                              for a, b in debug.union_defects]}


def with_paths(data: dict[str, Any], paths: CoursePaths, *, debug: bool = False) -> dict[str, Any]:
    """JSON 3.3 : le dict 3.2 ``data`` (``with_bunkers``) plus la clé de
    premier niveau ``paths`` (dernière clé), couche à plat de
    ``CoursePaths`` — ``width`` (blocs), ``cells`` (union des cases, ponts
    compris, ``[[x, z], ...]`` triées par x puis z), ``bridge_cells``
    (sous-ensemble de ``cells`` sur l'eau), ``plaza`` (``{cells, size,
    offset}``, ``offset`` = ``{along, inward}`` : décalage en blocs le long
    du bord et vers l'intérieur, ou ``null``) et ``anchors`` (``[[x, z], ...]``) — et ``metadata.version``
    "3.3" ; avec ``debug``, une sous-clé ``paths.debug`` (dernière) détaille
    chaque liaison (``_paths_debug_v33``). Tout le reste est repris tel
    quel, sauf une clé ``trees`` (3.4), retirée (``with_trees`` la recalcule).
    ``ValueError`` si ``data`` n'a pas de bunkers (versions en
    escalier : pas de chemins sans bunkers), si une case sort de la carte ou
    si ``debug`` est demandé sans détail. ``data`` n'est pas modifié."""
    from .dressing.paths import CoursePaths  # paresseux (cf. en-tête)
    if not isinstance(paths, CoursePaths):
        raise TypeError("paths doit être un CoursePaths")
    if "bunkers" not in data:
        raise ValueError("chemins sans bunkers : appliquer with_bunkers d'abord")
    if debug and paths.debug is None:
        raise ValueError("chemins sans détail : debug demandé")
    width, height = data["terrain"]["width"], data["terrain"]["height"]
    layers = [("cells", paths.cells), ("bridge_cells", paths.bridge_cells),
              ("anchors", paths.anchors)]
    if paths.plaza is not None:
        layers.append(("plaza", paths.plaza.cells))
    for name, cells in layers:
        cells = np.asarray(cells).reshape(-1, 2)
        if len(cells) and ((cells < 0).any() or (cells[:, 0] >= width).any()
                           or (cells[:, 1] >= height).any()):
            raise ValueError(f"chemins : case de {name} hors de la carte")
    plaza = None
    if paths.plaza is not None:
        plaza = {"cells": _cells_v33(paths.plaza.cells), "size": int(paths.plaza.size),
                 "offset": {"along": int(paths.plaza.shift[0]),
                            "inward": int(paths.plaza.shift[1])}}
    data = copy.deepcopy(data)
    data.pop("paths", None)
    data.pop("trees", None)
    data["metadata"]["version"] = PATHS_FORMAT_VERSION
    section: dict[str, Any] = {"width": float(paths.width), "cells": _cells_v33(paths.cells),
                               "bridge_cells": _cells_v33(paths.bridge_cells), "plaza": plaza,
                               "anchors": _cells_v33(paths.anchors)}
    if debug:
        section["debug"] = _paths_debug_v33(paths)
    data["paths"] = section
    return data


def _tree_item_v34(item) -> dict[str, Any]:
    """Arbre 3.4 : ``{x, z, radius, layer}``, plus ``grove`` (indice de
    l'ancrage) sur les arbres d'ancrage seuls."""
    entry: dict[str, Any] = {"x": int(item.x), "z": int(item.z), "radius": int(item.radius), "layer": item.layer}
    if item.grove is not None:
        entry["grove"] = int(item.grove)
    return entry


def _trees_debug_v34(trees: CourseTrees) -> dict[str, Any]:
    """Détail des arbres (``--trees-debug``) : ``counts`` (arbres par couche),
    ``skips`` (par couche, défauts par motif) et ``groves`` (un par ancrage,
    dans l'ordre de ``paths.anchors``)."""
    return {"counts": {name: int(n) for name, n in trees.counts.items()},
            "skips": {name: {motif: int(n) for motif, n in motifs.items()} for name, motifs in trees.skips.items()},
            "groves": [{"index": int(grove.index), "anchor": [int(v) for v in grove.anchor],
                        "placed": len(grove.trees), "target": int(grove.target),
                        "trees": [[int(v) for v in tree] for tree in grove.trees], "motif": grove.motif}
                       for grove in trees.groves]}


def with_trees(data: dict[str, Any], trees: CourseTrees, *, debug: bool = False) -> dict[str, Any]:
    """JSON 3.4 : le dict 3.3 ``data`` (``with_paths``) plus la clé de premier
    niveau ``trees`` (dernière clé), couche à plat ``{items: [...]}`` dans
    l'ordre de pose (``_tree_item_v34``), et ``metadata.version`` "3.4" ; avec
    ``debug``, une sous-clé ``trees.debug`` (dernière ; ``_trees_debug_v34``).
    Tout le reste est repris tel quel. ``ValueError`` si ``data`` n'a pas de
    chemins (versions en escalier) ou si une couronne sort de la carte.
    ``data`` n'est pas modifié."""
    from .dressing.trees import CourseTrees  # paresseux (cf. en-tête)
    if not isinstance(trees, CourseTrees):
        raise TypeError("trees doit être un CourseTrees")
    if "paths" not in data:
        raise ValueError("arbres sans chemins : appliquer with_paths d'abord")
    width, height = data["terrain"]["width"], data["terrain"]["height"]
    for item in trees.items:
        if not (item.radius <= item.x < width - item.radius and item.radius <= item.z < height - item.radius):
            raise ValueError(f"arbres : couronne de ({item.x}, {item.z}) hors de la carte")
    data = copy.deepcopy(data)
    data.pop("trees", None)
    data["metadata"]["version"] = TREES_FORMAT_VERSION
    section: dict[str, Any] = {"items": [_tree_item_v34(item) for item in trees.items]}
    if debug:
        section["debug"] = _trees_debug_v34(trees)
    data["trees"] = section
    return data


def write_json_atomic(path: str | Path, data: dict[str, Any]) -> None:
    """Écrit ``data`` en JSON (indenté, UTF-8) de façon atomique : fichier
    temporaire du même dossier, ``flush`` + ``os.fsync``, puis ``os.replace``.
    En cas d'échec, un fichier existant à ``path`` reste intact et aucun
    temporaire ne subsiste.

    Si ``path`` est un lien symbolique, le lien lui-même est remplacé par un
    fichier ordinaire (sa cible n'est pas modifiée). Le fichier est créé à
    neuf : ses permissions viennent de l'umask, pas d'un fichier existant."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.{uuid.uuid4().hex}.tmp")
    try:
        with open(tmp, "x", encoding="utf-8") as handle:
            json.dump(data, handle, indent=2, ensure_ascii=False)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise

