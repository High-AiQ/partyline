"""Chrome routing retains UIA query scope, reply timing and queued operation timing."""
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock, Mock

from partyline_helper.timing import Timing
from partyline_helper.uia_task import WindowTask, read_options
from tests.cdp_fakes import Fixture
from tests.test_screen_latency import Clock


class RoutingTimingTests(IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.f = Fixture()
        self.addAsyncCleanup(self.f.close)
        self.worker = WindowTask(self.f.access.session)
        self.addAsyncCleanup(self.worker.close)

    async def test_chrome_first_read_and_action_keep_queue_timing_and_message_context(self):
        await self.f.browser.ensure()
        clock = Clock()
        queued = Timing(now=clock)
        clock.advance(3)
        message = dict(agent="caller", line_id="line")
        await self.worker._read("read", message=message, queued=queued)
        reply = self.f.session.send.await_args.kwargs
        self.assertEqual("cdp", reply["source"])
        self.assertEqual(3, reply["timing"]["task_queue_ms"])
        self.assertIn('"process":"caller"', self.f.session.tools.audit.append.call_args.args[-1])
        page = await self.f.chrome.page(self.f.access)
        page.quiet.wait = AsyncMock(return_value="quiet")
        self.worker.actions.perform = AsyncMock()
        queued = Timing(now=clock)
        clock.advance(5)
        await self.worker._action(dict(request_id="act", action="invoke", force=True,
                                      element_id=reply["elements"][1]["id"], **message), queued=queued)
        reply = self.f.session.send.await_args.kwargs
        self.assertEqual("completed", reply["status"])
        self.assertEqual("cdp", reply["source"])
        self.assertEqual(5, reply["timing"]["task_queue_ms"])
        self.worker.actions.perform.assert_not_awaited()

    async def test_uia_fallback_keeps_filtered_read_and_action_phase_timings(self):
        self.f.browser.discovery = lambda: None
        self.f.access.reader = Mock(return_value={"elements": [], "snapshot_id": "s", "scoped": True,
                                                 "timing": {"walk_ms": 7}})
        query = {"query": "=Control", "control_type": "Button"}
        options = read_options(dict(query_scope=query))
        await self.worker._read("read", options=options)
        reply = self.f.session.send.await_args.kwargs
        self.assertEqual("uia", reply["source"])
        self.assertTrue(reply["scoped"])
        self.assertEqual(7, reply["timing"]["walk_ms"])
        self.assertIn("task_queue_ms", reply["timing"])
        self.assertEqual(query, self.f.access.reader.call_args.kwargs["query"])
        self.worker.actions.perform = AsyncMock(return_value={"status": "completed",
                                                              "timing": {"target_ms": 11}})
        await self.worker._action(dict(request_id="act", action="invoke", element_id="id"))
        reply = self.f.session.send.await_args.kwargs
        self.assertEqual("uia", reply["source"])
        self.assertEqual(11, reply["timing"]["target_ms"])
        self.assertIn("task_queue_ms", reply["timing"])
        self.worker.actions.perform.assert_awaited_once()
