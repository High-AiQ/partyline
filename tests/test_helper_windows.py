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
from tests.screen_helper_fakes import FakeDesktop, FakeTerminal, request, serve


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
        self.wait = patch.object(stopping, "wait_pid", return_value=True).start()
        self.addCleanup(patch.stopall)

    def stop(self, holders):
        FakeLock.holders = holders
        return stopping.stop_helper(FakeLock, lambda pid, sig: self.kills.append((pid, sig)),
                                    self.path)

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
        self.assertEqual(self.naps, [])
        self.wait.assert_called_once_with(4242, timeout=5)

    def test_an_old_helper_that_ignores_the_file_is_ended_by_pid(self):
        self.wait.side_effect = [False, True]
        stopped, text = self.stop([4242])
        self.assertTrue(stopped)
        self.assertIn("ending the process", text)
        self.assertEqual(self.kills, [(4242, signal.SIGTERM)])
        self.assertFalse(self.path.exists())  # nobody will read it now

    def test_a_helper_that_survives_everything_is_reported(self):
        self.wait.return_value = False
        stopped, text = self.stop([4242])
        self.assertFalse(stopped)
        self.assertIn("Task Manager", text)

    def test_a_kill_that_is_denied_is_not_fatal(self):
        self.wait.return_value = False
        FakeLock.holders = [4242]

        def deny(pid, sig):
            raise PermissionError
        self.assertFalse(stopping.stop_helper(FakeLock, deny, self.path)[0])


class WatchStopTests(unittest.IsolatedAsyncioTestCase):
    async def test_the_stop_file_cancels_the_helper_and_is_consumed(self):
        with tempfile.TemporaryDirectory() as tmp:
            path, cancelled = Path(tmp) / "run.stop", []
            entered, created = asyncio.Event(), asyncio.Event()

            class Events:
                def __init__(self, *args):
                    pass

                async def __aenter__(self):
                    return self

                async def __aexit__(self, *args):
                    pass

                async def wait(self):
                    entered.set()
                    await created.wait()

            with patch.object(stopping, 'FileEvents', Events):
                watching = asyncio.create_task(stopping.watch_stop(lambda: cancelled.append(1), path))
                await entered.wait()
                self.assertEqual(cancelled, [])
                path.write_text("stop")
                created.set()
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

    def run_detached(self, setup=None):
        self.running = True
        if setup:
            setup(self)

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
        label, stop, stop_all, choose_window, end_tools, end_checks, quit_item = icon.menu
        self.assertEqual((stop.text, stop_all.text), ("Stop screen sharing", "Stop all sharing"))
        picked, revoked = [], []
        status.choose_window, status.stop_window = lambda: picked.append(1), lambda: revoked.append(1)
        choose_window.action()
        self.assertEqual(picked, [1])
        self.assertFalse(stop_all.enabled(None))
        status.window_title = "Editor"
        self.assertTrue(stop_all.enabled(None))
        stop_all.action()
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
        self.assertTrue(stop_all.enabled(None))
        self.assertEqual(label.text(None), "Sharing part of your screen")
        self.assertIn("Sharing", icon.title)
        stop.action()
        stop_all.action()
        quit_item.action()
        self.assertEqual((stops, quits, revoked), ([1, 1], [1], [1, 1]))
        self.assertEqual(icon.updates, 3)  # the post-start redraw, then paired and sharing
        status.attention("Answer me")
        self.assertEqual(icon.notified, [("Answer me", "Partyline Helper")])
        shown.stop()
        self.assertTrue(icon.stopped)
        shown.stop()  # idempotent

    def test_each_window_menu_stops_only_its_own_grant(self):
        status = Status()
        status.window_grants = {"first": "Editor → @builder «Dev»", "second": "Browser → @designer «Design»"}
        stopped = []
        status.stop_window_grant = stopped.append
        shown = tray.start_tray(status, FAKE_BACKEND)
        menu = shown.icon.menu
        windows = [item for item in menu if "→" in str(item.text)]
        self.assertEqual(2, len(windows))
        windows[0].action[0].action()
        windows[1].action[0].action()
        self.assertEqual(["first", "second"], stopped)
        status.window_grants = {"second": status.window_grants["second"]}
        status.changed()
        self.assertEqual(1, len([item for item in shown.icon.menu if "→" in str(item.text)]))
        shown.stop()

    def test_each_state_has_its_own_colour_and_a_tray_that_cannot_start_is_none(self):
        pixels = {state: tray.draw_icon(state).getpixel((32, 32)) for state in tray.COLORS}
        self.assertEqual(len(set(pixels.values())), 5)

        def broken(*a, **k):
            raise RuntimeError("no tray on this desktop")
        with contextlib.redirect_stdout(io.StringIO()):
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
        with contextlib.redirect_stdout(io.StringIO()):
            shown.notify("x")
            shown.stop()


class Win32LikeIcon(FakeIcon):
    """pystray's win32 Icon: a settable menu that is turned into a native menu only when update_menu
    runs (so it is a snapshot), and a tooltip of at most 128 characters that raises when longer, after
    pystray has already stored it."""

    def __init__(self, name, image, title, menu):
        self._menu, self._title, self.native, self.updates = None, title, [], 0
        super().__init__(name, image, title, menu)

    @property
    def menu(self):
        return self._menu

    @menu.setter
    def menu(self, value):
        self._menu = value
        self.update_menu()

    @property
    def title(self):
        return self._title

    @title.setter
    def title(self, value):
        if value != self._title:
            self._title = value
            if len(value.encode("utf-16-le")) // 2 > 128:
                raise ValueError("string too long (maximum length 128)")

    def update_menu(self):
        super().update_menu()
        self.native = list(self._menu or [])

    def clicked(self, text):
        entry = next(item for item in self.native if str(item.text) == text)
        return entry.action[0].action() if isinstance(entry.action, list) else entry.action()


class WindowStopInTheTrayTests(unittest.TestCase):
    """A person must be able to end a window share from the tray: the shared window's long title made
    pystray raise on the tooltip, which skipped the menu update until a later redraw happened to succeed."""

    def start(self):
        status = Status()
        status.stop_window_grant = lambda ident: self.revoke(status, ident)
        self.grants = {}
        shown = tray.start_tray(status, SimpleNamespace(Icon=Win32LikeIcon, Menu=FAKE_BACKEND.Menu,
                                                         MenuItem=FAKE_BACKEND.MenuItem))
        return status, shown

    def revoke(self, status, ident):
        self.grants.pop(ident, None)
        self.publish(status)

    def publish(self, status):
        status.window_grants = dict(self.grants)
        status.window_title = "; ".join(self.grants.values()) or None
        status.changed()

    def test_a_grant_with_a_long_title_shows_its_stop_and_stop_ends_it(self):
        status, shown = self.start()
        printed = io.StringIO()
        tab = "a very long browser tab title " * 4
        self.grants["w1"] = f"Partyline — {tab} → @opus5 «partyline dev»"
        with contextlib.redirect_stdout(printed):
            self.publish(status)
        icon = shown.icon
        windows = [str(item.text) for item in icon.native if "→" in str(item.text)]
        self.assertEqual(windows, [self.grants["w1"]])
        self.assertLessEqual(len(icon.title), 128)
        self.assertEqual(printed.getvalue(), "")  # nothing failed: the tooltip is cut to fit
        self.assertTrue(next(i for i in icon.native if i.text == "Stop all sharing").enabled(None))
        icon.clicked(self.grants["w1"])
        self.assertEqual(self.grants, {})
        self.assertEqual([i for i in icon.native if "→" in str(i.text)], [])
        self.assertFalse(next(i for i in icon.native if i.text == "Stop all sharing").enabled(None))

    def test_grants_revoked_elsewhere_leave_the_menu_and_stop_all_ends_everything(self):
        status, shown = self.start()
        stopped = []
        status.stop_share = lambda: stopped.append("screen")
        status.stop_window = lambda: stopped.append("windows")
        self.grants.update(a="A → @x «L»", b="B → @y «M»")
        self.publish(status)
        self.assertEqual(2, len([i for i in shown.icon.native if "→" in str(i.text)]))
        del self.grants["a"]  # the server or the web revoked it
        self.publish(status)
        self.assertEqual(["B → @y «M»"], [str(i.text) for i in shown.icon.native if "→" in str(i.text)])
        shown.icon.clicked("Stop all sharing")
        self.assertEqual(stopped, ["screen", "windows"])

    def test_a_failing_tray_step_is_logged_once_and_does_not_skip_the_others(self):
        status, shown = self.start()
        printed = io.StringIO()
        self.grants["w"] = "W → @x «L»"
        shown.icon.update_menu = Mock(side_effect=RuntimeError("no menu"))
        with contextlib.redirect_stdout(printed):
            self.publish(status)
            self.publish(status)
        self.assertEqual(1, printed.getvalue().count("Tray menu update failed"))
        self.assertEqual(shown.icon.icon.getpixel((32, 32)), tray.draw_icon("offline").getpixel((32, 32)))

    def test_the_tooltip_is_cut_in_utf16_units_without_splitting_an_emoji(self):
        self.assertEqual(tray.tooltip("short"), "short")
        for text in ("x" * 300, "Partyline Helper: " + "😀" * 120, "é" * 127 + "😀"):
            cut = tray.tooltip(text)
            self.assertLessEqual(tray.units(cut), 127)
            self.assertTrue(cut.endswith("…"))
            cut.encode("utf-16-le")  # a split surrogate pair would not encode
        status, shown = self.start()
        self.grants["w"] = "😀" * 120 + " → @x «L»"
        printed = io.StringIO()
        with contextlib.redirect_stdout(printed):
            self.publish(status)
        self.assertEqual("", printed.getvalue())
        self.assertLessEqual(tray.units(shown.icon.title), 128)

    def test_start_and_stop_failures_are_logged_and_never_end_the_helper(self):
        class Broken(FakeIcon):
            def run_detached(self, setup=None):
                raise RuntimeError("no shell")
        printed = io.StringIO()
        with contextlib.redirect_stdout(printed):
            self.assertIsNone(tray.start_tray(Status(), SimpleNamespace(
                Icon=Broken, Menu=FAKE_BACKEND.Menu, MenuItem=FAKE_BACKEND.MenuItem)))
            status, shown = self.start()
            shown.icon.stop = Mock(side_effect=RuntimeError("hung"))
            shown.stop()
            shown.stop()
        self.assertIn("Tray start failed", printed.getvalue())
        self.assertIn("no shell", printed.getvalue())
        self.assertEqual(1, printed.getvalue().count("Tray stop update failed"))


class StartupRaceTests(unittest.TestCase):
    """Greg's Windows 11 report: the helper paired but the tray stayed grey.

    A session thread calls `status.set("paired")` while the tray is still starting. These tests race it
    deliberately, with a fake pystray backend and an in-memory Status; no real time passes.
    """

    def backend(self, icon_type):
        return SimpleNamespace(Icon=icon_type, Menu=lambda *items: list(items),
                               MenuItem=lambda text, action, enabled=True: SimpleNamespace(
                                   text=text, action=action, enabled=enabled))

    def assert_paired(self, icon):
        self.assertEqual(icon.icon.getpixel((32, 32)), tray.draw_icon("paired").getpixel((32, 32)))
        self.assertEqual(icon.title, "Partyline Helper: Paired with Partyline")

    def test_pairing_while_the_icon_is_built_is_not_lost(self):
        status = Status()
        FakeIcon.instances = []

        class PairingIcon(FakeIcon):
            """The session pairs after the icon read its state but before the listener was listening."""

            def __init__(self, *args):
                super().__init__(*args)
                status.set("paired")

        shown = tray.start_tray(status, self.backend(PairingIcon))
        self.assertIsNotNone(shown)
        self.assert_paired(FakeIcon.instances[-1])

    def test_an_update_dropped_before_run_detached_is_redrawn(self):
        status = Status()
        FakeIcon.instances = []

        class NotReadyIcon(FakeIcon):
            """pystray on Windows drops icon and title updates until run_detached has set up the tray."""

            def __init__(self, *args):
                super().__init__(*args)
                self.ready = False

            def __setattr__(self, name, value):
                if (name in ("icon", "title") and "ready" in self.__dict__
                        and not self.ready):
                    return
                super().__setattr__(name, value)

            def run_detached(self, setup=None):
                status.set("paired")  # pairs just before pystray is ready: this redraw is dropped
                self.ready = True
                super().run_detached(setup)

        shown = tray.start_tray(status, self.backend(NotReadyIcon))
        self.assertIsNotNone(shown)
        self.assert_paired(FakeIcon.instances[-1])

    def test_a_pairing_while_the_icon_is_being_shown_is_drawn_once_it_is_visible(self):
        status = Status()
        FakeIcon.instances = []

        class ShowingIcon(FakeIcon):
            """pystray on Windows: showing adds the handle built from the image at that moment, a pairing
            can land inside that window, and only a visible icon redraws on an image change."""

            def __init__(self, *args):
                self.shown, self.image, self.drawn, self.setup = False, None, None, None
                super().__init__(*args)

            icon = property(lambda self: self.image, lambda self, image: self.set_image(image))

            def set_image(self, image):
                self.image = image
                if self.shown:
                    self.drawn = image

            visible = property(lambda self: self.shown, lambda self, value: self.show())

            def show(self):
                self.drawn = self.image
                status.set("paired")  # stored but not drawn: the icon is not visible yet
                self.shown = True

            def run_detached(self, setup=None):
                self.setup = setup  # pystray runs it on its own thread, later

        shown = tray.start_tray(status, self.backend(ShowingIcon))
        icon = FakeIcon.instances[-1]
        status.set("sharing")  # between construction and setup
        self.assertIsNone(icon.drawn)
        icon.setup(icon)
        colour = lambda image: image.getpixel((32, 32))  # noqa: E731
        self.assertEqual(colour(icon.drawn), colour(tray.draw_icon("paired")))
        shown.refresh("offline")  # a stale argument: the latest state wins
        self.assertEqual(colour(icon.drawn), colour(tray.draw_icon("paired")))
        status.set("control")
        self.assertEqual(colour(icon.drawn), colour(tray.draw_icon("control")))

    def test_the_normal_ordering_still_pairs_the_icon(self):
        status = Status()
        FakeIcon.instances = []
        shown = tray.start_tray(status, self.backend(FakeIcon))
        self.assertEqual(FakeIcon.instances[-1].icon.getpixel((32, 32)),
                         tray.draw_icon("offline").getpixel((32, 32)))
        status.set("paired")
        self.assert_paired(FakeIcon.instances[-1])
        self.assertEqual(shown.status.state, "paired")


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
