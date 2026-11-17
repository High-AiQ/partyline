"""Approved Chrome discovery, mapping, normalization and real CDP transport with no real-time waits."""
import asyncio
import json
from pathlib import Path
import tempfile
from unittest import IsolatedAsyncioTestCase, TestCase
from unittest.mock import AsyncMock

from partyline.screen_tree import Snapshot
from partyline.screen_tree_answer import answer, size
from partyline_helper.cdp_actions import evaluate
from partyline_helper.cdp_recipes import HIT, STATE, normalize
from partyline_helper.cdp_transport import BrowserConnection, CDPError, discover
from partyline_helper.uia_task import WindowTask
from tests.cdp_fakes import Fixture, Socket


class Discovery(TestCase):
    def test_discovery_validates_file_without_profile_launch(self):
        with tempfile.TemporaryDirectory() as root:
            self.assertIsNone(discover(root))
            path = Path(root) / "DevToolsActivePort"
            for content in ("", "9222", "0\n/devtools/browser/a", "65536\n/devtools/browser/a",
                            "9222\n//evil", "9222\n/devtools/browser/a?secret"):
                path.write_text(content)
                self.assertIsNone(discover(root))
            path.write_text("9222\n/devtools/browser/abc-123\n")
            self.assertEqual(discover(root), "ws://127.0.0.1:9222/devtools/browser/abc-123")

    def test_provenance_and_redaction(self):
        node = dict(role={"value": "textbox"}, name={"value": "Secret"}, value={"value": "hidden"},
                    backendDOMNodeId=2, properties=[dict(name="disabled", value={"value": True})])
        item = normalize(node, "id", None, dict(password=True, readonly=True, inert=True))
        self.assertNotIn("value", item)
        self.assertNotIn("set_value", item["actions"])
        self.assertEqual(item["disabled_provenance"], ["inert", "AX.disabled"])
        mixed = normalize(dict(role={"value": "checkbox"}, backendDOMNodeId=1), "id", None,
                          dict(checked="mixed", selected=True))
        self.assertEqual(mixed["toggle"], 2)
        self.assertTrue(mixed["selected"])


class CDPTests(IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.f = Fixture()
        self.addAsyncCleanup(self.f.close)

    async def test_connection_states_and_one_browser_connection(self):
        states = []
        socket = Socket()
        connect = AsyncMock(return_value=socket)
        browser = BrowserConnection(lambda s, d: states.append(s), lambda: None, connect)
        self.assertFalse(await browser.ensure())
        self.assertEqual(browser.state, "not_enabled")
        self.assertEqual(states, [])  # hello already carries the initial state
        browser.discovery = lambda: "ws://fake"
        self.assertTrue(await browser.ensure())
        self.assertTrue(await browser.ensure())
        self.assertEqual(states[-2:], ["awaiting_approval", "connected"])
        self.assertEqual(connect.await_count, 1)
        await browser.close()
        self.assertTrue(socket.closed)
        self.assertFalse(await browser.ensure())
        refused = BrowserConnection(connector=AsyncMock(side_effect=OSError), discovery=lambda: "ws://fake")
        self.assertFalse(await refused.ensure())
        self.assertEqual(refused.state, "refused")
        self.assertFalse(await refused.ensure())
        await refused.close()

    async def test_late_approval_after_helper_exit_closes_without_any_command(self):
        socket = Socket()
        accepted = asyncio.get_running_loop().create_future()
        entered = asyncio.Event()
        async def connect(*args, **kwargs):
            entered.set()
            return await accepted
        browser = BrowserConnection(connector=connect, discovery=lambda: "ws://fake")
        task = asyncio.create_task(browser.ensure())
        await entered.wait()
        await browser.close()
        accepted.set_result(socket)
        self.assertFalse(await task)
        self.assertTrue(socket.closed)
        self.assertEqual(socket.calls, [])

    async def test_cancelled_approval_handshake_closes_connection(self):
        socket = Socket()
        entered = asyncio.Event()
        async def send(*args):
            entered.set()
            await asyncio.Event().wait()
        socket.send = send
        browser = BrowserConnection(connector=AsyncMock(return_value=socket), discovery=lambda: "ws://fake")
        task = asyncio.create_task(browser.ensure())
        await entered.wait()
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        self.assertTrue(socket.closed)
        self.assertEqual(browser.state, "refused")
        self.assertFalse(browser.pending)
        await browser.close()

    async def test_unique_mapping_excludes_second_chrome_window(self):
        result = await self.f.read()
        self.assertEqual(result["source"], "cdp")
        attaches = [m["params"]["targetId"] for m in self.f.socket.calls
                    if m["method"] == "Target.attachToTarget"]
        self.assertEqual(attaches, ["a"])
        self.assertNotIn("other", attaches)
        await self.f.read()
        self.assertEqual(self.f.connector.await_count, 1)

    async def test_ambiguous_mapping_refuses_and_uses_uia(self):
        await self.f.browser.ensure()
        self.f.socket.rects[2] = self.f.socket.rects[1]
        self.f.socket.titles["other"] = "Lab"
        worker = WindowTask(self.f.access.session)
        result = await worker.snapshot({}, dict(agent="a", line_id="l"))
        self.assertEqual(result["source"], "uia")
        self.assertIn("ambiguous", result["source_reason"])
        self.assertFalse(any(m["method"] == "Target.attachToTarget" for m in self.f.socket.calls))

    async def test_tab_enumeration_hook_includes_inactive_tabs_and_mapped_hwnd(self):
        await self.f.browser.ensure()
        tabs = await self.f.chrome.tabs(self.f.access)
        self.assertEqual({t["target_id"] for t in tabs}, {"a", "b"})
        self.assertTrue(all(t["hwnd"] == 1 for t in tabs))
        self.assertEqual([t["title"] for t in tabs if t["active"]], ["Lab"])

    async def test_process_mismatch_refuses(self):
        self.f.window["pid"] = self.f.access.grant["pid"] = 99
        self.assertIsNone(await self.f.read())
        self.assertIn("UIA", self.f.chrome.reasons[self.f.access])

    async def test_active_tab_follows_but_old_element_ids_do_not(self):
        before = await self.f.read()
        self.f.socket.visible.update(a=False, b=True)
        self.f.window["title"] = "Background - Google Chrome"
        after = await self.f.read()
        self.assertTrue({i["id"] for i in before["elements"]}.isdisjoint(i["id"] for i in after["elements"]))
        self.assertEqual(self.f.chrome.selected[self.f.access], "b")

    async def test_class_only_link_reports_aria_provenance_and_current_ids_budget(self):
        result = await self.f.read()
        tree = Snapshot(result["snapshot_id"], 0)
        tree.source = result["source"]
        tree.add(result["elements"])
        reply = answer(tree, dict(title="Lab", process="chrome.exe"), dict(query="Manage"))
        self.assertEqual(reply["source"], "cdp")
        self.assertIn("disabled(aria_disabled)", reply["lines"])
        self.assertNotIn("IsEnabled", reply["lines"])
        self.assertLessEqual(size(reply), 4096)
        ids = set(tree.nodes)
        next_tree = Snapshot("next", 1, tree.space)
        next_tree.add((await self.f.read())["elements"])
        self.assertEqual(ids, set(next_tree.nodes))
        self.assertTrue(all(len(ident) == 6 for ident in ids))

    async def test_select_uses_trusted_keyboard_and_never_dispatches_synthetic_events(self):
        result = await self.f.read()
        ident = next(i["id"] for i in result["elements"] if i["control_type"] == "ComboBox")
        page = await self.f.chrome.page(self.f.access)
        page.quiet.wait = AsyncMock(return_value="quiet")
        result = await self.f.chrome.action(self.f.access,
                                             dict(action="select", element_id=ident, value="New"))
        self.assertEqual(result["element"]["value"], "New")
        self.assertEqual(result["settle"], "quiet")
        keys = [m["params"]["key"] for m in self.f.socket.calls
                if m["method"] == "Input.dispatchKeyEvent" and m["params"]["type"] == "keyDown"]
        self.assertEqual(keys, ["ArrowDown", "ArrowDown", "Enter"])
        self.assertEqual(self.f.socket.input_events, [("input", True), ("change", True)])
        recipes = [m["params"]["functionDeclaration"] for m in self.f.socket.calls
                   if m["method"] == "Runtime.callFunctionOn"]
        self.assertFalse(any("dispatchEvent" in recipe or "setter.call" in recipe for recipe in recipes))
        self.assertEqual(result["events"], "trusted keyboard input/change")

    async def test_composed_hit_test_descends_shadow_roots_and_tracks_slot_assignment(self):
        self.assertIn("shadowRoot.elementFromPoint(x,y)", HIT)
        self.assertIn("n.assignedSlot||n.parentNode||(n.host||null)", HIT)
        self.assertNotIn("while(", HIT + STATE)  # every composed walk is bounded
        self.assertIn("a.shadowRoot.activeElement", STATE)
        self.assertIn("composedContains(n,e)", HIT)  # closed-root host / slotted light child

    async def test_reads_never_hit_test_or_read_covering_text(self):
        # Per-node hit tests reading a covering container's text exhausted renderer memory.
        self.assertNotIn("elementFromPoint", STATE)
        self.assertNotIn("innerText", HIT)
        self.assertNotIn("textContent", HIT)
        await self.f.read()
        recipes = [m["params"]["functionDeclaration"] for m in self.f.socket.calls
                   if m["method"] == "Runtime.callFunctionOn"]
        self.assertTrue(recipes)
        self.assertNotIn(HIT, recipes)

    async def test_hit_test_refusal_prevents_a_click_on_covered_shadow_element(self):
        await self.f.read()
        page = await self.f.chrome.page(self.f.access)
        page.quiet.wait = AsyncMock(return_value="quiet")
        self.f.socket.states[2]["hit"] = False  # recipe reports an overlay from another subtree
        self.f.socket.states[2]["aria_disabled"] = False
        ident = next(i["id"] for i in (await page.snapshot())["elements"] if i["control_type"] == "Hyperlink")
        result = await self.f.chrome.action(self.f.access, dict(action="invoke", element_id=ident))
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["error"], "element is covered")
        self.assertFalse(any(m["method"] == "Input.dispatchMouseEvent" for m in self.f.socket.calls))

    async def test_open_shadow_ax_button_is_invokable_with_trusted_mouse_input(self):
        self.f.socket.nodes.append(dict(nodeId="4", parentId="1", backendDOMNodeId=4,
                                        role={"value": "button"}, name={"value": "Shadow action"}))
        self.f.socket.states[4] = dict(tag="BUTTON", hit=True)
        result = await self.f.read()
        button = next(item for item in result["elements"] if item["name"] == "Shadow action")
        action = await self.f.chrome.action(self.f.access, dict(action="invoke", element_id=button["id"]))
        events = [(call["params"]["type"], call["params"]["x"], call["params"]["y"])
                  for call in self.f.socket.calls if call["method"] == "Input.dispatchMouseEvent"]
        self.assertEqual(action["status"], "completed")
        self.assertEqual([event[0] for event in events], ["mousePressed", "mouseReleased"])
        self.assertEqual(events[0][1:], (50, 20))

    async def test_eval_is_bounded_and_audit_has_lengths_without_code(self):
        await self.f.browser.ensure()
        self.f.socket.eval_value = "💻" * 10000
        result = await self.f.chrome.action(self.f.access, dict(type="window_eval", expression="secretCode()",
                                                              agent="caller", line_id="line"))
        self.assertTrue(result["truncated"])
        self.assertLessEqual(size(result), 4096)
        info = self.f.session.tools.audit.append.call_args.args[-1]
        self.assertNotIn("secretCode", info)
        self.assertEqual(json.loads(info), dict(grant="g", line="line", process="caller",
                                               operation="screen_eval", input_length=12))

    async def test_event_during_capture_advances_shared_barrier(self):
        fired = False
        def hook(m):
            nonlocal fired
            if not fired and m["method"] == "Runtime.callFunctionOn":
                fired = True
                self.f.socket.event()
        self.f.socket.hook = hook
        result = await self.f.read()
        self.assertLess(result["captured_event_counter"], result["event_counter"])
        self.assertTrue(result["subscription_live"])
        self.assertEqual(self.f.chrome.status(self.f.access)["event_counter"], result["event_counter"])

    async def test_revocation_mid_command_stops_every_subsequent_cdp_use(self):
        await self.f.read()
        page = await self.f.chrome.page(self.f.access)
        def hook(m):
            if m["method"] == "Runtime.evaluate":
                self.f.access.gate.invalidate()
                self.f.chrome.revoke(self.f.access)
        self.f.socket.hook = hook
        with self.assertRaisesRegex(CDPError, "revoked"):
            await evaluate(page, "doWork()")
        before = len(self.f.socket.calls)
        with self.assertRaises(CDPError):
            await page.call("DOM.focus", {"backendNodeId": 2})
        self.assertFalse(any(m["method"] != "Target.detachFromTarget" for m in self.f.socket.calls[before:]))

    async def test_uia_fallback_when_not_enabled_and_non_chrome(self):
        self.f.browser.discovery = lambda: None
        worker = WindowTask(self.f.access.session)
        result = await worker.snapshot({}, {})
        self.assertEqual(result["source"], "uia")
        self.assertIn("chrome://inspect", result["source_reason"])
        self.f.access.grant["process"] = "editor.exe"
        self.assertIsNone(await self.f.chrome.page(self.f.access))
        result = await self.f.chrome.action(self.f.access, dict(type="window_eval", expression="1"))
        self.assertEqual(result["status"], "failed")
