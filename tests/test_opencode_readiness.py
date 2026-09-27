"""An unclaimed OpenCode process cannot reserve the whole instance forever."""

import asyncio
import tempfile
import unittest
from unittest.mock import AsyncMock, Mock, patch

from partyline.adapters.bundled.opencode.v2 import PartylineAdapter
from partyline.db import Db
from partyline.line_process_routes import detach_attachment
from partyline.presence import Presence
from partyline.runtime import ChatRuntime


class OpenCodeReadinessTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db = Db(f"{self.tmp.name}/partyline.db")
        self.addCleanup(self.db.close)
        self.db.create_conversation("line", "Line")
        for ident in ("bunny", "other"):
            self.db.add_attachment(ident, "line", ident, "opencode-v2", [],
                                   self.tmp.name, ident)
        self.db.set_attachment_status("other", "detached", "other")
        self.runtime = ChatRuntime(self.db)
        att = self.db.get_attachment("bunny")
        att["adapter_metadata"] = {"capabilities": {"transcript": True}}
        self.adapter = PartylineAdapter(att, AsyncMock(), AsyncMock())
        self.adapter.send_keys = AsyncMock()
        self.runtime.live["bunny"] = self.adapter

    async def test_unready_delivery_leaves_cursor_and_other_lifecycles_available(self):
        message = self.db.add_message("line", "greg", "human", "@bunny continue")
        # This is the production route that held the global owner lock overnight.
        delivered = await asyncio.wait_for(self.runtime.deliver_pending(
            "line", self.db.get_attachment("bunny"), self.adapter), timeout=0.2)
        self.assertFalse(delivered)
        self.adapter.send_keys.assert_not_awaited()
        self.assertLess(self.db.get_attachment("bunny")["last_seen"], message["id"])
        self.assertTrue(await asyncio.wait_for(
            self.db.claim_attachment_async("other", "new-owner"), timeout=0.2))
        self.runtime.live["other"] = Mock(
            att={"runtime_owner": "new-owner"}, stop=AsyncMock(side_effect=lambda:
                self.db.set_attachment_status("other", "detached", "new-owner")))
        self.assertEqual(await asyncio.wait_for(
            detach_attachment(self.runtime, "other"), timeout=0.2), {"ok": True})

    async def test_ready_claim_retries_previously_unpasted_message(self):
        message = self.db.add_message("line", "greg", "human", "@bunny continue")
        presence = Presence(self.runtime)
        presence.watch(self.adapter, "line", "bunny", "receipt",
                       *self.runtime.held_wake_hooks("line", "bunny", "bunny"))
        await asyncio.wait_for(self.runtime.deliver_pending(
            "line", self.db.get_attachment("bunny"), self.adapter), timeout=0.2)
        self.adapter._claim_proven = True
        sent = asyncio.Event()
        self.adapter.send_keys.side_effect = lambda text: sent.set()
        self.adapter.mark_ready()
        await asyncio.wait_for(sent.wait(), timeout=0.2)
        self.assertEqual(self.adapter._wake_receipts[0]["ids"], [message["id"]])
        # A paste alone must not advance the durable delivery cursor.
        self.assertLess(self.db.get_attachment("bunny")["last_seen"], message["id"])

    async def test_failed_startup_releases_waiters_and_stops_process(self):
        self.adapter._resolve_store = Mock(side_effect=OSError("diagnostic unavailable"))
        with patch.object(self.adapter, "stop", new_callable=AsyncMock) as stop:
            await self.adapter._run()
        self.assertFalse(await asyncio.wait_for(self.adapter.wait_ready(), timeout=0.2))
        stop.assert_awaited_once()
        self.assertIn("diagnostic unavailable", self.adapter._post_to_chat.call_args.args[-1])
