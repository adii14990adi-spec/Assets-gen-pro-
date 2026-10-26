"""Pure-Python procedural 3D asset generators for the static GitHub Pages gallery.

Every model shipped by this repository is created by code in this package:
``numpy`` + ``scipy`` + ``trimesh`` on Python 3.11 (optionally Blade-less Blender
4.2 LTS ``bpy`` for verification only). Nothing is fetched, sculpted by hand, or
generated at page load time.
"""

from __future__ import annotations

from .pipeline import (
    BUILDERS,
    ENGINE_LABEL,
    GENERATOR_STRING,
    AssetGenerationError,
    GeneratedAsset,
    generate_asset,
    runtime_banner,
    validate_glb_bytes,
)
from .specs import (
    CATEGORY_META,
    CATEGORY_ORDER,
    HERO_FACE_BAND,
    HERO_PRESET_ID,
    AssetSpec,
    load_specs,
)

__all__ = [
    "BUILDERS",
    "CATEGORY_META",
    "CATEGORY_ORDER",
    "ENGINE_LABEL",
    "GENERATOR_STRING",
    "HERO_FACE_BAND",
    "HERO_PRESET_ID",
    "AssetGenerationError",
    "AssetSpec",
    "GeneratedAsset",
    "generate_asset",
    "load_specs",
    "runtime_banner",
    "validate_glb_bytes",
]
