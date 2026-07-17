"""End-to-end tests for closed-loop prompt processing.

Two-turn conversations through POST /api/prompt with the session summary
enabled (fakes opt in via ``make_client(summary=True)``): turn 1's response
feeds a background summary update; turn 2 sees the summary injected under
``### Chat Summary``. Plus leak checks — the enhanced prompt and the summary
must never appear in any wire payload — and toggle-off parity with the
original three-node flow.
"""

import pytest

from app.state.identity import IdentityStore
from tests.backend.fakes import FakeAuditService, make_client, make_runtime

_REVIEW_DIRECT = (
    '{"intent": "conversation", "needs_background_work": false, "concerns": []}'
)


@pytest.fixture
def audit():
    return FakeAuditService()


@pytest.fixture
def runtime_and_fake(tmp_path):
    return make_runtime(tmp_path)


async def test_second_turn_receives_the_rolling_summary(audit, runtime_and_fake):
    runtime, fake = runtime_and_fake
    async with make_client(audit, runtime, summary=True) as client:
        summarizer = client.app.state.session_summarizer

        # Turn 1: enhance, review, respond (foreground), then the background
        # summarize call — four pops, in call order.
        fake.queued_responses = [
            "enhanced one",
            _REVIEW_DIRECT,
            "response one",
            "TURN1-SUMMARY",
        ]
        first = await client.post(
            "/api/prompt", json={"text": "turn one raw", "session_id": "s-loop"}
        )
        assert first.status_code == 200
        assert first.json()["response_text"] == "response one"
        await summarizer.wait_idle()

        # The summarize call saw the RAW user prompt, not the enhanced form.
        summarize_call = fake.calls[3]
        assert "turn one raw" in summarize_call["messages"][0]["content"]
        assert "enhanced one" not in summarize_call["messages"][0]["content"]
        assert "response one" in summarize_call["messages"][0]["content"]

        # Turn 2, same session: the stored summary rides along.
        fake.queued_responses = [
            "enhanced two",
            _REVIEW_DIRECT,
            "response two",
            "TURN2-SUMMARY",
        ]
        second = await client.post(
            "/api/prompt", json={"text": "turn two raw", "session_id": "s-loop"}
        )
        assert second.status_code == 200
        assert second.json()["response_text"] == "response two"
        await summarizer.wait_idle()

        enhance_two, review_two, respond_two = fake.calls[4:7]
        # The enhancer never sees the summary block ...
        assert "### Chat Summary" not in enhance_two["messages"][0]["content"]
        assert "TURN1-SUMMARY" not in enhance_two["messages"][0]["content"]
        # ... review and respond both consume the enhanced prompt + summary.
        assert "### Chat Summary" in review_two["messages"][0]["content"]
        assert "TURN1-SUMMARY" in review_two["messages"][0]["content"]
        user_turn = next(
            m for m in respond_two["messages"] if m["role"] == "user"
        )
        assert user_turn["content"] == (
            "enhanced two\n\n### Chat Summary\nTURN1-SUMMARY"
        )

        # The enhancement decision records the injection (audit trail).
        decisions = audit.prompt_responses[-1]["usage"]["decisions"]
        enhancement = next(
            d for d in decisions if d["node"] == "prompt_enhancement"
        )
        assert enhancement["status"] == "enhanced"
        assert enhancement["summary_injected"] is True

        # Leak checks: neither response body nor the session endpoint ever
        # carries the summary or the enhanced prompt.
        for resp in (first, second):
            assert "Chat Summary" not in resp.text
            assert "enhanced" not in resp.json()["response_text"]
        session = await client.get("/api/sessions/s-loop")
        assert session.status_code == 200
        assert "TURN1-SUMMARY" not in session.text
        assert "TURN2-SUMMARY" not in session.text
        assert "summary" not in session.json()


async def test_summary_survives_a_failed_update_and_stays_internal(
    audit, runtime_and_fake
):
    runtime, fake = runtime_and_fake
    async with make_client(audit, runtime, summary=True) as client:
        summarizer = client.app.state.session_summarizer
        store = client.app.state.state_store

        fake.queued_responses = ["enhanced", _REVIEW_DIRECT, "response one"]
        fake.fail_once = None
        resp = await client.post(
            "/api/prompt", json={"text": "raw", "session_id": "s-fail"}
        )
        assert resp.status_code == 200
        # Fail the (only remaining) summarize call: old summary retained.
        fake.fail_once = RuntimeError("summarize kaboom")
        await summarizer.wait_idle()
        assert store.get_session_summary("s-fail") is None


async def test_both_toggles_off_restore_the_original_flow(audit, runtime_and_fake):
    runtime, fake = runtime_and_fake
    async with make_client(
        audit, runtime, enhancement=False, summary=False
    ) as client:
        resp = await client.post("/api/prompt", json={"text": "hello"})
        assert resp.status_code == 200
        assert resp.json()["response_text"] == "echo: hello"

    # Exactly two LLM calls and the original three-node decision list.
    assert len(fake.calls) == 2
    decisions = audit.prompt_responses[-1]["usage"]["decisions"]
    assert [d["node"] for d in decisions] == [
        "prompt_engineering",
        "llm_review",
        "respond",
    ]


async def test_summary_only_mode_injects_without_an_enhancement_call(
    audit, runtime_and_fake
):
    runtime, fake = runtime_and_fake
    async with make_client(
        audit, runtime, enhancement=False, summary=True
    ) as client:
        summarizer = client.app.state.session_summarizer

        # Turn 1: review, respond, then summarize — no enhancement call.
        fake.queued_responses = [_REVIEW_DIRECT, "response one", "TURN1-SUMMARY"]
        first = await client.post(
            "/api/prompt", json={"text": "turn one", "session_id": "s-hybrid"}
        )
        assert first.status_code == 200
        await summarizer.wait_idle()
        assert len(fake.calls) == 3

        fake.queued_responses = [_REVIEW_DIRECT, "response two", "TURN2-SUMMARY"]
        second = await client.post(
            "/api/prompt", json={"text": "turn two", "session_id": "s-hybrid"}
        )
        assert second.status_code == 200
        await summarizer.wait_idle()

        # The node ran deterministically: summary appended to the reviewed
        # prompt, decision recorded as disabled.
        respond_two = fake.calls[4]
        user_turn = next(
            m for m in respond_two["messages"] if m["role"] == "user"
        )
        assert user_turn["content"] == (
            "turn two\n\n### Chat Summary\nTURN1-SUMMARY"
        )
        decisions = audit.prompt_responses[-1]["usage"]["decisions"]
        enhancement = next(
            d for d in decisions if d["node"] == "prompt_enhancement"
        )
        assert enhancement["status"] == "disabled"
        assert enhancement["summary_injected"] is True


async def test_identity_is_pinned_and_survives_a_summary_reset(
    audit, runtime_and_fake
):
    """Step 20: identity fields ride every injected summary, and a reset
    clears only the rolling part — the next turn is identity-only again."""
    runtime, fake = runtime_and_fake
    identity = IdentityStore(name="Luna", age="7")
    async with make_client(
        audit, runtime, summary=True, identity=identity
    ) as client:
        summarizer = client.app.state.session_summarizer

        # Turn 1: no rolling summary yet — identity-only injection.
        fake.queued_responses = [
            "enhanced one",
            _REVIEW_DIRECT,
            "response one",
            "TURN1-SUMMARY",
        ]
        first = await client.post(
            "/api/prompt", json={"text": "turn one", "session_id": "s-id"}
        )
        assert first.status_code == 200
        await summarizer.wait_idle()
        respond_one = fake.calls[2]
        user_turn = next(
            m for m in respond_one["messages"] if m["role"] == "user"
        )
        assert user_turn["content"] == (
            "enhanced one\n\n### Chat Summary\nName: Luna\nAge: 7"
        )

        # Turn 2: identity block precedes the rolling summary.
        fake.queued_responses = [
            "enhanced two",
            _REVIEW_DIRECT,
            "response two",
            "TURN2-SUMMARY",
        ]
        second = await client.post(
            "/api/prompt", json={"text": "turn two", "session_id": "s-id"}
        )
        assert second.status_code == 200
        await summarizer.wait_idle()
        respond_two = fake.calls[6]
        user_turn = next(
            m for m in respond_two["messages"] if m["role"] == "user"
        )
        assert user_turn["content"] == (
            "enhanced two\n\n### Chat Summary\n"
            "Name: Luna\nAge: 7\n\nTURN1-SUMMARY"
        )

        # Reset: rolling context gone, identity untouched.
        reset = await client.post("/api/sessions/s-id/summary/reset")
        assert reset.status_code == 200
        assert reset.json() == {"session_id": "s-id", "cleared": True}

        # Turn 3: identity-only again — the outline's post-reset format.
        fake.queued_responses = [
            "enhanced three",
            _REVIEW_DIRECT,
            "response three",
            "TURN3-SUMMARY",
        ]
        third = await client.post(
            "/api/prompt", json={"text": "turn three", "session_id": "s-id"}
        )
        assert third.status_code == 200
        await summarizer.wait_idle()
        respond_three = fake.calls[10]
        user_turn = next(
            m for m in respond_three["messages"] if m["role"] == "user"
        )
        assert user_turn["content"] == (
            "enhanced three\n\n### Chat Summary\nName: Luna\nAge: 7"
        )
        assert "TURN1-SUMMARY" not in user_turn["content"]
        assert "TURN2-SUMMARY" not in user_turn["content"]

        # Identity values stay off the session status wire (they are only
        # served by /api/identity).
        session = await client.get("/api/sessions/s-id")
        assert "Luna" not in session.text


async def test_reset_endpoint_invalidates_in_flight_summary_updates(
    audit, runtime_and_fake
):
    """A reset issued while a background summarize is still pending must win:
    the pending update is discarded via the epoch guard."""
    runtime, fake = runtime_and_fake
    async with make_client(audit, runtime, summary=True) as client:
        summarizer = client.app.state.session_summarizer
        store = client.app.state.state_store

        fake.queued_responses = [
            "enhanced",
            _REVIEW_DIRECT,
            "response one",
            "STALE-SUMMARY",
        ]
        resp = await client.post(
            "/api/prompt", json={"text": "hello", "session_id": "s-race"}
        )
        assert resp.status_code == 200
        # Reset lands before the background summarize settles.
        reset = await client.post("/api/sessions/s-race/summary/reset")
        assert reset.json()["cleared"] is True
        await summarizer.wait_idle()

        assert store.get_session_summary("s-race") is None


async def test_openapi_schemas_never_document_a_summary_field(
    audit, runtime_and_fake
):
    """Structural never-leak guard: the session wire schemas must not grow a
    summary property."""
    async with make_client(audit, runtime_and_fake[0], summary=True) as client:
        spec = (await client.get("/openapi.json")).json()
    schemas = spec["components"]["schemas"]
    assert "summary" not in schemas["SessionStatus"]["properties"]
    if "SessionSummary" in schemas:  # WS payload schema, if exposed
        assert "summary" not in schemas["SessionSummary"]["properties"]
