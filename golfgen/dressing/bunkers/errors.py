"""Erreur attendue de la pose des bunkers."""

from __future__ import annotations


class BunkerError(Exception):
    """Échec ATTENDU de la pose des bunkers : impossibilité géométrique qui
    dépend de la seed (enveloppe convexe dégénérée, empreinte sans sable,
    trou sans fairway, tirage refusé…) ; l'appelant peut proposer une autre
    seed ou ``--no-bunkers``. Toute autre exception levée pendant la pose
    (``ValueError`` d'un invariant, d'un paramètre…) est un bogue et doit
    remonter. Pas une ``ValueError`` : un ``except ValueError`` ne la
    confond pas avec un bogue."""
