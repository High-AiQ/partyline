"""Release validation and opt-in persistence use fake assets and platform trust APIs."""
import ctypes
import hashlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch
from urllib.error import HTTPError
from urllib.request import Request

from partyline_helper import update_download as downloads, update_preferences as preferences
from partyline_helper import update_signature, update_supervisor as supervisor
from partyline_helper.update_release import installer_info
from partyline_helper.native_host import hello


class ReleaseTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.info = {**installer_info("1.7.0"), "available": True}
        self.data = b"installer bytes"
        self.checksum = hashlib.sha256(self.data).hexdigest() + "  " + self.info["filename"]
        self.calls = []

    def fetch(self, url, path, limit):
        self.calls.append((url, limit))
        path.write_bytes(self.checksum.encode() if url.endswith(".sha256") else self.data)
        return True

    def prepare(self, **kwargs):
        return downloads.prepare(self.info, "1.6.0", self.root, fetch=self.fetch, **kwargs)

    def test_exact_url_checksum_and_optional_signature(self):
        verifier = Mock(return_value=True)
        path = self.prepare(signed=True, verify=verifier)
        self.assertEqual(path.read_bytes(), self.data)
        self.assertEqual([row[0] for row in self.calls], [self.info["url"] + ".sha256", self.info["url"]])
        verifier.assert_called_once_with(path)
        self.assertFalse(path.with_suffix(".exe.sha256").exists())
        verifier.reset_mock()
        self.prepare(signed=False, verify=verifier)
        verifier.assert_not_called()

    def test_wrong_checksum_malformed_checksum_and_invalid_signature_fail_closed(self):
        self.checksum = "0" * 64 + "  " + self.info["filename"]
        with self.assertRaisesRegex(ValueError, "checksum mismatch"):
            self.prepare()
        self.assertEqual(list(self.root.iterdir()), [])
        for checksum in ("bad", "0" * 64 + "  different.exe"):
            self.checksum = checksum
            with self.assertRaisesRegex(ValueError, "checksum file"):
                self.prepare()
        self.checksum = hashlib.sha256(self.data).hexdigest() + "  " + self.info["filename"]
        with self.assertRaisesRegex(ValueError, "Authenticode"):
            self.prepare(signed=True, verify=lambda _: False)
        self.assertEqual(list(self.root.iterdir()), [])

    def test_signed_release_requires_authenticode_even_from_an_unsigned_helper(self):
        self.checksum += "\n# authenticode=required"
        verifier = Mock(return_value=False)
        with self.assertRaisesRegex(ValueError, "Authenticode"):
            self.prepare(signed=False, verify=verifier)
        verifier.assert_called_once()
        self.checksum += "\n# extra"
        with self.assertRaisesRegex(ValueError, "checksum file"):
            self.prepare()

    def test_missing_asset_does_not_retry(self):
        for missing in (".sha256", ".exe"):
            calls = []
            def fetch(url, path, limit, calls=calls, missing=missing):
                calls.append(url)
                return False if url.endswith(missing) else self.fetch(url, path, limit)
            self.assertIsNone(downloads.prepare(self.info, "1.6.0", self.root, fetch=fetch))
            self.assertEqual(len(calls), 1 if missing == ".sha256" else 2)

    def test_no_downgrade_no_unknown_version_or_arbitrary_url(self):
        fetch = Mock()
        for version in ("1.7.0", "1.8.0", "unknown"):
            self.assertIsNone(downloads.prepare(self.info, version, self.root, fetch=fetch))
        for version in ("unknown", " 1.8.0", None):
            self.assertIsNone(downloads.prepare({**self.info, "version": version}, "1.6.0", self.root,
                                                fetch=fetch))
        self.assertIsNone(downloads.prepare({**self.info, "available": False}, "1.6.0", self.root,
                                            fetch=fetch))
        with self.assertRaisesRegex(ValueError, "release URL"):
            downloads.prepare({**self.info, "url": "https://example.test/setup.exe"}, "1.6.0",
                              self.root, fetch=fetch)
        fetch.assert_not_called()

    def test_https_context_redirect_and_limits(self):
        opener = Mock()
        opener.open.return_value = io.BytesIO(b"data")
        with patch.object(downloads, "build_opener", return_value=opener) as build:
            self.assertTrue(downloads.download(self.info["url"], self.root / "setup.exe", 4))
            context = build.call_args.args[0]._context
            self.assertTrue(context.check_hostname)
            self.assertEqual(context.verify_mode, __import__("ssl").CERT_REQUIRED)
            opener.open.return_value = io.BytesIO(b"oversize")
            with self.assertRaisesRegex(ValueError, "limit"):
                downloads.download(self.info["url"], self.root / "setup.exe", 2)
            for status in (404, 403):
                opener.open.side_effect = HTTPError(self.info["url"], status, "missing", {}, None)
                if status == 404:
                    self.assertFalse(downloads.download(self.info["url"], self.root / "setup.exe", 4))
                else:
                    with self.assertRaises(HTTPError):
                        downloads.download(self.info["url"], self.root / "setup.exe", 4)
        with self.assertRaises(ValueError):
            downloads.download("http://example.test/asset", self.root / "setup.exe", 4)
        redirects = downloads.SecureRedirect()
        with self.assertRaises(ValueError):
            redirects.redirect_request(Request(self.info["url"]), None, 302, "", {}, "http://example.test/a")
        self.assertEqual(redirects.redirect_request(Request(self.info["url"]), None, 302, "", {},
                                                   "https://example.test/a").full_url, "https://example.test/a")

    def test_winverifytrust_seam_always_closes_provider_state(self):
        call = Mock(return_value=0)
        library = SimpleNamespace(WinVerifyTrust=call)
        self.assertTrue(update_signature.verify(self.root / "setup.exe", library))
        self.assertEqual(call.call_count, 2)
        data = ctypes.cast(call.call_args.args[2], ctypes.POINTER(update_signature.TrustData)).contents
        self.assertEqual(data.action, 2)
        call.reset_mock()
        call.return_value = -1
        self.assertFalse(update_signature.verify(self.root / "setup.exe", library))
        self.assertEqual(call.call_count, 2)

    def test_setting_defaults_off_keeps_credentials_and_is_audited(self):
        path = self.root / "helper.json"
        with patch.object(preferences, "config_path", return_value=path), \
                patch.object(preferences, "ScreenAccessAudit") as audit:
            self.assertFalse(preferences.enabled())
            path.write_text('{"token":"private","server":"https://example.test"}')
            self.assertTrue(preferences.set_enabled(True))
            self.assertTrue(preferences.enabled())
            self.assertEqual(preferences.read()["token"], "private")
            self.assertTrue(preferences.set_enabled(True))
            audit.return_value.append.assert_called_once()
            preferences.failed_version("1.7.0")
            self.assertEqual(preferences.read()["failed_update"], "1.7.0")
            path.write_text("bad")
            self.assertFalse(preferences.set_enabled(False))

    def test_native_hello_reads_installed_manifest_and_opt_in(self):
        path = self.root / "helper.json"
        extension = self.root / "chrome-extension"
        extension.mkdir()
        (extension / "manifest.json").write_text('{"version":"1.7.0"}')
        with patch("partyline_helper.native_host.config_path", return_value=path), \
                patch("partyline_helper.native_host.enabled", return_value=True):
            self.assertEqual(hello(), {"method": "Partyline.hello", "extension_version": "1.7.0",
                                      "auto_update": True})
            (extension / "manifest.json").unlink()
            self.assertIsNone(hello()["extension_version"])


class SupervisorTests(unittest.TestCase):
    def test_success_and_each_failure_restore_the_previous_version(self):
        with tempfile.TemporaryDirectory() as directory:
            plan = Path(directory) / "install-plan.json"
            data = {"installer": "setup.exe", "previous": ["old-helper.exe"], "pid": 42,
                    "version": "1.7.0", "event": "event"}
            plan.write_text(json.dumps(data))
            for parent_gone, code, connected in ((True, 0, True), (True, 1, False),
                                                 (True, 0, False), (False, 0, False)):
                run = Mock(return_value=SimpleNamespace(returncode=code))
                event = Mock()
                event.wait.return_value = connected
                wait = Mock(return_value=parent_gone)
                installer = Mock()
                installer.wait.return_value = code
                success = supervisor.run(plan, run, wait, lambda _, event=event: event,
                                         lambda _, installer=installer: installer, ready=Mock())
                self.assertEqual(success, parent_gone and code == 0 and connected)
                event.close.assert_called_once()
                wait.assert_called_once_with(42, timeout=30)
                if success:
                    run.assert_not_called()
                    installer.wait.assert_called_once_with(timeout=120)
                    installer.abort.assert_not_called()
                else:
                    self.assertEqual([call.args[0][-1] for call in run.call_args_list[-3:]],
                                     ["stop", "install", "start"])
                    self.assertTrue(json.loads((plan.parent / "result.json").read_text())["failed"])

    def test_supervisor_launch_is_detached_without_shell_and_event_is_signalled(self):
        with tempfile.TemporaryDirectory() as directory, \
                patch.object(supervisor, "config_path", return_value=Path(directory) / "helper.json"):
            popen = Mock()
            ready = Mock()
            ready.wait.return_value = True
            name = supervisor.launch(Path(directory) / "setup.exe", "1.7.0", popen, ["helper.exe"],
                                     readiness=lambda _: ready)
            argv = popen.call_args.args[0]
            self.assertEqual(argv[:2], ["helper.exe", "update-install"])
            self.assertEqual(json.loads(Path(argv[2]).read_text())["event"], name)
            self.assertEqual(supervisor.result(), {})
            ready.wait.assert_called_once_with(10)
            ready.wait.return_value = False
            with self.assertRaisesRegex(OSError, "supervisor"):
                supervisor.launch(Path(directory) / "setup.exe", "1.7.0", popen, ["helper.exe"],
                                  readiness=lambda _: ready)
            popen.return_value.terminate.assert_called_once()
            kernel = SimpleNamespace(**{key: Mock(return_value=1) for key in
                ("CreateEventW", "OpenEventW", "WaitForSingleObject", "SetEvent", "CloseHandle")})
            supervisor.signal(name, kernel)
            kernel.SetEvent.assert_called_once_with(1)
            kernel.CloseHandle.assert_called_once_with(1)
            kernel.CreateEventW.return_value = 0
            with self.assertRaises(OSError):
                supervisor.Completion(name, kernel)
            kernel.CreateEventW.return_value = 1
            kernel.SetEvent.return_value = 0
            with self.assertRaises(OSError):
                supervisor.signal(name, kernel)
    def test_shortcut_repair_failure_still_starts_the_previous_helper(self):
        with tempfile.TemporaryDirectory() as directory:
            plan = Path(directory) / "install-plan.json"
            plan.write_text(json.dumps({"installer": "setup.exe", "previous": ["old.exe"], "pid": 42,
                                        "event": "completion", "version": "1.7.0"}))
            event, installer = Mock(), Mock()
            installer.wait.return_value = 1
            def execute(argv, **kwargs):
                if argv[-1] == "install":
                    raise OSError("shortcut unavailable")
            run = Mock(side_effect=execute)
            self.assertFalse(supervisor.run(plan, execute=run, wait=lambda *a, **k: True,
                                           completion=lambda _: event, installation=lambda _: installer,
                                           ready=Mock()))
            self.assertEqual(run.call_args.args[0], ["old.exe", "start"])


class InstallerJobTests(unittest.TestCase):
    def test_installer_is_assigned_before_resume_and_timeout_kills_its_whole_tree(self):
        from partyline_helper.update_installer import Installer, FLAGS
        kernel = SimpleNamespace(**{name: Mock(return_value=1) for name in (
            "CreateJobObjectW", "AssignProcessToJobObject", "TerminateJobObject", "CloseHandle",
            "ResumeThread")})
        process = Mock(_handle=42, thread=43)
        popen = Mock(return_value=process)
        job = Installer(Path("setup.exe"), popen, kernel)
        self.assertEqual(popen.call_args.args[0], ["setup.exe", *FLAGS])
        kernel.AssignProcessToJobObject.assert_called_once_with(1, 42)
        kernel.ResumeThread.assert_called_once_with(43)
        job.wait(120)
        process.wait.assert_called_with(timeout=120)
        job.abort()
        kernel.TerminateJobObject.assert_called_once_with(1, 1)
        job.close()
        kernel.CloseHandle.assert_called_once_with(1)
        kernel.AssignProcessToJobObject.return_value = 0
        with self.assertRaises(OSError):
            Installer(Path("setup.exe"), popen, kernel)
        process.kill.assert_called_once()
        kernel.CreateJobObjectW.return_value = 0
        with self.assertRaises(OSError):
            Installer(Path("setup.exe"), popen, kernel)

class RollbackRegistrationTests(unittest.TestCase):
    @patch("partyline_helper.windows_shortcut.repair")
    def test_installer_can_locate_the_last_working_executable_after_rollback(self, repair):
        from partyline_helper import install_windows
        from tests.test_helper_install import FakeRegistry
        registry = FakeRegistry()
        install_windows.install(registry, [r"C:\Programs\Helper\versions\1.7.0\PartylineHelper.exe"], "log")
        previous = r"C:\Programs\Helper\versions\1.6.0\PartylineHelper.exe"
        install_windows.install(registry, [previous], "log")
        self.assertEqual(registry.values[(install_windows.HELPER_KEY, "Executable")], previous)
        install_windows.uninstall(registry)
        self.assertNotIn((install_windows.HELPER_KEY, "Executable"), registry.values)

class SuspendedProcessTests(unittest.TestCase):
    def test_win32_spawn_retains_thread_and_timeout_is_an_os_wait(self):
        from subprocess import TimeoutExpired
        from partyline_helper.update_installer import SuspendedProcess
        api = SimpleNamespace(CreateProcess=Mock(return_value=(10, 11, 12, 13)),
                              WaitForSingleObject=Mock(return_value=0),
                              GetExitCodeProcess=Mock(return_value=0),
                              TerminateProcess=Mock(), CloseHandle=Mock())
        process = SuspendedProcess(["setup.exe", "/VERYSILENT"], api, object())
        self.assertEqual((process._handle, process.thread, process.pid), (10, 11, 12))
        self.assertEqual(api.CreateProcess.call_args.args[5], 0x08000004)
        self.assertEqual(process.wait(120), 0)
        api.WaitForSingleObject.assert_called_once_with(10, 120000)
        api.WaitForSingleObject.return_value = 258
        with self.assertRaises(TimeoutExpired):
            process.wait(120)
        process.kill()
        api.TerminateProcess.assert_called_once_with(10, 1)
        process.close()
        self.assertEqual([call.args[0] for call in api.CloseHandle.call_args_list], [11, 10])

class UpdateCleanupTests(unittest.TestCase):
    def test_staging_cleanup_only_removes_its_owned_installer_directory(self):
        from partyline_helper import update_cleanup as cleanup
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / "updates" / "staged" / "setup.exe"
            path.parent.mkdir(parents=True)
            path.write_bytes(b"installer")
            outside = root / "keep.exe"
            outside.write_bytes(b"other")
            with patch.object(cleanup, "config_path", return_value=root / "helper.json"):
                cleanup.installer(path)
                cleanup.installer(outside)
            self.assertFalse(path.parent.exists())
            self.assertTrue(outside.exists())

    def test_success_keeps_current_and_previous_version_folders_and_ignores_unrelated_paths(self):
        from partyline_helper import update_cleanup as cleanup
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "versions"
            for version in ("1.4.0", "1.5.0", "1.6.0", "1.7.0", "notes"):
                (root / version).mkdir(parents=True)
            cleanup.versions([str(root / "1.6.0" / "helper.exe")], "1.7.0", active=lambda: None)
            self.assertEqual(sorted(path.name for path in root.iterdir()), ["1.6.0", "1.7.0", "notes"])
            cleanup.versions(["python", "-m", "helper"], "1.8.0")
            self.assertTrue((root / "1.6.0").exists())

    def test_cleanup_protects_a_live_native_host_and_keeps_future_installations(self):
        from partyline_helper import update_cleanup as cleanup
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "versions"
            for version in ("1.3.0", "1.4.0", "1.6.0", "1.7.0", "1.8.0"):
                (root / version).mkdir(parents=True)
            previous = [str(root / "1.6.0" / "helper.exe")]
            cleanup.versions(previous, "1.7.0", active=lambda: "unknown")
            self.assertTrue((root / "1.3.0").exists())
            cleanup.versions(previous, "1.7.0", active=lambda: "1.4.0")
            self.assertFalse((root / "1.3.0").exists())
            self.assertTrue((root / "1.4.0").exists())
            self.assertTrue((root / "1.8.0").exists())


class WindowsShortcutTests(unittest.TestCase):
    def test_rollback_install_repairs_the_start_menu_and_uninstall_icon(self):
        from partyline_helper import windows_shortcut as shortcuts, install_windows
        with tempfile.TemporaryDirectory() as directory:
            old = str(Path(directory) / "versions" / "1.6.0" / "helper.exe")
            shell = Mock()
            shell.SpecialFolders.return_value = str(Path(directory) / "programs")
            registry = Mock()
            shortcuts.repair(old, registry, create=lambda: shell)
            self.assertEqual(shell.CreateShortcut.call_args.args[0],
                             str(Path(directory) / "programs" / "Partyline Helper.lnk"))
            self.assertEqual(shell.CreateShortcut.return_value.TargetPath, old)
            self.assertEqual(shell.CreateShortcut.return_value.Arguments, "start")
            shell.CreateShortcut.return_value.Save.assert_called_once()
            registry.set.assert_called_with(shortcuts.UNINSTALL, "DisplayIcon", old)
            with patch.object(install_windows.os, "name", "nt"), patch.object(shortcuts, "repair") as repair:
                install_windows.install(registry, [old], "log")
            repair.assert_called_once_with(old, registry)
