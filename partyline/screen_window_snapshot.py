"""One screenshot of a window granted to the caller's line: native size, stored as line media, audited.

Elements stay the default way to read a window; this is for layout and visuals. The helper captures that one
window (never the desktop around it) and sends the image after a `window_snapshot` message. The media store
keeps it as the original and derives its `slim` and `thumb` tiers, as for every image.
"""
import asyncio
import time
from types import SimpleNamespace

from fastapi import APIRouter, HTTPException, Request

from .auth_guard import request_principal
from .contracts import MessageEvent, MessageResponse
from .machine_scope import deny_unless
from .local_tools_media import decodes
from .media import MAX_IMAGE_BYTES, MediaError
from .screen_audit import publish, record
from .screen_errors import screen_error
from .screen_frame_store import frame_reference
from .screen_grants import require_window, resolve_window
from .screen_protocol import HEARTBEAT_TIMEOUT
from .screen_timing import timed, phase, locked

MAX_CHUNKS = 8  # binary messages one screenshot may travel in; the image itself is capped by the media store
MIN_WINDOWS = 2  # the helper's `windows` hello value that can take window screenshots
OLD_HELPER = "update the Partyline helper to use window screenshots"
MIMES = ("image/png", "image/webp", "image/jpeg")
CLAUDE_EDGE, CLAUDE_PIXELS = 1568, 1_150_000  # a model shrinks an image past these before it reads it
BLANK = ("The image is entirely black: the window shows protected (DRM) content, which Windows hides from "
         "every capture, or it has drawn nothing yet. Read screen_elements instead.")


def image_tokens(width, height):
    """What a vision model charges to read an image: width x height / 750, after its own resize."""
    scale = min(1, CLAUDE_EDGE / max(width, height), (CLAUDE_PIXELS / (width * height)) ** 0.5)
    return round(width * scale * height * scale / 750)


def variants(ref):
    """The `full`, `slim` and `thumb` tiers: where each is served from, its size and what it costs to read."""
    tiers = {"full": (ref.width, ref.height, ref.urls.original)}
    for name in ("slim", "thumb"):
        if tier := getattr(ref, name):
            tiers[name] = (tier.width, tier.height, getattr(ref.urls, name))
    return {name: {"url": url, "width": width, "height": height, "image_tokens": image_tokens(width, height)}
            for name, (width, height, url) in tiers.items()}


class WindowSnapshots:
    def __init__(self, hub, wall=time.time):
        self.hub, self.wall = hub, wall
        self.last = {}  # window grant id -> {"at": epoch seconds, "by": handle} of its latest capture
        self.shares = {}  # window grant id -> what frame_reference needs to say "unchanged"
        self.locks = {}

    def end(self, grant_id):
        for table in (self.last, self.shares, self.locks):
            table.pop(grant_id, None)

    def last_screenshot(self, grant_id):
        return self.last.get(grant_id)

    async def from_helper(self, device, message):
        """The helper's answer; its image is the binary message that follows when `media` is true."""
        data = None
        if message.get("media") is True:
            count = message.get("chunks")
            count = count if isinstance(count, int) and 1 <= count <= MAX_CHUNKS else 1
            parts = [await asyncio.wait_for(device["socket"].receive_bytes(), HEARTBEAT_TIMEOUT)
                     for _ in range(count)]
            data = b"".join(parts) if sum(map(len, parts)) <= MAX_IMAGE_BYTES else None
        self.hub.elements.receive(device, {**message, "data": data})

    @timed
    async def take(self, principal, store, window=None, device_name=None):
        grant, device = resolve_window(self.hub, principal, window, device_name)
        if device.get("windows", 0) < MIN_WINDOWS:
            raise HTTPException(409, OLD_HELPER)
        async with locked(self.locks.setdefault(grant["id"], asyncio.Lock())):
            try:
                answer = await self.hub.elements.exchange(principal, grant, device, "snapshot_window",
                                                          agent=principal.name)
            except (TimeoutError, OSError, RuntimeError) as exc:
                raise screen_error(exc if isinstance(exc, TimeoutError) else ValueError(
                    "the computer did not take the screenshot")) from exc
            if answer.get("ok") is not True:
                reason = answer.get("error") or "the computer could not take the screenshot"
                raise HTTPException(409, str(reason)[:300])
            with phase("image_store_ms"):
                return await self.keep(store, principal, grant, answer)

    async def keep(self, store, principal, grant, answer):
        data, mime = answer.get("data"), answer.get("mime")
        if (not data or len(data) > MAX_IMAGE_BYTES or mime not in MIMES
                or not await asyncio.to_thread(decodes, data)):
            raise HTTPException(502, "the computer sent an image that cannot be used")
        require_window(self.hub, principal, grant["id"])  # nothing is stored for a grant that has ended
        share = self.shares.setdefault(grant["id"], SimpleNamespace(
            frame_lock=asyncio.Lock(), agent_frames={}, conv_id=grant["conv_id"]))
        try:
            ref, unchanged = await frame_reference(
                store, share, principal.name,
                SimpleNamespace(region=None, out_width=answer.get("width"), out_height=answer.get("height")),
                data, mime)
        except MediaError as exc:  # bytes the media store cannot read as an image
            raise HTTPException(502 if exc.status_code == 400 else exc.status_code, exc.detail) from exc
        try:
            await self.audit(principal, grant, ref)
            require_window(self.hub, principal, grant["id"])  # the one gate: nothing awaits before the return
        except HTTPException:  # the grant ended while it was stored or announced: nothing leaves or stays
            if not unchanged:
                share.agent_frames.pop(principal.name, None)
                await asyncio.to_thread(store.delete_file, ref.id)
            record(self.hub.runtime.db, grant["id"], grant["conv_id"], principal.name,
                   f"window screenshot withheld: {grant['process']} — {grant['title']} "
                   "(result=withheld; the grant ended before delivery)")
            raise
        result = {"file": ref.model_dump(mode="json"), "window": grant["id"], "title": grant["title"],
                  "width": ref.width, "height": ref.height, "variants": variants(ref),
                  "use": "slim is the usual choice; full is the window's own pixels", "unchanged": unchanged}
        if answer.get("blank") is True:
            result["note"] = BLANK
        return result

    async def audit(self, principal, grant, ref):
        self.last[grant["id"]] = {"at": self.wall(), "by": principal.name}
        db = self.hub.runtime.db
        detail = (f"({ref.width}x{ref.height}, {ref.bytes // 1024} KB; "
                  f"app={grant['process']}; result=completed)")
        record(db, grant["id"], grant["conv_id"], principal.name,
               f"window screenshot of «{grant['title']}» {detail}")
        message = publish(db, grant["id"])
        if message:
            await self.hub.runtime.broadcast(
                grant["conv_id"], MessageEvent(message=MessageResponse.model_validate(message)))
        await self.hub.window_grants.changed(grant["device_id"])


def snapshot_router(runtime, hub, store):
    router = APIRouter()

    @router.post("/api/conversations/{conv_id}/screen-window-snapshot")
    @timed
    async def window_snapshot(conv_id: str, request: Request, device: str | None = None,
                              window: str | None = None):
        principal = request_principal(request)
        deny_unless(runtime.db, principal, conv_id, "read")
        return await hub.snapshots.take(principal, store, window, device)

    return router
