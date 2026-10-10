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


# Types de green, dans l'ordre des poids de ``StyleSpec.kind_weights`` et des
# plages de ``StyleSpec.kind_aspects`` : rond, allongé, haricot.
GREEN_KINDS = ("round", "elongated", "bean")


@dataclass(frozen=True, slots=True)
class StyleSpec:
    """Paramètres d'un style d'habillage.

    ``green_rho`` : plage de ρ, diamètre du disque de même aire que le green
    rapporté à la largeur ``l`` du cœur du trou ; ``green_area`` : bornes de
    l'aire visée (blocs², avant réduction éventuelle par l'inclusion dans le
    cœur), ``π/4·(ρ·l)²`` y étant ramenée ; ``harmonic_amplitude`` : écart
    radial relatif maximal dû aux harmoniques (``GREEN_HARMONICS``, somme des
    amplitudes) ; ``kind_weights`` : parts NETTES visées des types
    ``GREEN_KINDS`` (après bascules), atteintes par les trois constantes
    suivantes, qui en sont dérivées par mesure ; ``kind_aspects`` : plage de
    l'allongement tiré (grand axe / petit axe de l'ellipse de base) par
    type ; ``bean_depth`` : plage du creux du haricot (blocs, distance du
    contour à son enveloppe convexe) ; ``bean_min_area`` : aire visée
    minimale (blocs²) d'un haricot, en dessous le green est rond ou allongé ;
    ``bean_given_eligible`` : P(haricot tiré | aire visée ≥
    ``bean_min_area``) ; ``round_given_plain`` : P(rond | haricot non tiré),
    éligible ou non (le reste est allongé)."""

    name: str
    green_rho: tuple[float, float]
    green_area: tuple[float, float]
    harmonic_amplitude: float
    kind_weights: tuple[float, float, float]
    kind_aspects: tuple[tuple[float, float], tuple[float, float], tuple[float, float]]
    bean_depth: tuple[float, float]
    bean_min_area: float
    bean_given_eligible: float
    round_given_plain: float


# Tailles (R1c, validées mais PROVISOIRES) : links ρ 0,68–0,85 et aire
# 50–135 blocs², parkland ρ 0,62–0,76 et 42–105 ; elles remplacent les plages
# fixes 60–95 / 50–75. Provisoire, retour à 60–95 / 50–75 si les bunkers ne
# passent pas.
# Types (parts nettes visées) : links rond 0,30 / allongé 0,35 / haricot
# 0,35, parkland 0,30 / 0,40 / 0,30 ; allongé plafonné à 1,75 en parkland ;
# allongement de base du haricot 1,15–1,45 (l'encoche l'allonge, mesuré
# ≈ 1,5–1,8) ; creux du haricot 1,5–2,0 blocs dans les deux styles (au-delà
# de ≈ 2, l'encoche ±90° bornée à 0,9 du rayon ne l'atteint pas).
#
# Éligibilité et tirage des types (R1b) : mesurés sur 30 seeds × 2 formats
# (400x300 et 300x400, patron random), soit 1080 trous par style, en forçant
# le haricot sur chaque trou (la bascule ne dépend que de l'aire et des
# tirages de forme, pas du tirage du type) :
# - ``bean_min_area`` = plus petite aire visée entière à partir de laquelle
#   le taux de bascule haricot → allongé parmi les éligibles est ≤ 5 % (il
#   reste ≤ 5 % au-dessus) ;
# - ``bean_given_eligible`` = P_eff = part de haricots visée / (part
#   d'éligibles × (1 − taux de bascule)), plafonnée à 1 : compense les
#   bascules ;
# - ``round_given_plain`` = part de ronds visée / (1 − P_eff × part
#   d'éligibles) : les bascules grossissent les allongés, le rapport des
#   poids nominaux (0,30 / 0,65 en links) ferait dériver les ronds d'environ
#   0,5 point vers le bas.
# links : seuil 84 blocs² ; éligibles 547/1080 = 50,6 % ; bascule 24/547
#   = 4,4 % ; P_eff = 0,35 / (0,506 × 0,956) = 0,723 ; rond 0,30 / (1 − 0,723
#   × 0,506) = 0,473.
# parkland : seuil 77 blocs² (inchangé) ; éligibles 413/1080 = 38,2 % ;
#   bascule 19/413 = 4,6 % ; P_eff = 0,30 / (0,382 × 0,954) = 0,822 ; rond
#   0,30 / (1 − 0,822 × 0,382) = 0,438.
STYLE_SPECS: Mapping[str, StyleSpec] = MappingProxyType({
    "links": StyleSpec("links", green_rho=(0.68, 0.85), green_area=(50.0, 135.0),
                       harmonic_amplitude=0.12,
                       kind_weights=(0.30, 0.35, 0.35),
                       kind_aspects=((1.0, 1.3), (1.45, 1.9), (1.15, 1.45)),
                       bean_depth=(1.5, 2.0),
                       bean_min_area=84.0, bean_given_eligible=0.723,
                       round_given_plain=0.473),
    "parkland": StyleSpec("parkland", green_rho=(0.62, 0.76), green_area=(42.0, 105.0),
                          harmonic_amplitude=0.06,
                          kind_weights=(0.30, 0.40, 0.30),
                          kind_aspects=((1.0, 1.3), (1.45, 1.75), (1.15, 1.45)),
                          bean_depth=(1.5, 2.0),
                          bean_min_area=77.0, bean_given_eligible=0.822,
                          round_given_plain=0.438),
})


@dataclass(frozen=True, slots=True)
class GreenShape:
    """Contour du green d'un trou, en blocs, coordonnées arrondies à 2 décimales.

    ``outline`` : polygone simple fermé implicitement (dernier sommet relié au
    premier), aire signée positive dans le repère (x, y) de la carte (sens
    horaire à l'écran, y vers le bas) ; ``center`` : centre de la forme
    (avant réduction : point de l'axe reculé depuis le drapeau, cf.
    ``golfgen.dressing.green``) ; ``area`` : aire du polygone arrondi. ``target_area`` : aire
    visée avant inclusion ; ``scale`` : facteur de l'homothétie (centrée sur le
    drapeau) appliquée pour tenir dans le cœur, 1.0 sans réduction ;
    ``shrink_steps`` : nombre de pas ×0,95 appliqués ; ``kind`` : type final
    (``GREEN_KINDS``) ; ``bean_fallback`` : haricot tiré devenu allongé faute
    de col suffisant ; ``kind`` et ``bean_fallback`` sont internes, non
    exportés."""

    outline: tuple[Point, ...]
    center: Point
    area: float
    target_area: float
    scale: float = 1.0
    shrink_steps: int = 0
    kind: str = "round"
    bean_fallback: bool = False

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
