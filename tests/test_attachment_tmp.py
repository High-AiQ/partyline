"""Per-attachment temp directories: creation, env, guarded reaping, sizing (5.12)."""

import os
import stat
import tempfile
import unittest
from pathlib import Path

from partyline.attachment_tmp import (
    attachment_tmp_dir, base_dir, dir_size, ensure_tmp_dir, env_for, guarded_path,
    line_tmp_bytes, reap_line_tmp, reap_missing_tmp, reap_tmp_dir, tmp_resource_line,
    tmp_summary,
)
from partyline.db import Db


def write_file(path: Path, size: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"x" * size)


class AttachmentTmpTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name, "tmp")  # base_dir() becomes <tmp>/partyline
        os.environ["PARTYLINE_TMP_BASE"] = str(self.base)
        self.addCleanup(os.environ.pop, "PARTYLINE_TMP_BASE")

    def test_ensure_creates_a_private_dir_reused_by_the_same_id(self):
        first = Path(os.environ["PARTYLINE_TMP_BASE"], "partyline", "att-1")
        self.assertEqual(base_dir(), first.parent)
        self.assertEqual(ensure_tmp_dir({"id": "att-1"}), str(first))
        self.assertTrue(first.is_dir())
        self.assertEqual(stat.S_IMODE(first.stat().st_mode), 0o700)
        write_file(first / "left.txt", 10)
        self.assertEqual(ensure_tmp_dir({"id": "att-1"}), str(first))
        self.assertTrue((first / "left.txt").exists())  # same id, same dir, kept

    def test_env_for_points_the_three_temp_vars_at_the_dir(self):
        self.assertEqual(env_for({}), {})
        env = env_for({"tmp_dir": "/tmp/partyline/att-1"})
        self.assertEqual(env, {"TMPDIR": "/tmp/partyline/att-1",
                               "TMP": "/tmp/partyline/att-1",
                               "TEMP": "/tmp/partyline/att-1"})

    def test_reap_removes_the_dir_and_reports_its_bytes(self):
        directory = attachment_tmp_dir("att-2")
        directory.mkdir(parents=True)
        write_file(directory / "a.bin", 4096)
        write_file(directory / "sub" / "b.bin", 1024)
        self.assertEqual(reap_tmp_dir("att-2"), 5120)
        self.assertFalse(directory.exists())
        self.assertIsNone(reap_tmp_dir("att-2"))  # already gone

    def test_a_symlink_escape_is_refused(self):
        outside = Path(self.tmp.name, "outside")
        outside.mkdir()
        write_file(outside / "keep.txt", 8)
        base_dir().mkdir(parents=True, exist_ok=True)
        os.symlink(outside, attachment_tmp_dir("att-3"))
        self.assertIsNone(guarded_path("att-3"))
        self.assertIsNone(reap_tmp_dir("att-3"))
        self.assertTrue((outside / "keep.txt").exists())  # never followed out

    def test_size_math_walks_the_tree_and_skips_symlinks(self):
        directory = attachment_tmp_dir("att-4")
        directory.mkdir(parents=True)
        write_file(directory / "one", 100)
        write_file(directory / "two", 50)
        write_file(directory / "deep" / "three", 27)
        os.symlink("/etc/hostname", directory / "huge-link")
        self.assertEqual(dir_size(directory, budget=None), 177)

    def test_reap_line_and_missing_reaps(self):
        db = Db(f"{self.tmp.name}/partyline.db")
        self.addCleanup(db.close)
        db.create_conversation("line", "Line")
        db.add_attachment("live-1", "line", "a", "raw", ["cat"], self.tmp.name)
        db.add_attachment("gone-1", "line", "b", "raw", ["cat"], self.tmp.name)
        for att_id in ("live-1", "gone-1", "no-row-1"):
            attachment_tmp_dir(att_id).mkdir(parents=True)
            write_file(attachment_tmp_dir(att_id) / "f", 64)
        self.assertEqual(reap_line_tmp(db, "line"), 128)  # the line's own rows only
        self.assertFalse(attachment_tmp_dir("live-1").exists())
        self.assertTrue(attachment_tmp_dir("no-row-1").exists())
        freed, reaped = reap_missing_tmp(db)
        self.assertEqual((freed, reaped), (64, ["no-row-1"]))

    def test_summary_reports_mount_totals_and_the_partyline_share(self):
        directory = attachment_tmp_dir("att-5")
        directory.mkdir(parents=True)
        write_file(directory / "data", 4096)
        summary = tmp_summary(cached=False)
        self.assertIsNotNone(summary["tmp_total_bytes"])
        self.assertIsNotNone(summary["tmp_used_bytes"])
        self.assertGreaterEqual(summary["tmp_used_bytes"], summary["tmp_partyline_bytes"])
        self.assertGreaterEqual(summary["tmp_partyline_bytes"], 4096)

    def test_the_rider_names_the_mount_and_this_lines_share(self):
        db = Db(f"{self.tmp.name}/partyline.db")
        self.addCleanup(db.close)
        db.create_conversation("line", "Line")
        db.add_attachment("live-1", "line", "a", "raw", ["cat"], self.tmp.name)
        db._exec("UPDATE attachments SET status='running' WHERE id='live-1'")
        ensure_tmp_dir({"id": "live-1"})
        write_file(attachment_tmp_dir("live-1") / "f", 2048)
        rider = tmp_resource_line(db, "line")
        self.assertTrue(rider.startswith("(tmp: /tmp "))
        self.assertIn("GB · this line's processes", rider)
        self.assertTrue(rider.endswith(")"))
        self.assertGreater(line_tmp_bytes(db, "line"), 0)


if __name__ == "__main__":
    unittest.main()
