"""Coverage for the bundled Antigravity (`agy`) adapter.

The tests build the adapter directly with recording callbacks and point it at
hand-written log/transcript fixtures. The real CLI is never started: discovery
is exercised against a fake `--log-file`, and relaying against a fixture
transcript in a temporary brain directory.
"""

from __future__ import annotations

import asyncio
import json
import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from partyline.adapters.bundled.antigravity import adapter as antigravity_module
from partyline.adapters.bundled.antigravity import logparse
from partyline.adapters.bundled.antigravity.adapter import PartylineAdapter
from partyline.adapters.receipts import BEGAN, ENDED

CONV_ID = "f4de7395-4edd-4412-abcf-693c3e1ac837"


class Process:
    def __init__(self):
        self.returncode = None

    def poll(self):
        return self.returncode

    def stop(self):
        self.returncode = 0


def attachment(name="agent", *, cwd="/project", command=None, **extra):
    return {
        "id": name + "-id",
        "name": name,
        "cwd": cwd,
        "command": command or ["agy"],
        "adapter_metadata": {"command": ["agy"]},
        **extra,
    }


def step(index, source, stype, content="", created="2026-08-21T23:57:14Z", **extra):
    record = {
        "step_index": index,
        "source": source,
        "type": stype,
        "status": "DONE",
        "created_at": created,
        "content": content,
    }
    record.update(extra)
    return json.dumps(record) + "\n"


def later(stamp: float) -> str:
    """A transcript timestamp written after `stamp` (ISO, Z-suffixed)."""
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(stamp + 5))


def glog_submission(text: str, stamp: float) -> str:
    """A verbatim-shaped HandleUserInput line: Go-quoted payload, glog ts."""
    ts = time.strftime("I%m%d %H:%M:%S.000000", time.localtime(stamp))
    escaped = text.replace("\\", "\\\\").replace("\n", "\\n").replace('"', '\\"')
    return (
        f"ERROR: logging before google.Init: {ts}   21217 input_loop.go:36] "
        f'HandleUserInput called with text: "{escaped}"\n'
    )


class AntigravityAdapterTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.messages = []
        self.statuses = []
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.log_root = os.path.join(self.tmp.name, "logs")
        self.brain_root = Path(self.tmp.name) / "brain"
        self.old_roots = (antigravity_module.LOG_ROOT, antigravity_module.BRAIN_ROOT)
        antigravity_module.LOG_ROOT = self.log_root
        antigravity_module.BRAIN_ROOT = self.brain_root
        self.addCleanup(self._restore_roots)

    def _restore_roots(self):
        antigravity_module.LOG_ROOT, antigravity_module.BRAIN_ROOT = self.old_roots

    async def post(self, sender, sender_type, body):
        self.messages.append((sender, sender_type, body))

    async def status(self, value):
        self.statuses.append(value)

    def make(self, **extra):
        return PartylineAdapter(attachment(**extra), self.post, self.status)

    def write_log(self, adapter, conversation=CONV_ID):
        Path(self.log_root).mkdir(parents=True, exist_ok=True)
        Path(adapter.log_path()).write_text(
            f"I0821 server.go:1074] Created conversation {conversation}\n", encoding="utf-8"
        )

    def write_transcript(self, records, conversation=CONV_ID):
        path = self.brain_root / conversation / ".system_generated" / "logs" / "transcript.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("".join(records), encoding="utf-8")
        return path

    async def test_build_command_pins_log_file_and_resume_conversation(self):
        fresh = self.make()
        self.assertEqual(
            fresh.build_command(),
            ["agy", "--log-file", os.path.join(self.log_root, "agent-id.log")],
        )
        explicit = self.make(command=["agy", "--log-file", "custom.log", "--model", "x"])
        self.assertEqual(explicit.build_command(), ["agy", "--log-file", "custom.log", "--model", "x"])

        resumed = self.make(resume=True, cli_session=CONV_ID)
        self.assertEqual(
            resumed.build_command(),
            ["agy", "--log-file", os.path.join(self.log_root, "agent-id.log"),
             "--conversation", CONV_ID],
        )
        staged = self.make(resume=True, cli_session=CONV_ID)
        staged._startup_prompt = "wake up"
        self.assertEqual(
            staged.build_command()[-2:], ["--prompt-interactive", "wake up"],
        )
        flagged = self.make(
            resume=True, cli_session="new", command=["agy", "--conversation", "old"]
        )
        self.assertEqual(
            flagged.build_command(),
            ["agy", "--conversation", "old", "--log-file", os.path.join(self.log_root, "agent-id.log")],
        )
        no_session = self.make(resume=True)
        self.assertNotIn("--conversation", no_session.build_command())

    async def test_stage_startup_delivery_only_for_resume_with_messages(self):
        fresh = self.make()
        self.assertFalse(fresh.stage_startup_delivery([{"sender": "greg", "body": "hi"}]))
        self.assertNotIn("--prompt-interactive", fresh.build_command())
        resumed = self.make(resume=True, cli_session=CONV_ID)
        self.assertFalse(resumed.stage_startup_delivery([]))
        messages = [{"sender": "system", "body": "Continuation debrief: nonce-123"}]
        self.assertTrue(resumed.stage_startup_delivery(messages))
        self.assertEqual(resumed._startup_prompt, resumed.format_digest(messages))
        self.assertFalse(resumed._silent_until_wake)

    async def test_conversation_from_log_parses_created_line(self):
        adapter = self.make()
        self.assertIsNone(adapter._conversation_from_log())
        self.write_log(adapter, conversation="")
        Path(adapter.log_path()).write_text("no conversation here\n", encoding="utf-8")
        self.assertIsNone(adapter._conversation_from_log())
        self.write_log(adapter)
        self.assertEqual(adapter._conversation_from_log(), CONV_ID)

    async def test_run_tails_planner_text_and_emits_receipts_once(self):
        adapter = self.make(hook_url="http://hook/x")
        adapter.proc = Process()
        adapter.spawned_at = time.time()
        self.write_log(adapter)
        self.write_transcript([
            "not json\n",
            step(0, "USER_EXPLICIT", "USER_INPUT", "<USER_REQUEST>\nhi\n</USER_REQUEST>"),
            step(1, "SYSTEM", "CHECKPOINT", "{{ CHECKPOINT 0 }}"),
            step(2, "MODEL", "PLANNER_RESPONSE", "", tool_calls=[{"name": "view_file"}]),
            step(3, "MODEL", "GENERIC", "tool output stays off the line"),
            step(4, "MODEL", "PLANNER_RESPONSE", "done working"),
            step(4, "MODEL", "PLANNER_RESPONSE", "duplicate write"),
        ])
        sent = []
        adapter.send_keys = AsyncMock(side_effect=lambda text: sent.append(text))
        sessions = []
        adapter.on_cli_session = sessions.append

        original_post = adapter.post

        async def post(sender, sender_type, body):
            await original_post(sender, sender_type, body)
            adapter.proc.stop()

        adapter.post = post
        with (
            patch("partyline.adapters.bundled.antigravity.adapter.asyncio.sleep", new=AsyncMock()),
            patch("partyline.adapters.bundled.antigravity.adapter.receipt", new=AsyncMock()) as mock_receipt,
        ):
            await adapter._run()
        self.assertEqual(self.messages, [("agent", "agent", "done working")])
        self.assertEqual(sent, [adapter.briefing()])
        self.assertEqual(sessions, [CONV_ID])
        self.assertEqual(
            [call.args for call in mock_receipt.await_args_list],
            [(adapter.att, BEGAN), (adapter.att, ENDED)],
        )
        self.assertTrue(await adapter.wait_ready())

    async def test_run_resume_skips_stale_records_and_marks_startup_delivery(self):
        adapter = self.make(resume=True, cli_session=CONV_ID)
        adapter.proc = Process()
        adapter.spawned_at = time.time()
        old = "2000-01-01T00:00:00Z"
        now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(adapter.spawned_at + 1))
        adapter._startup_prompt = "nonce-xyz pick up where you left off"
        user_input = f"<USER_REQUEST>\n{adapter._startup_prompt}\n</USER_REQUEST>"
        self.write_transcript([
            step(0, "MODEL", "PLANNER_RESPONSE", "stale answer", created=old),
            step(1, "USER_EXPLICIT", "USER_INPUT", user_input, created=now),
            step(2, "MODEL", "PLANNER_RESPONSE", "fresh answer", created=now),
        ])

        async def post(sender, sender_type, body):
            await self.post(sender, sender_type, body)
            adapter.proc.stop()

        adapter.post = post
        adapter.send_keys = AsyncMock()
        with (
            patch("partyline.adapters.bundled.antigravity.adapter.asyncio.sleep", new=AsyncMock()),
            patch("partyline.adapters.bundled.antigravity.adapter.receipt", new=AsyncMock()),
        ):
            await adapter._run()
        self.assertEqual(self.messages, [("agent", "agent", "fresh answer")])
        adapter.send_keys.assert_not_awaited()
        self.assertTrue(await adapter.wait_startup_delivery_received())

    async def test_run_retries_trust_prompt_then_reports_missing_conversation(self):
        adapter = self.make()
        adapter.proc = Process()
        adapter.master = 7
        adapter.send_keys = AsyncMock()
        waits = 0

        async def sleep(_seconds):
            nonlocal waits
            waits += 1

        with (
            patch("partyline.adapters.bundled.antigravity.adapter.os.write") as write,
            patch("partyline.adapters.bundled.antigravity.adapter.asyncio.sleep", new=sleep),
        ):
            await adapter._run()
        self.assertIn("no conversation after 45s", self.messages[-1][2])
        self.assertEqual(write.call_count, 2)
        self.assertEqual(adapter.send_keys.await_count, 3)

    async def test_run_returns_quietly_when_process_exits_early(self):
        adapter = self.make()
        adapter.proc = Process()
        adapter.proc.stop()
        with patch("partyline.adapters.bundled.antigravity.adapter.asyncio.sleep", new=AsyncMock()):
            await adapter._run()
        self.assertEqual(self.messages, [])

        waiting = self.make()
        waiting.proc = Process()
        waiting.send_keys = AsyncMock()
        waits = 0

        async def stop_waiting(_seconds):
            nonlocal waits
            waits += 1
            if waits > 2:
                waiting.proc.stop()

        with patch("partyline.adapters.bundled.antigravity.adapter.asyncio.sleep", new=stop_waiting):
            await waiting._run()
        self.assertEqual(self.messages, [])

        resumed = self.make(resume=True, cli_session=CONV_ID)
        resumed.proc = Process()
        transcript_waits = 0

        async def stop_transcript_wait(_seconds):
            nonlocal transcript_waits
            transcript_waits += 1
            if transcript_waits > 2:
                resumed.proc.stop()

        # The conversation id is known but the process dies before its
        # transcript ever appears: nothing to tail, nothing to say.
        with patch(
            "partyline.adapters.bundled.antigravity.adapter.asyncio.sleep", new=stop_transcript_wait
        ):
            await resumed._run()
        self.assertEqual(self.messages, [])

    async def test_a_submitted_input_that_skips_the_wake_resends_once_then_notices(self):
        """Regression for the stuck-badge incident, evidence-only: an idle TUI
        can hold a pasted digest unsubmitted. A USER_INPUT that contains the
        digest verifies it; one that does not *proves* the paste was skipped,
        which re-sends it exactly once — a second proof drops it with one
        factual notice. No timer may guess at the CLI's state."""
        adapter = self.make()
        adapter.proc = Process()
        sent = []
        adapter.send_keys = AsyncMock(side_effect=lambda text: sent.append(text))
        await adapter.deliver([{"sender": "greg", "body": "wake one"}])
        digest = adapter.format_digest([{"sender": "greg", "body": "wake one"}])
        self.assertEqual([d for d, _ in adapter._outstanding], [digest])
        pasted = adapter._outstanding[0][1]

        await adapter._note_user_input(
            "<USER_REQUEST>\n/some other command\n</USER_REQUEST>", later(pasted)
        )
        # The original paste from deliver() plus the one proof-triggered resend.
        self.assertEqual(sent, [digest, digest])
        self.assertEqual([d for d, _ in adapter._outstanding], [digest])

        await adapter._note_user_input(
            "<USER_REQUEST>\n/something else\n</USER_REQUEST>", later(pasted)
        )
        self.assertEqual(sent, [digest, digest])
        self.assertEqual(adapter._outstanding, [])
        self.assertEqual(len(self.messages), 1)
        self.assertIn("was not delivered", self.messages[0][2])

    async def test_a_record_cannot_judge_a_digest_pasted_after_it(self):
        """A mention delivered mid-turn pastes a wake that the running turn's
        already-written USER_INPUT cannot contain; judging it would call a
        healthy paste skipped and re-send it. Ordering is evidence, not
        guessing: the record settles only earlier pastes."""
        adapter = self.make()
        adapter.proc = Process()
        sent = []
        adapter.send_keys = AsyncMock(side_effect=lambda text: sent.append(text))
        await adapter.deliver([{"sender": "greg", "body": "mid-turn wake"}])
        digest = adapter.format_digest([{"sender": "greg", "body": "mid-turn wake"}])
        # The record was written before the paste: no verdict either way.
        await adapter._note_user_input(
            "<USER_REQUEST>\n/unrelated earlier turn\n</USER_REQUEST>",
            time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() - 10)),
        )
        self.assertEqual(sent, [digest])
        self.assertEqual([d for d, _ in adapter._outstanding], [digest])
        self.assertEqual(self.messages, [])

    async def test_a_transcript_input_containing_the_digest_verifies_it(self):
        adapter = self.make()
        adapter.proc = Process()
        sent = []
        adapter.send_keys = AsyncMock(side_effect=lambda text: sent.append(text))
        await adapter.deliver([{"sender": "greg", "body": "wake two"}])
        digest = adapter.format_digest([{"sender": "greg", "body": "wake two"}])
        # The TUI took the paste, possibly reflowed: whitespace differences
        # must still verify the digest, with no resend and no notice.
        await adapter._note_user_input(
            "<USER_REQUEST>\n  " + digest.replace("\n", " \n ") + "\n</USER_REQUEST>",
            later(adapter._outstanding[0][1]),
        )
        # Only deliver()'s original paste: verification sends nothing.
        self.assertEqual(sent, [digest])
        self.assertEqual(adapter._outstanding, [])
        self.assertEqual(self.messages, [])

    async def test_deliver_does_not_track_a_wake_for_a_dead_process(self):
        adapter = self.make()
        adapter.proc = Process()
        adapter.proc.stop()
        adapter.send_keys = AsyncMock()
        await adapter.deliver([{"sender": "greg", "body": "wake three"}])
        self.assertEqual(adapter._outstanding, [])

    async def test_loss_notices_are_capped_across_distinct_wakes(self):
        """The notice's @handle delivers a fresh wake; the global cap keeps a
        pathological CLI from farming notices, and a verified wake resets it."""
        adapter = self.make()
        adapter.proc = Process()
        adapter.send_keys = AsyncMock()
        for body in ("first", "second", "third"):
            await adapter.deliver([{"sender": "greg", "body": body}])
        for _ in range(2):
            await adapter._note_user_input("<USER_REQUEST>\n/nope\n</USER_REQUEST>", later(time.time()))
        self.assertEqual(len(self.messages), 2)
        # A later wake that lands resets the cap for future losses.
        await adapter.deliver([{"sender": "greg", "body": "fourth"}])
        digest = adapter.format_digest([{"sender": "greg", "body": "fourth"}])
        await adapter._note_user_input(
            "<USER_REQUEST>\n" + digest + "\n</USER_REQUEST>", later(time.time())
        )
        self.assertEqual(adapter._notices, 0)

    async def test_run_waits_for_transcript_after_conversation_appears(self):
        adapter = self.make(resume=True, cli_session=CONV_ID)
        adapter.proc = Process()
        adapter.send_keys = AsyncMock()
        # A delivered wake clears post-resume silence; simulate that directly.
        adapter._silent_until_wake = False
        waits = 0

        async def sleep(_seconds):
            nonlocal waits
            waits += 1
            if waits == 3:
                self.write_transcript([step(0, "MODEL", "PLANNER_RESPONSE", "late transcript")])
            elif waits > 6:
                adapter.proc.stop()

        with (
            patch("partyline.adapters.bundled.antigravity.adapter.asyncio.sleep", new=sleep),
            patch("partyline.adapters.bundled.antigravity.adapter.receipt", new=AsyncMock()),
        ):
            await adapter._run()
        self.assertEqual(self.messages, [("agent", "agent", "late transcript")])

    async def test_a_log_submission_containing_the_digest_verifies_it(self):
        """The pinned log judges at submit time, minutes before the transcript.
        The payload is Go-quoted — the digest's real newlines arrive as literal
        \\n sequences — so both sides are unescaped before containment judges."""
        adapter = self.make()
        adapter.proc = Process()
        sent = []
        adapter.send_keys = AsyncMock(side_effect=lambda text: sent.append(text))
        await adapter.deliver([{"sender": "greg", "body": 'wake "quoted" five'}])
        digest = adapter.format_digest([{"sender": "greg", "body": 'wake "quoted" five'}])
        await adapter._note_log_line(glog_submission(digest, adapter._outstanding[0][1] + 5))
        self.assertEqual(sent, [digest])
        self.assertEqual(adapter._outstanding, [])
        self.assertEqual(self.messages, [])

    async def test_a_log_submission_of_other_input_proves_skip_then_notices(self):
        adapter = self.make()
        adapter.proc = Process()
        sent = []
        adapter.send_keys = AsyncMock(side_effect=lambda text: sent.append(text))
        await adapter.deliver([{"sender": "greg", "body": "wake six"}])
        digest = adapter.format_digest([{"sender": "greg", "body": "wake six"}])
        pasted = adapter._outstanding[0][1]

        await adapter._note_log_line(glog_submission("/status", pasted + 5))
        self.assertEqual(sent, [digest, digest])

        await adapter._note_log_line(glog_submission("/quit", pasted + 6))
        self.assertEqual(sent, [digest, digest])
        self.assertEqual(adapter._outstanding, [])
        self.assertEqual(len(self.messages), 1)
        self.assertIn("was not delivered", self.messages[0][2])

    async def test_a_log_line_without_a_parseable_timestamp_cannot_judge(self):
        adapter = self.make()
        adapter.proc = Process()
        sent = []
        adapter.send_keys = AsyncMock(side_effect=lambda text: sent.append(text))
        await adapter.deliver([{"sender": "greg", "body": "wake seven"}])
        digest = adapter.format_digest([{"sender": "greg", "body": "wake seven"}])
        # A submission line with no glog prefix carries no ordering evidence.
        await adapter._note_log_line('HandleUserInput called with text: "/status"\n')
        # And a line that is not a submission says nothing at all.
        await adapter._note_log_line(glog_submission("", time.time()).replace(
            'HandleUserInput called with text: ""', "Streaming conversation abc"))
        self.assertEqual(sent, [digest])
        self.assertEqual([d for d, _ in adapter._outstanding], [digest])
        self.assertEqual(self.messages, [])

    def test_logparse_rolls_back_a_future_yearless_stamp(self):
        future = time.strftime("I%m%d %H:%M:%S", time.localtime(time.time() + 3 * 86400))
        stamp = logparse._glog_timestamp(f"{future}.000000 1 x.go:1] hi")
        self.assertLess(stamp, time.time())
        self.assertIsNone(logparse._glog_timestamp("no timestamp here"))
        self.assertIsNone(logparse.submission("no timestamp here"))
        self.assertIsNone(logparse.submission('HandleUserInput called with text: "x"'))

    async def test_tail_log_returns_when_the_log_cannot_be_opened(self):
        adapter = self.make()
        adapter.proc = Process()
        os.makedirs(adapter.log_path())  # a directory cannot be opened for reading
        await adapter._tail_log()

    async def test_tail_log_judges_lines_appended_after_it_opens(self):
        adapter = self.make()
        adapter.proc = Process()
        adapter.send_keys = AsyncMock()
        os.makedirs(self.log_root, exist_ok=True)
        Path(adapter.log_path()).write_text("", encoding="utf-8")
        await adapter.deliver([{"sender": "greg", "body": "via log"}])
        digest = adapter.format_digest([{"sender": "greg", "body": "via log"}])
        tail = asyncio.create_task(adapter._tail_log())
        await asyncio.sleep(0.1)  # let the tail open the file and seek to EOF
        with open(adapter.log_path(), "a", encoding="utf-8") as file:
            file.write(glog_submission(digest, time.time() + 5))
        for _ in range(30):
            if not adapter._outstanding:
                break
            await asyncio.sleep(0.1)
        adapter.proc.stop()
        await asyncio.wait_for(tail, 5)
        self.assertEqual(adapter._outstanding, [])

    async def test_send_keys_holds_enter_until_the_composer_echoes(self):
        """The fixed paste→Enter delay lost the race on a slow TUI; the Enter
        now waits for the CLI's own redraw to prove the paste landed."""
        adapter = self.make()
        adapter.proc = Process()
        adapter.master = 7
        adapter.screen_text = lambda: "input box is empty"
        writes = []
        with (
            patch("partyline.adapters.bundled.antigravity.adapter.os.write",
                  side_effect=lambda fd, data: writes.append(data)),
            patch.object(antigravity_module, "PASTE_PACE", 30.0),
        ):
            sending = asyncio.create_task(adapter.send_keys("wake eight"))
            await asyncio.sleep(0.05)
            self.assertEqual(len(writes), 1)  # paste written, Enter held
            adapter.screen_text = lambda: "> wake eight"
            await adapter.on_output(b"redraw")
            await asyncio.wait_for(sending, 5)
        self.assertEqual(
            writes,
            [b"\x1b[200~wake eight\x1b[201~", b"\r"],
        )

    async def test_send_keys_paces_the_enter_when_no_echo_comes(self):
        """The bound is flow control between two writes, not a verdict: the
        Enter still goes when the echo never arrives, as it always has."""
        adapter = self.make()
        adapter.proc = Process()
        adapter.master = 7
        adapter.screen_text = lambda: "nothing"
        writes = []
        with (
            patch("partyline.adapters.bundled.antigravity.adapter.os.write",
                  side_effect=lambda fd, data: writes.append(data)),
            patch.object(antigravity_module, "PASTE_PACE", 0.05),
        ):
            await adapter.send_keys("wake nine")
        self.assertEqual(writes[-1], b"\r")
        # A deadline already past still sends the Enter — pacing, not a verdict.
        with (
            patch("partyline.adapters.bundled.antigravity.adapter.os.write",
                  side_effect=lambda fd, data: writes.append(data)),
            patch.object(antigravity_module, "PASTE_PACE", -1.0),
        ):
            await adapter.send_keys("wake ten")
        self.assertEqual(writes[-1], b"\r")

    async def test_an_input_with_a_malformed_timestamp_still_judges(self):
        adapter = self.make()
        adapter.proc = Process()
        sent = []
        adapter.send_keys = AsyncMock(side_effect=lambda text: sent.append(text))
        await adapter.deliver([{"sender": "greg", "body": "wake eleven"}])
        digest = adapter.format_digest([{"sender": "greg", "body": "wake eleven"}])
        await adapter._note_user_input(digest, "not-a-date")
        self.assertEqual(adapter._outstanding, [])
        # A record carrying no timestamp at all still settles a wake.
        await adapter.deliver([{"sender": "greg", "body": "wake twelve"}])
        digest = adapter.format_digest([{"sender": "greg", "body": "wake twelve"}])
        await adapter._note_user_input(digest, None)
        self.assertEqual(adapter._outstanding, [])

    async def test_stage_startup_delivery_rejects_a_blank_digest(self):
        resumed = self.make(resume=True, cli_session=CONV_ID)
        resumed.format_digest = lambda messages: "   "
        self.assertFalse(resumed.stage_startup_delivery([{"sender": "greg", "body": "x"}]))

    async def test_tail_log_waits_for_the_log_to_appear(self):
        adapter = self.make()
        adapter.proc = Process()
        sleeps = 0

        async def sleep(_seconds):
            nonlocal sleeps
            sleeps += 1
            if sleeps > 2:
                adapter.proc.stop()

        with patch("partyline.adapters.bundled.antigravity.adapter.asyncio.sleep", new=sleep):
            await adapter._tail_log()
        self.assertGreater(sleeps, 2)

    async def test_deliver_flushes_a_stuck_composer_only_when_screen_proves_it(self):
        """A wake the TUI held unsubmitted still sits in the composer: the
        next deliver sends a bare Enter first — the fix the original incident
        got by hand — but only when the screen proves the stuck text is ours."""
        adapter = self.make()
        adapter.proc = Process()
        adapter.master = 7
        adapter.send_keys = AsyncMock()
        await adapter.deliver([{"sender": "greg", "body": "stuck wake"}])
        stuck = adapter.format_digest([{"sender": "greg", "body": "stuck wake"}])

        writes = []
        adapter.send_keys = PartylineAdapter.send_keys.__get__(adapter)
        with (
            patch("partyline.adapters.bundled.antigravity.adapter.os.write",
                  side_effect=lambda fd, data: writes.append(data)),
            patch.object(antigravity_module, "PASTE_PACE", 0.05),
        ):
            adapter.screen_text = lambda: "nothing of ours here"
            await adapter.deliver([{"sender": "greg", "body": "second wake"}])
            self.assertTrue(writes[0].startswith(b"\x1b[200~"))  # no flush

            writes.clear()
            adapter.screen_text = lambda: "> " + stuck[-60:]
            await adapter.deliver([{"sender": "greg", "body": "third wake"}])
        self.assertEqual(writes[0], b"\r")  # the stuck wake is flushed first
        self.assertTrue(writes[1].startswith(b"\x1b[200~"))


if __name__ == "__main__":
    unittest.main()
