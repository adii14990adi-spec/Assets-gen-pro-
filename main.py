"""Alternate ASGI entrypoint — re-exports the app from root `app.py`.

Exists so hosts/tooling that default to ``uvicorn main:app`` work out of
the box alongside ``uvicorn app:app`` (Render start command) and
``uvicorn backend.main:app``:

    uvicorn main:app --host 0.0.0.0 --port $PORT
"""

from __future__ import annotations

import os

from app import app

__all__ = ["app"]

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=int(os.environ.get("PORT", "8000")),
    )
