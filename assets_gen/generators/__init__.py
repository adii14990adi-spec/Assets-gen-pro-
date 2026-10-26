"""Generator registry and the render context passed to each generator."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass

from ..palettes import STYLES, build_palette
from ..rng import make_rng
from ..svg import CANVAS, document
from . import badge, identicon, mesh, pattern, placeholder
from .base import Context, ParamSpec


class UnknownKindError(KeyError):
    """Raised when an unknown asset kind is requested."""


Renderer = Callable[[Context], "tuple[str, str]"]


@dataclass(frozen=True)
class Kind:
    """A registered asset kind."""

    id: str
    label: str
    description: str
    params: tuple[ParamSpec, ...]
    render: Renderer

    def to_dict(self) -> dict[str, object]:
        return {
            "id": self.id,
            "label": self.label,
            "description": self.description,
            "params": [param.to_dict() for param in self.params],
        }


_KINDS: tuple[Kind, ...] = (
    Kind(
        id="mesh",
        label="Mesh gradient",
        description="Soft aurora blobs blended over a deep background.",
        params=mesh.PARAMS,
        render=mesh.render,
    ),
    Kind(
        id="pattern",
        label="Geometric pattern",
        description="Tiled motifs — dots, triangles, hexagons, waves or stripes.",
        params=pattern.PARAMS,
        render=pattern.render,
    ),
    Kind(
        id="identicon",
        label="Identicon",
        description="Symmetrical block avatar, ideal for user placeholders.",
        params=identicon.PARAMS,
        render=identicon.render,
    ),
    Kind(
        id="badge",
        label="Shield badge",
        description="Gradient shield with initials — achievements and labels.",
        params=badge.PARAMS,
        render=badge.render,
    ),
    Kind(
        id="placeholder",
        label="Image placeholder",
        description="Framed empty-state graphic with a caption.",
        params=placeholder.PARAMS,
        render=placeholder.render,
    ),
)

KINDS: Mapping[str, Kind] = {kind.id: kind for kind in _KINDS}


def get_kind(kind: str) -> Kind:
    """Look up a kind by id, raising :class:`UnknownKindError` when missing."""
    try:
        return KINDS[kind]
    except KeyError as exc:
        raise UnknownKindError(kind) from exc


def generate(
    kind: str,
    *,
    seed: str = "demo",
    size: int = CANVAS,
    palette: str = "vivid",
    params: Mapping[str, object] | None = None,
) -> str:
    """Render one asset and return the complete SVG document."""
    definition = get_kind(kind)
    if palette not in STYLES:
        raise ValueError(f"unknown palette style: {palette!r}")

    rng = make_rng(definition.id, seed, palette)
    ctx = Context(
        kind=definition.id,
        seed=seed,
        size=size,
        rng=rng,
        palette=build_palette(rng, palette),
        params=dict(params or {}),
    )
    defs, body = definition.render(ctx)
    return document(
        size=size,
        defs=defs,
        body=body,
        title=f"{definition.label} · {seed}",
    )
