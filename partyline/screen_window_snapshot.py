"""One screenshot of a window granted to the caller's line: native size, stored as line media, audited.

Elements stay the default way to read a window; this is for layout and visuals. The helper captures that one
window (never the desktop around it) and sends the image after a `window_snapshot` message. The media store
keeps it as the original and derives its `slim` and `thumb` tiers, as for every image.
"""
import asyncio
import time
from types import SimpleNamespace
from typing import Literal

from fastapi import APIRouter, HTTPException, Request

from .auth_guard import request_principal
from .machine_scope import deny_unless
from .local_tools_media import decodes
from .media import MAX_IMAGE_BYTES, MediaError
from .screen_audit import record
from .screen_errors import screen_error
from .screen_frame_store import frame_reference
from .screen_grants import require_window, resolve_window
from .screen_protocol import HEARTBEAT_TIMEOUT
from .screen_timing import timed, phase, locked
from .screen_window_marks import (NO_TREE, THUMB_EDGE, THUMB_PIXELS, USE, Geometries, clean_marks,
                                  mark_inputs)

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


KEPT_WHEN_UNCHANGED = ("snapshot", "note", "budget", "source", "page_state", "recovery_hint")


class WindowSnapshots:
    def __init__(self, hub, wall=time.time):
        from .screen_window_look import WindowLooks
        self.looks = WindowLooks(hub)
        self.hub, self.wall = hub, wall
        self.last = {}  # window grant id -> {"at": epoch seconds, "by": handle} of its latest capture
        self.shares = {}  # window grant id -> what frame_reference needs to say "unchanged"
        self.locks = {}
        self.geometry = Geometries()  # window grant id -> the geometry of its latest snapshots
        self.marks = {}  # (window grant id, handle) -> the marks that process was last sent

    def end(self, grant_id):
        self.looks.end(grant_id)
        for table in (self.last, self.shares, self.locks):
            table.pop(grant_id, None)
        for key in [key for key in self.marks if key[0] == grant_id]:
            del self.marks[key]
        self.geometry.end(grant_id)

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
    async def take(self, principal, store, window=None, device_name=None, marks=False, tier=None,
                   landing=None):
        """One picture. `tier` "thumb" (the default with marks) shrinks the window to THUMB_EDGE x
        THUMB_PIXELS
        before the boxes are drawn and its geometry is recorded, so the picture costs at most ~930 image
        tokens and its pixels are the ones a point operation takes; "full" is the window's own size."""
        tier = tier or ("thumb" if marks else "full")
        grant, device = resolve_window(self.hub, principal, window, device_name)
        if device.get("windows", 0) < MIN_WINDOWS:
            raise HTTPException(409, OLD_HELPER)
        async with locked(self.locks.setdefault(grant["id"], asyncio.Lock())):
            tree = self.hub.elements.snapshots.get(grant["id"]) if marks else None
            extra = {"overlay": True, "marks": mark_inputs(tree) if tree is not None else []} if marks else {}
            if landing is not None:
                extra["landing"] = list(landing)
            if tier == "thumb":
                extra["fit"] = {"edge": THUMB_EDGE, "pixels": THUMB_PIXELS}
            try:
                answer = await self.hub.elements.exchange(principal, grant, device, "snapshot_window",
                                                          agent=principal.name, **extra)
            except (TimeoutError, OSError, RuntimeError) as exc:
                raise screen_error(exc if isinstance(exc, TimeoutError) else ValueError(
                    "the computer did not take the screenshot")) from exc
            if answer.get("ok") is not True:
                reason = answer.get("error") or "the computer could not take the screenshot"
                raise HTTPException(409, str(reason)[:300])
            if landing is not None and answer.get("landing_marked") is not True:
                raise HTTPException(409, "update the Partyline helper to get a marked landing thumbnail")
            with phase("image_store_ms"):
                result = await self.keep(store, principal, grant, answer, tier)
                if marks:
                    listed = clean_marks(answer.get("marks")) if tree is not None else []
                    key = (grant["id"], principal.name)
                    if result["unchanged"] and self.marks.get(key) == listed:
                        result["marks_unchanged"] = True
                    else:
                        result["marks"] = listed
                    self.marks[key] = listed
                    if tree is None:
                        result["marks_note"] = NO_TREE
                return result

    async def keep(self, store, principal, grant, answer, tier="full"):
        data, mime = answer.get("data"), answer.get("mime")
        if (not data or len(data) > MAX_IMAGE_BYTES or mime not in MIMES
                or not await asyncio.to_thread(decodes, data)):
            raise HTTPException(502, "the computer sent an image that cannot be used")
        require_window(self.hub, principal, grant["id"])  # nothing is stored for a grant that has ended
        share = self.shares.setdefault(grant["id"], SimpleNamespace(
            frame_lock=asyncio.Lock(), agent_frames={}, conv_id=grant["conv_id"]))
        sender = (principal.name, "landing") if answer.get("landing_marked") else principal.name
        try:
            ref, unchanged = await frame_reference(
                store, share, sender,
                SimpleNamespace(region=None, out_width=answer.get("width"), out_height=answer.get("height")),
                data, mime)
        except MediaError as exc:  # bytes the media store cannot read as an image
            raise HTTPException(502 if exc.status_code == 400 else exc.status_code, exc.detail) from exc
        try:
            await self.audit(principal, grant, ref)
            require_window(self.hub, principal, grant["id"])  # the one gate: nothing awaits before the return
        except HTTPException:  # the grant ended during storage or the device update
            if not unchanged:
                share.agent_frames.pop(sender, None)
                await asyncio.to_thread(store.delete_file, ref.id)
            record(self.hub.runtime.db, grant["id"], principal.conv_id or grant["conv_id"], principal.name,
                   f"window screenshot withheld: {grant['process']} — {grant['title']} "
                   "(result=withheld; the grant ended before delivery)")
            raise
        result = {"file": ref.model_dump(mode="json"), "window": grant["id"], "title": grant["title"],
                  "width": ref.width, "height": ref.height, "variants": variants(ref),
                  "use": "slim is the usual choice; full is the window's own pixels", "unchanged": unchanged}
        result.update({key: answer[key] for key in ("source", "page_state", "recovery_hint")
                       if key in answer})
        if tier == "thumb":  # the picture was shrunk to the budget, so full and slim are the same pixels
            result["variants"] = {name: tiers for name, tiers in result["variants"].items() if name != "full"}
            result["budget"] = {"tier": "thumb", "max_edge": THUMB_EDGE, "max_pixels": THUMB_PIXELS,
                                "image_tokens": image_tokens(ref.width, ref.height)}
            result["use"] = "slim is this picture (the thumb tier); thumb is a 512 px glance"
        if answer.get("blank") is True:
            result["note"] = BLANK
        if self.geometry.keep(grant["id"], answer.get("snapshot_id"), answer.get("geometry")):
            result.update(snapshot=answer["snapshot_id"], coordinates=USE)
        if unchanged and not answer.get("landing_marked"):  # reuse the image with its new snapshot id
            result = {"unchanged": True, "file": {"id": ref.id}, "window": grant["id"],
                      "title": grant["title"],
                      "width": ref.width, "height": ref.height,
                      **{key: result[key] for key in KEPT_WHEN_UNCHANGED if key in result},
                      "use": "the picture is the same as your last one for this window: use that image with "
                             "this snapshot id"}
        return result

    async def audit(self, principal, grant, ref):
        self.last[grant["id"]] = {"at": self.wall(), "by": principal.name}
        db = self.hub.runtime.db
        detail = (f"({ref.width}x{ref.height}, {ref.bytes // 1024} KB; "
                  f"app={grant['process']}; result=completed)")
        record(db, grant["id"], principal.conv_id or grant["conv_id"], principal.name,
               f"window screenshot of «{grant['title']}» {detail}")
        await self.hub.window_grants.changed(grant["device_id"])


def snapshot_router(runtime, hub, store):
    router = APIRouter()

    @router.post("/api/conversations/{conv_id}/screen-window-snapshot")
    @timed
    async def window_snapshot(conv_id: str, request: Request, device: str | None = None,
                              window: str | None = None, marks: bool = False,
                              tier: Literal["thumb", "full"] | None = None):
        principal = request_principal(request)
        deny_unless(runtime.db, principal, conv_id, "read")
        from .screen_grants import resolve_window
        grant, _ = resolve_window(hub, principal, window, device)
        from .screen_workflow_learning import record_call
        try:
            result = await hub.snapshots.take(principal, store, window, device, marks, tier)
        except HTTPException:
            record_call(runtime.db, grant["id"], "screen_window_snapshot",
                        {"marks": marks, "tier": tier}, "failed")
            raise
        record_call(runtime.db, grant["id"], "screen_window_snapshot",
                    {"marks": marks, "tier": tier}, "returned", None)
        return result

    @router.post("/api/conversations/{conv_id}/screen-window-look")
    @timed
    async def window_look(conv_id: str, request: Request, window: str | None = None,
                          detail: Literal["thumb", "slim", "full"] = "thumb", query: str | None = None):
        principal = request_principal(request)
        deny_unless(runtime.db, principal, conv_id, "read")
        if query is not None and not 1 <= len(query) <= 200:
            raise HTTPException(422, "query must have 1–200 characters")
        from .screen_grants import resolve_window
        grant, _ = resolve_window(hub, principal, window)
        from .screen_workflow_learning import record_call
        try:
            result = await hub.snapshots.looks.take(principal, store, window, detail, query)
        except HTTPException:
            record_call(runtime.db, grant["id"], "screen_window_look",
                        {"detail": detail, "query": query}, "failed")
            raise
        record_call(runtime.db, grant["id"], "screen_window_look",
                    {"detail": detail, "query": query}, "returned", None)
        return result

    return router
