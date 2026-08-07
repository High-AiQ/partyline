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


def delivery(text):
    """The coordinator's actual wording, which every real wake carries."""
    return f"\u260f the trusted cockpit plan started automatic sequential " \
           f"reattachment after the dogfood restart\n\nContinuation debrief: {text}"


def wake(text):
    """What a partyline delivery actually looks like in a codex rollout."""
    return {"payload": {"type": "user_message", "message": f"[opus]: {delivery(text)}"}}


def mirrored_wake(text):
    """The same delivery, in the shape some CLIs also record it as."""
    return {"payload": {"type": "message", "role": "user",
                        "content": [{"type": "input_text", "text": delivery(text)}]}}


def claude_wake(text):
    """A Claude transcript record: typed `user`, with `role` nested one level
    down. Reading only the top-level `role` made these invisible."""
    return {"type": "user", "message": {"role": "user", "content": delivery(text)}}


def room_chat(text):
    """Another participant *saying* the nonce in the room.

    The initiator announces it before arming, so this lands in every
    transcript — as a genuine user-role delivery — before the restart even
    happens. It is the one confound a random token does not defeat."""
    return {"type": "user", "message": {"role": "user",
                                        "content": f"[sol]: Restart armed. Nonce {text}."}}


def tool_call(text):
    """An agent *running* a command containing the text — e.g. the very
    `cockpit plan --debrief "…"` that created the plan."""
    return {"payload": {"type": "custom_tool_call", "name": "exec", "input": text}}


def tool_output(text):
    """An agent dumping the database while investigating the bug."""
    return {"payload": {"type": "custom_tool_call_output", "output": text}}


class ClaudeShapeTest(unittest.TestCase):
    """The oracle must see every participant's transcript, not most of them.

    It reported CONTINUATION LOST for a Claude process whose transcript plainly
    contained the debrief, because `role` sits under `message` there rather than
    at the top level. A restart that had worked was very nearly recorded as a
    failure on the strength of that.
    """

    def test_a_claude_delivery_is_a_receipt(self):
        self.assertTrue(is_input_record(claude_wake(NONCE), NONCE))

    def test_a_claude_transcript_yields_a_receipt(self):
        path = transcript(claude_wake(NONCE))
        try:
            self.assertTrue(read_receipt("opus", path, NONCE).received)
        finally:
            path.unlink()


class ChatQuotingTest(unittest.TestCase):
    """Hearing the nonce is not the same as being handed the debrief."""

    def test_room_chat_quoting_the_nonce_is_not_a_receipt(self):
        self.assertFalse(is_input_record(room_chat(NONCE), NONCE))

    def test_a_process_that_only_heard_it_announced_is_reported_lost(self):
        """The failure this prevents is the worst kind: a restart that
        delivered nothing to anybody, reporting four receipts, because the
        initiator announced the nonce in the room beforehand."""
        path = transcript(room_chat(NONCE), room_chat(NONCE))
        try:
            self.assertFalse(read_receipt("terra", path, NONCE).received)
        finally:
            path.unlink()

    def test_a_real_delivery_still_counts_amid_the_chatter(self):
        path = transcript(room_chat(NONCE), claude_wake(NONCE), room_chat(NONCE))
        try:
            self.assertEqual(read_receipt("opus", path, NONCE).delivered, 1)
        finally:
            path.unlink()


class ToolResultContaminationTest(unittest.TestCase):
    """The investigation must not be able to manufacture its own receipt.

    Claude addresses tool results to `user` too — because that is who the
    result is *for* — so an agent grepping its own transcript for the nonce
    produces a `type=user` record containing both the marker and the nonce.
    Counting it would mean the act of checking whether a receipt exists creates
    one, which is the exact confound the nonce was introduced to eliminate.
    """

    def grep_output(self, text):
        return {"type": "user", "message": {"role": "user", "content": [
            {"type": "tool_result", "content": delivery(text)}]}}

    def test_a_tool_result_carrying_marker_and_nonce_is_not_a_receipt(self):
        self.assertFalse(is_input_record(self.grep_output(NONCE), NONCE))

    def test_a_transcript_of_nothing_but_self_inspection_is_reported_lost(self):
        path = transcript(self.grep_output(NONCE), self.grep_output(NONCE))
        try:
            self.assertFalse(read_receipt("opus", path, NONCE).received)
        finally:
            path.unlink()

    def test_a_real_delivery_survives_alongside_its_own_investigation(self):
        path = transcript(self.grep_output(NONCE), claude_wake(NONCE))
        try:
            self.assertEqual(read_receipt("opus", path, NONCE).delivered, 1)
        finally:
            path.unlink()


class SpeakerTest(unittest.TestCase):
    """`message` says nothing about who spoke; only `role` does."""

    def assistant_echo(self, text):
        """A process's own reply, quoting the debrief it is reporting on —
        which is what every one of these agents does immediately after
        resuming. Counting it would let a receipt prove itself."""
        return {"payload": {"type": "message", "role": "assistant",
                            "content": [{"type": "text", "text": delivery(text)}]}}

    def test_an_assistant_turn_quoting_the_debrief_is_not_a_receipt(self):
        self.assertFalse(is_input_record(self.assistant_echo(NONCE), NONCE))

    def test_a_transcript_of_only_self_report_is_reported_lost(self):
        path = transcript(self.assistant_echo(NONCE))
        try:
            self.assertFalse(read_receipt("sol", path, NONCE).received)
        finally:
            path.unlink()

    def test_the_codex_delivery_shape_still_counts_without_a_role(self):
        """Codex's `user_message` carries no `role`; the type is the claim."""
        self.assertTrue(is_input_record(wake(NONCE), NONCE))


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
