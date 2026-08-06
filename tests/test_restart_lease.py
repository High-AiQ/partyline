import asyncio
import tempfile
import unittest
from unittest.mock import AsyncMock, patch

from partyline.db import Db
from partyline.restart_lease import (
    LeaseTiming,
    RestartPlanLeaseLost,
    _renew,
    run_automatic_restart_plan,
)


class RestartLeaseTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.db = Db(f"{self.directory.name}/partyline.db")
        self.db.create_conversation("line", "Line")
        self.db.save_restart_plan("line", ["agent"], "continue", "automatic")
        self.timing = LeaseTiming(lease_seconds=30, renew_interval=10, retry_interval=0.001)

    async def asyncTearDown(self):
        self.db.close()
        self.directory.cleanup()

    async def test_two_lifespans_cannot_run_one_plan(self):
        first_started = asyncio.Event()
        finish_first = asyncio.Event()
        second_started = asyncio.Event()

        async def first(plan, ensure_owned):
            ensure_owned()
            first_started.set()
            await finish_first.wait()
            return plan["token"]

        async def second(plan, ensure_owned):
            ensure_owned()
            second_started.set()
            return plan["token"]

        first_task = asyncio.create_task(
            run_automatic_restart_plan(self.db, first, self.timing)
        )
        await first_started.wait()
        second_task = asyncio.create_task(
            run_automatic_restart_plan(self.db, second, self.timing)
        )
        await asyncio.sleep(0)
        self.assertFalse(second_started.is_set())

        finish_first.set()
        first_result, second_result = await asyncio.gather(first_task, second_task)

        self.assertIsInstance(first_result, str)
        self.assertIsNone(second_result)
        self.assertFalse(second_started.is_set())
        self.assertIsNone(self.db.get_restart_plan())

    async def test_cancellation_releases_the_claim_and_preserves_the_plan(self):
        started = asyncio.Event()
        wait_forever = asyncio.Event()

        async def operation(plan, ensure_owned):
            ensure_owned()
            started.set()
            await wait_forever.wait()
            return plan["token"]

        task = asyncio.create_task(run_automatic_restart_plan(self.db, operation, self.timing))
        await started.wait()
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task

        plan = self.db.get_restart_plan()
        self.assertIsNotNone(plan)
        self.assertIsNone(plan["claim_owner"])
        self.assertIsNone(plan["claim_until"])

    async def test_operation_failure_releases_the_claim_for_an_immediate_retry(self):
        async def fail(plan, ensure_owned):
            ensure_owned()
            raise RuntimeError(f"failed {plan['token']}")

        with self.assertRaisesRegex(RuntimeError, "failed"):
            await run_automatic_restart_plan(self.db, fail, self.timing)

        async def retry(plan, ensure_owned):
            ensure_owned()
            return plan["token"]

        result = await run_automatic_restart_plan(self.db, retry, self.timing)
        self.assertIsInstance(result, str)
        self.assertIsNone(self.db.get_restart_plan())

    async def test_replacement_stops_the_old_owner_before_its_next_effect(self):
        replacement_token = None

        async def operation(plan, ensure_owned):
            nonlocal replacement_token
            replacement = self.db.save_restart_plan(
                "line", ["new-agent"], "replacement", "automatic"
            )
            replacement_token = replacement["token"]
            ensure_owned()
            self.fail("a replaced owner must not continue")

        with self.assertRaisesRegex(RuntimeError, "lost its durable lease"):
            await run_automatic_restart_plan(self.db, operation, self.timing)

        pending = self.db.get_restart_plan()
        self.assertEqual(pending["token"], replacement_token)
        self.assertIsNone(pending["claim_owner"])

    async def test_heartbeat_stops_when_an_owner_cannot_renew(self):
        claimed = self.db.claim_restart_plan("automatic", "old-owner", 30)
        self.db.save_restart_plan("line", ["new-agent"], "replacement", "automatic")

        with patch("partyline.restart_lease.asyncio.sleep", AsyncMock(return_value=None)):
            with self.assertRaisesRegex(RestartPlanLeaseLost, "lost its durable lease"):
                await _renew(self.db, claimed, "old-owner", self.timing)

    async def test_completion_cannot_delete_a_replacement_plan(self):
        replacement_token = None

        async def operation(plan, ensure_owned):
            nonlocal replacement_token
            replacement = self.db.save_restart_plan(
                "line", ["new-agent"], "replacement", "automatic"
            )
            replacement_token = replacement["token"]
            return plan["token"]

        with self.assertRaisesRegex(RestartPlanLeaseLost, "false completion"):
            await run_automatic_restart_plan(self.db, operation, self.timing)

        self.assertEqual(self.db.get_restart_plan()["token"], replacement_token)


if __name__ == "__main__":
    unittest.main()
