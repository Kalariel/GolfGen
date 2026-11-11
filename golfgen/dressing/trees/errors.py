"""Erreur de la pose des arbres : bogue ou invariant cassé."""

from __future__ import annotations


class TreeError(Exception):
    """Bogue ou invariant cassé dans la pose des arbres, et rien d'autre : JSON
    sans ``paths.cells`` ou sans ``bunkers.items`` (erreur de l'appelant), zone
    de retombée divergente du profil du fairway. Aucun échec attendu ne la
    lève : un trou sauté ou un ancrage partiel est compté, jamais signalé par
    une exception. Classe dédiée, pas une ``ValueError`` : un ``except
    ValueError`` ne l'avale pas."""
