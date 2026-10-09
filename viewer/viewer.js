/**
 * Viewer de parcours de golf — lit le JSON 3.x produit par `pipeline.py`
 * (routeur Muirfield, contrat dans docs/format-3.0.md).
 * Affiche le relief, les 18 trous (couloir tee -> doglegs -> green, largeur
 * totale du fairway), les liaisons et le clubhouse. Zoom/pan interactif.
 * Tout autre format (2.0 compris) est refusé avec un message à l'écran.
 */

// === State ===
let courseData = null;
let heightmapPixels = null; // Uint8Array (octets 0..255 normalisés sur [min, max])
let terrainCache = null;    // canvas terrain 1:1
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
  flag: '#e5534b',
  link: '#e6edf3',
  club: '#e5534b',
};
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

// === Init ===
function init() {
  document.getElementById('file-input').addEventListener('change', handleFileLoad);
  window.addEventListener('resize', resizeCanvas);

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
// (utile pour comparer deux fichiers ou tester le refus d'un format).
async function tryAutoLoad() {
  const param = new URLSearchParams(window.location.search).get('json');
  const url = param || '../output/course.json';
  try {
    const resp = await fetch(url);
    if (!resp.ok) {
      showNoData();
      return;
    }
    const json = await resp.json();
    const name = url.split('/').pop();
    if (loadCourseData(json)) {
      document.getElementById('filename').textContent = `${name} (auto)`;
    } else {
      document.getElementById('filename').textContent = `${name} (refuse)`;
    }
  } catch (e) {
    showNoData();
  }
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
  highlightedHole = null;
  tooltip.style.display = 'none';
  resetHeader();
  const info = document.getElementById('course-info');
  info.innerHTML = `<div class="info-box error-box"><strong>${esc(lines[0])}</strong><br>`
    + lines.slice(1).map(esc).join('<br>') + '</div>';
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
    highlightedHole = null;

    const meta = json.metadata;
    mapW = (json.terrain && json.terrain.width) || meta.width;
    mapH = (json.terrain && json.terrain.height) || meta.height;
    blockM = meta.block_m || 3;

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

    updateHeader();
    updateSidebar();
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
// bloc terrain). Le 3.0 n'a pas de niveau de base ni de niveau d'eau : on
// ne dessine donc pas d'eau, seulement la hauteur relative.
function buildTerrainCache() {
  const w = courseData.terrain.width;
  const h = courseData.terrain.height;
  const oc = document.createElement('canvas');
  oc.width = w;
  oc.height = h;
  const octx = oc.getContext('2d');
  const imageData = octx.createImageData(w, h);
  const pixels = imageData.data;

  for (let idx = 0; idx < w * h; idx++) {
    const [r, g, b] = reliefColor(heightmapPixels[idx] / 255);
    const p = idx * 4;
    pixels[p] = r;
    pixels[p + 1] = g;
    pixels[p + 2] = b;
    pixels[p + 3] = 255;
  }
  octx.putImageData(imageData, 0, 0);
  terrainCache = oc;
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

  const holes = routing.holes || [];
  ['front', 'back'].forEach(nine => {
    const subset = holes.filter(h => h.nine === nine);
    if (subset.length > 0) {
      container.appendChild(createHoleTable(nineLabel(nine).toUpperCase(), subset));
    }
  });
}

function createHoleTable(title, holes) {
  const wrap = document.createElement('div');
  const h2 = document.createElement('h2');
  h2.textContent = title;
  wrap.appendChild(h2);

  const table = document.createElement('table');
  table.className = 'hole-table';
  table.innerHTML = '<thead><tr><th>#</th><th>Par</th><th>Blocs</th><th>m</th></tr></thead>';

  const tbody = document.createElement('tbody');
  let totalPar = 0;
  let totalBlocks = 0;
  holes.forEach(h => {
    totalPar += h.par;
    totalBlocks += h.length;
    const row = document.createElement('tr');
    row.className = `par${h.par}`;
    row.dataset.holeId = h.id;
    row.innerHTML = `<td><strong>${esc(h.id)}</strong></td><td>${esc(h.par)}</td>`
      + `<td>${esc(Number(h.length).toFixed(1))}</td><td>${esc(Math.round(h.length * blockM))}</td>`;
    row.addEventListener('mouseenter', () => setHighlight(h.id));
    row.addEventListener('mouseleave', () => setHighlight(null));
    tbody.appendChild(row);
  });
  const totalRow = document.createElement('tr');
  totalRow.className = 'total-row';
  totalRow.innerHTML = `<td></td><td>${totalPar}</td><td>${totalBlocks.toFixed(1)}</td>`
    + `<td>${Math.round(totalBlocks * blockM)}</td>`;
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

  if (show.terrain) drawTerrain();
  drawMapFrame();
  if (courseData.routing) {
    if (show.holes) drawCorridors();
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
    ctx.fillStyle = C.paper;
    ctx.strokeStyle = C.ink;
    ctx.lineWidth = 1;
    ctx.fillRect(tx - 4, ty - 4, 8, 8);
    ctx.strokeRect(tx - 4, ty - 4, 8, 8);

    const [gx, gy] = toCanvas(h.green.x, h.green.y);
    ctx.beginPath();
    ctx.arc(gx, gy, Math.max(4, GREEN_RADIUS * camZoom), 0, Math.PI * 2);
    ctx.fillStyle = C.green;
    ctx.fill();
    ctx.strokeStyle = C.paper;
    ctx.lineWidth = 1.5;
    ctx.stroke();
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
    tooltip.innerHTML = `<div class="tt-title">Trou ${esc(hole.id)} — Par ${esc(hole.par)}</div>`
      + `Nine : ${esc(nineLabel(hole.nine))}<br>`
      + `Longueur : ${esc(fmtBlocks(hole.length))} (${esc(fmtMeters(hole.length))})<br>`
      + `Largeur : ${esc(Number(hole.width).toFixed(1))} blocs (${esc(fmtMeters(hole.width))})`;
    setHighlight(hole.id);
    return;
  }

  tooltip.style.display = 'none';
  if (highlightedHole !== null) setHighlight(null);
}

/** Trou sous le point (blocs) : couloir, green ou tee ; le plus « profond » l'emporte. */
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
function toggle(key) {
  show[key] = !show[key];
  const btn = document.getElementById('btn-' + key);
  if (btn) btn.classList.toggle('active', show[key]);
  draw();
}

// === Start ===
init();
