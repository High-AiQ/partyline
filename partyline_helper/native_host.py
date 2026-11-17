"""Chrome-started stdio bridge; retains the native port across helper restarts."""
import asyncio
import contextlib
import json
import os
import secrets
import sys

from partyline.process_events import process_exited, wait_pid
from .chrome_identity import ORIGIN
from .config import config_path, save_config
from .update_preferences import enabled
from . import __version__
from .instance import InstanceLock
from .native_codec import Decoder, frame, length, packets, read_frame
from .native_socket import NativeSocket


def hello(helper=False):
    """The extension's greeting. Only a hello sent when a helper attaches carries `helper_connected`."""
    try:
        version = json.loads((config_path().parent / "chrome-extension" / "manifest.json").read_text())[
            "version"]
    except (OSError, ValueError, KeyError):
        version = None
    message = {"method": "Partyline.hello", "extension_version": version, "auto_update": enabled(),
               "helper_connected": helper}
    if helper:
        message["helper_version"] = __version__
    return message


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


def seen():
    """A native host has run for this user before (Chrome started one for the loaded extension).

    The host's own lock file stays after it exits, so a helper that starts while the extension is between
    hosts (an update, a restart, a reload) still knows the extension is there and waits for it."""
    return endpoint_path().with_name("chrome-native.lock").exists()


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
            if auth != {"token": self.token}:
                return
            if self.client:
                # The newest authenticated helper wins: a helper that was killed or lost its network
                # may leave a half-open socket here, and Chrome must not stay unreachable behind it.
                await self.drop_client()
            owned = True
            self.client = socket
            self.native(hello(helper=True))
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
                self.pending = {i: pair for i, pair in self.pending.items() if pair[0] is not socket}
                if self.client is socket:  # a newer helper replaced this one: it owns the extension now
                    self.client = None
                    self.native({"method": "Partyline.reset"})
            with contextlib.suppress(OSError):
                await socket.close()

    async def drop_client(self):
        client, self.client = self.client, None
        self.pending = {}
        with contextlib.suppress(OSError):
            await client.close()

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


async def serve_until_chrome_exits(bridge, stream, parent=process_exited):
    """Chrome closing the port ends `receive`; Chrome itself going away (killed, or its session torn down)
    must end the host too, or a stale host keeps the lock and every later host exits unseen.

    no-poll (b): one process-exit wait on Chrome's pid, never a liveness scan."""
    receiving = asyncio.ensure_future(bridge.receive(stream))
    watching = asyncio.ensure_future(parent(bridge.browser_pid)) if bridge.browser_pid else None
    try:
        pending = {t for t in (receiving, watching) if t}
        while receiving in pending:
            done, pending = await asyncio.wait(pending, return_when=asyncio.FIRST_COMPLETED)
            if watching in done and not watching.cancelled() and watching.exception():
                # Fail open: a watch that cannot open Chrome's process must never end a healthy host.
                print(f"Chrome parent watch stopped ({type(watching.exception()).__name__}); "
                      "the host ends with Chrome's port", file=sys.stderr, flush=True)
                watching = None
            elif watching in done:
                break  # Chrome exited
    finally:
        for task in (receiving, watching):
            if task and not task.done():
                task.cancel()
        await asyncio.gather(*(t for t in (receiving, watching) if t), return_exceptions=True)
    if receiving.done() and not receiving.cancelled() and receiving.exception():
        raise receiving.exception()


async def run(stream, output, wait=wait_pid, parent=process_exited):
    lock = InstanceLock("chrome-native")
    if not lock.acquire():
        # no-poll (b): extension reload may overlap the previous host's exit; wait once on its PID.
        previous = running_pid()
        if (not previous or previous == os.getpid() or
                not await asyncio.to_thread(wait, previous, timeout=5) or not lock.acquire()):
            # Say why before exiting: Chrome only reports "Native host has exited", and the extension retries
            # on its schedule while the older host (a stale one never leaves) is the real reason.
            with contextlib.suppress(OSError, ValueError):
                output.write(frame({"method": "Partyline.busy", "pid": previous}))
                output.flush()
            return
    token = secrets.token_hex(32)
    bridge = Bridge(output, token)
    server = None
    try:
        server = await asyncio.start_server(bridge.accept, "127.0.0.1", 0)
        save_config({"port": server.sockets[0].getsockname()[1], "token": token,
                     "pid": os.getpid(), "version": __version__}, endpoint_path())
        bridge.native(hello())
        await serve_until_chrome_exits(bridge, stream, parent)
    finally:
        # Close the helper first: wait_closed() (Python 3.12+) waits for every open connection, so a
        # host whose Chrome side ended would otherwise keep the lock and refuse each later host.
        if server:
            server.close()
        if bridge.client:
            await bridge.drop_client()
        if server:
            if close_clients := getattr(server, "close_clients", None):
                close_clients()
            await server.wait_closed()
        endpoint_path().unlink(missing_ok=True)
        lock.release()


def main(argv=None, stream=None, output=None):
    args = sys.argv[1:] if argv is None else argv
    if not args or args[0] != ORIGIN:
        raise ValueError("Native host only accepts the Partyline extension origin")
    if sys.platform == "win32":
        from .native_windows import binary_stdio
        binary_stdio()
    if stream is not None:
        asyncio.run(run(stream, output or sys.stdout.buffer))
        return
    # A read of Chrome's pipe cannot be cancelled: when Chrome is gone but its pipe is still open,
    # asyncio.run would wait for that read forever and keep the host alive. So the loop ends, then the
    # process does. A crash is written to stderr first (Chrome only says "Native host has exited").
    code = 0
    try:
        asyncio.new_event_loop().run_until_complete(run(sys.stdin.buffer, output or sys.stdout.buffer))
    except BaseException:  # pragma: no cover - the real process
        import traceback
        code = 1
        with contextlib.suppress(OSError, ValueError):
            traceback.print_exc()
    finally:
        with contextlib.suppress(OSError, ValueError):
            sys.stdout.flush()
        os._exit(code)  # pragma: no cover - the real process


if __name__ == "__main__":
    main()
