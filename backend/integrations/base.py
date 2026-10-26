"""Base adapter contract for Blender add-ons and Python mesh-processing libraries."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Literal

from backend.schemas import AssetCategory, CapabilityStatus


class CapabilityAdapter(ABC):
    """Abstract adapter isolating an optional modeling extension or mesh library."""

    capability_id: str
    display_name: str
    kind: Literal["blender_core", "blender_addon", "python_library"]
    license_name: str
    applicable_categories: list[AssetCategory]
    fallback_strategy: str

    @abstractmethod
    def detect(self) -> CapabilityStatus:
        """Probe whether the dependency is genuinely installed and functional."""

    def applies_to(self, category: AssetCategory) -> bool:
        return category in self.applicable_categories
