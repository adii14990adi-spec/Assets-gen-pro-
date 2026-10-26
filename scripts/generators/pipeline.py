"""Deterministic, in-process 3D asset generation pipeline.

This module is the single entrypoint used by ``scripts/build_all_assets.py``
(and therefore by GitHub Actions): it dispatches a fully-specified asset
description to the correct pure-Python procedural generator, applies the
polygon budget, bakes flat-faceted or smooth normals, serializes a valid
glTF 2.0 binary (``.glb``) in memory, and then *re-imports those exact bytes*
with Trimesh to measure and prove the topology it reports.

No server, no Blender requirement, no network access: numpy + scipy + trimesh.
"""

from __future__ import annotations

import io
import json
import struct
import time
import zlib
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

import numpy as np
import scipy
import trimesh

from .architecture import build_architecture
from .diagnostics import measure_diagnostics
from .glb_writer import build_glb_stream
from .humanoid import build_humanoid
from .meshkit import Quality, SceneBuilder, enforce_budget, mesh_to_glb_part, resolve_quality
from .palette import resolve_materials
from .props import build_prop
from .terrain import build_environment

ENGINE_LABEL = "AssetsGenPro-codegen/2.0"
GENERATOR_STRING = f"{ENGINE_LABEL} (numpy+scipy+trimesh)"

BUILDERS: dict[
    str, Callable[[SceneBuilder, dict[str, Any], Quality, np.random.Generator], None]
] = {
    "props": build_prop,
    "architecture": build_architecture,
    "environment": build_environment,
    "humanoid": build_humanoid,
}

ProgressFn = Callable[[str, int, str], None]


class AssetGenerationError(RuntimeError):
    """Raised when a generator fails to produce a shippable asset."""


@dataclass
class GeneratedAsset:
    """A finished in-memory asset plus its measured statistics."""

    glb_bytes: bytes
    vertices: int
    faces: int
    triangles: int
    file_size_bytes: int
    generation_seconds: float
    flat_shading: bool
    mesh_count: int
    material_count: int
    dimensions: tuple[float, float, float]
    materials: list[dict[str, Any]] = field(default_factory=list)
    capability_notes: list[str] = field(default_factory=list)
    seed: int = 0

    @property
    def file_size_kb(self) -> float:
        return round(self.file_size_bytes / 1024.0, 2)


def _seed_entropy(seed: int, preset_id: str) -> int:
    return (seed ^ zlib.crc32(preset_id.encode("utf-8"))) & 0x7FFFFFFF


def generate_asset(
    config: dict[str, Any],
    on_progress: ProgressFn | None = None,
    should_cancel: Callable[[], bool] | None = None,
) -> GeneratedAsset:
    """Generate one asset from a fully-resolved configuration dict.

    Required config keys: ``category``, ``preset_id``, ``parameters``,
    ``polygon_budget``. Optional: ``seed``, ``quality_profile``,
    ``material_preset``, ``flat_shading``.
    """

    def emit(stage: str, pct: int, message: str) -> None:
        if on_progress is not None:
            on_progress(stage, pct, message)

    def check_cancel() -> None:
        if should_cancel is not None and should_cancel():
            raise AssetGenerationError("Generation cancelled.")

    started = time.perf_counter()
    category = str(config["category"])
    preset_id = str(config["preset_id"])
    budget = int(config.get("polygon_budget") or 2200)
    quality = resolve_quality(str(config.get("quality_profile", "optimized_mid_poly")), budget)
    seed = int(config.get("seed", 1727))
    params = dict(config.get("parameters") or {})
    flat_shading = bool(config.get("flat_shading", params.get("flat_shading", True)))
    rng = np.random.default_rng(_seed_entropy(seed, preset_id))

    builder = BUILDERS.get(category)
    if builder is None:
        raise AssetGenerationError(
            f"Unsupported asset category {category!r}; expected one of {sorted(BUILDERS)}."
        )

    emit("materials", 8, f"Resolving PBR palette for {category}/{preset_id}...")
    materials = resolve_materials(config)
    check_cancel()

    emit("geometry", 25, f"Synthesizing procedural {category} geometry ({preset_id})...")
    scene = SceneBuilder(materials)
    builder(scene, config, quality, rng)
    check_cancel()

    parts = scene.merged_parts()
    if not parts:
        raise AssetGenerationError(f"Generator produced zero mesh parts for {preset_id!r}.")

    raw_faces = sum(len(mesh.faces) for _, _, mesh in parts)
    if raw_faces > budget:
        emit("decimating", 52, f"Decimating {raw_faces:,} raw faces toward a {budget:,} face budget...")
        parts = enforce_budget(parts, budget)
    check_cancel()

    shading = "flat-faceted face normals" if flat_shading else "smooth welded vertex normals"
    emit("shading", 68, f"Baking {shading}, triplanar UVs, and per-face vertex colors...")
    glb_parts = [
        mesh_to_glb_part(name, mesh, materials[slot], rng, flat_shading=flat_shading)
        for name, slot, mesh in parts
    ]

    emit("exporting", 82, "Serializing glTF 2.0 binary (.glb) buffer...")
    stream: io.BytesIO = build_glb_stream(glb_parts, generator=GENERATOR_STRING)
    glb_bytes = stream.getvalue()
    check_cancel()

    emit("verifying", 92, "Re-importing the exported GLB to measure real topology...")
    diagnostics, reimport = measure_diagnostics(category, parts, glb_parts, materials, glb_bytes)
    if not reimport["passed"]:
        raise AssetGenerationError(
            f"GLB round-trip verification failed for {preset_id!r}: "
            f"{reimport['reimported_triangles']} re-imported triangles vs "
            f"{diagnostics['actual_triangles']} exported."
        )

    notes = [
        "geometry: pure Python analytic/spline construction (no Blender dependency)",
        "export: built-in deterministic glTF 2.0 binary writer",
        "validation: Trimesh re-import of the exact exported bytes",
    ]
    if category == "humanoid":
        pose = "symmetrical T-pose" if preset_id == "midpoly_character" else "stylized A-pose"
        notes.append(f"rig: static {pose} mesh (no skeletal animation baked into the GLB)")

    elapsed = round(time.perf_counter() - started, 3)
    emit(
        "completed",
        100,
        f"{diagnostics['actual_triangles']:,} triangles / "
        f"{diagnostics['actual_vertices']:,} vertices in {elapsed:.2f}s",
    )
    return GeneratedAsset(
        glb_bytes=glb_bytes,
        vertices=int(diagnostics["actual_vertices"]),
        faces=int(diagnostics["polygon_faces"]),
        triangles=int(diagnostics["actual_triangles"]),
        file_size_bytes=len(glb_bytes),
        generation_seconds=elapsed,
        flat_shading=flat_shading,
        mesh_count=int(diagnostics["mesh_count"]),
        material_count=int(diagnostics["material_count"]),
        dimensions=tuple(diagnostics["bounding_box"]["dimensions"]),
        materials=list(diagnostics["materials"]),
        capability_notes=notes,
        seed=seed,
    )


# ---------------------------------------------------------------------------
# Standalone GLB binary validation (independent of the generator that wrote it)
# ---------------------------------------------------------------------------

_GLB_MAGIC = 0x46546C67
_GLB_CHUNK_JSON = 0x4E4F534A
_GLB_CHUNK_BIN = 0x004E4942
_COMPONENT_SIZES = {5120: 1, 5121: 1, 5122: 2, 5123: 2, 5125: 4, 5126: 4}
_TYPE_COUNTS = {"SCALAR": 1, "VEC2": 2, "VEC3": 3, "VEC4": 4, "MAT4": 16}


def validate_glb_bytes(data: bytes, *, expected_triangles: int | None = None) -> dict[str, Any]:
    """Structurally validate a binary glTF 2.0 container and its mesh accessors.

    Checks the 12-byte header, every chunk boundary, JSON parseability, and for
    each mesh primitive: accessor existence, component type consistency, in-range
    indices, POSITION min/max presence, and triangle-count parity with a fresh
    Trimesh re-import. Raises :class:`AssetGenerationError` on any violation.
    """

    if len(data) < 20:
        raise AssetGenerationError("GLB payload is too small to be a valid container.")
    magic, version, declared_length = struct.unpack_from("<III", data, 0)
    if magic != _GLB_MAGIC:
        raise AssetGenerationError(f"GLB magic mismatch: 0x{magic:08x}")
    if version != 2:
        raise AssetGenerationError(f"Unsupported GLB container version {version}.")
    if declared_length != len(data):
        raise AssetGenerationError(
            f"GLB header declares {declared_length} bytes but the file is {len(data)} bytes."
        )

    offset = 12
    gltf: dict[str, Any] | None = None
    bin_length = 0
    bin_payload = b""
    chunk_errors: list[str] = []
    while offset < len(data):
        if offset + 8 > len(data):
            raise AssetGenerationError("Truncated GLB chunk header.")
        chunk_length, chunk_type = struct.unpack_from("<II", data, offset)
        offset += 8
        payload = data[offset : offset + chunk_length]
        if len(payload) != chunk_length:
            raise AssetGenerationError("GLB chunk extends past end of file.")
        if chunk_type == _GLB_CHUNK_JSON:
            try:
                gltf = json.loads(payload.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:  # pragma: no cover - defensive
                raise AssetGenerationError(f"GLB JSON chunk is not valid JSON: {exc}") from exc
        elif chunk_type == _GLB_CHUNK_BIN:
            bin_length = chunk_length
            bin_payload = payload
        else:
            chunk_errors.append(f"unexpected chunk type 0x{chunk_type:08x}")
        offset += chunk_length
        offset += (-chunk_length) % 4  # chunks are 4-byte aligned

    if gltf is None:
        raise AssetGenerationError("GLB has no JSON chunk.")
    if chunk_errors:
        raise AssetGenerationError(f"GLB chunk layout problems: {chunk_errors}")

    buffers = gltf.get("buffers") or []
    if not buffers:
        raise AssetGenerationError("glTF JSON declares no buffers.")
    if int(buffers[0].get("byteLength", -1)) > bin_length:
        raise AssetGenerationError("glTF buffer byteLength exceeds the BIN chunk size.")

    accessors = gltf.get("accessors") or []
    buffer_views = gltf.get("bufferViews") or []
    meshes = gltf.get("meshes") or []
    if not meshes:
        raise AssetGenerationError("glTF JSON declares no meshes.")

    triangles = 0
    primitives = 0
    for mesh in meshes:
        for prim in mesh.get("primitives", []):
            primitives += 1
            attrs = prim.get("attributes") or {}
            pos_idx = attrs.get("POSITION")
            if pos_idx is None or pos_idx >= len(accessors):
                raise AssetGenerationError("Mesh primitive is missing a valid POSITION accessor.")
            pos = accessors[pos_idx]
            if "min" not in pos or "max" not in pos:
                raise AssetGenerationError("POSITION accessor is missing spec-required min/max bounds.")
            if pos.get("type") != "VEC3":
                raise AssetGenerationError("POSITION accessor must be VEC3.")
            view = buffer_views[pos["bufferView"]]
            stride = _COMPONENT_SIZES[pos["componentType"]] * _TYPE_COUNTS[pos["type"]]
            if pos.get("byteOffset", 0) + pos["count"] * stride > view["byteLength"]:
                raise AssetGenerationError("POSITION accessor overruns its bufferView.")
            idx_idx = prim.get("indices")
            if idx_idx is not None:
                if idx_idx >= len(accessors):
                    raise AssetGenerationError("Mesh primitive indices accessor is out of range.")
                idx = accessors[idx_idx]
                if idx["count"] % 3 != 0:
                    raise AssetGenerationError("Index accessor count is not a multiple of 3.")
                triangles += idx["count"] // 3
                raw = bin_payload
                view = buffer_views[idx["bufferView"]]
                start = view.get("byteOffset", 0) + idx.get("byteOffset", 0)
                fmt = {5121: "B", 5123: "H", 5125: "I"}[idx["componentType"]]
                indices = struct.unpack_from(f"<{idx['count']}{fmt}", raw, start)
                if max(indices) >= pos["count"]:
                    raise AssetGenerationError("Index accessor references vertices outside POSITION.")
            else:
                triangles += pos["count"] // 3

    if primitives == 0:
        raise AssetGenerationError("glTF meshes contain no primitives.")

    reimported = trimesh.load(
        trimesh.util.wrap_as_stream(data), file_type="glb", force="scene", process=False
    )
    reimported_tris = int(sum(len(g.faces) for g in reimported.geometry.values()))
    if reimported_tris != triangles:
        raise AssetGenerationError(
            f"Triangle count mismatch: accessors declare {triangles}, re-import found {reimported_tris}."
        )
    if expected_triangles is not None and triangles != expected_triangles:
        raise AssetGenerationError(
            f"Expected {expected_triangles} triangles, GLB contains {triangles}."
        )

    return {
        "valid": True,
        "version": version,
        "byte_length": len(data),
        "json_chunk_bytes": len(json.dumps(gltf)),
        "bin_chunk_bytes": bin_length,
        "meshes": len(meshes),
        "primitives": primitives,
        "materials": len(gltf.get("materials") or []),
        "accessors": len(accessors),
        "triangles": triangles,
        "reimported_triangles": reimported_tris,
        "has_vertex_colors": any(
            "COLOR_0" in (mesh.get("primitives") or [{}])[0].get("attributes", {}) for mesh in meshes
        ),
        "has_uvs": any(
            "TEXCOORD_0" in (mesh.get("primitives") or [{}])[0].get("attributes", {}) for mesh in meshes
        ),
        "generator": gltf.get("asset", {}).get("generator", ""),
    }


def runtime_banner() -> str:
    """One-line description of the local generation stack (recorded in reports)."""
    return (
        f"numpy {np.__version__} | scipy {scipy.__version__} | "
        f"trimesh {trimesh.__version__} | {ENGINE_LABEL}"
    )
