"""Compaction hooks as an adapter capability (finding 2.13).

A Claude Code worker's `PreCompact` hook event becomes a line event with a
persisted counter; three auto compactions within the last five hook turns
ring the line's live captain once. `SessionStart(compact)` GETs a re-briefing
that the harness folds back into the model's context.
"""

import os
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from partyline import auth_store, auth_tokens
from partyline.adapters import ADAPTER_METADATA
from partyline.compaction_events import compaction_count
from partyline.db import Db
from partyline.hook_routes import hooks_router
from partyline.runtime import ChatRuntime


class Recorder:
    def __init__(self, attachment):
        self.att = attachment
        self.delivered = []

    async def deliver(self, messages):
        self.delivered.extend(messages)
        return [m["id"] for m in messages]


def claude_metadata():
    return {"capabilities": {"compaction_hooks": True}}


class CompactionEventsTest(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.db = Db(f"{self.directory.name}/partyline.db")
        self.addCleanup(self.db.close)
        self.runtime = ChatRuntime(self.db)
        metadata = {
            **ADAPTER_METADATA,
            "claude": {"capabilities": {"compaction_hooks": True}},
            "raw": {"capabilities": {}},
        }
        self.metadata_patch = patch.dict(ADAPTER_METADATA, metadata, clear=True)
        self.metadata_patch.start()
        self.addCleanup(self.metadata_patch.stop)
        self.presence = SimpleNamespace(began=AsyncMock(), ended=AsyncMock())
        app = FastAPI()
        from partyline.auth_guard import install_auth_guard

        install_auth_guard(app, self.db)
        app.include_router(hooks_router(self.runtime, self.presence))
        self.client = TestClient(app)
        self.addCleanup(self.client.close)
        self.db.create_conversation("line", "Line")
        self.db.add_attachment("haiku", "line", "haiku", "claude", ["claude"], "/tmp")
        self.db._exec("UPDATE attachments SET status='running' WHERE id='haiku'")
        self.db.add_attachment("cap", "line", "sol", "claude", ["claude"], "/tmp")
        self.db._exec(
            "UPDATE attachments SET is_lead=1, status='running' WHERE id='cap'")
        user = auth_store.create_user(
            self.db, "person@example.com", "person", auth_tokens.hash_password("hunter2222"))
        self.human = {"Authorization": "Bearer " + auth_tokens.create_access_token(
            auth_tokens.signing_secret(self.db), user["id"])}
        self.db._exec("UPDATE attachments SET runtime_owner='owner1' WHERE id='haiku'")
        self.hooks = "/api/hooks/haiku/owner1"
        self.captain_recorder = Recorder(self.db.get_attachment("cap"))
        self.runtime.live["cap"] = self.captain_recorder

    def post_hook(self, body):
        return self.client.post(self.hooks, json=body)

    def compact(self, trigger="auto"):
        return self.post_hook({"hook_event_name": "PreCompact", "trigger": trigger})

    def turn(self):
        return self.post_hook({"hook_event_name": "UserPromptSubmit"})

    def test_the_generated_settings_carry_the_compaction_hooks_only_when_capable(self):
        from partyline.adapters.bundled.claude.adapter import PartylineAdapter

        with_compaction = PartylineAdapter._hook_settings("http://h:1/x/T", True)
        self.assertIn("PreCompact", with_compaction["hooks"])
        self.assertEqual(
            [entry["matcher"] for entry in with_compaction["hooks"]["PreCompact"]],
            ["auto", "manual"])
        session = with_compaction["hooks"]["SessionStart"]
        self.assertEqual([entry["matcher"] for entry in session], ["compact"])
        self.assertIn("/rebrief", session[0]["hooks"][0]["command"])
        self.assertIn("curl", session[0]["hooks"][0]["command"])  # prints to stdout
        without = PartylineAdapter._hook_settings("http://h:1/x/T", False)
        self.assertEqual(
            sorted(without["hooks"]), ["Notification", "Stop", "UserPromptSubmit"])

    def test_a_precompact_post_bumps_the_counter_and_posts_one_notice(self):
        self.assertEqual(self.compact("auto").status_code, 200)
        notices = [m["body"] for m in self.db.list_messages("line") if "compacted" in m["body"]]
        self.assertEqual(notices, ["⚠ @haiku compacted (auto, 1st time)"])
        self.assertEqual(compaction_count(self.db, "haiku"), 1)
        self.assertEqual(self.compact("manual").status_code, 200)
        notices = [m["body"] for m in self.db.list_messages("line") if "compacted" in m["body"]]
        self.assertIn("⚠ @haiku compacted (manual, 2nd time)", notices)
        self.assertEqual(compaction_count(self.db, "haiku"), 2)

    def test_three_auto_compactions_within_five_turns_ring_the_captain_once(self):
        self.turn()
        self.compact("auto")  # turn 1: 1 in window
        self.turn()
        self.compact("auto")  # turn 2: 2 in window, no ring yet
        delivered = [m["body"] for m in self.captain_recorder.delivered]
        self.assertFalse(any("thrashing" in body for body in delivered))
        self.turn()
        self.compact("auto")  # turn 3: 3 in window — the ring
        delivered = [m["body"] for m in self.captain_recorder.delivered]
        self.assertTrue(any("@haiku is thrashing" in body for body in delivered))
        self.turn()
        self.compact("auto")  # turn 4: 4 in window — already rung once
        rings = [m for m in self.captain_recorder.delivered if "thrashing" in m["body"]]
        self.assertEqual(len(rings), 1)

    def test_a_single_compaction_does_not_ring_the_captain(self):
        self.compact("auto")
        self.assertEqual(self.captain_recorder.delivered, [])

    def test_a_worker_without_the_capability_is_not_counted(self):
        raw = "/api/hooks/for-raw/raw-owner"
        self.db.add_attachment("for-raw", "line", "dig", "raw", ["raw"], "/tmp")
        self.db._exec(
            "UPDATE attachments SET status='running', runtime_owner='raw-owner' "
            "WHERE id='for-raw'")
        made = self.client.post(raw, json={"hook_event_name": "PreCompact",
                                           "trigger": "auto"})
        self.assertEqual(made.status_code, 200, made.text)
        self.assertEqual(compaction_count(self.db, "for-raw"), 0)
        self.assertEqual([m for m in self.db.list_messages("line") if "compacted" in m["body"]],
                         [])

    def test_the_rebrief_returns_goal_topic_and_latest_assignment(self):
        from partyline.goal import set_goal

        set_goal(self.db, "line", "ship the parser fix")
        self.db.set_topic("line", "the parser lives in src/parser.py; gates: pytest")
        self.db.add_message("line", "sol", "agent", "@haiku please add tests for the lexer")
        self.db._exec("UPDATE messages SET source_attachment_id='cap' "
                      "WHERE body LIKE '@haiku please add tests%'")
        self.db.add_message("line", "dig", "agent", "@haiku also the readme is stale")
        seen = self.client.get(self.hooks + "/rebrief")
        self.assertEqual(seen.status_code, 200, seen.text)
        self.assertIn("text/plain", seen.headers["content-type"])
        body = seen.text
        self.assertIn("ship the parser fix", body)
        self.assertIn("src/parser.py", body)
        self.assertIn("@haiku please add tests for the lexer", body)  # the captain's, verbatim
        self.assertNotIn("readme is stale", body)  # a sibling worker does not assign
        self.assertIn("you are a worker on a captained line", body)

    def test_the_rebrief_refuses_a_wrong_token_and_an_incapable_adapter(self):
        self.assertEqual(
            self.client.get("/api/hooks/haiku/wrong-token/rebrief").status_code, 404)
        self.db.add_attachment("for-raw", "line", "dig", "raw", ["raw"], "/tmp")
        self.db._exec(
            "UPDATE attachments SET status='running', runtime_owner='raw-owner' "
            "WHERE id='for-raw'")
        self.assertEqual(
            self.client.get("/api/hooks/for-raw/raw-owner/rebrief").status_code, 403)

    def test_a_restart_resets_the_thrash_window_but_not_the_badge(self):
        self.turn()
        self.compact("auto")
        self.turn()
        self.compact("auto")
        self.turn()
        self.compact("auto")  # third in window under owner1: the one ring
        self.assertEqual(len([m for m in self.captain_recorder.delivered
                              if "thrashing" in m["body"]]), 1)
        # restart as owner B: the turn count and the ordinal start over, and
        # owner A's old high-turn events must not read as thrash
        self.db._exec("UPDATE attachments SET runtime_owner='owner2' WHERE id='haiku'")
        self.turn_post = self.client.post("/api/hooks/haiku/owner2",
                                          json={"hookEventName": "UserPromptSubmit"})
        self.assertEqual(self.turn_post.status_code, 200, self.turn_post.text)
        made = self.client.post("/api/hooks/haiku/owner2",
                                json={"hook_event_name": "PreCompact", "trigger": "auto"})
        self.assertEqual(made.status_code, 200)
        notices = [m["body"] for m in self.db.list_messages("line") if "compacted" in m["body"]]
        self.assertIn("⚠ @haiku compacted (auto, 1st time)", notices)  # this activation's 1st
        self.assertEqual(len([m for m in self.captain_recorder.delivered
                              if "thrashing" in m["body"]]), 1)  # still just the one ring
        # the staffing badge keeps the lifetime count across owners
        from partyline.compaction_events import compaction_counts

        self.assertEqual(compaction_counts(self.db).get("haiku"), 4)

    def test_a_captains_rebrief_points_at_the_captain_pack(self):
        from partyline.goal import set_goal

        self.db._exec(
            "UPDATE attachments SET runtime_owner='cap-owner' WHERE id='cap'")
        set_goal(self.db, "line", "review and accept the parser fix")
        self.db.add_message("line", "person", "human", "@sol the parser fix is ready for review")
        seen = self.client.get("/api/hooks/cap/cap-owner/rebrief")
        self.assertEqual(seen.status_code, 200, seen.text)
        body = seen.text
        self.assertIn("(captain pack: GET /api/conversations/line/briefing)", body)
        self.assertNotIn("you are a worker on a captained line", body)
        self.assertIn("@sol the parser fix is ready for review", body)
        self.assertIn("review and accept the parser fix", body)

    def test_importing_the_server_never_cycles_on_the_capability(self):
        # adapter_capabilities imported the adapters package, whose bundled
        # claude adapter imported the helper back from the still-loading
        # module: every import whose first hop went through runtime died.
        # Fresh subprocess, fresh interpreter, both orders.
        import subprocess
        import sys

        for program in (
            "import partyline.adapter_capabilities; import partyline.server",
            "import partyline.server; import partyline.adapter_capabilities",
        ):
            done = subprocess.run(
                [sys.executable, "-c", program], capture_output=True, text=True,
                cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                env={**os.environ, "PARTYLINE_DB": os.path.join(
                    self.directory.name, "cycle-check.db")},
            )
            self.assertEqual(done.returncode, 0, f"{program}:\n{done.stderr}")

    def test_the_schema_migration_runs_twice(self):
        from partyline.compaction_schema import MIGRATIONS as COMPACTION_MIGRATIONS

        for _ in range(2):
            for migration in COMPACTION_MIGRATIONS:
                self.db._exec(migration)
        self.compact("auto")
        self.assertEqual(compaction_count(self.db, "haiku"), 1)


if __name__ == "__main__":
    unittest.main()
