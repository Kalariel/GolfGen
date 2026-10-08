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
"""

from __future__ import annotations

import math
from typing import Sequence

import numpy as np

from experiments.elastic_routing.model import CourseLayout, ElasticHole


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
    """Moyenne de |sin α| ∈ [0, 1] ; 0.0 sans trou."""
    sines = obliquity_sines(tees, greens, path)
    return float(np.abs(sines).mean()) if sines.size else 0.0


def _xy(point) -> Point:
    return (point.x, point.y)


def _nine_metrics(holes: Sequence[ElasticHole], centre: Point,
                  path: Sequence[Point] | None = None) -> dict[str, float | None]:
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
    return metrics


def _rounded(metrics: dict[str, float | None], digits: int) -> dict[str, float | None]:
    return {k: (None if v is None else round(v, digits)) for k, v in metrics.items()}


def shape_metrics(layout: CourseLayout, digits: int = 4, *,
                  front_path: Sequence[Point] | None = None,
                  back_path: Sequence[Point] | None = None
                  ) -> dict[str, dict[str, float | None]]:
    """Synthèse sérialisable ``{"front": {...}, "back": {...}, "course": {...}}``.

    Pour ``course`` : entropie et R sur les 18 trous ; CV sur les 16 pas
    orientés regroupés (8 par nine, chaque nine orienté selon son propre sens,
    sans le pas green 9 → green 10 qui change d'anneau).

    ``front_path`` / ``back_path`` (chemins des nines orientés dans le sens de
    jeu) ajoutent ``obliquity_signed`` et ``obliquity_abs`` au nine
    correspondant ; pas d'obliquité au niveau ``course``.
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
        "front": _rounded(_nine_metrics(front, centre, front_path), digits),
        "back": _rounded(_nine_metrics(back, centre, back_path), digits),
        "course": _rounded(course, digits),
    }
