"""OpenCode v2 fixtures mirror its session_v2/session_message store."""

import asyncio
import errno
import json
import sqlite3
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch, Mock

from tests.adapter_event_clock import install as event_clock

from partyline.adapters.bundled.opencode.v2 import RECHECK_SECONDS, PartylineAdapter
from partyline.adapters.receipts import BEGAN, ENDED


class OpenCodeV2Tests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = Path(self.tmp.name) / "opencode.db"
        self.db = sqlite3.connect(self.store)
        self.addCleanup(self.db.close)
        self.db.executescript("""
            CREATE TABLE session_v2(id TEXT, directory TEXT, parent_id TEXT);
            CREATE TABLE session_message(id TEXT, session_id TEXT, type TEXT,
                                         seq INTEGER, time_created INTEGER, data TEXT);
            INSERT INTO session_v2 VALUES('ours', '/project', NULL);
            INSERT INTO session_v2 VALUES('other', '/project', NULL);
            INSERT INTO session_v2 VALUES('child', '/project', 'ours');
        """)
        self.post = AsyncMock()
        self.adapter = self.make()
        PartylineAdapter._CLAIMED.clear()
        self.addCleanup(PartylineAdapter._CLAIMED.clear)

    def make(self, **extra):
        att = dict(id="a", name="agent", conv_id="line", conv="room", cwd="/project",
                   command=[], adapter_metadata={"capabilities": {"transcript": True}})
        att.update(extra)
        adapter = PartylineAdapter(att, self.post, AsyncMock())
        event_clock(adapter)
        adapter._store = self.store
        adapter.spawned_at = 1
        self.addCleanup(adapter._close_store)
        return event_clock(adapter)

    def row(self, ident, kind, data, seq=1, session="ours", created=1000):
        self.db.execute("INSERT INTO session_message VALUES(?,?,?,?,?,?)",
                        (ident, session, kind, seq, created, json.dumps(data)))
        self.db.commit()

    def claim(self):
        self.row("claim", "user", {"text": self.adapter._claim_token})
        self.adapter._session_id = self.adapter._find_session()

    def test_command_is_interactive_private_and_claimed(self):
        command = self.adapter.build_command()
        self.assertEqual(command[:4], ["opencode2", "--standalone", "--auto", "--prompt"])
        self.assertIn(self.adapter._claim_token, command[-1])
        resumed = self.make(resume=True, cli_session="ours")
        self.assertIn("--session", resumed.build_command())
        self.assertIn("READY", resumed.build_command()[-1])
        for args in (["--server", "remote"], ["--server=remote"], ["--standalone=false"],
                     ["--no-standalone"], ["--prompt=x"], ["--prompt", "x"]):
            with self.assertRaises(ValueError):
                self.make(command=["opencode2", *args]).build_command()
        with self.assertRaises(ValueError):
            self.make(command=["opencode2", "-s", "x"], resume=True,
                      cli_session="ours").build_command()
        command = self.make(command=["custom", "--standalone"]).build_command()
        self.assertEqual(command.count("--standalone"), 1)

    def test_store_path_comes_from_selected_binary(self):
        with patch("partyline.adapters.bundled.opencode.v2.subprocess.run") as run:
            run.return_value.stdout = str(self.store) + "\n"
            self.assertEqual(self.adapter._resolve_store(), self.store)
            self.assertEqual(run.call_args.args[0], ["opencode2", "debug", "paths", "db"])
            run.return_value.stdout = ":memory:"
            with self.assertRaises(ValueError):
                self.adapter._resolve_store()

    def test_v2_database_is_separate_unless_explicitly_overridden(self):
        with patch.dict("os.environ", {}, clear=True):
            self.assertEqual(self.adapter.spawn_env(), {"OPENCODE_DB": "opencode-v2.db"})
        with patch.dict("os.environ", {"OPENCODE_DB": "/custom/session.db"}):
            self.assertEqual(self.adapter.spawn_env(), {"OPENCODE_DB": "/custom/session.db"})

    def test_claim_rejects_neighbors_old_markers_and_children(self):
        self.row("neighbor", "user", {"text": "another marker"}, session="other")
        self.row("old", "user", {"text": self.adapter._claim_token}, created=999)
        self.row("child", "user", {"text": self.adapter._claim_token}, session="child")
        self.row("fake", "user", {"metadata": self.adapter._claim_token})
        self.assertIsNone(self.adapter._find_session())
        self.claim()
        self.assertEqual(self.adapter._session_id, "ours")
        self.assertTrue(self.adapter._claim_proven)
        PartylineAdapter._CLAIMED[(str(self.store), "ours")] = "other-owner"
        self.assertIsNone(self.adapter._find_session())
        self.assertIsNone(self.make()._find_session())

    def test_resume_cannot_claim_a_different_session(self):
        self.adapter.resume = True
        self.adapter.att["cli_session"] = "other"
        self.claim()
        self.assertIsNone(self.adapter._session_id)

    async def test_completed_speech_only_and_idle_closes_turn_once(self):
        self.row("history", "assistant", {"time": {"completed": 1}, "content": [
            {"type": "text", "text": "old"}]}, seq=0)
        self.claim()
        self.row("stream", "assistant", {"time": {}, "content": [{"type": "text", "text": "partial"}]}, seq=2)
        self.row("summary", "compaction", {"summary": "private summary"}, seq=3)
        self.row("answer", "assistant", {"time": {"completed": 1500}, "content": [
            {"type": "reasoning", "text": "private"}, {"type": "tool", "text": "tool output"},
            {"type": "text", "text": "answer"}, {}, None, {"type": "text", "text": 3}]}, seq=4)
        self.row("steer", "user", {"text": "follow-up"}, seq=5)
        self.row("idle", "idle", {"outcome": "interrupted"}, seq=6)
        with patch("partyline.adapters.bundled.opencode.v2.receipt", new_callable=AsyncMock) as receipt:
            await self.adapter._poll()
            await self.adapter._poll()
        self.assertEqual([c.args[1] for c in receipt.call_args_list], [BEGAN, ENDED])
        self.post.assert_awaited_once_with("agent", "agent", "answer")
        self.assertTrue(self.adapter._ready_result)
        self.db.execute("UPDATE session_message SET data=? WHERE id='stream'", (json.dumps({
            "time": {"completed": 1600}, "content": [{"type": "text", "text": "finished"}]}),))
        self.db.commit()
        await self.adapter._poll()
        self.assertEqual(self.post.call_args.args[-1], "finished")

    async def test_a_turn_a_background_job_started_is_a_turn(self):
        """A subagent or background command finishing prompts the model with no user row.

        The process then read as idle while it worked (no badge, on 2026-11-12), and its
        turn never ended for the return path.
        """
        self.claim()
        self.row("idle-1", "idle", {"outcome": "succeeded"}, seq=2)
        with patch("partyline.adapters.bundled.opencode.v2.receipt", new_callable=AsyncMock) as receipt:
            await self.adapter._poll()
            self.assertEqual([c.args[1] for c in receipt.call_args_list], [BEGAN, ENDED])
            self.row("wake", "synthetic", {"metadata": {"source": "subagent"}, "text": "done"}, seq=3)
            self.row("step", "assistant", {"time": {}, "content": []}, seq=4)
            await self.adapter._poll()
            self.assertEqual([c.args[1] for c in receipt.call_args_list], [BEGAN, ENDED, BEGAN])
            self.db.execute("UPDATE session_message SET data=? WHERE id='step'", (json.dumps({
                "time": {"completed": 9}, "content": [{"type": "text", "text": "reviewed"}]}),))
            self.row("idle-2", "idle", {"outcome": "succeeded"}, seq=5)
            await self.adapter._poll()
        self.assertEqual([c.args[1] for c in receipt.call_args_list], [BEGAN, ENDED, BEGAN, ENDED])
        self.post.assert_awaited_once_with("agent", "agent", "reviewed")

    async def test_a_settled_rows_body_is_never_read_again(self):
        """Every read used to fetch every row since the claim, megabytes of them."""
        self.claim()
        for seq in range(2, 6):
            self.row(f"done-{seq}", "assistant", {"time": {"completed": 1}, "content": [
                {"type": "text", "text": f"answer {seq}"}]}, seq=seq)
        self.row("stream", "assistant", {"time": {}, "content": []}, seq=6)
        fetched = []
        reader = self.adapter._connect()

        class Spy:
            def execute(self, sql, args=()):
                if "SELECT id, type, data" in sql:
                    fetched.append(sorted(arg for arg in args if arg != "ours"))
                return reader.execute(sql, args)

        self.adapter._connect = Spy
        self.assertTrue(await self.adapter._poll())
        self.assertEqual(fetched, [sorted(["claim", "done-2", "done-3", "done-4", "done-5", "stream"])])
        self.assertFalse(await self.adapter._poll())  # nothing was committed: one pragma, no listing
        self.assertEqual(len(fetched), 1)
        self.row("elsewhere", "assistant", {"time": {"completed": 1}, "content": []}, session="other")
        self.assertTrue(await self.adapter._poll())
        self.assertEqual(fetched[1:], [["stream"]])  # only the row still being written
        self.assertEqual(self.post.await_count, 4)
        self.assertEqual(set(self.adapter._row_versions), {"stream"})

    @unittest.skipUnless(sys.platform == "linux", "native inotify close events")
    async def test_reading_the_store_does_not_wake_its_own_watcher(self):
        """A connection per read closed -wal and -shm each time, and that close is an event.

        Every read caused the next (2,885 reads a second in review of #497): the watcher
        never waited and held a full core whether or not the process was doing anything.
        """
        from partyline.file_events import FileEvents

        self.db.execute("PRAGMA journal_mode=WAL")  # the writer keeps -wal and -shm alive
        self.claim()

        async def notified():
            for _ in range(5):
                await asyncio.sleep(0)  # let queued native notifications reach the loop
            return self.adapter._changes.version - self.adapter._other_wakes

        async with FileEvents(self.store, changes=self.adapter._changes):
            self.assertTrue(await self.adapter._poll())
            quiet = await notified()
            for _ in range(20):
                self.assertFalse(await self.adapter._poll())
                self.adapter._find_session()
            self.assertEqual(await notified(), quiet)  # forty reads, not one file notification
            self.row("idle", "idle", {"outcome": "succeeded"}, seq=2)
            self.assertGreater(await notified(), quiet)  # a real commit is still announced
            self.assertTrue(await self.adapter._poll())
        self.adapter._close_store()
        self.assertIsNone(self.adapter._reader)

    async def run_with_backend(self, backend):
        """Run the real watcher loop over a claimed store, returning (stop calls, posts)."""
        from partyline.adapters.events import AdapterEvents

        self.claim()
        adapter = self.adapter
        adapter._resolve_store = Mock(return_value=self.store)
        adapter.file_events = lambda *paths, **kw: AdapterEvents.file_events(
            adapter, *paths, backend=backend, **kw)
        wakes = iter(range(6))
        adapter.alive = lambda: next(wakes, None) is not None
        adapter.stop = AsyncMock()
        with patch("partyline.attachment_stop_audit.direct_stop") as direct_stop:
            await adapter._run()
            await asyncio.sleep(0)  # let the one report task post
        return adapter.stop.await_count + direct_stop.call_count

    async def test_running_out_of_descriptors_keeps_the_process_attached_and_retries(self):
        from tests.test_watch_exhaustion import Backend

        backend = Backend(creation=[OSError(errno.EMFILE, "Too many open files")])
        self.assertEqual(await self.run_with_backend(backend), 0)
        self.assertEqual(len(backend.made), 1)  # the next wake re-created the watch
        notices = [c.args[2] for c in self.post.await_args_list if c.args[0] == "system"]
        self.assertEqual(len(notices), 1)
        self.assertIn("file descriptors", notices[0])

    async def test_any_other_watch_failure_still_stops_the_process(self):
        from tests.test_watch_exhaustion import Backend

        backend = Backend(creation=[PermissionError(errno.EACCES, "denied")])
        self.assertEqual(await self.run_with_backend(backend), 2)
        failure = [c.args[2] for c in self.post.await_args_list if "monitoring failed" in c.args[2]]
        self.assertEqual(len(failure), 1)

    async def watch(self, wakes, polls, backend=None):
        """Drive the watcher loop with named wakes; return the delays it asked to wait."""
        self.claim()
        self.adapter._resolve_store = Mock(return_value=self.store)
        if backend is not None:
            from partyline.adapters.events import AdapterEvents

            self.adapter.file_events = lambda *paths, **kw: AdapterEvents.file_events(
                self.adapter, *paths, backend=backend, **kw)
        self.adapter._poll = AsyncMock(side_effect=polls)
        self.adapter._after_poll = Mock()
        wakes, delays, alive, now = iter(wakes), [], True, 0.0

        async def wait(timeout=None):
            nonlocal alive, now
            delays.append(timeout)
            kind = next(wakes)
            now += timeout if kind == "deadline" else 0.001
            if kind == "file":
                self.adapter._changes.notify()
            elif kind != "deadline":
                alive = kind != "exit"
                self.adapter.changed()

        self.adapter.wait_for_change = wait
        self.adapter.event_time = lambda: now
        self.adapter.alive = lambda: alive
        await self.adapter._run()
        return delays

    async def test_terminal_output_wakes_the_watcher_without_reading_the_store(self):
        delays = await self.watch(["deadline", "output", "output", "file", "output", "exit"],
                                  [True, False, True])
        # The first read and its one later look, then the file event: no read per redraw.
        self.assertEqual(self.adapter._poll.await_count, 3)
        self.assertEqual(self.adapter._after_poll.call_count, 3)  # a redraw still runs deadlines
        self.assertAlmostEqual(delays[0], RECHECK_SECONDS)
        self.assertEqual(delays[1:4], [None, None, None])

    async def test_a_watch_that_comes_back_reads_what_was_written_while_it_was_down(self):
        """A turn end written while the watch was starved would otherwise wait for the next
        write to the store: the wake that restores the watch is terminal output, which
        alone never reads (integration review of #500)."""
        from tests.test_watch_exhaustion import Backend

        # Refused on entry and again when the claim wakes the watcher, so the first read
        # happens with the watch still down.
        backend = Backend(creation=[OSError(errno.EMFILE, "Too many open files")] * 2)
        await self.watch(["output", "output", "exit"], [True, True, True], backend)
        self.assertEqual(len(backend.made), 1)  # the first output re-created the watch
        self.assertEqual(self.adapter._poll.await_count, 2)  # the first read, then the catch-up

    async def test_a_notification_that_shows_nothing_new_gets_one_later_look(self):
        """The notification can arrive before the commit it announces is visible."""
        delays = await self.watch(["file", "output", "deadline", "output", "exit"],
                                  [True, False, False])
        self.assertEqual(self.adapter._poll.await_count, 3)  # first read, the event, one later look
        self.assertAlmostEqual(delays[0], RECHECK_SECONDS)  # the first read is owed one too
        self.assertAlmostEqual(delays[1], RECHECK_SECONDS)
        self.assertLess(delays[2], RECHECK_SECONDS)  # output does not push the deadline back
        # The later look found nothing either and arms nothing: no 50 ms poll.
        self.assertEqual(delays[3:], [None, None])

    async def test_a_read_that_found_a_commit_still_gets_its_later_look(self):
        """Two commits back to back: the read sees the answer and not yet the idle row.

        Nothing else would look again, and the turn would show as working until the next
        write to the store (review of #497, 97 of 100 turn ends under full sync).
        """
        delays = await self.watch(["file", "deadline", "output", "exit"], [True, True, True])
        self.assertEqual(self.adapter._poll.await_count, 3)
        self.assertAlmostEqual(delays[1], RECHECK_SECONDS)
        self.assertEqual(delays[2:], [None, None])

    async def test_a_store_that_fails_at_the_later_look_is_not_retried_in_a_loop(self):
        """The deadline stayed armed after an error: 31,000 failing reads a second in review."""
        delays = await self.watch(["file", "deadline", "output", "exit"],
                                  [True, False, sqlite3.OperationalError("disk I/O error")])
        self.assertEqual(self.adapter._poll.await_count, 3)
        self.assertAlmostEqual(delays[1], RECHECK_SECONDS)
        self.assertEqual(delays[2:], [None, None])  # retried on the next wake, not at once

    async def test_stopping_during_a_read_closes_the_store_only_after_the_read(self):
        """Cancelling the watcher does not stop its worker thread.

        The connection was closed on the loop thread while a read was still running on it
        in a worker, which crashed the interpreter (review of #497).
        """
        self.claim()
        real, order = self.adapter._connect(), []
        started, release = threading.Event(), threading.Event()

        class Reader:
            def execute(self, sql, args=()):
                if "PRAGMA" in sql:
                    order.append("read began")
                    started.set()
                    release.wait(5)
                return real.execute(sql, args)

            def close(self):
                order.append("closed")
                real.close()

        self.adapter._reader = Reader()
        reading = asyncio.create_task(self.adapter._poll())
        await asyncio.to_thread(started.wait, 5)
        held = not self.adapter._store_lock.acquire(blocking=False)
        if not held:
            self.adapter._store_lock.release()  # fail below instead of blocking the cleanup
        self.assertTrue(held, "a read must hold the store lock, so a close has to wait for it")
        closing = threading.Thread(target=self.adapter._close_store)
        closing.start()
        order.append("read released")
        release.set()
        await reading
        await asyncio.to_thread(closing.join, 5)
        self.assertEqual(order, ["read began", "read released", "closed"])
        with self.assertRaises(sqlite3.ProgrammingError):  # a read queued behind the stop
            self.adapter._unsettled_rows()
        self.assertIsNone(self.adapter._reader)

    async def test_a_compaction_first_seen_while_it_runs_is_counted_when_it_completes(self):
        """Settled on first sight, a running compaction was never counted (review of #497)."""
        self.claim()
        noted = AsyncMock()
        self.adapter.att["on_compaction"] = noted
        self.row("compact", "compaction", {"status": "running", "reason": "auto"}, seq=2)
        await self.adapter._poll()
        noted.assert_not_awaited()
        self.db.execute("UPDATE session_message SET data=? WHERE id='compact'",
                        (json.dumps({"status": "completed", "reason": "auto"}),))
        self.db.commit()
        await self.adapter._poll()
        await self.adapter._poll()
        noted.assert_awaited_once_with("auto")

    async def test_speech_gate_and_malformed_data(self):
        self.adapter._session_id = "ours"
        for i, data in enumerate((None, [], {}, {"time": None}, {"time": {"completed": 1}, "content": 5})):
            self.row(str(i), "assistant", data, seq=i)
        self.row("speech", "assistant", {"time": {"completed": 1}, "content": [
            {"type": "text", "text": "unclaimed"}]}, seq=7)
        await self.adapter._poll()
        self.post.assert_not_awaited()
        self.assertEqual(self.adapter._decode("bad json"), {})

    async def test_wake_receipt_requires_recorded_user_marker(self):
        self.claim()
        await self.adapter._poll()
        confirm = AsyncMock(return_value=True)
        self.adapter.att["confirm_delivery_ids"] = confirm
        self.adapter._wake_receipts = [{"digest": "message", "marker": "paste-marker",
                                       "ids": [42], "proven": False}]
        self.row("wake", "user", {"text": "message paste-marker"}, seq=2)
        await self.adapter._poll()
        confirm.assert_awaited_once_with([42])
        self.assertEqual(self.adapter._confirmed_delivery_ids, {42})

    # Shape copied from a real opencode-v2 session store (2026-10-11): every
    # observed compaction row is status=completed, reason=auto; the summary
    # and recent fields are redacted here.
    COMPACTION = {
        "time": {"created": 1790484322896},
        "status": "completed",
        "reason": "auto",
        "model": {"id": "space-bunny-free", "providerID": "opencode", "variant": "xhigh"},
        "summary": "<redacted>",
        "recent": "<redacted>",
        "cost": 0,
        "tokens": {"input": 561, "output": 1717, "reasoning": 0,
                   "cache": {"read": 472469, "write": 0}},
    }

    async def test_a_compaction_row_calls_the_callback_once_even_when_reread(self):
        from unittest.mock import AsyncMock

        noted = AsyncMock()
        self.adapter.att["on_compaction"] = noted
        self.claim()
        self.row("compact", "compaction", dict(self.COMPACTION), seq=2)

        await self.adapter._poll()
        await self.adapter._poll()  # the same row read again must not count twice

        noted.assert_awaited_once_with("auto")
        self.post.assert_not_awaited()  # the summary is not speech

    async def test_an_unfinished_compaction_row_and_a_manual_reason(self):
        from unittest.mock import AsyncMock

        noted = AsyncMock()
        self.adapter.att["on_compaction"] = noted
        self.claim()
        self.row("running", "compaction", {**self.COMPACTION, "status": "running"}, seq=2)
        await self.adapter._poll()
        noted.assert_not_awaited()  # only completed compactions count

        self.row("manual", "compaction", {**self.COMPACTION, "reason": "manual"}, seq=3)
        await self.adapter._poll()
        noted.assert_awaited_once_with("manual")

    async def test_a_row_without_the_capability_callback_is_harmless(self):
        self.claim()
        self.row("compact", "compaction", dict(self.COMPACTION), seq=2)
        await self.adapter._poll()  # no on_compaction bound: nothing raised
        self.post.assert_not_awaited()

    async def test_run_claims_and_polls_then_stop_releases(self):
        self.claim()
        self.adapter._resolve_store = Mock(return_value=self.store)
        self.adapter.alive = Mock(side_effect=[True, True, False])
        self.adapter.on_cli_session = Mock()
        with patch("partyline.adapters.bundled.opencode.v2.asyncio.sleep", new_callable=AsyncMock):
            await self.adapter._run()
        self.adapter.on_cli_session.assert_called_once_with("ours")
        self.assertNotIn((str(self.store), "ours"), PartylineAdapter._CLAIMED)
        with patch("partyline.adapters.base.Adapter.stop", new_callable=AsyncMock):
            await self.adapter.stop()
        self.assertNotIn((str(self.store), "ours"), PartylineAdapter._CLAIMED)

    async def test_run_handles_missing_store_timeout_and_exit(self):
        self.adapter._resolve_store = Mock(return_value=self.store)
        self.adapter.alive = Mock(return_value=True)
        self.adapter._find_session = Mock(side_effect=sqlite3.OperationalError("busy"))
        with patch("partyline.adapters.bundled.opencode.v2.asyncio.sleep", new_callable=AsyncMock):
            await self.adapter._run()
        self.assertIn("45s", self.post.call_args.args[-1])
        self.adapter.alive = Mock(return_value=False)
        await self.adapter._run()

    async def test_poll_failure_is_retried(self):
        self.claim()
        self.adapter._resolve_store = Mock(return_value=self.store)
        self.adapter.alive = Mock(side_effect=[True, True, False])
        self.adapter._poll = AsyncMock(side_effect=sqlite3.OperationalError("busy"))
        with patch("partyline.adapters.bundled.opencode.v2.asyncio.sleep", new_callable=AsyncMock):
            await self.adapter._run()
        self.adapter._poll.assert_awaited_once()

    async def test_natural_exit_releases_session_for_a_new_resume_claim(self):
        self.claim()
        self.adapter._resolve_store = Mock(return_value=self.store)
        self.adapter.alive = Mock(side_effect=[True, False])
        await self.adapter._run()
        resumed = self.make(resume=True, cli_session="ours")
        self.row("resume", "user", {"text": resumed._claim_token}, seq=20)
        self.assertEqual(resumed._find_session(), "ours")
        self.assertEqual(resumed._claim_seq, 20)

    async def test_late_cleanup_cannot_release_another_activation_claim(self):
        self.adapter._session_id = "ours"
        key = (str(self.store), "ours")
        PartylineAdapter._CLAIMED[key] = "new-activation"
        with patch("partyline.adapters.base.Adapter.stop", new_callable=AsyncMock):
            await self.adapter.stop()
        self.assertEqual(PartylineAdapter._CLAIMED[key], "new-activation")

    async def test_watcher_can_stop_itself_without_cancelling_status_cleanup(self):
        self.adapter._resolve_store = Mock(side_effect=OSError("missing store"))
        task = asyncio.create_task(self.adapter._run())
        self.adapter._tasks = [task]
        with self.assertLogs("partyline.attachment_stop_audit", level="INFO") as logs:
            await task
        self.assertIn("source=opencode.transcript_watcher_failure", logs.output[0])
        self.adapter.on_status.assert_awaited_once_with("detached")
        self.assertFalse(task.cancelled())

    async def test_prefilled_prompt_gets_one_enter_but_screen_never_proves_claim(self):
        self.adapter._resolve_store = Mock(return_value=self.store)
        self.adapter.alive = Mock(return_value=True)
        self.adapter.screen_text = Mock(return_value=self.adapter._claim_token)
        self.adapter._write_all = AsyncMock()
        with patch("partyline.adapters.bundled.opencode.v2.asyncio.sleep", new_callable=AsyncMock):
            await self.adapter._run()
        self.adapter._write_all.assert_awaited_once_with(b"\r")
        self.assertFalse(self.adapter._claim_proven)
        self.assertFalse(self.adapter._ready_result)
        self.assertTrue(all(call.args[1] == "system" for call in self.post.call_args_list))

    async def test_compaction_rewrite_does_not_replay_speech_or_adopt_sibling(self):
        self.claim()
        answer = {"time": {"completed": 1500}, "content": [{"type": "text", "text": "answer"}]}
        self.row("answer", "assistant", answer, seq=2)
        await self.adapter._poll()
        self.db.execute("DELETE FROM session_message")
        self.db.commit()
        self.row("answer", "assistant", answer, seq=2)
        self.row("compact", "compaction", {"status": "completed", "summary": "private",
                                           "recent": "private"}, seq=3)
        self.row("sibling", "assistant", answer, seq=4, session="other")
        await self.adapter._poll()
        self.post.assert_awaited_once_with("agent", "agent", "answer")
