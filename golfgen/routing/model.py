"""Contrats immuables du routage Muirfield (historique : ``docs/muirfield-spike.md``).

Ce module décrit un parcours et ses liaisons sans contenir de solveur ni
d'oracle géométrique. Les invariants structurels sont vérifiés immédiatement ;
les contraintes que l'optimiseur doit pouvoir violer temporairement (plages de
longueur et de largeur, limites de carte, collisions) restent consultables mais
seront contrôlées par l'oracle indépendant de l'étape 2.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
import json
import math
from types import MappingProxyType
from typing import Any, Mapping


SCHEMA_VERSION = 1
GLOBAL_PAR_QUOTA = MappingProxyType({3: 4, 4: 10, 5: 4})


def _as_finite_float(value: float, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"{field} doit être un nombre fini")
    result = float(value)
    if not math.isfinite(result):
        raise ValueError(f"{field} doit être fini")
    return result


def _as_hole_order(value: int | None, field: str) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{field} doit être un entier ou None")
    if not 1 <= value <= 18:
        raise ValueError(f"{field} doit être compris entre 1 et 18")
    return value


@dataclass(frozen=True, slots=True)
class HoleClassSpec:
    """Dimensions finales validées pour une classe de par."""

    par: int
    length_min: float
    length_max: float
    width_min: float
    width_max: float
    coarse_max_doglegs: int = 1
    final_max_doglegs: int = 2

    def __post_init__(self) -> None:
        if isinstance(self.par, bool) or not isinstance(self.par, int) or self.par not in (3, 4, 5):
            raise ValueError("par doit valoir 3, 4 ou 5")
        for field in ("length_min", "length_max", "width_min", "width_max"):
            object.__setattr__(self, field, _as_finite_float(getattr(self, field), field))
        if not 0.0 < self.length_min <= self.length_max:
            raise ValueError("plage de longueur invalide")
        if not 0.0 < self.width_min <= self.width_max:
            raise ValueError("plage de largeur invalide")
        if (isinstance(self.coarse_max_doglegs, bool)
                or not isinstance(self.coarse_max_doglegs, int)
                or isinstance(self.final_max_doglegs, bool)
                or not isinstance(self.final_max_doglegs, int)):
            raise TypeError("les bornes de doglegs doivent être des entiers")
        if not 0 <= self.coarse_max_doglegs <= self.final_max_doglegs:
            raise ValueError("bornes de doglegs invalides")

    def accepts_length(self, length: float) -> bool:
        return self.length_min <= length <= self.length_max

    def accepts_width(self, width: float) -> bool:
        return self.width_min <= width <= self.width_max


# Plages réalistes (1 bloc = 3 m) décidées le 2026-10-07 pour l'étape M :
# par 3 ≈ 135–210 m, par 4 ≈ 300–435 m, par 5 ≈ 435–555 m.
PAR_SPECS: Mapping[int, HoleClassSpec] = MappingProxyType({
    3: HoleClassSpec(3, 45.0, 70.0, 10.0, 15.0),
    4: HoleClassSpec(4, 100.0, 145.0, 11.0, 17.0),
    5: HoleClassSpec(5, 145.0, 185.0, 12.0, 18.0),
})


@dataclass(frozen=True, slots=True)
class ControlPoint:
    """Point continu employé par les axes et les liaisons."""

    x: float
    y: float

    def __post_init__(self) -> None:
        object.__setattr__(self, "x", _as_finite_float(self.x, "x"))
        object.__setattr__(self, "y", _as_finite_float(self.y, "y"))

    def to_dict(self) -> dict[str, float]:
        return {"x": self.x, "y": self.y}

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> ControlPoint:
        return cls(x=data["x"], y=data["y"])


@dataclass(frozen=True, slots=True)
class ElasticHole:
    """Axe de trou déformable, sans empreinte géométrique dérivée."""

    order: int
    par: int
    tee: ControlPoint
    green: ControlPoint
    doglegs: tuple[ControlPoint, ...] = ()
    width: float = 12.0
    rough_margin: float = 5.0

    def __post_init__(self) -> None:
        order = _as_hole_order(self.order, "order")
        if order is None:
            raise TypeError("order doit être un entier")
        object.__setattr__(self, "order", order)
        if isinstance(self.par, bool) or not isinstance(self.par, int) or self.par not in PAR_SPECS:
            raise ValueError("par doit valoir 3, 4 ou 5")
        if not isinstance(self.tee, ControlPoint) or not isinstance(self.green, ControlPoint):
            raise TypeError("tee et green doivent être des ControlPoint")
        doglegs = tuple(self.doglegs)
        if any(not isinstance(point, ControlPoint) for point in doglegs):
            raise TypeError("les doglegs doivent être des ControlPoint")
        if len(doglegs) > PAR_SPECS[self.par].final_max_doglegs:
            raise ValueError("un trou ne peut pas avoir plus de deux doglegs")
        object.__setattr__(self, "doglegs", doglegs)
        object.__setattr__(self, "width", _as_finite_float(self.width, "width"))
        object.__setattr__(self, "rough_margin", _as_finite_float(self.rough_margin, "rough_margin"))
        if self.width <= 0.0:
            raise ValueError("width doit être strictement positif")
        if self.rough_margin < 0.0:
            raise ValueError("rough_margin doit être positif ou nul")
        if any(first == second for first, second in zip(self.axis, self.axis[1:])):
            raise ValueError("l'axe ne peut pas contenir de segment nul")

    @property
    def axis(self) -> tuple[ControlPoint, ...]:
        return (self.tee, *self.doglegs, self.green)

    @property
    def length(self) -> float:
        return math.fsum(math.dist((a.x, a.y), (b.x, b.y))
                         for a, b in zip(self.axis, self.axis[1:]))

    @property
    def dimensions_are_final(self) -> bool:
        spec = PAR_SPECS[self.par]
        return spec.accepts_length(self.length) and spec.accepts_width(self.width)

    def to_dict(self) -> dict[str, Any]:
        return {
            "doglegs": [point.to_dict() for point in self.doglegs],
            "green": self.green.to_dict(),
            "order": self.order,
            "par": self.par,
            "rough_margin": self.rough_margin,
            "tee": self.tee.to_dict(),
            "width": self.width,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> ElasticHole:
        return cls(
            order=data["order"],
            par=data["par"],
            tee=ControlPoint.from_dict(data["tee"]),
            green=ControlPoint.from_dict(data["green"]),
            doglegs=tuple(ControlPoint.from_dict(point) for point in data.get("doglegs", ())),
            width=data["width"],
            rough_margin=data["rough_margin"],
        )


@dataclass(frozen=True, slots=True)
class WalkingLink:
    """Liaison entre clubhouse et trou, ou entre deux trous consécutifs."""

    start: ControlPoint
    end: ControlPoint
    from_hole_order: int | None
    to_hole_order: int | None

    def __post_init__(self) -> None:
        if not isinstance(self.start, ControlPoint) or not isinstance(self.end, ControlPoint):
            raise TypeError("start et end doivent être des ControlPoint")
        object.__setattr__(self, "from_hole_order",
                           _as_hole_order(self.from_hole_order, "from_hole_order"))
        object.__setattr__(self, "to_hole_order",
                           _as_hole_order(self.to_hole_order, "to_hole_order"))
        if self.from_hole_order is None and self.to_hole_order is None:
            raise ValueError("une liaison doit appartenir à au moins un trou")
        if (self.from_hole_order is not None
                and self.from_hole_order == self.to_hole_order):
            raise ValueError("une liaison ne peut pas relier un trou à lui-même")
        if self.start == self.end:
            raise ValueError("une liaison ne peut pas avoir une longueur nulle")

    @property
    def length(self) -> float:
        return math.dist((self.start.x, self.start.y), (self.end.x, self.end.y))

    def to_dict(self) -> dict[str, Any]:
        return {
            "end": self.end.to_dict(),
            "from_hole_order": self.from_hole_order,
            "start": self.start.to_dict(),
            "to_hole_order": self.to_hole_order,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> WalkingLink:
        return cls(
            start=ControlPoint.from_dict(data["start"]),
            end=ControlPoint.from_dict(data["end"]),
            from_hole_order=data["from_hole_order"],
            to_hole_order=data["to_hole_order"],
        )


@dataclass(frozen=True, slots=True)
class NineLayout:
    """Neuf trous ordonnés et leurs dix liaisons explicites."""

    start_order: int
    holes: tuple[ElasticHole, ...]
    links: tuple[WalkingLink, ...]

    def __post_init__(self) -> None:
        if isinstance(self.start_order, bool) or not isinstance(self.start_order, int):
            raise TypeError("start_order doit être un entier")
        if self.start_order not in (1, 10):
            raise ValueError("start_order doit valoir 1 ou 10")
        holes = tuple(self.holes)
        links = tuple(self.links)
        object.__setattr__(self, "holes", holes)
        object.__setattr__(self, "links", links)
        if len(holes) != 9:
            raise ValueError("un nine doit contenir exactement neuf trous")
        if any(not isinstance(hole, ElasticHole) for hole in holes):
            raise TypeError("holes doit contenir des ElasticHole")
        expected_orders = tuple(range(self.start_order, self.start_order + 9))
        if tuple(hole.order for hole in holes) != expected_orders:
            raise ValueError(f"ordres attendus pour le nine : {expected_orders}")
        if len(links) != 10:
            raise ValueError("un nine doit contenir exactement dix liaisons")
        if any(not isinstance(link, WalkingLink) for link in links):
            raise TypeError("links doit contenir des WalkingLink")
        self._validate_link_sequence()

    def _validate_link_sequence(self) -> None:
        first_link = self.links[0]
        if ((first_link.from_hole_order, first_link.to_hole_order)
                != (None, self.holes[0].order) or first_link.end != self.holes[0].tee):
            raise ValueError("la première liaison doit aller du clubhouse au premier tee")

        for index, (previous, current) in enumerate(zip(self.holes, self.holes[1:]), start=1):
            link = self.links[index]
            if ((link.from_hole_order, link.to_hole_order) != (previous.order, current.order)
                    or link.start != previous.green or link.end != current.tee):
                raise ValueError("les liaisons internes doivent relier green et tee consécutifs")

        last_link = self.links[-1]
        if ((last_link.from_hole_order, last_link.to_hole_order)
                != (self.holes[-1].order, None) or last_link.start != self.holes[-1].green):
            raise ValueError("la dernière liaison doit aller du dernier green au clubhouse")

    @classmethod
    def from_holes(cls, start_order: int, clubhouse: ControlPoint,
                   holes: tuple[ElasticHole, ...]) -> NineLayout:
        holes = tuple(holes)
        if not holes:
            raise ValueError("holes ne peut pas être vide")
        links = [WalkingLink(clubhouse, holes[0].tee, None, holes[0].order)]
        links.extend(WalkingLink(previous.green, current.tee, previous.order, current.order)
                     for previous, current in zip(holes, holes[1:]))
        links.append(WalkingLink(holes[-1].green, clubhouse, holes[-1].order, None))
        return cls(start_order=start_order, holes=holes, links=tuple(links))

    def to_dict(self) -> dict[str, Any]:
        return {
            "holes": [hole.to_dict() for hole in self.holes],
            "links": [link.to_dict() for link in self.links],
            "start_order": self.start_order,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> NineLayout:
        return cls(
            start_order=data["start_order"],
            holes=tuple(ElasticHole.from_dict(hole) for hole in data["holes"]),
            links=tuple(WalkingLink.from_dict(link) for link in data["links"]),
        )


@dataclass(frozen=True, slots=True)
class CourseLayout:
    """Parcours complet : deux nines partageant un clubhouse."""

    seed: int
    width: float
    height: float
    clubhouse: ControlPoint
    front: NineLayout
    back: NineLayout

    def __post_init__(self) -> None:
        if isinstance(self.seed, bool) or not isinstance(self.seed, int):
            raise TypeError("seed doit être un entier")
        object.__setattr__(self, "width", _as_finite_float(self.width, "width"))
        object.__setattr__(self, "height", _as_finite_float(self.height, "height"))
        if self.width <= 0.0 or self.height <= 0.0:
            raise ValueError("les dimensions de carte doivent être strictement positives")
        if not isinstance(self.clubhouse, ControlPoint):
            raise TypeError("clubhouse doit être un ControlPoint")
        if not 0.0 <= self.clubhouse.x <= self.width or not 0.0 <= self.clubhouse.y <= self.height:
            raise ValueError("le clubhouse doit être dans la carte")
        if not isinstance(self.front, NineLayout) or not isinstance(self.back, NineLayout):
            raise TypeError("front et back doivent être des NineLayout")
        if self.front.start_order != 1 or self.back.start_order != 10:
            raise ValueError("le front doit commencer au trou 1 et le back au trou 10")
        for nine in (self.front, self.back):
            if nine.links[0].start != self.clubhouse or nine.links[-1].end != self.clubhouse:
                raise ValueError("chaque nine doit partir du clubhouse et y revenir")
        quota = Counter(hole.par for hole in self.holes)
        if quota != Counter(GLOBAL_PAR_QUOTA):
            raise ValueError(f"quota global attendu : {dict(GLOBAL_PAR_QUOTA)}")

    @property
    def holes(self) -> tuple[ElasticHole, ...]:
        return self.front.holes + self.back.holes

    @property
    def links(self) -> tuple[WalkingLink, ...]:
        return self.front.links + self.back.links

    def to_dict(self) -> dict[str, Any]:
        return {
            "back": self.back.to_dict(),
            "clubhouse": self.clubhouse.to_dict(),
            "front": self.front.to_dict(),
            "height": self.height,
            "schema_version": SCHEMA_VERSION,
            "seed": self.seed,
            "width": self.width,
        }

    def to_json(self, *, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent, sort_keys=True, allow_nan=False) + "\n"

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> CourseLayout:
        version = data.get("schema_version")
        if version != SCHEMA_VERSION:
            raise ValueError(f"schema_version non supportée : {version!r}")
        return cls(
            seed=data["seed"],
            width=data["width"],
            height=data["height"],
            clubhouse=ControlPoint.from_dict(data["clubhouse"]),
            front=NineLayout.from_dict(data["front"]),
            back=NineLayout.from_dict(data["back"]),
        )

    @classmethod
    def from_json(cls, payload: str) -> CourseLayout:
        data = json.loads(payload)
        if not isinstance(data, dict):
            raise ValueError("le JSON d'un parcours doit contenir un objet")
        return cls.from_dict(data)
