"""A process that dies from a normal detach is attributed to partyline, through the production close route."""

import tempfile
import unittest

from partyline import process_exit
from partyline.db import Db
from partyline.line_process_routes import close_attachment
from partyline.runtime import ChatRuntime


class StopAdapter:
    """Stops the way a real adapter does: flag stopping, then the group exits from SIGTERM."""

    def __init__(self, att, status):
        self.att = att
        self.status = status
        self.memory_scope = None
        self.memory_limit = "4G"
        self._stopping = False

    async def stop(self):
        self._stopping = True
        await process_exit.report_exit(self, -15)
        await self.status("detached")


class DetachStopAttributionTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.db = Db(f"{self.directory.name}/partyline.db")
        self.addCleanup(self.db.close)
        self.runtime = ChatRuntime(self.db)
        self.db.create_conversation("line", "Line")
        self.db.add_attachment("worker-att", "line", "worker", "raw", ["sh"],
                               self.directory.name, "owner", counts_toward_total=True)
        self.db.set_attachment_status("worker-att", "running", "owner")
        adapter = StopAdapter({"id": "worker-att", "name": "worker", "runtime_owner": "owner"},
                              self.runtime.status_callback("worker-att", "line", "owner"))
        self.runtime.live["worker-att"] = adapter

    async def test_the_production_close_route_records_its_stop_as_partyline_sent(self):
        with self.assertLogs("partyline.process_exit", level="INFO") as logs:
            await close_attachment(self.runtime, "worker-att")

        exit_lines = [line for line in logs.output if "exited from SIGTERM" in line]
        self.assertEqual(len(exit_lines), 1, logs.output)
        self.assertIn("sent by partyline: close_attachment (requested by none)", exit_lines[0])
        self.assertNotIn("external", exit_lines[0])
