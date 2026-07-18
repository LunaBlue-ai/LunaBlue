"""Tests for readiness vs. liveness (Step 17, ``api/routes/health.py``).

Liveness is covered in test_llm_runtime.py (answers during generation); these
cover the per-dependency readiness checks. The all-green path needs the
suite's temp-file SQLite database (``audit_db`` fixture).
"""

from httpx import ASGITransport, AsyncClient

from app.audit import db
from tests.backend.fakes import FakeAuditService, FakeLlamaRuntime, make_app


def _make_app(runtime=None):
    if runtime is None:
        runtime = FakeLlamaRuntime()
        runtime.load()
    return make_app(FakeAuditService(), runtime)


def _client(app) -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def test_liveness_never_touches_dependencies():
    # No database engine, no model: /api/health still answers 200.
    await db.dispose_engine()
    app = _make_app()
    app.state.llm_runtime = None
    async with _client(app) as client:
        resp = await client.get("/api/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


async def test_readiness_reports_every_check_when_degraded():
    await db.dispose_engine()  # database check must fail
    app = _make_app()
    async with _client(app) as client:
        resp = await client.get("/api/health/ready")
    assert resp.status_code == 503
    body = resp.json()
    assert body["status"] == "unavailable"
    checks = body["checks"]
    assert set(checks) == {
        "model",
        "database",
        "audit_queue",
        "agent_runner",
        "embedding",
    }
    assert checks["model"]["ok"] is True
    assert checks["database"] == {"ok": False, "detail": "unreachable"}
    assert checks["audit_queue"]["ok"] is True
    # Embeddings are an optional enhancement: absent runtime reports ok.
    assert checks["embedding"] == {"ok": True, "detail": "disabled"}
    # make_app never starts the runner workers.
    assert checks["agent_runner"]["ok"] is False
    # Legacy fields survive for older consumers.
    assert body["model"] == "model.gguf"
    assert body["database"] == "unreachable"


async def test_readiness_reports_unhealthy_model_after_crash():
    await db.dispose_engine()
    runtime = FakeLlamaRuntime()
    runtime.load()
    runtime._mark_unhealthy(RuntimeError("llama crashed"))
    app = _make_app(runtime)
    async with _client(app) as client:
        resp = await client.get("/api/health/ready")
    assert resp.status_code == 503
    model_check = resp.json()["checks"]["model"]
    assert model_check["ok"] is False
    assert model_check["detail"] == "unhealthy"
    assert "llama crashed" in model_check["error"]
    # The model id is still reported: it is loaded, just unhealthy.
    assert resp.json()["model"] == "model.gguf"


async def test_readiness_is_ok_with_all_dependencies_green(audit_db):
    """Full 200 path: database up (temp SQLite), model healthy, audit queue
    idle, runner started."""
    app = _make_app()
    app.state.agent_runner.start()
    try:
        async with _client(app) as client:
            resp = await client.get("/api/health/ready")
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "ok"
        assert all(check["ok"] for check in body["checks"].values())
        assert body["checks"]["database"]["detail"] == "ok"
        assert body["checks"]["audit_queue"]["dropped_total"] == 0
    finally:
        await app.state.agent_runner.close()


async def test_readiness_reports_stopped_runner(audit_db):
    app = _make_app()
    app.state.agent_runner.start()
    await app.state.agent_runner.close()
    async with _client(app) as client:
        resp = await client.get("/api/health/ready")
    assert resp.status_code == 503
    assert resp.json()["checks"]["agent_runner"] == {
        "ok": False,
        "detail": "stopped",
    }
