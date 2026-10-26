"""Procedural Environment, Terrain, Cliffs, Islands, Rivers, Rocks & Foliage Generator.

Uses NumPy vectorized multi-octave fractional Brownian motion (fBm) & ridged multifractal
synthesis combined with Blender 4.2 Geometry Nodes scatter and spline-lofted foliage.
"""

from __future__ import annotations

import math
from typing import Any

import numpy as np

from backend.blender.geo_nodes import apply_surface_scatter_geonodes
from backend.blender.materials import (
    ensure_smart_uv_project,
    get_or_create_pbr_material,
    resolve_theme_materials,
)
from backend.enums import QualityProfile
from backend.generator.base import GenerationContext


def _smoothstep(t: np.ndarray) -> np.ndarray:
    return t * t * (3.0 - 2.0 * t)


def _fbm_2d(
    xx: np.ndarray,
    yy: np.ndarray,
    seed: int,
    octaves: int = 5,
    lacunarity: float = 2.05,
    gain: float = 0.5,
    ridged: bool = False,
) -> np.ndarray:
    """Deterministic NumPy 2D value/gradient fBm & ridged multifractal synthesizer."""
    rng = np.random.default_rng(seed)
    total = np.zeros_like(xx, dtype=np.float64)
    amp = 1.0
    freq = 1.0
    norm = 0.0

    for oct_i in range(octaves):
        grid_n = max(4, int(round(4 * freq)) + 3)
        lattice = rng.uniform(-1.0, 1.0, size=(grid_n, grid_n))
        gx = np.clip((xx + 0.5) * (grid_n - 2), 0.0, grid_n - 2.0001)
        gy = np.clip((yy + 0.5) * (grid_n - 2), 0.0, grid_n - 2.0001)

        ix = gx.astype(np.int32)
        iy = gy.astype(np.int32)
        fx = _smoothstep(gx - ix)
        fy = _smoothstep(gy - iy)

        v00 = lattice[iy, ix]
        v10 = lattice[iy, ix + 1]
        v01 = lattice[iy + 1, ix]
        v11 = lattice[iy + 1, ix + 1]

        nx0 = v00 * (1.0 - fx) + v10 * fx
        nx1 = v01 * (1.0 - fx) + v11 * fx
        val = nx0 * (1.0 - fy) + nx1 * fy

        if ridged:
            val = 1.0 - np.abs(val) * 2.0
            val = val * np.abs(val)

        total += val * amp
        norm += amp
        amp *= gain
        freq *= lacunarity
        _ = oct_i

    return (total / max(1e-6, norm) + 1.0) * 0.5


def _build_boulder_prototype(name: str, radius: float, seed: int, mat: Any) -> Any:
    """Create a small manifold faceted rock prototype for Geometry Nodes scattering."""
    import bmesh  # type: ignore[import-not-found]
    import bpy  # type: ignore[import-not-found]

    rng = np.random.default_rng(seed)
    bm = bmesh.new()
    bmesh.ops.create_icosphere(bm, subdivisions=1, radius=radius)
    for v in bm.verts:
        scale_xy = float(rng.uniform(0.78, 1.24))
        scale_z = float(rng.uniform(0.55, 0.92))
        v.co.x *= scale_xy
        v.co.y *= scale_xy
        v.co.z = v.co.z * scale_z + radius * 0.32
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces[:])
    mesh = bpy.data.meshes.new(f"{name}_Mesh")
    bm.to_mesh(mesh)
    bm.free()
    obj = bpy.data.objects.new(name, mesh)
    obj.data.materials.append(mat)
    bpy.context.collection.objects.link(obj)
    return obj


def _build_heightfield_terrain_mesh(
    name: str,
    width: float,
    depth: float,
    z_grid: np.ndarray,
    mats: list[Any],
    elevation: float,
) -> Any:
    """Convert a 2D NumPy heightfield `(ny, nx)` into a closed-skirt manifold Blender mesh with slope/altitude materials."""
    import bmesh  # type: ignore[import-not-found]
    import bpy  # type: ignore[import-not-found]

    ny, nx = z_grid.shape
    xs = np.linspace(-width * 0.5, width * 0.5, nx)
    ys = np.linspace(-depth * 0.5, depth * 0.5, ny)

    bm = bmesh.new()
    top_verts: list[list[Any]] = []
    min_top_z = float(np.min(z_grid))
    base_z = 0.0
    z_offset = -min_top_z + 0.35  # leave a clean 0.35m solid geological plinth skirt above Z=0

    for j in range(ny):
        row = []
        for i in range(nx):
            row.append(bm.verts.new((float(xs[i]), float(ys[j]), float(z_grid[j, i] + z_offset))))
        top_verts.append(row)

    # Assign material slot per quad by slope & altitude:
    # 0 = grassy/biome primary, 1 = rocky cliff secondary, 2 = sand/scree accent
    for j in range(ny - 1):
        for i in range(nx - 1):
            v00 = top_verts[j][i]
            v10 = top_verts[j][i + 1]
            v11 = top_verts[j + 1][i + 1]
            v01 = top_verts[j + 1][i]
            f = bm.faces.new((v00, v10, v11, v01))

            avg_z = (v00.co.z + v10.co.z + v11.co.z + v01.co.z) * 0.25 - 0.35
            dz_dx = abs((v10.co.z - v00.co.z)) / max(1e-4, width / (nx - 1))
            dz_dy = abs((v01.co.z - v00.co.z)) / max(1e-4, depth / (ny - 1))
            slope = math.hypot(dz_dx, dz_dy)

            if slope > 0.68 or avg_z > elevation * 0.76:
                f.material_index = 1  # steep cliff rock
            elif avg_z < elevation * 0.16:
                f.material_index = 2  # sandy beach / lowland scree
            else:
                f.material_index = 0  # biome grass / scrubland

    # Perimeter skirt + solid bottom cap so terrain chunk is a clean watertight volume!
    perimeter_top: list[Any] = []
    for i in range(nx):
        perimeter_top.append(top_verts[0][i])
    for j in range(1, ny):
        perimeter_top.append(top_verts[j][nx - 1])
    for i in range(nx - 2, -1, -1):
        perimeter_top.append(top_verts[ny - 1][i])
    for j in range(ny - 2, 0, -1):
        perimeter_top.append(top_verts[j][0])

    perimeter_bot = [bm.verts.new((v.co.x, v.co.y, base_z)) for v in perimeter_top]
    n_perim = len(perimeter_top)
    for k in range(n_perim):
        kn = (k + 1) % n_perim
        fs = bm.faces.new((perimeter_bot[k], perimeter_bot[kn], perimeter_top[kn], perimeter_top[k]))
        fs.material_index = 1

    bot_center = bm.verts.new((0.0, 0.0, base_z))
    for k in range(n_perim):
        kn = (k + 1) % n_perim
        fb = bm.faces.new((perimeter_bot[kn], perimeter_bot[k], bot_center))
        fb.material_index = 1

    bmesh.ops.recalc_face_normals(bm, faces=bm.faces[:])
    mesh = bpy.data.meshes.new(f"{name}_Mesh")
    bm.to_mesh(mesh)
    bm.free()

    for poly in mesh.polygons:
        poly.use_smooth = True
    mesh.update()

    obj = bpy.data.objects.new(name, mesh)
    bpy.context.collection.objects.link(obj)
    for m in mats:
        obj.data.materials.append(m)
    ensure_smart_uv_project(obj)
    return obj


def _build_terrain_variant(ctx: GenerationContext, mats: dict[str, Any]) -> list[Any]:
    import bmesh  # type: ignore[import-not-found]
    import bpy  # type: ignore[import-not-found]

    p = ctx.parameters
    w = float(p["width"])
    d = float(p["depth"])
    elev = float(p["elevation"])
    slope_k = float(p["slope_intensity"])
    rough = float(p["surface_roughness"])
    terraces = int(p["terrace_steps"])
    scatter = float(p["scatter_density"])

    grid_res = (
        26
        if ctx.quality_profile == QualityProfile.PROTOTYPE
        else (64 if ctx.quality_profile == QualityProfile.DETAILED_MID_POLY else 44)
    )
    u = np.linspace(-0.5, 0.5, grid_res)
    v = np.linspace(-0.5, 0.5, grid_res)
    xx, yy = np.meshgrid(u, v)

    base_noise = _fbm_2d(xx * 1.4, yy * 1.4, ctx.seed, octaves=5, gain=0.45 + 0.2 * rough, ridged=True)
    detail_noise = _fbm_2d(xx * 3.2, yy * 3.2, ctx.seed + 91, octaves=4, gain=0.5, ridged=False)
    h_norm = np.clip((base_noise * 0.72 + detail_noise * 0.28) ** (1.45 - 0.55 * slope_k), 0.0, 1.0)

    if ctx.preset_id == "battle_royale_island":
        radial = np.sqrt(xx * xx + yy * yy) * 2.0
        coast_mask = np.clip(1.0 - radial**2.2, 0.0, 1.0)
        h_norm = h_norm * coast_mask
    elif ctx.preset_id == "river_ravine_crossing":
        meander_x = 0.14 * np.sin(yy * math.pi * 2.1 + float(ctx.seed % 11))
        dist_river = np.abs(xx - meander_x)
        channel = _smoothstep(np.clip(dist_river / 0.16, 0.0, 1.0))
        h_norm = h_norm * (0.18 + 0.82 * channel)

    if terraces >= 2:
        t_quant = np.floor(h_norm * terraces) / terraces
        frac = (h_norm * terraces) - np.floor(h_norm * terraces)
        ramp = _smoothstep(np.clip(frac * 1.4, 0.0, 1.0)) / terraces
        h_norm = 0.45 * h_norm + 0.55 * (t_quant + ramp)

    z_grid = h_norm * elev
    mat_list = [mats["primary"], mats["secondary"], mats["accent"]]
    terrain_obj = _build_heightfield_terrain_mesh(ctx.asset_name, w, d, z_grid, mat_list, elev)

    # Scatter boulders via Blender Geometry Nodes when enabled
    if scatter > 0.05 and "geometry_nodes" in ctx.capabilities_available:
        proto = _build_boulder_prototype("ScatterBoulderProto", radius=min(w, d) * 0.022, seed=ctx.seed + 5, mat=mats["secondary"])
        density_val = scatter * (0.045 if ctx.quality_profile != QualityProfile.PROTOTYPE else 0.02)
        apply_surface_scatter_geonodes(terrain_obj, proto, density=density_val, seed=ctx.seed, scale_min=0.6, scale_max=1.45)
        old_pm = proto.data
        bpy.data.objects.remove(proto, do_unlink=True)
        bpy.data.meshes.remove(old_pm)
        ensure_smart_uv_project(terrain_obj)

    results = [terrain_obj]

    # Add water ribbon / coastal water plane for Island or River presets
    if ctx.preset_id in ("river_ravine_crossing", "battle_royale_island"):
        water_mat = mats.get("water") or get_or_create_pbr_material(
            "Mat_Water_Translucent", (0.13, 0.39, 0.50), metallic=0.08, roughness=0.14, pattern="smooth", seed=ctx.seed, use_texture=False, alpha=0.82
        )
        w_bm = bmesh.new()
        water_z = 0.35 + elev * (0.15 if ctx.preset_id == "battle_royale_island" else 0.24)
        hw, hd = w * 0.495, d * 0.495
        wv = [
            w_bm.verts.new((-hw, -hd, water_z)),
            w_bm.verts.new((hw, -hd, water_z)),
            w_bm.verts.new((hw, hd, water_z)),
            w_bm.verts.new((-hw, hd, water_z)),
        ]
        w_bm.faces.new(wv)
        w_mesh = bpy.data.meshes.new(f"{ctx.asset_name}_Water_Mesh")
        w_bm.to_mesh(w_mesh)
        w_bm.free()
        w_obj = bpy.data.objects.new(f"{ctx.asset_name}_Water", w_mesh)
        w_obj.data.materials.append(water_mat)
        bpy.context.collection.objects.link(w_obj)
        ensure_smart_uv_project(w_obj)
        results.append(w_obj)

    return results


def _build_desert_rock_outcrop(ctx: GenerationContext, mats: dict[str, Any]) -> list[Any]:
    import bmesh  # type: ignore[import-not-found]
    import bpy  # type: ignore[import-not-found]

    p = ctx.parameters
    w = float(p["width"])
    d = float(p["depth"])
    elev = float(p["elevation"])
    rough = float(p["surface_roughness"])
    terraces = max(2, int(p["terrace_steps"]))

    rng = np.random.default_rng(ctx.seed)
    subdiv = 2 if ctx.quality_profile == QualityProfile.PROTOTYPE else (4 if ctx.quality_profile == QualityProfile.DETAILED_MID_POLY else 3)

    bm = bmesh.new()
    # Cluster of 3 overlapping stratified sandstone spires/boulders
    spire_specs = [
        (0.0, 0.0, 1.0, 1.0),
        (-w * 0.26, d * 0.14, 0.62, 0.58),
        (w * 0.25, -d * 0.16, 0.55, 0.48),
    ]
    for idx, (cx, cy, s_xy, s_z) in enumerate(spire_specs):
        ret = bmesh.ops.create_icosphere(bm, subdivisions=subdiv, radius=1.0)
        for v in ret["verts"]:
            nx, ny, nz = v.co.x, v.co.y, v.co.z
            #Flatten underside and terrace Z into sedimentary strata
            z01 = max(0.0, (nz + 0.85) / 1.85)
            strata_ripple = 1.0 + 0.09 * rough * math.sin(z01 * terraces * math.pi * 2.0)
            angular = 1.0 + 0.16 * rough * math.cos(3.0 * math.atan2(ny, nx) + idx * 1.7)
            jitter = float(rng.uniform(0.94, 1.06))
            v.co.x = cx + nx * (w * 0.36 * s_xy) * strata_ripple * angular * jitter
            v.co.y = cy + ny * (d * 0.36 * s_xy) * strata_ripple * angular * jitter
            v.co.z = z01 * elev * s_z

    bmesh.ops.remove_doubles(bm, verts=bm.verts[:], dist=1e-4)
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces[:])
    min_z = min(v.co.z for v in bm.verts)
    for v in bm.verts:
        v.co.z -= min_z
    for f in bm.faces:
        f.material_index = 0 if abs(f.normal.z) < 0.72 else 1

    mesh = bpy.data.meshes.new(f"{ctx.asset_name}_Mesh")
    bm.to_mesh(mesh)
    bm.free()
    obj = bpy.data.objects.new(ctx.asset_name, mesh)
    obj.data.materials.append(mats["secondary"])
    obj.data.materials.append(mats["accent"])
    bpy.context.collection.objects.link(obj)
    ensure_smart_uv_project(obj)
    return [obj]


def _add_tapered_branch_tube(
    bm: Any,
    pts: list[tuple[float, float, float]],
    radii: list[float],
    radial_segs: int,
    mat_index: int = 0,
) -> None:
    from mathutils import Vector  # type: ignore[import-not-found]

    rings: list[list[Any]] = []
    for k, (pt, rad) in enumerate(zip(pts, radii, strict=True)):
        p_vec = Vector(pt)
        if k < len(pts) - 1:
            tangent = (Vector(pts[k + 1]) - p_vec).normalized()
        else:
            tangent = (p_vec - Vector(pts[k - 1])).normalized()
        up_ref = Vector((1.0, 0.0, 0.0)) if abs(tangent.z) > 0.92 else Vector((0.0, 0.0, 1.0))
        binorm = tangent.cross(up_ref).normalized()
        normal = binorm.cross(tangent).normalized()

        ring = []
        for s in range(radial_segs):
            ang = 2.0 * math.pi * s / radial_segs
            offset = (binorm * math.cos(ang) + normal * math.sin(ang)) * rad
            pos = p_vec + offset
            ring.append(bm.verts.new((pos.x, pos.y, pos.z)))
        rings.append(ring)

    # Cap base & tip
    c_bot = bm.verts.new(pts[0])
    c_top = bm.verts.new(pts[-1])
    for s in range(radial_segs):
        sn = (s + 1) % radial_segs
        bm.faces.new((rings[0][sn], rings[0][s], c_bot)).material_index = mat_index
        bm.faces.new((rings[-1][s], rings[-1][sn], c_top)).material_index = mat_index

    for r_i in range(len(rings) - 1):
        ra, rb = rings[r_i], rings[r_i + 1]
        for s in range(radial_segs):
            sn = (s + 1) % radial_segs
            bm.faces.new((ra[s], ra[sn], rb[sn], rb[s])).material_index = mat_index


def _build_stylized_banyan_tree(ctx: GenerationContext, mats: dict[str, Any]) -> list[Any]:
    import bmesh  # type: ignore[import-not-found]
    import bpy  # type: ignore[import-not-found]

    p = ctx.parameters
    canopy_w = float(p["width"])
    h = float(p["elevation"])
    foliage_density = float(p["scatter_density"])
    rng = np.random.default_rng(ctx.seed)

    radial_segs = 8 if ctx.quality_profile == QualityProfile.PROTOTYPE else 12
    canopy_subdiv = 1 if ctx.quality_profile == QualityProfile.PROTOTYPE else 2

    bm = bmesh.new()
    trunk_r = max(0.24, canopy_w * 0.065)
    split_z = h * 0.44

    # 1. Gnarled main Banyan trunk
    trunk_pts = [
        (0.0, 0.0, 0.0),
        (0.05 * trunk_r, -0.04 * trunk_r, split_z * 0.35),
        (-0.04 * trunk_r, 0.05 * trunk_r, split_z * 0.72),
        (0.0, 0.0, split_z),
    ]
    trunk_radii = [trunk_r * 1.45, trunk_r * 1.12, trunk_r * 0.96, trunk_r * 0.85]
    _add_tapered_branch_tube(bm, trunk_pts, trunk_radii, radial_segs, mat_index=0)

    # 2. Spreading primary limbs + Banyan aerial prop roots + lush stylized canopy clusters
    branch_count = max(4, int(round(4 + foliage_density * 4)))
    canopy_centers: list[tuple[float, float, float, float]] = [(0.0, 0.0, h * 0.82, canopy_w * 0.28)]

    for bi in range(branch_count):
        ang = (2.0 * math.pi * bi / branch_count) + float(rng.uniform(-0.22, 0.22))
        reach = canopy_w * float(rng.uniform(0.28, 0.42))
        top_z = h * float(rng.uniform(0.66, 0.84))
        bx = math.cos(ang) * reach
        by = math.sin(ang) * reach

        b_pts = [
            (0.0, 0.0, split_z * 0.92),
            (bx * 0.48, by * 0.48, split_z + (top_z - split_z) * 0.58),
            (bx, by, top_z),
        ]
        _add_tapered_branch_tube(bm, b_pts, [trunk_r * 0.55, trunk_r * 0.34, trunk_r * 0.16], max(6, radial_segs - 2), mat_index=0)
        canopy_centers.append((bx, by, top_z + h * 0.06, canopy_w * float(rng.uniform(0.20, 0.27))))

        # Signature Indian Banyan aerial prop root dropping down to ground on alternating limbs
        if bi % 2 == 0:
            rx, ry = bx * 0.68, by * 0.68
            rz_top = split_z + (top_z - split_z) * 0.68
            _add_tapered_branch_tube(
                bm,
                [(rx, ry, 0.0), (rx * 1.03, ry * 0.97, rz_top * 0.5), (rx, ry, rz_top)],
                [trunk_r * 0.22, trunk_r * 0.14, trunk_r * 0.16],
                6,
                mat_index=0,
            )

    # 3. Layered stylized foliage canopy cushions (flattened displaced icospheres)
    for cx, cy, cz, cr in canopy_centers:
        ret = bmesh.ops.create_icosphere(bm, subdivisions=canopy_subdiv, radius=1.0)
        for v in ret["verts"]:
            wobble = float(rng.uniform(0.90, 1.12))
            v.co.x = cx + v.co.x * cr * wobble
            v.co.y = cy + v.co.y * cr * wobble
            v.co.z = cz + v.co.z * (cr * 0.56) * wobble
        vset = set(ret["verts"])
        for f in bm.faces:
            if all(v in vset for v in f.verts):
                f.material_index = 1

    bmesh.ops.recalc_face_normals(bm, faces=bm.faces[:])
    min_z = min(v.co.z for v in bm.verts)
    for v in bm.verts:
        v.co.z -= min_z

    mesh = bpy.data.meshes.new(f"{ctx.asset_name}_Mesh")
    bm.to_mesh(mesh)
    bm.free()
    for poly in mesh.polygons:
        poly.use_smooth = True
    mesh.update()

    obj = bpy.data.objects.new(ctx.asset_name, mesh)
    obj.data.materials.append(mats["trim"])     # bark
    obj.data.materials.append(mats["primary"])  # lush canopy green
    bpy.context.collection.objects.link(obj)
    ensure_smart_uv_project(obj)
    return [obj]


def generate_environment_asset(ctx: GenerationContext) -> list[Any]:
    """Dispatch to the requested terrain, island, river, rock, or tree generator."""
    mats = resolve_theme_materials(ctx.material_preset, "aravalli_biome", ctx.seed, wear_amount=0.35)

    if ctx.preset_id == "desert_rock_outcrop":
        return _build_desert_rock_outcrop(ctx, mats)
    if ctx.preset_id == "stylized_banyan_tree":
        return _build_stylized_banyan_tree(ctx, mats)
    return _build_terrain_variant(ctx, mats)
