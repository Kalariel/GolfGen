"""Chemins (habillage, lot 4) : configuration validée de l'étude, portée en
production en rounds.

Configuration portée, et elle seule : tronc commun activé ; parvis du
clubhouse activé, SANS portes (extrémité glissante sur tout son bord : les
sorties réparties du r5 sont abandonnées) ; sans lissage, sans serpentins,
sans variante A (ligne droite brute) ; un virage marqué sur les tronçons
droits d'au moins 35 blocs, deux en S au-delà de 60. Styles ``links``
(largeur 2) et ``parkland`` (largeur 3).

API : ``place_paths(data) -> CoursePaths`` (``course``) : couche à plat
des chemins d'un JSON 3.2 (cases ``[x, z]`` de l'union, cases de pont,
parvis, ancrages des virages), détail par liaison dans ``debug``.

Rounds : R1 scène, parvis et A* ; R2 la route ; R3 blocs, virages et
assemblage ; R4 réparation des contacts par un coin de l'union, export JSON
3.3 (``golfgen.exporter.with_paths``, clé ``paths``) et étape 5 du pipeline.

- ``geometry`` : polygones, distances, échantillonnage, cases traversées ;
- ``scene`` : ``Scene``, obstacles, extrémités des liaisons
  (``LinkEnds``), ``scene_from_json`` (JSON 3.2, parvis posé),
  ``obstacle_mask`` ;
- ``plaza`` : parvis du clubhouse (pose, décalage, réduction) ;
- ``fairway_rule`` : ``FairwayRule``, traitement du fairway (défaut : la
  correction, fairway « comme l'eau », surcoût 2 sur toute la largeur, ligne
  droite hors fairway, tension et virages sans fairway de plus), passé à
  ``place_paths(data, fairway_rule=...)`` ;
- ``bridge_rule`` : ``BridgeRule``, règle des ponts (défaut : règle du
  gain, pont si la marche gagnée atteint 25 %, surcoût bas, virages doux ;
  ``BridgeRule.gained(G)`` : autre gain ; forme ``straight`` | ``bends`` ;
  corrections : un seul morceau par liaison, eau du pont reliée à la
  traversée, bouts sans surface non prolongés, largeur rendue côté sec, pas
  de crochet autour d'un coin, liaison coupée en ``PathError``), passé à
  ``place_paths(data, bridge_rule=...)`` ;
- ``bridge_shape`` : forme ``bends`` (``bend_bridge`` : virages doux comptés
  sur toute la liaison, 3, 2 puis 1, sommets sur l'eau, sans ancrage, sans
  tirage) ;
- ``grid`` : ``Grid`` d'une liaison (``build_grid`` : dilatation,
  relâchement aux extrémités, sources et cibles sur le bord des surfaces),
  ``Network`` (axe et anneau des chemins déjà posés), A* multi-source et
  multi-cible (``astar``, ``shortest_path``), heuristique octile réduite de
  ``TRUNK_FACTOR`` (×0,5) quand un tronc est posé ;
- ``route`` : ``route_link`` (ligne droite libre, recherche A* sèche dans
  les fenêtres 15 → 30 → 60, tension refusée si elle ajoute de l'eau,
  reprojection des bouts, pont selon la règle du gain, ``water_fringe``, emprunts exacts au tronc commun ; ``Route``),
  ``route_network`` (liaisons posées dans l'ordre de ``routing.links``) ;
  une liaison sans chemin lève ``PathError`` (un bogue) ;
- ``blocks`` : conversion en blocs (``band_cells`` : trait épais à compte
  fixe ``round(w / cos θ)`` par colonne de l'axe dominant ; ``path_blocks``
  : prolongement des bouts, rognage sur les obstacles, réparations ;
  ``bridge_water`` : eau permise sur les ``bridge_spans`` prolongés de
  ``BRIDGE_BANK`` et sous tout le trait (l'eau reliée à la traversée) ;
  ``water_cuts`` : contrôle du pincement ; ``link_blocks``) ;
- ``bends`` : virages marqués (``bend_route`` : un virage sur le plus long
  tronçon propre ≥ 35 blocs, deux en S au-delà de 60, ancrage côté
  intérieur ; ``anchor_check`` : contrôle sur les cases finales), flux
  ``golfgen.dressing.rng.bend_rng`` ;
- ``course`` : ``place_paths``, ``repair_union_corners``, ``CoursePaths`` (couche exportée),
  ``LinkPaths`` et ``PathsDebug`` (détail, non exporté) ;
- ``errors`` : ``PathError``.

Chaque fonction est le portage de son modèle de l'étude ; la parité a été
vérifiée au portage, puis les tests de parité et l'étude ont été retirés
(2026-11-08) : les tests figent désormais le comportement de production
(``tests/test_dressing_paths_frozen.py``). Ajoutés depuis l'étude : la
réparation des contacts par un coin de l'union (``repair_union_corners``),
les règles ``FairwayRule`` et ``BridgeRule``.
"""

from golfgen.dressing.paths.bends import Bend, BendReport, bend_route
from golfgen.dressing.paths.blocks import Blocks, band_cells, link_blocks, path_blocks
from golfgen.dressing.paths.bridge_rule import BridgeRule
from golfgen.dressing.paths.course import (CoursePaths, LinkPaths, PathsDebug, PlazaLayer,
                                           place_paths)
from golfgen.dressing.paths.errors import PathError
from golfgen.dressing.paths.fairway_rule import FairwayRule
from golfgen.dressing.paths.grid import Grid, Network, astar, build_grid, shortest_path
from golfgen.dressing.paths.plaza import Plaza, place_plaza
from golfgen.dressing.paths.route import Route, route_link, route_network
from golfgen.dressing.paths.scene import LinkEnds, Obstacle, Scene, obstacle_mask, scene_from_json

__all__ = ["Bend", "BendReport", "Blocks", "BridgeRule", "CoursePaths", "FairwayRule", "Grid",
           "LinkEnds", "LinkPaths",
           "Network", "Obstacle", "PathError", "PathsDebug", "Plaza", "PlazaLayer", "Route",
           "Scene", "astar", "band_cells", "bend_route", "build_grid", "link_blocks",
           "obstacle_mask", "path_blocks", "place_paths", "place_plaza", "route_link",
           "route_network", "scene_from_json", "shortest_path"]
