"""Durable exact-message delivery for receipt adapters."""

import tempfile
import unittest

from partyline.db import Db
from partyline.presence import Presence
from partyline.runtime import ChatRuntime


class RecordingAdapter:
    def __init__(self, owner: str):
        self.att = {"runtime_owner": owner}
        self.deliveries: list[list[dict]] = []
        self.pastes: list[str] = []

    async def deliver(self, messages: list[dict]):
        self.deliveries.append(messages)

    async def send_keys(self, text: str):
        self.pastes.append(text)


class DurableDeliveryQueueTest(unittest.IsolatedAsyncioTestCase):
    async def test_compact_pastes_now_while_idle(self):
        presence = Presence(type("Runtime", (), {"broadcast": lambda *args: None})())
        sent = []

        async def send():
            sent.append("/compact")

        self.assertFalse(await presence.queue.compact("att", send, working=False))
        self.assertEqual(sent, ["/compact"])

    async def test_compact_mid_turn_is_latest_wins_and_fires_on_ended(self):
        class Runtime:
            async def broadcast(self, *args):
                pass

            async def broadcast_attachment(self, *args):
                pass

        presence = Presence(Runtime())
        sent = []

        async def first():
            sent.append("first")

        async def latest():
            sent.append("latest")

        await presence.began("line", "att")
        self.assertTrue(await presence.queue.compact("att", first, working=True))
        self.assertTrue(await presence.queue.compact("att", latest, working=True))
        self.assertEqual(sent, [])
        self.assertFalse(await presence.queue.flush("att"))
        self.assertEqual(sent, [])

        await presence.ended("line", "att")

        self.assertEqual(sent, ["latest"])

    async def test_held_wake_runs_before_compact_at_turn_end(self):
        with tempfile.TemporaryDirectory() as directory:
            db = Db(f"{directory}/partyline.db")
            try:
                db.create_conversation("line", "Line")
                db.add_attachment(
                    "att", "line", "composer", "fake", ["fake"], directory, "owner"
                )
                db.set_attachment_status("att", "running", "owner")
                runtime = ChatRuntime(db)
                presence = Presence(runtime)
                adapter = RecordingAdapter("owner")
                watched = presence.watch(
                    adapter,
                    "line",
                    "att",
                    "receipt",
                    *runtime.held_wake_hooks("line", "att", "composer"),
                )
                runtime.live["att"] = watched
                message = db.add_message("line", "greg", "human", "@composer wake")
                await presence.began("line", "att", owner="owner")
                self.assertFalse(await watched.deliver([message]))
                await presence.queue.compact(
                    "att", lambda: adapter.send_keys("/compact"), working=True
                )

                await presence.ended("line", "att", owner="owner")
                self.assertEqual(adapter.pastes, [])
                self.assertEqual(adapter.deliveries, [[message]])
                self.assertEqual(presence.queue.held_count("att"), 0)

                await presence.began("line", "att", owner="owner")
                await presence.ended("line", "att", owner="owner")
                self.assertEqual(adapter.pastes, ["/compact"])
                self.assertEqual(adapter.deliveries, [[message]])
            finally:
                db.close()

    async def test_unmentioned_chatter_does_not_paste_on_ended(self):
        with tempfile.TemporaryDirectory() as directory:
            db = Db(f"{directory}/partyline.db")
            try:
                db.create_conversation("line", "Line")
                db.add_attachment(
                    "att", "line", "composer", "fake", ["fake"], directory, "owner"
                )
                db.set_attachment_status("att", "running", "owner")
                runtime = ChatRuntime(db)
                presence = Presence(runtime)
                adapter = RecordingAdapter("owner")
                watched = presence.watch(
                    adapter,
                    "line",
                    "att",
                    "receipt",
                    *runtime.held_wake_hooks("line", "att", "composer"),
                )
                runtime.live["att"] = watched
                chatter = db.add_message("line", "greg", "human", "not a mention")

                await presence.began("line", "att", owner="owner")
                await presence.ended("line", "att", owner="owner")

                self.assertEqual(adapter.deliveries, [])
                self.assertEqual(db.get_attachment("att")["last_seen"], 0)
                self.assertEqual(db.messages_after("line", 0), [chatter])
            finally:
                db.close()

    async def test_give_up_survives_restart_and_replays_a_without_later_chatter_b(self):
        with tempfile.TemporaryDirectory() as directory:
            path = f"{directory}/partyline.db"
            first_db = Db(path)
            first_db.create_conversation("line", "Line")
            first_db.add_attachment(
                "att", "line", "composer", "fake", ["fake"], directory, "owner-one"
            )
            first_db.set_attachment_status("att", "running", "owner-one")
            first_runtime = ChatRuntime(first_db)
            first_presence = Presence(first_runtime)
            first_adapter = RecordingAdapter("owner-one")
            watched = first_presence.watch(
                first_adapter,
                "line",
                "att",
                "receipt",
                *first_runtime.held_wake_hooks("line", "att", "composer"),
            )
            first_runtime.live["att"] = watched

            message_a = first_db.add_message("line", "greg", "human", "@composer A")
            attachment = first_db.get_attachment("att")
            self.assertTrue(
                await first_runtime.deliver_pending("line", attachment, watched)
            )
            await first_presence.began("line", "att")
            self.assertTrue(
                await watched.att["repool_message_ids"]([message_a["id"]])
            )
            message_b = first_db.add_message("line", "greg", "human", "later chatter B")
            self.assertEqual(first_db.queued_delivery_ids("att"), [message_a["id"]])
            first_db.close()

            second_db = Db(path)
            try:
                second_db.mark_stale_attachments()
                self.assertTrue(second_db.claim_attachment("att", "owner-two"))
                self.assertTrue(
                    second_db.set_attachment_status("att", "running", "owner-two")
                )
                second_runtime = ChatRuntime(second_db)
                second_presence = Presence(second_runtime)
                second_adapter = RecordingAdapter("owner-two")
                reattached = second_presence.watch(
                    second_adapter,
                    "line",
                    "att",
                    "receipt",
                    *second_runtime.held_wake_hooks("line", "att", "composer"),
                )
                second_runtime.live["att"] = reattached

                self.assertEqual(second_presence.queue.held_count("att"), 1)
                await second_presence.began("line", "att", owner="owner-two")
                await second_presence.ended("line", "att", owner="owner-two")
                self.assertEqual(second_adapter.deliveries, [[message_a]])
                self.assertNotIn(message_b, second_adapter.deliveries[0])
                self.assertEqual(second_db.get_attachment("att")["last_seen"], message_a["id"])
                self.assertEqual(second_db.queued_delivery_ids("att"), [])
                self.assertEqual(
                    second_db.messages_after("line", message_a["id"]), [message_b]
                )
            finally:
                second_db.close()


if __name__ == "__main__":
    unittest.main()
