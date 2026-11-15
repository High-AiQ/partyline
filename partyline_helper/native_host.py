"""Chrome-started stdio bridge; retains the native port across helper restarts."""
import asyncio
import contextlib
import json
import os
import secrets
import sys

from partyline.process_events import wait_pid
from .chrome_identity import ORIGIN
from .config import config_path, save_config
from .instance import InstanceLock
from .native_codec import Decoder, frame, length, packets, read_frame
from .native_socket import NativeSocket


def endpoint_path():
    return config_path().with_name("chrome-native.json")


def running_pid():
    """Read-only liveness check: discovery must never acquire Chrome's startup lock."""
    try:
        pid = int(endpoint_path().with_name("chrome-native.pid").read_text())
        if 0 < pid <= 0x7fffffff and not wait_pid(pid, timeout=0):
            return pid
    except (OSError, ValueError):
        pass
    return None


def discover():
    try:
        value = json.loads(endpoint_path().read_text())
        if (type(value["port"]) is int and 0 < value["port"] < 65536
                and isinstance(value["token"], str) and len(value["token"]) == 64
                and type(value["pid"]) is int and value["pid"] == running_pid()):
            return value
    except (OSError, ValueError, KeyError, TypeError):
        pass
    return None


class Bridge:
    def __init__(self, output, token, browser_pid=None):
        self.output, self.token, self.client = output, token, None
        if browser_pid is None and sys.platform == "win32":
            from .native_windows import chrome_parent
            browser_pid = chrome_parent()
        self.browser_pid = os.getppid() if browser_pid is None else browser_pid
        self.serial, self.pending = 0, {}

    def native(self, message):
        for packet in packets(message):
            self.output.write(frame(packet))
        self.output.flush()

    async def accept(self, reader, writer):
        socket = NativeSocket(reader, writer)
        owned = False
        try:
            async with asyncio.timeout(3):
                size = length(await reader.readexactly(4))
                if size > 1024:
                    return  # authenticate one small frame before accepting chunked CDP messages
                auth = json.loads(await reader.readexactly(size))
            if auth != {"token": self.token} or self.client:
                return
            owned = True
            self.client = socket
            async for raw in socket:
                message = json.loads(raw)
                if "id" in message:
                    if len(self.pending) >= 256:
                        raise ValueError("Too many outstanding native commands")
                    self.serial += 1
                    self.pending[self.serial] = (socket, message["id"])
                    message["id"] = self.serial
                self.native(message)
        except (EOFError, OSError, ValueError, TimeoutError, StopAsyncIteration,
                asyncio.IncompleteReadError):
            pass
        finally:
            if owned:
                self.client = None
                self.pending = {i: pair for i, pair in self.pending.items() if pair[0] is not socket}
                self.native({"method": "Partyline.reset"})
            with contextlib.suppress(OSError):
                await socket.close()

    async def receive(self, stream):
        decoder = Decoder()
        while True:
            try:
                packet = await asyncio.to_thread(read_frame, stream)
                message = decoder.accept(packet)
                if message is not None and self.client:
                    if "id" in message:
                        owner = self.pending.pop(message["id"], None)
                        if owner is None or owner[0] is not self.client:
                            continue  # a previous helper's late result cannot satisfy this helper's call
                        message["id"] = owner[1]
                    if isinstance(message.get("result"), dict):
                        message["result"]["_partyline_browser_pid"] = self.browser_pid
                    client = self.client
                    try:
                        await client.send(json.dumps(message))
                    except OSError:
                        await client.close()  # helper exit must not terminate Chrome's native port
            except (EOFError, OSError, ValueError, KeyError, TypeError):
                return


async def run(stream, output):
    lock = InstanceLock("chrome-native")
    if not lock.acquire():
        return
    token = secrets.token_hex(32)
    bridge = Bridge(output, token)
    server = None
    try:
        server = await asyncio.start_server(bridge.accept, "127.0.0.1", 0)
        save_config({"port": server.sockets[0].getsockname()[1], "token": token,
                     "pid": os.getpid()}, endpoint_path())
        bridge.native({"method": "Partyline.hello"})
        await bridge.receive(stream)
    finally:
        if server:
            server.close()
            await server.wait_closed()
        if bridge.client:
            await bridge.client.close()
        endpoint_path().unlink(missing_ok=True)
        lock.release()


def main(argv=None, stream=None, output=None):
    args = sys.argv[1:] if argv is None else argv
    if not args or args[0] != ORIGIN:
        raise ValueError("Native host only accepts the Partyline extension origin")
    if sys.platform == "win32":
        from .native_windows import binary_stdio
        binary_stdio()
    asyncio.run(run(stream or sys.stdin.buffer, output or sys.stdout.buffer))


if __name__ == "__main__":
    main()
