"""The GitHub Pages gallery must stay fully static and self-contained."""

from __future__ import annotations

import json
import pathlib
import re

PUBLIC_FILES = ("index.html", ".nojekyll", "assets/manifest.json")


def _html(public_dir: pathlib.Path) -> str:
    return (public_dir / "index.html").read_text(encoding="utf-8")


def test_publish_root_contains_the_static_bundle(public_dir: pathlib.Path):
    for relative in PUBLIC_FILES:
        assert (public_dir / relative).is_file(), f"public/{relative} is missing to publish"
    # GitHub Pages would otherwise run Jekyll and drop files/folders it dislikes.
    assert (public_dir / ".nojekyll").read_text(encoding="utf-8") == ""


def test_gallery_uses_relative_paths_for_project_urls(public_dir: pathlib.Path):
    html = _html(public_dir)
    assert "./assets/manifest.json" in html
    assert "./${model.glb_path}" in html
    # No root-absolute bundle paths: they break on /<repo-name>/ project URLs.
    assert not re.search(r"""['"]/assets/""", html)
    assert "glb_path" in html


def test_gallery_is_a_view_only_inspector(public_dir: pathlib.Path):
    html = _html(public_dir)

    # No server runtime, no generation endpoints, no localhost calls.
    lowered = html.lower()
    for forbidden in ("/api/generate", "localhost:", "127.0.0.1", "fastapi", "uvicorn", "render.com"):
        assert forbidden not in lowered, f"server-era reference leaked into the gallery: {forbidden}"

    # Nothing that could trigger a build from the browser.
    assert "method=\"post\"" not in lowered
    assert "generate(" not in html

    # Required Three.js modules.
    assert "three@" in html and "three.module.js" in html
    assert "GLTFLoader" in html and "OrbitControls" in html
    assert 'type="importmap"' in html
    assert "cdn.tailwindcss.com" in html


def test_gallery_ships_every_requested_feature(public_dir: pathlib.Path):
    html = _html(public_dir)

    # Sidebar gallery + category filters + search
    assert 'id="modelList"' in html and 'id="filters"' in html
    assert "category" in html and "state.category" in html

    # Studio 3-point lighting rig + grid helper
    assert "keyLight" in html and "fillLight" in html and "rimLight" in html
    assert "HemisphereLight" in html and "GridHelper" in html
    assert "enableDamping" in html and "TOUCH.ROTATE" in html

    # Inspector toolbar
    assert 'data-shading="flat"' in html and 'data-shading="smooth"' in html
    assert 'id="wireBtn"' in html and "Wireframe" in html
    assert 'id="rotateBtn"' in html and "controls.autoRotate" in html
    assert 'data-bg="studio"' in html and "applyBackground" in html

    # Live geometry HUD + source script + download
    for hud_id in ("statVerts", "statTris", "statSize", "statScript", "hudName", "hudCategory"):
        assert f'id="{hud_id}"' in html, f"HUD element {hud_id} missing"
    assert "vertex_count" in html and "face_count" in html and "file_size_kb" in html
    assert "script_source" in html and "/blob/" in html
    assert 'id="downloadBtn"' in html and "download .glb" in html.lower()
    assert "download" in html


def test_every_referenced_dom_id_exists(public_dir: pathlib.Path):
    html = _html(public_dir)
    declared = set(re.findall(r'id="([A-Za-z0-9_-]+)"', html))
    referenced = set(re.findall(r"\$\('([A-Za-z0-9_-]+)'\)", html))
    referenced |= set(re.findall(r"getElementById\('([A-Za-z0-9_-]+)'\)", html))
    missing = referenced - declared
    assert not missing, f"JS references unknown element ids: {sorted(missing)}"


def test_mobile_friendly_markup(public_dir: pathlib.Path):
    html = _html(public_dir)
    assert 'name="viewport"' in html and "width=device-width" in html
    assert "touch-action" in html
    assert "prefers-reduced-motion" in html
    assert "#sidebar" in html  # drawer behaviour for small screens


def test_manifest_is_published_next_to_the_models(public_dir: pathlib.Path):
    manifest = json.loads((public_dir / "assets" / "manifest.json").read_text(encoding="utf-8"))
    for model in manifest["models"]:
        glb = public_dir / model["glb_path"]
        assert glb.is_file(), f"manifest points at a missing file: {model['glb_path']}"
    assert manifest["asset_count"] == 18
    categories = {category["id"] for category in manifest["categories"]}
    assert categories == {"humanoid", "architecture", "environment", "props"}


def test_no_generator_logic_lives_in_the_browser(public_dir: pathlib.Path):
    """The web app may orbit, shade, and tint — never build geometry."""

    html = _html(public_dir)
    forbidden = (
        "BufferGeometry().setFromPoints(",
        "new THREE.BoxGeometry(",
        "new THREE.CylinderGeometry(",
        "new THREE.SphereGeometry(",
        "LatheGeometry",
        "ExtrudeGeometry",
    )
    for token in forbidden:
        assert token not in html, f"viewer appears to synthesize geometry: {token}"
