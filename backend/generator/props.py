"""Procedural 3D Gameplay Props & Vehicle Generators (Blender bpy + BMesh + NumPy).

Presets:
- `br_supply_crate`: Tactical military airdrop crate with recessed panels, corner bumpers, clasps, straps
- `explosive_fuel_barrel`: Corrugated 200L cylindrical steel drum with rolling ribs & dual bung caps
- `tactical_cover_barrier`: Reinforced concrete/steel Battle Royale cover barrier with forklift cutouts
- `desert_recon_buggy`: Mid-poly off-road desert recon buggy with chassis, roll cage, seats, lightbar & 4 treaded wheels
"""

from __future__ import annotations

import math
from typing import Any

import numpy as np

from backend.blender.materials import ensure_smart_uv_project, resolve_theme_materials
from backend.enums import QualityProfile
from backend.generator.base import GenerationContext


def _create_bmesh_box(
    bm: Any,
    size_xyz: tuple[float, float, float],
    center_xyz: tuple[float, float, float],
    mat_index: int = 0,
    bevel_width: float = 0.0,
    bevel_segments: int = 1,
) -> list[Any]:
    import bmesh  # type: ignore[import-not-found]
    from mathutils import Matrix, Vector  # type: ignore[import-not-found]

    sx, sy, sz = size_xyz
    ret = bmesh.ops.create_cube(bm, size=1.0)
    verts = ret["verts"]
    bmesh.ops.scale(bm, vec=Vector((sx, sy, sz)), verts=verts)
    bmesh.ops.translate(bm, vec=Vector(center_xyz), verts=verts)

    vert_set = set(verts)
    box_faces = [f for f in bm.faces if all(v in vert_set for v in f.verts)]
    for f in box_faces:
        f.material_index = mat_index

    if bevel_width > 1e-4:
        box_edges = [e for e in bm.edges if e.verts[0] in vert_set and e.verts[1] in vert_set]
        bev = bmesh.ops.bevel(
            bm,
            geom=box_edges,
            offset=min(bevel_width, min(sx, sy, sz) * 0.22),
            offset_type="OFFSET",
            segments=max(1, bevel_segments),
            profile=0.5,
            affect="EDGES",
        )
        for f in bev.get("faces", []):
            f.material_index = mat_index
    _ = Matrix  # keep mathutils import explicit
    return verts


def _create_cylinder_part(
    bm: Any,
    radius: float,
    length: float,
    segments: int,
    center_xyz: tuple[float, float, float],
    axis: str = "Z",
    mat_index: int = 0,
) -> None:
    import bmesh  # type: ignore[import-not-found]
    from mathutils import Euler, Matrix, Vector  # type: ignore[import-not-found]

    ret = bmesh.ops.create_cone(
        bm,
        cap_ends=True,
        cap_tris=False,
        segments=segments,
        radius1=radius,
        radius2=radius,
        depth=length,
    )
    verts = ret["verts"]
    if axis == "X":
        rot = Euler((0.0, math.pi * 0.5, 0.0), "XYZ").to_matrix()
        bmesh.ops.rotate(bm, cent=Vector((0, 0, 0)), matrix=rot, verts=verts)
    elif axis == "Y":
        rot = Euler((math.pi * 0.5, 0.0, 0.0), "XYZ").to_matrix()
        bmesh.ops.rotate(bm, cent=Vector((0, 0, 0)), matrix=rot, verts=verts)
    bmesh.ops.translate(bm, vec=Vector(center_xyz), verts=verts)
    vert_set = set(verts)
    for f in bm.faces:
        if all(v in vert_set for v in f.verts):
            f.material_index = mat_index
    _ = Matrix


def _finalize_mesh_object(name: str, bm: Any, materials: list[Any], smooth_shade: bool = False) -> Any:
    import bmesh  # type: ignore[import-not-found]
    import bpy  # type: ignore[import-not-found]

    bmesh.ops.remove_doubles(bm, verts=bm.verts[:], dist=1e-5)
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces[:])

    # Ground minimum Z precisely at 0.0
    if bm.verts:
        min_z = min(v.co.z for v in bm.verts)
        if abs(min_z) > 1e-6:
            for v in bm.verts:
                v.co.z -= min_z

    mesh = bpy.data.meshes.new(f"{name}_Mesh")
    bm.to_mesh(mesh)
    bm.free()

    for poly in mesh.polygons:
        poly.use_smooth = smooth_shade
    mesh.update()

    obj = bpy.data.objects.new(name, mesh)
    bpy.context.collection.objects.link(obj)
    for mat in materials:
        obj.data.materials.append(mat)
    ensure_smart_uv_project(obj)
    return obj


def _build_supply_crate(ctx: GenerationContext, mats: dict[str, Any]) -> list[Any]:
    import bmesh  # type: ignore[import-not-found]

    p = ctx.parameters
    w = float(p["width"])
    d = float(p["depth"])
    h = float(p["height"])
    bev = float(p["bevel_amount"])
    detail = float(p["panel_detail"])
    bev_segs = 1 if ctx.quality_profile == QualityProfile.PROTOTYPE else (3 if ctx.quality_profile == QualityProfile.DETAILED_MID_POLY else 2)

    bm = bmesh.new()
    # Slot 0: primary olive/tan body, 1: dark metal brackets, 2: hazard accent clasps, 3: strap trim
    body_h = h * 0.78
    lid_h = h * 0.24

    # Main hull & overhanging lid
    _create_bmesh_box(bm, (w * 0.96, d * 0.96, body_h), (0.0, 0.0, body_h * 0.5), mat_index=0, bevel_width=bev, bevel_segments=bev_segs)
    _create_bmesh_box(bm, (w, d, lid_h), (0.0, 0.0, body_h + lid_h * 0.46), mat_index=0, bevel_width=bev * 0.9, bevel_segments=bev_segs)

    # Reinforced 8 steel corner bumpers
    cb = min(w, d, h) * 0.16
    for sx in (-1.0, 1.0):
        for sy in (-1.0, 1.0):
            _create_bmesh_box(
                bm,
                (cb, cb, cb),
                (sx * (w * 0.5 - cb * 0.42), sy * (d * 0.5 - cb * 0.42), cb * 0.48),
                mat_index=1,
                bevel_width=bev * 0.5,
                bevel_segments=1,
            )
            _create_bmesh_box(
                bm,
                (cb * 1.04, cb * 1.04, cb * 0.9),
                (sx * (w * 0.5 - cb * 0.42), sy * (d * 0.5 - cb * 0.42), h - cb * 0.42),
                mat_index=1,
                bevel_width=bev * 0.5,
                bevel_segments=1,
            )

    # Vertical structural ribs & tie-down straps
    rib_count = max(2, int(round(2 + detail * 3)))
    for i in range(rib_count):
        t = -0.34 + 0.68 * (i / max(1, rib_count - 1))
        rx = w * t
        for sy in (-1.0, 1.0):
            _create_bmesh_box(
                bm,
                (w * 0.055, d * 0.035, body_h * 0.82),
                (rx, sy * (d * 0.485), body_h * 0.48),
                mat_index=1,
                bevel_width=bev * 0.35,
            )

    # Twin airdrop nylon straps wrapping over the crate
    for sx in (-0.28 * w, 0.28 * w):
        _create_bmesh_box(
            bm,
            (w * 0.05, d * 1.025, h * 1.015),
            (sx, 0.0, h * 0.505),
            mat_index=3,
            bevel_width=0.006,
        )

    # Front/back hazard latches + side handles
    if detail >= 0.25:
        for sx in (-0.22 * w, 0.22 * w):
            for sy in (-1.0, 1.0):
                _create_bmesh_box(
                    bm,
                    (w * 0.08, d * 0.045, h * 0.16),
                    (sx, sy * (d * 0.505), body_h),
                    mat_index=2,
                    bevel_width=0.006,
                )
        for sx in (-1.0, 1.0):
            _create_cylinder_part(
                bm,
                radius=min(h, d) * 0.025,
                length=d * 0.34,
                segments=10 if ctx.quality_profile != QualityProfile.PROTOTYPE else 6,
                center_xyz=(sx * (w * 0.505), 0.0, body_h * 0.62),
                axis="Y",
                mat_index=1,
            )

    mat_list = [mats["primary"], mats["secondary"], mats["accent"], mats["trim"]]
    return [_finalize_mesh_object(ctx.asset_name, bm, mat_list, smooth_shade=False)]


def _build_fuel_barrel(ctx: GenerationContext, mats: dict[str, Any]) -> list[Any]:
    import bmesh  # type: ignore[import-not-found]

    p = ctx.parameters
    radius = max(float(p["width"]), float(p["depth"])) * 0.5
    h = float(p["height"])
    detail = float(p["panel_detail"])

    radial_segs = (
        18
        if ctx.quality_profile == QualityProfile.PROTOTYPE
        else (42 if ctx.quality_profile == QualityProfile.DETAILED_MID_POLY else 28)
    )

    # Parametric lathe profile (z_frac, r_scale, mat_slot) using NumPy
    z_samples = np.linspace(0.0, 1.0, 29 if ctx.quality_profile != QualityProfile.PROTOTYPE else 17)
    r_samples = np.ones_like(z_samples) * radius
    for idx, zf in enumerate(z_samples):
        # Bottom & top rolled steel chimes
        if zf < 0.035 or zf > 0.965:
            r_samples[idx] = radius * 1.045
        # Two corrugated rolling hoops at z=0.33 and z=0.67
        elif abs(zf - 0.33) < 0.045:
            rib = math.cos((zf - 0.33) / 0.045 * math.pi * 0.5)
            r_samples[idx] = radius * (1.0 + 0.048 * detail * rib)
        elif abs(zf - 0.67) < 0.045:
            rib = math.cos((zf - 0.67) / 0.045 * math.pi * 0.5)
            r_samples[idx] = radius * (1.0 + 0.048 * detail * rib)

    bm = bmesh.new()
    angles = np.linspace(0.0, 2.0 * math.pi, radial_segs, endpoint=False)
    rings: list[list[Any]] = []
    for zf, rad in zip(z_samples, r_samples, strict=True):
        z = float(zf * h)
        ring = [bm.verts.new((float(rad * math.cos(a)), float(rad * math.sin(a)), z)) for a in angles]
        rings.append(ring)

    for r_idx in range(len(rings) - 1):
        zf_mid = 0.5 * (z_samples[r_idx] + z_samples[r_idx + 1])
        if zf_mid < 0.04 or zf_mid > 0.96:
            m_slot = 1  # steel rim
        elif 0.36 <= zf_mid <= 0.64:
            m_slot = 2  # central hazard band
        else:
            m_slot = 0  # painted drum body
        ring_a = rings[r_idx]
        ring_b = rings[r_idx + 1]
        for s in range(radial_segs):
            s_next = (s + 1) % radial_segs
            f = bm.faces.new((ring_a[s], ring_a[s_next], ring_b[s_next], ring_b[s]))
            f.material_index = m_slot

    # Recessed top & bottom drum heads with center vertex fan
    bot_inner = [bm.verts.new((float(radius * 0.93 * math.cos(a)), float(radius * 0.93 * math.sin(a)), h * 0.02)) for a in angles]
    top_inner = [bm.verts.new((float(radius * 0.93 * math.cos(a)), float(radius * 0.93 * math.sin(a)), h * 0.975)) for a in angles]
    bot_center = bm.verts.new((0.0, 0.0, h * 0.02))
    top_center = bm.verts.new((0.0, 0.0, h * 0.975))

    for s in range(radial_segs):
        sn = (s + 1) % radial_segs
        f1 = bm.faces.new((rings[0][sn], rings[0][s], bot_inner[s], bot_inner[sn]))
        f1.material_index = 1
        fb = bm.faces.new((bot_inner[sn], bot_inner[s], bot_center))
        fb.material_index = 1

        f2 = bm.faces.new((rings[-1][s], rings[-1][sn], top_inner[sn], top_inner[s]))
        f2.material_index = 1
        ft = bm.faces.new((top_inner[s], top_inner[sn], top_center))
        ft.material_index = 0

    # Dual top bung caps (2-inch filler + 3/4-inch vent)
    if detail > 0.2:
        _create_cylinder_part(bm, radius * 0.13, h * 0.035, 12, (radius * 0.48, 0.0, h * 0.985), "Z", mat_index=1)
        _create_cylinder_part(bm, radius * 0.075, h * 0.03, 10, (-radius * 0.45, radius * 0.18, h * 0.985), "Z", mat_index=1)

    mat_list = [mats["primary"], mats["secondary"], mats["accent"]]
    return [_finalize_mesh_object(ctx.asset_name, bm, mat_list, smooth_shade=True)]


def _build_cover_barrier(ctx: GenerationContext, mats: dict[str, Any]) -> list[Any]:
    import bmesh  # type: ignore[import-not-found]
    import bpy  # type: ignore[import-not-found]

    p = ctx.parameters
    w = float(p["width"])
    d = float(p["depth"])
    h = float(p["height"])
    detail = float(p["panel_detail"])

    # Classic Jersey barrier cross-section in YZ extruded across X
    profile_yz = [
        (-d * 0.50, 0.0),
        (d * 0.50, 0.0),
        (d * 0.50, h * 0.12),
        (d * 0.26, h * 0.36),
        (d * 0.16, h * 0.96),
        (d * 0.11, h),
        (-d * 0.11, h),
        (-d * 0.16, h * 0.96),
        (-d * 0.26, h * 0.36),
        (-d * 0.50, h * 0.12),
    ]

    bm = bmesh.new()
    x_slices = 9 if ctx.quality_profile != QualityProfile.PROTOTYPE else 5
    xs = np.linspace(-w * 0.5, w * 0.5, x_slices)
    rings: list[list[Any]] = []
    for x in xs:
        rings.append([bm.verts.new((float(x), float(py), float(pz))) for py, pz in profile_yz])

    n_prof = len(profile_yz)
    for i in range(len(rings) - 1):
        ra, rb = rings[i], rings[i + 1]
        for j in range(n_prof):
            jn = (j + 1) % n_prof
            f = bm.faces.new((ra[j], rb[j], rb[jn], ra[jn]))
            f.material_index = 2 if j in (4, 5, 6) else 0

    # End caps
    f_left = bm.faces.new(list(reversed(rings[0])))
    f_left.material_index = 0
    f_right = bm.faces.new(rings[-1])
    f_right.material_index = 0

    # Upper bolted armor shield & end interlock lugs
    if detail >= 0.3:
        _create_bmesh_box(
            bm,
            (w * 0.86, d * 0.36, h * 0.22),
            (0.0, 0.0, h * 0.82),
            mat_index=1,
            bevel_width=0.012,
        )
        for sx in (-1.0, 1.0):
            _create_cylinder_part(bm, d * 0.07, h * 0.28, 10, (sx * w * 0.51, 0.0, h * 0.54), "Z", mat_index=1)

    mat_list = [mats["primary"], mats["secondary"], mats["accent"]]
    obj = _finalize_mesh_object(ctx.asset_name, bm, mat_list, smooth_shade=False)

    # Boolean forklift drainage slots through base using native Blender BOOLEAN Exact solver
    if "native_boolean" in ctx.capabilities_available and detail >= 0.4:
        cutter_bm = bmesh.new()
        for sx in (-0.27 * w, 0.27 * w):
            _create_bmesh_box(cutter_bm, (w * 0.16, d * 1.4, h * 0.11), (sx, 0.0, h * 0.055), mat_index=0)
        bmesh.ops.recalc_face_normals(cutter_bm, faces=cutter_bm.faces[:])
        cutter_mesh = bpy.data.meshes.new("ForkliftSlotCutter_Mesh")
        cutter_bm.to_mesh(cutter_mesh)
        cutter_bm.free()
        cutter_obj = bpy.data.objects.new("ForkliftSlotCutter", cutter_mesh)
        bpy.context.collection.objects.link(cutter_obj)

        bool_mod = obj.modifiers.new(name="ForkliftSlots", type="BOOLEAN")
        bool_mod.operation = "DIFFERENCE"
        bool_mod.solver = "EXACT"
        bool_mod.object = cutter_obj

        depsgraph = bpy.context.evaluated_depsgraph_get()
        eval_obj = obj.evaluated_get(depsgraph)
        baked = bpy.data.meshes.new_from_object(eval_obj, preserve_all_data_layers=True, depsgraph=depsgraph)
        old = obj.data
        obj.modifiers.remove(bool_mod)
        obj.data = baked
        bpy.data.meshes.remove(old)
        bpy.data.objects.remove(cutter_obj, do_unlink=True)
        bpy.data.meshes.remove(cutter_mesh)
        ensure_smart_uv_project(obj)

    return [obj]


def _build_desert_recon_buggy(ctx: GenerationContext, mats: dict[str, Any]) -> list[Any]:
    import bmesh  # type: ignore[import-not-found]

    p = ctx.parameters
    w = max(1.4, float(p["width"]))
    d = max(2.4, float(p["depth"]))
    h = max(1.2, float(p["height"]))
    bev = float(p["bevel_amount"])
    detail = float(p["panel_detail"])

    wheel_segs = (
        14
        if ctx.quality_profile == QualityProfile.PROTOTYPE
        else (28 if ctx.quality_profile == QualityProfile.DETAILED_MID_POLY else 20)
    )
    bm = bmesh.new()

    wheel_r = min(h * 0.27, d * 0.145)
    wheel_w = w * 0.16
    ground_clear = wheel_r * 0.88

    # 1. Armored lower tub chassis & sloped nose hood (slot 0: primary armor, slot 1: gunmetal frame, slot 2: accent lightbar, slot 3: rubber tires)
    _create_bmesh_box(
        bm,
        (w * 0.64, d * 0.68, h * 0.22),
        (0.0, 0.0, ground_clear + h * 0.11),
        mat_index=0,
        bevel_width=bev,
    )
    # Front armored nose cowling
    _create_bmesh_box(
        bm,
        (w * 0.56, d * 0.26, h * 0.18),
        (0.0, -d * 0.34, ground_clear + h * 0.16),
        mat_index=0,
        bevel_width=bev,
    )
    # Rear engine deck + twin intercooler vents
    _create_bmesh_box(
        bm,
        (w * 0.60, d * 0.25, h * 0.26),
        (0.0, d * 0.33, ground_clear + h * 0.20),
        mat_index=1,
        bevel_width=bev,
    )

    # 2. Dual bucket seats & center console
    seat_x = w * 0.16
    for sx in (-seat_x, seat_x):
        _create_bmesh_box(bm, (w * 0.21, d * 0.16, h * 0.07), (sx, d * 0.02, ground_clear + h * 0.25), mat_index=3, bevel_width=0.01)
        _create_bmesh_box(bm, (w * 0.20, d * 0.06, h * 0.34), (sx, d * 0.09, ground_clear + h * 0.43), mat_index=3, bevel_width=0.01)

    # 3. Tubular roll cage pillars, roof bars, and roof LED lightbar
    tube_r = min(w, h) * 0.024
    roof_z = h - tube_r * 1.4
    pillar_x = w * 0.30
    for sx in (-pillar_x, pillar_x):
        # Roof longitudinal rail
        _create_cylinder_part(bm, tube_r, d * 0.52, 8, (sx, d * 0.03, roof_z), "Y", mat_index=1)
        # Vertical B-pillar & A-pillar posts
        pillar_h = roof_z - (ground_clear + h * 0.20)
        _create_cylinder_part(bm, tube_r, pillar_h, 8, (sx, d * 0.18, ground_clear + h * 0.20 + pillar_h * 0.5), "Z", mat_index=1)
        _create_cylinder_part(bm, tube_r, pillar_h, 8, (sx, -d * 0.18, ground_clear + h * 0.20 + pillar_h * 0.5), "Z", mat_index=1)

    # Roof crossbars + canopy plate + tactical lightbar
    for py in (-d * 0.18, 0.0, d * 0.18):
        _create_cylinder_part(bm, tube_r, pillar_x * 2.0, 8, (0.0, py, roof_z), "X", mat_index=1)
    _create_bmesh_box(bm, (pillar_x * 1.92, d * 0.36, h * 0.025), (0.0, 0.0, roof_z + h * 0.015), mat_index=0, bevel_width=0.008)
    _create_bmesh_box(bm, (pillar_x * 1.55, d * 0.045, h * 0.055), (0.0, -d * 0.20, roof_z + h * 0.035), mat_index=2, bevel_width=0.008)

    # 4. Four off-road wheels + hubs + suspension A-arms
    axle_x = w * 0.44
    for sx in (-1.0, 1.0):
        for sy_pos in (-d * 0.33, d * 0.33):
            wx = sx * axle_x
            # Tire outer drum
            _create_cylinder_part(bm, wheel_r, wheel_w, wheel_segs, (wx, sy_pos, wheel_r), "X", mat_index=3)
            # Alloy wheel hub
            _create_cylinder_part(bm, wheel_r * 0.56, wheel_w * 1.06, max(8, wheel_segs // 2), (wx, sy_pos, wheel_r), "X", mat_index=1)
            # Suspension wishbone arm & coilover strut
            arm_len = abs(wx) - w * 0.26
            _create_bmesh_box(
                bm,
                (arm_len, d * 0.045, h * 0.04),
                (sx * (w * 0.26 + arm_len * 0.5), sy_pos, wheel_r),
                mat_index=1,
            )
            if detail >= 0.5:
                # Tire tread blocks around circumference
                tread_n = 12 if ctx.quality_profile != QualityProfile.PROTOTYPE else 8
                for ti in range(tread_n):
                    ang = 2.0 * math.pi * ti / tread_n
                    ty = sy_pos + (wheel_r * 0.99) * math.cos(ang)
                    tz = wheel_r + (wheel_r * 0.99) * math.sin(ang)
                    _create_bmesh_box(bm, (wheel_w * 0.92, wheel_r * 0.12, wheel_r * 0.12), (wx, ty, tz), mat_index=3)

    # Front bullbar bumper
    _create_cylinder_part(bm, tube_r * 1.2, w * 0.62, 10, (0.0, -d * 0.48, ground_clear + h * 0.12), "X", mat_index=1)

    mat_list = [mats["primary"], mats["secondary"], mats["accent"], mats["trim"]]
    return [_finalize_mesh_object(ctx.asset_name, bm, mat_list, smooth_shade=False)]


def generate_prop_asset(ctx: GenerationContext) -> list[Any]:
    """Dispatch to the requested prop or vehicle preset generator."""
    wear = float(ctx.parameters.get("wear_amount", 0.35))
    mats = resolve_theme_materials(ctx.material_preset, "tactical_military", ctx.seed, wear_amount=wear)

    if ctx.preset_id == "explosive_fuel_barrel":
        return _build_fuel_barrel(ctx, mats)
    if ctx.preset_id == "tactical_cover_barrier":
        return _build_cover_barrier(ctx, mats)
    if ctx.preset_id == "desert_recon_buggy":
        return _build_desert_recon_buggy(ctx, mats)
    return _build_supply_crate(ctx, mats)
