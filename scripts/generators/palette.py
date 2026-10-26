"""Deterministic PBR material palettes for the procedural generators.

Every palette entry is a glTF 2.0 ``pbrMetallicRoughness`` factor triple
(sRGB base color, metallic, roughness) so exports carry genuine PBR materials
without any texture downloads.
"""

from __future__ import annotations

from typing import Any

from .character_tpose import (
    DEFAULT_OUTFIT_HEX,
    DEFAULT_SKIN_HEX,
    HEX_COLOR_RE,
    build_character_palette,
    parse_hex_color,
)
from .glb_writer import GlbMaterial as PaletteMaterial

THEME_PALETTES: dict[str, dict[str, tuple[tuple[float, float, float], float, float, str]]] = {
    "rajasthan_sandstone": {
        "primary": ((0.76, 0.44, 0.35), 0.0, 0.78, "masonry"),
        "secondary": ((0.89, 0.78, 0.66), 0.0, 0.68, "sandstone"),
        "accent": ((0.94, 0.92, 0.88), 0.02, 0.42, "marble"),
        "trim": ((0.29, 0.19, 0.12), 0.05, 0.65, "wood"),
        "metal": ((0.26, 0.23, 0.20), 0.82, 0.42, "metal"),
    },
    "makrana_marble": {
        "primary": ((0.93, 0.91, 0.88), 0.02, 0.34, "marble"),
        "secondary": ((0.82, 0.52, 0.42), 0.0, 0.72, "sandstone"),
        "accent": ((0.83, 0.67, 0.26), 0.88, 0.28, "metal"),
        "trim": ((0.35, 0.23, 0.15), 0.04, 0.62, "wood"),
        "metal": ((0.78, 0.62, 0.24), 0.90, 0.25, "metal"),
    },
    "tactical_military": {
        "primary": ((0.24, 0.29, 0.21), 0.04, 0.74, "fabric"),
        "secondary": ((0.17, 0.18, 0.20), 0.78, 0.38, "metal"),
        "accent": ((0.84, 0.56, 0.14), 0.15, 0.48, "stripe"),
        "trim": ((0.13, 0.13, 0.14), 0.12, 0.82, "rubber"),
        "metal": ((0.32, 0.34, 0.36), 0.88, 0.34, "metal"),
    },
    "desert_camo": {
        "primary": ((0.71, 0.61, 0.45), 0.03, 0.76, "fabric"),
        "secondary": ((0.36, 0.31, 0.25), 0.55, 0.48, "metal"),
        "accent": ((0.76, 0.31, 0.16), 0.12, 0.52, "stripe"),
        "trim": ((0.16, 0.15, 0.14), 0.08, 0.85, "rubber"),
        "metal": ((0.40, 0.38, 0.35), 0.85, 0.38, "metal"),
    },
    "aravalli_biome": {
        "primary": ((0.34, 0.45, 0.23), 0.0, 0.86, "foliage"),
        "secondary": ((0.52, 0.44, 0.36), 0.0, 0.88, "rock"),
        "accent": ((0.76, 0.67, 0.50), 0.0, 0.82, "sandstone"),
        "trim": ((0.33, 0.24, 0.16), 0.0, 0.84, "wood"),
        "water": ((0.14, 0.39, 0.48), 0.08, 0.16, "smooth"),
    },
    "cyber_arena": {
        "primary": ((0.16, 0.18, 0.23), 0.65, 0.35, "metal"),
        "secondary": ((0.11, 0.12, 0.15), 0.40, 0.50, "fabric"),
        "accent": ((0.16, 0.54, 0.92), 0.35, 0.28, "stripe"),
        "trim": ((0.09, 0.09, 0.11), 0.20, 0.75, "rubber"),
        "metal": ((0.58, 0.62, 0.68), 0.92, 0.24, "metal"),
    },
}


# Category-default material themes.
CATEGORY_DEFAULT_THEME: dict[str, str] = {
    "props": "tactical_military",
    "architecture": "rajasthan_sandstone",
    "environment": "aravalli_biome",
    "humanoid": "tactical_military",
}

# Extra non-theme slots (sRGB, metallic, roughness) used across categories.
EXTRA_SLOTS: dict[str, tuple[tuple[float, float, float], float, float]] = {
    "water": ((0.13, 0.38, 0.50), 0.05, 0.18),
    "skin": ((0.76, 0.55, 0.42), 0.0, 0.62),
    "hair": ((0.10, 0.08, 0.07), 0.0, 0.72),
    "sand": ((0.82, 0.72, 0.53), 0.0, 0.9),
    "foliage_dark": ((0.20, 0.32, 0.16), 0.0, 0.88),
    "glass_lamp": ((1.0, 0.82, 0.45), 0.1, 0.25),
}


def extract_hex_override(cfg: dict[str, Any], key: str) -> str | None:
    top_val = cfg.get(key)
    param_val = cfg.get("parameters", {}).get(key)
    for candidate in (top_val, param_val):
        if isinstance(candidate, str) and candidate.strip() and HEX_COLOR_RE.match(candidate.strip()):
            return candidate.strip()
    return None


def resolve_materials(cfg: dict[str, Any]) -> dict[str, PaletteMaterial]:
    category = str(cfg["category"])
    preset_id = str(cfg.get("preset_id", ""))
    requested = str(cfg.get("material_preset", "default"))
    theme = requested if requested in THEME_PALETTES else CATEGORY_DEFAULT_THEME[category]
    palette = THEME_PALETTES[theme]

    materials: dict[str, PaletteMaterial] = {}
    for slot, (rgb, metallic, roughness, _pattern) in palette.items():
        materials[slot] = PaletteMaterial(
            name=f"Mat_{theme}_{slot}",
            base_color_srgb=(rgb[0], rgb[1], rgb[2], 1.0),
            metallic=float(metallic),
            roughness=float(roughness),
        )
    for slot, (rgb, metallic, roughness) in EXTRA_SLOTS.items():
        materials.setdefault(
            slot,
            PaletteMaterial(
                name=f"Mat_{theme}_{slot}",
                base_color_srgb=(rgb[0], rgb[1], rgb[2], 1.0),
                metallic=float(metallic),
                roughness=float(roughness),
                emissive_srgb=(1.0, 0.72, 0.30) if slot == "glass_lamp" else None,
            ),
        )
    # Guarantee the standard slots exist even for palettes that omit them.
    for slot, donor in (("metal", "secondary"), ("accent", "primary"), ("trim", "secondary")):
        if slot not in materials and donor in materials:
            d = materials[donor]
            materials[slot] = PaletteMaterial(
                name=f"Mat_{theme}_{slot}",
                base_color_srgb=d.base_color_srgb,
                metallic=d.metallic,
                roughness=d.roughness,
            )

    skin_hex = extract_hex_override(cfg, "skin_color")
    outfit_hex = extract_hex_override(cfg, "outfit_color")

    if category == "humanoid":
        use_char_defaults = preset_id == "midpoly_character"
        eff_skin = skin_hex or (DEFAULT_SKIN_HEX if use_char_defaults else None)
        eff_outfit = outfit_hex or (DEFAULT_OUTFIT_HEX if use_char_defaults else None)
        char_pal = build_character_palette(
            skin_color=eff_skin or DEFAULT_SKIN_HEX,
            outfit_color=eff_outfit or DEFAULT_OUTFIT_HEX,
        )
        for slot_name, (rgb, met, rough) in char_pal.items():
            if slot_name == "skin" and eff_skin is None and not use_char_defaults:
                continue
            materials[slot_name] = PaletteMaterial(
                name=f"Mat_Char_{slot_name}",
                base_color_srgb=(rgb[0], rgb[1], rgb[2], 1.0),
                metallic=met,
                roughness=rough,
            )
        if eff_outfit is not None:
            materials["primary"] = materials["outfit"]
            materials["secondary"] = materials["shorts"]
            materials["accent"] = materials["outfit_accent"]
            materials["trim"] = materials["sole"]
    else:
        if outfit_hex is not None:
            orgb = parse_hex_color(outfit_hex, DEFAULT_OUTFIT_HEX)
            materials["primary"] = PaletteMaterial(
                name=f"Mat_{theme}_primary_custom",
                base_color_srgb=(orgb[0], orgb[1], orgb[2], 1.0),
                metallic=materials["primary"].metallic,
                roughness=materials["primary"].roughness,
            )
            materials["accent"] = PaletteMaterial(
                name=f"Mat_{theme}_accent_custom",
                base_color_srgb=(
                    min(1.0, orgb[0] * 1.12),
                    min(1.0, orgb[1] * 1.12),
                    min(1.0, orgb[2] * 1.12),
                    1.0,
                ),
                metallic=materials["accent"].metallic,
                roughness=materials["accent"].roughness,
            )
        if skin_hex is not None:
            srgb = parse_hex_color(skin_hex, DEFAULT_SKIN_HEX)
            materials["secondary"] = PaletteMaterial(
                name=f"Mat_{theme}_secondary_custom",
                base_color_srgb=(srgb[0], srgb[1], srgb[2], 1.0),
                metallic=materials["secondary"].metallic,
                roughness=materials["secondary"].roughness,
            )

    return materials
