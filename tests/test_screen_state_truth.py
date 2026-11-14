"""Event clocks, cache barriers and diagnostics use deterministic fake providers."""
import asyncio
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch

from partyline.screen_elements import ElementsHub
from partyline.screen_element_state import verdict
from partyline.screen_element_actions import Then, after
from partyline_helper.uia_event_state import EventState
from partyline_helper.uia_probe import inspect, current
from partyline_helper.uia_events import PROPERTIES, register_handlers
from partyline_helper.uia_access import WindowAccess
from partyline_helper.window_shares import WindowShares

GRANT = {"id": "g", "title": "Chrome", "process": "chrome.exe"}


class StateTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.hub = ElementsHub(SimpleNamespace(), clock=lambda: 0)
        self.counter, self.captures, self.barriers = 0, 0, 0
        self.enabled, self.live, self.supported = False, True, True
        self.during, self.late, self.cursor = False, False, None
        self.hub.exchange = self.exchange
        self.principal = SimpleNamespace()
        self.device = {"id": "d"}
        for name, value in (("resolve_window", (GRANT, self.device)), ("require_window", None)):
            p = patch("partyline.screen_elements." + name, return_value=value)
            p.start()
            self.addCleanup(p.stop)

    def status(self):
        return {"event_counter": self.counter, "subscription_live": self.live,
                "events_supported": self.supported, "last_event_time": 123}

    async def exchange(self, principal, grant, device, kind, **fields):
        if fields.get("event_status"):
            self.barriers += 1
            return self.status()
        if fields.get("inspect"):
            return {**self.status(), "live": {"enabled": self.enabled}, "ancestors": []}
        self.captures += 1
        captured = self.counter
        if self.during:
            self.during = False
            self.counter += 1
            self.enabled = True
        return {**self.status(), "captured_event_counter": captured, "snapshot_id": str(self.captures),
                "next_cursor": self.cursor, "elements": [
                    {"id": "w", "name": "Chrome", "control_type": "Window", "enabled": True},
                    {"id": "link", "parent": "w", "name": "Manage A+ Content",
                     "control_type": "Hyperlink", "enabled": self.enabled, "bounds": [1, 2, 30, 40]}]}

    async def read(self, **options):
        return await self.hub.read(self.principal, options=options)

    async def test_inflight_event_before_debounced_push_forces_capture_and_delta(self):
        await self.read()
        self.counter += 1  # no hub.changed push yet
        self.enabled = True
        result = await self.read(changes=True)
        self.assertEqual(2, self.captures)
        self.assertIn("~1", result["diff"])
        self.assertIn("Manage A+ Content", result["lines"])
        self.assertNotIn("disabled", result["lines"])
        self.assertFalse(result["change_event_since_snapshot"])

    async def test_layout_and_focus_changes_do_not_hide_the_enabled_link_delta(self):
        exchange = self.exchange
        shifted = False
        async def layout(*args, **fields):
            result = await exchange(*args, **fields)
            if fields.get("event_status"):
                return result
            result["elements"].insert(1, {"id": "doc", "parent": "w", "name": "Page",
                                          "control_type": "Document", "enabled": True})
            result["elements"][2]["parent"] = "doc"
            result["elements"].extend({"id": str(i), "parent": "doc", "name": f"Other link {i}",
                                       "control_type": "Hyperlink", "enabled": True} for i in range(30))
            for item in result["elements"]:
                item.update(bounds=[5 if shifted else 0, 0, 100, 20], focused=shifted,
                            offscreen=shifted, patterns=["Invoke"] if shifted else [])
            return result
        self.hub.exchange = layout
        await self.read()
        shifted = True
        self.counter += 1
        self.enabled = True
        result = await self.read(changes=True)
        self.assertEqual("+0 -0 ~1", result["diff"])
        self.assertEqual(1, result["total"])
        self.assertIn("Manage A+ Content", result["lines"])
        self.assertNotIn('Document "Page"', result["lines"])
        # A layout-only change is not a semantic state delta.
        shifted = False
        self.counter += 1
        layout_only = await self.read(changes=True)
        self.assertEqual("+0 -0", layout_only["diff"])
        self.assertEqual("", layout_only["lines"])

    async def test_cache_hit_uses_one_barrier(self):
        await self.read()
        before = self.barriers
        await self.read()
        self.assertEqual(before + 1, self.barriers)
        self.assertEqual(1, self.captures)

    async def test_event_during_capture_recaptures_without_sleep(self):
        self.during = True
        result = await self.read(query="Manage")
        self.assertEqual(2, self.captures)
        self.assertEqual(1, result["snapshot_event_counter"])
        self.assertTrue(result["change_event_since_snapshot"])
        self.assertNotIn("disabled", result["lines"])
        cached = await self.read(query="Manage")
        self.assertFalse(cached["change_event_since_snapshot"])
        self.assertEqual(2, self.captures)

    async def test_churn_is_bounded_and_explicitly_inconsistent(self):
        exchange = self.exchange
        async def churn(*args, **kwargs):
            if not kwargs.get("event_status"):
                self.during = True
            return await exchange(*args, **kwargs)
        self.hub.exchange = churn
        result = await self.read()
        self.assertEqual(8, self.captures)
        self.assertIn("inconsistent", result["partial"])
        self.assertTrue(result["change_event_since_snapshot"])

    async def test_late_after_action_event_is_reported_and_next_read_is_delta(self):
        await self.read()
        original = self.hub.capture_status
        count = 0
        async def late(*args):
            nonlocal count
            count += 1
            if count == 2:  # after post-action capture, just before its final status read
                self.counter += 1
                self.enabled = True
            return await original(*args)
        self.hub.capture_status = late
        result = await after(SimpleNamespace(elements=self.hub), self.principal, GRANT, Then(), {})
        self.assertEqual(0, result["snapshot_event_counter"])
        self.assertTrue(result["change_event_since_snapshot"])
        self.hub.action_completed("g", retain_snapshot=True)
        delta = await self.read(changes=True)
        self.assertIn("~1", delta["diff"])
        self.assertIn("Manage A+ Content", delta["lines"])

    async def test_more_across_event_restarts_from_root(self):
        await self.read()
        self.hub.snapshots["g"].cursor = "old"
        self.counter += 1
        calls = []
        original = self.exchange
        async def exchange(*args, **fields):
            calls.append(fields)
            return await original(*args, **fields)
        self.hub.exchange = exchange
        result = await self.read(more=True)
        self.assertIn("restarted", result["continuation_restarted"])
        self.assertFalse(any(call.get("cursor") for call in calls))
        self.assertEqual(2, self.captures)

    async def test_no_confirmed_subscription_or_support_never_reuses(self):
        for field in ("live", "supported"):
            with self.subTest(field=field):
                setattr(self, field, False)
                before = self.captures
                await self.read()
                await self.read()
                self.assertEqual(before + 2, self.captures)
                setattr(self, field, True)

    async def test_old_helper_keeps_ttl_behavior_without_barrier(self):
        original = self.exchange
        async def old(*args, **fields):
            result = await original(*args, **fields)
            return {key: value for key, value in result.items()
                    if key not in (*self.status(), "captured_event_counter")}
        self.hub.exchange = old
        await self.read()
        await self.read()
        self.assertEqual(1, self.captures)
        self.assertEqual(0, self.barriers)

    async def test_probe_compares_original_snapshot_without_refreshing(self):
        await self.read()
        ident = self.hub.snapshots["g"].by_helper["link"]
        self.enabled = True
        self.hub.changed("g")
        result = await self.read(inspect=ident)
        self.assertEqual("live enabled, snapshot disabled: stale", result["verdict"])
        self.assertFalse(result["cached"]["enabled"])
        self.assertEqual([1, 2, 30, 40], result["cached"]["bounds"])
        self.assertTrue(result["live"]["enabled"])
        self.assertFalse(result["event_counter_advanced_since_snapshot"])
        self.counter += 1
        delivered = await self.read(inspect=ident)
        self.assertTrue(delivered["event_counter_advanced_since_snapshot"])
        self.assertEqual(1, result["server_change_version"])
        self.assertEqual(0, result["snapshot_change_version"])
        self.assertEqual(1, self.captures)
        self.assertIn("error", await self.read(inspect="missing"))


class ProbeTests(unittest.TestCase):
    def test_verdicts(self):
        cached = {"enabled": False}
        self.assertIn("Chrome reports disabled", verdict(cached, cached, []))
        self.assertEqual("live enabled, snapshot disabled: stale", verdict({"enabled": True}, cached, []))
        self.assertEqual("live disabled, snapshot enabled: stale",
                         verdict(cached, {"enabled": True}, []))
        self.assertEqual("live enabled, snapshot disabled: stale",
                         verdict({"enabled": True}, cached, [{"name": "pane", "enabled": False}]))
        self.assertEqual("live disabled, snapshot enabled: stale",
                         verdict(cached, {"enabled": True}, [{"name": "pane", "enabled": False}]))
        self.assertEqual("live and snapshot agree: enabled",
                         verdict({"enabled": True}, {"enabled": True},
                                 [{"name": "pane", "enabled": False}]))
        self.assertEqual("ancestor region disabled", verdict(cached, cached,
                         [{"name": "region", "enabled": False}]))
        self.assertIn("enabled", verdict({"enabled": True}, {}, []))
        self.assertEqual("live state unavailable", verdict({}, {}, []))

    def test_probe_current_only_password_redaction_and_ancestors(self):
        class Node:
            def __init__(self, ident):
                self.ident = ident
                self.calls = []
            def GetCurrentPropertyValue(self, prop):
                self.calls.append(prop)
                return {30010: self.ident != 1, 30005: "region", 30096: 1,
                        30001: (1, 2, 3, 4)}.get(prop)
        nodes = [Node(i) for i in range(3)]
        provider = SimpleNamespace(root=lambda: nodes[0], same_window=lambda node: True,
            runtime_id=lambda node: [node.ident], password=lambda node: True,
            parent=lambda node: nodes[node.ident - 1])
        with patch("partyline_helper.uia_probe.find", return_value=nodes[2]):
            result = inspect(provider, "link")
        self.assertTrue(result["grant_root_reached"])
        self.assertEqual([False, True], [item["enabled"] for item in result["ancestors"]])
        self.assertTrue(result["live"]["legacy_unavailable"])
        self.assertIsNone(result["live"]["value"])
        self.assertNotIn(30045, nodes[2].calls)
        self.assertEqual([1, 2, 4, 6], result["live"]["bounds"])
        with patch("partyline_helper.uia_probe.find", return_value=None):
            self.assertIn("error", inspect(provider, "gone"))
        self.assertIsNone(current(SimpleNamespace(), 123))

    def test_counter_advances_on_callback_thread_before_push(self):
        state = EventState(clock=lambda: 7)
        state.subscription = SimpleNamespace(live=True)
        state.supported = True
        state.changed()
        self.assertEqual({"event_counter": 1, "last_event_time": 7, "events_supported": True,
                          "subscription_live": True}, state.status())
        state.subscription.live = False
        self.assertFalse(state.status()["subscription_live"])

    def test_property_scope_delivers_link_ancestor_and_descendant(self):
        automation = SimpleNamespace(AddPropertyChangedEventHandler=lambda *args: None,
                                     AddStructureChangedEventHandler=lambda *args: None)
        uia = SimpleNamespace(IUIAutomationPropertyChangedEventHandler=object,
                              IUIAutomationStructureChangedEventHandler=object)
        seen = []
        handlers = register_handlers(automation, uia, "grant-root", lambda: seen.append(1), object)
        prop = handlers[0][2]
        for sender in ("link", "aria-ancestor", "descendant"):
            prop.HandlePropertyChangedEvent(sender, 30010, True)
        self.assertEqual(3, len(seen))
        self.assertIn(30010, PROPERTIES)
        self.assertIn(30102, PROPERTIES)


class HelperStateTests(unittest.IsolatedAsyncioTestCase):
    async def test_callback_bumps_counter_before_loop_delivers_push_and_status_is_cheap(self):
        class Subscription:
            live = True
            def __init__(self, hwnd, changed):
                self.changed = changed
            def start(self):
                return True
            def close(self):
                self.live = False
        session = SimpleNamespace(send=AsyncMock())
        shares = WindowShares(session, event_factory=Subscription)
        access = SimpleNamespace()
        worker = SimpleNamespace(submit=AsyncMock())
        shares.grants["g"] = {"access": access, "worker": worker}
        await shares.start_events("g", 1)
        subscription = shares.grants["g"]["events"]
        subscription.changed()
        self.assertEqual(1, access.event_status()["event_counter"])
        session.send.assert_not_awaited()
        await shares.dispatch({"type": "read_window_elements", "grant_id": "g",
                               "request_id": "r", "event_status": True})
        self.assertEqual(1, session.send.await_args.kwargs["event_counter"])
        self.assertTrue(session.send.await_args.kwargs["subscription_live"])
        worker.submit.assert_not_awaited()
        # Drain the callback without a timer; cancel its coalesced notification at teardown.
        await asyncio.get_running_loop().run_in_executor(None, lambda: None)
        for timer in shares.event_timers.values():
            timer.cancel()

    async def test_helper_refuses_continuation_across_event_and_reads_probe_without_forgetting(self):
        grant = {"hwnd": 1, "pid": 2, "title": "Chrome", "process": "chrome"}
        session = SimpleNamespace(share=None, accepted=False)
        access = WindowAccess(session, platform="win32", list_windows=lambda: [grant])
        access.grant = grant
        status = {"event_counter": 1, "events_supported": True, "subscription_live": True}
        access.event_status = lambda: dict(status)
        access.event_counter = 0
        access.walks["c"] = {"stack": []}
        self.assertIn("inconsistent", (await access.snapshot({"cursor": "c"}))["elements_unavailable"])
        access.paths["link"] = [0]
        access.elements["link"] = {"name": "secret"}
        def reader(hwnd, **options):
            self.assertEqual({"id": "link", "path": [0]}, options["probe"])
            return {"live": {"enabled": True}}
        access.reader = reader
        result = await access.snapshot({"inspect": "link"})
        self.assertTrue(result["live"]["enabled"])
        self.assertEqual(1, result["event_counter"])
        self.assertIn("link", access.elements)
        self.assertIn("link", access.paths)
