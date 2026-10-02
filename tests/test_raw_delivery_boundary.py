"""Raw fallback settles only after its adapter boundary, never on paste."""

from __future__ import annotations

import time
import unittest
from unittest.mock import AsyncMock

from partyline.adapters.bundled.raw.adapter import RawAdapter


class RawDeliveryBoundaryTest(unittest.IsolatedAsyncioTestCase):
    async def test_quiescence_flush_reports_the_weaker_delivery_boundary(self):
        adapter = RawAdapter(
            {"name": "raw", "cwd": ".", "runtime_owner": "owner"},
            AsyncMock(),
            AsyncMock(),
        )
        adapter.alive = lambda: False
        adapter.post = AsyncMock()
        boundary = AsyncMock()
        adapter.att["credit_delivery_boundary"] = boundary
        adapter._buffer = ["completed output"]
        adapter._last_output = time.monotonic() - 2
        await adapter._run()

        adapter.post.assert_awaited_once_with("raw", "agent", "completed output")
        boundary.assert_awaited_once_with()


if __name__ == "__main__":
    unittest.main()
