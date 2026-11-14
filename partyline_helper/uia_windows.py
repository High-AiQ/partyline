"""Windows UI Automation COM provider; loaded only in the isolated reader process."""
import ctypes

from .uia_patterns import PATTERN
from .uia_pattern_state import PatternState
from .uia_press_state import PressState
from .uia_com_timing import track
from .uia_popups import WindowScope, configure, popup_name
from .uia_expand_events import structure_call

PATTERNS = {10000: "Invoke", 10015: "Toggle", 10002: "Value", 10010: "SelectionItem",
            10005: "ExpandCollapse", 10003: "RangeValue", 10004: "Scroll", 10017: "ScrollItem",
            10009: "Window", 10016: "Transform", 10018: "LegacyIAccessible"}
# UIA_Is<Pattern>PatternAvailablePropertyId, fetched for every node in one cached round trip.
AVAILABLE = {10000: 30031, 10015: 30041, 10002: 30043, 10010: 30036, 10005: 30028, 10003: 30033,
             10004: 30034, 10017: 30035, 10009: 30044, 10016: 30042, 10018: 30090}
# Properties a snapshot reads for every node, fetched with it so each node costs no further round trips.
CACHED = {"RuntimeId": 30000, "BoundingRectangle": 30001, "ControlType": 30003, "Name": 30005,
          "HasKeyboardFocus": 30008,
          "IsEnabled": 30010, "AutomationId": 30011, "IsPassword": 30019, "NativeWindowHandle": 30020,
          "IsOffscreen": 30022, "ProcessId": 30002, "AriaProperties": 30102, "IsKeyboardFocusable": 30009}
PATTERN_STATE = {"value": 30045, "toggle": 30086, "selected": 30079, "expand_state": 30070}
SUBTREE, SHALLOW = 7, 3  # TreeScope_Subtree; TreeScope_Element | TreeScope_Children
MAX_CHILDREN = 20000  # runaway guard for one node's children; far beyond any real list
EXPAND_STATES = {0: "collapsed", 1: "expanded", 2: "partial", 3: "leaf"}
SCROLL_AMOUNT = {("up", "small"): (2, 1), ("up", "large"): (2, 0), ("down", "small"): (2, 4),
                 ("down", "large"): (2, 3), ("left", "small"): (1, 2), ("left", "large"): (0, 2),
                 ("right", "small"): (4, 2), ("right", "large"): (3, 2)}
NO_SCROLL = -1  # UIA_ScrollPatternNoScroll
TYPES = {50000: "Button", 50002: "CheckBox", 50003: "ComboBox", 50004: "Edit", 50005: "Hyperlink",
         50007: "ListItem", 50008: "List", 50009: "Menu", 50010: "MenuBar", 50011: "MenuItem",
         50012: "ProgressBar", 50013: "RadioButton", 50014: "ScrollBar", 50015: "Slider",
         50018: "Tab", 50019: "TabItem", 50020: "Text", 50021: "ToolBar", 50023: "Tree",
         50024: "TreeItem", 50025: "Custom", 50026: "Group", 50028: "DataGrid", 50029: "DataItem",
         50030: "Document", 50032: "Window", 50033: "Pane", 50034: "Header", 50036: "Table",
         50037: "TitleBar"}


class WindowsProvider(PatternState, PressState):  # pragma: no cover - Windows foundations job
    com_calls = 0

    def __init__(self, hwnd, cached=False, deep=False):
        import comtypes.client
        ctypes.windll.user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))
        comtypes.client.GetModule("UIAutomationCore.dll")
        from comtypes.gen import UIAutomationClient as uia
        self.com_calls = 0
        self.uia = uia
        self.automation = track(comtypes.client.CreateObject(
            uia.CUIAutomation, interface=uia.IUIAutomation), self)
        self.user32 = ctypes.windll.user32
        self.user32.GetAncestor.argtypes = [ctypes.c_void_p, ctypes.c_uint]
        self.user32.GetAncestor.restype = ctypes.c_void_p
        self.user32.IsWindow.argtypes = [ctypes.c_void_p]
        self.user32.GetForegroundWindow.restype = ctypes.c_void_p
        configure(self.user32)
        self.scope = WindowScope(self.user32, hwnd)
        self.popup_roots = None
        self.popup_nodes = {}
        self.hwnd = hwnd
        self.top = None
        if not self.hwnd:
            raise RuntimeError("no window")
        self.walker = self.automation.ControlViewWalker
        # Both requests follow the control view, so cached child indices match the live walker's.
        self.cache = self.request(SUBTREE)  # the whole tree under a node in one cross-process call
        self.shallow = self.request(SHALLOW)  # a node and its direct children, one call per parent
        self.deep = deep  # a first snapshot part prefetches the window's whole tree
        self.cached = cached  # snapshots read the cache; action rechecks always read live state

    def request(self, scope):
        cache = self.automation.CreateCacheRequest()
        for prop in (*AVAILABLE.values(), *CACHED.values(), *PATTERN_STATE.values()):
            cache.AddProperty(prop)
        cache.TreeScope = scope
        cache.TreeFilter = self.automation.ControlViewCondition
        return cache

    def prop(self, node, name):
        if self.cached:
            try:
                return getattr(node, f"Cached{name}")
            except Exception:  # not a cached element: ask the provider directly
                pass
        return getattr(node, f"Current{name}")

    def foreground(self):
        return self.user32.GetForegroundWindow()

    def restore_foreground(self, hwnd, expected_current):
        """Restore the prior foreground and z-order if the action's window is still active."""
        if not hwnd or self.foreground() != expected_current:
            return False
        kernel32 = ctypes.windll.kernel32
        kernel32.GetCurrentThreadId.restype = ctypes.c_ulong
        current_thread = kernel32.GetCurrentThreadId()
        self.user32.GetWindowThreadProcessId.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
        self.user32.GetWindowThreadProcessId.restype = ctypes.c_ulong
        self.user32.AttachThreadInput.argtypes = [ctypes.c_ulong, ctypes.c_ulong, ctypes.c_bool]
        self.user32.AttachThreadInput.restype = ctypes.c_bool
        foreground_thread = self.user32.GetWindowThreadProcessId(expected_current, None)
        attached = bool(foreground_thread and foreground_thread != current_thread and
                        self.user32.AttachThreadInput(current_thread, foreground_thread, True))
        if self.foreground() != expected_current:
            if attached:
                self.user32.AttachThreadInput(current_thread, foreground_thread, False)
            return False
        self.user32.SetWindowPos.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_int,
                                             ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_uint]
        self.user32.SetWindowPos.restype = ctypes.c_bool
        # Restore the prior top-of-band order without activating until SetForegroundWindow below.
        ordered = self.user32.SetWindowPos(hwnd, None, 0, 0, 0, 0, 0x0001 | 0x0002 | 0x0010)
        self.user32.SetForegroundWindow.argtypes = [ctypes.c_void_p]
        self.user32.SetForegroundWindow.restype = ctypes.c_bool
        try:
            activated = self.user32.SetForegroundWindow(hwnd) if ordered else False
            return bool(activated and self.foreground() == hwnd)
        finally:
            if attached:
                self.user32.AttachThreadInput(current_thread, foreground_thread, False)

    def root(self):
        """The window element; the first call fetches the cache, so a deep prefetch happens once."""
        if self.top is None:
            cache = self.cache if self.deep else self.shallow
            self.top = self.automation.ElementFromHandleBuildCache(self.hwnd, cache)
        return self.top

    def runtime_id(self, node):
        if self.cached:
            try:
                return node.GetCachedPropertyValue(30000)
            except Exception:
                pass  # live ancestor supplied by a walker rather than a cache request
        return node.GetRuntimeId()

    def same_window(self, node):
        handle = self.prop(node, "NativeWindowHandle")
        popup = self.popup_nodes.get(tuple(self.runtime_id(node)))
        if popup is not None:
            return (self.prop(node, "ProcessId") == self.scope.process(popup) and self.scope.accepts(popup)
                    and (not handle or self.scope.accepts(handle)))
        if not handle or self.user32.GetAncestor(handle, 2) == self.hwnd:
            return True  # granted subtree can contain hosted content from another process
        accepted = self.prop(node, "ProcessId") == self.scope.process(handle) and self.scope.accepts(handle)
        if accepted:
            self.popup_nodes[tuple(self.runtime_id(node))] = self.user32.GetAncestor(handle, 2)
        return accepted

    def offscreen(self, node):
        return bool(self.prop(node, "IsOffscreen"))
    def password(self, node):
        return bool(self.prop(node, "IsPassword"))
    def read_only(self, node):
        pattern = node.GetCurrentPattern(10002).QueryInterface(self.uia.IUIAutomationValuePattern)
        return bool(pattern.CurrentIsReadOnly)
    def pattern(self, node, ident, name):
        return node.GetCurrentPattern(ident).QueryInterface(getattr(self.uia, f"IUIAutomation{name}Pattern"))

    def action_call(self, node, action, arg=None):
        """Bind the pattern method now; `arg` is the set_value text or a dict of validated parameters."""
        if action == "set_value":
            pattern = self.pattern(node, 10002, "Value")
            return lambda: pattern.SetValue(arg)
        pattern_id = {name: ident for ident, name in PATTERNS.items()}[PATTERN[action]]
        pattern = self.pattern(node, pattern_id, PATTERN[action])
        if action == "scroll":
            # ScrollAmount: 0 large-, 1 small-, 2 none, 3 large+, 4 small+
            horizontal, vertical = SCROLL_AMOUNT[(arg["direction"], arg["amount"])]
            return lambda: pattern.Scroll(horizontal, vertical)
        if action == "set_scroll_percent":
            return lambda: pattern.SetScrollPercent(arg.get("horizontal_percent", NO_SCROLL),
                                                    arg.get("vertical_percent", NO_SCROLL))
        if action == "set_range_value":
            return lambda: pattern.SetValue(float(arg["number"]))
        if action == "window_move":
            return lambda: pattern.Move(arg["x"], arg["y"])
        if action == "window_resize":
            return lambda: pattern.Resize(arg["width"], arg["height"])
        states = {"window_minimize": 2, "window_maximize": 1, "window_restore": 0}
        if action in states:
            return lambda: pattern.SetWindowVisualState(states[action])
        method = {"invoke": "Invoke", "toggle": "Toggle", "select": "Select",
                  "add_to_selection": "AddToSelection", "remove_from_selection": "RemoveFromSelection",
                  "expand": "Expand", "collapse": "Collapse", "scroll_into_view": "ScrollIntoView",
                  "window_close": "Close"}[action]
        call = getattr(pattern, method)
        return structure_call(self.hwnd, call) if action == "expand" else call

    def default_action(self, node):
        return self.pattern(node, 10018, "LegacyIAccessible").DoDefaultAction()

    def current(self):
        return bool(self.user32.IsWindow(self.hwnd))

    def bounds(self, node):
        rect = self.prop(node, "BoundingRectangle")
        return rect.left, rect.top, rect.right, rect.bottom

    def parent(self, node):
        return self.walker.GetParentElement(node)

    def option_container(self, node):
        return self.prop(node, "ControlType") in (50008, 50009)  # List or Menu

    def popups(self):
        if self.popup_roots is None:
            cache = self.cache if self.deep else self.shallow
            self.popup_roots = [self.automation.ElementFromHandleBuildCache(hwnd, cache)
                                for hwnd in self.scope.popups()]
        for node in self.popup_roots:
            self.popup_nodes[tuple(self.runtime_id(node))] = self.prop(node, "NativeWindowHandle")
        return [node for node in self.popup_roots if self.same_window(node)]

    def refresh(self):
        self.top, self.popup_roots = None, None
        self.__dict__.pop("_popup_names", None)

    def children(self, node):
        """Control-view children by index; the snapshot and the action recheck both use this."""
        is_root = self.prop(node, "NativeWindowHandle") == self.hwnd
        if not self.deep:  # a node's own children are cached only by asking for them: one call per parent
            node = node.BuildUpdatedCache(self.shallow)
        found = node.GetCachedChildren()  # deep mode: the Subtree request already cached every level
        children = ([found.GetElement(index) for index in range(min(found.Length, MAX_CHILDREN))]
                    if found else [])
        popup = self.popup_nodes.get(tuple(self.runtime_id(node)))
        if popup is not None:
            for child in children:
                self.popup_nodes[tuple(self.runtime_id(child))] = popup
        if is_root:
            known = {self.prop(child, "NativeWindowHandle") for child in children}
            children.extend(popup for popup in self.popups()
                            if self.prop(popup, "NativeWindowHandle") not in known)
        return children

    def properties(self, node):
        control = self.prop(node, "ControlType")
        # Legacy is only a link/button fallback, not a reason to retain every unnamed wrapper.
        patterns = [name for ident, name in PATTERNS.items() if self.available(node, ident)
                    and (name != "LegacyIAccessible" or control in (50000, 50005))]
        result = {"control_type": TYPES.get(control, str(control)),
                  "name": self.prop(node, "Name"), "automation_id": self.prop(node, "AutomationId"),
                  "enabled": bool(self.prop(node, "IsEnabled")),
                  "focused": bool(self.prop(node, "HasKeyboardFocus")),
                  "focusable": bool(self.prop(node, "IsKeyboardFocusable")),
                  "offscreen": bool(self.prop(node, "IsOffscreen")), "patterns": patterns}
        if name := popup_name(self, node):
            result["scope_window"] = name
        if not result["enabled"]:
            result["aria_properties"] = str(self.prop(node, "AriaProperties") or "")[:160]
        handle = self.prop(node, "NativeWindowHandle")
        if handle and handle != self.hwnd and self.user32.GetAncestor(handle, 2) == handle:
            result["name"] = "popup: " + (result["name"] or result["control_type"])
        if "Value" in patterns and not self.prop(node, "IsPassword"):
            result["value"] = self.state_value(node, "value", 10002, "Value", "CurrentValue")
        if "Toggle" in patterns:
            result["toggle"] = int(self.state_value(node, "toggle", 10015, "Toggle", "CurrentToggleState"))
        if "SelectionItem" in patterns:
            result["selected"] = bool(self.state_value(node, "selected", 10010, "SelectionItem",
                                                       "CurrentIsSelected"))
        if "ExpandCollapse" in patterns:
            state = self.state_value(node, "expand_state", 10005, "ExpandCollapse",
                                     "CurrentExpandCollapseState")
            result["expand_state"] = EXPAND_STATES.get(int(state), "unknown")
        return result

    def state_value(self, node, key, ident, name, attribute):
        if self.cached:
            try:
                return node.GetCachedPropertyValue(PATTERN_STATE[key])
            except Exception:  # not cached on this element: ask the pattern
                pass
        return getattr(self.pattern(node, ident, name), attribute)

    def available(self, node, ident):
        try:
            return bool(node.GetCachedPropertyValue(AVAILABLE[ident]))
        except Exception:  # not a cached element: ask the provider directly
            return bool(node.GetCurrentPattern(ident))
