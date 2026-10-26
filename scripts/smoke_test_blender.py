#!/usr/bin/env python3
"""Fast background smoke test verifying Blender runtime, mesh creation, and GLB roundtrip."""

from __future__ import annotations

import os
import pathlib
import subprocess
import sys
import tempfile


def main() -> int:
    repo_root = pathlib.Path(__file__).resolve().parent.parent
    runtime_py = pathlib.Path(
        os.environ.get(
            "BLENDER_PYTHON_EXECUTABLE",
            str(pathlib.Path.home() / ".local" / "blender-runtime" / "bin" / "python"),
        )
    )
    headless_libs = pathlib.Path(
        os.environ.get(
            "BLENDER_HEADLESS_LIBS",
            str(runtime_py.parent.parent / "headless-libs"),
        )
    )
    blender_bin = os.environ.get("BLENDER_EXECUTABLE", "")

    env = os.environ.copy()
    env["PYTHONPATH"] = str(repo_root)
    if headless_libs.exists():
        ld = env.get("LD_LIBRARY_PATH", "")
        env["LD_LIBRARY_PATH"] = f"{headless_libs}:{ld}" if ld else str(headless_libs)

    with tempfile.TemporaryDirectory(prefix="blender_smoke_") as tmpdir:
        glb_path = pathlib.Path(tmpdir) / "smoke.glb"
        inline_script = f"""
import bpy, os, sys
bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.mesh.primitive_cube_add(size=1.5)
obj = bpy.context.active_object
obj.name = "SmokeCube"
bpy.ops.export_scene.gltf(filepath={str(glb_path)!r}, export_format="GLB")
assert os.path.exists({str(glb_path)!r}), "GLB was not written"
assert os.path.getsize({str(glb_path)!r}) > 100, "GLB is unexpectedly small"
bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.gltf(filepath={str(glb_path)!r})
meshes = [o for o in bpy.data.objects if o.type == "MESH"]
assert len(meshes) == 1, f"Expected 1 mesh on re-import, got {{len(meshes)}}"
print("SMOKE_OK version=" + bpy.app.version_string + " bytes=" + str(os.path.getsize({str(glb_path)!r})))
sys.stdout.flush()
if "python" in os.path.basename(sys.executable).lower():
    os._exit(0)
"""
        script_file = pathlib.Path(tmpdir) / "smoke_runner.py"
        script_file.write_text(inline_script, encoding="utf-8")

        if blender_bin and pathlib.Path(blender_bin).exists():
            cmd = [blender_bin, "--background", "--factory-startup", "--python", str(script_file)]
        elif runtime_py.exists():
            cmd = [str(runtime_py), str(script_file)]
        else:
            print(f"ERROR: Neither BLENDER_EXECUTABLE nor {runtime_py} exists.", file=sys.stderr)
            return 1

        proc = subprocess.run(cmd, env=env, capture_output=True, text=True, timeout=60)
        print(proc.stdout)
        if proc.returncode != 0:
            print(proc.stderr, file=sys.stderr)
            return proc.returncode
        if "SMOKE_OK" not in proc.stdout:
            print("ERROR: SMOKE_OK marker missing from output", file=sys.stderr)
            return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
