"""Native consent dialogs: fake backends, a manual clock, no real windows or time."""
import asyncio
import contextlib
import io
import json
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


class FakePopen:
    def __init__(self, command, returncode=0, **options):
        self.command, self.options, self.returncode, self.terminated = command, options, returncode, 0
        self.stdin = io.BytesIO()
        self.stdin.close = lambda: None
        self.running = True

    def wait(self):
        return self.returncode

    def poll(self):
        return None if self.running else self.returncode

    def terminate(self):
        self.terminated += 1


class ProcessDialogTests(unittest.TestCase):
    def start(self, **kwargs):
        made = []

        def popen(command, **options):
            made.append(FakePopen(command, **kwargs, **options))
            return made[0]
        return consent_dialog.ProcessDialog("Title", "Message ' $(x)", 12, popen), made[0]

    def test_dialog_runs_in_a_child_process_with_data_on_stdin_not_argv(self):
        handle, proc = self.start()
        self.assertEqual(proc.command, [sys.executable, "-m", "partyline_helper.dialog_proc"])
        self.assertNotIn("Message", " ".join(proc.command))
        self.assertTrue(proc.stdin.getvalue().endswith(b"\n"))
        self.assertEqual(json.loads(proc.stdin.getvalue()),
                         {"title": "Title", "message": "Message ' $(x)", "timeout": 12})
        self.assertNotIn("shell", proc.options)
        self.assertTrue(handle.wait())

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

    def test_close_releases_the_pipe_so_the_child_sees_eof(self):
        handle, proc = self.start()
        closed = []
        proc.stdin.close = lambda: closed.append(True)
        handle.close()
        self.assertEqual(closed, [True])

    def test_default_backend(self):
        with patch("partyline_helper.consent_dialog.importlib.util.find_spec", return_value=object()):
            self.assertIs(consent_dialog.default_backend(), consent_dialog.ProcessDialog)
        with patch("partyline_helper.consent_dialog.importlib.util.find_spec", return_value=None):
            self.assertIsNone(consent_dialog.default_backend())


class TkDialogProcessTests(unittest.TestCase):
    def fake_tk(self, press=None):
        root = SimpleNamespace(destroyed=0, scheduled=None)
        buttons = {}

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
            root.attributes = lambda *a: None
            root.protocol = lambda *a: None
            root.destroy = lambda: setattr(root, "destroyed", root.destroyed + 1)
            root.after = lambda ms, fn: setattr(root, "scheduled", ms)
            root.mainloop = lambda: press and buttons[press]()
            return root
        module = types.ModuleType("tkinter")
        module.Tk, module.Label, module.Frame, module.Button = tk, Widget, Widget, Button
        return module, root

    def test_buttons_answer_and_the_dialog_times_out_by_closing(self):
        for press, expected in (("Yes", True), ("No", False), (None, False)):
            module, root = self.fake_tk(press)
            with self.subTest(press=press), patch.dict(sys.modules, {"tkinter": module}):
                self.assertIs(dialog_proc.tk_ask("T", "M", 60), expected)
                self.assertEqual(root.scheduled, 60000)

    def test_main_maps_answers_to_exit_codes_and_failures_decline(self):
        module, _ = self.fake_tk("Yes")
        payload = json.dumps({"title": "T", "message": "M", "timeout": 5}) + "\n"
        watched = []
        with patch.dict(sys.modules, {"tkinter": module}):
            self.assertEqual(dialog_proc.main(io.StringIO(payload), watched.append), 0)
        self.assertEqual(len(watched), 1)
        module, _ = self.fake_tk("No")
        with patch.dict(sys.modules, {"tkinter": module}):
            self.assertEqual(dialog_proc.main(io.StringIO(payload), watched.append), 1)
        self.assertEqual(dialog_proc.main(io.StringIO("not json"), watched.append), 2)
        self.assertEqual(dialog_proc.main(io.StringIO("{}\n"), watched.append), 2)

    def test_stdin_eof_means_the_parent_is_gone_and_the_dialog_exits(self):
        exits = []
        dialog_proc.watch_parent(io.StringIO(""), exits.append).join()
        self.assertEqual(exits, [3])

        class Broken:
            def read(self):
                raise ValueError("closed")
        dialog_proc.watch_parent(Broken(), exits.append).join()
        self.assertEqual(exits, [3, 3])

    def test_a_real_child_dialog_exits_when_its_parent_closes_the_pipe(self):
        """A blocked dialog (fake Tk mainloop) must die when stdin closes, without any timer."""
        script = ("import sys, threading, types\n"
                  "tk = types.ModuleType('tkinter')\n"
                  "class W:\n"
                  "    def __init__(self, *a, **k): pass\n"
                  "    def pack(self, **k): pass\n"
                  "    def title(self, t): pass\n"
                  "    def attributes(self, *a): pass\n"
                  "    def protocol(self, *a): pass\n"
                  "    def destroy(self): pass\n"
                  "    def after(self, *a): pass\n"
                  "    def mainloop(self): threading.Event().wait()\n"
                  "tk.Tk = tk.Label = tk.Frame = tk.Button = W\n"
                  "sys.modules['tkinter'] = tk\n"
                  "from partyline_helper import dialog_proc\n"
                  "raise SystemExit(dialog_proc.main())\n")
        import subprocess
        child = subprocess.Popen([sys.executable, "-c", script], stdin=subprocess.PIPE,
                                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        child.stdin.write(json.dumps({"title": "T", "message": "M", "timeout": 3600}).encode() + b"\n")
        child.stdin.flush()
        self.assertIsNone(child.poll())
        child.stdin.close()  # what the OS does when the helper is SIGTERMed
        self.assertEqual(child.wait(timeout=30), 3)

    def test_without_tkinter_off_windows_the_answer_is_no(self):
        with patch.dict(sys.modules, {"tkinter": None}):
            self.assertFalse(dialog_proc.ask("T", "M", 1))

    def test_notify_never_raises(self):
        shown = []
        consent_dialog.notify("T", "M", lambda t, m: shown.append((t, m)))
        self.assertEqual(shown, [("T", "M")])

        def boom(*a):
            raise RuntimeError
        consent_dialog.notify("T", "M", boom)
        module, _ = self.fake_tk()
        module.messagebox = SimpleNamespace(showinfo=lambda *a, **k: shown.append("info"))
        module.__dict__["Tk"] = lambda: SimpleNamespace(withdraw=lambda: None, destroy=lambda: None)
        with patch.dict(sys.modules, {"tkinter": module, "tkinter.messagebox": module.messagebox}):
            consent_dialog.notify("T", "M")
        self.assertEqual(shown[-1], "info")


if __name__ == "__main__":
    unittest.main()
