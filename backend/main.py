"""FastAPI Application — Procedural 3D Asset Generator Studio.

Exposes validated REST endpoints, Server-Sent Events (SSE), and WebSocket job streams
connecting the interactive React Three Fiber studio to the isolated Blender 4.2 LTS worker.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import pathlib
import tempfile
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Annotated, Any, Literal

from fastapi import (
    Depends,
    FastAPI,
    File,
    Header,
    HTTPException,
    Query,
    UploadFile,
    WebSocket,
    WebSocketDisconnect,
    status,
)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from backend import __version__
from backend.config import REPO_ROOT, Settings, get_settings
from backend.database import StudioRepository
from backend.enums import AssetCategory, ExecutionMode, JobStatus
from backend.generator.base import ParameterValidationError
from backend.generator.catalog import (
    MATERIAL_PRESET_OPTIONS,
    get_preset,
    list_asset_types,
    list_presets,
)
from backend.integrations.registry import CapabilityRegistry
from backend.jobs.manager import JobManager
from backend.schemas import (
    AssetRecord,
    GenerateAssetRequest,
    JobRecord,
    JobResultResponse,
    PresetInfo,
)
from backend.storage.store import ArtifactStorage, StorageSecurityError
from backend.validation.validator import validate_standalone_glb


class AppState:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.storage = ArtifactStorage(settings)
        self.repository = StudioRepository(settings)
        self.capabilities = CapabilityRegistry()
        self.job_manager = JobManager(self.repository, self.storage, settings)


def create_app(custom_settings: Settings | None = None) -> FastAPI:
    cfg = custom_settings or get_settings()
    state = AppState(cfg)

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        await state.job_manager.start()
        try:
            yield
        finally:
            await state.job_manager.stop()

    app = FastAPI(
        title="Procedural 3D Asset Generator Studio",
        version=__version__,
        description=(
            "End-to-end procedural 3D game asset generator using Python, Blender 4.2 LTS, NumPy, "
            "Geometry Nodes, Rigify, and independent GLB validation for Godot 4 Android Battle Royale pipelines."
        ),
        lifespan=lifespan,
    )
    app.state.studio = state

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["ETag", "Content-Disposition", "Content-Length"],
    )

    def _require_privileged_auth(
        x_api_key: Annotated[str | None, Header(alias="X-API-Key")] = None,
    ) -> None:
        expected = state.settings.api_key.strip()
        if expected and x_api_key != expected:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Valid X-API-Key header required for privileged action.",
            )

    @app.exception_handler(StorageSecurityError)
    async def _handle_storage_security(_req: Any, exc: StorageSecurityError) -> JSONResponse:
        return JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            content={"error": "security_violation", "detail": str(exc)},
        )

    @app.exception_handler(ParameterValidationError)
    async def _handle_param_validation(_req: Any, exc: ParameterValidationError) -> JSONResponse:
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            content={"error": "invalid_parameters", "detail": str(exc)},
        )

    @app.get("/api/health")
    async def get_health() -> dict[str, Any]:
        caps = state.capabilities.list_capabilities()
        blender_core = next((c for c in caps if c.id == "blender_core"), None)
        return {
            "status": "ok" if (blender_core and blender_core.available) else "degraded",
            "service": state.settings.app_name,
            "version": __version__,
            "operating_mode": state.settings.operating_mode,
            "github_dispatch_configured": bool(state.settings.github_dispatch_token.strip()),
            "blender_available": bool(blender_core and blender_core.available),
            "blender_version": blender_core.version if blender_core else None,
            "active_jobs": state.job_manager.active_count,
            "queued_jobs": state.job_manager.queued_count,
            "capabilities_verified": sum(1 for c in caps if c.verified),
            "capabilities_total": len(caps),
        }

    @app.get("/api/capabilities")
    async def get_capabilities(refresh: bool = Query(default=False)) -> dict[str, Any]:
        caps = state.capabilities.list_capabilities(force_refresh=refresh)
        by_category = {
            cat.value: {
                "active": [c.id for c in state.capabilities.select_for_category(cat)["active"]],
                "fallback": [c.id for c in state.capabilities.select_for_category(cat)["fallback"]],
            }
            for cat in AssetCategory
        }
        return {
            "capabilities": [c.model_dump(mode="json") for c in caps],
            "category_plan": by_category,
        }

    @app.get("/api/assets/types")
    async def get_asset_types() -> dict[str, Any]:
        return {
            "types": [t.model_dump(mode="json") for t in list_asset_types()],
            "material_presets": [m.model_dump(mode="json") for m in MATERIAL_PRESET_OPTIONS],
            "quality_profiles": [
                {
                    "id": "prototype",
                    "label": "Prototype (Fast Iteration)",
                    "description": "Low-latency blockout & CI verification mesh.",
                },
                {
                    "id": "optimized_mid_poly",
                    "label": "Optimized Mid-Poly (Godot 4 Android)",
                    "description": "Balanced triangle count, smooth normals, and PBR textures for mobile BR.",
                },
                {
                    "id": "detailed_mid_poly",
                    "label": "Detailed Mid-Poly (Hero / Showcase)",
                    "description": "Higher subdivision, chamfered bevels, and rich architectural/character detail.",
                },
            ],
        }

    @app.get("/api/presets", response_model=list[PresetInfo])
    async def get_presets(category: AssetCategory | None = Query(default=None)) -> list[PresetInfo]:
        return list_presets(category=category)

    @app.get("/api/presets/{preset_id}", response_model=PresetInfo)
    async def get_single_preset(preset_id: str) -> PresetInfo:
        preset = get_preset(preset_id)
        if preset is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Preset '{preset_id}' not found.")
        return preset

    @app.post("/api/generate", response_model=JobRecord, status_code=status.HTTP_202_ACCEPTED)
    async def start_generation(
        req: GenerateAssetRequest,
        x_api_key: Annotated[str | None, Header(alias="X-API-Key")] = None,
    ) -> JobRecord:
        if req.execution_mode == ExecutionMode.GITHUB_ACTIONS:
            _require_privileged_auth(x_api_key)
        return await state.job_manager.enqueue_generation(req)

    @app.get("/api/jobs", response_model=list[JobRecord])
    async def list_recent_jobs(limit: int = Query(default=25, ge=1, le=100)) -> list[JobRecord]:
        return state.repository.list_jobs(limit=limit)

    @app.get("/api/jobs/{job_id}", response_model=JobRecord)
    async def get_job_status(job_id: str) -> JobRecord:
        state.storage.validate_id(job_id)
        job = state.repository.get_job(job_id)
        if job is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Job '{job_id}' not found.")
        return job

    @app.post("/api/jobs/{job_id}/cancel", response_model=JobRecord)
    async def cancel_generation_job(job_id: str) -> JobRecord:
        state.storage.validate_id(job_id)
        job = await state.job_manager.cancel_job(job_id)
        if job is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Job '{job_id}' not found.")
        return job

    @app.get("/api/jobs/{job_id}/result", response_model=JobResultResponse)
    async def get_job_result(job_id: str) -> JobResultResponse:
        state.storage.validate_id(job_id)
        job = state.repository.get_job(job_id)
        if job is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Job '{job_id}' not found.")
        asset = state.repository.get_asset(job.asset_id) if job.asset_id else None
        return JobResultResponse(job=job, asset=asset)

    @app.get("/api/jobs/{job_id}/events")
    async def stream_job_events(job_id: str) -> StreamingResponse:
        state.storage.validate_id(job_id)
        initial = state.repository.get_job(job_id)
        if initial is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Job '{job_id}' not found.")

        async def _event_generator() -> AsyncIterator[str]:
            sub_q = state.job_manager.subscribe(job_id)
            try:
                cur = state.repository.get_job(job_id)
                if cur is not None:
                    yield f"data: {cur.model_dump_json()}\n\n"
                    if cur.status in (JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.CANCELLED):
                        return
                while True:
                    try:
                        update = await asyncio.wait_for(sub_q.get(), timeout=15.0)
                        yield f"data: {json.dumps(update)}\n\n"
                        if update.get("status") in ("completed", "failed", "cancelled"):
                            return
                    except TimeoutError:
                        yield ": keepalive\n\n"
            finally:
                state.job_manager.unsubscribe(job_id, sub_q)

        return StreamingResponse(
            _event_generator(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    @app.websocket("/api/jobs/{job_id}/ws")
    async def websocket_job_events(websocket: WebSocket, job_id: str) -> None:
        try:
            state.storage.validate_id(job_id)
        except StorageSecurityError:
            await websocket.close(code=1008)
            return
        job = state.repository.get_job(job_id)
        if job is None:
            await websocket.close(code=1008)
            return
        await websocket.accept()
        sub_q = state.job_manager.subscribe(job_id)
        try:
            await websocket.send_json(job.model_dump(mode="json"))
            if job.status in (JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.CANCELLED):
                return
            while True:
                update = await sub_q.get()
                await websocket.send_json(update)
                if update.get("status") in ("completed", "failed", "cancelled"):
                    return
        except WebSocketDisconnect:
            return
        finally:
            state.job_manager.unsubscribe(job_id, sub_q)

    @app.get("/api/assets", response_model=list[AssetRecord])
    async def list_generated_assets(
        category: AssetCategory | None = Query(default=None),
        limit: int = Query(default=40, ge=1, le=200),
        offset: int = Query(default=0, ge=0),
    ) -> list[AssetRecord]:
        return state.repository.list_assets(category=category, limit=limit, offset=offset)

    @app.get("/api/assets/{asset_id}", response_model=AssetRecord)
    async def get_asset_details(asset_id: str) -> AssetRecord:
        state.storage.validate_id(asset_id)
        asset = state.repository.get_asset(asset_id)
        if asset is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Asset '{asset_id}' not found.")
        return asset

    @app.delete("/api/assets/{asset_id}", dependencies=[Depends(_require_privileged_auth)])
    async def delete_asset_record(asset_id: str) -> dict[str, Any]:
        state.storage.validate_id(asset_id)
        existed = state.repository.delete_asset(asset_id)
        if not existed:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Asset '{asset_id}' not found.")
        state.storage.delete_asset_files(asset_id)
        return {"deleted": True, "asset_id": asset_id}

    @app.get("/api/assets/{asset_id}/download")
    async def download_asset_artifact(
        asset_id: str,
        format: Literal["glb", "blend", "metadata"] = Query(default="glb"),
    ) -> FileResponse:
        state.storage.validate_id(asset_id)
        asset = state.repository.get_asset(asset_id)
        if asset is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Asset '{asset_id}' not found.")

        if format == "glb":
            filename = asset.glb_filename
            media_type = "model/gltf-binary"
        elif format == "blend":
            if not asset.blend_filename:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Native .blend file was not saved for this asset.",
                )
            filename = asset.blend_filename
            media_type = "application/octet-stream"
        else:
            filename = f"{asset.id}_metadata.json"
            media_type = "application/json"

        try:
            file_path = state.storage.resolve_asset_file(asset.id, filename)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc

        etag = hashlib.sha256(f"{asset.id}:{filename}:{file_path.stat().st_size}".encode()).hexdigest()[:24]
        return FileResponse(
            path=file_path,
            media_type=media_type,
            filename=filename,
            headers={"ETag": f'"{etag}"', "Cache-Control": "public, max-age=3600"},
        )

    @app.post("/api/validate")
    async def validate_uploaded_glb(
        file: UploadFile = File(...),
        polygon_budget: int | None = Query(default=None, ge=100, le=500_000),
    ) -> dict[str, Any]:
        if not file.filename or not file.filename.lower().endswith(".glb"):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Uploaded file must have a .glb extension.",
            )

        content = await file.read(state.settings.max_upload_bytes + 1)
        if len(content) > state.settings.max_upload_bytes:
            raise HTTPException(
                status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                detail=f"Uploaded GLB exceeds maximum allowed size ({state.settings.max_upload_bytes:,} bytes).",
            )
        if len(content) == 0:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Uploaded GLB file is empty.")

        with tempfile.TemporaryDirectory(prefix="glb_validate_") as tmpdir:
            tmp_glb = pathlib.Path(tmpdir) / "upload.glb"
            tmp_glb.write_bytes(content)
            stats, report = validate_standalone_glb(
                glb_path=tmp_glb,
                polygon_budget=polygon_budget,
                max_output_bytes=state.settings.max_upload_bytes,
            )
            return {
                "filename": file.filename,
                "size_bytes": len(content),
                "stats": stats.model_dump(mode="json") if stats else None,
                "validation": report.model_dump(mode="json"),
            }

    # Serve production static frontend build if `frontend/dist` exists
    dist_dir = REPO_ROOT / "frontend" / "dist"
    if dist_dir.exists() and (dist_dir / "index.html").exists():
        app.mount("/", StaticFiles(directory=str(dist_dir), html=True), name="frontend")

    return app


app = create_app()
