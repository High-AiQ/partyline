"""Regression coverage for ignored AX nodes, covered HWNDs, approval and attach revocation."""
import asyncio
import json
from unittest import IsolatedAsyncioTestCase, TestCase

from partyline.screen_bounded import bounded
from partyline.screen_tree_answer import size
from partyline_helper.cdp_ax import exposed
from partyline_helper.uia_task import WindowTask
from tests.cdp_fakes import Fixture
from tests.screen_helper_fakes import checkpoint


class Revisions(IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.f = Fixture()
        self.addAsyncCleanup(self.f.close)

    async def test_ignored_nodes_are_removed_before_chunking_and_children_reparented(self):
        hidden = [dict(nodeId=str(n), backendDOMNodeId=n, parentId="1", ignored=True,
                       ignoredReasons=[{"name": "ariaHiddenElement"}],
                       role={"value": "button"}, name={"value": "Hidden"}) for n in range(10, 2510)]
        child = dict(nodeId="3000", parentId="11", backendDOMNodeId=3000,
                     role={"value": "button"}, name={"value": "Exposed child"})
        self.f.socket.nodes = [*self.f.socket.nodes, *hidden, child]
        result = await self.f.read()
        self.assertEqual(len(result["elements"]), 4)
        self.assertNotIn("next_cursor", result)
        root = result["elements"][0]["id"]
        self.assertEqual(result["elements"][-1]["parent"], root)
        self.assertNotIn("Hidden", json.dumps(result))
        resolved = [m["params"]["backendNodeId"] for m in self.f.socket.calls
                    if m["method"] == "DOM.resolveNode"]
        self.assertEqual(resolved, [1, 2, 3, 3000])
        self.assertEqual(len(self.f.chrome.pages[self.f.access]["a"].nodes), 4)
        self.assertEqual(sum(m["method"] == "Runtime.releaseObjectGroup" for m in self.f.socket.calls), 1)
        self.assertFalse(any(m["method"] == "Runtime.releaseObject" for m in self.f.socket.calls))

    async def test_all_hidden_occluded_window_uses_unique_hwnd_title(self):
        self.f.socket.visible = {key: False for key in self.f.socket.visible}
        result = await self.f.read()
        self.assertEqual(result["source"], "cdp")
        self.assertEqual(self.f.chrome.selected[self.f.access], "a")
        self.f.socket.event("Runtime.bindingCalled", name="__partylineChange", payload="hidden")
        await checkpoint()
        self.assertEqual((await self.f.read())["source"], "cdp")

    async def test_duplicate_titles_use_visibility_tiebreaker_and_refuse_all_hidden(self):
        self.f.socket.titles["b"] = "Lab"
        self.f.socket.visible.update(a=False, b=True)
        self.assertEqual((await self.f.read())["source"], "cdp")
        self.assertEqual(self.f.chrome.selected[self.f.access], "b")
        self.f.socket.visible["b"] = False
        self.assertIsNone(await self.f.chrome.page(self.f.access))
        self.assertIn("ambiguous", self.f.chrome.reasons[self.f.access])

    async def test_pending_approval_serves_uia_and_late_approval_needs_no_reshare(self):
        accepted = asyncio.get_running_loop().create_future()
        entered = asyncio.Event()
        async def connect(*args, **kwargs):
            self.assertIsNone(kwargs["open_timeout"])
            entered.set()
            return await accepted
        self.f.browser.connector = connect
        self.f.chrome.start(self.f.access)
        await entered.wait()
        worker = WindowTask(self.f.access.session)
        for _ in range(2):
            result = await worker.snapshot({}, {})
            self.assertEqual(result["source"], "uia")
            self.assertIn("approval", result["source_reason"].lower())
            self.assertFalse(self.f.chrome.connecting.done())
        accepted.set_result(self.f.socket)
        await self.f.chrome.connecting
        result = await worker.snapshot({}, {})
        self.assertEqual(result["source"], "cdp")
        self.assertEqual(self.f.browser.state, "connected")

    async def test_not_enabled_status_does_not_advance_the_snapshot_event_barrier(self):
        self.f.browser.discovery = lambda: None
        worker = WindowTask(self.f.access.session)
        result = await worker.snapshot({}, {})
        self.assertEqual(result["source"], "uia")
        self.assertIn("chrome://inspect", result["source_reason"])
        counter = result["event_counter"]
        for _ in range(2):
            await self.f.shares.dispatch(dict(type="read_window_elements", grant_id="g",
                                             request_id="status", event_status=True))
            self.assertEqual(self.f.session.send.await_args.kwargs["event_counter"], counter)

    async def test_revoke_during_attach_detaches_new_session_without_orphan_page(self):
        await self.f.browser.ensure()
        def hook(message):
            if message["method"] == "Target.attachToTarget":
                self.f.access.revoke()
        self.f.socket.hook = hook
        self.assertIsNone(await self.f.chrome.page(self.f.access))
        if self.f.shares.tasks:
            await asyncio.gather(*list(self.f.shares.tasks))
        self.assertFalse(self.f.browser.listeners)
        self.assertFalse(self.f.browser.result_hooks)
        self.assertFalse(self.f.chrome.pages[self.f.access])
        self.assertTrue(any(m["method"] == "Target.detachFromTarget" and m["params"]["sessionId"] == "a"
                            for m in self.f.socket.calls))

    async def test_cancelled_attach_late_response_is_detached(self):
        await self.f.browser.ensure()
        entered, request = asyncio.Event(), {}
        original = self.f.socket.send
        async def send(raw):
            message = json.loads(raw)
            if message["method"] == "Target.attachToTarget":
                request.update(message)
                entered.set()
            else:
                await original(raw)
        self.f.socket.send = send
        task = asyncio.create_task(self.f.chrome.page(self.f.access))
        await entered.wait()
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        self.f.socket.queue.put_nowait(dict(id=request["id"], result={"sessionId": "late"}))
        await checkpoint()
        if self.f.shares.tasks:
            await asyncio.gather(*list(self.f.shares.tasks))
        self.assertFalse(self.f.browser.listeners)
        self.assertFalse(self.f.browser.result_hooks)
        self.assertTrue(any(m["method"] == "Target.detachFromTarget" and m["params"]["sessionId"] == "late"
                            for m in self.f.socket.calls))


class Normalization(TestCase):
    def test_ignored_ancestor_chains_and_cycles_are_bounded(self):
        nodes = [dict(nodeId="w", ignored=True), dict(nodeId="i", ignored=True, parentId="w"),
                 dict(nodeId="leaf", parentId="i"), dict(nodeId="cycle", ignored=True, parentId="cycle"),
                 dict(nodeId="last", parentId="cycle")]
        self.assertEqual(exposed(nodes), [dict(nodeId="leaf", parentId=None),
                                          dict(nodeId="last", parentId=None)])

    def test_server_bounds_unicode_escaped_strings_and_preserves_small_results(self):
        small = {"source": "cdp", "status": "completed", "result": {"value": 42}}
        self.assertIs(bounded(small), small)
        hostile_metadata = bounded({"source": "x" * 5000, "status": "y" * 5000, "result": 1})
        self.assertLessEqual(size(hostile_metadata), 4096)
        self.assertEqual((hostile_metadata["source"], hostile_metadata["status"]), ("cdp", "completed"))
        for value in ("💻" * 10000, '"\\' * 10000, "\x01" * 10000):
            result = bounded({"source": "cdp", "status": "completed", "result": value})
            self.assertTrue(result["truncated"])
            self.assertLessEqual(size(result), 4096)
            self.assertTrue(result["result_preview"])
