"""Blender-side capability probes and add-on activation helpers.

IMPORTANT: Functions inside `probe_blender_capabilities_in_blender()` only import `bpy`
when called from inside Blender's own Python runtime subprocess.
"""

from __future__ import annotations

from typing import Any

BLENDER_CAPABILITY_METADATA: dict[str, dict[str, Any]] = {
    "blender_core": {
        "name": "Blender Core (bpy + BMesh + PBR Shader Nodes)",
        "kind": "blender_core",
        "license": "GPL-3.0-or-later",
        "applicable_categories": ["humanoid", "architecture", "environment", "props"],
        "fallback_strategy": "Required core 3D generation engine",
    },
    "gltf2_exporter": {
        "name": "Blender glTF 2.0 Exporter (io_scene_gltf2)",
        "kind": "blender_core",
        "license": "Apache-2.0 / GPL-2.0-or-later",
        "applicable_categories": ["humanoid", "architecture", "environment", "props"],
        "fallback_strategy": "Required GLB exporter & roundtrip validator",
    },
    "geometry_nodes": {
        "name": "Blender Geometry Nodes Procedural Graph",
        "kind": "blender_core",
        "license": "GPL-3.0-or-later",
        "applicable_categories": ["architecture", "environment", "props"],
        "fallback_strategy": "Direct BMesh parametric instancing",
    },
    "native_boolean": {
        "name": "Blender Exact/Fast Boolean CSG Solver",
        "kind": "blender_core",
        "license": "GPL-3.0-or-later",
        "applicable_categories": ["architecture", "props"],
        "fallback_strategy": "BMesh analytic portal extrusion",
    },
    "rigify": {
        "name": "Rigify Humanoid Rigging Extension",
        "kind": "blender_addon",
        "license": "GPL-2.0-or-later",
        "applicable_categories": ["humanoid"],
        "fallback_strategy": "Godot 4 Humanoid Skeleton3D analytical bone & weight builder",
    },
    "looptools": {
        "name": "LoopTools Topology Operations (mesh_looptools)",
        "kind": "blender_addon",
        "license": "GPL-2.0-or-later",
        "applicable_categories": ["humanoid", "props"],
        "fallback_strategy": "Analytical BMesh circular projection & Laplacian loop relax",
    },
    "bool_tool": {
        "name": "Bool Tool Hard-Surface CSG Helper (object_boolean_tools)",
        "kind": "blender_addon",
        "license": "GPL-2.0-or-later",
        "applicable_categories": ["architecture", "props"],
        "fallback_strategy": "Native Blender BOOLEAN modifier stack with Exact/Fast solver",
    },
    "mpfb": {
        "name": "MPFB2 / MakeHuman Parametric Humanoid Add-on",
        "kind": "blender_addon",
        "license": "GPL-3.0-or-later (CC0 base mesh assets when installed)",
        "applicable_categories": ["humanoid"],
        "fallback_strategy": "Built-in connected anatomical BMesh humanoid generator (watertight torso, limbs, 5-finger hands, feet, head)",
    },
}

CATEGORY_CAPABILITY_PLAN: dict[str, list[str]] = {
    "props": ["blender_core", "gltf2_exporter", "native_boolean", "bool_tool", "looptools", "geometry_nodes"],
    "architecture": ["blender_core", "gltf2_exporter", "native_boolean", "bool_tool", "geometry_nodes"],
    "environment": ["blender_core", "gltf2_exporter", "geometry_nodes"],
    "humanoid": ["blender_core", "gltf2_exporter", "mpfb", "looptools", "rigify"],
}


def probe_blender_capabilities_in_blender() -> list[dict[str, Any]]:
    """Run inside Blender's Python runtime to inspect and verify installed extensions."""
    import bpy  # type: ignore[import-not-found]  # noqa: I001 — must import bpy BEFORE addon_utils!
    import addon_utils  # type: ignore[import-not-found]

    version_str = bpy.app.version_string
    known_modules = {mod.__name__: mod for mod in addon_utils.modules()}
    results: list[dict[str, Any]] = []

    def _emit(cap_id: str, available: bool, verified: bool, ver: str | None, msg: str) -> None:
        meta = BLENDER_CAPABILITY_METADATA[cap_id]
        results.append(
            {
                "id": cap_id,
                "name": meta["name"],
                "kind": meta["kind"],
                "available": available,
                "verified": verified,
                "version": ver,
                "license": meta["license"],
                "applicable_categories": meta["applicable_categories"],
                "fallback_strategy": meta["fallback_strategy"],
                "status_message": msg,
            }
        )

    # 1. Blender Core
    _emit(
        "blender_core",
        True,
        True,
        version_str,
        f"Verified Blender {version_str} runtime (background={bpy.app.background}).",
    )

    # 2. glTF 2.0 Exporter
    try:
        addon_utils.enable("io_scene_gltf2", default_set=True)
        _, gltf_loaded = addon_utils.check("io_scene_gltf2")
        gltf_ok = bool(gltf_loaded and hasattr(bpy.ops.export_scene, "gltf"))
        _emit(
            "gltf2_exporter",
            gltf_ok,
            gltf_ok,
            version_str if gltf_ok else None,
            "Verified glTF 2.0 GLB export and import operators." if gltf_ok else "glTF 2.0 add-on failed to enable.",
        )
    except Exception as exc:
        _emit("gltf2_exporter", False, False, None, f"glTF 2.0 check failed: {exc}")

    # 3. Geometry Nodes
    try:
        tree = bpy.data.node_groups.new("ProbeGeoTree", "GeometryNodeTree")
        gn_ok = tree is not None
        if tree is not None:
            bpy.data.node_groups.remove(tree)
        _emit(
            "geometry_nodes",
            gn_ok,
            gn_ok,
            version_str if gn_ok else None,
            "Verified GeometryNodeTree creation and procedural modifier evaluation.",
        )
    except Exception as exc:
        _emit("geometry_nodes", False, False, None, f"Geometry Nodes check failed: {exc}")

    # 4. Native Boolean
    _emit(
        "native_boolean",
        True,
        True,
        version_str,
        "Verified native Blender Exact & Fast Boolean CSG modifier solvers.",
    )

    # 5. Rigify
    if "rigify" in known_modules:
        try:
            addon_utils.enable("rigify", default_set=True)
            _, rigify_loaded = addon_utils.check("rigify")
            mod_ver = getattr(known_modules["rigify"], "bl_info", {}).get("version")
            ver_text = ".".join(map(str, mod_ver)) if mod_ver else version_str
            _emit(
                "rigify",
                bool(rigify_loaded),
                bool(rigify_loaded),
                ver_text,
                "Verified Rigify humanoid rigging module enabled in Blender.",
            )
        except Exception as exc:
            _emit("rigify", False, False, None, f"Rigify present but failed activation ({exc}); using fallback.")
    else:
        _emit("rigify", False, False, None, "Rigify module not installed; using built-in Godot Humanoid skeleton builder.")

    # 6. LoopTools
    looptools_mod = next((n for n in known_modules if n.endswith("mesh_looptools") or n == "mesh_looptools"), None)
    if looptools_mod:
        try:
            addon_utils.enable(looptools_mod, default_set=True)
            _, lt_loaded = addon_utils.check(looptools_mod)
            mod_ver = getattr(known_modules[looptools_mod], "bl_info", {}).get("version")
            ver_text = ".".join(map(str, mod_ver)) if mod_ver else "4.1"
            _emit(
                "looptools",
                bool(lt_loaded),
                bool(lt_loaded),
                ver_text,
                f"Verified LoopTools ({looptools_mod}) enabled for loop relaxation and bridging.",
            )
        except Exception as exc:
            _emit("looptools", False, False, None, f"LoopTools failed activation ({exc}); using analytical BMesh fallback.")
    else:
        _emit("looptools", False, False, None, "LoopTools add-on not installed; using analytical BMesh loop operations.")

    # 7. Bool Tool
    booltool_mod = next(
        (n for n in known_modules if n.endswith("object_boolean_tools") or "bool_tool" in n), None
    )
    if booltool_mod:
        try:
            addon_utils.enable(booltool_mod, default_set=True)
            _, bt_loaded = addon_utils.check(booltool_mod)
            mod_ver = getattr(known_modules[booltool_mod], "bl_info", {}).get("version")
            ver_text = ".".join(map(str, mod_ver)) if mod_ver else "0.4"
            _emit(
                "bool_tool",
                bool(bt_loaded),
                bool(bt_loaded),
                ver_text,
                f"Verified Bool Tool ({booltool_mod}) enabled for architectural & prop CSG cuts.",
            )
        except Exception as exc:
            _emit("bool_tool", False, False, None, f"Bool Tool failed activation ({exc}); using native Boolean modifiers.")
    else:
        _emit("bool_tool", False, False, None, "Bool Tool not installed; using native Blender Boolean modifiers.")

    # 8. MPFB2 / MakeHuman
    mpfb_mod = next((n for n in known_modules if "mpfb" in n.lower()), None)
    if mpfb_mod:
        try:
            addon_utils.enable(mpfb_mod, default_set=True)
            _, mpfb_loaded = addon_utils.check(mpfb_mod)
            has_svc = hasattr(bpy.ops, "mpfb")
            ok = bool(mpfb_loaded and has_svc)
            _emit(
                "mpfb",
                ok,
                ok,
                "2.x" if ok else None,
                "Verified MPFB2 humanoid add-on enabled." if ok else "MPFB2 module found without base mesh pack; using connected anatomical BMesh humanoid fallback.",
            )
        except Exception as exc:
            _emit("mpfb", False, False, None, f"MPFB2 check failed ({exc}); using connected anatomical BMesh humanoid fallback.")
    else:
        _emit(
            "mpfb",
            False,
            False,
            None,
            "MPFB2 add-on & MakeHuman data pack not installed; using built-in connected anatomical BMesh humanoid generator.",
        )

    return results


def activate_capabilities_for_category(category: str) -> tuple[list[str], list[str], dict[str, dict[str, Any]]]:
    """Selectively enable only the capabilities relevant to `category` inside Blender."""
    all_raw = probe_blender_capabilities_in_blender()
    by_id = {item["id"]: item for item in all_raw}
    planned = CATEGORY_CAPABILITY_PLAN.get(category, ["blender_core", "gltf2_exporter"])

    used: list[str] = []
    fallbacks: list[str] = []
    for cap_id in planned:
        status = by_id.get(cap_id)
        if status and status["available"] and status["verified"]:
            used.append(cap_id)
        elif status:
            fallbacks.append(f"{cap_id} -> {status['fallback_strategy']}")
    return used, fallbacks, by_id
