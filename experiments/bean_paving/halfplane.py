"""Biais souple de demi-plan (score uniquement, jamais une règle dure).

Contexte : EXPERIMENT_18_HALFPLANE.md. Une droite passant par le clubhouse à
l'angle ``theta_deg`` partage la carte en deux. Le camp "back" est celui vers
lequel pointe le vecteur unitaire ``unit_vector(theta_deg)`` ; le camp
"front" est l'autre. Le front est pénalisé (dans le score du beam, jamais
dans ``geometry.validate``) quand un trou empiète dans le camp back ; le back
reste libre (poids 0 côté back). Pour éviter l'effet "deux nines collées"
observé avec un partage dur, aucune pénalité ne s'applique dans une bande de
transition de part et d'autre de la droite : elle grandit ensuite de façon
lisse (quadratique) avec la profondeur d'intrusion.

Choix géométrique : la profondeur d'intrusion est mesurée sur l'EMPREINTE
complète (rough, tous les sommets), pas sur un centroïde + rayon. Un
centroïde+extension sous-estime l'intrusion d'un haricot dont l'axe est
coudé ou dont la largeur est asymétrique par rapport à son centre ; prendre
le maximum de projection sur les sommets de l'empreinte capture exactement
la pointe qui dépasse dans le camp adverse, ce qui est précisément ce que
l'utilisateur veut éviter de voir sur le rendu SVG.
"""

from __future__ import annotations

import math
from typing import TYPE_CHECKING

from experiments.bean_paving.bean_bank import Point

if TYPE_CHECKING:
    from experiments.bean_paving.geometry import PlacedBean


def unit_vector(theta_deg: float) -> Point:
    rad = math.radians(theta_deg)
    return (math.cos(rad), math.sin(rad))


def projection(point: Point, clubhouse: Point, theta_deg: float) -> float:
    """Coordonnée signée de ``point`` le long de ``unit_vector(theta_deg)``,
    origine au clubhouse. Positif = camp "back"."""
    ux, uy = unit_vector(theta_deg)
    return (point[0] - clubhouse[0]) * ux + (point[1] - clubhouse[1]) * uy


def centroid(bean: "PlacedBean") -> Point:
    return ((bean.tee[0] + bean.green[0]) / 2.0, (bean.tee[1] + bean.green[1]) / 2.0)


def intrusion_depth(points: tuple[Point, ...], clubhouse: Point, theta_deg: float,
                     band: float) -> float:
    """Profondeur d'intrusion dans le camp back au-delà de la bande de
    transition (``band`` blocs, centrée sur la droite) : 0.0 à l'intérieur
    de la bande, croissant ensuite avec la projection maximale des points."""
    half_band = band / 2.0
    max_s = max(projection(p, clubhouse, theta_deg) for p in points)
    return max(0.0, max_s - half_band)


def front_penalty(bean: "PlacedBean", clubhouse: Point, theta_deg: float, band: float,
                   weight: float) -> float:
    """Pénalité de score pour un trou côté front : 0.0 si ``weight`` est nul
    (comportement par défaut, inchangé) ou si le trou reste dans la bande ou
    le camp front ; croît ensuite de façon lisse (quadratique) avec la
    profondeur d'intrusion dans le camp back."""
    if weight <= 0.0:
        return 0.0
    depth = intrusion_depth(bean.footprint, clubhouse, theta_deg, band)
    return weight * depth * depth


def wrong_side_count(front: tuple["PlacedBean", ...], back: tuple["PlacedBean", ...],
                      clubhouse: Point, theta_deg: float, band: float) -> int:
    """Diagnostic (sans effet sur la recherche) : nombre de trous dont le
    centroïde (milieu tee-green) est au-delà de la bande, du côté du camp de
    l'AUTRE nine — un front trop avancé dans le camp back, ou l'inverse."""
    half_band = band / 2.0
    count = 0
    for bean in front:
        if projection(centroid(bean), clubhouse, theta_deg) > half_band:
            count += 1
    for bean in back:
        if projection(centroid(bean), clubhouse, theta_deg) < -half_band:
            count += 1
    return count


def interleave_pairs(front: tuple["PlacedBean", ...], back: tuple["PlacedBean", ...]) -> int:
    """Diagnostic (sans effet sur la recherche) : nombre de paires
    front/back dont les roughs se touchent ou se chevauchent — proxy de
    l'effet visuel "deux nines collées" (plus ce nombre est grand par
    rapport au nombre de trous posés, plus les deux nines sont imbriqués
    plutôt que séparés par la droite)."""
    from experiments.bean_paving.geometry import polygons_intersect
    return sum(1 for f in front for b in back if polygons_intersect(f.footprint, b.footprint))
