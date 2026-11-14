"""Element key delivery uses bounded HWND messages, with fake UIA and Win32 APIs."""
import ctypes
import inspect
import json
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from partyline_helper import uia_press
from partyline_helper.uia_action_worker import run_action
from partyline_helper.uia_gate import DispatchGate
from partyline_helper.uia_identity import element_id
from partyline_helper.uia_patterns import ActionRefused, supported
from tests.test_uia_patterns import PatternProvider


class Node(int):
    def __bool__(self):
        return True

    def SetFocus(self):
        if self.provider.focus_ignored:
            return
        self.provider.extra[self]["focused"] = True
        if self.provider.focus_error:
            raise RuntimeError("provider detail")
        if self.provider.activates:
            self.provider.foreground_hwnd = 1
        self.provider.after_focus()


class PressProvider(PatternProvider):
    def __init__(self, page=False):
        super().__init__({"patterns": ["Value"], "value": "old", "focusable": True})
        self.hwnd, self.focus_error, self.activates = 1, False, False
        self.focus_ignored = False
        self.after_focus = lambda: None
        self.user32 = Mock()
        self.handles = {0: 1, 1: 0}
        self.parents = {1: 0}
        self.kinds = {0: "Window", 1: "Edit"}
        self.extra[0]["name"] = "old title"
        self.walker = SimpleNamespace(GetParentElement=lambda node: self.node(self.parents[node])
                                     if node in self.parents else None)
        if page:
            self.nodes.append({"rect": (0, 0, 100, 100), "children": [1]})
            self.nodes[0]["children"] = [2]
            self.handles[2], self.parents[1], self.parents[2], self.kinds[2] = 0, 2, 0, "Document"
            self.extra[2] = {}

    def node(self, index):
        node = Node(index)
        node.provider = self
        return node

    def root(self):
        return self.node(0)

    def children(self, node):
        return [self.node(index) for index in super().children(node)]

    def prop(self, node, name):
        return self.handles[node]

    def properties(self, node):
        return {**super().properties(node), "control_type": self.kinds[node]}


class Messages:
    def __init__(self, chrome=False):
        self.chrome, self.calls, self.candidates = chrome, [], [3]
        self.valid, self.effect = True, lambda: None

    def belongs(self, hwnd, top):
        return self.valid and top == 1 and hwnd in (1, 3, 4)

    def class_name(self, hwnd):
        return "Chrome_WidgetWin_1" if hwnd == 1 and self.chrome else uia_press.RENDERER

    def renderers(self, top, bounds):
        return self.candidates

    def post(self, *args):
        self.calls.append(args)
        self.effect()
        return True


class PressTests(unittest.TestCase):
    def test_allowed_keys_reach_exact_hwnd_and_no_change_is_no_effect(self):
        for key, code in (("enter", 13), ("tab", 9), ("escape", 27)):
            provider, messages = PressProvider(), Messages()
            result = uia_press.press(provider, provider.node(1), key, messages)
            self.assertEqual("no_effect", result["status"])
            self.assertIn("hint", result)
            self.assertEqual(3, result["posted"])
            self.assertEqual([(1, message, code) for message in (0x100, 0x102, 0x101)],
                             [call[:3] for call in messages.calls])
            self.assertEqual(3 << 30, messages.calls[-1][3] & (3 << 30))
            self.assertEqual([], result["observation"]["changed"])
            self.assertTrue(result["observation"]["after"]["focused"])

    def test_disallowed_keys_refused_before_any_input(self):
        provider, messages = PressProvider(), Messages()
        for key in ("ctrl+enter", "a", "alt+tab", "", None):
            with self.assertRaises(ActionRefused):
                uia_press.press(provider, provider.node(1), key, messages)
        self.assertEqual([], messages.calls)
        self.assertIn("press", supported({"focusable": True}, False))

    def test_chrome_page_and_omnibox_use_different_hwnds(self):
        for page, hwnd in ((True, 3), (False, 1)):
            provider, messages = PressProvider(page), Messages(chrome=True)
            result = uia_press.press(provider, provider.node(1), "enter", messages)
            self.assertEqual(3, result["posted"])
            self.assertEqual({hwnd}, {call[0] for call in messages.calls})
        provider.handles[1] = 4
        self.assertEqual(4, uia_press.target_hwnd(provider, provider.node(1), Messages()))

    def test_renderer_ambiguity_missing_foreign_and_ancestor_renderer(self):
        for candidates in ([], [3, 4]):
            provider, messages = PressProvider(True), Messages(chrome=True)
            messages.candidates = candidates
            result = uia_press.press(provider, provider.node(1), "enter", messages)
            self.assertEqual("no_effect", result["status"])
            self.assertEqual([], messages.calls)
        provider.handles[2] = 3
        self.assertEqual(3, uia_press.target_hwnd(provider, provider.node(1), messages))
        provider.parents = {}
        self.assertIsNone(uia_press.target_hwnd(provider, provider.node(1), messages))
        self.assertIsNone(uia_press.submit_hint(provider, provider.node(1)))
        provider.nodes[1]["same"] = False
        self.assertEqual([], uia_press.ancestry(provider, provider.node(1)))

    def test_native_submit_hint_precedes_messages_and_does_not_invoke(self):
        provider, messages = PressProvider(), Messages()
        provider.nodes.append({"rect": (0, 0, 5, 5)})
        provider.nodes[0]["children"].append(2)
        provider.extra[2] = {"name": "Submit", "patterns": ["Invoke"], "enabled": True}
        provider.kinds[2] = "Button"
        result = uia_press.press(provider, provider.node(1), "enter", messages)
        self.assertEqual({"query": "Submit", "control_type": "Button"}, result["native_submit"])
        self.assertEqual("no_effect", result["status"])
        self.assertEqual([], messages.calls)
        self.assertEqual([], provider.calls)

    def test_observed_value_title_url_and_focus_changes(self):
        provider, messages = PressProvider(), Messages()
        provider.extra[1]["name"] = "Address and search bar"
        def effect():
            provider.extra[1].update(value="https://example.com/", focused=False)
            provider.extra[0]["name"] = "new title"
        messages.effect = effect
        result = uia_press.press(provider, provider.node(1), "enter", messages)
        self.assertEqual("completed", result["status"])
        self.assertNotIn("hint", result)
        self.assertEqual(["focused", "url", "value", "window_title"], result["observation"]["changed"])
        self.assertEqual("https://example.com/", result["observation"]["after"]["url"])
        provider.nodes[1]["password"] = True
        self.assertNotIn("value", uia_press.observe(provider, provider.node(1)))
        self.assertNotIn("url", uia_press.observe(provider, provider.node(1)))

    def test_failures_and_revocation_never_fall_back(self):
        for failure in ("focus_error", "focus_ignored", "activates", "invalid", "changed_hwnd", "post",
                        "inactive", "revoke"):
            provider, messages = PressProvider(), Messages()
            active = Mock(return_value=True)
            if failure in ("focus_error", "focus_ignored", "activates"):
                setattr(provider, failure, True)
            elif failure == "invalid":
                messages.valid = False
            elif failure == "changed_hwnd":
                provider.after_focus = lambda m=messages: setattr(m, "valid", False)
            elif failure == "post":
                messages.post = Mock(return_value=False)
            elif failure == "inactive":
                active.return_value = False
            elif failure == "revoke":
                active.side_effect = [True, False]
            with self.subTest(failure=failure):
                result = uia_press.press(provider, provider.node(1), "escape", messages, active)
                self.assertEqual("no_effect", result["status"])
                self.assertIn("hint", result)
                self.assertEqual([], messages.calls)

    def test_long_unicode_observations_fit_and_changes_beyond_preview_are_detected(self):
        for value in ("🦕" * 300, "\x00" * 300):
            provider, messages = PressProvider(), Messages()
            provider.extra[1]["value"] = value
            messages.effect = lambda p=provider, v=value: p.extra[1].update(value=v + "changed")
            result = uia_press.press(provider, provider.node(1), "enter", messages)
            self.assertEqual("completed", result["status"])
            self.assertEqual(["value"], result["observation"]["changed"])
            self.assertTrue(result["observation"]["truncated"])
            self.assertLess(len(json.dumps(result, ensure_ascii=False).encode()), 2000)

    def test_navigation_that_removes_target_still_reports_new_title(self):
        provider, messages = PressProvider(), Messages()
        original = provider.properties
        removed = [False]
        def properties(node):
            if node == 1 and removed[0]:
                raise RuntimeError("stale")
            return original(node)
        provider.properties = properties
        def effect():
            removed[0] = True
            provider.extra[0]["name"] = "new page"
        messages.effect = effect
        result = uia_press.press(provider, provider.node(1), "enter", messages)
        self.assertEqual("completed", result["status"])
        self.assertEqual(["window_title"], result["observation"]["changed"])

    def test_worker_keeps_no_effect_and_revocation_discards_observations(self):
        for revoke in (False, True):
            provider, messages = PressProvider(), Messages()
            gate = DispatchGate()
            generation = gate.grant()
            grant = {"hwnd": 1, "pid": 2}
            access = SimpleNamespace(gate=gate, list_windows=lambda g=grant: [g])
            if revoke:
                messages.effect = gate.invalidate
            with patch.object(uia_press, "WindowMessages", return_value=messages):
                result = run_action(access, grant, generation,
                    {"element_id": element_id(provider, provider.node(1), [0]),
                     "action": "press", "key": "enter"}, factory=lambda _, p=provider: p)
            if revoke:
                self.assertTrue(result["revoked_during"])
                self.assertNotIn("observation", result)
                self.assertEqual(1, len(messages.calls))
            else:
                self.assertEqual("no_effect", result["status"])
                self.assertEqual(3, result["posted"])

    def test_input_path_has_no_global_injection_activation_or_mouse_calls(self):
        from partyline_helper import uia_action_worker, uia_windows
        source = "\n".join(inspect.getsource(module) for module in
                           (uia_press, uia_action_worker, uia_windows))
        for forbidden in ("SendInput", "keybd_event", "mouse_event", "SetCursorPos", "PostThreadMessage"):
            self.assertNotIn(forbidden, source)
        for forbidden in ("SetForegroundWindow", "AttachThreadInput"):
            self.assertNotIn(forbidden, inspect.getsource(uia_press))


class WindowMessagesTests(unittest.TestCase):
    def test_native_wrapper_uses_pointer_sized_handles_and_scoped_renderers(self):
        top, child = 2**40, 2**40 + 1
        api = SimpleNamespace(**{name: Mock() for name in
            ("PostMessageW", "GetClassNameW", "GetAncestor", "GetWindowRect",
             "IsWindow", "EnumChildWindows")})
        api.GetAncestor.return_value = top
        api.IsWindow.return_value = True
        def class_name(hwnd, buf, length):
            buf.value = uia_press.RENDERER
            return 1
        api.GetClassNameW.side_effect = class_name
        def rect(hwnd, pointer):
            pointer._obj.left, pointer._obj.top, pointer._obj.right, pointer._obj.bottom = 0, 0, 20, 20
            return True
        api.GetWindowRect.side_effect = rect
        api.EnumChildWindows.side_effect = lambda hwnd, callback, data: callback(child, data)
        with patch.object(ctypes, "WINFUNCTYPE", ctypes.CFUNCTYPE, create=True):
            messages = uia_press.WindowMessages(api)
        self.assertFalse(messages.belongs(0, top))
        self.assertFalse(messages.belongs(0xFFFF, top))
        self.assertTrue(messages.belongs(child, top))
        self.assertEqual([child], messages.renderers(top, (1, 1, 3, 3)))
        self.assertEqual([], messages.renderers(top, (40, 40, 50, 50)))
        self.assertTrue(messages.post(child, 0x100, 13, 1))
        api.PostMessageW.assert_called_once_with(child, 0x100, 13, 1)
        self.assertEqual(ctypes.sizeof(ctypes.c_void_p), ctypes.sizeof(api.PostMessageW.argtypes[0]))
