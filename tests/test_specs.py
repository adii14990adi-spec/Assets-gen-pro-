"""The declarative asset catalogue must stay complete and internally consistent."""

from __future__ import annotations

import pathlib

from generators.specs import (
    CATEGORY_META,
    CATEGORY_ORDER,
    HERO_FACE_BAND,
    HERO_PRESET_ID,
    load_specs,
)

EXPECTED_COUNT = 18


def test_every_preset_is_catalogued(specs):
    assert len(specs) == EXPECTED_COUNT
    ids = [spec.id for spec in specs]
    assert len(ids) == len(set(ids)), "duplicate preset ids in the manifest catalogue"


def test_categories_are_complete_and_ordered(specs):
    present = {spec.category for spec in specs}
    assert present == set(CATEGORY_ORDER)
    order = [CATEGORY_ORDER.index(spec.category) for spec in specs]
    assert order == sorted(order), "specs must be grouped by category"


def test_each_category_has_a_dedicated_generator(repo_root: pathlib.Path, specs):
    for spec in specs:
        script = repo_root / spec.script_source
        assert script.is_file(), f"{spec.id} points at a missing generator: {spec.script_source}"
        assert spec.script_source in {
            meta["script"] for meta in CATEGORY_META.values()
        } | {"scripts/generators/character_tpose.py"}


def test_hero_character_is_configured_for_the_face_band(spec_by_id):
    hero = spec_by_id[HERO_PRESET_ID]
    assert hero.face_band == HERO_FACE_BAND
    assert hero.script_source == "scripts/generators/character_tpose.py"
    assert hero.parameters["pose"] == "t_pose"
    assert hero.parameters["include_clothing"] is True
    assert hero.flat_shading is True
    assert hero.face_budget_candidates, "hero needs a budget ladder for its face band"


def test_budgets_and_seeds_are_sane(specs):
    for spec in specs:
        assert 300 <= spec.polygon_budget <= 60_000, spec.id
        assert 0 <= spec.seed < 2**31, spec.id
        assert spec.name and spec.description, spec.id
        assert spec.tags, spec.id


def test_specs_are_deterministic(repo_root: pathlib.Path):
    first = load_specs(repo_root)
    second = load_specs(repo_root)
    assert [(s.id, s.seed, s.polygon_budget) for s in first] == [
        (s.id, s.seed, s.polygon_budget) for s in second
    ]
