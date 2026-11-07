"""install / uninstall / open / native consent, all against fakes under temp dirs and a manual clock."""
import contextlib
import io
import json
import plistlib
import sys
import tempfile
import unittest
import warnings
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from partyline_helper import cli, config, install, install_windows, instance, launch, links, urls

warnings.filterwarnings("ignore", message="HTTP LAN connection")
PRIVATE = "http://192.168.1.5:8642"
LAUNCH = ["/venv/bin/python", "-m", "partyline_helper"]


class TempHome(unittest.TestCase):
    """Config, data and home all live in one temp dir; nothing real is read or written."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.home = Path(self.tmp.name)
        env = patch.dict("os.environ", {"XDG_CONFIG_HOME": str(self.home / "config"),
                                        "XDG_DATA_HOME": str(self.home / "data"), "HOME": str(self.home),
                                        "USERPROFILE": str(self.home), "APPDATA": str(self.home),
                                        "LOCALAPPDATA": str(self.home)})
        env.start()
        self.addCleanup(env.stop)
        # Windows' config_path ignores XDG and uses Path.home(); redirect that too.
        home = patch("pathlib.Path.home", return_value=self.home)
        home.start()
        self.addCleanup(home.stop)
        # Guard: production paths must resolve under the temp dir (Windows derives them from Path.home()).
        self.assertEqual(Path.home(), self.home)
        self.assertTrue(config.config_path().is_relative_to(self.home))


class FakeRegistry:
    def __init__(self):
        self.values, self.calls = {}, []

    def set(self, path, name, value):
        self.values[(path, name)] = value

    def delete_value(self, path, name):
        self.values.pop((path, name), None)

    def delete_tree(self, path):
        self.values = {k: v for k, v in self.values.items() if not k[0].startswith(path)}


class FakeRun:
    def __init__(self, returncode=0, stdout="", missing=()):
        self.calls, self.returncode, self.stdout, self.missing = [], returncode, stdout, missing

    def __call__(self, command, **kwargs):
        self.calls.append(command)
        if command[0] in self.missing:
            raise FileNotFoundError(command[0])
        return SimpleNamespace(returncode=self.returncode, stdout=self.stdout, stderr="boom")


class UrlTests(unittest.TestCase):
    def test_valid_links(self):
        self.assertEqual(urls.parse_link("partyline://run"), ("run", {}))
        self.assertEqual(urls.parse_link("partyline://run/"), ("run", {}))
        self.assertEqual(urls.parse_link(f"partyline://pair?server={PRIVATE}&code=abcd1234&name=My%20PC"),
                         ("pair", {"server": PRIVATE, "code": "ABCD1234", "name": "My PC"}))
        self.assertEqual(urls.parse_link("PARTYLINE://Pair?server=https%3A%2F%2Fpl.example&code=0123ABCD"),
                         ("pair", {"server": "https://pl.example", "code": "0123ABCD"}))

    def test_hostile_and_malformed_links_are_rejected(self):
        good = f"partyline://pair?server={PRIVATE}&code=ABCD1234"
        bad = [
            "", None, 42, "http://pair?server=x", "javascript:alert(1)", "partyline:", "partyline://",
            "partyline://other", "partyline://pair", "partyline://pair?code=ABCD1234",
            f"partyline://pair?server={PRIVATE}", f"partyline://pair?server={PRIVATE}&code=ZZZZZZZZ",
            f"partyline://pair?server={PRIVATE}&code=ABCD123", f"partyline://pair?server={PRIVATE}&code=ABCD12345",
            f"partyline://pair?server={PRIVATE}&code=ABCD1234%3B%20rm%20-rf%20%2F",
            f"partyline://pair?server={PRIVATE}&code=ABCD1234%0A", good + "&code=ABCD1235", good + "&x=1",
            good + "#frag", "partyline://user:pw@pair?server=" + PRIVATE + "&code=ABCD1234",
            good.replace("pair?", "pair/x?"), good + "&name=", good + "&name=" + "a" * 121,
            good + "&name=%00%07", good + " ", good.replace("pair", "pa\u00efr"), good + "&name=\u00e9",
            "partyline://run?x=1", "partyline://run#x", "partyline://[::1?x",
            "partyline://pair?server=ftp%3A%2F%2Fpl.example&code=ABCD1234",
            "partyline://pair?server=file%3A%2F%2F%2Fetc&code=ABCD1234",
            "partyline://pair?server=pl.example&code=ABCD1234",
            "partyline://pair?server=https%3A%2F%2Fu%3Ap%40pl.example&code=ABCD1234",
            "partyline://pair?server=https%3A%2F%2Fpl.example%2Fpath&code=ABCD1234",
            "partyline://pair?server=https%3A%2F%2Fpl.example%3Fa%3Db&code=ABCD1234",
            "partyline://pair?server=http%3A%2F%2F8.8.8.8&code=ABCD1234",
            "partyline://pair?server=http%3A%2F%2Fevil.example%24%28id%29&code=ABCD1234",
            "x" * 3000,
        ]
        for link in bad:
            with self.subTest(link=link), self.assertRaises(urls.LinkError):
                urls.parse_link(link)

    def test_unresolvable_http_host_is_rejected(self):
        import socket
        with patch("partyline_helper.config.socket.getaddrinfo", side_effect=socket.gaierror("nope")), \
                self.assertRaises(urls.LinkError):
            urls.parse_link("partyline://pair?server=http%3A%2F%2Fnowhere.invalid&code=ABCD1234")


class LaunchTests(TempHome):
    def test_uvx_environments_are_ephemeral(self):
        temp = self.home / "tmp"
        for prefix, expected in [
            ("/home/u/.cache/uv/archive-v0/abc123", True),
            ("/home/u/.cache/uv/environments-v2/xyz", True),
            (r"C:/Users/u/AppData/Local/uv/cache/archive-v0/abc", True),
            ("/home/u/code/partyline/.venv", False),
            ("/home/u/.local/share/uv/tools/partyline", False),
            ("/home/u/.cache/other/archive-v0/abc", False),
            (str(temp / "tmpabc"), True),
        ]:
            with self.subTest(prefix=prefix):
                self.assertIs(launch.is_ephemeral(prefix, {}, temp), expected)
        custom = self.home / "mycache"
        self.assertTrue(launch.is_ephemeral(custom / "x", {"UV_CACHE_DIR": str(custom)}, temp))
        self.assertFalse(launch.is_ephemeral(self.home / "y", {}, temp))

    def test_current_launch_is_this_interpreter_and_module(self):
        self.assertEqual(launch.current_launch()[1:], ["-m", "partyline_helper"])
        self.assertEqual(launch.current_launch()[0], sys.executable)

    def test_windowless_prefers_pythonw_on_windows_only(self):
        (self.home / "pythonw.exe").write_text("")
        self.assertEqual(launch.windowless(self.home / "python.exe", True), str(self.home / "pythonw.exe"))
        self.assertEqual(launch.windowless(self.home / "other" / "python.exe", True),
                         str(self.home / "other" / "python.exe"))
        self.assertEqual(launch.windowless(self.home / "python.exe", False), str(self.home / "python.exe"))
        self.assertEqual(launch.windowless(self.home / "python.exe"), str(self.home / "python.exe"))

    def fake_tool(self, python=True):
        env = self.home / "tools" / "partyline" / "bin"
        if python:
            env.mkdir(parents=True)
            (env / "python").write_text("")
        results = [SimpleNamespace(returncode=0, stdout="", stderr=""),
                   SimpleNamespace(returncode=0, stdout=str(self.home / "tools") + "\n", stderr="")]
        calls = []

        def run(command, **kwargs):
            calls.append(command)
            return results.pop(0)
        return run, calls, env

    def test_ephemeral_installs_a_stable_tool_copy(self):
        run, calls, env = self.fake_tool()
        result, notes = launch.resolve_launch(True, run=run, which=lambda name: "/bin/uv", env={})
        self.assertEqual(result, [str(env / "python"), "-m", "partyline_helper"])
        self.assertEqual(calls[0], ["/bin/uv", "tool", "install", "--force", launch.SPEC])
        self.assertEqual(calls[1], ["/bin/uv", "tool", "dir"])
        self.assertIn("temporary uvx cache", notes[0])
        self.assertIn("uv tool install", notes[1])

    def test_ephemeral_failures_are_actionable(self):
        with self.assertRaisesRegex(RuntimeError, "uv was not found"):
            launch.tool_launch(run=FakeRun(), which=lambda name: None, env={})
        with self.assertRaisesRegex(RuntimeError, "install` failed:\nboom"):
            launch.tool_launch(run=FakeRun(returncode=2), which=lambda name: "uv", env={})
        results = [SimpleNamespace(returncode=0, stdout="", stderr=""),
                   SimpleNamespace(returncode=1, stdout="", stderr="")]
        with self.assertRaisesRegex(RuntimeError, "tool dir"):
            launch.tool_launch(run=lambda *a, **k: results.pop(0), which=lambda name: "uv", env={})
        run, _, _ = self.fake_tool(python=False)
        with self.assertRaisesRegex(RuntimeError, "no interpreter"):
            launch.tool_launch(run=run, which=lambda name: "uv", env={"UV": "/x/uv"})

    def test_stable_environment_is_used_in_place(self):
        with patch("partyline_helper.launch.is_ephemeral", return_value=False):
            result, notes = launch.resolve_launch()
        self.assertEqual(result, launch.current_launch())
        self.assertIn("using this environment", notes[0])

    def test_record_round_trip_and_fallbacks(self):
        path = self.home / "config" / "partyline" / "install.json"
        self.assertEqual(launch.recorded_launch(path), launch.current_launch())
        launch.save_record(LAUNCH, path)
        self.assertEqual(launch.recorded_launch(path), LAUNCH)
        for junk in ("not json", json.dumps({"launch": "x"}), json.dumps({"launch": [1]}), "{}", "[]"):
            path.write_text(junk)
            self.assertEqual(launch.recorded_launch(path), launch.current_launch())


class InstallTests(TempHome):
    def installer(self, system, **kwargs):
        env = {"XDG_CONFIG_HOME": str(self.home / "config"), "XDG_DATA_HOME": str(self.home / "data")}
        return install.Installer(system, self.home / "h", env, **kwargs)

    def snapshot(self):
        return {str(p): p.read_bytes() for p in self.home.rglob("*") if p.is_file()}

    def test_linux_install_writes_handler_and_autostart_and_is_idempotent(self):
        run = FakeRun()
        installer = self.installer("Linux", run=run)
        first = installer.install(["/my venv/bin/python", "-m", "partyline_helper"])
        handler, autostart = installer.linux_paths()
        text = handler.read_text()
        self.assertIn("MimeType=x-scheme-handler/partyline;", text)
        self.assertIn('Exec="/my venv/bin/python" -m partyline_helper open -- %u', text)
        self.assertIn("Terminal=false", text)
        self.assertIn(" run --log ", autostart.read_text())
        self.assertIn("helper.log", autostart.read_text())
        self.assertEqual(run.calls[0], ["xdg-mime", "default", "partyline-helper.desktop",
                                        "x-scheme-handler/partyline"])
        self.assertTrue(any(str(handler) in line for line in first))
        self.assertTrue(any(str(autostart) in line for line in first))
        before = self.snapshot()
        second = installer.install(["/my venv/bin/python", "-m", "partyline_helper"])
        self.assertEqual(before, self.snapshot())
        self.assertEqual(first, second)

    def test_linux_tool_problems_are_warnings_not_failures(self):
        missing = FakeRun(missing=("xdg-mime", "update-desktop-database"))
        lines = self.installer("Linux", run=missing).install(LAUNCH)
        self.assertTrue(any("xdg-mime" in line and "unavailable" in line for line in lines))
        lines = self.installer("Linux", run=FakeRun(returncode=3)).install(LAUNCH)
        self.assertTrue(any("exited 3" in line for line in lines))

    def test_linux_uninstall_removes_only_what_install_made(self):
        installer = self.installer("Linux", run=FakeRun())
        pairing = self.home / "config" / "partyline" / "helper.json"
        pairing.parent.mkdir(parents=True)
        pairing.write_text("{}")
        installer.install(LAUNCH)
        out = installer.uninstall()
        self.assertTrue(all(line.startswith("removed") for line in out))
        self.assertEqual([p for p in installer.linux_paths() if p.exists()], [])
        self.assertTrue(pairing.exists())
        again = installer.uninstall()
        self.assertTrue(all(line.startswith("not present") for line in again))

    def test_default_xdg_locations_fall_back_to_home(self):
        installer = install.Installer("Linux", self.home, {}, run=FakeRun())
        handler, autostart = installer.linux_paths()
        self.assertEqual(handler, self.home / ".local/share/applications/partyline-helper.desktop")
        self.assertEqual(autostart, self.home / ".config/autostart/partyline-helper.desktop")

    def test_windows_install_uses_hkcu_only_and_is_idempotent(self):
        registry = FakeRegistry()
        installer = self.installer("Windows", registry=registry)
        launch_cmd = [r"C:\Program Files\py\pythonw.exe", "-m", "partyline_helper"]
        first = installer.install(launch_cmd)
        opener = registry.values[(install_windows.PROTOCOL + r"\shell\open\command", "")]
        self.assertEqual(opener, '"C:\\Program Files\\py\\pythonw.exe" -m partyline_helper open -- "%1"')
        self.assertEqual(registry.values[(install_windows.PROTOCOL, "URL Protocol")], "")
        runner = registry.values[(install_windows.RUN_KEY, "PartylineHelper")]
        self.assertIn("pythonw.exe", runner)
        self.assertIn("run --log", runner)
        self.assertTrue(all(path.startswith("Software\\") for path, _ in registry.values))
        self.assertTrue(any("HKCU" in line for line in first))
        snapshot = dict(registry.values)
        self.assertEqual(installer.install(launch_cmd), first)
        self.assertEqual(snapshot, registry.values)
        out = installer.uninstall()
        self.assertEqual(registry.values, {})
        self.assertEqual(len(out), 2)
        installer.uninstall()

    def test_macos_install_writes_a_launch_agent_and_says_no_url_handler(self):
        run = FakeRun()
        installer = self.installer("Darwin", run=run)
        lines = installer.install(LAUNCH)
        plist = plistlib.loads(installer.mac_plist().read_bytes())
        self.assertEqual(plist["Label"], "io.partyline.helper")
        self.assertEqual(plist["ProgramArguments"][:3], LAUNCH)
        self.assertEqual(plist["ProgramArguments"][3:5], ["run", "--log"])
        self.assertTrue(plist["RunAtLoad"])
        self.assertTrue(any("not available on macOS" in line for line in lines))
        self.assertEqual([c[1] for c in run.calls], ["bootout", "bootstrap"])
        before = self.snapshot()
        installer.install(LAUNCH)
        self.assertEqual(before, self.snapshot())
        failing = self.installer("Darwin", run=FakeRun(returncode=5)).install(LAUNCH)
        self.assertIn("warning", " ".join(failing))
        out = installer.uninstall()
        self.assertTrue(out[0].startswith("removed"))
        self.assertFalse(installer.mac_plist().exists())
        self.assertEqual(run.calls[-1][1], "bootout")

    def test_desktop_quoting_never_leaves_specials_bare(self):
        self.assertEqual(install.desktop_quote("plain"), "plain")
        self.assertEqual(install.desktop_quote("a b"), '"a b"')
        self.assertEqual(install.desktop_quote('a"$`\\'), '"a\\"\\$\\`\\\\"')
        self.assertEqual(install.desktop_quote("100%"), "100%%")

    def test_install_command_records_launch_and_uninstall_keeps_pairing(self):
        pairing = self.home / "config" / "partyline" / "helper.json"
        pairing.parent.mkdir(parents=True)
        pairing.write_text("{}")
        installer = self.installer("Linux", run=FakeRun())
        with patch("partyline_helper.launch.is_ephemeral", return_value=False):
            text = install.install_command(installer)
        self.assertIn("launch command:", text)
        self.assertIn("start at login:", text)
        self.assertEqual(launch.recorded_launch(), launch.current_launch())
        self.assertTrue(launch.record_path().exists())
        text = install.uninstall_command(installer)
        self.assertFalse(launch.record_path().exists())
        self.assertIn("left in place", text)
        self.assertTrue(pairing.exists())

    def test_platform_defaults(self):
        for platform, name in (("win32", "Windows"), ("darwin", "Darwin"), ("linux", "Linux")):
            with patch("partyline_helper.install.sys.platform", platform):
                self.assertEqual(install.Installer().system, name)


class InstanceTests(TempHome):
    def test_second_launch_sees_the_holder_and_hands_off(self):
        first = instance.InstanceLock("run")
        self.assertTrue(first.acquire())
        second = instance.InstanceLock("run")
        self.assertFalse(second.acquire())
        self.assertEqual(second.holder(), first.holder())
        self.assertIsNotNone(second.holder())
        with instance.InstanceLock("run") as taken:
            self.assertIsNone(taken)
        first.release()
        self.assertIsNone(second.holder())
        with instance.InstanceLock("run") as taken:
            self.assertIsNotNone(taken)
            self.assertIsNotNone(taken.handle)
        first.release()

    def test_holder_pid_is_readable_when_the_lock_file_denies_reads(self):
        """Windows byte-range locks make the locked file unreadable to other processes."""
        first = instance.InstanceLock("run")
        self.assertTrue(first.acquire())
        original = Path.read_text

        def read_text(path, *args, **kwargs):
            if path.suffix == ".lock":
                raise PermissionError("locked by another process")
            return original(path, *args, **kwargs)
        with patch.object(Path, "read_text", read_text):
            self.assertEqual(instance.InstanceLock("run").holder(), first.holder())
            self.assertIsNotNone(instance.InstanceLock("run").holder())
        first.release()
        self.assertFalse(first.pid_path.exists())

    def test_release_never_deletes_the_pid_of_the_next_owner(self):
        """A new owner may take the lock the instant it is released; its pid must survive."""
        first, second = instance.InstanceLock("run"), instance.InstanceLock("run")
        self.assertTrue(first.acquire())
        real = first.handle

        class Handle:
            def __init__(self):
                self.entered = []

            def close(self):
                real.close()
                self.entered.append(second.acquire())  # next owner wins right after the unlock

            def __getattr__(self, name):
                return getattr(real, name)
        first.handle = proxy = Handle()
        first.release()
        self.assertEqual(proxy.entered, [True])
        self.assertEqual(instance.InstanceLock("run").holder(), second.holder())
        self.assertIsNotNone(instance.InstanceLock("run").holder())
        second.release()

    def test_holder_that_has_not_written_its_pid_yet_is_unknown(self):
        first = instance.InstanceLock("run")
        self.assertTrue(first.acquire())
        first.pid_path.write_text("not a pid")
        self.assertIsNone(instance.InstanceLock("run").holder())
        first.release()

    def test_spawn_is_detached_argv(self):
        calls = []
        instance.spawn_detached(["py", "-m", "x"], popen=lambda *a, **k: calls.append((a, k)))
        (args, kwargs), = calls
        self.assertEqual(args, (["py", "-m", "x"],))
        self.assertTrue(kwargs["start_new_session"])
        self.assertNotIn("shell", kwargs)


class FakeLock:
    """Stands in for InstanceLock without touching files."""
    held = set()

    def __init__(self, name):
        self.name = name

    def __enter__(self):
        return None if self.name in self.held else self

    def __exit__(self, *exc):
        pass

    def holder(self):
        return 4242 if self.name in self.held else None

    def acquire(self):
        return self.name not in self.held


class OpenLinkTests(TempHome):
    def setUp(self):
        super().setUp()
        FakeLock.held = set()
        self.events, self.told = [], []
        self.link = f"partyline://pair?server={PRIVATE}&code=ABCD1234&name=Desk"

    def ask(self, answer):
        async def ask(title, text):
            self.events.append(("ask", text))
            return answer
        return ask

    def open(self, url, answer=True, **kwargs):
        kwargs.setdefault("ensure", lambda restart=False: f"ensured restart={restart}")
        return links.open_link(url, ask=self.ask(answer), tell=lambda *a: self.told.append(a),
                               pairing=lambda *a: self.events.append(("pair", a)), lock=FakeLock,
                               hostname=lambda: "host", **kwargs)

    def test_confirmed_pair_pairs_then_restarts_the_helper(self):
        result = self.open(self.link)
        self.assertEqual(self.events[0][0], "ask")
        self.assertIn(f"Pair this computer with {PRIVATE}?", self.events[0][1])
        self.assertEqual(self.events[1], ("pair", (PRIVATE, "ABCD1234", "Desk")))
        self.assertIn("ensured restart=True", result)

    def test_declined_pair_changes_nothing(self):
        self.assertEqual(self.open(self.link, answer=False), "Pairing declined.")
        self.assertEqual([e[0] for e in self.events], ["ask"])

    def test_default_name_is_the_hostname_and_old_pairing_is_mentioned(self):
        config = self.home / "config" / "partyline" / "helper.json"
        config.parent.mkdir(parents=True)
        config.write_text(json.dumps({"server": "https://old.example"}))
        self.open(f"partyline://pair?server={PRIVATE}&code=ABCD1234")
        self.assertIn("host", self.events[0][1])
        self.assertIn("replaces your current pairing with https://old.example", self.events[0][1])
        self.assertEqual(self.events[1][1][2], "host")

    def test_run_link_only_ensures_running_with_no_prompt(self):
        self.assertEqual(self.open("partyline://run"), "ensured restart=False")
        self.assertEqual(self.events, [])

    def test_bad_links_are_rejected_and_the_person_is_told(self):
        for link in ("partyline://pair?server=x&code=y", "http://evil", "partyline://pair?server=" + PRIVATE):
            self.assertTrue(self.open(link).startswith("Rejected link"))
        self.assertEqual(self.events, [])
        self.assertEqual(len(self.told), 3)

    def test_pairing_failure_is_reported(self):
        def broken(*args):
            raise OSError("secret-token-in-message")
        result = links.open_link(self.link, ask=self.ask(True), tell=lambda *a: self.told.append(a),
                                 pairing=broken, lock=FakeLock, hostname=lambda: "h",
                                 ensure=lambda restart=False: "x")
        self.assertEqual(result, "Pairing failed (OSError).")
        self.assertNotIn("secret", str(self.told))

    def test_concurrent_link_hands_off_cleanly(self):
        FakeLock.held = {"open"}
        self.assertIn("Another Partyline link", self.open(self.link))
        self.assertEqual(self.events, [])


class EnsureRunningTests(TempHome):
    def go(self, holder, restart):
        FakeLock.held = {"run"} if holder else set()
        spawned, stopped = [], []
        text = links.ensure_running(restart, spawn=spawned.append,
                                    stop=lambda: (stopped.append(4242), (True, "stopped"))[1],
                                    launch=lambda: LAUNCH, lock=FakeLock)
        return text, spawned, stopped

    def test_already_running_is_left_alone(self):
        text, spawned, killed = self.go(True, False)
        self.assertIn("already running (pid 4242)", text)
        self.assertEqual((spawned, killed), ([], []))

    def test_not_running_starts_run_with_the_recorded_command_and_log(self):
        text, spawned, killed = self.go(False, False)
        self.assertEqual(spawned, [LAUNCH + ["run", "--log", str(links.log_path())]])
        self.assertIn("Started", text)

    def test_restart_replaces_the_running_helper(self):
        text, spawned, killed = self.go(True, True)
        self.assertEqual(killed, [4242])  # the stop routine ran (polite stop file, then by pid)
        self.assertEqual(spawned[0][-1], "--wait")
        self.assertIn("Restarted", text)


class ClaimRunTests(TempHome):
    def test_claim_sets_log_and_blocks_a_second_helper(self):
        links._held.clear()
        log = self.home / "logs" / "helper.log"
        out, err = sys.stdout, sys.stderr
        try:
            self.assertTrue(links.claim_run(log))
            sys.stdout.write("hello\n")
            sys.stdout.flush()
            self.assertEqual(log.read_text(), "hello\n")
            sys.stdout.close()
        finally:
            sys.stdout, sys.stderr = out, err
        self.assertFalse(links.claim_run(None))
        links._held.pop().release()

    def test_wait_retries_until_the_old_helper_releases(self):
        links._held.clear()
        holder = instance.InstanceLock("run")
        holder.acquire()
        sleeps = []

        def sleep(seconds):
            sleeps.append(seconds)
            holder.release()
        self.assertTrue(links.claim_run(None, wait=True, sleep=sleep))
        self.assertEqual(sleeps, [0.1])
        links._held.pop().release()
        holder = instance.InstanceLock("run")
        holder.acquire()
        self.assertFalse(links.claim_run(None, wait=True, sleep=lambda s: None, attempts=3))
        holder.release()


class CliTests(TempHome):
    def main(self, *argv):
        with contextlib.redirect_stdout(io.StringIO()) as out:
            cli.main(list(argv))
        return out.getvalue()

    def test_install_uninstall_open_dispatch(self):
        with patch("partyline_helper.install.install_command",
                   return_value="installed"):
            self.assertIn("installed", self.main("install"))
        with patch("partyline_helper.install.uninstall_command", return_value="gone"):
            self.assertIn("gone", self.main("uninstall"))
        with patch("partyline_helper.links.open_link", return_value="opened") as opener:
            self.assertIn("opened", self.main("open", "--", "partyline://run"))
        opener.assert_called_once_with("partyline://run")

    def test_module_entry_point_runs_main(self):
        import runpy
        with patch.object(sys, "argv", ["partyline_helper", "--help"]), \
                contextlib.redirect_stdout(io.StringIO()) as out, self.assertRaises(SystemExit):
            runpy.run_module("partyline_helper", run_name="__main__")
        self.assertIn("install", out.getvalue())

    def test_run_exits_cleanly_when_another_helper_runs(self):
        with patch("partyline_helper.links.claim_run", return_value=False) as claim:
            self.assertIn("already running", self.main("run", "--log", "x.log"))
        claim.assert_called_once_with(Path("x.log"), False)
