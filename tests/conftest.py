"""Shared pytest fixtures for the code-only 3D asset pipeline."""

from __future__ import annotations

import pathlib
import sys

import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
SCRIPTS_DIR = REPO_ROOT / "scripts"

if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))


@pytest.fixture(scope="session")
def repo_root() -> pathlib.Path:
    return REPO_ROOT


@pytest.fixture(scope="session")
def public_dir(repo_root: pathlib.Path) -> pathlib.Path:
    return repo_root / "public"


@pytest.fixture(scope="session")
def specs(repo_root: pathlib.Path):
    from generators.specs import load_specs

    return load_specs(repo_root)


@pytest.fixture(scope="session")
def spec_by_id(specs):
    return {spec.id: spec for spec in specs}
