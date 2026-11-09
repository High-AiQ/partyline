"""A browser-shaped window read in parts: every node reachable, the page deep inside; fake clock."""
import unittest
from types import SimpleNamespace

from partyline_helper.uia_access import WindowAccess
from partyline_helper.uia_action import by_path, find
from partyline_helper.uia_identity import element_id
from partyline_helper.uia_snapshot import snapshot

CALL = .012  # seconds one Chrome UIA call takes


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


def read_all(browser, **caps):
    """Follow state from part to part, the way the cursor does; return every part."""
    parts, state = [], None
    while True:
        parts.append(snapshot(browser, clock=browser.clock, state=state, **caps))
        state = parts[-1].get("state")
        if not state:
            return parts


class PageContentTests(unittest.TestCase):
    def test_tree_order_with_window_first_and_parent_links(self):
        browser = Browser(chrome=3, links=3)
        result = snapshot(browser, clock=browser.clock)
        self.assertEqual("Browser", names(result)[0])
        order = [result["paths"][item["id"]] for item in result["elements"]]
        self.assertEqual(sorted(order), order)
        self.assertLess(names(result).index("Address"), names(result).index("Page"))
        by_name = {item["name"]: item for item in result["elements"]}
        self.assertNotIn("parent", by_name["Browser"])
        self.assertEqual(by_name["Browser"]["id"], by_name["Title"]["parent"])
        self.assertEqual(by_name["Page"]["id"], by_name["Section 0"]["parent"])

    def test_unnamed_empty_wrappers_cost_no_elements_but_keep_their_paths(self):
        browser = Browser(links=2, chrome=1, wrappers=4)
        result = snapshot(browser, clock=browser.clock)
        self.assertNotIn("", names(result))
        self.assertFalse(result["truncated"])
        document = next(item for item in result["elements"] if item["name"] == "Page")
        self.assertGreater(len(result["paths"][document["id"]]), 8)

    def test_a_walk_in_parts_reaches_every_node_once_and_the_page_is_not_cut_off(self):
        browser = Browser(links=500, chrome=300, latency=0)
        parts = read_all(browser, limit=100)
        found = [item["id"] for part in parts for item in part["elements"]]
        self.assertEqual(len(found), len(set(found)))
        whole = snapshot(browser, clock=browser.clock, limit=10_000)
        self.assertEqual([item["id"] for item in whole["elements"]], found)
        self.assertGreater(len(parts), 8)
        self.assertIn("Link 499", [item["name"] for part in parts for item in part["elements"]])
        self.assertFalse(parts[-1]["truncated"])
        self.assertTrue(all(part["truncated"] for part in parts[:-1]))

    def test_every_cap_continues_and_text_is_capped(self):
        browser = Browser(links=1, chrome=1, latency=0)
        browser.nodes[browser.document]["name"] = "x" * 500
        result = snapshot(browser, clock=browser.clock)
        self.assertTrue(all(len(item["name"]) <= 160 for item in result["elements"]))
        tall = Browser(links=0, chrome=0, latency=0)
        node = 0
        for _ in range(1200):
            node = tall.add("Pane", "", node, patterns=[])
        tall.add("Button", "Deep button", node)
        parts = read_all(tall, max_visits=500)
        self.assertGreater(len(parts), 2)
        self.assertLessEqual(max(len(tall.reads) for _ in parts), 3000)
        self.assertIn("Deep button", [item["name"] for part in parts for item in part["elements"]])

    def test_a_small_window_is_one_untruncated_part(self):
        browser = Browser(links=2, chrome=2, latency=0)
        result = snapshot(browser, clock=browser.clock)
        self.assertFalse(result["truncated"])
        self.assertNotIn("truncation", result)
        self.assertNotIn("state", result)

    def test_a_changed_tree_between_parts_skips_what_is_gone(self):
        browser = Browser(links=20, chrome=2, latency=0)
        first = snapshot(browser, clock=browser.clock, limit=10)
        browser.nodes[browser.document]["children"] = []
        rest = snapshot(browser, clock=browser.clock, state=first["state"])
        self.assertFalse(rest["truncated"])
        self.assertNotIn("Link 19", names(rest))


class PathTargetTests(unittest.TestCase):
    def test_page_elements_are_found_by_path_beyond_the_search_cap(self):
        browser = Browser(chrome=1500, latency=0)
        result = snapshot(browser, clock=browser.clock, limit=10_000)
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
