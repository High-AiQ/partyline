"""A fresh worker's first hello reaches its captain (finding 5.7)."""

import asyncio
import tempfile
import unittest

from partyline.db import Db
from partyline.first_hello import deliver_pending_first_hello, mark_pending
from partyline.runtime import ChatRuntime


class Recorder:
    def __init__(self, attachment):
        self.att = attachment
        self.delivered = []

    async def deliver(self, messages):
        self.delivered.extend(messages)
        return [m["id"] for m in messages]


class FirstHelloTest(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.db = Db(f"{self.directory.name}/partyline.db")
        self.addCleanup(self.db.close)
        self.runtime = ChatRuntime(self.db)
        self.db.create_conversation("line", "Line")
        self.db.add_attachment("cap", "line", "sol", "raw", ["raw"], "/tmp")
        self.db._exec(
            "UPDATE attachments SET is_lead=1, status='running' WHERE id='cap'")
        self.captain_recorder = Recorder(self.db.get_attachment("cap"))
        self.runtime.live["cap"] = self.captain_recorder

    def worker(self, att_id="w1", owner="owner-1"):
        self.db.add_attachment(att_id, "line", "worker", "raw", ["raw"],
                               self.directory.name, owner)
        self.db.set_attachment_status(att_id, "running", owner)
        mark_pending(self.runtime, att_id)

    def hello(self, att_id="w1", body="waiting for your @mention"):
        self.db.add_message("line", "worker", "agent", body)
        return asyncio.run(deliver_pending_first_hello(
            self.runtime, att_id, "worker", body))

    def delivered_bodies(self):
        return [m["body"] for m in self.captain_recorder.delivered]

    def test_first_bare_hello_is_delivered_once_to_the_captain(self):
        self.worker()
        self.assertTrue(self.hello())
        self.assertEqual(len(self.delivered_bodies()), 1)
        self.assertIn("waiting for your @mention", self.delivered_bodies()[0])
        rows = [m for m in self.db.message_page("line", limit=50)[0] if m["sender"] == "worker"]
        self.assertEqual(len(rows), 1)  # woken on its cursor, not shown a second copy
        # the second bare message routes normally: no second copy
        self.assertFalse(self.hello("still standing by"))
        self.assertEqual(len(self.delivered_bodies()), 1)

    def test_a_hello_that_mentions_the_captain_needs_no_copy(self):
        self.worker()
        self.assertFalse(self.hello(body="@sol the lexer tests are done"))
        self.assertEqual(self.delivered_bodies(), [])  # the @mention routes alone

    def test_a_line_without_a_captain_does_nothing_extra(self):
        self.db._exec("UPDATE attachments SET is_lead=0 WHERE id='cap'")
        self.runtime.live.pop("cap")
        self.worker()
        self.assertFalse(self.hello())
        self.assertEqual(self.delivered_bodies(), [])

    def test_a_stale_pending_mark_for_a_gone_attachment_is_harmless(self):
        mark_pending(self.runtime, "ghost")
        self.assertFalse(self.hello())  # nothing crashes on an unknown row

    def test_pending_marks_are_per_activation(self):
        self.worker("w1", "owner-1")
        self.worker("w2", "owner-2")
        self.assertTrue(self.hello("w1"))
        self.assertTrue(self.hello("w2"))  # each activation gets its own hello


if __name__ == "__main__":
    unittest.main()
