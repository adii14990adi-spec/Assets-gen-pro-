"""Static guardrails for the optional Blender add-on in scripts/assetgen_mesh_optimizer.py.

CI has no Blender (see README -> "Why no Blender in CI?"), so the tests here are
of the kind that can run anywhere: they parse the add-on's source and assert the
invariants that actually break add-ons in the wild (registration order, a panel
touching a property that does not exist, an operator id that was renamed but not
updated at the call site).

The functional block at the bottom needs a real ``bpy`` and is skipped unless one
is importable -- run it with the isolated Blender runtime:

    ~/.local/blender-runtime/bin/python -m pytest tests/test_mesh_optimizer_addon.py -v
"""

from __future__ import annotations

import ast
import pathlib
import sys

import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
ADDON = REPO_ROOT / "scripts" / "assetgen_mesh_optimizer.py"
tree = ast.parse(ADDON.read_text(encoding="utf-8"))


def _assignements(node_filter) -> dict:
    out = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and node_filter(target.id):
                    out[target.id] = node
    return out


def _class_names() -> list[str]:
    return [node.name for node in tree.body if isinstance(node, ast.ClassDef)]


def _module_level_names() -> list[str]:
    return [alias.name for node in tree.body if isinstance(node, (ast.Import, ast.ImportFrom))
            for alias in node.names]


def _prop_names_of(class_name: str) -> set[str]:
    """Every ``name: bpy.props.XProperty()`` field declared by a PropertyGroup."""
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == class_name:
            fields = set()
            for item in node.body:
                if isinstance(item, ast.AnnAssign) and isinstance(item.target, ast.Name):
                    fields.add(item.target.id)
            return fields
    raise AssertionError(f"{class_name} not found")


def _registered_classes() -> list[str]:
    for name, node in _assignements(lambda n: n == "classes").items():
        if isinstance(node.value, ast.Tuple):
            return [element.id for element in node.value.elts if isinstance(element, ast.Name)]
    raise AssertionError("no `classes = (...)` tuple found")


# --------------------------------------------------------------------------- #
# Add-on metadata
# --------------------------------------------------------------------------- #
def test_addon_exists_with_bl_info():
    assert ADDON.is_file(), "the add-on must ship in scripts/ so CI lints it"
    source = ADDON.read_text(encoding="utf-8")
    assert "bl_info" in source
    assignment = next(node for node in tree.body if isinstance(node, ast.Assign)
                      and any(getattr(t, "id", "") == "bl_info" for t in node.targets))
    info = ast.literal_eval(assignment.value)
    assert info["blender"] >= (4, 0, 0), "the brief targets Blender 4.0+"
    for key in ("name", "author", "version", "blender", "category", "description"):
        assert info.get(key), f"bl_info is missing '{key}'"
    # a docstring is what makes the file usable without opening the source
    assert ast.get_docstring(tree) and len(ast.get_docstring(tree)) > 400


def test_bpy_is_imported_before_bmesh_and_mathutils():
    """`bpy` registers the module path bmesh/mathutils live on, so order matters.

    Ruff's isort rule would happily "fix" this into a broken import, hence the
    explicit test next to the `# noqa: I001` markers.
    """
    names = _module_level_names()
    assert "bpy" in names and "bmesh" in names
    assert names.index("bpy") < names.index("bmesh")
    if "Vector" in names:
        assert names.index("bpy") < names.index("Vector")


def test_every_class_is_registered_exactly_once():
    registered = _registered_classes()
    classes = _class_names()
    assert len(registered) == len(set(registered)), "duplicate entry in classes"
    for name in registered:
        assert name in classes, f"{name} is registered but never defined"
    for name in classes:
        if name == "ASSETGEN_OT_base":
            continue                      # shared plumbing, no bl_idname by design
        if name.startswith("ASSETGEN_OT_") or name.startswith("ASSETGEN_PT_") or name.endswith("_settings"):
            assert name in registered, f"{name} is defined but never registered"


def test_base_operator_is_not_registered():
    """A subclass without bl_idname raises at registration time."""
    registered = _registered_classes()
    assert "ASSETGEN_OT_base" not in registered
    base = next(node for node in tree.body if isinstance(node, ast.ClassDef)
                and node.name == "ASSETGEN_OT_base")
    assert not any(isinstance(item, ast.AnnAssign) and getattr(item.target, "id", "") == "bl_idname"
                   for item in base.body)


def test_operator_ids_are_unique_and_match_their_class():
    ids = []                                          # (class name, bl_idname)
    for node in tree.body:
        if not isinstance(node, ast.ClassDef) or not node.name.startswith("ASSETGEN_OT_"):
            continue
        for item in node.body:
            if isinstance(item, ast.Assign):
                for target in item.targets:
                    if isinstance(target, ast.Name) and target.id == "bl_idname":
                        ids.append((node.name, ast.literal_eval(item.value)))
    bl_idnames = [value for _, value in ids]
    assert len(bl_idnames) == len(set(bl_idnames)), f"duplicate bl_idname in {bl_idnames}"
    for class_name, idname in ids:
        assert idname.startswith("assetgen."), f"{class_name} must live in the assetgen namespace"
        # ASSETGEN_OT_clean -> assetgen.clean : the suffix must line up, because the
        # panel and any keymap reference the idname, never the class name.
        suffix = class_name.split("_", 2)[-1].lower()
        assert idname.split(".")[1] == suffix, f"{class_name} should be 'assetgen.{suffix}'"


def test_unregister_is_the_reverse_of_register_and_removes_the_pointer():
    source = ADDON.read_text(encoding="utf-8")        # text checks below
    assert "reversed(classes)" in source, "unregister must unwind in reverse"
    assert "del bpy.types.Scene.assetgen" in source
    assert "bpy.types.Scene.assetgen = " in source
    assert "VIEW3D_MT_object.append" in source and "VIEW3D_MT_object.remove" in source


# --------------------------------------------------------------------------- #
# Panel <-> data consistency (the usual source of red-text-in-the-sidebar bugs)
# --------------------------------------------------------------------------- #
def test_panel_only_touches_declared_properties():
    fields = _prop_names_of("ASSETGEN_PG_settings")
    assert fields, "the settings group must declare the panel's sliders"
    used = set()
    for node in ast.walk(tree):
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and node.func.attr == "prop" and len(node.args) >= 2
                and isinstance(node.args[0], ast.Name) and node.args[0].id == "settings"
                and isinstance(node.args[1], ast.Constant)):
            used.add(node.args[1].value)
    assert len(used) >= 20, f"expected a settings-rich panel, only found {len(used)} props"
    missing = sorted(used - fields)
    assert not missing, f"panel binds undeclared properties: {missing}"


def test_panel_operators_exist_and_are_registered():
    registered_ids = set()
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name.startswith("ASSETGEN_OT_"):
            for item in node.body:
                if isinstance(item, ast.Assign) and any(getattr(t, "id", "") == "bl_idname"
                                                         for t in item.targets):
                    registered_ids.add(ast.literal_eval(item.value))
    referenced = set()
    for node in ast.walk(tree):
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and node.func.attr in {"operator"} and node.args
                and isinstance(node.args[0], ast.Constant)
                and isinstance(node.args[0].value, str) and node.args[0].value.startswith("assetgen.")):
            referenced.add(node.args[0].value)
    assert referenced, "the panel must expose buttons"
    unknown = sorted(referenced - registered_ids)
    assert not unknown, f"panel calls unregistered operators: {unknown}"


def test_the_five_required_steps_are_all_present():
    """Import & setup, cleanup, the two optimisation modes, UV unwrap, panel tab."""
    source = ADDON.read_text(encoding="utf-8")
    for needle in ("remove_doubles", "recalc_face_normals", "DECIMATE", "VOXEL",
                   "smart_project", "bl_category = \"AssetGenPro\"", "tris_convert_to_quads",
                   "symmetrize"):
        assert needle in source, f"missing feature marker: {needle}"
    assert "normals_make_consistent" not in source, \
        "edit-mode normal operators are context-dependent; use bmesh instead"
    for step in ("setup", "clean", "symmetrize", "optimize", "unwrap", "run_all"):
        assert f"bl_idname = \"assetgen.{step}\"" in source, f"no operator for step '{step}'"


def _prop_defaults(class_name: str) -> dict:
    """``default=`` of every ``bpy.props`` field declared on *class_name*."""
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == class_name:
            found = {}
            for item in node.body:
                # `name: bpy.props.FloatProperty(default=...)` is an AnnAssign whose
                # property call sits in .annotation, not .value
                call = item.annotation if isinstance(item, ast.AnnAssign) else None
                if not isinstance(call, ast.Call) or not isinstance(item.target, ast.Name):
                    continue
                for keyword in call.keywords:
                    if keyword.arg == "default" and isinstance(keyword.value, ast.Constant):
                        found[item.target.id] = keyword.value.value
            return found
    raise AssertionError(f"{class_name} not found")


def test_ratio_and_voxel_defaults_follow_the_brief():
    """The numbers from the brief are the shipped defaults, not just documentation."""
    defaults = _prop_defaults("ASSETGEN_PG_settings")
    assert defaults["weld_threshold"] == 0.0001, "merge-by-distance threshold is fixed at 1e-4"
    assert defaults["decimate_ratio"] == 0.5
    assert defaults["voxel_size"] == 0.02
    assert defaults["method"] == "DECIMATE"
    assert defaults["uv_method"] == "SMART"
    assert defaults["recalc_normals"] is True and defaults["delete_loose"] is True
    assert defaults["keep_backup"] is True, "the transfer/bake source must exist by default"


def test_no_placeholders_or_todo_left():
    source = ADDON.read_text(encoding="utf-8")
    for banned in ("TODO", "FIXME", "NotImplementedError", "raise NotImplemented", "...  #"):
        assert banned not in source, f"found placeholder marker '{banned}'"
    # a `pass` in an except handler is intentional; a bare function body is not
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef,)):
            body = [stmt for stmt in node.body if not (isinstance(stmt, ast.Expr)
                                                       and isinstance(stmt.value, ast.Constant))]
            assert body, f"{node.name} has an empty body"
            assert not (len(body) == 1 and isinstance(body[0], ast.Pass)), f"{node.name} is a stub"


# --------------------------------------------------------------------------- #
# Functional tests: only when a real bpy is importable
# --------------------------------------------------------------------------- #
def _dirty_mesh(bpy, name: str):
    """A cube with AI-export defects: split seams, dust, a flipped shell, no UVs."""
    import bmesh

    mesh = bpy.data.meshes.new(name)
    bm = bmesh.new()
    bmesh.ops.create_cube(bm, size=1.0)
    v1 = bm.verts.new((3.0, 3.0, 3.0))
    v2 = bm.verts.new((3.06, 3.0, 3.0))
    v3 = bm.verts.new((3.0, 3.06, 3.0))
    bm.faces.new((v1, v2, v3))                       # floating dust island
    bm.verts.new((9.0, 9.0, 9.0))                    # loose vertex
    bmesh.ops.split_edges(bm, edges=list(bm.edges))  # duplicate verts everywhere
    bmesh.ops.recalc_face_normals(bm, faces=[f for f in bm.faces if f.is_valid])
    bm.to_mesh(mesh)
    uv = mesh.uv_layers.new(name="UVMap")
    for index in range(len(mesh.loops)):
        uv.data[index].uv = ((index % 5) * 0.2, (index % 3) * 0.5)
    colour = mesh.color_attributes.new(name="Col", type="BYTE_COLOR", domain="CORNER")
    for index in range(len(mesh.loops)):
        colour.data[index].color = (0.8, 0.3, 0.2, 1.0)
    bm.free()
    obj = bpy.data.objects.new(name, mesh)
    bpy.context.scene.collection.objects.link(obj)
    obj.scale = (2.0, 2.0, 2.0)
    return obj


@pytest.fixture(scope="module")
def addon_module():
    import importlib.util

    pytest.importorskip("bpy")
    spec = importlib.util.spec_from_file_location("assetgen_addon_under_test", ADDON)
    module = importlib.util.module_from_spec(spec)
    # Blender calls typing.get_type_hints() on PropertyGroups, which resolves the
    # postponed annotations through sys.modules[module.__name__]; skipping this
    # step fails registration with `NameError: name 'bpy' is not defined`.
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    module.register()
    yield module
    sys.modules.pop(spec.name, None)
    module.unregister()


@pytest.fixture()
def scene_with_mesh(addon_module):
    bpy = pytest.importorskip("bpy")
    for obj in list(bpy.data.objects):
        bpy.data.objects.remove(obj, do_unlink=True)
    obj = _dirty_mesh(bpy, "CI_AI_Mesh")
    bpy.context.view_layer.update()
    for other in bpy.data.objects:
        other.select_set(False)
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj
    yield obj
    for obj2 in list(bpy.data.objects):
        bpy.data.objects.remove(obj2, do_unlink=True)


@pytest.mark.parametrize("step,expect", [("setup", None), ("clean", None), ("unwrap", None)])
def test_each_step_runs_headlessly(addon_module, scene_with_mesh, step, expect):
    bpy = pytest.importorskip("bpy")
    result = getattr(bpy.ops.assetgen, step)()
    assert result == {"FINISHED"}


def test_setup_applies_transforms(addon_module, scene_with_mesh):
    bpy = pytest.importorskip("bpy")
    obj = scene_with_mesh
    assert tuple(round(v, 5) for v in obj.scale) != (1.0, 1.0, 1.0)
    bpy.ops.assetgen.setup()
    assert tuple(round(v, 5) for v in obj.scale) == (1.0, 1.0, 1.0)
    assert max(abs(corner[0]) for corner in obj.bound_box) > 1.0, "scale must be baked into the data"


def test_clean_welds_and_removes_dust(addon_module, scene_with_mesh):
    bpy = pytest.importorskip("bpy")
    import bmesh

    obj = scene_with_mesh
    before = len(obj.data.vertices)
    bpy.context.scene.assetgen.min_island_faces = 4
    bpy.ops.assetgen.clean()
    assert len(obj.data.vertices) < before, "duplicate verts must be merged"
    bm = bmesh.new()
    bm.from_mesh(obj.data)
    volume = bm.calc_volume(signed=True)
    bm.free()
    assert volume > 0.0, "normals must end up pointing outward"
    assert not any(edge.is_loose for edge in obj.data.edges), "loose geometry must go"
    assert len(obj.data.polygons) == 6, "only the cube shell should survive"


def test_optimize_and_transfer_keep_an_atlas(addon_module, scene_with_mesh):
    bpy = pytest.importorskip("bpy")
    obj = scene_with_mesh
    bpy.ops.assetgen.setup()
    bpy.ops.assetgen.clean()
    settings = bpy.context.scene.assetgen
    settings.voxel_size = 0.25
    settings.remesh_decimate_to_target = False
    settings.transfer_uvs = True
    bpy.ops.assetgen.optimize(method="REMESH")
    assert len(obj.data.polygons) > 6, "voxel remesh should subdivide the shell"
    assert len(obj.data.uv_layers) >= 1, "UVs must be recovered from the source backup"
    spread = {(round(data.uv[0], 3), round(data.uv[1], 3)) for data in obj.data.uv_layers.active.data}
    assert len(spread) > 1, "transferred UVs must not be a single constant"
    bpy.ops.assetgen.unwrap()
    assert len(obj.modifiers) == 0, "no modifier may be left on the stack"


def test_destructive_steps_refuse_shape_keys(addon_module, scene_with_mesh):
    bpy = pytest.importorskip("bpy")
    obj = scene_with_mesh
    obj.shape_key_add(name="Basis")
    faces = len(obj.data.polygons)
    bpy.context.scene.assetgen.allow_shape_key_drop = False
    bpy.ops.assetgen.clean()
    assert len(obj.data.polygons) == faces, "shape keys must block a weld"
    lines = [line.text for line in bpy.context.scene.assetgen.report_lines]
    assert any("shape key" in line for line in lines)


def test_full_pipeline_is_idempotent(addon_module, scene_with_mesh):
    bpy = pytest.importorskip("bpy")
    obj = scene_with_mesh
    settings = bpy.context.scene.assetgen
    settings.step_symmetrize = True
    settings.min_island_faces = 4
    assert bpy.ops.assetgen.run_all() == {"FINISHED"}
    verts = len(obj.data.vertices)
    assert verts > 0 and len(obj.data.uv_layers) >= 1
    assert bpy.ops.assetgen.run_all() == {"FINISHED"}
    assert abs(len(obj.data.vertices) - verts) <= 2, "a second pass must not chew through the mesh"
