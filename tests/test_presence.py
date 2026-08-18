"""Wake receipts: the server says who is working, and nobody else can.

The failure these exist for: a process is working from the moment it is woken,
but says nothing until its turn ends, so the room cannot tell thinking from
dead. Every assertion here is about *who* produced the signal as much as when.
"""

import asyncio
import unittest
from pathlib import Path

from partyline.presence import Presence


class FakeRuntime:
    def __init__(self):
        self.events = []

    async def broadcast(self, conv_id, event):
        self.events.append((conv_id, event.model_dump()))

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

    async def test_speech_ends_the_turn(self):
        posted = []

        async def post(sender, sender_type, body):
            posted.append(body)

        adapter = self.presence.watch(RecordingAdapter(), "line", "att")
        speak = self.presence.posting("line", "att", post)
        await adapter.deliver([{"id": 1}])
        await speak("grok", "agent", "here is the answer")

        self.assertEqual(posted, ["here is the answer"])
        self.assertFalse(self.presence.is_working("att"))
        self.assertEqual(self.runtime.working_events(), [("att", True), ("att", False)])

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

        self.assertEqual(self.presence.working_ids(), ["two"])

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

        self.assertEqual(presence.working_ids(), ["two"])


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
        self.assertEqual(event, {"type": "working", "attachment_id": "att-uuid", "working": True})


if __name__ == "__main__":
    unittest.main()
