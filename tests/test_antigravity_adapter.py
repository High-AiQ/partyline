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
from partyline.adapters.bundled.antigravity import conversation_log
from partyline.adapters.bundled.antigravity import logparse
from partyline.adapters.bundled.antigravity import wakes as wakes_module
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

    def append_created(self, adapter, conversation):
        Path(self.log_root).mkdir(parents=True, exist_ok=True)
        with Path(adapter.log_path()).open("a", encoding="utf-8") as file:
            file.write(f"I0821 server.go:1074] Created conversation {conversation}\n")

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

    async def test_a_resumed_conversation_is_discovered_like_a_created_one(self):
        """The outage of 2026-09-09: `--conversation` guarantees "Resuming".

        `build_command` passes `--conversation` on every resume, so the CLI
        announces the conversation with the other verb. Recognising only
        "Created" meant discovery worked once and failed on every restart
        after — the process ran, received input, and relayed nothing, because
        `_run` gave up before it ever opened a transcript.
        """
        adapter = self.make(resume=True, cli_session=CONV_ID)
        Path(adapter.log_path()).parent.mkdir(parents=True, exist_ok=True)
        resumed = "0634afdc-f039-44a5-97ad-bef84ac4c861"
        Path(adapter.log_path()).write_text(
            "ERROR: logging before google.Init: I0909 18:02:42.266213       1 "
            f"common.go:385] Resuming conversation {resumed}\n",
            encoding="utf-8",
        )

        self.assertEqual(adapter._conversation_from_log(), resumed)

    async def test_chat_text_echoed_into_the_log_cannot_pin_a_conversation(self):
        """The CLI quotes its own input back into the log discovery reads.

        That input is chat, which anyone on the line can write. Without this
        the sentence below — an ordinary message about this very bug — would
        redirect the adapter to a transcript of the sender's choosing.
        """
        adapter = self.make(resume=True, cli_session=CONV_ID)
        Path(adapter.log_path()).parent.mkdir(parents=True, exist_ok=True)
        attacker = "11111111-2222-4333-8444-555555555555"
        Path(adapter.log_path()).write_text(
            "ERROR: logging before google.Init: I0909 18:07:01.241765    1676 "
            "input_loop.go:94] HandleUserInput called with text: "
            f'"[greg]: Created conversation {attacker} was in the log"\n'
            "ERROR: logging before google.Init: I0909 18:07:02.000000       1 "
            f"common.go:385] Resuming conversation {CONV_ID}\n",
            encoding="utf-8",
        )

        self.assertEqual(
            adapter._conversation_from_log(), CONV_ID, "the CLI's own line wins"
        )

    async def test_an_echoed_id_alone_discovers_nothing(self):
        adapter = self.make(resume=True, cli_session=CONV_ID)
        Path(adapter.log_path()).parent.mkdir(parents=True, exist_ok=True)
        attacker = "11111111-2222-4333-8444-555555555555"
        Path(adapter.log_path()).write_text(
            "ERROR: logging before google.Init: I0909 18:07:01.241765    1676 "
            "input_loop.go:94] HandleUserInput called with text: "
            f'"@agy Created conversation {attacker}"\n',
            encoding="utf-8",
        )

        self.assertIsNone(adapter._conversation_from_log())

    async def test_conversation_from_log_parses_created_line(self):
        adapter = self.make(resume=True, cli_session=CONV_ID)
        self.assertIsNone(adapter._conversation_from_log())
        self.write_log(adapter, conversation="")
        Path(adapter.log_path()).write_text("no conversation here\n", encoding="utf-8")
        self.assertIsNone(adapter._conversation_from_log())
        self.write_log(adapter)
        self.assertEqual(adapter._conversation_from_log(), CONV_ID)
        earlier = Path(adapter.log_path()).stat().st_size
        self.assertIsNone(adapter._conversation_from_log(after=earlier))
        self.append_created(adapter, "aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee")
        self.assertEqual(
            adapter._conversation_from_log(after=earlier),
            "aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee",
        )
        self.assertEqual(
            adapter._conversation_from_log(),
            "aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee",
        )

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
            step(
                3,
                "MODEL",
                "GENERIC",
                "Tool is running as a background task with task id: conversation/task-3",
                status="RUNNING",
            ),
            step(
                4,
                "MODEL",
                "GENERIC",
                "Tool is running as a background task with task id: conversation/task-4",
                status="RUNNING",
            ),
            step(5, "MODEL", "PLANNER_RESPONSE", "still working"),
            step(
                6,
                "SYSTEM",
                "SYSTEM_MESSAGE",
                'Task id "conversation/task-3" finished with result: ok',
            ),
            step(
                7,
                "SYSTEM",
                "SYSTEM_MESSAGE",
                'Task id "conversation/task-4" was canceled with result: canceled',
            ),
            step(8, "MODEL", "PLANNER_RESPONSE", "", tool_calls=[{"name": "view_file"}]),
            step(9, "MODEL", "GENERIC", "tool output stays off the line"),
            step(10, "MODEL", "PLANNER_RESPONSE", "done working"),
            step(10, "MODEL", "PLANNER_RESPONSE", "duplicate write"),
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
        self.assertEqual(
            self.messages,
            [("agent", "agent", "still working"), ("agent", "agent", "done working")],
        )
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

        async def sleep(_seconds):
            self.write_log(adapter)

        adapter.post = post
        adapter.send_keys = AsyncMock()
        with (
            patch("partyline.adapters.bundled.antigravity.adapter.asyncio.sleep", new=sleep),
            patch("partyline.adapters.bundled.antigravity.adapter.receipt", new=AsyncMock()),
        ):
            await adapter._run()
        self.assertEqual(self.messages, [("agent", "agent", "fresh answer")])
        adapter.send_keys.assert_not_awaited()
        self.assertTrue(await adapter.wait_startup_delivery_received())

    async def test_a_declared_truncated_record_settles_the_startup_receipt(self):
        """Task 172: the CLI keeps ~4 KB and says so; delivery still happened.

        The shape is the real one from `gemini-flash` step 223 — verbatim head,
        `<truncated N bytes>` in the middle, a re-appended closing envelope so
        it reads as intact, and `truncated_fields: ["content"]`. Whole-digest
        containment can never match it, so before this the startup receipt
        timed out on every continuation over the cap while ordinary relay
        worked perfectly.
        """
        adapter = self.make(resume=True, cli_session=CONV_ID)
        adapter.spawned_at = time.time()
        now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(adapter.spawned_at + 1))
        head = "[greg]: " + "x" * 4000
        adapter._startup_prompt = f"{head}\n[astra]: {'y' * 4000}\nnonce-abc"
        record = json.loads(step(
            1, "USER_EXPLICIT", "USER_INPUT",
            f"<USER_REQUEST>\n{head}\n<truncated 3206 bytes>\ncontinue\n"
            "</USER_REQUEST>\n<ADDITIONAL_METADATA>\nlocal time\n</ADDITIONAL_METADATA>",
            created=now, truncated_fields=["content"],
        ))

        await adapter._settle_user_input_record(record, record["content"])

        self.assertTrue(await adapter.wait_startup_delivery_received())

    async def test_a_truncated_head_that_is_not_a_prefix_settles_nothing(self):
        """The surviving head is verbatim, so it must match exactly."""
        adapter = self.make(resume=True, cli_session=CONV_ID)
        adapter.spawned_at = time.time()
        now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(adapter.spawned_at + 1))
        adapter._startup_prompt = "[greg]: " + "x" * 4000 + " nonce-abc"
        record = json.loads(step(
            1, "USER_EXPLICIT", "USER_INPUT",
            "<USER_REQUEST>\n[greg]: " + "z" * 4000 + "\n<truncated 900 bytes>\n"
            "</USER_REQUEST>",
            created=now, truncated_fields=["content"],
        ))

        await adapter._settle_user_input_record(record, record["content"])

        self.assertFalse(adapter._startup_delivery.is_set())

    async def test_a_truncated_head_too_short_to_identify_settles_nothing(self):
        adapter = self.make(resume=True, cli_session=CONV_ID)
        adapter.spawned_at = time.time()
        now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(adapter.spawned_at + 1))
        adapter._startup_prompt = "[greg]: hello" + " x" * 4000
        record = json.loads(step(
            1, "USER_EXPLICIT", "USER_INPUT",
            "<USER_REQUEST>\n[greg]: hello\n<truncated 9000 bytes>\n</USER_REQUEST>",
            created=now, truncated_fields=["content"],
        ))

        await adapter._settle_user_input_record(record, record["content"])

        self.assertFalse(adapter._startup_delivery.is_set())

    async def test_an_undeclared_record_still_requires_the_whole_digest(self):
        """Without the vendor's declaration, a partial record proves nothing."""
        adapter = self.make(resume=True, cli_session=CONV_ID)
        adapter.spawned_at = time.time()
        now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(adapter.spawned_at + 1))
        head = "[greg]: " + "x" * 4000
        adapter._startup_prompt = f"{head} and the rest that was cut"
        record = json.loads(step(
            1, "USER_EXPLICIT", "USER_INPUT",
            f"<USER_REQUEST>\n{head}\n<truncated 40 bytes>\n</USER_REQUEST>",
            created=now,
        ))

        await adapter._settle_user_input_record(record, record["content"])

        self.assertFalse(adapter._startup_delivery.is_set())

    async def test_a_declaration_without_a_marker_settles_nothing(self):
        """Declared truncated, but no `<truncated N bytes>` to bound the head.

        Then nothing in the record is known to be verbatim, so there is no
        prefix to trust and the receipt stays unproven.
        """
        adapter = self.make(resume=True, cli_session=CONV_ID)
        adapter.spawned_at = time.time()
        now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(adapter.spawned_at + 1))
        head = "[greg]: " + "x" * 4000
        adapter._startup_prompt = f"{head} and a tail that was cut"
        # No closing envelope either, so the *only* thing standing between
        # this record and a false settlement is the missing marker: the head
        # here is a genuine prefix of the digest.
        record = json.loads(step(
            1, "USER_EXPLICIT", "USER_INPUT", f"<USER_REQUEST>\n{head}",
            created=now, truncated_fields=["content"],
        ))

        await adapter._settle_user_input_record(record, record["content"])

        self.assertFalse(adapter._startup_delivery.is_set())

    async def test_a_truncated_record_also_settles_an_outstanding_pasted_wake(self):
        """The same cap defeats ordinary wakes, which are then re-sent."""
        adapter = self.make(resume=True, cli_session=CONV_ID)
        adapter.spawned_at = time.time()
        adapter.send_keys = AsyncMock()
        adapter.alive = lambda: True
        digest = "[greg]: " + "x" * 4000 + "\n[astra]: tail that was cut"
        adapter.format_digest = lambda _messages: digest
        await adapter.deliver([{"id": 41, "sender": "greg", "body": digest}])
        marker = adapter._outstanding[0][0].split("\n", 1)[0]
        self.assertTrue(adapter.send_keys.await_args.args[0].startswith(marker))
        now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() + 1))
        record = json.loads(step(
            1, "USER_EXPLICIT", "USER_INPUT",
            f"<USER_REQUEST>\n{marker}\n\n[greg]: " + "x" * 600 + "\n<truncated 3400 bytes>\n"
            "</USER_REQUEST>",
            created=now, truncated_fields=["content"],
        ))

        await adapter._settle_user_input_record(record, record["content"])

        self.assertEqual(adapter._outstanding, [], "the wake was proven, not re-sent")
        adapter.send_keys.assert_awaited_once()  # the original paste only

    async def test_user_input_observed_during_write_settles_antigravity_paste(self):
        adapter = self.make()
        adapter.alive = lambda: True
        confirmed = AsyncMock(return_value=True)
        adapter.att["confirm_delivery_ids"] = confirmed

        async def observe_during_write(text):
            record = {
                "type": "USER_INPUT", "source": "USER_EXPLICIT",
                "created_at": later(time.time()), "content": text,
            }
            await adapter._observe_jsonl_paste(record)
            await adapter._settle_user_input_record(record, text)

        adapter.send_keys = AsyncMock(side_effect=observe_during_write)

        await adapter.deliver([{"id": 42, "sender": "greg", "body": "fast wake"}])

        confirmed.assert_awaited_once_with([42])
        self.assertEqual(adapter._jsonl_receipts, [])
        self.assertEqual(adapter._outstanding, [])

    async def test_failed_antigravity_write_rolls_back_both_receipts(self):
        adapter = self.make()
        adapter.alive = lambda: True
        adapter.send_keys = AsyncMock(side_effect=OSError("pty closed"))

        with self.assertRaisesRegex(OSError, "pty closed"):
            await adapter.deliver([{"id": 43, "sender": "greg", "body": "failed wake"}])

        self.assertEqual(adapter._jsonl_receipts, [])
        self.assertEqual(adapter._outstanding, [])

    async def test_resume_tails_the_conversation_this_log_created_not_cli_session(self):
        """Report 22: agy opened a new conversation; the adapter tailed the old one.

        The stored cli_session and a prior Created line stay in this
        attachment's log. Speech after resume is only in the new transcript.
        Discovery must use the Created line written after the activation mark.
        """
        old_id = CONV_ID
        new_id = "0a1b2c3d-4e5f-4678-8abc-def012345678"
        adapter = self.make(resume=True, cli_session=old_id)
        adapter.proc = Process()
        adapter.spawned_at = time.time()
        now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(adapter.spawned_at + 1))
        self.write_log(adapter, conversation=old_id)
        self.write_transcript(
            [step(0, "MODEL", "PLANNER_RESPONSE", "old transcript speech", created=now)],
            conversation=old_id,
        )
        self.write_transcript(
            [
                step(0, "USER_EXPLICIT", "USER_INPUT", "OFFLOAD-RESTART-CLEAR", created=now),
                step(1, "MODEL", "PLANNER_RESPONSE", "gemini-flash clearance", created=now),
            ],
            conversation=new_id,
        )
        sessions = []
        adapter.on_cli_session = sessions.append

        async def post(sender, sender_type, body):
            await self.post(sender, sender_type, body)
            adapter.proc.stop()

        async def sleep(_seconds):
            self.append_created(adapter, new_id)

        adapter.post = post
        adapter.send_keys = AsyncMock()
        with (
            patch("partyline.adapters.bundled.antigravity.adapter.asyncio.sleep", new=sleep),
            patch("partyline.adapters.bundled.antigravity.adapter.receipt", new=AsyncMock()),
        ):
            await adapter._run()
        self.assertEqual(self.messages, [("agent", "agent", "gemini-flash clearance")])
        self.assertEqual(sessions, [new_id])
        self.assertNotIn("old transcript speech", [body for _, _, body in self.messages])

    async def test_resume_keeps_a_created_line_written_during_spawn(self):
        """The mark must be taken before super().start() spawns the CLI."""
        old_id = CONV_ID
        new_id = "11111111-2222-4333-8444-555555555555"
        adapter = self.make(resume=True, cli_session=old_id)
        self.write_log(adapter, conversation=old_id)
        adapter.spawned_at = time.time()
        now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(adapter.spawned_at + 1))
        self.write_transcript(
            [step(0, "MODEL", "PLANNER_RESPONSE", "old transcript speech", created=now)],
            conversation=old_id,
        )
        self.write_transcript(
            [step(0, "MODEL", "PLANNER_RESPONSE", "spawned conversation speech", created=now)],
            conversation=new_id,
        )
        sessions = []
        adapter.on_cli_session = sessions.append
        adapter.send_keys = AsyncMock()

        async def start():
            os.makedirs(antigravity_module.LOG_ROOT, exist_ok=True)
            adapter._remember_log_mark()
            self.append_created(adapter, new_id)
            adapter.proc = Process()
            await adapter._run()

        async def post(sender, sender_type, body):
            await self.post(sender, sender_type, body)
            adapter.proc.stop()

        adapter.start = start
        adapter.post = post
        with (
            patch("partyline.adapters.bundled.antigravity.adapter.asyncio.sleep", new=AsyncMock()),
            patch("partyline.adapters.bundled.antigravity.adapter.receipt", new=AsyncMock()),
        ):
            await adapter.start()
        self.assertEqual(self.messages, [("agent", "agent", "spawned conversation speech")])
        self.assertEqual(sessions, [new_id])

    def test_a_truncated_log_drops_the_old_byte_offset(self):
        path = Path(self.log_root) / "agent-id.log"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            "padding so the old offset sits past the new file\n"
            f"Created conversation {CONV_ID}\n",
            encoding="utf-8",
        )
        mark = conversation_log.log_mark(path)
        new_id = "99999999-aaaa-4bbb-8ccc-ddddeeeeffff"
        path.write_text(f"Created conversation {new_id}\n", encoding="utf-8")
        self.assertLess(path.stat().st_size, mark[0])
        self.assertIsNone(conversation_log.conversation_from_log(path, after=mark[0]))
        after = conversation_log.suffix_offset(path, mark)
        self.assertEqual(after, 0)
        self.assertEqual(conversation_log.conversation_from_log(path, after=after), new_id)

    def test_same_inode_truncate_and_regrow_resets_the_offset(self):
        """CLI truncates in place and writes past the old size before we poll."""
        path = Path(self.log_root) / "agent-id.log"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            "x" * 200 + f"\nCreated conversation {CONV_ID}\n",
            encoding="utf-8",
        )
        mark = conversation_log.log_mark(path)
        inode = path.stat().st_ino
        new_id = "aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee"
        grown = (
            f"Created conversation {new_id}\n"
            + "y" * (mark[0] + 50)
        )
        path.write_text(grown, encoding="utf-8")
        self.assertEqual(path.stat().st_ino, inode)
        self.assertGreaterEqual(path.stat().st_size, mark[0])
        self.assertIsNone(
            conversation_log.conversation_from_log(path, after=mark[0])
        )
        after = conversation_log.suffix_offset(path, mark)
        self.assertEqual(after, 0)
        self.assertEqual(
            conversation_log.conversation_from_log(path, after=after), new_id
        )
        self.assertNotEqual(
            conversation_log.conversation_from_log(path, after=after), CONV_ID
        )

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
        self.assertIn("conversation line in this activation's log after 45s", self.messages[-1][2])
        self.assertTrue(self.messages[-1][2].startswith("agent: no Created or Resuming"))
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

    async def test_a_submitted_input_that_skips_the_wake_resends_twice_then_repools(self):
        """Regression for the stuck-badge incident, evidence-only: an idle TUI
        can hold a pasted digest unsubmitted. A USER_INPUT that contains the
        digest verifies it; one that does not *proves* the paste was skipped,
        which re-sends it up to twice — a third proof re-pools with one
        factual notice. No timer may guess at the CLI's state."""
        adapter = self.make()
        adapter.proc = Process()
        adapter.att["repool_message_ids"] = AsyncMock(return_value=True)
        sent = []
        adapter.send_keys = AsyncMock(side_effect=lambda text: sent.append(text))
        await adapter.deliver([{"id": 41, "sender": "greg", "body": "wake one"}])
        paste = adapter._outstanding[0][0]
        self.assertTrue(paste.startswith(adapter._jsonl_receipts[0]["marker"]))
        self.assertEqual([wake[0] for wake in adapter._outstanding], [paste])
        pasted = adapter._outstanding[0][1]

        # 1st skip proof -> 1st resend
        await adapter._note_user_input(
            "<USER_REQUEST>\n/some other command\n</USER_REQUEST>", later(pasted)
        )
        self.assertEqual(len(sent), 2)
        self.assertEqual(sent[0], paste)
        self.assertTrue(sent[1].startswith(adapter._jsonl_receipts[-1]["marker"]))
        self.assertEqual(adapter._jsonl_receipts[-1]["ids"], [41])
        self.assertEqual([wake[0] for wake in adapter._outstanding], [paste])

        # 2nd skip proof -> 2nd resend
        await adapter._note_user_input(
            "<USER_REQUEST>\n/second command\n</USER_REQUEST>", later(pasted)
        )
        self.assertEqual(len(sent), 3)
        self.assertEqual([wake[0] for wake in adapter._outstanding], [paste])

        # 3rd skip proof -> give up, post notice, repool
        await adapter._note_user_input(
            "<USER_REQUEST>\n/something else\n</USER_REQUEST>", later(pasted)
        )
        self.assertEqual(len(sent), 3)
        self.assertEqual(adapter._outstanding, [])
        adapter.att["repool_message_ids"].assert_awaited_once_with([41])
        self.assertEqual(len(self.messages), 1)
        self.assertTrue(self.messages[0][2].startswith("agent: the CLI submitted other input"))
        self.assertIn("wake queued for next turn-end", self.messages[0][2])
        self.assertFalse(hasattr(adapter, "_repool_messages"))

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
        paste = adapter._outstanding[0][0]
        # The record was written before the paste: no verdict either way.
        await adapter._note_user_input(
            "<USER_REQUEST>\n/unrelated earlier turn\n</USER_REQUEST>",
            time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() - 10)),
        )
        self.assertEqual(sent, [paste])
        self.assertEqual([wake[0] for wake in adapter._outstanding], [paste])
        self.assertEqual(self.messages, [])

    async def test_a_transcript_input_containing_the_digest_verifies_it(self):
        adapter = self.make()
        adapter.proc = Process()
        sent = []
        adapter.send_keys = AsyncMock(side_effect=lambda text: sent.append(text))
        await adapter.deliver([{"sender": "greg", "body": "wake two"}])
        paste = adapter._outstanding[0][0]
        # The TUI took the paste, possibly reflowed: whitespace differences
        # must still verify the digest, with no resend and no notice.
        await adapter._note_user_input(
            "<USER_REQUEST>\n  " + paste.replace("\n", " \n ") + "\n</USER_REQUEST>",
            later(adapter._outstanding[0][1]),
        )
        # Only deliver()'s original paste: verification sends nothing.
        self.assertEqual(sent, [paste])
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
        """The global cap prevents a pathological CLI from farming notices,
        and a verified wake resets it."""
        adapter = self.make()
        adapter.proc = Process()
        adapter.send_keys = AsyncMock()
        for body in ("first", "second", "third"):
            await adapter.deliver([{"sender": "greg", "body": body}])
        # 3 skips per wake triggers notice after 2 resends
        for _ in range(3):
            await adapter._note_user_input("<USER_REQUEST>\n/nope\n</USER_REQUEST>", later(time.time()))
        self.assertEqual(len(self.messages), 2)
        # A later wake that lands resets the cap for future losses.
        await adapter.deliver([{"sender": "greg", "body": "fourth"}])
        paste = adapter._outstanding[-1][0]
        await adapter._note_user_input(
            "<USER_REQUEST>\n" + paste + "\n</USER_REQUEST>", later(time.time())
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
            if waits == 1:
                self.write_log(adapter)
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
        paste = adapter._outstanding[0][0]
        await adapter._note_log_line(glog_submission(paste, adapter._outstanding[0][1] + 5))
        self.assertEqual(sent, [paste])
        self.assertEqual(adapter._outstanding, [])
        self.assertEqual(self.messages, [])

    async def test_a_log_submission_of_other_input_proves_skip_then_repools(self):
        adapter = self.make()
        adapter.proc = Process()
        adapter.att["repool_message_ids"] = AsyncMock(return_value=True)
        sent = []
        adapter.send_keys = AsyncMock(side_effect=lambda text: sent.append(text))
        await adapter.deliver([{"id": 42, "sender": "greg", "body": "wake six"}])
        pasted = adapter._outstanding[0][1]

        # 1st skip -> 1st resend
        await adapter._note_log_line(glog_submission("/status", pasted + 5))
        self.assertEqual(len(sent), 2)

        # 2nd skip -> 2nd resend
        await adapter._note_log_line(glog_submission("/info", pasted + 6))
        self.assertEqual(len(sent), 3)

        # 3rd skip -> give up, repool, notice
        await adapter._note_log_line(glog_submission("/quit", pasted + 7))
        self.assertEqual(len(sent), 3)
        self.assertEqual(adapter._outstanding, [])
        adapter.att["repool_message_ids"].assert_awaited_once_with([42])
        self.assertEqual(len(self.messages), 1)
        self.assertTrue(self.messages[0][2].startswith("agent: the CLI submitted other input"))
        self.assertIn("wake queued for next turn-end", self.messages[0][2])
        self.assertFalse(hasattr(adapter, "_repool_messages"))

    async def test_error_planner_record_emits_ended_through_run_handler(self):
        adapter = self.make(resume=True, cli_session=CONV_ID)
        adapter.proc = Process()
        receipts = []

        async def fake_receipt(att, kind, **kwargs):
            receipts.append((att["id"], kind))

        self.write_transcript([step(0, "MODEL", "PLANNER_RESPONSE", status="ERROR")])

        async def tail(_path, handle):
            await handle({
                "step_index": 0, "created_at": "2026-01-01T00:00:00Z",
                "source": "MODEL", "type": "PLANNER_RESPONSE", "status": "ERROR",
            })
            adapter.proc.stop()

        adapter._tail_jsonl = tail

        async def sleep(_seconds):
            self.write_log(adapter)

        with (
            patch("partyline.adapters.bundled.antigravity.adapter.receipt", new=fake_receipt),
            patch.object(adapter, "_fresh", return_value=True),
            patch("partyline.adapters.bundled.antigravity.adapter.asyncio.sleep", new=sleep),
        ):
            await adapter._run()

        self.assertIn((adapter.att["id"], ENDED), receipts)

    async def test_a_log_line_without_a_parseable_timestamp_cannot_judge(self):
        adapter = self.make()
        adapter.proc = Process()
        sent = []
        adapter.send_keys = AsyncMock(side_effect=lambda text: sent.append(text))
        await adapter.deliver([{"sender": "greg", "body": "wake seven"}])
        paste = adapter._outstanding[0][0]
        # A submission line with no glog prefix carries no ordering evidence.
        await adapter._note_log_line('HandleUserInput called with text: "/status"\n')
        # And a line that is not a submission says nothing at all.
        await adapter._note_log_line(glog_submission("", time.time()).replace(
            'HandleUserInput called with text: ""', "Streaming conversation abc"))
        self.assertEqual(sent, [paste])
        self.assertEqual([wake[0] for wake in adapter._outstanding], [paste])
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
        paste = adapter._outstanding[0][0]
        tail = asyncio.create_task(adapter._tail_log())
        await asyncio.sleep(0.1)  # let the tail open the file and seek to EOF
        with open(adapter.log_path(), "a", encoding="utf-8") as file:
            file.write(glog_submission(paste, time.time() + 5))
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
        adapter._write_all = AsyncMock(side_effect=lambda data: writes.append(data))
        with patch.object(antigravity_module, "PASTE_PACE", 30.0):
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
        adapter._write_all = AsyncMock(side_effect=lambda data: writes.append(data))
        with patch.object(antigravity_module, "PASTE_PACE", 0.05):
            await adapter.send_keys("wake nine")
        self.assertEqual(writes[-1], b"\r")
        # A deadline already past still sends the Enter — pacing, not a verdict.
        with patch.object(antigravity_module, "PASTE_PACE", -1.0):
            await adapter.send_keys("wake ten")
        self.assertEqual(writes[-1], b"\r")

    async def test_an_input_with_a_malformed_timestamp_still_judges(self):
        adapter = self.make()
        adapter.proc = Process()
        sent = []
        adapter.send_keys = AsyncMock(side_effect=lambda text: sent.append(text))
        await adapter.deliver([{"sender": "greg", "body": "wake eleven"}])
        paste = adapter._outstanding[0][0]
        await adapter._note_user_input(paste, "not-a-date")
        self.assertEqual(adapter._outstanding, [])
        # A record carrying no timestamp at all still settles a wake.
        await adapter.deliver([{"sender": "greg", "body": "wake twelve"}])
        paste = adapter._outstanding[0][0]
        await adapter._note_user_input(paste, None)
        self.assertEqual(adapter._outstanding, [])

    async def test_a_mid_turn_paste_is_not_credited_by_its_own_log_echo(self):
        """Regression 2026-08-24: two @gemini-flash mentions pasted mid-turn
        were credited by the HandleUserInput echo — which is the paste itself
        bounced back — and never retried, while agy had dropped them. An echo
        may only settle a wake that was pasted while the CLI was idle."""
        adapter = self.make()
        adapter.proc = Process()
        adapter._turn_open = True
        sent = []
        adapter.send_keys = AsyncMock(side_effect=lambda text: sent.append(text))
        await adapter.deliver([{"sender": "greg", "body": "busy wake"}])
        paste = adapter._outstanding[0][0]
        await adapter._note_log_line(glog_submission(paste, adapter._outstanding[0][1] + 5))
        self.assertEqual([wake[0] for wake in adapter._outstanding], [paste])
        self.assertEqual(sent, [paste])  # no blind resend into the busy TUI
        self.assertEqual(self.messages, [])

    async def test_a_transcript_input_verifies_a_mid_turn_wake(self):
        adapter = self.make()
        adapter.proc = Process()
        adapter._turn_open = True
        adapter.send_keys = AsyncMock()
        await adapter.deliver([{"sender": "greg", "body": "queued wake"}])
        paste = adapter._outstanding[0][0]
        await adapter._note_user_input(
            "<USER_REQUEST>\n" + paste + "\n</USER_REQUEST>", later(adapter._outstanding[0][1])
        )
        self.assertEqual(adapter._outstanding, [])

    async def test_a_transcript_input_without_the_digest_holds_a_mid_turn_wake(self):
        """A transcript record that skips a mid-turn wake proves it was
        dropped, but resending into a busy TUI feeds the same bit bucket:
        the wake holds for the turn-end settlement instead."""
        adapter = self.make()
        adapter.proc = Process()
        adapter._turn_open = True
        sent = []
        adapter.send_keys = AsyncMock(side_effect=lambda text: sent.append(text))
        await adapter.deliver([{"id": 7, "sender": "greg", "body": "held wake"}])
        paste = adapter._outstanding[0][0]
        await adapter._note_user_input(
            "<USER_REQUEST>\n/some other command\n</USER_REQUEST>", later(adapter._outstanding[0][1])
        )
        self.assertEqual(sent, [paste])  # only the original paste
        self.assertEqual([wake[0] for wake in adapter._outstanding], [paste])

    async def test_turn_end_repools_a_mid_turn_wake_that_never_began_a_turn(self):
        adapter = self.make()
        adapter.proc = Process()
        adapter._turn_open = True
        adapter.att["repool_message_ids"] = AsyncMock(return_value=True)
        adapter.send_keys = AsyncMock()
        await adapter.deliver([{"id": 9, "sender": "greg", "body": "lost wake"}])
        with patch(
            "partyline.adapters.bundled.antigravity.wakes.asyncio.sleep", new=AsyncMock()
        ):
            await adapter._settle_turn_end()
        adapter.att["repool_message_ids"].assert_awaited_once_with([9])
        self.assertEqual(adapter._outstanding, [])
        self.assertTrue(any("never began a turn" in body for _, _, body in self.messages))

    async def test_turn_end_grace_lets_a_queued_ingestion_land_first(self):
        """A mid-turn submission can be queued by the CLI and ingested right
        after the turn ends; its USER_INPUT lands during the grace and must
        preempt the repool, or the wake would be delivered twice."""
        adapter = self.make()
        adapter.proc = Process()
        adapter._turn_open = True
        adapter.att["repool_message_ids"] = AsyncMock(return_value=True)
        adapter.send_keys = AsyncMock()
        await adapter.deliver([{"id": 11, "sender": "greg", "body": "maybe queued"}])
        paste = adapter._outstanding[0][0]

        async def land_record_during_grace(_seconds):
            await adapter._note_user_input(
                "<USER_REQUEST>\n" + paste + "\n</USER_REQUEST>", later(time.time())
            )

        with patch(
            "partyline.adapters.bundled.antigravity.wakes.asyncio.sleep",
            new=land_record_during_grace,
        ):
            await adapter._settle_turn_end()
        adapter.att["repool_message_ids"].assert_not_awaited()
        self.assertEqual(adapter._outstanding, [])

    async def test_a_second_turn_end_gets_its_own_settlement(self):
        """Regression (sol's review of #122): an end landing while a grace
        pass is running used to be swallowed — a wake pasted into the second
        turn stayed outstanding forever because the only pending pass had
        snapshotted before it existed. Every turn end now queues exactly one
        more pass, which courts the wakes that arrived after the snapshot."""
        adapter = self.make()
        adapter.proc = Process()
        adapter._turn_open = True
        adapter.att["repool_message_ids"] = AsyncMock(return_value=True)
        adapter.send_keys = AsyncMock()
        await adapter.deliver([{"id": 21, "sender": "greg", "body": "wake one"}])
        paste1 = adapter._outstanding[0][0]
        gate = asyncio.Event()
        graces = {"n": 0}
        real_sleep = asyncio.sleep

        async def gated_sleep(seconds):
            # Patching asyncio.sleep intercepts every sleeper in the loop —
            # including this test's own yields — so delegate everything that
            # is not a grace sleep back to the real sleeper.
            if seconds != wakes_module.REPOOL_GRACE:
                await real_sleep(min(seconds, 0.05))
                return
            graces["n"] += 1
            if graces["n"] == 1:
                await gate.wait()

        with patch(
            "partyline.adapters.bundled.antigravity.wakes.asyncio.sleep", new=gated_sleep
        ):
            adapter._turn_open = False
            adapter._schedule_settle()  # pass one: snapshot has wake one only
            await asyncio.sleep(0.05)
            # wake one settles from its transcript record during the grace…
            await adapter._note_user_input(
                "<USER_REQUEST>\n" + paste1 + "\n</USER_REQUEST>", later(time.time())
            )
            # …and wake two is pasted into turn two, which ends mid-grace.
            await adapter.deliver([{"id": 22, "sender": "greg", "body": "wake two"}])
            adapter._turn_open = False
            adapter._schedule_settle()  # queued behind the running pass
            gate.set()
            for _ in range(50):
                if adapter.att["repool_message_ids"].await_count:
                    break
                await asyncio.sleep(0.02)
            await adapter._settle_task
        self.assertEqual(graces["n"], 2)
        adapter.att["repool_message_ids"].assert_awaited_once_with([22])
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
        adapter._write_all = AsyncMock(side_effect=lambda data: writes.append(data))
        with patch.object(antigravity_module, "PASTE_PACE", 0.05):
            adapter.screen_text = lambda: "nothing of ours here"
            await adapter.deliver([{"sender": "greg", "body": "second wake"}])
            self.assertTrue(writes[0].startswith(b"\x1b[200~"))  # no flush

            writes.clear()
            # ConPTY has no Unix master descriptor but needs the same flush.
            adapter.master = None
            adapter._windows = object()
            adapter.screen_text = lambda: "> " + stuck[-60:]
            await adapter.deliver([{"sender": "greg", "body": "third wake"}])
        self.assertEqual(writes[0], b"\r")  # the stuck wake is flushed first
        self.assertTrue(writes[1].startswith(b"\x1b[200~"))


if __name__ == "__main__":
    unittest.main()
