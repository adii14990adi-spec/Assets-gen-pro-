"""Entrypoint & frontend-serving tests: app.py, main.py, GET / behavior."""

from __future__ import annotations

import httpx
import pytest

from backend.config import Settings
from backend.main import create_app


def test_root_entrypoints_expose_the_same_app() -> None:
    import app as root_app_module
    import main as root_main_module
    from backend.main import app as backend_app

    assert root_app_module.app is backend_app
    assert root_main_module.app is backend_app


@pytest.mark.asyncio
async def test_root_serves_studio_and_health_reports_engine(
    isolated_settings: Settings,
) -> None:
    app = create_app(isolated_settings)
    transport = httpx.ASGITransport(app=app)
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            root = await client.get("/")
            assert root.status_code == 200
            assert "text/html" in root.headers["content-type"]
            # Either the React build or the fallback Three.js studio.
            assert "Procedural 3D" in root.text

            health = (await client.get("/api/health")).json()
            assert health["status"] == "ok"
            assert health["generation_engine"] in ("blender", "python_fallback")
            assert health["python_fallback_available"] is True
            assert health["configured_engine"] in ("auto", "blender", "python")
