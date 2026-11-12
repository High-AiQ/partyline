"""A resumed process is pasted what its kept session does not provably hold, in full, with a pointer."""

import asyncio
import json
import os
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from partyline.adapters.bundled.opencode.seen import seen_ids
from partyline.db import Db
from partyline.resume_replay import READ_PAGE, for_resume


def messages(count, size=400, start=1):
    return [{"id": start + index, "conv_id": "line", "sender": "cap", "sender_type": "agent",
             "body": f"{index:03d} " + "x" * size} for index in range(count)]


class ReplayTest(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.db = Db(os.path.join(self.directory.name, "x.db"))
        self.addCleanup(self.db.close)
        self.db.create_conversation("line", "line")
        self.db.add_attachment("me", "line", "impl", "opencode-v2", ["run"], "/tmp")
        self.db._exec("UPDATE attachments SET runtime_owner='old', cli_session='ses' WHERE id='me'")
        self.att = {**self.db.get_attachment("me")}
        self.runtime = type("R", (), {"db": self.db})()
        self.store = Path(self.directory.name) / "opencode.db"

    def session(self, lines, session="ses"):
        db = sqlite3.connect(self.store)
        db.execute("CREATE TABLE IF NOT EXISTS session_message"
                   "(id TEXT, session_id TEXT, seq INT, type TEXT, data TEXT)")
        for index, line in enumerate(lines):
            db.execute("INSERT INTO session_message VALUES(?,?,?,?,?)",
                       (f"m{index}", session, index, "user", json.dumps({"text": line})))
        db.commit()
        db.close()

    def test_what_the_kept_session_holds_is_not_replayed_and_the_cursor_follows(self):
        pending = messages(6)
        self.session([f"[cap]: {m['body']}" for m in pending[:4]])
        with patch("partyline.adapters.bundled.opencode.seen.store_path", lambda _att: self.store):
            replay = asyncio.run(for_resume(self.runtime, self.att, pending))
        note, rest = replay[0], replay[1:]
        self.assertEqual([m["id"] for m in rest], [5, 6])
        self.assertEqual(note["id"], 4)  # the receipt counts the skipped, provably-seen run
        self.assertIn("4 earlier message(s)", note["body"])
        self.assertIn(f"read_messages(after_id=0, limit={READ_PAGE})", note["body"])
        self.assertIn("repeat with after_id set to the last id returned", note["body"])
        self.assertEqual(self.db.get_attachment("me")["last_seen"], 4)

    def test_a_gap_in_what_is_seen_credits_only_the_unbroken_run(self):
        pending = messages(5)
        self.session([f"[cap]: {pending[index]['body']}" for index in (0, 1, 3)])
        with patch("partyline.adapters.bundled.opencode.seen.store_path", lambda _att: self.store):
            replay = asyncio.run(for_resume(self.runtime, self.att, pending))
        self.assertEqual([m["id"] for m in replay if m["sender_type"] != "system"], [3, 5])
        self.assertEqual(self.db.get_attachment("me")["last_seen"], 2)  # the unbroken seen run only

    def test_a_repeated_line_hides_only_as_many_messages_as_the_session_holds(self):
        twice = [{**m, "body": "continue"} for m in messages(2)]
        self.session(["[cap]: continue"])
        self.assertEqual(seen_ids(self.att, twice, self.store), {1})

    def test_any_failure_to_read_the_session_replays_everything(self):
        pending = messages(2)
        self.assertEqual(seen_ids(self.att, pending, Path(self.directory.name) / "missing.db"), set())
        self.assertEqual(seen_ids({**self.att, "cli_session": ""}, pending, self.store), set())
        with patch("partyline.adapters.bundled.opencode.seen.store_path", lambda _att: None):
            self.assertEqual([m["id"] for m in asyncio.run(for_resume(self.runtime, self.att, pending))],
                             [1, 2])

    def test_a_longer_line_that_starts_the_same_does_not_hide_a_new_message(self):
        # The reviewer's repro: the session holds two other digests; none of these was pasted.
        pending = [{**messages(1)[0], "id": 10, "sender": "greg", "body": "yes"},
                   {**messages(1)[0], "id": 11, "sender": "greg", "body": "y"},
                   {**messages(1)[0], "id": 12, "sender": "cap", "body": "@impl-x stop"}]
        self.session(["[greg]: yes", "[cap]: @impl-x stop: the plan changed, do not continue"])
        self.assertEqual(seen_ids(self.att, pending, self.store), {10})  # whole-line "yes" only

    def test_a_multiline_body_must_match_whole_not_by_its_first_line(self):
        pending = [{**messages(1)[0], "id": 3, "body": "plan\nstep two"}]
        self.session(["[cap]: plan\nstep three"])
        self.assertEqual(seen_ids(self.att, pending, self.store), set())
        self.session(["[cap]: plan\nstep two\n(cwd git: abc clean)"])
        self.assertEqual(seen_ids(self.att, pending, self.store), {3})

    def test_a_line_pasted_before_the_cursor_does_not_hide_a_new_identical_one(self):
        old = {**messages(1)[0], "id": 4, "sender": "greg", "body": "yes"}
        new = {**messages(1)[0], "id": 9, "sender": "greg", "body": "yes"}
        self.session(["[greg]: yes", "[cap]: other"])
        credited = [{**old, "id": 1}]
        self.assertEqual(seen_ids(self.att, [new], self.store, credited), set())
        # A later "yes" is indistinguishable from the credited one, so the window starts after it:
        # replaying is the safe direction. Anything pasted after the credited paste is seen.
        self.session(["[greg]: yes", "[cap]: other", "[greg]: yes"], session="ses2")
        att = {**self.att, "cli_session": "ses2"}
        self.assertEqual(seen_ids(att, [new], self.store, credited), set())
        later = {**messages(1)[0], "id": 9, "body": "other"}
        self.assertEqual(seen_ids(self.att, [later], self.store, credited), {9})

    def test_a_credited_paste_that_cannot_be_found_vouches_for_nothing(self):
        pending = messages(2)
        self.session([f"[cap]: {m['body']}" for m in pending])
        gone = [{**messages(1)[0], "id": 1, "body": "never in this session"}]
        self.assertEqual(seen_ids(self.att, pending, self.store, gone), set())

    def test_for_resume_anchors_on_the_credited_tail_from_the_database(self):
        first = self.db.add_message("line", "greg", "human", "yes")
        self.db._exec("UPDATE attachments SET last_seen=? WHERE id='me'", (first["id"],))
        att = {**self.db.get_attachment("me")}
        second = self.db.add_message("line", "greg", "human", "yes")
        self.session(["[greg]: yes"])  # only the credited paste is in the session
        with patch("partyline.adapters.bundled.opencode.seen.store_path", lambda _att: self.store):
            replay = asyncio.run(for_resume(self.runtime, att, [second]))
        self.assertEqual([m["id"] for m in replay], [second["id"]])
        self.assertEqual(self.db.get_attachment("me")["last_seen"], first["id"])

    def test_a_cursor_with_no_findable_credited_message_vouches_for_nothing(self):
        old = self.db.add_message("line", "cap", "agent", "[greg]: yes")  # not addressed to "me"
        self.db._exec("UPDATE messages SET audience_attachment_id='someone-else' WHERE id=?", (old["id"],))
        self.db._exec("UPDATE attachments SET last_seen=? WHERE id='me'", (old["id"],))
        att = {**self.db.get_attachment("me")}
        new = {**messages(1)[0], "id": old["id"] + 1, "sender": "greg", "body": "yes"}
        self.session(["[greg]: yes"])  # an old identical line sits in the session
        with patch("partyline.adapters.bundled.opencode.seen.store_path", lambda _att: self.store):
            replay = asyncio.run(for_resume(self.runtime, att, [new]))
        self.assertEqual([m["id"] for m in replay], [new["id"]])
        self.assertEqual(self.db.get_attachment("me")["last_seen"], old["id"])

    def test_a_fresh_instance_without_the_kept_session_gets_the_full_replay(self):
        pending = messages(30)
        # The previous instance's session still exists in the store; the new one has no claim on it.
        self.session([f"[cap]: {m['body']}" for m in pending], session="ses")
        for cleared in (None, ""):
            with self.subTest(cli_session=cleared):
                att = {**self.att, "cli_session": cleared}
                with patch("partyline.adapters.bundled.opencode.seen.store_path",
                           lambda _att: self.store):
                    replay = asyncio.run(for_resume(self.runtime, att, pending))
                self.assertEqual(replay, pending)
                self.assertEqual(self.db.get_attachment("me")["last_seen"], 0)

    def test_another_adapter_is_left_unchanged(self):
        att = {**self.att, "adapter": "codex"}
        pending = messages(3)
        self.session([f"[cap]: {m['body']}" for m in pending])
        with patch("partyline.adapters.bundled.opencode.seen.store_path", lambda _att: self.store):
            self.assertEqual(asyncio.run(for_resume(self.runtime, att, pending)), pending)


if __name__ == "__main__":
    unittest.main()
