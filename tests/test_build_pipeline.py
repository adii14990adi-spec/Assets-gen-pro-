"""``scripts/build_all_assets.py`` must produce a self-describing static bundle."""

from __future__ import annotations

import json
import pathlib

import build_all_assets
import pytest
from generators.pipeline import validate_glb_bytes

REQUIRED_MODEL_KEYS = {
    "id",
    "name",
    "category",
    "script_source",
    "glb_path",
    "vertex_count",
    "face_count",
    "file_size_kb",
    "updated_at",
}


@pytest.fixture(scope="module")
def built_bundle(tmp_path_factory):
    out_dir = tmp_path_factory.mktemp("site") / "assets"
    code = build_all_assets.main(
        [
            "--output-dir",
            str(out_dir),
            "--only",
            "br_supply_crate",
            "explosive_fuel_barrel",
            "--quiet",
        ]
    )
    return code, out_dir


def test_build_command_succeeds(built_bundle):
    code, out_dir = built_bundle
    assert code == 0
    assert (out_dir / "manifest.json").is_file()
    assert (out_dir / "models" / "br_supply_crate.glb").is_file()
    assert (out_dir / "models" / "explosive_fuel_barrel.glb").is_file()


def test_manifest_contains_every_required_field(built_bundle):
    _code, out_dir = built_bundle
    manifest = json.loads((out_dir / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["asset_count"] == 2
    assert manifest["generator"] == "scripts/build_all_assets.py"
    assert manifest["schema_version"] == 2
    assert "numpy" in manifest["engine"] and "trimesh" in manifest["engine"]
    assert len(manifest["categories"]) == 1

    for model in manifest["models"]:
        missing = REQUIRED_MODEL_KEYS - model.keys()
        assert not missing, f"{model['id']} is missing {sorted(missing)}"
        assert model["script_source"].startswith("scripts/generators/")
        assert model["glb_path"] == f"assets/models/{model['id']}.glb"
        assert model["updated_at"].endswith("Z")


def test_manifest_numbers_match_the_shipped_bytes(built_bundle):
    _code, out_dir = built_bundle
    manifest = json.loads((out_dir / "manifest.json").read_text(encoding="utf-8"))
    for model in manifest["models"]:
        # glb_path is relative to the published public/ root (assets/models/…).
        glb = out_dir / "models" / f"{model['id']}.glb"
        data = glb.read_bytes()
        report = validate_glb_bytes(data, expected_triangles=model["face_count"])
        assert report["triangles"] == model["face_count"]
        assert round(len(data) / 1024, 2) == model["file_size_kb"]
        assert model["vertex_count"] > model["face_count"]


def test_stale_models_are_cleaned_up(tmp_path):
    out_dir = tmp_path / "assets"
    (out_dir / "models").mkdir(parents=True)
    (out_dir / "models" / "ghost_model.glb").write_bytes(b"glTF-stale")
    code = build_all_assets.main(
        ["--output-dir", str(out_dir), "--only", "br_supply_crate", "--quiet"]
    )
    assert code == 0
    assert not (out_dir / "models" / "ghost_model.glb").exists()
    assert (out_dir / "models" / "br_supply_crate.glb").is_file()


def test_unknown_preset_is_a_hard_error(tmp_path):
    code = build_all_assets.main(
        ["--output-dir", str(tmp_path / "assets"), "--only", "not_a_real_model", "--quiet"]
    )
    assert code == 2


def test_seed_override_is_reflected_in_the_manifest(tmp_path):
    out_dir = tmp_path / "assets"
    assert build_all_assets.main(
        ["--output-dir", str(out_dir), "--only", "tactical_cover_barrier", "--seed", "99", "--quiet"]
    ) == 0
    manifest = json.loads((out_dir / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["models"][0]["seed"] == 99


def test_repository_bundle_is_consistent(repo_root: pathlib.Path):
    """The committed gallery must describe the committed .glb files exactly."""

    public = repo_root / "public"
    manifest = json.loads((public / "assets" / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["asset_count"] == len(manifest["models"]) == 18
    ids = {model["id"] for model in manifest["models"]}
    on_disk = {path.stem for path in (public / "assets" / "models").glob("*.glb")}
    assert on_disk == ids, f"manifest/disk mismatch: {on_disk ^ ids}"

    for model in manifest["models"]:
        glb = public / model["glb_path"]
        data = glb.read_bytes()
        assert data[:4] == b"glTF", model["id"]
        report = validate_glb_bytes(data, expected_triangles=model["face_count"])
        assert report["triangles"] == model["face_count"]
        assert report["version"] == 2
        assert abs(len(data) / 1024 - model["file_size_kb"]) < 0.5
        assert (repo_root / model["script_source"]).is_file()

    hero = next(model for model in manifest["models"] if model["id"] == "midpoly_character")
    assert 1200 <= hero["face_count"] <= 1500
