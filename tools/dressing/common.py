"""Aides communes aux outils de ``tools/dressing`` : lecture des seeds en
argument et police des montages ``magick``."""

from __future__ import annotations

MONTAGE_FONT = "DejaVu-Sans"


def parse_seeds(text: str) -> tuple[int, ...]:
    """Seeds ``"1-30"`` (plage incluse) ou ``"3,7"`` (liste). Lève
    ``ValueError`` avec un message explicite si le texte est vide, mal formé
    ou si la liste a un élément vide (``"3,,7"``)."""
    text = text.strip()
    if not text:
        raise ValueError("liste de seeds vide (attendu : 1-30 ou 3,7)")
    if "-" not in text and not all(v.strip() for v in text.split(",")):
        raise ValueError(f"élément vide dans {text!r} (attendu : 1-30 ou 3,7)")
    try:
        if "-" in text:
            low, high = (int(v) for v in text.split("-"))
            seeds = tuple(range(low, high + 1))
        else:
            seeds = tuple(int(v) for v in text.split(","))
    except ValueError:
        raise ValueError(f"seeds mal formées : {text!r} (attendu : 1-30 ou 3,7)") from None
    if not seeds:
        raise ValueError(f"aucune seed dans {text!r} (attendu : 1-30 ou 3,7)")
    return seeds
