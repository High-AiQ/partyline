"""Targeted CDP renderer coverage for a generic comparison grid."""
import asyncio
from pathlib import Path
from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock, Mock, patch

from playwright.async_api import async_playwright

from partyline.screen_tree import Snapshot
from partyline.screen_tree_views import find
from partyline_helper.cdp_actions import act
from partyline_helper.cdp_control_details import CONTROL_DETAILS
from partyline_helper.cdp_page import Page
from partyline_helper.cdp_transport import CDPError
from tests.cdp_fakes import Fixture
from tests.test_cdp_hidden_files import dom

FIXTURE = Path(__file__).parent / "fixtures" / "cdp_custom_controls.html"


class Protocol(IsolatedAsyncioTestCase):
    async def test_roleless_controls_share_a_batch_within_each_renderer_document(self):
        fixture = Fixture()
        self.addAsyncCleanup(fixture.close)
        socket = fixture.socket
        socket.document = dom("#document", 1, [
            dom("DIV", 4, tabindex="0"), dom("DIV", 5, **{"aria-controls": "options"}),
            dom("DIV", 6, tabindex="0"),
        ])
        socket.nodes.append(dict(nodeId="5", backendDOMNodeId=5, parentId="1", role={"value": "generic"}))
        socket.states.update({
            4: dict(tag="DIV", short_text="One", row_label="Measure A", column_header="Period A"),
            5: dict(tag="DIV", short_text="Two", popup_hint="listbox"),
            6: dict(tag="DIV", short_text="Three", document_identity="another document"),
        })
        elements = (await fixture.read())["elements"]
        batches = [m["params"] for m in socket.calls
                   if m["params"].get("functionDeclaration") == CONTROL_DETAILS]
        self.assertEqual({frozenset([p["objectId"], *(a["objectId"] for a in p["arguments"])])
                          for p in batches}, {frozenset(["4", "5"]), frozenset(["6"])})
        tree = Snapshot("fixture", 0)
        tree.add(elements)
        answer = find(tree, "=Period A", "Group", None, 0, False)
        self.assertEqual(answer["total"], 1)
        self.assertIn('row="Measure A" column="Period A"', answer["lines"][-1])
        self.assertIn('popup="listbox"', tree.line(next(n for n in tree.nodes.values() if n.name == "Two")))
        original = socket.response

        def response(message):
            if message["params"].get("functionDeclaration") == CONTROL_DETAILS:
                return {"exceptionDetails": {"text": "Uncaught"}}
            return original(message)

        fixture.access.reader = Mock()
        with (patch.object(socket, "response", response),
              self.assertRaisesRegex(CDPError, "control observation")):
            await fixture.read()
        fixture.access.reader.assert_not_called()


class Renderer:
    def __init__(self, session):
        self.session = session
        self.listeners = set()
        self.calls = []

    async def call(self, method, params, session, guard):
        guard()
        self.calls.append((method, params or {}))
        result = await self.session.send(method, params or {})
        guard()
        return result


class ChromiumFixture(IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        playwright = await self.enterAsyncContext(async_playwright())
        if not Path(playwright.chromium.executable_path).is_file():
            self.skipTest("Playwright Chromium is not installed")
        browser = await playwright.chromium.launch()
        self.addAsyncCleanup(browser.close)
        self.tab = await browser.new_page()
        await self.tab.goto(FIXTURE.resolve().as_uri())
        self.renderer = Renderer(await self.tab.context.new_cdp_session(self.tab))
        access = SimpleNamespace(
            grant={}, gate=SimpleNamespace(generation=0, revoked=asyncio.Event()),
            session=SimpleNamespace(window_grant_id="fixture"), event_status=lambda: {"event_counter": 0},
            forget=lambda: None, keep=lambda *args: None,
        )
        self.page = Page(self.renderer, access, "fixture", "fixture", lambda: None)
        await self.page.initialize()
        self.page.quiet.wait = AsyncMock(return_value="quiet")

    async def test_snapshot_batches_visible_labels_and_context_and_preserves_named_identity(self):
        capture = await self.page.snapshot()
        elements = capture["elements"]
        controls = [item for item in elements if "row_label" in item]
        self.assertEqual({(item["name"], item["row_label"], item.get("column_header"), item.get("popup_hint"))
                          for item in controls}, {
            ("(none)", "Temperature", "Period A", None),
            ("(none)", "Rainfall", "Actual", "dialog"),
            ("Choose now", "Humidity", "Morning", "popover"),
            ("(none)", "Humidity", "Afternoon", None),
            ("(none)", "Air pressure", "Afternoon", None),
            ("(none)", "Water level", "Reading", None),
        })
        self.assertTrue(all("invoke" in item["actions"] for item in controls))
        batches = [p for _, p in self.renderer.calls if p.get("functionDeclaration") == CONTROL_DETAILS]
        self.assertEqual(len(batches), 1)
        self.assertEqual(len(batches[0]["arguments"]), 6)
        empty = next(item for item in controls if item["row_label"] == "Temperature")
        live = (await self.page.snapshot({"inspect": empty["id"]}))["live"]
        self.assertEqual((live["short_text"], live["row_label"]), ("(none)", "Temperature"))
        tree = Snapshot("fixture", 0)
        tree.add(elements)
        answer = find(tree, "=Temperature", "Group", None, 0, False)
        self.assertIn('row="Temperature" column="Period A"', "\n".join(answer["lines"]))
        named = next(n for n in elements if n["name"] == "Named control")
        explicit = next(n for n in elements if n["control_type"] == "Button")
        self.assertNotIn("row_label", named)
        self.assertNotIn("popup_hint", named)
        self.assertNotIn("row_label", explicit)
        after = (await self.page.snapshot())["elements"]
        self.assertEqual(named, next(n for n in after if n["name"] == named["name"]))
        self.assertEqual(explicit, next(n for n in after if n["id"] == explicit["id"]))

    async def test_transparent_control_stays_discoverable_and_keeps_its_text(self):
        elements = (await self.page.snapshot())["elements"]
        control = next((n for n in elements if n["name"] == "Transparent control"), None)
        self.assertIsNotNone(control)
        self.assertTrue(self.page.nodes[control["id"]]["dom_discovered"])
        self.assertIn("invoke", control["actions"])
        live = (await self.page.snapshot({"inspect": control["id"]}))["live"]
        self.assertFalse(live["hidden"])
        self.assertEqual(live["short_text"], "Transparent control")

    async def test_clear_search_input_uses_trusted_delete_and_reads_back_empty_value(self):
        edit = next(n for n in (await self.page.snapshot())["elements"] if n["control_type"] == "Edit")
        self.assertEqual((edit["name"], edit["value"]), ("Enter a reading", "Warm"))
        self.assertNotIn("row_label", edit)
        await self.tab.evaluate("""() => {
          window.received = [];
          document.querySelector('input').addEventListener('input',
            e => received.push([e.isTrusted, e.inputType, e.target.value]));
        }""")
        result = await act(self.page, {"element_id": edit["id"], "action": "set_value", "value": ""})
        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["element"]["value"], "")
        self.assertEqual(await self.tab.evaluate("received"), [[True, "deleteContentForward", ""]])
        self.assertFalse(any(method == "Input.insertText" for method, _ in self.renderer.calls))
