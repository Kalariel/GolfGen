"""Habillage d'un parcours routé : point d'entrée ``dress_course``."""

from __future__ import annotations

import dataclasses
from types import MappingProxyType

import numpy as np

from golfgen.dressing.fairway import FAIRWAY_STYLES
from golfgen.dressing.fairway_profile import fairway_obstacles
from golfgen.dressing.fairway_water import FAIRWAY_WATER_CUT, water_fairway
from golfgen.dressing.green import dry_green_shape
from golfgen.dressing.model import STYLE_SPECS, CourseDressing, HoleDressing, WaterFix
from golfgen.dressing.pairs import pair_selection
# Flux aléatoires (étiquette, sous-flux, générateurs) : module feuille
# ``golfgen.dressing.rng``, réexporté ici (sous-flux 1–4 de l'habillage et
# 5/7/8/9/11/12 et suivants des bunkers documentés là-bas). Feuille : les bunkers
# l'importent sans passer par ce module, qui les importera.
from golfgen.dressing.rng import (COURSE_ORDER, FAIRWAY_STREAM, PAIR_STREAM,  # noqa: F401
                                  PROFILE_STREAM, RNG_LABEL, TEE_STREAM, fairway_profile_rng,
                                  fairway_rng, green_rng, pair_rng, tee_rng)
from golfgen.dressing.tees import dry_tee_boxes
from golfgen.dressing.water import effective_water, raised_mask
from golfgen.routing.geometry import build_hole_geometry
from golfgen.routing.sites import water_mask


def _has_course_context(layout) -> bool:
    """Vrai si ``layout`` porte le contexte des contrôles des paires
    (liaisons, clubhouse, taille de carte), comme tout ``CourseLayout``."""
    return all(hasattr(layout, name) for name in ("links", "clubhouse", "width", "height"))


def dress_course(result, *, seed: int, style: str,
                 relief: np.ndarray | None = None) -> CourseDressing:
    """Habillage du parcours ``result`` (``MuirfieldResult``, ou tout objet
    portant ``layout: CourseLayout``) pour le ``style`` donné.

    ``relief`` : relief du routage (``(h, w)``, indexé ``[y, x]``, taille de
    la carte), dont l'habillage lit l'eau à la vraie berge
    (``golfgen.routing.sites.water_mask``), ou ``None`` (défaut) pour une
    carte sans eau connue : habillage d'avant l'eau, au bit près. Avec
    ``relief`` (production : ``dress_course_json`` passe le relief relu),
    lot 1 eau : chaque green tiré sur l'eau est replié selon le style
    (``dry_green_shape`` : décalé en links, insulaire en parkland et en
    dernier recours links), puis les boîtes de départ sont gardées au sec de
    l'eau EFFECTIVE de leur trou (``golfgen.dressing.water.effective_water``
    : eau réelle moins son green insulaire ; ``dry_tee_boxes`` : glissement
    dans l'axe, décalage en travers, puis remontée, jamais sur une cellule
    déjà remontée), une paire de greens
    dont la forme touche l'eau RÉELLE est écartée (cause ``eau``, pas
    d'insulaire pour les greens doubles) ; replis déterministes, sans tirage
    supplémentaire, tracés dans ``HoleDressing.water_fix``. Un trou sans
    eau sous son green ni ses boîtes a l'habillage d'avant l'eau, au bit
    près (son fairway peut changer si un green ou une boîte voisins ont
    bougé : ``fairway_obstacles``). Lot 2 R4 : le fairway de chaque trou est
    coupé au-dessus de l'eau EFFECTIVE du trou (``effective_water(eau,
    (green, *boîtes))``) selon ``FAIRWAY_WATER_CUT``
    (``golfgen.dressing.fairway_water.water_fairway`` : bande de rough,
    fragments trop petits retirés et tracés dans
    ``HoleDressing.fairway_removed``, fairway vidé tracé dans
    ``HoleDressing.fairway_empty_cause``) ; sans ``relief``, aucune
    coupure, fairway de production au bit près ; eau entourée de fairway :
    ``DressingError``, sans repli.

    Fonction pure : ni I/O, ni état global ; aléa tiré de flux propres à
    chaque trou : ``green_rng`` pour le green, ``tee_rng`` pour les départs
    (``golfgen.dressing.tees``), posés après le green ; puis, une fois tous
    les greens et départs posés, sélection des greens doubles
    (``golfgen.dressing.pairs``, flux ``pair_rng`` du parcours), qui les lit
    sans les modifier, et forme de chaque paire retenue
    (``golfgen.dressing.pair_shape``, déterministe, sans tirage) ; enfin le
    fairway de chaque trou (``golfgen.dressing.fairway`` et
    ``golfgen.dressing.fairway_profile``, lus par rien d'autre) : forme
    B v1 à col marqué (``profile_neck``, flux ``fairway_rng``), profil en
    long (flux ``fairway_profile_rng``), contournement des boîtes, des greens et des
    greens doubles (``fairway_obstacles``), coupure sur l'eau
    (``golfgen.dressing.fairway_water``, déterministe, sans tirage). L'oracle
    ``check_green_pairs`` est appelé dans la sélection, paire par paire :
    une paire dont la forme échoue (construction, oracle)
    est ÉCARTÉE et la valide suivante est examinée ; ``dress_course`` ne
    lève pas pour une paire. Les candidates écartées et leur cause sont
    tracées dans ``pair_rejections``
    (``golfgen.dressing.pairs.pair_selection``). La sélection exige le
    contexte complet d'un ``CourseLayout`` (liaisons, clubhouse, taille de
    carte) ; un ``layout``
    réduit à ``holes`` (instantanés de tests et d'outils) est habillé sans
    greens doubles (``green_pairs = ()``).
    ``seed`` est la seed u64 donnée au routage (``golfgen.seed.seed_u64``).
    Ne lit que le tracé, ne le modifie pas."""
    if isinstance(seed, bool) or not isinstance(seed, int):
        raise TypeError("seed doit être un entier")
    if not 0 <= seed < 2 ** 64:
        raise ValueError("seed attendue sous forme u64 (0 ≤ seed < 2^64)")
    if style not in STYLE_SPECS:
        raise ValueError(f"style inconnu : {style!r} (attendu : {', '.join(STYLE_SPECS)})")
    water = None
    if relief is not None:
        relief = np.asarray(relief)
        if relief.ndim != 2:
            raise ValueError("relief attendu en tableau 2D (h, w)")
        water = water_mask(relief)
        if _has_course_context(result.layout):
            water.require_size(result.layout.width, result.layout.height)
    spec = STYLE_SPECS[style]
    ordered = sorted(result.layout.holes, key=lambda h: h.order)
    cores, greens = {}, {}
    for hole in ordered:
        cores[hole.order] = core = build_hole_geometry(hole).core
        greens[hole.order] = dry_green_shape(hole, core, green_rng(seed, hole.order), spec,
                                             water, relief)
    # départs posés après TOUS les greens (flux séparés : aucun tirage ne
    # change), chacun sur l'eau effective de SON trou (eau réelle moins son
    # green insulaire : la bande remontée par un autre trou reste de l'eau),
    # sans se remonter sur une cellule déjà remontée (``raised`` : greens de
    # tous les trous, boîtes des trous précédents)
    raised = raised_mask(water, (green for green, _ in greens.values()))
    holes = {}
    for hole in ordered:
        green, green_fix = greens[hole.order]
        tees, cause, tee_fix = dry_tee_boxes(hole, cores[hole.order], green.outline,
                                             tee_rng(seed, hole.order),
                                             effective_water(water, (green,)), relief, raised)
        if tee_fix is not None and tee_fix.tees_raised:
            raised = raised | raised_mask(water, tees)
        fix = green_fix
        if tee_fix is not None:
            fix = dataclasses.replace(
                green_fix or WaterFix(), tees_moved=tee_fix.tees_moved,
                tees_shifted=tee_fix.tees_shifted, tees_raised=tee_fix.tees_raised,
                tees_submerged=tee_fix.tees_submerged, back_slide=tee_fix.back_slide)
        holes[hole.order] = HoleDressing(order=hole.order, green=green, tees=tees,
                                         tee_fallback_cause=cause, water_fix=fix)
    pairs, rejections = (), ()
    if _has_course_context(result.layout):
        pairs, rejections = pair_selection(result.layout, holes, cores, style, pair_rng(seed),
                                           water)
    obstacles = fairway_obstacles(holes, pairs)
    for hole in sorted(result.layout.holes, key=lambda h: h.order):
        hd = holes[hole.order]
        # eau effective du trou (eau réelle moins SON green insulaire et SES
        # boîtes remontées) ; ``None`` sans relief : aucune coupure
        fairway = water_fairway(hole, cores[hole.order], FAIRWAY_STYLES[style],
                                fairway_rng(seed, hole.order),
                                fairway_profile_rng(seed, hole.order), hd.tees,
                                hd.green.outline, obstacles,
                                effective_water(water, (hd.green, *hd.tees)), FAIRWAY_WATER_CUT)
        holes[hole.order] = dataclasses.replace(hd, fairway=fairway.shapes,
                                                fairway_removed=fairway.removed,
                                                fairway_empty_cause=fairway.empty_cause)
    return CourseDressing(style=style, holes=MappingProxyType(holes), green_pairs=pairs,
                          pair_rejections=rejections)
