"""ASGI entrypoint forwarding to `backend.main:app`."""

from backend.main import app

__all__ = ["app"]
