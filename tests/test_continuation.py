"""Unit coverage for the continuation-receipt oracle.

The oracle is the whole value here. Three earlier ones each gave a confident
wrong answer about the same restart — the database cursor said delivered, the
terminal screen said lost for a process that had received it, and a plain
transcript grep said two of three when the truth was none. So these tests are
mostly about what must *not* count as receipt.
"""

import contextlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.continuation import Receipt, is_input_record, read_receipt, report  # noqa: E402

NONCE = "nonce-7f3a91"


def transcript(*records) -> Path:
    handle = tempfile.NamedTemporaryFile("w", suffix=".jsonl", delete=False, encoding="utf-8")
    for record in records:
        handle.write(json.dumps(record) + "\n")
    handle.close()
    return Path(handle.name)


def wake(text):
    """What a partyline delivery actually looks like in a codex rollout."""
    return {"payload": {"type": "user_message", "message": f"[opus]: {text}"}}


def mirrored_wake(text):
    """The same delivery, in the shape some CLIs also record it as."""
    return {"payload": {"type": "message", "role": "user",
                        "content": [{"type": "input_text", "text": text}]}}


def tool_call(text):
    """An agent *running* a command containing the text — e.g. the very
    `cockpit plan --debrief "…"` that created the plan."""
    return {"payload": {"type": "custom_tool_call", "name": "exec", "input": text}}


def tool_output(text):
    """An agent dumping the database while investigating the bug."""
    return {"payload": {"type": "custom_tool_call_output", "output": text}}


class InputRecordTest(unittest.TestCase):
    def test_a_delivered_wake_counts(self):
        self.assertTrue(is_input_record(wake(NONCE), NONCE))

    def test_the_mirrored_shape_counts_too(self):
        self.assertTrue(is_input_record(mirrored_wake(NONCE), NONCE))

    def test_an_agents_own_command_does_not_count(self):
        # This is the exact confound that made a naive grep report success:
        # the command that *created* the plan contains the debrief text.
        self.assertFalse(is_input_record(tool_call(NONCE), NONCE))

    def test_an_agents_own_database_dump_does_not_count(self):
        self.assertFalse(is_input_record(tool_output(NONCE), NONCE))

    def test_a_record_without_the_phrase_does_not_count(self):
        self.assertFalse(is_input_record(wake("something else"), NONCE))

    def test_a_malformed_payload_is_not_receipt(self):
        self.assertFalse(is_input_record({"payload": "not-a-dict"}, NONCE))


class ReadReceiptTest(unittest.TestCase):
    def test_a_process_that_was_told_reports_received(self):
        path = transcript(tool_call("unrelated"), wake(NONCE))
        receipt = read_receipt("sol", path, NONCE)
        self.assertTrue(receipt.received)
        self.assertEqual(receipt.delivered, 1)

    def test_a_process_that_only_investigated_reports_lost(self):
        """The night this was written, two processes looked like they had
        received the debrief purely because they had been looking into why it
        was missing."""
        path = transcript(tool_call(NONCE), tool_output(NONCE))
        receipt = read_receipt("terra", path, NONCE)
        self.assertFalse(receipt.received)
        self.assertEqual(receipt.delivered, 0)
        self.assertEqual(receipt.artefacts, 2)

    def test_an_empty_transcript_reports_lost(self):
        receipt = read_receipt("luna", transcript(), NONCE)
        self.assertFalse(receipt.received)

    def test_unparseable_lines_are_skipped_rather_than_fatal(self):
        path = transcript(wake(NONCE))
        path.write_text(f"{{not json but contains {NONCE}\n" + path.read_text(), encoding="utf-8")
        self.assertTrue(read_receipt("sol", path, NONCE).received)

    def test_artefacts_are_counted_separately_so_the_report_can_explain_itself(self):
        path = transcript(tool_call(NONCE), wake(NONCE))
        receipt = read_receipt("sol", path, NONCE)
        self.assertEqual((receipt.delivered, receipt.artefacts), (1, 1))
        self.assertIn("investigation artefact", receipt.describe())


class ReportTest(unittest.TestCase):
    """`report` prints; the tests care about its verdict, not its noise."""

    @staticmethod
    def verdict(receipts):
        with contextlib.redirect_stdout(io.StringIO()):
            return report(receipts)

    def test_all_received_is_a_pass(self):
        self.assertEqual(self.verdict([Receipt("sol", 1, 0), Receipt("luna", 1, 0)]), 0)

    def test_any_loss_is_a_failure(self):
        self.assertEqual(self.verdict([Receipt("sol", 1, 0), Receipt("luna", 0, 0)]), 1)

    def test_nothing_to_check_is_not_silently_a_pass(self):
        # An empty run must never read as success: "no processes found" is how
        # a broken check quietly stops protecting anything.
        self.assertEqual(self.verdict([]), 2)

    def test_a_lost_process_is_named(self):
        self.assertTrue(Receipt("luna", 0, 0).describe().strip().startswith("✗"))
        self.assertIn("luna", Receipt("luna", 0, 0).describe())


if __name__ == "__main__":
    unittest.main()
