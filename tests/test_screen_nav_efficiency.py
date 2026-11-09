"""Cheap window navigation: exact queries, whole-name text, stable ids, patterns and click-then-read."""
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from fastapi import HTTPException

from partyline.mcp import tools_control
from partyline.screen_element_actions import STALE, ElementAction, Then, element_action
from partyline.screen_elements import ElementsHub
from partyline.screen_tree import Snapshot, clip
from partyline.screen_tree_ids import IdSpace
from partyline.screen_tree_answer import answer, size
from partyline.screen_tree_query import matcher
from partyline.screen_tree_views import changes, detail, find, text_lines
from tests.bookshelf_fixture import bookshelf

GRANT = {"id": "g", "title": "Bookshelf", "process": "chrome.exe"}


def load(page=1, **kwargs):
    stored = Snapshot("s", 0)
    stored.add(bookshelf(page, **kwargs))
    return stored


def ids(result):
    return [line.split("\n")[-1].split(" ")[0] for line in result["lines"]]


def named(stored, kind, name):
    return next(ident for ident, node in stored.nodes.items() if node.type == kind and node.name == name)


class QueryTests(unittest.TestCase):
    def test_terms_match_substrings_exactly_and_at_the_ends(self):
        for query, text, expected in [("ab", "xABx", True), ("=ab", "xabx", False), ("=AB", "ab", True),
                                      ("^1$", "1", True), ("^1$", "12", False), ("^ab", "abc", True),
                                      ("^ab", "cab", False), ("ab$", "cab", True), ("ab$", "abc", False),
                                      ("2|3", "x3", True), ("2|3", "x4", False), ("=", "", True)]:
            self.assertEqual(expected, matcher(query)(text), (query, text))
        self.assertIsNone(matcher(" | "))
        self.assertIsNone(matcher(None))

    def test_query_matches_names_and_value_is_a_separate_filter(self):
        stored = load()
        self.assertEqual(0, find(stored, "2|3", "Hyperlink", None, 0, False, value="zzz")["total"])
        self.assertEqual(1, find(stored, "=2", "Hyperlink", None, 0, False)["total"])
        self.assertEqual(2, find(stored, "=2|=3", "Hyperlink", None, 0, False)["total"])
        self.assertEqual(2, find(stored, "^2$|^3$", "Hyperlink", None, 0, False)["total"])
        self.assertEqual(1, find(stored, "=2", None, None, 0, False, value="#2$")["total"])
        by_value = find(stored, None, "Hyperlink", None, 0, False, value="bookshelf#")
        self.assertEqual(3, by_value["total"])
        self.assertEqual(0, find(stored, "=2", None, None, 0, False, value="#3$")["total"])


class FindLinesTests(unittest.TestCase):
    def test_ancestors_are_named_once_for_the_lines_that_share_them(self):
        stored = load()
        result = find(stored, None, "Hyperlink", named(stored, "List", "Pagination"), 0, False)
        self.assertEqual(3, result["total"])
        heads = [line for line in "\n".join(result["lines"]).split("\n") if line.startswith("in:")]
        self.assertEqual(1, len(heads))
        self.assertIn("[invoke,scroll_into_view]", result["lines"][0])
        row = find(stored, None, "DataItem", None, 0, False)["lines"][0]
        self.assertNotIn("[", row)

    def test_unnamed_wrappers_are_left_out_of_a_path(self):
        stored = load()
        link = named(stored, "Hyperlink", "Reports")
        self.assertEqual("Document Amazon Kindle Direct Pub > List Main menu > ListItem", stored.path(link))

    def test_a_lone_scroll_into_view_is_dropped_but_other_actions_stay(self):
        stored = Snapshot("s", 0)
        stored.add([{"id": "a", "actions": ["scroll_into_view"]},
                    {"id": "b", "actions": ["invoke", "scroll_into_view"]}])
        self.assertNotIn("[", stored.line(stored.nodes[stored.by_helper["a"]]))
        self.assertIn("[invoke,scroll_into_view]", stored.line(stored.nodes[stored.by_helper["b"]]))


class NamesAndTextTests(unittest.TestCase):
    def test_text_includes_names_that_no_text_below_carries_once(self):
        stored = load()
        lines = text_lines(stored, named(stored, "Table", "Your books"))
        first = [line for line in lines if line.startswith("Book in")]
        self.assertEqual(10, len(first))
        self.assertIn("Harbor Lights", lines)
        self.assertTrue(lines[0].startswith("Book in Harbor Lights"))
        self.assertEqual("Harbor Lights", lines[1])
        self.assertEqual(len(lines), len([line for line in lines if line != "Kindle eBook"]) + 10)

    def test_a_name_that_text_below_already_says_is_not_repeated(self):
        stored = load()
        pager = text_lines(stored, named(stored, "List", "Pagination"))
        self.assertEqual(["1", "2", "3"], pager)

    def test_long_names_are_clipped_on_lines_with_a_mark_and_read_whole_by_id(self):
        stored = Snapshot("s", 0)
        stored.add([{"id": "a", "control_type": "DataItem", "name": "T" * 600, "value": "v" * 300}])
        ident = stored.by_helper["a"]
        self.assertEqual("abc", clip("abc", 5))
        self.assertTrue(stored.line(stored.nodes[ident]).count("…") == 2)
        whole = detail(stored, ident)["lines"][0]
        self.assertIn("T" * 600, whole)
        self.assertIn("v" * 300, whole)
        self.assertIsNone(detail(stored, "nope"))
        self.assertEqual(whole, answer(stored, GRANT, {"id": ident})["lines"])
        self.assertIn("unknown element id", answer(stored, GRANT, {"id": "nope"})["error"])

    def test_detail_names_where_the_element_sits(self):
        stored = load()
        link = named(stored, "Hyperlink", "2")
        self.assertIn("in: Document", detail(stored, link)["lines"][0])


class StableIdTests(unittest.TestCase):
    def test_ids_survive_a_new_snapshot_and_a_new_page_title(self):
        first, second = load(1), load(2, snapshot="other")
        self.assertNotEqual(first.nodes[first.order[0]].helper, second.nodes[second.order[0]].helper)
        for kind, name in (("Hyperlink", "2"), ("List", "Pagination"), ("Table", "Your books"),
                           ("Hyperlink", "Reports")):
            self.assertEqual(named(first, kind, name), named(second, kind, name))
        rows = {node.id for node in first.nodes.values() if node.type == "DataItem"}
        self.assertFalse(rows & {node.id for node in second.nodes.values() if node.type == "DataItem"})
        self.assertEqual(len(first.order), len(first.nodes))

    def test_a_banner_and_a_previous_item_do_not_renumber_the_named_elements(self):
        first, second = load(1), load(2, snapshot="other", shifted=True)
        for kind, name in (("Hyperlink", "1"), ("Hyperlink", "2"), ("Hyperlink", "3"), ("List", "Pagination"),
                           ("Table", "Your books"), ("Hyperlink", "Reports")):
            self.assertEqual(named(first, kind, name), named(second, kind, name), name)
        self.assertEqual(4, len(second.kids[named(second, "List", "Pagination")]))  # Previous, 1, 2, 3

    def test_identical_siblings_get_distinct_stable_ids(self):
        again = load(1, snapshot="x")
        links = [node.id for node in again.nodes.values() if node.type == "ListItem"]
        self.assertEqual(len(links), len(set(links)))
        self.assertEqual(list(load(1).nodes), list(again.nodes))

    def test_a_clash_moves_on_and_stays_moved_after_the_other_element_is_gone(self):
        with patch("partyline.screen_tree_ids.ID_CHARS", 1):  # 32 ids for 24 buttons: clashes are certain
            def buttons(names, space=None):
                stored = Snapshot("s", 0, space)
                stored.add([{"id": "w", "control_type": "Window", "name": "App"}] + [
                    {"id": f"h{name}", "parent": "w", "control_type": "Button", "name": f"Action {name}"}
                    for name in names])
                return stored
            first = buttons(range(24))
            ids = {name: first.by_helper[f"h{name}"] for name in range(24)}
            self.assertEqual(25, len(set(first.nodes)))
            later = buttons(range(12, 24), first.space)  # the first twelve are gone
            for name in range(12, 24):
                self.assertEqual(ids[name], later.by_helper[f"h{name}"], name)
            self.assertFalse({ids[name] for name in range(12)} & set(later.nodes) - set(ids.values()))
            again = buttons(range(12, 24), later.space)
            self.assertEqual(list(later.nodes), list(again.nodes))

    def test_a_full_id_space_starts_a_new_numbering_instead_of_forgetting_a_claim(self):
        space = IdSpace()
        first = space.give(b"one")
        with patch("partyline.screen_tree_ids.MAX_CLAIMS", 0):
            space.renew()
        self.assertEqual((1, {}), (space.epoch, space.claims))
        self.assertNotEqual(first, space.give(b"one"))
        space.renew()
        self.assertEqual(1, space.epoch)

    def test_an_id_from_an_old_epoch_never_names_an_element_of_a_new_one(self):
        with patch("partyline.screen_tree_ids.ID_CHARS", 1):  # so the bare ids of two epochs overlap
            def buttons(label):
                stored = Snapshot("s", 0, space)
                stored.add([{"id": "w", "control_type": "Window", "name": "App"}] + [
                    {"id": f"h{n}", "parent": "w", "control_type": "Button", "name": f"{label} {n}"}
                    for n in range(20)])
                return stored
            space = IdSpace()
            old = buttons("Before")
            with patch("partyline.screen_tree_ids.MAX_CLAIMS", 0):
                space.renew()
            new = buttons("After")
        self.assertEqual(1, space.epoch)
        self.assertFalse(set(old.nodes) & set(new.nodes))
        self.assertTrue(all(ident.endswith("-1") for ident in new.nodes))

    def test_a_changed_edit_value_does_not_renumber_its_siblings(self):
        def edits(values):
            stored = Snapshot("s", 0)
            stored.add([{"id": "w", "control_type": "Window"}] + [
                {"id": f"e{n}", "parent": "w", "control_type": "Edit", "name": "Search", "value": value}
                for n, value in enumerate(values)])
            return stored
        one, two = edits("ab"), edits("bb")
        self.assertEqual(one.by_helper["e0"], two.by_helper["e0"])
        self.assertEqual(one.by_helper["e1"], two.by_helper["e1"])


class PatternTests(unittest.TestCase):
    def test_summary_calls_out_the_pager_and_the_table_rows(self):
        stored = load()
        result = answer(stored, GRANT, {})
        patterns = "\n".join(result["patterns"])
        pager = named(stored, "List", "Pagination")
        self.assertIn(f"pager List Pagination {pager}: 1=", patterns)
        link2 = named(stored, "Hyperlink", "2")
        self.assertIn(f"2={link2}", patterns)
        table = named(stored, "Table", "Your books")
        self.assertIn(f"10 similar DataItem rows in Table Your books {table}", patterns)
        self.assertLessEqual(size(result), 2000)

    def test_runs_of_alike_unnamed_items_are_folded_in_the_outline(self):
        outline = "\n".join(answer(load(), GRANT, {})["outline"])
        self.assertIn("+5 alike", outline)
        self.assertIn("… 8 more", outline)

    def test_a_next_link_makes_a_pager_and_a_nested_pager_is_reported_once(self):
        stored = Snapshot("s", 0)
        stored.add([{"id": "w", "control_type": "Window"},
                    {"id": "nav", "parent": "w", "control_type": "Group"},
                    {"id": "p", "parent": "nav", "control_type": "List", "name": "Pages"},
                    {"id": "a", "parent": "p", "control_type": "Hyperlink", "name": "1"},
                    {"id": "n", "parent": "p", "control_type": "Hyperlink", "name": "Next"}])
        lines = answer(stored, GRANT, {})["patterns"]
        self.assertEqual(1, len(lines))
        self.assertIn(f"1={stored.by_helper['a']} Next={stored.by_helper['n']}", lines[0])


class BudgetTests(unittest.TestCase):
    def test_many_pagers_cannot_overflow_the_summary(self):
        rows = [{"id": "w", "control_type": "Window", "name": "App"}, {"id": "d", "parent": "w",
                                                                       "control_type": "Document"}]
        for number in range(100):
            rows.append({"id": f"l{number}", "parent": "d", "control_type": "List",
                         "name": f"Pager {number}"})
            rows += [{"id": f"l{number}-{n}", "parent": f"l{number}", "control_type": "Hyperlink",
                      "name": str(n)} for n in (1, 2, 3)]
        stored = Snapshot("s", 0)
        stored.add(rows)
        result = answer(stored, GRANT, {})
        self.assertLessEqual(size(result), 4096)
        self.assertTrue(result["patterns"])


    def test_one_long_pager_line_cannot_overflow_the_summary(self):
        rows = [{"id": "w", "control_type": "Window", "name": "App"},
                {"id": "l", "parent": "w", "control_type": "List", "name": "Pages"}]
        rows += [{"id": f"h{n}", "parent": "l", "control_type": "Hyperlink", "name": str(n) * 500}
                 for n in range(1, 10)]
        rows += [{"id": f"t{n}", "parent": "w", "control_type": "T" * 90 + str(n)} for n in range(30)]
        stored = Snapshot("s", 0)
        stored.add(rows)
        result = answer(stored, GRANT, {})
        self.assertLessEqual(size(result), 4096)
        self.assertTrue(result["patterns"][0].endswith("…") or len(result["patterns"][0]) <= 200)


class ChangesTests(unittest.TestCase):
    def test_changes_lists_the_topmost_new_elements(self):
        old, new = load(1), load(2, snapshot="b")
        new.before = set(old.nodes)
        result = changes(new)
        self.assertEqual("+100 -100", result["diff"])
        self.assertEqual(10, result["total"])
        self.assertTrue(all("DataItem" in line for line in result["lines"]))
        self.assertEqual("+100 -100", answer(new, GRANT, {"changes": True})["diff"])
        with_query = answer(new, GRANT, {"changes": True, "query": "reports", "control_type": "Hyperlink"})
        self.assertEqual("+100 -100", with_query["diff"])
        self.assertEqual(1, with_query["total"])


class DiffPagingTests(unittest.TestCase):
    def test_a_long_diff_pages_with_offset_and_is_asked_for_by_changes(self):
        def table(prefix):
            stored = Snapshot("s", 0)
            stored.add([{"id": "w", "control_type": "Window"},
                        {"id": "t", "parent": "w", "control_type": "Table", "name": "Rows"}] + [
                {"id": f"r{n}", "parent": "t", "control_type": "DataItem",
                 "name": f"{prefix} {n} " + "x" * 150} for n in range(40)])
            return stored
        old, new = table("old"), table("new")
        new.before = set(old.nodes)
        first = answer(new, GRANT, {"changes": True})
        self.assertIn("next_offset", first)
        second = answer(new, GRANT, {"changes": True, "offset": first["next_offset"]})
        self.assertTrue(second["lines"].startswith(new.by_helper[f"r{first['next_offset']}"]))
        self.assertEqual("+40 -40", second["diff"])
        self.assertNotIn("outline", second)


class Socket:
    def __init__(self):
        self.sent = []

    async def send_json(self, message):
        self.sent.append(message)


class ClickThenReadTests(unittest.IsolatedAsyncioTestCase):
    """The whole loop on a ~425 node page, with the helper's ids changing at every snapshot."""

    async def asyncSetUp(self):
        self.page = 1
        self.snapshots = 0
        self.actions = []
        self.hub = ElementsHub(SimpleNamespace(devices={}), clock=lambda: 0)
        self.hub.settle = AsyncMock()

        async def exchange(principal, grant, device, kind, **fields):
            if kind == "read_window_elements":
                self.snapshots += 1
                return {"snapshot_id": f"s{self.snapshots}", "elements": bookshelf(self.page, self.snapshots)}
            self.actions.append(fields)
            self.page = 2
            return {"status": "completed", "type": "x", "request_id": "r"}

        self.hub.exchange = exchange
        self.principal = SimpleNamespace(name="agent", kind="machine", attachment_id="a")
        for target, value in (("resolve_window", (GRANT, {"id": "d"})), ("require_window", None)):
            patcher = patch("partyline.screen_elements." + target, return_value=value)
            patcher.start()
            self.addCleanup(patcher.stop)
        for target, value in (("resolve_window", (GRANT, {"id": "d"})), ("request_principal", self.principal),
                              ("deny_unless", None)):
            patcher = patch("partyline.screen_element_actions." + target, return_value=value)
            patcher.start()
            self.addCleanup(patcher.stop)
        grants = SimpleNamespace(spend=lambda grant: None)
        self.hub_ns = SimpleNamespace(elements=self.hub, window_grants=grants)

    async def act(self, **body):
        body = ElementAction(action="invoke", **body)
        return await element_action(SimpleNamespace(db=None), self.hub_ns, "line", body, None)

    async def test_click_the_remembered_pager_link_and_read_the_new_titles_in_one_call(self):
        summary = await self.hub.read(self.principal)
        link = named(self.hub.snapshots["g"], "Hyperlink", "2")
        helper = self.hub.snapshots["g"].nodes[link].helper
        self.assertIn(f"2={link}", "".join(summary["patterns"]))
        result = await self.act(element_id=link, then=Then())
        self.assertEqual(helper, self.actions[0]["element_id"])
        self.assertNotEqual(helper, self.hub.snapshots["g"].nodes[link].helper)
        self.assertEqual("completed", result["status"])
        self.assertEqual(2, self.snapshots)
        self.assertIn("Title Number 20", result["after"]["lines"])
        self.assertNotIn("Title Number 10", result["after"]["lines"])
        self.assertLessEqual(size(result), 4096)
        self.assertLess(size(result) / 3.5, 1000)  # a page change and its titles stay under ~1,000 tokens
        # the remembered id still names the link in the new snapshot
        self.assertEqual(link, named(self.hub.snapshots["g"], "Hyperlink", "2"))
        self.hub.settle.assert_awaited()

    async def test_then_can_ask_a_question_and_is_kept_inside_the_budget(self):
        await self.hub.read(self.principal)
        link = named(self.hub.snapshots["g"], "Hyperlink", "2")
        result = await self.act(element_id=link, then=Then(text=True, context=0))
        self.assertLessEqual(size(result), 4096)
        self.assertIn("more", result["after"])
        self.assertNotIn("Title Number 10", result["after"]["lines"])

    async def test_a_stale_id_fails_clearly_and_never_reaches_the_helper(self):
        await self.hub.read(self.principal)
        row = next(ident for ident, node in self.hub.snapshots["g"].nodes.items() if node.type == "DataItem")
        await self.act(element_id=named(self.hub.snapshots["g"], "Hyperlink", "2"))
        await self.hub.read(self.principal, options={"refresh": True})
        self.actions.clear()
        result = await self.act(element_id=row)
        self.assertEqual({"status": "failed", "error": STALE}, result)
        self.assertEqual([], self.actions)

    async def test_without_a_stored_tree_the_id_goes_to_the_helper_as_given(self):
        result = await self.act(element_id="abc")
        self.assertEqual("completed", result["status"])
        self.assertEqual("abc", self.actions[0]["element_id"])
        self.assertNotIn("after", result)

    async def test_the_helpers_own_id_from_the_same_snapshot_still_works(self):
        await self.hub.read(self.principal)
        node = self.hub.snapshots["g"].nodes[named(self.hub.snapshots["g"], "Hyperlink", "2")]
        await self.act(element_id=node.helper)
        self.assertEqual(node.helper, self.actions[0]["element_id"])

    async def test_a_revoke_while_reading_after_keeps_the_action_result(self):
        await self.hub.read(self.principal)
        link = named(self.hub.snapshots["g"], "Hyperlink", "2")
        self.hub.read = AsyncMock(side_effect=HTTPException(403, "revoked"))
        result = await self.act(element_id=link, then=Then())
        self.assertEqual({"error": "revoked"}, result["after"])
        self.assertEqual("completed", result["status"])

    async def test_a_snapshot_without_a_previous_one_lists_every_top_element(self):
        self.hub.snapshots.clear()
        result = await self.hub.read(self.principal, options={"changes": True, "refresh": True})
        self.assertTrue(result["diff"].startswith("+425 -0"))


class IdLifetimeTests(unittest.IsolatedAsyncioTestCase):
    """Ids a grant has given stay with that grant, whatever happens to its trees."""

    async def asyncSetUp(self):
        self.now = [0]
        self.page = list(range(24))
        self.hub = ElementsHub(SimpleNamespace(devices={}), clock=lambda: self.now[0])

        async def exchange(principal, grant, device, kind, **fields):
            return {"snapshot_id": "s", "elements": [{"id": "w", "control_type": "Window", "name": "App"}] + [
                {"id": f"h{n}", "parent": "w", "control_type": "Button", "name": f"Action {n}"}
                for n in self.page]}

        self.hub.exchange = exchange
        for target, value in (("resolve_window", (GRANT, {"id": "d"})), ("require_window", None)):
            patcher = patch("partyline.screen_elements." + target, return_value=value)
            patcher.start()
            self.addCleanup(patcher.stop)
        patcher = patch("partyline.screen_tree_ids.ID_CHARS", 1)
        patcher.start()
        self.addCleanup(patcher.stop)

    async def ids(self):
        await self.hub.read(None, options={"refresh": True})
        return self.hub.snapshots["g"].by_helper

    async def test_ids_survive_the_trees_expiring_and_end_with_the_grant(self):
        before = dict(await self.ids())
        self.page = list(range(12, 24))
        await self.ids()
        self.now[0] = 601  # the tree has expired
        self.hub.snapshots.clear()  # ... or was evicted
        after = await self.ids()
        for n in range(12, 24):
            self.assertEqual(before[f"h{n}"], after[f"h{n}"])
        self.assertEqual((before["w"], False), (after["w"], self.hub.helper_id("g", before["h0"])[1]))
        self.hub.end("g")
        self.assertEqual(({}, {}), (self.hub.snapshots, self.hub.spaces))


class SchemaTests(unittest.TestCase):
    def test_the_action_tool_takes_then_and_rejects_unknown_fields_in_it(self):
        tool = {tool["name"]: tool for tool in tools_control.tool_list({"actions": ["write"]})}[
            "screen_element_action"]
        self.assertIn("then", tool["inputSchema"]["properties"])
        calls = []
        client = SimpleNamespace(home="line", request=lambda *args, **kwargs: calls.append(args) or {})
        tools_control.call(client, "screen_element_action", {"element_id": "a", "action": "invoke",
                                                             "then": {"query": "x", "text": True}},
                           {"actions": ["write"]})
        self.assertEqual("x", calls[0][2]["then"]["query"])
        with self.assertRaises(ValueError):
            bad = {"element_id": "a", "action": "invoke", "then": {"bogus": 1}}
            tools_control.call(client, "screen_element_action", bad, {"actions": ["write"]})

    def test_a_click_that_reads_afterwards_gets_a_longer_client_timeout(self):
        calls = []
        client = SimpleNamespace(home="line", request=lambda *args, **kwargs: calls.append(kwargs) or {})
        action = {"element_id": "a", "action": "invoke"}
        tools_control.call(client, "screen_element_action", action, {"actions": ["write"]})
        tools_control.call(client, "screen_element_action", {**action, "then": {}}, {"actions": ["write"]})
        self.assertEqual([{"timeout": 40}, {"timeout": 100}], calls)

    def test_descriptions_stay_short(self):
        from partyline.mcp.tools_screen import ELEMENTS_NOTE
        self.assertLess(len(ELEMENTS_NOTE), 900)
        self.assertLess(len(tools_control.ELEMENT_ACTION_NOTE), 400)


class FixtureSizeTests(unittest.TestCase):
    def test_the_bookshelf_has_about_425_nodes_and_answers_fit_the_budget(self):
        stored = load()
        self.assertEqual(425, len(stored.order))
        table = named(stored, "Table", "Your books")
        for options in ({}, {"text": True}, {"query": "link"}, {"root": table}):
            self.assertLessEqual(size(answer(stored, GRANT, options)), 4096)
        self.assertEqual(1, find(stored, "=2", "Hyperlink", None, 0, False)["total"])
