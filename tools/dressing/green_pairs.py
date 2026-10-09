"""Mesure des greens doubles (habillage, lot 1, round 0) : aucune règle de
production, seulement une calibration de la règle provisoire.

Règle provisoire mesurée, post-routage, sur chaque layout :

- paires (i, j), i < j, de greens NON consécutifs (j ≠ i + 1, donc 9/10
  exclu ; 1/18 reste éligible), hors paire 9/18 ;
- distance entre centres de greens dans une fourchette (référence [12, 30]
  blocs ; alternatives [10, 25], [15, 35], [12, 40]) ;
- forme : enveloppe convexe des deux greens, chaque green approché par un
  disque de rayon ``GREEN_RADIUS`` (polygone circonscrit) ;
- contrôles (tous évalués, rejets comptés par contrôle) :
  ``coeur`` écart ≥ 5 blocs au cœur (``buffered_axis(axe, width/2)``) de tout
  trou autre que i et j ; ``tees`` écart ≥ 5 blocs à chacun des 18 tees ;
  ``liaisons`` aucune liaison de ``layout.links`` ne traverse l'enveloppe, sauf
  celles qui partent du green i ou j ; ``clubhouse`` ≥ 10 blocs du clubhouse ;
  ``carte`` enveloppe entièrement dans la carte ;
- sélection gloutonne déterministe des paires valides triées
  (distance, i, j), au plus 2 paires, écart ≥ 5 blocs entre enveloppes.

Layouts : rounds ``rc-30`` (300×400) et ``land-30`` (400×300), patrons
muirfield et muirfield_inverse, seeds 1–30, même routage que
``tools.muirfield.run_muirfield`` (``load_terrain`` + ``build_course``, largeurs
``variable``). Chaque layout routé est mis en cache (non versionné) sous
``output/green_pairs/cache/`` : une relance ne reroute que les seeds absentes,
ce qui permet de découper le routage (``--round``, ``--pattern``,
``--seeds``, ``--route-only``). Le rapport et la planche ne sont écrits que
sur l'ensemble demandé.

Sorties sous ``tools/dressing/output/green_pairs/`` : ``report.json``
(versionné, synthèse), ``planche.png`` et ``tile_*.png`` (non versionnés).

    .venv/bin/python -m tools.dressing.green_pairs --round rc-30 --route-only
    .venv/bin/python -m tools.dressing.green_pairs
"""

from __future__ import annotations

import argparse
from collections import Counter
import json
import math
from pathlib import Path
import subprocess
import time

from golfgen.routing.geometry import (
    _point_polygon_distance,
    _segment_crosses_polygon,
    build_hole_geometry,
    polygon_gap,
)
from golfgen.routing.model import CourseLayout
from golfgen.routing.muirfield import PATTERNS, build_course, outer_start
from golfgen.routing.sites import WATER_LEVEL, load_terrain
from tools.muirfield.render_readable import render_readable_svg
from tools.muirfield.run_muirfield import OUTPUT_ROOT as MUIRFIELD_OUTPUT, ROBUSTNESS_SEEDS


Point = tuple[float, float]

OUTPUT_DIR = Path(__file__).resolve().parent / "output" / "green_pairs"
CACHE_DIR = OUTPUT_DIR / "cache"

# rounds de robustesse du runner Muirfield : (largeur, hauteur, préfixe)
ROUNDS = {"rc-30": (300, 400, "rc"), "land-30": (400, 300, "land")}

GREEN_RADIUS = 5.0
DISK_VERTICES = 16
CORE_GAP = 5.0
TEE_GAP = 5.0
CLUBHOUSE_MIN = 10.0
PAIR_GAP = 5.0
MAX_PAIRS = 2
EXCLUDED_PAIRS = frozenset({(9, 18)})
REFERENCE_RANGE = "12-30"
RANGES = {"12-30": (12.0, 30.0), "10-25": (10.0, 25.0),
          "15-35": (15.0, 35.0), "12-40": (12.0, 40.0)}
CONTROLS = ("coeur", "tees", "liaisons", "clubhouse", "carte")
HIST_STEP = 5
HIST_MAX = 60
EPSILON = 1e-7

SELECTED_COLORS = ("#ff7b00", "#d2a8ff")
VALID_COLOR = "#f0f6fc"


# --- géométrie --------------------------------------------------------------

def convex_hull(points) -> tuple[Point, ...]:
    """Enveloppe convexe (chaîne monotone), sens trigonométrique, sans
    points colinéaires."""
    pts = sorted(set((float(x), float(y)) for x, y in points))
    if len(pts) <= 2:
        return tuple(pts)

    def cross(o, a, b):
        return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])

    lower, upper = [], []
    for p in pts:
        while len(lower) >= 2 and cross(lower[-2], lower[-1], p) <= 0:
            lower.pop()
        lower.append(p)
    for p in reversed(pts):
        while len(upper) >= 2 and cross(upper[-2], upper[-1], p) <= 0:
            upper.pop()
        upper.append(p)
    return tuple(lower[:-1] + upper[:-1])


def disk(center: Point, radius: float = GREEN_RADIUS, vertices: int = DISK_VERTICES):
    """Polygone régulier CIRCONSCRIT au disque (le contient entièrement)."""
    outer = radius / math.cos(math.pi / vertices)
    return [(center[0] + outer * math.cos(2 * math.pi * k / vertices),
             center[1] + outer * math.sin(2 * math.pi * k / vertices))
            for k in range(vertices)]


def green_center(layout: CourseLayout, order: int) -> Point:
    green = layout.holes[order - 1].green
    return (green.x, green.y)


def pair_hull(layout: CourseLayout, i: int, j: int) -> tuple[Point, ...]:
    return convex_hull(disk(green_center(layout, i)) + disk(green_center(layout, j)))


def eligible_pairs(layout: CourseLayout) -> list[tuple[int, int, float]]:
    """Toutes les paires (i, j, distance) non consécutives, hors 9/18."""
    orders = [hole.order for hole in layout.holes]
    out = []
    for a, i in enumerate(orders):
        for j in orders[a + 1:]:
            if j == i + 1 or (i, j) in EXCLUDED_PAIRS:
                continue
            out.append((i, j, math.dist(green_center(layout, i), green_center(layout, j))))
    return out


def pair_checks(layout: CourseLayout, i: int, j: int, hull=None,
                cores: dict[int, tuple[Point, ...]] | None = None) -> dict:
    """Chaque contrôle de la règle provisoire : ``{nom: (ok, mesure)}``."""
    hull = hull or pair_hull(layout, i, j)
    if cores is None:
        cores = {h.order: build_hole_geometry(h).core for h in layout.holes}
    core_gap = min(polygon_gap(hull, cores[h.order]) for h in layout.holes
                   if h.order not in (i, j))
    tee_gap = min(_point_polygon_distance((h.tee.x, h.tee.y), hull) for h in layout.holes)
    crossing = [
        [link.from_hole_order, link.to_hole_order] for link in layout.links
        if link.from_hole_order not in (i, j)
        and _segment_crosses_polygon((link.start.x, link.start.y),
                                     (link.end.x, link.end.y), hull)]
    clubhouse = _point_polygon_distance((layout.clubhouse.x, layout.clubhouse.y), hull)
    in_map = all(-EPSILON <= x <= layout.width + EPSILON
                 and -EPSILON <= y <= layout.height + EPSILON for x, y in hull)
    return {
        "coeur": (core_gap >= CORE_GAP - EPSILON, round(core_gap, 2)),
        "tees": (tee_gap >= TEE_GAP - EPSILON, round(tee_gap, 2)),
        "liaisons": (not crossing, crossing),
        "clubhouse": (clubhouse >= CLUBHOUSE_MIN - EPSILON, round(clubhouse, 2)),
        "carte": (in_map, in_map),
    }


def select_pairs(valid: list[dict], hulls: dict[tuple[int, int], tuple[Point, ...]],
                 max_pairs: int = MAX_PAIRS, gap: float = PAIR_GAP) -> tuple[list[dict], int]:
    """Glouton déterministe trié (distance, i, j) ; renvoie les paires
    retenues et le nombre de paires valides écartées pour écart < ``gap``
    avant d'atteindre ``max_pairs``."""
    chosen, blocked = [], 0
    for pair in sorted(valid, key=lambda p: (p["d"], p["i"], p["j"])):
        if len(chosen) >= max_pairs:
            break
        hull = hulls[(pair["i"], pair["j"])]
        if all(polygon_gap(hull, hulls[(c["i"], c["j"])]) >= gap - EPSILON for c in chosen):
            chosen.append(pair)
        else:
            blocked += 1
    return chosen, blocked


def loop_relation(i: int, j: int, outer_first: int) -> str:
    """``exterieure`` / ``interieure`` (même boucle) ou ``croisee``."""
    def outer(order):
        return (order <= 9) == (outer_first == 1)
    if outer(i) and outer(j):
        return "exterieure"
    if not outer(i) and not outer(j):
        return "interieure"
    return "croisee"


def evaluate_layout(layout: CourseLayout, outer_first: int, ranges=RANGES) -> dict:
    """Distances, candidats par fourchette, rejets par contrôle, sélection."""
    pairs = eligible_pairs(layout)
    lo = min(r[0] for r in ranges.values())
    hi = max(r[1] for r in ranges.values())
    cores = {h.order: build_hole_geometry(h).core for h in layout.holes}
    hulls, checks = {}, {}
    for i, j, d in pairs:
        if lo - EPSILON <= d <= hi + EPSILON:
            hulls[(i, j)] = pair_hull(layout, i, j)
            checks[(i, j)] = pair_checks(layout, i, j, hulls[(i, j)], cores)
    nn_eligible = {}
    for i, j, d in pairs:
        for a in (i, j):
            nn_eligible[a] = min(nn_eligible.get(a, math.inf), d)
    nn_any = {}
    for h in layout.holes:
        nn_any[h.order] = min(math.dist(green_center(layout, h.order), green_center(layout, o.order))
                              for o in layout.holes if o.order != h.order)
    per_range = {}
    for name, (rmin, rmax) in ranges.items():
        candidates = [(i, j, d) for i, j, d in pairs if rmin - EPSILON <= d <= rmax + EPSILON]
        fails = Counter()
        only = Counter()
        valid = []
        for i, j, d in candidates:
            failed = [c for c in CONTROLS if not checks[(i, j)][c][0]]
            fails.update(failed)
            if len(failed) == 1:
                only[failed[0]] += 1
            if not failed:
                valid.append({"i": i, "j": j, "d": round(d, 2)})
        chosen, blocked = select_pairs(valid, hulls)
        for pair in chosen:
            pair["boucle"] = loop_relation(pair["i"], pair["j"], outer_first)
        per_range[name] = {
            "candidates": len(candidates),
            "fails": {c: fails[c] for c in CONTROLS},
            "only_fail": {c: only[c] for c in CONTROLS},
            "valid": len(valid),
            "valid_pairs": valid,
            "blocked_by_pair_gap": blocked,
            "selected": chosen,
        }
    return {
        "pair_distances": [round(d, 2) for _, _, d in pairs],
        "nn_eligible": [round(nn_eligible[o], 2) for o in sorted(nn_eligible)],
        "nn_any": [round(nn_any[o], 2) for o in sorted(nn_any)],
        "ranges": per_range,
    }


def histogram(values, step: int = HIST_STEP, top: int = HIST_MAX) -> dict[str, int]:
    """Tranches ``[lo, lo + step)`` en blocs, clés à deux chiffres (ordre
    lexicographique = ordre numérique dans le JSON trié), puis ``top+``."""
    bins = {f"{lo:02d}-{lo + step:02d}": 0 for lo in range(0, top, step)}
    bins[f"{top}+"] = 0
    for value in values:
        lo = int(value // step) * step
        bins[f"{top}+" if value >= top else f"{lo:02d}-{lo + step:02d}"] += 1
    return bins


# --- routage (même mécanique que tools.muirfield.run_muirfield) -------------

def _set_name(round_name: str, pattern: str) -> str:
    return f"{round_name}_{pattern}"


def _cache_path(round_name: str, pattern: str, seed: int) -> Path:
    return CACHE_DIR / _set_name(round_name, pattern) / f"seed_{seed}.json"


def _runner_lengths(round_name: str, pattern: str) -> dict[int, list[float]]:
    """Longueurs de trous du report.json versionné du runner (contrôle de
    reproductibilité), ou ``{}``."""
    width, height, label = ROUNDS[round_name]
    path = MUIRFIELD_OUTPUT / f"{label}_{pattern}_{width}x{height}_30seeds" / "report.json"
    if not path.exists():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    return {r["seed"]: r["hole_lengths"] for r in data["reports"] if r["status"] == "succes"}


def route(round_name: str, pattern: str, seed: int) -> dict:
    """Layout routé (depuis le cache s'il existe), avec son contexte."""
    path = _cache_path(round_name, pattern, seed)
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    width, height, _ = ROUNDS[round_name]
    heightmap = load_terrain(seed, width, height)
    t0 = time.perf_counter()
    result = build_course(seed, pattern, heightmap, width=width, height=height,
                          width_mode="variable")
    elapsed = time.perf_counter() - t0
    entry = {
        "round": round_name, "pattern": result.pattern, "seed": seed,
        "width": width, "height": height,
        "outer_first": outer_start(result.pattern),
        "violations": len(result.violations),
        "elapsed_seconds": round(elapsed, 3),
        "outer_ring": [list(p) for p in result.outer_ring],
        "inner_ring": [list(p) for p in result.inner_ring],
        "layout": result.layout.to_dict(),
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(entry), encoding="utf-8")
    print(f"{round_name} {pattern} seed {seed}: routé en {elapsed:.1f} s", flush=True)
    return entry


# --- rendu ------------------------------------------------------------------

def render_tile(entry: dict, evaluation: dict, range_name: str, path: Path) -> Path:
    layout = CourseLayout.from_dict(entry["layout"])
    data = evaluation["ranges"][range_name]
    overlays = []
    chosen = {(p["i"], p["j"]) for p in data["selected"]}
    for pair in data["valid_pairs"]:
        if (pair["i"], pair["j"]) not in chosen:
            overlays.append((pair_hull(layout, pair["i"], pair["j"]), VALID_COLOR))
    for k, pair in enumerate(data["selected"]):
        overlays.append((pair_hull(layout, pair["i"], pair["j"]),
                         SELECTED_COLORS[k % len(SELECTED_COLORS)]))
    pairs = " · ".join(f"{p['i']}/{p['j']} d={p['d']:.0f} {p['boucle']}"
                       for p in data["selected"]) or "aucune"
    heightmap = load_terrain(entry["seed"], entry["width"], entry["height"])
    svg = render_readable_svg(
        layout, (), heightmap=heightmap, water_level=WATER_LEVEL,
        rings=(entry["outer_ring"], entry["inner_ring"]), overlays=overlays,
        title=(f"{entry['pattern']} {entry['round']} · {entry['width']}×{entry['height']} · "
               f"seed {entry['seed']} · greens doubles [{range_name}]"),
        subtitle=(f"retenues : {pairs}  |  {data['candidates']} candidate(s), "
                  f"{data['valid']} valide(s) (blanc = valide non retenue)"),
    )
    svg_path = path.with_suffix(".svg")
    svg_path.write_text(svg, encoding="utf-8")
    subprocess.run(["rsvg-convert", "-o", str(path), str(svg_path)], check=True)
    svg_path.unlink()
    return path


def planche_entries(results: list[tuple[dict, dict]], range_name: str) -> list[tuple[dict, dict]]:
    """Par jeu (round, patron) : la plus petite seed au maximum de paires
    retenues et la plus petite au minimum (déterministe, ≥ 4 vignettes dès
    que deux jeux sont présents)."""
    by_set: dict[str, list[tuple[dict, dict]]] = {}
    for entry, evaluation in results:
        by_set.setdefault(_set_name(entry["round"], entry["pattern"]), []).append((entry, evaluation))
    picked = []
    for name in sorted(by_set):
        items = sorted(by_set[name], key=lambda item: item[0]["seed"])
        count = [len(ev["ranges"][range_name]["selected"]) for _, ev in items]
        best = items[count.index(max(count))]
        worst = items[count.index(min(count))]
        picked.append(best)
        if worst is not best:
            picked.append(worst)
        elif len(items) > 1:
            picked.append(items[1] if items[0] is best else items[0])
    return picked


# --- synthèse ---------------------------------------------------------------

def _quantiles(values: list[float]) -> dict:
    if not values:
        return {}
    ordered = sorted(values)

    def q(p):
        rank = p * (len(ordered) - 1)
        low = int(rank)
        high = min(low + 1, len(ordered) - 1)
        return round(ordered[low] + (ordered[high] - ordered[low]) * (rank - low), 2)
    return {"min": ordered[0], "p10": q(0.1), "median": q(0.5), "p90": q(0.9), "max": ordered[-1]}


def summarize(results: list[tuple[dict, dict]], ranges=RANGES) -> dict:
    n = len(results)
    distances = [d for _, ev in results for d in ev["pair_distances"]]
    nn_eligible = [d for _, ev in results for d in ev["nn_eligible"]]
    nn_any = [d for _, ev in results for d in ev["nn_any"]]
    per_range = {}
    for name in ranges:
        data = [ev["ranges"][name] for _, ev in results]
        selected = [p for d in data for p in d["selected"]]
        counts = Counter(len(d["selected"]) for d in data)
        per_range[name] = {
            "bounds": list(ranges[name]),
            "layouts": n,
            "pct_ge1": round(100 * sum(1 for d in data if d["selected"]) / n, 1) if n else None,
            "pct_ge2": round(100 * sum(1 for d in data if len(d["selected"]) >= 2) / n, 1) if n else None,
            "selected_count_distribution": {str(k): counts.get(k, 0) for k in range(MAX_PAIRS + 1)},
            "candidates_total": sum(d["candidates"] for d in data),
            "candidates_mean": round(sum(d["candidates"] for d in data) / n, 2) if n else None,
            "valid_total": sum(d["valid"] for d in data),
            "valid_mean": round(sum(d["valid"] for d in data) / n, 2) if n else None,
            "fails_total": {c: sum(d["fails"][c] for d in data) for c in CONTROLS},
            "only_fail_total": {c: sum(d["only_fail"][c] for d in data) for c in CONTROLS},
            "blocked_by_pair_gap_total": sum(d["blocked_by_pair_gap"] for d in data),
            "selected_total": len(selected),
            "selected_loops": dict(sorted(Counter(p["boucle"] for p in selected).items())),
            "selected_distance": _quantiles([p["d"] for p in selected]),
        }
    return {
        "layouts": n,
        "pair_distance_histogram": histogram(distances),
        "pair_distance_quantiles": _quantiles(distances),
        "nn_eligible_histogram": histogram(nn_eligible),
        "nn_eligible_quantiles": _quantiles(nn_eligible),
        "nn_any_histogram": histogram(nn_any),
        "nn_any_quantiles": _quantiles(nn_any),
        "ranges": per_range,
    }


def _parse_seeds(text: str) -> tuple[int, ...]:
    if "-" in text:
        low, high = (int(v) for v in text.split("-"))
        return tuple(range(low, high + 1))
    return tuple(int(v) for v in text.split(","))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--round", choices=tuple(ROUNDS), default=None,
                        help="un seul round (défaut : rc-30 et land-30)")
    parser.add_argument("--pattern", choices=PATTERNS, default=None,
                        help="un seul patron (défaut : les deux)")
    parser.add_argument("--seeds", default=None, help="ex. 1-30 ou 3,7 (défaut : 1-30)")
    parser.add_argument("--route-only", action="store_true",
                        help="remplir le cache sans écrire de rapport ni de planche")
    parser.add_argument("--no-planche", action="store_true")
    args = parser.parse_args()
    rounds = (args.round,) if args.round else tuple(ROUNDS)
    patterns = (args.pattern,) if args.pattern else PATTERNS
    seeds = _parse_seeds(args.seeds) if args.seeds else ROBUSTNESS_SEEDS

    results, mismatches = [], []
    for round_name in rounds:
        for pattern in patterns:
            reference = _runner_lengths(round_name, pattern)
            for seed in seeds:
                entry = route(round_name, pattern, seed)
                layout = CourseLayout.from_dict(entry["layout"])
                lengths = [round(h.length, 1) for h in layout.holes]
                if seed in reference and reference[seed] != lengths:
                    mismatches.append(f"{round_name}/{pattern}/{seed}")
                if args.route_only:
                    continue
                results.append((entry, evaluate_layout(layout, entry["outer_first"])))
    if mismatches:
        print(f"ATTENTION : layouts différents du report.json du runner : {mismatches}")
    if args.route_only:
        return

    summary = {
        "rule": {
            "green_radius": GREEN_RADIUS, "disk_vertices": DISK_VERTICES,
            "core_gap": CORE_GAP, "tee_gap": TEE_GAP, "clubhouse_min": CLUBHOUSE_MIN,
            "pair_gap": PAIR_GAP, "max_pairs": MAX_PAIRS,
            "excluded_pairs": sorted(list(p) for p in EXCLUDED_PAIRS),
            "consecutive_excluded": "j = i + 1 (9/10 compris)",
            "reference_range": REFERENCE_RANGE,
            "ranges": {k: list(v) for k, v in RANGES.items()},
            "controls": list(CONTROLS),
        },
        "rounds": list(rounds), "patterns": list(patterns), "seeds": list(seeds),
        "runner_mismatches": mismatches,
        "overall": summarize(results),
        "by_set": {},
        "layouts": [],
    }
    for round_name in rounds:
        for pattern in patterns:
            subset = [(e, ev) for e, ev in results
                      if e["round"] == round_name and e["pattern"] == pattern]
            if subset:
                summary["by_set"][_set_name(round_name, pattern)] = summarize(subset)["ranges"]
    for entry, ev in results:
        summary["layouts"].append({
            "round": entry["round"], "pattern": entry["pattern"], "seed": entry["seed"],
            "ranges": {name: {"candidates": d["candidates"], "fails": d["fails"],
                              "valid": d["valid"], "selected": d["selected"]}
                       for name, d in ev["ranges"].items()},
        })

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    if not args.no_planche and results:
        tiles = []
        for entry, ev in planche_entries(results, REFERENCE_RANGE):
            path = OUTPUT_DIR / f"tile_{entry['round']}_{entry['pattern']}_seed_{entry['seed']}.png"
            tiles.append(str(render_tile(entry, ev, REFERENCE_RANGE, path)))
        subprocess.run(["magick", "montage", *tiles, "-tile", "4x", "-geometry", "+6+6",
                        "-background", "#0d1117", str(OUTPUT_DIR / "planche.png")], check=True)
        summary["planche"] = [Path(t).name for t in tiles]
    (OUTPUT_DIR / "report.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")
    for name, data in summary["overall"]["ranges"].items():
        print(f"[{name}] ≥1 {data['pct_ge1']} % · ≥2 {data['pct_ge2']} % · "
              f"candidats {data['candidates_total']} · valides {data['valid_total']} · "
              f"rejets {data['fails_total']} · boucles {data['selected_loops']}")


if __name__ == "__main__":
    main()
