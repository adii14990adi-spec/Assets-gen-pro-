# Deployment & Operations Guide

## Critical Architectural Distinction: GitHub Actions vs Live Application Server

**GitHub Actions is an ephemeral CI/CD runner, not an always-on FastAPI web server.**
Accordingly, Procedural 3D Asset Generator Studio supports two complementary operating modes:

---

## Mode A: Controlled Asynchronous Generation via GitHub Actions

Suitable when hosting a lightweight static viewer (e.g. GitHub Pages) or triggering curated batch asset builds without maintaining an always-on GPU/CPU worker:

1. **Direct Manual Dispatch on GitHub**:
   - Navigate to **Actions → Generate 3D Asset (Manual Blender Dispatch) → Run workflow**.
   - Choose `category`, `preset`, `quality_profile`, `seed`, `material_preset`, and `save_blend`.
   - The runner installs Python 3.11 + isolated Blender 4.2.23 LTS, generates the 3D asset via `scripts/cli_generate.py`, validates the exported `.glb`, writes a full mesh & validation report to the GitHub Step Summary, and uploads the `.glb`, `.blend`, and `metadata.json` via `actions/upload-artifact@v4`.
2. **Server-Authorized Dispatch (`STUDIO_OPERATING_MODE=github_actions`)**:
   - Keep `GITHUB_DISPATCH_TOKEN` strictly on the backend server (`.env`), **never** in frontend bundle code.
   - Protect dispatch endpoints with `STUDIO_API_KEY` (`X-API-Key` header) so anonymous internet visitors cannot trigger unbounded workflow runs or gain repository write access.
   - For durable public hosting beyond GitHub Actions' artifact retention window (default 30 days), add an S3 / Cloudflare R2 upload step at the end of `generate-asset.yml` and set `STUDIO_PUBLIC_STORAGE_BASE_URL` to your bucket's public CDN URL.

---

## Mode B: Live Interactive Generation Service (Recommended for Interactive Studio)

Required for real-time, interactive parameter tweaking and sub-second/multi-second generation directly in the web viewport:

1. **Host Requirements**:
   - Linux x86_64 VM or container (2+ vCPU, 4+ GB RAM, Python 3.11, Node 22 for build).
   - Either standalone Blender 4.2 LTS (`BLENDER_EXECUTABLE=/usr/bin/blender`) OR the isolated headless Blender runtime created by `python scripts/setup_blender_runtime.py` (`BLENDER_PYTHON_EXECUTABLE=/opt/blender-runtime/bin/python`).
2. **Single-Container / VM Production Start**:
   ```bash
   # 1. Build static frontend into frontend/dist
   cd frontend && npm ci && npm run build && cd ..

   # 2. Prepare Python venv & isolated Blender runtime
   python3.11 -m venv .venv
   .venv/bin/pip install -r requirements.txt
   .venv/bin/python scripts/setup_blender_runtime.py --runtime-dir /opt/blender-runtime

   # 3. Launch FastAPI serving both /api/* and frontend/dist
   export BLENDER_PYTHON_EXECUTABLE=/opt/blender-runtime/bin/python
   export STUDIO_STORAGE_DIR=/var/lib/asset-studio/storage_data
   export STUDIO_DATABASE_URL=sqlite:////var/lib/asset-studio/studio.sqlite3
   .venv/bin/uvicorn backend.main:app --host 0.0.0.0 --port 8000 --workers 1
   ```
   *(Note: Use `--workers 1` with `STUDIO_MAX_CONCURRENT_JOBS=2..4` when using in-process `asyncio.Queue`, or point `STUDIO_DATABASE_URL` to PostgreSQL and S3/R2 object storage when scaling across multiple worker nodes.)*
3. **Independent Frontend + Backend Hosting**:
   - Build the frontend with `VITE_API_BASE_URL=https://your-blender-api.example.com npm run build` and deploy `frontend/dist` to GitHub Pages, Cloudflare Pages, or Vercel while FastAPI + Blender runs on your compute instance.

---

## Security Controls Implemented

- **Zero Arbitrary Code Execution**: `POST /api/generate` accepts only strictly typed Pydantic v2 fields (`extra="forbid"`), regex-validated preset IDs, and range-checked numeric/enum parameters. User-supplied Python scripts or shell arguments are never accepted.
- **Path Traversal Prevention**: `ArtifactStorage` validates all job and asset IDs against `^[A-Za-z0-9_-]{3,80}$` and verifies `.resolve()` remains strictly inside `storage_data/`.
- **Process Isolation & Resource Bounds**: Blender runs in its own POSIX process group (`os.setsid`) with `RLIMIT_CPU`, wall-clock timeouts (`STUDIO_JOB_TIMEOUT_SECONDS`), process-group termination on cancellation, and bounded output/upload byte caps (`STUDIO_MAX_OUTPUT_BYTES`, `STUDIO_MAX_UPLOAD_BYTES`).
- **Token Protection**: Privileged actions (`DELETE /api/assets/{id}` and Mode A workflow dispatches) enforce `X-API-Key` when `STUDIO_API_KEY` is configured, and `GITHUB_DISPATCH_TOKEN` is never exposed to browser clients.

---

## Mode C: Render (Free Tier) — Native Python & Docker

### Python version pinning (fixes `gfortran` source-build failures)

Render selects its newest Python (3.14+) when the version is unpinned. At that
version, `numpy`/`scipy` pins that lack pre-compiled wheels are built from
source and fail with `ERROR: Unknown compiler(s): [['gfortran']]`. This repo
pins **Python 3.11.11** in four places so every deploy path agrees:

| Location | Value |
| --- | --- |
| `.python-version` | `3.11.11` |
| `runtime.txt` | `python-3.11.11` |
| `render.yaml` env | `PYTHON_VERSION: "3.11.11"` |
| `pyproject.toml` | `requires-python = ">=3.11,<3.13"` |

`requirements.txt` uses wheel-safe ranges (`numpy>=1.26.4,<2.2.0`,
`scipy>=1.11.4,<1.16.0`, `trimesh>=4.0.0,<5.0.0`, `fastapi>=0.115.0`,
`uvicorn[standard]>=0.34.0`, …). CI proves `pip install --only-binary=:all:`
succeeds, so no compiler is ever needed at install time. `pymeshlab` and
`open3d` are optional runtime-probed accelerators kept in
`requirements-optional.txt` (their Qt/OpenGL stacks break slim deploys).

### Render Native Python (Blueprint)

`render.yaml` provisions a free web service with:

- **Build**: `pip install --upgrade pip setuptools wheel && pip install --prefer-binary -r requirements.txt`
- **Start**: `uvicorn app:app --host 0.0.0.0 --port $PORT` (`uvicorn main:app` and `uvicorn backend.main:app` also work — root `app.py`/`main.py` both re-export the same FastAPI app)
- **Health check**: `GET /api/health` → `{"status": "ok", "generation_engine": "python_fallback", …}`

Because the Render Python runtime ships no `blender` binary, the
**dual-engine dispatcher** (`backend/blender/runtime.py`,
`STUDIO_GENERATION_ENGINE=auto`) routes generation to the pure-Python
NumPy+Trimesh engine (`backend/fallback/`). It procedurally builds all 17
presets (characters, Rajasthani architecture, closed-solid terrain, props),
decimates to the requested polygon budget via deterministic vertex
clustering, facets flat-shaded normals, assigns triplanar UVs + per-face
vertex colors + named PBR materials, and serializes a binary glTF 2.0
`.glb` that passes the same independent validator as Blender output.
Blender-only extras are reported honestly in `capabilities_fallback`:
humanoids are static A-pose meshes (no armature skinning) and no native
`.blend` file is produced (`blend_filename: null`, download returns 404).

If `frontend/dist` is not built, `GET /` serves a **self-contained fallback
Three.js studio** (`backend/fallback_ui.py`) with preset selection, live
generation progress, an orbitable GLB viewport, mesh stats, library, and
downloads — so a bare `pip install` deploy is fully usable.

Free-tier caveats: ~512 MB RAM (blueprint sets `STUDIO_MAX_CONCURRENT_JOBS=1`),
cold starts after inactivity, and an **ephemeral filesystem** — assets in
`storage_data/` reset on restart. Attach a persistent disk (paid) or publish
GLBs to S3/R2 via `STUDIO_PUBLIC_STORAGE_BASE_URL` for durable hosting.

### Render Docker (full Blender engine)

The production `Dockerfile` is multi-stage:

1. `frontend-build` — Node 22 builds the React Three Fiber studio.
2. `blender-runtime` — Python 3.11-slim + OpenGL/X11 libs; runs
   `scripts/setup_blender_runtime.py` to create the isolated headless
   **Blender 4.2 LTS** (`bpy==4.2.23`) venv at `/opt/blender-runtime`.
3. `runtime-base` → `runtime` (default) — FastAPI + built frontend +
   Blender runtime; `BLENDER_PYTHON_EXECUTABLE` points at the isolated
   venv, so auto-detection selects the Blender/BMesh/Geometry Nodes
   pipeline (skinned humanoids + `.blend` exports included).
4. `runtime-lite` (`--target runtime-lite`) — the same service without
   Blender, for fast/small deploys on the Python fallback engine.

To deploy via the blueprint, switch the service to the commented Docker
block in `render.yaml` (or create a Docker web service in the dashboard).
Expect a large first build (~2 GB image); the free tier build is slow but
cached afterwards, and CI verifies the `runtime-lite` image end-to-end.

### GitHub Pages (optional static frontend)

`actions/configure-pages` returns `HttpError: Not Found — Get Pages site
failed` until Pages is enabled **once** in repository settings:
**Settings → Pages → Build and deployment → Source: GitHub Actions**.
The CI `pages` job treats that state as a warning, not a failure
(`continue-on-error` on the configure step + job, deploy steps gated on
its outcome), so build/test jobs stay green either way. After enabling
Pages, pushes to `main` publish the frontend under
`https://<owner>.github.io/<repo>/`; set the repository variable
`PAGES_API_BASE_URL` to your live backend (e.g. the Render URL) so the
static studio can reach the generation API.
