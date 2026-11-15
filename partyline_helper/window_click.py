"""A click at a point of an earlier window snapshot, on a window granted to a line.

The helper converts the point again with the geometry it recorded for that snapshot (never with what the
server sent), and refuses when the window moved, resized, closed or was re-granted since, when the point is
outside the window's client area, or when the window is a hard-floor program. Then it picks the route:
a Chrome page with a CDP connection is clicked through CDP (no cursor, no foreground); every other window
needs the person's consent for that grant and uses the real cursor, confined to the window.
"""
import asyncio
import json
import time

from partyline.point_geometry import GeometryError, locate

from .cdp_transport import CDPError
from .point_cdp import click as cdp_click, page_frame, render_rect
from .point_consent import MouseConsent, clear
from .point_cursor import PointRefused, click as cursor_click
from .point_win32 import Win32Pointer
from .uia_window_list import HARD_FLOOR
from .uia_window_identity import live

STALE = ("the window moved, resized, closed or was re-granted since that snapshot, or the snapshot is "
         "unknown: take a fresh screen_window_snapshot and click in its pixels")
GONE = "consent revoked"
HIDDEN = ("the tab this window grant selected is not the tab shown in the window, so a click at a point "
          "of its picture could land on another page: take a fresh screen_window_snapshot")
FLOOR = "that window is never clickable (terminal, password manager, security or Partyline's own window)"
AUDIT = "the helper could not write its audit log"
TIMEOUT = 20
POINT_VERSION = 3  # the `windows` hello value that can click at a point of a snapshot


class Refused(Exception):
    """Nothing was sent; the message is for the agent."""


def hard_floor(grant):
    return str(grant.get("process", "")).casefold() in HARD_FLOOR


class PointClicks:
    def __init__(self, shares, pointer=None, ask=None, clock=None, rect_of=render_rect):
        self.shares, self.rect_of = shares, rect_of
        self.pointer = pointer or (lambda hwnd: Win32Pointer(hwnd))
        self.consent = MouseConsent(ask, clock or time.monotonic)

    async def handle(self, entry, message):
        from .screen_access_audit import audit_window, begin_window_call, end_window_call
        access = entry["access"]
        session = getattr(access, "session", self.shares.session)
        active = begin_window_call(session, message.get("agent", ""),
                                   message.get("line_name") or message.get("line"))
        route = "none"
        try:
            route, result = await self.run(entry, message, active)
        except (Refused, PointRefused, CDPError) as exc:
            result = {"status": "failed", "error": str(exc)}
        except Exception as exc:  # noqa: BLE001 - whatever fails, the caller gets an answer, not a timeout
            print(f"Point click failed: {exc!r}", flush=True)
            result = {"status": "failed", "error": "the click failed; see the helper's terminal"}
        finally:
            end_window_call(active)
        result.setdefault("route", route)
        try:
            self.record(entry, message, route, result.get("status", "failed"), result.get("error"))
            audit_window(session, "point_click", message.get("agent", ""),
                         f"{result.get('status', 'failed')} ({route})", message.get("line"))
        except OSError:
            result = {"status": "failed", "error": AUDIT}
        await self.shares.session.send("window_element_result", request_id=message["request_id"], **result)

    def record(self, entry, message, route, result, reason=None):
        """Grant, line, process, operation, route, point and result; never pixels. Raises OSError."""
        info = {"grant": message.get("grant_id", ""), "line": message.get("line", ""),
                "process": str(message.get("agent", ""))[:120], "operation": "screen_window_click",
                "route": route, "point": [message.get("x"), message.get("y")],
                "screen": message.get("screen"), "result": result}
        if reason:
            info["reason"] = str(reason)[:120]
        self.shares.session.tools.audit.append("action", "window", str(message.get("agent", ""))[:120],
                                               "point_click", json.dumps(info, separators=(",", ":")))

    def begin(self, entry, message, route):
        """The audit row written before any input goes out; a log that cannot be written refuses the click."""
        try:
            self.record(entry, message, route, "dispatching")
        except OSError as exc:
            raise Refused(AUDIT) from exc

    def check(self, entry, access, grant, generation, message):
        """The screen point, once every refusal that needs no waiting has been passed."""
        live_entry = self.shares.grants.get(message.get("grant_id"))
        if (not grant or access.grant is not grant or live_entry is not entry
                or access.gate.revoked.is_set() or access.gate.generation != generation):
            raise Refused(GONE)
        if hard_floor(grant):
            raise Refused(FLOOR)
        record = entry.get("snapshots", {}).get(message.get("snapshot"))
        if not record or record["grant"] is not grant or record["generation"] != generation:
            raise Refused(STALE)
        try:
            point = locate(record["geometry"], message.get("x"), message.get("y"))
        except GeometryError as exc:
            raise Refused(str(exc)) from exc
        if list(point) != list(message.get("screen") or point):
            raise Refused("the server and the helper disagree about that snapshot: take a fresh one")
        return point, record

    async def current(self, entry, access, grant, generation, message):
        """`check`, then the live window: still there, not on the secure desktop, same place and shape."""
        point, record = self.check(entry, access, grant, generation, message)
        reason = await access.check(grant)
        if reason == "window closed":
            access.revoke(reason)
        if reason:
            raise Refused(reason)
        layout = await asyncio.to_thread(self.shares.snapshots.backend.layout, grant["hwnd"])
        wanted = record["geometry"]
        if (tuple(layout["rect"]) != tuple(wanted["rect"])
                or sorted(map(tuple, layout["regions"])) != sorted(map(tuple, wanted["regions"]))):
            raise Refused(STALE)
        return point

    async def run(self, entry, message, active):
        access = entry["access"]
        grant, generation = access.grant, access.gate.generation
        point = await self.current(entry, access, grant, generation, message)
        page = (await self.shares.chrome.page(access)
                if str(grant.get("process", "")).lower() == "chrome.exe" else None)
        if page:
            return "cdp", await self.by_cdp(entry, message, page, grant, point)
        epoch = self.shares.generation
        reason = await self.consent.check(entry, message)
        if self.shares.generation != epoch:  # access was switched off or paused while the person was asked
            clear(entry)
            raise Refused(GONE)
        if reason:
            raise Refused(reason)
        point = await self.current(entry, access, grant, generation, message)  # it may have changed meanwhile
        if active:
            active[0].mark_mouse(active[1])
        return "cursor", await self.by_cursor(entry, message, access, grant, generation, point)

    async def by_cdp(self, entry, message, page, grant, point):
        if grant.get("target_id") and not await page.visible():  # a picked tab may be behind the shown one
            raise Refused(HIDDEN)
        frame = await page_frame(page, grant["hwnd"], self.rect_of)
        self.begin(entry, message, "cdp")
        page.dispatched, page.operation_epoch = False, None
        try:
            info = await cdp_click(page, frame, point, message["button"], message["clicks"])
            counter = page.access.event_status()["event_counter"]
            settle = await page.quiet.wait()
            if page.access.event_status()["event_counter"] != counter and settle == "quiet":
                settle = "changing"
            return {"status": "completed", "source": "cdp", "settle": settle,
                    "settled_event_counter": counter, **info}
        except CDPError as exc:
            if not page.dispatched:
                raise Refused(str(exc)) from exc
            return {"status": "unconfirmed", "source": "cdp", "error": str(exc),
                    "revoked_during": not page.live}

    async def by_cursor(self, entry, message, access, grant, generation, point):
        self.begin(entry, message, "cursor")

        def alive():
            if access.gate.revoked.is_set() or access.gate.generation != generation:
                raise PointRefused("revoked")
            windows = access.list_windows()
            if windows is None:
                raise PointRefused("secure desktop active")
            if (not any(w["hwnd"] == grant["hwnd"] and w["pid"] == grant["pid"] for w in windows)
                    or (grant.get("marker") and not live(grant))):
                raise PointRefused("window closed")

        def call():
            return cursor_click(self.pointer(grant["hwnd"]), grant, point, message["button"],
                                message["clicks"], alive, getattr(access, "event_state", None))
        try:
            result, revoked = await asyncio.wait_for(
                asyncio.to_thread(access.gate.dispatch, generation, call), TIMEOUT)
        except TimeoutError:
            access.gate.invalidate()
            return {"status": "unconfirmed", "error": "the click did not finish in time"}
        except ValueError as exc:  # the gate: revoked before the click
            raise Refused(GONE if str(exc) == "revoked" else str(exc)) from exc
        if revoked or access.gate.revoked.is_set():
            result["revoked_during"] = True
        return result
