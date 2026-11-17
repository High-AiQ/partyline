"""A picture of the window that rides on an action that did not land, so the agent can switch to a point.

Only the failures a picture can explain get one (the point was covered, the element or snapshot was stale or
not found, the page never settled); a revoked grant, a refused consent, a floor program or a vanished window
get none. The picture is the granted window alone (the helper captures that one window, never the desktop
around it), in the thumb tier with numbered marks from a tree read just now, and only for a caller who may
read the window. Point input also uses this capture path for a crosshair crop on unchanged outcomes.
"""
import asyncio
import re

from fastapi import HTTPException

from .machine_scope import deny_unless

REASONS = frozenset({"covered", "stale", "outside", "not_found", "target_changed"})
TEXT = re.compile(r"covered|outside the viewport|stale|unknown element|read (?:it|the window) again|"
                  r"could not refresh|not found|no such element|detached", re.IGNORECASE)
KEPT = ("file", "width", "height", "snapshot", "marks", "marks_unchanged", "marks_note", "unchanged", "note",
        "budget", "coordinates", "use")
SECONDS = 20  # the whole read and capture; a failure answer is never held longer than this


def failed(result):
    """True when `result` is a failure a picture can explain."""
    if result.get("grant_ended"):
        return False
    if result.get("status") == "failed":
        return result.get("reason") in REASONS or bool(TEXT.search(str(result.get("error", ""))))
    return result.get("status") == "completed" and result.get("settle") == "deadline"


def compact(picture):
    """The picture as an answer carries it: its file, size, snapshot id, marks, and the two usable tiers."""
    shot = {key: picture[key] for key in KEPT if key in picture}
    tiers = picture.get("variants", {})
    shot["variants"] = {name: tiers[name] for name in ("slim", "thumb") if name in tiers} or tiers
    return shot


async def attach(runtime, hub, store, principal, conv_id, grant, result, key="screenshot", marks=True,
                 landing=None):
    """Put a picture under `result[key]`; with `marks` the tree is read fresh first so the boxes are true.

    Never raises: a caller without read access, a grant that ended or a capture that took too long leaves
    the answer as it was, with the reason in place of the picture."""
    try:
        deny_unless(runtime.db, principal, conv_id, "read")
    except HTTPException:
        return
    try:
        busy = result.get("reason") == "target_changed"
        if busy:
            marks = False  # another full tree walk cannot explain a target stability refusal
        async with asyncio.timeout(2 if busy else SECONDS):
            if marks:
                await hub.elements.read(principal, None, grant["id"], {"refresh": True})
            extra = {"landing": landing} if landing is not None else {}
            picture = await hub.snapshots.take(principal, store, grant["id"], None, marks, "thumb", **extra)
    except HTTPException as exc:
        result[key] = {"error": str(exc.detail)}
    except TimeoutError:
        result[key] = {"error": "the picture took too long; take screen_window_snapshot yourself"}
    else:
        result[key] = compact(picture)
