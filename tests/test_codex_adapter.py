"""Startup-delivery contract for the private Codex adapter."""

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

        self.assertIn('version = "1.0.3"', manifest)

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
    def setUp(self):
        # reset claimed set between tests
        from partyline.adapters.bundled.codex.adapter import PartylineAdapter as CodexAdapter

        CodexAdapter._CLAIMED.clear()
        self.addCleanup(CodexAdapter._CLAIMED.clear)

    def make_adapter(self, **extra):
        import asyncio

        adapter = PartylineAdapter.__new__(PartylineAdapter)
        adapter.att = {"cwd": "/work", "cli_session": "session-1", "id": "att-1", **extra}
        adapter.spawned_at = 1000.0
        adapter.resume = False
        adapter._CLAIMED = PartylineAdapter._CLAIMED
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

    def test_find_rollout_matches_cwd_and_claims(self):
        import json
        import tempfile
        from pathlib import Path
        from unittest.mock import patch

        from partyline.adapters.bundled.codex.adapter import PartylineAdapter

        with tempfile.TemporaryDirectory() as tmp:
            rollout = Path(tmp) / "rollout-1.jsonl"
            rollout.write_text(
                json.dumps(
                    {"type": "session_meta", "payload": {"id": "sess-1", "cwd": "/work", "source": {}}}
                )
                + "\n",
                encoding="utf-8",
            )
            adapter = self.make_adapter()
            with (
                patch(
                    "partyline.adapters.bundled.codex.adapter.glob.glob",
                    return_value=[str(rollout)],
                ),
                patch(
                    "partyline.adapters.bundled.codex.adapter.os.path.getmtime",
                    return_value=999.9,
                ),
            ):
                found = adapter._find_rollout()
            self.assertEqual(found, str(rollout))
            self.assertIn(str(rollout), PartylineAdapter._CLAIMED)

    def test_find_rollout_skips_claimed_and_stale(self):
        import json
        import tempfile
        from pathlib import Path
        from unittest.mock import patch

        from partyline.adapters.bundled.codex.adapter import PartylineAdapter

        with tempfile.TemporaryDirectory() as tmp:
            rollout = Path(tmp) / "rollout-2.jsonl"
            rollout.write_text(
                json.dumps({"type": "session_meta", "payload": {"id": "sess-2", "cwd": "/work"}}) + "\n",
                encoding="utf-8",
            )
            PartylineAdapter._CLAIMED.add(str(rollout))
            adapter = self.make_adapter()
            # claimed path should be skipped -> None
            with (
                patch(
                    "partyline.adapters.bundled.codex.adapter.glob.glob",
                    return_value=[str(rollout)],
                ),
                patch(
                    "partyline.adapters.bundled.codex.adapter.os.path.getmtime",
                    return_value=999.9,
                ),
            ):
                self.assertIsNone(adapter._find_rollout())
            PartylineAdapter._CLAIMED.clear()
            # stale mtime should be skipped
            with (
                patch(
                    "partyline.adapters.bundled.codex.adapter.glob.glob",
                    return_value=[str(rollout)],
                ),
                patch(
                    "partyline.adapters.bundled.codex.adapter.os.path.getmtime",
                    return_value=900.0,
                ),
            ):
                self.assertIsNone(adapter._find_rollout())

    def test_find_rollout_filters_by_source_and_resume(self):
        import json
        import tempfile
        from pathlib import Path
        from unittest.mock import mock_open, patch


        def fake_open(path, *args, **kwargs):
            payloads = {
                "bad-type": {"type": "other", "payload": {"id": "x", "cwd": "/work"}},
                "subagent": {
                    "type": "session_meta",
                    "payload": {"id": "x", "cwd": "/work", "source": {"subagent": True}},
                },
                "resume-mismatch": {
                    "type": "session_meta",
                    "payload": {"id": "other", "cwd": "/work", "forked_from_id": "other"},
                },
                "resume-match": {
                    "type": "session_meta",
                    "payload": {"id": "new", "forked_from_id": "session-1", "cwd": "/work"},
                },
                "cwd-mismatch": {
                    "type": "session_meta",
                    "payload": {"id": "x", "cwd": "/other"},
                },
            }
            key = Path(path).stem
            data = payloads.get(key, payloads["bad-type"])
            m = mock_open(read_data=json.dumps(data) + "\n")
            return m(path, *args, **kwargs)

        with tempfile.TemporaryDirectory() as tmp:
            paths = [
                str(Path(tmp) / "bad-type.jsonl"),
                str(Path(tmp) / "subagent.jsonl"),
                str(Path(tmp) / "cwd-mismatch.jsonl"),
            ]
            adapter = self.make_adapter()
            with patch(
                "partyline.adapters.bundled.codex.adapter.glob.glob", return_value=paths
            ), patch(
                "partyline.adapters.bundled.codex.adapter.os.path.getmtime", return_value=999.9
            ), patch(
                "partyline.adapters.bundled.codex.adapter.open", side_effect=fake_open
            ):
                self.assertIsNone(adapter._find_rollout())
            # resume match should succeed
            paths2 = [str(Path(tmp) / "resume-match.jsonl"), str(Path(tmp) / "resume-mismatch.jsonl")]
            adapter2 = self.make_adapter()
            adapter2.resume = True
            with patch(
                "partyline.adapters.bundled.codex.adapter.glob.glob", return_value=paths2
            ), patch(
                "partyline.adapters.bundled.codex.adapter.os.path.getmtime", return_value=999.9
            ), patch(
                "partyline.adapters.bundled.codex.adapter.open", side_effect=fake_open
            ):
                found = adapter2._find_rollout()
                self.assertEqual(found, str(Path(tmp) / "resume-match.jsonl"))

    def test_find_rollout_handles_os_and_json_errors(self):
        from unittest.mock import patch

        adapter = self.make_adapter()

        def bad_open(path, *args, **kwargs):
            raise OSError("no read")

        with patch(
            "partyline.adapters.bundled.codex.adapter.glob.glob", return_value=["/tmp/bad.jsonl"]
        ), patch(
            "partyline.adapters.bundled.codex.adapter.os.path.getmtime", return_value=999.9
        ), patch("partyline.adapters.bundled.codex.adapter.open", side_effect=bad_open):
            self.assertIsNone(adapter._find_rollout())

        def json_error_open(path, *args, **kwargs):
            from unittest.mock import mock_open

            m = mock_open(read_data="not json\n")
            return m(path, *args, **kwargs)

        with patch(
            "partyline.adapters.bundled.codex.adapter.glob.glob", return_value=["/tmp/bad2.jsonl"]
        ), patch(
            "partyline.adapters.bundled.codex.adapter.os.path.getmtime", return_value=999.9
        ), patch("partyline.adapters.bundled.codex.adapter.open", side_effect=json_error_open):
            self.assertIsNone(adapter._find_rollout())

    async def test_stop_releases_claimed_rollout(self):
        from partyline.adapters.bundled.codex.adapter import PartylineAdapter

        adapter = self.make_adapter()
        fake_path = "/tmp/fake-rollout.jsonl"
        PartylineAdapter._CLAIMED.add(fake_path)
        adapter._rollout = fake_path
        await adapter.stop()
        self.assertNotIn(fake_path, PartylineAdapter._CLAIMED)


if __name__ == "__main__":
    unittest.main()
