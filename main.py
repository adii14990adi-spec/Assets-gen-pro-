"""Root ASGI entrypoint forwarding `app` from `app.py` for Render (`uvicorn main:app`)."""

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
