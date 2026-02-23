/**
 * Editeur de trous — dessin interactif sur le canvas.
 * Supporte deux modes de dessin :
 *   - Freehand : maintenir clic gauche et tracer une courbe
 *   - Point par point : clic simple pour poser des waypoints, double-clic pour finir
 */

// === State ===
let editorMode = 'view'; // 'view' | 'draw'
let currentHole = null; // { points: [{x,y}] }
let editorHoles = [];
let selectedHoleId = null;
let nextId = 1;
let editingHoleOriginalId = null; // ID du trou en cours d'édition (pour réinsérer à la bonne place)

// Facilities state
let editorFacilities = [];
let facilityMode = null; // null | 'clubhouse' | 'putting_green' | 'practice'
let currentFacilityDraw = null; // { type, x, y, w, h } — preview pendant drag
let selectedFacilityId = null;
let nextFacilityId = 1;

// Freehand state
let isFreehand = false;       // true si on est en train de tracer en freehand
let freehandRaw = [];         // points bruts pendant le trace
const FREEHAND_MIN_DIST = 1;  // distance min entre echantillons (blocs monde)
const FREEHAND_EPSILON = 3;   // tolerance RDP pour simplification

// Mouse position en coords monde (pour preview)
let mouseWorldX = 0;
let mouseWorldY = 0;

// Callbacks
let _onChangeCallback = null;
let _drawCallback = null;

function editorSetOnChange(fn) { _onChangeCallback = fn; }
function editorSetDrawCallback(fn) { _drawCallback = fn; }
function getEditorMode() { return editorMode; }
function getHoles() { return editorHoles; }
function getSelectedHoleId() { return selectedHoleId; }
function getCurrentHole() { return currentHole; }
function getMouseWorld() { return { x: mouseWorldX, y: mouseWorldY }; }
function setMouseWorld(x, y) { mouseWorldX = x; mouseWorldY = y; }
function isFreehandActive() { return isFreehand; }
function getFreehandRaw() { return freehandRaw; }
function getFacilityMode() { return facilityMode; }
function getFacilities() { return editorFacilities; }
function getSelectedFacilityId() { return selectedFacilityId; }
function getCurrentFacilityDraw() { return currentFacilityDraw; }
function isFacilityDragActive() { return currentFacilityDraw !== null; }

// === Mode toggle ===
function toggleDrawMode() {
  if (editorMode === 'draw') {
    if (currentHole) {
      currentHole = null;
      updateDrawInfo();
    }
    isFreehand = false;
    freehandRaw = [];
    editingHoleOriginalId = null;
    editorMode = 'view';
  } else {
    editorMode = 'draw';
    selectedHoleId = null;
  }
  updateEditorButtons();
  if (_drawCallback) _drawCallback();
}

// === Facility mode ===
function setFacilityMode(type) {
  facilityMode = facilityMode === type ? null : type;
  currentFacilityDraw = null;
  selectedFacilityId = null;
  updateFacilityButtons();
  if (_drawCallback) _drawCallback();
}

function facilityDragStart(wx, wy) {
  if (!facilityMode) return;
  currentFacilityDraw = { type: facilityMode, x: wx, y: wy, w: 0, h: 0 };
  if (_drawCallback) _drawCallback();
}

function facilityDragMove(wx, wy) {
  if (!currentFacilityDraw) return;
  currentFacilityDraw.w = wx - currentFacilityDraw.x;
  currentFacilityDraw.h = wy - currentFacilityDraw.y;
  if (_drawCallback) _drawCallback();
}

function facilityDragEnd() {
  if (!currentFacilityDraw) return;
  let { type, x, y, w, h } = currentFacilityDraw;
  currentFacilityDraw = null;

  // Normaliser si w/h négatifs (drag dans le sens inverse)
  if (w < 0) { x += w; w = -w; }
  if (h < 0) { y += h; h = -h; }

  // Rejeter si trop petit
  if (w < 5 || h < 5) {
    if (_drawCallback) _drawCallback();
    return;
  }

  const facility = {
    id: nextFacilityId++,
    type,
    x: Math.round(x * 10) / 10,
    y: Math.round(y * 10) / 10,
    w: Math.round(w * 10) / 10,
    h: Math.round(h * 10) / 10,
  };

  editorFacilities.push(facility);
  selectedFacilityId = facility.id;

  if (_onChangeCallback) _onChangeCallback();
  if (_drawCallback) _drawCallback();
}

function selectFacility(id) {
  selectedFacilityId = id === selectedFacilityId ? null : id;
  if (_drawCallback) _drawCallback();
}

function updateFacility(id, x, y, w, h) {
  const f = editorFacilities.find(f => f.id === id);
  if (!f) return;
  f.x = Math.round(x * 10) / 10;
  f.y = Math.round(y * 10) / 10;
  f.w = Math.round(w * 10) / 10;
  f.h = Math.round(h * 10) / 10;
  if (_onChangeCallback) _onChangeCallback();
  if (_drawCallback) _drawCallback();
}

function deleteLastFacility() {
  if (editorFacilities.length === 0) return;
  editorFacilities.pop();
  editorFacilities.forEach((f, i) => (f.id = i + 1));
  nextFacilityId = editorFacilities.length + 1;
  selectedFacilityId = null;
  if (_onChangeCallback) _onChangeCallback();
  if (_drawCallback) _drawCallback();
}

function importFacilities(arr) {
  if (!arr || !arr.length) return;
  editorFacilities = arr.map((f, i) => ({
    id: i + 1,
    type: f.type,
    x: f.x,
    y: f.y,
    w: f.width,
    h: f.height,
  }));
  nextFacilityId = editorFacilities.length + 1;
}

function getFacilityAt(wx, wy) {
  // Cherche la dernière facility qui contient le point (ordre z inverse)
  for (let i = editorFacilities.length - 1; i >= 0; i--) {
    const f = editorFacilities[i];
    if (wx >= f.x && wx <= f.x + f.w && wy >= f.y && wy <= f.y + f.h) {
      return f;
    }
  }
  return null;
}

// === Freehand drawing ===
function freehandStart(worldX, worldY) {
  if (editorMode !== 'draw') return false;
  // Ne pas demarrer le freehand si on a deja un trou en cours (mode point par point)
  if (currentHole && currentHole.points.length > 0) return false;

  isFreehand = true;
  freehandRaw = [{ x: worldX, y: worldY }];
  if (_drawCallback) _drawCallback();
  return true;
}

function freehandMove(worldX, worldY) {
  if (!isFreehand) return;
  const last = freehandRaw[freehandRaw.length - 1];
  const dx = worldX - last.x;
  const dy = worldY - last.y;
  if (dx * dx + dy * dy >= FREEHAND_MIN_DIST * FREEHAND_MIN_DIST) {
    freehandRaw.push({ x: worldX, y: worldY });
    if (_drawCallback) _drawCallback();
  }
}

function freehandEnd() {
  if (!isFreehand) return;
  isFreehand = false;

  if (freehandRaw.length < 3) {
    // Trop court — traiter comme un simple clic (mode point par point)
    if (freehandRaw.length >= 1) {
      handleCanvasClick(freehandRaw[0].x, freehandRaw[0].y);
    }
    freehandRaw = [];
    return;
  }

  // Simplifier avec RDP
  const simplified = simplifyRDP(freehandRaw, FREEHAND_EPSILON);
  freehandRaw = [];

  if (simplified.length < 2) return;

  // Arrondir les coords
  const pts = simplified.map(p => ({
    x: Math.round(p.x * 10) / 10,
    y: Math.round(p.y * 10) / 10,
  }));

  const blocks = polylineLength(pts);
  if (blocks < 5) return; // Vraiment trop court

  const par = autoPar(blocks);
  const hole = {
    id: nextId++,
    points: pts,
    par: par,
    fairwayWidth: autoFairwayWidth(par),
    greenRadius: 8,
    blocks: blocks,
    direction: directionLabel(pts[0], pts[pts.length - 1]),
    features: emptyFeatures(),
  };

  _commitHole(hole);
  currentHole = null;

  updateDrawInfo();
  updateEditorButtons();
  if (_onChangeCallback) _onChangeCallback();
  if (_drawCallback) _drawCallback();
}

// Insère le trou à sa position d'origine (si édition) ou à la fin (si nouveau)
function _commitHole(hole) {
  if (editingHoleOriginalId !== null) {
    const idx = Math.min(editingHoleOriginalId - 1, editorHoles.length);
    editorHoles.splice(idx, 0, hole);
    editorHoles.forEach((h, i) => (h.id = i + 1));
    nextId = editorHoles.length + 1;
    editingHoleOriginalId = null;
  } else {
    editorHoles.push(hole);
  }
}

// === Features helpers ===
function emptyFeatures() {
  return { bunkers: [], water_hazards: [], trees: [], cart_path: null };
}

// === Point-by-point drawing ===
function handleCanvasClick(worldX, worldY) {
  if (editorMode !== 'draw') return false;

  if (!currentHole) {
    currentHole = { points: [] };
  }

  currentHole.points.push({ x: Math.round(worldX * 10) / 10, y: Math.round(worldY * 10) / 10 });
  updateDrawInfo();
  updateEditorButtons();
  if (_drawCallback) _drawCallback();
  return true;
}

function handleCanvasDblClick() {
  if (editorMode !== 'draw' || !currentHole) return false;
  finishHole();
  return true;
}

function finishHole() {
  if (!currentHole || currentHole.points.length < 2) return;

  const pts = currentHole.points;
  const blocks = polylineLength(pts);
  const par = autoPar(blocks);

  const hole = {
    id: nextId++,
    points: pts,
    par: par,
    fairwayWidth: autoFairwayWidth(par),
    greenRadius: 8,
    blocks: blocks,
    direction: directionLabel(pts[0], pts[pts.length - 1]),
    features: emptyFeatures(),
  };

  _commitHole(hole);
  currentHole = null;

  updateDrawInfo();
  updateEditorButtons();
  if (_onChangeCallback) _onChangeCallback();
  if (_drawCallback) _drawCallback();
}

function undoPoint() {
  if (currentHole && currentHole.points.length > 0) {
    currentHole.points.pop();
    if (currentHole.points.length === 0) {
      currentHole = null;
    }
    updateDrawInfo();
    updateEditorButtons();
    if (_drawCallback) _drawCallback();
  }
}

function deleteSelected() {
  if (selectedHoleId === null) return;
  editorHoles = editorHoles.filter((h) => h.id !== selectedHoleId);
  editorHoles.forEach((h, i) => (h.id = i + 1));
  nextId = editorHoles.length + 1;
  selectedHoleId = null;
  updateEditorButtons();
  if (_onChangeCallback) _onChangeCallback();
  if (_drawCallback) _drawCallback();
}

function deleteLastHole() {
  if (editorHoles.length === 0) return;
  editorHoles.pop();
  editorHoles.forEach((h, i) => (h.id = i + 1));
  nextId = editorHoles.length + 1;
  selectedHoleId = null;
  updateEditorButtons();
  if (_onChangeCallback) _onChangeCallback();
  if (_drawCallback) _drawCallback();
}

function resetAllHoles() {
  editorHoles = [];
  currentHole = null;
  selectedHoleId = null;
  nextId = 1;
  isFreehand = false;
  freehandRaw = [];
  editorFacilities = [];
  facilityMode = null;
  currentFacilityDraw = null;
  selectedFacilityId = null;
  nextFacilityId = 1;
  localStorage.removeItem('golfgen_autosave');
  updateDrawInfo();
  updateEditorButtons();
  updateFacilityButtons();
  if (_onChangeCallback) _onChangeCallback();
  if (_drawCallback) _drawCallback();
}

function selectHole(id) {
  selectedHoleId = id === selectedHoleId ? null : id;
  updateEditorButtons();
  updateHoleSelectedPanel();
  if (_drawCallback) _drawCallback();
}

// === Edition d'un trou existant ===
function editSelectedHole() {
  if (selectedHoleId === null) return;
  const h = editorHoles.find(h => h.id === selectedHoleId);
  if (!h) return;

  // Mémoriser l'ID d'origine pour réinsérer au bon endroit après édition
  editingHoleOriginalId = h.id;

  // Retirer le trou de la liste et renuméroter
  editorHoles = editorHoles.filter(hole => hole.id !== selectedHoleId);
  editorHoles.forEach((hole, i) => (hole.id = i + 1));
  nextId = editorHoles.length + 1;
  selectedHoleId = null;

  // Reprendre ses points en mode draw
  currentHole = { points: h.points.map(p => ({ x: p.x, y: p.y })) };
  editorMode = 'draw';

  updateDrawInfo();
  updateEditorButtons();
  updateHoleSelectedPanel();
  if (_onChangeCallback) _onChangeCallback();
  if (_drawCallback) _drawCallback();
}

function reorderHole(fromId, beforeId) {
  const fromIdx = editorHoles.findIndex(h => h.id === fromId);
  if (fromIdx === -1) return;
  const [hole] = editorHoles.splice(fromIdx, 1);
  if (beforeId === null) {
    editorHoles.push(hole);
  } else {
    const toIdx = editorHoles.findIndex(h => h.id === beforeId);
    editorHoles.splice(toIdx === -1 ? editorHoles.length : toIdx, 0, hole);
  }
  selectedHoleId = null;
  editorHoles.forEach((h, i) => (h.id = i + 1));
  nextId = editorHoles.length + 1;
  if (_onChangeCallback) _onChangeCallback();
  if (_drawCallback) _drawCallback();
}

function removeLastWaypoint() {
  if (selectedHoleId === null) return;
  const h = editorHoles.find(h => h.id === selectedHoleId);
  if (!h || h.points.length <= 2) return; // minimum 2 points pour un trou valide

  h.points.pop();
  const blocks = polylineLength(h.points);
  h.blocks = blocks;
  h.par = autoPar(blocks);
  h.fairwayWidth = autoFairwayWidth(h.par);
  h.direction = directionLabel(h.points[0], h.points[h.points.length - 1]);

  updateHoleSelectedPanel();
  if (_onChangeCallback) _onChangeCallback();
  if (_drawCallback) _drawCallback();
}

function moveWaypoint(holeId, idx, wx, wy) {
  const h = editorHoles.find(h => h.id === holeId);
  if (!h) return;
  h.points[idx] = { x: Math.round(wx * 10) / 10, y: Math.round(wy * 10) / 10 };
  const blocks = polylineLength(h.points);
  h.blocks = blocks;
  h.par = autoPar(blocks);
  h.fairwayWidth = autoFairwayWidth(h.par);
  h.direction = directionLabel(h.points[0], h.points[h.points.length - 1]);
  if (_drawCallback) _drawCallback();
}

function finalizeWaypointMove() {
  if (_onChangeCallback) _onChangeCallback();
}

// === Import depuis JSON routing ===
function importHoles(routingHoles) {
  editorHoles = routingHoles.map((h) => ({
    id: h.id,
    points: h.waypoints.map((w) => ({ x: w.x, y: w.y })),
    par: h.par,
    fairwayWidth: h.fairway_width || 12,
    greenRadius: (h.green && h.green.radius) || 8,
    blocks: h.blocks || polylineLength(h.waypoints),
    direction: h.direction || '',
    features: h.features || emptyFeatures(),
  }));
  nextId = editorHoles.length + 1;
  if (_onChangeCallback) _onChangeCallback();
}

// === Sync vers courseData.routing ===
function buildRoutingData() {
  return {
    holes: editorHoles.map((h) => ({
      id: h.id,
      par: h.par,
      blocks: h.blocks,
      direction: h.direction,
      fairway_width: h.fairwayWidth,
      tee: { x: h.points[0].x, y: h.points[0].y },
      green: {
        x: h.points[h.points.length - 1].x,
        y: h.points[h.points.length - 1].y,
        radius: h.greenRadius,
      },
      waypoints: h.points.map((p) => ({ x: p.x, y: p.y })),
      features: h.features || emptyFeatures(),
    })),
    facilities: editorFacilities.map((f) => ({
      id: f.id,
      type: f.type,
      x: f.x,
      y: f.y,
      width: f.w,
      height: f.h,
    })),
  };
}

// === UI updates ===
function updateDrawInfo() {
  const infoEl = document.getElementById('draw-info');
  if (!currentHole || currentHole.points.length === 0) {
    infoEl.style.display = 'none';
    return;
  }
  infoEl.style.display = 'block';
  const pts = currentHole.points;
  const blocks = polylineLength(pts);
  const par = pts.length >= 2 ? autoPar(blocks) : '?';
  const scale = (typeof courseData !== 'undefined' && courseData?.metadata?.config?.scale_ratio) || 3;
  const meters = Math.round(blocks * scale);
  document.getElementById('draw-points').textContent = `${pts.length} pts`;
  document.getElementById('draw-dist').textContent = `${blocks} blocs`;
  document.getElementById('draw-meters').textContent = `${meters} m`;
  document.getElementById('draw-par').textContent = `par ${par}`;
}

function updateEditorButtons() {
  const btnDraw = document.getElementById('btn-draw');
  const btnFinish = document.getElementById('btn-finish');
  const btnUndo = document.getElementById('btn-undo');

  btnDraw.classList.toggle('active', editorMode === 'draw');
  btnDraw.textContent = editorMode === 'draw' ? 'Annuler dessin' : 'Dessiner';
  btnFinish.disabled = !currentHole || currentHole.points.length < 2;
  btnUndo.disabled = !currentHole || currentHole.points.length === 0;

  updateHoleSelectedPanel();
}

function updateHoleSelectedPanel() {
  const panel = document.getElementById('hole-selected-controls');
  if (!panel) return;

  const hasSel = selectedHoleId !== null && editorMode === 'view';
  panel.style.display = hasSel ? '' : 'none';

  if (!hasSel) return;
  const h = editorHoles.find(h => h.id === selectedHoleId);
  if (!h) return;

  document.getElementById('sel-hole-id').textContent = h.id;
  document.getElementById('sel-hole-par').textContent = `par ${h.par}`;
  document.getElementById('sel-hole-dist').textContent = `${h.blocks} blocs`;
}

function updateFacilityButtons() {
  const types = ['clubhouse', 'putting_green', 'practice'];
  types.forEach((type) => {
    const btn = document.getElementById('btn-facility-' + type);
    if (!btn) return;
    btn.classList.toggle('active', facilityMode === type);
  });
}

// === Hole Editor State ===
let heEditingHoleId = null;
let heFeatureType = null; // 'bunker'|'water_hazard'|'tree'|'cart_path'|null
let heCurrentPoly = null; // { points: [] } — polygone en cours de dessin
let heIsFreehand = false;
let heFreehandRaw = [];
const HE_FREEHAND_MIN_DIST = 1;
const HE_FREEHAND_EPSILON = 3;
let _heDrawCallback = null;

function heSetDrawCallback(fn) { _heDrawCallback = fn; }
function getHeEditingHoleId() { return heEditingHoleId; }
function getHeFeatureType() { return heFeatureType; }
function getHeCurrentPoly() { return heCurrentPoly; }
function isHeFreehandActive() { return heIsFreehand; }
function getHeFreehandRaw() { return heFreehandRaw; }

function openHoleEditorState(holeId) {
  heEditingHoleId = holeId;
  heFeatureType = null;
  heCurrentPoly = null;
  heIsFreehand = false;
  heFreehandRaw = [];
}

function closeHoleEditorState() {
  heEditingHoleId = null;
  heFeatureType = null;
  heCurrentPoly = null;
  heIsFreehand = false;
  heFreehandRaw = [];
}

function setHeFeatureType(type) {
  heCurrentPoly = null;
  heIsFreehand = false;
  heFreehandRaw = [];
  heFeatureType = (heFeatureType === type || type === null) ? null : type;
  updateHeButtons();
  if (_heDrawCallback) _heDrawCallback();
}

function heHandleClick(wx, wy) {
  if (!heFeatureType) return;
  const h = editorHoles.find(h => h.id === heEditingHoleId);
  if (!h) return;

  if (heFeatureType === 'tree') {
    const id = h.features.trees.length > 0
      ? Math.max(...h.features.trees.map(t => t.id)) + 1 : 1;
    h.features.trees.push({ id, x: Math.round(wx * 10) / 10, y: Math.round(wy * 10) / 10 });
    if (_onChangeCallback) _onChangeCallback();
    return;
  }

  if (!heCurrentPoly) heCurrentPoly = { points: [] };
  heCurrentPoly.points.push({ x: Math.round(wx * 10) / 10, y: Math.round(wy * 10) / 10 });
}

function heHandleDblClick() {
  heFinishPoly();
}

function heFinishPoly() {
  const h = editorHoles.find(h => h.id === heEditingHoleId);
  if (!h || !heCurrentPoly) return;
  const pts = heCurrentPoly.points;
  const isPath = heFeatureType === 'cart_path';
  const minPts = isPath ? 2 : 3;
  if (pts.length < minPts) { heCurrentPoly = null; return; }

  if (heFeatureType === 'bunker') {
    const id = h.features.bunkers.length > 0
      ? Math.max(...h.features.bunkers.map(b => b.id)) + 1 : 1;
    const smooth = pts.length >= 3 ? smoothChaikin(pts, 3, true) : pts;
    h.features.bunkers.push({ id, points: smooth });
  } else if (heFeatureType === 'water_hazard') {
    const id = h.features.water_hazards.length > 0
      ? Math.max(...h.features.water_hazards.map(w => w.id)) + 1 : 1;
    const smooth = pts.length >= 3 ? smoothChaikin(pts, 3, true) : pts;
    h.features.water_hazards.push({ id, points: smooth });
  } else if (heFeatureType === 'cart_path') {
    const smooth = pts.length >= 2 ? smoothChaikin(pts, 2, false) : pts;
    h.features.cart_path = { points: smooth };
  }
  heCurrentPoly = null;
  if (_onChangeCallback) _onChangeCallback();
}

function heFreehandStart(wx, wy) {
  if (!heFeatureType || heFeatureType === 'tree') return false;
  if (heCurrentPoly && heCurrentPoly.points.length > 0) return false;
  heIsFreehand = true;
  heFreehandRaw = [{ x: wx, y: wy }];
  return true;
}

function heFreehandMove(wx, wy) {
  if (!heIsFreehand) return;
  const last = heFreehandRaw[heFreehandRaw.length - 1];
  const dx = wx - last.x;
  const dy = wy - last.y;
  if (dx * dx + dy * dy >= HE_FREEHAND_MIN_DIST * HE_FREEHAND_MIN_DIST) {
    heFreehandRaw.push({ x: wx, y: wy });
  }
}

function heFreehandEnd() {
  if (!heIsFreehand) return;
  heIsFreehand = false;
  if (heFreehandRaw.length < 3) {
    if (heFreehandRaw.length >= 1) heHandleClick(heFreehandRaw[0].x, heFreehandRaw[0].y);
    heFreehandRaw = [];
    return;
  }
  const simplified = simplifyRDP(heFreehandRaw, HE_FREEHAND_EPSILON);
  heFreehandRaw = [];
  if (simplified.length < 2) return;
  const pts = simplified.map(p => ({
    x: Math.round(p.x * 10) / 10,
    y: Math.round(p.y * 10) / 10,
  }));
  heCurrentPoly = { points: pts };
  heFinishPoly();
}

function heUndoPoint() {
  if (heCurrentPoly && heCurrentPoly.points.length > 0) {
    heCurrentPoly.points.pop();
    if (heCurrentPoly.points.length === 0) heCurrentPoly = null;
    if (_heDrawCallback) _heDrawCallback();
  }
}

function deleteHoleFeature(holeId, type, featureId) {
  const h = editorHoles.find(h => h.id === holeId);
  if (!h) return;
  if (type === 'bunker') {
    h.features.bunkers = h.features.bunkers.filter(b => b.id !== featureId);
    h.features.bunkers.forEach((b, i) => (b.id = i + 1));
  } else if (type === 'water_hazard') {
    h.features.water_hazards = h.features.water_hazards.filter(w => w.id !== featureId);
    h.features.water_hazards.forEach((w, i) => (w.id = i + 1));
  } else if (type === 'tree') {
    h.features.trees = h.features.trees.filter(t => t.id !== featureId);
    h.features.trees.forEach((t, i) => (t.id = i + 1));
  } else if (type === 'cart_path') {
    h.features.cart_path = null;
  }
  if (_onChangeCallback) _onChangeCallback();
}

function updateHeButtons() {
  ['bunker', 'water_hazard', 'tree', 'cart_path'].forEach(type => {
    const btn = document.getElementById('he-btn-' + type);
    if (!btn) return;
    btn.classList.toggle('active', heFeatureType === type);
  });
  const btnNone = document.getElementById('he-btn-none');
  if (btnNone) btnNone.classList.toggle('active', heFeatureType === null);
}

/**
 * Détermine la zone d'un bloc (bx, by) pour le rendu bloc-par-bloc.
 * Priorité : tee → green → bunker → water → tree → cart_path → fairway → semi_rough → rough
 */
function getHoleZoneAt(h, bx, by) {
  const wps = h.points;
  const tee = wps[0];
  const green = wps[wps.length - 1];
  const gr = h.greenRadius || 8;
  const fw = h.fairwayWidth || 12;
  const features = h.features || {};

  // Tee box (rectangle ~8×5 blocs)
  if (Math.abs(bx - tee.x) <= 4 && Math.abs(by - tee.y) <= 2.5) return 'tee';

  // Green + fringe
  const dgr = Math.hypot(bx - green.x, by - green.y);
  if (dgr <= gr) return 'green';
  if (dgr <= gr + 3) return 'green_fringe';

  // Bunkers
  for (const bunker of (features.bunkers || [])) {
    if (bunker.points && bunker.points.length >= 3 && pointInPolygon(bx, by, bunker.points)) return 'bunker';
  }
  // Eau
  for (const water of (features.water_hazards || [])) {
    if (water.points && water.points.length >= 3 && pointInPolygon(bx, by, water.points)) return 'water';
  }
  // Arbres (cercle r=2)
  for (const tree of (features.trees || [])) {
    if (Math.hypot(bx - tree.x, by - tree.y) <= 2) return 'tree';
  }
  // Cart path (polyline, épaisseur 1.5 blocs de chaque côté)
  if (features.cart_path && features.cart_path.points && features.cart_path.points.length >= 2) {
    const cp = features.cart_path.points;
    for (let i = 1; i < cp.length; i++) {
      if (pointToSegDist(bx, by, cp[i - 1].x, cp[i - 1].y, cp[i].x, cp[i].y) <= 1.5) return 'cart_path';
    }
  }

  // Distance à la polyligne des waypoints
  let minDist = Infinity;
  for (let i = 1; i < wps.length; i++) {
    const d = pointToSegDist(bx, by, wps[i - 1].x, wps[i - 1].y, wps[i].x, wps[i].y);
    if (d < minDist) minDist = d;
  }
  if (minDist <= fw / 2) return 'fairway';
  if (minDist <= fw / 2 + 5) return 'semi_rough';
  return 'rough';
}

// Priorité des zones pour la fusion globale (plus grand = prioritaire)
const ZONE_PRIORITY = {
  rough: 0, semi_rough: 1, fairway: 2, cart_path: 3,
  tree: 4, water: 5, bunker: 6, green_fringe: 7, green: 8, tee: 9,
};

/** Bounding box d'un trou (avec padding semi_rough + features) pour le culling. */
function getHoleBBox(h) {
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
    minX = Math.min(minX, t.x); maxX = Math.max(maxX, t.x);
    minY = Math.min(minY, t.y); maxY = Math.max(maxY, t.y);
  });
  return { minX: minX - pad, minY: minY - pad, maxX: maxX + pad, maxY: maxY + pad };
}

/**
 * Zone globale d'un bloc en tenant compte de tous les trous (priorité max).
 * @param {number} bx @param {number} by
 * @param {Array} holes @param {Array} bboxes - résultat de holes.map(getHoleBBox)
 */
function getGlobalZoneAt(bx, by, holes, bboxes) {
  let bestPriority = -1;
  let bestZone = 'rough';
  for (let i = 0; i < holes.length; i++) {
    const bb = bboxes[i];
    if (bx < bb.minX || bx > bb.maxX || by < bb.minY || by > bb.maxY) continue;
    const zone = getHoleZoneAt(holes[i], bx, by);
    const priority = ZONE_PRIORITY[zone] ?? 0;
    if (priority > bestPriority) {
      bestPriority = priority;
      bestZone = zone;
      if (priority === 9) break; // tee = max possible
    }
  }
  return bestZone;
}
