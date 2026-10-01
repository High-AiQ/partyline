"""A person's plain message on a line with one live process reaches that process."""

import tempfile
import unittest
from partyline.db import Db
from partyline.hierarchy import create_child_conversation
from partyline.runtime import ChatRuntime
from partyline.resume_backlog import addressed_backlog
from partyline.solo_line import implied_addressee, solo_process


class Recorder:
    def __init__(self, att: dict):
        self.att = att
        self.delivered: list[dict] = []
        self.wakes = 0

    async def deliver(self, messages):
        self.wakes += 1
        self.delivered.extend(messages)


# The shape greg's text-plus-image post actually had: a second paragraph that
# begins a line with "Also,", which the colon-address guess reads as a handle.
ATTACHMENT_CAPTION = (
    "Couple things:\n\n"
    "The plus box is too big, it’s out of place too. Why not a faded happy "
    "face or something.\n\n"
    "Also, look at the placeholder text for the input area when I’m in mobile "
    "view, it’s cut off at the bottom\n"
    "📷 image · 1320×2868 · thumb: https://partyline.example/api/media/"
    "be81cde2/thumb · slim: https://partyline.example/api/media/"
    "be81cde2/slim · original: https://partyline.example/api/media/"
    "be81cde2/original"
)


class SoloLineTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db = Db(f"{self.tmp.name}/partyline.db")
        self.addCleanup(self.db.close)
        self.db.create_conversation("line", "Line")
        self.runtime = ChatRuntime(self.db)
        self.runtime.broadcast = self._noop
        self.runtime.broadcast_all = self._noop
        self.fable = self.attach("fable-att", "fable")

    async def _noop(self, *args, **kwargs):
        return None

    def attach(self, att_id: str, name: str, status: str = "running") -> Recorder:
        self.db.add_attachment(att_id, "line", name, "fake", ["fake"], self.tmp.name, "owner")
        self.db.set_attachment_status(att_id, status, "owner")
        recorder = Recorder(self.db.get_attachment(att_id))
        self.runtime.live[att_id] = recorder
        return recorder

    async def say(self, body: str, sender: str = "greg", kind: str = "human") -> dict:
        return await self.runtime.post_message("line", sender, kind, body)

    async def test_a_plain_human_message_wakes_the_only_live_process(self):
        await self.say("please read the checkpoint and tell me the ledger")
        self.assertEqual([m["body"] for m in self.fable.delivered],
                         ["please read the checkpoint and tell me the ledger"])
        self.assertEqual(solo_process(self.db, "line")["name"], "fable")

    async def test_literal_14852_body_wakes_the_solo_process(self):
        body = ('yes please do the follow-up so a child captain\'s @mention '
                'hand-off stops the extra "goal still open" wake')
        await self.say(body)
        self.assertEqual([m["body"] for m in self.fable.delivered], [body])

    async def test_unknown_at_words_and_email_prose_still_wake_solo_process(self):
        for body in ("@mention is literal prose", "@param is a placeholder",
                     "email greg@example.com about it"):
            with self.subTest(body=body):
                self.fable.delivered.clear()
                self.fable.wakes = 0
                await self.say(body)
                self.assertEqual([m["body"] for m in self.fable.delivered], [body])

    async def test_known_but_exited_mention_does_not_redirect_to_solo_process(self):
        self.attach("lead-att", "lead", status="exited")
        await self.say("@lead please review")
        self.assertEqual(self.fable.delivered, [])

    async def test_all_still_reaches_the_solo_process(self):
        await self.say("@all please read this")
        self.assertEqual([m["body"] for m in self.fable.delivered],
                         ["@all please read this"])

    async def test_unknown_mention_on_a_multi_process_line_reports_nobody_reached(self):
        self.attach("grok-att", "grok")
        await self.say("@missing please review")
        self.assertEqual((self.fable.delivered, self.runtime.live["grok-att"].delivered),
                         ([], []))
        self.assertIn(
            "nobody live on this line is named @missing",
            self.db.list_messages("line")[-1]["body"])
        notices = [m for m in self.db.list_messages("line")
                   if "nobody live on this line" in m["body"]]
        self.assertEqual(len(notices), 1)

    async def test_a_reachable_related_process_is_a_known_mention(self):
        create_child_conversation(self.db, "line", "child", "Child")
        self.db.add_attachment("worker-att", "child", "worker", "fake", ["fake"],
                               self.tmp.name, "owner")
        self.db.set_attachment_status("worker-att", "running", "owner")
        worker = Recorder(self.db.get_attachment("worker-att"))
        self.runtime.live["worker-att"] = worker
        await self.say("@worker please review")
        self.assertEqual(self.fable.delivered, [])
        self.assertEqual([m["body"] for m in worker.delivered], ["@worker please review"])

    async def test_a_user_handle_is_a_known_mention(self):
        self.add_user("greg")
        await self.say("@greg please review")
        self.assertEqual(self.fable.delivered, [])
        self.assertFalse(any("nobody live on this line" in m["body"]
                             for m in self.db.list_messages("line")))

    async def test_a_user_handle_on_a_multi_process_line_posts_no_notice(self):
        self.add_user("greg")
        self.attach("grok-att", "grok")
        await self.say("@greg can you look at this?")
        self.assertEqual(self.fable.delivered, [])
        self.assertEqual(self.runtime.live["grok-att"].delivered, [])
        self.assertFalse(any("nobody live on this line" in m["body"]
                             for m in self.db.list_messages("line")))

    async def test_unknown_name_with_user_handle_reports_only_the_unknown(self):
        self.add_user("greg")
        self.attach("grok-att", "grok")
        await self.say("@missing @greg can you look at this?")
        notices = [m["body"] for m in self.db.list_messages("line")
                   if "nobody live on this line" in m["body"]]
        self.assertEqual(len(notices), 1)
        self.assertIn("@missing", notices[0])
        self.assertNotIn("@greg", notices[0])

    def add_user(self, handle: str):
        self.db._exec(
            "INSERT INTO users(email, handle, password_hash, created_at) "
            "VALUES(?,?,?,?)",
            (f"{handle}@example.com", handle, "unused", 0),
        )

    def test_resume_backlog_uses_the_same_solo_prose_rule(self):
        body = "please do the follow-up; a captain's @mention hand-off"
        message = self.db.add_message("line", "greg", "human", body)
        self.assertEqual(
            [row["id"] for row in addressed_backlog(self.runtime, self.db.get_attachment("fable-att"))],
            [message["id"]],
        )

    async def test_a_second_live_process_restores_the_mention_rule(self):
        grok = self.attach("grok-att", "grok")
        await self.say("who has the ledger?")
        self.assertEqual((self.fable.delivered, grok.delivered), ([], []))
        await self.say("@grok you do")
        # One wake for grok; its digest carries the room's backlog, which is the
        # existing rule, and nothing wakes fable.
        self.assertEqual((grok.wakes, grok.delivered[-1]["body"]), (1, "@grok you do"))
        self.assertEqual(self.fable.delivered, [])

    async def test_a_stopped_process_does_not_count_and_the_shortcut_returns(self):
        self.attach("grok-att", "grok", status="exited")
        await self.say("still just you")
        self.assertEqual([m["body"] for m in self.fable.delivered], ["still just you"])

    async def test_agent_and_system_speech_is_never_implied(self):
        await self.say("done, 6 tests pass", sender="grok", kind="agent")
        await self.say("☏ goal set by @greg: finish", sender="system", kind="system")
        self.assertEqual(self.fable.delivered, [])
        row = self.db.add_message("line", "grok", "agent", "plain reply")
        self.assertIsNone(implied_addressee(self.db, row))

    async def test_an_explicit_mention_of_someone_else_is_not_redirected(self):
        self.attach("grok-att", "grok", status="exited")
        await self.say("@grok are you there?")
        self.assertEqual(self.fable.delivered, [])

    def test_a_private_copy_keeps_its_own_audience(self):
        self.assertIsNone(implied_addressee(self.db, {
            "conv_id": "line", "sender_type": "human", "body": "plain",
            "audience_attachment_id": "someone-else"}))

    async def test_an_attachment_post_with_an_also_comma_line_wakes_now(self):
        # Regression: the attachment's caption was routed but reached nobody
        # because "Also," on its own line read as a colon-address to no one.
        await self.say(ATTACHMENT_CAPTION)
        self.assertEqual(self.fable.wakes, 1)
        self.assertEqual([m["body"] for m in self.fable.delivered],
                         [ATTACHMENT_CAPTION])

    async def test_a_plain_message_after_the_attachment_also_wakes_now(self):
        await self.say(ATTACHMENT_CAPTION)
        self.fable.delivered.clear()
        self.fable.wakes = 0
        await self.say("Hello?")
        self.assertEqual(self.fable.wakes, 1)
        self.assertEqual([m["body"] for m in self.fable.delivered], ["Hello?"])

    def test_prose_that_matches_no_live_handle_is_not_an_address(self):
        self.assertEqual(implied_addressee(self.db, {
            "conv_id": "line", "sender_type": "human",
            "body": "Also, look at the placeholder", "audience_attachment_id": None,
        }), "fable")

    def test_a_colon_address_to_a_live_handle_is_still_an_address(self):
        self.assertIsNone(implied_addressee(self.db, {
            "conv_id": "line", "sender_type": "human",
            "body": "fable, please look", "audience_attachment_id": None,
        }))
