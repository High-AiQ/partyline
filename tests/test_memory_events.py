"""Native pressure events wake the warning policy and push current gauges."""

import asyncio
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from partyline import memory_event_policy, memory_events


class MemoryEventTest(unittest.IsolatedAsyncioTestCase):
    async def test_pressure_warns_and_pushes_one_fresh_sample(self):
        row = {"id": "worker", "conv_id": "line", "name": "worker"}
        sample = {"usage_bytes": 90, "raw_bytes": 95, "cap_bytes": 100,
                  "anon_bytes": None, "file_bytes": None, "kernel_bytes": None,
                  "percent": 90, "cgroup": None}
        runtime = SimpleNamespace(db=object(), live={"worker": object()},
                                  memory_usage={"worker": sample}, sockets={"line": {object()}},
                                  broadcast=AsyncMock())
        policy = memory_event_policy.MemoryPolicy(clock=lambda: 1000)
        with patch.object(memory_event_policy, "refresh", new_callable=AsyncMock,
                          return_value={"worker"}) as refresh, \
                patch.object(memory_event_policy, "live_rows", return_value=[row]), \
                patch.object(memory_event_policy, "settings", return_value={"memory_warn_percent": 80}), \
                patch.object(memory_event_policy, "warning_limit", return_value=100), \
                patch.object(memory_event_policy, "_warn", new_callable=AsyncMock) as warn, \
                patch.object(memory_event_policy, "push_resources", new_callable=AsyncMock) as push:
            await policy.handle(runtime, {"worker"}, True)
        refresh.assert_awaited_once_with(runtime)
        warn.assert_awaited_once()
        push.assert_awaited_once_with(runtime)
        self.assertEqual(runtime.broadcast.await_args.args[1].usage_bytes, 90)

    async def test_warning_cooldown_cap_crossing_and_new_activation(self):
        row = {"id": "worker", "conv_id": "line", "name": "worker"}
        sample = {"usage_bytes": 90, "raw_bytes": 90, "cap_bytes": 100,
                  "percent": 90, "cgroup": None}
        runtime = SimpleNamespace(db=object(), live={"worker": object()},
                                  memory_usage={"worker": sample}, sockets={}, broadcast=AsyncMock())
        now = [1000]
        policy = memory_event_policy.MemoryPolicy(clock=lambda: now[0])
        with patch.object(memory_event_policy, "refresh", new=AsyncMock(return_value={"worker"})), \
                patch.object(memory_event_policy, "live_rows", return_value=[row]), \
                patch.object(memory_event_policy, "settings", return_value={"memory_warn_percent": 80}), \
                patch.object(memory_event_policy, "warning_limit", return_value=100), \
                patch.object(memory_event_policy, "_warn", new_callable=AsyncMock) as warn:
            await policy.handle(runtime, None, True)
            await policy.handle(runtime, None, True)
            self.assertEqual(warn.await_count, 1)
            sample["usage_bytes"] = 100
            await policy.handle(runtime, None, True)
            self.assertEqual(warn.await_count, 2)  # crossing the cap ignores cooldown
            runtime.live["worker"] = object()
            await policy.handle(runtime, None, True)
            self.assertEqual(warn.await_count, 3)  # a new process is separately warned
            sample["usage_bytes"] = 40
            now[0] += 601
            await policy.handle(runtime, None, False)  # a non-warning event re-arms
            sample["usage_bytes"] = 90
            await policy.handle(runtime, None, True)
            self.assertEqual(warn.await_count, 4)

    async def test_warning_failure_does_not_prevent_the_gauge_push(self):
        row = {"id": "worker", "conv_id": "line", "name": "worker"}
        sample = {"usage_bytes": 90, "raw_bytes": 90, "cap_bytes": 100,
                  "percent": 90, "cgroup": None}
        runtime = SimpleNamespace(db=object(), live={"worker": object()},
                                  memory_usage={"worker": sample}, sockets={}, broadcast=AsyncMock())
        policy = memory_event_policy.MemoryPolicy(clock=lambda: 1000)
        with patch.object(memory_event_policy, "refresh", new=AsyncMock(return_value={"worker"})), \
                patch.object(memory_event_policy, "live_rows", return_value=[row]), \
                patch.object(memory_event_policy, "settings", return_value={"memory_warn_percent": 80}), \
                patch.object(memory_event_policy, "warning_limit", return_value=100), \
                patch.object(memory_event_policy, "_warn", new_callable=AsyncMock,
                             side_effect=OSError("unavailable")), \
                self.assertLogs(memory_event_policy.logger, level="ERROR"):
            await policy.handle(runtime, None, True)
        runtime.broadcast.assert_awaited_once()
        self.assertNotIn("worker", policy.notified)

    async def test_removed_sample_during_processing_is_skipped(self):
        rows = [{"id": "one", "conv_id": "line"}, {"id": "two", "conv_id": "line"}]
        sample = {"usage_bytes": 90, "raw_bytes": 90, "cap_bytes": 100,
                  "percent": 90, "cgroup": {"root": "/scope"}}
        runtime = SimpleNamespace(db=object(), live={"one": object(), "two": object()},
                                  memory_usage={"one": sample, "two": dict(sample)},
                                  sockets={}, broadcast=AsyncMock())

        async def cleanup(*args):
            runtime.memory_usage.pop("two", None)

        policy = memory_event_policy.MemoryPolicy(clock=lambda: 1000)
        with patch.object(memory_event_policy, "refresh", new=AsyncMock(return_value={"one", "two"})), \
                patch.object(memory_event_policy, "live_rows", return_value=rows), \
                patch.object(memory_event_policy, "settings", return_value={"memory_warn_percent": 80}), \
                patch.object(memory_event_policy, "warning_limit", return_value=100), \
                patch.object(memory_event_policy, "_housekeeping", side_effect=cleanup):
            await policy.handle(runtime, None, False)
        runtime.broadcast.assert_awaited_once()

    async def test_requested_snapshot_does_not_cancel_an_inflight_pressure_notice(self):
        from partyline import memory_snapshot

        row = {"id": "worker", "conv_id": "line", "name": "worker"}
        sample = {"usage_bytes": 90, "raw_bytes": 90, "cap_bytes": 100,
                  "percent": 90, "cgroup": None}
        runtime = SimpleNamespace(db=object(), live={"worker": object()},
                                  memory_usage={"worker": sample}, sockets={}, broadcast=AsyncMock())
        started, release = asyncio.Event(), asyncio.Event()

        async def warn(*args, **kwargs):
            started.set()
            await release.wait()

        policy = memory_event_policy.MemoryPolicy(clock=lambda: 1000)
        with patch.object(memory_event_policy, "refresh", new=AsyncMock(return_value={"worker"})), \
                patch.object(memory_event_policy, "live_rows", return_value=[row]), \
                patch.object(memory_event_policy, "settings", return_value={"memory_warn_percent": 80}), \
                patch.object(memory_event_policy, "warning_limit", return_value=100), \
                patch.object(memory_event_policy, "_warn", side_effect=warn), \
                patch.object(memory_snapshot, "_read", return_value={"worker": {"usage_bytes": 10}}):
            task = asyncio.create_task(policy.handle(runtime, None, True))
            await started.wait()
            await memory_snapshot.refresh(runtime)
            self.assertTrue(runtime.memory_usage["worker"]["pressure_notice"])
            release.set()
            await task

    async def test_reclaim_and_housekeeping_use_the_event_sample_without_rereading(self):
        row = {"id": "worker", "conv_id": "line", "name": "worker"}
        detail = {"root": "/scope", "shmem": 0}
        sample = {"usage_bytes": 20, "raw_bytes": 95, "cap_bytes": 100,
                  "percent": 20, "cgroup": detail}
        runtime = SimpleNamespace(db=object(), live={"worker": object()},
                                  memory_usage={"worker": sample}, sockets={}, broadcast=AsyncMock())
        policy = memory_event_policy.MemoryPolicy(clock=lambda: 1000)
        with patch.object(memory_event_policy, "refresh", new_callable=AsyncMock,
                          return_value={"worker"}) as refresh, \
                patch.object(memory_event_policy, "live_rows", return_value=[row]), \
                patch.object(memory_event_policy, "settings", return_value={"memory_warn_percent": 80}), \
                patch.object(memory_event_policy, "warning_limit", return_value=100), \
                patch.object(memory_event_policy, "reclaim_scope") as reclaim, \
                patch.object(memory_event_policy, "reap_pytest_if_tmpfs") as reap, \
                patch.object(memory_event_policy, "_warn", new_callable=AsyncMock):
            await policy.handle(runtime, None, False)
            reclaim.assert_called_once_with("/scope", 75)
            sample["usage_bytes"] = 90
            await policy.handle(runtime, None, False)
            reap.assert_called_once()
            self.assertEqual(refresh.await_count, 2)

    async def test_idle_path_has_no_timers_and_event_reaches_policy(self):
        class Signal:
            def __init__(self):
                self.event = asyncio.Event()

            def __enter__(self):
                return self

            def __exit__(self, *args):
                pass

            async def wait(self):
                await self.event.wait()

        signal = Signal()
        runtime = SimpleNamespace(db=SimpleNamespace(events=SimpleNamespace(
            subscribe=lambda *args: signal)), live={"worker": object()})
        ready, handled = asyncio.Event(), asyncio.Event()
        source = SimpleNamespace(sync=lambda mapping: ready.set(), close=Mock())
        callbacks = []

        def factory(loop, callback):
            callbacks.append(callback)
            return source

        async def handle(runtime, targets, warning):
            self.assertEqual((targets, warning), ({"worker"}, {"worker"}))
            handled.set()

        loop = asyncio.get_running_loop()
        with patch.object(memory_events, "_scope_map", return_value={}), \
                patch.object(loop, "call_later", side_effect=AssertionError("timer created")), \
                patch.object(asyncio, "sleep", side_effect=AssertionError("sleep called")):
            task = asyncio.create_task(memory_events.run(runtime, source_factory=factory,
                                                         policy=SimpleNamespace(handle=handle)))
            await ready.wait()
            callbacks[0]({"worker"}, True)
            await handled.wait()
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task
        source.close.assert_called_once()

    async def test_event_burst_merges_targets_and_warning_eligibility(self):
        pending = memory_events.PendingEvents()
        for _ in range(1000):
            pending.notify({"a"}, True)
            pending.notify({"b"}, False)
        pending.notify(None, False)
        targets, warnings = await pending.wait()
        self.assertIsNone(targets)
        self.assertEqual(warnings, {"a"})
        self.assertFalse(pending.ready.is_set())

    async def test_events_arriving_during_a_read_form_one_followup(self):
        class Signal:
            def __enter__(self):
                return self

            def __exit__(self, *args):
                pass

            async def wait(self):
                await asyncio.Event().wait()

        runtime = SimpleNamespace(db=SimpleNamespace(events=SimpleNamespace(
            subscribe=lambda *args: Signal())), live={"a": object(), "b": object()})
        ready, first, release, second = (asyncio.Event() for _ in range(4))
        callback = []
        source = SimpleNamespace(sync=lambda mapping: ready.set(), close=Mock())
        seen = []

        async def handle(runtime, targets, warning):
            seen.append((targets, warning))
            if len(seen) == 1:
                first.set()
                await release.wait()
            else:
                second.set()

        def factory(loop, notify):
            callback.append(notify)
            return source

        with patch.object(memory_events, "_scope_map", return_value={}):
            task = asyncio.create_task(memory_events.run(runtime, source_factory=factory,
                                                         policy=SimpleNamespace(handle=handle)))
            await ready.wait()
            callback[0]({"a"}, True)
            await first.wait()
            for _ in range(1000):
                callback[0]({"a"}, True)
                callback[0]({"b"}, False)
            release.set()
            await second.wait()
            self.assertEqual(seen, [({"a"}, {"a"}), ({"a", "b"}, {"a"})])
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task

    async def test_global_pressure_pushes_but_does_not_warn_below_threshold(self):
        rows = [{"id": "low", "conv_id": "line", "name": "low"},
                {"id": "high", "conv_id": "line", "name": "high"}]
        def sample(usage):
            return {"usage_bytes": usage, "raw_bytes": usage, "cap_bytes": 100,
                    "percent": usage, "cgroup": None}
        runtime = SimpleNamespace(db=object(), live={"low": object(), "high": object()},
                                  memory_usage={"low": sample(10), "high": sample(90)},
                                  sockets={}, broadcast=AsyncMock())
        policy = memory_event_policy.MemoryPolicy(clock=lambda: 1000)
        with patch.object(memory_event_policy, "refresh", new=AsyncMock(return_value={"low", "high"})), \
                patch.object(memory_event_policy, "live_rows", return_value=rows), \
                patch.object(memory_event_policy, "settings", return_value={"memory_warn_percent": 80}), \
                patch.object(memory_event_policy, "warning_limit", return_value=100), \
                patch.object(memory_event_policy, "_warn", new_callable=AsyncMock) as warn:
            await policy.handle(runtime, None, True)
        self.assertEqual(warn.await_count, 1)
        self.assertEqual(warn.await_args.args[1]["id"], "high")
        self.assertEqual(runtime.broadcast.await_count, 2)
