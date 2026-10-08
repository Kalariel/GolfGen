"""Métriques de forme d'un parcours Muirfield (défaut « hélice / moulinet »).

Fonctions pures et déterministes (aucun aléa) : elles mesurent la forme d'un
``CourseLayout`` sans rien changer au routage. Elles servent de base avant le
round R2b, qui vise à casser l'aspect hélice ou moulinet.

Le centre de référence est le centre de la carte ``(width/2, height/2)`` : les
anneaux Muirfield y sont centrés. Les nines se déduisent de ``hole.order``
(1–9 = front, 10–18 = back), chaque nine étant trié par ordre de jeu.

Trois métriques, calculées par nine et pour le parcours entier :

- ``angular_step_cv`` : coefficient de variation des pas angulaires entre
  greens successifs. Bas → progression trop régulière autour du centre
  (hélice).
- ``direction_entropy`` : entropie normalisée des orientations des trous
  (orientation = corde tee→green ; les coudes sont ignorés). Basse → trous
  en faisceaux parallèles.
- ``radial_alignment_R`` : concentration de l'obliquité des trous par rapport
  au rayon. Haute → pales de même obliquité (moulinet).

Deux métriques par nine seulement, quand le chemin du nine (``front_path`` /
``back_path`` de ``MuirfieldResult``, orienté dans le sens de jeu) est fourni :

- ``obliquity_signed`` : moyenne de sin α, α = angle signé entre la corde
  tee→green et la tangente du chemin (segment le plus proche du milieu de la
  corde). ≈ 0 → trous tangents (ou à rebours, ou obliquités qui se
  compensent) ; nettement d'un seul signe → pales de moulinet.
- ``obliquity_abs`` : moyenne de |sin α| (obliquité sans signe).

Round R2b M2 (chemin intérieur à lobes), par nine :

- ``heading_turns`` (toujours) : Σ|Δcap| / 2π sur la suite des cordes
  tee→green successives ; auto-enroulement du nine (≈ 1 pour un tour simple,
  au-delà le nine s'enroule ou zigzague).
- ``hull_ratio`` (``outer_ring`` fourni) : aire de l'enveloppe convexe des
  tees et greens du nine / aire du polygone de l'anneau extérieur ; non
  borné à [0, 1] (le nine extérieur dépasse 1).
- ``path_to_nine_length`` et ``forward_mean`` (chemin fourni) : longueur du
  chemin cible / longueur nominale du nine (``nominal_nine_length``) ;
  moyenne de cos α (trous joués à rebours : cos α < 0).
- ``obliquity_signed_ring`` / ``obliquity_abs_ring`` (chemin ANNEAU fourni) :
  obliquités mesurées sur l'anneau, comparables au round R2b 1 quand le
  chemin effectif est à lobes.
"""

from __future__ import annotations

import math
from typing import Sequence

import numpy as np

from experiments.elastic_routing.model import PAR_SPECS, CourseLayout, ElasticHole
from experiments.elastic_routing.muirfield import LINK_NOMINAL


Point = tuple[float, float]

DIRECTION_BINS = 12                 # cases de 15° sur [0°, 180°)
CV_MIN_PROGRESS = math.pi / 2       # |Σ Δθ| en deçà : pas de tour net, CV non défini


def _as_array(points: Sequence[Point]) -> np.ndarray:
    return np.asarray(points, dtype=float).reshape(-1, 2)


def _wrap(angles: np.ndarray) -> np.ndarray:
    """Ramène des écarts angulaires dans [-π, π)."""
    return (angles + math.pi) % (2.0 * math.pi) - math.pi


def oriented_angular_steps(greens: Sequence[Point], centre: Point) -> np.ndarray:
    """Pas angulaires Δθ entre greens successifs, orientés selon le sens du nine.

    Les angles θ sont pris autour de ``centre`` ; chaque Δθ est déroulé dans
    [-π, π) (un passage de +179° à -179° compte +2°, pas -358°). Choix :
    Δθ SIGNÉ, multiplié par le signe de la somme des pas (sens dominant de la
    boucle), de sorte qu'un parcours horaire et son miroir anti-horaire donnent
    les mêmes pas. Un pas à rebours reste négatif : il augmente la dispersion
    au lieu de passer pour un pas régulier, ce qu'une valeur absolue masquerait.
    """
    points = _as_array(greens)
    if len(points) < 2:
        return np.zeros(0)
    theta = np.arctan2(points[:, 1] - centre[1], points[:, 0] - centre[0])
    steps = _wrap(np.diff(theta))
    return steps * (-1.0 if steps.sum() < 0.0 else 1.0)


def _cv(steps: np.ndarray) -> float | None:
    if steps.size == 0:
        return None
    if abs(float(steps.sum())) < CV_MIN_PROGRESS:
        return None
    return float(steps.std()) / abs(float(steps.mean()))


def angular_step_cv(greens: Sequence[Point], centre: Point) -> float | None:
    """Coefficient de variation (écart-type / moyenne) des pas angulaires.

    Pas orientés de ``oriented_angular_steps`` ; écart-type de population.
    ``None`` si moins de deux greens ou si la progression nette |Σ Δθ| est
    inférieure à ``CV_MIN_PROGRESS`` (π/2 : la boucle ne tourne pas assez
    autour du centre pour qu'un pas moyen ait un sens). Une valeur proche de 0 signale une hélice : les
    greens avancent d'un pas constant autour du centre.
    """
    return _cv(oriented_angular_steps(greens, centre))


def _orientations(tees: Sequence[Point], greens: Sequence[Point]) -> np.ndarray:
    delta = _as_array(greens) - _as_array(tees)
    return np.arctan2(delta[:, 1], delta[:, 0])


def direction_entropy(tees: Sequence[Point], greens: Sequence[Point],
                      bins: int = DIRECTION_BINS) -> float:
    """Entropie de Shannon des orientations tee→green, modulo 180°, normalisée.

    Histogramme en ``bins`` cases égales sur [0, π) (un trou et son inverse
    tombent dans la même case), entropie divisée par ``log(bins)`` : résultat
    dans [0, 1]. 0 = toutes les directions identiques (faisceau) ; 1 = cases
    également remplies, inaccessible avec moins de ``bins`` trous (9 trous :
    au plus log 9 / log 12 ≈ 0,884).
    """
    folded = _orientations(tees, greens) % math.pi
    if folded.size == 0:
        return 0.0
    index = np.minimum((folded / (math.pi / bins)).astype(int), bins - 1)
    counts = np.bincount(index, minlength=bins)
    p = counts[counts > 0] / folded.size
    entropy = float(-(p * np.log(p)).sum()) / math.log(bins)
    return max(entropy, 0.0)        # évite un -0.0 quand une seule case est remplie


def radial_alignment_R(tees: Sequence[Point], greens: Sequence[Point],
                       centre: Point) -> float:
    """Concentration circulaire de l'obliquité des trous par rapport au rayon.

    Pour chaque trou, α = angle(tee→green) − angle(centre→milieu du trou).
    Choix : angles DOUBLÉS, R = |moyenne de exp(2iα)|. Une pale est une
    droite : un trou et son inverse (green↔tee) ont la même obliquité et
    doublent vers la même valeur, ce qui rend R indépendant du sens de jeu
    (nines horaire et anti-horaire comparables, parcours entier poolable).
    Le doublement garde la chiralité : des obliquités +45° et −45° (moulinets
    miroirs) s'annulent. R ∈ [0, 1] ; proche de 1 = toutes les pales ont la
    même obliquité (moulinet ; R = 1 aussi pour des trous tous tangents ou
    tous radiaux).
    """
    tee_xy, green_xy = _as_array(tees), _as_array(greens)
    if len(tee_xy) == 0:
        return 0.0
    middle = (tee_xy + green_xy) / 2.0
    radial = np.arctan2(middle[:, 1] - centre[1], middle[:, 0] - centre[0])
    alpha = _orientations(tee_xy, green_xy) - radial
    return float(abs(np.exp(2j * alpha).mean()))


def nearest_segment(path: Sequence[Point], point: Point) -> int:
    """Index ``i`` du segment ``[path[i], path[i + 1]]`` le plus proche de ``point``.

    Distance euclidienne au segment (projection bornée aux extrémités) ; les
    segments de longueur nulle sont ignorés ; en cas d'égalité, le premier
    segment l'emporte. ``ValueError`` si le chemin n'a aucun segment non nul.
    """
    arr = _as_array(path)
    if len(arr) < 2:
        raise ValueError("chemin d'au moins deux points attendu")
    start, delta = arr[:-1], np.diff(arr, axis=0)
    length2 = (delta ** 2).sum(axis=1)
    valid = length2 > 0.0
    if not valid.any():
        raise ValueError("chemin sans segment de longueur non nulle")
    offset = np.asarray(point, dtype=float) - start
    t = np.clip((offset * delta).sum(axis=1) / np.where(valid, length2, 1.0), 0.0, 1.0)
    distance2 = ((offset - t[:, None] * delta) ** 2).sum(axis=1)
    return int(np.argmin(np.where(valid, distance2, np.inf)))


def path_tangent(path: Sequence[Point], point: Point) -> float:
    """Angle (radians, repère de la carte) du segment de ``path`` le plus
    proche de ``point``, orienté dans le sens de parcours du chemin."""
    arr = _as_array(path)
    i = nearest_segment(arr, point)
    dx, dy = arr[i + 1] - arr[i]
    return math.atan2(dy, dx)


def obliquity_sines(tees: Sequence[Point], greens: Sequence[Point],
                    path: Sequence[Point]) -> np.ndarray:
    """sin α par trou, α = angle(tee→green) − tangente du chemin au milieu
    de la corde (segment le plus proche, ``path_tangent``)."""
    tee_xy, green_xy = _as_array(tees), _as_array(greens)
    middle = (tee_xy + green_xy) / 2.0
    tangent = np.array([path_tangent(path, tuple(m)) for m in middle])
    return np.sin(_orientations(tee_xy, green_xy) - tangent)


def obliquity_signed(tees: Sequence[Point], greens: Sequence[Point],
                     path: Sequence[Point]) -> float:
    """Moyenne de sin α ∈ [-1, 1] (``obliquity_sines``) ; 0.0 sans trou.

    ≈ 0 : trous tangents au chemin, joués à rebours, ou obliquités qui se
    compensent ; valeur nettement d'un seul signe : pales de moulinet. Le
    signe dépend du sens du chemin et du repère (y vers le bas en image)."""
    sines = obliquity_sines(tees, greens, path)
    return float(sines.mean()) if sines.size else 0.0


def obliquity_abs(tees: Sequence[Point], greens: Sequence[Point],
                  path: Sequence[Point]) -> float:
    """Moyenne de |sin α| ∈ [0, 1] ; 0.0 sans trou.

    Un trou joué à rebours (α ≈ 180°) y compte pour 0, comme un trou
    tangent : ``forward_mean`` (moyenne de cos α) les distingue."""
    sines = obliquity_sines(tees, greens, path)
    return float(np.abs(sines).mean()) if sines.size else 0.0


def hole_cosines(tees: Sequence[Point], greens: Sequence[Point],
                 path: Sequence[Point]) -> np.ndarray:
    """cos α par trou (même α que ``obliquity_sines``)."""
    tee_xy, green_xy = _as_array(tees), _as_array(greens)
    middle = (tee_xy + green_xy) / 2.0
    tangent = np.array([path_tangent(path, tuple(m)) for m in middle])
    return np.cos(_orientations(tee_xy, green_xy) - tangent)


def forward_mean(tees: Sequence[Point], greens: Sequence[Point],
                 path: Sequence[Point]) -> float:
    """Moyenne de cos α ∈ [-1, 1] ; 0.0 sans trou. 1 = trous joués dans le
    sens du chemin ; un trou joué à rebours compte pour −1, un trou
    perpendiculaire pour 0."""
    cosines = hole_cosines(tees, greens, path)
    return float(cosines.mean()) if cosines.size else 0.0


def heading_turns(tees: Sequence[Point], greens: Sequence[Point]) -> float:
    """Σ|Δcap| / 2π : somme des virages absolus entre cordes tee→green
    successives (chaque Δ ramené dans [-π, π)), en tours. 0 sans virage ou
    avec moins de deux trous. Un nine qui fait un tour régulier vaut à peu
    près 1 (un peu moins : 8 virages pour 9 trous) ; une hélice ou un zigzag
    donne plus."""
    headings = _orientations(tees, greens)
    if headings.size < 2:
        return 0.0
    return float(np.abs(_wrap(np.diff(headings))).sum()) / (2.0 * math.pi)


def polygon_area(points: Sequence[Point]) -> float:
    """Aire (non signée) d'un polygone, formule du lacet ; le polygone est
    fermé implicitement (un dernier point égal au premier ne change rien)."""
    arr = _as_array(points)
    if len(arr) < 3:
        return 0.0
    x, y = arr[:, 0], arr[:, 1]
    return abs(float(np.dot(x, np.roll(y, -1)) - np.dot(y, np.roll(x, -1)))) / 2.0


def convex_hull(points: Sequence[Point]) -> np.ndarray:
    """Enveloppe convexe (chaîne monotone d'Andrew), sommets dans l'ordre ;
    points alignés retirés."""
    arr = np.unique(_as_array(points), axis=0)
    if len(arr) < 3:
        return arr

    def half(sequence) -> list:
        chain: list = []
        for p in sequence:
            while len(chain) >= 2:
                (ax, ay), (bx, by) = chain[-2], chain[-1]
                if (bx - ax) * (p[1] - ay) - (by - ay) * (p[0] - ax) > 0.0:
                    break
                chain.pop()
            chain.append(p)
        return chain

    lower, upper = half(arr), half(arr[::-1])
    return np.asarray(lower[:-1] + upper[:-1])


def hull_ratio(tees: Sequence[Point], greens: Sequence[Point],
               outer_ring: Sequence[Point]) -> float:
    """Aire de l'enveloppe convexe des tees et greens / aire du polygone
    ``outer_ring`` (anneau extérieur). Petite valeur : nine ramassé (le
    nine intérieur enroulé au centre). Pas borné à [0, 1] : le nine
    extérieur déborde de l'anneau extérieur et dépasse couramment 1.
    ``ValueError`` si l'anneau est d'aire nulle."""
    ring_area = polygon_area(outer_ring)
    if ring_area <= 0.0:
        raise ValueError("anneau extérieur d'aire nulle")
    return polygon_area(convex_hull([*tees, *greens])) / ring_area


def nominal_nine_length(pars: Sequence[int]) -> float:
    """Longueur nominale d'un nine : milieu de la plage de longueur de
    chaque par, plus ``LINK_NOMINAL`` par liaison (len(pars) + 1 liaisons,
    clubhouse compris). C'est le total que ``muirfield.green_targets``
    répartit le long du chemin cible."""
    return math.fsum((PAR_SPECS[par].length_min + PAR_SPECS[par].length_max) / 2.0
                     for par in pars) + (len(pars) + 1) * LINK_NOMINAL


def path_to_nine_length(path: Sequence[Point], pars: Sequence[int]) -> float:
    """Longueur du chemin cible (polyligne complète, liaisons au clubhouse
    comprises) / ``nominal_nine_length(pars)``. > 1 : les cibles sont plus
    espacées que la longueur naturelle du nine ; < 1 : le nine doit
    s'enrouler pour consommer sa longueur."""
    arr = _as_array(path)
    length = float(np.hypot(*np.diff(arr, axis=0).T).sum())
    return length / nominal_nine_length(pars)


def _xy(point) -> Point:
    return (point.x, point.y)


def _nine_metrics(holes: Sequence[ElasticHole], centre: Point,
                  path: Sequence[Point] | None = None, *, nine: bool = False,
                  ring_path: Sequence[Point] | None = None,
                  outer_ring: Sequence[Point] | None = None) -> dict[str, float | None]:
    tees = [_xy(h.tee) for h in holes]
    greens = [_xy(h.green) for h in holes]
    metrics = {
        "angular_step_cv": angular_step_cv(greens, centre),
        "direction_entropy": direction_entropy(tees, greens),
        "radial_alignment_R": radial_alignment_R(tees, greens, centre),
    }
    if path is not None:
        metrics["obliquity_signed"] = obliquity_signed(tees, greens, path)
        metrics["obliquity_abs"] = obliquity_abs(tees, greens, path)
    if not nine:
        return metrics
    metrics["heading_turns"] = heading_turns(tees, greens)
    if outer_ring is not None:
        metrics["hull_ratio"] = hull_ratio(tees, greens, outer_ring)
    if path is not None:
        metrics["forward_mean"] = forward_mean(tees, greens, path)
        metrics["path_to_nine_length"] = path_to_nine_length(path, [h.par for h in holes])
    if ring_path is not None:
        metrics["obliquity_signed_ring"] = obliquity_signed(tees, greens, ring_path)
        metrics["obliquity_abs_ring"] = obliquity_abs(tees, greens, ring_path)
    return metrics


def _rounded(metrics: dict[str, float | None], digits: int) -> dict[str, float | None]:
    return {k: (None if v is None else round(v, digits)) for k, v in metrics.items()}


def shape_metrics(layout: CourseLayout, digits: int = 4, *,
                  front_path: Sequence[Point] | None = None,
                  back_path: Sequence[Point] | None = None,
                  front_ring_path: Sequence[Point] | None = None,
                  back_ring_path: Sequence[Point] | None = None,
                  outer_ring: Sequence[Point] | None = None,
                  ) -> dict[str, dict[str, float | None]]:
    """Synthèse sérialisable ``{"front": {...}, "back": {...}, "course": {...}}``.

    Pour ``course`` : entropie et R sur les 18 trous ; CV sur les 16 pas
    orientés regroupés (8 par nine, chaque nine orienté selon son propre sens,
    sans le pas green 9 → green 10 qui change d'anneau).

    ``front_path`` / ``back_path`` (chemins des nines orientés dans le sens de
    jeu) ajoutent ``obliquity_signed`` et ``obliquity_abs`` au nine
    correspondant ; pas d'obliquité au niveau ``course``.

    Par nine seulement (round R2b M2) : ``heading_turns`` toujours ;
    ``forward_mean`` et ``path_to_nine_length`` avec le chemin ;
    ``obliquity_*_ring`` avec ``front_ring_path`` / ``back_ring_path``
    (chemins sur l'anneau) ; ``hull_ratio`` avec ``outer_ring``.
    """
    centre = (layout.width / 2.0, layout.height / 2.0)
    ordered = sorted(layout.holes, key=lambda h: h.order)
    front = [h for h in ordered if h.order <= 9]
    back = [h for h in ordered if h.order >= 10]
    course = _nine_metrics(ordered, centre)
    steps = np.concatenate([oriented_angular_steps([_xy(h.green) for h in nine], centre)
                            for nine in (front, back)])
    course["angular_step_cv"] = _cv(steps)
    return {
        "front": _rounded(_nine_metrics(front, centre, front_path, nine=True,
                                        ring_path=front_ring_path, outer_ring=outer_ring),
                          digits),
        "back": _rounded(_nine_metrics(back, centre, back_path, nine=True,
                                       ring_path=back_ring_path, outer_ring=outer_ring),
                         digits),
        "course": _rounded(course, digits),
    }
