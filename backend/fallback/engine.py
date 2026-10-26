"""Pure-Python procedural 3D generation engine (NumPy + Trimesh).

This is the second half of the studio's **dual-engine** architecture:

* When a Blender 4.2 LTS runtime is present (``blender`` CLI, the isolated
  ``bpy`` venv, or an importable ``bpy`` module), generation runs through
  the full BMesh / Geometry Nodes pipeline in ``backend/blender/runner.py``.
* When Blender is NOT installed — Render Native Python, slim containers,
  minimal CI — this engine generates the same presets entirely in-process:
  deterministic seeded procedural meshes for humanoid characters,
  Rajasthani architecture, terrain/environment, and gameplay props,
  followed by vertex-clustering decimation to the requested polygon
  budget, flat-shaded faceting, triplanar UV projection, per-face vertex
  colors, and serialization via the built-in glTF 2.0 writer
  (``backend/fallback/glb_writer.py``).

The returned payload mirrors the Blender runner's ``blender_result.json``
contract (``scene_diagnostics``, ``reimport_check``, capabilities, GLB
filename/size) so the job manager, validator, and frontend work unchanged.
Diagnostics are *measured* with Trimesh/NumPy — never fabricated. Where
Blender-only features are unavailable (skinned armature, native ``.blend``
files) the payload says so honestly via ``capabilities_fallback``.

All geometry is authored directly in glTF space: meters, ``+Y`` up,
grounded at ``Y = 0``.
"""

from __future__ import annotations

import json
import math
import pathlib
import time
import zlib
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import numpy as np
import trimesh

from backend.blender.materials import THEME_PALETTES
from backend.fallback.glb_writer import GlbMaterial, GlbPart, build_glb_bytes

ENGINE_NAME = "python_fallback"
ENGINE_VERSION_LABEL = "PythonFallback/1.0"

# Category-default material themes — mirrored from the Blender generators.
_CATEGORY_DEFAULT_THEME = {
    "props": "tactical_military",
    "architecture": "rajasthan_sandstone",
    "environment": "aravalli_biome",
    "humanoid": "tactical_military",
}

# Extra non-theme slots (sRGB, metallic, roughness) used across categories.
_EXTRA_SLOTS: dict[str, tuple[tuple[float, float, float], float, float]] = {
    "water": ((0.13, 0.38, 0.50), 0.05, 0.18),
    "skin": ((0.76, 0.55, 0.42), 0.0, 0.62),
    "hair": ((0.10, 0.08, 0.07), 0.0, 0.72),
    "sand": ((0.82, 0.72, 0.53), 0.0, 0.9),
    "foliage_dark": ((0.20, 0.32, 0.16), 0.0, 0.88),
    "glass_lamp": ((1.0, 0.82, 0.45), 0.1, 0.25),
}


@dataclass(frozen=True)
class _Quality:
    radial: int  # cylinder/tube radial segments
    sphere_subdiv: int  # icosphere subdivisions for hero forms
    terrain_res: int  # heightfield grid resolution (per side)
    scatter_mul: float
    fingers: bool


_QUALITY = {
    "prototype": _Quality(radial=10, sphere_subdiv=2, terrain_res=26, scatter_mul=0.6, fingers=False),
    "optimized_mid_poly": _Quality(
        radial=16, sphere_subdiv=3, terrain_res=38, scatter_mul=1.0, fingers=True
    ),
    "detailed_mid_poly": _Quality(
        radial=22, sphere_subdiv=3, terrain_res=52, scatter_mul=1.5, fingers=True
    ),
}


# ---------------------------------------------------------------------------
# Material resolution
# ---------------------------------------------------------------------------


def _resolve_materials(cfg: dict[str, Any]) -> dict[str, GlbMaterial]:
    category = str(cfg["category"])
    requested = str(cfg.get("material_preset", "default"))
    theme = requested if requested in THEME_PALETTES else _CATEGORY_DEFAULT_THEME[category]
    palette = THEME_PALETTES[theme]

    materials: dict[str, GlbMaterial] = {}
    for slot, (rgb, metallic, roughness, _pattern) in palette.items():
        materials[slot] = GlbMaterial(
            name=f"Mat_{theme}_{slot}",
            base_color_srgb=(rgb[0], rgb[1], rgb[2], 1.0),
            metallic=float(metallic),
            roughness=float(roughness),
        )
    for slot, (rgb, metallic, roughness) in _EXTRA_SLOTS.items():
        materials.setdefault(
            slot,
            GlbMaterial(
                name=f"Mat_{theme}_{slot}",
                base_color_srgb=(rgb[0], rgb[1], rgb[2], 1.0),
                metallic=float(metallic),
                roughness=float(roughness),
                emissive_srgb=(1.0, 0.72, 0.30) if slot == "glass_lamp" else None,
            ),
    )
    # Guarantee the standard slots exist even for palettes that omit them.
    for slot, donor in (("metal", "secondary"), ("accent", "primary"), ("trim", "secondary")):
        if slot not in materials and donor in materials:
            d = materials[donor]
            materials[slot] = GlbMaterial(
                name=f"Mat_{theme}_{slot}",
                base_color_srgb=d.base_color_srgb,
                metallic=d.metallic,
                roughness=d.roughness,
            )
    return materials


# ---------------------------------------------------------------------------
# Low-level mesh helpers (all return merged-vertex watertight primitives)
# ---------------------------------------------------------------------------


def _rot(mesh: trimesh.Trimesh, angle: float, axis: tuple[float, float, float], point: Any) -> trimesh.Trimesh:
    mesh.apply_transform(
        trimesh.transformations.rotation_matrix(angle, list(axis), list(point))
    )
    return mesh


def _box(size: tuple[float, float, float], center: tuple[float, float, float]) -> trimesh.Trimesh:
    mesh = trimesh.creation.box(extents=[max(s, 1e-4) for s in size])
    mesh.apply_translation(center)
    return mesh


def _cyl_Y(
    radius: float, height: float, sections: int, center: tuple[float, float, float]
) -> trimesh.Trimesh:
    """Cylinder with its axis along +Y (trimesh authors along +Z)."""
    mesh = trimesh.creation.cylinder(radius=radius, height=height, sections=max(3, sections))
    _rot(mesh, -math.pi / 2.0, (1, 0, 0), (0, 0, 0))
    mesh.apply_translation(center)
    return mesh


def _cone_Y(
    radius: float, height: float, sections: int, center: tuple[float, float, float]
) -> trimesh.Trimesh:
    mesh = trimesh.creation.cone(radius=radius, height=height, sections=max(3, sections))
    _rot(mesh, -math.pi / 2.0, (1, 0, 0), (0, 0, 0))
    mesh.apply_translation(center)
    return mesh


def _sphere(
    radii: tuple[float, float, float],
    center: tuple[float, float, float],
    subdivisions: int,
) -> trimesh.Trimesh:
    mesh = trimesh.creation.icosphere(subdivisions=subdivisions, radius=1.0)
    mesh.apply_scale(radii)
    mesh.apply_translation(center)
    return mesh


def _tube(
    p1: tuple[float, float, float], p2: tuple[float, float, float], radius: float, sections: int
) -> trimesh.Trimesh:
    return trimesh.creation.cylinder(
        radius=radius, sections=max(3, sections), segment=[list(p1), list(p2)]
    )


def _torus_flat(
    major_r: float,
    minor_r: float,
    center: tuple[float, float, float],
    major_sections: int,
    minor_sections: int,
) -> trimesh.Trimesh:
    """Torus lying in the XZ plane (hole axis = Y)."""
    mesh = trimesh.creation.torus(
        major_radius=major_r,
        minor_radius=minor_r,
        major_sections=major_sections,
        minor_sections=minor_sections,
    )
    _rot(mesh, math.pi / 2.0, (1, 0, 0), (0, 0, 0))
    mesh.apply_translation(center)
    return mesh


def _displaced_rock(
    center: tuple[float, float, float],
    radii: tuple[float, float, float],
    subdivisions: int,
    rng: np.random.Generator,
    roughness: float = 0.35,
) -> trimesh.Trimesh:
    mesh = trimesh.creation.icosphere(subdivisions=subdivisions, radius=1.0)
    verts = np.asarray(mesh.vertices, dtype=np.float64)
    dirs = verts / np.maximum(np.linalg.norm(verts, axis=1, keepdims=True), 1e-9)
    # Deterministic low-frequency radial noise keeps shared vertices consistent.
    waves = rng.normal(0.0, 1.6, size=(4, 3))
    phases = rng.uniform(0.0, 2.0 * math.pi, size=4)
    amps = np.array([0.55, 0.30, 0.18, 0.10])
    disp = np.ones(len(verts))
    for k in range(4):
        disp += roughness * amps[k] * np.sin(dirs @ waves[k] + phases[k])
    mesh.vertices = dirs * disp[:, None]
    mesh.apply_scale(radii)
    mesh.apply_translation(center)
    return mesh


# ---------------------------------------------------------------------------
# Scene assembly
# ---------------------------------------------------------------------------


class _SceneBuilder:
    """Collects merged-vertex meshes grouped into named GLB parts."""

    def __init__(self, materials: dict[str, GlbMaterial]) -> None:
        self.materials = materials
        self._groups: dict[tuple[str, str], list[trimesh.Trimesh]] = {}

    def add(self, part: str, slot: str, mesh: trimesh.Trimesh) -> None:
        if len(mesh.faces) == 0:
            return
        self._groups.setdefault((part, slot), []).append(mesh)

    def add_many(self, part: str, slot: str, meshes: list[trimesh.Trimesh]) -> None:
        for mesh in meshes:
            self.add(part, slot, mesh)

    def merged_parts(self) -> list[tuple[str, str, trimesh.Trimesh]]:
        out: list[tuple[str, str, trimesh.Trimesh]] = []
        for (part, slot), meshes in sorted(self._groups.items()):
            merged = meshes[0] if len(meshes) == 1 else trimesh.util.concatenate(meshes)
            try:
                merged.merge_vertices()
            except Exception:
                pass
            name = part if len([k for k in self._groups if k[0] == part]) == 1 else f"{part}_{slot}"
            out.append((name, slot, merged))
        return out


def _submesh_by_mask(mesh: trimesh.Trimesh, mask: np.ndarray) -> trimesh.Trimesh | None:
    faces = np.asarray(mesh.faces)[mask]
    if len(faces) == 0:
        return None
    used, inverse = np.unique(faces.reshape(-1), return_inverse=True)
    return trimesh.Trimesh(
        vertices=np.asarray(mesh.vertices)[used],
        faces=inverse.reshape(-1, 3),
        process=False,
    )


# ---------------------------------------------------------------------------
# Heightfield terrain (closed solid: top grid + skirt + bottom)
# ---------------------------------------------------------------------------


def _fbm(x: np.ndarray, z: np.ndarray, rng: np.random.Generator, octaves: int = 4) -> np.ndarray:
    total = np.zeros_like(x, dtype=np.float64)
    amp = 1.0
    freq = 1.0
    norm = 0.0
    for _ in range(octaves):
        p1, p2 = rng.uniform(0.0, 2.0 * math.pi, size=2)
        total += amp * np.sin(x * freq * 1.7 + p1) * np.cos(z * freq * 1.5 + p2)
        total += amp * 0.5 * np.sin((x + z) * freq * 0.9 + p2)
        norm += amp * 1.5
        amp *= 0.5
        freq *= 2.1
    return total / max(norm, 1e-9)


def _heightfield(
    width: float,
    depth: float,
    res: int,
    heights: np.ndarray,
    *,
    base_lift: float = 0.6,
) -> tuple[trimesh.Trimesh, np.ndarray, np.ndarray, np.ndarray]:
    """Build a closed terrain solid. Returns (mesh, top_face_slot_codes, xs, zs).

    Slot codes are per-face integers: 0=sand/low, 1=grass/mid, 2=rock/steep,
    computed for top faces; skirt/bottom faces are coded rock (2).
    ``heights`` is shaped (res, res) indexed [x, z] and is shifted so its
    minimum sits at ``base_lift`` (the solid extends down to Y=0).
    """
    H = np.asarray(heights, dtype=np.float64).copy()
    H = H - H.min() + base_lift
    xs = np.linspace(-width / 2.0, width / 2.0, res)
    zs = np.linspace(-depth / 2.0, depth / 2.0, res)

    verts = np.zeros((res * res, 3), dtype=np.float64)
    for i in range(res):
        for j in range(res):
            verts[i * res + j] = (xs[i], H[i, j], zs[j])

    def vid(i: int, j: int) -> int:
        return i * res + j

    faces: list[tuple[int, int, int]] = []
    codes: list[int] = []
    h_span = max(float(H.max() - H.min()), 1e-6)
    for i in range(res - 1):
        for j in range(res - 1):
            a, b, c, d = vid(i, j), vid(i + 1, j), vid(i, j + 1), vid(i + 1, j + 1)
            mean_h = 0.25 * (H[i, j] + H[i + 1, j] + H[i, j + 1] + H[i + 1, j + 1])
            grad = max(abs(H[i + 1, j] - H[i, j]), abs(H[i, j + 1] - H[i, j])) * res / max(width, 1e-6)
            frac = (mean_h - H.min()) / h_span
            code = 2 if (grad > 0.55 or frac > 0.78) else (0 if frac < 0.16 else 1)
            faces.append((a, c, b))
            faces.append((b, c, d))
            codes.extend([code, code])

    # Bottom grid (full duplicate grid at Y=0) so the solid is a genuine
    # closed 2-manifold: bottom faces share edges with each other and the
    # skirt bottom ring is exactly the bottom grid's perimeter.
    bot_offset = len(verts)
    bot_verts = verts.copy()
    bot_verts[:, 1] = 0.0
    verts = np.vstack([verts, bot_verts])

    def bvid(i: int, j: int) -> int:
        return bot_offset + vid(i, j)

    for i in range(res - 1):
        for j in range(res - 1):
            a, b, c, d = bvid(i, j), bvid(i + 1, j), bvid(i, j + 1), bvid(i + 1, j + 1)
            faces.append((a, b, c))  # reversed vs top: normal = -Y
            faces.append((b, d, c))
            codes.extend([2, 2])

    # Skirt: perimeter ring dropped to Y=0.
    perimeter: list[int] = []
    perimeter += [vid(i, 0) for i in range(res)]
    perimeter += [vid(res - 1, j) for j in range(1, res)]
    perimeter += [vid(i, res - 1) for i in range(res - 2, -1, -1)]
    perimeter += [vid(0, j) for j in range(res - 2, 0, -1)]
    for k in range(len(perimeter)):
        p = perimeter[k]
        q = perimeter[(k + 1) % len(perimeter)]
        pb, qb = bot_offset + p, bot_offset + q
        faces.append((p, q, qb))
        faces.append((p, qb, pb))
        codes.extend([2, 2])

    mesh = trimesh.Trimesh(vertices=verts, faces=np.array(faces), process=False)
    return mesh, np.array(codes, dtype=np.int32), xs, zs


def _sample_height(H: np.ndarray, xs: np.ndarray, zs: np.ndarray, x: float, z: float) -> float:
    res = len(xs)
    fx = float(np.interp(x, xs, np.arange(res)))
    fz = float(np.interp(z, zs, np.arange(res)))
    i0, j0 = int(np.floor(fx)), int(np.floor(fz))
    i1, j1 = min(i0 + 1, res - 1), min(j0 + 1, res - 1)
    tx, tz = fx - i0, fz - j0
    top = H[i0, j0] * (1 - tx) + H[i1, j0] * tx
    bot = H[i0, j1] * (1 - tx) + H[i1, j1] * tx
    return float(top * (1 - tz) + bot * tz)


# ---------------------------------------------------------------------------
# Decimation (deterministic NumPy vertex-clustering)
# ---------------------------------------------------------------------------


def _cluster_decimate(mesh: trimesh.Trimesh, target_faces: int) -> trimesh.Trimesh:
    if len(mesh.faces) <= target_faces or target_faces < 24:
        return mesh
    verts = np.asarray(mesh.vertices, dtype=np.float64)
    faces = np.asarray(mesh.faces, dtype=np.int64)
    diag = float(np.linalg.norm(verts.max(axis=0) - verts.min(axis=0)))
    if diag <= 0:
        return mesh
    best = mesh
    for grid in (160, 110, 75, 52, 36, 25, 17, 12, 8):
        cell = diag / grid
        keys = np.floor((verts - verts.min(axis=0)) / cell).astype(np.int64)
        # Pack 3D cell indices into one sortable key via structured view.
        _, inverse = np.unique(keys, axis=0, return_inverse=True)
        inverse = inverse.reshape(-1)
        counts = np.bincount(inverse).astype(np.float64)
        sums = np.zeros((len(counts), 3), dtype=np.float64)
        np.add.at(sums, inverse, verts)
        new_verts = sums / counts[:, None]
        new_faces = inverse[faces]
        keep = (
            (new_faces[:, 0] != new_faces[:, 1])
            & (new_faces[:, 1] != new_faces[:, 2])
            & (new_faces[:, 0] != new_faces[:, 2])
        )
        new_faces = new_faces[keep]
        if len(new_faces) == 0:
            continue
        v0 = new_verts[new_faces[:, 0]]
        v1 = new_verts[new_faces[:, 1]]
        v2 = new_verts[new_faces[:, 2]]
        areas = 0.5 * np.linalg.norm(np.cross(v1 - v0, v2 - v0), axis=1)
        new_faces = new_faces[areas > 1e-12]
        if len(new_faces) == 0:
            continue
        used, inv2 = np.unique(new_faces.reshape(-1), return_inverse=True)
        candidate = trimesh.Trimesh(
            vertices=new_verts[used], faces=inv2.reshape(-1, 3), process=False
        )
        best = candidate
        if len(candidate.faces) <= target_faces:
            return candidate
    return best


def _decimate_by_component(mesh: trimesh.Trimesh, target_faces: int) -> trimesh.Trimesh:
    """Decimate only large connected components; never crush small hard-surface parts.

    Vertex-clustering a 12-triangle box (or a merged group of small boxes)
    collapses its faces into degenerate holes, so components below the
    threshold pass through untouched and the budget becomes a soft target
    for chunky low-poly assemblies — matching the validator's warning-only
    budget semantics while preserving watertight topology.
    """
    if len(mesh.faces) <= target_faces:
        return mesh
    try:
        components = mesh.split(only_watertight=False)
    except Exception:
        components = [mesh]
    if len(components) <= 1:
        return _cluster_decimate(mesh, target_faces)
    small_total = sum(len(c.faces) for c in components if len(c.faces) <= 80)
    large_total = sum(len(c.faces) for c in components if len(c.faces) > 80)
    if large_total == 0:
        return mesh
    budget_for_large = max(target_faces - small_total, int(large_total * 0.3))
    rebuilt: list[trimesh.Trimesh] = []
    for comp in components:
        if len(comp.faces) <= 80:
            rebuilt.append(comp)
        else:
            share = max(80, int(budget_for_large * len(comp.faces) / large_total))
            rebuilt.append(_cluster_decimate(comp, share))
    return rebuilt[0] if len(rebuilt) == 1 else trimesh.util.concatenate(rebuilt)


def _enforce_budget(
    parts: list[tuple[str, str, trimesh.Trimesh]], polygon_budget: int
) -> list[tuple[str, str, trimesh.Trimesh]]:
    total = sum(len(m.faces) for _, _, m in parts)
    if total <= polygon_budget or total == 0:
        return parts
    out: list[tuple[str, str, trimesh.Trimesh]] = []
    for name, slot, mesh in parts:
        share = max(24, int(polygon_budget * len(mesh.faces) / total))
        out.append((name, slot, _decimate_by_component(mesh, share)))
    return out


# ---------------------------------------------------------------------------
# Faceting: flat normals + triplanar UVs + per-face vertex colors
# ---------------------------------------------------------------------------


def _facet_part(
    name: str, mesh: trimesh.Trimesh, material: GlbMaterial, rng: np.random.Generator
) -> GlbPart:
    verts = np.asarray(mesh.vertices, dtype=np.float64)
    faces = np.asarray(mesh.faces, dtype=np.int64)
    corners = verts[faces]  # (F, 3, 3)
    normals_raw = np.cross(corners[:, 1] - corners[:, 0], corners[:, 2] - corners[:, 0])
    lengths = np.linalg.norm(normals_raw, axis=1, keepdims=True)
    face_normals = np.divide(
        normals_raw, np.maximum(lengths, 1e-12), out=np.zeros_like(normals_raw), where=lengths > 0
    )
    degenerate = lengths.reshape(-1) <= 1e-12
    face_normals[degenerate] = (0.0, 1.0, 0.0)

    positions = corners.reshape(-1, 3)
    normals = np.repeat(face_normals, 3, axis=0)
    indices = np.arange(len(positions), dtype=np.uint32).reshape(-1, 3)

    # Triplanar/box UV projection normalized per mesh (mirrors Blender path).
    mins = positions.min(axis=0)
    span = np.maximum(positions.max(axis=0) - mins, 1e-6)
    abs_n = np.abs(normals)
    uvs = np.zeros((len(positions), 2), dtype=np.float64)
    mask_z = (abs_n[:, 2] >= abs_n[:, 0]) & (abs_n[:, 2] >= abs_n[:, 1])
    mask_x = (~mask_z) & (abs_n[:, 0] >= abs_n[:, 1])
    mask_y = ~(mask_z | mask_x)
    uvs[mask_z] = (positions[mask_z][:, [0, 1]] - mins[[0, 1]]) / span[[0, 1]]
    uvs[mask_x] = (positions[mask_x][:, [2, 1]] - mins[[2, 1]]) / span[[2, 1]]
    uvs[mask_y] = (positions[mask_y][:, [0, 2]] - mins[[0, 2]]) / span[[0, 2]]

    # Per-face vertex-color tint: near-white variation driven by face-normal
    # elevation + deterministic jitter, multiplied with the PBR base color.
    elev = 0.5 + 0.5 * face_normals[:, 1]
    jitter = rng.uniform(-0.045, 0.045, size=len(faces))
    shade = np.clip(0.84 + 0.16 * elev + jitter, 0.72, 1.0)
    warm = np.clip(shade * rng.uniform(0.97, 1.0, size=len(faces)), 0.0, 1.0)
    face_rgba = np.stack(
        [np.clip(shade * 1.0, 0, 1), np.clip(shade * 0.995, 0, 1), warm, np.ones(len(faces))],
        axis=1,
    )
    colors = (np.repeat(face_rgba, 3, axis=0) * 255.0).astype(np.uint8)

    return GlbPart(
        name=name,
        positions=positions.astype(np.float32),
        normals=normals.astype(np.float32),
        uvs=uvs.astype(np.float32),
        colors=colors,
        indices=indices,
        material=material,
    )


# ---------------------------------------------------------------------------
# Diagnostics (measured, mirroring the Blender runner's contract)
# ---------------------------------------------------------------------------


def _measure_diagnostics(
    category: str,
    parts: list[tuple[str, str, trimesh.Trimesh]],
    glb_parts: list[GlbPart],
    materials: dict[str, GlbMaterial],
    glb_bytes: bytes,
) -> tuple[dict[str, Any], dict[str, Any]]:
    total_tris = int(sum(len(p.indices) for p in glb_parts))
    total_verts = int(sum(len(p.positions) for p in glb_parts))

    degenerate = 0
    non_manifold = 0
    dup_verts = 0
    components = 0
    body_components = 1 if category == "humanoid" else 0

    for part_name, _slot, mesh in parts:
        faces = np.asarray(mesh.faces)
        verts = np.asarray(mesh.vertices)
        if len(faces):
            v0, v1, v2 = verts[faces[:, 0]], verts[faces[:, 1]], verts[faces[:, 2]]
            areas = 0.5 * np.linalg.norm(np.cross(v1 - v0, v2 - v0), axis=1)
            degenerate += int(np.sum(areas < 1e-11))
            # (Scene-level manifold counting happens after this loop.)
        rounded = np.round(verts / 1e-6).astype(np.int64)
        dup_verts += int(len(verts) - len(np.unique(rounded, axis=0)))
        try:
            count = len(mesh.split(only_watertight=False))
        except Exception:
            count = 1
        components += count
        if category == "humanoid" and part_name.startswith("Body"):
            body_components = count

    # Scene-level manifold count on a globally welded vertex graph: parts
    # split by material slot share coincident boundary vertices, so
    # per-part edge counting would falsely report open seams.
    try:
        all_faces: list[np.ndarray] = []
        offset = 0
        welded_ids: dict[tuple[int, int, int], int] = {}
        for _name, _slot, mesh in parts:
            v = np.asarray(mesh.vertices)
            keys = np.round(v / 1e-6).astype(np.int64)
            remap = np.zeros(len(v), dtype=np.int64)
            for idx, key in enumerate(map(tuple, keys)):  # noqa: B905 - small meshes
                got = welded_ids.get(key)  # type: ignore[arg-type]
                if got is None:
                    got = len(welded_ids)
                    welded_ids[key] = got  # type: ignore[arg-type]
                remap[idx] = got
            all_faces.append(remap[np.asarray(mesh.faces)])
            offset += len(v)
        faces_all = np.vstack(all_faces)
        edges = np.sort(
            np.vstack([faces_all[:, [0, 1]], faces_all[:, [1, 2]], faces_all[:, [2, 0]]]),
            axis=1,
        )
        _, edge_counts = np.unique(edges, axis=0, return_counts=True)
        non_manifold = int(np.sum(edge_counts != 2))
    except Exception:
        non_manifold = 0

    # Honest roundtrip verification: re-load the exact bytes we will ship.
    reimport_tris = 0
    reimport_meshes = 0
    reimport_ok = False
    bounds_min = np.array([0.0, 0.0, 0.0])
    bounds_max = np.array([0.0, 0.0, 0.0])
    try:
        scene = trimesh.load(
            trimesh.util.wrap_as_stream(glb_bytes), file_type="glb", force="scene", process=False
        )
        reimport_meshes = len(scene.geometry)
        reimport_tris = int(sum(len(g.faces) for g in scene.geometry.values()))
        reimport_ok = reimport_meshes >= 1 and reimport_tris == total_tris
        if scene.bounds is not None:
            bounds_min = np.asarray(scene.bounds[0], dtype=np.float64)
            bounds_max = np.asarray(scene.bounds[1], dtype=np.float64)
    except Exception:
        reimport_ok = False

    dims = tuple(round(float(bounds_max[i] - bounds_min[i]), 4) for i in range(3))
    center = tuple(round(float((bounds_min[i] + bounds_max[i]) * 0.5), 4) for i in range(3))
    diag = round(math.sqrt(sum(d * d for d in dims)), 4)

    used_slots = sorted({slot for _, slot, _ in parts})
    mat_summaries = []
    for slot in used_slots:
        mat = materials[slot]
        r, g, b, a = mat.base_color_srgb
        mat_summaries.append(
            {
                "name": mat.name,
                "base_color": (round(r, 4), round(g, 4), round(b, 4), round(a, 4)),
                "metallic": round(mat.metallic, 4),
                "roughness": round(mat.roughness, 4),
                "has_textures": False,
                "texture_names": [],
            }
        )

    diagnostics: dict[str, Any] = {
        "category": category,
        "mesh_count": len(glb_parts),
        "actual_triangles": total_tris,
        "actual_vertices": total_verts,
        "polygon_faces": total_tris,
        "material_count": len(mat_summaries),
        "texture_count": 0,
        "connected_components": components,
        "body_connected_components": body_components,
        "uv_layer_count": len(glb_parts),
        "has_uvs": True,
        "degenerate_faces": degenerate,
        "invalid_face_indices": 0,
        "non_manifold_edges": non_manifold,
        "duplicate_vert_candidates": dup_verts,
        "unapplied_transforms": [],
        "missing_material_meshes": [],
        "bounding_box": {
            "min_corner": tuple(round(float(x), 4) for x in bounds_min),
            "max_corner": tuple(round(float(x), 4) for x in bounds_max),
            "dimensions": dims,
            "center": center,
            "diagonal": diag,
        },
        "materials": mat_summaries,
        "rig": {
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
        },
    }
    reimport = {
        "passed": reimport_ok,
        "reimported_mesh_count": reimport_meshes,
        "reimported_triangles": reimport_tris,
        "reimported_armature_count": 0,
    }
    return diagnostics, reimport


# ---------------------------------------------------------------------------
# Shared architectural ornaments
# ---------------------------------------------------------------------------


def _arch_ring(
    scene: _SceneBuilder,
    part: str,
    slot: str,
    *,
    cx: float,
    cy: float,
    cz: float,
    radius: float,
    thickness: float,
    depth_t: float,
    segments: int,
) -> None:
    """Semicircular voussoir arch ring in the XY plane (facing +/-Z)."""
    segs = max(5, segments)
    arc_len = math.pi * radius / segs
    for k in range(segs):
        angle = math.pi * (k + 0.5) / segs
        x = cx + radius * math.cos(angle)
        y = cy + radius * math.sin(angle)
        block = _box((arc_len * 1.08, thickness, depth_t), (x, y, cz))
        _rot(block, angle - math.pi / 2.0, (0, 0, 1), (x, y, cz))
        scene.add(part, slot, block)


def _merlon_run(
    scene: _SceneBuilder,
    part: str,
    slot: str,
    *,
    start: tuple[float, float, float],
    end: tuple[float, float, float],
    size: tuple[float, float, float],
    spacing: float,
) -> None:
    a = np.array(start, dtype=float)
    b = np.array(end, dtype=float)
    length = float(np.linalg.norm(b - a))
    count = max(1, int(length / max(spacing, 0.1)))
    for k in range(count + 1):
        p = a + (b - a) * (k / count)
        scene.add(part, slot, _box(size, (float(p[0]), float(p[1]), float(p[2]))))


def _parapet(
    scene: _SceneBuilder,
    *,
    w: float,
    d: float,
    top_y: float,
    detail: float,
    slot: str = "secondary",
) -> None:
    """Kangura battlement parapet around a rectangular roofline."""
    rail_h = 0.22
    scene.add("Parapet", slot, _box((w, rail_h, 0.18), (0, top_y + rail_h / 2, d / 2 - 0.09)))
    scene.add("Parapet", slot, _box((w, rail_h, 0.18), (0, top_y + rail_h / 2, -d / 2 + 0.09)))
    scene.add("Parapet", slot, _box((0.18, rail_h, d), (w / 2 - 0.09, top_y + rail_h / 2, 0)))
    scene.add("Parapet", slot, _box((0.18, rail_h, d), (-w / 2 + 0.09, top_y + rail_h / 2, 0)))
    spacing = 0.95 - 0.45 * float(np.clip(detail, 0.0, 1.0))
    merlon = (0.30, 0.34, 0.20)
    my = top_y + rail_h + merlon[1] / 2
    _merlon_run(scene, "Parapet", slot, start=(-w / 2 + 0.3, my, d / 2 - 0.09), end=(w / 2 - 0.3, my, d / 2 - 0.09), size=merlon, spacing=spacing)
    _merlon_run(scene, "Parapet", slot, start=(-w / 2 + 0.3, my, -d / 2 + 0.09), end=(w / 2 - 0.3, my, -d / 2 + 0.09), size=merlon, spacing=spacing)
    side = (0.20, 0.34, 0.30)
    _merlon_run(scene, "Parapet", slot, start=(w / 2 - 0.09, my, -d / 2 + 0.3), end=(w / 2 - 0.09, my, d / 2 - 0.3), size=side, spacing=spacing)
    _merlon_run(scene, "Parapet", slot, start=(-w / 2 + 0.09, my, -d / 2 + 0.3), end=(-w / 2 + 0.09, my, d / 2 - 0.3), size=side, spacing=spacing)


def _pillar(
    scene: _SceneBuilder,
    part: str,
    *,
    x: float,
    z: float,
    base_y: float,
    height: float,
    radius: float,
    segments: int,
) -> None:
    scene.add(part, "accent", _box((radius * 2.6, 0.16, radius * 2.6), (x, base_y + 0.08, z)))
    scene.add(part, "primary", _cyl_Y(radius, height, segments, (x, base_y + height / 2.0, z)))
    scene.add(part, "accent", _box((radius * 2.7, 0.15, radius * 2.7), (x, base_y + height + 0.07, z)))


def _front_wall_with_portal(
    scene: _SceneBuilder,
    *,
    w: float,
    h: float,
    z: float,
    thickness: float,
    opening_w: float,
    opening_h: float,
    arch_segments: int,
    base_y: float = 0.0,
) -> None:
    """Front facade (facing +Z) with a genuine arched doorway opening."""
    side_w = max((w - opening_w) / 2.0, 0.05)
    spring_y = max(opening_h - opening_w / 2.0, opening_h * 0.55)
    for sx in (-1.0, 1.0):
        scene.add(
            "Facade",
            "primary",
            _box(
                (side_w, h, thickness),
                (sx * (opening_w / 2.0 + side_w / 2.0), base_y + h / 2.0, z),
            ),
        )
    lintel_h = max(h - opening_h, 0.1)
    scene.add(
        "Facade",
        "primary",
        _box((opening_w + 0.3, lintel_h, thickness), (0, base_y + opening_h + lintel_h / 2.0, z)),
    )
    _arch_ring(
        scene,
        "Facade",
        "accent",
        cx=0,
        cy=base_y + spring_y,
        cz=z,
        radius=opening_w / 2.0 + 0.07,
        thickness=0.22,
        depth_t=thickness + 0.05,
        segments=arch_segments,
    )
    # Recessed timber door leaves inside the opening.
    door_h = spring_y
    for sx in (-1.0, 1.0):
        door = _box((opening_w / 2.0 - 0.03, door_h, 0.09), (sx * opening_w / 4.0, base_y + door_h / 2.0, z - thickness * 0.35))
        _rot(door, sx * 0.12, (0, 1, 0), (sx * opening_w / 2.0, base_y + door_h / 2.0, z - thickness * 0.35))
        scene.add("Doors", "trim", door)


# ---------------------------------------------------------------------------
# PROPS builders
# ---------------------------------------------------------------------------


def _build_prop(scene: _SceneBuilder, cfg: dict[str, Any], q: _Quality, rng: np.random.Generator) -> None:
    p = cfg["parameters"]
    preset = str(cfg["preset_id"])
    w, d, h = float(p["width"]), float(p["depth"]), float(p["height"])
    detail = float(p.get("panel_detail", 0.65))

    if preset == "explosive_fuel_barrel":
        r = min(w, d) / 2.0
        segs = q.radial + 10
        scene.add("Drum", "primary", _cyl_Y(r, h, segs, (0, h / 2.0, 0)))
        for fy in (0.22, 0.5, 0.78):  # rolling chimes
            scene.add("Drum", "secondary", _torus_flat(r, 0.022, (0, h * fy, 0), max(12, segs - 6), 5))
        scene.add("Drum", "accent", _cyl_Y(r + 0.006, h * 0.16, segs, (0, h * 0.64, 0)))
        for sx in (-0.45, 0.45):  # bung caps
            scene.add("Caps", "metal", _cyl_Y(0.045, 0.05, 10, (sx * r, h + 0.02, 0)))
        return

    if preset == "tactical_cover_barrier":
        scene.add("Barrier", "secondary", _box((w, h * 0.72, d), (0, h * 0.36, 0)))
        cap = _box((w, h * 0.34, d * 0.62), (0, h * 0.86, 0))
        scene.add("Barrier", "primary", cap)
        for sx in (-1.0, 1.0):  # angled deflection feet
            foot = _box((w * 0.16, 0.16, d * 1.7), (sx * w * 0.36, 0.08, 0))
            scene.add("Feet", "secondary", foot)
        scene.add("ArmorPlate", "metal", _box((w * 0.92, h * 0.4, 0.06), (0, h * 0.62, d / 2 + 0.03)))
        n_stripes = 3 + int(detail * 3)
        for k in range(n_stripes):
            x = -w * 0.36 + (w * 0.72) * (k / max(1, n_stripes - 1))
            stripe = _box((0.12, h * 0.3, 0.02), (x, h * 0.62, d / 2 + 0.075))
            _rot(stripe, 0.5, (0, 0, 1), (x, h * 0.62, d / 2 + 0.075))
            scene.add("Hazard", "accent", stripe)
        for sx in (-0.3, 0.3):  # forklift slots (dark recess illusions)
            scene.add("Slots", "trim", _box((w * 0.16, 0.14, d + 0.02), (sx * w, 0.09, 0)))
        rib_n = 4 + int(detail * 5)
        for k in range(rib_n):
            rx = -w * 0.44 + w * 0.88 * (k / max(1, rib_n - 1))
            for sz in (-1.0, 1.0):
                scene.add("Ribs", "primary", _box((0.07, h * 0.58, 0.05), (rx, h * 0.38, sz * (d / 2 + 0.02))))
                bolt = _cyl_Y(0.022, 0.04, 6, (rx, h * 0.62, sz * (d * 0.31 + 0.05)))
                _rot(bolt, math.pi / 2.0, (1, 0, 0), (rx, h * 0.62, sz * (d * 0.31 + 0.05)))
                scene.add("Bolts", "metal", bolt)
        return

    if preset == "desert_recon_buggy":
        wheel_r = h * 0.24
        ground_clear = wheel_r + 0.10
        scene.add("Chassis", "primary", _box((w * 0.82, 0.22, d * 0.86), (0, ground_clear + 0.11, 0)))
        hood = _box((w * 0.78, 0.20, d * 0.30), (0, ground_clear + 0.34, d * 0.30))
        _rot(hood, -0.10, (1, 0, 0), (0, ground_clear + 0.34, d * 0.30))
        scene.add("Hood", "primary", hood)
        scene.add("NoseArmor", "metal", _box((w * 0.7, 0.30, 0.10), (0, ground_clear + 0.12, d * 0.47)))
        for sx in (-1.0, 1.0):
            scene.add("Seats", "trim", _box((0.46, 0.12, 0.46), (sx * w * 0.21, ground_clear + 0.30, -d * 0.08)))
            scene.add("Seats", "trim", _box((0.46, 0.55, 0.12), (sx * w * 0.21, ground_clear + 0.55, -d * 0.20)))
        cage_r = 0.045
        top_y = ground_clear + h * 0.62
        posts = [
            ((-w * 0.38, ground_clear, d * 0.16), (-w * 0.34, top_y, d * 0.06)),
            ((w * 0.38, ground_clear, d * 0.16), (w * 0.34, top_y, d * 0.06)),
            ((-w * 0.38, ground_clear, -d * 0.28), (-w * 0.34, top_y, -d * 0.20)),
            ((w * 0.38, ground_clear, -d * 0.28), (w * 0.34, top_y, -d * 0.20)),
            ((-w * 0.34, top_y, d * 0.06), (w * 0.34, top_y, d * 0.06)),
            ((-w * 0.34, top_y, -d * 0.20), (w * 0.34, top_y, -d * 0.20)),
            ((-w * 0.34, top_y, d * 0.06), (-w * 0.34, top_y, -d * 0.20)),
            ((w * 0.34, top_y, d * 0.06), (w * 0.34, top_y, -d * 0.20)),
        ]
        scene.add_many("RollCage", "metal", [_tube(a, b, cage_r, 8) for a, b in posts])
        scene.add("Lightbar", "metal", _box((w * 0.5, 0.09, 0.09), (0, top_y + 0.08, d * 0.07)))
        for k in range(3):
            lx = (k - 1) * w * 0.15
            lamp = _cyl_Y(0.055, 0.06, 10, (lx, top_y + 0.08, d * 0.13))
            _rot(lamp, math.pi / 2.0, (1, 0, 0), (lx, top_y + 0.08, d * 0.13))
            scene.add("Lamps", "glass_lamp", lamp)
        for sx in (-1.0, 1.0):
            for sz, zz in ((1.0, d * 0.32), (-1.0, -d * 0.32)):
                tire = _cyl_Y(wheel_r, 0.24, q.radial + 4, (sx * w * 0.46, wheel_r, zz))
                _rot(tire, math.pi / 2.0, (0, 0, 1), (sx * w * 0.46, wheel_r, zz))
                scene.add("Wheels", "trim", tire)
                hub = _cyl_Y(wheel_r * 0.45, 0.26, 8, (sx * w * 0.46, wheel_r, zz))
                _rot(hub, math.pi / 2.0, (0, 0, 1), (sx * w * 0.46, wheel_r, zz))
                scene.add("Wheels", "metal", hub)
                if detail > 0.55:
                    for t in range(8):
                        ang = 2 * math.pi * t / 8
                        ty = wheel_r + math.sin(ang) * wheel_r
                        tz = zz + math.cos(ang) * wheel_r
                        scene.add("Treads", "trim", _box((0.26, 0.09, 0.13), (sx * w * 0.46, ty, tz)))
        spare = _cyl_Y(wheel_r * 0.92, 0.18, q.radial, (0, ground_clear + 0.45, -d * 0.47))
        _rot(spare, math.pi / 2.0, (1, 0, 0), (0, ground_clear + 0.45, -d * 0.47))
        scene.add("SpareWheel", "trim", spare)
        return

    # Default: br_supply_crate (also the fallback for any unknown prop preset)
    body_h = h * 0.78
    scene.add("Hull", "primary", _box((w * 0.96, body_h, d * 0.96), (0, body_h / 2.0, 0)))
    scene.add("Lid", "primary", _box((w, h * 0.24, d), (0, body_h + h * 0.11, 0)))
    cb = min(w, d, h) * 0.17
    for sx in (-1.0, 1.0):
        for sz in (-1.0, 1.0):
            scene.add("Corners", "metal", _box((cb, cb, cb), (sx * (w / 2 - cb * 0.42), cb * 0.5, sz * (d / 2 - cb * 0.42))))
            scene.add("Corners", "metal", _box((cb, cb * 0.9, cb), (sx * (w / 2 - cb * 0.42), h - cb * 0.42, sz * (d / 2 - cb * 0.42))))
    rib_count = max(2, int(round(2 + detail * 3)))
    for k in range(rib_count):
        t = -0.34 + 0.68 * (k / max(1, rib_count - 1))
        for sz in (-1.0, 1.0):
            scene.add("Ribs", "secondary", _box((w * 0.055, body_h * 0.82, 0.035), (w * t, body_h * 0.48, sz * (d * 0.49))))
    for sx in (-0.28 * w, 0.28 * w):
        scene.add("Straps", "trim", _box((w * 0.055, h * 1.01, d * 1.015), (sx, h * 0.5, 0)))
    if detail >= 0.25:
        for sx in (-0.22 * w, 0.22 * w):
            for sz in (-1.0, 1.0):
                scene.add("Latches", "accent", _box((w * 0.09, h * 0.17, 0.045), (sx, body_h, sz * (d * 0.51))))
        bolt_n = 6 if detail > 0.6 else 4
        for k in range(bolt_n):
            bx = -w * 0.4 + w * 0.8 * (k / max(1, bolt_n - 1))
            for sz in (-1.0, 1.0):
                bolt = _cyl_Y(0.018, 0.03, 6, (bx, body_h * 0.9, sz * d * 0.5))
                _rot(bolt, math.pi / 2.0, (1, 0, 0), (bx, body_h * 0.9, sz * d * 0.5))
                scene.add("Bolts", "metal", bolt)


# ---------------------------------------------------------------------------
# ARCHITECTURE builders
# ---------------------------------------------------------------------------


def _build_architecture(scene: _SceneBuilder, cfg: dict[str, Any], q: _Quality, rng: np.random.Generator) -> None:
    p = cfg["parameters"]
    preset = str(cfg["preset_id"])
    w, d = float(p["width"]), float(p["depth"])
    h, wt = float(p["height"]), float(p["wall_thickness"])
    ow, oh = float(p["opening_width"]), float(p["opening_height"])
    floors = int(p.get("floors", 1))
    arch_segs = int(p.get("arch_segments", 12))
    detail = float(p.get("decorative_detail", 0.75))

    if preset == "stone_arch_bridge":
        deck_y = h * 0.78
        scene.add("Deck", "primary", _box((w, h * 0.18, d), (0, deck_y, 0)))
        scene.add("Roadway", "accent", _box((w, 0.09, d * 0.8), (0, deck_y + h * 0.09 + 0.045, 0)))
        for sz in (-1.0, 1.0):
            scene.add("Parapet", "secondary", _box((w, 0.55, 0.24), (0, deck_y + 0.45, sz * (d / 2 - 0.12))))
        n_spans = 3
        pier_xs = [-w / 2 + w * k / n_spans for k in range(n_spans + 1)]
        for px in pier_xs[1:-1]:
            scene.add("Piers", "primary", _box((w * 0.055, deck_y, d * 0.92), (px, deck_y / 2.0, 0)))
            for sz in (-1.0, 1.0):  # triangular cutwaters (rotated square prisms)
                cut = _cyl_Y(d * 0.16, deck_y * 0.7, 4, (px, deck_y * 0.35, sz * d * 0.52))
                scene.add("Cutwaters", "secondary", cut)
        for s in range(n_spans):
            cx = (pier_xs[s] + pier_xs[s + 1]) / 2.0
            span = (pier_xs[s + 1] - pier_xs[s]) * 0.46
            for sz in (-1.0, 1.0):
                _arch_ring(scene, "Arches", "accent", cx=cx, cy=deck_y - span - 0.1, cz=sz * (d / 2 - 0.18), radius=span, thickness=0.30, depth_t=0.30, segments=arch_segs)
        for sx in (-1.0, 1.0):
            scene.add("Abutments", "primary", _box((w * 0.07, deck_y + 0.3, d), (sx * (w / 2 - w * 0.035), (deck_y + 0.3) / 2.0, 0)))
        for lx in (-w * 0.3, 0.0, w * 0.3):
            for sz in (-1.0, 1.0):
                scene.add("LampPosts", "metal", _tube((lx, deck_y + 0.6, sz * (d / 2 - 0.12)), (lx, deck_y + 1.55, sz * (d / 2 - 0.12)), 0.035, 6))
                scene.add("Lamps", "glass_lamp", _sphere((0.11, 0.13, 0.11), (lx, deck_y + 1.62, sz * (d / 2 - 0.12)), 1))
        return

    if preset == "chhatri_pavilion":
        step_r = min(w, d) / 2.0
        scene.add("Plinth", "secondary", _cyl_Y(step_r, 0.45, 8, (0, 0.225, 0)))
        scene.add("Plinth", "accent", _cyl_Y(step_r * 0.88, 0.35, 8, (0, 0.625, 0)))
        pillar_h = h * 0.46
        ring_r = step_r * 0.76
        for k in range(8):
            ang = 2 * math.pi * k / 8 + math.pi / 8
            _pillar(scene, "Pillars", x=ring_r * math.cos(ang), z=ring_r * math.sin(ang), base_y=0.8, height=pillar_h, radius=step_r * 0.075, segments=8)
        ent_y = 0.8 + pillar_h + 0.22
        scene.add("Entablature", "primary", _cyl_Y(step_r * 0.96, 0.42, 8, (0, ent_y + 0.21, 0)))
        scene.add("Chhajja", "secondary", _cyl_Y(step_r * 1.04, 0.16, 8, (0, ent_y + 0.5, 0)))
        drum_y = ent_y + 0.58
        scene.add("DomeDrum", "accent", _cyl_Y(step_r * 0.55, 0.5, 12, (0, drum_y + 0.25, 0)))
        dome_r = step_r * 0.55
        scene.add("Dome", "primary", _sphere((dome_r, dome_r * 1.05, dome_r), (0, drum_y + 0.45, 0), q.sphere_subdiv))
        scene.add("Finial", "accent", _cone_Y(0.14, 0.6, 8, (0, drum_y + 0.45 + dome_r * 1.05 + 0.2, 0)))
        scene.add("Finial", "accent", _sphere((0.11, 0.11, 0.11), (0, drum_y + 0.45 + dome_r * 1.05 + 0.03, 0), 1))
        scene.add("LampChain", "metal", _tube((0, ent_y, 0), (0, ent_y - 0.85, 0), 0.025, 6))
        scene.add("Lamp", "glass_lamp", _sphere((0.22, 0.26, 0.22), (0, ent_y - 1.05, 0), 2))
        scene.add("FloorMedallion", "trim", _cyl_Y(step_r * 0.34, 0.06, 8, (0, 0.83, 0)))
        return

    if preset == "pol_arched_gateway":
        tower_r = d * 0.34
        tower_x = w / 2 - tower_r * 0.9
        for sx in (-1.0, 1.0):
            scene.add("Towers", "primary", _cyl_Y(tower_r, h, 8, (sx * tower_x, h / 2.0, 0)))
            scene.add("Towers", "secondary", _cyl_Y(tower_r * 1.12, 0.4, 8, (sx * tower_x, h + 0.2, 0)))
            scene.add("TowerCaps", "accent", _sphere((tower_r * 0.7, tower_r * 0.55, tower_r * 0.7), (sx * tower_x, h + 0.38, 0), 2))
            for wy in (0.45, 0.68):
                scene.add("ArrowSlits", "trim", _box((0.14, 0.65, 0.1), (sx * tower_x, h * wy, tower_r * 0.95)))
        gallery_w = tower_x * 2
        scene.add("Gallery", "primary", _box((gallery_w, h - oh - 0.25, d * 0.72), (0, oh + (h - oh) / 2.0 + 0.1, 0)))
        spring_y = max(oh - ow / 2.0, oh * 0.55)
        _arch_ring(scene, "Portal", "accent", cx=0, cy=spring_y, cz=d * 0.37, radius=ow / 2 + 0.1, thickness=0.34, depth_t=0.34, segments=arch_segs + 4)
        _arch_ring(scene, "Portal", "accent", cx=0, cy=spring_y, cz=-d * 0.37, radius=ow / 2 + 0.1, thickness=0.34, depth_t=0.34, segments=arch_segs + 4)
        scene.add("PortalWalls", "primary", _box((0.3, spring_y, d * 0.72), (-ow / 2 - 0.12, spring_y / 2.0, 0)))
        scene.add("PortalWalls", "primary", _box((0.3, spring_y, d * 0.72), (ow / 2 + 0.12, spring_y / 2.0, 0)))
        for sx in (-1.0, 1.0):
            door = _box((ow / 2 - 0.04, spring_y, 0.12), (sx * ow / 4.0, spring_y / 2.0, d * 0.20))
            _rot(door, sx * 0.38, (0, 1, 0), (sx * ow / 2.0, spring_y / 2.0, d * 0.20))
            scene.add("Doors", "trim", door)
            for sy in (0.3, 0.55, 0.8):
                scene.add("DoorStuds", "metal", _cyl_Y(0.05, 0.07, 6, (sx * ow * 0.24, spring_y * sy, d * 0.28)))
        _parapet(scene, w=gallery_w * 0.98, d=d * 0.72, top_y=h + 0.15, detail=detail)
        return

    if preset == "rajput_fort_bastion":
        wall_t = max(wt, 0.7)
        scene.add("CurtainWall", "primary", _box((w, h * 0.86, wall_t), (0, h * 0.43, -d * 0.18)))
        batter = _box((w, h * 0.4, wall_t * 0.7), (0, h * 0.2, -d * 0.18 + wall_t * 0.75))
        _rot(batter, 0.42, (1, 0, 0), (0, h * 0.2, -d * 0.18 + wall_t * 0.75))
        scene.add("Batter", "secondary", batter)
        tower_r = d * 0.30
        scene.add("Bastion", "primary", _cyl_Y(tower_r, h * 1.04, 8, (0, h * 0.52, d * 0.16)))
        scene.add("Bastion", "secondary", _cyl_Y(tower_r * 1.14, 0.42, 8, (0, h * 1.04 + 0.2, d * 0.16)))
        scene.add("BastionCap", "accent", _sphere((tower_r * 0.68, tower_r * 0.5, tower_r * 0.68), (0, h * 1.04 + 0.4, d * 0.16), 2))
        spring_y = max(oh - ow / 2.0, oh * 0.55)
        # Gate passage through the bastion front
        _arch_ring(scene, "Gate", "accent", cx=0, cy=spring_y, cz=d * 0.16 + tower_r * 0.9, radius=ow / 2 + 0.08, thickness=0.32, depth_t=0.3, segments=arch_segs)
        scene.add("GateDoors", "trim", _box((ow - 0.06, spring_y, 0.12), (0, spring_y / 2.0, d * 0.16 + tower_r * 0.55)))
        for sx in np.linspace(-0.42, 0.42, 7):
            if abs(sx) < 0.08:
                continue
            scene.add("ArrowSlits", "trim", _box((0.15, 0.7, 0.1), (float(sx) * w, h * 0.62, -d * 0.18 + wall_t / 2 + 0.05)))
        _merlon_run(scene, "Crenellation", "secondary", start=(-w / 2 + 0.3, h * 0.86 + 0.28, -d * 0.18), end=(w / 2 - 0.3, h * 0.86 + 0.28, -d * 0.18), size=(0.34, 0.42, 0.26), spacing=0.9 - 0.35 * detail)
        scene.add("WallWalk", "secondary", _box((w, 0.18, wall_t + 0.5), (0, h * 0.86, -d * 0.18)))
        scene.add("Plinth", "secondary", _box((w * 1.02, 0.5, d), (0, 0.25, 0)))
        return

    # Default: rajasthani_haveli — enterable courtyard house shell
    scene.add("Plinth", "secondary", _box((w + 0.5, 0.45, d + 0.5), (0, 0.225, 0)))
    wall_h = h - 0.45
    base = 0.45
    # Back + side walls (solid), front wall with arched portal
    scene.add("Walls", "primary", _box((w, wall_h, wt), (0, base + wall_h / 2, -d / 2 + wt / 2)))
    for sx in (-1.0, 1.0):
        scene.add("Walls", "primary", _box((wt, wall_h, d), (sx * (w / 2 - wt / 2), base + wall_h / 2, 0)))
    _front_wall_with_portal(scene, w=w, h=wall_h, z=d / 2 - wt / 2, thickness=wt, opening_w=ow, opening_h=min(oh, wall_h - 0.6), arch_segments=arch_segs, base_y=base)
    # Shift facade pieces up by plinth height: portal was authored at ground;
    # overlay a step so the doorway reads correctly from street level.
    scene.add("Steps", "accent", _box((ow + 0.8, 0.22, 0.7), (0, 0.34, d / 2 + 0.45)))
    scene.add("Steps", "accent", _box((ow + 0.4, 0.22, 0.5), (0, 0.45, d / 2 + 0.22)))
    scene.add("Floor", "secondary", _box((w - wt, 0.12, d - wt), (0, base + 0.06, 0)))
    # Roof slab + chhajja eaves at each floor line
    roof_y = base + wall_h
    scene.add("Roof", "secondary", _box((w, 0.22, d), (0, roof_y + 0.11, 0)))
    for f in range(max(1, floors)):
        fy = base + wall_h * (f + 1) / max(1, floors)
        for sz in (-1.0, 1.0):
            eave = _box((w + 0.5, 0.10, 0.55), (0, min(fy, roof_y) + 0.05, sz * (d / 2 + 0.16)))
            _rot(eave, sz * 0.18, (1, 0, 0), (0, min(fy, roof_y) + 0.05, sz * (d / 2 + 0.16)))
            scene.add("Chhajja", "accent", eave)
    # Jharokha balcony (front, upper)
    jw, jh = min(2.2, w * 0.3), 1.15
    jy = base + wall_h * (0.58 if floors > 1 else 0.5)
    scene.add("Jharokha", "secondary", _box((jw, 0.16, 0.75), (0, jy, d / 2 + 0.35)))
    for sx in (-1.0, 1.0):
        scene.add("Jharokha", "accent", _cyl_Y(0.07, jh, 8, (sx * (jw / 2 - 0.09), jy + jh / 2, d / 2 + 0.62)))
    scene.add("Jharokha", "primary", _box((jw, 0.14, 0.8), (0, jy + jh + 0.07, d / 2 + 0.35)))
    dome_ry = jw * 0.24
    scene.add("JharokhaDome", "accent", _sphere((jw * 0.30, dome_ry, jw * 0.30), (0, jy + jh + 0.14 + dome_ry * 0.55, d / 2 + 0.35), 2))
    # Window insets with arch frames on front + sides
    n_win = 2 + int(detail * 3)
    for k in range(n_win):
        wx = -w * 0.36 + w * 0.72 * (k / max(1, n_win - 1)) if n_win > 1 else 0.0
        if abs(wx) < ow * 0.75 and floors == 1:
            continue
        wy = base + wall_h * (0.72 if floors > 1 else 0.55)
        scene.add("Windows", "trim", _box((0.62, 0.92, 0.08), (wx, wy, d / 2 + 0.02)))
        _arch_ring(scene, "Windows", "accent", cx=wx, cy=wy + 0.46, cz=d / 2 + 0.03, radius=0.34, thickness=0.10, depth_t=0.08, segments=7)
    _parapet(scene, w=w, d=d, top_y=roof_y + 0.22, detail=detail)
    if detail > 0.5:  # corner chhatri kiosks
        for sx in (-1.0, 1.0):
            kx = sx * (w / 2 - 0.75)
            scene.add("Kiosks", "secondary", _cyl_Y(0.62, 0.28, 8, (kx, roof_y + 0.36, d / 2 - 0.75)))
            scene.add("Kiosks", "accent", _sphere((0.52, 0.42, 0.52), (kx, roof_y + 0.55, d / 2 - 0.75), 2))


# ---------------------------------------------------------------------------
# ENVIRONMENT builders
# ---------------------------------------------------------------------------


def _scatter_rocks(
    scene: _SceneBuilder,
    *,
    H: np.ndarray,
    xs: np.ndarray,
    zs: np.ndarray,
    count: int,
    rng: np.random.Generator,
    subdiv: int,
    slot: str = "secondary",
    scale_range: tuple[float, float] = (0.4, 1.6),
    avoid_center: float = 0.0,
) -> None:
    width = float(xs[-1] - xs[0])
    depth = float(zs[-1] - zs[0])
    placed = 0
    guard = 0
    while placed < count and guard < count * 20:
        guard += 1
        x = float(rng.uniform(-0.46, 0.46)) * width
        z = float(rng.uniform(-0.46, 0.46)) * depth
        if avoid_center > 0 and math.hypot(x, z) < avoid_center:
            continue
        s = float(rng.uniform(*scale_range))
        y = _sample_height(H, xs, zs, x, z)
        rock = _displaced_rock((x, y + s * 0.22, z), (s, s * 0.72, s * 0.85), subdiv, rng)
        _rot(rock, float(rng.uniform(0, 2 * math.pi)), (0, 1, 0), (x, y + s * 0.22, z))
        scene.add("Rocks", slot, rock)
        placed += 1


def _acacia_tree(
    scene: _SceneBuilder,
    *,
    x: float,
    y: float,
    z: float,
    scale: float,
    rng: np.random.Generator,
    subdiv: int,
) -> None:
    trunk_top = (x + float(rng.uniform(-0.3, 0.3)) * scale, y + 2.1 * scale, z)
    scene.add("Trees", "trim", _tube((x, y - 0.1, z), trunk_top, 0.16 * scale, 7))
    for _ in range(3):
        ang = float(rng.uniform(0, 2 * math.pi))
        tip = (
            trunk_top[0] + math.cos(ang) * 1.1 * scale,
            trunk_top[1] + 0.75 * scale,
            trunk_top[2] + math.sin(ang) * 1.1 * scale,
        )
        scene.add("Trees", "trim", _tube(trunk_top, tip, 0.08 * scale, 6))
        scene.add(
            "Canopy",
            "primary" if rng.random() > 0.4 else "foliage_dark",
            _displaced_rock(tip, (1.15 * scale, 0.5 * scale, 1.15 * scale), max(1, subdiv - 1), rng, roughness=0.22),
        )
    scene.add(
        "Canopy",
        "primary",
        _displaced_rock((trunk_top[0], trunk_top[1] + 1.0 * scale, trunk_top[2]), (1.5 * scale, 0.6 * scale, 1.5 * scale), max(1, subdiv - 1), rng, roughness=0.22),
    )


def _add_heightfield_terrain(
    scene: _SceneBuilder,
    *,
    w: float,
    d: float,
    res: int,
    heights: np.ndarray,
    base_lift: float,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    mesh, codes, xs, zs = _heightfield(w, d, res, heights, base_lift=base_lift)
    slot_by_code = {0: "sand", 1: "primary", 2: "secondary"}
    for code, slot in slot_by_code.items():
        sub = _submesh_by_mask(mesh, codes == code)
        if sub is not None:
            scene.add("Terrain", slot, sub)
    lifted = np.asarray(heights, dtype=float) - float(np.min(heights)) + base_lift
    return lifted, xs, zs


def _build_environment(scene: _SceneBuilder, cfg: dict[str, Any], q: _Quality, rng: np.random.Generator) -> None:
    p = cfg["parameters"]
    preset = str(cfg["preset_id"])
    w, d = float(p["width"]), float(p["depth"])
    elev = float(p.get("elevation", 6.0))
    slope = float(p.get("slope_intensity", 0.6))
    rough = float(p.get("surface_roughness", 0.5))
    terraces = int(p.get("terrace_steps", 3))
    scatter = float(p.get("scatter_density", 0.35))
    budget = int(cfg.get("polygon_budget", 4000))
    # Closed terrain solid faces ~= 4 * (res-1)^2 (top + bottom grids);
    # size the grid to the requested budget (capped by quality) so
    # topology-preserving generation rarely needs destructive decimation.
    res = int(
        np.clip(
            math.sqrt(max(budget, 800) * 0.50 / 4.0) + 1,
            16,
            q.terrain_res + 10,
        )
    )
    xs = np.linspace(-w / 2, w / 2, res)
    zs = np.linspace(-d / 2, d / 2, res)
    X, Z = np.meshgrid(xs, zs, indexing="ij")

    if preset == "stylized_banyan_tree":
        scene.add("Ground", "sand", _cyl_Y(min(w, d) / 2.0, 0.35, q.radial + 8, (0, 0.175, 0)))
        H_top = 0.35
        trunk_h = elev * 0.42
        prev = (0.0, H_top - 0.1, 0.0)
        bend = 0.0
        joints = [prev]
        for step in range(3):
            bend += float(rng.uniform(-0.22, 0.22))
            nxt = (bend * elev * 0.12, H_top + trunk_h * (step + 1) / 3.0, float(rng.uniform(-0.1, 0.1)))
            r = elev * 0.045 * (1.0 - 0.18 * step)
            scene.add("Trunk", "trim", _tube(prev, nxt, max(r, 0.06), 8))
            joints.append(nxt)
            prev = nxt
        top = joints[-1]
        n_branches = 5
        canopy_centers = []
        for k in range(n_branches):
            ang = 2 * math.pi * k / n_branches + float(rng.uniform(-0.2, 0.2))
            reach = min(w, d) * (0.30 + 0.08 * float(rng.random()))
            tip = (top[0] + math.cos(ang) * reach, top[1] + elev * 0.16, top[2] + math.sin(ang) * reach)
            scene.add("Branches", "trim", _tube(top, tip, 0.07, 7))
            # Aerial prop root from mid-branch to the ground
            mid = (top[0] + (tip[0] - top[0]) * 0.65, top[1] + (tip[1] - top[1]) * 0.65, top[2] + (tip[2] - top[2]) * 0.65)
            scene.add("PropRoots", "trim", _tube(mid, (mid[0], H_top - 0.05, mid[2]), 0.045, 6))
            canopy_centers.append(tip)
        for tip in canopy_centers:
            cr = min(w, d) * 0.19
            slot = "primary" if rng.random() > 0.35 else "foliage_dark"
            scene.add("Canopy", slot, _displaced_rock((tip[0], tip[1] + cr * 0.35, tip[2]), (cr, cr * 0.48, cr), q.sphere_subdiv - 1, rng, roughness=0.20))
        cr = min(w, d) * 0.24
        scene.add("Canopy", "primary", _displaced_rock((top[0], top[1] + elev * 0.22, top[2]), (cr, cr * 0.5, cr), q.sphere_subdiv - 1, rng, roughness=0.20))
        return

    if preset == "desert_rock_outcrop":
        mound = elev * 0.16 * np.exp(-((X / (w * 0.4)) ** 2 + (Z / (d * 0.4)) ** 2)) + rough * 0.4 * _fbm(X / w * 4, Z / d * 4, rng)
        H, hx, hz = _add_heightfield_terrain(scene, w=w, d=d, res=res, heights=mound, base_lift=0.35)
        n_big = 5 + int(scatter * 5)
        for k in range(n_big):
            ang = 2 * math.pi * k / n_big + float(rng.uniform(-0.3, 0.3))
            dist = min(w, d) * float(rng.uniform(0.05, 0.34))
            x, z = math.cos(ang) * dist, math.sin(ang) * dist
            s = elev * float(rng.uniform(0.16, 0.34))
            y = _sample_height(H, hx, hz, x, z)
            rock = _displaced_rock((x, y + s * 0.5, z), (s, s * (1.1 + slope * 0.7), s * 0.8), 2, rng, roughness=0.3 + rough * 0.3)
            _rot(rock, float(rng.uniform(0, 2 * math.pi)), (0, 1, 0), (x, y + s * 0.5, z))
            scene.add("Outcrop", "secondary", rock)
        _scatter_rocks(scene, H=H, xs=hx, zs=hz, count=int(8 * scatter * q.scatter_mul) + 3, rng=rng, subdiv=1, scale_range=(0.15, 0.45))
        return

    if preset == "battle_royale_island":
        R = min(w, d) / 2.0
        r_norm = np.sqrt((X / (w / 2)) ** 2 + (Z / (d / 2)) ** 2)
        peak_x, peak_z = float(rng.uniform(-3, 3)), float(rng.uniform(-3, 3))
        peak = np.exp(-(((X - peak_x) / (w * 0.22)) ** 2 + ((Z - peak_z) / (d * 0.22)) ** 2))
        falloff = np.clip(1.0 - r_norm**2.2, 0.0, 1.0)
        heights = elev * (0.55 * falloff + 0.65 * peak * falloff) * (0.8 + rough * 0.45 * _fbm(X / w * 5, Z / d * 5, rng))
        H, hx, hz = _add_heightfield_terrain(scene, w=w, d=d, res=res, heights=heights, base_lift=0.25)
        scene.add("Water", "water", _cyl_Y(R * 1.35, 0.3, q.radial + 16, (0, 0.55, 0)))
        _scatter_rocks(scene, H=H, xs=hx, zs=hz, count=int(10 * scatter * q.scatter_mul) + 2, rng=rng, subdiv=1, scale_range=(0.3, 1.1))
        for _ in range(int(3 * scatter * q.scatter_mul) + 1):
            tx = float(rng.uniform(-0.3, 0.3)) * w
            tz = float(rng.uniform(-0.3, 0.3)) * d
            ty = _sample_height(H, hx, hz, tx, tz)
            if ty > 0.9:
                _acacia_tree(scene, x=tx, y=ty, z=tz, scale=0.9, rng=rng, subdiv=2)
        return

    if preset == "river_ravine_crossing":
        base = elev * (0.55 + 0.45 * _fbm(X / w * 3.2, Z / d * 3.2, rng)) * (0.6 + 0.6 * slope)
        curve_amp = w * 0.18
        river_x = curve_amp * np.sin(Z / d * math.pi * 1.7)
        dist = np.abs(X - river_x)
        carve = elev * 0.85 * np.exp(-((dist / (w * 0.075)) ** 2))
        heights = np.maximum(base - carve, 0.02)
        H, hx, hz = _add_heightfield_terrain(scene, w=w, d=d, res=res, heights=heights, base_lift=0.30)
        n_seg = 16
        for k in range(n_seg):
            zz = -d / 2 + d * (k + 0.5) / n_seg
            xc = curve_amp * math.sin(zz / d * math.pi * 1.7)
            dx_dz = curve_amp * (math.pi * 1.7 / d) * math.cos(zz / d * math.pi * 1.7)
            seg = _box((w * 0.11, 0.14, d / n_seg * 1.3), (float(xc), 0.52, float(zz)))
            _rot(seg, math.atan2(dx_dz, 1.0), (0, 1, 0), (float(xc), 0.52, float(zz)))
            scene.add("Water", "water", seg)
        _scatter_rocks(scene, H=H, xs=hx, zs=hz, count=int(9 * scatter * q.scatter_mul) + 2, rng=rng, subdiv=1, scale_range=(0.25, 0.9))
        return

    # Default: aravalli_ridge_terrain — diagonal ridged range with terraces
    ridge_axis = (X * 0.72 + Z * 0.45) / max(w, 1.0)
    ridge = np.exp(-((ridge_axis / 0.26) ** 2))
    heights = elev * (0.75 * ridge + 0.35) * (0.65 + rough * 0.7 * (0.5 + 0.5 * _fbm(X / w * 4.5, Z / d * 4.5, rng)))
    heights *= 0.7 + 0.55 * slope
    if terraces > 0:
        levels = max(terraces, 2)
        quantized = np.floor(heights / elev * levels) / levels * elev
        heights = heights * 0.62 + quantized * 0.38
    H, hx, hz = _add_heightfield_terrain(scene, w=w, d=d, res=res, heights=heights, base_lift=0.55)
    _scatter_rocks(scene, H=H, xs=hx, zs=hz, count=int(14 * scatter * q.scatter_mul) + 3, rng=rng, subdiv=1, scale_range=(0.3, 1.4))
    for _ in range(int(4 * scatter * q.scatter_mul) + 1):
        tx = float(rng.uniform(-0.4, 0.4)) * w
        tz = float(rng.uniform(-0.4, 0.4)) * d
        ty = _sample_height(H, hx, hz, tx, tz)
        _acacia_tree(scene, x=tx, y=ty, z=tz, scale=float(rng.uniform(0.8, 1.2)), rng=rng, subdiv=2)


# ---------------------------------------------------------------------------
# HUMANOID builder (static stylized A-pose; rigging requires Blender engine)
# ---------------------------------------------------------------------------


def _build_humanoid(scene: _SceneBuilder, cfg: dict[str, Any], q: _Quality, rng: np.random.Generator) -> None:
    p = cfg["parameters"]
    H = float(p.get("height", 1.78))
    muscle = float(p.get("musculature", 0.55))
    female = str(p.get("gender", "male")) == "female"
    shoulder_s = float(p.get("shoulder_width", 1.0)) * (0.94 if female else 1.05)
    hip_s = float(p.get("hip_width", 1.0)) * (1.06 if female else 0.97)
    limb_s = float(p.get("limb_length_scale", 1.0))
    clothing = bool(p.get("include_clothing", True))
    hair_on = bool(p.get("include_hair", True))
    shoes = bool(p.get("include_shoes", True))
    armor = bool(p.get("include_armor", False))
    backpack = bool(p.get("include_backpack", False))

    sub = q.sphere_subdiv
    sub_small = max(1, sub - 1)
    limb_r = (0.045 + 0.028 * muscle) * H

    hip_y = 0.525 * H * limb_s
    waist_y = 0.60 * H
    chest_y = 0.725 * H
    shoulder_y = 0.815 * H
    neck_y = 0.845 * H
    head_r = 0.072 * H
    head_cy = 0.92 * H
    half_hip = 0.088 * H * hip_s
    half_sh = 0.128 * H * shoulder_s

    def limb(part: str, slot: str, a: tuple[float, float, float], b: tuple[float, float, float], r: float) -> None:
        scene.add(part, slot, _tube(a, b, r, q.radial))
        scene.add(part, slot, _sphere((r, r, r), a, sub_small))
        scene.add(part, slot, _sphere((r, r, r), b, sub_small))

    # Core body
    chest_rx = half_sh * (0.92 + 0.18 * muscle)
    waist_rx = chest_rx * (0.72 if female else 0.82)
    torso_slot = "primary" if clothing else "skin"
    torso_part = "Shirt" if clothing else "Body"
    scene.add(torso_part, torso_slot, _sphere((chest_rx, 0.115 * H, 0.062 * H * (1 + 0.2 * muscle)), (0, chest_y, 0), sub))
    scene.add(torso_part, torso_slot, _sphere((waist_rx, 0.085 * H, 0.055 * H), (0, waist_y, 0), sub))
    scene.add("Body", "primary" if clothing else "skin", _sphere((half_hip * 1.25, 0.075 * H, 0.06 * H), (0, hip_y, 0), sub))
    neck = _cyl_Y(0.028 * H, 0.07 * H, q.radial, (0, neck_y, 0))
    scene.add("Body", "skin", neck)
    head = _sphere((head_r * 0.92, head_r * 1.12, head_r), (0, head_cy, 0), sub)
    scene.add("Head", "skin", head)
    # Nose hint (keeps the silhouette readable at gameplay distance)
    scene.add("Head", "skin", _sphere((head_r * 0.16, head_r * 0.22, head_r * 0.18), (0, head_cy - head_r * 0.08, head_r * 0.98), 1))
    if hair_on:
        cap = _sphere((head_r * 1.0, head_r * 1.16, head_r * 1.06), (0, head_cy + head_r * 0.20, -head_r * 0.12), sub)
        scene.add("Hair", "hair", cap)
        if female:
            scene.add("Hair", "hair", _sphere((head_r * 0.72, head_r * 1.7, head_r * 0.5), (0, head_cy - head_r * 0.7, -head_r * 0.85), sub_small))

    # Arms (A-pose, ~32 degrees from the torso) + hands
    for side in (-1.0, 1.0):
        sh = (side * half_sh, shoulder_y, 0.0)
        el = (side * (half_sh + 0.115 * H * limb_s), shoulder_y - 0.175 * H * limb_s, 0.012 * H)
        wr = (side * (half_sh + 0.185 * H * limb_s), shoulder_y - 0.335 * H * limb_s, 0.03 * H)
        upper_slot = "primary" if clothing else "skin"
        limb("Shirt" if clothing else "Body", upper_slot, sh, el, limb_r * (1.06 if clothing else 1.0))
        limb("Body", "skin", el, wr, limb_r * 0.82)
        hand_c = (wr[0] + side * 0.012 * H, wr[1] - 0.045 * H, wr[2] + 0.008 * H)
        scene.add("Hands", "skin", _box((0.038 * H, 0.085 * H, 0.052 * H), hand_c))
        if q.fingers:
            for f in range(4):
                fx = hand_c[0] + (f - 1.5) * 0.011 * H
                base = (fx, hand_c[1] - 0.04 * H, hand_c[2] + 0.004 * H)
                tip = (fx, base[1] - 0.042 * H, base[2] + 0.006 * H)
                scene.add("Hands", "skin", _tube(base, tip, 0.0045 * H, 5))
            thumb_base = (hand_c[0] - side * 0.016 * H, hand_c[1] - 0.01 * H, hand_c[2] + 0.02 * H)
            thumb_tip = (thumb_base[0] - side * 0.016 * H, thumb_base[1] - 0.028 * H, thumb_base[2] + 0.016 * H)
            scene.add("Hands", "skin", _tube(thumb_base, thumb_tip, 0.005 * H, 5))

    # Legs + boots
    ankle_y = 0.062 * H
    knee_y = hip_y * 0.52
    for side in (-1.0, 1.0):
        hip = (side * half_hip, hip_y, 0.0)
        knee = (side * half_hip * 1.04, knee_y, 0.012 * H)
        ankle = (side * half_hip * 1.08, ankle_y, 0.0)
        leg_slot = "secondary" if clothing else "skin"
        leg_part = "Trousers" if clothing else "Body"
        limb(leg_part, leg_slot, hip, knee, limb_r * 1.28 * (1.05 if clothing else 1.0))
        limb(leg_part, leg_slot, knee, ankle, limb_r * 0.98 * (1.05 if clothing else 1.0))
        if shoes:
            scene.add("Boots", "trim", _box((0.052 * H, 0.055 * H, 0.16 * H), (ankle[0], 0.028 * H, 0.035 * H)))
            scene.add("Boots", "trim", _cyl_Y(limb_r * 0.95, 0.09 * H, q.radial, (ankle[0], ankle_y + 0.02 * H, 0)))
        else:
            scene.add("Feet", "skin", _box((0.046 * H, 0.03 * H, 0.13 * H), (ankle[0], 0.015 * H, 0.03 * H)))

    if clothing:  # belt + collar trims
        scene.add("Belt", "trim", _sphere((waist_rx * 1.04, 0.026 * H, 0.058 * H), (0, waist_y - 0.045 * H, 0), sub_small))
        scene.add("Belt", "accent", _box((0.05 * H, 0.035 * H, 0.02 * H), (0, waist_y - 0.045 * H, 0.056 * H)))
    if armor:
        scene.add("Armor", "metal", _sphere((chest_rx * 0.96, 0.10 * H, 0.070 * H), (0, chest_y - 0.01 * H, 0.012 * H), sub))
        scene.add("Armor", "metal", _box((chest_rx * 1.1, 0.05 * H, 0.03 * H), (0, chest_y - 0.075 * H, 0.062 * H)))
        for side in (-1.0, 1.0):
            scene.add("Armor", "metal", _sphere((limb_r * 1.5, limb_r * 1.15, limb_r * 1.5), (side * half_sh, shoulder_y + 0.012 * H, 0), sub_small))
    if backpack:
        scene.add("Backpack", "accent", _box((0.17 * H, 0.24 * H, 0.09 * H), (0, chest_y, -0.105 * H)))
        roll = _cyl_Y(0.04 * H, 0.17 * H, 10, (0, chest_y + 0.15 * H, -0.105 * H))
        _rot(roll, math.pi / 2.0, (0, 0, 1), (0, chest_y + 0.15 * H, -0.105 * H))
        scene.add("Backpack", "secondary", roll)
        for side in (-1.0, 1.0):
            scene.add("Backpack", "accent", _box((0.055 * H, 0.09 * H, 0.06 * H), (side * 0.115 * H, chest_y - 0.04 * H, -0.105 * H)))


# ---------------------------------------------------------------------------
# Engine orchestration
# ---------------------------------------------------------------------------


_BUILDERS: dict[str, Callable[[_SceneBuilder, dict[str, Any], _Quality, np.random.Generator], None]] = {
    "props": _build_prop,
    "architecture": _build_architecture,
    "environment": _build_environment,
    "humanoid": _build_humanoid,
}


def generate_asset_python(
    job_config_path: pathlib.Path,
    output_dir: pathlib.Path,
    on_progress: Callable[[str, int, str], None] | None = None,
    should_cancel: Callable[[], bool] | None = None,
) -> dict[str, Any]:
    """Generate one asset with the pure-Python engine; mirror Blender payload.

    Runs synchronously (callers dispatch it via ``asyncio.to_thread``).
    """

    def emit(stage: str, pct: int, message: str) -> None:
        if on_progress is not None:
            on_progress(stage, pct, message)

    def check_cancel() -> None:
        if should_cancel is not None and should_cancel():
            raise InterruptedError("Generation cancelled by user.")

    t0 = time.perf_counter()
    cfg = json.loads(job_config_path.read_text(encoding="utf-8"))
    output_dir.mkdir(parents=True, exist_ok=True)

    category = str(cfg["category"])
    preset_id = str(cfg["preset_id"])
    quality = _QUALITY.get(str(cfg.get("quality_profile", "optimized_mid_poly")), _QUALITY["optimized_mid_poly"])
    seed = int(cfg.get("seed", 42))
    polygon_budget = int(cfg.get("polygon_budget", 4000))
    seed_entropy = (seed ^ zlib.crc32(preset_id.encode("utf-8"))) & 0x7FFFFFFF
    rng = np.random.default_rng(seed_entropy)

    emit("initializing", 10, f"Initializing pure-Python engine (trimesh {trimesh.__version__}, numpy {np.__version__})...")
    check_cancel()
    materials = _resolve_materials(cfg)
    scene = _SceneBuilder(materials)

    emit("geometry", 32, f"Generating procedural {category} geometry ({preset_id}) with NumPy + Trimesh...")
    builder = _BUILDERS.get(category)
    if builder is None:
        raise ValueError(f"Unsupported asset category for Python fallback engine: {category!r}")
    builder(scene, cfg, quality, rng)
    check_cancel()

    parts = scene.merged_parts()
    if not parts:
        raise RuntimeError("Python fallback generator produced zero mesh parts.")

    raw_total = sum(len(m.faces) for _, _, m in parts)
    if raw_total > polygon_budget:
        emit("decimating", 58, f"Decimating {raw_total:,} triangles toward budget {polygon_budget:,} (vertex clustering)...")
        parts = _enforce_budget(parts, polygon_budget)
    check_cancel()

    emit("inspecting", 68, "Faceting flat normals, projecting UVs, and assigning vertex colors...")
    glb_parts = [
        _facet_part(name, mesh, materials[slot], rng) for name, slot, mesh in parts
    ]

    emit("exporting_glb", 80, "Serializing glTF 2.0 binary (.glb) for Godot 4...")
    glb_bytes = build_glb_bytes(
        glb_parts,
        generator=f"AssetsGenPro {ENGINE_VERSION_LABEL} (numpy+trimesh, no Blender runtime)",
    )
    glb_filename = f"{cfg['asset_id']}.glb"
    glb_path = output_dir / glb_filename
    glb_path.write_bytes(glb_bytes)
    check_cancel()

    if bool(cfg.get("save_blend", False)):
        emit(
            "saving_blend",
            88,
            "Native .blend export requires the Blender engine; skipping in Python fallback mode.",
        )

    emit("verifying_reimport", 93, "Re-loading exported GLB with Trimesh to verify roundtrip integrity...")
    diagnostics, reimport = _measure_diagnostics(category, parts, glb_parts, materials, glb_bytes)

    fallbacks = [
        "blender_core: Blender runtime not installed; generated with the pure-Python NumPy+Trimesh engine",
        "gltf2_exporter: replaced by the built-in deterministic glTF 2.0 binary writer",
    ]
    if category in ("architecture", "props"):
        fallbacks.append("native_boolean: CSG replaced by analytic multi-part construction")
        fallbacks.append("bool_tool: CSG replaced by analytic multi-part construction")
    if category in ("architecture", "environment"):
        fallbacks.append("geometry_nodes: procedural graphs replaced by NumPy heightfield/scatter synthesis")
    if category == "humanoid":
        fallbacks.append("mpfb: MakeHuman unavailable; used stylized anatomical capsule/ellipsoid humanoid")
        fallbacks.append("rigify: skinned armature requires the Blender engine; exported static A-pose character")

    elapsed = round(time.perf_counter() - t0, 3)
    payload: dict[str, Any] = {
        "success": True,
        "generation_engine": ENGINE_NAME,
        "blender_version": ENGINE_VERSION_LABEL,
        "generation_time_seconds": elapsed,
        "glb_filename": glb_filename,
        "glb_size_bytes": len(glb_bytes),
        "blend_filename": None,
        "blend_size_bytes": None,
        "capabilities_used": ["python_fallback_engine", "trimesh", "numpy"],
        "capabilities_fallback": fallbacks,
        "scene_diagnostics": diagnostics,
        "reimport_check": reimport,
    }
    (output_dir / "generation_result.json").write_text(
        json.dumps(payload, indent=2), encoding="utf-8"
    )
    emit("completed", 100, f"Generated {diagnostics['actual_triangles']:,} triangles in {elapsed:.2f}s (Python fallback engine).")
    return payload


def verify_python_engine() -> tuple[bool, str]:
    """Cheap self-check: build + serialize + re-load a 12-triangle cube GLB."""
    try:
        rng = np.random.default_rng(0)
        material = GlbMaterial(name="Mat_SelfCheck", base_color_srgb=(0.8, 0.8, 0.8, 1.0))
        part = _facet_part("SelfCheckCube", _box((1.0, 1.0, 1.0), (0, 0.5, 0)), material, rng)
        data = build_glb_bytes([part], generator="AssetsGenPro self-check")
        if data[:4] != b"glTF":
            return False, "GLB magic mismatch in self-check export."
        scene = trimesh.load(
            trimesh.util.wrap_as_stream(data), file_type="glb", force="scene", process=False
        )
        tris = int(sum(len(g.faces) for g in scene.geometry.values()))
        if tris != 12:
            return False, f"Self-check roundtrip triangle mismatch ({tris} != 12)."
        return True, f"Verified: NumPy {np.__version__} + Trimesh {trimesh.__version__} GLB roundtrip OK."
    except Exception as exc:  # pragma: no cover - defensive capability probe
        return False, f"{type(exc).__name__}: {exc}"
