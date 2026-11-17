"""CDP dispatch barriers, input recipes, continuation and bounded eval edge cases."""
import asyncio
import json
import subprocess
from unittest import IsolatedAsyncioTestCase, TestCase
from unittest.mock import AsyncMock, patch

from partyline_helper.cdp_actions import evaluate
from partyline_helper.cdp_recipes import HIT, SELECT_PLAN
from partyline_helper.cdp_transport import CDPError
from tests.cdp_fakes import Fixture
from tests.screen_helper_fakes import checkpoint


class Commands(IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.f = Fixture()
        self.addAsyncCleanup(self.f.close)
        self.snapshot = await self.f.read()
        self.page = await self.f.chrome.page(self.f.access)
        self.page.quiet.wait = AsyncMock(return_value="quiet")
        self.link, self.select = [n["id"] for n in self.snapshot["elements"][1:]]

    async def test_mouse_keyboard_and_insert_text_are_actual_cdp_input(self):
        result = await self.f.chrome.action(self.f.access, dict(action="invoke", element_id=self.link))
        self.assertEqual(result["status"], "failed")
        result = await self.f.chrome.action(self.f.access,
                                             dict(action="invoke", element_id=self.link, force=True))
        self.assertEqual(result["status"], "completed")
        mouse = [m["params"] for m in self.f.socket.calls if m["method"] == "Input.dispatchMouseEvent"]
        self.assertEqual([m["type"] for m in mouse], ["mousePressed", "mouseReleased"])
        self.assertTrue(all(m["x"] == 50 and m["y"] == 20 for m in mouse))
        self.f.socket.states[3]["tag"] = "INPUT"
        await self.f.chrome.action(self.f.access,
                                   dict(action="set_value", element_id=self.select, value="new"))
        self.assertEqual([m["params"]["text"] for m in self.f.socket.calls
                          if m["method"] == "Input.insertText"], ["new"])
        await self.f.chrome.action(self.f.access, dict(action="press", element_id=self.select, key="enter"))
        keys = [m["params"] for m in self.f.socket.calls if m["method"] == "Input.dispatchKeyEvent"]
        self.assertEqual([m["key"] for m in keys], ["a", "a", "Enter", "Enter"])
        self.assertEqual([m["modifiers"] for m in keys[:2]], [2, 2])
        self.assertTrue(any(m["method"] == "DOM.focus" for m in self.f.socket.calls))

    async def test_select_uses_current_option_popup_and_reports_unchanged_selection(self):
        self.f.socket.options = [dict(label=c, value=c) for c in "ABCD"]
        self.f.socket.states[3].update(selected_index=3, value="D")
        result = await self.f.chrome.action(self.f.access,
            dict(action="select", element_id=self.select, value="B"))
        self.assertEqual(result["element"]["value"], "B")
        keys = [m["params"]["key"] for m in self.f.socket.calls
                if m["method"] == "Input.dispatchKeyEvent" and m["params"]["type"] == "keyDown"]
        self.assertEqual(keys, ["ArrowDown", "ArrowUp", "ArrowUp", "Enter"])
        self.assertEqual(result["trusted_change_events"], 1)
        before = len(self.f.socket.input_events)
        result = await self.f.chrome.action(self.f.access,
            dict(action="select", element_id=self.select, value="B"))
        self.assertFalse(result["value_changed"])
        self.assertEqual(result["events"], "none (already selected)")
        self.assertEqual(len(self.f.socket.input_events), before)

    async def test_select_verifies_the_native_control_after_keyboard_dispatch(self):
        def hook(message):
            if message["method"] == "Input.dispatchKeyEvent":
                self.f.socket.focused = None  # page intercepted the input or replaced its focused control
        self.f.socket.hook = hook
        result = await self.f.chrome.action(self.f.access,
            dict(action="select", element_id=self.select, value="New"))
        self.assertEqual(result["status"], "unconfirmed")
        self.assertIn("not confirmed", result["error"])

    async def test_unsupported_stale_readonly_and_covered_targets_do_not_dispatch_input(self):
        for action, extra in (("window_close", {}), ("select", {}), ("press", {"key": "ctrl+enter"})):
            result = await self.f.chrome.action(self.f.access, dict(action=action,
                                                element_id=self.select, **extra))
            self.assertEqual(result["status"], "failed")
        self.f.socket.states[3]["readonly"] = True
        result = await self.f.chrome.action(self.f.access, dict(action="set_value", element_id=self.select,
                                                              value="no"))
        self.assertEqual(result["status"], "failed")
        self.f.socket.states[2].update(aria_disabled=False, hit=False)
        result = await self.f.chrome.action(self.f.access, dict(action="invoke", element_id=self.link))
        self.assertEqual(result["status"], "failed")
        self.assertFalse(any(m["method"].startswith("Input.") for m in self.f.socket.calls))
        self.assertEqual((await self.f.chrome.action(self.f.access,
            dict(action="invoke", element_id="missing")))["status"], "failed")

    async def test_inspect_and_document_replacement_invalidate_backend_id_identity(self):
        inspected = await self.f.read(inspect=self.link)
        self.assertFalse(inspected["live"]["enabled"])
        self.assertEqual(inspected["live"]["disabled_provenance"], ["aria_disabled"])
        self.f.socket.event("DOM.documentUpdated")
        await checkpoint()
        result = await self.f.read()
        self.assertNotEqual(result["elements"][1]["id"], self.link)
        self.assertIn("error", await self.f.read(inspect=self.link))

    async def test_eval_escapes_quotes_within_budget_and_supports_json(self):
        for value in ('"\\' * 10000, {"answer": 42}, None):
            self.f.socket.eval_value = value
            result = await evaluate(self.page, "expression")
            self.assertLessEqual(len(json.dumps(result, ensure_ascii=False).encode()), 4096)
            if not isinstance(value, str):
                self.assertEqual(result["result"], value)

    async def test_hidden_visibility_keeps_covered_page_live_and_advances_counter(self):
        before = self.f.state.count
        self.f.socket.event("Runtime.bindingCalled", name="__partylineChange", payload="hidden")
        await checkpoint()
        self.assertTrue(self.page.live)
        self.assertGreater(self.f.state.count, before)
        await self.page.call("Runtime.evaluate", {"expression": "0"})

    async def test_close_rejects_pending_calls_and_removes_listeners(self):
        # A fake peer accepts a command but withholds its response; closing is the completion event.
        self.f.socket.send = AsyncMock()
        pending = asyncio.create_task(self.page.call("Runtime.evaluate", {"expression": "0"}))
        await checkpoint()
        await self.f.browser.disconnect()
        with self.assertRaises(CDPError):
            await pending
        self.assertFalse(self.f.browser.listeners)

    async def test_capture_deadline_cancels_cdp_work_without_waiting_real_time(self):
        from partyline_helper.uia_task import WindowTask
        entered = asyncio.Event()
        async def blocked(*args):
            entered.set()
            await asyncio.Event().wait()
        async def deadline(*args):
            await entered.wait()
            raise TimeoutError
        worker = WindowTask(self.f.access.session)
        self.f.chrome.read = blocked
        with patch("partyline_helper.uia_task.asyncio.wait_for", side_effect=deadline):
            await worker._read("deadline")
        await checkpoint()
        self.assertTrue(worker.read_task.cancelled())
        self.f.session.send.assert_awaited_with("window_elements", request_id="deadline",
                                              elements_unavailable="timeout", truncated=True,
                                              timing=self.f.session.send.await_args.kwargs["timing"])
        await worker.close()

    async def test_continuation_and_racing_event(self):
        self.f.socket.nodes = [dict(nodeId=str(n), role={"value": "StaticText"}, name={"value": "x"})
                               for n in range(2001)]
        result = await self.f.read()
        cursor = result["next_cursor"]
        self.assertTrue(result["truncated"])
        rest = await self.f.read(cursor=cursor)
        self.assertEqual(len(rest["elements"]), 1)
        self.assertEqual(result["snapshot_id"], rest["snapshot_id"])
        self.f.socket.event()
        await checkpoint()
        self.assertIn("elements_unavailable", await self.f.read(cursor=cursor))


class SelectRecipe(TestCase):
    def test_select_plan_reads_options_without_changing_value_or_firing_events(self):
        script = r"""
const option=(label,value,disabled=false)=>({label,value,hidden:false,matches:()=>disabled});
const getComputedStyle=()=>({display:'block'});
const options=[option('Disabled','d',true),option('A','a'),option('B','b'),option('C','c')];
const e={tagName:'SELECT',multiple:false,options,selectedIndex:1};
const result=(RECIPE).call(e,'C');
const invalid=(RECIPE).call(e,'Disabled');
console.log(JSON.stringify({result,invalid,selected:e.selectedIndex}));
""".replace("RECIPE", SELECT_PLAN)
        result = subprocess.run(["node", "-e", script], capture_output=True, text=True, check=True)
        value = json.loads(result.stdout)
        self.assertEqual(value["selected"], 1)
        self.assertEqual(value["result"], dict(index=3, current=1, label="C",
                                               direction="ArrowDown", steps=2, popup=True))
        self.assertIn("error", value["invalid"])


class HitRecipe(TestCase):
    def run_hit(self, scene):
        script = r"""
const innerWidth=800, innerHeight=600;
const style={visibility:'visible',display:'block'};
const doc={host:null,defaultView:{getComputedStyle:()=>style}};
const el=(tagName,parentNode=null,attrs={})=>({tagName,parentNode,assignedSlot:null,shadowRoot:null,
  getAttribute:k=>attrs[k]??null,getRootNode(){let n=this;while(n.parentNode)n=n.parentNode;return n;},
  getBoundingClientRect:()=>({x:10,y:10,width:100,height:40}),ownerDocument:doc});
const shadow=(host,mode,hit)=>{const root={host,mode,parentNode:null,elementFromPoint:()=>hit(),
  getRootNode:()=>host.getRootNode()};if(mode==='open')host.shadowRoot=root;return root;};
const body=el('BODY',doc);
const host=el('X-BUTTON',body);
let target, top;
switch(SCENE){
 case 'open-host': {const root=shadow(host,'open',()=>host);target=el('BUTTON',root);top=host;break;}
 case 'open-empty': {const root=shadow(host,'open',()=>null);target=el('BUTTON',root);top=host;break;}
 case 'closed-host': {const root=shadow(host,'closed',()=>null);target=el('BUTTON',root);top=host;break;}
 case 'slotted': {shadow(host,'open',()=>null);target=el('SPAN',host);top=host;break;}
 case 'hidden': {target=el('BUTTON',body);top=target;style.visibility='hidden';break;}
 case 'collapsed': {target=el('BUTTON',body);top=target;style.visibility='collapse';break;}
 case 'display-none': {target=el('BUTTON',body);top=target;style.display='none';break;}
 case 'zero-size': {target=el('BUTTON',body);top=target;
   target.getBoundingClientRect=()=>({x:10,y:10,width:0,height:40});break;}
 case 'offscreen': {target=el('BUTTON',body);top=target;
   target.getBoundingClientRect=()=>({x:900,y:10,width:100,height:40});break;}
 case 'moved': {target=el('BUTTON',body);top=target;
   target.getBoundingClientRect=()=>({x:50.25,y:70.75,width:100,height:40});break;}
 case 'overlay': {target=el('BUTTON',body);top=el('DIV',body,{'aria-label':'Dialog'});break;}
 case 'plain-ancestor': {const wrap=el('DIV',body);target=el('BUTTON',wrap);top=wrap;break;}
}
doc.elementFromPoint=()=>top;
console.log(JSON.stringify((RECIPE).call(target)));
""".replace("RECIPE", HIT).replace("SCENE", json.dumps(scene))
        result = subprocess.run(["node", "-e", script], capture_output=True, text=True, check=True)
        return json.loads(result.stdout)

    def test_a_hit_on_the_targets_own_component_host_counts_as_the_target(self):
        for scene in ("open-host", "open-empty", "closed-host", "slotted"):
            with self.subTest(scene=scene):
                self.assertEqual(self.run_hit(scene), {"hit": True, "x": 60, "y": 30})

    def test_unrelated_overlays_and_plain_ancestors_still_cover_the_target(self):
        self.assertEqual(self.run_hit("overlay"), {"hit": False, "reason": "element is covered"})
        self.assertEqual(self.run_hit("plain-ancestor"), {"hit": False, "reason": "element is covered"})

    def test_live_point_visibility_and_viewport_are_checked(self):
        for scene in ('hidden', 'collapsed', 'display-none', 'zero-size'):
            with self.subTest(scene=scene):
                self.assertEqual(self.run_hit(scene),
                                 {"hit": False, "reason": "element is no longer visible"})
        self.assertEqual(self.run_hit('offscreen'), {"hit": False, "reason": "outside viewport"})
        self.assertEqual(self.run_hit('moved'), {"hit": True, "x": 100.25, "y": 90.75})
