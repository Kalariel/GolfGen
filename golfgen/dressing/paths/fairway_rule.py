"""Traitement du fairway par les chemins (``FairwayRule``).

Défaut (``FairwayRule()``, celui de ``place_paths`` et du pipeline) : la
correction, le fairway traité « comme l'eau » : traversé seulement si le
détour est vraiment long, et alors au plus court ; surcoût ``DEFAULT_COST``
(2) par bloc, validé sur planche.
Trois volets, chacun activable seul :

a) ``full_width`` : surcoût ``cost`` par bloc sur le fairway DILATÉ de la
   demi-largeur du chemin (cases dont le centre est à moins de ``w/2`` d'une
   case de fairway, distance centre → carré plein, comme les marges des
   obstacles sans ``CELL_PAD``) : un axe qui y passe a une case de son trait
   sur le fairway ;
b) ``dry_straight`` : la ligne droite n'est acceptée que si son trait
   (``band_cells``) ne touche aucune case de fairway — l'analogue de la
   règle de l'eau (ligne droite « sèche ») ; sinon l'A* décide (et peut
   retrouver la droite, ``slide``) ;
c) ``no_increase`` : un raccourci de la tension n'a pas plus de cases de
   fairway sous son trait que le tronçon qu'il remplace ; un bout reprojeté
   (``reproject_ends``) n'en ajoute pas au segment qu'il remplace (sinon
   l'ancien bout est gardé) ; la tension est REFUSÉE (brut gardé) si le
   trait tendu a plus de cases de fairway que le brut ; un virage est refusé
   s'il ajoute des cases de fairway au trait — le miroir de « refusée si
   elle ajoute de l'eau ». Compte exact : cases de fairway sous
   ``band_cells`` (``route.fairway_cells``).

Non couverts (mesurés, laissés tels quels) : les emprunts au tronc (un tracé
déjà posé n'ajoute aucune case à l'union), les réparations de la conversion
en blocs et de l'union (quelques cases, nécessaires à la 4-connexité).
"""

from __future__ import annotations

from dataclasses import dataclass

DEFAULT_COST = 2.0       # surcoût par bloc de la correction par défaut


@dataclass(frozen=True)
class FairwayRule:
    """Règle du fairway (voir le docstring du module) ; ``FairwayRule()`` :
    la correction, surcoût ``DEFAULT_COST``."""
    cost: float = DEFAULT_COST        # surcoût par bloc (A*, plafonds de la tension)
    full_width: bool = True           # a) fairway dilaté de la demi-largeur
    dry_straight: bool = True         # b) ligne droite seulement hors du fairway
    no_increase: bool = True          # c) tension et virages sans fairway de plus

    def __post_init__(self) -> None:
        # surcoût négatif : l'heuristique octile de l'A* ne serait plus admissible
        if not self.cost >= 0:
            raise ValueError(f"FairwayRule.cost doit être >= 0 (reçu {self.cost!r})")

    @classmethod
    def corrected(cls, cost: float) -> "FairwayRule":
        """Les trois volets de la correction, surcoût ``cost`` par bloc."""
        return cls(cost=cost, full_width=True, dry_straight=True, no_increase=True)
