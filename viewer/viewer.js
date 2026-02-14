/**
 * Viewer de parcours de golf — consomme le JSON produit par le pipeline Python.
 * Affiche les couches : terrain, routing, obstacles, vegetation, features.
 * Zoom/pan interactif (molette + glisser).
 */

// === State ===
let courseData = null;
let heightmapPixels = null; // Uint8Array pour tooltips
let terrainCache = null;    // OffscreenCanvas terrain 1:1
let ownerCache = null;      // Int16Array cache paving

// Camera
let camZoom = 2.0;
let camPanX = 0;
let camPanY = 0;
const MIN_ZOOM = 0.5;
const MAX_ZOOM = 10;

// Layers
let show = {
  terrain: true,
  paving: true,
  routing: true,
  hazards: true,
  vegetation: true,
  features: true,
  grid: true,
  nums: true,
};

let highlightedHole = null;

// Pan state
let isPanning = false;
let panStartX = 0, panStartY = 0;
let panStartCamX = 0, panStartCamY = 0;
let didDrag = false;

// === Palette Minecraft ===
const C = {
  rough: '#2e5420',
  roughDark: '#233f18',
  fairway: '#6aad45',
  fairwayLight: '#7abf52',
  green: '#3dbd4e',
  greenEdge: '#34a843',
  tee: '#4ecf5f',
  sand: '#e8d68a',
  sandDark: '#d4c170',
  water: '#3b8bba',
  waterDeep: '#2a6f99',
  tree: '#2d5e1e',
  treeDark: '#1f4a14',
  treeLight: '#3d7a2a',
  path: '#a08b6e',
  flag: '#ff3b3b',
};

// === DOM ===
const canvas = document.getElementById('map');
const ctx = canvas.getContext('2d');
const tooltip = document.getElementById('tooltip');
const coordsEl = document.getElementById('coords');

// === Init ===
function init() {
  document.getElementById('file-input').addEventListener('change', handleFileLoad);

  // Resize
  window.addEventListener('resize', resizeCanvas);

  // Zoom/Pan events
  canvas.addEventListener('wheel', onWheel, { passive: false });
  canvas.addEventListener('mousedown', onMouseDown);
  window.addEventListener('mousemove', onMouseMove);
  window.addEventListener('mouseup', onMouseUp);
  canvas.addEventListener('mouseleave', onMouseLeave);

  resizeCanvas();
  tryAutoLoad();
}

function resizeCanvas() {
  const wrapper = document.querySelector('.canvas-wrapper');
  const rect = wrapper.getBoundingClientRect();
  canvas.width = Math.floor(rect.width);
  canvas.height = Math.floor(rect.height);
  if (courseData) draw();
  else showNoData();
}

// === Camera ===
function toCanvas(wx, wy) {
  return [wx * camZoom + camPanX, wy * camZoom + camPanY];
}

function toWorld(sx, sy) {
  return [(sx - camPanX) / camZoom, (sy - camPanY) / camZoom];
}

function centerMap() {
  if (!courseData) return;
  const w = courseData.metadata.config.width || 600;
  const h = courseData.metadata.config.height || 600;
  camPanX = (canvas.width - w * camZoom) / 2;
  camPanY = (canvas.height - h * camZoom) / 2;
}

function resetView() {
  camZoom = 2.0;
  centerMap();
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
    didDrag = false;
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
    const dx = e.clientX - panStartX;
    const dy = e.clientY - panStartY;
    if (Math.abs(dx) > 3 || Math.abs(dy) > 3) didDrag = true;
    camPanX = panStartCamX + dx;
    camPanY = panStartCamY + dy;
    draw();
    updateCoords(mx, my);
    return;
  }

  // Tooltip / highlight
  updateTooltip(e.clientX, e.clientY, mx, my);
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
async function tryAutoLoad() {
  try {
    const resp = await fetch('../output/course.json');
    if (resp.ok) {
      const json = await resp.json();
      loadCourseData(json);
      document.getElementById('filename').textContent = 'course.json (auto)';
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
    try {
      const json = JSON.parse(ev.target.result);
      loadCourseData(json);
      document.getElementById('filename').textContent = file.name;
    } catch (err) {
      alert('Erreur de parsing JSON: ' + err.message);
    }
  };
  reader.readAsText(file);
}

function loadCourseData(json) {
  courseData = json;
  heightmapPixels = null;
  terrainCache = null;
  ownerCache = null;

  // Decode heightmap
  if (json.terrain && json.terrain.elevation) {
    const b64 = json.terrain.elevation.data;
    const binary = atob(b64);
    heightmapPixels = new Uint8Array(binary.length);
    for (let i = 0; i < binary.length; i++) {
      heightmapPixels[i] = binary.charCodeAt(i);
    }
    buildTerrainCache();
  }

  // Cache owner
  if (json.paving && json.paving.owner) {
    const b64 = json.paving.owner.data;
    const binary = atob(b64);
    const bytes = new Uint8Array(binary.length);
    for (let i = 0; i < binary.length; i++) bytes[i] = binary.charCodeAt(i);
    ownerCache = new Int16Array(bytes.buffer);
  }

  updateHeader();
  updateLayerButtons();
  updateSidebar();

  centerMap();
  updateZoomDisplay();
  draw();
}

function buildTerrainCache() {
  const w = courseData.terrain.width;
  const h = courseData.terrain.height;
  const elev = courseData.terrain.elevation;
  const elevMin = elev.min_elevation;
  const elevMax = elev.max_elevation;
  const elevRange = elevMax - elevMin;
  const baseElev = courseData.metadata.config.base_elevation || 64;

  const oc = document.createElement('canvas');
  oc.width = w;
  oc.height = h;
  const octx = oc.getContext('2d');
  const imageData = octx.createImageData(w, h);
  const pixels = imageData.data;

  for (let y = 0; y < h; y++) {
    for (let x = 0; x < w; x++) {
      const idx = y * w + x;
      const val = heightmapPixels[idx];
      const realElev = elevMin + (val / 255) * elevRange;
      const [r, g, b] = elevationToColor(realElev, baseElev);
      const pidx = idx * 4;
      pixels[pidx] = r;
      pixels[pidx + 1] = g;
      pixels[pidx + 2] = b;
      pixels[pidx + 3] = 255;
    }
  }

  octx.putImageData(imageData, 0, 0);
  terrainCache = oc;
}

// === Header / Sidebar ===
function updateHeader() {
  const meta = courseData.metadata;
  document.getElementById('stat-seed').textContent = meta.seed;
  document.getElementById('stat-size').textContent =
    `${meta.config.width}x${meta.config.height}`;
  document.getElementById('stat-stages').textContent =
    meta.pipeline_stages.join(', ');

  if (courseData.routing) {
    const holes = courseData.routing.holes;
    const totalPar = holes.reduce((s, h) => s + h.par, 0);
    document.getElementById('stat-holes').textContent =
      `${holes.length} trous, par ${totalPar}`;
  } else {
    document.getElementById('stat-holes').textContent = 'N/A';
  }
}

function updateLayerButtons() {
  const stages = courseData.metadata.pipeline_stages;
  ['terrain', 'paving', 'clubhouse', 'routing', 'hazards', 'vegetation', 'features'].forEach(layer => {
    const btn = document.getElementById('btn-' + layer);
    if (btn) {
      const available = stages.includes(layer);
      btn.disabled = !available;
      btn.classList.toggle('active', available && show[layer]);
      if (!available) {
        btn.style.opacity = '0.3';
        show[layer] = false;
      }
    }
  });
}

function updateSidebar() {
  const tableContainer = document.getElementById('hole-tables');
  tableContainer.innerHTML = '';

  if (!courseData.routing) {
    tableContainer.innerHTML = '<div class="info-box">Pas de routing — executer le pipeline avec --stage routing</div>';
    return;
  }

  const holes = courseData.routing.holes;
  const frontHoles = holes.filter(h => h.id <= 9);
  const backHoles = holes.filter(h => h.id > 9);

  if (frontHoles.length > 0) {
    tableContainer.appendChild(createHoleTable('ALLER', frontHoles));
  }
  if (backHoles.length > 0) {
    tableContainer.appendChild(createHoleTable('RETOUR', backHoles));
  }
}

function createHoleTable(title, holes) {
  const container = document.createElement('div');
  const h2 = document.createElement('h2');
  h2.textContent = title;
  container.appendChild(h2);

  const table = document.createElement('table');
  table.className = 'hole-table';

  const thead = document.createElement('thead');
  thead.innerHTML = '<tr><th>#</th><th>Par</th><th>Blocs</th><th>m</th><th>Dir</th></tr>';
  table.appendChild(thead);

  const tbody = document.createElement('tbody');
  let totalPar = 0;
  let totalBlocks = 0;

  holes.forEach(h => {
    const parClass = h.par === 3 ? 'par3' : h.par === 5 ? 'par5' : 'par4';
    const meters = Math.round(h.blocks * (courseData.metadata.config.scale_ratio || 3));
    const dir = h.direction || '';
    totalPar += h.par;
    totalBlocks += h.blocks;

    const row = document.createElement('tr');
    row.className = parClass;
    row.dataset.holeId = h.id;
    row.innerHTML = `<td><strong>${h.id}</strong></td><td>${h.par}</td><td>${h.blocks}</td><td>${meters}</td><td>${dir}</td>`;
    row.addEventListener('mouseenter', () => setHighlight(h.id));
    row.addEventListener('mouseleave', () => setHighlight(null));
    tbody.appendChild(row);
  });

  const totalRow = document.createElement('tr');
  totalRow.className = 'total-row';
  totalRow.innerHTML = `<td></td><td>${totalPar}</td><td>${totalBlocks}</td><td>${Math.round(totalBlocks * (courseData.metadata.config.scale_ratio || 3))}</td><td></td>`;
  tbody.appendChild(totalRow);

  table.appendChild(tbody);
  container.appendChild(table);
  return container;
}

function setHighlight(id) {
  highlightedHole = id;
  document.querySelectorAll('.hole-table tr[data-hole-id]').forEach(r => {
    r.classList.toggle('active', parseInt(r.dataset.holeId) === id);
  });
  draw();
}

// === Drawing ===
function draw() {
  if (!courseData) return;

  ctx.fillStyle = '#1a2410';
  ctx.fillRect(0, 0, canvas.width, canvas.height);

  if (show.terrain) drawTerrain();
  if (show.paving && courseData.paving) drawPaving();
  if (show.hazards && courseData.hazards) drawHazards();
  if (show.vegetation && courseData.vegetation) drawVegetation();
  if (show.routing && courseData.routing) drawRouting();
  if (show.features && courseData.features) drawFeatures();
  if (show.grid) drawGrid();
}

function drawTerrain() {
  if (!terrainCache) return;
  const [dx, dy] = toCanvas(0, 0);
  const dw = terrainCache.width * camZoom;
  const dh = terrainCache.height * camZoom;
  ctx.imageSmoothingEnabled = false;
  ctx.drawImage(terrainCache, dx, dy, dw, dh);
}

function elevationToColor(elev, baseElev) {
  if (elev < baseElev - 2) {
    const depth = Math.max(0, Math.min(1, (baseElev - 2 - elev) / 6));
    return [
      Math.floor(30 - depth * 15),
      Math.floor(85 - depth * 30),
      Math.floor(130 + depth * 30)
    ];
  }
  if (elev < baseElev) {
    return [35, 95, 55];
  }
  const t = Math.min(1, Math.max(0, (elev - baseElev) / 18));
  if (t < 0.5) {
    const s = t * 2;
    return [
      Math.floor(30 + s * 25),
      Math.floor(70 + s * 50),
      Math.floor(28 + s * 15)
    ];
  } else {
    const s = (t - 0.5) * 2;
    return [
      Math.floor(55 + s * 40),
      Math.floor(120 - s * 20),
      Math.floor(43 - s * 10)
    ];
  }
}

function drawPaving() {
  if (!ownerCache) return;
  const pav = courseData.paving;
  const ts = pav.tile_size;
  const gw = pav.grid_width;
  const gh = pav.grid_height;

  // Viewport culling
  const [visX0, visY0] = toWorld(0, 0);
  const [visX1, visY1] = toWorld(canvas.width, canvas.height);
  const tx0 = Math.max(0, Math.floor(visX0 / ts));
  const ty0 = Math.max(0, Math.floor(visY0 / ts));
  const tx1 = Math.min(gw - 1, Math.ceil(visX1 / ts));
  const ty1 = Math.min(gh - 1, Math.ceil(visY1 / ts));

  for (let ty = ty0; ty <= ty1; ty++) {
    for (let tx = tx0; tx <= tx1; tx++) {
      const cellId = ownerCache[ty * gw + tx];
      if (cellId < 0) continue;

      const bx = tx * ts;
      const by = ty * ts;
      const [cx, cy] = toCanvas(bx, by);
      const sw = ts * camZoom;
      const sh = ts * camZoom;

      if (cellId === 18) {
        ctx.fillStyle = 'rgba(122, 107, 80, 0.5)';
      } else {
        const hue = (cellId * 20) % 360;
        ctx.fillStyle = `hsla(${hue}, 60%, 50%, 0.4)`;
      }
      ctx.fillRect(cx, cy, sw, sh);

      // Border
      ctx.strokeStyle = 'rgba(0, 0, 0, 0.5)';
      ctx.lineWidth = 1;

      const right = tx < gw - 1 ? ownerCache[ty * gw + tx + 1] : -2;
      const bottom = ty < gh - 1 ? ownerCache[(ty + 1) * gw + tx] : -2;

      if (right !== cellId) {
        ctx.beginPath();
        ctx.moveTo(cx + sw, cy);
        ctx.lineTo(cx + sw, cy + sh);
        ctx.stroke();
      }
      if (bottom !== cellId) {
        ctx.beginPath();
        ctx.moveTo(cx, cy + sh);
        ctx.lineTo(cx + sw, cy + sh);
        ctx.stroke();
      }
    }
  }

  // Labels
  const labelSize = Math.round(Math.max(7, Math.min(18, 9 * camZoom / 1.5)));
  pav.cells.forEach(cell => {
    if (cell.type === 'clubhouse') return;
    const bx = cell.seed_tx * ts + ts / 2;
    const by = cell.seed_ty * ts + ts / 2;
    const [cx, cy] = toCanvas(bx, by);

    ctx.font = `bold ${labelSize}px Silkscreen`;
    ctx.textAlign = 'center';
    ctx.textBaseline = 'middle';
    ctx.fillStyle = 'rgba(255, 255, 255, 0.9)';
    ctx.strokeStyle = 'rgba(0, 0, 0, 0.7)';
    ctx.lineWidth = 2;
    const label = `${cell.id + 1}`;
    ctx.strokeText(label, cx, cy);
    ctx.fillText(label, cx, cy);
  });
}

function drawRouting() {
  const routing = courseData.routing;
  const holes = routing.holes;
  const ch = courseData.clubhouse || routing.clubhouse;

  holes.forEach(h => {
    const hl = highlightedHole === h.id;
    const alpha = highlightedHole !== null && !hl ? 0.25 : 1;
    ctx.globalAlpha = alpha;

    const isBack = h.id >= 10;
    const baseColor = isBack ? '#4a9ed6' : '#6aad45';
    const greenColor = isBack ? '#3db8de' : '#3dbd4e';
    const fw = h.fairway_width || 12;
    const gr = h.green.radius || 8;

    // Glow si highlight
    if (hl) {
      ctx.shadowColor = isBack ? '#4a9ed6' : '#4ecf5f';
      ctx.shadowBlur = 16;
      ctx.strokeStyle = isBack ? 'rgba(74,158,214,0.35)' : 'rgba(78,207,95,0.35)';
      ctx.lineWidth = fw * camZoom + 10;
      ctx.lineCap = 'round';
      ctx.lineJoin = 'round';
      ctx.beginPath();
      const wps = h.waypoints;
      const [s0x, s0y] = toCanvas(wps[0].x, wps[0].y);
      ctx.moveTo(s0x, s0y);
      for (let i = 1; i < wps.length; i++) {
        const [wx, wy] = toCanvas(wps[i].x, wps[i].y);
        ctx.lineTo(wx, wy);
      }
      ctx.stroke();
      ctx.shadowBlur = 0;
    }

    // Fairway
    ctx.strokeStyle = baseColor;
    ctx.lineWidth = fw * camZoom;
    ctx.lineCap = 'round';
    ctx.lineJoin = 'round';
    ctx.beginPath();
    const wps = h.waypoints;
    const [sx, sy] = toCanvas(wps[0].x, wps[0].y);
    ctx.moveTo(sx, sy);
    for (let i = 1; i < wps.length; i++) {
      const [wx, wy] = toCanvas(wps[i].x, wps[i].y);
      ctx.lineTo(wx, wy);
    }
    ctx.stroke();

    // Green
    const [gx, gy] = toCanvas(h.green.x, h.green.y);
    ctx.beginPath();
    ctx.arc(gx, gy, gr * camZoom, 0, Math.PI * 2);
    ctx.fillStyle = greenColor;
    ctx.fill();

    // Flag
    const flagScale = Math.max(0.6, Math.min(2, camZoom / 1.5));
    ctx.fillStyle = C.flag;
    ctx.fillRect(gx - 1 * flagScale, gy - 7 * flagScale, 2 * flagScale, 9 * flagScale);
    ctx.beginPath();
    ctx.moveTo(gx + 1 * flagScale, gy - 7 * flagScale);
    ctx.lineTo(gx + 5 * flagScale, gy - 4.5 * flagScale);
    ctx.lineTo(gx + 1 * flagScale, gy - 2 * flagScale);
    ctx.fill();

    // Tee
    const [tx, ty] = toCanvas(h.tee.x, h.tee.y);
    ctx.fillStyle = C.tee;
    ctx.fillRect(tx - 4 * camZoom, ty - 2.5 * camZoom, 8 * camZoom, 5 * camZoom);

    ctx.globalAlpha = 1;

    // Numeros
    if (show.nums) {
      const mi = Math.floor(wps.length / 2);
      const [nx, ny] = toCanvas(wps[mi].x, wps[mi].y);

      const numSize = Math.round(Math.max(8, Math.min(20, (hl ? 12 : 10) * camZoom / 1.5)));
      ctx.font = hl ? `bold ${numSize}px Silkscreen` : `${numSize}px Silkscreen`;
      ctx.textAlign = 'center';
      ctx.textBaseline = 'middle';

      const numText = String(h.id);
      const tw = ctx.measureText(numText).width;
      const pillPad = Math.max(6, 10 * camZoom / 2);
      const pillH = numSize + 5;
      const pillW = tw + pillPad * 2;
      const pillX = nx - pillW / 2;
      const pillY = ny - pillH / 2 - numSize;

      ctx.fillStyle = hl
        ? (isBack ? 'rgba(74,158,214,0.9)' : 'rgba(78,207,95,0.9)')
        : 'rgba(0,0,0,0.7)';
      ctx.beginPath();
      ctx.roundRect(pillX, pillY, pillW, pillH, 3);
      ctx.fill();

      if (!hl) {
        ctx.strokeStyle = isBack ? 'rgba(74,158,214,0.3)' : 'rgba(78,207,95,0.2)';
        ctx.lineWidth = 0.5;
        ctx.stroke();
      }

      ctx.fillStyle = hl ? '#000' : (isBack ? 'rgba(140,200,255,0.9)' : 'rgba(200,255,200,0.9)');
      ctx.fillText(numText, nx, pillY + pillH / 2);
    }
  });

  // Clubhouse (ch.x, ch.y = centre)
  if (ch) {
    const [chCx, chCy] = toCanvas(ch.x, ch.y);
    const chw = ch.width * camZoom;
    const chh = ch.height * camZoom;
    const chx = chCx - chw / 2;
    const chy = chCy - chh / 2;

    ctx.fillStyle = 'rgba(0,0,0,0.35)';
    ctx.fillRect(chx + 3, chy + 3, chw, chh);

    ctx.fillStyle = '#7a6b50';
    ctx.fillRect(chx, chy, chw, chh);
    ctx.fillStyle = '#a08b6e';
    ctx.fillRect(chx - 3, chy - 4, chw + 6, 8);

    ctx.strokeStyle = 'rgba(255,255,255,0.3)';
    ctx.lineWidth = 1.5;
    ctx.strokeRect(chx, chy, chw, chh);

    const chFontSize = Math.round(Math.max(7, Math.min(14, 9 * camZoom / 1.5)));
    ctx.fillStyle = '#fff';
    ctx.font = `bold ${chFontSize}px Silkscreen`;
    ctx.textAlign = 'center';
    ctx.fillText('CLUB', chCx, chCy - 2);
    ctx.fillText('HOUSE', chCx, chCy + chFontSize + 1);

    // Practice range
    if (ch.practice_range) {
      const pr = ch.practice_range;
      const [px, py] = toCanvas(pr.x, pr.y);
      const pw = pr.width * camZoom;
      const ph = pr.height * camZoom;

      ctx.fillStyle = 'rgba(85, 140, 55, 0.4)';
      ctx.fillRect(px, py, pw, ph);
      ctx.strokeStyle = 'rgba(255, 255, 255, 0.15)';
      ctx.lineWidth = 1;
      ctx.strokeRect(px, py, pw, ph);

      const prFontSize = Math.round(Math.max(6, Math.min(12, 8 * camZoom / 1.5)));
      ctx.fillStyle = 'rgba(255, 255, 255, 0.45)';
      ctx.font = `${prFontSize}px Silkscreen`;
      ctx.textAlign = 'center';
      ctx.fillText('PRACTICE', px + pw / 2, py + ph / 2 + 3);
    }

    // Putting green
    if (ch.putting_green) {
      const pg = ch.putting_green;
      const [pgx, pgy] = toCanvas(pg.x, pg.y);
      const pgr = pg.radius * camZoom;

      ctx.fillStyle = 'rgba(61, 189, 78, 0.5)';
      ctx.beginPath();
      ctx.arc(pgx, pgy, pgr, 0, Math.PI * 2);
      ctx.fill();
      ctx.strokeStyle = 'rgba(255, 255, 255, 0.15)';
      ctx.lineWidth = 1;
      ctx.stroke();

      const pgFontSize = Math.round(Math.max(5, Math.min(10, 7 * camZoom / 1.5)));
      ctx.fillStyle = 'rgba(255, 255, 255, 0.5)';
      ctx.font = `${pgFontSize}px Silkscreen`;
      ctx.textAlign = 'center';
      ctx.textBaseline = 'middle';
      ctx.fillText('PUTT', pgx, pgy);
    }
  }
}

function drawHazards() {
  const hazards = courseData.hazards;

  // Bunkers
  if (hazards.bunkers) {
    hazards.bunkers.forEach(b => {
      const [bx, by] = toCanvas(b.x, b.y);
      const rx = (b.radius_x || b.radius || 5) * camZoom;
      const ry = (b.radius_y || b.radius || 4) * camZoom;
      ctx.fillStyle = C.sand;
      ctx.beginPath();
      ctx.ellipse(bx, by, rx, ry, b.angle || 0, 0, Math.PI * 2);
      ctx.fill();
      ctx.strokeStyle = C.sandDark;
      ctx.lineWidth = 1;
      ctx.stroke();
    });
  }

  // Eau
  if (hazards.water_bodies) {
    hazards.water_bodies.forEach(wb => {
      if (wb.points) {
        ctx.fillStyle = 'rgba(30, 85, 130, 0.75)';
        ctx.beginPath();
        const [sx, sy] = toCanvas(wb.points[0].x, wb.points[0].y);
        ctx.moveTo(sx, sy);
        for (let i = 1; i < wb.points.length; i++) {
          const [nx, ny] = toCanvas(wb.points[i].x, wb.points[i].y);
          ctx.lineTo(nx, ny);
        }
        ctx.closePath();
        ctx.fill();

        ctx.strokeStyle = 'rgba(80, 160, 210, 0.25)';
        ctx.lineWidth = 1.5;
        ctx.stroke();
      } else {
        const [wx, wy] = toCanvas(wb.x, wb.y);
        const rx = (wb.radius_x || 30) * camZoom;
        const ry = (wb.radius_y || 20) * camZoom;
        ctx.fillStyle = 'rgba(30, 85, 130, 0.75)';
        ctx.beginPath();
        ctx.ellipse(wx, wy, rx, ry, 0, 0, Math.PI * 2);
        ctx.fill();
      }

      if (wb.label) {
        const lx = wb.label_x || wb.x;
        const ly = wb.label_y || wb.y;
        ctx.fillStyle = 'rgba(120, 200, 255, 0.3)';
        ctx.font = '10px Silkscreen';
        ctx.textAlign = 'center';
        ctx.fillText(wb.label, ...toCanvas(lx, ly));
      }
    });
  }

  // Ravins
  if (hazards.ravines) {
    hazards.ravines.forEach(r => {
      if (!r.points || r.points.length < 2) return;
      ctx.strokeStyle = 'rgba(60, 45, 30, 0.55)';
      ctx.lineWidth = (r.width || 6) * camZoom;
      ctx.lineCap = 'round';
      ctx.beginPath();
      const [sx, sy] = toCanvas(r.points[0].x, r.points[0].y);
      ctx.moveTo(sx, sy);
      for (let i = 1; i < r.points.length; i++) {
        const [nx, ny] = toCanvas(r.points[i].x, r.points[i].y);
        ctx.lineTo(nx, ny);
      }
      ctx.stroke();

      ctx.strokeStyle = 'rgba(30, 20, 15, 0.5)';
      ctx.lineWidth = (r.width || 6) * 0.4 * camZoom;
      ctx.beginPath();
      ctx.moveTo(sx, sy);
      for (let i = 1; i < r.points.length; i++) {
        const [nx, ny] = toCanvas(r.points[i].x, r.points[i].y);
        ctx.lineTo(nx, ny);
      }
      ctx.stroke();
    });
  }
}

function drawVegetation() {
  const veg = courseData.vegetation;

  // Forets denses
  if (veg.dense_forests) {
    let seed = 1337;
    function sR() {
      seed = (seed * 16807) % 2147483647;
      return (seed - 1) / 2147483646;
    }

    veg.dense_forests.forEach(cl => {
      for (let i = 0; i < cl.count; i++) {
        const tx = cl.x + (sR() - 0.5) * cl.spread * 2;
        const ty = cl.y + (sR() - 0.5) * cl.spread * 2;
        const r = (3.5 + sR() * 4) * camZoom;
        const [cx, cy] = toCanvas(tx, ty);

        ctx.fillStyle = 'rgba(0, 20, 0, 0.4)';
        ctx.beginPath();
        ctx.arc(cx + 1.5, cy + 2, r * 1.05, 0, Math.PI * 2);
        ctx.fill();

        const g = Math.floor(45 + sR() * 35);
        ctx.fillStyle = `rgba(18, ${g}, 12, 0.85)`;
        ctx.beginPath();
        ctx.arc(cx, cy, r, 0, Math.PI * 2);
        ctx.fill();

        ctx.fillStyle = `rgba(35, ${g + 20}, 22, 0.25)`;
        ctx.beginPath();
        ctx.arc(cx - r * 0.2, cy - r * 0.2, r * 0.4, 0, Math.PI * 2);
        ctx.fill();
      }
    });
  }

  // Clusters d'arbres
  if (veg.tree_clusters) {
    let seed = 42;
    function sRand() {
      seed = (seed * 16807) % 2147483647;
      return (seed - 1) / 2147483646;
    }

    veg.tree_clusters.forEach(cl => {
      for (let i = 0; i < cl.count; i++) {
        const tx = cl.x + (sRand() - 0.5) * cl.spread * 2;
        const ty = cl.y + (sRand() - 0.5) * cl.spread * 2;
        const r = (3 + sRand() * 3.5) * camZoom;
        const [cx, cy] = toCanvas(tx, ty);

        ctx.fillStyle = 'rgba(0, 25, 0, 0.3)';
        ctx.beginPath();
        ctx.arc(cx + 2, cy + 2, r, 0, Math.PI * 2);
        ctx.fill();

        const green = Math.floor(55 + sRand() * 45);
        ctx.fillStyle = `rgba(22, ${green}, 15, 0.8)`;
        ctx.beginPath();
        ctx.arc(cx, cy, r, 0, Math.PI * 2);
        ctx.fill();

        ctx.fillStyle = `rgba(45, ${green + 30}, 28, 0.3)`;
        ctx.beginPath();
        ctx.arc(cx - r * 0.25, cy - r * 0.25, r * 0.45, 0, Math.PI * 2);
        ctx.fill();
      }
    });
  }
}

function drawFeatures() {
  const feat = courseData.features;

  // Ponts
  if (feat.bridges) {
    feat.bridges.forEach(br => {
      const [bsx, bsy] = toCanvas(br.start.x, br.start.y);
      const [bex, bey] = toCanvas(br.end.x, br.end.y);

      ctx.strokeStyle = '#8b7355';
      ctx.lineWidth = 5 * camZoom;
      ctx.lineCap = 'round';
      ctx.beginPath();
      ctx.moveTo(bsx, bsy);
      ctx.lineTo(bex, bey);
      ctx.stroke();

      ctx.strokeStyle = '#6b5540';
      ctx.lineWidth = 1;
      const angle = Math.atan2(bey - bsy, bex - bsx);
      const perpX = Math.sin(angle) * 3 * camZoom;
      const perpY = -Math.cos(angle) * 3 * camZoom;

      ctx.beginPath();
      ctx.moveTo(bsx + perpX, bsy + perpY);
      ctx.lineTo(bex + perpX, bey + perpY);
      ctx.stroke();
      ctx.beginPath();
      ctx.moveTo(bsx - perpX, bsy - perpY);
      ctx.lineTo(bex - perpX, bey - perpY);
      ctx.stroke();
    });
  }

  // Ruisseaux
  if (feat.streams) {
    feat.streams.forEach(s => {
      if (!s.points || s.points.length < 2) return;
      ctx.strokeStyle = 'rgba(60, 140, 190, 0.45)';
      ctx.lineWidth = 2.5 * camZoom;
      ctx.lineCap = 'round';
      ctx.beginPath();
      const [sx, sy] = toCanvas(s.points[0].x, s.points[0].y);
      ctx.moveTo(sx, sy);
      for (let i = 1; i < s.points.length; i++) {
        const [nx, ny] = toCanvas(s.points[i].x, s.points[i].y);
        ctx.lineTo(nx, ny);
      }
      ctx.stroke();
    });
  }

  // Practice range (from features)
  if (feat.practice_range) {
    const pr = feat.practice_range;
    const [px, py] = toCanvas(pr.x, pr.y);
    const pw = pr.width * camZoom;
    const ph = pr.height * camZoom;

    ctx.fillStyle = 'rgba(85, 140, 55, 0.4)';
    ctx.fillRect(px, py, pw, ph);
    ctx.strokeStyle = 'rgba(255, 255, 255, 0.1)';
    ctx.lineWidth = 1;
    ctx.strokeRect(px, py, pw, ph);

    ctx.fillStyle = 'rgba(255, 255, 255, 0.4)';
    ctx.font = '8px Silkscreen';
    ctx.textAlign = 'center';
    ctx.fillText('PRACTICE', px + pw / 2, py + ph + 12);
  }
}

function drawGrid() {
  if (!courseData) return;
  const w = courseData.metadata.config.width || 600;
  const h = courseData.metadata.config.height || 600;

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

  // Vertical lines
  for (let x = 0; x <= w; x += step) {
    const [cx] = toCanvas(x, 0);
    if (cx < -1 || cx > canvas.width + 1) continue;
    ctx.beginPath();
    ctx.moveTo(cx, gridY0);
    ctx.lineTo(cx, gridY1);
    ctx.stroke();
  }

  // Horizontal lines
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
  ctx.fillStyle = 'rgba(255,255,255,0.12)';
  ctx.font = `${Math.round(labelSize)}px IBM Plex Mono`;

  // X labels (top)
  ctx.textAlign = 'center';
  const labelStep = step < 50 ? step * 2 : step;
  for (let x = 0; x <= w; x += labelStep) {
    const [cx, cy] = toCanvas(x, 0);
    if (cx < 20 || cx > canvas.width - 20) continue;
    ctx.fillText(x, cx, cy - 6);
  }

  // Y labels (left)
  ctx.textAlign = 'right';
  for (let y = 0; y <= h; y += labelStep) {
    const [cx, cy] = toCanvas(0, y);
    if (cy < 10 || cy > canvas.height - 10) continue;
    ctx.fillText(y, cx - 6, cy + 3);
  }

  // Nord
  const [nfx, nfy] = toCanvas(w - 20, 15);
  if (nfx > 0 && nfx < canvas.width && nfy > 0 && nfy < canvas.height) {
    ctx.fillStyle = 'rgba(255,255,255,0.25)';
    ctx.font = 'bold 12px Silkscreen';
    ctx.textAlign = 'center';
    ctx.fillText('N', nfx, nfy);
  }
}

function showNoData() {
  ctx.fillStyle = '#1a2410';
  ctx.fillRect(0, 0, canvas.width, canvas.height);

  ctx.fillStyle = 'rgba(255,255,255,0.2)';
  ctx.font = '14px Silkscreen';
  ctx.textAlign = 'center';
  ctx.fillText('Aucune donnee chargee', canvas.width / 2, canvas.height / 2 - 20);
  ctx.font = '11px IBM Plex Mono';
  ctx.fillStyle = 'rgba(255,255,255,0.15)';
  ctx.fillText('Charger un JSON ou executer :', canvas.width / 2, canvas.height / 2 + 10);
  ctx.fillText('python pipeline.py --stage terrain', canvas.width / 2, canvas.height / 2 + 30);
}

// === Tooltip / Coords ===
function updateCoords(mx, my) {
  if (!courseData) return;
  const [bx, by] = toWorld(mx, my);
  const w = courseData.metadata.config.width || 600;
  const h = courseData.metadata.config.height || 600;
  const ix = Math.round(bx);
  const iy = Math.round(by);

  if (ix >= 0 && ix < w && iy >= 0 && iy < h) {
    let info = `Bloc (${ix}, ${iy})`;
    if (heightmapPixels) {
      const idx = iy * w + ix;
      const val = heightmapPixels[idx];
      const elev = courseData.terrain.elevation;
      const realElev = elev.min_elevation + (val / 255) * (elev.max_elevation - elev.min_elevation);
      info += ` — Y=${realElev.toFixed(1)}`;
    }
    if (ownerCache && courseData.paving) {
      const ts = courseData.paving.tile_size;
      const gw = courseData.paving.grid_width;
      const ttx = Math.floor(ix / ts);
      const tty = Math.floor(iy / ts);
      if (ttx >= 0 && ttx < gw && tty >= 0 && tty < courseData.paving.grid_height) {
        const cellId = ownerCache[tty * gw + ttx];
        info += ` — Cell ${cellId}`;
      }
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
  const w = courseData.metadata.config.width || 600;
  const h = courseData.metadata.config.height || 600;
  const ix = Math.round(bx);
  const iy = Math.round(by);

  updateCoords(mx, my);

  if (ix >= 0 && ix < w && iy >= 0 && iy < h && courseData.routing) {
    const hit = getHoleAt(bx, by);
    if (hit) {
      tooltip.style.display = 'block';
      tooltip.style.left = (clientX + 12) + 'px';
      tooltip.style.top = (clientY + 12) + 'px';
      const meters = Math.round(hit.hole.blocks * (courseData.metadata.config.scale_ratio || 3));
      tooltip.innerHTML = `<div class="tt-title">Trou ${hit.hole.id} — Par ${hit.hole.par}</div>${hit.hole.blocks} blocs (${meters}m)<br><span style="color:rgba(255,255,255,0.4)">${hit.zone}</span>`;
      setHighlight(hit.hole.id);
      return;
    }
  }

  tooltip.style.display = 'none';
  if (highlightedHole !== null) setHighlight(null);
}

function getHoleAt(bx, by) {
  if (!courseData.routing) return null;
  for (const h of courseData.routing.holes) {
    if (Math.hypot(bx - h.green.x, by - h.green.y) < (h.green.radius || 8) + 2)
      return { hole: h, zone: 'green' };
    if (Math.hypot(bx - h.tee.x, by - h.tee.y) < 6)
      return { hole: h, zone: 'tee' };
    const wps = h.waypoints;
    for (let i = 0; i < wps.length - 1; i++) {
      if (pointToSegDist(bx, by, wps[i].x, wps[i].y, wps[i + 1].x, wps[i + 1].y)
          < (h.fairway_width || 12))
        return { hole: h, zone: 'fairway' };
    }
  }
  return null;
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
  if (btn) btn.classList.toggle('active');
  draw();
}

// === Start ===
init();
