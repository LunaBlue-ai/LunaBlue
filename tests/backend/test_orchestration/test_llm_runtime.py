"""Tests for the LLM runtime (Step 7).

All tests run against a fake ``Llama`` class injected via ``llama_factory``
(see ``tests.backend.fakes``), so the suite needs neither a model file nor the
``llama-cpp-python`` package.
"""

import asyncio
import time

import pytest
from httpx import ASGITransport, AsyncClient

from app.audit import db
from app.llm.runtime import (
    GenerationResult,
    GenerationTimeoutError,
    LlamaRuntime,
    ModelNotFoundError,
    load_system_prompt,
)
from app.main import create_app
from tests.backend.fakes import FakeAuditService, FakeLlama, make_app, make_runtime


def test_missing_model_file_fails_fast_with_actionable_error(tmp_path):
    runtime = LlamaRuntime(
        model_path=str(tmp_path / "nope.gguf"), llama_factory=FakeLlama
    )
    with pytest.raises(ModelNotFoundError) as exc_info:
        runtime.load()
    assert not runtime.loaded
    # The message must point the user at the fix.
    assert "scripts/download_model" in str(exc_info.value)
    assert "MODEL_PATH" in str(exc_info.value)


async def test_generate_before_load_raises(tmp_path):
    runtime = LlamaRuntime(
        model_path=str(tmp_path / "model.gguf"), llama_factory=FakeLlama
    )
    with pytest.raises(RuntimeError, match="before load"):
        await runtime.generate("hi")


async def test_generate_returns_text_and_metadata(tmp_path):
    runtime, fake = make_runtime(tmp_path)
    result = await runtime.generate("hello", system="be terse")

    assert isinstance(result, GenerationResult)
    assert result.text == "echo: hello"
    assert result.model_id == "model.gguf"
    assert result.prompt_tokens == 7
    assert result.completion_tokens == 3
    assert result.total_tokens == 10
    assert result.duration_ms >= 0
    assert result.finish_reason == "stop"
    # usage() is the dict the audit layer (Step 8) will persist.
    assert result.usage()["total_tokens"] == 10
    assert "duration_ms" in result.usage()

    # System prompt precedes the user turn.
    [call] = fake.calls
    assert call["messages"][0] == {"role": "system", "content": "be terse"}
    assert call["messages"][1] == {"role": "user", "content": "hello"}


async def test_settings_flow_to_llama_and_overrides_win(tmp_path):
    runtime, fake = make_runtime(
        tmp_path, context_size=2048, gpu_layers=5, max_tokens=64, temperature=0.1
    )
    assert fake.n_ctx == 2048
    assert fake.n_gpu_layers == 5

    await runtime.generate("a")
    assert fake.calls[-1]["max_tokens"] == 64
    assert fake.calls[-1]["temperature"] == 0.1

    await runtime.generate("b", max_tokens=8, temperature=0.9)
    assert fake.calls[-1]["max_tokens"] == 8
    assert fake.calls[-1]["temperature"] == 0.9


async def test_concurrent_generations_serialize_and_both_complete(tmp_path):
    runtime, fake = make_runtime(tmp_path)
    fake.block_seconds = 0.05

    results = await asyncio.gather(
        runtime.generate("one"), runtime.generate("two")
    )
    assert not fake.concurrent_entry  # never two threads inside Llama at once
    assert sorted(r.text for r in results) == ["echo: one", "echo: two"]


async def test_foreground_calls_jump_ahead_of_queued_background_ones(tmp_path):
    """Step 14 scheduling: while a generation is in flight, a waiting
    foreground call gets the next turn even if a background one queued first."""
    runtime, fake = make_runtime(tmp_path)
    fake.block_seconds = 0.05

    first = asyncio.create_task(runtime.generate("first"))
    await asyncio.sleep(0.01)  # first is now inside the (blocked) model
    background = asyncio.create_task(
        runtime.generate("background", background=True)
    )
    await asyncio.sleep(0.01)  # background queued ahead of foreground
    foreground = asyncio.create_task(runtime.generate("foreground"))

    await asyncio.gather(first, background, foreground)
    order = [
        next(m["content"] for m in call["messages"] if m["role"] == "user")
        for call in fake.calls
    ]
    assert order == ["first", "foreground", "background"]
    assert not fake.concurrent_entry


async def test_event_loop_stays_responsive_during_generation(tmp_path):
    runtime, fake = make_runtime(tmp_path)
    fake.block_seconds = 0.2

    ticks = 0

    async def ticker():
        nonlocal ticks
        for _ in range(5):
            await asyncio.sleep(0.01)
            ticks += 1

    # If generation blocked the loop, the ticker could not finish first.
    task = asyncio.create_task(runtime.generate("slow"))
    await ticker()
    assert ticks == 5
    assert not task.done()
    await task


def test_model_info_and_loaded_flag(tmp_path):
    runtime, fake = make_runtime(tmp_path, context_size=1024)
    assert runtime.loaded
    info = runtime.model_info
    assert info["model_id"] == "model.gguf"
    assert info["context_size"] == 1024
    assert info["loaded"] is True
    # No probe injected and no llama_cpp import: capability is unknown.
    assert info["gpu_offload_supported"] is None

    runtime.close()
    assert not runtime.loaded
    assert fake.closed


def test_cpu_only_build_with_gpu_layers_warns(tmp_path, caplog):
    """A CPU-only llama-cpp-python build silently ignores n_gpu_layers; the
    runtime must surface that instead of letting inference quietly run on
    CPU (the exact failure mode this guard exists for)."""
    with caplog.at_level("WARNING", logger="app.llm.runtime"):
        runtime, _ = make_runtime(
            tmp_path, gpu_layers=-1, gpu_support_probe=lambda: False
        )
    assert any(
        "no GPU offload support" in record.message for record in caplog.records
    )
    assert runtime.model_info["gpu_offload_supported"] is False


@pytest.mark.parametrize(
    ("gpu_layers", "probe_result"),
    [
        (0, False),  # CPU-only requested: nothing to warn about
        (-1, True),  # GPU requested and the build supports it
        (5, None),  # capability unknown (no llama_cpp): stay silent
    ],
)
def test_no_warning_when_offload_matches_config(
    tmp_path, caplog, gpu_layers, probe_result
):
    with caplog.at_level("WARNING", logger="app.llm.runtime"):
        runtime, _ = make_runtime(
            tmp_path, gpu_layers=gpu_layers, gpu_support_probe=lambda: probe_result
        )
    assert not any(
        "GPU offload" in record.message for record in caplog.records
    )
    assert runtime.model_info["gpu_offload_supported"] is probe_result


def test_system_prompt_template_loads():
    text = load_system_prompt()
    assert "LunaBlue" in text


# -- Step 17 guards -------------------------------------------------------------


async def test_generation_timeout_fails_cleanly_and_next_call_succeeds(tmp_path):
    runtime, fake = make_runtime(tmp_path, generation_timeout_seconds=0.05)
    fake.block_seconds = 0.2

    with pytest.raises(GenerationTimeoutError) as exc_info:
        await runtime.generate("slow")
    assert "0.1s" in str(exc_info.value) or "0.0s" in str(exc_info.value)
    # A timeout is not a crash: the model stays healthy.
    assert runtime.healthy

    # The abandoned thread holds the lock until it finishes; the next call
    # queues behind it and then succeeds — never a concurrent entry.
    fake.block_seconds = 0.0
    result = await runtime.generate("next")
    assert result.text == "echo: next"
    assert not fake.concurrent_entry


async def test_model_crash_marks_runtime_unhealthy_and_success_heals(tmp_path):
    runtime, fake = make_runtime(tmp_path)
    assert runtime.healthy

    fake.fail_with = RuntimeError("llama.cpp exploded")
    with pytest.raises(RuntimeError, match="exploded"):
        await runtime.generate("boom")
    assert not runtime.healthy
    assert "exploded" in runtime.last_error
    assert runtime.model_info["healthy"] is False

    # The runtime still accepts calls; a successful generation self-heals.
    fake.fail_with = None
    await runtime.generate("recovered")
    assert runtime.healthy
    assert runtime.last_error is None


async def test_queue_depth_counts_in_flight_and_queued_calls(tmp_path):
    runtime, fake = make_runtime(tmp_path)
    assert runtime.queue_depth == 0
    fake.block_seconds = 0.05

    first = asyncio.create_task(runtime.generate("one"))
    await asyncio.sleep(0.01)  # first is in flight
    second = asyncio.create_task(runtime.generate("two"))
    await asyncio.sleep(0.01)  # second queued behind it
    assert runtime.queue_depth == 2

    await asyncio.gather(first, second)
    assert runtime.queue_depth == 0


# -- HTTP surface -------------------------------------------------------------


def make_client(runtime) -> AsyncClient:
    """App without lifespan; the runtime is injected directly."""
    app = create_app()
    app.state.llm_runtime = runtime
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def test_readiness_reports_model_state(tmp_path):
    # Model loaded, but no database engine: readiness must still answer (503)
    # and carry the model field. Dispose any engine a previous test left.
    await db.dispose_engine()
    runtime, _ = make_runtime(tmp_path)
    async with make_client(runtime) as client:
        resp = await client.get("/api/health/ready")
    assert resp.status_code == 503  # database unreachable in tests
    body = resp.json()
    assert body["model"] == "model.gguf"
    assert body["database"] == "unreachable"

    # No runtime at all -> reported as not loaded.
    app = create_app()
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        resp = await client.get("/api/health/ready")
    assert resp.status_code == 503
    assert resp.json()["model"] == "not_loaded"


async def test_health_liveness_answers_while_generation_runs(tmp_path):
    runtime, fake = make_runtime(tmp_path)
    fake.block_seconds = 0.2
    app = make_app(FakeAuditService(), runtime)
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        generation = asyncio.create_task(
            client.post("/api/prompt", json={"text": "busy"})
        )
        await asyncio.sleep(0.02)  # generation is now in flight
        started = time.perf_counter()
        health = await client.get("/api/health")
        elapsed = time.perf_counter() - started
        assert health.status_code == 200
        assert elapsed < 0.15  # answered while inference still blocking
        gen_resp = await generation
    assert gen_resp.status_code == 200
    assert gen_resp.json()["response_text"] == "echo: busy"
