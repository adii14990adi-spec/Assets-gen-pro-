"""Tests for the HTTP API."""

from __future__ import annotations

import xml.etree.ElementTree as ET

import pytest
from fastapi.testclient import TestClient

from app import app

client = TestClient(app)

KIND_IDS = ["mesh", "pattern", "identicon", "badge", "placeholder"]


def test_health() -> None:
    response = client.get("/api/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["kinds"] == len(KIND_IDS)


def test_kinds_endpoint_describes_params() -> None:
    response = client.get("/api/kinds")
    assert response.status_code == 200
    kinds = response.json()["kinds"]
    assert [kind["id"] for kind in kinds] == KIND_IDS
    for kind in kinds:
        assert kind["label"] and kind["description"]
        for param in kind["params"]:
            assert {"name", "label", "type", "default"} <= param.keys()


@pytest.mark.parametrize("kind", KIND_IDS)
def test_asset_svg_defaults(kind: str) -> None:
    response = client.get("/api/asset.svg", params={"kind": kind, "seed": "abc"})
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("image/svg+xml")
    assert response.headers["etag"]
    ET.fromstring(response.text)


def test_asset_svg_is_cacheable_and_revalidates() -> None:
    first = client.get("/api/asset.svg", params={"kind": "mesh", "seed": "cache"})
    etag = first.headers["etag"]
    assert "immutable" in first.headers["cache-control"]

    second = client.get(
        "/api/asset.svg",
        params={"kind": "mesh", "seed": "cache"},
        headers={"If-None-Match": etag},
    )
    assert second.status_code == 304
    assert second.content == b""


@pytest.mark.parametrize(
    "params",
    [
        {"kind": "nope"},
        {"kind": "mesh", "palette": "chartreuse"},
        {"kind": "mesh", "size": 8},
        {"kind": "mesh", "size": 99999},
        {"kind": "mesh", "size": "big"},
        {"kind": "mesh", "blobs": 50},
        {"kind": "pattern", "motif": "spiral"},
        {"kind": "badge", "text": "TOO-LONG-FOR-A-BADGE"},
    ],
)
def test_invalid_parameters_return_errors(params: dict[str, object]) -> None:
    response = client.get("/api/asset.svg", params=params)
    assert response.status_code in {404, 422}
    assert "detail" in response.json()


def test_head_advertises_metadata_without_a_body() -> None:
    response = client.head("/api/asset.svg", params={"kind": "mesh", "seed": "head"})
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("image/svg+xml")
    assert response.headers["etag"]
    assert int(response.headers["content-length"]) > 0
    assert response.content == b""


def test_missing_kind_is_rejected() -> None:
    assert client.get("/api/asset.svg").status_code == 422


def test_post_renders_same_as_get() -> None:
    body = {
        "kind": "badge",
        "seed": "post",
        "size": 300,
        "palette": "neon",
        "params": {"text": "AB", "sparkles": False},
    }
    posted = client.post("/api/asset.svg", json=body)
    assert posted.status_code == 200

    fetched = client.get(
        "/api/asset.svg",
        params={
            "kind": "badge",
            "seed": "post",
            "size": 300,
            "palette": "neon",
            "text": "AB",
            "sparkles": "false",
        },
    )
    assert fetched.text == posted.text


def test_post_rejects_bad_payloads() -> None:
    assert client.post("/api/asset.svg", json={"seed": "x"}).status_code == 422
    assert client.post("/api/asset.svg", json={"kind": "nope"}).status_code == 404
    assert (
        client.post("/api/asset.svg", json={"kind": "mesh", "params": []}).status_code
        == 422
    )


def test_batch_returns_requested_count() -> None:
    response = client.get(
        "/api/batch.json", params={"kind": "identicon", "seed": "team", "count": 5}
    )
    assert response.status_code == 200
    items = response.json()["items"]
    assert len(items) == 5
    assert len({item["seed"] for item in items}) == 5
    assert all(item["url"].startswith("/api/asset.svg?") for item in items)

    derived = client.get(items[0]["url"])
    assert derived.status_code == 200


def test_batch_count_is_clamped() -> None:
    body = client.get(
        "/api/batch.json", params={"kind": "mesh", "seed": "s", "count": 999}
    ).json()
    assert len(body["items"]) == 32


def test_seed_endpoint_is_random() -> None:
    first = client.get("/api/seed").json()["seed"]
    second = client.get("/api/seed").json()["seed"]
    assert first != second
    assert len(first) == 12


def test_ui_is_served() -> None:
    response = client.get("/")
    assert response.status_code == 200
    assert "Assets Gen Pro" in response.text
    assert 'src="app.js"' in response.text


def test_ui_assets_are_served() -> None:
    assert client.get("/styles.css").status_code == 200
    assert client.get("/app.js").status_code == 200


def test_ui_uses_relative_api_paths() -> None:
    for path in ("/app.js",):
        source = client.get(path).text
        assert "localhost" not in source
        assert "127.0.0.1" not in source
