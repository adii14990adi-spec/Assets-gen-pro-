"""Unified Capability Registry combining Blender subprocess probes and Python library adapters."""

from __future__ import annotations

import json
import time
from functools import lru_cache

from backend.blender.runtime import run_blender_json_probe
from backend.integrations.blender_addons import BLENDER_CAPABILITY_METADATA, CATEGORY_CAPABILITY_PLAN
from backend.integrations.mesh_libs import Open3DAdapter, PyMeshLabAdapter, TrimeshAdapter
from backend.schemas import AssetCategory, CapabilityStatus


class CapabilityRegistry:
    """Discovers, verifies, caches, and selects capabilities per asset category."""

    def __init__(self, cache_ttl_seconds: float = 120.0) -> None:
        self._cache_ttl = cache_ttl_seconds
        self._cached_at: float = 0.0
        self._cached_items: list[CapabilityStatus] | None = None
        self._python_adapters = [TrimeshAdapter(), PyMeshLabAdapter(), Open3DAdapter()]

    def list_capabilities(self, force_refresh: bool = False) -> list[CapabilityStatus]:
        now = time.monotonic()
        if not force_refresh and self._cached_items is not None and (now - self._cached_at) < self._cache_ttl:
            return list(self._cached_items)

        statuses: list[CapabilityStatus] = []

        # 1. Probe Blender capabilities inside Blender's isolated Python runtime
        ok, payload, error_msg = run_blender_json_probe()
        if ok and isinstance(payload, list):
            for entry in payload:
                statuses.append(CapabilityStatus.model_validate(entry))
        else:
            for cap_id, meta in BLENDER_CAPABILITY_METADATA.items():
                statuses.append(
                    CapabilityStatus(
                        id=cap_id,
                        name=meta["name"],
                        kind=meta["kind"],
                        available=False,
                        verified=False,
                        version=None,
                        license=meta["license"],
                        applicable_categories=[AssetCategory(c) for c in meta["applicable_categories"]],
                        fallback_strategy=meta["fallback_strategy"],
                        status_message=f"Blender runtime unavailable ({error_msg or 'not configured'}). Run scripts/setup_blender_runtime.py.",
                    )
                )

        # 2. Probe Python mesh libraries in the backend runtime
        for adapter in self._python_adapters:
            statuses.append(adapter.detect())

        self._cached_items = statuses
        self._cached_at = now
        return list(statuses)

    def select_for_category(self, category: AssetCategory) -> dict[str, list[CapabilityStatus]]:
        all_caps = {c.id: c for c in self.list_capabilities()}
        planned_ids = list(CATEGORY_CAPABILITY_PLAN.get(category.value, []))
        for py_adapter in self._python_adapters:
            if py_adapter.applies_to(category):
                planned_ids.append(py_adapter.capability_id)

        active: list[CapabilityStatus] = []
        fallback: list[CapabilityStatus] = []
        for cap_id in planned_ids:
            cap = all_caps.get(cap_id)
            if not cap:
                continue
            if cap.available and cap.verified:
                active.append(cap)
            else:
                fallback.append(cap)
        return {"active": active, "fallback": fallback}

    def summary_json(self) -> str:
        return json.dumps([c.model_dump(mode="json") for c in self.list_capabilities()], indent=2)


@lru_cache(maxsize=1)
def get_capability_registry() -> CapabilityRegistry:
    return CapabilityRegistry()
