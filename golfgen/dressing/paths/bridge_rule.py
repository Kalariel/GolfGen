"""Règle des ponts des chemins (``BridgeRule``).

Déclencheur (``route.route_link``) :

RÈGLE DU GAIN (défaut : ``BridgeRule()``, ``gain`` à ``DEFAULT_GAIN``, 25 %,
validé sur planche ; autre seuil : ``BridgeRule.gained(G)``) : UNE règle
uniforme, sans seuil sur la distance directe. Pour toute liaison qui n'est
pas une ligne droite libre, la route SÈCHE (eau interdite) et la route
MOUILLÉE (eau traversable au surcoût FIXE et BAS ``GAIN_COST``) sont
cherchées ; la mouillée est prise si et seulement si elle fait gagner au
moins ``G`` de marche :

    (longueur sèche − longueur mouillée) / longueur sèche ≥ G

longueurs : ``polyline_length`` des tracés de ``search`` (après emprunts
au tronc et TENSION, avant les virages doux du pont et les virages marqués
de ``bends``). Sans route sèche, la mouillée est prise. Une route mouillée
qui passe sur l'eau effective est un pont, sinon un gué (``water_fringe``).
La recherche mouillée n'est pas lancée si la fenêtre de la route sèche n'a
aucune case d'eau (dilatée) : elle rendrait la même route (gain nul).

``GAIN_COST`` (0,25) : avec un surcoût bas, la route mouillée TRAVERSE au
lieu de longer la rive par un gué (s86624 links, green 15 → départ 16 :
au surcoût 0,5 et au-delà, gué de 44,9 blocs le long de la rive ; à 0,25 et
0,1, la traversée droite de 37,7 blocs, celle de la planche des formes).

Forme ``bends`` (« virages doux ») : virages comptés sur TOUTE la liaison
(``bridge_shape``) : 3, sinon 2, sinon 1, sommets sur l'eau effective, sans
ancrage, côtés alternés, placement qui met le plus de tracé sur l'eau.

Corrections :

- une liaison est exactement un morceau 4-connexe : seul reste le plus grand
  des morceaux qui portent le tracé (``blocks.path_blocks``,
  ``single_piece``) ; un tracé coupé (``Blocks.severed``) ou un bout de
  surface non touché (``blocks.contacts_missing``) lève ``PathError``
  (``course.place_paths``) : une liaison coupée n'est jamais exportée ;
- eau du pont sous tout le trait limitée à l'eau reliée à
  la traversée (``bridge_spans``) dans le trait : une autre mare frôlée par
  le bord du trait n'est pas posée en cases d'eau (``blocks.bridge_water``) ;
- ce trait n'est prolongé qu'aux bouts qui ont une surface (pas le
  clubhouse ponctuel) ;
- toute case du trait découpée par l'eau interdite en chemin (gué pincé,
  mare frôlée) est rendue de l'autre côté du trait si la case y est libre et
  hors fairway : largeur gardée, aucune case d'eau hors pont (sur un pont,
  seulement l'eau que ``bridge_water`` lui permet ; ``blocks.path_blocks``,
  ``compensate``) ;
- une case due au seul prolongement d'un bout, passée au-delà de ce bout sans
  mener à sa surface, est retirée (pas de crochet autour du coin d'une boîte
  tournée ; ``blocks.past_the_surface``).
"""

from __future__ import annotations

from dataclasses import dataclass

GAIN_COST = 0.25         # règle du gain : surcoût fixe et bas sur l'eau
DEFAULT_GAIN = 0.25      # règle du gain : gain de marche minimal par défaut (fraction)
BRIDGE_SHAPES = ("straight", "bends")


@dataclass(frozen=True)
class BridgeRule:
    """Règle des ponts (voir le docstring du module) ; ``BridgeRule()`` :
    règle du gain à 25 %, surcoût ``GAIN_COST``, virages doux ;
    ``BridgeRule.gained(G)`` : la même à un autre gain."""
    cost: float = GAIN_COST          # surcoût par bloc sur l'eau (A*, plafonds de la tension)
    shape: str = "bends"             # ``straight`` | ``bends``
    gain: float = DEFAULT_GAIN        # gain de marche minimal (fraction)

    def __post_init__(self) -> None:
        # surcoût négatif : l'heuristique octile de l'A* ne serait plus admissible
        if not self.cost >= 0:
            raise ValueError(f"BridgeRule.cost doit être >= 0 (reçu {self.cost!r})")
        if self.shape not in BRIDGE_SHAPES:
            raise ValueError(f"BridgeRule.shape : {BRIDGE_SHAPES} (reçu {self.shape!r})")
        if not 0.0 < self.gain < 1.0:
            raise ValueError(f"BridgeRule.gain doit être dans ]0, 1[ (reçu {self.gain!r})")

    @classmethod
    def gained(cls, gain: float, shape: str = "bends") -> "BridgeRule":
        """Règle du gain ``gain`` (fraction), surcoût ``GAIN_COST``, virages
        doux."""
        return cls(shape=shape, gain=gain)
