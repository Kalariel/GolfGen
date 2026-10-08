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
- ``direction_entropy`` : entropie normalisée des orientations des trous.
  Basse → trous en faisceaux parallèles.
- ``radial_alignment_R`` : concentration de l'obliquité des trous par rapport
  au rayon. Haute → pales de même obliquité (moulinet).
"""

from __future__ import annotations

import math
from typing import Sequence

import numpy as np

from experiments.elastic_routing.model import CourseLayout, ElasticHole


Point = tuple[float, float]

DIRECTION_BINS = 12                 # cases de 15° sur [0°, 180°)
CV_MEAN_EPSILON = 1e-9              # pas moyen nul : CV non défini


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
    mean = float(steps.mean())
    if abs(mean) < CV_MEAN_EPSILON:
        return None
    return float(steps.std()) / abs(mean)


def angular_step_cv(greens: Sequence[Point], centre: Point) -> float | None:
    """Coefficient de variation (écart-type / moyenne) des pas angulaires.

    Pas orientés de ``oriented_angular_steps`` ; écart-type de population.
    ``None`` si moins de deux greens ou si le pas moyen est nul (boucle qui
    revient sur elle-même). Une valeur proche de 0 signale une hélice : les
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


def _xy(point) -> Point:
    return (point.x, point.y)


def _nine_metrics(holes: Sequence[ElasticHole], centre: Point) -> dict[str, float | None]:
    tees = [_xy(h.tee) for h in holes]
    greens = [_xy(h.green) for h in holes]
    return {
        "angular_step_cv": angular_step_cv(greens, centre),
        "direction_entropy": direction_entropy(tees, greens),
        "radial_alignment_R": radial_alignment_R(tees, greens, centre),
    }


def _rounded(metrics: dict[str, float | None], digits: int) -> dict[str, float | None]:
    return {k: (None if v is None else round(v, digits)) for k, v in metrics.items()}


def shape_metrics(layout: CourseLayout, digits: int = 4) -> dict[str, dict[str, float | None]]:
    """Synthèse sérialisable ``{"front": {...}, "back": {...}, "course": {...}}``.

    Pour ``course`` : entropie et R sur les 18 trous ; CV sur les 16 pas
    orientés regroupés (8 par nine, chaque nine orienté selon son propre sens,
    sans le pas green 9 → green 10 qui change d'anneau).
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
        "front": _rounded(_nine_metrics(front, centre), digits),
        "back": _rounded(_nine_metrics(back, centre), digits),
        "course": _rounded(course, digits),
    }
