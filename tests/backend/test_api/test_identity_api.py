"""Tests for GET/PUT /api/identity (Step 20)."""

import pytest

from app.state.identity import IdentityStore
from tests.backend.fakes import FakeAuditService, make_client, make_runtime

_EMPTY = {
    "name": "",
    "age": "",
    "occupation": "",
    "personality": "",
    "interests": "",
}


@pytest.fixture
def audit():
    return FakeAuditService()


@pytest.fixture
def runtime_and_fake(tmp_path):
    return make_runtime(tmp_path)


async def test_get_returns_empty_defaults(audit, runtime_and_fake):
    async with make_client(audit, runtime_and_fake[0]) as client:
        resp = await client.get("/api/identity")
    assert resp.status_code == 200
    assert resp.json() == _EMPTY


async def test_get_reflects_a_seeded_store(audit, runtime_and_fake):
    identity = IdentityStore(name="Luna", interests="cats")
    async with make_client(
        audit, runtime_and_fake[0], identity=identity
    ) as client:
        resp = await client.get("/api/identity")
    assert resp.json() == {**_EMPTY, "name": "Luna", "interests": "cats"}


async def test_put_replaces_and_get_round_trips(audit, runtime_and_fake):
    async with make_client(audit, runtime_and_fake[0]) as client:
        body = {
            "name": "  Luna  ",
            "age": "7",
            "occupation": "assistant",
            "personality": "curious",
            "interests": "cats",
        }
        put = await client.put("/api/identity", json=body)
        assert put.status_code == 200
        assert put.json()["name"] == "Luna"  # whitespace stripped

        get = await client.get("/api/identity")
        assert get.json() == {
            "name": "Luna",
            "age": "7",
            "occupation": "assistant",
            "personality": "curious",
            "interests": "cats",
        }


async def test_partial_put_blanks_omitted_fields(audit, runtime_and_fake):
    identity = IdentityStore(name="Luna", age="7", interests="cats")
    async with make_client(
        audit, runtime_and_fake[0], identity=identity
    ) as client:
        resp = await client.put("/api/identity", json={"name": "Zed"})
        assert resp.status_code == 200
        assert resp.json() == {**_EMPTY, "name": "Zed"}  # full replace


async def test_overlong_field_is_rejected_with_422(audit, runtime_and_fake):
    async with make_client(audit, runtime_and_fake[0]) as client:
        resp = await client.put("/api/identity", json={"name": "x" * 201})
        assert resp.status_code == 422
        assert resp.json()["code"] == "validation_error"
        # The identity store is untouched.
        assert (await client.get("/api/identity")).json() == _EMPTY


async def test_openapi_documents_the_identity_endpoints(audit, runtime_and_fake):
    async with make_client(audit, runtime_and_fake[0]) as client:
        spec = (await client.get("/openapi.json")).json()
    assert spec["paths"]["/api/identity"]["get"]["summary"]
    assert spec["paths"]["/api/identity"]["put"]["summary"]
    props = spec["components"]["schemas"]["Identity"]["properties"]
    assert set(props) == {
        "name",
        "age",
        "occupation",
        "personality",
        "interests",
    }
    assert all(p["maxLength"] == 200 for p in props.values())
