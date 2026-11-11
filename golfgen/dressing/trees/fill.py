"""Pose gloutonne des arbres, lisière et bruit du remplissage.

Portage de l'étude du remplissage (lot 5, retirée au R7). ``greedy`` est la
seule pose des couches ancrages, lisière et remplissage. Le bruit passe par
une instance ``OpenSimplex`` locale : la graine globale d'``opensimplex``
n'est jamais touchée.
"""

from __future__ import annotations

import numpy as np
from opensimplex import OpenSimplex

from golfgen.dressing.rng import TREE_NOISE_LAYER, tree_rng
from golfgen.dressing.trees.geometry import CROWN_RADII, Tree, crown_cells

# Tirage 30/50/20 %. Répartition POSÉE ≈ 50/37/12 sur lisière et remplissage : le
# tirage est tenu tant que les rayons tiennent, puis une queue de rayon 2 comble
# les interstices.
RADIUS_WEIGHTS = (0.3, 0.5, 0.2)    # parts tirées de CROWN_RADII
PLANTABLE_RADIUS = 2                # blocs : plus petite couronne
NOISE_WAVELENGTH = 40.0             # blocs, une octave
NOISE_SEED_SPAN = 2 ** 31


def draw_radius(rng: np.random.Generator) -> int:
    """Rayon de couronne tiré selon ``RADIUS_WEIGHTS``."""
    return CROWN_RADII[int(np.searchsorted(np.cumsum(RADIUS_WEIGHTS)[:-1], rng.random(), side="right"))]


def greedy(cells: np.ndarray, solid: np.ndarray, crowns: np.ndarray, rng: np.random.Generator, *,
           radius: int | None = None, limit: int | None = None, shuffle: bool = True,
           budget: int | None = None) -> list[Tree]:
    """La seule pose : candidats ``(k, 2)`` permutés (si ``shuffle``), rejet si la
    couronne sort de la carte ou touche ``solid``. ``radius`` imposé : aucun tirage,
    arrêt quand il ne tient plus. Sinon, rayon tiré et conservé d'un candidat à
    l'autre jusqu'à ce qu'il tienne ; s'il ne tient plus nulle part, plafond au
    rayon inférieur pour terminer. ``budget`` : cases de couronne à ne pas
    dépasser. Marque ``solid`` et ``crowns``."""
    height, width = solid.shape
    order = rng.permutation(len(cells)) if shuffle else np.arange(len(cells))
    ceiling = [max(CROWN_RADII)] * len(cells)   # plus grand rayon encore possible (``solid`` ne fait que croître)
    cursor, cap, used = dict.fromkeys(CROWN_RADII, 0), max(CROWN_RADII), 0
    placed: list[Tree] = []
    pending = draw_radius(rng) if radius is None else radius
    while limit is None or len(placed) < limit:
        r = min(pending, cap)
        k = cursor[r]
        while k < len(cells) and ceiling[k] < r:
            k += 1
        cursor[r] = k
        if k == len(cells):
            if radius is not None or r == min(CROWN_RADII):
                break
            cap = max(v for v in CROWN_RADII if v < r)
            continue
        x, y = int(cells[order[k], 0]), int(cells[order[k], 1])
        crown = crown_cells((x, y), r)
        if not (r <= x < width - r and r <= y < height - r) or solid[crown[:, 1], crown[:, 0]].any():
            ceiling[k] = r - 1
            continue
        if budget is not None and used + len(crown) > budget:
            break
        solid[crown[:, 1], crown[:, 0]] = crowns[crown[:, 1], crown[:, 0]] = True
        placed.append((x, y, r))
        used, ceiling[k] = used + len(crown), 0
        pending = draw_radius(rng) if radius is None else radius
    return placed


def edge_band(width: int, height: int, edge: int) -> np.ndarray:
    """Cases à moins de ``edge`` blocs du bord (rien si ``edge`` vaut 0)."""
    band = np.ones((height, width), dtype=bool)
    band[edge:height - edge, edge:width - edge] = False
    return band if edge else np.zeros((height, width), dtype=bool)


def noise_field(seed: int, width: int, height: int) -> np.ndarray:
    """Bruit ``(h, w)`` du remplissage, une octave, instance locale."""
    generator = OpenSimplex(int(tree_rng(seed, TREE_NOISE_LAYER).integers(NOISE_SEED_SPAN)))
    return generator.noise2array(np.arange(width) / NOISE_WAVELENGTH, np.arange(height) / NOISE_WAVELENGTH)


def forest_zone(noise: np.ndarray, plantable: np.ndarray, cover: float) -> np.ndarray:
    """Part ``cover`` du plantable, aux valeurs de bruit les plus hautes."""
    if not plantable.any():
        return np.zeros_like(plantable)
    return plantable & (noise >= np.quantile(noise[plantable], 1.0 - cover))
