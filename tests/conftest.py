"""Shared pytest fixtures for isolated storage, SQLite DB, and FastAPI E2E client."""

from __future__ import annotations

import pathlib

import pytest

from backend.config import Settings


@pytest.fixture()
def isolated_settings(tmp_path: pathlib.Path) -> Settings:
    storage_dir = tmp_path / "studio_storage"
    db_path = storage_dir / "test_studio.sqlite3"
    return Settings(
        STUDIO_STORAGE_DIR=storage_dir,
        STUDIO_DATABASE_URL=f"sqlite:///{db_path}",
        STUDIO_MAX_CONCURRENT_JOBS=2,
        STUDIO_JOB_TIMEOUT_SECONDS=120,
        STUDIO_MAX_RETRIES=0,
    )
