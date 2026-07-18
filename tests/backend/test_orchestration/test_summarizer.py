"""Tests for the SessionSummarizer (closed-loop prompt processing).

The summarizer is fire-and-forget; tests synchronize via ``wait_idle()``.
"""

from app.orchestration.summarizer import SessionSummarizer
from app.state.store import StateStore
from tests.backend.fakes import make_runtime


def make_summarizer(tmp_path, **kwargs):
    runtime, fake = make_runtime(tmp_path)
    store = StateStore(max_finished_runs=8)
    summarizer = SessionSummarizer(runtime=runtime, store=store, **kwargs)
    return summarizer, store, fake


async def test_scheduled_update_stores_the_new_summary(tmp_path):
    summarizer, store, fake = make_summarizer(tmp_path)
    fake.queued_responses = ["User greeted the assistant."]

    summarizer.schedule("sess-1", user_prompt="hello", response_text="hi there")
    await summarizer.wait_idle()

    assert store.get_session_summary("sess-1") == "User greeted the assistant."
    # The summarize instructions with the numeric cap substituted, plus the
    # turn's raw prompt and response excerpt, go out in one user-turn call.
    [call] = fake.calls
    [message] = call["messages"]
    assert message["role"] == "user"
    assert "conversation-memory stage" in message["content"]
    assert "at most 2000" in message["content"]  # cap substituted in
    assert "(none)" in message["content"]  # no prior summary yet
    assert "hello" in message["content"]
    assert "hi there" in message["content"]
    assert call["temperature"] == 0.2
    assert call["max_tokens"] == 600


async def test_next_update_sees_the_previous_summary(tmp_path):
    summarizer, store, fake = make_summarizer(tmp_path)
    fake.queued_responses = ["first summary", "second summary"]

    summarizer.schedule("sess-1", user_prompt="one", response_text="r1")
    await summarizer.wait_idle()
    summarizer.schedule("sess-1", user_prompt="two", response_text="r2")
    await summarizer.wait_idle()

    assert store.get_session_summary("sess-1") == "second summary"
    assert "first summary" in fake.calls[1]["messages"][0]["content"]


async def test_overlong_output_is_hard_capped(tmp_path):
    summarizer, store, fake = make_summarizer(tmp_path, max_chars=50)
    fake.queued_responses = ["x" * 400]

    summarizer.schedule("sess-1", user_prompt="p", response_text="r")
    await summarizer.wait_idle()

    stored = store.get_session_summary("sess-1")
    assert len(stored) == 50
    assert stored.endswith("…")


async def test_failed_update_keeps_the_previous_summary(tmp_path):
    summarizer, store, fake = make_summarizer(tmp_path)
    await store.set_session_summary("sess-1", "previous summary")
    fake.fail_once = RuntimeError("kaboom")

    summarizer.schedule("sess-1", user_prompt="p", response_text="r")
    await summarizer.wait_idle()  # nothing escapes

    assert store.get_session_summary("sess-1") == "previous summary"


async def test_empty_output_keeps_the_previous_summary(tmp_path):
    summarizer, store, fake = make_summarizer(tmp_path)
    await store.set_session_summary("sess-1", "previous summary")
    fake.queued_responses = ["   "]

    summarizer.schedule("sess-1", user_prompt="p", response_text="r")
    await summarizer.wait_idle()

    assert store.get_session_summary("sess-1") == "previous summary"


async def test_same_session_updates_apply_in_submission_order(tmp_path):
    summarizer, store, fake = make_summarizer(tmp_path)
    fake.queued_responses = ["first", "second"]

    # Scheduled back to back without waiting: the second chains on the first.
    summarizer.schedule("sess-1", user_prompt="one", response_text="r1")
    summarizer.schedule("sess-1", user_prompt="two", response_text="r2")
    await summarizer.wait_idle()

    assert store.get_session_summary("sess-1") == "second"
    assert len(fake.calls) == 2


async def test_reset_invalidates_an_in_flight_update(tmp_path):
    """A summarize scheduled before a reset must not resurrect the cleared
    summary (Step 20 epoch guard)."""
    summarizer, store, fake = make_summarizer(tmp_path)
    fake.queued_responses = ["stale summary"]

    # No intervening await: the scheduled task has not run when reset lands.
    summarizer.schedule("sess-1", user_prompt="p", response_text="r")
    await summarizer.reset("sess-1")
    await summarizer.wait_idle()

    assert store.get_session_summary("sess-1") is None


async def test_schedule_after_reset_writes_normally(tmp_path):
    summarizer, store, fake = make_summarizer(tmp_path)
    await store.set_session_summary("sess-1", "old context")
    fake.queued_responses = ["fresh summary"]

    await summarizer.reset("sess-1")
    summarizer.schedule("sess-1", user_prompt="p", response_text="r")
    await summarizer.wait_idle()

    assert store.get_session_summary("sess-1") == "fresh summary"


async def test_reset_on_a_never_seen_session_is_safe(tmp_path):
    summarizer, store, _ = make_summarizer(tmp_path)
    await summarizer.reset("sess-unknown")  # must not raise
    assert store.get_session_summary("sess-unknown") is None


async def test_reset_only_affects_its_own_session(tmp_path):
    summarizer, store, fake = make_summarizer(tmp_path)
    fake.queued_responses = ["other session summary"]

    summarizer.schedule("sess-other", user_prompt="p", response_text="r")
    await summarizer.reset("sess-1")
    await summarizer.wait_idle()

    assert store.get_session_summary("sess-other") == "other session summary"


async def test_aclose_stops_new_work_and_settles_pending(tmp_path):
    summarizer, store, fake = make_summarizer(tmp_path)
    fake.queued_responses = ["never applied?"]

    summarizer.schedule("sess-1", user_prompt="p", response_text="r")
    await summarizer.aclose()  # must not hang or raise

    # Closed: further schedules are no-ops.
    summarizer.schedule("sess-2", user_prompt="p", response_text="r")
    await summarizer.wait_idle()
    assert store.get_session_summary("sess-2") is None
