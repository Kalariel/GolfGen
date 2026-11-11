"""Phase fairway : bunkers de fairway posés après ceux des greens, avec
recul le long de l'axe (round R5).

Chemin validé de l'étude (décision B2, greens d'abord) : sur l'état des
greens (``green_phase.green_phase(...)[1]``), trous dans l'ordre, les
unités de fairway du trou (``landing_units`` : grappe des pots d'appel,
bloc rigide, ou haricot de retombée), dans l'ordre de la liste du trou,
sont contrôlées UNE fois, à leur pose, contre tout ce qui est déjà posé
(bunkers de green des 18 trous, unités de fairway précédentes).

Légalité d'une position (``trial``, relevé complet sans court-circuit) :

- contrôles existants de la famille (``existing_check``) : pots =
  ``legality.pot_measurements`` avec ``hd`` (carte, herbe entre pots, marges
  green/départs, voisins, au moins 4 cases sur 8 dans le fairway par pot) ;
  haricot = ``legality.pose_record`` (carte, marges contour et raster
  green/départs, voisins) ; eau refusée si le contexte en porte
  (``None`` : étude au bit près) ;
- aucun contact (arête/coin, ``ContactIndex``) avec un bunker déjà posé ;
- règle des 18 b (``distance.too_close``) : sable à sable strictement sous
  ``MIN_GREEN_DISTANCE_BLOCKS`` d'un bunker de green devant/côté du MÊME
  trou (``distance.front_side_greens``) : refus ;
- accès : la pose ne fait passer aucun green à
  ``fail`` (accès de 2 blocs, pots de green exemptés, ``access.sand_of`` /
  ``ACCESS_EXEMPT`` ; domaine du trou recalculé avec l'unité, autres trous
  dont le domaine contient une case de l'unité recontrôlés) ; un green déjà
  ``fail`` avant la pose ne compte pas.

Recul (``green_phase.offsets``) : translation rigide ``rint(P(s0 − k) −
P(s0))`` le long de l'axe du trou, k = 0, 1, … ``max_slide`` blocs
(``ADOPTED_MAX_SLIDE_BLOCKS`` = 12) vers le départ ; translation déjà
essayée sautée ; première position légale gardée ; aucune : unité non posée
(``NOT_PLACED``, raison ``not_placed_reason``). Haricot de retombée de
dogleg (coin extérieur) : pas de recul, contrôle en place seulement. Unité
reculée : relevé de pose à la position reculée (``slid_record``), position
d'origine et recul à part.

Sortie (forme de l'étude) : ``(rows, cases)`` ; ``rows`` = un relevé par
unité, ``cases`` = parcours final (bunkers de green et de fairway posés,
unités non posées retirées avec leur relevé).

Carte, cibles et eau viennent du contexte (aucune taille figée).
"""

from __future__ import annotations

import numpy as np

from golfgen.dressing.bunkers import access, distance
from golfgen.dressing.bunkers.cases import interactions
from golfgen.dressing.bunkers.green_phase import offsets, translated
from golfgen.dressing.bunkers.legality import POSE_FOUND, ContactIndex, pose_record, pot_measurements

MIN_GREEN_DISTANCE_BLOCKS = distance.MIN_GREEN_DISTANCE_BLOCKS
# Valeurs adoptées (validé par l'utilisateur le 2026-11-01, planche_recul_fairway.png) :
# recul max 12 b, contrôle d'accès des bunkers de fairway gardé.
ADOPTED_MAX_SLIDE_BLOCKS = 12
POTS, STRAIGHT, DOGLEG = "grappe_pots", "haricot_droit", "haricot_dogleg"
# Haricot de retombée : spec ``haricot_landing`` -> unité ; toute autre valeur refusée.
LANDING_KINDS = {"straight": STRAIGHT, "outside": DOGLEG}
SLIDING_KINDS = (POTS, STRAIGHT)
IN_PLACE, SLID, NOT_PLACED = "pose_en_place", "recule", "non_pose"
PLACED = (IN_PLACE, SLID)
# Échecs d'une position.
DISTANCE_FAILURE, ACCESS_FAILURE, CONTACT_FAILURE = "distance_green", "acces_green", "contact_bunker"
# Raison d'une unité non posée (priorité de ``not_placed_reason``).
REASON_DISTANCE, REASON_ACCESS, REASON_OTHER = "18b", "acces", "autre"
RECORD_FAILURE_KEYS = ("reason", "rejection_checks")


def landing_units(case: dict) -> list[dict]:
    """Unités de fairway du trou, ordre de la liste : grappe de pots, haricots de retombée."""
    landing = [b for b in case["bunkers"] if b["role"] == "landing"]
    units, pot_ids = [], [b["id"] for b in landing if b["family"] == "pot"]
    for b in landing:
        if b["family"] == "pot":
            if b["id"] == pot_ids[0]:
                units.append({"kind": POTS, "ids": pot_ids})
        elif b["family"] == "haricot":
            landing_kind = case["spec"].get("haricot_landing")
            if landing_kind not in LANDING_KINDS:
                raise ValueError(f"t{case['hole'].order} {b['id']} : haricot_landing {landing_kind!r} inconnu "
                                 f"(attendu : {', '.join(LANDING_KINDS)})")
            units.append({"kind": LANDING_KINDS[landing_kind], "ids": [b["id"]]})
        else:
            raise ValueError(f"t{case['hole'].order} {b['id']} : famille de fairway inconnue {b['family']!r}")
    return units


def existing_check(kind: str, bunkers: list[dict], case: dict, context) -> tuple[list[str], dict]:
    """Contrôles existants de la famille ; (échecs, champs de pose du relevé à cette position)."""
    hole = case["hole"]
    if kind == POTS:
        group = tuple(np.asarray(b["cells"], dtype=int) for b in bunkers)
        measured = pot_measurements(group, hole.order, context.limits, context.targets, hd=case["hd"],
                                    water=context.water)
        failures = list(measured["failures"])
        return failures, {"status": "rejected" if failures else POSE_FOUND, "measurements": measured}
    (b,) = bunkers
    record = pose_record({"id": b["id"], "family": "haricot", "role": "landing"}, kind, b, hole.order,
                         context.limits, context.targets, water=context.water)
    failures = [] if record["status"] == POSE_FOUND else list(record["rejection_checks"])
    return failures, {k: record[k] for k in ("status", "measurements", *RECORD_FAILURE_KEYS) if k in record}


def unit_record(record: dict, unit: dict) -> bool:
    """Relevé de pose de l'unité (pots d'appel : un relevé partagé par la grappe)."""
    return record.get("id") in unit["ids"] or (unit["kind"] == POTS and record.get("family") == "pot"
                                               and record.get("role") == "landing")


def slid_record(record: dict, unit: dict, moved: list[dict], pose: dict, k: int, offset) -> dict:
    """Relevé à la position reculée ; position d'origine (``origin_position``) et recul (``slide``) à part."""
    position = dict(pose)
    if unit["kind"] == POTS:
        position["cells"] = [np.asarray(b["cells"], dtype=int).tolist() for b in moved]
    keys = (*position, *RECORD_FAILURE_KEYS)
    origin = {key: record[key] for key in dict.fromkeys(keys) if key in record}
    out = {key: value for key, value in record.items() if key not in RECORD_FAILURE_KEYS}
    offset = np.asarray(offset, dtype=int)
    return {**out, **position, "origin_position": origin,
            "slide": {"slide_blocks": int(k), "offset": offset.tolist(),
                      "offset_norm_blocks": round(float(np.linalg.norm(offset)), 4)}}


def course_sand(cases: list[dict]) -> np.ndarray:
    """Masque d'obstacles de l'accès (pots de green exemptés), tous les trous."""
    return access.sand_of([b for c in cases for b in c["bunkers"]])


def hole_access(case: dict, sand: np.ndarray) -> str:
    return access.access_status(case["hole"], case["hd"], case["bunkers"], sand)["status"]


def access_statuses(cases: list[dict]) -> dict[int, str]:
    sand = course_sand(cases)
    return {c["hole"].order: hole_access(c, sand) for c in cases}


def with_unit(cases: list[dict], index: int, bunkers: list[dict], original_order: list[str]) -> list[dict]:
    """Parcours avec l'unité ajoutée à son trou, bunkers dans l'ordre de la liste d'origine."""
    case = cases[index]
    rank = {identity: i for i, identity in enumerate(original_order)}
    merged = sorted([*case["bunkers"], *bunkers], key=lambda b: rank[b["id"]])
    return [*cases[:index], {**case, "bunkers": merged, "pairs": interactions(merged)}, *cases[index + 1:]]


def domain_key(case: dict) -> set:
    """Cases du domaine d'accès contrôlé du trou (vide : sans fairway ou bande vide)."""
    return access.domain_cells(case["hole"], case["hd"], case["bunkers"])


def touched(cases: list[dict], index: int, cells, domains: dict[int, set]) -> list[int]:
    """Trous dont la décision d'accès peut changer avec ces cases : le trou, et les domaines touchés."""
    keys = {tuple(c) for c in np.asarray(cells, dtype=int).reshape(-1, 2).tolist()}
    return [i for i, c in enumerate(cases) if i == index or keys.intersection(domains[c["hole"].order])]


def trial(cases: list[dict], index: int, unit: dict, bunkers: list[dict], original_order: list[str],
          context, contacts: ContactIndex, greens: list[dict], before: dict[int, str],
          domains: dict[int, set]) -> dict:
    """Tous les contrôles d'une position (aucun court-circuit : relevé complet)."""
    case = cases[index]
    cells = np.vstack([np.asarray(b["cells"], dtype=int).reshape(-1, 2) for b in bunkers])
    failures, pose = existing_check(unit["kind"], bunkers, case, context)
    touching = contacts.contacts(cells)
    if touching:
        failures.append(CONTACT_FAILURE)
    # Décision sur la distance exacte ; ``nearest`` (arrondie au millième) pour le relevé seul.
    near = distance.nearest(cells, greens)
    if distance.too_close(cells, greens, MIN_GREEN_DISTANCE_BLOCKS):
        failures.append(DISTANCE_FAILURE)
    course = with_unit(cases, index, bunkers, original_order)
    sand = course_sand(course)
    checked = [course[i] for i in touched(course, index, cells, domains)]
    newly = [c["hole"].order for c in checked
             if before[c["hole"].order] != access.FAIL and hole_access(c, sand) == access.FAIL]
    if newly:
        failures.append(ACCESS_FAILURE)
    return {"failures": failures, "nearest_front_side_green": near, "newly_failing_greens": newly,
            "contacts": [[c["order"], c["bunker"]] for c in touching], "pose": pose}


def not_placed_reason(trials: list[dict]) -> str:
    """18b : la distance échoue partout ; sinon acces : distance ou accès partout, accès au moins
    une fois ; sinon autre."""
    if all(DISTANCE_FAILURE in t["failures"] for t in trials):
        return REASON_DISTANCE
    if all({DISTANCE_FAILURE, ACCESS_FAILURE} & set(t["failures"]) for t in trials) and \
            any(ACCESS_FAILURE in t["failures"] for t in trials):
        return REASON_ACCESS
    return REASON_OTHER


def first_index(trials: list[dict], ignored: frozenset = frozenset()) -> int | None:
    return next((i for i, t in enumerate(trials) if not set(t["failures"]) - ignored), None)


def front_side_greens(case: dict) -> list[dict]:
    """Bunkers de green devant/côté du trou, avec leur ``site`` et ``hole_order``."""
    hole = case["hole"]
    return [{**g, "hole_order": hole.order}
            for g in distance.front_side_greens(hole, case["hd"], case["bunkers"], case["records"])]


def fairway_phase(built: list[dict], green_after: list[dict], context) -> tuple[list[dict], list[dict]]:
    """Unités de fairway posées sur l'état des greens ; ``(rows, cases)``.

    ``built`` : cas construits (``cases.course_cases``, bunkers de fairway à leur
    pose de construction) ; ``green_after`` : état des greens
    (``green_phase.green_phase(...)[1]``) ; ``context`` : ``BunkerContext``
    (carte, cibles, eau). Valeurs adoptées : recul max
    ``ADOPTED_MAX_SLIDE_BLOCKS``, règle des 18 b, contrôle d'accès.
    """
    max_slide = ADOPTED_MAX_SLIDE_BLOCKS
    cases, rows = list(green_after), []
    # Décisions d'accès et domaines tenus à jour pose après pose (seuls les trous touchés changent).
    before = access_statuses(cases)
    domains = {c["hole"].order: domain_key(c) for c in cases}
    for index, source in enumerate(built):
        order = [b["id"] for b in source["bunkers"]]
        by_id = {b["id"]: b for b in source["bunkers"]}
        greens = front_side_greens(cases[index])
        for unit in landing_units(source):
            original = [by_id[i] for i in unit["ids"]]
            contacts = ContactIndex([(c["hole"].order, b) for c in cases for b in c["bunkers"]])
            cells = np.vstack([np.asarray(b["cells"], dtype=int).reshape(-1, 2) for b in original])
            steps = offsets(source["hole"], cells, max_slide if unit["kind"] in SLIDING_KINDS else 0)
            trials, chosen = [], None
            for k, offset in steps:
                moved = [translated(b, offset) for b in original]
                checked = trial(cases, index, unit, moved, order, context, contacts, greens, before, domains)
                trials.append({"slide_blocks": k, "offset": offset.tolist(), **checked})
                if not checked["failures"]:
                    chosen = (k, offset, moved, checked["pose"])
                    break
            without_access = first_index(trials, frozenset({ACCESS_FAILURE}))
            row = {"hole_order": source["hole"].order, "ids": unit["ids"], "kind": unit["kind"],
                   "slides": unit["kind"] in SLIDING_KINDS, "max_slide_blocks": max_slide,
                   "trials": trials, "origin_failures": trials[0]["failures"],
                   "origin_nearest_front_side_green": trials[0]["nearest_front_side_green"],
                   # Relevé : première position légale sans le contrôle d'accès.
                   "first_legal_without_access_blocks": (None if without_access is None
                                                         else trials[without_access]["slide_blocks"])}
            if chosen is None:
                row.update(status=NOT_PLACED, reason=not_placed_reason(trials), slide_blocks=None, offset=None)
                records = [r for r in cases[index]["records"] if not unit_record(r, unit)]
                cases[index] = {**cases[index], "records": records}
            else:
                k, offset, moved, pose = chosen
                row.update(status=IN_PLACE if k == 0 else SLID, reason=None, slide_blocks=k, offset=offset.tolist(),
                           offset_norm_blocks=round(float(np.linalg.norm(offset)), 4))
                cases = with_unit(cases, index, moved, order)
                if k:
                    records = [slid_record(r, unit, moved, pose, k, offset) if unit_record(r, unit) else r
                               for r in cases[index]["records"]]
                    cases[index] = {**cases[index], "records": records}
                sand = course_sand(cases)
                for i in touched(cases, index, np.vstack([b["cells"] for b in moved]), domains):
                    before[cases[i]["hole"].order] = hole_access(cases[i], sand)
                domains[source["hole"].order] = domain_key(cases[index])
            row["access_affected"] = row["first_legal_without_access_blocks"] != row["slide_blocks"]
            rows.append(row)
    return rows, cases
