"""Guardrails for the single GitHub Actions deployment workflow."""

from __future__ import annotations

import pathlib

import pytest

yaml = pytest.importorskip("yaml")


@pytest.fixture(scope="module")
def workflows(repo_root: pathlib.Path) -> dict[str, dict]:
    loaded = {}
    for path in sorted((repo_root / ".github" / "workflows").glob("*.yml")):
        loaded[path.name] = yaml.safe_load(path.read_text(encoding="utf-8"))
    return loaded


@pytest.fixture(scope="module")
def deploy(workflows):
    assert "deploy.yml" in workflows, "deploy.yml must exist"
    return workflows["deploy.yml"]


def test_only_one_workflow_remains(workflows):
    assert set(workflows) == {"deploy.yml"}, f"unexpected workflows: {sorted(workflows)}"


def test_triggers_are_push_to_main_and_manual(deploy):
    # PyYAML maps the bare key `on:` to the boolean True.
    triggers = deploy.get("on", deploy.get(True))
    assert triggers == {"push": {"branches": ["main"]}, "workflow_dispatch": None}


def test_workflow_can_publish_the_gh_pages_branch(deploy):
    assert deploy["permissions"]["contents"] == "write"


def test_required_steps_are_present_in_order(deploy):
    steps = deploy["jobs"]["build-and-deploy"]["steps"]
    uses = [step.get("uses", "") for step in steps]
    runs = " ".join(step.get("run", "") for step in steps)

    assert "actions/checkout@v4" in uses
    assert "actions/setup-python@v5" in uses
    assert any(use.startswith("peaceiris/actions-gh-pages@v4") for use in uses)

    setup = next(step for step in steps if step.get("uses") == "actions/setup-python@v5")
    assert str(setup["with"]["python-version"]) == "3.11"

    install_index = next(i for i, step in enumerate(steps) if "pip install" in step.get("run", ""))
    build_index = next(i for i, step in enumerate(steps) if "build_all_assets.py" in step.get("run", ""))
    deploy_index = next(
        i for i, step in enumerate(steps) if step.get("uses", "").startswith("peaceiris/actions-gh-pages")
    )
    assert install_index < build_index < deploy_index, "steps must install → generate → deploy"

    for dependency in ("numpy", "scipy", "trimesh"):
        assert dependency in runs, f"{dependency} is not installed in CI"
    assert "python scripts/build_all_assets.py" in runs


def test_deploy_step_publishes_the_public_folder(deploy):
    steps = deploy["jobs"]["build-and-deploy"]["steps"]
    publish = next(step for step in steps if step.get("uses", "").startswith("peaceiris/actions-gh-pages"))
    options = publish["with"]
    assert options["publish_dir"] == "./public"
    assert options["github_token"] == "${{ secrets.GITHUB_TOKEN }}"
    assert options["publish_branch"] == "gh-pages"
    assert options["enable_jekyll"] is False


def test_pages_actions_are_not_used(deploy):
    """actions/configure-pages fails hard with 'Get Pages site failed'."""

    text = yaml.safe_dump(deploy)
    for forbidden in ("actions/configure-pages", "actions/deploy-pages", "actions/upload-pages-artifact"):
        assert forbidden not in text, f"{forbidden} must not be referenced"


def test_no_server_runtime_remains_in_the_repository(repo_root: pathlib.Path):
    for relative in ("app.py", "main.py", "backend", "frontend", "render.yaml", "Dockerfile"):
        assert not (repo_root / relative).exists(), f"server-era artifact still present: {relative}"
