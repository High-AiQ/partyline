"""Fresh-session boundaries use temporary persistence and fake process adapters."""

import asyncio
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from partyline.adapters.briefing import fresh_checkpoint_briefing
from partyline.attachment_lifecycle import (FreshAttachmentRequest, create_fresh_record,
                                           remove_stopped_record)
from partyline.attachment_lifecycle_routes import register_attachment_lifecycle_routes
from partyline.attachment_start import start_attachment
from partyline.attachment_broadcast import broadcast_attachment_state
from partyline.attachment_contracts import AttachmentResponse
from partyline.auth_store import attachment_by_api_token, ensure_api_token
from partyline.db import Db
from partyline.runtime import ChatRuntime


class LifecycleTest(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.db = Db(f"{self.directory.name}/test.db")
        self.runtime = ChatRuntime(self.db)
        self.db.create_conversation("line", "Line")
        self.db.create_conversation("other", "Other")
        self.runtime.broadcast = AsyncMock()
        self.runtime.route_mentions = AsyncMock()
        self.spawn_failure = False
        self.make_failure = False
        self.spawn_gap = False
        self.concurrent_removal = False
        self.adapters = []
        self.validation = Mock()
        self.loopback = Mock()
        self.presence = SimpleNamespace(
            posting=lambda conv, ident, callback: callback,
            statusing=lambda conv, ident, callback, name: callback,
            watch=lambda adapter, *args: adapter,
        )
        self.tasks = SimpleNamespace(rider=lambda _: "current tasks")
        self.hook_url = lambda ident, owner: f"hook/{ident}/{owner}"
        app = FastAPI()
        register_attachment_lifecycle_routes(
            app, self.runtime, start=self.start, require_loopback=self.loopback,
            validate=self.validation,
        )
        self.client = TestClient(app)
        self.add_old()

    def tearDown(self):
        self.client.close()
        self.db.close()
        self.directory.cleanup()

    def add_old(self):
        att = self.db.add_attachment(
            "old", "line", "worker", "raw", ["sh"], self.directory.name, "owner-old"
        )
        self.db.set_attachment_status("old", "detached", "owner-old")
        self.db.set_cli_session("old", "previous-cli-session", "owner-old")
        self.old_token = ensure_api_token(self.db, "old")
        return att

    def factory(self, adapter_id, att, post, status, **kwargs):
        if self.make_failure:
            raise RuntimeError("factory failed")
        adapter = SimpleNamespace(att=att, deliveries=[], stopped=False)

        async def start():
            if self.spawn_failure:
                raise RuntimeError("spawn failed")
            if self.spawn_gap:
                self.db.add_message("line", "greg", "human", "instruction during spawn")
            await status("running")
            if self.concurrent_removal:
                await remove_stopped_record(self.db, "old")

        async def stop():
            adapter.stopped = True

        async def deliver(messages):
            adapter.deliveries.extend(messages)

        adapter.start, adapter.stop, adapter.deliver = start, stop, deliver
        self.adapters.append(adapter)
        return adapter

    async def start(self, att, **kwargs):
        return await start_attachment(
            att, runtime=self.runtime, presence=self.presence, tasks=self.tasks,
            make_adapter=self.factory, hook_url=self.hook_url,
            **kwargs,
        )

    def fresh(self, body=None):
        return self.client.post("/api/attachments/old/fresh", json=body)

    def test_fresh_replaces_identity_and_revokes_old_token_without_chat_replay(self):
        old_message = self.db.add_message("line", "greg", "human", "old context")
        response = self.fresh()
        self.assertEqual(response.status_code, 200, response.text)
        new = response.json()
        self.assertNotEqual(new["id"], "old")
        self.assertEqual(new["last_seen"], old_message["id"])
        self.assertIsNone(new["cli_session"])
        self.assertEqual(new["command"], ["sh"])
        self.assertEqual(new["name"], "worker")
        self.assertNotIn("api_token", new)
        self.assertIsNone(self.db.get_attachment("old"))
        self.assertIsNone(attachment_by_api_token(self.db, self.old_token))
        adapter = self.adapters[-1]
        self.assertNotEqual(adapter.att["api_token"], self.old_token)
        self.assertNotIn("resume", adapter.att)
        self.assertEqual(adapter.att["digest_rider"](), "current tasks")
        self.assertIn(old_message, self.db.list_messages("line"))
        events = [call.args[1].model_dump() for call in self.runtime.broadcast.call_args_list]
        self.assertIn({"type": "attachment_removed", "attachment_id": "old",
                       "conversation_id": "line"}, events)
        self.assertEqual(events[-1]["attachment"]["id"], new["id"])

    def test_checkpoint_boundary_delivers_gap_once_and_never_prior_context(self):
        for index in range(20):
            boundary = self.db.add_message("line", "greg", "human", f"old {index}")
        gap = self.db.add_message("line", "greg", "human", "instruction during detach")
        self.spawn_gap = True
        response = self.fresh({"checkpoint": "docs/checkpoint.md",
                               "after_message_id": boundary["id"]})
        self.assertEqual(response.status_code, 200, response.text)
        adapter = self.adapters[-1]
        new_id = response.json()["id"]
        self.assertEqual(adapter.att["fresh_checkpoint"], "docs/checkpoint.md")
        wake = self.db.add_message("line", "greg", "human", "@worker continue")
        for _ in range(2):
            asyncio.run(ChatRuntime.route_mentions(self.runtime, "line", wake))
        self.assertGreater(self.db.get_attachment(new_id)["last_seen"], boundary["id"])
        bodies = [message["body"] for message in adapter.deliveries]
        self.assertEqual(bodies.count(gap["body"]), 1)
        self.assertEqual(bodies.count("instruction during spawn"), 1)
        self.assertFalse(any(body.startswith("old ") for body in bodies))

    def test_spawn_and_factory_failure_preserve_resumable_old_record(self):
        for failure in ("spawn_failure", "make_failure"):
            with self.subTest(failure=failure):
                setattr(self, failure, True)
                response = self.fresh({})
                self.assertEqual(response.status_code, 500, response.text)
                self.assertEqual(len(self.db.list_attachments("line")), 1)
                self.assertEqual(self.db.get_attachment("old")["cli_session"], "previous-cli-session")
                self.assertIsNotNone(attachment_by_api_token(self.db, self.old_token))
                setattr(self, failure, False)
        self.assertTrue(self.adapters[0].stopped)

    def test_remove_preserves_chat_and_refuses_live_or_missing_records(self):
        message = self.db.add_message("line", "worker", "agent", "retained history")
        self.runtime.uncredited["old"] = {"owner": "owner-old", "ids": {message["id"]}}
        self.runtime.unclaimed_noticed.add("old")
        response = self.client.delete("/api/attachments/old/record")
        self.assertEqual(response.status_code, 200)
        self.assertNotIn("old", self.runtime.uncredited)
        self.assertNotIn("old", self.runtime.unclaimed_noticed)
        self.assertIsNone(attachment_by_api_token(self.db, self.old_token))
        self.assertEqual(self.db.list_messages("line"), [message])
        self.assertEqual(self.client.delete("/api/attachments/old/record").status_code, 404)
        self.add_old()
        for status in ("starting", "running"):
            self.db.set_attachment_status("old", status, "owner-old")
            self.assertEqual(self.client.delete("/api/attachments/old/record").status_code, 409)
            self.assertEqual(self.fresh({}).status_code, 409)
        self.db.set_attachment_status("old", "detached", "owner-old")
        self.runtime.live["old"] = object()
        self.assertEqual(self.client.delete("/api/attachments/old/record").status_code, 409)
        self.assertEqual(self.fresh({}).status_code, 409)

    def test_validation_fails_before_reserving_or_spawning(self):
        self.assertEqual(self.fresh({"after_message_id": 0}).status_code, 422)
        self.assertEqual(self.fresh({"checkpoint": "x", "after_message_id": -1}).status_code, 422)
        self.assertEqual(self.fresh({"checkpoint": "x", "after_message_id": 500}).status_code, 400)
        other = self.db.add_message("other", "greg", "human", "other line")
        self.assertEqual(self.fresh({"checkpoint": "x", "after_message_id": other["id"]}).status_code, 400)
        self.validation.side_effect = ValueError("invalid adapter")
        self.assertEqual(self.fresh({}).status_code, 400)
        self.validation.side_effect = None
        self.db.archive_conversation("line")
        self.assertEqual(self.fresh({}).status_code, 409)
        self.assertEqual(self.adapters, [])

    def test_boundary_zero_is_refused_and_plain_checkpoint_briefing_is_supported(self):
        self.assertEqual(fresh_checkpoint_briefing("intro", None), "intro")
        self.assertIn("docs/state.md", fresh_checkpoint_briefing("intro", "docs/state.md"))
        self.assertEqual(self.fresh({"checkpoint": "docs/state.md", "after_message_id": 0}).status_code, 422)

    def test_reserved_replacement_prevents_old_resume_and_double_fresh(self):
        old = self.db.get_attachment("old")
        asyncio.run(create_fresh_record(self.db, old, FreshAttachmentRequest()))
        self.assertFalse(self.db.claim_attachment("old", "racing-resume"))
        self.assertEqual(self.fresh({}).status_code, 409)
        self.assertEqual(len(self.db.list_attachments("line")), 2)

    def test_changed_settings_and_missing_directory_fail_before_spawn(self):
        old = self.db.get_attachment("old")
        asyncio.run(self.db.update_inactive_attachment_command("old", ["other"]))
        with self.assertRaises(HTTPException) as caught:
            asyncio.run(create_fresh_record(self.db, old, FreshAttachmentRequest()))
        self.assertEqual(caught.exception.status_code, 409)
        self.db._exec("UPDATE attachments SET cwd='/missing-directory' WHERE id='old'")
        self.assertEqual(self.fresh({}).status_code, 400)

    def test_removal_clears_delivery_rows_and_saved_restart_membership(self):
        message = self.db.add_message("line", "greg", "human", "kept")
        self.db._exec("INSERT INTO queued_delivery_messages VALUES(?,?)", ("old", message["id"]))
        self.db._exec("INSERT INTO transcript_delivery_records VALUES(?,?,?)",
                      ("old", message["id"], b"fingerprint"))
        self.db.save_restart_plan("line", ["old", "another"], "continue")
        self.assertEqual(self.client.delete("/api/attachments/old/record").status_code, 200)
        self.assertEqual(self.db.get_restart_plan()["attachment_ids"], ["another"])
        for table in ("queued_delivery_messages", "transcript_delivery_records"):
            self.assertEqual(self.db._exec(f"SELECT COUNT(*) FROM {table}").fetchone()[0], 0)
        self.add_old()
        self.db.save_restart_plan("line", ["old"], "continue")
        self.assertEqual(self.client.delete("/api/attachments/old/record").status_code, 200)
        self.assertIsNone(self.db.get_restart_plan())

    def test_local_control_gate_runs_before_any_mutation(self):
        self.loopback.side_effect = HTTPException(403, "local control only")
        self.assertEqual(self.fresh({}).status_code, 403)
        self.assertEqual(self.client.delete("/api/attachments/old/record").status_code, 403)
        self.assertEqual(len(self.db.list_attachments("line")), 1)

    def test_concurrent_old_card_removal_does_not_fail_a_successful_spawn(self):
        self.concurrent_removal = True
        response = self.fresh({})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertIn(response.json()["id"], self.runtime.live)

    def test_boundaries_reject_boolean_fraction_and_sqlite_overflow(self):
        for value in (True, 1.5, 2**63):
            with self.subTest(value=value):
                self.assertEqual(self.fresh({"checkpoint": "x", "after_message_id": value}).status_code, 422)

    def test_delayed_attachment_broadcast_cannot_resurrect_a_removed_record(self):
        async def scenario():
            entered, release = asyncio.Event(), asyncio.Event()

            async def delayed_response(att):
                entered.set()
                await release.wait()
                return AttachmentResponse.model_validate(att).model_dump()

            with patch("partyline.attachment_broadcast.attachment_response", delayed_response):
                pending = asyncio.create_task(broadcast_attachment_state(self.runtime, "line", "old"))
                await entered.wait()
                await remove_stopped_record(self.db, "old")
                release.set()
                await pending
            self.runtime.broadcast.assert_not_awaited()
        asyncio.run(scenario())

    def test_setup_failure_releases_reservation_for_retry(self):
        self.hook_url = Mock(side_effect=RuntimeError("hook failed"))
        response = self.fresh({})
        self.hook_url = lambda ident, owner: f"hook/{ident}/{owner}"
        self.assertEqual(response.status_code, 500)
        self.assertEqual([att["id"] for att in self.db.list_attachments("line")], ["old"])
        self.assertEqual(self.runtime.live, {})
        self.assertEqual(self.fresh({}).status_code, 200)

    def test_announcement_failure_stops_process_before_forgetting_reservation(self):
        with patch("partyline.attachment_start.announce_attachment", side_effect=RuntimeError("post failed")):
            response = self.fresh({})
        self.assertEqual(response.status_code, 500)
        self.assertTrue(self.adapters[-1].stopped)
        self.assertEqual(self.runtime.live, {})
        self.assertEqual([att["id"] for att in self.db.list_attachments("line")], ["old"])

    def test_uncertain_stop_keeps_replacement_reachable(self):
        original_factory = self.factory

        def factory(*args, **kwargs):
            adapter = original_factory(*args, **kwargs)
            adapter.stop = AsyncMock(side_effect=RuntimeError("stop failed"))
            return adapter

        self.factory = factory
        self.spawn_failure = True
        response = self.fresh({})
        self.assertEqual(response.status_code, 500)
        self.assertIn("still tracked", response.text)
        self.assertEqual(len(self.runtime.live), 1)
        self.assertEqual(len(self.db.list_attachments("line")), 2)
        self.assertIsNotNone(attachment_by_api_token(self.db, self.old_token))

    def test_stale_checkpoint_refuses_unbounded_replay_without_spawning(self):
        boundary = self.db.add_message("line", "greg", "human", "checkpoint")
        for _ in range(101):
            self.db.add_message("line", "greg", "human", "later")
        response = self.fresh({"checkpoint": "x", "after_message_id": boundary["id"]})
        self.assertEqual(response.status_code, 400)
        self.assertIn("101 messages", response.text)
        self.assertEqual(len(self.db.list_attachments("line")), 1)
        recent = self.db.add_message("line", "greg", "human", "new checkpoint")
        self.db.add_message("line", "greg", "human", "x" * 32001)
        self.assertEqual(self.fresh({"checkpoint": "x", "after_message_id": recent["id"]}).status_code, 400)
        self.assertEqual(self.adapters, [])

    def test_response_failure_rolls_back_the_spawned_process(self):
        with patch("partyline.attachment_start.attachment_response",
                   side_effect=RuntimeError("response failed")):
            response = self.fresh({})
        self.assertEqual(response.status_code, 500)
        self.assertTrue(self.adapters[-1].stopped)
        self.assertEqual(self.runtime.live, {})
        self.assertEqual([att["id"] for att in self.db.list_attachments("line")], ["old"])
