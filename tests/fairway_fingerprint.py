"""Empreinte de B v1 (fairway, lot 2 R2) : hash des contours et des zones
de réception sur un échantillon fixe, figé AVANT la reprise du mécanisme
dans ``golfgen/dressing/fairway.py``, à partir de l'outil exploratoire du
R1 (colonne B, ``88e670c``, outil retiré depuis).

Échantillon : trous de l'instantané ``tests/data/dressing_holes_30x2.json``
(deux premiers trous, dans l'ordre de l'instantané, de chaque catégorie
par × coudes × cœur étroit ≤ 11 blocs : par 3, 4 et 5, avec et sans coude,
cœurs étroits compris) et trous fabriqués (deux coudes, cœur de 10) ; deux
styles ; seeds u64 ``SEEDS``. Par cas : sha256 des octets float64
little-endian du contour (forme comprise), des centres de zones et du
nombre de boucles. L'empreinte est comparée AU BIT PRÈS
(``tests/test_dressing_fairway.py``) : jamais relâchée en silence.

Empreinte de PRODUCTION (R2b, ``NECK_FINGERPRINT``) : même échantillon,
mêmes styles et seeds, même hash ; fairway complet (forme B v1 à col marqué
0,55 × zone plus profil en long du R3 et contournement) de la colonne ``K``
de l'outil des cols après les nits de sa revue (``aceac1d``, outil retiré
depuis), figée AVANT l'intégration de ``profile_neck`` au paquet ; greens
et départs : ``dress_course`` du trou seul (pas de green double).

Ces deux empreintes sont figées : les outils qui les ont produites n'existent
plus, elles ne se régénèrent pas.

Empreinte « fairway avec eau » (R4c, ``WATER_FINGERPRINT``) : fairway coupé
par ``dress_course`` AVEC le relief (``load_terrain``) sur tout
l'instantané 30x2 (60 parcours, seeds brutes, deux styles, trous seuls, pas
de green double), coupure de production ``FAIRWAY_WATER_CUT`` ; par trou,
sha256 des morceaux (octets float64 little-endian des contours et des
aires), des fragments retirés (aire, cause) et de la cause du vide ; un cas
par parcours et par style (``water_course_digest``). Figée au branchement
de la coupure (``tests/test_dressing_fairway_water.py``) ; régénérer exige
``--force`` et une raison.

    .venv/bin/python -m tests.fairway_fingerprint          # vérifie (eau)
    .venv/bin/python -m tests.fairway_fingerprint --force  # réécrit (eau)
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sys

import numpy as np

from golfgen.routing.geometry import build_hole_geometry
from golfgen.routing.model import ControlPoint, ElasticHole

DATA = Path(__file__).resolve().parent / "data"
SNAPSHOT = DATA / "dressing_holes_30x2.json"
FINGERPRINT = DATA / "fairway_b_v1_fingerprint.json"
NECK_FINGERPRINT = DATA / "fairway_neck_k_fingerprint.json"
WATER_FINGERPRINT = DATA / "fairway_water_fingerprint.json"
STYLES = ("links", "parkland")
SEEDS = (1, 5, 2 ** 64 - 1)
PER_CATEGORY = 2
NARROW = 11.0                   # blocs : cœur étroit

FABRICATED = {
    "par 4 droit": ElasticHole(order=2, par=4, tee=ControlPoint(50.0, 20.0),
                               green=ControlPoint(50.0, 150.0), width=14.0),
    "par 5 coudé": ElasticHole(order=7, par=5, tee=ControlPoint(40.0, 20.0),
                               doglegs=(ControlPoint(60.0, 105.0),),
                               green=ControlPoint(20.0, 175.0), width=16.0),
    "par 5, 2 coudes": ElasticHole(order=11, par=5, tee=ControlPoint(40.0, 20.0),
                                   doglegs=(ControlPoint(70.0, 90.0),
                                            ControlPoint(50.0, 160.0)),
                                   green=ControlPoint(80.0, 210.0), width=15.0),
    "par 4, 2 coudes": ElasticHole(order=13, par=4, tee=ControlPoint(20.0, 20.0),
                                   doglegs=(ControlPoint(35.0, 70.0),
                                            ControlPoint(20.0, 110.0)),
                                   green=ControlPoint(45.0, 140.0), width=12.0),
    "par 3 étroit": ElasticHole(order=9, par=3, tee=ControlPoint(10.0, 10.0),
                                green=ControlPoint(60.0, 40.0), width=10.0),
    "par 4 étroit": ElasticHole(order=4, par=4, tee=ControlPoint(30.0, 20.0),
                                green=ControlPoint(30.0, 150.0), width=11.0),
}


def sample_holes() -> list[tuple[str, ElasticHole]]:
    """``(étiquette, trou)`` de l'échantillon, ordre fixe."""
    data = json.loads(SNAPSHOT.read_text(encoding="utf-8"))
    taken: dict[tuple, int] = {}
    out = []
    for course in data["courses"]:
        for raw in course["holes"]:
            hole = ElasticHole.from_dict(raw)
            key = (hole.par, len(hole.doglegs), hole.width <= NARROW)
            if taken.get(key, 0) >= PER_CATEGORY:
                continue
            taken[key] = taken.get(key, 0) + 1
            label = (f"{course['size']}/{course['seed']}#{hole.order} par {hole.par}, "
                     f"{len(hole.doglegs)} coude(s), cœur {hole.width:g}")
            out.append((label, hole))
    out.extend((f"fabriqué {name}", hole) for name, hole in FABRICATED.items())
    return out


def case_digest(outline: np.ndarray, zones, loops: int) -> str:
    outline = np.ascontiguousarray(outline, dtype="<f8")
    h = hashlib.sha256()
    h.update(np.asarray(outline.shape, dtype="<i8").tobytes())
    h.update(outline.tobytes())
    h.update(np.asarray(zones, dtype="<f8").tobytes())
    h.update(np.asarray([loops], dtype="<i8").tobytes())
    return h.hexdigest()


def fingerprint(shape) -> dict:
    """``shape(hole, core, style, seed) -> (contour, zones, boucles)`` ;
    empreinte par cas et globale."""
    cases = {}
    for label, hole in sample_holes():
        core = np.asarray(build_hole_geometry(hole).core, dtype=float)
        for style in STYLES:
            for seed in SEEDS:
                outline, zones, loops = shape(hole, core, style, seed)
                cases[f"{label} | {style} | {seed}"] = case_digest(outline, zones, loops)
    total = hashlib.sha256("\n".join(f"{k}={v}" for k, v in cases.items()).encode())
    return {"digest": total.hexdigest(), "cases": cases}


def single_hole_dressing(hole, style, seed):
    """Habillage du trou seul (``dress_course``) et ses obstacles."""
    from types import SimpleNamespace

    from golfgen.dressing import dress_course
    from golfgen.dressing.fairway_profile import fairway_obstacles
    dressing = dress_course(SimpleNamespace(layout=SimpleNamespace(holes=(hole,))), seed=seed,
                            style=style)
    return dressing, fairway_obstacles(dressing.holes, dressing.green_pairs)


def water_corpus():
    """``(étiquette, seed, trous, relief)`` de l'instantané 30x2, dans son
    ordre ; relief ``load_terrain`` (cache)."""
    from golfgen.routing.sites import load_terrain
    data = json.loads(SNAPSHOT.read_text(encoding="utf-8"))
    for course in data["courses"]:
        width, height = map(int, course["size"].split("x"))
        holes = tuple(ElasticHole.from_dict(h) for h in course["holes"])
        yield (f"{course['size']}/{course['seed']}", course["seed"], holes,
               load_terrain(course["seed"], width, height))


def water_dressings():
    """``(étiquette, style, trous, relief, habillage)`` : ``dress_course``
    avec le relief, trous seuls, chaque parcours de ``water_corpus`` et
    chaque style."""
    from types import SimpleNamespace

    from golfgen.dressing import dress_course
    for label, seed, holes, relief in water_corpus():
        for style in STYLES:
            yield (label, style, holes, relief,
                   dress_course(SimpleNamespace(layout=SimpleNamespace(holes=holes)),
                                seed=seed, style=style, relief=relief))


def water_hole_digest(hd) -> str:
    """sha256 du fairway coupé d'un trou : morceaux (forme et octets
    float64 LE du contour, aire), fragments retirés (aire, cause), cause du
    vide."""
    h = hashlib.sha256()
    h.update(np.asarray([len(hd.fairway)], dtype="<i8").tobytes())
    for shape in hd.fairway:
        outline = np.ascontiguousarray(shape.outline, dtype="<f8")
        h.update(np.asarray(outline.shape, dtype="<i8").tobytes())
        h.update(outline.tobytes())
        h.update(np.asarray([shape.area], dtype="<f8").tobytes())
    h.update(np.asarray([len(hd.fairway_removed)], dtype="<i8").tobytes())
    for piece in hd.fairway_removed:
        h.update(np.asarray([piece.area], dtype="<f8").tobytes())
        h.update(piece.cause.encode() + b"\0")
    h.update(repr(hd.fairway_empty_cause).encode())
    return h.hexdigest()


def water_course_digest(dressing) -> str:
    """sha256 des empreintes de ses trous (``water_hole_digest``), par numéro."""
    lines = (f"{order}={water_hole_digest(hd)}" for order, hd in sorted(dressing.holes.items()))
    return hashlib.sha256("\n".join(lines).encode()).hexdigest()


def water_fingerprint(dressings) -> dict:
    """Empreinte « fairway avec eau » : ``dressings`` = ``(étiquette,
    style, …, habillage)`` (``water_dressings``) ; cas par parcours et par
    style, et globale."""
    cases = {f"{row[0]} | {row[1]}": water_course_digest(row[-1]) for row in dressings}
    total = hashlib.sha256("\n".join(f"{k}={v}" for k, v in cases.items()).encode())
    return {"digest": total.hexdigest(), "cases": cases}


def load(path: Path = FINGERPRINT) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


WATER_NOTE = ("fairway avec eau (dress_course avec le relief, coupure "
              "FAIRWAY_WATER_CUT : bande 2, aire minimale 5 blocs²), instantané "
              "30x2, deux styles, figée au R4c du lot 2 ; voir "
              "tests/fairway_fingerprint.py")


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    path, got = WATER_FINGERPRINT, water_fingerprint(water_dressings())
    head = {"note": WATER_NOTE, "styles": list(STYLES)}
    if "--force" in argv or not path.exists():
        path.write_text(json.dumps({**head, **got}, indent=2, ensure_ascii=False) + "\n",
                        encoding="utf-8")
        print(f"écrit : {path} ({len(got['cases'])} cas)")
        return 0
    ok = got["digest"] == load(path)["digest"]
    print(f"{'identique' if ok else 'DIFFÉRENTE'} ({len(got['cases'])} cas)")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
