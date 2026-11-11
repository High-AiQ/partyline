"""A resume drops notices whose state is already resolved and keeps live ones."""

import tempfile
import unittest

from partyline import reports
from partyline.db import Db
from partyline.resolved_notices import tag_memory_notice
from partyline.resume_backlog import addressed_backlog
from partyline.runtime import ChatRuntime

GIB = 1024**3


class ResolvedNoticesTest(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.db = Db(f"{self.directory.name}/partyline.db")
        self.runtime = ChatRuntime(self.db)
        self.db.create_conversation("root", "Root")
        self.db.create_conversation("kid", "Kid")
        self.db.add_attachment("cap", "root", "lead", "fake", ["fake"], "/tmp", "o1")
        self.db.add_attachment("wk", "kid", "worker", "fake", ["fake"], "/tmp", "o2")

    def tearDown(self):
        self.db.close()
        self.directory.cleanup()

    def private(self, conv, body, audience):
        message = self.db.add_message(conv, "system", "system", body)
        self.db._exec("UPDATE messages SET audience_attachment_id=? WHERE id=?",
                      (audience, message["id"]))
        return message["id"]

    def backlog_ids(self, att_id="cap"):
        return [m["id"] for m in addressed_backlog(self.runtime, self.db.get_attachment(att_id))]

    def memory_notice(self, cap):
        mid = self.private("root", "⚠ lead, you are using 4.2 GiB of 4.0 GiB", "cap")
        tag_memory_notice(self.db, mid, "cap", cap)
        return mid

    def test_memory_warning_dropped_once_the_cap_was_raised(self):
        mid = self.memory_notice(4 * GIB)
        self.assertIn(mid, self.backlog_ids())
        self.db._exec("UPDATE attachments SET memory_limit='12G' WHERE id='cap'")
        self.assertNotIn(mid, self.backlog_ids())

    def test_memory_warning_dropped_when_usage_no_longer_crosses(self):
        mid = self.memory_notice(4 * GIB)
        self.runtime.memory_usage["cap"] = {"usage_bytes": GIB, "cap_bytes": 4 * GIB}
        self.assertNotIn(mid, self.backlog_ids())

    def test_memory_warning_kept_while_still_over_the_threshold(self):
        mid = self.memory_notice(4 * GIB)
        self.runtime.memory_usage["cap"] = {"usage_bytes": 4 * GIB, "cap_bytes": 4 * GIB}
        self.assertIn(mid, self.backlog_ids())

    def test_report_wake_dropped_when_acknowledged(self):
        row, _ = reports.add(self.db, "root", "kid", "w", "done", notify=True)
        mid = self.private("root", f"@lead needs attention: report {row['id']}", "cap")
        self.assertIn(mid, self.backlog_ids())
        reports.acknowledge(self.db, row["id"], "root", row["revision"])
        self.assertNotIn(mid, self.backlog_ids())

    def test_older_wake_for_the_same_report_is_superseded(self):
        row, _ = reports.add(self.db, "root", "kid", "w", "done", notify=True)
        old = self.private("root", f"@lead needs attention: report {row['id']}", "cap")
        new = self.private("root", f"@lead needs attention: report {row['id']}", "cap")
        self.assertEqual(self.backlog_ids(), [new])
        self.assertNotIn(old, self.backlog_ids())

    def test_delivered_then_answered_question_is_dropped(self):
        answered = self.db.add_message("root", "boris", "agent", "@lead which branch?")
        self.db.set_last_seen("cap", answered["id"], "o1")
        self.db.add_message("root", "lead", "agent", "@boris use main")
        self.assertNotIn(answered["id"], self.backlog_ids())

    def test_reply_does_not_answer_unproved_mail(self):
        message = self.db.add_message("root", "boris", "agent", "@lead which branch?")
        self.db.add_message("root", "lead", "agent", "@boris which option?")
        self.assertIn(message["id"], self.backlog_ids())
