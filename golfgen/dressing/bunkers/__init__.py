"""Bunkers (habillage) : chemin validé de l'étude des bunkers
(greens d'abord, fairway ensuite), porté en production en rounds.

Round R1 : géométrie pure des empreintes, sans pose ni contrôle.

- ``raster`` : repère local, cases de sable, topologie, distances de cases,
  enveloppe convexe ;
- ``beans`` : haricots (deux disques fondus), tirage, orientation et miroir ;
- ``pots`` : motifs de pots, tailles mêlées, géométrie des grappes.

Round R2 : légalité d'une pose, sans recherche ni sélection.

- ``legality`` : cibles du parcours, contrôles de pose (carte, marges
  green/départs au contour et aux carrés, voisins, contacts, fairway des
  pots d'appel), sonde au site, pose de flanc ; ``water`` refuse le sable
  sur l'eau (``None`` : aucune eau connue) ;
- ``context`` : adaptateur en mémoire du contexte de l'étude (tracé,
  habillage, taille de carte, eau ; aucune taille ni style figés) ;
- ``sites`` : sites candidats, site retenu, position au coude ;
- ``access`` : passage de 2 blocs vers le green, pots de green exemptés,
  domaine du trou, coupables d'un blocage ;
- ``distance`` : site des bunkers de green, règle des 18 b.

Round R3 : sélection et construction des bunkers initiaux de chaque trou.

- ``selection`` : choix seedés par trou avant toute pose (trous vides,
  famille, sites ; poids du prototype regroupés) ; trous vides : 1 chance
  sur 50 par trou (flux dédié) ; famille remplacée (ex-organique de
  green) servie par des haricots de green sur flux dédiés ;
- ``pot_groups`` : pots de green (grappe tirée, recentrée, raster) et
  pots d'appel (duo, trio compact), relevé par rôle ;
- ``placements`` : haricots de green sur trois sites, haricot de retombée
  (droit ou coude extérieur) ;
- ``cases`` : cas par trou (``spec``, ``hole``, ``hd``, ``bunkers``,
  ``records``, ``missing``, ``pairs``), ``course_cases`` = sélection puis
  construction ; toute taille de carte, links comme parkland.

Round R4 : phase green (chemin validé B2, greens d'abord).

- ``green_phase`` : bunkers de fairway retirés (``stripped``), puis
  haricots « devant » re-posés en flanc d'entrée (côté seedé ou opposé au
  haricot côté, balayage θ, glissement arrêté par contact, ``FlankAudit``,
  accès de 2 blocs, option a′) ; ``(rows,
  after)`` pour la phase fairway ; ``offsets``/``translated`` (recul
  rigide le long de l'axe) prêts pour elle.

Round R5 : phase fairway (chemin validé B2, fairway ensuite).

- ``fairway_phase`` : unités de fairway (grappe des pots d'appel, haricot
  de retombée) posées sur l'état des greens, contrôlées une fois contre
  tout le déjà posé (contrôles existants, contact, règle des 18 b, accès
  de 2 blocs, pots de green exemptés) ; recul rigide le long de l'axe
  jusqu'à 12 b, haricot de dogleg extérieur en place seulement ;
- ``course`` : point d'entrée public ``place_bunkers(layout, dressing,
  seed, *, water=None)`` (contexte, cas, phase green, phase fairway) ->
  ``CourseBunkers`` figé (``PlacedBunker`` : id, trou,
  famille, rôle, cases ``(x, z)``, statut, sable légal seulement ;
  ``UnplacedBunker`` : non posés, poses signalées et leurs raisons comprises).

Chaque fonction est le portage de son modèle de l'étude (mêmes flux
aléatoires ``[seed, RNG_LABEL, order, STREAM, ...]``) ; la parité a été
vérifiée au portage, puis les tests de parité et l'étude ont été retirés
(2026-11-02) : les tests figent désormais le comportement de production.

Round R6 : branchement dans le pipeline (``pipeline.py``, désactivable par
``--no-bunkers``) : ``place_bunkers_json(data, dressing)`` relit le JSON du
routage (tracé, seed, eau) comme ``dress_course_json`` ; export dans la clé
``bunkers`` du JSON 3.2 (``golfgen.exporter.with_bunkers``).

``BunkerError`` (``errors``) : échec attendu, dépendant de la seed
(impossibilité géométrique) ; le pipeline propose une autre seed ou
``--no-bunkers``. Toute autre exception est un bogue et remonte.
"""

from golfgen.dressing.bunkers.course import (CourseBunkers, PlacedBunker, UnplacedBunker, place_bunkers,
                                             place_bunkers_json)
from golfgen.dressing.bunkers.errors import BunkerError

__all__ = ["BunkerError", "CourseBunkers", "PlacedBunker", "UnplacedBunker", "place_bunkers",
           "place_bunkers_json"]
