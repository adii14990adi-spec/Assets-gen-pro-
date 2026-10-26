"""Procedural Rajasthani, Indian, and Battle Royale Modular Architecture Generator.

Presets:
- `rajasthani_haveli`: Multi-story sandstone Haveli with interior space, cusped arch portals,
  cantilevered Jharokha balconies, sloped Chhajja eaves, and Geometry Nodes Kangura battlements.
- `rajput_fort_bastion`: Battered fort curtain wall + semi-octagonal watch bastion + crenellations.
- `chhatri_pavilion`: Stepped octagonal Rajasthani Chhatri with 8 pillars, cusped arches, and lotus dome.
- `pol_arched_gateway`: Grand fortified Pol gateway flanked by octagonal turrets & timber gate leaves.
- `stone_arch_bridge`: Multi-span vaulted masonry bridge with cutwater piers and parapet walls.
"""

from __future__ import annotations

import math
from typing import Any

import numpy as np

from backend.blender.geo_nodes import apply_linear_instancer_geonodes
from backend.blender.materials import ensure_smart_uv_project, resolve_theme_materials
from backend.enums import QualityProfile
from backend.generator.base import GenerationContext


def _add_box(
    bm: Any,
    size_xyz: tuple[float, float, float],
    center_xyz: tuple[float, float, float],
    mat_index: int = 0,
) -> None:
    import bmesh  # type: ignore[import-not-found]
    from mathutils import Vector  # type: ignore[import-not-found]

    ret = bmesh.ops.create_cube(bm, size=1.0)
    verts = ret["verts"]
    bmesh.ops.scale(bm, vec=Vector(size_xyz), verts=verts)
    bmesh.ops.translate(bm, vec=Vector(center_xyz), verts=verts)
    vert_set = set(verts)
    for f in bm.faces:
        if all(v in vert_set for v in f.verts):
            f.material_index = mat_index


def _add_cusped_arch_cutter_bm(
    bm: Any,
    width: float,
    height: float,
    depth: float,
    center_xyz: tuple[float, float, float],
    axis: str = "Y",
    segments: int = 12,
    cusps: int = 5,
) -> None:
    """Create a traditional Rajasthani pointed multifoil cusped arch volume in `bm` for CSG cutting."""
    cx, cy, cz_base = center_xyz
    half_w = width * 0.5
    spring_h = height * 0.60
    arch_h = height - spring_h

    angles = np.linspace(0.0, math.pi, max(6, segments))
    pts_2d: list[tuple[float, float]] = [(-half_w, -0.05), (half_w, -0.05), (half_w, spring_h)]

    for ang in angles[1:-1]:
        # Pointed ogee/cusped Rajasthani arch profile
        base_x = half_w * math.cos(ang)
        pointed_z = spring_h + arch_h * (math.sin(ang) ** 0.82)
        scallop = 0.045 * half_w * abs(math.sin(ang * cusps)) if cusps > 0 else 0.0
        pts_2d.append((float(base_x), float(pointed_z + scallop)))

    pts_2d.append((-half_w, spring_h))

    half_d = depth * 0.5
    front_ring = []
    back_ring = []
    for u, v in pts_2d:
        if axis == "Y":
            front_ring.append(bm.verts.new((cx + u, cy - half_d, cz_base + v)))
            back_ring.append(bm.verts.new((cx + u, cy + half_d, cz_base + v)))
        else:
            front_ring.append(bm.verts.new((cx - half_d, cy + u, cz_base + v)))
            back_ring.append(bm.verts.new((cx + half_d, cy + u, cz_base + v)))

    n = len(front_ring)
    for i in range(n):
        inext = (i + 1) % n
        bm.faces.new((front_ring[i], front_ring[inext], back_ring[inext], back_ring[i]))
    bm.faces.new(list(reversed(front_ring)))
    bm.faces.new(back_ring)


def _add_lotus_dome(
    bm: Any,
    radius: float,
    height: float,
    center_xyz: tuple[float, float, float],
    radial_segs: int = 20,
    rings_n: int = 10,
    mat_index: int = 2,
    finial_mat: int = 4,
) -> None:
    """Create a ribbed Rajasthani onion/lotus dome with Kalash finial."""
    cx, cy, cz = center_xyz
    angles = np.linspace(0.0, 2.0 * math.pi, radial_segs, endpoint=False)
    t_vals = np.linspace(0.0, 1.0, rings_n)

    rings: list[list[Any]] = []
    for t in t_vals[:-1]:
        # Slight bulbous lotus swell near base tapering cleanly to apex
        swell = math.sin((1.0 - t) * math.pi * 0.58) * (1.0 + 0.14 * math.sin(t * math.pi))
        z = cz + t * height
        ring = []
        for s_idx, ang in enumerate(angles):
            rib = 1.0 + 0.028 * math.cos(ang * (radial_segs // 2))
            r = radius * swell * rib
            ring.append(bm.verts.new((cx + float(r * math.cos(ang)), cy + float(r * math.sin(ang)), float(z))))
            _ = s_idx
        rings.append(ring)

    apex = bm.verts.new((cx, cy, cz + height))
    base_center = bm.verts.new((cx, cy, cz))

    for s in range(radial_segs):
        sn = (s + 1) % radial_segs
        fb = bm.faces.new((rings[0][sn], rings[0][s], base_center))
        fb.material_index = mat_index

    for r_i in range(len(rings) - 1):
        ra, rb = rings[r_i], rings[r_i + 1]
        for s in range(radial_segs):
            sn = (s + 1) % radial_segs
            f = bm.faces.new((ra[s], ra[sn], rb[sn], rb[s]))
            f.material_index = mat_index

    top_ring = rings[-1]
    for s in range(radial_segs):
        sn = (s + 1) % radial_segs
        ft = bm.faces.new((top_ring[s], top_ring[sn], apex))
        ft.material_index = mat_index

    # Kalash brass/gold finial spike
    _add_box(bm, (radius * 0.14, radius * 0.14, height * 0.24), (cx, cy, cz + height + height * 0.11), mat_index=finial_mat)


def _apply_boolean_cutter(target_obj: Any, cutter_bm: Any) -> None:
    import bmesh  # type: ignore[import-not-found]
    import bpy  # type: ignore[import-not-found]

    if not cutter_bm.faces:
        cutter_bm.free()
        return

    bmesh.ops.recalc_face_normals(cutter_bm, faces=cutter_bm.faces[:])
    cutter_mesh = bpy.data.meshes.new(f"{target_obj.name}_CutterMesh")
    cutter_bm.to_mesh(cutter_mesh)
    cutter_bm.free()
    cutter_obj = bpy.data.objects.new(f"{target_obj.name}_Cutter", cutter_mesh)
    bpy.context.collection.objects.link(cutter_obj)

    mod = target_obj.modifiers.new(name="ArchPortalsBoolean", type="BOOLEAN")
    mod.operation = "DIFFERENCE"
    mod.solver = "EXACT"
    mod.object = cutter_obj

    depsgraph = bpy.context.evaluated_depsgraph_get()
    eval_obj = target_obj.evaluated_get(depsgraph)
    baked = bpy.data.meshes.new_from_object(eval_obj, preserve_all_data_layers=True, depsgraph=depsgraph)
    old_mesh = target_obj.data
    target_obj.modifiers.remove(mod)
    target_obj.data = baked
    bpy.data.meshes.remove(old_mesh)
    bpy.data.objects.remove(cutter_obj, do_unlink=True)
    bpy.data.meshes.remove(cutter_mesh)


def _add_kangura_parapet_geonodes(
    main_obj: Any,
    width: float,
    depth: float,
    top_z: float,
    merlon_mat: Any,
    detail: float,
) -> None:
    """Use Blender 4.2 Geometry Nodes to array traditional Rajasthani Kangura merlons along roof edges."""
    import bmesh  # type: ignore[import-not-found]
    import bpy  # type: ignore[import-not-found]

    if detail < 0.2:
        return

    # Build one pointed Kangura merlon prototype
    m_bm = bmesh.new()
    mw, md, mh = 0.42, 0.22, 0.52
    _add_box(m_bm, (mw, md, mh * 0.65), (0.0, 0.0, mh * 0.325), mat_index=0)
    _add_box(m_bm, (mw * 0.68, md * 0.92, mh * 0.35), (0.0, 0.0, mh * 0.78), mat_index=0)
    bmesh.ops.recalc_face_normals(m_bm, faces=m_bm.faces[:])
    m_mesh = bpy.data.meshes.new("KanguraMerlonProto_Mesh")
    m_bm.to_mesh(m_mesh)
    m_bm.free()
    m_obj = bpy.data.objects.new("KanguraMerlonProto", m_mesh)
    m_obj.data.materials.append(merlon_mat)
    bpy.context.collection.objects.link(m_obj)

    nx = max(3, int(round(width / 0.68)))
    ny = max(3, int(round(depth / 0.68)))
    hx = width * 0.5 - 0.18
    hy = depth * 0.5 - 0.18

    spawned = [
        apply_linear_instancer_geonodes(m_obj, (-hx, -hy, top_z), (hx, -hy, top_z), nx, "Kangura_Front"),
        apply_linear_instancer_geonodes(m_obj, (-hx, hy, top_z), (hx, hy, top_z), nx, "Kangura_Back"),
        apply_linear_instancer_geonodes(m_obj, (-hx, -hy + 0.5, top_z), (-hx, hy - 0.5, top_z), max(2, ny - 2), "Kangura_Left", (0.0, 0.0, math.pi * 0.5)),
        apply_linear_instancer_geonodes(m_obj, (hx, -hy + 0.5, top_z), (hx, hy - 0.5, top_z), max(2, ny - 2), "Kangura_Right", (0.0, 0.0, math.pi * 0.5)),
    ]

    # Merge realized Kangura lines directly into main_obj for clean single-drawcall modular asset
    mat_idx = len(main_obj.data.materials)
    for idx, existing in enumerate(main_obj.data.materials):
        if existing and existing.name == merlon_mat.name:
            mat_idx = idx
            break
    else:
        main_obj.data.materials.append(merlon_mat)

    host_bm = bmesh.new()
    host_bm.from_mesh(main_obj.data)
    for part in spawned:
        if part is None:
            continue
        part_bm = bmesh.new()
        part_bm.from_mesh(part.data)
        for f in part_bm.faces:
            f.material_index = mat_idx
        temp_mesh = bpy.data.meshes.new("TmpMerge")
        part_bm.to_mesh(temp_mesh)
        part_bm.free()
        host_bm.from_mesh(temp_mesh)
        bpy.data.meshes.remove(temp_mesh)
        old_d = part.data
        bpy.data.objects.remove(part, do_unlink=True)
        bpy.data.meshes.remove(old_d)

    host_bm.to_mesh(main_obj.data)
    host_bm.free()
    bpy.data.objects.remove(m_obj, do_unlink=True)
    bpy.data.meshes.remove(m_mesh)


def _finalize_arch_object(name: str, bm: Any, mat_list: list[Any]) -> Any:
    import bmesh  # type: ignore[import-not-found]
    import bpy  # type: ignore[import-not-found]

    bmesh.ops.remove_doubles(bm, verts=bm.verts[:], dist=1e-5)
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces[:])
    if bm.verts:
        min_z = min(v.co.z for v in bm.verts)
        if abs(min_z) > 1e-6:
            for v in bm.verts:
                v.co.z -= min_z

    mesh = bpy.data.meshes.new(f"{name}_Mesh")
    bm.to_mesh(mesh)
    bm.free()
    obj = bpy.data.objects.new(name, mesh)
    bpy.context.collection.objects.link(obj)
    for m in mat_list:
        obj.data.materials.append(m)
    return obj


def _build_rajasthani_haveli(ctx: GenerationContext, mats: dict[str, Any]) -> list[Any]:
    import bmesh  # type: ignore[import-not-found]

    p = ctx.parameters
    w = float(p["width"])
    d = float(p["depth"])
    h = float(p["height"])
    wt = float(p["wall_thickness"])
    ow = float(p["opening_width"])
    oh = float(p["opening_height"])
    floors = int(p["floors"])
    arch_segs = int(p["arch_segments"])
    detail = float(p["decorative_detail"])
    roof_style = str(p["roof_style"])

    plinth_h = 0.42
    wall_h = h - plinth_h
    story_h = wall_h / max(1, floors)

    bm = bmesh.new()
    # Stepped sandstone plinth + front entrance steps
    _add_box(bm, (w + 0.45, d + 0.45, plinth_h), (0.0, 0.0, plinth_h * 0.5), mat_index=1)
    for step_i in range(3):
        sh = plinth_h * (3 - step_i) / 3.0
        _add_box(bm, (ow * 1.25, 0.34, sh), (0.0, -d * 0.5 - 0.22 - step_i * 0.30, sh * 0.5), mat_index=1)

    # Outer shell block (will be hollowed with wall_thickness + arch openings via Exact Boolean!)
    _add_box(bm, (w, d, wall_h), (0.0, 0.0, plinth_h + wall_h * 0.5), mat_index=0)

    # Sloped Chhajja sun-breaker eaves per floor + cornice bands
    for fl in range(1, floors + 1):
        fz = plinth_h + fl * story_h - 0.12
        _add_box(bm, (w + 0.65, d + 0.65, 0.14), (0.0, 0.0, fz), mat_index=1)

    # Iconic cantilevered Rajasthani Jharokha balconies on upper floor (front & sides)
    if detail >= 0.35:
        jh_z = plinth_h + (story_h * 1.05 if floors >= 2 else wall_h * 0.48)
        jh_w = min(w * 0.34, 2.4)
        jh_proj = 0.72
        jh_h = min(story_h * 0.78, 2.2)
        # Front central Jharokha box + carved corbel brackets + domed canopy
        _add_box(bm, (jh_w, jh_proj, 0.18), (0.0, -d * 0.5 - jh_proj * 0.5, jh_z), mat_index=2)
        _add_box(bm, (jh_w, jh_proj, 0.75), (0.0, -d * 0.5 - jh_proj * 0.5, jh_z + 0.38), mat_index=2)
        for bx in (-jh_w * 0.38, 0.0, jh_w * 0.38):
            _add_box(bm, (0.16, jh_proj * 0.85, 0.38), (bx, -d * 0.5 - jh_proj * 0.42, jh_z - 0.22), mat_index=1)
        for px in (-jh_w * 0.44, jh_w * 0.44):
            _add_box(bm, (0.14, 0.14, jh_h * 0.65), (px, -d * 0.5 - jh_proj + 0.1, jh_z + 0.75 + jh_h * 0.32), mat_index=2)
        _add_box(bm, (jh_w + 0.28, jh_proj + 0.24, 0.16), (0.0, -d * 0.5 - jh_proj * 0.5, jh_z + 0.75 + jh_h * 0.66), mat_index=2)
        _add_lotus_dome(
            bm,
            radius=jh_w * 0.36,
            height=0.65,
            center_xyz=(0.0, -d * 0.5 - jh_proj * 0.5, jh_z + 0.75 + jh_h * 0.74),
            radial_segs=12 if ctx.quality_profile != QualityProfile.PROTOTYPE else 8,
            rings_n=6,
            mat_index=2,
            finial_mat=4,
        )

    # Optional corner rooftop Chhatri / dome crown
    if roof_style == "lotus_dome":
        _add_lotus_dome(bm, min(w, d) * 0.28, h * 0.26, (0.0, 0.0, h), radial_segs=max(12, arch_segs), rings_n=8)
    elif roof_style == "stepped_shikhara":
        for tier in range(3):
            scale_t = 0.58 - tier * 0.14
            _add_box(bm, (w * scale_t, d * scale_t, 0.55), (0.0, 0.0, h + tier * 0.55 + 0.275), mat_index=1)

    mat_list = [mats["primary"], mats["secondary"], mats["accent"], mats["trim"], mats["metal"]]
    obj = _finalize_arch_object(ctx.asset_name, bm, mat_list)

    # Boolean interior room hollowing + cusped front/rear doors + arched side windows!
    cutter_bm = bmesh.new()
    inner_w = max(1.2, w - 2.0 * wt)
    inner_d = max(1.2, d - 2.0 * wt)
    inner_h = max(2.0, wall_h - wt)
    _add_box(cutter_bm, (inner_w, inner_d, inner_h), (0.0, 0.0, plinth_h + inner_h * 0.5 + 0.08))

    # Front & rear cusped arched entrance portals
    door_h = min(oh, story_h * 0.86)
    _add_cusped_arch_cutter_bm(cutter_bm, ow, door_h, wt * 2.8, (0.0, -d * 0.5, plinth_h), "Y", segments=arch_segs)
    _add_cusped_arch_cutter_bm(cutter_bm, ow * 0.85, door_h * 0.92, wt * 2.8, (0.0, d * 0.5, plinth_h), "Y", segments=arch_segs)

    # Side & upper arched windows
    win_w = min(1.15, inner_d * 0.28)
    win_h = min(1.55, story_h * 0.52)
    for sx in (-d * 0.24, d * 0.24):
        _add_cusped_arch_cutter_bm(cutter_bm, win_w, win_h, wt * 2.8, (-w * 0.5, sx, plinth_h + 0.95), "X", segments=max(8, arch_segs - 2))
        _add_cusped_arch_cutter_bm(cutter_bm, win_w, win_h, wt * 2.8, (w * 0.5, sx, plinth_h + 0.95), "X", segments=max(8, arch_segs - 2))

    _apply_boolean_cutter(obj, cutter_bm)

    if roof_style == "chhatri_parapet" and "geometry_nodes" in ctx.capabilities_available:
        _add_kangura_parapet_geonodes(obj, w, d, h, mats["secondary"], detail)

    ensure_smart_uv_project(obj)
    return [obj]


def _build_rajput_fort_bastion(ctx: GenerationContext, mats: dict[str, Any]) -> list[Any]:
    import bmesh  # type: ignore[import-not-found]

    p = ctx.parameters
    w = float(p["width"])
    d = float(p["depth"])
    h = float(p["height"])
    wt = float(p["wall_thickness"])
    ow = float(p["opening_width"])
    oh = float(p["opening_height"])
    arch_segs = int(p["arch_segments"])
    detail = float(p["decorative_detail"])

    bm = bmesh.new()
    # Battered (sloped) rampart curtain wall on left & right + central semi-octagonal projecting bastion!
    wall_d = max(1.8, wt * 2.8, d * 0.42)
    _add_box(bm, (w, wall_d, h * 0.86), (0.0, 0.0, h * 0.43), mat_index=0)
    # Battered base skirt
    _add_box(bm, (w + 0.5, wall_d + 0.65, h * 0.28), (0.0, 0.0, h * 0.14), mat_index=1)

    # Projecting polygonal Rajput watch bastion at one flank (x = +w*0.28)
    bastion_r = d * 0.52
    bastion_x = w * 0.26
    oct_segs = 12 if ctx.quality_profile != QualityProfile.PROTOTYPE else 8
    angles = np.linspace(0.0, 2.0 * math.pi, oct_segs, endpoint=False)
    b_bot = [bm.verts.new((bastion_x + float(bastion_r * 1.12 * math.cos(a)), float(-d * 0.18 + bastion_r * 1.12 * math.sin(a)), 0.0)) for a in angles]
    b_top = [bm.verts.new((bastion_x + float(bastion_r * 0.94 * math.cos(a)), float(-d * 0.18 + bastion_r * 0.94 * math.sin(a)), h)) for a in angles]
    for i in range(oct_segs):
        inext = (i + 1) % oct_segs
        f = bm.faces.new((b_bot[i], b_bot[inext], b_top[inext], b_top[i]))
        f.material_index = 0
    bm.faces.new(list(reversed(b_bot))).material_index = 1
    bm.faces.new(b_top).material_index = 1

    # Machicolation cornice ring + parapet crown on bastion
    _add_lotus_dome(
        bm,
        radius=bastion_r * 0.52,
        height=h * 0.24,
        center_xyz=(bastion_x, -d * 0.18, h),
        radial_segs=oct_segs,
        rings_n=6,
        mat_index=2,
        finial_mat=4,
    )

    mat_list = [mats["primary"], mats["secondary"], mats["accent"], mats["trim"], mats["metal"]]
    obj = _finalize_arch_object(ctx.asset_name, bm, mat_list)

    # Cut arched sally-port passage on left curtain wall + arrow-slit embrasures
    cutter_bm = bmesh.new()
    gate_x = -w * 0.24
    _add_cusped_arch_cutter_bm(
        cutter_bm,
        min(ow, w * 0.35),
        min(oh, h * 0.65),
        wall_d * 2.2,
        (gate_x, 0.0, 0.0),
        "Y",
        segments=arch_segs,
    )
    if detail >= 0.3:
        for slit_i in range(3):
            ang = -math.pi * 0.75 + slit_i * (math.pi * 0.25)
            sx = bastion_x + math.cos(ang) * bastion_r * 0.96
            sy = -d * 0.18 + math.sin(ang) * bastion_r * 0.96
            _add_box(cutter_bm, (0.24, 0.95, 1.25), (sx, sy, h * 0.58))
    _apply_boolean_cutter(obj, cutter_bm)

    if "geometry_nodes" in ctx.capabilities_available:
        _add_kangura_parapet_geonodes(obj, w, wall_d, h * 0.86, mats["secondary"], detail)

    ensure_smart_uv_project(obj)
    return [obj]


def _build_chhatri_pavilion(ctx: GenerationContext, mats: dict[str, Any]) -> list[Any]:
    import bmesh  # type: ignore[import-not-found]

    p = ctx.parameters
    w = float(p["width"])
    h = float(p["height"])
    arch_segs = int(p["arch_segments"])
    detail = float(p["decorative_detail"])

    radius = w * 0.46
    plinth_h = h * 0.16
    pillar_h = h * 0.46
    dome_h = h - plinth_h - pillar_h - 0.32

    bm = bmesh.new()
    # Two-tier octagonal plinth platform
    for tier, scale_r in enumerate((1.08, 0.96)):
        tz0 = tier * (plinth_h * 0.5)
        tz1 = (tier + 1) * (plinth_h * 0.5)
        oct_a = np.linspace(0.0, 2.0 * math.pi, 8, endpoint=False) + math.pi / 8.0
        rb = [bm.verts.new((float(radius * scale_r * math.cos(a)), float(radius * scale_r * math.sin(a)), tz0)) for a in oct_a]
        rt = [bm.verts.new((float(radius * scale_r * math.cos(a)), float(radius * scale_r * math.sin(a)), tz1)) for a in oct_a]
        for i in range(8):
            inext = (i + 1) % 8
            bm.faces.new((rb[i], rb[inext], rt[inext], rt[i])).material_index = 1
        bm.faces.new(list(reversed(rb))).material_index = 1
        bm.faces.new(rt).material_index = 2

    # 8 Rajput octagonal pillars + capital brackets
    pillar_ring_r = radius * 0.80
    oct_angles = np.linspace(0.0, 2.0 * math.pi, 8, endpoint=False) + math.pi / 8.0
    pil_r = max(0.14, radius * 0.068)
    for ang in oct_angles:
        px = float(pillar_ring_r * math.cos(ang))
        py = float(pillar_ring_r * math.sin(ang))
        # Pillar base, shaft, and lotus capital
        _add_box(bm, (pil_r * 2.5, pil_r * 2.5, 0.24), (px, py, plinth_h + 0.12), mat_index=1)
        _add_box(bm, (pil_r * 1.75, pil_r * 1.75, pillar_h - 0.44), (px, py, plinth_h + pillar_h * 0.5), mat_index=0)
        _add_box(bm, (pil_r * 2.7, pil_r * 2.7, 0.24), (px, py, plinth_h + pillar_h - 0.12), mat_index=2)

    # Octagonal ring beam + overhanging Chhajja cornice
    eave_z = plinth_h + pillar_h
    for scale_r, thick, z_off, m_idx in ((0.86, 0.30, 0.15, 0), (1.06 if detail > 0.2 else 0.92, 0.14, 0.30, 1)):
        rb = [bm.verts.new((float(radius * scale_r * math.cos(a)), float(radius * scale_r * math.sin(a)), eave_z + z_off - thick * 0.5)) for a in oct_angles]
        rt = [bm.verts.new((float(radius * scale_r * math.cos(a)), float(radius * scale_r * math.sin(a)), eave_z + z_off + thick * 0.5)) for a in oct_angles]
        for i in range(8):
            inext = (i + 1) % 8
            bm.faces.new((rb[i], rb[inext], rt[inext], rt[i])).material_index = m_idx
        bm.faces.new(list(reversed(rb))).material_index = m_idx
        bm.faces.new(rt).material_index = m_idx

    # Ribbed lotus dome crown
    _add_lotus_dome(
        bm,
        radius=radius * 0.74,
        height=max(1.2, dome_h),
        center_xyz=(0.0, 0.0, eave_z + 0.36),
        radial_segs=max(16, arch_segs),
        rings_n=10 if ctx.quality_profile != QualityProfile.PROTOTYPE else 6,
        mat_index=0,
        finial_mat=4,
    )

    mat_list = [mats["primary"], mats["secondary"], mats["accent"], mats["trim"], mats["metal"]]
    obj = _finalize_arch_object(ctx.asset_name, bm, mat_list)
    ensure_smart_uv_project(obj)
    return [obj]


def _build_pol_gateway(ctx: GenerationContext, mats: dict[str, Any]) -> list[Any]:
    import bmesh  # type: ignore[import-not-found]

    p = ctx.parameters
    w = float(p["width"])
    d = float(p["depth"])
    h = float(p["height"])
    ow = min(float(p["opening_width"]), w * 0.48)
    oh = min(float(p["opening_height"]), h * 0.68)
    arch_segs = int(p["arch_segments"])
    detail = float(p["decorative_detail"])

    bm = bmesh.new()
    # Central gateway massif
    _add_box(bm, (w * 0.72, d, h * 0.88), (0.0, 0.0, h * 0.44), mat_index=0)

    # Twin flanking octagonal buttress towers + rooftop Chhatri cupolas
    tower_r = d * 0.56
    for sx in (-1.0, 1.0):
        tx = sx * (w * 0.39)
        oct_a = np.linspace(0.0, 2.0 * math.pi, 8, endpoint=False) + math.pi / 8.0
        rb = [bm.verts.new((tx + float(tower_r * 1.06 * math.cos(a)), float(tower_r * 1.06 * math.sin(a)), 0.0)) for a in oct_a]
        rt = [bm.verts.new((tx + float(tower_r * 0.92 * math.cos(a)), float(tower_r * 0.92 * math.sin(a)), h * 0.92)) for a in oct_a]
        for i in range(8):
            inext = (i + 1) % 8
            bm.faces.new((rb[i], rb[inext], rt[inext], rt[i])).material_index = 1
        bm.faces.new(list(reversed(rb))).material_index = 1
        bm.faces.new(rt).material_index = 1
        _add_lotus_dome(bm, tower_r * 0.66, h * 0.16, (tx, 0.0, h * 0.92), radial_segs=12, rings_n=6, mat_index=2, finial_mat=4)

    mat_list = [mats["primary"], mats["secondary"], mats["accent"], mats["trim"], mats["metal"]]
    obj = _finalize_arch_object(ctx.asset_name, bm, mat_list)

    # Carve central pointed multifoil cusped archway + upper gallery windows
    cutter_bm = bmesh.new()
    _add_cusped_arch_cutter_bm(cutter_bm, ow, oh, d * 2.2, (0.0, 0.0, 0.0), "Y", segments=arch_segs, cusps=7)
    if detail >= 0.4:
        for wx in (-ow * 0.55, 0.0, ow * 0.55):
            _add_cusped_arch_cutter_bm(cutter_bm, 0.72, 1.15, d * 2.2, (wx, 0.0, oh + 0.85), "Y", segments=8, cusps=3)
    _apply_boolean_cutter(obj, cutter_bm)

    # Add slightly-open studded teakwood Pol gate leaves inside the carved passage!
    doors_bm = bmesh.new()
    doors_bm.from_mesh(obj.data)
    leaf_w = ow * 0.44
    leaf_h = oh * 0.68
    for sx in (-1.0, 1.0):
        _add_box(doors_bm, (0.12, leaf_w, leaf_h), (sx * (ow * 0.46), -d * 0.12, leaf_h * 0.5), mat_index=3)
    doors_bm.to_mesh(obj.data)
    doors_bm.free()

    if "geometry_nodes" in ctx.capabilities_available:
        _add_kangura_parapet_geonodes(obj, w * 0.70, d, h * 0.88, mats["secondary"], detail)

    ensure_smart_uv_project(obj)
    return [obj]


def _build_stone_arch_bridge(ctx: GenerationContext, mats: dict[str, Any]) -> list[Any]:
    import bmesh  # type: ignore[import-not-found]

    p = ctx.parameters
    w = float(p["width"])
    d = float(p["depth"])
    h = float(p["height"])
    ow = float(p["opening_width"])
    oh = min(float(p["opening_height"]), h * 0.72)
    arch_segs = int(p["arch_segments"])
    detail = float(p["decorative_detail"])

    deck_h = h * 0.82
    parapet_h = h - deck_h

    bm = bmesh.new()
    # Main masonry bridge span + low parapet walls + end bollards
    _add_box(bm, (w, d, deck_h), (0.0, 0.0, deck_h * 0.5), mat_index=0)
    for sy in (-1.0, 1.0):
        _add_box(bm, (w, 0.34, parapet_h), (0.0, sy * (d * 0.5 - 0.17), deck_h + parapet_h * 0.5), mat_index=1)
        for sx in (-w * 0.48, 0.0, w * 0.48):
            _add_box(bm, (0.48, 0.48, parapet_h * 1.45), (sx, sy * (d * 0.5 - 0.18), deck_h + parapet_h * 0.72), mat_index=2)

    # Cutwater piers between arches
    spans = max(2, min(4, int(round(w / max(2.2, ow * 1.35)))))
    span_step = w / spans
    if detail >= 0.3:
        for i in range(1, spans):
            px = -w * 0.5 + i * span_step
            _add_box(bm, (0.65, d + 0.75, deck_h * 0.72), (px, 0.0, deck_h * 0.36), mat_index=1)

    mat_list = [mats["primary"], mats["secondary"], mats["accent"], mats["trim"], mats["metal"]]
    obj = _finalize_arch_object(ctx.asset_name, bm, mat_list)

    # Boolean vaulted masonry arches through bridge span
    cutter_bm = bmesh.new()
    arch_w = min(ow, span_step * 0.74)
    for i in range(spans):
        ax = -w * 0.5 + (i + 0.5) * span_step
        _add_cusped_arch_cutter_bm(cutter_bm, arch_w, oh, d * 2.2, (ax, 0.0, 0.0), "Y", segments=arch_segs, cusps=0)
    _apply_boolean_cutter(obj, cutter_bm)
    ensure_smart_uv_project(obj)
    return [obj]


def generate_architecture_asset(ctx: GenerationContext) -> list[Any]:
    """Dispatch to the requested Rajasthani / modular architecture preset."""
    mats = resolve_theme_materials(ctx.material_preset, "rajasthan_sandstone", ctx.seed, wear_amount=0.3)

    if ctx.preset_id == "rajput_fort_bastion":
        return _build_rajput_fort_bastion(ctx, mats)
    if ctx.preset_id == "chhatri_pavilion":
        return _build_chhatri_pavilion(ctx, mats)
    if ctx.preset_id == "pol_arched_gateway":
        return _build_pol_gateway(ctx, mats)
    if ctx.preset_id == "stone_arch_bridge":
        return _build_stone_arch_bridge(ctx, mats)
    return _build_rajasthani_haveli(ctx, mats)
