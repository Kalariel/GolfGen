"""
Validate the GA fitness function against a reference golf course.

Usage:
    python tools/validate_fitness.py --course tools/pebble_beach.json
    python tools/validate_fitness.py --course tools/pebble_beach.json --seed 42
"""
import argparse
import json
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from golfgen.config import CourseConfig
from golfgen.ga import GeneticOptimizer


def load_holes(path: str) -> tuple[str, list[dict]]:
    with open(path) as f:
        data = json.load(f)
    course_name = data.get("course", path)
    raw_holes = data["holes"]

    holes = []
    for h in raw_holes:
        tee = h["tee"]
        green = h["green"]
        wps = h.get("waypoints", [tee, green])
        holes.append({
            "id": h["id"],
            "par": h["par"],
            "tee": tuple(tee),
            "green": tuple(green),
            "waypoints": [tuple(wp) for wp in wps],
            "fairway_width": h.get("fairway_width", 12),
        })
    return course_name, holes


def par_summary(holes: list[dict]) -> str:
    counts = {3: 0, 4: 0, 5: 0}
    for h in holes:
        counts[h["par"]] = counts.get(h["par"], 0) + 1
    return f"{counts[3]}×par3  {counts[4]}×par4  {counts[5]}×par5"


def main():
    parser = argparse.ArgumentParser(description="Validate GA fitness on a reference course")
    parser.add_argument("--course", required=True, help="Path to reference course JSON")
    parser.add_argument("--seed", type=int, default=42, help="Seed for GA config (affects clubhouse position)")
    args = parser.parse_args()

    course_name, holes = load_holes(args.course)

    config = CourseConfig(seed=args.seed)
    optimizer = GeneticOptimizer(config, heightmap=None)

    scores = optimizer.evaluate_holes(holes)

    n = len(holes)
    n_target = {3: round(n * 4 / 18), 4: round(n * 10 / 18), 5: round(n * 4 / 18)}
    target_str = f"cible {n_target[3]}/{n_target[4]}/{n_target[5]}"

    from golfgen.utils import polyline_length
    import math

    # Compute direction circular variance for display
    angles = []
    for h in holes:
        tx, ty = h["tee"]
        gx, gy = h["green"]
        angles.append(math.atan2(gy - ty, gx - tx))
    R = abs(sum(complex(math.cos(a), math.sin(a)) for a in angles)) / len(angles)
    circ_var = 1.0 - R

    # Return distance
    last_green = holes[-1]["green"]
    from golfgen.utils import distance
    ret_dist = distance(last_green, optimizer.clubhouse_pos)

    # Lengths per par
    len_by_par: dict[int, list[float]] = {3: [], 4: [], 5: []}
    for h in holes:
        par = h["par"]
        length = polyline_length(h["waypoints"])
        len_by_par.setdefault(par, []).append(length)
    avg = {p: (sum(v) / len(v) if v else 0) for p, v in len_by_par.items()}

    # Display
    w = 52
    print()
    print(f"{'=' * w}")
    print(f"  Validation fitness — {course_name}")
    print(f"{'=' * w}")
    print(f"  Trous : {n}   Seed clubhouse : {args.seed}")
    print(f"  Clubhouse : {optimizer.clubhouse_pos}")
    print(f"{'-' * w}")

    def row(label, detail, score, ok=None):
        icon = ("✓" if ok else "✗") if ok is not None else " "
        print(f"  {icon} {label:<28} {detail:<12}  {score:>10.1f}")

    row("Par distribution", par_summary(holes) + f"  ({target_str})", scores["par_distribution"],
        ok=scores["par_distribution"] == 0)
    avg3 = f"{avg[3]:.0f}" if avg[3] else "-"
    avg4 = f"{avg[4]:.0f}" if avg[4] else "-"
    avg5 = f"{avg[5]:.0f}" if avg[5] else "-"
    row("Longueur par par (blocs)", f"p3={avg3} p4={avg4} p5={avg5}", scores["hole_length"],
        ok=scores["hole_length"] < 500)
    row("Variété directions", f"var_circ={circ_var:.2f}", scores["direction_variety"],
        ok=circ_var >= 0.5)
    row("Retour clubhouse", f"dist={ret_dist:.0f} blocs", scores["return_to_clubhouse"],
        ok=15 <= ret_dist <= 50)
    print(f"{'-' * w}")
    row("Overlap", "", scores["overlap"])
    row("Compacité", "", scores["compacity"])
    row("Tee→Green continuité", "", scores["tee_green"])
    row("Consécutif", "", scores["consecutive"])
    row("Layout naturel", "", scores["natural_layout"])
    row("Concentration fairways", "", scores["fairway_concentration"])
    print(f"{'=' * w}")
    print(f"  {'TOTAL':<42}  {scores['total']:>10.1f}")
    print(f"{'=' * w}")
    print()
    print("  Un bon score sur les 4 premiers critères (≈0) valide la fitness.")
    print("  Les critères spatiaux (compacité, concentration) seront élevés")
    print("  pour un layout synthétique — c'est attendu.")
    print()


if __name__ == "__main__":
    main()
