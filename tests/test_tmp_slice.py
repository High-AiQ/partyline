"""Finding 5.15: where process temp lives, how it is judged, and what moving it may delete."""

import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from partyline import attachment_tmp
from partyline.attachment_tmp import base_dir, ensure_tmp_dir, instance_key, temp_root
from partyline.cgroup_sample import cgroup_usage, read_cgroup_sample, reclaim_scope
from partyline.memory_warning import SHMEM_NOTICE_BYTES, tmpfs_note, tmpfs_note_for
from partyline.temp_mounts import fstype_of, largest_dir_under, on_tmpfs
from partyline.tmp_levels import private_level
from partyline.tmp_migration import in_use, live_paths, reap_previous_tmp_root

GIB = 1024**3


def mountinfo(directory: str, *mounts: tuple[str, str]) -> str:
    path = Path(directory, "mountinfo")
    path.write_text(
        "".join(f"{n} 1 0:{n} / {point} rw - {fs} {fs} rw\n" for n, (point, fs) in enumerate(mounts, 30)),
        encoding="utf-8",
    )
    return str(path)


class Scratch(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(os.path.realpath(self.tmp.name))


class TempMountsTest(Scratch):
    def test_the_longest_matching_mount_decides_and_escapes_are_decoded(self):
        spaced = self.root / "a b"
        spaced.mkdir()
        info = mountinfo(
            self.tmp.name,
            ("/", "ext4"),
            (str(self.root), "tmpfs"),
            (str(spaced).replace(" ", "\\040"), "ext4"),
        )
        self.assertEqual(fstype_of(self.root / "x", info), "tmpfs")
        self.assertEqual(fstype_of(spaced / "inner", info), "ext4")  # \040 means a space
        self.assertFalse(on_tmpfs(spaced, info))
        self.assertTrue(on_tmpfs(self.root, info))

    def test_a_symlink_is_judged_by_where_it_lands(self):
        disk = self.root / "disk"
        ram = self.root / "ram"
        disk.mkdir(), ram.mkdir()
        (self.root / "link").symlink_to(ram)
        info = mountinfo(self.tmp.name, ("/", "ext4"), (str(ram), "tmpfs"))
        self.assertTrue(on_tmpfs(self.root / "link", info))
        self.assertFalse(on_tmpfs(disk, info))

    def test_missing_mount_information_is_unknown(self):
        self.assertIsNone(fstype_of(self.root, str(self.root / "nope")))
        bad = self.root / "bad"
        bad.write_text("no dash here\n36 35 98:0 / /mnt rw -\n", encoding="utf-8")
        self.assertIsNone(fstype_of(self.root, str(bad)))

    def test_the_largest_directory_is_found_at_any_depth_and_symlinks_are_skipped(self):
        (self.root / "small").mkdir()
        (self.root / "small" / "f").write_bytes(b"x" * 10)
        (self.root / "big" / "deep").mkdir(parents=True)
        (self.root / "big" / "deep" / "f").write_bytes(b"x" * 500)
        (self.root / "link").symlink_to("/etc")
        self.assertEqual(largest_dir_under(self.root), (str(self.root / "big" / "deep"), 500))
        self.assertIsNone(largest_dir_under(self.root / "missing"))
        self.assertIsNone(largest_dir_under(self.root / "small", budget_seconds=-1))


class TempRootTest(Scratch):
    def pick(self, *mounts):
        var_tmp = self.root / "vartmp"
        var_tmp.mkdir(exist_ok=True)
        info = mountinfo(
            self.tmp.name, *[(str(self.root if p == "TMP" else var_tmp), fs) for p, fs in mounts]
        )
        env = {k: v for k, v in os.environ.items() if k != "PARTYLINE_TMP_BASE"}
        with (
            patch.dict(os.environ, env, clear=True),
            patch("partyline.attachment_tmp.tempfile.gettempdir", return_value=str(self.root)),
            patch("partyline.attachment_tmp.sys.platform", "linux"),
        ):
            return temp_root(mountinfo=info, var_tmp=str(var_tmp)), var_tmp

    def test_var_tmp_is_chosen_when_the_platform_temp_is_tmpfs(self):
        chosen, var_tmp = self.pick(("TMP", "tmpfs"), ("VAR", "ext4"))
        self.assertEqual(chosen, var_tmp)

    def test_the_platform_temp_stays_when_it_is_already_on_disk(self):
        chosen, _ = self.pick(("TMP", "ext4"), ("VAR", "ext4"))
        self.assertEqual(chosen, self.root)

    def test_a_tmpfs_var_tmp_keeps_the_platform_temp(self):
        chosen, _ = self.pick(("TMP", "tmpfs"), ("VAR", "tmpfs"))
        self.assertEqual(chosen, self.root)

    def test_an_unwritable_var_tmp_keeps_the_platform_temp(self):
        with patch("partyline.attachment_tmp.os.access", return_value=False):
            chosen, _ = self.pick(("TMP", "tmpfs"), ("VAR", "ext4"))
        self.assertEqual(chosen, self.root)

    def test_the_pin_wins_and_other_platforms_keep_their_temp(self):
        with patch.dict(os.environ, {"PARTYLINE_TMP_BASE": str(self.root / "pin")}):
            self.assertEqual(temp_root(), self.root / "pin")
        info = mountinfo(self.tmp.name, (str(self.root), "tmpfs"))
        env = {k: v for k, v in os.environ.items() if k != "PARTYLINE_TMP_BASE"}
        with (
            patch.dict(os.environ, env, clear=True),
            patch("partyline.attachment_tmp.tempfile.gettempdir", return_value=str(self.root)),
            patch("partyline.attachment_tmp.sys.platform", "darwin"),
        ):
            self.assertEqual(temp_root(mountinfo=info), self.root)


class PrivateLevelsTest(Scratch):
    def setUp(self):
        super().setUp()
        pin = patch.dict(os.environ, {"PARTYLINE_TMP_BASE": str(self.root / "shared")})
        pin.start()
        self.addCleanup(pin.stop)
        self.att = {"id": "att-1"}

    def test_new_levels_are_0700_and_the_root_is_left_as_it_is(self):
        (self.root / "shared").mkdir(mode=0o777)
        os.chmod(self.root / "shared", 0o777)
        path = Path(ensure_tmp_dir(self.att))
        self.assertEqual(path, base_dir() / "att-1")
        for level in (path, path.parent, path.parent.parent):
            self.assertEqual(level.stat().st_mode & 0o777, 0o700, level)
        self.assertEqual((self.root / "shared").stat().st_mode & 0o777, 0o777)  # not ours to change
        self.assertEqual(ensure_tmp_dir(self.att), str(path))  # idempotent

    def test_a_level_with_group_or_other_write_is_tightened(self):
        shared = self.root / "shared" / "partyline"
        shared.mkdir(parents=True)
        os.chmod(shared, 0o777)
        ensure_tmp_dir(self.att)
        self.assertEqual(shared.stat().st_mode & 0o777, 0o700)

    def test_a_symlinked_level_is_refused(self):
        (self.root / "shared").mkdir()
        elsewhere = self.root / "elsewhere"
        elsewhere.mkdir()
        (self.root / "shared" / "partyline").symlink_to(elsewhere)
        with self.assertRaisesRegex(PermissionError, "symlink"):
            ensure_tmp_dir(self.att)
        self.assertEqual(list(elsewhere.iterdir()), [])

    def test_a_level_owned_by_someone_else_is_refused(self):
        (self.root / "shared" / "partyline").mkdir(parents=True)
        with patch("partyline.tmp_levels.os.getuid", return_value=os.getuid() + 1):
            with self.assertRaisesRegex(PermissionError, "owned by uid"):
                ensure_tmp_dir(self.att)

    def test_a_plain_file_in_the_way_is_refused_and_windows_just_makes_it(self):
        blocked = self.root / "file"
        blocked.write_text("x")
        with self.assertRaises(PermissionError):
            private_level(blocked)
        with patch("partyline.tmp_levels.hasattr", return_value=False, create=True):
            private_level(self.root / "made")
        self.assertTrue((self.root / "made").is_dir())


class PreviousRootTest(Scratch):
    def setUp(self):
        super().setUp()
        self.platform_tmp = self.root / "platform"
        self.disk = self.root / "disk"
        self.platform_tmp.mkdir()
        self.disk.mkdir()
        for target in (
            patch("partyline.tmp_migration.tempfile.gettempdir", return_value=str(self.platform_tmp)),
            patch.dict(os.environ, {"PARTYLINE_TMP_BASE": str(self.disk)}),
        ):
            target.start()
            self.addCleanup(target.stop)
        self.old = self.platform_tmp / "partyline" / instance_key()
        (self.old / "old-1").mkdir(parents=True)
        (self.old / "old-1" / "f").write_bytes(b"x" * 64)
        self.proc = self.root / "proc"
        self.proc.mkdir()

    def fake_process(self, pid, cwd=None, environ=b""):
        directory = self.proc / str(pid)
        directory.mkdir()
        if cwd:
            (directory / "cwd").symlink_to(cwd)
        (directory / "environ").write_bytes(environ)

    def test_a_symlinked_var_tmp_that_is_the_same_directory_deletes_nothing(self):
        shutil.rmtree(self.disk)
        self.disk.symlink_to(self.platform_tmp)  # /var/tmp -> /tmp
        self.assertEqual(os.path.realpath(base_dir()), str(self.platform_tmp / "partyline" / instance_key()))
        self.assertEqual(reap_previous_tmp_root(None, proc=str(self.proc)), 0)
        self.assertTrue((self.old / "old-1" / "f").exists())
        # the same answer when the two spellings differ only by a link in the path
        alias = self.root / "alias"
        alias.symlink_to(self.platform_tmp)
        with patch.dict(os.environ, {"PARTYLINE_TMP_BASE": str(alias)}):
            self.assertEqual(reap_previous_tmp_root(None, proc=str(self.proc)), 0)
        self.assertTrue((self.old / "old-1" / "f").exists())

    def test_idle_directories_go_and_the_empty_root_is_removed(self):
        (self.old / "keepsake.txt").write_text("not an id")
        self.assertEqual(reap_previous_tmp_root(None, proc=str(self.proc)), 64)
        self.assertFalse((self.old / "old-1").exists())
        self.assertTrue((self.old / "keepsake.txt").exists())
        (self.old / "keepsake.txt").unlink()
        (self.old / "old-2").mkdir()
        reap_previous_tmp_root(None, proc=str(self.proc))
        self.assertFalse(self.old.exists())

    def test_a_directory_a_live_process_works_in_or_points_its_temp_at_survives(self):
        for name in ("cwd-1", "env-1", "free-1"):
            (self.old / name / "sub").mkdir(parents=True)
            (self.old / name / "sub" / "f").write_bytes(b"x")
        self.fake_process(11, cwd=self.old / "cwd-1" / "sub")
        self.fake_process(12, environ=b"PATH=/bin\0TMPDIR=" + str(self.old / "env-1").encode() + b"\0")
        self.fake_process(13, environ=b"TEMP=" + str(self.old / "old-1" / "x").encode())
        reap_previous_tmp_root(None, proc=str(self.proc))
        self.assertTrue((self.old / "cwd-1").exists())
        self.assertTrue((self.old / "env-1").exists())
        self.assertTrue((self.old / "old-1").exists())  # a TEMP below it counts too
        self.assertFalse((self.old / "free-1").exists())

    def test_live_path_scan_is_best_effort(self):
        self.assertEqual(live_paths(str(self.root / "no-proc")), set())
        (self.proc / "9").mkdir()  # no cwd, no environ: unreadable, skipped
        (self.proc / "self").mkdir()
        self.assertEqual(live_paths(str(self.proc)), set())
        self.assertTrue(in_use(self.old, {str(self.old / "old-1")}))
        self.assertFalse(in_use(self.old / "old-1", {str(self.old / "old-10")}))

    def test_symlinks_foreign_roots_and_odd_names_are_left_alone(self):
        (self.old / "bad name").mkdir()
        (self.old / "link-1").symlink_to(self.disk)
        self.assertEqual(reap_previous_tmp_root(None, proc=str(self.proc)), 64)
        self.assertTrue((self.old / "bad name").exists() and (self.old / "link-1").is_symlink())
        shutil.rmtree(self.old)
        elsewhere = self.root / "elsewhere"
        (elsewhere / "old-9").mkdir(parents=True)
        self.old.symlink_to(elsewhere)
        self.assertEqual(reap_previous_tmp_root(None, proc=str(self.proc)), 0)
        self.assertTrue((elsewhere / "old-9").exists())
        self.old.unlink()
        self.assertEqual(reap_previous_tmp_root(None, proc=str(self.proc)), 0)  # no old root
        self.old.mkdir()
        with patch("partyline.tmp_migration.os.getuid", return_value=os.getuid() + 1):
            self.assertEqual(reap_previous_tmp_root(None, proc=str(self.proc)), 0)


class CgroupSampleTest(Scratch):
    def scope(self, _name="scope", **files):
        scope = self.root / _name
        scope.mkdir(exist_ok=True)
        for name, text in files.items():
            (scope / name.replace("_", ".")).write_text(text, encoding="ascii")
        return str(scope)

    def test_the_sample_reports_working_set_peak_and_shared_memory(self):
        root = self.scope(
            memory_current="1000\n",
            memory_peak="1200\n",
            memory_stat=("anon 5\ninactive_file 300\nactive_file 9\nshmem 70\n"
                         "file 309\nkernel 40\nslab 25\n"),
        )
        self.assertEqual(
            read_cgroup_sample(root),
            {"root": root, "current": 1000, "peak": 1200, "anon": 5,
             "file": 309, "inactive_file": 300, "active_file": 9,
             "kernel": 40, "slab": 25, "shmem": 70, "kernel_total": 686,
             "working_set": 761},
        )

    def test_missing_or_broken_files_degrade_without_raising(self):
        root = self.scope(memory_current="500\n", memory_stat="inactive_file 900\nshmem x\n")
        sample = read_cgroup_sample(root)
        self.assertEqual((sample["peak"], sample["working_set"], sample["shmem"]), (None, 0, 0))
        self.assertIsNone(read_cgroup_sample(self.scope("junk", memory_current="nope\n")))
        self.assertIsNone(read_cgroup_sample(str(self.root / "absent")))
        bare = read_cgroup_sample(self.scope("bare", memory_current="7\n", memory_peak="bad\n"))
        self.assertEqual((bare["peak"], bare["working_set"]), (None, 7))
        self.assertIsNone(bare["anon"])
        self.assertIsNone(bare["file"])

    def test_at_risk_usage_is_never_below_anonymous_memory(self):
        root = self.scope(
            memory_current="500\n",
            memory_stat="anon 600\nfile 100\nshmem 0\n",
        )
        self.assertEqual(read_cgroup_sample(root)["working_set"], 600)

    def test_old_stat_falls_back_to_inactive_file_working_set(self):
        root = self.scope(
            memory_current="1000\n",
            memory_stat="inactive_file 300\nactive_file 500\nshmem 70\n",
        )
        sample = read_cgroup_sample(root)
        self.assertEqual(sample["working_set"], 700)
        self.assertIsNone(sample["anon"])
        self.assertIsNone(sample["file"])
        self.assertIsNone(sample["kernel_total"])

    @unittest.skipUnless(sys.platform.startswith("linux"), "reads /proc/<pid>/cgroup")
    def test_the_scope_of_a_process_is_found_through_its_cgroup_file(self):
        with open("/proc/self/cgroup", encoding="ascii") as stream:
            relative = next(
                (line.split("::", 1)[1].strip() for line in stream if line.startswith("0::")), None
            )
        if relative is None:
            self.skipTest("not a cgroup v2 host")
        base = self.root / "cgroups"
        scope = base / relative.lstrip("/")
        scope.mkdir(parents=True)
        (scope / "memory.current").write_text("42\n")
        self.assertEqual(cgroup_usage(os.getpid(), str(base))["current"], 42)
        self.assertIsNone(cgroup_usage(os.getpid(), str(self.root / "none")))
        self.assertIsNone(cgroup_usage(2**22 + 12345))

    def test_reclaim_writes_the_amount_and_reports_failure(self):
        root = self.scope()
        self.assertTrue(reclaim_scope(root, 0))
        self.assertFalse((Path(root) / "memory.reclaim").exists())
        self.assertTrue(reclaim_scope(root, 4096))
        self.assertEqual((Path(root) / "memory.reclaim").read_text(), "4096")
        self.assertFalse(reclaim_scope(str(self.root / "missing" / "scope"), 4096))


class TmpfsNoteTest(Scratch):
    def test_nothing_under_the_threshold(self):
        self.assertIsNone(tmpfs_note(SHMEM_NOTICE_BYTES, "/t", ("/t/x", 1)))

    def test_on_tmpfs_the_directory_is_named_and_off_tmpfs_only_the_sources_are(self):
        named = tmpfs_note(2 * GIB, "/t", ("/t/models", GIB))
        self.assertIn("2.0 GiB of this is files on tmpfs (largest under /t: /t/models 1.0 GiB)", named)
        generic = tmpfs_note(2 * GIB, "/t", None, tmp_on_tmpfs=False)
        self.assertIn("shared memory", generic)
        self.assertIn("/dev/shm", generic)
        self.assertNotIn("largest under", generic)
        self.assertIn("2.0 GiB of this is files on tmpfs.", tmpfs_note(2 * GIB, "/t", None))

    async def _note(self, on):
        (self.root / "models").mkdir(exist_ok=True)
        (self.root / "models" / "w").write_bytes(b"x" * 100)
        with patch("partyline.temp_mounts.on_tmpfs", return_value=on):
            return await tmpfs_note_for(str(self.root), 2 * GIB)

    def test_the_note_follows_the_filesystem_of_the_processs_own_temp(self):
        import asyncio

        self.assertIn(f"largest under {self.root}", asyncio.run(self._note(True)))
        disk = asyncio.run(self._note(False))
        self.assertIn("/dev/shm", disk)
        self.assertNotIn(str(self.root), disk)
        self.assertIsNone(asyncio.run(tmpfs_note_for(str(self.root), 1)))


@unittest.skipIf(os.name == "nt", "the Windows sandbox keeps the platform temp")
class SandboxTest(unittest.TestCase):
    def test_tests_never_use_the_real_tmp(self):
        sandbox = Path(tempfile.gettempdir())
        self.assertNotEqual(os.path.realpath(sandbox), os.path.realpath("/tmp"))
        self.assertTrue(attachment_tmp.temp_root().is_relative_to(sandbox))
        self.assertEqual(os.environ["TMPDIR"], str(sandbox))


if __name__ == "__main__":
    unittest.main()
