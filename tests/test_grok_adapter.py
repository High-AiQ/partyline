"""Deterministic coverage for the bundled Grok Build adapter."""

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from partyline.adapters.bundled.grok.adapter import PartylineAdapter


SESSION_ID = "12345678-1234-4234-8234-123456789abc"


async def post(sender, sender_type, body):
    pass


async def status(value):
    pass


def make_adapter(*, command=None, resume=False, session_id=None):
    return PartylineAdapter(
        {
            "adapter_metadata": {"env_unset": []},
            "command": list(command if command is not None else ["grok"]),
            "cli_session": session_id,
            "conv_name": "grok tests",
            "cwd": "/tmp/grok-project",
            "id": SESSION_ID,
            "name": "groky",
            "resume": resume,
        },
        post,
        status,
    )


class ManifestTest(unittest.TestCase):
    def test_manifest_declares_resumable_interactive_grok(self):
        root = Path(__file__).parents[1] / "partyline" / "adapters" / "bundled" / "grok"
        manifest = (root / "adapter.toml").read_text(encoding="utf-8")

        self.assertIn('command = ["grok", "--permission-mode", "bypassPermissions"]', manifest)
        self.assertIn("resume = true", manifest)


class CommandTest(unittest.TestCase):
    def test_fresh_command_pins_a_uuid_and_passes_the_briefing_as_prompt(self):
        adapter = make_adapter()
        self.assertEqual(
            adapter.build_command(),
            ["grok", "--session-id", SESSION_ID, adapter.briefing()],
        )

    def test_resume_uses_stored_uuid(self):
        adapter = make_adapter(resume=True, session_id=SESSION_ID)

        self.assertEqual(adapter.build_command(), ["grok", "--resume", SESSION_ID])

    def test_resume_without_a_stored_uuid_is_refused(self):
        with self.assertRaisesRegex(ValueError, "stored session UUID"):
            make_adapter(resume=True).build_command()

    def test_user_supplied_session_id_is_refused(self):
        with self.assertRaisesRegex(ValueError, "managed by Partyline"):
            make_adapter(command=["grok", "--session-id", "not-ours"]).build_command()

    def test_equals_form_of_user_supplied_session_id_is_refused(self):
        with self.assertRaisesRegex(ValueError, "managed by Partyline"):
            make_adapter(command=["grok", f"--session-id={SESSION_ID}"]).build_command()


class TranscriptTest(unittest.TestCase):
    def test_only_assistant_speech_is_relayed(self):
        self.assertEqual(PartylineAdapter._assistant_text({"type": "assistant", "content": "hi"}), "hi")
        self.assertEqual(
            PartylineAdapter._assistant_text({"type": "assistant", "content": [
                {"type": "text", "text": "first"},
                {"type": "tool_use", "name": "read"},
                {"type": "text", "text": "second"},
            ]}),
            "first\n\nsecond",
        )
        self.assertIsNone(PartylineAdapter._assistant_text({"type": "reasoning", "content": "secret"}))
        self.assertIsNone(PartylineAdapter._assistant_text({"type": "assistant", "content": []}))

    def test_pinned_uuid_requires_one_exact_transcript(self):
        adapter = make_adapter()
        adapter._session_id = SESSION_ID
        expected = Path("/tmp/sessions/cwd") / SESSION_ID / "chat_history.jsonl"
        with patch("partyline.adapters.bundled.grok.adapter.glob.glob", return_value=[str(expected)]):
            self.assertEqual(adapter._transcript(), expected)
        with patch("partyline.adapters.bundled.grok.adapter.glob.glob", return_value=[]):
            self.assertIsNone(adapter._transcript())


class ResumeOffsetTest(unittest.IsolatedAsyncioTestCase):
    async def test_failed_pre_spawn_stat_seeks_to_end_without_replaying_history(self):
        """Regression for the exact state left by Grok's OSError path."""
        posted = []

        async def collect(sender, sender_type, body):
            posted.append((sender, sender_type, body))

        with tempfile.TemporaryDirectory() as home:
            transcript = (
                Path(home) / ".grok" / "sessions" / "%2Ftmp%2Fgrok-project"
                / SESSION_ID / "chat_history.jsonl"
            )
            transcript.parent.mkdir(parents=True)
            transcript.write_text(
                '{"type":"assistant","content":"old reply"}\n', encoding="utf-8",
            )
            adapter = make_adapter(resume=True, session_id=SESSION_ID)
            adapter._post_to_chat = collect
            adapter._resume_offset = None
            adapter.alive = lambda: False
            with patch.dict(os.environ, {"HOME": home}):
                await adapter._run()

        self.assertEqual(posted, [])
