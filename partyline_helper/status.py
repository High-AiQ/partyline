"""What the helper is doing, for the tray icon: offline, paired (idle), sharing or control.

Setters may run on any thread; listeners are called on the setter's thread. `stop_share` and `quit` are
thread-safe callbacks the running session and runner register so the tray can act on them.
"""
import contextlib

LABELS = {"offline": "Not connected to Partyline", "paired": "Paired with Partyline",
          "sharing": "Sharing part of your screen",
          "control": "An agent is controlling your mouse and keyboard",
          "tools": "An agent is running a local tool session"}


class Status:
    def __init__(self):
        self.state = "offline"
        self.listeners, self.attention_listeners = [], []
        self.stop_share = self.quit = self.stop_tools = None
        self.tools_active = False
        self.window_title = None
        self.window_grants = {}
        self.stop_window_grant = None
        self.choose_window = self.stop_window = None
        self.checks_active, self.stop_checks = False, None

    @property
    def label(self):
        label = LABELS[self.state]
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

    def request_stop_checks(self):
        if self.stop_checks:
            self.stop_checks()

    def request_quit(self):
        if self.quit:
            self.quit()
