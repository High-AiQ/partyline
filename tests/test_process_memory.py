"""Per-process memory scope and capped-test enforcement regression tests."""

import os
import runpy
import shutil
import subprocess
import sys
import unittest
from contextlib import redirect_stderr
from io import StringIO
from unittest.mock import patch

from partyline import process_memory


class ProcessMemoryTest(unittest.TestCase):
    def test_default_limit_and_environment_override(self):
        self.assertEqual(process_memory.process_memory_limit({}), "4G")
        self.assertEqual(
            process_memory.process_memory_limit({"PARTYLINE_PROCESS_MEMORY_LIMIT": "3G"}),
            "3G",
        )

    def test_linux_command_runs_inside_a_transient_scope(self):
        with patch.object(process_memory.shutil, "which", return_value="/usr/bin/systemd-run"):
            argv = process_memory.scope_argv(["/usr/bin/bwrap", "--die-with-parent"], "4G")
        self.assertEqual(argv[:9], [
            "/usr/bin/systemd-run", "--user", "--scope", "-q", "--collect",
            "-p", "MemoryMax=4G", "-p", "MemorySwapMax=0",
        ])
        self.assertEqual(argv[9:13], ["--", sys.executable, "-m", "partyline.process_memory"])
        self.assertEqual(argv[-3:], ["--", "/usr/bin/bwrap", "--die-with-parent"])
        self.assertIn("--die-with-parent", argv)

    def test_linux_refuses_to_launch_without_systemd_scope(self):
        with patch.object(process_memory.shutil, "which", return_value=None):
            with self.assertRaises(process_memory.MemoryScopeUnavailable):
                process_memory.scope_argv(["bwrap"], "4G")
        self.assertEqual(process_memory.exit_notice(-9, "4G", "codex"),
                         "codex killed: memory limit 4G")
        self.assertIsNone(process_memory.exit_notice(1, "4G", "codex"))

    def test_boot_probe_reads_the_scope_limit_without_allocating(self):
        with patch.object(process_memory, "process_memory_limit", return_value="4G"), \
                patch.object(process_memory.shutil, "which", return_value="/usr/bin/systemd-run"), \
                patch.object(process_memory.subprocess, "run", return_value=subprocess.CompletedProcess(
                    ["probe"], 0, str(4 * 1024**3), "")) as run:
            self.assertEqual(process_memory.probe_scope(), (True, ""))
        run.assert_called_once()
        self.assertIn("MemoryMax=4G", run.call_args.args[0])
        self.assertIn("memory.max", run.call_args.args[0][-3])
        self.assertIn('[ "$value" -le "$1" ]', run.call_args.args[0][-3])


class CappedTestLimitTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.script = runpy.run_path(os.path.join(os.path.dirname(__file__), "..", "scripts", "capped-test"))

    def test_systemd_scope_is_rejected_when_memory_max_is_unlimited(self):
        self.assertFalse(self.script["memory_max_enforced"]("max", 1024))

    def test_systemd_scope_accepts_a_finite_limit_at_or_below_requested(self):
        self.assertTrue(self.script["memory_max_enforced"]("1024", 1024))
        self.assertFalse(self.script["memory_max_enforced"]("2048", 1024))

    def test_refuses_to_run_when_neither_memory_guard_can_be_verified(self):
        with patch.dict(self.script, {
            "systemd_available": lambda _limit, _env=None: False,
            "rlimit_available": lambda _limit: False,
        }):
            error = StringIO()
            with redirect_stderr(error):
                result = self.script["run_capped"](["this-must-not-run"], 1024, os.environ.copy())
        self.assertEqual(result, 125)
        self.assertIn("refusing to run", error.getvalue())

    def test_refuses_when_a_new_test_scope_does_not_show_the_limit(self):
        error = StringIO()
        namespace = self.script["verify_scope_and_exec"].__globals__
        with patch.dict(namespace, {"_read_memory_max": lambda: "max"}):
            with redirect_stderr(error):
                result = self.script["verify_scope_and_exec"](1024, ["this-must-not-run"])
        self.assertEqual(result, 125)
        self.assertIn("memory.max=max", error.getvalue())

    def test_rlimit_fallback_is_inherited_by_child_without_allocating(self):
        code = ("import resource; "
                "print(resource.getrlimit(resource.RLIMIT_AS)[0])")
        command = [sys.executable, "-c", code]
        result = subprocess.run(
            [sys.executable, os.path.join(os.path.dirname(__file__), "..", "scripts", "capped-test"),
             "--memory", "64M", "--", *command],
            capture_output=True, env={**os.environ, "XDG_RUNTIME_DIR": ""},
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(b"RLIMIT_AS=64M", result.stderr)
        self.assertLessEqual(int(result.stdout.strip()), 64 * 1024 * 1024)

    @unittest.skipUnless(shutil.which("bwrap") and shutil.which("systemd-run"),
                         "requires bubblewrap and a systemd user manager")
    def test_fenced_probe_reads_an_enforced_memory_max(self):
        limit = "64M"
        probe = [
            shutil.which("bwrap"), "--bind", "/", "/", "--dev-bind", "/dev", "/dev",
            "--proc", "/proc", "--unshare-user", "--die-with-parent", "--",
            sys.executable, "-c",
            "from partyline.process_memory import read_memory_max,memory_max_enforced; "
            "import sys; v=read_memory_max(); print(v); "
            "sys.exit(0 if memory_max_enforced(v, '64M') else 1)",
        ]
        with patch.dict(os.environ, {"XDG_RUNTIME_DIR": os.environ.get("XDG_RUNTIME_DIR", "/run/user/0")}):
            try:
                argv = process_memory.scope_argv(probe, limit)
                result = subprocess.run(argv, capture_output=True, timeout=10)
            except (OSError, subprocess.TimeoutExpired) as exc:
                self.skipTest(f"systemd user scope is unavailable: {exc}")
        if result.returncode == 125:
            self.skipTest("systemd user manager did not apply MemoryMax from this environment")
        if b"No permissions to create a new namespace" in result.stderr:
            self.skipTest("kernel user namespaces are disabled")
        self.assertEqual(result.returncode, 0, result.stderr.decode(errors="replace"))
        self.assertTrue(process_memory.memory_max_enforced(result.stdout.decode().strip(), limit))
