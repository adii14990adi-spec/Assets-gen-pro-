"""Deterministic pseudo-random number generation.

Every asset is a pure function of its inputs, so the same ``(kind, seed,
palette)`` triple must always yield the same SVG.  We therefore never touch
the global :mod:`random` state: each render gets its own generator seeded from
a SHA-256 digest of the human-readable inputs.
"""

from __future__ import annotations

import hashlib
import os
import random

_SEED_ALPHABET = "abcdefghijkmnpqrstuvwxyz23456789"


def make_rng(*parts: object) -> random.Random:
    """Return a generator seeded deterministically from ``parts``."""
    payload = "|".join(str(part) for part in parts)
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()
    return random.Random(int(digest[:16], 16))


def random_seed(length: int = 12) -> str:
    """Return a fresh, URL-safe seed string."""
    raw = os.urandom(length * 2)
    return "".join(_SEED_ALPHABET[b % len(_SEED_ALPHABET)] for b in raw)[:length]


def derive_seed(base: str, index: int) -> str:
    """Derive a stable child seed for batch generation."""
    return f"{base}-{index:02d}"
