"""Raw delivery is bounded, credits the cursor, and never posts echo remnants."""

from __future__ import annotations

import os
import pty
import unittest
from unittest.mock import AsyncMock

from partyline.adapters.bundled.raw.adapter import RawAdapter
from partyline.adapters.pty_io import write_all
from tests.test_raw_echo import flush, make


def msgs(count: int, size: int = 300) -> list[dict]:
    return [
        {"id": i, "sender": "x", "sender_type": "agent", "body": f"{i}:" + "m" * size}
        for i in range(count)
    ]


class RawBoundedDeliveryTest(unittest.IsolatedAsyncioTestCase):
    def test_digest_is_capped_and_keeps_the_newest(self):
        adapter = make()
        adapter.att["cwd"] = "/nonexistent"
        digest = adapter.format_digest(msgs(40))
        self.assertLess(len(digest.encode()), 1200)
        self.assertIn("earlier messages omitted", digest.splitlines()[0])
        self.assertIn("39:", digest)
        self.assertNotIn("\n0:", digest)

    def test_small_digest_is_unchanged(self):
        adapter = make()
        adapter.att["cwd"] = "/nonexistent"
        self.assertEqual(adapter.format_digest(msgs(2, 5)), "0:mmmmm\n1:mmmmm")

    async def test_non_reading_child_accepts_the_whole_delivery(self):
        adapter = RawAdapter({"name": "raw", "cwd": "/nonexistent"}, AsyncMock(), AsyncMock())
        pid, fd = pty.fork()
        if pid == 0:
            os.execvp("sleep", ["sleep", "30"])
        try:
            payload = adapter.format_digest(msgs(200)).encode() + b"\r"
            # Unbounded, 200 x 300 bytes would stall at the tty's 4095-byte buffer.
            await write_all(fd, payload)
        finally:
            os.kill(pid, 9)
            os.waitpid(pid, 0)
            os.close(fd)

    async def test_partial_echo_prefix_is_not_posted(self):
        adapter = make()
        await adapter.send_keys("a long digest line that the tty only half echoed")
        await adapter.on_output(b"a long digest line that")
        await flush(adapter)
        adapter.post.assert_not_awaited()
        adapter.att["credit_delivery_boundary"].assert_awaited_once_with()

    async def test_real_output_after_partial_echo_still_posts(self):
        adapter = make()
        await adapter.send_keys("hello there")
        await adapter.on_output(b"hello th\r\nreal output\r\n")
        await flush(adapter)
        adapter.post.assert_awaited_once_with("raw", "agent", "real output")

    async def test_unrelated_text_is_not_mistaken_for_echo(self):
        adapter = make()
        await adapter.send_keys("hello there")
        await adapter.on_output(b"goodbye")
        await flush(adapter)
        adapter.post.assert_awaited_once_with("raw", "agent", "goodbye")


if __name__ == "__main__":
    unittest.main()
