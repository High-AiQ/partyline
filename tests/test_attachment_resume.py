"""The server-owned delivery history passed into resumable adapters."""

import tempfile
import unittest

from partyline.attachment_resume import delivered_bodies
from partyline.db import Db


class DeliveredBodiesTest(unittest.TestCase):
    def test_history_belongs_to_one_attachment_lifetime_and_line(self):
        with tempfile.TemporaryDirectory() as directory:
            db = Db(f"{directory}/partyline.db")
            db.create_conversation("line-a", "A")
            db.create_conversation("line-b", "B")
            db.add_message("line-a", "grok", "agent", "from an older attachment")
            attachment = db.add_attachment(
                "att", "line-a", "grok", "grok", ["grok"], directory
            )
            db.add_message("line-a", "grok", "agent", "first")
            db.add_message("line-a", "other", "agent", "not this attachment")
            db.add_message("line-a", "grok", "system", "not agent speech")
            db.add_message("line-b", "grok", "agent", "wrong line")
            db.add_message("line-a", "grok", "agent", "second")

            self.assertEqual(delivered_bodies(db, attachment), ["first", "second"])
            db.close()
