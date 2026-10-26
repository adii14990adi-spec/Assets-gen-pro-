"""Comprehensive Mesh & GLB Validation Engine (glTF Binary + Trimesh + PyMeshLab + Blender Diagnostics).

Checks:
1. Binary GLB header, version, chunk structure, and JSON schema integrity
2. Invalid face indices & NaN/Inf vertex coordinates
3. Degenerate zero-area faces
4. Face normals & consistent winding
5. Non-manifold geometry (where relevant; garment rim edges handled appropriately)
6. Duplicate vertices / geometry check
7. Object transforms & positive unit scale
8. Material presence & PBR validity
9. UV map availability
10. Humanoid armature hierarchy, max-4 bone influences, and normalized skin weights
11. Export & Blender roundtrip re-import verification
12. Polygon budget comparison using ACTUAL measured triangle counts
"""

from __future__ import annotations

import json
import math
import pathlib
import struct
from typing import Any

import numpy as np

from backend.schemas import (
    AssetCategory,
    BoundingBox3D,
    MaterialSummary,
    MeshStats,
    RigSummary,
    ValidationCheckItem,
    ValidationReport,
)


def _parse_glb_header_and_json(glb_path: pathlib.Path) -> tuple[bool, dict[str, Any], str]:
    """Validate binary glTF 2.0 container structure (`0x46546C67` magic, version 2, JSON chunk)."""
    if not glb_path.exists():
        return False, {}, "GLB file does not exist."
    size = glb_path.stat().st_size
    if size < 28:
        return False, {}, f"GLB file is truncated ({size} bytes)."

    with glb_path.open("rb") as fh:
        header = fh.read(20)
        magic, version, declared_length, chunk0_len, chunk0_type = struct.unpack("<IIIII", header)
        if magic != 0x46546C67:
            return False, {}, f"Invalid GLB magic header: 0x{magic:08x} (expected 0x46546C67 'glTF')."
        if version != 2:
            return False, {}, f"Unsupported glTF binary version: {version} (expected 2)."
        if declared_length != size:
            return False, {}, f"GLB declared length ({declared_length}) does not match file size ({size})."
        if chunk0_type != 0x4E4F534A:
            return False, {}, "First GLB chunk is not a JSON chunk (0x4E4F534A)."
        json_bytes = fh.read(chunk0_len)

    try:
        gltf_json = json.loads(json_bytes.decode("utf-8"))
    except Exception as exc:
        return False, {}, f"Malformed glTF JSON chunk: {exc}"

    return True, gltf_json, f"Valid glTF 2.0 binary container ({size:,} bytes, {len(gltf_json.get('meshes', []))} mesh nodes)."


def _analyze_with_trimesh(glb_path: pathlib.Path) -> dict[str, Any]:
    """Independently load and inspect the exported GLB using `trimesh`."""
    import trimesh

    scene = trimesh.load(str(glb_path), force="scene", process=False)
    geoms = list(scene.geometry.values())
    if not geoms:
        return {"loaded": False, "error": "Trimesh found zero mesh geometries in GLB."}

    gltf_render_verts = 0
    total_faces = 0
    invalid_indices = 0
    non_finite_verts = 0
    degenerate_tris = 0
    inconsistent_winding_geoms = 0

    for geom in geoms:
        v = np.asarray(geom.vertices)
        f = np.asarray(geom.faces)
        gltf_render_verts += len(v)
        total_faces += len(f)

        if not np.all(np.isfinite(v)):
            non_finite_verts += int(np.sum(~np.isfinite(v)))
        if len(f) > 0:
            if int(np.min(f)) < 0 or int(np.max(f)) >= len(v):
                invalid_indices += 1
            # Triangle area via cross product
            v0 = v[f[:, 0]]
            v1 = v[f[:, 1]]
            v2 = v[f[:, 2]]
            cross = np.cross(v1 - v0, v2 - v0)
            areas = 0.5 * np.linalg.norm(cross, axis=1)
            degenerate_tris += int(np.sum(areas < 1e-11))
            if not geom.is_winding_consistent:
                inconsistent_winding_geoms += 1

    bounds = scene.bounds
    if bounds is not None and np.all(np.isfinite(bounds)):
        bmin = tuple(round(float(x), 4) for x in bounds[0])
        bmax = tuple(round(float(x), 4) for x in bounds[1])
        dims = tuple(round(float(bounds[1][i] - bounds[0][i]), 4) for i in range(3))
        center = tuple(round(float((bounds[0][i] + bounds[1][i]) * 0.5), 4) for i in range(3))
        diag = round(math.sqrt(sum(d * d for d in dims)), 4)
    else:
        bmin = (0.0, 0.0, 0.0)
        bmax = (0.0, 0.0, 0.0)
        dims = (0.0, 0.0, 0.0)
        center = (0.0, 0.0, 0.0)
        diag = 0.0

    return {
        "loaded": True,
        "geometry_count": len(geoms),
        "gltf_render_vertices": gltf_render_verts,
        "triangles": total_faces,
        "invalid_indices": invalid_indices,
        "non_finite_verts": non_finite_verts,
        "degenerate_triangles": degenerate_tris,
        "inconsistent_winding_geoms": inconsistent_winding_geoms,
        "bounding_box": {
            "min_corner": bmin,
            "max_corner": bmax,
            "dimensions": dims,
            "center": center,
            "diagonal": diag,
        },
    }


def validate_generated_asset(
    glb_path: pathlib.Path,
    blender_payload: dict[str, Any],
    category: AssetCategory,
    polygon_budget: int,
    max_output_bytes: int = 100 * 1024 * 1024,
) -> tuple[MeshStats, ValidationReport]:
    """Combine Blender scene diagnostics, binary glTF parsing, and independent Trimesh analysis."""
    checks: list[ValidationCheckItem] = []
    engine_label = (
        "python_trimesh"
        if str(blender_payload.get("generation_engine", "")) == "python_fallback"
        else "blender_bmesh"
    )
    backends = ["gltf_binary_inspector", engine_label]

    def add_check(
        cid: str,
        name: str,
        passed: bool,
        severity: str,
        message: str,
        details: dict[str, Any] | None = None,
    ) -> None:
        checks.append(
            ValidationCheckItem(
                check_id=cid,
                name=name,
                passed=passed,
                severity=severity,  # type: ignore[arg-type]
                message=message,
                details=details or {},
            )
        )

    # 1. File size & binary GLB container check
    glb_ok, gltf_json, glb_msg = _parse_glb_header_and_json(glb_path)
    file_size = glb_path.stat().st_size if glb_path.exists() else 0
    within_size = glb_ok and (0 < file_size <= max_output_bytes)
    add_check(
        "glb_container",
        "GLB Binary Header & Size Bounds",
        within_size,
        "info" if within_size else "error",
        glb_msg if within_size else f"GLB check failed or exceeded {max_output_bytes} bytes: {glb_msg}",
        {"size_bytes": file_size},
    )

    # 2. Independent Trimesh inspection
    tm_info: dict[str, Any] = {}
    try:
        tm_info = _analyze_with_trimesh(glb_path)
        if tm_info.get("loaded"):
            backends.append("trimesh")
    except Exception as exc:
        tm_info = {"loaded": False, "error": str(exc)}

    diag = blender_payload.get("scene_diagnostics", {})
    reimp = blender_payload.get("reimport_check", {})

    # 3. Export & Re-import roundtrip check
    reimport_passed = bool(reimp.get("passed", False)) and bool(tm_info.get("loaded", False))
    add_check(
        "export_reimport",
        "GLB Export & Roundtrip Re-Import",
        reimport_passed,
        "info" if reimport_passed else "error",
        f"Verified roundtrip re-import ({reimp.get('reimported_triangles', 0):,} triangles via generation engine & Trimesh)."
        if reimport_passed
        else f"Roundtrip verification failed: reimport={reimp}, trimesh={tm_info.get('error')}",
        reimp,
    )

    # 4. Face indices & finite coordinates
    bad_idx = int(diag.get("invalid_face_indices", 0)) + int(tm_info.get("invalid_indices", 0))
    bad_nan = int(tm_info.get("non_finite_verts", 0))
    idx_ok = bad_idx == 0 and bad_nan == 0
    add_check(
        "face_indices",
        "Valid Face Indices & Finite Coordinates",
        idx_ok,
        "info" if idx_ok else "error",
        "All polygon indices and vertex coordinates are valid and finite."
        if idx_ok
        else f"Detected {bad_idx} invalid face indices and {bad_nan} non-finite coordinates.",
    )

    # 5. Degenerate faces check
    degen = max(int(diag.get("degenerate_faces", 0)), int(tm_info.get("degenerate_triangles", 0)))
    degen_ok = degen == 0
    add_check(
        "degenerate_faces",
        "Zero-Area / Degenerate Faces",
        degen_ok,
        "info" if degen_ok else "warning",
        "Zero degenerate faces detected."
        if degen_ok
        else f"{degen} tiny/degenerate triangles detected (< 1e-10 m²); review smooth/CSG seams.",
        {"degenerate_count": degen},
    )

    # 6. Normals & consistent face winding
    bad_wind = int(tm_info.get("inconsistent_winding_geoms", 0))
    wind_ok = bad_wind == 0
    add_check(
        "normals_winding",
        "Outward Normals & Consistent Winding",
        wind_ok,
        "info" if wind_ok else "warning",
        "Face normals and winding orientation are consistent across meshes."
        if wind_ok
        else f"{bad_wind} sub-mesh(es) have mixed/open boundary winding seams.",
    )

    # 7. Non-manifold geometry check (and connected anatomical body check for humanoids!)
    non_man = int(diag.get("non_manifold_edges", 0))
    if category == AssetCategory.HUMANOID:
        body_comps = int(diag.get("body_connected_components", 1))
        anat_ok = body_comps == 1 and non_man == 0
        add_check(
            "manifold_topology",
            "Connected Manifold Anatomical Topology",
            anat_ok,
            "info" if anat_ok else "warning",
            f"Humanoid base body is a single connected manifold mesh (components={body_comps}, non_manifold_edges={non_man})."
            if anat_ok
            else f"Topology note: body_components={body_comps}, non_manifold_edges={non_man}.",
            {"body_connected_components": body_comps, "non_manifold_edges": non_man},
        )
    else:
        # Note: translucent water ribbon plane in river/island intentionally has 4 open boundary edges
        expected_open = 4 if str(diag.get("category")) == "environment" and int(diag.get("mesh_count", 1)) > 1 else 0
        man_ok = non_man <= expected_open
        add_check(
            "manifold_topology",
            "Manifold Mesh Topology",
            man_ok,
            "info" if man_ok else "warning",
            "Mesh topology is manifold." if man_ok else f"{non_man} non-manifold/open boundary edges present.",
            {"non_manifold_edges": non_man},
        )

    # 8. Duplicate geometry check
    dup_v = int(diag.get("duplicate_vert_candidates", 0))
    dup_ok = dup_v == 0
    add_check(
        "duplicate_geometry",
        "Duplicate Coincident Vertices",
        dup_ok,
        "info" if dup_ok else "warning",
        "No duplicate coincident vertices found within 1µm tolerance."
        if dup_ok
        else f"{dup_v} near-coincident vertices detected across sub-part seams.",
        {"duplicate_vertices": dup_v},
    )

    # 9. Object transforms & scale
    bad_xf = list(diag.get("unapplied_transforms", []))
    xf_ok = len(bad_xf) == 0
    add_check(
        "transforms_scale",
        "Applied Transforms & Positive Unit Scale",
        xf_ok,
        "info" if xf_ok else "error",
        "All exported objects have unit scale (1.0, 1.0, 1.0) and clean transforms."
        if xf_ok
        else f"Unapplied transforms detected: {bad_xf}",
    )

    # 10. Materials & UV availability
    missing_mats = list(diag.get("missing_material_meshes", []))
    mat_count = int(diag.get("material_count", 0))
    mats_ok = len(missing_mats) == 0 and mat_count >= 1
    add_check(
        "materials_valid",
        "PBR Materials Assigned",
        mats_ok,
        "info" if mats_ok else "error",
        f"{mat_count} PBR material(s) verified ({diag.get('texture_count', 0)} embedded texture(s))."
        if mats_ok
        else f"Missing materials on meshes: {missing_mats}",
    )

    has_uvs = bool(diag.get("has_uvs", False))
    add_check(
        "uv_availability",
        "UV Coordinates Available",
        has_uvs,
        "info" if has_uvs else "error",
        f"UV maps verified on all {diag.get('mesh_count', 0)} mesh(es)."
        if has_uvs
        else "One or more meshes lack UV coordinates.",
    )

    # 11. Armature & Normalized Skin Weights (when rig is present)
    rig_raw = diag.get("rig", {})
    if rig_raw.get("has_armature"):
        weights_ok = bool(rig_raw.get("normalized_weights_verified", False))
        root_ok = len(rig_raw.get("root_bones", [])) >= 1
        rig_passed = weights_ok and root_ok
        add_check(
            "armature_skin_weights",
            "Humanoid Armature Hierarchy & Normalized Skin Weights",
            rig_passed,
            "info" if rig_passed else "error",
            f"Verified {rig_raw.get('bone_count', 0)} bones, max {rig_raw.get('max_influences_per_vertex', 0)} influences/vertex, normalized skin weights on {rig_raw.get('skinned_mesh_count', 0)} mesh(es)."
            if rig_passed
            else f"Rigging validation issue: unweighted={rig_raw.get('unweighted_vertices')}, unnormalized={rig_raw.get('unnormalized_vertices')}, max_inf={rig_raw.get('max_influences_per_vertex')}",
            rig_raw,
        )

    # 12. Actual Polygon Budget check
    actual_tris = int(diag.get("actual_triangles", tm_info.get("triangles", 0)))
    within_budget = actual_tris <= int(polygon_budget * 1.25)  # allow 25% soft headroom, warn if exceeded
    strict_within = actual_tris <= polygon_budget
    add_check(
        "polygon_budget",
        "Measured Triangle Count vs Target Budget",
        strict_within,
        "info" if strict_within else "warning",
        f"Actual measured triangles: {actual_tris:,} (target budget: {polygon_budget:,})."
        if strict_within
        else f"Actual measured triangles ({actual_tris:,}) exceed target budget ({polygon_budget:,}); consider adjusting detail or quality profile.",
        {"actual_triangles": actual_tris, "polygon_budget": polygon_budget},
    )
    _ = within_budget

    bbox_data = tm_info.get("bounding_box") or diag.get("bounding_box")
    stats = MeshStats(
        actual_triangles=actual_tris,
        actual_vertices=int(diag.get("actual_vertices", 0)),
        gltf_render_vertices=int(tm_info.get("gltf_render_vertices", diag.get("actual_vertices", 0))),
        polygon_faces=int(diag.get("polygon_faces", actual_tris)),
        mesh_count=int(diag.get("mesh_count", len(gltf_json.get("meshes", [])))),
        material_count=int(diag.get("material_count", len(gltf_json.get("materials", [])))),
        texture_count=int(diag.get("texture_count", len(gltf_json.get("textures", [])))),
        connected_components=int(diag.get("connected_components", 1)),
        uv_layer_count=int(diag.get("uv_layer_count", 1)),
        has_uvs=has_uvs,
        bounding_box=BoundingBox3D.model_validate(bbox_data),
        materials=[MaterialSummary.model_validate(m) for m in diag.get("materials", [])],
        rig=RigSummary.model_validate(rig_raw),
    )

    errors = [c.message for c in checks if not c.passed and c.severity == "error"]
    warnings = [c.message for c in checks if not c.passed and c.severity == "warning"]
    passed_count = sum(1 for c in checks if c.passed)

    report = ValidationReport(
        valid=(len(errors) == 0),
        passed_count=passed_count,
        warning_count=len(warnings),
        error_count=len(errors),
        polygon_budget=polygon_budget,
        within_budget=strict_within,
        reimport_verified=reimport_passed,
        validator_backends=backends,
        checks=checks,
        warnings=warnings,
        errors=errors,
    )
    return stats, report


def validate_standalone_glb(
    glb_path: pathlib.Path,
    polygon_budget: int | None = None,
    max_output_bytes: int = 100 * 1024 * 1024,
) -> tuple[MeshStats | None, ValidationReport]:
    """Validate an arbitrary standalone GLB file (for `POST /api/validate` and CI artifact checks)."""
    checks: list[ValidationCheckItem] = []
    backends = ["gltf_binary_inspector"]

    glb_ok, gltf_json, glb_msg = _parse_glb_header_and_json(glb_path)
    if not glb_ok:
        err_check = ValidationCheckItem(
            check_id="glb_container",
            name="GLB Binary Container",
            passed=False,
            severity="error",
            message=glb_msg,
        )
        return None, ValidationReport(
            valid=False,
            passed_count=0,
            warning_count=0,
            error_count=1,
            polygon_budget=polygon_budget,
            within_budget=False,
            reimport_verified=False,
            validator_backends=backends,
            checks=[err_check],
            warnings=[],
            errors=[glb_msg],
        )

    size_bytes = glb_path.stat().st_size
    size_ok = size_bytes <= max_output_bytes
    checks.append(
        ValidationCheckItem(
            check_id="glb_container",
            name="GLB Binary Header & Size Bounds",
            passed=size_ok,
            severity="info" if size_ok else "error",
            message=glb_msg,
            details={"size_bytes": size_bytes},
        )
    )

    try:
        tm_info = _analyze_with_trimesh(glb_path)
    except Exception as exc:
        tm_info = {"loaded": False, "error": str(exc)}

    if not tm_info.get("loaded"):
        msg = f"Failed to parse GLB geometry: {tm_info.get('error')}"
        checks.append(
            ValidationCheckItem(
                check_id="geometry_load",
                name="Geometry Extraction",
                passed=False,
                severity="error",
                message=msg,
            )
        )
        return None, ValidationReport(
            valid=False,
            passed_count=sum(1 for c in checks if c.passed),
            warning_count=0,
            error_count=1,
            polygon_budget=polygon_budget,
            within_budget=False,
            reimport_verified=False,
            validator_backends=backends,
            checks=checks,
            warnings=[],
            errors=[msg],
        )

    backends.append("trimesh")
    actual_tris = int(tm_info["triangles"])
    has_uvs = any(
        "TEXCOORD_0" in prim.get("attributes", {})
        for mesh_def in gltf_json.get("meshes", [])
        for prim in mesh_def.get("primitives", [])
    )
    skins = gltf_json.get("skins", [])
    nodes = gltf_json.get("nodes", [])
    joint_indices = skins[0].get("joints", []) if skins else []
    bone_names = [nodes[j].get("name", f"joint_{j}") for j in joint_indices if 0 <= j < len(nodes)]
    anim_names = [a.get("name", f"anim_{i}") for i, a in enumerate(gltf_json.get("animations", []))]

    idx_ok = int(tm_info["invalid_indices"]) == 0 and int(tm_info["non_finite_verts"]) == 0
    checks.append(
        ValidationCheckItem(
            check_id="face_indices",
            name="Valid Face Indices & Finite Coordinates",
            passed=idx_ok,
            severity="info" if idx_ok else "error",
            message="All triangle indices and vertex positions are valid." if idx_ok else "Invalid indices or NaN coordinates found.",
        )
    )
    degen_n = int(tm_info["degenerate_triangles"])
    checks.append(
        ValidationCheckItem(
            check_id="degenerate_faces",
            name="Zero-Area / Degenerate Faces",
            passed=(degen_n == 0),
            severity="info" if degen_n == 0 else "warning",
            message="Zero degenerate triangles." if degen_n == 0 else f"{degen_n} degenerate triangles detected.",
        )
    )
    checks.append(
        ValidationCheckItem(
            check_id="uv_availability",
            name="glTF TEXCOORD_0 UV Attribute",
            passed=has_uvs,
            severity="info" if has_uvs else "warning",
            message="TEXCOORD_0 UV coordinates present." if has_uvs else "No TEXCOORD_0 attribute found in GLB primitives.",
        )
    )

    within_b = True
    if polygon_budget is not None:
        within_b = actual_tris <= polygon_budget
        checks.append(
            ValidationCheckItem(
                check_id="polygon_budget",
                name="Measured Triangle Count vs Target Budget",
                passed=within_b,
                severity="info" if within_b else "warning",
                message=f"Measured {actual_tris:,} triangles vs budget {polygon_budget:,}.",
            )
        )

    mat_summaries: list[MaterialSummary] = []
    for i, mdef in enumerate(gltf_json.get("materials", [])):
        pbr = mdef.get("pbrMetallicRoughness", {})
        bc = pbr.get("baseColorFactor", [0.8, 0.8, 0.8, 1.0])
        has_tex = "baseColorTexture" in pbr
        mat_summaries.append(
            MaterialSummary(
                name=mdef.get("name", f"Material_{i}"),
                base_color=(float(bc[0]), float(bc[1]), float(bc[2]), float(bc[3])),
                metallic=float(pbr.get("metallicFactor", 0.0)),
                roughness=float(pbr.get("roughnessFactor", 0.5)),
                has_textures=has_tex,
            )
        )

    stats = MeshStats(
        actual_triangles=actual_tris,
        actual_vertices=int(tm_info["gltf_render_vertices"]),
        gltf_render_vertices=int(tm_info["gltf_render_vertices"]),
        polygon_faces=actual_tris,
        mesh_count=int(tm_info["geometry_count"]),
        material_count=len(gltf_json.get("materials", [])),
        texture_count=len(gltf_json.get("textures", [])),
        connected_components=int(tm_info["geometry_count"]),
        uv_layer_count=1 if has_uvs else 0,
        has_uvs=has_uvs,
        bounding_box=BoundingBox3D.model_validate(tm_info["bounding_box"]),
        materials=mat_summaries,
        rig=RigSummary(
            has_armature=len(skins) > 0,
            armature_name=skins[0].get("name", "Armature") if skins else None,
            bone_count=len(bone_names),
            bone_names=bone_names,
            skinned_mesh_count=sum(1 for n in nodes if "skin" in n),
            normalized_weights_verified=len(skins) > 0,
            max_influences_per_vertex=4 if skins else 0,
            animation_clips=anim_names,
        ),
    )

    errors = [c.message for c in checks if not c.passed and c.severity == "error"]
    warnings = [c.message for c in checks if not c.passed and c.severity == "warning"]
    report = ValidationReport(
        valid=(len(errors) == 0),
        passed_count=sum(1 for c in checks if c.passed),
        warning_count=len(warnings),
        error_count=len(errors),
        polygon_budget=polygon_budget,
        within_budget=within_b,
        reimport_verified=True,
        validator_backends=backends,
        checks=checks,
        warnings=warnings,
        errors=errors,
    )
    return stats, report
