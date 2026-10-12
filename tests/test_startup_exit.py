import tempfile
import unittest
from unittest.mock import AsyncMock

from partyline.adapters.output_tail import OutputTail
from partyline.db import Db
from partyline.features import overridden
from partyline.process_incidents import exit_callback, last_incident
from partyline.runtime import ChatRuntime
from tests.test_adapter_base import Recorder, until

CAPS = {"capabilities": {"transcript": True}}


def setUpModule():
    global _fence
    _fence = overridden(write_fence=False)
    _fence.__enter__()


def tearDownModule():
    _fence.__exit__(None, None, None)


class OutputTailTest(unittest.TestCase):
    def test_keeps_only_a_bounded_tail_with_escapes_stripped(self):
        tail = OutputTail(limit=64)
        tail.feed(b"old\n" * 100 + b"\x1b[31mred\x1b[0m\r\n\x1b]0;title\x07fatal: nope\r\n\n")
        self.assertEqual(tail.lines(2), ["red", "fatal: nope"])
        self.assertLessEqual(len(tail._raw), 64)

    def test_a_redrawn_line_keeps_its_final_state(self):
        tail = OutputTail()
        tail.feed(b"loading 10%\rloading 90%\rdone\n")
        self.assertEqual(tail.lines(5), ["done"])


class StartupExitTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db = Db(f"{self.tmp.name}/test.db")
        self.addCleanup(self.db.close)
        self.runtime = ChatRuntime(self.db)
        self.runtime.broadcast = AsyncMock()
        self.db.create_conversation("line", "Line")
        self.db.add_attachment("worker", "line", "worker", "fake", ["sh"], self.tmp.name, "owner")
        self.db._exec("UPDATE attachments SET status='running' WHERE id='worker'")

    async def run_child(self, script, *, ready=False):
        att = self.db.get_attachment("worker")
        adapter = Recorder(
            ["sh", "-c", script], id="worker", name="worker", conv_id="line",
            runtime_owner="owner", cwd=self.tmp.name, adapter_metadata=CAPS,
            on_process_exit=exit_callback(self.runtime, att))
        await adapter.start()
        if ready:
            adapter.mark_ready()
        await until(lambda: "exited" in adapter.statuses, what="exit report")
        await until(lambda: self.db.list_messages("line"), what="exit notice")
        return adapter

    async def test_exit_before_ready_records_output_and_names_it_in_the_notice(self):
        await self.run_child("printf 'boot\\nwarn: slow\\nfatal: bad config\\nhint: fix it\\n'; exit 1")
        incident = last_incident(self.db, "worker")
        self.assertTrue(incident["startup"])
        self.assertEqual(incident["last_output"].splitlines(),
                         ["boot", "warn: slow", "fatal: bad config", "hint: fix it"])
        body = self.db.list_messages("line")[-1]["body"]
        self.assertIn("⚠ @worker exited during startup (code 1): "
                      "warn: slow | fatal: bad config | hint: fix it", body)
        self.assertNotIn("boot", body)
        self.assertNotIn("workload", body)

    async def test_exit_after_ready_gets_no_startup_wording(self):
        await self.run_child("sleep 0.3; echo late; exit 1", ready=True)
        incident = last_incident(self.db, "worker")
        self.assertFalse(incident["startup"])
        self.assertIsNone(incident["last_output"])
        self.assertNotIn("startup", self.db.list_messages("line")[-1]["body"])
