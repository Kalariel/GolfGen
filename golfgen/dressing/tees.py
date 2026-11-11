"""Boîtes de départ d'un trou (habillage, round R2b).

Boîte : rectangle de ``TEE_BOX_LENGTH`` blocs dans le sens du jeu sur
``TEE_BOX_WIDTH`` en travers, centré SUR l'axe (pas de décalage latéral,
sauf repli pour l'eau, ``dry_tee_boxes`` : glissement dans l'axe, décalage
en travers, puis remontée), toutes de même taille. Le sens du jeu est ``dir``, direction unitaire du
premier segment de l'axe (``axis[0] → axis[1]``).

Placement : la boîte arrière (rang 0) est centrée exactement sur
``hole.tee`` ; les boîtes avancées sont posées sur l'axe à la distance ``d``
du tee le long de ``dir``, toutes sur le premier segment. L'ÉTALEMENT ``E``
est la distance entre les centres de la boîte arrière et de la plus avancée.

Nombre de boîtes (``drawn_count``) : par 3 de longueur d'axe ``L <
TEE_SHORT_PAR3`` : 1 ; par 3 plus long : 2 ; par 4 : 2 ou 3 à 50/50 ;
par 5 : 3. Le style (links / parkland) n'intervient pas.

Étalement : 2 boîtes, ``E`` uniforme dans ``[TEE_SPREAD_MIN_2, Emax]`` ;
3 boîtes, ``[TEE_SPREAD_MIN_3, Emax]`` ; ``Emax = min(TEE_SPREAD_MAX,
F·L, seg1 − M)`` (``spread_cap``), ``F`` = ``TEE_LENGTH_FRACTION``, ``M`` =
``TEE_DOGLEG_MARGIN``, ``seg1`` = longueur du premier segment ; le terme
``seg1 − M`` ne joue que si le trou a au moins un coude. Boîte du milieu
(3 boîtes) : ``d`` uniforme dans ``[max(TEE_MIN_SPACING, a·E),
min(E − TEE_MIN_SPACING, b·E)]``, ``(a, b)`` = ``TEE_MIDDLE_RANGE``.

Bascules, si ``Emax`` est inférieur au minimum requis : 3 → 2 boîtes si
``Emax ≥ TEE_SPREAD_MIN_2``, sinon → 1 boîte (2 → 1 de même). Cause
(``HoleDressing.tee_fallback_cause``, ``TEE_FALLBACK_CAUSES``) :
``trou_court`` si c'est ``F·L`` qui contraint, ``segment_court`` si c'est
``seg1 − M`` (à égalité : ``trou_court``).

Aléa : flux propre aux départs, SÉPARÉ de celui du green
(``golfgen.dressing.rng.tee_rng``) : les greens ne changent pas. Ordre
des tirages, figé : nombre de boîtes (par 4 seulement), ``E`` (2 boîtes ou
plus, après bascule), ``d`` du milieu (3 boîtes).

Contraintes dures : chaque boîte est dans le CŒUR du trou
(``build_hole_geometry(hole).core``) et à un écart STRICTEMENT positif du
green (polygones fermés : un contact par un bord ou un coin seul est
refusé) ; sinon ``DressingError``. Les coordonnées des sommets sont arrondies à
2 décimales AVANT le contrôle ; les centres ne le sont pas.
"""

from __future__ import annotations

import math

import numpy as np

from golfgen.dressing.green import cross, points_in_polygon, polygon_inside
from golfgen.dressing.model import DressingError, Point, TeeBox, TeeIsland, WaterFix
from golfgen.dressing.water import TEE_WATER_MARGIN, is_dry, tee_island_of
from golfgen.routing.model import ElasticHole
from golfgen.routing.sites import WaterMask


# Constantes validées (R2b), d'après les mesures R2a (instantané 30 seeds × 2
# formats, 1080 trous) : longueur d'axe par 3 45,1–69,9 (médiane 48,8), par 4
# ≥ 100,1, par 5 ≥ 145,1 ; premier segment des trous à coude ≥ 27,2 (par 3
# 27,2–27,8, par 4 ≥ 59,1, par 5 ≥ 85,2) ; width 10–18. D'où Emax = 20 pour
# les par 4 et 5, F·L ≥ 13,75 pour les par 3 de L ≥ 55 et seg1 − M ≥ 17,2
# pour les coudes : bascules attendues ≈ 0 %.
TEE_BOX_LENGTH = 4.0            # blocs, dans le sens du jeu
TEE_BOX_WIDTH = 3.0             # blocs, en travers
TEE_MIN_GAP = 2.0               # blocs, écart minimal bord à bord entre boîtes
TEE_MIN_SPACING = TEE_BOX_LENGTH + TEE_MIN_GAP      # 6 blocs entre centres consécutifs
TEE_SHORT_PAR3 = 55.0           # S : par 3 de L < S → 1 boîte, sinon 2
TEE_LENGTH_FRACTION = 0.25      # F : Emax ≤ F·L
TEE_DOGLEG_MARGIN = 10.0        # M : Emax ≤ seg1 − M (trous à coude)
TEE_SPREAD_MIN_2 = 10.0         # blocs : E minimal à 2 boîtes
TEE_SPREAD_MIN_3 = 12.0         # blocs : E minimal à 3 boîtes (2 × TEE_MIN_SPACING)
TEE_SPREAD_MAX = 20.0           # blocs : plafond absolu de E
TEE_MIDDLE_RANGE = (0.35, 0.65)     # boîte du milieu : d dans [0,35·E, 0,65·E] (bornée)
TEE_PAR4_THREE = 0.5            # P(3 boîtes) pour un par 4
# Causes de réduction du nombre de boîtes (``HoleDressing.tee_fallback_cause``) ;
# le repli pour l'eau ne retire aucune boîte (lot 1 eau : remontée en dernier
# recours), il n'a donc pas de cause.
TEE_FALLBACK_CAUSES = ("trou_court", "segment_court")
# Repli pour l'eau (lot 1 eau, décision utilisateur) : pas de la grille des
# positions candidates d'une boîte (blocs, le long du premier segment, et en
# travers pour le décalage latéral d'une boîte avancée) ; glissement maximal
# de la boîte arrière dans l'axe.
TEE_WATER_STEP = 0.5
TEE_BACK_SLIDE_MAX = 1.0

ROUNDING_MARGIN = 0.01          # blocs : arrondi des sommets (≤ 0,005·√2) dans les contrôles


def first_segment(hole: ElasticHole) -> float:
    """Longueur ``seg1`` du premier segment de l'axe."""
    a, b = hole.axis[0], hole.axis[1]
    return math.dist((a.x, a.y), (b.x, b.y))


def drawn_count(hole: ElasticHole, rng: np.random.Generator) -> int:
    """Nombre de boîtes avant bascule ; tire ``rng`` pour un par 4 seulement."""
    if hole.par == 3:
        return 1 if hole.length < TEE_SHORT_PAR3 else 2
    if hole.par == 4:
        return 3 if rng.uniform() < TEE_PAR4_THREE else 2
    return 3


def spread_cap(hole: ElasticHole) -> tuple[float, str]:
    """``(Emax, cause)`` : plafond de l'étalement et cause d'une éventuelle
    bascule (terme le plus contraignant entre ``F·L`` et, trou à coude,
    ``seg1 − M``)."""
    cap, cause = TEE_LENGTH_FRACTION * hole.length, "trou_court"
    if hole.doglegs:
        by_segment = first_segment(hole) - TEE_DOGLEG_MARGIN
        if by_segment < cap:
            cap, cause = by_segment, "segment_court"
    return min(TEE_SPREAD_MAX, cap), cause


def settled_count(drawn: int, cap: float, cause: str) -> tuple[int, str | None]:
    """Nombre de boîtes après bascule et sa cause (``None`` sans bascule)."""
    count = drawn
    if count == 3 and cap < TEE_SPREAD_MIN_3:
        count = 2
    if count == 2 and cap < TEE_SPREAD_MIN_2:
        count = 1
    return count, (cause if count < drawn else None)


def middle_range(spread: float) -> tuple[float, float]:
    """Bornes de ``d`` de la boîte du milieu pour l'étalement ``spread``."""
    lo, hi = TEE_MIDDLE_RANGE
    return (max(TEE_MIN_SPACING, lo * spread), min(spread - TEE_MIN_SPACING, hi * spread))


def _rectangle(cx: float, cy: float, hx: float, hy: float, back: float, front: float,
               half: float) -> list[Point]:
    """Rectangle de l'axe passant par ``(cx, cy)``, de direction ``(hx, hy)``
    (unitaire) : ``back ≤ long ≤ front`` le long de l'axe, ``|travers| ≤
    half`` ; 4 sommets, aire signée positive (sens de ``GreenShape.outline``)."""
    nx, ny = -hy, hx
    return [(cx + a * hx + b * nx, cy + a * hy + b * ny)
            for a, b in ((back, -half), (front, -half), (front, half), (back, half))]


def _segment_meets_rectangle(p: Point, q: Point, back: float, front: float,
                             half: float) -> bool:
    """Le segment ``[p, q]`` (repère local : long, travers) rencontre le
    rectangle FERMÉ ``[back, front] × [−half, half]`` (Liang–Barsky)."""
    t0, t1 = 0.0, 1.0
    du, dv = q[0] - p[0], q[1] - p[1]
    for step, room in ((-du, p[0] - back), (du, front - p[0]),
                       (-dv, p[1] + half), (dv, half - p[1])):
        if step == 0.0:
            if room < 0.0:
                return False
            continue
        t = room / step
        if step < 0.0:
            t0 = max(t0, t)
        else:
            t1 = min(t1, t)
        if t0 > t1:
            return False
    return True


def _rectangle_in_core(local_core: list[Point], back: float, front: float,
                       half: float) -> bool:
    """Condition SUFFISANTE d'inclusion du rectangle de l'axe ``[back, front]
    × [−half, half]`` (repère local du tee) dans le cœur ``local_core`` (même
    repère) : son centre est intérieur et aucune arête du cœur ne rencontre
    le rectangle fermé ; l'intérieur du rectangle, connexe, ne coupe alors pas
    le bord du cœur et contient un point intérieur, il est dans le cœur."""
    u, v = (back + front) / 2.0, 0.0
    inside = False
    previous = local_core[-1]
    for current in local_core:
        if _segment_meets_rectangle(previous, current, back, front, half):
            return False
        if (current[1] > v) != (previous[1] > v):
            u_cross = ((previous[0] - current[0]) * (v - current[1])
                       / (previous[1] - current[1]) + current[0])
            if u < u_cross:
                inside = not inside
        previous = current
    return inside


def _vertex_edge_distances(points: np.ndarray, polygon: np.ndarray) -> np.ndarray:
    """Distance ``(k, m)`` de chaque point aux ``m`` arêtes de ``polygon``."""
    a = polygon
    ab = np.roll(polygon, -1, axis=0) - a
    ap = points[:, None, :] - a[None, :, :]
    length2 = np.maximum((ab * ab).sum(axis=1), 1e-300)
    t = np.clip((ap * ab[None]).sum(axis=2) / length2, 0.0, 1.0)
    return np.hypot(ap[..., 0] - t * ab[:, 0], ap[..., 1] - t * ab[:, 1])


def _gap(box: np.ndarray, polygon: np.ndarray) -> float:
    """Écart (distance minimale) entre deux polygones FERMÉS, nul s'ils se
    touchent, se coupent ou si l'un contient l'autre. Hors croisement propre
    d'arêtes, la distance de deux segments est atteinte en une extrémité :
    minimum des distances sommet → arête dans les deux sens ; un contact par
    un bord ou un coin seul donne donc 0. Sur une arête oblique, un contact
    exact peut toutefois laisser un résidu flottant (≈ 1e-17) que le test
    ``> 0.0`` accepte comme écart, comme dans ``polygon_gap`` (routage)."""
    a, b = box[:, None, :], np.roll(box, -1, axis=0)[:, None, :]
    c, d = polygon[None, :, :], np.roll(polygon, -1, axis=0)[None, :, :]
    # croisement propre SANS tolérance (``edges_cross`` en a une, qui
    # laisserait passer un croisement rasant avec un écart minuscule > 0)
    if np.any((np.sign(cross(a, b, c)) * np.sign(cross(a, b, d)) < 0)
              & (np.sign(cross(c, d, a)) * np.sign(cross(c, d, b)) < 0)):
        return 0.0
    gap = float(min(_vertex_edge_distances(box, polygon).min(),
                    _vertex_edge_distances(polygon, box).min()))
    if gap > 0.0 and (points_in_polygon(box[:1], polygon)[0]
                      or points_in_polygon(polygon[:1], box)[0]):
        return 0.0
    return gap


def _area(outline) -> float:
    """Aire (valeur absolue, formule du lacet) d'un polygone en tuples."""
    total = 0.0
    for (x0, y0), (x1, y1) in zip(outline, outline[1:] + outline[:1]):
        total += x0 * y1 - x1 * y0
    return abs(total) / 2.0


def _scan(lo: float, hi: float, start: float) -> list[float]:
    """Positions candidates ``d`` du repli pour l'eau dans ``[lo, hi]`` :
    ``start`` d'abord s'il y est, puis la grille ``lo + k·TEE_WATER_STEP``
    et ``hi``, triées par écart à ``start`` (à égalité, la plus courte)."""
    if not lo <= hi:
        return []
    grid = [lo + k * TEE_WATER_STEP for k in range(int((hi - lo) / TEE_WATER_STEP) + 1)]
    grid.append(hi)
    ordered = sorted(set(grid), key=lambda d: (abs(d - start), d))
    return ([start] if lo <= start <= hi else []) + [d for d in ordered if d != start]


def tee_boxes(hole: ElasticHole, core, green_outline, rng: np.random.Generator
              ) -> tuple[tuple[TeeBox, ...], str | None]:
    """Boîtes de départ sans eau connue et cause de bascule
    (``dry_tee_boxes`` sans masque)."""
    return dry_tee_boxes(hole, core, green_outline, rng, None)[:2]


def _lateral_offsets(hole: ElasticHole) -> list[float]:
    """Décalages en travers essayés pour une boîte avancée (blocs, signés,
    côté ``(-hy, hx)`` d'abord) : ``±k·TEE_WATER_STEP`` jusqu'à la
    demi-largeur du cœur, du plus petit au plus grand."""
    count = int(hole.width / 2.0 / TEE_WATER_STEP)
    return [sign * k * TEE_WATER_STEP for k in range(1, count + 1) for sign in (1.0, -1.0)]


def dry_tee_boxes(hole: ElasticHole, core, green_outline, rng: np.random.Generator,
                  water: WaterMask | None, relief: np.ndarray | None = None,
                  raised: np.ndarray | None = None
                  ) -> tuple[tuple[TeeBox, ...], str | None, WaterFix | None]:
    """Boîtes de départ du trou, de l'arrière vers l'avant, cause de bascule
    (``None`` sans bascule) et repli pour l'eau (``WaterFix`` réduit aux
    champs des départs, ``None`` sans repli). ``core`` : polygone du cœur ;
    ``green_outline`` : contour du green déjà placé ; ``water`` : eau
    EFFECTIVE du trou (``golfgen.dressing.water.effective_water`` sur son
    seul green, ``None`` : pas d'eau connue) ; ``relief`` (indexé ``[y,
    x]``) : lu pour une boîte remontée seulement (``ValueError`` s'il manque
    alors) ; ``raised`` : masque ``(h, w)`` des cellules déjà remontées
    (greens de tous les trous, boîtes des trous déjà habillés), où aucune
    boîte ne se remonte (``None`` : aucune). Lève ``DressingError`` si le
    premier segment est nul, si une boîte TIRÉE sort du cœur ou touche le
    green (écart ``_gap`` non strictement positif, contact par un bord
    compris), ou si une boîte sur l'eau ne trouve ni place au sec ni place
    où se remonter.

    Contrôles exacts, au coût réduit (budget d'habillage) : les boîtes sont
    alignées sur l'axe, leur union tient dans le rectangle ``R`` (de l'arrière
    de la boîte arrière à l'avant de la plus avancée), élargi de
    ``ROUNDING_MARGIN`` pour contenir les sommets arrondis ; si ``R`` est
    dans le cœur (``_rectangle_in_core``, condition suffisante), chaque boîte
    l'est ; sinon chaque boîte est contrôlée (``polygon_inside``). De même,
    le contact avec le green n'est contrôlé boîte par boîte que si les
    rectangles englobants de ``R`` et du green se recouvrent.

    Repli pour l'eau (lot 1 eau, décision utilisateur), déterministe, sans
    tirage supplémentaire, appliqué seulement si une boîte tirée n'est pas au
    sec à ``TEE_WATER_MARGIN`` (``golfgen.dressing.water.is_dry``). Une
    position candidate est valide si sa boîte est au sec, dans le cœur et à
    un écart > 0 du green. AUCUNE boîte n'est retirée : le nombre de boîtes
    par par reste celui de la règle.

    Boîtes avancées : chacune est cherchée d'abord DANS L'AXE (positions
    ``_scan``, la position tirée d'abord), puis, à défaut, DÉCALÉE EN
    TRAVERS dans le cœur, comme les départs décalés des vrais parcours
    (``_lateral_offsets``, du plus petit décalage au plus grand, chacun avec
    les mêmes positions dans l'axe) ; les écarts dans l'axe entre boîtes
    restent ceux de la règle ; à défaut, REMONTÉE (``TeeBox.island``,
    ``golfgen.dressing.water.tee_island_of`` : cellules d'eau qu'elle touche
    remontées à l'altitude minimale de sa partie émergée, bord franc ;
    entièrement immergée, à un bloc au-dessus de l'eau) à la première des mêmes
    positions, dans le même ordre (la position tirée d'abord), qui est dans
    le cœur, à un écart > 0 du green et sans cellule de ``raised`` sous
    elle. Trois boîtes : la plus avancée est placée dans
    ``[TEE_SPREAD_MIN_3, Emax]`` autour de ``E`` tiré, puis celle du milieu
    dans ``middle_range`` de ce nouvel étalement, autour de ``d`` tiré.
    Deux boîtes : la plus avancée dans ``[TEE_SPREAD_MIN_2, Emax]``.

    Boîte arrière (centrée sur ``hole.tee`` routé) : si elle n'est pas au
    sec, elle glisse dans l'axe d'au plus ``TEE_BACK_SLIDE_MAX`` bloc
    (``_scan`` autour de 0, pas ``TEE_WATER_STEP``, vers l'arrière d'abord à
    écart égal), à ``TEE_MIN_SPACING`` au moins de la boîte suivante ; à
    défaut, elle est remontée sur le tee routé (pas de décalage en travers :
    elle reste centrée sur ``hole.tee``) ; sinon
    ``DressingError``."""
    first, second = hole.axis[0], hole.axis[1]
    tx, ty = first.x, first.y
    dx, dy = second.x - tx, second.y - ty
    norm = math.hypot(dx, dy)
    if not norm > 0.0 or not math.isfinite(norm):
        raise DressingError(f"trou {hole.order} : premier segment nul, sens du jeu indéfini")
    hx, hy = dx / norm, dy / norm
    nx, ny = -hy, hx

    cap, cause = spread_cap(hole)
    count, cause = settled_count(drawn_count(hole, rng), cap, cause)
    distances = [0.0]
    if count >= 2:
        spread = rng.uniform(TEE_SPREAD_MIN_3 if count == 3 else TEE_SPREAD_MIN_2, cap)
        if count == 3:
            distances.append(rng.uniform(*middle_range(spread)))
        distances.append(spread)

    half_length, half_width = TEE_BOX_LENGTH / 2.0, TEE_BOX_WIDTH / 2.0

    def center_at(d: float, offset: float = 0.0) -> Point:
        if offset == 0.0:
            return (tx + d * hx, ty + d * hy)                  # d = 0 : le tee exact
        return (tx + d * hx + offset * nx, ty + d * hy + offset * ny)

    def outline_at(d: float, offset: float = 0.0) -> tuple[Point, ...]:
        cx, cy = center_at(d, offset)
        return tuple((round(x, 2), round(y, 2))
                     for x, y in _rectangle(cx, cy, hx, hy, -half_length, half_length,
                                            half_width))

    centers = [center_at(d) for d in distances]
    outlines = [outline_at(d) for d in distances]

    # rectangle R (repère local du tee : long, travers) contenant toutes les
    # boîtes arrondies, à ROUNDING_MARGIN près
    back = -half_length - ROUNDING_MARGIN
    front = distances[-1] + half_length + ROUNDING_MARGIN
    half = half_width + ROUNDING_MARGIN
    local_core = [((x - tx) * hx + (y - ty) * hy, (y - ty) * hx - (x - tx) * hy)
                  for x, y in core]
    core_array = np.asarray(core, dtype=float)
    if not _rectangle_in_core(local_core, back, front, half):
        for rank, outline in enumerate(outlines):
            if not polygon_inside(np.array(outline), core_array):
                raise DressingError(f"trou {hole.order} : départ {rank} hors du cœur")
    hull = _rectangle(tx, ty, hx, hy, back, front, half)
    hull_xs, hull_ys = zip(*hull)
    xs, ys = zip(*green_outline)
    green_array = np.asarray(green_outline, dtype=float)
    if (min(hull_xs) <= max(xs) and min(xs) <= max(hull_xs)
            and min(hull_ys) <= max(ys) and min(ys) <= max(hull_ys)):
        for rank, outline in enumerate(outlines):
            if not _gap(np.array(outline), green_array) > 0.0:
                raise DressingError(f"trou {hole.order} : départ {rank} sur le green")

    valid: dict[tuple[float, float], bool] = {}
    liftable: dict[tuple[float, float], bool] = {}
    raised_water = None if raised is None else WaterMask(water=raised)

    def placeable(d: float, offset: float) -> bool:
        box = np.array(outline_at(d, offset))
        return polygon_inside(box, core_array) and _gap(box, green_array) > 0.0

    def ok(d: float, offset: float = 0.0) -> bool:
        if (d, offset) not in valid:
            valid[(d, offset)] = (is_dry(outline_at(d, offset), water, TEE_WATER_MARGIN)
                                  and placeable(d, offset))
        return valid[(d, offset)]

    def can_lift(d: float, offset: float = 0.0) -> bool:
        """Position où la boîte peut être REMONTÉE : dans le cœur, écart > 0
        au green, sans cellule déjà remontée (green, autre boîte, autre
        trou) sous elle."""
        if (d, offset) not in liftable:
            liftable[(d, offset)] = (placeable(d, offset)
                                     and is_dry(outline_at(d, offset), raised_water, 0.0))
        return liftable[(d, offset)]

    moved: tuple[int, ...] = ()
    shifted: tuple[int, ...] = ()
    lifted: list[int] = []
    offsets = [0.0] * len(distances)
    if not all(is_dry(outline, water, TEE_WATER_MARGIN) for outline in outlines[1:]):
        lateral = _lateral_offsets(hole)

        def place(rank: int, lo: float, hi: float, start: float) -> tuple[float, float]:
            positions = _scan(lo, hi, start)
            candidates = [(d, offset) for offset in [0.0] + lateral for d in positions]
            found = next((c for c in candidates if ok(*c)), None)
            if found is None:
                found = next((c for c in candidates if can_lift(*c)), None)
                if found is None:
                    raise DressingError(f"trou {hole.order} : départ {rank} sur l'eau, "
                                        "ni déplaçable au sec ni remontable")
                lifted.append(rank)
            return found

        drawn = list(distances)
        if count == 3:
            far = place(2, TEE_SPREAD_MIN_3, cap, drawn[2])
            settled = [(0.0, 0.0), place(1, *middle_range(far[0]), drawn[1]), far]
        else:
            settled = [(0.0, 0.0), place(1, TEE_SPREAD_MIN_2, cap, drawn[1])]
        moved = tuple(rank for rank in range(1, count) if settled[rank][0] != drawn[rank])
        shifted = tuple(rank for rank in range(1, count) if settled[rank][1] != 0.0)
        distances = [d for d, _ in settled]
        offsets = [offset for _, offset in settled]

    slide = 0.0
    if not is_dry(outlines[0], water, TEE_WATER_MARGIN):
        following = distances[1] if len(distances) > 1 else math.inf
        slide = next((d for d in _scan(-TEE_BACK_SLIDE_MAX, TEE_BACK_SLIDE_MAX, 0.0)
                      if d != 0.0 and following - d >= TEE_MIN_SPACING and ok(d)), None)
        if slide is None:
            slide = 0.0
            if not can_lift(0.0):
                raise DressingError(f"trou {hole.order} : boîte arrière sur l'eau, ni "
                                    f"glissée de {TEE_BACK_SLIDE_MAX:g} bloc au sec ni "
                                    "remontable")
            lifted.append(0)
        distances[0] = slide

    if moved or shifted or lifted or slide:
        centers = [center_at(d, offset) for d, offset in zip(distances, offsets)]
        outlines = [outline_at(d, offset) for d, offset in zip(distances, offsets)]
    islands: list[TeeIsland | None] = [None] * len(outlines)
    if lifted:
        if relief is None:
            raise ValueError(f"trou {hole.order} : boîte remontée, relief requis")
        for rank in lifted:
            islands[rank] = tee_island_of(outlines[rank], relief, water)
    raised_ranks = tuple(sorted(lifted))
    submerged = tuple(rank for rank in raised_ranks if islands[rank].submerged)
    fix = (WaterFix(tees_moved=moved, tees_shifted=shifted, tees_raised=raised_ranks,
                    tees_submerged=submerged, back_slide=slide)
           if moved or shifted or lifted or slide else None)

    heading = (hx, hy)
    return tuple(TeeBox(outline=outline, center=center, area=round(_area(outline), 2),
                        rank=rank, heading=heading, island=island)
                 for rank, (outline, center, island)
                 in enumerate(zip(outlines, centers, islands))), cause, fix
