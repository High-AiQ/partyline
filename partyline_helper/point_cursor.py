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
    return run(api, grant, [point], lambda pointer, again: pointer.send(point, button, clicks), alive, events,
               ready, last, partial=lambda pointer: pointer.release(button), what="click")


def run(api, grant, points, send, alive, events=None, ready=lambda: None, last=lambda: None, check=None,
        partial=lambda api: None, what="input"):
    """Every real-input operation shares this: the window in front, every point inside it and not a floor
    program, the foreground unchanged, the guard last. `points` are the screen pixels the input touches
    (the first is where the cursor goes); none for the keyboard, which goes to the window in front.
    `send(api, again)` returns (events sent, events wanted), and calls `again()` before any input beyond its
    first (a send made of several inputs, with blocking checks between them); `partial` undoes a short send;
    `check(api)` is a blocking refusal (the focused field) that runs once the window is known to be the one
    in front."""
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
            if points:
                moved = api.move(*points[0])
                if not moved:
                    raise PointRefused(f"the cursor could not be moved; no {what} was sent")
            ready()  # after the window was brought forward: it may have moved
            for point in points or [None]:
                under = api.window_at(*point) if point else focus
                if not under or not api.owns(under):
                    raise PointRefused(COVERED)
                if api.image_name(under) in HARD_FLOOR or api.is_helper(under):
                    raise PointRefused(FLOOR)
            if api.foreground() != focus or not api.owns(api.foreground()):
                raise PointRefused(CHANGED)
            if points and tuple(api.cursor() or ()) != tuple(points[0]):
                raise PointRefused(MOVED)
            if check:
                check(api)
                if api.foreground() != focus:
                    raise PointRefused(CHANGED)
            last()

            def again():
                last()
                if api.foreground() != focus or not api.owns(api.foreground()):
                    raise PointRefused(CHANGED)
            sent, wanted = send(api, again)
            if sent != wanted:
                partial(api)
                return {"status": "unconfirmed", "error": f"the {what} was only partly delivered", **report}
        finally:
            if moved:
                report["cursor_restored"] = (api.cursor() == tuple(points[-1])
                                             and bool(api.move(*prior_cursor)))
            came = report["target_came_forward"]
            report["foreground_restored"] = bool(
                came and api.foreground() == focus and api.restore(prior, focus))
    settle = events.settle(counter) if events else "unsupported"
    return {"status": "completed", "route": "cursor", "settle": settle, **report}
