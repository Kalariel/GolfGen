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
    l'allongement tiré par type (rond, allongé : grand axe / petit axe de
    l'ellipse de base ; haricot : λ, longueur dépliée / largeur de la
    capsule courbée) ; ``bean_depth`` : plage du creux du haricot (blocs, distance du
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
# 0,35, parkland 0,30 / 0,40 / 0,30 ; allongé plafonné à 1,75 en parkland.
# Haricot (capsule courbée, ``golfgen.dressing.green._bean``) : la plage
# « allongement » du haricot dans ``kind_aspects`` est celle de λ = longueur
# dépliée / largeur de la capsule, 2,15–2,24 dans les deux styles (au-delà
# de ≈ 2,24 en links, des haricots dépassent 2,0 d'allongement : saucisses ;
# en deçà de 2,15, l'arc intérieur disparaît plus souvent : creux
# inatteignable). Correspondance λ → allongement mesuré (moment d'inertie,
# haricots forcés éligibles, λ fixe ; médiane / max, links puis parkland) :
# 2,0 → 1,61 / 1,76 et 1,58 / 1,66 (bascules 52 % et 74 %) ; 2,1 → 1,67 /
# 1,86 et 1,63 / 1,77 ; 2,2 → 1,75 / 1,96 et 1,70 / 1,87 ; 2,25 → 1,80 / 2,01
# et 1,75 / 1,92 ; 2,3 → 1,85 / 2,06 et 1,80 / 1,97 ; 2,4 → 1,95 / 2,16 et
# 1,90 / 2,06. Avec 2,15–2,24 (mêmes haricots forcés) : links 1,53–1,96
# (quartiles 1,69–1,81, médiane 1,75), parkland 1,53–1,88 (1,64–1,75,
# médiane 1,70) : au-dessus de la cible de l'ancienne encoche (≈ 1,4–1,7),
# inhérent à la capsule.
# Creux du haricot 1,5–2,0 blocs dans les deux styles. Causes de bascule
# haricot → allongé (``golfgen.dressing.green.FALLBACK_CAUSES``) : creux
# inatteignable (arc intérieur inexistant pour la flèche visée, dès la
# première évaluation), calage (échec du recalage du creux : non convergé, ou
# sécante qui pousse la flèche hors du domaine de la capsule ; cause réelle,
# 0,5–1,0 % des haricots, qu'un bornage de la flèche pourrait réduire : piste
# future, non faite pour ne pas recalibrer), col < 5,5 blocs ou creux
# rastérisé < 1 bloc sur le contour placé (réduit compris).
#
# Éligibilité et tirage des types (R1b) : mesurés sur 30 seeds × 2 formats
# (400x300 et 300x400, patron random), soit 1080 trous par style ; les seeds
# brutes 1–30 sont passées telles quelles à l'habillage (instantané
# ``tests/data/dressing_holes_30x2.json``), pas ``seed_u64(seed)`` comme dans
# ``pipeline.py`` : même échantillon statistique, tirages différents ; en forçant
# le haricot sur chaque trou (la bascule ne dépend que de l'aire et des
# tirages de forme, pas du tirage du type) :
# - ``bean_min_area`` : seuils validés (« un haricot exige un grand
#   green »), qui ne descendent pas même si une aire plus petite tient la
#   règle ; ils ne seraient relevés que si la bascule y dépassait 5 % (plus
#   petite aire visée entière à partir de laquelle le taux de bascule
#   haricot → allongé parmi les éligibles est ≤ 5 %, et le reste au-dessus :
#   74 en links, 72 en parkland avec la capsule) ;
# - ``bean_given_eligible`` = P_eff = part de haricots visée / (part
#   d'éligibles × (1 − taux de bascule)), plafonnée à 1 : compense les
#   bascules ;
# - ``round_given_plain`` = part de ronds visée / (1 − P_eff × part
#   d'éligibles) : les bascules grossissent les allongés, le rapport des
#   poids nominaux (0,30 / 0,65 en links) ferait dériver les ronds vers le
#   bas.
# Bascules par cause ci-dessous : haricots forcés sur les éligibles (base de
# P_eff) ; sur les haricots tirés au même échantillon (``report.json``),
# links 3/370 (3 calages), parkland 9/317 (5 creux inatteignables, 3 calages,
# 1 creux rastérisé) : sous-ensemble des forcés, mêmes taux à l'échantillon
# près.
# links : seuil 84 blocs² ; éligibles 547/1080 = 50,6 % ; bascule 4/547
#   = 0,7 % (3 calages, 1 creux rastérisé) ; P_eff = 0,35 /
#   (0,506 × 0,993) = 0,696 ; rond 0,30 / (1 − 0,696 × 0,506) = 0,463.
# parkland : seuil 77 blocs² ; éligibles 415/1080 = 38,4 % ; bascule 10/415
#   = 2,4 % (5 creux inatteignables, 4 calages, 1 creux rastérisé) ;
#   P_eff = 0,30 / (0,384 × 0,976) = 0,800 ; rond 0,30 / (1 − 0,800 × 0,384)
#   = 0,433.
STYLE_SPECS: Mapping[str, StyleSpec] = MappingProxyType({
    "links": StyleSpec("links", green_rho=(0.68, 0.85), green_area=(50.0, 135.0),
                       harmonic_amplitude=0.12,
                       kind_weights=(0.30, 0.35, 0.35),
                       kind_aspects=((1.0, 1.3), (1.45, 1.9), (2.15, 2.24)),
                       bean_depth=(1.5, 2.0),
                       bean_min_area=84.0, bean_given_eligible=0.696,
                       round_given_plain=0.463),
    "parkland": StyleSpec("parkland", green_rho=(0.62, 0.76), green_area=(42.0, 105.0),
                          harmonic_amplitude=0.06,
                          kind_weights=(0.30, 0.40, 0.30),
                          kind_aspects=((1.0, 1.3), (1.45, 1.75), (2.15, 2.24)),
                          bean_depth=(1.5, 2.0),
                          bean_min_area=77.0, bean_given_eligible=0.800,
                          round_given_plain=0.433),
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
    (``GREEN_KINDS``) ; ``fallback_cause`` : cause de la bascule d'un haricot
    tiré devenu allongé (``golfgen.dressing.green.FALLBACK_CAUSES``), ``None``
    sans bascule ; ``kind`` et ``fallback_cause`` sont internes, non
    exportés."""

    outline: tuple[Point, ...]
    center: Point
    area: float
    target_area: float
    scale: float = 1.0
    shrink_steps: int = 0
    kind: str = "round"
    fallback_cause: str | None = None

    @property
    def reduced(self) -> bool:
        return self.shrink_steps > 0

    @property
    def bean_fallback(self) -> bool:
        """Haricot tiré devenu allongé (``fallback_cause`` renseignée)."""
        return self.fallback_cause is not None


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
