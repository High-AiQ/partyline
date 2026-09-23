"""The readiness gate: a transcript claim releases old pastes for retry.

A wake pasted into an adapter that has not claimed its transcript used to
advance ``last_seen`` on the paste alone — exactly how a mention was credited
to a live-but-mute CLI that could never speak again. The gate pastes (the wake
carries the claim token, so pasting is how an unclaimed adapter claims) but
holds delivery credit until the claim appears, then retries the pending wake.
An unadvanced cursor is the durable record of what was never proved ingested.
"""

import asyncio
import tempfile
import unittest

from partyline.adapters.base import Adapter
from partyline.db import Db
from partyline.presence import Presence
from partyline.runtime import ChatRuntime


class RecordingAdapter(Adapter):
    """Records deliveries through the real base readiness machinery, so the
    regression exercises production ``mark_ready`` — hook included."""

    def __init__(self, owner: str, *, transcript: bool):
        super().__init__(
            {
                "name": "composer",
                "runtime_owner": owner,
                "adapter_metadata": {"capabilities": {"transcript": transcript}},
            },
            self.record_post,
            self.record_status,
        )
        self.deliveries: list[list[dict]] = []
        self.delivery_result = None
        self.delivery_event = asyncio.Event()
        self.posts: list[tuple] = []
        self.statuses: list[str] = []

    async def record_post(self, sender, sender_type, body):
        self.posts.append((sender, sender_type, body))

    async def record_status(self, value):
        self.statuses.append(value)

    async def deliver(self, messages: list[dict]):
        # Record instead of writing a pty; the gate only observes the paste.
        self.deliveries.append(messages)
        self.delivery_event.set()
        return self.delivery_result


class ReadinessDeliveryGateTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db = Db(f"{self.tmp.name}/partyline.db")
        self.addCleanup(self.db.close)
        self.db.create_conversation("line", "Line")
        self.db.add_attachment(
            "att", "line", "composer", "fake", ["fake"], self.tmp.name, "owner"
        )
        self.db.set_attachment_status("att", "running", "owner")
        self.runtime = ChatRuntime(self.db)
        self.presence = Presence(self.runtime)
        self.messages = []

        async def post(conv_id, sender, sender_type, body):
            self.messages.append((sender, body))

        self.runtime.post_message = post

    def adapter(self, *, transcript: bool, completion: str = "none") -> RecordingAdapter:
        adapter = RecordingAdapter("owner", transcript=transcript)
        watched = self.presence.watch(
            adapter, "line", "att", completion,
            *self.runtime.held_wake_hooks("line", "att", "composer"),
        )
        self.runtime.live["att"] = watched  # production only routes to live watchers
        return watched

    def attachment(self):
        return self.db.get_attachment("att")

    def say(self, body: str) -> int:
        return self.db.add_message("line", "greg", "human", f"@composer {body}")["id"]

    async def test_an_unclaimed_transcript_adapter_is_pasted_without_credit(self):
        adapter = self.adapter(transcript=True)
        self.say("wake one")
        self.assertTrue(await self.runtime.deliver_pending("line", self.attachment(), adapter))
        self.assertEqual(len(adapter.deliveries), 1)  # pasted — the paste is the probe
        self.assertEqual(self.db.get_attachment("att")["last_seen"], 0)  # not credited
        self.assertEqual(len(self.messages), 1)
        self.assertIn("has not claimed its transcript", self.messages[0][1])

    async def test_claim_does_not_credit_a_paste_without_its_own_proof(self):
        adapter = self.adapter(transcript=True, completion="receipt")
        first = self.say("wake one")
        await self.runtime.deliver_pending("line", self.attachment(), adapter)
        second = self.say("wake two")
        await self.runtime.deliver_pending("line", self.attachment(), adapter)
        self.assertEqual(len(adapter.deliveries), 2)
        self.assertEqual(adapter.deliveries[1], [m for m in adapter.deliveries[1] if m["id"] == second])

        adapter.delivery_result = False  # paste still has no user-record receipt
        adapter.delivery_event.clear()
        adapter.mark_ready()  # the transcript claim appears
        self.assertEqual(self.db.get_attachment("att")["last_seen"], 0)
        await asyncio.wait_for(adapter.delivery_event.wait(), timeout=1.0)
        self.assertEqual(len(adapter.deliveries), 3)  # both unproved wakes retry

        await adapter.att["confirm_delivery_ids"]([first])
        self.assertEqual(self.db.get_attachment("att")["last_seen"], first)
        self.assertEqual(len(adapter.deliveries), 3)

    async def test_unproved_pastes_are_suppressed_and_later_proof_cannot_skip_a_gap(self):
        adapter = self.adapter(transcript=True)
        adapter._ready_result = True
        adapter.delivery_result = False
        first = self.say("wake one")
        self.assertFalse(await self.runtime.deliver_pending("line", self.attachment(), adapter))
        second = self.say("wake two")
        self.assertFalse(await self.runtime.deliver_pending("line", self.attachment(), adapter))
        self.assertEqual([[m["id"] for m in batch] for batch in adapter.deliveries], [[first], [second]])
        self.assertFalse(await self.runtime.deliver_pending("line", self.attachment(), adapter))
        self.assertEqual(len(adapter.deliveries), 2)

        confirm = adapter.att["confirm_delivery_ids"]
        self.assertFalse(await confirm([second]))
        self.assertEqual(self.db.get_attachment("att")["last_seen"], 0)
        self.assertTrue(await confirm([first]))
        self.assertEqual(self.db.get_attachment("att")["last_seen"], second)

    async def test_a_second_unready_delivery_pastes_only_what_is_new(self):
        adapter = self.adapter(transcript=True)
        first = self.say("wake one")
        await self.runtime.deliver_pending("line", self.attachment(), adapter)
        second = self.say("wake two")
        await self.runtime.deliver_pending("line", self.attachment(), adapter)
        self.assertEqual([m["id"] for m in adapter.deliveries[1]], [second])
        self.assertNotIn(first, [m["id"] for m in adapter.deliveries[1]])

    async def test_the_held_credit_notice_posts_once_per_episode(self):
        adapter = self.adapter(transcript=True)
        for n in range(3):
            self.say(f"wake {n}")
            await self.runtime.deliver_pending("line", self.attachment(), adapter)
        self.assertEqual(len(self.messages), 1)

    async def test_a_replacement_activation_owes_nothing_and_is_owed_everything(self):
        """Sol's lifecycle fixture: the predecessor's pasted-unproved ids must
        neither suppress the replacement's delivery nor be credited by it."""
        first = self.adapter(transcript=True)
        stale = self.say("wake one")
        await self.runtime.deliver_pending("line", self.attachment(), first)
        self.assertEqual(self.db.get_attachment("att")["last_seen"], 0)

        self.db.mark_stale_attachments()
        self.assertTrue(self.db.claim_attachment("att", "owner-two"))
        self.db.set_attachment_status("att", "running", "owner-two")
        replacement = RecordingAdapter("owner-two", transcript=True)
        replacement._ready_result = True  # claimed before its first wake
        watched = self.presence.watch(
            replacement, "line", "att", "receipt",
            *self.runtime.held_wake_hooks("line", "att", "composer"),
        )
        self.runtime.live["att"] = watched
        fresh = self.say("wake two")
        await self.runtime.deliver_pending("line", self.attachment(), replacement)
        delivered = [m["id"] for m in replacement.deliveries[0]]
        self.assertEqual(delivered, [stale, fresh])  # nothing suppressed
        self.assertEqual(self.db.get_attachment("att")["last_seen"], fresh)

    async def test_a_state_broadcast_releases_unproved_pastes_without_credit(self):
        adapter = self.adapter(transcript=True, completion="receipt")
        adapter.delivery_result = False
        only = self.say("wake one")
        self.assertFalse(await self.runtime.deliver_pending("line", self.attachment(), adapter))
        self.assertEqual(self.db.get_attachment("att")["last_seen"], 0)

        from partyline.attachment_broadcast import broadcast_attachment_state

        adapter._ready_result = True  # the claim appears mid-turn
        adapter.delivery_event.clear()
        await broadcast_attachment_state(self.runtime, "line", "att")
        self.assertEqual(self.db.get_attachment("att")["last_seen"], 0)
        await asyncio.wait_for(adapter.delivery_event.wait(), timeout=1.0)
        self.assertEqual(len(adapter.deliveries), 2)
        await adapter.att["confirm_delivery_ids"]([only])
        self.assertEqual(self.db.get_attachment("att")["last_seen"], only)

    async def test_claim_retries_preclaim_paste_without_a_later_mention(self):
        """Claim releases the old attempt and retries it while the line is idle."""
        adapter = self.adapter(transcript=True, completion="receipt")
        adapter.delivery_result = False
        only = self.say("wake one")
        self.assertFalse(await self.runtime.deliver_pending("line", self.attachment(), adapter))
        self.assertEqual(self.db.get_attachment("att")["last_seen"], 0)

        adapter.delivery_event.clear()
        adapter.mark_ready()  # _tail_jsonl opening the claimed transcript
        self.assertEqual(self.db.get_attachment("att")["last_seen"], 0)
        await asyncio.wait_for(adapter.delivery_event.wait(), timeout=1.0)
        self.assertEqual(len(adapter.deliveries), 2)  # automatic idle retry
        self.assertEqual(self.db.get_attachment("att")["last_seen"], 0)

        await adapter.att["confirm_delivery_ids"]([only])
        self.assertEqual(self.db.get_attachment("att")["last_seen"], only)

    async def test_claim_retry_holds_addressed_wake_until_briefing_turn_ends(self):
        adapter = self.adapter(transcript=True, completion="receipt")
        adapter.delivery_result = False
        only = self.say("wake one")  # direct addressing would bypass the busy hold
        self.assertFalse(await self.runtime.deliver_pending("line", self.attachment(), adapter))

        await self.presence.started("line", "att", "owner")
        adapter.mark_ready()
        await asyncio.sleep(0)  # run the scheduled claim retry

        self.assertEqual(len(adapter.deliveries), 1)
        self.assertEqual(self.presence.queue.held_ids("att"), [only])
        self.assertEqual(self.db.get_attachment("att")["last_seen"], 0)

        await self.presence.ended("line", "att", "owner")
        self.assertEqual(len(adapter.deliveries), 2)
        self.assertEqual(self.db.get_attachment("att")["last_seen"], 0)
        await adapter.att["confirm_delivery_ids"]([only])
        self.assertEqual(self.db.get_attachment("att")["last_seen"], only)

    async def test_claim_keeps_old_ids_suppressed_until_retry_queue_owns_them(self):
        adapter = self.adapter(transcript=True, completion="receipt")
        adapter.delivery_result = False
        first = self.say("wake one")
        self.assertFalse(await self.runtime.deliver_pending("line", self.attachment(), adapter))

        entered = asyncio.Event()
        release = asyncio.Event()

        async def blocked_repool(message_ids):
            self.assertEqual(message_ids, [first])
            entered.set()
            await release.wait()
            return True

        adapter.att["repool_message_ids"] = blocked_repool
        adapter.mark_ready()
        await asyncio.wait_for(entered.wait(), timeout=1.0)

        second = self.say("wake two")
        await self.runtime.deliver_pending("line", self.attachment(), adapter)
        self.assertEqual([m["id"] for m in adapter.deliveries[-1]], [second])

        release.set()
        await asyncio.sleep(0)
        self.assertEqual(self.runtime.uncredited["att"]["ids"], {second})

    async def test_the_claim_hook_is_activation_scoped(self):
        """A replacement activation registers its own hook; the predecessor's
        captured owner must not credit across the ownership change."""
        first = self.adapter(transcript=True)
        self.say("wake one")
        await self.runtime.deliver_pending("line", self.attachment(), first)

        self.db.mark_stale_attachments()
        self.assertTrue(self.db.claim_attachment("att", "owner-two"))
        self.db.set_attachment_status("att", "running", "owner-two")
        replacement = first.__class__("owner-two", transcript=True)
        replacement._ready_result = True
        self.runtime.live["att"] = replacement
        fresh = self.say("wake two")

        # The stale activation fires its hook after losing ownership: no-op.
        first.mark_ready()
        self.assertNotEqual(self.db.get_attachment("att")["last_seen"], fresh - 1)

        await self.runtime.deliver_pending("line", self.attachment(), replacement)
        self.assertEqual(self.db.get_attachment("att")["last_seen"], max(fresh - 1, 0) + 1)

    async def test_a_bare_process_keeps_paste_and_credit(self):
        adapter = self.adapter(transcript=False)
        only = self.say("wake one")
        self.assertTrue(await self.runtime.deliver_pending("line", self.attachment(), adapter))
        self.assertEqual(len(adapter.deliveries), 1)
        self.assertEqual(self.db.get_attachment("att")["last_seen"], only)
        self.assertEqual(self.messages, [])


if __name__ == "__main__":
    unittest.main()
