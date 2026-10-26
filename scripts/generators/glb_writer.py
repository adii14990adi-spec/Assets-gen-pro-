"""Minimal, spec-correct glTF 2.0 binary (``.glb``) writer.

Why a custom writer instead of ``trimesh.Scene.export``?  Trimesh's exporter
cannot simultaneously emit ``COLOR_0`` vertex colors, ``TEXCOORD_0`` UVs,
flat-shaded ``NORMAL`` attributes, and individually named
``pbrMetallicRoughness`` materials.  This writer emits exactly that
combination with fully deterministic byte layout:

* one interleaved-free BIN buffer, every ``bufferView`` 4-byte aligned,
* ``POSITION`` accessors carry the spec-required ``min``/``max`` bounds,
* sRGB palette colors are converted to linear space for
  ``baseColorFactor`` (glTF factors are linear), while ``COLOR_0`` carries
  near-white per-face faceting tints so the product
  ``baseColorFactor * COLOR_0`` renders the intended stylized flat color,
* deterministic ordering (parts, materials, accessors) so identical seeds
  produce byte-identical GLBs.
"""

from __future__ import annotations

import io
import json
import struct
from dataclasses import dataclass, field
from typing import Any

import numpy as np

GLB_MAGIC = 0x46546C67  # "glTF"
GLB_VERSION = 2
CHUNK_JSON = 0x4E4F534A  # "JSON"
CHUNK_BIN = 0x004E4942  # "BIN\0"

# glTF component / type enums
_CT_UNSIGNED_BYTE = 5121
_CT_UNSIGNED_INT = 5125
_CT_FLOAT = 5126
_TARGET_ARRAY_BUFFER = 34962
_TARGET_ELEMENT_ARRAY_BUFFER = 34963


def srgb_to_linear(value: float) -> float:
    """Convert one sRGB channel in ``[0, 1]`` to linear space."""
    v = float(np.clip(value, 0.0, 1.0))
    return v / 12.92 if v <= 0.04045 else ((v + 0.055) / 1.055) ** 2.4


def srgb_array_to_linear(rgb: np.ndarray) -> np.ndarray:
    """Vectorized sRGB ``[..., 3]`` in ``[0, 1]`` -> glTF linear space."""
    v = np.clip(np.asarray(rgb, dtype=np.float64), 0.0, 1.0)
    return np.where(v <= 0.04045, v / 12.92, ((v + 0.055) / 1.055) ** 2.4)


@dataclass
class GlbMaterial:
    """A single glTF PBR material (colors supplied in sRGB space)."""

    name: str
    base_color_srgb: tuple[float, float, float, float]
    metallic: float = 0.0
    roughness: float = 0.65
    emissive_srgb: tuple[float, float, float] | None = None
    double_sided: bool = False
    vertex_color_albedo: bool = True


@dataclass
class GlbPart:
    """One exported mesh: faceted vertices + indices + material reference."""

    name: str
    positions: np.ndarray  # (N, 3) float32, Y-up meters
    normals: np.ndarray  # (N, 3) float32, flat-shaded
    uvs: np.ndarray  # (N, 2) float32
    colors: np.ndarray  # (N, 4) uint8 faceting tints
    indices: np.ndarray  # (M, 3) uint32
    material: GlbMaterial


@dataclass
class _BufferBuilder:
    data: bytearray = field(default_factory=bytearray)
    views: list[dict[str, Any]] = field(default_factory=list)
    accessors: list[dict[str, Any]] = field(default_factory=list)

    def _pad(self) -> None:
        while len(self.data) % 4 != 0:
            self.data.append(0)

    def add_accessor(
        self,
        array: np.ndarray,
        component_type: int,
        accessor_type: str,
        target: int,
        *,
        normalized: bool = False,
        include_min_max: bool = False,
    ) -> int:
        self._pad()
        raw = np.ascontiguousarray(array).tobytes()
        view_index = len(self.views)
        self.views.append(
            {
                "buffer": 0,
                "byteOffset": len(self.data),
                "byteLength": len(raw),
                "target": target,
            }
        )
        self.data.extend(raw)

        accessor: dict[str, Any] = {
            "bufferView": view_index,
            "byteOffset": 0,
            "componentType": component_type,
            "count": int(array.shape[0]),
            "type": accessor_type,
        }
        if normalized:
            accessor["normalized"] = True
        if include_min_max:
            accessor["min"] = [float(x) for x in np.min(array, axis=0)]
            accessor["max"] = [float(x) for x in np.max(array, axis=0)]
        self.accessors.append(accessor)
        return len(self.accessors) - 1


def build_glb_bytes(parts: list[GlbPart], *, generator: str) -> bytes:
    """Serialize *parts* into a complete, valid binary glTF 2.0 payload."""
    if not parts:
        raise ValueError("Cannot build a GLB with zero mesh parts.")

    builder = _BufferBuilder()
    materials_json: list[dict[str, Any]] = []
    material_index: dict[str, int] = {}
    meshes_json: list[dict[str, Any]] = []
    nodes_json: list[dict[str, Any]] = []

    for part in parts:
        if part.material.name not in material_index:
            mat = part.material
            r, g, b, a = mat.base_color_srgb
            if mat.vertex_color_albedo:
                # COLOR_0 already stores linear RGB vertex/face colors directly,
                # so keep baseColorFactor neutral [1,1,1,a] to avoid color^2 darkening.
                base_factor = [1.0, 1.0, 1.0, float(a)]
            else:
                base_factor = [
                    round(srgb_to_linear(r), 6),
                    round(srgb_to_linear(g), 6),
                    round(srgb_to_linear(b), 6),
                    float(a),
                ]
            material_json: dict[str, Any] = {
                "name": mat.name,
                "pbrMetallicRoughness": {
                    "baseColorFactor": base_factor,
                    "metallicFactor": float(np.clip(mat.metallic, 0.0, 1.0)),
                    "roughnessFactor": float(np.clip(mat.roughness, 0.04, 1.0)),
                },
            }
            if mat.emissive_srgb is not None:
                er, eg, eb = mat.emissive_srgb
                material_json["emissiveFactor"] = [
                    round(srgb_to_linear(er), 6),
                    round(srgb_to_linear(eg), 6),
                    round(srgb_to_linear(eb), 6),
                ]
            if mat.double_sided:
                material_json["doubleSided"] = True
            material_index[mat.name] = len(materials_json)
            materials_json.append(material_json)

        pos_idx = builder.add_accessor(
            part.positions.astype(np.float32),
            _CT_FLOAT,
            "VEC3",
            _TARGET_ARRAY_BUFFER,
            include_min_max=True,
        )
        norm_idx = builder.add_accessor(
            part.normals.astype(np.float32), _CT_FLOAT, "VEC3", _TARGET_ARRAY_BUFFER
        )
        uv_idx = builder.add_accessor(
            part.uvs.astype(np.float32), _CT_FLOAT, "VEC2", _TARGET_ARRAY_BUFFER
        )
        col_idx = builder.add_accessor(
            part.colors.astype(np.uint8),
            _CT_UNSIGNED_BYTE,
            "VEC4",
            _TARGET_ARRAY_BUFFER,
            normalized=True,
        )
        idx_idx = builder.add_accessor(
            part.indices.astype(np.uint32).reshape(-1),
            _CT_UNSIGNED_INT,
            "SCALAR",
            _TARGET_ELEMENT_ARRAY_BUFFER,
        )

        meshes_json.append(
            {
                "name": part.name,
                "primitives": [
                    {
                        "attributes": {
                            "POSITION": pos_idx,
                            "NORMAL": norm_idx,
                            "TEXCOORD_0": uv_idx,
                            "COLOR_0": col_idx,
                        },
                        "indices": idx_idx,
                        "material": material_index[part.material.name],
                        "mode": 4,  # TRIANGLES
                    }
                ],
            }
        )
        nodes_json.append({"name": part.name, "mesh": len(meshes_json) - 1})

    builder._pad()
    gltf: dict[str, Any] = {
        "asset": {"version": "2.0", "generator": generator},
        "scene": 0,
        "scenes": [{"name": "Scene", "nodes": list(range(len(nodes_json)))}],
        "nodes": nodes_json,
        "meshes": meshes_json,
        "materials": materials_json,
        "buffers": [{"byteLength": len(builder.data)}],
        "bufferViews": builder.views,
        "accessors": builder.accessors,
    }

    json_bytes = json.dumps(gltf, separators=(",", ":")).encode("utf-8")
    json_bytes += b" " * ((4 - len(json_bytes) % 4) % 4)
    bin_bytes = bytes(builder.data)
    bin_bytes += b"\x00" * ((4 - len(bin_bytes) % 4) % 4)

    total_length = 12 + 8 + len(json_bytes) + 8 + len(bin_bytes)
    stream = io.BytesIO()
    stream.write(struct.pack("<III", GLB_MAGIC, GLB_VERSION, total_length))
    stream.write(struct.pack("<II", len(json_bytes), CHUNK_JSON))
    stream.write(json_bytes)
    stream.write(struct.pack("<II", len(bin_bytes), CHUNK_BIN))
    stream.write(bin_bytes)
    return stream.getvalue()


def build_glb_stream(parts: list[GlbPart], *, generator: str) -> io.BytesIO:
    """Serialize *parts* into an in-memory ``io.BytesIO`` binary ``.glb`` stream."""
    buf = io.BytesIO(build_glb_bytes(parts, generator=generator))
    buf.seek(0)
    return buf
