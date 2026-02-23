/**
 * GolfGen — Editeur de parcours de golf interactif.
 * Rendu canvas, camera, UI, orchestration.
 */

// === State ===
let courseData = null;
let heightmapPixels = null;
let terrainCache = null;

// Camera
let camZoom = 2.0;
let camPanX = 0;
let camPanY = 0;
const MIN_ZOOM = 0.5;
const MAX_ZOOM = 10;

// Layers
let show = {
  terrain: true,
  water: true,
  routing: true,
  grid: true,
  nums: true,
  pixel: false,
};

let highlightedHole = null;

// Pan state
let isPanning = false;
let panStartX = 0;
let panStartY = 0;
let panStartCamX = 0;
let panStartCamY = 0;
let didDrag = false;

// Draw drag detection (freehand vs click)
let drawMouseStartX = 0;
let drawMouseStartY = 0;
let drawDidDrag = false;

// Waypoint drag state
let isDraggingWaypoint = false;
let draggingHoleId = null;
let draggingWaypointIdx = null;

// Facility resize state
let isResizingFacility = false;
// DnD reorder holes state
let dragSourceId = null;
let dropBeforeId = null;
let _dropIndicator = null;
let resizeFacilityId = null;
let resizeFacilityHandle = null; // 'tl'|'tr'|'bl'|'br'|'t'|'b'|'l'|'r'
let resizeFacilityOrigRect = null;
let resizeFacilityStartWX = 0;
let resizeFacilityStartWY = 0;

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
  window.addEventListener('resize', resizeCanvas);

  canvas.addEventListener('wheel', onWheel, { passive: false });
  canvas.addEventListener('mousedown', onMouseDown);
  window.addEventListener('mousemove', onMouseMove);
  window.addEventListener('mouseup', onMouseUp);
  canvas.addEventListener('mouseleave', onMouseLeave);
  canvas.addEventListener('dblclick', onDblClick);
  canvas.addEventListener('contextmenu', (e) => e.preventDefault());
  window.addEventListener('keydown', onKeyDown);

  // Drop indicator DnD (singleton réutilisé entre rebuilds)
  _dropIndicator = document.createElement('tr');
  _dropIndicator.className = 'drop-indicator';
  _dropIndicator.innerHTML = '<td colspan="5"></td>';

  // Editor callbacks
  editorSetOnChange(onEditorChange);
  editorSetDrawCallback(() => draw());
  heSetDrawCallback(() => drawHoleEditor());

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

function getOrigin() {
  const x = parseInt(document.getElementById('origin-x-input').value) || 0;
  const z = parseInt(document.getElementById('origin-z-input').value) || 0;
  return { x, z };
}

function centerMap() {
  if (!courseData) return;
  const w = courseData.metadata.config.width || 350;
  const h = courseData.metadata.config.height || 350;
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
  // Clic droit ou molette = pan toujours
  if (e.button === 2 || e.button === 1) {
    isPanning = true;
    didDrag = false;
    panStartX = e.clientX;
    panStartY = e.clientY;
    panStartCamX = camPanX;
    panStartCamY = camPanY;
    canvas.style.cursor = 'grabbing';
    return;
  }

  // Clic gauche
  if (e.button === 0) {
    const rect = canvas.getBoundingClientRect();
    const mx = e.clientX - rect.left;
    const my = e.clientY - rect.top;
    const [wx, wy] = toWorld(mx, my);

    // Priorité 1 : mode facility → dessiner un rectangle
    if (getFacilityMode()) {
      facilityDragStart(wx, wy);
      return;
    }

    // Priorité 2 : mode draw → freehand ou point-par-point
    if (getEditorMode() === 'draw') {
      if (freehandStart(wx, wy)) {
        drawMouseStartX = e.clientX;
        drawMouseStartY = e.clientY;
        drawDidDrag = false;
        return;
      }
      handleCanvasClick(wx, wy);
      return;
    }

    // Mode view : check resize handle de la facility sélectionnée
    const handle = getFacilityHandleAt(wx, wy);
    if (handle) {
      const f = getFacilities().find(f => f.id === handle.id);
      isResizingFacility = true;
      resizeFacilityId = handle.id;
      resizeFacilityHandle = handle.handle;
      resizeFacilityOrigRect = { x: f.x, y: f.y, w: f.w, h: f.h };
      resizeFacilityStartWX = wx;
      resizeFacilityStartWY = wy;
      canvas.style.cursor = 'nwse-resize';
      return;
    }

    // Mode view : drag d'un waypoint de trou sélectionné
    const wpHit = getHoleWaypointAt(wx, wy);
    if (wpHit) {
      isDraggingWaypoint = true;
      draggingHoleId = wpHit.holeId;
      draggingWaypointIdx = wpHit.idx;
      canvas.style.cursor = 'move';
      return;
    }

    // Mode view : sélection d'une facility
    const hitFacility = getFacilityAt(wx, wy);
    if (hitFacility) {
      selectFacility(hitFacility.id);
      return;
    }

    // En mode view, clic gauche = pan
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
  if (getHeEditingHoleId() !== null) return;
  const rect = canvas.getBoundingClientRect();
  const mx = e.clientX - rect.left;
  const my = e.clientY - rect.top;
  const [wx, wy] = toWorld(mx, my);

  setMouseWorld(wx, wy);

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

  // Facility drag (dessin rectangle)
  if (isFacilityDragActive()) {
    facilityDragMove(wx, wy);
    draw();
    updateCoords(mx, my);
    return;
  }

  // Facility resize
  if (isResizingFacility) {
    const dx = wx - resizeFacilityStartWX;
    const dy = wy - resizeFacilityStartWY;
    const o = resizeFacilityOrigRect;
    let nx = o.x, ny = o.y, nw = o.w, nh = o.h;
    const h = resizeFacilityHandle;
    if (h === 'tl') { nx = o.x + dx; ny = o.y + dy; nw = o.w - dx; nh = o.h - dy; }
    else if (h === 'tr') { ny = o.y + dy; nw = o.w + dx; nh = o.h - dy; }
    else if (h === 'bl') { nx = o.x + dx; nw = o.w - dx; nh = o.h + dy; }
    else if (h === 'br') { nw = o.w + dx; nh = o.h + dy; }
    else if (h === 't')  { ny = o.y + dy; nh = o.h - dy; }
    else if (h === 'b')  { nh = o.h + dy; }
    else if (h === 'l')  { nx = o.x + dx; nw = o.w - dx; }
    else if (h === 'r')  { nw = o.w + dx; }
    nw = Math.max(5, nw);
    nh = Math.max(5, nh);
    updateFacility(resizeFacilityId, nx, ny, nw, nh);
    return;
  }

  // Waypoint drag
  if (isDraggingWaypoint) {
    moveWaypoint(draggingHoleId, draggingWaypointIdx, wx, wy);
    syncRouting(); // mise à jour en temps réel sans déclencher autosave/sidebar
    draw();
    return;
  }

  // Freehand en cours
  if (isFreehandActive()) {
    const dx = e.clientX - drawMouseStartX;
    const dy = e.clientY - drawMouseStartY;
    if (Math.abs(dx) > 3 || Math.abs(dy) > 3) drawDidDrag = true;
    freehandMove(wx, wy);
    draw();
    updateCoords(mx, my);
    return;
  }

  // Preview dessin point par point
  if (getEditorMode() === 'draw' && getCurrentHole()) {
    draw();
  }

  updateTooltip(e.clientX, e.clientY, mx, my);
}

function onMouseUp(e) {
  if (getHeEditingHoleId() !== null) return;
  if (e.button !== 0) {
    if (isPanning) {
      isPanning = false;
      canvas.style.cursor = getEditorMode() === 'draw' ? 'crosshair' : 'grab';
    }
    return;
  }

  // Fin du drag facility (dessin)
  if (isFacilityDragActive()) {
    facilityDragEnd();
    canvas.style.cursor = 'crosshair';
    return;
  }

  // Fin du drag waypoint
  if (isDraggingWaypoint) {
    isDraggingWaypoint = false;
    draggingHoleId = null;
    draggingWaypointIdx = null;
    finalizeWaypointMove();
    canvas.style.cursor = 'grab';
    return;
  }

  // Fin du resize facility
  if (isResizingFacility) {
    isResizingFacility = false;
    resizeFacilityId = null;
    resizeFacilityHandle = null;
    resizeFacilityOrigRect = null;
    canvas.style.cursor = 'grab';
    return;
  }

  // Fin du freehand
  if (isFreehandActive()) {
    freehandEnd();
    canvas.style.cursor = 'crosshair';
    return;
  }

  if (isPanning) {
    isPanning = false;
    canvas.style.cursor = getEditorMode() === 'draw' ? 'crosshair' : 'grab';

    if (!didDrag && e.button === 0 && getEditorMode() === 'view' && courseData) {
      const rect = canvas.getBoundingClientRect();
      const mx = e.clientX - rect.left;
      const my = e.clientY - rect.top;
      const [wx, wy] = toWorld(mx, my);
      selectFacility(null); // désélectionner la facility si clic sur espace vide
      const hit = getHoleAt(wx, wy);
      selectHole(hit ? hit.hole.id : null);
    }
  }
}

function onMouseLeave() {
  tooltip.style.display = 'none';
  if (highlightedHole !== null) setHighlight(null);
}

function onDblClick(e) {
  if (getHeEditingHoleId() !== null) return;
  if (getEditorMode() === 'draw') {
    handleCanvasDblClick();
  }
}

// === Terrain generation ===
function generateAndDisplay() {
  const seed = parseInt(document.getElementById('seed-input').value) || 42;
  const result = generateTerrain({ seed, width: 350, height: 350 });

  heightmapPixels = result.heightmap;

  const courseName = document.getElementById('course-name-input').value.trim();
  const origin = getOrigin();

  courseData = {
    metadata: {
      version: '3.0',
      name: courseName || null,
      seed: seed,
      origin: (origin.x !== 0 || origin.z !== 0) ? origin : null,
      config: { width: 350, height: 350, scale_ratio: 3.0, base_elevation: 64 },
    },
    terrain: {
      width: 350,
      height: 350,
      elevation: {
        encoding: 'raw',
        min_elevation: result.minElevation,
        max_elevation: result.maxElevation,
      },
    },
  };

  buildTerrainCache();
  updateHeader();
  syncRouting();
  updateSidebar();
  centerMap();
  updateZoomDisplay();
  draw();
}

// === File loading ===
function tryAutoLoad() {
  const saved = localStorage.getItem('golfgen_autosave');
  if (saved) {
    try {
      const state = JSON.parse(saved);
      if (state.seed != null) {
        if (state.name) document.getElementById('course-name-input').value = state.name;
        if (state.origin) {
          document.getElementById('origin-x-input').value = state.origin.x;
          document.getElementById('origin-z-input').value = state.origin.z;
        }
        document.getElementById('seed-input').value = state.seed;
        generateAndDisplay();
        if (state.holes && state.holes.length > 0) {
          const routingHoles = state.holes.map((h) => ({
            id: h.id,
            par: h.par,
            blocks: h.blocks,
            direction: h.direction,
            fairway_width: h.fairwayWidth,
            tee: h.points[0],
            green: { ...h.points[h.points.length - 1], radius: h.greenRadius },
            waypoints: h.points,
            features: h.features,
          }));
          importHoles(routingHoles);
          syncRouting();
          updateSidebar();
          draw();
        }
        if (state.facilities && state.facilities.length > 0) {
          importFacilities(state.facilities.map(f => ({
            type: f.type, x: f.x, y: f.y, width: f.w, height: f.h,
          })));
          draw();
        }
        return;
      }
    } catch (e) {
      // Ignore
    }
  }
  showNoData();
}

function handleFileLoad(e) {
  const file = e.target.files[0];
  if (!file) return;
  const reader = new FileReader();
  reader.onload = (ev) => {
    try {
      const json = JSON.parse(ev.target.result);
      loadCourseData(json);
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

  const nameInput = document.getElementById('course-name-input');
  nameInput.value = (json.metadata && json.metadata.name) ? json.metadata.name : '';
  const originX = document.getElementById('origin-x-input');
  const originZ = document.getElementById('origin-z-input');
  if (json.metadata && json.metadata.origin) {
    originX.value = json.metadata.origin.x || '';
    originZ.value = json.metadata.origin.z || '';
  } else {
    originX.value = '';
    originZ.value = '';
  }

  if (json.terrain && json.terrain.elevation && json.terrain.elevation.data) {
    const b64 = json.terrain.elevation.data;
    const binary = atob(b64);
    heightmapPixels = new Uint8Array(binary.length);
    for (let i = 0; i < binary.length; i++) {
      heightmapPixels[i] = binary.charCodeAt(i);
    }
    buildTerrainCache();
  }

  if (json.routing && json.routing.facilities) {
    importFacilities(json.routing.facilities);
  }
  if (json.routing && json.routing.holes) {
    importHoles(json.routing.holes);
  }

  updateHeader();
  syncRouting();
  updateSidebar();
  centerMap();
  updateZoomDisplay();
  draw();
}

// === Terrain cache ===
function buildTerrainCache() {
  const w = courseData.terrain.width;
  const h = courseData.terrain.height;
  const elev = courseData.terrain.elevation;
  const elevMin = elev.min_elevation;
  const elevMax = elev.max_elevation;
  const elevRange = elevMax - elevMin;
  const baseElev = (courseData.metadata.config && courseData.metadata.config.base_elevation) || 64;

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
  if (!courseData) return;
  const meta = courseData.metadata;
  document.getElementById('stat-seed').textContent = meta.seed;
  document.getElementById('stat-size').textContent = `${meta.config.width}x${meta.config.height}`;

  const holes = getHoles();
  if (holes.length > 0) {
    const totalPar = holes.reduce((s, h) => s + h.par, 0);
    document.getElementById('stat-holes').textContent = `${holes.length} trous, par ${totalPar}`;
  } else {
    document.getElementById('stat-holes').textContent = '0';
  }
}

function syncRouting() {
  if (!courseData) return;
  const routing = buildRoutingData();
  if (routing.holes.length > 0) {
    courseData.routing = routing;
  } else {
    delete courseData.routing;
  }
}

function onEditorChange() {
  if (getHeEditingHoleId() !== null) {
    heBlockCache = null;
    heBlockCacheBounds = null;
  }
  syncRouting();
  updateHeader();
  updateSidebar();
  autoSave();
  scheduleBlockMapRebuild();
}

function updateSidebar() {
  const tableContainer = document.getElementById('hole-tables');
  tableContainer.innerHTML = '';

  const holes = getHoles();
  if (holes.length === 0) {
    tableContainer.innerHTML = '<div class="info-box">Generer un terrain puis dessiner des trous.</div>';
    return;
  }

  tableContainer.appendChild(buildHoleTable(holes));
}

function buildHoleTable(holes) {
  const scaleRatio = (courseData && courseData.metadata.config.scale_ratio) || 3;
  const selId = getSelectedHoleId();

  const table = document.createElement('table');
  table.className = 'hole-table';

  const thead = document.createElement('thead');
  thead.innerHTML = '<tr><th>#</th><th>Par</th><th>Blocs</th><th>m</th><th>Dir</th></tr>';
  table.appendChild(thead);

  const tbody = document.createElement('tbody');

  function addSection(title, sectionHoles) {
    const headerRow = document.createElement('tr');
    headerRow.className = 'section-header';
    headerRow.innerHTML = `<td colspan="5">${title}</td>`;
    tbody.appendChild(headerRow);

    let totalPar = 0;
    let totalBlocks = 0;

    sectionHoles.forEach((h) => {
      const parClass = h.par === 3 ? 'par3' : h.par === 5 ? 'par5' : 'par4';
      const meters = Math.round(h.blocks * scaleRatio);
      totalPar += h.par;
      totalBlocks += h.blocks;

      const row = document.createElement('tr');
      row.className = parClass;
      if (h.id === selId) row.classList.add('selected');
      row.dataset.holeId = h.id;
      row.draggable = true;
      row.innerHTML = `<td><strong>${h.id}</strong></td><td>${h.par}</td><td>${h.blocks}</td><td>${meters}</td><td>${h.direction}</td>`;
      row.addEventListener('mouseenter', () => setHighlight(h.id));
      row.addEventListener('mouseleave', () => setHighlight(null));
      row.addEventListener('click', () => selectHole(h.id));

      row.addEventListener('dragstart', (e) => {
        dragSourceId = h.id;
        e.dataTransfer.effectAllowed = 'move';
        // Délai pour que le navigateur capture le snapshot avant d'appliquer l'opacité
        setTimeout(() => row.classList.add('dragging'), 0);
      });

      row.addEventListener('dragend', () => {
        row.classList.remove('dragging');
        _dropIndicator.remove();
        dragSourceId = null;
        dropBeforeId = null;
      });

      tbody.appendChild(row);
    });

    const totalRow = document.createElement('tr');
    totalRow.className = 'total-row';
    totalRow.innerHTML = `<td></td><td>${totalPar}</td><td>${totalBlocks}</td><td>${Math.round(totalBlocks * scaleRatio)}</td><td></td>`;
    tbody.appendChild(totalRow);
  }

  const frontHoles = holes.filter((h) => h.id <= 9);
  const backHoles = holes.filter((h) => h.id > 9);
  if (frontHoles.length > 0) addSection('ALLER', frontHoles);
  if (backHoles.length > 0) addSection('RETOUR', backHoles);

  // Dragover : positionne l'indicateur de drop
  tbody.addEventListener('dragover', (e) => {
    e.preventDefault();
    e.dataTransfer.dropEffect = 'move';

    // Ignorer si on survole l'indicateur lui-même
    if (_dropIndicator.contains(e.target)) return;

    const targetRow = e.target.closest('tr[data-hole-id]');
    if (!targetRow) return; // section-header ou total-row : on garde la position actuelle

    const rect = targetRow.getBoundingClientRect();
    if (e.clientY < rect.top + rect.height / 2) {
      // Moitié haute → insérer avant targetRow
      dropBeforeId = parseInt(targetRow.dataset.holeId);
      tbody.insertBefore(_dropIndicator, targetRow);
    } else {
      // Moitié basse → insérer après targetRow
      const next = targetRow.nextElementSibling;
      if (next && next.dataset.holeId) {
        dropBeforeId = parseInt(next.dataset.holeId);
        tbody.insertBefore(_dropIndicator, next);
      } else {
        // Fin de section ou de liste
        dropBeforeId = null;
        targetRow.after(_dropIndicator);
      }
    }
  });

  // Retrait de l'indicateur si on sort du tbody
  tbody.addEventListener('dragleave', (e) => {
    if (!e.relatedTarget || !tbody.contains(e.relatedTarget)) {
      _dropIndicator.remove();
      dropBeforeId = null;
    }
  });

  tbody.addEventListener('drop', (e) => {
    e.preventDefault();
    _dropIndicator.remove();
    if (dragSourceId !== null) {
      reorderHole(dragSourceId, dropBeforeId);
    }
    dragSourceId = null;
    dropBeforeId = null;
  });

  table.appendChild(tbody);
  return table;
}

function setHighlight(id) {
  highlightedHole = id;
  document.querySelectorAll('.hole-table tr[data-hole-id]').forEach((r) => {
    r.classList.toggle('active', parseInt(r.dataset.holeId) === id);
  });
  draw();
}

// === Drawing ===
function draw() {
  if (!courseData) return;

  ctx.fillStyle = '#111a0c';
  ctx.fillRect(0, 0, canvas.width, canvas.height);

  if (show.pixel && mainPixelCache) {
    drawPixelMap();
    if (show.routing && courseData.routing) drawRouting(true);
  } else {
    if (show.terrain) drawTerrain();
    if (show.routing && courseData.routing) drawRouting(false);
  }
  drawFacilities();
  if (getEditorMode() === 'draw') drawPreview();
  if (show.grid) drawGrid();
}

function drawPixelMap() {
  const [dx, dy] = toCanvas(0, 0);
  ctx.imageSmoothingEnabled = false;
  ctx.drawImage(mainPixelCache, dx, dy, 350 * camZoom, 350 * camZoom);
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
  if (show.water && elev < baseElev - 2) {
    const depth = Math.max(0, Math.min(1, (baseElev - 2 - elev) / 6));
    return [
      Math.floor(30 - depth * 15),
      Math.floor(85 - depth * 30),
      Math.floor(130 + depth * 30),
    ];
  }
  if (elev < baseElev) {
    return [35, 95, 55];
  }
  const t = Math.min(1, Math.max(0, (elev - baseElev) / 18));
  if (t < 0.5) {
    const s = t * 2;
    return [Math.floor(30 + s * 25), Math.floor(70 + s * 50), Math.floor(28 + s * 15)];
  } else {
    const s = (t - 0.5) * 2;
    return [Math.floor(55 + s * 40), Math.floor(120 - s * 20), Math.floor(43 - s * 10)];
  }
}

function drawRouting(overlayOnly = false) {
  const routing = courseData.routing;
  const holes = routing.holes;
  const selId = getSelectedHoleId();

  holes.forEach((h) => {
    const hl = highlightedHole === h.id;
    const sel = selId === h.id;
    const alpha = highlightedHole !== null && !hl ? 0.25 : 1;
    ctx.globalAlpha = alpha;

    const isBack = h.id >= 10;
    const baseColor = isBack ? '#4a9ed6' : '#6aad45';
    const greenColor = isBack ? '#3db8de' : '#3dbd4e';
    const fw = h.fairway_width || 12;
    const gr = h.green.radius || 8;

    // Glow
    if (hl || sel) {
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

    const wps = h.waypoints;
    const [gx, gy] = toCanvas(h.green.x, h.green.y);

    if (!overlayOnly) {
      // Fairway
      ctx.strokeStyle = baseColor;
      ctx.lineWidth = fw * camZoom;
      ctx.lineCap = 'round';
      ctx.lineJoin = 'round';
      ctx.setLineDash([]);
      ctx.beginPath();
      const [sx, sy] = toCanvas(wps[0].x, wps[0].y);
      ctx.moveTo(sx, sy);
      for (let i = 1; i < wps.length; i++) {
        const [wx, wy] = toCanvas(wps[i].x, wps[i].y);
        ctx.lineTo(wx, wy);
      }
      ctx.stroke();

      // Features (bunkers, eau, arbres, cart path)
      drawHoleFeatures(h);

      // Green
      ctx.beginPath();
      ctx.arc(gx, gy, gr * camZoom, 0, Math.PI * 2);
      ctx.fillStyle = greenColor;
      ctx.fill();

      // Tee
      const [tx, ty] = toCanvas(h.tee.x, h.tee.y);
      ctx.fillStyle = C.tee;
      ctx.fillRect(tx - 4 * camZoom, ty - 2.5 * camZoom, 8 * camZoom, 5 * camZoom);
    }

    // Flag (toujours visible)
    const flagScale = Math.max(0.6, Math.min(2, camZoom / 1.5));
    ctx.fillStyle = C.flag;
    ctx.fillRect(gx - flagScale, gy - 7 * flagScale, 2 * flagScale, 9 * flagScale);
    ctx.beginPath();
    ctx.moveTo(gx + flagScale, gy - 7 * flagScale);
    ctx.lineTo(gx + 5 * flagScale, gy - 4.5 * flagScale);
    ctx.lineTo(gx + flagScale, gy - 2 * flagScale);
    ctx.fill();

    ctx.globalAlpha = 1;

    // Numeros
    if (show.nums) {
      const mi = Math.floor(wps.length / 2);
      const [nx, ny] = toCanvas(wps[mi].x, wps[mi].y);

      const numSize = Math.round(Math.max(8, Math.min(20, (hl || sel ? 12 : 10) * (camZoom / 1.5))));
      ctx.font = hl || sel ? `bold ${numSize}px Silkscreen` : `${numSize}px Silkscreen`;
      ctx.textAlign = 'center';
      ctx.textBaseline = 'middle';

      const numText = String(h.id);
      const tw = ctx.measureText(numText).width;
      const pillPad = Math.max(6, (10 * camZoom) / 2);
      const pillH = numSize + 5;
      const pillW = tw + pillPad * 2;
      const pillX = nx - pillW / 2;
      const pillY = ny - pillH / 2 - numSize;

      ctx.fillStyle = hl || sel
        ? (isBack ? 'rgba(74,158,214,0.9)' : 'rgba(78,207,95,0.9)')
        : 'rgba(0,0,0,0.7)';
      ctx.beginPath();
      ctx.roundRect(pillX, pillY, pillW, pillH, 3);
      ctx.fill();

      if (!hl && !sel) {
        ctx.strokeStyle = isBack ? 'rgba(74,158,214,0.3)' : 'rgba(78,207,95,0.2)';
        ctx.lineWidth = 0.5;
        ctx.stroke();
      }

      ctx.fillStyle = hl || sel ? '#000' : (isBack ? 'rgba(140,200,255,0.9)' : 'rgba(200,255,200,0.9)');
      ctx.fillText(numText, nx, pillY + pillH / 2);
    }

    // Poignées de waypoints si sélectionné
    if (sel) {
      ctx.globalAlpha = 1;
      wps.forEach((p, i) => {
        const [pcx, pcy] = toCanvas(p.x, p.y);
        const isFirst = i === 0;
        const isLast = i === wps.length - 1;
        const r = (isFirst || isLast) ? 6 : 4;
        ctx.beginPath();
        ctx.arc(pcx, pcy, r, 0, Math.PI * 2);
        ctx.fillStyle = isFirst ? C.tee : (isLast ? C.flag : 'rgba(255,200,50,0.9)');
        ctx.fill();
        ctx.strokeStyle = '#fff';
        ctx.lineWidth = 1.5;
        ctx.setLineDash([]);
        ctx.stroke();
      });
    }
  });
}

function drawHoleFeatures(h) {
  const features = h.features;
  if (!features) return;

  // Bunkers
  (features.bunkers || []).forEach((bunker) => {
    if (!bunker.points || bunker.points.length < 3) return;
    ctx.beginPath();
    const [fx, fy] = toCanvas(bunker.points[0].x, bunker.points[0].y);
    ctx.moveTo(fx, fy);
    for (let i = 1; i < bunker.points.length; i++) {
      const [px, py] = toCanvas(bunker.points[i].x, bunker.points[i].y);
      ctx.lineTo(px, py);
    }
    ctx.closePath();
    ctx.fillStyle = 'rgba(232, 214, 138, 0.75)';
    ctx.fill();
    ctx.strokeStyle = '#d4c170';
    ctx.lineWidth = 1;
    ctx.setLineDash([]);
    ctx.stroke();
  });

  // Water hazards
  (features.water_hazards || []).forEach((water) => {
    if (!water.points || water.points.length < 3) return;
    ctx.beginPath();
    const [fx, fy] = toCanvas(water.points[0].x, water.points[0].y);
    ctx.moveTo(fx, fy);
    for (let i = 1; i < water.points.length; i++) {
      const [px, py] = toCanvas(water.points[i].x, water.points[i].y);
      ctx.lineTo(px, py);
    }
    ctx.closePath();
    ctx.fillStyle = 'rgba(59, 139, 186, 0.70)';
    ctx.fill();
    ctx.strokeStyle = '#2a6f99';
    ctx.lineWidth = 1;
    ctx.setLineDash([]);
    ctx.stroke();
  });

  // Trees
  (features.trees || []).forEach((tree) => {
    const [tx, ty] = toCanvas(tree.x, tree.y);
    ctx.beginPath();
    ctx.arc(tx, ty, 3, 0, Math.PI * 2);
    ctx.fillStyle = '#2d5e1e';
    ctx.fill();
    ctx.strokeStyle = '#1f4a14';
    ctx.lineWidth = 0.5;
    ctx.setLineDash([]);
    ctx.stroke();
  });

  // Cart path
  if (features.cart_path && features.cart_path.points && features.cart_path.points.length >= 2) {
    const pts = features.cart_path.points;
    ctx.beginPath();
    const [sx, sy] = toCanvas(pts[0].x, pts[0].y);
    ctx.moveTo(sx, sy);
    for (let i = 1; i < pts.length; i++) {
      const [px, py] = toCanvas(pts[i].x, pts[i].y);
      ctx.lineTo(px, py);
    }
    ctx.strokeStyle = '#a08b6e';
    ctx.lineWidth = 1.5;
    ctx.setLineDash([4, 4]);
    ctx.stroke();
    ctx.setLineDash([]);
  }
}

function drawPreview() {
  // Freehand en cours ?
  if (isFreehandActive()) {
    const raw = getFreehandRaw();
    if (raw.length < 2) return;

    ctx.strokeStyle = 'rgba(255, 200, 50, 0.8)';
    ctx.lineWidth = 3;
    ctx.lineCap = 'round';
    ctx.lineJoin = 'round';
    ctx.beginPath();
    const [sx, sy] = toCanvas(raw[0].x, raw[0].y);
    ctx.moveTo(sx, sy);
    for (let i = 1; i < raw.length; i++) {
      const [wx, wy] = toCanvas(raw[i].x, raw[i].y);
      ctx.lineTo(wx, wy);
    }
    ctx.stroke();

    // Point de depart (tee)
    const [tx, ty] = toCanvas(raw[0].x, raw[0].y);
    ctx.beginPath();
    ctx.arc(tx, ty, 6, 0, Math.PI * 2);
    ctx.fillStyle = C.tee;
    ctx.fill();
    ctx.strokeStyle = '#fff';
    ctx.lineWidth = 1;
    ctx.stroke();

    // Info distance
    const blocks = polylineLength(raw);
    const par = autoPar(blocks);
    const scaleRatio = (courseData?.metadata?.config?.scale_ratio) || 3;
    const meters = Math.round(blocks * scaleRatio);
    const last = raw[raw.length - 1];
    const [lx, ly] = toCanvas(last.x, last.y);
    ctx.fillStyle = 'rgba(0,0,0,0.7)';
    ctx.font = '11px IBM Plex Mono';
    ctx.textAlign = 'left';
    ctx.fillText(`${blocks} blocs (${meters} m) — par ${par}`, lx + 15, ly - 5);
    return;
  }

  // Mode point par point
  const current = getCurrentHole();
  if (!current || current.points.length === 0) return;

  const pts = current.points;
  const mouse = getMouseWorld();

  // Segments existants
  ctx.strokeStyle = 'rgba(255, 200, 50, 0.8)';
  ctx.lineWidth = 3;
  ctx.lineCap = 'round';
  ctx.lineJoin = 'round';
  ctx.beginPath();
  const [sx, sy] = toCanvas(pts[0].x, pts[0].y);
  ctx.moveTo(sx, sy);
  for (let i = 1; i < pts.length; i++) {
    const [wx, wy] = toCanvas(pts[i].x, pts[i].y);
    ctx.lineTo(wx, wy);
  }
  ctx.stroke();

  // Ligne pointillee vers la souris
  const lastPt = pts[pts.length - 1];
  const [lx, ly] = toCanvas(lastPt.x, lastPt.y);
  const [mmx, mmy] = toCanvas(mouse.x, mouse.y);
  ctx.setLineDash([6, 4]);
  ctx.strokeStyle = 'rgba(255, 200, 50, 0.5)';
  ctx.lineWidth = 2;
  ctx.beginPath();
  ctx.moveTo(lx, ly);
  ctx.lineTo(mmx, mmy);
  ctx.stroke();
  ctx.setLineDash([]);

  // Points
  pts.forEach((p, i) => {
    const [px, py] = toCanvas(p.x, p.y);
    ctx.beginPath();
    ctx.arc(px, py, i === 0 ? 6 : 4, 0, Math.PI * 2);
    ctx.fillStyle = i === 0 ? C.tee : 'rgba(255, 200, 50, 0.9)';
    ctx.fill();
    ctx.strokeStyle = '#fff';
    ctx.lineWidth = 1;
    ctx.stroke();
  });

  // Info distance
  const previewPts = [...pts, { x: mouse.x, y: mouse.y }];
  const blocks = polylineLength(previewPts);
  const par = autoPar(blocks);
  const scaleRatio = (courseData?.metadata?.config?.scale_ratio) || 3;
  const meters = Math.round(blocks * scaleRatio);
  const [mx, my] = toCanvas(mouse.x, mouse.y);
  ctx.fillStyle = 'rgba(0,0,0,0.7)';
  ctx.font = '11px IBM Plex Mono';
  ctx.textAlign = 'left';
  ctx.fillText(`${blocks} blocs (${meters} m) — par ${par}`, mx + 15, my - 5);
}

function drawGrid() {
  if (!courseData) return;
  const w = courseData.metadata.config.width || 350;
  const h = courseData.metadata.config.height || 350;

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

  const labelSize = Math.max(6, Math.min(10, (7 * camZoom) / 1.5));
  ctx.fillStyle = 'rgba(255,255,255,0.12)';
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
  ctx.fillText('Entrer une seed et cliquer "Generer"', canvas.width / 2, canvas.height / 2 + 10);
}

// === Tooltip / Coords ===
function updateCoords(mx, my) {
  if (!courseData) return;
  const [bx, by] = toWorld(mx, my);
  const w = courseData.metadata.config.width || 350;
  const h = courseData.metadata.config.height || 350;
  const ix = Math.round(bx);
  const iy = Math.round(by);

  if (ix >= 0 && ix < w && iy >= 0 && iy < h) {
    const origin = getOrigin();
    const mcX = origin.x + ix;
    const mcZ = origin.z + iy;
    let info = `X=${mcX}  Z=${mcZ}`;
    if (heightmapPixels) {
      const idx = iy * w + ix;
      const val = heightmapPixels[idx];
      const elev = courseData.terrain.elevation;
      const realElev = elev.min_elevation + (val / 255) * (elev.max_elevation - elev.min_elevation);
      info += `  Y=${Math.round(realElev)}`;
    }
    if (origin.x === 0 && origin.z === 0) info += '  (origine non définie)';
    coordsEl.textContent = info;
  } else {
    coordsEl.textContent = 'Survole la carte pour voir les coordonnees';
  }
}

function updateTooltip(clientX, clientY, mx, my) {
  if (!courseData) {
    tooltip.style.display = 'none';
    return;
  }

  const [bx, by] = toWorld(mx, my);
  const w = courseData.metadata.config.width || 350;
  const h = courseData.metadata.config.height || 350;
  const ix = Math.round(bx);
  const iy = Math.round(by);

  updateCoords(mx, my);

  if (ix >= 0 && ix < w && iy >= 0 && iy < h && courseData.routing) {
    const hit = getHoleAt(bx, by);
    if (hit) {
      tooltip.style.display = 'block';
      tooltip.style.left = clientX + 12 + 'px';
      tooltip.style.top = clientY + 12 + 'px';
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
      if (pointToSegDist(bx, by, wps[i].x, wps[i].y, wps[i + 1].x, wps[i + 1].y) < (h.fairway_width || 12))
        return { hole: h, zone: 'fairway' };
    }
  }
  return null;
}

// === Facilities ===
const FACILITY_STYLE = {
  clubhouse:    { fill: 'rgba(139,115,85,0.4)',   stroke: '#c8a96e', label: 'CLUBHOUSE' },
  putting_green:{ fill: 'rgba(80,200,120,0.3)',   stroke: '#50c878', label: 'PUTTING GREEN' },
  practice:     { fill: 'rgba(245,166,35,0.25)',  stroke: '#f5a623', label: 'PRACTICE' },
};

function getFacilityStyle(type) {
  return FACILITY_STYLE[type] || { fill: 'rgba(200,200,200,0.2)', stroke: '#aaa', label: type.toUpperCase() };
}

function getHoleWaypointAt(wx, wy) {
  const selId = getSelectedHoleId();
  if (selId === null) return null;
  const h = getHoles().find(h => h.id === selId);
  if (!h) return null;
  const threshold = 8 / camZoom;
  for (let i = 0; i < h.points.length; i++) {
    const p = h.points[i];
    if (Math.abs(wx - p.x) <= threshold && Math.abs(wy - p.y) <= threshold) {
      return { holeId: h.id, idx: i };
    }
  }
  return null;
}

function getFacilityHandleAt(wx, wy) {
  const selId = getSelectedFacilityId();
  if (selId === null) return null;
  const f = getFacilities().find(f => f.id === selId);
  if (!f) return null;

  const threshold = 8 / camZoom; // 8px écran → blocs monde
  const handles = {
    tl: { hx: f.x,           hy: f.y           },
    t:  { hx: f.x + f.w / 2, hy: f.y           },
    tr: { hx: f.x + f.w,     hy: f.y           },
    l:  { hx: f.x,           hy: f.y + f.h / 2 },
    r:  { hx: f.x + f.w,     hy: f.y + f.h / 2 },
    bl: { hx: f.x,           hy: f.y + f.h     },
    b:  { hx: f.x + f.w / 2, hy: f.y + f.h     },
    br: { hx: f.x + f.w,     hy: f.y + f.h     },
  };

  for (const [name, pos] of Object.entries(handles)) {
    if (Math.abs(wx - pos.hx) <= threshold && Math.abs(wy - pos.hy) <= threshold) {
      return { id: f.id, handle: name };
    }
  }
  return null;
}

function drawFacilities() {
  const facilities = getFacilities();
  const selId = getSelectedFacilityId();

  facilities.forEach((f) => {
    const style = getFacilityStyle(f.type);
    const [cx, cy] = toCanvas(f.x, f.y);
    const cw = f.w * camZoom;
    const ch = f.h * camZoom;
    const isSel = f.id === selId;

    // Fond
    ctx.fillStyle = style.fill;
    ctx.fillRect(cx, cy, cw, ch);

    // Bordure
    ctx.strokeStyle = style.stroke;
    ctx.lineWidth = isSel ? 2 : 1;
    ctx.setLineDash([]);
    ctx.strokeRect(cx, cy, cw, ch);

    // Label centré
    const labelSize = Math.max(8, Math.min(12, camZoom * 5));
    ctx.font = `${Math.round(labelSize)}px IBM Plex Mono`;
    ctx.fillStyle = style.stroke;
    ctx.textAlign = 'center';
    ctx.textBaseline = 'middle';
    ctx.fillText(style.label, cx + cw / 2, cy + ch / 2);

    // Poignées de resize si sélectionnée
    if (isSel) {
      const handlePositions = [
        [f.x,           f.y          ],
        [f.x + f.w / 2, f.y          ],
        [f.x + f.w,     f.y          ],
        [f.x,           f.y + f.h / 2],
        [f.x + f.w,     f.y + f.h / 2],
        [f.x,           f.y + f.h    ],
        [f.x + f.w / 2, f.y + f.h    ],
        [f.x + f.w,     f.y + f.h    ],
      ];
      const hs = 5; // demi-taille en px
      handlePositions.forEach(([hx, hy]) => {
        const [hcx, hcy] = toCanvas(hx, hy);
        ctx.fillStyle = '#fff';
        ctx.fillRect(hcx - hs, hcy - hs, hs * 2, hs * 2);
        ctx.strokeStyle = style.stroke;
        ctx.lineWidth = 1;
        ctx.strokeRect(hcx - hs, hcy - hs, hs * 2, hs * 2);
      });
    }
  });

  // Preview pendant le drag
  const preview = getCurrentFacilityDraw();
  if (preview) {
    const style = getFacilityStyle(preview.type);
    let { x, y, w, h } = preview;
    // Afficher dans le bon sens même si drag inversé
    const px = w >= 0 ? x : x + w;
    const py = h >= 0 ? y : y + h;
    const pw = Math.abs(w);
    const ph = Math.abs(h);
    const [cx, cy] = toCanvas(px, py);
    const cw = pw * camZoom;
    const ch = ph * camZoom;

    ctx.fillStyle = style.fill;
    ctx.fillRect(cx, cy, cw, ch);
    ctx.strokeStyle = style.stroke;
    ctx.lineWidth = 1.5;
    ctx.setLineDash([4, 3]);
    ctx.strokeRect(cx, cy, cw, ch);
    ctx.setLineDash([]);
  }
}

// === Export JSON ===
function exportJSON() {
  if (!courseData) return;

  let terrainData = null;
  if (heightmapPixels) {
    let binary = '';
    for (let i = 0; i < heightmapPixels.length; i++) {
      binary += String.fromCharCode(heightmapPixels[i]);
    }
    terrainData = {
      width: courseData.terrain.width,
      height: courseData.terrain.height,
      elevation: {
        encoding: 'base64_uint8',
        data: btoa(binary),
        min_elevation: courseData.terrain.elevation.min_elevation,
        max_elevation: courseData.terrain.elevation.max_elevation,
      },
    };
  }

  const courseName = document.getElementById('course-name-input').value.trim();
  if (courseName) courseData.metadata.name = courseName;
  const exportOrigin = getOrigin();
  courseData.metadata.origin = (exportOrigin.x !== 0 || exportOrigin.z !== 0) ? exportOrigin : null;

  let blockMapData = null;
  if (courseBlockMap) {
    let binary = '';
    for (let i = 0; i < courseBlockMap.length; i++) binary += String.fromCharCode(courseBlockMap[i]);
    blockMapData = {
      width: 350,
      height: 350,
      zones: ZONE_INDEX,
      encoding: 'base64_uint8',
      data: btoa(binary),
    };
  }

  const data = {
    metadata: {
      version: '3.0',
      name: courseData.metadata.name || null,
      seed: courseData.metadata.seed,
      origin: courseData.metadata.origin || null,
      config: courseData.metadata.config,
    },
    terrain: terrainData,
    routing: courseData.routing || null,
    block_map: blockMapData,
  };

  const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  const nameSlug = courseData.metadata.name
    ? courseData.metadata.name.toLowerCase().replace(/[^a-z0-9]+/g, '_').replace(/^_|_$/g, '')
    : null;
  a.download = nameSlug ? `${nameSlug}.json` : `golfgen_${courseData.metadata.seed}.json`;
  a.click();
  URL.revokeObjectURL(url);
}

// === Autosave ===
function autoSave() {
  if (!courseData) return;
  const state = {
    name: courseData.metadata.name || null,
    seed: courseData.metadata.seed,
    origin: courseData.metadata.origin || null,
    holes: getHoles(),
    facilities: getFacilities(),
  };
  localStorage.setItem('golfgen_autosave', JSON.stringify(state));
}

// === Toggle ===
function toggle(key) {
  show[key] = !show[key];
  if (key === 'water' && heightmapPixels) buildTerrainCache();
  const btn = document.getElementById('btn-' + key);
  if (btn) btn.classList.toggle('active');
  draw();
}

// === Course Block Map ===
function buildCourseBlockMap() {
  const holes = getHoles();
  if (holes.length === 0) { courseBlockMap = null; mainPixelCache = null; return; }
  const bboxes = holes.map(getHoleBBox);
  const data = new Uint8Array(350 * 350);

  const offscreen = document.createElement('canvas');
  offscreen.width = 350;
  offscreen.height = 350;
  const octx = offscreen.getContext('2d');
  const imageData = octx.createImageData(350, 350);
  const imgData = imageData.data;

  for (let by = 0; by < 350; by++) {
    for (let bx = 0; bx < 350; bx++) {
      const zone = getGlobalZoneAt(bx, by, holes, bboxes);
      data[by * 350 + bx] = ZONE_TO_IDX[zone] ?? 0;
      const hex = zone === 'rough'
        ? ((bx + by) % 2 === 0 ? HE_ZONE_COLORS.rough : HE_ZONE_COLORS.rough_alt)
        : (HE_ZONE_COLORS[zone] || HE_ZONE_COLORS.rough);
      const [r, g, b] = hexToRgb(hex);
      const idx = (by * 350 + bx) * 4;
      imgData[idx] = r; imgData[idx + 1] = g; imgData[idx + 2] = b; imgData[idx + 3] = 255;
    }
  }
  octx.putImageData(imageData, 0, 0);
  courseBlockMap = data;
  mainPixelCache = offscreen;
  if (show.pixel) draw();
}

function scheduleBlockMapRebuild() {
  if (_blockMapTimer) clearTimeout(_blockMapTimer);
  _blockMapTimer = setTimeout(() => {
    buildCourseBlockMap();
    _blockMapTimer = null;
  }, 300);
}

// === Hole Editor ===
let heCanvas = null;
let heCtx = null;
let heCamZoom = 3.0;
let heCamPanX = 0;
let heCamPanY = 0;
let heIsPanning = false;
let hePanStartX = 0, hePanStartY = 0;
let hePanStartCamX = 0, hePanStartCamY = 0;
let heDrawMouseStartX = 0, heDrawMouseStartY = 0;
let heMouseWorldX = 0, heMouseWorldY = 0;
let heBlockCache = null;
let heBlockCacheBounds = null;

// Course block map (350×350, 1 octet par bloc)
let courseBlockMap = null;
let mainPixelCache = null; // canvas coloré pour la vue pixel
let _blockMapTimer = null;
const ZONE_INDEX = ['rough', 'semi_rough', 'fairway', 'cart_path', 'tree', 'water', 'bunker', 'green_fringe', 'green', 'tee'];
const ZONE_TO_IDX = Object.fromEntries(ZONE_INDEX.map((z, i) => [z, i]));

function toHeCanvas(wx, wy) {
  return [wx * heCamZoom + heCamPanX, wy * heCamZoom + heCamPanY];
}

function fromHeCanvas(sx, sy) {
  return [(sx - heCamPanX) / heCamZoom, (sy - heCamPanY) / heCamZoom];
}

function openHoleEditor(holeId) {
  if (!holeId || !courseData) return;
  const alreadyOpen = document.getElementById('hole-editor-overlay').style.display !== 'none';
  openHoleEditorState(holeId);

  const overlay = document.getElementById('hole-editor-overlay');
  overlay.style.display = 'flex';

  heCanvas = document.getElementById('hole-canvas');
  heCtx = heCanvas.getContext('2d');
  heResizeCanvas();
  heFitCamera(holeId);

  if (!alreadyOpen) {
    heCanvas.addEventListener('wheel', heOnWheel, { passive: false });
    heCanvas.addEventListener('mousedown', heOnMouseDown);
    heCanvas.addEventListener('dblclick', heOnDblClick);
    heCanvas.addEventListener('contextmenu', hePreventContext);
    window.addEventListener('mousemove', heOnMouseMoveGlobal);
    window.addEventListener('mouseup', heOnMouseUpGlobal);
    window.addEventListener('resize', heOnResize);
  }

  heBlockCache = null;
  heBlockCacheBounds = null;
  updateHeTitle();
  updateHeSidebar();
  updateHeButtons();
  drawHoleEditor();
}

function heResizeCanvas() {
  if (!heCanvas) return;
  const wrapper = heCanvas.parentElement;
  const rect = wrapper.getBoundingClientRect();
  heCanvas.width = Math.floor(rect.width);
  heCanvas.height = Math.floor(rect.height);
}

function heOnResize() {
  heResizeCanvas();
  drawHoleEditor();
}

function heFitCamera(holeId) {
  const h = getHoles().find(h => h.id === holeId);
  if (!h || !heCanvas) return;
  const pts = h.points;
  let minX = pts[0].x, maxX = pts[0].x;
  let minY = pts[0].y, maxY = pts[0].y;
  pts.forEach(p => {
    minX = Math.min(minX, p.x); maxX = Math.max(maxX, p.x);
    minY = Math.min(minY, p.y); maxY = Math.max(maxY, p.y);
  });
  const pad = 50;
  minX -= pad; maxX += pad;
  minY -= pad; maxY += pad;
  const zoomX = heCanvas.width / (maxX - minX);
  const zoomY = heCanvas.height / (maxY - minY);
  heCamZoom = Math.max(0.5, Math.min(20, Math.min(zoomX, zoomY)));
  const cx = (minX + maxX) / 2;
  const cy = (minY + maxY) / 2;
  heCamPanX = heCanvas.width / 2 - cx * heCamZoom;
  heCamPanY = heCanvas.height / 2 - cy * heCamZoom;
}

function hePreventContext(e) { e.preventDefault(); }

function closeHoleEditor() {
  closeHoleEditorState();
  if (heCanvas) {
    heCanvas.removeEventListener('wheel', heOnWheel);
    heCanvas.removeEventListener('mousedown', heOnMouseDown);
    heCanvas.removeEventListener('dblclick', heOnDblClick);
    heCanvas.removeEventListener('contextmenu', hePreventContext);
  }
  window.removeEventListener('mousemove', heOnMouseMoveGlobal);
  window.removeEventListener('mouseup', heOnMouseUpGlobal);
  window.removeEventListener('resize', heOnResize);
  heCanvas = null;
  heCtx = null;
  document.getElementById('hole-editor-overlay').style.display = 'none';
  draw();
}

function holeEditorNav(dir) {
  const holes = getHoles();
  const idx = holes.findIndex(h => h.id === getHeEditingHoleId());
  if (idx === -1) return;
  const next = holes[idx + dir];
  if (next) openHoleEditor(next.id);
}

function updateHeTitle() {
  const id = getHeEditingHoleId();
  const h = getHoles().find(h => h.id === id);
  if (!h) return;
  document.getElementById('he-title').textContent = `Trou ${h.id} — Par ${h.par}`;
  const holes = getHoles();
  const idx = holes.findIndex(h => h.id === id);
  document.getElementById('he-btn-prev').disabled = idx === 0;
  document.getElementById('he-btn-next').disabled = idx === holes.length - 1;
}

function updateHeSidebar() {
  const id = getHeEditingHoleId();
  const h = getHoles().find(h => h.id === id);
  const container = document.getElementById('he-feature-list');
  if (!h || !container) return;
  const features = h.features || { bunkers: [], water_hazards: [], trees: [], cart_path: null };
  let html = '';

  const sections = [
    { label: 'Bunkers',    type: 'bunker',       items: features.bunkers || [] },
    { label: "Zones d'eau", type: 'water_hazard', items: features.water_hazards || [] },
    { label: 'Arbres',     type: 'tree',          items: features.trees || [] },
  ];

  sections.forEach(({ label, type, items }) => {
    if (items.length === 0) return;
    html += `<div class="he-feature-section">`;
    html += `<div class="he-feature-section-title">${label}</div>`;
    items.forEach(item => {
      html += `<div class="he-feature-item"><span>#${item.id}</span>`;
      html += `<button onclick="heDeleteFeature(${id},'${type}',${item.id})">×</button></div>`;
    });
    html += `</div>`;
  });

  if (features.cart_path && features.cart_path.points && features.cart_path.points.length >= 2) {
    html += `<div class="he-feature-section">`;
    html += `<div class="he-feature-section-title">Cart Path</div>`;
    html += `<div class="he-feature-item"><span>${features.cart_path.points.length} pts</span>`;
    html += `<button onclick="heDeleteFeature(${id},'cart_path',0)">×</button></div>`;
    html += `</div>`;
  }

  if (!html) {
    html = '<div style="font-size:9px;color:rgba(255,255,255,0.25);padding:4px 0">Aucune feature</div>';
  }
  container.innerHTML = html;
}

function heDeleteFeature(holeId, type, featureId) {
  deleteHoleFeature(holeId, type, featureId);
  heBlockCache = null;
  updateHeSidebar();
  drawHoleEditor();
}

// --- Hole Editor Rendering ---
const HE_ZONE_COLORS = {
  tee:          '#4ecf5f',
  green:        '#3dbd4e',
  green_fringe: '#4db84a',
  fairway:      '#6aad45',
  semi_rough:   '#4a8632',
  rough:        '#2e5420',
  rough_alt:    '#263f1a',
  bunker:       '#e8d68a',
  water:        '#3b8bba',
  tree:         '#2d5e1e',
  cart_path:    '#a08b6e',
};

function hexToRgb(hex) {
  return [parseInt(hex.slice(1, 3), 16), parseInt(hex.slice(3, 5), 16), parseInt(hex.slice(5, 7), 16)];
}

function buildHoleBlockCache(h) {
  const wps = h.points;
  const fw = h.fairwayWidth || 12;
  const gr = h.greenRadius || 8;
  const pad = Math.max(fw / 2 + 5, gr) + 8;

  let minX = wps[0].x, maxX = wps[0].x;
  let minY = wps[0].y, maxY = wps[0].y;
  wps.forEach(p => {
    minX = Math.min(minX, p.x); maxX = Math.max(maxX, p.x);
    minY = Math.min(minY, p.y); maxY = Math.max(maxY, p.y);
  });

  const features = h.features || {};
  [...(features.bunkers || []), ...(features.water_hazards || [])].forEach(f => {
    (f.points || []).forEach(p => {
      minX = Math.min(minX, p.x); maxX = Math.max(maxX, p.x);
      minY = Math.min(minY, p.y); maxY = Math.max(maxY, p.y);
    });
  });
  (features.trees || []).forEach(t => {
    minX = Math.min(minX, t.x - 2); maxX = Math.max(maxX, t.x + 2);
    minY = Math.min(minY, t.y - 2); maxY = Math.max(maxY, t.y + 2);
  });
  if (features.cart_path && features.cart_path.points) {
    features.cart_path.points.forEach(p => {
      minX = Math.min(minX, p.x); maxX = Math.max(maxX, p.x);
      minY = Math.min(minY, p.y); maxY = Math.max(maxY, p.y);
    });
  }

  minX = Math.max(0, Math.floor(minX - pad));
  minY = Math.max(0, Math.floor(minY - pad));
  maxX = Math.min(349, Math.ceil(maxX + pad));
  maxY = Math.min(349, Math.ceil(maxY + pad));

  const W = maxX - minX + 1;
  const H = maxY - minY + 1;
  const offscreen = document.createElement('canvas');
  offscreen.width = W;
  offscreen.height = H;
  const octx = offscreen.getContext('2d');
  const imageData = octx.createImageData(W, H);
  const data = imageData.data;

  for (let j = 0; j < H; j++) {
    for (let i = 0; i < W; i++) {
      const bx = minX + i;
      const by = minY + j;
      const zone = getHoleZoneAt(h, bx, by);
      const hex = zone === 'rough'
        ? ((bx + by) % 2 === 0 ? HE_ZONE_COLORS.rough : HE_ZONE_COLORS.rough_alt)
        : (HE_ZONE_COLORS[zone] || HE_ZONE_COLORS.rough);
      const [r, g, b] = hexToRgb(hex);
      const idx = (j * W + i) * 4;
      data[idx] = r; data[idx + 1] = g; data[idx + 2] = b; data[idx + 3] = 255;
    }
  }
  octx.putImageData(imageData, 0, 0);
  heBlockCache = offscreen;
  heBlockCacheBounds = { minX, minY, maxX, maxY };
}

function drawHoleEditor() {
  if (!heCtx || !heCanvas) return;
  const W = heCanvas.width, H = heCanvas.height;
  heCtx.fillStyle = '#111a0c';
  heCtx.fillRect(0, 0, W, H);

  const holeId = getHeEditingHoleId();
  const holes = getHoles();
  const cur = holes.find(h => h.id === holeId);

  if (cur) {
    if (!heBlockCache) buildHoleBlockCache(cur);

    if (heBlockCache && heBlockCacheBounds) {
      const b = heBlockCacheBounds;
      const [dx, dy] = toHeCanvas(b.minX, b.minY);
      const dw = (b.maxX - b.minX + 1) * heCamZoom;
      const dh = (b.maxY - b.minY + 1) * heCamZoom;
      heCtx.imageSmoothingEnabled = false;
      heCtx.drawImage(heBlockCache, dx, dy, dw, dh);
    }

    // Trous adjacents (vecteur, alpha réduit)
    heCtx.globalAlpha = 0.2;
    holes.forEach(h => { if (h.id !== holeId) heDrawAdjacentHoleVec(h); });
    heCtx.globalAlpha = 1;

    // Overlay waypoints + flag
    heDrawWaypointOverlay(cur);
    heDrawFlagPin(cur);
  }

  heDrawCurrentPoly();
  if (isHeFreehandActive()) heDrawFreehandHE();
  heDrawGrid();
}

function heDrawAdjacentHoleVec(h) {
  const wps = h.points;
  heCtx.strokeStyle = '#6aad45';
  heCtx.lineWidth = (h.fairwayWidth || 12) * heCamZoom;
  heCtx.lineCap = 'round';
  heCtx.lineJoin = 'round';
  heCtx.setLineDash([]);
  heCtx.beginPath();
  const [sx, sy] = toHeCanvas(wps[0].x, wps[0].y);
  heCtx.moveTo(sx, sy);
  for (let i = 1; i < wps.length; i++) {
    const [wx, wy] = toHeCanvas(wps[i].x, wps[i].y);
    heCtx.lineTo(wx, wy);
  }
  heCtx.stroke();
}

function heDrawWaypointOverlay(h) {
  const wps = h.points;
  // Ligne pointillée reliant les waypoints
  heCtx.strokeStyle = 'rgba(255,255,255,0.35)';
  heCtx.lineWidth = 1.5;
  heCtx.setLineDash([4, 4]);
  heCtx.lineCap = 'round';
  heCtx.beginPath();
  const [sx, sy] = toHeCanvas(wps[0].x, wps[0].y);
  heCtx.moveTo(sx, sy);
  for (let i = 1; i < wps.length; i++) {
    const [wx, wy] = toHeCanvas(wps[i].x, wps[i].y);
    heCtx.lineTo(wx, wy);
  }
  heCtx.stroke();
  heCtx.setLineDash([]);
  // Handles
  wps.forEach((p, i) => {
    const [cx, cy] = toHeCanvas(p.x, p.y);
    const isFirst = i === 0, isLast = i === wps.length - 1;
    heCtx.beginPath();
    heCtx.arc(cx, cy, (isFirst || isLast) ? 5 : 3, 0, Math.PI * 2);
    heCtx.fillStyle = isFirst ? '#4ecf5f' : isLast ? '#ff3b3b' : 'rgba(255,200,50,0.7)';
    heCtx.fill();
    heCtx.strokeStyle = 'rgba(255,255,255,0.6)';
    heCtx.lineWidth = 1;
    heCtx.stroke();
  });
}

function heDrawFlagPin(h) {
  const wps = h.points;
  const green = wps[wps.length - 1];
  const [gx, gy] = toHeCanvas(green.x, green.y);
  const isBack = h.id >= 10;
  const ns = Math.round(Math.max(8, Math.min(20, 10 * (heCamZoom / 1.5))));
  heCtx.font = `bold ${ns}px Silkscreen`;
  heCtx.textAlign = 'center';
  heCtx.textBaseline = 'middle';
  const txt = String(h.id);
  const tw = heCtx.measureText(txt).width;
  const pp = Math.max(6, (10 * heCamZoom) / 2);
  const ph = ns + 5, pw = tw + pp * 2;
  const labX = gx - pw / 2, labY = gy - ph - ns;
  heCtx.fillStyle = isBack ? 'rgba(74,158,214,0.9)' : 'rgba(78,207,95,0.9)';
  heCtx.beginPath();
  heCtx.roundRect(labX, labY, pw, ph, 3);
  heCtx.fill();
  heCtx.fillStyle = '#000';
  heCtx.fillText(txt, gx, labY + ph / 2);
  // Drapeau
  const fs = Math.max(0.6, Math.min(2, heCamZoom / 1.5));
  heCtx.fillStyle = '#ff3b3b';
  heCtx.fillRect(gx - fs, gy - 7 * fs, 2 * fs, 9 * fs);
  heCtx.beginPath();
  heCtx.moveTo(gx + fs, gy - 7 * fs);
  heCtx.lineTo(gx + 5 * fs, gy - 4.5 * fs);
  heCtx.lineTo(gx + fs, gy - 2 * fs);
  heCtx.fill();
}

function heFeatureColor(type) {
  switch (type) {
    case 'bunker':       return '#e8d68a';
    case 'water_hazard': return '#3b8bba';
    case 'tree':         return '#3d7a2a';
    case 'cart_path':    return '#a08b6e';
    default:             return '#ffffff';
  }
}

function heFeatureColorAlpha(type, a) {
  switch (type) {
    case 'bunker':       return `rgba(232,214,138,${a})`;
    case 'water_hazard': return `rgba(59,139,186,${a})`;
    case 'tree':         return `rgba(61,122,42,${a})`;
    case 'cart_path':    return `rgba(160,139,110,${a})`;
    default:             return `rgba(255,255,255,${a})`;
  }
}

function heDrawCurrentPoly() {
  const poly = getHeCurrentPoly();
  if (!poly || poly.points.length === 0) return;
  const pts = poly.points;
  const ft = getHeFeatureType();
  const color = heFeatureColor(ft);

  heCtx.strokeStyle = color;
  heCtx.lineWidth = 2;
  heCtx.lineCap = 'round';
  heCtx.lineJoin = 'round';
  heCtx.setLineDash([]);
  heCtx.beginPath();
  const [sx, sy] = toHeCanvas(pts[0].x, pts[0].y);
  heCtx.moveTo(sx, sy);
  for (let i = 1; i < pts.length; i++) {
    const [px, py] = toHeCanvas(pts[i].x, pts[i].y);
    heCtx.lineTo(px, py);
  }
  heCtx.stroke();

  // Ligne pointillée vers la souris
  const lastPt = pts[pts.length - 1];
  const [lx, ly] = toHeCanvas(lastPt.x, lastPt.y);
  const [mmx, mmy] = toHeCanvas(heMouseWorldX, heMouseWorldY);
  heCtx.setLineDash([5, 4]);
  heCtx.strokeStyle = heFeatureColorAlpha(ft, 0.45);
  heCtx.lineWidth = 1.5;
  heCtx.beginPath();
  heCtx.moveTo(lx, ly);
  heCtx.lineTo(mmx, mmy);
  heCtx.stroke();
  heCtx.setLineDash([]);

  pts.forEach((p, i) => {
    const [px, py] = toHeCanvas(p.x, p.y);
    heCtx.beginPath();
    heCtx.arc(px, py, i === 0 ? 5 : 3, 0, Math.PI * 2);
    heCtx.fillStyle = color;
    heCtx.fill();
    heCtx.strokeStyle = '#fff';
    heCtx.lineWidth = 1;
    heCtx.setLineDash([]);
    heCtx.stroke();
  });
}

function heDrawFreehandHE() {
  const raw = getHeFreehandRaw();
  if (raw.length < 2) return;
  const ft = getHeFeatureType();
  heCtx.strokeStyle = heFeatureColor(ft);
  heCtx.lineWidth = 2;
  heCtx.lineCap = 'round';
  heCtx.lineJoin = 'round';
  heCtx.setLineDash([]);
  heCtx.beginPath();
  const [sx, sy] = toHeCanvas(raw[0].x, raw[0].y);
  heCtx.moveTo(sx, sy);
  for (let i = 1; i < raw.length; i++) {
    const [wx, wy] = toHeCanvas(raw[i].x, raw[i].y);
    heCtx.lineTo(wx, wy);
  }
  heCtx.stroke();
}

function heDrawGrid() {
  const w = 350, h = 350;
  const steps = [10, 25, 50, 100, 200, 500];
  let step = 50;
  for (const s of steps) { if (s * heCamZoom >= 50) { step = s; break; } }

  heCtx.strokeStyle = 'rgba(255,255,255,0.05)';
  heCtx.lineWidth = 0.5;
  heCtx.setLineDash([]);
  const [gx0, gy0] = toHeCanvas(0, 0);
  const [gx1, gy1] = toHeCanvas(w, h);

  for (let x = 0; x <= w; x += step) {
    const [cx] = toHeCanvas(x, 0);
    if (cx < -1 || cx > heCanvas.width + 1) continue;
    heCtx.beginPath(); heCtx.moveTo(cx, gy0); heCtx.lineTo(cx, gy1); heCtx.stroke();
  }
  for (let y = 0; y <= h; y += step) {
    const [, cy] = toHeCanvas(0, y);
    if (cy < -1 || cy > heCanvas.height + 1) continue;
    heCtx.beginPath(); heCtx.moveTo(gx0, cy); heCtx.lineTo(gx1, cy); heCtx.stroke();
  }
}

// --- Hole Editor Events ---
function heOnWheel(e) {
  e.preventDefault();
  const factor = e.deltaY > 0 ? 0.9 : 1.111;
  const rect = heCanvas.getBoundingClientRect();
  const sx = e.clientX - rect.left;
  const sy = e.clientY - rect.top;
  const [wx, wy] = fromHeCanvas(sx, sy);
  heCamZoom = Math.max(0.5, Math.min(20, heCamZoom * factor));
  heCamPanX = sx - wx * heCamZoom;
  heCamPanY = sy - wy * heCamZoom;
  drawHoleEditor();
}

function heOnMouseDown(e) {
  const rect = heCanvas.getBoundingClientRect();
  const mx = e.clientX - rect.left;
  const my = e.clientY - rect.top;

  if (e.button === 2 || e.button === 1) {
    heIsPanning = true;
    hePanStartX = e.clientX; hePanStartY = e.clientY;
    hePanStartCamX = heCamPanX; hePanStartCamY = heCamPanY;
    heCanvas.style.cursor = 'grabbing';
    return;
  }

  if (e.button === 0) {
    const [wx, wy] = fromHeCanvas(mx, my);
    const ft = getHeFeatureType();

    if (!ft) {
      heIsPanning = true;
      hePanStartX = e.clientX; hePanStartY = e.clientY;
      hePanStartCamX = heCamPanX; hePanStartCamY = heCamPanY;
      heCanvas.style.cursor = 'grabbing';
      return;
    }

    if (ft === 'tree') {
      heHandleClick(wx, wy);
      updateHeSidebar();
      drawHoleEditor();
      return;
    }

    // Polygone / polyline : freehand ou point-par-point
    if (heFreehandStart(wx, wy)) {
      heDrawMouseStartX = e.clientX;
      heDrawMouseStartY = e.clientY;
    } else {
      // Poly déjà en cours : ajouter un point directement
      heHandleClick(wx, wy);
      drawHoleEditor();
    }
  }
}

function heOnMouseMoveGlobal(e) {
  if (!heCanvas) return;
  const rect = heCanvas.getBoundingClientRect();
  const mx = e.clientX - rect.left;
  const my = e.clientY - rect.top;
  const [wx, wy] = fromHeCanvas(mx, my);
  heMouseWorldX = wx;
  heMouseWorldY = wy;

  if (heIsPanning) {
    heCamPanX = hePanStartCamX + (e.clientX - hePanStartX);
    heCamPanY = hePanStartCamY + (e.clientY - hePanStartY);
    drawHoleEditor();
    return;
  }

  if (isHeFreehandActive()) {
    heFreehandMove(wx, wy);
    drawHoleEditor();
    return;
  }

  // Preview ligne pointillée vers souris
  if (getHeFeatureType() && getHeCurrentPoly()) {
    drawHoleEditor();
  }
}

function heOnMouseUpGlobal(e) {
  if (!heCanvas) return;

  if (e.button !== 0) {
    if (heIsPanning) {
      heIsPanning = false;
      heCanvas.style.cursor = getHeFeatureType() ? 'crosshair' : 'grab';
    }
    return;
  }

  if (heIsPanning) {
    heIsPanning = false;
    heCanvas.style.cursor = getHeFeatureType() ? 'crosshair' : 'grab';
    return;
  }

  if (isHeFreehandActive()) {
    heFreehandEnd();
    updateHeSidebar();
    drawHoleEditor();
    heCanvas.style.cursor = 'crosshair';
  }
}

function heOnDblClick(e) {
  const ft = getHeFeatureType();
  if (ft && ft !== 'tree') {
    heHandleDblClick();
    updateHeSidebar();
    drawHoleEditor();
  }
}

// === Keyboard ===
function onKeyDown(e) {
  // Ne pas interférer avec les inputs texte
  if (e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA') return;

  if (e.key === 'Escape') {
    e.preventDefault();

    // Hole Editor ouvert
    if (getHeEditingHoleId() !== null) {
      // 1. Polygone de feature en cours → annuler le tracé
      if (getHeCurrentPoly() && getHeCurrentPoly().points.length > 0) {
        heUndoPoint();
        // Vider tout le polygone en cours
        while (getHeCurrentPoly() && getHeCurrentPoly().points.length > 0) heUndoPoint();
        drawHoleEditor();
        return;
      }
      // 2. Mode de dessin actif → revenir en vue seule
      if (getHeFeatureType() !== null) {
        setHeFeatureType(null);
        return;
      }
      // 3. Fermer l'overlay
      closeHoleEditor();
      return;
    }

    // Canvas principal
    // 4. Dessin en cours (freehand ou point-par-point) → annuler
    if (getEditorMode() === 'draw') {
      toggleDrawMode();
      return;
    }
    // 5. Trou sélectionné → désélectionner
    if (getSelectedHoleId() !== null) {
      selectHole(null);
      return;
    }
  }
}

// === Start ===
init();
