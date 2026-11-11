"""Habillage depuis le seul JSON du routage : point d'entrée ``dress_course_json``.

Étape 2 du pipeline (« bouton 2 ») : le JSON 3.x écrit par
``golfgen.exporter.muirfield_to_dict`` porte, en pleine précision, tout ce que
lit l'habillage — trous (``par``, ``tee``, ``green``, ``doglegs``, ``width``,
``rough_margin``), ordre des liaisons (``from``/``to``), clubhouse, taille de
carte — et le relief float32 sans perte (``terrain.elevation_f32``). On en
reconstruit le ``CourseLayout`` (liaisons déduites des trous et du clubhouse
par ``NineLayout.from_holes``, mêmes contrôles qu'au routage), le masque
d'eau brut par ``golfgen.routing.sites.water_mask`` et le masque sec par
``DryMask.from_water`` (sources uniques des critères), puis
on habille par ``dress_course`` avec le relief relu (eau du lot 1) : même
habillage, au bit près, que sur le parcours en mémoire habillé avec le même
relief. Un JSON produit avant ces champs (3.0/3.1 arrondis à
2 décimales) est refusé (``CourseJsonError``) : l'habiller donnerait des
formes légèrement différentes, en silence.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

import numpy as np

from golfgen.dressing.course import dress_course
from golfgen.dressing.model import CourseDressing
from golfgen.routing.model import ControlPoint, CourseLayout, ElasticHole, NineLayout
from golfgen.routing.sites import WATER_LEVEL, DryMask, WaterMask, water_mask
from golfgen.seed import seed_u64
from golfgen.terrain import relief_from_f32_block


class CourseJsonError(ValueError):
    """JSON de parcours inutilisable pour l'habillage (version, champ
    manquant, incohérence) ; message en français."""


@dataclass(frozen=True, slots=True, eq=False)
class CourseInput:
    """Résultat de l'étape 1 relu depuis le JSON : ce que l'habillage peut
    lire. ``layout`` : tracé reconstruit ; ``seed`` : seed u64 du routage
    (``seed_u64`` de ``metadata.seed``) ; ``relief`` : float32 ``(h, w)``
    identique au relief du routage ; ``water`` : son ``WaterMask`` (vraie
    berge, lu par l'habillage) ; ``dry`` : son ``DryMask`` (déduit de
    ``water``, celui du routeur). Porte ``layout`` comme un
    ``MuirfieldResult`` : ``dress_course`` l'accepte."""

    layout: CourseLayout
    seed: int
    relief: np.ndarray
    water: WaterMask
    dry: DryMask


# Champs ajoutés pour l'habillage depuis le JSON : leur absence signe un
# export antérieur, arrondi à 2 décimales.
_HOLE_FIELDS = ("id", "nine", "par", "width", "rough_margin", "tee", "green", "doglegs")
_LINK_FIELDS = ("from", "to")
# écart toléré entre ``length`` exportée (arrondie) et celle reconstruite
_LENGTH_TOLERANCE = 0.005


def _point(data: Mapping[str, Any], where: str) -> ControlPoint:
    try:
        return ControlPoint(x=data["x"], y=data["y"])
    except (KeyError, TypeError, ValueError) as exc:
        raise CourseJsonError(f"{where} : point invalide ({exc})") from None


def _missing(data: Mapping[str, Any]) -> list[str]:
    """Champs d'entrée de l'habillage absents, désignés par leur chemin."""
    missing = []
    terrain, routing = data.get("terrain", {}), data.get("routing", {})
    if not isinstance(terrain, Mapping) or not isinstance(routing, Mapping):
        raise CourseJsonError("terrain et routing doivent être des objets")
    if "elevation_f32" not in terrain:
        missing.append("terrain.elevation_f32")
    for key in ("holes", "links", "clubhouse"):
        if key not in routing:
            missing.append(f"routing.{key}")
    for key, fields in (("holes", _HOLE_FIELDS), ("links", _LINK_FIELDS)):
        items = routing.get(key, [])
        if not isinstance(items, list):
            raise CourseJsonError(f"routing.{key} doit être une liste")
        bad = next((i for i, item in enumerate(items) if not isinstance(item, Mapping)), None)
        if bad is not None:
            raise CourseJsonError(f"routing.{key}[{bad}] doit être un objet")
        for field in fields:
            if any(field not in item for item in items):
                missing.append(f"routing.{key}[].{field}")
    return missing


def _r2(value: float) -> float:
    """Arrondi des statistiques exportées (``golfgen.exporter._r2``)."""
    return round(float(value), 2)


def _check_length(exported: Any, rebuilt: float, what: str, version: str) -> None:
    """``length`` exportée (arrondie à 2 décimales) ≟ celle du tracé
    reconstruit : un tee, green ou coude retouché à la main est refusé
    (``with_dressing`` recopie les longueurs telles quelles)."""
    if (isinstance(exported, bool) or not isinstance(exported, (int, float))
            or not abs(exported - _r2(rebuilt)) <= _LENGTH_TOLERANCE):
        raise CourseJsonError(
            f"tracé du JSON {version} incohérent : {what}, longueur exportée "
            f"{exported!r} ≠ {_r2(rebuilt)} reconstruite (tee, green ou coude modifié ?)")


def _end(order: int | None) -> int | str:
    """Extrémité d'une liaison telle qu'exportée (``from``/``to``)."""
    return "clubhouse" if order is None else order


def course_input_from_json(data: Mapping[str, Any]) -> CourseInput:
    """Relit le résultat de l'étape 1 dans un dict JSON 3.x (``json.load``
    du fichier, ou le dict de ``muirfield_to_dict``). ``CourseJsonError``
    si la version n'est pas 3.x, si un champ d'entrée de l'habillage manque
    (JSON antérieur, arrondi) ou si le tracé relu est incohérent (contrôles
    de ``CourseLayout``, ordre des liaisons, ``length`` des trous et
    liaisons ≠ celles du tracé reconstruit à 0,005 près) ; le niveau d'eau du JSON doit être celui du
    routeur (``WATER_LEVEL``), sinon le masque sec ne serait pas le sien."""
    if not isinstance(data, Mapping):
        raise CourseJsonError("le JSON d'un parcours doit contenir un objet")
    metadata = data.get("metadata", {})
    if not isinstance(metadata, Mapping):
        raise CourseJsonError("metadata doit être un objet")
    version = metadata.get("version")
    if not isinstance(version, str) or not version.startswith("3."):
        raise CourseJsonError(f"version de JSON non prise en charge : {version!r} (attendu 3.x)")
    missing = _missing(data)
    if missing:
        raise CourseJsonError(
            f"JSON {version} sans les entrées de l'habillage ({', '.join(missing)}) : "
            "export antérieur, coordonnées arrondies à 2 décimales ; relancer le routage "
            "(pipeline.py) pour obtenir un JSON habillable")

    terrain, routing = data["terrain"], data["routing"]
    width, height = terrain.get("width"), terrain.get("height")
    if (any(not isinstance(side, int) or isinstance(side, bool) or side <= 0
            for side in (width, height))
            or (metadata.get("width"), metadata.get("height")) != (float(width), float(height))):
        raise CourseJsonError(f"taille de carte incohérente : terrain {width}×{height}, "
                              f"metadata {metadata.get('width')}×{metadata.get('height')}")
    if terrain.get("water_level") != round(WATER_LEVEL, 2):
        raise CourseJsonError(f"niveau d'eau {terrain.get('water_level')!r} ≠ celui du "
                              f"routeur ({WATER_LEVEL})")
    if not isinstance(terrain["elevation_f32"], Mapping):
        raise CourseJsonError(f"JSON {version} : relief illisible "
                              "(terrain.elevation_f32 doit être un objet)")
    try:
        seed = seed_u64(int(metadata["seed"]))
        relief = relief_from_f32_block(terrain["elevation_f32"], width, height)
    except (KeyError, TypeError, ValueError) as exc:
        raise CourseJsonError(f"JSON {version} : seed ou relief illisible ({exc})") from None

    try:
        holes = {}
        for item in routing["holes"]:
            if item["id"] in holes:
                raise ValueError(f"trou {item['id']!r} en double")
            holes[item["id"]] = (item["nine"], ElasticHole(
                order=item["id"], par=item["par"],
                tee=_point(item["tee"], f"trou {item['id']} tee"),
                green=_point(item["green"], f"trou {item['id']} green"),
                doglegs=tuple(_point(p, f"trou {item['id']} coude") for p in item["doglegs"]),
                width=item["width"], rough_margin=item["rough_margin"]))
        clubhouse = _point(routing["clubhouse"], "clubhouse")
        nines = {}
        for name, start in (("front", 1), ("back", 10)):
            members = sorted((hole for nine, hole in holes.values() if nine == name),
                             key=lambda hole: hole.order)
            # liaisons déduites des trous et du clubhouse : aucune donnée en double
            nines[name] = NineLayout.from_holes(start, clubhouse, tuple(members))
        if len(routing["holes"]) != 18 or len(routing["links"]) != 20:
            raise ValueError("18 trous et 20 liaisons attendus")
        layout = CourseLayout(seed=seed, width=float(width), height=float(height),
                              clubhouse=clubhouse, front=nines["front"], back=nines["back"])
        expected = [(_end(link.from_hole_order), _end(link.to_hole_order))
                    for link in layout.links]
        exported = [(link["from"], link["to"]) for link in routing["links"]]
    except CourseJsonError:
        raise
    except (KeyError, TypeError, ValueError) as exc:
        raise CourseJsonError(f"tracé du JSON {version} incohérent : {exc}") from None
    if exported != expected:
        bad = next(i for i, pair in enumerate(exported) if pair != expected[i])
        raise CourseJsonError(
            f"tracé du JSON {version} incohérent : liaison {bad} "
            f"{exported[bad][0]!r} → {exported[bad][1]!r}, attendue "
            f"{expected[bad][0]!r} → {expected[bad][1]!r} (ordre de jeu)")
    rebuilt = {hole.order: hole for hole in layout.holes}
    for item in routing["holes"]:
        _check_length(item.get("length"), rebuilt[item["id"]].length,
                      f"trou {item['id']}", version)
    for i, (item, link) in enumerate(zip(routing["links"], layout.links)):
        _check_length(item.get("length"), link.length,
                      f"liaison {i} {item['from']!r} → {item['to']!r}", version)
    water = water_mask(relief)
    return CourseInput(layout=layout, seed=seed, relief=relief, water=water,
                       dry=DryMask.from_water(water))


def dress_course_json(data: Mapping[str, Any], style: str) -> CourseDressing:
    """Habillage (``dress_course``) du parcours décrit par le JSON ``data``
    pour le ``style`` donné, sans re-router : relu par
    ``course_input_from_json`` (``CourseJsonError`` si le JSON n'est pas
    habillable). Même résultat, au bit près, que ``dress_course`` sur le
    résultat du routage dont ``data`` est l'export, habillé avec son relief
    (``dress_course(..., relief=heightmap)``). ``DressingError`` comme
    ``dress_course``. Le relief relu (``CourseInput.relief``) est passé à
    ``dress_course`` : greens et départs tenus hors de l'eau (lot 1 eau)."""
    course = course_input_from_json(data)
    return dress_course(course, seed=course.seed, style=style, relief=course.relief)
