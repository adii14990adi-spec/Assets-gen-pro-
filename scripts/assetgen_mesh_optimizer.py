# SPDX-License-Identifier: GPL-3.0-or-later
"""AI Mesh Optimizer — one-click clean / optimise / rig-ready for generated meshes.

A Blender 4.0+ add-on for the Asset Forge pipeline.  Meshes that come out of AI
generators (Tripo, Meshy, Rodin, Hunyuan3D, ...), Z-brushes exported at sculpt
resolution, or `.glb` files pulled from the ``public/assets/models`` gallery
share the same defects: welded-shut seams made of duplicate vertices, floating
dust, inverted shells, a triangle soup for topology and no usable UVs.  This
add-on fixes all of it from one N-panel, so the result can be dropped straight
into a rig.

Install
-------
* Blender  ->  Edit  ->  Preferences  ->  Add-ons  ->  Install...  ->  pick this
  file  ->  enable "AssetGenPro: AI Mesh Optimizer".
* Or paste it into a Text Editor and hit Run Script: ``register()`` is called at
  the bottom of the file, so the panel shows up in the 3D Viewport sidebar
  without restarting Blender.
* Headless smoke test, e.g. on a downloaded gallery asset (no UI needed)::

      blender --background some_ai_mesh.blend \
        --python scripts/assetgen_mesh_optimizer.py \
        --python-expr "import bpy; bpy.ops.assetgen.run_all(); \
    bpy.ops.wm.save_as_mainfile(filepath='cleaned.blend')"

Panel
-----
``3D Viewport``  ->  sidebar (N)  ->  **AssetGenPro** tab.  Every slider lives
on the scene (``Scene.assetgen``), so settings survive reloads and all buttons
read the same values you see.

Pipeline (each step is also a standalone button)
------------------------------------------------
0. ``Import & Setup``   target resolution, single-user mesh, transforms applied
                        (scale -> 1.0), origin to geometry / world / floor.
1. ``Clean Mesh``       ``bmesh.ops.remove_doubles`` (weld, default 0.0001),
                        degenerate-face dissolve, optional coplanar-triangle
                        dissolve and tri->quad conversion, loose vert/edge
                        removal, tiny-island removal, ``recalc_face_normals``.
2. ``Symmetrize``       ``bmesh.ops.symmetrize`` across X (or Y/Z) with a snap
                        distance -- AI meshes are rarely mirrored evenly.
3. ``Optimize``         Mode A Decimate (Collapse, user ratio or a target face
                        count) which keeps UVs and vertex groups, or Mode B
                        Voxel Remesh (default 0.02) for a clean uniform rigging
                        base, optionally followed by a decimate pass to a
                        triangle budget, with UV / vertex-colour recovery from
                        the untouched backup via a Data Transfer modifier.
4. ``Unwrap``           Smart UV Project (angle limit + island margin) or a
                        seam-respecting ``ANGLE_BASED`` unwrap for meshes that
                        already carry seams.

A hidden ``<name>_AI_SRC`` copy of the original mesh is kept when
``Keep Source Backup`` is on, which is what UV/colour transfer samples *and* what
you bake from if you want the AI texture on the retopologised mesh (see
``Bake Source To Slot`` in the panel's Utilities box, which wires the backup up
as a bake target without leaving the add-on).

Notes on robustness
-------------------
* All cleanup runs through ``bmesh`` rather than edit-mode operators, so the
  result never depends on which area happens to be under the mouse, and the
  whole add-on works in ``--background``.
* Modifier application goes through ``bpy.context.temp_override`` with an
  explicit ``selected_editable_objects`` list, because ``modifier_apply`` polls
  the active object and fails silently otherwise.
* Mesh data with more than one user is copied before anything is edited, and
  shape keys block destructive passes unless you explicitly allow dropping them
  (otherwise welding through a shape key would corrupt them).
"""

from __future__ import annotations

import math
import time

# `bpy` has to be imported before `bmesh` and `mathutils`: importing it is what
# registers the module path those two live on.  Sorting that block alphabetically
# (what isort would do) breaks the file with `ModuleNotFoundError: bmesh`, so the
# range is switched off for the linter instead of being reordered.

# isort: off
import bpy
import bmesh
from mathutils import Matrix, Vector
# isort: on

# Every value here has to be a *literal*: Blender's `addon_utils` does not
# import this file to list the add-on, it parses the module with `ast`, so a
# module-level constant or a call inside this dict makes the add-on silently
# disappear from Preferences -> Add-ons.  The URL below points at the README
# section describing the panel and feeds the entry's "Documentation" button.
bl_info = {
    "name": "AssetGenPro: AI Mesh Optimizer",
    "author": "Asset Forge",
    "version": (1, 0, 0),
    "blender": (4, 0, 0),
    "location": "3D Viewport > Sidebar (N) > AssetGenPro",
    "description": "One-click cleanup, retopology, UV unwrap and rig-ready "
                   "prep for AI-generated meshes (bmesh + modifiers only)",
    "doc_url": "https://github.com/adii14990adi-spec/Assets-gen-pro-"
               "#cleaning-up-an-ai-generated-mesh-optional-blender-add-on",
    "support": "COMMUNITY",
    "category": "Asset Forge",
}

LOG_TAG = "ASSETGEN"
BACKUP_SUFFIX = "_AI_SRC"
MAX_REPORT_LINES = 24


# --------------------------------------------------------------------------- #
# Small compatibility helpers
#
# Blender renames and re-types RNA properties between releases (this add-on
# targets 4.0+ but must not break on 4.1/4.2/4.3), so every write goes through
# `set_props`, which checks that the identifier exists *and* that the value is
# representable, and quietly skips the rest.  That is far cheaper than wrapping
# each call site in try/except.
# --------------------------------------------------------------------------- #
def prop_names(block) -> set[str]:
    return {prop.identifier for prop in block.bl_rna.properties}


def set_props(block, **values) -> list:
    """Assign only the properties *block* really has; return the identifiers applied."""
    applied = []
    rna = block.bl_rna.properties
    for key, value in values.items():
        prop = rna.get(key)
        if prop is None or prop.is_readonly or value is None:
            continue
        try:
            if prop.type == "ENUM":
                items = {item.identifier for item in prop.enum_items}
                wanted = value if isinstance(value, (set, frozenset)) else {value}
                if not wanted.issubset(items):
                    continue
            setattr(block, prop.identifier, value)
        except (TypeError, ValueError, RuntimeError):
            continue
        applied.append(prop.identifier)
    return applied


def op_parts(op_idname: str) -> tuple:
    """Split "bpy.ops.mesh.foo" / "mesh.foo" into ("mesh", "foo")."""
    cleaned = op_idname
    for prefix in ("bpy.ops.", "bpy.ops"):
        if cleaned.startswith(prefix):
            cleaned = cleaned[len(prefix):]
            break
    parts = [part for part in cleaned.split(".") if part]
    if len(parts) != 2:
        return "", ""
    return parts[0], parts[1]


def op_property_names(op_idname: str) -> dict:
    """The writable RNA properties of an operator, or {} when it is missing."""
    category, name = op_parts(op_idname)
    if not category:
        return {}
    try:
        op = getattr(getattr(bpy.ops, category, None), name, None)
        return {prop.identifier: prop for prop in op.get_rna_type().properties if not prop.is_readonly}
    except (AttributeError, KeyError, RuntimeError, TypeError):    # pragma: no cover
        return {}


def op_kwargs(op_idname: str, wanted: dict) -> dict:
    """Filter *wanted* down to the properties operator *op_idname* accepts.

    Exporters and bmesh operators keep renaming and re-typing their arguments
    between Blender releases, so passing a dict straight through is a guaranteed
    traceback on some version.  Unknown or type-mismatched keys are dropped.
    """
    props = op_property_names(op_idname)
    clean: dict = {}
    for key, value in wanted.items():
        prop = props.get(key)
        if prop is None:
            continue
        if prop.type == "ENUM":
            allowed = {item.identifier for item in prop.enum_items}
            if not isinstance(value, (set, frozenset)) and value not in allowed:
                continue
            if isinstance(value, (set, frozenset)) and not set(value).issubset(allowed):
                continue
        clean[key] = value
    return clean


def run_op(op_idname: str, **wanted) -> bool:
    """Call a Blender operator with whatever subset of *wanted* it supports."""
    category, name = op_parts(op_idname)
    op = getattr(getattr(bpy.ops, category, None), name, None)
    if op is None:
        return False
    kwargs = op_kwargs(op_idname, wanted)
    try:
        op(**kwargs)
    except (RuntimeError, TypeError) as exc:                       # pragma: no cover
        log(f"{op_idname} skipped: {exc}")
        return False
    return True


def log(message: str) -> None:
    print(f"{LOG_TAG}: {message}")


class ObjectMode:
    """Force OBJECT mode for the duration of a block, restoring it afterwards.

    Mesh-level bmesh edits do not need edit mode at all, but modifier
    application and `transform_apply` do require it, and a user pressing a panel
    button while sitting in Edit mode must get the same result.
    """

    def __init__(self, objects=()):
        self.previous = ""
        self.objects = tuple(objects)

    def __enter__(self):
        self.previous = bpy.context.mode
        if self.previous != "OBJECT":
            try:
                bpy.ops.object.mode_set(mode="OBJECT")
            except (RuntimeError, TypeError):                     # pragma: no cover
                pass
        return self

    def __exit__(self, exc_type, exc, tb):
        if self.previous in {"EDIT_MESH", "EDIT"} and not exc_type:
            target = next((ob for ob in self.objects if ob), None) or bpy.context.active_object
            if target is not None:
                try:
                    bpy.context.view_layer.objects.active = target
                    bpy.ops.object.mode_set(mode="EDIT")
                except (RuntimeError, TypeError):                 # pragma: no cover
                    pass
        return False


def make_single_user(obj: bpy.types.Object) -> bool:
    """Give *obj* private mesh data; returns True when a copy had to be made."""
    mesh = obj.data
    if mesh is None or mesh.users == 1:
        return False
    if mesh.shape_keys is not None:
        # Copying a mesh that owns shape keys would orphan the key block; the
        # safe move is to refuse the shared-data optimisation entirely.
        return False
    clone = mesh.copy()
    clone.name = mesh.name + "_local"
    obj.data = clone
    return True


def resolve_targets(context, prefer_selection=True) -> list:
    """The meshes this add-on should work on.

    Selected meshes first (so multi-object batch jobs are one click), then the
    active object, then -- only when the scene holds a single mesh -- that mesh,
    because a freshly imported AI asset is usually the only thing in the file.
    """
    meshes = [ob for ob in context.selected_objects if ob.type == "MESH" and ob.visible_get()]
    if not prefer_selection:
        meshes = []
    if not meshes:
        active = context.active_object
        if active is not None and active.type == "MESH" and active.visible_get():
            meshes = [active]
    if not meshes:
        candidates = [ob for ob in context.view_layer.objects
                      if ob.type == "MESH" and ob.visible_get() and not ob.name.endswith(BACKUP_SUFFIX)]
        if len(candidates) == 1:
            meshes = candidates
    # de-duplicate, keep selection order
    seen, out = set(), []
    for ob in meshes:
        if ob.name not in seen:
            seen.add(ob.name)
            out.append(ob)
    return out


def mesh_stats(obj: bpy.types.Object) -> dict:
    """Everything the panel reports per object; read-only and cheap enough to call often.

    ``MeshEdge`` has no ``link_faces`` accessor (only ``bmesh`` does), so edge
    valence is tallied from the loop table instead.  That is also the only way to
    tell a boundary edge (one face) from a non-manifold one (three or more).
    """
    mesh = obj.data
    verts, polys, loops, edges = mesh.vertices, mesh.polygons, mesh.loops, mesh.edges
    tris = sum(max(3, len(poly.vertices) - 2) for poly in polys)
    face_counts: dict = {}
    for poly in polys:
        face_counts[len(poly.vertices)] = face_counts.get(len(poly.vertices), 0) + 1

    edge_face_uses: dict = {}
    for poly in polys:
        for loop_index in poly.loop_indices:
            key = (loops[loop_index].edge_index)
            edge_face_uses[key] = edge_face_uses.get(key, 0) + 1
    non_manifold = sum(1 for count in edge_face_uses.values() if count > 2)
    boundary = sum(1 for count in edge_face_uses.values() if count < 2)
    degenerate = sum(1 for poly in polys if poly.area <= 1e-9)
    loose_edges = sum(1 for edge in edges if edge.is_loose)

    world = [obj.matrix_world @ Vector(corner) for corner in obj.bound_box]
    size = [round(max(c[i] for c in world) - min(c[i] for c in world), 4) for i in range(3)]
    return {
        "name": obj.name,
        "verts": len(verts),
        "faces": len(polys),
        "tris": int(tris),
        "edges": len(edges),
        "loops": len(loops),
        "quads": face_counts.get(4, 0),
        "tris_only": face_counts.get(3, 0),
        "ngons": sum(count for corners, count in face_counts.items() if corners > 4),
        "uv_layers": len(mesh.uv_layers),
        "vcols": len(mesh.color_attributes),
        "materials": len(mesh.materials),
        "vgroups": len(obj.vertex_groups),
        "modifiers": len(obj.modifiers),
        "non_manifold_edges": non_manifold,
        "boundary_edges": boundary,
        "loose_edges": loose_edges,
        "degenerate_faces": degenerate,
        "shape_keys": 0 if mesh.shape_keys is None else len(mesh.shape_keys.key_blocks),
        "size": size,
        "scale": tuple(round(value, 4) for value in obj.scale),
    }


def format_stats(stats: dict) -> str:
    return (f"{stats['name']}: {stats['verts']:,}v / {stats['faces']:,}f / "
            f"{stats['tris']:,} tris | uv={stats['uv_layers']} mat={stats['materials']} "
            f"vg={stats['vgroups']} nonmanifold={stats['non_manifold_edges']} "
            f"degenerate={stats['degenerate_faces']}")


def island_sizes(bm: bmesh.types.BMesh) -> list:
    """Connected components as ``(verts, face_indices)`` pairs.

    ``bmesh.ops.connected_components_get`` was removed in 4.x, so the flood fill
    lives here.  Two hazards specific to cleaning up generated meshes:

    * stale elements: after a pass such as ``remove_doubles`` the bmesh still
      holds the verts it merged away, and seeding from one of those drags whole
      real islands into the "delete me" bucket;
    * never key geometry by ``id()``: ``BMVert``/``BMFace`` wrappers are created
      on access, so two visits hand out different ids for the same face and a
      colliding id silently merges or splits counts.  Indices are stable.
    """
    bm.verts.ensure_lookup_table()
    bm.faces.ensure_lookup_table()
    live_verts = [vert for vert in bm.verts if vert.is_valid and vert.link_faces]
    usable = {vert.index for vert in live_verts}
    seen: set = set()
    islands = []
    for start_vert in live_verts:
        if start_vert.index in seen:
            continue
        stack = [start_vert]
        seen.add(start_vert.index)
        island, faces = [], set()
        while stack:
            vert = stack.pop()
            island.append(vert)
            for face in vert.link_faces:
                if not face.is_valid:
                    continue
                faces.add(face.index)
                for neighbour in face.verts:
                    key = neighbour.index
                    if neighbour.is_valid and key in usable and key not in seen:
                        seen.add(key)
                        stack.append(neighbour)
        islands.append((island, faces))
    return islands


# --------------------------------------------------------------------------- #
# Scene settings (the panel's sliders) and the report buffer
# --------------------------------------------------------------------------- #
class ASSETGEN_LT_line(bpy.types.PropertyGroup):
    """One line of the last run's report, shown at the bottom of the panel."""

    text: bpy.props.StringProperty(name="Line", default="")       # type: ignore


class ASSETGEN_PG_settings(bpy.types.PropertyGroup):
    """Every knob the operators read, stored on the scene so it persists."""

    # -- 0. import & setup ---------------------------------------------------
    apply_transforms: bpy.props.BoolProperty(
        name="Apply Transforms", default=True,
        description="Apply location / rotation / scale so the scale is 1.0 and "
                    "voxel sizes and weld distances mean what they say")
    origin_mode: bpy.props.EnumProperty(
        name="Origin", default="GEOMETRY",
        items=[("GEOMETRY", "Geometry to Origin", "Move the origin to the mesh bounding-box centre"),
               ("WORLD", "World Origin", "Put the origin at the world origin (asset drop-in for a rig root)"),
               ("FLOOR", "Floor Centre", "Origin at the mesh centre on the world Z=0 floor plane"),
               ("CURSOR", "3D Cursor", "Move the origin to the current 3D cursor")],
        description="Where the object origin ends up")
    include_children: bpy.props.BoolProperty(
        name="Whole Hierarchy", default=False,
        description="Also process the children of the selected objects (AI exports "
                    "often arrive as a parent empty with several mesh parts)")

    # -- 1. cleanup ----------------------------------------------------------
    weld_threshold: bpy.props.FloatProperty(
        name="Weld Distance", default=0.0001, min=0.0, max=0.05, step=0.001,
        precision=5, soft_max=0.005,
        description="Merge by distance: vertices closer than this become one "
                    "(AI meshes ship broken seams a few microns wide)")
    dissolve_degenerate: bpy.props.BoolProperty(
        name="Dissolve Degenerate", default=True,
        description="Remove zero-area faces and their sliver edges")
    coplanar_angle: bpy.props.FloatProperty(
        name="Planar Threshold", default=0.0, min=0.0, max=30.0, step=1.0, unit="ROTATION",
        description="Dissolve interior edges between coplanar faces (triangle soup -> "
                    "quads/ngons). 0 = off")
    tri_to_quad: bpy.props.BoolProperty(
        name="Triangles to Quads", default=False,
        description="Pair up adjacent triangles into quads (only helps clean grids)")
    delete_loose: bpy.props.BoolProperty(
        name="Delete Loose", default=True, description="Remove unattached vertices and edges")
    min_island_faces: bpy.props.IntProperty(
        name="Min Island Faces", default=0, min=0, max=10000,
        description="Delete floating shells smaller than this many faces (0 = keep everything)")
    recalc_normals: bpy.props.BoolProperty(
        name="Recalculate Normals", default=True, description="Point every face outward")
    flip_normals: bpy.props.BoolProperty(
        name="Flip After Recalc", default=False,
        description="Negate normals after recalculating: for assets that are consistently inside-out")
    mark_seams_off: bpy.props.BoolProperty(
        name="Clear Custom Split Normals", default=True,
        description="Drop stale auto-small/normal edits left by the generator so the "
                    "recalculated normals are what you actually see")

    # -- 2. symmetry ---------------------------------------------------------
    sym_direction: bpy.props.EnumProperty(
        name="Direction", default="-X",
        items=[("-X", "-X", "Replace the +X side with the mirrored -X side"),
               ("X", "+X", "Replace the -X side with the mirrored +X side"),
               ("-Y", "-Y", "Front/back mirror, keeping the -Y side"),
               ("Y", "+Y", "Front/back mirror, keeping the +Y side"),
               ("-Z", "-Z", "Top/bottom mirror, keeping the -Z side"),
               ("Z", "+Z", "Top/bottom mirror, keeping the +Z side")],
        description="Same semantics as Edit > Mesh > Symmetrize: the axis and side "
                    "whose geometry is rebuilt from the other half")
    sym_dist: bpy.props.FloatProperty(
        name="Snap Distance", default=0.0005, min=0.0, max=0.05, step=0.001, precision=5,
        soft_max=0.005, description="Weld distance used to stitch the mirrored seam closed")
    sym_center_x: bpy.props.BoolProperty(
        name="Centre on Axis", default=True,
        description="Snap the mirror plane to the bounding-box centre instead of the object origin")

    # -- 3. topology ---------------------------------------------------------
    method: bpy.props.EnumProperty(
        name="Method", default="DECIMATE",
        items=[("DECIMATE", "Decimate (Keep Texture)", "Collapse: keeps UVs, materials and skin weights"),
               ("REMESH", "Voxel Remesh (Clean Base)", "Uniform quads for rigging; needs UV transfer afterwards")])
    decimate_ratio: bpy.props.FloatProperty(
        name="Ratio", default=0.5, min=0.001, max=1.0, step=0.01,
        description="Fraction of faces to keep")
    use_face_target: bpy.props.BoolProperty(
        name="Target Face Count", default=False,
        description="Ignore the ratio and collapse to an exact face budget instead")
    target_faces: bpy.props.IntProperty(
        name="Faces", default=1500, min=4, max=2_000_000,
        description="Face budget for the target mode and for the post-remesh pass")
    decimate_triangulate: bpy.props.BoolProperty(
        name="Triangulate Output", default=True,
        description="Emit only triangles: what a game engine wants and what makes the "
                    "face count equal the triangle count")
    remesh_preserve_colors: bpy.props.BoolProperty(
        name="Preserve Colours", default=True,
        description="Voxel mode interpolates vertex colours; leave on for vertex-colour assets")
    voxel_size: bpy.props.FloatProperty(
        name="Voxel Size", default=0.02, min=0.0001, max=1.0, step=0.01, precision=4,
        soft_max=0.2, description="Remesh voxel edge in metres: 0.02 is a clean rig base "
                                   "for a 1.7 m character")
    remesh_smooth_shade: bpy.props.BoolProperty(
        name="Smooth Shade Result", default=False,
        description="Flat (faceted) shading stays on so the low-poly silhouette reads crisp")
    remesh_remove_disconnected: bpy.props.BoolProperty(
        name="Drop Disconnected Parts", default=True,
        description="Voxel remesh keeps only the largest shell - ideal for AI dust")
    remesh_decimate_to_target: bpy.props.BoolProperty(
        name="Decimate To Budget", default=True,
        description="Voxel remesh explodes face counts; collapse the result to the target above")
    transfer_uvs: bpy.props.BoolProperty(
        name="Transfer UVs", default=True,
        description="Recover UVs on the new topology by sampling the untouched backup "
                    "(nearest-face interpolation). Required to bake the old texture onto it")
    transfer_vcols: bpy.props.BoolProperty(
        name="Transfer Vertex Colours", default=True,
        description="Same trick for colour attributes, which this repo's generators use instead of textures")
    shade_angle: bpy.props.FloatProperty(
        name="Auto Smooth Angle", default=30.0, min=0.0, max=180.0, step=1.0,
        description="Smooth-by-angle threshold applied when Smooth Shade Result is on")

    # -- 4. UV ---------------------------------------------------------------
    uv_method: bpy.props.EnumProperty(
        name="Method", default="SMART",
        items=[("SMART", "Smart UV Project", "Angle-limited unwrap, no seams required"),
               ("ANGLE", "Unwrap (Respect Seams)", "Angle-based unwrap; use when the mesh already has seams")],
        description="How the atlas is built after the topology changed")
    uv_angle_limit: bpy.props.FloatProperty(
        name="Angle Limit", default=66.0, min=1.0, max=180.0, step=1.0,
        description="Neighbouring faces that bend past this angle start a new island")
    uv_margin: bpy.props.FloatProperty(
        name="Island Margin", default=0.02, min=0.0, max=0.5, step=0.001, precision=4,
        soft_max=0.05, description="UV-space padding between islands: stops texture bleed at mip levels")
    uv_new_layer: bpy.props.BoolProperty(
        name="New UV Layer", default=False,
        description="Write into a second UV map instead of overwriting UVMap, so the "
                    "generator's original atlas survives for reference")

    # -- safety / bookkeeping ------------------------------------------------
    keep_backup: bpy.props.BoolProperty(
        name="Keep Source Backup", default=True,
        description="Leave a hidden copy of the untouched mesh next to the object; it is the "
                    "transfer and bake source")
    allow_skinned: bpy.props.BoolProperty(
        name="Allow On Skinned Mesh", default=False,
        description="Run destructive passes even when the mesh carries skin weights. Voxel "
                    "remesh throws them away, so this is off by default")
    allow_shape_key_drop: bpy.props.BoolProperty(
        name="Allow Dropping Shape Keys", default=False,
        description="Welding or remeshing a mesh with shape keys requires clearing them first")
    verbose_console: bpy.props.BoolProperty(
        name="Console Log", default=True, description="Print every pass to the system console")

    # -- one-click pipeline --------------------------------------------------
    step_setup: bpy.props.BoolProperty(name="Step 0 - Setup", default=True,
                                      description="Apply transforms and re-seat the origin")
    step_clean: bpy.props.BoolProperty(name="Step 1 - Clean", default=True,
                                       description="Weld, dissolve, delete loose, recalculate normals")
    step_symmetrize: bpy.props.BoolProperty(name="Step 2 - Symmetrize", default=False,
                                            description="Rebuild one half from the other")
    step_optimize: bpy.props.BoolProperty(name="Step 3 - Optimize", default=True,
                                          description="Decimate or voxel remesh")
    step_unwrap: bpy.props.BoolProperty(name="Step 4 - Unwrap", default=True,
                                        description="Rebuild the UV atlas on the new topology")

    report_lines: bpy.props.CollectionProperty(type=ASSETGEN_LT_line)       # type: ignore
    last_run: bpy.props.StringProperty(name="Last Run", default="", options={"HIDDEN"})       # type: ignore


# --------------------------------------------------------------------------- #
# Report buffer -> panel + console
# --------------------------------------------------------------------------- #
def report(context, lines, *, level="INFO", tag="run"):
    """Push *lines* into the panel report and, when enabled, the console."""
    settings = getattr(context.scene, "assetgen", None)
    if settings is not None:
        settings.report_lines.clear()
        for line in lines:
            settings.report_lines.add().text = line
        settings.last_run = f"{tag} @ {time.strftime('%H:%M:%S')}"
    if settings is None or settings.verbose_console:
        for line in lines:
            print(f"{LOG_TAG}: {line}")


def stats_block(obj: bpy.types.Object) -> list:
    st = mesh_stats(obj)
    return [
        f"{st['name']}: {st['verts']:,} v / {st['faces']:,} f / {st['tris']:,} tris "
        f"(quads {st['quads']:,}, ngons {st['ngons']:,})",
        f"  size {st['size'][0]:.3f} x {st['size'][1]:.3f} x {st['size'][2]:.3f} m"
        f"  |  scale {st['scale'][0]:g}, {st['scale'][1]:g}, {st['scale'][2]:g}",
        f"  uv {st['uv_layers']}  |  colour {st['vcols']}  |  materials {st['materials']}  |  "
        f"vgroups {st['vgroups']}  |  shape keys {st['shape_keys']}",
        f"  non-manifold {st['non_manifold_edges']}  |  loose {st['loose_edges']}  |  "
        f"zero-area faces {st['degenerate_faces']}",
    ]


# --------------------------------------------------------------------------- #
# Object plumbing: refusal guards, backups, modifier application, transfers
# --------------------------------------------------------------------------- #
def is_skinned(obj: bpy.types.Object) -> bool:
    """True when the mesh looks rigged, i.e. it has skin weights to lose."""
    if obj.vertex_groups:
        return True
    return any(mod.type == "ARMATURE" for mod in obj.modifiers)


def refusal_reason(obj: bpy.types.Object, settings, *, destructive: bool) -> str:
    """Why *obj* must not be edited right now, or "" when it may be."""
    if obj.type != "MESH" or obj.data is None:
        return "not a mesh"
    if not obj.visible_get():
        return "hidden in the viewport"
    if not destructive:
        return ""
    if obj.data.shape_keys is not None and not settings.allow_shape_key_drop:
        return "has shape keys (tick 'Allow Dropping Shape Keys' to weld/remesh anyway)"
    if is_skinned(obj) and not settings.allow_skinned:
        return "is skinned (tick 'Allow On Skinned Mesh' to accept losing the weights)"
    return ""


def expand_hierarchy(context, targets: list) -> list:
    if not targets:
        return []
    first = targets[0]
    if getattr(context.scene.assetgen, "include_children", False) and first.parent is None:
        extra = [ob for root in targets for ob in root.children_recursive if ob.type == "MESH"]
        seen = {ob.name for ob in targets}
        for ob in extra:
            if ob.name not in seen:
                seen.add(ob.name)
                targets.append(ob)
    return targets


def make_backup(obj: bpy.types.Object, settings) -> bpy.types.Object | None:
    """Hidden single-user copy of the pristine mesh: transfer + bake source."""
    if not settings.keep_backup:
        return None
    existing = bpy.data.objects.get(obj.name + BACKUP_SUFFIX)
    if existing is not None:
        return existing                      # keep the truly original, not a re-copy
    clone = obj.copy()
    clone.data = obj.data.copy()
    clone.name = obj.name + BACKUP_SUFFIX
    clone.modifiers.clear()
    clone.parent = None
    clone.vertex_groups.clear()
    clone.hide_render = True
    target = next(iter(obj.users_collection), None) or bpy.context.scene.collection
    target.objects.link(clone)
    clone.hide_set(True)                 # needs to be in the view layer first
    return clone


def apply_modifier(obj: bpy.types.Object, mod) -> bool:
    """Apply *mod* without depending on which area is under the mouse.

    ``modifier_apply`` polls the active object, so the override carries it plus an
    explicit selection.  Two hazards are handled here:

    * a modifier that errors out (a decimate on a 3-face mesh, say) can leave the
      ``Modifier`` wrapper pointing at freed memory, so its name is captured
      before the call and every later access is guarded;
    * the fallback that bakes through the depsgraph is only correct when this is
      the object's sole modifier, and only if the evaluation produced geometry.
    """
    name = str(mod.name)
    if name not in [str(entry.name) for entry in obj.modifiers]:
        return False
    try:
        with bpy.context.temp_override(object=obj, active_object=obj,
                                       selected_editable_objects=[obj]):
            bpy.ops.object.modifier_apply(modifier=name)
        return True
    except (RuntimeError, TypeError, ReferenceError):              # pragma: no cover
        pass

    if len(obj.modifiers) != 1:
        return False
    deps = bpy.context.evaluated_depsgraph_get()
    try:
        evaluated = obj.evaluated_get(deps)
        baked = bpy.data.meshes.new_from_object(evaluated, preserve_all_data_layers=True,
                                               depsgraph=deps)
        if not baked.polygons:
            raise RuntimeError("evaluation produced no geometry")
    except (RuntimeError, TypeError):                               # pragma: no cover
        if baked is not None and baked.users == 0:
            bpy.data.meshes.remove(baked)
        return False
    old_mesh = obj.data
    baked.user_clear()
    obj.data = baked
    if old_mesh.users == 0:
        bpy.data.meshes.remove(old_mesh)
    obj.modifiers.clear()
    return True


def drop_modifier(obj: bpy.types.Object, name: str) -> None:
    """Remove a leftover modifier by name, never through a possibly stale wrapper."""
    for entry in list(obj.modifiers):
        if entry.name == name:
            obj.modifiers.remove(entry)


def _match_layer(dst_layers, src_name: str, preferred: str):
    """Return a destination layer named like *src_name*, creating it if needed."""
    for layer in dst_layers:
        if layer.name == src_name:
            return layer
    if preferred == "new":
        try:
            return dst_layers.new(name=src_name)
        except (RuntimeError, TypeError):                        # pragma: no cover
            return None
    return None


def transfer_attributes(obj: bpy.types.Object, backup, settings) -> list:
    """Recover UVs / vertex colours on new topology by sampling *backup*.

    Nearest-polygon loop mapping is what the Data Transfer modifier is for: the
    destination loop inherits the attributes of the source face its centre falls
    inside, which is exactly the "bake the old texture onto the new mesh"
    plumbing an AI asset needs after a voxel remesh.
    """
    notes: list = []
    if backup is None or obj.data is None:
        return ["transfer skipped: no source backup"]
    src, dst = backup.data, obj.data

    if settings.transfer_uvs and len(src.uv_layers):
        name = src.uv_layers[0].name
        if _match_layer(dst.uv_layers, name, "new") is None:
            notes.append("transfer skipped: could not create the destination UV layer")
        else:
            mod = obj.modifiers.new("AssetGen Transfer", "DATA_TRANSFER")
            set_props(mod, object=backup, use_loop_data=True, data_types_loops={"UV"},
                      loop_mapping="NEAREST_POLY", use_vert_data=False, use_poly_data=False,
                      use_edge_data=False, mix_mode="REPLACE")
            notes.append("UVs transferred from " + backup.name if apply_modifier(obj, mod)
                         else "UV transfer failed")
            drop_modifier(obj, "AssetGen Transfer")

    if settings.transfer_vcols and len(src.color_attributes):
        for attr in list(src.color_attributes):
            target = next((entry for entry in dst.color_attributes if entry.name == attr.name), None)
            if target is None:
                try:                                  # colour layers need type + domain
                    target = dst.color_attributes.new(name=attr.name, type=attr.data_type,
                                                       domain=attr.domain)
                except (RuntimeError, TypeError):      # pragma: no cover
                    continue
            mod = obj.modifiers.new("AssetGen Transfer", "DATA_TRANSFER")
            set_props(mod, object=backup, use_vert_data=True, data_types_verts={"COLOR_VERTEX"},
                      vert_mapping="NEAREST", use_loop_data=False, use_poly_data=False,
                      use_edge_data=False, mix_mode="REPLACE")
            ok = apply_modifier(obj, mod)
            notes.append(f"colour '{attr.name}' transferred" if ok else f"colour '{attr.name}' transfer failed")
            drop_modifier(obj, "AssetGen Transfer")
    return notes or ["nothing to transfer"]


def apply_transforms(obj: bpy.types.Object) -> bool:
    with bpy.context.temp_override(object=obj, active_object=obj, selected_editable_objects=[obj]):
        return run_op("bpy.ops.object.transform_apply", location=True, rotation=True, scale=True,
                      properties=False, isolate_users=False)


def shift_origin(obj: bpy.types.Object, mode: str) -> str:
    """Move the object origin; returns a one-line description for the report."""
    if mode in {"GEOMETRY", "CURSOR"}:
        op_type = "ORIGIN_GEOMETRY" if mode == "GEOMETRY" else "ORIGIN_CURSOR"
        with bpy.context.temp_override(object=obj, active_object=obj, selected_editable_objects=[obj]):
            if run_op("bpy.ops.object.origin_set", type=op_type,
                      **({"center": "BOUNDS"} if mode == "GEOMETRY" else {})):
                return "origin to " + ("geometry (bounds centre)" if mode == "GEOMETRY" else "3D cursor")
        return "origin untouched (operator unavailable)"

    # WORLD / FLOOR leave the mesh exactly where it is and re-seat the origin, so
    # a rig root at (0, 0, 0) still lines up with the exported asset.
    corners = [obj.matrix_world @ Vector(corner) for corner in obj.bound_box]
    centre_x = sum(corner.x for corner in corners) / 8.0
    centre_y = sum(corner.y for corner in corners) / 8.0
    floor_z = min(corner.z for corner in corners)
    if mode == "WORLD":
        target = Vector((0.0, 0.0, 0.0))
    else:
        # the mesh's own lowest point: the feet of a character that was exported
        # floating 40 cm above the ground still end up with their origin on it
        target = Vector((centre_x, centre_y, floor_z))

    delta_world = target - obj.matrix_world.translation
    local_delta = obj.matrix_world.inverted().to_3x3() @ (-delta_world)
    shift = Matrix.Translation(local_delta)
    obj.data.transform(shift)
    if obj.data.shape_keys is not None:
        for key in obj.data.shape_keys.key_blocks:
            key.data.transform(shift)
    obj.matrix_basis.translation += delta_world
    obj.matrix_world.update()
    obj.data.update()
    return f"origin to {mode.lower()}: ({target.x:.3f}, {target.y:.3f}, {target.z:.3f})"


def shade_object(obj: bpy.types.Object, smooth: bool, angle_deg: float) -> str:
    """Flat faceting is the Asset Forge look, so smoothing is opt-in."""
    mesh = obj.data
    for poly in mesh.polygons:
        poly.use_smooth = bool(smooth)
    if smooth:
        bpy.context.view_layer.objects.active = obj
        with bpy.context.temp_override(object=obj, active_object=obj, selected_editable_objects=[obj]):
            if not run_op("bpy.ops.object.shade_smooth_by_angle", angle=math.radians(angle_deg),
                          keep_sharp_edges=True):
                run_op("bpy.ops.object.shade_auto_smooth", angle=math.radians(angle_deg))
        return f"smooth shading, sharp edges past {angle_deg:.0f} deg"
    return "flat shading"


# --------------------------------------------------------------------------- #
# bmesh passes
#
# Each one mutates the live bmesh and records what it did in `counts`, so the
# panel can print "welded 1,204 verts, dropped 38 loose" instead of a bare
# "success".  Everything here is context-free: no edit mode, no area overrides,
# which is what makes the add-on usable from --background and batch scripts.
# --------------------------------------------------------------------------- #
def live(seq) -> list:
    """Filter out geometry freed by an earlier pass in the same edit."""
    return [element for element in seq if element.is_valid]


def pass_weld(bm, settings, counts) -> None:
    if settings.weld_threshold <= 0.0:
        return
    before = len(live(bm.verts))
    bmesh.ops.remove_doubles(bm, verts=live(bm.verts), dist=settings.weld_threshold)
    counts["welded"] = before - len(live(bm.verts))
    if settings.dissolve_degenerate:
        faces_before = len(live(bm.faces))
        bmesh.ops.dissolve_degenerate(bm, dist=max(settings.weld_threshold, 1e-7), edges=live(bm.edges))
        counts["degenerate"] = faces_before - len(live(bm.faces))


def pass_coplanar(bm, settings, counts) -> None:
    """Triangle soup -> quads/ngons, without crossing materials or UV seams."""
    if settings.coplanar_angle <= 0.0:
        return
    faces_before = len(live(bm.faces))
    try:
        bmesh.ops.dissolve_limit(bm, angle_limit=math.radians(settings.coplanar_angle),
                                 verts=live(bm.verts), edges=live(bm.edges),
                                 use_dissolve_boundaries=False,
                                 delimit={"MATERIAL", "SEAM", "UV"})
    except (TypeError, RuntimeError):                            # pragma: no cover
        bmesh.ops.dissolve_limit(bm, angle_limit=math.radians(settings.coplanar_angle),
                                 verts=live(bm.verts), edges=live(bm.edges))
    counts["coplanar"] = faces_before - len(live(bm.faces))


def pass_loose(bm, settings, counts) -> None:
    if not settings.delete_loose:
        return
    removed_verts = removed_edges = 0
    for _ in range(2):                  # freeing an edge can leave its verts loose
        loose_verts = [v for v in bm.verts if v.is_valid and not v.link_faces]
        if not loose_verts:
            break
        bmesh.ops.delete(bm, geom=loose_verts, context="VERTS")
        removed_verts += len(loose_verts)
    loose_edges = [e for e in bm.edges if e.is_valid and not e.link_faces]
    if loose_edges:
        bmesh.ops.delete(bm, geom=loose_edges, context="EDGES")
        removed_edges = len(loose_edges)
        loose_verts = [v for v in bm.verts if v.is_valid and not v.link_faces]
        if loose_verts:
            bmesh.ops.delete(bm, geom=loose_verts, context="VERTS")
            removed_verts += len(loose_verts)
    counts["loose_verts"], counts["loose_edges"] = removed_verts, removed_edges


def pass_islands(bm, settings, counts) -> None:
    """Drop AI dust: floating shells below a face count, keeping the real body."""
    if settings.min_island_faces <= 0:
        return
    doomed: list = []
    dropped_islands = 0
    for island, faces in island_sizes(bm):
        if len(faces) < settings.min_island_faces:
            doomed.extend(vert for vert in island if vert.is_valid)
            dropped_islands += 1
    if doomed:
        bmesh.ops.delete(bm, geom=doomed, context="VERTS")
    counts["island_verts"] = len(doomed)
    if dropped_islands:
        counts["islands"] = dropped_islands


def pass_normals(bm, settings, counts) -> None:
    """Recalculate outward-consistent normals, then honour the manual flip.

    ``recalc_face_normals`` only guarantees *consistency* between neighbours, so
    a mesh whose shell is uniformly inside-out comes back still inside-out.  The
    signed volume tells the two cases apart, which is the difference between a
    model that renders and one that renders as an empty hole in engines with
    back-face culling.
    """
    faces = live(bm.faces)
    if settings.recalc_normals and faces:
        bmesh.ops.recalc_face_normals(bm, faces=faces)
        counts["recalculated"] = len(faces)
        try:
            volume = bm.calc_volume(signed=True)
        except (ValueError, RuntimeError):                         # pragma: no cover
            volume = 0.0
        if volume < 0.0:
            bmesh.ops.reverse_faces(bm, faces=live(bm.faces))
            counts["reversed for outward"] = len(faces)
    if settings.flip_normals:
        bmesh.ops.reverse_faces(bm, faces=live(bm.faces))
        counts["flipped"] = len(live(bm.faces))


def symmetrize_bm(bm, direction: str, dist: float, centre_on_axis: bool) -> dict:
    """Mirror one half across the object axis, welding the stitch seam.

    Blender 4.2 replaced ``plane_no`` / ``plane_co`` with ``direction``, so both
    spellings are attempted; ``{}`` comes back when the build offers neither.
    """
    axis = direction.lstrip("-").upper()
    if centre_on_axis:
        # `bmesh.ops.symmetrize` always mirrors across the mesh's own origin, so
        # a model exported off-centre has to be nudged first: shift, mirror,
        # shift back.  Without this an AI mesh whose median is 3 cm off-axis
        # would get two overlapping halves instead of a mirrored body.
        coords = [vert.co for vert in live(bm.verts)]
        if coords:
            index = {"X": 0, "Y": 1, "Z": 2}[axis]
            values = [getattr(co, "xyz"[index]) for co in coords]
            offset = (min(values) + max(values)) / 2.0
            if abs(offset) > dist:
                vector = Vector((0.0, 0.0, 0.0))
                setattr(vector, "xyz"[index], -offset)
                bmesh.ops.translate(bm, verts=live(bm.verts), vec=vector)
                bm.verts.ensure_lookup_table()
                centre_shift = -offset
            else:
                centre_shift = 0.0
        else:
            centre_shift = 0.0
    else:
        centre_shift = 0.0

    geometry = live(bm.verts) + live(bm.edges) + live(bm.faces)
    before = len(live(bm.faces))
    try:
        result = bmesh.ops.symmetrize(bm, input=geometry, direction=direction, dist=dist)
        new_geom = result.get("geom", []) if isinstance(result, dict) else []
    except TypeError:                                             # Blender <= 4.1
        try:
            plane_no = Vector((1.0, 0.0, 0.0) if axis == "X" else
                              (0.0, 1.0, 0.0) if axis == "Y" else (0.0, 0.0, 1.0))
            bmesh.ops.symmetrize(bm, geom=geometry, plane_no=plane_no, plane_co=Vector((0, 0, 0)),
                                 use_no_overlap=True, use_seam=True)
            new_geom = []
        except (TypeError, RuntimeError):
            return {"error": "no symmetrize operator in this Blender build"}
    if centre_shift:
        restore = Vector((0.0, 0.0, 0.0))
        setattr(restore, "xyz"[{"X": 0, "Y": 1, "Z": 2}[axis]], -centre_shift)
        bmesh.ops.translate(bm, verts=live(bm.verts), vec=restore)
    return {"faces_before": before, "faces_after": len(live(bm.faces)), "created": len(new_geom)}


def clear_split_normals(obj: bpy.types.Object) -> bool:
    """Drop stale custom split normals so the recalculation is actually visible."""
    mesh = obj.data
    if not getattr(mesh, "has_custom_normals", False):
        return False
    try:
        bpy.ops.object.mode_set(mode="EDIT")
        bpy.ops.mesh.select_all(action="SELECT")
        bpy.ops.mesh.customdata_custom_splitnormals_clear()
    except (RuntimeError, TypeError):                              # pragma: no cover
        return False
    finally:
        try:
            bpy.ops.object.mode_set(mode="OBJECT")
        except (RuntimeError, TypeError):                          # pragma: no cover
            pass
    return True


def tris_to_quads(obj: bpy.types.Object) -> bool:
    """`Edit > Triangulate`'s inverse; needs the bundled loop-tools add-on."""
    try:
        bpy.ops.object.mode_set(mode="EDIT")
        bpy.ops.mesh.select_all(action="SELECT")
        ok = run_op("bpy.ops.mesh.tris_convert_to_quads", face_threshold=math.radians(1.0),
                    shape_threshold=math.radians(1.0))
    except (RuntimeError, TypeError):                              # pragma: no cover
        ok = False
    finally:
        try:
            bpy.ops.object.mode_set(mode="OBJECT")
        except (RuntimeError, TypeError):                          # pragma: no cover
            pass
    return bool(ok)


def smart_unwrap(obj: bpy.types.Object, settings) -> str:
    """Build the atlas the bake pass needs, into the layer the user picked."""
    mesh = obj.data
    name = "AssetGenUV" if settings.uv_new_layer else "UVMap"
    layer = next((uv for uv in mesh.uv_layers if uv.name == name), None)
    if layer is None:
        try:
            layer = mesh.uv_layers.new(name=name)
        except (RuntimeError, TypeError):                           # pragma: no cover
            return "could not create a UV layer"
    for uv in mesh.uv_layers:
        uv.active = (uv.name == layer.name)
    if bpy.context.mode != "EDIT_MESH":
        try:
            bpy.ops.object.mode_set(mode="EDIT")
        except (RuntimeError, TypeError):                           # pragma: no cover
            return "could not enter edit mode"
    try:
        bpy.ops.mesh.select_all(action="SELECT")
        if settings.uv_method == "SMART":
            ok = run_op("bpy.ops.uv.smart_project", angle_limit=math.radians(settings.uv_angle_limit),
                        island_margin=settings.uv_margin, correct_aspect=True, scale_to_bounds=False,
                        area_weight=0.0)
        else:
            ok = run_op("bpy.ops.uv.unwrap", method="ANGLE_BASED", margin=settings.uv_margin)
        if not ok:
            ok = run_op("bpy.ops.uv.smart_project", angle_limit=math.radians(settings.uv_angle_limit),
                        island_margin=settings.uv_margin)
    except (RuntimeError, TypeError):                               # pragma: no cover
        ok = False
    finally:
        try:
            bpy.ops.object.mode_set(mode="OBJECT")
        except (RuntimeError, TypeError):                           # pragma: no cover
            pass
    return f"{layer.name} unwrapped ({'smart' if settings.uv_method == 'SMART' else 'seams'})" if ok \
        else "unwrap unavailable in this Blender build"


# --------------------------------------------------------------------------- #
# Operators
# --------------------------------------------------------------------------- #
class ASSETGEN_OT_base(bpy.types.Operator):
    """Shared plumbing: target resolution, safety rails, before/after reporting."""

    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return bool(resolve_targets(context))

    # -- helpers -------------------------------------------------------------
    def targets(self, context) -> list:
        settings = context.scene.assetgen
        found = resolve_targets(context)
        return expand_hierarchy(context, found) if settings.include_children else found

    def edit(self, context, obj, work, *, destructive=True):
        """Run *work*(bmesh, counts) over *obj* behind every safety check."""
        settings = context.scene.assetgen
        reason = refusal_reason(obj, settings, destructive=destructive)
        if reason:
            return False, f"skipped: {reason}"
        if destructive:
            make_single_user(obj)
            if settings.allow_shape_key_drop and obj.data.shape_keys is not None:
                obj.shape_key_clear()
            make_backup(obj, settings)
        before = mesh_stats(obj)
        bmesh_obj = bmesh.new()
        bmesh_obj.from_mesh(obj.data)
        counts: dict = {}
        try:
            note = work(bmesh_obj, counts)
        finally:
            bmesh_obj.to_mesh(obj.data)
            bmesh_obj.free()
        obj.data.update()
        after = mesh_stats(obj)
        summary = ", ".join(f"{key} {value:,}" for key, value in counts.items() if value)
        line = (f"{obj.name}: {before['verts']:,}->{after['verts']:,} v, "
                f"{before['faces']:,}->{after['faces']:,} f")
        if summary:
            line += f"  [{summary}]"
        return True, line + (f"  {note}" if note else "")


class ASSETGEN_OT_setup(ASSETGEN_OT_base):
    """0. Apply transforms and re-seat the origin on every selected mesh."""

    bl_idname = "assetgen.setup"
    bl_label = "Import & Setup"
    bl_description = ("Apply location/rotation/scale (scale becomes 1.000) and move the origin, "
                      "so weld distances and voxel sizes are in real metres")

    def execute(self, context):
        settings = context.scene.assetgen
        lines: list = []
        done = 0
        for obj in self.targets(context):
            if obj.mode == "EDIT":
                bpy.ops.object.mode_set(mode="OBJECT")
            notes = []
            if settings.apply_transforms:
                notes.append("transforms applied" if apply_transforms(obj) else "transform_apply unavailable")
            notes.append(shift_origin(obj, settings.origin_mode))
            done += 1
            lines.append(f"{obj.name}: " + " | ".join(notes))
        if not lines:
            self.report({"WARNING"}, "No visible mesh object selected")
            return {"CANCELLED"}
        report(context, lines, tag="setup")
        self.report({"INFO"}, f"setup done on {done} object(s)")
        return {"FINISHED"}


class ASSETGEN_OT_clean(ASSETGEN_OT_base):
    """1. Weld broken seams, drop loose geometry, fix normals."""

    bl_idname = "assetgen.clean"
    bl_label = "Clean Mesh"
    bl_description = ("Merge by distance, dissolve degenerate faces, delete loose geometry and "
                      "floating islands, then recalculate normals outward")

    def execute(self, context):
        settings = context.scene.assetgen

        def work(bmesh_obj, counts):
            pass_weld(bmesh_obj, settings, counts)
            pass_islands(bmesh_obj, settings, counts)
            pass_coplanar(bmesh_obj, settings, counts)
            pass_loose(bmesh_obj, settings, counts)
            pass_normals(bmesh_obj, settings, counts)
            return ""

        lines, touched = [], 0
        for obj in self.targets(context):
            ok, line = self.edit(context, obj, work)
            lines.append(line)
            if ok:
                touched += 1
                if settings.tri_to_quad and tris_to_quads(obj):
                    lines.append(f"  triangles merged into quads: {len(obj.data.polygons):,} faces")
                if settings.mark_seams_off and clear_split_normals(obj):
                    lines.append("  custom split normals cleared")
        if not lines:
            self.report({"WARNING"}, "No visible mesh object selected")
            return {"CANCELLED"}
        lines.append(f"weld distance {settings.weld_threshold:.5f} m")
        report(context, lines, tag="clean")
        self.report({"INFO"}, f"cleaned {touched} mesh(es)")
        return {"FINISHED"}


class ASSETGEN_OT_symmetrize(ASSETGEN_OT_base):
    """2. Rebuild one half of the model from the other."""

    bl_idname = "assetgen.symmetrize"
    bl_label = "Symmetrize"
    bl_description = ("AI meshes are almost never mirrored evenly: rebuild the chosen side across "
                      "the axis and weld the stitch seam")

    def execute(self, context):
        settings = context.scene.assetgen

        def work(bmesh_obj, counts):
            result = symmetrize_bm(bmesh_obj, settings.sym_direction, settings.sym_dist,
                                  settings.sym_center_x)
            if "error" in result:
                return result["error"]
            counts["faces mirrored"] = result["faces_after"] - result["faces_before"]
            before = len(live(bmesh_obj.verts))
            if settings.weld_threshold > 0.0:
                bmesh.ops.remove_doubles(bmesh_obj, verts=live(bmesh_obj.verts),
                                         dist=max(settings.sym_dist, settings.weld_threshold))
                counts["stitched"] = before - len(live(bmesh_obj.verts))
            bmesh.ops.recalc_face_normals(bmesh_obj, faces=live(bmesh_obj.faces))
            return f"direction {settings.sym_direction}"

        lines, touched = [], 0
        for obj in self.targets(context):
            ok, line = self.edit(context, obj, work)
            lines.append(line)
            touched += int(ok)
        if not lines:
            self.report({"WARNING"}, "No visible mesh object selected")
            return {"CANCELLED"}
        report(context, lines, tag="symmetrize")
        self.report({"INFO"}, f"symmetrized {touched} mesh(es)")
        return {"FINISHED"}


class ASSETGEN_OT_optimize(ASSETGEN_OT_base):
    """3. Decimate (keeps texture) or voxel-remesh (clean rig base)."""

    bl_idname = "assetgen.optimize"
    bl_label = "Optimize Topology"
    bl_description = ("Mode A decimates with Collapse and preserves UVs, materials and weights; "
                      "Mode B voxel-remeshes for uniform quads and then re-recovers UVs/colours")

    method: bpy.props.EnumProperty(
        name="Method", default="SCENE",
        items=[("SCENE", "Panel Setting", "Use the method chosen in the panel"),
               ("DECIMATE", "Decimate", "Collapse the mesh to a ratio or a face budget"),
               ("REMESH", "Voxel Remesh", "Rebuild as a uniform quad shell")])       # type: ignore

    def decimate(self, obj, settings, faces_before: int):
        if faces_before < 4:
            return False, "decimate needs at least 4 faces"
        mod = obj.modifiers.new("AssetGen Decimate", "DECIMATE")
        ratio = settings.decimate_ratio
        if settings.use_face_target and faces_before > 0:
            ratio = max(min(settings.target_faces / faces_before, 1.0), 0.001)
        set_props(mod, decimate_type="COLLAPSE", ratio=ratio,
                  use_collapse_triangulate=settings.decimate_triangulate)
        applied = apply_modifier(obj, mod)
        drop_modifier(obj, "AssetGen Decimate")
        if not applied:
            return False, "decimate could not be applied"
        return True, f"decimated to {ratio:.3f} of {faces_before:,} faces"

    def execute(self, context):
        settings = context.scene.assetgen
        method = settings.method if self.method == "SCENE" else self.method
        lines, touched = [], 0
        for obj in self.targets(context):
            reason = refusal_reason(obj, settings, destructive=True)
            if reason:
                lines.append(f"{obj.name}: skipped: {reason}")
                continue
            make_single_user(obj)
            if settings.allow_shape_key_drop and obj.data.shape_keys is not None:
                obj.shape_key_clear()
            backup = make_backup(obj, settings)
            before = mesh_stats(obj)
            note = ""
            if method == "DECIMATE":
                _, note = self.decimate(obj, settings, before["faces"])
            else:
                if before["faces"] < 4:
                    note = "voxel remesh needs a closed shell of at least 4 faces"
                    lines.append(f"{obj.name}: {note}")
                    continue
                mod = obj.modifiers.new("AssetGen Remesh", "REMESH")
                set_props(mod, mode="VOXEL", voxel_size=settings.voxel_size,
                          use_remove_disconnected=settings.remesh_remove_disconnected,
                          use_smooth_shade=settings.remesh_smooth_shade,
                          use_multi_res_mesh=False)
                applied = apply_modifier(obj, mod)
                drop_modifier(obj, "AssetGen Remesh")
                if not applied:
                    note = "voxel remesh failed (mesh not manifold enough for a volume shell)"
                else:
                    after_remesh = mesh_stats(obj)
                    note = f"voxel {settings.voxel_size:g} m -> {after_remesh['faces']:,} faces"
                    if settings.remesh_decimate_to_target and after_remesh["faces"] > settings.target_faces:
                        _, extra = self.decimate(obj, settings, after_remesh["faces"])
                        note += f"; {extra}"
            if method == "REMESH" and (settings.transfer_uvs or settings.transfer_vcols):
                note += " | " + "; ".join(transfer_attributes(obj, backup, settings))
            if method == "REMESH" and settings.remesh_smooth_shade:
                note += " | " + shade_object(obj, True, settings.shade_angle)
            after = mesh_stats(obj)
            lines.append(f"{obj.name}: {before['tris']:,} -> {after['tris']:,} tris "
                         f"({after['tris'] / max(before['tris'], 1):.0%})  {note}")
            touched += 1
        if not lines:
            self.report({"WARNING"}, "No visible mesh object selected")
            return {"CANCELLED"}
        lines.append("remeshed meshes lose skin weights: bind again after this step")
        report(context, lines, tag="optimize")
        self.report({"INFO"}, f"optimized {touched} mesh(es) with {method.lower()}")
        return {"FINISHED"}


class ASSETGEN_OT_unwrap(ASSETGEN_OT_base):
    """4. Rebuild the UV atlas on the new topology."""

    bl_idname = "assetgen.unwrap"
    bl_label = "Auto UV Unwrap"
    bl_description = ("Smart UV Project the cleaned topology into a fresh atlas so the old texture "
                      "can be baked onto it, or an angle-based unwrap when seams already exist")

    def execute(self, context):
        settings = context.scene.assetgen
        lines, touched = [], 0
        for obj in self.targets(context):
            make_single_user(obj)
            note = smart_unwrap(obj, settings)
            uv_count = len(obj.data.uv_layers)
            lines.append(f"{obj.name}: {note} | {uv_count} uv layer(s)")
            touched += 1
        if not lines:
            self.report({"WARNING"}, "No visible mesh object selected")
            return {"CANCELLED"}
        report(context, lines, tag="unwrap")
        self.report({"INFO"}, f"unwrapped {touched} mesh(es)")
        return {"FINISHED"}


class ASSETGEN_OT_stats(ASSETGEN_OT_base):
    """Read-only: what the pipeline would change, and what is still wrong."""

    bl_idname = "assetgen.stats"
    bl_label = "Report"
    bl_description = "Print per-object geometry statistics without touching the mesh"
    bl_options = {"REGISTER"}

    @classmethod
    def poll(cls, context):
        return context.scene is not None

    def execute(self, context):
        targets = self.targets(context)
        lines: list = []
        for obj in targets:
            lines.extend(stats_block(obj))
        if not lines:
            lines = ["no mesh object selected"]
        lines.insert(0, f"{len(targets)} mesh target(s)")
        report(context, lines, tag="report")
        self.report({"INFO"}, f"reported on {len(targets)} object(s)")
        return {"FINISHED"}


class ASSETGEN_OT_run_all(ASSETGEN_OT_base):
    """The single click: setup -> clean -> (symmetrize) -> optimize -> unwrap."""

    bl_idname = "assetgen.run_all"
    bl_label = "Run Full Optimizer"
    bl_description = "Run every enabled step in order on the selected meshes"

    @classmethod
    def poll(cls, context):
        return bool(resolve_targets(context))

    def execute(self, context):
        started = time.perf_counter()
        settings = context.scene.assetgen
        steps = [("assetgen.setup", settings.step_setup),
                 ("assetgen.clean", settings.step_clean),
                 ("assetgen.symmetrize", settings.step_symmetrize),
                 ("assetgen.optimize", settings.step_optimize),
                 ("assetgen.unwrap", settings.step_unwrap)]
        summary: list = []
        for idname, enabled in steps:
            if not enabled:
                summary.append(f"{idname.split('.')[1]:<12} skipped")
                continue
            call = getattr(getattr(bpy.ops, "assetgen", None), idname.split(".")[1], None)
            if call is None:                                       # pragma: no cover
                summary.append(f"{idname.split('.')[1]:<12} unavailable")
                continue
            try:
                result = call()
            except (RuntimeError, TypeError) as exc:               # pragma: no cover
                summary.append(f"{idname.split('.')[1]:<12} failed: {exc}")
                continue
            summary.append(f"{idname.split('.')[1]:<12} {'done' if result == {'FINISHED'} else 'cancelled'}")
        for obj in self.targets(context):
            summary.extend(stats_block(obj))
        summary.append(f"elapsed {time.perf_counter() - started:.2f}s")
        report(context, summary, tag="run_all")
        self.report({"INFO"}, "AI mesh optimizer finished in " + f"{time.perf_counter() - started:.1f}s")
        return {"FINISHED"}


# --------------------------------------------------------------------------- #
# Utilities: source backups and high-to-low texture baking
# --------------------------------------------------------------------------- #
def backup_objects(context, targets) -> list:
    names = {obj.name + BACKUP_SUFFIX for obj in targets}
    return [ob for name in names for ob in [bpy.data.objects.get(name)] if ob is not None]


class ASSETGEN_OT_clear_backups(bpy.types.Operator):
    """Delete the hidden *_AI_SRC copies this add-on created."""

    bl_idname = "assetgen.clear_backups"
    bl_label = "Clear Source Backups"
    bl_description = ("Remove every hidden backup object. Do it last: the UV/colour transfer and the "
                      "bake both sample them")
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        targets = resolve_targets(context)
        doomed = backup_objects(context, targets) or [ob for ob in context.view_layer.objects
                                                       if ob.name.endswith(BACKUP_SUFFIX)]
        for obj in doomed:
            mesh = obj.data
            bpy.data.objects.remove(obj, do_unlink=True)
            if mesh is not None and mesh.users == 0:
                bpy.data.meshes.remove(mesh)
        if not doomed:
            self.report({"INFO"}, "no backups to remove")
            return {"CANCELLED"}
        report(context, [f"removed {len(doomed)} backup object(s)"], tag="clear_backups")
        self.report({"INFO"}, f"removed {len(doomed)} backup(s)")
        return {"FINISHED"}


class ASSETGEN_OT_bake_prep(ASSETGEN_OT_base):
    """Wire the source backup up as a high-to-low bake target and bake it."""

    bl_idname = "assetgen.bake_prep"
    bl_label = "Bake Source Texture"
    bl_description = ("Bake the hidden *_AI_SRC backup onto the optimised mesh (selected to active, "
                      "diffuse colour only) into a new image, so the AI texture survives remeshing")
    bl_options = {"REGISTER", "UNDO"}

    size: bpy.props.IntProperty(name="Image Size", default=2048, min=256, max=8192,
                               soft_min=512, soft_max=4096)       # type: ignore
    run_bake: bpy.props.BoolProperty(name="Bake Now", default=True,
                                     description="Otherwise only set up the image and bake settings")       # type: ignore

    @classmethod
    def poll(cls, context):
        return bool(resolve_targets(context))

    def execute(self, context):
        obj = context.active_object
        if obj is None or obj.type != "MESH":
            self.report({"WARNING"}, "Select the mesh to bake into")
            return {"CANCELLED"}
        backup = bpy.data.objects.get(obj.name + BACKUP_SUFFIX)
        if backup is None:
            self.report({"WARNING"}, "No source backup found - run Clean/Optimize with "
                                    "'Keep Source Backup' on first")
            return {"CANCELLED"}
        if not obj.data.uv_layers:
            self.report({"WARNING"}, "The target needs a UV map: run Auto UV Unwrap first")
            return {"CANCELLED"}

        size = self.size or 2048
        image = bpy.data.images.new(f"{obj.name}_Bake", size, size, alpha=False, float_buffer=False)
        image.colorspace_settings.name = "sRGB"
        slot = obj.data.materials[0] if obj.data.materials else bpy.data.materials.new(f"{obj.name}_BakeMat")
        if not slot.use_nodes:
            slot.use_nodes = True
        nodes, links = slot.node_tree.nodes, slot.node_tree.links
        target = nodes.new("ShaderNodeTexImage")
        target.image = image
        target.label = "AssetGen Bake Target"
        for node in nodes:
            node.select = False
        nodes.active = target
        if not links:
            log("material has no nodes to connect; the baked image stays unconnected")

        scene = context.scene
        lines = [f"bake target: {image.name} ({size}x{size})", f"slot material: {slot.name}"]
        try:
            scene.render.engine = "CYCLES"
        except (TypeError, RuntimeError):                            # pragma: no cover
            lines.append("Cycles unavailable - open the file in Blender UI and bake manually")
        bake = scene.render.bake
        set_props(bake, use_selected_to_active=True, cage_extrusion=0.05, max_ray_distance=0.5,
                   margin=8, use_pass_direct=False, use_pass_indirect=False, use_pass_color=True,
                   use_clear=True)
        if not self.run_bake:
            report(context, lines + ["bake setup only (Bake Now off)"], tag="bake_prep")
            return {"FINISHED"}

        for other in context.selected_objects:
            other.select_set(False)
        backup.hide_set(False)
        backup.hide_viewport = False
        try:
            backup.select_set(True)
        except (RuntimeError, TypeError):                          # pragma: no cover
            pass
        obj.select_set(True)
        context.view_layer.objects.active = obj
        if len(context.selected_objects) < 2:
            backup.hide_set(True)
            self.report({"ERROR"}, "selected-to-active needs both the source backup and the "
                                   "target selected - unhide the backup and retry")
            return {"CANCELLED"}
        try:
            bpy.ops.object.bake(type="DIFFUSE", pass_filter={"COLOR"}, margin=8,
                                use_selected_to_active=True, use_cage=False,
                                use_pass_direct=False, use_pass_indirect=False, use_pass_color=True)
            try:
                image.pack()
                packed = ", packed into the .blend"
            except (RuntimeError, TypeError):                     # pragma: no cover
                packed = ""
            lines.append(f"baked diffuse colour into {image.name}{packed}")
        except (RuntimeError, TypeError) as exc:
            lines.append(f"bake failed: {exc}")
        finally:
            backup.hide_viewport = True
        report(context, lines, tag="bake_prep")
        return {"FINISHED"}


# --------------------------------------------------------------------------- #
# Panel
# --------------------------------------------------------------------------- #
class ASSETGEN_PT_panel(bpy.types.Panel):
    """Assets Gen Pro - one-click cleanup, retopology and UVs for AI meshes."""

    bl_label = "Assets Gen Pro"
    bl_idname = "ASSETGEN_PT_panel"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "AssetGenPro"
    bl_options = {"DEFAULT_CLOSED"}

    @classmethod
    def poll(cls, context):
        return context.scene is not None and hasattr(context.scene, "assetgen")

    def draw(self, context):
        layout = self.layout
        settings = context.scene.assetgen
        targets = resolve_targets(context)
        first = targets[0] if targets else None

        header = layout.row(align=True)
        header.label(text=f"Targets: {len(targets)}" + (f"  ({first.name})" if len(targets) == 1 else ""),
                     icon="MESH_DATA")
        header.operator("assetgen.stats", text="", icon="INFO")
        if not targets:
            layout.label(text="Select a mesh (or one mesh in the scene)", icon="ERROR")
            layout.label(text="or hide nothing so the solo mesh is picked up")
            return

        self.draw_warnings(layout, settings, targets)

        box = layout.box()
        box.label(text="0  Import & Setup", icon="OBJECT_DATA")
        col = box.column(align=True)
        col.prop(settings, "origin_mode")
        col.prop(settings, "apply_transforms")
        col.prop(settings, "include_children")
        box.operator("assetgen.setup", icon="PIVOT_CURSOR")

        box = layout.box()
        box.label(text="1  Mesh Cleanup", icon="BRUSH_DATA")
        col = box.column(align=True)
        col.prop(settings, "weld_threshold")
        col.prop(settings, "dissolve_degenerate")
        col.prop(settings, "coplanar_angle")
        col.prop(settings, "delete_loose")
        col.prop(settings, "min_island_faces")
        col.prop(settings, "recalc_normals")
        col.prop(settings, "flip_normals")
        col.prop(settings, "mark_seams_off")
        col.prop(settings, "tri_to_quad")
        box.operator("assetgen.clean", icon="MOD_DECIM")

        box = layout.box()
        box.label(text="2  Symmetry", icon="MOD_MIRROR")
        col = box.column(align=True)
        col.prop(settings, "sym_direction")
        col.prop(settings, "sym_dist")
        col.prop(settings, "sym_center_x")
        box.operator("assetgen.symmetrize", icon="MOD_MIRROR")

        box = layout.box()
        box.label(text="3  Topology Optimization", icon="MOD_REMESH")
        col = box.column(align=True)
        col.prop(settings, "method", expand=True)
        if settings.method == "DECIMATE":
            col.prop(settings, "decimate_ratio", slider=True)
            col.prop(settings, "use_face_target")
            if settings.use_face_target:
                col.prop(settings, "target_faces")
            col.prop(settings, "decimate_triangulate")
        else:
            col.prop(settings, "voxel_size")
            col.prop(settings, "remesh_decimate_to_target")
            if settings.remesh_decimate_to_target:
                col.prop(settings, "target_faces")
            col.prop(settings, "remesh_remove_disconnected")
            col.prop(settings, "remesh_smooth_shade")
            if settings.remesh_smooth_shade:
                col.prop(settings, "shade_angle", slider=True)
            col.prop(settings, "transfer_uvs")
            col.prop(settings, "transfer_vcols")
        row = box.row(align=True)
        row.operator("assetgen.optimize", text="Optimize (Decimate)").method = "DECIMATE"
        row.operator("assetgen.optimize", text="Remesh").method = "REMESH"

        box = layout.box()
        box.label(text="4  UV Unwrap", icon="UV")
        col = box.column(align=True)
        col.prop(settings, "uv_method")
        col.prop(settings, "uv_angle_limit", slider=True)
        col.prop(settings, "uv_margin")
        col.prop(settings, "uv_new_layer")
        box.operator("assetgen.unwrap", icon="UV")

        box = layout.box()
        box.label(text="One Click", icon="TOOL_SETTINGS")
        col = box.column(align=True)
        col.prop(settings, "step_setup")
        col.prop(settings, "step_clean")
        col.prop(settings, "step_symmetrize")
        col.prop(settings, "step_optimize")
        col.prop(settings, "step_unwrap")
        box.operator("assetgen.run_all", icon="PLAY", text="Clean + Optimize + Unwrap")
        box.label(text=settings.last_run or "not run yet", icon="TIME")

        box = layout.box()
        box.label(text="Utilities", icon="PREFERENCES")
        col = box.column(align=True)
        col.operator("assetgen.bake_prep", icon="TEX")
        col.operator("assetgen.clear_backups", icon="X")
        col.prop(settings, "keep_backup")
        col.prop(settings, "allow_skinned")
        col.prop(settings, "allow_shape_key_drop")
        col.prop(settings, "verbose_console")

        if settings.report_lines:
            box = layout.box()
            box.label(text="Last Run", icon="CONSOLE")
            for line in settings.report_lines:
                box.label(text=line.text, translate=False)

    @staticmethod
    def draw_warnings(layout, settings, targets):
        notes = []
        for obj in targets[:8]:
            if obj.vertex_groups or any(mod.type == "ARMATURE" for mod in obj.modifiers):
                notes.append(f"{obj.name} is skinned: weights are dropped by optimize")
            if obj.data.shape_keys is not None:
                notes.append(f"{obj.name} has shape keys: destructive passes are refused")
            if tuple(round(value, 4) for value in obj.scale) != (1.0, 1.0, 1.0):
                notes.append(f"{obj.name} scale is not 1.0: run Import & Setup first")
            if not obj.data.uv_layers:
                notes.append(f"{obj.name} has no UV map yet")
        if len(targets) > 1:
            notes.append(f"{len(targets)} targets: every step runs on all of them")
        for note in notes[:6]:
            layout.label(text=note[:74], icon="ERROR")


# --------------------------------------------------------------------------- #
# Registration
# --------------------------------------------------------------------------- #
classes = (
    ASSETGEN_LT_line,
    ASSETGEN_PG_settings,
    ASSETGEN_OT_setup,
    ASSETGEN_OT_clean,
    ASSETGEN_OT_symmetrize,
    ASSETGEN_OT_optimize,
    ASSETGEN_OT_unwrap,
    ASSETGEN_OT_stats,
    ASSETGEN_OT_run_all,
    ASSETGEN_OT_bake_prep,
    ASSETGEN_OT_clear_backups,
    ASSETGEN_PT_panel,
)


def menu_draw(self, context):
    """Entry in the viewport's ``Add``/object menu so the pipeline is reachable
    without opening the sidebar (also the easiest thing to bind to a shortcut)."""
    self.layout.operator("assetgen.run_all", text="AssetGenPro: Clean + Optimize Mesh",
                         icon="MOD_DECIM")


def register():
    for cls in classes:
        bpy.utils.register_class(cls)
    bpy.types.Scene.assetgen = bpy.props.PointerProperty(type=ASSETGEN_PG_settings)
    # A menu entry means the pipeline is reachable without opening the sidebar.
    bpy.types.VIEW3D_MT_object.append(menu_draw)


def unregister():
    bpy.types.VIEW3D_MT_object.remove(menu_draw)
    del bpy.types.Scene.assetgen
    for cls in reversed(classes):
        if not hasattr(cls, "bl_rna"):                             # pragma: no cover
            continue
        try:
            bpy.utils.unregister_class(cls)
        except RuntimeError:                                       # pragma: no cover
            pass


if __name__ == "__main__":
    register()
