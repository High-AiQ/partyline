"""What the helper is doing, for the tray icon: offline, paired (idle), sharing or control.

Setters may run on any thread; listeners are called on the setter's thread. `stop_share` and `quit` are
thread-safe callbacks the running session and runner register so the tray can act on them.
"""
import contextlib

LABELS = {"offline": "Not connected to Partyline", "paired": "Paired with Partyline",
          "sharing": "Sharing part of your screen",
          "control": "An agent is controlling your mouse and keyboard"}


class Status:
    def __init__(self):
        self.state = "offline"
        self.listeners, self.attention_listeners = [], []
        self.stop_share = self.quit = None

    @property
    def label(self):
        return LABELS[self.state]

    def set(self, state):
        if state != self.state:
            self.state = state
            for listener in list(self.listeners):
                with contextlib.suppress(Exception):  # a broken tray must never end a share
                    listener(state)

    def attention(self, text):
        """A prompt needs an answer: the tray can raise a balloon if the dialog is hidden."""
        for listener in list(self.attention_listeners):
            with contextlib.suppress(Exception):
                listener(text)

    def request_stop_share(self):
        if self.stop_share:
            self.stop_share()

    def request_quit(self):
        if self.quit:
            self.quit()
