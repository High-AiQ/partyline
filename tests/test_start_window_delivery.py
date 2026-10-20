"""A message addressed to a process while it is still starting is not lost."""

import tempfile
import unittest

from partyline.attachment_start import deliver_since_attach
from partyline.db import Db
from partyline.runtime import ChatRuntime


class Recorder:
    def __init__(self, attachment):
        self.att = attachment
        self.delivered = []

    async def deliver(self, messages):
        self.delivered.extend(messages)
        return [m["id"] for m in messages]


class StartWindowTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.db = Db(f"{self.directory.name}/partyline.db")
        self.addCleanup(self.db.close)
        self.runtime = ChatRuntime(self.db)
        self.db.create_conversation("line", "Line")
        self.db.add_message("line", "greg", "human", "old history before the attach")
        self.att = self.db.add_attachment("w", "line", "worker", "raw", ["raw"], "/tmp", "owner",
                                          start_after_history=True)
        self.runtime.live["w"] = Recorder(self.att)

    def bodies(self):
        return [m["body"] for m in self.runtime.live["w"].delivered]

    def notices(self):
        return [m["body"] for m in self.db.message_page("line", limit=50)[0]
                if m["sender_type"] == "system"]

    async def test_assignment_posted_while_starting_arrives_once_after_ready(self):
        await self.runtime.post_message("line", "sol", "agent", "@worker build the thing")
        self.assertEqual(self.bodies(), [])
        self.assertFalse([n for n in self.notices() if "not attached" in n])
        self.db.set_attachment_status("w", "running", "owner")
        self.runtime.live["w"].att = self.db.get_attachment("w")
        await deliver_since_attach(self.runtime, "w")
        self.assertEqual(self.bodies().count("@worker build the thing"), 1)
        self.assertNotIn("old history before the attach", self.bodies())
        await deliver_since_attach(self.runtime, "w")
        self.assertEqual(self.bodies().count("@worker build the thing"), 1)


if __name__ == "__main__":
    unittest.main()
