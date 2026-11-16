"""A stop request belongs to the activation it stopped; it never passes to the next one."""

import asyncio
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from partyline import process_exit
from partyline.adapters import base
from partyline.attachment_stop_audit import direct_stop, pop_stop_intent
from tests.test_adapter_base import Recorder


class StopActivationTest(unittest.IsolatedAsyncioTestCase):
    async def test_a_cancelled_stop_does_not_hand_its_intent_to_the_next_activation(self):
        first = Recorder(["cat"], id="worker-att", name="worker", runtime_owner="owner-1",
                         memory_limit="4G")
        first.proc = SimpleNamespace(pid=1)
        never_exits = asyncio.Event()  # only a real exit would set it; stop cancels the watcher first

        async def wait_for_exit(proc):
            await never_exits.wait()
            return -15

        with patch.object(base, "wait_for_process", wait_for_exit), \
                patch.object(base, "stop_process_group", AsyncMock()):
            first._tasks = [asyncio.create_task(first._watch_exit())]
            direct_stop("worker-att", "line_process_routes.close_attachment", "operator")
            await first.stop()
            await asyncio.gather(*first._tasks, return_exceptions=True)

        second = Recorder(["cat"], id="worker-att", name="worker", runtime_owner="owner-2",
                          memory_limit="4G")
        second.memory_limit = "4G"  # start() sets this on a real activation
        await process_exit.report_exit(second, -15)

        self.assertIn("worker exited (code -15, SIGTERM sent by external)", second.posts[-1][2])
        self.assertIsNone(pop_stop_intent("worker-att"))

    async def test_the_activation_that_was_stopped_attributes_its_own_exit(self):
        adapter = Recorder(["cat"], id="worker-att", name="worker", runtime_owner="owner-1",
                           memory_limit="4G")
        adapter.memory_limit = "4G"  # start() sets this on a real activation
        direct_stop("worker-att", "line_process_routes.close_attachment", "operator")
        await adapter.stop()

        with self.assertLogs("partyline.process_exit", level="INFO") as logs:
            await process_exit.report_exit(adapter, -15)

        self.assertTrue(any(
            "SIGTERM sent by partyline: line_process_routes.close_attachment (requested by operator)"
            in line for line in logs.output), logs.output)
