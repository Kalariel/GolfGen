"""Planche du rendu du rough dans le viewer (R5b) : rendu par défaut et
option « Debug », sur des trous choisis dans le JSON.

Génère un parcours 3.1 avec ``pipeline.py`` (seed, style, patron, taille),
choisit quelques trous dans le JSON et les capture dans le viewer
(``viewer/viewer.js`` via ``tools/dressing/rough_capture.html``) en headless,
deux colonnes : rendu par défaut (rough = toute terre ferme qu'aucun élément
ne couvre, translucide sur le relief, eau repeinte, fairways cernés, greens,
départs) et option Debug (couloirs, axes, sens de jeu, contour de la bande de
jeu). ``--overview`` ajoute une première ligne « parcours entier ».

Bande de jeu d'un trou = ``buffered_axis(axe, width / 2 + rough_margin)``
(``golfgen.routing.geometry.build_hole_geometry``, zone de placement
interne, pas une surface), cœur = ``buffered_axis(axe, width / 2)`` ; eau =
cellules dont l'octet du relief est sous le seuil de ``terrain.water_level``
(même règle que le viewer).

Choix automatique des trous (sauf ``--holes``), un par critère, sans
doublon, dans cet ordre : fairway coupé par l'eau (le plus de cellules d'eau
dans le cœur, fairway non vide), fairway en plusieurs morceaux, plus long
carry de rough après la boîte de départ avant, plus fort chevauchement de
bande de jeu avec un trou voisin, fairway vidé par l'eau ; complété jusqu'à
``MIN_HOLES`` par l'eau dans le cœur.

Capture : ``python -m http.server`` local (racine du dépôt) et
``chrome-headless-shell`` de Playwright (``--chrome`` sinon cherché sous
``~/.cache/ms-playwright``) ; vignettes, assemblages et montages ``magick``
(requis, vérifié au départ). Sorties (non
versionnées) sous ``tools/dressing/output/rough_plate/`` : JSON du parcours,
vignettes, ``selection_<style>_s<seed>.json`` et
``planche_<style>_s<seed>.png``.

    .venv/bin/python -m tools.dressing.rough_plate --seed 8 --style links \\
        --pattern random --width 400 --height 300 --overview

Parcours entiers sur plusieurs seeds (``--seeds 3,7`` ou ``1-10``, à la place
de ``--seed``) : ``pipeline.py`` avec ses paramètres PAR DÉFAUT (bunkers
posés, style, patron et taille de la config ; seuls ``--style``,
``--pattern``, ``--width`` et ``--height`` (ensemble) donnés
explicitement sont transmis ; ``--holes``, ``--tile``,
``--overview`` et ``--copy-to`` sont refusés),
puis la vue globale seule, rendu par défaut (couches Bunkers et Chemins
actives, Ancrages et liaisons droites masquées, sans Debug),
``--overview-width`` pixels de large (défaut ``SEED_TILE_W``), titre
« seed N — LxH, patron » au-dessus. Un échec du pipeline (code 3 : routage,
habillage ou bunkers) ou de la capture est relevé et la série continue
(vignette d'échec) ; le code de sortie vaut alors ``EXIT_SEEDS_FAILED``.
Sorties sous ``--output`` (défaut ``tools/dressing/output/bunkers_seeds/``) :
``seed_<N>.png``, ``montage.png`` (2 colonnes, ``magick montage``) et
``report.json`` (par seed : taille, patron, style, durée du pipeline,
bunkers posés par famille/rôle et par famille, trous vides de la règle et
trous sans aucun bunker, non posés et leurs raisons — lus dans la console
du pipeline, absents du JSON —, code de sortie ; seeds en échec).

    .venv/bin/python -m tools.dressing.rough_plate --seeds 1-10
"""

from __future__ import annotations

import argparse
import base64
from dataclasses import dataclass, asdict
import json
import math
import re
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import time

import numpy as np

from golfgen.routing.geometry import buffered_axis
from tools.dressing.common import MONTAGE_FONT, parse_seeds

ROOT = Path(__file__).resolve().parents[2]
OUTPUT_DIR = ROOT / "tools" / "dressing" / "output" / "rough_plate"
CAPTURE_PAGE = "/tools/dressing/rough_capture.html"
TILE_W, TILE_H = 640, 480
LABEL_W = 250
PAD = 8.0           # blocs autour de la bande de jeu du trou dans la vignette
MIN_HOLES, MAX_HOLES = 4, 6
MODES = {
    "defaut": "rendu par défaut",
    "debug": "option Debug : couloirs, axes, bande de jeu",
}
OVERVIEW_PAD = 4.0  # blocs autour de la carte dans la vue globale
SEEDS_OUTPUT_DIR = ROOT / "tools" / "dressing" / "output" / "bunkers_seeds"
SEED_TILE_W = 2000  # largeur (px) de la vue globale d'une seed (--seeds)
SEED_TITLE_H = 64   # bandeau du titre « seed N — LxH, patron »
MONTAGE_COLUMNS, MONTAGE_TILE_W = 2, 1000
EXIT_SEEDS_FAILED = 1   # au moins une seed en échec (pipeline ou capture)
UNPLACED_LINE = re.compile(r"^\s*(\d+) non posé\(s\)(?: : (.*))?$", re.MULTILINE)
BG, INK = "#0d1117", "#f0f6fc"

Point = tuple[float, float]


@dataclass(frozen=True)
class HoleTags:
    """Mesures d'un trou pour le choix des lignes de la planche."""
    id: int
    par: int
    pieces: int | None        # morceaux de fairway ; None = clé absente
    core_water: int           # cellules d'eau dans le cœur
    carry: float | None       # blocs, boîte avant -> fairway ; None sans fairway/départs
    overlap_with: int | None  # trou dont la bande de jeu chevauche le plus
    overlap_cells: int        # cellules communes avec ce trou

    @property
    def empty(self) -> bool:
        return self.pieces == 0


def axis_of(hole: dict) -> tuple[Point, ...]:
    return tuple((p["x"], p["y"]) for p in [hole["tee"], *hole.get("doglegs", []), hole["green"]])


def band_polygon(hole: dict) -> tuple[Point, ...]:
    return buffered_axis(axis_of(hole), hole["width"] / 2.0 + hole.get("rough_margin", 0.0))


def core_polygon(hole: dict) -> tuple[Point, ...]:
    return buffered_axis(axis_of(hole), hole["width"] / 2.0)


def water_mask(data: dict) -> np.ndarray:
    """Eau (hauteur × largeur), seuil d'octet identique à ``waterThreshold``
    du viewer ; tout faux sans ``water_level`` ou sans relief."""
    terrain = data["terrain"]
    w, h = int(terrain["width"]), int(terrain["height"])
    elev = terrain.get("elevation") or {}
    level = terrain.get("water_level")
    if level is None or "data" not in elev:
        return np.zeros((h, w), dtype=bool)
    raw = np.frombuffer(base64.b64decode(elev["data"]), dtype=np.uint8)
    lo, hi = float(elev["min_elevation"]), float(elev["max_elevation"])
    if hi - lo < 1e-10:
        threshold = 256 if level > lo else 0
    else:
        threshold = max(0, min(256, math.ceil((level - lo) / (hi - lo) * 255)))
    return (raw.astype(np.int32) < threshold).reshape(h, w)


def polygon_mask(polygon, width: int, height: int) -> np.ndarray:
    """Cellules (centres ``x + 0,5``, ``y + 0,5``) dans le polygone
    (pair-impair), grille hauteur × largeur."""
    poly = np.asarray(polygon, dtype=float)
    mask = np.zeros((height, width), dtype=bool)
    x0 = max(0, int(math.floor(poly[:, 0].min())))
    x1 = min(width, int(math.ceil(poly[:, 0].max())) + 1)
    y0 = max(0, int(math.floor(poly[:, 1].min())))
    y1 = min(height, int(math.ceil(poly[:, 1].max())) + 1)
    if x0 >= x1 or y0 >= y1:
        return mask
    xs, ys = np.meshgrid(np.arange(x0, x1) + 0.5, np.arange(y0, y1) + 0.5)
    inside = np.zeros(xs.shape, dtype=bool)
    for (ax, ay), (bx, by) in zip(poly, np.roll(poly, -1, axis=0)):
        crosses = (ay > ys) != (by > ys)
        with np.errstate(divide="ignore", invalid="ignore"):
            xi = ax + (ys - ay) * (bx - ax) / (by - ay)
        inside ^= crosses & (xs < xi)
    mask[y0:y1, x0:x1] = inside
    return mask


def _carry(hole: dict) -> float | None:
    """Distance (blocs) entre la boîte de départ avant et le morceau de
    fairway le plus proche (sommets contre sommets) ; None sans l'un des deux."""
    features = hole.get("features") or {}
    tees = features.get("tees") or []
    pieces = features.get("fairway") or []
    if not tees or not pieces:
        return None
    box = np.array([(p["x"], p["y"]) for p in tees[-1]["outline"]], dtype=float)
    fairway = np.array([(p["x"], p["y"]) for piece in pieces for p in piece["outline"]],
                       dtype=float)
    return float(np.min(np.hypot(*(box[:, None, :] - fairway[None, :, :]).transpose(2, 0, 1))))


def hole_tags(data: dict) -> list[HoleTags]:
    terrain = data["terrain"]
    w, h = int(terrain["width"]), int(terrain["height"])
    water = water_mask(data)
    holes = data["routing"]["holes"]
    bands = {hole["id"]: polygon_mask(band_polygon(hole), w, h) for hole in holes}
    tags = []
    for hole in holes:
        fairway = (hole.get("features") or {}).get("fairway")
        core = polygon_mask(core_polygon(hole), w, h)
        best, best_cells = None, 0
        for other, mask in bands.items():
            if other == hole["id"]:
                continue
            cells = int(np.count_nonzero(bands[hole["id"]] & mask))
            if cells > best_cells:
                best, best_cells = other, cells
        tags.append(HoleTags(
            id=hole["id"], par=hole["par"],
            pieces=len(fairway) if isinstance(fairway, list) else None,
            core_water=int(np.count_nonzero(core & water)),
            carry=_carry(hole), overlap_with=best, overlap_cells=best_cells))
    return tags


def select_holes(tags: list[HoleTags], max_holes: int = MAX_HOLES,
                 min_holes: int = MIN_HOLES) -> list[tuple[int, str]]:
    """Trous retenus ``(id, critère)`` dans l'ordre des critères (voir le
    docstring du module) ; un critère sans candidat est sauté."""
    chosen: list[tuple[int, str]] = []
    taken: set[int] = set()

    def pick(candidates, key, reason):
        pool = [t for t in candidates if t.id not in taken]
        if pool and len(chosen) < max_holes:
            best = max(pool, key=key)
            chosen.append((best.id, reason))
            taken.add(best.id)

    pick([t for t in tags if t.core_water > 0 and t.pieces], lambda t: (t.core_water, -t.id),
         "fairway coupé par l'eau")
    pick([t for t in tags if t.pieces and t.pieces >= 2], lambda t: (t.pieces, t.core_water, -t.id),
         "fairway en plusieurs morceaux")
    pick([t for t in tags if t.carry is not None], lambda t: (t.carry, -t.id),
         "carry de rough après les départs")
    pick([t for t in tags if t.overlap_cells > 0], lambda t: (t.overlap_cells, -t.id),
         "bandes de jeu voisines qui se chevauchent")
    pick([t for t in tags if t.empty], lambda t: (t.core_water, -t.id),
         "fairway vidé par l'eau")
    while len(chosen) < min(min_holes, max_holes):
        before = len(chosen)
        pick([t for t in tags if t.core_water > 0], lambda t: (t.core_water, -t.id),
             "eau dans le cœur")
        if len(chosen) == before:
            break
    return chosen


def bbox(polygon) -> tuple[float, float, float, float]:
    xs = [p[0] for p in polygon]
    ys = [p[1] for p in polygon]
    return min(xs), min(ys), max(xs), max(ys)


def crop_view(box, tile_w: int = TILE_W, tile_h: int = TILE_H,
              pad: float = PAD) -> tuple[float, float, float]:
    """Caméra du viewer ``(zoom, pan_x, pan_y)`` (pixels par bloc, décalage
    en pixels) qui centre la boîte ``(x0, y0, x1, y1)`` (blocs), élargie de
    ``pad`` de chaque côté, dans une vignette ``tile_w × tile_h``, en entier."""
    x0, y0, x1, y1 = box
    bw, bh = (x1 - x0) + 2 * pad, (y1 - y0) + 2 * pad
    if bw <= 0 or bh <= 0:
        raise ValueError("boîte vide")
    zoom = min(tile_w / bw, tile_h / bh)
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    return zoom, tile_w / 2 - cx * zoom, tile_h / 2 - cy * zoom


def parse_holes(text: str, known) -> list[tuple[int, str]]:
    """Trous imposés ``--holes`` (``"3,7,13"``) : ``[(id, "imposé")]`` dans
    l'ordre donné ; un identifiant mal formé ou absent du parcours (``known``)
    arrête l'outil avec un message explicite."""
    try:
        ids = [int(v) for v in text.split(",")]
    except ValueError:
        raise SystemExit(f"--holes mal formé : {text!r} (attendu : 3,7,13)") from None
    missing = [i for i in ids if i not in known]
    if missing:
        raise SystemExit(f"--holes : trou(s) absent(s) du parcours : "
                         f"{', '.join(map(str, missing))} (trous : {min(known)} à {max(known)})")
    return [(i, "imposé") for i in ids]


def overview_size(map_w: int, map_h: int, tile_w: int,
                  pad: float = OVERVIEW_PAD) -> tuple[int, int]:
    """Vignette de la vue globale : largeur ``tile_w``, hauteur au rapport
    de la carte élargie de ``pad`` (entière)."""
    return tile_w, int(round(tile_w * (map_h + 2 * pad) / (map_w + 2 * pad)))


def describe(tag: HoleTags) -> str:
    """Mesures lisibles d'un trou (étiquette de ligne)."""
    parts = [f"par {tag.par}"]
    if tag.pieces is None:
        parts.append("fairway non exporté")
    elif tag.pieces == 0:
        parts.append("fairway vide")
    else:
        parts.append(f"{tag.pieces} morceau{'x' if tag.pieces > 1 else ''}")
    parts.append(f"eau dans le cœur : {tag.core_water} b²")
    if tag.carry is not None:
        parts.append(f"carry : {tag.carry:.1f} b")
    if tag.overlap_with is not None:
        parts.append(f"chevauche #{tag.overlap_with} : {tag.overlap_cells} b²")
    return "\n".join(parts)


# === Capture et assemblage (navigateur, magick) ===

class CaptureError(RuntimeError):
    """Capture vide (navigateur)."""


# Échecs d'une capture ou d'un assemblage, relevés seed par seed (--seeds).
CAPTURE_ERRORS = (CaptureError, subprocess.CalledProcessError, subprocess.TimeoutExpired, OSError)


def require_magick() -> None:
    """``magick`` (ImageMagick) : requis par les vignettes de texte, les
    assemblages et les montages (aucun repli)."""
    if shutil.which("magick") is None:
        raise SystemExit("magick (ImageMagick) introuvable : requis pour les vignettes et les planches")


def find_chrome(explicit: str | None) -> Path:
    if explicit:
        path = Path(explicit)
    else:
        found = sorted(Path.home().glob(
            ".cache/ms-playwright/chromium_headless_shell-*/chrome-headless-shell*/chrome-headless-shell"))
        if not found:
            raise SystemExit("chrome-headless-shell introuvable sous ~/.cache/ms-playwright (--chrome)")
        path = found[-1]
    if not path.is_file():
        raise SystemExit(f"navigateur introuvable : {path}")
    return path


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def start_server(port: int) -> subprocess.Popen:
    server = subprocess.Popen(
        [sys.executable, "-m", "http.server", str(port), "--bind", "127.0.0.1",
         "--directory", str(ROOT)],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    for _ in range(100):
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.2):
                return server
        except OSError:
            time.sleep(0.05)
    server.terminate()
    raise SystemExit("http.server ne répond pas")


def capture(chrome: Path, url: str, path: Path, size: tuple[int, int] = (TILE_W, TILE_H)) -> Path:
    path.unlink(missing_ok=True)
    subprocess.run(
        [str(chrome), "--headless", "--disable-gpu", "--hide-scrollbars",
         f"--window-size={size[0]},{size[1]}", "--virtual-time-budget=5000",
         f"--screenshot={path}", url],
        check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=120)
    if not path.is_file() or path.stat().st_size == 0:
        raise CaptureError(f"capture vide : {url}")
    return path


def _text_tile(path: Path, text: str, width: int, height: int, size: int,
               gravity: str = "center") -> Path:
    subprocess.run(["magick", "-size", f"{width}x{height}", "-background", BG, "-fill", INK,
                    "-font", MONTAGE_FONT, "-pointsize", str(size), "-gravity", gravity,
                    f"caption:{text}", str(path)], check=True)
    return path


def _stack(paths: list[Path], path: Path, *, vertical: bool = True, border: int = 0) -> Path:
    """Images ``paths`` les unes sous les autres (``vertical``) ou côte à
    côte, centrées, fond ``BG``, ``border`` px autour de chacune."""
    framed = ["-bordercolor", BG, "-border", str(border)] if border else []
    subprocess.run(["magick", *map(str, paths), *framed, "-background", BG, "-gravity", "center",
                    "-append" if vertical else "+append", "+repage", "-depth", "8", str(path)],
                   check=True)
    return path


def assemble(rows: list[tuple[str, list[Path], int]], tile_w: int, title: str,
             path: Path, work: Path) -> Path:
    """Planche : titre, en-têtes des modes, puis une ligne par trou
    ``(étiquette, vignettes, hauteur)`` (étiquette à gauche, une vignette par
    mode)."""
    border = ["-bordercolor", BG, "-border", "3"]
    parts = [_text_tile(work / "title.png", title, LABEL_W + len(MODES) * (tile_w + 6) + 6,
                        40, 20)]
    heads = [_text_tile(work / "head_label.png", "trou", LABEL_W, 44, 16)]
    heads += [_text_tile(work / f"head_{m}.png", text, tile_w, 44, 16) for m, text in MODES.items()]
    subprocess.run(["magick", *map(str, heads), *border, "+append", str(work / "head.png")],
                   check=True)
    parts.append(work / "head.png")
    for k, (label, tiles, height) in enumerate(rows):
        label_png = _text_tile(work / f"row_{k}_label.png", label, LABEL_W, height, 15, "west")
        row = work / f"row_{k}.png"
        subprocess.run(["magick", str(label_png), *map(str, tiles), *border, "+append", str(row)],
                       check=True)
        parts.append(row)
    subprocess.run(["magick", *map(str, parts), "-background", BG, "-gravity", "west",
                    "-append", "+repage", "-depth", "8", str(path)], check=True)
    return path


def _under_root(output: Path) -> Path:
    """``output`` résolu, sous la racine du dépôt (servie par http.server)."""
    output = output.resolve()
    try:
        output.relative_to(ROOT)
    except ValueError:
        raise SystemExit(f"--output doit être sous {ROOT} (servi par http.server)") from None
    return output


def _pipeline_options(args) -> list[str]:
    """Options du pipeline données explicitement (``--width`` et ``--height``
    vont ensemble, vérifié par ``check_args``)."""
    cmd = []
    if args.style:
        cmd += ["--style", args.style]
    if args.pattern:
        cmd += ["--pattern", args.pattern]
    if args.width is not None:
        cmd += ["--width", str(args.width), "--height", str(args.height)]
    return cmd


def generate(args, output: Path) -> Path:
    name = f"{args.style}_s{args.seed}"
    json_path = output / f"{name}.json"
    cmd = [sys.executable, str(ROOT / "pipeline.py"), "--seed", str(args.seed),
           "--output", str(json_path), *_pipeline_options(args)]
    subprocess.run(cmd, check=True, cwd=ROOT, stdout=subprocess.DEVNULL)
    return json_path


# === Plusieurs seeds : parcours entiers (--seeds) ===

def parse_unplaced(stdout: str) -> tuple[int | None, dict[str, int]]:
    """Non posés de la console du pipeline (``_bunkers_lines``) : nombre et
    comptes ``étape/raison`` ; ``(None, {})`` sans la ligne (pas de bunkers)."""
    match = UNPLACED_LINE.search(stdout)
    if match is None:
        return None, {}
    reasons = {}
    for part in (match.group(2) or "").split(", "):
        if part.strip():
            key, count = part.strip().rsplit(" ", 1)
            reasons[key] = int(count)
    return int(match.group(1)), reasons


def bunker_counts(data: dict) -> dict:
    """Bunkers posés du JSON 3.2 : total, par ``famille/rôle`` et par
    famille, trous vides de la règle (``empty_holes``) et trous du tracé
    sans aucun bunker posé (``holes_without_bunker``) ; ``None`` sans clé
    ``bunkers``."""
    bunkers = data.get("bunkers")
    if not isinstance(bunkers, dict):
        return None
    items = bunkers.get("items") or []
    by, families = {}, {}
    for item in items:
        key = f"{item['family']}/{item['role']}"
        by[key] = by.get(key, 0) + 1
        families[item["family"]] = families.get(item["family"], 0) + 1
    holes = {hole["id"] for hole in (data.get("routing") or {}).get("holes") or []}
    return {"placed": len(items), "by_family_role": dict(sorted(by.items())),
            "by_family": dict(sorted(families.items())),
            "empty_holes": list(bunkers.get("empty_holes") or []),
            "holes_without_bunker": sorted(holes - {item["hole"] for item in items})}


def seed_title(seed: int, data: dict) -> str:
    """Titre d'une vignette : « seed N — LxH, patron » (rien d'autre)."""
    meta = data["metadata"]
    return (f"seed {seed} — {int(meta['width'])}x{int(meta['height'])}, "
            f"{meta.get('pattern', {}).get('resolved', '?')}")


def run_seed(args, seed: int, output: Path) -> tuple[dict, Path | None]:
    """``pipeline.py`` pour ``seed`` (paramètres par défaut sauf options
    explicites) ; relevé du rapport et JSON écrit (``None`` en échec) sous
    ``seed_<N>.json``."""
    json_path = output / f"seed_{seed}.json"
    json_path.unlink(missing_ok=True)
    cmd = [sys.executable, str(ROOT / "pipeline.py"), "--seed", str(seed), "--output", str(json_path),
           *_pipeline_options(args)]
    t0 = time.perf_counter()
    done = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True)
    record = {"seed": seed, "exit_code": done.returncode,
              "pipeline_seconds": round(time.perf_counter() - t0, 2)}
    if done.returncode != 0 or not json_path.is_file():
        lines = [line for line in done.stderr.splitlines() if line.strip()]
        record["error"] = lines[-1] if lines else "(pas de message)"
        return record, None
    data = json.loads(json_path.read_text(encoding="utf-8"))
    meta = data["metadata"]
    unplaced, reasons = parse_unplaced(done.stdout)
    record.update(size=f"{int(meta['width'])}x{int(meta['height'])}",
                  pattern=meta.get("pattern", {}).get("resolved"), style=meta.get("style"),
                  bunkers=bunker_counts(data), unplaced=unplaced, unplaced_by_reason=reasons)
    return record, json_path


def overview_view(data: dict, width: int) -> tuple[tuple[int, int], tuple[float, float, float]]:
    """Taille de la vue globale (``width`` px de large) et caméra du viewer."""
    map_w, map_h = int(data["terrain"]["width"]), int(data["terrain"]["height"])
    size = overview_size(map_w, map_h, width)
    return size, crop_view((0, 0, map_w, map_h), *size, pad=OVERVIEW_PAD)


def overview_shot(chrome: Path, port: int, json_path: Path, size, view, path: Path) -> Path:
    """Vue globale du JSON ``json_path``, rendu par défaut (sans Debug)."""
    zoom, pan_x, pan_y = view
    json_url = "/" + json_path.relative_to(ROOT).as_posix()
    return capture(chrome, f"http://127.0.0.1:{port}{CAPTURE_PAGE}?json={json_url}"
                           f"&debug=0&vue={zoom:.4f},{pan_x:.2f},{pan_y:.2f}", path, size)


def montage(paths: list[Path], path: Path) -> Path:
    """Planche des seeds, ``MONTAGE_COLUMNS`` colonnes (``magick montage``)."""
    subprocess.run(["magick", "montage", *map(str, paths), "-tile", f"{MONTAGE_COLUMNS}x",
                    "-geometry", f"{MONTAGE_TILE_W}x+6+6", "-background", BG,
                    str(path)], check=True)
    return path


def _failure_tile(path: Path, text: str, size: tuple[int, int]) -> Path:
    return _text_tile(path, text, size[0], size[1], 32)


def _write_report(output: Path, report: dict) -> None:
    (output / "report.json").write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n",
                                        encoding="utf-8")


def seeds_batch(args, seeds: tuple[int, ...]) -> tuple[Path, list[int]]:
    """Parcours entiers de ``seeds`` : une vue globale par seed, montage et
    ``report.json`` (voir le docstring du module) ; renvoie le montage et
    les seeds en échec (pipeline ou capture)."""
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    chrome = find_chrome(args.chrome)
    work = output / "tiles"
    work.mkdir(exist_ok=True)
    records, pngs, failed = [], [], []
    fallback = (args.overview_width, args.overview_width * 3 // 4)
    port = _free_port()
    server = start_server(port)
    try:
        for seed in seeds:
            record, json_path = run_seed(args, seed, output)
            png = output / f"seed_{seed}.png"
            png.unlink(missing_ok=True)
            records.append(record)
            if json_path is None:
                print(f"seed {seed} : échec (code {record['exit_code']}) : {record['error']}",
                      file=sys.stderr)
                failed.append(seed)
                pngs.append(_failure_tile(work / f"seed_{seed}_echec.png",
                                          f"seed {seed} — échec du pipeline (code {record['exit_code']})",
                                          fallback))
                continue
            data = json.loads(json_path.read_text(encoding="utf-8"))
            size, view = overview_view(data, args.overview_width)
            try:
                shot = overview_shot(chrome, port, json_path, size, view, work / f"seed_{seed}_vue.png")
                title = _text_tile(work / f"seed_{seed}_titre.png", seed_title(seed, data),
                                   size[0], SEED_TITLE_H, 30)
                _stack([title, shot], png)
            except CAPTURE_ERRORS as exc:
                record["error"] = f"capture : {exc}"
                print(f"seed {seed} : échec de la capture : {exc}", file=sys.stderr)
                failed.append(seed)
                pngs.append(_failure_tile(work / f"seed_{seed}_echec.png",
                                          f"seed {seed} — échec de la capture", size))
                continue
            record["png"] = png.name
            pngs.append(png)
            print(f"seed {seed} : {record['size']}, {record['pattern']}, "
                  f"{record['bunkers']['placed'] if record['bunkers'] else '-'} posé(s), "
                  f"{record['unplaced']} non posé(s), {record['pipeline_seconds']} s")
    finally:
        server.terminate()
        server.wait(timeout=10)
    plate = montage(pngs, output / "montage.png")
    _write_report(output, {
        "seeds": list(seeds),
        "pipeline_options": {"style": args.style, "pattern": args.pattern,
                             "width": args.width, "height": args.height},
        "overview_width_px": args.overview_width,
        "montage": plate.name,
        "failed_seeds": failed,
        "runs": records,
    })
    print(plate)
    return plate, failed


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--seed", type=int)
    parser.add_argument("--seeds", help="parcours entiers de plusieurs seeds, ex. 1-10 ou 3,7 "
                                        "(paramètres du pipeline par défaut)")
    parser.add_argument("--overview-width", type=int,
                        help=f"largeur (px) de la vue globale d'une seed avec --seeds "
                             f"(défaut {SEED_TILE_W})")
    parser.add_argument("--style", choices=("links", "parkland"))
    parser.add_argument("--pattern", choices=("muirfield", "muirfield_inverse", "random"))
    parser.add_argument("--width", type=int)
    parser.add_argument("--height", type=int)
    parser.add_argument("--holes", help="trous imposés, ex. 3,7,13 (sinon choix automatique)")
    parser.add_argument("--chrome", help="chemin de chrome-headless-shell")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--copy-to", type=Path, help="dossier où copier la planche")
    parser.add_argument("--tile",
                        help=f"taille des vignettes de trou, LxH (défaut {TILE_W}x{TILE_H})")
    parser.add_argument("--overview", action="store_true",
                        help="ajoute une première ligne « parcours entier » (vue globale)")
    return parser


def check_args(parser: argparse.ArgumentParser, args) -> None:
    """Combinaisons refusées (``parser.error``, code 2) : options d'un seul
    mode, ``--width`` sans ``--height`` (ou l'inverse)."""
    if (args.seed is None) == (args.seeds is None):
        parser.error("--seed ou --seeds (un seul des deux)")
    if (args.width is None) != (args.height is None):
        parser.error("--width et --height vont ensemble")
    if args.seeds is not None:
        single = [flag for flag, given in (("--holes", args.holes), ("--copy-to", args.copy_to),
                                           ("--tile", args.tile), ("--overview", args.overview))
                  if given]
        if single:
            parser.error(f"{', '.join(single)} : avec --seed seulement (pas avec --seeds)")
    else:
        if args.overview_width is not None:
            parser.error("--overview-width : avec --seeds seulement (pas avec --seed)")
        if args.style is None:
            parser.error("--style requis avec --seed")


def main(argv=None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    check_args(parser, args)
    require_magick()
    if args.seeds is not None:
        try:
            seeds = parse_seeds(",".join(args.seeds.replace(",", " ").split()))
        except ValueError as exc:
            parser.error(f"--seeds : {exc}")
        args.overview_width = args.overview_width or SEED_TILE_W
        args.output = args.output or SEEDS_OUTPUT_DIR
        _under_root(args.output)
        _, failed = seeds_batch(args, seeds)
        if failed:
            print(f"{len(failed)} seed(s) en échec : {', '.join(map(str, failed))}", file=sys.stderr)
            return EXIT_SEEDS_FAILED
        return 0
    args.output = args.output or OUTPUT_DIR
    tile = tuple(int(v) for v in (args.tile or f"{TILE_W}x{TILE_H}").lower().split("x"))

    output = _under_root(args.output)
    output.mkdir(parents=True, exist_ok=True)
    chrome = find_chrome(args.chrome)
    json_path = generate(args, output)
    data = json.loads(json_path.read_text(encoding="utf-8"))
    tags = {t.id: t for t in hole_tags(data)}
    if args.holes:
        chosen = parse_holes(args.holes, tags)
    else:
        chosen = select_holes(list(tags.values()))
    holes = {h["id"]: h for h in data["routing"]["holes"]}
    name = json_path.stem
    work = output / f"tiles_{name}"
    work.mkdir(exist_ok=True)

    port = _free_port()
    server = start_server(port)
    rows = []
    try:
        json_url = "/" + json_path.relative_to(ROOT).as_posix()

        def capture_row(prefix, view, size):
            zoom, pan_x, pan_y = view
            return [capture(chrome, f"http://127.0.0.1:{port}{CAPTURE_PAGE}?json={json_url}"
                                    f"&debug={int(m == 'debug')}&vue={zoom:.4f},{pan_x:.2f},{pan_y:.2f}",
                            work / f"{prefix}_{m}.png", size) for m in MODES]

        if args.overview:
            map_w, map_h = int(data["terrain"]["width"]), int(data["terrain"]["height"])
            size = overview_size(map_w, map_h, tile[0])
            view = crop_view((0, 0, map_w, map_h), *size, pad=OVERVIEW_PAD)
            rows.append(("parcours entier", capture_row("overview", view, size), size[1]))
        for hole_id, reason in chosen:
            view = crop_view(bbox(band_polygon(holes[hole_id])), *tile)
            label = f"#{hole_id} — {reason}\n\n{describe(tags[hole_id])}"
            rows.append((label, capture_row(f"h{hole_id:02d}", view, tile), tile[1]))
    except CaptureError as exc:
        raise SystemExit(str(exc)) from None
    finally:
        server.terminate()
        server.wait(timeout=10)

    meta = data["metadata"]
    title = (f"Rendu du rough (R5b) — {args.style}, seed {args.seed}, "
             f"{meta.get('pattern', {}).get('resolved', '?')}, "
             f"{int(meta['width'])}x{int(meta['height'])}")
    plate = assemble(rows, tile[0], title, output / f"planche_{name}.png", work)
    (output / f"selection_{name}.json").write_text(json.dumps({
        "seed": args.seed, "style": args.style, "json": json_path.name,
        "holes": [{"id": i, "reason": r, **asdict(tags[i])} for i, r in chosen],
    }, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    if args.copy_to:
        args.copy_to.mkdir(parents=True, exist_ok=True)
        shutil.copy2(plate, args.copy_to / plate.name)
    print(plate)
    return 0


if __name__ == "__main__":
    sys.exit(main())
