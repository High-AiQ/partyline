"""What the helper is doing, for the tray icon: offline, paired (idle), sharing or control.

Setters may run on any thread; listeners are called on the setter's thread. `stop_share` and `quit` are
thread-safe callbacks the running session and runner register so the tray can act on them.
"""
import contextlib
import itertools

LABELS = {"offline": "Not connected to Partyline", "paired": "Paired with Partyline",
          "sharing": "Sharing part of your screen",
          "control": "An agent is controlling your mouse and keyboard",
          "tools": "An agent is running a local tool session",
          "window_off": "Window access is off", "window_on": "Agents can use your windows",
          "window_active": "An agent is using a window"}


class Status:
    def __init__(self):
        self.state = "offline"
        self.update = None
        from .update_preferences import enabled
        self.auto_update = enabled()
        self.auto_update_toggle = None
        self.notified_updates = set()
        self.listeners, self.attention_listeners = [], []
        self.stop_share = self.quit = self.stop_tools = None
        self.tools_active = False
        self.chrome = ""
        self.window_title = None
        self.window_grants = {}
        self.stop_window_grant = None
        self.choose_window = self.stop_window = None
        self.checks_active, self.stop_checks = False, None
        self.window_access_enabled = False
        self.window_access_active = None
        self.window_calls = {}
        self.window_mouse = set()  # ids of the window calls that are using the real mouse
        self.window_call_ids = itertools.count()
        self.window_access_toggle = None
        self.window_access_pause = None
        self.window_access_audit = None

    @property
    def label(self):
        if self.window_access_active:
            line, agent = self.window_access_active
            return f"Active: {line} / {agent}" + (" (using your mouse)" if self.window_mouse else "")
        if self.state != "offline":
            permission = LABELS["window_on" if self.window_access_enabled else "window_off"]
            return f"{LABELS[self.state]}; {permission.lower()}"
        label = LABELS[self.state]
        label += "; " + self.chrome if self.chrome else ""
        return label + f"; reading {self.window_title}" if self.window_title else label

    def set(self, state):
        if state != self.state:
            self.state = state
            self.changed()

    def changed(self):
        """Tell the tray to redraw (also when only a menu item's availability changed)."""
        for listener in list(self.listeners):
            with contextlib.suppress(Exception):  # a broken tray must never end a share
                listener(self.state)

    def attention(self, text):
        """A prompt needs an answer: the tray can raise a balloon if the dialog is hidden."""
        for listener in list(self.attention_listeners):
            with contextlib.suppress(Exception):
                listener(text)

    def set_update(self, update):
        version, url = update.get("version"), update.get("url")
        valid = update.get("available") and isinstance(version, str) and isinstance(url, str)
        self.update = (version, url) if valid else None
        self.changed()
        if self.update and version not in self.notified_updates:
            self.notified_updates.add(version)
            self.attention(f"Partyline Helper update available ({version})")

    def request_stop_share(self):
        if self.stop_share:
            self.stop_share()

    def request_stop_tools(self):
        if self.stop_tools:
            self.stop_tools()

    def request_choose_window(self):
        if self.choose_window:
            self.choose_window()

    def request_stop_window(self):
        if self.stop_window:
            self.stop_window()

    def request_stop_window_grant(self, ident):
        if self.stop_window_grant:
            self.stop_window_grant(ident)

    def request_stop_all(self):
        """End the screen share and every window grant."""
        self.request_stop_share()
        self.request_stop_window()

    def request_window_access(self, enabled):
        if self.window_access_toggle:
            self.window_access_toggle(bool(enabled))

    def begin_window_call(self, line, agent):
        ident = next(self.window_call_ids)
        self.window_calls[ident] = (str(line)[:80], str(agent)[:80])
        self.window_access_active = next(iter(self.window_calls.values()))
        self.changed()
        return ident

    def mark_mouse(self, ident):
        """The window call `ident` is moving the real mouse: the tray and its tooltip say so."""
        if ident in self.window_calls:
            self.window_mouse.add(ident)
            self.changed()

    def end_window_call(self, ident):
        self.window_calls.pop(ident, None)
        self.window_mouse.discard(ident)
        self.window_access_active = next(iter(self.window_calls.values()), None)
        self.changed()

    def request_pause_windows(self):
        if self.window_access_pause:
            self.window_access_pause()

    def request_stop_checks(self):
        if self.stop_checks:
            self.stop_checks()

    def request_quit(self):
        if self.quit:
            self.quit()

    def request_auto_update(self, value):
        if self.auto_update_toggle:
            self.auto_update_toggle(value)
        else:
            from .update_preferences import set_enabled
            self.auto_update = set_enabled(value)
            self.changed()
