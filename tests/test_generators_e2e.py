"""End-to-end tests proving real Blender 3D generation, GLB export, and roundtrip validation
across Props, Modular Rajasthani Architecture, Procedural Terrain, and Rigged Humanoids.
"""

from __future__ import annotations

import json
import pathlib

import pytest
import trimesh

from backend.blender.runtime import run_blender_generation_job
from backend.enums import AssetCategory, QualityProfile
from backend.generator.catalog import validate_and_merge_parameters
from backend.validation.validator import validate_generated_asset


async def _generate_and_validate(
    tmp_path: pathlib.Path,
    category: AssetCategory,
    preset_id: str,
    quality: QualityProfile = QualityProfile.PROTOTYPE,
    seed: int = 42,
    save_blend: bool = False,
    overrides: dict | None = None,
) -> tuple[pathlib.Path, dict, object, object]:
    merged_params, budget, preset = validate_and_merge_parameters(
        category=category,
        preset_id=preset_id,
        quality_profile=quality,
        user_params=overrides or {},
    )
    out_dir = tmp_path / f"{preset_id}_{seed}"
    out_dir.mkdir(parents=True, exist_ok=True)
    asset_id = f"test_{preset_id}_{seed}"
    cfg = {
        "job_id": f"job_{preset_id}",
        "asset_id": asset_id,
        "asset_name": preset.name,
        "category": category.value,
        "preset_id": preset_id,
        "quality_profile": quality.value,
        "seed": seed,
        "polygon_budget": budget,
        "material_preset": preset.material_preset,
        "save_blend": save_blend,
        "parameters": merged_params,
    }
    cfg_file = out_dir / "config.json"
    cfg_file.write_text(json.dumps(cfg), encoding="utf-8")

    blender_res = await run_blender_generation_job(job_config_path=cfg_file, output_dir=out_dir)
    glb_path = out_dir / blender_res["glb_filename"]
    stats, report = validate_generated_asset(
        glb_path=glb_path,
        blender_payload=blender_res,
        category=category,
        polygon_budget=budget,
    )
    return glb_path, blender_res, stats, report


@pytest.mark.asyncio
async def test_generate_prop_and_deterministic_repeatability(tmp_path: pathlib.Path) -> None:
    glb1, res1, stats1, report1 = await _generate_and_validate(
        tmp_path / "run1",
        AssetCategory.PROPS,
        "br_supply_crate",
        QualityProfile.OPTIMIZED_MID_POLY,
        seed=108,
        save_blend=True,
    )
    assert glb1.exists() and glb1.stat().st_size > 10_000
    assert (glb1.parent / res1["blend_filename"]).exists()
    assert report1.valid is True
    assert report1.reimport_verified is True
    assert 300 <= stats1.actual_triangles <= 2500
    assert stats1.material_count >= 3
    assert stats1.has_uvs is True

    # Independent Trimesh scene check (glTF exports 1 primitive per material slot)
    scene = trimesh.load(str(glb1), force="scene", process=False)
    assert len(scene.geometry) >= 1
    assert sum(len(g.faces) for g in scene.geometry.values()) == stats1.actual_triangles

    # Verify deterministic repeatability for identical seed & parameters
    _, _, stats2, report2 = await _generate_and_validate(
        tmp_path / "run2",
        AssetCategory.PROPS,
        "br_supply_crate",
        QualityProfile.OPTIMIZED_MID_POLY,
        seed=108,
    )
    assert report2.valid is True
    assert stats2.actual_triangles == stats1.actual_triangles
    assert stats2.actual_vertices == stats1.actual_vertices
    assert stats2.bounding_box.dimensions == stats1.bounding_box.dimensions


@pytest.mark.asyncio
async def test_generate_rajasthani_architecture_component(tmp_path: pathlib.Path) -> None:
    glb_path, _, stats, report = await _generate_and_validate(
        tmp_path,
        AssetCategory.ARCHITECTURE,
        "rajasthani_haveli",
        QualityProfile.OPTIMIZED_MID_POLY,
        seed=1727,
        overrides={"width": 9.0, "depth": 7.5, "height": 7.0, "floors": 2},
    )
    assert glb_path.exists()
    assert report.valid is True
    assert report.reimport_verified is True
    assert 800 <= stats.actual_triangles <= 10_000
    assert stats.material_count >= 4
    # Verify metric dimensions match configured Haveli footprint + plinth/jharokha overhang
    w, h, d = stats.bounding_box.dimensions
    assert w > 8.5
    assert h > 6.5
    assert d > 7.0


@pytest.mark.asyncio
async def test_generate_procedural_terrain_sample(tmp_path: pathlib.Path) -> None:
    glb_path, _, stats, report = await _generate_and_validate(
        tmp_path,
        AssetCategory.ENVIRONMENT,
        "aravalli_ridge_terrain",
        QualityProfile.PROTOTYPE,
        seed=402,
    )
    assert glb_path.exists()
    assert report.valid is True
    assert report.reimport_verified is True
    assert stats.actual_triangles > 400
    assert stats.has_uvs is True


@pytest.mark.asyncio
async def test_generate_rigged_humanoid_character(tmp_path: pathlib.Path) -> None:
    glb_path, blender_res, stats, report = await _generate_and_validate(
        tmp_path,
        AssetCategory.HUMANOID,
        "athletic_female_scout",
        QualityProfile.PROTOTYPE,
        seed=55,
        overrides={
            "gender": "female",
            "height": 1.70,
            "include_clothing": True,
            "include_shoes": True,
            "include_hair": True,
            "include_backpack": True,
            "include_rig": True,
        },
    )
    assert glb_path.exists()
    assert report.valid is True
    assert report.reimport_verified is True
    assert stats.actual_triangles > 3500
    assert stats.mesh_count >= 5  # Body + Shirt + Trousers + Boots + Hair + Backpack
    assert stats.rig.has_armature is True
    assert stats.rig.bone_count >= 25
    assert stats.rig.normalized_weights_verified is True
    assert stats.rig.max_influences_per_vertex <= 4
    assert "IdleReady" in stats.rig.animation_clips

    # Verify honest fallback reporting when MPFB is not installed
    if "mpfb" not in blender_res["capabilities_used"]:
        assert any("mpfb" in fb for fb in blender_res["capabilities_fallback"])
