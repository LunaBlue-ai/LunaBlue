"""Tests for the prompt_enhancement node (closed-loop prompt processing).

The node runs as a pure function against a fake LLM runtime and a hand-built
state, mirroring the other node tests in test_main_graph.py.
"""

from app.governance.policy import GovernanceMetadata
from app.orchestration.nodes.prompt_enhancement import enhance_prompt
from tests.backend.fakes import make_runtime


def make_state(**overrides) -> dict:
    state = {
        "request_id": "req-1",
        "session_id": "sess-1",
        "reviewed_prompt": "hello world",
        "governance": GovernanceMetadata(
            decision="allowed",
            tags=(),
            directives=(),
            rationale=(),
            matched_rules=(),
            strict_mode=False,
        ),
        "decisions": [],
        "engineered_prompt": "hello world",
    }
    state.update(overrides)
    return state


async def test_enhancement_rewrites_the_prompt_and_records_the_decision(tmp_path):
    runtime, fake = make_runtime(tmp_path)
    fake.queued_responses = ["Please greet the world clearly."]

    update = await enhance_prompt(make_state(), llm_runtime=runtime)

    assert update["engineered_prompt"] == "Please greet the world clearly."
    assert update["enhanced_prompt"] == update["engineered_prompt"]

    [decision] = update["decisions"]
    assert decision["node"] == "prompt_enhancement"
    assert decision["template"] == "enhance"
    assert decision["status"] == "enhanced"
    assert decision["error"] is None
    assert decision["enhanced_prompt"] == "Please greet the world clearly."
    assert decision["summary_injected"] is False
    assert decision["model_id"] == "model.gguf"
    assert decision["usage"]["total_tokens"] == 10
    assert decision["duration_ms"] >= 0

    # The enhance instructions (llm/prompts/enhance.md) and the prompt go
    # out together in the user turn (small local models ignore system-role
    # meta-task instructions), with bounded near-deterministic params.
    [call] = fake.calls
    [message] = call["messages"]
    assert message["role"] == "user"
    assert "prompt-enhancement stage" in message["content"]
    assert "hello world" in message["content"]
    assert call["temperature"] == 0.2
    assert call["max_tokens"] == 512


async def test_enhancement_failure_falls_back_to_the_original_prompt(tmp_path):
    runtime, fake = make_runtime(tmp_path)
    fake.fail_with = RuntimeError("kaboom")

    update = await enhance_prompt(make_state(), llm_runtime=runtime)

    # No raise, prompt unchanged, failure recorded in the decision log.
    assert update["engineered_prompt"] == "hello world"
    [decision] = update["decisions"]
    assert decision["status"] == "fallback"
    assert "kaboom" in decision["error"]
    assert decision["enhanced_prompt"] == "hello world"
    assert "usage" not in decision


async def test_empty_enhancement_output_falls_back(tmp_path):
    runtime, fake = make_runtime(tmp_path)
    fake.queued_responses = ["   \n"]

    update = await enhance_prompt(make_state(), llm_runtime=runtime)

    assert update["engineered_prompt"] == "hello world"
    [decision] = update["decisions"]
    assert decision["status"] == "fallback"
    assert decision["error"] == "empty enhancement output"


async def test_chat_summary_is_appended_after_the_llm_call(tmp_path):
    runtime, fake = make_runtime(tmp_path)
    fake.queued_responses = ["Greet the world."]
    state = make_state(chat_summary="user likes cats")

    update = await enhance_prompt(state, llm_runtime=runtime)

    assert update["engineered_prompt"] == (
        "Greet the world.\n\n### Chat Summary\nuser likes cats"
    )
    [decision] = update["decisions"]
    assert decision["summary_injected"] is True
    assert decision["chat_summary_chars"] == len("user likes cats")
    # The enhancement LLM call never sees the summary block.
    [call] = fake.calls
    assert "### Chat Summary" not in call["messages"][0]["content"]
    assert "user likes cats" not in call["messages"][0]["content"]


async def test_disabled_enhancement_still_injects_the_summary(tmp_path):
    runtime, fake = make_runtime(tmp_path)
    state = make_state(chat_summary="user likes cats")

    update = await enhance_prompt(state, llm_runtime=runtime, enabled=False)

    # Deterministic: no LLM call, just the summary append.
    assert fake.calls == []
    assert update["engineered_prompt"] == (
        "hello world\n\n### Chat Summary\nuser likes cats"
    )
    [decision] = update["decisions"]
    assert decision["status"] == "disabled"
    assert decision["template"] is None
    assert decision["summary_injected"] is True


async def test_max_tokens_override_reaches_the_call(tmp_path):
    runtime, fake = make_runtime(tmp_path)
    fake.queued_responses = ["ok"]

    await enhance_prompt(make_state(), llm_runtime=runtime, max_tokens=64)

    [call] = fake.calls
    assert call["max_tokens"] == 64
