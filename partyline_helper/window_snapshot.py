"""One screenshot of a granted window, answered with the server's request id even when it fails."""
import asyncio
import contextlib
import time
import uuid
from collections import OrderedDict
from io import BytesIO

from websockets.exceptions import ConnectionClosed

from partyline.point_geometry import GeometryError, clean

from .window_grab import GrabError, WindowGrab
from .timing import Timing
from .window_fit import budget, fitted
from .window_marks import boxes, clean_inputs, draw, listed

SNAPSHOT_VERSION = 2  # the `windows` hello value that includes window screenshots
MAX_BYTES = 20 * 1024 * 1024  # the media store's own image limit: a larger one loses quality, never size
CHUNK = 4 * 1024 * 1024  # one binary message; a bigger image travels as several in a row
QUALITIES = (95, 90, 80, 70, 50)
KEPT = 8  # snapshots per grant a later click may still name
MINIMIZED = ("the window is minimised; Partyline never restores it. Ask the person to bring it back, "
             "then try again")


def prepare(image):
    """`(bytes, mime, black)`: the window at its own size, lossless when that fits one message.

    A window too detailed for one message is saved at the highest WebP quality that fits, never smaller.
    """
    image = image.convert("RGB")
    black = not any(image.convert("L").getextrema())
    out = BytesIO()
    image.save(out, "PNG")
    if out.tell() <= MAX_BYTES:
        return out.getvalue(), "image/png", black
    for quality in QUALITIES:
        out = BytesIO()
        image.save(out, "WEBP", quality=quality, method=4)
        if out.tell() <= MAX_BYTES:
            return out.getvalue(), "image/webp", black
    raise GrabError(f"the window is {image.width}x{image.height}, too detailed to send even compressed")


class WindowSnapshots:
    def __init__(self, shares, backend=None, clock=time.time):
        self.shares, self.backend, self.clock = shares, backend or WindowGrab(), clock

    async def reply(self, request_id, binary=None, before=None, **fields):
        with contextlib.suppress(ConnectionClosed, OSError):
            await self.shares.session.send("window_snapshot", binary, before, request_id=request_id, **fields)

    async def handle(self, entry, message):
        """Answer one `snapshot_window` request: an image, or `ok: false` with the reason."""
        request_id = message["request_id"]
        from .screen_access_audit import begin_window_call, end_window_call
        active = (begin_window_call(getattr(entry["access"], "session", self.shares.session),
                                    message.get("agent", ""), message.get("line_name")
                                    or message.get("line")) if entry else None)
        try:
            await self.take(entry, message, request_id)
        except GrabError as exc:
            self.audit(entry, message, "failed")
            await self.reply(request_id, ok=False, error=str(exc))
        except Exception as exc:  # noqa: BLE001 - whatever fails, the caller gets an answer, not a timeout
            print(f"Window screenshot failed: {exc!r}", flush=True)
            self.audit(entry, message, "failed")
            await self.reply(request_id, ok=False, error="the screenshot failed; see the helper's terminal")
        finally:
            if active:
                end_window_call(active)

    async def take(self, entry, message, request_id):
        timing = Timing()
        access = entry["access"] if entry else None
        grant = access.grant if access else None
        if not grant:
            raise GrabError("consent revoked")
        generation, gate_generation = access.generation, access.gate.generation
        await self.check(access, grant, generation)
        if await asyncio.to_thread(self.backend.minimized, grant["hwnd"]):
            raise GrabError(MINIMIZED)
        with timing.phase("capture_ms"):
            image = fitted(await asyncio.to_thread(self.backend.grab, grant["hwnd"]), budget(message))
        ident, geometry = self.remember(entry, grant, image, gate_generation)
        found = None
        if message.get("overlay") and geometry:
            found = boxes(clean_inputs(message.get("marks")), geometry, await self.page(access, grant))
            image = draw(image, found)
        with timing.phase("encode_ms"):
            binary, mime, black = await asyncio.to_thread(prepare, image)
        chrome = getattr(getattr(access, "session", None), "chrome", None)
        metadata = chrome.metadata(access) if chrome else {}
        agent = str(message.get("agent") or "an agent")[:80]

        async def gate():
            """The one consent check, under the writer lock: a revoke while queued sends nothing."""
            await self.check(access, grant, generation)
            entry["last_screenshot"] = {"at": self.clock(), "by": agent}
            self.shares.changed()
            self.audit(entry, message, "captured")
            try:
                names = image.info.get("scoped_popups", [])
                popup_info = f", owned popups: {', '.join(names)}" if names else ""
                self.shares.session.tools.audit.append(
                    "event", "window", agent, "window_snapshot",
                    f"{grant['title']} ({grant['process']}): {image.width}x{image.height}, "
                    f"{len(binary)} bytes{popup_info}")
            except OSError as exc:  # the person's record comes first: no entry, no image
                raise GrabError("the helper could not write its audit log") from exc
        chunks = [binary[i:i + CHUNK] for i in range(0, len(binary), CHUNK)]
        await self.reply(request_id, chunks, gate, ok=True, mime=mime, width=image.width,
                         height=image.height, media=True, chunks=len(chunks),
                         timing=timing.values, **metadata,
                         **({"blank": True} if black else {}),
                         **({"snapshot_id": ident, "geometry": {k: geometry[k] for k in (
                             "rect", "size", "regions", "dpi")}} if ident else {}),
                         **({"marks": listed(found)} if found is not None else {}))

    @staticmethod
    def remember(entry, grant, image, generation):
        """Keep what a later click needs to convert this picture; `(id, geometry)` or `(None, None)`."""
        rect, regions = image.info.get("rect"), image.info.get("regions")
        if not rect or not regions:
            return None, None
        try:
            geometry = clean({"rect": list(rect), "size": [image.width, image.height],
                              "dpi": image.info.get("dpi", 96), "regions": [list(r) for r in regions]})
        except GeometryError:
            return None, None
        ident = uuid.uuid4().hex[:16]
        rows = entry.setdefault("snapshots", OrderedDict())
        rows[ident] = {"geometry": geometry, "grant": grant, "generation": generation}
        while len(rows) > KEPT:
            rows.popitem(last=False)
        return ident, geometry

    async def page(self, access, grant):
        """Where a Chrome page's CSS pixels are on screen, for marks on page elements; None when unknown."""
        chrome = getattr(self.shares, "chrome", None)
        if not chrome or str(grant.get("process", "")).lower() != "chrome.exe":
            return None
        from .cdp_transport import CDPError
        from .point_cdp import page_frame
        try:
            page = chrome.pages.get(access, {}).get(chrome.selected.get(access))
            if not page or not page.live or page.page_state != "alive":
                return None
            sources = getattr(getattr(self.shares, "clicks", None), "sources", None)  # the clicks' own
            return (await page_frame(page, grant["hwnd"], None, sources))[:3]
        except (CDPError, OSError):
            return None

    @staticmethod
    def audit(entry, message, result):
        if entry:
            from .screen_access_audit import audit_window
            session = getattr(entry["access"], "session", None)
            if session is not None:
                audit_window(session, "screenshot", message.get("agent", ""), result,
                             message.get("line"))
        else:
            from .screen_access_audit import append_metadata
            append_metadata(message, "screenshot", result)

    @staticmethod
    async def check(access, grant, generation):
        reason = await access.check(grant)
        if access.grant is not grant or access.generation != generation:
            raise GrabError("consent revoked")
        if reason == "window closed":
            access.revoke(reason)
        if reason:
            raise GrabError(reason)
