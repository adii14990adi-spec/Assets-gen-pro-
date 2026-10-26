"""Asynchronous Background Job Queue & Worker Supervisor for Blender Generation.

Supports:
- Mode B (`live`): Local/remote bounded async worker pool running Blender in isolated subprocesses.
- Mode A (`github_actions`): Authorized `workflow_dispatch` trigger against `.github/workflows/generate-asset.yml`.
- Real-time progress streaming to SSE and WebSocket subscribers.
- Retries for transient runtime failures, timeouts, cancellation, and post-export verification.
"""

from __future__ import annotations

import asyncio
import json
import uuid
from datetime import UTC, datetime
from typing import Any

import httpx

from backend.blender.runtime import run_blender_generation_job
from backend.config import Settings, get_settings
from backend.database import StudioRepository
from backend.enums import ExecutionMode, JobStatus
from backend.generator.catalog import validate_and_merge_parameters
from backend.schemas import AssetRecord, GenerateAssetRequest, JobProgressEntry, JobRecord
from backend.storage.store import ArtifactStorage
from backend.validation.validator import validate_generated_asset


class JobManager:
    """Coordinates background Blender generation jobs, retries, cancellation, and live pubsub."""

    def __init__(
        self,
        repository: StudioRepository,
        storage: ArtifactStorage,
        settings: Settings | None = None,
    ) -> None:
        self._repo = repository
        self._storage = storage
        self._settings = settings or get_settings()
        self._queue: asyncio.Queue[str] = asyncio.Queue()
        self._workers: list[asyncio.Task[None]] = []
        self._cancel_events: dict[str, asyncio.Event] = {}
        self._subscribers: dict[str, set[asyncio.Queue[dict[str, Any]]]] = {}
        self._started = False

    async def start(self) -> None:
        if self._started:
            return
        self._started = True
        for idx in range(self._settings.max_concurrent_jobs):
            task = asyncio.create_task(self._worker_loop(idx), name=f"blender-worker-{idx}")
            self._workers.append(task)

    async def stop(self) -> None:
        if not self._started:
            return
        self._started = False
        for ev in self._cancel_events.values():
            ev.set()
        for task in self._workers:
            task.cancel()
        await asyncio.gather(*self._workers, return_exceptions=True)
        self._workers.clear()

    @property
    def active_count(self) -> int:
        return sum(1 for j in self._repo.list_jobs(limit=20) if j.status == JobStatus.RUNNING)

    @property
    def queued_count(self) -> int:
        return self._queue.qsize()

    def subscribe(self, job_id: str) -> asyncio.Queue[dict[str, Any]]:
        q: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=64)
        self._subscribers.setdefault(job_id, set()).add(q)
        return q

    def unsubscribe(self, job_id: str, q: asyncio.Queue[dict[str, Any]]) -> None:
        subs = self._subscribers.get(job_id)
        if subs:
            subs.discard(q)
            if not subs:
                self._subscribers.pop(job_id, None)

    def _broadcast(self, job: JobRecord) -> None:
        subs = self._subscribers.get(job.id)
        if not subs:
            return
        payload = job.model_dump(mode="json")
        for q in list(subs):
            try:
                if q.full():
                    _ = q.get_nowait()
                q.put_nowait(payload)
            except Exception:
                pass

    def _append_log(self, job: JobRecord, stage: str, pct: int, message: str) -> None:
        now = datetime.now(UTC)
        job.stage = stage
        job.progress_pct = max(0, min(100, int(pct)))
        job.message = message
        job.logs.append(JobProgressEntry(timestamp=now, stage=stage, progress_pct=job.progress_pct, message=message))
        self._repo.upsert_job(job)
        self._broadcast(job)

    async def enqueue_generation(self, req: GenerateAssetRequest) -> JobRecord:
        # Validate parameters eagerly before queueing so invalid configs return 422 immediately!
        merged_params, resolved_budget, preset = validate_and_merge_parameters(
            category=req.category,
            preset_id=req.preset_id,
            quality_profile=req.quality_profile,
            user_params=req.parameters,
            explicit_budget=req.polygon_budget,
        )
        normalized_req = req.model_copy(
            update={
                "name": req.name or preset.name,
                "polygon_budget": resolved_budget,
                "material_preset": req.material_preset if req.material_preset != "default" else preset.material_preset,
                "parameters": merged_params,
            }
        )

        job_id = f"job_{uuid.uuid4().hex[:12]}"
        now = datetime.now(UTC)
        job = JobRecord(
            id=job_id,
            status=JobStatus.QUEUED,
            execution_mode=normalized_req.execution_mode,
            stage="queued",
            progress_pct=2,
            message="Job validated and queued for Blender execution.",
            request=normalized_req,
            created_at=now,
            logs=[
                JobProgressEntry(
                    timestamp=now,
                    stage="queued",
                    progress_pct=2,
                    message=f"Queued {preset.name} ({normalized_req.quality_profile.value}, seed={normalized_req.seed}).",
                )
            ],
        )
        self._cancel_events[job_id] = asyncio.Event()
        self._repo.upsert_job(job)
        self._broadcast(job)
        await self._queue.put(job_id)
        return job

    async def cancel_job(self, job_id: str) -> JobRecord | None:
        job = self._repo.get_job(job_id)
        if job is None:
            return None
        if job.status in (JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.CANCELLED):
            return job
        ev = self._cancel_events.get(job_id)
        if ev:
            ev.set()
        job.status = JobStatus.CANCELLED
        job.completed_at = datetime.now(UTC)
        self._append_log(job, "cancelled", job.progress_pct, "Job cancelled by user request.")
        return job

    async def _worker_loop(self, _worker_index: int) -> None:
        while self._started:
            job_id = await self._queue.get()
            try:
                await self._execute_job(job_id)
            finally:
                self._queue.task_done()
                self._cancel_events.pop(job_id, None)

    async def _dispatch_github_workflow(self, job: JobRecord) -> str:
        """Mode A: Trigger authorized GitHub Actions `workflow_dispatch` run via server-side token."""
        token = self._settings.github_dispatch_token.strip()
        if not token:
            raise RuntimeError(
                "Mode A (GitHub Actions dispatch) requires GITHUB_DISPATCH_TOKEN to be configured on the backend server. "
                "Switch execution mode to 'Live Generation Service' (Mode B) or set GITHUB_DISPATCH_TOKEN in .env."
            )
        url = (
            f"https://api.github.com/repos/{self._settings.github_repository}"
            f"/actions/workflows/{self._settings.github_workflow_id}/dispatches"
        )
        headers = {
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        body = {
            "ref": self._settings.github_ref,
            "inputs": {
                "category": job.request.category.value,
                "preset": job.request.preset_id,
                "quality_profile": job.request.quality_profile.value,
                "seed": str(job.request.seed),
                "save_blend": "true" if job.request.save_blend else "false",
            },
        }
        async with httpx.AsyncClient(timeout=20.0) as client:
            resp = await client.post(url, headers=headers, json=body)
            if resp.status_code not in (200, 201, 204):
                raise RuntimeError(
                    f"GitHub Actions workflow_dispatch returned HTTP {resp.status_code}: {resp.text[:300]}"
                )
        return f"https://github.com/{self._settings.github_repository}/actions/workflows/{self._settings.github_workflow_id}"

    async def _execute_job(self, job_id: str) -> None:
        job = self._repo.get_job(job_id)
        if job is None or job.status == JobStatus.CANCELLED:
            return
        cancel_ev = self._cancel_events.get(job_id)
        if cancel_ev and cancel_ev.is_set():
            return

        job.status = JobStatus.RUNNING
        job.started_at = datetime.now(UTC)
        self._append_log(job, "starting", 5, "Worker acquired job; preparing isolated workspace...")

        # Optional Mode A workflow_dispatch notification alongside or before generation
        if job.execution_mode == ExecutionMode.GITHUB_ACTIONS:
            try:
                self._append_log(job, "github_dispatch", 10, "Triggering GitHub Actions workflow_dispatch...")
                actions_url = await self._dispatch_github_workflow(job)
                job.external_run_url = actions_url
                self._append_log(
                    job,
                    "github_dispatched",
                    15,
                    f"Dispatched GitHub Actions workflow ({actions_url}); generating verifiable local preview artifact in parallel...",
                )
            except Exception as exc:
                job.status = JobStatus.FAILED
                job.completed_at = datetime.now(UTC)
                job.error = str(exc)
                self._append_log(job, "failed", job.progress_pct, f"Mode A dispatch error: {exc}")
                return

        max_attempts = 1 + self._settings.max_retries
        last_error: str | None = None

        for attempt in range(1, max_attempts + 1):
            if cancel_ev and cancel_ev.is_set():
                job.status = JobStatus.CANCELLED
                job.completed_at = datetime.now(UTC)
                self._append_log(job, "cancelled", job.progress_pct, "Job cancelled during execution.")
                return

            workdir = self._storage.create_job_workdir(f"{job_id}_try{attempt}")
            asset_id = f"ast_{job.request.preset_id}_{job.request.seed}_{uuid.uuid4().hex[:8]}"

            try:
                cfg_payload = {
                    "job_id": job.id,
                    "asset_id": asset_id,
                    "asset_name": job.request.name or job.request.preset_id,
                    "category": job.request.category.value,
                    "preset_id": job.request.preset_id,
                    "quality_profile": job.request.quality_profile.value,
                    "seed": job.request.seed,
                    "polygon_budget": job.request.polygon_budget or 4000,
                    "material_preset": job.request.material_preset,
                    "save_blend": job.request.save_blend,
                    "parameters": job.request.parameters,
                }
                cfg_path = workdir / "job_config.json"
                cfg_path.write_text(json.dumps(cfg_payload, indent=2), encoding="utf-8")

                def _on_blender_progress(stage: str, pct: int, msg: str) -> None:
                    scaled_pct = min(90, max(12, int(pct * 0.88)))
                    self._append_log(job, stage, scaled_pct, msg)

                blender_res = await run_blender_generation_job(
                    job_config_path=cfg_path,
                    output_dir=workdir,
                    on_progress=_on_blender_progress,
                    cancel_event=cancel_ev,
                    settings=self._settings,
                )

                self._append_log(job, "validating", 93, "Running independent Trimesh & GLB binary validation...")
                glb_temp_path = workdir / blender_res["glb_filename"]
                if not glb_temp_path.exists() or glb_temp_path.stat().st_size == 0:
                    raise RuntimeError("Output GLB file missing or empty after Blender execution.")

                stats, validation = validate_generated_asset(
                    glb_path=glb_temp_path,
                    blender_payload=blender_res,
                    category=job.request.category,
                    polygon_budget=job.request.polygon_budget or 4000,
                    max_output_bytes=self._settings.max_output_bytes,
                )
                if not validation.valid:
                    raise RuntimeError(f"Generated GLB failed validation: {'; '.join(validation.errors)}")

                now = datetime.now(UTC)
                asset_record = AssetRecord(
                    id=asset_id,
                    job_id=job.id,
                    name=job.request.name or job.request.preset_id,
                    category=job.request.category,
                    preset_id=job.request.preset_id,
                    quality_profile=job.request.quality_profile,
                    seed=job.request.seed,
                    polygon_budget=job.request.polygon_budget or 4000,
                    material_preset=job.request.material_preset,
                    parameters=job.request.parameters,
                    created_at=now,
                    glb_filename=blender_res["glb_filename"],
                    glb_size_bytes=int(blender_res["glb_size_bytes"]),
                    glb_download_url=self._storage.build_download_url(asset_id, "glb"),
                    blend_filename=blender_res.get("blend_filename"),
                    blend_size_bytes=blender_res.get("blend_size_bytes"),
                    blend_download_url=(
                        self._storage.build_download_url(asset_id, "blend")
                        if blender_res.get("blend_filename")
                        else None
                    ),
                    metadata_download_url=self._storage.build_download_url(asset_id, "metadata"),
                    capabilities_used=list(blender_res.get("capabilities_used", [])),
                    capabilities_fallback=list(blender_res.get("capabilities_fallback", [])),
                    blender_version=str(blender_res.get("blender_version", "")),
                    generation_time_seconds=float(blender_res.get("generation_time_seconds", 0.0)),
                    stats=stats,
                    validation=validation,
                )

                meta_filename = f"{asset_id}_metadata.json"
                (workdir / meta_filename).write_text(asset_record.model_dump_json(indent=2), encoding="utf-8")

                files_to_store = [blender_res["glb_filename"], meta_filename]
                if blender_res.get("blend_filename"):
                    files_to_store.append(blender_res["blend_filename"])

                self._storage.promote_job_outputs(asset_id, workdir, files_to_store)
                # Double-check persisted GLB exists and is readable before marking job COMPLETED!
                persisted_glb = self._storage.resolve_asset_file(asset_id, blender_res["glb_filename"])
                if persisted_glb.stat().st_size != int(blender_res["glb_size_bytes"]):
                    raise RuntimeError("Persisted GLB byte size mismatch.")

                self._repo.save_asset(asset_record)
                job.asset_id = asset_id
                job.status = JobStatus.COMPLETED
                job.completed_at = datetime.now(UTC)
                job.error = None
                self._append_log(
                    job,
                    "completed",
                    100,
                    f"Verified {asset_record.glb_filename} ({asset_record.glb_size_bytes:,} bytes, {stats.actual_triangles:,} triangles).",
                )
                return

            except asyncio.CancelledError:
                job.status = JobStatus.CANCELLED
                job.completed_at = datetime.now(UTC)
                self._append_log(job, "cancelled", job.progress_pct, "Generation cancelled.")
                return
            except Exception as exc:
                last_error = str(exc)
                job.retry_count = attempt - 1
                if attempt < max_attempts:
                    self._append_log(
                        job,
                        "retrying",
                        15,
                        f"Attempt {attempt} encountered error ({exc}); retrying ({attempt + 1}/{max_attempts})...",
                    )
                    await asyncio.sleep(0.5)
                else:
                    job.status = JobStatus.FAILED
                    job.completed_at = datetime.now(UTC)
                    job.error = last_error
                    self._append_log(job, "failed", job.progress_pct, f"Generation failed: {last_error}")
            finally:
                self._storage.cleanup_job_workdir(f"{job_id}_try{attempt}")
