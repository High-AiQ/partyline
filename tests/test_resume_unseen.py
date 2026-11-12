"""A message not provably in the kept session is always pasted, in full, oldest first, and the
cursor never passes an undelivered one (the resume bound once dropped 5 of 15 assigned messages)."""

import asyncio
import json
import os
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from partyline.db import Db
from partyline.delivery_credit_accounting import confirm_reserved
from partyline.notice_policy import digest_candidates
from partyline.resume_backlog import addressed_backlog
from partyline.resume_replay import for_resume
from partyline.runtime import ChatRuntime

STORE = "partyline.adapters.bundled.opencode.seen.store_path"


class UnseenResumeTest(unittest.TestCase):
    CREDIT = True

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.db = Db(os.path.join(self.directory.name, "x.db"))
        self.addCleanup(self.db.close)
        self.runtime = ChatRuntime(self.db)
        self.db.create_conversation("line", "Line")
        self.db.add_attachment("cap", "line", "cap", "fake", ["fake"], "/tmp", "co")
        if self.CREDIT:  # the mechanism under test; production keeps it off
            credit = patch("partyline.resume_replay.CREDIT_KEPT_SESSION", True)
            credit.start()
            self.addCleanup(credit.stop)

    def worker(self, adapter):
        self.db.add_attachment("w", "line", "worker", adapter, ["x"], "/tmp", "wo")
        self.db._exec("UPDATE attachments SET status='exited', cli_session='ses' WHERE id='w'")
        return self.db.get_attachment("w")

    def say(self, count):
        ids = [self.db.add_message("line", "cap", "agent",
                                   (f"@worker ASSIGNMENT: build the importer. {'detail ' * 110}" if not n
                                    else f"@worker follow-up {n}: {'note ' * 150}"))["id"]
               for n in range(count)]
        return ids

    def session(self, lines):
        path = Path(self.directory.name) / "opencode.db"
        db = sqlite3.connect(path)
        db.execute("CREATE TABLE session_message(id TEXT, session_id TEXT, seq INT, type TEXT, data TEXT)")
        for index, line in enumerate(lines):
            db.execute("INSERT INTO session_message VALUES(?,?,?,?,?)",
                       (f"m{index}", "ses", index, "user", json.dumps({"text": line})))
        db.commit()
        db.close()
        return path

    def test_fifteen_unseen_messages_are_all_pasted_oldest_first_on_every_adapter(self):
        for adapter in ("claude", "codex", "opencode-v2"):
            with self.subTest(adapter=adapter):
                self.setUp()
                att = self.worker(adapter)
                ids = self.say(15)
                backlog = addressed_backlog(self.runtime, att)
                self.assertGreater(sum(len(m["body"]) for m in backlog), 11_000)
                with patch(STORE, lambda _att: None):  # nothing provably seen
                    replay = asyncio.run(for_resume(self.runtime, att, backlog))
                self.assertEqual([m["id"] for m in replay], ids)
                self.assertTrue(replay[0]["body"].startswith("@worker ASSIGNMENT"))
                self.db._exec("UPDATE attachments SET status='running' WHERE id='w'")
                confirm_reserved(self.runtime, "w", [m["id"] for m in replay], "wo")
                row = self.db.get_attachment("w")
                self.assertEqual(row["last_seen"], ids[-1])
                self.assertEqual(digest_candidates(self.db, "line", row["last_seen"], "worker", "w"), [])
                self.db.close()
                self.directory.cleanup()

    def test_interleaved_seen_and_unseen_pastes_every_unseen_and_credits_only_the_unbroken_run(self):
        att = self.worker("opencode-v2")
        ids = self.say(8)
        backlog = addressed_backlog(self.runtime, att)
        held = {0, 1, 3, 5}  # indexes the session holds
        store = self.session([f"[cap]: {backlog[i]['body']}" for i in sorted(held)])
        with patch(STORE, lambda _att: store):
            replay = asyncio.run(for_resume(self.runtime, att, backlog))
        note, pasted = replay[0], replay[1:]
        self.assertEqual([m["id"] for m in pasted], [ids[i] for i in range(8) if i not in held])
        self.assertEqual(note["sender_type"], "system")
        self.assertIn("4 earlier message(s)", note["body"])
        self.assertEqual(self.db.get_attachment("w")["last_seen"], ids[1])  # 0 and 1 only
        self.db._exec("UPDATE attachments SET status='running' WHERE id='w'")
        confirm_reserved(self.runtime, "w", [m["id"] for m in replay], "wo")
        row = self.db.get_attachment("w")
        self.assertEqual(row["last_seen"], ids[-1])  # after the paste, all delivered or provably seen
        self.assertEqual(digest_candidates(self.db, "line", row["last_seen"], "worker", "w"), [])


class ShippedResumeTest(UnseenResumeTest):
    """As shipped, the kept session vouches for nothing: every pending message is pasted."""

    CREDIT = False
    test_interleaved_seen_and_unseen_pastes_every_unseen_and_credits_only_the_unbroken_run = None

    def test_a_message_that_opens_like_an_earlier_longer_one_is_pasted_not_credited(self):
        """The text proof took "rebase onto main" for the first line of a longer message the
        session held, credited it unpasted and moved the cursor past it (review of #507)."""
        att = self.worker("opencode-v2")
        ids = [self.db.add_message("line", "cap", "agent", body)["id"] for body in (
            "@worker rebase onto main\n\nDetails: keep the merge commit.",
            "@worker rebase onto main",
            "@worker and run the gates afterwards")]
        backlog = addressed_backlog(self.runtime, att)
        store = self.session([f"[cap]: {backlog[0]['body']}"])  # pasted once, its proof lost
        with patch(STORE, lambda _att: store):
            replay = asyncio.run(for_resume(self.runtime, att, backlog))
        self.assertEqual([m["id"] for m in replay], ids)
        self.assertEqual(self.db.get_attachment("w")["last_seen"], 0)


if __name__ == "__main__":
    unittest.main()
