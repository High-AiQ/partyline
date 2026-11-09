"""System-tray icon: status colour, tooltip, the Stop items and Quit (pystray; Windows by default).

The icon and its menu live on pystray's own thread; every action goes through the `Status` callbacks,
which hand off to the helper's event loop thread-safely. `icon_type` is injectable so tests need no desktop.
"""
import threading

from PIL import Image, ImageDraw

COLORS = {"offline": (128, 128, 128), "paired": (46, 160, 67), "sharing": (240, 165, 0),
          "control": (215, 58, 73), "tools": (130, 80, 220)}
TITLE = "Partyline Helper"
TIP_LIMIT = 127  # szTip holds 127 UTF-16 units and a terminator; pystray raises on more


def draw_icon(state, size=64):
    """A round badge in the state's colour (grey offline, green paired, amber sharing, red control)."""
    image = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    pad = size // 16
    ImageDraw.Draw(image).ellipse((pad, pad, size - pad, size - pad), fill=COLORS[state] + (255,),
                                  outline=(255, 255, 255, 255), width=max(2, size // 16))
    return image


def units(text):
    """Length in UTF-16 code units, which is what Windows' WCHAR arrays count (an emoji is two)."""
    return len(text.encode("utf-16-le")) // 2


def tooltip(text):
    """The tooltip text, cut to what the Windows tray accepts (a longer one raises inside pystray)."""
    if units(text) <= TIP_LIMIT:
        return text
    kept, used = [], 1  # one unit for the ellipsis
    for char in text:
        used += units(char)
        if used > TIP_LIMIT:
            break
        kept.append(char)
    return "".join(kept) + "…"


def default_icon_type():  # pragma: no cover - needs a desktop
    import pystray
    return pystray


class Tray:
    def __init__(self, status, backend=None):
        self.status = status
        self.backend = backend or default_icon_type()
        self.icon = None
        self.drawing = threading.Lock()
        self.reported = set()

    def sharing(self, item=None):
        return self.status.state in ("sharing", "control")

    def shared(self, item=None):
        return self.sharing() or bool(self.status.window_grants or self.status.window_title)

    def tools(self, item=None):
        return self.status.tools_active

    def menu(self):
        item = self.backend.MenuItem
        return self.backend.Menu(
            item(lambda _: self.status.label, None, enabled=False),
            item("Stop screen sharing", lambda *_: self.status.request_stop_share(),
                 enabled=lambda _: self.sharing()),
            item("Stop all sharing", lambda *_: self.status.request_stop_all(),
                 enabled=lambda _: self.shared()),
            item("Share a window…", lambda *_: self.status.request_choose_window()),
            *(item(label, self.backend.Menu(item("Stop", lambda *_, key=ident:
                  self.status.request_stop_window_grant(key))))
              for ident, label in self.status.window_grants.items()),
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
        self.icon.run_detached(setup=self.show)

    def show(self, icon):
        """pystray's setup hook: show the icon, then draw. A draw before it is visible can be lost,
        because showing it adds the icon handle built from the image it had before that draw."""
        self.apply("show", lambda: setattr(icon, "visible", True))
        self.refresh()

    def refresh(self, state=None):
        """Draw the current state; serialised, and read inside the lock so no older state lands on top.

        The menu goes first and each step stands alone: a step pystray rejects (an over-long tooltip
        raised for a shared window's title, which left the menu without its Stop item) must not skip the
        rest, and is logged once so a broken tray can be diagnosed.
        """
        with self.drawing:
            icon = self.icon
            if icon:
                self.apply("menu", lambda: self.set_menu(icon))
                self.apply("icon", lambda: setattr(icon, "icon", draw_icon(self.status.state)))
                self.apply("title", lambda: setattr(icon, "title", tooltip(f"{TITLE}: {self.status.label}")))

    def set_menu(self, icon):
        icon.menu = self.menu()
        icon.update_menu()

    def apply(self, step, action):
        try:
            action()
        except Exception as exc:  # noqa: BLE001 - a broken tray must never break the helper
            if step not in self.reported:
                self.reported.add(step)
                print(f"Tray {step} update failed: {exc!r}", flush=True)

    def notify(self, text):
        """A balloon in case the dialog is still hidden; best effort."""
        if self.icon:
            self.apply("notify", lambda: self.icon.notify(text, TITLE))

    def stop(self):
        icon, self.icon = self.icon, None
        if icon:
            self.apply("stop", icon.stop)


def start_tray(status, backend=None):
    """A running tray, or None when there is no desktop tray here (headless, missing pystray)."""
    try:
        tray = Tray(status, backend)
        tray.start()
    except Exception as exc:  # noqa: BLE001 - the helper works without a tray icon
        print(f"Tray start failed, running without a tray icon: {exc!r}", flush=True)
        return None
    return tray
