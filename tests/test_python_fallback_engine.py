"""Pure-Python fallback engine tests — the Render Native Python guarantee.

These tests prove that EVERY preset produces a valid binary GLB with zero
Blender involvement, that engine selection degrades gracefully when no
Blender runtime exists, and that output is deterministic per seed.
"""

from __future__ import annotations

import importlib.util
import json
import pathlib
import shutil
import struct

import pytest

from backend.blender.runtime import (
    detect_blender_runtime,
    run_generation_job,
    select_generation_engine,
)
from backend.config import Settings
from backend.enums import QualityProfile
from backend.fallback.engine import generate_asset_python
from backend.generator.catalog import list_presets, validate_and_merge_parameters
from backend.validation.validator import validate_generated_asset, validate_standalone_glb


def _job_config(
    tmp_path: pathlib.Path,
    preset_id: str,
    *,
    seed: int = 42,
    quality: QualityProfile = QualityProfile.PROTOTYPE,
) -> tuple[pathlib.Path, pathlib.Path, dict]:
    preset = next(p for p in list_presets() if p.id == preset_id)
    merged, budget, _ = validate_and_merge_parameters(
        category=preset.category,
        preset_id=preset.id,
        quality_profile=quality,
        user_params={},
    )
    out_dir = tmp_path / f"{preset_id}_{quality.value}_{seed}"
    out_dir.mkdir(parents=True, exist_ok=True)
    cfg = {
        "job_id": f"job_{preset_id}",
        "asset_id": f"ast_{preset_id}_{seed}",
        "asset_name": preset.name,
        "category": preset.category.value,
        "preset_id": preset.id,
        "quality_profile": quality.value,
        "seed": seed,
        "polygon_budget": budget,
        "material_preset": preset.material_preset,
        "save_blend": True,
        "parameters": merged,
    }
    cfg_path = out_dir / "config.json"
    cfg_path.write_text(json.dumps(cfg), encoding="utf-8")
    return cfg_path, out_dir, cfg


@pytest.mark.parametrize("preset", list_presets(), ids=lambda p: p.id)
def test_every_preset_generates_valid_glb_without_blender(
    tmp_path: pathlib.Path, preset: object
) -> None:
    cfg_path, out_dir, cfg = _job_config(tmp_path, preset.id)  # type: ignore[attr-defined]
    result = generate_asset_python(cfg_path, out_dir)

    assert result["generation_engine"] == "python_fallback"
    assert result["blend_filename"] is None  # .blend honestly unavailable
    assert "python_fallback_engine" in result["capabilities_used"]
    assert any("blender_core" in fb for fb in result["capabilities_fallback"])

    glb_path = out_dir / result["glb_filename"]
    data = glb_path.read_bytes()
    assert len(data) == result["glb_size_bytes"] > 1_000
    magic, version, total_len = struct.unpack("<III", data[:12])
    assert magic == 0x46546C67 and version == 2 and total_len == len(data)

    # glTF payload must carry flat normals + UVs + vertex colors + PBR mats
    json_len = struct.unpack("<I", data[12:16])[0]
    gltf = json.loads(data[20 : 20 + json_len])
    assert len(gltf.get("materials", [])) >= 3
    for mesh in gltf["meshes"]:
        attrs = mesh["primitives"][0]["attributes"]
        assert {"POSITION", "NORMAL", "TEXCOORD_0", "COLOR_0"} <= set(attrs)

    stats, report = validate_generated_asset(
        glb_path=glb_path,
        blender_payload=result,
        category=preset.category,  # type: ignore[attr-defined]
        polygon_budget=cfg["polygon_budget"],
    )
    assert report.valid is True, report.errors
    assert report.reimport_verified is True
    assert stats.actual_triangles > 100
    assert stats.has_uvs is True

    sa_stats, sa_report = validate_standalone_glb(glb_path)
    assert sa_report.valid is True
    assert sa_stats is not None
    assert sa_stats.actual_triangles == stats.actual_triangles


def test_python_engine_output_is_byte_deterministic(tmp_path: pathlib.Path) -> None:
    cfg1, out1, _ = _job_config(tmp_path / "a", "rajasthani_haveli", seed=1727)
    cfg2, out2, _ = _job_config(tmp_path / "b", "rajasthani_haveli", seed=1727)
    res1 = generate_asset_python(cfg1, out1)
    res2 = generate_asset_python(cfg2, out2)
    assert (out1 / res1["glb_filename"]).read_bytes() == (out2 / res2["glb_filename"]).read_bytes()
    assert (
        res1["scene_diagnostics"]["actual_triangles"]
        == res2["scene_diagnostics"]["actual_triangles"]
    )


def test_engine_selection_falls_back_when_blender_missing(tmp_path: pathlib.Path) -> None:
    if shutil.which("blender") or importlib.util.find_spec("bpy") is not None:
        pytest.skip("A real Blender runtime is available in this environment.")
    settings = Settings(
        STUDIO_GENERATION_ENGINE="auto",
        BLENDER_EXECUTABLE="/nonexistent/blender",
        BLENDER_PYTHON_EXECUTABLE="/nonexistent/blender-python",
        STUDIO_STORAGE_DIR=tmp_path / "storage",
        STUDIO_DATABASE_URL=f"sqlite:///{tmp_path / 'storage' / 't.sqlite3'}",
    )
    available, _label = detect_blender_runtime(settings)
    if available:
        pytest.skip("Blender runtime resolved via a path this test cannot disable.")
    assert select_generation_engine(settings) == "python_fallback"


@pytest.mark.asyncio
async def test_dispatcher_generates_via_python_engine_when_forced(
    tmp_path: pathlib.Path,
) -> None:
    cfg_path, out_dir, _cfg = _job_config(tmp_path, "explosive_fuel_barrel", seed=5)
    settings = Settings(
        STUDIO_GENERATION_ENGINE="python",
        STUDIO_STORAGE_DIR=tmp_path / "storage",
        STUDIO_DATABASE_URL=f"sqlite:///{tmp_path / 'storage' / 't.sqlite3'}",
    )
    result = await run_generation_job(
        job_config_path=cfg_path, output_dir=out_dir, settings=settings
    )
    assert result["generation_engine"] == "python_fallback"
    assert (out_dir / result["glb_filename"]).stat().st_size == result["glb_size_bytes"]
