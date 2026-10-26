"""Small helpers for assembling SVG documents by hand.

Generators draw on a fixed 400×400 user-space canvas and the document is
scaled via ``width``/``height`` so a single render is crisp at any export
size.
"""

from __future__ import annotations

from xml.sax.saxutils import escape

CANVAS = 400


def esc(value: object) -> str:
    """Escape text for safe inclusion in SVG markup."""
    return escape(str(value), {'"': "&quot;", "'": "&apos;"})


def num(value: float) -> str:
    """Format a number compactly for use in an SVG attribute."""
    if abs(value - round(value)) < 1e-9:
        return str(round(value))
    return f"{value:.2f}".rstrip("0").rstrip(".")


def document(*, size: int, body: str, defs: str = "", title: str = "Asset") -> str:
    """Wrap generated content in a standalone SVG document."""
    parts = [
        '<svg xmlns="http://www.w3.org/2000/svg"',
        f' width="{size}" height="{size}"',
        f' viewBox="0 0 {CANVAS} {CANVAS}"',
        ' preserveAspectRatio="xMidYMid meet"',
        f' role="img" aria-label="{esc(title)}">',
        f"<title>{esc(title)}</title>",
    ]
    if defs:
        parts.append(f"<defs>{defs}</defs>")
    parts.append(body)
    parts.append("</svg>")
    return "".join(parts)


def sparkle(
    cx: float,
    cy: float,
    radius: float,
    *,
    fill: str,
    opacity: float = 1.0,
    inner: float = 0.34,
) -> str:
    """Return a four-point sparkle element centred on ``(cx, cy)``."""
    r_in = radius * inner
    points = [
        (cx, cy - radius),
        (cx + r_in, cy - r_in),
        (cx + radius, cy),
        (cx + r_in, cy + r_in),
        (cx, cy + radius),
        (cx - r_in, cy + r_in),
        (cx - radius, cy),
        (cx - r_in, cy - r_in),
    ]
    d = "M " + " L ".join(f"{num(x)} {num(y)}" for x, y in points) + " Z"
    return f'<path d="{d}" fill="{fill}" opacity="{num(opacity)}"/>'
