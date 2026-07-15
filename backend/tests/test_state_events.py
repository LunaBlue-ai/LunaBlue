"""Tests for the EventBus (Step 13): stamping, fan-out, slow-consumer
drop-oldest, and unsubscribe — driven through a real StateStore attached via
the Step 10 notify hook."""

import logging
from datetime import timezone

import pytest

from app.state.events import EventBus
from app.state.store import RunSnapshot, SessionSnapshot, StateStore


async def test_store_mutations_publish_stamped_events_to_all_subscribers():
    bus = EventBus()
    store = StateStore(notify=bus.publish)
    sub_a = bus.subscribe()
    sub_b = bus.subscribe()

    await store.start_run("r1", "s1", user_id="u1")  # run_updated + session_updated
    await store.update_run_phase("r1", "governance")

    events_a = [await anext(sub_a) for _ in range(3)]
    events_b = [await anext(sub_b) for _ in range(3)]

    # Both subscribers see the same events, in publication order.
    assert [e.type for e in events_a] == [
        "run_updated",
        "session_updated",
        "run_updated",
    ]
    assert [(e.type, e.seq) for e in events_a] == [
        (e.type, e.seq) for e in events_b
    ]

    # Monotonic sequence numbers and UTC timestamps.
    assert [e.seq for e in events_a] == [1, 2, 3]
    assert bus.seq == 3
    assert all(e.ts.tzinfo is timezone.utc for e in events_a)

    # Payloads are the post-mutation snapshots.
    first, session, second = events_a
    assert isinstance(first.payload, RunSnapshot)
    assert (first.payload.request_id, first.payload.phase) == ("r1", "received")
    assert isinstance(session.payload, SessionSnapshot)
    assert session.payload.session_id == "s1"
    assert second.payload.phase == "governance"

    await sub_a.aclose()
    await sub_b.aclose()


async def test_slow_subscriber_drops_oldest_and_never_blocks_publisher(caplog):
    bus = EventBus(max_queue=2)
    store = StateStore(notify=bus.publish)
    sub = bus.subscribe()

    with caplog.at_level(logging.WARNING, logger="app.state.events"):
        for _ in range(4):  # nobody consuming: seqs 1 and 2 must roll off
            await store.touch_session("s1")

    assert [(await anext(sub)).seq for _ in range(2)] == [3, 4]
    assert sub._queue.empty()
    dropped = [r for r in caplog.records if "Slow event subscriber" in r.message]
    assert len(dropped) == 2

    await sub.aclose()


async def test_aclose_unsubscribes_and_ends_iteration():
    bus = EventBus()
    sub = bus.subscribe()
    assert bus.subscriber_count == 1

    await sub.aclose()
    await sub.aclose()  # idempotent
    assert bus.subscriber_count == 0
    with pytest.raises(StopAsyncIteration):
        await anext(sub)

    # Publishing with no subscribers still advances the sequence, quietly.
    store = StateStore(notify=bus.publish)
    await store.touch_session("s1")
    assert bus.seq == 1


async def test_aclose_before_first_read_still_unsubscribes():
    bus = EventBus()
    sub = bus.subscribe()
    await sub.aclose()  # never iterated
    assert bus.subscriber_count == 0
