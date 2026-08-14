"""Vendor-free contract tests for the Claude Code adapter."""

import json
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from partyline.adapters.bundled.claude.adapter import PartylineAdapter


class ClaudeCommandTest(unittest.TestCase):
    def make_adapter(self, *, command: list[str], resume: bool, hook_url: str | None = None):
        """Build only the pure argv seam; no pty or Claude CLI is involved."""
        adapter = PartylineAdapter.__new__(PartylineAdapter)
        adapter.att = {"command": command, "id": "attachment-1"}
        if hook_url is not None:
            adapter.att["hook_url"] = hook_url
        adapter.resume = resume
        return adapter

    def test_fresh_command_gets_one_session_id(self):
        adapter = self.make_adapter(command=["claude", "--model", "opus"], resume=False)

        self.assertEqual(
            adapter.build_command(),
            ["claude", "--model", "opus", "--session-id", "attachment-1"],
        )

    def test_existing_session_id_is_not_duplicated(self):
        adapter = self.make_adapter(
            command=["claude", "--session-id", "chosen-by-user"], resume=False,
        )

        self.assertEqual(adapter.build_command(), ["claude", "--session-id", "chosen-by-user"])

    def test_resume_command_uses_the_attachment_id(self):
        adapter = self.make_adapter(command=["claude", "--model", "opus"], resume=True)

        self.assertEqual(
            adapter.build_command(),
            ["claude", "--model", "opus", "--resume", "attachment-1"],
        )

    def test_notification_hook_is_structured_settings_not_a_vendor_invocation(self):
        adapter = self.make_adapter(
            command=["claude"], resume=False,
            hook_url="https://hooks.example.test/notify?line=partyline&kind=agent",
        )

        command = adapter.build_command()
        settings = json.loads(command[command.index("--settings") + 1])
        hook = settings["hooks"]["Notification"][0]["hooks"][0]

        self.assertEqual(hook["type"], "command")
        self.assertIn("curl -s -m 5 -X POST", hook["command"])
        self.assertIn("hooks.example.test", hook["command"])
        self.assertIn("--data-binary @-", hook["command"])

    def test_existing_settings_are_not_replaced(self):
        adapter = self.make_adapter(
            command=["claude", "--settings", "existing.json"],
            resume=False,
            hook_url="https://hooks.example.test/notify",
        )

        self.assertEqual(
            adapter.build_command(),
            ["claude", "--settings", "existing.json", "--session-id", "attachment-1"],
        )


class ClaudeTranscriptTest(unittest.IsolatedAsyncioTestCase):
    fixture = (
        Path(__file__).parent.parent
        / "partyline"
        / "adapters"
        / "bundled"
        / "claude"
        / "fixtures"
        / "transcript.jsonl"
    )

    def make_adapter(self, posts: list[tuple[str, str, str]]) -> PartylineAdapter:
        async def post(sender: str, sender_type: str, body: str) -> None:
            posts.append((sender, sender_type, body))

        async def on_status(status: str) -> None:
            return None

        adapter = PartylineAdapter(
            {
                "command": ["claude"],
                "id": "attachment-1",
                "name": "claude",
                "cwd": "/work",
                "resume": True,
            },
            post,
            on_status,
        )
        # This test isolates transcript parsing. The process has already received a real wake.
        adapter._silent_until_wake = False
        adapter.alive = lambda: True
        adapter._fresh = lambda timestamp: timestamp == "fresh"
        return adapter

    async def test_transcript_posts_only_fresh_unique_assistant_text(self):
        posts: list[tuple[str, str, str]] = []
        adapter = self.make_adapter(posts)

        async def tail(path: str, handle) -> None:
            self.assertEqual(path, "fixture.jsonl")
            for line in self.fixture.read_text(encoding="utf-8").splitlines():
                await handle(json.loads(line))

        adapter._tail_jsonl = tail
        with (
            patch("partyline.adapters.bundled.claude.adapter.asyncio.sleep", AsyncMock()),
            patch("partyline.adapters.bundled.claude.adapter.glob.glob", return_value=["fixture.jsonl"]),
        ):
            await adapter._run()

        self.assertEqual(posts, [("claude", "agent", "first answer\n\nsecond paragraph")])

    async def test_run_waits_for_transcript_and_retries_briefing(self):
        posts: list[tuple[str, str, str]] = []
        adapter = self.make_adapter(posts)
        adapter.alive = lambda: True
        adapter._fresh = lambda timestamp: True

        # Simulate transcript appearing after two empty globs, then found
        globs = [[], [], ["found.jsonl"]]

        async def fake_tail(path, handle):
            await handle(
                {
                    "type": "assistant",
                    "timestamp": "fresh",
                    "uuid": "u1",
                    "message": {"content": [{"type": "text", "text": "hi"}]},
                }
            )

        adapter._tail_jsonl = fake_tail
        with (
            patch("partyline.adapters.bundled.claude.adapter.asyncio.sleep", AsyncMock()),
            patch("partyline.adapters.bundled.claude.adapter.glob.glob", side_effect=globs),
            patch.object(adapter, "send_keys", AsyncMock()) as mock_keys,
        ):
            await adapter._run()
        # briefing sent once at start, and transcript found
        self.assertTrue(mock_keys.called)
        self.assertEqual(posts, [("claude", "agent", "hi")])


if __name__ == "__main__":
    unittest.main()
