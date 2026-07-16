"""Tests for serving the built frontend from FastAPI (Step 12).

The static routes never touch ``app.state``, so a bare ``create_app`` over a
fabricated bundle directory is enough — no fakes, no Postgres, no model.
"""

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import create_app

_INDEX_HTML = "<!doctype html><title>LunaBlue</title>"
_ASSET_JS = "console.log('bundle');"


def _client(static_dir) -> AsyncClient:
    app = create_app(static_dir=static_dir)
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


@pytest.fixture
def bundle_dir(tmp_path):
    """A directory shaped like a Vite build output."""
    static = tmp_path / "static"
    (static / "assets").mkdir(parents=True)
    (static / "index.html").write_text(_INDEX_HTML)
    (static / "assets" / "index-abc123.js").write_text(_ASSET_JS)
    (static / "vite.svg").write_text("<svg></svg>")
    return static


@pytest.fixture
async def client(bundle_dir):
    async with _client(bundle_dir) as c:
        yield c


async def test_root_serves_index_html_with_no_cache(client):
    resp = await client.get("/")
    assert resp.status_code == 200
    assert resp.text == _INDEX_HTML
    assert resp.headers["content-type"].startswith("text/html")
    assert resp.headers["cache-control"] == "no-cache"


async def test_hashed_assets_are_immutable_with_correct_content_type(client):
    resp = await client.get("/assets/index-abc123.js")
    assert resp.status_code == 200
    assert resp.text == _ASSET_JS
    assert "javascript" in resp.headers["content-type"]
    assert resp.headers["cache-control"] == "public, max-age=31536000, immutable"


async def test_unhashed_root_files_are_served_but_revalidated(client):
    resp = await client.get("/vite.svg")
    assert resp.status_code == 200
    assert resp.headers["cache-control"] == "no-cache"


async def test_unknown_client_route_falls_back_to_index_html(client):
    resp = await client.get("/some/client/route")
    assert resp.status_code == 200
    assert resp.text == _INDEX_HTML
    assert resp.headers["cache-control"] == "no-cache"


async def test_api_routes_win_over_the_catch_all(client):
    resp = await client.get("/api/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


async def test_unknown_api_path_is_a_json_404_not_the_spa(client):
    resp = await client.get("/api/nope")
    assert resp.status_code == 404
    body = resp.json()
    # Step 17 error envelope: code/message/request_id, detail kept for
    # backward compatibility.
    assert body["detail"] == "Not Found"
    assert body["code"] == "not_found"
    assert body["message"] == "Not Found"
    assert body["request_id"]


async def test_post_to_an_unknown_api_path_is_still_a_json_404(client):
    resp = await client.post("/api/nope", json={})
    assert resp.status_code == 404
    body = resp.json()
    assert body["detail"] == "Not Found"
    assert body["code"] == "not_found"


async def test_post_to_a_frontend_path_is_a_405(client):
    resp = await client.post("/", json={})
    assert resp.status_code == 405
    assert resp.headers["allow"] == "GET, HEAD"


async def test_unknown_ws_path_is_a_json_404_not_the_spa(client):
    resp = await client.get("/ws/nope")
    assert resp.status_code == 404
    body = resp.json()
    assert body["detail"] == "Not Found"
    assert body["code"] == "not_found"


async def test_path_traversal_cannot_escape_the_static_dir(bundle_dir, client):
    (bundle_dir.parent / "secret.txt").write_text("top secret")
    # %2e%2e decodes to ".." after routing, dodging client-side URL
    # normalization; the resolve() containment check must reject it.
    resp = await client.get("/assets/%2e%2e/%2e%2e/secret.txt")
    assert resp.status_code == 200
    assert resp.text == _INDEX_HTML  # SPA fallback, not the file


async def test_openapi_schema_is_not_polluted_by_the_catch_all(client):
    spec = (await client.get("/openapi.json")).json()
    assert all(p.startswith("/api/") for p in spec["paths"])


class TestEmptyStaticDir:
    """Dev mode: the backend runs before any frontend build exists."""

    @pytest.fixture
    async def client(self, tmp_path):
        empty = tmp_path / "static"
        empty.mkdir()
        (empty / ".gitkeep").touch()
        async with _client(empty) as c:
            yield c

    async def test_root_returns_a_dev_workflow_pointer(self, client):
        resp = await client.get("/")
        assert resp.status_code == 200
        body = resp.json()
        assert body["detail"] == "Frontend bundle not built."
        assert "build_frontend" in body["hint"]
        assert "npm run dev" in body["hint"]

    async def test_other_paths_404_with_the_same_pointer(self, client):
        resp = await client.get("/some/client/route")
        assert resp.status_code == 404
        assert resp.json()["detail"] == "Frontend bundle not built."

    async def test_api_still_works(self, client):
        assert (await client.get("/api/health")).status_code == 200
