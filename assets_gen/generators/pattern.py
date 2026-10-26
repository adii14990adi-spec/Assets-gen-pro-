"""Tiled geometric patterns."""

from __future__ import annotations

import math

from ..params import as_choice, as_int
from ..svg import CANVAS, num
from .base import Context, ParamSpec

MOTIFS: tuple[str, ...] = (
    "auto",
    "dots",
    "triangles",
    "hexagons",
    "waves",
    "stripes",
)

PARAMS: tuple[ParamSpec, ...] = (
    ParamSpec("motif", "Motif", "choice", "auto", choices=MOTIFS),
    ParamSpec("density", "Density", "int", 6, minimum=3, maximum=10),
)


def render(ctx: Context) -> tuple[str, str]:
    motif = as_choice(ctx.params, "motif", "auto", MOTIFS)
    if motif == "auto":
        motif = ctx.rng.choice(MOTIFS[1:])
    density = as_int(ctx.params, "density", 6, 3, 10)

    defs: list[str] = []
    body: list[str] = [
        f'<rect width="{CANVAS}" height="{CANVAS}" fill="{ctx.palette.bg}"/>'
    ]
    painter = {
        "dots": _dots,
        "triangles": _triangles,
        "hexagons": _hexagons,
        "waves": _waves,
        "stripes": _stripes,
    }[motif]
    defs_out, body_out = painter(ctx, density)
    defs.extend(defs_out)
    body.append(body_out)
    return "".join(defs), "".join(body)


def _dots(ctx: Context, density: int) -> tuple[list[str], str]:
    step = CANVAS / density
    parts: list[str] = []
    for row in range(density):
        for col in range(density):
            if ctx.rng.random() < 0.10:
                continue
            radius = step * ctx.rng.uniform(0.16, 0.34)
            cx = (col + 0.5) * step
            cy = (row + 0.5) * step
            colour = ctx.palette.shade(row + col)
            parts.append(
                f'<circle cx="{num(cx)}" cy="{num(cy)}" r="{num(radius)}" '
                f'fill="{colour}" opacity="{num(ctx.rng.uniform(0.72, 1.0))}"/>'
            )
    return [], "".join(parts)


def _triangles(ctx: Context, density: int) -> tuple[list[str], str]:
    step = CANVAS / density
    parts: list[str] = []
    for row in range(density):
        for col in range(density):
            x = col * step
            y = row * step
            inset = step * 0.06
            flip = (row + col) % 2 == 0
            if flip:
                points = (
                    (x + inset, y + step - inset),
                    (x + step - inset, y + step - inset),
                    (x + step / 2, y + inset),
                )
            else:
                points = (
                    (x + inset, y + inset),
                    (x + step - inset, y + inset),
                    (x + step / 2, y + step - inset),
                )
            path = " ".join(f"{num(px)},{num(py)}" for px, py in points)
            parts.append(
                f'<polygon points="{path}" fill="{ctx.palette.shade(row * 2 + col)}" '
                f'opacity="{num(ctx.rng.uniform(0.75, 0.95))}"/>'
            )
    return [], "".join(parts)


def _hexagons(ctx: Context, density: int) -> tuple[list[str], str]:
    radius = CANVAS / density * 0.52
    dx = radius * math.sqrt(3)
    dy = radius * 1.5
    parts: list[str] = []
    rows = int(CANVAS / dy) + 2
    cols = int(CANVAS / dx) + 2
    for row in range(rows):
        for col in range(cols):
            cx = col * dx + (dx / 2 if row % 2 else 0)
            cy = row * dy
            points = []
            for corner in range(6):
                angle = math.radians(60 * corner)
                points.append(
                    f"{num(cx + radius * math.cos(angle))},"
                    f"{num(cy + radius * math.sin(angle))}"
                )
            parts.append(
                f'<polygon points="{" ".join(points)}" '
                f'fill="{ctx.palette.shade(row + col * 2)}" '
                f'stroke="{ctx.palette.bg}" stroke-width="2" '
                f'opacity="{num(ctx.rng.uniform(0.78, 0.96))}"/>'
            )
    return [], "".join(parts)


def _waves(ctx: Context, density: int) -> tuple[list[str], str]:
    bands = max(4, density + 2)
    parts: list[str] = []
    for band in range(bands):
        base_y = CANVAS * (band + 0.5) / bands
        amplitude = CANVAS / bands * ctx.rng.uniform(0.32, 0.55)
        wavelength = CANVAS / ctx.rng.uniform(1.1, 2.4)
        phase = ctx.rng.uniform(0, 2 * math.pi)
        width = ctx.rng.uniform(2.5, 7.0)
        steps = 48
        points = []
        for step in range(steps + 1):
            x = CANVAS * step / steps
            y = base_y + amplitude * math.sin(2 * math.pi * x / wavelength + phase)
            points.append(f"{num(x)} {num(y)}")
        parts.append(
            f'<path d="M {" L ".join(points)}" fill="none" '
            f'stroke="{ctx.palette.shade(band)}" stroke-width="{num(width)}" '
            f'stroke-linecap="round" opacity="{num(ctx.rng.uniform(0.70, 0.95))}"/>'
        )
    return [], "".join(parts)


def _stripes(ctx: Context, density: int) -> tuple[list[str], str]:
    bands = density * 2
    width = CANVAS * 1.5 / bands
    parts: list[str] = []
    for index in range(bands):
        parts.append(
            f'<rect x="{num(-CANVAS * 0.4 + index * width)}" y="-200" '
            f'width="{num(width)}" height="800" '
            f'fill="{ctx.palette.shade(index)}" '
            f'opacity="{num(ctx.rng.uniform(0.65, 0.92))}"/>'
        )
    defs = [
        (
            f'<clipPath id="frame"><rect width="{CANVAS}" height="{CANVAS}" '
            'rx="0"/></clipPath>'
        )
    ]
    inner = (
        f'<g clip-path="url(#frame)" transform="rotate({num(ctx.rng.uniform(20, 70))} '
        f'200 200)">{"".join(parts)}</g>'
    )
    return defs, inner
