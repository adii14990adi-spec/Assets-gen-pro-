#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Build a stylized 3D character matching the reference photo with bpy.

Reference look (IMG-20261101-WA3164.jpg):
  * female figure, arms stretched out horizontally (T-pose)
  * black spaghetti-strap camisole top
  * high-waisted blue ripped jeans + black belt
  * white sneakers, long dark wavy hair, delicate necklace

Run with the repo's bpy wheel runtime:

    LD_LIBRARY_PATH=<xstubs> python scripts/generate_reference_character.py

Outputs (git-ignored ``artifacts_out/blender/``):
  reference_character.blend, reference_character.glb, reference_preview.png
"""

from __future__ import annotations

import math
import os

import bpy
from mathutils import Vector

# --------------------------------------------------------------------------- #
# Config
# --------------------------------------------------------------------------- #
OUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                       "..", "artifacts_out", "blender")
os.makedirs(OUT_DIR, exist_ok=True)

SEG = 24          # radial segments of every loft
SKIN = (0.784, 0.576, 0.463, 1.0)   # warm skin tone
HAIR_C = (0.055, 0.038, 0.030, 1.0)
TOP_C = (0.015, 0.015, 0.017, 1.0)
JEAN_C = (0.085, 0.155, 0.290, 1.0)
BELT_C = (0.02, 0.02, 0.022, 1.0)
SHOE_C = (0.93, 0.93, 0.95, 1.0)

# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #

def reset_scene():
    bpy.ops.wm.read_factory_settings(use_empty=True)
    for block in (bpy.data.meshes, bpy.data.curves, bpy.data.materials,
                  bpy.data.cameras, bpy.data.lights):
        for item in list(block):
            block.remove(item)


def make_mat(name, color, rough=0.55, metallic=0.0):
    m = bpy.data.materials.new(name)
    m.use_nodes = True
    bsdf = m.node_tree.nodes["Principled BSDF"]
    bsdf.inputs["Base Color"].default_value = color
    bsdf.inputs["Roughness"].default_value = rough
    bsdf.inputs["Metallic"].default_value = metallic
    return m


def loft(name, rings, mat, seg=SEG, cap_top=True, cap_bottom=True):
    """rings: list of (z, cx, cy, rx, ry). Returns mesh object."""
    verts, faces = [], []
    n = len(rings)
    for (z, cx, cy, rx, ry) in rings:
        for i in range(seg):
            a = 2 * math.pi * i / seg
            verts.append((cx + rx * math.cos(a), cy + ry * math.sin(a), z))
    for r in range(n - 1):
        for i in range(seg):
            j = (i + 1) % seg
            a, b = r * seg + i, r * seg + j
            c, d = (r + 1) * seg + j, (r + 1) * seg + i
            faces.append((a, b, c, d))
    if cap_bottom:
        faces.append(tuple(reversed([i for i in range(seg)])))
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


def tube(name, points, radii, mat, seg=16):
    """Loft a tube along a polyline of 3D points."""
    pts = [Vector(p) for p in points]
    rings = []
    for i, p in enumerate(pts):
        if i == 0:
            d = (pts[1] - p).normalized()
        elif i == len(pts) - 1:
            d = (p - pts[i - 1]).normalized()
        else:
            d = (pts[i + 1] - pts[i - 1]).normalized()
        # build orthonormal frame
        up = Vector((0, 0, 1)) if abs(d.z) < 0.9 else Vector((1, 0, 0))
        u = d.cross(up).normalized()
        v = d.cross(u).normalized()
        r = radii[i]
        rings.append((p, u * r, v * r))
    verts, faces = [], []
    n = len(rings)
    for (p, u, v) in rings:
        for i in range(seg):
            a = 2 * math.pi * i / seg
            w = u * math.cos(a) + v * math.sin(a)
            verts.append(tuple(p + w))
    for rr in range(n - 1):
        for i in range(seg):
            j = (i + 1) % seg
            faces.append((rr * seg + i, rr * seg + j,
                          (rr + 1) * seg + j, (rr + 1) * seg + i))
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


def sphere(name, loc, scale, mat, seg=24, rings=16):
    bpy.ops.mesh.primitive_uv_sphere_add(segments=seg, ring_count=rings,
                                          location=loc)
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
    if bevel > 0:
        mod = ob.modifiers.new("bev", "BEVEL")
        mod.width = bevel
        mod.segments = 2
    if mat:
        ob.data.materials.append(mat)
    return ob


def join_objects(objs, name):
    bpy.ops.object.select_all(action="DESELECT")
    for o in objs:
        o.select_set(True)
    bpy.context.view_layer.objects.active = objs[0]
    bpy.ops.object.join()
    ob = bpy.context.active_object
    ob.name = name
    return ob

# --------------------------------------------------------------------------- #
# Build
# --------------------------------------------------------------------------- #

reset_scene()

skin = make_mat("Skin", SKIN, rough=0.45)
hair_m = make_mat("Hair", HAIR_C, rough=0.35)
top_m = make_mat("Top", TOP_C, rough=0.7)
jean_m = make_mat("Jeans", JEAN_C, rough=0.85)
belt_m = make_mat("Belt", BELT_C, rough=0.4, metallic=0.6)
shoe_m = make_mat("Sneakers", SHOE_C, rough=0.6)
white_m = make_mat("EyeWhite", (0.96, 0.96, 0.98, 1), rough=0.15)
iris_m = make_mat("Iris", (0.18, 0.38, 0.62, 1), rough=0.1)
brow_m = make_mat("Brows", HAIR_C, rough=0.8)
lip_m = make_mat("Lips", (0.72, 0.38, 0.36, 1), rough=0.35)
silver_m = make_mat("Silver", (0.75, 0.77, 0.82, 1), rough=0.25, metallic=0.9)

# --- body (lofted, symmetric, T-pose) -------------------------------------- #
# z keypoints: ankle .08, knee .50, crotch .90, hip 1.02, waist 1.18,
# chest 1.36, shoulder 1.50, neck 1.55, head centre 1.65
body = loft("Body", [
    (0.86, 0, 0, 0.098, 0.072),   # upper thigh / crotch
    (0.94, 0, 0, 0.155, 0.105),   # hips
    (1.04, 0, 0, 0.165, 0.108),   # seat
    (1.14, 0, 0, 0.128, 0.088),   # waist
    (1.24, 0, 0, 0.138, 0.095),   # lower ribs
    (1.34, 0, 0, 0.148, 0.100),   # bust
    (1.44, 0, 0, 0.135, 0.092),   # upper chest
    (1.50, 0, 0, 0.175, 0.095),   # shoulders
    (1.545, 0, 0, 0.052, 0.048),  # neck
], skin)

# head with tapered jaw
h = sphere("Head", (0, 0, 1.655), (0.082, 0.088, 0.105), skin, seg=32, rings=24)
jaw = sphere("Jaw", (0, 0.012, 1.600), (0.062, 0.066, 0.058), skin, seg=24, rings=16)

# --- face ---------------------------------------------------------------- #
for sx in (-1, 1):
    sphere(f"EyeW{sx}", (0.031 * sx, 0.072, 1.672), (0.0135, 0.008, 0.011), white_m, seg=16, rings=12)
    sphere(f"Iris{sx}", (0.031 * sx, 0.0785, 1.672), (0.0075, 0.004, 0.0085), iris_m, seg=16, rings=12)
    sphere(f"Pupil{sx}", (0.031 * sx, 0.082, 1.672), (0.0032, 0.0025, 0.0040), belt_m, seg=12, rings=8)
    # brow
    b = box(f"Brow{sx}", (0.032 * sx, 0.068, 1.700), (0.020, 0.008, 0.004), brow_m, bevel=0.003)
    b.rotation_euler[2] = -0.12 * sx
    b.rotation_euler[0] = 0.25
# nose
nose = sphere("Nose", (0, 0.086, 1.645), (0.011, 0.014, 0.020), skin, seg=16, rings=12)
# lips
lips = sphere("Lips", (0, 0.070, 1.606), (0.020, 0.007, 0.008), lip_m, seg=16, rings=12)
# ears
for sx in (-1, 1):
    sphere(f"Ear{sx}", (0.080 * sx, 0.005, 1.655), (0.012, 0.018, 0.024), skin, seg=12, rings=8)

# --- necklace -------------------------------------------------------------- #
bpy.ops.mesh.primitive_torus_add(major_radius=0.052, minor_radius=0.0035,
                                 major_segments=24, minor_segments=8,
                                 location=(0, 0.012, 1.545))
necklace = bpy.context.active_object
necklace.name = "Necklace"
necklace.scale = (1.0, 0.55, 1.0)
bpy.ops.object.transform_apply(scale=True)
necklace.data.materials.append(silver_m)
sphere("Pendant", (0, 0.040, 1.512), (0.008, 0.004, 0.010), silver_m, seg=12, rings=8)

# --- arms (stretched horizontally, slight downward slope) ------------------ #
arm_objs = []
for sx in (-1, 1):
    pts = [(0.185 * sx, 0, 1.485), (0.34 * sx, 0, 1.462), (0.50 * sx, 0, 1.445),
           (0.64 * sx, 0, 1.435), (0.735 * sx, 0, 1.432)]
    rad = [0.052, 0.044, 0.038, 0.032, 0.026]
    arm_objs.append(tube(f"Arm{sx}", pts, rad, skin, seg=16))
    # hand
    sphere(f"Hand{sx}", (0.775 * sx, 0, 1.430), (0.026, 0.012, 0.045), skin, seg=16, rings=12)
    # fingers
    for fi, ang in enumerate((-0.42, -0.14, 0.14, 0.42)):
        fx = 0.775 * sx + 0.030 * math.cos(ang) * (1 if sx > 0 else -1) * 0
        tip = Vector((0.80 * sx, 0.014 * math.sin(ang), 1.430 - 0.014 * math.cos(ang) * 0 + 0.010 * fi - 0.012))
        base = Vector((0.772 * sx, 0.004 * math.sin(ang), 1.430 + 0.010 * fi - 0.012))
        tube(f"Finger{sx}_{fi}", [tuple(base), tuple((base + tip) / 2), tuple(tip)],
             [0.0075, 0.0065, 0.0050], skin, seg=10)

# --- legs ------------------------------------------------------------------ #
leg_objs = []
for sx in (-1, 1):
    x = 0.088 * sx
    pts = [(x, 0, 0.90), (x, 0, 0.72), (x, 0, 0.52), (x, 0.004, 0.30),
           (x, 0.008, 0.12), (x, 0.010, 0.045)]
    rad = [0.105, 0.095, 0.082, 0.072, 0.058, 0.038]
    leg_objs.append(tube(f"Leg{sx}", pts, rad, skin, seg=20))

# --- hair: scalp cap + long wavy strands ----------------------------------- #
sphere("Scalp", (0, -0.006, 1.672), (0.090, 0.096, 0.112), hair_m, seg=32, rings=24)
hair_parts = []
for sx in (-1, 1):
    for k in range(4):
        off = (0.052 + 0.018 * k) * sx
        pts = [(off, -0.005, 1.74), (off * 1.20, -0.015, 1.60), (off * 1.30, -0.020, 1.42),
               (off * 1.25, -0.015, 1.26), (off * 1.10, -0.010, 1.14)]
        rad = [0.020, 0.022, 0.020, 0.016, 0.010]
        hair_parts.append(tube(f"Strand{sx}_{k}", pts, rad, hair_m, seg=10))
# centre back hair
for k in range(3):
    z0 = 1.72 - 0.03 * k
    pts = [(0, -0.075 - 0.01 * k, z0), (0.01 * (k - 1), -0.095, 1.55),
           (0, -0.10, 1.35), (-0.01 * (k - 1), -0.095, 1.18)]
    hair_parts.append(tube(f"Back{k}", pts, [0.030, 0.030, 0.024, 0.014], hair_m, seg=10))

# --- camisole top ------------------------------------------------------------ #
top = loft("Camisole", [
    (1.52, 0, 0, 0.158, 0.098),
    (1.46, 0, 0, 0.150, 0.102),
    (1.38, 0, 0, 0.160, 0.110),
    (1.28, 0, 0, 0.150, 0.106),
    (1.18, 0, 0, 0.140, 0.100),
    (1.095, 0, 0, 0.150, 0.106),
], top_m)
# (closed neckline: the camisole loft already covers the chest)
# straps
for sx in (-1, 1):
    tube(f"Strap{sx}", [(0.075 * sx, 0, 1.51), (0.062 * sx, 0.01, 1.545)],
         [0.007, 0.007], top_m, seg=8)

# --- jeans ------------------------------------------------------------------- #
jeans_parts = []
for sx in (-1, 1):
    x = 0.088 * sx
    jeans_parts.append(loft(f"JeanLeg{sx}", [
        (0.90, x, 0, 0.118, 0.100),
        (0.72, x, 0, 0.108, 0.092),
        (0.52, x, 0, 0.094, 0.082),
        (0.30, x, 0.004, 0.084, 0.074),
        (0.12, x, 0.008, 0.070, 0.062),
        (0.055, x, 0.010, 0.052, 0.048),
    ], jean_m, seg=20))
jeans_parts.append(loft("JeanHips", [
    (1.125, 0, 0, 0.182, 0.118),
    (1.02, 0, 0, 0.172, 0.112),
    (0.93, 0, 0, 0.115, 0.085),
], jean_m, seg=20))
# rips at knees (darker inset patches)
rip_m = make_mat("Rip", (0.55, 0.40, 0.30, 1), rough=0.9)
for sx in (-1, 1):
    for z in (0.545, 0.475):
        sphere(f"Rip{sx}_{z}", (0.088 * sx, 0.072, z), (0.028, 0.012, 0.022), rip_m, seg=12, rings=8)
# belt
bpy.ops.mesh.primitive_torus_add(major_radius=0.163, minor_radius=0.016,
                                 major_segments=28, minor_segments=10,
                                 location=(0, 0, 1.095))
belt = bpy.context.active_object
belt.name = "Belt"
belt.scale = (1.0, 0.72, 1.0)
bpy.ops.object.transform_apply(scale=True)
belt.data.materials.append(belt_m)
box("Buckle", (0, 0.118, 1.095), (0.018, 0.008, 0.022), silver_m, bevel=0.004)

# --- sneakers ---------------------------------------------------------------- #
for sx in (-1, 1):
    box(f"Shoe{sx}", (0.088 * sx, 0.035, 0.055), (0.048, 0.105, 0.055), shoe_m, bevel=0.02)
    box(f"Sole{sx}", (0.088 * sx, 0.035, 0.018), (0.050, 0.108, 0.018), white_m, bevel=0.008)

# --- scene: ground, lights, camera ------------------------------------------ #
bpy.ops.mesh.primitive_plane_add(size=6, location=(0, 0, 0))
ground = bpy.context.active_object
ground.name = "Ground"
ground.data.materials.append(make_mat("Ground", (0.82, 0.82, 0.84, 1), rough=0.9))

def add_light(name, kind, loc, energy, color=(1, 1, 1), size=1.0):
    ld = bpy.data.lights.new(name, kind)
    ld.energy = energy
    ld.color = color
    if kind == "AREA":
        ld.shape = "DISK"
        ld.size = size
    ob = bpy.data.objects.new(name, ld)
    bpy.context.collection.objects.link(ob)
    ob.location = loc
    return ob

key = add_light("Key", "AREA", (2.5, 2.0, 3.5), 900, (1.0, 0.95, 0.9), 2.0)
key.rotation_euler = (0.6, 0.0, 0.9)
add_light("Fill", "AREA", (-2.5, 1.5, 2.2), 600, (0.9, 0.95, 1.0), 2.0)
add_light("Rim", "AREA", (0.5, -2.5, 3.0), 1000, (1.0, 1.0, 1.0), 1.5)

cam_data = bpy.data.cameras.new("Cam")
cam = bpy.data.objects.new("Cam", cam_data)
bpy.context.collection.objects.link(cam)
cam.location = (0, 3.4, 1.02)
target = Vector((0, 0, 0.95))
cam.rotation_euler = (target - Vector(cam.location)).to_track_quat("-Z", "Y").to_euler()
cam_data.lens = 55
bpy.context.scene.camera = cam

# --- render + save ------------------------------------------------------------ #
scene = bpy.context.scene
# CYCLES CPU: headless-safe (EEVEE/WORKBENCH need a GL/EGL context)
scene.render.engine = "CYCLES"
scene.cycles.samples = 48
scene.cycles.use_denoising = True
scene.render.resolution_x = 700
scene.render.resolution_y = 1000
scene.render.filepath = os.path.join(OUT_DIR, "reference_preview.png")
scene.world = bpy.data.worlds.new("World")
scene.world.use_nodes = True
scene.world.node_tree.nodes["Background"].inputs[0].default_value = (0.9, 0.9, 0.92, 1)

blend_path = os.path.join(OUT_DIR, "reference_character.blend")
bpy.ops.wm.save_as_mainfile(filepath=blend_path)
print("saved", blend_path)

bpy.ops.render.render(write_still=True)
print("rendered", scene.render.filepath)

try:
    bpy.ops.export_scene.gltf(filepath=os.path.join(OUT_DIR, "reference_character.glb"),
                              export_format="GLB")
    print("exported glb")
except Exception as exc:
    print("glb export skipped:", exc)

print("DONE objects:", len(bpy.data.objects))
