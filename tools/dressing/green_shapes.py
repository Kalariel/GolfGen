"""Planches et statistiques des formes de greens (habillage, lot 1, round 1).

Même chaîne que ``pipeline.py`` : relief (cache), ``build_course`` (patron
``random`` par défaut), puis ``golfgen.dressing.dress_course`` pour chaque
style. Sorties sous ``tools/dressing/output/green_shapes/`` :

- ``overview_seed<N>.png`` : planche d'ensemble (``render_readable_svg``,
  greens en ``overlays``), links et parkland côte à côte ;
- ``zoom_seed<N>_<style>.png`` : les 18 greens recadrés (``SPAN`` blocs de
  côté, centrés sur le drapeau) avec le cœur du trou, l'axe d'approche, le
  drapeau et le centre de la forme ;
- ``report.json`` (versionné) : aires par par et par style, greens réduits
  par l'inclusion dans le cœur, temps de l'habillage.

    .venv/bin/python -m tools.dressing.green_shapes
    .venv/bin/python -m tools.dressing.green_shapes --stats-seeds 1-6 --no-planche
"""

from __future__ import annotations

import argparse
from collections import defaultdict
from html import escape
import json
from pathlib import Path
import subprocess
import time

import numpy as np

from golfgen.dressing import STYLE_SPECS, CourseDressing, dress_course
from golfgen.routing.geometry import build_hole_geometry
from golfgen.routing.model import ElasticHole
from golfgen.routing.muirfield import MuirfieldResult, build_course
from golfgen.routing.sites import WATER_LEVEL, load_terrain
from tools.muirfield.render_readable import PAR_COLORS, render_readable_svg


Point = tuple[float, float]

OUTPUT_DIR = Path(__file__).resolve().parent / "output" / "green_shapes"
SIZES = {"400x300": (400, 300), "300x400": (300, 400)}
OVERVIEW_SEEDS = (4,)
ZOOM_SEEDS = (1, 4)
PLANCHE_SIZE = (400, 300)
SPAN = 30.0                     # côté du recadrage (blocs)
TILE = 260                      # px
FOOTER = 40                     # px sous le recadrage
GREEN_FILL = "#9be58f"
GREEN_EDGE = "#2b7a34"
REDUCED_COLOR = "#ff2d7a"
OVERLAY_COLOR = "#d9ffd2"       # overlay translucide (opacité 0.35) : plus clair que les bandes
MONTAGE_FONT = "DejaVu-Sans"


def route(seed: int, width: int, height: int,
          pattern: str = "random") -> tuple[np.ndarray, MuirfieldResult]:
    heightmap = load_terrain(seed, width, height)
    return heightmap, build_course(seed, pattern, heightmap, width=width, height=height)


def timed_dressing(result: MuirfieldResult, seed: int, style: str) -> tuple[CourseDressing, float]:
    t0 = time.perf_counter()
    dressing = dress_course(result, seed=seed, style=style)
    return dressing, time.perf_counter() - t0


# --- statistiques -------------------------------------------------------------

def _quantiles(values: list[float]) -> dict[str, float]:
    array = np.asarray(values, dtype=float)
    keys = ("min", "q25", "median", "q75", "max")
    stats = dict(zip(keys, (round(float(v), 1)
                            for v in np.quantile(array, (0.0, 0.25, 0.5, 0.75, 1.0)))))
    stats["mean"] = round(float(array.mean()), 1)
    return stats


def summarize(rows: list[dict]) -> dict:
    """``rows`` : ``{style, par, area, target_area, reduced, shrink_steps, width}``
    par green ; synthèse par style puis par par."""
    grouped: dict[str, dict[int, list[dict]]] = defaultdict(lambda: defaultdict(list))
    for row in rows:
        grouped[row["style"]][row["par"]].append(row)
    out = {}
    for style in sorted(grouped):
        by_par = {}
        for par in sorted(grouped[style]):
            items = grouped[style][par]
            reduced = [r for r in items if r["reduced"]]
            by_par[str(par)] = {
                "greens": len(items),
                "area": _quantiles([r["area"] for r in items]),
                "target_area": _quantiles([r["target_area"] for r in items]),
                "reduced": len(reduced),
                "reduced_pct": round(100.0 * len(reduced) / len(items), 1),
                "reduced_widths": sorted(round(r["width"], 1) for r in reduced),
                "max_shrink_steps": max((r["shrink_steps"] for r in items), default=0),
            }
        all_items = [r for par in grouped[style].values() for r in par]
        out[style] = {
            "range": list(STYLE_SPECS[style].green_area),
            "greens": len(all_items),
            "reduced": sum(r["reduced"] for r in all_items),
            "area": _quantiles([r["area"] for r in all_items]),
            "by_par": by_par,
        }
    return out


# --- rendu --------------------------------------------------------------------

def tile_svg(hole: ElasticHole, dressing: CourseDressing, *, label: str = "") -> str:
    """Recadrage ``SPAN``×``SPAN`` blocs centré sur le drapeau : cœur du trou
    (couleur du par), axe (approche), green, centre (croix), drapeau."""
    green = dressing[hole.order].green
    flag = (hole.green.x, hole.green.y)
    scale = TILE / SPAN
    x0, y0 = flag[0] - SPAN / 2, flag[1] - SPAN / 2

    def pt(p: Point) -> tuple[float, float]:
        return ((p[0] - x0) * scale, (p[1] - y0) * scale)

    def fmt(points) -> str:
        return " ".join(f"{pt(p)[0]:.1f},{pt(p)[1]:.1f}" for p in points)

    color = PAR_COLORS[hole.par]
    core = build_hole_geometry(hole).core
    axis = [(p.x, p.y) for p in hole.axis]
    fx, fy = pt(flag)
    cx, cy = pt(green.center)
    reduced = green.reduced
    out = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{TILE}" height="{TILE + FOOTER}">',
        '<rect width="100%" height="100%" fill="#0d1117"/>',
        '<style>text{font-family:monospace;fill:#f0f6fc}</style>',
        f'<svg x="0" y="0" width="{TILE}" height="{TILE}" overflow="hidden">',
        f'<rect width="{TILE}" height="{TILE}" fill="#1b2a17"/>',
        f'<polygon points="{fmt(core)}" fill="{color}" fill-opacity="0.22" '
        f'stroke="{color}" stroke-width="1.5"/>',
        f'<polyline points="{fmt(axis)}" fill="none" stroke="#f0f6fc" stroke-opacity="0.7" '
        'stroke-width="1.2" stroke-dasharray="5 4"/>',
        f'<polygon points="{fmt(green.outline)}" fill="{GREEN_FILL}" fill-opacity="0.85" '
        f'stroke="{GREEN_EDGE}" stroke-width="1.6"/>',
        f'<path d="M{cx - 4:.1f},{cy:.1f}h8M{cx:.1f},{cy - 4:.1f}v8" stroke="#0d1117" '
        'stroke-width="1.3"/>',
        f'<circle cx="{fx:.1f}" cy="{fy:.1f}" r="2.2" fill="#0d1117"/>',
        f'<line x1="{fx:.1f}" y1="{fy:.1f}" x2="{fx:.1f}" y2="{fy - 18:.1f}" stroke="#f0f6fc" '
        'stroke-width="1.4"/>',
        f'<polygon points="{fx:.1f},{fy - 18:.1f} {fx + 10:.1f},{fy - 14.5:.1f} '
        f'{fx:.1f},{fy - 11:.1f}" fill="#e5534b"/>',
        # échelle : 5 blocs
        f'<line x1="8" y1="{TILE - 8}" x2="{8 + 5 * scale:.1f}" y2="{TILE - 8}" '
        'stroke="#f0f6fc" stroke-width="2"/>',
        f'<text x="8" y="{TILE - 13}" font-size="10">5 blocs</text>',
        '</svg>',
    ]
    shrink = f' · réduit ×{green.scale:.2f}' if reduced else ''

    first = f"#{hole.order} par {hole.par} · L {hole.length:.0f} · l {hole.width:.1f}"
    second = f"A {green.area:.0f} bl² (visée {green.target_area:.0f}){shrink}"
    style = f' style="fill:{REDUCED_COLOR}"' if reduced else ""
    out.extend([
        f'<text x="6" y="{TILE + 15}" font-size="11.5">{escape(first)}</text>',
        f'<text x="6" y="{TILE + 32}" font-size="11.5"{style}>{escape(second)}</text>',
    ])
    if label:
        out.append(f'<text x="{TILE - 6}" y="16" font-size="11" text-anchor="end">'
                   f'{escape(label)}</text>')
    out.append("</svg>")
    return "\n".join(out) + "\n"


def overview_svg(result: MuirfieldResult, heightmap: np.ndarray, dressing: CourseDressing,
                 *, seed: int, timing: float) -> str:
    overlays = [(dressing[hole.order].green.outline, OVERLAY_COLOR)
                for hole in result.layout.holes]
    reduced = sum(h.green.reduced for h in dressing.holes.values())
    return render_readable_svg(
        result.layout, result.violations, heightmap=heightmap, water_level=WATER_LEVEL,
        overlays=overlays, green_disks=False,
        title=f"seed {seed} · {int(result.width)}×{int(result.height)} · {result.pattern} · "
              f"style {dressing.style}",
        subtitle=f"greens habillés (vert clair) · {reduced} réduit(s) par le cœur · "
                 f"habillage {timing * 1000:.1f} ms")


def _svg_to_png(svg: str, path: Path) -> Path:
    svg_path = path.with_suffix(".svg")
    svg_path.write_text(svg, encoding="utf-8")
    subprocess.run(["rsvg-convert", "-o", str(path), str(svg_path)], check=True)
    svg_path.unlink()
    return path


def _montage(tiles: list[Path], columns: int, path: Path, title: str) -> Path:
    subprocess.run(["magick", "montage", *map(str, tiles), "-tile", f"{columns}x",
                    "-geometry", "+4+4", "-background", "#0d1117", "-fill", "#f0f6fc",
                    "-font", MONTAGE_FONT, "-pointsize", "18", "-title", title, str(path)], check=True)
    for tile in tiles:
        tile.unlink()
    return path


def render_planches(output: Path) -> list[Path]:
    width, height = PLANCHE_SIZE
    planches = []
    for seed in sorted(set(OVERVIEW_SEEDS) | set(ZOOM_SEEDS)):
        heightmap, result = route(seed, width, height)
        holes = sorted(result.layout.holes, key=lambda h: h.order)
        overview_tiles = []
        for style in STYLE_SPECS:
            dressing, timing = timed_dressing(result, seed, style)
            if seed in OVERVIEW_SEEDS:
                overview_tiles.append(_svg_to_png(
                    overview_svg(result, heightmap, dressing, seed=seed, timing=timing),
                    output / f"_overview_{seed}_{style}.png"))
            if seed in ZOOM_SEEDS:
                tiles = [_svg_to_png(tile_svg(hole, dressing, label=style),
                                     output / f"_tile_{seed}_{style}_{hole.order:02d}.png")
                         for hole in holes]
                planches.append(_montage(
                    tiles, 6, output / f"zoom_seed{seed}_{style}.png",
                    f"seed {seed} · {width}×{height} · {result.pattern} · {style} · "
                    f"greens recadrés {SPAN:.0f}×{SPAN:.0f} blocs"))
        if overview_tiles:
            planches.append(_montage(overview_tiles, 2, output / f"overview_seed{seed}.png",
                                     f"seed {seed} · links | parkland"))
    return planches


def _parse_seeds(text: str) -> tuple[int, ...]:
    if "-" in text:
        low, high = (int(v) for v in text.split("-"))
        return tuple(range(low, high + 1))
    return tuple(int(v) for v in text.split(","))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--stats-seeds", default="1-30", help="ex. 1-30 ou 3,7 (défaut : 1-30)")
    parser.add_argument("--sizes", default=",".join(SIZES),
                        help=f"tailles des statistiques (défaut : {','.join(SIZES)})")
    parser.add_argument("--no-planche", action="store_true")
    args = parser.parse_args()
    seeds = _parse_seeds(args.stats_seeds)
    sizes = [s for s in args.sizes.split(",") if s]

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    rows, timings, failures = [], [], []
    for size in sizes:
        width, height = SIZES[size]
        for seed in seeds:
            try:
                _, result = route(seed, width, height)
            except Exception as exc:          # routage impossible : compté, pas masqué
                failures.append({"size": size, "seed": seed, "error": type(exc).__name__})
                continue
            for style in STYLE_SPECS:
                dressing, timing = timed_dressing(result, seed, style)
                timings.append(timing)
                for hole in result.layout.holes:
                    green = dressing[hole.order].green
                    rows.append({"style": style, "par": hole.par, "area": green.area,
                                 "target_area": green.target_area, "reduced": green.reduced,
                                 "shrink_steps": green.shrink_steps, "width": hole.width})
            print(f"{size} seed {seed} : ok", flush=True)

    report = {
        "sizes": sizes, "seeds": list(seeds), "pattern": "random",
        "routing_failures": failures,
        "dressing_ms": _quantiles([t * 1000 for t in timings]),
        "styles": summarize(rows),
    }
    if not args.no_planche:
        report["planches"] = [p.name for p in render_planches(OUTPUT_DIR)]
    (OUTPUT_DIR / "report.json").write_text(
        json.dumps(report, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8")
    for style, data in report["styles"].items():
        print(f"[{style}] {data['greens']} greens, {data['reduced']} réduits, aire {data['area']}")
        for par, stats in data["by_par"].items():
            print(f"   par {par} : n={stats['greens']} aire {stats['area']} "
                  f"réduits {stats['reduced']} ({stats['reduced_pct']} %)")
    print(f"habillage (ms) : {report['dressing_ms']}")


if __name__ == "__main__":
    main()
