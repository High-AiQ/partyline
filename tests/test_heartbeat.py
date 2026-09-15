"""The lead heartbeat: one pending wake, settled only by real delivery.

Every timing assertion here runs on an injected clock. A test that waits out a
five-minute interval proves the same thing five minutes later, and a test that
shortens the interval to prove it faster is testing a configuration nobody
runs.
"""

import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

from fastapi import FastAPI
from fastapi.testclient import TestClient

from partyline import (auth_store, auth_tokens, heartbeat, heartbeat_scheduler,
                       heartbeat_files, heartbeat_snapshot, heartbeat_wake)
from partyline.auth_guard import install_auth_guard
from partyline.auth_store import ensure_api_token
from partyline.db import Db
from partyline.heartbeat_routes import heartbeat_router
from partyline.hierarchy import create_child_conversation, set_lead, set_parent
from partyline.role_briefing import role_instructions
from partyline.runtime import ChatRuntime

ROOT = "root"
OWNER = "lead-att"


class FakeAdapter:
    """A bare process: pasting is delivery, and it can refuse to paste.

    `accept=False` is the wedged case the whole design turns on — the reminder
    is posted and offered, but the cursor never moves, so the wake stays
    outstanding and no second reminder joins it.
    """

    def __init__(self, att: dict):
        self.att = att
        self.accept = True
        self.delivered: list[dict] = []

    async def deliver(self, messages):
        if not self.accept:
            return False
        self.delivered.extend(messages)
        return None


class HeartbeatFixture(unittest.IsolatedAsyncioTestCase):
    """A root line with a live, appointed manager — the only eligible shape."""

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.db = Db(Path(self.directory.name) / "partyline.db")
        self.runtime = ChatRuntime(self.db)
        self.runtime.broadcast = AsyncMock()
        self.runtime.route_mentions = AsyncMock()
        self.db.create_conversation(ROOT, "Root")
        self.db.add_attachment(
            OWNER, ROOT, "astra", "raw", ["sh"], self.directory.name, "owner"
        )
        self.db.set_attachment_status(OWNER, "running", "owner")
        set_lead(self.db, ROOT, OWNER)
        self.adapter = FakeAdapter(self.db.get_attachment(OWNER))
        self.runtime.live[OWNER] = self.adapter
        self.runtime.activation_matches = lambda adapter, att: adapter is self.adapter
        self.now = 1_000.0

    def tearDown(self):
        self.db.close()
        self.directory.cleanup()

    def enable(self, **kwargs):
        """Wake on the clock, which is what the lifecycle tests are about.

        Quiet suppression is a separate decision with its own tests; leaving it
        on here would make every wake-lifecycle test depend on room activity
        and prove nothing about the lifecycle.
        """
        kwargs.setdefault("quiet_if_unchanged", False)
        return heartbeat.enable(self.db, ROOT, OWNER, now=self.now, **kwargs)

    def saved(self, message_id: int) -> dict:
        """The snapshot the reminder pointed at, fetched the way a lead would."""
        body = self.body(message_id)
        digest = [word for word in body.split() if word.startswith("sha256:")][0]
        payload = heartbeat_files.read(self.db.path, digest)
        self.assertIsNotNone(payload, f"the pointer named a missing file: {digest}")
        return payload

    def body(self, message_id: int) -> str:
        return [m for m in self.db.list_messages(ROOT) if m["id"] == message_id][0]["body"]

    def snapshot(self, db=None):
        """Whatever the delta happens to be; these tests are about the wake."""
        return heartbeat_snapshot.build(db or self.db, ROOT, 0)

    async def tick(self, advance: float = 0.0):
        self.now += advance
        return await heartbeat_scheduler.tick(self.runtime, now=self.now)

    def deliver(self, message_id: int, att_id: str = OWNER):
        """What a real delivery does to the cursor, and nothing more."""
        self.db.set_last_seen(att_id, message_id, "owner")


class IntervalTest(HeartbeatFixture):
    async def test_nothing_fires_before_the_first_interval_elapses(self):
        self.enable()

        self.assertIsNone(await self.tick(heartbeat.DEFAULT_INTERVAL - 1))

        first = await self.tick(1)
        self.assertIsNotNone(first)

    async def test_the_reminder_names_the_owner_and_grants_nothing(self):
        self.enable(goal="finish the three books")

        message_id = await self.tick(heartbeat.DEFAULT_INTERVAL)

        posted = [m for m in self.db.list_messages(ROOT) if m["id"] == message_id]
        body = posted[0]["body"]
        self.assertIn("@astra", body)
        self.assertIn("finish the three books", body)
        self.assertIn("No reply is needed", body)
        self.assertIn("authorizes no spending", body)

    async def test_the_interval_is_bounded_and_defaults(self):
        # Pinned to the value Greg asked for. Every other assertion uses the
        # symbol, so without this the default could drift unnoticed.
        self.assertEqual(heartbeat.DEFAULT_INTERVAL, 900.0, "fifteen minutes")
        self.assertEqual(heartbeat.normalize_interval(None), heartbeat.DEFAULT_INTERVAL)
        for bad in (0, 59.9, 3600.1, float("nan"), float("inf"), "soon"):
            with self.subTest(bad=bad), self.assertRaises(heartbeat.HeartbeatError):
                heartbeat.normalize_interval(bad)
        self.assertEqual(heartbeat.normalize_interval(60), 60.0)

    async def test_a_long_outage_produces_one_reminder_not_a_backlog(self):
        """A suspended host must not owe an hour of identical reminders."""
        self.enable()

        first = await self.tick(heartbeat.DEFAULT_INTERVAL * 20)
        self.assertIsNotNone(first)
        self.deliver(first)

        self.assertIsNone(await self.tick(1), "the missed intervals are not owed")
        self.assertIsNotNone(await self.tick(heartbeat.DEFAULT_INTERVAL))


class OnePendingWakeTest(HeartbeatFixture):
    async def test_a_second_reminder_waits_for_the_first_to_be_delivered(self):
        self.enable()
        self.adapter.accept = False  # offered, never pasted
        first = await self.tick(heartbeat.DEFAULT_INTERVAL)
        self.assertIsNotNone(first)

        for _ in range(5):
            self.assertIsNone(
                await self.tick(heartbeat.DEFAULT_INTERVAL),
                "an undelivered reminder must not be joined by another",
            )
        self.assertTrue(heartbeat.status(self.db)["wake_pending"])

        self.adapter.accept = True
        self.assertIsNone(await self.tick(1), "the outstanding one is delivered first")
        self.assertIsNotNone(await self.tick(heartbeat.DEFAULT_INTERVAL))

    async def test_a_paste_that_never_reached_the_cursor_does_not_settle(self):
        """Posting is not delivery. Only the durable cursor settles a wake."""
        self.enable()
        self.adapter.accept = False
        first = await self.tick(heartbeat.DEFAULT_INTERVAL)

        # The room saw it and the adapter was offered it; the cursor did not move.
        self.runtime.broadcast.assert_awaited()
        self.assertEqual(self.db.get_attachment(OWNER)["last_seen"], 0)

        self.assertIsNone(await self.tick(heartbeat.DEFAULT_INTERVAL))
        self.assertEqual(heartbeat.status(self.db)["pending_message_id"], first)

        self.deliver(first - 1)
        self.assertIsNone(
            await self.tick(heartbeat.DEFAULT_INTERVAL),
            "a cursor short of the reminder has not delivered it",
        )

        self.deliver(first)
        self.assertFalse(heartbeat_wake.settle_delivered(self.db)["pending_message_id"])

    async def test_a_committed_reminder_is_retried_not_replaced(self):
        """The crash case: the row names the exact message that is owed."""
        self.enable()
        self.adapter.accept = False
        first = await self.tick(heartbeat.DEFAULT_INTERVAL)

        self.adapter.accept = True
        self.assertIsNone(await self.tick(heartbeat.DEFAULT_INTERVAL * 3))

        self.assertEqual(
            [message["id"] for message in self.adapter.delivered], [first],
            "the same reminder was delivered, and no second one was written",
        )
        self.assertFalse(heartbeat.status(self.db)["wake_pending"])

    async def test_concurrent_ticks_produce_exactly_one_reminder(self):
        import asyncio

        self.enable()
        self.now += heartbeat.DEFAULT_INTERVAL

        results = await asyncio.gather(
            *(heartbeat_scheduler.tick(self.runtime, now=self.now) for _ in range(8))
        )

        posted = [value for value in results if value is not None]
        self.assertEqual(len(posted), 1, f"one reminder, got {posted}")

    async def test_a_restart_mid_flight_does_not_duplicate_the_wake(self):
        """The pending mark is in the row, so a fresh process still sees it."""
        self.enable()
        self.adapter.accept = False
        first = await self.tick(heartbeat.DEFAULT_INTERVAL)

        reopened = Db(Path(self.directory.name) / "partyline.db")
        try:
            self.assertEqual(
                heartbeat.status(reopened)["pending_message_id"],
                first,
                "a restart must not forget an outstanding reminder",
            )
            self.assertIsNone(
                heartbeat_wake.post_due_reminder(
                    reopened, self.now + 10_000, sender="system",
                    snapshot=self.snapshot(reopened), snapshot_hash="sha256:x",
                    body_for=lambda row, delta: "should never be written",
                )
            )
        finally:
            reopened.close()


class OwnerTest(HeartbeatFixture):
    async def test_a_detached_owner_pauses_rather_than_redirecting(self):
        self.enable()
        self.db.set_attachment_status(OWNER, "detached", "owner")

        self.assertIsNone(await self.tick(heartbeat.DEFAULT_INTERVAL * 3))
        self.assertEqual(self.db.list_messages(ROOT), [])

        self.db.set_attachment_status(OWNER, "running", "owner")
        self.assertIsNotNone(await self.tick(1), "the same owner resumes on return")

    async def test_losing_the_lead_pauses_and_never_wakes_the_replacement(self):
        self.enable()
        self.db.add_attachment(
            "other", ROOT, "someone", "raw", ["sh"], self.directory.name, "owner"
        )
        self.db.set_attachment_status("other", "running", "owner")
        self.runtime.live["other"] = self.adapter
        set_lead(self.db, ROOT, "other")

        self.assertIsNone(await self.tick(heartbeat.DEFAULT_INTERVAL * 3))
        self.assertEqual(self.db.list_messages(ROOT), [])

    async def test_a_pending_wake_survives_the_pause_for_its_own_owner(self):
        self.enable()
        self.adapter.accept = False
        first = await self.tick(heartbeat.DEFAULT_INTERVAL)
        self.db.set_attachment_status(OWNER, "detached", "owner")

        await self.tick(heartbeat.DEFAULT_INTERVAL)
        self.assertEqual(heartbeat.status(self.db)["pending_message_id"], first)

        self.db.set_attachment_status(OWNER, "running", "owner")
        self.deliver(first)
        self.assertIsNotNone(await self.tick(heartbeat.DEFAULT_INTERVAL))

    async def test_a_dead_adapter_is_not_delivery(self):
        self.enable()
        self.runtime.live.pop(OWNER)

        self.assertIsNone(await self.tick(heartbeat.DEFAULT_INTERVAL * 2))

    async def test_only_a_root_lead_is_eligible(self):
        self.assertTrue(heartbeat.is_root_lead(self.db, ROOT, OWNER))
        self.assertFalse(heartbeat.is_root_lead(self.db, ROOT, "someone-else"))
        self.assertFalse(heartbeat.is_root_lead(self.db, None, OWNER))
        self.assertFalse(heartbeat.is_root_lead(self.db, "missing", OWNER))

        create_child_conversation(self.db, ROOT, "child", "Child")
        self.db.add_attachment(
            "child-att", "child", "worker", "raw", ["sh"], self.directory.name, "owner"
        )
        set_lead(self.db, "child", "child-att")
        self.assertFalse(
            heartbeat.is_root_lead(self.db, "child", "child-att"),
            "a child manager is not the root manager",
        )


class RaceTest(HeartbeatFixture):
    """What happens between a reminder falling due and having been received."""

    async def test_a_second_connection_reconfiguring_after_the_write_wins(self):
        """The interleaving the generation column exists for.

        A reminder is committed and pending. Another connection — a second
        server process, or an operator's helper — disables and re-enables the
        monitor. The old reminder must not be carried into the new
        configuration as its outstanding wake.
        """
        self.enable()
        self.adapter.accept = False
        stale = await self.tick(heartbeat.DEFAULT_INTERVAL)
        self.assertEqual(heartbeat.status(self.db)["pending_message_id"], stale)

        elsewhere = Db(Path(self.directory.name) / "partyline.db")
        try:
            before = heartbeat.get(elsewhere)["generation"]
            heartbeat.disable(elsewhere)
            heartbeat.enable(
                elsewhere, ROOT, OWNER, goal="a different goal", now=self.now,
                quiet_if_unchanged=False,
            )
            after = heartbeat.get(elsewhere)["generation"]
        finally:
            elsewhere.close()

        self.assertGreater(after, before + 1, "disable and enable each advanced it")
        self.assertFalse(
            heartbeat.status(self.db)["wake_pending"],
            "the previous configuration's reminder is not this one's wake",
        )

        self.adapter.accept = True
        fresh = await self.tick(heartbeat.DEFAULT_INTERVAL)
        self.assertIsNotNone(fresh)
        self.assertNotEqual(fresh, stale, "a new configuration posts its own reminder")
        self.assertIn("a different goal", self.adapter.delivered[-1]["body"])

    async def test_a_concurrent_disable_never_leaves_a_torn_row(self):
        """Whoever wins, the row is never pending on a message that isn't there."""
        import threading

        self.enable()
        self.now += heartbeat.DEFAULT_INTERVAL
        elsewhere = Db(Path(self.directory.name) / "partyline.db")
        started = threading.Event()

        def disable_elsewhere():
            started.wait(timeout=5)
            heartbeat.disable(elsewhere)

        worker = threading.Thread(target=disable_elsewhere)
        worker.start()
        try:
            started.set()
            posted = heartbeat_wake.post_due_reminder(
                self.db, self.now, sender="system",
                snapshot=self.snapshot(), snapshot_hash="sha256:x",
                body_for=lambda row, delta: heartbeat.wake_body("astra", row["goal"]),
            )
        finally:
            worker.join(timeout=5)
            elsewhere.close()

        row = heartbeat.get(self.db)
        pending = row["pending_message_id"]
        if pending is not None:
            self.assertEqual(pending, posted[0]["id"])
            ids = [message["id"] for message in self.db.list_messages(ROOT)]
            self.assertIn(pending, ids, "pending always names a message that exists")

    async def _tick_with_paused_broadcast(self, interfere):
        """Freeze the tick inside its broadcast await, interfere, then resume.

        The window the review found: ownership was checked before this await
        and delivery happened after it, with nothing in between re-reading the
        row. Anything that can change during an await must be proved here.
        """
        import asyncio

        entered = asyncio.Event()
        resume = asyncio.Event()

        async def paused_broadcast(*_args, **_kwargs):
            entered.set()
            await resume.wait()

        self.runtime.broadcast = paused_broadcast
        self.now += heartbeat.DEFAULT_INTERVAL
        running = asyncio.create_task(
            heartbeat_scheduler.tick(self.runtime, now=self.now)
        )
        await asyncio.wait_for(entered.wait(), timeout=5)

        elsewhere = Db(Path(self.directory.name) / "partyline.db")
        try:
            interfere(elsewhere)
        finally:
            elsewhere.close()

        resume.set()
        return await asyncio.wait_for(running, timeout=5)

    async def test_a_disable_during_the_broadcast_await_stops_delivery(self):
        self.enable()

        await self._tick_with_paused_broadcast(heartbeat.disable)

        self.assertEqual(
            self.adapter.delivered, [], "the old tick delivered for a dead monitor"
        )
        self.assertEqual(self.db.get_attachment(OWNER)["last_seen"], 0)

    async def test_a_reconfigure_during_the_broadcast_await_stops_delivery(self):
        self.enable()

        def reconfigure(elsewhere):
            heartbeat.disable(elsewhere)
            heartbeat.enable(
                elsewhere, ROOT, OWNER, goal="a different goal", now=self.now,
                quiet_if_unchanged=False,
            )

        await self._tick_with_paused_broadcast(reconfigure)

        self.assertEqual(self.adapter.delivered, [])
        self.assertFalse(
            heartbeat.status(self.db)["wake_pending"],
            "the superseded reminder is not the new configuration's wake",
        )

    async def test_detaching_during_the_broadcast_await_stops_delivery(self):
        self.enable()

        await self._tick_with_paused_broadcast(
            lambda elsewhere: elsewhere.set_attachment_status(
                OWNER, "detached", "owner"
            )
        )

        self.assertEqual(self.adapter.delivered, [])

    async def test_a_removed_attachment_during_the_await_is_survivable(self):
        """The owner's row can be gone entirely by the time delivery runs."""
        self.enable()

        def remove(elsewhere):
            elsewhere.set_attachment_status(OWNER, "detached", "owner")
            with elsewhere.lock:
                elsewhere.conn.execute("DELETE FROM attachments WHERE id=?", (OWNER,))
                elsewhere.conn.commit()

        await self._tick_with_paused_broadcast(remove)

        self.assertEqual(self.adapter.delivered, [])

    async def _tick_paused_at_delivery(self, interfere):
        """Freeze the tick on the way into delivery, interfere, then resume.

        Grok's probe: pausing at `broadcast` leaves a later window, because
        `deliver_pending` itself awaits before it reserves and pastes. The
        interference lands between the scheduler's own check and the paste,
        which is the only place a guard taken inside the reservation can save.
        """
        import asyncio

        entered = asyncio.Event()
        resume = asyncio.Event()
        original = self.runtime.deliver_pending

        async def paused_deliver(*args, **kwargs):
            entered.set()
            await resume.wait()
            return await original(*args, **kwargs)

        self.runtime.deliver_pending = paused_deliver
        self.now += heartbeat.DEFAULT_INTERVAL
        running = asyncio.create_task(
            heartbeat_scheduler.tick(self.runtime, now=self.now)
        )
        await asyncio.wait_for(entered.wait(), timeout=5)

        elsewhere = Db(Path(self.directory.name) / "partyline.db")
        try:
            interfere(elsewhere)
        finally:
            elsewhere.close()

        resume.set()
        return await asyncio.wait_for(running, timeout=5)

    async def test_a_disable_at_the_reservation_boundary_stops_the_paste(self):
        self.enable()

        await self._tick_paused_at_delivery(heartbeat.disable)

        self.assertEqual(self.adapter.delivered, [], "nothing was pasted")
        self.assertEqual(
            self.db.get_attachment(OWNER)["last_seen"], 0, "the cursor did not move"
        )

    async def test_a_reconfigure_at_the_reservation_boundary_stops_the_paste(self):
        self.enable()

        def reconfigure(elsewhere):
            heartbeat.disable(elsewhere)
            heartbeat.enable(
                elsewhere, ROOT, OWNER, goal="a different goal", now=self.now,
                quiet_if_unchanged=False,
            )

        await self._tick_paused_at_delivery(reconfigure)

        self.assertEqual(self.adapter.delivered, [])
        self.assertEqual(self.db.get_attachment(OWNER)["last_seen"], 0)

    async def test_losing_the_lead_at_the_reservation_boundary_stops_the_paste(self):
        self.enable()
        self.db.add_attachment(
            "usurper", ROOT, "someone", "raw", ["sh"], self.directory.name, "owner"
        )

        await self._tick_paused_at_delivery(
            lambda elsewhere: set_lead(elsewhere, ROOT, "usurper")
        )

        self.assertEqual(self.adapter.delivered, [])

    async def test_detaching_at_the_reservation_boundary_stops_the_paste(self):
        """Detach changes the attachment, not the row: the guard asks both."""
        self.enable()

        await self._tick_paused_at_delivery(
            lambda elsewhere: elsewhere.set_attachment_status(
                OWNER, "detached", "owner"
            )
        )

        self.assertEqual(self.adapter.delivered, [])
        self.assertEqual(self.db.get_attachment(OWNER)["last_seen"], 0)

    async def test_a_dead_adapter_at_the_reservation_boundary_stops_the_paste(self):
        self.enable()

        def unregister(_elsewhere):
            self.runtime.live.pop(OWNER)

        await self._tick_paused_at_delivery(unregister)

        self.assertEqual(self.adapter.delivered, [])

    async def test_a_replacement_adapter_at_the_boundary_never_gets_the_paste(self):
        """A new process adopting the row is not the reader this reminder had."""
        self.enable()
        replacement = FakeAdapter(self.db.get_attachment(OWNER))

        def swap(_elsewhere):
            self.runtime.live[OWNER] = replacement

        await self._tick_paused_at_delivery(swap)

        self.assertEqual(replacement.delivered, [], "the replacement was not woken")
        self.assertEqual(self.adapter.delivered, [])
        self.assertEqual(self.db.get_attachment(OWNER)["last_seen"], 0)

    async def test_a_pause_at_the_boundary_keeps_the_reminder_for_its_owner(self):
        """Pausing is not cancelling: the same wake is still owed, to the same
        process, and is delivered when it comes back."""
        self.enable()

        posted = await self._tick_paused_at_delivery(
            lambda elsewhere: elsewhere.set_attachment_status(
                OWNER, "detached", "owner"
            )
        )

        self.assertEqual(heartbeat.status(self.db)["pending_message_id"], posted)

        self.db.set_attachment_status(OWNER, "running", "owner")
        self.assertIsNone(await self.tick(1))
        self.assertEqual([m["id"] for m in self.adapter.delivered], [posted])
        self.assertFalse(heartbeat.status(self.db)["wake_pending"])

    async def test_an_undisturbed_delivery_still_pastes_and_settles(self):
        """The guard must not become a reason nothing is ever delivered."""
        self.enable()

        posted = await self._tick_paused_at_delivery(lambda _elsewhere: None)

        self.assertEqual([m["id"] for m in self.adapter.delivered], [posted])
        self.assertFalse(heartbeat.status(self.db)["wake_pending"])

    async def test_a_reminder_due_but_disabled_first_is_never_written(self):
        """Enabled, pending and due are all re-read inside the write itself."""
        self.enable()
        self.now += heartbeat.DEFAULT_INTERVAL
        heartbeat.disable(self.db)

        posted = heartbeat_wake.post_due_reminder(
            self.db, self.now, sender="system",
            snapshot=self.snapshot(), snapshot_hash="sha256:x",
            body_for=lambda row, delta: "should never be written",
        )

        self.assertIsNone(posted)
        self.assertEqual(self.db.list_messages(ROOT), [])

    async def test_a_reminder_whose_owner_changed_in_flight_is_left_unowned(self):
        self.enable()
        self.adapter.accept = False

        posted = await self.tick(heartbeat.DEFAULT_INTERVAL)

        # The message and its pending reference are written together, so
        # there is no state in which one exists without the other.
        self.assertIsNotNone(posted)
        self.assertEqual(heartbeat.status(self.db)["pending_message_id"], posted)

    async def test_an_owner_on_another_line_is_never_deliverable(self):
        row = dict(heartbeat.get(self.db) or {}, conv_id="somewhere-else",
                   attachment_id=OWNER)

        self.assertIsNone(heartbeat_scheduler.deliverable_owner(self.runtime, row))


class GoalRoutingTest(HeartbeatFixture):
    """The goal is the lead's own text, so it must not be able to ring the room."""

    def setUp(self):
        super().setUp()
        self.db.add_attachment(
            "bystander", ROOT, "grok", "raw", ["sh"], self.directory.name, "owner"
        )
        self.db.set_attachment_status("bystander", "running", "owner")
        self.other = FakeAdapter(self.db.get_attachment("bystander"))
        self.runtime.live["bystander"] = self.other
        matches = self.runtime.activation_matches
        self.runtime.activation_matches = lambda adapter, att: (
            adapter is self.other or matches(adapter, att)
        )

    async def test_a_goal_naming_all_wakes_nobody_else(self):
        self.enable(goal="@all drop everything and render the covers")

        posted = await self.tick(heartbeat.DEFAULT_INTERVAL)

        self.assertEqual(
            [message["id"] for message in self.adapter.delivered], [posted],
            "the owner received its own reminder",
        )
        self.assertEqual(self.other.delivered, [], "and nobody else did")
        self.assertEqual(self.db.get_attachment("bystander")["last_seen"], 0)

    async def test_a_goal_naming_another_handle_wakes_nobody_else(self):
        self.enable(goal="chase @grok about the raw submit path")

        await self.tick(heartbeat.DEFAULT_INTERVAL)

        self.assertEqual(self.other.delivered, [])

    async def test_the_reminder_is_never_handed_to_the_mention_router(self):
        """Mention routing is the mechanism that would honour `@all`."""
        self.enable(goal="@all")

        await self.tick(heartbeat.DEFAULT_INTERVAL)

        self.runtime.route_mentions.assert_not_awaited()


class RootRevalidationTest(HeartbeatFixture):
    async def test_a_line_that_gains_a_parent_stops_being_eligible(self):
        """Root is a runtime fact: a line can be linked under another later."""
        self.enable()
        self.db.create_conversation("new-parent", "Parent")
        set_parent(self.db, ROOT, "new-parent")

        self.assertIsNone(await self.tick(heartbeat.DEFAULT_INTERVAL * 3))
        self.assertEqual(self.db.list_messages(ROOT), [])

        set_parent(self.db, ROOT, None)
        self.assertIsNotNone(await self.tick(1), "and eligible again when unlinked")


class TwoRootLinesTest(HeartbeatFixture):
    """One database, two unrelated root managers, one singleton monitor."""

    def setUp(self):
        super().setUp()
        self.db.create_conversation("other-root", "Other Root")
        self.db.add_attachment(
            "other-lead", "other-root", "sol", "raw", ["sh"],
            self.directory.name, "owner",
        )
        self.db.set_attachment_status("other-lead", "running", "owner")
        set_lead(self.db, "other-root", "other-lead")
        app = FastAPI()
        install_auth_guard(app, self.db)
        app.include_router(heartbeat_router(self.runtime))
        self.client = TestClient(app)

    def tearDown(self):
        self.client.close()
        super().tearDown()

    def as_attachment(self, att_id: str):
        self.client.headers["Authorization"] = (
            f"Bearer {ensure_api_token(self.db, att_id)}"
        )

    async def test_the_other_root_lead_can_neither_read_replace_nor_disable_it(self):
        self.as_attachment(OWNER)
        self.assertEqual(
            self.client.post("/api/heartbeat", json={"goal": "mine"}).status_code, 200
        )

        self.as_attachment("other-lead")
        self.assertEqual(self.client.get("/api/heartbeat").status_code, 403)
        self.assertEqual(self.client.post("/api/heartbeat", json={}).status_code, 403)
        self.assertEqual(self.client.delete("/api/heartbeat").status_code, 403)

        self.as_attachment(OWNER)
        state = self.client.get("/api/heartbeat").json()
        self.assertEqual(state["goal"], "mine")
        self.assertEqual(state["attachment_id"], OWNER)

    async def test_an_unconfigured_monitor_may_be_claimed_by_either_root_lead(self):
        self.as_attachment("other-lead")

        self.assertEqual(self.client.get("/api/heartbeat").status_code, 200)
        self.assertEqual(self.client.post("/api/heartbeat", json={}).status_code, 200)
        self.assertEqual(
            self.client.get("/api/heartbeat").json()["attachment_id"], "other-lead"
        )

    async def test_a_switched_off_monitor_may_be_claimed_by_the_other_root_lead(self):
        self.as_attachment(OWNER)
        self.client.post("/api/heartbeat", json={"goal": "mine"})
        self.assertFalse(self.client.delete("/api/heartbeat").json()["enabled"])

        self.as_attachment("other-lead")
        self.assertEqual(self.client.get("/api/heartbeat").status_code, 200)
        claimed = self.client.post("/api/heartbeat", json={"goal": "theirs"})
        self.assertEqual(claimed.status_code, 200, claimed.text)
        self.assertEqual(claimed.json()["attachment_id"], "other-lead")

    async def test_a_monitor_whose_owner_is_gone_may_be_claimed(self):
        # The dogfood shape: the row pointed at an attachment that had been
        # deleted from an archived root line, and every new root captain got 403.
        self.as_attachment(OWNER)
        self.client.post("/api/heartbeat", json={"goal": "mine"})
        self.db._exec("DELETE FROM attachments WHERE id=?", (OWNER,))

        self.as_attachment("other-lead")
        self.assertEqual(self.client.get("/api/heartbeat").status_code, 200)
        self.assertEqual(self.client.post("/api/heartbeat", json={}).status_code, 200)
        self.assertEqual(
            self.client.get("/api/heartbeat").json()["attachment_id"], "other-lead"
        )

    async def test_a_person_may_still_switch_off_a_monitor_they_do_not_own(self):
        self.as_attachment(OWNER)
        self.client.post("/api/heartbeat", json={})

        user = auth_store.create_user(
            self.db, "greg@example.com", "greg",
            auth_tokens.hash_password("hunter2222"),
        )
        self.client.headers["Authorization"] = (
            f"Bearer {auth_tokens.create_access_token(auth_tokens.signing_secret(self.db), user['id'])}"
        )

        self.assertFalse(self.client.delete("/api/heartbeat").json()["enabled"])


class DisableTest(HeartbeatFixture):
    async def test_disable_clears_the_pending_wake_and_stops_reminders(self):
        self.enable()
        await self.tick(heartbeat.DEFAULT_INTERVAL)

        state = heartbeat.disable(self.db)

        self.assertFalse(state["enabled"])
        self.assertIsNone(state["pending_message_id"])
        self.assertIsNone(await self.tick(heartbeat.DEFAULT_INTERVAL * 5))

    async def test_re_enabling_keeps_no_stale_wake_and_restarts_the_interval(self):
        self.enable()
        await self.tick(heartbeat.DEFAULT_INTERVAL)
        heartbeat.disable(self.db)

        self.enable()
        status = heartbeat.status(self.db, now=self.now)
        self.assertTrue(status["enabled"])
        self.assertFalse(status["wake_pending"])
        self.assertAlmostEqual(status["seconds_until_due"], heartbeat.DEFAULT_INTERVAL)

    async def test_idleness_never_disables_it(self):
        """Completion is an explicit act; a quiet room is not evidence of it."""
        self.enable()
        for _ in range(10):
            posted = await self.tick(heartbeat.DEFAULT_INTERVAL)
            if posted is not None:
                self.deliver(posted)

        self.assertTrue(heartbeat.status(self.db)["enabled"])


class StatusTest(HeartbeatFixture):
    async def test_status_reports_state_interval_due_time_and_pending(self):
        self.assertEqual(
            heartbeat.status(self.db, now=self.now),
            {
                "enabled": False, "conv_id": None, "attachment_id": None,
                "interval_seconds": heartbeat.DEFAULT_INTERVAL, "goal": None,
                "next_due_at": None, "seconds_until_due": None,
                "wake_pending": False, "pending_message_id": None,
                "since_id": 0, "snapshot_hash": None, "quiet_wakes": 0,
                "quiet_if_unchanged": True,
            },
        )

        self.enable(interval_seconds=120, goal="ship the books")
        status = heartbeat.status(self.db, now=self.now)
        self.assertEqual(status["enabled"], True)
        self.assertEqual(status["interval_seconds"], 120.0)
        self.assertEqual(status["goal"], "ship the books")
        self.assertEqual(status["next_due_at"], self.now + 120)
        self.assertEqual(status["seconds_until_due"], 120.0)
        self.assertFalse(status["wake_pending"])

        self.adapter.accept = False
        posted = await self.tick(120)
        status = heartbeat.status(self.db, now=self.now)
        self.assertTrue(status["wake_pending"])
        self.assertEqual(status["pending_message_id"], posted)

    async def test_seconds_until_due_never_goes_negative(self):
        self.enable()
        self.assertEqual(
            heartbeat.status(self.db, now=self.now + 10_000)["seconds_until_due"], 0.0
        )

    async def test_the_goal_is_bounded_and_persisted(self):
        with self.assertRaises(heartbeat.HeartbeatError):
            heartbeat.normalize_goal("   ")
        with self.assertRaises(heartbeat.HeartbeatError):
            heartbeat.normalize_goal("x" * (heartbeat.MAX_GOAL + 1))

        self.enable(goal="  keep the trucks moving  ")
        reopened = Db(Path(self.directory.name) / "partyline.db")
        try:
            self.assertEqual(
                heartbeat.status(reopened)["goal"], "keep the trucks moving"
            )
        finally:
            reopened.close()


class BriefingTest(unittest.TestCase):
    def test_only_a_root_manager_is_told_about_the_heartbeat(self):
        actions = ["assign", "create_child", "read_reports", "report"]

        root = role_instructions(actions, ROOT, None)
        self.assertIn("POST /api/heartbeat", root)
        self.assertIn("DELETE /api/heartbeat", root)
        self.assertIn("authorizes no", root)

        self.assertNotIn("/api/heartbeat", role_instructions(actions, "child", ROOT))
        self.assertNotIn("/api/heartbeat", role_instructions(["read", "write"], ROOT, None))


class RouteTest(HeartbeatFixture):
    def setUp(self):
        super().setUp()
        app = FastAPI()
        install_auth_guard(app, self.db)
        app.include_router(heartbeat_router(self.runtime))
        self.client = TestClient(app)
        self.owner_token = ensure_api_token(self.db, OWNER)
        self.client.headers["Authorization"] = f"Bearer {self.owner_token}"

    def tearDown(self):
        self.client.close()
        super().tearDown()

    def human(self):
        user = auth_store.create_user(
            self.db, "greg@example.com", "greg",
            auth_tokens.hash_password("hunter2222"),
        )
        return auth_tokens.create_access_token(
            auth_tokens.signing_secret(self.db), user["id"]
        )

    async def test_the_root_lead_enables_reads_and_disables_its_own(self):
        response = self.client.post("/api/heartbeat", json={"interval_seconds": 600})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["interval_seconds"], 600.0)
        self.assertEqual(response.json()["attachment_id"], OWNER)

        self.assertTrue(self.client.get("/api/heartbeat").json()["enabled"])
        self.assertFalse(self.client.delete("/api/heartbeat").json()["enabled"])

    async def test_a_bad_interval_is_refused_without_changing_anything(self):
        self.client.post("/api/heartbeat", json={"interval_seconds": 600})

        self.assertEqual(
            self.client.post("/api/heartbeat", json={"interval_seconds": 5}).status_code,
            400,
        )
        self.assertEqual(self.client.get("/api/heartbeat").json()["interval_seconds"], 600.0)

    async def test_a_non_root_machine_cannot_read_or_arm_it(self):
        create_child_conversation(self.db, ROOT, "child", "Child")
        self.db.add_attachment(
            "child-att", "child", "worker", "raw", ["sh"], self.directory.name, "owner"
        )
        set_lead(self.db, "child", "child-att")
        self.client.headers["Authorization"] = (
            f"Bearer {ensure_api_token(self.db, 'child-att')}"
        )

        for call in (
            lambda: self.client.get("/api/heartbeat"),
            lambda: self.client.post("/api/heartbeat", json={}),
            lambda: self.client.delete("/api/heartbeat"),
        ):
            self.assertEqual(call().status_code, 403)

    async def test_a_human_may_read_and_switch_it_off_but_not_own_one(self):
        self.client.post("/api/heartbeat", json={})
        self.client.headers["Authorization"] = f"Bearer {self.human()}"

        self.assertTrue(self.client.get("/api/heartbeat").json()["enabled"])
        self.assertEqual(self.client.post("/api/heartbeat", json={}).status_code, 403)
        self.assertFalse(self.client.delete("/api/heartbeat").json()["enabled"])

    async def test_an_unauthenticated_caller_is_refused(self):
        self.client.headers.pop("Authorization")

        self.assertEqual(self.client.get("/api/heartbeat").status_code, 401)

    async def test_the_status_endpoint_returns_the_same_delta_without_posting(self):
        """An operator can see what the monitor is reacting to, for free."""
        self.client.post("/api/heartbeat", json={})
        self.db.add_message(ROOT, "greg", "human", "something to report")

        response = self.client.get("/api/heartbeat/status")

        self.assertEqual(response.status_code, 200, response.text)
        payload = response.json()
        self.assertTrue(payload["actionable"])
        self.assertEqual(payload["snapshot"]["lines"][0]["senders"], ["greg"])
        self.assertTrue(payload["hash"].startswith("sha256:"))
        self.assertNotIn("something to report", response.text)
        self.assertEqual(
            [m for m in self.db.list_messages(ROOT) if m["sender_type"] == "system"],
            [], "reading the snapshot posts nothing",
        )

    async def test_the_status_endpoint_is_404_before_anything_is_configured(self):
        self.assertEqual(self.client.get("/api/heartbeat/status").status_code, 404)

    async def test_the_status_endpoint_refuses_another_lines_manager(self):
        self.client.post("/api/heartbeat", json={})
        create_child_conversation(self.db, ROOT, "child", "Child")
        self.db.add_attachment(
            "child-att", "child", "worker", "raw", ["sh"], self.directory.name, "owner"
        )
        set_lead(self.db, "child", "child-att")
        self.client.headers["Authorization"] = (
            f"Bearer {ensure_api_token(self.db, 'child-att')}"
        )

        self.assertEqual(self.client.get("/api/heartbeat/status").status_code, 403)

    async def test_an_unknown_field_is_refused(self):
        response = self.client.post(
            "/api/heartbeat", json={"interval_seconds": 300, "attachment_id": "someone"}
        )

        self.assertEqual(response.status_code, 422, "the owner is never a parameter")


class ContinuityTest(HeartbeatFixture):
    async def test_the_row_survives_a_restart_with_its_schedule_intact(self):
        self.enable(interval_seconds=600, goal="see the release through")

        reopened = Db(Path(self.directory.name) / "partyline.db")
        try:
            status = heartbeat.status(reopened, now=self.now)
            self.assertTrue(status["enabled"])
            self.assertEqual(status["interval_seconds"], 600.0)
            self.assertEqual(status["goal"], "see the release through")
            self.assertEqual(status["attachment_id"], OWNER)
        finally:
            reopened.close()

    async def test_re_enabling_bumps_the_generation(self):
        first = self.enable()["generation"]
        second = self.enable()["generation"]
        disabled = heartbeat.disable(self.db)["generation"]

        self.assertGreater(second, first, "a re-enable is a new configuration")
        self.assertGreater(disabled, second)


class SchedulerLoopTest(HeartbeatFixture):
    async def test_a_failing_tick_does_not_end_the_monitor(self):
        import asyncio

        calls = []

        async def sleep(_seconds):
            calls.append(1)
            if len(calls) >= 3:
                raise asyncio.CancelledError

        broken = SimpleNamespace(
            db=SimpleNamespace(),
            live={},
        )
        with self.assertRaises(asyncio.CancelledError):
            await heartbeat_scheduler.run(broken, sleep=sleep, clock=lambda: self.now)

        self.assertEqual(len(calls), 3, "the loop kept ticking after failures")


if __name__ == "__main__":
    unittest.main()


class QuietSnapshotTest(HeartbeatFixture):
    """Quiet by default: a wake is earned by the room's state, not the clock.

    The first heartbeat woke its lead sixty times in one night and each wake
    said only what the lead already knew, so the only possible reply was "no
    action taken". These tests are that night, encoded.
    """

    def enable(self, **kwargs):
        kwargs.setdefault("quiet_if_unchanged", True)
        return heartbeat.enable(self.db, ROOT, OWNER, now=self.now, **kwargs)

    async def test_an_unchanged_room_is_never_woken_about(self):
        self.enable()

        for _ in range(20):
            self.assertIsNone(await self.tick(heartbeat.DEFAULT_INTERVAL))

        self.assertEqual(self.db.list_messages(ROOT), [], "nothing was posted")
        self.assertEqual(heartbeat.status(self.db)["quiet_wakes"], 20)

    async def test_a_peer_on_the_root_line_does_not_keep_it_awake(self):
        """Grok's probe: the monitor must not make the room look unread.

        Reminders are delivered to the owner alone, so on the heartbeat's own
        line every peer is behind by the number of wakes posted. Counting those
        keeps `is_actionable` true forever and suppression never fires again —
        and the plain quiet test misses it entirely, because it has no peer.
        """
        peer = FakeAdapter(self.db.add_attachment(
            "peer", ROOT, "grok", "raw", ["sh"], self.directory.name, "owner"
        ))
        self.db.set_attachment_status("peer", "running", "owner")
        self.enable()

        self.db.add_message(ROOT, "greg", "human", "something real")
        first = await self.tick(heartbeat.DEFAULT_INTERVAL)
        self.assertIsNotNone(first)
        self.deliver(first)
        # The peer read the human message but not the owner-only reminder,
        # which is the state every real line is in after a wake.
        self.db.set_last_seen("peer", first - 1, "owner")

        for _ in range(10):
            self.assertIsNone(
                await self.tick(heartbeat.DEFAULT_INTERVAL),
                "a peer behind only by our own reminders is not news",
            )
        self.assertEqual(peer.delivered, [])

    async def test_a_peer_genuinely_behind_is_still_reported(self):
        """The exclusion must not blind the monitor to a real backlog."""
        self.db.add_attachment(
            "peer", ROOT, "grok", "raw", ["sh"], self.directory.name, "owner"
        )
        self.db.set_attachment_status("peer", "running", "owner")
        self.enable()
        self.db.add_message(ROOT, "greg", "human", "@grok please look at this")

        posted = await self.tick(heartbeat.DEFAULT_INTERVAL)

        self.assertIsNotNone(posted)
        agent = self.saved(posted)["lines"][0]["agents"][0]
        self.assertEqual((agent["attachment_id"], agent["unread"]), ("peer", 1))

    async def test_new_speech_earns_exactly_one_wake(self):
        self.enable()
        self.assertIsNone(await self.tick(heartbeat.DEFAULT_INTERVAL))

        self.db.add_message(ROOT, "greg", "human", "a new instruction")
        posted = await self.tick(heartbeat.DEFAULT_INTERVAL)

        self.assertIsNotNone(posted)
        self.assertIn("1 line(s) with new messages", self.body(posted))
        line = self.saved(posted)["lines"][0]
        self.assertEqual((line["new"], line["senders"]), (1, ["greg"]))
        self.deliver(posted)
        self.assertIsNone(
            await self.tick(heartbeat.DEFAULT_INTERVAL),
            "the same news does not earn a second wake",
        )

    async def test_the_monitors_own_reminders_are_not_news(self):
        """Otherwise the heartbeat is permanently actionable because of itself."""
        self.enable()
        self.db.add_message(ROOT, "greg", "human", "something happened")
        first = await self.tick(heartbeat.DEFAULT_INTERVAL)
        self.deliver(first)

        for _ in range(5):
            self.assertIsNone(await self.tick(heartbeat.DEFAULT_INTERVAL))

    async def test_a_quiet_skip_keeps_the_delta_owed(self):
        """A skipped wake must not silently consume what it declined to report."""
        self.enable()
        before = heartbeat.status(self.db)["since_id"]

        await self.tick(heartbeat.DEFAULT_INTERVAL)

        self.assertEqual(heartbeat.status(self.db)["since_id"], before)

    async def test_since_id_advances_only_when_the_wake_is_delivered(self):
        self.enable()
        self.db.add_message(ROOT, "greg", "human", "news")
        self.adapter.accept = False
        posted = await self.tick(heartbeat.DEFAULT_INTERVAL)
        before = heartbeat.status(self.db)["since_id"]

        self.assertEqual(before, 0, "an undelivered reminder moves no boundary")

        self.adapter.accept = True
        self.deliver(posted)
        heartbeat_wake.settle_delivered(self.db)

        # The boundary is the delta that was reported, which stops short of
        # the reminder itself — the reminder is not news.
        self.assertEqual(heartbeat.status(self.db)["since_id"], posted - 1)

    async def test_enabling_bootstraps_the_boundary_to_the_present(self):
        """Starting at zero would make the first wake a history dump."""
        for index in range(30):
            self.db.add_message(ROOT, "greg", "human", f"old {index}")

        state = self.enable()

        self.assertGreater(state["since_id"], 0)
        self.assertIsNone(
            await self.tick(heartbeat.DEFAULT_INTERVAL),
            "history before the monitor existed is not a delta",
        )

    async def test_an_unacknowledged_report_is_actionable_without_new_speech(self):
        from partyline.hierarchy import create_child_conversation
        from partyline.reports import add as add_report

        self.enable()
        create_child_conversation(self.db, ROOT, "child", "Child")
        self.assertIsNone(await self.tick(heartbeat.DEFAULT_INTERVAL))

        add_report(self.db, ROOT, "child", "worker", "a blocker needs you")
        posted = await self.tick(heartbeat.DEFAULT_INTERVAL)

        self.assertIsNotNone(posted, "a waiting report is worth a wake")
        self.assertIn("1 report(s) waiting", self.body(posted))
        self.assertEqual(len(self.saved(posted)["reports"]), 1)

    async def test_a_behind_or_stopped_agent_is_actionable(self):
        self.enable()
        self.db.add_attachment(
            "worker", ROOT, "worker", "raw", ["sh"], self.directory.name, "owner"
        )
        self.db.set_attachment_status("worker", "detached", "owner")

        posted = await self.tick(heartbeat.DEFAULT_INTERVAL)

        self.assertIsNotNone(posted, "a process nobody is feeding is news")
        self.assertIn("1 process(es) behind", self.body(posted))
        agent = self.saved(posted)["lines"][0]["agents"][0]
        self.assertEqual((agent["attachment_id"], agent["status"]), ("worker", "detached"))

    async def test_agents_are_keyed_by_attachment_not_handle(self):
        """A replacement keeps the handle and is a different process."""
        self.enable()
        self.db.add_attachment(
            "first", ROOT, "worker", "raw", ["sh"], self.directory.name, "owner"
        )
        self.db.set_attachment_status("first", "exited", "owner")
        snapshot = heartbeat_snapshot.build(self.db, ROOT, 0)

        listed = [
            agent for line in snapshot["lines"] for agent in line["agents"]
        ]
        self.assertIn("first", [agent["attachment_id"] for agent in listed])


    async def test_a_silent_line_with_no_open_work_never_alarms(self):
        from partyline.hierarchy import create_child_conversation

        self.enable()
        create_child_conversation(self.db, ROOT, "child", "Child")

        for _ in range(18):  # long past any former stall threshold
            self.assertIsNone(await self.tick(heartbeat.DEFAULT_INTERVAL))

    async def test_quiet_can_be_switched_off(self):
        self.enable(quiet_if_unchanged=False)

        self.assertIsNotNone(await self.tick(heartbeat.DEFAULT_INTERVAL))


class SnapshotHashTest(HeartbeatFixture):
    async def test_head_id_is_reported_but_never_hashed(self):
        """The correction that saves suppression.

        `head_id` moves for unrelated lines and for the monitor's own posted
        reminder. Hashing it would change the digest on every single wake, so
        suppression would never fire and the overnight failure would repeat
        with a JSON payload attached.
        """
        first = heartbeat_snapshot.build(self.db, ROOT, 0)
        self.db.create_conversation("elsewhere", "Unrelated")
        self.db.add_message("elsewhere", "greg", "human", "not this tree")
        second = heartbeat_snapshot.build(self.db, ROOT, 0)

        self.assertNotEqual(first["head_id"], second["head_id"])
        self.assertEqual(
            heartbeat_snapshot.canonical_hash(first),
            heartbeat_snapshot.canonical_hash(second),
        )

    async def test_the_hash_is_stable_and_order_independent(self):
        snapshot = heartbeat_snapshot.build(self.db, ROOT, 0)
        shuffled = dict(reversed(list(snapshot.items())))

        self.assertEqual(
            heartbeat_snapshot.canonical_hash(snapshot),
            heartbeat_snapshot.canonical_hash(shuffled),
        )

    async def test_the_hash_changes_when_the_tree_changes(self):
        before = heartbeat_snapshot.canonical_hash(
            heartbeat_snapshot.build(self.db, ROOT, 0)
        )
        self.db.add_message(ROOT, "greg", "human", "news")

        self.assertNotEqual(
            before,
            heartbeat_snapshot.canonical_hash(
                heartbeat_snapshot.build(self.db, ROOT, 0)
            ),
        )

    async def test_no_message_body_reaches_the_snapshot(self):
        self.db.add_message(ROOT, "greg", "human", "a private instruction")

        rendered = heartbeat_snapshot.render(
            heartbeat_snapshot.build(self.db, ROOT, 0)
        )

        self.assertNotIn("a private instruction", rendered)


class SnapshotFileTest(HeartbeatFixture):
    """The delta lives in a file; the room sees one line about it.

    Inlining the JSON was right about the information and wrong about the
    delivery — it dumped kilobytes into a room humans read, which is the first
    heartbeat's mistake one level up.
    """

    def enable(self, **kwargs):
        kwargs.setdefault("quiet_if_unchanged", True)
        return heartbeat.enable(self.db, ROOT, OWNER, now=self.now, **kwargs)

    async def test_the_wake_carries_a_pointer_not_the_payload(self):
        self.enable()
        self.db.add_message(ROOT, "greg", "human", "a private instruction")

        posted = await self.tick(heartbeat.DEFAULT_INTERVAL)
        body = self.body(posted)

        self.assertLess(len(body), 600, "the room gets a sentence, not a dump")
        self.assertNotIn('"lines"', body, "no JSON payload in the message")
        self.assertNotIn("a private instruction", body)
        self.assertIn("sha256:", body)
        self.assertEqual(self.saved(posted)["lines"][0]["new"], 1)

    async def test_the_pointer_digest_verifies_the_file_it_names(self):
        self.enable()
        self.db.add_message(ROOT, "greg", "human", "news")
        posted = await self.tick(heartbeat.DEFAULT_INTERVAL)

        body = self.body(posted)
        digest = [word for word in body.split() if word.startswith("sha256:")][0]

        self.assertEqual(
            heartbeat_snapshot.canonical_hash(self.saved(posted)), digest,
            "a fetched snapshot re-hashes to the digest that named it",
        )

    async def test_an_identical_snapshot_reuses_one_file(self):
        """The name is the content, so writing twice is writing once."""
        snapshot = heartbeat_snapshot.build(self.db, ROOT, 0, OWNER)
        digest = heartbeat_snapshot.canonical_hash(snapshot)

        first = heartbeat_files.write(self.db.path, digest, snapshot)
        second = heartbeat_files.write(self.db.path, digest, snapshot)

        self.assertEqual(first, second)
        self.assertEqual(
            len(list(heartbeat_files.snapshot_root(self.db.path).glob("*.json"))), 1
        )

    async def test_a_snapshot_file_is_private_to_this_user(self):
        snapshot = heartbeat_snapshot.build(self.db, ROOT, 0, OWNER)
        digest = heartbeat_snapshot.canonical_hash(snapshot)

        path = heartbeat_files.write(self.db.path, digest, snapshot)

        self.assertEqual(path.stat().st_mode & 0o777, 0o600)

    async def test_no_caller_supplied_string_ever_becomes_a_path(self):
        """The digest is validated before it is a filename, not after."""
        for hostile in (
            "sha256:../../../../etc/passwd",
            "../../etc/passwd",
            "sha256:" + "g" * 16,
            "sha256:0123456789abcdef/../..",
            "", "sha256:", "/etc/passwd",
        ):
            with self.subTest(hostile=hostile):
                self.assertIsNone(heartbeat_files.read(self.db.path, hostile))
                with self.assertRaises(ValueError):
                    heartbeat_files.write(self.db.path, hostile, {"v": 1})

    async def test_the_file_is_private_from_the_instant_it_appears(self):
        """Grok's residual: a chmod after the rename is a window, however brief.

        The rename is what publishes the file, so the mode has to be right
        before it — another process may look at any instant, which is the whole
        reason the write renames into place.
        """
        snapshot = heartbeat_snapshot.build(self.db, ROOT, 0, OWNER)
        digest = heartbeat_snapshot.canonical_hash(snapshot)
        original = os.umask(0)
        try:
            path = heartbeat_files.write(self.db.path, digest, snapshot)
        finally:
            os.umask(original)

        self.assertEqual(
            path.stat().st_mode & 0o777, 0o600,
            "a permissive umask must not widen a published snapshot",
        )

    async def test_the_snapshot_directory_is_private_too(self):
        """A listing of digests and mtimes is a map of when this tree was busy."""
        snapshot = heartbeat_snapshot.build(self.db, ROOT, 0, OWNER)
        heartbeat_files.write(
            self.db.path, heartbeat_snapshot.canonical_hash(snapshot), snapshot
        )

        root = heartbeat_files.snapshot_root(self.db.path)

        self.assertEqual(root.stat().st_mode & 0o777, 0o700)

    async def test_crash_leftovers_are_collected(self):
        """A `.partial` can only come from a write that died; nothing finishes it."""
        root = heartbeat_files.snapshot_root(self.db.path)
        root.mkdir(parents=True, exist_ok=True)
        (root / "sha256-0000000000000000.json.partial").write_text("{", encoding="utf-8")

        removed = heartbeat_files.prune(self.db.path)

        self.assertEqual(removed, 1)
        self.assertEqual(list(root.glob("*.partial")), [])

    async def test_a_failed_write_leaves_nothing_behind(self):
        class Unserializable:
            pass

        snapshot = heartbeat_snapshot.build(self.db, ROOT, 0, OWNER)
        digest = heartbeat_snapshot.canonical_hash(snapshot)

        with self.assertRaises(TypeError):
            heartbeat_files.write(
                self.db.path, digest, {**snapshot, "bad": Unserializable()}
            )

        root = heartbeat_files.snapshot_root(self.db.path)
        self.assertEqual(list(root.glob("*.partial")), [], "the temp file was removed")

    async def test_a_partial_write_is_never_visible(self):
        """Another process fetches this file; it must never see half of one."""
        snapshot = heartbeat_snapshot.build(self.db, ROOT, 0, OWNER)
        digest = heartbeat_snapshot.canonical_hash(snapshot)
        heartbeat_files.write(self.db.path, digest, snapshot)

        leftovers = list(
            heartbeat_files.snapshot_root(self.db.path).glob("*.partial")
        )

        self.assertEqual(leftovers, [], "the write renames into place")

    async def test_old_snapshots_are_pruned_but_recent_ones_kept(self):
        root = heartbeat_files.snapshot_root(self.db.path)
        root.mkdir(parents=True, exist_ok=True)
        for index in range(12):
            (root / f"sha256-{index:016x}.json").write_text("{}", encoding="utf-8")

        removed = heartbeat_files.prune(self.db.path, keep=5)

        self.assertEqual(removed, 7)
        self.assertEqual(len(list(root.glob("sha256-*.json"))), 5)

    async def test_the_directory_follows_the_database(self):
        self.assertEqual(
            heartbeat_files.snapshot_root("/tmp/example.db"),
            Path("/tmp/example/heartbeat"),
        )


class SnapshotDownloadTest(HeartbeatFixture):
    def setUp(self):
        super().setUp()
        app = FastAPI()
        install_auth_guard(app, self.db)
        app.include_router(heartbeat_router(self.runtime))
        self.client = TestClient(app)
        self.client.headers["Authorization"] = (
            f"Bearer {ensure_api_token(self.db, OWNER)}"
        )

    def tearDown(self):
        self.client.close()
        super().tearDown()

    async def test_the_root_lead_can_download_a_snapshot_by_digest(self):
        snapshot = heartbeat_snapshot.build(self.db, ROOT, 0, OWNER)
        digest = heartbeat_snapshot.canonical_hash(snapshot)
        heartbeat_files.write(self.db.path, digest, snapshot)

        response = self.client.get(f"/api/heartbeat/snapshots/{digest}")

        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json(), snapshot)

    async def test_an_unknown_or_hostile_digest_is_404_not_a_file_read(self):
        for digest in ("sha256:" + "0" * 16, "sha256:..", "nonsense"):
            with self.subTest(digest=digest):
                self.assertEqual(
                    self.client.get(f"/api/heartbeat/snapshots/{digest}").status_code,
                    404,
                )

    async def test_an_unauthenticated_caller_cannot_download_one(self):
        snapshot = heartbeat_snapshot.build(self.db, ROOT, 0, OWNER)
        digest = heartbeat_snapshot.canonical_hash(snapshot)
        heartbeat_files.write(self.db.path, digest, snapshot)
        self.client.headers.pop("Authorization")

        self.assertEqual(
            self.client.get(f"/api/heartbeat/snapshots/{digest}").status_code, 401
        )
