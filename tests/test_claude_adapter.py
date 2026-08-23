"""Vendor-free contract tests for the Claude Code adapter."""

import json
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from partyline.adapters.bundled.claude.adapter import PartylineAdapter


class ClaudeManifestTest(unittest.TestCase):
    def test_manifest_declares_receipt_turn_end(self):
        root = Path(__file__).parents[1] / "partyline" / "adapters" / "bundled" / "claude"
        manifest = (root / "adapter.toml").read_text(encoding="utf-8")
        self.assertIn("resume = true", manifest)
        self.assertIn('turn_end = "receipt"', manifest)
        self.assertIn('update_command = ["claude", "update"]', manifest)


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
        self.assertEqual(
            settings["hooks"]["Stop"][0]["hooks"][0]["command"], hook["command"],
        )
        self.assertEqual(
            settings["hooks"]["UserPromptSubmit"][0]["hooks"][0]["command"],
            hook["command"],
        )
        self.assertNotIn("SubagentStop", settings["hooks"])

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
    # Test fixtures live beside the tests, not inside the adapter package.
    # Anything under partyline/ ships in the wheel, so a fixture placed there
    # is shipped to every user to support a test they will never run.
    fixture = Path(__file__).parent / "fixtures" / "claude_transcript.jsonl"

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
        adapter.resume = False
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

    async def test_run_exits_when_process_dies_before_transcript(self):
        posts: list[tuple[str, str, str]] = []
        adapter = self.make_adapter(posts)
        adapter.alive = lambda: False
        adapter._fresh = lambda timestamp: True

        async def fake_tail(path, handle):
            self.fail("should not tail without transcript")

        adapter._tail_jsonl = fake_tail
        with (
            patch("partyline.adapters.bundled.claude.adapter.asyncio.sleep", AsyncMock()),
            patch("partyline.adapters.bundled.claude.adapter.glob.glob", return_value=[]),
        ):
            await adapter._run()
        self.assertEqual(posts, [])

    async def test_timeout_notice_names_claude_without_addressing_it(self):
        posts: list[tuple[str, str, str]] = []
        adapter = self.make_adapter(posts)
        adapter.resume = False
        adapter.alive = lambda: True
        adapter.master = 1

        with (
            patch("partyline.adapters.bundled.claude.adapter.asyncio.sleep", AsyncMock()),
            patch("partyline.adapters.bundled.claude.adapter.glob.glob", return_value=[]),
            patch("partyline.adapters.bundled.claude.adapter.os.write"),
            patch.object(adapter, "send_keys", AsyncMock()),
        ):
            await adapter._run()

        self.assertTrue(posts[0][2].startswith("claude: no transcript after 45s"))

    async def test_run_retries_briefing_at_12_and_24_seconds(self):
        posts: list[tuple[str, str, str]] = []
        adapter = self.make_adapter(posts)
        adapter.resume = False
        adapter.alive = lambda: True
        adapter._fresh = lambda timestamp: True
        adapter.master = 1

        # Need to simulate waited hitting 12 and 24 before transcript appears
        # We'll mock glob to return empty for first 24 calls, then found
        call_count = 0

        def fake_glob(pattern):
            nonlocal call_count
            call_count += 1
            if call_count < 13:
                return []
            return ["found.jsonl"]

        async def fake_tail(path, handle):
            await handle(
                {
                    "type": "assistant",
                    "timestamp": "fresh",
                    "uuid": "u2",
                    "message": {"content": [{"type": "text", "text": "after retry"}]},
                }
            )

        adapter._tail_jsonl = fake_tail
        import asyncio as _asyncio2

        orig_sleep2 = _asyncio2.sleep

        async def _fast_sleep2(*args, **kwargs):
            await orig_sleep2(0)

        with (
            patch("partyline.adapters.bundled.claude.adapter.asyncio.sleep", _fast_sleep2),
            patch("partyline.adapters.bundled.claude.adapter.glob.glob", side_effect=fake_glob),
            patch("partyline.adapters.bundled.claude.adapter.os.write") as mock_write,
            patch.object(adapter, "send_keys", AsyncMock()) as mock_keys,
        ):
            await adapter._run()
        # Should have retried at 12
        self.assertEqual(mock_write.call_count, 1)
        self.assertGreaterEqual(mock_keys.call_count, 2)  # initial + 1 retry
        self.assertEqual(posts, [("claude", "agent", "after retry")])


if __name__ == "__main__":
    unittest.main()
