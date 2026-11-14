"""Read current UIA properties without BuildCache or a cached property accessor."""
from .uia_action import find
from .timing import Timing
from .uia_windows import WindowsProvider

PROPERTIES = {"enabled": 30010, "name": 30005, "value": 30045, "toggle": 30086,
              "selected": 30079, "expand_state": 30070, "bounds": 30001,
              "aria_role": 30101, "aria_properties": 30102, "legacy_state": 30096,
              "class_name": 30012, "framework_id": 30024, "provider_description": 30107}


class LiveProvider(WindowsProvider):  # pragma: no cover - native Windows walker
    def request(self, scope):
        return None  # this provider never creates or uses a UIA cache request

    def parent(self, node):
        return self.automation.RawViewWalker.GetParentElement(node)

    def root(self):
        if self.top is None:
            self.top = self.automation.ElementFromHandle(self.hwnd)
        return self.top

    def popups(self):
        roots = [self.automation.ElementFromHandle(hwnd) for hwnd in self.scope.popups()]
        for node in roots:
            self.popup_nodes[tuple(self.runtime_id(node))] = self.prop(node, "NativeWindowHandle")
        return [node for node in roots if self.same_window(node)]

    def children(self, node):
        children = []
        child = self.walker.GetFirstChildElement(node)
        while child and len(children) < 20000:
            children.append(child)
            child = self.walker.GetNextSiblingElement(child)
        popup = self.popup_nodes.get(tuple(self.runtime_id(node)))
        if popup is not None:
            for child in children:
                self.popup_nodes[tuple(self.runtime_id(child))] = popup
        if self.prop(node, "NativeWindowHandle") == self.hwnd:
            known = {self.prop(child, "NativeWindowHandle") for child in children}
            children.extend(popup for popup in self.popups()
                            if self.prop(popup, "NativeWindowHandle") not in known)
        return children


def current(node, ident):
    try:
        value = node.GetCurrentPropertyValue(ident)
        if isinstance(value, (str, int, float, bool)) or value is None:
            return value[:2000] if isinstance(value, str) else value
        return list(value)
    except Exception:
        return None  # unsupported properties remain explicit, rather than looking false


def inspect(provider, target, path=None):
    timing = Timing()
    with timing.phase("target_ms"):
        node = find(provider, target, path)
    if node is None:
        return timing.finish({"error": "stale or unknown element; find it again"})
    with timing.phase("post_read_ms"):
        result = _inspect(provider, node)
    timing.values.update(nodes=1 + len(result["ancestors"]), com_calls=getattr(provider, "com_calls", 0))
    return timing.finish(result)


def _inspect(provider, node):
    password = provider.password(node)
    live = {key: None if key == "value" and password else current(node, ident)
            for key, ident in PROPERTIES.items()}
    if isinstance(live["bounds"], list) and len(live["bounds"]) == 4:
        x, y, width, height = live["bounds"]
        live["bounds"] = [x, y, x + width, y + height]
    if live["expand_state"] in (0, 1, 2, 3):
        live["expand_state"] = ("collapsed", "expanded", "partial", "leaf")[live["expand_state"]]
    state = live["legacy_state"]
    live["legacy_unavailable"] = bool(state & 1) if isinstance(state, int) else None
    ancestors, seen = [], set()
    root_id = tuple(provider.runtime_id(provider.root()))
    reached = tuple(provider.runtime_id(node)) == root_id
    while not reached and len(ancestors) < 512:
        node = provider.parent(node)
        if node is None:
            break
        ident = tuple(provider.runtime_id(node))
        if ident in seen:
            break
        seen.add(ident)
        # Stop before exposing anything beyond the explicitly granted window.
        if not provider.same_window(node):
            break
        ancestors.append({"name": current(node, 30005), "enabled": current(node, 30010),
                          "runtime_id": list(ident)})
        reached = ident == root_id
    return {"live": live, "ancestors": ancestors, "grant_root_reached": reached}
