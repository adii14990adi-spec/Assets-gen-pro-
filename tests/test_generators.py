"""Every generator must emit a spec-valid, flat-shaded, deterministic binary GLB."""

from __future__ import annotations

import json
import struct

import numpy as np
import pytest
from generators.pipeline import AssetGenerationError, generate_asset, validate_glb_bytes

# One representative preset per category keeps the suite fast while covering
# all four generator modules.
SAMPLE_PRESETS = [
    "midpoly_character",
    "rajasthani_haveli",
    "aravalli_ridge_terrain",
    "br_supply_crate",
]


def _config(spec, *, budget: int | None = None) -> dict:
    return {
        "asset_id": spec.id,
        "category": spec.category,
        "preset_id": spec.id,
        "polygon_budget": budget or spec.polygon_budget,
        "quality_profile": spec.quality_profile,
        "material_preset": spec.material_preset,
        "parameters": dict(spec.parameters),
        "seed": spec.seed,
        "flat_shading": spec.flat_shading,
    }


@pytest.fixture(scope="module")
def sample_assets(spec_by_id):
    return {preset: generate_asset(_config(spec_by_id[preset])) for preset in SAMPLE_PRESETS}


@pytest.mark.parametrize("preset", SAMPLE_PRESETS)
def test_glb_is_a_valid_gltf2_container(preset, sample_assets):
    asset = sample_assets[preset]
    report = validate_glb_bytes(asset.glb_bytes, expected_triangles=asset.triangles)
    assert report["valid"] is True
    assert report["version"] == 2
    assert report["byte_length"] == asset.file_size_bytes
    assert report["meshes"] == asset.mesh_count
    assert report["triangles"] == asset.triangles
    assert report["has_vertex_colors"] is True
    assert report["has_uvs"] is True
    assert report["generator"].startswith("AssetsGenPro")


@pytest.mark.parametrize("preset", SAMPLE_PRESETS)
def test_assets_are_grounded_and_non_empty(preset, sample_assets):
    asset = sample_assets[preset]
    assert asset.vertices > 0 and asset.faces > 0
    assert asset.triangles == asset.faces
    # Face-split (flat shaded) exports have exactly three vertices per triangle.
    assert asset.vertices == asset.triangles * 3
    x, y, z = asset.dimensions
    assert y > 0 and x > 0 and z > 0
    assert asset.file_size_bytes > 20_000


@pytest.mark.parametrize("preset", SAMPLE_PRESETS)
def test_flat_shading_has_per_face_normals(preset, sample_assets):
    """Flat faceted normals: the three corners of every triangle share a normal."""

    asset = sample_assets[preset]
    data = asset.glb_bytes
    json_len = struct.unpack_from("<I", data, 12)[0]
    gltf = json.loads(data[20 : 20 + json_len])
    pos_accessor = gltf["meshes"][0]["primitives"][0]["attributes"]["POSITION"]
    assert "min" in gltf["accessors"][pos_accessor]
    # Trimesh round-trip: a flat-shaded mesh has one normal per face, i.e. no
    # vertex is shared between triangles with different normals.
    import trimesh

    scene = trimesh.load(
        trimesh.util.wrap_as_stream(data), file_type="glb", force="scene", process=False
    )
    for geometry in scene.geometry.values():
        normals = np.asarray(geometry.vertex_normals)
        assert normals.shape[0] == len(geometry.vertices)
        # Consecutive triplets (corner order of the faceted export) are identical.
        triplets = normals.reshape(-1, 3, 3)
        assert np.allclose(triplets[:, 0], triplets[:, 1], atol=1e-5)
        assert np.allclose(triplets[:, 1], triplets[:, 2], atol=1e-5)


def _glb_meshes(data: bytes) -> dict[str, np.ndarray]:
    """Return ``{mesh_name: mean sRGB color}`` decoded straight from a GLB."""

    json_len = struct.unpack_from("<I", data, 12)[0]
    gltf = json.loads(data[20 : 20 + json_len])
    offset = 20 + json_len
    bin_len = struct.unpack_from("<I", data, offset)[0]
    bin_payload = data[offset + 8 : offset + 8 + bin_len]

    names: dict[int, str] = {}
    for node in gltf.get("nodes", []):
        if "mesh" in node:
            names.setdefault(node["mesh"], node.get("name", f"mesh_{node['mesh']}"))

    colors: dict[str, np.ndarray] = {}
    for mesh_index, mesh in enumerate(gltf["meshes"]):
        prim = mesh["primitives"][0]
        accessor = gltf["accessors"][prim["attributes"]["COLOR_0"]]
        view = gltf["bufferViews"][accessor["bufferView"]]
        start = view.get("byteOffset", 0) + accessor.get("byteOffset", 0)
        count = accessor["count"]
        raw = np.frombuffer(bin_payload, dtype=np.uint8, count=count * 4, offset=start)
        rgba = raw.reshape(count, 4).astype(np.float64) / 255.0
        # COLOR_0 is linear-space; convert back to sRGB for human-readable checks.
        linear = rgba[:, :3]
        srgb = np.where(
            linear <= 0.0031308, linear * 12.92, 1.055 * np.power(np.clip(linear, 0, None), 1 / 2.4) - 0.055
        )
        colors[names.get(mesh_index, mesh.get("name", f"mesh_{mesh_index}"))] = srgb.mean(axis=0)
    return colors


def test_vertex_colors_distinguish_outfit_parts(spec_by_id):
    """Athletic top and shorts must not collapse to the same vertex color."""

    hero = spec_by_id["midpoly_character"]
    asset = generate_asset(_config(hero, budget=1000))
    colors = _glb_meshes(asset.glb_bytes)
    assert colors, "expected vertex colors on the hero character"

    def pick(prefix: str) -> np.ndarray:
        for name, color in colors.items():
            if name.startswith(prefix):
                return color
        raise AssertionError(f"no mesh starting with {prefix!r} in {sorted(colors)}")

    torso = pick("AthleticTop")  # athletic sports top (blue outfit color)
    shorts = pick("ShortsPelvis")  # shorts (darkened outfit mix)
    skin = pick("Thigh")  # bare skin
    trim = pick("AthleticTopTrim")  # collar / hem trim accents
    assert not np.allclose(torso, shorts, atol=0.02), "top and shorts share one vertex color"
    assert not np.allclose(torso, skin, atol=0.02), "top and skin share one vertex color"
    assert not np.allclose(torso, trim, atol=0.02), "top and its trim share one vertex color"
    # The sports top is the blue outfit color; the shorts are a darker mix.
    assert torso[2] > torso[0], f"athletic top should be blue-ish, got {torso}"
    assert shorts.sum() < torso.sum(), "shorts should be darker than the top"


def test_generation_is_byte_for_byte_deterministic(spec_by_id):
    spec = spec_by_id["br_supply_crate"]
    first = generate_asset(_config(spec))
    second = generate_asset(_config(spec))
    assert first.glb_bytes == second.glb_bytes
    assert (first.vertices, first.faces) == (second.vertices, second.faces)


def test_polygon_budget_is_respected(spec_by_id):
    spec = spec_by_id["aravalli_ridge_terrain"]
    tight = generate_asset(_config(spec, budget=1200))
    loose = generate_asset(_config(spec, budget=spec.polygon_budget))
    assert tight.faces <= loose.faces
    assert tight.faces <= 2600, f"decmation failed: {tight.faces} faces for a 1,200 budget"


def test_unknown_category_raises(spec_by_id):
    config = _config(spec_by_id["br_supply_crate"])
    config["category"] = "vehicles"
    with pytest.raises(AssetGenerationError):
        generate_asset(config)


def test_truncated_glb_is_rejected(sample_assets):
    payload = sample_assets["br_supply_crate"].glb_bytes
    with pytest.raises(AssetGenerationError):
        validate_glb_bytes(payload[:-64])


def test_triangle_mismatch_is_rejected(sample_assets):
    asset = sample_assets["br_supply_crate"]
    with pytest.raises(AssetGenerationError):
        validate_glb_bytes(asset.glb_bytes, expected_triangles=asset.triangles + 3)
