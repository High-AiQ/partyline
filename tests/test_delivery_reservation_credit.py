"""Write-based delivery credit and ownership handoff are one reserved effect."""

from contextlib import asynccontextmanager
import tempfile
import unittest

from partyline.continuation_delivery import deliver_continuation
from partyline.db import Db
from partyline.runtime import ChatRuntime


class Adapter:
    def __init__(self):
        self.att = {"runtime_owner": "old"}
        self.deliveries = []

    async def deliver(self, messages):
        self.deliveries.append(messages)
        return True


class DeliveryReservationCreditTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.db = Db(f"{self.directory.name}/test.db")
        self.db.create_conversation("line", "Line")
        self.db.add_attachment("one", "line", "worker", "fake", ["fake"], "/tmp", "old")
        self.db.set_attachment_status("one", "running", "old")
        self.runtime = ChatRuntime(self.db)
        self.adapter = Adapter()
        self.runtime.live["one"] = self.adapter
        self.original_reservation = self.db.reserve_attachment_delivery
        self.credit_at_handoff = None

        @asynccontextmanager
        async def reserve(att_id, owner):
            async with self.original_reservation(att_id, owner) as reserved:
                yield reserved
            # Simulate a waiting replacement winning immediately on release.
            entry = self.runtime.uncredited.get(att_id) or {}
            self.credit_at_handoff = set(entry.get("confirmed", ()))
            self.db._exec("UPDATE attachments SET runtime_owner='new' WHERE id=?", (att_id,))

        self.db.reserve_attachment_delivery = reserve

    async def asyncTearDown(self):
        self.db.close()
        self.directory.cleanup()

    async def test_fallback_write_credits_before_replacement_claims(self):
        message = self.db.add_message("line", "human", "human", "@worker backlog")
        await deliver_continuation(self.runtime, self.adapter, "one", [message], .5)
        self.assertEqual(self.db.get_attachment("one")["runtime_owner"], "new")
        self.assertEqual(self.db.get_attachment("one")["last_seen"], message["id"])
        self.assertEqual(len(self.adapter.deliveries), 1)

    async def test_newer_writes_record_their_proof_before_handoff(self):
        for path in ("mention", "queue"):
            with self.subTest(path=path):
                self.db._exec("UPDATE attachments SET runtime_owner='old', last_seen=0 WHERE id='one'")
                self.db._exec("DELETE FROM messages")
                self.runtime.uncredited.clear()
                older = self.db.add_message("line", "human", "human", "@worker older")
                newer = self.db.add_message("line", "human", "human", "@worker newer")
                self.runtime._record_unproved(self.db.get_attachment("one"), self.adapter, [older])
                if path == "mention":
                    self.assertTrue(await self.runtime.deliver_pending(
                        "line", self.db.get_attachment("one"), self.adapter
                    ))
                else:
                    await self.db.queue_delivery_ids("one", [newer["id"]], "old")
                    flush, *_ = self.runtime.held_wake_hooks("line", "one", "worker")
                    self.assertTrue(await flush([newer["id"]]))
                self.assertEqual(self.credit_at_handoff, {newer["id"]})
                self.assertEqual(self.db.get_attachment("one")["last_seen"], 0)
                self.assertEqual(self.db.get_attachment("one")["runtime_owner"], "new")
