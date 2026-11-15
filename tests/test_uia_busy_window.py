"""A window with one subtree that raises events without end still reads and acts: fake provider, no clock."""
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from partyline.screen_elements import ElementsHub
from partyline_helper.uia_access import WindowAccess
from partyline_helper.uia_action_worker import ActionWorker, run_action
from partyline_helper.uia_event_state import EventState
from partyline_helper.uia_query import snapshot as query_snapshot
from partyline_helper.uia_snapshot import snapshot
from partyline_helper.uia_task import read_options
from tests.test_uia_worker import Provider

GRANT = {"id": "g", "title": "Dialog", "process": "app"}
KINDS = {0: "Window", 1: "Pane", 2: "ComboBox", 3: "Edit", 4: "List", 5: "ListItem", 6: "ListItem"}
NAMES = {0: "Dialog", 1: "Form", 2: "Name box", 3: "Name field", 4: "Items", 5: "one", 6: "two"}
PARENTS = {1: 0, 2: 1, 3: 2, 4: 0, 5: 4, 6: 4}
FORM, EDIT, LIST = 1, 3, 4


class FakeTree(Provider):
    """Nodes 4-6 form a sibling subtree; whatever is in `noisy` raises an event each time it is read."""

    def __init__(self, raise_event):
        super().__init__()
        self.nodes = [{"rect": (0, 0, 9, 9), "children": [1, 4], "name": NAMES[0]}]
        for index in range(1, 7):
            self.nodes.append({"rect": (0, 0, 5, 5), "name": NAMES[index],
                               "children": {1: [2], 2: [3], 4: [5, 6]}.get(index, [])})
        self.raise_event, self.noisy = raise_event, set()

    def properties(self, node):
        if node in self.noisy:
            self.raise_event(node)
        result = super().properties(node)
        result["control_type"] = KINDS[node]
        return result

    def parent(self, node):
        return PARENTS[node]


class BusyWindowTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.state = EventState()
        self.state.supported, self.state.subscription = True, SimpleNamespace(live=True)
        self.provider = FakeTree(self.event)
        self.reads, self.found = [], (5, [3])  # a query's finder raises this node's event, finds those
        session = SimpleNamespace(share=None, accepted=False, window_grant_id="g",
                                  status=SimpleNamespace(window_title="App", changed=Mock()),
                                  tools=SimpleNamespace(audit=SimpleNamespace(
                                      append=Mock(), ensure_writable=Mock())))
        self.grant = {"hwnd": 1, "pid": 2, "title": "Dialog", "process": "app"}
        self.access = WindowAccess(session, platform="win32", reader=self.reader,
                                   list_windows=lambda: [self.grant])
        self.access.grant, self.access.event_status = self.grant, self.state.status
        self.access.event_state = self.state
        self.access.gate.grant()
        session.window = self.access
        self.worker = ActionWorker(session, runner=lambda *args: run_action(
            *args, factory=lambda _: self.provider))
        self.hub = ElementsHub(SimpleNamespace(), clock=lambda: 0)
        self.hub.exchange = self.exchange
        self.principal = SimpleNamespace()
        for name, value in (("resolve_window", (GRANT, {"id": "d"})), ("require_window", None)):
            patcher = patch("partyline.screen_elements." + name, return_value=value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def event(self, node):
        self.state.changed((node,))

    def reader(self, hwnd, frame=None, state=None, deep=True, **options):
        self.reads.append(options)
        if options.get("query"):
            def finder(*_):
                self.event(self.found[0])  # a subtree keeps going while the query reads
                return self.found[1]
            return query_snapshot(self.provider, options["query"], finder=finder)
        return snapshot(self.provider, clock=lambda: 0, state=state)

    async def exchange(self, principal, grant, device, kind, **fields):
        if kind == "window_element_action":
            return await self.worker.perform(fields)
        if fields.get("event_status"):
            status = self.state.status()
            if "events_since" in fields:
                status["event_sources"] = self.access.event_sources(fields["events_since"])
            return status
        return await self.access.snapshot(read_options(fields))

    async def read(self, **options):
        return await self.hub.read(self.principal, options=options)

    def captures(self):
        return len([item for item in self.reads if not item.get("cursor")])

    def stable(self, node):
        tree = self.hub.snapshots["g"]
        return next(ident for ident, item in tree.nodes.items() if item.name == NAMES[node])

    async def test_whole_window_read_settles_and_names_the_busy_subtree(self):
        self.provider.noisy = {LIST, 5, 6}
        result = await self.read()
        self.assertEqual(2, self.captures())
        self.assertNotIn("partial", result)
        self.assertIn(f'{self.stable(LIST)} List "Items"', result["busy"])
        self.assertIn(f"root={self.stable(FORM)}", result["busy"])
        self.assertTrue(result["change_event_since_snapshot"])

    async def test_one_burst_that_stops_leaves_no_busy_note(self):
        self.provider.noisy = {5}
        original = self.provider.raise_event
        def once(node):
            original(node)
            self.provider.noisy.clear()
        self.provider.raise_event = once
        result = await self.read()
        self.assertEqual(2, self.captures())
        self.assertNotIn("busy", result)

    async def test_a_read_scoped_away_from_the_busy_subtree_is_clean(self):
        self.provider.noisy = {LIST, 5, 6}
        await self.read()
        result = await self.read(refresh=True, root=self.stable(FORM))
        self.assertNotIn("busy", result)
        self.assertNotIn("partial", result)
        self.assertFalse(result["change_event_since_snapshot"])
        inside = await self.read(refresh=True, root=self.stable(LIST))
        self.assertIn("busy", inside)

    async def test_query_capture_ignores_events_outside_its_matches(self):
        self.provider.noisy = {LIST}
        await self.read()
        self.reads.clear()
        result = await self.read(query="Name field")
        self.assertEqual(1, self.captures())
        self.assertNotIn("partial", result)
        self.assertNotIn("busy", result)
        self.assertIn("Name field", result["lines"])

    async def test_unplaced_events_fail_with_the_way_to_recover(self):
        result = await self.read(query="Name field")
        self.assertEqual(8, self.captures())
        self.assertIn("inconsistent", result["partial"])
        self.assertIn("read the whole window once", result["partial"])

    async def act(self, target):
        return await self.worker.perform({"element_id": target, "action": "set_value", "value": "x"})

    async def test_set_value_on_the_stable_edit_proceeds_beside_a_busy_subtree(self):
        self.provider.noisy = {LIST, 5, 6}
        await self.read()
        reads = len(self.reads)
        self.hub.changed("g")  # the helper keeps pushing change notices
        self.event(5)
        target, known = await self.hub.action_target(self.principal, GRANT, self.stable(EDIT))
        self.assertEqual(reads, len(self.reads))  # the tree was judged, not read again
        self.assertTrue(known)
        self.assertEqual("completed", (await self.act(target))["status"])
        self.assertEqual([(EDIT, "set_value", "x")], self.provider.calls)

    async def test_an_event_in_the_target_or_above_it_forces_a_new_read(self):
        for source in (EDIT, 2, FORM):
            with self.subTest(source=source):
                self.provider.noisy = {LIST}
                await self.read()
                reads = len(self.reads)
                self.hub.changed("g")
                self.event(source)
                target, _ = await self.hub.action_target(self.principal, GRANT, self.stable(EDIT))
                self.assertGreater(len(self.reads), reads)
                self.assertIsNotNone(target)  # the new read found the target itself quiet

    async def test_a_target_that_keeps_changing_is_refused(self):
        self.provider.noisy = {LIST}
        await self.read()
        self.provider.noisy = {EDIT}
        self.hub.changed("g")
        self.event(EDIT)
        self.assertEqual((None, False), await self.hub.action_target(self.principal, GRANT,
                                                                      self.stable(EDIT)))
        self.assertFalse(self.provider.calls)

    async def test_a_busy_list_item_is_not_a_stable_target(self):
        self.provider.noisy = {5}
        await self.read()
        self.hub.changed("g")
        self.assertEqual((None, False), await self.hub.action_target(self.principal, GRANT,
                                                                      self.stable(5)))

    async def test_a_fresh_tree_that_recorded_the_target_busy_refuses_it(self):
        self.provider.noisy = {EDIT}
        await self.read()
        self.assertEqual((None, False), await self.hub.action_target(self.principal, GRANT,
                                                                      self.stable(EDIT)))
        self.assertFalse(self.provider.calls)

    async def test_a_query_match_is_no_stable_target_when_something_below_it_changes(self):
        self.provider.noisy = {LIST}
        await self.read()
        edit = self.stable(EDIT)
        self.found = (EDIT, [2])  # the query keeps only the combo box; its child Edit raises events
        result = await self.read(query="Name box")
        self.assertNotIn("busy", result)  # what the query shows is the match itself
        tree = self.hub.snapshots["g"]
        self.assertNotIn(edit, tree.nodes)
        self.assertFalse(await self.hub.target_stable(self.principal, GRANT, {"id": "d"}, tree,
                                                      self.stable(2)))

    async def test_a_fresh_query_tree_is_judged_through_the_action_path(self):
        await self.read()
        self.found = (EDIT, [2])
        await self.read(query="Name box", refresh=True)
        parent, reads = self.stable(2), len(self.reads)
        target, _ = await self.hub.action_target(self.principal, GRANT, parent)
        self.assertGreater(len(self.reads), reads)  # the omitted descendant's event forced a new read
        self.assertIsNotNone(target)
        self.provider.noisy = {EDIT}
        await self.read(query="Name box", refresh=True)
        self.assertEqual((None, False), await self.hub.action_target(self.principal, GRANT,
                                                                      self.stable(2)))

    async def test_ancestry_kept_across_a_reorder_is_not_trusted(self):
        await self.read()
        self.provider.nodes[0]["children"] = [4, 1]  # the root reorders its children
        self.event(0)
        self.found = (EDIT, [2])
        await self.read(query="Name box", refresh=True)
        reads = len(self.reads)
        target, _ = await self.hub.action_target(self.principal, GRANT, self.stable(2))
        self.assertGreater(len(self.reads), reads)  # not judged stable on the old paths
        self.assertEqual(self.hub.snapshots["g"].nodes[self.stable(2)].helper, target)

    async def test_every_action_target_is_proved_before_it_is_used(self):
        await self.read()  # quiet: the tree is fresh and flagged nothing
        self.event(EDIT)
        self.provider.noisy = {EDIT}  # and still changing, before any debounced push arrives
        self.assertEqual((None, False), await self.hub.action_target(self.principal, GRANT,
                                                                      self.stable(EDIT)))

    async def test_an_event_seen_only_by_the_final_status_check_stops_the_action(self):
        await self.read()
        original = self.hub.capture_status
        async def late(*args):
            self.event(EDIT)  # arrives after the capture, before the read answers
            return await original(*args)
        self.hub.capture_status = late
        await self.read(refresh=True)
        self.provider.noisy = {EDIT}
        self.assertEqual((None, False), await self.hub.action_target(self.principal, GRANT,
                                                                      self.stable(EDIT)))

    async def test_a_target_kept_only_as_a_retained_id_is_read_again(self):
        await self.read()
        edit = self.stable(EDIT)
        self.found = (5, [5])
        await self.read(query="one", refresh=True)  # a query tree: the Edit survives only as an action id
        self.assertNotIn(edit, self.hub.snapshots["g"].nodes)
        self.provider.noisy = {EDIT}
        self.assertEqual((None, False), await self.hub.action_target(self.principal, GRANT, edit))
        self.provider.noisy = set()
        reads = len(self.reads)
        target, known = await self.hub.action_target(self.principal, GRANT, edit)
        self.assertGreater(len(self.reads), reads)
        self.assertTrue(known)

    async def test_an_event_with_no_sender_voids_retained_ancestry(self):
        await self.read()
        self.provider.nodes[0]["children"] = [4, 1]
        self.state.changed()
        self.found = (EDIT, [2])
        await self.read(query="Name box", refresh=True)
        reads = len(self.reads)
        target, _ = await self.hub.action_target(self.principal, GRANT, self.stable(2))
        self.assertGreater(len(self.reads), reads)
        self.assertEqual(self.hub.snapshots["g"].nodes[self.stable(2)].helper, target)

    async def test_an_event_from_an_unlisted_sender_voids_retained_ancestry(self):
        await self.read()
        self.provider.nodes[0]["children"] = [4, 1]
        self.state.changed((99,))  # a runtime id no read ever listed
        self.found = (EDIT, [2])
        await self.read(query="Name box", refresh=True)
        reads = len(self.reads)
        await self.hub.action_target(self.principal, GRANT, self.stable(2))
        self.assertGreater(len(self.reads), reads)
