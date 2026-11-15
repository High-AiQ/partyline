"""The cursor route of a point click: the real mouse, confined to one granted window.

`api` is the Win32 side (point_win32.Win32Pointer; tests pass a fake). The click is refused, nothing sent,
unless the granted window is in front, the window at the point belongs to it (or to a dialog it owns), is
not a hard-floor program, and the foreground is still the same just before the button goes down.
"""
import threading

from .uia_window_list import HARD_FLOOR

MINIMIZED = "the window is minimised; Partyline never restores it. Ask the person to bring it back"
NOT_FRONT = "the window could not be brought to the front; no click was sent"
COVERED = "another window is on top at that point; no click was sent. Take a fresh snapshot"
FLOOR = "that window is never clickable (terminal, password manager, security or Partyline's own window)"
CHANGED = "the foreground window changed during the click; no click was sent"
MOVED = "the cursor was moved by something else before the click; no click was sent"
ONE_AT_A_TIME = threading.Lock()  # one real-cursor click at a time across every grant


class PointRefused(Exception):
    """Nothing was sent; the message is for the agent."""


def click(api, grant, point, button, clicks, alive, events=None, ready=lambda: None, last=lambda: None):
    """`alive` is the slow liveness check, run early; `ready` the window's-place check (blocking), run
    once the cursor is in position; `last` the cheap authority guard (deadline, revocation, consent), run
    after every blocking call and immediately before the input, which itself moves to the checked point."""
    hwnd, report = grant["hwnd"], {}
    with ONE_AT_A_TIME, api.session():
        alive()
        if api.iconic(hwnd):
            raise PointRefused(MINIMIZED)
        prior, prior_cursor = api.foreground(), api.cursor()
        report["target_came_forward"] = False
        if not api.owns(prior):
            report["target_came_forward"] = bool(api.bring_forward(hwnd, prior))
        focus = api.foreground()
        if not api.owns(focus):
            raise PointRefused(NOT_FRONT)
        alive()
        counter = events.status()["event_counter"] if events else None
        moved = False
        try:
            moved = api.move(*point)
            if not moved:
                raise PointRefused("the cursor could not be moved; no click was sent")
            ready()  # after the window was brought forward: it may have moved
            under = api.window_at(*point)
            if not under or not api.owns(under):
                raise PointRefused(COVERED)
            if api.image_name(under) in HARD_FLOOR or api.is_helper(under):
                raise PointRefused(FLOOR)
            if api.foreground() != focus or not api.owns(api.foreground()):
                raise PointRefused(CHANGED)
            if tuple(api.cursor() or ()) != tuple(point):
                raise PointRefused(MOVED)
            last()
            sent, wanted = api.send(point, button, clicks)
            if sent != wanted:
                api.release(button)
                return {"status": "unconfirmed", "error": "the click was only partly delivered", **report}
        finally:
            if moved:
                report["cursor_restored"] = api.cursor() == tuple(point) and bool(api.move(*prior_cursor))
            came = report["target_came_forward"]
            report["foreground_restored"] = bool(
                came and api.foreground() == focus and api.restore(prior, focus))
    settle = events.settle(counter) if events else "unsupported"
    return {"status": "completed", "route": "cursor", "settle": settle, **report}
