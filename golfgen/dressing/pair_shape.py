"""Greens doubles : forme partagée et oracle (habillage, rounds R3c et R3f).

Forme de production (R3f : variante A des planches R3e, choisie par
l'utilisateur) : ``pair_outline``, en deux temps, déterministe (aucun
tirage).

1. Forme de départ : enveloppe convexe ``H`` des deux contours de greens
   habillés, PINCÉE au milieu de l'axe des centres jusqu'au col ``w``
   (``pinched_shape``, mécanisme (c) de R3b/R3c, décrit ci-dessous), avec
   ``w = max(NECK_FLOOR, NECK_RATIO × W)``, ``NECK_RATIO = 1,0`` : col égal à
   la largeur ``W`` du plus petit green. Si ``w`` atteint la corde ``W0`` de
   ``H`` au milieu des centres, le pincement est nul : la forme de départ
   EST ``H`` (``pinched_shape`` n'est pas appelé : son flanc serait confondu
   avec les arcs des greens).
2. Dilatation arrondie de ``DILATION`` blocs avec fermeture de rayon
   ``CLOSING`` (``golfgen.dressing.offset.offset_closing`` : angles
   saillants arrondis à ``DILATION``, rentrants à ``CLOSING`` au moins),
   contour rééchantillonné au pas ``RESAMPLE_STEP``. Le résultat contient la
   forme de départ dilatée de ``DILATION`` : greens et drapeaux dedans. Il
   DÉPASSE l'empreinte ``H`` (de ``DILATION`` au moins) : les contrôles de
   distance de la sélection, faits sur ``H``, sont revérifiés par l'oracle
   sur la forme finale.

Pincement (forme de départ) : repère local d'origine le milieu ``m`` des
centres (``GreenShape.center``),
abscisse ``s`` le long de l'axe ``ci → cj`` (``ci`` en ``s = −h``, ``cj`` en
``s = +h``, ``h = d / 2``), ordonnée ``t`` sur la normale (rotation directe :
les sens de parcours sont conservés). L'enveloppe convexe ``H`` a, à chaque
abscisse, une coupe ``[t_bas(s), t_haut(s)]`` (chaînes inférieure et
supérieure, affines par morceaux). Le pincement multiplie ``t`` par
``f(s) = 1 − p·cos²(π s / d)`` pour ``|s| < h`` (1 au-delà), ``p = 1 − w /
W0``, ``W0`` = corde de ``H`` au milieu : la coupe du milieu vaut exactement
``w``. L'enveloppe pincée est donc la région ``f·t_bas ≤ t ≤ f·t_haut`` ; ses
deux flancs ``t = f(s)·t_haut(s)`` et ``t = f(s)·t_bas(s)`` sont échantillonnés
au pas ``FLANK_STEP`` (plus les abscisses des sommets de ``H``).

Construction directe (sans union générique) : hors de la bande ``|s| < h``,
la forme est ``H`` (le pincement y est nul et ``H`` contient les greens) ;
dans la bande, chaque côté est un chemin du point de ``H`` en ``s = −h`` à
celui en ``s = +h`` qui suit le flanc et, là où un green dépasse du flanc,
l'arc de son contour : parcours du bord extérieur, avec changement de courbe
à chaque croisement flanc ↔ contour (entrées et sorties vérifiées). Le côté
inférieur est le côté supérieur de la configuration tournée de 180°.
Forme pincée ⊆ ``H``.

Contours d'entrée nettoyés (``clean_outline``, R3c retouches) : sommets
consécutifs identiques ou quasi identiques (à ``ON_TOL`` près) et point de
fermeture dupliqué retirés ; sommet non fini (NaN, inf), contour de moins de
3 sommets ou d'aire nulle : ``PairShapeError``.

Plus de règle ``w < W`` (R3f) : le col visé vaut ``W`` (ou le plancher) ;
l'oracle vérifie que le col réel de la forme finale est ≥ ``W``.

Oracle ``check_green_pairs`` (forme finale, seul chevauchement de cœurs
permis) : voir ``ORACLE_CHECKS`` et ``check_pair_shape``
(``golfgen.dressing.pairs``).
"""

from __future__ import annotations

import math
from fractions import Fraction
import sys

import numpy as np

from golfgen.dressing.green import (BEAN_MIN_NECK, _convex_hull, _following, chord_length,
                                    edges_cross, points_in_polygon, shoelace)
from golfgen.dressing.model import GreenPair, Point
from golfgen.dressing.offset import GRID_STEP, offset_closing, resample


# R3f (variante A des planches R3e) : col visé = largeur du plus petit green
# (R3c : 0,6 × W, avec la règle w < W, abandonnée), puis forme dilatée.
NECK_RATIO = 1.0                # w = 1,0 × largeur du plus petit green
NECK_FLOOR = BEAN_MIN_NECK      # 5,5 blocs : plancher du col (règle du haricot)
DILATION = 1.5                  # blocs : dilatation arrondie de la forme pincée
CLOSING = 3.0                   # blocs : rayon de la fermeture (angles rentrants)
RESAMPLE_STEP = 0.5             # blocs : pas du contour final
FLANK_STEP = 0.5                # blocs : pas max des flancs pincés (comme R3b)
NECK_STEP = 0.05                # blocs : pas des coupes de la mesure du col
CONTAIN_TOL = 1e-6              # blocs : inclusion des contours de greens
CONTAIN_STEP = 0.1              # blocs : échantillonnage des arêtes (inclusion)
ON_TOL = 1e-9                   # blocs : point posé sur un contour
EPSILON = 1e-12
# borne d'erreur relative d'orient2d (Shewchuk, ccwerrboundA), ε = 2⁻⁵³
_ORIENT_BOUND = (3.0 + 16.0 * 2.0 ** -53) * 2.0 ** -53


class PairShapeError(ValueError):
    """Forme du green double impossible à construire (géométrie dégénérée,
    parcours du bord incohérent) : la paire est rejetée."""


class GreensOverlapError(PairShapeError):
    """Les deux greens se chevauchent : la paire est rejetée (cause
    distincte d'un échec de construction)."""


# --- largeur de col -----------------------------------------------------------

def min_width(polygon) -> float:
    """Largeur minimale au pied à coulisse (celle de l'enveloppe convexe :
    minimum, sur les arêtes de l'enveloppe, de la plus grande distance d'un
    sommet à la droite de l'arête)."""
    hull = _convex_hull(np.asarray(polygon, dtype=float))
    edge = _following(hull) - hull
    length = np.linalg.norm(edge, axis=1)
    rel = hull[None, :, :] - hull[:, None, :]
    dist = np.abs(edge[:, None, 0] * rel[..., 1] - edge[:, None, 1] * rel[..., 0]) / length[:, None]
    return float(dist.max(axis=1).min())


def neck_target(first_outline, second_outline) -> tuple[float, float]:
    """``(w, W)`` : ``W`` largeur du plus petit green, ``w = max(NECK_FLOOR,
    NECK_RATIO × W)`` (col visé de la forme pincée de départ)."""
    smaller = min(min_width(first_outline), min_width(second_outline))
    return max(NECK_RATIO * smaller, NECK_FLOOR), smaller


# --- repère local -------------------------------------------------------------

def _frame(ci, cj) -> tuple[np.ndarray, np.ndarray, float]:
    """Milieu ``m``, rotation ``R`` (lignes : axe ``u``, normale ``n``) et
    demi-distance ``h`` ; local = ``(p − m) @ R.T``, monde = ``m + local @ R``."""
    ci, cj = np.asarray(ci, dtype=float), np.asarray(cj, dtype=float)
    d = float(np.linalg.norm(cj - ci))
    if d <= 0.0:
        raise PairShapeError("centres confondus")
    u = (cj - ci) / d
    return 0.5 * (ci + cj), np.array((u, (-u[1], u[0]))), 0.5 * d


def _ccw(polygon) -> np.ndarray:
    points = np.asarray(polygon, dtype=float)
    return points[::-1].copy() if shoelace(points) < 0 else points


def _chains(hull: np.ndarray):
    """Chaînes inférieure et supérieure de l'enveloppe ``hull`` (locale, sens
    trigonométrique), chacune triée par ``s`` croissant : ``(s, t)``."""
    order = np.lexsort((hull[:, 1], hull[:, 0]))
    first, last = int(order[0]), int(order[-1])         # gauche-bas, droite-haut
    rolled = np.roll(hull, -first, axis=0)
    split = (last - first) % len(hull)
    lower = rolled[:split + 1]
    upper = np.concatenate((rolled[split:], rolled[:1]))[::-1]
    return lower, upper


def _samples(regular: np.ndarray, inner: np.ndarray) -> np.ndarray:
    """Abscisses du flanc, croissantes : échantillons réguliers ``regular``
    et abscisses ``inner`` des sommets de l'enveloppe, sauf celles à
    ``ON_TOL`` près d'une abscisse déjà gardée (un sommet d'enveloppe posé
    sur un échantillon, à l'arrondi près, ferait un segment de flanc de
    longueur ~1e-15, de direction arbitraire)."""
    kept = np.unique(regular)
    for x in np.unique(inner).tolist():
        if np.abs(kept - x).min() > ON_TOL:
            kept = np.insert(kept, np.searchsorted(kept, x), x)
    return kept


def _pinch(s: np.ndarray, h: float, depth: float) -> np.ndarray:
    inside = np.abs(s) < h
    return np.where(inside, 1.0 - depth * np.cos(0.5 * math.pi * s / h) ** 2, 1.0)


# --- parcours d'un côté -------------------------------------------------------

def _sides(value: np.ndarray, tie: np.ndarray) -> np.ndarray:
    """Côté (``True`` : positif) d'après le signe de ``value`` ; ``value``
    nul : côté ``tie`` (signe de la dérivée selon la perturbation ``δ``)."""
    return (value > 0.0) | ((value == 0.0) & tie)


def _tie_sides(direction: np.ndarray) -> np.ndarray:
    """Signe de ``−δ × d`` pour chaque direction ``d``, ``δ = (ε, ε²)``,
    ``ε → 0⁺`` : celui de ``−d_y``, ou de ``d_x`` si ``d_y = 0``."""
    return np.where(direction[:, 1] != 0.0, direction[:, 1] < 0.0, direction[:, 0] > 0.0)


def _orientations(p: np.ndarray, a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """``(a − p) × (b − a)`` (tableaux diffusables ``(…, 2)``) : valeur
    flottante, SIGNE EXACT. Filtre d'erreur de Shewchuk (``orient2d``,
    borne ``ccwerrboundA``) ; valeurs douteuses (dont les nulles, et les non
    finies : débordement du calcul flottant) recalculées en rationnels
    exacts (``Fraction`` des flottants), puis arrondies par
    ``_signed_float`` : signe pris sur le rationnel, zéro seulement si
    l'orientation est exactement nulle (débordement ou sous-dépassement de
    l'arrondi saturés, sans changer le signe)."""
    with np.errstate(over="ignore", under="ignore", invalid="ignore"):
        u, v = a - p, b - a
        left, right = u[..., 0] * v[..., 1], u[..., 1] * v[..., 0]
        value = left - right                    # inf − inf : NaN, donc douteux
        doubt = ~(np.abs(value) > _ORIENT_BOUND * (np.abs(left) + np.abs(right)))
    if doubt.any():
        shape = value.shape + (2,)
        p, a, b = (np.broadcast_to(x, shape) for x in (p, a, b))
        for index in zip(*np.nonzero(doubt)):
            value[index] = _signed_float(_exact_orientation(p[index], a[index], b[index]))
    return value


def _signed_float(value: Fraction) -> float:
    """``value`` arrondi en flottant, SIGNE de ``value`` (pris sur le
    rationnel, jamais sur l'arrondi) : hors de la plage des flottants, le
    plus grand flottant fini ; sous le plus petit flottant non nul, celui-ci
    (pas de faux zéro) ; ``0.0`` seulement pour ``value == 0``."""
    if value == 0:
        return 0.0
    sign = 1.0 if value > 0 else -1.0
    try:
        rounded = abs(float(value))
    except OverflowError:
        rounded = math.inf
    return sign * min(max(rounded, math.ulp(0.0)), sys.float_info.max)


def _exact_orientation(p, a, b) -> Fraction:
    """``(a − p) × (b − a)`` en rationnels exacts (points flottants)."""
    (px, py), (ax, ay), (bx, by) = (map(Fraction, np.asarray(x, dtype=float).tolist())
                                    for x in (p, a, b))
    return (ax - px) * (by - ay) - (ay - py) * (bx - ax)


def _exact_ratio(p0, p1, a, b) -> float:
    """``t`` exact (arrondi) du point ``p0 + t (p1 − p0)`` posé sur la
    droite ``a b`` : rapport des orientations exactes de ``p0`` et ``p1``
    (affines le long du segment), de signes opposés ou nulle pour l'une."""
    first, second = _exact_orientation(p0, a, b), _exact_orientation(p1, a, b)
    return float(first / (first - second))


def _crossings(flank: np.ndarray, ring: np.ndarray):
    """Croisements du flanc (polyligne ouverte) et d'un anneau fermé :
    positions ``k + α`` sur le flanc, ``e + β`` sur l'anneau, points, et
    ``entre`` (le flanc entre dans l'anneau, intérieur à droite de l'anneau).

    Prédicats d'orientation à signe exact (``_orientations``) et partagés :
    le côté d'un sommet du flanc par rapport à la droite d'une arête de
    l'anneau est calculé UNE fois et sert aux deux segments du flanc qui
    s'y joignent (de même pour un sommet de l'anneau par rapport à la
    droite d'un segment du flanc). Égalités exactes (orientation nulle) :
    tranchées comme si le flanc entier était translaté de ``δ = (ε, ε²)``
    infinitésimal (perturbation symbolique, une seule pour tous les
    prédicats ; ``δ`` n'est parallèle à aucune arête non nulle). Les signes
    sont donc ceux d'une configuration réelle en position générale : pour
    tout flanc et tout anneau finis, le nombre de croisements a la parité
    exacte du changement intérieur/extérieur (perturbé) entre les deux
    extrémités du flanc, et ``entre`` alterne le long du flanc perturbé (un
    sommet du flanc posé sur une arête ou un sommet de l'anneau : un
    croisement s'il le traverse, aucun ou deux s'il ne fait que le toucher).
    Seules les POSITIONS sont arrondies (``α``, ``β`` flottants, bornés à
    ``[0, 1]``) : des croisements confondus ou distants de l'ordre de
    l'arrondi peuvent sortir dans le désordre (``_side_path`` rejette les
    croisements confondus)."""
    a, r = flank[:-1], flank[1:] - flank[:-1]
    c, q = ring, _following(ring) - ring
    # (c_e − f_v) × q_e : > 0 si le sommet v du flanc est à gauche de
    # l'arête e (hors de l'anneau horaire) ; pour v = k, numérateur de α
    side_flank = _orientations(flank[:, None, :], c[None, :, :], _following(ring)[None, :, :])
    # (c_v − a_k) × r_k = −(a_k − c_v) × r_k : côté du sommet v de l'anneau
    # / segment k du flanc, numérateur de β
    side_ring = -_orientations(c[None, :, :], a[:, None, :], flank[1:, None, :])
    out = _sides(side_flank, _tie_sides(q)[None, :])
    right = _sides(side_ring, _tie_sides(r)[:, None])
    hit = (out[:-1] != out[1:]) & (right != _following(right.T).T)
    k, e = np.nonzero(hit)
    num_a, num_b = side_flank[k, e], side_ring[k, e]
    with np.errstate(over="ignore", invalid="ignore"):
        denom = r[k, 0] * q[e, 1] - r[k, 1] * q[e, 0]
    # α, β : intersection des droites (bornées à [0, 1] : arrondi) ;
    # segments presque parallèles (intersection mal conditionnée) ou calcul
    # flottant débordé : interpolation des orientations exactes des
    # extrémités (signes opposés, ou un zéro : dans [0, 1], bornée aussi)
    ok = (np.abs(denom) > EPSILON) & np.isfinite(denom)
    safe = np.where(ok, denom, 1.0)
    al, be = np.clip(num_a / safe, 0.0, 1.0), np.clip(num_b / safe, 0.0, 1.0)
    following = _following(ring)
    for n in np.flatnonzero(~ok).tolist():
        kn, en = k[n], e[n]
        al[n] = min(max(_exact_ratio(flank[kn], flank[kn + 1], ring[en], following[en]), 0.0), 1.0)
        be[n] = min(max(_exact_ratio(ring[en], following[en], flank[kn], flank[kn + 1]), 0.0), 1.0)
    points = a[k] + al[:, None] * r[k]
    # anneau horaire (intérieur à droite) : le flanc entre s'il passe de la
    # gauche (dehors) à la droite de l'arête
    enters = out[k, e]
    return k + al, (e + be) % len(ring), points, enters


def _ring_position(ring: np.ndarray, point: np.ndarray) -> float | None:
    """Position ``e + β`` de ``point`` sur l'anneau s'il y est posé (à
    ``ON_TOL`` près), sinon ``None``."""
    a, q = ring, _following(ring) - ring
    length2 = np.maximum((q * q).sum(axis=1), 1e-300)
    beta = np.clip(((point - a) * q).sum(axis=1) / length2, 0.0, 1.0)
    gap = np.hypot(*(a + beta[:, None] * q - point).T)
    e = int(np.argmin(gap))
    if gap[e] > ON_TOL:
        return None
    return float(e + beta[e]) % len(ring)


def _side_path(flank: np.ndarray, greens) -> list:
    """Bord extérieur du côté supérieur, de ``flank[0]`` à ``flank[-1]``
    (sens horaire : la forme à droite). ``greens`` : contours locaux (sens
    trigonométrique), parcourus en sens horaire."""
    rings = [g[::-1] for g in greens]
    start, end = flank[0], flank[-1]
    hits = []                       # (pos flanc, anneau, pos anneau, point, entre)
    for index, ring in enumerate(rings):
        fpos, rpos, points, enters = _crossings(flank, ring)
        for f, p, x, enter in zip(fpos.tolist(), rpos.tolist(), points, enters.tolist()):
            if min(np.hypot(*(x - start)), np.hypot(*(x - end))) <= ON_TOL:
                continue                # extrémités posées sur un contour : pas un croisement
            hits.append((f, index, p, x, enter))
    hits.sort(key=lambda hit: hit[0])
    for a, b in zip(hits, hits[1:]):
        if np.hypot(*(a[3] - b[3])) <= ON_TOL:
            raise PairShapeError("croisements confondus")
    end_on = {index: pos for index, ring in enumerate(rings)
              if (pos := _ring_position(ring, end)) is not None}

    path = [start]
    on_ring, pos = None, 0.0
    for index, ring in enumerate(rings):
        here = _ring_position(ring, start)
        if here is None:
            continue
        first = next((hit for hit in hits if hit[1] == index), None)
        if first is not None and not first[4]:
            on_ring, pos = index, here          # flanc parti dans ce green : on suit le contour
        elif first is None and points_in_polygon(0.5 * (flank[:1] + flank[1:2]), ring)[0]:
            on_ring, pos = index, here
        break
    for _ in range(len(hits) + 2):
        if on_ring is None:
            nxt = next((hit for hit in hits if hit[0] > pos + EPSILON), None)
            stop = math.floor(nxt[0]) if nxt is not None else len(flank) - 1
            path.extend(flank[math.floor(pos) + 1:stop + 1])
            if nxt is None:
                if not np.array_equal(path[-1], end):
                    path.append(end)
                return path
            if not nxt[4]:
                raise PairShapeError("flanc qui sort d'un green hors du bord extérieur")
            path.append(nxt[3])
            on_ring, pos = nxt[1], nxt[2]
            continue
        ring = rings[on_ring]
        size = len(ring)
        ahead = [((hit[2] - pos) % size, hit) for hit in hits
                 if hit[1] == on_ring and (hit[2] - pos) % size > EPSILON]
        to_end = (end_on[on_ring] - pos) % size if on_ring in end_on else math.inf
        step, hit = min(ahead, key=lambda item: item[0]) if ahead else (math.inf, None)
        if to_end < step:
            step = to_end
        if math.isinf(step):
            raise PairShapeError("contour de green sans retour au flanc")
        first = math.floor(pos) + 1
        last = math.floor(pos + step)
        path.extend(ring[k % size] for k in range(first, last + 1))
        if step == to_end:
            path.append(end)
            return path
        if hit[4]:
            raise PairShapeError("retour au flanc sur une entrée")
        path.append(hit[3])
        on_ring, pos = None, hit[0]
    raise PairShapeError("parcours du bord non terminé")


def _dedupe(points: np.ndarray) -> np.ndarray:
    """Sommets sans doublon consécutif (à ``ON_TOL`` près), fermeture
    comprise : un sommet est retiré s'il coïncide avec le suivant (le
    dernier avec le premier, point de fermeture dupliqué)."""
    keep = np.hypot(*(points - _following(points)).T) > ON_TOL
    return points[keep]


def clean_outline(outline) -> np.ndarray:
    """Contour d'entrée de la construction, sens trigonométrique, sans
    sommets consécutifs identiques ou quasi identiques (``_dedupe``, point
    de fermeture dupliqué compris). ``PairShapeError`` si un sommet n'est
    pas fini (NaN, inf : refusé AVANT le dédoublonnage, qui l'écarterait
    sans bruit, ses distances étant NaN), ou s'il reste moins de 3 sommets
    ou une aire nulle (contour dégénéré)."""
    points = np.asarray(outline, dtype=float).reshape(-1, 2)
    if not np.isfinite(points).all():
        raise PairShapeError("contour de green non fini (NaN ou inf)")
    if len(points):
        points = _dedupe(points)
    if len(points) < 3 or abs(shoelace(points)) <= EPSILON:
        raise PairShapeError("contour de green dégénéré")
    return _ccw(points)


def pinched_shape(first_outline, second_outline, first_center, second_center,
                  w: float) -> np.ndarray:
    """Contour (sens trigonométrique, coordonnées de la carte, non arrondies)
    de l'enveloppe convexe des deux greens pincée à ``w`` au milieu de l'axe
    des centres, unie aux deux greens. ``PairShapeError`` si les greens se
    chevauchent (``GreensOverlapError``), si un contour est dégénéré ou si le
    parcours du bord échoue. Contours d'entrée nettoyés (``clean_outline``)."""
    return _pinched_shape(clean_outline(first_outline), clean_outline(second_outline),
                          first_center, second_center, w)


def _pinched_shape(gi: np.ndarray, gj: np.ndarray, first_center, second_center,
                   w: float) -> np.ndarray:
    """``pinched_shape`` sur des contours déjà nettoyés (``clean_outline``)."""
    if edges_cross(gi, gj) or points_in_polygon(gi[:1], gj)[0] or points_in_polygon(gj[:1], gi)[0]:
        raise GreensOverlapError("greens qui se chevauchent")
    m, rot, h = _frame(first_center, second_center)
    hull = (_convex_hull(np.concatenate((gi, gj))) - m) @ rot.T
    li, lj = (gi - m) @ rot.T, (gj - m) @ rot.T
    lower, upper = _chains(hull)
    w0 = float(np.interp(0.0, upper[:, 0], upper[:, 1]) - np.interp(0.0, lower[:, 0], lower[:, 1]))
    depth = 1.0 - min(w / w0, 1.0) if w0 > 0.0 else 0.0
    count = max(2, math.ceil(2.0 * h / FLANK_STEP))
    inner = hull[:, 0][np.abs(hull[:, 0]) < h]
    s = _samples(np.linspace(-h, h, count + 1), inner)
    factor = _pinch(s, h, depth)
    top = np.column_stack((s, factor * np.interp(s, upper[:, 0], upper[:, 1])))
    # côté inférieur = côté supérieur de la configuration tournée de 180°
    bottom = np.column_stack((-s[::-1], -(factor * np.interp(s, lower[:, 0], lower[:, 1]))[::-1]))
    up = _side_path(top, (li, lj))
    down = [-p for p in _side_path(bottom, (-li, -lj))]
    by_s = np.argsort(hull[:, 0], kind="stable")
    left_first = np.roll(hull, -int(by_s[-1]), axis=0)     # départ au sommet le plus à droite
    right_first = np.roll(hull, -int(by_s[0]), axis=0)     # départ au sommet le plus à gauche
    right = right_first[right_first[:, 0] > h][::-1]      # haut → bas (sens horaire)
    left = left_first[left_first[:, 0] < -h][::-1]        # bas → haut
    clockwise = np.concatenate((np.asarray(up), right.reshape(-1, 2),
                                np.asarray(down), left.reshape(-1, 2)))
    local = _dedupe(clockwise[::-1])
    return m + local @ rot


def mid_chord(hull: np.ndarray, first_center, second_center) -> float:
    """Corde ``W0`` de ``hull`` sur la perpendiculaire à l'axe des centres en
    leur milieu."""
    m, rot, _ = _frame(first_center, second_center)
    return chord_length(hull, m, rot[1])


def base_shape(gi: np.ndarray, gj: np.ndarray, first_center, second_center,
               w: float) -> np.ndarray:
    """Forme de départ (contours déjà nettoyés) : enveloppe pincée à ``w``,
    ou l'enveloppe elle-même si ``w ≥ W0`` (``mid_chord``). Lève
    ``GreensOverlapError`` si les greens se chevauchent."""
    if edges_cross(gi, gj) or points_in_polygon(gi[:1], gj)[0] or points_in_polygon(gj[:1], gi)[0]:
        raise GreensOverlapError("greens qui se chevauchent")
    hull = _convex_hull(np.concatenate((gi, gj)))
    if w >= mid_chord(hull, first_center, second_center):
        return hull
    return _pinched_shape(gi, gj, first_center, second_center, w)


def pair_outline(first_outline, second_outline, first_center, second_center,
                 w: float, step: float = GRID_STEP) -> np.ndarray:
    """Contour de production du green double (sens trigonométrique,
    coordonnées de la carte, non arrondies) : forme de départ
    (``base_shape``) dilatée de ``DILATION`` avec fermeture de rayon
    ``CLOSING`` (``offset_closing``, grille de pas ``step``), rééchantillonnée
    au pas ``RESAMPLE_STEP``. ``PairShapeError`` si un contour est dégénéré,
    si les greens se chevauchent (``GreensOverlapError``), si le parcours du
    bord échoue ou si la forme lissée n'est pas d'un seul tenant (plusieurs
    boucles)."""
    gi, gj = clean_outline(first_outline), clean_outline(second_outline)
    base = clean_outline(base_shape(gi, gj, first_center, second_center, w))
    try:
        shape, loops = offset_closing(base, DILATION, CLOSING, step)
    except ValueError as exc:                   # marching squares incohérent
        raise PairShapeError(f"lissage : {exc}") from None
    if loops != 1:
        raise PairShapeError(f"forme lissée en {loops} boucles")
    return resample(shape, RESAMPLE_STEP)


def build_pair(pair: GreenPair, first_green, second_green) -> GreenPair:
    """``pair`` complétée de sa forme (``pair_outline``) et du col visé ``w``
    (``GreenShape`` des trous ``i`` et ``j``). Lève ``PairShapeError`` si la
    construction échoue ou si un contour est invalide."""
    w, _ = neck_target(first_green.outline, second_green.outline)
    shape = pair_outline(first_green.outline, second_green.outline, first_green.center,
                         second_green.center, w)
    return GreenPair(i=pair.i, j=pair.j, distance=pair.distance, footprint=pair.footprint,
                     outline=tuple((float(x), float(y)) for x, y in shape), neck_width=w)


# --- mesures de l'oracle ------------------------------------------------------

def _densify(polygon: np.ndarray, step: float) -> np.ndarray:
    following = _following(polygon)
    counts = np.maximum(1, np.ceil(np.hypot(*(following - polygon).T) / step).astype(int))
    index = np.repeat(np.arange(len(polygon)), counts)
    frac = np.concatenate([np.arange(c) / c for c in counts])
    return polygon[index] + frac[:, None] * (following - polygon)[index]


def _edge_distances(points: np.ndarray, polygon: np.ndarray) -> np.ndarray:
    """Distance ``(k,)`` de chaque point au bord du polygone."""
    a = polygon
    ab = _following(polygon) - a
    ap = points[:, None, :] - a[None, :, :]
    length2 = np.maximum((ab * ab).sum(axis=1), 1e-300)
    t = np.clip((ap * ab[None]).sum(axis=2) / length2, 0.0, 1.0)
    return np.hypot(ap[..., 0] - t * ab[:, 0], ap[..., 1] - t * ab[:, 1]).min(axis=1)


def contains_outline(shape, outline) -> bool:
    """``outline`` ⊆ ``shape`` : ses sommets et ses arêtes échantillonnées
    (pas ``CONTAIN_STEP``) sont intérieurs ou à moins de ``CONTAIN_TOL`` du
    bord (les arcs de green repris par la forme sont SUR son bord)."""
    shape = np.asarray(shape, dtype=float)
    samples = _densify(np.asarray(outline, dtype=float), CONTAIN_STEP)
    outside = samples[~points_in_polygon(samples, shape)]
    return not len(outside) or bool(_edge_distances(outside, shape).max() <= CONTAIN_TOL)


def is_simple(shape) -> bool:
    """Aucune paire d'arêtes ne se coupe proprement (contacts aux sommets
    partagés exclus)."""
    shape = np.asarray(shape, dtype=float)
    return not edges_cross(shape, shape)


def neck_measure(shape, first_outline, second_outline, first_center, second_center
                 ) -> tuple[float, tuple[Point, Point] | None]:
    """Col réel et ses extrémités : minimum, sur les coupes perpendiculaires à
    l'axe des centres (pas ``NECK_STEP``) prises ENTRE les deux greens (de la
    face avancée de l'un à celle de l'autre, dans ``[−h, h]``), de la
    longueur de la composante de la coupe qui contient le point de l'axe
    (plus proches croisements du bord de part et d'autre), pas de
    l'étendue extrême de la coupe (biais des formes non convexes). Si UNE
    coupe entre les greens n'a pas de bord d'un côté de l'axe (l'axe sort
    de la forme) : ``(inf, None)``, col non mesurable (l'oracle ``col``
    échoue), au lieu d'ignorer cette coupe."""
    m, rot, h = _frame(first_center, second_center)
    local = (np.asarray(shape, dtype=float) - m) @ rot.T
    face_i = float(((np.asarray(first_outline, dtype=float) - m) @ rot[0]).max())
    face_j = float(((np.asarray(second_outline, dtype=float) - m) @ rot[0]).min())
    lo, hi = sorted((min(max(face_i, -h), h), min(max(face_j, -h), h)))
    s = np.linspace(lo, hi, max(1, math.ceil((hi - lo) / NECK_STEP)) + 1)
    a, b = local, _following(local)
    straddle = (a[None, :, 0] <= s[:, None]) != (b[None, :, 0] <= s[:, None])
    dx = np.where(straddle, b[:, 0] - a[:, 0], 1.0)
    t = a[:, 1] + (s[:, None] - a[:, 0]) * (b[:, 1] - a[:, 1]) / dx
    below = np.where(straddle & (t <= 0.0), t, -np.inf).max(axis=1)
    above = np.where(straddle & (t > 0.0), t, np.inf).min(axis=1)
    width = above - below
    if not np.isfinite(width).all():
        return math.inf, None
    k = int(np.argmin(width))
    ends = np.array(((s[k], below[k]), (s[k], above[k]))) @ rot + m
    return float(width[k]), (tuple(map(float, ends[0])), tuple(map(float, ends[1])))
