"""Per-process memory scope and capped-test enforcement regression tests."""

import os
import runpy
import shutil
import subprocess
import sys
import types
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
        self.assertEqual(argv[9:14], ["--expand-environment=no", "--", sys.executable,
                                    "-m", "partyline.process_memory"])
        self.assertEqual(argv[-3:], ["--", "/usr/bin/bwrap", "--die-with-parent"])
        self.assertIn("--die-with-parent", argv)

    def test_backstop_sits_above_the_soft_cap_within_three_quarters_of_ram(self):
        gib = 1024**3
        self.assertEqual(process_memory.backstop_limit("4G", 64 * gib), "6G")
        self.assertEqual(process_memory.backstop_limit("1G", 64 * gib), "2G")
        # The host ceiling wins over an oversized saved budget, and over rounding.
        self.assertEqual(process_memory.backstop_limit("8G", 8 * gib), "6G")
        self.assertEqual(process_memory.backstop_limit("4G", 7 * gib), "5376M")
        odd_host = 8 * gib - 4096
        self.assertLessEqual(process_memory.backstop_bytes(4 * gib, odd_host), odd_host * 3 // 4)
        with patch("partyline.server_memory.host_memory_bytes", return_value=64 * gib):
            self.assertEqual(process_memory.backstop_limit("2G"), "3G")

    def test_linux_refuses_to_launch_without_systemd_scope(self):
        with patch.object(process_memory.shutil, "which", return_value=None):
            with self.assertRaises(process_memory.MemoryScopeUnavailable):
                process_memory.scope_argv(["bwrap"], "4G")
        self.assertEqual(process_memory.exit_notice(-9, "4G", "codex"),
                         "codex exited (code -9): killed; memory-limit cause unconfirmed")
        self.assertIsNone(process_memory.exit_notice(1, "4G", "codex"))

    def test_boot_probe_reads_the_scope_limit_without_allocating(self):
        with patch.object(process_memory, "process_memory_limit", return_value="4G"), \
                patch.object(process_memory.shutil, "which", return_value="/usr/bin/systemd-run"), \
                patch.object(process_memory.subprocess, "run", return_value=subprocess.CompletedProcess(
                    ["probe"], 0, str(4 * 1024**3), "")) as run:
            self.assertEqual(process_memory.probe_scope(), (True, ""))
        run.assert_called_once()
        self.assertIn("MemoryMax=4G", run.call_args.args[0])
        self.assertIn("--expand-environment=no", run.call_args.args[0])
        self.assertIn("memory.max", run.call_args.args[0][-3])
        self.assertIn('[ "$value" -le "$1" ]', run.call_args.args[0][-3])


class AddressSpaceFallbackTest(unittest.TestCase):
    """The non-Linux preexec fallback must never kill the spawn.

    macOS can carry a hard ``RLIMIT_AS`` below the configured cap; the old
    unclamped ``setrlimit(RLIMIT_AS, (amount, amount))`` then raised
    ``ValueError: current limit exceeds maximum limit`` between fork and exec,
    which subprocess surfaces as "Exception occurred in preexec_fn".
    """

    RLIMIT_AS = 6
    RLIM_INFINITY = -1

    def fake(self, soft: int, hard: int, *, fail: bool = False):
        module = types.SimpleNamespace(
            RLIMIT_AS=self.RLIMIT_AS,
            RLIM_INFINITY=self.RLIM_INFINITY,
            calls=[],
        )

        def getrlimit(_which):
            return (soft, hard)

        def setrlimit(_which, limits):
            new_soft, new_hard = limits
            if fail or (hard != self.RLIM_INFINITY
                        and (new_soft > hard or new_hard > hard)):
                raise ValueError("current limit exceeds maximum limit")
            module.calls.append((new_soft, new_hard))

        module.getrlimit = getrlimit
        module.setrlimit = setrlimit
        return module

    def apply(self, module, limit: str = "4G") -> None:
        with patch.dict(sys.modules, {"resource": module}):
            process_memory.apply_address_space_limit(limit)

    def test_a_hard_limit_below_the_request_is_clamped_not_failed(self):
        hard = 2 * 1024**3
        module = self.fake(hard, hard)
        self.apply(module)  # must not raise
        self.assertEqual(module.calls, [(hard, hard)])

    def test_c_requested_below_the_hard_limit_is_applied_as_before(self):
        hard = 8 * 1024**3
        module = self.fake(hard, hard)
        self.apply(module)
        self.assertEqual(module.calls, [(4 * 1024**3, 4 * 1024**3)])

    def test_b_setrlimit_valueerror_cannot_kill_the_fallback(self):
        module = self.fake(8 * 1024**3, 8 * 1024**3, fail=True)
        self.apply(module)  # must not raise
        self.assertEqual(module.calls, [])

    def test_an_infinite_hard_limit_leaves_the_request_alone(self):
        module = self.fake(self.RLIM_INFINITY, self.RLIM_INFINITY)
        self.apply(module)
        self.assertEqual(module.calls, [(4 * 1024**3, 4 * 1024**3)])

    def test_a_getrlimit_failure_is_swallowed(self):
        module = self.fake(0, 0)
        module.getrlimit = lambda _which: (_ for _ in ()).throw(OSError("no rlimit"))
        self.apply(module)  # must not raise
        self.assertEqual(module.calls, [])


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
        if (b"No permissions to create a new namespace" in result.stderr
                or b"setting up uid map" in result.stderr):
            self.skipTest("kernel user namespaces are unavailable here")
        self.assertEqual(result.returncode, 0, result.stderr.decode(errors="replace"))
        self.assertTrue(process_memory.memory_max_enforced(result.stdout.decode().strip(), limit))
        # Exercise the real boot probe too: mocking subprocess.run hides systemd's
        # expansion of shell variables before /bin/sh receives the script.
        with patch.object(process_memory, "process_memory_limit", return_value=limit):
            self.assertEqual(process_memory.probe_scope(), (True, ""))
