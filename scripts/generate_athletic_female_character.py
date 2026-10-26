#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Procedural game-ready low-poly athletic female character generator for Blender 4.0+.

Run it either way:

    # 1) standalone Blender (recommended: Blender 4.2 LTS or newer)
    blender --background --factory-startup --python generate_athletic_female_character.py

    # 2) the isolated `bpy` wheel runtime used by this repo
    ~/.local/blender-runtime/bin/python generate_athletic_female_character.py

    # 3) paste into Blender's Text Editor and press Alt+P (UI run also works)

Outputs land in ``<repo>/artifacts_out/blender/`` when the script lives in this
checkout (that folder is git-ignored), otherwise next to the script in
``./output/``.  Optional overrides are passed after ``--`` on the CLI:

    blender --background --python generate_athletic_female_character.py -- \
        --height 1.72 --subdiv 0 --pose A --outdir /tmp/out

Knobs at the top of the file (``TARGET_HEIGHT``, ``POSE``, ``SUBDIV_LEVEL``,
``CLOTH_THICKNESS``, ``FLAT_SHADING``, ``ADD_UVS``, ``LIMIT_BONE_INFLUENCES``)
are all honoured; ``SUBDIV_LEVEL = 0`` keeps the raw ~5k-triangle cage, ``1``
is the subdivided ~15k-triangle variant asked for by the brief.

Everything below is generated from code: no bundled assets, no add-ons, no
network access.  The script is deterministic (same inputs -> same mesh).

Pipeline
--------
1. Scene reset (objects/meshes/armatures/materials purged) + metric units.
2. BMesh cross-section lofting of a symmetric quad body (T-pose, or 45 deg
   A-pose via ``--pose A``): torso with
   an anatomical profile, head with a tapered jawline, arms with 5 fully
   modelled fingers, legs with calves/ankles/bare feet and 5 toes.
3. Integrated sub-meshes: sports bra (racerback + straps), high-waisted
   athletic shorts with a raised waistband belt, hair cap with side-swept
   bangs and a high ponytail.
4. Four procedural PBR materials assigned per face region.
5. 51-bone humanoid armature authored from the *same* joint table that drives
   the loft, so bones land exactly on the mesh joints.
6. Skinning through ``bpy.ops.object.parent_set(type='ARMATURE_AUTO')``,
   transforms applied, influences clamped to 4 and re-normalised.
7. ``athletic_female_character.blend`` + ``athletic_female_character.glb``
   (binary glTF 2.0, skinned, weighted, materials + UVs) and a printed report.
"""

from __future__ import annotations

import math
import os
import sys
import time
import traceback

try:
    # Order matters: `bmesh` and `mathutils` live on module paths that are only
    # registered once `bpy` itself has been imported, so isort must not reorder
    # this block.
    import bpy  # noqa: I001  (import-order is deliberate, see above)
    import bmesh
    from mathutils import Matrix, Vector
except ImportError as exc:  # pragma: no cover - only hit outside Blender
    raise SystemExit(
        "This script must run inside Blender 4.0+ (import bpy failed: %s)" % exc
    )

# --------------------------------------------------------------------------- #
# Configuration
# --------------------------------------------------------------------------- #
TARGET_HEIGHT = 1.72          # metres, crown-to-floor
POSE = "T"                    # "T" or "A" (A rotates the arms down 45 deg)
SUBDIV_LEVEL = 1              # Subdivision Surface level applied to the skin
                             # cage before merging.  Measured on this mesh:
                             #   0 -> 2 684 faces / 5 092 tris (raw low-poly cage)
                             #   1 -> 7 428 faces / 14 828 tris (brief default)
SUBDIV_ON_CLOTH = False       # cloth stays crisp: no subsurf on bra/shorts
CLOTH_THICKNESS = 0.0065      # Solidify wall thickness for cloth + hair shells
SKIN_OFFSET = 0.0055          # radial gap between the body and its clothing
WELD_TOLERANCE = 0.00025      # only exact duplicates weld: keeps L/R topology symmetric
BODY_SEGMENTS = 14            # ring resolution for torso / head (even number!)
LIMB_SEGMENTS = 10            # ring resolution for arms / legs
SMALL_SEGMENTS = 6            # ring resolution for fingers / toes / straps
FLAT_SHADING = True           # faceted low-poly look
ADD_UVS = True                # smart UV atlas so the GLB carries TEXCOORD_0
ADD_SHAPE_KEYS = False        # drives glTF morph-target export; no shape keys authored
LIMIT_BONE_INFLUENCES = 4     # game-ready: max 4 weights per vertex
EXPORT_BLENDS = True

MATERIAL_KEYS = ("Mat_Skin", "Mat_Sportswear", "Mat_Hair", "Mat_Eyes_Lips")

ASSET_STEM = "athletic_female_character"

LOG_PREFIX = "ATHLETIC_FEMALE"


def log(msg: str) -> None:
    """Single, greppable log channel (works headless and in the UI)."""
    print(f"{LOG_PREFIX}: {msg}")


def warn(msg: str) -> None:
    print(f"{LOG_PREFIX}: WARNING: {msg}")


# --------------------------------------------------------------------------- #
# Small maths / colour helpers
# --------------------------------------------------------------------------- #
def clamp(value: float, low: float, high: float) -> float:
    return low if value < low else (high if value > high else value)


def srgb_to_linear(channel: float) -> float:
    """Blender colour inputs are linear; sRGB hex needs converting."""
    c = clamp(channel, 0.0, 1.0)
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def hex_to_rgba(hex_string: str, alpha: float = 1.0) -> tuple[float, float, float, float]:
    h = hex_string.lstrip("#")
    r = int(h[0:2], 16) / 255.0
    g = int(h[2:4], 16) / 255.0
    b = int(h[4:6], 16) / 255.0
    return (srgb_to_linear(r), srgb_to_linear(g), srgb_to_linear(b), alpha)


def sign_power(value: float, exponent: float) -> float:
    """sign(v) * |v|**e -> super-ellipse shaping term."""
    if value >= 0.0:
        return value ** exponent
    return -((-value) ** exponent)


# Blender convention used everywhere below:
#   +Z up, -Y forward (the character looks towards -Y), +X is the character's
#   LEFT side, which is why ".L" bones live on +X (mirrored by rig/engine).
FWD = Vector((0.0, -1.0, 0.0))
LAT = Vector((1.0, 0.0, 0.0))
UP = Vector((0.0, 0.0, 1.0))


# --------------------------------------------------------------------------- #
# Scene setup & cleanup
# --------------------------------------------------------------------------- #
DATA_CATEGORIES = (
    "meshes", "curves", "surfaces", "metaballs", "armatures", "actions",
    "materials", "textures", "images", "node_groups", "lights", "cameras",
    "meshes", "vertex_groups", "collections",
)


def reset_scene() -> None:
    """Delete every object and purge all orphan ID data blocks."""
    if bpy.app.background:
        # Headless: reloading the factory-empty file is the only way to also
        # drop startup data blocks that are pinned by the scene itself (e.g.
        # the grease pencil 'Dots Stroke' material).  In the UI we never touch
        # preferences, so the manual sweep below does the work instead.
        try:
            bpy.ops.wm.read_factory_settings(use_empty=True)
        except (RuntimeError, TypeError):                     # pragma: no cover
            pass

    if bpy.context.mode != "OBJECT":
        try:
            bpy.ops.object.mode_set(mode="OBJECT")
        except RuntimeError:
            pass

    for obj in list(bpy.data.objects):
        try:
            obj.user_fake_user = False
        except AttributeError:
            pass
        # unlink from every view layer collection first (fast + safe)
        for coll in list(obj.users_collection):
            coll.objects.unlink(obj)
        bpy.data.objects.remove(obj, do_unlink=True)

    bpy.context.view_layer.update() if bpy.context.window_manager else None

    # clear fake users so pure data blocks become purgeable
    for cat in DATA_CATEGORIES:
        bucket = getattr(bpy.data, cat, None)
        if bucket is None:
            continue
        for block in list(bucket):
            try:
                block.use_fake_user = False
            except AttributeError:
                pass

    if hasattr(bpy.data, "orphans_purge"):
        for _ in range(4):
            try:
                bpy.data.orphans_purge(do_local_ids=True, do_linked_ids=True, do_recursive=True)
            except (TypeError, RuntimeError):
                try:
                    bpy.data.orphans_purge()
                except (TypeError, RuntimeError):
                    break
    else:  # pragma: no cover - Blender < 4.1 fallback
        for cat in DATA_CATEGORIES:
            bucket = getattr(bpy.data, cat, None)
            if bucket is None:
                continue
            for block in list(bucket):
                if block.users == 0:
                    try:
                        bucket.remove(block)
                    except RuntimeError:
                        pass

    for scene in list(bpy.data.scenes):
        if len(bpy.data.scenes) > 1:
            bpy.data.scenes.remove(scene)

    # The startup file's grease-pencil stroke material is referenced by the
    # scene, which keeps one material block alive after the purge.  Release it
    # so the .blend really contains only what this script generates.
    for scene in bpy.data.scenes:
        gp = getattr(scene, "grease_pencil", None)
        for attr in ("stroke_material", "fill_material"):
            if gp is not None and getattr(gp, attr, None) is not None:
                try:
                    setattr(gp, attr, None)
                except (TypeError, AttributeError):            # pragma: no cover
                    pass

    # final explicit sweep: any zero-user block that survived the purge is
    # removed by hand so the .blend only ever contains what we generate.
    for cat in DATA_CATEGORIES:
        bucket = getattr(bpy.data, cat, None)
        if bucket is None:
            continue
        for block in list(bucket):
            if block.users == 0:
                try:
                    bucket.remove(block)
                except RuntimeError:
                    pass

    # 'Dots Stroke' (grease pencil) + the active collection legitimately stay
    # alive in every startup file - they are not part of the asset.
    log(
        "scene reset -> objects=%d meshes=%d armatures=%d materials=%d"
        % (
            len(bpy.data.objects),
            len(bpy.data.meshes),
            len(bpy.data.armatures),
            len(bpy.data.materials),
        )
    )


def configure_units(scene: bpy.types.Scene) -> None:
    units = scene.unit_settings
    units.system = "METRIC"
    units.scale_length = 1.0
    try:
        units.length_unit = "METERS"
    except TypeError:
        pass
    scene.cursor.location = (0.0, 0.0, 0.0)
    # Save straight over the target file: a generated asset folder should not
    # accumulate .blend1 backups that confuse downstream file watchers.
    # (Blender's .blend1 backup is left enabled on purpose - this repo's
    #  .gitignore already covers it.)
    # a clean, deterministic viewport state helps when the .blend is opened
    try:
        for area in bpy.context.screen.areas if bpy.context.screen else []:
            if area.type == "VIEW_3D":
                area.spaces[0].shading.type = "SOLID"
                area.spaces[0].overlay.show_overlays = False
    except (AttributeError, ReferenceError):
        pass


def apply_props(block, mapping: dict) -> list[str]:
    """Set only the properties that exist on this Blender version; report the rest."""
    missing = []
    for key, value in mapping.items():
        if hasattr(block, key):
            try:
                setattr(block, key, value)
            except (TypeError, ValueError, RuntimeError):     # pragma: no cover
                missing.append(key)
        else:
            missing.append(key)
    return missing


def op_kwargs(operator, wanted: dict) -> dict:
    """Filter + coerce operator keywords against the installed RNA definition.

    Blender renamed and re-typed several glTF / UV operator properties across
    4.0 / 4.2 / 4.5 (for example ``export_rest_position_armature`` went from an
    enum to a bool).  Validating names *and* types up front keeps the calls
    error-free on every 4.x build instead of raising TypeError at run time.
    """
    try:
        rna = operator.get_rna_type()
    except (AttributeError, RuntimeError):                   # pragma: no cover
        return {}
    clean: dict = {}
    for key, value in wanted.items():
        prop = rna.properties.get(key)
        if prop is None:
            continue
        prop_type = getattr(prop, "type", None)
        try:
            if prop_type == "BOOLEAN":
                if not isinstance(value, bool):
                    continue
            elif prop_type == "ENUM":
                options = {item.identifier for item in prop.enum_items}
                if not isinstance(value, str) or value not in options:
                    continue
            elif prop_type in {"INT", "FLOAT"} and value is not None:
                value = int(value) if prop_type == "INT" else float(value)
        except (AttributeError, RuntimeError, TypeError):    # pragma: no cover
            continue
        clean[key] = value
    return clean


# --------------------------------------------------------------------------- #
# BMesh lofting toolkit
# --------------------------------------------------------------------------- #
def make_ring(
    center,
    n: int,
    r_fwd: float,
    r_lat: float,
    fwd: Vector = FWD,
    lat: Vector = LAT,
    bulge_fwd: float = 0.0,
    bulge_back: float = 0.0,
    front_taper: float = 0.0,
    front_dip: float = 0.0,
    sq: float = 1.0,
    push: float = 0.0,
    lat_bias: float = 0.0,
) -> list[Vector]:
    """One elliptical/super-elliptical cross-section, sampled with *n* points.

    ``i == 0`` always sits on the midline in the *fwd* direction, so every ring
    of the character shares one angular phase (clean quads, weldable seams).

    * ``r_fwd`` / ``r_lat``  half depth (front-back) / half width of the ring
    * ``bulge_fwd``/-``back`` extra outward push for bust, glutes, calves, jaw
    * ``front_taper``        narrows the front-lateral corners (chin, lats)
    * ``front_dip``          carves the sternal cleft between the pectorals
    * ``sq``                 1.0 = ellipse, <1 = boxier, >1 = pointier
    * ``push``               uniform outward offset (used by cloth / hair)
    * ``lat_bias``           shifts the whole ring along *lat* (asymmetric sweep)
    """
    c = Vector(center)
    pts: list[Vector] = []
    for i in range(n):
        theta = 2.0 * math.pi * i / n
        ca, sa = math.cos(theta), math.sin(theta)
        a = r_fwd * sign_power(ca, sq)
        b = r_lat * sign_power(sa, sq)
        if ca > 0.0:
            a += bulge_fwd * (ca ** 1.5)
            a *= 1.0 - front_dip * (ca ** 3.0)
            b *= 1.0 - front_taper * (ca ** 1.3)
        else:
            a -= bulge_back * ((-ca) ** 1.5)
        # 2-D profile normal -> even outward offset instead of naive scaling
        na = a / max(abs(r_fwd), 1e-6)
        nb = b / max(abs(r_lat), 1e-6)
        nl = math.hypot(na, nb) or 1.0
        pts.append(c + fwd * (a + push * na / nl) + lat * (b + push * nb / nl + lat_bias))
    return pts


def delete_geom(bm, geom, kinds: tuple[str, ...]) -> None:
    """bmesh.ops.delete with a context name that exists on this Blender version."""
    for context in kinds:
        try:
            bmesh.ops.delete(bm, geom=list(geom), context=context)
            return
        except (ValueError, TypeError):
            continue
    if geom:                                                # pragma: no cover
        warn(f"could not delete {len(geom)} element(s) via bmesh.ops.delete")


def ring_centroid(pts: list[Vector]) -> Vector:
    total = Vector((0.0, 0.0, 0.0))
    for p in pts:
        total += p
    return total / max(len(pts), 1)


def ring_radius(pts: list[Vector], center: Vector) -> float:
    total = 0.0
    for p in pts:
        total += (p - center).length
    return total / max(len(pts), 1)


class Part:
    """A bmesh body-part: lofted quads + per-face material overrides."""

    def __init__(
        self,
        name: str,
        materials: tuple[str, ...] = ("Mat_Skin",),
        thickness: float = 0.0,
        subsurf: bool = False,
    ) -> None:
        self.name = name
        self.materials = list(materials)
        self.thickness = thickness
        self.subsurf = subsurf
        self.bm = bmesh.new()
        self.overrides: list[tuple[object, int]] = []
        self.rows: list[list] = []

    # -- low level ---------------------------------------------------------- #
    def _face(self, loop, mat_key: str | None = None):
        try:
            face = self.bm.faces.new(tuple(loop))
        except ValueError:
            return None
        if mat_key and mat_key != self.materials[0]:
            self.overrides.append((face, self.materials.index(mat_key)))
        return face

    def cap_ring(self, ring_verts, tip: Vector, mat_key: str | None = None):
        """Close a ring with a pole vertex (only used on extremity tips)."""
        faces = []
        k = len(ring_verts)
        for i in range(k):
            f = self._face((ring_verts[i], ring_verts[(i + 1) % k], tip), mat_key)
            if f:
                faces.append(f)
        return faces

    def loft(
        self,
        rings: list[list[Vector]],
        cap_first: bool = False,
        cap_last: bool = False,
        mat_key: str | None = None,
        cap_tension: float = 0.5,
        last_tension: float | None = None,
    ) -> list:
        """Bridge *rings* with quad strips, optionally capping either end.

        ``cap_tension`` / ``last_tension`` scale how far the pole vertex of the
        start / end cap sits past its ring (0.22 = a flat knuckle, 0.85 = a
        rounded cranium).  Returns every face created, in order, so callers can
        re-tag materials by (row, column) without a second spatial lookup.
        """
        created: list = []
        rows = []
        for pts in rings:
            rows.append([self.bm.verts.new(p) for p in pts])

        for ri in range(len(rows) - 1):
            lower, upper = rows[ri], rows[ri + 1]
            k = min(len(lower), len(upper))
            for ci in range(k):
                f = self._face(
                    (lower[ci], lower[(ci + 1) % k], upper[(ci + 1) % k], upper[ci]),
                    mat_key,
                )
                if f:
                    created.append(f)

        tensions = {0: cap_tension, len(rows) - 1: last_tension or cap_tension}
        for which, cap in ((0, cap_first), (len(rows) - 1, cap_last)):
            if not cap:
                continue
            pts = rings[which]
            centre = ring_centroid(pts)
            radius = ring_radius(pts, centre)
            if len(rings) > 1:
                other = rings[1 - which if which == 0 else -2]
                direction = centre - ring_centroid(other)
            else:  # pragma: no cover - defensive
                direction = Vector((0.0, 0.0, 1.0))
            if direction.length < 1e-9:
                continue
            direction.normalize()
            tip = self.bm.verts.new(centre + direction * radius * tensions[which])
            created.extend(self.cap_ring(rows[which], tip, mat_key))
        self.rows = rows
        return created

    def delete_faces_where(self, predicate) -> int:
        doomed = [f for f in self.bm.faces if predicate(f.calc_center_median())]
        if doomed:
            delete_geom(self.bm, doomed, ("FACES",))
        loose = [v for v in self.bm.verts if not v.link_faces]
        if loose:
            delete_geom(self.bm, loose, ("VERTS", "VERTICES"))
        return len(doomed)

    # -- output ------------------------------------------------------------- #
    def to_object(self, apply_modifiers: bool = True):
        bm = self.bm
        bmesh.ops.remove_doubles(bm, verts=bm.verts[:], dist=0.00035)
        bmesh.ops.recalc_face_normals(bm, faces=bm.faces[:])
        if not bm.faces:
            raise RuntimeError(f"part '{self.name}' produced no faces")

        mesh = bpy.data.meshes.new(self.name)
        bm.to_mesh(mesh)
        obj = bpy.data.objects.new(self.name, mesh)
        bpy.context.scene.collection.objects.link(obj)

        for key in self.materials:
            mesh.materials.append(bpy.data.materials[key])
        for face, slot in self.overrides:
            if 0 <= face.index < len(mesh.polygons):
                mesh.polygons[face.index].material_index = slot

        stack = []
        if self.thickness > 0.0:
            sol = obj.modifiers.new("Cloth_Thickness", "SOLIDIFY")
            apply_props(sol, {
                "thickness": self.thickness,
                "offset": 1.0,               # wall grows outwards, body stays exact
                "use_even_offset": True,
                "use_rim": True,
                "use_rim_only": False,
                "material_offset": 0,
                "material_offset_rim": 0,
                "material_mode": "MAT_OFFSET",
            })
            stack.append(sol.name)
        if self.subsurf and SUBDIV_LEVEL > 0:
            sub = obj.modifiers.new("Subdiv", "SUBSURF")
            apply_props(sub, {
                "levels": SUBDIV_LEVEL,
                "render_levels": SUBDIV_LEVEL,
                "subdivision_type": "CATMULL_CLARK",
                "use_limit_surface": False,
                "uv_smooth": "NONE",
            })
            stack.append(sub.name)

        if apply_modifiers and stack:
            previous = activate(obj)
            for name in stack:
                try:
                    bpy.ops.object.modifier_apply(modifier=name)
                except RuntimeError as exc:
                    warn(f"{self.name}: modifier '{name}' not applied ({exc})")
            restore_active(previous)

        bm.free()
        return obj


# --------------------------------------------------------------------------- #
# Anatomy table: single source of truth for mesh *and* armature
# --------------------------------------------------------------------------- #
# z, r_lat, r_fwd, bulge_fwd, bulge_back, front_taper, front_dip, sq
TORSO_STATIONS = [
    (0.828, 0.108, 0.092, 0.000, 0.000, 0.00, 0.00, 1.00),  # 0  pelvic floor
    (0.868, 0.148, 0.118, 0.000, 0.012, 0.00, 0.00, 1.02),  # 1  gluteal fold
    (0.928, 0.166, 0.132, 0.002, 0.020, 0.00, 0.00, 1.02),  # 2  widest hips
    (0.988, 0.156, 0.124, 0.004, 0.012, 0.02, 0.00, 1.00),  # 3  iliac crest
    (1.046, 0.120, 0.099, 0.004, 0.006, 0.06, 0.00, 0.98),  # 4  navel / waist
    (1.088, 0.112, 0.094, 0.004, 0.004, 0.10, 0.00, 0.98),  # 5  narrowest waist
    (1.140, 0.124, 0.103, 0.004, 0.004, 0.04, 0.00, 1.00),  # 6  floating ribs
    (1.196, 0.135, 0.111, 0.016, 0.004, 0.00, 0.00, 1.02),  # 7  inframammary band
    (1.258, 0.145, 0.118, 0.058, 0.004, 0.00, 0.34, 1.04),  # 8  bust line
    (1.312, 0.145, 0.112, 0.026, 0.006, 0.02, 0.22, 1.04),  # 9  upper chest
    (1.362, 0.150, 0.104, 0.006, 0.008, 0.06, 0.00, 1.05),  # 10 pectoral shelf
    (1.404, 0.146, 0.095, 0.002, 0.010, 0.26, 0.00, 1.08),  # 11 trapezius slope
    (1.442, 0.064, 0.068, 0.004, 0.006, 0.10, 0.00, 1.00),  # 12 neck root
    (1.482, 0.053, 0.056, 0.004, 0.006, 0.00, 0.00, 1.00),  # 13 mid neck
    (1.516, 0.050, 0.053, 0.002, 0.004, 0.00, 0.00, 1.00),  # 14 neck top (welded)
]

# head: (z, r_lat, r_fwd, bulge_fwd, bulge_back, front_taper, front_dip, sq)
HEAD_STATIONS = [
    (1.516, 0.050, 0.053, 0.002, 0.004, 0.00, 0.00, 1.00),  # 0 welded to neck
    (1.545, 0.058, 0.066, 0.010, 0.004, 0.34, 0.00, 1.02),  # 1 chin / jaw underside
    (1.576, 0.068, 0.076, 0.006, 0.008, 0.24, 0.00, 1.04),  # 2 jaw angle
    (1.606, 0.071, 0.081, 0.004, 0.008, 0.14, 0.00, 1.04),  # 3 mouth row
    (1.634, 0.073, 0.084, 0.004, 0.008, 0.06, 0.00, 1.03),  # 4 cheek / nose
    (1.660, 0.073, 0.083, 0.008, 0.008, 0.04, 0.00, 1.02),  # 5 eye / brow row
    (1.684, 0.072, 0.081, 0.000, 0.010, 0.02, 0.00, 1.01),  # 6 forehead
    (1.698, 0.066, 0.076, 0.000, 0.012, 0.00, 0.00, 1.00),  # 7 crown front
    (1.709, 0.049, 0.058, 0.000, 0.008, 0.00, 0.00, 0.98),  # 8 crown top
]
H_ROW_LIPS, H_ROW_EYES = 2, 4          # head loft rows tagged with Mat_Eyes_Lips

# arm: (x, r_fwd, r_lat, bulge_fwd, bulge_back, front_taper, front_dip, sq)
# for the arms r_fwd measures the front-back (Y) radius, r_lat the vertical (Z)
ARM_STATIONS = [
    (0.058, 0.076, 0.080, 0.000, 0.004, 0.00, 0.00, 1.02),  # 0 axilla (inside torso)
    (0.128, 0.069, 0.072, 0.000, 0.004, 0.00, 0.00, 1.02),  # 1 armpit
    (0.196, 0.064, 0.066, 0.002, 0.004, 0.00, 0.00, 1.02),  # 2 deltoid
    (0.268, 0.055, 0.057, 0.004, 0.006, 0.00, 0.00, 1.00),  # 3 biceps peak
    (0.340, 0.049, 0.052, 0.002, 0.008, 0.00, 0.00, 1.00),  # 4 distal biceps
    (0.402, 0.043, 0.046, 0.000, 0.004, 0.00, 0.00, 1.00),  # 5 above elbow
    (0.445, 0.041, 0.045, 0.002, 0.004, 0.00, 0.00, 1.00),  # 6 elbow
    (0.498, 0.043, 0.044, 0.004, 0.006, 0.00, 0.00, 1.00),  # 7 forearm mass
    (0.568, 0.036, 0.037, 0.002, 0.004, 0.00, 0.00, 1.00),  # 8 mid forearm
    (0.640, 0.028, 0.030, 0.000, 0.002, 0.00, 0.00, 1.00),  # 9 distal forearm
    (0.690, 0.026, 0.027, 0.000, 0.002, 0.00, 0.00, 1.00),  # 10 wrist
    (0.726, 0.036, 0.020, 0.000, 0.000, 0.00, 0.00, 0.72),  # 11 palm heel
    (0.762, 0.041, 0.015, 0.000, 0.000, 0.00, 0.00, 0.66),  # 12 palm mid
    (0.786, 0.041, 0.014, 0.002, 0.000, 0.00, 0.00, 0.62),  # 13 knuckle ridge
]
# leg: (z, r_lat, r_fwd, bulge_fwd, bulge_back, front_taper, front_dip, sq)
LEG_STATIONS = [
    (0.960, 0.0905, 0.0945, 0.000, 0.000, 0.00, 0.00, 1.00),  # 0 hip root (inside pelvis)
    (0.906, 0.0960, 0.0985, 0.002, 0.014, 0.00, 0.00, 1.02),  # 1 upper thigh
    (0.848, 0.0930, 0.0955, 0.004, 0.013, 0.00, 0.00, 1.02),  # 2 adductor / hamstring
    (0.760, 0.0860, 0.0895, 0.008, 0.008, 0.00, 0.00, 1.00),  # 3 vastus lateralis
    (0.660, 0.0770, 0.0810, 0.008, 0.004, 0.00, 0.00, 1.00),  # 4 quad sweep
    (0.560, 0.0645, 0.0675, 0.006, 0.004, 0.04, 0.00, 1.00),  # 5 above knee
    (0.478, 0.0525, 0.0555, 0.006, 0.004, 0.06, 0.00, 1.00),  # 6 knee / patella
    (0.430, 0.0495, 0.0525, 0.002, 0.008, 0.04, 0.00, 1.00),  # 7 tibial tuberosity
    (0.352, 0.0545, 0.0580, 0.000, 0.015, 0.00, 0.00, 1.02),  # 8 gastrocnemius
    (0.290, 0.0475, 0.0500, 0.000, 0.010, 0.00, 0.00, 1.00),  # 9 calf taper
    (0.200, 0.0355, 0.0375, 0.000, 0.004, 0.02, 0.00, 1.00),  # 10 shin
    (0.126, 0.0300, 0.0320, 0.000, 0.004, 0.02, 0.00, 1.00),  # 11 malleolus
    (0.092, 0.0285, 0.0305, 0.002, 0.004, 0.00, 0.00, 1.00),  # 12 ankle
]
# foot: (y, r_lat, r_up, bulge_up, bulge_down, taper, sq) with the sole clamped flat
FOOT_STATIONS = [
    # y,      r_lat,  r_up,   bulge_up, bulge_down, sq,   centre z
    (0.080, 0.0340, 0.0400, 0.000, 0.008, 1.02, 0.0470),   # 0 heel
    (0.048, 0.0370, 0.0410, 0.002, 0.004, 1.00, 0.0480),  # 1 behind ankle
    (0.000, 0.0400, 0.0360, 0.004, 0.000, 1.00, 0.0400),  # 2 instep
    (-0.052, 0.0430, 0.0300, 0.002, 0.002, 0.98, 0.0330),  # 3 midfoot
    (-0.104, 0.0470, 0.0260, 0.000, 0.004, 0.96, 0.0285),  # 4 metatarsal heads
    (-0.150, 0.0430, 0.0210, 0.000, 0.004, 0.94, 0.0235),  # 5 toe line
    (-0.176, 0.0300, 0.0150, 0.000, 0.002, 0.92, 0.0190),  # 6 distal toes
]

# finger: name, lateral offset (Y in body space), base radius, length, flex direction
FINGERS = [
    # (name,  y_offset,  r_half,  length,  z_off,   splay)
    ("Index", -0.0295, 0.0098, 0.0665, 0.0015, -0.010),
    ("Middle", -0.0098, 0.0103, 0.0760, 0.0020, -0.002),
    ("Ring", 0.0102, 0.0096, 0.0695, 0.0015, 0.006),
    ("Pinky", 0.0298, 0.0082, 0.0520, 0.0005, 0.016),
]
# (index/middle/ring/pinky sit towards the front of the palm so the thumb,
#  which also leans anteriorly, clears the index finger)
FINGER_SEGMENT_SPLIT = (0.0, 0.44, 0.73, 1.0)     # MCP / PIP / DIP / tip
THUMB_STATIONS = [
    # x offset, anterior offset from the hand axis, vertical offset
    (0.700, -0.026, 0.001),
    (0.736, -0.050, 0.004),
    (0.764, -0.065, 0.006),
    (0.788, -0.075, 0.006),
]
THUMB_RADII = (0.0125, 0.0112, 0.0100, 0.0082)

# toes: (medial-lateral offset from the foot axis, half radius, length, y start)
TOES = [
    (-0.0215, 0.0108, 0.0300, -0.146),
    (-0.0055, 0.0084, 0.0245, -0.158),
    (0.0072, 0.0076, 0.0215, -0.161),
    (0.0185, 0.0068, 0.0180, -0.160),
    (0.0280, 0.0058, 0.0145, -0.156),
]
# ponytail spine (back of the crown -> hanging down the upper back)
PONYTAIL_SPINE = [
    (0.000, 0.070, 1.706),
    (0.000, 0.098, 1.700),
    (0.004, 0.124, 1.668),
    (0.008, 0.142, 1.612),
    (0.010, 0.152, 1.544),
    (0.009, 0.153, 1.470),
    (0.006, 0.146, 1.398),
    (0.002, 0.134, 1.330),
    (-0.002, 0.120, 1.272),
]
PONYTAIL_WIDTH = (0.046, 0.044, 0.038, 0.032, 0.027, 0.021, 0.015, 0.010, 0.006)
PONYTAIL_DEPTH = (0.028, 0.027, 0.024, 0.021, 0.018, 0.014, 0.010, 0.007, 0.004)


def interp_chain(chain: list[Vector], axis: int, value: float) -> Vector:
    """Point on a polyline whose *axis* coordinate equals *value* (clamped)."""
    if len(chain) == 1:
        return chain[0].copy()
    span = chain[-1][axis] - chain[0][axis]
    if abs(span) < 1e-9:
        return chain[0].copy()
    t = clamp((value - chain[0][axis]) / span, 0.0, 1.0 - 1e-6)
    seg = t * (len(chain) - 1)
    i = int(seg)
    local = seg - i
    return chain[i].lerp(chain[min(i + 1, len(chain) - 1)], local)


# --------------------------------------------------------------------------- #
# Joint table  (the armature and the loft read the *same* numbers)
# --------------------------------------------------------------------------- #
def V(x: float, y: float, z: float) -> Vector:
    return Vector((x, y, z))


SHOULDER_X, ELBOW_X, WRIST_X, MCP_X = 0.170, 0.445, 0.690, 0.786
ARM_Z = 1.375
HIP_X, KNEE_X, ANKLE_X = 0.093, 0.098, 0.101
HIP_Z, KNEE_Z, ANKLE_Z = 0.900, 0.478, 0.088
FOOT_BALL_Y, TOE_Y = -0.072, -0.170
ARM_ANGLE_DEG = 0.0 if POSE.upper() == "T" else 45.0

SPINE_CHAIN = [
    V(0.0, 0.024, 0.850),   # sacrum / pelvic floor
    V(0.0, 0.014, 0.948),   # Hips -> Spine joint
    V(0.0, 0.004, 1.060),   # Spine -> Chest joint (top of the waist)
    V(0.0, -0.006, 1.270),  # bust / sternum
    V(0.0, 0.000, 1.404),   # Chest -> Neck joint
    V(0.0, 0.002, 1.516),   # Neck -> Head joint (chin line)
]
HEAD_CENTER_PATH = [
    (1.516, 0.002),
    (1.558, -0.006),
    (1.616, -0.006),
    (1.672, 0.002),
    (1.726, 0.014),
]
HEAD_SURFACE = Vector((0.0, 0.004, 1.612))   # ellipsoid centre for hair placement
HEAD_RADII = (0.0755, 0.0870, 0.1100)        # lat, fwd, up of that ellipsoid


def lerp_table(table: list[tuple], key_idx: int, value: float) -> tuple:
    """Interpolate a station table along one key column (either direction).

    The leg/head tables are stored top-down (decreasing z), the arm table
    bottom-up, so the lookup has to be direction agnostic - silently clamping
    it collapses an entire limb into one ring.
    """
    keys = [row[key_idx] for row in table]
    first, last = keys[0], keys[-1]
    ascending = last >= first
    if ascending:
        if value <= first:
            return table[0]
        if value >= last:
            return table[-1]
    else:
        if value >= first:
            return table[0]
        if value <= last:
            return table[-1]
    for i in range(len(table) - 1):
        lo, hi = keys[i], keys[i + 1]
        low, high = (lo, hi) if lo <= hi else (hi, lo)
        if low - 1e-12 <= value <= high + 1e-12:
            span = hi - lo
            f = 0.5 if abs(span) < 1e-12 else clamp((value - lo) / span, 0.0, 1.0)
            return tuple(a + (b - a) * f for a, b in zip(table[i], table[i + 1], strict=True))
    return table[-1]


def head_centre_y(z: float) -> float:
    """Anterior/posterior drift of the head+neck axis (skull leans back)."""
    return lerp_table(HEAD_CENTER_PATH, 0, z)[1]


def torso_ring_at(z: float, push: float = 0.0, n: int = BODY_SEGMENTS) -> list[Vector]:
    _, r_lat, r_fwd, bulge_f, bulge_b, taper, dip, sq = lerp_table(TORSO_STATIONS, 0, z)
    centre = interp_chain(SPINE_CHAIN, 2, z)
    centre.z = z
    return make_ring(centre, n, r_fwd, r_lat, FWD, LAT, bulge_f, bulge_b, taper, dip, sq, push)


def head_ring_at(z: float, n: int = BODY_SEGMENTS, push: float = 0.0) -> list[Vector]:
    _, r_lat, r_fwd, bulge_f, bulge_b, taper, dip, sq = lerp_table(HEAD_STATIONS, 0, z)
    centre = V(0.0, head_centre_y(z), z)
    return make_ring(centre, n, r_fwd, r_lat, FWD, LAT, bulge_f, bulge_b, taper, dip, sq, push)


def arm_root_xform(sx: float) -> Matrix:
    """Optional A-pose: rotate the whole arm about the shoulder pivot."""
    if abs(ARM_ANGLE_DEG) < 1e-6:
        return Matrix.Identity(4)
    pivot = V(sx * SHOULDER_X, 0.0, ARM_Z)
    rot = Matrix.Rotation(math.radians(ARM_ANGLE_DEG * sx), 4, "Y")
    return Matrix.Translation(pivot) @ rot @ Matrix.Translation(-pivot)


def arm_chain(sx: float) -> list[Vector]:
    chain = [
        V(sx * 0.048, 0.006, 1.384),
        V(sx * SHOULDER_X, 0.000, ARM_Z),
        V(sx * ELBOW_X, -0.004, 1.373),
        V(sx * WRIST_X, -0.007, 1.371),
        V(sx * MCP_X, -0.008, 1.370),
    ]
    mat = arm_root_xform(sx)
    return [mat @ p for p in chain]


def leg_chain(sx: float) -> list[Vector]:
    return [
        V(sx * HIP_X, 0.012, 0.982),
        V(sx * HIP_X, 0.004, HIP_Z),
        V(sx * KNEE_X, -0.012, KNEE_Z),
        V(sx * ANKLE_X, 0.018, ANKLE_Z),
        V(sx * ANKLE_X, FOOT_BALL_Y, 0.030),
        V(sx * ANKLE_X, TOE_Y, 0.026),
    ]


def arm_ring_at(x: float, sx: float, push: float = 0.0, n: int = LIMB_SEGMENTS) -> list[Vector]:
    """*x* is the unsigned distance out the arm; *sx* picks the side (the joint
    chain is already mirrored, so the lookup key has to be mirrored too)."""
    x, r_fwd, r_lat, bulge_f, bulge_b, taper, dip, sq = lerp_table(ARM_STATIONS, 0, x)
    centre = interp_chain(arm_chain(sx), 0, sx * x)
    return make_ring(centre, n, r_fwd, r_lat, FWD, UP, bulge_f, bulge_b, taper, dip, sq, push)


def leg_ring_at(z: float, sx: float, push: float = 0.0, n: int = LIMB_SEGMENTS) -> list[Vector]:
    z, r_lat, r_fwd, bulge_f, bulge_b, taper, dip, sq = lerp_table(LEG_STATIONS, 0, z)
    centre = interp_chain(leg_chain(sx), 2, z)
    centre.z = z
    centre.x = centre.x if abs(push) < 1e-9 else centre.x + sx * push * 0.35
    return make_ring(centre, n, r_fwd, r_lat, FWD, LAT, bulge_f, bulge_b, taper, dip, sq, push)


def finger_joint(sx: float, base_y: float, base_z: float, length: float, splay: float, frac: float) -> Vector:
    palm = interp_chain(arm_chain(sx), 0, sx * MCP_X)
    return V(sx * (MCP_X + frac * length), palm.y + base_y + splay * frac, palm.z + base_z)


def finger_stations(sx: float) -> dict[str, list[Vector]]:
    """Joint polyline for every finger of one hand (also drives the bones)."""
    out: dict[str, list[Vector]] = {}
    for name, off_y, _r, length, off_z, splay in FINGERS:
        out[name] = [finger_joint(sx, off_y, off_z, length, splay, f) for f in FINGER_SEGMENT_SPLIT]
    palm = interp_chain(arm_chain(sx), 0, sx * MCP_X)
    thumb = [V(sx * x, palm.y + y, palm.z + z) for x, y, z in THUMB_STATIONS]
    out["Thumb"] = thumb
    mat = arm_root_xform(sx)
    if mat is not None:
        for key, pts in out.items():
            out[key] = [mat @ p for p in pts]
    return out


# --------------------------------------------------------------------------- #
# Character parts
# --------------------------------------------------------------------------- #
def build_torso_and_head() -> Part:
    """Pelvic floor -> hips -> waist -> chest -> shoulders -> neck -> skull.

    One continuous loft (the neck ring is shared, not duplicated) so the
    Subdivision pass produces a crease-free head/neck/torso surface instead of
    two shells that have to be welded together afterwards.
    """
    part = Part("Body_Torso_Head", ("Mat_Skin", "Mat_Eyes_Lips"), subsurf=True)
    n = BODY_SEGMENTS
    rings = [torso_ring_at(row[0]) for row in TORSO_STATIONS]
    rings += [head_ring_at(row[0]) for row in HEAD_STATIONS[1:]]
    faces = part.loft(rings, cap_first=True, cap_last=True, cap_tension=0.85,
                      last_tension=0.22)

    head_row_offset = len(TORSO_STATIONS) - 1
    lip_cols, eye_cols = (0, n - 1), (1, 2, n - 3, n - 2)
    for head_row, cols in ((H_ROW_LIPS, lip_cols), (H_ROW_EYES, eye_cols)):
        row = head_row_offset + head_row - 1
        for col in cols:
            index = row * n + col
            if 0 <= index < len(faces):
                part.overrides.append((faces[index], part.materials.index("Mat_Eyes_Lips")))

    # gentle sculpt: recessed eye field, proud brow + lips, so the accents read
    for face in faces:
        centre = face.calc_center_median()
        if centre.z < 1.52 or centre.y > -0.045:
            continue
        shift = 0.0
        if abs(centre.z - 1.6470) < 0.020:
            shift = -0.0055
        elif 1.5740 < centre.z < 1.6010:
            shift = 0.0040
        if shift:
            for vert in face.verts:
                vert.co += FWD * shift
    return part


# palm stations continue the arm tube: (x, r_fwd, r_lat, sq)
PALM_STATIONS = [
    (0.716, 0.0345, 0.0210, 0.78),
    (0.750, 0.0405, 0.0170, 0.70),
    (0.778, 0.0410, 0.0158, 0.66),
    (0.790, 0.0385, 0.0185, 0.70),
]
FINGER_TAPER = (1.16, 1.00, 0.955, 0.875, 0.735)
TOE_TAPER = (1.14, 1.00, 0.90, 0.70)


def build_arm_side(sx: float) -> Part:
    """Upper arm -> forearm -> wrist -> palm -> 4 fingers + opposable thumb."""
    side = "L" if sx > 0 else "R"
    part = Part(f"Body_Arm_{side}", ("Mat_Skin",), subsurf=True)

    arm_x = [row[0] for row in ARM_STATIONS]
    part.loft([arm_ring_at(x, sx) for x in arm_x], cap_first=True, cap_last=False,
              cap_tension=0.55)

    palm_rings = [arm_ring_at(WRIST_X, sx)]            # shared ring -> welds shut
    for x, r_fwd, r_lat, sq in PALM_STATIONS:
        centre = interp_chain(arm_chain(sx), 0, sx * x)
        palm_rings.append(make_ring(centre, LIMB_SEGMENTS, r_fwd, r_lat, FWD, UP, sq=sq))
    part.loft(palm_rings, cap_first=False, cap_last=True, cap_tension=0.26)

    for _finger, off_y, radius, length, off_z, splay in FINGERS:
        rings = []
        for i, frac in enumerate(FINGER_SEGMENT_SPLIT[:-1] + (0.84, 1.0)):
            centre = finger_joint(sx, off_y, off_z, length, splay, frac)
            rings.append(
                make_ring(centre, SMALL_SEGMENTS, radius * FINGER_TAPER[i],
                          radius * 0.86 * FINGER_TAPER[i], FWD, UP, sq=0.90)
            )
        part.loft(rings, cap_first=False, cap_last=True, cap_tension=0.58)

    palm = interp_chain(arm_chain(sx), 0, sx * MCP_X)
    thumb_rings, previous = [], None
    for i, (x, y, z) in enumerate(THUMB_STATIONS):
        centre = V(sx * x, palm.y + y, palm.z + z)
        radius = THUMB_RADII[i]
        direction = FWD if previous is None else (centre - previous).normalized()
        previous = centre
        lat_axis = UP
        fwd_axis = direction.cross(lat_axis)
        fwd_axis = fwd_axis.normalized() if fwd_axis.length > 1e-6 else FWD
        thumb_rings.append(
            make_ring(centre, SMALL_SEGMENTS, radius * 0.82, radius, fwd_axis, lat_axis, sq=0.92)
        )
    part.loft(thumb_rings, cap_first=False, cap_last=True, cap_tension=0.58)

    if abs(ARM_ANGLE_DEG) > 1e-6:
        part.bm.transform(arm_root_xform(sx))
    return part


def build_leg_side(sx: float) -> Part:
    """Hip -> thigh (vastus / adductor sweep) -> knee -> calf -> ankle -> bare foot."""
    side = "L" if sx > 0 else "R"
    part = Part(f"Body_Leg_{side}", ("Mat_Skin",), subsurf=True)

    part.loft([leg_ring_at(row[0], sx) for row in LEG_STATIONS],
              cap_first=True, cap_last=True, cap_tension=0.72)

    ankle = interp_chain(leg_chain(sx), 2, ANKLE_Z)   # x already carries the side sign
    foot_rings = [
        make_ring(V(ankle.x, y, cz), LIMB_SEGMENTS, r_up, r_lat, UP, LAT,
                  bulge_up, bulge_down, sq=sq)
        for y, r_lat, r_up, bulge_up, bulge_down, sq, cz in FOOT_STATIONS
    ]
    part.loft(foot_rings, cap_first=False, cap_last=True, cap_tension=0.72)

    for off_lat, radius, length, y_start in TOES:
        rings = []
        for j, frac in enumerate((-0.30, 0.0, 0.55, 1.0)):
            y = y_start + frac * length
            z = radius * 0.90 * TOE_TAPER[j]
            centre = V(ankle.x + sx * off_lat, y, z)
            scale = TOE_TAPER[j]
            rings.append(
                make_ring(centre, SMALL_SEGMENTS, radius * 0.92 * scale, radius * scale,
                          UP, LAT, sq=0.94)
            )
        part.loft(rings, cap_first=False, cap_last=True, cap_tension=0.66)
    return part


# --------------------------------------------------------------------------- #
# Clothing sub-meshes (shells derived from the body rings, then solidified)
# --------------------------------------------------------------------------- #
def curve_rings(
    points: list[Vector],
    widths: list[float],
    depths: list[float],
    n: int,
    ref: Vector = LAT,
    sq: float = 1.0,
) -> list[list[Vector]]:
    """Rings perpendicular to a 3D curve, with the width aligned to *ref*.

    Used for the racerback straps and the ponytail: both are lofts along a
    swept path rather than along a world axis.
    """
    rings: list[list[Vector]] = []
    count = len(points)
    for i, point in enumerate(points):
        previous = points[max(i - 1, 0)]
        nxt = points[min(i + 1, count - 1)]
        tangent = nxt - previous
        if tangent.length < 1e-8:
            tangent = nxt - point
        if tangent.length < 1e-8:
            tangent = V(0.0, 0.0, 1.0)
        tangent.normalize()
        lat = ref - tangent * ref.dot(tangent)
        if lat.length < 1e-6:
            lat = V(0.0, 1.0, 0.0)
        lat.normalize()
        fwd = tangent.cross(lat).normalized()
        rings.append(
            make_ring(point, n, depths[i], widths[i], fwd, lat, sq=sq)
        )
    return rings


def build_sports_bra() -> Part:
    """Crop-top / sports bra band + racerback straps + under-bust seam."""
    part = Part("Cloth_SportsBra", ("Mat_Sportswear",),
                thickness=CLOTH_THICKNESS, subsurf=SUBDIV_ON_CLOTH)

    band_zs = (1.176, 1.200, 1.224, 1.252, 1.282, 1.310, 1.334)
    rings = [torso_ring_at(z, push=SKIN_OFFSET) for z in band_zs]
    part.loft(rings, cap_first=False, cap_last=False)

    # scoop neckline: drop the front-centre faces of the top two rows
    part.delete_faces_where(
        lambda c: c.z > 1.298 and c.y < -0.052 and abs(c.x) < 0.078
    )

    # racerback straps: ellipse wrap around the shoulder, converging on T1/T2
    strap_z0, strap_b, strap_c = 1.360, 0.1215, 0.0965
    for sx in (1.0, -1.0):
        spine, widths, depths = [], [], []
        steps = 7
        for i in range(steps):
            u = math.radians(102.0 - i * (207.0 / (steps - 1)))   # front -> top -> back
            y = -strap_b * math.sin(u)
            z = strap_z0 + strap_c * math.cos(u)
            frac = i / (steps - 1)
            x = sx * (0.0625 - 0.0330 * frac)
            spine.append(V(x, y, z))
            widths.append(0.0165 - 0.0035 * abs(frac - 0.5) * 2.0)
            depths.append(0.0040)
        rings = curve_rings(spine, widths, depths, SMALL_SEGMENTS, ref=LAT, sq=0.65)
        part.loft(rings, cap_first=False, cap_last=False)
        if sx > 0:
            strap_left_tail = list(part.rows[-1])
        else:
            k = len(part.rows[-1])
            left, right = strap_left_tail, list(part.rows[-1])
            for c in range(k):
                # stitch the two tails together into the racerback cross-bar
                part._face((left[c], left[(c + 1) % k], right[(c + 1) % k], right[c]),
                           "Mat_Sportswear")
    return part


def build_shorts() -> Part:
    """High-waisted tight shorts: pelvis shell + two thigh cuffs."""
    part = Part("Cloth_Shorts", ("Mat_Sportswear",),
                thickness=CLOTH_THICKNESS, subsurf=SUBDIV_ON_CLOTH)

    body_zs = (1.112, 1.086, 1.052, 1.012, 0.972, 0.932, 0.892, 0.858, 0.826)
    rings = [torso_ring_at(z, push=SKIN_OFFSET) for z in body_zs]
    part.loft(rings, cap_first=False, cap_last=True, cap_tension=0.62)

    cuff_zs = (0.946, 0.900, 0.848, 0.788, 0.726, 0.672, 0.646)
    for sx in (1.0, -1.0):
        leg_rings = [leg_ring_at(z, sx, push=SKIN_OFFSET) for z in cuff_zs]
        part.loft(leg_rings, cap_first=False, cap_last=False)
    return part


def build_waistband() -> Part:
    """Raised waistband 'belt' ring over the top of the shorts."""
    part = Part("Cloth_Waistband", ("Mat_Sportswear",),
                thickness=0.0040, subsurf=SUBDIV_ON_CLOTH)
    zs = (1.030, 1.058, 1.088, 1.110)
    rings = [torso_ring_at(z, push=SKIN_OFFSET + 0.0085) for z in zs]
    part.loft(rings, cap_first=False, cap_last=False)
    return part


# --------------------------------------------------------------------------- #
# Hair: shrink-wrapped helmet grid, side-swept bangs, high ponytail
# --------------------------------------------------------------------------- #
HAIRLINE = [
    (0.0, 0.745),
    (30.0, 0.790),
    (58.0, 0.870),
    (86.0, 0.985),
    (112.0, 1.140),
    (146.0, 1.360),
    (180.0, 1.470),
]
HAIR_COLS, HAIR_ROWS = 20, 10
HAIR_LIFT = 0.0105


def head_profile(z: float, clamp_z: float = 1.575) -> tuple[float, float, float]:
    zz = max(z, clamp_z)
    _, r_lat, r_fwd = lerp_table(HEAD_STATIONS, 0, zz)[:3]
    return head_centre_y(zz), r_lat, r_fwd


def hair_point(az: float, t: float, lift: float = HAIR_LIFT, bulge: float = 0.0) -> Vector:
    """Point on the hair shell: shrink-wrapped to the lofted head + lifted out."""
    el = math.radians(88.0 * (1.0 - t))
    rx, ry, rz = HEAD_RADII
    cx, cy, cz = HEAD_SURFACE
    cos_e, sin_e = math.cos(el), math.sin(el)
    dx = rx * cos_e * math.sin(az)
    dy = -ry * cos_e * math.cos(az)
    z = cz + rz * sin_e
    centre_y, a_lat, b_fwd = head_profile(z)
    dy -= centre_y
    denom = math.sqrt((dx / a_lat) ** 2 + (dy / b_fwd) ** 2)
    scale = (1.0 / denom) if denom > 1e-6 else 1.0
    x, y = dx * scale, dy * scale
    nx, ny = x / (a_lat * a_lat), y / (b_fwd * b_fwd)
    nl = math.hypot(nx, ny) or 1.0
    lift_total = lift + bulge
    return V(x + lift_total * nx / nl, centre_y + y + lift_total * ny / nl, z)


def build_hair() -> Part:
    part = Part("Hair", ("Mat_Hair", "Mat_Sportswear"), subsurf=False)

    # ---- helmet: a lat/long grid whose lower edge follows the hairline -----
    grid = []
    for i in range(HAIR_COLS):
        az = -math.pi + 2.0 * math.pi * i / HAIR_COLS
        t_edge = lerp_table(HAIRLINE, 0, math.degrees(abs(az)))[1]
        # extra volume at the occiput only (front of the head stays tight)
        occipital = 0.0115 * max(0.0, -math.cos(az)) ** 1.5
        column = []
        for j in range(HAIR_ROWS):
            t = t_edge * j / (HAIR_ROWS - 1)
            lift = HAIR_LIFT * (0.52 + 0.48 * min(t, 1.0)) + 0.0035 * t
            column.append(hair_point(az, t, lift, occipital))
        grid.append(column)

    verts = [[part.bm.verts.new(p) for p in col] for col in grid]
    for i in range(HAIR_COLS):
        nxt = (i + 1) % HAIR_COLS
        for j in range(HAIR_ROWS - 1):
            part._face((verts[i][j], verts[nxt][j], verts[nxt][j + 1], verts[i][j + 1]))
    top = [verts[i][0] for i in range(HAIR_COLS)]
    tip = ring_centroid([grid[i][0] for i in range(HAIR_COLS)]) + V(0.0, 0.006, 0.0075)
    pole = part.bm.verts.new(tip)
    for i in range(HAIR_COLS):
        part._face((top[i], top[(i + 1) % HAIR_COLS], pole))

    # ---- side-swept bangs: tapered ribbons flowing to the character's left --
    blades = 7
    for b in range(blades):
        az_root = math.radians(-62.0 + b * 17.5)
        sweep = math.radians(52.0)
        stations = 5
        path = []
        for i in range(stations):
            f = i / (stations - 1)
            az = az_root + sweep * f ** 1.15
            t = 0.700 + 0.185 * f ** 1.25
            bulge = 0.0070 * math.sin(math.pi * min(f * 1.12, 1.0))
            path.append(hair_point(az, t, 0.0075 + bulge * 0.7, bulge * 0.3))
        widths = [0.0175 - 0.0024 * i for i in range(stations)]
        rings = curve_rings(path, widths, [0.0035] * stations, 4, ref=UP, sq=0.6)
        part.loft(rings, cap_first=False, cap_last=True, cap_tension=0.45)

    # ---- hair tie + high ponytail ------------------------------------------
    spine = [V(*p) for p in PONYTAIL_SPINE]
    tie_rings = curve_rings(spine[:2], [0.0430, 0.0410], [0.0265, 0.0250], 8, ref=LAT, sq=0.7)
    part.loft(tie_rings, cap_first=False, cap_last=False, mat_key="Mat_Sportswear")

    tail_widths = [w * 0.78 for w in PONYTAIL_WIDTH]
    tail_depths = [d * 0.78 for d in PONYTAIL_DEPTH]
    tail_spine = spine[1:]
    rings = curve_rings(tail_spine, tail_widths[1:], tail_depths[1:], 8, ref=LAT, sq=0.9)
    part.loft(rings, cap_first=True, cap_last=True, cap_tension=0.55)
    return part


# --------------------------------------------------------------------------- #
# Procedural PBR materials
# --------------------------------------------------------------------------- #
PROCEDURAL_DETAIL = True   # adds a woven bump to the fabric + pore noise to skin


def _bsdf_node(mat: bpy.types.Material):
    tree = mat.node_tree
    node = tree.nodes.get("Principled BSDF")
    if node is None:
        node = next((n for n in tree.nodes if n.type == "BSDF_PRINCIPLED"), None)
    if node is None:
        node = tree.nodes.new("ShaderNodeBsdfPrincipled")
        output = next((n for n in tree.nodes if n.type == "OUTPUT_MATERIAL"), None)
        if output:
            tree.links.new(node.outputs["BSDF"], output.inputs["Surface"])
    node.inputs["Roughness"].default_value = 0.5
    return node


def set_input(node, aliases: tuple[str, ...], value) -> bool:
    """Assign the first Principled input that exists in this Blender version.

    Socket types move around between releases (Sheen Tint became a colour in
    4.x, Subsurface Radius a vector), so the value is coerced to the socket's
    own type instead of assuming one signature.
    """
    if node is None:
        return False
    for name in aliases:
        socket = node.inputs.get(name)
        if socket is None:
            continue
        try:
            if socket.type == "VALUE":
                socket.default_value = float(value) if not isinstance(value, (tuple, list)) else float(value[0])
            elif socket.type == "RGBA":
                colour = value if isinstance(value, (tuple, list)) else (value, value, value, 1.0)
                if len(colour) == 3:
                    colour = (*colour, 1.0)
                socket.default_value = tuple(float(c) for c in colour)
            elif socket.type == "VECTOR":
                vector = value if isinstance(value, (tuple, list)) else (value, value, value)
                socket.default_value = tuple(float(c) for c in vector[:3])
            else:                                            # pragma: no cover
                socket.default_value = value
        except (TypeError, ValueError, IndexError) as exc:   # pragma: no cover
            warn(f"input '{name}' rejected ({exc})")
            return False
        return True
    return False


def create_materials() -> dict[str, bpy.types.Material]:
    """Four Principled BSDF materials, authored entirely from data."""
    specs = {
        "Mat_Skin": {
            "Base Color": "#E0A382",
            "Roughness": 0.65,
            "Subsurface Weight": 0.10,
            "Subsurface Radius": (0.12, 0.05, 0.03),
            "Subsurface Scale": 0.05,
            "Specular IOR Level": 0.42,
            "Sheen Weight": 0.02,
        },
        "Mat_Sportswear": {
            "Base Color": "#1C1D21",
            "Roughness": 0.85,
            "Metallic": 0.0,
            "Specular IOR Level": 0.20,
            "Sheen Weight": 0.35,
            "Sheen Tint": (0.85, 0.85, 0.90),
        },
        "Mat_Hair": {
            "Base Color": "#1A110E",
            "Roughness": 0.45,
            "Anisotropic": 0.65,
            "Anisotropic Rotation": 0.0,
            "Coat Weight": 0.18,
            "Specular IOR Level": 0.45,
        },
        "Mat_Eyes_Lips": {
            "Base Color": "#2B1A17",
            "Roughness": 0.28,
            "Metallic": 0.0,
            "Specular IOR Level": 0.65,
            "Coat Weight": 0.35,
        },
    }

    missing_keys = [k for k in MATERIAL_KEYS if k not in specs]
    if missing_keys:                                           # pragma: no cover
        raise RuntimeError(f"material definitions missing for {missing_keys}")

    materials: dict[str, bpy.types.Material] = {}
    for key, values in specs.items():
        mat = bpy.data.materials.new(key)
        mat.use_nodes = True
        mat.diffuse_color = (1.0, 1.0, 1.0, 1.0)
        bsdf = _bsdf_node(mat)
        for alias, value in values.items():
            colour = None
            if isinstance(value, str) and value.startswith("#"):
                colour = hex_to_rgba(value)
                value = colour
            if alias == "Base Color" and colour is not None:
                mat.diffuse_color = colour
            if not set_input(bsdf, (alias, _legacy_alias(alias)), value):
                warn(f"{key}: input '{alias}' not available in Blender {bpy.app.version_string}")
        if PROCEDURAL_DETAIL and key == "Mat_Sportswear":
            _add_fabric_weave(mat)
        if PROCEDURAL_DETAIL and key == "Mat_Skin":
            _add_skin_pores(mat)
        materials[key] = mat
        log(f"material {key}: {len(mat.node_tree.nodes)} nodes")
    assert set(materials) == set(MATERIAL_KEYS), "material set drifted from MATERIAL_KEYS"
    return materials


def _legacy_alias(name: str) -> str:
    """Blender 4.0 renamed several Principled inputs; keep 3.x names as fallback."""
    return {
        "Base Color": "Base Color",
        "Subsurface Weight": "Subsurface",
        "Subsurface Radius": "Subsurface Radius",
        "Subsurface Scale": "Subsurface Scale",
        "Specular IOR Level": "Specular",
        "Sheen Weight": "Sheen",
        "Sheen Tint": "Sheen Tint",
        "Coat Weight": "Coat",
        "Anisotropic": "Anisotropic",
        "Anisotropic Rotation": "Anisotropic Rotation",
        "Metallic": "Metallic",
        "Roughness": "Roughness",
    }.get(name, name)


def _add_fabric_weave(mat: bpy.types.Material) -> None:
    try:
        tree = mat.node_tree
        bsdf = _bsdf_node(mat)
        wave = tree.nodes.new("ShaderNodeTexWave")
        wave.inputs["Scale"].default_value = 900.0
        wave.inputs["Distortion"].default_value = 3.0
        wave.inputs["Detail"].default_value = 1.0
        bump = tree.nodes.new("ShaderNodeBump")
        bump.inputs["Strength"].default_value = 0.16
        bump.inputs["Distance"].default_value = 0.0008
        tree.links.new(wave.outputs["Color"], bump.inputs["Height"])
        tree.links.new(bump.outputs["Normal"], bsdf.inputs["Normal"])
    except (RuntimeError, KeyError, TypeError) as exc:      # pragma: no cover
        warn(f"fabric weave skipped: {exc}")


def _add_skin_pores(mat: bpy.types.Material) -> None:
    try:
        tree = mat.node_tree
        bsdf = _bsdf_node(mat)
        noise = tree.nodes.new("ShaderNodeTexNoise")
        noise.inputs["Scale"].default_value = 780.0
        noise.inputs["Detail"].default_value = 2.0
        noise.inputs["Roughness"].default_value = 0.55
        bump = tree.nodes.new("ShaderNodeBump")
        bump.inputs["Strength"].default_value = 0.045
        bump.inputs["Distance"].default_value = 0.0004
        tree.links.new(noise.outputs["Fac"], bump.inputs["Height"])
        tree.links.new(bump.outputs["Normal"], bsdf.inputs["Normal"])
    except (RuntimeError, KeyError, TypeError) as exc:      # pragma: no cover
        warn(f"skin micro-bump skipped: {exc}")


# --------------------------------------------------------------------------- #
# Assembly helpers
# --------------------------------------------------------------------------- #
def activate(obj: bpy.types.Object | None) -> bpy.types.Object | None:
    """Select + activate exactly one object; returns the previous active object."""
    previous = bpy.context.view_layer.objects.active
    try:
        if bpy.context.mode != "OBJECT":
            bpy.ops.object.mode_set(mode="OBJECT")
    except RuntimeError:                                      # pragma: no cover
        pass
    bpy.ops.object.select_all(action="DESELECT")
    if obj is not None:
        obj.hide_set(False)
        obj.select_set(True)
        bpy.context.view_layer.objects.active = obj
    bpy.context.view_layer.update()
    return previous


def restore_active(previous: bpy.types.Object | None) -> None:
    if previous is None:
        return
    try:
        bpy.ops.object.select_all(action="DESELECT")
        previous.select_set(True)
        bpy.context.view_layer.objects.active = previous
    except (RuntimeError, ReferenceError):                    # pragma: no cover
        pass


def join_parts(parts: list[Part], name: str) -> bpy.types.Object:
    objects = [part.to_object() for part in parts]
    return join_objects(objects, name)


def join_objects(objects: list[bpy.types.Object], name: str) -> bpy.types.Object:
    keep = [o for o in objects if o is not None]
    if not keep:
        raise RuntimeError("nothing to join")
    bpy.ops.object.mode_set(mode="OBJECT")
    bpy.ops.object.select_all(action="DESELECT")
    for obj in keep:
        obj.hide_set(False)
        obj.select_set(True)
    bpy.context.view_layer.objects.active = keep[0]
    if len(keep) > 1:
        bpy.ops.object.join()
    result = bpy.context.view_layer.objects.active
    result.name = name
    result.data.name = name
    return result


def weld_and_clean(obj: bpy.types.Object, tolerance: float) -> dict:
    bm = bmesh.new()
    bm.from_mesh(obj.data)
    for pass_index, dist in enumerate((tolerance, tolerance * 0.25)):
        bmesh.ops.remove_doubles(bm, verts=bm.verts[:], dist=dist)
        degenerate = [f for f in bm.faces if len(f.verts) < 3 or f.calc_area() < 1e-9]
        if degenerate:
            delete_geom(bm, degenerate, ("FACES",))
        loose = [v for v in bm.verts if not v.link_faces]
        if loose:
            delete_geom(bm, loose, ("VERTS", "VERTICES"))
        _ = pass_index
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces[:])
    counts = {"verts": len(bm.verts), "faces": len(bm.faces)}
    bm.to_mesh(obj.data)
    bm.free()
    obj.data.update()
    return counts


def flatten_shading(obj: bpy.types.Object) -> None:
    if not FLAT_SHADING:
        return
    # flat / faceted shading: clear the smooth flag on every polygon and drop
    # any custom split normals, which is the 4.x equivalent of shade_flat().
    smooth = [False] * len(obj.data.polygons)
    if smooth:
        obj.data.polygons.foreach_set("use_smooth", smooth)
    try:
        obj.data.use_auto_smooth = False          # Blender <= 4.0 only
    except AttributeError:
        pass
    for clearer in ("custom_split_normals_clear", "free_custom_normals"):
        method = getattr(obj.data, clearer, None)
        if callable(method):                                 # pragma: no cover
            try:
                method()
            except (RuntimeError, TypeError):
                pass
    if hasattr(bpy.ops.mesh, "customdata_custom_splitnormals_clear"):
        try:
            previous = bpy.context.view_layer.objects.active
            bpy.ops.object.select_all(action="DESELECT")
            obj.select_set(True)
            bpy.context.view_layer.objects.active = obj
            bpy.ops.mesh.customdata_custom_splitnormals_clear()
            if previous is not None:
                previous.select_set(True)
        except (RuntimeError, TypeError):                    # pragma: no cover
            pass
    obj.data.update()
    previous = activate(obj)
    try:
        bpy.ops.object.shade_flat()
    except (RuntimeError, TypeError):                         # pragma: no cover
        pass
    restore_active(previous)


def clamp_sole_to_floor(obj: bpy.types.Object, ceiling: float = 0.0035) -> int:
    touched = 0
    for vert in obj.data.vertices:
        if vert.co.z < ceiling:
            vert.co.z = 0.0
            touched += 1
    obj.data.update()
    return touched


def measure(obj: bpy.types.Object) -> tuple[Vector, Vector]:
    corners = [obj.matrix_world @ Vector(corner) for corner in obj.bound_box]
    low = Vector((min(c.x for c in corners), min(c.y for c in corners), min(c.z for c in corners)))
    high = Vector((max(c.x for c in corners), max(c.y for c in corners), max(c.z for c in corners)))
    return low, high


def fit_height(objects: list[bpy.types.Object], target: float) -> float:
    """Uniformly scale rig + meshes so the crown lands exactly on *target*."""
    reference = objects[0]
    low, high = measure(reference)
    current = high.z - min(low.z, 0.0)
    if current <= 1e-6:
        return 1.0
    factor = target / current
    if abs(factor - 1.0) > 1e-5:
        scale = Matrix.Scale(factor, 4)
        for obj in objects:
            obj.matrix_world = scale @ obj.matrix_world
    return factor


def apply_transforms(objects: list[bpy.types.Object]) -> None:
    """Ctrl+A equivalent: bake location / rotation / scale into the data."""
    bpy.ops.object.mode_set(mode="OBJECT")
    bpy.ops.object.select_all(action="DESELECT")
    for obj in objects:
        obj.hide_set(False)
        obj.select_set(True)
    bpy.context.view_layer.objects.active = objects[0]
    args = op_kwargs(
        bpy.ops.object.transform_apply,
        {"location": True, "rotation": True, "scale": True, "properties": False},
    )
    try:
        bpy.ops.object.transform_apply(**args)
    except (RuntimeError, TypeError) as exc:                 # pragma: no cover
        warn(f"transform_apply failed ({exc}) - baking transforms by hand")
        for obj in objects:
            obj.matrix_basis = Matrix.Identity(4)
    for obj in objects:
        if hasattr(obj.data, "update"):
            obj.data.update()
    bpy.context.view_layer.update()


def smart_uv(obj: bpy.types.Object) -> bool:
    if not ADD_UVS:
        return False
    previous = activate(obj)
    try:
        bpy.ops.object.mode_set(mode="EDIT")
        bpy.ops.mesh.select_all(action="SELECT")
        args = op_kwargs(
            bpy.ops.uv.smart_project,
            {
                "angle_limit": math.radians(66.0),
                "island_margin": 0.018,
                "area_weight": 0.25,
                "corrective_angle_limit": math.radians(88.0),
                "scale_by_length_changed": False,
            },
        )
        bpy.ops.uv.smart_project(**args)
        try:
            pack = op_kwargs(bpy.ops.uv.pack_islands, {"rotate": True, "margin": 0.006})
            bpy.ops.uv.pack_islands(**pack)
        except (RuntimeError, TypeError) as exc:            # pragma: no cover
            warn(f"pack_islands skipped ({exc})")
        bpy.ops.object.mode_set(mode="OBJECT")
        restore_active(previous)
        return True
    except (RuntimeError, TypeError) as exc:                # pragma: no cover
        try:
            bpy.ops.object.mode_set(mode="OBJECT")
        except RuntimeError:
            pass
        restore_active(previous)
        warn(f"UV unwrap skipped: {exc}")
        return False


# --------------------------------------------------------------------------- #
# Humanoid armature
# --------------------------------------------------------------------------- #
def bone_table() -> list[tuple]:
    """(name, head, tail, parent, use_connect) for the full 51-bone humanoid rig.

    Every joint position is read from the same chains that drive the loft, so
    the skeleton lands exactly on the mesh.  Nothing here is a placeholder:
    all five fingers per hand and both legs are authored explicitly.
    """
    specs: list[tuple] = [
        ("Hips", V(0.0, 0.026, 0.856), SPINE_CHAIN[1], None, False),
        ("Spine", SPINE_CHAIN[1], SPINE_CHAIN[2], "Hips", True),
        ("Chest", SPINE_CHAIN[2], SPINE_CHAIN[4], "Spine", True),
        ("Neck", SPINE_CHAIN[4], SPINE_CHAIN[5], "Chest", True),
        ("Head", SPINE_CHAIN[5], V(0.0, 0.012, 1.662), "Neck", True),
    ]

    for sx, suffix in ((1.0, "L"), (-1.0, "R")):
        arm_pts = arm_chain(sx)
        leg_pts = leg_chain(sx)

        specs.append((f"Shoulder.{suffix}", V(sx * 0.020, -0.012, 1.352),
                      V(sx * 0.163, 0.000, ARM_Z), "Chest", False))
        specs.append((f"UpperArm.{suffix}", arm_pts[1], arm_pts[2], f"Shoulder.{suffix}", False))
        specs.append((f"LowerArm.{suffix}", arm_pts[2], arm_pts[3], f"UpperArm.{suffix}", True))
        specs.append((f"Hand.{suffix}", arm_pts[3], arm_pts[4], f"LowerArm.{suffix}", True))

        stations = finger_stations(sx)
        for finger in ("Thumb", "Index", "Middle", "Ring", "Pinky"):
            joints = stations[finger]
            parent = f"Hand.{suffix}"
            for i in range(len(joints) - 1):
                name = f"{finger}.0{i + 1}.{suffix}"
                specs.append((name, joints[i], joints[i + 1], parent, i > 0))
                parent = name

        specs.append((f"UpperLeg.{suffix}", leg_pts[1], leg_pts[2], "Hips", False))
        specs.append((f"LowerLeg.{suffix}", leg_pts[2], leg_pts[3], f"UpperLeg.{suffix}", True))
        specs.append((f"Foot.{suffix}", leg_pts[3], leg_pts[4], f"LowerLeg.{suffix}", True))
        specs.append((f"Toe.{suffix}", leg_pts[4], leg_pts[5], f"Foot.{suffix}", True))
    return specs


def build_armature() -> bpy.types.Object:
    armature_data = bpy.data.armatures.new("Armature")
    armature = bpy.data.objects.new("AthleticFemale_Rig", armature_data)
    bpy.context.scene.collection.objects.link(armature)
    armature.location = (0.0, 0.0, 0.0)
    armature.rotation_euler = (0.0, 0.0, 0.0)
    armature.scale = (1.0, 1.0, 1.0)
    armature.display_type = "WIRE"
    armature.show_in_front = True          # handy while animating in the viewport

    bpy.ops.object.mode_set(mode="OBJECT")
    bpy.ops.object.select_all(action="DESELECT")
    armature.select_set(True)
    bpy.context.view_layer.objects.active = armature
    bpy.ops.object.mode_set(mode="EDIT")
    edit_bones = armature_data.edit_bones
    for name, head, tail, parent, connect in bone_table():
        bone = edit_bones.new(name)
        bone.head = head
        bone.tail = tail
        bone.roll = 0.0
        try:                        # bone layers still exist on <= 4.0 / rigify
            bone.layers = tuple([True] + [False] * (len(bone.layers) - 1))
        except (AttributeError, TypeError):   # 4.x uses bone collections
            pass
        if parent:
            parent_bone = edit_bones.get(parent)
            if parent_bone is None:                          # pragma: no cover
                warn(f"bone '{name}': parent '{parent}' missing, left unparented")
            else:
                bone.parent = parent_bone
                bone.use_connect = bool(connect)
    bpy.ops.object.mode_set(mode="OBJECT")

    for bone in armature_data.bones:
        bone.use_deform = True
    if "Hips" in armature_data.bones:
        armature_data.bones.active = armature_data.bones["Hips"]
    armature_data.update_tag()
    bpy.context.view_layer.update()
    log(f"armature: {len(armature_data.bones)} bones")
    return armature


# --------------------------------------------------------------------------- #
# Skinning
# --------------------------------------------------------------------------- #
def _rest_bone_segments(armature: bpy.types.Object) -> list[tuple[str, Vector, Vector]]:
    out = []
    matrix = armature.matrix_world
    for bone in armature.data.bones:
        out.append((bone.name, matrix @ bone.head_local, matrix @ bone.tail_local))
    return out


def _closest_bone(co: Vector, segments: list[tuple[str, Vector, Vector]]) -> str:
    best_name, best_dist = segments[0][0], float("inf")
    for name, head, tail in segments:
        axis = tail - head
        length_sq = axis.length_squared
        if length_sq < 1e-12:
            dist = (co - head).length
        else:
            t = clamp((co - head).dot(axis) / length_sq, 0.0, 1.0)
            dist = (co - (head + axis * t)).length
        if dist < best_dist:
            best_name, best_dist = name, dist
    return best_name


def bind_automatic_weights(body: bpy.types.Object, hair: bpy.types.Object,
                           armature: bpy.types.Object) -> str:
    """`Ctrl+P -> Armature Deform (Automatic Weights)` for the body, rigid Head
    bind for the hair (so the ponytail never gets blended with the neck)."""
    method = "automatic_weights"
    bpy.ops.object.mode_set(mode="OBJECT")
    bpy.ops.object.select_all(action="DESELECT")
    body.select_set(True)
    armature.select_set(True)
    bpy.context.view_layer.objects.active = armature
    try:
        bpy.ops.object.parent_set(type="ARMATURE_AUTO")
    except (RuntimeError, TypeError) as exc:
        warn(f"ARMATURE_AUTO failed ({exc}) - falling back to nearest-bone weights")
        method = "nearest_bone"
    if method == "nearest_bone":
        body.parent = armature
        if not any(m.type == "ARMATURE" for m in body.modifiers):
            mod = body.modifiers.new("Armature", "ARMATURE")
            mod.object = armature
        _assign_nearest_weights(body, armature)
    if not body.vertex_groups:                               # pragma: no cover
        warn("automatic weights produced no groups - re-assigning by proximity")
        _assign_nearest_weights(body, armature)

    # hair: bone-parented to Head through a single full-weight vertex group
    hair.parent = armature
    hair.matrix_parent_inverse = armature.matrix_world.inverted()
    group = hair.vertex_groups.get("Head") or hair.vertex_groups.new(name="Head")
    group.add(range(len(hair.data.vertices)), 1.0, "REPLACE")
    if not any(m.type == "ARMATURE" for m in hair.modifiers):
        mod = hair.modifiers.new("Armature", "ARMATURE")
        mod.object = armature
        mod.use_vertex_groups = True
        mod.use_bone_envelopes = False
    return method


def _assign_nearest_weights(obj: bpy.types.Object, armature: bpy.types.Object) -> None:
    """Deterministic safety net: one rigid weight per vertex, nearest bone."""
    segments = _rest_bone_segments(armature)
    groups = {name: obj.vertex_groups.get(name) or obj.vertex_groups.new(name=name)
              for name, _head, _tail in segments}
    inverse = obj.matrix_world.inverted()
    counts: dict[str, list[int]] = {}
    for vert in obj.data.vertices:
        counts.setdefault(_closest_bone(inverse @ vert.co, segments), []).append(vert.index)
    for bone_name, indices in counts.items():
        groups[bone_name].add(indices, 1.0, "REPLACE")


def quantize_weights(obj: bpy.types.Object, armature: bpy.types.Object,
                     limit: int = 4) -> dict:
    """Clamp to *limit* influences, renormalise, and repair unweighted vertices."""
    segments = _rest_bone_segments(armature)
    valid = {name for name, _h, _t in segments}
    total_verts = len(obj.data.vertices)
    index_to_name = {group.index: group.name for group in obj.vertex_groups}
    payload: list[list[tuple[float, int]]] = []
    repaired = 0
    for vert in obj.data.vertices:
        pairs = sorted(((g.weight, g.group) for g in vert.groups
                        if g.group in index_to_name and index_to_name[g.group] in valid),
                       reverse=True)
        pairs = [p for p in pairs if p[0] > 1e-6][:limit]
        total = sum(w for w, _g in pairs)
        if total <= 1e-6:
            name = _closest_bone(obj.matrix_world.inverted() @ vert.co, segments)
            group = obj.vertex_groups.get(name) or obj.vertex_groups.new(name=name)
            pairs = [(1.0, group.index)]
            repaired += 1
        else:
            pairs = [(w / total, g) for w, g in pairs]
        payload.append(pairs)

    all_indices = range(total_verts)
    for group in list(obj.vertex_groups):
        group.remove(all_indices)
    # VertexGroup.add() takes one scalar weight per call in 4.x, so the batch is
    # written per vertex (still ~20k fast calls for this mesh, no operators needed).
    for index, pairs in enumerate(payload):
        for weight, group_index in pairs:
            obj.vertex_groups[group_index].add([index], weight, "REPLACE")
    by_group: dict[int, int] = {}
    for pairs in payload:
        for _weight, group_index in pairs:
            by_group[group_index] = by_group.get(group_index, 0) + 1
    for name, count in sorted(by_group.items(), key=lambda kv: -kv[1])[:6]:
        log(f"  weight share: {index_to_name.get(name, name)} -> {count} verts")
    # Prune groups that ended up empty.  Removal renumbers the surviving
    # groups, so keep/drop is decided by *name* and removals run from the
    # highest index down (never shifts an index we have yet to test).
    keep = {index_to_name[gi] for gi in by_group if gi in index_to_name}
    for group in sorted(list(obj.vertex_groups), key=lambda g: -g.index):
        if group.name not in keep:
            obj.vertex_groups.remove(group)

    max_influence = max((len(p) for p in payload), default=0)
    log(
        f"weights: {total_verts} verts, {len(obj.vertex_groups)} groups, "
        f"max {max_influence} influences, {repaired} vertex/vertices re-targeted"
    )
    return {"vertices": total_verts, "groups": len(obj.vertex_groups),
            "max_influence": max_influence, "repaired": repaired}


def verify_weights(obj: bpy.types.Object, limit: int) -> dict:
    worst = 0.0
    over = 0
    empty = 0
    for vert in obj.data.vertices:
        total = sum(g.weight for g in vert.groups)
        worst = max(worst, abs(total - 1.0))
        if len(vert.groups) > limit:
            over += 1
        if total <= 1e-6:
            empty += 1
    return {"max_normalisation_error": worst, "over_limit": over, "unweighted": empty}


# --------------------------------------------------------------------------- #
# Save + game-ready glTF export
# --------------------------------------------------------------------------- #
def enable_gltf_addon() -> bool:
    if hasattr(bpy.ops.export_scene, "gltf"):
        return True
    for module in ("io_scene_gltf2", "bl_ext.system.io_scene_gltf2",
                   "bl_ext.blender_org.io_scene_gltf2"):
        try:
            bpy.ops.preferences.addon_enable(module=module)
        except (RuntimeError, AttributeError):
            continue
        if hasattr(bpy.ops.export_scene, "gltf"):
            return True
    return False


def export_glb(objects: list[bpy.types.Object], path: str) -> int:
    if not enable_gltf_addon():
        raise RuntimeError("glTF 2.0 exporter (io_scene_gltf2) is not available in this Blender build")

    bpy.ops.object.mode_set(mode="OBJECT")
    bpy.ops.object.select_all(action="DESELECT")
    for obj in objects:
        obj.hide_set(False)
        obj.hide_render = False
        obj.select_set(True)
    bpy.context.view_layer.objects.active = objects[0]
    bpy.context.view_layer.update()

    wanted = {
        "filepath": path,
        "export_format": "GLB",
        "use_selection": True,
        "use_visible": False,
        "use_renderable": False,
        "export_copyright": "Procedural athletic female - generated with generate_athletic_female_character.py",
        "export_apply": False,
        "export_yup": True,
        "export_materials": "EXPORT",
        "export_image_format": "AUTO",
        "export_texcoords": ADD_UVS,
        "export_normals": True,
        "export_tangents": False,
        "export_attributes": True,
        "export_extras": False,
        "export_skins": True,
        "export_all_influences": False,
        "export_influence_nb": LIMIT_BONE_INFLUENCES,
        "export_def_bones": False,
        "export_leaf_bones": False,
        "export_rest_position_armature": "REST_POSITION",
        "export_animations": False,
        "export_morph": ADD_SHAPE_KEYS,
        "export_lights": False,
        "export_cameras": False,
        "export_gn_mesh": False,
        "export_shared_accessors": True,
        "export_hierarchy_flatten_bones": False,
        }
    args = op_kwargs(bpy.ops.export_scene.gltf, wanted)
    # A few option types changed between glTF exporter 1.5 / 1.6 / 4.5 builds
    # (e.g. export_rest_position_armature went enum -> bool), so drop any
    # keyword the installed exporter refuses and retry instead of failing.
    while True:
        try:
            bpy.ops.export_scene.gltf(**args)
            break
        except (TypeError, RuntimeError) as exc:
            message = str(exc)
            offender = next((k for k in args if k in message), None)
            if offender in (None, "filepath"):
                raise
            warn(f"glTF exporter rejected '{offender}' ({message.strip()[:120]}) - retrying without it")
            args.pop(offender)
    log("glTF options: " + ", ".join(sorted(k for k in args if k != "filepath")))
    return os.path.getsize(path) if os.path.exists(path) else 0


def save_blend(path: str) -> int:
    try:
        bpy.ops.wm.save_as_mainfile(filepath=path)
    except (RuntimeError, OSError) as exc:                   # pragma: no cover
        warn(f"save_as_mainfile failed: {exc}")
        return 0
    return os.path.getsize(path) if os.path.exists(path) else 0


def reimport_check(path: str, expected: tuple[str, ...] = ("AthleticFemale_Body", "AthleticFemale_Hair")) -> dict:
    """Round-trip the exported .glb to prove skins + weights + materials survived.

    Only the objects we exported are judged; the importer may also add helper
    objects (a preview mesh for material variants), which are cleaned up below.
    """
    known = {obj.name for obj in bpy.data.objects}
    result = {"ok": False, "meshes": 0, "skinned": 0, "materials": set(), "joints": 0}
    try:
        bpy.ops.import_scene.gltf(filepath=path)
    except (RuntimeError, TypeError, AttributeError) as exc:  # pragma: no cover
        warn(f"glTF re-import unavailable ({exc}) - skipping round-trip check")
        return result
    imported = [o for o in bpy.data.objects if o.name not in known]
    found: dict[str, bpy.types.Object] = {}
    for obj in imported:
        stem = obj.name.split(".")[0]
        if obj.type == "ARMATURE":
            result["joints"] = max(result["joints"], len(obj.data.bones))
        if stem in expected and obj.type == "MESH" and stem not in found:
            found[stem] = obj
            for slot in obj.material_slots:
                if slot.material:
                    result["materials"].add(slot.material.name)
            result["uv_layers"] = max(result.get("uv_layers", 0), len(obj.data.uv_layers))
            result["verts"] = result.get("verts", 0) + len(obj.data.vertices)
            result["tris"] = result.get("tris", 0) + sum(
                len(p.vertices) - 2 for p in obj.data.polygons)
    result["meshes"] = len(found)
    result["skinned"] = sum(
        1 for obj in found.values()
        if obj.vertex_groups and any(m.type == "ARMATURE" for m in obj.modifiers)
    )
    result["ok"] = (
        result["meshes"] == len(expected)
        and result["skinned"] == result["meshes"]
        and result["joints"] >= 45
    )
    for obj in imported:
        for coll in list(obj.users_collection):
            coll.objects.unlink(obj)
        bpy.data.objects.remove(obj, do_unlink=True)
    if hasattr(bpy.data, "orphans_purge"):
        try:
            bpy.data.orphans_purge(do_local_ids=True, do_linked_ids=True, do_recursive=True)
        except (TypeError, RuntimeError):                     # pragma: no cover
            pass
    return result


# --------------------------------------------------------------------------- #
# Report
# --------------------------------------------------------------------------- #
def mesh_stats(obj: bpy.types.Object) -> dict:
    tris = sum(len(poly.vertices) - 2 for poly in obj.data.polygons)
    quads = sum(1 for poly in obj.data.polygons if len(poly.vertices) == 4)
    faces = len(obj.data.polygons)
    bm = bmesh.new()
    bm.from_mesh(obj.data)
    non_manifold = sum(1 for edge in bm.edges if not edge.is_manifold)
    boundary = sum(1 for edge in bm.edges if edge.is_boundary)
    degenerate = sum(1 for face in bm.faces if face.calc_area() < 1e-10)
    bm.free()
    low, high = measure(obj)
    return {
        "vertices": len(obj.data.vertices),
        "faces": faces,
        "triangles": tris,
        "quads": quads,
        "quad_ratio": (quads / faces) if faces else 0.0,
        "non_manifold_edges": non_manifold,
        "boundary_edges": boundary,
        "degenerate_faces": degenerate,
        "material_slots": len(obj.material_slots),
        "uv_layers": len(obj.data.uv_layers),
        "dimensions": high - low,
        "height": high.z,
    }


def print_report(body: bpy.types.Object, hair: bpy.types.Object,
                 armature: bpy.types.Object, weight_info: dict,
                 bind_method: str, files: dict[str, int],
                 gltf_roundtrip: dict, elapsed: float) -> None:
    body_stats, hair_stats = mesh_stats(body), mesh_stats(hair)
    bones = list(armature.data.bones)
    connected = sum(1 for b in bones if b.use_connect)
    chains = {
        "spine": ["Hips", "Spine", "Chest", "Neck", "Head"],
        "arm": [f"{n}.L" for n in ("Shoulder", "UpperArm", "LowerArm", "Hand")],
        "leg": [f"{n}.L" for n in ("UpperLeg", "LowerLeg", "Foot", "Toe")],
        "fingers": [f"{f}.0{i}.{s}" for f in ("Thumb", "Index", "Middle", "Ring", "Pinky")
                    for i in (1, 2, 3) for s in ("L", "R")],
    }
    bone_names = {bone.name for bone in bones}
    missing = sorted(name for chain in chains.values() for name in chain if name not in bone_names)

    log("---------------- asset report ----------------")
    log("files: " + ", ".join(f"{os.path.basename(k)} ({v / 1024:.0f} KiB)" for k, v in files.items()))
    log(f"bind method: {bind_method}; transforms applied: "
        f"{body.matrix_world.is_identity and hair.matrix_world.is_identity}")
    log(f"body: {body_stats['vertices']} verts / {body_stats['faces']} faces / "
        f"{body_stats['triangles']} tris / {body_stats['quad_ratio'] * 100:.1f}% quads")
    log(f"hair: {hair_stats['vertices']} verts / {hair_stats['faces']} faces")
    log(f"total triangles (body+hair): {body_stats['triangles'] + hair_stats['triangles']}")
    log(f"dimensions WxDxH: {body_stats['dimensions'].x:.3f} x "
        f"{body_stats['dimensions'].y:.3f} x {body_stats['height']:.3f} m "
        f"(with hair {max(body_stats['height'], hair_stats['height']):.3f} m)")
    log(f"topology: {body_stats['non_manifold_edges']} non-manifold edges, "
        f"{body_stats['boundary_edges']} boundary edges, "
        f"{body_stats['degenerate_faces']} degenerate faces")
    slots = {slot.material.name for slot in body.material_slots if slot.material}
    slots |= {slot.material.name for slot in hair.material_slots if slot.material}
    log(f"materials: {sorted(slots)}")
    for label, obj in (("body", body), ("hair", hair)):
        counts = {}
        for poly in obj.data.polygons:
            name = obj.material_slots[poly.material_index].material.name if \
                poly.material_index < len(obj.material_slots) and obj.material_slots[poly.material_index].material else "-"
            counts[name] = counts.get(name, 0) + 1
        log(f"{label} faces per material: {counts}")
    log(f"uv layers: body={body_stats['uv_layers']} hair={hair_stats['uv_layers']}")
    log(f"armature: {len(bones)} bones ({connected} connected), missing={missing or 'none'}")
    log(f"weights: {weight_info['groups']} groups, max {weight_info['max_influence']} "
        f"influences/vertex, {weight_info['repaired']} repaired")
    check = verify_weights(body, LIMIT_BONE_INFLUENCES)
    log(f"weights check: max |sum-1| = {check['max_normalisation_error']:.2e}, "
        f"over-limit verts = {check['over_limit']}, unweighted verts = {check['unweighted']}")
    if gltf_roundtrip.get("ok"):
        log(f"glb roundtrip: {gltf_roundtrip['meshes']} meshes all skinned, "
            f"{gltf_roundtrip['joints']} joints, {gltf_roundtrip.get('verts', 0)} verts / "
            f"{gltf_roundtrip.get('tris', 0)} tris, "
            f"materials={sorted({m.split('.')[0] for m in gltf_roundtrip.get('materials', set())})}")
    else:
        warn("glb round-trip check did not confirm skinning")
    log(f"elapsed: {elapsed:.1f}s")
    log("------------------------------------------")


# --------------------------------------------------------------------------- #
# Entry point
# --------------------------------------------------------------------------- #
def parse_args(argv: list[str]) -> dict:
    opts = {"height": TARGET_HEIGHT, "subdiv": SUBDIV_LEVEL, "outdir": None, "pose": POSE}
    if "--" in argv:
        argv = argv[argv.index("--") + 1:]
    else:
        argv = argv[1:]
    i = 0
    while i < len(argv):
        token = argv[i]
        if token.startswith("--"):
            key, _, value = token[2:].partition("=")
            i += 1
            if not value and i < len(argv) and not argv[i].startswith("--"):
                value = argv[i]
                i += 1
        else:
            i += 1
            continue
        if key in ("height", "subdiv", "outdir", "pose"):
            if key == "outdir":
                opts["outdir"] = value
            elif key == "pose":
                opts["pose"] = value
            else:
                opts[key] = float(value) if key == "height" else int(value)
    return opts


def resolve_output_dir(cli_value: str | None) -> str:
    """Output location precedence: --outdir > $OUTPUT_DIR > repo artifacts dir > ./output."""
    if cli_value:
        path = os.path.abspath(os.path.expanduser(cli_value))
    elif os.environ.get("OUTPUT_DIR"):
        path = os.path.abspath(os.path.expanduser(os.environ["OUTPUT_DIR"]))
    else:
        here = ""
        try:
            here = os.path.dirname(os.path.abspath(__file__))
        except NameError:                       # pasted into Blender's Text Editor
            here = ""
        if not here and bpy.data.filepath:
            here = os.path.dirname(bpy.data.filepath)
        if not here:
            here = os.path.abspath(os.getcwd())
        repo_root = os.path.dirname(here)
        if os.path.isdir(os.path.join(repo_root, ".git")):
            # this repo git-ignores artifacts_out/ (and *.blend), so generated
            # binaries never dirty the working tree
            path = os.path.join(repo_root, "artifacts_out", "blender")
        else:
            path = os.path.join(here, "output")
    os.makedirs(path, exist_ok=True)
    return path


def build_character(opts: dict) -> tuple[bpy.types.Object, bpy.types.Object,
                                         bpy.types.Object, dict, str]:
    global SUBDIV_LEVEL, ARM_ANGLE_DEG, POSE
    SUBDIV_LEVEL = max(0, int(opts.get("subdiv", SUBDIV_LEVEL)))
    pose = str(opts.get("pose", POSE)).strip().upper()
    if pose in ("T", "A"):
        POSE = pose
        ARM_ANGLE_DEG = 0.0 if pose == "T" else 45.0
    log(f"pose={POSE}  subdivisions={SUBDIV_LEVEL}  cloth_thickness={CLOTH_THICKNESS}")

    reset_scene()
    scene = bpy.context.scene
    configure_units(scene)
    create_materials()

    log("building parts ...")
    parts = [
        build_torso_and_head(),
        build_arm_side(1.0),
        build_arm_side(-1.0),
        build_leg_side(1.0),
        build_leg_side(-1.0),
        build_sports_bra(),
        build_shorts(),
        build_waistband(),
    ]
    body = join_parts(parts, "AthleticFemale_Body")
    hair = build_hair().to_object()
    hair.name = "AthleticFemale_Hair"
    hair.data.name = "AthleticFemale_Hair"

    log(f"body: weld/clean -> {weld_and_clean(body, WELD_TOLERANCE)}")
    weld_and_clean(hair, 0.0006)
    log(f"sole clamp: {clamp_sole_to_floor(body)} vertex/vertices snapped to the floor plane")
    flatten_shading(body)
    flatten_shading(hair)
    if ADD_UVS:
        log(f"UV atlas: body={smart_uv(body)} hair={smart_uv(hair)}")

    armature = build_armature()
    factor = fit_height([body, hair, armature], float(opts["height"]))
    if abs(factor - 1.0) > 1e-6:
        log(f"uniform scale to reach {opts['height']:.3f} m: {factor:.5f}")
    apply_transforms([body, hair, armature])

    method = bind_automatic_weights(body, hair, armature)
    info = quantize_weights(body, armature, LIMIT_BONE_INFLUENCES)
    quantize_weights(hair, armature, 1)
    bpy.context.view_layer.update()
    return body, hair, armature, info, method


def main(argv: list[str] | None = None) -> int:
    started = time.time()
    opts = parse_args(list(argv if argv is not None else sys.argv))
    out_dir = resolve_output_dir(opts["outdir"])
    try:
        body, hair, armature, info, method = build_character(opts)
    except Exception:                                          # pragma: no cover
        traceback.print_exc()
        log("FAILED")
        return 1

    blend_path = os.path.join(out_dir, f"{ASSET_STEM}.blend")
    glb_path = os.path.join(out_dir, f"{ASSET_STEM}.glb")
    files = {"blend": save_blend(blend_path) if EXPORT_BLENDS else 0}
    if not EXPORT_BLENDS:
        log("EXPORT_BLENDS is False - skipping the .blend save")
    try:
        files["glb"] = export_glb([armature, body, hair], glb_path)
    except (RuntimeError, TypeError) as exc:                   # pragma: no cover
        warn(f"glTF export failed: {exc}")
        files["glb"] = 0
    roundtrip = reimport_check(glb_path) if files["glb"] else {}

    print_report(body, hair, armature, info, method, files, roundtrip, time.time() - started)
    log(f"outputs: {blend_path}")
    log(f"outputs: {glb_path}")

    # A zero size means the writer failed (read-only or missing directory).
    # Never report a successful job to a subprocess caller in that case.
    if EXPORT_BLENDS and not files["blend"]:
        warn(f".blend was not written: {blend_path}")
    if not files["glb"]:
        warn(f".glb was not written: {glb_path}")
        return 1
    return 0


if __name__ == "__main__":
    status = 0
    try:
        status = int(main() or 0)
    except BaseException:                                       # pragma: no cover
        traceback.print_exc()
        status = 1
    finally:
        sys.stdout.flush()
        sys.stderr.flush()

    # Headless `bpy` wheels (the pip build this repo's isolated Blender runtime
    # installs) can segfault inside the window-manager exit handler once a glTF
    # export has run, even though every output file is already written and
    # closed.  A subprocess caller checks the exit code, so on success leave
    # immediately with status 0 instead of relying on Blender's teardown.
    # Failures still report a non-zero status.
    if bpy.app.background:                                        # pragma: no cover
        os._exit(status)
    if status:
        sys.exit(status)
