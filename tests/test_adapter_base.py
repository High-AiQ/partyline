"""Coverage for the pty runtime every adapter inherits.

These tests spawn real pseudo-terminals, because the pty *is* the thing under
test — but only ever running `sh` and `cat`, never a real CLI. Nothing here
waits a fixed amount of time for something to happen: helpers poll for the
condition and fail on a deadline, so a slow machine is slow rather than flaky.
"""

import asyncio
import json
import os
import tempfile
import time
import unittest
from pathlib import Path

os.environ.setdefault("PARTYLINE_DB", "/tmp/partyline-test-adapter-base.db")

from partyline.adapters.base import Adapter
from partyline.adapters.terminal import terminal_responses
from datetime import UTC


async def until(predicate, timeout=10.0, what="condition"):
    """Poll until a predicate holds, or fail the test on the deadline."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        await asyncio.sleep(0.02)
    raise AssertionError(f"timed out after {timeout}s waiting for {what}")


class Recorder(Adapter):
    """Adapter that keeps everything it is handed, for assertions."""

    def __init__(self, command, **att):
        self.output = bytearray()
        self.statuses: list[str] = []
        self.posts: list[tuple] = []
        attachment = {
            "id": "att-1", "name": "dummy", "command": command, "cwd": "/tmp",
            "conv_name": "a line", "adapter_metadata": {},
        }
        attachment.update(att)
        super().__init__(attachment, self._post, self._status)

    async def _post(self, sender, sender_type, body):
        self.posts.append((sender, sender_type, body))

    async def _status(self, status):
        self.statuses.append(status)

    async def on_output(self, data):
        self.output.extend(data)

    def saw(self, text):
        return text.encode() in bytes(self.output)


class AdapterLifecycleTest(unittest.IsolatedAsyncioTestCase):
    async def test_wait_ready_completes_only_after_adapter_marks_ready(self):
        adapter = Recorder(["sh", "-c", "sleep 30"])
        await adapter.start()
        self.addAsyncCleanup(adapter.stop)

        waiting = asyncio.create_task(adapter.wait_ready())
        await asyncio.sleep(0)
        self.assertFalse(waiting.done())

        adapter.mark_ready()
        self.assertTrue(await waiting)

    async def test_wait_ready_returns_false_when_process_exits_first(self):
        adapter = Recorder(["sh", "-c", "exit 0"])
        await adapter.start()

        self.assertFalse(await adapter.wait_ready())

    async def test_startup_delivery_waits_for_structured_receipt(self):
        adapter = Recorder(["cat"], resume=True)
        waiter = asyncio.create_task(adapter.wait_startup_delivery_received())

        await asyncio.sleep(0)
        self.assertFalse(waiter.done())
        adapter.mark_startup_delivery_received()

        self.assertTrue(await waiter)

    async def test_stopping_releases_unconfirmed_startup_delivery(self):
        adapter = Recorder(["cat"], resume=True)

        await adapter.stop()

        self.assertFalse(await adapter.wait_startup_delivery_received())

    async def test_stopping_before_ready_releases_waiters_as_not_ready(self):
        adapter = Recorder(["sh", "-c", "sleep 30"])
        await adapter.start()
        waiting = asyncio.create_task(adapter.wait_ready())

        await adapter.stop()

        self.assertFalse(await waiting)

    async def test_start_reports_running_and_stop_reports_detached(self):
        adapter = Recorder(["sh", "-c", "sleep 30"])
        await adapter.start()
        self.assertEqual(adapter.statuses, ["running"])
        self.assertTrue(adapter.alive())
        pid = adapter.proc.pid

        await adapter.stop()

        self.assertEqual(adapter.statuses, ["running", "detached"])
        await until(lambda: not adapter.alive(), what="the process to die")
        with self.assertRaises(ProcessLookupError):
            os.kill(pid, 0)

    async def test_stop_is_quiet_when_the_process_is_already_gone(self):
        adapter = Recorder(["sh", "-c", "exit 0"])
        await adapter.start()
        await until(lambda: not adapter.alive(), what="the process to exit")

        await adapter.stop()  # must not raise on a pid that no longer exists

        self.assertEqual(adapter.statuses[-1], "detached")

    async def test_an_unprompted_exit_is_announced_with_its_code(self):
        adapter = Recorder(["sh", "-c", "exit 3"])
        await adapter.start()

        await until(lambda: adapter.posts, what="the exit notice")

        self.assertIn("exited", adapter.statuses)
        self.assertEqual(adapter.posts[0][:2], ("system", "system"))
        self.assertIn("@dummy exited (code 3)", adapter.posts[0][2])
        await adapter.stop()

    async def test_stopping_suppresses_the_exit_notice(self):
        """A detach is not a crash, and must not be reported as one."""
        adapter = Recorder(["sh", "-c", "sleep 30"])
        await adapter.start()

        await adapter.stop()
        await asyncio.sleep(0.3)  # give a stray notice time to appear

        self.assertEqual(adapter.posts, [])
        self.assertNotIn("exited", adapter.statuses)

    async def test_alive_is_false_before_anything_is_spawned(self):
        self.assertFalse(Recorder(["true"]).alive())


class AdapterEnvironmentTest(unittest.IsolatedAsyncioTestCase):
    async def test_env_unset_strips_names_and_wildcard_prefixes(self):
        os.environ["PARTYLINE_TEST_PLAIN"] = "plain"
        os.environ["PARTYLINE_TEST_WILD_ONE"] = "one"
        os.environ["PARTYLINE_TEST_KEPT"] = "kept"
        self.addCleanup(lambda: [os.environ.pop(key, None) for key in (
            "PARTYLINE_TEST_PLAIN", "PARTYLINE_TEST_WILD_ONE", "PARTYLINE_TEST_KEPT")])
        adapter = Recorder(
            ["sh", "-c", 'printf "[%s][%s][%s]" '
             '"$PARTYLINE_TEST_PLAIN" "$PARTYLINE_TEST_WILD_ONE" "$PARTYLINE_TEST_KEPT"'],
            adapter_metadata={"env_unset": ["PARTYLINE_TEST_PLAIN", "PARTYLINE_TEST_WILD_*"]},
        )

        await adapter.start()
        await until(lambda: adapter.saw("[]"), what="the child's environment")

        self.assertTrue(adapter.saw("[][][kept]"), bytes(adapter.output))
        await adapter.stop()

    async def test_build_command_does_not_alias_the_stored_argv(self):
        adapter = Recorder(["cat"])
        built = adapter.build_command()
        built.append("--extra")
        self.assertEqual(adapter.att["command"], ["cat"])


class AdapterKeystrokeTest(unittest.IsolatedAsyncioTestCase):
    async def test_send_keys_wraps_the_text_in_a_bracketed_paste(self):
        """Byte-exact, against a pipe: the tty echoes escapes back in its own
        rendering, so the echo cannot tell us what was actually written."""
        read_fd, write_fd = os.pipe()
        self.addCleanup(os.close, read_fd)
        adapter = Recorder(["cat"])
        adapter.master = write_fd

        await adapter.send_keys("hello line")
        os.close(write_fd)

        written = b""
        while chunk := os.read(read_fd, 4096):
            written += chunk
        # Bracketed paste, so a human mid-keystroke does not have their input
        # spliced into the middle of the delivered message. Enter comes after.
        self.assertEqual(written, b"\x1b[200~hello line\x1b[201~\r")

    async def test_pasted_text_reaches_the_process_and_renders_on_the_screen(self):
        adapter = Recorder(["cat"])
        await adapter.start()
        self.addCleanup(lambda: asyncio.run(_stop(adapter)))

        await adapter.send_keys("hello line")

        await until(lambda: adapter.saw("hello line"), what="the pasted text")
        await until(lambda: "hello line" in adapter.screen_text(), what="the rendered screen")

    async def test_send_key_writes_known_keys_and_rejects_the_rest(self):
        adapter = Recorder(["cat"])
        await adapter.start()
        self.addCleanup(lambda: asyncio.run(_stop(adapter)))

        adapter.send_key("y")
        await until(lambda: adapter.saw("y"), what="the keystroke to echo")

        with self.assertRaises(ValueError) as caught:
            adapter.send_key("f13")
        self.assertIn("unsupported key", str(caught.exception))

    async def test_screen_text_trims_the_blank_tail(self):
        adapter = Recorder(["cat"])
        await adapter.start()
        self.addCleanup(lambda: asyncio.run(_stop(adapter)))

        await adapter.send_keys("only line")
        await until(lambda: adapter.screen_text(), what="the screen to fill")

        # pyte's display is a fixed 40 rows; the tail of empty ones is dropped.
        self.assertFalse(adapter.screen_text().endswith("\n"))
        self.assertLess(len(adapter.screen_text().split("\n")), 40)


class TerminalQueryTest(unittest.TestCase):
    """A full-screen client must not block on split terminal queries."""

    def test_terminal_answers_are_an_explicit_adapter_capability(self):
        self.assertFalse(Recorder(["cat"]).answers_terminal_queries)

    def test_terminal_queries_receive_terminal_like_replies_across_chunks(self):
        adapter = Recorder(["cat"])
        adapter._term.cursor.x = 12
        adapter._term.cursor.y = 3
        replies, tail = terminal_responses(adapter._term, b"", b"before\x1b[6")
        self.assertEqual(replies, b"")
        self.assertEqual(tail, b"\x1b[6")

        replies, tail = terminal_responses(
            adapter._term, tail, b"n\x1b]10;?\x1b\\\x1b]11;?\x07\x1b[c\x1b[?u\x1b[?1004h")

        self.assertEqual(tail, b"")
        self.assertEqual(
            replies,
            b"\x1b[4;13R\x1b]10;rgb:0000/0000/0000\x1b\\"
            b"\x1b]11;rgb:ffff/ffff/ffff\x07\x1b[?62c",
        )


class TerminalQueryPtyTest(unittest.IsolatedAsyncioTestCase):
    async def test_opted_in_adapter_answers_a_real_pty_cursor_query(self):
        class QueryingRecorder(Recorder):
            answers_terminal_queries = True

        adapter = QueryingRecorder([
            "sh", "-c", "stty raw -echo; printf '\\033[6n'; "
            "dd bs=1 count=6 2>/dev/null | od -An -t x1",
        ])
        await adapter.start()
        await until(lambda: adapter.saw("1b 5b 31 3b 31 52"), what="the DSR reply")
        await adapter.stop()


async def _stop(adapter):
    await adapter.stop()


class DigestTest(unittest.IsolatedAsyncioTestCase):
    def test_a_digest_is_sender_prefixed_lines_plus_the_standing_reminder(self):
        adapter = Recorder(["cat"])
        digest = adapter.format_digest([
            {"sender": "greg", "body": "ship it"},
            {"sender": "luna", "body": "on it"},
        ])
        self.assertIn("[greg]: ship it\n[luna]: on it", digest)
        self.assertIn("processes only see messages that @mention them", digest)

    async def test_deliver_sends_nothing_when_there_is_nothing_to_say(self):
        sent = []

        class Silent(Recorder):
            async def send_keys(self, text):
                sent.append(text)

        adapter = Silent(["cat"])
        adapter.format_digest = lambda messages: "   "
        await adapter.deliver([])
        self.assertEqual(sent, [])

    async def test_deliver_sends_the_digest_when_there_is(self):
        sent = []

        class Silent(Recorder):
            async def send_keys(self, text):
                sent.append(text)

        adapter = Silent(["cat"])
        await adapter.deliver([{"sender": "greg", "body": "hi"}])
        self.assertEqual(len(sent), 1)
        self.assertIn("[greg]: hi", sent[0])


class ResumeSilenceTest(unittest.IsolatedAsyncioTestCase):
    """A process resumed after being killed mid-turn must not blurt out the
    tail of the turn nobody is waiting for."""

    async def test_a_fresh_process_posts_normally(self):
        adapter = Recorder(["cat"])
        await adapter.post("dummy", "agent", "hello everyone")
        self.assertEqual(adapter.posts, [("dummy", "agent", "hello everyone")])

    async def test_a_resumed_process_holds_back_its_interrupted_turn(self):
        adapter = Recorder(["cat"], resume=True)
        await adapter.post("dummy", "agent", "…as I was saying")

        self.assertEqual(len(adapter.posts), 1)
        sender, kind, body = adapter.posts[0]
        self.assertEqual((sender, kind), ("system", "system"))
        self.assertIn("resumed mid-turn", body)
        self.assertNotIn("as I was saying", body)

    async def test_the_explanation_is_posted_only_once(self):
        adapter = Recorder(["cat"], resume=True)
        for fragment in ("first", "second", "third"):
            await adapter.post("dummy", "agent", fragment)
        self.assertEqual(len(adapter.posts), 1)

    async def test_system_notices_are_never_held_back(self):
        """An exit or a failure is how a person learns something broke."""
        adapter = Recorder(["cat"], resume=True)
        await adapter.post("system", "system", "@dummy exited (code 1)")
        self.assertEqual(adapter.posts, [("system", "system", "@dummy exited (code 1)")])

    async def test_being_woken_ends_the_silence(self):
        sent = []

        class Silent(Recorder):
            async def send_keys(self, text):
                sent.append(text)

        adapter = Silent(["cat"], resume=True)
        await adapter.deliver([{"sender": "greg", "body": "you there?"}])
        await adapter.post("dummy", "agent", "yes — picking this back up")

        self.assertEqual(len(sent), 1)
        self.assertEqual(adapter.posts, [("dummy", "agent", "yes — picking this back up")])

    async def test_an_exiting_resumed_process_still_reports_its_code(self):
        """End to end through the real pty path, not just the wrapper."""
        adapter = Recorder(["sh", "-c", "exit 4"], resume=True)
        await adapter.start()
        await until(lambda: adapter.posts, what="the exit notice")
        self.assertIn("@dummy exited (code 4)", adapter.posts[0][2])
        await adapter.stop()


class BriefingTest(unittest.TestCase):
    def test_briefing_names_the_process_and_its_line(self):
        text = Recorder(["cat"]).briefing()
        self.assertIn('You are "dummy"', text)
        self.assertIn('conversation "a line"', text)
        self.assertNotIn("standing context", text)

    def test_a_topic_is_appended_as_standing_context(self):
        text = Recorder(["cat"], topic="  ship the archive feature  ").briefing()
        self.assertIn("standing context", text)
        self.assertIn("ship the archive feature", text)

    def test_a_blank_topic_is_left_out_entirely(self):
        self.assertNotIn("standing context", Recorder(["cat"], topic="   ").briefing())

    def test_a_line_with_no_name_falls_back_rather_than_raising(self):
        adapter = Recorder(["cat"])
        adapter.att.pop("conv_name")
        self.assertIn('conversation "?"', adapter.briefing())


class FreshnessTest(unittest.TestCase):
    """`_fresh` is what stops a resumed process replaying its whole history."""

    def test_everything_is_fresh_when_not_resuming(self):
        self.assertTrue(Recorder(["cat"])._fresh(None))

    def test_a_resumed_process_rejects_records_with_no_timestamp(self):
        self.assertFalse(Recorder(["cat"], resume=True)._fresh(None))

    def test_a_resumed_process_rejects_an_unparseable_timestamp(self):
        self.assertFalse(Recorder(["cat"], resume=True)._fresh("last tuesday"))

    def test_a_resumed_process_rejects_records_from_before_it_started(self):
        adapter = Recorder(["cat"], resume=True)
        adapter.spawned_at = time.time()
        from datetime import datetime
        old = datetime.fromtimestamp(adapter.spawned_at - 3600, UTC).isoformat()
        self.assertFalse(adapter._fresh(old))

    def test_a_resumed_process_accepts_records_from_after_it_started(self):
        adapter = Recorder(["cat"], resume=True)
        adapter.spawned_at = time.time()
        from datetime import datetime
        now = datetime.fromtimestamp(adapter.spawned_at + 1, UTC).isoformat()
        self.assertTrue(adapter._fresh(now))

    def test_a_trailing_z_is_understood_as_utc(self):
        adapter = Recorder(["cat"], resume=True)
        adapter.spawned_at = time.time()
        from datetime import datetime
        stamp = datetime.fromtimestamp(adapter.spawned_at + 1, UTC)
        self.assertTrue(adapter._fresh(stamp.isoformat().replace("+00:00", "Z")))


class TailJsonlTest(unittest.IsolatedAsyncioTestCase):
    """The transcript tail must survive everything a half-written file can be."""

    async def _tail(self, text, adapter=None):
        adapter = adapter or Recorder(["cat"])
        seen = []

        async def handle(record):
            seen.append(record)

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "transcript.jsonl"
            path.write_text(text, encoding="utf-8")
            await asyncio.wait_for(adapter._tail_jsonl(str(path), handle), timeout=10)
        return seen

    async def test_complete_records_are_handed_over_in_order(self):
        adapter = Recorder(["cat"])
        seen = await self._tail('{"n": 1}\n{"n": 2}\n', adapter)
        self.assertEqual(seen, [{"n": 1}, {"n": 2}])
        self.assertTrue(await adapter.wait_ready())

    async def test_a_corrupt_record_is_skipped_not_fatal(self):
        seen = await self._tail('{"n": 1}\nnot json at all\n{"n": 2}\n')
        self.assertEqual(seen, [{"n": 1}, {"n": 2}])

    async def test_valid_non_object_records_are_skipped_not_fatal(self):
        seen = await self._tail('[]\n"not a record"\n42\nnull\n{"n": 2}\n')
        self.assertEqual(seen, [{"n": 2}])

    async def test_a_half_written_final_record_is_never_delivered(self):
        # The tail returns rather than spinning on the fragment, because the
        # process that would have finished writing it is gone.
        seen = await self._tail('{"n": 1}\n{"n": 2, "unfinis')
        self.assertEqual(seen, [{"n": 1}])

    async def test_invalid_utf8_does_not_kill_the_tail(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "transcript.jsonl"
            path.write_bytes(b'{"n": "\xff\xfe"}\n{"n": 2}\n')
            seen = []

            async def handle(record):
                seen.append(record)

            await asyncio.wait_for(Recorder(["cat"])._tail_jsonl(str(path), handle), timeout=10)
        self.assertEqual(seen[-1], {"n": 2})

    async def test_the_tail_follows_a_file_that_is_still_being_written(self):
        adapter = Recorder(["sh", "-c", "sleep 30"])
        await adapter.start()
        self.addCleanup(lambda: asyncio.run(_stop(adapter)))
        seen = []

        async def handle(record):
            seen.append(record)

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "transcript.jsonl"
            path.write_text('{"n": 1}\n', encoding="utf-8")
            task = asyncio.create_task(adapter._tail_jsonl(str(path), handle))
            await until(lambda: seen, what="the first record")
            with path.open("a", encoding="utf-8") as file:
                file.write(json.dumps({"n": 2}) + "\n")
                file.flush()
            await until(lambda: len(seen) == 2, what="the appended record")
            task.cancel()

        self.assertEqual(seen, [{"n": 1}, {"n": 2}])


class DefaultHooksTest(unittest.IsolatedAsyncioTestCase):
    """The base class's no-op hooks exist so adapters can ignore what they want."""

    async def test_base_run_and_on_output_do_nothing_and_raise_nothing(self):
        adapter = Adapter({"id": "x", "name": "n", "command": ["cat"], "cwd": "/tmp"},
                          _noop_post, _noop_status)
        self.assertIsNone(await adapter._run())
        self.assertIsNone(await adapter.on_output(b"ignored"))


async def _noop_post(sender, sender_type, body):
    pass


async def _noop_status(status):
    pass


if __name__ == "__main__":
    unittest.main()
