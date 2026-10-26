"""Declarative catalogue of every 3D asset the static gallery ships.

Asset definitions are read from the versioned ``presets/`` JSON files (names,
descriptions, tags, material themes, polygon budgets, and generator
parameters) and annotated here with the exact Python script that produces each
model, the deterministic seed, and any gallery-specific overrides.
"""

from __future__ import annotations

import json
import pathlib
from dataclasses import dataclass, field
from typing import Any

CATEGORY_ORDER: tuple[str, ...] = ("humanoid", "architecture", "environment", "props")

CATEGORY_META: dict[str, dict[str, str]] = {
    "humanoid": {
        "label": "Humanoid Characters",
        "description": (
            "Connected, flat-shaded mid-poly combat characters with athletic sportswear, "
            "sculpted hair, and tactical loadout variants."
        ),
        "script": "scripts/generators/humanoid.py",
    },
    "architecture": {
        "label": "Rajasthani & Modular Architecture",
        "description": (
            "Enterable sandstone havelis, fort bastions, chhatri pavilions, cusped arch "
            "gateways, and stone arch bridges."
        ),
        "script": "scripts/generators/architecture.py",
    },
    "environment": {
        "label": "Environment & Terrain",
        "description": (
            "Multi-octave fBm terrain solids, battle royale islands, river ravines, "
            "desert outcrops, and stylized banyan trees."
        ),
        "script": "scripts/generators/terrain.py",
    },
    "props": {
        "label": "Props, Gear & Vehicles",
        "description": "Battle royale crates, fuel barrels, cover barriers, and recon buggies.",
        "script": "scripts/generators/props.py",
    },
}

# Preset-specific script overrides (the hero character has its own generator).
SCRIPT_OVERRIDES: dict[str, str] = {
    "midpoly_character": "scripts/generators/character_tpose.py",
}

DEFAULT_SEED = 1727

# Hero asset: a stylized faceted mid-poly female T-pose character that must land
# inside a 1,200-1,500 face window. The generator's ring density is quantized, so
# the build tries these polygon budgets in order until the exported face count
# falls inside HERO_FACE_BAND. (1,000 lands at ~1,424 faces on the pinned stack.)
HERO_PRESET_ID = "midpoly_character"
HERO_FACE_BAND: tuple[int, int] = (1200, 1500)
HERO_BUDGET_LADDER: tuple[int, ...] = (1000, 950, 1050, 900, 1100, 1200, 1300, 850)


@dataclass(frozen=True)
class AssetSpec:
    """Fully-resolved recipe for one generated model."""

    id: str
    name: str
    category: str
    description: str
    material_preset: str
    quality_profile: str
    polygon_budget: int
    parameters: dict[str, Any] = field(default_factory=dict)
    tags: tuple[str, ...] = ()
    seed: int = DEFAULT_SEED
    flat_shading: bool = True
    script_source: str = ""
    face_band: tuple[int, int] | None = None
    budget_ladder: tuple[int, ...] = ()

    @property
    def face_budget_candidates(self) -> tuple[int, ...]:
        """Budgets to attempt, in order, until the face band is satisfied."""
        if not self.face_band:
            return (self.polygon_budget,)
        ladder = self.budget_ladder or HERO_BUDGET_LADDER
        ordered = (self.polygon_budget, *(b for b in ladder if b != self.polygon_budget))
        return ordered


def _script_for(preset_id: str, category: str) -> str:
    if preset_id in SCRIPT_OVERRIDES:
        return SCRIPT_OVERRIDES[preset_id]
    meta = CATEGORY_META.get(category)
    if meta is None:
        raise ValueError(f"Unknown asset category {category!r} for preset {preset_id!r}.")
    return meta["script"]


def load_specs(repo_root: pathlib.Path) -> list[AssetSpec]:
    """Load and annotate every preset JSON under ``<repo_root>/presets``."""

    presets_root = repo_root / "presets"
    if not presets_root.is_dir():
        raise FileNotFoundError(f"Preset directory not found: {presets_root}")

    specs: list[AssetSpec] = []
    for preset_file in sorted(presets_root.rglob("*.json")):
        data = json.loads(preset_file.read_text(encoding="utf-8"))
        preset_id = str(data["id"])
        category = str(data["category"])
        if category not in CATEGORY_META:
            raise ValueError(f"Preset {preset_id!r} has unsupported category {category!r}.")

        override_budget = None
        face_band = None
        ladder: tuple[int, ...] = ()
        if preset_id == HERO_PRESET_ID:
            face_band = HERO_FACE_BAND
            ladder = HERO_BUDGET_LADDER
            override_budget = HERO_BUDGET_LADDER[0]

        specs.append(
            AssetSpec(
                id=preset_id,
                name=str(data["name"]),
                category=category,
                description=str(data.get("description", "")),
                material_preset=str(data.get("material_preset", "default")),
                quality_profile=str(data.get("quality_profile", "optimized_mid_poly")),
                polygon_budget=int(override_budget or data.get("polygon_budget", 2200)),
                parameters=dict(data.get("parameters") or {}),
                tags=tuple(str(tag) for tag in data.get("tags", ())),
                seed=int(data.get("seed", DEFAULT_SEED)),
                flat_shading=bool((data.get("parameters") or {}).get("flat_shading", True)),
                script_source=_script_for(preset_id, category),
                face_band=face_band,
                budget_ladder=ladder,
            )
        )

    order = {category: index for index, category in enumerate(CATEGORY_ORDER)}
    specs.sort(key=lambda spec: (order.get(spec.category, len(order)), spec.name))
    return specs
