"""Procedural Connected Anatomical Humanoid Character & Rigging Generator.

Builds:
1. A single-piece, watertight, quad-dominant anatomical base mesh (`male` / `female`)
   connecting pelvis, abdomen, ribcage, chest, neck, sculpted head (cranium, jaw, nose, ears),
   shoulders, arms, forearms, wrists, palms, 5 articulated fingers per hand, thighs, knees,
   calves, ankles, heels, and feet — zero disconnected spheres/cylinders!
2. Parametric athletic proportions (`height`, `musculature`, `shoulder_width`, `hip_width`,
   `limb_length_scale`) + NumPy anatomical muscle-group harmonic sculpting.
3. Fitted Battle Royale character equipment layers:
   - Tactical shirt & cargo combat trousers (`include_clothing`)
   - Sculpted hair mesh (`include_hair`)
   - Molded tactical combat boots (`include_shoes`)
   - Modular ballistic plate carrier vest + mag pouches (`include_armor`)
   - Contoured field survival backpack (`include_backpack`)
4. Godot 4 `SkeletonProfileHumanoid`-compatible Armature + strictly normalized 4-bone
   capsule-falloff skin weights across the body and all equipped garments (`include_rig`),
   plus a subtle animation-ready `IdleReady` pose action!
"""

from __future__ import annotations

import math
from typing import Any

import numpy as np

from backend.blender.materials import (
    ensure_smart_uv_project,
    get_or_create_pbr_material,
    resolve_theme_materials,
)
from backend.enums import QualityProfile
from backend.generator.base import GenerationContext


def _parse_hex_rgb_optional(raw: Any) -> tuple[float, float, float] | None:
    if not isinstance(raw, str):
        return None
    s = raw.strip().lstrip("#")
    if len(s) == 3 and all(c in "0123456789abcdefABCDEF" for c in s):
        s = "".join(c * 2 for c in s)
    if len(s) != 6 or not all(c in "0123456789abcdefABCDEF" for c in s):
        return None
    return (int(s[0:2], 16) / 255.0, int(s[2:4], 16) / 255.0, int(s[4:6], 16) / 255.0)


def _build_anatomical_wire_spec(
    height: float,
    is_female: bool,
    muscle: float,
    shoulder_scale: float,
    hip_scale: float,
    limb_scale: float,
    t_pose: bool = False,
) -> tuple[list[tuple[float, float, float]], list[tuple[int, int]], list[tuple[float, float]], dict[str, tuple[float, float, float]]]:
    """Construct connected anatomical skeleton/skin graph & joint landmarks in meters (-Y forward, +Z up)."""
    s = height / 1.78
    m_boost = 0.88 + 0.28 * muscle

    # Proportional widths
    hip_x = (0.104 if is_female else 0.096) * s * hip_scale
    shoulder_x = (0.175 if is_female else 0.205) * s * shoulder_scale
    waist_rx = (0.118 if is_female else 0.136) * s * (0.96 + 0.08 * muscle)
    chest_rx = (0.148 if is_female else 0.174) * s * shoulder_scale * (0.95 + 0.10 * muscle)
    pelvis_rx = (0.158 if is_female else 0.146) * s * hip_scale

    # Vertical landmarks
    z_ankle = 0.072 * s
    z_knee = 0.485 * s
    z_pelvis = 0.915 * s
    z_waist = 1.065 * s
    z_abdomen = 1.165 * s
    z_chest = 1.315 * s
    z_clavicle = 1.435 * s
    z_neck_base = 1.495 * s
    z_neck_top = 1.565 * s
    z_head_center = 1.655 * s
    z_head_top = 1.745 * s

    verts: list[tuple[float, float, float]] = []
    radii: list[tuple[float, float]] = []
    edges: list[tuple[int, int]] = []
    landmarks: dict[str, tuple[float, float, float]] = {}

    def add_node(pos: tuple[float, float, float], rad: tuple[float, float], parent: int | None = None, tag: str | None = None) -> int:
        idx = len(verts)
        verts.append(pos)
        radii.append(rad)
        if parent is not None:
            edges.append((parent, idx))
        if tag:
            landmarks[tag] = pos
        return idx

    # Spine & Head chain (root at pelvis)
    n_pelvis = add_node((0.0, 0.008 * s, z_pelvis), (pelvis_rx, 0.112 * s), None, "Hips")
    n_waist = add_node((0.0, 0.0, z_waist), (waist_rx, 0.096 * s), n_pelvis, "Spine")
    n_abdomen = add_node((0.0, -0.006 * s, z_abdomen), (waist_rx * 1.05, 0.104 * s), n_waist, "Chest")
    n_chest = add_node((0.0, -0.008 * s, z_chest), (chest_rx, (0.118 if is_female else 0.122) * s * m_boost), n_abdomen, "UpperChest")
    n_clav = add_node((0.0, 0.0, z_clavicle), (chest_rx * 0.88, 0.095 * s), n_chest, "ClavicleCenter")
    n_neck0 = add_node((0.0, 0.006 * s, z_neck_base), (0.058 * s * m_boost, 0.058 * s), n_clav, "Neck")
    n_neck1 = add_node((0.0, 0.004 * s, z_neck_top), (0.053 * s, 0.055 * s), n_neck0, "HeadBase")
    n_head_mid = add_node((0.0, -0.010 * s, z_head_center), (0.088 * s, 0.104 * s), n_neck1, "Head")
    add_node((0.0, 0.005 * s, z_head_top), (0.082 * s, 0.095 * s), n_head_mid, "HeadTop")
    # Jaw/chin forward node for facial profile
    add_node((0.0, -0.068 * s, z_neck_top + 0.032 * s), (0.048 * s, 0.044 * s), n_head_mid)

    # Bilateral Legs + Feet AND Arms + 5-Finger Hands
    arm_reach = limb_scale * s
    for side_sign, side_prefix in ((-1.0, "Right"), (1.0, "Left")):
        # Note: in glTF/Godot character facing -Y in Blender (which exports to +Z forward in glTF),
        # +X is character's Right or Left: wait! In Blender (-Y forward, +Z up), character faces -Y:
        # looking from behind toward -Y, +X is RIGHT and -X is LEFT! Wait: let's check standard Blender Rigify convention:
        # In Blender, character faces -Y: character's LEFT arm is at +X (`Left` = +X, `Right` = -X)!
        # Let's double check: if a person stands at origin facing -Y (south), their nose points to (0, -1, 0),
        # top of head is (0, 0, +1): then cross(forward=(0,-1,0), up=(0,0,1)) = (-1, 0, 0) = RIGHT hand,
        # so (+1, 0, 0) IS INDEED LEFT HAND! `(-1.0, "Right"), (1.0, "Left")` is 100% anatomically & Blender-standard!

        hx = side_sign * hip_x
        n_hip = add_node((hx, 0.005 * s, z_pelvis - 0.025 * s), (0.088 * s * hip_scale, 0.090 * s * m_boost), n_pelvis, f"{side_prefix}UpperLeg")
        n_thigh_u = add_node((hx * 1.03, -0.004 * s, z_pelvis - 0.19 * s), (0.082 * s * m_boost, 0.084 * s * m_boost), n_hip)
        n_thigh_l = add_node((hx * 1.02, 0.0, z_knee + 0.11 * s), (0.068 * s * m_boost, 0.070 * s * m_boost), n_thigh_u)
        n_knee = add_node((hx * 1.01, -0.008 * s, z_knee), (0.058 * s, 0.060 * s), n_thigh_l, f"{side_prefix}LowerLeg")
        n_calf_u = add_node((hx * 1.01, 0.012 * s, z_knee - 0.13 * s), (0.060 * s * m_boost, 0.065 * s * m_boost), n_knee)
        n_calf_l = add_node((hx * 1.00, 0.006 * s, z_ankle + 0.11 * s), (0.045 * s, 0.047 * s), n_calf_u)
        n_ankle = add_node((hx * 1.00, 0.004 * s, z_ankle), (0.041 * s, 0.043 * s), n_calf_l, f"{side_prefix}Foot")
        # Heel & forefoot & toes
        add_node((hx * 1.00, 0.042 * s, 0.032 * s), (0.038 * s, 0.032 * s), n_ankle)
        n_midfoot = add_node((hx * 1.00, -0.065 * s, 0.034 * s), (0.045 * s, 0.030 * s), n_ankle)
        add_node((hx * 1.01, -0.145 * s, 0.024 * s), (0.047 * s, 0.022 * s), n_midfoot, f"{side_prefix}Toes")

        # Relaxed A-pose / tactical ready arm (~28 deg downward from horizontal for superior shoulder skinning!)
        sx = side_sign * shoulder_x
        z_sh = z_clavicle - 0.015 * s
        n_clav_side = add_node((sx * 0.56, -0.005 * s, z_clavicle), (0.064 * s, 0.058 * s), n_clav, f"{side_prefix}Shoulder")
        n_shoulder = add_node((sx, 0.005 * s, z_sh), (0.068 * s * m_boost, 0.066 * s * m_boost), n_clav_side, f"{side_prefix}UpperArm")

        arm_ang = math.radians(0.0 if t_pose else 26.0)
        dx = side_sign * math.cos(arm_ang)
        dz = -math.sin(arm_ang)

        upper_len = 0.275 * arm_reach
        fore_len = 0.255 * arm_reach

        bicep_p = (sx + dx * upper_len * 0.48, 0.006 * s, z_sh + dz * upper_len * 0.48)
        elbow_p = (sx + dx * upper_len, 0.012 * s, z_sh + dz * upper_len)
        fore_mid_p = (elbow_p[0] + dx * fore_len * 0.46, 0.0, elbow_p[2] + dz * fore_len * 0.46)
        wrist_p = (elbow_p[0] + dx * fore_len, -0.014 * s, elbow_p[2] + dz * fore_len)

        n_bicep = add_node(bicep_p, (0.054 * s * m_boost, 0.056 * s * m_boost), n_shoulder)
        n_elbow = add_node(elbow_p, (0.045 * s, 0.046 * s), n_bicep, f"{side_prefix}LowerArm")
        n_fore = add_node(fore_mid_p, (0.046 * s * m_boost, 0.044 * s * m_boost), n_elbow)
        n_wrist = add_node(wrist_p, (0.033 * s, 0.026 * s), n_fore, f"{side_prefix}Hand")

        palm_len = 0.068 * arm_reach
        palm_p = (wrist_p[0] + dx * palm_len, wrist_p[1] - 0.004 * s, wrist_p[2] + dz * palm_len)
        n_palm = add_node(palm_p, (0.044 * s, 0.036 * s), n_wrist, f"{side_prefix}Palm")

        # 5 Articulated Fingers per hand (Thumb + Index, Middle, Ring, Pinky) with generous root radii so MOD_SKIN keeps 1 connected shell!
        thumb_p1 = (wrist_p[0] + dx * palm_len * 0.62, wrist_p[1] - 0.048 * s, wrist_p[2] + dz * palm_len * 0.45)
        thumb_p2 = (thumb_p1[0] + dx * 0.045 * arm_reach, thumb_p1[1] - 0.032 * s, thumb_p1[2] + dz * 0.032 * arm_reach)
        n_th1 = add_node(thumb_p1, (0.018 * s, 0.017 * s), n_wrist, f"{side_prefix}ThumbProximal")
        add_node(thumb_p2, (0.013 * s, 0.013 * s), n_th1, f"{side_prefix}ThumbTip")

        finger_specs = [
            ("Index", -0.034, 0.072),
            ("Middle", -0.011, 0.079),
            ("Ring", 0.012, 0.074),
            ("Pinky", 0.034, 0.060),
        ]
        for fname, y_off, flen in finger_specs:
            knuckle_p = (palm_p[0] + dx * 0.026 * arm_reach, palm_p[1] + y_off * s, palm_p[2] + dz * 0.026 * arm_reach)
            tip_f_p = (knuckle_p[0] + dx * flen * arm_reach, knuckle_p[1] + y_off * 0.15 * s, knuckle_p[2] + dz * flen * 1.05 * arm_reach)
            n_fk = add_node(knuckle_p, (0.017 * s, 0.016 * s), n_palm, f"{side_prefix}{fname}Proximal")
            add_node(tip_f_p, (0.012 * s, 0.012 * s), n_fk, f"{side_prefix}{fname}Tip")

    return verts, edges, radii, landmarks


def _sculpt_anatomical_harmonics(mesh: Any, height: float, is_female: bool, muscle: float) -> None:
    """Apply vectorized NumPy anatomical contours (pectorals, ribcage, abs, glutes, nose, flat soles)."""
    n_verts = len(mesh.vertices)
    coords = np.empty(n_verts * 3, dtype=np.float32)
    mesh.vertices.foreach_get("co", coords)
    pts = coords.reshape((-1, 3))

    s = height / 1.78
    x = pts[:, 0]
    y = pts[:, 1]
    z = pts[:, 2]

    # 1. Pectoral / chest contour (-Y is anterior front!)
    z_pec = (1.30 if is_female else 1.32) * s
    pec_dx = (np.abs(x) - (0.068 if is_female else 0.075) * s) / (0.062 * s)
    pec_dz = (z - z_pec) / (0.062 * s)
    front_mask = (y < -0.02 * s).astype(np.float32)
    pec_gauss = np.exp(-0.5 * (pec_dx * pec_dx + pec_dz * pec_dz)) * front_mask
    pec_amp = (0.032 if is_female else (0.014 + 0.016 * muscle)) * s
    pts[:, 1] -= pec_gauss * pec_amp

    # 2. Anterior linea alba / sternum subtle groove + rectus definition
    sternum_mask = np.exp(-((x / (0.018 * s)) ** 2)) * np.exp(-(((z - 1.24 * s) / (0.14 * s)) ** 2)) * front_mask
    pts[:, 1] += sternum_mask * (0.008 * s * muscle)

    # 3. Gluteal posterior contour (+Y is posterior back!)
    back_mask = (y > 0.02 * s).astype(np.float32)
    glute_dx = (np.abs(x) - 0.068 * s) / (0.065 * s)
    glute_dz = (z - 0.90 * s) / (0.080 * s)
    glute_gauss = np.exp(-0.5 * (glute_dx * glute_dx + glute_dz * glute_dz)) * back_mask
    pts[:, 1] += glute_gauss * ((0.026 if is_female else 0.020) * s * (0.8 + 0.4 * muscle))

    # 4. Facial nose bridge & brow ridge on anterior head
    nose_mask = (
        np.exp(-((x / (0.015 * s)) ** 2))
        * np.exp(-(((z - 1.635 * s) / (0.026 * s)) ** 2))
        * (y < -0.05 * s).astype(np.float32)
    )
    pts[:, 1] -= nose_mask * (0.018 * s)

    # 5. Flatten plantar sole cleanly at Z = 0
    min_z = float(np.min(pts[:, 2]))
    pts[:, 2] -= min_z
    sole_zone = pts[:, 2] < (0.018 * s)
    pts[sole_zone, 2] *= 0.25

    mesh.vertices.foreach_set("co", pts.ravel())
    mesh.update()


def _extract_shell_garment(
    body_obj: Any,
    name: str,
    face_predicate: Any,
    offset: float,
    thickness: float,
    mat: Any,
) -> Any | None:
    """Extract a fitted garment shell from selected anatomical body faces and solidify cleanly."""
    import bmesh  # type: ignore[import-not-found]
    import bpy  # type: ignore[import-not-found]

    bm = bmesh.new()
    bm.from_mesh(body_obj.data)
    bm.faces.ensure_lookup_table()

    remove_faces = [f for f in bm.faces if not face_predicate(f.calc_center_median())]
    if len(remove_faces) >= len(bm.faces):
        bm.free()
        return None

    bmesh.ops.delete(bm, geom=remove_faces, context="FACES")
    bmesh.ops.remove_doubles(bm, verts=bm.verts[:], dist=1e-5)
    bm.normal_update()

    # Displace outward along vertex normals so garment sits cleanly outside skin without z-fighting
    for v in bm.verts:
        v.co += v.normal * offset

    # Solidify rim only if thickness > 0 using Blender's SOLIDIFY modifier for watertight cuff edges
    mesh = bpy.data.meshes.new(f"{name}_Mesh")
    bm.to_mesh(mesh)
    bm.free()

    for poly in mesh.polygons:
        poly.use_smooth = True
    mesh.update()

    obj = bpy.data.objects.new(name, mesh)
    obj.data.materials.append(mat)
    bpy.context.collection.objects.link(obj)

    if thickness > 1e-4:
        sol = obj.modifiers.new(name="GarmentSolidify", type="SOLIDIFY")
        sol.thickness = thickness
        sol.offset = 1.0
        sol.use_rim = True
        deps = bpy.context.evaluated_depsgraph_get()
        ev = obj.evaluated_get(deps)
        baked = bpy.data.meshes.new_from_object(ev, preserve_all_data_layers=True, depsgraph=deps)
        old = obj.data
        obj.modifiers.remove(sol)
        obj.data = baked
        bpy.data.meshes.remove(old)

    ensure_smart_uv_project(obj)
    return obj


def _build_tactical_armor_and_backpack(
    ctx: GenerationContext,
    height: float,
    mats: dict[str, Any],
    include_armor: bool,
    include_backpack: bool,
) -> list[Any]:
    import bmesh  # type: ignore[import-not-found]
    import bpy  # type: ignore[import-not-found]

    s = height / 1.78
    extra_objs: list[Any] = []

    def add_beveled_box(bm: Any, size: tuple[float, float, float], center: tuple[float, float, float], mat_idx: int = 0) -> None:
        from mathutils import Vector  # type: ignore[import-not-found]

        ret = bmesh.ops.create_cube(bm, size=1.0)
        verts = ret["verts"]
        bmesh.ops.scale(bm, vec=Vector(size), verts=verts)
        bmesh.ops.translate(bm, vec=Vector(center), verts=verts)
        vset = set(verts)
        edges = [e for e in bm.edges if e.verts[0] in vset and e.verts[1] in vset]
        bev = bmesh.ops.bevel(bm, geom=edges, offset=min(size) * 0.14, offset_type="OFFSET", segments=2, profile=0.5, affect="EDGES")
        for f in bm.faces:
            if all(v in vset for v in f.verts) or f in bev.get("faces", []):
                f.material_index = mat_idx

    if include_armor:
        v_bm = bmesh.new()
        # Front & back ballistic plates + cummerbund + shoulder straps + 3 mag pouches
        add_beveled_box(v_bm, (0.29 * s, 0.045 * s, 0.31 * s), (0.0, -0.142 * s, 1.29 * s), 0)
        add_beveled_box(v_bm, (0.28 * s, 0.045 * s, 0.32 * s), (0.0, 0.135 * s, 1.30 * s), 0)
        for sx in (-1.0, 1.0):
            add_beveled_box(v_bm, (0.045 * s, 0.24 * s, 0.12 * s), (sx * 0.165 * s, 0.0, 1.21 * s), 1)
            add_beveled_box(v_bm, (0.062 * s, 0.22 * s, 0.038 * s), (sx * 0.105 * s, 0.0, 1.455 * s), 1)
        for px in (-0.085 * s, 0.0, 0.085 * s):
            add_beveled_box(v_bm, (0.068 * s, 0.042 * s, 0.115 * s), (px, -0.172 * s, 1.22 * s), 1)
        bmesh.ops.recalc_face_normals(v_bm, faces=v_bm.faces[:])
        v_mesh = bpy.data.meshes.new(f"{ctx.asset_name}_ArmorVest_Mesh")
        v_bm.to_mesh(v_mesh)
        v_bm.free()
        v_obj = bpy.data.objects.new(f"{ctx.asset_name}_ArmorVest", v_mesh)
        v_obj.data.materials.append(mats["secondary"])
        v_obj.data.materials.append(mats["primary"])
        bpy.context.collection.objects.link(v_obj)
        ensure_smart_uv_project(v_obj)
        extra_objs.append(v_obj)

    if include_backpack:
        bp_bm = bmesh.new()
        # Main tactical rucksack + upper lid pouch + lower utility pocket + side canteens + top bedroll
        add_beveled_box(bp_bm, (0.29 * s, 0.165 * s, 0.39 * s), (0.0, 0.225 * s, 1.28 * s), 0)
        add_beveled_box(bp_bm, (0.24 * s, 0.075 * s, 0.18 * s), (0.0, 0.315 * s, 1.20 * s), 1)
        add_beveled_box(bp_bm, (0.31 * s, 0.18 * s, 0.085 * s), (0.0, 0.225 * s, 1.47 * s), 1)
        for sx in (-1.0, 1.0):
            add_beveled_box(bp_bm, (0.055 * s, 0.10 * s, 0.20 * s), (sx * 0.165 * s, 0.22 * s, 1.22 * s), 1)
        bmesh.ops.recalc_face_normals(bp_bm, faces=bp_bm.faces[:])
        bp_mesh = bpy.data.meshes.new(f"{ctx.asset_name}_Backpack_Mesh")
        bp_bm.to_mesh(bp_mesh)
        bp_bm.free()
        bp_obj = bpy.data.objects.new(f"{ctx.asset_name}_Backpack", bp_mesh)
        bp_obj.data.materials.append(mats["primary"])
        bp_obj.data.materials.append(mats["trim"])
        bpy.context.collection.objects.link(bp_obj)
        ensure_smart_uv_project(bp_obj)
        extra_objs.append(bp_obj)

    return extra_objs


def _build_humanoid_armature_and_weights(
    name: str,
    landmarks: dict[str, tuple[float, float, float]],
    skinned_meshes: list[Any],
    height: float,
) -> Any:
    """Create a Godot 4 Humanoid-compatible Armature and assign normalized max-4 bone skin weights."""
    import bpy  # type: ignore[import-not-found]
    from mathutils import Vector  # type: ignore[import-not-found]

    s = height / 1.78
    arm_data = bpy.data.armatures.new(f"{name}_ArmatureData")
    arm_obj = bpy.data.objects.new(f"{name}_Armature", arm_data)
    bpy.context.collection.objects.link(arm_obj)
    bpy.context.view_layer.objects.active = arm_obj

    # Bone definitions: (bone_name, head_landmark_or_pos, tail_landmark_or_pos, parent_name, connected)
    bone_specs: list[tuple[str, tuple[float, float, float], tuple[float, float, float], str | None, bool]] = [
        ("Root", (0.0, 0.0, 0.0), (0.0, 0.0, 0.18 * s), None, False),
        ("Hips", landmarks["Hips"], landmarks["Spine"], "Root", False),
        ("Spine", landmarks["Spine"], landmarks["Chest"], "Hips", True),
        ("Chest", landmarks["Chest"], landmarks["UpperChest"], "Spine", True),
        ("UpperChest", landmarks["UpperChest"], landmarks["Neck"], "Chest", True),
        ("Neck", landmarks["Neck"], landmarks["HeadBase"], "UpperChest", True),
        ("Head", landmarks["HeadBase"], landmarks["HeadTop"], "Neck", True),
    ]

    for side in ("Left", "Right"):
        bone_specs.extend(
            [
                (f"{side}Shoulder", landmarks["ClavicleCenter"], landmarks[f"{side}Shoulder"], "UpperChest", False),
                (f"{side}UpperArm", landmarks[f"{side}UpperArm"], landmarks[f"{side}LowerArm"], f"{side}Shoulder", False),
                (f"{side}LowerArm", landmarks[f"{side}LowerArm"], landmarks[f"{side}Hand"], f"{side}UpperArm", True),
                (f"{side}Hand", landmarks[f"{side}Hand"], landmarks[f"{side}Palm"], f"{side}LowerArm", True),
                (f"{side}ThumbProximal", landmarks[f"{side}ThumbProximal"], landmarks[f"{side}ThumbTip"], f"{side}Hand", False),
                (f"{side}IndexProximal", landmarks[f"{side}IndexProximal"], landmarks[f"{side}IndexTip"], f"{side}Hand", False),
                (f"{side}MiddleProximal", landmarks[f"{side}MiddleProximal"], landmarks[f"{side}MiddleTip"], f"{side}Hand", False),
                (f"{side}RingProximal", landmarks[f"{side}RingProximal"], landmarks[f"{side}RingTip"], f"{side}Hand", False),
                (f"{side}PinkyProximal", landmarks[f"{side}PinkyProximal"], landmarks[f"{side}PinkyTip"], f"{side}Hand", False),
                (f"{side}UpperLeg", landmarks[f"{side}UpperLeg"], landmarks[f"{side}LowerLeg"], "Hips", False),
                (f"{side}LowerLeg", landmarks[f"{side}LowerLeg"], landmarks[f"{side}Foot"], f"{side}UpperLeg", True),
                (f"{side}Foot", landmarks[f"{side}Foot"], landmarks[f"{side}Toes"], f"{side}LowerLeg", True),
            ]
        )

    bpy.ops.object.mode_set(mode="EDIT")
    edit_bones = arm_data.edit_bones
    created_bones: dict[str, Any] = {}
    for b_name, head_pt, tail_pt, parent_name, use_conn in bone_specs:
        eb = edit_bones.new(b_name)
        eb.head = Vector(head_pt)
        tail_v = Vector(tail_pt)
        if (tail_v - eb.head).length < 1e-3:
            tail_v = eb.head + Vector((0.0, 0.0, 0.05))
        eb.tail = tail_v
        if parent_name and parent_name in created_bones:
            eb.parent = created_bones[parent_name]
            eb.use_connect = use_conn
        created_bones[b_name] = eb
    bpy.ops.object.mode_set(mode="OBJECT")

    # Exclude non-deforming `Root` from skinning so all weights map onto anatomical deformation bones
    deform_specs = [b for b in bone_specs if b[0] != "Root"]
    seg_a = np.array([b[1] for b in deform_specs], dtype=np.float64)
    seg_b = np.array([b[2] for b in deform_specs], dtype=np.float64)
    seg_ab = seg_b - seg_a
    seg_len_sq = np.maximum(np.sum(seg_ab * seg_ab, axis=1), 1e-8)
    deform_names = [b[0] for b in deform_specs]

    # Bind each mesh to Armature with vectorized capsule-distance Gaussian weights (max 4 influences, sum=1.0)
    sigma = 0.075 * s
    inv_two_sigma2 = 1.0 / (2.0 * sigma * sigma)

    for mesh_obj in skinned_meshes:
        mesh_obj.parent = arm_obj
        arm_mod = mesh_obj.modifiers.new(name="Armature", type="ARMATURE")
        arm_mod.object = arm_obj

        vgroups = {bname: mesh_obj.vertex_groups.new(name=bname) for bname in deform_names}
        n_v = len(mesh_obj.data.vertices)
        v_coords = np.empty(n_v * 3, dtype=np.float32)
        mesh_obj.data.vertices.foreach_get("co", v_coords)
        pts = v_coords.reshape((-1, 3)).astype(np.float64)

        # Compute point-to-segment squared distance (N_verts, N_bones)
        diff = pts[:, None, :] - seg_a[None, :, :]
        t_proj = np.clip(np.sum(diff * seg_ab[None, :, :], axis=2) / seg_len_sq[None, :], 0.0, 1.0)
        closest = seg_a[None, :, :] + t_proj[:, :, None] * seg_ab[None, :, :]
        dist_sq = np.sum((pts[:, None, :] - closest) ** 2, axis=2)

        raw_w = np.exp(-dist_sq * inv_two_sigma2) + 1e-7
        # Keep top 4 influences per vertex (glTF 2.0 JOINTS_0 / WEIGHTS_0 requirement)
        top4_idx = np.argpartition(-raw_w, kth=3, axis=1)[:, :4]
        row_idx = np.arange(n_v)[:, None]
        top4_w = raw_w[row_idx, top4_idx]
        # Zero tiny negligible weights unless primary
        top4_w = np.where(top4_w >= 0.005, top4_w, 0.0)
        zero_rows = np.sum(top4_w, axis=1) < 1e-8
        if np.any(zero_rows):
            best_col = np.argmax(raw_w[zero_rows], axis=1)
            top4_idx[zero_rows, 0] = best_col
            top4_w[zero_rows, 0] = 1.0

        # Normalize strictly so sum(weights) == 1.000000 for every single vertex!
        top4_w = top4_w / np.sum(top4_w, axis=1, keepdims=True)

        for v_i in range(n_v):
            for k in range(4):
                w_val = float(top4_w[v_i, k])
                if w_val > 0.0:
                    b_idx = int(top4_idx[v_i, k])
                    vgroups[deform_names[b_idx]].add([v_i], w_val, "REPLACE")

    # Add a clean 24-frame subtle `IdleReady` breathing/stance animation clip on the Armature!
    arm_obj.animation_data_create()
    action = bpy.data.actions.new(name="IdleReady")
    arm_obj.animation_data.action = action
    chest_pb = arm_obj.pose.bones.get("Chest")
    hips_pb = arm_obj.pose.bones.get("Hips")
    if chest_pb and hips_pb:
        chest_pb.rotation_mode = "XYZ"
        hips_pb.location = (0.0, 0.0, 0.0)
        hips_pb.keyframe_insert(data_path="location", frame=1)
        chest_pb.rotation_euler = (0.0, 0.0, 0.0)
        chest_pb.keyframe_insert(data_path="rotation_euler", frame=1)

        hips_pb.location = (0.0, 0.0, -0.012 * s)
        hips_pb.keyframe_insert(data_path="location", frame=13)
        chest_pb.rotation_euler = (0.035, 0.0, 0.0)
        chest_pb.keyframe_insert(data_path="rotation_euler", frame=13)

        hips_pb.location = (0.0, 0.0, 0.0)
        hips_pb.keyframe_insert(data_path="location", frame=25)
        chest_pb.rotation_euler = (0.0, 0.0, 0.0)
        chest_pb.keyframe_insert(data_path="rotation_euler", frame=25)

    return arm_obj


def generate_humanoid_asset(ctx: GenerationContext) -> list[Any]:
    """Generate a connected anatomical humanoid character with optional clothing, gear, and rig."""
    import bpy  # type: ignore[import-not-found]

    p = ctx.parameters
    is_female = str(p.get("gender", "male")) == "female"
    height = float(p.get("height", 1.78))
    muscle = float(p.get("musculature", 0.58))
    shoulder_w = float(p.get("shoulder_width", 1.0))
    hip_w = float(p.get("hip_width", 1.0))
    limb_s = float(p.get("limb_length_scale", 1.0))

    inc_clothing = bool(p.get("include_clothing", True))
    inc_hair = bool(p.get("include_hair", True))
    inc_shoes = bool(p.get("include_shoes", True))
    inc_armor = bool(p.get("include_armor", False))
    inc_backpack = bool(p.get("include_backpack", False))
    inc_rig = bool(p.get("include_rig", True))

    mats = resolve_theme_materials(ctx.material_preset, "tactical_military", ctx.seed, wear_amount=0.3)
    outfit_rgb_override = _parse_hex_rgb_optional(p.get("outfit_color"))
    if outfit_rgb_override is not None:
        mats["primary"] = get_or_create_pbr_material(
            name=f"Mat_OutfitCustom_{ctx.seed}",
            base_rgb=outfit_rgb_override,
            metallic=0.04,
            roughness=0.48,
            pattern="fabric",
            seed=ctx.seed + 3,
            use_texture=False,
        )
    rng = np.random.default_rng(ctx.seed)
    skin_tone_shift = float(rng.uniform(-0.04, 0.04))
    skin_rgb_override = _parse_hex_rgb_optional(p.get("skin_color"))
    skin_rgb = skin_rgb_override or (
        float(np.clip(0.68 + skin_tone_shift, 0.35, 0.85)),
        float(np.clip(0.49 + skin_tone_shift * 0.8, 0.25, 0.72)),
        float(np.clip(0.37 + skin_tone_shift * 0.6, 0.18, 0.62)),
    )
    skin_mat = get_or_create_pbr_material(
        name=f"Mat_Skin_{ctx.seed}",
        base_rgb=skin_rgb,
        metallic=0.0,
        roughness=0.58,
        pattern="smooth",
        seed=ctx.seed,
        use_texture=False,
    )
    hair_mat = get_or_create_pbr_material(
        name=f"Mat_Hair_{ctx.seed}",
        base_rgb=(0.11, 0.08, 0.06),
        metallic=0.02,
        roughness=0.52,
        pattern="wood",
        seed=ctx.seed + 19,
        use_texture=True,
    )

    is_t_pose = str(p.get("pose", "")) == "t_pose" or ctx.preset_id == "midpoly_character"
    flat_shading = bool(p.get("flat_shading", ctx.preset_id == "midpoly_character"))

    verts, edges, radii, landmarks = _build_anatomical_wire_spec(
        height=height,
        is_female=is_female,
        muscle=muscle,
        shoulder_scale=shoulder_w,
        hip_scale=hip_w,
        limb_scale=limb_s,
        t_pose=is_t_pose,
    )

    wire_mesh = bpy.data.meshes.new(f"{ctx.asset_name}_Wire")
    wire_mesh.from_pydata(verts, edges, [])
    body_obj = bpy.data.objects.new(f"{ctx.asset_name}_Body", wire_mesh)
    bpy.context.collection.objects.link(body_obj)

    skin_mod = body_obj.modifiers.new(name="AnatomicalSkin", type="SKIN")
    skin_mod.branch_smoothing = 0.28
    skin_mod.use_smooth_shade = not flat_shading

    sv_data = body_obj.data.skin_vertices[0].data
    sv_data[0].use_root = True
    for idx, (rx, ry) in enumerate(radii):
        sv_data[idx].radius = (float(rx), float(ry))

    sub_mod = body_obj.modifiers.new(name="AnatomicalSubsurf", type="SUBSURF")
    if ctx.quality_profile == QualityProfile.PROTOTYPE:
        sub_mod.levels = 1
    else:
        sub_mod.levels = 2

    depsgraph = bpy.context.evaluated_depsgraph_get()
    eval_body = body_obj.evaluated_get(depsgraph)
    baked_body_mesh = bpy.data.meshes.new_from_object(eval_body, preserve_all_data_layers=True, depsgraph=depsgraph)
    body_obj.modifiers.clear()
    body_obj.data = baked_body_mesh
    bpy.data.meshes.remove(wire_mesh)

    # Apply anatomical muscle & facial harmonic sculpting + sole grounding
    _sculpt_anatomical_harmonics(body_obj.data, height=height, is_female=is_female, muscle=muscle)
    body_obj.data.materials.append(skin_mat)
    ensure_smart_uv_project(body_obj)

    all_meshes: list[Any] = [body_obj]
    s = height / 1.78

    # Fitted clothing shells extracted directly from sculpted anatomy for zero clipping!
    if inc_clothing:
        shirt = _extract_shell_garment(
            body_obj,
            f"{ctx.asset_name}_TacticalShirt",
            lambda c: (1.03 * s <= c.z <= 1.48 * s) and (abs(c.x) <= 0.34 * s),
            offset=0.0055 * s,
            thickness=0.004 * s,
            mat=mats["primary"],
        )
        if shirt is not None:
            all_meshes.append(shirt)

        trousers = _extract_shell_garment(
            body_obj,
            f"{ctx.asset_name}_CombatTrousers",
            lambda c: (0.17 * s <= c.z <= 1.055 * s),
            offset=0.005 * s,
            thickness=0.004 * s,
            mat=mats["secondary"] if ctx.material_preset == "cyber_arena" else mats["trim"],
        )
        if trousers is not None:
            all_meshes.append(trousers)

    if inc_shoes:
        boots = _extract_shell_garment(
            body_obj,
            f"{ctx.asset_name}_CombatBoots",
            lambda c: c.z <= 0.20 * s,
            offset=0.0075 * s,
            thickness=0.006 * s,
            mat=mats["trim"],
        )
        if boots is not None:
            # Ground boot soles at Z = 0
            for v in boots.data.vertices:
                if v.co.z < 0.0:
                    v.co.z = 0.0
            boots.data.update()
            all_meshes.append(boots)

    if inc_hair:
        hair = _extract_shell_garment(
            body_obj,
            f"{ctx.asset_name}_Hair",
            lambda c: (c.z >= 1.665 * s) or (c.z >= 1.56 * s and c.y > 0.015 * s),
            offset=0.009 * s,
            thickness=0.010 * s if is_female else 0.007 * s,
            mat=hair_mat,
        )
        if hair is not None:
            all_meshes.append(hair)

    if inc_armor or inc_backpack:
        gear_objs = _build_tactical_armor_and_backpack(ctx, height, mats, inc_armor, inc_backpack)
        all_meshes.extend(gear_objs)

    if inc_rig:
        arm_obj = _build_humanoid_armature_and_weights(ctx.asset_name, landmarks, all_meshes, height)
        return [arm_obj, *all_meshes]

    return all_meshes
