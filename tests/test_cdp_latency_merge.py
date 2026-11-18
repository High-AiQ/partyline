"""Chrome routing retains UIA query scope, reply timing and queued operation timing."""
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock, Mock

from partyline_helper.cdp_recipes import ACTION_STATE
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
        self.assertGreater(reply["timing"]["ax_nodes"], 0)
        self.assertGreater(reply["timing"]["cdp_commands"], 0)
        self.assertIn("dom_mapping_ms", reply["timing"])
        self.assertEqual(3, reply["timing"]["task_queue_ms"])
        self.assertIn('"process":"caller"', self.f.session.tools.audit.append.call_args.args[-1])
        page = await self.f.chrome.page(self.f.access)
        page.quiet.wait = AsyncMock(return_value="quiet")
        queued = Timing(now=clock)
        clock.advance(5)
        await self.worker._action(dict(request_id="act", action="invoke", force=True,
                                      element_id=reply["elements"][1]["id"], **message), queued=queued)
        reply = self.f.session.send.await_args.kwargs
        self.assertEqual("completed", reply["status"])
        self.assertEqual("cdp", reply["source"])
        self.assertEqual(5, reply["timing"]["task_queue_ms"])
        self.assertGreater(reply["timing"]["target_proof_ms"], 0)
        self.assertGreater(reply["timing"]["dispatch_proof_ms"], 0)
        self.assertGreater(reply["timing"]["settle_wait_ms"], 0)
        self.assertEqual(1, sum(call["method"] == "Accessibility.getFullAXTree"
                                for call in self.f.socket.calls))
        self.assertEqual(12, reply["timing"]["cdp_commands"])

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

    async def test_target_proof_failure_keeps_helper_phase_timing(self):
        read = await self.f.read()
        self.f.socket.states[2]["connected"] = False
        result = await self.f.chrome.action(self.f.access, dict(
            type="window_element_action", action="invoke", element_id=read["elements"][1]["id"]))
        self.assertEqual("failed", result["status"])
        self.assertIn("target_proof_ms", result["timing"])
        self.assertGreater(result["timing"]["cdp_commands"], 0)

    async def test_dom_discovered_proof_combines_state_and_visibility_without_weakening_identity(self):
        self.f.socket.nodes[1]["dom_discovered"] = True
        read = await self.f.read()
        page = await self.f.chrome.page(self.f.access)
        page.quiet.wait = AsyncMock(return_value="quiet")
        self.f.socket.states[2]["document_identity"] = "replacement document"
        result = await self.f.chrome.action(self.f.access, dict(
            action="invoke", element_id=read["elements"][1]["id"]))
        self.assertEqual("target_changed", result["reason"])
        calls = [call for call in self.f.socket.calls if call["method"] == "Runtime.callFunctionOn"]
        self.assertEqual(1, sum(call["params"]["functionDeclaration"] == ACTION_STATE for call in calls))
        self.assertFalse(any(call["method"].startswith("Input.") for call in self.f.socket.calls))

    async def test_action_cleanup_skips_cdp_after_access_revocation(self):
        read = await self.f.read()
        self.f.socket.calls.clear()
        def revoke(message):
            if message["method"] == "Runtime.callFunctionOn":
                self.f.access.gate.invalidate()
                self.f.chrome.revoke(self.f.access)
        self.f.socket.hook = revoke
        result = await self.f.chrome.action(self.f.access, dict(
            action="invoke", element_id=read["elements"][1]["id"]))
        self.assertEqual("failed", result["status"])
        self.assertFalse(any(call["method"] == "Runtime.releaseObjectGroup" for call in self.f.socket.calls))
