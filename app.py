"""ASGI entrypoint for the Procedural 3D Asset Generator Studio.

All supported server commands resolve to the same FastAPI application:

    uvicorn app:app         --host 0.0.0.0 --port $PORT   # Render default
    uvicorn main:app        --host 0.0.0.0 --port $PORT   # via root main.py
    uvicorn backend.main:app --host 0.0.0.0 --port $PORT  # package path
    python app.py                                          # PORT env or 8000
"""

from __future__ import annotations

import os

from backend.main import app

__all__ = ["app"]

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "app:app",
        host="0.0.0.0",
        port=int(os.environ.get("PORT", "8000")),
    )
