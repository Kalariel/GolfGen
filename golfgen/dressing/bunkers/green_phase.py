"""Phase green : bunkers de green seuls, haricots « devant » re-posés en
flanc d'entrée (round R4).

Chemin validé de l'étude (décision B2, greens d'abord) : à partir des cas
de ``cases.course_cases``, les bunkers de fairway (rôle ``landing`` : pots
d'appel, haricots de retombée) sont retirés (``stripped``) ; ils n'arrêtent
pas le glissement du flanc et ne comptent ni dans le domaine d'accès ni
comme obstacles pendant la pose des greens. Puis ``green_phase`` re-pose,
trous dans l'ordre, les haricots de green du site « devant »
(``green_targets``), chacun voyant les poses précédentes ; les autres
bunkers de green (pots, haricots côté et derrière) gardent leur pose. Sans
la règle de la retombée proche (B2 : la distance de 18 b de la phase
fairway la remplace).

Pose de flanc (``flank_pose``) :

- côté : tiré sur un flux dédié et neuf par trou (``side_draw`` : haricots
  ``HARICOT_FLANK_STREAM``, haricots de la famille remplacée
  ``REPLACED_FLANK_STREAM``), sauf pour un haricot « devant » d'un green
  qui porte un haricot « côté actuel » : côté opposé à lui
  (``devant_side``) ;
- θ de 0° (direction d'entrée, ``-Axis.tangents[-1]``) à 180° du côté
  retenu, pas de 5° ; P = intersection la plus lointaine du rayon issu du
  centre du green avec son contour ; tangente lissée (corde de ±2 blocs)
  et normale extérieure ;
- orientation (``oriented_tangent``) : creux du haricot vers le green ;
- glissement vers l'extérieur de 0 à 40 blocs par pas de 0,25 : tout
  contact (arête/coin, ``ContactIndex``) avec un autre bunker du parcours
  arrête le glissement de ce θ ; une pose sans contact rejetée par
  ``FlankAudit`` (inclusion, marges, topologie, carte, voisins, eau) est
  sautée ; première pose légale gardée ;
- accès de 2 blocs vers le green (``access.access_status``, pots de green
  exemptés) : premier θ dont la pose légale passe ; aucun : échec, la pose
  construite reste ;
- option a′ : si le green est déjà bloqué par le sable sans ce bunker
  (``access.access_without``), les coupables de ce blocage sont retirés
  des obstacles du contrôle d'accès (statut ``POSED_IGNORING``).

Sortie (forme de l'étude, que la phase fairway enchaîne) : ``(rows,
after)`` ; ``rows`` = un relevé par bunker re-posé (``flank_pose``),
``after`` = cas sans bunkers de fairway, poses de flanc remplacées
(``replaced`` : bunkers, relevé ``flank_record``, ``pairs``).

Production : carte ``context.limits``, style de l'habillage pour les sites
du haricot de garde, ``context.water`` dans ``FlankAudit`` (``None`` :
aucune eau connue).
"""

from __future__ import annotations

from collections import Counter
import time

import numpy as np

from golfgen.dressing.bunkers import access
from golfgen.dressing.bunkers.beans import bean_cells, bean_outline, concave_side
from golfgen.dressing.bunkers.cases import interactions
from golfgen.dressing.bunkers.errors import BunkerError
from golfgen.dressing.bunkers.legality import POSE_FOUND, ContactIndex, FlankAudit
from golfgen.dressing.bunkers.placements import green_reference
from golfgen.dressing.bunkers.selection import is_replaced
from golfgen.dressing.bunkers.raster import ONE_PIECE, convex_hull, to_world
from golfgen.dressing.bunkers.sites import candidates
from golfgen.dressing.fairway import Axis
from golfgen.dressing.green import points_in_polygon
from golfgen.dressing.rng import REPLACED_GREEN_FLANK, REPLACED_GREEN_STREAM, RNG_LABEL

# Flux du côté : [seed, RNG_LABEL, trou, HARICOT_FLANK_STREAM], générateur
# neuf par trou ; « FLKH » en ASCII (0x464C4B31, « FLK1 », des organiques :
# retiré, ``rng.RETIRED_STREAMS``).
HARICOT_FLANK_STREAM = 0x464C4B48
# Haricot « devant » de la famille remplacée : flux dédié
# [seed, RNG_LABEL, trou, REPLACED_GREEN_STREAM, REPLACED_GREEN_FLANK].
REPLACED_FLANK_STREAM = (REPLACED_GREEN_STREAM, REPLACED_GREEN_FLANK)
# θ depuis la direction d'entrée (-Axis.tangents[-1]) vers le côté retenu.
THETA_STEP_DEG = 5.0
THETA_MAX_DEG = 180.0
THETAS_DEG = tuple(np.arange(0.0, THETA_MAX_DEG + 1e-9, THETA_STEP_DEG).tolist())
# Glissement le long de la normale extérieure.
OFFSETS = np.arange(0.0, 40.01, 0.25)
# Tangente lissée : corde entre les points du contour à ±2 blocs de P.
SMOOTHING_HALF_WINDOW = 2.0
PASS = access.PASS
NO_LEGAL_POSE = "no_legal_pose_0_to_40_blocks"
CONTACT_STOP = "bunker_contact_stops_slide"
POSED_IGNORING = "acces_controle_sans_fautifs"
POSED = (POSE_FOUND, POSED_IGNORING)
FAILED = "échec"
# Haricots de green re-posés en flanc : site « devant » ; côté opposé au
# haricot « côté actuel » du même green s'il existe.
SITE = "devant"
COTE_SITE = "côté actuel"
DRAWN, OPPOSITE = "tirage", "opposé au haricot côté"
SOURCE = "green_phase.flank_pose"


# --- repère au contour du green ---------------------------------------------------------

def side_draw(seed: int, order: int, stream: int | tuple[int, ...]) -> str:
    """Côté tiré : « droite » si le flux du trou tire < 0,5 (``stream`` : un
    mot, ou plusieurs pour les haricots de la famille remplacée)."""
    words = stream if isinstance(stream, tuple) else (stream,)
    rng = np.random.default_rng([seed, RNG_LABEL, order, *words])
    return "droite" if rng.random() < 0.5 else "gauche"


def ray_direction(forward, theta_deg: float, side: str) -> np.ndarray:
    """θ depuis l'entrée (-forward), vers +across à droite, -across à gauche."""
    forward = np.asarray(forward, dtype=float)
    across = np.array((-forward[1], forward[0]))
    sign = 1.0 if side == "droite" else -1.0
    theta = np.radians(theta_deg)
    return np.cos(theta) * -forward + np.sin(theta) * sign * across


def ray_hits(outline, center, direction) -> list[tuple[float, float]]:
    """(distance sur le rayon, abscisse curviligne) des intersections avec le contour."""
    outline = np.asarray(outline, dtype=float)
    center, direction = np.asarray(center, dtype=float), np.asarray(direction, dtype=float)
    ends = np.roll(outline, -1, axis=0)
    lengths = np.linalg.norm(ends - outline, axis=1)
    starts = np.concatenate(([0.0], np.cumsum(lengths)[:-1]))
    hits = []
    for p, q, length, start in zip(outline, ends, lengths, starts):
        d = q - p
        det = direction[0] * -d[1] + direction[1] * d[0]
        if abs(det) < 1e-12:
            continue
        rel = p - center
        t = (rel[0] * -d[1] + rel[1] * d[0]) / det
        s = (direction[0] * rel[1] - direction[1] * rel[0]) / det
        if t > 0 and 0 <= s < 1:
            hits.append((float(t), float(start + s * length)))
    return hits


def point_at(outline, arc: float) -> np.ndarray:
    """Point du contour fermé à l'abscisse curviligne ``arc`` (modulo le périmètre)."""
    outline = np.asarray(outline, dtype=float)
    ends = np.roll(outline, -1, axis=0)
    lengths = np.linalg.norm(ends - outline, axis=1)
    arc = float(arc) % lengths.sum()
    starts = np.concatenate(([0.0], np.cumsum(lengths)[:-1]))
    i = int(np.searchsorted(starts, arc, side="right") - 1)
    return outline[i] + (arc - starts[i]) / lengths[i] * (ends[i] - outline[i])


def smoothed_frame(outline, arc: float, half_window: float = SMOOTHING_HALF_WINDOW
                   ) -> tuple[np.ndarray, np.ndarray]:
    """Tangente (sens du contour) et normale extérieure lissées en ``arc``."""
    outline = np.asarray(outline, dtype=float)
    chord = point_at(outline, arc + half_window) - point_at(outline, arc - half_window)
    norm = np.linalg.norm(chord)
    if norm < 1e-9:
        raise BunkerError("corde de lissage dégénérée")
    tangent = chord / norm
    x, y = outline[:, 0], outline[:, 1]
    area = 0.5 * float(np.sum(x * np.roll(y, -1) - np.roll(x, -1) * y))
    # Contour direct (aire > 0) : l'extérieur est à droite du sens de parcours.
    normal = np.array((tangent[1], -tangent[0])) * (1.0 if area > 0 else -1.0)
    return tangent, normal


def contour_frame(outline, center, direction, half_window: float = SMOOTHING_HALF_WINDOW) -> dict:
    """Point P (intersection la plus lointaine du rayon), tangente et normale lissées."""
    hits = ray_hits(outline, center, direction)
    if not hits:
        raise BunkerError("rayon sans intersection avec le contour")
    distance, arc = max(hits)
    tangent, normal = smoothed_frame(outline, arc, half_window)
    return {"point": np.asarray(center, dtype=float) + distance * np.asarray(direction, dtype=float),
            "arc": arc, "tangent": tangent, "normal": normal, "crossings": len(hits)}


# --- formes re-posées -------------------------------------------------------------------

def green_haricot_site(case: dict, bunker: dict) -> str | None:
    """Site tiré d'un haricot de green (relevé de pose), ``None`` sinon."""
    if bunker["family"] != "haricot" or bunker["role"] != "green":
        return None
    record = next((r for r in case["records"] if r.get("id") == bunker["id"]), None)
    return None if record is None else record.get("site")


def is_devant(case: dict, bunker: dict) -> bool:
    return green_haricot_site(case, bunker) == SITE


def cote_side(case: dict) -> str | None:
    """Côté de l'axe d'entrée du haricot « côté actuel » du trou, ``None`` sans lui."""
    cote = [b for b in case["bunkers"] if green_haricot_site(case, b) == COTE_SITE]
    if not cote:
        return None
    if len(cote) > 1:
        raise ValueError(f"t{case['hole'].order} : plusieurs haricots côté")
    forward = Axis.of(case["hole"]).tangents[-1]
    across = np.array((-forward[1], forward[0]))
    offset = float((np.asarray(cote[0]["cells"], dtype=float).mean(axis=0) + 0.5
                    - np.asarray(case["hd"].green.center)) @ across)
    if offset == 0.0:
        raise ValueError(f"t{case['hole'].order} : haricot côté sur l'axe d'entrée")
    return "droite" if offset > 0 else "gauche"


def devant_side(case: dict) -> str | None:
    """Côté imposé au haricot « devant » : opposé au haricot côté, ``None`` sinon (tirage)."""
    side = cote_side(case)
    return None if side is None else ("gauche" if side == "droite" else "droite")


def haricot_shape(case: dict, bunker: dict, seed: int, context) -> dict:
    """Forme exacte du haricot « devant » construit, vérifiée contre sa pose."""
    hole, hd = case["hole"], case["hd"]
    sites = candidates(hole, style=context.style, green=hd.green, tees=hd.tees, seed=seed)
    replaced = is_replaced(case["spec"])
    found = green_reference(hole, hd, seed, sites, replaced=replaced)
    if found is None:
        raise ValueError(f"t{hole.order} : tirage du haricot introuvable")
    bean = found["bean"]
    local = bean_outline(bean)
    if not np.allclose(to_world(local, bunker["center"], bunker["tangent"]), bunker["outline"], atol=1e-9) \
            or not np.array_equal(bean_cells(bean, bunker["center"], bunker["tangent"], outline=local),
                                  bunker["cells"]):
        raise ValueError(f"t{hole.order} : haricot actuel non reproduit")
    side = concave_side(local)
    declared = -1 if bean.mirror else 1
    forced = devant_side(case)
    return {"family": "haricot", "layout": "haricot", "order": hole.order,
            "length_blocks": round(float(np.ptp(local[:, 0])), 4), "scale": float(bean.scale),
            "bean": bean, "local": local,
            "side_stream": REPLACED_FLANK_STREAM if replaced else HARICOT_FLANK_STREAM,
            "side": forced, "side_rule": OPPOSITE if forced else DRAWN,
            "concave_sign": side["sign"],
            "concave_side": {**side, "declared_sign": declared, "agrees_with_bean": side["sign"] == declared},
            "cells_of": lambda center, tangent: bean_cells(bean, center, tangent, outline=local)}


def oriented_tangent(shape: dict, frame: dict) -> tuple[np.ndarray, str]:
    """Tangente de pose (creux du haricot vers le green) et sa règle."""
    inward = -frame["normal"]
    toward = float(shape["concave_sign"])
    tangent = frame["tangent"]
    # to_world : y local -> (-t_y, t_x) ; retournement si ce côté ne regarde pas le green.
    if toward * (np.array((-tangent[1], tangent[0])) @ inward) < 0:
        tangent = -tangent
    return tangent, "creux"


# --- glissement et pose -----------------------------------------------------------------

def slide(shape: dict, frame: dict, tangent, audit: FlankAudit, contacts: ContactIndex
          ) -> tuple[dict | None, dict | None]:
    """Glissement le long de la normale : (première pose légale, arrêt par contact)."""
    for distance in OFFSETS:
        center = frame["point"] + distance * frame["normal"]
        outline = to_world(shape["local"], center, tangent)
        cells = shape["cells_of"](center, tangent)
        touching = contacts.contacts(cells)
        if touching:
            return None, {"offset_blocks": float(distance), "contacts": touching}
        position = {"center": center, "tangent": np.asarray(tangent, dtype=float), "outline": outline,
                    "cells": cells}
        failure, record, topology = audit.check(position)
        if failure is None:
            return {"position": position, "offset_blocks": float(distance), "record": record,
                    "topology": topology}, None
    return None, None


def replaced(case: dict, bunker_id: str, position: dict, record: dict | None = None) -> dict:
    """Copie du trou avec la seule pose ``bunker_id`` remplacée."""
    bunkers = [{**b, **position} if b["id"] == bunker_id else b for b in case["bunkers"]]
    records = list(case["records"])
    if record is not None:
        index = next(i for i, r in enumerate(records) if r.get("id") == bunker_id)
        records[index] = record
    return {**case, "bunkers": bunkers, "records": records, "pairs": interactions(bunkers)}


def concave_toward_green(outline, inward) -> bool:
    """La baie (enveloppe convexe moins forme, pas de 0,1 bloc) est-elle côté green ?"""
    outline = np.asarray(outline, dtype=float)
    hull = convex_hull(outline)
    low, high = outline.min(axis=0), outline.max(axis=0)
    x, y = np.meshgrid(np.arange(low[0], high[0], 0.1), np.arange(low[1], high[1], 0.1), indexing="ij")
    points = np.column_stack((x.ravel(), y.ravel()))
    in_hull, in_shape = points_in_polygon(points, hull), points_in_polygon(points, outline)
    bay = points[in_hull & ~in_shape]
    return bool((bay.mean(axis=0) - points[in_shape].mean(axis=0)) @ np.asarray(inward) > 0)


def fold_deg(first, second) -> float:
    """Angle entre deux directions non orientées, dans [0, 90]."""
    cosine = abs(float(np.dot(first, second)) / (np.linalg.norm(first) * np.linalg.norm(second)))
    return float(np.degrees(np.arccos(min(1.0, cosine))))


def fairway_cells(hd) -> np.ndarray:
    """Cases dont le centre est dans l'union du fairway du trou."""
    polygons = [np.asarray(f.outline) for f in hd.fairway]
    vertices = np.vstack(polygons)
    low, high = np.floor(vertices.min(axis=0)).astype(int), np.ceil(vertices.max(axis=0)).astype(int)
    x, z = np.meshgrid(np.arange(low[0], high[0]), np.arange(low[1], high[1]), indexing="ij")
    cells = np.column_stack((x.ravel(), z.ravel()))
    inside = np.zeros(len(cells), dtype=bool)
    for polygon in polygons:
        inside |= points_in_polygon(cells + .5, polygon)
    return cells[inside]


def occupancy(cells, fairway: set) -> dict:
    """Part du sable sur le fairway (relevé, aucun seuil)."""
    sand = set(map(tuple, cells))
    if not sand:
        raise BunkerError("empreinte sable vide")
    on_fairway = sorted(sand & fairway)
    return {"sand_blocks": len(sand), "sand_on_fairway_blocks": len(on_fairway),
            "fraction_on_fairway": len(on_fairway) / len(sand)}


PRESENCE_KEYS = ("sand_blocks", "sand_on_fairway_blocks", "fraction_on_fairway")


def flank_pose(case: dict, bunker: dict, cases: list[dict], context, *, seed: int, shape: dict) -> dict:
    """Balayage θ du côté retenu ; premier θ légal qui passe l'accès, sinon échec.

    ``cases`` : parcours en cours (poses précédentes comprises).
    """
    start = time.perf_counter()
    hole, hd = case["hole"], case["hd"]
    side = shape.get("side") or side_draw(seed, hole.order, shape["side_stream"])
    forward = Axis.of(hole).tangents[-1]
    center, outline = np.asarray(hd.green.center), np.asarray(hd.green.outline)
    others = [(c["hole"].order, b) for c in cases for b in c["bunkers"]
              if not (c["hole"].order == hole.order and b["id"] == bunker["id"])]
    contacts = ContactIndex(others)
    audit = FlankAudit(context, hole.order)
    # Obstacles du contrôle d'accès : pots de green exemptés (access.sand_of).
    other_sand = access.sand_of([b for _, b in others])
    without = access.access_without(cases, hole.order, bunker["id"])
    preblocked = without["status"] == access.FAIL and without["reason"] == access.SAND_FAILURE
    ignored = [{k: c[k] for k in ("hole_order", "id", "label")} for c in without["culprits"]] if preblocked else []
    if ignored:
        # Option a′ : sable des coupables du blocage retiré du contrôle d'accès seulement.
        skip = {(c["hole_order"], c["id"]) for c in ignored}
        other_sand = access.sand_of([b for order, b in others if (order, b["id"]) not in skip])
    tried, chosen = [], None
    for theta in THETAS_DEG:
        frame = contour_frame(outline, center, ray_direction(forward, theta, side))
        tangent, rule = oriented_tangent(shape, frame)
        legal, stop = slide(shape, frame, tangent, audit, contacts)
        if stop is not None:
            tried.append({"theta_deg": theta, "status": CONTACT_STOP, "contact_offset_blocks": stop["offset_blocks"],
                          "contacts": [[c["order"], c["bunker"]] for c in stop["contacts"]]})
            continue
        if legal is None:
            tried.append({"theta_deg": theta, "status": NO_LEGAL_POSE})
            continue
        trial = replaced(case, bunker["id"], legal["position"])
        checked = access.access_status(hole, hd, trial["bunkers"],
                                       np.vstack((other_sand, legal["position"]["cells"])))
        tried.append({"theta_deg": theta, "status": checked["status"], "reason": checked["reason"],
                      "offset_blocks": legal["offset_blocks"]})
        if checked["status"] == PASS:
            chosen = {**legal, "frame": frame, "tangent": tangent, "theta_deg": theta, "flip_rule": rule}
            break
    seconds = time.perf_counter() - start
    fairway = {tuple(map(int, p)) for p in fairway_cells(hd).tolist()} if hd.fairway else set()
    old = occupancy(np.asarray(bunker["cells"]).tolist(), fairway)
    described = {"family": shape["family"], "layout": shape["layout"], "length_blocks": shape["length_blocks"],
                 "scale": shape["scale"], "concave_side": shape["concave_side"], "side_rule": shape["side_rule"]}
    row = {"hole_order": hole.order, "id": bunker["id"], "side": side, **described,
           "theta_tried": len(tried), "trials": tried, "pose_seconds": seconds,
           "green_preblocked": preblocked, "access_without": without, "access_ignored_culprits": ignored,
           "old_fairway_presence": {k: old[k] for k in PRESENCE_KEYS}}
    if chosen is None:
        reasons = Counter(t["status"] if t["status"] != access.FAIL else t["reason"] for t in tried)
        reason = ("aucun θ du côté tiré : pose légale passant l'accès2blocs sans les coupables du blocage introuvable"
                  if preblocked else "aucun θ du côté tiré : pose légale passant l'accès2blocs introuvable")
        row.update(status=FAILED, reason=reason, reasons=dict(reasons), position=None)
        return row
    position, measured = chosen["position"], chosen["record"]["measurements"]
    new = occupancy(position["cells"].tolist(), fairway)
    inward = -chosen["frame"]["normal"]
    row.update(status=POSED_IGNORING if preblocked else POSE_FOUND, theta_deg=chosen["theta_deg"],
               offset_blocks=chosen["offset_blocks"],
               contour_point=[round(float(v), 4) for v in chosen["frame"]["point"]],
               contour_crossings=chosen["frame"]["crossings"],
               normal=[round(float(v), 6) for v in chosen["frame"]["normal"]],
               tangent=[round(float(v), 6) for v in chosen["tangent"]],
               flip_rule=chosen["flip_rule"],
               local_x_vs_contour_tangent_deg=round(fold_deg(chosen["tangent"], chosen["frame"]["tangent"]), 2),
               green_contour_gap_blocks=measured["green_contour_gap_blocks"],
               green_raster_gap_blocks=measured["green_raster_gap_blocks"],
               tee_contour_gap_blocks=measured["tee_contour_gap_blocks"],
               tee_raster_gap_blocks=measured["tee_raster_gap_blocks"],
               access_pass=True, topology=chosen["topology"],
               new_fairway_presence={k: new[k] for k in PRESENCE_KEYS},
               record=chosen["record"], position=position)
    row["topology_pass"] = row["topology"] == ONE_PIECE
    # Contrôle indépendant dans le monde : baie (enveloppe moins forme) côté green.
    row["concave_toward_green"] = concave_toward_green(position["outline"], inward)
    return row


def flank_record(row: dict, bunker: dict, previous: dict) -> dict:
    """Relevé de la nouvelle pose dans le parcours « après »."""
    return {**row["record"], "id": bunker["id"], "family": "haricot", "role": "green",
            "source": SOURCE, "drawn_site": previous.get("site"),
            "layout": row["layout"], "length_blocks": row["length_blocks"], "scale": row["scale"]}


# --- phase green ------------------------------------------------------------------------

def green_targets(case: dict) -> list[dict]:
    """Bunkers re-posés du trou : haricots « devant », ordre de la liste du trou."""
    return [b for b in case["bunkers"] if is_devant(case, b)]


def stripped(case: dict) -> dict:
    """Copie du trou sans ses bunkers de rôle landing (relevés conservés)."""
    bunkers = [b for b in case["bunkers"] if b["role"] != "landing"]
    return {**case, "bunkers": bunkers, "pairs": interactions(bunkers)}


def green_phase(cases: list[dict], context, seed: int) -> tuple[list[dict], list[dict]]:
    """Bunkers de green seuls, flanc des haricots « devant ».

    Trous dans l'ordre de ``cases`` : chaque pose voit les bunkers des trous
    précédents déjà re-posés et ceux des suivants à leur pose construite ;
    dans un trou, ordre de ``green_targets`` (figé sur le trou d'origine),
    chaque pose voyant les précédentes. ``(rows, after)``.
    """
    cases = [stripped(c) for c in cases]
    rows, after = [], list(cases)
    for index, case in enumerate(cases):
        for bunker in green_targets(case):
            shape = haricot_shape(case, bunker, seed, context)
            row = flank_pose(case, bunker, after, context, seed=seed, shape=shape)
            rows.append(row)
            if row["position"] is not None:
                previous = next(r for r in case["records"] if r.get("id") == bunker["id"])
                after[index] = case = replaced(after[index], bunker["id"], row["position"],
                                               flank_record(row, bunker, previous))
    return rows, after


# --- recul rigide le long de l'axe (phase fairway) ----------------------------------------

def station(axis: Axis, point) -> float:
    """Abscisse curviligne du point de l'axe le plus proche de ``point``."""
    point = np.asarray(point, dtype=float)
    rel = point - axis.points[:-1]
    t = np.clip(np.einsum("ij,ij->i", rel, axis.tangents), 0.0, axis.lengths)
    closest = axis.points[:-1] + t[:, None] * axis.tangents
    index = int(np.argmin(np.linalg.norm(closest - point, axis=1)))
    return float(axis.starts[index] + t[index])


def offsets(hole, cells, max_slide: int) -> list[tuple[int, np.ndarray]]:
    """Reculs k = 0..max_slide et translations entières, doublons d'arrondi écartés."""
    axis = Axis.of(hole)
    s0 = station(axis, np.asarray(cells, dtype=float).reshape(-1, 2).mean(axis=0) + 0.5)
    ks = np.arange(0, int(max_slide) + 1, dtype=float)
    points, _ = axis.at(np.concatenate(([s0], s0 - ks)))
    out, seen = [], set()
    for k, p in zip(ks, points[1:]):
        offset = np.rint(p - points[0]).astype(int)
        if tuple(offset) in seen:
            continue
        seen.add(tuple(offset))
        out.append((int(k), offset))
    return out


def translated(bunker: dict, offset) -> dict:
    """Translation rigide (cases, contour, centre) d'un bunker."""
    offset = np.asarray(offset, dtype=int)
    out = {**bunker, "cells": np.asarray(bunker["cells"], dtype=int) + offset}
    for key in ("outline", "center"):
        if bunker.get(key) is not None:
            out[key] = np.asarray(bunker[key], dtype=float) + offset
    return out
