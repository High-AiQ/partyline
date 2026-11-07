"""A restart's queued processes are announced, listed and protected from hand restarts."""

import os
import tempfile
import unittest
from unittest.mock import patch

from fastapi import HTTPException

from partyline import resume_folder
from partyline.db import Db
from partyline.orchestrator_contracts import MessageTaskIn
from partyline.orchestrator_handles import message_task
from partyline.orchestrator_share_ref import share_ref
from partyline.reattach_queue import no_live_detail, queued_ids
from partyline.reattach import ReattachCoordinator, ResumedAttachment
from partyline.review_scope import ReviewError
from partyline.runtime import ChatRuntime
from partyline.staffing import staffing_line, staffing_report
from tests.orchestrator_fixture import TaskFixture
from tests.test_reattach import ReadyAdapter


class QueueAnnouncementTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.db = Db(f"{self.directory.name}/partyline.db")
        self.addCleanup(self.db.close)
        self.runtime = ChatRuntime(self.db)
        self.db.save_preset("sol", "sol", "sol", "fake", "fake")
        self.db.create_conversation("owner", "Owner")
        self.db.create_conversation("other", "Other")
        for ident, line, name in (("cap", "owner", "captain"), ("one", "owner", "impl-x"),
                                  ("two", "other", "review-y")):
            self.db.add_attachment(ident, line, name, "fake", ["fake"], self.directory.name)
            self.db.set_attachment_status(ident, "exited", None)
        self.plan = self.db.save_restart_plan("owner", ["cap", "one", "two"], "Continue.")
        self.seen = {}

    def bodies(self, line):
        return "\n".join(row["body"] for row in self.db.messages_after(line, 0))

    async def test_requester_is_told_who_is_queued_and_the_digest_lists_them(self):
        async def resume(attachment_id, _pending):
            name = self.db.get_attachment(attachment_id)["name"]
            if name == "captain":
                self.seen["digest"] = staffing_line(self.db, "owner", runtime=self.runtime)
                self.seen["report"] = staffing_report(self.db, "owner", runtime=self.runtime)
            adapter = ReadyAdapter([], name)
            self.runtime.live[attachment_id] = adapter
            return ResumedAttachment(adapter, False)

        await ReattachCoordinator(self.runtime, resume).run(self.plan, None)

        owner = self.bodies("owner")
        self.assertIn("3 previously attached processes are queued", owner)
        self.assertIn("@impl-x, @review-y «Other»", owner)
        self.assertIn("Do not restart, reattach or re-create them by hand", owner)
        self.assertIn("sequential reattachment finished", owner)
        # The other line hears only of its own process.
        other = self.bodies("other")
        self.assertIn("1 previously attached process is queued", other)
        self.assertIn("@review-y", other)
        self.assertNotIn("impl-x", other.split("Do not restart")[0])
        # The digest is scoped to the asking line's subtree; the report to its subtree too.
        self.assertIn("reattaching (queued): captain «Owner», impl-x «Owner». free",
                      self.seen["digest"])
        self.assertEqual({item["handle"] for item in self.seen["report"]["reattaching"]},
                         {"captain", "impl-x"})
        self.assertEqual(self.seen["report"]["processes"], [])
        # Nothing stays queued once the plan is done.
        self.assertNotIn("reattaching", staffing_line(self.db, "owner", runtime=self.runtime))
        self.assertEqual(staffing_report(self.db, "owner", runtime=self.runtime)["reattaching"], [])


    async def test_idle_captains_receive_the_queue_notice_in_their_continuation(self):
        self.db.add_attachment("cap2", "other", "captain-2", "fake", ["fake"], self.directory.name)
        self.db.set_attachment_status("cap2", "exited", None)
        for ident in ("cap", "cap2"):
            self.db._exec("UPDATE attachments SET is_lead=1 WHERE id=?", (ident,))
        plan = self.db.save_restart_plan("owner", ["cap", "one", "two", "cap2"], "")
        pending, adapters = {}, {}

        async def resume(attachment_id, backlog):
            name = self.db.get_attachment(attachment_id)["name"]
            pending[name] = "\n".join(row["body"] for row in backlog)
            adapter = adapters[name] = ReadyAdapter([], name)
            self.db.set_attachment_status(attachment_id, "running", None)
            self.runtime.live[attachment_id] = adapter
            return ResumedAttachment(adapter, False)

        await ReattachCoordinator(self.runtime, resume).run(plan, None)

        self.assertIn("previously attached processes are queued", pending["captain"])
        self.assertIn("previously attached processes are queued", pending["captain-2"])
        self.assertIn("@review-y", pending["captain-2"])
        self.assertEqual(pending["impl-x"], "")
        self.assertEqual(pending["review-y"], "")
        # The captains were told to wait for the closing notice, so it must wake them
        # without an unrelated mention; workers, who were not told, are left alone.
        for name in ("captain", "captain-2"):
            delivered = [m["body"] for batch in adapters[name].deliveries for m in batch]
            self.assertTrue(any("☏ sequential reattachment finished —" in body for body in delivered),
                            (name, delivered))
        for name in ("impl-x", "review-y"):
            self.assertFalse(any("☏ sequential reattachment finished —" in m["body"]
                                 for batch in adapters[name].deliveries for m in batch))

    async def test_a_worker_whose_resume_failed_is_no_longer_queued(self):
        plan = self.db.save_restart_plan("owner", ["one", "cap"], "Continue.")
        seen = {}

        async def resume(attachment_id, _pending):
            name = self.db.get_attachment(attachment_id)["name"]
            if name == "impl-x":
                raise HTTPException(500, "failed to resume: boom")
            seen["queued"] = queued_ids(self.runtime)
            seen["detail"] = no_live_detail(self.runtime, self.db.get_attachment("one"),
                                            "implementer")
            adapter = ReadyAdapter([], name)
            self.runtime.live[attachment_id] = adapter
            return ResumedAttachment(adapter, False)

        result = await ReattachCoordinator(self.runtime, resume).run(plan, None)

        self.assertEqual(result.failed, ("impl-x",))
        self.assertNotIn("one", seen["queued"])
        self.assertIn("call restart_implementer", seen["detail"])


class QueuedWorkerRefusalTest(TaskFixture):
    def queue_implementer(self):
        ident = self.row()["implementer_id"]
        self.db._exec("UPDATE attachments SET status='exited' WHERE id=?", (ident,))
        self.runtime.live.pop(ident, None)
        self.runtime.reattaching.add(ident)
        self.runtime.restart_plan_order = [ident]
        return ident

    async def test_a_queued_worker_is_told_to_wait_and_a_detached_one_to_restart(self):
        await self.create()
        ident = self.queue_implementer()
        with self.assertRaises(HTTPException) as queued:
            await message_task(self.runtime, self.captain, self.conv_id, MessageTaskIn(text="hi"))
        self.assertIn("queued for automatic reattachment", queued.exception.detail)
        self.assertNotIn("call restart_implementer", queued.exception.detail)
        with self.assertRaises(HTTPException) as shared:
            await share_ref(self.runtime, self.captain, self.conv_id,
                            MessageTaskIn(text="x"))
        self.assertIn("queued for automatic reattachment", shared.exception.detail)
        response = self.client.post(f"/api/conversations/{self.conv_id}/task/implementer")
        self.assertEqual(response.status_code, 409)
        self.assertIn("wait", response.json()["detail"])

        self.runtime.reattaching.discard(ident)  # the plan moved on: truly detached now
        with self.assertRaises(HTTPException) as detached:
            await message_task(self.runtime, self.captain, self.conv_id, MessageTaskIn(text="hi"))
        self.assertIn("call restart_implementer", detached.exception.detail)

    async def test_a_queued_reviewer_is_not_restarted_by_hand(self):
        await self.create()
        self.db._exec("UPDATE task_reviews SET status='in_review',reviewer_id='rev' WHERE conv_id=?",
                      (self.conv_id,))
        self.db.add_attachment("rev", self.conv_id, "review-x", "fake", ["fake"], self.repo)
        self.db.set_attachment_status("rev", "exited", None)
        self.runtime.reattaching.add("rev")
        self.runtime.restart_plan_order = ["rev"]
        response = self.client.post(f"/api/conversations/{self.conv_id}/task/reviewer")
        self.assertEqual(response.status_code, 409, response.text)
        self.assertIn("queued for automatic reattachment", response.json()["detail"])


class ResumeFolderTest(TaskFixture):
    async def reviewer(self, status="in_review"):
        await self.create()
        folder = os.path.join(self.directory.name, "gone")
        self.db._exec("UPDATE task_reviews SET status=?,reviewer_id='rev',sha='abc',"
                      "review_worktree=? WHERE conv_id=?", (status, folder, self.conv_id))
        self.db.add_attachment("rev", self.conv_id, "review-x", "fake", ["fake"], folder)
        return self.db.get_attachment("rev"), folder

    async def test_a_removed_review_checkout_is_recreated_on_resume(self):
        att, folder = await self.reviewer()
        calls = []

        def recreate(db, conv_id, entries, primary):
            calls.append((conv_id, entries, primary))
            os.makedirs(folder)

        with patch.object(resume_folder, "move_task_review_worktrees", recreate):
            resume_folder.ensure_resume_folder(self.db, att)
        self.assertEqual(calls, [(self.conv_id, [("", "abc")], None)])
        resume_folder.ensure_resume_folder(self.db, att)  # present now: nothing to do
        self.assertEqual(len(calls), 1)

    async def test_an_unrecreatable_checkout_fails_with_the_way_forward(self):
        att, folder = await self.reviewer()
        with patch.object(resume_folder, "move_task_review_worktrees",
                          side_effect=ReviewError(400, "no commit abc")):
            with self.assertRaises(HTTPException) as caught:
                resume_folder.ensure_resume_folder(self.db, att)
        self.assertEqual(caught.exception.status_code, 409)
        self.assertIn("no commit abc", caught.exception.detail)
        self.assertIn("request_review", caught.exception.detail)

    async def test_any_other_missing_folder_is_named_not_a_raw_errno(self):
        await self.create()
        att = self.db.get_attachment(self.row()["implementer_id"])
        att["cwd"] = os.path.join(self.directory.name, "vanished")
        with self.assertRaises(HTTPException) as caught:
            resume_folder.ensure_resume_folder(self.db, att)
        self.assertIn("vanished no longer exists", caught.exception.detail)
        att["cwd"] = ""
        resume_folder.ensure_resume_folder(self.db, att)
