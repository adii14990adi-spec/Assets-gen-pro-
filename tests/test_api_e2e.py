"""Full API + Background Job Worker + Download + Security E2E Tests."""

from __future__ import annotations

import asyncio
import struct

import httpx
import pytest
import trimesh

from backend.config import REPO_ROOT, Settings
from backend.main import create_app


@pytest.mark.asyncio
async def test_full_web_to_blender_pipeline_and_downloads(isolated_settings: Settings) -> None:
    app = create_app(isolated_settings)
    transport = httpx.ASGITransport(app=app)

    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            # 1. Health & Catalog endpoints
            health = (await client.get("/api/health")).json()
            assert health["status"] == "ok"
            assert health["blender_available"] is True

            types_res = await client.get("/api/assets/types")
            assert types_res.status_code == 200
            assert len(types_res.json()["types"]) == 4

            presets_res = await client.get("/api/presets?category=props")
            assert presets_res.status_code == 200
            assert any(p["id"] == "explosive_fuel_barrel" for p in presets_res.json())

            # 2. Submit real generation job
            gen_resp = await client.post(
                "/api/generate",
                json={
                    "name": "E2E Fuel Drum",
                    "category": "props",
                    "preset_id": "explosive_fuel_barrel",
                    "quality_profile": "prototype",
                    "seed": 303,
                    "material_preset": "desert_camo",
                    "save_blend": True,
                    "execution_mode": "live",
                    "parameters": {"width": 0.64, "depth": 0.64, "height": 0.94},
                },
            )
            assert gen_resp.status_code == 202
            job = gen_resp.json()
            job_id = job["id"]

            # 3. Poll job status until completed
            final_job = None
            for _ in range(80):
                poll = await client.get(f"/api/jobs/{job_id}")
                assert poll.status_code == 200
                cur = poll.json()
                if cur["status"] in ("completed", "failed", "cancelled"):
                    final_job = cur
                    break
                await asyncio.sleep(0.15)

            assert final_job is not None, "Job did not finish within timeout"
            assert final_job["status"] == "completed", f"Job failed: {final_job.get('error')}"
            assert final_job["progress_pct"] == 100
            asset_id = final_job["asset_id"]
            assert asset_id

            # 4. Inspect job result & persistent asset library
            res_endpoint = (await client.get(f"/api/jobs/{job_id}/result")).json()
            assert res_endpoint["asset"]["id"] == asset_id
            assert res_endpoint["asset"]["stats"]["actual_triangles"] > 200

            lib = (await client.get("/api/assets")).json()
            assert any(a["id"] == asset_id for a in lib)

            # 5. Download real GLB, BLEND, and Metadata and verify bytes!
            dl_glb = await client.get(f"/api/assets/{asset_id}/download?format=glb")
            assert dl_glb.status_code == 200
            assert dl_glb.headers["content-type"] == "model/gltf-binary"
            glb_bytes = dl_glb.content
            assert len(glb_bytes) == res_endpoint["asset"]["glb_size_bytes"]
            magic, version, total_len = struct.unpack("<III", glb_bytes[:12])
            assert magic == 0x46546C67
            assert version == 2
            assert total_len == len(glb_bytes)

            # Load downloaded GLB directly into Trimesh from memory to prove real 3D geometry
            scene = trimesh.load(trimesh.util.wrap_as_stream(glb_bytes), file_type="glb", force="scene")
            assert len(scene.geometry) >= 1
            assert sum(len(g.faces) for g in scene.geometry.values()) == res_endpoint["asset"]["stats"]["actual_triangles"]

            dl_blend = await client.get(f"/api/assets/{asset_id}/download?format=blend")
            assert dl_blend.status_code == 200
            assert len(dl_blend.content) > 50_000

            dl_meta = await client.get(f"/api/assets/{asset_id}/download?format=metadata")
            assert dl_meta.status_code == 200
            assert dl_meta.json()["id"] == asset_id

            # 6. Upload GLB to POST /api/validate endpoint
            val_upload = await client.post(
                "/api/validate?polygon_budget=3000",
                files={"file": ("drum.glb", glb_bytes, "model/gltf-binary")},
            )
            assert val_upload.status_code == 200
            val_json = val_upload.json()
            assert val_json["validation"]["valid"] is True
            assert val_json["stats"]["actual_triangles"] == res_endpoint["asset"]["stats"]["actual_triangles"]


@pytest.mark.asyncio
async def test_validation_errors_job_failure_and_security_guards(isolated_settings: Settings) -> None:
    app = create_app(isolated_settings)
    transport = httpx.ASGITransport(app=app)

    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            # 1. Category / preset mismatch -> 422
            bad_preset = await client.post(
                "/api/generate",
                json={
                    "category": "humanoid",
                    "preset_id": "br_supply_crate",
                    "quality_profile": "prototype",
                    "seed": 1,
                },
            )
            assert bad_preset.status_code == 422

            # 2. Out-of-bounds parameter -> 422
            bad_dim = await client.post(
                "/api/generate",
                json={
                    "category": "props",
                    "preset_id": "br_supply_crate",
                    "quality_profile": "prototype",
                    "seed": 1,
                    "parameters": {"width": 999.0},
                },
            )
            assert bad_dim.status_code == 422

            # 3. Path-traversal characters in name -> 422, and in URL -> 400
            bad_name = await client.post(
                "/api/generate",
                json={
                    "name": "../../etc/passwd",
                    "category": "props",
                    "preset_id": "br_supply_crate",
                },
            )
            assert bad_name.status_code == 422

            bad_id = await client.get("/api/assets/bad$id!/download")
            assert bad_id.status_code == 400

            # 4. Job failure reporting when Mode A GitHub Actions lacks token
            gh_job_resp = await client.post(
                "/api/generate",
                json={
                    "category": "props",
                    "preset_id": "br_supply_crate",
                    "quality_profile": "prototype",
                    "seed": 12,
                    "execution_mode": "github_actions",
                },
            )
            assert gh_job_resp.status_code == 202
            gh_job_id = gh_job_resp.json()["id"]

            failed_state = None
            for _ in range(30):
                cur = (await client.get(f"/api/jobs/{gh_job_id}")).json()
                if cur["status"] == "failed":
                    failed_state = cur
                    break
                await asyncio.sleep(0.1)

            assert failed_state is not None
            assert failed_state["status"] == "failed"
            assert "GITHUB_DISPATCH_TOKEN" in (failed_state["error"] or "")
            _ = REPO_ROOT
