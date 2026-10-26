"""Self-contained Interactive Three.js 3D Web Studio UI (`GET /` & `GET /studio`).

Served automatically at `GET /` on Render's Python runtime whenever `frontend/dist`
is not pre-built (and always reachable at `GET /studio`). Uses native browser ES
module importmaps for `three`, `GLTFLoader`, `OrbitControls`, and `RoomEnvironment`
with relative `/api/*` endpoints so it works out of the box behind any reverse proxy.
"""

from __future__ import annotations

FALLBACK_INDEX_HTML = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1, maximum-scale=1" />
<title>Procedural 3D Asset Generator Studio — Python Mid-Poly 3D Engine</title>
<link rel="icon" href="data:image/svg+xml,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 100 100'><text y='.9em' font-size='90'>🧊</text></svg>" />
<style>
  :root {
    --bg: #090d18;
    --panel: #101729;
    --panel-alt: #162038;
    --panel-hover: #1d2a49;
    --border: #253458;
    --txt: #ecf1fc;
    --muted: #93a3c7;
    --accent: #3b82f6;
    --accent-bright: #60a5fa;
    --warm: #f59e0b;
    --ok: #34d399;
    --err: #fb7185;
  }
  * { box-sizing: border-box; }
  html, body { height: 100%; margin: 0; background: var(--bg); color: var(--txt); font-family: Inter, system-ui, -apple-system, "Segoe UI", Roboto, sans-serif; }
  body { display: flex; flex-direction: column; overflow: hidden; }

  header {
    display: flex; align-items: center; justify-content: space-between; gap: 12px;
    padding: 10px 16px; background: var(--panel); border-bottom: 1px solid var(--border);
    flex-wrap: wrap; z-index: 10;
  }
  .brand { display: flex; align-items: center; gap: 10px; }
  .brand-logo {
    width: 34px; height: 34px; border-radius: 9px;
    background: linear-gradient(135deg, #3b82f6, #8b5cf6);
    display: grid; place-items: center; font-size: 18px; box-shadow: 0 4px 14px rgba(59,130,246,.35);
  }
  .brand h1 { font-size: 15px; font-weight: 700; margin: 0; letter-spacing: -0.01em; }
  .brand .sub { font-size: 11.5px; color: var(--muted); margin-top: 1px; }
  .header-badges { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
  .badge {
    font-size: 11.5px; padding: 4px 10px; border-radius: 999px;
    border: 1px solid var(--border); background: var(--panel-alt); color: var(--muted);
    display: inline-flex; align-items: center; gap: 6px;
  }
  .badge.ok { color: var(--ok); border-color: rgba(52,211,153,.35); background: rgba(16,185,129,.09); }
  .badge a { color: var(--accent-bright); text-decoration: none; }

  .workspace {
    flex: 1; display: grid; grid-template-columns: 330px 1fr 305px; min-height: 0;
  }
  aside {
    background: var(--panel); padding: 14px 15px 20px; overflow-y: auto;
    display: flex; flex-direction: column; gap: 12px;
  }
  aside.left { border-right: 1px solid var(--border); }
  aside.right { border-left: 1px solid var(--border); }

  .section-card {
    background: rgba(22, 32, 56, 0.55); border: 1px solid var(--border);
    border-radius: 11px; padding: 12px;
  }
  .section-title {
    font-size: 11px; font-weight: 700; text-transform: uppercase;
    letter-spacing: 0.08em; color: var(--muted); margin: 0 0 10px;
    display: flex; align-items: center; justify-content: space-between;
  }
  label {
    display: flex; align-items: center; justify-content: space-between;
    font-size: 12px; color: var(--txt); font-weight: 500; margin: 9px 0 5px;
  }
  label:first-of-type { margin-top: 0; }
  label span.hint { color: var(--muted); font-weight: 400; font-size: 11px; }

  select, input[type="number"], input[type="text"] {
    width: 100%; padding: 8px 10px; border-radius: 8px;
    border: 1px solid var(--border); background: var(--bg); color: var(--txt);
    font-size: 13px; outline: none;
  }
  select:focus, input:focus { border-color: var(--accent); }

  .slider-row { display: grid; grid-template-columns: 1fr 78px; gap: 8px; align-items: center; }
  input[type="range"] { width: 100%; accent-color: var(--accent); cursor: pointer; }

  .toggle-row {
    display: flex; align-items: center; justify-content: space-between;
    padding: 8px 10px; border-radius: 8px; background: var(--bg); border: 1px solid var(--border);
    margin-top: 8px; cursor: pointer; user-select: none;
  }
  .toggle-row input { width: 17px; height: 17px; accent-color: var(--accent); cursor: pointer; margin: 0; }
  .toggle-label { font-size: 12.5px; font-weight: 600; }
  .toggle-sub { font-size: 11px; color: var(--muted); display: block; margin-top: 1px; }

  .color-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; margin-top: 4px; }
  .color-box {
    background: var(--bg); border: 1px solid var(--border); border-radius: 9px; padding: 8px;
  }
  .color-picker-wrap { display: flex; align-items: center; gap: 8px; margin-top: 5px; }
  input[type="color"] {
    width: 34px; height: 30px; border: none; border-radius: 6px; padding: 0;
    background: transparent; cursor: pointer;
  }
  .hex-code { font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: 12px; color: var(--muted); }
  .swatches { display: flex; gap: 5px; margin-top: 7px; flex-wrap: wrap; }
  .swatch {
    width: 18px; height: 18px; border-radius: 50%; border: 1px solid rgba(255,255,255,.28);
    cursor: pointer; padding: 0; transition: transform .12s;
  }
  .swatch:hover { transform: scale(1.18); }

  .seed-row { display: grid; grid-template-columns: 1fr auto; gap: 8px; }

  button {
    cursor: pointer; border: 1px solid var(--border); background: var(--panel-alt);
    color: var(--txt); padding: 7px 11px; border-radius: 8px; font-size: 12.5px; font-weight: 500;
    transition: border-color .15s, background .15s, transform .06s;
  }
  button:hover { border-color: var(--accent-bright); background: var(--panel-hover); }
  button:active { transform: translateY(1px); }
  button.active { border-color: var(--ok); color: var(--ok); background: rgba(16,185,129,.12); }

  .btn-generate {
    width: 100%; padding: 12px 14px; font-size: 14px; font-weight: 700;
    background: linear-gradient(135deg, #2563eb, #4f46e5);
    border-color: #3b82f6; color: #fff; border-radius: 10px;
    box-shadow: 0 6px 20px rgba(37, 99, 235, 0.35);
    display: flex; align-items: center; justify-content: center; gap: 8px;
  }
  .btn-generate:hover { background: linear-gradient(135deg, #3b82f6, #6366f1); }
  .btn-generate:disabled { opacity: 0.6; cursor: wait; }

  .btn-download {
    width: 100%; padding: 10px 12px; font-size: 13px; font-weight: 700;
    background: rgba(16, 185, 129, 0.15); border-color: rgba(52, 211, 153, 0.5);
    color: var(--ok); border-radius: 9px; display: flex; align-items: center; justify-content: center; gap: 7px;
  }
  .btn-download:hover { background: rgba(16, 185, 129, 0.25); }
  .btn-download:disabled { opacity: 0.4; cursor: not-allowed; }

  /* Viewport */
  #viewportSection {
    position: relative; min-height: 360px; overflow: hidden;
    background: radial-gradient(circle at 50% 32%, #1d2b4f 0%, #090d18 74%);
  }
  #viewport { position: absolute; inset: 0; }
  #viewport canvas { display: block; width: 100%; height: 100%; outline: none; }

  .hud-top {
    position: absolute; top: 12px; left: 12px; right: 12px;
    display: flex; justify-content: space-between; align-items: flex-start;
    gap: 8px; pointer-events: none; flex-wrap: wrap;
  }
  .hud-pills { display: flex; gap: 6px; flex-wrap: wrap; pointer-events: auto; }
  .hud-pill {
    background: rgba(10, 15, 29, 0.78); backdrop-filter: blur(8px);
    border: 1px solid rgba(59, 130, 246, 0.28); border-radius: 8px;
    padding: 5px 9px; font-size: 11.5px; color: var(--muted);
  }
  .hud-pill b { color: var(--txt); font-weight: 700; margin-left: 3px; }

  .cam-bar { display: flex; gap: 5px; flex-wrap: wrap; pointer-events: auto; }
  .cam-bar button {
    padding: 5px 8px; font-size: 11.5px;
    background: rgba(16, 23, 41, 0.82); backdrop-filter: blur(8px);
  }

  .hud-bottom {
    position: absolute; left: 12px; right: 12px; bottom: 12px;
    display: flex; justify-content: space-between; align-items: center;
    gap: 8px; flex-wrap: wrap; pointer-events: none;
  }
  .tool-group { display: flex; gap: 6px; flex-wrap: wrap; pointer-events: auto; }
  .tool-group button {
    padding: 6px 10px; font-size: 12px;
    background: rgba(16, 23, 41, 0.86); backdrop-filter: blur(8px);
  }

  #loadingOverlay {
    position: absolute; inset: 0; display: flex; flex-direction: column;
    align-items: center; justify-content: center; gap: 10px;
    background: rgba(9, 13, 24, 0.52); backdrop-filter: blur(3px);
    z-index: 5; transition: opacity .2s;
  }
  #loadingOverlay.hidden { opacity: 0; pointer-events: none; }
  .spinner {
    width: 34px; height: 34px; border-radius: 50%;
    border: 3px solid rgba(96, 165, 250, 0.25); border-top-color: var(--accent-bright);
    animation: spin .75s linear infinite;
  }
  @keyframes spin { to { transform: rotate(360deg); } }

  /* Right inspector */
  .stat-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 7px; }
  .stat-tile {
    background: var(--bg); border: 1px solid var(--border); border-radius: 8px; padding: 8px 9px;
  }
  .stat-tile .k { font-size: 10.5px; color: var(--muted); text-transform: uppercase; letter-spacing: .04em; }
  .stat-tile .v { font-size: 15px; font-weight: 700; margin-top: 2px; color: var(--txt); }
  .stat-row {
    display: flex; justify-content: space-between; font-size: 12px;
    padding: 5px 0; border-bottom: 1px dashed rgba(37, 52, 88, 0.7);
  }
  .stat-row:last-child { border-bottom: none; }
  .stat-row span { color: var(--muted); }

  .history-list { display: flex; flex-direction: column; gap: 6px; max-height: 240px; overflow-y: auto; }
  .history-item {
    text-align: left; width: 100%; padding: 8px 10px; background: var(--bg);
  }
  .history-item small { display: block; color: var(--muted); font-size: 11px; margin-top: 2px; }

  .status-msg { font-size: 11.5px; color: var(--muted); min-height: 16px; }
  .error-msg {
    font-size: 12px; color: var(--err); background: rgba(251,113,133,.1);
    border: 1px solid rgba(251,113,133,.35); border-radius: 8px; padding: 8px 10px;
    display: none; white-space: pre-wrap;
  }

  @media (max-width: 1080px) {
    body { overflow: auto; }
    .workspace { grid-template-columns: 1fr; height: auto; }
    #viewportSection { height: 56vh; min-height: 340px; order: -1; }
    aside { overflow: visible; }
  }
</style>
</head>
<body>
<header>
  <div class="brand">
    <div class="brand-logo">🧊</div>
    <div>
      <h1>Procedural 3D Asset Generator Studio</h1>
      <div class="sub">100% Python Mid-Poly Procedural Mesh Engine · In-Memory glTF 2.0 (.glb) · Three.js WebGL Studio</div>
    </div>
  </div>
  <div class="header-badges">
    <span class="badge ok" id="engineBadge">⚡ Checking 3D engine…</span>
    <span class="badge" id="runtimeBadge">Python 3.11</span>
    <span class="badge"><a href="/docs" target="_blank" rel="noopener">OpenAPI Docs ↗</a></span>
  </div>
</header>

<div class="workspace">
  <!-- LEFT CONTROLS -->
  <aside class="left">
    <div class="section-card">
      <div class="section-title"><span>1. Model Preset</span><span id="categoryTag">humanoid</span></div>
      <label for="presetSelect">3D Generator Preset</label>
      <select id="presetSelect">
        <optgroup label="Featured Mid-Poly Generators">
          <option value="midpoly_character" selected>🧍‍♀️ Mid-Poly Stylized Female T-Pose Character</option>
          <option value="architecture">🏰 Rajasthani Courtyard Haveli (Architecture)</option>
          <option value="terrain">⛰️ Aravalli Ridge Terrain (Environment)</option>
          <option value="prop">📦 Battle Royale Supply Crate (Prop)</option>
        </optgroup>
        <optgroup label="Characters &amp; Loadouts">
          <option value="athletic_female_scout">Athletic Female Recon Scout</option>
          <option value="athletic_male_combatant">Athletic Male Combatant</option>
          <option value="armored_squad_leader">Armored Squad Leader</option>
        </optgroup>
        <optgroup label="Architecture &amp; Fortifications">
          <option value="rajput_fort_bastion">Rajput Fort Corner Bastion</option>
          <option value="chhatri_pavilion">Octagonal Chhatri Pavilion</option>
          <option value="pol_arched_gateway">Pol Fortified Arched Gateway</option>
          <option value="stone_arch_bridge">Modular Stone Arch Bridge</option>
        </optgroup>
        <optgroup label="Terrain &amp; Foliage">
          <option value="battle_royale_island">Battle Royale Coastal Island</option>
          <option value="river_ravine_crossing">River Ravine Tactical Crossing</option>
          <option value="desert_rock_outcrop">Stratified Desert Rock Outcrop</option>
          <option value="stylized_banyan_tree">Stylized Indian Banyan Tree</option>
        </optgroup>
        <optgroup label="Gameplay Props &amp; Vehicles">
          <option value="explosive_fuel_barrel">Corrugated Fuel Barrel</option>
          <option value="tactical_cover_barrier">Tactical Concrete Cover Barrier</option>
          <option value="desert_recon_buggy">Desert Off-Road Recon Buggy</option>
        </optgroup>
      </select>
      <div class="status-msg" id="presetDesc" style="margin-top:7px;">
        Symmetrical horizontal T-pose stylized female character with head, ponytail, athletic top, waist, shorts, arms, hands, legs &amp; sneakers.
      </div>
    </div>

    <div class="section-card">
      <div class="section-title"><span>2. Topology &amp; Shading</span></div>
      <label for="targetFaces">
        <span>Target Faces Budget</span>
        <span class="hint">400 – 5,000</span>
      </label>
      <div class="slider-row">
        <input id="targetFaces" type="range" min="400" max="5000" step="50" value="1800" />
        <input id="targetFacesNum" type="number" min="400" max="20000" step="50" value="1800" />
      </div>

      <label class="toggle-row" for="flatShading">
        <div>
          <span class="toggle-label">Flat Shading (Faceted Mid-Poly)</span>
          <span class="toggle-sub">Unmerge vertices &amp; sharp face normals</span>
        </div>
        <input id="flatShading" type="checkbox" checked />
      </label>
    </div>

    <div class="section-card">
      <div class="section-title"><span>3. Vertex / Face Colors</span></div>
      <div class="color-grid">
        <div class="color-box">
          <div style="font-size:11.5px;font-weight:600;">Skin / Secondary</div>
          <div class="color-picker-wrap">
            <input id="skinColor" type="color" value="#e6a88a" />
            <span class="hex-code" id="skinHex">#e6a88a</span>
          </div>
          <div class="swatches" id="skinSwatches">
            <button type="button" class="swatch" data-color="#f5c9b2" style="background:#f5c9b2" title="Porcelain"></button>
            <button type="button" class="swatch" data-color="#e6a88a" style="background:#e6a88a" title="Warm Peach"></button>
            <button type="button" class="swatch" data-color="#c98562" style="background:#c98562" title="Golden Tan"></button>
            <button type="button" class="swatch" data-color="#9c5f40" style="background:#9c5f40" title="Rich Bronze"></button>
            <button type="button" class="swatch" data-color="#6b3e28" style="background:#6b3e28" title="Deep Espresso"></button>
          </div>
        </div>
        <div class="color-box">
          <div style="font-size:11.5px;font-weight:600;">Outfit / Primary</div>
          <div class="color-picker-wrap">
            <input id="outfitColor" type="color" value="#3b82f6" />
            <span class="hex-code" id="outfitHex">#3b82f6</span>
          </div>
          <div class="swatches" id="outfitSwatches">
            <button type="button" class="swatch" data-color="#3b82f6" style="background:#3b82f6" title="Cobalt"></button>
            <button type="button" class="swatch" data-color="#ef4444" style="background:#ef4444" title="Crimson"></button>
            <button type="button" class="swatch" data-color="#10b981" style="background:#10b981" title="Emerald"></button>
            <button type="button" class="swatch" data-color="#f59e0b" style="background:#f59e0b" title="Saffron"></button>
            <button type="button" class="swatch" data-color="#8b5cf6" style="background:#8b5cf6" title="Violet"></button>
          </div>
        </div>
      </div>

      <label for="seedInput" style="margin-top:11px;">
        <span>Deterministic Seed</span>
        <span class="hint">Repeatable geometry</span>
      </label>
      <div class="seed-row">
        <input id="seedInput" type="number" min="0" max="2147483647" value="42" />
        <button type="button" id="randomSeedBtn" title="Pick random seed">🎲 Random</button>
      </div>
    </div>

    <button type="button" class="btn-generate" id="generateBtn">⚡ Generate 3D Model</button>
    <div class="status-msg" id="statusLine">Ready.</div>
    <div class="error-msg" id="errorBox"></div>
  </aside>

  <!-- CENTER 3D VIEWPORT -->
  <section id="viewportSection">
    <div id="viewport"></div>

    <div class="hud-top">
      <div class="hud-pills">
        <div class="hud-pill">Vertices <b id="hudVerts">—</b></div>
        <div class="hud-pill">Faces <b id="hudFaces">—</b></div>
        <div class="hud-pill">Triangles <b id="hudTris">—</b></div>
        <div class="hud-pill">GLB <b id="hudSize">—</b></div>
      </div>
      <div class="cam-bar">
        <button type="button" data-cam="persp">3/4 View</button>
        <button type="button" data-cam="front">Front</button>
        <button type="button" data-cam="side">Side</button>
        <button type="button" data-cam="back">Back</button>
        <button type="button" data-cam="top">Top</button>
        <button type="button" id="fitCamBtn">Fit</button>
      </div>
    </div>

    <div id="loadingOverlay">
      <div class="spinner"></div>
      <div style="font-size:13px;font-weight:600;" id="loadingText">Synthesizing 3D mesh in Python…</div>
    </div>

    <div class="hud-bottom">
      <div class="tool-group">
        <button type="button" id="edgeOverlayBtn" class="active">Facet Edges</button>
        <button type="button" id="wireOnlyBtn">Wireframe</button>
        <button type="button" id="autoRotBtn" class="active">Auto-Rotate</button>
        <button type="button" id="gridBtn" class="active">Grid &amp; Axes</button>
      </div>
      <div class="tool-group">
        <button type="button" id="bgBtn">Theme: Studio Dark</button>
        <button type="button" id="fullscreenBtn">⛶ Fullscreen</button>
      </div>
    </div>
  </section>

  <!-- RIGHT INSPECTOR & DOWNLOAD -->
  <aside class="right">
    <div class="section-card">
      <div class="section-title"><span>Live Topology Stats</span></div>
      <div class="stat-grid">
        <div class="stat-tile"><div class="k">Vertices</div><div class="v" id="statVerts">—</div></div>
        <div class="stat-tile"><div class="k">Faces</div><div class="v" id="statFaces">—</div></div>
        <div class="stat-tile"><div class="k">Triangles</div><div class="v" id="statTris">—</div></div>
        <div class="stat-tile"><div class="k">GLB Size</div><div class="v" id="statSize">—</div></div>
      </div>
      <div style="margin-top:10px;">
        <div class="stat-row"><span>Active Engine</span><b id="statEngine">—</b></div>
        <div class="stat-row"><span>Shading</span><b id="statShading">—</b></div>
        <div class="stat-row"><span>Dimensions (m)</span><b id="statDims">—</b></div>
        <div class="stat-row"><span>Gen Time</span><b id="statTime">—</b></div>
        <div class="stat-row"><span>Validation</span><b id="statValid" style="color:var(--ok);">—</b></div>
      </div>
      <div style="margin-top:12px;">
        <button type="button" class="btn-download" id="downloadGlbBtn" disabled>⬇ Download Binary .glb</button>
      </div>
    </div>

    <div class="section-card" style="flex:1;display:flex;flex-direction:column;min-height:180px;">
      <div class="section-title">
        <span>Recent Generated Assets</span>
        <button type="button" id="refreshHistoryBtn" style="padding:2px 7px;font-size:11px;">↻</button>
      </div>
      <div class="history-list" id="historyList">
        <div class="status-msg">Generating initial T-pose model…</div>
      </div>
    </div>
  </aside>
</div>

<script type="importmap">
{
  "imports": {
    "three": "https://cdn.jsdelivr.net/npm/three@0.170.0/build/three.module.js",
    "three/addons/": "https://cdn.jsdelivr.net/npm/three@0.170.0/examples/jsm/"
  }
}
</script>
<script type="module">
import * as THREE from "three";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";
import { GLTFLoader } from "three/addons/loaders/GLTFLoader.js";
import { RoomEnvironment } from "three/addons/environments/RoomEnvironment.js";

const $ = (id) => document.getElementById(id);

// ---------- Three.js WebGL Studio Setup ----------
const container = $("viewport");
const renderer = new THREE.WebGLRenderer({ antialias: true, powerPreference: "high-performance" });
renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
renderer.toneMapping = THREE.ACESFilmicToneMapping;
renderer.toneMappingExposure = 1.06;
renderer.outputColorSpace = THREE.SRGBColorSpace;
container.appendChild(renderer.domElement);

const scene = new THREE.Scene();
const pmrem = new THREE.PMREMGenerator(renderer);
scene.environment = pmrem.fromScene(new RoomEnvironment(), 0.04).texture;

const camera = new THREE.PerspectiveCamera(42, 1, 0.02, 2000);
camera.position.set(1.65, 1.35, 2.55);

const controls = new OrbitControls(camera, renderer.domElement);
controls.enableDamping = true;
controls.dampingFactor = 0.065;
controls.autoRotate = true;
controls.autoRotateSpeed = 1.15;
controls.target.set(0, 0.88, 0);

// 3-point + hemisphere studio rig for crisp facet readability
const hemi = new THREE.HemisphereLight(0xe4eeff, 0x261d18, 0.65);
scene.add(hemi);
const keyLight = new THREE.DirectionalLight(0xfff4e4, 1.55);
keyLight.position.set(4.5, 7.5, 5.5);
scene.add(keyLight);
const rimLight = new THREE.DirectionalLight(0x7dd3fc, 0.72);
rimLight.position.set(-5.0, 4.0, -5.5);
scene.add(rimLight);

const helperGroup = new THREE.Group();
const grid = new THREE.GridHelper(24, 24, 0x334b7c, 0x1b2848);
helperGroup.add(grid);
const axes = new THREE.AxesHelper(0.75);
axes.position.y = 0.002;
helperGroup.add(axes);
scene.add(helperGroup);

const gltfLoader = new GLTFLoader();
let currentRoot = null;
let edgeOverlayGroup = null;
let activeObjectUrl = null;
let latestGlbBlob = null;
let latestFilename = "midpoly_character.glb";
let latestBounds = { center: new THREE.Vector3(0, 0.86, 0), diag: 2.2, size: new THREE.Vector3(1.7, 1.72, 0.4) };
let showEdgeOverlay = true;
let wireOnly = false;
let bgIndex = 0;
const BG_THEMES = [
  { label: "Theme: Studio Dark", css: "radial-gradient(circle at 50% 32%, #1d2b4f 0%, #090d18 74%)" },
  { label: "Theme: Blueprint", css: "radial-gradient(circle at 50% 30%, #1e3a5f 0%, #0f172a 76%)" },
  { label: "Theme: Daylight Clay", css: "radial-gradient(circle at 50% 28%, #475569 0%, #1e293b 78%)" },
];

function resizeViewport() {
  const w = Math.max(container.clientWidth, 2);
  const h = Math.max(container.clientHeight, 2);
  renderer.setSize(w, h);
  camera.aspect = w / h;
  camera.updateProjectionMatrix();
}
new ResizeObserver(resizeViewport).observe(container);
resizeViewport();

renderer.setAnimationLoop(() => {
  controls.update();
  renderer.render(scene, camera);
});

function setCameraView(mode) {
  const { center, diag } = latestBounds;
  const dist = Math.max(diag * 1.15, 0.9);
  controls.target.copy(center);
  if (mode === "front") camera.position.set(center.x, center.y + dist * 0.08, center.z + dist * 1.15);
  else if (mode === "back") camera.position.set(center.x, center.y + dist * 0.08, center.z - dist * 1.15);
  else if (mode === "side") camera.position.set(center.x + dist * 1.15, center.y + dist * 0.08, center.z);
  else if (mode === "top") camera.position.set(center.x, center.y + dist * 1.35, center.z + 0.01);
  else camera.position.set(center.x + dist * 0.68, center.y + dist * 0.34, center.z + dist * 0.96);
  camera.near = Math.max(diag / 500, 0.01);
  camera.far = Math.max(diag * 60 + 200, 500);
  camera.updateProjectionMatrix();
  controls.update();
}

function rebuildOverlays() {
  if (!currentRoot) return;
  if (edgeOverlayGroup) {
    currentRoot.remove(edgeOverlayGroup);
    edgeOverlayGroup.traverse((c) => {
      if (c.geometry) c.geometry.dispose();
      if (c.material) c.material.dispose();
    });
    edgeOverlayGroup = null;
  }
  currentRoot.traverse((obj) => {
    if (obj.isMesh && obj.material) {
      obj.material.wireframe = wireOnly;
      obj.material.needsUpdate = true;
    }
  });
  if (showEdgeOverlay && !wireOnly) {
    edgeOverlayGroup = new THREE.Group();
    const lineMat = new THREE.LineBasicMaterial({
      color: 0x0b1222,
      transparent: true,
      opacity: 0.26,
    });
    currentRoot.traverse((obj) => {
      if (obj.isMesh && obj.geometry && obj !== edgeOverlayGroup) {
        const wireGeo = new THREE.WireframeGeometry(obj.geometry);
        const segs = new THREE.LineSegments(wireGeo, lineMat);
        segs.position.copy(obj.position);
        segs.quaternion.copy(obj.quaternion);
        segs.scale.copy(obj.scale);
        edgeOverlayGroup.add(segs);
      }
    });
    currentRoot.add(edgeOverlayGroup);
  }
}

async function loadGlbBytes(arrayBuffer, filename) {
  const view = new DataView(arrayBuffer);
  if (arrayBuffer.byteLength < 28 || view.getUint32(0, true) !== 0x46546c67 || view.getUint32(4, true) !== 2) {
    throw new Error("Invalid binary glTF 2.0 (.glb) header received from backend.");
  }

  const nextBlob = new Blob([arrayBuffer], { type: "model/gltf-binary" });
  const nextUrl = URL.createObjectURL(nextBlob);

  try {
    const gltf = await gltfLoader.loadAsync(nextUrl);
    if (currentRoot) {
      scene.remove(currentRoot);
    }
    if (activeObjectUrl) {
      URL.revokeObjectURL(activeObjectUrl);
    }
    activeObjectUrl = nextUrl;
    latestGlbBlob = nextBlob;
    latestFilename = filename || "generated_model.glb";
    $("downloadGlbBtn").disabled = false;

    currentRoot = gltf.scene;
    scene.add(currentRoot);
    rebuildOverlays();

    const box = new THREE.Box3().setFromObject(currentRoot);
    const size = box.getSize(new THREE.Vector3());
    const center = box.getCenter(new THREE.Vector3());
    latestBounds = { center, size, diag: Math.max(size.length(), 0.5) };
    setCameraView("persp");
  } catch (err) {
    URL.revokeObjectURL(nextUrl);
    throw err;
  }
}

function base64ToArrayBuffer(b64) {
  const bin = atob(b64);
  const bytes = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i);
  return bytes.buffer;
}

function updateStatsUI(meta) {
  const verts = (meta.vertices ?? meta.stats?.actual_vertices ?? 0).toLocaleString();
  const faces = (meta.faces ?? meta.stats?.polygon_faces ?? 0).toLocaleString();
  const tris = (meta.triangles ?? meta.stats?.actual_triangles ?? 0).toLocaleString();
  const kb = meta.file_size_kb != null
    ? `${Number(meta.file_size_kb).toFixed(1)} KB`
    : meta.glb_size_bytes ? `${(meta.glb_size_bytes / 1024).toFixed(1)} KB` : "—";

  $("hudVerts").textContent = verts;
  $("hudFaces").textContent = faces;
  $("hudTris").textContent = tris;
  $("hudSize").textContent = kb;

  $("statVerts").textContent = verts;
  $("statFaces").textContent = faces;
  $("statTris").textContent = tris;
  $("statSize").textContent = kb;
  $("statEngine").textContent = meta.engine || meta.blender_version || "python_procedural";
  $("statShading").textContent = meta.flat_shading === false ? "Smooth Normals" : "Flat Faceted";

  const dims = meta.bounding_box?.dimensions || meta.stats?.bounding_box?.dimensions;
  $("statDims").textContent = dims ? dims.map((d) => Number(d).toFixed(2)).join(" × ") : "—";
  $("statTime").textContent = meta.generation_time_ms != null
    ? `${meta.generation_time_ms} ms`
    : meta.generation_time_seconds != null ? `${Math.round(meta.generation_time_seconds * 1000)} ms` : "—";
  const valid = meta.validation ? meta.validation.valid : true;
  $("statValid").textContent = valid ? "✅ Valid glTF 2.0" : "⚠ Check Warnings";
}

// ---------- API Calls ----------
let presetCatalog = {};

async function fetchHealthAndPresets() {
  try {
    const health = await fetch("/api/health").then((r) => r.json());
    const engLabel = health.active_engine === "blender"
      ? `Blender ${health.blender_version || "4.2 LTS"}`
      : `Python 3D Engine (NumPy ${health.packages?.numpy || ""} + Trimesh)`;
    $("engineBadge").textContent = `⚡ ${engLabel}`;
    $("runtimeBadge").textContent = `Python ${health.python_version || "3.11"}`;
  } catch {
    $("engineBadge").textContent = "⚠ Backend unreachable";
  }

  try {
    const list = await fetch("/api/presets").then((r) => r.json());
    for (const p of list) presetCatalog[p.id] = p;
  } catch {}
}

async function refreshAssetHistory() {
  try {
    const assets = await fetch("/api/assets?limit=15").then((r) => r.json());
    const box = $("historyList");
    if (!Array.isArray(assets) || assets.length === 0) {
      box.innerHTML = '<div class="status-msg">No saved models yet.</div>';
      return;
    }
    box.innerHTML = "";
    for (const a of assets) {
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = "history-item";
      const tris = (a.stats?.actual_triangles ?? 0).toLocaleString();
      const kb = a.glb_size_bytes ? (a.glb_size_bytes / 1024).toFixed(1) : "0";
      btn.innerHTML = `<b>${a.name}</b><small>${a.preset_id} · ${tris} tris · ${kb} KB · seed ${a.seed}</small>`;
      btn.onclick = async () => {
        try {
          setLoading(true, `Loading ${a.name}…`);
          const resp = await fetch(a.glb_download_url);
          if (!resp.ok) throw new Error(`Download HTTP ${resp.status}`);
          const buf = await resp.arrayBuffer();
          await loadGlbBytes(buf, a.glb_filename || `${a.id}.glb`);
          updateStatsUI(a);
          $("statusLine").textContent = `Loaded ${a.name} from asset library.`;
        } catch (err) {
          showError(err);
        } finally {
          setLoading(false);
        }
      };
      box.appendChild(btn);
    }
  } catch {}
}

function setLoading(active, text) {
  const el = $("loadingOverlay");
  if (text) $("loadingText").textContent = text;
  el.classList.toggle("hidden", !active);
  $("generateBtn").disabled = active;
}

function showError(err) {
  const box = $("errorBox");
  if (!err) {
    box.style.display = "none";
    box.textContent = "";
    return;
  }
  box.style.display = "block";
  box.textContent = err?.message || String(err);
}

async function generateModel() {
  showError(null);
  const preset = $("presetSelect").value;
  const target_faces = Math.max(100, Math.min(200000, Number($("targetFacesNum").value) || 1800));
  const flat_shading = $("flatShading").checked;
  const skin_color = $("skinColor").value;
  const outfit_color = $("outfitColor").value;
  const seed = Math.max(0, Number($("seedInput").value) || 42);

  setLoading(true, `Generating ${preset} (${target_faces.toLocaleString()} target faces)…`);
  $("statusLine").textContent = "Running Python procedural 3D generator…";

  try {
    const resp = await fetch("/api/generate", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        preset,
        target_faces,
        flat_shading,
        skin_color,
        outfit_color,
        seed,
      }),
    });
    if (!resp.ok) {
      let msg = `HTTP ${resp.status}`;
      try {
        const errJson = await resp.json();
        msg = typeof errJson.detail === "string" ? errJson.detail : JSON.stringify(errJson.detail || errJson);
      } catch {}
      throw new Error(msg);
    }

    const contentType = resp.headers.get("content-type") || "";
    if (contentType.includes("model/gltf-binary")) {
      const buf = await resp.arrayBuffer();
      const fname = `${preset}_${target_faces}f_seed${seed}.glb`;
      await loadGlbBytes(buf, fname);
      updateStatsUI({
        vertices: Number(resp.headers.get("x-vertices") || 0),
        faces: Number(resp.headers.get("x-faces") || 0),
        triangles: Number(resp.headers.get("x-triangles") || 0),
        file_size_kb: Number(resp.headers.get("x-file-size-kb") || (buf.byteLength / 1024)),
        engine: resp.headers.get("x-active-engine") || "python_procedural",
        flat_shading,
      });
    } else {
      const data = await resp.json();
      const buf = data.glb_base64
        ? base64ToArrayBuffer(data.glb_base64)
        : await (await fetch(data.glb_url)).arrayBuffer();
      const fname = `${data.preset_id || preset}_${data.triangles}tris_seed${seed}.glb`;
      await loadGlbBytes(buf, fname);
      updateStatsUI(data);
      $("categoryTag").textContent = data.category || "3d";
      $("statusLine").textContent = `Generated ${data.name} (${data.triangles.toLocaleString()} tris, ${data.file_size_kb} KB) in ${data.generation_time_ms} ms.`;
    }
    await refreshAssetHistory();
  } catch (err) {
    showError(err);
    $("statusLine").textContent = "Generation failed.";
  } finally {
    setLoading(false);
  }
}

// ---------- UI Event Wiring ----------
const PRESET_NOTES = {
  midpoly_character: "Symmetrical horizontal T-pose stylized female character with sculpted head, ponytail, neck, athletic sports top, waist, shorts, arms, hands, thighs, calves & sneakers.",
  architecture: "Multi-story Rajasthani courtyard haveli with cusped arches, cantilevered jharokha balconies, chhajja eaves, and rooftop kangura battlements.",
  terrain: "Multi-octave Aravalli mountain ridge terrain solid with geological terraces, closed watertight base skirt, boulders, and stylized trees.",
  prop: "Reinforced Battle Royale supply drop crate with chamfered corner bumpers, recessed side panels, lid latches, and tactical color accents.",
};

$("presetSelect").addEventListener("change", () => {
  const val = $("presetSelect").value;
  const info = presetCatalog[val];
  $("presetDesc").textContent = PRESET_NOTES[val] || info?.description || "Procedural 3D asset preset.";
  if (info?.category) $("categoryTag").textContent = info.category;
});

$("targetFaces").addEventListener("input", (e) => { $("targetFacesNum").value = e.target.value; });
$("targetFacesNum").addEventListener("input", (e) => {
  const v = Math.min(5000, Math.max(400, Number(e.target.value) || 400));
  $("targetFaces").value = String(v);
});

$("skinColor").addEventListener("input", (e) => { $("skinHex").textContent = e.target.value; });
$("outfitColor").addEventListener("input", (e) => { $("outfitHex").textContent = e.target.value; });

$("skinSwatches").querySelectorAll(".swatch").forEach((btn) => {
  btn.addEventListener("click", () => {
    const c = btn.dataset.color;
    $("skinColor").value = c;
    $("skinHex").textContent = c;
    generateModel();
  });
});

$("outfitSwatches").querySelectorAll(".swatch").forEach((btn) => {
  btn.addEventListener("click", () => {
    const c = btn.dataset.color;
    $("outfitColor").value = c;
    $("outfitHex").textContent = c;
    generateModel();
  });
});

$("flatShading").addEventListener("change", () => generateModel());
$("randomSeedBtn").addEventListener("click", () => {
  $("seedInput").value = String(Math.floor(Math.random() * 999999) + 1);
  generateModel();
});
$("generateBtn").addEventListener("click", () => generateModel());
$("refreshHistoryBtn").addEventListener("click", () => refreshAssetHistory());

$("downloadGlbBtn").addEventListener("click", () => {
  if (!latestGlbBlob) return;
  const dlUrl = URL.createObjectURL(latestGlbBlob);
  const a = document.createElement("a");
  a.href = dlUrl;
  a.download = latestFilename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(dlUrl), 1500);
});

document.querySelectorAll("[data-cam]").forEach((btn) => {
  btn.addEventListener("click", () => setCameraView(btn.dataset.cam));
});
$("fitCamBtn").addEventListener("click", () => setCameraView("persp"));

$("edgeOverlayBtn").addEventListener("click", (e) => {
  showEdgeOverlay = !showEdgeOverlay;
  e.currentTarget.classList.toggle("active", showEdgeOverlay);
  rebuildOverlays();
});
$("wireOnlyBtn").addEventListener("click", (e) => {
  wireOnly = !wireOnly;
  e.currentTarget.classList.toggle("active", wireOnly);
  rebuildOverlays();
});
$("autoRotBtn").addEventListener("click", (e) => {
  controls.autoRotate = !controls.autoRotate;
  e.currentTarget.classList.toggle("active", controls.autoRotate);
});
$("gridBtn").addEventListener("click", (e) => {
  helperGroup.visible = !helperGroup.visible;
  e.currentTarget.classList.toggle("active", helperGroup.visible);
});
$("bgBtn").addEventListener("click", (e) => {
  bgIndex = (bgIndex + 1) % BG_THEMES.length;
  $("viewportSection").style.background = BG_THEMES[bgIndex].css;
  e.currentTarget.textContent = BG_THEMES[bgIndex].label;
});
$("fullscreenBtn").addEventListener("click", () => {
  const el = $("viewportSection");
  if (!document.fullscreenElement) el.requestFullscreen?.();
  else document.exitFullscreen?.();
});

// Boot: load engine health, presets, and immediately generate default Mid-Poly Female T-Pose Character!
(async () => {
  await fetchHealthAndPresets();
  await generateModel();
})();
</script>
</body>
</html>
"""
