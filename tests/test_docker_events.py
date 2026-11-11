"""Docker notifications drive refreshes, including across HTTP chunk boundaries."""

import asyncio
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from partyline.docker_events import consume, run


class DockerEventsTest(unittest.IsolatedAsyncioTestCase):
    async def test_chunked_events_refresh_and_push(self):
        reader = asyncio.StreamReader()
        parts = [b'{"Type":"container","Action":"st', b'art"}\n',
                 b'{"Type":"network","Action":"start"}\n',
                 b'{"Type":"container","Action":"oom"}\n']
        reader.feed_data(b"HTTP/1.1 200 OK\r\nTransfer-Encoding: chunked\r\n\r\n"
                         + b"".join(f"{len(part):x}\r\n".encode() + part + b"\r\n" for part in parts)
                         + b"0\r\n\r\n")
        reader.feed_eof()
        writer = Mock()
        writer.drain = AsyncMock()
        runtime = SimpleNamespace(sockets={"line": [object()]})
        inventory = SimpleNamespace(sample=AsyncMock())
        with patch("partyline.docker_events.open_upstream", new=AsyncMock(return_value=(reader, writer))), \
                patch("partyline.browser_snapshots.push_resources", new_callable=AsyncMock) as push:
            await consume(runtime, inventory)
        self.assertEqual(inventory.sample.await_count, 3)  # startup plus two relevant events
        self.assertEqual(push.await_count, 2)
        writer.close.assert_called_once()

    async def test_rejected_stream_is_closed(self):
        reader = asyncio.StreamReader()
        reader.feed_data(b"HTTP/1.1 403 Forbidden\r\n\r\n")
        writer = Mock()
        writer.drain = AsyncMock()
        with patch("partyline.docker_events.open_upstream", new=AsyncMock(return_value=(reader, writer))):
            with self.assertRaises(OSError):
                await consume(SimpleNamespace(), SimpleNamespace())
        writer.close.assert_called_once()

    async def test_stream_waits_without_a_timer_and_closes(self):
        class Signal:
            def __init__(self):
                self.event = asyncio.Event()

            async def wait(self):
                await self.event.wait()
                self.event.clear()

            def __enter__(self):
                return self

            def __exit__(self, *args):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, *args):
                pass

        db_signal, file_signal = Signal(), Signal()
        granted = [True]
        started, stopped = asyncio.Event(), asyncio.Event()

        async def stream(*args):
            started.set()
            try:
                await asyncio.Event().wait()
            finally:
                stopped.set()

        async def in_thread(fn, *args):
            return fn(*args)

        runtime = SimpleNamespace(db=SimpleNamespace(events=SimpleNamespace(
            subscribe=lambda *args: db_signal)))
        inventory = SimpleNamespace(watching=False)
        loop = asyncio.get_running_loop()
        with patch("partyline.docker_events.FileEvents", return_value=file_signal), \
                patch("partyline.docker_events.docker_relay.any_grant", side_effect=lambda db: granted[0]), \
                patch("partyline.docker_events.consume", side_effect=stream), \
                patch("partyline.docker_events.asyncio.to_thread", side_effect=in_thread), \
                patch.object(loop, "call_later", side_effect=AssertionError("timer created")):
            task = asyncio.create_task(run(runtime, inventory))
            for _ in range(20):
                tick = loop.create_future()
                loop.call_soon(tick.set_result, None)
                await tick
                if started.is_set() or task.done():
                    break
            if task.done():
                task.result()
            self.assertTrue(started.is_set())
            granted[0] = False
            db_signal.event.set()
            for _ in range(20):
                tick = loop.create_future()
                loop.call_soon(tick.set_result, None)
                await tick
                if stopped.is_set() or task.done():
                    break
            if task.done():
                task.result()
            self.assertTrue(stopped.is_set())
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task
            self.assertTrue(stopped.is_set())
