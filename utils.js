/**
 * Utilitaires math/geometrie pour GolfGen.
 */

/** Longueur d'une polyligne (somme des segments). */
function polylineLength(points) {
  let len = 0;
  for (let i = 1; i < points.length; i++) {
    const dx = points[i].x - points[i - 1].x;
    const dy = points[i].y - points[i - 1].y;
    len += Math.sqrt(dx * dx + dy * dy);
  }
  return Math.round(len);
}

/** Par automatique base sur la longueur en blocs. */
function autoPar(blocks) {
  if (blocks <= 70) return 3;
  if (blocks <= 155) return 4;
  return 5;
}

/** Largeur fairway automatique selon le par. */
function autoFairwayWidth(par) {
  if (par === 3) return 9;
  if (par === 5) return 13;
  return 12;
}

/** Label de direction (N, NE, E, SE, S, SW, W, NW). */
function directionLabel(from, to) {
  const dx = to.x - from.x;
  const dy = to.y - from.y;
  const angle = Math.atan2(dy, dx) * (180 / Math.PI);
  const dirs = ['E', 'SE', 'S', 'SW', 'W', 'NW', 'N', 'NE'];
  const idx = Math.round(((angle + 360) % 360) / 45) % 8;
  return dirs[idx];
}

/** Distance point-segment. */
function pointToSegDist(px, py, ax, ay, bx, by) {
  const dx = bx - ax;
  const dy = by - ay;
  const len2 = dx * dx + dy * dy;
  if (len2 === 0) return Math.hypot(px - ax, py - ay);
  let t = ((px - ax) * dx + (py - ay) * dy) / len2;
  t = Math.max(0, Math.min(1, t));
  return Math.hypot(px - (ax + t * dx), py - (ay + t * dy));
}

/**
 * Lissage Chaikin (corner-cutting).
 * Chaque arête est subdivisée en deux points à 1/4 et 3/4.
 * @param {Array<{x,y}>} points
 * @param {number} iterations
 * @param {boolean} closed - true pour polygone fermé, false pour polyligne ouverte
 */
function smoothChaikin(points, iterations, closed) {
  let pts = points.slice();
  for (let k = 0; k < iterations; k++) {
    const n = pts.length;
    const result = [];
    const limit = closed ? n : n - 1;
    for (let i = 0; i < limit; i++) {
      const p0 = pts[i];
      const p1 = pts[(i + 1) % n];
      result.push({ x: 0.75 * p0.x + 0.25 * p1.x, y: 0.75 * p0.y + 0.25 * p1.y });
      result.push({ x: 0.25 * p0.x + 0.75 * p1.x, y: 0.25 * p0.y + 0.75 * p1.y });
    }
    pts = closed ? result : [pts[0], ...result, pts[n - 1]];
  }
  return pts;
}

/** Test si un point (px, py) est dans un polygone (ray casting). */
function pointInPolygon(px, py, points) {
  let inside = false;
  for (let i = 0, j = points.length - 1; i < points.length; j = i++) {
    const xi = points[i].x, yi = points[i].y;
    const xj = points[j].x, yj = points[j].y;
    if (((yi > py) !== (yj > py)) && (px < (xj - xi) * (py - yi) / (yj - yi) + xi))
      inside = !inside;
  }
  return inside;
}

/**
 * Simplification Ramer-Douglas-Peucker.
 * Reduit une polyligne en gardant les points significatifs.
 * @param {Array<{x,y}>} points
 * @param {number} epsilon - tolerance (en blocs monde)
 * @returns {Array<{x,y}>}
 */
function simplifyRDP(points, epsilon) {
  if (points.length <= 2) return points.slice();

  // Trouver le point le plus eloigne du segment first-last
  const first = points[0];
  const last = points[points.length - 1];
  let maxDist = 0;
  let maxIdx = 0;

  for (let i = 1; i < points.length - 1; i++) {
    const d = pointToSegDist(points[i].x, points[i].y, first.x, first.y, last.x, last.y);
    if (d > maxDist) {
      maxDist = d;
      maxIdx = i;
    }
  }

  if (maxDist > epsilon) {
    const left = simplifyRDP(points.slice(0, maxIdx + 1), epsilon);
    const right = simplifyRDP(points.slice(maxIdx), epsilon);
    return left.slice(0, -1).concat(right);
  } else {
    return [first, last];
  }
}
