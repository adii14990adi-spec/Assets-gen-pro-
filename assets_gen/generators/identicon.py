"""Symmetrical block identicons."""

from __future__ import annotations

from ..params import as_choice
from ..svg import CANVAS, num
from .base import Context, ParamSpec

GRIDS: tuple[str, ...] = ("5", "7")
MASKS: tuple[str, ...] = ("circle", "squircle")

PARAMS: tuple[ParamSpec, ...] = (
    ParamSpec("grid", "Grid", "choice", "5", choices=GRIDS),
    ParamSpec("mask", "Frame", "choice", "circle", choices=MASKS),
)


def render(ctx: Context) -> tuple[str, str]:
    grid = int(as_choice(ctx.params, "grid", "5", GRIDS))
    mask = as_choice(ctx.params, "mask", "circle", MASKS)
    palette = ctx.palette
    rng = ctx.rng

    half = (grid + 1) // 2
    pattern = [[rng.random() < 0.48 for _ in range(half)] for _ in range(grid)]
    if not any(any(row) for row in pattern):
        pattern[grid // 2][0] = True

    ink = palette.pick(rng)
    highlight = palette.pick(rng)
    margin = CANVAS * 0.10
    inner = CANVAS - 2 * margin
    cell = inner / grid
    gap = cell * 0.10
    origin = margin

    defs = [
        '<clipPath id="frame">'
        + (
            f'<circle cx="{CANVAS / 2}" cy="{CANVAS / 2}" r="{CANVAS / 2}"/>'
            if mask == "circle"
            else f'<rect width="{CANVAS}" height="{CANVAS}" rx="86"/>'
        )
        + "</clipPath>"
    ]
    body: list[str] = [
        '<g clip-path="url(#frame)">',
        f'<rect width="{CANVAS}" height="{CANVAS}" fill="{palette.bg}"/>',
    ]

    # Faint inner glow so the avatar does not look flat.
    defs.append(
        '<radialGradient id="glow" cx="50%" cy="38%" r="62%">'
        f'<stop offset="0" stop-color="{highlight}" stop-opacity="0.30"/>'
        f'<stop offset="100%" stop-color="{highlight}" stop-opacity="0"/></radialGradient>'
    )
    body.append(f'<rect width="{CANVAS}" height="{CANVAS}" fill="url(#glow)"/>')

    for row in range(grid):
        for col in range(grid):
            source = col if col < half else grid - 1 - col
            if not pattern[row][source]:
                continue
            x = origin + col * cell + gap / 2
            y = origin + row * cell + gap / 2
            size = cell - gap
            fill = ink if rng.random() > 0.22 else highlight
            body.append(
                f'<rect x="{num(x)}" y="{num(y)}" width="{num(size)}" '
                f'height="{num(size)}" rx="{num(cell * 0.22)}" fill="{fill}"/>'
            )

    body.append("</g>")
    body.append(
        '<rect x="1.5" y="1.5" width="397" height="397" fill="none" '
        f'stroke="{palette.fg}" stroke-opacity="0.14" stroke-width="3" '
        f'rx="{"198" if mask == "circle" else "85"}"/>'
    )
    return "".join(defs), "".join(body)
