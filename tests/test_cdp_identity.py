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
from partyline_helper.cdp_recipes import DISPATCH, STATE
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

    async def test_disconnection_and_frame_document_change_refuse_even_with_force(self):
        for change in ({"connected": False},
                       {"document_identity": "new document"}):
            with self.subTest(change=change):
                self.f.socket.states[2] = dict(tag="A", hit=True)
                await self.read()
                self.f.socket.states[2].update(change)
                result = await self.f.chrome.action(self.f.access, dict(action="invoke", force=True,
                    element_id=self.elements.snapshots["g"].nodes[self.ident].helper))
                self.assertEqual(("failed", "target_changed"), (result["status"], result["reason"]))
                detail = "connected=false" if "connected" in change else "document identity"
                self.assertIn(detail, result["error"])
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
                    if message["method"] == "DOM.focus":
                        gone = True  # collected after focus, before the dispatch proof
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
        self.assertEqual("completed", (await self.invoke())["status"])
        self.assert_mouse_point(100, 20)

    def assert_mouse_point(self, x, y):
        events = [m["params"] for m in self.f.socket.calls if m["method"] == "Input.dispatchMouseEvent"]
        self.assertTrue(events)
        self.assertTrue(all((m["x"], m["y"]) == (x, y) for m in events[-2:]))

    async def test_fractional_jitter_and_large_movement_keep_identity_token(self):
        for bounds in ([0.49, 0.1, 100.49, 40.1], [50, 10, 150, 50]):
            with self.subTest(bounds=bounds):
                await self.read()
                token = self.elements.snapshots["g"].nodes[self.ident].cached["action_token"]
                self.f.socket.states[2]["bounds"] = bounds
                result = await self.f.read()
                self.assertEqual(token, result["elements"][1]["action_token"])
                self.assertEqual("completed", (await self.invoke())["status"])
                self.assert_mouse_point((bounds[0] + bounds[2]) / 2, (bounds[1] + bounds[3]) / 2)

    async def test_frame_offset_point_comes_from_proven_backends_live_cdp_box(self):
        self.f.socket.frame_offsets[2] = (200, 120)
        await self.read()
        def move(message):
            if message["method"] == "DOM.focus":
                self.f.socket.states[2]["bounds"] = [50, 10, 150, 50]
        self.f.socket.hook = move
        self.assertEqual("completed", (await self.invoke())["status"])
        self.assert_mouse_point(300, 150)  # frame-local hit-test centre is only (100, 30)
        methods = [m["method"] for m in self.f.socket.calls]
        dispatch = methods.index("Input.dispatchMouseEvent")
        self.assertEqual("DOM.getBoxModel", methods[dispatch - 1])
        self.assertEqual({"backendNodeId": 2}, self.f.socket.calls[dispatch - 1]["params"])

    async def test_viewport_transformed_cdp_quad_is_used_without_local_point_or_extra_scaling(self):
        await self.read()
        # Protocol output already incorporates frame/viewport transforms; it can be a non-axis-aligned quad.
        self.f.socket.box_quads[2] = [220, 140, 320, 160, 300, 200, 200, 180]
        self.assertEqual("completed", (await self.invoke())["status"])
        self.assert_mouse_point(260, 170)

    async def test_unsafe_movement_at_dispatch_refuses_with_specific_reason_and_rounded_bounds(self):
        for reason in ("element is covered", "outside viewport", "element is no longer visible"):
            with self.subTest(reason=reason):
                self.f.socket.hook = None
                self.f.socket.states[2] = dict(tag="A", hit=True)
                await self.read()
                def cover(message, reason=reason):
                    if (message["method"] == "Runtime.callFunctionOn"
                            and message["params"]["functionDeclaration"] == DISPATCH):
                        self.f.socket.states[2].update(hit=False, reason=reason,
                                                      bounds=[50.1, 0.2, 150.1, 40.2])
                self.f.socket.hook = cover
                result = await self.invoke()
                self.assertEqual("failed", result["status"])
                self.assertIn(reason, result["error"])
                self.assertIn("bounds [0, 0, 100, 40] → [50, 0, 150, 40]", result["error"])
        self.assertFalse(any(m["method"].startswith("Input.") for m in self.f.socket.calls))

    async def test_coordinate_input_after_element_action_keeps_its_explicit_point(self):
        await self.read()
        self.assertEqual("completed", (await self.invoke())["status"])
        page = self.f.chrome.pages[self.f.access]["a"]
        self.assertIsNone(page.action_proof)
        await page.call("Input.dispatchMouseEvent", {"type": "mouseMoved", "x": 250, "y": 80})
        self.assertEqual({"type": "mouseMoved", "x": 250, "y": 80}, self.f.socket.calls[-1]["params"])

    async def test_helper_recapture_accepts_same_nodes_new_bounds(self):
        await self.read()
        self.f.socket.states[2]["bounds"] = [50, 0, 150, 40]
        await self.f.read()  # helper cache advanced, but the server still holds the original capture
        self.assertEqual("completed", (await self.invoke())["status"])
        self.assert_mouse_point(100, 20)

    async def test_recapture_while_waiting_for_window_lock_refuses_changed_document(self):
        await self.read()
        locked = self.elements.locked
        @asynccontextmanager
        async def changed(grant_id):
            async with locked(grant_id):
                self.f.socket.states[2]["document_identity"] = "new document"
                result = await self.f.read()
                tree = self.elements.snapshots["g"]
                tree.nodes[self.ident].cached["action_token"] = result["elements"][1]["action_token"]
                yield
        self.elements.locked = changed
        result = await self.invoke()
        self.assertEqual("target_changed", result["reason"])
        self.assertIn("document identity token changed", result["error"])
        self.assertFalse(any(m["method"].startswith("Input.") for m in self.f.socket.calls))

    async def test_related_mutation_that_moves_same_target_uses_live_point(self):
        for backend in (1, 2, 4):
            with self.subTest(backend=backend):
                self.f.socket.states[2].pop("bounds", None)
                await self.read()
                self.f.socket.event("DOM.attributeModified", nodeId=backend, name="class", value="changed")
                self.f.socket.states[2]["bounds"] = [50, 0, 150, 40]
                self.assertEqual("completed", (await self.invoke())["status"])
                self.assert_mouse_point(100, 20)

    async def test_document_epoch_change_and_lost_cdp_never_fall_back_to_uia(self):
        await self.read()
        page = self.f.chrome.pages[self.f.access]["a"]
        page.epoch += 1
        result = await self.invoke()
        self.assertEqual("target_changed", result["reason"])
        self.assertIn("page epoch 0 → 1", result["error"])
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

    async def test_movement_at_dispatch_observation_uses_live_point(self):
        await self.read()
        def move(message):
            if (message["method"] == "Runtime.callFunctionOn"
                    and message["params"]["functionDeclaration"] == DISPATCH):
                self.f.socket.states[2]["bounds"] = [50, 0, 150, 40]
        self.f.socket.hook = move
        self.assertEqual("completed", (await self.invoke())["status"])
        self.assert_mouse_point(100, 20)

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
const innerWidth=800,innerHeight=600;
const document=()=>({activeElement:null,elementFromPoint:()=>e,
  defaultView:{getComputedStyle:()=>({visibility:'visible',display:'block'})}});
const e={ownerDocument:document(),tagName:'BUTTON',isConnected:true,tabIndex:0,
  getBoundingClientRect:()=>({left:1,top:2,right:11,bottom:12,x:1,y:2,width:10,height:10}),
  closest:()=>null,matches:()=>false,getAttribute:()=>null,getRootNode(){return this.ownerDocument;}};
const state=RECIPE;
const first=state.call(e), same=state.call(e), dispatch=(DISPATCH_RECIPE).call(e);
e.ownerDocument=document();
const adopted=state.call(e);
e.isConnected=false;
console.log(JSON.stringify({first,same,adopted,dispatch,detached:state.call(e)}));
""".replace("DISPATCH_RECIPE", DISPATCH).replace("RECIPE", STATE)
        output = subprocess.run(["node", "-e", script], capture_output=True, text=True, check=True)
        result = json.loads(output.stdout)
        self.assertEqual(result["first"]["document_identity"], result["same"]["document_identity"])
        self.assertNotEqual(result["first"]["document_identity"], result["adopted"]["document_identity"])
        self.assertEqual([1, 2, 11, 12], result["first"]["bounds"])
        self.assertEqual((True, 6, 7), tuple(result["dispatch"][key] for key in ("hit", "x", "y")))
        self.assertEqual(result["first"]["document_identity"], result["dispatch"]["document_identity"])
        self.assertTrue(result["adopted"]["connected"])
        self.assertFalse(result["detached"]["connected"])
