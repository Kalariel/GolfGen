"""Modèle de l'habillage : styles et formes par trou.

Les structures sont figées et extensibles : ``HoleDressing`` porte aujourd'hui
le green ; les tees et le green double viendront comme champs optionnels
supplémentaires (défaut ``None``), sans changer les champs existants.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType


Point = tuple[float, float]


class DressingError(Exception):
    """Échec ATTENDU de l'habillage (segment final nul, green impossible à
    inclure dans le cœur…) : l'appelant peut proposer une autre seed. Toute
    autre exception levée pendant l'habillage est un bogue et doit remonter."""


@dataclass(frozen=True, slots=True)
class StyleSpec:
    """Paramètres d'un style d'habillage.

    ``green_area`` : plage d'aire visée du green (blocs², avant réduction
    éventuelle par l'inclusion dans le cœur) ; ``harmonic_amplitude`` : écart
    radial relatif maximal dû aux harmoniques 2–4 (somme des amplitudes)."""

    name: str
    green_area: tuple[float, float]
    harmonic_amplitude: float


# Plages provisoires (habillage, lot 1) : links 60–95 blocs², parkland 50–75.
STYLE_SPECS: Mapping[str, StyleSpec] = MappingProxyType({
    "links": StyleSpec("links", (60.0, 95.0), 0.12),
    "parkland": StyleSpec("parkland", (50.0, 75.0), 0.06),
})


@dataclass(frozen=True, slots=True)
class GreenShape:
    """Contour du green d'un trou, en blocs, coordonnées arrondies à 2 décimales.

    ``outline`` : polygone simple fermé implicitement (dernier sommet relié au
    premier), aire signée positive dans le repère (x, y) de la carte (sens
    horaire à l'écran, y vers le bas) ; ``center`` : centre de la forme
    (avant réduction : point de l'axe reculé de 0 à 1,5 bloc depuis le
    drapeau) ; ``area`` : aire du polygone arrondi. ``target_area`` : aire
    visée avant inclusion ; ``scale`` : facteur de l'homothétie (centrée sur le
    drapeau) appliquée pour tenir dans le cœur, 1.0 sans réduction ;
    ``shrink_steps`` : nombre de pas ×0,95 appliqués."""

    outline: tuple[Point, ...]
    center: Point
    area: float
    target_area: float
    scale: float = 1.0
    shrink_steps: int = 0

    @property
    def reduced(self) -> bool:
        return self.shrink_steps > 0


@dataclass(frozen=True, slots=True)
class HoleDressing:
    """Habillage d'un trou (``order`` = numéro du trou). Extensible : tees et
    green double s'ajouteront ici comme champs optionnels."""

    order: int
    green: GreenShape


@dataclass(frozen=True, slots=True)
class CourseDressing:
    """Habillage d'un parcours : ``holes`` = ``{order: HoleDressing}`` trié par
    numéro de trou, ``style`` = clé de ``STYLE_SPECS``."""

    style: str
    holes: Mapping[int, HoleDressing]

    def __getitem__(self, order: int) -> HoleDressing:
        return self.holes[order]
