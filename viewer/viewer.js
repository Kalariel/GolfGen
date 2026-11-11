/**
 * Viewer de parcours de golf — lit le JSON 3.x produit par `pipeline.py`
 * (routeur Muirfield, contrat dans docs/format-3.0.md).
 * Affiche le relief, les 18 trous, les liaisons et le clubhouse ; en 3.1,
 * l'habillage (`holes[].features` : fairways, contours de greens et boîtes de
 * départ), détecté par présence et non par version. Avec `features.fairway`,
 * le rough est la surface par défaut (toute terre ferme qu'aucun élément ne
 * couvre) et les trous se lisent départ -> fairway -> green ; sans cette clé
 * (3.0, 3.1 d'avant R5), couloir tee -> doglegs -> green (largeur totale du
 * fairway). Option « Debug » : couloirs, axes, sens de jeu et contour de la
 * bande de jeu (cœur + rough_margin). En 3.2, les bunkers (clé de premier
 * niveau `bunkers`, détectée par présence) : cases de sable sur le rough et
 * les fairways, sous les greens et les départs. En 3.3, les chemins (clé de
 * premier niveau `paths`, détectée par présence) : cases de terre battue sur
 * le sable et le rough, ponts en bois par-dessus, parvis du clubhouse d'une
 * nuance proche, sous les greens et les départs ; ancrages des virages en
 * option. Avec des chemins, les liaisons droites en tirets (redondantes)
 * sont masquées par défaut, toujours accessibles par leur bouton. En 3.4,
 * les arbres (clé de premier niveau `trees`, détectée par présence) : cercles
 * de rayon réel, sous le sable, les chemins, les greens et les départs ; une
 * seule couleur, ou une couleur par couche sous Debug. Le bouton « Arbres »
 * n'existe qu'avec la clé.
 * Zoom/pan interactif.
 * Tout autre format est refusé avec un message à l'écran.
 */

// === State ===
let courseData = null;
let heightmapPixels = null; // Uint8Array (octets 0..255 normalisés sur [min, max])
let terrainCache = null;    // canvas terrain 1:1
let waterCache = null;      // canvas 1:1 de l'eau seule, repeinte sur le rough
let bunkerCache = null;     // canvas 1:1 du sable seul (3.2), null sans clé `bunkers`
let bunkerEdges = null;     // Path2D (blocs) des bords du sable, liseré
let bunkerCounts = null;    // Map trou -> nombre de bunkers posés, null sans clé `bunkers`
let pathCache = null;       // canvas 1:1 des chemins, ponts et parvis (3.3), null sans clé `paths`
let pathEdges = null;       // Path2D (blocs) des bords entre surfaces de chemin, liseré
let pathAnchors = null;     // cases [x, z] des ancrages des virages (3.3), null sans clé `paths`
let treeUnion = null;       // Path2D (blocs) de toutes les couronnes (3.4), null sans clé `trees`
let treeLayers = null;      // Map couche -> Path2D (blocs) des couronnes (3.4), null sans clé `trees`
let fairwayPainted = false; // paintsFairway() du fichier chargé, calculé une fois au chargement
let mapW = 0;               // blocs
let mapH = 0;               // blocs
let blockM = 3;             // mètres par bloc (metadata.block_m)

// Camera
let camZoom = 1.0;
let camPanX = 0;
let camPanY = 0;
const MIN_ZOOM = 0.5;
const MAX_ZOOM = 10;

// Layers
let show = {
  terrain: true,
  holes: true,
  links: true,
  grid: true,
  nums: true,
  dressing: true,
  bunkers: true,
  paths: true,     // chemins, ponts et parvis (3.3)
  anchors: false,  // ancrages des virages (3.3)
  trees: true,     // arbres (3.4)
  debug: false,  // couloirs, axes, sens de jeu et bande de jeu
};

let highlightedHole = null;
let currentMessage = null;  // lignes du message affiché à la place de la carte

// Pan state
let isPanning = false;
let panStartX = 0, panStartY = 0;
let panStartCamX = 0, panStartCamY = 0;

// === Conventions visuelles (reprises de tools/muirfield/render_readable.py) ===
const PAR_COLORS = { 3: '#58a6ff', 4: '#56d364', 5: '#f2cc60' };
const C = {
  ink: '#0d1117',
  paper: '#f0f6fc',
  green: '#3dbd4e',
  greenShape: '#9be58f',     // green habillé (3.1) : vert clair...
  greenEdge: '#2b7a34',      // ...avec contour
  teeShape: '#d2a8ff',       // boîtes de départ (3.1) : lilas, hors palette des pars...
  teeEdge: '#0d1117',        // ...cerné d'encre
  flag: '#e5534b',
  link: '#e6edf3',
  club: '#e5534b',
  rough: '#557f3e',          // rough : surface par défaut, translucide sur le relief...
  fairway: '#7fb85e',        // ...fairway plus clair, sous le vert du green...
  fairwayEdge: '#2f5124',    // ...cerné d'un liseré
  sand: '#e8d9a8',           // bunkers (3.2) : beige sable pâle, une couleur pour toutes les familles...
  sandEdge: '#a68c50',       // ...liseré plus sombre aux bords des cases
  path: '#c9a46a',           // chemins (3.3) : terre battue de la planche d'étude...
  bridge: '#8b5a2b',         // ...ponts en bois par-dessus...
  plaza: '#b08a55',          // ...parvis du clubhouse, nuance plus foncée...
  pathEdge: '#5c4022',       // ...liseré brun aux bords (chemin, pont, parvis, rough)
  anchor: '#14420f',         // ancrages des virages : repère vert foncé...
  anchorRing: '#f0f6fc',     // ...cerné de clair
  tree: '#10481c',           // arbres (3.4) : vert foncé des planches d'étude...
  treeEdge: '#06230c',       // ...cerné plus sombre
};
// Couleur des arbres par couche sous Debug (autre couche : C.tree).
const TREE_DEBUG_COLORS = {
  retombee: '#f08a1a', green: '#d61fb0', ancrage: '#20c4e8', lisiere: '#7b5cff', remplissage: '#1f7a3a',
};
const TREE_ALPHA = 0.82;     // opacité des couronnes : le rough reste lisible dessous
const ROUGH_ALPHA = 0.6;     // opacité du rough : le relief reste lisible dessous
const LABEL_BACKOFF = 11.0;  // numéro du trou posé derrière le tee (blocs)
const GREEN_RADIUS = 4.5;    // rayon d'affichage du green (blocs)

const NINE_LABEL = { front: 'aller', back: 'retour' };
const TURN_LABEL = { clockwise: 'horaire', counterclockwise: 'antihoraire' };
const ORIENTATION_LABEL = { landscape: 'paysage', portrait: 'portrait', square: 'carre' };

// === DOM ===
const canvas = document.getElementById('map');
const ctx = canvas.getContext('2d');
const tooltip = document.getElementById('tooltip');
const coordsEl = document.getElementById('coords');

// === Utils ===
function esc(value) {
  return String(value)
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
}

function fmtBlocks(blocks) {
  return `${Number(blocks).toFixed(1)} blocs`;
}

function fmtMeters(blocks) {
  return `${Math.round(blocks * blockM)} m`;
}

function holeAxis(h) {
  return [h.tee, ...(h.doglegs || []), h.green];
}

/** Contour du green habillé (3.1, `features.green.outline`), sinon null. */
function greenOutline(h) {
  const g = h.features && h.features.green;
  return g && Array.isArray(g.outline) && g.outline.length >= 3 ? g.outline : null;
}

/**
 * Contours des boîtes de départ (3.1, `features.tees[].outline`, de l'arrière
 * vers l'avant), sinon null (clé absente : 3.0, ou 3.1 d'avant les départs).
 */
function teeOutlines(h) {
  const t = h.features && h.features.tees;
  if (!Array.isArray(t)) return null;
  const outlines = t
    .map(box => box && box.outline)
    .filter(o => Array.isArray(o) && o.length >= 3);
  return outlines.length ? outlines : null;
}

/**
 * Morceaux du fairway (3.1 R5, `features.fairway[].outline`, le principal
 * d'abord) : null si la clé est absente (fichier d'avant R5), [] si l'eau a
 * vidé le fairway.
 */
function fairwayOutlines(h) {
  const f = h.features && h.features.fairway;
  if (!Array.isArray(f)) return null;
  return f
    .map(piece => piece && piece.outline)
    .filter(o => Array.isArray(o) && o.length >= 3);
}

/**
 * Greens doubles (3.1, `routing.green_pairs` : `{holes: [i, j], outline, area}`)
 * aux contours lisibles (sommets `{x, y}` finis ; paire ignorée sinon), sinon [] (clé absente : 3.0, ou 3.1 d'avant les
 * greens doubles ; liste vide : aucun green double).
 */
function greenPairs() {
  const pairs = courseData && courseData.routing ? courseData.routing.green_pairs : null;
  if (!Array.isArray(pairs)) return [];
  const isPoint = q => q && typeof q === 'object'
    && Number.isFinite(q.x) && Number.isFinite(q.y);
  return pairs.filter(p => p && Array.isArray(p.holes) && p.holes.length === 2
    && Array.isArray(p.outline) && p.outline.length >= 3 && p.outline.every(isPoint));
}

/** Green double du trou `id` : `{partner, area}` (area éventuellement absente), sinon null. */
function greenPairOf(id) {
  for (const p of greenPairs()) {
    const k = p.holes.indexOf(id);
    if (k >= 0) return { partner: p.holes[1 - k], area: p.area };
  }
  return null;
}

/**
 * Vrai si au moins un trou porte la clé `features.fairway` (même vide) :
 * rendu rough + fairways ; sinon (3.0, 3.1 d'avant R5) rendu en couloir.
 */
function paintsFairway() {
  const holes = courseData && courseData.routing ? courseData.routing.holes || [] : [];
  return holes.some(h => fairwayOutlines(h) !== null);
}

/** Fairway du trou pour le tooltip : `{pieces, area}`, `{pieces: 0}` si vidé, sinon null. */
function fairwaySummary(h) {
  const f = h.features && h.features.fairway;
  if (!Array.isArray(f)) return null;
  const pieces = f.filter(p => p && Array.isArray(p.outline) && p.outline.length >= 3);
  const area = pieces.reduce((sum, p) => sum + (Number.isFinite(Number(p.area)) ? Number(p.area) : 0), 0);
  return { pieces: pieces.length, area };
}

function hasDressing() {
  const holes = courseData && courseData.routing ? courseData.routing.holes || [] : [];
  return holes.some(h => greenOutline(h) !== null || teeOutlines(h) !== null)
    || greenPairs().length > 0;
}

/** Bouton « Habillage » : désactivé si le fichier n'a ni `features` ni `green_pairs`. */
function updateDressingButton() {
  const btn = document.getElementById('btn-dressing');
  if (btn) btn.disabled = !hasDressing();
}

// === Init ===
function init() {
  document.getElementById('file-input').addEventListener('change', handleFileLoad);
  // La hauteur de l'en-tête suit ses polices et son contenu : on suit la zone
  // de carte elle-même plutôt que la seule fenêtre.
  if (window.ResizeObserver) {
    new ResizeObserver(() => resizeCanvas()).observe(document.querySelector('.canvas-wrapper'));
  } else {
    window.addEventListener('resize', resizeCanvas);
  }

  canvas.addEventListener('wheel', onWheel, { passive: false });
  canvas.addEventListener('mousedown', onMouseDown);
  window.addEventListener('mousemove', onMouseMove);
  window.addEventListener('mouseup', onMouseUp);
  canvas.addEventListener('mouseleave', onMouseLeave);

  // Le canvas ne recharge pas seul ses polices : redessiner une fois chargées.
  if (document.fonts && document.fonts.ready) {
    document.fonts.ready.then(() => resizeCanvas());
  }

  resizeCanvas();
  tryAutoLoad();
}

function resizeCanvas() {
  const wrapper = document.querySelector('.canvas-wrapper');
  const rect = wrapper.getBoundingClientRect();
  canvas.width = Math.floor(rect.width);
  canvas.height = Math.floor(rect.height);
  if (courseData) draw();
  else if (currentMessage) showMessage(currentMessage);
  else showNoData();
}

// === Camera ===
function toCanvas(wx, wy) {
  return [wx * camZoom + camPanX, wy * camZoom + camPanY];
}

function toWorld(sx, sy) {
  return [(sx - camPanX) / camZoom, (sy - camPanY) / camZoom];
}

function fitView() {
  if (!courseData || mapW <= 0 || mapH <= 0) return;
  const fit = 0.94 * Math.min(canvas.width / mapW, canvas.height / mapH);
  camZoom = Math.max(MIN_ZOOM, Math.min(MAX_ZOOM, fit));
  camPanX = (canvas.width - mapW * camZoom) / 2;
  camPanY = (canvas.height - mapH * camZoom) / 2;
}

function resetView() {
  fitView();
  updateZoomDisplay();
  draw();
}

function zoomIn() {
  zoomAt(canvas.width / 2, canvas.height / 2, 1.3);
}

function zoomOut() {
  zoomAt(canvas.width / 2, canvas.height / 2, 0.77);
}

function zoomAt(sx, sy, factor) {
  const [wx, wy] = toWorld(sx, sy);
  camZoom = Math.max(MIN_ZOOM, Math.min(MAX_ZOOM, camZoom * factor));
  camPanX = sx - wx * camZoom;
  camPanY = sy - wy * camZoom;
  updateZoomDisplay();
  draw();
}

function updateZoomDisplay() {
  const el = document.getElementById('zoom-level');
  if (el) el.textContent = `${Math.round(camZoom * 100)}%`;
}

// === Zoom/Pan Events ===
function onWheel(e) {
  e.preventDefault();
  const factor = e.deltaY > 0 ? 0.9 : 1.111;
  const rect = canvas.getBoundingClientRect();
  zoomAt(e.clientX - rect.left, e.clientY - rect.top, factor);
}

function onMouseDown(e) {
  if (e.button === 0) {
    isPanning = true;
    panStartX = e.clientX;
    panStartY = e.clientY;
    panStartCamX = camPanX;
    panStartCamY = camPanY;
    canvas.style.cursor = 'grabbing';
  }
}

function onMouseMove(e) {
  const rect = canvas.getBoundingClientRect();
  const mx = e.clientX - rect.left;
  const my = e.clientY - rect.top;

  if (isPanning) {
    camPanX = panStartCamX + (e.clientX - panStartX);
    camPanY = panStartCamY + (e.clientY - panStartY);
    draw();
    updateCoords(mx, my);
    return;
  }

  if (mx >= 0 && mx <= rect.width && my >= 0 && my <= rect.height) {
    updateTooltip(e.clientX, e.clientY, mx, my);
  }
}

function onMouseUp() {
  if (isPanning) {
    isPanning = false;
    canvas.style.cursor = 'crosshair';
  }
}

function onMouseLeave() {
  tooltip.style.display = 'none';
  if (highlightedHole !== null) setHighlight(null);
}

// === File Loading ===
// `?json=<url>` remplace le chargement automatique de ../output/course.json
// (utile pour comparer deux fichiers ou tester le refus d'un format) ; seule
// une URL de même origine que le viewer est acceptée.
async function tryAutoLoad() {
  const param = new URLSearchParams(window.location.search).get('json');
  const fileLabel = document.getElementById('filename');
  let url;
  if (param) {
    let target = null;
    try {
      target = new URL(param, window.location.href);
    } catch (e) {
      target = null;
    }
    // En file://, les deux origines valent « null », comme celle d'une URL
    // data: : une origine opaque est donc toujours refusée.
    if (!target || target.origin === 'null' || target.origin !== window.location.origin) {
      rejectData([
        '?json= refuse',
        `URL hors de l'origine du viewer : ${param}`,
        window.location.origin === 'null'
          ? 'Viewer ouvert en file:// : le servir en http pour utiliser ?json=.'
          : `Seules les URL de ${window.location.origin} sont acceptees.`,
      ]);
      fileLabel.textContent = '?json= refuse';
      return;
    }
    url = target.href;
  } else {
    url = '../output/course.json';
  }
  const name = url.split('?')[0].split('/').pop();

  let resp;
  try {
    resp = await fetch(url);
  } catch (err) {
    if (!param) {
      showNoData();
      return;
    }
    rejectData(['Chargement impossible', `${name} : ${String(err.message)}`]);
    fileLabel.textContent = `${name} (refuse)`;
    return;
  }
  if (!resp.ok) {
    if (!param && resp.status === 404) {
      showNoData();  // pas encore de output/course.json : écran d'accueil
      return;
    }
    rejectData(['Chargement impossible', `${name} : HTTP ${resp.status} ${resp.statusText}`.trim()]);
    fileLabel.textContent = `${name} (refuse)`;
    return;
  }
  let json;
  try {
    json = JSON.parse(await resp.text());
  } catch (err) {
    rejectData(['JSON illisible', String(err.message)]);
    fileLabel.textContent = `${name} (refuse)`;
    return;
  }
  fileLabel.textContent = loadCourseData(json) ? `${name} (auto)` : `${name} (refuse)`;
}

function handleFileLoad(e) {
  const file = e.target.files[0];
  if (!file) return;
  const reader = new FileReader();
  reader.onload = (ev) => {
    let json;
    try {
      json = JSON.parse(ev.target.result);
    } catch (err) {
      rejectData(['JSON illisible', String(err.message)]);
      document.getElementById('filename').textContent = `${file.name} (refuse)`;
      return;
    }
    const ok = loadCourseData(json);
    document.getElementById('filename').textContent = ok ? file.name : `${file.name} (refuse)`;
  };
  reader.readAsText(file);
}

/** Renvoie null si le fichier est un 3.x lisible, sinon les lignes du message d'erreur. */
function checkFormat(json) {
  const version = json && json.metadata ? json.metadata.version : undefined;
  if (version === undefined || version === null) {
    return ['Format non reconnu', 'metadata.version absent : ce viewer lit le format 3.x.'];
  }
  if (!/^3(\.\d+)?$/.test(String(version))) {
    return [
      `Format ${version} non pris en charge`,
      'Ce viewer lit le format 3.x (routeur Muirfield, docs/format-3.0.md).',
      'Regenerer le parcours : python pipeline.py --seed 4',
    ];
  }
  const meta = json.metadata;
  const hasSize = (json.terrain && json.terrain.width && json.terrain.height)
    || (meta.width && meta.height);
  if (!hasSize) {
    return [`Format ${version} incomplet`, 'Ni terrain.width/height ni metadata.width/height.'];
  }
  return null;
}

function rejectData(lines) {
  courseData = null;
  heightmapPixels = null;
  terrainCache = null;
  waterCache = null;
  clearBunkers();
  clearPaths();
  clearTrees();
  fairwayPainted = false;
  highlightedHole = null;
  tooltip.style.display = 'none';
  resetHeader();
  const info = document.getElementById('course-info');
  info.innerHTML = `<div class="info-box error-box"><strong>${esc(lines[0])}</strong><br>`
    + lines.slice(1).map(esc).join('<br>') + '</div>';
  resetHoleList();
  updateBunkersButton();
  updatePathsButtons();
  updateTreesButton();
  showMessage(lines);
}

/** Charge un JSON ; renvoie false (et affiche le refus) s'il n'est pas lisible. */
function loadCourseData(json) {
  const problem = checkFormat(json);
  if (problem) {
    rejectData(problem);
    return false;
  }
  try {
    currentMessage = null;
    courseData = json;
    heightmapPixels = null;
    terrainCache = null;
    waterCache = null;
    clearBunkers();
    clearPaths();
    clearTrees();
    fairwayPainted = paintsFairway();
    highlightedHole = null;

    const meta = json.metadata;
    mapW = Number((json.terrain && json.terrain.width) || meta.width);
    mapH = Number((json.terrain && json.terrain.height) || meta.height);
    blockM = Number(meta.block_m) || 3;

    if (json.terrain && json.terrain.elevation && json.terrain.elevation.data) {
      const binary = atob(json.terrain.elevation.data);
      heightmapPixels = new Uint8Array(binary.length);
      for (let i = 0; i < binary.length; i++) {
        heightmapPixels[i] = binary.charCodeAt(i);
      }
      if (heightmapPixels.length === json.terrain.width * json.terrain.height) {
        buildTerrainCache();
      } else {
        heightmapPixels = null;
      }
    }

    buildBunkerCache();
    buildPathCache();
    buildTreePaths();
    // chemins présents : les liaisons droites (redondantes) masquées par
    // défaut, réaffichables par leur bouton ; sans chemins, affichées
    setLayer('links', !hasPaths());
    setLayer('trees', true);

    updateHeader();
    updateSidebar();
    updateDressingButton();
    updateBunkersButton();
    updatePathsButtons();
    updateTreesButton();
    fitView();
    updateZoomDisplay();
    draw();
    return true;
  } catch (err) {
    rejectData(['Fichier 3.x illisible', String(err.message)]);
    return false;
  }
}

// Relief : rampe de couleur sur l'octet normalisé (0 = min, 255 = max du
// bloc terrain). Sous `terrain.water_level` (altitude, mêmes unités que
// min/max_elevation), le pixel est de l'eau, comme pour le routeur et les
// planches PNG (même couleur que render_readable) ; sans ce champ, pas d'eau.
const WATER_RGB = [0x1d, 0x4f, 0x73];

/** Octet seuil : un pixel d'octet < seuil est sous l'eau ; 0 = pas d'eau. */
function waterThreshold(terrain) {
  const level = Number(terrain.water_level);
  const elev = terrain.elevation || {};
  const lo = Number(elev.min_elevation);
  const hi = Number(elev.max_elevation);
  if (terrain.water_level === undefined || terrain.water_level === null
      || !Number.isFinite(level) || !Number.isFinite(lo) || !Number.isFinite(hi)) {
    return 0;
  }
  if (hi - lo < 1e-10) return level > lo ? 256 : 0;  // relief plat
  // altitude = min + octet / 255 × (max − min) < level
  return Math.max(0, Math.min(256, Math.ceil((level - lo) / (hi - lo) * 255)));
}

function buildTerrainCache() {
  const w = courseData.terrain.width;
  const h = courseData.terrain.height;
  const water = waterThreshold(courseData.terrain);
  const oc = document.createElement('canvas');
  oc.width = w;
  oc.height = h;
  const octx = oc.getContext('2d');
  const imageData = octx.createImageData(w, h);
  const pixels = imageData.data;

  for (let idx = 0; idx < w * h; idx++) {
    const v = heightmapPixels[idx];
    const [r, g, b] = v < water ? WATER_RGB : reliefColor(v / 255);
    const p = idx * 4;
    pixels[p] = r;
    pixels[p + 1] = g;
    pixels[p + 2] = b;
    pixels[p + 3] = 255;
  }
  octx.putImageData(imageData, 0, 0);
  terrainCache = oc;
  if (fairwayPainted) buildWaterCache(water);
}

/** Eau seule (transparente ailleurs), repeinte par-dessus le rough. */
function buildWaterCache(water) {
  const w = courseData.terrain.width;
  const h = courseData.terrain.height;
  const oc = document.createElement('canvas');
  oc.width = w;
  oc.height = h;
  const octx = oc.getContext('2d');
  const imageData = octx.createImageData(w, h);
  const pixels = imageData.data;
  for (let idx = 0; idx < w * h; idx++) {
    if (heightmapPixels[idx] >= water) continue;
    const p = idx * 4;
    pixels[p] = WATER_RGB[0];
    pixels[p + 1] = WATER_RGB[1];
    pixels[p + 2] = WATER_RGB[2];
    pixels[p + 3] = 255;
  }
  octx.putImageData(imageData, 0, 0);
  waterCache = oc;
}

function clearBunkers() {
  bunkerCache = null;
  bunkerEdges = null;
  bunkerCounts = null;
}

/** Vrai si le fichier porte la clé `bunkers` (3.2), quelle que soit la version. */
function hasBunkers() {
  return Boolean(courseData && courseData.bunkers && typeof courseData.bunkers === 'object');
}

/** Vrai si le trou est listé dans `bunkers.empty_holes` (laissé sans bunker). */
function emptyBunkerHole(id) {
  const empty = hasBunkers() ? courseData.bunkers.empty_holes : null;
  return Array.isArray(empty) && empty.includes(id);
}

/** Bouton « Bunkers » : désactivé si le fichier n'a pas de clé `bunkers`. */
function updateBunkersButton() {
  const btn = document.getElementById('btn-bunkers');
  if (btn) btn.disabled = !hasBunkers();
}

/**
 * Sable des bunkers (3.2) : la case `[x, z]` couvre `[x, x+1] × [z, z+1]`
 * (blocs, z vers le bas). Pixels 1:1 (sable seul, transparent ailleurs) et
 * chemin des bords entre sable et non-sable, en blocs, pour un liseré fin
 * indépendant du zoom ; décomptes par trou. Cases invalides ou hors carte
 * ignorées. Sans clé `bunkers` : rien (3.0/3.1 inchangés).
 */
function buildBunkerCache() {
  if (!hasBunkers() || !(mapW > 0) || !(mapH > 0)) return;
  const items = Array.isArray(courseData.bunkers.items) ? courseData.bunkers.items : [];
  const w = mapW;
  const h = mapH;
  const sand = new Uint8Array(w * h);
  const counts = new Map();
  items.forEach(item => {
    if (!item || !Array.isArray(item.cells)) return;
    counts.set(item.hole, (counts.get(item.hole) || 0) + 1);
    item.cells.forEach(c => {
      if (!Array.isArray(c)) return;
      const x = Number(c[0]);
      const z = Number(c[1]);
      if (!Number.isInteger(x) || !Number.isInteger(z) || x < 0 || z < 0 || x >= w || z >= h) return;
      sand[z * w + x] = 1;
    });
  });
  bunkerCounts = counts;

  const oc = document.createElement('canvas');
  oc.width = w;
  oc.height = h;
  const octx = oc.getContext('2d');
  const imageData = octx.createImageData(w, h);
  const pixels = imageData.data;
  const rgb = [1, 3, 5].map(i => parseInt(C.sand.slice(i, i + 2), 16));
  const edges = new Path2D();
  const isSand = (x, z) => x >= 0 && z >= 0 && x < w && z < h && sand[z * w + x] === 1;
  for (let z = 0; z < h; z++) {
    for (let x = 0; x < w; x++) {
      if (!sand[z * w + x]) continue;
      const p = (z * w + x) * 4;
      pixels[p] = rgb[0];
      pixels[p + 1] = rgb[1];
      pixels[p + 2] = rgb[2];
      pixels[p + 3] = 255;
      if (!isSand(x, z - 1)) { edges.moveTo(x, z); edges.lineTo(x + 1, z); }
      if (!isSand(x, z + 1)) { edges.moveTo(x, z + 1); edges.lineTo(x + 1, z + 1); }
      if (!isSand(x - 1, z)) { edges.moveTo(x, z); edges.lineTo(x, z + 1); }
      if (!isSand(x + 1, z)) { edges.moveTo(x + 1, z); edges.lineTo(x + 1, z + 1); }
    }
  }
  octx.putImageData(imageData, 0, 0);
  bunkerCache = oc;
  bunkerEdges = edges;
}

function clearPaths() {
  pathCache = null;
  pathEdges = null;
  pathAnchors = null;
}

function clearTrees() {
  treeUnion = null;
  treeLayers = null;
}

/** Vrai si le fichier porte la clé `trees` (3.4), quelle que soit la version. */
function hasTrees() {
  return Boolean(courseData && courseData.trees && typeof courseData.trees === 'object');
}

/** Bouton « Arbres » : présent seulement avec la clé `trees`. */
function updateTreesButton() {
  const btn = document.getElementById('btn-trees');
  if (btn) btn.style.display = hasTrees() ? '' : 'none';
}

/**
 * Arbres (3.4) : un Path2D en blocs par couche et un pour toutes, cercles de
 * rayon réel au centre de la case. Arbres mal formés ou hors carte ignorés.
 * Sans clé `trees` : rien.
 */
function buildTreePaths() {
  if (!hasTrees()) return;
  const items = Array.isArray(courseData.trees.items) ? courseData.trees.items : [];
  treeUnion = new Path2D();
  treeLayers = new Map();
  items.forEach(item => {
    if (!item || typeof item !== 'object') return;
    const x = Number(item.x);
    const z = Number(item.z);
    const r = Number(item.radius);
    if (!Number.isInteger(x) || !Number.isInteger(z) || !(r > 0)
        || x < 0 || z < 0 || x >= mapW || z >= mapH) return;
    const layer = String(item.layer);
    if (!treeLayers.has(layer)) treeLayers.set(layer, new Path2D());
    [treeUnion, treeLayers.get(layer)].forEach(path => {
      path.moveTo(x + 0.5 + r, z + 0.5);
      path.arc(x + 0.5, z + 0.5, r, 0, 2 * Math.PI);
    });
  });
}

/** Vrai si le fichier porte la clé `paths` (3.3), quelle que soit la version. */
function hasPaths() {
  return Boolean(courseData && courseData.paths && typeof courseData.paths === 'object');
}

/** Boutons « Chemins » et « Ancrages » : désactivés sans clé `paths`. */
function updatePathsButtons() {
  ['paths', 'anchors'].forEach(key => {
    const btn = document.getElementById('btn-' + key);
    if (btn) btn.disabled = !hasPaths();
  });
}

/** Cases `[x, z]` entières dans la carte d'une liste (autres ignorées). */
function validCells(list, w, h) {
  if (!Array.isArray(list)) return [];
  const out = [];
  list.forEach(c => {
    if (!Array.isArray(c)) return;
    const x = Number(c[0]);
    const z = Number(c[1]);
    if (!Number.isInteger(x) || !Number.isInteger(z) || x < 0 || z < 0 || x >= w || z >= h) return;
    out.push([x, z]);
  });
  return out;
}

/**
 * Chemins (3.3), en cases comme le sable des bunkers : pixels 1:1 du parvis
 * (`plaza.cells`), des chemins (`cells`) et des ponts (`bridge_cells`, sous-
 * ensemble de `cells`, peints par-dessus), transparents ailleurs ; liseré
 * (Path2D en blocs) partout où deux cases voisines n'ont pas la même
 * surface (bord du chemin, entrée d'un pont, contact du parvis). Ancrages
 * gardés à part (repères). Sans clé `paths` : rien.
 */
function buildPathCache() {
  if (!hasPaths() || !(mapW > 0) || !(mapH > 0)) return;
  const paths = courseData.paths;
  const w = mapW;
  const h = mapH;
  const kind = new Uint8Array(w * h);  // 0 rien, 1 chemin, 2 pont, 3 parvis
  if (paths.plaza && typeof paths.plaza === 'object') {
    validCells(paths.plaza.cells, w, h).forEach(([x, z]) => { kind[z * w + x] = 3; });
  }
  validCells(paths.cells, w, h).forEach(([x, z]) => { kind[z * w + x] = 1; });
  validCells(paths.bridge_cells, w, h).forEach(([x, z]) => { kind[z * w + x] = 2; });
  pathAnchors = validCells(paths.anchors, w, h);

  const oc = document.createElement('canvas');
  oc.width = w;
  oc.height = h;
  const octx = oc.getContext('2d');
  const imageData = octx.createImageData(w, h);
  const pixels = imageData.data;
  const hex = c => [1, 3, 5].map(i => parseInt(c.slice(i, i + 2), 16));
  const rgb = [null, hex(C.path), hex(C.bridge), hex(C.plaza)];
  const edges = new Path2D();
  const at = (x, z) => (x >= 0 && z >= 0 && x < w && z < h ? kind[z * w + x] : 0);
  for (let z = 0; z < h; z++) {
    for (let x = 0; x < w; x++) {
      const k = kind[z * w + x];
      if (!k) continue;
      const p = (z * w + x) * 4;
      pixels[p] = rgb[k][0];
      pixels[p + 1] = rgb[k][1];
      pixels[p + 2] = rgb[k][2];
      pixels[p + 3] = 255;
      // bords vers le haut et la gauche entre deux surfaces (chacun une fois),
      // vers le bas et la droite seulement contre le vide
      if (at(x, z - 1) !== k) { edges.moveTo(x, z); edges.lineTo(x + 1, z); }
      if (at(x - 1, z) !== k) { edges.moveTo(x, z); edges.lineTo(x, z + 1); }
      if (!at(x, z + 1)) { edges.moveTo(x, z + 1); edges.lineTo(x + 1, z + 1); }
      if (!at(x + 1, z)) { edges.moveTo(x + 1, z); edges.lineTo(x + 1, z + 1); }
    }
  }
  octx.putImageData(imageData, 0, 0);
  pathCache = oc;
  pathEdges = edges;
}

function reliefColor(t) {
  if (t < 0.5) {
    const s = t * 2;
    return [
      Math.floor(26 + s * 26),
      Math.floor(60 + s * 52),
      Math.floor(26 + s * 14),
    ];
  }
  const s = (t - 0.5) * 2;
  return [
    Math.floor(52 + s * 46),
    Math.floor(112 - s * 14),
    Math.floor(40 - s * 6),
  ];
}

// === Header / Sidebar ===
function resetHeader() {
  ['stat-seed', 'stat-size', 'stat-pattern', 'stat-course', 'stat-format'].forEach(id => {
    document.getElementById(id).textContent = '—';
  });
}

function updateHeader() {
  const meta = courseData.metadata;
  const stats = meta.stats || {};
  document.getElementById('stat-seed').textContent = meta.seed !== undefined ? meta.seed : '—';
  document.getElementById('stat-size').textContent = `${mapW}x${mapH}`;
  document.getElementById('stat-pattern').textContent =
    meta.pattern ? meta.pattern.resolved : '—';
  const holes = courseData.routing ? courseData.routing.holes || [] : [];
  document.getElementById('stat-course').textContent = stats.total !== undefined
    ? `${holes.length} trous, par ${stats.par}, ${Math.round(stats.total)} blocs`
    : `${holes.length} trous`;
  document.getElementById('stat-format').textContent = meta.version;
}

function infoRow(label, value) {
  return `<div class="info-row"><span>${esc(label)}</span><strong>${esc(value)}</strong></div>`;
}

function nineLabel(nine) {
  return `${NINE_LABEL[nine] || nine} (${nine})`;
}

function updateSidebar() {
  const container = document.getElementById('course-info');
  container.innerHTML = '';
  const meta = courseData.metadata;
  const stats = meta.stats || {};
  const routing = courseData.routing || {};

  let html = '<h2>PARCOURS</h2><div class="info-box">';
  html += infoRow('Seed', meta.seed);
  if (meta.seed_input !== null && meta.seed_input !== undefined) {
    html += infoRow('Saisie', `« ${meta.seed_input} »`);
  }
  if (meta.pattern) {
    html += infoRow('Patron demande', meta.pattern.requested);
    html += infoRow('Patron resolu', meta.pattern.resolved);
  }
  html += infoRow('Taille', `${mapW} x ${mapH} blocs (${mapW * blockM} x ${mapH * blockM} m)`);
  if (meta.style) {
    html += infoRow('Style', meta.style);
  }
  if (meta.orientation) {
    html += infoRow('Orientation', ORIENTATION_LABEL[meta.orientation] || meta.orientation);
  }
  if (routing.direction) {
    const d = routing.direction;
    html += infoRow('Exterieur', `${nineLabel(d.outer_nine)}, ${TURN_LABEL[d.outer_turn] || d.outer_turn}`);
    html += infoRow('Interieur', `${nineLabel(d.inner_nine)}, ${TURN_LABEL[d.inner_turn] || d.inner_turn}`);
  }
  if (routing.clubhouse) {
    html += infoRow('Clubhouse', `bord ${routing.clubhouse.edge}`);
  }
  if (hasPaths()) {
    const paths = courseData.paths;
    const count = key => (Array.isArray(paths[key]) ? paths[key].length : 0);
    html += infoRow('Chemins', `${count('cells')} cases, largeur ${Number(paths.width)}`);
    html += infoRow('Ponts', `${count('bridge_cells')} cases`);
    html += infoRow('Parvis', paths.plaza && Number.isFinite(Number(paths.plaza.size))
      ? `${paths.plaza.size} x ${paths.plaza.size}` : 'aucun');
    html += infoRow('Ancrages', count('anchors'));
  }
  if (hasTrees()) {
    html += infoRow('Arbres', Array.isArray(courseData.trees.items) ? courseData.trees.items.length : 0);
  }
  html += '</div>';

  if (stats.total !== undefined) {
    html += '<h2>STATS</h2><div class="info-box">';
    ['front', 'back'].forEach(nine => {
      const s = stats[nine];
      if (!s) return;
      html += `<div class="info-sub">${esc(nineLabel(nine))} — par ${esc(s.par)}</div>`;
      html += infoRow('Trous', `${fmtBlocks(s.holes_length)} (${fmtMeters(s.holes_length)})`);
      html += infoRow('Liaisons', `${fmtBlocks(s.links_length)} (${fmtMeters(s.links_length)})`);
      html += infoRow('Total', `${fmtBlocks(s.total)} (${fmtMeters(s.total)})`);
    });
    html += `<div class="info-sub">18 trous — par ${esc(stats.par)}</div>`;
    html += infoRow('Total', `${fmtBlocks(stats.total)} (${fmtMeters(stats.total)})`);
    if (stats.elapsed_seconds !== undefined) {
      html += infoRow('Routage', `${Number(stats.elapsed_seconds).toFixed(2)} s`);
    }
    if (stats.relaunches !== undefined) {
      html += infoRow('Relances', stats.relaunches);
    }
    html += '</div>';
  }
  container.insertAdjacentHTML('beforeend', html);
  updateHoleList(routing.holes || []);
}

// Panneau droit : titre « TROUS » toujours affiché, puis tableaux aller /
// retour (trou, par, longueur).
function resetHoleList() {
  document.getElementById('hole-list').innerHTML =
    '<h2>TROUS</h2><div class="info-box">Aucun parcours charge.</div>';
}

function updateHoleList(holes) {
  const panel = document.getElementById('hole-list');
  panel.innerHTML = '<h2>TROUS</h2>';
  let tables = 0;
  ['front', 'back'].forEach(nine => {
    const subset = holes.filter(h => h.nine === nine);
    if (subset.length > 0) {
      panel.appendChild(createHoleTable(nineLabel(nine).toUpperCase(), subset));
      tables += 1;
    }
  });
  if (tables === 0) {
    panel.insertAdjacentHTML('beforeend', '<div class="info-box">Aucun trou dans ce JSON.</div>');
  }
}

function createHoleTable(title, holes) {
  const wrap = document.createElement('div');
  const h3 = document.createElement('h3');
  h3.textContent = title;
  wrap.appendChild(h3);

  const table = document.createElement('table');
  table.className = 'hole-table';
  table.innerHTML = '<thead><tr><th>#</th><th>Par</th><th>Blocs</th><th>m</th></tr></thead>';

  const tbody = document.createElement('tbody');
  let totalPar = 0;
  let totalBlocks = 0;
  holes.forEach(h => {
    totalPar += Number(h.par);
    totalBlocks += Number(h.length);
    const row = document.createElement('tr');
    row.className = `par${Number(h.par)}`;
    row.dataset.holeId = h.id;
    row.innerHTML = `<td><strong>${esc(h.id)}</strong></td><td>${esc(h.par)}</td>`
      + `<td>${esc(Number(h.length).toFixed(1))}</td><td>${esc(Math.round(Number(h.length) * blockM))}</td>`;
    row.addEventListener('mouseenter', () => setHighlight(h.id));
    row.addEventListener('mouseleave', () => setHighlight(null));
    tbody.appendChild(row);
  });
  const totalRow = document.createElement('tr');
  totalRow.className = 'total-row';
  totalRow.innerHTML = `<td></td><td>${esc(totalPar)}</td><td>${esc(totalBlocks.toFixed(1))}</td>`
    + `<td>${esc(Math.round(totalBlocks * blockM))}</td>`;
  tbody.appendChild(totalRow);

  table.appendChild(tbody);
  wrap.appendChild(table);
  return wrap;
}

function setHighlight(id) {
  if (highlightedHole === id) return;
  highlightedHole = id;
  document.querySelectorAll('.hole-table tr[data-hole-id]').forEach(r => {
    r.classList.toggle('active', parseInt(r.dataset.holeId, 10) === id);
  });
  draw();
}

// === Drawing ===
function draw() {
  if (!courseData) return;

  ctx.fillStyle = '#1a2410';
  ctx.fillRect(0, 0, canvas.width, canvas.height);

  const fairway = courseData.routing && fairwayPainted;
  if (show.terrain) drawTerrain();
  if (show.terrain && fairway) drawRough();
  drawMapFrame();
  if (courseData.routing) {
    if (show.holes && fairway) drawFairways();
    if (show.holes && (!fairway || show.debug)) drawCorridors();
    if (show.holes && show.debug) drawPlayBands();
    if (show.trees && treeUnion) drawTrees();
    if (show.bunkers && bunkerCache) drawBunkers();
    if (show.paths && pathCache) drawPaths();
    if (show.anchors && pathAnchors) drawAnchors();
    if (show.dressing && hasDressing()) drawDressing();
    if (show.links) drawLinks();
    if (show.holes) drawHoleMarkers();
    drawClubhouse();
  }
  if (show.grid) drawGrid();
}

function drawTerrain() {
  if (!terrainCache) return;
  const [dx, dy] = toCanvas(0, 0);
  ctx.imageSmoothingEnabled = false;
  ctx.drawImage(terrainCache, dx, dy, terrainCache.width * camZoom, terrainCache.height * camZoom);
}

function drawMapFrame() {
  const [x0, y0] = toCanvas(0, 0);
  ctx.strokeStyle = 'rgba(139,148,158,0.8)';
  ctx.lineWidth = 1;
  ctx.strokeRect(x0, y0, mapW * camZoom, mapH * camZoom);
}

function tracePolyline(points) {
  ctx.beginPath();
  points.forEach((p, i) => {
    const [cx, cy] = toCanvas(p.x, p.y);
    if (i === 0) ctx.moveTo(cx, cy);
    else ctx.lineTo(cx, cy);
  });
}

/** Point et tangente unitaire à l'abscisse curviligne `dist` le long de l'axe. */
function pointAndTangent(points, dist) {
  let remaining = dist;
  for (let i = 0; i < points.length - 1; i++) {
    const a = points[i], b = points[i + 1];
    const seg = Math.hypot(b.x - a.x, b.y - a.y);
    if (seg === 0) continue;
    if (remaining <= seg || i === points.length - 2) {
      const t = Math.max(0, Math.min(1, remaining / seg));
      return [
        { x: a.x + (b.x - a.x) * t, y: a.y + (b.y - a.y) * t },
        { x: (b.x - a.x) / seg, y: (b.y - a.y) / seg },
      ];
    }
    remaining -= seg;
  }
  return [points[0], { x: 1, y: 0 }];
}

function axisLength(points) {
  let total = 0;
  for (let i = 0; i < points.length - 1; i++) {
    total += Math.hypot(points[i + 1].x - points[i].x, points[i + 1].y - points[i].y);
  }
  return total;
}

function drawCorridors() {
  const holes = courseData.routing.holes || [];
  ctx.lineJoin = 'round';
  holes.forEach(h => {
    const axis = holeAxis(h);
    const hl = h.id === highlightedHole;
    const widthPx = Math.max(1, h.width * camZoom);
    ctx.lineCap = 'butt';
    if (hl) {
      // contour blanc du trou survolé, sous le couloir
      tracePolyline(axis);
      ctx.strokeStyle = C.paper;
      ctx.lineWidth = widthPx + 4;
      ctx.stroke();
    }
    // Couloir : largeur TOTALE du fairway, en blocs.
    tracePolyline(axis);
    ctx.strokeStyle = PAR_COLORS[h.par] || '#cccccc';
    ctx.globalAlpha = hl ? 1 : 0.7;
    ctx.lineWidth = widthPx;
    ctx.stroke();
    ctx.globalAlpha = 1;
    // Axe
    tracePolyline(axis);
    ctx.strokeStyle = 'rgba(13,17,23,0.5)';
    ctx.lineWidth = 1;
    ctx.stroke();
    // Flèche de sens au milieu de l'axe
    const [mid, tan] = pointAndTangent(axis, axisLength(axis) * 0.5);
    const [mx, my] = toCanvas(mid.x, mid.y);
    const s = Math.max(4, Math.min(9, 2.2 * camZoom));
    const nx = -tan.y, ny = tan.x;
    ctx.beginPath();
    ctx.moveTo(mx + tan.x * s * 1.25, my + tan.y * s * 1.25);
    ctx.lineTo(mx - tan.x * s + nx * s, my - tan.y * s + ny * s);
    ctx.lineTo(mx - tan.x * s - nx * s, my - tan.y * s - ny * s);
    ctx.closePath();
    ctx.fillStyle = 'rgba(13,17,23,0.75)';
    ctx.fill();
  });
}

/**
 * Contour simple à joints biseautés autour de l'axe ouvert, bouts tee et green
 * prolongés de `radius` : portage de `buffered_axis` (golfgen/routing/geometry.py).
 */
function bufferedAxis(axis, radius) {
  const pts = axis.filter((p, i) => i === 0
    || Math.hypot(p.x - axis[i - 1].x, p.y - axis[i - 1].y) > 1e-9);
  if (pts.length < 2 || !(radius > 0)) return null;
  const unit = (a, b) => {
    const len = Math.hypot(b.x - a.x, b.y - a.y);
    return { x: (b.x - a.x) / len, y: (b.y - a.y) / len };
  };
  const normals = [];
  for (let i = 0; i < pts.length - 1; i++) {
    const u = unit(pts[i], pts[i + 1]);
    normals.push({ x: -u.y, y: u.x });
  }
  const offsets = pts.map((_, i) => {
    if (i === 0) return normals[0];
    if (i === pts.length - 1) return normals[normals.length - 1];
    let nx = normals[i - 1].x + normals[i].x;
    let ny = normals[i - 1].y + normals[i].y;
    const norm = Math.hypot(nx, ny);
    if (norm < 1e-7) return normals[i];
    nx /= norm;
    ny /= norm;
    const dot = Math.max(0.72, nx * normals[i].x + ny * normals[i].y);
    return { x: nx / dot, y: ny / dot };
  });
  const left = pts.map((p, i) => ({ x: p.x + radius * offsets[i].x, y: p.y + radius * offsets[i].y }));
  const right = pts.map((p, i) => ({ x: p.x - radius * offsets[i].x, y: p.y - radius * offsets[i].y }));
  const start = unit(pts[0], pts[1]);
  const end = unit(pts[pts.length - 2], pts[pts.length - 1]);
  const last = pts.length - 1;
  [left, right].forEach(side => {
    side[0] = { x: side[0].x - radius * start.x, y: side[0].y - radius * start.y };
    side[last] = { x: side[last].x + radius * end.x, y: side[last].y + radius * end.y };
  });
  return left.concat(right.reverse());
}

/**
 * Rough : surface par défaut, toute terre ferme qu'aucun élément ne couvre.
 * Teinte plate translucide sur toute la carte (le relief reste lisible), puis
 * l'eau repeinte par-dessus ; fairways, greens et départs viennent ensuite.
 */
function drawRough() {
  const [x0, y0] = toCanvas(0, 0);
  ctx.fillStyle = C.rough;
  ctx.globalAlpha = ROUGH_ALPHA;
  ctx.fillRect(x0, y0, mapW * camZoom, mapH * camZoom);
  ctx.globalAlpha = 1;
  if (waterCache) {
    ctx.imageSmoothingEnabled = false;
    ctx.drawImage(waterCache, x0, y0, waterCache.width * camZoom, waterCache.height * camZoom);
  }
}

/** Morceaux de fairway (3.1 R5), cernés d'un liseré ; trou survolé cerné de blanc. */
function drawFairways() {
  ctx.lineJoin = 'round';
  (courseData.routing.holes || []).forEach(h => {
    const hl = h.id === highlightedHole;
    (fairwayOutlines(h) || []).forEach(piece => {
      tracePolyline(piece);
      ctx.closePath();
      ctx.fillStyle = C.fairway;
      ctx.fill();
      ctx.strokeStyle = hl ? C.paper : C.fairwayEdge;
      ctx.lineWidth = hl ? 1.6 : 1;
      ctx.stroke();
    });
  });
}

/**
 * Bunkers (3.2) : sable (cache 1:1) sur le rough et les fairways, sous les
 * greens et les départs, cerné d'un liseré fin aux bords des cases.
 */
function drawBunkers() {
  const [x0, y0] = toCanvas(0, 0);
  ctx.imageSmoothingEnabled = false;
  ctx.drawImage(bunkerCache, x0, y0, bunkerCache.width * camZoom, bunkerCache.height * camZoom);
  if (!bunkerEdges) return;
  ctx.save();
  ctx.translate(x0, y0);
  ctx.scale(camZoom, camZoom);
  ctx.strokeStyle = C.sandEdge;
  ctx.lineWidth = Math.min(1, 0.8 / camZoom);
  ctx.stroke(bunkerEdges);
  ctx.restore();
}

/**
 * Chemins (3.3) : gravier, ponts et parvis (cache 1:1) sur le rough, les
 * fairways et le sable, sous les greens et les départs, cernés d'un liseré
 * fin aux bords des cases.
 */
function drawPaths() {
  const [x0, y0] = toCanvas(0, 0);
  ctx.imageSmoothingEnabled = false;
  ctx.drawImage(pathCache, x0, y0, pathCache.width * camZoom, pathCache.height * camZoom);
  if (!pathEdges) return;
  ctx.save();
  ctx.translate(x0, y0);
  ctx.scale(camZoom, camZoom);
  ctx.strokeStyle = C.pathEdge;
  ctx.lineWidth = Math.min(1, 0.8 / camZoom);
  ctx.stroke(pathEdges);
  ctx.restore();
}

/**
 * Arbres (3.4) : couronnes pleines sur le rough et les fairways, sous le
 * sable, les chemins, les greens et les départs (un cercle de rayon r passe
 * par le centre des cases du bord de sa couronne : il les couvre à moitié et
 * peut effleurer une case voisine) ; une couleur par couche sous Debug.
 */
function drawTrees() {
  const [x0, y0] = toCanvas(0, 0);
  ctx.save();
  ctx.translate(x0, y0);
  ctx.scale(camZoom, camZoom);
  ctx.globalAlpha = TREE_ALPHA;
  ctx.fillStyle = C.tree;
  if (show.debug) {
    treeLayers.forEach((path, layer) => {
      ctx.fillStyle = TREE_DEBUG_COLORS[layer] || C.tree;
      ctx.fill(path);
    });
  } else {
    ctx.fill(treeUnion);
  }
  ctx.strokeStyle = C.treeEdge;
  ctx.lineWidth = 1 / camZoom;
  ctx.stroke(treeUnion);
  ctx.restore();
}

/** Ancrages des virages (3.3) : petit repère vert foncé, cerné de clair, au centre de la case. */
function drawAnchors() {
  const r = Math.max(1.8, camZoom * 0.28);
  ctx.save();
  pathAnchors.forEach(([x, z]) => {
    const [cx, cy] = toCanvas(x + 0.5, z + 0.5);
    ctx.beginPath();
    ctx.arc(cx, cy, r + 0.8, 0, 2 * Math.PI);
    ctx.fillStyle = C.anchorRing;
    ctx.fill();
    ctx.beginPath();
    ctx.arc(cx, cy, r, 0, 2 * Math.PI);
    ctx.fillStyle = C.anchor;
    ctx.fill();
  });
  ctx.restore();
}

/**
 * Debug : contour de la bande de jeu (cœur + rough_margin, `buffered_axis`),
 * zone de placement interne (arbres, bunkers, hors-limites), pas une surface.
 */
function drawPlayBands() {
  ctx.save();
  ctx.setLineDash([5, 4]);
  ctx.lineJoin = 'miter';
  (courseData.routing.holes || []).forEach(h => {
    const band = bufferedAxis(holeAxis(h), h.width / 2 + Number(h.rough_margin || 0));
    if (!band) return;
    tracePolyline(band);
    ctx.closePath();
    ctx.strokeStyle = h.id === highlightedHole ? C.paper : 'rgba(240,246,252,0.55)';
    ctx.lineWidth = 1.2;
    ctx.stroke();
  });
  ctx.restore();
}

/**
 * Habillage (3.1) : greens doubles (`routing.green_pairs`), en vert clair avec
 * contour, dessous ; contours de greens, en vert clair avec contour (trait
 * fin seul pour les deux greens d'une paire, que la paire contient), et
 * boîtes de départ, en lilas cerné d'encre.
 */
function drawDressing() {
  const holes = courseData.routing.holes || [];
  ctx.lineJoin = 'round';
  const paired = new Set();
  greenPairs().forEach(p => {
    const hl = p.holes.includes(highlightedHole);
    tracePolyline(p.outline);
    ctx.closePath();
    ctx.fillStyle = C.greenShape;
    ctx.fill();
    ctx.strokeStyle = C.greenEdge;
    ctx.lineWidth = hl ? 2 : 1.2;
    ctx.stroke();
    p.holes.forEach(id => paired.add(id));
  });
  holes.forEach(h => {
    const hl = h.id === highlightedHole;
    const outline = greenOutline(h);
    if (outline && paired.has(h.id)) {
      tracePolyline(outline);
      ctx.closePath();
      ctx.strokeStyle = C.greenEdge;
      ctx.lineWidth = hl ? 1.2 : 0.6;
      ctx.stroke();
    } else if (outline) {
      tracePolyline(outline);
      ctx.closePath();
      ctx.fillStyle = C.greenShape;
      ctx.fill();
      ctx.strokeStyle = C.greenEdge;
      ctx.lineWidth = hl ? 2 : 1.2;
      ctx.stroke();
    }
    ctx.lineJoin = 'miter';
    (teeOutlines(h) || []).forEach(box => {
      tracePolyline(box);
      ctx.closePath();
      ctx.fillStyle = C.teeShape;
      ctx.fill();
      ctx.strokeStyle = hl ? C.paper : C.teeEdge;
      ctx.lineWidth = hl ? 1.6 : 1;
      ctx.stroke();
    });
    ctx.lineJoin = 'round';
  });
}

function endpoint(ref, side) {
  const routing = courseData.routing;
  if (ref === 'clubhouse') return routing.clubhouse;
  const h = (routing.holes || []).find(x => x.id === ref);
  if (!h) return null;
  return side === 'from' ? h.green : h.tee;
}

function drawLinks() {
  const links = courseData.routing.links || [];
  ctx.save();
  ctx.setLineDash([4, 4]);
  ctx.strokeStyle = 'rgba(230,237,243,0.75)';
  ctx.lineWidth = 1.4;
  links.forEach(l => {
    const a = endpoint(l.from, 'from');
    const b = endpoint(l.to, 'to');
    if (!a || !b) return;
    tracePolyline([a, b]);
    ctx.stroke();
  });
  ctx.restore();
}

function drawHoleMarkers() {
  const holes = courseData.routing.holes || [];
  // Tees et greens
  holes.forEach(h => {
    const [tx, ty] = toCanvas(h.tee.x, h.tee.y);
    if (show.dressing && teeOutlines(h)) {
      // boîtes de départ déjà dessinées (l'arrière centrée sur le tee) :
      // seul un point marque le tee routé
      ctx.beginPath();
      ctx.arc(tx, ty, 1.8, 0, Math.PI * 2);
      ctx.fillStyle = C.ink;
      ctx.fill();
    } else {
      ctx.fillStyle = C.paper;
      ctx.strokeStyle = C.ink;
      ctx.lineWidth = 1;
      ctx.fillRect(tx - 4, ty - 4, 8, 8);
      ctx.strokeRect(tx - 4, ty - 4, 8, 8);
    }

    const [gx, gy] = toCanvas(h.green.x, h.green.y);
    if (show.dressing && greenOutline(h)) {
      // green habillé déjà dessiné : seul le trou du drapeau
      ctx.beginPath();
      ctx.arc(gx, gy, 1.8, 0, Math.PI * 2);
      ctx.fillStyle = C.ink;
      ctx.fill();
    } else {
      ctx.beginPath();
      ctx.arc(gx, gy, Math.max(4, GREEN_RADIUS * camZoom), 0, Math.PI * 2);
      ctx.fillStyle = C.green;
      ctx.fill();
      ctx.strokeStyle = C.paper;
      ctx.lineWidth = 1.5;
      ctx.stroke();
    }
    // Drapeau
    ctx.beginPath();
    ctx.moveTo(gx, gy);
    ctx.lineTo(gx, gy - 13);
    ctx.strokeStyle = C.paper;
    ctx.lineWidth = 1.2;
    ctx.stroke();
    ctx.beginPath();
    ctx.moveTo(gx, gy - 13);
    ctx.lineTo(gx + 7, gy - 10.5);
    ctx.lineTo(gx, gy - 8);
    ctx.closePath();
    ctx.fillStyle = C.flag;
    ctx.fill();
  });

  if (!show.nums) return;
  // Numéros derrière le tee
  holes.forEach(h => {
    const [, tan] = pointAndTangent(holeAxis(h), 0);
    const [lx, ly] = toCanvas(h.tee.x - tan.x * LABEL_BACKOFF, h.tee.y - tan.y * LABEL_BACKOFF);
    ctx.beginPath();
    ctx.arc(lx, ly, 10, 0, Math.PI * 2);
    ctx.fillStyle = PAR_COLORS[h.par] || '#cccccc';
    ctx.fill();
    ctx.strokeStyle = h.id === highlightedHole ? C.paper : C.ink;
    ctx.lineWidth = 2;
    ctx.stroke();
    ctx.fillStyle = C.ink;
    ctx.font = 'bold 12px IBM Plex Mono';
    ctx.textAlign = 'center';
    ctx.textBaseline = 'middle';
    ctx.fillText(String(h.id), lx, ly + 0.5);
    ctx.textBaseline = 'alphabetic';
  });
}

function drawClubhouse() {
  const club = courseData.routing.clubhouse;
  if (!club) return;
  const [cx, cy] = toCanvas(club.x, club.y);
  ctx.save();
  ctx.translate(cx, cy);
  ctx.rotate(Math.PI / 4);
  ctx.fillStyle = C.club;
  ctx.strokeStyle = C.paper;
  ctx.lineWidth = 2.5;
  ctx.fillRect(-10, -10, 20, 20);
  ctx.strokeRect(-10, -10, 20, 20);
  ctx.restore();
  ctx.fillStyle = C.paper;
  ctx.font = 'bold 10px IBM Plex Mono';
  ctx.textAlign = 'center';
  ctx.textBaseline = 'middle';
  ctx.fillText('CH', cx, cy + 0.5);
  ctx.textBaseline = 'alphabetic';
}

function drawGrid() {
  if (!courseData) return;
  const w = mapW;
  const h = mapH;

  // Adaptive grid spacing
  const steps = [10, 25, 50, 100, 200, 500];
  let step = 50;
  for (const s of steps) {
    if (s * camZoom >= 50) { step = s; break; }
  }

  ctx.strokeStyle = 'rgba(255,255,255,0.05)';
  ctx.lineWidth = 0.5;

  const [gridX0, gridY0] = toCanvas(0, 0);
  const [gridX1, gridY1] = toCanvas(w, h);

  for (let x = 0; x <= w; x += step) {
    const [cx] = toCanvas(x, 0);
    if (cx < -1 || cx > canvas.width + 1) continue;
    ctx.beginPath();
    ctx.moveTo(cx, gridY0);
    ctx.lineTo(cx, gridY1);
    ctx.stroke();
  }

  for (let y = 0; y <= h; y += step) {
    const [, cy] = toCanvas(0, y);
    if (cy < -1 || cy > canvas.height + 1) continue;
    ctx.beginPath();
    ctx.moveTo(gridX0, cy);
    ctx.lineTo(gridX1, cy);
    ctx.stroke();
  }

  // Labels
  const labelSize = Math.max(6, Math.min(10, 7 * camZoom / 1.5));
  ctx.fillStyle = 'rgba(255,255,255,0.25)';
  ctx.font = `${Math.round(labelSize)}px IBM Plex Mono`;

  ctx.textAlign = 'center';
  const labelStep = step < 50 ? step * 2 : step;
  for (let x = 0; x <= w; x += labelStep) {
    const [cx, cy] = toCanvas(x, 0);
    if (cx < 20 || cx > canvas.width - 20) continue;
    ctx.fillText(x, cx, cy - 6);
  }

  ctx.textAlign = 'right';
  for (let y = 0; y <= h; y += labelStep) {
    const [cx, cy] = toCanvas(0, y);
    if (cy < 10 || cy > canvas.height - 10) continue;
    ctx.fillText(y, cx - 6, cy + 3);
  }

  // Nord
  const [nfx, nfy] = toCanvas(w - 20, 15);
  if (nfx > 0 && nfx < canvas.width && nfy > 0 && nfy < canvas.height) {
    ctx.fillStyle = 'rgba(255,255,255,0.35)';
    ctx.font = 'bold 12px Silkscreen';
    ctx.textAlign = 'center';
    ctx.fillText('N', nfx, nfy);
  }
}

function showMessage(lines) {
  currentMessage = lines;
  ctx.fillStyle = '#1a2410';
  ctx.fillRect(0, 0, canvas.width, canvas.height);
  ctx.textAlign = 'center';
  ctx.fillStyle = '#e5534b';
  ctx.font = '16px Silkscreen';
  ctx.fillText(lines[0], canvas.width / 2, canvas.height / 2 - 24);
  ctx.font = '12px IBM Plex Mono';
  ctx.fillStyle = 'rgba(255,255,255,0.6)';
  lines.slice(1).forEach((line, i) => {
    ctx.fillText(line, canvas.width / 2, canvas.height / 2 + 8 + i * 20);
  });
}

function showNoData() {
  currentMessage = null;
  ctx.fillStyle = '#1a2410';
  ctx.fillRect(0, 0, canvas.width, canvas.height);

  ctx.fillStyle = 'rgba(255,255,255,0.3)';
  ctx.font = '14px Silkscreen';
  ctx.textAlign = 'center';
  ctx.fillText('Aucune donnee chargee', canvas.width / 2, canvas.height / 2 - 20);
  ctx.font = '11px IBM Plex Mono';
  ctx.fillStyle = 'rgba(255,255,255,0.25)';
  ctx.fillText('Charger un JSON 3.x ou executer :', canvas.width / 2, canvas.height / 2 + 10);
  ctx.fillText('python pipeline.py --seed 4', canvas.width / 2, canvas.height / 2 + 30);
}

// === Tooltip / Coords ===
function updateCoords(mx, my) {
  if (!courseData) return;
  const [bx, by] = toWorld(mx, my);
  const ix = Math.floor(bx);
  const iy = Math.floor(by);

  if (ix >= 0 && ix < mapW && iy >= 0 && iy < mapH) {
    let info = `Bloc (${ix}, ${iy})`;
    if (heightmapPixels) {
      const val = heightmapPixels[iy * courseData.terrain.width + ix];
      const elev = courseData.terrain.elevation;
      const realElev = elev.min_elevation + (val / 255) * (elev.max_elevation - elev.min_elevation);
      info += ` — Y=${realElev.toFixed(1)}`;
    }
    coordsEl.textContent = info;
  } else {
    coordsEl.textContent = 'Survole la carte pour voir les coordonnees bloc';
  }
}

function updateTooltip(clientX, clientY, mx, my) {
  if (!courseData) {
    tooltip.style.display = 'none';
    return;
  }

  const [bx, by] = toWorld(mx, my);
  updateCoords(mx, my);

  const hole = courseData.routing && show.holes ? getHoleAt(bx, by) : null;
  if (hole) {
    tooltip.style.display = 'block';
    tooltip.style.left = (clientX + 12) + 'px';
    tooltip.style.top = (clientY + 12) + 'px';
    const tees = teeOutlines(hole);
    const pair = greenPairOf(hole.id);
    const fairway = fairwaySummary(hole);
    tooltip.innerHTML = `<div class="tt-title">Trou ${esc(hole.id)} — Par ${esc(hole.par)}</div>`
      + `Nine : ${esc(nineLabel(hole.nine))}<br>`
      + `Longueur : ${esc(fmtBlocks(hole.length))} (${esc(fmtMeters(hole.length))})<br>`
      + `Largeur : ${esc(Number(hole.width).toFixed(1))} blocs (${esc(fmtMeters(hole.width))})`
      + (greenOutline(hole) && hole.features.green.area !== undefined
        ? `<br>Green : ${esc(Number(hole.features.green.area).toFixed(0))} blocs²`
        : '')
      + (pair
        ? `<br>Green double avec le trou ${esc(pair.partner)}`
          + (pair.area !== undefined ? ` · ${esc(Number(pair.area).toFixed(0))} blocs²` : '')
        : '')
      + (tees
        ? `<br>Départs : ${esc(tees.length)}`
        : '')
      + (bunkerCounts
        ? (emptyBunkerHole(hole.id)
          ? '<br>Bunkers : aucun (trou vide)'
          : `<br>Bunkers : ${esc(bunkerCounts.get(hole.id) || 0)}`)
        : '')
      + (fairway === null ? ''
        : fairway.pieces === 0 ? '<br>Fairway : vidé par l\'eau'
          : `<br>Fairway : ${esc(fairway.pieces)} morceau${fairway.pieces > 1 ? 'x' : ''}`
            + ` · ${esc(fairway.area.toFixed(0))} blocs²`);
    setHighlight(hole.id);
    return;
  }

  tooltip.style.display = 'none';
  if (highlightedHole !== null) setHighlight(null);
}

/**
 * Trou sous le point (blocs) : couloir (largeur totale, aussi en rendu rough +
 * fairways), green ou tee ; le plus « profond » l'emporte.
 */
function getHoleAt(bx, by) {
  const pickPx = 3 / camZoom;  // tolérance de 3 px écran
  let best = null;
  let bestScore = Infinity;
  for (const h of courseData.routing.holes || []) {
    const axis = holeAxis(h);
    let d = Infinity;
    for (let i = 0; i < axis.length - 1; i++) {
      d = Math.min(d, pointToSegDist(bx, by, axis[i].x, axis[i].y, axis[i + 1].x, axis[i + 1].y));
    }
    let score = d - (h.width / 2 + pickPx);
    score = Math.min(score, Math.hypot(bx - h.green.x, by - h.green.y) - (GREEN_RADIUS + pickPx));
    if (score <= 0 && score < bestScore) {
      best = h;
      bestScore = score;
    }
  }
  return best;
}

function pointToSegDist(px, py, ax, ay, bx, by) {
  const dx = bx - ax, dy = by - ay;
  const len2 = dx * dx + dy * dy;
  if (len2 === 0) return Math.hypot(px - ax, py - ay);
  let t = ((px - ax) * dx + (py - ay) * dy) / len2;
  t = Math.max(0, Math.min(1, t));
  return Math.hypot(px - (ax + t * dx), py - (ay + t * dy));
}

// === Toggle ===
/** Fixe la couche `key` et l'état de son bouton, sans redessiner. */
function setLayer(key, on) {
  show[key] = on;
  const btn = document.getElementById('btn-' + key);
  if (btn) btn.classList.toggle('active', show[key]);
}

function toggle(key) {
  setLayer(key, !show[key]);
  draw();
}

// === Start ===
init();
