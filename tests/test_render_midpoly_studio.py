"""Tests for Render Python 3.11 deployment pins, pure-Python mid-poly T-pose
character generation, unified FastAPI routes, and the built-in Three.js Web Studio.
"""

from __future__ import annotations

import base64
import io
import json
import struct

import httpx
import numpy as np
import pytest
import trimesh

from backend.config import REPO_ROOT, Settings
from backend.fallback.engine import generate_glb_in_memory
from backend.main import create_app


def _extract_glb_color0_bytes(glb_bytes: bytes) -> np.ndarray:
    json_len = struct.unpack("<I", glb_bytes[12:16])[0]
    gltf = json.loads(glb_bytes[20 : 20 + json_len])
    bin_offset = 20 + json_len + 8
    bin_chunk = glb_bytes[bin_offset:]
    arrays: list[np.ndarray] = []
    for mesh in gltf["meshes"]:
        acc_idx = mesh["primitives"][0]["attributes"]["COLOR_0"]
        acc = gltf["accessors"][acc_idx]
        bv = gltf["bufferViews"][acc["bufferView"]]
        raw = bin_chunk[bv["byteOffset"] : bv["byteOffset"] + bv["byteLength"]]
        arrays.append(np.frombuffer(raw, dtype=np.uint8).reshape(-1, 4))
    return np.vstack(arrays)


def test_render_python_version_and_wheel_safe_manifests() -> None:
    py_ver = (REPO_ROOT / ".python-version").read_text(encoding="utf-8").strip()
    runtime_txt = (REPO_ROOT / "runtime.txt").read_text(encoding="utf-8").strip()
    assert py_ver == "3.11.11"
    assert runtime_txt == "python-3.11.11"

    req_lines = [
        line.strip()
        for line in (REPO_ROOT / "requirements.txt").read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]
    pyproject_text = (REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8")

    # Zero strict `==` pins in requirements.txt or pyproject.toml
    assert all("==" not in line for line in req_lines), f"Strict pin found in requirements.txt: {req_lines}"
    for line in pyproject_text.splitlines():
        stripped = line.strip().strip(",").strip('"')
        if any(
            stripped.startswith(pkg)
            for pkg in ("numpy", "scipy", "trimesh", "fastapi", "uvicorn", "pydantic", "bpy", "pymeshlab")
        ):
            assert "==" not in stripped, f"Strict pin found in pyproject.toml: {stripped}"

    joined_reqs = "\n".join(req_lines)
    assert "numpy>=1.26.4,<2.0.0" in joined_reqs
    assert "scipy>=1.11.4" in joined_reqs
    assert "trimesh>=4.0.0" in joined_reqs
    assert "fastapi>=0.115.0" in joined_reqs
    assert "uvicorn[standard]>=0.34.0" in joined_reqs
    assert "pydantic>=2.10.0" in joined_reqs
    assert "numpy>=1.26.4,<2.0.0" in pyproject_text


def test_in_memory_midpoly_female_tpose_character_anatomy_shading_and_colors() -> None:
    base_cfg = {
        "category": "humanoid",
        "preset_id": "midpoly_character",
        "quality_profile": "optimized_mid_poly",
        "seed": 42,
        "polygon_budget": 1800,
        "target_faces": 1800,
        "flat_shading": True,
        "skin_color": "#e6a88a",
        "outfit_color": "#3b82f6",
        "material_preset": "cyber_arena",
        "parameters": {"gender": "female", "pose": "t_pose", "height": 1.72},
    }

    flat_res = generate_glb_in_memory(base_cfg)
    assert isinstance(flat_res["glb_stream"], io.BytesIO)
    glb_bytes = flat_res["glb_stream"].read()
    assert glb_bytes[:4] == b"glTF"
    assert flat_res["triangles"] == flat_res["faces"] > 600
    # Flat shading unmerges vertices per triangle (3 vertices per triangle)
    assert flat_res["vertices"] == 3 * flat_res["triangles"]

    # Parse GLB JSON to verify required articulated T-pose character segments
    json_len = struct.unpack("<I", glb_bytes[12:16])[0]
    gltf = json.loads(glb_bytes[20 : 20 + json_len])
    mesh_names = {m["name"] for m in gltf["meshes"]}
    for expected_prefix in (
        "Head",
        "Hair",
        "Ponytail",
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
        "ShoeSole_L",
        "ShoeUpper_L",
    ):
        assert any(n.startswith(expected_prefix) for n in mesh_names), (
            f"Missing segment {expected_prefix!r} in {sorted(mesh_names)}"
        )

    # Verify symmetrical horizontal T-pose bounds & grounded feet (Y_min == 0)
    scene = trimesh.load(io.BytesIO(glb_bytes), file_type="glb", force="scene", process=False)
    bmin, bmax = scene.bounds
    assert abs(float(bmin[0]) + float(bmax[0])) < 0.02, f"T-pose X asymmetry: {bmin[0]} vs {bmax[0]}"
    assert (bmax[0] - bmin[0]) > 1.35, "Expected horizontal T-pose wingspan > 1.35m"
    assert abs(float(bmin[1])) < 1e-3, f"Expected character grounded at Y=0, got {bmin[1]}"
    assert 1.65 <= float(bmax[1]) <= 1.82

    # Smooth shading (`flat_shading=False`) must weld shared vertices (< 3 * triangles)
    smooth_cfg = {**base_cfg, "flat_shading": False}
    smooth_res = generate_glb_in_memory(smooth_cfg)
    assert smooth_res["triangles"] == flat_res["triangles"]
    assert smooth_res["vertices"] < flat_res["vertices"]

    # Changing skin_color / outfit_color must change the encoded COLOR_0 buffer bytes directly
    recolored_cfg = {**base_cfg, "skin_color": "#6b3e28", "outfit_color": "#ef4444"}
    recolored_res = generate_glb_in_memory(recolored_cfg)
    assert recolored_res["glb_bytes"] != flat_res["glb_bytes"]
    colors_a = _extract_glb_color0_bytes(flat_res["glb_bytes"])
    colors_b = _extract_glb_color0_bytes(recolored_res["glb_bytes"])
    assert colors_a.shape == colors_b.shape
    assert not np.array_equal(colors_a, colors_b)

    # Monotonic target_faces scaling across 400 -> 1800 -> 4500
    low_res = generate_glb_in_memory({**base_cfg, "polygon_budget": 450, "target_faces": 450})
    high_res = generate_glb_in_memory({**base_cfg, "polygon_budget": 4500, "target_faces": 4500})
    assert low_res["faces"] < flat_res["faces"] < high_res["faces"]


@pytest.mark.asyncio
async def test_live_generate_routes_json_and_binary_glb_and_builtin_studio(
    isolated_settings: Settings,
) -> None:
    app = create_app(isolated_settings)
    transport = httpx.ASGITransport(app=app)

    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            # 1. Built-in Three.js Web Studio HTML (always served at /studio, and at / when dist is absent)
            studio_resp = await client.get("/studio")
            assert studio_resp.status_code == 200
            html = studio_resp.text
            assert '<script type="importmap">' in html
            assert "GLTFLoader" in html
            assert "OrbitControls" in html
            assert "midpoly_character" in html

            if not (REPO_ROOT / "frontend" / "dist" / "index.html").exists():
                root_resp = await client.get("/")
                assert root_resp.status_code == 200
                assert '<script type="importmap">' in root_resp.text

            # 2. Health endpoint reports active 3D engine & package telemetry
            health = (await client.get("/api/health")).json()
            assert health["status"] == "ok"
            assert health["active_engine"] in ("python_procedural", "blender")
            assert "numpy" in health["packages"]
            assert "scipy" in health["packages"]
            assert "trimesh" in health["packages"]

            # 3. Direct POST /api/generate JSON response for midpoly_character, architecture, terrain, prop
            for preset_key in ("midpoly_character", "architecture", "terrain", "prop"):
                resp = await client.post(
                    "/api/generate",
                    json={
                        "preset": preset_key,
                        "target_faces": 1200,
                        "flat_shading": True,
                        "skin_color": "#e6a88a",
                        "outfit_color": "#10b981",
                        "seed": 77,
                    },
                )
                assert resp.status_code == 200, resp.text
                body = resp.json()
                assert body["status"] == "completed"
                assert body["vertices"] > 100
                assert body["faces"] > 50
                assert body["triangles"] >= body["faces"]
                assert body["file_size_kb"] > 1.0
                raw_glb = base64.b64decode(body["glb_base64"])
                assert raw_glb[:4] == b"glTF"
                assert len(raw_glb) == body["file_size_bytes"]

            # 4. Direct POST /api/generate streaming binary `model/gltf-binary`
            bin_resp = await client.post(
                "/api/generate?format=glb",
                json={
                    "preset": "midpoly_character",
                    "target_faces": 1500,
                    "flat_shading": True,
                    "skin_color": "#c98562",
                    "outfit_color": "#ef4444",
                    "seed": 99,
                },
            )
            assert bin_resp.status_code == 200
            assert bin_resp.headers["content-type"] == "model/gltf-binary"
            assert int(bin_resp.headers["x-triangles"]) > 400
            assert bin_resp.content[:4] == b"glTF"
            parsed = trimesh.load(io.BytesIO(bin_resp.content), file_type="glb", force="scene")
            assert len(parsed.geometry) >= 4
