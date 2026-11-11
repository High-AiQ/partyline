"""Outbound protocol v1 session, consent lifecycle and reconnect policy."""
import asyncio
import contextlib
import json
import math
import platform
import time

from websockets.asyncio.client import connect
from websockets.exceptions import ConnectionClosed, InvalidHandshake, InvalidStatus

from .bounds import MAX_MESSAGE_BYTES, bounded, validate_request
from .control import CONTROL_VERSION, Control
from .desktop import pointer_state
from .images import changed, encode, thumbnail
from .status import Status
from .tools import MESSAGES as TOOL_MESSAGES, TOOLS_VERSION, Tools
from .transport import CertificateError, certificate_failure
from .version import helper_version
from .uia_access import WindowAccess
from .uia_task import WindowTask, read_options
from .session_transport import SessionTransport
from .window_shares import MESSAGES as WINDOW_MESSAGES, WindowShares

class Revoked(Exception):
    """The paired credential is no longer authorized."""


class Session(SessionTransport):
    def __init__(self, socket, desktop, terminal, name, yes=False, preview_times=None,
                 clock=time.monotonic, sleep=asyncio.sleep, border=None, allow_control=False,
                 inputs=None, status=None):
        self.socket, self.desktop, self.terminal = socket, desktop, terminal
        self.status = status or Status()
        self.name, self.yes, self.border = name, yes, border
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
        self.control = Control(self, inputs, allow_control)
        self.tools = Tools(self)
        self.window = WindowAccess(self)
        self.window_task = WindowTask(self)
        self.windows = WindowShares(self)
        self.last_uia_frame = None

    async def stop(self, reason="remote", notify=True):
        self.control.end(f"sharing stopped: {reason}")  # before any await: no queued action runs
        if self.border:
            self.border.hide()
        self.status.set("paired")
        worker, self.worker = self.worker, None
        self.pending_id = None
        if worker:
            cancellations = asyncio.current_task().cancelling()
            worker.cancel()
            try:
                await worker
            except asyncio.CancelledError:
                if asyncio.current_task().cancelling() > cancellations:
                    raise
            except ConnectionClosed:
                pass
        share, self.share = self.share, None
        self.accepted = False
        self.last_uia_frame = None
        if share and notify:
            await self.send("share_stopped", share_id=share["share_id"], reason=reason)
        if share:
            print(f"Sharing stopped: {reason}", flush=True)

    def validate(self, request):
        validate_request(self.desktop, request)

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
            if self.border:
                self.border.show(request["region"])
            await self.send("share_accepted", share_id=request["share_id"])
            self.accepted = True
            self.status.set("sharing")
            self.terminal.clear()
            print("SHARING ACTIVE — type s Enter or press Ctrl+C to stop", flush=True)
            if request.get("control") is True:  # the person asked for agent control with the share
                await self.control.request(dict(request, type="control_request"))
            from .capture_loop import capture
            await capture(self, request)
        except (ValueError, TypeError, KeyError, RuntimeError, OSError) as exc:
            accepted = self.share is not None
            self.share = None
            self.accepted = False
            print(f"Share ended: {exc}", flush=True)
            await self.send("share_stopped" if accepted else "share_declined",
                            share_id=request.get("share_id"), reason=str(exc))
        finally:
            self.control.end("share ended")
            if self.border:
                self.border.hide()
            self.status.set("paired")

    async def frame(self, request_id=None, force=False):
        async with self.frame_lock:
            return await self._frame(request_id, force)

    async def _frame(self, request_id, force=False):
        share = self.share
        if not share or not self.accepted:
            return
        if (not force and self.last_frame_at is not None
                and self.clock() - self.last_frame_at < 1 / share["max_fps"]):
            if request_id is not None:
                await self.send("error", request_id=request_id,
                                message="Snap rate limit: wait for the next frame")
            return
        region = share["region"]
        image = self.desktop.grab(region)
        thumb = thumbnail(image)
        pointer = pointer_state(self.desktop, region)
        if (request_id is None and not changed(self.previous, thumb, share["min_change"])
                and pointer == self.last_pointer):
            return
        binary, width, height, mime = encode(image, share["long_edge"])
        await self.send("frame", binary, share_id=share["share_id"], request_id=request_id,
                        ts_ms=int((self.clock() - self.started) * 1000), region=region,
                        out_width=width, out_height=height, pointer=pointer, mime=mime)
        self.last_uia_frame = (dict(region), width, height)
        self.previous, self.last_pointer = thumb, pointer
        self.last_frame_at = self.clock()

    async def dispatch(self, message):
        kind = message["type"]
        if kind == "start_share":
            if (self.worker and not self.worker.done() and not self.accepted
                    and self.pending_id is not None):
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
        elif kind in ("control_request", "control_revoked", "action"):
            await self.control.dispatch(message)
        elif kind in TOOL_MESSAGES:
            await self.tools.dispatch(message)
        elif kind in WINDOW_MESSAGES:
            await self.windows.receive(message)
        elif kind in ("read_window_elements", "window_element_action") and "grant_id" in message:
            await self.windows.dispatch(message)
        elif kind == "read_window_elements":
            await self.window_task.submit(message["request_id"], read_options(message))
        elif kind == "window_element_action":
            await self.window_task.submit_action(message)
        elif kind == "ping":
            await self.send("pong")
        elif kind not in ("pong", "snap", "error"):
            await self.send("error", request_id=message.get("request_id"), message=f"unsupported: {kind}")

    async def heartbeat(self):
        while True:
            # no-poll (c): websocket ping keeps the connection alive through idle proxies
            await self.sleep(min(15, max(0, 45 - (self.clock() - self.last_received))))
            if self.clock() - self.last_received >= 45:
                await self.socket.close(code=1011, reason="Heartbeat timeout")
                return
            await self.send("ping")

    async def run(self):
        await self.send("hello", protocol=1, device_name=self.name, os=platform.system(),
                        helper_version=helper_version(), monitors=self.desktop.monitors(),
                        control=CONTROL_VERSION, tools=TOOLS_VERSION)
        self.status.set("paired")
        loop = asyncio.get_running_loop()
        # The tray's Stop sharing runs on another thread: hand the stop to this loop.
        self.status.stop_share = lambda: asyncio.run_coroutine_threadsafe(self.stop("local"), loop)
        self.status.choose_window = lambda: asyncio.run_coroutine_threadsafe(self.windows.choose(), loop)
        self.status.stop_window = lambda: loop.call_soon_threadsafe(self.windows.revoke_all)
        heartbeat = asyncio.create_task(self.heartbeat())
        self.status.stop_window_grant = lambda ident: loop.call_soon_threadsafe(self.windows.revoke, ident)
        window_watch = asyncio.create_task(self.windows.watch())
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
            window_watch.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await window_watch
            with contextlib.suppress(asyncio.CancelledError):
                await heartbeat
            with contextlib.suppress(ConnectionClosed):
                await self.stop("disconnected")
            await self.tools.end("disconnected")
            self.status.stop_share = None
            self.status.choose_window = self.status.stop_window = None
            self.window.revoke()
            await self.window_task.close()
            await self.windows.close()
            self.status.stop_window_grant = None
            self.status.set("offline")
        if self.socket.close_code in (1008, 4001, 4003, 4401, 4403):
            raise Revoked


async def serve(config, desktop, terminal, yes=False, sleep=asyncio.sleep,
                clock=time.monotonic, session_sleep=asyncio.sleep, border=None, allow_control=False,
                inputs=None, status=None):
    from .config import server_url
    server = server_url(config["server"])
    url = ("wss" if server.startswith("https:") else "ws") + server[server.index(":"):] + "/api/screen/helper"
    delay = 1
    preview_times = {}
    while True:
        try:
            async with connect(url, additional_headers={"Authorization": "Bearer " + config["token"]},
                               ping_interval=None, max_size=MAX_MESSAGE_BYTES) as socket:
                connected_at = clock()
                await Session(socket, desktop, terminal, config.get("device_name", "Desktop"),
                              yes, preview_times, clock, session_sleep, border=border,
                              allow_control=allow_control, inputs=inputs, status=status).run()
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
        # no-poll (e): reconnect after transport failure; success ends retries
        await sleep(delay)
        delay = min(60, delay * 2)
