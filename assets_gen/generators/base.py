"""Shared types for generators (kept separate to avoid import cycles)."""

from __future__ import annotations

import random
from collections.abc import Mapping
from dataclasses import dataclass, field

from ..palettes import Palette


@dataclass
class Context:
    """Everything a generator needs to draw a single asset."""

    kind: str
    seed: str
    size: int
    rng: random.Random
    palette: Palette
    params: Mapping[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class ParamSpec:
    """Describes one tunable parameter so the UI can build its controls."""

    name: str
    label: str
    type: str  # "int" | "choice" | "bool" | "text"
    default: object
    minimum: int | None = None
    maximum: int | None = None
    choices: tuple[str, ...] = ()
    max_length: int | None = None
    help: str = ""

    def to_dict(self) -> dict[str, object]:
        data: dict[str, object] = {
            "name": self.name,
            "label": self.label,
            "type": self.type,
            "default": self.default,
        }
        if self.minimum is not None:
            data["min"] = self.minimum
        if self.maximum is not None:
            data["max"] = self.maximum
        if self.choices:
            data["choices"] = list(self.choices)
        if self.max_length is not None:
            data["max_length"] = self.max_length
        if self.help:
            data["help"] = self.help
        return data
