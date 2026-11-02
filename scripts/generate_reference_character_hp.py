#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""High-poly, UE5-ready stylized character from the front/back reference.

Run with the repo's bpy wheel runtime:

    LD_LIBRARY_PATH=<xstubs> python scripts/generate_reference_character_hp.py

Outputs in ``artifacts_out/blender/`` (git-ignored):
  reference_character_hp.blend / .glb (subdivided, skinned) / reference_hp_preview.png
"""

from __future__ import annotations

import math
import os
import random

import bpy
from mathutils import Vector

OUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                       "..", "artifacts_out", "blender")
os.makedirs(OUT_DIR, exist_ok=True)

SEG = 48          # radial segments per loft ring (high-poly base cage)
SUBDIV = 3        # subdivision levels applied -> final dense mesh

# --------------------------------------------------------------------------- #
# Scene + material helpers
# --------------------------------------------------------------------------- #

def reset_scene():
    bpy.ops.wm.read_factory_settings(use_empty=True)
    for block in (bpy.data.meshes, bpy.data.curves, bpy.data.materials,
                  bpy.data.cameras, bpy.data.lights, bpy.data.armatures):
        for item in list(block):
            block.remove(item)


def make_mat(name, color, rough=0.5, metallic=0.0, subsurface=0.0, noise_bump=0.0):
    m = bpy.data.materials.new(name)
    m.use_nodes = True
    nt = m.node_tree
    bsdf = nt.nodes["Principled BSDF"]
    bsdf.inputs["Base Color"].default_value = color
    bsdf.inputs["Roughness"].default_value = rough
    bsdf.inputs["Metallic"].default_value = metallic
    if subsurface:
        bsdf.inputs["Subsurface Weight"].default_value = subsurface
    if noise_bump:
        tex = nt.nodes.new("ShaderNodeTexNoise")
        tex.inputs["Scale"].default_value = 60.0
        tex.inputs["Detail"].default_value = 3.0
        bump = nt.nodes.new("ShaderNodeBump")
        bump.inputs["Strength"].default_value = noise_bump
        nt.links.new(tex.outputs["Fac"], bump.inputs["Height"])
        nt.links.new(bump.outputs["Normal"], bsdf.inputs["Normal"])
    return m


def loft(name, rings, mat, seg=SEG, cap_top=True, cap_bottom=True):
    verts, faces = [], []
    n = len(rings)
    for (z, cx, cy, rx, ry) in rings:
        for i in range(seg):
            a = 2 * math.pi * i / seg
            verts.append((cx + rx * math.cos(a), cy + ry * math.sin(a), z))
    for r in range(n - 1):
        for i in range(seg):
            j = (i + 1) % seg
            faces.append((r * seg + i, r * seg + j,
                          (r + 1) * seg + j, (r + 1) * seg + i))
    if cap_bottom:
        faces.append(tuple(reversed(range(seg))))
    if cap_top:
        faces.append(tuple((n - 1) * seg + i for i in range(seg)))
    me = bpy.data.meshes.new(name)
    me.from_pydata(verts, [], faces)
    me.update()
    ob = bpy.data.objects.new(name, me)
    bpy.context.collection.objects.link(ob)
    for p in me.polygons:
        p.use_smooth = True
    if mat:
        ob.data.materials.append(mat)
    return ob


def tube(name, points, radii, mat, seg=20):
    pts = [Vector(p) for p in points]
    rings = []
    for i, p in enumerate(pts):
        if i == 0:
            d = (pts[1] - p).normalized()
        elif i == len(pts) - 1:
            d = (p - pts[i - 1]).normalized()
        else:
            d = (pts[i + 1] - pts[i - 1]).normalized()
        up = Vector((0, 0, 1)) if abs(d.z) < 0.9 else Vector((1, 0, 0))
        u = d.cross(up).normalized()
        v = d.cross(u).normalized()
        rings.append((p, u * radii[i], v * radii[i]))
    verts, faces = [], []
    n = len(rings)
    for (p, u, v) in rings:
        for i in range(seg):
            a = 2 * math.pi * i / seg
            verts.append(tuple(p + u * math.cos(a) + v * math.sin(a)))
    for r in range(n - 1):
        for i in range(seg):
            j = (i + 1) % seg
            faces.append((r * seg + i, r * seg + j, (r + 1) * seg + j, (r + 1) * seg + i))
    faces.append(tuple(reversed(range(seg))))
    faces.append(tuple((n - 1) * seg + i for i in range(seg)))
    me = bpy.data.meshes.new(name)
    me.from_pydata(verts, [], faces)
    me.update()
    ob = bpy.data.objects.new(name, me)
    bpy.context.collection.objects.link(ob)
    for p in me.polygons:
        p.use_smooth = True
    if mat:
        ob.data.materials.append(mat)
    return ob


def sphere(name, loc, scale, mat, seg=40, rings=28):
    bpy.ops.mesh.primitive_uv_sphere_add(segments=seg, ring_count=rings, location=loc)
    ob = bpy.context.active_object
    ob.name = name
    ob.scale = scale
    bpy.ops.object.transform_apply(scale=True)
    for p in ob.data.polygons:
        p.use_smooth = True
    if mat:
        ob.data.materials.append(mat)
    return ob


def box(name, loc, scale, mat, bevel=0.01):
    bpy.ops.mesh.primitive_cube_add(location=loc)
    ob = bpy.context.active_object
    ob.name = name
    ob.scale = scale
    bpy.ops.object.transform_apply(scale=True)
    if bevel:
        mod = ob.modifiers.new("bev", "BEVEL")
        mod.width = bevel
        mod.segments = 3
    if mat:
        ob.data.materials.append(mat)
    return ob


def curve_tube(name, points, radius, mat, bevel_res=3):
    cu = bpy.data.curves.new(name, "CURVE")
    cu.dimensions = "3D"
    cu.bevel_depth = radius
    cu.bevel_resolution = bevel_res
    sp = cu.splines.new("BEZIER")
    sp.bezier_points.add(len(points) - 1)
    for bp, co in zip(sp.bezier_points, points):
        bp.co = co
        bp.handle_left_type = "AUTO"
        bp.handle_right_type = "AUTO"
    ob = bpy.data.objects.new(name, cu)
    bpy.context.collection.objects.link(ob)
    if mat:
        ob.data.materials.append(mat)
    return ob


def subdivide(obj, level=SUBDIV):
    mod = obj.modifiers.new("subd", "SUBSURF")
    mod.levels = level
    mod.render_levels = level
    bpy.context.view_layer.objects.active = obj
    obj.select_set(True)
    bpy.ops.object.modifier_apply(modifier=mod.name)
    obj.select_set(False)
    return obj

# --------------------------------------------------------------------------- #
# Materials
# --------------------------------------------------------------------------- #
reset_scene()

skin = make_mat("Skin", (0.72, 0.52, 0.42, 1), rough=0.38, subsurface=0.12)
hair_m = make_mat("Hair", (0.045, 0.030, 0.022, 1), rough=0.28)
top_m = make_mat("Camisole", (0.012, 0.012, 0.014, 1), rough=0.75, noise_bump=0.15)
jean_m = make_mat("Jeans", (0.075, 0.13, 0.24, 1), rough=0.9, noise_bump=0.35)
jean_dark = make_mat("JeansDark", (0.05, 0.09, 0.17, 1), rough=0.95, noise_bump=0.4)
belt_m = make_mat("Belt", (0.015, 0.015, 0.018, 1), rough=0.35)
shoe_m = make_mat("Sneaker", (0.92, 0.92, 0.94, 1), rough=0.55, noise_bump=0.1)
sole_m = make_mat("Sole", (0.85, 0.85, 0.87, 1), rough=0.7)
white_m = make_mat("EyeWhite", (0.97, 0.97, 0.98, 1), rough=0.12)
iris_m = make_mat("Iris", (0.16, 0.33, 0.58, 1), rough=0.08)
lip_m = make_mat("Lips", (0.62, 0.30, 0.28, 1), rough=0.3, subsurface=0.05)
silver_m = make_mat("Silver", (0.72, 0.74, 0.8, 1), rough=0.22, metallic=0.95)

# --------------------------------------------------------------------------- #
# Body (high-seg loft) + head/face
# --------------------------------------------------------------------------- #
body = loft("Body", [
    (0.86, 0, 0, 0.100, 0.074),
    (0.94, 0, 0, 0.158, 0.108),
    (1.04, 0, 0, 0.168, 0.110),
    (1.14, 0, 0, 0.130, 0.090),
    (1.24, 0, 0, 0.140, 0.097),
    (1.34, 0, 0, 0.150, 0.102),
    (1.44, 0, 0, 0.137, 0.094),
    (1.50, 0, 0, 0.178, 0.096),
    (1.545, 0, 0, 0.053, 0.049),
], skin)
subdivide(body)

head = sphere("Head", (0, 0, 1.655), (0.083, 0.089, 0.106), skin)
subdivide(head)
sphere("Jaw", (0, 0.006, 1.598), (0.060, 0.064, 0.057), skin)
for sx in (-1, 1):
    sphere(f"Ear{sx}", (0.081 * sx, 0.004, 1.655), (0.012, 0.018, 0.024), skin, seg=24, rings=16)

# face features
for sx in (-1, 1):
    sphere(f"EyeW{sx}", (0.032 * sx, 0.073, 1.672), (0.0135, 0.008, 0.011), white_m, seg=20, rings=14)
    sphere(f"Iris{sx}", (0.032 * sx, 0.0795, 1.672), (0.0076, 0.004, 0.0086), iris_m, seg=20, rings=14)
    sphere(f"Pupil{sx}", (0.032 * sx, 0.0825, 1.672), (0.0032, 0.0025, 0.004), belt_m, seg=14, rings=10)
    b = box(f"Brow{sx}", (0.033 * sx, 0.069, 1.701), (0.021, 0.008, 0.0042), hair_m, bevel=0.003)
    b.rotation_euler = (0.25, 0, -0.12 * sx)
sphere("Nose", (0, 0.087, 1.644), (0.011, 0.014, 0.021), skin, seg=20, rings=14)
sphere("Lips", (0, 0.071, 1.605), (0.021, 0.007, 0.0085), lip_m, seg=20, rings=14)

# necklace
bpy.ops.mesh.primitive_torus_add(major_radius=0.052, minor_radius=0.0035,
                                 major_segments=32, minor_segments=10, location=(0, 0.012, 1.545))
nk = bpy.context.active_object
nk.name = "Necklace"
nk.scale = (1.0, 0.55, 1.0)
bpy.ops.object.transform_apply(scale=True)
nk.data.materials.append(silver_m)
sphere("Pendant", (0, 0.040, 1.512), (0.008, 0.004, 0.010), silver_m, seg=16, rings=12)

# --------------------------------------------------------------------------- #
# Arms (T-pose, slight downward slope) + hands with fingers
# --------------------------------------------------------------------------- #
for sx in (-1, 1):
    pts = [(0.185 * sx, 0, 1.485), (0.34 * sx, 0, 1.462), (0.50 * sx, 0, 1.445),
           (0.64 * sx, 0, 1.435), (0.735 * sx, 0, 1.432)]
    subdivide(tube(f"Arm{sx}", pts, [0.053, 0.045, 0.039, 0.033, 0.027], skin, seg=24))
    subdivide(sphere(f"Hand{sx}", (0.775 * sx, 0, 1.430), (0.027, 0.013, 0.046), skin, seg=20, rings=14))
    for fi, ang in enumerate((-0.45, -0.15, 0.15, 0.45)):
        base = Vector((0.772 * sx, 0.004 * math.sin(ang), 1.430 + 0.011 * fi - 0.014))
        mid = base + Vector((0.030 * sx, 0.008 * math.sin(ang), -0.004))
        tip = base + Vector((0.052 * sx, 0.012 * math.sin(ang), -0.010))
        tube(f"Finger{sx}_{fi}", [tuple(base), tuple(mid), tuple(tip)],
             [0.0078, 0.0068, 0.0052], skin, seg=10)
    # forearm tattoo hint: thin dark band
    tube(f"Tattoo{sx}", [(0.47 * sx, 0.0405, 1.4405), (0.50 * sx, 0.0400, 1.439)],
         [0.0400, 0.0398], hair_m, seg=12)

# --------------------------------------------------------------------------- #
# Legs
# --------------------------------------------------------------------------- #
for sx in (-1, 1):
    x = 0.088 * sx
    subdivide(tube(f"Leg{sx}", [(x, 0, 0.90), (x, 0, 0.72), (x, 0, 0.52), (x, 0.004, 0.30),
                      (x, 0.008, 0.12), (x, 0.010, 0.045)],
         [0.106, 0.096, 0.083, 0.073, 0.059, 0.039], skin, seg=28))

# --------------------------------------------------------------------------- #
# Hair: scalp + many wavy strands
# --------------------------------------------------------------------------- #
sphere("Scalp", (0, -0.018, 1.676), (0.088, 0.088, 0.110), hair_m)
random.seed(7)
for sx in (-1, 1):
    for k in range(7):
        off = (0.030 + 0.0095 * k) * sx
        wave = random.uniform(0.008, 0.02)
        pts = [(off, -0.01, 1.75), (off * 1.22, -0.01 + wave, 1.62), (off * 1.32, -0.015, 1.46),
               (off * 1.28 + wave * sx, -0.01, 1.30), (off * 1.14 + wave, -0.005, 1.16)]
        curve_tube(f"Strand{sx}_{k}", pts, 0.011 - 0.0012 * k, hair_m)
for k in range(5):
    z0 = 1.73 - 0.025 * k
    wob = random.uniform(-0.015, 0.015)
    pts = [(0, -0.080 - 0.008 * k, z0), (wob, -0.098, 1.56), (wob * 1.4, -0.105, 1.36),
           (wob, -0.098, 1.20), (wob * 0.7, -0.09, 1.10)]
    curve_tube(f"Back{k}", pts, 0.017 - 0.0015 * k, hair_m)

# --------------------------------------------------------------------------- #
# Camisole (two front panels -> V neck) + straps
# --------------------------------------------------------------------------- #
for sx in (-1, 1):
    # inner edge of each panel moves toward x=0 with depth -> V neckline
    loft(f"TopFront{sx}", [
        (1.515, (0.035 + 0.085) * sx, 0.045, 0.085, 0.070),
        (1.46, (0.028 + 0.088) * sx, 0.068, 0.088, 0.072),
        (1.40, (0.018 + 0.092) * sx, 0.088, 0.092, 0.072),
        (1.32, (0.008 + 0.096) * sx, 0.090, 0.096, 0.070),
        (1.22, (0.000 + 0.098) * sx, 0.088, 0.098, 0.068),
        (1.10, (0.000 + 0.104) * sx, 0.086, 0.104, 0.070),
    ], top_m, seg=32)
loft("TopBack", [
    (1.52, 0, -0.010, 0.150, 0.090),
    (1.45, 0, -0.020, 0.148, 0.096),
    (1.36, 0, -0.022, 0.155, 0.100),
    (1.26, 0, -0.020, 0.148, 0.098),
    (1.16, 0, -0.018, 0.140, 0.094),
    (1.075, 0, -0.018, 0.152, 0.104),
], top_m, seg=32)
for sx in (-1, 1):
    tube(f"Strap{sx}", [(0.075 * sx, 0.02, 1.505), (0.062 * sx, 0.01, 1.548)],
         [0.0075, 0.0075], top_m, seg=10)

# --------------------------------------------------------------------------- #
# Jeans: waistband, legs, pockets, belt loops, buckle, rips
# --------------------------------------------------------------------------- #
loft("Waistband", [
    (1.13, 0, 0, 0.184, 0.122),
    (1.09, 0, 0, 0.180, 0.120),
], jean_dark, seg=32)
loft("JeanHips", [
    (1.13, 0, 0, 0.186, 0.124),
    (1.04, 0, 0, 0.178, 0.120),
    (0.94, 0, 0, 0.130, 0.100),
], jean_m, seg=32)
for sx in (-1, 1):
    x = 0.088 * sx
    loft(f"JeanLeg{sx}", [
        (0.92, x, 0, 0.122, 0.116),
        (0.72, x, 0, 0.112, 0.108),
        (0.52, x, 0, 0.098, 0.097),
        (0.30, x, 0.004, 0.088, 0.088),
        (0.12, x, 0.008, 0.074, 0.075),
        (0.055, x, 0.010, 0.056, 0.061),
    ], jean_m, seg=28)
    # front pocket
    box(f"Pocket{sx}", (0.055 * sx, 0.088, 1.02), (0.038, 0.012, 0.055), jean_m, bevel=0.008)
    # back pocket
    box(f"BackPocket{sx}", (0.060 * sx, -0.092, 1.00), (0.042, 0.012, 0.050), jean_m, bevel=0.008)
# belt + loops + buckle
bpy.ops.mesh.primitive_torus_add(major_radius=0.168, minor_radius=0.017,
                                 major_segments=40, minor_segments=12, location=(0, 0, 1.105))
belt = bpy.context.active_object
belt.name = "Belt"
belt.scale = (1.0, 0.72, 1.0)
bpy.ops.object.transform_apply(scale=True)
belt.data.materials.append(belt_m)
box("Buckle", (0, 0.122, 1.105), (0.020, 0.008, 0.024), silver_m, bevel=0.005)
for i in range(5):
    a = -0.9 + i * 0.45
    box(f"Loop{i}", (0.170 * math.sin(a), 0.118 * math.cos(a), 1.105),
        (0.008, 0.008, 0.020), belt_m, bevel=0.002)
# ripped knees: dark hole + frayed rim
for sx in (-1, 1):
    for z in (0.545, 0.475):
        sphere(f"Rip{sx}_{z}", (0.088 * sx, 0.074, z), (0.030, 0.012, 0.024), skin, seg=16, rings=12)
        bpy.ops.mesh.primitive_torus_add(major_radius=0.030, minor_radius=0.006,
                                         major_segments=20, minor_segments=8,
                                         location=(0.088 * sx, 0.072, z))
        fr = bpy.context.active_object
        fr.name = f"Fray{sx}_{z}"
        fr.scale = (1.0, 0.45, 0.85)
        bpy.ops.object.transform_apply(scale=True)
        fr.data.materials.append(jean_m)

# --------------------------------------------------------------------------- #
# Sneakers with soles + laces
# --------------------------------------------------------------------------- #
for sx in (-1, 1):
    box(f"Shoe{sx}", (0.088 * sx, 0.038, 0.058), (0.050, 0.108, 0.056), shoe_m, bevel=0.022)
    box(f"Sole{sx}", (0.088 * sx, 0.038, 0.018), (0.052, 0.112, 0.018), sole_m, bevel=0.008)
    for li in range(4):
        curve_tube(f"Lace{sx}_{li}",
                   [(0.088 * sx - 0.020, 0.005 + li * 0.018, 0.085),
                    (0.088 * sx, 0.002 + li * 0.018, 0.095),
                    (0.088 * sx + 0.020, 0.005 + li * 0.018, 0.085)],
                   0.0035, sole_m, bevel_res=2)

# --------------------------------------------------------------------------- #
# Armature (UE5-style humanoid skeleton) + auto skinning
# --------------------------------------------------------------------------- #
arm_data = bpy.data.armatures.new("CharacterRig")
arm = bpy.data.objects.new("CharacterRig", arm_data)
bpy.context.collection.objects.link(arm)
bpy.context.view_layer.objects.active = arm
bpy.ops.object.mode_set(mode="EDIT")


def bone(name, head, tail):
    b = arm_data.edit_bones.new(name)
    b.head = head
    b.tail = tail
    return b


pelvis = bone("pelvis", (0, 0, 1.00), (0, 0, 1.10))
spine = bone("spine_01", (0, 0, 1.10), (0, 0, 1.30))
spine.parent = pelvis
chest = bone("spine_02", (0, 0, 1.30), (0, 0, 1.46))
chest.parent = spine
neck = bone("neck_01", (0, 0, 1.50), (0, 0, 1.58))
neck.parent = chest
head_b = bone("head", (0, 0, 1.58), (0, 0, 1.76))
head_b.parent = neck
for sx in (-1, 1):
    sh = bone(f"shoulder{'_L' if sx < 0 else '_R'}", (0.06 * sx, 0, 1.49), (0.19 * sx, 0, 1.485))
    sh.parent = chest
    ua = bone(f"upperarm{'_L' if sx < 0 else '_R'}", (0.19 * sx, 0, 1.485), (0.47 * sx, 0, 1.447))
    ua.parent = sh
    fa = bone(f"lowerarm{'_L' if sx < 0 else '_R'}", (0.47 * sx, 0, 1.447), (0.72 * sx, 0, 1.433))
    fa.parent = ua
    hand_b = bone(f"hand{'_L' if sx < 0 else '_R'}", (0.72 * sx, 0, 1.433), (0.80 * sx, 0, 1.430))
    hand_b.parent = fa
    th = bone(f"thigh{'_L' if sx < 0 else '_R'}", (0.088 * sx, 0, 0.95), (0.088 * sx, 0, 0.52))
    th.parent = pelvis
    calf = bone(f"calf{'_L' if sx < 0 else '_R'}", (0.088 * sx, 0, 0.52), (0.088 * sx, 0.008, 0.10))
    calf.parent = th
    foot = bone(f"foot{'_L' if sx < 0 else '_R'}", (0.088 * sx, 0.008, 0.10), (0.088 * sx, 0.06, 0.02))
    foot.parent = calf

bpy.ops.object.mode_set(mode="OBJECT")

SKIN_PREFIX = ("Body", "Head", "Jaw", "Ear", "Arm", "Hand", "Finger", "Leg", "EyeW", "Iris", "Pupil", "Nose", "Lips", "Necklace", "Pendant")
SKIN_EXCLUDE = ("Ground",)
skinned = [o for o in bpy.data.objects if o.type == "MESH"
           and o.name.startswith(SKIN_PREFIX) and o.name not in SKIN_EXCLUDE]
bpy.ops.object.select_all(action="DESELECT")
for ob in skinned:
    ob.select_set(True)
arm.select_set(True)
bpy.context.view_layer.objects.active = arm
bpy.ops.object.parent_set(type="ARMATURE_AUTO")

# --------------------------------------------------------------------------- #
# Ground, lights, camera, render, save, export
# --------------------------------------------------------------------------- #
bpy.ops.mesh.primitive_plane_add(size=8, location=(0, 0, 0))
ground = bpy.context.active_object
ground.name = "Ground"
ground.data.materials.append(make_mat("Ground", (0.55, 0.55, 0.58, 1), rough=0.95))


def add_light(name, loc, energy, color=(1, 1, 1), size=2.0):
    ld = bpy.data.lights.new(name, "AREA")
    ld.energy = energy
    ld.color = color
    ld.shape = "DISK"
    ld.size = size
    ob = bpy.data.objects.new(name, ld)
    bpy.context.collection.objects.link(ob)
    ob.location = loc
    return ob


key = add_light("Key", (2.5, 2.5, 3.5), 1000, (1.0, 0.95, 0.9))
key.rotation_euler = (0.5, 0.1, 0.8)
add_light("Fill", (-2.5, 2.0, 2.2), 700, (0.9, 0.95, 1.0))
add_light("Rim", (0.5, -2.5, 3.2), 1200)

cam_data = bpy.data.cameras.new("Cam")
cam = bpy.data.objects.new("Cam", cam_data)
bpy.context.collection.objects.link(cam)
cam.location = (0, 3.6, 1.0)
cam.rotation_euler = (Vector((0, 0, 0.95)) - Vector(cam.location)).to_track_quat("-Z", "Y").to_euler()
cam_data.lens = 60
bpy.context.scene.camera = cam

scene = bpy.context.scene
scene.render.engine = "CYCLES"
scene.cycles.samples = 64
scene.cycles.use_denoising = True
scene.render.resolution_x = 800
scene.render.resolution_y = 1100
scene.render.filepath = os.path.join(OUT_DIR, "reference_hp_preview.png")
scene.world = bpy.data.worlds.new("World")
scene.world.use_nodes = True
scene.world.node_tree.nodes["Background"].inputs[0].default_value = (0.7, 0.7, 0.73, 1)

blend_path = os.path.join(OUT_DIR, "reference_character_hp.blend")
bpy.ops.wm.save_as_mainfile(filepath=blend_path)
print("saved", blend_path)

bpy.ops.render.render(write_still=True)
print("rendered", scene.render.filepath)

bpy.ops.export_scene.gltf(
    filepath=os.path.join(OUT_DIR, "reference_character_hp.glb"),
    export_format="GLB", export_skins=True, export_apply=True,
    export_yup=True)
print("exported glb")

tris = sum(len(o.data.polygons) for o in bpy.data.objects if o.type == "MESH")
verts = sum(len(o.data.vertices) for o in bpy.data.objects if o.type == "MESH")
print(f"DONE mesh verts={verts} faces={tris} objects={len(bpy.data.objects)}")
