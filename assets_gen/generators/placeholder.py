"""Framed empty-state image placeholders."""

from __future__ import annotations

from ..params import as_bool, as_choice, as_text
from ..svg import CANVAS, esc, num
from .base import Context, ParamSpec

PARAMS: tuple[ParamSpec, ...] = (
    ParamSpec("caption", "Caption", "text", "", max_length=16),
    ParamSpec("dots", "Dot grid", "bool", True),
    ParamSpec("corners", "Corner marks", "bool", True),
    ParamSpec(
        "icon", "Icon", "choice", "mountain", choices=("mountain", "camera", "layers")
    ),
)


def _icon(ctx: Context, icon: str, colour: str) -> str:
    if icon == "camera":
        return (
            f'<g fill="none" stroke="{colour}" stroke-width="7" '
            'stroke-linejoin="round" stroke-linecap="round">'
            '<rect x="128" y="146" width="144" height="104" rx="18"/>'
            '<path d="M168 146 L182 124 H218 L232 146"/>'
            '<circle cx="200" cy="196" r="27"/></g>'
        )
    if icon == "layers":
        return (
            f'<g fill="none" stroke="{colour}" stroke-width="7" '
            'stroke-linejoin="round" stroke-linecap="round">'
            '<path d="M200 128 L272 164 L200 200 L128 164 Z"/>'
            '<path d="M128 196 L200 232 L272 196"/>'
            '<path d="M128 228 L200 264 L272 228"/></g>'
        )
    return (
        f'<g fill="none" stroke="{colour}" stroke-width="7" '
        'stroke-linejoin="round" stroke-linecap="round">'
        '<path d="M126 260 L176 186 L212 234 L238 204 L274 260 Z"/>'
        '<circle cx="246" cy="152" r="13"/></g>'
    )


def render(ctx: Context) -> tuple[str, str]:
    caption = as_text(ctx.params, "caption", "", max_length=16)
    dots = as_bool(ctx.params, "dots", True)
    corners = as_bool(ctx.params, "corners", True)
    icon = as_choice(ctx.params, "icon", "mountain", ("mountain", "camera", "layers"))
    palette = ctx.palette
    rng = ctx.rng

    defs = [
        (
            '<pattern id="dotgrid" width="26" height="26" '
            'patternUnits="userSpaceOnUse">'
            f'<circle cx="2" cy="2" r="1.8" fill="{palette.fg}" '
            'opacity="0.22"/></pattern>'
        ),
        (
            '<linearGradient id="wash" x1="0" y1="0" x2="1" y2="1">'
            f'<stop offset="0" stop-color="{palette.bg}"/>'
            f'<stop offset="100%" stop-color="{palette.shade(0)}" '
            'stop-opacity="0.30"/></linearGradient>'
        ),
    ]
    body: list[str] = [f'<rect width="{CANVAS}" height="{CANVAS}" fill="url(#wash)"/>']

    if dots:
        body.append(f'<rect width="{CANVAS}" height="{CANVAS}" fill="url(#dotgrid)"/>')

    inset = 36
    body.append(
        f'<rect x="{inset}" y="{inset}" width="{CANVAS - 2 * inset}" '
        f'height="{CANVAS - 2 * inset}" rx="26" fill="none" '
        f'stroke="{palette.fg}" stroke-opacity="0.42" stroke-width="3" '
        'stroke-dasharray="14 12"/>'
    )

    if corners:
        arm = 34
        for cx, cy, sx, sy in (
            (inset, inset, 1, 1),
            (CANVAS - inset, inset, -1, 1),
            (inset, CANVAS - inset, 1, -1),
            (CANVAS - inset, CANVAS - inset, -1, -1),
        ):
            body.append(
                f'<path d="M {num(cx + sx * arm)} {num(cy)} '
                f'L {num(cx)} {num(cy)} L {num(cx)} {num(cy + sy * arm)}" '
                f'fill="none" stroke="{palette.shade(0)}" stroke-width="5" '
                'stroke-linecap="round"/>'
            )

    body.append(_icon(ctx, icon, palette.shade(rng.choice((0, 1)))))

    label = caption or f"{CANVAS} × {CANVAS}"
    body.append(
        f'<text x="200" y="312" text-anchor="middle" '
        "font-family=\"Inter, 'Helvetica Neue', Arial, sans-serif\" "
        f'font-size="26" font-weight="600" letter-spacing="1.5" '
        f'fill="{palette.fg}" fill-opacity="0.82">{esc(label)}</text>'
    )

    return "".join(defs), "".join(body)
