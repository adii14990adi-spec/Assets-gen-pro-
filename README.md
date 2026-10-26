# Procedural 3D Asset Generator Studio

**Python 3.11 + Blender 4.2 LTS (`bpy` & BMesh & Geometry Nodes) + NumPy + FastAPI + React Three Fiber + GitHub Actions**

An end-to-end procedural 3D game asset studio engineered for **Godot 4 Android Battle Royale** production pipelines. Configure parametric 3D characters, Rajasthani & modular architecture, multi-octave terrain, and gameplay props in the browser, generate **genuine 3D geometry** inside an isolated Blender 4.2 LTS runtime, validate topology and normalized skin weights independently, inspect the real binary `.glb` in an interactive 3D viewport, and download game-ready `.glb` and `.blend` assets.

---

## Verified Runtime Stack

| Layer | Technology & Pinned Version | Notes |
| --- | --- | --- |
| **3D Engine** | Blender **4.2.23 LTS** (`bpy==4.2.23` isolated Python 3.11 runtime or standalone `blender` 4.2+ CLI) | Never imported inside the FastAPI web server process; executed strictly in isolated background subprocesses. |
| **Procedural Geometry** | `bmesh`, `numpy==1.26.4`, Blender **Geometry Nodes**, Exact **Boolean** CSG, **Skin + Subsurf** modifiers | Deterministic seeded generation across all 4 categories. |
| **Blender Extensions** | `io_scene_gltf2`, `rigify`, `mesh_looptools` (GPL-2.0+), `object_boolean_tools` (GPL-2.0+), optional `mpfb` | Dynamically probed and verified at runtime via the **Capability Registry** with honest fallback adapters. |
| **Pure-Python 3D Engine** | NumPy + SciPy + Trimesh procedural engine (`backend/fallback/engine.py`, `backend/fallback/character_tpose.py`) | Generates all **18 presets** (including the spline-lofted **Mid-Poly Stylized Female T-Pose Character**) in memory (`io.BytesIO`) as validated binary `.glb` files with configurable `target_faces`, `flat_shading`, `skin_color`, `outfit_color`, and `seed` — zero Blender installation required on **Render Native Python**. |
| **Mesh Validation** | `trimesh>=4,<5`, `scipy>=1.11.4,<1.16`, optional `pymeshlab` (`requirements-optional.txt`), glTF 2.0 binary chunk inspector + roundtrip re-import | Measures **actual** triangle/vertex counts, winding, manifoldness, UVs, transforms, and normalized 4-bone skin weights. |
| **Backend API & Queue** | Python **3.11.11** (pinned via `.python-version` / `runtime.txt`), `fastapi>=0.115`, `pydantic>=2.11`, `sqlalchemy>=2.0` (SQLite WAL / PostgreSQL) — all binary-wheel installs | Async bounded worker pool, Server-Sent Events (SSE), WebSocket job progress, retries, timeouts, and cancellation. |
| **Interactive 3D Frontend** | React **18.3**, TypeScript **5.7**, Vite **6.0**, Three.js **0.170**, `@react-three/fiber`, `@react-three/drei` | Loads the exact generated `.glb` binary, supports Material / Solid / Wireframe / Rig views, 6 camera presets, and revokes blob URLs cleanly. |
| **CI/CD** | GitHub Actions (`.github/workflows/ci.yml` & `.github/workflows/generate-asset.yml`) | Automated linting, TypeScript & Vitest checks, Blender smoke test, E2E pytest suite, and manual `workflow_dispatch` asset packaging. |

---

## Asset Categories & Presets (18 Presets)

### 1. Humanoid Characters (`humanoid`)
- **Presets**: `midpoly_character` (*Mid-Poly Stylized Female T-Pose Character*), `athletic_male_combatant`, `athletic_female_scout`, `armored_squad_leader`
- **Features**: Single-piece connected watertight anatomical mesh (pelvis, abdomen, ribcage, chest, neck, sculpted head, shoulders, arms, forearms, palms, **5 articulated fingers per hand**, thighs, knees, calves, ankles, heels, feet), NumPy muscle-group harmonic sculpting, fitted tactical shirt & cargo trousers, combat boots, sculpted hair, plate-carrier armor vest, survival backpack, and **31-bone Godot 4 `SkeletonProfileHumanoid`-compatible Armature** with normalized max-4 bone weights and an exported `IdleReady` animation clip.

### 2. Rajasthani, Indian & Modular Architecture (`architecture`)
- **Presets**: `rajasthani_haveli`, `rajput_fort_bastion`, `chhatri_pavilion`, `pol_arched_gateway`, `stone_arch_bridge`
- **Features**: Enterable thick-walled masonry structures, pointed multifoil cusped arches carved with Blender's Exact Boolean CSG solver, cantilevered **Jharokha** balconies, sloped **Chhajja** eaves, ribbed lotus domes with Kalash finials, and **Geometry Nodes Kangura** rooftop battlements.

### 3. Environment & Terrain (`environment`)
- **Presets**: `aravalli_ridge_terrain`, `battle_royale_island`, `river_ravine_crossing`, `desert_rock_outcrop`, `stylized_banyan_tree`
- **Features**: Vectorized NumPy multi-octave fBm & ridged multifractal terrain synthesis, terraced geological strata, closed watertight terrain skirts, **Geometry Nodes** Poisson boulder scattering, coastal/river translucent water planes, and spline-lofted Indian Banyan trees with aerial prop roots.

### 4. Gameplay Props & Vehicles (`props`)
- **Presets**: `br_supply_crate`, `explosive_fuel_barrel`, `tactical_cover_barrier`, `desert_recon_buggy`
- **Features**: Chamfered hard-surface geometry, recessed panels, corner bumpers, corrugated barrel chimes, Boolean forklift drainage slots, and a complete two-seat off-road Battle Royale recon buggy with roll cage and treaded wheels.

---

## Quick Start (Local Development)

### 1. Set up the Backend & Isolated Blender 4.2 LTS Runtime

```bash
python3.11 -m venv .venv
.venv/bin/pip install --upgrade pip
.venv/bin/pip install -r requirements-dev.txt

# Bootstraps isolated Blender 4.2.23 LTS runtime in ~/.local/blender-runtime
# (keeps `bpy` strictly isolated from the FastAPI web server venv)
.venv/bin/python scripts/setup_blender_runtime.py

# Verify headless Blender mesh creation & GLB roundtrip
.venv/bin/python scripts/smoke_test_blender.py
```

### 2. Install & Build the Frontend

```bash
cd frontend
npm install
npm run typecheck
npm test
cd ..
```

### 3. Run the Live Studio (Backend + Vite Dev Server)

Terminal 1 — FastAPI + Background Blender Worker:
```bash
.venv/bin/uvicorn backend.main:app --host 0.0.0.0 --port 8000
```

Terminal 2 — Interactive React Three Fiber Studio:
```bash
cd frontend
npm run dev
```

Open `http://localhost:5173` (or run production single-port mode after `cd frontend && npm run build` at `http://localhost:8000`).

## Direct Live Generation API (`POST /api/generate`)

Generate a mid-poly 3D model in memory and receive JSON with `glb_base64`, `glb_url`, and live topology stats (`vertices`, `faces`, `triangles`, `file_size_kb`):

```bash
curl -X POST http://localhost:8000/api/generate \
  -H "Content-Type: application/json" \
  -d '{
    "preset": "midpoly_character",
    "target_faces": 1800,
    "flat_shading": true,
    "skin_color": "#e6a88a",
    "outfit_color": "#3b82f6",
    "seed": 42
  }'
```

Or stream the binary `.glb` (`model/gltf-binary`) directly:

```bash
curl -X POST "http://localhost:8000/api/generate?format=glb" \
  -H "Content-Type: application/json" \
  -d '{"preset": "midpoly_character", "target_faces": 1800, "flat_shading": true, "seed": 42}' \
  --output midpoly_character.glb
```

---

## Deployment (Render Free Tier & Docker)

Python is pinned to **3.11.11** everywhere (`.python-version`, `runtime.txt`, `PYTHON_VERSION` in `render.yaml`, `python:3.11.11-slim` in the `Dockerfile`). Without the pin, Render selects a newer interpreter where `numpy`/`scipy` fall back to source builds and fail with `ERROR: Unknown compiler(s): [['gfortran']]`. Every dependency in `requirements.txt` ships pre-compiled CPython 3.11 wheels, so installs never compile from source:

```bash
pip install --only-binary=:all: -r requirements.txt   # verified in CI
```

### Option A — Render Native Python (1-click, free)

Import the repo as a Render Blueprint (`render.yaml`) or create a Web Service with:

- **Build Command**: `pip install --upgrade pip setuptools wheel && pip install --prefer-binary -r requirements.txt`
- **Start Command**: `uvicorn app:app --host 0.0.0.0 --port $PORT`
- **Env**: `PYTHON_VERSION=3.11.11`

Render has no `blender` binary, so the dual-engine dispatcher automatically uses the **pure-Python fallback engine**: all presets generate validated `.glb` files in-process (humanoids are static A-pose characters — skinned rigs and native `.blend` files require the Blender engine), and `GET /` serves a built-in interactive Three.js studio. All root entrypoints work identically: `uvicorn app:app`, `uvicorn main:app`, `uvicorn backend.main:app`.

### Option B — Docker (full Blender 4.2 LTS engine + React studio)

```bash
docker build -t assets-gen-pro .                        # full dual-engine image
docker build --target runtime-lite -t assets-gen-pro:lite .  # Blender-free, small
docker run --rm -p 8000:8000 -e PORT=8000 assets-gen-pro
```

The default image contains the isolated headless Blender 4.2 LTS runtime (`bpy==4.2.23`), the built React Three Fiber frontend (`frontend/dist`, served at `GET /`), and the FastAPI service. Force an engine with `-e STUDIO_GENERATION_ENGINE=blender|python|auto`.

> **GitHub Pages**: CI can deploy the static frontend to Pages, but only after Pages is enabled once in **Settings → Pages → Source: GitHub Actions**. Until then the deployment job is skipped with a warning and CI stays green. See [`docs/DEPLOYMENT.md`](docs/DEPLOYMENT.md) for details, Godot 4 notes in [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md).

## CLI Generation & Automated Tests

Generate any asset directly from the command line:
```bash
.venv/bin/python scripts/cli_generate.py \
  --category architecture \
  --preset rajasthani_haveli \
  --quality optimized_mid_poly \
  --seed 1727 \
  --save-blend \
  --output-dir artifacts_out
```

Run all backend, Blender E2E, and frontend tests:
```bash
.venv/bin/ruff check backend scripts tests app.py
.venv/bin/pytest -v
cd frontend && npm test
```

---

## API Overview

| Method & Path | Description |
| --- | --- |
| `GET /api/health` | Service status, Blender runtime availability, version, and queue metrics |
| `GET /api/capabilities` | Verified Blender add-ons & Python mesh libraries with licenses and fallbacks |
| `GET /api/assets/types` | Category definitions, polygon budget guides, material themes, and parameter schemas |
| `GET /api/presets` | Preset catalogue (optional `?category=` filter) |
| `POST /api/generate` | Validate config and enqueue asynchronous Blender generation job (`202 Accepted`) |
| `GET /api/jobs/{job_id}` | Poll job state (`queued`, `running`, `completed`, `failed`, `cancelled`) and stage logs |
| `GET /api/jobs/{job_id}/events` | Server-Sent Events (SSE) real-time job progress stream |
| `WS /api/jobs/{job_id}/ws` | WebSocket real-time job progress stream |
| `POST /api/jobs/{job_id}/cancel` | Terminate a queued or running Blender job cleanly |
| `GET /api/jobs/{job_id}/result` | Job record paired with the verified `AssetRecord` |
| `GET /api/assets` | Persistent asset library history |
| `GET /api/assets/{asset_id}` | Complete metadata, measured mesh statistics, rig details, and validation report |
| `GET /api/assets/{asset_id}/download` | Download `.glb` (`?format=glb`), `.blend` (`?format=blend`), or `metadata.json` (`?format=metadata`) |
| `POST /api/validate` | Upload any `.glb` binary for standalone glTF + Trimesh geometry validation |

---

## Repository Structure

```text
├── backend/
│   ├── main.py                 # FastAPI routes, SSE/WebSocket streams, security & static serving
│   ├── config.py               # Environment settings & resource bounds
│   ├── schemas.py              # Strict Pydantic v2 validation schemas
│   ├── database.py             # SQLite (WAL) / PostgreSQL persistence for jobs & asset library
│   ├── generator/              # Procedural asset generators (humanoid, architecture, environment, props)
│   ├── blender/                # Subprocess supervisor, headless runner, PBR materials, Geometry Nodes
│   ├── integrations/           # Capability Registry & optional tool adapters (Rigify, LoopTools, Bool Tool, MPFB, Trimesh, PyMeshLab, Open3D)
│   ├── validation/             # Multi-backend mesh, skin-weight, & binary GLB validator
│   ├── jobs/                   # Async background worker pool & GitHub Actions Mode A dispatcher
│   └── storage/                # Path-safe persistent artifact storage & S3/CDN URL builder
├── frontend/                   # React + TypeScript + Vite + Three.js / React Three Fiber 3D Studio
├── presets/                    # 17 JSON presets across humanoid, architecture, environment, and props
├── examples/                   # Sample API generation payloads
├── scripts/                    # Blender runtime bootstrapper, smoke test, and standalone CLI generator
├── tests/                      # Automated E2E pytest suite + real Blender GLB test fixture
├── .github/workflows/          # Workflow A (`ci.yml`) and Workflow B (`generate-asset.yml`)
└── docs/                       # Detailed architecture, Godot 4 import, and deployment guides
```

See [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) and [`docs/DEPLOYMENT.md`](docs/DEPLOYMENT.md) for in-depth architecture, security, Mode A vs Mode B deployment, and Godot 4 Android integration details.
