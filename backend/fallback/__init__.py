"""Pure-Python procedural 3D fallback engine (NumPy + Trimesh).

Used automatically whenever no Blender runtime is available (e.g. Render
Native Python, slim containers, CI without a Blender install) so that 3D
generation requests NEVER fail with ``FileNotFoundError: 'blender'``.
"""

from backend.fallback.engine import ENGINE_NAME, generate_asset_python

__all__ = ["ENGINE_NAME", "generate_asset_python"]
