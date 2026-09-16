"""Which lines have a captain, by the live lead row and not the stale flag."""

import tempfile
import unittest

from partyline.db import Db
from partyline.hierarchy import set_lead
from partyline.line_depth import has_captain


class HasCaptainTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.db = Db(f"{self.directory.name}/partyline.db")
        self.addCleanup(self.db.close)
        self.db.create_conversation("line", "Line")
        self.db.add_attachment("lead", "line", "lead", "fake", ["fake"], "/tmp", "own")
        self.db.set_attachment_status("lead", "running", "own")

    def test_no_lead_means_no_captain(self):
        self.assertFalse(has_captain(self.db, "line"))

    def test_a_starting_or_running_lead_is_the_captain(self):
        set_lead(self.db, "line", "lead")
        for status in ("starting", "running"):
            with self.subTest(status):
                self.db.set_attachment_status("lead", status, "own")
                self.assertTrue(has_captain(self.db, "line"))

    def test_a_lead_that_exited_or_detached_no_longer_counts(self):
        set_lead(self.db, "line", "lead")
        self.assertTrue(has_captain(self.db, "line"))
        for status in ("exited", "detached"):
            with self.subTest(status):
                self.db.set_attachment_status("lead", status, "own")
                self.assertTrue(self.db.get_attachment("lead")["is_lead"])
                self.assertFalse(has_captain(self.db, "line"))
                self.db.set_attachment_status("lead", "running", "own")
