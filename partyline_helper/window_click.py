"""A click, scroll or drag at a point of an earlier window snapshot, or typing and keys, on a granted window.

The helper reconverts the named snapshot, refuses stale geometry and floor programs, then picks the route:
a Chrome page with a CDP connection is clicked through CDP (no cursor, no foreground); every other window
needs the person's consent for that grant and uses the real cursor, confined to the window.
Typing and keys name no point: they need an earlier click in the grant and go to where it put the focus.
"""
import asyncio
import json
import time

from partyline.point_geometry import GeometryError, locate

from .cdp_transport import CDPError
from .page_windows import PageSources
from .point_cdp import page_frame
from .point_consent import MouseConsent, clear
from .point_cdp import CHROME
from .point_cursor import CHANGED, COVERED, MOVED, PointRefused, run as cursor_run
from .point_ops import KEYBOARD, NEEDS_CLICK, POINTED, arguments, by_cdp, for_cursor, which
from .point_win32 import Win32Pointer
from .point_landing import evidence, landing_session
from .uia_window_list import HARD_FLOOR
from .uia_window_identity import live

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


class Refused(Exception):
    """Nothing was sent; the message is for the agent."""


def hard_floor(grant):
    return str(grant.get("process", "")).casefold() in HARD_FLOOR


class PointClicks:
    def __init__(self, shares, pointer=None, ask=None, clock=None, sources=None):
        self.shares, self.sources, self.clock = shares, sources or PageSources(), clock or time.monotonic
        self.pointer = pointer or (lambda hwnd: Win32Pointer(hwnd))
        self.consent = MouseConsent(ask, self.clock)

    async def handle(self, entry, message):
        from .screen_access_audit import audit_window, begin_window_call, end_window_call
        access = entry["access"]
        session = getattr(access, "session", self.shares.session)
        active = begin_window_call(session, message.get("agent", ""),
                                   message.get("line_name") or message.get("line"))
        route = "none"
        message = {**message, "deadline": self.clock() + self.budget(message)}
        operation = which(message)
        message["landing"] = evidence(entry, message)
        try:
            from .window_look import StaleMark, check, operation_lock
            async with operation_lock(entry):
                check(access, message)
                route, result = await self.run(entry, message, active)
        except (Refused, PointRefused, CDPError, StaleMark) as exc:
            result = {"status": "failed", "error": str(exc),
                      **({"reason": code} if (code := reason_code(str(exc))) else {})}
        except Exception as exc:  # noqa: BLE001 - whatever fails, the caller gets an answer, not a timeout
            print(f"Point {operation} failed: {exc!r}", flush=True)
            result = {"status": "failed", "error": f"the {operation} failed; see the helper's terminal"}
        finally:
            end_window_call(active)
        result.setdefault("route", route)
        try:
            self.record(entry, message, route, result.get("status", "failed"), result.get("error"))
            audit_window(session, f"point_{operation}", message.get("agent", ""),
                         f"{result.get('status', 'failed')} ({route})", message.get("line"))
        except OSError:
            result = {"status": "failed", "error": AUDIT}
        result["landing"] = message["landing"]
        await self.shares.session.send("window_element_result", request_id=message["request_id"], **result)

    @staticmethod
    def budget(message):
        """Seconds, from now, in which a click may still start; the server's `budget`, bounded."""
        value = message.get("budget")
        ok = isinstance(value, (int, float)) and not isinstance(value, bool)
        return min(max(float(value), 1.0), 120.0) if ok else float(BUDGET)

    def late(self, message):
        """Refuse to start a click once the server's deadline has passed: it has reported it unconfirmed."""
        if self.clock() >= message["deadline"]:
            raise Refused(LATE)

    def record(self, entry, message, route, result, reason=None):
        """Grant, line, process, operation, route, point and result; never pixels. Raises OSError."""
        operation = which(message)
        info = {"grant": message.get("grant_id", ""), "line": message.get("line", ""),
                "process": str(message.get("agent", ""))[:120], "operation": f"screen_window_{operation}",
                "route": route, "result": result}
        if operation in POINTED:
            info.update(point=[message.get("x"), message.get("y")], screen=message.get("screen"))
        if operation == "drag":
            info.update(to=[message.get("x2"), message.get("y2")], to_screen=message.get("screen2"))
        if operation == "type":  # what was typed is never logged
            info["characters"] = len(str(message.get("text", "")))
        if reason:
            info["reason"] = str(reason)[:120]
        self.shares.session.tools.audit.append("action", "window", str(message.get("agent", ""))[:120],
                                               f"point_{operation}", json.dumps(info, separators=(",", ":")))

    def begin(self, entry, message, route):
        """The audit row written before any input goes out; a log that cannot be written refuses the click."""
        try:
            self.record(entry, message, route, "dispatching")
        except OSError as exc:
            raise Refused(AUDIT) from exc

    def check(self, entry, access, grant, generation, message):
        """`(screen points, snapshot record)` once every refusal that needs no waiting has been passed.

        A click, scroll or drag names pixels of a snapshot, converted again with the helper's own geometry.
        Typing and keys name none: they need a click in this grant first and have no snapshot record."""
        live_entry = self.shares.grants.get(message.get("grant_id"))
        if (not grant or access.grant is not grant or live_entry is not entry
                or access.gate.revoked.is_set() or access.gate.generation != generation):
            raise Refused(GONE)
        if hard_floor(grant):
            raise Refused(FLOOR)
        operation = which(message)
        if operation in KEYBOARD:
            if entry.get("point_clicked") != generation:
                raise Refused(NEEDS_CLICK)
            return [], None
        record = entry.get("snapshots", {}).get(message.get("snapshot"))
        if not record or record["grant"] is not grant or record["generation"] != generation:
            raise Refused(STALE)
        points = []
        for x, y, told in (("x", "y", "screen"), ("x2", "y2", "screen2"))[:2 if operation == "drag" else 1]:
            try:
                point = locate(record["geometry"], message.get(x), message.get(y))
            except GeometryError as exc:
                raise Refused(str(exc)) from exc
            if list(point) != list(message.get(told) or point):
                raise Refused("the server and the helper disagree about that snapshot: take a fresh one")
            points.append(point)
        return points, record

    async def current(self, entry, access, grant, generation, message):
        """`check`, then the live window: still there, not on the secure desktop, same place and shape."""
        points, record = self.check(entry, access, grant, generation, message)
        reason = await access.check(grant)
        if reason == "window closed":
            access.revoke(reason)
        if reason:
            raise Refused(reason)
        if record:
            await asyncio.to_thread(self.shifted, record, grant)
        return points

    def shifted(self, record, grant):
        """Refuse unless the window is exactly where and as large as the snapshot recorded (blocking call)."""
        layout = self.shares.snapshots.backend.layout(grant["hwnd"])
        wanted = record["geometry"]
        if (tuple(layout["rect"]) != tuple(wanted["rect"])
                or sorted(map(tuple, layout["regions"])) != sorted(map(tuple, wanted["regions"]))):
            raise Refused(STALE)

    async def run(self, entry, message, active):
        access = entry["access"]
        grant, generation = access.grant, access.gate.generation
        try:
            operation, args = arguments(message)
        except ValueError as exc:
            raise Refused(str(exc)) from exc
        points = await self.current(entry, access, grant, generation, message)
        page = (await self.shares.chrome.page(access)
                if str(grant.get("process", "")).lower() == "chrome.exe" else None)
        if page:
            route, result = "cdp", await self.via_cdp(entry, message, page, access, grant, generation, args)
        else:
            for_cursor(operation, points, args)  # refuses what the real keyboard never sends, before asking
            epoch = self.shares.generation
            reason = await self.consent.check(entry, message)
            if self.shares.generation != epoch:  # access was switched off or paused while asked
                clear(entry)
                raise Refused(GONE)
            if self.clock() >= message["deadline"]:  # the answer came too late: it counts for nothing
                clear(entry)
                raise Refused(LATE)
            if reason:
                raise Refused(reason)
            points = await self.current(entry, access, grant, generation, message)  # it may have changed
            if active:
                active[0].mark_mouse(active[1])
            route, result = "cursor", await self.via_cursor(entry, message, access, grant, generation,
                                                            points, epoch, args)
        if operation == "click" and result.get("status") == "completed":
            entry["point_clicked"] = generation  # typing and keys may follow in this grant
        return route, result

    async def via_cdp(self, entry, message, page, access, grant, generation, args):
        operation = which(message)
        if grant.get("target_id") and not await page.visible():  # a picked tab may be behind the shown one
            raise Refused(HIDDEN)
        frame = None
        if operation in POINTED:  # the first point picks the renderer when Chrome shows several
            first = (await self.current(entry, access, grant, generation, message) or [None])[0]
            frame = await page_frame(page, grant["hwnd"], first, self.sources)
        points = await self.current(entry, access, grant, generation, message)  # the window may have moved
        self.late(message)
        self.begin(entry, message, "cdp")
        page.dispatched, page.operation_epoch = False, None
        limit = min(message["deadline"], self.clock() + TIMEOUT)  # no new press after the budget or the cap

        def guard():
            if self.clock() >= limit:
                raise CDPError(PARTLY if page.dispatched else LATE)
        api, landing = self.pointer(grant["hwnd"]), message["landing"]
        with landing_session(api, grant, landing, page):
            try:
                info = await by_cdp(operation, page, frame, points, args, guard)
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

    async def via_cursor(self, entry, message, access, grant, generation, points, epoch, args):
        operation = which(message)
        spots, send, partial, check = for_cursor(operation, points, args)
        self.begin(entry, message, "cursor")
        record = entry.get("snapshots", {}).get(message.get("snapshot")) if operation in POINTED else None

        def ready():
            """The window is where the snapshot saw it, now that it is in front (a blocking call)."""
            if record:
                self.shifted(record, grant)

        def last():
            """Cheap and last: nothing blocks between this and the input."""
            self.late(message)
            if access.gate.revoked.is_set() or access.gate.generation != generation:
                raise PointRefused("revoked")
            if (not entry.get("mouse_approved") or self.shares.generation != epoch
                    or self.shares.grants.get(message.get("grant_id")) is not entry):
                raise Refused(GONE)  # access was switched off, paused or ended after the person said yes

        def alive():
            self.late(message)
            if access.gate.revoked.is_set() or access.gate.generation != generation:
                raise PointRefused("revoked")
            windows = access.list_windows()
            if windows is None:
                raise PointRefused("secure desktop active")
            if (not any(w["hwnd"] == grant["hwnd"] and w["pid"] == grant["pid"] for w in windows)
                    or (grant.get("marker") and not live(grant))):
                raise PointRefused("window closed")

        def call():
            return cursor_run(self.pointer(grant["hwnd"]), grant, spots, send, alive,
                              getattr(access, "event_state", None), ready, last, check, partial, operation,
                              message["landing"])
        try:
            result, revoked = await asyncio.wait_for(
                asyncio.to_thread(access.gate.dispatch, generation, call), TIMEOUT)
        except TimeoutError:
            message["landing"]["input_sent"] = None
            access.gate.invalidate()
            return {"status": "unconfirmed", "error": f"the {operation} did not finish in time"}
        except ValueError as exc:  # the gate: revoked before the input
            raise Refused(GONE if str(exc) == "revoked" else str(exc)) from exc
        if revoked or access.gate.revoked.is_set():
            result["revoked_during"] = True
        return result
