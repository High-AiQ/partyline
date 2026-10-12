import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from partyline.contracts import ResourceSnapshotEvent
from partyline.db import Db
from partyline.resource_budget import snapshot
from partyline.resource_push import HEARTBEAT, ResourcePusher

MB = 1024**2


class ResourcePushTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.db = Db(f"{self.temp.name}/partyline.db")
        self.addCleanup(self.db.close)
        self.base = snapshot(self.db)
        self.base.update(host_used_bytes=8_000 * MB, partyline_used_bytes=2_000 * MB,
                         tmp_used_bytes=1_000 * MB)
        self.view = dict(self.base)
        self.sockets = {"line": {object()}}
        self.runtime = SimpleNamespace(db=self.db, sockets=self.sockets, broadcast_all=AsyncMock())
        self.now = 1000.0
        self.pusher = ResourcePusher(lambda: self.now)
        patcher = patch("partyline.resource_push.snapshot",
                        side_effect=lambda *args: dict(self.view))
        self.compute = patcher.start()
        self.addCleanup(patcher.stop)

    async def tick(self, after=5.0):
        self.now += after
        return await self.pusher.tick(self.runtime)

    async def test_no_sockets_means_no_snapshot_is_computed(self):
        self.sockets.clear()
        self.assertFalse(await self.tick())
        self.compute.assert_not_called()
        self.runtime.broadcast_all.assert_not_awaited()

    async def test_first_tick_sends_the_snapshot_event(self):
        self.assertTrue(await self.tick())
        event = self.runtime.broadcast_all.await_args.args[0]
        self.assertIsInstance(event, ResourceSnapshotEvent)
        self.assertEqual(event.snapshot.host_used_bytes, 8_000 * MB)

    async def test_an_unchanged_tick_within_the_heartbeat_sends_nothing(self):
        await self.tick()
        for _ in range(5):
            self.assertFalse(await self.tick())
        self.assertEqual(self.runtime.broadcast_all.await_count, 1)

    async def test_small_drift_is_quiet_and_a_real_move_is_sent_once(self):
        await self.tick()
        self.view["host_used_bytes"] += 10 * MB
        self.assertFalse(await self.tick())
        self.view["host_used_bytes"] += 60 * MB  # 70 MB past the last frame sent
        self.assertTrue(await self.tick())
        self.assertFalse(await self.tick())
        self.assertEqual(self.runtime.broadcast_all.await_count, 2)

    async def test_each_watched_number_triggers_a_frame(self):
        await self.tick()
        for key, delta in (("partyline_used_bytes", 70 * MB), ("tmp_used_bytes", 70 * MB),
                           ("live_processes", 1), ("max_live_processes", 1),
                           ("memory_reserve_bytes", 1)):
            with self.subTest(key):
                self.view[key] += delta
                self.assertTrue(await self.tick())

    async def test_a_heartbeat_follows_a_quiet_minute(self):
        await self.tick()
        self.assertFalse(await self.tick(HEARTBEAT - 10))
        self.assertTrue(await self.tick(10))
        self.assertEqual(self.runtime.broadcast_all.await_count, 2)
