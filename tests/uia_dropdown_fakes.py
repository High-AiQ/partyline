"""Chrome-shaped fake COM tree: options live in a separate owned top-level window."""
from types import SimpleNamespace

from partyline_helper.uia_popups import WindowScope
from partyline_helper.uia_windows import WindowsProvider


class User:
    def __init__(self):
        self.pids = {1: 10, 2: 10, 3: 10, 4: 10, 5: 20, 6: 10, 7: 10}
        self.owners = {2: 1, 4: 2, 5: 1, 6: 7, 7: 6}
        self.visible = {1, 3, 4, 5, 6, 7}

    def GetWindowThreadProcessId(self, hwnd, pointer):
        pointer._obj.value = self.pids.get(hwnd, 0)

    def GetWindow(self, hwnd, flag):
        assert flag == 4
        return self.owners.get(hwnd, 0)

    def GetAncestor(self, hwnd, flag):
        assert flag == 2
        return hwnd if hwnd in self.pids else 0

    def IsWindowVisible(self, hwnd):
        return hwnd in self.visible


class Node:
    def __init__(self, ident, handle, kind, name, patterns=(), **state):
        self.ident, self.kids, self.state = ident, [], state
        self.props = dict(NativeWindowHandle=handle, ProcessId=10, ControlType=kind, Name=name,
                          AutomationId="", IsEnabled=True, HasKeyboardFocus=False, IsOffscreen=False,
                          IsPassword=False, AriaProperties="", IsKeyboardFocusable=False,
                          BoundingRectangle=SimpleNamespace(left=0, top=0, right=100, bottom=20))
        self.patterns = patterns

    def GetRuntimeId(self):
        return [self.ident]

    def BuildUpdatedCache(self, cache):
        return self

    def GetCachedChildren(self):
        return SimpleNamespace(Length=len(self.kids), GetElement=self.kids.__getitem__)


class Chrome(WindowsProvider):
    """Exercise the production scope, children, popup labelling and property reads with fake COM."""
    def __init__(self):
        self.user32, self.hwnd = User(), 1
        self.scope = WindowScope(self.user32, 1, lambda: list(self.user32.pids),
                                 image_path=lambda pid: {10: "chrome", 20: "other"}.get(pid),
                                 class_name=lambda hwnd: "#32770")
        self.cached, self.deep, self.cache, self.shallow = False, False, None, None
        self.top, self.popup_roots = None, None
        self.popup_nodes = {}
        self.window = Node(1, 1, 50032, "Chrome dropdown fixture")
        self.combo = Node(10, 0, 50003, "Choose a marketplace…", ("Value", "ExpandCollapse"),
                          value="shop.us", expand_state="collapsed")
        self.popup = Node(2, 2, 50008, "")
        self.first = Node(20, 0, 50007, "shop.us", ("SelectionItem",), selected=True)
        self.second = Node(21, 0, 50007, "shop.uk", ("SelectionItem",), selected=False)
        self.popup.kids = [self.first, self.second]
        self.window.kids = [self.combo]
        self.other = Node(3, 3, 50032, "Unrelated Chrome window")
        self.handles = {1: self.window, 2: self.popup, 3: self.other, 4: Node(4, 4, 50009, "Menu")}
        self.automation = SimpleNamespace(ElementFromHandleBuildCache=lambda hwnd, cache: self.handles[hwnd])
        self.calls, self.noop, self.destroy_on_select = [], False, False
        # The nested menu exists in Win32 but is hidden in this fixture by default.
        self.user32.visible.discard(4)

    def parent(self, node):
        roots = (self.window, self.popup, *self.window.kids)
        return next((parent for parent in roots if node in parent.kids), None)

    def prop(self, node, name):
        return node.props.get(name, False)

    def available(self, node, ident):
        from partyline_helper.uia_windows import PATTERNS
        return PATTERNS[ident] in node.patterns

    def state_value(self, node, key, *args):
        if key == "expand_state":
            return {"collapsed": 0, "expanded": 1, "partial": 2, "leaf": 3}[node.state[key]]
        return node.state[key]

    def state(self, node, props):
        props.update(node.state)

    def current(self):
        return True

    def foreground(self):
        return 99

    def read_only(self, node):
        return False

    def action_call(self, node, action, arg):
        def call():
            self.calls.append((node.ident, action, arg))
            if self.noop:
                return
            if action in ("expand", "collapse"):
                self.combo.state["expand_state"] = "expanded" if action == "expand" else "collapsed"
                if action == "expand":
                    self.user32.visible.add(2)
                else:
                    self.user32.visible.discard(2)
            elif action == "select":
                self.first.state["selected"] = node is self.first
                self.second.state["selected"] = node is self.second
                self.combo.state["value"] = node.props["Name"]
                if self.destroy_on_select:
                    self.combo.state["expand_state"] = "collapsed"
                    self.user32.visible.discard(2)
            elif action == "set_value":
                node.state["value"] = arg
        return call


class SiblingChrome(Chrome):
    """The live dashboard layout: a sibling List inside Document > Group, and stale Collapsed state."""
    def __init__(self):
        super().__init__()
        self.document = Node(40, 0, 50030, "Catalog Dashboard")
        self.group = Node(41, 0, 50026, "Marketplaces")
        self.document.kids = [self.group]
        self.group.kids = [self.combo]
        self.window.kids = [self.document]
        self.sibling = Node(42, 0, 50008, "Marketplaces")
        self.sibling.kids = [self.first, self.second]
        self.calls = []

    def parent(self, node):
        roots = (self.window, self.document, self.group, self.sibling)
        return next((parent for parent in roots if node in parent.kids), None)

    def action_call(self, node, action, arg):
        if action not in ("expand", "collapse"):
            return super().action_call(node, action, arg)
        def call():
            self.calls.append((node.ident, action, arg))
            if action == "expand":
                self.group.kids = [self.combo, self.sibling]
            else:
                self.group.kids = [self.combo]
            # Chrome's ExpandCollapsePattern still reports Collapsed while the List is visible.
        return call
