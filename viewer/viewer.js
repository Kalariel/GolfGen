/**
 * Viewer de parcours de golf — consomme le JSON produit par le pipeline Python.
 * Affiche les couches : terrain, routing, obstacles, végétation, features.
 */

// === State ===
let courseData = null;
let heightmapPixels = null; // Uint8Array décodée

const SCALE = 1.15;
const PAD = 35;

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

// === Init ===
const canvas = document.getElementById('map');
const ctx = canvas.getContext('2d');
const tooltip = document.getElementById('tooltip');
const coordsEl = document.getElementById('coords');

function init() {
  // Bouton de chargement
  const fileInput = document.getElementById('file-input');
  fileInput.addEventListener('change', handleFileLoad);

  // Essayer de charger automatiquement depuis ../output/course.json
  tryAutoLoad();
}

async function tryAutoLoad() {
  try {
    const resp = await fetch('../output/course.json');
    if (resp.ok) {
      const json = await resp.json();
      loadCourseData(json);
      document.getElementById('filename').textContent = 'course.json (auto)';
    }
  } catch (e) {
    // Pas de fichier auto — l'utilisateur devra charger manuellement
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

  // Décoder la heightmap si présente
  if (json.terrain && json.terrain.elevation) {
    const elev = json.terrain.elevation;
    const b64 = elev.data;
    const binary = atob(b64);
    heightmapPixels = new Uint8Array(binary.length);
    for (let i = 0; i < binary.length; i++) {
      heightmapPixels[i] = binary.charCodeAt(i);
    }
  }

  // Mettre à jour le header
  updateHeader();

  // Activer/désactiver les boutons de couche
  updateLayerButtons();

  // Remplir la sidebar
  updateSidebar();

  // Configurer le canvas et dessiner
  setupCanvas();
  draw();
}

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
    const totalBlocks = holes.reduce((s, h) => s + h.blocks, 0);
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
    tableContainer.innerHTML = '<div class="info-box">Pas de routing — exécuter le pipeline avec --stage routing</div>';
    return;
  }

  const holes = courseData.routing.holes;

  // Table Aller (1-9)
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

  // Total
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

// === Canvas ===
function setupCanvas() {
  const w = courseData.metadata.config.width || 600;
  const h = courseData.metadata.config.height || 600;
  canvas.width = w * SCALE + PAD * 2;
  canvas.height = h * SCALE + PAD * 2;
}

function toCanvas(cx, cy) {
  return [PAD + cx * SCALE, PAD + cy * SCALE];
}

// === Dessin ===
function draw() {
  if (!courseData) return;

  const w = courseData.metadata.config.width || 600;
  const h = courseData.metadata.config.height || 600;

  ctx.fillStyle = '#1a2410';
  ctx.fillRect(0, 0, canvas.width, canvas.height);

  if (show.terrain) drawTerrain(w, h);
  if (show.paving && courseData.paving) drawPaving(w, h);
  if (show.hazards && courseData.hazards) drawHazards();
  if (show.vegetation && courseData.vegetation) drawVegetation();
  if (show.routing && courseData.routing) drawRouting();
  if (show.features && courseData.features) drawFeatures();
  if (show.grid) drawGrid(w, h);
}

function drawTerrain(w, h) {
  if (!heightmapPixels) return;

  const elev = courseData.terrain.elevation;
  const elevMin = elev.min_elevation;
  const elevMax = elev.max_elevation;
  const elevRange = elevMax - elevMin;
  const baseElev = courseData.metadata.config.base_elevation || 64;

  // Dessiner pixel par pixel avec un dégradé de verts
  // Optimisation : utiliser ImageData
  const imgW = Math.ceil(w * SCALE);
  const imgH = Math.ceil(h * SCALE);
  const imageData = ctx.createImageData(imgW, imgH);
  const pixels = imageData.data;

  for (let py = 0; py < imgH; py++) {
    const by = Math.floor(py / SCALE);
    if (by >= h) continue;
    for (let px = 0; px < imgW; px++) {
      const bx = Math.floor(px / SCALE);
      if (bx >= w) continue;

      const idx = by * w + bx;
      const val = heightmapPixels[idx]; // 0-255
      const realElev = elevMin + (val / 255) * elevRange;

      // Couleur basée sur l'élévation
      const [r, g, b] = elevationToColor(realElev, baseElev);

      const pidx = (py * imgW + px) * 4;
      pixels[pidx] = r;
      pixels[pidx + 1] = g;
      pixels[pidx + 2] = b;
      pixels[pidx + 3] = 255;
    }
  }

  ctx.putImageData(imageData, PAD, PAD);
}

function elevationToColor(elev, baseElev) {
  // Sous l'eau (< baseElev - 2)
  if (elev < baseElev - 2) {
    const depth = Math.max(0, Math.min(1, (baseElev - 2 - elev) / 6));
    return [
      Math.floor(30 - depth * 15),
      Math.floor(85 - depth * 30),
      Math.floor(130 + depth * 30)
    ];
  }

  // Plaine basse (baseElev - 2 à baseElev)
  if (elev < baseElev) {
    return [35, 95, 55];
  }

  // Terrain normal (baseElev à baseElev + 10)
  const t = Math.min(1, Math.max(0, (elev - baseElev) / 18));

  // Dégradé : vert foncé (bas) → vert clair (moyen) → brun-vert (haut)
  if (t < 0.5) {
    const s = t * 2; // 0-1 dans la première moitié
    return [
      Math.floor(30 + s * 25),
      Math.floor(70 + s * 50),
      Math.floor(28 + s * 15)
    ];
  } else {
    const s = (t - 0.5) * 2; // 0-1 dans la seconde moitié
    return [
      Math.floor(55 + s * 40),
      Math.floor(120 - s * 20),
      Math.floor(43 - s * 10)
    ];
  }
}

function drawPaving(w, h) {
  const pav = courseData.paving;
  const ts = pav.tile_size;
  const gw = pav.grid_width;
  const gh = pav.grid_height;

  // Decoder owner base64 int16
  const b64 = pav.owner.data;
  const binary = atob(b64);
  const bytes = new Uint8Array(binary.length);
  for (let i = 0; i < binary.length; i++) bytes[i] = binary.charCodeAt(i);
  const owner = new Int16Array(bytes.buffer);

  const nCells = pav.cells.length;

  // Dessiner chaque tile avec couleur HSL
  for (let ty = 0; ty < gh; ty++) {
    for (let tx = 0; tx < gw; tx++) {
      const cellId = owner[ty * gw + tx];
      if (cellId < 0) continue;

      const hue = (cellId * 20) % 360;
      const bx = tx * ts;
      const by = ty * ts;
      const [cx, cy] = toCanvas(bx, by);
      const sw = ts * SCALE;
      const sh = ts * SCALE;

      ctx.fillStyle = `hsla(${hue}, 60%, 50%, 0.4)`;
      ctx.fillRect(cx, cy, sw, sh);

      // Contour : trait sombre aux frontieres (4 cotes + detection diagonale)
      ctx.strokeStyle = 'rgba(0, 0, 0, 0.5)';
      ctx.lineWidth = 1;

      const right = tx < gw - 1 ? owner[ty * gw + tx + 1] : -2;
      const bottom = ty < gh - 1 ? owner[(ty + 1) * gw + tx] : -2;

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

  // Labels des seeds
  pav.cells.forEach(cell => {
    const bx = cell.seed_tx * ts + ts / 2;
    const by = cell.seed_ty * ts + ts / 2;
    const [cx, cy] = toCanvas(bx, by);

    ctx.font = 'bold 9px Silkscreen';
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
  // Clubhouse : nouvelle section top-level ou fallback routing.clubhouse
  const ch = courseData.clubhouse || routing.clubhouse;

  // Fairways, greens, tees
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
      ctx.lineWidth = fw * SCALE + 10;
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
    ctx.lineWidth = fw * SCALE;
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
    ctx.arc(gx, gy, gr * SCALE, 0, Math.PI * 2);
    ctx.fillStyle = greenColor;
    ctx.fill();

    // Flag
    ctx.fillStyle = C.flag;
    ctx.fillRect(gx - 1, gy - 7, 2, 9);
    ctx.beginPath();
    ctx.moveTo(gx + 1, gy - 7);
    ctx.lineTo(gx + 5, gy - 4.5);
    ctx.lineTo(gx + 1, gy - 2);
    ctx.fill();

    // Tee
    const [tx, ty] = toCanvas(h.tee.x, h.tee.y);
    ctx.fillStyle = C.tee;
    ctx.fillRect(tx - 4 * SCALE, ty - 2.5 * SCALE, 8 * SCALE, 5 * SCALE);

    ctx.globalAlpha = 1;

    // Numéros
    if (show.nums) {
      const mi = Math.floor(wps.length / 2);
      const [nx, ny] = toCanvas(wps[mi].x, wps[mi].y);

      ctx.font = hl ? 'bold 12px Silkscreen' : '10px Silkscreen';
      ctx.textAlign = 'center';
      ctx.textBaseline = 'middle';

      const numText = String(h.id);
      const tw = ctx.measureText(numText).width;
      const pillW = tw + 10, pillH = 15;
      const pillX = nx - pillW / 2, pillY = ny - pillH / 2 - 13;

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
      ctx.fillText(numText, nx, ny - 13);
    }
  });

  // Clubhouse
  if (ch) {
    const [chx, chy] = toCanvas(ch.x, ch.y);
    const chw = ch.width * SCALE;
    const chh = ch.height * SCALE;

    ctx.fillStyle = 'rgba(0,0,0,0.35)';
    ctx.fillRect(chx + 3, chy + 3, chw, chh);

    ctx.fillStyle = '#7a6b50';
    ctx.fillRect(chx, chy, chw, chh);
    ctx.fillStyle = '#a08b6e';
    ctx.fillRect(chx - 3, chy - 4, chw + 6, 8);

    ctx.strokeStyle = 'rgba(255,255,255,0.3)';
    ctx.lineWidth = 1.5;
    ctx.strokeRect(chx, chy, chw, chh);

    ctx.fillStyle = '#fff';
    ctx.font = 'bold 9px Silkscreen';
    ctx.textAlign = 'center';
    ctx.fillText('CLUB', chx + chw / 2, chy + chh / 2 - 2);
    ctx.fillText('HOUSE', chx + chw / 2, chy + chh / 2 + 9);

    // Practice range
    if (ch.practice_range) {
      const pr = ch.practice_range;
      const [px, py] = toCanvas(pr.x, pr.y);
      const pw = pr.width * SCALE;
      const ph = pr.height * SCALE;

      ctx.fillStyle = 'rgba(85, 140, 55, 0.4)';
      ctx.fillRect(px, py, pw, ph);
      ctx.strokeStyle = 'rgba(255, 255, 255, 0.15)';
      ctx.lineWidth = 1;
      ctx.strokeRect(px, py, pw, ph);

      ctx.fillStyle = 'rgba(255, 255, 255, 0.45)';
      ctx.font = '8px Silkscreen';
      ctx.textAlign = 'center';
      ctx.fillText('PRACTICE', px + pw / 2, py + ph / 2 + 3);
    }

    // Putting green
    if (ch.putting_green) {
      const pg = ch.putting_green;
      const [pgx, pgy] = toCanvas(pg.x, pg.y);
      const pgr = pg.radius * SCALE;

      ctx.fillStyle = 'rgba(61, 189, 78, 0.5)';
      ctx.beginPath();
      ctx.arc(pgx, pgy, pgr, 0, Math.PI * 2);
      ctx.fill();
      ctx.strokeStyle = 'rgba(255, 255, 255, 0.15)';
      ctx.lineWidth = 1;
      ctx.stroke();

      ctx.fillStyle = 'rgba(255, 255, 255, 0.5)';
      ctx.font = '7px Silkscreen';
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
      const rx = (b.radius_x || b.radius || 5) * SCALE;
      const ry = (b.radius_y || b.radius || 4) * SCALE;
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
        const rx = (wb.radius_x || 30) * SCALE;
        const ry = (wb.radius_y || 20) * SCALE;
        ctx.fillStyle = 'rgba(30, 85, 130, 0.75)';
        ctx.beginPath();
        ctx.ellipse(wx, wy, rx, ry, 0, 0, Math.PI * 2);
        ctx.fill();
      }

      // Label
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
      ctx.lineWidth = (r.width || 6) * SCALE;
      ctx.lineCap = 'round';
      ctx.beginPath();
      const [sx, sy] = toCanvas(r.points[0].x, r.points[0].y);
      ctx.moveTo(sx, sy);
      for (let i = 1; i < r.points.length; i++) {
        const [nx, ny] = toCanvas(r.points[i].x, r.points[i].y);
        ctx.lineTo(nx, ny);
      }
      ctx.stroke();

      // Fond plus sombre
      ctx.strokeStyle = 'rgba(30, 20, 15, 0.5)';
      ctx.lineWidth = (r.width || 6) * 0.4 * SCALE;
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

  // Forêts denses
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
        const r = (3.5 + sR() * 4) * SCALE;
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
        const r = (3 + sRand() * 3.5) * SCALE;
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
      ctx.lineWidth = 5 * SCALE;
      ctx.lineCap = 'round';
      ctx.beginPath();
      ctx.moveTo(bsx, bsy);
      ctx.lineTo(bex, bey);
      ctx.stroke();

      ctx.strokeStyle = '#6b5540';
      ctx.lineWidth = 1;
      const angle = Math.atan2(bey - bsy, bex - bsx);
      const perpX = Math.sin(angle) * 3 * SCALE;
      const perpY = -Math.cos(angle) * 3 * SCALE;

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
      ctx.lineWidth = 2.5;
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

  // Practice range
  if (feat.practice_range) {
    const pr = feat.practice_range;
    const [px, py] = toCanvas(pr.x, pr.y);
    const pw = pr.width * SCALE;
    const ph = pr.height * SCALE;

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

function drawGrid(w, h) {
  ctx.strokeStyle = 'rgba(255,255,255,0.05)';
  ctx.lineWidth = 0.5;
  for (let x = 0; x <= w; x += 50) {
    const [cx] = toCanvas(x, 0);
    ctx.beginPath();
    ctx.moveTo(cx, PAD);
    ctx.lineTo(cx, PAD + h * SCALE);
    ctx.stroke();
  }
  for (let y = 0; y <= h; y += 50) {
    const [, cy] = toCanvas(0, y);
    ctx.beginPath();
    ctx.moveTo(PAD, cy);
    ctx.lineTo(PAD + w * SCALE, cy);
    ctx.stroke();
  }

  // Labels
  ctx.fillStyle = 'rgba(255,255,255,0.12)';
  ctx.font = '7px IBM Plex Mono';
  ctx.textAlign = 'center';
  for (let x = 0; x <= w; x += 100) {
    ctx.fillText(x, ...toCanvas(x, -8));
  }
  ctx.textAlign = 'right';
  for (let y = 0; y <= h; y += 100) {
    const [, cy] = toCanvas(0, y);
    ctx.fillText(y, PAD - 6, cy + 3);
  }

  // Nord
  ctx.fillStyle = 'rgba(255,255,255,0.25)';
  ctx.font = 'bold 12px Silkscreen';
  ctx.textAlign = 'center';
  ctx.fillText('N', ...toCanvas(w - 20, 15));
}

function showNoData() {
  const w = 600, h = 600;
  canvas.width = w * SCALE + PAD * 2;
  canvas.height = h * SCALE + PAD * 2;

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

// === Tooltip ===
canvas.addEventListener('mousemove', (e) => {
  if (!courseData) return;

  const rect = canvas.getBoundingClientRect();
  const mx = e.clientX - rect.left;
  const my = e.clientY - rect.top;
  const bx = Math.round((mx - PAD) / SCALE);
  const by = Math.round((my - PAD) / SCALE);

  const w = courseData.metadata.config.width || 600;
  const h = courseData.metadata.config.height || 600;

  if (bx >= 0 && bx < w && by >= 0 && by < h) {
    let info = `Bloc (${bx}, ${by})`;

    // Élévation
    if (heightmapPixels) {
      const idx = by * w + bx;
      const val = heightmapPixels[idx];
      const elev = courseData.terrain.elevation;
      const realElev = elev.min_elevation + (val / 255) * (elev.max_elevation - elev.min_elevation);
      info += ` — Y=${realElev.toFixed(1)}`;
    }

    coordsEl.textContent = info;

    // Hit test trou
    if (courseData.routing) {
      const hit = getHoleAt(bx, by);
      if (hit) {
        tooltip.style.display = 'block';
        tooltip.style.left = (e.clientX + 12) + 'px';
        tooltip.style.top = (e.clientY + 12) + 'px';
        const meters = Math.round(hit.hole.blocks * (courseData.metadata.config.scale_ratio || 3));
        tooltip.innerHTML = `<div class="tt-title">Trou ${hit.hole.id} — Par ${hit.hole.par}</div>${hit.hole.blocks} blocs (${meters}m)<br><span style="color:rgba(255,255,255,0.4)">${hit.zone}</span>`;
        setHighlight(hit.hole.id);
        return;
      }
    }

    tooltip.style.display = 'none';
    if (highlightedHole !== null) setHighlight(null);
  } else {
    tooltip.style.display = 'none';
    coordsEl.textContent = 'Survole la carte pour voir les coordonnees bloc';
    if (highlightedHole !== null) setHighlight(null);
  }
});

canvas.addEventListener('mouseleave', () => {
  tooltip.style.display = 'none';
  if (highlightedHole !== null) setHighlight(null);
});

function getHoleAt(bx, by) {
  if (!courseData.routing) return null;
  for (const h of courseData.routing.holes) {
    // Green
    if (Math.hypot(bx - h.green.x, by - h.green.y) < (h.green.radius || 8) + 2)
      return { hole: h, zone: 'green' };
    // Tee
    if (Math.hypot(bx - h.tee.x, by - h.tee.y) < 6)
      return { hole: h, zone: 'tee' };
    // Fairway
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
