"""One screenshot of a granted window, answered with the server's request id even when it fails."""
import asyncio
import contextlib
import time
from io import BytesIO

from websockets.exceptions import ConnectionClosed

from .window_grab import GrabError, WindowGrab
from .timing import Timing

SNAPSHOT_VERSION = 2  # the `windows` hello value that includes window screenshots
MAX_BYTES = 20 * 1024 * 1024  # the media store's own image limit: a larger one loses quality, never size
CHUNK = 4 * 1024 * 1024  # one binary message; a bigger image travels as several in a row
QUALITIES = (95, 90, 80, 70, 50)
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
        try:
            await self.take(entry, message, request_id)
        except GrabError as exc:
            await self.reply(request_id, ok=False, error=str(exc))
        except Exception as exc:  # noqa: BLE001 - whatever fails, the caller gets an answer, not a timeout
            print(f"Window screenshot failed: {exc!r}", flush=True)
            await self.reply(request_id, ok=False, error="the screenshot failed; see the helper's terminal")

    async def take(self, entry, message, request_id):
        timing = Timing()
        access = entry["access"] if entry else None
        grant = access.grant if access else None
        if not grant:
            raise GrabError("consent revoked")
        generation = access.generation
        await self.check(access, grant, generation)
        if await asyncio.to_thread(self.backend.minimized, grant["hwnd"]):
            raise GrabError(MINIMIZED)
        with timing.phase("capture_ms"):
            image = await asyncio.to_thread(self.backend.grab, grant["hwnd"])
        with timing.phase("encode_ms"):
            binary, mime, black = await asyncio.to_thread(prepare, image)
        agent = str(message.get("agent") or "an agent")[:80]

        async def gate():
            """The one consent check, under the writer lock: a revoke while queued sends nothing."""
            await self.check(access, grant, generation)
            entry["last_screenshot"] = {"at": self.clock(), "by": agent}
            self.shares.changed()
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
                         height=image.height, media=True, chunks=len(chunks), timing=timing.values,
                         **({"blank": True} if black else {}))

    @staticmethod
    async def check(access, grant, generation):
        reason = await access.check(grant)
        if access.grant is not grant or access.generation != generation:
            raise GrabError("consent revoked")
        if reason == "window closed":
            access.revoke(reason)
        if reason:
            raise GrabError(reason)
