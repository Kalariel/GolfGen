"""Contexte des contrôles de bunkers d'un parcours, en mémoire (round R2).

``BunkerContext`` lit les données de production, sans instantané ni taille
ou style figés :

- ``of(layout, dressing)`` : tracé et habillage en mémoire (``CourseLayout``,
  ``CourseDressing``) ;
- ``holes`` : trous du tracé par numéro ;
- ``dressing`` (``dress_course``, paires comprises) ;
- ``style`` = ``dressing.style`` ;
- ``limits`` = ``(largeur, hauteur)`` en blocs entiers (``whole_blocks`` : pas
  de troncature) ;
- ``targets`` (``legality.Target``) ;
- ``polygons``, ``audit()`` (``PoseAudit`` mis en cache par trou) ;
- ``water`` : ``WaterMask`` ou ``None``.
"""

from __future__ import annotations

from golfgen.dressing.bunkers.legality import PoseAudit, course_targets, prepared


def whole_blocks(value, name: str) -> int:
    """Côté de carte en blocs entiers (``CourseLayout`` le porte en flottant,
    ``400.0``) ; ``ValueError`` plutôt qu'une troncature silencieuse."""
    error = ValueError(f"{name} de carte : nombre entier de blocs attendu, pas {value!r}")
    if isinstance(value, (bool, str, bytes)):
        raise error
    try:
        number = float(value)
    except (TypeError, ValueError):
        raise error from None
    if not number.is_integer() or number <= 0:
        raise error
    return int(number)


class BunkerContext:
    """Cibles préparées et audits par trou d'un parcours habillé."""

    def __init__(self, holes, dressing, width, height, *, water=None):
        self.holes = {hole.order: hole for hole in holes}
        self.dressing = dressing
        self.style = dressing.style
        self.limits = (whole_blocks(width, "largeur"), whole_blocks(height, "hauteur"))
        if water is not None:
            water.require_size(width, height)
        self.water = water
        self.targets = course_targets(dressing)
        self.polygons = [prepared(t.outline) for t in self.targets]
        self._audits: dict[int, PoseAudit] = {}

    @classmethod
    def of(cls, layout, dressing, *, water=None) -> BunkerContext:
        """Contexte d'un ``CourseLayout`` (trous, taille de carte) et de son habillage."""
        return cls(layout.holes, dressing, layout.width, layout.height, water=water)

    def audit(self, order: int) -> PoseAudit:
        if order not in self._audits:
            self._audits[order] = PoseAudit(self.targets, order, self.limits, polygons=self.polygons,
                                            water=self.water)
        return self._audits[order]
