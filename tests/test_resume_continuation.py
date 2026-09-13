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
        adapter = StagingAdapter("owner-1")
        resume, seen = self._resume(adapter, staged=True)
        await resume_with_backlog(self.runtime, "one", resume)
        await asyncio.sleep(0)
        self.assertEqual(seen["pending"], [])
