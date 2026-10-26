"""Base procedural generator context and parameter validation helpers."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from backend.enums import AssetCategory, QualityProfile


class ParameterValidationError(ValueError):
    """Raised when user-supplied procedural parameters violate schema bounds."""


@dataclass
class GenerationContext:
    """Normalized, deterministic configuration passed into Blender asset generators."""

    job_id: str
    asset_name: str
    category: AssetCategory
    preset_id: str
    quality_profile: QualityProfile
    seed: int
    polygon_budget: int
    material_preset: str
    parameters: dict[str, Any]
    capabilities_available: set[str] = field(default_factory=set)

    @property
    def detail_multiplier(self) -> float:
        if self.quality_profile == QualityProfile.PROTOTYPE:
            return 0.6
        if self.quality_profile == QualityProfile.DETAILED_MID_POLY:
            return 1.45
        return 1.0
