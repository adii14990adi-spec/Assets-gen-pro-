"""Tests for the Blender & Python Capability Registry and honest fallback reporting."""

from __future__ import annotations

from backend.enums import AssetCategory
from backend.integrations.registry import CapabilityRegistry


def test_capability_registry_verifies_blender_and_reports_fallbacks_honestly() -> None:
    registry = CapabilityRegistry(cache_ttl_seconds=0.0)
    caps = registry.list_capabilities(force_refresh=True)
    by_id = {c.id: c for c in caps}

    # Core required capabilities must be genuinely installed & verified
    for required_id in ("blender_core", "gltf2_exporter", "geometry_nodes", "native_boolean", "rigify", "trimesh"):
        assert required_id in by_id, f"Missing capability entry: {required_id}"
        assert by_id[required_id].available is True, f"{required_id} not available: {by_id[required_id].status_message}"
        assert by_id[required_id].verified is True

    # Every capability (whether installed or fallback) must declare a license and fallback strategy
    for cap in caps:
        assert cap.license
        assert cap.fallback_strategy
        assert cap.status_message

    # MPFB should be reported honestly: if MakeHuman data pack is not installed, available must be False
    assert "mpfb" in by_id
    if not by_id["mpfb"].available:
        assert "anatomical BMesh humanoid" in by_id["mpfb"].fallback_strategy


def test_capability_selection_is_scoped_by_asset_category() -> None:
    registry = CapabilityRegistry()
    props_plan = registry.select_for_category(AssetCategory.PROPS)
    props_ids = {c.id for c in props_plan["active"] + props_plan["fallback"]}
    assert "rigify" not in props_ids
    assert "mpfb" not in props_ids

    human_plan = registry.select_for_category(AssetCategory.HUMANOID)
    human_active_ids = {c.id for c in human_plan["active"]}
    assert "rigify" in human_active_ids
    assert "blender_core" in human_active_ids
