import tempfile
import unittest
from unittest.mock import AsyncMock

from partyline.db import Db
from partyline.reattach import ReattachCoordinator
from partyline.runtime import ChatRuntime


class ReadyAdapter:
    def __init__(self, order, name, *, ready=True):
        self.order = order
        self.name = name
        self.ready = ready
        self.deliveries = []
        self.stopped = False

    async def deliver(self, messages):
        self.deliveries.append(messages)
        self.order.append(f"deliver:{self.name}")

    async def wait_ready(self):
        self.order.append(f"ready:{self.name}")
        return self.ready

    async def stop(self):
        self.stopped = True


class ReattachCoordinatorTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.db = Db(f"{self.directory.name}/partyline.db")
        self.db.create_conversation("line", "Line")
        self.runtime = ChatRuntime(self.db)
        self.order = []
        for ident, name in (("one", "sol"), ("two", "terra")):
            self.db.add_attachment(ident, "line", name, "fake", ["fake"], self.directory.name)
            self.db.set_attachment_status(ident, "exited")
        self.plan = self.db.save_restart_plan(
            "line", ["one", "two"], "Continue the TypeScript review."
        )

    async def asyncTearDown(self):
        self.db.close()
        self.directory.cleanup()

    async def test_each_process_is_delivered_and_ready_before_the_next_starts(self):
        adapters = {}

        async def resume(attachment_id):
            name = self.db.get_attachment(attachment_id)["name"]
            self.order.append(f"start:{name}")
            adapter = ReadyAdapter(self.order, name)
            adapters[attachment_id] = adapter
            self.runtime.live[attachment_id] = adapter
            return adapter

        result = await ReattachCoordinator(self.runtime, resume).run(self.plan, "greg")

        self.assertEqual(
            self.order,
            [
                "start:sol",
                "deliver:sol",
                "ready:sol",
                "start:terra",
                "deliver:terra",
                "ready:terra",
            ],
        )
        self.assertEqual(result.ready, ("sol", "terra"))
        self.assertIn("Continuation debrief", adapters["one"].deliveries[0][0]["body"])

    async def test_an_unready_process_is_stopped_before_the_sequence_advances(self):
        adapters = {}

        async def resume(attachment_id):
            name = self.db.get_attachment(attachment_id)["name"]
            self.order.append(f"start:{name}")
            adapter = ReadyAdapter(self.order, name, ready=attachment_id != "one")
            adapters[attachment_id] = adapter
            self.runtime.live[attachment_id] = adapter
            return adapter

        result = await ReattachCoordinator(self.runtime, resume).run(self.plan, "greg")

        self.assertTrue(adapters["one"].stopped)
        self.assertNotIn("one", self.runtime.live)
        self.assertEqual(result.failed, ("sol",))
        self.assertGreater(self.order.index("start:terra"), self.order.index("ready:sol"))

    async def test_missing_attachment_does_not_block_later_entries(self):
        plan = {**self.plan, "attachment_ids": ["missing", "two"]}

        async def resume(attachment_id):
            adapter = ReadyAdapter(self.order, "terra")
            self.runtime.live[attachment_id] = adapter
            return adapter

        result = await ReattachCoordinator(self.runtime, resume).run(plan, "greg")

        self.assertEqual(result.ready, ("terra",))
        self.assertEqual(result.failed, ("missing",))

    async def test_readiness_timeout_is_explained_and_does_not_block_the_sequence(self):
        adapters = {}

        async def resume(attachment_id):
            name = self.db.get_attachment(attachment_id)["name"]
            self.order.append(f"start:{name}")
            adapter = ReadyAdapter(self.order, name)
            if attachment_id == "one":
                adapter.wait_ready = lambda: __import__("asyncio").sleep(30)
            adapters[attachment_id] = adapter
            self.runtime.live[attachment_id] = adapter
            return adapter

        result = await ReattachCoordinator(self.runtime, resume, ready_timeout=0.01).run(
            self.plan, "greg"
        )

        self.assertTrue(adapters["one"].stopped)
        self.assertEqual(result.ready, ("terra",))
        self.assertEqual(result.failed, ("sol",))
        bodies = [message["body"] for message in self.db.list_messages("line")]
        self.assertTrue(any("readiness timed out after 0.01s" in body for body in bodies))

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


if __name__ == "__main__":
    unittest.main()
