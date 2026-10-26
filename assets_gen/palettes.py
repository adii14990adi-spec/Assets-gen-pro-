"""Palette construction.

A palette is derived from the same seeded PRNG as the artwork, which keeps
generated assets consistent with their declared seed.  Each style returns a
background colour, a foreground/ink colour and four harmonised accents.
"""

from __future__ import annotations

import colorsys
import random
from dataclasses import dataclass

STYLES: tuple[str, ...] = ("vivid", "pastel", "neon", "mono", "earth")


def hsl(hue: float, saturation: float, lightness: float) -> str:
    """Convert HSL (hue in degrees, s/l in 0..1) to a ``#rrggbb`` string."""
    r, g, b = colorsys.hls_to_rgb(
        (hue % 360) / 360,
        min(max(lightness, 0.0), 1.0),
        min(max(saturation, 0.0), 1.0),
    )
    return "#{:02x}{:02x}{:02x}".format(
        *(round(channel * 255) for channel in (r, g, b))
    )


@dataclass(frozen=True)
class Palette:
    """A small, harmonised colour set."""

    style: str
    bg: str
    fg: str
    accents: tuple[str, ...]

    def shade(self, index: int) -> str:
        """Return an accent by index, cycling when out of range."""
        return self.accents[index % len(self.accents)]

    def pick(self, rng: random.Random) -> str:
        """Return a random accent."""
        return rng.choice(self.accents)

    def to_dict(self) -> dict[str, object]:
        return {
            "style": self.style,
            "bg": self.bg,
            "fg": self.fg,
            "accents": list(self.accents),
        }


def _jitter(rng: random.Random, value: float, spread: float) -> float:
    return value + rng.uniform(-spread, spread)


def build_palette(rng: random.Random, style: str = "vivid") -> Palette:
    """Build a palette for ``style`` using values drawn from ``rng``."""
    if style not in STYLES:
        raise ValueError(f"unknown palette style: {style!r}")

    base = rng.uniform(0, 360)

    if style == "vivid":
        bg = hsl(_jitter(rng, base + 215, 20), 0.42, 0.08)
        fg = hsl(base, 0.24, 0.97)
        accents = tuple(
            hsl(
                _jitter(rng, base + offset, 12),
                rng.uniform(0.74, 0.92),
                rng.uniform(0.52, 0.66),
            )
            for offset in (0, 36, 74, 168)
        )
    elif style == "pastel":
        bg = hsl(_jitter(rng, base + 8, 14), 0.32, 0.965)
        fg = hsl(base, 0.36, 0.28)
        accents = tuple(
            hsl(
                _jitter(rng, base + offset, 14),
                rng.uniform(0.40, 0.56),
                rng.uniform(0.70, 0.82),
            )
            for offset in (0, 44, 92, 178)
        )
    elif style == "neon":
        bg = hsl(_jitter(rng, base + 200, 18), 0.48, 0.05)
        fg = hsl(base, 0.90, 0.96)
        accents = tuple(
            hsl(_jitter(rng, base + offset, 10), 0.96, rng.uniform(0.55, 0.66))
            for offset in (0, 62, 124, 186)
        )
    elif style == "mono":
        bg = hsl(_jitter(rng, base, 10), 0.20, 0.10)
        fg = hsl(base, 0.14, 0.96)
        accents = tuple(
            hsl(_jitter(rng, base, 6), rng.uniform(0.16, 0.34), level)
            for level in (0.38, 0.52, 0.68, 0.84)
        )
    else:  # earth
        bg = hsl(_jitter(rng, 38, 8), 0.30, 0.94)
        fg = hsl(28, 0.38, 0.18)
        accents = tuple(
            hsl(_jitter(rng, hue, 8), rng.uniform(0.32, 0.50), rng.uniform(0.34, 0.56))
            for hue in (22, 40, 58, 96)
        )

    return Palette(style=style, bg=bg, fg=fg, accents=accents)
