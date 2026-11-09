"""Windows UIA integration: a background window remains readable without focusing it."""
import asyncio
import json
import queue
import subprocess
import sys
import threading
import unittest
from types import SimpleNamespace
from unittest.mock import Mock


@unittest.skipUnless(sys.platform == "win32", "Windows UI Automation requires Windows")
class WindowsUIATests(unittest.TestCase):
    def test_background_tk_window(self):  # pragma: no cover - Windows CI
        import ctypes
        from ctypes import wintypes
        process = subprocess.Popen([sys.executable, "-u", "-m", "tests.windows_uia_window"],
                                   stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
        foreground_process = None
        lines = queue.Queue()
        threading.Thread(target=lambda: [lines.put(line) for line in process.stdout], daemon=True).start()
        try:
            try:
                ready = lines.get(timeout=20)
            except queue.Empty:
                self.fail("test window did not become ready")
            self.assertTrue(ready, "test window exited before reporting its controls")
            window = json.loads(ready)
            foreground_process = subprocess.Popen(
                [sys.executable, "-u", "-m", "tests.windows_uia_window", "--role", "foreground"],
                stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, text=True)
            foreground_lines = queue.Queue()
            threading.Thread(target=lambda: foreground_lines.put(foreground_process.stdout.readline()),
                             daemon=True).start()
            try:
                foreground_ready = foreground_lines.get(timeout=20)
            except queue.Empty:
                self.fail("foreground window did not become ready")
            self.assertTrue(foreground_ready, "foreground window exited before reporting its handle")
            foreground_window = json.loads(foreground_ready)
            self.assertTrue(foreground_window["hwnd"], "foreground fixture reported no window handle")
            self.assertNotEqual(window["pid"], foreground_window["pid"])
            from partyline_helper.uia_access import WindowAccess
            from partyline_helper.uia_window_identity import mark
            grant = {"hwnd": window["hwnd"], "pid": window["pid"], "title": "Partyline UIA target",
                     "process": "python.exe", "marker": mark(window["hwnd"])}
            self.assertTrue(grant["marker"])
            audit = SimpleNamespace(append=Mock(), ensure_writable=Mock())
            session = SimpleNamespace(status=SimpleNamespace(window_title=None, changed=Mock()),
                                      tools=SimpleNamespace(audit=audit),
                                      share={"share_id": "share"}, accepted=True, last_uia_frame=None,
                                      control=SimpleNamespace(granted=True))
            access = WindowAccess(session, picker=lambda: grant, list_windows=lambda: [grant],
                                  platform="win32")
            user32 = ctypes.windll.user32
            user32.GetForegroundWindow.restype = ctypes.c_void_p
            foreground = foreground_window["hwnd"]

            user32.GetCursorPos.argtypes = [ctypes.POINTER(wintypes.POINT)]

            def cursor():
                point = wintypes.POINT()
                self.assertTrue(user32.GetCursorPos(ctypes.byref(point)))
                return point.x, point.y

            def assert_foreground():
                actual = user32.GetForegroundWindow()
                detail = (f"target hwnd={window['hwnd']}, foreground fixture hwnd={foreground}, "
                          f"actual hwnd={actual}")
                self.assertNotEqual(window["hwnd"], actual, detail)
                self.assertEqual(foreground, actual, detail)

            assert_foreground()

            async def capture():
                await access.choose()
                return await access.snapshot()
            result = asyncio.run(capture())
            self.assertIn("elements", result, result)
            for expected in window["bounds"]:
                matches = (all(abs(a - b) <= 3 for a, b in zip(item["bounds"], expected, strict=True))
                           for item in result["elements"])
                self.assertTrue(any(matches), (expected, result))
            assert_foreground()
            # Read the same window in tiny parts: a first deep part, then per-parent resumed parts.
            import comtypes  # noqa: F401 - initialises COM for this thread
            from partyline_helper.uia_snapshot import snapshot as walk
            from partyline_helper.uia_windows import WindowsProvider
            part = walk(WindowsProvider(window["hwnd"], cached=True, deep=True), limit=2)
            self.assertTrue(part["truncated"], part)
            ids = [item["id"] for item in part["elements"]]
            while part.get("state"):
                part = walk(WindowsProvider(window["hwnd"], cached=True, deep=False), state=part["state"],
                            limit=2)
                ids += [item["id"] for item in part["elements"]]
            self.assertEqual([item["id"] for item in result["elements"]], ids)
            from partyline_helper.uia_action_worker import ActionWorker
            worker = ActionWorker(session)
            session.window = access
            targets = []
            for expected in window["bounds"]:
                targets.append(next(item for item in result["elements"]
                                    if all(abs(a - b) <= 3 for a, b in
                                           zip(item["bounds"], expected, strict=True))))
            async def act():
                answers = []
                actions = ((targets[1], "set_value", "new value"),
                           (targets[2], "toggle", None), (targets[0], "invoke", None))
                for item, action, value in actions:
                    before = user32.GetForegroundWindow()
                    pointer = cursor()
                    message = {"element_id": item["id"], "action": action, "value": value,
                               "share_id": "share", "agent": "test"}
                    answer = await worker.perform(message)
                    after = user32.GetForegroundWindow()
                    self.assertEqual(pointer, cursor(), f"{action} moved the cursor")
                    self.assertIsInstance(answer.get("foreground_changed"), bool, (action, answer))
                    self.assertIsInstance(answer.get("target_came_forward"), bool, (action, answer))
                    if answer.get("target_came_forward"):
                        self.assertEqual(window["hwnd"], after, (action, before, after, answer))
                    if before == after:
                        self.assertFalse(answer.get("foreground_changed"), (action, before, after, answer))
                    elif not answer.get("foreground_changed"):
                        print(f"{action}: test saw a foreground change outside helper samples", flush=True)
                    if action == "set_value":
                        print(f"SetValue foreground changed: {answer.get('foreground_changed')}", flush=True)
                    answers.append(answer)
                return answers
            answers = asyncio.run(act())
            self.assertTrue(all(item["status"] == "completed" for item in answers), answers)
            entries = [str(call) for call in session.tools.audit.append.call_args_list]
            self.assertTrue(any("value_length" in entry for entry in entries))
            self.assertTrue(all("new value" not in entry for entry in entries))
            process.stdin.write("report\n")
            process.stdin.flush()
            report = json.loads(lines.get(timeout=20))
            self.assertEqual({"clicked": 1, "value": "new value", "checked": 1},
                             {key: report[key] for key in ("clicked", "value", "checked")})
            from tests.windows_uia_patterns import Driver
            asyncio.run(Driver(self, worker, access, window, process, lines).run())
            access.revoke()
        finally:
            for child in (foreground_process, process):
                if child is None:
                    continue
                if child.poll() is None:
                    child.terminate()
                try:
                    child.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    child.kill()
                    child.wait(timeout=10)
                if child.stdin:
                    child.stdin.close()
                child.stdout.close()
