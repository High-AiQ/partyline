"""The stored window tree, its small answers, and the hub's capture limits."""
import asyncio
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from fastapi import HTTPException

from partyline.mcp.render import render
from partyline.mcp.tools_screen import elements_query, screen_elements_tool
from partyline.screen_elements import MAX_SNAPSHOTS, ElementsHub
from partyline.screen_tree import Snapshot, fit
from partyline.screen_tree_answer import answer
from partyline.screen_tree_views import find, listing, summary, text, text_lines


def tree(*rows):
    result = Snapshot("snap", 0)
    result.add([dict(zip(("id", "parent", "control_type", "name"), row, strict=True)) for row in rows])
    return result


SAMPLE = [("w", None, "Window", "App"), ("t", "w", "Text", "Hello  \"world\"\n"), ("b", "w", "Button", "OK"),
          ("d", "w", "Document", "Page"), ("l", "d", "List", "Nav"), ("a", "l", "Hyperlink", "Alpha"),
          ("c", "l", "Hyperlink", "Beta")]


class TreeTests(unittest.TestCase):
    def test_lines_are_compact_and_single_line(self):
        item = {"id": "x", "control_type": "CheckBox", "name": 'say "hi"\nnow', "value": "v", "toggle": 1,
                "actions": ["toggle"], "enabled": False, "offscreen": True, "focused": True,
                "bounds": [1, 2, 3, 4], "frame_bounds": [5, 6, 7, 8]}
        node = Snapshot("s", 0)
        node.add([item, {"id": "y", "control_type": "Edit", "automation_id": "field"}, {"id": ""}, item])
        self.assertEqual(2, len(node.nodes))
        line = node.line(node.nodes["x"], 2)
        self.assertEqual("  x CheckBox \"say 'hi' now\" =\"v\" [toggle] toggle:on off-screen disabled "
                         "focused", line)
        self.assertTrue(node.line(node.nodes["x"], bounds=True).endswith("@1,2,3,4 frame@5,6,7,8"))
        self.assertEqual("y Edit #field", node.line(node.nodes["y"]))

    def test_fit_stops_at_the_budget_but_always_keeps_one_line(self):
        lines, shown = fit(["a" * 50] * 10, str, budget=120)
        self.assertEqual((2, 2), (len(lines), shown))
        self.assertEqual(1, fit(["a" * 500], str, budget=10)[1])

    def test_descendants_paths_and_orphans(self):
        stored = tree(*SAMPLE, ("o", "gone", "Button", "Orphan"))
        self.assertEqual(6, stored.descendants()["w"])
        self.assertEqual("Window App > Document Page > List Nav", stored.path("a"))
        self.assertEqual("", stored.path("w"))
        self.assertIn("o", stored.kids[None])
        self.assertIsNone(stored.subtree("missing"))
        self.assertEqual(["l", "a", "c"], stored.subtree("l"))
        self.assertFalse(stored.partial)
        stored.note = "x"
        self.assertTrue(stored.partial)

    def test_find_matches_names_values_types_and_alternatives(self):
        stored = tree(*SAMPLE)
        names = lambda result: [line.split(" ")[0] for line in result["lines"]]  # noqa: E731
        self.assertEqual(["a", "c"], names(find(stored, None, "hyperlink", None, 0, False)))
        self.assertEqual(["b", "a"], names(find(stored, "ALPHA|ok", None, None, 0, False)))
        self.assertEqual(["c"], names(find(stored, "a", "Hyperlink", "c", 0, False)))
        self.assertEqual([], find(stored, "zzz", None, None, 0, False)["lines"])
        self.assertIsNone(find(stored, "a", None, "missing", 0, False))
        self.assertEqual(["c"], names(find(stored, "a", "Hyperlink", None, 1, False)))

    def test_listing_shows_children_with_counts_and_pages(self):
        stored = tree(*SAMPLE)
        shallow = listing(stored, "w", 1, 0)
        self.assertEqual(3, shallow["total"])
        self.assertEqual('d Document "Page" (1 children, 3 in all)', shallow["lines"][2])
        deep = listing(stored, "w", 3, 0)
        self.assertEqual(6, deep["total"])
        self.assertTrue(deep["lines"][-1].startswith("  "))
        self.assertIsNone(listing(stored, "missing", 1, 0))
        with patch("partyline.screen_tree_views.fit", return_value=(["x"], 1)):
            self.assertEqual({"lines": ["x"], "total": 3, "more": 1, "next_offset": 2, "resume": [1, 2]},
                             listing(stored, "w", 1, 1))

    def test_text_is_leaf_names_in_order_with_grep_context(self):
        stored = tree(*SAMPLE, ("e", "d", "Edit", "Search"))
        stored.add([{"id": "ev", "parent": "e", "control_type": "Edit", "name": "Zip", "value": "9021"}])
        stored.nodes["e"].value = "cats"
        lines = text_lines(stored, None)
        self.assertEqual(["Alpha", "Beta", "[Search] cats", "Zip"], text_lines(stored, "d"))
        self.assertEqual("Hello  'world'", lines[0].strip())
        whole = text(stored, None, None, 1, 0)
        self.assertEqual("0: Alpha", whole["lines"][0])
        grep = text(stored, None, "beta", 1, 0)
        self.assertEqual(["0: Alpha", "1: Beta", "2: [Search] cats"], grep["lines"])
        self.assertEqual(3, grep["total"])
        self.assertIsNone(text(stored, "missing", None, 1, 0))
        with patch("partyline.screen_tree_views.fit", return_value=(["x"], 1)):
            paged = text(stored, "d", "a", 0, 0)
            self.assertEqual(paged["next_offset"], 1)

    def test_summary_collapses_wrappers_and_notes_the_rest(self):
        rows = [("w", None, "Window", "App"), ("d", "w", "Document", "Page"), ("g1", "d", "Group", "One"),
                ("g2", "g1", "Group", "Two")]
        rows += [(f"k{n}", "g2", "Group" if n < 10 else "Button", f"Kid {n}") for n in range(12)]
        rows += [(f"m{n}", "k0", "Button", f"M{n}") for n in range(2)]
        result = summary(tree(*rows))
        outline = result["outline"]
        self.assertEqual(18, result["nodes"])
        self.assertTrue(any("Kid 0" in line and "(2 children" in line for line in outline))
        self.assertTrue(any(line.strip().startswith("… ") for line in outline))
        self.assertFalse(any("Kid 11" in line for line in outline))

    def test_answer_modes_and_errors(self):
        stored = tree(*SAMPLE)
        grant = {"title": "Win", "process": "p.exe"}
        self.assertIn("outline", "".join(answer(stored, grant, {})))
        self.assertIn("lines", answer(stored, grant, {"root": "l"}))
        self.assertIn("lines", answer(stored, grant, {"query": "a"}))
        self.assertIn("lines", answer(stored, grant, {"text": True}))
        stored.cursor = "c"
        self.assertIn("more=true", answer(stored, grant, {})["partial"])
        stored.cursor, stored.note = None, "stopped"
        self.assertEqual("stopped", answer(stored, grant, {})["partial"])
        self.assertIn("unknown element", answer(stored, grant, {"root": "nope"})["error"])

    def test_tool_schema_and_query_string(self):
        tool = screen_elements_tool()
        self.assertEqual({"device", "window", "refresh", "more", "root", "depth", "query", "control_type",
                          "text", "context", "offset", "bounds"}, set(tool["inputSchema"]["properties"]))
        for word in ("summary", "find", "text=true", "root=<id>", "screen_element_action", "refresh=true"):
            self.assertIn(word, tool["description"])
        self.assertEqual("", elements_query({}))
        self.assertEqual("?device=My%20PC&depth=2&query=a%26b&text=true",
                         elements_query({"device": "My PC", "query": "a&b", "text": True, "depth": 2,
                                         "refresh": False, "more": None}))


class HubTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.replies = []
        self.sent = []
        grant = {"id": "g", "title": "T", "process": "p"}
        self.hub = ElementsHub(SimpleNamespace(devices={}), clock=lambda: 0)
        self.device = {"id": "d"}

        async def exchange(principal, grant, device, kind, **fields):
            self.sent.append(fields)
            return self.replies.pop(0)

        self.hub.exchange = exchange
        self.revoked = False

        def require(hub, principal, grant_id):
            if self.revoked:
                raise HTTPException(403, "revoked")
            return grant, self.device

        for target, value in (("resolve_window", (grant, self.device)),):
            patcher = patch("partyline.screen_elements." + target, return_value=value)
            patcher.start()
            self.addCleanup(patcher.stop)
        patcher = patch("partyline.screen_elements.require_window", side_effect=require)
        patcher.start()
        self.addCleanup(patcher.stop)

    async def test_unavailable_first_part_is_reported_and_not_stored(self):
        self.replies = [{"elements_unavailable": "not consented", "truncated": True}]
        self.assertEqual({"elements_unavailable": "not consented", "truncated": True},
                         await self.hub.read(None))
        self.assertEqual({}, self.hub.snapshots)

    async def test_a_part_that_fails_midway_leaves_a_partial_tree_to_retry(self):
        self.replies = [{"snapshot_id": "s", "next_cursor": "c", "elements": [{"id": "w", "name": "W"}]},
                        {"elements_unavailable": "timeout"},
                        {"elements": [{"id": "x", "parent": "w", "name": "X"}]}]
        first = await self.hub.read(None)
        self.assertEqual("capture stopped: timeout", first["partial"])
        self.assertEqual(1, first["nodes"])
        retry = await self.hub.read(None, options={"more": True})
        self.assertEqual("c", self.sent[-1]["cursor"])
        self.assertEqual((2, False), (retry["nodes"], "partial" in retry))

    async def test_a_server_timeout_keeps_the_parts_already_read(self):
        async def exchange(principal, grant, device, kind, **fields):
            self.sent.append(fields)
            if fields:
                raise TimeoutError
            return {"snapshot_id": "s", "next_cursor": "c", "elements": [{"id": "w", "name": "W"}]}
        self.hub.exchange = exchange
        result = await self.hub.read(None)
        self.assertEqual(("capture stopped: helper did not respond", 1),
                         (result["partial"], result["nodes"]))
        self.assertEqual("c", self.hub.snapshots["g"].cursor)

    async def test_a_first_part_timeout_is_reported(self):
        async def exchange(*args, **fields):
            raise TimeoutError
        self.hub.exchange = exchange
        self.assertEqual("helper did not respond", (await self.hub.read(None))["elements_unavailable"])

    async def test_an_old_helper_that_cannot_continue_is_named(self):
        self.replies = [{"snapshot_id": "s", "truncated": True, "elements": [{"id": "w"}]}]
        self.assertIn("update it", (await self.hub.read(None))["partial"])

    async def test_helper_silence_and_snapshot_memory_are_bounded(self):
        async def silent(*args, **fields):
            raise TimeoutError
        self.hub.exchange = silent
        self.assertEqual("helper did not respond", (await self.hub.read(None))["elements_unavailable"])
        for number in range(MAX_SNAPSHOTS + 3):
            self.hub.remember(f"g{number}", Snapshot("s", 0))
        self.assertEqual(MAX_SNAPSHOTS, len(self.hub.snapshots))
        self.assertNotIn("g0", self.hub.snapshots)

    async def test_concurrent_calls_share_one_capture(self):
        self.replies = [{"snapshot_id": "s", "elements": [{"id": "w", "name": "W"}]}]
        first, second = await asyncio.gather(self.hub.read(None), self.hub.read(None, options={"query": "w"}))
        self.assertEqual(1, len(self.sent))
        self.assertEqual(1, second["total"])
        self.assertEqual(1, first["nodes"])

    async def test_a_changed_page_is_named_in_every_answer(self):
        self.replies = [{"snapshot_id": "s", "next_cursor": "c", "elements": [{"id": "w", "name": "W"}]},
                        {"changed": True, "elements": [{"id": "x", "parent": "w", "name": "X"}]}]
        result = await self.hub.read(None)
        self.assertIn("refresh=true", result["changed"])
        self.assertIn("partial", result)
        self.assertIn("changed", await self.hub.read(None, options={"query": "x"}))

    async def test_a_revoke_during_the_capture_stores_no_tree(self):
        async def exchange(principal, grant, device, kind, **fields):
            self.revoked = True  # the share stops while the part is being read
            return {"snapshot_id": "s", "elements": [{"id": "w", "name": "W"}]}
        self.hub.exchange = exchange
        with self.assertRaises(HTTPException):
            await self.hub.read(None)
        self.assertEqual({}, self.hub.snapshots)

    async def test_an_older_helper_is_named_even_when_its_read_was_complete(self):
        self.replies = [{"snapshot_id": "s", "elements": [{"id": "a" * 64, "name": "W"}]}]
        result = await self.hub.read(None)
        self.assertNotIn("partial", result)
        self.assertIn("update it", result["update_helper"])
        self.assertIn("update_helper", await self.hub.read(None, options={"query": "w"}))

    async def test_a_refresh_that_fails_drops_the_old_tree(self):
        self.replies = [{"snapshot_id": "s", "elements": [{"id": "w", "name": "W"}]},
                        {"elements_unavailable": "window closed"}]
        await self.hub.read(None)
        self.assertEqual("window closed", (await self.hub.read(None, options={"refresh": True}))[
            "elements_unavailable"])
        self.assertEqual({}, self.hub.snapshots)

    async def test_expired_trees_of_every_window_and_revoked_ones_are_dropped(self):
        now = [0]
        self.hub.clock = lambda: now[0]
        for name in ("old", "other", "keep"):
            self.hub.remember(name, Snapshot("s", 0 if name != "keep" else 900))
        now[0] = 1000
        self.replies = [{"snapshot_id": "s", "elements": [{"id": "w", "name": "W"}]}]
        await self.hub.read(None)  # purges before it answers
        self.assertEqual({"keep", "g"}, set(self.hub.snapshots))
        self.hub.forget("keep")
        self.assertEqual({"g"}, set(self.hub.snapshots))
        self.assertEqual({}, self.hub.locks)

    async def test_stored_trees_are_bounded_in_total_nodes(self):
        with patch("partyline.screen_elements.MAX_STORED", 5):
            for name in ("a", "b", "c"):
                full = Snapshot("s", 0)
                full.add([{"id": f"{name}{n}", "name": "n"} for n in range(3)])
                self.hub.remember(name, full)
        self.assertEqual(["c"], list(self.hub.snapshots))

    async def test_one_tree_stops_at_its_node_cap_with_a_note(self):
        self.replies = [{"snapshot_id": "s", "next_cursor": "c",
                         "elements": [{"id": f"n{n}", "parent": "n0" if n else None, "name": "n"}
                                      for n in range(8)]}]
        with patch("partyline.screen_tree.MAX_TREE", 5), patch("partyline.screen_elements.MAX_TREE", 5):
            result = await self.hub.read(None)
        self.assertEqual(5, result["nodes"])
        self.assertIn("keeps", result["partial"])
        self.assertIsNone(self.hub.snapshots["g"].cursor)

    async def test_an_older_helper_gives_a_flat_list_that_summary_and_ls_can_use(self):
        flat = [{"id": "x" * 64, "control_type": "Window", "name": "W"}] + [
            {"id": f"{n:064x}", "control_type": "Hyperlink", "name": f"Link {n}"} for n in range(1, 30)]
        self.replies = [{"snapshot_id": "s", "truncated": True, "elements": flat}]
        summary = await self.hub.read(None)
        self.assertIn("update it", summary["partial"])
        self.assertEqual(30, summary["nodes"])
        self.assertGreater(len(summary["outline"]), 1)
        listed = await self.hub.read(None, options={"root": "x" * 64})
        self.assertEqual(29, listed["total"])
        self.assertIn("update it", listed["partial"])


class PagingTests(unittest.TestCase):
    def test_text_search_pages_reach_every_match(self):
        rows = [("w", None, "Window", "App"), ("d", "w", "Document", "Page")]
        rows += [(f"t{n}", "d", "Text", f"line {n} {'hit' if n % 10 == 0 else 'x'} " + "y" * 120)
                 for n in range(2000)]
        stored = tree(*rows)
        grant = {"title": "T", "process": "p"}
        seen, offset, pages = [], 0, 0
        while True:
            result = answer(stored, grant, {"text": True, "query": "hit", "context": 0, "offset": offset})
            seen += [line.split(":")[0] for line in result["lines"].split("\n") if line]
            pages += 1
            if "next_offset" not in result:
                break
            self.assertGreater(result["next_offset"], offset)
            offset = result["next_offset"]
        self.assertEqual(200, len(seen))
        self.assertEqual(sorted(set(seen), key=int), seen)
        self.assertGreater(pages, 5)

    def test_find_and_ls_pages_resume_at_the_first_row_not_shown(self):
        rows = [("w", None, "Window", "App")] + [(f"n{n}", "w", "Button", "b" * 100) for n in range(100)]
        stored = tree(*rows)
        first = answer(stored, {"title": "T", "process": "p"}, {"root": "w"})
        shown = len(first["lines"].split("\n"))
        self.assertEqual(shown, first["next_offset"])
        second = answer(stored, {"title": "T", "process": "p"}, {"root": "w", "offset": first["next_offset"]})
        self.assertTrue(second["lines"].startswith(f"n{shown} "))


class WidthTests(unittest.TestCase):
    def test_the_whole_answer_stays_within_4096_utf8_bytes_for_cjk_text(self):
        rows = [("w", None, "Window", "窗" * 200), ("d", "w", "Document", "文" * 200)]
        rows += [(f"n{n}", "d", "Hyperlink", "链接" * 80) for n in range(300)]
        stored = tree(*rows)
        grant = {"title": "标题" * 100, "process": "chrome.exe"}
        for options in ({}, {"root": "d"}, {"query": "链"}, {"text": True}, {"root": "d", "bounds": True}):
            result = answer(stored, grant, options)
            size = len(render(result, "http://x").encode())
            self.assertLessEqual(size, 4096, options)
        listed = answer(stored, grant, {"root": "d"})
        self.assertIn("more", listed)
        self.assertEqual(listed["next_offset"], len(listed["lines"].split("\n")))
