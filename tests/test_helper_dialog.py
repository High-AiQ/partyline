"""Native consent dialogs: fake backends, a manual clock, no real windows or time."""
import asyncio
import base64
import contextlib
import io
import json
import os
import subprocess
import sys
import threading
import types
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from partyline_helper import consent_dialog, dialog_proc
from partyline_helper.terminal import Terminal
from tests.screen_helper_fakes import ManualTime, checkpoint, request


class FakeHandle:
    """A dialog handle: `wait` blocks until answered or closed, like a child process."""
    live = []

    def __init__(self, answer=None):
        self.answer, self.closed, self.done = answer, 0, threading.Event()
        FakeHandle.live.append(self)

    def wait(self):
        if self.answer is not None:
            return self.answer
        self.done.wait()
        return False if self.closed else bool(self.answer)

    def close(self):
        self.closed += 1
        self.done.set()


class DialogTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.clock = ManualTime()
        self.calls, FakeHandle.live = [], []

    def backend(self, answer=None, error=None):
        def start(title, message, timeout):
            self.calls.append((title, message, timeout))
            if error:
                raise error
            return FakeHandle(answer)
        return start

    async def run_confirm(self, backend, timeout=60):
        task = asyncio.create_task(consent_dialog.confirm("T", "M", timeout, backend, self.clock.sleep))
        self.assertEqual(await self.clock.sleep_calls.get(), 1)  # input guard
        self.clock.advance(1)
        return task

    async def test_yes_is_accepted_after_the_input_guard_and_the_window_is_closed(self):
        task = await self.run_confirm(self.backend(True))
        self.assertTrue(await task)
        self.assertEqual(self.calls, [("T", "M", 59)])
        self.assertEqual(FakeHandle.live[0].closed, 1)

    async def test_nothing_is_shown_during_the_input_guard(self):
        task = asyncio.create_task(consent_dialog.confirm("T", "M", 60, self.backend(True), self.clock.sleep))
        await self.clock.sleep_calls.get()
        await checkpoint()
        self.assertEqual(self.calls, [])
        self.clock.advance(1)
        self.assertTrue(await task)

    async def test_no_and_backend_errors_decline(self):
        for backend in (self.backend(False), self.backend(error=OSError("no display"))):
            self.clock = ManualTime()
            self.assertFalse(await (await self.run_confirm(backend)))

    async def test_silence_declines_at_the_timeout_and_closes_the_dialog(self):
        task = await self.run_confirm(self.backend())
        self.assertEqual(await self.clock.sleep_calls.get(), 59)
        self.clock.advance(59)
        self.assertFalse(await task)
        self.assertEqual(FakeHandle.live[0].closed, 1)

    async def test_cancelled_prompt_closes_its_dialog_so_prompts_never_overlap(self):
        first = await self.run_confirm(self.backend())
        await self.clock.sleep_calls.get()
        first.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await first
        self.assertEqual(FakeHandle.live[0].closed, 1)
        self.clock = ManualTime()
        second = await self.run_confirm(self.backend(True))
        self.assertTrue(await second)
        self.assertEqual([h.closed for h in FakeHandle.live], [1, 1])

    async def test_missing_backend_declines(self):
        with patch.object(consent_dialog, "default_backend", return_value=None):
            self.assertFalse(await consent_dialog.confirm("T", "M"))

    async def test_terminal_without_a_tty_uses_the_dialog_with_sanitised_text(self):
        seen = []

        async def dialog(title, text, timeout, sleep):
            seen.append((title, text, timeout))
            return True
        term = Terminal(clock=self.clock, sleep=self.clock.sleep, read_stdin=True, dialog=dialog)
        req = request()
        req.update(requested_by="\x1b[2JPerson", line_name="L")
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertTrue(await term.consent(req, timeout=60))
            self.assertTrue(await term.consent(req, yes=True))
        self.assertEqual(seen[0][2], 60)
        self.assertIn("Person asks to share part of your screen", seen[0][1])
        self.assertNotIn("\x1b", seen[0][1])
        self.assertEqual(len(seen), 1)

    async def test_terminal_dialog_decline_and_timeout_both_decline(self):
        async def declining(title, text, timeout, sleep):
            return False
        term = Terminal(clock=self.clock, sleep=self.clock.sleep, read_stdin=False, dialog=declining)
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertFalse(await term.consent(request()))
        silent = Terminal(clock=self.clock, sleep=self.clock.sleep, read_stdin=False,
                          dialog=lambda *a, **k: consent_dialog.confirm(
                              *a[:2], timeout=k["timeout"], backend=self.backend(), sleep=k["sleep"]))
        pending = asyncio.create_task(silent.consent(request(), timeout=60))
        await self.clock.sleep_calls.get()
        self.clock.advance(1)
        await self.clock.sleep_calls.get()
        self.clock.advance(59)
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertFalse(await pending)

    def test_interactive_and_auto_dialog(self):
        for stdin, expected in ((None, False), (SimpleNamespace(isatty=lambda: True), True),
                                (SimpleNamespace(isatty=lambda: False), False)):
            with patch.object(sys, "stdin", stdin):
                self.assertIs(consent_dialog.interactive(), expected)
                self.assertIs(consent_dialog.auto_dialog() is None, expected)

        def closed():
            raise ValueError("closed")
        with patch.object(sys, "stdin", SimpleNamespace(isatty=closed)):
            self.assertFalse(consent_dialog.interactive())

    def test_windows_nul_stdin_is_not_a_terminal(self):
        """A detached process gets NUL as stdin: a character device, so isatty() is True, nobody can type."""
        nul = SimpleNamespace(isatty=lambda: True)
        real_console = SimpleNamespace(isatty=lambda: True)
        console = lambda stream: stream is real_console  # noqa: E731 - fakes GetConsoleMode
        self.assertFalse(consent_dialog.interactive(nul, windows=True, console=console))
        self.assertTrue(consent_dialog.interactive(real_console, windows=True, console=console))
        self.assertFalse(consent_dialog.interactive(SimpleNamespace(isatty=lambda: False), windows=True,
                                                    console=lambda stream: True))  # a pipe
        self.assertTrue(consent_dialog.interactive(nul, windows=False, console=lambda stream: False))  # POSIX
        def broken(stream):
            raise OSError("no handle")
        self.assertFalse(consent_dialog.interactive(real_console, windows=True, console=broken))

    def test_a_background_run_always_uses_the_dialog(self):
        self.assertIs(consent_dialog.auto_dialog(True, terminal=lambda: True), consent_dialog.confirm)
        self.assertIs(consent_dialog.auto_dialog(True, terminal=lambda: False), consent_dialog.confirm)
        self.assertIsNone(consent_dialog.auto_dialog(False, terminal=lambda: True))
        self.assertIs(consent_dialog.auto_dialog(False, terminal=lambda: False), consent_dialog.confirm)


class FakePopen:
    def __init__(self, command, returncode=0, **options):
        self.command, self.options, self.returncode, self.terminated = command, options, returncode, 0
        self.running = True

    def wait(self):
        return self.returncode

    def poll(self):
        return None if self.running else self.returncode

    def terminate(self):
        self.terminated += 1


def decoded(command):
    return json.loads(base64.urlsafe_b64decode(command[-1]))


class ProcessDialogTests(unittest.TestCase):
    def start(self, kind="ask", **kwargs):
        made = []

        def popen(command, **options):
            made.append(FakePopen(command, **kwargs, **options))
            return made[0]
        return consent_dialog.ProcessDialog("Title", "Message ' $(x)", 12, popen, kind), made[0]

    def test_dialog_request_travels_in_argv_not_stdin_and_names_this_process(self):
        handle, proc = self.start()
        self.assertEqual(proc.command[:3], [sys.executable, "-m", "partyline_helper.dialog_proc"])
        self.assertEqual(decoded(proc.command), {"title": "Title", "message": "Message ' $(x)", "timeout": 12,
                                                 "kind": "ask", "parent": os.getpid()})
        self.assertIs(proc.options["stdin"], subprocess.DEVNULL)  # a windowed child may have no stdin
        self.assertNotIn("shell", proc.options)
        self.assertTrue(handle.wait())

    def test_frozen_exe_runs_its_own_dialog_subcommand(self):
        self.assertEqual(consent_dialog.dialog_command("req", frozen=True, executable="C:/h/Helper.exe"),
                         ["C:/h/Helper.exe", "dialog", "req"])
        with patch.object(sys, "frozen", True, create=True):
            self.assertEqual(consent_dialog.dialog_command("req", executable="x")[1], "dialog")

    def test_notices_use_the_info_kind(self):
        _, proc = self.start(kind="info")
        self.assertEqual(decoded(proc.command)["kind"], "info")

    def test_only_exit_status_zero_is_yes(self):
        for code, expected in ((0, True), (1, False), (2, False), (-15, False)):
            handle, _ = self.start(returncode=code)
            self.assertIs(handle.wait(), expected)

    def test_close_terminates_a_live_dialog_only(self):
        handle, proc = self.start()
        handle.close()
        self.assertEqual(proc.terminated, 1)
        proc.running = False
        handle.close()
        self.assertEqual(proc.terminated, 1)
        proc.running = True
        proc.terminate = lambda: (_ for _ in ()).throw(OSError("gone"))
        handle.close()

    def test_default_backend(self):
        with patch("partyline_helper.consent_dialog.importlib.util.find_spec", return_value=object()):
            self.assertIs(consent_dialog.default_backend(), consent_dialog.ProcessDialog)
        with patch("partyline_helper.consent_dialog.importlib.util.find_spec", return_value=None):
            self.assertIsNone(consent_dialog.default_backend())


class TkDialogProcessTests(unittest.TestCase):
    def fake_tk(self, press=None):
        root = SimpleNamespace(destroyed=0, scheduled=[], buttons={})
        buttons = root.buttons

        class Widget:
            def __init__(self, *a, **k):
                pass

            def pack(self, **k):
                pass

        class Button(Widget):
            def __init__(self, parent, **k):
                buttons[k["text"]] = k["command"]

        def tk():
            root.title = lambda t: None
            root.protocol = lambda *a: None
            root.destroy = lambda: setattr(root, "destroyed", root.destroyed + 1)
            root.after = lambda ms, fn: root.scheduled.append(ms)
            root.mainloop = lambda: press and buttons[press]()
            for name in ("update_idletasks", "deiconify", "lift", "attributes", "focus_force", "geometry"):
                setattr(root, name, lambda *a: None)
            root.winfo_reqwidth = root.winfo_reqheight = root.winfo_screenwidth = lambda: 800
            root.winfo_screenheight = lambda: 600
            return root
        module = types.ModuleType("tkinter")
        module.Tk, module.Label, module.Frame, module.Button = tk, Widget, Widget, Button
        return module, root

    def test_buttons_answer_and_the_dialog_times_out_by_closing(self):
        for press, expected in (("Yes", True), ("No", False), (None, False)):
            module, root = self.fake_tk(press)
            with self.subTest(press=press), patch.dict(sys.modules, {"tkinter": module}):
                self.assertIs(dialog_proc.tk_ask("T", "M", 60), expected)
                self.assertIn(60000, root.scheduled)
                self.assertIn(0, root.scheduled)  # the raise-to-front attempt is queued

    def test_a_notice_has_a_single_ok_button(self):
        module, root = self.fake_tk("OK")
        with patch.dict(sys.modules, {"tkinter": module}):
            self.assertTrue(dialog_proc.tk_ask("T", "M", 5, "info"))
        self.assertEqual(list(root.buttons), ["OK"])

    def test_main_maps_answers_to_exit_codes_and_failures_decline(self):
        module, _ = self.fake_tk("Yes")
        request = dialog_proc.encode_request("T", "M", 5, parent=77)
        watched = []
        with patch.dict(sys.modules, {"tkinter": module}):
            self.assertEqual(dialog_proc.main([request], watched.append), 0)
        self.assertEqual(watched, [77])
        module, _ = self.fake_tk("No")
        with patch.dict(sys.modules, {"tkinter": module}):
            self.assertEqual(dialog_proc.main([request], watched.append), 1)
        module, _ = self.fake_tk("OK")
        with patch.dict(sys.modules, {"tkinter": module}):
            self.assertEqual(dialog_proc.main([dialog_proc.encode_request("T", "M", 5, "info", 77)],
                                              watched.append), 0)
        self.assertEqual(dialog_proc.main(["not base64 json"], watched.append), 2)
        self.assertEqual(dialog_proc.main([], watched.append), 2)
        self.assertEqual(dialog_proc.main([base64.urlsafe_b64encode(b"{}").decode()], watched.append), 2)

    def test_the_dialog_exits_when_the_helper_that_opened_it_is_gone(self):
        exits = []
        dialog_proc.watch_parent(77, exits.append, lambda pid: None).join()
        self.assertEqual(exits, [3])

        def broken(pid):
            raise OSError("no such process")
        dialog_proc.watch_parent(77, exits.append, broken).join()
        self.assertEqual(exits, [3])  # a parent we cannot watch must not make the dialog vanish

    def test_waiting_for_a_parent_uses_a_native_process_exit_event(self):
        with patch('partyline.process_events.wait_pid') as wait:
            dialog_proc.process_gone(77)
        wait.assert_called_once_with(77)

    def test_without_tkinter_off_windows_the_answer_is_no(self):
        with patch.dict(sys.modules, {"tkinter": None}):
            self.assertFalse(dialog_proc.ask("T", "M", 1))

    def test_notify_never_raises_and_shows_a_notice_dialog(self):
        shown = []
        consent_dialog.notify("T", "M", lambda t, m: shown.append((t, m)))
        self.assertEqual(shown, [("T", "M")])

        def boom(*a):
            raise RuntimeError
        consent_dialog.notify("T", "M", boom)
        made = []

        class Fake:
            def __init__(self, title, message, timeout, kind):
                made.append((title, message, kind))

            def wait(self):
                made.append("waited")
        with patch.object(consent_dialog, "ProcessDialog", Fake):
            consent_dialog.notify("T", "M")
        self.assertEqual(made, [("T", "M", "info"), "waited"])


if __name__ == "__main__":
    unittest.main()
