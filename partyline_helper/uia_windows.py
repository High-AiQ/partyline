"""Windows UI Automation COM provider; loaded only in the isolated reader process."""
import ctypes

# UIA property and pattern IDs are defined by UIAutomationClient.h.
PATTERNS = {10000: "Invoke", 10015: "Toggle", 10002: "Value", 10010: "SelectionItem",
            10005: "ExpandCollapse"}
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

    def foreground(self):
        return self.user32.GetForegroundWindow()

    def root(self):
        return self.automation.ElementFromHandle(self.hwnd)

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

    def action_call(self, node, action, value=None):
        if action == "invoke":
            pattern = node.GetCurrentPattern(10000).QueryInterface(self.uia.IUIAutomationInvokePattern)
            return pattern.Invoke
        if action == "toggle":
            pattern = node.GetCurrentPattern(10015).QueryInterface(self.uia.IUIAutomationTogglePattern)
            return pattern.Toggle
        if action == "set_value":
            pattern = node.GetCurrentPattern(10002).QueryInterface(self.uia.IUIAutomationValuePattern)
            return lambda: pattern.SetValue(value)
        raise ValueError("unsupported action")

    def current(self):
        return bool(self.user32.IsWindow(self.hwnd))

    def bounds(self, node):
        rect = node.CurrentBoundingRectangle
        return rect.left, rect.top, rect.right, rect.bottom

    def children(self, node):
        result = []
        child = self.walker.GetFirstChildElement(node)
        while child and len(result) < 200:
            result.append(child)
            child = self.walker.GetNextSiblingElement(child)
        return result

    def properties(self, node):
        patterns = [name for ident, name in PATTERNS.items() if node.GetCurrentPattern(ident)]
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
