"""SQLAlchemy 2.0 persistent database repository for jobs and generated 3D assets.

Defaults to SQLite (WAL mode) under `storage_data/studio.sqlite3` with a zero-change
migration path to PostgreSQL via `STUDIO_DATABASE_URL=postgresql+psycopg://...`.
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from sqlalchemy import (
    Column,
    Float,
    Integer,
    MetaData,
    String,
    Table,
    Text,
    create_engine,
    desc,
    event,
    select,
)
from sqlalchemy.engine import Engine

from backend.config import Settings, get_settings
from backend.schemas import (
    AssetCategory,
    AssetRecord,
    ExecutionMode,
    GenerateAssetRequest,
    JobProgressEntry,
    JobRecord,
    JobStatus,
    MeshStats,
    QualityProfile,
    ValidationReport,
)

metadata_obj = MetaData()

jobs_table = Table(
    "jobs",
    metadata_obj,
    Column("id", String(64), primary_key=True),
    Column("status", String(24), nullable=False, index=True),
    Column("execution_mode", String(24), nullable=False),
    Column("stage", String(48), nullable=False),
    Column("progress_pct", Integer, nullable=False),
    Column("message", Text, nullable=False),
    Column("request_json", Text, nullable=False),
    Column("created_at", String(40), nullable=False, index=True),
    Column("started_at", String(40), nullable=True),
    Column("completed_at", String(40), nullable=True),
    Column("retry_count", Integer, nullable=False, default=0),
    Column("asset_id", String(64), nullable=True, index=True),
    Column("error", Text, nullable=True),
    Column("logs_json", Text, nullable=False),
    Column("external_run_url", Text, nullable=True),
)

assets_table = Table(
    "assets",
    metadata_obj,
    Column("id", String(64), primary_key=True),
    Column("job_id", String(64), nullable=False, index=True),
    Column("name", String(120), nullable=False),
    Column("category", String(32), nullable=False, index=True),
    Column("preset_id", String(64), nullable=False, index=True),
    Column("quality_profile", String(32), nullable=False),
    Column("seed", Integer, nullable=False),
    Column("polygon_budget", Integer, nullable=False),
    Column("material_preset", String(48), nullable=False),
    Column("parameters_json", Text, nullable=False),
    Column("created_at", String(40), nullable=False, index=True),
    Column("glb_filename", String(128), nullable=False),
    Column("glb_size_bytes", Integer, nullable=False),
    Column("glb_download_url", Text, nullable=False),
    Column("blend_filename", String(128), nullable=True),
    Column("blend_size_bytes", Integer, nullable=True),
    Column("blend_download_url", Text, nullable=True),
    Column("metadata_download_url", Text, nullable=False),
    Column("capabilities_used_json", Text, nullable=False),
    Column("capabilities_fallback_json", Text, nullable=False),
    Column("blender_version", String(48), nullable=False),
    Column("generation_time_seconds", Float, nullable=False),
    Column("stats_json", Text, nullable=False),
    Column("validation_json", Text, nullable=False),
)


class StudioRepository:
    """Thread-safe SQLAlchemy repository persisting jobs and generated assets."""

    def __init__(self, settings: Settings | None = None) -> None:
        cfg = settings or get_settings()
        if cfg.database_url and not cfg.database_url.startswith("sqlite"):
            db_url = cfg.database_url
            connect_args: dict[str, Any] = {}
        else:
            db_path = cfg.resolved_database_path
            db_path.parent.mkdir(parents=True, exist_ok=True)
            db_url = f"sqlite:///{db_path}"
            connect_args = {"check_same_thread": False, "timeout": 30}

        self._engine: Engine = create_engine(db_url, connect_args=connect_args, future=True)
        if db_url.startswith("sqlite"):

            @event.listens_for(self._engine, "connect")
            def _set_sqlite_pragma(dbapi_conn: Any, _conn_record: Any) -> None:
                cursor = dbapi_conn.cursor()
                cursor.execute("PRAGMA journal_mode=WAL")
                cursor.execute("PRAGMA synchronous=NORMAL")
                cursor.close()

        metadata_obj.create_all(self._engine)

    @property
    def engine(self) -> Engine:
        return self._engine

    def upsert_job(self, job: JobRecord) -> None:
        values = {
            "id": job.id,
            "status": job.status.value,
            "execution_mode": job.execution_mode.value,
            "stage": job.stage,
            "progress_pct": job.progress_pct,
            "message": job.message,
            "request_json": job.request.model_dump_json(),
            "created_at": job.created_at.isoformat(),
            "started_at": job.started_at.isoformat() if job.started_at else None,
            "completed_at": job.completed_at.isoformat() if job.completed_at else None,
            "retry_count": job.retry_count,
            "asset_id": job.asset_id,
            "error": job.error,
            "logs_json": json.dumps([e.model_dump(mode="json") for e in job.logs]),
            "external_run_url": job.external_run_url,
        }
        with self._engine.begin() as conn:
            existing = conn.execute(select(jobs_table.c.id).where(jobs_table.c.id == job.id)).first()
            if existing:
                conn.execute(jobs_table.update().where(jobs_table.c.id == job.id).values(**values))
            else:
                conn.execute(jobs_table.insert().values(**values))

    def get_job(self, job_id: str) -> JobRecord | None:
        with self._engine.connect() as conn:
            row = conn.execute(select(jobs_table).where(jobs_table.c.id == job_id)).mappings().first()
            if not row:
                return None
            return self._row_to_job(dict(row))

    def list_jobs(self, limit: int = 30) -> list[JobRecord]:
        with self._engine.connect() as conn:
            rows = (
                conn.execute(select(jobs_table).order_by(desc(jobs_table.c.created_at)).limit(limit))
                .mappings()
                .all()
            )
            return [self._row_to_job(dict(r)) for r in rows]

    def save_asset(self, asset: AssetRecord) -> None:
        values = {
            "id": asset.id,
            "job_id": asset.job_id,
            "name": asset.name,
            "category": asset.category.value,
            "preset_id": asset.preset_id,
            "quality_profile": asset.quality_profile.value,
            "seed": asset.seed,
            "polygon_budget": asset.polygon_budget,
            "material_preset": asset.material_preset,
            "parameters_json": json.dumps(asset.parameters),
            "created_at": asset.created_at.isoformat(),
            "glb_filename": asset.glb_filename,
            "glb_size_bytes": asset.glb_size_bytes,
            "glb_download_url": asset.glb_download_url,
            "blend_filename": asset.blend_filename,
            "blend_size_bytes": asset.blend_size_bytes,
            "blend_download_url": asset.blend_download_url,
            "metadata_download_url": asset.metadata_download_url,
            "capabilities_used_json": json.dumps(asset.capabilities_used),
            "capabilities_fallback_json": json.dumps(asset.capabilities_fallback),
            "blender_version": asset.blender_version,
            "generation_time_seconds": asset.generation_time_seconds,
            "stats_json": asset.stats.model_dump_json(),
            "validation_json": asset.validation.model_dump_json(),
        }
        with self._engine.begin() as conn:
            existing = conn.execute(select(assets_table.c.id).where(assets_table.c.id == asset.id)).first()
            if existing:
                conn.execute(assets_table.update().where(assets_table.c.id == asset.id).values(**values))
            else:
                conn.execute(assets_table.insert().values(**values))

    def get_asset(self, asset_id: str) -> AssetRecord | None:
        with self._engine.connect() as conn:
            row = conn.execute(select(assets_table).where(assets_table.c.id == asset_id)).mappings().first()
            if not row:
                return None
            return self._row_to_asset(dict(row))

    def list_assets(
        self,
        category: AssetCategory | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[AssetRecord]:
        stmt = select(assets_table)
        if category is not None:
            stmt = stmt.where(assets_table.c.category == category.value)
        stmt = stmt.order_by(desc(assets_table.c.created_at)).limit(limit).offset(offset)
        with self._engine.connect() as conn:
            rows = conn.execute(stmt).mappings().all()
            return [self._row_to_asset(dict(r)) for r in rows]

    def delete_asset(self, asset_id: str) -> bool:
        with self._engine.begin() as conn:
            res = conn.execute(assets_table.delete().where(assets_table.c.id == asset_id))
            return bool(res.rowcount and res.rowcount > 0)

    @staticmethod
    def _row_to_job(row: dict[str, Any]) -> JobRecord:
        logs_raw = json.loads(row["logs_json"]) if row.get("logs_json") else []
        return JobRecord(
            id=row["id"],
            status=JobStatus(row["status"]),
            execution_mode=ExecutionMode(row["execution_mode"]),
            stage=row["stage"],
            progress_pct=int(row["progress_pct"]),
            message=row["message"],
            request=GenerateAssetRequest.model_validate_json(row["request_json"]),
            created_at=datetime.fromisoformat(row["created_at"]),
            started_at=datetime.fromisoformat(row["started_at"]) if row.get("started_at") else None,
            completed_at=datetime.fromisoformat(row["completed_at"]) if row.get("completed_at") else None,
            retry_count=int(row.get("retry_count", 0)),
            asset_id=row.get("asset_id"),
            error=row.get("error"),
            logs=[JobProgressEntry.model_validate(item) for item in logs_raw],
            external_run_url=row.get("external_run_url"),
        )

    @staticmethod
    def _row_to_asset(row: dict[str, Any]) -> AssetRecord:
        return AssetRecord(
            id=row["id"],
            job_id=row["job_id"],
            name=row["name"],
            category=AssetCategory(row["category"]),
            preset_id=row["preset_id"],
            quality_profile=QualityProfile(row["quality_profile"]),
            seed=int(row["seed"]),
            polygon_budget=int(row["polygon_budget"]),
            material_preset=row["material_preset"],
            parameters=json.loads(row["parameters_json"]),
            created_at=datetime.fromisoformat(row["created_at"]),
            glb_filename=row["glb_filename"],
            glb_size_bytes=int(row["glb_size_bytes"]),
            glb_download_url=row["glb_download_url"],
            blend_filename=row.get("blend_filename"),
            blend_size_bytes=int(row["blend_size_bytes"]) if row.get("blend_size_bytes") is not None else None,
            blend_download_url=row.get("blend_download_url"),
            metadata_download_url=row["metadata_download_url"],
            capabilities_used=json.loads(row["capabilities_used_json"]),
            capabilities_fallback=json.loads(row["capabilities_fallback_json"]),
            blender_version=row["blender_version"],
            generation_time_seconds=float(row["generation_time_seconds"]),
            stats=MeshStats.model_validate_json(row["stats_json"]),
            validation=ValidationReport.model_validate_json(row["validation_json"]),
        )
