"""Outbound protocol v1 session, consent lifecycle and reconnect policy."""
import asyncio
import contextlib
import json
import math
import platform
import time

from websockets.asyncio.client import connect
from websockets.exceptions import ConnectionClosed, InvalidHandshake, InvalidStatus

from .images import changed, encode, thumbnail
from .transport import CertificateError, certificate_failure


class Revoked(Exception):
    """The paired credential is no longer authorized."""


def bounded(value, default, low, high):
    number = float(value if value is not None else default)
    if not math.isfinite(number) or not low <= number <= high:
        raise ValueError("Share setting outside supported bounds")
    return number


class Session:
    def __init__(self, socket, desktop, terminal, name, yes=False, preview_times=None,
                 clock=time.monotonic, sleep=asyncio.sleep):
        self.socket, self.desktop, self.terminal = socket, desktop, terminal
        self.name, self.yes = name, yes
        self.clock, self.sleep = clock, sleep
        self.lock = asyncio.Lock()
        self.frame_lock = asyncio.Lock()
        self.preview_times = preview_times if preview_times is not None else {}
        self.accepted = False
        self.last_frame_at = None
        self.share = None
        self.worker = None
        self.pending_id = None
        self.last_received = self.clock()
        self.previous = self.last_pointer = None

    async def send(self, kind, binary=None, **fields):
        async def write():
            await self.socket.send(json.dumps(dict(type=kind, **fields)))
            if binary is not None:
                await self.socket.send(binary)

        async with self.lock:
            if binary is None:
                await write()
                return
            # Cancellation must not insert share_stopped between metadata and bytes.
            writing = asyncio.create_task(write())
            try:
                await asyncio.shield(writing)
            except asyncio.CancelledError:
                try:
                    await asyncio.wait_for(asyncio.shield(writing), 5)
                except (TimeoutError, ConnectionClosed):
                    await self.socket.close()
                    writing.cancel()
                    with contextlib.suppress(asyncio.CancelledError, ConnectionClosed):
                        await writing
                raise

    async def stop(self, reason="remote", notify=True):
        worker, self.worker = self.worker, None
        self.pending_id = None
        if worker:
            worker.cancel()
            with contextlib.suppress(asyncio.CancelledError, ConnectionClosed):
                await worker
        share, self.share = self.share, None
        self.accepted = False
        if share and notify:
            await self.send("share_stopped", share_id=share["share_id"], reason=reason)
        if share:
            print(f"Sharing stopped: {reason}", flush=True)

    def validate(self, request):
        region = request["region"]
        for key in ("x", "y", "width", "height"):
            if type(region[key]) is not int:
                raise ValueError("Region must use integer desktop pixels")
        if not 0 < region["width"] <= 32768 or not 0 < region["height"] <= 32768:
            raise ValueError("Invalid region dimensions")
        # Bound allocation and ensure all pixels belong to the virtual desktop.
        if region["width"] * region["height"] > 100_000_000:
            raise ValueError("Region is too large")
        monitors = self.desktop.monitors()
        left, top = min(m["x"] for m in monitors), min(m["y"] for m in monitors)
        right = max(m["x"] + m["width"] for m in monitors)
        bottom = max(m["y"] + m["height"] for m in monitors)
        if not (left <= region["x"] and top <= region["y"] and
                region["x"] + region["width"] <= right and region["y"] + region["height"] <= bottom):
            raise ValueError("Region is outside the desktop")
        request["max_fps"] = bounded(request.get("max_fps"), 1, 0.1, 30)
        request["long_edge"] = int(bounded(request.get("long_edge"), 1280, 1, 4096))
        request["min_change"] = bounded(request.get("min_change"), .02, 0, 1)

    async def start(self, request):
        try:
            self.validate(request)
            if not await self.terminal.consent(request, self.yes):
                await self.send("share_declined", share_id=request["share_id"],
                                reason="Local consent declined or timed out")
                return
            self.accepted = False
            self.started = self.clock()
            self.previous = self.last_pointer = self.last_frame_at = None
            self.share = request
            await self.send("share_accepted", share_id=request["share_id"])
            self.accepted = True
            self.terminal.clear()
            print("SHARING ACTIVE — type s Enter or press Ctrl+C to stop", flush=True)
            while True:
                await self.frame()
                end = self.clock() + 1 / request["max_fps"]
                while self.clock() < end:
                    if await self.terminal.read(min(.05, end - self.clock())) == "s":
                        self.share = None
                        self.accepted = False
                        await self.send("share_stopped", share_id=request["share_id"], reason="local")
                        print("Sharing stopped: local", flush=True)
                        return
        except (ValueError, TypeError, KeyError, RuntimeError, OSError) as exc:
            accepted = self.share is not None
            self.share = None
            self.accepted = False
            print(f"Share ended: {exc}", flush=True)
            await self.send("share_stopped" if accepted else "share_declined",
                            share_id=request.get("share_id"), reason=str(exc))

    async def frame(self, request_id=None):
        async with self.frame_lock:
            return await self._frame(request_id)

    async def _frame(self, request_id):
        share = self.share
        if not share or not self.accepted:
            return
        if self.last_frame_at is not None and self.clock() - self.last_frame_at < 1 / share["max_fps"]:
            if request_id is not None:
                await self.send("error", request_id=request_id,
                                message="Snap rate limit: wait for the next frame")
            return
        region = share["region"]
        image = self.desktop.grab(region)
        thumb = thumbnail(image)
        x, y = self.desktop.pointer()
        pointer = dict(x=x, y=y, visible=(region["x"] <= x < region["x"] + region["width"] and
                                       region["y"] <= y < region["y"] + region["height"]))
        if (request_id is None and not changed(self.previous, thumb, share["min_change"])
                and pointer == self.last_pointer):
            return
        binary, width, height, mime = encode(image, share["long_edge"])
        await self.send("frame", binary, share_id=share["share_id"], request_id=request_id,
                        ts_ms=int((self.clock() - self.started) * 1000), region=region,
                        out_width=width, out_height=height, pointer=pointer, mime=mime)
        self.previous, self.last_pointer = thumb, pointer
        self.last_frame_at = self.clock()

    async def dispatch(self, message):
        kind = message["type"]
        if kind == "start_share":
            if self.worker and not self.worker.done() and not self.accepted:
                await self.send("share_declined", share_id=message["share_id"], reason="prompt pending")
                return
            await self.stop("replaced")
            self.pending_id = message["share_id"]
            self.worker = asyncio.create_task(self.start(message))
        elif kind == "stop_share":
            # Also cancel consent before acceptance.
            if message["share_id"] == self.pending_id:
                await self.stop()
        elif kind == "snap" and self.share and message["share_id"] == self.share["share_id"]:
            await self.frame(message["request_id"])
        elif kind == "get_preview":
            monitor = next(m for m in self.desktop.monitors() if m["id"] == message["monitor_id"])
            now = self.clock()
            if now - self.preview_times.get(monitor["id"], -math.inf) < 3:
                await self.send("error", request_id=message["request_id"],
                                message="Preview rate limit: one per monitor every 3 seconds")
                return
            self.preview_times[monitor["id"]] = now
            print(f"Taking preview of monitor {monitor['id']}", flush=True)
            edge = min(480, int(bounded(message.get("long_edge"), 480, 1, 32768)))
            binary, width, height, mime = encode(self.desktop.grab(monitor), edge)
            await self.send("preview", binary, request_id=message["request_id"], monitor_id=monitor["id"],
                            out_width=width, out_height=height, mime=mime)
        elif kind == "ping":
            await self.send("pong")

    async def heartbeat(self):
        while True:
            await self.sleep(min(15, max(0, 45 - (self.clock() - self.last_received))))
            if self.clock() - self.last_received >= 45:
                await self.socket.close(code=1011, reason="Heartbeat timeout")
                return
            await self.send("ping")

    async def run(self):
        # Read distribution metadata without importing server modules.
        from importlib.metadata import version
        await self.send("hello", protocol=1, device_name=self.name, os=platform.system(),
                        helper_version=version("partyline"), monitors=self.desktop.monitors())
        heartbeat = asyncio.create_task(self.heartbeat())
        try:
            async for raw in self.socket:
                self.last_received = self.clock()
                message = None
                try:
                    message = json.loads(raw)
                    await self.dispatch(message)
                except (ValueError, KeyError, TypeError, StopIteration, RuntimeError, OSError) as exc:
                    print(f"Helper request failed: {exc}", flush=True)
                    request_id = message.get("request_id") if isinstance(message, dict) else None
                    await self.send("error", request_id=request_id,
                                    message="Invalid request or capture failed; see local terminal")
        finally:
            heartbeat.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await heartbeat
            with contextlib.suppress(ConnectionClosed):
                await self.stop("disconnected")
        if self.socket.close_code in (1008, 4001, 4003, 4401, 4403):
            raise Revoked


async def serve(config, desktop, terminal, yes=False, sleep=asyncio.sleep,
                clock=time.monotonic, session_sleep=asyncio.sleep):
    from .config import server_url
    server = server_url(config["server"])
    url = ("wss" if server.startswith("https:") else "ws") + server[server.index(":"):] + "/api/screen/helper"
    delay = 1
    preview_times = {}
    while True:
        try:
            async with connect(url, additional_headers={"Authorization": "Bearer " + config["token"]},
                               ping_interval=None, max_size=1_000_000) as socket:
                connected_at = clock()
                await Session(socket, desktop, terminal, config.get("device_name", "Desktop"),
                              yes, preview_times, clock, session_sleep).run()
                if clock() - connected_at >= 45:
                    delay = 1
        except InvalidStatus as exc:
            if exc.response.status_code in (401, 403):
                print("Device revoked. Pair again to reconnect.", flush=True)
                return
        except Revoked:
            print("Device revoked. Pair again to reconnect.", flush=True)
            return
        except ConnectionClosed as exc:
            if exc.rcvd and exc.rcvd.code in (1008, 4001, 4003, 4401, 4403):
                print("Device revoked. Pair again to reconnect.", flush=True)
                return
        except (OSError, TimeoutError, InvalidHandshake) as exc:
            if message := certificate_failure(exc, server):
                raise CertificateError(message) from None
        print(f"Disconnected. Reconnecting in {delay}s; active share ended.", flush=True)
        await sleep(delay)
        delay = min(60, delay * 2)
