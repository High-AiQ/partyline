"""An explicit resume hands its backlog to the adapter to stage, never pasting blind."""

import asyncio
import tempfile
import unittest

from partyline.db import Db
from partyline.reattach import ResumedAttachment
from partyline.resume_continuation import drain, resume_with_backlog
from partyline.runtime import ChatRuntime


class StagingAdapter:
    """Accepts its backlog as a startup prompt, like codex resume."""

    def __init__(self, owner):
        self.att = {"runtime_owner": owner}
        self.staged = None
        self.deliveries = []

    async def wait_startup_delivery_received(self):
        return True

    async def wait_ready(self):
        return True

    async def deliver(self, messages):
        self.deliveries.append(messages)


class PastingAdapter(StagingAdapter):
    """No startup prompt: the backlog must wait for readiness, then be pasted."""


class ResumeContinuationTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.db = Db(f"{self.directory.name}/partyline.db")
        self.runtime = ChatRuntime(self.db)
        self.db.create_conversation("line", "Line")
        self.db.add_attachment("one", "line", "luna", "fake", ["fake"], "/tmp", "owner-1")
        self.db.set_attachment_status("one", "exited", "owner-1")
        self.db.add_message("line", "greg", "human", "@luna finish the adapter")

    async def asyncTearDown(self):
        self.db.close()
        self.directory.cleanup()

    def _resume(self, adapter, staged):
        seen = {}

        async def resume(att_id, pending):
            seen["pending"] = pending
            adapter.staged = pending if staged else None
            return ResumedAttachment(adapter, staged)

        return resume, seen

    async def test_a_staging_adapter_gets_the_backlog_and_the_notice_as_its_prompt(self):
        self.db._exec("UPDATE attachments SET turn_open=1 WHERE id='one'")
        adapter = StagingAdapter("owner-1")
        resume, seen = self._resume(adapter, staged=True)
        await resume_with_backlog(self.runtime, "one", resume)
        await drain()
        bodies = [m["body"] for m in seen["pending"]]
        self.assertEqual(bodies[0], "@luna finish the adapter")
        self.assertIn("restarted in the middle of a turn", bodies[1])
        self.assertEqual(seen["pending"][1]["audience_attachment_id"], "one")
        self.assertEqual(adapter.deliveries, [])  # nothing pasted at t=0
        self.assertEqual(self.db.get_attachment("one")["last_seen"], seen["pending"][-1]["id"])
        self.assertEqual(self.db.get_attachment("one")["turn_open"], 0)

    async def test_a_pasting_adapter_gets_the_backlog_only_after_it_is_ready(self):
        adapter = PastingAdapter("owner-1")
        resume, seen = self._resume(adapter, staged=False)
        await resume_with_backlog(self.runtime, "one", resume)
        await drain()
        self.assertEqual([m["body"] for m in adapter.deliveries[0]], ["@luna finish the adapter"])
        self.assertEqual(self.db.get_attachment("one")["last_seen"], seen["pending"][-1]["id"])

    async def test_a_process_that_finished_its_turn_gets_no_notice(self):
        adapter = StagingAdapter("owner-1")
        resume, seen = self._resume(adapter, staged=True)
        await resume_with_backlog(self.runtime, "one", resume)
        await drain()
        self.assertEqual([m["body"] for m in seen["pending"]], ["@luna finish the adapter"])

    async def test_nothing_pending_means_nothing_to_settle(self):
        self.db.set_last_seen("one", 10**6, "owner-1")
        self.db.add_message("line", "luna", "agent", "I finished the request")
        adapter = StagingAdapter("owner-1")
        resume, seen = self._resume(adapter, staged=True)
        await resume_with_backlog(self.runtime, "one", resume)
        await asyncio.sleep(0)
        self.assertEqual(seen["pending"], [])

    async def test_a_plain_human_message_is_delivered_to_a_stopped_solo_process(self):
        self.db.add_message("line", "greg", "human", "please look at this")
        adapter = StagingAdapter("owner-1")
        resume, seen = self._resume(adapter, staged=True)

        await resume_with_backlog(self.runtime, "one", resume)
        await drain()

        self.assertEqual(
            [message["body"] for message in seen["pending"]],
            ["@luna finish the adapter", "please look at this"],
        )

    async def test_a_cursor_passed_plain_message_replays_to_the_resuming_solo_process(self):
        message = self.db.add_message("line", "greg", "human", "please look again")
        self.db.set_last_seen("one", message["id"], "owner-1")
        adapter = StagingAdapter("owner-1")
        resume, seen = self._resume(adapter, staged=True)

        await resume_with_backlog(self.runtime, "one", resume)
        await drain()

        self.assertEqual([row["body"] for row in seen["pending"]], ["please look again"])

    async def test_a_cursor_passed_nonhuman_latest_message_does_not_replay(self):
        assignment = self.db.add_message("line", "greg", "human", "@luna please finish")
        self.db.set_last_seen("one", assignment["id"], "owner-1")
        self.db.add_message("line", "luna", "agent", "done")

        adapter = StagingAdapter("owner-1")
        resume, seen = self._resume(adapter, staged=True)
        await resume_with_backlog(self.runtime, "one", resume)

        self.assertEqual(seen["pending"], [])

    async def test_a_cursor_passed_system_only_message_does_not_replay(self):
        self.db._exec("DELETE FROM messages")
        notice = self.db.add_message("line", "system", "system", "service restarted")
        self.db.set_last_seen("one", notice["id"], "owner-1")
        adapter = StagingAdapter("owner-1")
        resume, seen = self._resume(adapter, staged=True)

        await resume_with_backlog(self.runtime, "one", resume)

        self.assertEqual(seen["pending"], [])


class SiblingResumeTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.db = Db(f"{self.directory.name}/partyline.db")
        self.runtime = ChatRuntime(self.db)
        self.db.create_conversation("line", "Line")
        for att_id, name in (("a", "alpha"), ("b", "beta")):
            self.db.add_attachment(att_id, "line", name, "fake", ["fake"], "/tmp", att_id)
            self.db.set_attachment_status(att_id, "exited", att_id)

    async def asyncTearDown(self):
        self.db.close()
        self.directory.cleanup()

    async def _resume(self, att_id):
        adapter = StagingAdapter(att_id)
        observed = {}

        async def resume(_, pending):
            observed["pending"] = pending
            return ResumedAttachment(adapter, True)

        await resume_with_backlog(self.runtime, att_id, resume)
        await drain()
        return [message["body"] for message in observed["pending"]]

    async def test_alpha_speaks_last_then_both_resume_without_each_others_speech(self):
        self.db.add_message("line", "beta", "agent", "beta's earlier update")
        self.db.add_message("line", "alpha", "agent", "alpha speaks last")

        self.assertEqual(await self._resume("a"), [])
        self.assertEqual(await self._resume("b"), [])

    async def test_beta_speaks_last_then_both_resume_without_each_others_speech(self):
        self.db.add_message("line", "alpha", "agent", "alpha's earlier update")
        self.db.add_message("line", "beta", "agent", "beta speaks last")

        self.assertEqual(await self._resume("a"), [])
        self.assertEqual(await self._resume("b"), [])

    async def test_two_siblings_do_not_receive_a_plain_human_message(self):
        self.db.add_message("line", "greg", "human", "anyone seen the notes?")

        self.assertEqual(await self._resume("a"), [])
        self.assertEqual(await self._resume("b"), [])

    async def test_a_finished_process_does_not_get_an_assignment_it_already_answered(self):
        assignment = self.db.add_message("line", "greg", "human", "@alpha please finish")
        self.db.set_last_seen("a", assignment["id"], "a")
        self.db.add_message("line", "alpha", "agent", "finished")

        self.assertEqual(await self._resume("a"), [])

    async def test_a_public_system_notice_mention_is_not_an_instruction_on_resume(self):
        self.db.add_message("line", "system", "system", "⚠ 2 wakes pending for @alpha")
        self.db.add_message("line", "alpha", "agent", "finished")

        self.assertEqual(await self._resume("a"), [])

    async def test_a_forced_worker_pack_rider_is_resume_mail_to_its_named_worker(self):
        self.db.add_message(
            "line",
            "system",
            "system",
            "☏ workers @alpha: opus is now this line's captain — wait for your captain",
        )

        self.assertEqual(
            await self._resume("a"),
            ["☏ workers @alpha: opus is now this line's captain — wait for your captain"],
        )
        self.assertEqual(await self._resume("b"), [])

    async def test_only_the_cut_mid_turn_sibling_gets_a_notice(self):
        self.db._exec("UPDATE attachments SET turn_open=1 WHERE id='a'")
        self.db.add_message("line", "beta", "agent", "hello")

        alpha = await self._resume("a")
        beta = await self._resume("b")

        self.assertEqual(len(alpha), 1)
        self.assertIn("restarted in the middle of a turn", alpha[0])
        self.assertEqual(beta, [])

    async def test_a_sibling_hello_does_not_wake_the_other_process(self):
        class RecordingAdapter:
            def __init__(self, owner):
                self.att = {"runtime_owner": owner}
                self.deliveries = []

            async def deliver(self, messages):
                self.deliveries.extend(messages)

        for att_id in ("a", "b"):
            self.db.set_attachment_status(att_id, "running", att_id)
        alpha, beta = RecordingAdapter("a"), RecordingAdapter("b")
        self.runtime.live.update({"a": alpha, "b": beta})
        hello = self.db.add_message("line", "alpha", "agent", "hello")

        await self.runtime.route_mentions("line", hello)

        self.assertEqual(alpha.deliveries, [])
        self.assertEqual(beta.deliveries, [])

    async def test_resume_delivers_an_unread_message_that_addresses_only_its_recipient(self):
        self.db.add_message("line", "greg", "human", "@beta please continue")

        self.assertEqual(await self._resume("a"), [])
        self.assertEqual(await self._resume("b"), ["@beta please continue"])

    async def test_resume_delivers_an_unread_room_wide_mention_to_both_siblings(self):
        self.db.add_message("line", "greg", "human", "@all please read this")

        self.assertEqual(await self._resume("a"), ["@all please read this"])
        self.assertEqual(await self._resume("b"), ["@all please read this"])

    async def test_a_cursor_passed_human_message_is_replayed_once_to_its_addressee(self):
        message = self.db.add_message("line", "greg", "human", "@alpha pick this up")
        self.db.set_last_seen("a", message["id"], "a")

        replayed = await self._resume("a")

        self.assertEqual(replayed, ["@alpha pick this up"])
        self.assertEqual(self.db.get_attachment("a")["last_seen"], message["id"])

    async def test_a_cursor_passed_human_message_is_not_replayed_to_a_sibling(self):
        message = self.db.add_message("line", "greg", "human", "@alpha pick this up")
        self.db.set_last_seen("b", message["id"], "b")

        self.assertEqual(await self._resume("b"), [])

    async def test_a_private_human_copy_is_never_replayed_to_another_process(self):
        message = self.db.add_message("line", "greg", "human", "@all please read")
        self.db._exec(
            "UPDATE messages SET audience_attachment_id='b' WHERE id=?", (message["id"],)
        )
        self.db.set_last_seen("a", message["id"], "a")
        self.db.set_last_seen("b", message["id"], "b")

        self.assertEqual(await self._resume("a"), [])
        self.assertEqual(await self._resume("b"), ["@all please read"])

    async def test_a_colon_address_replays_only_to_the_named_process(self):
        message = self.db.add_message("line", "greg", "human", "alpha: continue the change")
        self.db.set_last_seen("a", message["id"], "a")
        self.db.set_last_seen("b", message["id"], "b")

        self.assertEqual(await self._resume("a"), ["alpha: continue the change"])
        self.assertEqual(await self._resume("b"), [])

    async def test_past_cursor_all_replays_once_per_resume_until_someone_speaks(self):
        message = self.db.add_message("line", "greg", "human", "@all please continue")
        self.db.set_last_seen("a", message["id"], "a")
        self.db.set_last_seen("b", message["id"], "b")

        self.assertEqual(await self._resume("a"), ["@all please continue"])
        self.assertEqual(await self._resume("b"), ["@all please continue"])
        # An unanswered human request is intentionally replayed once on each resume.
        self.assertEqual(await self._resume("a"), ["@all please continue"])

        self.db.add_message("line", "alpha", "agent", "continuing now")
        self.assertEqual(await self._resume("a"), [])

    async def test_a_later_process_or_human_reply_suppresses_the_replay(self):
        assignment = self.db.add_message("line", "greg", "human", "@alpha please review")
        self.db.set_last_seen("a", assignment["id"], "a")
        self.db.add_message("line", "beta", "agent", "I handled this")
        self.assertEqual(await self._resume("a"), [])

        assignment = self.db.add_message("line", "greg", "human", "@alpha another request")
        self.db.set_last_seen("a", assignment["id"], "a")
        self.db.add_message("line", "greg", "human", "I changed my mind")
        self.assertEqual(await self._resume("a"), [])

    async def test_system_notice_after_human_does_not_hide_replay_or_lower_cursor(self):
        message = self.db.add_message("line", "greg", "human", "@alpha continue")
        self.db.set_last_seen("a", message["id"] + 10, "a")
        self.db.add_message("line", "system", "system", "server restarted")

        self.assertEqual(await self._resume("a"), ["@alpha continue"])
        self.assertEqual(self.db.get_attachment("a")["last_seen"], message["id"] + 10)

    async def test_cut_mid_turn_gets_one_replay_and_one_continue_notice(self):
        message = self.db.add_message("line", "greg", "human", "@alpha finish the edit")
        self.db.set_last_seen("a", message["id"], "a")
        self.db._exec("UPDATE attachments SET turn_open=1 WHERE id='a'")

        backlog = await self._resume("a")

        self.assertEqual(backlog.count("@alpha finish the edit"), 1)
        self.assertEqual(sum("restarted in the middle of a turn" in body for body in backlog), 1)
        self.assertEqual(self.db.get_attachment("a")["last_seen"], max(
            row["id"] for row in self.db.messages_after("line", 0)
        ))
