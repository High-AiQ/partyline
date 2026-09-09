"""A wake Grok offloaded to a file is still a wake it received.

The record shape here is not invented: it is the structure of root Grok's
`prompt_index=54` on 2026-09-09, captured while the session still held it.
Grok replaced a 183,885-character paste with a head/tail preview and a pointer
line, and the receipt matcher compared that preview against the full digest —
so nine deliveries were pasted, read, and never credited.

The regression is deliberately synthetic rather than a captured fixture: the
preview boundary, the byte count in the marker, and the prose around the
pointer are all Grok's to change, and a test pinned to them would fail for
reasons that have nothing to do with the receipt. What must not change is that
a session-owned prompt file for *this* ordinal credits, and that nothing else
does.
"""

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock

from partyline.adapters.bundled.grok import offloaded_prompt
from partyline.adapters.bundled.grok.adapter import PartylineAdapter
from partyline.adapters.bundled.grok.offloaded_prompt import session_prompt_path

DIGEST = "[greg]: @groky the wake that was too large to store inline"
SESSION_ID = "12345678-1234-4234-8234-123456789abc"


async def _noop(*args):
    pass


def receipt_adapter() -> PartylineAdapter:
    """A Grok adapter with nothing running: only the receipt path is exercised."""
    adapter = PartylineAdapter(
        {
            "adapter_metadata": {"env_unset": []},
            "command": ["grok"],
            "cli_session": None,
            "conv_name": "grok tests",
            "cwd": "/tmp/grok-project",
            "id": SESSION_ID,
            "name": "groky",
            "resume": False,
        },
        _noop,
        _noop,
    )
    adapter._silent_until_wake = False
    return adapter


def offloaded_record(prompt_index: int, path: Path, *, preview: str = DIGEST[:20]) -> dict:
    """Grok's large-prompt shape: truncated envelope, then a pointer footer."""
    return {
        "type": "user",
        "prompt_index": prompt_index,
        "content": [{
            "type": "text",
            "text": (
                f"<user_query>\n{preview}\n</user_query>\n\n"
                "[Full request offloaded to file] The text above was truncated "
                "(185489 bytes total). The user's FULL request — which may include "
                "their actual question and any skill instructions not shown above — "
                f"is in this file:\n{path}\n"
                "Read this file with read_file before responding; the question you "
                "must answer may only be there."
            ),
        }],
    }


class OffloadedPromptTest(unittest.TestCase):
    def test_the_allowed_path_is_derived_from_the_transcript_not_the_record(self):
        transcript = Path(
            "/home/agent/.grok/sessions/%2Fhome%2Fagent%2Fproject/"
            "f1a2fd5f-1c36-4d21-978c-c8d41e1e6696/chat_history.jsonl"
        )

        self.assertEqual(
            session_prompt_path(transcript, 54),
            transcript.parent / "prompts" / "prompt_54.txt",
        )

    def test_only_this_ordinals_file_in_this_session_resolves(self):
        with tempfile.TemporaryDirectory() as directory:
            session = Path(directory) / "session"
            (session / "prompts").mkdir(parents=True)
            transcript = session / "chat_history.jsonl"
            mine = session_prompt_path(transcript, 54)
            mine.write_text(f"<user_query>\n{DIGEST}\n</user_query>", encoding="utf-8")
            neighbour = session_prompt_path(transcript, 53)
            neighbour.write_text("someone else's prompt", encoding="utf-8")
            elsewhere = Path(directory) / "secret.txt"
            elsewhere.write_text("not part of this session", encoding="utf-8")

            body = offloaded_record(54, mine)["content"][0]["text"]
            self.assertEqual(offloaded_prompt.resolve(body, 54, transcript), DIGEST)

            # Same file, wrong ordinal: the ordinal picks the file, so the
            # record's own path is simply not the one we are allowed to read.
            self.assertIsNone(offloaded_prompt.resolve(body, 55, transcript))

            for pointed in (
                neighbour,
                elsewhere,
                Path(f"{session}/prompts/../../secret.txt"),
                Path("/etc/passwd"),
            ):
                self.assertIsNone(
                    offloaded_prompt.resolve(
                        offloaded_record(54, pointed)["content"][0]["text"],
                        54,
                        transcript,
                    ),
                    f"{pointed} is not this session's prompt 54",
                )

    def test_an_unreadable_or_absent_file_resolves_to_nothing(self):
        with tempfile.TemporaryDirectory() as directory:
            session = Path(directory) / "session"
            (session / "prompts").mkdir(parents=True)
            transcript = session / "chat_history.jsonl"
            expected = session_prompt_path(transcript, 54)
            body = offloaded_record(54, expected)["content"][0]["text"]

            self.assertIsNone(offloaded_prompt.resolve(body, 54, transcript))

            expected.write_text("   \n", encoding="utf-8")
            self.assertIsNone(offloaded_prompt.resolve(body, 54, transcript))

            at_cap = f"<user_query>\n{DIGEST}\n</user_query>"
            expected.write_text(at_cap, encoding="utf-8")
            original = offloaded_prompt.MAX_PROMPT_BYTES
            try:
                offloaded_prompt.MAX_PROMPT_BYTES = len(at_cap) - 1
                self.assertIsNone(offloaded_prompt.resolve(body, 54, transcript))

                # Exactly at the cap is not over it, and the read still stops
                # cleanly rather than spinning for a byte that never comes.
                offloaded_prompt.MAX_PROMPT_BYTES = len(at_cap)
                self.assertEqual(offloaded_prompt.resolve(body, 54, transcript), DIGEST)
            finally:
                offloaded_prompt.MAX_PROMPT_BYTES = original

    def test_a_symlink_at_the_computed_name_reads_nothing(self):
        """The one name this module opens is also the one an attacker can plant.

        Grok probed exactly this against the first draft and got the outside
        file's contents back, so it is a regression, not a hypothetical.
        """
        with tempfile.TemporaryDirectory() as directory:
            session = Path(directory) / "session"
            (session / "prompts").mkdir(parents=True)
            transcript = session / "chat_history.jsonl"
            outside = Path(directory) / "outside.txt"
            outside.write_text(f"<user_query>\n{DIGEST}\n</user_query>", encoding="utf-8")
            expected = session_prompt_path(transcript, 54)
            expected.symlink_to(outside)
            body = offloaded_record(54, expected)["content"][0]["text"]

            self.assertIsNone(offloaded_prompt.resolve(body, 54, transcript))

    def test_a_symlinked_prompts_directory_reads_nothing(self):
        with tempfile.TemporaryDirectory() as directory:
            session = Path(directory) / "session"
            session.mkdir(parents=True)
            transcript = session / "chat_history.jsonl"
            elsewhere = Path(directory) / "elsewhere"
            elsewhere.mkdir()
            (elsewhere / "prompt_54.txt").write_text(
                f"<user_query>\n{DIGEST}\n</user_query>", encoding="utf-8"
            )
            (session / "prompts").symlink_to(elsewhere, target_is_directory=True)
            body = offloaded_record(
                54, session_prompt_path(transcript, 54)
            )["content"][0]["text"]

            self.assertIsNone(offloaded_prompt.resolve(body, 54, transcript))

    def test_a_fifo_is_refused_rather_than_read(self):
        with tempfile.TemporaryDirectory() as directory:
            session = Path(directory) / "session"
            (session / "prompts").mkdir(parents=True)
            transcript = session / "chat_history.jsonl"
            expected = session_prompt_path(transcript, 54)
            os.mkfifo(expected)
            body = offloaded_record(54, expected)["content"][0]["text"]

            # A blocking open would hang the transcript tail, so this test
            # timing out is itself the failure signal.
            self.assertIsNone(offloaded_prompt.resolve(body, 54, transcript))

    def test_a_record_without_the_marker_is_never_a_file_read(self):
        with tempfile.TemporaryDirectory() as directory:
            session = Path(directory) / "session"
            (session / "prompts").mkdir(parents=True)
            transcript = session / "chat_history.jsonl"
            session_prompt_path(transcript, 54).write_text(DIGEST, encoding="utf-8")

            self.assertIsNone(offloaded_prompt.resolve(DIGEST, 54, transcript))
            self.assertIsNone(offloaded_prompt.resolve(DIGEST, 54, None))


class OffloadedWakeCreditTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.session = Path(self.directory.name) / "session"
        (self.session / "prompts").mkdir(parents=True)
        self.transcript = self.session / "chat_history.jsonl"
        self.adapter = receipt_adapter()
        self.adapter._transcript = lambda: self.transcript
        self.adapter.send_keys = AsyncMock()
        self.adapter.format_digest = lambda _messages: DIGEST
        self.credited = AsyncMock(return_value=True)
        self.adapter.att["confirm_delivery_ids"] = self.credited

    def tearDown(self):
        self.directory.cleanup()

    def write_prompt(self, prompt_index: int, text: str) -> Path:
        path = session_prompt_path(self.transcript, prompt_index)
        path.write_text(f"<user_query>\n{text}\n</user_query>", encoding="utf-8")
        return path

    async def test_an_offloaded_record_credits_the_wake_it_carried(self):
        self.assertFalse(await self.adapter.deliver([{"id": 41}]))
        path = self.write_prompt(54, DIGEST)

        await self.adapter._note_user_record(offloaded_record(54, path))

        self.credited.assert_awaited_once_with([41])

    async def test_the_offloaded_file_must_still_match_the_digest_exactly(self):
        self.assertFalse(await self.adapter.deliver([{"id": 41}]))
        path = self.write_prompt(54, DIGEST + " plus something nobody sent")

        await self.adapter._note_user_record(offloaded_record(54, path))

        self.credited.assert_not_awaited()

    async def test_a_stale_ordinal_is_still_refused_before_any_file_is_read(self):
        self.assertFalse(await self.adapter.deliver([{"id": 41}]))
        path = self.write_prompt(54, DIGEST)
        self.adapter._wake_receipts.seed(54, self.adapter)

        await self.adapter._note_user_record(offloaded_record(54, path))

        self.credited.assert_not_awaited()

    async def test_an_unresolvable_offload_leaves_the_wake_outstanding(self):
        self.assertFalse(await self.adapter.deliver([{"id": 41}]))
        missing = session_prompt_path(self.transcript, 54)

        await self.adapter._note_user_record(offloaded_record(54, missing))
        self.credited.assert_not_awaited()

        # The wake is still pending, so the file appearing later still credits.
        self.write_prompt(55, DIGEST)
        await self.adapter._note_user_record(
            offloaded_record(55, session_prompt_path(self.transcript, 55))
        )
        self.credited.assert_awaited_once_with([41])

    async def test_an_adapter_without_a_transcript_credits_nothing(self):
        self.adapter._transcript = lambda: None
        self.assertFalse(await self.adapter.deliver([{"id": 41}]))
        path = self.write_prompt(54, DIGEST)

        await self.adapter._note_user_record(offloaded_record(54, path))

        self.credited.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
