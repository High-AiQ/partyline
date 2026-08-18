"""Deterministic coverage for the bundled Grok Build adapter."""

import asyncio
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from partyline.adapters import Adapter
from partyline.adapters.bundled.grok.adapter import PartylineAdapter


SESSION_ID = "12345678-1234-4234-8234-123456789abc"


async def post(sender, sender_type, body):
    pass


async def status(value):
    pass


def make_adapter(*, command=None, resume=False, session_id=None, collector=post):
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
        self.assertIsNone(PartylineAdapter._assistant_text([]))
        self.assertIsNone(PartylineAdapter._assistant_text("bare string"))
        self.assertIsNone(PartylineAdapter._assistant_text(42))
        self.assertIsNone(PartylineAdapter._assistant_text(None))
        self.assertIsNone(PartylineAdapter._assistant_text({"type": "reasoning", "content": "secret"}))
        self.assertIsNone(PartylineAdapter._assistant_text({"type": "assistant", "content": []}))
        self.assertIsNone(PartylineAdapter._assistant_text({"type": "assistant", "content": 3}))
        self.assertIsNone(PartylineAdapter._assistant_text({
            "type": "assistant", "content": "I am about to work", "tool_calls": [{"id": "x"}],
        }))
        self.assertEqual(
            PartylineAdapter._assistant_text({
                "type": "assistant", "content": "finished reply", "tool_calls": [],
            }),
            "finished reply",
        )

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

            async def keep_growing():
                index = 0
                while writing:
                    with transcript.open("a", encoding="utf-8") as file:
                        file.write(f'{{"type":"assistant","content":"{index}"}}\n')
                    index += 1
                    await asyncio.sleep(0)

            writer = asyncio.create_task(keep_growing())
            with patch.object(adapter, "_transcript", return_value=transcript):
                await adapter._run()
            writing = False
            await writer

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

    async def test_narration_occupies_an_ordinal_even_when_not_relayed(self):
        """Resume position follows durable records, not relay policy."""
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
                    "type": "assistant", "content": "working note", "tool_calls": [{"id": "x"}],
                }) + "\n" + json.dumps({"type": "assistant", "content": "first reply"}) + "\n"
                + json.dumps({"type": "assistant", "content": "second reply"}) + "\n",
                encoding="utf-8",
            )
            await adapter._tail_grok_transcript(path, handle)

        self.assertEqual(posted, ["first reply", "second reply"])
        self.assertEqual(adapter._accounted, 3)

    async def test_tail_leaves_a_half_written_record_unposted(self):
        running = True
        adapter = make_adapter()
        adapter.alive = lambda: running
        adapter._accounted = 0

        async def stop_sleep(_):
            nonlocal running
            running = False

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "chat_history.jsonl"
            path.write_text('{"type":"assistant"', encoding="utf-8")
            with patch("partyline.adapters.bundled.grok.adapter.asyncio.sleep", stop_sleep):
                await adapter._tail_grok_transcript(path, AsyncMock())

    async def test_tail_retries_after_an_open_error(self):
        running = True
        adapter = make_adapter()
        adapter.alive = lambda: running

        async def stop_sleep(_):
            nonlocal running
            running = False

        with patch.object(Path, "open", side_effect=OSError), \
                patch("partyline.adapters.bundled.grok.adapter.asyncio.sleep", stop_sleep):
            await adapter._tail_grok_transcript(Path("/unreadable"), AsyncMock())

    def test_replaced_treats_a_stat_error_as_replacement(self):
        fake_file = MagicMock()
        with patch.object(Path, "stat", side_effect=OSError):
            self.assertTrue(PartylineAdapter._replaced(fake_file, Path("/gone")))
