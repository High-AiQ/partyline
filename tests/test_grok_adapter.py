"""Deterministic coverage for the bundled Grok Build adapter."""

import asyncio
import json
import os
import resource
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch


def _memory_bounded() -> bool:
    """Whether the kernel would kill this process before it kills the machine.

    Checks the actual bound, not a flag someone remembered to export: either
    a finite RLIMIT_AS, or a cgroup ancestor with a real ``memory.max`` (what
    ``./scripts/capped-test`` sets up).
    """
    soft, _ = resource.getrlimit(resource.RLIMIT_AS)
    if soft != resource.RLIM_INFINITY:
        return True
    try:
        entry = Path("/proc/self/cgroup").read_text().strip().splitlines()[-1]
        node = Path("/sys/fs/cgroup") / entry.split(":", 2)[2].lstrip("/")
        while str(node).startswith("/sys/fs/cgroup"):
            limit = node / "memory.max"
            if limit.is_file() and limit.read_text().strip() != "max":
                return True
            node = node.parent
    except (OSError, IndexError):
        pass
    return False


def setUpModule():
    # This module has twice OOM-killed the whole dogfood machine (19 GB and
    # 31 GB incidents in docs/lessons.md) when a patched sleep left a poll
    # spinning. A prose warning was not a completed lesson: the file itself
    # now refuses to be the weapon. CI runners are ephemeral and run the bare
    # command on purpose.
    if not (_memory_bounded() or os.environ.get("CI")):
        raise unittest.SkipTest(
            "refusing to run unbounded: this module has twice OOM-killed the "
            "machine — run it through ./scripts/capped-test (CI is exempt)"
        )


from partyline.adapters import Adapter
from partyline.adapters.bundled.grok.adapter import PartylineAdapter
from partyline.adapters.bundled.grok import turn_hooks
from partyline.adapters.bundled.grok.resume import (
    align_delivery_history,
    announce_backlog,
    AlignmentError,
    align_delivered_sequence,
    delivery_plan_matches,
)
from partyline.adapters.bundled.grok.transcript import (
    AssistantRecord,
    latest_user_prompt,
    user_input,
)
from partyline.db import Db
from partyline.presence import Presence
from partyline.runtime import ChatRuntime
from partyline.transcript_delivery import TranscriptDeliveryRecord


SESSION_ID = "12345678-1234-4234-8234-123456789abc"


async def post(sender, sender_type, body):
    pass


async def status(value):
    pass


def make_adapter(
    *, command=None, resume=False, session_id=None, collector=post,
    delivered_bodies=None, delivered_records=None, legacy_relayed_bodies=None,
    mark_transcript_delivery=None,
):
    adapter = PartylineAdapter(
        {
            "adapter_metadata": {"env_unset": []},
            "command": list(command if command is not None else ["grok"]),
            "cli_session": session_id,
            "conv_name": "grok tests",
            "cwd": "/tmp/grok-project",
            "id": SESSION_ID,
            "name": "groky",
            "resume": resume,
            "delivered_bodies": delivered_bodies,
            "delivered_transcript_records": delivered_records,
            "legacy_relayed_bodies": legacy_relayed_bodies,
            "mark_transcript_delivery": mark_transcript_delivery,
        },
        collector,
        status,
    )
    adapter._silent_until_wake = False
    return adapter


class ManifestTest(unittest.TestCase):
    def test_manifest_declares_resumable_interactive_grok(self):
        root = Path(__file__).parents[1] / "partyline" / "adapters" / "bundled" / "grok"
        manifest = (root / "adapter.toml").read_text(encoding="utf-8")

        self.assertIn('command = ["grok", "--permission-mode", "bypassPermissions"]', manifest)
        self.assertIn("resume = true", manifest)
        self.assertIn('turn_end = "receipt"', manifest)
        self.assertIn('update_command = ["grok", "update"]', manifest)

    def test_grok_diagnostics_name_the_jack_without_self_mentions(self):
        root = Path(__file__).parents[1] / "partyline" / "adapters" / "bundled" / "grok"
        notices = "".join(
            (root / name).read_text(encoding="utf-8")
            for name in ("adapter.py", "resume.py", "tail.py")
        )

        self.assertNotIn('f"@{adapter.att[', notices)
        self.assertNotIn('f"@{self.att[', notices)


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


class WakeCreditTest(unittest.IsolatedAsyncioTestCase):
    async def test_cursor_waits_for_a_new_matching_transcript_user_record(self):
        with tempfile.TemporaryDirectory() as directory:
            db = Db(Path(directory) / "partyline.db")
            try:
                db.create_conversation("line", "Line")
                db.add_attachment(
                    SESSION_ID, "line", "groky", "grok", ["grok"], directory, "owner"
                )
                db.set_attachment_status(SESSION_ID, "running", "owner")
                runtime = ChatRuntime(db)
                presence = Presence(runtime)
                adapter = make_adapter()
                adapter.att["runtime_owner"] = "owner"
                adapter.format_digest = lambda _messages: "the exact wake digest"
                adapter.send_keys = AsyncMock()
                watched = presence.watch(
                    adapter,
                    "line",
                    SESSION_ID,
                    "receipt",
                    *runtime.held_wake_hooks("line", SESSION_ID, "groky"),
                )
                runtime.live[SESSION_ID] = watched
                message = db.add_message("line", "greg", "human", "@groky approved")

                self.assertFalse(
                    await runtime.deliver_pending(
                        "line", db.get_attachment(SESSION_ID), watched
                    )
                )
                self.assertEqual(db.get_attachment(SESSION_ID)["last_seen"], 0)
                adapter.send_keys.assert_awaited_once_with("the exact wake digest")

                # Routing again while the cursor correctly stays behind must
                # not paste the identical outstanding batch twice.
                self.assertFalse(
                    await runtime.deliver_pending(
                        "line", db.get_attachment(SESSION_ID), watched
                    )
                )
                adapter.send_keys.assert_awaited_once()

                adapter._wake_receipts.seed(466)
                await adapter._note_user_record({
                    "type": "user",
                    "prompt_index": 466,
                    "content": [{"type": "text", "text": "the exact wake digest"}],
                })
                self.assertEqual(db.get_attachment(SESSION_ID)["last_seen"], 0)

                await adapter._note_user_record({
                    "type": "user",
                    "prompt_index": 467,
                    "content": [{
                        "type": "text",
                        "text": "<user_query>\nthe exact wake digest\n</user_query>",
                    }],
                })
                self.assertEqual(
                    db.get_attachment(SESSION_ID)["last_seen"], message["id"]
                )

                later = db.add_message("line", "greg", "human", "@groky one more")
                self.assertFalse(
                    await runtime.deliver_pending(
                        "line", db.get_attachment(SESSION_ID), watched
                    )
                )
                self.assertTrue(db.set_attachment_status(SESSION_ID, "exited", "owner"))
                self.assertTrue(db.claim_attachment(SESSION_ID, "replacement"))
                self.assertTrue(
                    db.set_attachment_status(SESSION_ID, "running", "replacement")
                )
                await adapter._note_user_record({
                    "type": "user",
                    "prompt_index": 468,
                    "content": [{"type": "text", "text": "the exact wake digest"}],
                })
                self.assertEqual(
                    db.get_attachment(SESSION_ID)["last_seen"], message["id"]
                )
                self.assertGreater(later["id"], message["id"])
            finally:
                db.close()

    async def test_failed_pty_write_does_not_suppress_a_retry(self):
        adapter = make_adapter()
        adapter.att["confirm_delivery_ids"] = AsyncMock(return_value=True)
        adapter.format_digest = lambda _messages: "retry this wake"
        adapter.send_keys = AsyncMock(side_effect=RuntimeError("pty closed"))

        with self.assertRaisesRegex(RuntimeError, "pty closed"):
            await adapter.deliver([{"id": 41}])

        adapter.send_keys = AsyncMock()
        self.assertFalse(await adapter.deliver([{"id": 41}]))
        adapter.send_keys.assert_awaited_once_with("retry this wake")

    async def test_confirmed_superset_covers_a_swallowed_earlier_wake(self):
        adapter = make_adapter()
        credited = AsyncMock(return_value=True)
        adapter.att["confirm_delivery_ids"] = credited
        adapter.send_keys = AsyncMock()
        adapter.format_digest = lambda messages: "wake " + ",".join(
            str(message["id"]) for message in messages
        )

        self.assertFalse(await adapter.deliver([{"id": 41}]))
        self.assertFalse(await adapter.deliver([{"id": 41}, {"id": 42}]))
        await adapter._note_user_record({
            "type": "user",
            "prompt_index": 1,
            "content": [{
                "type": "text",
                "text": "<user_query>\nwake 41,42\n</user_query>",
            }],
        })

        credited.assert_awaited_once_with([41, 42])
        self.assertEqual(adapter._wake_receipts.pending, [])
        self.assertEqual(adapter.send_keys.await_count, 2)

    async def test_confirmed_disjoint_batch_cannot_jump_an_unconfirmed_wake(self):
        adapter = make_adapter()
        credited = AsyncMock(return_value=True)
        adapter.att["confirm_delivery_ids"] = credited
        adapter.send_keys = AsyncMock()
        adapter.format_digest = lambda messages: "wake " + ",".join(
            str(message["id"]) for message in messages
        )

        self.assertFalse(await adapter.deliver([{"id": 41}]))
        self.assertFalse(await adapter.deliver([{"id": 42}]))
        await adapter._note_user_record({
            "type": "user",
            "prompt_index": 1,
            "content": [{"type": "text", "text": "wake 42"}],
        })
        credited.assert_not_awaited()

        await adapter._note_user_record({
            "type": "user",
            "prompt_index": 2,
            "content": [{"type": "text", "text": "wake 41"}],
        })
        credited.assert_awaited_once_with([41, 42])

    async def test_one_user_record_credits_one_occurrence_of_an_identical_digest(self):
        adapter = make_adapter()
        credited = AsyncMock(return_value=True)
        adapter.att["confirm_delivery_ids"] = credited
        adapter.send_keys = AsyncMock()
        adapter.format_digest = lambda _messages: "same digest"

        self.assertFalse(await adapter.deliver([{"id": 41}]))
        self.assertFalse(await adapter.deliver([{"id": 42}]))
        await adapter._note_user_record({
            "type": "user",
            "prompt_index": 1,
            "content": [{"type": "text", "text": "same digest"}],
        })
        credited.assert_awaited_once_with([41])

        await adapter._note_user_record({
            "type": "user",
            "prompt_index": 2,
            "content": [{"type": "text", "text": "same digest"}],
        })
        self.assertEqual(credited.await_args_list[-1].args[0], [42])

    async def test_transcript_tail_is_the_component_that_confirms_the_wake(self):
        with tempfile.TemporaryDirectory() as directory:
            transcript = Path(directory) / "chat_history.jsonl"
            adapter = make_adapter()
            adapter._accounted = 0
            adapter.format_digest = lambda _messages: "tail-confirmed digest"
            adapter.send_keys = AsyncMock()
            running = True
            confirmed = asyncio.Event()

            async def credit(message_ids):
                nonlocal running
                self.assertEqual(message_ids, [51])
                running = False
                confirmed.set()
                return True

            adapter.att["confirm_delivery_ids"] = credit
            adapter.alive = lambda: running
            self.assertFalse(await adapter.deliver([{"id": 51}]))
            transcript.write_text(
                '{"type":"user","prompt_index":1,"content":['
                '{"type":"text","text":"tail-confirmed digest"}]}\n',
                encoding="utf-8",
            )

            await asyncio.wait_for(
                adapter._tail_grok_transcript(transcript, AsyncMock()), timeout=1
            )
            self.assertTrue(confirmed.is_set())


class TurnHookTest(unittest.TestCase):
    def test_payload_is_a_session_filtered_pair_without_subagent_stop(self):
        url = "http://127.0.0.1:9/api/hooks/a/tok"
        doc = turn_hooks.payload(url, SESSION_ID)
        self.assertEqual(
            set(doc["hooks"]),
            {"UserPromptSubmit", "Stop", "StopFailure", "StopCancelled"},
        )
        command = doc["hooks"]["Stop"][0]["hooks"][0]["command"]
        self.assertEqual(command, doc["hooks"]["UserPromptSubmit"][0]["hooks"][0]["command"])
        self.assertIn(SESSION_ID, command)
        self.assertIn(url, command)
        self.assertNotIn("SubagentStop", doc["hooks"])
        for name in ("stop", "userpromptsubmit", "stopfailure", "stopcancelled"):
            self.assertIn(repr(name), command)

    def test_install_lives_under_partyline_and_registers_hooks_paths(self):
        with tempfile.TemporaryDirectory() as tmp:
            att = {
                "grok_hooks_dir": str(Path(tmp) / "hooks"),
                "grok_hooks_paths": str(Path(tmp) / "hooks-paths"),
            }
            path = turn_hooks.install("http://example.test/h", SESSION_ID, att)
            self.assertTrue(path.is_file())
            self.assertEqual(path.parent, Path(att["grok_hooks_dir"]))
            self.assertIn(str(path.resolve()), Path(att["grok_hooks_paths"]).read_text())
            turn_hooks.uninstall(SESSION_ID, att)
            self.assertFalse(path.exists())
            self.assertNotIn(str(path.resolve()), Path(att["grok_hooks_paths"]).read_text())


class TranscriptTest(unittest.TestCase):
    def test_user_input_requires_a_real_prompt_ordinal(self):
        fixture = Path(__file__).parent / "fixtures" / "grok_user_delivery.jsonl"
        record = json.loads(fixture.read_text().splitlines()[0])

        self.assertEqual(user_input(record), (466, "historical input"))
        self.assertEqual(latest_user_prompt(fixture), 466)
        self.assertEqual(
            user_input({
                "type": "user",
                "prompt_index": 467,
                "content": "prefix <user_query>historical input</user_query>",
            }),
            (467, "prefix <user_query>historical input</user_query>"),
        )
        self.assertIsNone(user_input({"type": "user", "content": "no ordinal"}))
        self.assertIsNone(user_input({
            "type": "user",
            "prompt_index": 467,
            "synthetic_reason": "compaction_meta",
            "content": "summary",
        }))

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
        self.assertIsNone(PartylineAdapter._assistant_text([]))
        self.assertIsNone(PartylineAdapter._assistant_text("bare string"))
        self.assertIsNone(PartylineAdapter._assistant_text(42))
        self.assertIsNone(PartylineAdapter._assistant_text(None))
        self.assertIsNone(PartylineAdapter._assistant_text({"type": "reasoning", "content": "secret"}))
        self.assertIsNone(PartylineAdapter._assistant_text({"type": "assistant", "content": []}))
        self.assertIsNone(PartylineAdapter._assistant_text({"type": "assistant", "content": 3}))
        self.assertEqual(
            PartylineAdapter._assistant_text({
                "type": "assistant", "content": "I am about to work",
                "tool_calls": [{"id": "x"}],
            }),
            "I am about to work",
        )
        self.assertIsNone(PartylineAdapter._assistant_text({
            "type": "assistant", "content": "  ", "tool_calls": [{"id": "x"}],
        }))
        self.assertEqual(
            PartylineAdapter._assistant_text({
                "type": "assistant", "content": "finished reply", "tool_calls": [],
            }),
            "finished reply",
        )

    def test_live_ack_beside_tools_is_room_speech(self):
        # Captured from grok2 session 060f33b4 on 2026-08-19. Peek showed this
        # sentence; the room never did, because the record also had tool_calls.
        record = {
            "type": "assistant",
            "content": (
                "@greg-at-work I’ll check why the others look stuck on the line "
                "and whether `https://partyline.home.arpa` is actually up."
            ),
            "tool_calls": [{"id": "a"}, {"id": "b"}, {"id": "c"}],
        }
        self.assertEqual(PartylineAdapter._assistant_text(record), record["content"])

    def test_pinned_uuid_requires_one_exact_transcript(self):
        adapter = make_adapter()
        adapter._session_id = SESSION_ID
        expected = Path("/tmp/sessions/cwd") / SESSION_ID / "chat_history.jsonl"
        with patch("partyline.adapters.bundled.grok.adapter.glob.glob", return_value=[str(expected)]):
            self.assertEqual(adapter._transcript(), expected)
        with patch("partyline.adapters.bundled.grok.adapter.glob.glob", return_value=[]):
            self.assertIsNone(adapter._transcript())


class ResumeTranscriptTest(unittest.IsolatedAsyncioTestCase):
    async def test_replaced_transcript_skips_history_and_relays_new_speech(self):
        """Grok resume replaces the file, so the tail must reopen by inode."""
        posted = []
        delivered = asyncio.Event()
        running = True

        async def handle(record):
            posted.append(record["content"])
            delivered.set()

        with tempfile.TemporaryDirectory() as directory:
            transcript = Path(directory) / "chat_history.jsonl"
            transcript.write_text(
                '{"type":"assistant","content":"old reply"}\n', encoding="utf-8",
            )
            adapter = make_adapter(resume=True, session_id=SESSION_ID)
            adapter._accounted = 1
            adapter.alive = lambda: running
            task = asyncio.create_task(adapter._tail_grok_transcript(transcript, handle))
            await asyncio.wait_for(adapter._ready.wait(), timeout=1)

            replacement = Path(directory) / "replacement.jsonl"
            replacement.write_text(
                '{"type":"assistant","content":"old reply"}\n'
                '{"type":"assistant","content":"new reply"}\n',
                encoding="utf-8",
            )
            replacement.replace(transcript)
            await asyncio.wait_for(delivered.wait(), timeout=2)
            running = False
            await asyncio.wait_for(task, timeout=2)

        self.assertEqual(posted, ["new reply"])

    async def test_rewrite_does_not_repost_speech_already_relayed(self):
        posted = []
        first_delivered = asyncio.Event()
        delivered = asyncio.Event()
        running = True

        async def handle(record):
            posted.append(record["content"])
            if len(posted) == 1:
                first_delivered.set()
            if len(posted) == 2:
                delivered.set()

        with tempfile.TemporaryDirectory() as directory:
            transcript = Path(directory) / "chat_history.jsonl"
            transcript.write_text(
                '{"type":"assistant","content":"first reply"}\n', encoding="utf-8",
            )
            adapter = make_adapter()
            adapter.alive = lambda: running
            task = asyncio.create_task(adapter._tail_grok_transcript(transcript, handle))
            await asyncio.wait_for(first_delivered.wait(), timeout=1)

            replacement = Path(directory) / "replacement.jsonl"
            replacement.write_text(
                '{"type":"assistant","content":"first reply"}\n'
                '{"type":"assistant","content":"second reply"}\n',
                encoding="utf-8",
            )
            replacement.replace(transcript)
            await asyncio.wait_for(delivered.wait(), timeout=2)
            running = False
            await asyncio.wait_for(task, timeout=2)

        self.assertEqual(posted, ["first reply", "second reply"])

    async def test_compaction_relays_replies_written_after_the_rewrite(self):
        """A shorter replacement must re-anchor the watermark, not mute the tail."""
        posted = []
        caught_up = asyncio.Event()
        delivered = asyncio.Event()
        running = True

        async def handle(record):
            posted.append(record["content"])
            if len(posted) == 5:
                caught_up.set()
            if record["content"] == "post-compaction reply":
                delivered.set()

        with tempfile.TemporaryDirectory() as directory:
            transcript = Path(directory) / "chat_history.jsonl"
            transcript.write_text(
                "".join(
                    f'{{"type":"assistant","content":"reply {n}"}}\n' for n in range(1, 6)
                ),
                encoding="utf-8",
            )
            adapter = make_adapter()
            adapter.alive = lambda: running
            task = asyncio.create_task(adapter._tail_grok_transcript(transcript, handle))
            await asyncio.wait_for(caught_up.wait(), timeout=1)

            replacement = Path(directory) / "replacement.jsonl"
            replacement.write_text(
                '{"type":"assistant","content":"reply 4"}\n'
                '{"type":"assistant","content":"reply 5"}\n'
                '{"type":"assistant","content":"post-compaction reply"}\n',
                encoding="utf-8",
            )
            replacement.replace(transcript)
            await asyncio.wait_for(delivered.wait(), timeout=2)
            running = False
            await asyncio.wait_for(task, timeout=2)

        self.assertEqual(
            posted,
            [f"reply {n}" for n in range(1, 6)] + ["post-compaction reply"],
        )

    async def test_fully_rewritten_transcript_relays_everything_it_contains(self):
        """No retained records means no overlap, so nothing may be skipped."""
        posted = []
        caught_up = asyncio.Event()
        delivered = asyncio.Event()
        running = True

        async def handle(record):
            posted.append(record["content"])
            if len(posted) == 2:
                caught_up.set()
            if record["content"] == "brand new":
                delivered.set()

        with tempfile.TemporaryDirectory() as directory:
            transcript = Path(directory) / "chat_history.jsonl"
            transcript.write_text(
                '{"type":"assistant","content":"old one"}\n'
                '{"type":"assistant","content":"old two"}\n',
                encoding="utf-8",
            )
            adapter = make_adapter()
            adapter.alive = lambda: running
            task = asyncio.create_task(adapter._tail_grok_transcript(transcript, handle))
            await asyncio.wait_for(caught_up.wait(), timeout=1)

            replacement = Path(directory) / "replacement.jsonl"
            replacement.write_text(
                '{"type":"assistant","content":"brand new"}\n', encoding="utf-8",
            )
            replacement.replace(transcript)
            await asyncio.wait_for(delivered.wait(), timeout=2)
            running = False
            await asyncio.wait_for(task, timeout=2)

        self.assertEqual(posted, ["old one", "old two", "brand new"])

    async def test_resync_keeps_its_position_on_an_unreadable_replacement(self):
        """Awaited on purpose: this ran as an un-awaited coroutine and passed.

        Found by @sol. The method became async and the call did not, so the
        test exercised no production code at all while reporting green — the
        repo's "a green test without its failing control proves nothing" class,
        in its purest form. A refusal here must keep the old position *and*
        say so out loud, since silently holding a watermark is how a muted
        process looks identical to an idle one.
        """
        posted = []

        async def collect(sender, sender_type, body):
            posted.append(body)

        adapter = make_adapter(collector=collect)
        adapter._accounted = 7
        adapter._assistant_fingerprints = [b"fingerprint"]
        await adapter._resync_after_replace(Path("/gone"))

        self.assertEqual(adapter._accounted, 7)
        self.assertIn("holding position and retrying", posted[0])


class ResumeWatermarkTest(unittest.IsolatedAsyncioTestCase):
    """The failing control for the post-restart replay incident.

    On 2026-08-17 a dogfood restart left @grok reposting its entire
    pre-restart history to the line, in order, ending exactly at the old end
    of history. The transcript was one continuous 1MB file whose first
    assistant record was the session's first reply — so the watermark had to
    have been zero, not merely short. These tests pin the doors that let a
    bad count through.
    """

    def history(self, count):
        return "".join(
            f'{{"type":"assistant","content":"old reply {n}"}}\n' for n in range(count)
        )

    async def settle(self, adapter, target, attribute="_accounted"):
        """Wait on an observable state change rather than on a duration."""
        for _ in range(400):
            if getattr(adapter, attribute) == target:
                return
            await asyncio.sleep(0.005)
        self.fail(f"{attribute} never reached {target}")

    async def test_history_arriving_after_the_count_is_not_replayed(self):
        posted = []
        running = True

        async def collect(sender, sender_type, body):
            posted.append(body)

        with tempfile.TemporaryDirectory() as directory:
            transcript = Path(directory) / "chat_history.jsonl"
            # Grok has recreated the file but has not restored history yet.
            transcript.write_text("", encoding="utf-8")
            adapter = make_adapter(resume=True, session_id=SESSION_ID, collector=collect)
            adapter.POLL_SECONDS = 0.01
            adapter.SETTLE_SECONDS = 0.03
            adapter.alive = lambda: running
            with patch.object(adapter, "_transcript", return_value=transcript):
                task = asyncio.create_task(adapter._run())
                await asyncio.sleep(0.02)
                transcript.write_text(self.history(3), encoding="utf-8")
                await self.settle(adapter, 3)
                running = False
                await asyncio.wait_for(task, timeout=2)

        self.assertEqual(posted, [])

    async def test_speech_after_a_resume_still_reaches_the_room(self):
        """The guard must not buy silence by muting the process entirely."""
        posted = []
        running = True

        async def collect(sender, sender_type, body):
            posted.append(body)

        with tempfile.TemporaryDirectory() as directory:
            transcript = Path(directory) / "chat_history.jsonl"
            transcript.write_text(self.history(2), encoding="utf-8")
            adapter = make_adapter(resume=True, session_id=SESSION_ID, collector=collect)
            adapter.POLL_SECONDS = 0.01
            adapter.SETTLE_SECONDS = 0.03
            adapter.alive = lambda: running
            with patch.object(adapter, "_transcript", return_value=transcript):
                task = asyncio.create_task(adapter._run())
                await self.settle(adapter, 2)
                with transcript.open("a", encoding="utf-8") as file:
                    file.write('{"type":"assistant","content":"live again"}\n')
                await self.settle(adapter, 3)
                running = False
                await asyncio.wait_for(task, timeout=2)

        self.assertEqual(posted, ["live again"])

    async def test_a_transcript_that_moves_during_the_scan_is_not_accepted(self):
        """Quiet before the read is not quiet during it.

        Found in review by @sol: the settle window closed, the scan started,
        and the restore resumed while the file was being read — yielding a
        count of what the transcript used to hold. A short watermark replays
        the difference, which is the same failure through a narrower door.
        """
        with tempfile.TemporaryDirectory() as directory:
            transcript = Path(directory) / "chat_history.jsonl"
            transcript.write_text(self.history(1), encoding="utf-8")
            adapter = make_adapter(resume=True, session_id=SESSION_ID)
            adapter.POLL_SECONDS = 0.001
            adapter.SETTLE_SECONDS = 0.002
            adapter.alive = lambda: True
            original_scan = adapter._assistant_scan
            grew = []

            def scan_then_grow(path):
                scanned = original_scan(path)
                if not grew:  # the restore resumes mid-read, exactly once
                    grew.append(True)
                    with path.open("a", encoding="utf-8") as file:
                        file.write('{"type":"assistant","content":"old reply 1"}\n')
                return scanned

            with patch.object(adapter, "_assistant_scan", side_effect=scan_then_grow):
                accepted = await adapter._settled_assistant_scan(transcript)

        # The count must describe the file as it finally stands, never the
        # shorter one the scan happened to read.
        self.assertEqual(len(accepted), 2)

    async def test_a_transcript_that_never_settles_is_refused_out_loud(self):
        posted = []

        async def collect(sender, sender_type, body):
            posted.append(body)

        with tempfile.TemporaryDirectory() as directory:
            transcript = Path(directory) / "chat_history.jsonl"
            transcript.write_text("", encoding="utf-8")
            adapter = make_adapter(resume=True, session_id=SESSION_ID, collector=collect)
            adapter.POLL_SECONDS = 0.001
            adapter.SETTLE_TIMEOUT = 0.02
            adapter.alive = lambda: True
            writing = True

            # 2026-08-19: this writer was unbounded and `_run()` had no
            # timeout. A regression that made `_run()` not return turned the
            # pair into the 31 GB climb that OOM-killed the cockpit twice
            # (crash_report.md). The cap bounds the bomb; the assertion below
            # proves the cap was never the reason the writer stopped.
            writer_cap = 50_000

            async def keep_growing():
                index = 0
                while writing and index < writer_cap:
                    with transcript.open("a", encoding="utf-8") as file:
                        file.write(f'{{"type":"assistant","content":"{index}"}}\n')
                    index += 1
                    await asyncio.sleep(0)
                return index

            writer = asyncio.create_task(keep_growing())
            try:
                with patch.object(adapter, "_transcript", return_value=transcript):
                    await asyncio.wait_for(adapter._run(), timeout=5)
            finally:
                writing = False
                written = await asyncio.wait_for(writer, timeout=2)

        self.assertLess(written, writer_cap)
        self.assertIn("could not be counted", posted[0])
        self.assertFalse(await adapter.wait_ready())

    async def test_an_empty_pre_spawn_scan_is_not_accepted_as_a_count(self):
        """The second door: `start()` counting a transcript already recreated."""
        with tempfile.TemporaryDirectory() as directory:
            transcript = Path(directory) / "chat_history.jsonl"
            transcript.write_text("", encoding="utf-8")
            adapter = make_adapter(resume=True, session_id=SESSION_ID)
            with (
                patch.object(adapter, "_transcript", return_value=transcript),
                patch.object(Adapter, "start", new=AsyncMock()),
            ):
                await adapter.start()

        self.assertIsNone(adapter._accounted)


class ResumeReplacementTest(unittest.IsolatedAsyncioTestCase):
    """The live shape the first watermark fix did not model.

    Observed 2026-08-17 on the second dogfood restart, isolated by @sol:
    ``start()`` counts the old transcript, then Grok's resume replaces it with
    an *empty* file and refills it. The tail sees a replacement, finds no
    overlap with what it had seen, concludes the history was rewritten from
    scratch, and zeroes the watermark — so the refill relays the entire
    session back into the room. Every earlier guard was true and none of them
    applied: nothing was moving at the moment anything was counted.
    """

    def history(self, first, count):
        return "".join(
            f'{{"type":"assistant","content":"old reply {n}"}}\n'
            for n in range(first, first + count)
        )

    async def test_a_relayed_backlog_record_is_not_replayed_on_the_next_resume(self):
        """The chat-order append placed old transcript speech at the wrong boundary.

        A resume hatch relays the first transcript record after the normally
        delivered tail, so an ordered body alignment cannot match it later.
        The marker must survive Grok re-serializing the retained record, and
        its body fallback must remain hatch-only so identical new speech posts.
        """
        stale = "Standing by after compact."
        marked = []
        first_posted = []
        first_running = True

        async def first_collect(sender, sender_type, body):
            first_posted.append((sender_type, body))

        def mark(fingerprint, body):
            marked.append((fingerprint, body))
            return True

        with tempfile.TemporaryDirectory() as directory:
            transcript = Path(directory) / "chat_history.jsonl"
            transcript.write_text(
                json.dumps({"type": "assistant", "content": stale}) + "\n"
                + self.history(0, 2),
                encoding="utf-8",
            )
            adapter = make_adapter(
                resume=True,
                session_id=SESSION_ID,
                collector=first_collect,
                delivered_bodies=["old reply 0", "old reply 1"],
                mark_transcript_delivery=mark,
            )
            adapter.POLL_SECONDS = 0.005
            adapter.SETTLE_SECONDS = 0.02
            adapter.alive = lambda: first_running

            with patch.object(adapter, "_transcript", return_value=transcript):
                task = asyncio.create_task(adapter._run())
                for _ in range(300):
                    if marked:
                        break
                    await asyncio.sleep(0.01)
                first_running = False
                await asyncio.wait_for(task, timeout=3)

            self.assertEqual([body for kind, body in first_posted if kind == "agent"], [stale])
            self.assertEqual(len(marked), 1)
            self.assertEqual(marked[0][1], stale)
            self.assertEqual(adapter._delivered_bodies, ["old reply 0", "old reply 1"])

            # Compaction retained the semantic record but rewrote its JSON
            # bytes. Raw fingerprint matching alone replays it on this resume.
            transcript.write_text(
                json.dumps({"content": stale, "type": "assistant"}) + "\n"
                + self.history(0, 2),
                encoding="utf-8",
            )

            second_posted = []
            second_running = True

            async def second_collect(sender, sender_type, body):
                second_posted.append((sender_type, body))

            resumed = make_adapter(
                resume=True,
                session_id=SESSION_ID,
                collector=second_collect,
                delivered_bodies=["old reply 0", "old reply 1"],
                delivered_records=[TranscriptDeliveryRecord(marked[0][0], stale)],
            )
            resumed.POLL_SECONDS = 0.005
            resumed.SETTLE_SECONDS = 0.02
            resumed.alive = lambda: second_running

            with patch.object(resumed, "_transcript", return_value=transcript):
                task = asyncio.create_task(resumed._run())
                await asyncio.sleep(0.1)
                self.assertEqual(second_posted, [])
                with transcript.open("a", encoding="utf-8") as file:
                    file.write(json.dumps({"type": "assistant", "content": stale}) + "\n")
                for _ in range(300):
                    if second_posted:
                        break
                    await asyncio.sleep(0.01)
                second_running = False
                await asyncio.wait_for(task, timeout=3)

        self.assertEqual(second_posted, [("agent", stale)])

    async def test_a_large_resume_backlog_is_refused_without_muting_new_speech(self):
        posted = []
        running = True

        async def collect(sender, sender_type, body):
            posted.append((sender_type, body))

        with tempfile.TemporaryDirectory() as directory:
            transcript = Path(directory) / "chat_history.jsonl"
            backlog = "".join(
                json.dumps({"type": "assistant", "content": f"stale {index}"}) + "\n"
                for index in range(171)
            )
            transcript.write_text(backlog + self.history(0, 2), encoding="utf-8")
            adapter = make_adapter(
                resume=True,
                session_id=SESSION_ID,
                collector=collect,
                delivered_bodies=["old reply 0", "old reply 1"],
            )
            adapter.POLL_SECONDS = 0.005
            adapter.SETTLE_SECONDS = 0.02
            adapter.alive = lambda: running

            with patch.object(adapter, "_transcript", return_value=transcript):
                task = asyncio.create_task(adapter._run())
                for _ in range(300):
                    if posted:
                        break
                    await asyncio.sleep(0.01)
                self.assertEqual(len(posted), 1)
                self.assertEqual(posted[0], (
                    "system",
                    "groky: resume backlog of 171 looks like misaligned history — "
                    "skipped; new speech will relay",
                ))
                with transcript.open("a", encoding="utf-8") as file:
                    file.write(json.dumps({"type": "assistant", "content": "new speech"}) + "\n")
                for _ in range(300):
                    if len(posted) == 2:
                        break
                    await asyncio.sleep(0.01)
                running = False
                await asyncio.wait_for(task, timeout=3)

        self.assertEqual(posted[-1], ("agent", "new speech"))

    async def test_legacy_replay_notices_heal_an_already_looping_record(self):
        posted = []
        running = True

        async def collect(sender, sender_type, body):
            posted.append((sender_type, body))

        with tempfile.TemporaryDirectory() as directory:
            transcript = Path(directory) / "chat_history.jsonl"
            transcript.write_text(
                '{"type":"assistant","content":"stale"}\n' + self.history(0, 2),
                encoding="utf-8",
            )
            adapter = make_adapter(
                resume=True,
                session_id=SESSION_ID,
                collector=collect,
                delivered_bodies=["old reply 0", "old reply 1"],
                legacy_relayed_bodies=["stale", "stale", "stale"],
            )
            adapter.POLL_SECONDS = 0.005
            adapter.SETTLE_SECONDS = 0.02
            adapter.alive = lambda: running

            with patch.object(adapter, "_transcript", return_value=transcript):
                task = asyncio.create_task(adapter._run())
                await asyncio.sleep(0.1)
                running = False
                await asyncio.wait_for(task, timeout=3)

        self.assertEqual(posted, [])

    async def test_a_restored_sequence_suppresses_replays_not_missing_speech(self):
        """Captured v0.38.2 failure: a restored file is not a positional superset.

        Grok wrote speech while its relay was muted, then spoke again after an
        intervening restart.  The next restore placed the missing speech
        *before* the already-delivered tail, so carrying the old ordinal
        skipped part of the backlog and reposted part of that tail.  Partyline
        must align its own delivered sequence, relay the unmatched backlog,
        and suppress only the matched records.  A later identical body is new
        speech and must still relay: this is a resume boundary, never global
        body deduplication.
        """
        posted = []
        running = True

        async def collect(sender, sender_type, body):
            posted.append(body)

        with tempfile.TemporaryDirectory() as directory:
            transcript = Path(directory) / "chat_history.jsonl"
            transcript.write_text(self.history(0, 2), encoding="utf-8")
            adapter = make_adapter(
                resume=True,
                session_id=SESSION_ID,
                collector=collect,
                delivered_bodies=["old reply 0", "old reply 1"],
            )
            adapter.POLL_SECONDS = 0.005
            adapter.SETTLE_SECONDS = 0.02
            adapter.alive = lambda: running

            with patch.object(adapter, "_transcript", return_value=transcript):
                with patch.object(Adapter, "start", new=AsyncMock()):
                    await adapter.start()
                task = asyncio.create_task(adapter._run())
                await asyncio.sleep(0.05)
                restored = Path(directory) / "restored.jsonl"
                restored.write_text(
                    '{"type":"assistant","content":"missed while muted"}\n'
                    + self.history(0, 2),
                    encoding="utf-8",
                )
                restored.replace(transcript)
                for _ in range(300):
                    if "missed while muted" in posted:
                        break
                    await asyncio.sleep(0.01)
                with transcript.open("a", encoding="utf-8") as file:
                    file.write('{"type":"assistant","content":"old reply 1"}\n')
                for _ in range(300):
                    if posted.count("old reply 1") == 1:
                        break
                    await asyncio.sleep(0.01)
                running = False
                await asyncio.wait_for(task, timeout=3)

        # The notice rides in front of the flush it describes; the speech
        # itself is unchanged — suppression and ordering still hold.
        self.assertTrue(posted[0].startswith("groky: relaying 1 message(s)"))
        self.assertEqual(posted[1:], ["missed while muted", "old reply 1"])

    async def test_a_resume_says_how_much_of_its_flush_is_history(self):
        """Stale speech that reads as current nearly cost a merge revert.

        The count comes from the alignment rather than from message volume or
        record age: the transcript carries no timestamps, so any heuristic
        would be a guess where an exact number already exists.
        """
        posted = []

        async def collect(sender, sender_type, body):
            posted.append((sender_type, body))

        adapter = make_adapter(resume=True, session_id=SESSION_ID, collector=collect)
        adapter._pending_backlog = 39
        await announce_backlog(adapter)

        self.assertEqual(len(posted), 1)
        sender_type, body = posted[0]
        self.assertEqual(sender_type, "system")
        self.assertFalse(body.startswith("@"))
        self.assertIn("39 message(s) that never reached this line", body)
        self.assertIn("older state", body)

    async def test_a_refused_alignment_drops_an_earlier_pending_count(self):
        """A count belongs to the alignment that measured it.

        Raised by @sol: if a later alignment refuses, its predecessor's
        backlog must not survive and describe a flush that no longer exists.
        """
        posted = []

        async def collect(sender, sender_type, body):
            posted.append(body)

        with tempfile.TemporaryDirectory() as directory:
            transcript = Path(directory) / "chat_history.jsonl"
            transcript.write_text(
                '{"type":"assistant","content":"Idle."}\n'
                '{"type":"assistant","content":"Idle."}\n',
                encoding="utf-8",
            )
            adapter = make_adapter(resume=True, session_id=SESSION_ID, collector=collect)
            adapter.POLL_SECONDS = 0.005
            adapter.SETTLE_SECONDS = 0.01
            adapter.alive = lambda: True
            adapter._pending_backlog = 39  # measured by an earlier alignment
            adapter._delivered_bodies = ["Idle."]  # ambiguous: no unique suffix

            await align_delivery_history(adapter, transcript)

        self.assertEqual(adapter._pending_backlog, 0)
        self.assertTrue(any("no unique suffix" in body for body in posted))

    async def test_a_resume_with_nothing_held_back_says_nothing(self):
        posted = []

        async def collect(sender, sender_type, body):
            posted.append(body)

        adapter = make_adapter(resume=True, session_id=SESSION_ID, collector=collect)
        await announce_backlog(adapter)

        self.assertEqual(posted, [])

    def test_an_ambiguous_delivered_suffix_is_refused_not_guessed(self):
        records = [
            AssistantRecord(b"fingerprint", body)
            for body in ["Idle.", "working", "Idle.", "working"]
        ]

        with self.assertRaisesRegex(AlignmentError, "no unique suffix"):
            align_delivered_sequence(records, ["Idle.", "working"])

    def test_a_repeated_body_is_matched_by_occurrence_not_globally_deduplicated(self):
        records = [
            AssistantRecord(b"fingerprint", body)
            for body in ["armed", "missed", "checkpoint", "armed", "done"]
        ]

        aligned = align_delivered_sequence(
            records, ["older", "checkpoint", "armed", "done"]
        )

        self.assertEqual(aligned.skip, frozenset({3, 4, 5}))
        self.assertEqual(aligned.backlog, 2)

    def test_attachment_age_does_not_exhaust_the_alignment(self):
        delivered = [f"reply {index}" for index in range(2500)]
        records = [AssistantRecord(b"fingerprint", "missed while muted")]
        records.extend(
            AssistantRecord(b"fingerprint", body) for body in delivered
        )

        aligned = align_delivered_sequence(records, delivered)

        self.assertEqual(len(aligned.skip), 2500)
        self.assertNotIn(1, aligned.skip)
        self.assertEqual(aligned.backlog, 1)

    def test_repeated_history_refuses_before_allocating_too_many_pairs(self):
        delivered = ["Idle."] * 381 + ["unique boundary"]
        records = [AssistantRecord(b"fingerprint", "missed while muted")]
        records.extend(
            AssistantRecord(b"fingerprint", body) for body in delivered
        )

        with self.assertRaisesRegex(AlignmentError, "101124 occurrence pairs"):
            align_delivered_sequence(records, delivered)

    async def test_an_ambiguous_restore_skips_history_but_not_new_speech(self):
        posted = []
        running = True

        async def collect(sender, sender_type, body):
            posted.append((sender_type, body))

        with tempfile.TemporaryDirectory() as directory:
            transcript = Path(directory) / "chat_history.jsonl"
            transcript.write_text(
                '{"type":"assistant","content":"Idle."}\n'
                '{"type":"assistant","content":"working"}\n'
                '{"type":"assistant","content":"Idle."}\n'
                '{"type":"assistant","content":"working"}\n',
                encoding="utf-8",
            )
            adapter = make_adapter(
                resume=True,
                session_id=SESSION_ID,
                collector=collect,
                delivered_bodies=["Idle.", "working"],
            )
            adapter.POLL_SECONDS = 0.005
            adapter.SETTLE_SECONDS = 0.02
            adapter.alive = lambda: running

            with patch.object(adapter, "_transcript", return_value=transcript):
                task = asyncio.create_task(adapter._run())
                for _ in range(300):
                    if posted:
                        break
                    await asyncio.sleep(0.01)
                with transcript.open("a", encoding="utf-8") as file:
                    file.write('{"type":"assistant","content":"Idle."}\n')
                for _ in range(300):
                    if ("agent", "Idle.") in posted:
                        break
                    await asyncio.sleep(0.01)
                running = False
                await asyncio.wait_for(task, timeout=3)

        self.assertEqual([body for kind, body in posted if kind == "agent"], ["Idle."])
        self.assertIn("skipped restored history", posted[0][1])

    async def test_an_undelivered_flush_waits_for_a_real_wake(self):
        """Counting transcript speech must never mean Partyline delivered it."""
        posted = []
        running = True

        async def collect(sender, sender_type, body):
            posted.append((sender_type, body))

        with tempfile.TemporaryDirectory() as directory:
            transcript = Path(directory) / "chat_history.jsonl"
            transcript.write_text(
                '{"type":"assistant","content":"missed while muted"}\n'
                + self.history(0, 2),
                encoding="utf-8",
            )
            adapter = make_adapter(
                resume=True,
                session_id=SESSION_ID,
                collector=collect,
                delivered_bodies=["old reply 0", "old reply 1"],
            )
            adapter.POLL_SECONDS = 0.005
            adapter.SETTLE_SECONDS = 0.02
            adapter.alive = lambda: running
            adapter._silent_until_wake = True

            with patch.object(adapter, "_transcript", return_value=transcript):
                task = asyncio.create_task(adapter._run())
                await asyncio.sleep(0.1)
                self.assertEqual(posted, [], "suppressed output was counted as delivered")
                adapter._silent_until_wake = False  # the mention delivery boundary
                for _ in range(300):
                    if posted:
                        break
                    await asyncio.sleep(0.01)
                running = False
                await asyncio.wait_for(task, timeout=3)

        self.assertEqual(
            [entry for entry in posted if entry[0] == "agent"],
            [("agent", "missed while muted")],
        )
        self.assertEqual(posted[0][0], "system")  # the notice precedes the flush

    async def test_a_same_inode_rewrite_cannot_use_an_old_delivery_plan(self):
        with tempfile.TemporaryDirectory() as directory:
            transcript = Path(directory) / "chat_history.jsonl"
            transcript.write_text(self.history(0, 2), encoding="utf-8")
            adapter = make_adapter(
                resume=True,
                session_id=SESSION_ID,
                delivered_bodies=["old reply 0", "old reply 1"],
            )
            adapter.POLL_SECONDS = 0.005
            adapter.SETTLE_SECONDS = 0.02
            adapter.alive = lambda: True
            self.assertTrue(await adapter._align_delivery_history(transcript))

            # Same path and inode, same-or-larger size, different records.
            transcript.write_text(
                '{"type":"assistant","content":"rewritten one"}\n'
                '{"type":"assistant","content":"rewritten two"}\n',
                encoding="utf-8",
            )
            with transcript.open() as file:
                self.assertFalse(delivery_plan_matches(adapter, file))

    async def test_an_empty_replacement_during_resume_does_not_replay_history(self):
        posted = []
        running = True

        async def collect(sender, sender_type, body):
            posted.append(body)

        with tempfile.TemporaryDirectory() as directory:
            transcript = Path(directory) / "chat_history.jsonl"
            transcript.write_text(self.history(0, 3), encoding="utf-8")
            adapter = make_adapter(resume=True, session_id=SESSION_ID, collector=collect)
            adapter.POLL_SECONDS = 0.005
            adapter.SETTLE_SECONDS = 0.02
            adapter.alive = lambda: running

            # Exactly what a resume does: pre-spawn count of the old file...
            with patch.object(adapter, "_transcript", return_value=transcript):
                with patch.object(Adapter, "start", new=AsyncMock()):
                    await adapter.start()
                self.assertEqual(adapter._accounted, 3)

                task = asyncio.create_task(adapter._run())
                await asyncio.sleep(0.05)
                # ...then the CLI swaps in an empty file and refills it.
                empty = Path(directory) / "empty.jsonl"
                empty.write_text("", encoding="utf-8")
                empty.replace(transcript)
                await asyncio.sleep(0.05)
                transcript.write_text(self.history(0, 3), encoding="utf-8")
                await asyncio.sleep(0.2)
                # New speech after the restore must still arrive.
                with transcript.open("a", encoding="utf-8") as file:
                    file.write('{"type":"assistant","content":"live again"}\n')
                for _ in range(200):
                    if "live again" in posted:
                        break
                    await asyncio.sleep(0.01)
                running = False
                await asyncio.wait_for(task, timeout=3)

        replayed = [body for body in posted if body.startswith("old reply")]
        self.assertEqual(replayed, [], "the restored history was relayed as new speech")
        self.assertIn("live again", posted)


    async def test_a_partly_refilled_replacement_does_not_replay_history(self):
        """Found by @sol: a pause mid-restore looks like a finished short file.

        Restoration writes one old record, pauses long enough to satisfy any
        settle window, then continues. Overlap between the old history's
        suffix and that partial prefix is empty, so a compaction reading
        zeroes the watermark and the refill replays. "Settled briefly" cannot
        prove "restore complete" — only the lifecycle can.
        """
        posted = []
        running = True

        async def collect(sender, sender_type, body):
            posted.append(body)

        with tempfile.TemporaryDirectory() as directory:
            transcript = Path(directory) / "chat_history.jsonl"
            transcript.write_text(self.history(0, 3), encoding="utf-8")
            adapter = make_adapter(resume=True, session_id=SESSION_ID, collector=collect)
            adapter.POLL_SECONDS = 0.005
            adapter.SETTLE_SECONDS = 0.02
            adapter.alive = lambda: running

            with patch.object(adapter, "_transcript", return_value=transcript):
                with patch.object(Adapter, "start", new=AsyncMock()):
                    await adapter.start()
                self.assertEqual(adapter._accounted, 3)
                task = asyncio.create_task(adapter._run())
                await asyncio.sleep(0.05)
                # The replacement arrives holding only the first old record,
                # and rests there long past any settle window.
                partial = Path(directory) / "partial.jsonl"
                partial.write_text(self.history(0, 1), encoding="utf-8")
                partial.replace(transcript)
                await asyncio.sleep(0.2)
                transcript.write_text(self.history(0, 3), encoding="utf-8")
                await asyncio.sleep(0.1)
                with transcript.open("a", encoding="utf-8") as file:
                    file.write('{"type":"assistant","content":"live again"}\n')
                for _ in range(300):
                    if "live again" in posted:
                        break
                    await asyncio.sleep(0.01)
                running = False
                await asyncio.wait_for(task, timeout=3)

        self.assertEqual([body for body in posted if body.startswith("old reply")], [])
        self.assertIn("live again", posted)


    async def test_without_a_pre_spawn_count_a_later_replacement_is_a_compaction(self):
        """The inverse control, from @sol: the flag must record, not assume.

        With no transcript before the spawn, ``_run`` counts the already
        restored file. The next replacement is then an ordinary compaction, so
        overlap must decide the watermark — a flag left true by "resume" alone
        would carry a stale ordinal and mute the process instead.
        """
        posted = []
        running = True

        async def collect(sender, sender_type, body):
            posted.append(body)

        with tempfile.TemporaryDirectory() as directory:
            transcript = Path(directory) / "chat_history.jsonl"
            adapter = make_adapter(resume=True, session_id=SESSION_ID, collector=collect)
            adapter.POLL_SECONDS = 0.005
            adapter.SETTLE_SECONDS = 0.02
            adapter.alive = lambda: running

            # No transcript before the spawn: nothing to carry across.
            with patch.object(adapter, "_transcript", return_value=None):
                with patch.object(Adapter, "start", new=AsyncMock()):
                    await adapter.start()
            self.assertIsNone(adapter._accounted)
            self.assertFalse(adapter._resume_swap_pending)

            transcript.write_text(self.history(0, 3), encoding="utf-8")
            with patch.object(adapter, "_transcript", return_value=transcript):
                task = asyncio.create_task(adapter._run())
                await asyncio.sleep(0.15)
                self.assertEqual(adapter._accounted, 3)
                # A real compaction: the tail is dropped, newer speech kept.
                compacted = Path(directory) / "compacted.jsonl"
                compacted.write_text(
                    self.history(2, 1) + '{"type":"assistant","content":"after compaction"}\n',
                    encoding="utf-8",
                )
                compacted.replace(transcript)
                for _ in range(300):
                    if "after compaction" in posted:
                        break
                    await asyncio.sleep(0.01)
                running = False
                await asyncio.wait_for(task, timeout=3)

        self.assertIn("after compaction", posted)
        self.assertEqual([body for body in posted if body.startswith("old reply")], [])


    async def test_a_stale_watermark_recovers_instead_of_muting_forever(self):
        """Live failure, 2026-08-18: refusing to replay became refusing to speak.

        A re-anchor was refused — correctly, the transcript was moving — and
        the file then settled *shorter* than the held ordinal. Nothing could
        ever clear the watermark again, so the process stayed alive, kept its
        cursor current, and was silent for hours while its terminal showed the
        replies it was producing. A guard that trades replay for permanent
        silence has swapped one invisible failure for another.
        """
        posted = []
        running = True

        async def collect(sender, sender_type, body):
            posted.append(body)

        with tempfile.TemporaryDirectory() as directory:
            transcript = Path(directory) / "chat_history.jsonl"
            transcript.write_text(self.history(0, 2), encoding="utf-8")
            adapter = make_adapter(resume=True, session_id=SESSION_ID, collector=collect)
            adapter.POLL_SECONDS = 0.005
            adapter.SETTLE_SECONDS = 0.02
            adapter.alive = lambda: running
            # A watermark inherited from a longer file that has since compacted.
            adapter._accounted = 9
            adapter._assistant_fingerprints = [b"x"] * 9

            task = asyncio.create_task(adapter._tail_grok_transcript(transcript, self.relay(posted)))
            await asyncio.sleep(0.15)
            with transcript.open("a", encoding="utf-8") as file:
                file.write('{"type":"assistant","content":"after the mute"}\n')
            for _ in range(400):
                if "after the mute" in posted:
                    break
                await asyncio.sleep(0.01)
            running = False
            await asyncio.wait_for(task, timeout=3)

        self.assertIn("after the mute", posted, "the process stayed muted")

    def relay(self, posted):
        async def handle(record):
            posted.append(record["content"])

        return handle


    async def test_a_compaction_after_a_completed_restore_is_not_treated_as_the_swap(self):
        """@sol's inverse control: the swap is consumed once, not held open.

        A resume replaces the transcript, the refill completes, and Grok is
        then compacted *before* saying anything new. If the resume flag were
        still set, that compaction would carry a stale ordinal and mute the
        process — the same silence, one lifecycle later.
        """
        posted = []
        running = True

        with tempfile.TemporaryDirectory() as directory:
            transcript = Path(directory) / "chat_history.jsonl"
            transcript.write_text(self.history(0, 3), encoding="utf-8")
            adapter = make_adapter(resume=True, session_id=SESSION_ID)
            adapter.POLL_SECONDS = 0.005
            adapter.SETTLE_SECONDS = 0.02
            adapter.alive = lambda: running

            with patch.object(adapter, "_transcript", return_value=transcript):
                with patch.object(Adapter, "start", new=AsyncMock()):
                    await adapter.start()
                task = asyncio.create_task(
                    adapter._tail_grok_transcript(transcript, self.relay(posted))
                )
                await asyncio.sleep(0.05)
                # The resume swap: same history, new file, refilled at once.
                swap = Path(directory) / "swap.jsonl"
                swap.write_text(self.history(0, 3), encoding="utf-8")
                swap.replace(transcript)
                await asyncio.sleep(0.15)
                self.assertIsNone(adapter._restoring_to, "the refill never registered")

                # A real compaction, before any new speech: keeps the tail.
                compacted = Path(directory) / "compacted.jsonl"
                compacted.write_text(
                    self.history(2, 1) + '{"type":"assistant","content":"after compaction"}\n',
                    encoding="utf-8",
                )
                compacted.replace(transcript)
                for _ in range(400):
                    if "after compaction" in posted:
                        break
                    await asyncio.sleep(0.01)
                running = False
                await asyncio.wait_for(task, timeout=3)

        self.assertIn("after compaction", posted, "muted by a stale resume flag")
        self.assertEqual([body for body in posted if body.startswith("old reply")], [])


class LifecycleTest(unittest.IsolatedAsyncioTestCase):
    async def test_start_refuses_resume_without_a_session_before_spawning(self):
        adapter = make_adapter(resume=True)
        with self.assertRaisesRegex(ValueError, "stored session UUID"):
            await adapter.start()

    async def test_start_counts_assistant_records_before_spawning_a_resume(self):
        adapter = make_adapter(resume=True, session_id=SESSION_ID)
        transcript = Path("/tmp/grok-transcript.jsonl")
        with (
            patch.object(adapter, "_transcript", return_value=transcript),
            patch.object(adapter, "_assistant_scan", return_value=[b"a", b"b", b"c"]),
            patch.object(Adapter, "start", new=AsyncMock()),
        ):
            await adapter.start()

        self.assertEqual(adapter._accounted, 3)
        self.assertEqual(adapter._assistant_fingerprints, [b"a", b"b", b"c"])

    async def test_start_installs_session_filtered_hooks_then_cleans_them_up(self):
        with tempfile.TemporaryDirectory() as tmp:
            att_hooks = {
                "grok_hooks_dir": str(Path(tmp) / "hooks"),
                "grok_hooks_paths": str(Path(tmp) / "hooks-paths"),
            }
            adapter = make_adapter()
            adapter.att["hook_url"] = "http://127.0.0.1:9/api/hooks/a/tok"
            adapter.att.update(att_hooks)
            with patch.object(Adapter, "start", new=AsyncMock()):
                await adapter.start()
            path = turn_hooks.hook_file(SESSION_ID, adapter.att)
            self.assertTrue(path.is_file())
            self.assertNotIn("SubagentStop", json.loads(path.read_text())["hooks"])
            await adapter.stop()
            self.assertFalse(path.exists())

    def test_assistant_count_skips_invalid_and_non_assistant_records(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "chat_history.jsonl"
            path.write_text(
                '{"type":"assistant","content":"one"}\n'
                'not json\n[]\n{"type":"reasoning"}\n'
                '{"type":"assistant","content":"two"}\n',
                encoding="utf-8",
            )
            self.assertEqual(PartylineAdapter._assistant_count(path), 2)

    def test_assistant_count_refuses_an_unreadable_file(self):
        with patch.object(Path, "open", side_effect=OSError):
            self.assertIsNone(PartylineAdapter._assistant_count(Path("/unreadable")))

    async def test_run_refuses_when_the_resume_history_cannot_be_counted(self):
        posted = []

        async def collect(sender, sender_type, body):
            posted.append((sender, sender_type, body))

        adapter = make_adapter(resume=True, session_id=SESSION_ID, collector=collect)
        path = Path("/tmp/grok-transcript.jsonl")
        adapter.alive = lambda: True
        with (
            patch.object(adapter, "_transcript", return_value=path),
            patch.object(adapter, "_assistant_scan", return_value=None),
        ):
            await adapter._run()

        self.assertIn("could not be counted", posted[0][2])
        self.assertFalse(await adapter.wait_ready())

    async def test_run_reports_a_missing_transcript_after_timeout(self):
        posted = []

        async def collect(sender, sender_type, body):
            posted.append((sender, sender_type, body))

        adapter = make_adapter(collector=collect)
        adapter.TRANSCRIPT_TIMEOUT = 0
        adapter.alive = lambda: True
        with patch.object(adapter, "_transcript", return_value=None):
            await adapter._run()

        self.assertIn("no Grok transcript appeared", posted[0][2])

    async def test_run_waits_for_a_transcript_then_tails_and_records_session(self):
        sessions = []
        path = Path("/tmp/grok-transcript.jsonl")
        adapter = make_adapter()
        adapter.on_cli_session = sessions.append
        adapter.alive = lambda: True
        tail = AsyncMock()
        with (
            patch.object(adapter, "_transcript", side_effect=[None, path]),
            patch("partyline.adapters.bundled.grok.adapter.asyncio.sleep", new=AsyncMock()),
            patch.object(adapter, "_tail_grok_transcript", new=tail),
        ):
            await adapter._run()

        self.assertEqual(sessions, [SESSION_ID])
        tail.assert_awaited_once()

    async def test_tail_skips_malformed_and_non_assistant_records(self):
        posted = []
        running = True

        async def handle(record):
            posted.append(record["content"])

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "chat_history.jsonl"
            path.write_text(
                'not json\n{"type":"reasoning"}\n'
                '{"type":"assistant","content":"survived"}\n', encoding="utf-8",
            )
            adapter = make_adapter()
            adapter.alive = lambda: running

            async def stop_after_post(record):
                nonlocal running
                await handle(record)
                running = False

            await adapter._tail_grok_transcript(path, stop_after_post)

        self.assertEqual(posted, ["survived"])

    async def test_speech_beside_tool_calls_is_relayed_and_counted(self):
        """A tool-using record with text is speech; an empty one still counts."""
        posted = []
        running = True
        adapter = make_adapter()
        adapter.alive = lambda: running

        async def handle(record):
            nonlocal running
            body = adapter._assistant_text(record)
            if body is not None:
                posted.append(body)
            if record["content"] == "second reply":
                running = False

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "chat_history.jsonl"
            path.write_text(
                json.dumps({
                    "type": "assistant", "content": "working note",
                    "tool_calls": [{"id": "x"}],
                }) + "\n" + json.dumps({
                    "type": "assistant", "content": "",
                    "tool_calls": [{"id": "y"}],
                }) + "\n" + json.dumps({"type": "assistant", "content": "first reply"}) + "\n"
                + json.dumps({"type": "assistant", "content": "second reply"}) + "\n",
                encoding="utf-8",
            )
            await adapter._tail_grok_transcript(path, handle)

        self.assertEqual(posted, ["working note", "first reply", "second reply"])
        self.assertEqual(adapter._accounted, 4)

    async def test_tail_leaves_a_half_written_record_unposted(self):
        running = True
        adapter = make_adapter()
        adapter.alive = lambda: running
        adapter._accounted = 0

        async def stop_sleep():
            nonlocal running
            running = False

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "chat_history.jsonl"
            path.write_text('{"type":"assistant"', encoding="utf-8")
            with patch.object(adapter, "_poll", stop_sleep):
                await adapter._tail_grok_transcript(path, AsyncMock())

    async def test_tail_retries_after_an_open_error(self):
        running = True
        adapter = make_adapter()
        adapter.alive = lambda: running

        async def stop_sleep():
            nonlocal running
            running = False

        with patch.object(Path, "open", side_effect=OSError), \
                patch.object(adapter, "_poll", stop_sleep):
            await adapter._tail_grok_transcript(Path("/unreadable"), AsyncMock())

    def test_replaced_treats_a_stat_error_as_replacement(self):
        fake_file = MagicMock()
        with patch.object(Path, "stat", side_effect=OSError):
            self.assertTrue(PartylineAdapter._replaced(fake_file, Path("/gone")))
