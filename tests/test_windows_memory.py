"""Job configuration controls plus a bounded native Windows allocation probe."""

import ctypes
import os
from pathlib import Path
import runpy
import subprocess
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from partyline import windows_memory as memory


class WindowsJobTest(unittest.TestCase):
    def api(self, *, maximum=1024, flags=memory.JOB_OBJECT_LIMIT_JOB_MEMORY, member=True):
        def query(_handle, _kind, pointer, _size, _length):
            info = ctypes.cast(pointer, ctypes.POINTER(memory.ExtendedLimits)).contents
            info.BasicLimitInformation.LimitFlags = flags
            info.JobMemoryLimit = maximum
            return True

        def membership(_process, _job, pointer):
            pointer._obj.value = member
            return True

        return SimpleNamespace(
            CreateJobObjectW=Mock(return_value=123), SetInformationJobObject=Mock(return_value=True),
            QueryInformationJobObject=Mock(side_effect=query), GetCurrentProcess=Mock(return_value=456),
            AssignProcessToJobObject=Mock(return_value=True), IsProcessInJob=Mock(side_effect=membership),
            CloseHandle=Mock(return_value=True),
        )

    def test_configure_verify_assign_and_close_once(self):
        api = self.api()
        with patch.object(memory, "_api", return_value=api):
            job = memory.WindowsJob(1024)
            job.assign_current_process()
            job.close()
            job.close()
        api.AssignProcessToJobObject.assert_called_once_with(123, 456)
        api.CloseHandle.assert_called_once_with(123)
        self.assertEqual(api.QueryInformationJobObject.call_count, 2)

    def test_invalid_limits_are_rejected_before_creating_a_job(self):
        for limit in (0, -1, ctypes.c_size_t(-1).value + 1):
            with self.assertRaises(ValueError):
                memory.WindowsJob(limit)

    def test_unenforced_cap_closes_job_and_refuses(self):
        for maximum, flags in ((0, 512), (2048, 512), (1024, 0)):
            api = self.api(maximum=maximum, flags=flags)
            with patch.object(memory, "_api", return_value=api):
                with self.assertRaisesRegex(OSError, "not enforced"):
                    memory.WindowsJob(1024)
            api.CloseHandle.assert_called_once_with(123)

    def test_assignment_must_be_confirmed(self):
        api = self.api(member=False)
        with patch.object(memory, "_api", return_value=api):
            job = memory.WindowsJob(1024)
            try:
                with self.assertRaisesRegex(OSError, "did not enter"):
                    job.assign_current_process()
            finally:
                job.close()

    def test_api_errors_are_not_treated_as_success(self):
        with patch.object(ctypes, "get_last_error", return_value=5, create=True), \
                patch.object(ctypes, "FormatError", return_value="Access denied", create=True):
            with self.assertRaisesRegex(OSError, "AssignProcessToJobObject failed"):
                memory._check(0, "AssignProcessToJobObject")

    def test_native_api_is_not_loaded_on_other_platforms(self):
        with patch.object(memory.sys, "platform", "linux"):
            with self.assertRaisesRegex(OSError, "native Windows"):
                memory.WindowsJob(1024)

    def test_capped_runner_refuses_if_job_assignment_fails(self):
        runner = runpy.run_path(str(Path(__file__).parents[1] / "scripts" / "capped-test"))
        fake = Mock()
        fake.assign_current_process.side_effect = OSError("assignment denied")
        with patch.object(sys, "platform", "win32"), \
                patch.object(memory, "WindowsJob", return_value=fake), \
                patch.object(subprocess, "run") as run:
            self.assertEqual(runner["run_capped"](["must-not-run"], 1024, {}), 125)
        run.assert_not_called()
        fake.close.assert_called_once()

    @unittest.skipUnless(sys.platform == "win32", "requires native Windows")
    def test_native_cap_survives_handle_close_and_covers_descendants(self):
        allocation = "try:\n data=bytearray(192*1024**2)\nexcept MemoryError:\n print('blocked')"
        code = (
            "import subprocess,sys; from partyline.windows_memory import WindowsJob; "
            "job=WindowsJob(128*1024**2); job.assign_current_process(); job.close();\n"
            + allocation + "\n"
            + f"result=subprocess.run([sys.executable,'-c',{allocation!r}],capture_output=True,text=True); "
            "print(result.stdout.strip()); sys.exit(result.returncode)"
        )
        result = subprocess.run([sys.executable, "-c", code], capture_output=True,
                                text=True, timeout=20, env=os.environ.copy())
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.splitlines(), ["blocked", "blocked"])

    @unittest.skipUnless(sys.platform == "win32", "requires native Windows")
    def test_native_job_counts_combined_parent_and_child_allocations(self):
        allocate = ("try:\n data=bytearray(80*1024**2); print('allocated')\n"
                    "except MemoryError:\n print('blocked')")
        code = (
            "import subprocess,sys; from partyline.windows_memory import WindowsJob; "
            "job=WindowsJob(128*1024**2); job.assign_current_process(); "
            "held=bytearray(64*1024**2); "
            + f"result=subprocess.run([sys.executable,'-c',{allocate!r}],capture_output=True,text=True); "
            "print(result.stdout.strip()); sys.exit(result.returncode)"
        )
        control = subprocess.run([sys.executable, "-c", allocate], capture_output=True,
                                 text=True, timeout=20)
        self.assertEqual(control.returncode, 0, control.stderr)
        self.assertEqual(control.stdout.strip(), "allocated")
        result = subprocess.run([sys.executable, "-c", code], capture_output=True,
                                text=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "blocked")
