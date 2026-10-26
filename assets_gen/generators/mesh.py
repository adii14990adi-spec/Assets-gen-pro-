"""Soft mesh-gradient backgrounds."""

from __future__ import annotations

from ..params import as_bool, as_int
from ..svg import CANVAS, num
from .base import Context, ParamSpec

PARAMS: tuple[ParamSpec, ...] = (
    ParamSpec("blobs", "Blobs", "int", 6, minimum=3, maximum=10),
    ParamSpec("grain", "Film grain", "bool", True),
)


def render(ctx: Context) -> tuple[str, str]:
    blobs = as_int(ctx.params, "blobs", 6, 3, 10)
    grain = as_bool(ctx.params, "grain", True)
    palette = ctx.palette
    rng = ctx.rng

    defs: list[str] = [
        (
            '<filter id="soften" x="-35%" y="-35%" width="170%" height="170%">'
            '<feGaussianBlur stdDeviation="22"/></filter>'
        )
    ]
    body: list[str] = [
        f'<rect width="{CANVAS}" height="{CANVAS}" fill="{palette.bg}"/>'
    ]

    layers: list[str] = []
    for index in range(blobs):
        colour = palette.pick(rng)
        opacity = rng.uniform(0.45, 0.88)
        defs.append(
            f'<radialGradient id="blob{index}" cx="50%" cy="50%" r="50%">'
            f'<stop offset="0" stop-color="{colour}" stop-opacity="{num(opacity)}"/>'
            f'<stop offset="62%" stop-color="{colour}" '
            f'stop-opacity="{num(opacity * 0.42)}"/>'
            f'<stop offset="100%" stop-color="{colour}" stop-opacity="0"/></radialGradient>'
        )
        cx = rng.uniform(-70, CANVAS + 70)
        cy = rng.uniform(-70, CANVAS + 70)
        radius = rng.uniform(120, 250)
        layers.append(
            f'<circle cx="{num(cx)}" cy="{num(cy)}" r="{num(radius)}" '
            f'fill="url(#blob{index})"/>'
        )

    body.append(f'<g filter="url(#soften)">{"".join(layers)}</g>')

    defs.append(
        '<radialGradient id="vignette" cx="50%" cy="50%" r="72%">'
        '<stop offset="52%" stop-color="#000000" stop-opacity="0"/>'
        '<stop offset="100%" stop-color="#000000" stop-opacity="0.42"/></radialGradient>'
    )
    body.append(f'<rect width="{CANVAS}" height="{CANVAS}" fill="url(#vignette)"/>')

    if grain:
        defs.append(
            '<filter id="grain" x="0" y="0" width="100%" height="100%">'
            '<feTurbulence type="fractalNoise" baseFrequency="0.9" '
            'numOctaves="3" stitchTiles="stitch"/>'
            '<feColorMatrix type="saturate" values="0"/></filter>'
        )
        body.append(
            f'<rect width="{CANVAS}" height="{CANVAS}" filter="url(#grain)" '
            'opacity="0.07" style="mix-blend-mode:overlay"/>'
        )

    return "".join(defs), "".join(body)
