import asyncio
import os
import tempfile
import unittest
from types import SimpleNamespace

from fastapi import WebSocketDisconnect

from partyline.adapters.base import Adapter
from partyline.auth_store import ensure_api_token
from partyline.db import Db
from partyline.terminal_stream import terminal_endpoint
from partyline.terminal_viewers import VIEWER_QUEUE_LIMIT, TerminalViewerRegistry


async def eventually(predicate, what):
    for _ in range(100):
        if predicate():
            return
        await asyncio.sleep(0.01)
    raise AssertionError(f"timed out waiting for {what}")


class FakeWebSocket:
    def __init__(self, token: str = ""):
        self.accepted = asyncio.Event()
        self.incoming: asyncio.Queue[str | None] = asyncio.Queue()
        self.sent: list[tuple[str, str | bytes]] = []
        self.closed = None
        self.headers: dict[str, str] = {}
        self.query_params = {"token": token} if token else {}

    async def accept(self):
        self.accepted.set()

    async def send_text(self, data):
        self.sent.append(("text", data))

    async def send_bytes(self, data):
        self.sent.append(("bytes", data))

    async def receive_text(self):
        data = await self.incoming.get()
        if data is None:
            raise WebSocketDisconnect()
        return data

    async def close(self, code, reason):
        self.closed = (code, reason)


class FakeTerminalAdapter:
    def __init__(self):
        self.registry = TerminalViewerRegistry(lambda: "snapshot")
        self.writes = []
        self.detached = []

    def attach_terminal_viewer(self):
        return self.registry.attach()

    def detach_terminal_viewer(self, viewer):
        self.detached.append(viewer)
        self.registry.detach(viewer)

    def terminal_dimensions(self):
        return 120, 40

    def write_terminal(self, data):
        self.writes.append(data)


class TerminalViewerRegistryTest(unittest.TestCase):
    def test_fans_out_and_closes_a_slow_viewer_on_overflow(self):
        registry = TerminalViewerRegistry(lambda: "screen")
        first = registry.attach()
        second = registry.attach()

        registry.publish(b"same")
        self.assertEqual(first.queue.get_nowait(), b"same")
        self.assertEqual(second.queue.get_nowait(), b"same")

        for number in range(VIEWER_QUEUE_LIMIT):
            first.queue.put_nowait(str(number).encode())
        self.assertEqual(first.queue.qsize(), VIEWER_QUEUE_LIMIT)
        registry.publish(b"overflow")
        self.assertIsNone(first.queue.get_nowait())
        self.assertEqual(second.queue.get_nowait(), b"overflow")

    def test_late_viewer_gets_a_coherent_snapshot(self):
        registry = TerminalViewerRegistry(lambda: "screen state")
        viewer = registry.attach()

        self.assertEqual(viewer.snapshot, "screen state")
        self.assertEqual(viewer.queue.qsize(), 0)

    def test_attach_after_close_is_woken_immediately(self):
        registry = TerminalViewerRegistry(lambda: "screen")
        registry.close()

        viewer = registry.attach()

        self.assertIsNone(viewer.queue.get_nowait())

    def test_close_wakes_every_viewer_with_a_sentinel(self):
        registry = TerminalViewerRegistry(lambda: "screen")
        first = registry.attach()
        second = registry.attach()

        registry.close()

        self.assertIsNone(first.queue.get_nowait())
        self.assertIsNone(second.queue.get_nowait())
        self.assertEqual(registry._queues, set())


class TerminalDrainTest(unittest.IsolatedAsyncioTestCase):
    async def test_drain_fans_out_pipe_bytes_without_a_second_reader(self):
        read_fd, write_fd = os.pipe()
        adapter = Adapter(
            {"id": "a", "name": "agent", "command": ["cat"], "cwd": "/tmp"},
            lambda *_: None,
            lambda *_: None,
        )
        adapter.master = read_fd
        first = adapter.attach_terminal_viewer()
        second = adapter.attach_terminal_viewer()
        task = asyncio.create_task(adapter._drain())
        self.addAsyncCleanup(task.cancel)
        self.addCleanup(os.close, write_fd)
        self.addCleanup(os.close, read_fd)

        os.write(write_fd, b"hello")
        await eventually(lambda: first.queue.qsize() == 1, "first viewer data")

        self.assertEqual(first.queue.get_nowait(), b"hello")
        self.assertEqual(second.queue.get_nowait(), b"hello")
        self.assertIn("hello", adapter.screen_text())

        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        self.assertIsNone(first.queue.get_nowait())
        self.assertIsNone(second.queue.get_nowait())


class TerminalEndpointTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.db = Db(f"{self.directory.name}/terminal.db")
        self.addCleanup(self.db.close)
        self.db.create_conversation("line", "Line")
        self.db.add_attachment("att-1", "line", "opus", "fake", ["fake"], "/tmp")
        self.token = ensure_api_token(self.db, "att-1")

    async def test_endpoint_orders_geometry_snapshot_then_live_bytes_and_writes_raw_input(self):
        adapter = FakeTerminalAdapter()
        ws = FakeWebSocket(token=self.token)
        runtime = SimpleNamespace(live={"att-1": adapter}, db=self.db)
        endpoint = terminal_endpoint(runtime)
        task = asyncio.create_task(endpoint(ws, "att-1"))

        await ws.accepted.wait()
        self.assertEqual(ws.sent[:2], [("text", '{"cols":120,"rows":40}'), ("text", "snapshot")])

        adapter.registry.publish(b"live")
        await eventually(lambda: ("bytes", b"live") in ws.sent, "live terminal bytes")
        ws.incoming.put_nowait("\x03\x1b[A")
        await eventually(lambda: adapter.writes == [b"\x03\x1b[A"], "raw terminal input")

        ws.incoming.put_nowait(None)
        await task
        self.assertEqual(len(adapter.detached), 1)

    async def test_missing_attachment_is_closed(self):
        ws = FakeWebSocket(token=self.token)
        await terminal_endpoint(
            SimpleNamespace(live={"other": object()}, db=self.db))(ws, "missing")

        self.assertTrue(ws.accepted.is_set())
        self.assertEqual(ws.closed, (4404, "attachment is not live"))

    async def test_unauthenticated_socket_is_closed_4401(self):
        # A terminal socket can type into a real pty; without a credential it
        # must close before the adapter is even looked up.
        ws = FakeWebSocket()
        await terminal_endpoint(
            SimpleNamespace(live={}, db=self.db))(ws, "att-1")

        self.assertEqual(ws.closed, (4401, "authentication required"))


if __name__ == "__main__":
    unittest.main()
