"""Reusable procedural mesh toolkit (NumPy + SciPy + Trimesh).

Everything here is pure Python: watertight primitive builders, a
material-aware scene collector, deterministic vertex-clustering decimation,
triplanar UV projection, flat-faceted / smooth-normal baking, and the
conversion of Trimesh meshes into ready-to-serialize ``GlbPart`` payloads.

All geometry is authored directly in glTF space: meters, ``+Y`` up, grounded
at ``Y = 0``.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

import numpy as np
import trimesh

from .glb_writer import GlbMaterial, GlbPart, srgb_array_to_linear

# ---------------------------------------------------------------------------
# Generation quality presets
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Quality:
    radial: int  # cylinder/tube radial segments
    sphere_subdiv: int  # icosphere subdivisions for hero forms
    terrain_res: int  # heightfield grid resolution (per side)
    scatter_mul: float
    fingers: bool


QUALITY_PRESETS = {
    "prototype": Quality(radial=10, sphere_subdiv=2, terrain_res=26, scatter_mul=0.6, fingers=False),
    "optimized_mid_poly": Quality(
        radial=16, sphere_subdiv=3, terrain_res=38, scatter_mul=1.0, fingers=True
    ),
    "detailed_mid_poly": Quality(
        radial=22, sphere_subdiv=3, terrain_res=52, scatter_mul=1.5, fingers=True
    ),
}


def resolve_quality(quality_name: str, polygon_budget: int) -> Quality:
    base = QUALITY_PRESETS.get(quality_name, QUALITY_PRESETS["optimized_mid_poly"])
    if polygon_budget <= 700:
        return Quality(radial=8, sphere_subdiv=1, terrain_res=15, scatter_mul=0.35, fingers=False)
    if polygon_budget <= 1400:
        return Quality(radial=10, sphere_subdiv=2, terrain_res=21, scatter_mul=0.55, fingers=False)
    if polygon_budget <= 2600:
        return Quality(radial=min(base.radial, 14), sphere_subdiv=2, terrain_res=28, scatter_mul=0.8, fingers=True)
    return base


# ---------------------------------------------------------------------------
# Material resolution (with direct hex skin_color & outfit_color overrides)


# ---------------------------------------------------------------------------
# Low-level primitives (all return merged-vertex watertight meshes)
# ---------------------------------------------------------------------------

def rotate_mesh(mesh: trimesh.Trimesh, angle: float, axis: tuple[float, float, float], point: Any) -> trimesh.Trimesh:
    mesh.apply_transform(
        trimesh.transformations.rotation_matrix(angle, list(axis), list(point))
    )
    return mesh


def box(size: tuple[float, float, float], center: tuple[float, float, float]) -> trimesh.Trimesh:
    mesh = trimesh.creation.box(extents=[max(s, 1e-4) for s in size])
    mesh.apply_translation(center)
    return mesh


def cylinder_y(
    radius: float, height: float, sections: int, center: tuple[float, float, float]
) -> trimesh.Trimesh:
    """Cylinder with its axis along +Y (trimesh authors along +Z)."""
    mesh = trimesh.creation.cylinder(radius=radius, height=height, sections=max(3, sections))
    rotate_mesh(mesh, -math.pi / 2.0, (1, 0, 0), (0, 0, 0))
    mesh.apply_translation(center)
    return mesh


def cone_y(
    radius: float, height: float, sections: int, center: tuple[float, float, float]
) -> trimesh.Trimesh:
    mesh = trimesh.creation.cone(radius=radius, height=height, sections=max(3, sections))
    rotate_mesh(mesh, -math.pi / 2.0, (1, 0, 0), (0, 0, 0))
    mesh.apply_translation(center)
    return mesh


def sphere(
    radii: tuple[float, float, float],
    center: tuple[float, float, float],
    subdivisions: int,
) -> trimesh.Trimesh:
    mesh = trimesh.creation.icosphere(subdivisions=subdivisions, radius=1.0)
    mesh.apply_scale(radii)
    mesh.apply_translation(center)
    return mesh


def tube(
    p1: tuple[float, float, float], p2: tuple[float, float, float], radius: float, sections: int
) -> trimesh.Trimesh:
    return trimesh.creation.cylinder(
        radius=radius, sections=max(3, sections), segment=[list(p1), list(p2)]
    )


def torus_flat(
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
    rotate_mesh(mesh, math.pi / 2.0, (1, 0, 0), (0, 0, 0))
    mesh.apply_translation(center)
    return mesh


def displaced_rock(
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


class SceneBuilder:
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


def submesh_by_mask(mesh: trimesh.Trimesh, mask: np.ndarray) -> trimesh.Trimesh | None:
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
# Deterministic decimation
# ---------------------------------------------------------------------------

def cluster_decimate(mesh: trimesh.Trimesh, target_faces: int) -> trimesh.Trimesh:
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


def decimate_by_component(mesh: trimesh.Trimesh, target_faces: int) -> trimesh.Trimesh:
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
        return cluster_decimate(mesh, target_faces)
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
            rebuilt.append(cluster_decimate(comp, share))
    return rebuilt[0] if len(rebuilt) == 1 else trimesh.util.concatenate(rebuilt)


def enforce_budget(
    parts: list[tuple[str, str, trimesh.Trimesh]], polygon_budget: int
) -> list[tuple[str, str, trimesh.Trimesh]]:
    total = sum(len(m.faces) for _, _, m in parts)
    if total <= polygon_budget or total == 0:
        return parts
    out: list[tuple[str, str, trimesh.Trimesh]] = []
    for name, slot, mesh in parts:
        share = max(24, int(polygon_budget * len(mesh.faces) / total))
        out.append((name, slot, decimate_by_component(mesh, share)))
    return out


# ---------------------------------------------------------------------------
# Shading & Vertex Colors: crisp faceted flat normals OR smooth welded normals


# ---------------------------------------------------------------------------
# Shading: crisp faceted flat normals or smooth welded normals
# ---------------------------------------------------------------------------

def project_triplanar_uvs(positions: np.ndarray, normals: np.ndarray) -> np.ndarray:
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
    return uvs


def facet_part(
    name: str, mesh: trimesh.Trimesh, material: GlbMaterial, rng: np.random.Generator
) -> GlbPart:
    """Unmerge vertices per triangle and compute sharp per-face normals + direct face colors."""
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
    uvs = project_triplanar_uvs(positions, normals)

    # Apply the material's sRGB color directly into COLOR_0 (converted to linear
    # space per glTF 2.0 spec) with crisp per-facet elevation + micro-contrast.
    base_rgb = np.asarray(material.base_color_srgb[:3], dtype=np.float64)
    alpha = float(material.base_color_srgb[3])
    elev = 0.5 + 0.5 * face_normals[:, 1]
    key_dir = np.clip(0.35 * face_normals[:, 0] + 0.55 * face_normals[:, 1] + 0.45 * face_normals[:, 2], -0.5, 1.0)
    jitter = rng.uniform(-0.025, 0.025, size=len(faces))
    shade = np.clip(0.90 + 0.08 * elev + 0.04 * key_dir + jitter, 0.78, 1.06)

    face_srgb = np.clip(base_rgb[None, :] * shade[:, None], 0.0, 1.0)
    face_lin = srgb_array_to_linear(face_srgb)
    face_rgba = np.concatenate([face_lin, np.full((len(faces), 1), alpha)], axis=1)
    colors = np.round(np.repeat(face_rgba, 3, axis=0) * 255.0).clip(0, 255).astype(np.uint8)

    return GlbPart(
        name=name,
        positions=positions.astype(np.float32),
        normals=normals.astype(np.float32),
        uvs=uvs.astype(np.float32),
        colors=colors,
        indices=indices,
        material=material,
    )


def smooth_part(name: str, mesh: trimesh.Trimesh, material: GlbMaterial) -> GlbPart:
    """Keep shared welded vertices and compute smooth vertex normals + direct vertex colors."""
    welded = mesh.copy()
    try:
        welded.merge_vertices()
    except Exception:
        pass
    positions = np.asarray(welded.vertices, dtype=np.float64)
    indices = np.asarray(welded.faces, dtype=np.uint32)
    v_normals = np.asarray(welded.vertex_normals, dtype=np.float64)
    n_len = np.linalg.norm(v_normals, axis=1, keepdims=True)
    normals = np.divide(v_normals, np.maximum(n_len, 1e-12), out=np.zeros_like(v_normals), where=n_len > 0)
    normals[n_len.reshape(-1) <= 1e-12] = (0.0, 1.0, 0.0)
    uvs = project_triplanar_uvs(positions, normals)

    base_rgb = np.asarray(material.base_color_srgb[:3], dtype=np.float64)
    alpha = float(material.base_color_srgb[3])
    elev = 0.5 + 0.5 * normals[:, 1]
    shade = np.clip(0.92 + 0.08 * elev, 0.84, 1.04)
    vert_srgb = np.clip(base_rgb[None, :] * shade[:, None], 0.0, 1.0)
    vert_lin = srgb_array_to_linear(vert_srgb)
    vert_rgba = np.concatenate([vert_lin, np.full((len(positions), 1), alpha)], axis=1)
    colors = np.round(vert_rgba * 255.0).clip(0, 255).astype(np.uint8)

    return GlbPart(
        name=name,
        positions=positions.astype(np.float32),
        normals=normals.astype(np.float32),
        uvs=uvs.astype(np.float32),
        colors=colors,
        indices=indices,
        material=material,
    )


def mesh_to_glb_part(
    name: str,
    mesh: trimesh.Trimesh,
    material: GlbMaterial,
    rng: np.random.Generator,
    *,
    flat_shading: bool = True,
) -> GlbPart:
    if flat_shading:
        return facet_part(name, mesh, material, rng)
    return smooth_part(name, mesh, material)


# ---------------------------------------------------------------------------
# Diagnostics (measured, mirroring the Blender runner's contract)
