"""Foreground launches retain the quick start while establishing a real cap."""

import os
import subprocess
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from partyline import launch, server_memory, service_guard


class LaunchTest(unittest.TestCase):
    def setUp(self):
        self.serve = Mock(return_value=0)
        for patcher in (
            patch.dict(sys.modules, {"partyline.server": SimpleNamespace(main=self.serve)}),
            patch.object(launch.sys, "platform", "linux"),
            patch("partyline.bind.load_dotenv"),
            patch.object(server_memory, "host_memory_bytes", return_value=8 * 1024**3),
            patch.dict(os.environ, {"PARTYLINE_SERVER_MEMORY_LIMIT": "", "PARTYLINE_SYSTEMD_UNIT": ""}),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_terminal_launch_executes_a_scope_before_importing_server(self):
        with patch.object(service_guard, "unit_from_cgroup", return_value=None), \
                patch.object(launch.shutil, "which", return_value="/usr/bin/systemd-run"), \
                patch.object(launch.os, "execv", side_effect=SystemExit(0)) as execute:
            with self.assertRaises(SystemExit):
                launch.main(["--instance-name", "literal ${path}", "--port", "8649"])
        argv = execute.call_args.args[1]
        self.assertIn("--scope", argv)
        self.assertIn("--expand-environment=no", argv)
        self.assertIn("MemoryMax=2147483648", argv)
        self.assertIn("OOMPolicy=continue", argv)
        self.assertEqual(argv[-5:], ["--within-memory-scope", "--instance-name", "literal ${path}",
                                    "--port", "8649"])
        self.serve.assert_not_called()

    def test_child_verifies_cap_before_starting_server(self):
        with patch.object(server_memory, "verify", return_value=(True, "")):
            self.assertEqual(launch.main(["--within-memory-scope", "--port", "8649"]), 0)
        self.serve.assert_called_once_with(["--port", "8649"])

    def test_internal_flag_does_not_bypass_verification(self):
        with patch.object(server_memory, "verify", return_value=(False, "memory.max=max")):
            with self.assertRaisesRegex(SystemExit, "memory.max=max"):
                launch.main(["--within-memory-scope"])
        self.serve.assert_not_called()

    def test_existing_service_and_help_do_not_spawn_scopes(self):
        with patch.object(service_guard, "unit_from_cgroup", return_value="partyline.service"), \
                patch.object(launch.os, "execv") as execute:
            launch.main([])
            launch.main(["--help"])
        execute.assert_not_called()
        self.assertEqual(self.serve.call_count, 2)

    def test_macos_does_not_require_systemd(self):
        with patch.object(launch.sys, "platform", "darwin"), \
                patch.object(launch.os, "execv") as execute:
            launch.main([])
        execute.assert_not_called()
        self.serve.assert_called_once_with([])

    def test_missing_systemd_refuses_before_starting_server(self):
        with patch.object(service_guard, "unit_from_cgroup", return_value=None), \
                patch.object(launch.shutil, "which", return_value=None):
            with self.assertRaisesRegex(SystemExit, "systemd user manager"):
                launch.main([])
        self.serve.assert_not_called()


class ServerMemoryTest(unittest.TestCase):
    def test_default_and_configured_limits_leave_host_headroom(self):
        with patch.object(server_memory, "host_memory_bytes", return_value=1024**3), \
                patch.dict(os.environ, {"PARTYLINE_SERVER_MEMORY_LIMIT": ""}):
            self.assertEqual(server_memory.limit_bytes(), 1024**3 * 5 // 8)
            for bad in ("4G", "0G", "-1G", "oops"):
                with patch.dict(os.environ, {"PARTYLINE_SERVER_MEMORY_LIMIT": bad}):
                    with self.assertRaises(ValueError):
                        server_memory.limit_bytes()
            with patch.dict(os.environ, {"PARTYLINE_SERVER_MEMORY_LIMIT": "512M"}):
                self.assertEqual(server_memory.limit_bytes(), 512 * 1024**2)

    def test_kernel_cap_and_oom_group_must_both_be_safe(self):
        with patch.object(server_memory, "limit_bytes", return_value=1024), \
                patch.object(server_memory.subprocess, "run", return_value=
                             subprocess.CompletedProcess([], 0, "continue\n", "")):
            for maximum, group, ok in (("1024", "0", True), ("max", "0", False),
                                        ("2048", "0", False), ("0", "0", False),
                                        ("1024", "1", False)):
                with self.subTest(maximum=maximum, group=group), patch.object(
                    server_memory.Path, "read_text", side_effect=["0::/example.scope", maximum, group],
                ):
                    self.assertEqual(server_memory.verify()[0], ok)

    def test_stop_policy_is_rejected_even_with_oom_group_disabled(self):
        with patch.object(server_memory, "limit_bytes", return_value=1024), \
                patch.object(server_memory.Path, "read_text",
                             side_effect=["0::/example.scope", "1024", "0"]), \
                patch.object(server_memory.subprocess, "run", return_value=
                             subprocess.CompletedProcess([], 0, "stop\n", "")):
            self.assertEqual(server_memory.verify(),
                             (False, "server scope OOMPolicy=continue is not effective"))

    def test_missing_controller_is_a_failure(self):
        with patch.object(server_memory.Path, "read_text", side_effect=OSError("missing")):
            self.assertFalse(server_memory.verify()[0])

    def test_boot_accepts_verified_foreground_scope_without_a_service(self):
        with patch.object(server_memory, "verify", return_value=(True, "")), \
                patch.object(service_guard.subprocess, "run") as run:
            self.assertEqual(service_guard.probe(discover=False), (True, "", ""))
        run.assert_not_called()

    @unittest.skipUnless(sys.platform.startswith("linux"), "Linux cgroup check")
    def test_real_scope_passes_the_same_verification_as_boot(self):
        from partyline import process_memory

        command = [sys.executable, "-c",
                   "from partyline.server_memory import verify; "
                   "ok, reason = verify(); print(reason); raise SystemExit(0 if ok else 1)"]
        with patch.dict(os.environ, {"PARTYLINE_SERVER_MEMORY_LIMIT": "64M"}):
            argv = process_memory.scope_argv(command, "64M")
            delimiter = argv.index("--")
            argv[delimiter:delimiter] = ["-p", "OOMPolicy=continue"]
            done = subprocess.run(argv, capture_output=True,
                                  text=True, timeout=15)
        if done.returncode == 125 or "Failed to connect" in done.stderr:
            self.skipTest("systemd user scope is unavailable")
        self.assertEqual(done.returncode, 0, done.stderr + done.stdout)
