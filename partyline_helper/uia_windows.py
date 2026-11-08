"""Windows UI Automation COM provider; loaded only in the isolated reader process."""
import ctypes

from .uia_patterns import PATTERN

# UIA property and pattern IDs are defined by UIAutomationClient.h.
PATTERNS = {10000: "Invoke", 10015: "Toggle", 10002: "Value", 10010: "SelectionItem",
            10005: "ExpandCollapse", 10003: "RangeValue", 10004: "Scroll", 10017: "ScrollItem",
            10009: "Window", 10016: "Transform"}
# UIA_Is<Pattern>PatternAvailablePropertyId, fetched for every node in one cached round trip.
AVAILABLE = {10000: 30031, 10015: 30041, 10002: 30043, 10010: 30036, 10005: 30028, 10003: 30033,
             10004: 30034, 10017: 30035, 10009: 30044, 10016: 30042}
EXPAND_STATES = {0: "collapsed", 1: "expanded", 2: "partial", 3: "leaf"}
WINDOW_STATES = {0: "normal", 1: "maximized", 2: "minimized"}
SCROLL_AMOUNT = {("up", "small"): (2, 1), ("up", "large"): (2, 0), ("down", "small"): (2, 4),
                 ("down", "large"): (2, 3), ("left", "small"): (1, 2), ("left", "large"): (0, 2),
                 ("right", "small"): (4, 2), ("right", "large"): (3, 2)}
NO_SCROLL = -1  # UIA_ScrollPatternNoScroll
TYPES = {50000: "Button", 50002: "CheckBox", 50003: "ComboBox", 50004: "Edit", 50005: "Hyperlink",
         50007: "ListItem", 50008: "List", 50009: "Menu", 50010: "MenuBar", 50011: "MenuItem",
         50012: "ProgressBar", 50013: "RadioButton", 50014: "ScrollBar", 50015: "Slider",
         50018: "Tab", 50019: "TabItem", 50020: "Text", 50021: "ToolBar", 50023: "Tree",
         50024: "TreeItem", 50025: "Custom", 50026: "Group", 50028: "DataGrid", 50029: "DataItem",
         50030: "Document", 50032: "Window", 50033: "Pane", 50034: "Header", 50036: "Table"}


class WindowsProvider:  # pragma: no cover - exercised in the Windows foundations job
    def __init__(self, hwnd):
        import comtypes.client
        ctypes.windll.user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))
        comtypes.client.GetModule("UIAutomationCore.dll")
        from comtypes.gen import UIAutomationClient as uia
        self.uia = uia
        self.automation = comtypes.client.CreateObject(uia.CUIAutomation, interface=uia.IUIAutomation)
        self.user32 = ctypes.windll.user32
        self.user32.GetAncestor.argtypes = [ctypes.c_void_p, ctypes.c_uint]
        self.user32.GetAncestor.restype = ctypes.c_void_p
        self.user32.IsWindow.argtypes = [ctypes.c_void_p]
        self.user32.GetForegroundWindow.restype = ctypes.c_void_p
        self.hwnd = hwnd
        if not self.hwnd:
            raise RuntimeError("no window")
        self.walker = self.automation.ControlViewWalker
        self.cache = self.automation.CreateCacheRequest()
        for prop in AVAILABLE.values():
            self.cache.AddProperty(prop)

    def foreground(self):
        return self.user32.GetForegroundWindow()

    def root(self):
        return self.automation.ElementFromHandleBuildCache(self.hwnd, self.cache)

    def runtime_id(self, node):
        return node.GetRuntimeId()

    def same_window(self, node):
        handle = node.CurrentNativeWindowHandle
        return not handle or self.user32.GetAncestor(handle, 2) == self.hwnd

    def offscreen(self, node):
        return bool(node.CurrentIsOffscreen)

    def password(self, node):
        return bool(node.CurrentIsPassword)

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
        return getattr(pattern, method)

    def current(self):
        return bool(self.user32.IsWindow(self.hwnd))

    def bounds(self, node):
        rect = node.CurrentBoundingRectangle
        return rect.left, rect.top, rect.right, rect.bottom

    def children(self, node):
        result = []
        child = self.walker.GetFirstChildElementBuildCache(node, self.cache)
        while child and len(result) < 200:
            result.append(child)
            child = self.walker.GetNextSiblingElementBuildCache(child, self.cache)
        return result

    def properties(self, node):
        patterns = [name for ident, name in PATTERNS.items() if self.available(node, ident)]
        result = {"control_type": TYPES.get(node.CurrentControlType, str(node.CurrentControlType)),
                  "name": node.CurrentName,
                  "automation_id": node.CurrentAutomationId,
                  "enabled": bool(node.CurrentIsEnabled), "focused": bool(node.CurrentHasKeyboardFocus),
                  "offscreen": bool(node.CurrentIsOffscreen), "patterns": patterns}
        if "Value" in patterns and not node.CurrentIsPassword:
            pattern = node.GetCurrentPattern(10002).QueryInterface(self.uia.IUIAutomationValuePattern)
            result["value"] = pattern.CurrentValue
        if "Toggle" in patterns:
            pattern = node.GetCurrentPattern(10015).QueryInterface(self.uia.IUIAutomationTogglePattern)
            result["toggle"] = int(pattern.CurrentToggleState)
        return result

    def available(self, node, ident):
        try:
            return bool(node.GetCachedPropertyValue(AVAILABLE[ident]))
        except Exception:  # not a cached element: ask the provider directly
            return bool(node.GetCurrentPattern(ident))

    def state(self, node, props):
        """Add the state the extra patterns expose, for an action target only (never a snapshot)."""
        try:
            self.pattern_state(node, props["patterns"], props)
        except Exception:  # a misbehaving provider only loses extra state; actions then fail closed
            pass

    def pattern_state(self, node, patterns, result):
        if "SelectionItem" in patterns:
            result["selected"] = bool(self.pattern(node, 10010, "SelectionItem").CurrentIsSelected)
        if "ExpandCollapse" in patterns:
            state = self.pattern(node, 10005, "ExpandCollapse").CurrentExpandCollapseState
            result["expand_state"] = EXPAND_STATES.get(int(state), "unknown")
        if "RangeValue" in patterns:
            pattern = self.pattern(node, 10003, "RangeValue")
            result.update(range_value=pattern.CurrentValue, range_min=pattern.CurrentMinimum,
                          range_max=pattern.CurrentMaximum, range_read_only=bool(pattern.CurrentIsReadOnly))
        if "Scroll" in patterns:
            pattern = self.pattern(node, 10004, "Scroll")
            result.update(h_scrollable=bool(pattern.CurrentHorizontallyScrollable),
                          v_scrollable=bool(pattern.CurrentVerticallyScrollable),
                          h_scroll_percent=pattern.CurrentHorizontalScrollPercent,
                          v_scroll_percent=pattern.CurrentVerticalScrollPercent)
        if "Window" in patterns:
            pattern = self.pattern(node, 10009, "Window")
            result.update(can_minimize=bool(pattern.CurrentCanMinimize),
                          can_maximize=bool(pattern.CurrentCanMaximize),
                          window_state=WINDOW_STATES.get(int(pattern.CurrentWindowVisualState), "unknown"))
        if "Transform" in patterns:
            pattern = self.pattern(node, 10016, "Transform")
            result.update(can_move=bool(pattern.CurrentCanMove), can_resize=bool(pattern.CurrentCanResize))
