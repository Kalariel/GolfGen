"""Sélection des bunkers de chaque trou, avant toute pose (round R3).

Choix seedés trou par trou, sans regarder la géométrie ni l'admissibilité
des poses : trous vides, famille du green, sites des haricots de green,
coin du haricot de retombée. Le résultat est une ``HoleSpec`` (dict) par
trou, que lit ``golfgen.dressing.bunkers.cases.build_cases``.

Flux : ``np.random.default_rng([seed, SELECTION_STREAM, order, choix])``,
un flux par choix (``*_CHOICE``). Distincts des flux de forme
(``[seed, RNG_LABEL, ...]``). Choix retirés, jamais réemployés :
``RETIRED_CHOICES``.

Trous vides (``empty_holes``, règle ``EMPTY_RULE``, validée par
l'utilisateur le 2026-10-22) : chaque trou, indépendamment, n'a aucun
bunker avec la probabilité ``EMPTY_PROBABILITY`` (1 sur 50) ; ni minimum
ni plafond. Tirage sur un flux dédié par trou
(``golfgen.dressing.rng.empty_hole_rng``), qui ne consomme ni ne décale
aucun autre flux.

Famille du green : tirage uniforme sur ``GREEN_FAMILIES`` (1/4 pots, 1/4
haricots, 1/2 famille remplacée). La famille remplacée
(``REPLACED_FAMILY``) occupe les cases de l'ancien organique de green : le
tirage de la famille est gardé tel quel, et ses greens reçoivent des
haricots de green (décision du 2026-11-02 : les organiques sont
abandonnés), nombre et sites tirés comme ceux de la famille haricot mais
sur un flux dédié (``golfgen.dressing.rng.replaced_green_rng``).

Poids : ceux du prototype de l'étude, NON validés comme définitifs. Ils
sont regroupés ci-dessous (``GREEN_FAMILIES``, ``BEAN_GREEN_COUNTS``).
"""

from __future__ import annotations

from typing import TypedDict

import numpy as np

from golfgen.dressing.rng import REPLACED_GREEN_SITES, empty_hole_rng, replaced_green_rng

# --- flux ---------------------------------------------------------------------------
SELECTION_STREAM = 0x43534C31
FAMILY_CHOICE = 2                   # famille du green
BEAN_SITES_CHOICE = 3               # nombre et sites des haricots de green
LANDING_SITE_CHOICE = 7             # site du haricot de retombée
# Choix retirés, jamais réemployés : 0 et 1 (quota de trous vides de
# l'étude), 4, 5 et 6 (lobes, disposition et longueur des organiques).
RETIRED_CHOICES = (0, 1, 4, 5, 6)

# --- trous sans bunker -----------------------------------------------------------------
EMPTY_RULE = "per_hole"             # règle unique, exportée (``bunkers.empty_rule`` du JSON 3.2)
EMPTY_PROBABILITY = 1 / 50
COURSE_HOLES = 18

# --- poids des familles (prototype de l'étude) ---------------------------------------
# Famille remplacée : ex-organique de green, servie par des haricots de green
# tirés sur un flux dédié (``replaced_green_beans``).
REPLACED_FAMILY = "haricot_remplacant"
# Famille du green : index uniforme sur ce tuple (1/4 pots, 1/4 haricots,
# 1/2 famille remplacée).
GREEN_FAMILIES = ("pot", "haricot", REPLACED_FAMILY, REPLACED_FAMILY)
BEAN_SITES = ("côté actuel", "devant", "derrière")
BEAN_GREEN_COUNTS = (1, 2)          # nombre de haricots de green, équiprobable

# --- haricot de retombée --------------------------------------------------------------
OUTSIDE, STRAIGHT = "outside", "straight"
# Chemin validé (corpus de l'étude, 2026-11-01) : coin extérieur des doglegs.
DOGLEG_LANDING = OUTSIDE


class HoleSpec(TypedDict, total=False):
    """Sélection d'un trou.

    Toujours : ``key`` (``"tNN"``), ``title``, ``order``,
    ``empty_selected``. Hors trou vide : ``green_family`` (``"pot"``,
    ``"haricot"``, ``REPLACED_FAMILY``) puis, selon la famille :

    - pot : ``pots = "green"`` ;
    - haricot : ``haricot_green`` (1 ou 2 sites de ``BEAN_SITES``, dans cet
      ordre), et ``pots = "landing"`` hors par 3 ;
    - famille remplacée : hors par 3 ``haricot_landing`` (``"straight"``,
      ou le coin ``DOGLEG_LANDING`` d'un dogleg) avec ``landing_site_draw``
      ∈ [0, 1), puis ``haricot_green`` (``replaced_green_beans``).
    """

    key: str
    title: str
    order: int
    empty_selected: bool
    green_family: str
    pots: str
    haricot_green: tuple[str, ...]
    haricot_landing: str
    landing_site_draw: float


def is_replaced(spec: HoleSpec) -> bool:
    """Trou de la famille remplacée : ses haricots de green ont leurs flux
    dédiés (``replaced_green_rng``) et sont construits en dernier."""
    return spec.get("green_family") == REPLACED_FAMILY


def bean_sites(draw: np.random.Generator) -> tuple[str, ...]:
    """1 ou 2 sites de ``BEAN_SITES`` (dans cet ordre) tirés sur ``draw``."""
    count = int(draw.integers(BEAN_GREEN_COUNTS[0], BEAN_GREEN_COUNTS[-1] + 1))
    indices = sorted(draw.choice(len(BEAN_SITES), count, replace=False).tolist())
    return tuple(BEAN_SITES[i] for i in indices)


def replaced_green_beans(seed: int, order: int) -> tuple[str, ...]:
    """Sites des haricots de green de la famille remplacée : même loi que la
    famille haricot, flux dédié ``replaced_green_rng(seed, order,
    REPLACED_GREEN_SITES)``."""
    return bean_sites(replaced_green_rng(seed, order, REPLACED_GREEN_SITES))


def selection_rng(seed: int, order: int, choice: int) -> np.random.Generator:
    """Flux du choix ``choice`` du trou ``order``."""
    return np.random.default_rng([seed, SELECTION_STREAM, order, choice])


def empty_holes(seed: int, holes) -> set[int]:
    """Trous sans bunker : un tirage par trou (``EMPTY_PROBABILITY``)."""
    return {h.order for h in holes if empty_hole_rng(seed, h.order).random() < EMPTY_PROBABILITY}


def select_specs(seed: int, holes) -> list[HoleSpec]:
    """Sélection de chaque trou (triée par numéro), avant toute pose."""
    holes = sorted(holes, key=lambda h: h.order)
    if len(holes) != COURSE_HOLES or len({h.order for h in holes}) != COURSE_HOLES:
        raise ValueError(f"parcours de {COURSE_HOLES} trous distincts attendu")
    empty = empty_holes(seed, holes)
    specs = []
    for hole in holes:
        spec: HoleSpec = {"key": f"t{hole.order:02d}", "title": f"Trou {hole.order} · par {hole.par}",
                          "order": hole.order, "empty_selected": hole.order in empty}
        if hole.order not in empty:
            family = GREEN_FAMILIES[int(selection_rng(seed, hole.order, FAMILY_CHOICE).integers(len(GREEN_FAMILIES)))]
            spec["green_family"] = family
            if family == "pot":
                spec["pots"] = "green"
            elif family == "haricot":
                spec["haricot_green"] = bean_sites(selection_rng(seed, hole.order, BEAN_SITES_CHOICE))
                if hole.par != 3:
                    spec["pots"] = "landing"
            else:
                if hole.par != 3:
                    spec["haricot_landing"] = DOGLEG_LANDING if hole.doglegs else STRAIGHT
                    spec["landing_site_draw"] = float(selection_rng(seed, hole.order, LANDING_SITE_CHOICE).random())
                spec["haricot_green"] = replaced_green_beans(seed, hole.order)
        specs.append(spec)
    return specs
