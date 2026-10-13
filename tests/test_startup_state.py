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
    boot_id, default_marker, interruption_notice, interruption_state,
    post_interruption_notices, take_marker, write_orderly_marker,
)


def this_boot(path: Path, name: str) -> str:
    path.write_text(f"{name}\n")
    return str(path)


class StartupStateTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db_path = Path(self.tmp.name, "partyline.db")
        self.marker = Path(default_marker(str(self.db_path)))
        self.boot = Path(self.tmp.name, "boot-id")

    def test_default_marker_sits_next_to_the_instance_database(self):
        # Per-instance keying (review B1): a dev instance's orderly restart
        # must never mask the production instance's crash.
        self.assertEqual(default_marker("/srv/partyline/prod.db"),
                         "/srv/partyline/prod.db.last-stop")
        self.assertIsNone(default_marker(None))

    def test_boot_id_reads_and_strips(self):
        self.boot.write_text("boot-123\n")
        self.assertEqual(boot_id(self.boot), "boot-123")
        self.assertIsNone(boot_id(Path(self.tmp.name, "missing")))

    def test_write_orderly_marker_records_boot_and_time(self):
        write_orderly_marker(str(self.db_path), boot_id_path=self.boot)
        payload = json.loads(self.marker.read_text())
        self.assertEqual(payload["boot"], boot_id(self.boot))
        self.assertLessEqual(payload["at"], time.time())

    def test_the_marker_is_consumed_exactly_once(self):
        # Review B1: a marker that survives startup makes every later crash
        # on the same boot read as orderly.
        self.boot.write_text("boot-abc\n")
        write_orderly_marker(str(self.db_path), boot_id_path=self.boot)
        self.assertIsNotNone(take_marker(self.marker))
        self.assertIsNone(take_marker(self.marker))

    def test_a_missing_marker_means_unplanned(self):
        self.boot.write_text("boot-abc\n")
        state = interruption_state(take_marker(self.marker), boot_id_path=self.boot)
        self.assertFalse(state["orderly"])
        self.assertFalse(state["rebooted"])

    def test_same_boot_marker_means_orderly(self):
        self.boot.write_text("boot-abc\n")
        self.marker.write_text(json.dumps({"boot": "boot-abc", "at": 1.0}))
        state = interruption_state(take_marker(self.marker), boot_id_path=self.boot)
        self.assertTrue(state["orderly"])

    def test_a_different_boot_means_the_host_rebooted(self):
        self.boot.write_text("boot-xyz\n")
        self.marker.write_text(json.dumps({"boot": "boot-abc", "at": 1.0}))
        state = interruption_state(take_marker(self.marker), boot_id_path=self.boot)
        self.assertFalse(state["orderly"])
        self.assertTrue(state["rebooted"])

    def test_two_instances_keep_separate_markers(self):
        other_db = Path(self.tmp.name, "dev.db")
        other_marker = Path(default_marker(str(other_db)))
        self.assertNotEqual(self.marker, other_marker)
        write_orderly_marker(str(other_db), boot_id_path=self.boot)
        self.assertFalse(self.marker.exists())  # the LAN instance wrote nothing
        self.assertTrue(other_marker.exists())

    def test_the_notice_names_what_was_running_and_the_rule(self):
        rows = [
            {"id": "1", "name": "sol", "conv_id": "line", "status": "running"},
            {"id": "2", "name": "nix", "conv_id": "line", "status": "starting"},
        ]
        bodies = interruption_notice({"orderly": False, "rebooted": True}, rows)
        self.assertIn("unplanned", bodies["line"])
        self.assertIn("the host rebooted", bodies["line"])
        self.assertIn("Processes that were running: @sol, @nix", bodies["line"])
        self.assertIn("Do not replay interrupted heavy work", bodies["line"])
        self.assertEqual(
            interruption_notice({"orderly": True, "rebooted": False}, rows), {})

    def test_marker_lifecycle_across_two_restarts(self):
        """Orderly restart, then a crash: the second start says unplanned."""
        db = Db(str(self.db_path))
        self.addCleanup(db.close)
        db.create_conversation("line", "Line")
        db.add_attachment("one", "line", "sol", "raw", ["cat"], self.tmp.name)
        db._exec("UPDATE attachments SET status='running' WHERE id='one'")
        runtime = ChatRuntime(db)
        runtime.broadcast = AsyncMock()
        this_boot(self.boot, "boot-one")

        # First start: this feature has run before? No marker and no watch
        # record yet, so the very first start stays silent (review fix).
        self.assertFalse(self._post(runtime))
        self.assertEqual(db.get_setting("interruption_watch_seen"), "1")

        # An orderly approved restart writes the marker; the next start with
        # the marker present and the same boot posts nothing.
        write_orderly_marker(str(self.db_path), boot_id_path=self.boot)
        self.assertFalse(self._post(runtime))

        # A crash leaves no marker: the next start says unplanned.
        self.assertTrue(self._post(runtime))
        bodies = " ".join(
            row["body"] for row in db._exec(
                "SELECT body FROM messages WHERE conv_id='line'").fetchall())
        self.assertIn("unplanned", bodies)
        self.assertIn("@sol", bodies)
        self.assertNotIn("the host rebooted", bodies)

    def _post(self, runtime) -> bool:
        import asyncio

        return asyncio.run(post_interruption_notices(
            runtime, marker_path=self.marker, boot_id_path=self.boot))


if __name__ == "__main__":
    unittest.main()
