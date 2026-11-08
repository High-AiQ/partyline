"""A browser-shaped window: slow chrome walked first, the page deep inside; fake clock throughout."""
import unittest
from types import SimpleNamespace

from partyline_helper.uia_access import WindowAccess
from partyline_helper.uia_action import by_path, find
from partyline_helper.uia_identity import element_id
from partyline_helper.uia_snapshot import BUDGET, MAX_ELEMENTS, PAGE_SHARE, snapshot

CALL = .012  # seconds one Chrome UIA call takes: an unprioritised depth-first walk reads ~12 nodes in .3 s


class Browser:
    """Window > frame wrappers > title bar, toolbar, bookmarks, then the web page's Document."""

    def __init__(self, links=80, chrome=300, latency=CALL, wrappers=3):
        self.now, self.latency, self.nodes, self.reads = 0.0, latency, [], []
        root = self.add("Window", "Browser")
        frame = self.chain(root, wrappers)
        self.add("TitleBar", "Title", frame, patterns=[])
        bar = self.add("ToolBar", "Toolbar", frame)
        for number in range(chrome):
            self.add("Button", f"Chrome button {number}", bar)
        self.add("Edit", "Address", bar)
        pane = self.chain(frame, wrappers)
        self.document = self.add("Document", "Page", pane)
        region = self.document
        for depth in range(8):
            region = self.add("Group", f"Section {depth}", region)
        for number in range(links):
            self.add("Hyperlink", f"Link {number}", region)
            if number % 10 == 0:
                self.add("Text", f"Heading {number}", region)

    def add(self, kind, name, parent=None, patterns=("Invoke",)):
        self.nodes.append({"type": kind, "name": name, "children": [], "patterns": list(patterns)})
        if parent is not None:
            self.nodes[parent]["children"].append(len(self.nodes) - 1)
        return len(self.nodes) - 1

    def chain(self, parent, count):
        for _ in range(count):
            parent = self.add("Pane", "", parent, patterns=[])
        return parent

    def clock(self):
        return self.now

    def root(self):
        return 0

    def runtime_id(self, node):
        return [node]

    def same_window(self, node):
        return True

    def password(self, node):
        return False

    def current(self):
        return True

    def bounds(self, node):
        return 0, 0, 10, 10

    def children(self, node):
        self.now += self.latency
        return self.nodes[node]["children"]

    def properties(self, node):
        self.now += self.latency
        self.reads.append(node)
        n = self.nodes[node]
        return {"control_type": n["type"], "name": n["name"], "automation_id": "", "enabled": True,
                "focused": False, "offscreen": False, "patterns": n["patterns"]}


def names(result):
    return [item["name"] for item in result["elements"]]


class PageContentTests(unittest.TestCase):
    def test_slow_chrome_does_not_hide_the_page(self):
        browser = Browser(links=30)
        result = snapshot(browser, clock=browser.clock)
        found = names(result)
        self.assertIn("Page", found)
        self.assertEqual(30, sum(name.startswith("Link ") for name in found))
        self.assertEqual(3, sum(name.startswith("Heading ") for name in found))
        self.assertLessEqual(browser.now, BUDGET + 2 * CALL)
        self.assertTrue(result["truncated"])
        self.assertIn("time budget", result["truncation"])
        self.assertIn("page content read", result["truncation"])
        self.assertIn("unread browser chrome subtrees", result["truncation"])
        self.assertNotIn("not reached", result["truncation"])

    def test_a_short_budget_spends_itself_on_the_page_not_the_toolbar(self):
        browser = Browser()
        result = snapshot(browser, clock=browser.clock, budget=.6)
        self.assertIn("Page", names(result))
        self.assertIn("Section 0", names(result))
        self.assertLess(sum(name.startswith("Chrome button") for name in names(result)), 5)

    def test_output_is_in_tree_order_with_window_first(self):
        browser = Browser(chrome=3, links=3)
        result = snapshot(browser, clock=browser.clock)
        self.assertEqual("Browser", names(result)[0])
        order = [result["paths"][item["id"]] for item in result["elements"]]
        self.assertEqual(sorted(order), order)
        self.assertLess(names(result).index("Address"), names(result).index("Page"))

    def test_unnamed_empty_wrappers_cost_no_elements_but_keep_their_paths(self):
        browser = Browser(links=2, chrome=1, wrappers=4)
        result = snapshot(browser, clock=browser.clock)
        self.assertNotIn("", names(result))
        self.assertFalse(result["truncated"])
        document = next(item for item in result["elements"] if item["name"] == "Page")
        self.assertGreater(len(result["paths"][document["id"]]), 8)

    def test_not_reaching_the_page_is_reported(self):
        browser = Browser()
        result = snapshot(browser, clock=browser.clock, budget=4 * CALL)
        self.assertTrue(result["truncated"])
        self.assertIn("page content not reached", result["truncation"])
        self.assertNotIn("Page", names(result))

    def test_caps_hold_and_the_page_leaves_room_for_the_frame(self):
        browser = Browser(links=500, chrome=20, latency=0)
        result = snapshot(browser, clock=browser.clock)
        found = names(result)
        self.assertEqual(MAX_ELEMENTS, len(found))
        self.assertIn("element limit", result["truncation"])
        self.assertIn("Chrome button 19", found)  # spare room goes back to the page, not to waste
        big = Browser(links=500, chrome=300, latency=0)
        found = names(snapshot(big, clock=big.clock))
        self.assertEqual(PAGE_SHARE, len(found) - 1 - found.index("Page"))
        self.assertIn("Chrome button 40", found)

    def test_depth_limit_is_reported_and_text_is_capped(self):
        browser = Browser(links=1, chrome=1, latency=0)
        browser.nodes[browser.document]["name"] = "x" * 500
        result = snapshot(browser, clock=browser.clock, depth_limit=4)
        self.assertTrue(result["truncated"])
        self.assertIn("depth limit", result["truncation"])
        self.assertIn("page content not reached", result["truncation"])
        self.assertTrue(all(len(item["name"]) <= 160 for item in result["elements"]))

    def test_visit_cap_stops_a_tree_of_empty_wrappers(self):
        browser = Browser(links=0, chrome=0, latency=0)
        node = 0
        for _ in range(1200):
            node = browser.add("Pane", "", node, patterns=[])
        result = snapshot(browser, clock=browser.clock, depth_limit=5000)
        self.assertTrue(result["truncated"])
        self.assertLessEqual(len(browser.reads), 1000)

    def test_a_complete_small_window_is_not_truncated(self):
        browser = Browser(links=2, chrome=2, latency=0)
        result = snapshot(browser, clock=browser.clock)
        self.assertFalse(result["truncated"])
        self.assertNotIn("truncation", result)


class PathTargetTests(unittest.TestCase):
    def test_page_elements_are_found_by_path_beyond_the_search_cap(self):
        browser = Browser(chrome=300)
        result = snapshot(browser, clock=browser.clock)
        link = next(item for item in result["elements"] if item["name"] == "Link 5")
        path = result["paths"][link["id"]]
        node = by_path(browser, link["id"], path)
        self.assertEqual("Link 5", browser.nodes[node]["name"])
        self.assertEqual(node, find(browser, link["id"], path))
        self.assertIsNone(find(browser, link["id"]))  # the old bounded search cannot reach it

    def test_a_changed_tree_is_refused(self):
        browser = Browser(chrome=3)
        target = element_id(browser, 5, [0, 0, 0])
        self.assertIsNone(by_path(browser, target, [0, 99]))
        self.assertIsNone(by_path(browser, target, [0, 0, 0]))
        browser.same_window = lambda node: node != 0
        self.assertIsNone(by_path(browser, target, [0]))
        browser.same_window = lambda node: node == 0
        self.assertIsNone(by_path(browser, element_id(browser, 1, [0]), [0]))


class AccessPathTests(unittest.IsolatedAsyncioTestCase):
    async def test_paths_stay_local_and_are_cleared_with_the_snapshot(self):
        grant = {"hwnd": 10, "pid": 42, "title": "Browser", "process": "chrome.exe"}
        session = SimpleNamespace(status=SimpleNamespace(window_title=None, changed=lambda: None),
                                  tools=SimpleNamespace(audit=SimpleNamespace(append=lambda *a: None)),
                                  share=None, accepted=False, last_uia_frame=None)
        def reader(*args):
            return {"elements": [{"id": "a"}], "paths": {"a": [0, 2]}, "snapshot_id": "s"}
        access = WindowAccess(session, picker=lambda: grant, list_windows=lambda: [grant], reader=reader,
                              platform="win32")
        await access.choose()
        result = await access.snapshot()
        self.assertNotIn("paths", result)
        self.assertEqual({"a": [0, 2]}, access.paths)
        access.revoke()
        self.assertEqual({}, access.paths)
