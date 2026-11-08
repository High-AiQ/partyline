"""Windows installer support, tested on Linux with fakes: foreground, stop, tray, status, frozen launch."""
import asyncio
import contextlib
import io
import json
import os
import signal
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from websockets.asyncio.server import serve as websocket_server

from partyline_helper import cli, foreground, install_windows, launch, links, runtime, stopping, tray, version
from partyline_helper.status import Status
from tests.screen_helper_fakes import FakeDesktop, FakeTerminal, ManualTime, request, serve


class FakeUser32:
    """Records Win32 calls; `foreground_after` lists which call counts of GetForegroundWindow match."""

    def __init__(self, front=(), iconic=False, theirs=7):
        self.calls, self.front, self.iconic, self.theirs, self.focused = [], list(front), iconic, theirs, None

    def __getattr__(self, name):
        def call(*args):
            self.calls.append(name)
            if name == "GetForegroundWindow":
                return self.front.pop(0) if self.front else 0
            if name == "IsIconic":
                return self.iconic
            if name == "GetWindowThreadProcessId":
                return self.theirs
            return 1
        return call


class ForegroundTests(unittest.TestCase):
    kernel = SimpleNamespace(GetCurrentThreadId=lambda: 1)

    def test_already_in_front_needs_nothing_more(self):
        user = FakeUser32(front=[42])
        self.assertTrue(foreground.bring_to_front(42, user, self.kernel))
        self.assertEqual(user.calls, ["IsIconic", "ShowWindow", "SetWindowPos", "GetForegroundWindow"])

    def test_minimised_windows_are_restored(self):
        user = FakeUser32(front=[42], iconic=True)
        foreground.bring_to_front(42, user, self.kernel)
        self.assertEqual(user.calls[:2], ["IsIconic", "ShowWindow"])

    def test_a_refused_foreground_borrows_the_input_queue_then_taps_alt_then_succeeds(self):
        # not front, (thread lookup), after SetForegroundWindow: still not front, after Alt: yes
        user = FakeUser32(front=[0, 99, 0, 42])
        self.assertTrue(foreground.bring_to_front(42, user, self.kernel))
        self.assertEqual(user.calls.count("AttachThreadInput"), 2)  # attach, then detach
        self.assertEqual(user.calls.count("keybd_event"), 2)  # Alt down and up
        self.assertEqual(user.calls.count("SetForegroundWindow"), 2)
        self.assertNotIn("FlashWindowEx", user.calls)

    def test_when_windows_still_refuses_the_taskbar_button_flashes(self):
        user = FakeUser32(front=[0, 99, 0, 0])
        self.assertFalse(foreground.bring_to_front(42, user, self.kernel))
        self.assertEqual(user.calls[-1], "FlashWindowEx")

    def test_no_attach_when_the_foreground_thread_is_ours_or_unknown(self):
        for theirs in (1, 0):
            user = FakeUser32(front=[0, 99, 0, 42], theirs=theirs)
            foreground.bring_to_front(42, user, self.kernel)
            self.assertNotIn("AttachThreadInput", user.calls)

    def test_flash_asks_to_flash_until_foreground(self):
        seen = []
        foreground.flash_taskbar(5, SimpleNamespace(FlashWindowEx=lambda ref: seen.append(ref._obj)))
        self.assertEqual(seen[0].hwnd, 5)
        self.assertEqual(seen[0].dwFlags, foreground.FLASHW_ALL | foreground.FLASHW_TIMERNOFG)


class FakeRoot:
    def __init__(self, handle="0x2a"):
        self.calls, self.handle, self.scheduled = [], handle, []

    def __getattr__(self, name):
        def call(*args):
            self.calls.append((name, args))
            return {"wm_frame": self.handle, "winfo_reqwidth": 400, "winfo_reqheight": 200,
                    "winfo_screenwidth": 1000, "winfo_screenheight": 900}.get(name)
        return call

    def after(self, ms, fn):
        self.scheduled.append((ms, fn))


class RaiseWindowTests(unittest.TestCase):
    def test_off_windows_it_lifts_and_focuses(self):
        root = FakeRoot()
        self.assertTrue(foreground.raise_window(root, windows=False))
        names = [name for name, _ in root.calls]
        self.assertIn("lift", names)
        self.assertIn("focus_force", names)
        self.assertIn(("attributes", ("-topmost", True)), root.calls)

    def test_on_windows_the_tk_frame_handle_goes_to_bring_to_front(self):
        root, seen = FakeRoot("0x2a"), []
        bring = lambda hwnd, user, kernel: seen.append((hwnd, user, kernel)) or True  # noqa: E731
        self.assertTrue(foreground.raise_window(root, bring, lambda: ("u", "k"), windows=True))
        self.assertEqual(seen, [(42, "u", "k")])

    def test_errors_are_swallowed_and_report_not_foreground(self):
        def broken():
            raise OSError("no user32")
        self.assertFalse(foreground.raise_window(FakeRoot(), libraries=broken, windows=True))
        self.assertFalse(foreground.raise_window(FakeRoot("nonsense"), Mock(), lambda: (1, 2), windows=True))

    def test_keep_raising_retries_until_in_front_or_out_of_tries(self):
        root = FakeRoot()
        results = iter([False, False, True])
        foreground.keep_raising(root, lambda r: next(results), tries=6, delay_ms=300)
        for _ in range(3):
            root.scheduled.pop(0)[1]()
        self.assertEqual(root.scheduled, [])
        root = FakeRoot()
        foreground.keep_raising(root, lambda r: False, tries=3, delay_ms=300)
        for _ in range(3):
            root.scheduled.pop(0)[1]()
        self.assertEqual(root.scheduled, [])  # gave up after three, never raised again

    def test_the_dialog_is_centred_a_third_down(self):
        root = FakeRoot()
        foreground.center(root)
        self.assertIn(("geometry", ("+300+233",)), root.calls)


class FakeLock:
    """`holders` is consumed per `.holder()` call, so a test scripts how the helper goes away."""
    holders = []

    def __init__(self, name):
        pass

    def holder(self):
        return FakeLock.holders.pop(0) if len(FakeLock.holders) > 1 else FakeLock.holders[0]


class StopTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "run.stop"
        self.naps, self.kills = [], []

    def stop(self, holders):
        FakeLock.holders = holders
        return stopping.stop_helper(FakeLock, lambda pid, sig: self.kills.append((pid, sig)),
                                    self.naps.append, self.path)

    def test_nothing_running_is_fine_and_clears_a_stale_request(self):
        self.path.write_text("stop")
        self.assertEqual(self.stop([None]), (True, "The helper is not running."))
        self.assertFalse(self.path.exists())

    def test_a_helper_that_obeys_the_stop_file_is_not_killed(self):
        stopped, text = self.stop([4242, 4242, None])
        self.assertTrue(stopped)
        self.assertIn("4242", text)
        self.assertEqual(self.kills, [])
        self.assertEqual(self.path.read_text(), "stop")  # the helper deletes it as it exits
        self.assertEqual(self.naps, [stopping.POLL])

    def test_an_old_helper_that_ignores_the_file_is_ended_by_pid(self):
        stopped, text = self.stop([4242] * (stopping.WAITS + 2) + [None])
        self.assertTrue(stopped)
        self.assertIn("ending the process", text)
        self.assertEqual(self.kills, [(4242, signal.SIGTERM)])
        self.assertFalse(self.path.exists())  # nobody will read it now

    def test_a_helper_that_survives_everything_is_reported(self):
        stopped, text = self.stop([4242])
        self.assertFalse(stopped)
        self.assertIn("Task Manager", text)

    def test_a_kill_that_is_denied_is_not_fatal(self):
        FakeLock.holders = [4242]

        def deny(pid, sig):
            raise PermissionError
        self.assertFalse(stopping.stop_helper(FakeLock, deny, self.naps.append, self.path)[0])


class WatchStopTests(unittest.IsolatedAsyncioTestCase):
    async def test_the_stop_file_cancels_the_helper_and_is_consumed(self):
        with tempfile.TemporaryDirectory() as tmp:
            path, clock, cancelled = Path(tmp) / "run.stop", ManualTime(), []
            watching = asyncio.create_task(
                stopping.watch_stop(lambda: cancelled.append(1), path, clock.sleep))
            self.assertEqual(await clock.sleep_calls.get(), 0.5)
            self.assertEqual(cancelled, [])
            path.write_text("stop")
            clock.advance(0.5)
            await watching
            self.assertEqual(cancelled, [1])
            self.assertFalse(path.exists())


class GuardedTests(unittest.IsolatedAsyncioTestCase):
    async def never_ends(self):
        await asyncio.Event().wait()

    async def test_a_stop_request_ends_the_helper_cleanly(self):
        status, out = Status(), io.StringIO()

        async def watch(cancel):
            cancel()
        with contextlib.redirect_stdout(out):
            await runtime.guarded(self.never_ends(), status, watch)
        self.assertIn("Helper stopped.", out.getvalue())

    async def test_the_tray_quit_cancels_from_another_thread(self):
        status = Status()
        quitting = asyncio.Event()

        async def watch(cancel):
            await quitting.wait()
        task = asyncio.create_task(runtime.guarded(self.never_ends(), status, watch))
        while status.quit is None:
            await asyncio.sleep(0)
        with contextlib.redirect_stdout(io.StringIO()):
            await asyncio.to_thread(status.request_quit)
            await task

    async def test_ctrl_c_still_propagates(self):
        status = Status()

        async def watch(cancel):
            await asyncio.Event().wait()
        task = asyncio.create_task(runtime.guarded(self.never_ends(), status, watch))
        await asyncio.sleep(0)
        await asyncio.sleep(0)
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task


class RuntimeHelperTests(unittest.TestCase):
    def test_failures_become_dialogs_only_without_a_terminal(self):
        told = []
        with contextlib.redirect_stdout(io.StringIO()) as out:
            runtime.fail("broken", lambda: True, lambda *a: told.append(a))
            self.assertEqual(told, [])
            runtime.fail("broken", lambda: False, lambda *a: told.append(a))
        self.assertEqual(told, [("Partyline Helper", "broken")])
        self.assertIn("broken", out.getvalue())

    def test_the_tray_is_on_by_default_on_windows_only(self):
        self.assertTrue(runtime.tray_wanted(False, windows=True))
        self.assertFalse(runtime.tray_wanted(True, windows=True))
        self.assertFalse(runtime.tray_wanted(False, windows=False))
        self.assertEqual(runtime.tray_wanted(False), os.name == "nt")

    def test_start_explains_an_unpaired_or_running_helper_and_otherwise_just_starts(self):
        told = []
        tell = lambda title, text: told.append(text)  # noqa: E731
        runtime.start_helper(lambda: False, Mock(), tell)
        self.assertIn("not paired yet", told[-1])
        self.assertEqual(runtime.start_helper(lambda: True, lambda: "The helper is already running (pid 1).",
                                              tell), "The helper is already running (pid 1).")
        self.assertIn("system tray", told[-1])
        count = len(told)
        runtime.start_helper(lambda: True, lambda: "Started the helper in the background.", tell)
        self.assertEqual(len(told), count)


class FakeIcon:
    instances = []

    def __init__(self, name, image, title, menu):
        self.name, self.icon, self.title, self.menu = name, image, title, menu
        self.notified, self.updates, self.running, self.stopped = [], 0, False, False
        FakeIcon.instances.append(self)

    def run_detached(self):
        self.running = True

    def update_menu(self):
        self.updates += 1

    def notify(self, text, title):
        self.notified.append((text, title))

    def stop(self):
        self.stopped = True


FAKE_BACKEND = SimpleNamespace(Icon=FakeIcon, Menu=lambda *items: list(items),
                               MenuItem=lambda text, action, enabled=True: SimpleNamespace(
                                   text=text, action=action, enabled=enabled))


class TrayTests(unittest.TestCase):
    def test_icon_follows_status_and_menu_acts_through_callbacks(self):
        status, FakeIcon.instances, ended = Status(), [], []
        shown = tray.start_tray(status, FAKE_BACKEND)
        icon = FakeIcon.instances[0]
        self.assertTrue(icon.running)
        label, stop, choose_window, stop_window, end_tools, end_checks, quit_item = icon.menu
        picked, revoked = [], []
        status.choose_window, status.stop_window = lambda: picked.append(1), lambda: revoked.append(1)
        choose_window.action()
        self.assertEqual(picked, [1])
        self.assertFalse(stop_window.enabled(None))
        status.window_title = "Editor"
        self.assertTrue(stop_window.enabled(None))
        stop_window.action()
        self.assertEqual(revoked, [1])
        status.window_title = None
        self.assertEqual(end_tools.text, "End agent session")
        self.assertFalse(end_tools.enabled(None))
        self.assertEqual(end_checks.text, "Stop render checks")
        self.assertFalse(end_checks.enabled(None))
        status.checks_active, status.stop_checks = True, lambda: ended.append("checks")
        self.assertTrue(end_checks.enabled(None))
        end_checks.action()
        status.checks_active = False
        self.assertEqual(ended, ["checks"])
        ended.clear()
        status.tools_active, status.stop_tools = True, lambda: ended.append(1)
        self.assertTrue(end_tools.enabled(None))
        end_tools.action()
        status.tools_active = False
        self.assertEqual(ended, [1])
        self.assertEqual(label.text(None), "Not connected to Partyline")
        self.assertFalse(stop.enabled(None))
        stops, quits = [], []
        status.stop_share, status.quit = lambda: stops.append(1), lambda: quits.append(1)
        status.set("paired")
        status.set("sharing")
        self.assertTrue(stop.enabled(None))
        self.assertEqual(label.text(None), "Sharing part of your screen")
        self.assertIn("Sharing", icon.title)
        stop.action()
        quit_item.action()
        self.assertEqual((stops, quits), ([1], [1]))
        self.assertEqual(icon.updates, 2)
        status.attention("Answer me")
        self.assertEqual(icon.notified, [("Answer me", "Partyline Helper")])
        shown.stop()
        self.assertTrue(icon.stopped)
        shown.stop()  # idempotent

    def test_each_state_has_its_own_colour_and_a_tray_that_cannot_start_is_none(self):
        pixels = {state: tray.draw_icon(state).getpixel((32, 32)) for state in tray.COLORS}
        self.assertEqual(len(set(pixels.values())), 5)

        def broken(*a, **k):
            raise RuntimeError("no tray on this desktop")
        self.assertIsNone(tray.start_tray(Status(), SimpleNamespace(Icon=broken)))

    def test_broken_listeners_never_break_the_share(self):
        status = Status()
        status.listeners.append(Mock(side_effect=RuntimeError))
        status.attention_listeners.append(Mock(side_effect=RuntimeError))
        status.set("sharing")
        status.attention("x")
        status.request_stop_share()  # no callbacks registered: nothing happens
        status.request_quit()

    def test_icon_methods_fail_soft(self):
        status = Status()
        shown = tray.Tray(status, FAKE_BACKEND)
        shown.refresh("paired")  # not started
        shown.notify("x")
        shown.start()
        shown.icon.notify = Mock(side_effect=RuntimeError)
        shown.icon.stop = Mock(side_effect=RuntimeError)
        shown.notify("x")
        shown.stop()


class VersionTests(unittest.TestCase):
    def test_version_comes_from_metadata_or_is_unknown(self):
        self.assertEqual(version.helper_version(lambda name: "9.9.9"), "9.9.9")

        def missing(name):
            raise version.PackageNotFoundError(name)
        self.assertEqual(version.helper_version(missing), "unknown")

    def test_cli_prints_it(self):
        with contextlib.redirect_stdout(io.StringIO()) as out, \
                patch.object(version, "version", lambda n: "1.2.3"):
            cli.main(["version"])
        self.assertEqual(out.getvalue().strip(), "1.2.3")


class SessionStatusTests(unittest.IsolatedAsyncioTestCase):
    async def test_hello_reports_the_version_and_status_follows_the_share(self):
        status, states, hello = Status(), [], []
        status.listeners.append(states.append)
        terminal = FakeTerminal()
        done = asyncio.Event()

        async def receive(ws, kind):
            while True:
                raw = await ws.recv()
                if not isinstance(raw, bytes) and json.loads(raw)["type"] == kind:
                    return json.loads(raw)

        async def handler(ws):
            hello.append(json.loads(await ws.recv()))
            await ws.send(json.dumps(request()))
            await receive(ws, "share_accepted")
            await receive(ws, "frame")
            # the tray's Stop sharing, from another thread
            await asyncio.to_thread(status.request_stop_share)
            stopped = await receive(ws, "share_stopped")
            hello.append(stopped)
            await ws.close(code=4001, reason="revoked")
            done.set()
        async with websocket_server(handler, "127.0.0.1", 0, ping_interval=None) as server:
            port = server.sockets[0].getsockname()[1]
            with self.assertWarns(UserWarning), patch.object(version, "version", lambda n: "7.8.9"), \
                    contextlib.redirect_stdout(io.StringIO()):
                await serve(dict(server=f"http://127.0.0.1:{port}", token="t"), FakeDesktop(), terminal,
                            status=status)
            await done.wait()
        self.assertEqual(hello[0]["helper_version"], "7.8.9")
        self.assertEqual(hello[1]["reason"], "local")
        self.assertEqual(states, ["paired", "sharing", "paired", "offline"])
        self.assertIsNone(status.stop_share)

    async def test_agent_control_shows_in_the_status(self):
        from partyline_helper.control import border_mode
        session = SimpleNamespace(status=Status(), border=None)
        border_mode(session, "control")
        self.assertEqual(session.status.state, "control")
        border_mode(session, "share")
        self.assertEqual(session.status.state, "sharing")


class FrozenLaunchTests(unittest.TestCase):
    def test_a_frozen_exe_launches_itself_and_is_never_ephemeral(self):
        with patch.object(sys, "frozen", True, create=True), patch.object(sys, "executable", "C:/H/PH.exe"):
            self.assertEqual(launch.current_launch(), ["C:/H/PH.exe"])
            self.assertFalse(launch.is_ephemeral(prefix="/tmp/x", temp="/tmp"))
            self.assertEqual(launch.resolve_launch()[0], ["C:/H/PH.exe"])

    def test_the_installer_registers_the_frozen_exe_for_links_and_login(self):
        values = {}

        class Registry:
            def set(self, path, name, value):
                values[(path, name)] = value
        exe = r"C:\Users\me\AppData\Local\Programs\Partyline Helper\PartylineHelper.exe"
        install_windows.install(Registry(), [exe], Path(r"C:\log.txt"))
        opener = values[(install_windows.PROTOCOL + r"\shell\open\command", "")]
        self.assertEqual(opener, f'"{exe}" open -- "%1"')  # the space in the path is quoted
        runner = values[(install_windows.RUN_KEY, install_windows.RUN_NAME)]
        self.assertTrue(runner.startswith(f'"{exe}" run --log '))
        self.assertNotIn("python", runner.lower())


class SelfCheckTests(unittest.TestCase):
    def test_windows_checks_comtypes_and_generated_uia(self):
        loaded = []
        init = Mock()
        runtime.selfcheck(load=loaded.append, windows=True, initialize=init)
        init.assert_called_once()
        self.assertIn("comtypes.client", loaded)
        self.assertIn("comtypes.gen.UIAutomationClient", loaded)

    def test_reports_each_module_that_fails_to_import(self):
        def load(name):
            if name == "pystray":
                raise ImportError("No module named pystray")
        problems = runtime.selfcheck(("os", "pystray"), load)
        self.assertEqual([p for p in problems if p.startswith("pystray")],
                         ["pystray: ImportError: No module named pystray"])
        self.assertFalse([p for p in problems if p.startswith("os")])

    def test_tcl_and_webp_failures_are_reported(self):
        fake = SimpleNamespace(Tcl=lambda: (_ for _ in ()).throw(RuntimeError("no tcl")))
        with patch.dict(sys.modules, {"tkinter": fake}):
            self.assertIn("tkinter: RuntimeError: no tcl", runtime.selfcheck((), lambda n: None))
        from PIL import features
        with patch.dict(sys.modules, {"tkinter": SimpleNamespace(Tcl=lambda: Mock())}), \
                patch.object(features, "check", return_value=False):
            self.assertEqual(runtime.selfcheck((), lambda n: None), ["Pillow was built without WebP"])
        with patch.dict(sys.modules, {"tkinter": SimpleNamespace(Tcl=lambda: Mock())}), \
                patch.object(features, "check", side_effect=RuntimeError("no pillow")):
            self.assertEqual(runtime.selfcheck((), lambda n: None), ["Pillow: RuntimeError: no pillow"])

    def test_cli_exit_status_follows_the_problems(self):
        for problems, code, text in (([], 0, "OK"), (["x: broken"], 1, "x: broken")):
            with patch("partyline_helper.runtime.selfcheck", return_value=problems), \
                    contextlib.redirect_stdout(io.StringIO()) as out, \
                    self.assertRaises(SystemExit) as leaving:
                cli.main(["selfcheck"])
            self.assertEqual((leaving.exception.code, out.getvalue().strip()), (code, text))


class CliWindowsCommandsTests(unittest.TestCase):
    def test_stop_prints_the_outcome(self):
        with patch.object(links, "stop_helper", return_value=(True, "Stopped the helper (pid 1).")), \
                contextlib.redirect_stdout(io.StringIO()) as out:
            cli.main(["stop"])
        self.assertEqual(out.getvalue().strip(), "Stopped the helper (pid 1).")

    def test_a_failed_stop_exits_nonzero_and_says_why(self):
        stuck = (False, "The helper (pid 7) did not stop; end it in Task Manager.")
        with patch.object(links, "stop_helper", return_value=stuck), \
                patch("partyline_helper.consent_dialog.notify") as told, \
                patch("partyline_helper.consent_dialog.interactive", return_value=False), \
                contextlib.redirect_stdout(io.StringIO()), \
                self.assertRaises(SystemExit) as leaving:
            cli.main(["stop"])
        self.assertEqual(leaving.exception.code, 1)
        told.assert_called_once_with("Partyline Helper", stuck[1])  # a dialog without a terminal

    def test_a_restart_never_starts_a_second_helper_beside_one_that_will_not_stop(self):
        spawned = []
        with self.assertRaisesRegex(RuntimeError, "did not stop"):
            links.ensure_running(True, spawn=spawned.append, stop=lambda: (False, "it did not stop"),
                                 launch=lambda: ["x"],
                                 lock=lambda name: SimpleNamespace(holder=lambda: 9))
        self.assertEqual(spawned, [])

    def test_no_command_starts_the_helper(self):
        with patch("partyline_helper.runtime.start_helper", return_value="Started.") as starting, \
                contextlib.redirect_stdout(io.StringIO()):
            cli.main([])
        starting.assert_called_once_with(links.paired, links.ensure_running)

    def test_paired_follows_the_credentials(self):
        with patch.object(links, "load_config", return_value={}):
            self.assertTrue(links.paired())
        with patch.object(links, "load_config", side_effect=FileNotFoundError):
            self.assertFalse(links.paired())

    def test_the_hidden_dialog_command_exits_with_the_dialog_answer(self):
        with patch("partyline_helper.dialog_proc.main", return_value=0) as dialog, \
                self.assertRaises(SystemExit) as leaving:
            cli.main(["dialog", "REQUEST"])
        dialog.assert_called_once_with(["REQUEST"])
        self.assertEqual(leaving.exception.code, 0)

    def test_a_background_run_before_pairing_stays_quiet(self):
        with tempfile.TemporaryDirectory() as tmp, \
                patch.object(cli, "config_path", return_value=Path(tmp) / "missing.json"), \
                patch("partyline_helper.links.claim_run", return_value=True), \
                patch("partyline_helper.desktop.Desktop") as opening, \
                contextlib.redirect_stdout(io.StringIO()) as out:
            cli.main(["run", "--log", str(Path(tmp) / "helper.log")])
        opening.assert_not_called()
        self.assertIn("Not paired yet", out.getvalue())

    def test_run_wires_status_and_the_tray_on_windows_only(self):
        with patch("partyline_helper.desktop.Desktop", return_value=Mock(scale=1)), \
                patch.object(cli, "load_config", return_value={}), \
                patch("partyline_helper.terminal.Terminal"), \
                patch("partyline_helper.links.claim_run", return_value=True), \
                patch("partyline_helper.client.serve", new=AsyncMock()) as serving, \
                patch("partyline_helper.tray.start_tray") as starting, \
                patch.object(cli, "tray_wanted", return_value=True):
            cli.main(["run", "--no-border"])
        self.assertIsInstance(serving.call_args.kwargs["status"], Status)
        starting.assert_called_once_with(serving.call_args.kwargs["status"])
        starting.return_value.stop.assert_called_once_with()


class DetachedRunUsesDialogsTests(unittest.IsolatedAsyncioTestCase):
    """Greg's Windows test: a detached run has NUL as stdin, which looks like a tty, so consent went to an
    invisible y/N prompt in the log. Background runs now always use the native dialog."""

    def terminal_dialog(self, argv, terminal=True, frozen=False):
        config = Path(self.enterContext(tempfile.TemporaryDirectory())) / "config.json"
        config.write_text("{}")
        with patch("partyline_helper.desktop.Desktop", return_value=Mock(scale=1)), \
                patch.object(cli, "load_config", return_value={}), \
                patch.object(cli, "config_path", return_value=config), \
                patch("partyline_helper.terminal.Terminal") as building, \
                patch("partyline_helper.client.serve", new=Mock()), \
                patch.object(cli.asyncio, "run", side_effect=lambda work: work.close()), \
                patch("partyline_helper.links.claim_run", return_value=True), \
                patch("partyline_helper.consent_dialog.interactive", return_value=terminal), \
                patch.object(sys, "frozen", frozen, create=True), \
                contextlib.redirect_stdout(io.StringIO()):
            cli.main([*argv, "--no-border", "--no-tray"])
        return building.call_args.kwargs["dialog"]

    def test_a_detached_log_run_picks_the_dialog_even_though_stdin_looks_like_a_terminal(self):
        from partyline_helper import consent_dialog
        self.assertIs(self.terminal_dialog(["run", "--log", "helper.log"]), consent_dialog.confirm)

    def test_the_frozen_exe_always_picks_the_dialog(self):
        from partyline_helper import consent_dialog
        self.assertIs(self.terminal_dialog(["run"], frozen=True), consent_dialog.confirm)

    def test_a_run_from_a_real_terminal_keeps_the_prompt(self):
        self.assertIsNone(self.terminal_dialog(["run"]))
        from partyline_helper import consent_dialog
        self.assertIs(self.terminal_dialog(["run"], terminal=False), consent_dialog.confirm)

    async def test_control_consent_in_that_mode_asks_the_dialog_and_prints_no_prompt(self):
        from partyline_helper.terminal import Terminal
        asked = []

        async def dialog(title, message, timeout, sleep):
            asked.append((title, message))
            return True
        terminal = Terminal(read_stdin=False, dialog=dialog)
        with contextlib.redirect_stdout(io.StringIO()) as out:
            self.assertTrue(await terminal.ask("Allow agent control? [y/N] ", dialog=("Control", "Allow?")))
        self.assertEqual((asked, out.getvalue()), ([("Control", "Allow?")], ""))


if __name__ == "__main__":
    unittest.main()
