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

    async def test_connect_asks_for_fresh_docker_and_memory_snapshot(self):
        runtime = SimpleNamespace(db=object())
        speech = SimpleNamespace(settings=SimpleNamespace(model_dump=lambda: {}))
        with patch.object(browser_snapshots, "speech_snapshot", return_value=speech), \
                patch.object(browser_snapshots, "_view", return_value={"live_processes": 7}), \
                patch("partyline.docker_workloads.inventory.sample", new_callable=AsyncMock) as docker, \
                patch.object(memory_snapshot, "refresh", new_callable=AsyncMock) as refresh:
            hello = await browser_snapshots.hello_payload(runtime, "line", "name", "build", "1", None)
        self.assertEqual(hello["resource_snapshot"]["live_processes"], 7)
        docker.assert_awaited_once_with(runtime, force=True)
        refresh.assert_awaited_once_with(runtime)
