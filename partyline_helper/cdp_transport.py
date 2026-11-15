"""One approved browser websocket, multiplexing CDP calls and pushed events."""
import asyncio
import contextlib
import json
import os
from pathlib import Path
import re

from websockets.asyncio.client import connect
from websockets.exceptions import WebSocketException

INSTRUCTION = "Enable remote debugging in Chrome at chrome://inspect/#remote-debugging"


class CDPError(ValueError):
    """A bounded, non-page-derived CDP failure."""


class DocumentChanged(CDPError):
    """The main document changed while element input was in flight."""


def discover(root=None):
    """Chrome/Puppeteer's approved-session discovery file; never launch or copy a profile."""
    root = Path(root) if root else Path(os.environ.get("LOCALAPPDATA", "")) / "Google/Chrome/User Data"
    try:
        port, path, *_ = root.joinpath("DevToolsActivePort").read_text(encoding="utf-8").splitlines()
        if not port.isdecimal() or not 0 < int(port) < 65536:
            return None
        if not re.fullmatch(r"/devtools/browser/[a-zA-Z0-9-]+", path):
            return None
        return f"ws://127.0.0.1:{int(port)}{path}"
    except (OSError, ValueError):
        return None


class BrowserConnection:
    def __init__(self, changed=lambda state, detail: None, discovery=discover, connector=connect):
        self.changed, self.discovery, self.connector = changed, discovery, connector
        self.state, self.detail = "not_enabled", INSTRUCTION
        self.socket = self.reader = None
        self.pending, self.listeners, self.result_hooks = {}, set(), {}
        self.serial = 0
        self.lock = asyncio.Lock()
        self.closed = False

    def report(self, state, detail=""):
        if (state, detail) == (self.state, self.detail):
            return
        self.state, self.detail = state, detail
        self.changed(state, detail)

    async def ensure(self):
        async with self.lock:
            if self.closed or self.state == "refused":
                return False
            if self.socket:
                return True
            endpoint = self.discovery()
            if not endpoint:
                self.report("not_enabled", INSTRUCTION)
                return False
            self.report("awaiting_approval", "Approve the remote debugging connection in Chrome")
            try:
                socket = await self.connector(endpoint, open_timeout=None, max_size=16 * 1024 * 1024)
                if self.closed:  # helper exit may race Chrome's approval prompt
                    await socket.close()
                    return False
                self.socket = socket
                self.reader = asyncio.create_task(self.receive())
                await self.call("Browser.getVersion")
            except asyncio.CancelledError:
                await self.disconnect()
                if not self.closed:
                    self.report("refused", "Chrome connection cancelled; share again to retry")
                raise
            except (OSError, TimeoutError, WebSocketException, CDPError):
                await self.disconnect()
                self.report("refused", "Chrome refused or closed the connection; share again to retry")
                return False
            self.report("connected")
            return True

    async def call(self, method, params=None, session=None, guard=lambda: None, on_result=None):
        guard()
        if not self.socket:
            raise CDPError("Chrome disconnected")
        self.serial += 1
        ident = self.serial
        future = asyncio.get_running_loop().create_future()
        self.pending[ident] = future
        if on_result:
            self.result_hooks[ident] = on_result
        message = {"id": ident, "method": method, "params": params or {}}
        if session:
            message["sessionId"] = session
        try:
            async with asyncio.timeout(10):
                guard()  # no await between consent check and websocket dispatch
                await self.socket.send(json.dumps(message))
                result = await future
            guard()  # discard a response that arrived after revocation
            return result
        except (OSError, TimeoutError, WebSocketException) as exc:
            raise CDPError("Chrome command interrupted; do not retry actions automatically") from exc
        finally:
            self.pending.pop(ident, None)

    async def receive(self):
        try:
            async for raw in self.socket:
                message = json.loads(raw)
                future = self.pending.get(message.get("id"))
                if hook := self.result_hooks.pop(message.get("id"), None):
                    hook(message.get("result", {}), future is None or future.done())
                if future and not future.done():
                    if "error" in message:
                        future.set_exception(CDPError("Chrome rejected the CDP command"))
                    else:
                        future.set_result(message.get("result", {}))
                elif "method" in message:
                    for listener in list(self.listeners):
                        listener(message)
        except (OSError, ValueError, WebSocketException):
            pass
        finally:
            self.socket = None
            self.result_hooks.clear()
            for future in list(self.pending.values()):
                if not future.done():
                    future.set_exception(CDPError("Chrome disconnected"))
            if not self.closed:
                self.report("refused", "Chrome disconnected; share again to retry")

    async def disconnect(self):
        socket, self.socket = self.socket, None
        if socket:
            await socket.close()
        if self.reader and self.reader is not asyncio.current_task():
            self.reader.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self.reader
        self.reader = None

    async def close(self):
        self.closed = True
        await self.disconnect()
