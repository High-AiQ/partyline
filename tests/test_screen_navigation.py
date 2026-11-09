"""A 5,000-node page captured through cursors, stored on the server and explored in small answers."""
import asyncio
import json
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from partyline.mcp.render import render
from partyline.screen_elements import ElementsHub
from partyline_helper.uia_access import WindowAccess
from partyline_helper.uia_action_worker import run_action
from partyline_helper.uia_snapshot import snapshot
from tests.test_uia_page_content import Browser

GRANT = {"hwnd": 10, "pid": 42, "title": "KDP Bookshelf", "process": "chrome.exe"}


def rows(lines):
    """The element lines of an answer, without the `in:` ancestor lines between them."""
    return [line for line in lines.split("\n") if not line.startswith("in: ")]


class Page(Browser):
    """A browser fake that can also be acted on; links hang off a deep section, a pager beside them."""

    def __init__(self, links=5000):
        super().__init__(links=links, chrome=20, latency=0)
        section = self.document
        while (kids := self.nodes[section]["children"]) and self.nodes[kids[0]]["type"] == "Group":
            section = kids[0]
        self.pager = self.add("List", "Pagination", section, patterns=[])
        for number in range(1, 4):
            item = self.add("ListItem", f"Page {number}", self.pager, patterns=[])
            self.add("Hyperlink", str(number), item)
        self.add("Text", "Showing 10 of 4,982 books", section, patterns=[])
        self.calls = []

    def state(self, node, props):
        """Pattern state is read for an action target only."""

    def read_only(self, node):
        return False

    def foreground(self):
        return 5

    def action_call(self, node, action, arg=None):
        return lambda: self.calls.append((self.nodes[node]["name"], action))


class PageCase(unittest.IsolatedAsyncioTestCase):
    LINKS = 5000
    PART = 2000  # elements per helper part, as MAX_ELEMENTS

    async def asyncSetUp(self):
        self.page = Page(self.LINKS)
        self.parts = []
        self.now = [0.0]

        def reader(hwnd, frame, state, deep):
            self.parts.append(state)
            part = snapshot(self.page, frame, clock=self.page.clock, state=state, limit=self.PART)
            part = json.loads(json.dumps(part))
            if state is None:
                self.first_ids = {item["id"] for item in part["elements"]}
            return part

        session = SimpleNamespace(status=SimpleNamespace(window_title=None, changed=Mock()),
                                  tools=SimpleNamespace(audit=SimpleNamespace(append=Mock())),
                                  share=None, accepted=False, last_uia_frame=None)
        self.access = WindowAccess(session, picker=lambda: GRANT, list_windows=lambda: [GRANT],
                                   reader=reader, platform="win32")
        await self.access.choose()
        self.messages = asyncio.Queue()
        socket = SimpleNamespace(send_json=self.messages.put)
        self.device = {"id": "d", "conv_id": "line", "name": "PC", "socket": socket}
        self.hub = ElementsHub(SimpleNamespace(devices={"d": self.device}), clock=lambda: self.now[0])
        self.principal = SimpleNamespace(kind="machine", attachment_id="a")
        grant = {"id": "g", "title": GRANT["title"], "process": GRANT["process"]}
        for target in ("partyline.screen_elements.resolve_window", ):
            patcher = patch(target, return_value=(grant, self.device))
            patcher.start()
            self.addCleanup(patcher.stop)
        patcher = patch("partyline.screen_elements.require_window")
        patcher.start()
        self.addCleanup(patcher.stop)
        self.helper = asyncio.create_task(self.serve())
        self.addCleanup(self.helper.cancel)

    async def serve(self):
        while True:
            request = await self.messages.get()
            result = await self.access.snapshot({"cursor": request.get("cursor")})
            self.hub.receive(self.device, {"request_id": request["request_id"],
                                           **json.loads(json.dumps(result))})

    async def ask(self, **options):
        result = await self.hub.read(self.principal, options=options)
        self.assertLessEqual(len(render(result, "http://x")), 4096, options)
        return result

class NavigationTests(PageCase):
    async def test_a_five_thousand_node_page_is_captured_whole_and_summarised_in_a_few_lines(self):
        summary = await self.ask()
        total = len(snapshot(self.page, clock=self.page.clock, limit=100_000)["elements"])
        self.assertGreater(total, 5000)
        self.assertEqual(total, summary["nodes"])
        self.assertGreater(len(self.parts), 2)  # several cursor parts, one helper read each
        self.assertLess(len(self.first_ids), total)
        self.assertNotIn("partial", summary)
        self.assertLess(len(summary["outline"]), 40)
        self.assertIn("Hyperlink", summary["types"])
        self.assertEqual("KDP Bookshelf", summary["window_title"])
        self.assertIn("Document", "\n".join(summary["outline"]))

    async def test_ls_find_and_text_use_the_stored_snapshot_without_another_helper_read(self):
        summary = await self.ask()
        reads = len(self.parts)
        pager = rows((await self.ask(query="Pagination"))["lines"])[0].split(" ")[0]
        listing = await self.ask(root=pager, depth=2)
        self.assertEqual(6, listing["total"])
        self.assertIn('Hyperlink "2"', listing["lines"])
        self.assertIn("(1 children, 1 in all)", listing["lines"])
        found = await self.ask(query="2", control_type="Hyperlink", root=pager)
        self.assertEqual(1, found["total"])
        self.assertIn("> List Pagination > ListItem Page 2\n", found["lines"])
        text = await self.ask(text=True, query="showing", context=0)
        self.assertEqual(["Showing 10 of 4,982 books"],
                         [line.split(": ", 1)[1] for line in text["lines"].split("\n")])
        self.assertEqual(reads, len(self.parts))
        self.assertTrue(self.messages.empty())
        self.assertEqual(summary["snapshot_id"], found["snapshot_id"])

    async def test_a_deep_node_found_by_query_is_a_valid_action_target(self):
        await self.ask()
        found = await self.ask(query="Link 4321", control_type="Hyperlink", bounds=True)
        self.assertEqual(1, found["total"])
        ident = rows(found["lines"])[0].split(" ")[0]
        helper = self.hub.snapshots["g"].nodes[ident].helper
        self.assertNotIn(helper, self.first_ids)  # it came from a later cursor part
        self.assertIn("[invoke]", found["lines"])
        self.assertIn("@0,0,10,10", found["lines"])
        self.assertIn("in: Group Section 5 > Group Section 6 > Group Section 7\n", found["lines"])
        generation = self.access.gate.grant()
        access = SimpleNamespace(gate=self.access.gate, list_windows=lambda: [GRANT], paths=self.access.paths)
        result = run_action(access, GRANT, generation, {"element_id": helper, "action": "invoke"},
                            factory=lambda _: self.page)
        self.assertEqual("completed", result["status"])
        self.assertEqual([("Link 4321", "invoke")], self.page.calls)

    async def test_a_long_name_travels_through_the_real_helper_and_id_reads_it_whole(self):
        self.page.add("ListItem", "Title " + "z" * 700, self.page.pager, patterns=[])
        await self.ask()
        found = await self.ask(query="^Title z")
        ident = rows(found["lines"])[0].split(" ")[0]
        self.assertIn("…", found["lines"])
        whole = await self.ask(id=ident)
        self.assertIn("Title " + "z" * 700 + '"', whole["lines"])

    async def test_text_reads_in_order_and_pages(self):
        await self.ask()
        first = await self.ask(text=True)
        self.assertIn("more", first)
        self.assertTrue(first["lines"].startswith("0: "))
        second = await self.ask(text=True, offset=first["next_offset"])
        self.assertTrue(second["lines"].startswith(f"{first['next_offset']}: "))

    async def test_a_capture_cap_leaves_a_cursor_and_more_continues_it(self):
        with patch("partyline.screen_elements.MAX_NODES", 1500):
            partial = await self.ask()
            self.assertIn("more=true", partial["partial"])
            self.assertLess(partial["nodes"], 5200)
            more = await self.ask(more=True)
            while "partial" in more:
                more = await self.ask(more=True)
        self.assertGreater(more["nodes"], 5000)
        self.assertEqual(partial["snapshot_id"], more["snapshot_id"])
        found = await self.ask(query="Link 4999")
        self.assertEqual(1, found["total"])

    async def test_unknown_root_is_reported(self):
        await self.ask()
        self.assertIn("unknown element", (await self.ask(root="nope"))["error"])


class LifecycleTests(PageCase):
    """Refresh and expiry need several captures, so a small page in small parts keeps them fast."""
    LINKS = 600
    PART = 400

    async def test_refresh_starts_a_new_snapshot_and_ends_the_old_cursor(self):
        first = await self.ask()
        with patch("partyline.screen_elements.MAX_NODES", 300):
            await self.ask(refresh=True)
        old = next(iter(self.access.walks))
        second = await self.ask(refresh=True)
        self.assertNotEqual(first["snapshot_id"], second["snapshot_id"])
        self.assertEqual("cursor expired; start a new snapshot",
                         (await self.access.snapshot({"cursor": old}))["elements_unavailable"])

    async def test_an_old_snapshot_expires(self):
        first = await self.ask()
        self.now[0] = 601
        second = await self.ask()
        self.assertNotEqual(first["snapshot_id"], second["snapshot_id"])


class PagingTests(PageCase):
    LINKS = 1200

    async def test_long_answers_page_through_offset_and_stay_small(self):
        await self.ask()
        seen, offset, answers = [], 0, 0
        while True:
            answer = await self.ask(query="Link", offset=offset)
            seen += [line.split(" ")[0] for line in rows(answer["lines"])]
            answers += 1
            if "more" not in answer:
                break
            self.assertEqual(answer["total"] - offset - len(rows(answer["lines"])), answer["more"])
            offset = answer["next_offset"]
        self.assertEqual(1200, len(set(seen)))
        self.assertEqual(1200, answer["total"])
        self.assertGreater(answers, 10)
