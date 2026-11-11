"""Advisory warnings preserve routing, cleanup, and process memory behavior."""

import tempfile
from pathlib import Path
import os
import time
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from partyline.db import Db
from partyline.attachment_tmp import attachment_tmp_dir
from partyline import memory_event_policy
from partyline.memory_sampler import (
    _warn, crosses_warning, process_tree_rss,
    warning_limit, warning_text,
)
from partyline.runtime import ChatRuntime


class MemorySamplerTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.db = Db(f"{self.temp.name}/partyline.db")
        self.addCleanup(self.db.close)
        self.db.create_conversation("line", "Line", captain_mode="manager_tree")
        self.db.add_attachment("worker", "line", "worker", "fake", ["fake"], self.temp.name)
        self.db._exec("UPDATE attachments SET status='running',memory_limit='1G' WHERE id='worker'")
        self.runtime = SimpleNamespace(db=self.db, live={"worker": object()}, memory_usage={})
        self.runtime.broadcast = AsyncMock()

    def test_threshold_and_cross_platform_tree_rss(self):
        self.assertTrue(crosses_warning(800, 1000, 80))
        self.assertFalse(crosses_warning(799, 1000, 80))
        completed = SimpleNamespace(returncode=0, stdout="10 1 100\n11 10 200\n20 1 500\n")
        with patch("subprocess.run", return_value=completed):
            self.assertEqual(process_tree_rss(10, "darwin"), 300 * 1024)

    def test_warning_text_uses_a_ceiling_bounded_request_and_human_units(self):
        with patch("partyline.memory_warning.memory_ceiling", return_value=6 * 1024**3):
            text = warning_text({"id": "worker", "name": "worker"},
                                3_600_000_000, 4 * 1024**3)
        self.assertIn("3.4 GiB of its 4.0 GiB per-process memory budget (83%)", text)
        self.assertIn("approval restarts the process", text)
        self.assertIn('/api/attachments/worker/memory-requests', text)
        self.assertIn('"requested_limit":"6G"', text)

    def test_own_warning_says_what_the_host_does_at_the_cap(self):
        row = {"id": "worker", "name": "worker"}
        cases = {"linux": "emergency backstop the kernel kills this process",
                 "win32": "allocations past it fail",
                 "darwin": "cannot enforce the budget on resident memory"}
        for platform, phrase in cases.items():
            with self.subTest(platform), \
                    patch("partyline.memory_warning.sys.platform", platform):
                text = warning_text(row, 9, 10, own=True)
            self.assertIn(phrase, text)
            self.assertIn("Commit or save your work now", text)

    async def test_self_warning_really_rings_the_warned_process(self):
        self.db._exec("UPDATE attachments SET is_lead=1 WHERE id='worker'")
        runtime = ChatRuntime(self.db)
        runtime.live["worker"] = SimpleNamespace(att=self.db.get_attachment("worker"))
        runtime.deliver_pending = AsyncMock(return_value=True)
        row = {"id": "worker", "name": "worker", "conv_id": "line"}
        await _warn(runtime, row, 3 * 1024**3, 4 * 1024**3)
        rung = [call.args[1]["id"] for call in runtime.deliver_pending.await_args_list]
        self.assertEqual(rung, ["worker"])

    def test_host_clamp_changes_linux_warning_limit_and_both_warning_copies(self):
        gib = 1024**3
        row = {'id': 'worker', 'name': 'worker'}
        with patch('partyline.server_memory.host_memory_bytes', return_value=8 * gib):
            for platform in ('linux', 'win32', 'darwin'):
                with self.subTest(platform=platform), \
                        patch('partyline.memory_sampler.sys.platform', platform), \
                        patch('partyline.memory_warning.sys.platform', platform):
                    self.assertEqual(warning_limit(8 * gib), (6 if platform == 'linux' else 8) * gib)
                    self.assertEqual(warning_limit(4 * gib), 4 * gib)
            with patch('partyline.memory_sampler.sys.platform', 'linux'):
                for budget in (6 * gib, 8 * gib):
                    for own in (True, False):
                        text = warning_text(row, 5 * gib, budget, own=own)
                        self.assertIn('6.0 GiB emergency backstop is at or below', text)
                        self.assertIn('Warnings use the backstop', text)
                        self.assertNotIn('nothing stops you there', text)


    def _hot_runtime(self, shmem=0):
        gib = 1024**3
        runtime = ChatRuntime(self.db)
        runtime.live["worker"] = SimpleNamespace(
            att=self.db.get_attachment("worker"), proc=SimpleNamespace(pid=123))
        runtime.deliver_pending = AsyncMock(return_value=True)
        sample = {"root": str(Path(self.temp.name, "scope")), "current": 980 * 1024**2,
                  "peak": None, "shmem": shmem, "working_set": 960 * 1024**2}
        return runtime, sample, gib

    async def _run_events(self, runtime, sample, gib, events=1, **patches):
        async def refresh(runtime):
            usage, raw = sample["working_set"], sample["current"]
            runtime.memory_usage["worker"] = {
                "usage_bytes": usage, "raw_bytes": raw, "cap_bytes": gib,
                "percent": usage * 100 // gib, "cgroup": sample,
            }
            return {"worker"}

        with patch("partyline.memory_sampler.sys.platform", "linux"), \
                patch("partyline.server_memory.host_memory_bytes", return_value=gib * 8), \
                patch("partyline.memory_event_policy.refresh", side_effect=refresh):
            with patch("partyline.temp_mounts.on_tmpfs", **patches):
                policy = memory_event_policy.MemoryPolicy()
                for _ in range(events):
                    await policy.handle(runtime, None, sample["working_set"] >= gib * 0.8)

    async def test_reclaim_does_not_depend_on_where_temp_lives(self):
        """The reclaim runs on every filesystem: the cgroup directory is cgroup2, never tmpfs."""
        scope = Path(self.temp.name, "scope")
        scope.mkdir()
        runtime, sample, gib = self._hot_runtime()
        sample.update(root=str(scope), working_set=100 * 1024**2, current=900 * 1024**2)
        for on_tmpfs in (True, False):
            (scope / "memory.reclaim").unlink(missing_ok=True)
            runtime.memory_usage.clear()
            await self._run_events(runtime, sample, gib, return_value=on_tmpfs)
            self.assertEqual(int((scope / "memory.reclaim").read_text()), 800 * 1024**2, on_tmpfs)

    async def test_pytest_housekeeping_only_runs_when_temp_is_tmpfs(self):
        tmp_dir = attachment_tmp_dir("worker")
        old = time.time() - 31 * 60
        run_old = tmp_dir / "pytest-of-u" / "pytest-3"
        run_old.mkdir(parents=True, exist_ok=True)
        (run_old / "f.bin").write_bytes(b"x" * 64)
        os.utime(run_old, (old, old))
        os.utime(run_old / "f.bin", (old, old))
        runtime, sample, gib = self._hot_runtime()
        await self._run_events(runtime, sample, gib, return_value=False)
        self.assertTrue(run_old.exists())  # on disk the runs cost no memory: kept
        runtime.memory_usage.clear()
        await self._run_events(runtime, sample, gib, return_value=True)
        self.assertFalse(run_old.exists())  # on tmpfs: reaped

    async def test_the_tmpfs_note_is_built_only_when_a_warning_is_sent(self):
        shmem = 2 * 1024**3
        runtime, sample, gib = self._hot_runtime(shmem=shmem)
        note = AsyncMock(return_value="NOTE")
        with patch("partyline.memory_sampler.tmpfs_note_for", note):
            # below the threshold: no warning, so no directory walk
            quiet = dict(sample, current=100 * 1024**2, working_set=100 * 1024**2)
            await self._run_events(runtime, quiet, gib, return_value=True)
            note.assert_not_awaited()
            await self._run_events(runtime, sample, gib, events=3, return_value=True)
        self.assertEqual(note.await_count, 1)  # once for the one warning sent, not per event
        self.assertEqual(note.await_args.args[1], shmem)


    async def test_warning_is_private_to_the_line_captain_and_people_can_read_it(self):
        worker = {"id": "worker", "name": "worker", "conv_id": "line"}
        self.db.add_attachment("captain", "line", "captain", "fake", ["fake"], self.temp.name)
        self.db._exec("UPDATE attachments SET is_lead=1,status='running' WHERE id='captain'")
        runtime = ChatRuntime(self.db)
        runtime.live["captain"] = SimpleNamespace(att=self.db.get_attachment("captain"))
        with patch("partyline.memory_sampler.post_private", new_callable=AsyncMock,
                   return_value={"id": 1}) as private:
            await _warn(runtime, worker, 3 * 1024**3, 4 * 1024**3)
        audiences = [call.kwargs["audience"] for call in private.await_args_list]
        self.assertEqual(audiences, ["worker", "captain"])
        self.assertIn("you are using", private.await_args_list[0].args[4])
        self.assertIn("worker is using", private.await_args_list[1].args[4])
        self.assertIn("As its captain, decide now", private.await_args_list[1].args[4])

    async def test_root_captain_warning_rings_the_captain_itself(self):
        self.db._exec("UPDATE attachments SET is_lead=1,status='running' WHERE id='worker'")
        self.db._exec("UPDATE attachments SET is_lead=0 WHERE id='captain'")
        runtime = ChatRuntime(self.db)
        runtime.live["worker"] = SimpleNamespace(att=self.db.get_attachment("worker"))
        row = {"id": "worker", "name": "captain", "conv_id": "line"}
        with patch("partyline.memory_sampler.post_private", new_callable=AsyncMock,
                   return_value={"id": 1}) as private:
            await _warn(runtime, row, 3 * 1024**3, 4 * 1024**3)
        self.assertEqual([call.kwargs["audience"] for call in private.await_args_list], ["worker"])
        self.assertEqual(private.await_args.args[1], "line")

    async def test_captain_warning_rings_itself_and_the_parent_captain(self):
        self.db.create_conversation("parent", "Parent", captain_mode="manager_tree")
        self.db._exec("UPDATE conversations SET parent_id='parent' WHERE id='line'")
        self.db.add_attachment("parent-captain", "parent", "boss", "fake", ["fake"], self.temp.name)
        self.db._exec("UPDATE attachments SET status='running',is_lead=1 WHERE id='parent-captain'")
        self.db._exec("UPDATE attachments SET is_lead=1 WHERE id='worker'")
        self.db._exec("UPDATE attachments SET is_lead=0 WHERE id='captain'")
        runtime = ChatRuntime(self.db)
        runtime.live["worker"] = SimpleNamespace(att=self.db.get_attachment("worker"))
        runtime.live["parent-captain"] = SimpleNamespace(att=self.db.get_attachment("parent-captain"))
        row = {"id": "worker", "name": "captain", "conv_id": "line"}
        with patch("partyline.memory_sampler.post_private", new_callable=AsyncMock,
                   return_value={"id": 1}) as private:
            await _warn(runtime, row, 3 * 1024**3, 4 * 1024**3)
        calls = [(call.args[1], call.kwargs["audience"]) for call in private.await_args_list]
        self.assertEqual(calls, [("line", "worker"), ("parent", "parent-captain")])
