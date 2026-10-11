"""Replace a process with a fresh instance of itself (finding 2.8)."""

import asyncio
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from partyline import auth_store, auth_tokens
from partyline.adapters import ADAPTER_METADATA
from partyline.attachment_lifecycle_routes import register_attachment_lifecycle_routes
from partyline.auth_guard import install_auth_guard
from partyline.compaction_events import note_hook_compaction
from partyline.db import Db
from partyline.line_notes import write_notes
from partyline.runtime import ChatRuntime


class Recorder:
    def __init__(self, attachment):
        self.att = attachment
        self.delivered = []

    async def deliver(self, messages):
        self.delivered.extend(messages)
        return [m["id"] for m in messages]


class ReplaceAttachmentTest(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.db = Db(f"{self.directory.name}/test.db")
        self.runtime = ChatRuntime(self.db)
        self.runtime.broadcast = AsyncMock()
        self.spawned = []
        self.validation = Mock()
        self.loopback = Mock()
        app = FastAPI()
        install_auth_guard(app, self.db)
        register_attachment_lifecycle_routes(
            app, self.runtime, start=self.start, require_loopback=self.loopback,
            validate=self.validation,
        )
        self.client = TestClient(app)
        self.addCleanup(self.client.close)
        self.db.create_conversation("line", "Line")
        user = auth_store.create_user(
            self.db, "greg@example.com", "greg", auth_tokens.hash_password("hunter2222"))
        token = auth_tokens.create_access_token(auth_tokens.signing_secret(self.db), user["id"])
        self.human = {"Authorization": f"Bearer {token}"}
        self.client.headers.update(self.human)
        self.db.add_attachment("old", "line", "worker", "raw", ["sh"],
                               self.directory.name, "owner-old")
        self.db.set_attachment_status("old", "detached", "owner-old")
        self.captain_token = self.lead("cap", "sol")
        self.captain_recorder = Recorder(self.db.get_attachment("cap"))
        self.runtime.live["cap"] = self.captain_recorder

    def lead(self, att_id, name):
        self.db.add_attachment(att_id, "line", name, "raw", ["sh"], self.directory.name)
        self.db._exec("UPDATE attachments SET is_lead=1, status='running' WHERE id=?", (att_id,))
        return {"Authorization": "Bearer " + auth_store.ensure_api_token(self.db, att_id)}

    def worker_token(self, att_id, name, owner):
        self.db.add_attachment(att_id, "line", name, "raw", ["sh"], self.directory.name, owner)
        self.db.set_attachment_status(att_id, "running", owner)
        return {"Authorization": "Bearer " + auth_store.ensure_api_token(self.db, att_id)}

    async def start(self, att, **kwargs):
        if getattr(self, "start_failure", False):
            raise RuntimeError("spawn failed")
        self.spawned.append(dict(att, **kwargs))
        return att

    def replace(self, body=None, att_id="old", headers=None):
        payload = {"reason": "thrashing on compaction"} if body is None else body
        return self.client.post(f"/api/attachments/{att_id}/replace",
                                json=payload, headers=headers)

    def test_replace_makes_a_fresh_same_handle_record_and_removes_the_old(self):
        self.db.set_cli_session("old", "previous-cli-session", "owner-old")
        response = self.replace()
        self.assertEqual(response.status_code, 200, response.text)
        new = response.json()
        self.assertNotEqual(new["id"], "old")
        self.assertEqual(new["name"], "worker")
        self.assertEqual(new["cwd"], self.directory.name)
        self.assertIsNone(new["cli_session"])  # a new session, never a resume
        self.assertIsNone(self.db.get_attachment("old"))
        # the fresh session started with the re-briefing as its checkpoint
        checkpoint = self.spawned[-1].get("checkpoint") or ""
        self.assertIn("@worker", checkpoint)

    def test_a_failed_start_leaves_the_captain_in_place(self):
        # the captain replaces itself and the start fails: the old row must
        # keep the lead flag, or the line is left with no captain at all
        self.db._exec("UPDATE attachments SET runtime_owner='cap-owner', "
                      "status='detached' WHERE id='cap'")
        self.runtime.live.pop("cap")
        headers = {"Authorization": "Bearer " + auth_store.ensure_api_token(self.db, "cap")}
        self.start_failure = True
        failed = self.replace(att_id="cap",
                              body={"reason": "thrashing on compaction"}, headers=headers)
        self.assertEqual(failed.status_code, 500, failed.text)
        old = self.db.get_attachment("cap")
        self.assertIsNotNone(old)
        self.assertTrue(old["is_lead"])
        self.assertFalse(self.spawned)

    def test_the_captain_role_survives_the_replacement(self):
        # the captain replaces itself: the fresh instance is still the captain
        self.db._exec("UPDATE attachments SET runtime_owner='cap-owner', "
                      "status='detached' WHERE id='cap'")
        self.runtime.live.pop("cap")  # detached: no live process to stop
        headers = {"Authorization": "Bearer " + auth_store.ensure_api_token(self.db, "cap")}
        response = self.replace(att_id="cap", headers=headers)
        self.assertEqual(response.status_code, 200, response.text)
        replacement = response.json()
        self.assertTrue(self.db.get_attachment(replacement["id"])["is_lead"])
        self.assertEqual(replacement["name"], "sol")
        self.assertIsNone(self.db.get_attachment("cap"))

    def test_a_worker_cannot_replace_another_worker(self):
        other = self.worker_token("dig", "dig", "dig-owner")
        response = self.replace(headers=other)
        self.assertEqual(response.status_code, 403, response.text)
        self.assertIsNotNone(self.db.get_attachment("old"))

    def test_a_person_can_replace_and_the_notice_is_posted(self):
        response = self.replace(headers=self.human)
        self.assertEqual(response.status_code, 200, response.text)
        notices = [m["body"] for m in self.db.list_messages("line") if "↻" in m["body"]]
        self.assertEqual(len(notices), 1)
        self.assertIn("@worker replaced with a fresh instance (by @greg)", notices[0])
        self.assertIn("thrashing on compaction", notices[0])

    def test_the_reason_is_required(self):
        self.assertEqual(self.replace({}).status_code, 422)
        self.assertEqual(self.replace({"reason": "   "}).status_code, 422)

    def test_the_checkpoint_carries_the_line_notes_and_the_assignment(self):
        write_notes(self.db, "line", "line", "gates: pytest tests/test_parser.py",
                    attachment_id="")
        self.db.add_message("line", "sol", "agent",
                            "@worker the lexer tests are yours — report by 5")
        self.db._exec("UPDATE messages SET source_attachment_id='cap' "
                      "WHERE body LIKE '@worker the lexer tests%'")
        self.replace()
        checkpoint = self.spawned[-1].get("checkpoint") or ""
        self.assertIn("gates: pytest tests/test_parser.py", checkpoint)
        self.assertIn("@worker the lexer tests are yours", checkpoint)
        # a replaced process was not compacted: the header names the replacement
        self.assertIn("You are a fresh instance replacing the previous @worker: "
                      "thrashing on compaction", checkpoint)
        self.assertNotIn("just compacted", checkpoint)

    def test_a_live_process_is_detached_then_replaced(self):
        self.db._exec("UPDATE attachments SET status='running' WHERE id='old'")
        live = SimpleNamespace(att=self.db.get_attachment("old"), stopped=False)
        on_status = self.runtime.status_callback("old", "line", "owner-old")

        async def stop():
            live.stopped = True
            await on_status("exited")  # the harness reports the stop asynchronously

        live.stop = stop
        self.runtime.live["old"] = live
        response = self.replace()
        self.assertEqual(response.status_code, 200, response.text)
        self.assertTrue(live.stopped)
        self.assertNotIn("old", self.runtime.live)
        self.assertIsNone(self.db.get_attachment("old"))

    def test_the_compaction_thrash_ring_names_the_replace_action(self):
        self.db.add_attachment("haiku", "line", "haiku", "claude", ["claude"],
                               self.directory.name, "haiku-owner")
        self.db._exec("UPDATE attachments SET status='running' WHERE id='haiku'")
        att = self.db.get_attachment("haiku")
        with patch.dict(ADAPTER_METADATA,
                        {"claude": {"capabilities": {"compaction_hooks": True}}}):
            for _ in range(3):
                asyncio.run(note_hook_compaction(self.runtime, att, "auto"))
        ringed = [m["body"] for m in self.captain_recorder.delivered
                  if "thrashing" in m["body"]]
        self.assertTrue(ringed)
        self.assertIn("POST /api/attachments/haiku/replace", ringed[-1])


if __name__ == "__main__":
    unittest.main()
