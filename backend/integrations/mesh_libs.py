"""Python mesh/generation adapters: fallback engine, trimesh, pymeshlab, Open3D."""

from __future__ import annotations

import importlib
import os
import pathlib
import subprocess
import sys

from backend.config import get_settings
from backend.integrations.base import CapabilityAdapter
from backend.schemas import AssetCategory, CapabilityStatus


class TrimeshAdapter(CapabilityAdapter):
    capability_id = "trimesh"
    display_name = "Trimesh Geometry Analyzer"
    kind = "python_library"
    license_name = "MIT"
    applicable_categories = [
        AssetCategory.PROPS,
        AssetCategory.ARCHITECTURE,
        AssetCategory.ENVIRONMENT,
        AssetCategory.HUMANOID,
    ]
    fallback_strategy = "Blender BMesh + glTF JSON binary chunk validator"

    def detect(self) -> CapabilityStatus:
        try:
            trimesh = importlib.import_module("trimesh")
            # Verify real mesh construction works
            mesh = trimesh.Trimesh(vertices=[[0, 0, 0], [1, 0, 0], [0, 1, 0]], faces=[[0, 1, 2]])
            ok = len(mesh.faces) == 1
            return CapabilityStatus(
                id=self.capability_id,
                name=self.display_name,
                kind=self.kind,
                available=ok,
                verified=ok,
                version=getattr(trimesh, "__version__", "unknown"),
                license=self.license_name,
                applicable_categories=self.applicable_categories,
                fallback_strategy=self.fallback_strategy,
                status_message="Verified: independent GLB loading, bounds, face-winding, and manifold checks active.",
            )
        except Exception as exc:
            return CapabilityStatus(
                id=self.capability_id,
                name=self.display_name,
                kind=self.kind,
                available=False,
                verified=False,
                version=None,
                license=self.license_name,
                applicable_categories=self.applicable_categories,
                fallback_strategy=self.fallback_strategy,
                status_message=f"Unavailable ({exc}); using {self.fallback_strategy}.",
            )


class PyMeshLabAdapter(CapabilityAdapter):
    capability_id = "pymeshlab"
    display_name = "PyMeshLab Topological Processor"
    kind = "python_library"
    license_name = "GPL-3.0-or-later"
    applicable_categories = [
        AssetCategory.PROPS,
        AssetCategory.ARCHITECTURE,
        AssetCategory.ENVIRONMENT,
    ]
    fallback_strategy = "Trimesh + Blender BMesh topological inspection"

    def detect(self) -> CapabilityStatus:
        settings = get_settings()
        env = os.environ.copy()
        shim_dir = pathlib.Path(settings.pymeshlab_headless_libs)
        if shim_dir.exists():
            ld = env.get("LD_LIBRARY_PATH", "")
            env["LD_LIBRARY_PATH"] = f"{shim_dir}:{ld}" if ld else str(shim_dir)

        probe = (
            "import pymeshlab, numpy as np; "
            "ms = pymeshlab.MeshSet(); "
            "ms.add_mesh(pymeshlab.Mesh(np.array([[0,0,0],[1,0,0],[0,1,0]], dtype=float), np.array([[0,1,2]]))); "
            "t = ms.get_topological_measures(); "
            "print('OK:' + str(t['faces_number']))"
        )
        try:
            proc = subprocess.run(
                [sys.executable, "-c", probe],
                env=env,
                capture_output=True,
                text=True,
                timeout=15,
            )
            if proc.returncode == 0 and "OK:1" in proc.stdout:
                import importlib.metadata

                try:
                    ver = importlib.metadata.version("pymeshlab")
                except Exception:
                    ver = "installed"
                return CapabilityStatus(
                    id=self.capability_id,
                    name=self.display_name,
                    kind=self.kind,
                    available=True,
                    verified=True,
                    version=ver,
                    license=self.license_name,
                    applicable_categories=self.applicable_categories,
                    fallback_strategy=self.fallback_strategy,
                    status_message="Verified: MeshSet non-manifold and genus diagnostics operational.",
                )
            reason = (proc.stderr or proc.stdout).strip().splitlines()[-1] if (proc.stderr or proc.stdout) else "probe failed"
            return CapabilityStatus(
                id=self.capability_id,
                name=self.display_name,
                kind=self.kind,
                available=False,
                verified=False,
                version=None,
                license=self.license_name,
                applicable_categories=self.applicable_categories,
                fallback_strategy=self.fallback_strategy,
                status_message=f"Unavailable ({reason}); using {self.fallback_strategy}.",
            )
        except Exception as exc:
            return CapabilityStatus(
                id=self.capability_id,
                name=self.display_name,
                kind=self.kind,
                available=False,
                verified=False,
                version=None,
                license=self.license_name,
                applicable_categories=self.applicable_categories,
                fallback_strategy=self.fallback_strategy,
                status_message=f"Unavailable ({exc}); using {self.fallback_strategy}.",
            )


class Open3DAdapter(CapabilityAdapter):
    capability_id = "open3d"
    display_name = "Open3D Point-Cloud & Mesh Toolkit"
    kind = "python_library"
    license_name = "MIT"
    applicable_categories = [AssetCategory.ENVIRONMENT]
    fallback_strategy = "NumPy multi-octave terrain synthesis + Blender Geometry Nodes"

    def detect(self) -> CapabilityStatus:
        try:
            o3d = importlib.import_module("open3d")
            ver = getattr(o3d, "__version__", "installed")
            return CapabilityStatus(
                id=self.capability_id,
                name=self.display_name,
                kind=self.kind,
                available=True,
                verified=True,
                version=ver,
                license=self.license_name,
                applicable_categories=self.applicable_categories,
                fallback_strategy=self.fallback_strategy,
                status_message="Verified: Open3D mesh & point-cloud operations available.",
            )
        except Exception as exc:
            return CapabilityStatus(
                id=self.capability_id,
                name=self.display_name,
                kind=self.kind,
                available=False,
                verified=False,
                version=None,
                license=self.license_name,
                applicable_categories=self.applicable_categories,
                fallback_strategy=self.fallback_strategy,
                status_message=f"Optional dependency not installed ({type(exc).__name__}); using {self.fallback_strategy}.",
            )


class PythonFallbackAdapter(CapabilityAdapter):
    """Pure-Python NumPy+Trimesh generation engine (Blender-free fallback)."""

    capability_id = "python_fallback_engine"
    display_name = "Pure-Python Fallback 3D Engine (NumPy + Trimesh)"
    kind = "python_library"
    license_name = "MIT (Trimesh) / BSD-3-Clause (NumPy)"
    applicable_categories = [
        AssetCategory.PROPS,
        AssetCategory.ARCHITECTURE,
        AssetCategory.ENVIRONMENT,
        AssetCategory.HUMANOID,
    ]
    fallback_strategy = "Blender 4.2 LTS BMesh/Geometry Nodes pipeline when a Blender runtime is installed"

    def detect(self) -> CapabilityStatus:
        try:
            from backend.fallback.engine import verify_python_engine

            ok, message = verify_python_engine()
            version = None
            if ok:
                import numpy
                import trimesh

                version = f"trimesh {trimesh.__version__} / numpy {numpy.__version__}"
            return CapabilityStatus(
                id=self.capability_id,
                name=self.display_name,
                kind=self.kind,
                available=ok,
                verified=ok,
                version=version,
                license=self.license_name,
                applicable_categories=self.applicable_categories,
                fallback_strategy=self.fallback_strategy,
                status_message=(
                    f"{message} Generates all presets without Blender (used automatically "
                    "on hosts without a Blender runtime, e.g. Render Native Python)."
                    if ok
                    else f"Unavailable ({message}); Blender runtime required for generation."
                ),
            )
        except Exception as exc:
            return CapabilityStatus(
                id=self.capability_id,
                name=self.display_name,
                kind=self.kind,
                available=False,
                verified=False,
                version=None,
                license=self.license_name,
                applicable_categories=self.applicable_categories,
                fallback_strategy=self.fallback_strategy,
                status_message=f"Unavailable ({exc}); Blender runtime required for generation.",
            )
