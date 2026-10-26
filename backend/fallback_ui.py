"""Self-contained fallback Three.js studio UI.

Served at ``GET /`` whenever the production React build (``frontend/dist``)
is not present — e.g. Render Native Python deploys that only run
``pip install -r requirements.txt``. The page is a single HTML document:
it loads Three.js from a CDN, talks to the same ``/api/*`` endpoints as
the React studio (relative URLs only, so it works behind any proxy), and
provides preset browsing, generation with live progress, an interactive
GLB viewport, stats, and downloads.
"""

from __future__ import annotations

FALLBACK_INDEX_HTML = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<title>Procedural 3D Asset Generator Studio</title>
<link rel="icon" href="data:image/svg+xml,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 100 100'><text y='.9em' font-size='90'>🧊</text></svg>" />
<style>
  :root { --bg:#0b1020; --panel:#131a2e; --panel2:#182138; --line:#263355; --txt:#e8edf9; --dim:#93a0bf; --acc:#e08a3c; --acc2:#4da3ff; --ok:#3ecf8e; --err:#ff6b6b; }
  * { box-sizing:border-box; } html,body { height:100%; }
  body { margin:0; font-family:system-ui,-apple-system,"Segoe UI",Roboto,sans-serif; background:var(--bg); color:var(--txt); display:flex; flex-direction:column; }
  header { display:flex; align-items:center; gap:14px; padding:12px 18px; background:var(--panel); border-bottom:1px solid var(--line); flex-wrap:wrap; }
  header h1 { font-size:17px; margin:0; } header .sub { color:var(--dim); font-size:12px; }
  .badge { font-size:12px; padding:4px 10px; border-radius:999px; border:1px solid var(--line); background:var(--panel2); }
  .badge.ok { color:var(--ok); border-color:#1f5c40; } .badge.warn { color:var(--acc); }
  main { flex:1; display:grid; grid-template-columns:320px 1fr 300px; min-height:0; }
  aside { background:var(--panel); padding:16px; overflow-y:auto; }
  aside.left { border-right:1px solid var(--line); } aside.right { border-left:1px solid var(--line); }
  h2 { font-size:13px; text-transform:uppercase; letter-spacing:.08em; color:var(--dim); margin:14px 0 8px; }
  h2:first-child { margin-top:0; }
  label { display:block; font-size:12px; color:var(--dim); margin:10px 0 4px; }
  select, input { width:100%; padding:8px; border-radius:8px; border:1px solid var(--line); background:var(--panel2); color:var(--txt); font-size:14px; }
  button { cursor:pointer; border:1px solid var(--line); background:var(--panel2); color:var(--txt); padding:8px 12px; border-radius:8px; font-size:13px; }
  button:hover { border-color:var(--acc2); } button.primary { background:var(--acc); border-color:var(--acc); color:#1a1206; font-weight:700; width:100%; padding:11px; margin-top:14px; font-size:14px; }
  button.primary:disabled { opacity:.55; cursor:wait; }
  button.on { border-color:var(--ok); color:var(--ok); }
  .row { display:flex; gap:8px; flex-wrap:wrap; }
  #viewportWrap { position:relative; min-height:320px; background:radial-gradient(ellipse at 50% 35%, #1b2748 0%, #0b1020 70%); }
  #viewport { position:absolute; inset:0; } #viewport canvas { display:block; }
  #viewportMsg { position:absolute; inset:0; display:flex; align-items:center; justify-content:center; color:var(--dim); text-align:center; padding:20px; pointer-events:none; }
  .toolbar { position:absolute; left:12px; bottom:12px; display:flex; gap:8px; flex-wrap:wrap; }
  .toolbar a { text-decoration:none; }
  #progressWrap { height:10px; background:var(--panel2); border-radius:5px; overflow:hidden; margin-top:12px; border:1px solid var(--line); }
  #progressBar { height:100%; width:0%; background:linear-gradient(90deg,var(--acc),var(--acc2)); transition:width .3s; }
  #log { font-family:ui-monospace,Menlo,Consolas,monospace; font-size:11px; color:var(--dim); white-space:pre-wrap; max-height:180px; overflow-y:auto; margin-top:10px; }
  .stat { display:flex; justify-content:space-between; padding:5px 0; border-bottom:1px dashed #1d2947; font-size:13px; }
  .stat b { font-weight:600; }
  .assetItem { width:100%; text-align:left; margin-bottom:8px; }
  .assetItem small { display:block; color:var(--dim); margin-top:2px; }
  .err { color:var(--err); font-size:13px; margin-top:10px; white-space:pre-wrap; }
  .note { font-size:12px; color:var(--dim); line-height:1.5; }
  a { color:var(--acc2); }
  @media (max-width: 1050px) { main { grid-template-columns:1fr; overflow-y:auto; } #viewportWrap { height:55vh; } aside { overflow:visible; } }
</style>
</head>
<body>
<header>
  <div>
    <h1>🧊 Procedural 3D Asset Generator Studio</h1>
    <div class="sub">Blender 4.2 LTS / Pure-Python dual-engine · glTF 2.0 (.glb) · Godot 4 Android pipeline</div>
  </div>
  <span class="badge" id="engineBadge">checking engine…</span>
  <span class="badge" id="healthBadge">…</span>
  <span class="badge"><a href="/docs" target="_blank" rel="noopener">API docs</a></span>
</header>
<main>
  <aside class="left">
    <h2>Generate asset</h2>
    <label for="category">Category</label>
    <select id="category">
      <option value="props">Gameplay Props &amp; Vehicles</option>
      <option value="architecture" selected>Architecture &amp; Forts</option>
      <option value="environment">Terrain &amp; Environment</option>
      <option value="humanoid">Humanoid Characters</option>
    </select>
    <label for="preset">Preset</label>
    <select id="preset"></select>
    <div class="note" id="presetDesc" style="margin-top:6px"></div>
    <label for="quality">Quality profile</label>
    <select id="quality">
      <option value="prototype">Prototype (fast)</option>
      <option value="optimized_mid_poly" selected>Optimized Mid-Poly (Godot 4 Android)</option>
      <option value="detailed_mid_poly">Detailed Mid-Poly (hero)</option>
    </select>
    <label for="material">Material theme</label>
    <select id="material">
      <option value="default" selected>Preset default</option>
      <option value="rajasthan_sandstone">Rajasthani Pink/Red Sandstone</option>
      <option value="makrana_marble">Makrana Royal Marble &amp; Gold</option>
      <option value="tactical_military">Tactical Olive &amp; Gunmetal</option>
      <option value="desert_camo">Thar Desert Tan &amp; Weathered Steel</option>
      <option value="aravalli_biome">Aravalli Scrubland &amp; Granite</option>
      <option value="cyber_arena">Arena Carbon &amp; Cobalt</option>
    </select>
    <label for="seed">Seed</label>
    <input id="seed" type="number" value="1727" min="0" max="2147483647" />
    <label for="assetName">Asset name (optional)</label>
    <input id="assetName" type="text" maxlength="80" placeholder="e.g. Jaipur Drop Crate" />
    <button class="primary" id="generateBtn">⚙️ Generate 3D Asset</button>
    <div id="progressWrap"><div id="progressBar"></div></div>
    <div id="log"></div>
    <div class="err" id="errorBox"></div>
    <h2>About this viewer</h2>
    <p class="note">This is the built-in fallback studio, served when the React
    build (<code>frontend/dist</code>) is not present. Generation runs on the
    Blender engine when installed, otherwise on the pure-Python
    NumPy+Trimesh engine — either way you get a validated binary
    <code>.glb</code>. Drag to orbit · scroll to zoom · right-drag to pan.</p>
  </aside>

  <section id="viewportWrap">
    <div id="viewport"></div>
    <div id="viewportMsg">Pick a preset and click <b>&nbsp;Generate 3D Asset&nbsp;</b> — your model will appear here.</div>
    <div class="toolbar">
      <button id="wireBtn" type="button">Wireframe</button>
      <button id="spinBtn" type="button" class="on">Auto-rotate</button>
      <button id="resetBtn" type="button">Reset view</button>
      <a id="downloadBtn" href="#" style="display:none"><button type="button">⬇ Download .glb</button></a>
    </div>
  </section>

  <aside class="right">
    <h2>Mesh inspector</h2>
    <div id="stats"><p class="note">No asset loaded yet.</p></div>
    <h2>Asset library</h2>
    <div id="library"><p class="note">Loading…</p></div>
    <button id="refreshLib" type="button" style="width:100%">↻ Refresh library</button>
  </aside>
</main>

<script type="importmap">
{ "imports": {
  "three": "https://cdn.jsdelivr.net/npm/three@0.170.0/build/three.module.js",
  "three/addons/": "https://cdn.jsdelivr.net/npm/three@0.170.0/examples/jsm/"
} }
</script>
<script type="module">
import * as THREE from "three";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";
import { GLTFLoader } from "three/addons/loaders/GLTFLoader.js";
import { RoomEnvironment } from "three/addons/environments/RoomEnvironment.js";

const $ = (id) => document.getElementById(id);
const api = async (path, init) => {
  const r = await fetch(path, init);
  if (!r.ok) {
    let detail = `HTTP ${r.status}`;
    try { const b = await r.json(); detail = typeof b.detail === "string" ? b.detail : JSON.stringify(b.detail ?? b); } catch {}
    throw new Error(detail);
  }
  return r.json();
};

// ---------- Three.js scene ----------
const container = $("viewport");
const renderer = new THREE.WebGLRenderer({ antialias: true });
renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
renderer.toneMapping = THREE.ACESFilmicToneMapping;
container.appendChild(renderer.domElement);
const scene = new THREE.Scene();
const pmrem = new THREE.PMREMGenerator(renderer);
scene.environment = pmrem.fromScene(new RoomEnvironment(), 0.04).texture;
const camera = new THREE.PerspectiveCamera(45, 1, 0.05, 2000);
camera.position.set(8, 6, 10);
const controls = new OrbitControls(camera, renderer.domElement);
controls.enableDamping = true;
controls.autoRotate = true;
controls.autoRotateSpeed = 1.1;
scene.add(new THREE.HemisphereLight(0xdfe9ff, 0x33241a, 0.55));
const sun = new THREE.DirectionalLight(0xffe2b0, 1.6);
sun.position.set(12, 18, 8);
scene.add(sun);
const grid = new THREE.GridHelper(60, 60, 0x2c3d66, 0x1a2745);
scene.add(grid);
let currentModel = null, currentObjectUrl = null, wireframe = false;

function resize() {
  const w = container.clientWidth || 2, h = container.clientHeight || 2;
  renderer.setSize(w, h);
  camera.aspect = w / h;
  camera.updateProjectionMatrix();
}
new ResizeObserver(resize).observe(container);
resize();
renderer.setAnimationLoop(() => { controls.update(); renderer.render(scene, camera); });

function frameModel(obj) {
  const box = new THREE.Box3().setFromObject(obj);
  const size = box.getSize(new THREE.Vector3());
  const center = box.getCenter(new THREE.Vector3());
  const diag = Math.max(size.length(), 0.5);
  camera.position.set(center.x + diag * 0.85, center.y + diag * 0.55, center.z + diag * 0.85);
  controls.target.copy(center);
  camera.near = Math.max(diag / 500, 0.01);
  camera.far = diag * 60 + 500;
  camera.updateProjectionMatrix();
  controls.update();
}

async function loadGlb(downloadUrl, asset) {
  const resp = await fetch(downloadUrl);
  if (!resp.ok) throw new Error(`GLB download failed (HTTP ${resp.status})`);
  const buf = await resp.arrayBuffer();
  const view = new DataView(buf);
  if (buf.byteLength < 28 || view.getUint32(0, true) !== 0x46546c67 || view.getUint32(4, true) !== 2) {
    throw new Error("Downloaded file is not a valid glTF 2.0 binary (.glb).");
  }
  if (currentObjectUrl) URL.revokeObjectURL(currentObjectUrl);
  currentObjectUrl = URL.createObjectURL(new Blob([buf], { type: "model/gltf-binary" }));
  const gltf = await new GLTFLoader().loadAsync(currentObjectUrl);
  if (currentModel) { scene.remove(currentModel); }
  currentModel = gltf.scene;
  currentModel.traverse((o) => { if (o.isMesh && o.material) { o.material.wireframe = wireframe; } });
  scene.add(currentModel);
  $("viewportMsg").style.display = "none";
  frameModel(currentModel);
  if (asset) renderStats(asset);
  const dl = $("downloadBtn");
  dl.href = downloadUrl;
  dl.style.display = "";
}

function renderStats(asset) {
  const s = asset.stats || {}, v = asset.validation || {}, bb = s.bounding_box || {};
  const dims = (bb.dimensions || []).map((x) => Number(x).toFixed(2)).join(" × ");
  const rows = [
    ["Asset", asset.name || asset.id], ["Category / Preset", `${asset.category} / ${asset.preset_id}`],
    ["Triangles", (s.actual_triangles ?? 0).toLocaleString()], ["Vertices", (s.actual_vertices ?? 0).toLocaleString()],
    ["Meshes", s.mesh_count ?? "—"], ["Materials", s.material_count ?? "—"],
    ["Dimensions (m)", dims || "—"], ["GLB size", asset.glb_size_bytes ? `${(asset.glb_size_bytes/1024).toFixed(1)} KB` : "—"],
    ["Engine", asset.blender_version || "—"], ["Validation", v.valid ? `✅ valid (${v.passed_count} checks)` : "❌ invalid"],
    ["Rigged", s.rig?.has_armature ? `yes (${s.rig.bone_count} bones)` : "static mesh"],
  ];
  $("stats").innerHTML = rows.map(([k, val]) => `<div class="stat"><span>${k}</span><b>${val}</b></div>`).join("");
}

// ---------- Catalog / library ----------
let presets = [];
function refreshPresets() {
  const cat = $("category").value;
  const list = presets.filter((p) => p.category === cat);
  $("preset").innerHTML = list.map((p) => `<option value="${p.id}">${p.name}</option>`).join("");
  updatePresetDesc();
}
function updatePresetDesc() {
  const p = presets.find((x) => x.id === $("preset").value);
  $("presetDesc").textContent = p ? p.description : "";
}
async function refreshLibrary() {
  try {
    const assets = await api("/api/assets?limit=30");
    $("library").innerHTML = assets.length ? "" : '<p class="note">No generated assets yet.</p>';
    for (const a of assets) {
      const b = document.createElement("button");
      b.className = "assetItem"; b.type = "button";
      b.innerHTML = `${a.name}<small>${a.category} · ${(a.stats?.actual_triangles ?? 0).toLocaleString()} tris · ${new Date(a.created_at).toLocaleString()}</small>`;
      b.onclick = () => loadGlb(a.glb_download_url, a).catch(showError);
      $("library").appendChild(b);
    }
  } catch (e) { $("library").innerHTML = `<p class="err">${e.message}</p>`; }
}

// ---------- Generation flow ----------
function log(line) { const el = $("log"); el.textContent += line + "\\n"; el.scrollTop = el.scrollHeight; }
function showError(e) { $("errorBox").textContent = e?.message || String(e); }
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

$("generateBtn").onclick = async () => {
  const btn = $("generateBtn");
  btn.disabled = true; $("errorBox").textContent = ""; $("log").textContent = "";
  $("progressBar").style.width = "3%";
  try {
    const body = {
      name: $("assetName").value.trim() || null,
      category: $("category").value,
      preset_id: $("preset").value,
      quality_profile: $("quality").value,
      seed: Number($("seed").value || 42),
      material_preset: $("material").value,
      save_blend: false,
      execution_mode: "live",
      parameters: {},
    };
    const job = await api("/api/generate", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
    log(`Job ${job.id} queued…`);
    let cur = job, seenLogs = 0;
    while (cur.status === "queued" || cur.status === "running") {
      await sleep(650);
      cur = await api(`/api/jobs/${encodeURIComponent(job.id)}`);
      $("progressBar").style.width = `${cur.progress_pct}%`;
      for (; seenLogs < (cur.logs || []).length; seenLogs++) {
        const l = cur.logs[seenLogs];
        log(`[${l.progress_pct}%] ${l.message}`);
      }
    }
    if (cur.status !== "completed") throw new Error(cur.error || `Job ${cur.status}`);
    const result = await api(`/api/jobs/${encodeURIComponent(job.id)}/result`);
    if (!result.asset) throw new Error("Job completed without an asset record.");
    log(`✅ Done: ${result.asset.glb_filename} (${(result.asset.glb_size_bytes/1024).toFixed(1)} KB)`);
    await loadGlb(result.asset.glb_download_url, result.asset);
    await refreshLibrary();
  } catch (e) {
    showError(e);
    log(`❌ ${e.message}`);
  } finally {
    btn.disabled = false;
  }
};

$("category").onchange = refreshPresets;
$("preset").onchange = updatePresetDesc;
$("refreshLib").onclick = refreshLibrary;
$("wireBtn").onclick = () => {
  wireframe = !wireframe;
  $("wireBtn").classList.toggle("on", wireframe);
  if (currentModel) currentModel.traverse((o) => { if (o.isMesh && o.material) o.material.wireframe = wireframe; });
};
$("spinBtn").onclick = () => {
  controls.autoRotate = !controls.autoRotate;
  $("spinBtn").classList.toggle("on", controls.autoRotate);
};
$("resetBtn").onclick = () => { if (currentModel) frameModel(currentModel); };

// ---------- Boot ----------
(async () => {
  try {
    const h = await api("/api/health");
    const engine = h.generation_engine === "blender" ? `Blender ${h.blender_version || ""}`.trim() : "Pure-Python engine (NumPy+Trimesh)";
    $("engineBadge").textContent = `⚙️ ${engine}`;
    $("engineBadge").className = "badge ok";
    $("healthBadge").textContent = h.status === "ok" ? "● service healthy" : `● ${h.status}`;
    $("healthBadge").className = "badge " + (h.status === "ok" ? "ok" : "warn");
  } catch { $("engineBadge").textContent = "engine unknown"; }
  try {
    presets = await api("/api/presets");
    refreshPresets();
    const born = $("preset");
    if ([...born.options].some((o) => o.value === "rajasthani_haveli")) { born.value = "rajasthani_haveli"; updatePresetDesc(); }
  } catch (e) { showError(e); }
  await refreshLibrary();
})();
</script>
</body>
</html>
"""
