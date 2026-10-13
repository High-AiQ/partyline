"""Per-attachment temp directories: creation, env, guarded reaping, sizing (5.12)."""

import os
import stat
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from partyline import attachment_tmp
from partyline.attachment_tmp import (
    attachment_tmp_dir, base_dir, dir_size, ensure_tmp_dir, env_for, guarded_path,
    instance_key, line_tmp_bytes, reap_line_tmp, reap_missing_tmp, reap_tmp_dir,
    temp_root, tmp_resource_line, tmp_summary,
)
from partyline.auth_guard import Principal
from partyline.db import Db
from partyline.runtime import ChatRuntime
from partyline.tmp_reap_routes import register_tmp_reap_routes


def write_file(path: Path, size: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"x" * size)


def pin_tmp_base(testcase, path: Path) -> None:
    """Pin the temp base for one test, restoring whatever was there before."""
    saver = patch.dict(os.environ, {"PARTYLINE_TMP_BASE": str(path)})
    saver.start()
    testcase.addCleanup(saver.stop)


class AttachmentTmpTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name, "tmp")  # base_dir() is <tmp>/partyline/<key>
        pin_tmp_base(self, self.base)

    def test_ensure_creates_a_scoped_private_dir_reused_by_the_same_id(self):
        first = attachment_tmp_dir("att-1")
        self.assertEqual(base_dir(), first.parent)
        self.assertEqual(first.parent.name, instance_key())
        self.assertRegex(instance_key(), r"[0-9a-f]{12}")
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

    def test_a_base_reached_through_a_symlinked_parent_still_reaps(self):
        # macOS's temp is /var/folders, a symlink away from /private/var: the
        # parents compare resolved, so such a base must reap, not refuse.
        real = Path(self.tmp.name, "real-temp")
        link = Path(self.tmp.name, "linked-temp")
        real.mkdir()
        os.symlink(real, link)
        pin_tmp_base(self, link)
        directory = attachment_tmp_dir("att-mac")
        directory.mkdir(parents=True)
        write_file(directory / "f", 16)
        self.assertIsNotNone(guarded_path("att-mac"))
        self.assertEqual(reap_tmp_dir("att-mac"), 16)

    def test_size_math_walks_the_tree_and_skips_symlinks(self):
        directory = attachment_tmp_dir("att-4")
        directory.mkdir(parents=True)
        write_file(directory / "one", 100)
        write_file(directory / "two", 50)
        write_file(directory / "deep" / "three", 27)
        os.symlink("/etc/hostname", directory / "huge-link")
        self.assertEqual(dir_size(directory, budget=None), 177)

    def test_reap_line_and_missing_reaps_skip_foreign_scopes_and_names(self):
        db = Db(f"{self.tmp.name}/partyline.db")
        self.addCleanup(db.close)
        db.create_conversation("line", "Line")
        db.add_attachment("live-1", "line", "a", "raw", ["cat"], self.tmp.name)
        db.add_attachment("gone-1", "line", "b", "raw", ["cat"], self.tmp.name)
        for att_id in ("live-1", "gone-1", "no-row-1"):
            attachment_tmp_dir(att_id).mkdir(parents=True)
            write_file(attachment_tmp_dir(att_id) / "f", 64)
        # another partyline instance on this host, and a non-id entry: both
        # live outside this instance's authority
        other = temp_root() / "partyline" / "deadbeefcafe1234"
        write_file(other / "somewhere-else" / "f", 99)
        write_file(base_dir() / "cache.bin", 7)
        self.assertEqual(reap_line_tmp(db, "line"), 128)  # the line's own rows only
        self.assertTrue((other / "somewhere-else" / "f").exists())
        self.assertTrue((base_dir() / "cache.bin").exists())
        freed, reaped = reap_missing_tmp(db)
        self.assertEqual((freed, reaped), (64, ["no-row-1"]))
        self.assertTrue((other / "somewhere-else" / "f").exists())
        self.assertTrue((base_dir() / "cache.bin").exists())

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
        db.create_conversation("other", "Other")
        db.add_attachment("live-1", "line", "a", "raw", ["cat"], self.tmp.name)
        db._exec("UPDATE attachments SET status='running' WHERE id='live-1'")
        db.add_attachment("live-2", "other", "b", "raw", ["cat"], self.tmp.name)
        db._exec("UPDATE attachments SET status='running' WHERE id='live-2'")
        ensure_tmp_dir({"id": "live-1"})
        write_file(attachment_tmp_dir("live-1") / "f", 2048)
        ensure_tmp_dir({"id": "live-2"})
        write_file(attachment_tmp_dir("live-2") / "f", 4096)
        attachment_tmp.cached_usage(cached=False)  # fill the cache once
        rider = tmp_resource_line(db, "line")
        self.assertTrue(rider.startswith(f"(tmp: /{temp_root().name} "))
        self.assertIn("GB · this line's processes", rider)
        # Finding 5.13: the rider names the top lines by temp for everyone,
        # not only the reader's own line.
        self.assertIn("top tmp: «Other»", rider)
        self.assertIn("«Line»", rider)
        self.assertTrue(rider.endswith(")"))
        self.assertGreater(line_tmp_bytes(db, "line"), 0)

    def test_riders_within_the_ttl_read_the_cache_instead_of_walking(self):
        db = Db(f"{self.tmp.name}/partyline.db")
        self.addCleanup(db.close)
        db.create_conversation("line", "Line")
        db.add_attachment("live-1", "line", "a", "raw", ["cat"], self.tmp.name)
        db._exec("UPDATE attachments SET status='running' WHERE id='live-1'")
        ensure_tmp_dir({"id": "live-1"})
        attachment_tmp.cached_usage(cached=False)  # one fresh walk, then TTL
        with patch.object(attachment_tmp, "dir_size", return_value=0) as walk:
            tmp_resource_line(db, "line")
            tmp_resource_line(db, "line")
            self.assertEqual(walk.call_count, 0)  # riders never touch the disk


class CloseReapTest(unittest.IsolatedAsyncioTestCase):
    """Close reaps the temp dir; an internal detach never does (5.12)."""

    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        pin_tmp_base(self, Path(self.tmp.name, "tmp"))
        self.db = Db(f"{self.tmp.name}/partyline.db")
        self.addCleanup(self.db.close)
        self.db.create_conversation("line", "Line")
        self.db.add_attachment("det-1", "line", "d", "raw", ["cat"], self.tmp.name)
        self.db._exec("UPDATE attachments SET status='detached' WHERE id='det-1'")
        self.runtime = ChatRuntime(self.db)
        self.runtime.broadcast = AsyncMock()
        self.runtime.broadcast_attachment = AsyncMock()
        ensure_tmp_dir({"id": "det-1"})

    async def test_an_internal_detach_keeps_the_directory(self):
        from partyline.line_process_routes import detach_attachment

        self.assertTrue((await detach_attachment(self.runtime, "det-1"))["ok"])
        self.assertTrue(attachment_tmp_dir("det-1").exists())

    async def test_the_close_reaps_the_directory(self):
        from partyline.line_process_routes import close_attachment

        self.assertTrue((await close_attachment(self.runtime, "det-1"))["ok"])
        self.assertFalse(attachment_tmp_dir("det-1").exists())


class TmpReapRouteTest(unittest.TestCase):
    """POST …/tmp/reap: the root captain or a person; rows that can resume stay."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        pin_tmp_base(self, Path(self.tmp.name, "tmp"))
        self.db = Db(f"{self.tmp.name}/partyline.db")
        self.addCleanup(self.db.close)
        self.db.create_conversation("root", "Root")
        self.db.create_conversation("kid", "Kid")
        self.db._exec("UPDATE conversations SET parent_id='root' WHERE id='kid'")
        self.db.add_attachment("rootcap", "root", "cap", "raw", ["cat"], self.tmp.name)
        self.db._exec("UPDATE attachments SET is_lead=1, status='running' WHERE id='rootcap'")
        self.db.add_attachment("kidcap", "kid", "sub", "raw", ["cat"], self.tmp.name)
        self.db._exec("UPDATE attachments SET is_lead=1, status='running' WHERE id='kidcap'")
        self.db.add_attachment("kid-live", "kid", "w", "raw", ["cat"], self.tmp.name)
        self.db._exec("UPDATE attachments SET status='running' WHERE id='kid-live'")
        self.db.add_attachment("kid-det", "kid", "d", "raw", ["cat"], self.tmp.name)
        self.db._exec("UPDATE attachments SET status='detached' WHERE id='kid-det'")
        for att_id in ("kid-live", "kid-det", "leftover"):
            attachment_tmp_dir(att_id).mkdir(parents=True)
            write_file(attachment_tmp_dir(att_id) / "f", 32)
        app = FastAPI()

        @app.middleware("http")
        async def identify(request, call_next):
            request.state.principal = Principal(
                kind=request.headers.get("x-kind", "user"),
                name=request.headers.get("x-name", "greg"),
                conv_id=request.headers.get("x-conv"),
                attachment_id=request.headers.get("x-att"),
                is_lead=request.headers.get("x-lead") == "1",
            )
            return await call_next(request)

        register_tmp_reap_routes(app, SimpleNamespace(db=self.db))
        self.client = TestClient(app)

    def reap(self, conv="root", **headers):
        # kwargs cannot carry dashes; the tests speak x_kind, HTTP wants x-kind
        return self.client.post(f"/api/conversations/{conv}/tmp/reap",
                                headers={k.replace("_", "-"): v
                                         for k, v in headers.items()})

    def test_a_person_reaps_only_the_dirs_that_cannot_resume(self):
        answer = self.reap()
        self.assertEqual(answer.status_code, 200, answer.text)
        self.assertEqual(answer.json()["reaped"], ["leftover"])
        self.assertEqual(answer.json()["freed_bytes"], 32)
        self.assertTrue(attachment_tmp_dir("kid-live").exists())
        self.assertTrue(attachment_tmp_dir("kid-det").exists())  # resumable: kept

    def test_a_machine_that_is_not_the_root_captain_is_refused(self):
        refused = self.reap(x_kind="machine", x_name="kidcap", x_conv="kid",
                            x_att="kidcap", x_lead="1")
        self.assertEqual(refused.status_code, 403, refused.text)
        worker = self.reap(x_kind="machine", x_name="w", x_conv="kid",
                           x_att="kid-live")
        self.assertEqual(worker.status_code, 403, worker.text)

    def test_the_live_root_captain_may_reap(self):
        answer = self.reap(x_kind="machine", x_name="cap", x_conv="root",
                           x_att="rootcap", x_lead="1")
        self.assertEqual(answer.status_code, 200, answer.text)
        self.assertEqual(answer.json()["reaped"], ["leftover"])

    def test_a_root_captain_that_is_not_live_is_refused(self):
        self.db._exec("UPDATE attachments SET status='detached' WHERE id='rootcap'")
        refused = self.reap(x_kind="machine", x_name="cap", x_conv="root",
                            x_att="rootcap", x_lead="1")
        self.assertEqual(refused.status_code, 403, refused.text)


if __name__ == "__main__":
    unittest.main()
