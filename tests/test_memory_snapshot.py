"""Explicit snapshots read fresh gauges rather than relying on a sampler tick."""

import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from partyline import browser_snapshots, memory_snapshot


class MemorySnapshotTest(unittest.IsolatedAsyncioTestCase):
    async def test_refresh_reads_live_scope_and_replaces_stale_value(self):
        adapter = SimpleNamespace(proc=SimpleNamespace(pid=123))
        runtime = SimpleNamespace(db=object(), live={"worker": adapter},
                                  memory_usage={"worker": {"usage_bytes": 1}})
        row = {"id": "worker"}
        sample = {"working_set": 80, "peak": 90, "current": 100,
                  "anon": 70, "file": 20, "kernel_total": 10}
        with patch.object(memory_snapshot, "live_rows", return_value=[row]), \
                patch.object(memory_snapshot, "settings", return_value={}), \
                patch.object(memory_snapshot, "cap_bytes", return_value=200), \
                patch.object(memory_snapshot.sys, "platform", "linux"), \
                patch.object(memory_snapshot, "cgroup_usage", return_value=sample), \
                patch.object(memory_snapshot, "process_snapshot") as table:
            await memory_snapshot.refresh(runtime)
        self.assertEqual(runtime.memory_usage["worker"]["usage_bytes"], 80)
        self.assertEqual(runtime.memory_usage["worker"]["raw_bytes"], 100)
        self.assertEqual(runtime.memory_usage["worker"]["percent"], 40)
        table.assert_not_called()

    async def test_connect_reads_memory_and_requests_docker_refresh(self):
        runtime = SimpleNamespace(db=object())
        speech = SimpleNamespace(settings=SimpleNamespace(model_dump=lambda: {}))
        with patch.object(browser_snapshots, "speech_snapshot", return_value=speech), \
                patch.object(browser_snapshots, "_view", return_value={"live_processes": 7}), \
                patch("partyline.docker_workloads.inventory.kick") as docker, \
                patch.object(memory_snapshot, "refresh", new_callable=AsyncMock) as refresh:
            hello = await browser_snapshots.hello_payload(runtime, "line", "name", "build", "1", None)
        self.assertEqual(hello["resource_snapshot"]["live_processes"], 7)
        docker.assert_called_once_with(runtime)
        refresh.assert_awaited_once_with(runtime)

    async def test_connect_does_not_wait_for_a_hung_docker_daemon(self):
        import asyncio
        from partyline.docker_workloads import Inventory

        inventory = Inventory()
        started = asyncio.Event()

        async def stalled(runtime):
            started.set()
            await asyncio.Event().wait()

        runtime = SimpleNamespace(db=object(), sockets={})
        speech = SimpleNamespace(settings=SimpleNamespace(model_dump=lambda: {}))
        with patch.object(inventory, "sample", side_effect=stalled), \
                patch("partyline.docker_workloads.inventory", inventory), \
                patch.object(memory_snapshot, "refresh", new_callable=AsyncMock), \
                patch.object(browser_snapshots, "speech_snapshot", return_value=speech), \
                patch.object(browser_snapshots, "_view", return_value={"live_processes": 7}):
            hello = await browser_snapshots.hello_payload(runtime, "line", "name", "build", "1", None)
            self.assertEqual(hello["resource_snapshot"]["live_processes"], 7)
            await started.wait()
            await inventory.close()

    async def test_rss_fallback_uses_one_process_listing(self):
        adapters = {"one": SimpleNamespace(proc=SimpleNamespace(pid=1)),
                    "two": SimpleNamespace(proc=SimpleNamespace(pid=2))}
        runtime = SimpleNamespace(db=object(), live=adapters, memory_usage={})
        with patch.object(memory_snapshot, "live_rows", return_value=[{"id": "one"}, {"id": "two"}]), \
                patch.object(memory_snapshot, "settings", return_value={}), \
                patch.object(memory_snapshot, "cap_bytes", return_value=100), \
                patch.object(memory_snapshot.sys, "platform", "darwin"), \
                patch.object(memory_snapshot, "process_snapshot", return_value=({1: 0, 2: 0},
                                                                                {1: 10, 2: 20})) as table:
            await memory_snapshot.refresh(runtime)
        table.assert_called_once()
        self.assertEqual(runtime.memory_usage["one"]["usage_bytes"], 10)
        self.assertEqual(runtime.memory_usage["two"]["usage_bytes"], 20)

    async def test_replaced_activation_does_not_receive_old_reading(self):
        import asyncio
        from threading import Event

        started, release = Event(), Event()
        old = object()
        runtime = SimpleNamespace(db=object(), live={"worker": old}, memory_usage={})

        def read(db, live):
            started.set()
            release.wait()
            return {"worker": {"usage_bytes": 100}}

        with patch.object(memory_snapshot, "_read", side_effect=read):
            task = asyncio.create_task(memory_snapshot.refresh(runtime))
            await asyncio.to_thread(started.wait)
            runtime.live["worker"] = object()
            release.set()
            self.assertEqual(await task, set())
        self.assertEqual(runtime.memory_usage, {})
