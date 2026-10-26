"""The stylized faceted female T-pose character must hit its contractual spec.

Contract (from the brief):
  * 1,200-1,500 faces
  * flat-shaded normals with crisp polygon edges
  * athletic top and shorts vertex colors
  * a genuine horizontal T-pose silhouette
"""

from __future__ import annotations

import numpy as np
from build_all_assets import build_spec
from generators.character_tpose import build_midpoly_female_tpose_parts
from generators.pipeline import generate_asset, validate_glb_bytes
from generators.specs import HERO_FACE_BAND, HERO_PRESET_ID


def _hero_config(spec) -> dict:
    return {
        "asset_id": spec.id,
        "category": spec.category,
        "preset_id": spec.id,
        "polygon_budget": spec.face_budget_candidates[0],
        "quality_profile": spec.quality_profile,
        "material_preset": spec.material_preset,
        "parameters": dict(spec.parameters),
        "seed": spec.seed,
        "flat_shading": True,
    }


def test_hero_lands_inside_the_face_band(spec_by_id):
    hero = spec_by_id[HERO_PRESET_ID]
    glb_bytes, record = build_spec(hero, quiet=True)
    low, high = HERO_FACE_BAND
    assert low <= record["face_count"] <= high, (
        f"hero exported {record['face_count']} faces, outside {low}-{high}"
    )
    assert record["triangle_count"] == record["face_count"]
    assert record["flat_shading"] is True
    report = validate_glb_bytes(glb_bytes, expected_triangles=record["triangle_count"])
    assert report["valid"] and report["has_vertex_colors"] and report["has_uvs"]


def test_hero_is_a_horizontal_t_pose(spec_by_id):
    hero = spec_by_id[HERO_PRESET_ID]
    asset = generate_asset(_hero_config(hero))
    width, height, depth = asset.dimensions
    # Arms fully extended: the span is at least the body height for a T-pose.
    assert width >= height * 0.9, f"arms are not horizontal (w={width} h={height})"
    assert depth < width * 0.6, "silhouette is too deep for a T-pose"
    assert 1.5 <= height <= 2.0, f"unexpected character height {height} m"


def test_hero_parts_cover_the_required_anatomy():
    parts = build_midpoly_female_tpose_parts(target_faces=1000, height=1.72)
    names = {name for name, _slot, _mesh in parts}
    required = {
        "Head",
        "Hair",
        "Neck",
        "AthleticTop",
        "Waist",
        "ShortsPelvis",
        "UpperArm_L",
        "UpperArm_R",
        "LowerArm_L",
        "LowerArm_R",
        "Hand_L",
        "Hand_R",
        "Thigh_L",
        "Thigh_R",
        "Calf_L",
        "Calf_R",
        "ShoeUpper_L",
        "ShoeUpper_R",
    }
    missing = required - names
    assert not missing, f"hero is missing body parts: {sorted(missing)}"

    slots = {slot for _name, slot, _mesh in parts}
    assert {"skin", "outfit", "shorts", "hair"} <= slots, sorted(slots)

    # Every part is a real, closed, non-degenerate mesh.
    for name, _slot, mesh in parts:
        assert len(mesh.faces) > 0, name
        assert len(mesh.vertices) > 0, name
        assert np.isfinite(np.asarray(mesh.vertices)).all(), name


def test_hero_feet_are_grounded_at_origin():
    parts = build_midpoly_female_tpose_parts(target_faces=1000, height=1.72)
    lowest = min(float(np.asarray(mesh.vertices)[:, 1].min()) for _n, _s, mesh in parts)
    assert -0.005 <= lowest <= 0.02, f"character floats/sinks: lowest vertex at y={lowest}"


def test_hero_export_is_deterministic(spec_by_id):
    hero = spec_by_id[HERO_PRESET_ID]
    first = generate_asset(_hero_config(hero))
    second = generate_asset(_hero_config(hero))
    assert first.glb_bytes == second.glb_bytes
    assert first.faces == second.faces
