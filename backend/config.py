"""Centralized configuration for Procedural 3D Asset Generator Studio."""

from __future__ import annotations

import pathlib
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    """Validated runtime settings loaded from environment or .env file."""

    model_config = SettingsConfigDict(
        env_file=str(REPO_ROOT / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "Procedural 3D Asset Generator Studio"
    app_version: str = "1.0.0"

    # Mode B ("live") runs local/worker Blender jobs directly;
    # Mode A ("github_actions") supports authorized GitHub workflow dispatch alongside local artifacts.
    operating_mode: Literal["live", "github_actions"] = Field(
        default="live", validation_alias="STUDIO_OPERATING_MODE"
    )

    # Blender execution paths
    blender_executable: str = Field(default="", validation_alias="BLENDER_EXECUTABLE")
    blender_python_executable: str = Field(
        default=str(pathlib.Path.home() / ".local" / "blender-runtime" / "bin" / "python"),
        validation_alias="BLENDER_PYTHON_EXECUTABLE",
    )
    blender_headless_libs: str = Field(
        default=str(pathlib.Path.home() / ".local" / "blender-runtime" / "headless-libs"),
        validation_alias="BLENDER_HEADLESS_LIBS",
    )
    pymeshlab_headless_libs: str = Field(
        default=str(pathlib.Path.home() / ".local" / "pymeshlab-headless-libs"),
        validation_alias="PYMESHLAB_HEADLESS_LIBS",
    )

    # Worker & resource bounds
    max_concurrent_jobs: int = Field(default=2, ge=1, le=16, validation_alias="STUDIO_MAX_CONCURRENT_JOBS")
    job_timeout_seconds: int = Field(default=180, ge=10, le=900, validation_alias="STUDIO_JOB_TIMEOUT_SECONDS")
    max_retries: int = Field(default=1, ge=0, le=3, validation_alias="STUDIO_MAX_RETRIES")
    max_output_bytes: int = Field(
        default=100 * 1024 * 1024, ge=1024 * 1024, validation_alias="STUDIO_MAX_OUTPUT_BYTES"
    )
    max_upload_bytes: int = Field(
        default=50 * 1024 * 1024, ge=1024 * 1024, validation_alias="STUDIO_MAX_UPLOAD_BYTES"
    )
    subprocess_memory_limit_mb: int = Field(
        default=3072, ge=512, le=16384, validation_alias="STUDIO_SUBPROCESS_MEMORY_MB"
    )

    # Storage & SQLite / PostgreSQL database
    storage_dir: pathlib.Path = Field(
        default=REPO_ROOT / "storage_data", validation_alias="STUDIO_STORAGE_DIR"
    )
    database_url: str = Field(
        default="", validation_alias="STUDIO_DATABASE_URL"
    )
    public_storage_base_url: str = Field(
        default="", validation_alias="STUDIO_PUBLIC_STORAGE_BASE_URL"
    )
    presets_dir: pathlib.Path = Field(default=REPO_ROOT / "presets")

    # Security & optional GitHub Actions Mode A integration
    api_key: str = Field(default="", validation_alias="STUDIO_API_KEY")
    github_repository: str = Field(
        default="adii14990adi-spec/Assets-gen-pro-", validation_alias="GITHUB_REPOSITORY"
    )
    github_workflow_id: str = Field(default="generate-asset.yml", validation_alias="GITHUB_WORKFLOW_ID")
    github_ref: str = Field(default="main", validation_alias="GITHUB_REF")
    github_dispatch_token: str = Field(default="", validation_alias="GITHUB_DISPATCH_TOKEN")

    @property
    def resolved_storage_dir(self) -> pathlib.Path:
        path = self.storage_dir if self.storage_dir.is_absolute() else (REPO_ROOT / self.storage_dir)
        return path.resolve()

    @property
    def resolved_database_path(self) -> pathlib.Path:
        if self.database_url.startswith("sqlite:///"):
            raw = self.database_url.replace("sqlite:///", "", 1)
            p = pathlib.Path(raw)
            return p.resolve() if p.is_absolute() else (REPO_ROOT / p).resolve()
        return self.resolved_storage_dir / "studio.sqlite3"


def get_settings() -> Settings:
    return Settings()
