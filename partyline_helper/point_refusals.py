"""Public point-action refusals and their screenshot diagnostic codes."""
from .point_cdp import CHROME
from .point_cursor import CHANGED, COVERED, MOVED

STALE = ("the window moved, resized, closed or was re-granted since that snapshot, or the snapshot is "
         "unknown: take a fresh screen_window_snapshot and click in its pixels")
GONE = "consent revoked"
HIDDEN = ("the tab this window grant selected is not the tab shown in the window, so a click at a point "
          "of its picture could land on another page: take a fresh screen_window_snapshot")
LATE = ("the click was not started in time (the person took too long or the server stopped waiting); "
        "nothing was sent")
PARTLY = ("the click ran out of time after it had started; it may be only partly delivered "
          "(no button is left down)")
FLOOR = "that window is never clickable (terminal, password manager, security or Partyline's own window)"
AUDIT = "the helper could not write its audit log"
TIMEOUT = 20  # a click that started finishes within this
BUDGET = 30  # when the server names no deadline: seconds after the request arrives in which a click may start
POINT_VERSION = 4  # the `windows` hello value that can also scroll, drag, type and press keys


REASONS = {STALE: "stale", HIDDEN: "stale", COVERED: "covered", CHANGED: "covered", MOVED: "covered",
           CHROME: "outside"}  # what a picture can explain: the server attaches one to these failures
PARTS = (("outside the snapshot image", "outside"), ("frame or title bar", "outside"),
         ("pinch-zoomed", "stale"), ("disagree about that snapshot", "stale"))


def reason_code(text):
    """A short code for a refusal a picture of the window can explain, or None."""
    return REASONS.get(text) or next((code for part, code in PARTS if part in text), None)

