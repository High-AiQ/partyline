"""The pre-2.33 legacy temp locations reap narrowly (finding 5.13)."""

import os
import tempfile
import time
import unittest
from pathlib import Path

from partyline.db import Db
from partyline.legacy_tmp import (
    PYTEST_MAX_AGE_SECONDS, reap_claude_temp, reap_legacy_temp, reap_pytest_temp,
)


def write_file(path: Path, size: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"x" * size)


class LegacyTmpTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.claude = Path(self.tmp.name, "claude-1000")
        self.pytest = Path(self.tmp.name, "pytest-of-tester")
        self.db = Db(f"{self.tmp.name}/partyline.db")
        self.addCleanup(self.db.close)
        self.db.create_conversation("line", "Line")
        self.db.add_attachment("live-1", "line", "a", "claude", ["claude"],
                               self.tmp.name)
        self.db._exec("UPDATE attachments SET status='running' WHERE id='live-1'")
        self.db.add_attachment("gone-1", "line", "b", "claude", ["claude"],
                               self.tmp.name)
        self.db._exec("UPDATE attachments SET status='exited' WHERE id='gone-1'")

    def test_only_closed_partyline_sessions_reap(self):
        write_file(self.claude / "line" / "live-1" / "scratch.bin", 64)
        write_file(self.claude / "line" / "gone-1" / "scratch.bin", 128)
        write_file(self.claude / "line" / "not-ours" / "keep.bin", 512)
        self.assertEqual(reap_claude_temp(self.db, self.claude), 128)
        self.assertTrue((self.claude / "line" / "live-1").exists())  # live: kept
        self.assertFalse((self.claude / "line" / "gone-1").exists())  # closed: reaped
        self.assertTrue((self.claude / "line" / "not-ours" / "keep.bin").exists())

    def test_a_symlinked_session_dir_is_never_removed(self):
        outside = Path(self.tmp.name, "outside")
        write_file(outside / "keep.bin", 32)
        (self.claude / "line").mkdir(parents=True, exist_ok=True)
        os.symlink(outside, self.claude / "line" / "gone-1")
        self.assertEqual(reap_claude_temp(self.db, self.claude), 0)
        self.assertTrue((outside / "keep.bin").exists())

    def test_old_pytest_runs_reap_and_current_survives(self):
        old = time.time() - PYTEST_MAX_AGE_SECONDS - 60
        write_file(self.pytest / "pytest-3" / "f.bin", 256)
        write_file(self.pytest / "pytest-7" / "f.bin", 128)
        os.utime(self.pytest / "pytest-3", (old, old))
        target = Path(self.tmp.name, "pytest-8")
        write_file(target / "f.bin", 4096)
        os.symlink(target, self.pytest / "pytest-current")
        os.utime(self.pytest / "pytest-current", (old, old))
        self.assertEqual(reap_pytest_temp(self.pytest, now=time.time()), 256)
        self.assertFalse((self.pytest / "pytest-3").exists())  # old run: reaped
        self.assertTrue((self.pytest / "pytest-7" / "f.bin").exists())  # fresh: kept
        self.assertTrue((self.pytest / "pytest-current").is_symlink())  # never removed
        self.assertTrue((target / "f.bin").exists())  # its target is untouched

    def test_a_non_run_name_is_never_a_candidate(self):
        write_file(self.pytest / "cache" / "f.bin", 77)
        os.utime(self.pytest / "cache", (time.time() - PYTEST_MAX_AGE_SECONDS * 5,) * 2)
        self.assertEqual(reap_pytest_temp(self.pytest, now=time.time()), 0)
        self.assertTrue((self.pytest / "cache" / "f.bin").exists())

    def test_reap_legacy_temp_reports_both_locations(self):
        write_file(self.claude / "line" / "gone-1" / "f", 50)
        write_file(self.pytest / "pytest-9" / "f", 25)
        os.utime(self.pytest / "pytest-9",
                 (time.time() - PYTEST_MAX_AGE_SECONDS - 10,) * 2)
        freed = reap_legacy_temp(self.db, claude=self.claude, pytest=self.pytest)
        self.assertEqual(freed, {"claude": 50, "pytest": 25})


if __name__ == "__main__":
    unittest.main()
