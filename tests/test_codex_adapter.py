"""Startup-delivery contract for the private Codex adapter."""

import json
import os
import shutil
import sqlite3
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from partyline.adapters.bundled.codex.adapter import PartylineAdapter
from partyline.terminal_viewers import TerminalViewerRegistry


class CodexCommandTest(unittest.IsolatedAsyncioTestCase):
    def test_manifest_versions_the_startup_delivery_contract(self):
        manifest = (
            Path(__file__).parent.parent / "partyline" / "adapters" / "bundled" / "codex" / "adapter.toml"
        ).read_text(encoding="utf-8")

        self.assertIn('version = "1.3.0"', manifest)
        self.assertIn('update_command = ["codex", "update"]', manifest)

    def make_adapter(
        self,
        *,
        command: list[str],
        resume: bool,
        session_id: str | None = None,
    ) -> PartylineAdapter:
        """Build only the pure argv seam; no pty or vendor CLI is involved."""
        adapter = PartylineAdapter.__new__(PartylineAdapter)
        adapter.att = {"command": command, "cli_session": session_id}
        adapter.resume = resume
        return adapter

    def make_resumed_adapter(self) -> PartylineAdapter:
        async def post(sender: str, sender_type: str, body: str) -> None:
            return None

        async def on_status(status: str) -> None:
            return None

        return PartylineAdapter(
            {
                "command": ["codex"],
                "cli_session": "session-1",
                "name": "terra",
                "resume": True,
            },
            post,
            on_status,
        )

    def test_fresh_command_is_unchanged(self):
        command = ["codex", "--model", "gpt-5.6-terra"]
        adapter = self.make_adapter(command=command, resume=False)

        self.assertEqual(adapter.build_command(), command)

    def test_resume_without_a_staged_digest_is_unchanged(self):
        command = ["codex", "--model", "gpt-5.6-terra"]
        adapter = self.make_adapter(command=command, resume=True, session_id="session-1")

        self.assertEqual(adapter.build_command(), ["codex", "resume", "session-1", *command[1:]])

    def test_staged_resume_digest_is_the_final_startup_prompt(self):
        command = ["codex", "--model", "gpt-5.6-terra"]
        messages = [{"sender": "system", "body": "Continuation debrief: nonce-123"}]
        adapter = self.make_adapter(command=command, resume=True, session_id="session-1")

        self.assertTrue(adapter.stage_startup_delivery(messages))

        self.assertEqual(
            adapter.build_command(),
            ["codex", "resume", "session-1", *command[1:], adapter.format_digest(messages)],
        )

    def test_fresh_attachment_refuses_staged_resume_delivery(self):
        command = ["codex", "--model", "gpt-5.6-terra"]
        adapter = self.make_adapter(command=command, resume=False)

        self.assertFalse(adapter.stage_startup_delivery([{"sender": "system", "body": "nonce-123"}]))
        self.assertEqual(adapter.build_command(), command)

    async def test_only_a_structured_startup_prompt_receives_the_staged_digest(self):
        messages = [{"sender": "system", "body": "Continuation debrief: nonce-123"}]

        async def run_with(record: dict) -> PartylineAdapter:
            adapter = self.make_resumed_adapter()
            self.assertTrue(adapter.stage_startup_delivery(messages))
            adapter.alive = lambda: True
            adapter._fresh = lambda timestamp: True
            adapter._find_rollout = lambda: "rollout.jsonl"

            async def tail(path, handle):
                await handle(record)

            adapter._tail_jsonl = tail
            with (
                patch("partyline.adapters.bundled.codex.adapter.asyncio.sleep", AsyncMock()),
                patch("builtins.open", side_effect=OSError),
            ):
                await adapter._run()
            return adapter

        prompt = self.make_resumed_adapter().format_digest(messages)
        received = await run_with(
            {
                "type": "event_msg",
                "timestamp": "2026-08-05T00:00:00Z",
                "payload": {"type": "user_message", "message": prompt},
            }
        )
        ignored = await run_with(
            {
                "type": "event_msg",
                "timestamp": "2026-08-05T00:00:00Z",
                "payload": {"type": "agent_message", "message": prompt},
            }
        )

        self.assertTrue(await received.wait_startup_delivery_received())
        self.assertIsNone(ignored._startup_delivery_result)

    async def test_timeout_notice_names_codex_without_addressing_it(self):
        posted: list[tuple[str, str, str]] = []

        async def post(sender: str, sender_type: str, body: str) -> None:
            posted.append((sender, sender_type, body))

        async def on_status(status: str) -> None:
            return None

        adapter = PartylineAdapter(
            {
                "command": ["codex"],
                "cwd": "/work",
                "id": "att-1",
                "name": "codex",
                "resume": False,
            },
            post,
            on_status,
        )
        adapter.alive = lambda: True
        adapter.master = 1
        adapter._find_rollout = lambda: None
        with (
            patch("partyline.adapters.bundled.codex.adapter.asyncio.sleep", AsyncMock()),
            patch("partyline.adapters.bundled.codex.adapter.os.write"),
            patch.object(adapter, "send_keys", AsyncMock()),
        ):
            await adapter._run()

        self.assertTrue(posted[0][2].startswith("codex: no rollout file after 90s"))

    async def run_tail_with(self, record: dict) -> tuple[PartylineAdapter, list[tuple]]:
        """Feed one rollout record through a resumed adapter's tail handler."""
        posted: list[tuple] = []

        async def post(sender: str, sender_type: str, body: str) -> None:
            posted.append((sender, sender_type, body))

        async def on_status(status: str) -> None:
            return None

        adapter = PartylineAdapter(
            {"command": ["codex"], "cli_session": "session-1", "name": "terra", "resume": True},
            post,
            on_status,
        )
        self.assertTrue(
            adapter.stage_startup_delivery(
                [{"sender": "system", "body": "Continuation debrief: nonce-123"}]
            )
        )
        adapter.alive = lambda: True
        adapter._fresh = lambda timestamp: True
        adapter._find_rollout = lambda: "rollout.jsonl"

        async def tail(path, handle):
            await handle(record)

        adapter._tail_jsonl = tail
        with (
            patch("partyline.adapters.bundled.codex.adapter.asyncio.sleep", AsyncMock()),
            patch("builtins.open", side_effect=OSError),
        ):
            await adapter._run()
        return adapter, posted

    # Newer Codex builds record speech as completed items rather than the
    # user_message/agent_message events the old vocabulary used. Two agents sat
    # on the line for an hour composing replies nobody ever saw because the
    # tail only spoke the old dialect.
    async def test_completed_final_answer_item_posts_to_the_line(self):
        _, posted = await self.run_tail_with(
            {
                "type": "event_msg",
                "timestamp": "2026-08-09T00:00:00Z",
                "payload": {
                    "type": "item_completed",
                    "item": {
                        "type": "AgentMessage",
                        "phase": "final_answer",
                        "content": [{"type": "Text", "text": "Hi — connected and ready."}],
                    },
                },
            }
        )

        self.assertEqual(posted, [("terra", "agent", "Hi — connected and ready.")])

    async def test_commentary_items_post_as_progress_notes(self):
        """An agent's pre-work acknowledgment rides the commentary phase; the
        briefing promises everything it writes reaches the line."""
        _, posted = await self.run_tail_with(
            {
                "type": "event_msg",
                "timestamp": "2026-08-09T00:00:00Z",
                "payload": {
                    "type": "item_completed",
                    "item": {
                        "type": "AgentMessage",
                        "phase": "commentary",
                        "content": [{"type": "Text", "text": "Starting on the adapter now."}],
                    },
                },
            }
        )

        self.assertEqual(posted, [("terra", "agent", "Starting on the adapter now.")])

    async def test_completed_user_message_item_marks_startup_receipt(self):
        prompt = self.make_resumed_adapter().format_digest(
            [{"sender": "system", "body": "Continuation debrief: nonce-123"}]
        )
        adapter, posted = await self.run_tail_with(
            {
                "type": "event_msg",
                "timestamp": "2026-08-09T00:00:00Z",
                "payload": {
                    "type": "item_completed",
                    "item": {
                        "type": "UserMessage",
                        "content": [{"type": "text", "text": prompt}],
                    },
                },
            }
        )

        self.assertEqual(posted, [])
        self.assertTrue(await adapter.wait_startup_delivery_received())


    async def test_user_and_agent_message_payloads_are_handled(self):
        # Direct user_message and agent_message types (older Codex vocab)
        _, posted = await self.run_tail_with(
            {
                "type": "event_msg",
                "timestamp": "2026-08-09T00:00:00Z",
                "payload": {"type": "user_message", "message": "hello from user"},
            }
        )
        self.assertEqual(posted, [])
        _, posted2 = await self.run_tail_with(
            {
                "type": "event_msg",
                "timestamp": "2026-08-09T00:00:00Z",
                "payload": {"type": "agent_message", "message": "hello from agent"},
            }
        )
        self.assertEqual(posted2, [("terra", "agent", "hello from agent")])

    async def test_rollout_turn_boundaries_become_receipts(self):
        """task_started/task_complete are the harness's own turn boundaries —
        the receipt that lets the working badge self-clear (#47)."""
        from partyline.adapters.receipts import BEGAN, ENDED

        for payload_type, event in (("task_started", BEGAN), ("task_complete", ENDED)):
            with patch(
                "partyline.adapters.bundled.codex.adapter.receipt", new=AsyncMock()
            ) as receipt_mock:
                adapter, posted = await self.run_tail_with(
                    {
                        "type": "event_msg",
                        "timestamp": "2026-08-09T00:00:00Z",
                        "payload": {"type": payload_type},
                    }
                )
            receipt_mock.assert_awaited_once_with(adapter.att, event)
            self.assertEqual(posted, [])

    async def test_a_task_started_while_a_task_is_open_ends_the_aborted_one(self):
        """An interrupted task writes no task_complete; the badge would wedge
        until the process exits. The superseding task_started is the aborted
        turn's only deterministic end, so it reports ENDED first."""
        from partyline.adapters.receipts import BEGAN, ENDED

        posted: list[tuple] = []

        async def post(sender: str, sender_type: str, body: str) -> None:
            posted.append((sender, sender_type, body))

        async def on_status(status: str) -> None:
            return None

        adapter = PartylineAdapter(
            {"command": ["codex"], "cli_session": "session-1", "name": "terra", "resume": True},
            post,
            on_status,
        )
        adapter.alive = lambda: True
        adapter._fresh = lambda timestamp: True
        adapter._find_rollout = lambda: "rollout.jsonl"
        records = [
            {
                "type": "event_msg",
                "timestamp": "2026-08-09T00:00:00Z",
                "payload": {"type": "task_started"},
            },
            {
                "type": "event_msg",
                "timestamp": "2026-08-09T00:00:01Z",
                "payload": {"type": "task_started"},
            },
        ]

        async def tail(path, handle):
            for record in records:
                await handle(record)

        adapter._tail_jsonl = tail
        with (
            patch("partyline.adapters.bundled.codex.adapter.asyncio.sleep", AsyncMock()),
            patch("builtins.open", side_effect=OSError),
            patch("partyline.adapters.bundled.codex.adapter.receipt", new=AsyncMock())
            as receipt_mock,
        ):
            await adapter._run()
        self.assertTrue(adapter._task_open)
        self.assertEqual(posted, [])
        self.assertEqual(
            [call.args[1] for call in receipt_mock.await_args_list],
            [BEGAN, ENDED, BEGAN],
        )

    async def test_a_stale_boundary_record_sends_no_receipt(self):
        """A resume replays the rollout's backlog through the tail handler;
        old turn boundaries must not emit, or they would clear a badge a
        live turn owns."""

        async def post(sender, sender_type, body):
            return None

        async def on_status(status):
            return None

        adapter = PartylineAdapter(
            {"command": ["codex"], "cli_session": "session-1", "name": "terra", "resume": True},
            post,
            on_status,
        )
        adapter._fresh = lambda timestamp: False
        adapter.alive = lambda: True
        adapter._find_rollout = lambda: "rollout.jsonl"

        async def tail(path, handle):
            await handle(
                {
                    "type": "event_msg",
                    "timestamp": "old",
                    "payload": {"type": "task_complete"},
                }
            )

        adapter._tail_jsonl = tail
        with (
            patch("partyline.adapters.bundled.codex.adapter.asyncio.sleep", new=AsyncMock()),
            patch("builtins.open", side_effect=OSError),
            patch(
                "partyline.adapters.bundled.codex.adapter.receipt", new=AsyncMock()
            ) as receipt_mock,
        ):
            await adapter._run()
        receipt_mock.assert_not_called()

    async def test_non_event_and_stale_records_are_ignored(self):
        # Non-event type and stale timestamp should not post
        _, posted = await self.run_tail_with(
            {"type": "other", "timestamp": "2026-08-09T00:00:00Z", "payload": {"type": "user_message"}}
        )
        self.assertEqual(posted, [])
        # Stale: use a timestamp before spawned_at (mock _fresh to False)
        from unittest.mock import patch

        from partyline.adapters.bundled.codex.adapter import PartylineAdapter

        posted2: list[tuple] = []

        async def post2(sender, sender_type, body):
            posted2.append((sender, sender_type, body))

        async def on_status2(status):
            return None

        adapter2 = PartylineAdapter(
            {"command": ["codex"], "cli_session": "session-1", "name": "terra", "resume": True},
            post2,
            on_status2,
        )
        adapter2._fresh = lambda ts: False
        adapter2.alive = lambda: True
        adapter2._find_rollout = lambda: "rollout.jsonl"
        adapter2.stage_startup_delivery([{"sender": "system", "body": "x"}])

        async def tail2(path, handle):
            await handle(
                {
                    "type": "event_msg",
                    "timestamp": "old",
                    "payload": {"type": "agent_message", "message": "hi"},
                }
            )

        adapter2._tail_jsonl = tail2
        # Use a counted alive that exits after one handle, and a yielding sleep mock
        import asyncio as _asyncio

        orig_sleep = _asyncio.sleep

        async def _yield(*_a, **_k):
            await orig_sleep(0)

        alive_calls = 0

        def alive_once():
            nonlocal alive_calls
            alive_calls += 1
            return alive_calls < 3

        adapter2.alive = alive_once
        with patch("partyline.adapters.bundled.codex.adapter.asyncio.sleep", side_effect=_yield), patch(
            "builtins.open", side_effect=OSError
        ):
            await adapter2._run()
        self.assertEqual(posted2, [])

class CodexDiscoveryTest(unittest.IsolatedAsyncioTestCase):
    def make_adapter(self, **extra):
        import asyncio

        adapter = PartylineAdapter.__new__(PartylineAdapter)
        adapter.att = {"cwd": "/work", "cli_session": "session-1", "id": "att-1",
                       "adapter_metadata": {"capabilities": {"transcript": True}}, **extra}
        adapter.spawned_at = 1000.0
        adapter.resume = False
        adapter._home = "/tmp/codex-home"
        adapter._ready_result = None
        adapter._ready = asyncio.Event()
        adapter._tail_task = None
        adapter._stopping = False
        adapter._startup_delivery = asyncio.Event()
        adapter._startup_delivery_result = None
        adapter._silent_until_wake = False
        adapter._terminal_viewers = TerminalViewerRegistry(lambda: "")

        async def _noop_post(*a, **k):
            return None

        async def _noop_status(*a, **k):
            return None

        adapter._post_to_chat = _noop_post
        adapter.on_status = _noop_status
        adapter.proc = None
        adapter.master = None
        adapter._tasks = []
        return adapter

    @staticmethod
    def write_rollout(path: str, meta: dict, lines=()) -> str:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(json.dumps({"type": "session_meta", "payload": meta}) + "\n")
            for line in lines:
                fh.write(line if line.endswith("\n") else line + "\n")
        return path

    def test_fresh_rollout_is_claimed_only_when_it_records_our_token(self):
        """Identity is content: recency and cwd merely bound the scan."""
        with tempfile.TemporaryDirectory() as tmp:
            rollout = self.write_rollout(
                os.path.join(tmp, "rollout-tokenless.jsonl"),
                {"id": "sess-1", "cwd": "/work", "source": {}})
            adapter = self.make_adapter()
            with (
                patch("partyline.adapters.bundled.codex.adapter.glob.glob",
                      return_value=[rollout]),
                patch("partyline.adapters.bundled.codex.adapter.os.path.getmtime",
                      return_value=999.9)):
                self.assertIsNone(adapter._find_rollout())

            self.write_rollout(rollout, {"id": "sess-1", "cwd": "/work", "source": {}},
                               [json.dumps({"payload": {"type": "user_message",
                                                       "message": adapter._claim_token}})])
            with (
                patch("partyline.adapters.bundled.codex.adapter.glob.glob",
                      return_value=[rollout]),
                patch("partyline.adapters.bundled.codex.adapter.os.path.getmtime",
                      return_value=999.9),
            ):
                self.assertEqual(adapter._find_rollout(), rollout)

    def test_stale_mtime_is_skipped(self):
        with tempfile.TemporaryDirectory() as tmp:
            rollout = self.write_rollout(
                os.path.join(tmp, "rollout-stale.jsonl"), {"id": "sess-2", "cwd": "/work"},
                [json.dumps({"message": self.make_adapter()._claim_token})])
            adapter = self.make_adapter()
            with (
                patch("partyline.adapters.bundled.codex.adapter.glob.glob",
                      return_value=[rollout]),
                patch("partyline.adapters.bundled.codex.adapter.os.path.getmtime",
                      return_value=900.0),
            ):
                self.assertIsNone(adapter._find_rollout())

    def test_a_foreign_marked_rollout_is_never_adopted(self):
        """The write-fence defect as a control: another attachment's marker
        disqualifies a candidate even when it is the newest cwd match."""
        with tempfile.TemporaryDirectory() as tmp:
            adapter = self.make_adapter()
            sessions = os.path.join(tmp, "sessions", "2026", "09", "22")
            foreign = self.write_rollout(
                os.path.join(sessions, "rollout-foreign.jsonl"), {"id": "sess-x", "cwd": "/work"},
                [json.dumps({"message": "[partyline-claim: other-att/deadbeef123]"})])
            ours = self.write_rollout(
                os.path.join(sessions, "rollout-ours.jsonl"), {"id": "sess-y", "cwd": "/work"},
                [json.dumps({"message": adapter._claim_token})])
            now = time.time()
            os.utime(ours, (now - 5, now - 5))
            os.utime(foreign, (now, now))
            adapter._home = tmp

            self.assertEqual(adapter._find_rollout(), ours)

    def test_find_rollout_filters_by_source_and_resume(self):
        with tempfile.TemporaryDirectory() as tmp:
            sessions = os.path.join(tmp, "sessions", "2026", "09", "22")
            adapter = self.make_adapter()
            token = adapter._claim_token
            bad_type = self.write_rollout(
                os.path.join(sessions, "rollout-bad-type.jsonl"), {"id": "x", "cwd": "/other"},
                [json.dumps({"message": token})])
            # rewrite as the wrong record type with our token present
            with open(bad_type, "w", encoding="utf-8") as fh:
                fh.write(json.dumps({"type": "other", "payload": {"id": "x", "cwd": "/work"}}) + "\n")
                fh.write(json.dumps({"message": token}) + "\n")
            self.write_rollout(
                os.path.join(sessions, "rollout-subagent.jsonl"),
                {"id": "x", "cwd": "/work", "source": {"subagent": True}},
                [json.dumps({"message": token})])
            self.write_rollout(
                os.path.join(sessions, "rollout-cwd-mismatch.jsonl"), {"id": "x", "cwd": "/other"},
                [json.dumps({"message": token})])
            adapter._home = tmp
            with patch(
                "partyline.adapters.bundled.codex.adapter.os.path.getmtime", return_value=999.9
            ):
                self.assertIsNone(adapter._find_rollout())

            resume_match = self.write_rollout(
                os.path.join(sessions, "rollout-resume-match.jsonl"),
                {"id": "new", "forked_from_id": "session-1", "cwd": "/work"})
            self.write_rollout(
                os.path.join(sessions, "rollout-resume-mismatch.jsonl"),
                {"id": "other", "cwd": "/work", "forked_from_id": "other"})
            resumed = self.make_adapter()
            resumed.resume = True
            resumed._home = tmp
            with patch(
                "partyline.adapters.bundled.codex.adapter.os.path.getmtime", return_value=999.9
            ):
                # Lineage is exact content, so a resume needs no token.
                self.assertEqual(resumed._find_rollout(), resume_match)
            os.unlink(resume_match)
            with patch(
                "partyline.adapters.bundled.codex.adapter.os.path.getmtime", return_value=999.9
            ):
                # A resume with neither lineage nor token has nothing to claim.
                self.assertIsNone(resumed._find_rollout())

    def test_find_rollout_handles_os_and_json_errors(self):
        adapter = self.make_adapter()
        with (
            patch("partyline.adapters.bundled.codex.adapter.glob.glob",
                  return_value=["/tmp/codex-missing.jsonl"]),
            patch("partyline.adapters.bundled.codex.adapter.os.path.getmtime",
                  return_value=999.9),
        ):
            self.assertIsNone(adapter._find_rollout())

        with tempfile.TemporaryDirectory() as tmp:
            broken = self.write_rollout(
                os.path.join(tmp, "not-json.jsonl"), {})
            with open(broken, "w", encoding="utf-8") as fh:
                fh.write("not json\n")
                fh.write(json.dumps({"message": adapter._claim_token}) + "\n")
            with (
                patch("partyline.adapters.bundled.codex.adapter.glob.glob",
                      return_value=[broken]),
                patch("partyline.adapters.bundled.codex.adapter.os.path.getmtime",
                      return_value=999.9),
            ):
                self.assertIsNone(adapter._find_rollout())


class CodexHomeTest(unittest.IsolatedAsyncioTestCase):
    """Per-attachment CODEX_HOME isolation."""

    def setUp(self):
        from partyline.adapters.bundled.codex import adapter as codex

        self.codex = codex
        self.root = tempfile.TemporaryDirectory()
        self.shared = tempfile.TemporaryDirectory()
        self.old_roots = (codex.HOME_ROOT, codex.SHARED_HOME)
        self.codex.HOME_ROOT = os.path.join(self.root.name, "homes")
        codex.SHARED_HOME = self.shared.name
        for name in self.codex.SHARED:
            os.makedirs(os.path.join(self.shared.name, name), exist_ok=True)

    def tearDown(self):
        self.codex.HOME_ROOT, self.codex.SHARED_HOME = self.old_roots
        self.root.cleanup()
        self.shared.cleanup()

    def make(self, *, att_id: str, resume: bool = False, session: str | None = None,
             cwd: str = "/work") -> PartylineAdapter:
        async def post(sender, sender_type, body):
            return None

        async def on_status(status):
            return None

        adapter = PartylineAdapter(
            {"command": ["codex"], "cwd": cwd, "id": att_id, "name": att_id,
             "resume": resume, "cli_session": session,
             "adapter_metadata": {"capabilities": {"transcript": True}}},
            post,
            on_status,
        )
        adapter.spawned_at = time.time()
        return adapter

    @staticmethod
    def write_rollout(path: str, *, cwd: str, session: str, records=()) -> str:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(json.dumps(
                {"type": "session_meta", "payload": {"id": session, "cwd": cwd}}) + "\n")
            for record in records:
                fh.write(json.dumps(record) + "\n")
        return path

    def test_home_is_per_attachment_and_seeds_shared_entries(self):
        adapter = self.make(att_id="att-1")

        home = adapter.codex_home()

        self.assertEqual(home, os.path.join(self.codex.HOME_ROOT, "att-1"))
        self.assertTrue(os.path.isdir(os.path.join(home, "sessions")))
        for name in self.codex.SHARED:
            self.assertEqual(os.path.realpath(os.path.join(home, name)),
                             os.path.join(self.shared.name, name), name)
        # The one directory that must stay private is never a link.
        sessions = os.path.join(home, "sessions")
        self.assertFalse(os.path.islink(sessions), "sessions must belong to this attachment")

    def test_a_second_prepare_leaves_existing_links_alone(self):
        adapter = self.make(att_id="att-1")
        home = adapter.codex_home()
        marker = os.path.join(home, "sessions", "kept.jsonl")
        open(marker, "w", encoding="utf-8").close()

        adapter.codex_home()

        self.assertTrue(os.path.exists(marker))
        self.assertEqual(len(os.listdir(os.path.join(home, "sessions"))), 1)

    def test_spawn_env_points_codex_at_the_private_home(self):
        adapter = self.make(att_id="att-1")

        self.assertEqual(adapter.spawn_env(), {"CODEX_HOME": adapter.codex_home()})

    def test_resume_links_the_prior_rollout_into_the_home(self):
        prior = "b6c2b3e4-1111-2222-3333-444455556666"
        name = f"rollout-2026-09-22T23-09-12-{prior}.jsonl"
        shared_sessions = os.path.join(self.shared.name, "sessions", "2026", "09", "22")
        self.write_rollout(os.path.join(shared_sessions, name), cwd="/work", session=prior)
        adapter = self.make(att_id="att-1", resume=True, session=prior)

        home = adapter.codex_home()

        link = os.path.join(home, "sessions", "2026", "09", "22", name)
        self.assertEqual(os.path.realpath(link),
                         os.path.join(shared_sessions, name))

    def test_resume_finds_its_linked_prior_despite_an_old_mtime(self):
        """The linked prior predates this spawn; lineage, not recency, matches."""
        prior = "b6c2b3e4-1111-2222-3333-444455556666"
        name = f"rollout-2026-09-01T00-00-00-{prior}.jsonl"
        source = self.write_rollout(
            os.path.join(self.shared.name, "sessions", "2026", "09", "01", name),
            cwd="/work", session=prior)
        os.utime(source, (1_000_000, 1_000_000))
        adapter = self.make(att_id="att-1", resume=True, session=prior)
        adapter._home = adapter.codex_home()

        self.assertEqual(adapter._find_rollout(),
                         os.path.join(adapter._home, "sessions", "2026", "09", "01", name))

    async def test_two_same_directory_attachments_each_tail_their_own_rollout(self):
        """The 2026-09-22 write-fence incident, as a control.

        sol and luna were attached to one cwd within two seconds of each
        other and each tailed the other's rollout: discovery ordered the
        shared sessions directory by recency, so the first scanner claimed
        whichever file had been written last. With a CODEX_HOME per
        attachment there is no shared directory to order — each adapter
        can only ever see its own sessions.
        """
        cwd = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, cwd, True)
        adapters, rollouts = [], []
        for att_id in ("att-sol", "att-luna"):
            adapter = self.make(att_id=att_id, cwd=cwd)
            adapter._home = adapter.codex_home()
            # The rollout records the paste only that pty received.
            rollouts.append(self.write_rollout(
                os.path.join(adapter._home, "sessions", "2026", "09", "22",
                             f"rollout-2026-09-22T23-09-12-{att_id}.jsonl"),
                cwd=cwd, session=att_id,
                records=[{"type": "event_msg",
                          "payload": {"type": "user_message",
                                      "message": adapter._claim_token}}]))
            adapters.append(adapter)
        # Same second on the clock, luna's flush the newer of the two.
        now = time.time()
        for adapter in adapters:
            adapter.spawned_at = now - 0.5
        os.utime(rollouts[0], (now - 0.4, now - 0.4))
        os.utime(rollouts[1], (now, now))

        self.assertEqual(adapters[0]._find_rollout(), rollouts[0])
        self.assertEqual(adapters[1]._find_rollout(), rollouts[1])

    async def test_two_same_second_attachments_pair_by_content_even_in_one_home(self):
        """If isolation ever fails, the token still pairs 1:1 by content.

        Both rollouts sit in one sessions directory — the shape the
        incident actually ran on — and the newest file belongs to the
        second attachment. Scan order must not decide identity: each
        adapter claims the rollout that recorded its own paste.
        """
        cwd = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, cwd, True)
        shared_home = os.path.join(self.root.name, "collided")
        rollouts, adapters = [], []
        for att_id in ("att-sol", "att-luna"):
            adapter = self.make(att_id=att_id, cwd=cwd)
            adapter._home = shared_home
            rollouts.append(self.write_rollout(
                os.path.join(shared_home, "sessions", "2026", "09", "22",
                             f"rollout-2026-09-22T23-09-12-{att_id}.jsonl"),
                cwd=cwd, session=att_id,
                records=[{"type": "event_msg",
                          "payload": {"type": "user_message",
                                      "message": adapter._claim_token}}]))
            adapters.append(adapter)
        now = time.time()
        for adapter in adapters:
            adapter.spawned_at = now - 0.5
        os.utime(rollouts[0], (now - 0.4, now - 0.4))
        os.utime(rollouts[1], (now, now))

        self.assertEqual(adapters[0]._find_rollout(), rollouts[0])
        self.assertEqual(adapters[1]._find_rollout(), rollouts[1])


class CodexThreadHistoryTest(unittest.IsolatedAsyncioTestCase):
    """Resumed turns relayed from CODEX_HOME's paginated thread history.

    Verified against codex-cli 0.156: ``codex resume`` writes no new rollout
    file. The turn is projected into ``thread_history_1.sqlite`` — this suite
    is the fixture stand-in for that store, with negative controls for
    compaction summaries, replayed history, foreign claim markers, and
    malformed rows. The vendor CLI is never invoked.
    """

    def setUp(self):
        from partyline.adapters.bundled.codex import thread_history as th

        self.th = th
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.home = self.tmp.name
        self.db_path = os.path.join(self.home, th.STORE_NAME)
        self.spawned_at = time.time()
        self.messages: list[tuple[str, str, str]] = []
        self.receipts: list[tuple[dict, str]] = []
        self.startup_marks = 0
        self.ready = False

        adapter = PartylineAdapter.__new__(PartylineAdapter)
        adapter.att = {
            "id": "att-1",
            "name": "terra",
            "resume": True,
            "cli_session": "thread-1",
            "adapter_metadata": {"capabilities": {"transcript": True}},
        }
        adapter.resume = True
        adapter._nonce = "nonce22222222"
        adapter._claim_proven = False
        adapter._startup_prompt = ""
        adapter._startup_delivery_result = None
        adapter._stopping = False
        adapter.spawned_at = self.spawned_at
        adapter._home = self.home

        async def post(sender, sender_type, body):
            if adapter.pastes_claim() and not adapter._claim_proven and sender_type == "agent":
                return
            self.messages.append((sender, sender_type, body))
            adapter._alive = False

        adapter.post = post
        adapter.mark_startup_delivery_received = lambda: setattr(
            self, "startup_marks", self.startup_marks + 1
        )
        adapter.mark_ready = lambda: setattr(self, "ready", True)
        adapter._alive = True
        adapter.alive = lambda: adapter._alive
        self.adapter = adapter

        async def fake_receipt(att, event):
            self.receipts.append((att, event))

        self._receipt_patch = patch.object(th, "receipt", new=fake_receipt)
        self._receipt_patch.start()
        self.addCleanup(self._receipt_patch.stop)

    def write_store(self, items=(), turns=()) -> None:
        db = sqlite3.connect(self.db_path)
        db.executescript(
            """
            CREATE TABLE thread_turns (
                thread_id TEXT NOT NULL, turn_id TEXT NOT NULL,
                status TEXT NOT NULL, started_at INTEGER, completed_at INTEGER,
                PRIMARY KEY (thread_id, turn_id)
            );
            CREATE TABLE thread_items (
                thread_id TEXT NOT NULL, turn_id TEXT NOT NULL, item_id TEXT NOT NULL,
                created_at_ms INTEGER NOT NULL, item_json TEXT NOT NULL,
                item_type TEXT NOT NULL DEFAULT '',
                PRIMARY KEY (thread_id, turn_id, item_id)
            );
            """
        )
        db.executemany(
            "INSERT INTO thread_turns(thread_id, turn_id, status, started_at, completed_at) "
            "VALUES(?,?,?,?,?)",
            turns,
        )
        db.executemany(
            "INSERT INTO thread_items(thread_id, turn_id, item_id, created_at_ms, item_json, item_type) "
            "VALUES(?,?,?,?,?,?)",
            items,
        )
        db.commit()
        db.close()

    @staticmethod
    def item(item_id: str, item_type: str, payload: dict, *, thread="thread-1",
             turn="turn-1", at_ms: int | None = None) -> tuple:
        at = int(time.time() * 1000) if at_ms is None else at_ms
        return (thread, turn, item_id, at, json.dumps(payload), item_type)

    async def run_tail(self, *, timeout: float = 0.0) -> bool:
        async def stop_after_poll(*_a, **_k):
            self.adapter._alive = False

        with patch.object(self.th.asyncio, "sleep", new=stop_after_poll):
            return await self.th.tail_thread_history(
                self.adapter, self.home, "thread-1", timeout=timeout
            )

    async def test_resumed_agent_message_is_relayed_from_thread_history(self):
        token = self.adapter._claim_token
        self.write_store(
            items=[
                self.item("u1", "userMessage",
                          {"type": "userMessage", "content": [{"type": "text", "text": token}]}),
                self.item("a1", "agentMessage",
                          {"type": "agentMessage", "text": "BRAVO-TWO.", "phase": "final_answer"}),
            ],
            turns=[("thread-1", "turn-1", "completed", 1, 2)],
        )

        self.assertTrue(await self.run_tail())

        self.assertTrue(self.ready)
        self.assertEqual(self.messages, [("terra", "agent", "BRAVO-TWO.")])
        self.assertTrue(self.adapter._claim_proven)

    async def test_speech_stays_held_until_this_activation_nonce_is_observed(self):
        """The claim-marker gate: a prior activation's token is not this one's."""
        self.write_store(
            items=[
                self.item("u1", "userMessage",
                          {"type": "userMessage",
                           "content": [{"type": "text",
                                        "text": "[partyline-claim: att-1/oldnonce000000]"}]}),
                self.item("a1", "agentMessage",
                          {"type": "agentMessage", "text": "leftover speech"}),
            ],
        )

        await self.run_tail()

        self.assertEqual(self.messages, [])
        self.assertFalse(self.adapter._claim_proven)

    async def test_context_compaction_is_never_speech(self):
        token = self.adapter._claim_token
        self.write_store(
            items=[
                self.item("u1", "userMessage",
                          {"type": "userMessage", "content": [{"type": "text", "text": token}]}),
                self.item("c1", "contextCompaction", {"type": "contextCompaction", "id": "c1"}),
                self.item("a1", "agentMessage", {"type": "agentMessage", "text": "after compact"}),
            ],
        )

        await self.run_tail()

        self.assertEqual(self.messages, [("terra", "agent", "after compact")])

    async def test_history_predating_this_activation_is_not_replayed(self):
        token = self.adapter._claim_token
        old_ms = int((self.spawned_at - 3600) * 1000)
        self.write_store(
            items=[
                self.item("old-user", "userMessage",
                          {"type": "userMessage", "content": [{"type": "text", "text": "old"}]},
                          at_ms=old_ms),
                self.item("old-agent", "agentMessage",
                          {"type": "agentMessage", "text": "replayed"},
                          at_ms=old_ms),
                self.item("new-user", "userMessage",
                          {"type": "userMessage", "content": [{"type": "text", "text": token}]}),
                self.item("new-agent", "agentMessage",
                          {"type": "agentMessage", "text": "fresh only"}),
            ],
        )

        await self.run_tail()

        self.assertEqual(self.messages, [("terra", "agent", "fresh only")])

    async def test_malformed_rows_are_survived(self):
        token = self.adapter._claim_token
        now = int(time.time() * 1000)
        self.write_store(
            items=[
                ("thread-1", "turn-1", "bad", now, "not json", "agentMessage"),
                ("thread-1", "turn-1", "num", now, json.dumps({"text": 9}), "agentMessage"),
                ("thread-1", "turn-1", "u1", now,
                 json.dumps({"type": "userMessage", "content": [{"type": "text", "text": token}]}),
                 "userMessage"),
                ("thread-1", "turn-1", "a1", now,
                 json.dumps({"type": "agentMessage", "text": "still here"}), "agentMessage"),
            ],
        )

        await self.run_tail()

        self.assertEqual(self.messages, [("terra", "agent", "still here")])

    async def test_turn_boundaries_become_receipts(self):
        from partyline.adapters.receipts import BEGAN, ENDED

        started = int(self.spawned_at)
        self.write_store(turns=[("thread-1", "turn-open", "inProgress", started, None)])
        polls = {"n": 0}

        async def two_polls(*_a, **_k):
            polls["n"] += 1
            if polls["n"] == 1:
                db = sqlite3.connect(self.db_path)
                db.execute(
                    "UPDATE thread_turns SET status='completed', completed_at=? "
                    "WHERE turn_id='turn-open'",
                    (started + 1,),
                )
                db.commit()
                db.close()
            else:
                self.adapter._alive = False

        with patch.object(self.th.asyncio, "sleep", new=two_polls):
            await self.th.tail_thread_history(self.adapter, self.home, "thread-1")

        self.assertEqual(self.receipts, [(self.adapter.att, BEGAN), (self.adapter.att, ENDED)])

    async def test_a_superseded_open_turn_ends_before_the_new_one_begins(self):
        from partyline.adapters.receipts import BEGAN, ENDED

        started = int(self.spawned_at)
        self.write_store(
            items=[],
            turns=[
                ("thread-1", "aborted", "inProgress", started, None),
                ("thread-1", "next", "inProgress", started + 2, None),
            ],
        )

        await self.run_tail()

        self.assertEqual(
            self.receipts,
            [(self.adapter.att, BEGAN), (self.adapter.att, ENDED), (self.adapter.att, BEGAN)],
        )

    async def test_startup_digest_in_a_user_message_marks_the_receipt(self):
        prompt = "Continuation debrief: nonce-123 [partyline-claim: att-1/nonce22222222]"
        self.adapter._startup_prompt = prompt
        self.write_store(
            items=[
                self.item("u1", "userMessage",
                          {"type": "userMessage",
                           "content": [{"type": "text", "text": prompt}]}),
            ],
        )

        await self.run_tail()

        self.assertEqual(self.startup_marks, 1)

    async def test_agent_message_is_not_a_startup_receipt(self):
        prompt = "Continuation debrief: nonce-123 [partyline-claim: att-1/nonce22222222]"
        self.adapter._startup_prompt = prompt
        self.write_store(
            items=[
                self.item("a1", "agentMessage",
                          {"type": "agentMessage", "text": prompt}),
            ],
        )

        await self.run_tail()

        self.assertEqual(self.startup_marks, 0)

    async def test_missing_store_reports_fallback_instead_of_hanging(self):
        self.assertFalse(await self.run_tail(timeout=0.0))
        self.assertFalse(self.ready)
        self.assertEqual(self.messages, [])

    async def test_a_late_store_is_waited_for_not_refused(self):
        token = self.adapter._claim_token
        polls = {"n": 0}

        async def appear_then_stop(*_a, **_k):
            polls["n"] += 1
            if polls["n"] == 1:
                self.write_store(items=[
                    self.item("u1", "userMessage",
                              {"type": "userMessage",
                               "content": [{"type": "text", "text": token}]}),
                    self.item("a1", "agentMessage", {"type": "agentMessage", "text": "late store"}),
                ])
            else:
                self.adapter._alive = False

        with patch.object(self.th.asyncio, "sleep", new=appear_then_stop):
            opened = await self.th.tail_thread_history(
                self.adapter, self.home, "thread-1", timeout=5.0
            )

        self.assertTrue(opened)
        self.assertEqual(self.messages, [("terra", "agent", "late store")])

    async def test_a_turn_that_completes_between_polls_is_not_re_emitted(self):
        from partyline.adapters.receipts import BEGAN, ENDED

        started = int(self.spawned_at)
        self.write_store(turns=[("thread-1", "t1", "inProgress", started, None)])
        polls = {"n": 0}

        async def three_polls(*_a, **_k):
            polls["n"] += 1
            if polls["n"] == 1:
                db = sqlite3.connect(self.db_path)
                db.execute(
                    "UPDATE thread_turns SET status='completed' WHERE turn_id='t1'"
                )
                db.commit()
                db.close()
            elif polls["n"] > 2:
                self.adapter._alive = False

        with patch.object(self.th.asyncio, "sleep", new=three_polls):
            await self.th.tail_thread_history(self.adapter, self.home, "thread-1")

        self.assertEqual(self.receipts, [(self.adapter.att, BEGAN), (self.adapter.att, ENDED)])

    async def test_a_turn_already_completed_on_first_sight_begins_and_ends(self):
        from partyline.adapters.receipts import BEGAN, ENDED

        started = int(self.spawned_at)
        self.write_store(turns=[("thread-1", "t1", "completed", started, started + 1)])

        await self.run_tail()

        self.assertEqual(
            self.receipts, [(self.adapter.att, BEGAN), (self.adapter.att, ENDED)]
        )

    async def test_duplicate_item_rows_are_counted_once_across_polls(self):
        token = self.adapter._claim_token
        self.write_store(items=[
            self.item("u1", "userMessage",
                      {"type": "userMessage", "content": [{"type": "text", "text": token}]}),
            self.item("a1", "agentMessage", {"type": "agentMessage", "text": "once"}),
        ])
        polls = {"n": 0}

        async def two_polls(*_a, **_k):
            polls["n"] += 1
            if polls["n"] > 1:
                self.adapter._alive = False

        # post() clears _alive; restore it between polls so the second read runs.
        original_post = self.adapter.post

        async def post_keep_alive(sender, sender_type, body):
            await original_post(sender, sender_type, body)
            self.adapter._alive = True

        self.adapter.post = post_keep_alive
        with patch.object(self.th.asyncio, "sleep", new=two_polls):
            await self.th.tail_thread_history(self.adapter, self.home, "thread-1")

        self.assertEqual(self.messages, [("terra", "agent", "once")])

    def test_parse_helpers_treat_shapes_the_store_actually_writes(self):
        th = self.th
        self.assertIsNone(th.parse_item("contextCompaction", "{}"))
        self.assertIsNone(th.parse_item("agentMessage", "not json"))
        self.assertIsNone(th.parse_item("agentMessage", "12"))
        self.assertEqual(th.parse_item("agentMessage", '{"text": "hi"}'), {"text": "hi"})
        self.assertEqual(
            th.user_text({"content": [{"type": "text", "text": "a"}, {"type": "other"}]}),
            "a",
        )
        self.assertEqual(th.agent_text({"text": "hello"}), "hello")
        self.assertEqual(th.agent_text({"text": 9}), "")
        self.assertEqual(th.agent_text({}), "")

    async def test_reopening_a_completed_turn_reports_a_new_beginning(self):
        from partyline.adapters.receipts import BEGAN

        seen = {"t1": "completed"}
        open_turn = await self.th._emit_turn(
            self.adapter, "t1", "inProgress", seen, None
        )
        self.assertEqual(open_turn, "t1")
        self.assertEqual(self.receipts, [(self.adapter.att, BEGAN)])

    async def test_poll_errors_do_not_kill_the_tail(self):
        token = self.adapter._claim_token
        self.write_store(
            items=[
                self.item("u1", "userMessage",
                          {"type": "userMessage", "content": [{"type": "text", "text": token}]}),
                self.item("a1", "agentMessage", {"type": "agentMessage", "text": "survived"}),
            ],
        )
        real_connect = self.th.connect
        calls = {"n": 0}

        def flaky(_home):
            calls["n"] += 1
            if calls["n"] == 1:
                raise sqlite3.OperationalError("database is locked")
            return real_connect(_home)

        with patch.object(self.th, "connect", new=flaky):
            async def one_sleep(*_a, **_k):
                if calls["n"] >= 2:
                    self.adapter._alive = False

            with patch.object(self.th.asyncio, "sleep", new=one_sleep):
                await self.th.tail_thread_history(self.adapter, self.home, "thread-1")

        self.assertEqual(self.messages, [("terra", "agent", "survived")])

    async def test_resume_prefers_thread_history_over_the_rollout_tail(self):
        """The 0.156 finding as a control: no new rollout is written, so the
        resumed turn must come from the sqlite store, not a forked file."""
        token = self.adapter._claim_token
        self.write_store(
            items=[
                self.item("u1", "userMessage",
                          {"type": "userMessage", "content": [{"type": "text", "text": token}]}),
                self.item("a1", "agentMessage", {"type": "agentMessage", "text": "from sqlite"}),
            ],
            turns=[("thread-1", "turn-1", "completed", 1, 2)],
        )
        adapter = self.adapter
        adapter._fresh = lambda ts: True
        adapter._find_rollout = lambda: self.fail("resume must not hunt a new rollout")
        adapter._tail_jsonl = lambda *a, **k: self.fail("resume must not tail a rollout")

        async def quiet_sleep(*_a, **_k):
            return None

        with patch("partyline.adapters.bundled.codex.adapter.asyncio.sleep", new=quiet_sleep):
            await adapter._run()

        self.assertEqual(self.messages, [("terra", "agent", "from sqlite")])


if __name__ == "__main__":
    unittest.main()
