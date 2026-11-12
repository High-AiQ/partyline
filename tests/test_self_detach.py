"""A captain's own detach needs a person behind it; nobody else's detach is gated."""

import tempfile
import unittest

from fastapi import HTTPException

from partyline.auth_guard import Principal
from partyline.db import Db
from partyline.self_detach import asked_self_detach, own


class SelfDetachTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db = Db(f"{self.tmp.name}/partyline.db")
        self.addCleanup(self.db.close)
        self.db._exec("INSERT INTO users(email, handle, password_hash, created_at)"
                      " VALUES('g@x', 'Greg', 'h', 1)")
        self.captain = Principal(kind="machine", name="cap", conv_id="line", attachment_id="cap")

    def test_detaching_someone_else_is_not_a_self_detach(self):
        self.assertFalse(asked_self_detach(self.db, self.captain, "worker", None))
        self.assertFalse(asked_self_detach(self.db, Principal(kind="user", name="greg"), "cap", None))
        self.assertFalse(own(Principal(kind="user", name="greg"), "cap"))

    def test_a_named_person_makes_it_deliberate_and_audited(self):
        with self.assertLogs("partyline.self_detach", level="INFO") as logs:
            self.assertTrue(asked_self_detach(self.db, self.captain, "cap", " @greg "))
        self.assertIn("self-detach attachment=cap told_by=greg", logs.output[0])

    def test_no_person_no_detach(self):
        for told_by in (None, "", "@", "cap", "someone-else"):
            with self.assertRaises(HTTPException) as refused:
                asked_self_detach(self.db, self.captain, "cap", told_by)
            self.assertEqual(refused.exception.status_code, 403)
            self.assertIn("Stay attached", refused.exception.detail)
