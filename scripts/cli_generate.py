#!/usr/bin/env python3
"""Command-line procedural 3D asset generator & validator (CI, workflow_dispatch, local CLI).

Dual-engine: uses Blender 4.2 LTS when detected, otherwise the pure-Python
NumPy+Trimesh fallback engine. Force an engine with `--engine` or the
`STUDIO_GENERATION_ENGINE` environment variable.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import pathlib
import sys
import uuid

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from backend.blender.runtime import run_blender_generation_job  # noqa: E402
from backend.generator.catalog import validate_and_merge_parameters  # noqa: E402
from backend.schemas import AssetCategory, QualityProfile  # noqa: E402
from backend.validation.validator import validate_generated_asset  # noqa: E402


async def _run_cli(args: argparse.Namespace) -> int:
    if args.engine:
        os.environ["STUDIO_GENERATION_ENGINE"] = args.engine
    category = AssetCategory(args.category)
    quality = QualityProfile(args.quality)
    user_params = json.loads(args.params) if args.params else {}

    merged_params, resolved_budget, preset = validate_and_merge_parameters(
        category=category,
        preset_id=args.preset,
        quality_profile=quality,
        user_params=user_params,
        explicit_budget=args.budget,
    )

    output_dir = args.output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    asset_id = args.asset_id or f"{args.preset}_{args.seed}_{uuid.uuid4().hex[:6]}"
    job_id = f"cli_{uuid.uuid4().hex[:8]}"

    mat_preset = args.material if args.material != "default" else preset.material_preset
    cfg = {
        "job_id": job_id,
        "asset_id": asset_id,
        "asset_name": args.name or preset.name,
        "category": category.value,
        "preset_id": args.preset,
        "quality_profile": quality.value,
        "seed": args.seed,
        "polygon_budget": resolved_budget,
        "material_preset": mat_preset,
        "save_blend": args.save_blend,
        "parameters": merged_params,
    }
    config_path = output_dir / f"{asset_id}_config.json"
    config_path.write_text(json.dumps(cfg, indent=2), encoding="utf-8")

    def _log_progress(stage: str, pct: int, message: str) -> None:
        print(f"[{pct:3d}% | {stage:<18}] {message}", flush=True)

    blender_result = await run_blender_generation_job(
        job_config_path=config_path,
        output_dir=output_dir,
        on_progress=_log_progress,
    )

    glb_path = output_dir / blender_result["glb_filename"]
    stats, report = validate_generated_asset(
        glb_path=glb_path,
        blender_payload=blender_result,
        category=category,
        polygon_budget=resolved_budget,
    )

    metadata = {
        "asset_id": asset_id,
        "job_id": job_id,
        "name": cfg["asset_name"],
        "category": category.value,
        "preset_id": args.preset,
        "quality_profile": quality.value,
        "seed": args.seed,
        "polygon_budget": resolved_budget,
        "material_preset": mat_preset,
        "parameters": merged_params,
        "blender_version": blender_result["blender_version"],
        "generation_time_seconds": blender_result["generation_time_seconds"],
        "capabilities_used": blender_result["capabilities_used"],
        "capabilities_fallback": blender_result["capabilities_fallback"],
        "glb_filename": blender_result["glb_filename"],
        "glb_size_bytes": blender_result["glb_size_bytes"],
        "blend_filename": blender_result.get("blend_filename"),
        "blend_size_bytes": blender_result.get("blend_size_bytes"),
        "stats": stats.model_dump(mode="json"),
        "validation": report.model_dump(mode="json"),
    }
    meta_path = output_dir / f"{asset_id}_metadata.json"
    meta_path.write_text(json.dumps(metadata, indent=2), encoding="utf-8")

    print(
        f"\nSUCCESS: {glb_path} ({blender_result['glb_size_bytes']:,} bytes) | "
        f"Triangles={stats.actual_triangles:,} | Verts={stats.actual_vertices:,} | "
        f"Meshes={stats.mesh_count} | Materials={stats.material_count} | "
        f"Rigged={stats.rig.has_armature} ({stats.rig.bone_count} bones) | "
        f"Valid={report.valid} (warnings={report.warning_count}, errors={report.error_count})"
    )
    return 0 if report.valid else 2


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate and validate a procedural 3D asset (Blender or Python fallback engine).")
    parser.add_argument("--category", required=True, choices=[c.value for c in AssetCategory])
    parser.add_argument("--preset", required=True)
    parser.add_argument(
        "--quality",
        default=QualityProfile.OPTIMIZED_MID_POLY.value,
        choices=[q.value for q in QualityProfile],
    )
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--budget", type=int, default=None)
    parser.add_argument("--material", default="default")
    parser.add_argument("--name", default=None)
    parser.add_argument("--asset-id", default=None)
    parser.add_argument("--params", default=None, help="Optional JSON object overriding preset parameters")
    parser.add_argument("--save-blend", action="store_true")
    parser.add_argument(
        "--engine",
        default=None,
        choices=["auto", "blender", "python"],
        help="Generation engine (default: STUDIO_GENERATION_ENGINE env or auto-detect)",
    )
    parser.add_argument("--output-dir", type=pathlib.Path, default=pathlib.Path("artifacts_out"))
    args = parser.parse_args()
    return asyncio.run(_run_cli(args))


if __name__ == "__main__":
    raise SystemExit(main())
