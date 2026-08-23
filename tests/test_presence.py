"""Wake receipts: the server says who is working, and nobody else can.

The failure these exist for: a process is working from the moment it is woken,
but says nothing until its turn ends, so the room cannot tell thinking from
dead. Every assertion here is about *who* produced the signal as much as when.
"""

import asyncio
import unittest
from pathlib import Path
from unittest.mock import AsyncMock

from partyline.presence import Presence


class FakeRuntime:
    def __init__(self):
        self.events = []
        self.refreshed = []

    async def broadcast(self, conv_id, event):
        self.events.append((conv_id, event.model_dump()))

    async def broadcast_attachment(self, conv_id, att_id):
        self.refreshed.append((conv_id, att_id))

    def working_events(self):
        return [(event["attachment_id"], event["working"]) for _, event in self.events]


class RecordingAdapter:
    def __init__(self, fails=False):
        self.delivered = []
        self.fails = fails

    async def deliver(self, messages):
        if self.fails:
            raise RuntimeError("the pty is gone")
        self.delivered.append(messages)


class PresenceTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.runtime = FakeRuntime()
        self.presence = Presence(self.runtime)

    async def test_a_delivered_wake_reports_the_turn_started(self):
        adapter = self.presence.watch(RecordingAdapter(), "line", "att")
        await adapter.deliver([{"id": 1}])

        self.assertTrue(self.presence.is_working("att"))
        self.assertEqual(self.runtime.working_events(), [("att", True)])

    async def test_the_receipt_follows_the_delivery_rather_than_preceding_it(self):
        """A wake that never reached the pty has not started a turn."""
        adapter = self.presence.watch(RecordingAdapter(fails=True), "line", "att")
        with self.assertRaises(RuntimeError):
            await adapter.deliver([{"id": 1}])

        self.assertFalse(self.presence.is_working("att"))
        self.assertEqual(self.runtime.working_events(), [])

    async def test_a_second_wake_mid_turn_is_not_a_second_receipt(self):
        adapter = self.presence.watch(RecordingAdapter(), "line", "att")
        await adapter.deliver([{"id": 1}])
        await adapter.deliver([{"id": 2}])

        self.assertEqual(self.runtime.working_events(), [("att", True)])

    async def test_an_ack_does_not_end_the_turn(self):
        """The bug @greg reported: agents answer, then keep working.

        This test used to assert the opposite — that the first thing a
        process said ended its turn. An ack is speech, so the badge died
        while the work being acknowledged had not started. The assertion
        that matters is the *absence* of a clearing event: the bug was a
        broadcast that should never have been sent.
        """
        posted = []

        async def post(sender, sender_type, body):
            posted.append(body)

        adapter = self.presence.watch(RecordingAdapter(), "line", "att")
        speak = self.presence.posting("line", "att", post)
        await adapter.deliver([{"id": 1}])
        await speak("grok", "agent", "ack — starting on it now")

        self.assertEqual(posted, ["ack — starting on it now"])
        self.assertTrue(self.presence.is_working("att"))
        self.assertNotIn(("att", False), self.runtime.working_events())
        self.assertEqual(self.presence.phase("att"), "speaking")

    async def test_only_the_harness_receipt_ends_the_turn(self):
        adapter = self.presence.watch(RecordingAdapter(), "line", "att")
        speak = self.presence.posting("line", "att", lambda *_: asyncio.sleep(0))
        await adapter.deliver([{"id": 1}])
        await self.presence.began("line", "att")
        await speak("grok", "agent", "ack")
        await speak("grok", "agent", "and here is the actual result")

        self.assertTrue(self.presence.is_working("att"))
        await self.presence.ended("line", "att")

        self.assertFalse(self.presence.is_working("att"))
        self.assertEqual(self.runtime.refreshed, [("line", "att")])
        self.assertEqual(
            self.runtime.working_events(),
            [("att", True), ("att", True), ("att", False)],
        )

    async def test_two_wakes_folded_into_one_harness_turn_do_not_wedge(self):
        """Raised by @sol: our deliveries do not map one-to-one onto CLI turns.

        A steering CLI can read two pasted digests in a single turn and
        report a single completion. Counting deliveries would leave the badge
        lit forever; counting the harness's own paired boundaries does not.
        """
        adapter = self.presence.watch(RecordingAdapter(), "line", "att")
        await adapter.deliver([{"id": 1}])
        await adapter.deliver([{"id": 2}])
        await self.presence.began("line", "att")
        await self.presence.ended("line", "att")

        self.assertFalse(self.presence.is_working("att"))

    async def test_a_stale_ending_after_a_new_wake_self_heals_on_began(self):
        """The transcript-receipt race (#47): a turn's `ended` can be observed
        one poll *after* a new digest already armed the badge, closing it
        wrongly. The harness's own `began` — the CLI reading that paste —
        re-arms it, so the sequence must end lit."""
        adapter = self.presence.watch(RecordingAdapter(), "line", "att")
        await adapter.deliver([{"id": 1}])
        await self.presence.ended("line", "att")
        self.assertFalse(self.presence.is_working("att"))

        await self.presence.began("line", "att")

        self.assertTrue(self.presence.is_working("att"))
        self.assertEqual(
            self.runtime.working_events(),
            [("att", True), ("att", False), ("att", True)],
        )

    async def test_a_began_while_a_turn_is_open_replaces_the_aborted_turn(self):
        """An Esc-aborted turn never reports its own end; the harness's next
        began is the only deterministic proof the old turn is dead. Stacking
        the two begins instead is how the badge wedged on forever-working."""
        self.presence.watch(RecordingAdapter(), "line", "att", completion="receipt")
        await self.presence.began("line", "att", owner="t")
        await self.presence.began("line", "att", owner="t")
        self.assertTrue(self.presence.is_working("att"))
        await self.presence.ended("line", "att", owner="t")
        self.assertFalse(self.presence.is_working("att"))

    async def test_two_turns_back_to_back_clear_between_and_after(self):
        """Sequential turns each end before the next begins; the badge may
        idle between them and must not stay lit after the second."""
        adapter = self.presence.watch(RecordingAdapter(), "line", "att")
        await adapter.deliver([{"id": 1}])
        await self.presence.began("line", "att")
        await self.presence.ended("line", "att")
        await adapter.deliver([{"id": 2}])
        await self.presence.began("line", "att")
        await self.presence.ended("line", "att")
        self.assertFalse(self.presence.is_working("att"))
        self.assertEqual(
            self.runtime.working_events(),
            [("att", True), ("att", False), ("att", True), ("att", False)],
        )

    async def test_a_system_notice_is_not_the_process_speaking(self):
        """Found by @sol: an adapter's own notices ride this same callback.

        A resume posts a backlog notice through the process's post callback
        before the speech it describes arrives. That is the server talking
        *about* a process, so it must not even move the phase.
        """
        adapter = self.presence.watch(RecordingAdapter(), "line", "att")
        speak = self.presence.posting("line", "att", lambda *_: asyncio.sleep(0))
        await adapter.deliver([{"id": 1}])
        await speak("system", "system", "@groky: relaying 3 message(s)…")

        self.assertEqual(self.presence.phase("att"), "working")
        self.assertEqual(self.runtime.working_events(), [("att", True)])

    async def test_a_late_receipt_cannot_resurrect_a_dead_turn(self):
        """Exit is terminal; the transcript tail is delivery, not work."""
        adapter = self.presence.watch(RecordingAdapter(), "line", "att")
        speak = self.presence.posting("line", "att", lambda *_: asyncio.sleep(0))
        status = self.presence.statusing("line", "att", lambda _: asyncio.sleep(0))
        await adapter.deliver([{"id": 1}])
        await self.presence.began("line", "att")
        await status("exited")
        before = list(self.runtime.working_events())

        await self.presence.ended("line", "att")
        await speak("grok", "agent", "a line the tail was still flushing")

        self.assertFalse(self.presence.is_working("att"))
        self.assertEqual(self.runtime.working_events(), before)

    async def test_a_receipt_from_a_previous_owner_is_ignored(self):
        """Attachments change server generation underneath us (`runtime.py`)."""
        adapter = RecordingAdapter()
        adapter.att = {"runtime_owner": "owner-two"}
        watched = self.presence.watch(adapter, "line", "att")
        await watched.deliver([{"id": 1}])
        await self.presence.began("line", "att", owner="owner-two")

        await self.presence.ended("line", "att", owner="owner-one")
        self.assertTrue(self.presence.is_working("att"))

        await self.presence.ended("line", "att", owner="owner-two")
        self.assertFalse(self.presence.is_working("att"))

    async def test_a_receipt_harness_does_not_arm_on_a_paste(self):
        """The stuck "working…" badge: the paste is not the turn.

        A TUI that silently swallowed a delivered digest never began a
        turn, so nothing may light the badge — arming on the write is
        the guess this regression removes for receipt harnesses.
        """
        adapter = self.presence.watch(RecordingAdapter(), "line", "att", completion="receipt")
        await adapter.deliver([{"id": 1}])

        self.assertFalse(self.presence.is_working("att"))
        self.assertEqual(self.runtime.working_events(), [])

    async def test_a_receipt_harness_arms_on_began_and_clears_on_ended(self):
        self.presence.watch(RecordingAdapter(), "line", "att", completion="receipt")
        await self.presence.began("line", "att", owner="t")
        self.assertTrue(self.presence.is_working("att"))

        await self.presence.ended("line", "att", owner="t")
        self.assertFalse(self.presence.is_working("att"))
        self.assertEqual(self.runtime.working_events(), [("att", True), ("att", False)])

    async def test_a_harness_without_receipts_still_arms_on_delivery(self):
        """The paste remains the only observable for a none-completion harness."""
        adapter = self.presence.watch(RecordingAdapter(), "line", "att", completion="none")
        await adapter.deliver([{"id": 1}])

        self.assertTrue(self.presence.is_working("att"))

    async def test_a_receipt_for_a_superseded_turn_is_ignored(self):
        adapter = self.presence.watch(RecordingAdapter(), "line", "att")
        await adapter.deliver([{"id": 1}])
        await self.presence.began("line", "att", turn=1)
        await self.presence.ended("line", "att", turn=1)
        await adapter.deliver([{"id": 2}])
        await self.presence.began("line", "att", turn=2)

        await self.presence.ended("line", "att", turn=1)
        self.assertTrue(self.presence.is_working("att"))

    async def test_no_guess_can_stand_in_for_a_turn_end(self):
        """@grok's survey: no bundled adapter has trustworthy output timing.

        `quiet` is reserved on the wire for a guessed ending and has no
        emitter. This pins that: the only phases a server can produce are the
        ones it observed.
        """
        adapter = self.presence.watch(RecordingAdapter(), "line", "att", completion="none")
        await adapter.deliver([{"id": 1}])

        # There is no verb for it. A server that cannot say "I think it ended"
        # cannot be wrong about it.
        self.assertFalse(hasattr(self.presence, "quieted"))
        self.assertEqual(self.presence.phase("att"), "working")
        self.assertNotIn("quiet", [event["phase"] for _, event in self.runtime.events])

    async def test_the_snapshot_carries_idle_tombstones_with_their_revision(self):
        """Raised by @sol: an omitted attachment cannot be ordered against.

        A client buffering events while its snapshot is in flight has to know
        whether a held `working` is older than the snapshot. Without a
        tombstone it would replay the stale event and relight a badge that
        had already gone out.
        """
        adapter = self.presence.watch(RecordingAdapter(), "line", "att", completion="receipt")
        await adapter.deliver([{"id": 1}])
        await self.presence.began("line", "att")

        open_state = self.presence.snapshot("line")
        self.assertEqual(len(open_state), 1)
        self.assertEqual(open_state[0]["id"], "att")
        self.assertEqual(open_state[0]["phase"], "working")
        self.assertEqual(open_state[0]["completion"], "receipt")
        self.assertGreater(open_state[0]["since"], 0)

        await self.presence.ended("line", "att")
        closed = self.presence.snapshot("line")
        self.assertEqual(closed[0]["phase"], "idle")
        self.assertEqual(closed[0]["since"], 0.0)
        self.assertGreater(closed[0]["revision"], open_state[0]["revision"])
        self.assertEqual(self.presence.snapshot("other-line"), [])

    async def test_forgetting_an_attachment_drops_its_tombstone_too(self):
        adapter = self.presence.watch(RecordingAdapter(), "line", "att")
        await adapter.deliver([{"id": 1}])
        self.presence.forget("att")

        self.assertEqual(self.presence.snapshot("line"), [])

    async def test_every_announcement_carries_a_rising_revision(self):
        adapter = self.presence.watch(RecordingAdapter(), "line", "att")
        speak = self.presence.posting("line", "att", lambda *_: asyncio.sleep(0))
        await adapter.deliver([{"id": 1}])
        await self.presence.began("line", "att")
        await speak("grok", "agent", "ack")
        await self.presence.ended("line", "att")

        revisions = [event["revision"] for _, event in self.runtime.events]
        phases = [event["phase"] for _, event in self.runtime.events]
        self.assertEqual(revisions, [1, 2, 3])
        self.assertEqual(phases, ["working", "speaking", "idle"])

    async def test_speech_from_an_idle_process_announces_nothing(self):
        """Only a real transition is worth a broadcast."""
        speak = self.presence.posting("line", "att", lambda *_: asyncio.sleep(0))
        await speak("grok", "agent", "unprompted")

        self.assertEqual(self.runtime.working_events(), [])

    async def test_a_process_that_dies_mid_turn_stops_looking_busy(self):
        """A pulse that never stops is a worse lie than no pulse at all."""
        seen = []

        async def on_status(value):
            seen.append(value)

        adapter = self.presence.watch(RecordingAdapter(), "line", "att")
        status = self.presence.statusing("line", "att", on_status)
        await adapter.deliver([{"id": 1}])
        await status("exited")

        self.assertEqual(seen, ["exited"])
        self.assertFalse(self.presence.is_working("att"))
        self.assertEqual(self.runtime.working_events(), [("att", True), ("att", False)])

    async def test_a_running_status_does_not_end_a_turn(self):
        adapter = self.presence.watch(RecordingAdapter(), "line", "att")
        status = self.presence.statusing("line", "att", lambda _: asyncio.sleep(0))
        await adapter.deliver([{"id": 1}])
        await status("running")

        self.assertTrue(self.presence.is_working("att"))

    async def test_several_attachments_are_tracked_apart(self):
        first = self.presence.watch(RecordingAdapter(), "line", "one")
        second = self.presence.watch(RecordingAdapter(), "line", "two")
        await first.deliver([{"id": 1}])
        await second.deliver([{"id": 2}])
        await self.presence.finished("line", "one")

        self.assertEqual(self.presence.working_ids("line"), ["two"])

    async def test_forgetting_an_attachment_is_silent(self):
        adapter = self.presence.watch(RecordingAdapter(), "line", "att")
        await adapter.deliver([{"id": 1}])
        self.presence.forget("att")

        self.assertFalse(self.presence.is_working("att"))
        self.assertEqual(self.runtime.working_events(), [("att", True)])


class SnapshotTest(unittest.IsolatedAsyncioTestCase):
    """A tab that arrives mid-turn must not see an empty room.

    Raised in review by @grok: the events describe transitions, so a browser
    that opens or reconnects while someone is thinking would show nothing
    until that turn ended — the indicator blank exactly when it is wanted.
    """

    async def test_conversation_detail_reports_who_is_working(self):
        import tempfile

        from partyline import server
        from partyline.db import Db
        from partyline.runtime import ChatRuntime

        with tempfile.TemporaryDirectory() as directory:
            db = Db(f"{directory}/partyline.db")
            runtime = ChatRuntime(db)
            presence = Presence(runtime)
            saved = (server.runtime, server.presence, server.media)
            server.runtime, server.presence = runtime, presence
            server.media = server.MediaStore(db, Path(directory) / "media")
            try:
                db.create_conversation("line", "Line")
                await presence.started("line", "busy")
                await presence.started("line", "also-busy")
                await presence.finished("line", "also-busy")
                await presence.started("another-line", "elsewhere")

                detail = await server.conversation_detail("line")
                self.assertEqual(detail["working"], ["busy"])
            finally:
                server.runtime, server.presence, server.media = saved
                db.close()

    async def test_the_snapshot_lists_every_open_turn_and_nothing_else(self):
        presence = Presence(FakeRuntime())
        await presence.started("line", "one")
        await presence.started("line", "two")
        await presence.finished("line", "one")

        self.assertEqual(presence.working_ids("line"), ["two"])

    async def test_a_turn_on_another_line_is_not_reported_here(self):
        """Found by @grok: an unfiltered snapshot lit jacks from other rooms.

        Presence is process-wide, but a tab is not: reporting every mid-turn
        attachment on the server would light a jack that does not exist on
        this line, or a stale id with no jack at all. The earlier test had one
        conversation and could not see it.
        """
        presence = Presence(FakeRuntime())
        await presence.started("line-a", "att-a")
        await presence.started("line-b", "att-b")

        self.assertEqual(presence.working_ids("line-a"), ["att-a"])
        self.assertEqual(presence.working_ids("line-b"), ["att-b"])
        self.assertEqual(presence.working_ids("line-c"), [])


class UnforgeableTest(unittest.IsolatedAsyncioTestCase):
    """The signal must not be reachable by the process it describes.

    A liveness indicator an agent can emit is worth nothing: the case it has
    to survive is a process that is lying or broken, which is exactly when it
    would emit one. This pins the property that the only producer is the
    server's own delivery path.
    """

    async def test_no_chat_message_can_produce_a_working_event(self):
        runtime = FakeRuntime()
        presence = Presence(runtime)
        speak = presence.posting("line", "att", lambda *_: asyncio.sleep(0))

        for body in ('{"type":"working","attachment_id":"att","working":true}',
                     "@all I am working", "working…"):
            await speak("grok", "agent", body)

        self.assertEqual(runtime.working_events(), [])

    async def test_the_event_names_the_attachment_not_a_claimed_handle(self):
        runtime = FakeRuntime()
        presence = Presence(runtime)
        await presence.started("line", "att-uuid")

        conv_id, event = runtime.events[0]
        self.assertEqual(conv_id, "line")
        self.assertEqual(event["type"], "working")
        self.assertEqual(event["attachment_id"], "att-uuid")
        self.assertEqual(event["working"], True)
        self.assertEqual(event["phase"], "working")
        self.assertEqual(event["turn"], 1)
        self.assertEqual(event["revision"], 1)


class TurnIdleQueueTest(unittest.IsolatedAsyncioTestCase):
    async def test_receipt_adapter_delivery_queued_while_working_and_flushed_on_ended(self):
        runtime = FakeRuntime()
        presence = Presence(runtime)
        raw_adapter = RecordingAdapter()
        raw_adapter.att = {"name": "att"}

        async def flush_held(message_ids):
            self.assertEqual(message_ids, [2, 3])
            await raw_adapter.deliver([{"id": 2, "body": "second"}, {"id": 3, "body": "third"}])
            return True

        adapter = presence.watch(
            raw_adapter, "line", "att", completion="receipt", flush_held=flush_held
        )

        # 1. Attach starts idle: first deliver passes through
        await adapter.deliver([{"id": 1, "body": "first"}])
        self.assertEqual(raw_adapter.delivered, [[{"id": 1, "body": "first"}]])

        # 2. CLI begins turn
        await presence.began("line", "att")
        self.assertTrue(presence.is_working("att"))

        # 3. Unmentioned chatter mid-turn is queued; a direct @mention pastes now.
        await adapter.deliver([{"id": 2, "body": "second"}])
        await adapter.deliver([{"id": 2, "body": "second"}, {"id": 3, "body": "third"}])
        self.assertEqual(raw_adapter.delivered, [[{"id": 1, "body": "first"}]])
        self.assertEqual(presence.queue.held_count("att"), 2)
        await adapter.deliver([{"id": 4, "body": "@att stop"}])
        self.assertEqual(
            raw_adapter.delivered,
            [[{"id": 1, "body": "first"}], [{"id": 4, "body": "@att stop"}]],
        )

        # Snapshots report held count
        snapshot = presence.snapshot("line")
        self.assertEqual(len(snapshot), 1)
        self.assertEqual(snapshot[0]["held"], 2)

        # 4. Turn ends: queue flushes coalesced in order
        await presence.ended("line", "att")
        self.assertFalse(presence.is_working("att"))
        self.assertEqual(presence.queue.held_count("att"), 0)
        self.assertEqual(
            raw_adapter.delivered,
            [
                [{"id": 1, "body": "first"}],
                [{"id": 4, "body": "@att stop"}],
                [{"id": 2, "body": "second"}, {"id": 3, "body": "third"}],
            ],
        )

    async def test_ended_does_not_flush_unheld_chatter(self):
        runtime = FakeRuntime()
        presence = Presence(runtime)
        flush_held = AsyncMock(return_value=True)
        presence.watch(
            RecordingAdapter(), "line", "att", completion="receipt", flush_held=flush_held
        )

        await presence.began("line", "att")
        await presence.ended("line", "att")

        flush_held.assert_not_awaited()

    async def test_a_proven_skip_flushes_immediately_when_idle(self):
        runtime = FakeRuntime()
        presence = Presence(runtime)
        raw_adapter = RecordingAdapter()
        raw_adapter.att = {"runtime_owner": "owner"}
        persisted = []
        flushed = []

        async def persist_ids(message_ids):
            persisted.extend(message_ids)
            return True

        async def flush_ids(message_ids):
            flushed.append(message_ids)
            persisted.clear()
            return True

        adapter = presence.watch(
            raw_adapter, "line", "att", "receipt",
            flush_ids, lambda: list(persisted), persist_ids,
        )
        self.assertTrue(await adapter.att["repool_message_ids"]([7]))
        self.assertEqual(flushed, [[7]])
        self.assertEqual(presence.queue.held_count("att"), 0)

    async def test_badge_and_flush_deduplicate_transient_and_persisted_ids(self):
        runtime = FakeRuntime()
        presence = Presence(runtime)
        raw_adapter = RecordingAdapter()
        persisted = [2, 3]

        async def flush_ids(message_ids):
            self.assertEqual(message_ids, [1, 2, 3])
            persisted.clear()
            return True

        adapter = presence.watch(
            raw_adapter, "line", "att", "receipt", flush_ids, lambda: persisted
        )
        await presence.began("line", "att")
        await adapter.deliver([{"id": 1}, {"id": 2}])
        self.assertEqual(presence.snapshot("line")[0]["held"], 3)
        await presence.ended("line", "att")
        self.assertEqual(presence.queue.held_count("att"), 0)

    async def test_second_began_repairs_state_without_pasting_from_queue(self):
        runtime = FakeRuntime()
        presence = Presence(runtime)
        raw_adapter = RecordingAdapter()
        adapter = presence.watch(raw_adapter, "line", "att", completion="receipt")

        await presence.began("line", "att")
        await adapter.deliver([{"id": 2, "body": "second"}])
        self.assertEqual(presence.queue.held_count("att"), 1)

        # Second began repairs open state only — no delivery from queue
        await presence.began("line", "att")
        self.assertTrue(presence.is_working("att"))
        self.assertEqual(raw_adapter.delivered, [])
        self.assertEqual(presence.queue.held_count("att"), 1)

    async def test_process_exit_discards_queue_and_posts_notice(self):
        runtime = FakeRuntime()
        presence = Presence(runtime)
        raw_adapter = RecordingAdapter()
        posted = []

        async def post(sender, sender_type, body):
            posted.append((sender, sender_type, body))

        raw_adapter.post = post
        adapter = presence.watch(raw_adapter, "line", "att", completion="receipt")

        await presence.began("line", "att")
        await adapter.deliver([{"id": 2, "body": "second"}])
        await adapter.deliver([{"id": 2, "body": "second"}, {"id": 3, "body": "third"}])

        on_status = AsyncMock()
        status_cb = presence.statusing("line", "att", on_status, name="composer")
        await status_cb("exited")

        self.assertFalse(presence.is_working("att"))
        self.assertEqual(presence.queue.held_count("att"), 0)
        self.assertEqual(len(posted), 1)
        self.assertIn("⚠ @composer exited with 2 held mentions undelivered", posted[0][2])


if __name__ == "__main__":
    unittest.main()
