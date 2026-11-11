"""Arbres d'un parcours : assemblage des couches.

Portage de ``plant_course`` (étude du lot 5, retirée au R7), sans
mesures. Couches dans l'ordre, chacune évitant les couronnes déjà posées :
stratégique (``place_strategic``, ``e = 3``), ancrages (``fixed``, cœur ``m = 0``
et couronnes), lisière (bande au bord, sans bruit) puis remplissage (bruit à
une octave, seuil = quantile sur le plantable, budget de couverture).

``margin`` ne règle que le corridor de la lisière et du remplissage ; les
couches stratégiques (corridors ``others`` à ``m = 5``) et les ancrages (cœur
``m = 0``) n'en dépendent pas.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
import math
from numbers import Real
from typing import Any, Mapping

import numpy as np

from golfgen.dressing.from_json import course_input_from_json
from golfgen.dressing.paths.scene import Scene, scene_from_json
from golfgen.dressing.rng import TREE_EDGE_LAYER, TREE_FILL_LAYER, tree_rng
from golfgen.dressing.trees.anchors import AnchorGrove, plant_anchors
from golfgen.dressing.trees.fill import PLANTABLE_RADIUS, edge_band, forest_zone, greedy, noise_field
from golfgen.dressing.trees.geometry import CORRIDOR_MARGIN, crown_fits, crown_mask, forbidden_masks
from golfgen.dressing.trees.strategic import GREEN_KEY, LANDING_KEY, place_strategic

ANCHOR_KEY, EDGE_KEY, FILL_KEY = "ancrage", "lisiere", "remplissage"
LAYERS = (LANDING_KEY, GREEN_KEY, ANCHOR_KEY, EDGE_KEY, FILL_KEY)
MARGIN_RANGE = (0.0, 12.0)      # blocs : plage validée de ``margin``


@dataclass(frozen=True)
class Preset:
    """Réglages du remplissage d'un style : part couverte du plantable et
    largeur de la bande de lisière (blocs, 0 : pas de lisière)."""
    cover: float
    edge: int


PRESETS: Mapping[str, Preset] = {"parkland": Preset(0.65, 12), "links": Preset(0.05, 0)}


@dataclass(frozen=True, slots=True)
class TreeItem:
    """Un arbre : case ``(x, z)``, rayon, couche (``LAYERS``), et ``grove``
    (indice de l'ancrage) sur les arbres d'ancrage seuls."""
    x: int
    z: int
    radius: int
    layer: str
    grove: int | None = None


@dataclass(frozen=True)
class CourseTrees:
    """Arbres d'un parcours, dans l'ordre de pose. ``counts`` : arbres par
    couche ; ``skips`` : par couche, trous ou ancrages en défaut par motif ;
    ``groves`` : détail de chaque ancrage (indice, case, arbres posés et visés,
    motif), complet ou non."""
    items: tuple[TreeItem, ...]
    counts: Mapping[str, int]
    skips: Mapping[str, Mapping[str, int]]
    groves: tuple[AnchorGrove, ...]

    def layer(self, name: str) -> tuple[TreeItem, ...]:
        """Arbres de la couche ``name``, dans l'ordre de pose."""
        return tuple(item for item in self.items if item.layer == name)


def validate_margin(margin: float) -> None:
    """``ValueError`` si ``margin`` n'est pas un nombre réel fini (booléens
    exclus) dans ``MARGIN_RANGE``."""
    if (isinstance(margin, bool) or not isinstance(margin, Real) or not math.isfinite(margin)
            or not MARGIN_RANGE[0] <= margin <= MARGIN_RANGE[1]):
        raise ValueError(f"marge des arbres invalide : {margin!r} (attendu : nombre fini "
                         f"entre {MARGIN_RANGE[0]:g} et {MARGIN_RANGE[1]:g} blocs)")


def place_trees(data: Mapping[str, Any], margin: float = CORRIDOR_MARGIN,
                scene: Scene | None = None) -> CourseTrees:
    """Arbres d'un JSON 3.3 (voir le docstring du module). ``scene`` : scène
    déjà construite, sinon lue du JSON. ``ValueError`` : ``margin`` hors de
    ``MARGIN_RANGE`` ou non finie. ``TreeError`` : JSON sans chemins ni bunkers,
    ou invariant cassé ; une couche incomplète n'en est jamais une."""
    validate_margin(margin)
    scene = scene_from_json(data) if scene is None else scene
    course = course_input_from_json(data)
    seed, width, height = int(course.seed), scene.width, scene.height
    preset = PRESETS[scene.style]
    masks = forbidden_masks(data, scene, margin)
    fixed, corridor = masks.fixed, masks.corridor

    strategic = place_strategic(data, course, masks)
    crowns = crown_mask([(t.x, t.z, t.radius) for t in strategic.trees], width, height)
    groves = plant_anchors(data, fixed | masks.core | crowns, crowns, seed)

    solid = fixed | corridor | crowns
    plantable = crown_fits(fixed | corridor, PLANTABLE_RADIUS)
    edge = greedy(np.argwhere(edge_band(width, height, preset.edge) & plantable)[:, ::-1], solid, crowns,
                  tree_rng(seed, TREE_EDGE_LAYER))
    zone = forest_zone(noise_field(seed, width, height), plantable, preset.cover)
    forest = greedy(np.argwhere(zone)[:, ::-1], solid, crowns, tree_rng(seed, TREE_FILL_LAYER),
                    budget=int(preset.cover * np.count_nonzero(plantable)))

    items = [*(TreeItem(t.x, t.z, t.radius, t.layer) for t in strategic.trees),
             *(TreeItem(x, z, r, ANCHOR_KEY, grove.index) for grove in groves for x, z, r in grove.trees),
             *(TreeItem(x, z, r, EDGE_KEY) for x, z, r in edge),
             *(TreeItem(x, z, r, FILL_KEY) for x, z, r in forest)]
    placed = Counter(item.layer for item in items)
    motifs = Counter(grove.motif for grove in groves if grove.motif)
    return CourseTrees(tuple(items), {name: placed[name] for name in LAYERS},
                       {LANDING_KEY: dict(strategic.landing.skips), GREEN_KEY: dict(strategic.green.skips),
                        ANCHOR_KEY: dict(sorted(motifs.items())), EDGE_KEY: {}, FILL_KEY: {}},
                       groves)
