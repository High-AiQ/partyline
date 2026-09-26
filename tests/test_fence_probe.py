"""The boot probe and doctor never need a real host sandbox in unit tests."""

import io
import subprocess
import unittest
from unittest.mock import mock_open, patch

from partyline import fence, fence_probe
from partyline.doctor import check_adapters, run


class RemedyTest(unittest.TestCase):
    def test_distro_install_lines_and_ubuntu_profile_note(self):
        cases = (
            ("ID=debian\n", "apt-get install -y bubblewrap"),
            ("ID=fedora\n", "dnf install bubblewrap"),
            ("ID=arch\n", "pacman -S bubblewrap"),
            ("ID=opensuse-tumbleweed\n", "zypper install bubblewrap"),
        )
        for release, expected in cases:
            with self.subTest(release=release), patch(
                "builtins.open", mock_open(read_data=release)
            ):
                self.assertEqual(fence_probe.remedy("linux"), expected)
        with patch("builtins.open", mock_open(read_data='ID=ubuntu\nVERSION_ID="24.04"\n')):
            self.assertEqual(fence_probe.remedy("linux"), "apt-get install -y bubblewrap")
            self.assertIn("AppArmor", fence_probe._probe_note())
            self.assertIn("pip-bundled", fence_probe._probe_note())
        self.assertIn("ships with macOS", fence_probe.remedy("darwin"))
        self.assertIn("https://", fence_probe.remedy("freebsd"))

    def test_unknown_and_unreadable_distribution_falls_back_to_package_docs(self):
        with patch("builtins.open", mock_open(read_data="NO_SEPARATOR\nID=other\n")):
            self.assertIn("bubblewrap package", fence_probe.remedy("linux"))
            self.assertEqual(fence_probe.values_release(), "")
            self.assertEqual(fence_probe._probe_note(), "")
        with patch("builtins.open", side_effect=OSError("no os-release")):
            self.assertIn("bubblewrap package", fence_probe.remedy("linux"))
            self.assertEqual(fence_probe._distribution(), ("", ""))

    def test_ubuntu_without_a_numeric_version_does_not_assume_apparmor(self):
        data = 'ID=ubuntu\nVERSION_ID="development"\n'
        with patch("builtins.open", mock_open(read_data=data)):
            self.assertEqual(fence_probe._probe_note(), "")


class ProbeTest(unittest.TestCase):
    def setUp(self):
        self.scope_probe = patch(
            "partyline.process_memory.probe_scope", return_value=(True, "")
        )
        self.guard_probe = patch("partyline.service_guard.probe", return_value=(True, "", ""))
        self.scope_probe.start()
        self.guard_probe.start()
        self.addCleanup(self.guard_probe.stop)
        self.addCleanup(self.scope_probe.stop)

    @patch("partyline.fence.backend_available", return_value=(True, ""))
    @patch("partyline.fence.backend", return_value="bubblewrap")
    @patch("partyline.fence_probe.subprocess.run")
    def test_linux_probe_uses_the_production_argv_builder(self, run, _backend, _available):
        run.return_value = subprocess.CompletedProcess([], 0, "", "")
        self.assertEqual(fence_probe.probe(), (True, "", ""))
        argv = run.call_args.args[0]
        self.assertEqual(argv[0], fence.BWRAP)
        self.assertIn("--unshare-user", argv)
        self.assertEqual(argv[-1], "/usr/bin/true")
        cwd = run.call_args.kwargs["cwd"]
        binds = [(argv[i + 1], argv[i + 2]) for i, flag in enumerate(argv)
                 if flag in ("--bind", "--ro-bind")]
        self.assertIn((cwd, cwd), binds)

    @patch("partyline.fence.backend_available", return_value=(False, "backend missing"))
    def test_missing_backend_returns_install_remedy_without_running(self, _available):
        with patch("partyline.fence_probe.subprocess.run") as run:
            ok, reason, install = fence_probe.probe()
        self.assertFalse(ok)
        self.assertTrue(reason.startswith("backend missing"))
        self.assertTrue(install)
        run.assert_not_called()

    @patch("partyline.fence.backend_available", return_value=(True, ""))
    @patch("partyline.fence.backend", return_value="sandbox-exec")
    @patch("partyline.fence_probe.subprocess.run")
    def test_darwin_probe_uses_the_system_profile(self, run, _backend, _available):
        run.return_value = subprocess.CompletedProcess([], 0, "", "")
        self.assertEqual(fence_probe.probe(), (True, "", ""))
        self.assertEqual(run.call_args.args[0][2], "(version 1)(allow default)")

    @patch("partyline.fence.backend_available", return_value=(True, ""))
    @patch("partyline.fence.backend", return_value="restricted-token")
    @patch("partyline.fence_probe.subprocess.run")
    def test_windows_probe_runs_real_console_and_permissions_check(self, run, _backend, _available):
        run.return_value = subprocess.CompletedProcess([], 0, "", "")
        self.assertEqual(fence_probe.probe(), (True, "", ""))
        self.assertEqual(run.call_args.args[0][-2:], ['-m', 'partyline.windows_probe'])
        self.assertEqual(run.call_args.kwargs['timeout'], 120)
        self.assertIn('filesystem ACLs', fence_probe.remedy('win32'))

    @patch("partyline.fence.backend_available", return_value=(True, ""))
    @patch("partyline.fence.backend", return_value="none")
    @patch("partyline.fence_probe.subprocess.run")
    def test_unknown_backend_fails_without_running_a_command(self, run, _backend, _available):
        result = fence_probe.probe()
        self.assertFalse(result[0])
        self.assertIn("no write-fence backend", result[1])
        run.assert_not_called()

    @patch("partyline.fence_probe.subprocess.run", side_effect=OSError("namespace denied"))
    @patch("partyline.fence.backend_available", return_value=(True, ""))
    @patch("partyline.fence.backend", return_value="bubblewrap")
    def test_execution_failure_becomes_remediable_probe_failure(
        self, _backend, _available, _run
    ):
        ok, reason, install = fence_probe.probe()
        self.assertFalse(ok)
        self.assertIn("namespace denied", reason)
        self.assertTrue(install)

    @patch("partyline.fence.backend_available", return_value=(True, ""))
    @patch("partyline.fence.backend", return_value="bubblewrap")
    @patch("partyline.fence_probe.subprocess.run")
    def test_nonzero_probe_without_output_gets_a_clear_failure(self, run, _backend, _available):
        run.return_value = subprocess.CompletedProcess([], 1, "", "")
        ok, reason, install = fence_probe.probe()
        self.assertFalse(ok)
        self.assertIn("command failed", reason)
        self.assertTrue(install)

    @patch("partyline.process_memory.probe_scope", return_value=(True, ""))
    @patch("partyline.service_guard.probe", return_value=(
        False, "unsafe partyline unit", "drop-in: [Service]\\nOOMPolicy=continue"
    ))
    @patch("partyline.fence.backend_available", return_value=(True, ""))
    @patch("partyline.fence.backend", return_value="bubblewrap")
    @patch("partyline.fence_probe.subprocess.run")
    def test_boot_probe_reports_service_guard_remedy(self, run, _backend, _available,
                                                     _service_guard, _scope_probe):
        run.return_value = subprocess.CompletedProcess([], 0, "", "")
        ok, reason, remedy = fence_probe.probe()
        self.assertFalse(ok)
        self.assertIn("unsafe partyline unit", reason)
        self.assertIn("OOMPolicy=continue", remedy)


class DoctorTest(unittest.TestCase):
    def test_requires_are_checked_once_and_doctor_fails_closed(self):
        metadata = {"one": {"requires": ["good", "missing"]}, "two": {"requires": []}}
        def locate(item):
            return "/bin/good" if item == "good" else None

        with patch("partyline.doctor.shutil.which", side_effect=locate):
            checks = check_adapters(metadata)
        self.assertEqual(checks, [("one", "good", True), ("one", "missing", False)])
        output = io.StringIO()
        with patch("partyline.doctor.fence_probe.status", return_value={
            "platform": "linux", "backend": "bubblewrap"
        }), patch("partyline.doctor.shutil.which", return_value=None), patch("sys.stdout", output):
            code = run(metadata, probe=lambda: (True, "", ""))
        self.assertEqual(code, 1)
        self.assertIn("missing", output.getvalue())

        with patch("partyline.doctor.fence_probe.status", return_value={
            "platform": "linux", "backend": "bubblewrap"
        }), patch("partyline.doctor.shutil.which", return_value="/bin/present"):
            self.assertEqual(run(metadata, probe=lambda: (True, "", "")), 0)

    def test_unit_guard_failure_is_printed_as_the_doctor_remedy(self):
        output = io.StringIO()
        remedy = "[Service]\nOOMPolicy=continue\nMemoryMax=48G"
        with patch("partyline.doctor.fence_probe.status", return_value={
            "platform": "linux", "backend": "bubblewrap"
        }), patch("partyline.doctor.shutil.which", return_value="/bin/present"), \
                patch("sys.stdout", output):
            code = run({}, probe=lambda: (False, "unit guard missing", remedy))
        self.assertEqual(code, 1)
        self.assertIn("unit guard missing", output.getvalue())
        self.assertIn("OOMPolicy=continue", output.getvalue())


if __name__ == "__main__":
    unittest.main()
