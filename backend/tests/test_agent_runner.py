"""Tests for background agents (Step 14): the lifecycle contract, the
AgentRunner (spawn/execute/cancel/shutdown, with every transition mirrored to
live state and audit), the research agent subgraph, and the main graph's
agent-spawn detour."""

import asyncio

import pytest

from app.orchestration.agents.base import (
    AgentContext,
    AgentResult,
    AgentSpec,
    BackgroundAgent,
)
from app.orchestration.agents.research import parse_sub_questions
from app.orchestration.graph import build_main_graph
from app.orchestration.runner import AgentRunner
from app.state.store import StateStore, StoreEvent
from tests.fakes import FakeAuditService, make_runtime


async def wait_until(predicate, timeout: float = 2.0) -> None:
    """Poll until ``predicate()`` is true (background work has no handle to
    await, by design — spawning is fire-and-forget)."""
    async with asyncio.timeout(timeout):
        while not predicate():
            await asyncio.sleep(0.005)


def scripted(kind: str, run_fn) -> type[BackgroundAgent]:
    """An agent class whose ``run`` delegates to ``run_fn(context)``."""

    class _Scripted(BackgroundAgent):
        async def run(self, context: AgentContext) -> AgentResult:
            return await run_fn(context)

    _Scripted.kind = kind
    return _Scripted


def make_runner(tmp_path, run_fn=None, *, kind="scripted", **kwargs):
    """A started runner over fakes; returns (runner, store, audit, fake_llama)."""
    runtime, fake = make_runtime(tmp_path)
    store = StateStore()
    audit = FakeAuditService()
    agent_types = None if run_fn is None else {kind: scripted(kind, run_fn)}
    runner = AgentRunner(
        runtime=runtime, store=store, audit=audit, agent_types=agent_types, **kwargs
    )
    runner.start()
    return runner, store, audit, fake


# -- lifecycle ------------------------------------------------------------------


async def test_agent_runs_through_the_full_lifecycle(tmp_path):
    async def work(context: AgentContext) -> AgentResult:
        await context.report_progress("step-one", fraction=0.25)
        await context.report_progress("step-two", fraction=0.75, detail="almost")
        return AgentResult(summary="all done", payload={"answer": 42})

    runner, store, audit, _ = make_runner(tmp_path, work)
    agent_updates: list[str] = []
    store.set_notify(
        lambda e: agent_updates.append(e.snapshot.state)
        if e.kind == "agent_updated"
        else None
    )
    spec = AgentSpec(
        kind="scripted", task="do the thing", request_id="req-1", session_id="s-1"
    )

    agent_id = await runner.spawn(spec)

    assert agent_id == spec.agent_id
    # Registered pending immediately, with the task queued.
    snapshot = store.get_agent(agent_id)
    assert snapshot.state == "pending"
    assert snapshot.kind == "scripted"
    assert snapshot.request_id == "req-1"
    assert snapshot.session_id == "s-1"
    assert [t.description for t in snapshot.queued_tasks] == ["do the thing"]

    await wait_until(lambda: store.get_agent(agent_id).state == "completed")
    done = store.get_agent(agent_id)
    assert done.last_result == "all done"
    assert done.progress_fraction == 1.0
    assert done.progress_phase == "step-two"
    assert done.error is None
    assert done.queued_tasks == ()

    # Every transition and progress update reached the store's notify hook
    # (the Step 13 agent_updated stream) ...
    assert agent_updates == ["pending", "running", "running", "running", "completed"]
    # ... and the audit trail holds the full ordered lifecycle.
    events = audit.events_for(agent_id)
    assert [e["event_type"] for e in events] == [
        "spawned",
        "started",
        "progress",
        "progress",
        "completed",
    ]
    assert events[0]["state"] == "pending"
    assert events[0]["payload"]["task"] == "do the thing"
    assert events[2]["payload"] == {
        "phase": "step-one",
        "fraction": 0.25,
        "detail": None,
    }
    assert events[3]["payload"]["detail"] == "almost"
    assert events[4]["payload"] == {
        "summary": "all done",
        "result": {"answer": 42},
    }
    assert all(e["request_id"] == "req-1" for e in events)
    await runner.close()


async def test_failing_agent_lands_failed_and_never_disturbs_the_runner(tmp_path):
    calls = []

    async def work(context: AgentContext) -> AgentResult:
        calls.append(context.spec.agent_id)
        if len(calls) == 1:
            raise RuntimeError("boom")
        return AgentResult(summary="second is fine")

    runner, store, audit, _ = make_runner(tmp_path, work)
    first = await runner.spawn(AgentSpec(kind="scripted", task="fails"))
    second = await runner.spawn(AgentSpec(kind="scripted", task="succeeds"))

    await wait_until(lambda: store.get_agent(second).state == "completed")
    failed = store.get_agent(first)
    assert failed.state == "failed"
    assert failed.error == "RuntimeError: boom"
    assert failed.last_result is None
    assert [e["event_type"] for e in audit.events_for(first)] == [
        "spawned",
        "started",
        "failed",
    ]
    assert audit.events_for(first)[-1]["payload"] == {"error": "RuntimeError: boom"}
    # The same worker went on to complete the next agent.
    assert store.get_agent(second).last_result == "second is fine"
    await runner.close()


async def test_unknown_kind_is_rejected_before_registering(tmp_path):
    runner, store, audit, _ = make_runner(tmp_path)
    spec = AgentSpec(kind="nope", task="t")
    with pytest.raises(ValueError, match="unknown agent kind"):
        await runner.spawn(spec)
    assert store.get_agent(spec.agent_id) is None
    assert audit.agent_events == []
    await runner.close()


# -- cancellation ------------------------------------------------------------------


async def test_cancel_running_agent_settles_and_audits_cancelled(tmp_path):
    release = asyncio.Event()

    async def work(context: AgentContext) -> AgentResult:
        await context.report_progress("working", fraction=0.1)
        await release.wait()  # blocks until cancelled
        return AgentResult(summary="never reached")

    runner, store, audit, _ = make_runner(tmp_path, work)
    agent_id = await runner.spawn(AgentSpec(kind="scripted", task="long"))
    await wait_until(
        lambda: (s := store.get_agent(agent_id)) and s.progress_phase == "working"
    )

    assert await runner.cancel(agent_id) is True
    await wait_until(lambda: store.get_agent(agent_id).state == "cancelled")
    assert [e["event_type"] for e in audit.events_for(agent_id)] == [
        "spawned",
        "started",
        "progress",
        "cancelled",
    ]
    assert audit.events_for(agent_id)[-1]["payload"] == {
        "reason": "cancelled while running"
    }
    # A settled agent is no longer cancellable.
    assert await runner.cancel(agent_id) is False
    await runner.close()


async def test_cancel_pending_agent_is_settled_and_skipped_by_the_worker(tmp_path):
    release = asyncio.Event()

    async def work(context: AgentContext) -> AgentResult:
        await release.wait()
        return AgentResult(summary="ran")

    runner, store, audit, _ = make_runner(tmp_path, work)  # one worker
    blocker = await runner.spawn(AgentSpec(kind="scripted", task="blocks"))
    await wait_until(lambda: store.get_agent(blocker).state == "running")
    pending = await runner.spawn(AgentSpec(kind="scripted", task="waits"))

    assert await runner.cancel(pending) is True
    assert store.get_agent(pending).state == "cancelled"
    assert [e["event_type"] for e in audit.events_for(pending)] == [
        "spawned",
        "cancelled",
    ]

    release.set()  # the worker moves on; the cancelled spec is skipped
    await wait_until(lambda: store.get_agent(blocker).state == "completed")
    assert [e["event_type"] for e in audit.events_for(pending)] == [
        "spawned",
        "cancelled",
    ]
    await runner.close()


async def test_close_cancels_running_and_pending_agents_gracefully(tmp_path):
    release = asyncio.Event()

    async def work(context: AgentContext) -> AgentResult:
        await release.wait()
        return AgentResult(summary="ran")

    runner, store, audit, _ = make_runner(tmp_path, work)
    running = await runner.spawn(AgentSpec(kind="scripted", task="in flight"))
    await wait_until(lambda: store.get_agent(running).state == "running")
    queued = await runner.spawn(AgentSpec(kind="scripted", task="still queued"))

    await runner.close()

    assert store.get_agent(running).state == "cancelled"
    assert store.get_agent(queued).state == "cancelled"
    assert audit.events_for(running)[-1]["payload"] == {
        "reason": "cancelled while running"
    }
    assert audit.events_for(queued)[-1]["payload"] == {
        "reason": "service shutdown before start"
    }
    with pytest.raises(RuntimeError, match="shut down"):
        await runner.spawn(AgentSpec(kind="scripted", task="too late"))
    await runner.close()  # idempotent


# -- the research agent -------------------------------------------------------------


async def test_research_agent_decomposes_investigates_and_summarizes(tmp_path):
    runtime, fake = make_runtime(tmp_path)
    store = StateStore()
    audit = FakeAuditService()
    runner = AgentRunner(runtime=runtime, store=store, audit=audit)
    runner.start()
    fake.queued_responses = [
        "1. What is X?\n2. How does Y relate?",
        "X is a thing.",
        "Y depends on X.",
        "In summary, X drives Y.",
    ]

    agent_id = await runner.spawn(
        AgentSpec(kind="research", task="explain X and Y", request_id="req-9")
    )

    await wait_until(lambda: store.get_agent(agent_id).state == "completed")
    done = store.get_agent(agent_id)
    assert done.last_result == "In summary, X drives Y."
    # Four background LLM calls: decompose, two investigations, summarize.
    assert len(fake.calls) == 4
    completed = audit.events_for(agent_id)[-1]
    assert completed["payload"]["result"]["questions"] == [
        "What is X?",
        "How does Y relate?",
    ]
    assert completed["payload"]["result"]["findings"] == [
        {"question": "What is X?", "answer": "X is a thing."},
        {"question": "How does Y relate?", "answer": "Y depends on X."},
    ]
    # Multi-step progress: one report per phase, one per sub-question.
    progress = [
        e["payload"]["phase"]
        for e in audit.events_for(agent_id)
        if e["event_type"] == "progress"
    ]
    assert progress == [
        "decomposing",
        "investigating",
        "investigating",
        "summarizing",
    ]
    await runner.close()


def test_parse_sub_questions_handles_markers_limit_and_noise():
    text = "Here you go:\n1. First?\n2) Second?\n- Third?\nnot a list line"
    assert parse_sub_questions(text, limit=5) == ["First?", "Second?", "Third?"]
    assert parse_sub_questions(text, limit=2) == ["First?", "Second?"]
    assert parse_sub_questions("no list at all", limit=3) == []


# -- main graph wiring ---------------------------------------------------------------


def make_graph_state(**overrides) -> dict:
    from app.governance.policy import GovernanceMetadata

    state = {
        "request_id": "req-1",
        "session_id": "sess-1",
        "reviewed_prompt": "research this topic",
        "governance": GovernanceMetadata(
            decision="allowed",
            tags=(),
            directives=(),
            rationale=(),
            matched_rules=(),
            strict_mode=False,
        ),
        "decisions": [],
    }
    state.update(overrides)
    return state


_REVIEW_WANTS_AGENT = (
    '{"intent": "task", "needs_background_work": true, "concerns": []}'
)
_REVIEW_DIRECT = (
    '{"intent": "question", "needs_background_work": false, "concerns": []}'
)


async def test_graph_detours_through_agent_spawn_and_mentions_the_agent(tmp_path):
    runtime, fake = make_runtime(tmp_path)
    store = StateStore()
    audit = FakeAuditService()
    runner = AgentRunner(runtime=runtime, store=store, audit=audit)
    # Deliberately not started: spawn only enqueues, proving respond never
    # waits on agent execution.
    fake.queued_responses = [_REVIEW_WANTS_AGENT]
    await store.start_run("req-1", "sess-1")
    graph = build_main_graph(runtime, store, runner)

    state = await graph.ainvoke(make_graph_state())

    agent_id = state["spawned_agent_id"]
    assert agent_id in state["final_output"]  # the answer names the agent
    assert agent_id not in state["draft_output"]
    assert [d["node"] for d in state["decisions"]] == [
        "prompt_engineering",
        "llm_review",
        "agent_spawn",
        "respond",
    ]
    spawn_decision = state["decisions"][2]
    assert spawn_decision["outcome"] == "spawned"
    assert spawn_decision["agent_id"] == agent_id
    assert spawn_decision["kind"] == "research"
    # The run's phase history shows the detour.
    assert [p.phase for p in store.get_run("req-1").phases] == [
        "received",
        "engineering",
        "reviewing",
        "spawning",
        "responding",
    ]
    # The agent is registered (pending — no worker running) and audited.
    assert store.get_agent(agent_id).state == "pending"
    assert store.get_agent(agent_id).request_id == "req-1"
    assert [e["event_type"] for e in audit.events_for(agent_id)] == ["spawned"]
    # Exactly two foreground LLM calls: review and respond — no agent work.
    assert len(fake.calls) == 2


async def test_graph_goes_straight_to_respond_when_no_background_work(tmp_path):
    runtime, fake = make_runtime(tmp_path)
    store = StateStore()
    runner = AgentRunner(
        runtime=runtime, store=store, audit=FakeAuditService()
    )
    fake.queued_responses = [_REVIEW_DIRECT]
    graph = build_main_graph(runtime, store, runner)

    state = await graph.ainvoke(make_graph_state())

    assert "spawned_agent_id" not in state
    assert state["final_output"] == state["draft_output"]
    assert [d["node"] for d in state["decisions"]] == [
        "prompt_engineering",
        "llm_review",
        "respond",
    ]
    assert store.list_agents() == ()


async def test_spawn_failure_is_non_fatal_and_recorded(tmp_path):
    runtime, fake = make_runtime(tmp_path)
    store = StateStore()
    # A runner with no registered kinds makes every spawn fail.
    runner = AgentRunner(
        runtime=runtime, store=store, audit=FakeAuditService(), agent_types={}
    )
    fake.queued_responses = [_REVIEW_WANTS_AGENT]
    graph = build_main_graph(runtime, store, runner)

    state = await graph.ainvoke(make_graph_state())

    assert "spawned_agent_id" not in state
    assert state["final_output"] == state["draft_output"]  # no agent mention
    spawn_decision = next(
        d for d in state["decisions"] if d["node"] == "agent_spawn"
    )
    assert spawn_decision["outcome"] == "spawn_failed"
    assert "unknown agent kind" in spawn_decision["error"]


async def test_graph_without_a_runner_never_detours(tmp_path):
    runtime, fake = make_runtime(tmp_path)
    fake.queued_responses = [_REVIEW_WANTS_AGENT]
    graph = build_main_graph(runtime)  # no runner bound

    state = await graph.ainvoke(make_graph_state())

    assert "spawned_agent_id" not in state
    assert [d["node"] for d in state["decisions"]] == [
        "prompt_engineering",
        "llm_review",
        "respond",
    ]
