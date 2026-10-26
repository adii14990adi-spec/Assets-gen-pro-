"""Tests for the dual-engine Capability Registry and honest fallback reporting."""

from __future__ import annotations

from backend.blender.runtime import detect_blender_runtime
from backend.enums import AssetCategory
from backend.integrations.registry import CapabilityRegistry

BLENDER_CAPABILITY_IDS = (
    "blender_core",
    "gltf2_exporter",
    "geometry_nodes",
    "native_boolean",
    "rigify",
    "looptools",
    "bool_tool",
    "mpfb",
)


def test_capability_registry_reports_python_engine_and_blender_state_honestly() -> None:
    registry = CapabilityRegistry(cache_ttl_seconds=0.0)
    caps = registry.list_capabilities(force_refresh=True)
    by_id = {c.id: c for c in caps}
    blender_present, _ = detect_blender_runtime()

    # The pure-Python fallback engine and Trimesh must ALWAYS be verified:
    # they are what makes Blender-free hosts (Render Native Python) work.
    for required_id in ("python_fallback_engine", "trimesh"):
        assert required_id in by_id, f"Missing capability entry: {required_id}"
        assert by_id[required_id].available is True, by_id[required_id].status_message
        assert by_id[required_id].verified is True

    for cap_id in BLENDER_CAPABILITY_IDS:
        assert cap_id in by_id, f"Missing capability entry: {cap_id}"

    if blender_present:
        # Full Blender environment (workstation / blender-e2e CI job).
        for required_id in ("blender_core", "gltf2_exporter", "geometry_nodes", "native_boolean", "rigify"):
            assert by_id[required_id].available is True, f"{required_id}: {by_id[required_id].status_message}"
            assert by_id[required_id].verified is True
    else:
        # Blender-free environment: Blender capabilities must be reported
        # unavailable with the Python fallback called out — never faked.
        for cap_id in BLENDER_CAPABILITY_IDS:
            assert by_id[cap_id].available is False
            assert by_id[cap_id].verified is False
            assert "fall back" in by_id[cap_id].status_message.lower() or "fallback" in by_id[cap_id].status_message.lower()

    # Every capability (installed or fallback) declares license + strategy.
    for cap in caps:
        assert cap.license
        assert cap.fallback_strategy
        assert cap.status_message

    # MPFB honesty: without the MakeHuman asset pack it must say so.
    if not by_id["mpfb"].available:
        assert "anatomical BMesh humanoid" in by_id["mpfb"].fallback_strategy


def test_capability_selection_is_scoped_by_asset_category() -> None:
    registry = CapabilityRegistry()
    blender_present, _ = detect_blender_runtime()

    props_plan = registry.select_for_category(AssetCategory.PROPS)
    props_ids = {c.id for c in props_plan["active"] + props_plan["fallback"]}
    assert "rigify" not in props_ids
    assert "mpfb" not in props_ids
    assert "python_fallback_engine" in {c.id for c in props_plan["active"]}

    human_plan = registry.select_for_category(AssetCategory.HUMANOID)
    human_active_ids = {c.id for c in human_plan["active"]}
    human_fallback_ids = {c.id for c in human_plan["fallback"]}
    assert "python_fallback_engine" in human_active_ids
    if blender_present:
        assert "rigify" in human_active_ids
        assert "blender_core" in human_active_ids
    else:
        assert "rigify" in human_fallback_ids
        assert "blender_core" in human_fallback_ids
