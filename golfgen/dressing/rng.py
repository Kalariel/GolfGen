"""Flux aléatoires de l'habillage : étiquette, sous-flux et générateurs.

Module feuille (n'importe que numpy) : ``golfgen.dressing.course`` le
réexporte, et les modules qu'il importera (bunkers) le lisent sans cycle.

Tous les flux sont ``np.random.default_rng([seed, RNG_LABEL, order, ...])``.
Le routeur n'emploie que des suites de un ou deux éléments après la seed
(sites : 0/1 ; muirfield : 7, 11, 13, 17, 23, 31) : flux disjoints, donc
changer l'habillage ou le style ne change jamais le tracé. Identifiants de
sous-flux (4ᵉ mot) ≥ 1 : ``SeedSequence`` confond une entropie et la même
suivie de zéros.

Sous-flux (4ᵉ mot) :

- (aucun) green : ``[seed, RNG_LABEL, order]`` (``green_rng``) ;
- 1 départs (``TEE_STREAM``), 2 greens doubles (``PAIR_STREAM``, ordre
  ``COURSE_ORDER`` = 0), 3 fairway (``FAIRWAY_STREAM``), 4 profil en long
  du fairway (``PROFILE_STREAM``) ;
- bunkers (``golfgen.dressing.bunkers``, mots suivants : rôle, catégorie ou
  nombre) : 5 haricots (``beans.BUNKER_STREAM``), 7 nombre et motif des
  pots de green (``pots.CLUSTER_STREAM``), 8 tailles des pots de green
  (``pots.MIX_STREAM``), 9 décalage du duo d'appel
  (``pots.STAGGER_STREAM``), 11 trio d'appel (``pots.TRIO_STREAM``), 12
  nombre de pots d'appel (``pots.COUNT_STREAM``), 0x464C4B48 côté du
  flanc des haricots « devant » (``green_phase.HARICOT_FLANK_STREAM``,
  « FLKH ») ;
- trous sans bunker (``EMPTY_HOLE_STREAM`` = 0x56494445, « VIDE » en
  ASCII, ``empty_hole_rng``) : un tirage par trou, 1 chance sur 50 que le
  trou n'ait aucun bunker (``bunkers.selection.empty_holes``). Générateur
  neuf par trou, valeur distincte de tous les sous-flux ci-dessus et des
  flux de l'étude : ce tirage ne décale aucun autre flux ;
- haricots de green de la famille remplacée (``REPLACED_GREEN_STREAM`` =
  0x4F524748, « ORGH » en ASCII, valeur historique : ces haricots ont
  remplacé les organiques de green ; ``replaced_green_rng``), 5ᵉ mot =
  usage : 1 nombre et sites (``REPLACED_GREEN_SITES``, même loi que
  ``selection.BEAN_GREEN_COUNTS`` et ``BEAN_SITES``), 2 forme du haricot
  (``REPLACED_GREEN_SHAPE``, même loi que le haricot de garde), 3 côté du
  flanc d'un haricot « devant » (``REPLACED_GREEN_FLANK``). Générateurs
  neufs par trou, réservés aux trous de la famille remplacée
  (``selection.REPLACED_FAMILY``) ;
- virages marqués des chemins (``BENDS_STREAM`` = 0x56495247, « VIRG » en
  ASCII, ``bend_rng``), flux du parcours : ``[seed, RNG_LABEL,
  COURSE_ORDER, BENDS_STREAM, index + 1]``, ordre 0 (aucun trou) et 5ᵉ mot =
  indice de la liaison dans ``routing.links`` + 1 (≥ 1). Générateur neuf
  par liaison (``golfgen.dressing.paths``).

Identifiants réservés, jamais employés en production, à ne jamais
réemployer : 0x43484D4E (« CHMN », serpentins de l'étude des chemins,
abandonnés avant le portage ; ``RESERVED_STREAMS`` ci-dessous).

Identifiants retirés (organiques de green supprimés, 2026-11-02), à ne
jamais réemployer : 0x0B6A (forme des organiques, ``organic.SHAPE_STREAM``)
et 0x464C4B31 (« FLK1 », côté du flanc des organiques,
``green_phase.FLANK_STREAM``) ; choix 0, 1 (quota de trous vides de
l'étude), 4, 5 et 6 (lobes, disposition et longueur des organiques) du
flux de sélection (``RETIRED_*`` ci-dessous et dans
``bunkers.selection``).

Hors de cette étiquette, la sélection des bunkers a ses propres flux
``[seed, bunkers.selection.SELECTION_STREAM, order, choix]``.

Même forme pour les arbres (``golfgen.dressing.trees``), hors de l'étiquette :
``[seed, TREES_STREAM, couche, ...]`` (``tree_rng``), « TRE2 » en ASCII, valeur
de l'étude conservée pour reproduire ses planches. Couches ``TREE_*_LAYER`` ≥ 1,
mots suivants selon la couche. Exception reprise de l'étude : l'indice d'un
ancrage part de 0, donc l'ancrage 0 se confond avec ``[seed, TREES_STREAM,
TREE_ANCHOR_LAYER]``, flux que rien n'emploie.
"""

from __future__ import annotations

import numpy as np

# Étiquette du flux aléatoire de l'habillage : ``[seed, RNG_LABEL, order]``.
RNG_LABEL = 0xD7E5
# Sous-flux des départs : ``[seed, RNG_LABEL, order, TEE_STREAM]``, séparé de
# celui du green (``[seed, RNG_LABEL, order]``) : poser les départs ne change
# aucun tirage du green.
TEE_STREAM = 1
# Flux du parcours pour les greens doubles : ``[seed, RNG_LABEL,
# COURSE_ORDER, PAIR_STREAM]``. ``ElasticHole`` impose ``1 ≤ order ≤ 18`` :
# l'ordre 0 ne désigne aucun trou, donc ce flux diffère de ``tee_rng`` (même
# longueur, 3ᵉ mot 0 ≠ order) et de ``green_rng`` (un mot de plus, non nul :
# ``SeedSequence`` ne le confond pas avec un bourrage de zéros, et 3ᵉ mot 0
# ≠ order). ``PAIR_STREAM`` = 2 : sous-flux réservé aux paires (0 interdit,
# 1 = départs). Vérifié par ``tests/test_dressing_pairs.py``.
COURSE_ORDER = 0
PAIR_STREAM = 2
# Sous-flux du fairway : ``[seed, RNG_LABEL, order, FAIRWAY_STREAM]`` (plan du
# lot 2), même forme que ``tee_rng`` avec un 4ᵉ mot différent : poser le
# fairway ne change aucun tirage du green, des départs ni des paires.
FAIRWAY_STREAM = 3
# Sous-flux du profil en long du fairway (R3 : carry, avant-green) :
# ``[seed, RNG_LABEL, order, PROFILE_STREAM]``, séparé de ``FAIRWAY_STREAM``
# : les tirages de forme (B v1 à col marqué) ne bougent pas.
PROFILE_STREAM = 4
# Sous-flux du tirage « trou sans bunker » (règle de production, 2 %) :
# ``[seed, RNG_LABEL, order, EMPTY_HOLE_STREAM]``, « VIDE » en ASCII.
EMPTY_HOLE_STREAM = 0x56494445
# Haricots de green de la famille remplacée (ex-organiques) : [seed,
# RNG_LABEL, order, REPLACED_GREEN_STREAM, usage], « ORGH » en ASCII
# (valeur historique, inchangée) ; usages ≥ 1.
REPLACED_GREEN_STREAM = 0x4F524748
REPLACED_GREEN_SITES = 1            # nombre et sites des haricots
REPLACED_GREEN_SHAPE = 2            # forme (tirage du haricot de garde)
REPLACED_GREEN_FLANK = 3            # côté du flanc d'un haricot « devant »
# Sous-flux retirés avec les organiques de green : jamais réemployés.
RETIRED_STREAMS = (0x0B6A, 0x464C4B31)
# Sous-flux des virages marqués des chemins : [seed, RNG_LABEL,
# COURSE_ORDER, BENDS_STREAM, index + 1], « VIRG » en ASCII.
BENDS_STREAM = 0x56495247
# Sous-flux réservés : employés par une étude, jamais en production, à ne
# jamais réemployer (« CHMN » : serpentins de l'étude des chemins).
RESERVED_STREAMS = (0x43484D4E,)
# Flux des arbres : [seed, TREES_STREAM, couche, ...], « TRE2 » en ASCII.
TREES_STREAM = 0x54524532
TREE_LANDING_LAYER = 1              # retombée : [TREE_USE_ORDER] ou [TREE_USE_HOLE, trou]
TREE_GREEN_LAYER = 2                # green : mêmes mots
TREE_ANCHOR_LAYER = 3               # ancrages : [indice de l'ancrage]
TREE_EDGE_LAYER = 4                 # lisière
TREE_FILL_LAYER = 5                 # remplissage
TREE_NOISE_LAYER = 6                # graine du bruit du remplissage
TREE_USE_ORDER = 1                  # ordre de visite des trous d'une couche
TREE_USE_HOLE = 2                   # tirages d'un trou (côté, nombre d'arbres)

def green_rng(seed: int, order: int) -> np.random.Generator:
    """Flux aléatoire du green du trou ``order``."""
    return np.random.default_rng([seed, RNG_LABEL, order])


def tee_rng(seed: int, order: int) -> np.random.Generator:
    """Flux aléatoire des départs du trou ``order`` (séparé de ``green_rng``)."""
    return np.random.default_rng([seed, RNG_LABEL, order, TEE_STREAM])


def fairway_rng(seed: int, order: int) -> np.random.Generator:
    """Flux aléatoire du fairway du trou ``order`` (``golfgen.dressing.fairway``)."""
    return np.random.default_rng([seed, RNG_LABEL, order, FAIRWAY_STREAM])


def fairway_profile_rng(seed: int, order: int) -> np.random.Generator:
    """Flux aléatoire du profil en long du fairway du trou ``order`` (séparé
    de ``fairway_rng`` : la forme brute ne change pas)."""
    return np.random.default_rng([seed, RNG_LABEL, order, PROFILE_STREAM])


def empty_hole_rng(seed: int, order: int) -> np.random.Generator:
    """Flux du tirage « trou sans bunker » du trou ``order`` (un tirage)."""
    return np.random.default_rng([seed, RNG_LABEL, order, EMPTY_HOLE_STREAM])


def replaced_green_rng(seed: int, order: int, use: int) -> np.random.Generator:
    """Flux ``use`` (``REPLACED_GREEN_*``) des haricots de green de la
    famille remplacée du trou ``order`` (générateur neuf)."""
    return np.random.default_rng([seed, RNG_LABEL, order, REPLACED_GREEN_STREAM, use])


def bend_rng(seed: int, index: int) -> np.random.Generator:
    """Flux des virages marqués de la liaison ``index`` (indice dans
    ``routing.links``, à partir de 0 ; générateur neuf)."""
    return np.random.default_rng([seed, RNG_LABEL, COURSE_ORDER, BENDS_STREAM, index + 1])


def tree_rng(seed: int, layer: int, *words: int) -> np.random.Generator:
    """Flux de la couche ``layer`` (``TREE_*_LAYER``) des arbres, mots suivants
    selon la couche (générateur neuf)."""
    return np.random.default_rng([seed, TREES_STREAM, layer, *words])


def pair_rng(seed: int) -> np.random.Generator:
    """Flux aléatoire du parcours pour les greens doubles (un tirage au plus,
    en parkland ; ``golfgen.dressing.pairs``)."""
    return np.random.default_rng([seed, RNG_LABEL, COURSE_ORDER, PAIR_STREAM])
