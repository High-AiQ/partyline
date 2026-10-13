"""Advisory sampling state is deterministic under fake usage and time."""

import tempfile
from pathlib import Path
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from partyline.db import Db
from partyline.memory_sampler import (
    _warn, crosses_warning, read_usage, process_tree_rss, reclaim_scope, run,
    warning_limit, warning_text,
)
from partyline.runtime import ChatRuntime


class MemorySamplerTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.db = Db(f"{self.temp.name}/partyline.db")
        self.addCleanup(self.db.close)
        self.db.create_conversation("line", "Line")
        self.db.add_attachment("worker", "line", "worker", "fake", ["fake"], self.temp.name)
        self.db._exec("UPDATE attachments SET status='running',memory_limit='1G' WHERE id='worker'")
        self.runtime = SimpleNamespace(db=self.db, live={"worker": object()}, memory_usage={})
        self.runtime.broadcast = AsyncMock()

    def test_threshold_and_cross_platform_tree_rss(self):
        self.assertTrue(crosses_warning(800, 1000, 80))
        self.assertFalse(crosses_warning(799, 1000, 80))
        completed = SimpleNamespace(returncode=0, stdout="10 1 100\n11 10 200\n20 1 500\n")
        with patch("subprocess.run", return_value=completed):
            self.assertEqual(process_tree_rss(10, "darwin"), 300 * 1024)

    def test_warning_text_uses_a_ceiling_bounded_request_and_human_units(self):
        with patch("partyline.memory_warning.memory_ceiling", return_value=6 * 1024**3):
            text = warning_text({"id": "worker", "name": "worker"},
                                3_600_000_000, 4 * 1024**3)
        self.assertIn("3.4 GiB of its 4.0 GiB per-process memory budget (83%)", text)
        self.assertIn("approval restarts the process", text)
        self.assertIn('/api/attachments/worker/memory-requests', text)
        self.assertIn('"requested_limit":"6G"', text)

    def test_own_warning_says_what_the_host_does_at_the_cap(self):
        row = {"id": "worker", "name": "worker"}
        cases = {"linux": "emergency backstop the kernel kills this process",
                 "win32": "allocations past it fail",
                 "darwin": "cannot enforce the budget on resident memory"}
        for platform, phrase in cases.items():
            with self.subTest(platform), \
                    patch("partyline.memory_warning.sys.platform", platform):
                text = warning_text(row, 9, 10, own=True)
            self.assertIn(phrase, text)
            self.assertIn("Commit or save your work now", text)

    async def test_self_warning_really_rings_the_warned_process(self):
        self.db._exec("UPDATE attachments SET is_lead=1 WHERE id='worker'")
        runtime = ChatRuntime(self.db)
        runtime.live["worker"] = SimpleNamespace(att=self.db.get_attachment("worker"))
        runtime.deliver_pending = AsyncMock(return_value=True)
        row = {"id": "worker", "name": "worker", "conv_id": "line"}
        await _warn(runtime, row, 3 * 1024**3, 4 * 1024**3)
        rung = [call.args[1]["id"] for call in runtime.deliver_pending.await_args_list]
        self.assertEqual(rung, ["worker"])

    def test_host_clamp_changes_linux_warning_limit_and_both_warning_copies(self):
        gib = 1024**3
        row = {'id': 'worker', 'name': 'worker'}
        with patch('partyline.server_memory.host_memory_bytes', return_value=8 * gib):
            for platform in ('linux', 'win32', 'darwin'):
                with self.subTest(platform=platform), \
                        patch('partyline.memory_sampler.sys.platform', platform), \
                        patch('partyline.memory_warning.sys.platform', platform):
                    self.assertEqual(warning_limit(8 * gib), (6 if platform == 'linux' else 8) * gib)
                    self.assertEqual(warning_limit(4 * gib), 4 * gib)
            with patch('partyline.memory_sampler.sys.platform', 'linux'):
                for budget in (6 * gib, 8 * gib):
                    for own in (True, False):
                        text = warning_text(row, 5 * gib, budget, own=own)
                        self.assertIn('6.0 GiB emergency backstop is at or below', text)
                        self.assertIn('Warnings use the backstop', text)
                        self.assertNotIn('nothing stops you there', text)

    async def test_cache_heavy_usage_reclaims_then_stays_silent(self):
        """File cache over the threshold with a healthy working set: the
        sampler reclaims the difference and posts no "decide now" notice."""
        import tempfile as tempfile_module

        scope = Path(tempfile_module.mkdtemp())
        sample_one = {"root": str(scope), "current": 900 * 1024**2,
                      "peak": None, "working_set": 100 * 1024**2}
        sample_two = {"root": str(scope), "current": 850 * 1024**2,
                      "peak": None, "working_set": 90 * 1024**2}
        runtime = ChatRuntime(self.db)
        runtime.live["worker"] = SimpleNamespace(proc=SimpleNamespace(pid=123))
        runtime.deliver_pending = AsyncMock(return_value=True)

        class StopSampling(Exception):
            pass

        async def tick(_seconds):
            raise StopSampling

        with patch("partyline.memory_sampler.sys.platform", "linux"), \
                patch("partyline.memory_sampler.cgroup_usage",
                      side_effect=[sample_one, sample_two]) as cgroup, \
                patch("partyline.memory_sampler.asyncio.sleep", tick):
            with self.assertRaises(StopSampling):
                await run(runtime, sampler=read_usage)
        reclaim = scope / "memory.reclaim"
        self.assertTrue(reclaim.exists())
        self.assertEqual(int(reclaim.read_text()), 800 * 1024**2)
        self.assertEqual(cgroup.call_count, 2)  # the re-read happened
        self.assertEqual([], self.db.list_messages("line"))
        self.assertEqual(runtime.memory_usage["worker"]["raw_bytes"],
                         850 * 1024**2)

    async def test_anon_heavy_usage_warns_on_the_working_set(self):
        gib = 1024**3
        runtime = ChatRuntime(self.db)
        runtime.live["worker"] = SimpleNamespace(
            att=self.db.get_attachment("worker"), proc=SimpleNamespace(pid=123))
        runtime.deliver_pending = AsyncMock(return_value=True)
        sample = {"root": str(Path(self.temp.name, "scope")),
                  "current": 980 * 1024**2, "peak": None,
                  "working_set": 960 * 1024**2}  # all anonymous: reclaim is futile

        class StopSampling(Exception):
            pass

        async def tick(_seconds):
            raise StopSampling

        with patch("partyline.memory_sampler.sys.platform", "linux"), \
                patch("partyline.server_memory.host_memory_bytes",
                      return_value=8 * gib), \
                patch("partyline.memory_sampler.cgroup_usage",
                      return_value=sample), \
                patch("partyline.memory_sampler.asyncio.sleep", tick):
            with self.assertRaises(StopSampling):
                await run(runtime, sampler=read_usage)
        runtime.deliver_pending.assert_awaited_once()
        text = self.db.list_messages("line")[-1]["body"]
        self.assertIn("memory budget (93%)", text)
        self.assertEqual(runtime.memory_usage["worker"]["raw_bytes"],
                         980 * 1024**2)

    async def test_a_failed_reclaim_falls_back_to_the_working_set_decision(self):
        gib = 1024**3
        runtime = ChatRuntime(self.db)
        runtime.live["worker"] = SimpleNamespace(
            att=self.db.get_attachment("worker"), proc=SimpleNamespace(pid=123))
        runtime.deliver_pending = AsyncMock(return_value=True)
        # A root that cannot hold a memory.reclaim file at all.
        sample = {"root": str(Path(self.temp.name, "gone", "scope")),
                  "current": 980 * 1024**2, "peak": None,
                  "working_set": 960 * 1024**2}

        class StopSampling(Exception):
            pass

        async def tick(_seconds):
            raise StopSampling

        with patch("partyline.memory_sampler.sys.platform", "linux"), \
                patch("partyline.server_memory.host_memory_bytes",
                      return_value=8 * gib), \
                patch("partyline.memory_sampler.cgroup_usage",
                      return_value=sample), \
                patch("partyline.memory_sampler.asyncio.sleep", tick):
            with self.assertRaises(StopSampling):
                await run(runtime, sampler=read_usage)  # must not raise
        runtime.deliver_pending.assert_awaited_once()  # warns on working set
        self.assertEqual([], [m for m in self.db.list_messages("line")
                              if "Raw" in m["body"]])

    async def test_reclaim_backs_off_and_runs_off_the_event_loop(self):
        """Two ticks with the same cache-heavy sample: one reclaim attempt
        (60 s backoff), executed through asyncio.to_thread, and no warning."""
        import asyncio as aio
        import tempfile as tempfile_module

        scope = Path(tempfile_module.mkdtemp())
        sample = {"root": str(scope), "current": 900 * 1024**2,
                  "peak": None, "working_set": 100 * 1024**2}
        runtime = ChatRuntime(self.db)
        runtime.live["worker"] = SimpleNamespace(
            att=self.db.get_attachment("worker"), proc=SimpleNamespace(pid=123))
        runtime.deliver_pending = AsyncMock(return_value=True)

        calls = {"ticks": 0}

        class StopSampling(Exception):
            pass

        async def tick(_seconds):
            calls["ticks"] += 1
            if calls["ticks"] >= 2:
                raise StopSampling

        real_to_thread = aio.to_thread
        to_thread_calls = []

        async def spy_to_thread(fn, *args, **kwargs):
            to_thread_calls.append(fn)
            return await real_to_thread(fn, *args, **kwargs)

        with patch("partyline.memory_sampler.sys.platform", "linux"), \
                patch("partyline.memory_sampler.cgroup_usage",
                      return_value=sample) as cgroup, \
                patch("partyline.memory_sampler.reclaim_scope",
                      wraps=reclaim_scope) as reclaim, \
                patch("partyline.memory_sampler.asyncio.to_thread",
                      side_effect=spy_to_thread), \
                patch("partyline.memory_sampler.asyncio.sleep", tick):
            with self.assertRaises(StopSampling):
                await run(runtime, sampler=read_usage)

        self.assertEqual(calls["ticks"], 2)
        self.assertEqual(reclaim.call_count, 1)  # backoff: one attempt
        # Both the reclaim write and the re-read ran off the event loop.
        self.assertIn(reclaim, to_thread_calls)
        self.assertIn(cgroup, to_thread_calls)
        self.assertTrue((scope / "memory.reclaim").exists())
        self.assertEqual([], self.db.list_messages("line"))

    async def test_oversized_budget_warns_and_routes_before_the_backstop(self):
        gib = 1024**3
        self.db._exec("UPDATE attachments SET memory_limit='8G',is_lead=1 WHERE id='worker'")
        runtime = ChatRuntime(self.db)
        runtime.live['worker'] = SimpleNamespace(att=self.db.get_attachment('worker'))
        runtime.deliver_pending = AsyncMock(return_value=True)
        usage = 6 * gib * 80 // 100 + 1

        class StopSampling(Exception):
            pass

        async def tick(_seconds):
            raise StopSampling

        with patch('partyline.server_memory.host_memory_bytes', return_value=8 * gib), \
                patch('partyline.memory_sampler.sys.platform', 'linux'), \
                patch('partyline.memory_sampler.asyncio.sleep', tick):
            with self.assertRaises(StopSampling):
                await run(runtime, sampler=lambda _: (usage, None, 'fake'))
        self.assertLess(usage, 6 * gib)
        runtime.deliver_pending.assert_awaited_once()
        text = self.db.list_messages('line')[-1]['body']
        self.assertIn('8.0 GiB per-process memory budget (60%)', text)
        self.assertIn('6.0 GiB emergency backstop is at or below', text)
        self.assertEqual(runtime.memory_usage['worker']['cap_bytes'], 8 * gib)

    async def test_warning_is_private_to_the_line_captain_and_people_can_read_it(self):
        worker = {"id": "worker", "name": "worker", "conv_id": "line"}
        self.db.add_attachment("captain", "line", "captain", "fake", ["fake"], self.temp.name)
        self.db._exec("UPDATE attachments SET is_lead=1,status='running' WHERE id='captain'")
        runtime = ChatRuntime(self.db)
        runtime.live["captain"] = SimpleNamespace(att=self.db.get_attachment("captain"))
        with patch("partyline.memory_sampler.post_private", new_callable=AsyncMock) as private:
            await _warn(runtime, worker, 3 * 1024**3, 4 * 1024**3)
        audiences = [call.kwargs["audience"] for call in private.await_args_list]
        self.assertEqual(audiences, ["worker", "captain"])
        self.assertIn("you are using", private.await_args_list[0].args[4])
        self.assertIn("worker is using", private.await_args_list[1].args[4])
        self.assertIn("As its captain, decide now", private.await_args_list[1].args[4])

    async def test_root_captain_warning_rings_the_captain_itself(self):
        self.db._exec("UPDATE attachments SET is_lead=1,status='running' WHERE id='worker'")
        self.db._exec("UPDATE attachments SET is_lead=0 WHERE id='captain'")
        runtime = ChatRuntime(self.db)
        runtime.live["worker"] = SimpleNamespace(att=self.db.get_attachment("worker"))
        row = {"id": "worker", "name": "captain", "conv_id": "line"}
        with patch("partyline.memory_sampler.post_private", new_callable=AsyncMock) as private:
            await _warn(runtime, row, 3 * 1024**3, 4 * 1024**3)
        self.assertEqual([call.kwargs["audience"] for call in private.await_args_list], ["worker"])
        self.assertEqual(private.await_args.args[1], "line")

    async def test_captain_warning_rings_itself_and_the_parent_captain(self):
        self.db.create_conversation("parent", "Parent")
        self.db._exec("UPDATE conversations SET parent_id='parent' WHERE id='line'")
        self.db.add_attachment("parent-captain", "parent", "boss", "fake", ["fake"], self.temp.name)
        self.db._exec("UPDATE attachments SET status='running',is_lead=1 WHERE id='parent-captain'")
        self.db._exec("UPDATE attachments SET is_lead=1 WHERE id='worker'")
        self.db._exec("UPDATE attachments SET is_lead=0 WHERE id='captain'")
        runtime = ChatRuntime(self.db)
        runtime.live["worker"] = SimpleNamespace(att=self.db.get_attachment("worker"))
        runtime.live["parent-captain"] = SimpleNamespace(att=self.db.get_attachment("parent-captain"))
        row = {"id": "worker", "name": "captain", "conv_id": "line"}
        with patch("partyline.memory_sampler.post_private", new_callable=AsyncMock) as private:
            await _warn(runtime, row, 3 * 1024**3, 4 * 1024**3)
        calls = [(call.args[1], call.kwargs["audience"]) for call in private.await_args_list]
        self.assertEqual(calls, [("line", "worker"), ("parent", "parent-captain")])

    async def test_sampler_continues_after_bad_tick_and_prunes_stopped_usage(self):
        values = iter([RuntimeError("sample failed"), (800 * 1024**2, None, "fake")])
        sleeps = 0

        def sample(_adapter):
            value = next(values)
            if isinstance(value, Exception):
                raise value
            return value

        async def tick(_seconds):
            nonlocal sleeps
            sleeps += 1
            if sleeps == 2:
                self.db._exec("UPDATE attachments SET status='stopped' WHERE id='worker'")
            elif sleeps == 3:
                raise StopSampling

        class StopSampling(Exception):
            pass

        self.runtime.memory_usage["stale"] = {"usage_bytes": 1}
        with patch("partyline.memory_sampler.asyncio.sleep", tick):
            try:
                await run(self.runtime, sampler=sample)
            except StopSampling:
                pass
        self.assertNotIn("stale", self.runtime.memory_usage)
        self.assertNotIn("worker", self.runtime.memory_usage)

    async def test_every_tick_offers_the_resource_snapshot_to_the_pusher(self):
        class StopSampling(Exception):
            pass

        async def stop_after_tick(_seconds):
            raise StopSampling

        with patch("partyline.memory_sampler.ResourcePusher.tick", new_callable=AsyncMock) as push, \
                patch("partyline.memory_sampler.asyncio.sleep", stop_after_tick):
            with self.assertRaises(StopSampling):
                await run(self.runtime, sampler=lambda _adapter: (1, None, "fake"))
        push.assert_awaited_once_with(self.runtime)

    async def test_real_rss_sampler_takes_one_snapshot_for_the_whole_tick(self):
        from partyline.memory_sampler import read_usage

        self.runtime.live["worker"] = SimpleNamespace(proc=SimpleNamespace(pid=123))
        table = ({123: 1}, {123: 500 * 1024**2})

        class StopSampling(Exception):
            pass

        async def stop_after_tick(_seconds):
            raise StopSampling

        with patch("partyline.memory_sampler.sys.platform", "darwin"), \
                patch("partyline.memory_sampler.process_snapshot", return_value=table) as snapshot, \
                patch("partyline.memory_sampler.cgroup_usage", return_value=None), \
                patch("partyline.memory_sampler.asyncio.sleep", stop_after_tick):
            with self.assertRaises(StopSampling):
                await run(self.runtime, sampler=read_usage)
        snapshot.assert_called_once_with()

    async def test_linux_cgroup_samples_skip_process_snapshot_when_all_rows_succeed(self):
        from partyline.memory_sampler import read_usage

        self.db.add_attachment("worker2", "line", "worker2", "fake", ["fake"], self.temp.name)
        self.db._exec("UPDATE attachments SET status='running',memory_limit='1G' WHERE id='worker2'")
        self.runtime.live["worker"] = SimpleNamespace(proc=SimpleNamespace(pid=123))
        self.runtime.live["worker2"] = SimpleNamespace(proc=SimpleNamespace(pid=456))

        class StopSampling(Exception):
            pass

        async def stop_after_tick(_seconds):
            raise StopSampling

        with patch("partyline.memory_sampler.sys.platform", "linux"), \
                patch("partyline.memory_sampler.cgroup_usage",
                      side_effect=[{"root": "/sys/fs/cgroup/fake",
                                    "current": 500 * 1024**2,
                                    "peak": 600 * 1024**2,
                                    "working_set": 500 * 1024**2},
                                   {"root": "/sys/fs/cgroup/fake",
                                    "current": 550 * 1024**2,
                                    "peak": 650 * 1024**2,
                                    "working_set": 550 * 1024**2}]) as cgroup, \
                patch("partyline.memory_sampler.process_snapshot") as snapshot, \
                patch("partyline.memory_sampler.asyncio.sleep", stop_after_tick):
            with self.assertRaises(StopSampling):
                await run(self.runtime, sampler=read_usage)
        self.assertEqual(cgroup.call_count, 2)
        snapshot.assert_not_called()
        self.assertEqual(self.runtime.memory_usage["worker"]["source"], "cgroup")
        self.assertEqual(self.runtime.memory_usage["worker2"]["source"], "cgroup")

    async def test_going_over_the_soft_cap_is_told_once_despite_the_cooldown(self):
        # 1G cap: warn at 81%, then over the cap a minute later, then stay over.
        values = iter([0.81, 1.05, 1.10, 1.20])
        notices = AsyncMock()

        def sample(_adapter):
            return int(next(values) * 1024**3), None, "fake"

        class StopSampling(Exception):
            pass

        ticks = []

        async def tick(_seconds):
            ticks.append(_seconds)
            if len(ticks) == 4:
                raise StopSampling

        with patch("partyline.memory_sampler._warn", notices), \
                patch("partyline.memory_sampler.asyncio.sleep", tick):
            with self.assertRaises(StopSampling):
                await run(self.runtime, clock=lambda: 60, sampler=sample)
        self.assertEqual(notices.await_count, 2)
        self.assertGreater(notices.await_args_list[1].args[2], 1024**3)

    async def test_a_new_activation_is_warned_again(self):
        """Sol's repro: over budget, stopped, resumed over budget — two warnings."""
        notices = AsyncMock()
        first, second = object(), object()
        steps = iter([("running", first), ("exited", None), ("running", second)])

        def sample(_adapter):
            return int(1.05 * 1024**3), None, "fake"

        class StopSampling(Exception):
            pass

        def advance():
            try:
                status, adapter = next(steps)
            except StopIteration:
                raise StopSampling from None
            self.db._exec("UPDATE attachments SET status=? WHERE id='worker'", (status,))
            self.runtime.live = {"worker": adapter} if adapter else {}
            if not adapter:
                self.runtime.memory_usage.pop("worker", None)  # as exit handling does

        async def tick(_seconds):
            advance()

        advance()
        with patch("partyline.memory_sampler._warn", notices), \
                patch("partyline.memory_sampler.asyncio.sleep", tick):
            with self.assertRaises(StopSampling):
                await run(self.runtime, clock=lambda: 60, sampler=sample)
        self.assertEqual(notices.await_count, 2)

    async def test_a_replaced_adapter_between_ticks_is_warned_again(self):
        notices = AsyncMock()
        adapters = iter([object(), object()])

        def sample(_adapter):
            return int(1.05 * 1024**3), None, "fake"

        class StopSampling(Exception):
            pass

        async def tick(_seconds):
            try:
                self.runtime.live = {"worker": next(adapters)}
            except StopIteration:
                raise StopSampling from None

        with patch("partyline.memory_sampler._warn", notices), \
                patch("partyline.memory_sampler.asyncio.sleep", tick):
            with self.assertRaises(StopSampling):
                await run(self.runtime, clock=lambda: 60, sampler=sample)
        # Three samples over budget across three activations: one warning each.
        self.assertEqual(notices.await_count, 3)

    async def test_hysteresis_and_one_notice_per_ten_minute_window(self):
        values = [0.81, 0.90, 0.60, 0.81, 0.81, 0.60, 0.81]
        times = iter([0, 60, 120, 180, 600, 660, 720])
        notices = AsyncMock()
        state = {"index": 0, "now": 0}

        def sample(_adapter):
            return int(values[state["index"]] * 1024**3), None, "fake"

        async def tick(_seconds):
            state["index"] += 1
            try:
                state["now"] = next(times)
            except StopIteration:
                raise StopSampling from None
            if state["index"] >= len(values):
                raise StopSampling

        class StopSampling(Exception):
            pass

        with patch("partyline.memory_sampler._warn", notices), \
                patch("partyline.memory_sampler.asyncio.sleep", tick):
            try:
                await run(self.runtime, clock=lambda: state["now"], sampler=sample)
            except StopSampling:
                pass
        self.assertEqual(notices.await_count, 2, (state, notices.await_args_list))
        self.assertEqual(self.runtime.memory_usage["worker"]["source"], "fake")
