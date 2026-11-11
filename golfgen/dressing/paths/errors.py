"""Erreur du tracé des chemins."""

from __future__ import annotations


class PathError(Exception):
    """Échec du tracé des chemins qui dépend de la seed ; l'appelant peut
    proposer une autre seed ou désactiver les chemins. Levée par
    ``route_link`` quand une liaison n'a aucune route (message : liaison,
    extrémités, seed) et par ``place_paths`` quand une liaison est coupée (tracé coupé en morceaux
    ou surface non touchée) ou l'union garde un contact par un coin ; même
    message : par construction, aucune liaison n'est impossible
    (le routeur pose des liaisons de 12 à 45 blocs sans couper d'autre
    fairway, l'habillage garde un accès de 2 blocs au green, les ponts sont
    permis), c'est donc le signe d'un bogue, rendu explicite au lieu du
    statut ``failed`` silencieux de l'étude. Toute autre exception levée
    pendant le tracé (``ValueError`` d'un invariant, d'un paramètre…) est un
    bogue et doit remonter. Pas une ``ValueError`` : un ``except
    ValueError`` ne la confond pas avec un bogue d'invariant."""
