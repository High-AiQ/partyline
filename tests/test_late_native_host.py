"""A helper that is already running accepts a native host that connects later (real IPC, no polling)."""
import asyncio
import contextlib
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from partyline.file_events import file_events
from partyline_helper import chrome_operations, native_host, native_shutdown
from partyline_helper.extension_transport import ExtensionTransport
from partyline_helper.native_codec import Decoder, frame, packets
from tests.cdp_fakes import Fixture


class Extension:
    """Chrome's end of one host's stdio: it answers every command the host forwards to it."""
    def __init__(self):
        read, self.write_fd = os.pipe()
        self.stdin = os.fdopen(read, "rb")
        self.buffer, self.decoder, self.seen, self.hellos = bytearray(), Decoder(), [], []
        self.suspended, self.changed, self.messages = asyncio.Event(), asyncio.Event(), []

    def write(self, raw):
        self.buffer += raw

    def flush(self):
        while len(self.buffer) >= 4:
            size = int.from_bytes(self.buffer[:4], "little")
            if len(self.buffer) < 4 + size:
                return
            message = self.decoder.accept(json.loads(bytes(self.buffer[4:4 + size])))
            del self.buffer[:4 + size]
            if message is None:
                continue
            self.seen.append(message["method"])
            self.messages.append(message)
            self.changed.set()
            if message["method"] == "Partyline.hello":
                self.hellos.append(message)
            if message["method"] == "Partyline.suspend":
                self.suspended.set()
            if "id" in message:
                for part in packets({"id": message["id"], "result": {"product": "extension"}}):
                    os.write(self.write_fd, frame(part))

    async def until(self, predicate):
        while not predicate():
            self.changed.clear()
            await self.changed.wait()

    def close(self):  # Chrome closes the native port: the host's stdin reaches end of file
        with contextlib.suppress(OSError):
            os.close(self.write_fd)


class LateHostTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.root = tempfile.TemporaryDirectory()
        self.addCleanup(self.root.cleanup)
        config = Path(self.root.name) / "helper.json"
        for target in ("partyline_helper.native_host.config_path", "partyline_helper.instance.config_path"):
            patcher = patch(target, return_value=config)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.f = Fixture()
        self.addAsyncCleanup(self.f.close)
        self.f.chrome.auto_transport = True
        self.connected, self.armed = asyncio.Event(), asyncio.Event()
        self.f.session.status.listeners.append(self.on_status)
        self.hosts = []

    def on_status(self, _state):
        if self.f.session.status.chrome == "Chrome: extension connected":
            self.connected.set()

    @contextlib.asynccontextmanager
    async def events(self, path):
        async with file_events(path) as watcher:
            self.armed.set()
            yield watcher

    async def start_host(self):
        extension = Extension()
        task = asyncio.create_task(native_host.run(extension.stdin, extension))
        self.hosts.append((extension, task))
        return extension, task

    async def finish(self, extension, task):
        extension.close()
        await asyncio.wait_for(task, 5)  # the host must end by itself once Chrome closes its port
        extension.stdin.close()

    async def test_running_helper_accepts_a_host_started_afterwards_and_again_after_a_pause(self):
        watch = asyncio.create_task(chrome_operations.watch_extension(self.f.chrome, self.events))
        self.addAsyncCleanup(lambda: asyncio.gather(watch, return_exceptions=True))
        await self.armed.wait()
        self.assertNotIsInstance(self.f.chrome.browser, ExtensionTransport)  # no host yet
        extension, host = await self.start_host()
        await self.connected.wait()
        self.assertIsInstance(self.f.chrome.browser, ExtensionTransport)
        self.assertEqual([h["helper_connected"] for h in extension.hellos], [False, True])
        self.assertEqual(extension.hellos[1]["helper_version"], native_host.__version__)
        # `suspend-chrome`: the installer pauses the host, Chrome closes the port, the host exits.
        endpoint = native_host.discover()
        suspending = asyncio.create_task(native_shutdown.suspend(endpoint))
        await extension.suspended.wait()
        await self.finish(extension, host)
        await asyncio.wait_for(suspending, 5)
        suspend = next(m for m in extension.messages if m["method"] == "Partyline.suspend")
        self.assertIs(suspend["release"], True)  # only an installer asks Chrome to close the port
        self.assertIsNone(native_host.discover())
        self.assertFalse(native_host.endpoint_path().exists())
        # The pause ends: the extension reconnects, and the same running helper takes the new host.
        self.connected.clear()
        again, host = await self.start_host()
        await self.connected.wait()
        self.assertEqual([h["helper_connected"] for h in again.hellos], [False, True])
        self.assertIn("Browser.getVersion", again.seen)
        await self.finish(again, host)  # also ends while the helper is still attached

    async def test_host_outlives_a_helper_that_quits_and_greets_the_next_one_without_chrome(self):
        extension, host = await self.start_host()
        await extension.until(lambda: len(extension.hellos) == 1)  # the endpoint file is written first
        first = ExtensionTransport()
        self.assertTrue(await first.ensure())
        await extension.until(lambda: len(extension.hellos) == 2)
        await first.close()  # the helper quits: Chrome's port is untouched
        await extension.until(lambda: "Partyline.reset" in extension.seen)
        self.assertFalse(host.done())
        self.assertIsNotNone(native_host.discover())
        second = ExtensionTransport()  # the restarted helper finds the same host by its endpoint file
        self.addAsyncCleanup(second.close)
        self.assertTrue(await second.ensure())
        await extension.until(lambda: len(extension.hellos) == 3)
        self.assertEqual([h["helper_connected"] for h in extension.hellos], [False, True, True])
        self.assertEqual((await second.call("Browser.getVersion"))["product"], "extension")
        await second.close()
        await self.finish(extension, host)

    async def test_newest_authenticated_helper_replaces_a_stale_one(self):
        from partyline_helper.native_socket import NativeSocket
        output = Extension()
        bridge = native_host.Bridge(output, "t" * 64, browser_pid=1)
        server = await asyncio.start_server(bridge.accept, "127.0.0.1", 0)
        port = server.sockets[0].getsockname()[1]
        self.addAsyncCleanup(server.wait_closed)
        self.addCleanup(server.close)

        async def helper():
            reader, writer = await asyncio.open_connection("127.0.0.1", port)
            socket = NativeSocket(reader, writer)
            socket.send_nowait({"token": "t" * 64})
            await writer.drain()
            return socket
        first = await helper()
        while len(output.hellos) < 1:
            await asyncio.sleep(0)  # yield to the accept handler: no timer involved
        second = await helper()  # the first helper is half open, never closed by its side
        while len(output.hellos) < 2:
            await asyncio.sleep(0)
        self.assertEqual([h["helper_connected"] for h in output.hellos], [True, True])
        self.assertIsNone(await anext(first, None))  # the stale helper was dropped
        self.assertNotIn("Partyline.reset", output.seen)  # the newer helper still owns the extension
        await second.close()
        await first.close()
        while "Partyline.reset" not in output.seen:
            await asyncio.sleep(0)
        output.close()
        output.stdin.close()
