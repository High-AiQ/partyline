"""Shared JSONL receipts are tied to the lifetime of each paste."""

import asyncio
import json
import tempfile
import unittest
from datetime import UTC, datetime
from unittest.mock import AsyncMock

from partyline.adapters.bundled.antigravity.adapter import PartylineAdapter as AntigravityAdapter
from partyline.adapters.bundled.claude.adapter import PartylineAdapter
from partyline.db import Db
from partyline.presence import Presence
from partyline.runtime import ChatRuntime


class ClaudeJsonlReceiptTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.db = Db(f"{self.temp.name}/partyline.db")
        self.addCleanup(self.db.close)
        self.db.create_conversation("line", "Line")
        self.db.add_attachment("att", "line", "claude", "claude", ["claude"],
                               self.temp.name, "owner")
        self.db.set_attachment_status("att", "running", "owner")
        self.runtime = ChatRuntime(self.db)
        self.presence = Presence(self.runtime)
        self.runtime.post_message = AsyncMock()

    def make_adapter(self):
        adapter = PartylineAdapter(
            {"id": "att", "name": "claude", "cwd": self.temp.name,
             "command": ["claude"], "runtime_owner": "owner",
             "adapter_metadata": {"capabilities": {"transcript": True}}},
            AsyncMock(), AsyncMock(),
        )
        adapter.format_digest = lambda _messages: "wake with a distinctive digest"
        adapter.send_keys = AsyncMock()
        adapter.alive = lambda: True
        watched = self.presence.watch(
            adapter, "line", "att", "receipt",
            *self.runtime.held_wake_hooks("line", "att", "claude"),
        )
        self.runtime.live["att"] = watched
        return watched

    def add_wake(self):
        return self.db.add_message("line", "human", "human", "@claude wake")["id"]

    async def test_old_identical_user_line_does_not_prove_a_new_paste(self):
        adapter = self.make_adapter()
        message_id = self.add_wake()
        await adapter.deliver([{"id": message_id}])
        calls = []

        async def confirm(ids):
            calls.append(ids)
            return True

        adapter.att["confirm_delivery_ids"] = confirm
        receipt = adapter._jsonl_receipts[0]
        old = {
            "type": "user", "timestamp": receipt["pasted_at"] - 1,
            "message": {"content": receipt["digest"]},
        }
        await adapter._observe_jsonl_paste(old)

        self.assertEqual(calls, [])
        self.assertEqual(self.db.get_attachment("att")["last_seen"], 0)
        self.assertEqual(len(adapter._jsonl_receipts), 1)

    async def test_claude_tool_result_echo_is_not_user_paste_proof(self):
        adapter = self.make_adapter()
        message_id = self.add_wake()
        await adapter.deliver([{"id": message_id}])
        receipt = adapter._jsonl_receipts[0]
        tool_echo = {
            "type": "user", "timestamp": receipt["pasted_at"] + 0.01,
            "message": {"content": [{
                "type": "tool_result", "content": [{
                    "type": "text", "text": receipt["marker"],
                }],
            }]},
        }

        await adapter._observe_jsonl_paste(tool_echo)

        self.assertEqual(self.db.get_attachment("att")["last_seen"], 0)
        self.assertEqual(len(adapter._jsonl_receipts), 1)

    async def test_later_claim_token_does_not_prove_a_lost_earlier_paste(self):
        adapter = self.make_adapter()
        adapter.format_digest = lambda _messages: f"same digest\n{adapter._claim_token}"
        confirmed = AsyncMock(return_value=True)
        adapter.att["confirm_delivery_ids"] = confirmed
        await adapter.deliver([{"id": 51, "body": "wake A"}])
        await adapter.deliver([{"id": 52, "body": "wake B"}])
        second = adapter._jsonl_receipts[1]

        await adapter._observe_jsonl_paste({
            "type": "user", "timestamp": second["pasted_at"] + 0.01,
            "message": {"content": f"{second['digest']}\n{second['marker']}"},
        })

        confirmed.assert_awaited_once_with([52])
        self.assertEqual([receipt["ids"] for receipt in adapter._jsonl_receipts], [[51]])

    async def test_one_user_record_proves_only_one_identical_paste(self):
        adapter = self.make_adapter()
        first, second = self.add_wake(), self.add_wake()
        path = f"{self.temp.name}/claude.jsonl"
        open(path, "w", encoding="utf-8").close()
        adapter._jsonl_tail_path = path
        await adapter.deliver([{"id": first}])
        await adapter.deliver([{"id": second}])
        first_receipt = adapter._jsonl_receipts[0]
        record = {
            "type": "user", "timestamp": first_receipt["pasted_at"] + 0.01,
            "message": {"content": first_receipt["marker"]},
        }

        await adapter._observe_jsonl_paste(record)

        self.assertEqual(self.db.get_attachment("att")["last_seen"], first)
        self.assertEqual([r["ids"] for r in adapter._jsonl_receipts], [[second]])

    async def test_antigravity_second_precision_uses_current_tail_position(self):
        adapter = AntigravityAdapter(
            {"id": "agy", "name": "agy", "cwd": self.temp.name, "command": ["agy"]},
            AsyncMock(), AsyncMock(),
        )
        adapter.format_digest = lambda _messages: "second precision wake"
        adapter.send_keys = AsyncMock()
        adapter.alive = lambda: True
        adapter._claim_proven = True
        path = f"{self.temp.name}/antigravity.jsonl"
        with open(path, "wb") as transcript:
            transcript.write(b"\n")
        adapter._jsonl_tail_path = path
        adapter.att["confirm_delivery_ids"] = AsyncMock(return_value=True)
        await adapter.deliver([{"id": 72}])
        paste = adapter._jsonl_receipts[0]
        record = {
            "source": "USER_EXPLICIT", "type": "USER_INPUT",
            "created_at": datetime.fromtimestamp(
                int(paste["pasted_at"]), tz=UTC,
            ).isoformat(),
            "content": paste["marker"],
        }

        await adapter._observe_jsonl_paste(record)

        adapter.att["confirm_delivery_ids"].assert_awaited_once_with([72])
        self.assertEqual(adapter._jsonl_receipts, [])

    async def test_preclaim_claude_record_settles_before_ready_without_repaste(self):
        adapter = self.make_adapter()
        message_id = self.add_wake()
        self.assertFalse(await self.runtime.deliver_pending(
            "line", self.db.get_attachment("att"), adapter,
        ))
        receipt = adapter._jsonl_receipts[0]
        current = {
            "type": "user", "timestamp": receipt["pasted_at"] + 0.01,
            "message": {"content": receipt["marker"]},
        }
        path = f"{self.temp.name}/claude.jsonl"
        with open(path, "w", encoding="utf-8") as transcript:
            transcript.write(json.dumps(current) + "\n")

        original_mark_ready = adapter.mark_ready

        def stop_after_ready():
            original_mark_ready()
            adapter.alive = lambda: False

        adapter.mark_ready = stop_after_ready
        await adapter._tail_jsonl(path, AsyncMock())

        self.assertEqual(adapter.send_keys.await_count, 1)
        self.assertEqual(self.db.get_attachment("att")["last_seen"], message_id)
        self.assertEqual(adapter._jsonl_receipts, [])

    async def test_activation_claim_proves_first_paste_without_a_timestamp(self):
        adapter = self.make_adapter()
        adapter.format_digest = lambda _messages: f"digest\n{adapter._claim_token}"
        message_id = self.add_wake()
        await adapter.deliver([{"id": message_id}])
        digest = adapter._jsonl_receipts[0]["digest"]
        record = {
            "type": "user",
            "message": {"content": f"briefing {digest}\n{adapter._jsonl_receipts[0]['marker']}"},
        }

        await adapter._observe_jsonl_paste(record)

        self.assertEqual(self.db.get_attachment("att")["last_seen"], message_id)
        self.assertEqual(adapter._jsonl_receipts, [])

    async def test_unrecorded_preclaim_paste_retries_after_ready(self):
        adapter = self.make_adapter()
        message_id = self.add_wake()
        path = f"{self.temp.name}/claude.jsonl"
        open(path, "w", encoding="utf-8").close()
        self.assertFalse(await self.runtime.deliver_pending(
            "line", self.db.get_attachment("att"), adapter,
        ))
        self.assertEqual(adapter.send_keys.await_count, 1)
        self.assertEqual(self.db.get_attachment("att")["last_seen"], 0)
        first_marker = adapter._jsonl_receipts[0]["marker"]

        tail = asyncio.create_task(adapter._tail_jsonl(path, AsyncMock()))
        deadline = asyncio.get_running_loop().time() + 2
        while adapter.send_keys.await_count < 2:
            if asyncio.get_running_loop().time() >= deadline:
                self.fail("unproved Claude paste was not retried after readiness")
            await asyncio.sleep(0.01)
        adapter.alive = lambda: False
        await asyncio.wait_for(tail, timeout=1)

        self.assertEqual(adapter.send_keys.await_count, 2)
        self.assertEqual(self.db.get_attachment("att")["last_seen"], 0)
        self.assertEqual(len(adapter._jsonl_receipts), 1)
        retry_receipt = adapter._jsonl_receipts[0]
        self.assertEqual(retry_receipt["ids"], [message_id])
        self.assertNotEqual(retry_receipt["marker"], first_marker)
        delivered = {
            "type": "user", "timestamp": retry_receipt["pasted_at"] + 0.01,
            "message": {"content": retry_receipt["marker"]},
        }
        await adapter._observe_jsonl_paste(delivered)
        self.assertEqual(self.db.get_attachment("att")["last_seen"], message_id)
        self.assertTrue(await self.runtime.deliver_pending(
            "line", self.db.get_attachment("att"), adapter,
        ))
        self.assertEqual(adapter.send_keys.await_count, 2)

    async def test_late_original_receipt_cancels_a_queued_retry(self):
        adapter = self.make_adapter()
        message_id = self.add_wake()
        self.assertFalse(await self.runtime.deliver_pending(
            "line", self.db.get_attachment("att"), adapter,
        ))
        receipt = adapter._jsonl_receipts[0]
        await self.presence.started("line", "att", "owner")
        adapter.mark_ready()
        deadline = asyncio.get_running_loop().time() + 1
        while not self.presence.queue.held_ids("att"):
            if asyncio.get_running_loop().time() >= deadline:
                self.fail("preclaim retry was not transferred to Presence")
            await asyncio.sleep(0.01)
        self.assertEqual(adapter.send_keys.await_count, 1)

        await adapter._observe_jsonl_paste({
            "type": "user", "timestamp": receipt["pasted_at"] + 0.01,
            "message": {"content": receipt["marker"]},
        })
        await self.presence.ended("line", "att", "owner")

        self.assertEqual(adapter.send_keys.await_count, 1)
        self.assertEqual(self.db.get_attachment("att")["last_seen"], message_id)
