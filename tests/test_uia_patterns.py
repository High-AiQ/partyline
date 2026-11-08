"""Validation, gating and audit of the pattern actions beyond invoke, toggle and set_value."""
import json
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

from partyline_helper.uia_action import prepare
from partyline_helper.uia_action_worker import ActionWorker, audit, run_action
from partyline_helper.uia_gate import DispatchGate
from partyline_helper.uia_identity import element_id
from partyline_helper.uia_patterns import ActionRefused, argument, check_argument, supported
from partyline_helper.uia_snapshot import snapshot
from tests.test_uia_snapshot import Provider

WINDOW = {"patterns": ["Window", "Transform"], "can_minimize": True, "can_maximize": True,
          "can_move": True, "can_resize": True}


class PatternProvider(Provider):
    """Two-node tree: node 0 is the window, node 1 a child whose properties come from `props`."""

    def __init__(self, child=None, window=None):
        super().__init__([{"rect": (0, 0, 100, 100), "children": [1]}, {"rect": (0, 0, 5, 5)}])
        self.extra = {0: window or WINDOW, 1: child or {}}
        self.calls, self.foreground_hwnd, self.alive = [], 99, True

    def properties(self, node):
        result = super().properties(node)
        result.update({"patterns": [], **self.extra[node]})
        return result

    def read_only(self, node):
        return False

    def foreground(self):
        return self.foreground_hwnd

    def current(self):
        return self.alive

    def action_call(self, node, action, arg):
        return lambda: self.calls.append((node, action, arg))

    def child(self):
        return element_id(self, 1, [0])

    def window(self):
        return element_id(self, 0, [])


class ArgumentTests(unittest.TestCase):
    def test_valid_and_invalid_arguments(self):
        good = [("scroll", {"direction": "up", "amount": "large"}),
                ("set_scroll_percent", {"vertical_percent": 0}),
                ("set_scroll_percent", {"horizontal_percent": 50.5, "vertical_percent": 100}),
                ("set_range_value", {"number": -3.5}), ("window_move", {"x": -1920, "y": 0}),
                ("window_resize", {"width": 640, "height": 480}), ("window_close", {}), ("select", None)]
        for action, arg in good:
            with self.subTest(action=action, arg=arg):
                check_argument(action, arg)
        bad = [("scroll", {"direction": "sideways", "amount": "small"}),
               ("scroll", {"direction": "up"}), ("scroll", {"direction": "up", "amount": "small", "x": 1}),
               ("set_scroll_percent", {}), ("set_scroll_percent", {"vertical_percent": 101}),
               ("set_scroll_percent", {"vertical_percent": True}),
               ("set_range_value", {}), ("set_range_value", {"number": float("nan")}),
               ("set_range_value", {"number": float("inf")}), ("set_range_value", {"number": True}),
               ("window_move", {"x": 1}), ("window_move", {"x": 1.5, "y": 0}),
               ("window_move", {"x": 40000, "y": 0}), ("window_resize", {"width": 0, "height": 5}),
               ("window_resize", {"width": 99999, "height": 5}), ("select", {"x": 1}),
               ("set_value", None), ("drag", {}), ("window_close", {"number": 1})]
        for action, arg in bad:
            with self.subTest(action=action, arg=arg), self.assertRaises(ActionRefused):
                check_argument(action, arg)

    def test_argument_extraction_ignores_unknown_and_null_fields(self):
        message = {"action": "scroll", "direction": "down", "amount": "small", "value": "x", "x": None,
                   "evil": 1}
        self.assertEqual({"direction": "down", "amount": "small"}, argument(message))
        self.assertEqual("t", argument({"action": "set_value", "value": "t", "x": 3}))


class PrepareTests(unittest.TestCase):
    def refused(self, provider, target, action, arg=None):
        with self.assertRaises(ActionRefused) as raised:
            prepare(provider, target, action, arg)
        return str(raised.exception)

    def test_missing_pattern_names_supported_actions(self):
        provider = PatternProvider({"patterns": ["Invoke", "ExpandCollapse"]})
        message = self.refused(provider, provider.child(), "select")
        self.assertIn("select", message)
        self.assertIn("it supports: invoke, expand, collapse", message)
        bare = PatternProvider({"patterns": []})
        self.assertIn("no actions", self.refused(bare, bare.child(), "scroll_into_view"))

    def test_each_pattern_action_is_allowed_with_its_pattern(self):
        cases = {"select": "SelectionItem", "add_to_selection": "SelectionItem",
                 "remove_from_selection": "SelectionItem", "expand": "ExpandCollapse",
                 "collapse": "ExpandCollapse", "scroll_into_view": "ScrollItem"}
        for action, pattern in cases.items():
            with self.subTest(action=action):
                provider = PatternProvider({"patterns": [pattern]})
                self.assertEqual(1, prepare(provider, provider.child(), action, {})[0])

    def test_disabled_and_stale_are_refused(self):
        provider = PatternProvider({"patterns": ["SelectionItem"]})
        target = provider.child()
        original = provider.properties
        provider.properties = lambda node: {**original(node), "enabled": False}
        self.assertIn("disabled", self.refused(provider, target, "select", {}))
        self.assertIn("stale", self.refused(provider, "0" * 64, "select", {}))

    def test_expand_refuses_leaf_nodes(self):
        provider = PatternProvider({"patterns": ["ExpandCollapse"], "expand_state": "leaf"})
        self.assertIn("nothing to expand", self.refused(provider, provider.child(), "expand", {}))
        provider.extra[1]["expand_state"] = "collapsed"
        prepare(provider, provider.child(), "expand", {})

    def test_scroll_honours_scrollable_axes(self):
        provider = PatternProvider({"patterns": ["Scroll"], "v_scrollable": True, "h_scrollable": False})
        target = provider.child()
        prepare(provider, target, "scroll", {"direction": "down", "amount": "small"})
        for arg in ({"direction": "left", "amount": "small"}, {"direction": "right", "amount": "large"}):
            self.assertIn("cannot scroll", self.refused(provider, target, "scroll", arg))
        prepare(provider, target, "set_scroll_percent", {"vertical_percent": 10})
        self.assertIn("horizontal_percent", self.refused(provider, target, "set_scroll_percent",
                                                         {"horizontal_percent": 10}))

    def test_range_value_is_bounded_and_refused_when_read_only(self):
        child = {"patterns": ["RangeValue"], "range_min": 0, "range_max": 10, "range_read_only": False}
        provider = PatternProvider(child)
        target = provider.child()
        for number in (0, 5.5, 10):
            prepare(provider, target, "set_range_value", {"number": number})
        for number in (-0.1, 10.01):
            self.assertIn("between 0 and 10", self.refused(provider, target, "set_range_value",
                                                           {"number": number}))
        provider.extra[1]["range_read_only"] = True
        self.assertIn("read-only", self.refused(provider, target, "set_range_value", {"number": 1}))
        provider.extra[1].update(range_read_only=False, range_min=None)
        self.assertIn("unavailable", self.refused(provider, target, "set_range_value", {"number": 1}))

    def test_window_actions_only_on_the_shared_window(self):
        provider = PatternProvider({"patterns": ["Window", "Transform"], **{k: True for k in WINDOW
                                                                            if k.startswith("can")}})
        for action, arg in (("window_close", {}), ("window_minimize", {}), ("window_maximize", {}),
                            ("window_restore", {}), ("window_move", {"x": 1, "y": 2}),
                            ("window_resize", {"width": 10, "height": 10})):
            with self.subTest(action=action):
                self.assertEqual(0, prepare(provider, provider.window(), action, arg)[0])
                self.assertIn("only to the shared window",
                              self.refused(provider, provider.child(), action, arg))
        plain = PatternProvider({"patterns": ["Invoke"]})
        self.assertIn("it supports: invoke", self.refused(plain, plain.child(), "window_close", {}))

    def test_window_flags_are_honoured(self):
        for action, arg, flag in (("window_minimize", {}, "can_minimize"),
                                  ("window_maximize", {}, "can_maximize"),
                                  ("window_move", {"x": 1, "y": 2}, "can_move"),
                                  ("window_resize", {"width": 9, "height": 9}, "can_resize")):
            with self.subTest(action=action):
                provider = PatternProvider(window={**WINDOW, flag: False})
                self.assertIn("cannot be", self.refused(provider, provider.window(), action, arg))
        provider = PatternProvider(window={**WINDOW, "can_minimize": False, "can_maximize": False})
        prepare(provider, provider.window(), "window_restore", {})
        prepare(provider, provider.window(), "window_close", {})

    def test_supported_lists_window_actions_only_for_the_window(self):
        props = {"patterns": ["Window", "Transform", "Invoke"]}
        self.assertEqual(["invoke"], supported(props, False))
        self.assertEqual(["invoke", "window_close", "window_minimize", "window_maximize", "window_restore",
                          "window_move", "window_resize"], supported(props, True))

    def test_snapshot_lists_supported_actions(self):
        provider = PatternProvider({"patterns": ["Scroll", "ScrollItem"]})
        items = snapshot(provider, clock=lambda: 0)["elements"]
        self.assertIn("window_close", items[0]["actions"])
        self.assertEqual(["scroll", "set_scroll_percent", "scroll_into_view"], items[1]["actions"])
        self.assertNotIn("actions", snapshot(PatternProvider({}), clock=lambda: 0)["elements"][1])


class RunTests(unittest.IsolatedAsyncioTestCase):
    def run_one(self, provider, target, action, **fields):
        gate = DispatchGate()
        generation = gate.grant()
        grant = {"hwnd": 1, "pid": 2, "process": "app"}
        access = SimpleNamespace(gate=gate, list_windows=lambda: [grant])
        message = {"element_id": target, "action": action, **fields}
        return run_action(access, grant, generation, message, factory=lambda _: provider), message, grant

    async def test_pattern_call_receives_validated_parameters_and_new_state(self):
        provider = PatternProvider({"patterns": ["Scroll"], "v_scrollable": True, "v_scroll_percent": 40})
        result, message, grant = self.run_one(provider, provider.child(), "scroll", direction="down",
                                              amount="large", value="ignored", x=None)
        self.assertEqual("completed", result["status"])
        self.assertEqual([(1, "scroll", {"direction": "down", "amount": "large"})], provider.calls)
        self.assertEqual(40, result["element"]["v_scroll_percent"])
        self.assertIn("foreground_changed", result)
        sink = Mock()
        audit(SimpleNamespace(tools=SimpleNamespace(audit=sink)), grant, message, {"name": "pane"}, result)
        entry = json.loads(sink.append.call_args.args[4])
        self.assertEqual({"direction": "down", "amount": "large"}, entry["params"])

    async def test_refusals_are_reported_verbatim_and_do_not_dispatch(self):
        provider = PatternProvider({"patterns": ["Invoke"]})
        result, _, _ = self.run_one(provider, provider.child(), "expand")
        self.assertEqual("failed", result["status"])
        self.assertIn("it supports: invoke", result["error"])
        self.assertEqual([], provider.calls)
        provider = PatternProvider({"patterns": ["RangeValue"], "range_min": 0, "range_max": 1,
                                    "range_read_only": False})
        result, _, _ = self.run_one(provider, provider.child(), "set_range_value", number=2)
        self.assertEqual("value must be between 0 and 1", result["error"])
        self.assertEqual([], provider.calls)

    async def test_window_move_rereads_bounds(self):
        provider = PatternProvider()
        result, _, _ = self.run_one(provider, provider.window(), "window_move", x=10, y=20)
        self.assertEqual("completed", result["status"])
        self.assertEqual([(0, "window_move", {"x": 10, "y": 20})], provider.calls)
        self.assertEqual([0, 0, 100, 100], result["element"]["bounds"])

    async def test_unexpected_provider_error_is_generic(self):
        provider = PatternProvider({"patterns": ["SelectionItem"]})
        provider.action_call = Mock(side_effect=ValueError("secret detail"))
        result, _, _ = self.run_one(provider, provider.child(), "select")
        self.assertEqual("UI Automation failed", result["error"])

    async def test_close_reports_whether_the_window_went_away(self):
        for alive in (True, False):
            with self.subTest(alive=alive):
                provider = PatternProvider()
                provider.action_call = lambda *_, p=provider, a=alive: (
                    lambda: setattr(p, "alive", a) or p.calls.append("close"))
                result, message, grant = self.run_one(provider, provider.window(), "window_close")
                self.assertEqual("completed", result["status"])
                self.assertTrue(result["close_requested"])
                self.assertIs(result["window_closed"], not alive)
                self.assertNotIn("element", result)
                sink = Mock()
                audit(SimpleNamespace(tools=SimpleNamespace(audit=sink)), grant, message, {}, result)
                self.assertIs(json.loads(sink.append.call_args.args[4])["window_closed"], not alive)

    async def test_close_that_removes_the_window_ends_the_grant(self):
        for closed in (True, False):
            with self.subTest(closed=closed):
                gate = DispatchGate()
                gate.grant()
                grant = {"hwnd": 1, "pid": 2, "process": "app"}
                access = SimpleNamespace(gate=gate, grant=grant, elements={"w": {"name": "win"}},
                                         revoke=Mock())
                audit_log = SimpleNamespace(ensure_writable=Mock(), append=Mock())
                session = SimpleNamespace(window=access, accepted=True, share={"share_id": "s"},
                                          control=SimpleNamespace(granted=True), send=AsyncMock(),
                                          tools=SimpleNamespace(audit=audit_log))
                def runner(*_, closed=closed):
                    return {"status": "completed", "close_requested": True, "window_closed": closed}
                result = await ActionWorker(session, runner=runner).perform(
                    {"element_id": "w", "action": "window_close", "share_id": "s"})
                self.assertEqual("completed", result["status"])
                if closed:
                    access.revoke.assert_called_once_with("window closed")
                else:
                    access.revoke.assert_not_called()
                audit_log.append.assert_called_once()
