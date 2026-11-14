"""Persistent UIA subscriptions on the grant and its currently visible popup roots only."""
from .uia_events import register_handlers, remove_handlers

POPUP_REFRESH = 0x804D  # private thread message; emitted by the pid-scoped WinEvent hook


class WindowHandlers:
    def __init__(self, automation, uia, hwnd, scope, changed, com_object):
        self.automation, self.uia, self.hwnd = automation, uia, hwnd
        self.scope, self.changed, self.com_object = scope, changed, com_object
        self.roots = {}

    def add(self, hwnd):
        root = self.automation.ElementFromHandle(hwnd)
        self.roots[hwnd] = register_handlers(self.automation, self.uia, root, self.changed, self.com_object)

    def start(self):
        self.add(self.hwnd)
        self.refresh()

    def drop(self, hwnd):
        for handler in self.roots.pop(hwnd):
            try:
                remove_handlers(self.automation, [handler])
            except Exception:
                pass  # a destroyed popup must not prevent other roots from being unsubscribed

    def refresh(self):
        """Called on startup or a posted lifecycle event, outside UIA and WinEvent handlers."""
        current = set(self.scope.popups()) | {self.hwnd}
        for hwnd in set(self.roots) - current:
            self.drop(hwnd)
        for hwnd in current - set(self.roots):
            try:
                self.add(hwnd)
            except Exception:
                pass  # popup disappeared during registration; the main subscription stays active

    def close(self):
        for hwnd in list(self.roots):
            self.drop(hwnd)
