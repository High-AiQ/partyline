"""Startup-delivery contract for the private Codex adapter."""

import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from partyline.adapters.bundled.codex.adapter import PartylineAdapter


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


class CodexDiscoveryTest(unittest.TestCase):
    def setUp(self):
        # reset claimed set between tests
        from partyline.adapters.bundled.codex.adapter import PartylineAdapter as CodexAdapter

        CodexAdapter._CLAIMED.clear()
        self.addCleanup(CodexAdapter._CLAIMED.clear)

    def make_adapter(self, **extra):
        adapter = PartylineAdapter.__new__(PartylineAdapter)
        adapter.att = {"cwd": "/work", "cli_session": "session-1", "id": "att-1", **extra}
        adapter.spawned_at = 1000.0
        adapter.resume = False
        adapter._CLAIMED = PartylineAdapter._CLAIMED
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
            name = Path(path).name
            # map filename to payload key
            key = name.split("-")[0]
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


if __name__ == "__main__":
    unittest.main()
