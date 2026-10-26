# syntax=docker/dockerfile:1
# =============================================================================
# Procedural 3D Asset Generator Studio — production container
# -----------------------------------------------------------------------------
# Stages:
#   frontend-build   Node 22 build of the React Three Fiber studio
#   blender-runtime  Isolated headless Blender 4.2 LTS (`bpy==4.2.23`) venv
#                    created by the SAME bootstrapper used in CI
#                    (scripts/setup_blender_runtime.py)
#   runtime-base     Python 3.11-slim FastAPI service + built frontend
#   runtime-lite     Blender-free image (pure-Python NumPy+Trimesh engine)
#                    -> `docker build --target runtime-lite -t assets-lite .`
#   runtime          DEFAULT final image: runtime-base + Blender 4.2 LTS
#
# The web process never imports `bpy`; Blender runs in isolated
# subprocesses. When the Blender runtime is absent (runtime-lite, or
# STUDIO_GENERATION_ENGINE=python), generation transparently uses the
# pure-Python fallback engine.
# =============================================================================

# ---------------------------------------------------------------------------
# 1. Frontend build
# ---------------------------------------------------------------------------
FROM node:22-bookworm-slim AS frontend-build
WORKDIR /build/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

# ---------------------------------------------------------------------------
# 2. Isolated headless Blender 4.2 LTS runtime (bpy wheel, cp311)
# ---------------------------------------------------------------------------
FROM python:3.11.11-slim-bookworm AS blender-runtime
# OpenGL/X11 client libraries required by the `bpy` shared libraries, plus
# gcc/binutils so the bootstrapper can synthesize stubs for anything still
# missing (mirrors the GitHub Actions environment).
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        libgl1 libopengl0 libglx0 libglu1-mesa libxrender1 libxi6 \
        libxkbcommon0 libsm6 libice6 libxxf86vm1 libxfixes3 libxt6 libxrandr2 \
        gcc binutils ca-certificates \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /opt/setup
COPY scripts/setup_blender_runtime.py ./scripts/setup_blender_runtime.py
# Add-ons are skipped for a deterministic, network-light image build;
# LoopTools/Bool Tool have analytical fallbacks and are reported honestly
# by the capability registry. Remove --skip-addons to fetch them from the
# official Blender add-ons repository at build time.
RUN python scripts/setup_blender_runtime.py \
        --runtime-dir /opt/blender-runtime \
        --backend-venv /nonexistent \
        --skip-addons

# ---------------------------------------------------------------------------
# 3. Application runtime base (Python 3.11-slim)
# ---------------------------------------------------------------------------
FROM python:3.11.11-slim-bookworm AS runtime-base
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    STUDIO_GENERATION_ENGINE=auto \
    PORT=8000

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        libgl1 libopengl0 libglx0 libglu1-mesa libxrender1 libxi6 \
        libxkbcommon0 libsm6 libice6 libxxf86vm1 libxfixes3 libxt6 libxrandr2 \
        curl ca-certificates \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --system appuser \
    && useradd --system --gid appuser --home /app appuser

WORKDIR /app

# Binary wheels only in practice: every pin ships a cp311 wheel, and
# --prefer-binary guarantees pip never falls back to a source build
# (which would need gcc/gfortran for numpy/scipy).
COPY requirements.txt ./
RUN pip install --upgrade pip setuptools wheel \
    && pip install --prefer-binary -r requirements.txt

COPY backend/ ./backend/
COPY presets/ ./presets/
COPY app.py main.py ./
COPY --from=frontend-build /build/frontend/dist ./frontend/dist

RUN mkdir -p /app/storage_data && chown -R appuser:appuser /app

USER appuser
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD curl -fsS "http://127.0.0.1:${PORT:-8000}/api/health" >/dev/null || exit 1

CMD ["sh", "-c", "uvicorn app:app --host 0.0.0.0 --port ${PORT:-8000}"]

# ---------------------------------------------------------------------------
# 4a. Lite image: no Blender — pure-Python fallback engine only
# ---------------------------------------------------------------------------
FROM runtime-base AS runtime-lite

# ---------------------------------------------------------------------------
# 4b. Default image: full dual-engine service with Blender 4.2 LTS
# ---------------------------------------------------------------------------
FROM runtime-base AS runtime
COPY --from=blender-runtime --chown=appuser:appuser /opt/blender-runtime /opt/blender-runtime
ENV BLENDER_PYTHON_EXECUTABLE=/opt/blender-runtime/bin/python \
    BLENDER_HEADLESS_LIBS=/opt/blender-runtime/headless-libs
