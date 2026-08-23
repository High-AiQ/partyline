import asyncio
from contextlib import contextmanager
import tempfile
import threading
import unittest
from unittest.mock import AsyncMock

from partyline.db import Db
from partyline.reattach import (
    ContinuationDeliveryPending,
    ReattachCoordinator,
    ResumedAttachment,
)
from partyline.restart_lease import RestartPlanLeaseLost
from partyline.runtime import ChatRuntime


class ReadyAdapter:
    def __init__(self, order, name, *, ready=True, startup_received=True):
        self.order = order
        self.name = name
        self.ready = ready
        self.startup_received = startup_received
        self.deliveries = []
        self.stopped = False
        self.att = {"runtime_owner": None}

    async def deliver(self, messages):
        self.deliveries.append(messages)
        self.order.append(f"deliver:{self.name}")

    async def wait_ready(self):
        self.order.append(f"ready:{self.name}")
        return self.ready

    async def wait_startup_delivery_received(self):
        self.order.append(f"receipt:{self.name}")
        return self.startup_received

    async def stop(self):
        self.stopped = True


class FailingDeliveryAdapter(ReadyAdapter):
    async def deliver(self, messages):
        self.deliveries.append(messages)
        self.order.append(f"deliver:{self.name}")
        raise RuntimeError("input was not accepted")


class ReplacingDeliveryAdapter(ReadyAdapter):
    def __init__(self, order, name, replacement, attachment_id):
        super().__init__(order, name)
        self.replacement = replacement
        self.attachment_id = attachment_id
        self.lock_attempted = threading.Event()
        self.replacement_finished = threading.Event()
        self.replacement_crossed_before_write = False
        self.replacement_task = None

    def replace(self):
        original_guard = self.replacement._runtime_serialized

        @contextmanager
        def signalled_guard():
            self.lock_attempted.set()
            with original_guard():
                yield

        self.replacement._runtime_serialized = signalled_guard
        self.replacement.mark_stale_attachments()
        self.replacement.claim_attachment(self.attachment_id, "new-generation")
        self.replacement.set_attachment_status(
            self.attachment_id, "running", "new-generation"
        )
        self.replacement_finished.set()

    async def deliver(self, messages):
        self.replacement_task = asyncio.create_task(asyncio.to_thread(self.replace))
        await asyncio.to_thread(self.lock_attempted.wait)
        try:
            await asyncio.wait_for(
                asyncio.to_thread(self.replacement_finished.wait), timeout=0.05
            )
        except TimeoutError:
            pass
        self.replacement_crossed_before_write = self.replacement_finished.is_set()
        await super().deliver(messages)


class ReattachCoordinatorTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.db = Db(f"{self.directory.name}/partyline.db")
        self.db.create_conversation("line", "Line")
        self.runtime = ChatRuntime(self.db)
        self.order = []
        for ident, name in (("one", "sol"), ("two", "terra")):
            self.db.add_attachment(ident, "line", name, "fake", ["fake"], self.directory.name)
            self.db.set_attachment_status(ident, "exited", None)
        self.plan = self.db.save_restart_plan(
            "line", ["one", "two"], "Continue the TypeScript review."
        )

    async def asyncTearDown(self):
        self.db.close()
        self.directory.cleanup()

    async def test_each_process_is_delivered_and_ready_before_the_next_starts(self):
        adapters = {}

        async def resume(attachment_id, _pending):
            name = self.db.get_attachment(attachment_id)["name"]
            self.order.append(f"start:{name}")
            adapter = ReadyAdapter(self.order, name)
            adapters[attachment_id] = adapter
            self.runtime.live[attachment_id] = adapter
            return ResumedAttachment(adapter, False)

        result = await ReattachCoordinator(self.runtime, resume).run(self.plan, "greg")

        self.assertEqual(
            self.order,
            [
                "start:sol",
                "ready:sol",
                "deliver:sol",
                "start:terra",
                "ready:terra",
                "deliver:terra",
            ],
        )
        self.assertEqual(result.ready, ("sol", "terra"))
        self.assertIn("Continuation debrief", adapters["one"].deliveries[0][0]["body"])

    async def test_staged_delivery_advances_cursor_without_pty_delivery(self):
        adapters = {}
        staged = []

        async def resume(attachment_id, pending):
            name = self.db.get_attachment(attachment_id)["name"]
            staged.append(pending)
            adapter = ReadyAdapter(self.order, name)
            adapters[attachment_id] = adapter
            self.runtime.live[attachment_id] = adapter
            return ResumedAttachment(adapter, True)

        result = await ReattachCoordinator(self.runtime, resume).run(self.plan, "greg")

        self.assertEqual(result.ready, ("sol", "terra"))
        self.assertTrue(staged[0])
        self.assertEqual(adapters["one"].deliveries, [])
        self.assertIn("receipt:sol", self.order)
        self.assertEqual(
            self.db.get_attachment("one")["last_seen"], staged[0][-1]["id"]
        )

    async def test_staged_process_exiting_before_receipt_keeps_cursor(self):
        plan = {**self.plan, "attachment_ids": ["one"]}

        async def resume(attachment_id, _pending):
            adapter = ReadyAdapter(self.order, "sol", startup_received=False)
            self.runtime.live[attachment_id] = adapter
            return ResumedAttachment(adapter, True)

        result = await ReattachCoordinator(self.runtime, resume).run(plan, "greg")

        self.assertEqual(result.failed, ("sol",))
        self.assertEqual(self.db.get_attachment("one")["last_seen"], 0)
        self.assertNotIn("one", self.runtime.live)

    async def test_unstaged_delivery_waits_for_evidence_outside_the_owner_lock(self):
        plan = {**self.plan, "attachment_ids": ["one"]}
        adapter = ReadyAdapter(self.order, "sol")

        async def deliver(messages):
            adapter.deliveries.append(messages)
            return False

        async def wait_delivery_received(message_ids):
            async with self.db.reserve_attachment_delivery("one", None) as reserved:
                self.assertTrue(reserved)
                self.assertTrue(self.db.set_last_seen("one", max(message_ids), None))
            return True

        adapter.deliver = deliver
        adapter.wait_delivery_received = wait_delivery_received

        async def resume(attachment_id, _pending):
            self.runtime.live[attachment_id] = adapter
            return ResumedAttachment(adapter, False)

        result = await ReattachCoordinator(self.runtime, resume).run(plan, "greg")

        self.assertEqual(result.ready, ("sol",))
        self.assertEqual(
            self.db.get_attachment("one")["last_seen"], adapter.deliveries[0][-1]["id"]
        )

    async def test_delivery_failure_leaves_cursor_for_recovery(self):
        adapters = {}

        async def resume(attachment_id, _pending):
            name = self.db.get_attachment(attachment_id)["name"]
            adapter = FailingDeliveryAdapter(self.order, name)
            adapters[attachment_id] = adapter
            self.runtime.live[attachment_id] = adapter
            return ResumedAttachment(adapter, False)

        result = await ReattachCoordinator(self.runtime, resume).run(self.plan, "greg")

        self.assertEqual(result.failed, ("sol", "terra"))
        self.assertEqual(self.db.get_attachment("one")["last_seen"], 0)
        self.assertEqual(self.db.get_attachment("two")["last_seen"], 0)
        self.assertEqual(len(adapters["one"].deliveries), 1)

    async def test_replacement_claim_blocks_fallback_delivery_to_stale_process(self):
        self.plan["attachment_ids"] = ["one"]
        adapter = ReadyAdapter(self.order, "sol")
        adapter.att["runtime_owner"] = "old-generation"

        async def ready_after_replacement():
            self.assertTrue(
                self.db.set_attachment_status("one", "exited", "old-generation")
            )
            self.assertTrue(self.db.claim_attachment("one", "new-generation"))
            self.assertTrue(
                self.db.set_attachment_status("one", "running", "new-generation")
            )
            return True

        adapter.wait_ready = ready_after_replacement

        async def resume(attachment_id, _pending):
            self.assertTrue(
                self.db.claim_attachment(attachment_id, "old-generation")
            )
            self.assertTrue(
                self.db.set_attachment_status(
                    attachment_id, "running", "old-generation"
                )
            )
            self.runtime.live[attachment_id] = adapter
            return ResumedAttachment(adapter, False)

        result = await ReattachCoordinator(self.runtime, resume).run(
            self.plan, "greg"
        )

        self.assertEqual(result.failed, ("sol",))
        self.assertEqual(adapter.deliveries, [])
        self.assertTrue(adapter.stopped)
        self.assertEqual(self.db.get_attachment("one")["status"], "running")
        self.assertEqual(self.db.get_attachment("one")["runtime_owner"], "new-generation")
        self.assertEqual(self.db.get_attachment("one")["last_seen"], 0)

    async def test_replacement_waits_for_fallback_pty_delivery_reservation(self):
        self.plan["attachment_ids"] = ["one"]
        replacement = Db(f"{self.directory.name}/partyline.db")
        adapter = ReplacingDeliveryAdapter(
            self.order, "sol", replacement, "one"
        )
        adapter.att["runtime_owner"] = "old-generation"

        async def resume(attachment_id, _pending):
            self.assertTrue(
                self.db.claim_attachment(attachment_id, "old-generation")
            )
            self.assertTrue(
                self.db.set_attachment_status(
                    attachment_id, "running", "old-generation"
                )
            )
            self.runtime.live[attachment_id] = adapter
            return ResumedAttachment(adapter, False)

        try:
            result = await ReattachCoordinator(self.runtime, resume).run(
                self.plan, "greg"
            )
            await adapter.replacement_task
            self.assertEqual(result.ready, ("sol",))
            self.assertFalse(adapter.replacement_crossed_before_write)
            self.assertEqual(len(adapter.deliveries), 1)
            current = replacement.get_attachment("one")
            self.assertEqual(current["runtime_owner"], "new-generation")
            self.assertEqual(current["status"], "running")
        finally:
            replacement.close()

    async def test_an_unready_process_is_stopped_before_the_sequence_advances(self):
        adapters = {}

        async def resume(attachment_id, _pending):
            name = self.db.get_attachment(attachment_id)["name"]
            self.order.append(f"start:{name}")
            adapter = ReadyAdapter(self.order, name, ready=attachment_id != "one")
            adapters[attachment_id] = adapter
            self.runtime.live[attachment_id] = adapter
            return ResumedAttachment(adapter, False)

        result = await ReattachCoordinator(self.runtime, resume).run(self.plan, "greg")

        self.assertTrue(adapters["one"].stopped)
        self.assertNotIn("one", self.runtime.live)
        self.assertEqual(result.failed, ("sol",))
        self.assertGreater(self.order.index("start:terra"), self.order.index("ready:sol"))

    async def test_missing_attachment_does_not_block_later_entries(self):
        plan = {**self.plan, "attachment_ids": ["missing", "two"]}

        async def resume(attachment_id, _pending):
            adapter = ReadyAdapter(self.order, "terra")
            self.runtime.live[attachment_id] = adapter
            return ResumedAttachment(adapter, False)

        result = await ReattachCoordinator(self.runtime, resume).run(plan, "greg")

        self.assertEqual(result.ready, ("terra",))
        self.assertEqual(result.failed, ("missing",))

    async def test_a_slow_process_is_left_running_and_the_sequence_advances(self):
        """Slow is not failed.

        This is the case that cost us three healthy agents in the first real
        dogfood. Readiness means "the adapter opened its claimed transcript",
        and a resumed codex writes that file lazily — its own source says the
        rollout "may not appear for many minutes". Stopping it at the timeout
        killed processes that were on their way back, and reported them as
        failures. The wait may run out of patience; it may not conclude from
        that that the process is broken.
        """
        adapters = {}

        async def resume(attachment_id, _pending):
            name = self.db.get_attachment(attachment_id)["name"]
            self.order.append(f"start:{name}")
            adapter = ReadyAdapter(self.order, name)
            if attachment_id == "one":
                adapter.wait_ready = lambda: asyncio.sleep(30)
            adapters[attachment_id] = adapter
            self.runtime.live[attachment_id] = adapter
            return ResumedAttachment(adapter, False)

        result = await ReattachCoordinator(self.runtime, resume, ready_timeout=0.01).run(
            self.plan, "greg"
        )

        # The whole point: it is still alive and still attached.
        self.assertFalse(adapters["one"].stopped)
        self.assertIn("one", self.runtime.live)
        self.assertEqual(result.slow, ())
        self.assertEqual(result.unconfirmed, ("sol",))
        self.assertEqual(result.failed, ())
        self.assertEqual(result.ready, ("terra",))
        # And the sequence still advanced rather than stalling behind it.
        self.assertGreater(self.order.index("start:terra"), self.order.index("start:sol"))

    async def test_a_slow_process_is_reported_as_settling_not_as_lost(self):
        """What the room is told matters as much as what happens to the process:
        "could not reattach safely" reads as a casualty, and people act on it."""

        async def resume(attachment_id, _pending):
            name = self.db.get_attachment(attachment_id)["name"]
            adapter = ReadyAdapter(self.order, name)
            if attachment_id == "one":
                adapter.wait_ready = lambda: asyncio.sleep(30)
            self.runtime.live[attachment_id] = adapter
            return ResumedAttachment(adapter, False)

        await ReattachCoordinator(self.runtime, resume, ready_timeout=0.01).run(self.plan, "greg")

        bodies = [message["body"] for message in self.db.list_messages("line")]
        self.assertTrue(
            any("continuation is still unconfirmed after 0.01s" in body for body in bodies),
            bodies,
        )
        self.assertTrue(any("1 continuation unconfirmed" in body for body in bodies), bodies)
        self.assertFalse(any("failed" in body for body in bodies), bodies)

    async def test_a_process_that_exits_is_still_a_failure(self):
        """The control for the two above. Loosening the timeout must not loosen
        the genuine case: a process that comes back and then dies has not
        reattached, and saying otherwise would be worse than the bug fixed."""
        adapters = {}

        async def resume(attachment_id, _pending):
            name = self.db.get_attachment(attachment_id)["name"]
            adapter = ReadyAdapter(self.order, name, ready=attachment_id != "one")
            adapters[attachment_id] = adapter
            self.runtime.live[attachment_id] = adapter
            return ResumedAttachment(adapter, False)

        result = await ReattachCoordinator(self.runtime, resume).run(self.plan, "greg")

        self.assertEqual(result.failed, ("sol",))
        self.assertEqual(result.slow, ())
        self.assertTrue(adapters["one"].stopped)

    async def test_cancel_consumes_the_offer_without_starting_any_process(self):
        resume = AsyncMock()
        coordinator = ReattachCoordinator(self.runtime, resume)

        error = await coordinator.choose(
            "line",
            {"type": "reattach", "token": self.plan["token"], "action": "cancel"},
            "greg",
        )

        self.assertIsNone(error)
        self.assertIsNone(self.db.get_restart_plan())
        resume.assert_not_awaited()
        self.assertIn("declined process reattachment", self.db.list_messages("line")[-1]["body"])

    async def test_a_stale_token_cannot_consume_the_current_offer(self):
        coordinator = ReattachCoordinator(self.runtime, AsyncMock())

        error = await coordinator.choose(
            "line",
            {"type": "reattach", "token": "stale-token", "action": "accept"},
            "greg",
        )

        self.assertEqual(error, "that reattachment offer is no longer available")
        self.assertEqual(self.db.get_restart_plan(), self.plan)

    async def test_automatic_plan_runs_without_a_browser_and_manual_plan_does_not(self):
        coordinator = ReattachCoordinator(self.runtime, AsyncMock())

        self.assertIsNone(await coordinator.run_automatic())
        self.assertEqual(self.db.get_restart_plan(), self.plan)

        automatic = self.db.save_restart_plan(
            "line", ["one"], "Continue autonomously.", "automatic"
        )
        refused = await coordinator.choose(
            "line",
            {"type": "reattach", "token": automatic["token"], "action": "accept"},
            "greg",
        )
        self.assertEqual(refused, "that reattachment offer is no longer available")
        self.assertEqual(self.db.get_restart_plan(), automatic)

        async def resume(attachment_id, _pending):
            durable = self.db.get_restart_plan()
            self.assertEqual(durable["token"], automatic["token"])
            self.assertIsNotNone(durable["claim_owner"])
            adapter = ReadyAdapter(self.order, "sol")
            self.runtime.live[attachment_id] = adapter
            return ResumedAttachment(adapter, False)

        coordinator = ReattachCoordinator(self.runtime, resume)
        self.assertIsNone(coordinator.offer("line"))
        result = await coordinator.run_automatic()

        self.assertEqual(result.ready, ("sol",))
        self.assertIsNone(self.db.get_restart_plan())
        bodies = [message["body"] for message in self.db.list_messages("line")]
        self.assertTrue(any("trusted cockpit plan started automatic" in body for body in bodies))
        self.assertNotEqual(automatic["token"], self.plan["token"])

    async def test_automatic_plan_survives_an_unexpected_coordinator_failure(self):
        automatic = self.db.save_restart_plan(
            "line", ["one"], "Retry after a failed startup.", "automatic"
        )
        original_post = self.runtime.post_message
        self.runtime.post_message = AsyncMock(side_effect=RuntimeError("database unavailable"))
        try:
            with self.assertRaisesRegex(RuntimeError, "database unavailable"):
                await ReattachCoordinator(self.runtime, AsyncMock()).run_automatic()
        finally:
            self.runtime.post_message = original_post

        preserved = self.db.get_restart_plan()
        self.assertEqual(preserved["token"], automatic["token"])
        self.assertEqual(preserved["attempt_count"], 1)
        self.assertIsNone(preserved["claim_owner"])
        self.assertEqual(self.runtime.reattaching, set())

    async def test_unconfirmed_automatic_continuation_retries_once_then_stops(self):
        automatic = self.db.save_restart_plan(
            "line", ["one"], "Continue the durable recovery review.", "automatic"
        )

        async def resume(attachment_id, _pending):
            adapter = ReadyAdapter(self.order, "sol")
            adapter.wait_startup_delivery_received = lambda: asyncio.sleep(30)
            self.runtime.live[attachment_id] = adapter
            return ResumedAttachment(adapter, True)

        coordinator = ReattachCoordinator(self.runtime, resume, ready_timeout=0.01)
        with self.assertRaisesRegex(ContinuationDeliveryPending, "preserved for one retry"):
            await coordinator.run_automatic()

        preserved = self.db.get_restart_plan()
        self.assertEqual(preserved["token"], automatic["token"])
        self.assertEqual(preserved["attempt_count"], 1)
        self.assertIn("one", self.runtime.reattaching)

        result = await coordinator.run_automatic()

        self.assertEqual(result.unconfirmed, ("sol",))
        self.assertIsNone(self.db.get_restart_plan())
        self.assertIn("one", self.runtime.live)
        self.assertNotIn("one", self.runtime.reattaching)
        warning = self.db.list_messages("line")[-1]["body"]
        self.assertIn("abandoned after 2 attempts", warning)
        self.assertIn("@sol", warning)
        self.assertIn("Continue the durable recovery review.", warning)

    async def test_lease_is_checked_before_the_first_coordinator_effect(self):
        resume = AsyncMock()

        def lost_lease():
            raise RestartPlanLeaseLost("replaced")

        with self.assertRaisesRegex(RestartPlanLeaseLost, "replaced"):
            await ReattachCoordinator(self.runtime, resume).run(
                self.plan, None, lost_lease
            )

        resume.assert_not_awaited()
        self.assertEqual(self.db.list_messages("line"), [])
        self.assertEqual(self.runtime.reattaching, set())

    async def test_mentions_for_later_processes_are_queued_until_their_turn(self):
        adapters = {}

        async def resume(attachment_id, _pending):
            name = self.db.get_attachment(attachment_id)["name"]
            adapter = ReadyAdapter(self.order, name)
            adapters[attachment_id] = adapter
            self.runtime.live[attachment_id] = adapter
            self.db.set_attachment_status(attachment_id, "running", None)
            if attachment_id == "one":
                async def ready_after_post():
                    await self.runtime.post_message(
                        "line", "sol", "agent", "@terra continue after me"
                    )
                    return True

                adapter.wait_ready = ready_after_post
            return ResumedAttachment(adapter, False)

        await ReattachCoordinator(self.runtime, resume).run(self.plan, "greg")

        bodies = [message["body"] for message in self.db.list_messages("line")]
        self.assertFalse(any("@terra was mentioned but is not attached" in body for body in bodies))
        delivered = [
            message["body"]
            for batch in adapters["two"].deliveries
            for message in batch
        ]
        self.assertIn("@terra continue after me", delivered)


if __name__ == "__main__":
    unittest.main()
