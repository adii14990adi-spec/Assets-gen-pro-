"""Gradient shield badges with initials."""

from __future__ import annotations

from ..params import as_bool, as_text
from ..svg import CANVAS, esc, sparkle
from .base import Context, ParamSpec

SHIELD = "M200 34 L354 88 V206 C354 292 288 344 200 374 C112 344 46 292 46 206 V88 Z"
INNER = "M200 62 L330 108 V206 C330 276 276 320 200 346 C124 320 70 276 70 206 V108 Z"
LETTERS = "ABCDEFGHJKLMNPQRSTUVWXYZ"

PARAMS: tuple[ParamSpec, ...] = (
    ParamSpec("text", "Initials", "text", "", max_length=4),
    ParamSpec("sparkles", "Sparkles", "bool", True),
)


def _initials(ctx: Context) -> str:
    explicit = as_text(ctx.params, "text", "", max_length=4)
    if explicit:
        return explicit.upper()
    count = ctx.rng.choice((2, 2, 3))
    return "".join(ctx.rng.choice(LETTERS) for _ in range(count))


def render(ctx: Context) -> tuple[str, str]:
    show_sparkles = as_bool(ctx.params, "sparkles", True)
    palette = ctx.palette
    rng = ctx.rng
    initials = _initials(ctx)

    top = palette.shade(0)
    bottom = palette.shade(rng.choice((1, 2, 3)))

    defs: list[str] = [
        (
            '<linearGradient id="shield" x1="0" y1="0" x2="1" y2="1">'
            f'<stop offset="0" stop-color="{top}"/>'
            f'<stop offset="100%" stop-color="{bottom}"/></linearGradient>'
        ),
        (
            '<linearGradient id="sheen" x1="0" y1="0" x2="0" y2="1">'
            '<stop offset="0" stop-color="#ffffff" stop-opacity="0.28"/>'
            '<stop offset="55%" stop-color="#ffffff" stop-opacity="0"/>'
            "</linearGradient>"
        ),
        (
            '<filter id="lift" x="-30%" y="-30%" width="160%" height="160%">'
            '<feDropShadow dx="0" dy="10" stdDeviation="12" '
            'flood-color="#000000" flood-opacity="0.38"/></filter>'
        ),
    ]

    body: list[str] = [
        f'<rect width="{CANVAS}" height="{CANVAS}" fill="{palette.bg}"/>'
    ]

    if show_sparkles:
        for _ in range(rng.randint(4, 7)):
            cx = rng.uniform(40, 360)
            cy = rng.uniform(40, 360)
            if 70 < cx < 330 and 60 < cy < 350:
                continue
            body.append(
                sparkle(
                    cx,
                    cy,
                    rng.uniform(5, 13),
                    fill=palette.fg,
                    opacity=rng.uniform(0.20, 0.55),
                )
            )

    body.append(f'<g filter="url(#lift)"><path d="{SHIELD}" fill="url(#shield)"/></g>')
    body.append(f'<path d="{SHIELD}" fill="url(#sheen)"/>')
    body.append(
        f'<path d="{INNER}" fill="none" stroke="{palette.fg}" '
        f'stroke-opacity="0.45" stroke-width="4" stroke-linejoin="round"/>'
    )

    font_size = 132 if len(initials) <= 2 else 104
    body.append(
        f'<text x="200" y="222" text-anchor="middle" '
        "font-family=\"Inter, 'Helvetica Neue', Arial, sans-serif\" "
        f'font-size="{font_size}" font-weight="700" letter-spacing="2" '
        f'fill="{palette.bg}" opacity="0.45" transform="translate(0 5)">'
        f"{esc(initials)}</text>"
    )
    body.append(
        f'<text x="200" y="222" text-anchor="middle" '
        "font-family=\"Inter, 'Helvetica Neue', Arial, sans-serif\" "
        f'font-size="{font_size}" font-weight="700" letter-spacing="2" '
        f'fill="{palette.fg}">{esc(initials)}</text>'
    )

    return "".join(defs), "".join(body)
