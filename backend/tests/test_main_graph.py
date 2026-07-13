"""Tests for the LangGraph main graph and its nodes (Step 9).

Each node runs as a pure function against a fake LLM runtime and a
hand-built state; a final set exercises the assembled graph end to end.
"""

import pytest

from app.governance.policy import GovernanceMetadata
from app.orchestration.graph import build_main_graph
from app.orchestration.nodes.llm_review import (
    parse_review_verdict,
    review_engineered_prompt,
)
from app.orchestration.nodes.prompt_engineering import engineer_prompt
from app.orchestration.nodes.respond import synthesize_response
from app.state.store import StateStore
from tests.fakes import make_runtime


def make_governance(**overrides) -> GovernanceMetadata:
    defaults = dict(
        decision="allowed",
        tags=(),
        directives=(),
        rationale=(),
        matched_rules=(),
        strict_mode=False,
    )
    return GovernanceMetadata(**{**defaults, **overrides})


def make_state(**overrides) -> dict:
    state = {
        "request_id": "req-1",
        "session_id": "sess-1",
        "reviewed_prompt": "hello world",
        "governance": make_governance(),
        "decisions": [],
    }
    state.update(overrides)
    return state


# -- prompt_engineering --------------------------------------------------------


def test_engineer_prompt_fills_template_and_applies_directives():
    state = make_state(
        governance=make_governance(
            directives=("Directive one.", "Directive two.")
        )
    )
    update = engineer_prompt(state)

    assert update["engineered_prompt"] == "hello world"
    assert "LunaBlue" in update["engineered_system"]  # llm/prompts/system.md
    assert "Directive one." in update["engineered_system"]
    assert "Directive two." in update["engineered_system"]

    [decision] = update["decisions"]
    assert decision["node"] == "prompt_engineering"
    assert decision["template"] == "system"
    assert decision["directives_applied"] == ["Directive one.", "Directive two."]
    assert decision["summary"]
    assert decision["duration_ms"] >= 0


def test_engineer_prompt_without_directives_uses_bare_template():
    update = engineer_prompt(make_state())
    assert "governance directives" not in update["engineered_system"]
    assert update["decisions"][0]["directives_applied"] == []


# -- llm_review ----------------------------------------------------------------


async def test_review_node_parses_model_verdict(tmp_path):
    runtime, fake = make_runtime(tmp_path)
    fake.queued_responses = [
        '{"intent": "coding", "needs_background_work": true,'
        ' "concerns": ["ambiguous scope"]}'
    ]
    state = make_state(engineered_prompt="write a parser")

    update = await review_engineered_prompt(state, llm_runtime=runtime)

    assert update["review"] == {
        "intent": "coding",
        "needs_background_work": True,
        "concerns": ["ambiguous scope"],
        "parsed": True,
    }
    [decision] = update["decisions"]
    assert decision["node"] == "llm_review"
    assert decision["outcome"] == update["review"]
    assert decision["model_id"] == "model.gguf"
    assert decision["usage"]["total_tokens"] == 10
    assert decision["duration_ms"] >= 0

    # The review instructions (llm/prompts/review.md) and the engineered
    # prompt go out together in the user turn (small local models ignore
    # system-role review instructions).
    [call] = fake.calls
    [message] = call["messages"]
    assert message["role"] == "user"
    assert "JSON" in message["content"]
    assert "write a parser" in message["content"]
    # Review is deterministic and bounded.
    assert call["temperature"] == 0.0
    assert call["max_tokens"] == 256


async def test_review_node_degrades_gracefully_on_unparseable_output(tmp_path):
    runtime, fake = make_runtime(tmp_path)
    # A model that answers the prompt instead of reviewing it.
    fake.queued_responses = ["The answer is 42."]
    update = await review_engineered_prompt(
        make_state(engineered_prompt="hi"), llm_runtime=runtime
    )
    review = update["review"]
    assert review["parsed"] is False
    assert review["intent"] == "unknown"
    assert review["needs_background_work"] is False
    assert review["raw_output"] == "The answer is 42."


def test_parse_review_verdict_tolerates_surrounding_prose_and_bad_types():
    verdict = parse_review_verdict(
        'Sure! Here is my assessment:\n{"intent": "question",'
        ' "needs_background_work": "yes", "concerns": "none"}\nHope it helps.'
    )
    assert verdict["parsed"] is True
    assert verdict["intent"] == "question"
    assert verdict["needs_background_work"] is True  # truthy string coerced
    assert verdict["concerns"] == []  # non-list dropped


# -- respond -------------------------------------------------------------------


async def test_respond_node_sets_draft_and_final_output(tmp_path):
    runtime, fake = make_runtime(tmp_path)
    state = make_state(
        engineered_prompt="hello world", engineered_system="be terse"
    )
    update = await synthesize_response(state, llm_runtime=runtime)

    assert update["draft_output"] == "echo: hello world"
    assert update["final_output"] == "echo: hello world"
    assert update["model_id"] == "model.gguf"
    assert update["usage"]["total_tokens"] == 10

    [decision] = update["decisions"]
    assert decision["node"] == "respond"
    assert decision["finish_reason"] == "stop"
    assert decision["duration_ms"] >= 0

    # The engineered system prompt is what reaches the model.
    [call] = fake.calls
    assert call["messages"][0] == {"role": "system", "content": "be terse"}


# -- the assembled graph -------------------------------------------------------


async def test_graph_runs_all_nodes_and_accumulates_decisions(tmp_path):
    runtime, fake = make_runtime(tmp_path)
    fake.queued_responses = [
        '{"intent": "conversation", "needs_background_work": false, "concerns": []}'
    ]
    graph = build_main_graph(runtime)

    state = await graph.ainvoke(make_state())

    assert state["final_output"] == "echo: hello world"
    assert state["draft_output"] == state["final_output"]
    assert state["review"]["intent"] == "conversation"
    # One decision record per node, in execution order, each timed.
    assert [d["node"] for d in state["decisions"]] == [
        "prompt_engineering",
        "llm_review",
        "respond",
    ]
    assert all(d["duration_ms"] >= 0 for d in state["decisions"])
    # Two LLM calls: review then respond.
    assert len(fake.calls) == 2


async def test_generation_failure_inside_a_node_propagates(tmp_path):
    runtime, fake = make_runtime(tmp_path)
    fake.fail_with = RuntimeError("kaboom")
    graph = build_main_graph(runtime)
    with pytest.raises(RuntimeError, match="kaboom"):
        await graph.ainvoke(make_state())


# -- Step 10: store instrumentation ---------------------------------------------


async def test_graph_with_store_advances_run_phases(tmp_path):
    runtime, fake = make_runtime(tmp_path)
    fake.queued_responses = [
        '{"intent": "conversation", "needs_background_work": false, "concerns": []}'
    ]
    store = StateStore(max_finished_runs=8)
    await store.start_run("req-1", "sess-1")
    graph = build_main_graph(runtime, store)

    state = await graph.ainvoke(make_state())

    assert state["final_output"] == "echo: hello world"
    run = store.get_run("req-1")
    # Entering each node advanced the phase; the pipeline (not the graph)
    # owns the terminal transition, so the run ends on the last node's phase.
    assert [p.phase for p in run.phases] == [
        "received",
        "engineering",
        "reviewing",
        "responding",
    ]
    assert run.phase == "responding"
    assert run.current_node == "respond"


async def test_graph_without_a_started_run_is_untracked_but_runs(tmp_path):
    """A store-instrumented graph tolerates unknown runs (e.g. evicted)."""
    runtime, fake = make_runtime(tmp_path)
    fake.queued_responses = ['{"intent": "conversation"}']
    store = StateStore(max_finished_runs=8)
    graph = build_main_graph(runtime, store)

    state = await graph.ainvoke(make_state())

    assert state["final_output"] == "echo: hello world"
    assert store.get_run("req-1") is None
