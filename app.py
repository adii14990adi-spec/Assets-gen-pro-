"""FastAPI application exposing the asset generator.

Run locally with::

    uvicorn app:app --reload --host 0.0.0.0 --port 8000
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from assets_gen import __version__
from assets_gen.generators import KINDS, UnknownKindError, generate
from assets_gen.palettes import STYLES
from assets_gen.params import ParamError
from assets_gen.rng import derive_seed, random_seed

WEB_DIR = Path(__file__).parent / "web"

SIZE_MIN = 16
SIZE_MAX = 2048
BATCH_MAX = 32

RESERVED = {"kind", "seed", "size", "palette", "download"}

app = FastAPI(
    title="Assets Gen Pro",
    version=__version__,
    description="Deterministic procedural SVG asset generation.",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
    expose_headers=["ETag"],
)


def _resolve_size(raw: object) -> int:
    """Parse and range-check the requested export size."""
    if raw is None or raw == "":
        return 400
    try:
        size = int(str(raw))
    except ValueError as exc:
        raise HTTPException(422, "'size' must be an integer") from exc
    if not SIZE_MIN <= size <= SIZE_MAX:
        raise HTTPException(422, f"'size' must be between {SIZE_MIN} and {SIZE_MAX}")
    return size


def _resolve_palette(raw: object) -> str:
    if raw is None or raw == "":
        return "vivid"
    palette = str(raw).strip().lower()
    if palette not in STYLES:
        raise HTTPException(422, f"'palette' must be one of: {', '.join(STYLES)}")
    return palette


def _render(
    *,
    kind: str,
    seed: str,
    size: int,
    palette: str,
    params: Mapping[str, Any],
) -> tuple[str, bytes, str]:
    """Render an asset, returning ``(svg text, utf-8 bytes, etag)``."""
    try:
        svg = generate(kind, seed=seed, size=size, palette=palette, params=params)
    except UnknownKindError as exc:
        raise HTTPException(404, f"unknown asset kind: {exc.args[0]}") from exc
    except ParamError as exc:
        raise HTTPException(422, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc

    payload = svg.encode("utf-8")
    etag = '"' + hashlib.sha256(payload).hexdigest()[:32] + '"'
    return svg, payload, etag


def _svg_response(
    request: Request,
    svg: str,
    payload: bytes,
    etag: str,
    *,
    seed: str,
    kind: str,
    head_only: bool = False,
) -> Response:
    headers = {
        "Cache-Control": "public, max-age=31536000, immutable",
        "Content-Disposition": (
            f'inline; filename="{kind}-{seed[:24].replace("/", "-")}.svg"'
        ),
        "X-Asset-Seed": seed,
    }
    if request.headers.get("if-none-match") in {etag, f"W/{etag}"}:
        return Response(status_code=304, headers={**headers, "ETag": etag})
    response = Response(
        content=b"" if head_only else payload,
        media_type="image/svg+xml; charset=utf-8",
        headers={**headers, "ETag": etag},
    )
    if head_only:
        # HEAD must advertise the size of the body a GET would return.
        response.headers["content-length"] = str(len(payload))
    return response


def _query_params(request: Request) -> dict[str, str]:
    return {
        key: value for key, value in request.query_params.items() if key not in RESERVED
    }


@app.get("/api/health")
def health() -> dict[str, object]:
    """Liveness probe plus a little metadata."""
    return {
        "status": "ok",
        "version": __version__,
        "kinds": len(KINDS),
        "palettes": list(STYLES),
    }


@app.get("/api/kinds")
def list_kinds() -> dict[str, object]:
    """Describe every registered kind and its parameters."""
    return {"kinds": [kind.to_dict() for kind in KINDS.values()]}


@app.get("/api/seed")
def new_seed(length: int = 12) -> dict[str, str]:
    """Return a fresh random seed for the UI's dice button."""
    length = max(4, min(length, 40))
    return {"seed": random_seed(length)}


@app.get("/api/asset.svg")
def asset_svg(request: Request, kind: str, seed: str = "demo") -> Response:
    """Render one asset as an SVG document."""
    size = _resolve_size(request.query_params.get("size"))
    palette = _resolve_palette(request.query_params.get("palette"))
    svg, payload, etag = _render(
        kind=kind,
        seed=seed,
        size=size,
        palette=palette,
        params=_query_params(request),
    )
    return _svg_response(request, svg, payload, etag, seed=seed, kind=kind)


@app.head("/api/asset.svg")
def asset_svg_head(request: Request, kind: str, seed: str = "demo") -> Response:
    """Metadata-only variant of :func:`asset_svg` for caches and probes."""
    size = _resolve_size(request.query_params.get("size"))
    palette = _resolve_palette(request.query_params.get("palette"))
    svg, payload, etag = _render(
        kind=kind,
        seed=seed,
        size=size,
        palette=palette,
        params=_query_params(request),
    )
    return _svg_response(
        request, svg, payload, etag, seed=seed, kind=kind, head_only=True
    )


@app.post("/api/asset.svg")
async def asset_svg_post(request: Request) -> Response:
    """Render one asset from a JSON body (handy for long parameter sets)."""
    try:
        body = await request.json()
    except ValueError as exc:
        raise HTTPException(400, "request body must be valid JSON") from exc
    if not isinstance(body, dict):
        raise HTTPException(400, "request body must be a JSON object")

    kind = body.get("kind")
    if not isinstance(kind, str) or not kind:
        raise HTTPException(422, "'kind' is required")

    seed = str(body.get("seed") or "demo")
    size = _resolve_size(body.get("size"))
    palette = _resolve_palette(body.get("palette"))
    params = body.get("params", {})
    if params is None:
        params = {}
    if not isinstance(params, dict):
        raise HTTPException(422, "'params' must be a JSON object")

    svg, payload, etag = _render(
        kind=kind, seed=seed, size=size, palette=palette, params=params
    )
    return _svg_response(request, svg, payload, etag, seed=seed, kind=kind)


@app.get("/api/batch.json")
def batch(
    kind: str,
    seed: str = "demo",
    count: int = 8,
    size: int = 400,
    palette: str = "vivid",
) -> dict[str, object]:
    """Return metadata for ``count`` assets derived from one seed."""
    if kind not in KINDS:
        raise HTTPException(404, f"unknown asset kind: {kind}")
    count = max(1, min(count, BATCH_MAX))
    size = _resolve_size(size)
    palette = _resolve_palette(palette)

    items = []
    for index in range(count):
        child = derive_seed(seed, index)
        items.append(
            {
                "seed": child,
                "url": (
                    f"/api/asset.svg?kind={kind}&seed={child}"
                    f"&size={size}&palette={palette}"
                ),
            }
        )
    return {"kind": kind, "palette": palette, "size": size, "items": items}


@app.exception_handler(UnknownKindError)
def _unknown_kind(_: Request, exc: UnknownKindError) -> JSONResponse:
    return JSONResponse({"detail": f"unknown asset kind: {exc.args[0]}"}, 404)


if WEB_DIR.is_dir():
    app.mount("/", StaticFiles(directory=WEB_DIR, html=True), name="web")
