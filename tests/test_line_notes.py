"""Finding 2.13, durable half: the line notebook and its re-briefing."""

import tempfile
import unittest
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from partyline import auth_store, auth_tokens
from partyline.auth_guard import install_auth_guard
from partyline.db import Db
from partyline.line_notes import NOTE_LIMIT, notes_router, write_notes
from partyline.notes_schema import MIGRATIONS as NOTES_MIGRATIONS
from partyline.rebrief import render_rebrief
from partyline.role_briefing import WORKER_REMINDER
from partyline.runtime import ChatRuntime


class LineNotesTest(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.db = Db(f"{self.directory.name}/partyline.db")
        self.addCleanup(self.db.close)
        self.runtime = ChatRuntime(self.db)
        app = FastAPI()
        install_auth_guard(app, self.db)
        app.include_router(notes_router(self.runtime))
        self.client = TestClient(app)
        self.addCleanup(self.client.close)
        self.db.create_conversation("root", "Root")
        self.db.create_conversation("line", "Line")
        self.db._exec("UPDATE conversations SET parent_id='root' WHERE id='line'")
        self.db.add_attachment("cap", "line", "sol", "fake", ["fake"], "/tmp", "o1")
        self.db._exec("UPDATE attachments SET is_lead=1, status='running' WHERE id='cap'")
        self.db.add_attachment("worker", "line", "haiku", "fake", ["fake"], "/tmp", "o2")
        self.db._exec("UPDATE attachments SET status='running' WHERE id='worker'")
        user = auth_store.create_user(
            self.db, "greg@example.com", "greg", auth_tokens.hash_password("hunter2222"))
        self.human = {"Authorization": "Bearer " + auth_tokens.create_access_token(
            auth_tokens.signing_secret(self.db), user["id"])}
        self.captain = {"Authorization": "Bearer " + auth_store.ensure_api_token(
            self.db, "cap")}
        self.worker = {"Authorization": "Bearer " + auth_store.ensure_api_token(
            self.db, "worker")}

    def put(self, scope, notes, headers, attachment_id=""):
        params = {"scope": scope}
        if attachment_id:
            params["attachment_id"] = attachment_id
        return self.client.put("/api/conversations/line/notes", params=params,
                               json={"notes": notes}, headers=headers)

    def get(self, scope, headers, attachment_id=""):
        params = {"scope": scope}
        if attachment_id:
            params["attachment_id"] = attachment_id
        return self.client.get("/api/conversations/line/notes", params=params,
                               headers=headers)

    # -- write permissions -------------------------------------------------

    def test_the_captain_writes_line_notes_and_the_root_captain_writes_tree(self):
        line = self.put("line", "acceptance: 11 tests green", self.captain)
        self.assertEqual(line.status_code, 200, line.text)
        self.assertEqual(self.get("line", self.captain).json()["notes"],
                         "acceptance: 11 tests green")

        self.db.add_attachment("rootcap", "root", "sol", "fake", ["fake"], "/tmp", "o0")
        self.db._exec("UPDATE attachments SET is_lead=1, status='running' WHERE id='rootcap'")
        root_captain = {"Authorization": "Bearer " + auth_store.ensure_api_token(
            self.db, "rootcap")}
        tree = self.put("tree", "main at 9140d4c", root_captain)
        self.assertEqual(tree.status_code, 200, tree.text)
        # tree notes are stored on the root, readable from the child line
        self.assertEqual(self.get("tree", self.captain).json()["notes"], "main at 9140d4c")
        row = self.db._exec("SELECT conv_id FROM line_notes WHERE scope='tree'").fetchone()
        self.assertEqual(row["conv_id"], "root")

    def test_a_sub_captain_cannot_overwrite_the_roots_tree_notes(self):
        # The storage is the root's, so the write permission must be too:
        # otherwise a grandchild's captain could rewrite the root's contracts.
        made = self.put("tree", "hijacked", self.captain)
        self.assertEqual(made.status_code, 403, made.text)

    def test_a_worker_may_write_only_its_own_notes(self):
        own = self.put("attachment", "files touched: calc.py", self.worker)
        self.assertEqual(own.status_code, 200, own.text)

        stolen = self.put("attachment", "not mine", self.worker, attachment_id="cap")
        self.assertEqual(stolen.status_code, 403, stolen.text)

        line = self.put("line", "captain's charge", self.worker)
        self.assertEqual(line.status_code, 403, line.text)
        tree = self.put("tree", "root's charge", self.worker)
        self.assertEqual(tree.status_code, 403, tree.text)

    def test_a_person_writes_all_three_scopes(self):
        for scope in ("line", "tree", "attachment"):
            made = self.put(scope, f"person wrote {scope}", self.human, attachment_id="worker")
            self.assertEqual(made.status_code, 200, made.text)
            read_back = self.get(scope, self.human, attachment_id="worker")
            self.assertEqual(read_back.json()["notes"], f"person wrote {scope}")

    def test_reads_need_only_read_and_default_to_own_notes(self):
        self.put("attachment", "mine", self.worker)
        self.put("line", "the line's", self.captain)

        own_default = self.client.get("/api/conversations/line/notes",
                                      params={"scope": "attachment"}, headers=self.worker)
        self.assertEqual(own_default.json()["notes"], "mine")
        other = self.get("attachment", self.captain, attachment_id="worker")
        self.assertEqual(other.json()["notes"], "mine")

    def test_an_unknown_scope_is_404(self):
        self.assertEqual(self.get("universe", self.human).status_code, 404)

    # -- limits ------------------------------------------------------------

    def test_the_four_thousand_character_cap_holds(self):
        ok = self.put("line", "x" * NOTE_LIMIT, self.human)
        self.assertEqual(ok.status_code, 200, ok.text)
        over = self.put("line", "x" * (NOTE_LIMIT + 1), self.human)
        self.assertEqual(over.status_code, 422, over.text)

    # -- the re-briefing ---------------------------------------------------

    def test_the_rebrief_carries_tree_line_and_own_notes_in_order(self):
        write_notes(self.db, "root", "tree", "contracts: docs/contracts/game.md")
        write_notes(self.db, "line", "line", "acceptance: 11 tests green")
        write_notes(self.db, "line", "attachment",
                    "doing: the notebook; next: wire the rebrief", attachment_id="worker")

        text = render_rebrief(self.db, self.db.get_attachment("worker"))

        tree_at = text.index("Tree notes")
        line_at = text.index("Line notes")
        label_at = text.index("Your own notes:")
        own_at = text.index("doing: the notebook")
        self.assertLess(tree_at, line_at)
        self.assertLess(line_at, label_at)
        self.assertLess(label_at, own_at)

    def test_the_rebrief_stays_within_its_cap_with_full_notes(self):
        write_notes(self.db, "line", "line", "L" * NOTE_LIMIT)
        write_notes(self.db, "line", "attachment", "A" * NOTE_LIMIT, attachment_id="worker")
        write_notes(self.db, "root", "tree", "T" * NOTE_LIMIT)

        text = render_rebrief(self.db, self.db.get_attachment("worker"))

        self.assertLessEqual(len(text), 4000)
        self.assertIn("(notes truncated)", text)
        # the worker reminder survives the truncate: it is the rule that matters
        self.assertIn("edit only on your captain's @mention", text)

    def test_a_huge_topic_cannot_push_out_the_assignment_or_the_reminder(self):
        self.db._exec("UPDATE conversations SET topic=? WHERE id='line'", ("X" * 18000,))
        self.db._exec("UPDATE conversations SET goal=? WHERE id='line'", ("G" * 3000,))
        write_notes(self.db, "line", "line", "L" * NOTE_LIMIT)
        write_notes(self.db, "line", "attachment", "A" * NOTE_LIMIT, attachment_id="worker")
        self.db.add_message("line", "greg", "human", "@haiku ship the notebook slice")

        text = render_rebrief(self.db, self.db.get_attachment("worker"))

        self.assertLessEqual(len(text), 4000)
        self.assertIn("@haiku ship the notebook slice", text)   # the assignment
        self.assertIn("edit only on your captain's @mention", text)  # the reminder
        self.assertIn("(full text: GET /api/conversations/line)", text)  # the pointer

    def test_an_eight_thousand_char_assignment_still_fits_and_ends_with_the_reminder(self):
        # Messages may be 8,000 characters: an unbounded quote is the one part
        # that alone can blow the cap and evict everything after it.
        self.db.add_message("line", "greg", "human", "@haiku " + "W" * 7990)
        write_notes(self.db, "line", "line", "L" * NOTE_LIMIT)
        write_notes(self.db, "line", "attachment", "A" * NOTE_LIMIT, attachment_id="worker")

        text = render_rebrief(self.db, self.db.get_attachment("worker"))

        self.assertLessEqual(len(text), 4000)
        self.assertIn("(truncated — read the line)", text)
        self.assertIn(WORKER_REMINDER, text)  # the reminder survives the cap
        self.assertTrue(text.endswith("notes?scope=attachment"))  # and the nudge rides last

    # -- schema ------------------------------------------------------------

    def test_the_notes_migration_runs_twice(self):
        import sqlite3

        for _ in range(2):
            for mig in NOTES_MIGRATIONS:
                try:
                    self.db.conn.execute(mig)
                except sqlite3.OperationalError:
                    pass  # already applied, exactly as db.py tolerates it
        self.db.conn.commit()
        row = self.db._exec("SELECT COUNT(*) AS n FROM line_notes").fetchone()
        self.assertEqual(row["n"], 0)

    def test_the_rebrief_always_ends_with_the_notes_nudge(self):
        # PreCompact stdout never reaches the model (Claude Code discards it),
        # so the rebriefing is where the worker is told to refresh its notes.
        write_notes(self.db, "line", "attachment", "doing: x", attachment_id="worker")

        text = render_rebrief(self.db, self.db.get_attachment("worker"))

        self.assertIn("Update your attachment notes now", text)
        self.assertIn("PUT $PARTYLINE_API/api/conversations/$PARTYLINE_CONV_ID"
                      "/notes?scope=attachment", text)
        self.assertTrue(text.endswith("notes?scope=attachment"))

    def test_the_nudge_rides_the_wake_every_eight_turns_when_notes_are_stale(self):
        from partyline.line_notes import notes_nudge

        self.assertEqual(notes_nudge(self.db, "line", "worker", 0), "")   # no turns yet
        self.assertEqual(notes_nudge(self.db, "line", "worker", 3), "")   # not a multiple
        write_notes(self.db, "line", "attachment", "doing: x", attachment_id="worker")
        # 8 is a multiple but the notes were just written (turn 0)
        self.assertEqual(notes_nudge(self.db, "line", "worker", 8), "")
        self.db._exec("UPDATE line_notes SET turn=8 WHERE scope='attachment'"
                      " AND attachment_id='worker'")
        self.assertEqual(notes_nudge(self.db, "line", "worker", 8), "")   # fresh
        self.assertEqual(notes_nudge(self.db, "line", "worker", 16), "")  # 16-8 < 16
        nudge = notes_nudge(self.db, "line", "worker", 24)                # 24-8 >= 16
        self.assertIn("Update your attachment notes now", nudge)

    def test_a_worker_that_never_wrote_notes_is_still_nudged(self):
        # Finding 5.1's complaint: the rebriefing carries "whatever the worker
        # last wrote, often nothing". No row at all is the stalest case.
        from partyline.line_notes import notes_nudge

        nudge = notes_nudge(self.db, "line", "worker", 16)  # a multiple, nothing written

        self.assertIn("Update your attachment notes now", nudge)

    def test_the_stale_turns_threshold_is_a_setting(self):
        from partyline.line_notes import notes_nudge

        write_notes(self.db, "line", "attachment", "doing: x", attachment_id="worker")
        self.db.set_setting("notes_stale_turns", "4")
        self.db._exec("UPDATE line_notes SET turn=8 WHERE scope='attachment'"
                      " AND attachment_id='worker'")

        self.assertEqual(notes_nudge(self.db, "line", "worker", 8), "")  # 8-8 < 4
        nudge = notes_nudge(self.db, "line", "worker", 16)  # 16-8 >= 4, and 16%8==0

        self.assertIn("Update your attachment notes now", nudge)

    def test_a_self_write_records_the_harness_turn(self):
        # The route stamps the writer's own turn so staleness is measurable.
        from partyline.compaction_events import bump_turn
        from partyline.line_notes import read_notes

        for _ in range(5):
            bump_turn(self.db, "worker", "owner")
        made = self.put("attachment", "files touched: calc.py", self.worker)

        self.assertEqual(made.status_code, 200, made.text)
        row = self.db._exec("SELECT turn FROM line_notes WHERE scope='attachment'"
                            " AND attachment_id='worker'").fetchone()
        self.assertEqual(row["turn"], 5)
        self.assertEqual(read_notes(self.db, "line", "attachment", "worker")["notes"],
                         "files touched: calc.py")

    def test_the_worker_rider_carries_the_nudge_when_notes_go_stale(self):
        from partyline.compaction_events import bump_turn
        from partyline.role_delivery import RoleState, bind_role_delivery

        worker = RoleState("participant", "line", "root", ("read", "write"),
                           captained=True)
        att = {"id": "worker", "digest_rider": lambda: "board"}
        for _ in range(16):
            bump_turn(self.db, "worker", "o2")
        with patch("partyline.role_delivery.current_role", return_value=worker):
            bind_role_delivery(self.db, att)
            ride = att["digest_rider"]()
        self.assertIn("Update your attachment notes now", ride)
        self.assertIn(WORKER_REMINDER, ride)  # the reminder rides with it


if __name__ == "__main__":
    unittest.main()
