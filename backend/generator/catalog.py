"""Catalogue of asset categories, parameter specifications, quality budgets, and presets."""

from __future__ import annotations

import json
import pathlib
import re
from functools import lru_cache
from typing import Any

from backend.config import REPO_ROOT
from backend.generator.base import ParameterValidationError
from backend.schemas import (
    AssetCategory,
    AssetTypeInfo,
    ParameterOption,
    ParameterSpec,
    PolygonBudgetGuide,
    PresetInfo,
    QualityProfile,
)

_HEX_COLOR_RE = re.compile(r"^#?(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6})$")

SHARED_SHADING_SPECS: list[ParameterSpec] = [
    ParameterSpec(
        name="flat_shading",
        label="Flat Faceted Shading",
        type="bool",
        default=True,
        description="Unmerge vertices and compute crisp per-face normals for a faceted mid-poly look.",
        group="Shading & Colors",
    ),
    ParameterSpec(
        name="skin_color",
        label="Skin / Secondary Hex Color",
        type="color",
        default="",
        description="Optional #RRGGBB override applied directly to vertex/face colors.",
        group="Shading & Colors",
    ),
    ParameterSpec(
        name="outfit_color",
        label="Outfit / Primary Hex Color",
        type="color",
        default="",
        description="Optional #RRGGBB override applied directly to vertex/face colors.",
        group="Shading & Colors",
    ),
]

MATERIAL_PRESET_OPTIONS = [
    ParameterOption(value="default", label="Preset Default"),
    ParameterOption(value="rajasthan_sandstone", label="Rajasthani Pink/Red Sandstone"),
    ParameterOption(value="makrana_marble", label="Makrana Royal Marble & Gold"),
    ParameterOption(value="tactical_military", label="Tactical Olive & Gunmetal"),
    ParameterOption(value="desert_camo", label="Thar Desert Tan & Weathered Steel"),
    ParameterOption(value="aravalli_biome", label="Aravalli Scrubland & Granite"),
    ParameterOption(value="cyber_arena", label="Arena Carbon & Cobalt"),
]


ASSET_TYPES: dict[AssetCategory, AssetTypeInfo] = {
    AssetCategory.HUMANOID: AssetTypeInfo(
        category=AssetCategory.HUMANOID,
        name="Humanoid Characters",
        description="Connected anatomical athletic male & female combat characters with clothing, hair, tactical armor, backpack, and Godot 4 Skeleton3D rigging.",
        icon="user",
        godot_target_notes="Connected quad-dominant topology, max 4 bone weights/vertex, normalized skinning, Godot 4 SkeletonProfileHumanoid naming.",
        default_budgets={
            QualityProfile.PROTOTYPE: PolygonBudgetGuide(min_triangles=3500, target_triangles=8500, max_triangles=12000),
            QualityProfile.OPTIMIZED_MID_POLY: PolygonBudgetGuide(min_triangles=15000, target_triangles=28000, max_triangles=34000),
            QualityProfile.DETAILED_MID_POLY: PolygonBudgetGuide(min_triangles=20000, target_triangles=35000, max_triangles=45000),
        },
        recommended_capabilities=["blender_core", "gltf2_exporter", "rigify", "looptools", "mpfb", "trimesh"],
        parameter_specs=[
            ParameterSpec(
                name="gender",
                label="Body Archetype",
                type="select",
                default="male",
                group="Anatomy & Proportions",
                options=[
                    ParameterOption(value="male", label="Athletic Male"),
                    ParameterOption(value="female", label="Athletic Female"),
                ],
            ),
            ParameterSpec(
                name="height",
                label="Character Height",
                type="float",
                default=1.78,
                min_value=1.45,
                max_value=2.15,
                step=0.01,
                unit="m",
                group="Anatomy & Proportions",
            ),
            ParameterSpec(
                name="musculature",
                label="Athletic Build / Muscle Definition",
                type="float",
                default=0.55,
                min_value=0.1,
                max_value=1.0,
                step=0.05,
                group="Anatomy & Proportions",
            ),
            ParameterSpec(
                name="shoulder_width",
                label="Shoulder Scale",
                type="float",
                default=1.0,
                min_value=0.8,
                max_value=1.25,
                step=0.02,
                group="Anatomy & Proportions",
            ),
            ParameterSpec(
                name="hip_width",
                label="Pelvis / Hip Scale",
                type="float",
                default=1.0,
                min_value=0.8,
                max_value=1.25,
                step=0.02,
                group="Anatomy & Proportions",
            ),
            ParameterSpec(
                name="limb_length_scale",
                label="Limb Proportion Scale",
                type="float",
                default=1.0,
                min_value=0.88,
                max_value=1.12,
                step=0.02,
                group="Anatomy & Proportions",
            ),
            ParameterSpec(
                name="include_clothing",
                label="Tactical Shirt & Combat Trousers",
                type="bool",
                default=True,
                group="Loadout & Equipment",
            ),
            ParameterSpec(
                name="include_hair",
                label="Sculpted Hair Mesh",
                type="bool",
                default=True,
                group="Loadout & Equipment",
            ),
            ParameterSpec(
                name="include_shoes",
                label="Tactical Combat Boots",
                type="bool",
                default=True,
                group="Loadout & Equipment",
            ),
            ParameterSpec(
                name="include_armor",
                label="Plate Carrier Armor Vest",
                type="bool",
                default=False,
                group="Loadout & Equipment",
            ),
            ParameterSpec(
                name="include_backpack",
                label="Survival Field Backpack",
                type="bool",
                default=False,
                group="Loadout & Equipment",
            ),
            ParameterSpec(
                name="pose",
                label="Character Rest Pose",
                type="select",
                default="a_pose",
                group="Anatomy & Proportions",
                options=[
                    ParameterOption(value="t_pose", label="Symmetrical Horizontal T-Pose"),
                    ParameterOption(value="a_pose", label="Relaxed Combat A-Pose"),
                ],
            ),
            ParameterSpec(
                name="ponytail_length",
                label="Ponytail Length Scale",
                type="float",
                default=1.0,
                min_value=0.4,
                max_value=1.6,
                step=0.05,
                group="Loadout & Equipment",
            ),
            ParameterSpec(
                name="include_rig",
                label="Humanoid Armature & Normalized Skin Weights",
                type="bool",
                default=True,
                group="Rigging & Export",
            ),
            *SHARED_SHADING_SPECS,
        ],
    ),
    AssetCategory.ARCHITECTURE: AssetTypeInfo(
        category=AssetCategory.ARCHITECTURE,
        name="Architecture & Forts",
        description="Modular Rajasthani, Indian, and Battle Royale structures: Havelis with jharokha balconies, Rajput fort bastions, chhatri pavilions, arched pol gateways, and bridges.",
        icon="landmark",
        godot_target_notes="Snap-friendly metric footprints, walkable interior clearances, clean CSG portals, multi-slot PBR materials.",
        default_budgets={
            QualityProfile.PROTOTYPE: PolygonBudgetGuide(min_triangles=500, target_triangles=1800, max_triangles=3500),
            QualityProfile.OPTIMIZED_MID_POLY: PolygonBudgetGuide(min_triangles=1000, target_triangles=4200, max_triangles=8000),
            QualityProfile.DETAILED_MID_POLY: PolygonBudgetGuide(min_triangles=2500, target_triangles=6800, max_triangles=10000),
        },
        recommended_capabilities=["blender_core", "gltf2_exporter", "native_boolean", "bool_tool", "geometry_nodes", "trimesh"],
        parameter_specs=[
            ParameterSpec(
                name="width",
                label="Footprint Width (X)",
                type="float",
                default=8.0,
                min_value=3.0,
                max_value=28.0,
                step=0.5,
                unit="m",
                group="Dimensions",
            ),
            ParameterSpec(
                name="depth",
                label="Footprint Depth (Y)",
                type="float",
                default=7.0,
                min_value=2.5,
                max_value=28.0,
                step=0.5,
                unit="m",
                group="Dimensions",
            ),
            ParameterSpec(
                name="height",
                label="Structure Height (Z)",
                type="float",
                default=6.5,
                min_value=2.8,
                max_value=22.0,
                step=0.25,
                unit="m",
                group="Dimensions",
            ),
            ParameterSpec(
                name="wall_thickness",
                label="Wall Thickness",
                type="float",
                default=0.42,
                min_value=0.18,
                max_value=1.5,
                step=0.04,
                unit="m",
                group="Structural Features",
            ),
            ParameterSpec(
                name="opening_width",
                label="Portal / Arch Width",
                type="float",
                default=2.0,
                min_value=0.9,
                max_value=6.0,
                step=0.1,
                unit="m",
                group="Structural Features",
            ),
            ParameterSpec(
                name="opening_height",
                label="Portal / Arch Height",
                type="float",
                default=2.8,
                min_value=1.8,
                max_value=7.5,
                step=0.1,
                unit="m",
                group="Structural Features",
            ),
            ParameterSpec(
                name="floors",
                label="Stories / Tiers",
                type="int",
                default=2,
                min_value=1,
                max_value=4,
                step=1,
                group="Structural Features",
            ),
            ParameterSpec(
                name="arch_segments",
                label="Arch & Dome Smoothness",
                type="int",
                default=12,
                min_value=6,
                max_value=28,
                step=2,
                group="Ornament & Roof",
            ),
            ParameterSpec(
                name="roof_style",
                label="Roof / Crown Style",
                type="select",
                default="chhatri_parapet",
                group="Ornament & Roof",
                options=[
                    ParameterOption(value="chhatri_parapet", label="Kangura Parapet & Chhatri"),
                    ParameterOption(value="lotus_dome", label="Rajasthani Ribbed Dome"),
                    ParameterOption(value="flat_terrace", label="Fortified Flat Terrace"),
                    ParameterOption(value="stepped_shikhara", label="Stepped Tiered Crown"),
                ],
            ),
            ParameterSpec(
                name="decorative_detail",
                label="Jharokha / Kangura / Chhajja Detail",
                type="float",
                default=0.7,
                min_value=0.0,
                max_value=1.0,
                step=0.1,
                group="Ornament & Roof",
            ),
            *SHARED_SHADING_SPECS,
        ],
    ),
    AssetCategory.ENVIRONMENT: AssetTypeInfo(
        category=AssetCategory.ENVIRONMENT,
        name="Environment & Terrain",
        description="Procedural Battle Royale hills, plateaus, islands, river ravines, stratified desert rock outcrops, and stylized Indian foliage.",
        icon="mountain",
        godot_target_notes="Clean heightfield & manifold cliff meshes ready for Godot TrimeshStaticBody3D collision generation.",
        default_budgets={
            QualityProfile.PROTOTYPE: PolygonBudgetGuide(min_triangles=400, target_triangles=1500, max_triangles=3000),
            QualityProfile.OPTIMIZED_MID_POLY: PolygonBudgetGuide(min_triangles=1500, target_triangles=4800, max_triangles=9000),
            QualityProfile.DETAILED_MID_POLY: PolygonBudgetGuide(min_triangles=4000, target_triangles=9500, max_triangles=18000),
        },
        recommended_capabilities=["blender_core", "gltf2_exporter", "geometry_nodes", "trimesh"],
        parameter_specs=[
            ParameterSpec(
                name="width",
                label="Terrain Extent X",
                type="float",
                default=24.0,
                min_value=3.0,
                max_value=120.0,
                step=1.0,
                unit="m",
                group="Dimensions",
            ),
            ParameterSpec(
                name="depth",
                label="Terrain Extent Y",
                type="float",
                default=24.0,
                min_value=3.0,
                max_value=120.0,
                step=1.0,
                unit="m",
                group="Dimensions",
            ),
            ParameterSpec(
                name="elevation",
                label="Max Height / Canopy Height",
                type="float",
                default=6.5,
                min_value=1.0,
                max_value=35.0,
                step=0.5,
                unit="m",
                group="Terrain Relief",
            ),
            ParameterSpec(
                name="slope_intensity",
                label="Slope & Cliff Steepness",
                type="float",
                default=0.6,
                min_value=0.1,
                max_value=1.0,
                step=0.05,
                group="Terrain Relief",
            ),
            ParameterSpec(
                name="surface_roughness",
                label="Surface Variation / Strata Detail",
                type="float",
                default=0.5,
                min_value=0.05,
                max_value=1.0,
                step=0.05,
                group="Terrain Relief",
            ),
            ParameterSpec(
                name="terrace_steps",
                label="Plateau / Terrace Levels",
                type="int",
                default=3,
                min_value=0,
                max_value=10,
                step=1,
                group="Terrain Relief",
            ),
            ParameterSpec(
                name="scatter_density",
                label="Geometry Nodes Rock/Foliage Scatter",
                type="float",
                default=0.35,
                min_value=0.0,
                max_value=1.0,
                step=0.05,
                group="Scatter & Biome",
            ),
            *SHARED_SHADING_SPECS,
        ],
    ),
    AssetCategory.PROPS: AssetTypeInfo(
        category=AssetCategory.PROPS,
        name="Gameplay Props & Vehicles",
        description="Battle Royale supply crates, fuel barrels, tactical cover barriers, and off-road recon buggies optimized for mobile draw calls.",
        icon="box",
        godot_target_notes="Centered floor pivot (Z=0), clean hard-surface bevels, compact UV islands, mobile-friendly triangle counts.",
        default_budgets={
            QualityProfile.PROTOTYPE: PolygonBudgetGuide(min_triangles=200, target_triangles=550, max_triangles=1200),
            QualityProfile.OPTIMIZED_MID_POLY: PolygonBudgetGuide(min_triangles=300, target_triangles=1100, max_triangles=2500),
            QualityProfile.DETAILED_MID_POLY: PolygonBudgetGuide(min_triangles=700, target_triangles=2000, max_triangles=6000),
        },
        recommended_capabilities=["blender_core", "gltf2_exporter", "native_boolean", "bool_tool", "looptools", "trimesh"],
        parameter_specs=[
            ParameterSpec(
                name="width",
                label="Width (X)",
                type="float",
                default=1.2,
                min_value=0.3,
                max_value=6.0,
                step=0.05,
                unit="m",
                group="Dimensions",
            ),
            ParameterSpec(
                name="depth",
                label="Length / Depth (Y)",
                type="float",
                default=0.85,
                min_value=0.3,
                max_value=8.0,
                step=0.05,
                unit="m",
                group="Dimensions",
            ),
            ParameterSpec(
                name="height",
                label="Height (Z)",
                type="float",
                default=0.75,
                min_value=0.25,
                max_value=4.0,
                step=0.05,
                unit="m",
                group="Dimensions",
            ),
            ParameterSpec(
                name="bevel_amount",
                label="Edge Chamfer / Bevel Width",
                type="float",
                default=0.025,
                min_value=0.005,
                max_value=0.12,
                step=0.005,
                unit="m",
                group="Hard-Surface Detail",
            ),
            ParameterSpec(
                name="panel_detail",
                label="Ribbing / Hardware Detail",
                type="float",
                default=0.65,
                min_value=0.0,
                max_value=1.0,
                step=0.05,
                group="Hard-Surface Detail",
            ),
            ParameterSpec(
                name="wear_amount",
                label="Surface Roughness / Battle Wear",
                type="float",
                default=0.35,
                min_value=0.0,
                max_value=1.0,
                step=0.05,
                group="Hard-Surface Detail",
            ),
            *SHARED_SHADING_SPECS,
        ],
    ),
}


@lru_cache(maxsize=1)
def _load_presets_from_disk() -> dict[str, PresetInfo]:
    presets_root: pathlib.Path = REPO_ROOT / "presets"
    loaded: dict[str, PresetInfo] = {}
    if not presets_root.exists():
        return loaded
    for json_file in sorted(presets_root.rglob("*.json")):
        data = json.loads(json_file.read_text(encoding="utf-8"))
        preset = PresetInfo.model_validate(data)
        loaded[preset.id] = preset
    return loaded


def list_asset_types() -> list[AssetTypeInfo]:
    return list(ASSET_TYPES.values())


def get_asset_type_info(category: AssetCategory) -> AssetTypeInfo:
    return ASSET_TYPES[category]


def list_presets(category: AssetCategory | None = None) -> list[PresetInfo]:
    all_presets = list(_load_presets_from_disk().values())
    if category is not None:
        return [p for p in all_presets if p.category == category]
    return all_presets


PRESET_SHORTHAND_ALIASES: dict[str, str] = {
    "midpoly_character": "midpoly_character",
    "character": "midpoly_character",
    "humanoid": "midpoly_character",
    "female_tpose": "midpoly_character",
    "stylized_female_tpose": "midpoly_character",
    "architecture": "rajasthani_haveli",
    "building": "rajasthani_haveli",
    "haveli": "rajasthani_haveli",
    "fort": "rajput_fort_bastion",
    "terrain": "aravalli_ridge_terrain",
    "environment": "aravalli_ridge_terrain",
    "landscape": "aravalli_ridge_terrain",
    "island": "battle_royale_island",
    "tree": "stylized_banyan_tree",
    "prop": "br_supply_crate",
    "props": "br_supply_crate",
    "crate": "br_supply_crate",
    "barrel": "explosive_fuel_barrel",
    "vehicle": "desert_recon_buggy",
}


def get_preset(preset_id: str) -> PresetInfo | None:
    return _load_presets_from_disk().get(preset_id)


def resolve_preset_identifier(
    preset_or_id: str,
    explicit_category: AssetCategory | None = None,
) -> tuple[AssetCategory, PresetInfo]:
    """Resolve either a shorthand preset key (e.g. ``'midpoly_character'``, ``'terrain'``) or full preset ID."""
    cleaned = preset_or_id.strip().lower()
    mapped_id = PRESET_SHORTHAND_ALIASES.get(cleaned, cleaned)
    preset = get_preset(mapped_id)
    if preset is None:
        raise ParameterValidationError(
            f"Unknown preset '{preset_or_id}'. Supported shorthands: {sorted(PRESET_SHORTHAND_ALIASES.keys())}."
        )
    if explicit_category is not None and preset.category != explicit_category:
        raise ParameterValidationError(
            f"Preset '{preset.id}' belongs to category '{preset.category.value}', not '{explicit_category.value}'."
        )
    return preset.category, preset


def validate_and_merge_parameters(
    category: AssetCategory,
    preset_id: str,
    quality_profile: QualityProfile,
    user_params: dict[str, Any],
    explicit_budget: int | None = None,
) -> tuple[dict[str, Any], int, PresetInfo]:
    """Validate category + preset compatibility, coerce parameter types, and check bounds."""
    preset = get_preset(preset_id)
    if preset is None:
        raise ParameterValidationError(f"Unknown preset '{preset_id}'.")
    if preset.category != category:
        raise ParameterValidationError(
            f"Preset '{preset_id}' belongs to category '{preset.category.value}', not '{category.value}'."
        )

    type_info = get_asset_type_info(category)
    spec_map = {s.name: s for s in type_info.parameter_specs}

    merged: dict[str, Any] = {s.name: s.default for s in type_info.parameter_specs}
    merged.update(preset.parameters)

    unknown_keys = set(user_params.keys()) - set(spec_map.keys())
    if unknown_keys:
        raise ParameterValidationError(
            f"Unsupported parameters for category '{category.value}': {sorted(unknown_keys)}"
        )

    for key, raw_val in user_params.items():
        spec = spec_map[key]
        if spec.type == "bool":
            if not isinstance(raw_val, bool):
                raise ParameterValidationError(f"Parameter '{key}' must be a boolean.")
            merged[key] = raw_val
        elif spec.type == "int":
            if isinstance(raw_val, bool) or not isinstance(raw_val, (int, float)):
                raise ParameterValidationError(f"Parameter '{key}' must be an integer.")
            val = int(round(raw_val))
            if spec.min_value is not None and val < int(spec.min_value):
                raise ParameterValidationError(f"Parameter '{key}'={val} is below minimum {spec.min_value}.")
            if spec.max_value is not None and val > int(spec.max_value):
                raise ParameterValidationError(f"Parameter '{key}'={val} exceeds maximum {spec.max_value}.")
            merged[key] = val
        elif spec.type == "float":
            if isinstance(raw_val, bool) or not isinstance(raw_val, (int, float)):
                raise ParameterValidationError(f"Parameter '{key}' must be a number.")
            val_f = float(raw_val)
            if spec.min_value is not None and val_f < float(spec.min_value) - 1e-6:
                raise ParameterValidationError(f"Parameter '{key}'={val_f} is below minimum {spec.min_value}.")
            if spec.max_value is not None and val_f > float(spec.max_value) + 1e-6:
                raise ParameterValidationError(f"Parameter '{key}'={val_f} exceeds maximum {spec.max_value}.")
            merged[key] = round(val_f, 5)
        elif spec.type == "select":
            allowed = [o.value for o in (spec.options or [])]
            if not isinstance(raw_val, str) or raw_val not in allowed:
                raise ParameterValidationError(
                    f"Parameter '{key}' must be one of {allowed}, got {raw_val!r}."
                )
            merged[key] = raw_val
        elif spec.type == "color":
            if not isinstance(raw_val, str):
                raise ParameterValidationError(f"Parameter '{key}' must be a hex color string.")
            cleaned_hex = raw_val.strip()
            if cleaned_hex == "":
                merged[key] = ""
            elif not _HEX_COLOR_RE.match(cleaned_hex):
                raise ParameterValidationError(
                    f"Parameter '{key}'={raw_val!r} is not a valid hex color (#RRGGBB or #RGB)."
                )
            else:
                h = cleaned_hex.lstrip("#")
                if len(h) == 3:
                    h = "".join(c * 2 for c in h)
                merged[key] = f"#{h.lower()}"
        else:
            merged[key] = raw_val

    # Cross-parameter sanity checks for architecture openings
    if category == AssetCategory.ARCHITECTURE:
        max_open_w = max(0.6, float(merged["width"]) - 2.0 * float(merged["wall_thickness"]) - 0.25)
        if float(merged["opening_width"]) > max_open_w:
            merged["opening_width"] = round(max_open_w, 3)
        max_open_h = max(1.4, float(merged["height"]) - 0.55)
        if float(merged["opening_height"]) > max_open_h:
            merged["opening_height"] = round(max_open_h, 3)

    budget_guide = type_info.default_budgets[quality_profile]
    resolved_budget = explicit_budget if explicit_budget is not None else max(
        budget_guide.min_triangles,
        preset.polygon_budget if quality_profile == preset.quality_profile else budget_guide.target_triangles,
    )
    return merged, resolved_budget, preset
