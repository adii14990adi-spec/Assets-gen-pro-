#!/usr/bin/env python3
"""Controlled Blender background script for procedural 3D asset generation & GLB export.

IMPORTANT: This script runs EXCLUSIVELY inside Blender's Python runtime (`blender --background`
or the isolated `bpy==4.2.23` Python 3.11 runtime), never inside the FastAPI web process.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import pathlib
import sys
import time
import traceback
from collections import deque
from typing import Any


def _emit_progress(stage: str, pct: int, message: str) -> None:
    payload = {"stage": stage, "pct": int(pct), "message": message}
    print(f"STUDIO_PROGRESS:{json.dumps(payload)}", flush=True)


def _clean_exit(code: int) -> None:
    sys.stdout.flush()
    sys.stderr.flush()
    exe_name = os.path.basename(sys.executable).lower()
    if "python" in exe_name:
        os._exit(code)
    sys.exit(code)


def _parse_cli_args() -> argparse.Namespace:
    argv = sys.argv[1:]
    if "--" in argv:
        argv = argv[argv.index("--") + 1 :]
    parser = argparse.ArgumentParser(description="Blender background runner")
    parser.add_argument("--probe-capabilities", action="store_true")
    parser.add_argument("--config", type=pathlib.Path)
    parser.add_argument("--output-dir", type=pathlib.Path)
    return parser.parse_args(argv)


def _count_connected_components(bm: Any) -> int:
    if not bm.verts:
        return 0
    visited: set[int] = set()
    components = 0
    bm.verts.ensure_lookup_table()
    for v in bm.verts:
        if v.index in visited:
            continue
        components += 1
        queue = deque([v])
        visited.add(v.index)
        while queue:
            cur = queue.popleft()
            for edge in cur.link_edges:
                other = edge.other_vert(cur)
                if other.index not in visited:
                    visited.add(other.index)
                    queue.append(other)
    return components


def _inspect_blender_scene(category: str) -> dict[str, Any]:
    """Measure exact geometry, materials, UVs, transforms, normals, manifoldness, and rigging."""
    import bmesh  # type: ignore[import-not-found]
    import bpy  # type: ignore[import-not-found]
    from mathutils import Vector  # type: ignore[import-not-found]

    mesh_objs = [o for o in bpy.context.scene.objects if o.type == "MESH"]
    arm_objs = [o for o in bpy.context.scene.objects if o.type == "ARMATURE"]

    total_tris = 0
    total_verts = 0
    total_polys = 0
    total_uv_layers = 0
    all_have_uvs = len(mesh_objs) > 0
    degenerate_faces = 0
    invalid_face_indices = 0
    non_manifold_edges = 0
    duplicate_vert_candidates = 0
    unapplied_transforms: list[str] = []
    missing_material_meshes: list[str] = []
    connected_components_total = 0
    body_connected_components = 0

    min_pt = [float("inf"), float("inf"), float("inf")]
    max_pt = [float("-inf"), float("-inf"), float("-inf")]

    unique_materials: dict[str, Any] = {}
    unique_textures: set[str] = set()

    for obj in mesh_objs:
        mesh = obj.data
        mesh.calc_loop_triangles()
        total_tris += len(mesh.loop_triangles)
        total_verts += len(mesh.vertices)
        total_polys += len(mesh.polygons)

        uv_n = len(mesh.uv_layers)
        total_uv_layers += uv_n
        if uv_n == 0:
            all_have_uvs = False

        # Check object scale & rotation
        sx, sy, sz = obj.scale
        if any(abs(s_val - 1.0) > 1e-3 for s_val in (sx, sy, sz)) or any(s_val <= 0 for s_val in (sx, sy, sz)):
            unapplied_transforms.append(f"{obj.name}: scale=({sx:.3f},{sy:.3f},{sz:.3f})")

        # Check materials
        valid_mats = [m for m in mesh.materials if m is not None]
        if not valid_mats:
            missing_material_meshes.append(obj.name)
        for m in valid_mats:
            unique_materials[m.name] = m

        # World-space bounding box
        mw = obj.matrix_world
        for v in mesh.vertices:
            wco: Vector = mw @ v.co
            for axis in range(3):
                if wco[axis] < min_pt[axis]:
                    min_pt[axis] = float(wco[axis])
                if wco[axis] > max_pt[axis]:
                    max_pt[axis] = float(wco[axis])

        # Validate face indices
        n_v = len(mesh.vertices)
        for poly in mesh.polygons:
            for vi in poly.vertices:
                if vi < 0 or vi >= n_v:
                    invalid_face_indices += 1

        # BMesh topology checks
        bm = bmesh.new()
        bm.from_mesh(mesh)
        comps = _count_connected_components(bm)
        connected_components_total += comps
        if obj.name.endswith("_Body"):
            body_connected_components = comps

        for f in bm.faces:
            if f.calc_area() < 1e-10:
                degenerate_faces += 1
        for e in bm.edges:
            if not e.is_manifold:
                non_manifold_edges += 1

        # Check duplicate coincident vertices without mutating mesh
        dup_bm = bm.copy()
        before_v = len(dup_bm.verts)
        bmesh.ops.remove_doubles(dup_bm, verts=dup_bm.verts[:], dist=1e-6)
        duplicate_vert_candidates += max(0, before_v - len(dup_bm.verts))
        dup_bm.free()
        bm.free()

    if min_pt[0] == float("inf"):
        min_pt = [0.0, 0.0, 0.0]
        max_pt = [0.0, 0.0, 0.0]

    # Summarize materials & embedded textures
    material_summaries: list[dict[str, Any]] = []
    for mat_name, mat in unique_materials.items():
        base_col = (0.8, 0.8, 0.8, 1.0)
        metallic = 0.0
        roughness = 0.5
        tex_names: list[str] = []
        if mat.use_nodes and mat.node_tree:
            for node in mat.node_tree.nodes:
                if node.type == "BSDF_PRINCIPLED":
                    bc = node.inputs["Base Color"].default_value
                    base_col = (round(float(bc[0]), 4), round(float(bc[1]), 4), round(float(bc[2]), 4), round(float(bc[3]), 4))
                    metallic = round(float(node.inputs["Metallic"].default_value), 4)
                    roughness = round(float(node.inputs["Roughness"].default_value), 4)
                elif node.type == "TEX_IMAGE" and node.image is not None:
                    tex_names.append(node.image.name)
                    unique_textures.add(node.image.name)
        material_summaries.append(
            {
                "name": mat_name,
                "base_color": base_col,
                "metallic": metallic,
                "roughness": roughness,
                "has_textures": len(tex_names) > 0,
                "texture_names": tex_names,
            }
        )

    # Summarize armature & verify skin weights
    rig_info: dict[str, Any] = {
        "has_armature": False,
        "armature_name": None,
        "bone_count": 0,
        "bone_names": [],
        "root_bones": [],
        "skinned_mesh_count": 0,
        "normalized_weights_verified": False,
        "max_influences_per_vertex": 0,
        "animation_clips": [],
        "unweighted_vertices": 0,
        "unnormalized_vertices": 0,
    }
    if arm_objs:
        arm = arm_objs[0]
        bones = list(arm.data.bones)
        root_bones = [b.name for b in bones if b.parent is None]
        bone_name_set = {b.name for b in bones}
        skinned_count = 0
        max_inf = 0
        unweighted = 0
        unnormalized = 0

        for m_obj in mesh_objs:
            has_arm_mod = any(mod.type == "ARMATURE" and mod.object == arm for mod in m_obj.modifiers)
            if not has_arm_mod:
                continue
            skinned_count += 1
            vg_index_to_bone = {vg.index: vg.name for vg in m_obj.vertex_groups if vg.name in bone_name_set}
            for v in m_obj.data.vertices:
                weights = [g.weight for g in v.groups if g.group in vg_index_to_bone and g.weight > 1e-6]
                max_inf = max(max_inf, len(weights))
                if not weights:
                    unweighted += 1
                else:
                    w_sum = sum(weights)
                    if abs(w_sum - 1.0) > 1e-2:
                        unnormalized += 1

        clips = [act.name for act in bpy.data.actions]
        rig_info = {
            "has_armature": True,
            "armature_name": arm.name,
            "bone_count": len(bones),
            "bone_names": [b.name for b in bones],
            "root_bones": root_bones,
            "skinned_mesh_count": skinned_count,
            "normalized_weights_verified": (skinned_count > 0 and unweighted == 0 and unnormalized == 0 and max_inf <= 4),
            "max_influences_per_vertex": max_inf,
            "animation_clips": clips,
            "unweighted_vertices": unweighted,
            "unnormalized_vertices": unnormalized,
        }

    dims = (
        round(max_pt[0] - min_pt[0], 4),
        round(max_pt[2] - min_pt[2], 4),  # Height (Z in Blender -> Y in glTF!)
        round(max_pt[1] - min_pt[1], 4),  # Depth (Y in Blender -> Z in glTF!)
    )
    center = (
        round((min_pt[0] + max_pt[0]) * 0.5, 4),
        round((min_pt[2] + max_pt[2]) * 0.5, 4),
        round((min_pt[1] + max_pt[1]) * 0.5, 4),
    )
    diag = round(math.sqrt(dims[0] ** 2 + dims[1] ** 2 + dims[2] ** 2), 4)

    return {
        "category": category,
        "mesh_count": len(mesh_objs),
        "actual_triangles": total_tris,
        "actual_vertices": total_verts,
        "polygon_faces": total_polys,
        "material_count": len(unique_materials),
        "texture_count": len(unique_textures),
        "connected_components": connected_components_total,
        "body_connected_components": body_connected_components,
        "uv_layer_count": total_uv_layers,
        "has_uvs": all_have_uvs,
        "degenerate_faces": degenerate_faces,
        "invalid_face_indices": invalid_face_indices,
        "non_manifold_edges": non_manifold_edges,
        "duplicate_vert_candidates": duplicate_vert_candidates,
        "unapplied_transforms": unapplied_transforms,
        "missing_material_meshes": missing_material_meshes,
        "bounding_box": {
            "min_corner": (round(min_pt[0], 4), round(min_pt[2], 4), round(-max_pt[1], 4)),
            "max_corner": (round(max_pt[0], 4), round(max_pt[2], 4), round(-min_pt[1], 4)),
            "dimensions": dims,
            "center": center,
            "diagonal": diag,
        },
        "materials": material_summaries,
        "rig": rig_info,
    }


def _run_generation(config_path: pathlib.Path, output_dir: pathlib.Path) -> int:
    import bpy  # type: ignore[import-not-found]

    from backend.enums import AssetCategory, QualityProfile
    from backend.generator.architecture import generate_architecture_asset
    from backend.generator.base import GenerationContext
    from backend.generator.environment import generate_environment_asset
    from backend.generator.humanoid import generate_humanoid_asset
    from backend.generator.props import generate_prop_asset
    from backend.integrations.blender_addons import activate_capabilities_for_category

    t0 = time.perf_counter()
    output_dir.mkdir(parents=True, exist_ok=True)
    result_path = output_dir / "blender_result.json"

    try:
        cfg = json.loads(config_path.read_text(encoding="utf-8"))
        _emit_progress("initializing", 8, f"Initializing Blender {bpy.app.version_string} scene...")
        bpy.ops.wm.read_factory_settings(use_empty=True)

        category_str = str(cfg["category"])
        used_caps, fallback_caps, _ = activate_capabilities_for_category(category_str)
        _emit_progress(
            "capabilities",
            18,
            f"Activated capabilities for {category_str}: {', '.join(used_caps)}",
        )

        ctx = GenerationContext(
            job_id=str(cfg["job_id"]),
            asset_name=str(cfg["asset_name"]),
            category=AssetCategory(category_str),
            preset_id=str(cfg["preset_id"]),
            quality_profile=QualityProfile(str(cfg["quality_profile"])),
            seed=int(cfg["seed"]),
            polygon_budget=int(cfg["polygon_budget"]),
            material_preset=str(cfg.get("material_preset", "default")),
            parameters=dict(cfg.get("parameters", {})),
            capabilities_available=set(used_caps),
        )

        _emit_progress("geometry", 35, f"Generating procedural {ctx.category.value} geometry ({ctx.preset_id})...")
        if ctx.category == AssetCategory.PROPS:
            created = generate_prop_asset(ctx)
        elif ctx.category == AssetCategory.ARCHITECTURE:
            created = generate_architecture_asset(ctx)
        elif ctx.category == AssetCategory.ENVIRONMENT:
            created = generate_environment_asset(ctx)
        elif ctx.category == AssetCategory.HUMANOID:
            created = generate_humanoid_asset(ctx)
        else:
            raise ValueError(f"Unsupported asset category: {ctx.category}")

        if not created:
            raise RuntimeError("Generator produced zero scene objects.")

        _emit_progress("inspecting", 62, "Measuring topology, normals, UVs, materials, and armature weights...")
        scene_diag = _inspect_blender_scene(category_str)

        glb_filename = f"{cfg['asset_id']}.glb"
        glb_path = output_dir / glb_filename
        _emit_progress("exporting_glb", 76, "Exporting glTF 2.0 binary (.glb) for Godot 4...")
        bpy.ops.export_scene.gltf(
            filepath=str(glb_path),
            export_format="GLB",
            export_yup=True,
            export_apply=False,
            export_texcoords=True,
            export_normals=True,
            export_materials="EXPORT",
            export_skins=True,
            export_animations=True,
        )

        if not glb_path.exists() or glb_path.stat().st_size < 128:
            raise RuntimeError("Blender glTF exporter did not produce a valid GLB file.")

        blend_filename: str | None = None
        if bool(cfg.get("save_blend", False)):
            blend_filename = f"{cfg['asset_id']}.blend"
            blend_path = output_dir / blend_filename
            _emit_progress("saving_blend", 86, "Saving native Blender (.blend) project file...")
            bpy.ops.wm.save_as_mainfile(filepath=str(blend_path), compress=True)

        # Verify GLB roundtrip re-import into a clean Blender scene!
        _emit_progress("verifying_reimport", 93, "Re-importing exported GLB to verify roundtrip integrity...")
        bpy.ops.wm.read_factory_settings(use_empty=True)
        bpy.ops.import_scene.gltf(filepath=str(glb_path))
        # Re-imports into Blender create helper bone-display meshes in collection "glTF_not_exported"
        not_exported_objs = set()
        if "glTF_not_exported" in bpy.data.collections:
            not_exported_objs = set(bpy.data.collections["glTF_not_exported"].all_objects)
        reimported_meshes = [
            o for o in bpy.context.scene.objects if o.type == "MESH" and o not in not_exported_objs
        ]
        reimported_arms = [o for o in bpy.context.scene.objects if o.type == "ARMATURE"]
        reimport_tris = 0
        for ro in reimported_meshes:
            ro.data.calc_loop_triangles()
            reimport_tris += len(ro.data.loop_triangles)

        reimport_ok = len(reimported_meshes) >= 1 and reimport_tris == scene_diag["actual_triangles"]
        if scene_diag["rig"]["has_armature"]:
            reimport_ok = reimport_ok and len(reimported_arms) >= 1

        elapsed = round(time.perf_counter() - t0, 3)
        result_payload = {
            "success": True,
            "blender_version": bpy.app.version_string,
            "generation_time_seconds": elapsed,
            "glb_filename": glb_filename,
            "glb_size_bytes": glb_path.stat().st_size,
            "blend_filename": blend_filename,
            "blend_size_bytes": (output_dir / blend_filename).stat().st_size if blend_filename else None,
            "capabilities_used": used_caps,
            "capabilities_fallback": fallback_caps,
            "scene_diagnostics": scene_diag,
            "reimport_check": {
                "passed": reimport_ok,
                "reimported_mesh_count": len(reimported_meshes),
                "reimported_triangles": reimport_tris,
                "reimported_armature_count": len(reimported_arms),
            },
        }
        result_path.write_text(json.dumps(result_payload, indent=2), encoding="utf-8")
        _emit_progress("completed", 100, f"Generated {scene_diag['actual_triangles']:,} triangles in {elapsed:.2f}s.")
        return 0

    except Exception as exc:
        err_payload = {
            "success": False,
            "error": f"{type(exc).__name__}: {exc}",
            "traceback": traceback.format_exc(),
        }
        result_path.write_text(json.dumps(err_payload, indent=2), encoding="utf-8")
        print(f"ERROR: {exc}", file=sys.stderr, flush=True)
        return 1


def main() -> None:
    args = _parse_cli_args()
    if args.probe_capabilities:
        from backend.integrations.blender_addons import probe_blender_capabilities_in_blender

        caps = probe_blender_capabilities_in_blender()
        print("STUDIO_CAPABILITIES_JSON:" + json.dumps(caps), flush=True)
        _clean_exit(0)

    if not args.config or not args.output_dir:
        print("ERROR: --config and --output-dir are required.", file=sys.stderr)
        _clean_exit(2)

    rc = _run_generation(args.config.resolve(), args.output_dir.resolve())
    _clean_exit(rc)


if __name__ == "__main__":
    main()
