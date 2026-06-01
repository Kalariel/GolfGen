"""
Fetch golf course tee/green positions from OpenStreetMap (Overpass API).
Falls back to hardcoded public data if OSM coverage is insufficient.

Usage:
    python tools/fetch_course_osm.py --course "Pebble Beach Golf Links" --output tools/pebble_beach.json
    python tools/fetch_course_osm.py --course "Augusta National Golf Club" --output tools/augusta.json
    python tools/fetch_course_osm.py --fallback pebble_beach --output tools/pebble_beach.json
"""
import argparse
import json
import math
import sys
import urllib.request
import urllib.parse


# ---------------------------------------------------------------------------
# Hardcoded fallback data (public domain stats)
# ---------------------------------------------------------------------------

FALLBACK_COURSES = {
    "pebble_beach": {
        "name": "Pebble Beach Golf Links",
        "source": "fallback (public stats)",
        # par per hole 1-18
        "pars": [4, 5, 4, 4, 3, 5, 3, 4, 4, 4, 3, 3, 4, 5, 4, 4, 3, 5],
        # distances in yards (championship tees, ~2024)
        "yards": [381, 502, 388, 327, 166, 516, 106, 418, 450,
                  495, 380, 202, 400, 580, 397, 403, 178, 543],
    },
    "augusta": {
        "name": "Augusta National Golf Club",
        "source": "fallback (public stats)",
        "pars": [4, 5, 4, 3, 4, 3, 4, 5, 4, 4, 4, 3, 5, 4, 5, 3, 4, 4],
        "yards": [445, 575, 350, 240, 495, 180, 450, 570, 460,
                  495, 520, 155, 510, 440, 550, 170, 440, 465],
    },
}


def _yards_to_blocks(yards: float) -> float:
    """1 yard ≈ 0.914 m, 1 block = 3 m → 1 yard ≈ 0.305 blocks."""
    return yards * 0.305


def _synthetic_layout(n_holes: int, blocks_per_hole: list[float], grid: int = 350, margin: int = 30) -> list[dict]:
    """
    Place n_holes on a rough elliptical loop inside a grid×grid space.
    Each hole length follows blocks_per_hole[i].
    Returns list of {tee: [x, y], green: [x, y]} dicts.
    """
    usable = grid - 2 * margin
    # Ellipse radii (leave room for hole lengths)
    rx = usable * 0.38
    ry = usable * 0.32
    cx = grid / 2
    cy = grid / 2

    positions = []
    for i in range(n_holes):
        # Spread tees evenly around the ellipse
        theta = (2 * math.pi * i / n_holes) - math.pi / 2  # start at top
        tee_x = cx + rx * math.cos(theta)
        tee_y = cy + ry * math.sin(theta)

        # Green is displaced inward toward next tee direction, scaled by hole length
        theta_next = (2 * math.pi * (i + 1) / n_holes) - math.pi / 2
        dx = math.cos(theta_next) - math.cos(theta)
        dy = math.sin(theta_next) - math.sin(theta)
        mag = math.hypot(dx, dy) or 1.0
        scale = min(blocks_per_hole[i], usable * 0.4)
        green_x = tee_x + (dx / mag) * scale
        green_y = tee_y + (dy / mag) * scale

        # Clamp to grid
        def clamp(v):
            return max(margin, min(v, grid - margin))

        positions.append({
            "tee": [round(clamp(tee_x), 2), round(clamp(tee_y), 2)],
            "green": [round(clamp(green_x), 2), round(clamp(green_y), 2)],
        })
    return positions


def build_from_fallback(key: str) -> list[dict]:
    data = FALLBACK_COURSES[key]
    pars = data["pars"]
    blocks = [_yards_to_blocks(y) for y in data["yards"]]
    layout = _synthetic_layout(len(pars), blocks)
    holes = []
    for i, (pos, par, b) in enumerate(zip(layout, pars, blocks)):
        tee = pos["tee"]
        green = pos["green"]
        holes.append({
            "id": i + 1,
            "par": par,
            "tee": tee,
            "green": green,
            "waypoints": [tee, green],
            "fairway_width": 12,
            "blocks_approx": round(b, 1),
            "source": data["source"],
        })
    return holes


# ---------------------------------------------------------------------------
# OSM fetch
# ---------------------------------------------------------------------------

OVERPASS_URL = "https://overpass-api.de/api/interpreter"


def _post_overpass(query: str, label: str = ""):
    data = urllib.parse.urlencode({"data": query}).encode()
    req = urllib.request.Request(OVERPASS_URL, data=data, method="POST")
    req.add_header("User-Agent", "GolfGen-validator/1.0")
    try:
        with urllib.request.urlopen(req, timeout=40) as resp:
            return json.loads(resp.read())
    except Exception as e:
        print(f"[OSM] Overpass request failed ({label}): {e}", file=sys.stderr)
        return None


NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"


def _nominatim_bbox(course_name: str):
    """
    Use Nominatim (OSM geocoder) to find a golf course bounding box.
    Returns (south, west, north, east) or None.

    Strategy: prefer results with class=leisure / type=golf_course.
    Reject results whose bbox is too small to be a golf course (< 0.005° wide).
    """
    params = urllib.parse.urlencode({"q": course_name, "format": "json", "limit": 10})
    url = f"{NOMINATIM_URL}?{params}"
    req = urllib.request.Request(url)
    req.add_header("User-Agent", "GolfGen-validator/1.0")
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            results = json.loads(resp.read())
    except Exception as e:
        print(f"[OSM] Nominatim request failed: {e}", file=sys.stderr)
        return None

    def parse_bb(r):
        bb = r.get("boundingbox")
        if not bb:
            return None
        s, n, w, e = float(bb[0]), float(bb[1]), float(bb[2]), float(bb[3])
        # Golf courses are at least ~0.005° × 0.005° (~500m × 500m)
        if (n - s) < 0.005 or (e - w) < 0.005:
            return None
        return s, w, n, e

    # Pass 1: exact golf_course match
    for r in results:
        if r.get("type") == "golf_course":
            bb = parse_bb(r)
            if bb:
                print(f"[OSM] Nominatim matched golf_course: {r.get('display_name','')[:80]}")
                return bb

    # Pass 2: leisure class with valid bbox
    for r in results:
        if r.get("class") == "leisure":
            bb = parse_bb(r)
            if bb:
                print(f"[OSM] Nominatim matched leisure: {r.get('display_name','')[:80]}")
                return bb

    # Pass 3: any result with a plausible golf-course-sized bbox
    for r in results:
        bb = parse_bb(r)
        if bb:
            print(f"[OSM] Nominatim fallback match: {r.get('display_name','')[:80]}")
            return bb

    print(f"[OSM] No valid bbox found in Nominatim results for: {course_name}", file=sys.stderr)
    return None


def _fetch_overpass(course_name: str):
    """
    Two-step fetch:
    1. Nominatim geocodes the course name → bounding box.
    2. Overpass fetches all golf features in that bbox.
       Priority: golf=hole ways (ref + par + bbox for tee/green estimation).
       Fallback: golf=tee / golf=green with ref/name tags.
    """
    print(f"[OSM] Step 1: Nominatim geocoding '{course_name}'...")
    bbox = _nominatim_bbox(course_name)
    if not bbox:
        print(f"[OSM] Nominatim found nothing for: {course_name}", file=sys.stderr)
        return None

    south, west, north, east = bbox
    buf = 0.003
    south -= buf; north += buf; west -= buf; east += buf
    print(f"[OSM] Step 2: fetching golf features in bbox ({south:.4f},{west:.4f},{north:.4f},{east:.4f})...")

    # Fetch golf=hole ways (with bounding box) + tee/green nodes/ways
    features_query = f"""[out:json][timeout:40];
(
  way["golf"="hole"]({south},{west},{north},{east});
  way["golf"="tee"]({south},{west},{north},{east});
  way["golf"="green"]({south},{west},{north},{east});
  node["golf"="tee"]({south},{west},{north},{east});
  node["golf"="green"]({south},{west},{north},{east});
);
out center bb tags;"""

    return _post_overpass(features_query, "features")


def _ref_from_tags(tags: dict):
    """Extract hole number from ref, hole, or name tag. Returns int or None."""
    raw = tags.get("ref") or tags.get("hole") or tags.get("name")
    if raw is None:
        return None
    raw = str(raw).split("/")[0].split("-")[0].strip()
    try:
        ref = int(raw)
        return ref if 1 <= ref <= 18 else None
    except ValueError:
        return None


def _parse_osm_elements(osm_data: dict, grid: int = 350, margin: int = 30) -> list[dict]:
    """
    Extract per-hole tee/green positions and par from OSM elements.

    Strategy (in order of preference):
    1. golf=hole ways: ref + par in tags, bbox used to estimate tee/green corners.
    2. golf=tee / golf=green with ref/name: centroid per ref.

    Returns list of hole dicts or [] if < 9 holes are recoverable.
    """
    # --- Pass 1: golf=hole ways ---
    hole_ways: dict[int, dict] = {}
    tees: dict[int, list] = {}
    greens: dict[int, list] = {}

    for el in osm_data.get("elements", []):
        tags = el.get("tags", {})
        golf_type = tags.get("golf")

        if golf_type == "hole":
            ref = _ref_from_tags(tags)
            if ref is None:
                continue
            bounds = el.get("bounds") or {}
            center = el.get("center") or {}
            if not bounds and not center:
                continue
            par_raw = tags.get("par")
            try:
                par = int(par_raw) if par_raw else None
            except ValueError:
                par = None
            # Store first occurrence per ref (avoids multi-course duplicates)
            if ref not in hole_ways:
                hole_ways[ref] = {"bounds": bounds, "center": center, "par": par}

        elif golf_type in ("tee", "green"):
            ref = _ref_from_tags(tags)
            if ref is None:
                continue
            if el["type"] == "node":
                lat, lon = el.get("lat"), el.get("lon")
            else:
                c = el.get("center", {})
                lat, lon = c.get("lat"), c.get("lon")
            if lat is None:
                continue
            (tees if golf_type == "tee" else greens).setdefault(ref, []).append((lat, lon))

    # Build per-hole tee/green positions
    hole_positions: dict[int, dict] = {}

    if len(hole_ways) >= 9:
        # Use golf=hole centroids with sequential ordering for tee/green.
        # tee[N]   = centroid of hole N      (where the hole starts)
        # green[N] = centroid of hole N+1    (direction the golfer walks toward)
        # This captures real directional diversity from the course layout.
        centroids: dict[int, tuple] = {}
        pars: dict[int, int] = {}
        for ref, hw in hole_ways.items():
            center = hw["center"]
            bounds = hw["bounds"]
            lat = center.get("lat") or ((bounds.get("minlat", 0) + bounds.get("maxlat", 0)) / 2)
            lon = center.get("lon") or ((bounds.get("minlon", 0) + bounds.get("maxlon", 0)) / 2)
            centroids[ref] = (lat, lon)
            pars[ref] = hw["par"]

        sorted_refs = sorted(centroids.keys())
        for i, ref in enumerate(sorted_refs):
            c = centroids[ref]
            if i < len(sorted_refs) - 1:
                # Green ≈ centroid of next hole (real inter-hole direction)
                next_c = centroids[sorted_refs[i + 1]]
            else:
                # Hole 18: extrapolate direction from hole 17→18
                prev_c = centroids[sorted_refs[i - 1]]
                next_c = (2 * c[0] - prev_c[0], 2 * c[1] - prev_c[1])
            hole_positions[ref] = {
                "tee_ll": c,
                "green_ll": next_c,
                "par": pars[ref],
            }
        print(f"[OSM] Using golf=hole centroid strategy: {len(hole_positions)} holes")
    else:
        # Fallback: pair tee/green by ref
        complete = [h for h in tees if h in greens]
        if len(complete) < 9:
            print(f"[OSM] Insufficient data: {len(complete)} complete holes (need 9)", file=sys.stderr)
            return []

        def centroid(pts):
            return sum(p[0] for p in pts) / len(pts), sum(p[1] for p in pts) / len(pts)

        for ref in complete:
            hole_positions[ref] = {
                "tee_ll": centroid(tees[ref]),
                "green_ll": centroid(greens[ref]),
                "par": None,
            }
        print(f"[OSM] Using tee/green strategy: {len(hole_positions)} holes")

    if len(hole_positions) < 9:
        return []

    # Normalize lat/lon → grid coordinates
    all_lats = [v for hp in hole_positions.values() for v in (hp["tee_ll"][0], hp["green_ll"][0])]
    all_lons = [v for hp in hole_positions.values() for v in (hp["tee_ll"][1], hp["green_ll"][1])]
    min_lat, max_lat = min(all_lats), max(all_lats)
    min_lon, max_lon = min(all_lons), max(all_lons)
    lat_range = max_lat - min_lat or 1e-9
    lon_range = max_lon - min_lon or 1e-9
    usable = grid - 2 * margin

    def norm(lat, lon):
        x = margin + (lon - min_lon) / lon_range * usable
        y = margin + (1.0 - (lat - min_lat) / lat_range) * usable
        return [round(x, 2), round(y, 2)]

    holes = []
    for h in sorted(hole_positions.keys()):
        hp = hole_positions[h]
        tee = norm(*hp["tee_ll"])
        green = norm(*hp["green_ll"])
        par_raw = hp["par"]
        holes.append({
            "id": h,
            "par": par_raw,
            "tee": tee,
            "green": green,
            "waypoints": [tee, green],
            "fairway_width": 12,
            "source": "osm",
        })
    return holes


def _fill_missing_pars(holes: list, fallback_pars) -> list:
    """Fill None pars from fallback list or default to par 4."""
    for hole in holes:
        if hole["par"] is None:
            idx = hole["id"] - 1
            if fallback_pars and idx < len(fallback_pars):
                hole["par"] = fallback_pars[idx]
            else:
                hole["par"] = 4
    return holes


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Fetch golf course data for fitness validation")
    parser.add_argument("--course", help='Course name to search in OSM (e.g. "Pebble Beach Golf Links")')
    parser.add_argument("--fallback", choices=list(FALLBACK_COURSES), help="Use hardcoded fallback data directly")
    parser.add_argument("--output", required=True, help="Output JSON path")
    parser.add_argument("--grid", type=int, default=350, help="Grid size (default 350)")
    args = parser.parse_args()

    if not args.course and not args.fallback:
        parser.error("Provide --course or --fallback")

    holes = []
    fallback_key = None

    if args.fallback:
        fallback_key = args.fallback
        print(f"[INFO] Using hardcoded fallback: {FALLBACK_COURSES[fallback_key]['name']}")
        holes = build_from_fallback(fallback_key)
    else:
        print(f"[INFO] Querying Overpass API for: {args.course}")
        osm_data = _fetch_overpass(args.course)
        if osm_data:
            holes = _parse_osm_elements(osm_data, grid=args.grid)

        if holes:
            print(f"[INFO] OSM: found {len(holes)} holes with tee+green data")
            # Match fallback pars if course name matches a known course
            for key, fdata in FALLBACK_COURSES.items():
                if fdata["name"].lower() in args.course.lower():
                    fallback_key = key
                    break
            fb_pars = FALLBACK_COURSES[fallback_key]["pars"] if fallback_key else None
            holes = _fill_missing_pars(holes, fb_pars)
        else:
            # Try to match a fallback
            for key, fdata in FALLBACK_COURSES.items():
                if fdata["name"].lower() in args.course.lower():
                    fallback_key = key
                    break
            if fallback_key:
                print(f"[WARN] OSM coverage insufficient, using fallback: {FALLBACK_COURSES[fallback_key]['name']}")
                holes = build_from_fallback(fallback_key)
            else:
                print(f"[ERROR] OSM returned no usable data and no fallback found for: {args.course}", file=sys.stderr)
                sys.exit(1)

    output = {
        "course": args.course or FALLBACK_COURSES.get(fallback_key, {}).get("name", "unknown"),
        "holes": holes,
    }
    with open(args.output, "w") as f:
        json.dump(output, f, indent=2)
    print(f"[INFO] Written {len(holes)} holes → {args.output}")


if __name__ == "__main__":
    main()
