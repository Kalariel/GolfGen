"""Modèle de l'habillage : styles et formes par trou.

Les structures sont figées et extensibles : ``HoleDressing`` porte le green,
les départs (``TeeBox``, champ ``tees`` à défaut vide) et le fairway
(``FairwayShape``, champ ``fairway`` à défaut vide, lot 2 ; fragments
retirés pour l'eau, ``RemovedPiece``, champ ``fairway_removed`` à défaut
vide, R4) ;
``CourseDressing.green_pairs`` porte les paires de greens doubles retenues
(``GreenPair``, champ à défaut vide, forme comprise) et
``CourseDressing.pair_rejections`` les candidates écartées avec leur cause
(``PairRejection``, champ à défaut vide), sans changer les champs
existants.
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
    éligible ou non (le reste est allongé) ; ``water_green`` : repli d'un
    green tiré sur l'eau (``WATER_GREEN_POLICIES``, lot 1 eau,
    ``golfgen.dressing.green.dry_green_shape``) : ``"shift"``, green décalé
    à l'opposé de l'eau (links), insulaire en dernier recours ;
    ``"island"``, green insulaire (parkland)."""

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
    water_green: str = "island"


# Replis d'un green tiré sur l'eau (``StyleSpec.water_green``), décision
# utilisateur du lot 1 eau.
WATER_GREEN_POLICIES = ("shift", "island")


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
                       round_given_plain=0.463, water_green="shift"),
    "parkland": StyleSpec("parkland", green_rho=(0.62, 0.76), green_area=(42.0, 105.0),
                          harmonic_amplitude=0.06,
                          kind_weights=(0.30, 0.40, 0.30),
                          kind_aspects=((1.0, 1.3), (1.45, 1.75), (2.15, 2.24)),
                          bean_depth=(1.5, 2.0),
                          bean_min_area=77.0, bean_given_eligible=0.800,
                          round_given_plain=0.433, water_green="island"),
})


@dataclass(frozen=True, slots=True)
class GreenIsland:
    """Green insulaire (lot 1 eau, ``golfgen.dressing.water.island_of``) :
    les cellules d'eau du relief recouvertes par le contour du green (aire
    commune non nulle) sont remontées, bord franc, sans talus ni liseré, à
    ``height``, altitude minimale de sa partie émergée (relief, non arrondi) ;
    ``raised_area`` : nombre de cellules remontées (blocs²). Rien d'autre
    n'est stocké : la remontée se déduit du contour et du relief
    (``golfgen.dressing.water.raised_cells``, ``effective_water``), le
    relief exporté par le routage ne change pas."""

    height: float
    raised_area: float


@dataclass(frozen=True, slots=True)
class TeeIsland:
    """Boîte de départ remontée (lot 1 eau, dernier repli d'une boîte sur
    l'eau, ``golfgen.dressing.water.tee_island_of``), même règle que le green
    insulaire (``GreenIsland``) : les cellules d'eau du relief que la boîte
    touche (aire commune non nulle) sont remontées, bord franc, à
    ``height``, altitude minimale de sa partie émergée (relief, non
    arrondi) ; ``submerged`` : boîte entièrement immergée (aucune partie
    émergée), remontée alors à un bloc au-dessus de l'eau, ``WATER_LEVEL +
    SUBMERGED_TEE_LIFT`` (``golfgen.routing.sites``,
    ``golfgen.dressing.water``), compté à part ; ``raised_area`` : nombre de
    cellules remontées (blocs²). Rien d'autre n'est stocké, le relief
    exporté ne change pas."""

    height: float
    raised_area: float
    submerged: bool = False


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
    exportés. ``island`` : remontée d'un green insulaire (``GreenIsland``,
    lot 1 eau), ``None`` pour un green au sec ; exporté en 3.1
    (``features.green.island``)."""

    outline: tuple[Point, ...]
    center: Point
    area: float
    target_area: float
    scale: float = 1.0
    shrink_steps: int = 0
    kind: str = "round"
    fallback_cause: str | None = None
    island: GreenIsland | None = None

    @property
    def reduced(self) -> bool:
        return self.shrink_steps > 0

    @property
    def bean_fallback(self) -> bool:
        """Haricot tiré devenu allongé (``fallback_cause`` renseignée)."""
        return self.fallback_cause is not None


@dataclass(frozen=True, slots=True)
class TeeBox:
    """Boîte de départ d'un trou, en blocs (``golfgen.dressing.tees``).

    ``outline`` : rectangle de 4 sommets, coordonnées arrondies à 2 décimales,
    même sens de parcours que ``GreenShape.outline`` (aire signée positive
    dans le repère (x, y) de la carte) ; ``center`` : centre NON arrondi,
    point de l'axe (la boîte arrière est centrée exactement sur
    ``hole.tee``), sauf repli pour l'eau (``WaterFix`` : boîte avancée
    décalée en travers, boîte arrière glissée d'au plus 1 bloc dans l'axe) ;
    ``area`` : aire du polygone arrondi ; ``rank`` : rang depuis l'arrière
    (0 = boîte arrière, centrée sur le tee) ; ``heading`` : direction
    unitaire du jeu (premier segment de l'axe), grand côté de la boîte ;
    ``island`` : remontée d'une boîte que ni le glissement dans l'axe ni le
    décalage en travers ne mettent au sec (``TeeIsland``, lot 1 eau),
    ``None`` pour une boîte au sec ; exporté en 3.1
    (``features.tees[].island``)."""

    outline: tuple[Point, ...]
    center: Point
    area: float
    rank: int
    heading: Point
    island: TeeIsland | None = None


@dataclass(frozen=True, slots=True)
class FairwayShape:
    """Polygone de fairway d'un trou, en blocs (``golfgen.dressing.fairway``,
    mécanisme B v1, lot 2 R2, à col marqué, R2b, avec profil en long et
    contournement des départs et des greens, R3).

    ``outline`` : polygone simple fermé implicitement, coordonnées NON
    arrondies (comme ``GreenPair.outline`` ; l'export arrondit, R5), sommets
    tous les ``OUTLINE_STEP`` ≈ 1 bloc ; ``area`` : aire signée de
    ``outline`` (blocs²). Contenu dans le cœur du trou (vérifié par les
    tests, pas clippé)."""

    outline: tuple[Point, ...]
    area: float


@dataclass(frozen=True, slots=True)
class RemovedPiece:
    """Fragment de fairway retiré (lot 2 R4, ``golfgen.dressing.fairway_water``) :
    aire (blocs²) et cause (``"eau"`` : morceau coupé par l'eau d'aire
    inférieure à l'aire minimale). Devenu rough implicite : interne, non
    exporté (R5)."""

    area: float
    cause: str


@dataclass(frozen=True, slots=True)
class WaterFix:
    """Repli d'un trou pour l'eau du relief (lot 1 eau ;
    ``golfgen.dressing.water``) : ce qui a été changé pour garder le green
    et les boîtes au sec de l'eau effective. Interne, non exporté.

    Green (``golfgen.dressing.green.dry_green_shape``) : ``green_shift``,
    translation du green décalé (blocs, ``(dx, dy)``), ``None`` sinon ;
    ``green_rotation``, rotation de la forme autour de son centre avant le
    décalage (degrés, 0 sans rotation) ; ``green_steps``, paliers d'aire
    descendus avant le décalage (0 : aire visée tirée) ; ``green_target`` :
    aire visée tirée (``None`` si le green n'a pas été touché) ;
    ``green_kind`` : type tiré quand la cascade l'a changé (haricot devenu
    allongé), ``None`` sinon ; ``green_island`` : green insulaire
    (``GreenShape.island``) ; ``green_island_fallback`` : insulaire en
    dernier recours d'un style à green décalé (rien n'a suffi), compté à
    part. Départs (``golfgen.dressing.tees.dry_tee_boxes``) : rangs
    (0 = arrière ; aucune boîte n'est retirée pour l'eau, rangs tirés et
    posés confondus) déplacés dans l'axe (``tees_moved``), décalés en
    travers (``tees_shifted``) ou remontés (``tees_raised``, ``TeeBox.island``),
    dont entièrement immergés (``tees_submerged``, comptés à part) ;
    ``back_slide`` : glissement de la boîte arrière dans l'axe (blocs,
    signé, 0 sans glissement)."""

    green_shift: tuple[float, float] | None = None
    green_rotation: float = 0.0
    green_steps: int = 0
    green_target: float | None = None
    green_kind: str | None = None
    green_island: bool = False
    green_island_fallback: bool = False
    tees_moved: tuple[int, ...] = ()
    tees_shifted: tuple[int, ...] = ()
    tees_raised: tuple[int, ...] = ()
    tees_submerged: tuple[int, ...] = ()
    back_slide: float = 0.0

    @property
    def green_changed(self) -> bool:
        return self.green_target is not None

    @property
    def tees_changed(self) -> bool:
        return bool(self.tees_moved or self.tees_shifted or self.tees_raised
                    or self.back_slide)


@dataclass(frozen=True, slots=True)
class HoleDressing:
    """Habillage d'un trou (``order`` = numéro du trou). Le green double est
    porté par le parcours (``CourseDressing.green_pairs``), pas ici.

    ``tees`` : boîtes de départ, de l'arrière vers l'avant (rang 0 d'abord) ;
    défaut ``()`` (tuple vide, pas ``None``) : « aucun départ » reste un
    tuple itérable et figé, sans cas ``None`` à traiter chez les lecteurs, et
    ``HoleDressing(order, green)`` reste valide. ``tee_fallback_cause`` :
    cause de la réduction du nombre de boîtes tiré
    (``golfgen.dressing.tees.TEE_FALLBACK_CAUSES``), ``None`` sans bascule ;
    interne, non exporté. ``fairway`` : polygones du fairway
    (``FairwayShape``, ``golfgen.dressing.fairway``, lot 2), défaut ``()``
    comme ``tees`` ; coupé au-dessus de l'eau effective du trou (R4,
    ``golfgen.dressing.fairway_water.water_fairway``, ``FAIRWAY_WATER_CUT``) :
    un seul polygone tant que l'eau ne coupe rien, sinon zéro, un ou
    plusieurs morceaux, le principal d'abord puis par aire décroissante ;
    non exporté avant le R5, exporté depuis dans ``features.fairway`` du
    JSON 3.1 (``golfgen.exporter``, même ordre, ``[]`` si vide, contours
    arrondis à 2 décimales). ``fairway_removed`` : fragments coupés par
    l'eau et retirés (``RemovedPiece``, aire < aire minimale, cause
    ``"eau"``), devenus rough implicite ; interne, non exporté (R5).
    ``fairway_empty_cause`` : cause d'un fairway vidé par l'eau (``"eau :
    noyé"`` ou ``"eau : fragments trop petits"``), renseignée si et
    seulement si ``fairway == ()`` sur un trou qui avait un fairway de
    production, ``None`` sinon ; interne. ``water_fix`` : repli pour l'eau
    du relief (``WaterFix``), ``None`` si ni le green ni les départs n'ont
    été touchés ; interne, non exporté."""

    order: int
    green: GreenShape
    tees: tuple[TeeBox, ...] = ()
    tee_fallback_cause: str | None = None
    fairway: tuple[FairwayShape, ...] = ()
    water_fix: WaterFix | None = None
    fairway_removed: tuple[RemovedPiece, ...] = ()
    fairway_empty_cause: str | None = None


@dataclass(frozen=True, slots=True)
class GreenPair:
    """Paire de greens d'un green double (``golfgen.dressing.pairs``).

    ``i < j`` : numéros des deux trous ; ``distance`` : distance entre les
    centres des greens du tracé (``hole.green``), en blocs ; ``footprint`` :
    empreinte de la sélection (R3a), enveloppe convexe des deux contours de
    greens (sens trigonométrique). Forme (R3c, revue en R3f,
    ``golfgen.dressing.pair_shape``, renseignée sur les paires retenues par
    ``dress_course``) : ``outline``, contour du green double (enveloppe
    pincée au col ``w``, dilatée et lissée : contient les deux greens et
    dépasse ``footprint``, sens trigonométrique, coordonnées NON arrondies),
    ``()`` sur une candidate sans forme ; ``neck_width`` : col visé ``w`` du
    pincement de départ (blocs, le col réel est plus large), ``None`` sans
    forme. Export JSON 3.1 (R3d,
    ``golfgen.exporter``, ``routing.green_pairs``) : ``i``, ``j`` et
    ``outline`` seuls (arrondi à 2 décimales, même sens que
    ``GreenShape.outline``) avec l'aire du contour arrondi ; ``distance``,
    ``footprint`` et ``neck_width`` restent internes."""

    i: int
    j: int
    distance: float
    footprint: tuple[Point, ...]
    outline: tuple[Point, ...] = ()
    neck_width: float | None = None


@dataclass(frozen=True, slots=True)
class PairRejection:
    """Candidate de green double écartée par la sélection
    (``golfgen.dressing.pairs``, R3c retouches).

    ``i < j`` : numéros des deux trous ; ``cause`` : constante stable de
    ``golfgen.dressing.pairs.PAIR_REJECTION_CAUSES`` ; ``checks`` : contrôles
    en échec, dans l'ordre canonique (``CONTROLS`` pour ``"empreinte"``,
    ``ORACLE_CHECKS`` pour ``"oracle"``), ``()`` pour les autres causes.
    Interne, non exporté."""

    i: int
    j: int
    cause: str
    checks: tuple[str, ...] = ()

    @property
    def label(self) -> str:
        """``cause``, suivie de ``":<contrôles>"`` s'il y en a (ex.
        ``"oracle:col,tees"``)."""
        return f"{self.cause}:{','.join(self.checks)}" if self.checks else self.cause


@dataclass(frozen=True, slots=True)
class CourseDressing:
    """Habillage d'un parcours : ``holes`` = ``{order: HoleDressing}`` trié par
    numéro de trou, ``style`` = clé de ``STYLE_SPECS`` ; ``green_pairs`` :
    paires de greens doubles retenues, triées ``(distance, i, j)``, défaut
    ``()`` (aucune paire, ou parcours sans contexte complet : cf.
    ``golfgen.dressing.course.dress_course``) ; ``pair_rejections`` :
    candidates écartées et cause (``PairRejection``), dans l'ordre des
    décisions (``golfgen.dressing.pairs.pair_selection``), défaut ``()`` ;
    sans effet sur la sélection, interne, non exporté."""

    style: str
    holes: Mapping[int, HoleDressing]
    green_pairs: tuple[GreenPair, ...] = ()
    pair_rejections: tuple[PairRejection, ...] = ()

    def __getitem__(self, order: int) -> HoleDressing:
        return self.holes[order]
