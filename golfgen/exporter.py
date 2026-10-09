"""Export JSON du parcours de golf."""

from __future__ import annotations

import base64
import json
import math
import os
from pathlib import Path
from typing import Any
import uuid

import numpy as np

from . import __version__
from .routing.model import ElasticHole, NineLayout, WalkingLink
from .routing.muirfield import MuirfieldResult, outer_start
from .routing.sites import WATER_LEVEL


def terrain_block(heightmap: np.ndarray) -> dict[str, Any]:
    """Bloc ``terrain`` du format 3.0 (sans ``water_level``) : heightmap encodée
    en base64 uint8 (normalisée sur [min, max]), min/max arrondis à 2 décimales."""
    h, w = heightmap.shape
    elev_min = float(heightmap.min())
    elev_max = float(heightmap.max())

    if elev_max - elev_min < 1e-10:
        uint8_data = np.zeros((h, w), dtype=np.uint8)
    else:
        normalized = (heightmap - elev_min) / (elev_max - elev_min)
        uint8_data = (normalized * 255).astype(np.uint8)

    encoded = base64.b64encode(uint8_data.tobytes()).decode('ascii')

    return {
        "width": w,
        "height": h,
        "elevation": {
            "encoding": "base64_uint8",
            "data": encoded,
            "min_elevation": round(elev_min, 2),
            "max_elevation": round(elev_max, 2),
        }
    }


FORMAT_VERSION = "3.0"
BLOCK_M = 3                     # 1 bloc Minecraft = 3 m (model.py)
# Sens de rotation du nine extérieur selon ``Plan.direction`` : +1 = angle
# croissant autour du centre de carte ; repère carte en y vers le bas (rendus
# SVG et viewer), donc sens horaire à l'écran.
TURNS = {1: "clockwise", -1: "counterclockwise"}


def _r2(value: float) -> float:
    return round(float(value), 2)


def _point(point) -> dict[str, float]:
    return {"x": _r2(point.x), "y": _r2(point.y)}


def _hole_v3(hole: ElasticHole, nine: str) -> dict[str, Any]:
    return {
        "id": hole.order,
        "nine": nine,
        "par": hole.par,
        "length": _r2(hole.length),
        "width": _r2(hole.width),
        "tee": _point(hole.tee),
        "green": _point(hole.green),
        "doglegs": [_point(p) for p in hole.doglegs],
    }


def _link_v3(link: WalkingLink) -> dict[str, Any]:
    def end(order: int | None) -> int | str:
        return "clubhouse" if order is None else order
    return {
        "from": end(link.from_hole_order),
        "to": end(link.to_hole_order),
        "length": _r2(link.length),
    }


def _nine_stats(nine: NineLayout) -> tuple[dict[str, Any], float, int]:
    holes = math.fsum(hole.length for hole in nine.holes)
    links = math.fsum(link.length for link in nine.links)
    par = sum(hole.par for hole in nine.holes)
    stats = {"holes_length": _r2(holes), "links_length": _r2(links),
             "total": _r2(holes + links), "par": par}
    return stats, holes + links, par


def muirfield_to_dict(result: MuirfieldResult, heightmap: np.ndarray, *, seed: int,
                      seed_input: str | None = None) -> dict[str, Any]:
    """Parcours Muirfield au format JSON 3.0 (référence : ``docs/format-3.0.md``).

    Fonction pure : ni I/O, ni état global, ni aléa. ``seed`` est l'entier
    signé 64 bits tel que saisi (exporté en chaîne, exact au-delà de 2^53),
    PAS sa forme u64 donnée au routage ; ce doit être un ``int`` Python
    (``int(seed)`` à l'appel : un ``np.int64`` est refusé) ; ``seed_input`` le
    texte d'origine, ou None. Unités : blocs (1 bloc = 3 m),
    flottants arrondis à 2 décimales. Le résultat passe ``json.dumps`` tel quel."""
    if isinstance(seed, bool) or not isinstance(seed, int):
        raise TypeError("seed doit être un entier")
    if seed_input is not None and not isinstance(seed_input, str):
        raise TypeError("seed_input doit être une chaîne ou None")
    width, height = float(result.width), float(result.height)
    if heightmap.shape != (int(height), int(width)):
        raise ValueError(f"relief {heightmap.shape}, carte attendue {int(height)}×{int(width)}")

    layout = result.layout
    if width > height:
        orientation = "landscape"
    elif width < height:
        orientation = "portrait"
    else:
        orientation = "square"

    front, front_total, front_par = _nine_stats(layout.front)
    back, back_total, back_par = _nine_stats(layout.back)
    outer = "front" if outer_start(result.pattern) == 1 else "back"
    direction = TURNS[result.direction]
    opposite = TURNS[-result.direction]

    holes = [_hole_v3(hole, name)
             for name, nine in (("front", layout.front), ("back", layout.back))
             for hole in nine.holes]
    holes.sort(key=lambda hole: hole["id"])

    return {
        "metadata": {
            "version": FORMAT_VERSION,
            "generator": f"golfgen {__version__}",
            "seed": str(seed),
            "seed_input": seed_input,
            "pattern": {"requested": result.requested_pattern, "resolved": result.pattern},
            "orientation": orientation,
            "short_side": _r2(min(width, height)),
            "long_side": _r2(max(width, height)),
            "width": _r2(width),
            "height": _r2(height),
            "block_m": BLOCK_M,
            "stats": {
                "front": front,
                "back": back,
                "total": _r2(front_total + back_total),
                "par": front_par + back_par,
                "elapsed_seconds": _r2(result.elapsed_seconds),
                "relaunches": result.relaunches,
            },
        },
        "terrain": {**terrain_block(heightmap), "water_level": _r2(WATER_LEVEL)},
        "routing": {
            "clubhouse": {**_point(layout.clubhouse), "edge": result.clubhouse_edge},
            "direction": {
                "outer_nine": outer,
                "outer_turn": direction,
                "inner_nine": "back" if outer == "front" else "front",
                "inner_turn": opposite,
            },
            "holes": holes,
            "links": [_link_v3(link) for link in layout.links],
        },
    }


def write_json_atomic(path: str | Path, data: dict[str, Any]) -> None:
    """Écrit ``data`` en JSON (indenté, UTF-8) de façon atomique : fichier
    temporaire du même dossier, ``flush`` + ``os.fsync``, puis ``os.replace``.
    En cas d'échec, un fichier existant à ``path`` reste intact et aucun
    temporaire ne subsiste.

    Si ``path`` est un lien symbolique, le lien lui-même est remplacé par un
    fichier ordinaire (sa cible n'est pas modifiée). Le fichier est créé à
    neuf : ses permissions viennent de l'umask, pas d'un fichier existant."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.{uuid.uuid4().hex}.tmp")
    try:
        with open(tmp, "x", encoding="utf-8") as handle:
            json.dump(data, handle, indent=2, ensure_ascii=False)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise

