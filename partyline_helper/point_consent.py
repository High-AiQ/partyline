"""The person's consent to the real mouse in one granted window: asked once per grant, kept only with it.

The answer lives in the grant's own entry, so it ends when that grant ends (revoked, window closed,
paused, disconnected) and is cleared when standing window access is switched off.
"""
import asyncio
import time

from . import consent_dialog
from .update_prompts import SCOPE

TITLE = "Partyline: mouse and keyboard"
ALLOW, DENY = "Allow for this window", "Deny"
SECONDS = 25  # the server waits 35 s for the whole click
COOLDOWN = 120  # after a Deny the same grant is not asked again for this long
DENIED = "the person declined mouse and keyboard input in this window"
SOON = ("the person declined mouse and keyboard input in this window a moment ago; "
        "do not ask again for a while")


def question(line, agent, title):
    return (f"Allow {line[:60]}/{agent[:40]} to use the mouse and keyboard in {title[:80]}?\n\n"
            "Each click, scroll, drag or key press moves your real pointer for an instant and brings "
            "that window to the front; typing goes to it. Input stays inside that window, and never into "
            "a password field. This lasts until the window is no longer shared.")


def clear(entry):
    entry.pop("mouse_approved", None)
    entry.pop("mouse_denied", None)
    entry.pop("point_clicked", None)


class MouseConsent:
    def __init__(self, ask=None, clock=time.monotonic):
        self.ask, self.clock = ask or consent_dialog.confirm_labeled, clock

    async def check(self, entry, message):
        """None when the mouse may be used in this grant now; otherwise why not. One ask at a time."""
        if entry.get("mouse_approved"):
            return None
        async with entry.setdefault("mouse_lock", asyncio.Lock()):
            if entry.get("mouse_approved"):
                return None
            denied = entry.get("mouse_denied")
            if denied is not None and self.clock() - denied < COOLDOWN:
                return SOON
            line = str(entry.get("target", {}).get("line_name") or "a line")
            text = question(line, str(message.get("agent") or "an agent"), str(entry.get("title", "")))
            access = entry.get("access")
            token = SCOPE.set({"kind": "mouse", "grant": getattr(
                getattr(access, "session", None), "window_grant_id", None)})
            try:
                yes = await self.ask(TITLE, text, labels=(ALLOW, DENY), timeout=SECONDS)
            finally:
                SCOPE.reset(token)
            if yes is True:
                entry["mouse_approved"] = True
                entry.pop("mouse_denied", None)
                return None
            entry["mouse_denied"] = self.clock()
            return DENIED
