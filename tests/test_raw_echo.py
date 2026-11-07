"""Raw adapter must not post the terminal's echo of the text we typed in."""

from __future__ import annotations

import asyncio
import os
import select
import time
import unittest
from unittest.mock import AsyncMock

from partyline.adapters.bundled.raw.adapter import RawAdapter


def make(alive=lambda: False) -> RawAdapter:
    adapter = RawAdapter({"name": "raw", "cwd": ".", "runtime_owner": "o"}, AsyncMock(), AsyncMock())
    adapter.alive = alive
    adapter._write_all = AsyncMock()
    adapter.post = AsyncMock()
    adapter.att["credit_delivery_boundary"] = AsyncMock()
    return adapter


async def flush(adapter: RawAdapter) -> None:
    adapter._last_output = time.monotonic() - 5
    adapter.alive = lambda: False
    await adapter._run()


class PtyHarness:
    """Run a real program on a pty and feed its bytes to the adapter."""

    def __init__(self, adapter, argv):
        self.adapter, self.argv = adapter, argv

    async def run(self, payload: str, expected: str, startup: str | None = None, wait: float = 1.0):
        import pty
        pid, fd = pty.fork()
        if pid == 0:
            os.execvp(self.argv[0], self.argv)
        try:
            self.adapter._write_all = AsyncMock(side_effect=lambda b: os.write(fd, b))
            if startup is not None:
                prompt = b""
                end = time.monotonic() + wait
                while startup.encode() not in prompt:
                    remaining = end - time.monotonic()
                    if remaining <= 0:
                        raise AssertionError(f"pty did not show startup prompt {startup!r}")
                    readable, _, _ = await asyncio.to_thread(select.select, [fd], [], [], remaining)
                    if not readable:
                        raise AssertionError(f"pty did not show startup prompt {startup!r}")
                    prompt += os.read(fd, 4096)
                await self.adapter.on_output(prompt)
            self.adapter._buffer.clear()  # drop startup noise (prompt)
            self.adapter._pending = False
            await self.adapter.send_keys(payload)
            end = time.monotonic() + wait
            while expected not in "".join(self.adapter._buffer):
                remaining = end - time.monotonic()
                if remaining <= 0:
                    break
                # Wait for the pty itself rather than a fixed startup delay or
                # a full one-second poll after the expected output has landed.
                readable, _, _ = await asyncio.to_thread(select.select, [fd], [], [], remaining)
                if not readable:
                    break
                try:
                    data = os.read(fd, 4096)
                except OSError:
                    break
                await self.adapter.on_output(data)
            # Close the child's input and drain through EOF. Stopping at the
            # first expected bytes would miss a duplicate in a later chunk.
            os.write(fd, b"\x04")
            while (remaining := end - time.monotonic()) > 0:
                readable, _, _ = await asyncio.to_thread(select.select, [fd], [], [], remaining)
                if not readable:
                    break
                try:
                    data = os.read(fd, 4096)
                except OSError:
                    break
                if not data:
                    break
                await self.adapter.on_output(data)
        finally:
            if os.waitpid(pid, os.WNOHANG) == (0, 0):
                os.kill(pid, 9)
                os.waitpid(pid, 0)
            os.close(fd)
        await flush(self.adapter)


class RawEchoTest(unittest.IsolatedAsyncioTestCase):
    async def test_cat_posts_one_copy(self):
        adapter = make()
        await PtyHarness(adapter, ["cat"]).run("hello", "hello")
        adapter.post.assert_awaited_once_with("raw", "agent", "hello")

    async def test_shell_posts_result_not_command(self):
        adapter = make()
        await PtyHarness(adapter, ["bash", "--norc", "--noprofile", "-i"]).run(
            "echo hi", "hi", startup="$ "
        )
        body = adapter.post.await_args.args[2]
        self.assertIn("hi", body)
        self.assertNotIn("echo hi", body)

    async def test_multiline_digest_not_posted_back(self):
        adapter = make()
        digest = "first line\nsecond line\n(cwd git: abc clean)"
        await PtyHarness(adapter, ["cat"]).run(digest, digest)
        self.assertEqual(adapter.post.await_args.args[2], digest)  # cat's own copy only

    async def test_chunked_echo_is_stripped(self):
        adapter = make()
        await adapter.send_keys("hello world")
        for chunk in (b"$ hel", b"lo wo", b"rld\r", b"\nreal\r\n"):
            await adapter.on_output(chunk)
        await flush(adapter)
        adapter.post.assert_awaited_once_with("raw", "agent", "real")

    async def test_equal_output_after_window_is_posted(self):
        adapter = make()
        await adapter.send_keys("hello")
        adapter._echo_deadline = time.monotonic() - 1
        await adapter.on_output(b"hello\r\n")
        await flush(adapter)
        adapter.post.assert_awaited_once_with("raw", "agent", "hello")

    async def test_equal_output_after_echo_consumed_is_posted(self):
        adapter = make()
        await adapter.send_keys("hello")
        await adapter.on_output(b"hello\r\nhello\r\n")
        await flush(adapter)
        adapter.post.assert_awaited_once_with("raw", "agent", "hello")

    async def test_echo_only_flush_credits_boundary_without_posting(self):
        adapter = make()
        await adapter.send_keys("a\nb")
        await adapter.on_output(b"a\r\nb\r\n")
        await flush(adapter)
        adapter.post.assert_not_awaited()
        adapter.att["credit_delivery_boundary"].assert_awaited_once_with()

    async def test_unterminated_echo_and_prompt_flush(self):
        adapter = make()
        await adapter.send_keys("hi")
        await adapter.on_output(b"$ hi")
        await adapter.on_output(b"")
        await flush(adapter)
        adapter.post.assert_not_awaited()
        adapter = make()
        await adapter.send_keys("hi")
        await adapter.on_output(b"$ ")
        await flush(adapter)
        adapter.post.assert_awaited_once_with("raw", "agent", "$ ")


if __name__ == "__main__":
    unittest.main()
