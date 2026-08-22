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

    async def test_deliver_resends_an_unaccepted_wake_then_gives_up_loudly(self):
        """Regression for the stuck-badge incident: an idle TUI can hold a
        pasted digest unsubmitted — no USER_INPUT, no turn, no ENDED receipt,
        presence lit forever. The adapter must resend on a bounded schedule
        and then say out loud that the wake never landed."""
        adapter = self.make()
        adapter.proc = Process()
        sent = []
        adapter.send_keys = AsyncMock(side_effect=lambda text: sent.append(text))
        with patch("partyline.adapters.bundled.antigravity.adapter.asyncio.sleep", new=AsyncMock()):
            await adapter.deliver([{"sender": "greg", "body": "wake one"}])
            await adapter._watchdog
        digest = adapter.format_digest([{"sender": "greg", "body": "wake one"}])
        # The original paste plus both scheduled retries.
        self.assertEqual(sent, [digest, digest, digest])
        self.assertEqual(len(self.messages), 1)
        self.assertIn("never took it", self.messages[0][2])

    async def test_a_transcript_input_clears_the_outstanding_wake(self):
        adapter = self.make()
        adapter.proc = Process()
        sent = []
        adapter.send_keys = AsyncMock(side_effect=lambda text: sent.append(text))
        sleeps = 0

        async def sleep(_seconds):
            nonlocal sleeps
            sleeps += 1
            if sleeps == 3:
                # The TUI took the paste, possibly reflowed: whitespace
                # differences must still clear the outstanding digest.
                adapter._note_user_input("<USER_REQUEST>\n  " + sent[0].replace("\n", " \n "))

        with patch("partyline.adapters.bundled.antigravity.adapter.asyncio.sleep", new=sleep):
            await adapter.deliver([{"sender": "greg", "body": "wake two"}])
            await adapter._watchdog
        self.assertEqual(sent, [adapter.format_digest([{"sender": "greg", "body": "wake two"}])])
        self.assertEqual(self.messages, [])
        self.assertEqual(adapter._outstanding, [])

    async def test_deliver_does_not_arm_the_watchdog_for_a_dead_process(self):
        adapter = self.make()
        adapter.proc = Process()
        adapter.proc.stop()
        adapter.send_keys = AsyncMock()
        await adapter.deliver([{"sender": "greg", "body": "wake three"}])
        self.assertEqual(adapter._outstanding, [])
        self.assertIsNone(adapter._watchdog)

    async def test_stop_cancels_a_pending_watchdog(self):
        adapter = self.make()
        adapter.proc = Process()
        adapter.send_keys = AsyncMock()
        await adapter.deliver([{"sender": "greg", "body": "wake four"}])
        self.assertFalse(adapter._watchdog.done())
        adapter.proc = None  # never really spawned: keep stop() off killpg
        await adapter.stop()
        await asyncio.sleep(0.01)  # let the cancelled task finish unwinding
        self.assertTrue(adapter._watchdog.cancelled())

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


if __name__ == "__main__":
    unittest.main()
