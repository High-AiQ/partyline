"""A resumed process is pasted only what its kept session lacks, bounded, with a pointer."""

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
from partyline.resume_replay import REPLAY_CHARS, bound, for_resume


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

    def test_a_short_backlog_is_unchanged(self):
        short = messages(3)
        self.assertEqual(bound(self.att, short), short)

    def test_a_long_backlog_keeps_the_newest_and_points_at_read_messages(self):
        long = messages(40)
        replay = bound(self.att, long)
        self.assertEqual(replay[-1], long[-1])
        note, kept = replay[0], replay[1:]
        self.assertLessEqual(sum(len(m["body"]) for m in kept), REPLAY_CHARS)
        self.assertEqual(kept, long[len(long) - len(kept):])
        omitted = len(long) - len(kept)
        self.assertIn(f"{omitted} earlier message(s)", note["body"])
        self.assertIn(f"read_messages(after_id={long[0]['id'] - 1}, limit=50)", note["body"])
        self.assertEqual(note["id"], long[omitted - 1]["id"])  # the cursor counts it as pasted
        self.assertEqual(note["audience_attachment_id"], "me")

    def test_one_message_over_the_bound_is_still_delivered(self):
        giant = messages(1, size=REPLAY_CHARS * 2)
        self.assertEqual(bound(self.att, giant), giant)

    def test_what_the_kept_session_holds_is_not_replayed_and_the_cursor_follows(self):
        pending = messages(6)
        self.session([f"[cap]: {m['body']}" for m in pending[:4]])
        with patch("partyline.adapters.bundled.opencode.seen.store_path", lambda _att: self.store):
            replay = asyncio.run(for_resume(self.runtime, self.att, pending))
        self.assertEqual([m["id"] for m in replay], [5, 6])
        self.assertEqual(self.db.get_attachment("me")["last_seen"], 4)

    def test_a_gap_in_what_is_seen_credits_only_the_unbroken_run(self):
        pending = messages(5)
        self.session([f"[cap]: {pending[index]['body']}" for index in (0, 1, 3)])
        with patch("partyline.adapters.bundled.opencode.seen.store_path", lambda _att: self.store):
            replay = asyncio.run(for_resume(self.runtime, self.att, pending))
        self.assertEqual([m["id"] for m in replay], [3, 5])
        self.assertEqual(self.db.get_attachment("me")["last_seen"], 2)

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

    def test_a_fresh_instance_without_the_kept_session_gets_the_full_bounded_replay(self):
        pending = messages(30)
        # The previous instance's session still exists in the store; the new one has no claim on it.
        self.session([f"[cap]: {m['body']}" for m in pending], session="ses")
        for cleared in (None, ""):
            with self.subTest(cli_session=cleared):
                att = {**self.att, "cli_session": cleared}
                with patch("partyline.adapters.bundled.opencode.seen.store_path",
                           lambda _att: self.store):
                    replay = asyncio.run(for_resume(self.runtime, att, pending))
                self.assertEqual(replay, bound(att, pending))
                self.assertEqual(replay[-1]["id"], 30)
                self.assertIn("read_messages(after_id=", replay[0]["body"])
                self.assertEqual(self.db.get_attachment("me")["last_seen"], 0)

    def test_another_adapter_is_only_bounded(self):
        att = {**self.att, "adapter": "codex"}
        pending = messages(3)
        self.session([f"[cap]: {m['body']}" for m in pending])
        with patch("partyline.adapters.bundled.opencode.seen.store_path", lambda _att: self.store):
            self.assertEqual(asyncio.run(for_resume(self.runtime, att, pending)), pending)


if __name__ == "__main__":
    unittest.main()
