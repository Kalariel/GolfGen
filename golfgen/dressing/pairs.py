"""Greens doubles : sélection des paires (R3a) et oracle de la forme (R3c,
règles de forme revues en R3f).

Après les greens et les départs, certaines paires de greens NON consécutifs
sont retenues pour être fondues en un green double, de forme
``golfgen.dressing.pair_shape`` (enveloppe pincée au col ``W`` puis dilatée
et lissée, R3f), vérifiée par l'oracle ``check_green_pairs``.

Candidats : paires ``(i, j)``, ``i < j``, de trous non consécutifs
(``j ≠ i + 1`` : 9/10 exclu, 1/18 reste éligible), hors 9/18. 9/18 est
exclu par la topologie du routage : 9 et 18 sont les deux fins de boucle,
qui reviennent toutes deux au clubhouse ; leurs greens y sont proches par
construction, et les fondre ferait un green double collé au clubhouse, au
point de convergence des deux boucles. La distance ``d`` entre les centres
des greens (points ``hole.green`` du tracé) est dans ``PAIR_DISTANCE``
(bornes comprises ; [12, 20] blocs depuis R3f, [12, 35] avant).

Empreinte d'une candidate : enveloppe convexe des deux contours de greens
habillés (``GreenShape.outline``). Depuis R3f, la forme finale du green
double DÉPASSE l'empreinte (dilatation de ``pair_shape.DILATION``) : les
contrôles qui suivent, faits sur l'empreinte, sont un premier filtre ;
l'oracle les refait sur la forme finale (mêmes seuils), et une paire qui
y échoue est écartée.

Contrôles (seuils de la mesure des greens doubles, inchangés),
tous évalués : ``coeur`` écart ≥ ``CORE_GAP`` au cœur
(``build_hole_geometry(hole).core``) de tout trou autre que i et j ;
``tees`` écart ≥ ``TEE_GAP`` aux contours de toutes les boîtes de départ
habillées (``HoleDressing.tees[*].outline``, R3c ; R3a : points
``hole.tee`` du tracé) ; ``liaisons`` aucune liaison de ``layout.links`` ne traverse
l'empreinte, sauf celles qui partent du green i ou j ; ``clubhouse`` ≥
``CLUBHOUSE_MIN`` du clubhouse ; ``carte`` empreinte entièrement dans la
carte. Une candidate est VALIDE si elle passe les cinq.

Sélection : gloutonne et déterministe, sur les valides triées
``(d, i, j)`` : une paire est retenue si son empreinte est à ≥ ``PAIR_GAP``
de celles déjà retenues ET si sa forme se construit (sinon rejet) et
passe l'oracle avec les paires déjà retenues (sinon elle est ÉCARTÉE et la suivante est examinée), jusqu'au plafond du
style (``PAIR_RULES`` : 2 en links, 1 en parkland). En parkland, s'il existe au moins une valide, UN
tirage par parcours (probabilité ``PAIR_RULES["parkland"].probability``)
décide si la paire est formée ; sans valide, aucun tirage n'est consommé.

Traçabilité (R3c retouches) : ``pair_selection`` renvoie aussi, pour
chaque candidate écartée, une ``PairRejection`` (identité ``(i, j)`` et
cause stable de ``PAIR_REJECTION_CAUSES``), dans l'ordre des décisions :
candidates non valides (ordre des candidates), puis valides dans l'ordre du
glouton. Toute candidate est soit retenue, soit écartée avec une cause.
Calculée à côté des décisions, la trace ne les change pas.

Aléa : flux propre au parcours ``pair_rng`` (``golfgen.dressing.rng``),
distinct des flux des trous : la sélection ne change ni les greens ni les
départs, qu'elle lit sans les modifier.
"""

from __future__ import annotations

from dataclasses import dataclass
import math

import numpy as np

from golfgen.dressing.green import _convex_hull, edges_cross, points_in_polygon
from golfgen.dressing.model import GreenPair, PairRejection, Point
from golfgen.dressing.pair_shape import (GreensOverlapError, PairShapeError, build_pair,
                                         contains_outline, is_simple, min_width, neck_measure)
from golfgen.dressing.water import PAIR_WATER_MARGIN, is_dry
from golfgen.routing.geometry import (
    point_polygon_distance,
    polygon_gap,
    segment_crosses_polygon,
)


# blocs, distance entre centres de greens (bornes comprises). R3f, décision de
# l'utilisateur après les planches R3e : [12, 20] (36 à 60 m) au lieu de
# [12, 35], en acceptant ~1 paire links et 0 parkland sur les 120 layouts.
PAIR_DISTANCE = (12.0, 20.0)
EXCLUDED_PAIRS = frozenset({(9, 18)})
CORE_GAP = 5.0                  # blocs, empreinte ↔ cœur des autres trous
TEE_GAP = 5.0                   # blocs, empreinte ↔ points de départ
CLUBHOUSE_MIN = 10.0            # blocs, empreinte ↔ clubhouse
PAIR_GAP = 5.0                  # blocs, entre empreintes de paires retenues
CONTROLS = ("coeur", "tees", "liaisons", "clubhouse", "carte")
EPSILON = 1e-7

# Causes de rejet d'une candidate (``PairRejection.cause``), constantes
# stables. Une candidate non valide est écartée sur ``REJECT_FOOTPRINT`` ;
# une valide, dans l'ordre du glouton, sur ``REJECT_DRAW``,
# ``REJECT_PAIR_GAP``, ``REJECT_CAP`` ou, si sa forme échoue
# (``shape_or_reject``), sur ``REJECT_OVERLAP``, ``REJECT_CONSTRUCTION``,
# ``REJECT_WATER`` ou ``REJECT_ORACLE`` (n'importe lequel des ``ORACLE_CHECKS`` en échec, pas
# seulement ``"col"`` et ``"tees"``). R3f : la cause ``"col_cible"`` (règle
# ``w < W`` de la forme R3c) n'existe plus ; un col réel trop étroit est un
# échec d'oracle (``"col"``).
REJECT_FOOTPRINT = "empreinte"          # contrôles ``CONTROLS`` en échec (non valide)
REJECT_DRAW = "tirage"                  # parkland : tirage du parcours négatif
REJECT_PAIR_GAP = "ecart_empreintes"    # empreinte à < ``PAIR_GAP`` d'une paire retenue
REJECT_OVERLAP = "chevauchement"        # ``GreensOverlapError``
REJECT_CONSTRUCTION = "construction"    # autre ``PairShapeError`` (géométrie dégénérée…)
REJECT_ORACLE = "oracle"                # ``ORACLE_CHECKS`` en échec (``checks``)
REJECT_CAP = "plafond"                  # non examinée : plafond du style atteint
# Lot 1 eau : forme construite qui n'est pas au sec à ``PAIR_WATER_MARGIN`` de
# l'eau RÉELLE du relief (``golfgen.dressing.water.is_dry``), ou green
# insulaire dans la paire (pas d'insulaire pour un green double), testée avant
# l'oracle.
REJECT_WATER = "eau"
PAIR_REJECTION_CAUSES = (REJECT_FOOTPRINT, REJECT_DRAW, REJECT_PAIR_GAP, REJECT_OVERLAP,
                         REJECT_CONSTRUCTION, REJECT_WATER, REJECT_ORACLE, REJECT_CAP)


@dataclass(frozen=True, slots=True)
class PairRule:
    """Règle de sélection d'un style : ``max_pairs`` paires au plus ;
    ``probability`` : probabilité du tirage unique par parcours qui décide si
    les paires sont formées, ``None`` sans tirage (toujours formées)."""

    max_pairs: int
    probability: float | None = None


PAIR_RULES = {
    "links": PairRule(max_pairs=2),
    "parkland": PairRule(max_pairs=1, probability=0.25),
}


def candidate_pairs(holes, bounds: tuple[float, float] | None = None
                    ) -> list[tuple[int, int, float]]:
    """Paires ``(i, j, d)`` non consécutives, hors ``EXCLUDED_PAIRS``, dont la
    distance ``d`` entre centres de greens est dans ``bounds`` (bornes
    comprises ; ``None`` : ``PAIR_DISTANCE``, lu à l'appel, en production ;
    autres plages : mesure)."""
    centers = {hole.order: (hole.green.x, hole.green.y) for hole in holes}
    orders = sorted(centers)
    lo, hi = PAIR_DISTANCE if bounds is None else bounds
    out = []
    for a, i in enumerate(orders):
        for j in orders[a + 1:]:
            if j == i + 1 or (i, j) in EXCLUDED_PAIRS:
                continue
            d = math.dist(centers[i], centers[j])
            if lo - EPSILON <= d <= hi + EPSILON:
                out.append((i, j, d))
    return out


def footprint(first_outline, second_outline) -> tuple[Point, ...]:
    """Empreinte provisoire : enveloppe convexe des deux contours de greens
    (sens trigonométrique, sans points alignés)."""
    hull = _convex_hull(np.asarray(tuple(first_outline) + tuple(second_outline), dtype=float))
    return tuple((float(x), float(y)) for x, y in hull)


def _bbox(polygon) -> tuple[float, float, float, float]:
    xs = [p[0] for p in polygon]
    ys = [p[1] for p in polygon]
    return min(xs), min(ys), max(xs), max(ys)


def _bbox_gap(first, second) -> float:
    """Distance entre boîtes englobantes : minorant de ``polygon_gap``."""
    dx = max(first[0] - second[2], second[0] - first[2], 0.0)
    dy = max(first[1] - second[3], second[1] - first[3], 0.0)
    return math.hypot(dx, dy)


def _point_edge_distances(points: np.ndarray, polygon: np.ndarray) -> np.ndarray:
    """Distances ``(k, m)`` des ``k`` points aux ``m`` arêtes du polygone."""
    a = polygon
    ab = np.concatenate((polygon[1:], polygon[:1])) - a
    ap = points[:, None, :] - a[None, :, :]
    length2 = np.maximum((ab * ab).sum(axis=1), 1e-300)
    t = np.clip((ap * ab[None]).sum(axis=2) / length2, 0.0, 1.0)
    return np.hypot(ap[..., 0] - t * ab[:, 0], ap[..., 1] - t * ab[:, 1])


def polygon_gap_np(first, second) -> float:
    """Écart bord à bord de deux polygones fermés, vectorisé : même valeur
    que ``golfgen.routing.geometry.polygon_gap`` (0 si les bords se coupent
    ou si l'un contient un sommet de l'autre ; sinon plus courte distance
    sommet ↔ arête, qui est celle de deux segments disjoints)."""
    a = np.asarray(first, dtype=float)
    b = np.asarray(second, dtype=float)
    if (edges_cross(a, b) or points_in_polygon(a[:1], b)[0]
            or points_in_polygon(b[:1], a)[0]):
        return 0.0
    return float(min(_point_edge_distances(a, b).min(), _point_edge_distances(b, a).min()))


def pair_checks(layout, i: int, j: int, hull, cores, tees) -> dict[str, tuple[bool, object]]:
    """Chaque contrôle de l'empreinte ``hull`` de la paire ``(i, j)`` :
    ``{nom: (ok, mesure)}``. ``cores`` : ``{order: cœur}`` ; ``tees`` :
    contours de toutes les boîtes de départ habillées.

    Préfiltre EXACT par boîtes englobantes (performance seule, verdicts
    inchangés) : un cœur ou une boîte de départ dont la boîte est à ≥ l'écart
    requis de celle de l'empreinte passe sans calcul exact (écart réel ≥
    écart des boîtes), une liaison dont la boîte est à plus de ``EPSILON``
    de celle de l'empreinte ne la traverse pas (``segments_intersect``
    compte un contact à ``EPSILON`` près). Les mesures ``coeur`` et ``tees`` sont
    donc l'écart minimal aux seuls éléments proches, ``inf`` s'il n'y en a
    aucun."""
    box = _bbox(hull)
    core_gap = math.inf
    for order, core in cores.items():
        if order in (i, j) or _bbox_gap(box, _bbox(core)) >= CORE_GAP:
            continue
        core_gap = min(core_gap, polygon_gap_np(hull, core))
    tee_gap = math.inf
    for tee in tees:
        if _bbox_gap(box, _bbox(tee)) < TEE_GAP:
            tee_gap = min(tee_gap, polygon_gap_np(hull, tee))
    crossing = []
    for link in layout.links:
        if link.from_hole_order in (i, j):
            continue
        start, end = (link.start.x, link.start.y), (link.end.x, link.end.y)
        if _bbox_gap(box, _bbox((start, end))) > EPSILON:
            continue
        if segment_crosses_polygon(start, end, hull):
            crossing.append([link.from_hole_order, link.to_hole_order])
    clubhouse = point_polygon_distance((layout.clubhouse.x, layout.clubhouse.y), hull)
    in_map = all(-EPSILON <= x <= layout.width + EPSILON
                 and -EPSILON <= y <= layout.height + EPSILON for x, y in hull)
    return {
        "coeur": (core_gap >= CORE_GAP - EPSILON, core_gap),
        "tees": (tee_gap >= TEE_GAP - EPSILON, tee_gap),
        "liaisons": (not crossing, crossing),
        "clubhouse": (clubhouse >= CLUBHOUSE_MIN - EPSILON, clubhouse),
        "carte": (in_map, in_map),
    }


def tee_outlines(holes) -> tuple[tuple[Point, ...], ...]:
    """Contours de toutes les boîtes de départ de ``holes`` (``{order:
    HoleDressing}``)."""
    return tuple(tee.outline for hd in holes.values() for tee in hd.tees)


def valid_pairs(layout, holes, cores, bounds: tuple[float, float] | None = None
                ) -> tuple[list[GreenPair], dict]:
    """Candidates valides (``GreenPair`` sans forme, ordre des candidates) et
    contrôles de chaque candidate ``{(i, j): pair_checks(...)}``. ``holes`` :
    ``{order: HoleDressing}`` (greens et départs habillés) ; ``cores`` :
    ``{order: cœur}`` ; ``bounds`` : plage de distance (``candidate_pairs`` ;
    ``None`` : ``PAIR_DISTANCE``)."""
    valid, checks = [], {}
    tees = tee_outlines(holes)
    for i, j, d in candidate_pairs(layout.holes, bounds):
        hull = footprint(holes[i].green.outline, holes[j].green.outline)
        checks[(i, j)] = result = pair_checks(layout, i, j, hull, cores, tees)
        if all(ok for ok, _ in result.values()):
            valid.append(GreenPair(i=i, j=j, distance=d, footprint=hull))
    return valid, checks


def greedy_select(valid, max_pairs: int, gap: float = PAIR_GAP, shape=None,
                  rejections: list | None = None) -> tuple[list, int]:
    """Glouton déterministe trié ``(d, i, j)`` : renvoie les paires retenues
    et le nombre de valides écartées pour écart < ``gap`` avant d'atteindre
    ``max_pairs``. ``shape(pair, chosen)`` (optionnel) : paire munie de sa
    forme, ou, si elle est rejetée (construction ou oracle),
    la ``PairRejection`` qui en donne la cause (``None`` : rejet sans cause,
    non tracé) ; une paire rejetée n'est pas retenue (ni comptée bloquée).
    ``rejections`` (optionnel) : liste complétée, dans l'ordre du glouton,
    d'une ``PairRejection`` par valide non retenue (``REJECT_PAIR_GAP``,
    rejet rendu par ``shape``, ``REJECT_CAP`` pour celles non examinées) ;
    sans effet sur les paires retenues."""
    chosen, blocked = [], 0
    ordered = sorted(valid, key=lambda p: (p.distance, p.i, p.j))
    for k, pair in enumerate(ordered):
        if len(chosen) >= max_pairs:
            if rejections is not None:
                rejections.extend(PairRejection(p.i, p.j, REJECT_CAP) for p in ordered[k:])
            break
        if not all(polygon_gap(pair.footprint, c.footprint) >= gap - EPSILON for c in chosen):
            blocked += 1
            if rejections is not None:
                rejections.append(PairRejection(pair.i, pair.j, REJECT_PAIR_GAP))
            continue
        if shape is not None:
            shaped = shape(pair, chosen)
            if shaped is None or isinstance(shaped, PairRejection):
                if shaped is not None and rejections is not None:
                    rejections.append(shaped)
                continue
            pair = shaped
        chosen.append(pair)
    return chosen, blocked


def shape_or_reject(layout, holes, cores, pair, chosen=(), water=None
                    ) -> tuple[GreenPair | None, PairRejection | None]:
    """Forme de ``pair`` et verdict de l'oracle avec les paires ``chosen``
    déjà retenues : ``(paire munie de sa forme, None)`` si tout passe, sinon
    ``(None, rejet)`` de cause ``REJECT_OVERLAP`` (``GreensOverlapError``),
    ``REJECT_CONSTRUCTION``
    (autre ``PairShapeError`` : géométrie dégénérée, parcours du bord),
    ``REJECT_WATER`` (forme pas au sec à ``PAIR_WATER_MARGIN`` de l'eau
    RÉELLE ``water``, ``WaterMask`` ou ``None`` sans eau connue, ou l'un des
    deux greens insulaire : pas d'insulaire pour un green double ; testé
    avant l'oracle) ou ``REJECT_ORACLE`` (``checks`` : contrôles en échec sur l'ensemble du
    rapport, ordre ``ORACLE_CHECKS``). Toute autre exception remonte
    (bogue, cf. ``DressingError``)."""
    try:
        shaped = build_pair(pair, holes[pair.i].green, holes[pair.j].green)
    except GreensOverlapError:
        return None, PairRejection(pair.i, pair.j, REJECT_OVERLAP)
    except PairShapeError:
        return None, PairRejection(pair.i, pair.j, REJECT_CONSTRUCTION)
    if (holes[pair.i].green.island is not None or holes[pair.j].green.island is not None
            or not is_dry(shaped.outline, water, PAIR_WATER_MARGIN)):
        return None, PairRejection(pair.i, pair.j, REJECT_WATER)
    report = check_green_pairs(layout, holes, (*chosen, shaped), cores)
    failed = {name for result in report.values() for name, (ok, _) in result.items() if not ok}
    if failed:
        checks = tuple(name for name in ORACLE_CHECKS if name in failed)
        return None, PairRejection(pair.i, pair.j, REJECT_ORACLE, checks)
    return shaped, None


def shape_and_check(layout, holes, cores, pair, chosen=(), water=None
                    ) -> tuple[GreenPair | None, str | None]:
    """``shape_or_reject`` avec la cause en texte (``PairRejection.label``) :
    ``"chevauchement"``, ``"construction"``, ``"eau"`` ou
    ``"oracle:<contrôles>"`` ; ``None`` si tout passe."""
    shaped, rejection = shape_or_reject(layout, holes, cores, pair, chosen, water)
    return shaped, None if rejection is None else rejection.label


def pair_selection(layout, holes, cores, style: str, rng: np.random.Generator, water=None
                   ) -> tuple[tuple[GreenPair, ...], tuple[PairRejection, ...]]:
    """Paires de greens retenues pour ``style`` (``PAIR_RULES``), triées
    ``(d, i, j)``, munies de leur forme, et candidates écartées
    (``PairRejection``, ordre des décisions : non valides, ``REJECT_FOOTPRINT``,
    dans l'ordre des candidates ; puis valides dans l'ordre du glouton, ou
    toutes ``REJECT_DRAW`` si le tirage parkland est négatif). ``holes`` :
    ``{order: HoleDressing}`` ; ``rng`` (flux du parcours) n'est tiré qu'en
    parkland, une fois, et seulement s'il existe au moins une paire valide.
    ``water`` : eau du relief (``WaterMask``, ``None`` sans eau connue),
    passée à ``shape_or_reject``."""
    rule = PAIR_RULES[style]
    valid, checks = valid_pairs(layout, holes, cores)
    rejections = [PairRejection(i, j, REJECT_FOOTPRINT,
                                tuple(name for name in CONTROLS if not result[name][0]))
                  for (i, j), result in checks.items()
                  if not all(ok for ok, _ in result.values())]
    if not valid:
        return (), tuple(rejections)
    if rule.probability is not None and not rng.random() < rule.probability:
        rejections.extend(PairRejection(p.i, p.j, REJECT_DRAW)
                          for p in sorted(valid, key=lambda p: (p.distance, p.i, p.j)))
        return (), tuple(rejections)
    chosen, _ = greedy_select(
        valid, rule.max_pairs, rejections=rejections,
        shape=lambda pair, done: _shaped_or_rejection(layout, holes, cores, pair, done, water))
    return tuple(chosen), tuple(rejections)


def _shaped_or_rejection(layout, holes, cores, pair, chosen, water) -> GreenPair | PairRejection:
    shaped, rejection = shape_or_reject(layout, holes, cores, pair, chosen, water)
    return shaped if rejection is None else rejection


def select_green_pairs(layout, holes, cores, style: str,
                       rng: np.random.Generator, water=None) -> tuple[GreenPair, ...]:
    """Paires retenues de ``pair_selection`` (sans la trace des rejets)."""
    return pair_selection(layout, holes, cores, style, rng, water)[0]


# --- oracle des greens doubles (R3c, R3f) --------------------------------------

# R3f (règle validée par l'utilisateur) : ``col_cible`` (w < W), ``enveloppe``
# (forme ⊆ empreinte) et l'ancien ``col`` (col réel = w à 5 % près),
# propres à la forme pincée R3c, sont remplacés par ``inclusion`` (greens ET
# drapeaux dans la forme), ``simple`` et ``col`` (col réel ≥ W) ; les
# contrôles d'écart sont inchangés.
ORACLE_CHECKS = ("inclusion", "simple", "col", "coeur", "tees", "liaison_autre",
                 "liaison_partenaire", "clubhouse", "carte", "ecart_paires")


def _shape_gap(shape: np.ndarray, polygons, gap: float) -> float:
    """Écart minimal de ``shape`` aux ``polygons`` dont la boîte est à moins
    de ``gap`` (préfiltre exact) ; ``inf`` s'il n'y en a aucun."""
    box = (*shape.min(axis=0), *shape.max(axis=0))
    best = math.inf
    for polygon in polygons:
        if _bbox_gap(box, _bbox(polygon)) < gap:
            best = min(best, polygon_gap_np(shape, polygon))
    return best


def check_pair_shape(layout, holes, pair: GreenPair, cores) -> dict[str, tuple[bool, object]]:
    """Contrôles de la forme finale de ``pair`` (``{nom: (ok, mesure)}``,
    ``ORACLE_CHECKS`` sauf ``ecart_paires``) :

    - ``inclusion`` : les deux contours de greens
      (``pair_shape.contains_outline``) et les deux drapeaux
      (``GreenShape.center``) dans la forme ; ``simple`` : contour sans
      auto-intersection ;
    - ``col`` : col réel (``pair_shape.neck_measure`` : coupe minimale de la
      composante entre les greens) ≥ ``W``, largeur minimale du plus petit
      des deux greens (``pair_shape.min_width``), fini ; mesure ``(col, W)`` ;
    - ``coeur`` ≥ ``CORE_GAP`` des cœurs des autres trous ; ``tees`` ≥
      ``TEE_GAP`` des contours de TOUTES les boîtes de départ ; ``clubhouse``
      ≥ ``CLUBHOUSE_MIN`` ; ``carte`` : dans la carte ;
    - ``liaison_autre`` : aucune liaison qui ne part ni de i ni de j ne
      traverse la forme (contrôle ``liaisons`` de la sélection) ;
      ``liaison_partenaire`` : la liaison qui part du green i (resp. j) ne
      traverse pas le contour du green PARTENAIRE j (resp. i) ; elle peut
      partir dans la forme partagée.

    Les contrôles de distance et ``liaison_autre`` sont ceux de la
    sélection, refaits sur la forme finale (qui dépasse l'empreinte)."""
    i, j = pair.i, pair.j
    gi, gj = holes[i].green, holes[j].green
    shape = np.asarray(pair.outline, dtype=float)
    if len(shape) < 3:
        return {name: (False, "sans forme") for name in ORACLE_CHECKS if name != "ecart_paires"}
    smaller = min(min_width(gi.outline), min_width(gj.outline))
    neck, _ = neck_measure(shape, gi.outline, gj.outline, gi.center, gj.center)
    pins = points_in_polygon(np.array((gi.center, gj.center), dtype=float), shape)
    poly = tuple(map(tuple, shape.tolist()))
    box = (*shape.min(axis=0), *shape.max(axis=0))
    other, partner = [], []
    mates = {i: gj.outline, j: gi.outline}
    for link in layout.links:
        start, end = (link.start.x, link.start.y), (link.end.x, link.end.y)
        if link.from_hole_order in mates:
            mate = mates[link.from_hole_order]
            if segment_crosses_polygon(start, end, mate):
                partner.append([link.from_hole_order, link.to_hole_order])
            continue
        if _bbox_gap(box, _bbox((start, end))) > EPSILON:
            continue
        if segment_crosses_polygon(start, end, poly):
            other.append([link.from_hole_order, link.to_hole_order])
    core_gap = _shape_gap(shape, [c for o, c in cores.items() if o not in (i, j)], CORE_GAP)
    tee_gap = _shape_gap(shape, tee_outlines(holes), TEE_GAP)
    clubhouse = point_polygon_distance((layout.clubhouse.x, layout.clubhouse.y), poly)
    in_map = bool((shape >= -EPSILON).all() and (shape[:, 0] <= layout.width + EPSILON).all()
                  and (shape[:, 1] <= layout.height + EPSILON).all())
    return {
        "inclusion": (bool(pins.all()) and contains_outline(shape, gi.outline)
                      and contains_outline(shape, gj.outline), None),
        "simple": (is_simple(shape), None),
        "col": (math.isfinite(neck) and neck >= smaller - EPSILON, (neck, smaller)),
        "coeur": (core_gap >= CORE_GAP - EPSILON, core_gap),
        "tees": (tee_gap >= TEE_GAP - EPSILON, tee_gap),
        "liaison_autre": (not other, other),
        "liaison_partenaire": (not partner, partner),
        "clubhouse": (clubhouse >= CLUBHOUSE_MIN - EPSILON, clubhouse),
        "carte": (in_map, in_map),
    }


def check_green_pairs(layout, holes, pairs, cores) -> dict[tuple[int, int], dict]:
    """Oracle des greens doubles d'un parcours, sur les formes FINALES (seul
    chevauchement de cœurs permis : celui des greens i et j d'une paire) :
    ``{(i, j): {nom: (ok, mesure)}}``, contrôles ``ORACLE_CHECKS``
    (``check_pair_shape``, plus ``ecart_paires`` : ≥ ``PAIR_GAP`` entre les
    formes de deux paires du parcours, ``inf`` pour une paire seule)."""
    report = {(p.i, p.j): check_pair_shape(layout, holes, p, cores) for p in pairs}
    shapes = [np.asarray(p.outline, dtype=float) for p in pairs]
    for a, pair in enumerate(pairs):
        others = [s for b, s in enumerate(shapes) if b != a and len(s) >= 3]
        gap = min((polygon_gap_np(shapes[a], s) for s in others), default=math.inf) \
            if len(shapes[a]) >= 3 else 0.0
        report[(pair.i, pair.j)]["ecart_paires"] = (gap >= PAIR_GAP - EPSILON, gap)
    return report


def oracle_failures(report) -> list[tuple[int, int, str]]:
    """Contrôles en échec d'un rapport de ``check_green_pairs``."""
    return [(i, j, name) for (i, j), result in report.items()
            for name, (ok, _) in result.items() if not ok]
