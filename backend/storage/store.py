"""Persistent artifact storage layer with path-traversal protection and S3/CDN URL support."""

from __future__ import annotations

import pathlib
import re
import shutil

from backend.config import Settings, get_settings

SAFE_ID_RE = re.compile(r"^[A-Za-z0-9_-]{3,80}$")


class StorageSecurityError(PermissionError):
    """Raised on path traversal or invalid artifact identifier attempts."""


class ArtifactStorage:
    """Manages durable GLB, BLEND, and JSON metadata files on disk (with optional CDN base URL)."""

    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()
        self._root = self._settings.resolved_storage_dir
        self._assets_dir = (self._root / "assets").resolve()
        self._jobs_tmp_dir = (self._root / "jobs_tmp").resolve()
        self._assets_dir.mkdir(parents=True, exist_ok=True)
        self._jobs_tmp_dir.mkdir(parents=True, exist_ok=True)

    @property
    def assets_dir(self) -> pathlib.Path:
        return self._assets_dir

    def validate_id(self, identifier: str) -> str:
        if not SAFE_ID_RE.match(identifier):
            raise StorageSecurityError(f"Unsafe or malformed identifier: {identifier!r}")
        return identifier

    def create_job_workdir(self, job_id: str) -> pathlib.Path:
        safe_job = self.validate_id(job_id)
        workdir = (self._jobs_tmp_dir / safe_job).resolve()
        if not str(workdir).startswith(str(self._jobs_tmp_dir)):
            raise StorageSecurityError("Job workdir escaped storage root.")
        workdir.mkdir(parents=True, exist_ok=True)
        return workdir

    def cleanup_job_workdir(self, job_id: str) -> None:
        try:
            safe_job = self.validate_id(job_id)
            workdir = (self._jobs_tmp_dir / safe_job).resolve()
            if workdir.exists() and str(workdir).startswith(str(self._jobs_tmp_dir)):
                shutil.rmtree(workdir, ignore_errors=True)
        except Exception:
            pass

    def promote_job_outputs(
        self,
        asset_id: str,
        job_workdir: pathlib.Path,
        filenames: list[str],
    ) -> pathlib.Path:
        """Move verified artifacts from temporary job directory into persistent asset directory."""
        safe_asset = self.validate_id(asset_id)
        dest_dir = (self._assets_dir / safe_asset).resolve()
        if not str(dest_dir).startswith(str(self._assets_dir)):
            raise StorageSecurityError("Asset destination escaped storage root.")
        dest_dir.mkdir(parents=True, exist_ok=True)

        for fname in filenames:
            if "/" in fname or "\\" in fname or ".." in fname:
                raise StorageSecurityError(f"Unsafe artifact filename: {fname!r}")
            src = (job_workdir / fname).resolve()
            if not src.exists() or not str(src).startswith(str(job_workdir.resolve())):
                raise FileNotFoundError(f"Expected artifact missing in job workdir: {fname}")
            if src.stat().st_size > self._settings.max_output_bytes:
                raise ValueError(
                    f"Artifact {fname} ({src.stat().st_size} bytes) exceeds limit ({self._settings.max_output_bytes} bytes)."
                )
            shutil.copy2(src, dest_dir / fname)

        return dest_dir

    def resolve_asset_file(self, asset_id: str, filename: str) -> pathlib.Path:
        safe_asset = self.validate_id(asset_id)
        if "/" in filename or "\\" in filename or ".." in filename or "\x00" in filename:
            raise StorageSecurityError(f"Invalid artifact filename: {filename!r}")
        asset_dir = (self._assets_dir / safe_asset).resolve()
        target = (asset_dir / filename).resolve()
        if not str(target).startswith(str(self._assets_dir)):
            raise StorageSecurityError("Resolved file path escaped assets root.")
        if not target.exists() or not target.is_file():
            raise FileNotFoundError(f"Artifact file not found: {asset_id}/{filename}")
        return target

    def delete_asset_files(self, asset_id: str) -> None:
        safe_asset = self.validate_id(asset_id)
        asset_dir = (self._assets_dir / safe_asset).resolve()
        if asset_dir.exists() and str(asset_dir).startswith(str(self._assets_dir)):
            shutil.rmtree(asset_dir, ignore_errors=True)

    def build_download_url(self, asset_id: str, fmt: str = "glb") -> str:
        safe_asset = self.validate_id(asset_id)
        base = self._settings.public_storage_base_url.rstrip("/")
        if base and fmt == "glb":
            return f"{base}/{safe_asset}/{safe_asset}.glb"
        return f"/api/assets/{safe_asset}/download?format={fmt}"
