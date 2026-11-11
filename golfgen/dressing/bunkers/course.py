"""Bunkers d'un parcours entier : point d'entrée public (round R5).

``place_bunkers(layout, dressing, seed)`` enchaîne le chemin validé de
l'étude (décision B2) : contexte (``BunkerContext``), cas de chaque trou
(``cases.course_cases`` : sélection puis construction), phase green
(``green_phase.green_phase``), phase fairway (``fairway_phase.fairway_phase``),
et rend un résultat figé, ``CourseBunkers`` :

- ``bunkers`` : sable légal seulement (``PlacedBunker``, aucun statut
  signalé), trous dans l'ordre, bunkers dans l'ordre de la liste du trou ;
  ``cells`` = cases de sable ``(k, 2)`` entières ``(x, z)`` (la case
  ``(x, z)`` couvre ``[x, x + 1] × [z, z + 1]``, comme ``WaterMask``), en
  lecture seule ;
- ``unplaced`` : bunkers sélectionnés mais absents du parcours final
  (``UnplacedBunker``, raisons ``reasons``) : rôle sans pose à la
  construction (``missing`` des cas, étape ``STAGE_CONSTRUCTION``), pose
  signalée retirée du sable (étape ``STAGE_CONSTRUCTION`` pour ``REJECTED``,
  ``STAGE_GREEN`` pour ``FLANK_FAILED`` ; pose gardée dans ``pose``) ou
  unité de fairway non posée (étape ``STAGE_FAIRWAY``, raison
  ``18b``/``acces``/``autre``) ;
- ``empty_holes`` : trous sans bunker par la règle des trous vides
  (``empty_rule`` : ``selection.EMPTY_RULE``, règle unique).

Statut d'une pose (``status``) :

- ``BUILT`` : pose de construction gardée et légale (pots de green,
  haricots de green côté et derrière) ;
- ``FLANK`` / ``FLANK_IGNORING`` : bunker de green re-posé en flanc
  d'entrée (le second : option a′, coupables du blocage ignorés) ;
- ``IN_PLACE`` / ``SLID`` : unité de fairway posée en place ou reculée ;
- ``FLANK_FAILED`` : flanc sans pose légale, pose de construction gardée
  (règle de l'étude) ;
- ``REJECTED`` : pose de construction gardée bien qu'un contrôle l'ait
  refusée (essai visible de l'étude, aucune autre pose à sa place).

Les deux derniers (``FLAGGED_STATUSES``) restaient dans le parcours de
l'étude ; en production, jamais de sable illégal : leur pose passe dans
``unplaced`` (``UnplacedBunker.pose``), avec les contrôles en échec comme
raisons (contrôles de la pose de construction, ``legality.WATER_FAILURE``
pour l'eau, ``map``, ``neighbor_contact``… ; puis, pour un flanc, les
issues des θ essayés : ``green_phase.NO_LEGAL_POSE``, ``CONTACT_STOP``,
raison d'échec de l'accès). ``bunkers`` ∪ poses de ``unplaced`` = parcours
final complet de l'étude.

Déterminisme : mêmes entrées, même résultat (aucun tirage hors des flux
seedés ``[seed, RNG_LABEL, …]``) ; égalité de ``CourseBunkers`` champ à
champ, cases comprises. Résultat non hachable (``__hash__ = None`` : les
cases sont des tableaux numpy).
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass

import numpy as np

from golfgen.dressing.bunkers import fairway_phase as fairway
from golfgen.dressing.bunkers import green_phase as green
from golfgen.dressing.bunkers.cases import course_cases
from golfgen.dressing.bunkers.context import BunkerContext
from golfgen.dressing.bunkers.legality import POSE_FOUND
from golfgen.dressing.bunkers.selection import EMPTY_RULE
from golfgen.dressing.from_json import course_input_from_json

BUILT, FLANK, FLANK_IGNORING = "construction", "flanc", "flanc_sans_fautifs"
IN_PLACE, SLID = fairway.IN_PLACE, fairway.SLID
FLANK_FAILED, REJECTED = "flanc_echec", "rejete"
STATUSES = (BUILT, FLANK, FLANK_IGNORING, IN_PLACE, SLID, FLANK_FAILED, REJECTED)
FLAGGED_STATUSES = (FLANK_FAILED, REJECTED)
STAGE_CONSTRUCTION, STAGE_GREEN, STAGE_FAIRWAY = "construction", "green", "fairway"
STAGES = (STAGE_CONSTRUCTION, STAGE_GREEN, STAGE_FAIRWAY)
FLANK_STATUSES = {green.POSE_FOUND: FLANK, green.POSED_IGNORING: FLANK_IGNORING, green.FAILED: FLANK_FAILED}
# Unité de fairway -> famille de ses bunkers.
UNIT_FAMILIES = {fairway.POTS: "pot", fairway.STRAIGHT: "haricot", fairway.DOGLEG: "haricot"}


def _frozen_cells(cells) -> np.ndarray:
    """Vue en lecture seule d'une copie figée : la copie possède ses données
    et n'est plus inscriptible, numpy refuse donc de rendre la vue
    inscriptible (``setflags(write=True)`` -> ``ValueError``)."""
    owner = np.array(np.asarray(cells, dtype=np.int64).reshape(-1, 2))
    owner.setflags(write=False)
    return owner.view()


@dataclass(frozen=True, slots=True, eq=False)
class PlacedBunker:
    """Pose d'un bunker : ``id`` unique dans son trou ``hole``, ``family``
    (``pot``, ``haricot``), ``role`` (``green``,
    ``landing``), ``cells`` (``(k, 2)`` int64 ``(x, z)``, lecture seule),
    ``status`` (``STATUSES``). Dans ``CourseBunkers.bunkers`` : statut non
    signalé ; sinon pose gardée d'un ``UnplacedBunker``. Non hachable."""

    id: str
    hole: int
    family: str
    role: str
    cells: np.ndarray
    status: str

    def __post_init__(self):
        if self.status not in STATUSES:
            raise ValueError(f"statut de bunker inconnu : {self.status!r}")
        object.__setattr__(self, "cells", _frozen_cells(self.cells))

    def _key(self) -> tuple:
        return (self.id, self.hole, self.family, self.role, self.status)

    def __eq__(self, other):
        if not isinstance(other, PlacedBunker):
            return NotImplemented
        return self._key() == other._key() and np.array_equal(self.cells, other.cells)

    __hash__ = None


@dataclass(frozen=True, slots=True)
class UnplacedBunker:
    """Bunker sélectionné absent du parcours final : ``stage``
    (``STAGE_CONSTRUCTION`` : aucune pose construite, ou pose construite
    refusée ; ``STAGE_GREEN`` : flanc sans pose légale ; ``STAGE_FAIRWAY`` :
    unité non posée), ``reasons`` (au moins une : raison de l'étude, ou
    contrôles en échec d'une pose signalée), ``ids`` de ses bunkers, ``site``
    éventuel, ``pose`` : pose signalée retirée du sable (statut
    ``FLAGGED_STATUSES``), sinon ``None``.

    Non hachable (``__hash__ = None`` explicite) : ``pose`` porte un tableau."""

    hole: int
    family: str
    role: str
    stage: str
    reasons: tuple[str, ...]
    ids: tuple[str, ...] = ()
    site: str | None = None
    pose: PlacedBunker | None = None

    def __post_init__(self):
        if self.stage not in STAGES:
            raise ValueError(f"étape inconnue : {self.stage!r}")
        reasons = tuple(str(r) for r in self.reasons)
        if not reasons:
            raise ValueError("bunker non posé sans raison")
        object.__setattr__(self, "reasons", reasons)
        if self.pose is not None and self.pose.status not in FLAGGED_STATUSES:
            raise ValueError(f"pose non signalée dans les non posés : {self.pose.status!r}")

    __hash__ = None


@dataclass(frozen=True, slots=True)
class CourseBunkers:
    """Bunkers d'un parcours (``place_bunkers``) ; ``bunkers`` : aucun statut
    signalé (refusé sinon). Égalité champ à champ ; non hachable
    (``__hash__ = None`` explicite, ``unsafe_hash=False``) : les bunkers
    portent des tableaux numpy. ``empty_rule`` : règle des trous vides,
    constante (``selection.EMPTY_RULE``, exportée dans le JSON 3.2)."""

    seed: int
    empty_holes: tuple[int, ...]
    bunkers: tuple[PlacedBunker, ...]
    unplaced: tuple[UnplacedBunker, ...]

    def __post_init__(self):
        flagged = [b.id for b in self.bunkers if b.status in FLAGGED_STATUSES]
        if flagged:
            raise ValueError(f"bunkers signalés dans le sable du parcours : {flagged}")

    __hash__ = None

    @property
    def empty_rule(self) -> str:
        return EMPTY_RULE

    def of_hole(self, order: int) -> tuple[PlacedBunker, ...]:
        return tuple(b for b in self.bunkers if b.hole == order)

    def flagged(self) -> tuple[UnplacedBunker, ...]:
        """Non posés dont la pose signalée a été retirée du sable."""
        return tuple(u for u in self.unplaced if u.pose is not None)

    def summary(self) -> dict:
        """Comptes pour un rapport : posés par statut, famille et rôle ; non
        posés par étape et raison (un bunker compte pour chacune de ses raisons)."""
        return {"placed": len(self.bunkers),
                "by_status": dict(Counter(b.status for b in self.bunkers)),
                "by_family_role": dict(Counter(f"{b.family}/{b.role}" for b in self.bunkers)),
                "flagged": dict(Counter(u.pose.status for u in self.flagged())),
                "unplaced": len(self.unplaced),
                "unplaced_by_reason": dict(Counter(f"{u.stage}/{r}" for u in self.unplaced for r in u.reasons)),
                "empty_holes": list(self.empty_holes)}


def _construction_record(case: dict, bunker: dict) -> dict:
    """Relevé de la pose de construction (ou de flanc réussie) d'un bunker."""
    if bunker["family"] == "pot":
        return next(r for r in case["records"] if r.get("family") == "pot" and r.get("role") == bunker["role"])
    return next(r for r in case["records"] if r.get("id") == bunker["id"])


def _construction_checks(record: dict) -> tuple[str, ...]:
    """Contrôles en échec d'une pose de construction (vide si légale) :
    ``rejection_checks`` (``pose_record``) ou ``failures`` (grappe de pots)."""
    if record["status"] == POSE_FOUND:
        return ()
    checks = record.get("rejection_checks") or (record.get("measurements") or {}).get("failures")
    return tuple(checks) if checks else (str(record.get("reason", record["status"])),)


def assemble(seed: int, final: list[dict], green_rows: list[dict], fairway_rows: list[dict]) -> CourseBunkers:
    """``CourseBunkers`` du parcours final ``final`` (``fairway_phase``) et des
    relevés des deux phases (forme de l'étude)."""
    flank = {(r["hole_order"], r["id"]): r for r in green_rows}
    units = {(r["hole_order"], i): r["status"] for r in fairway_rows if r["status"] in fairway.PLACED
             for i in r["ids"]}
    placed, unplaced = [], []
    for case in final:
        order = case["hole"].order
        for b in case["bunkers"]:
            key = (order, b["id"])
            reasons, site = (), None
            if b["role"] == "landing":
                status = units[key]
            else:
                record = _construction_record(case, b)
                site, checks = record.get("site"), _construction_checks(record)
                if key in flank:
                    status = FLANK_STATUSES[flank[key]["status"]]
                    # Flanc en échec : pose de construction gardée, puis issues des θ.
                    reasons = (*checks, *flank[key].get("reasons", {})) if status == FLANK_FAILED else ()
                else:
                    status, reasons = (BUILT, ()) if record["status"] == POSE_FOUND else (REJECTED, checks)
            pose = PlacedBunker(b["id"], order, b["family"], b["role"], b["cells"], status)
            if status in FLAGGED_STATUSES:
                stage = STAGE_GREEN if status == FLANK_FAILED else STAGE_CONSTRUCTION
                # Ordre des raisons : contrôles en échec de la pose de
                # construction, puis (flanc) issues des θ dans l'ordre où ils
                # ont été essayés (clés du ``Counter`` de ``green_phase``) ;
                # doublons retirés en gardant la première occurrence.
                reasons = tuple(dict.fromkeys(reasons))
                if not reasons:
                    raise ValueError(f"trou {order}, bunker {b['id']!r} : pose signalée {status!r} "
                                     "sans aucune raison (relevé de construction ou de flanc incomplet)")
                unplaced.append(UnplacedBunker(order, b["family"], b["role"], stage, reasons,
                                               ids=(b["id"],), site=site, pose=pose))
            else:
                placed.append(pose)
        unplaced.extend(UnplacedBunker(order, m["family"], m["role"], STAGE_CONSTRUCTION, (str(m["reason"]),),
                                       site=m.get("site")) for m in case["missing"])
        unplaced.extend(UnplacedBunker(order, UNIT_FAMILIES[r["kind"]], "landing", STAGE_FAIRWAY, (r["reason"],),
                                       ids=tuple(r["ids"]))
                        for r in fairway_rows if r["hole_order"] == order and r["status"] == fairway.NOT_PLACED)
    empty = tuple(c["hole"].order for c in final if c["spec"]["empty_selected"])
    return CourseBunkers(seed, empty, tuple(placed), tuple(unplaced))


def place_bunkers(layout, dressing, seed: int, *, water=None) -> CourseBunkers:
    """Bunkers du parcours ``layout`` (``CourseLayout`` : trous, taille de carte)
    habillé ``dressing`` (``CourseDressing``, style compris).

    ``water`` : ``WaterMask`` de la carte (sable refusé sur l'eau) ou ``None``
    (aucune eau connue). Valeurs adoptées partout (trous vides par trou,
    coin extérieur des doglegs, haricots de green de la famille remplacée,
    recul max 12 b, contrôle d'accès).
    """
    context = BunkerContext.of(layout, dressing, water=water)
    built = course_cases(context, seed)
    green_rows, green_after = green.green_phase(built, context, seed)
    fairway_rows, final = fairway.fairway_phase(built, green_after, context)
    return assemble(seed, final, green_rows, fairway_rows)


def place_bunkers_json(data, dressing) -> CourseBunkers:
    """Bunkers du parcours décrit par le JSON 3.x ``data`` (étape 2, sans
    re-router, comme ``dress_course_json``) habillé ``dressing`` (en
    général ``dress_course_json(data, style)``) : tracé, seed u64 du routage
    et eau réelle (``WaterMask``, celle que lit l'habillage) relus par
    ``course_input_from_json`` (``CourseJsonError`` si le JSON n'est pas
    habillable), puis ``place_bunkers``. Même JSON, même habillage : mêmes
    bunkers."""
    course = course_input_from_json(data)
    return place_bunkers(course.layout, dressing, course.seed, water=course.water)
