"""Startup tells an orderly approved restart from an unplanned stop
(finding 5.14 item 6)."""

import json
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import AsyncMock

from partyline.db import Db
from partyline.runtime import ChatRuntime
from partyline.startup_state import (
    boot_id, interruption_notice, interruption_state, post_interruption_notices,
    write_orderly_marker,
)


def this_boot_id() -> str:
    marker = Path(tempfile.mkdtemp(), "boot")
    marker.write_text("boot-abc\n")
    return str(marker)


class StartupStateTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.marker = Path(self.tmp.name, "last-stop.json")
        self.boot = Path(self.tmp.name, "boot-id")

    def test_boot_id_reads_and_strips(self):
        self.boot.write_text("boot-123\n")
        self.assertEqual(boot_id(self.boot), "boot-123")
        self.assertIsNone(boot_id(Path(self.tmp.name, "missing")))

    def test_write_orderly_marker_records_boot_and_time(self):
        self.boot.write_text("boot-abc\n")
        write_orderly_marker(self.marker, boot_id_path=self.boot)
        payload = json.loads(self.marker.read_text())
        self.assertEqual(payload["boot"], "boot-abc")
        self.assertLessEqual(payload["at"], time.time())

    def test_a_missing_marker_means_unplanned(self):
        state = interruption_state(self.marker, self.boot)
        self.assertFalse(state["orderly"])
        self.assertFalse(state["rebooted"])

    def test_same_boot_marker_means_orderly(self):
        self.boot.write_text("boot-abc\n")
        self.marker.write_text(json.dumps({"boot": "boot-abc", "at": 1.0}))
        self.assertTrue(interruption_state(self.marker, self.boot)["orderly"])

    def test_a_different_boot_means_the_host_rebooted(self):
        self.boot.write_text("boot-xyz\n")
        self.marker.write_text(json.dumps({"boot": "boot-abc", "at": 1.0}))
        state = interruption_state(self.marker, self.boot)
        self.assertFalse(state["orderly"])
        self.assertTrue(state["rebooted"])

    def test_the_notice_names_the_mid_turn_processes_and_the_rule(self):
        rows = [
            {"id": "1", "name": "sol", "conv_id": "line", "status": "running"},
            {"id": "2", "name": "nix", "conv_id": "line", "status": "starting"},
        ]
        bodies = interruption_notice({"orderly": False, "rebooted": True}, rows)
        self.assertIn("unplanned", bodies["line"])
        self.assertIn("the host rebooted", bodies["line"])
        self.assertIn("@sol, @nix", bodies["line"])
        self.assertIn("Do not replay interrupted heavy work", bodies["line"])
        self.assertEqual(
            interruption_notice({"orderly": True, "rebooted": False}, rows), {})

    def test_posting_is_driven_by_the_state(self):
        db = Db(f"{self.tmp.name}/partyline.db")
        self.addCleanup(db.close)
        db.create_conversation("line", "Line")
        db.add_attachment("one", "line", "sol", "raw", ["cat"], self.tmp.name)
        db._exec("UPDATE attachments SET status='running' WHERE id='one'")
        runtime = ChatRuntime(db)
        runtime.broadcast = AsyncMock()
        self.boot.write_text("boot-abc\n")

        # Unplanned: the marker names an older boot.
        self.marker.write_text(json.dumps({"boot": "boot-abc-old", "at": 1.0}))
        self.assertTrue(self._post(runtime))
        bodies = " ".join(
            row["body"] for row in db._exec(
                "SELECT body FROM messages WHERE conv_id='line'").fetchall())
        self.assertIn("unplanned", bodies)
        self.assertIn("@sol", bodies)

        # Orderly: the marker names this boot, so nothing is posted — even
        # after the rows are settled.
        self.marker.write_text(json.dumps({"boot": "boot-abc", "at": 2.0}))
        self.assertFalse(self._post(runtime))

    def _post(self, runtime) -> bool:
        import asyncio

        return asyncio.run(post_interruption_notices(
            runtime, marker_path=self.marker, boot_id_path=self.boot))


if __name__ == "__main__":
    unittest.main()
