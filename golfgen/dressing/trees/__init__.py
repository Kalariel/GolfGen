"""Arbres (habillage, lot 5) : configuration validée des études, portée en
production en rounds.

Round R1 : base du paquet, sans placement.

- ``errors`` : ``TreeError`` ;
- ``geometry`` : axes, masques de polygones, corridors, couronnes
  précalculées par rayon (``CROWN_DISCS``), interdits du parcours
  (``ForbiddenMasks``, ``forbidden_masks``).

Round R2 : couche stratégique (retombée puis green).

- ``strategic`` : ``place_strategic -> StrategicTrees`` (couches, arbres
  ``StrategicTree``, sauts par motif).

Round R3 : ancrages, lisière, remplissage, assemblage.

- ``fill`` : ``greedy`` (la seule pose), rayons, lisière, bruit à instance
  locale, zone de remplissage ;
- ``anchors`` : bosquets d'ancrage (``AnchorGrove``) ;
- ``course`` : ``place_trees(data, margin=5.0, scene=None) -> CourseTrees``
  (arbres ``TreeItem``, compteurs par couche et motif).

Flux aléatoires : ``golfgen.dressing.rng.tree_rng``.

Chaque fonction est le portage de son modèle de l'étude du lot 5, à
l'identique (étude retirée au R7, dans l'historique git ; sortie figée par
``tests/test_dressing_trees_frozen.py``, invariants vérifiés par l'oracle
``tests/test_dressing_trees_oracle.py``) ; la production n'importe jamais
``tools``.
"""

from golfgen.dressing.trees.anchors import AnchorGrove
from golfgen.dressing.trees.course import CourseTrees, TreeItem, place_trees, validate_margin
from golfgen.dressing.trees.errors import TreeError
from golfgen.dressing.trees.geometry import (APRON, CORE_MARGIN, CORRIDOR_MARGIN, CROWN_DISCS,
                                             CROWN_RADII, CROWN_RADIUS, ForbiddenMasks, Tree,
                                             aprons_mask, axis_of, corridor_polygon,
                                             corridors_mask, crown_cells, crown_fits, crown_mask,
                                             crown_on_map, dilate_disc, forbidden_masks, kind_mask,
                                             other_corridors, paths_mask, polygon_mask)
from golfgen.dressing.trees.strategic import (StrategicLayer, StrategicTree, StrategicTrees,
                                              place_strategic)

__all__ = ["APRON", "AnchorGrove", "CORE_MARGIN", "CORRIDOR_MARGIN", "CROWN_DISCS",
           "CROWN_RADII", "CROWN_RADIUS", "CourseTrees", "ForbiddenMasks", "StrategicLayer",
           "StrategicTree", "StrategicTrees", "Tree", "TreeError", "TreeItem", "aprons_mask",
           "axis_of", "corridor_polygon", "corridors_mask", "crown_cells", "crown_fits",
           "crown_mask", "crown_on_map", "dilate_disc", "forbidden_masks", "kind_mask",
           "other_corridors", "paths_mask", "place_strategic", "place_trees", "polygon_mask",
           "validate_margin"]
