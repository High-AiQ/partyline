"""Resume startup is a turn, not permission to paste the continuation."""

import asyncio
import json
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch

from partyline.adapters.bundled.opencode.v2 import RESUME_READY_TIMEOUT_SECONDS
from partyline.adapters.receipts import BEGAN
from partyline.db import Db
from partyline.presence import Presence
from partyline.runtime import ChatRuntime
from tests import test_opencode_v2_adapter as v2_tests


class OpenCodeV2ResumeTests(unittest.IsolatedAsyncioTestCase):
    setUp = v2_tests.OpenCodeV2Tests.setUp
    make = v2_tests.OpenCodeV2Tests.make
    row = v2_tests.OpenCodeV2Tests.row
    claim = v2_tests.OpenCodeV2Tests.claim

    async def test_preclaim_wakes_wait_for_ready_turn_idle_and_exact_user_proof(self):
        db = Db(f"{self.tmp.name}/partyline.db")
        self.addCleanup(db.close)
        db.create_conversation("line", "Line")
        db.add_attachment("a", "line", "agent", "opencode-v2", [], "/project", "owner")
        runtime = ChatRuntime(db)
        runtime.broadcast = AsyncMock()
        runtime.broadcast_attachment = AsyncMock()
        adapter = self.adapter
        adapter.resume = True
        adapter.att["cli_session"] = "ours"
        adapter.att["runtime_owner"] = "owner"
        adapter.att["adapter_metadata"]["delivery_proof"] = "transcript-user-record"
        adapter.send_keys = AsyncMock()
        runtime.live["a"] = adapter
        presence = Presence(runtime)
        presence.watch(adapter, "line", "a", "receipt", *runtime.held_wake_hooks("line", "a", "agent"))
        first = db.add_message("line", "system", "system", "continue the task")
        db._exec("UPDATE messages SET audience_attachment_id='a' WHERE id=?", (first["id"],))
        second = db.add_message("line", "captain", "agent", "@agent finish the fix")
        await runtime.deliver_pending("line", db.get_attachment("a"), adapter)

        async def boundary(att, event):
            if event == BEGAN:
                await presence.started("line", "a", "owner")
            else:
                await presence.ended("line", "a", "owner")

        with patch("partyline.adapters.bundled.opencode.v2.receipt", side_effect=boundary):
            self.claim()
            await adapter._poll()
            adapter.send_keys.assert_not_awaited()
            self.assertIsNone(adapter._ready_result)
            self.row("ready", "assistant", {"time": {"completed": 2}, "content": [
                {"type": "text", "text": "READY"}]}, seq=2)
            await adapter._poll()
            adapter.send_keys.assert_not_awaited()
            self.row("idle", "idle", {"outcome": "succeeded"}, seq=3)
            sent = asyncio.Event()
            adapter.send_keys.side_effect = lambda text: sent.set()
            await adapter._poll()
            await asyncio.wait_for(sent.wait(), 1)
            self.assertFalse(adapter._busy)
            self.assertFalse(presence.is_working("a"))
            wake = adapter._wake_receipts[0]
            self.assertEqual(wake["ids"], [first["id"], second["id"]])
            self.assertLess(db.get_attachment("a")["last_seen"], first["id"])
            # Neither READY, an assistant echo, nor unrelated user input is proof.
            self.row("echo", "assistant", {"time": {"completed": 3}, "content": [
                {"type": "text", "text": wake["marker"]}]}, seq=4)
            self.row("unrelated", "user", {"text": "other input"}, seq=5)
            await adapter._poll()
            self.assertLess(db.get_attachment("a")["last_seen"], first["id"])
            self.row("accepted", "user", {"text": wake["marker"]}, seq=6)
            await adapter._poll()
            self.assertEqual(db.get_attachment("a")["last_seen"], second["id"])

    async def test_swallowed_paste_is_retried_at_idle_without_credit(self):
        self.claim()
        await self.adapter._poll()
        self.adapter.send_keys = AsyncMock()
        self.adapter.att["confirm_delivery_ids"] = AsyncMock(return_value=True)
        self.adapter.att["repool_message_ids"] = AsyncMock(return_value=True)
        await self.adapter.deliver([{"id": 42, "sender": "captain", "body": "continue"}])
        self.row("ready", "assistant", {"time": {"completed": 2}, "content": [
            {"type": "text", "text": "READY"}]}, seq=2)
        self.row("idle", "idle", {"outcome": "succeeded"}, seq=3)
        with patch("partyline.adapters.bundled.opencode.wakes.REPOOL_GRACE", 0):
            await self.adapter._poll()
            await self.adapter._repool_task
        self.adapter.att["confirm_delivery_ids"].assert_not_awaited()
        self.adapter.att["repool_message_ids"].assert_awaited_once_with([42])
        self.assertFalse(self.adapter._busy)

    async def test_idle_dropped_paste_retries_without_another_transcript_record(self):
        self.claim()
        self.row("idle", "idle", {"outcome": "succeeded"}, seq=2)
        await self.adapter._poll()
        self.adapter.send_keys = AsyncMock()
        repool = AsyncMock(return_value=False)
        self.adapter.att["repool_message_ids"] = repool
        await self.adapter.deliver([{"id": 42, "sender": "captain", "body": "status?"}])
        with patch("partyline.adapters.bundled.opencode.wakes.REPOOL_GRACE", 0):
            await self.adapter._poll()
            await self.adapter._repool_task
            # A refused queue handoff must not erase the outstanding proof.
            self.assertEqual(self.adapter._wake_receipts[0]["ids"], [42])
            repool.side_effect = RuntimeError("queue unavailable")
            await self.adapter._poll()
            with self.assertRaisesRegex(RuntimeError, "queue unavailable"):
                await self.adapter._repool_task
            self.assertEqual(self.adapter._wake_receipts[0]["ids"], [42])
            repool.side_effect = None
            repool.return_value = True
            await self.adapter._poll()
            await self.adapter._repool_task
        self.assertEqual(repool.await_count, 3)
        self.assertEqual(self.adapter._wake_receipts, [])
        self.assertEqual(self.adapter._confirmed_delivery_ids, set())

    async def test_idle_retry_defers_if_a_new_user_turn_began_during_grace(self):
        self.claim()
        self.row("idle", "idle", {"outcome": "succeeded"}, seq=2)
        await self.adapter._poll()
        self.adapter.send_keys = AsyncMock()
        repool = AsyncMock(return_value=True)
        self.adapter.att["repool_message_ids"] = repool
        await self.adapter.deliver([{"id": 42, "sender": "captain", "body": "continue"}])
        with patch("partyline.adapters.bundled.opencode.wakes.REPOOL_GRACE", 0):
            await self.adapter._poll()
            self.adapter._busy = True
            await self.adapter._repool_task
        repool.assert_not_awaited()
        self.assertEqual(self.adapter._wake_receipts[0]["ids"], [42])

    async def test_resume_readiness_is_bounded_when_no_idle_row_arrives(self):
        self.adapter.resume = True
        self.adapter.att["cli_session"] = "ours"
        now = 100
        clock = SimpleNamespace(monotonic=lambda: now)
        with patch("partyline.adapters.bundled.opencode.v2.time", clock):
            self.claim()
            await self.adapter._poll()
            self.assertIsNone(self.adapter._ready_result)
            self.row("failure", "error", {"error": "provider unavailable"}, seq=2)
            now += RESUME_READY_TIMEOUT_SECONDS - 1
            await self.adapter._poll()
            self.assertIsNone(self.adapter._ready_result)
            now += 1
            await self.adapter._poll()  # no new rows, in particular no idle row
        self.assertTrue(await self.adapter.wait_ready())
        self.assertTrue(self.adapter._busy)  # timeout does not fabricate an idle receipt
        self.assertEqual(self.adapter._confirmed_delivery_ids, set())

    async def test_progress_tracks_new_rows_and_mutations_but_not_rereads(self):
        now = 100
        clock = SimpleNamespace(monotonic=lambda: now)
        with patch("partyline.adapters.bundled.opencode.v2.time", clock):
            self.claim()
            await self.adapter._poll()
            self.assertEqual(self.adapter.last_transcript_progress, 100)
            for seq, kind in enumerate(("user", "assistant", "error", "system", "idle",
                                        "compaction"), start=2):
                now += 100
                self.row(f"row-{seq}", kind, {"text": "input", "time": {}}, seq=seq)
                await self.adapter._poll()
                self.assertEqual(self.adapter.last_transcript_progress, now)
                now += 1
                await self.adapter._poll()
                self.assertEqual(self.adapter.last_transcript_progress, now - 1)
            # Stream/tool updates mutate an existing assistant row without a new id.
            now += 100
            self.db.execute("UPDATE session_message SET data=? WHERE id='row-3'",
                            (json.dumps({"time": {}, "content": [{"type": "text",
                                                                 "text": "streaming"}]}),))
            self.db.commit()
            await self.adapter._poll()
            self.assertEqual(self.adapter.last_transcript_progress, now)

    async def test_proven_receipts_do_not_schedule_idle_retry_tasks(self):
        self.claim()
        self.row("idle", "idle", {"outcome": "succeeded"}, seq=2)
        await self.adapter._poll()
        self.adapter._wake_receipts = [{"ids": [42], "proven": True}]
        for _ in range(3):
            await self.adapter._poll()
            self.assertIsNone(self.adapter._repool_task)
