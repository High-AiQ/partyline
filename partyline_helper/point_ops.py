"""The five point operations (click, scroll, drag, type, key): their arguments and what each route sends.

`window_click.PointClicks` runs every one through the same geometry, consent, deadline and floor rules; this
module only says which points an operation touches and how each route spells it.
"""
import re

from .point_cdp import click as cdp_click
from .point_cdp_ops import PASSWORD, UNKNOWN, drag, insert, password_check, press, wheel
from .point_cursor import PointRefused
from .point_keys import clean_text, combo, inserts_text, refusal, virtual_keys

OPS = ("click", "scroll", "drag", "type", "key")
POINTED = ("click", "scroll", "drag")  # operations that name pixels of a snapshot
KEYBOARD = ("type", "key")  # operations that need an earlier click in the grant
MAX_STEPS = 50
NEEDS_CLICK = ("click a field of this window first (screen_window_click), then type; "
               "the keyboard goes where the last click put the focus")
INTERMEDIATE = 40  # screen pixels between the points of a drag's path


def which(message):
    """The operation a server message names, or "invalid"; the name that goes into logs and audit rows."""
    op = message.get("op") or "click"
    return op if op in OPS else "invalid"


def arguments(message):
    """`(op, args)` from a server message; ValueError says what is wrong with it."""
    op = message.get("op") or "click"
    if op not in OPS:
        raise ValueError(f"unknown point operation {op!r}")
    if op == "click":
        return op, {"button": message.get("button", "left"), "clicks": message.get("clicks", 1)}
    if op == "scroll":
        steps = [message.get("dx", 0), message.get("dy", 0)]
        if not all(isinstance(n, int) and not isinstance(n, bool) and abs(n) <= MAX_STEPS for n in steps):
            raise ValueError(f"dx and dy are whole wheel steps, at most {MAX_STEPS} either way")
        if not any(steps):
            raise ValueError("scroll needs a nonzero dx or dy")
        return op, {"dx": steps[0], "dy": steps[1]}
    if op == "type":
        return op, {"text": clean_text(message.get("text"))}
    if op == "key":
        names = combo(message.get("keys"))
        if reason := refusal(names):
            raise ValueError(reason)
        return op, {"names": names}
    return op, {}


def path(points):
    """A drag's path: the two ends with a few points between them, at whole screen pixels."""
    (a, b), (c, d) = points
    length = max(abs(c - a), abs(d - b))
    steps = min(10, max(2, length // INTERMEDIATE))
    middle = [(a + (c - a) * i // steps, b + (d - b) * i // steps) for i in range(1, steps)]
    return [(a, b), *middle, (c, d)]


async def by_cdp(op, page, frame, points, args, guard):
    """What the page is sent for `op`; the result goes into the answer."""
    if op == "click":
        return await cdp_click(page, frame, points[0], args["button"], args["clicks"], guard)
    if op == "scroll":
        return await wheel(page, frame, points[0], args["dx"], args["dy"], guard)
    if op == "drag":
        return await drag(page, frame, path(points), guard)
    if op == "type":
        await password_check(page)
        return await insert(page, args["text"], guard)
    names = args["names"]
    await password_check(page, typing=inserts_text(names))
    return await press(page, names, guard)


def password(api):
    """Refuse unless UI Automation says the focused field is not a password field."""
    state = api.focused_password()
    if state is True:
        raise PointRefused(PASSWORD)
    if state is None:
        raise PointRefused(UNKNOWN)


def type_text(api, text, again):
    """Type `text` for the real keyboard, one run at a time. A Tab or Enter moves the focus, so the field is
    inspected again before any character that follows one: text never goes into a password field it was not
    aimed at. `again` is the click's last guard (deadline, revocation, consent, the window in front); it runs
    immediately before every send, after the blocking inspection: no input follows a condition that failed."""
    sent = wanted = typed = 0
    moved = False
    for run in re.findall(r"[^\t\n]+|\t|\n", text):
        key = run in ("\t", "\n")
        try:
            if moved and not key:
                password(api)
            again()
        except Exception as exc:  # the agent must know what already went in
            if typed:
                exc.args = (f"{exc} ({typed} of {len(text)} characters were typed before the input stopped)",)
            raise
        count, expected = api.send_text(run)
        sent, wanted, typed, moved = sent + count, wanted + expected, typed + len(run), key
        if count != expected:
            break
    return sent, wanted


def for_cursor(op, points, args):
    """`(points, send, partial, check)` of `run` for the real mouse and keyboard."""
    if op == "click":
        point = points[0]
        return [point], lambda api, again: api.send(point, args["button"], args["clicks"]), (
            lambda api: api.release(args["button"])), None
    if op == "scroll":
        return [points[0]], lambda api, again: api.send_wheel(points[0], args["dx"], args["dy"]), (
            lambda api: None), None
    if op == "drag":
        spots = path(points)
        return spots, lambda api, again: api.send_drag(spots), lambda api: api.release("left"), None
    if op == "type":
        return [], lambda api, again: type_text(api, args["text"], again), (
            lambda api: api.release_keys([9], 13)), password  # a short send may hold Tab or Enter down
    names = args["names"]
    if reason := refusal(names, cursor=True):
        raise PointRefused(reason)
    mods, key = virtual_keys(names)
    char = names[-1] if key is None else None
    return [], (lambda api, again: api.send_keys(mods, key, char)), (
        lambda api: api.release_keys(mods, key, char)), password if inserts_text(names) else None
