"""The readiness gate: a transcript-claiming adapter is not credited until it claims.

A wake pasted into an adapter that has not claimed its transcript used to
advance ``last_seen`` on the paste alone — exactly how a mention was credited
to a live-but-mute CLI that could never speak again. The gate pastes (the wake
carries the claim token, so pasting is how an unclaimed adapter claims) but
holds delivery credit until the claim appears; an unadvanced cursor is the
durable record of what was never proved ingested.
"""

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
        self.posts: list[tuple] = []
        self.statuses: list[str] = []

    async def record_post(self, sender, sender_type, body):
        self.posts.append((sender, sender_type, body))

    async def record_status(self, value):
        self.statuses.append(value)

    async def deliver(self, messages: list[dict]):
        # Record instead of writing a pty; the gate only observes the paste.
        self.deliveries.append(messages)


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

    async def test_the_claim_credits_everything_pasted_so_far(self):
        adapter = self.adapter(transcript=True)
        first = self.say("wake one")
        await self.runtime.deliver_pending("line", self.attachment(), adapter)
        second = self.say("wake two")
        await self.runtime.deliver_pending("line", self.attachment(), adapter)
        self.assertEqual(len(adapter.deliveries), 2)
        self.assertEqual(adapter.deliveries[1], [m for m in adapter.deliveries[1] if m["id"] == second])

        adapter._ready_result = True  # the transcript claim appears
        self.assertTrue(await self.runtime.deliver_pending("line", self.attachment(), adapter))
        self.assertEqual(self.db.get_attachment("att")["last_seen"], max(first, second))
        self.assertEqual(len(adapter.deliveries), 2)  # crediting re-pastes nothing

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

    async def test_the_claim_credits_through_a_state_broadcast_without_a_mention(self):
        adapter = self.adapter(transcript=True)
        only = self.say("wake one")
        await self.runtime.deliver_pending("line", self.attachment(), adapter)
        self.assertEqual(self.db.get_attachment("att")["last_seen"], 0)

        from partyline.attachment_broadcast import broadcast_attachment_state

        adapter._ready_result = True  # the claim appears mid-turn
        await broadcast_attachment_state(self.runtime, "line", "att")
        self.assertEqual(self.db.get_attachment("att")["last_seen"], only)
        self.assertEqual(len(adapter.deliveries), 1)  # no re-paste, no mention needed

    async def test_mark_ready_itself_credits_without_broadcast_or_mention(self):
        """Sol's fixture: hermes/muse/pi declare no receipt turn ends, so no
        attachment broadcast is guaranteed after the claim. The claim point
        itself (mark_ready, fired by _tail_jsonl in all nine adapters) has to
        be the trigger."""
        adapter = self.adapter(transcript=True)
        only = self.say("wake one")
        await self.runtime.deliver_pending("line", self.attachment(), adapter)
        self.assertEqual(self.db.get_attachment("att")["last_seen"], 0)

        adapter.mark_ready()  # _tail_jsonl opening the claimed transcript
        self.assertEqual(self.db.get_attachment("att")["last_seen"], only)
        self.assertEqual(len(adapter.deliveries), 1)

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
