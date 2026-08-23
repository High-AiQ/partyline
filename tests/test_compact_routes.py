"""REST compact requests use manifest pastes and the shared idle gate."""

import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from partyline.compact_routes import register_compact_route, request_compact
from partyline.presence import Presence


class CompactRouteTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.runtime = SimpleNamespace(live={}, broadcast=AsyncMock())
        self.presence = Presence(self.runtime)

    async def test_rejects_dead_and_unsupported_attachments(self):
        with self.assertRaises(HTTPException) as dead:
            await request_compact(self.runtime, self.presence, "missing")
        self.assertEqual(dead.exception.status_code, 404)

        self.runtime.live["raw"] = SimpleNamespace(
            att={"adapter_metadata": {"compact_paste": None}}, send_keys=AsyncMock()
        )
        with self.assertRaises(HTTPException) as unsupported:
            await request_compact(self.runtime, self.presence, "raw")
        self.assertEqual(unsupported.exception.status_code, 409)

    async def test_uses_exact_manifest_paste_and_reports_queue_state(self):
        adapter = SimpleNamespace(
            att={"adapter_metadata": {"compact_paste": "/summarize\n"}},
            send_keys=AsyncMock(),
        )
        self.runtime.live["cursor"] = adapter

        self.assertEqual(
            await request_compact(self.runtime, self.presence, "cursor"),
            {"ok": True, "queued": False},
        )
        adapter.send_keys.assert_awaited_once_with("/summarize\n")

        adapter.send_keys.reset_mock()
        await self.presence.began("line", "cursor")
        self.assertEqual(
            await request_compact(self.runtime, self.presence, "cursor"),
            {"ok": True, "queued": True},
        )
        adapter.send_keys.assert_not_awaited()
        await self.presence.ended("line", "cursor")
        adapter.send_keys.assert_awaited_once_with("/summarize\n")

    async def test_registered_rest_endpoint_returns_named_result(self):
        adapter = SimpleNamespace(
            att={"adapter_metadata": {"compact_paste": "/compact"}},
            send_keys=AsyncMock(),
        )
        self.runtime.live["codex"] = adapter
        app = FastAPI()
        register_compact_route(app, self.runtime, self.presence)

        with TestClient(app) as client:
            response = client.post("/api/attachments/codex/compact")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"ok": True, "queued": False})
        adapter.send_keys.assert_awaited_once_with("/compact")


if __name__ == "__main__":
    unittest.main()
