"""Event sources: how the helper names them and how the server places them in a captured tree."""
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from partyline import screen_event_scope as scope
from partyline.screen_element_state import ElementState
from partyline.screen_tree import Snapshot
from partyline_helper import uia_event_state
from partyline_helper.uia_access import WindowAccess
from partyline_helper.uia_event_state import EventState
from partyline_helper.uia_events import event_cache, register_handlers, source_of
from partyline_helper.uia_task import read_options
from partyline_helper.window_share_dispatch import _event_status
from tests.test_uia_events import AutomationContract, HandlerBase


class Sender:
    def __init__(self, own):
        self.own = own

    def GetCachedPropertyValue(self, ident):
        if self.own is None:
            raise OSError("not cached")
        return self.own


class HelperSideTests(unittest.IsolatedAsyncioTestCase):
    def test_sources_since_lists_each_distinct_source_after_the_counter(self):
        state = EventState()
        for source in ("a", "b", "a"):
            state.changed(source)
        self.assertEqual(["a", "b"], state.sources_since(0)["sources"])
        self.assertEqual(["a"], state.sources_since(2)["sources"])
        self.assertEqual({"sources": [], "unplaced": False, "overflow": False}, state.sources_since(3))
        state.changed()
        self.assertTrue(state.sources_since(3)["unplaced"])
        self.assertFalse(state.sources_since(4)["unplaced"])

    def test_dropping_the_oldest_sources_is_reported_as_overflow(self):
        state = EventState()
        with patch.object(uia_event_state, "MAX_SOURCES", 2):
            for source in "abc":
                state.changed(source)
        self.assertTrue(state.sources_since(0)["overflow"])
        self.assertFalse(state.sources_since(1)["overflow"])

    def test_handlers_name_their_source_from_the_cache_and_degrade_without_it(self):
        self.assertEqual((1,), source_of(Sender((1,))))
        self.assertIsNone(source_of(Sender(None)))
        automation = AutomationContract()
        uia = SimpleNamespace(IUIAutomationPropertyChangedEventHandler=object,
                              IUIAutomationStructureChangedEventHandler=object)
        seen = []
        register_handlers(automation, uia, "window", lambda *source: seen.append(source), HandlerBase,
                          cache="cache")
        automation.added[0][-2].HandlePropertyChangedEvent(Sender((1,)), 30010, True)
        automation.added[1][-1].HandleStructureChangedEvent(Sender(None), 0, [])
        self.assertEqual("cache", automation.added[0][3])
        self.assertEqual([((1,),), ()], seen)

    def test_a_provider_that_refuses_cached_events_is_registered_without_the_cache(self):
        class Strict(AutomationContract):
            def AddPropertyChangedEventHandler(self, element, scope, cache, handler, properties):
                if cache is not None:
                    raise OSError("no cache")
                super().AddPropertyChangedEventHandler(element, scope, cache, handler, properties)

        automation = Strict()
        uia = SimpleNamespace(IUIAutomationPropertyChangedEventHandler=object,
                              IUIAutomationStructureChangedEventHandler=object)
        register_handlers(automation, uia, "window", lambda: None, HandlerBase, cache="cache")
        self.assertEqual([None, None], [item[3] for item in automation.added])

    def test_the_cache_request_asks_for_the_runtime_id_of_the_sender_alone(self):
        request = SimpleNamespace(AddProperty=Mock())
        self.assertIs(request, event_cache(SimpleNamespace(CreateCacheRequest=lambda: request)))
        request.AddProperty.assert_called_once_with(30000)
        self.assertFalse(hasattr(request, "TreeScope"))  # UIA caches the element itself by default
        self.assertIsNone(event_cache(SimpleNamespace(CreateCacheRequest=Mock(side_effect=OSError))))

    def test_access_places_an_event_by_its_sender_and_names_its_listed_ancestors(self):
        access = WindowAccess(SimpleNamespace(), platform="win32")
        self.assertIsNone(access.event_sources(0))
        access.event_state = EventState()
        access.keep({"elements": [{"id": "x"}, {"id": "y"}], "paths": {"r": [], "y": [0], "x": [0, 1]},
                     "runtimes": [[[1], "x"], [[2], "y"]]}, None, counter=0)
        for source in ((1,), (2,)):
            access.event_state.changed(source)
        # y raised an event after x was listed, so x's path may be stale; y's ancestor r was quiet
        self.assertEqual({"ids": [["x", "y", "r"], ["y", "r"]], "unsure": ["x"], "unplaced": 0,
                          "overflow": False}, access.event_sources(0))
        access.event_state.changed((8,))  # a sender no read listed could have moved anything
        found = access.event_sources(0)
        self.assertEqual((["x", "y"], 1), (found["unsure"], found["unplaced"]))
        access.event_state.changed()  # an event with no sender could have moved anything
        found = access.event_sources(0)
        self.assertEqual((["x", "y"], 2), (found["unsure"], found["unplaced"]))
        access.listed.pop("y")
        access.forget()
        self.assertFalse(access.runtimes)

    def test_retained_runtime_ids_are_bounded(self):
        access = WindowAccess(SimpleNamespace(), platform="win32")
        with patch("partyline_helper.uia_access.MAX_RETAINED_IDS", 1):
            access.keep({"elements": [], "runtimes": [[[n], "x"] for n in range(5)]}, None, scoped=True)
        self.assertEqual({(3,), (4,)}, set(access.runtimes))

    async def test_continuation_tolerates_events_only_when_asked(self):
        session = SimpleNamespace(share=None, accepted=False)
        access = WindowAccess(session, platform="win32", reader=lambda *a, **k: {"elements": []},
                              list_windows=lambda: [{"hwnd": 1, "pid": 2}])
        access.grant, access.event_counter = {"hwnd": 1, "pid": 2, "title": "t", "process": "p"}, 1
        access.event_status, access.walks["c"] = (lambda: {"event_counter": 2}), {"stack": []}
        strict = await access.snapshot({"cursor": "c"})
        self.assertIn("inconsistent", strict["elements_unavailable"])
        self.assertNotIn("elements_unavailable", await access.snapshot({"cursor": "c",
                                                                        "tolerate_events": True}))
        self.assertEqual({"cursor": "c", "tolerate_events": True},
                         read_options({"cursor": "c", "tolerate_events": True}))
        self.assertEqual({"cursor": "c"}, read_options({"cursor": "c", "tolerate_events": 1}))

    async def test_event_status_answers_with_sources_when_asked(self):
        state = EventState()
        state.changed(((1,), None))
        access = SimpleNamespace(grant=None, event_sources=lambda since: {"since": since})
        sent = []
        shares = SimpleNamespace(session=SimpleNamespace(send=AsyncMock(
            side_effect=lambda *args, **fields: sent.append(fields))))
        entry = {"access": access, "event_state": state}
        await _event_status(shares, entry, {"request_id": "r", "events_since": 0})
        await _event_status(shares, entry, {"request_id": "r", "events_since": True})
        self.assertEqual({"since": 0}, sent[0]["event_sources"])
        self.assertNotIn("event_sources", sent[1])


def tree_of(shape):
    """Nodes named by letter: shape maps a node to its parent."""
    tree = Snapshot("s", 0)
    for name, parent in shape.items():
        tree.add([{"id": name, "parent": parent, "name": name, "control_type": "Button"}])
    tree.event_counter = 5
    tree.sources = True
    return tree


class ServerSideTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.hub = SimpleNamespace()
        self.tree = tree_of({"w": None, "a": "w", "b": "w", "c": "a", "d": "a"})

    async def judge(self, status, tree=None):
        hub = ElementState()
        hub.exchange = AsyncMock(return_value={"events_supported": True, "subscription_live": True, **status})
        return await hub.judge(None, {}, {}, tree or self.tree)

    async def test_judging_places_events_and_keeps_only_the_outermost(self):
        self.assertEqual((False, set()), await self.judge({"event_counter": 5}))
        sources = {"ids": [["c", "a", "w"], ["a", "w"], ["gone", "b"]], "unplaced": 0, "overflow": False}
        moved, roots = await self.judge({"event_counter": 9, "event_sources": sources})
        self.assertEqual((True, {self.tree.by_helper["a"], self.tree.by_helper["b"]}), (moved, roots))

    async def test_events_that_cannot_be_placed_touch_everything(self):
        for sources in ({"ids": [], "unplaced": 1, "overflow": False},
                        {"ids": [], "unplaced": 0, "overflow": True}, None):
            with self.subTest(sources=sources):
                self.assertEqual((True, None), await self.judge({"event_counter": 9,
                                                                 "event_sources": sources}))
        good = {"ids": [], "unplaced": 0, "overflow": False}
        self.assertEqual((True, None), await self.judge({"event_counter": 9, "event_sources": good,
                                                         "subscription_live": False}))
        self.tree.sources = False
        self.assertEqual((True, None), await self.judge({"event_counter": 9, "event_sources": good}))
        self.tree.sources, self.tree.cursor = True, "more"
        unread = {"ids": [["elsewhere"]], "unplaced": 0, "overflow": False}
        self.assertEqual((True, None), await self.judge({"event_counter": 9, "event_sources": unread}))

    async def test_target_stability_follows_the_events_ancestry(self):
        async def stable(ids, target):
            sources = {"ids": [[item, "w"] for item in ids], "unplaced": 0, "overflow": False}
            hub = ElementState()
            hub.exchange = AsyncMock(return_value={"events_supported": True, "subscription_live": True,
                                                   "event_counter": 9, "event_sources": sources})
            result = await hub.target_stable(None, {}, {}, self.tree, self.tree.by_helper[target])
            if not result:
                from partyline.screen_element_actions import changing
                hub.snapshots = {"g": self.tree}
                self.assertIn("subtree " + self.tree.by_helper[ids[0]], changing(hub, "g")["error"])
            return result
        self.assertTrue(await stable(["b"], "c"))
        self.assertTrue(await stable(["d"], "c"))
        self.assertFalse(await stable(["c"], "c"))
        self.assertFalse(await stable(["a"], "c"))
        self.assertFalse(await stable(["w"], "c"))
        self.assertFalse(await ElementState().target_stable(None, {}, {}, self.tree, "unknown"))

    def test_busy_note_names_subtrees_and_the_stable_parts_to_read(self):
        a, b = (self.tree.by_helper[name] for name in "ab")
        note = scope.busy_note(self.tree, [a])
        self.assertIn(f'{a} Button "a"', note)
        self.assertIn(f"root={b}", note)
        self.assertEqual([b], scope.stable_parts(self.tree, {a}))
        whole = scope.busy_note(self.tree, [self.tree.order[0]])
        self.assertIn("read it again when it settles", whole)
        many = tree_of({"w": None, **{f"n{i}": "w" for i in range(5)}})
        self.assertIn("and 2 more", scope.busy_note(many, [many.by_helper[f"n{i}"] for i in range(5)]))
        self.assertEqual([], scope.stable_parts(Snapshot("s", 0), set()))

    def test_a_read_answers_about_the_element_it_names(self):
        hub = ElementState()
        a = self.tree.by_helper["a"]
        self.assertEqual(a, hub.scope_top(self.tree, {"root": "a"}))
        self.assertEqual(a, hub.scope_top(self.tree, {"id": a}))
        self.assertIsNone(hub.scope_top(self.tree, {}))
        self.tree.scoped = True
        self.assertIsNone(hub.scope_top(self.tree, {"root": a}))
        self.tree.busy = {self.tree.by_helper["c"]}
        self.assertEqual(self.tree.busy, hub.busy_in(self.tree, None))
        self.assertEqual(set(), hub.busy_in(self.tree, self.tree.by_helper["b"]))

    async def test_a_target_in_an_incomplete_tree_is_unstable_when_a_source_may_be_unread(self):
        async def stable(chains, cursor):
            self.tree.cursor = cursor
            hub = ElementState()
            hub.exchange = AsyncMock(return_value={
                "events_supported": True, "subscription_live": True, "event_counter": 9,
                "event_sources": {"ids": chains, "unplaced": 0, "overflow": False}})
            return await hub.target_stable(None, {}, {}, self.tree, self.tree.by_helper["c"])
        self.assertTrue(await stable([["b", "w"]], None))
        self.assertTrue(await stable([["b", "w"]], "more"))
        self.assertFalse(await stable([["elsewhere"]], "more"))
        hub = ElementState()
        hub.exchange = AsyncMock(return_value={"event_counter": 9})
        self.assertFalse(await hub.target_stable(None, {}, {}, self.tree, self.tree.by_helper["c"]))

    async def test_a_source_with_stale_ancestry_is_not_trusted_unless_the_tree_holds_it(self):
        tree = tree_of({"w": None, "a": "w", "c": "a"})
        del tree.by_helper["c"]  # a query kept only the parent

        async def run(sources, scoped):
            tree.scoped = scoped
            hub = ElementState()
            hub.exchange = AsyncMock(return_value={
                "events_supported": True, "subscription_live": True, "event_counter": 9,
                "event_sources": {"ids": [["c", "a", "w"]], "unsure": sources, "unplaced": 0,
                                  "overflow": False}})
            return (await hub.target_stable(None, {}, {}, tree, tree.by_helper["a"]),
                    await hub.judge(None, {}, {}, tree))
        self.assertEqual((False, (True, None)), await run(["c"], False))
        stable, judged = await run(["c"], True)
        self.assertFalse(stable)  # the target's action never trusts what it cannot place
        self.assertEqual((True, set()), judged)  # a query read ignores what its tree does not hold
        self.assertEqual((False, (True, {tree.by_helper["a"]})), await run([], False))
