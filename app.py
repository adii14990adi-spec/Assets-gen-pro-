"""Unified FastAPI ASGI entrypoint for Procedural 3D Asset Generator Studio.

Supports both Render and local start commands seamlessly:

    uvicorn app:app --host 0.0.0.0 --port $PORT
    uvicorn main:app --host 0.0.0.0 --port $PORT
    python app.py
"""

from __future__ import annotations

import os

from fastapi import FastAPI

from backend.main import app as _studio_app
from backend.main import create_app

app: FastAPI = _studio_app

__all__ = ["app", "create_app"]

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "app:app",
        host="0.0.0.0",
        port=int(os.environ.get("PORT", "8000")),
    )
