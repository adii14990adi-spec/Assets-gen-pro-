#!/usr/bin/env python3
"""Build every 3D asset with pure Python and index it for the static gallery.

Run locally::

    python scripts/build_all_assets.py

or in CI (``.github/workflows/deploy.yml``). The script:

1. Loads the declarative asset catalogue (``presets/*.json`` + ``specs.py``).
2. Runs the procedural Python generators in ``scripts/generators/`` (Trimesh +
   NumPy + SciPy, optional ``bpy`` verification).
3. Structurally validates and writes binary ``.glb`` files to
   ``public/assets/models/``.
4. Regenerates ``public/assets/manifest.json`` with measured metadata for every
   model, so the GitHub Pages gallery can be fully static.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import pathlib
import subprocess
import sys
import time
from typing import Any

SCRIPT_DIR = pathlib.Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from generators import (  # noqa: E402  (path bootstrap must run first)
    CATEGORY_META,
    CATEGORY_ORDER,
    HERO_FACE_BAND,
    AssetGenerationError,
    AssetSpec,
    generate_asset,
    load_specs,
    runtime_banner,
    validate_glb_bytes,
)

MANIFEST_SCHEMA_VERSION = 2
DEFAULT_OUTPUT = pathlib.Path("public/assets")
DEFAULT_BRANCH = "main"


# ---------------------------------------------------------------------------
# Repository metadata
# ---------------------------------------------------------------------------


def _git(*args: str) -> str:
    try:
        return subprocess.run(
            ["git", *args],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        ).stdout.strip()
    except (OSError, subprocess.SubprocessError):  # pragma: no cover - git unavailable
        return ""


def resolve_repository_url() -> str:
    """Best-effort canonical repository URL (CI env first, then git remote)."""
    env_repo = os.environ.get("GITHUB_REPOSITORY", "").strip()
    if env_repo:
        server = os.environ.get("GITHUB_SERVER_URL", "https://github.com").rstrip("/")
        return f"{server}/{env_repo}"
    remote = _git("config", "--get", "remote.origin.url")
    if remote.startswith("git@github.com:"):
        remote = "https://github.com/" + remote[len("git@github.com:") :]
    if remote.endswith(".git"):
        remote = remote[: -len(".git")]
    if remote.startswith("http"):
        return remote
    return ""


def resolve_commit_sha() -> str:
    return (os.environ.get("GITHUB_SHA") or _git("rev-parse", "HEAD")).strip()


def utc_now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


# ---------------------------------------------------------------------------
# Asset building
# ---------------------------------------------------------------------------


def _config_for(spec: AssetSpec, polygon_budget: int) -> dict[str, Any]:
    return {
        "asset_id": spec.id,
        "category": spec.category,
        "preset_id": spec.id,
        "polygon_budget": polygon_budget,
        "quality_profile": spec.quality_profile,
        "material_preset": spec.material_preset,
        "parameters": dict(spec.parameters),
        "seed": spec.seed,
        "flat_shading": spec.flat_shading,
    }


def build_spec(spec: AssetSpec, *, quiet: bool = False) -> tuple[bytes, dict[str, Any]]:
    """Generate one asset, retrying budget candidates until the face band is met."""
    last: tuple[bytes, dict[str, Any]] | None = None
    for budget in spec.face_budget_candidates:
        asset = generate_asset(_config_for(spec, budget))
        report = validate_glb_bytes(asset.glb_bytes, expected_triangles=asset.triangles)
        record = {
            "glb_bytes": asset.glb_bytes,
            "vertex_count": asset.vertices,
            "face_count": asset.faces,
            "triangle_count": asset.triangles,
            "file_size_bytes": asset.file_size_bytes,
            "file_size_kb": asset.file_size_kb,
            "generation_seconds": asset.generation_seconds,
            "flat_shading": asset.flat_shading,
            "mesh_count": asset.mesh_count,
            "material_count": asset.material_count,
            "dimensions": {
                "x": asset.dimensions[0],
                "y": asset.dimensions[1],
                "z": asset.dimensions[2],
            },
            "polygon_budget": budget,
            "seed": asset.seed,
            "validation": report,
        }
        last = (asset.glb_bytes, record)
        if not spec.face_band:
            break
        low, high = spec.face_band
        if low <= asset.faces <= high:
            if not quiet:
                print(
                    f"    face band {low}-{high} satisfied at polygon budget {budget} "
                    f"({asset.faces:,} faces)"
                )
            break
    assert last is not None, "AssetSpec produced no budget candidates."
    return last


def build_manifest_entry(
    spec: AssetSpec, record: dict[str, Any], *, updated_at: str, models_dir_name: str
) -> dict[str, Any]:
    return {
        "id": spec.id,
        "name": spec.name,
        "category": spec.category,
        "script_source": spec.script_source,
        "glb_path": f"assets/{models_dir_name}/{spec.id}.glb",
        "vertex_count": record["vertex_count"],
        "face_count": record["face_count"],
        "triangle_count": record["triangle_count"],
        "file_size_kb": record["file_size_kb"],
        "file_size_bytes": record["file_size_bytes"],
        "updated_at": updated_at,
        "description": spec.description,
        "tags": list(spec.tags),
        "material_preset": spec.material_preset,
        "quality_profile": spec.quality_profile,
        "polygon_budget": record["polygon_budget"],
        "flat_shading": record["flat_shading"],
        "mesh_count": record["mesh_count"],
        "material_count": record["material_count"],
        "dimensions": record["dimensions"],
        "seed": record["seed"],
        "generation_seconds": record["generation_seconds"],
        "glb_version": record["validation"]["version"],
        "has_vertex_colors": record["validation"]["has_vertex_colors"],
        "has_uvs": record["validation"]["has_uvs"],
    }


def write_manifest(
    entries: list[dict[str, Any]],
    manifest_path: pathlib.Path,
    *,
    generated_at: str,
    models_dir_name: str,
) -> dict[str, Any]:
    categories = []
    for category in CATEGORY_ORDER:
        members = [entry for entry in entries if entry["category"] == category]
        if not members:
            continue
        meta = CATEGORY_META[category]
        categories.append(
            {
                "id": category,
                "label": meta["label"],
                "description": meta["description"],
                "script": meta["script"],
                "count": len(members),
            }
        )

    manifest = {
        "schema_version": MANIFEST_SCHEMA_VERSION,
        "generated_at": generated_at,
        "generator": "scripts/build_all_assets.py",
        "engine": runtime_banner(),
        "repository_url": resolve_repository_url(),
        "commit": resolve_commit_sha(),
        "default_branch": os.environ.get("GITHUB_REF_NAME", DEFAULT_BRANCH),
        "asset_count": len(entries),
        "categories": categories,
        "models": entries,
    }
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return manifest


def clean_stale_models(models_dir: pathlib.Path, keep: set[str]) -> list[str]:
    removed: list[str] = []
    for glb in sorted(models_dir.glob("*.glb")):
        if glb.stem not in keep:
            glb.unlink()
            removed.append(glb.name)
    return removed


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        "--output-dir",
        default=str(DEFAULT_OUTPUT),
        help="Directory that is published to GitHub Pages (default: public/assets).",
    )
    parser.add_argument(
        "--only",
        nargs="+",
        metavar="PRESET_ID",
        help="Build only these preset ids (default: every preset).",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=None,
        help="Override the deterministic seed for every asset.",
    )
    parser.add_argument(
        "--no-clean",
        action="store_true",
        help="Keep .glb files in the models directory that are not in the catalogue.",
    )
    parser.add_argument("--quiet", action="store_true", help="Only print the final summary.")
    args = parser.parse_args(argv)

    output_dir = (REPO_ROOT / args.output_dir).resolve()
    models_dir = output_dir / "models"
    manifest_path = output_dir / "manifest.json"
    models_dir.mkdir(parents=True, exist_ok=True)

    specs = load_specs(REPO_ROOT)
    if args.seed is not None:
        specs = [
            AssetSpec(**{**spec.__dict__, "seed": args.seed})  # type: ignore[arg-type]
            for spec in specs
        ]
    if args.only:
        wanted = {item.strip() for item in args.only}
        unknown = wanted - {spec.id for spec in specs}
        if unknown:
            print(f"::error::Unknown preset id(s): {sorted(unknown)}", file=sys.stderr)
            return 2
        specs = [spec for spec in specs if spec.id in wanted]

    if not specs:
        print("::error::No assets selected.", file=sys.stderr)
        return 2

    print(f"Procedural 3D asset build — {len(specs)} model(s)")
    print(f"  engine      : {runtime_banner()}")
    print(f"  output      : {output_dir.relative_to(REPO_ROOT) if output_dir.is_relative_to(REPO_ROOT) else output_dir}")
    print()

    updated_at = utc_now_iso()
    entries: list[dict[str, Any]] = []
    failures: list[tuple[str, str]] = []
    started = time.perf_counter()

    for index, spec in enumerate(specs, start=1):
        label = f"[{index}/{len(specs)}] {spec.id} ({spec.category})"
        if not args.quiet:
            print(f"{label}")
        try:
            glb_bytes, record = build_spec(spec, quiet=args.quiet)
            glb_path = models_dir / f"{spec.id}.glb"
            glb_path.write_bytes(glb_bytes)
            # Re-read from disk and validate the shipped file, not just the buffer.
            on_disk = validate_glb_bytes(glb_path.read_bytes(), expected_triangles=record["triangle_count"])
            if on_disk["byte_length"] != len(glb_bytes):
                raise AssetGenerationError("On-disk GLB size differs from the generated buffer.")
            if spec.face_band and not (spec.face_band[0] <= record["face_count"] <= spec.face_band[1]):
                raise AssetGenerationError(
                    f"{spec.id} exported {record['face_count']:,} faces, outside the required "
                    f"{spec.face_band[0]}-{spec.face_band[1]} face band."
                )
            entries.append(
                build_manifest_entry(spec, record, updated_at=updated_at, models_dir_name=models_dir.name)
            )
            if not args.quiet:
                band = ""
                if spec.face_band:
                    band = f"  (face band {HERO_FACE_BAND[0]}-{HERO_FACE_BAND[1]})"
                print(
                    f"    ok  {record['vertex_count']:>7,} verts | {record['triangle_count']:>7,} tris | "
                    f"{record['file_size_kb']:>8.2f} KB | {record['generation_seconds']:.2f}s{band}"
                )
        except Exception as exc:  # noqa: BLE001 - reported per asset, build continues
            failures.append((spec.id, f"{type(exc).__name__}: {exc}"))
            print(f"    FAILED {type(exc).__name__}: {exc}", file=sys.stderr)

    removed = [] if args.no_clean else clean_stale_models(models_dir, {entry["id"] for entry in entries})
    if removed and not args.quiet:
        print(f"\nRemoved {len(removed)} stale model(s): {', '.join(removed)}")

    if not entries:
        print("\n::error::Every asset failed; manifest not written.", file=sys.stderr)
        return 1

    manifest = write_manifest(entries, manifest_path, generated_at=updated_at, models_dir_name=models_dir.name)
    elapsed = time.perf_counter() - started

    print("\nManifest:", manifest_path.relative_to(REPO_ROOT) if manifest_path.is_relative_to(REPO_ROOT) else manifest_path)
    for category in manifest["categories"]:
        print(f"  {category['label']:<36} {category['count']:>2} model(s)  [{category['script']}]")
    total_kb = sum(entry["file_size_kb"] for entry in entries)
    print(f"  {'TOTAL':<36} {len(entries):>2} model(s)  {total_kb:,.2f} KB  in {elapsed:.2f}s")

    if failures:
        print(f"\n::error::{len(failures)} asset(s) failed:", file=sys.stderr)
        for preset_id, message in failures:
            print(f"  - {preset_id}: {message}", file=sys.stderr)
        return 1
    print("\nAll assets generated, validated, and indexed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
