"""Unit & artifact tests for the standalone GLB & mesh validation suite."""

from __future__ import annotations

import pathlib
import struct

from backend.config import REPO_ROOT
from backend.validation.validator import validate_standalone_glb

FIXTURE_GLB = REPO_ROOT / "tests" / "fixtures" / "real_blender_crate.glb"


def test_validate_real_fixture_glb() -> None:
    assert FIXTURE_GLB.exists()
    stats, report = validate_standalone_glb(FIXTURE_GLB, polygon_budget=1500)
    assert stats is not None
    assert report.valid is True
    assert report.within_budget is True
    assert stats.actual_triangles == 1096
    assert stats.has_uvs is True


def test_validate_detects_corrupted_or_truncated_glb(tmp_path: pathlib.Path) -> None:
    bad_file = tmp_path / "corrupt.glb"
    bad_file.write_bytes(b"NOT_A_GLB_HEADER_AT_ALL_1234567890")
    stats, report = validate_standalone_glb(bad_file)
    assert stats is None
    assert report.valid is False
    assert report.error_count >= 1
    assert any("magic" in e.lower() for e in report.errors)

    # Valid magic + version, but declared length mismatches actual file size
    mismatch = tmp_path / "mismatch.glb"
    mismatch.write_bytes(struct.pack("<IIIII", 0x46546C67, 2, 99999, 8, 0x4E4F534A) + b"{}      ")
    stats2, report2 = validate_standalone_glb(mismatch)
    assert stats2 is None
    assert report2.valid is False
    assert any("length" in e.lower() for e in report2.errors)


def test_validate_flags_budget_warning_without_falsifying_triangle_count() -> None:
    stats, report = validate_standalone_glb(FIXTURE_GLB, polygon_budget=500)
    assert stats is not None
    assert stats.actual_triangles == 1096
    assert report.within_budget is False
    assert report.warning_count >= 1
