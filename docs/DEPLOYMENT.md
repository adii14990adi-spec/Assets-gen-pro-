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
