"""The MCP tool-list watcher is a pushed stream: no request waits out a timer."""

import asyncio
import io
import queue
import socket
import tempfile
import threading
import unittest
import unittest.mock
from unittest.mock import patch

import uvicorn
from fastapi import FastAPI

from partyline import auth_store, auth_tokens
from partyline.auth_guard import install_auth_guard
from partyline.bind import StreamClosingServer
from partyline.capability_version_routes import router_for
from partyline.capability_versions import CapabilityVersions
from partyline.db import Db
from partyline.mcp.client import ApiError, PartylineClient
from partyline.mcp.server import MCPServer
from partyline.runtime import ChatRuntime

from tests.test_mcp import FakeClient


class CapabilityVersionsTests(unittest.IsolatedAsyncioTestCase):
    async def test_a_waiter_is_woken_by_a_change_and_never_by_a_clock(self):
        versions = CapabilityVersions()
        since = versions.current("att-1")
        waiting = asyncio.create_task(versions.wait_for_change("att-1", since))
        await asyncio.sleep(0)
        self.assertFalse(waiting.done())
        versions.bump_all()
        self.assertNotEqual(await waiting, since)
        self.assertEqual(versions._waiters, {})

    async def test_a_stream_gives_the_current_revision_then_each_change_and_ends_on_close(self):
        versions = CapabilityVersions()
        stream = versions.changes("att-1")
        first = await anext(stream)
        self.assertEqual(first, versions.current("att-1"))
        pending = asyncio.create_task(anext(stream))
        await asyncio.sleep(0)
        versions.bump_all()
        second = await pending
        self.assertNotEqual(second, first)
        pending = asyncio.create_task(anext(stream))
        await asyncio.sleep(0)
        versions.close()
        with self.assertRaises(StopAsyncIteration):
            await pending
        self.assertIsNone(await versions.wait_for_change("att-1", None))

    async def test_a_cancelled_waiter_leaves_nothing_behind(self):
        versions = CapabilityVersions()
        waiting = asyncio.create_task(versions.wait_for_change("att-1", versions.current("att-1")))
        await asyncio.sleep(0)
        waiting.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await waiting
        self.assertEqual(versions._waiters, {})


class StreamFollowerTests(unittest.TestCase):
    """The bridge's side: apply pushed revisions, reconnect only after a break."""

    class Stop:
        def __init__(self, waits):
            self.waits, self.delays = waits, []

        def is_set(self):
            return False

        def wait(self, delay):
            self.delays.append(delay)
            return len(self.delays) >= self.waits

    def server(self, client):
        client.state.update(dynamic_screen_tools=True, screen_read=False,
                            screen_control=False, screen_windows=False)
        output = io.StringIO()
        server = MCPServer(client, output)
        server._state_signature = server._signature(client.state)
        server._capability_version = "epoch:1"
        server._watch_ready.set()
        return server, output

    def test_a_pushed_revision_refreshes_the_tool_list_once(self):
        client = FakeClient(actions=("read", "write"))
        streams = []

        def capability_stream():
            streams.append(len(streams))
            if len(streams) == 1:
                raise ConnectionRefusedError("temporary outage")
            yield "epoch:1"  # what the listing already recorded: nothing to fetch
            client.state.update(screen_read=True, capability_version="epoch:2")
            yield "epoch:2"
            yield "epoch:2"

        client.capability_stream = capability_stream
        server, output = self.server(client)
        server._poll_stop = self.Stop(waits=2)
        with self.assertLogs("partyline.mcp.server", "WARNING"):
            server._poll_capabilities()
        self.assertEqual(len(streams), 2)
        self.assertEqual(client.requests.count(("CAP", None)), 1)
        self.assertEqual(output.getvalue().count("notifications/tools/list_changed"), 1)
        # A broken stream backs off; one that served revisions reconnects at the floor.
        self.assertEqual(server._poll_stop.delays, [1.0, 0.5])

    def test_backoff_doubles_to_a_cap_while_the_server_is_away(self):
        client = FakeClient()

        def capability_stream():
            raise ConnectionRefusedError("restarting")
            yield  # pragma: no cover - makes this a generator

        client.capability_stream = capability_stream
        server, _ = self.server(client)
        server._poll_stop = self.Stop(waits=6)
        with self.assertLogs("partyline.mcp.server", "WARNING"):
            server._poll_capabilities()
        self.assertEqual(server._poll_stop.delays, [1.0, 2.0, 4.0, 8.0, 10, 10])

    def test_a_revoked_credential_stops_the_watcher_for_good(self):
        client = FakeClient()
        streams = []

        def capability_stream():
            streams.append(1)
            yield "epoch:2"

        def refused(conv_id=None):
            raise ApiError("Partyline HTTP 401")

        client.capability_stream, client.capabilities = capability_stream, refused
        server, _ = self.server(client)
        server._poll_stop = self.Stop(waits=99)
        server._poll_capabilities()
        self.assertTrue(server._revoked)
        self.assertEqual((len(streams), server._poll_stop.delays), (1, []))


class StreamParsingTests(unittest.TestCase):
    def test_a_line_that_is_not_a_revision_breaks_the_stream_rather_than_being_guessed_at(self):
        class Response:
            status = 200

            def __init__(self, lines):
                self.lines = iter(lines)

            def readline(self, _limit):
                return next(self.lines, b"")

        class Connection:
            def __init__(self, lines):
                self.sock, self.response, self.closed = unittest.mock.Mock(), Response(lines), False

            def connect(self):
                pass

            def request(self, *args, **kwargs):
                pass

            def getresponse(self):
                return self.response

            def close(self):
                self.closed = True

        for garbage in (b"not json\n", b"[1]\n", b'{"version": 7}\n'):
            client = PartylineClient.__new__(PartylineClient)
            client.connection = {"api": "http://127.0.0.1:1", "token": "secret"}
            client._active_lock, client._active_connections = threading.Lock(), set()
            client._interrupted = False
            connection = Connection([b'{"version": "epoch:1"}\n', garbage])
            client._origin = lambda connection=connection: connection
            stream = client.capability_stream()
            self.assertEqual(next(stream), "epoch:1")
            with self.subTest(garbage=garbage), self.assertRaisesRegex(ApiError, "invalid capability"):
                next(stream)
            self.assertTrue(connection.closed)
            self.assertEqual(client._active_connections, set())


class CapabilityStreamRoundtripTests(unittest.TestCase):
    """The real bridge client against the real route, server and shutdown path."""

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.db = Db(f"{self.directory.name}/stream.db")
        self.runtime = ChatRuntime(self.db)
        self.versions = self.runtime.capability_versions
        app = FastAPI()
        install_auth_guard(app, self.db)
        app.include_router(router_for(self.runtime))
        self.db.create_conversation("line", "Line")
        self.db.add_attachment("att-a", "line", "worker", "fake", ["fake"],
                               self.directory.name, "owner")
        self.db.set_attachment_status("att-a", "running", "owner")
        self.token = auth_store.ensure_api_token(self.db, "att-a")
        listener = socket.socket()
        listener.bind(("127.0.0.1", 0))
        listener.listen()
        self.port = listener.getsockname()[1]
        self.server = StreamClosingServer(uvicorn.Config(
            app, host="127.0.0.1", port=self.port, log_level="error"), self.versions.close)
        self.stopping = threading.Event()

        async def main_loop():
            await asyncio.to_thread(self.stopping.wait)

        self.server.main_loop = main_loop
        real_shutdown, real_sleep = self.server.shutdown, asyncio.sleep

        async def shutdown(sockets=None):
            # uvicorn's own drain loop sleeps 100 ms a pass; here each pass only yields.
            with patch("uvicorn.server.asyncio.sleep", new=lambda _seconds: real_sleep(0)):
                await real_shutdown(sockets=sockets)

        self.server.shutdown = shutdown
        started, real_startup = threading.Event(), self.server.startup

        async def startup(sockets=None):
            await real_startup(sockets=sockets)
            started.set()

        self.server.startup = startup
        self.thread = threading.Thread(
            target=self.server.run, kwargs={"sockets": [listener]}, daemon=True)
        self.thread.start()
        self.assertTrue(started.wait(5), "stream server did not start")

    def stop(self):
        self.server.should_exit = True
        self.stopping.set()
        self.thread.join(timeout=5)
        self.assertFalse(self.thread.is_alive(), "an open stream held the shutdown")

    def tearDown(self):
        self.stop()
        self.db.close()
        self.directory.cleanup()

    def client(self, token):
        client = PartylineClient.__new__(PartylineClient)
        client.connection = {"api": f"http://127.0.0.1:{self.port}", "token": token,
                             "conversation_id": "line"}
        client._active_lock = threading.Lock()
        client._active_connections = set()
        client._interrupted = False
        return client

    def follow(self, client):
        """Read the stream on a thread; a missing line fails the test instead of hanging it."""
        lines = queue.Queue()

        def read():
            try:
                for version in client.capability_stream():
                    lines.put(version)
                lines.put(StopIteration)
            except Exception as exc:
                lines.put(exc)

        threading.Thread(target=read, daemon=True).start()
        return lambda: lines.get(timeout=5)

    def test_revisions_are_pushed_and_a_stopping_server_ends_the_stream(self):
        following = self.follow(self.client(self.token))
        first = following()
        self.assertEqual(first, self.versions.current("att-a"))
        self.versions.bump_all()
        second = following()
        self.assertEqual(second, self.versions.current("att-a"))
        self.assertNotEqual(second, first)
        # A row the tool list depends on changes: the database trace pushes it.
        self.db.set_attachment_status("att-a", "detached", "owner")
        self.assertNotEqual(following(), second)
        self.stop()  # the stream is still open; shutdown must end it, not wait on it
        while (line := following()) is not StopIteration:
            self.assertIsInstance(line, str)  # a revision pushed before the stop

    def test_the_bridge_can_abandon_an_idle_stream(self):
        client = self.client(self.token)
        following = self.follow(client)
        following()
        client.interrupt()
        self.assertIsNot(following(), None)
        with self.assertRaisesRegex(OSError, "shutting down"):
            next(client.capability_stream())

    def test_a_person_has_no_capability_stream(self):
        user = auth_store.create_user(
            self.db, "person@example.com", "person", auth_tokens.hash_password("test-password"))
        token = auth_tokens.create_access_token(auth_tokens.signing_secret(self.db), user["id"])
        outcome = self.follow(self.client(token))()
        self.assertIsInstance(outcome, ApiError)
        self.assertIn("403", str(outcome))


if __name__ == "__main__":
    unittest.main()
