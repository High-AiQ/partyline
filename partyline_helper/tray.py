"""System-tray icon: status colour, tooltip, Stop sharing and Quit (pystray; Windows by default).

The icon and its menu live on pystray's own thread; every action goes through the `Status` callbacks,
which hand off to the helper's event loop thread-safely. `icon_type` is injectable so tests need no desktop.
"""
import contextlib

from PIL import Image, ImageDraw

COLORS = {"offline": (128, 128, 128), "paired": (46, 160, 67), "sharing": (240, 165, 0),
          "control": (215, 58, 73), "tools": (130, 80, 220)}
TITLE = "Partyline Helper"


def draw_icon(state, size=64):
    """A round badge in the state's colour (grey offline, green paired, amber sharing, red control)."""
    image = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    pad = size // 16
    ImageDraw.Draw(image).ellipse((pad, pad, size - pad, size - pad), fill=COLORS[state] + (255,),
                                  outline=(255, 255, 255, 255), width=max(2, size // 16))
    return image


def default_icon_type():  # pragma: no cover - needs a desktop
    import pystray
    return pystray


class Tray:
    def __init__(self, status, backend=None):
        self.status = status
        self.backend = backend or default_icon_type()
        self.icon = None

    def sharing(self, item=None):
        return self.status.state in ("sharing", "control")

    def tools(self, item=None):
        return self.status.tools_active

    def menu(self):
        item = self.backend.MenuItem
        return self.backend.Menu(
            item(lambda _: self.status.label, None, enabled=False),
            item("Stop sharing", lambda *_: self.status.request_stop_share(),
                 enabled=lambda _: self.sharing()),
            item("Allow agents to read a window…", lambda *_: self.status.request_choose_window()),
            item("Stop reading window", lambda *_: self.status.request_stop_window(),
                 enabled=lambda _: bool(self.status.window_title)),
            item("End agent session", lambda *_: self.status.request_stop_tools(),
                 enabled=lambda _: self.tools()),
            item("Stop render checks", lambda *_: self.status.request_stop_checks(),
                 enabled=lambda _: self.status.checks_active),
            item("Quit Partyline Helper", lambda *_: self.status.request_quit()))

    def start(self):
        # Listen first: the session may pair in the middle of building the icon.
        self.status.listeners.append(self.refresh)
        self.status.attention_listeners.append(self.notify)
        self.icon = self.backend.Icon("partyline-helper", draw_icon(self.status.state), TITLE, self.menu())
        self.icon.run_detached()
        self.refresh(self.status.state)  # draw the current state once the tray is ready

    def refresh(self, state):
        if self.icon:
            with contextlib.suppress(Exception):  # a broken tray must never break the helper
                self.icon.icon = draw_icon(state)
                self.icon.title = f"{TITLE}: {self.status.label}"
                self.icon.update_menu()

    def notify(self, text):
        """A balloon in case the dialog is still hidden; best effort."""
        if self.icon:
            with contextlib.suppress(Exception):
                self.icon.notify(text, TITLE)

    def stop(self):
        icon, self.icon = self.icon, None
        if icon:
            with contextlib.suppress(Exception):
                icon.stop()


def start_tray(status, backend=None):
    """A running tray, or None when there is no desktop tray here (headless, missing pystray)."""
    try:
        tray = Tray(status, backend)
        tray.start()
    except Exception:  # noqa: BLE001 - the helper works without a tray icon
        return None
    return tray
