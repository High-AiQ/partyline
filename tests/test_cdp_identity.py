"""Busy pages use backend identity at dispatch instead of whole-page quiet."""
import asyncio
import json
import subprocess
import unittest
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from partyline.screen_elements import ElementsHub
from partyline.screen_element_actions import ElementAction, element_action
from partyline.screen_failure_snapshot import attach, failed
from partyline_helper.cdp_recipes import STATE
from partyline_helper.cdp_identity import TargetChanged
from partyline_helper.cdp_transport import CDPError, DocumentChanged, ExtensionRefused, PageUnavailable
from tests.cdp_fakes import Fixture
from tests.test_cdp_recovery import Deadline
from tests.test_cdp_settle import Clock
from tests.screen_helper_fakes import checkpoint

GRANT = {"id": "g", "process": "chrome.exe", "title": "Lab"}


class IdentityTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.f = Fixture()
        self.addAsyncCleanup(self.f.close)
        self.clock = Clock()
        self.elements = ElementsHub(SimpleNamespace(), clock=self.clock)
        self.outer = SimpleNamespace(elements=self.elements,
                                     window_grants=SimpleNamespace(spend=Mock()))
        self.principal = SimpleNamespace(name="agent")
        self.device = {"id": "device"}
        self.captures = 0
        self.elements.exchange = self.exchange
        self.f.socket.states[2]["aria_disabled"] = False
        self.f.socket.nodes.append(dict(nodeId="4", parentId="2", backendDOMNodeId=4,
                                        role={"value": "StaticText"}, name={"value": "Label"}))
        self.f.socket.states[4] = dict(tag="SPAN")
        for module in ("screen_elements", "screen_element_actions"):
            p = patch(f"partyline.{module}.resolve_window", return_value=(GRANT, self.device))
            p.start()
            self.addCleanup(p.stop)
        for name in ("screen_elements.require_window", "screen_element_actions.deny_unless"):
            p = patch("partyline." + name)
            p.start()
            self.addCleanup(p.stop)
        p = patch("partyline.screen_element_actions.request_principal", return_value=self.principal)
        p.start()
        self.addCleanup(p.stop)

    async def exchange(self, principal, grant, device, kind, **fields):
        if kind == "window_element_action":
            return await self.f.chrome.action(self.f.access, fields)
        if fields.get("event_status"):
            return self.f.chrome.status(self.f.access)
        self.captures += 1
        result = await self.f.read(**fields)
        page = self.f.chrome.pages[self.f.access]["a"]
        page.quiet.wait = AsyncMock(return_value="deadline")
        return result

    async def read(self):
        result = await self.elements.read(self.principal, window="g")
        tree = self.elements.snapshots["g"]
        self.ident = next(n.id for n in tree.nodes.values() if n.type == "Hyperlink")
        return result

    async def invoke(self):
        return await element_action(SimpleNamespace(db=None), self.outer, "line",
                                    ElementAction(element_id=self.ident, action="invoke"), None)

    def churn(self, message):
        if message.get("sessionId"):
            self.f.socket.event("Runtime.bindingCalled", name="__partylineChange", payload="")
            self.elements.changed("g")

    async def test_unrelated_continuous_mutations_allow_stable_invoke_without_recapture(self):
        self.f.socket.hook = self.churn
        read = await self.read()
        self.assertTrue(read["change_event_since_snapshot"])
        self.clock.advance(10)  # even an expired tree delegates its backend proof to the helper
        result = await self.invoke()
        self.assertEqual("completed", result["status"])
        self.assertEqual(1, self.captures)
        self.assertEqual(2, sum(m["method"] == "Input.dispatchMouseEvent" for m in self.f.socket.calls))

    async def test_target_ancestor_and_descendant_events_reprove_same_node_and_bounds(self):
        for backend in (1, 2, 4):
            with self.subTest(backend=backend):
                await self.read()
                self.f.socket.event("DOM.attributeModified", nodeId=backend, name="class", value="changed")
                self.elements.changed("g")
                await checkpoint()
                self.assertEqual("completed", (await self.invoke())["status"])

    async def test_movement_disconnection_and_frame_document_change_refuse_even_with_force(self):
        for change in ({"bounds": [1, 0, 101, 40]}, {"connected": False},
                       {"document_identity": "new document"}):
            with self.subTest(change=change):
                self.f.socket.states[2] = dict(tag="A", hit=True)
                await self.read()
                self.f.socket.states[2].update(change)
                result = await self.f.chrome.action(self.f.access, dict(action="invoke", force=True,
                    element_id=self.elements.snapshots["g"].nodes[self.ident].helper))
                self.assertEqual(("failed", "target_changed"), (result["status"], result["reason"]))
        self.assertFalse(any(m["method"].startswith("Input.") for m in self.f.socket.calls))

    async def test_replacement_with_same_name_never_dispatches_to_the_new_node(self):
        await self.read()
        self.f.socket.states.pop(2)  # original backend node remains resolvable but disconnected
        self.f.socket.states[4] = dict(tag="A", hit=True)
        self.f.socket.nodes[1] = {**self.f.socket.nodes[1], "backendDOMNodeId": 4}
        result = await self.invoke()
        self.assertEqual("target_changed", result["reason"])
        self.assertFalse(any(m["method"].startswith("Input.") for m in self.f.socket.calls))

    async def test_collected_node_resolution_refuses_at_initial_and_dispatch_proofs(self):
        for stage in ("initial", "dispatch"):
            with self.subTest(stage=stage):
                await self.read()
                gone = stage == "initial"
                send = self.f.socket.send
                async def reject(raw, send=send):
                    nonlocal gone
                    message = json.loads(raw)
                    if message["method"] == "DOM.getBoxModel":
                        gone = True  # collected after hit testing, before the final proof
                    if (gone and message["method"] == "DOM.resolveNode"
                            and message["params"]["backendNodeId"] == 2):
                        self.f.socket.calls.append(message)
                        self.f.socket.queue.put_nowait({"id": message["id"], "error": {
                            "code": -32000, "message": "No node with given id found"}})
                        return
                    await send(raw)
                with patch.object(self.f.socket, "send", side_effect=reject):
                    result = await self.invoke()
                self.assertEqual(("failed", "target_changed"), (result["status"], result["reason"]))
                self.assertIn("screen_window_snapshot + screen_window_click", result["error"])
                self.assertTrue(failed(result))  # retains the bounded failure-picture path
        self.assertFalse(any(m["method"].startswith("Input.") for m in self.f.socket.calls))

    async def test_resolution_proof_preserves_specific_cdp_failures_and_read_errors(self):
        await self.read()
        page = self.f.chrome.pages[self.f.access]["a"]
        for error in (PageUnavailable("detached"), ExtensionRefused("DOM.resolveNode", "domain_refused"),
                      DocumentChanged("document changed")):
            with self.subTest(error=type(error).__name__), \
                    patch.object(page, "call", side_effect=error):
                with self.assertRaises(type(error)) as caught:
                    await page.function(2, STATE, proof=True)
                self.assertIs(error, caught.exception)
        with patch.object(page, "call", side_effect=CDPError("Chrome rejected the CDP command")):
            with self.assertRaises(CDPError) as caught:
                await page.function(2, STATE)  # ordinary reads still report an unreadable node
            self.assertNotIsInstance(caught.exception, TargetChanged)

    async def test_proof_does_not_relabel_function_execution_errors_or_revocation(self):
        await self.read()
        page = self.f.chrome.pages[self.f.access]["a"]
        call = page.call
        async def rejected(method, *args, **kwargs):
            if method == "Runtime.callFunctionOn":
                raise CDPError("Chrome rejected the CDP command")
            return await call(method, *args, **kwargs)
        with patch.object(page, "call", side_effect=rejected):
            with self.assertRaises(CDPError) as caught:
                await page.function(2, STATE, proof=True)
            self.assertNotIsInstance(caught.exception, TargetChanged)
        self.f.access.gate.revoked.set()
        with self.assertRaisesRegex(CDPError, "consent revoked"):
            await page.function(2, STATE, proof=True)

    async def test_focus_handler_movement_is_reproved_before_input(self):
        await self.read()
        def move(message):
            if message["method"] == "DOM.focus":
                self.f.socket.states[2]["bounds"] = [50, 0, 150, 40]
        self.f.socket.hook = move
        self.assertEqual("target_changed", (await self.invoke())["reason"])
        self.assertFalse(any(m["method"].startswith("Input.") for m in self.f.socket.calls))

    async def test_helper_recapture_cannot_replace_the_servers_original_bounds_proof(self):
        await self.read()
        self.f.socket.states[2]["bounds"] = [50, 0, 150, 40]
        await self.f.read()  # helper cache advanced, but the server still holds the original capture
        self.assertEqual("target_changed", (await self.invoke())["reason"])
        self.assertFalse(any(m["method"].startswith("Input.") for m in self.f.socket.calls))

    async def test_recapture_while_waiting_for_window_lock_refuses_changed_proof(self):
        await self.read()
        locked = self.elements.locked
        @asynccontextmanager
        async def changed(grant_id):
            async with locked(grant_id):
                self.f.socket.states[2]["bounds"] = [50, 0, 150, 40]
                result = await self.f.read()
                tree = self.elements.snapshots["g"]
                tree.nodes[self.ident].cached["action_token"] = result["elements"][1]["action_token"]
                yield
        self.elements.locked = changed
        self.assertEqual("target_changed", (await self.invoke())["reason"])
        self.assertFalse(any(m["method"].startswith("Input.") for m in self.f.socket.calls))

    async def test_related_mutation_that_moves_target_refuses(self):
        for backend in (1, 2, 4):
            with self.subTest(backend=backend):
                self.f.socket.states[2].pop("bounds", None)
                await self.read()
                self.f.socket.event("DOM.attributeModified", nodeId=backend, name="class", value="changed")
                self.f.socket.states[2]["bounds"] = [50, 0, 150, 40]
                self.assertEqual("target_changed", (await self.invoke())["reason"])
        self.assertFalse(any(m["method"].startswith("Input.") for m in self.f.socket.calls))

    async def test_document_epoch_change_and_lost_cdp_never_fall_back_to_uia(self):
        await self.read()
        page = self.f.chrome.pages[self.f.access]["a"]
        page.epoch += 1
        self.assertEqual("target_changed", (await self.invoke())["reason"])
        self.outer.elements.snapshots.clear()
        self.f.access.snapshot = AsyncMock()
        await self.f.browser.disconnect()
        result = await self.f.chrome.action(self.f.access, dict(action="invoke", element_id="old"))
        self.assertEqual("failed", result["status"])
        self.f.access.snapshot.assert_not_awaited()

    async def test_busy_failure_skips_marks_and_picture_has_a_two_second_fake_deadline(self):
        result = {"status": "failed", "reason": "target_changed", "error": "target keeps changing"}
        self.assertTrue(failed(result))
        entered = asyncio.Event()
        async def capture(*args):
            self.assertFalse(args[4])  # marks=False
            entered.set()
            await asyncio.Event().wait()
        self.outer.snapshots = SimpleNamespace(take=AsyncMock(side_effect=capture))
        self.outer.elements.read = AsyncMock(side_effect=AssertionError("must not walk a busy page"))
        with patch("partyline.screen_failure_snapshot.deny_unless"), \
                patch("partyline.screen_failure_snapshot.asyncio.timeout",
                      side_effect=lambda delay: Deadline(self.clock, delay)):
            task = asyncio.create_task(attach(SimpleNamespace(db=None), self.outer, None,
                                             self.principal, "line", GRANT, result))
            await entered.wait()
            self.clock.advance(2)
            await task
        self.assertEqual(2, self.clock.now)
        self.assertIn("picture took too long", result["screenshot"]["error"])
        self.outer.elements.read.assert_not_awaited()

    async def test_identity_is_checked_again_after_hit_test_and_box_lookup(self):
        await self.read()
        def move(message):
            if message["method"] == "DOM.getBoxModel":
                self.f.socket.states[2]["bounds"] = [50, 0, 150, 40]
        self.f.socket.hook = move
        self.assertEqual("target_changed", (await self.invoke())["reason"])
        self.assertFalse(any(m["method"].startswith("Input.") for m in self.f.socket.calls))

    async def test_old_helper_keeps_its_counter_barrier(self):
        original = self.exchange
        async def legacy(*args, **kwargs):
            result = await original(*args, **kwargs)
            result.pop("action_identity_supported", None)
            return result
        self.elements.exchange = legacy
        await self.read()
        self.elements.changed("g")
        self.f.socket.event()
        await checkpoint()
        self.f.socket.hook = self.churn
        result = await self.invoke()
        self.assertEqual("target_changed", result["reason"])
        self.assertGreater(self.captures, 1)

    async def test_unreadable_window_has_a_distinct_failure(self):
        await self.read()
        self.elements.snapshots["g"].action_identity = False
        self.elements.changed("g")
        self.elements.exchange = AsyncMock(return_value={"elements_unavailable": "unreadable"})
        result = await self.invoke()
        self.assertIn("could not refresh", result["error"])
        self.assertNotIn("reason", result)


class StateIdentityRecipe(unittest.TestCase):
    def test_same_document_is_stable_and_adoption_changes_the_live_proof(self):
        script = r"""
const crypto=require('node:crypto').webcrypto;
const document=()=>({activeElement:null});
const e={ownerDocument:document(),tagName:'BUTTON',isConnected:true,tabIndex:0,
  getBoundingClientRect:()=>({left:1,top:2,right:11,bottom:12}),
  closest:()=>null,matches:()=>false,getAttribute:()=>null,getRootNode(){return this.ownerDocument;}};
const state=RECIPE;
const first=state.call(e), same=state.call(e);
e.ownerDocument=document();
const adopted=state.call(e);
e.isConnected=false;
console.log(JSON.stringify({first,same,adopted,detached:state.call(e)}));
""".replace("RECIPE", STATE)
        output = subprocess.run(["node", "-e", script], capture_output=True, text=True, check=True)
        result = json.loads(output.stdout)
        self.assertEqual(result["first"]["document_identity"], result["same"]["document_identity"])
        self.assertNotEqual(result["first"]["document_identity"], result["adopted"]["document_identity"])
        self.assertEqual([1, 2, 11, 12], result["first"]["bounds"])
        self.assertTrue(result["adopted"]["connected"])
        self.assertFalse(result["detached"]["connected"])
