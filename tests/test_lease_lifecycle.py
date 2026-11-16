"""Lease promotion and wake, approval release, the holder check and the idle exemption.

Every clock is a fake: no test waits in real time.
"""

import asyncio
import os
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from partyline import auth_store
from partyline.auth_guard import install_auth_guard
from partyline.db import Db
from partyline.lease_lifecycle import (
    holds_any_lease,
    holds_lease,
    next_expiry_delay,
    release_for_task,
    sweep,
)
from partyline.orchestrator_contracts import ReviewRequestIn, VerdictIn
from partyline.orchestrator_service import request_review, review_verdict
from partyline.orchestrator_stall import settle as stall_settle
from partyline.resource_leases import (
    register_lease_routes,
    release_attachment_leases,
    release_lease,
    request_lease,
)
from partyline.runtime import ChatRuntime
from tests.orchestrator_fixture import TaskFixture


class Clock:
    """A settable replacement for the `time` module the lease logic reads."""

    def __init__(self, now=1_000_000.0):
        self.now = now

    def time(self):
        return self.now


class LeaseWakeTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.db = Db(os.path.join(self.directory.name, "partyline.db"))
        self.addCleanup(self.db.close)
        self.runtime = ChatRuntime(self.db)
        self.runtime.route_mentions = AsyncMock()
        self.runtime.broadcast = AsyncMock()
        self.clock = Clock()
        patcher = patch("partyline.resource_leases.time", self.clock)
        patcher.start()
        self.addCleanup(patcher.stop)
        for name in ("a", "b", "c", "d", "e"):
            self.db.create_conversation(f"line-{name}", f"line {name}")
            self.db.add_attachment(name, f"line-{name}", f"proc-{name}", "raw", ["raw"],
                                   self.directory.name, f"owner-{name}")
            self.db.set_attachment_status(name, "running", f"owner-{name}")

    def take(self, who, mode="exclusive", ttl_s=900, name="shared-db"):
        att = self.db.get_attachment(who)
        return request_lease(self.db, who, att["name"], att["conv_id"], name, mode, ttl_s)

    def wakes(self, who):
        att = self.db.get_attachment(who)
        return [m for m in self.db.message_page(att["conv_id"], limit=100)[0]
                if "is now granted to you" in m["body"]
                and m["audience_attachment_id"] == who]

    def holds(self, who, name="shared-db"):
        row = self.db._exec(
            "SELECT waiting FROM resource_leases WHERE name=? AND holder_attachment=?",
            (name, who)).fetchone()
        return row is not None and not row["waiting"]

    async def test_release_promotes_and_wakes_the_next_waiter_once(self):
        self.assertTrue(self.take("a")["granted"])
        self.assertFalse(self.take("b", ttl_s=1800)["granted"])
        self.assertEqual(await sweep(self.runtime), 0)  # nothing is free yet
        self.assertTrue(release_lease(self.db, "a", "shared-db"))
        self.assertTrue(self.holds("b"))  # promoted by the release itself
        self.assertEqual(await sweep(self.runtime), 1)
        notice = self.wakes("b")[0]["body"]
        self.assertIn("shared-db", notice)
        self.assertIn("ttl 1800s", notice)
        self.assertEqual(await sweep(self.runtime), 0)  # a flag is claimed once
        self.assertEqual(len(self.wakes("b")), 1)
        self.runtime.route_mentions.assert_awaited()

    async def test_the_waiter_polling_first_is_not_woken_again(self):
        self.take("a")
        self.take("b")
        release_lease(self.db, "a", "shared-db")
        self.assertTrue(self.take("b")["granted"])  # its own poll found the grant
        self.assertEqual(await sweep(self.runtime), 0)
        self.assertEqual(self.wakes("b"), [])

    async def test_expiry_promotes_and_wakes_without_any_poll(self):
        self.take("a", ttl_s=900)
        self.take("b")
        self.clock.now += 899
        self.assertEqual(await sweep(self.runtime), 0)
        self.assertEqual(next_expiry_delay(self.db, self.clock.now), 1)
        self.clock.now += 2  # the holder's TTL has run out
        self.assertEqual(await sweep(self.runtime), 1)
        self.assertTrue(self.holds("b"))
        self.assertFalse(self.holds("a"))
        self.assertEqual(len(self.wakes("b")), 1)

    async def test_expiry_deadline_only_counts_leases_with_a_waiter(self):
        self.take("a", ttl_s=900)
        self.assertIsNone(next_expiry_delay(self.db, self.clock.now))
        self.take("b")
        self.assertEqual(next_expiry_delay(self.db, self.clock.now), 900)
        self.assertEqual(next_expiry_delay(self.db, self.clock.now + 5000), 0)

    async def test_exit_and_detach_free_the_slot_and_wake_the_waiter(self):
        from partyline.memory_contracts import ProcessExit
        from partyline.process_incidents import record_exit

        self.take("a")
        self.take("b")
        evidence = ProcessExit(code=0, reason="exit", limit_bytes=1)
        await record_exit(self.runtime, self.db.get_attachment("a"), evidence)
        self.assertTrue(self.holds("b"))
        await sweep(self.runtime)
        self.assertEqual(len(self.wakes("b")), 1)

        from partyline.line_process_routes import detach_attachment

        self.take("c")
        live = SimpleNamespace(att=self.db.get_attachment("b"), stopped=False)
        on_status = self.runtime.status_callback("b", "line-b", "owner-b")

        async def stop():
            await on_status("exited")

        live.stop = stop
        self.runtime.live["b"] = live
        await detach_attachment(self.runtime, "b")
        self.assertTrue(self.holds("c"))
        await sweep(self.runtime)
        self.assertEqual(len(self.wakes("c")), 1)

    async def test_queue_order_holds_for_shared_and_exclusive_waiters(self):
        self.assertTrue(self.take("a", mode="exclusive")["granted"])
        self.assertFalse(self.take("b", mode="shared")["granted"])
        self.clock.now += 1
        self.assertFalse(self.take("c", mode="shared")["granted"])
        self.clock.now += 1
        self.assertFalse(self.take("d", mode="exclusive")["granted"])
        self.clock.now += 1
        self.assertFalse(self.take("e", mode="shared")["granted"])  # behind the exclusive
        release_attachment_leases(self.db, "a")
        await sweep(self.runtime)
        self.assertEqual([who for who in "bcde" if self.wakes(who)], ["b", "c"])
        self.assertFalse(self.holds("d"))
        release_attachment_leases(self.db, "b")
        await sweep(self.runtime)
        self.assertFalse(self.holds("d"))  # a shared holder remains
        release_attachment_leases(self.db, "c")
        await sweep(self.runtime)
        self.assertEqual([who for who in "de" if self.wakes(who)], ["d"])
        self.assertFalse(self.holds("e"))
        release_attachment_leases(self.db, "d")
        await sweep(self.runtime)
        self.assertTrue(self.holds("e"))
        self.assertEqual(len(self.wakes("e")), 1)

    async def test_a_cancelled_exclusive_waiter_lets_shared_waiters_in(self):
        self.take("a", mode="shared")
        self.take("b", mode="exclusive")
        self.take("c", mode="shared")
        self.assertFalse(self.holds("c"))
        release_lease(self.db, "b", "shared-db")  # the exclusive waiter gives up
        await sweep(self.runtime)
        self.assertTrue(self.holds("c"))
        self.assertEqual(len(self.wakes("c")), 1)

    async def test_a_promoted_waiter_that_is_gone_does_not_keep_the_slot(self):
        self.take("a")
        self.take("b")
        self.take("c")
        self.db.set_attachment_status("b", "exited", "owner-b")
        release_lease(self.db, "a", "shared-db")
        await sweep(self.runtime)
        self.assertFalse(self.holds("b"))
        self.assertTrue(self.holds("c"))
        self.assertEqual(len(self.wakes("c")), 1)

    async def test_the_migration_adds_the_wake_flag_idempotently(self):
        from partyline.lease_schema import MIGRATIONS
        for _ in range(2):
            for statement in MIGRATIONS:
                try:
                    self.db._exec(statement)
                except Exception as exc:
                    self.assertIn("duplicate column", str(exc))

    async def test_the_resource_loop_wakes_a_waiter_on_release(self):
        from partyline.line_resource_routes import run

        woken = asyncio.Event()
        self.runtime.route_mentions = AsyncMock(side_effect=lambda *a, **k: woken.set())
        self.take("a")
        self.take("b")
        loop = asyncio.create_task(run(self.runtime))
        try:
            await asyncio.sleep(0)  # let the loop subscribe
            release_lease(self.db, "a", "shared-db")
            await asyncio.wait_for(woken.wait(), 5)  # event-driven; the bound only fails the test
        finally:
            loop.cancel()
        self.assertEqual(len(self.wakes("b")), 1)


class HolderRouteTest(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.db = Db(os.path.join(self.directory.name, "partyline.db"))
        self.addCleanup(self.db.close)
        self.runtime = ChatRuntime(self.db)
        app = FastAPI()
        install_auth_guard(app, self.db)
        register_lease_routes(app, self.runtime)
        self.client = TestClient(app)
        self.addCleanup(self.client.close)
        self.db.create_conversation("line", "line")
        self.headers = {}
        for who in ("holder", "waiter", "stranger"):
            self.db.add_attachment(who, "line", who, "raw", ["raw"], "/tmp")
            self.db._exec("UPDATE attachments SET status='running' WHERE id=?", (who,))
            self.headers[who] = {"Authorization": "Bearer " + auth_store.ensure_api_token(self.db, who)}

    def holder(self, caller, name="shared-db", **params):
        return self.client.get(f"/api/leases/{name}/holder", params=params,
                               headers=self.headers[caller])

    def test_holder_waiter_and_stranger_get_the_right_answer(self):
        for who in ("holder", "waiter"):
            self.client.post("/api/leases", json={"name": "shared-db", "ttl_s": 900},
                             headers=self.headers[who])
        own = self.holder("holder")
        self.assertEqual(own.status_code, 200, own.text)
        self.assertTrue(own.json()["held"])
        self.assertEqual(own.json()["state"], "held")
        waiting = self.holder("waiter").json()
        self.assertFalse(waiting["held"])
        self.assertEqual(waiting["state"], "waiting")
        stranger = self.holder("stranger").json()
        self.assertFalse(stranger["held"])
        self.assertEqual(stranger["state"], "none")
        # A wrapper outside the process asks about it by attachment id.
        self.assertTrue(self.holder("stranger", attachment="holder").json()["held"])
        self.assertFalse(self.holder("stranger", attachment="waiter").json()["held"])
        self.assertFalse(self.holder("holder", name="other").json()["held"])

    def test_a_released_or_expired_lease_is_not_held(self):
        self.client.post("/api/leases", json={"name": "shared-db", "ttl_s": 900},
                         headers=self.headers["holder"])
        self.db._exec("UPDATE resource_leases SET expires_at=1")  # the TTL ran out
        self.assertFalse(self.holder("holder").json()["held"])

    def test_a_person_must_name_the_process_and_bad_names_are_refused(self):
        self.assertEqual(self.holder("holder", name="bad name").status_code, 422)
        self.assertEqual(self.client.get("/api/leases/x/holder").status_code, 401)


class TaskLeaseTest(TaskFixture):
    def take(self, ident, name="shared-db", mode="exclusive"):
        att = self.db.get_attachment(ident)
        return request_lease(self.db, ident, att["name"], att["conv_id"], name, mode, 900)

    def holds(self, ident):
        return holds_lease(self.db, ident)

    async def approve(self):
        await self.create("captain")
        await request_review(self.runtime, self.worker, self.conv_id,
                             ReviewRequestIn(sha=self.commit(), what="built", where="code"))
        await review_verdict(self.runtime, self.captain, self.conv_id,
                             VerdictIn(verdict="approve", findings="fine"))

    async def test_approval_releases_the_lines_leases_and_says_so(self):
        await self.create("captain")
        worker = self.worker.attachment_id
        self.take(worker)
        self.assertFalse(self.take("captain")["granted"])  # another line queues behind it
        await request_review(self.runtime, self.worker, self.conv_id,
                             ReviewRequestIn(sha=self.commit(), what="built", where="code"))
        self.assertTrue(self.holds(worker))  # review is not settlement
        await review_verdict(self.runtime, self.captain, self.conv_id,
                             VerdictIn(verdict="approve", findings="fine"))
        self.assertEqual(self.row()["status"], "approved")
        self.assertFalse(self.holds(worker))
        self.assertTrue(self.holds("captain"))  # the waiter was promoted
        line = [m["body"] for m in self.db.message_page(self.conv_id, limit=100)[0]
                if "released the leases" in m["body"]]
        self.assertEqual(len(line), 1)
        self.assertIn("shared-db", line[0])
        woken = [m for m in self.db.message_page("root", limit=100)[0]
                 if "is now granted to you" in m["body"]]
        self.assertEqual(len(woken), 1)

    async def test_a_done_task_report_names_the_released_leases(self):
        await self.create("none")
        self.take(self.worker.attachment_id)
        await request_review(self.runtime, self.worker, self.conv_id,
                             ReviewRequestIn(sha=self.commit(), what="built", where="code"))
        self.assertEqual(self.row()["status"], "done")
        self.assertFalse(self.holds(self.worker.attachment_id))
        from partyline.reports import get
        body = get(self.db, self.row()["report_id"])["body"]
        self.assertIn("Released leases held by the task's processes: shared-db", body)

    async def test_a_release_after_approval_is_not_new_work(self):
        await self.approve()
        worker = self.worker.attachment_id
        # Nothing needs a message to release; a late release changes no task state.
        self.assertEqual(release_attachment_leases(self.db, worker), 0)
        self.assertEqual(self.row()["status"], "approved")
        self.assertEqual(self.row()["reopen_noticed"], 0)

    async def test_the_reviewers_leases_are_released_too(self):
        await self.create("inspector")
        await request_review(self.runtime, self.worker, self.conv_id,
                             ReviewRequestIn(sha=self.commit(), what="built", where="code"))
        reviewer = self.row()["reviewer_id"]
        self.take(reviewer)
        freed = await release_for_task(self.runtime, self.row())
        self.assertEqual(freed, ["shared-db"])
        self.assertFalse(self.holds(reviewer))

    async def test_a_done_task_releases_its_claims_on_declared_resources(self):
        await self.create("none")
        worker = self.worker.attachment_id
        self.db._exec("INSERT INTO line_resources VALUES(?,?)", ("root", "gpu"))
        self.db._exec("INSERT INTO line_resource_claims(conv_id,name,attachment_id,note,"
                      "created_at,granted_at,notified) VALUES('root','gpu',?,'',1,1,1)", (worker,))
        self.assertTrue(holds_any_lease(self.db, worker))
        await request_review(self.runtime, self.worker, self.conv_id,
                             ReviewRequestIn(sha=self.commit(), what="built", where="code"))
        self.assertEqual(self.row()["status"], "done")
        self.assertFalse(holds_any_lease(self.db, worker))


class IdleExemptionTest(TaskFixture):
    """A granted lease is long work, not idleness; a queue place is still idle."""

    clock = None

    def reminders(self):
        return [m for m in self.db.message_page(self.conv_id, limit=100)[0]
                if "no hand-off" in m["body"]]

    async def end_turn(self):
        att = self.db.get_attachment(self.worker.attachment_id)
        self.runtime.presence = SimpleNamespace(is_working=lambda ident: False)
        await stall_settle(self.runtime, att)

    async def test_a_granted_holder_is_not_reminded_but_a_waiter_is(self):
        await self.create("captain")
        worker = self.worker.attachment_id
        att = self.db.get_attachment(worker)
        request_lease(self.db, "captain", "captain", "root", "shared-db", "exclusive", 900)
        waiting = request_lease(self.db, worker, att["name"], att["conv_id"],
                                "shared-db", "exclusive", 900)
        self.assertFalse(waiting["granted"])
        self.assertFalse(holds_any_lease(self.db, worker))
        await self.end_turn()
        self.assertEqual(self.row()["stall_stage"], 1)  # queued, so idle-eligible
        self.assertEqual(len(self.reminders()), 1)
        self.db._exec("UPDATE task_reviews SET stall_stage=0,stall_notice_id=NULL WHERE conv_id=?",
                      (self.conv_id,))
        release_attachment_leases(self.db, "captain")  # the waiter is promoted
        self.assertTrue(holds_any_lease(self.db, worker))
        await self.end_turn()
        self.assertEqual(self.row()["stall_stage"], 0)
        self.assertEqual(len(self.reminders()), 1)  # no second reminder for the holder

    async def test_an_expired_lease_does_not_exempt(self):
        await self.create("captain")
        worker = self.worker.attachment_id
        att = self.db.get_attachment(worker)
        request_lease(self.db, worker, att["name"], att["conv_id"], "shared-db", "exclusive", 900)
        self.assertTrue(holds_any_lease(self.db, worker))
        self.db._exec("UPDATE resource_leases SET expires_at=1")
        self.assertFalse(holds_any_lease(self.db, worker))
        await self.end_turn()
        self.assertEqual(self.row()["stall_stage"], 1)


if __name__ == "__main__":
    unittest.main()
