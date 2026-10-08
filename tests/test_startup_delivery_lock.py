"""A blocked Claude startup must not lock every line's delivery and detach."""

import asyncio
from contextlib import suppress
from pathlib import Path
import tempfile
import tomllib
import unittest
from unittest.mock import AsyncMock

from partyline.adapters.bundled.claude.adapter import PartylineAdapter
from partyline.adapters.base import Adapter
from partyline.continuation_delivery import deliver_continuation
from partyline.db import Db
from partyline.delivery_reservation import reserve_delivery
from partyline.runtime import ChatRuntime


class StartupDeliveryLockTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.db = Db(f"{directory.name}/partyline.db")
        self.addCleanup(self.db.close)
        self.db.create_conversation("line", "Line")
        self.db.create_conversation("parent", "Parent")
        for ident, line in (("worker", "line"), ("captain", "parent")):
            self.db.add_attachment(ident, line, ident, "claude", ["claude"], directory.name, "owner")
            self.db.set_attachment_status(ident, "running", "owner")
        metadata = tomllib.loads((Path(__file__).parents[1] / "partyline/adapters/bundled/claude/"
                                  "adapter.toml").read_text())["adapter"]
        self.adapter = PartylineAdapter(
            {**self.db.get_attachment("worker"), "adapter_metadata": metadata}, AsyncMock(), AsyncMock()
        )
        self.adapter.send_keys = AsyncMock()
        self.runtime = ChatRuntime(self.db)
        self.runtime.live["worker"] = self.adapter
        self.message = self.db.add_message("line", "greg", "human", "@worker draw the hero")

    def delivery(self, path):
        if path == "mention":
            return self.runtime.deliver_pending("line", self.db.get_attachment("worker"), self.adapter)
        if path == "held":
            flush, *_ = self.runtime.held_wake_hooks("line", "worker", "worker")
            return flush([self.message["id"]])
        return deliver_continuation(self.runtime, self.adapter, "worker", [self.message], 1)

    async def cancel(self, task):
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task

    async def assert_captain_reachable(self):
        captain = self.db.get_attachment("captain")
        adapter = Adapter(captain, AsyncMock(), AsyncMock())
        adapter.send_keys = AsyncMock()
        self.db.add_message("parent", "greg", "human", "@captain hello?")
        self.assertTrue(await asyncio.wait_for(
            self.runtime.deliver_pending("parent", captain, adapter), .3
        ))
        adapter.send_keys.assert_awaited_once()
        self.assertTrue(await asyncio.wait_for(
            self.db.set_attachment_status_async("captain", "detached", "owner"), .3
        ))

    async def test_startup_wait_does_not_block_captain_delivery_or_detach(self):
        for path in ("mention", "held", "continuation"):
            with self.subTest(path=path):
                self.db.set_attachment_status("captain", "running", "owner")
                task = asyncio.create_task(self.delivery(path))
                try:
                    await asyncio.sleep(0)
                    self.assertFalse(task.done())
                    self.adapter.send_keys.assert_not_awaited()
                    await self.assert_captain_reachable()
                    self.assertEqual(self.db.get_attachment("worker")["last_seen"], 0)
                finally:
                    await self.cancel(task)

    async def test_briefing_retry_wait_does_not_block_other_lines(self):
        self.adapter._startup_prompt_result = True
        self.adapter._startup_prompt_delivery.set()
        for path in ("mention", "held", "continuation"):
            with self.subTest(path=path):
                self.db.set_attachment_status("captain", "running", "owner")
                async with self.adapter._startup_paste_lock:
                    task = asyncio.create_task(self.delivery(path))
                    try:
                        await asyncio.sleep(0)
                        self.assertFalse(task.done())
                        await self.assert_captain_reachable()
                    finally:
                        await self.cancel(task)

    async def test_opening_startup_pastes_once_and_waits_for_transcript_credit(self):
        task = asyncio.create_task(self.delivery("mention"))
        try:
            await asyncio.sleep(0)
            self.adapter._mark_claim_proven()
            self.adapter.mark_ready()
            self.adapter._startup_prompt_result = True
            self.adapter._startup_prompt_delivery.set()
            self.assertFalse(await asyncio.wait_for(task, .3))
            self.adapter.send_keys.assert_awaited_once()
            self.assertEqual(self.db.get_attachment("worker")["last_seen"], 0)
            self.assertTrue(await self.runtime.confirm_delivery_ids(
                "worker", [self.message["id"]], "owner"
            ))
            self.assertTrue(await self.delivery("mention"))
            self.adapter.send_keys.assert_awaited_once()
        finally:
            await self.cancel(task)

    async def test_stop_unblocks_startup_without_paste_or_credit(self):
        task = asyncio.create_task(self.delivery("mention"))
        try:
            await asyncio.sleep(0)
            self.adapter.abort_startup_prompt()
            self.assertFalse(await asyncio.wait_for(task, .3))
            self.adapter.send_keys.assert_not_awaited()
            self.assertEqual(self.db.get_attachment("worker")["last_seen"], 0)
        finally:
            await self.cancel(task)

    async def test_owner_change_during_startup_rejects_the_old_activation(self):
        task = asyncio.create_task(self.delivery("mention"))
        try:
            await asyncio.sleep(0)
            self.assertTrue(await self.db.set_attachment_status_async("worker", "exited", "owner"))
            self.assertTrue(await self.db.claim_attachment_async("worker", "replacement"))
            self.adapter._startup_prompt_result = True
            self.adapter._startup_prompt_delivery.set()
            self.assertFalse(await asyncio.wait_for(task, .3))
            self.adapter.send_keys.assert_not_awaited()
        finally:
            await self.cancel(task)

    async def test_cancellation_during_paste_releases_both_locks(self):
        self.adapter._startup_prompt_result = True
        self.adapter._startup_prompt_delivery.set()
        entered = asyncio.Event()

        async def paste(_text):
            entered.set()
            await asyncio.Event().wait()

        self.adapter.send_keys.side_effect = paste
        task = asyncio.create_task(self.delivery("mention"))
        await asyncio.wait_for(entered.wait(), .3)
        await self.cancel(task)
        self.assertFalse(self.adapter._startup_paste_lock.locked())
        self.assertIsNone(self.adapter._startup_delivery_task)
        await self.assert_captain_reachable()

    async def test_startup_reservation_excludes_retries_until_paste_finishes(self):
        self.adapter._startup_prompt_result = True
        self.adapter._startup_prompt_delivery.set()
        async with reserve_delivery(self.db, self.adapter, "worker", "owner") as reserved:
            self.assertTrue(reserved)
            self.assertTrue(await self.adapter.wait_startup_delivery())
            self.assertTrue(self.adapter._startup_paste_lock.locked())
        self.assertFalse(self.adapter._startup_paste_lock.locked())
