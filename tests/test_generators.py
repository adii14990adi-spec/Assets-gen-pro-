"""Tests for the pure rendering layer."""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET

import pytest

from assets_gen import KINDS, generate
from assets_gen.generators import UnknownKindError, get_kind
from assets_gen.palettes import STYLES, build_palette
from assets_gen.params import ParamError
from assets_gen.rng import make_rng

SEEDS = ["demo", "aurora", "", "Ünïcode seed", "a" * 200]
COLOR = re.compile(r"#[0-9a-f]{6}")


@pytest.mark.parametrize("kind", sorted(KINDS))
@pytest.mark.parametrize("palette", STYLES)
def test_every_kind_renders_valid_svg(kind: str, palette: str) -> None:
    svg = generate(kind, seed="aurora", size=512, palette=palette)
    assert svg.startswith("<svg")
    assert svg.endswith("</svg>")
    assert 'width="512"' in svg
    assert 'viewBox="0 0 400 400"' in svg

    root = ET.fromstring(svg)  # raises on malformed XML
    assert root.tag.endswith("svg")


@pytest.mark.parametrize("kind", sorted(KINDS))
def test_rendering_is_deterministic(kind: str) -> None:
    first = generate(kind, seed="stable")
    second = generate(kind, seed="stable")
    assert first == second


@pytest.mark.parametrize("kind", sorted(KINDS))
def test_seed_changes_output(kind: str) -> None:
    assert generate(kind, seed="alpha") != generate(kind, seed="beta")


@pytest.mark.parametrize("kind", sorted(KINDS))
@pytest.mark.parametrize("seed", SEEDS)
def test_odd_seeds_are_escaped_safely(kind: str, seed: str) -> None:
    svg = generate(kind, seed=seed)
    ET.fromstring(svg)
    assert "<script" not in svg


@pytest.mark.parametrize("kind", sorted(KINDS))
def test_palette_only_emits_valid_hex_colours(kind: str) -> None:
    svg = generate(kind, seed="colours")
    assert COLOR.findall(svg)


@pytest.mark.parametrize("kind", sorted(KINDS))
def test_output_has_no_broken_numbers(kind: str) -> None:
    svg = generate(kind, seed="numbers", params={"blobs": 10})
    for token in ("nan", "NaN", "None", "undefined", "inf"):
        assert token not in svg


def test_unknown_kind_raises() -> None:
    with pytest.raises(UnknownKindError):
        generate("nope")
    with pytest.raises(UnknownKindError):
        get_kind("nope")


def test_unknown_palette_raises() -> None:
    with pytest.raises(ValueError):
        generate("mesh", palette="chartreuse")


def test_palette_styles_are_distinct() -> None:
    generated = {style: build_palette(make_rng(style), style) for style in STYLES}
    assert len({palette.bg for palette in generated.values()}) == len(STYLES)
    for palette in generated.values():
        assert len(palette.accents) == 4


def test_param_validation_rejects_bad_values() -> None:
    with pytest.raises(ParamError):
        generate("mesh", params={"blobs": "99"})
    with pytest.raises(ParamError):
        generate("mesh", params={"blobs": "not-a-number"})
    with pytest.raises(ParamError):
        generate("pattern", params={"motif": "spiral"})
    with pytest.raises(ParamError):
        generate("badge", params={"text": "MUCH TOO LONG"})


def test_params_change_output() -> None:
    few = generate("mesh", params={"blobs": 3})
    many = generate("mesh", params={"blobs": 10})
    assert few != many


def test_badge_renders_requested_initials() -> None:
    svg = generate("badge", params={"text": "ad"})
    assert ">AD<" in svg


def test_random_seed_shape() -> None:
    from assets_gen.rng import random_seed

    seed = random_seed(10)
    assert len(seed) == 10
    assert random_seed(10) != seed
    assert re.fullmatch(r"[a-z0-9]+", seed)
