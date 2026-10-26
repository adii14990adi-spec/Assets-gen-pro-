#!/usr/bin/env python3
"""Bootstrap an isolated Blender 4.2 LTS Python 3.11 runtime and optional GPL add-ons.

This script creates a dedicated virtual environment (outside the FastAPI backend venv)
with `bpy==4.2.23` and `numpy==1.26.4`, installs verified official Blender Foundation
add-ons (`mesh_looptools`, `object_boolean_tools`) when reachable, and builds minimal
headless X11/GLX symbol shims ONLY when running inside bare Linux containers that do
not ship X11/OpenGL client shared libraries.
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import pathlib
import re
import shutil
import subprocess
import sys
import urllib.request

DEFAULT_RUNTIME_DIR = pathlib.Path.home() / ".local" / "blender-runtime"
DEFAULT_PYMESHLAB_SHIM_DIR = pathlib.Path.home() / ".local" / "pymeshlab-headless-libs"

BLENDER_ADDONS_API = {
    "mesh_looptools.py": "https://api.github.com/repos/blender/blender-addons/contents/mesh_looptools.py?ref=v4.1.1",
    "object_boolean_tools.py": "https://api.github.com/repos/blender/blender-addons/contents/object_boolean_tools.py?ref=v4.1.1",
}


def _find_missing_libs(binary: pathlib.Path) -> list[str]:
    if not binary.exists() or shutil.which("ldd") is None:
        return []
    out = subprocess.check_output(["ldd", str(binary)], text=True, stderr=subprocess.DEVNULL)
    missing: list[str] = []
    for line in out.splitlines():
        if "not found" in line:
            parts = line.strip().split()
            if parts:
                missing.append(parts[0])
    return missing


def _build_bpy_headless_stubs(site_packages: pathlib.Path, outdir: pathlib.Path) -> bool:
    """Compile minimal headless X11/GLX stub shared libraries when host lacks X11 client libs."""
    bpy_so = site_packages / "bpy" / "__init__.so"
    if not bpy_so.exists():
        return False

    missing_libs = _find_missing_libs(bpy_so)
    if not missing_libs and (outdir / "libGL.so.1").exists():
        return True
    if not missing_libs:
        print("[setup-blender] Host provides all shared libraries required by bpy.")
        return False

    if shutil.which("gcc") is None or shutil.which("nm") is None:
        print(f"[setup-blender] Warning: missing shared libs {missing_libs}, and gcc/nm not available.")
        return False

    outdir.mkdir(parents=True, exist_ok=True)
    for existing in outdir.glob("*.so*"):
        existing.unlink()

    targets = [
        bpy_so,
        site_packages / "bpy" / "lib" / "libMaterialXRenderHw.so.1",
        site_packages / "bpy" / "lib" / "libusd_ms.so",
    ]
    targets = [t for t in targets if t.exists()]

    resolved_libs: set[str] = set()
    for target in targets:
        ldd_out = subprocess.check_output(["ldd", str(target)], text=True, stderr=subprocess.DEVNULL)
        for line in ldd_out.splitlines():
            match = re.search(r"=>\s+(\S+)\s+\(0x", line)
            if match:
                resolved_libs.add(match.group(1))
    for libpy in pathlib.Path("/usr/lib/x86_64-linux-gnu").glob("libpython3.11*.so*"):
        resolved_libs.add(str(libpy))

    defined_syms: set[str] = set()
    for lib in resolved_libs:
        try:
            nm_out = subprocess.check_output(
                ["nm", "-D", "--defined-only", lib], text=True, stderr=subprocess.DEVNULL
            )
            for line in nm_out.splitlines():
                parts = line.split()
                if parts:
                    defined_syms.add(parts[-1].split("@")[0])
        except Exception:
            continue

    missing_syms: set[str] = set()
    for target in targets:
        nm_out = subprocess.check_output(["nm", "-D", "-u", str(target)], text=True, stderr=subprocess.DEVNULL)
        for line in nm_out.splitlines():
            parts = line.split()
            if not parts:
                continue
            sym = parts[-1].split("@")[0]
            if sym not in defined_syms and not sym.startswith(("Py", "_Py", "__", "_ITM", "_Jv")):
                missing_syms.add(sym)

    c_lines = ["/* Auto-generated headless X11/GLX stubs for bpy background execution */"]
    for sym in sorted(missing_syms):
        if not re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", sym):
            continue
        if sym in ("XtStrings", "applicationShellWidgetClass", "widgetClass", "topLevelShellWidgetClass"):
            c_lines.append(f"char {sym}[64] = {{0}};")
        else:
            c_lines.append(f"void* {sym}(void) {{ return 0; }}")

    stub_c = outdir / "stubs.c"
    stub_c.write_text("\n".join(c_lines) + "\n", encoding="utf-8")

    stub_lib_names = [
        "libXrender.so.1",
        "libXxf86vm.so.1",
        "libXfixes.so.3",
        "libXi.so.6",
        "libxkbcommon.so.0",
        "libSM.so.6",
        "libICE.so.6",
        "libGL.so.1",
        "libXt.so.6",
    ]
    for lib_name in stub_lib_names:
        subprocess.check_call(
            [
                "gcc",
                "-shared",
                "-fPIC",
                "-O2",
                f"-Wl,-soname,{lib_name}",
                str(stub_c),
                "-o",
                str(outdir / lib_name),
            ]
        )
    print(f"[setup-blender] Built {len(stub_lib_names)} headless X11/GLX shims ({len(missing_syms)} symbols) in {outdir}")
    return True


def _build_pymeshlab_gl_stubs(backend_venv: pathlib.Path | None, outdir: pathlib.Path) -> None:
    """Build minimal libGL/libGLU stubs for pymeshlab when running in bare headless containers."""
    if backend_venv is None:
        return
    pml_dir = backend_venv / "lib" / "python3.11" / "site-packages" / "pymeshlab" / "lib"
    if not pml_dir.exists() or shutil.which("gcc") is None or shutil.which("nm") is None:
        return
    glew_so = pml_dir / "libexternal-glew.so"
    if not _find_missing_libs(glew_so) and (outdir / "libGL.so.1").exists():
        return
    if not _find_missing_libs(glew_so):
        return

    outdir.mkdir(parents=True, exist_ok=True)
    gl_syms: set[str] = set()
    for so_file in pml_dir.glob("*.so*"):
        nm_out = subprocess.check_output(["nm", "-D", "-u", str(so_file)], text=True, stderr=subprocess.DEVNULL)
        for line in nm_out.splitlines():
            parts = line.split()
            if parts:
                sym = parts[-1].split("@")[0]
                if sym.startswith(("gl", "glu", "glX")) and sym not in ("glob", "glob64", "globfree", "globfree64"):
                    gl_syms.add(sym)

    gl_c = outdir / "gl_stubs.c"
    gl_c.write_text(
        "\n".join(
            f"void* {s}(void) {{ return 0; }}"
            for s in sorted(gl_syms)
            if re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", s)
        )
        + "\n",
        encoding="utf-8",
    )
    for lib_name in ["libGL.so.1", "libGLU.so.1", "libOpenGL.so.0", "libGLX.so.0"]:
        subprocess.check_call(
            ["gcc", "-shared", "-fPIC", "-O2", f"-Wl,-soname,{lib_name}", str(gl_c), "-o", str(outdir / lib_name)]
        )
    print(f"[setup-blender] Built pymeshlab headless GL shims in {outdir}")


def _install_gpl_addons(site_packages: pathlib.Path) -> None:
    addons_dir = site_packages / "bpy" / "4.2" / "scripts" / "addons_core"
    if not addons_dir.exists():
        return
    headers = {"Accept": "application/vnd.github+json", "User-Agent": "procedural-3d-asset-studio"}
    gh_token = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
    if gh_token:
        headers["Authorization"] = f"Bearer {gh_token}"

    for filename, api_url in BLENDER_ADDONS_API.items():
        dest = addons_dir / filename
        if dest.exists() and dest.stat().st_size > 1024:
            print(f"[setup-blender] Add-on already installed: {filename}")
            continue
        try:
            req = urllib.request.Request(api_url, headers=headers)
            with urllib.request.urlopen(req, timeout=20) as resp:
                payload = json.loads(resp.read().decode("utf-8"))
                raw_bytes = base64.b64decode(payload["content"])
                dest.write_bytes(raw_bytes)
                print(f"[setup-blender] Installed official Blender GPL add-on: {filename} ({len(raw_bytes)} bytes)")
        except Exception as exc:
            print(f"[setup-blender] Optional add-on {filename} skipped ({exc}); native fallback will be used.")


def main() -> int:
    parser = argparse.ArgumentParser(description="Setup isolated Blender 4.2 LTS runtime.")
    parser.add_argument("--runtime-dir", type=pathlib.Path, default=DEFAULT_RUNTIME_DIR)
    parser.add_argument("--backend-venv", type=pathlib.Path, default=pathlib.Path(".venv"))
    parser.add_argument("--skip-addons", action="store_true")
    args = parser.parse_args()

    runtime_dir: pathlib.Path = args.runtime_dir.resolve()
    python_bin = runtime_dir / "bin" / "python"
    pip_bin = runtime_dir / "bin" / "pip"

    if not python_bin.exists():
        print(f"[setup-blender] Creating isolated Python 3.11 venv at {runtime_dir}...")
        subprocess.check_call([sys.executable, "-m", "venv", str(runtime_dir)])
        subprocess.check_call([str(pip_bin), "install", "--upgrade", "pip"])

    site_packages = runtime_dir / "lib" / "python3.11" / "site-packages"
    if not (site_packages / "bpy" / "__init__.so").exists():
        print("[setup-blender] Installing bpy==4.2.23 and numpy==1.26.4...")
        subprocess.check_call([str(pip_bin), "install", "bpy==4.2.23", "numpy==1.26.4"])
    else:
        print("[setup-blender] bpy==4.2.23 already present in isolated runtime.")

    headless_libs = runtime_dir / "headless-libs"
    needs_shims = _build_bpy_headless_stubs(site_packages, headless_libs)
    if args.backend_venv.exists():
        _build_pymeshlab_gl_stubs(args.backend_venv.resolve(), DEFAULT_PYMESHLAB_SHIM_DIR)

    if not args.skip_addons:
        _install_gpl_addons(site_packages)

    env = os.environ.copy()
    if needs_shims or headless_libs.exists():
        existing_ld = env.get("LD_LIBRARY_PATH", "")
        env["LD_LIBRARY_PATH"] = f"{headless_libs}:{existing_ld}" if existing_ld else str(headless_libs)

    verify_code = (
        "import bpy, addon_utils, sys; "
        "print('Verified Blender runtime:', bpy.app.version_string, 'background=', bpy.app.background); "
        "sys.stdout.flush(); "
        "import os; os._exit(0)"
    )
    subprocess.check_call([str(python_bin), "-c", verify_code], env=env)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
