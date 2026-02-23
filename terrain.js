/**
 * Generation de terrain procedural — OpenSimplex multi-octave + gradient N-S.
 * Port JS de golfgen/terrain.py.
 *
 * Simplex noise 2D inline (pas de dependance CDN).
 * Adapte de simplex-noise par Jonas Wagner (MIT).
 */

// --- Simplex Noise 2D inline ---
const F2 = 0.5 * (Math.sqrt(3) - 1);
const G2 = (3 - Math.sqrt(3)) / 6;

const GRAD2 = [
  [1, 1], [-1, 1], [1, -1], [-1, -1],
  [1, 0], [-1, 0], [0, 1], [0, -1],
];

function buildPermTable(rng) {
  const perm = new Uint8Array(512);
  const p = new Uint8Array(256);
  for (let i = 0; i < 256; i++) p[i] = i;
  // Fisher-Yates shuffle
  for (let i = 255; i > 0; i--) {
    const j = Math.floor(rng() * (i + 1));
    [p[i], p[j]] = [p[j], p[i]];
  }
  for (let i = 0; i < 512; i++) perm[i] = p[i & 255];
  return perm;
}

function createNoise2D(rng) {
  const perm = buildPermTable(rng);

  return function noise2D(x, y) {
    const s = (x + y) * F2;
    const i = Math.floor(x + s);
    const j = Math.floor(y + s);
    const t = (i + j) * G2;
    const X0 = i - t;
    const Y0 = j - t;
    const x0 = x - X0;
    const y0 = y - Y0;

    let i1, j1;
    if (x0 > y0) { i1 = 1; j1 = 0; }
    else { i1 = 0; j1 = 1; }

    const x1 = x0 - i1 + G2;
    const y1 = y0 - j1 + G2;
    const x2 = x0 - 1 + 2 * G2;
    const y2 = y0 - 1 + 2 * G2;

    const ii = i & 255;
    const jj = j & 255;

    let n0 = 0, n1 = 0, n2 = 0;

    let t0 = 0.5 - x0 * x0 - y0 * y0;
    if (t0 > 0) {
      t0 *= t0;
      const gi = perm[ii + perm[jj]] & 7;
      n0 = t0 * t0 * (GRAD2[gi][0] * x0 + GRAD2[gi][1] * y0);
    }

    let t1 = 0.5 - x1 * x1 - y1 * y1;
    if (t1 > 0) {
      t1 *= t1;
      const gi = perm[ii + i1 + perm[jj + j1]] & 7;
      n1 = t1 * t1 * (GRAD2[gi][0] * x1 + GRAD2[gi][1] * y1);
    }

    let t2 = 0.5 - x2 * x2 - y2 * y2;
    if (t2 > 0) {
      t2 *= t2;
      const gi = perm[ii + 1 + perm[jj + 1]] & 7;
      n2 = t2 * t2 * (GRAD2[gi][0] * x2 + GRAD2[gi][1] * y2);
    }

    return 70 * (n0 + n1 + n2);
  };
}

// --- PRNG seede (mulberry32) ---
function mulberry32(seed) {
  return function () {
    seed |= 0;
    seed = (seed + 0x6d2b79f5) | 0;
    let t = Math.imul(seed ^ (seed >>> 15), 1 | seed);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

/**
 * @param {Object} config
 * @param {number} config.width       - Largeur grille (defaut 350)
 * @param {number} config.height      - Hauteur grille (defaut 350)
 * @param {number} config.seed        - Seed du PRNG (defaut 42)
 * @param {number} config.octaves     - Nombre d'octaves (defaut 6)
 * @param {number} config.persistence - Reduction amplitude par octave (defaut 0.5)
 * @param {number} config.scale       - Diviseur de frequence (defaut 120)
 * @param {number} config.elevationMin - Elevation minimum (defaut 58)
 * @param {number} config.elevationMax - Elevation maximum (defaut 82)
 * @param {number} config.nsGradient  - Amplitude gradient nord-sud (defaut 0.15)
 * @returns {{ heightmap: Uint8Array, width: number, height: number, minElevation: number, maxElevation: number }}
 */
window.generateTerrain = function generateTerrain(config = {}) {
  const w = config.width || 350;
  const h = config.height || 350;
  const seed = config.seed ?? 42;
  const octaves = config.octaves || 6;
  const persistence = config.persistence || 0.5;
  const scale = config.scale || 120.0;
  const elevMin = config.elevationMin ?? 58;
  const elevMax = config.elevationMax ?? 82;
  const nsGradient = config.nsGradient ?? 0.15;

  const rng = mulberry32(seed);
  const noise2D = createNoise2D(rng);

  // Multi-octave noise
  const raw = new Float64Array(w * h);
  let amplitude = 1.0;
  let frequency = 1.0;
  let maxAmplitude = 0;

  for (let oct = 0; oct < octaves; oct++) {
    for (let y = 0; y < h; y++) {
      for (let x = 0; x < w; x++) {
        const nx = (x * frequency) / scale;
        const ny = (y * frequency) / scale;
        raw[y * w + x] += noise2D(nx, ny) * amplitude;
      }
    }
    maxAmplitude += amplitude;
    amplitude *= persistence;
    frequency *= 2.0;
  }

  // Normaliser par amplitude max
  for (let i = 0; i < raw.length; i++) {
    raw[i] /= maxAmplitude;
  }

  // Gradient nord-sud
  for (let y = 0; y < h; y++) {
    const grad = nsGradient - (2 * nsGradient * y) / (h - 1);
    for (let x = 0; x < w; x++) {
      raw[y * w + x] += grad;
    }
  }

  // Trouver min/max
  let rawMin = Infinity;
  let rawMax = -Infinity;
  for (let i = 0; i < raw.length; i++) {
    if (raw[i] < rawMin) rawMin = raw[i];
    if (raw[i] > rawMax) rawMax = raw[i];
  }

  // Normaliser vers [0, 255] -> Uint8Array
  const range = rawMax - rawMin || 1;
  const heightmap = new Uint8Array(w * h);
  for (let i = 0; i < raw.length; i++) {
    heightmap[i] = Math.round(((raw[i] - rawMin) / range) * 255);
  }

  return {
    heightmap,
    width: w,
    height: h,
    minElevation: elevMin,
    maxElevation: elevMax,
  };
};
